#!/usr/bin/env python3
"""Objective A/B evaluation harness for native deck theme presets (#335, CMH-DECK-THEME-05).

Native theme presets replaced per-deck hand-translation of frontend-slides templates. To gate adding
MORE presets on measurable quality (not eyeballing), this harness renders a fixed corpus of deck slide
fragments (dev/eval/corpus/*.html) under every shipped preset AND an unthemed baseline, using the real
`deck_scaffold` -> `deck_validate` path, and reports objective metrics per (theme, corpus) cell:

- rc            : the scaffolder's create-time result (0 == the deck-contract + AA-contrast checks pass)
- errors        : count of `deck_validate.deck_checks` contract violations (must be 0)
- advisories    : count of `deck_validate.deck_warnings` content-overload advisories - an AUTHORED
                  budget proxy for clipping (too much authored content for the slide). It is computed
                  from static markup, so it is theme-independent; catching font-driven RENDERED
                  overflow is the manual blind-visual-preference leg, not this metric.
- bytes / dTheme: rendered size and the delta a theme adds over the baseline - the token/latency proxy
                  (a preset is a bounded CSS block, not a per-deck payload)

`gate_failures()` turns these into pass/fail thresholds so a NEW preset that fails contrast, clips
content, or bloats a deck fails the gate. The subjective "blind visual preference" leg of the original
A/B design is intentionally NOT automated here (it cannot be); it stays a manual review step documented
in dev/frontend-slides-upstream-sync.md.
"""
import argparse
import contextlib
import io
import os
from pathlib import Path
import sys
import tempfile

HERE = Path(__file__).resolve().parent
PKG = Path(os.environ.get("CMH_PKG_DIR") or (HERE.parent / "skill"))  # relocated stage (dev/skill)
TOOLS = PKG / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
import _toolpath  # noqa: E402
_toolpath.ensure()
import deck_scaffold  # noqa: E402
import deck_validate  # noqa: E402
import _deck_theme  # noqa: E402

DEFAULT_CORPUS = HERE / "corpus"
# A theme is a bounded <style> block; it must not add more than this many bytes over the unthemed deck.
SIZE_DELTA_CEILING = 20000
BASELINE = "(none)"


def _scaffold(fragment_path, theme, out_path):
    argv = ["--content", str(fragment_path), "--label", "eval-" + fragment_path.stem, "--out", str(out_path)]
    if theme:
        argv += ["--theme", theme]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        rc = deck_scaffold.main(argv)
    return rc, buf.getvalue().strip()


def evaluate(corpus_dir=DEFAULT_CORPUS, themes=None):
    """Render every corpus fragment under the baseline and each theme; return a metric row per cell."""
    themes = _deck_theme.list_presets() if themes is None else list(themes)
    rows = []
    fragments = sorted(Path(corpus_dir).glob("*.html"))
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        for frag in fragments:
            base_bytes = 0  # the baseline (unthemed) size, measured the same way as themed cells
            for theme in [None] + themes:
                name = theme or BASELINE
                out = tmp / (frag.stem + "__" + (theme or "none") + ".html")
                if out.exists():
                    out.unlink()
                rc, log = _scaffold(frag, theme, out)
                errors, advisories, size = [], [], 0
                if rc == 0:
                    html = out.read_text(encoding="utf-8")
                    errors = deck_validate.deck_checks(html)
                    advisories = deck_validate.deck_warnings(html)
                    size = len(html.encode("utf-8"))
                if theme is None:
                    base_bytes = size
                rows.append({
                    "theme": name,
                    "corpus": frag.name,
                    "rc": rc,
                    "errors": len(errors),
                    "advisories": len(advisories),
                    "bytes": size,
                    "delta": (size - base_bytes) if theme is not None and size else 0,
                    "error_list": list(errors),
                    "advisory_list": list(advisories),
                    "log": log,
                })
    return rows


def gate_failures(rows, size_delta_ceiling=SIZE_DELTA_CEILING):
    """Return a list of human-readable gate failures; empty means every cell meets the thresholds.

    Each failure class is checked independently so a cell with more than one problem surfaces all of
    them (not just the first)."""
    fails = []
    for r in rows:
        where = "%s @ %s" % (r["corpus"], r["theme"])
        if r["rc"] != 0:
            fails.append("%s: scaffold failed (rc=%d): %s" % (where, r["rc"], r["log"][:200]))
        if r["errors"]:
            fails.append("%s: %d validator error(s): %s" % (where, r["errors"], "; ".join(r["error_list"][:3])))
        if r["advisories"]:
            fails.append("%s: %d content-overload advisory(ies) - clipping risk" % (where, r["advisories"]))
        if r["theme"] != BASELINE and r["delta"] > size_delta_ceiling:
            fails.append("%s: theme adds %d bytes (> %d ceiling)" % (where, r["delta"], size_delta_ceiling))
    return fails


def _print_table(rows):
    print("%-14s %-24s %3s %4s %4s %8s %8s" % ("theme", "corpus", "rc", "err", "adv", "bytes", "dTheme"))
    for r in rows:
        print("%-14s %-24s %3d %4d %4d %8d %8d" % (
            r["theme"], r["corpus"], r["rc"], r["errors"], r["advisories"], r["bytes"], r["delta"]))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Evaluate native deck theme presets over a fixed corpus.")
    ap.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    args = ap.parse_args(argv)
    corpus = Path(args.corpus)
    rows = evaluate(corpus)
    if not rows:
        print("theme-eval: no corpus fragments found under %s (expected *.html slide fragments)"
              % corpus, file=sys.stderr)
        return 1
    _print_table(rows)
    fails = gate_failures(rows)
    if fails:
        print("\ntheme-eval GATE FAILURES:", file=sys.stderr)
        for f in fails:
            print("  - " + f, file=sys.stderr)
        return 1
    themes = sorted({r["theme"] for r in rows})
    print("\ntheme-eval OK (%d cells across %d themes/baseline)" % (len(rows), len(themes)))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
