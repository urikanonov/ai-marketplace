#!/usr/bin/env python3
"""Fail if a plugin's shipped source changed without a version bump.

For every plugin in the marketplace manifest, if any file under the plugin's
registered `source` path changed between a base ref and a head ref, the plugin's
version at head must be strictly greater than at base. Plugins whose source did
not change, and plugins that are newly introduced (absent at base), are skipped.

Usage:
  python scripts/check_version_bump.py [--base <ref>] [--head <ref>]

Defaults: --base origin/main, --head HEAD. In CI, pass the PR base sha (or the
push "before" sha) as --base and the head sha as --head.
"""

import argparse
import json
import os
import subprocess
import sys

MANIFEST = os.path.join(".github", "plugin", "marketplace.json")
_ZERO_SHA = "0000000000000000000000000000000000000000"


def _git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True)


def semver(v):
    parts = str(v).strip().split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise ValueError("not a semver: %r" % v)
    return tuple(int(p) for p in parts)


def changed_files(base, head):
    r = _git("diff", "--name-only", base, head)
    if r.returncode != 0:
        raise SystemExit("check-version-bump: git diff %s..%s failed: %s" % (base, head, r.stderr.strip()))
    return [line.strip().replace("\\", "/") for line in r.stdout.splitlines() if line.strip()]


def manifest_at(ref):
    r = _git("show", "%s:%s" % (ref, MANIFEST.replace("\\", "/")))
    if r.returncode != 0:
        return None
    return json.loads(r.stdout)


def _versions_by_name(manifest):
    return {p["name"]: p for p in (manifest.get("plugins", []) if manifest else [])}


def source_touched(source, files):
    src = source.lstrip("./").rstrip("/").replace("\\", "/")
    return any(f == src or f.startswith(src + "/") for f in files)


def evaluate(head_manifest, base_manifest, files):
    """Return a list of failure messages (empty means the bump rule is satisfied)."""
    failures = []
    base_by_name = _versions_by_name(base_manifest)
    for entry in head_manifest.get("plugins", []):
        name = entry["name"]
        source = entry.get("source", "")
        if not source_touched(source, files):
            continue
        if name not in base_by_name:
            continue  # newly introduced plugin: nothing to bump against
        head_v = entry.get("version")
        base_v = base_by_name[name].get("version")
        try:
            if semver(head_v) <= semver(base_v):
                failures.append(
                    "%s: source under '%s' changed but version did not increase (base %s, head %s). "
                    "Bump the version." % (name, source.lstrip('./'), base_v, head_v))
        except ValueError as exc:
            failures.append("%s: %s" % (name, exc))
    return failures


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=os.environ.get("BUMP_BASE_REF", "origin/main"))
    parser.add_argument("--head", default=os.environ.get("BUMP_HEAD_REF", "HEAD"))
    args = parser.parse_args(argv)

    if not args.base or args.base.startswith(_ZERO_SHA):
        print("check-version-bump: no base ref (new branch / first commit); skipping.")
        return 0

    head_manifest = manifest_at(args.head)
    if head_manifest is None:
        raise SystemExit("check-version-bump: could not read %s at %s" % (MANIFEST, args.head))
    base_manifest = manifest_at(args.base)
    if base_manifest is None:
        print("check-version-bump: manifest absent at base %s; skipping." % args.base)
        return 0

    files = changed_files(args.base, args.head)
    failures = evaluate(head_manifest, base_manifest, files)
    if failures:
        sys.stderr.write("check-version-bump FAILED:\n")
        for f in failures:
            sys.stderr.write("  - " + f + "\n")
        return 1
    print("check-version-bump OK (every changed plugin had a version bump).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
