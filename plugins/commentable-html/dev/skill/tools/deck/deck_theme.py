#!/usr/bin/env python3
"""Apply a native deck theme preset to an existing deck in place (CMH-DECK-THEME-02).

Idempotent and comment-safe. It swaps ONLY the ``<style id="cmh-deck-theme">`` block (inserting one
directly after ``cmh-deck-stage`` if absent) and never touches slide markup, ``data-slide-id``
values, the embedded-comments block, or the handled-ids block. Because the theme block is
``cm-skip`` it contributes no comment-offset text, so re-theming a deck that already carries
comments can never move an anchor. The write is atomic and fails closed - if the re-themed deck does
not validate, the source file is left untouched.

Usage (run from the skill root):
    python deck/deck_theme.py list
    python deck/deck_theme.py apply path/to/deck.html --theme terminal
    python deck/deck_theme.py apply path/to/deck.html --theme terminal --out re-themed.html
"""
import argparse
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tools/ root
import _toolpath  # noqa: E402
_toolpath.ensure()
import _deck_theme  # noqa: E402
import deck_validate  # noqa: E402

try:
    import validate as _base
except ImportError:  # pragma: no cover
    _base = None


def _is_repo_example(path):
    norm = os.path.normpath(os.path.abspath(path)).replace("\\", "/")
    return (
        "/pkg/skills/commentable-html/examples/" in norm
        or "/dev/examples/src/" in norm
    )


def _validate_html(html):
    problems = []
    warnings = []
    if _base is not None:
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as tf:
            tf.write(html)
            tmp = tf.name
        try:
            errors, warnings = _base.validate(tmp)
        finally:
            os.unlink(tmp)
        problems.extend(errors)
    problems.extend(deck_validate.deck_checks(html))
    return problems, warnings


def main(argv=None):
    ap = argparse.ArgumentParser(description="Apply a native deck theme preset to an existing deck.")
    sub = ap.add_subparsers(dest="cmd")
    p_apply = sub.add_parser("apply", help="re-theme a deck in place")
    p_apply.add_argument("deck", help="deck HTML file to re-theme")
    p_apply.add_argument("--theme", required=True,
                         help="preset name (see tools/deck/themes/) or a path to a .theme.json")
    p_apply.add_argument("--out", help="write to this file instead of re-theming in place")
    p_apply.add_argument("--force", action="store_true",
                         help="allow re-theming a repo example/source deck (rebuilt from dev/examples/src)")
    sub.add_parser("list", help="list available preset names and exit")
    args = ap.parse_args(argv)

    if args.cmd == "list":
        for name in _deck_theme.list_presets():
            print(name)
        return 0
    if args.cmd != "apply":
        ap.print_usage(sys.stderr)
        print("deck_theme: expected the 'apply' or 'list' command", file=sys.stderr)
        return 2

    if not os.path.isfile(args.deck):
        print(f"deck_theme: no such file: {args.deck}", file=sys.stderr)
        return 2
    if _is_repo_example(args.deck) and not args.force:
        print("deck_theme: refusing to re-theme a repo example/source deck (it is rebuilt from "
              "dev/examples/src by build.py); pass --force only if you know why.", file=sys.stderr)
        return 2

    # Preserve the source's newline convention (read + write with newline="") so untouched regions
    # are byte-identical on every platform - a CRLF-authored deck is not silently flipped to LF.
    with open(args.deck, encoding="utf-8", newline="") as fh:
        html = fh.read()
    try:
        theme = _deck_theme.load(args.theme)
        themed = _deck_theme.insert_or_replace(html, _deck_theme.render(theme))
    except _deck_theme.DeckThemeError as exc:
        print(f"deck_theme: {exc}", file=sys.stderr)
        return 2

    problems, warnings = _validate_html(themed)
    if problems:
        print("deck_theme: the re-themed deck does not validate (source left untouched):",
              file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        return 1
    for w in warnings:
        print(f"deck_theme: warning: {w}", file=sys.stderr)

    out = args.out or args.deck
    dest_dir = os.path.dirname(os.path.abspath(out)) or "."
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8",
                                     dir=dest_dir, newline="") as tf:
        tf.write(themed)
        tmp = tf.name
    try:
        os.replace(tmp, out)
    except OSError:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    print(f"deck_theme: applied theme '{theme.label}' to {out}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
