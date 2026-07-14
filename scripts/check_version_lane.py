#!/usr/bin/env python3
"""Advisory open-PR version-lane check for commentable-html.

History (finding 4.5): every shipped-source change bumps `plugins/commentable-html/dev/VERSION`,
and concurrent PRs repeatedly claimed the SAME version that a newer merge overtook (for example
#40 started at 1.6.0 but #30 merged 1.6.0 first, so #44 had to re-bump to 1.6.1). The required
`version-bump` gate already BLOCKS the real collision at merge time (it requires the shipped
version to be strictly greater than base `main`), so this check does not need to be a required
gate. Its job is to WARN early - at PR time - so the author picks a distinct lane up front and
avoids the re-bump churn.

Scope: the high-churn commentable-html `dev/VERSION`. A PR "claims a lane" only when its version
is strictly greater than base `main`'s version (i.e., it actually bumped). A lane conflict is when
the current PR's version is a duplicate of, or lower than, another open PR that also bumped - in
either case the two cannot both merge without a re-bump.

Live data (the versions of other open PRs) comes one of two ways, mirroring
`check_required_checks.py`:
  - the `VERSION_LANE_OTHERS` env var: a JSON array of {"number": N, "version": "x.y.z"}
    (used by the CI workflow, which pre-collects it, and by the unit tests); or
  - `gh` when run locally / when the env var is unset: list open PRs and read each head's
    `dev/VERSION`. A PR whose version cannot be read (a fork head not in this repo, a PR that
    does not touch the file) is skipped, not treated as a conflict.

Exit codes: 0 = clear, not bumping, or live data unavailable (advisory - do not block); 1 = a
lane conflict was found. Standard library only.
"""
import argparse
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION_PATH = "plugins/commentable-html/dev/VERSION"
DEFAULT_REPO = "urikanonov/ai-marketplace"
_SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def semver(value):
    match = _SEMVER.fullmatch(str(value).strip())
    if match is None:
        raise ValueError("not a MAJOR.MINOR.PATCH version: %r" % value)
    return tuple(int(part) for part in match.groups())


def parse_others_env(raw):
    """Parse VERSION_LANE_OTHERS (a JSON array) into a list of {number, version} dicts."""
    if not raw:
        return []
    data = json.loads(raw)
    out = []
    for item in data:
        out.append({"number": item["number"], "version": str(item["version"])})
    return out


def evaluate(current, base, others):
    """Return the list of other-PR dicts that conflict with *current*.

    A conflict exists only when the current PR claims a lane (current > base) and another open PR
    that also claimed a lane (its version > base) sits at a version >= current (duplicate or higher,
    so they cannot both merge without a re-bump). Others with an unparseable version are skipped.
    """
    try:
        cur = semver(current)
        base_v = semver(base)
    except ValueError:
        return []
    if cur <= base_v:  # current did not bump past base: not claiming a lane.
        return []
    conflicts = []
    for item in others:
        try:
            ver = semver(item["version"])
        except (ValueError, KeyError, TypeError):
            continue
        if ver <= base_v:  # this PR did not bump either: no lane, no conflict.
            continue
        if cur <= ver:  # duplicate of, or lower than, an open lane.
            conflicts.append(item)
    return conflicts


def suggested_next(conflicts):
    """A safe next version: patch-bump above the highest conflicting version."""
    highest = max(semver(c["version"]) for c in conflicts)
    return "%d.%d.%d" % (highest[0], highest[1], highest[2] + 1)


def _git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True, cwd=ROOT)


def _read_local_version():
    path = os.path.join(ROOT, VERSION_PATH.replace("/", os.sep))
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read().strip()


def _read_base_version(base_ref):
    r = _git("show", "%s:%s" % (base_ref, VERSION_PATH))
    if r.returncode != 0 or not r.stdout.strip():
        return None
    return r.stdout.strip()


def _gh(*args):
    try:
        return subprocess.run(["gh", *args], capture_output=True, text=True)
    except FileNotFoundError:
        return None


def _collect_others_from_gh(repo, self_number):
    """List open PRs and read each head's dev/VERSION via gh. Best-effort: a PR whose version
    cannot be read is skipped. Returns None if gh itself is unavailable/failed."""
    listed = _gh("pr", "list", "--repo", repo, "--state", "open", "--limit", "100",
                 "--json", "number,headRefOid")
    if listed is None or listed.returncode != 0 or not listed.stdout.strip():
        return None
    others = []
    for pr in json.loads(listed.stdout):
        number = pr.get("number")
        if number == self_number:
            continue
        sha = pr.get("headRefOid")
        if not sha:
            continue
        content = _gh("api", "repos/%s/contents/%s?ref=%s" % (repo, VERSION_PATH, sha),
                      "--jq", ".content")
        if content is None or content.returncode != 0 or not content.stdout.strip():
            continue
        import base64
        try:
            version = base64.b64decode(content.stdout.strip()).decode("utf-8").strip()
        except (ValueError, UnicodeDecodeError):
            continue
        others.append({"number": number, "version": version})
    return others


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=os.environ.get("VERSION_LANE_BASE", "origin/main"))
    parser.add_argument("--repo", default=os.environ.get("VERSION_LANE_REPO", DEFAULT_REPO))
    parser.add_argument("--self-number",
                        default=os.environ.get("VERSION_LANE_SELF", ""))
    args = parser.parse_args(argv)

    current = os.environ.get("VERSION_LANE_CURRENT")
    if not current:
        try:
            current = _read_local_version()
        except OSError as exc:
            print("check-version-lane: cannot read %s (%s); skipping." % (VERSION_PATH, exc))
            return 0

    base = os.environ.get("VERSION_LANE_BASE")
    if not base or base == "origin/main":
        base = _read_base_version(args.base)
    elif _SEMVER.fullmatch(base.strip()) is None:
        # base is a ref, not a literal version: resolve it.
        base = _read_base_version(base)
    if not base:
        print("check-version-lane: cannot determine base version (need git history or "
              "VERSION_LANE_BASE); skipping.")
        return 0

    others_raw = os.environ.get("VERSION_LANE_OTHERS")
    if others_raw is not None:
        others = parse_others_env(others_raw)
    else:
        self_number = int(args.self_number) if str(args.self_number).isdigit() else None
        others = _collect_others_from_gh(args.repo, self_number)
        if others is None:
            print("check-version-lane: could not list open PRs via gh (unavailable or no "
                  "access); skipping - this is an advisory early-warning check.")
            return 0

    conflicts = evaluate(current, base, others)
    if conflicts:
        sys.stderr.write(
            "check-version-lane: this PR's commentable-html version %s collides with another "
            "open PR's lane (base %s):\n" % (current, base))
        for c in sorted(conflicts, key=lambda c: c["number"]):
            sys.stderr.write("  - PR #%s already claims %s\n" % (c["number"], c["version"]))
        sys.stderr.write(
            "Pick a distinct, higher lane (for example %s) now to avoid a re-bump when the other "
            "PR merges first. This is advisory: the required version-bump gate still blocks the "
            "actual collision at merge time.\n" % suggested_next(conflicts))
        return 1
    print("check-version-lane OK (commentable-html %s does not collide with any open PR's lane)."
          % current)
    return 0


if __name__ == "__main__":
    sys.exit(main())
