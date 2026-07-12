#!/usr/bin/env python3
"""Fail PRs that introduce npm versions younger than the cooldown window."""

import argparse
import concurrent.futures
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
LOCKFILES = (
    "plugins/commentable-html/dev/package-lock.json",
    "tests/site/package-lock.json",
)
REQUEST_TIMEOUT_SECONDS = 10
REQUEST_RETRIES = 3
MAX_WORKERS = 8
_ZERO_SHA = "0" * 40


@dataclass(frozen=True, order=True)
class DependencyVersion:
    name: str
    version: str


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


def parse_lockfile_versions(lockfile, require_registry=True):
    versions = {}
    for key, entry in (lockfile or {}).get("packages", {}).items():
        if key == "" or not isinstance(entry, dict):
            continue
        version = entry.get("version")
        if not version or (require_registry and not _is_registry_npm(entry.get("resolved"))):
            continue
        name = _package_name_from_key(key)
        if name:
            versions[key.replace("\\", "/")] = DependencyVersion(name, str(version))
    return versions


def changed_dependency_versions(head_lockfile, base_lockfile):
    head_versions = parse_lockfile_versions(head_lockfile)
    base_versions = parse_lockfile_versions(base_lockfile, require_registry=False)
    changed = set()
    for key, head_dep in head_versions.items():
        base_dep = base_versions.get(key)
        if base_dep is None or base_dep.version != head_dep.version or base_dep.name != head_dep.name:
            changed.add(head_dep)
    return changed


def changed_pairs_from_git(base_ref, head_ref, event):
    if not base_ref or base_ref.startswith(_ZERO_SHA):
        print("check-dependency-cooldown: no base ref (new branch / first commit); skipping.")
        return set()
    if not ref_exists(base_ref):
        raise SystemExit(
            "check-dependency-cooldown: base ref %r is not a valid commit (fetch it, "
            "e.g. actions/checkout with fetch-depth: 0)." % base_ref
        )
    if not ref_exists(head_ref):
        raise SystemExit("check-dependency-cooldown: head ref %r is not a valid commit." % head_ref)
    if rev_parse(base_ref) == rev_parse(head_ref):
        print("check-dependency-cooldown: base and head resolve to the same commit; no changed npm versions.")
        return set()

    from_ref = base_ref if event == "push" else merge_base(base_ref, head_ref)
    changed = set()
    for path in LOCKFILES:
        head_lockfile = lockfile_at(head_ref, path)
        if head_lockfile is None:
            continue
        base_lockfile = lockfile_at(from_ref, path)
        changed.update(changed_dependency_versions(head_lockfile, base_lockfile))
    return changed


def parse_npm_time(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def fetch_publish_time(dep):
    package_url = "https://registry.npmjs.org/%s" % urllib.parse.quote(dep.name, safe="@")
    last_error = None
    for attempt in range(REQUEST_RETRIES):
        try:
            request = urllib.request.Request(package_url, headers={"User-Agent": "ai-marketplace-dependency-cooldown"})
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                packument = json.loads(response.read().decode("utf-8"))
            published = parse_npm_time(packument.get("time", {}).get(dep.version))
            if published is None:
                raise ValueError("packument has no parseable time[%s]" % dep.version)
            return dep, published, None
        except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError) as exc:
            last_error = exc
            if attempt + 1 < REQUEST_RETRIES:
                time.sleep(0.5 * (2 ** attempt))
    return dep, None, last_error


def fetch_publish_times(changed_pairs):
    publish_times = {}
    warnings = []
    if not changed_pairs:
        return publish_times, warnings
    workers = min(MAX_WORKERS, len(changed_pairs))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(fetch_publish_time, dep) for dep in sorted(changed_pairs)]
        for future in concurrent.futures.as_completed(futures):
            dep, published, error = future.result()
            if error is None:
                publish_times[dep] = published
            else:
                warnings.append(
                    "check-dependency-cooldown: WARNING - could not verify %s@%s from npm registry after %d attempts; "
                    "skipping this package (%s)."
                    % (dep.name, dep.version, REQUEST_RETRIES, error)
                )
    return publish_times, warnings


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

    changed = changed_pairs_from_git(args.base, args.head, args.event)
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
