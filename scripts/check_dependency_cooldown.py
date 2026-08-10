#!/usr/bin/env python3
"""Fail PRs that introduce npm versions younger than the cooldown window.

This gate mirrors the `cooldown: default-days: 14` setting in `.github/dependabot.yml`, which
Dependabot applies to VERSION updates only: it deliberately bypasses cooldown for a SECURITY
update, because holding a published fix for two weeks is the opposite of what an advisory calls
for. So the gate exempts a bump that closes an open Dependabot alert; without that it reds exactly
the pull requests that must land fastest, and a guard that has to be ignored to do the right thing
trains everyone to ignore it (issue #1252).

The exemption is resolved from the PUBLIC GitHub Advisory Database (`GET /advisories`) rather than
from this repository's `dependabot/alerts` endpoint, which needs a token carrying the
`security_events` (or classic `repo`) scope. No `GITHUB_TOKEN` workflow permission grants that
(`security-events` covers CODE SCANNING alerts only), and handing this job a PAT would mean a
`secrets.*` reference in a `pull_request` workflow that runs PR-authored code - which RULE B of
`scripts/check_workflow_policy.py` forbids. The advisory database answers the same question from
data that needs no credential: a Dependabot alert is open precisely when the version the lockfile
currently pins matches an advisory's `vulnerable_version_range`, and the bump closes that alert
precisely when the new version leaves the range at or above `first_patched_version`. Set
`GITHUB_TOKEN` in the environment to lift the unauthenticated rate limit; nothing requires it.

Every lookup fails OPEN: an unreachable, rate-limited, unauthorized, or malformed response yields
no exemptions and a warning, so the gate keeps its previous behavior instead of blocking a PR.
"""

import argparse
import concurrent.futures
import glob
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath

COOLDOWN_DAYS = 14
LOCKFILE_PATTERNS = (
    "plugins/*/dev/package-lock.json",
    "site/tests/package-lock.json",
)
REQUEST_TIMEOUT_SECONDS = 10
REQUEST_RETRIES = 3
MAX_WORKERS = 8
GLOBAL_DEADLINE_SECONDS = 60
ADVISORY_API_URL = "https://api.github.com/advisories"
ADVISORY_PAGE_SIZE = 100
_ZERO_SHA = "0" * 40


@dataclass(frozen=True, order=True)
class DependencyVersion:
    name: str
    version: str


@dataclass(frozen=True)
class LockfileDependency:
    name: str
    version: str
    resolved: str
    registry: bool


@dataclass(frozen=True)
class CooldownViolation:
    name: str
    version: str
    published_at: datetime
    age_days: float
    threshold_days: int


@dataclass(frozen=True)
class SecurityExemption:
    name: str
    version: str
    from_version: str
    ghsa_id: str


@dataclass
class LockfileDiff:
    """Changed head versions, the base versions they replace, and any policy warnings."""

    changed: set = field(default_factory=set)
    warnings: list = field(default_factory=list)
    base_versions: dict = field(default_factory=dict)

    def merge(self, other):
        self.changed.update(other.changed)
        self.warnings.extend(other.warnings)
        for name, versions in other.base_versions.items():
            self.base_versions.setdefault(name, set()).update(versions)
        return self


def _git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True)


def ref_exists(ref):
    return _git("rev-parse", "--verify", "--quiet", "%s^{commit}" % ref).returncode == 0


def rev_parse(ref):
    result = _git("rev-parse", "--verify", "--quiet", "%s^{commit}" % ref)
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def merge_base(base, head):
    result = _git("merge-base", base, head)
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    sys.stderr.write(
        "check-dependency-cooldown: WARNING - git merge-base %s %s failed (%s); "
        "diffing from base directly. Ensure fetch-depth: 0.\n"
        % (base, head, result.stderr.strip())
    )
    return base


def lockfile_at(ref, path):
    result = _git("show", "%s:%s" % (ref, path))
    if result.returncode == 0:
        return json.loads(result.stdout)
    stderr = result.stderr.lower()
    if "does not exist in" in stderr or "exists on disk, but not in" in stderr:
        return None
    raise SystemExit(
        "check-dependency-cooldown: git show %s:%s failed: %s"
        % (ref, path, result.stderr.strip())
    )


