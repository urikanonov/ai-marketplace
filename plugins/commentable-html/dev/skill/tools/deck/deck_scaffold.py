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
from typing import NamedTuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tools/ root
import _toolpath  # noqa: E402
_toolpath.ensure()
import _atomic_io  # noqa: E402
import _brand_profile  # noqa: E402
import _browser_attrs  # noqa: E402
import _deck_theme  # noqa: E402
from deck_common import esc, slide_id  # noqa: E402

HERE = Path(__file__).resolve().parent
PKG = Path(_toolpath.SKILL_ROOT)
TEMPLATE = Path(_toolpath.dist_template(_toolpath.SHAREABLE_TEMPLATE))
VIEWPORT_CSS = PKG / "vendor" / "frontend-slides" / "viewport-base.css"

import new_document  # noqa: E402
import deck_validate  # noqa: E402
import normalize_typography  # noqa: E402
try:
    import validate as _validate  # noqa: E402
except ImportError:  # pragma: no cover
    _validate = None
    _toolpath.warn_missing_tool("validate", "deck validation")
try:
    import highlight_document as _highlight_document  # noqa: E402
except ImportError:  # pragma: no cover
    _highlight_document = None
    _toolpath.warn_missing_tool("highlight_document", "syntax highlighting")

# A `<` that opens a COMMENT, a non-element region, or a TAG, in one pass so each shields the
# others: HTML requires an ASCII letter after a `<` or `</`, and every other spelling opens
# something that is NOT an element - a markup declaration (`<!DOCTYPE ...>`) or a BOGUS COMMENT
# (`<?...`, `<!...` that is not a comment, and a `</` with no tag name), each of which a browser
# ends at its first `>`. The tag NAME is never matched here - the walk finds every tag and the
# shared readings then decide each one's name and extent - because Python's `re.IGNORECASE` folds
# UNICODE: a `<section` pattern also matched `<\u017fection` (a CUSTOM ELEMENT to a browser, which
# folds a tag name ASCII-only), and the rewrite then emitted a real `<section>` in its place, with
# the authored `</\u017fection>` left behind as an unknown end tag so the phantom slide never
# closed. Walking EVERY tag is also what keeps a `<section` spelled inside another tag's quoted
# attribute value out of the result: that tag's own extent is consumed whole, so the decoy inside
# it is never a candidate.
TAG_OR_COMMENT_RE = re.compile(r"(<!--)|<(/?)(?=[a-zA-Z])|(<[!?]|</(?![a-zA-Z]))")
_BOGUS_COMMENT_CLOSE_RE = re.compile(r">")
# `</section` with HTML's own tag-name terminator, ASCII-folded (`re.A` beside `re.I`) exactly as a
# browser folds a tag name. Where the end tag ENDS is then the shared reading's answer, not this
# pattern's: a literal `</section>` refuses the ordinary `</section >` and `</section foo="x">`.
SECTION_END_RE = re.compile(r"</section(?=[\t\n\f\r />])", re.I | re.A)
_SECTION_TAG_LEN = len("<section")
# The shared raw-text set MINUS `title`, which is the one member that is also an ordinary FOREIGN
# element: nothing is raw text inside `<svg>` / `<math>`, and this walk keeps no namespace stack,
# so treating an `<svg><title>` as raw text could skip real markup - while no deck author writes a
# slide inside a `<title>` of either kind, so dropping it costs nothing.
_RAW_TEXT_TAGS = frozenset(_browser_attrs.raw_text_elements()) - {"title"}
_RAW_TEXT_END_RES = {}
# The `class` attribute in all three HTML quoting forms, with an attribute-name boundary and
# HTML's own unquoted-value terminator - ASCII whitespace or `>` ONLY (CMH-VAL-21 clause 11). Kept
# for the raw-text scans that have nothing else; the slide rewrite reads and RE-SERIALIZES parsed
# attributes instead, because a search matches a `class=` spelled inside another attribute's
# quoted value and would then rewrite THAT. `re.ASCII` beside `re.IGNORECASE` so Python's Unicode
# fold does not read `cla\u017f\u017f=` as `class=`.
CLASS_RE = re.compile(
    r"""(?<![^\t\n\f\r /"'])class[\t\n\f\r ]*=[\t\n\f\r ]*"""
    r"""(?:"([^"]*)"|'([^']*)'|([^\t\n\f\r >]+))""", re.I | re.A)
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
    "\n#commentRoot[data-cmh-mode=\"deck\"] .slide :where(h1,h2,h3,h4){font-family:var(--font-display);}"
    "\n#commentRoot[data-cmh-mode=\"deck\"] .slide,"
    "\n#commentRoot[data-cmh-mode=\"deck\"] .slide :where(h1,h2,h3,h4,h5,h6,p,li,td,th,blockquote,code,strong,em,span)"
    "{color:var(--slide-fg,#f4f4f5);}"
    "\n#commentRoot[data-cmh-mode=\"deck\"] .slide :where(th,td){border-color:var(--slide-border,rgba(255,255,255,0.22));}"
    "\n#commentRoot[data-cmh-mode=\"deck\"] .slide a{color:var(--slide-link,#93c5fd);}"
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


