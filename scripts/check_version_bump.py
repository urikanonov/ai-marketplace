#!/usr/bin/env python3
"""Fail if a plugin's shipped source changed without a version bump.

For every plugin in the marketplace manifest, if any file under the plugin's
registered `source` path (at the base or the head) changed between the base and
head refs, or the `source` path itself changed, the plugin's version at head
must be strictly greater than at base. Plugins whose source did not change, and
plugins that are newly introduced (absent at base), are skipped. Changes to a
plugin's CHANGELOG.md alone never require a bump - a changelog documents a
release, it is not itself a shipped change.

The diff is computed from the MERGE BASE of base..head so a PR is judged only on
its own changes, not on unrelated commits the base branch gained after the fork.
The version is compared against the base ref's manifest, so a bump must exceed
whatever is currently on the target branch.

Usage:
  python scripts/check_version_bump.py [--base <ref>] [--head <ref>]

Defaults: --base origin/main (or $BUMP_BASE_REF), --head HEAD (or $BUMP_HEAD_REF).
In CI, pass the PR base sha (or the push "before" sha) as --base and the head
sha as --head.
"""

import argparse
import json
import os
import posixpath
import subprocess
import sys

MANIFEST = ".github/plugin/marketplace.json"
_ZERO_SHA = "0" * 40
_EXEMPT_BASENAMES = {"CHANGELOG.md"}


def _git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True)


def semver(v):
    parts = str(v).strip().split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise ValueError("not a semver: %r" % v)
    return tuple(int(p) for p in parts)


def ref_exists(ref):
    return _git("rev-parse", "--verify", "--quiet", "%s^{commit}" % ref).returncode == 0


def merge_base(base, head):
    r = _git("merge-base", base, head)
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else base


def changed_files(from_ref, to_ref):
    r = _git("diff", "--name-only", from_ref, to_ref)
    if r.returncode != 0:
        raise SystemExit("check-version-bump: git diff %s %s failed: %s"
                         % (from_ref, to_ref, r.stderr.strip()))
    return [line.strip().replace("\\", "/") for line in r.stdout.splitlines() if line.strip()]


def manifest_at(ref):
    r = _git("show", "%s:%s" % (ref, MANIFEST))
    if r.returncode != 0:
        return None
    return json.loads(r.stdout)


def _entries(manifest):
    return {p["name"]: p for p in (manifest.get("plugins", []) if manifest else [])}


def _norm_source(source):
    """Normalize a manifest source path to a repo-relative posix prefix (no leading ./)."""
    s = str(source).replace("\\", "/")
    if s.startswith("./"):
        s = s[2:]
    s = posixpath.normpath(s)
    return "" if s == "." else s.rstrip("/")


def source_touched(source, files):
    src = _norm_source(source)
    for f in files:
        if os.path.basename(f) in _EXEMPT_BASENAMES:
            continue
        if src == "":
            return True
        if f == src or f.startswith(src + "/"):
            return True
    return False


def evaluate(head_manifest, base_manifest, files):
    """Return a list of failure messages (empty means the bump rule is satisfied)."""
    failures = []
    base_by_name = _entries(base_manifest)
    for name, entry in _entries(head_manifest).items():
        if name not in base_by_name:
            continue  # newly introduced plugin: nothing to bump against
        base_entry = base_by_name[name]
        head_source = entry.get("source", "")
        base_source = base_entry.get("source", "")
        source_changed = _norm_source(head_source) != _norm_source(base_source)
        touched = source_touched(head_source, files) or source_touched(base_source, files)
        if not (source_changed or touched):
            continue
        head_v = entry.get("version")
        base_v = base_entry.get("version")
        try:
            if semver(head_v) <= semver(base_v):
                why = "source path changed" if source_changed else "shipped source changed"
                failures.append(
                    "%s: %s but version did not increase (base %s, head %s). Bump the version."
                    % (name, why, base_v, head_v))
        except ValueError as exc:
            failures.append("%s: %s" % (name, exc))
    return failures


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=os.environ.get("BUMP_BASE_REF", "origin/main"))
    parser.add_argument("--head", default=os.environ.get("BUMP_HEAD_REF", "HEAD"))
    args = parser.parse_args(argv)

    base, head = args.base, args.head
    if not base or base.startswith(_ZERO_SHA):
        print("check-version-bump: no base ref (new branch / first commit); skipping.")
        return 0
    if not ref_exists(base):
        raise SystemExit("check-version-bump: base ref %r is not a valid commit (fetch it, "
                         "e.g. actions/checkout with fetch-depth: 0)." % base)

    head_manifest = manifest_at(head)
    if head_manifest is None:
        raise SystemExit("check-version-bump: could not read %s at %s" % (MANIFEST, head))
    base_manifest = manifest_at(base)
    if base_manifest is None:
        print("check-version-bump: manifest absent at base %s (new manifest); skipping." % base)
        return 0

    files = changed_files(merge_base(base, head), head)
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
