#!/usr/bin/env python3
"""Scaffold a commentable-native, fixed-stage deck from slide sections.

Produces a standalone commentable-html document whose content root carries
``data-cmh-mode="deck"`` and holds a ``.deck-viewport > .deck-stage`` fixed 16:9 stage with
one ``<section class="slide" data-slide-id=...>`` per slide (see references/deck-contract.md).
The vendored ``viewport-base.css`` is inlined. The deck body carries NO navigation script and
NO inline editor / localStorage autosave - navigation and commenting come from the
commentable-html deck runtime; slide edits are agent-only via the review loop.

The tool is CREATE-ONLY: it refuses to overwrite an existing ``--out`` (pass ``--force`` to
override) so a re-scaffold during reiteration can never renumber slide ids or reset comment
state. The result is self-validated with validate.py AND the deck contract
(deck_validate.deck_checks) before it is written; scaffolding fails closed if either reports a
problem, so a malformed deck (duplicate ids, remote media, missing deck mode) is never emitted.

Usage (run from the skill root):
    python deck/deck_scaffold.py --content slides.html --label "My Deck" --out deck.html
    python deck/deck_scaffold.py --slides 3 --label "Draft" --out deck.html   # placeholders
"""
import argparse
import hashlib
import os
from pathlib import Path
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tools/ root
import _toolpath  # noqa: E402
_toolpath.ensure()
from deck_common import esc, slide_id  # noqa: E402

HERE = Path(__file__).resolve().parent
PKG = Path(_toolpath.SKILL_ROOT)
TEMPLATE = PKG / "dist" / "PORTABLE.html"
VIEWPORT_CSS = PKG / "vendor" / "frontend-slides" / "viewport-base.css"

import new_document  # noqa: E402
import deck_validate  # noqa: E402
try:
    import validate as _validate  # noqa: E402
except ImportError:  # pragma: no cover
    _validate = None

SECTION_RE = re.compile(r'<section\b([^>]*)>(.*?)</section>', re.S | re.I)
CLASS_RE = re.compile(r'class\s*=\s*"([^"]*)"', re.I)
SLIDE_ID_ATTR_RE = re.compile(r'data-slide-id\s*=\s*"([^"]*)"', re.I)
MAIN_ROOT_RE = re.compile(r'<main\b[^>]*\bid="commentRoot"[^>]*>', re.I)

# A system-font stack keeps a scaffolded deck free of remote font requests; a design pass can
# override these vars with self-hosted @font-face fonts. The slide surface is a dark presentation
# background, so the slide content is given an explicit light colour (--slide-fg) with enough
# specificity to beat the layer's #commentRoot text/heading colours - otherwise a freshly
# scaffolded deck renders dark-on-dark and is illegible under the document's default light theme.
ROOT_VARS = (
    ":root{--stage-bg:#0b0b0f;--slide-bg:#0b0b0f;--slide-fg:#f4f4f5;"
    "--font-body:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;"
    "--font-display:var(--font-body);}"
    "\n.deck-stage{font-family:var(--font-body);}"
    "\n#commentRoot[data-cmh-mode=\"deck\"] .slide,"
    "\n#commentRoot[data-cmh-mode=\"deck\"] .slide :where(h1,h2,h3,h4,h5,h6,p,li,td,th,blockquote,code,strong,em,span)"
    "{color:var(--slide-fg,#f4f4f5);}"
    "\n#commentRoot[data-cmh-mode=\"deck\"] .slide :where(th,td){border-color:rgba(255,255,255,0.22);}"
    "\n#commentRoot[data-cmh-mode=\"deck\"] .slide a{color:#93c5fd;}"
    # Presentation-scale typography and padding for the 1920x1080 stage (default doc sizes are
    # tiny once the stage is scaled to the viewport). A design pass overrides these per slide.
    "\n#commentRoot[data-cmh-mode=\"deck\"] .slide{padding:72px 88px;font-size:28px;line-height:1.5;}"
    "\n#commentRoot[data-cmh-mode=\"deck\"] .slide :where(h1){font-size:76px;line-height:1.1;margin:0 0 .4em;}"
    "\n#commentRoot[data-cmh-mode=\"deck\"] .slide :where(h2){font-size:52px;line-height:1.15;margin:0 0 .5em;}"
    "\n#commentRoot[data-cmh-mode=\"deck\"] .slide :where(h3){font-size:38px;line-height:1.2;margin:0 0 .5em;}"
    "\n#commentRoot[data-cmh-mode=\"deck\"] .slide :where(p,li){font-size:28px;margin:.3em 0;}"
    "\n#commentRoot[data-cmh-mode=\"deck\"] .slide :where(li){margin:.5em 0;}"
    "\n#commentRoot[data-cmh-mode=\"deck\"] .slide :where(td,th){font-size:26px;padding:12px 18px;}"
)


def _strip_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html)


