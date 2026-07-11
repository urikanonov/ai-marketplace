#!/usr/bin/env python3
"""Fail if a plugin's shipped source changed without a version bump.

For every plugin in the marketplace manifest, if any file under the plugin's
registered `source` path changed between base and head, or the `source` path
itself changed, the plugin's version at head must be strictly greater than at
base. Plugins whose source did not change, and plugins newly introduced (absent
at base), are skipped. A change to the plugin's own `<source>/CHANGELOG.md`
never requires a bump - a changelog documents a release, it is not a shipped
change.

Diff scoping by event:
- pull_request: diff from the MERGE BASE of base..head, so a PR is judged only
  on its own changes (not commits the base branch gained after the fork).
- push: diff exactly base..head (the push's before..after), so a rollback /
  non-fast-forward push is judged on exactly what it changed.
Renames are split into an add + a delete (--no-renames) so a file moved OUT of a
source path still registers as a change to that source.

Usage:
  python scripts/check_version_bump.py [--base <ref>] [--head <ref>] [--event <name>]

Defaults: --base $BUMP_BASE_REF or origin/main; --head $BUMP_HEAD_REF or HEAD;
--event $BUMP_EVENT or pull_request.
"""

import argparse
import json
import os
import posixpath
import re
import subprocess
import sys

MANIFEST = ".github/plugin/marketplace.json"
_ZERO_SHA = "0" * 40
_SEMVER = re.compile(
    r"^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$"
)


def _git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True)


def semver(v):
    match = _SEMVER.fullmatch(str(v).strip())
    if match is None:
        raise ValueError("not a semver: %r" % v)
    major, minor, patch = (int(part) for part in match.group(1, 2, 3))
    prerelease = match.group(4)
    if prerelease is None:
        return major, minor, patch, 1, ()
    identifiers = tuple(
        (0, int(part)) if part.isdigit() else (1, part)
        for part in prerelease.split(".")
    )
    return major, minor, patch, 0, identifiers


def ref_exists(ref):
    return _git("rev-parse", "--verify", "--quiet", "%s^{commit}" % ref).returncode == 0


def merge_base(base, head):
    r = _git("merge-base", base, head)
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip()
    sys.stderr.write("check-version-bump: WARNING - git merge-base %s %s failed (%s); "
                     "diffing from base directly. Ensure fetch-depth: 0.\n"
                     % (base, head, r.stderr.strip()))
    return base


def changed_files(from_ref, to_ref):
    # --no-renames: a rename is reported as both a delete (old path) and an add
    # (new path), so moving a file out of a source path is not hidden.
    r = _git("diff", "--no-renames", "--name-only", from_ref, to_ref)
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
    """Normalize a manifest source to a repo-relative posix prefix (no leading ./)."""
    s = str(source).replace("\\", "/")
    if s.startswith("./"):
        s = s[2:]
    s = posixpath.normpath(s)
    return "" if s == "." else s.rstrip("/")


def source_touched(source, files):
    """True if any changed file lives under *source*, ignoring the plugin's own
    top-level CHANGELOG.md (a changelog does not itself require a bump)."""
    src = _norm_source(source)
    changelog = posixpath.join(src, "CHANGELOG.md") if src else "CHANGELOG.md"
    for f in files:
        if f == changelog:
            continue
        if src == "" or f == src or f.startswith(src + "/"):
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
        source_changed = _norm_source(entry.get("source", "")) != _norm_source(base_entry.get("source", ""))
        # When the source path is unchanged it equals the base source, so a single
        # source_touched check covers it; when it changed, source_changed forces
        # evaluation regardless of which files moved.
        if not (source_changed or source_touched(entry.get("source", ""), files)):
            continue
        try:
            if semver(entry.get("version")) <= semver(base_entry.get("version")):
                why = "source path changed" if source_changed else "shipped source changed"
                failures.append(
                    "%s: %s but version did not increase (base %s, head %s). Bump the version."
                    % (name, why, base_entry.get("version"), entry.get("version")))
        except ValueError as exc:
            failures.append("%s: %s" % (name, exc))
    return failures


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=os.environ.get("BUMP_BASE_REF", "origin/main"))
    parser.add_argument("--head", default=os.environ.get("BUMP_HEAD_REF", "HEAD"))
    parser.add_argument("--event", default=os.environ.get("BUMP_EVENT", "pull_request"))
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

    # A PR is judged on its own changes (merge base); a push is judged on exactly
    # what it moved (before..after), so a rollback cannot slip through an empty
    # merge-base diff.
    from_ref = base if args.event == "push" else merge_base(base, head)
    files = changed_files(from_ref, head)
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
