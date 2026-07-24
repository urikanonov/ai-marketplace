#!/usr/bin/env python3
"""Fail if a newly added commentable-html feature-id row lacks a doc-surface entry.

Governance (see AGENTS.md "Spec-and-test discipline" and the SPEC "Doc-surface coverage"
section): every NEW user-facing feature must, in the same pull request, declare where it is
surfaced to users - one or more of `tutorial`, `site`, `help` - OR record an explicit
`opt-out: <reason>` when it is not user-facing. The declaration lives in the "Doc-surface
registry" table of `plugins/commentable-html/dev/SPEC.md`.

This check diffs the SPEC between base and head, finds feature-id rows ADDED by the change
(ids present at head but not at base), and requires each to have a valid registry entry. It
also fails if a registry row names an id that no longer exists (a stale entry) or carries an
invalid surface value. Legacy ids that predate this mechanism are never "new", so they are not
forced to carry an entry - the gate is forward-looking and lightweight.

A feature-id row is a spec table row whose first cell is a feature id and which has at least
three cells (`Feature id | Behavior | Covering tests`). A registry row is a two-cell table row
whose first cell is a feature id (`Feature id | Doc surface`), so the two never collide.

Diff scoping by event mirrors check_version_bump.py:
- pull_request: diff from the MERGE BASE of base..head.
- push: diff exactly base..head.

Usage:
  python scripts/check_doc_surfaces.py [--base <ref>] [--head <ref>] [--event <name>]

Defaults: --base $DOCS_BASE_REF or origin/main; --head $DOCS_HEAD_REF or HEAD;
--event $DOCS_EVENT or pull_request.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC_REL = "plugins/commentable-html/dev/SPEC.md"
SPEC_PATH = REPO_ROOT / "plugins" / "commentable-html" / "dev" / "SPEC.md"
_ZERO_SHA = "0" * 40
_FEATURE_ID_RE = re.compile(r"[A-Z][A-Z0-9]+(?:-[A-Z0-9]+)*-\d+[a-z]?")
_SURFACES = frozenset({"tutorial", "site", "help"})


def _git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True)


def ref_exists(ref):
    return _git("rev-parse", "--verify", "--quiet", "%s^{commit}" % ref).returncode == 0


def merge_base(base, head):
    r = _git("merge-base", base, head)
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip()
    sys.stderr.write(
        "check-doc-surfaces: WARNING - git merge-base %s %s failed (%s); diffing from base "
        "directly. Ensure fetch-depth: 0.\n" % (base, head, r.stderr.strip())
    )
    return base


def _row_cells(line):
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return None
    cells = [cell.strip() for cell in stripped.strip("|").split("|")]
    if not cells:
        return None
    if cells[0].lower() in {"feature id", "feature", "area"}:
        return None
    if all(set(cell) <= {"-", ":", " "} for cell in cells):
        return None
    return cells


def _is_feature_id(text):
    return bool(_FEATURE_ID_RE.fullmatch(text.strip()))


def feature_ids(spec_text):
    """Feature ids named by MAIN feature rows (>= 3 cells with a feature-id first cell)."""
    ids = set()
    for line in spec_text.splitlines():
        cells = _row_cells(line)
        if cells and len(cells) >= 3 and _is_feature_id(cells[0]):
            ids.add(cells[0].strip())
    return ids


def registry_entries(spec_text):
    """List of (id, raw value) for every REGISTRY row (exactly 2 cells, feature-id first)."""
    entries = []
    for line in spec_text.splitlines():
        cells = _row_cells(line)
        if cells and len(cells) == 2 and _is_feature_id(cells[0]):
            entries.append((cells[0].strip(), cells[1].strip()))
    return entries


def registry(spec_text):
    """Map feature id -> raw doc-surface value from REGISTRY rows (exactly 2 cells)."""
    mapping = {}
    for line in spec_text.splitlines():
        cells = _row_cells(line)
        if cells and len(cells) == 2 and _is_feature_id(cells[0]):
            mapping[cells[0].strip()] = cells[1].strip()
    return mapping


def surface_value_error(value):
    """Return an error string if *value* is not a valid doc-surface declaration, else None.

    Valid forms: a comma-separated list of surfaces (each of tutorial/site/help, no empty
    element) OR `opt-out: <reason>` (a colon then a non-empty reason).
    """
    v = value.strip()
    if not v:
        return "empty value"
    # An `opt-out` attempt is `opt-out` followed by a word boundary (so `opt-outage` is not
    # mistaken for one); it must use the exact `opt-out: <reason>` form.
    if re.match(r"opt-out\b", v, re.IGNORECASE):
        if not v.lower().startswith("opt-out:"):
            return "opt-out must be written `opt-out: <reason>` (a colon then a reason)"
        if not any(ch.isalnum() for ch in v[len("opt-out:"):]):
            return "opt-out needs a reason (use `opt-out: <reason>`)"
        return None
    parts = [t.strip() for t in v.split(",")]
    if any(p == "" for p in parts):
        return "malformed surface list (empty element - remove a trailing or doubled comma)"
    bad = [p for p in parts if p.lower() not in _SURFACES]
    if bad:
        return "unknown surface(s) %s (use tutorial/site/help or `opt-out: <reason>`)" % ", ".join(sorted(set(bad)))
    return None


def spec_text_at(ref):
    r = _git("show", "%s:%s" % (ref, SPEC_REL))
    if r.returncode != 0:
        return None
    return r.stdout.replace("\r\n", "\n").replace("\r", "\n")


def evaluate(head_spec, base_spec):
    """Return a list of failure messages (empty means the doc-surface rule is satisfied).

    When *base_spec* is None (no usable base ref) only the registry's internal consistency is
    checked - the newly-added-id gate is skipped, so every legacy id is not spuriously treated
    as new.
    """
    failures = []
    head_ids = feature_ids(head_spec)
    reg = registry(head_spec)

    # 0. A feature id must not be declared twice in the registry (a silent overwrite hazard).
    seen = set()
    for fid, _value in registry_entries(head_spec):
        if fid in seen:
            failures.append("duplicate registry row for `%s` (declare each id once)." % fid)
        seen.add(fid)

    # 1. Every registry entry must name a real, current feature id and carry a valid value.
    for fid, value in sorted(reg.items()):
        if fid not in head_ids:
            failures.append("registry row for `%s` names an id with no feature row (stale entry)." % fid)
            continue
        err = surface_value_error(value)
        if err:
            failures.append("registry row for `%s`: %s" % (fid, err))

    # 2. Every NEWLY ADDED feature id must have a registry entry.
    if base_spec is not None:
        base_ids = feature_ids(base_spec)
        for fid in sorted(head_ids - base_ids):
            if fid not in reg:
                failures.append(
                    "new feature id `%s` has no Doc-surface registry entry. Add a row to the "
                    "\"Doc-surface registry\" table naming a surface (tutorial/site/help) or an "
                    "`opt-out: <reason>`." % fid
                )
    return failures


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=os.environ.get("DOCS_BASE_REF", "origin/main"))
    parser.add_argument("--head", default=os.environ.get("DOCS_HEAD_REF", "HEAD"))
    parser.add_argument("--event", default=os.environ.get("DOCS_EVENT", "pull_request"))
    args = parser.parse_args(argv)

    if not SPEC_PATH.is_file():
        print("check-doc-surfaces: %s not found; skipping." % SPEC_REL)
        return 0
    head_spec = spec_text_at(args.head)
    if head_spec is None:
        head_spec = SPEC_PATH.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")

    base = args.base
    base_spec = None
    if base and not base.startswith(_ZERO_SHA) and ref_exists(base):
        from_ref = base if args.event == "push" else merge_base(base, args.head)
        base_spec = spec_text_at(from_ref)
        if base_spec is None:
            print("check-doc-surfaces: SPEC absent at base %s (new spec); checking registry only." % from_ref)
    else:
        print("check-doc-surfaces: no usable base ref; checking registry consistency only.")

    failures = evaluate(head_spec, base_spec)
    if failures:
        sys.stderr.write("check-doc-surfaces FAILED:\n")
        for f in failures:
            sys.stderr.write("  - " + f + "\n")
        return 1
    print("check-doc-surfaces OK (every new feature id declares a doc surface or opt-out).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