def prepare_slides(fragment: str):
    """Ensure every slide <section> has a stable data-slide-id and the first is .active.
    Returns (rewritten_fragment, [slide_ids])."""
    taken = set()
    for m in SECTION_RE.finditer(fragment):
        cm = SLIDE_ID_ATTR_RE.search(m.group(1))
        if cm:
            taken.add(cm.group(1))
    ids = []
    first = [True]

    def repl(m):
        attrs, inner = m.group(1), m.group(2)
        cls_m = CLASS_RE.search(attrs)
        classes = (cls_m.group(1).split() if cls_m else [])
        if "slide" not in classes:
            return m.group(0)  # not a slide section; leave untouched
        cm = SLIDE_ID_ATTR_RE.search(attrs)
        if cm:
            sid = cm.group(1)
        else:
            sid = slide_id(_strip_tags(inner), taken)
            attrs = attrs + f' data-slide-id="{sid}"'
        ids.append(sid)
        if first[0] and "active" not in classes:
            classes.append("active")
            attrs = CLASS_RE.sub('class="%s"' % " ".join(classes), attrs, count=1)
        first[0] = False
        return f"<section{attrs}>{inner}</section>"

    return SECTION_RE.sub(repl, fragment), ids


def placeholder_slides(n: int) -> str:
    out = []
    for i in range(1, n + 1):
        out.append(
            f'<section class="slide">\n'
            f'  <h2 class="cmh-slide-title">Slide {i}</h2>\n'
            f'  <p>Replace this with slide {i} content.</p>\n'
            f'</section>'
        )
    return "\n".join(out) + "\n"


def build_content(slides_fragment: str) -> str:
    css = VIEWPORT_CSS.read_text(encoding="utf-8")
    prepared, ids = prepare_slides(slides_fragment)
    if not ids:
        raise ValueError('no <section class="slide"> found in the content fragment')
    style = f'<style id="cmh-deck-stage">\n{css}\n{ROOT_VARS}\n</style>'
    stage = f'<div class="deck-viewport">\n<div class="deck-stage">\n{prepared}\n</div>\n</div>'
    return f"{style}\n{stage}\n", ids


def _auto_key(label: str) -> str:
    return "deck-" + hashlib.sha1(label.strip().encode("utf-8")).hexdigest()[:10]


def _inject_deck_mode(html: str, key: str) -> str:
    # Target the REAL content root by its unique data-comment-key, never the decoy
    # <main id="commentRoot"> that lives in the template's top-of-file doc comment
    # (whose key is the "my-doc" placeholder). Matching the whole <main> open tag and
    # keying on the marker inside it is robust to the key string also appearing elsewhere
    # (e.g. an embedded-comment block) and is idempotent.
    marker = 'data-comment-key="' + key + '"'

    def repl(m):
        tag = m.group(0)
        if marker not in tag or "data-cmh-mode=" in tag:
            return tag
        return tag[:-1] + ' data-cmh-mode="deck">'

    return MAIN_ROOT_RE.sub(repl, html)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Scaffold a commentable-native fixed-stage deck.")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--content", help="slide-sections HTML fragment, or - for stdin")
    src.add_argument("--slides", type=int, help="generate N placeholder slides")
    ap.add_argument("--key", default="auto", help='data-comment-key, or "auto" to derive from --label')
    ap.add_argument("--label", required=True, help="human-readable document label")
    ap.add_argument("--source", help="data-doc-source (the file the agent edits)")
    ap.add_argument("--generated", help="ISO-8601 Generated-on stamp")
    ap.add_argument("--out", required=True, help="output file (create-only unless --force)")
    ap.add_argument("--force", action="store_true", help="overwrite an existing --out")
    args = ap.parse_args(argv)

    out = Path(args.out)
    if out.exists() and not args.force:
        print(f"deck_scaffold: refusing to overwrite existing {out} (create-only; pass --force). "
              "Reiteration edits the deck in place, it does not re-scaffold.", file=sys.stderr)
        return 1

    if args.slides is not None:
        if args.slides < 1:
            print("deck_scaffold: --slides must be >= 1", file=sys.stderr)
            return 1
        fragment = placeholder_slides(args.slides)
    else:
        fragment = sys.stdin.read() if args.content == "-" else Path(args.content).read_text(encoding="utf-8")

    try:
        content, _ids = build_content(fragment)
    except ValueError as exc:
        print(f"deck_scaffold: {exc}", file=sys.stderr)
        return 1

    key = _auto_key(args.label) if args.key == "auto" else args.key
    template = TEMPLATE.read_text(encoding="utf-8")
    try:
        html = new_document.make_document(template, content, key, args.label,
                                          source=args.source, generated=args.generated,
                                          kind="slides")
    except ValueError as exc:
        print(f"deck_scaffold: {exc}", file=sys.stderr)
        return 1
    html = _inject_deck_mode(html, key)

    problems = []
    if _validate is not None:
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as tf:
            tf.write(html)
            tmp = tf.name
        try:
            errors, _ = _validate.validate(tmp)
        finally:
            os.unlink(tmp)
        problems.extend(errors)
    # Fail closed on the deck contract too (duplicate/missing slide ids, remote media, missing
    # deck mode) so a malformed deck is never written to disk.
    problems.extend(deck_validate.deck_checks(html))
    if problems:
        print("deck_scaffold: the generated deck does not validate:", file=sys.stderr)
        for e in problems:
            print(f"  {e}", file=sys.stderr)
        return 1

    out.write_text(html, encoding="utf-8")
    print(f"deck_scaffold: wrote {out} ({len(_ids)} slide(s))")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