def _slide_classes(pairs):
    """The class tokens a parsed start tag names, IN ORDER.

    The ORDERED shared reading, not `str.split()`: the caller REWRITES the class attribute from
    these tokens, so they go back in the order the author wrote them - and Python's split would
    turn a `class="a\u000bb"` (ONE class to a browser) into two real classes on the way through.
    """
    return _browser_attrs.html_ws_tokens(next((v for n, v in pairs if n == "class"), None))


def _is_slide(pairs):
    return "slide" in _slide_classes(pairs)


def _slide_id_attr(pairs):
    """The `data-slide-id` a parsed start tag names, or None when it names none.

    The FIRST occurrence wins, as HTML5 and `deck_validate` read it: taking the first NON-EMPTY
    one instead would adopt an id a browser never sees, from a duplicate attribute the browser
    discards. A valueless or empty one decodes to no id at all, so it reads as missing - which is
    also how `deck_validate` reads it.
    """
    sid = next((v for n, v in pairs if n == "data-slide-id"), None)
    return sid or None


class _Section(NamedTuple):
    """One `<section>...</section>`, located the way a BROWSER reads its start tag."""
    start: int          # offset of the `<`
    tag_end: int        # offset just past the start tag's `>`
    inner_end: int      # offset of the `</section>` that closes it
    end: int            # offset just past that `</section>`
    attrs: str          # the start tag's RAW attribute region
    pairs: list         # that region's browser-decoded (name, value) pairs, in order


def _raw_text_end(fragment, pos, name):
    """The offset just past the end tag that closes the raw-text element `name` whose body starts
    at `pos`, or -1 when it never closes - which a browser reads as the body running to the end of
    the input, so nothing after it is markup either.

    HTML closes a raw-text element on `</name` followed by ASCII whitespace, `/` or `>`, and that
    closer is still a TAG, so the shared end-tag close decides where it ends. `<plaintext>` has no
    closer at all and so always answers -1.
    """
    if name == "plaintext":
        return -1
    pattern = _RAW_TEXT_END_RES.get(name)
    if pattern is None:
        pattern = _RAW_TEXT_END_RES[name] = re.compile(
            r"</%s(?=[\t\n\f\r />])" % re.escape(name), re.I | re.A)
    m = pattern.search(fragment, pos)
    if m is None:
        return -1
    return _browser_attrs.end_tag_close(fragment, m.start())