def discover_lockfiles(root="."):
    found = set()
    for pattern in LOCKFILE_PATTERNS:
        for path in glob.glob(os.path.join(root, pattern.replace("/", os.sep))):
            if os.path.isfile(path):
                found.add(os.path.relpath(path, root).replace(os.sep, "/"))
    return tuple(sorted(found))


def _package_name_from_key(key):
    parts = PurePosixPath(key.replace("\\", "/")).parts
    if "node_modules" not in parts:
        return None
    idx = len(parts) - 1 - parts[::-1].index("node_modules")
    if idx + 1 >= len(parts):
        return None
    first = parts[idx + 1]
    if first.startswith("@"):
        if idx + 2 >= len(parts):
            return None
        return first + "/" + parts[idx + 2]
    return first


def _is_registry_npm(resolved):
    if not resolved:
        return False
    try:
        return urllib.parse.urlparse(str(resolved)).netloc.lower() == "registry.npmjs.org"
    except ValueError:
        return False


def _package_name_from_entry(key, entry):
    name = entry.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return _package_name_from_key(key)


def parse_lockfile_dependencies(lockfile):
    deps = set()
    for key, entry in (lockfile or {}).get("packages", {}).items():
        if key == "" or not isinstance(entry, dict):
            continue
        version = entry.get("version")
        if not version:
            continue
        name = _package_name_from_entry(key, entry)
        if name:
            resolved = str(entry.get("resolved") or "")
            deps.add(LockfileDependency(name, str(version), resolved, _is_registry_npm(resolved)))
    return deps


def parse_lockfile_versions(lockfile, require_registry=True):
    versions = set()
    for dep in parse_lockfile_dependencies(lockfile):
        if require_registry and not dep.registry:
            continue
        versions.add(DependencyVersion(dep.name, dep.version))
    return versions


def _non_registry_warning(dep):
    source = dep.resolved or "(no resolved URL)"
    return (
        "check-dependency-cooldown: WARNING - %s@%s is a changed npm dependency from a non-registry source "
        "(%s) and is not cooldown-checked."
        % (dep.name, dep.version, source)
    )


def lockfile_diff(head_lockfile, base_lockfile):
    head_deps = parse_lockfile_dependencies(head_lockfile)
    base_deps = parse_lockfile_dependencies(base_lockfile)
    base_versions = {}
    for base_dep in base_deps:
        base_versions.setdefault(base_dep.name, set()).add(base_dep.version)
    base_identities = {DependencyVersion(d.name, d.version) for d in base_deps}
    result = LockfileDiff(base_versions=base_versions)
    for head_dep in sorted(head_deps, key=lambda d: (d.name, d.version, d.resolved)):
        identity = DependencyVersion(head_dep.name, head_dep.version)
        if identity in base_identities:
            continue
        if head_dep.registry:
            result.changed.add(identity)
        else:
            result.warnings.append(_non_registry_warning(head_dep))
    result.warnings.sort()
    return result


def changed_dependency_versions(head_lockfile, base_lockfile, include_warnings=False):
    result = lockfile_diff(head_lockfile, base_lockfile)
    if include_warnings:
        return result.changed, result.warnings
    return result.changed


def diff_from_git(base_ref, head_ref, event):
    """Diff every discovered lockfile between base and head; empty when there is nothing to compare."""
    if not base_ref or base_ref.startswith(_ZERO_SHA):
        print("check-dependency-cooldown: no base ref (new branch / first commit); skipping.")
        return LockfileDiff()
    if not ref_exists(base_ref):
        raise SystemExit(
            "check-dependency-cooldown: base ref %r is not a valid commit (fetch it, "
            "e.g. actions/checkout with fetch-depth: 0)." % base_ref
        )
    if not ref_exists(head_ref):
        raise SystemExit("check-dependency-cooldown: head ref %r is not a valid commit." % head_ref)
    if rev_parse(base_ref) == rev_parse(head_ref):
        print("check-dependency-cooldown: base and head resolve to the same commit; no changed npm versions.")
        return LockfileDiff()

    from_ref = base_ref if event == "push" else merge_base(base_ref, head_ref)
    result = LockfileDiff()
    for path in discover_lockfiles():
        head_lockfile = lockfile_at(head_ref, path)
        if head_lockfile is None:
            continue
        base_lockfile = lockfile_at(from_ref, path)
        result.merge(lockfile_diff(head_lockfile, base_lockfile))
    result.warnings.sort()
    return result


