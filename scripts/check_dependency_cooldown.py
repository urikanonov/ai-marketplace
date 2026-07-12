#!/usr/bin/env python3
"""Fail PRs that introduce npm versions younger than the cooldown window."""

import argparse
import concurrent.futures
import glob
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath

COOLDOWN_DAYS = 14
LOCKFILE_PATTERNS = (
    "plugins/*/dev/package-lock.json",
    "tests/site/package-lock.json",
)
REQUEST_TIMEOUT_SECONDS = 10
REQUEST_RETRIES = 3
MAX_WORKERS = 8
GLOBAL_DEADLINE_SECONDS = 60
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


def changed_dependency_versions(head_lockfile, base_lockfile, include_warnings=False):
    head_deps = parse_lockfile_dependencies(head_lockfile)
    base_versions = parse_lockfile_versions(base_lockfile, require_registry=False)
    changed = set()
    warnings = []
    for head_dep in sorted(head_deps, key=lambda d: (d.name, d.version, d.resolved)):
        identity = DependencyVersion(head_dep.name, head_dep.version)
        if identity in base_versions:
            continue
        if head_dep.registry:
            changed.add(identity)
        else:
            warnings.append(_non_registry_warning(head_dep))
    if include_warnings:
        return changed, sorted(warnings)
    return changed


def changed_pairs_from_git(base_ref, head_ref, event, include_warnings=False):
    if not base_ref or base_ref.startswith(_ZERO_SHA):
        print("check-dependency-cooldown: no base ref (new branch / first commit); skipping.")
        return (set(), []) if include_warnings else set()
    if not ref_exists(base_ref):
        raise SystemExit(
            "check-dependency-cooldown: base ref %r is not a valid commit (fetch it, "
            "e.g. actions/checkout with fetch-depth: 0)." % base_ref
        )
    if not ref_exists(head_ref):
        raise SystemExit("check-dependency-cooldown: head ref %r is not a valid commit." % head_ref)
    if rev_parse(base_ref) == rev_parse(head_ref):
        print("check-dependency-cooldown: base and head resolve to the same commit; no changed npm versions.")
        return (set(), []) if include_warnings else set()

    from_ref = base_ref if event == "push" else merge_base(base_ref, head_ref)
    changed = set()
    warnings = []
    for path in discover_lockfiles():
        head_lockfile = lockfile_at(head_ref, path)
        if head_lockfile is None:
            continue
        base_lockfile = lockfile_at(from_ref, path)
        path_changed, path_warnings = changed_dependency_versions(head_lockfile, base_lockfile, include_warnings=True)
        changed.update(path_changed)
        warnings.extend(path_warnings)
    if include_warnings:
        return changed, sorted(warnings)
    return changed


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


def cooldown_violations(changed_pairs, publish_times, now, days):
    """Return confirmed fresh-version violations. Missing publish times are skipped."""
    cutoff = now - timedelta(days=days)
    violations = []
    for dep in sorted(changed_pairs):
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

    changed, policy_warnings = changed_pairs_from_git(args.base, args.head, args.event, include_warnings=True)
    for warning in policy_warnings:
        sys.stderr.write(warning + "\n")
    if not changed:
        print("check-dependency-cooldown OK (no added or bumped npm dependency versions).")
        return 0

    print("check-dependency-cooldown: checking %d changed npm dependency version(s)." % len(changed))
    publish_times, warnings = fetch_publish_times(changed)
    for warning in warnings:
        sys.stderr.write(warning + "\n")

    now = datetime.now(timezone.utc)
    violations = cooldown_violations(changed, publish_times, now, COOLDOWN_DAYS)
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