def _walk_tags(fragment):
    """Yield `(start, is_end, end, name)` for every TAG in `fragment`, in document order.

    One left-to-right walk of the shapes a `<` can open, so each shields the others: every tag's
    whole extent is consumed (a tag-shaped string inside another tag's quoted attribute value is
    part of that value, never a tag), a COMMENT is skipped whole (its content is prose a reader
    sees), a RAW-TEXT body is skipped whole (same), and so is every NON-ELEMENT region a `<` can
    open - a markup declaration and a bogus comment (`<?...`, a `<!` that is not a comment, a `</`
    with no tag name), which a browser ends at its first `>`. Every boundary comes from the shared
    browser readings - `scan_start_tag` for a start tag (which also hands back the ASCII-folded
    name), `end_tag_close` for an end tag, `comment_close` for a comment - so the walk and the
    attribute reading that follows it cannot disagree about which tags exist.

    Skipping those regions is not a nicety: tokenizing there both invents elements and loses real
    ones. A commented-out or scripted tag carrying an unterminated quoted value (`<!-- <a href="x
    -->`) runs a start-tag scan through everything after it, so the real `<section class="slide">`
    that follows is consumed inside the pseudo-tag's extent and the slide disappears; and a
    `<section class="slide">` written inside a declaration or a bogus comment is not an element at
    all, so rewriting it would mint an id for a decoy and give it `.active`.

    One namespace-dependent case is deliberately left: `<![CDATA[ ... ]]>` is character data only
    inside FOREIGN content (`<svg>` / `<math>`), and this walk keeps no namespace stack, so it is
    read as the bogus comment it is in the HTML namespace - ending at the first `>`. That errs
    toward finding a decoy rather than toward losing a real slide, which is the safe direction.

    The walk STOPS - yielding nothing further - where a browser stops building elements: a tag
    that reaches the end of the input inside a quoted value (the HTML5 eof-in-tag error, which
    discards the tag and every character after that quote) and a raw-text body that never closes.

    `name` is the ASCII-folded tag name for a start tag; for an END tag it is `"section"` or None,
    which is all a section walk needs to know about it.
    """
    pos = 0
    while True:
        m = TAG_OR_COMMENT_RE.search(fragment, pos)
        if m is None:
            return
        start = m.start()
        if m.group(1):
            pos = _browser_attrs.comment_close(fragment, start)
            continue
        if m.group(3):
            close = _BOGUS_COMMENT_CLOSE_RE.search(fragment, start + len(m.group(3)))
            if close is None:
                return          # it runs to the end of the input; nothing after it is markup
            pos = close.end()
            continue
        if m.group(2):
            end = _browser_attrs.end_tag_close(fragment, start)
            if end < 0:
                return
            yield start, True, end, ("section" if SECTION_END_RE.match(fragment, start) else None)
            pos = end
            continue
        scanned = _browser_attrs.scan_start_tag(fragment, start)
        if scanned is None:
            return
        end, name = scanned[0], scanned[1]
        yield start, False, end, name
        if name in _RAW_TEXT_TAGS:
            end = _raw_text_end(fragment, end, name)
            if end < 0:
                return
        pos = end


def _section_tags(fragment):
    """Every `<section>...</section>` in `fragment` whose start tag BOTH shared readings agree on.

    Built on the `_walk_tags` walk, so every boundary and every tag name is the shared browser
    reading - the same reading the attributes are then read with, so the locate and the read
    cannot disagree about which tags exist. A quote-aware `<section ...>` regex disagreed in both
    directions: it opened a quoted run at ANY quote, where HTML opens one only AFTER an `=` and
    takes a stray quote INTO the attribute name, so `<section class="slide" a"b>` (a real slide to
    a browser) was skipped, while `<section class=slide foo" bar="x>` (which reaches EOF inside a
    quoted value, so a browser DISCARDS the tag) matched and was rewritten into a live slide the
    deck contract then passed (#1197).

    The FIRST `</section>` closes a section, as the non-greedy regex this replaces did, so a
    NESTED `<section>` is body content rather than a slide of its own. That is a deliberate
    divergence from a browser (which nests them) and it is what keeps a slide's body - and so its
    minted, supposedly stable id - the same text the old scan hashed.

    Three shapes are refused, and refusing them is what makes the tool fail CLOSED - a slide left
    without a `data-slide-id` is rejected by `deck_checks` before anything is written:

      - a tag that never finishes (the HTML5 eof-in-tag error), which stops the walk;
      - a `<section` whose tag name is not `section` under HTML's own ASCII fold and tag-name
        terminator - the CUSTOM ELEMENTS `<section-foo>` and `<\u017fection>`, both of which the
        old `<section\\b` plus `re.IGNORECASE` promoted into a real `<section>`;
      - a start tag the shared tokenizer did not fully consume, which would re-serialize with the
        attributes past that point silently dropped.
    """
    out = []
    pending = None
    for start, is_end, end, name in _walk_tags(fragment):
        if pending is None:
            if is_end or name != "section":
                continue
            attrs = fragment[start + _SECTION_TAG_LEN:end - 1]
            pending = (start, end) + _browser_attrs.raw_attrs_pairs_consumed(attrs) + (attrs,)
        elif is_end and name == "section":
            open_start, tag_end, pairs, consumed, attrs = pending
            if consumed:
                out.append(_Section(open_start, tag_end, start, end, attrs, pairs))
            pending = None
    return out