def changed_pairs_from_git(base_ref, head_ref, event, include_warnings=False):
    result = diff_from_git(base_ref, head_ref, event)
    if include_warnings:
        return result.changed, result.warnings
    return result.changed


def parse_npm_time(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def fetch_publish_times_for_name(name, versions, deadline_at):
    package_url = "https://registry.npmjs.org/%s" % urllib.parse.quote(name, safe="@")
    last_error = None
    versions = sorted(set(str(v) for v in versions))
    for attempt in range(REQUEST_RETRIES):
        remaining = deadline_at - time.monotonic()
        if remaining <= 0:
            last_error = TimeoutError("global deadline exceeded")
            break
        try:
            request = urllib.request.Request(package_url, headers={"User-Agent": "ai-marketplace-dependency-cooldown"})
            with urllib.request.urlopen(request, timeout=min(REQUEST_TIMEOUT_SECONDS, max(0.1, remaining))) as response:
                packument = json.loads(response.read().decode("utf-8"))
            time_map = packument.get("time")
            if not isinstance(time_map, dict):
                raise ValueError("packument has no parseable time map")
            publish_times = {}
            warnings = []
            for version in versions:
                published = parse_npm_time(time_map.get(version))
                dep = DependencyVersion(name, version)
                if published is None:
                    warnings.append(
                        "check-dependency-cooldown: WARNING - could not verify %s@%s from npm registry after %d attempts; "
                        "skipping this package (packument has no parseable time[%s])."
                        % (name, version, REQUEST_RETRIES, version)
                    )
                else:
                    publish_times[dep] = published
            return publish_times, warnings
        except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError) as exc:
            last_error = exc
            if attempt + 1 < REQUEST_RETRIES:
                sleep_for = min(0.5 * (2 ** attempt), max(0, deadline_at - time.monotonic()))
                if sleep_for > 0:
                    time.sleep(sleep_for)
    return {}, [
        "check-dependency-cooldown: WARNING - could not verify %s@%s from npm registry after %d attempts; "
        "skipping this package (%s)."
        % (name, version, REQUEST_RETRIES, last_error)
        for version in versions
    ]


def fetch_publish_time(dep):
    times, warnings = fetch_publish_times_for_name(dep.name, [dep.version], time.monotonic() + GLOBAL_DEADLINE_SECONDS)
    return dep, times.get(dep), None if not warnings else ValueError(warnings[0])


def fetch_publish_times(changed_pairs):
    publish_times = {}
    warnings = []
    if not changed_pairs:
        return publish_times, sorted(warnings)
    grouped = {}
    for dep in sorted(changed_pairs):
        grouped.setdefault(dep.name, set()).add(dep.version)
    deadline_at = time.monotonic() + GLOBAL_DEADLINE_SECONDS
    workers = min(MAX_WORKERS, len(grouped))
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=workers)
    future_to_name = {}
    try:
        for name, versions in sorted(grouped.items()):
            future = executor.submit(fetch_publish_times_for_name, name, sorted(versions), deadline_at)
            future_to_name[future] = name
        pending = set(future_to_name)
        while pending:
            remaining = deadline_at - time.monotonic()
            if remaining <= 0:
                break
            done, pending = concurrent.futures.wait(
                pending,
                timeout=remaining,
                return_when=concurrent.futures.FIRST_COMPLETED,
            )
            for future in done:
                try:
                    found, found_warnings = future.result()
                    publish_times.update(found)
                    warnings.extend(found_warnings)
                except Exception as exc:
                    name = future_to_name[future]
                    for version in sorted(grouped[name]):
                        warnings.append(
                            "check-dependency-cooldown: WARNING - could not verify %s@%s from npm registry after %d attempts; "
                            "skipping this package (%s)."
                            % (name, version, REQUEST_RETRIES, exc)
                        )
        for future in pending:
            future.cancel()
            name = future_to_name[future]
            for version in sorted(grouped[name]):
                warnings.append(
                    "check-dependency-cooldown: WARNING - could not verify %s@%s from npm registry before the %d-second deadline; "
                    "skipping this package."
                    % (name, version, GLOBAL_DEADLINE_SECONDS)
                )
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    return publish_times, sorted(warnings)


