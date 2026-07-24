#!/usr/bin/env python3
"""Fail if a newly added commentable-html feature-id row lacks a doc-surface + deck entry.

Governance (see AGENTS.md "Spec-and-test discipline" and the SPEC "Doc-surface coverage"
section): every NEW user-facing feature must, in the same pull request, declare TWO things in
the "Doc-surface registry" table of `plugins/commentable-html/dev/SPEC.md`:

- a `Doc surface`: where it is surfaced to readers - one or more of `tutorial`, `site`, `help`
  - OR `opt-out: <reason>` when it is not user-facing, and
- `Deck` coverage: `deck` when it is demonstrated on a showcase-deck slide, OR
  `opt-out: <reason>` when it genuinely does not warrant a slide.

This check diffs the SPEC between base and head, finds feature-id rows ADDED by the change
(ids present at head but not at base), and requires each to have a valid registry entry. It
also fails if a registry row names an id that no longer exists (a stale entry) or carries an
invalid surface / deck value. Legacy ids that predate this mechanism are never "new", so they
are not forced to carry an entry - the gate is forward-looking and lightweight.

A feature-id row is a spec table row whose first cell is a feature id and which has at least
three cells (`Feature id | Behavior | Covering tests`). Registry rows are the feature-id rows
under the "Doc-surface registry" heading (`Feature id | Doc surface | Deck`); parsing is
anchored on that heading so the two never collide regardless of column count.

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
_REGISTRY_HEADING_RE = re.compile(r"^#{1,6}\s+Doc-surface registry\s*$", re.IGNORECASE)
_HEADING_RE = re.compile(r"^#{1,6}\s")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")


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


def _split_registry(spec_text):
    """Split *spec_text* lines into (registry_lines, other_lines).

    Registry lines are those UNDER the "Doc-surface registry" heading, up to the next heading
    of any level or end-of-file. The heading line itself stays in *other_lines*. Anchoring the
    registry on its heading (rather than on a column count) lets registry rows carry any number
    of columns without being mistaken for main feature rows, and vice versa. Lines inside a
    fenced code block, and the fence markers themselves, are DROPPED from both lists, so a `#`
    heading, a sample table row, or any other markup inside a code sample is never parsed as a
    heading, a feature row, or a registry entry. A fence opens with a run of ``` or ~~~ and
    closes only on the SAME delimiter character (CommonMark rule), so a `~~~` line inside a
    ```-fence (or vice versa) is literal content and does not toggle the fence.
    """
    registry_lines = []
    other_lines = []
    in_registry = False
    fence_char = None
    for line in spec_text.splitlines():
        m = _FENCE_RE.match(line)
        if m:
            char = m.group(1)[0]
            if fence_char is None:
                fence_char = char
            elif char == fence_char:
                fence_char = None
            continue
        if fence_char is not None:
            continue
        if _REGISTRY_HEADING_RE.match(line):
            in_registry = True
            other_lines.append(line)
            continue
        if in_registry and _HEADING_RE.match(line):
            in_registry = False
        (registry_lines if in_registry else other_lines).append(line)
    return registry_lines, other_lines


def has_registry_heading(spec_text):
    """True if *spec_text* has a 'Doc-surface registry' heading (outside a code fence)."""
    fence_char = None
    for line in spec_text.splitlines():
        m = _FENCE_RE.match(line)
        if m:
            char = m.group(1)[0]
            if fence_char is None:
                fence_char = char
            elif char == fence_char:
                fence_char = None
            continue
        if fence_char is None and _REGISTRY_HEADING_RE.match(line):
            return True
    return False


def feature_ids(spec_text):
    """Feature ids named by MAIN feature rows (>= 3 cells, feature-id first), OUTSIDE the
    registry section (so a multi-column registry row is never counted as a feature)."""
    _registry_lines, other_lines = _split_registry(spec_text)
    ids = set()
    for line in other_lines:
        cells = _row_cells(line)
        if cells and len(cells) >= 3 and _is_feature_id(cells[0]):
            ids.add(cells[0].strip())
    return ids


def registry_entries(spec_text):
    """List of (id, doc-surface, deck) for every REGISTRY row under the registry heading.

    A registry row is a feature-id table row in the registry section. The deck cell is "" when
    the row is missing its third column, which `evaluate` reports as an invalid (empty) value.
    """
    registry_lines, _other_lines = _split_registry(spec_text)
    entries = []
    for line in registry_lines:
        cells = _row_cells(line)
        if cells and len(cells) >= 2 and _is_feature_id(cells[0]):
            doc = cells[1].strip()
            deck = cells[2].strip() if len(cells) >= 3 else ""
            entries.append((cells[0].strip(), doc, deck))
    return entries


def registry(spec_text):
    """Map feature id -> (doc-surface, deck) raw values from REGISTRY rows."""
    mapping = {}
    for fid, doc, deck in registry_entries(spec_text):
        mapping[fid] = (doc, deck)
    return mapping


def _opt_out_error(v):
    """Classify *v* as an opt-out declaration.

    Returns (is_opt_out, error): if *v* is (or attempts to be) an `opt-out: <reason>`, returns
    (True, error-or-None); otherwise (False, None) so the caller can parse it as something else.
    A token that merely starts with the letters "opt-out" without a word boundary (e.g. a typo
    like "opt-outage") is NOT treated as an opt-out attempt.
    """
    if re.match(r"opt-out\b", v, re.IGNORECASE):
        if not v.lower().startswith("opt-out:"):
            return True, "opt-out must be written `opt-out: <reason>` (a colon then a reason)"
        if not any(ch.isalnum() for ch in v[len("opt-out:"):]):
            return True, "opt-out needs a reason (use `opt-out: <reason>`)"
        return True, None
    return False, None


def surface_value_error(value):
    """Return an error string if *value* is not a valid doc-surface declaration, else None.

    Valid forms: a comma-separated list of surfaces (each of tutorial/site/help, no empty
    element) OR `opt-out: <reason>` (a colon then a non-empty reason).
    """
    v = value.strip()
    if not v:
        return "empty value"
    is_opt_out, err = _opt_out_error(v)
    if is_opt_out:
        return err
    parts = [t.strip() for t in v.split(",")]
    if any(p == "" for p in parts):
        return "malformed surface list (empty element - remove a trailing or doubled comma)"
    bad = [p for p in parts if p.lower() not in _SURFACES]
    if bad:
        return "unknown surface(s) %s (use tutorial/site/help or `opt-out: <reason>`)" % ", ".join(sorted(set(bad)))
    return None


def deck_value_error(value):
    """Return an error string if *value* is not a valid deck-coverage declaration, else None.

    Valid forms: the literal `deck` (the feature is demonstrated on a showcase-deck slide) OR
    `opt-out: <reason>` (a colon then a non-empty reason for having no slide).
    """
    v = value.strip()
    if not v:
        return "empty value"
    is_opt_out, err = _opt_out_error(v)
    if is_opt_out:
        return err
    if v.lower() == "deck":
        return None
    return "deck coverage must be `deck` (shown on a showcase-deck slide) or `opt-out: <reason>`"


def spec_text_at(ref):
    r = _git("show", "%s:%s" % (ref, SPEC_REL))
    if r.returncode != 0:
        return None
    return r.stdout.replace("\r\n", "\n").replace("\r", "\n")


def evaluate(head_spec, base_spec):
    """Return a list of failure messages (empty means the doc-surface + deck rule is satisfied).

    When *base_spec* is None (no usable base ref) only the registry's internal consistency is
    checked - the newly-added-id gate is skipped, so every legacy id is not spuriously treated
    as new.
    """
    failures = []
    head_ids = feature_ids(head_spec)

    # Fail closed if the registry section is gone (renamed/removed heading): otherwise the
    # registry would silently parse as empty and the check would stop validating coverage.
    if not has_registry_heading(head_spec):
        return [
            "no 'Doc-surface registry' heading found in the spec; cannot validate doc-surface + "
            "deck coverage. Restore the '### Doc-surface registry' section (see the SPEC "
            "\"Doc-surface coverage\" section)."
        ]

    # 0. A feature id must not be declared twice in the registry (a silent overwrite hazard).
    reg = {}
    seen = set()
    for fid, doc, deck in registry_entries(head_spec):
        if fid in seen:
            failures.append("duplicate registry row for `%s` (declare each id once)." % fid)
        seen.add(fid)
        reg[fid] = (doc, deck)

    # 1. Every registry entry must name a real, current feature id and carry valid values in
    #    BOTH the doc-surface and deck columns.
    for fid in sorted(reg):
        doc, deck = reg[fid]
        if fid not in head_ids:
            failures.append("registry row for `%s` names an id with no feature row (stale entry)." % fid)
            continue
        derr = surface_value_error(doc)
        if derr:
            failures.append("registry row for `%s` doc-surface: %s" % (fid, derr))
        kerr = deck_value_error(deck)
        if kerr:
            failures.append("registry row for `%s` deck: %s" % (fid, kerr))

    # 2. Every NEWLY ADDED feature id must have a registry entry.
    if base_spec is not None:
        base_ids = feature_ids(base_spec)
        for fid in sorted(head_ids - base_ids):
            if fid not in reg:
                failures.append(
                    "new feature id `%s` has no Doc-surface registry entry. Add a row to the "
                    "\"Doc-surface registry\" table naming a doc surface (tutorial/site/help or "
                    "`opt-out: <reason>`) AND deck coverage (`deck` or `opt-out: <reason>`)." % fid
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
    print("check-doc-surfaces OK (every new feature id declares a doc surface and deck coverage or opt-out).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