def prepare_slides(fragment: str):
    """Ensure every slide <section> has a stable data-slide-id and ONLY the first is .active.
    Returns (rewritten_fragment, [slide_ids])."""
    sections = _section_tags(fragment)
    taken = set()
    for sec in sections:
        # The shared raw-attribute reading, not a `data-slide-id\s*=\s*"..."` search: an id
        # authored single-quoted or unquoted is the SAME id to a browser (and to `deck_validate`,
        # which compares the decoded value), so a search that sees only the double-quoted form
        # leaves it out of `taken` and lets `slide_id()` mint it again - a deck the scaffold's own
        # deck contract then refuses as a duplicate. It also decodes character references and
        # ignores a `data-slide-id=` spelled inside another attribute's quoted value.
        #
        # Only a SLIDE's id is reserved, which is the only id `deck_validate` reads. Reserving an
        # unrelated `<section>`'s would push a real slide onto the `-2` branch and make that slide's
        # supposedly stable id depend on content that is not a slide at all.
        if not _is_slide(sec.pairs):
            continue
        sid = _slide_id_attr(sec.pairs)
        if sid:
            taken.add(sid)
    ids = []
    # `_section_tags` walks the fragment the way a browser tokenizes it, so a `<section>` inside a
    # comment or a raw-text body is already not here (#1197). A `<template>` SUBTREE is the one
    # remaining gap: its tags ARE tokenized, but a browser renders the fragment nowhere and
    # `deck_validate`'s structure scan does not count it - so letting a templated slide consume the
    # FIRST-slide position would put `.active` on markup nothing shows and leave every real slide
    # without it, which the deck contract then refuses (CMH-DECK-04). The answer comes from the
    # gate's OWN parse, so the scaffold and the gate it must satisfy hold one reading.
    slide_starts = [sec.start for sec in sections if _is_slide(sec.pairs)]
    first_start = deck_validate.first_live_slide_offset(fragment)
    if first_start not in slide_starts:
        # The two readings disagree about where the first slide BEGINS. Degrade to the first slide
        # this rewrite can actually reach rather than marking nothing active, which would emit a
        # deck this tool's own gate then refuses.
        first_start = slide_starts[0] if slide_starts else None
    out, cursor = [], 0
    for sec in sections:
        # The start tag is PARSED, not searched: a `class=` search matches one spelled inside
        # ANOTHER attribute's quoted value (`<section title=' class="slide"'>`) and the rewrite
        # below would then corrupt that title and promote a non-slide. The shared reading also
        # decodes character references (`class='sl&#105;de'` IS a slide to a browser), keeps the
        # FIRST of a duplicated attribute as HTML5 does, and reads all three quoting forms.
        classes = _slide_classes(sec.pairs)
        if "slide" not in classes:
            continue                       # not a slide section; leave untouched
        sid = _slide_id_attr(sec.pairs)
        if not sid:
            sid = slide_id(_strip_tags(fragment[sec.tag_end:sec.inner_end]), taken)
        ids.append(sid)
        # ONLY the first slide is `.active` (CMH-DECK-02). An input fragment that marks a LATER
        # slide active is NORMALIZED rather than carried through: two active slides, or an active
        # one that is not the first, is a deck that opens on the wrong slide, which the deck
        # contract refuses (CMH-DECK-04). `visible` goes with it - the runtime toggles the two in
        # lockstep and `viewport-base.css` shows a slide on EITHER, so a later slide left `visible`
        # paints stacked over the slide the deck opens on.
        if sec.start == first_start:
            if "active" not in classes:
                classes.append("active")
        else:
            classes = [c for c in classes if c not in ("active", "visible")]
        # The start tag is RE-SERIALIZED from the parsed attributes for EVERY slide, so the class
        # is written back in one canonical form and every value is re-escaped exactly once from its
        # DECODED form - escaping the raw text instead turned an authored `x&amp;y` into the
        # literal `x&amp;y`. The shared writer (`_browser_attrs.serialize_start_tag`) is the
        # inverse of the reading above, so a valueless attribute comes back as `name=""` and
        # cannot fuse with a following name that legally begins with `=` (#1191, #1195).
        rebuilt = []
        wrote_sid = False
        for name, value in sec.pairs:
            if name == "class":
                value = " ".join(classes)
            elif name == "data-slide-id":
                # A DUPLICATED id is written back ONCE. Re-emitting the later occurrences would
                # contradict the reading above, which - like HTML5 and `deck_validate` - treats
                # only the first as the slide's id, and would double the slide in every raw-text
                # `data-slide-id="..."` count.
                if wrote_sid:
                    continue
                wrote_sid = True
                value = sid
            rebuilt.append((name, value))
        if not wrote_sid:
            rebuilt.append(("data-slide-id", sid))
        # Only the START TAG is spliced; the body and the end tag are the authored bytes.
        out.append(fragment[cursor:sec.start])
        out.append(_browser_attrs.serialize_start_tag("section", rebuilt))
        cursor = sec.tag_end
    out.append(fragment[cursor:])
    return "".join(out), ids


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
    ap.add_argument("--source", help="data-doc-source filename (directories are stripped)")
    ap.add_argument("--generated", help="ISO-8601 Generated-on stamp")
    ap.add_argument("--out", required=True, help="output file (create-only unless --force)")
    ap.add_argument("--force", action="store_true", help="overwrite an existing --out")
    ap.add_argument("--no-highlight", action="store_true",
                    help="do not bake syntax highlighting into raw language-labelled code blocks "
                         "(baking is ON by default so a scaffolded deck is never raw)")
    ap.add_argument("--no-normalize", action="store_true",
                    help="do not rewrite AI smart-typography (em/en dashes, ellipsis, curly quotes, "
                         "nbsp) in slide prose to plain ASCII (normalizing is ON by default)")
    ap.add_argument("--brand", default=None,
                    help="optional brand.json profile that stamps validated --cp-* theme tokens "
                         "and local data-URI font faces")
    ap.add_argument("--theme", default=None,
                    help="native deck theme preset name (see tools/deck/themes/) or a path to a "
                         "<name>.theme.json profile; recolors the deck stage and components")
    ap.add_argument("--session-id", default=None,
                    help="AI session id of the agent creating this deck, stamped as provenance and "
                         "copyable from the footer (default: auto-detected from the environment)")
    ap.add_argument("--agent", default=None,
                    help="producing agent slug (e.g. copilot, claude) shown in the footer copy "
                         "tooltip; default: inferred from which session env var matched")
    ap.add_argument("--no-session-id", action="store_true",
                    help="do not stamp the creating AI session id (ON by default when a session id "
                         "is available from --session-id or the environment)")
    args = ap.parse_args(argv)

    out = Path(args.out)
    if out.exists() and not args.force:
        print(f"deck_scaffold: refusing to overwrite existing {out} (create-only; pass --force). "
              "Reiteration edits the deck in place, it does not re-scaffold.", file=sys.stderr)
        return 1

    # The deck is a DIFFERENT artifact than every file it is built FROM, including the two the
    # tool reads off its own install rather than off the command line (CMH-TOOL-23). The theme
    # is compared as the file `load` would READ, since a bare preset name resolves into themes/.
    if _atomic_io.refuse_aliased_output(
            "deck_scaffold", args.out,
            [_atomic_io.not_stdin(args.content), args.brand,
             _deck_theme.resolved_spec_path(args.theme),
             os.fspath(TEMPLATE), os.fspath(VIEWPORT_CSS)]):
        return 1

    if args.slides is not None:
        if args.slides < 1:
            print("deck_scaffold: --slides must be >= 1", file=sys.stderr)
            return 1
        fragment = placeholder_slides(args.slides)
    else:
        fragment = sys.stdin.read() if args.content == "-" else Path(args.content).read_text(encoding="utf-8")

    # Rewrite AI smart-typography to plain ASCII before assembly, leaving code/script/style verbatim
    # (CMH-ASCII-01): the slide prose fragment (HTML-aware), plus the label and source that get baked
    # into the document title and data-doc-* attributes (plain text, so use the plain-text path).
    # Placeholder slides are already ASCII (no-op).
    label, source = args.label, args.source
    if not args.no_normalize:
        fragment, _ = normalize_typography.normalize_typography(fragment)
        label, _ = normalize_typography.normalize_text(label)
        if source:
            source, _ = normalize_typography.normalize_text(source)

    try:
        content, _ids = build_content(fragment)
    except ValueError as exc:
        print(f"deck_scaffold: {exc}", file=sys.stderr)
        return 1

    # Apply a native deck theme preset into the content region (after cmh-deck-stage), before the
    # document is assembled, so the deck-contract and contrast checks cover the themed variables.
    if args.theme:
        try:
            theme = _deck_theme.load(args.theme)
            content = _deck_theme.insert_or_replace(content, _deck_theme.render(theme))
        except _deck_theme.DeckThemeError as exc:
            print(f"deck_scaffold: {exc}", file=sys.stderr)
            return 2

    key = _auto_key(args.label) if args.key == "auto" else args.key
    template = TEMPLATE.read_text(encoding="utf-8")
    try:
        html = new_document.make_document(template, content, key, label,
                                          source=source, generated=args.generated,
                                          kind="slides")
    except ValueError as exc:
        print(f"deck_scaffold: {exc}", file=sys.stderr)
        return 1
    html = _inject_deck_mode(html, key)

    # Bake syntax highlighting into raw language-labelled code blocks so a scaffolded deck is never
    # raw (opt out with --no-highlight).
    if not args.no_highlight and _highlight_document is not None:
        html, _ = _highlight_document.highlight_document(html)

    # Stamp the creation time so the runtime can tell a produced-but-never-validated deck apart from
    # a strict-validated one.
    try:
        import doc_stamp
        html = doc_stamp.stamp_created(html, when=args.generated)
        if not args.no_session_id:
            sid, agent = args.session_id, args.agent
            if not sid:
                sid, detected_agent = doc_stamp.detect_session()
                if agent is None:
                    agent = detected_agent
            html = doc_stamp.stamp_session(html, sid, agent=agent)
    except ImportError:
        _toolpath.warn_missing_tool("doc_stamp", "the session-id stamp")

    brand_warnings = []
    try:
        html, brand_warnings = _brand_profile.apply_brand(html, args.brand)
    except _brand_profile.BrandProfileError as exc:
        print(f"deck_scaffold: {exc}", file=sys.stderr)
        return 2

    problems = []
    warnings = []
    if _validate is not None:
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as tf:
            tf.write(html)
            tmp = tf.name
        try:
            errors, warnings = _validate.validate(tmp)
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

    # Surface validator warnings (previously discarded): a warning means the deck is valid but not
    # finished - it MUST still be finalized and strict-validated before it is shared.
    for w in list(warnings) + brand_warnings:
        print(f"deck_scaffold: warning: {w}", file=sys.stderr)

    # fallback: when the deck content came from a FILE, a new --out inherits its visibility
    # rather than the process umask default.
    content_source = args.content if args.content and args.content != "-" else None
    _atomic_io.atomic_write(os.fspath(out), html, fallback=content_source)
    print(f"deck_scaffold: wrote {out} ({len(_ids)} slide(s))")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
