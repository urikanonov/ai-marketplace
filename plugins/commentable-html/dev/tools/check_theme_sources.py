#!/usr/bin/env python3
"""Deck theme preset staleness / provenance gate (#336).

Each native deck theme preset under ``tools/deck/themes/*.theme.json`` records the frontend-slides
state it was adapted from: an ``adaptedFrom`` note (human provenance + credit) and a ``sourceCommit``
(the vendored frontend-slides commit it was reviewed against). This gate FAILS on an UNACKNOWLEDGED
upstream change so a vendor refresh cannot silently leave a preset behind:

- missing ``adaptedFrom`` or ``sourceCommit``       -> fail (unrecorded origin)
- ``sourceCommit`` != the currently vendored commit -> fail (upstream advanced; the preset has not
  been re-reviewed against it)

To acknowledge an upstream refresh - whether you re-ported the preset or decided no change is needed
("reviewed, no change") - set the preset's ``sourceCommit`` to the new vendored commit. That single
edit is the acknowledgement record the gate looks for. Run from the skill root or via ``--themes-dir``.
"""
import argparse
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent.parent / "pkg" / "skills" / "commentable-html"
DEFAULT_THEMES = SKILL / "tools" / "deck" / "themes"
DEFAULT_UPSTREAM = SKILL / "vendor" / "frontend-slides" / "UPSTREAM.md"


def vendored_commit(upstream=DEFAULT_UPSTREAM):
    """Return the frontend-slides commit currently vendored, or None if UPSTREAM.md lacks it."""
    m = re.search(r"Vendored commit:\s*`([0-9a-f]{7,40})`", Path(upstream).read_text(encoding="utf-8"))
    return m.group(1) if m else None


def check(themes_dir=DEFAULT_THEMES, upstream=DEFAULT_UPSTREAM):
    """Return a list of failure strings; empty means every preset is acknowledged and current."""
    errors = []
    commit = vendored_commit(upstream)
    if not commit:
        return ["could not determine the vendored frontend-slides commit from %s - expected a "
                "'Vendored commit: `<sha>`' line; cannot verify preset freshness" % upstream]
    for path in sorted(Path(themes_dir).glob("*.theme.json")):
        name = path.name
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append("%s: invalid JSON: %s" % (name, exc))
            continue
        if not str(data.get("adaptedFrom", "")).strip():
            errors.append("%s: missing 'adaptedFrom' provenance" % name)
        src = str(data.get("sourceCommit", "")).strip()
        if not src:
            errors.append("%s: missing 'sourceCommit' provenance" % name)
        elif src != commit:
            errors.append(
                "%s: sourceCommit %s does not match the vendored frontend-slides commit %s - "
                "an unacknowledged upstream change. Review the upstream diff, re-port the preset if "
                "the palette/type changed (dev/tools/fs_theme_convert.py), then set sourceCommit to "
                "%s to acknowledge ('reviewed, no change' is fine)."
                % (name, src[:12], commit[:12], commit[:12]))
    return errors


def main(argv=None):
    ap = argparse.ArgumentParser(description="Check deck theme preset provenance / freshness.")
    ap.add_argument("--themes-dir", default=str(DEFAULT_THEMES))
    ap.add_argument("--upstream", default=str(DEFAULT_UPSTREAM))
    args = ap.parse_args(argv)
    errors = check(args.themes_dir, args.upstream)
    if errors:
        for e in errors:
            print("check_theme_sources: %s" % e, file=sys.stderr)
        return 1
    print("check_theme_sources: OK (all presets acknowledge the current vendored commit)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