_CONSTRAINT_RE = re.compile(r"^(<=|>=|<|>|=)?\s*([0-9][0-9A-Za-z.+-]*)$")


def _identifier_key(part):
    if part.isdigit():
        return (0, int(part), "")
    return (1, 0, part)


def version_sort_key(version):
    """Order versions the way semver does: release parts numerically, prerelease below release."""
    text = str(version or "").strip()
    if text[:1] in ("v", "V"):
        text = text[1:]
    text = text.split("+", 1)[0]
    core, _, prerelease = text.partition("-")
    release = []
    for chunk in core.split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        release.append(int(digits) if digits else 0)
    while len(release) < 3:
        release.append(0)
    if prerelease:
        return (tuple(release), 0, tuple(_identifier_key(p) for p in prerelease.split(".")))
    return (tuple(release), 1, ())


def compare_versions(left, right):
    left_key = version_sort_key(left)
    right_key = version_sort_key(right)
    if left_key < right_key:
        return -1
    return 1 if left_key > right_key else 0


def version_matches_range(range_text, version):
    """True when `version` satisfies a GitHub advisory `vulnerable_version_range`.

    Unrecognized syntax matches nothing, so an unparseable range never grants an exemption.
    """
    if not isinstance(range_text, str) or not range_text.strip():
        return False
    for raw in range_text.split(","):
        match = _CONSTRAINT_RE.match(raw.strip())
        if not match:
            return False
        operator, bound = match.group(1) or "=", match.group(2)
        order = compare_versions(version, bound)
        if operator == "<" and order >= 0:
            return False
        if operator == "<=" and order > 0:
            return False
        if operator == ">" and order <= 0:
            return False
        if operator == ">=" and order < 0:
            return False
        if operator == "=" and order != 0:
            return False
    return True


def first_patched_identifier(value):
    """Read `first_patched_version` from either API shape (advisory string, alert object)."""
    if isinstance(value, dict):
        value = value.get("identifier")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def advisory_exemption(name, version, base_versions, advisories):
    """Return the exemption for a bump that closes an open alert on `name`, else None.

    An alert is open when a base (currently locked) version sits inside an advisory's vulnerable
    range; the bump closes it when `version` leaves that range at or above the first patched
    version. Ties are broken by GHSA id so the reported exemption does not depend on API ordering.
    """
    matches = []
    for advisory in advisories or []:
        if not isinstance(advisory, dict):
            continue
        ghsa_id = str(advisory.get("ghsa_id") or "")
        for vulnerability in advisory.get("vulnerabilities") or []:
            if not isinstance(vulnerability, dict):
                continue
            package = vulnerability.get("package") or {}
            if str(package.get("name") or "").lower() != name.lower():
                continue
            if str(package.get("ecosystem") or "npm").lower() != "npm":
                continue
            vulnerable_range = vulnerability.get("vulnerable_version_range")
            if version_matches_range(vulnerable_range, version):
                continue
            patched = first_patched_identifier(vulnerability.get("first_patched_version"))
            if patched and compare_versions(version, patched) < 0:
                continue
            for base_version in sorted(base_versions or (), key=version_sort_key):
                if not version_matches_range(vulnerable_range, base_version):
                    continue
                if not patched and compare_versions(version, base_version) <= 0:
                    continue
                matches.append(SecurityExemption(name, version, base_version, ghsa_id))
                break
    if not matches:
        return None
    return sorted(matches, key=lambda m: (m.ghsa_id, version_sort_key(m.from_version)))[0]


def _advisory_warning(name, detail):
    return (
        "check-dependency-cooldown: WARNING - could not read GitHub security advisories for %s (%s); "
        "not exempting it from cooldown." % (name, detail)
    )


def fetch_advisories(name, deadline_at):
    """Fetch reviewed npm advisories affecting `name`. Any failure returns no advisories."""
    query = urllib.parse.urlencode(
        {"ecosystem": "npm", "affects": name, "per_page": ADVISORY_PAGE_SIZE, "type": "reviewed"}
    )
    url = "%s?%s" % (ADVISORY_API_URL, query)
    headers = {
        "User-Agent": "ai-marketplace-dependency-cooldown",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip()
    if token:
        headers["Authorization"] = "Bearer " + token
    last_error = None
    for attempt in range(REQUEST_RETRIES):
        remaining = deadline_at - time.monotonic()
        if remaining <= 0:
            last_error = TimeoutError("global deadline exceeded")
            break
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(
                request, timeout=min(REQUEST_TIMEOUT_SECONDS, max(0.1, remaining))
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, list):
                raise ValueError("advisory response is not a list")
            return payload, []
        except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError) as exc:
            last_error = exc
            if attempt + 1 < REQUEST_RETRIES:
                sleep_for = min(0.5 * (2 ** attempt), max(0, deadline_at - time.monotonic()))
                if sleep_for > 0:
                    time.sleep(sleep_for)
    return [], [_advisory_warning(name, last_error)]


def security_exemptions(changed_pairs, base_versions):
    """Map each changed version that patches an open alert to the exemption that covers it."""
    exemptions = {}
    warnings = []
    names = sorted({dep.name for dep in changed_pairs if base_versions.get(dep.name)})
    if not names:
        return exemptions, warnings
    deadline_at = time.monotonic() + GLOBAL_DEADLINE_SECONDS
    for name in names:
        advisories, name_warnings = fetch_advisories(name, deadline_at)
        warnings.extend(name_warnings)
        if not advisories:
            continue
        for dep in sorted(d for d in changed_pairs if d.name == name):
            exemption = advisory_exemption(name, dep.version, base_versions.get(name, set()), advisories)
            if exemption is not None:
                exemptions[dep] = exemption
    return exemptions, sorted(warnings)


def cooldown_violations(changed_pairs, publish_times, now, days, exemptions=None):
    """Return confirmed fresh-version violations. Missing publish times are skipped."""
    cutoff = now - timedelta(days=days)
    exemptions = exemptions or {}
    violations = []
    for dep in sorted(changed_pairs):
        if dep in exemptions:
            continue
        published = publish_times.get(dep)
        if published is None:
            continue
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        published = published.astimezone(timezone.utc)
        if published > cutoff:
            age_days = (now - published).total_seconds() / 86400
            violations.append(CooldownViolation(dep.name, dep.version, published, age_days, days))
    return violations


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=os.environ.get("COOLDOWN_BASE_REF", "origin/main"))
    parser.add_argument("--head", default=os.environ.get("COOLDOWN_HEAD_REF", "HEAD"))
    parser.add_argument("--event", default=os.environ.get("COOLDOWN_EVENT", "pull_request"))
    args = parser.parse_args(argv)

    diff = diff_from_git(args.base, args.head, args.event)
    changed = diff.changed
    for warning in diff.warnings:
        sys.stderr.write(warning + "\n")
    if not changed:
        print("check-dependency-cooldown OK (no added or bumped npm dependency versions).")
        return 0

    print("check-dependency-cooldown: checking %d changed npm dependency version(s)." % len(changed))
    exemptions, exemption_warnings = security_exemptions(changed, diff.base_versions)
    for warning in exemption_warnings:
        sys.stderr.write(warning + "\n")
    for dep in sorted(exemptions):
        exemption = exemptions[dep]
        print(
            "check-dependency-cooldown: exempting %s@%s (patches %s, open on %s@%s); "
            "Dependabot bypasses cooldown for security updates."
            % (
                exemption.name,
                exemption.version,
                exemption.ghsa_id or "a security advisory",
                exemption.name,
                exemption.from_version,
            )
        )

    publish_times, warnings = fetch_publish_times(changed)
    for warning in warnings:
        sys.stderr.write(warning + "\n")

    now = datetime.now(timezone.utc)
    violations = cooldown_violations(changed, publish_times, now, COOLDOWN_DAYS, exemptions)
    if violations:
        sys.stderr.write("check-dependency-cooldown FAILED:\n")
        for violation in violations:
            sys.stderr.write(
                "  - %s@%s was published at %s (age %.2f days, threshold %d days).\n"
                % (
                    violation.name,
                    violation.version,
                    violation.published_at.isoformat(),
                    violation.age_days,
                    violation.threshold_days,
                )
            )
        return 1

    print("check-dependency-cooldown OK (%d changed npm dependency version(s) met the %d-day cooldown or were skipped)." % (len(changed), COOLDOWN_DAYS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
