#!/usr/bin/env python3
"""Validate a generated commentable-html deck (CMH-DECK-04).

Runs the base commentable-html validator, then adds the deck-specific fail-closed contract
(references/deck-contract.md): the deck body must declare deck mode, hold exactly one fixed
1920x1080 stage, give every slide a unique stable id, carry no <deck-stage> web component and
no inline editor, load no remote fonts, and contain no dangerous active content. The active
content and egress checks parse the HTML (via html.parser) rather than matching regex, so a
solidus attribute separator (<svg/onload=>), an entity-encoded scheme (&#106;avascript:), an
unquoted attribute (<img src=//evil>), or an SVG <image>/<use> href cannot bypass them.

Scope note: the network check targets remote FONTS, remote MEDIA/resources (img/video/audio/
source/track/image/use/iframe/embed/object) and active content, the concrete corporate-safety
and XSS risks; an external hyperlink (<a href>) is allowed because it is not egress. The strict
"zero network of any kind" guarantee (which also covers the layer's optional mermaid/Chart CDN
loaders and any chart init script) is asserted against the Export Offline deck, and rendered
overflow/overlap is a Playwright gate - neither is this static check's job.

Usage (run from the skill root):
    python deck/deck_validate.py deck.html
"""
import argparse
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tools/ root
import _toolpath  # noqa: E402
_toolpath.ensure()
from deck_common import SLIDE_ID_RE  # noqa: E402
from html.parser import HTMLParser  # noqa: E402
from cmhval import contrast  # noqa: E402

PKG = Path(_toolpath.SKILL_ROOT)
try:
    import validate as _base
except ImportError:  # pragma: no cover
    _base = None
    _toolpath.warn_missing_tool("validate", "the base layer checks")

# The content region is delimited by full HTML comments; anchoring on the comment form (not the
# bare text) and taking the LAST end marker means slide text that merely contains the literal
# "END: commentable-html - CONTENT" cannot truncate validation (extracted text is HTML-escaped,
# so it can never forge the "<!--" that opens a real marker comment).
BEGIN_MARK = "<!-- BEGIN: commentable-html - CONTENT"
END_MARK = "<!-- END: commentable-html - CONTENT -->"

REMOTE_FONT_RE = re.compile(r"fonts\.googleapis\.com|fonts\.gstatic\.com|api\.fontshare\.com", re.I)
FONTFACE_REMOTE_RE = re.compile(r"@font-face[^}]*url\(\s*['\"]?https?:", re.I | re.S)
IMPORT_REMOTE_RE = re.compile(r"@import\s+(?:url\()?['\"]?\s*(?:https?:)?//", re.I)
CSS_URL_REMOTE_RE = re.compile(r"url\(\s*['\"]?\s*(?:https?:)?//", re.I)
# image-set() can carry a bare remote string (no url() wrapper) that CSS_URL_REMOTE_RE misses.
CSS_IMAGE_SET_RE = re.compile(r"image-set\(\s*['\"]?\s*(?:https?:)?//", re.I)
# The upstream inline editor ships as an <edit-toggle> custom element / .edit-toggle control;
# match the actual element or class, not the bare substring (which can occur in slide prose).
EDIT_TOGGLE_RE = re.compile(r"<\s*edit-toggle\b|class\s*=\s*['\"][^'\"]*\bedit-toggle\b", re.I)
DECK_CONTRAST_VARIABLE_PAIRS = (
    ("--slide-fg", "--slide-bg", "deck theme variables --slide-fg/--slide-bg"),
    ("--slide-fg", "--stage-bg", "deck theme variables --slide-fg/--stage-bg"),
    ("--slide-fg-muted", "--slide-bg", "deck theme variables --slide-fg-muted/--slide-bg"),
    ("--slide-link", "--slide-bg", "deck theme variables --slide-link/--slide-bg"),
    ("--slide-link", "--cmh-deck-code-bg", "deck theme variables ref-link/code bg (recipe .cmh-refs a)"),
    ("--slide-accent-fg", "--slide-accent", "deck theme variables --slide-accent-fg/--slide-accent"),
    ("--slide-accent", "--slide-bg", "deck theme variables --slide-accent/--slide-bg (recipe accent text)"),
    ("--cmh-deck-code-text", "--cmh-deck-code-bg", "deck theme variables code text/bg"),
    ("--cmh-deck-code-muted", "--cmh-deck-code-bg", "deck theme variables code muted/bg"),
    ("--cmh-deck-code-muted", "--cmh-deck-code-bg-soft", "deck theme variables code muted/bg-soft"),
    ("--cmh-deck-code-soft", "--cmh-deck-code-bg", "deck theme variables code soft/bg"),
    ("--cmh-deck-diff-add-fg", "--cmh-deck-code-bg", "deck theme variables diff add/code bg"),
    ("--cmh-deck-diff-del-fg", "--cmh-deck-code-bg", "deck theme variables diff del/code bg"),
    ("--cmh-deck-diff-hunk-fg", "--cmh-deck-code-bg", "deck theme variables diff hunk/code bg"),
    ("--cmh-deck-tok-kw", "--cmh-deck-code-bg", "deck theme variables token kw/code bg"),
    ("--cmh-deck-tok-fn", "--cmh-deck-code-bg", "deck theme variables token fn/code bg"),
    ("--cmh-deck-tok-str", "--cmh-deck-code-bg", "deck theme variables token str/code bg"),
    ("--cmh-deck-tok-num", "--cmh-deck-code-bg", "deck theme variables token num/code bg"),
    ("--cmh-deck-tok-com", "--cmh-deck-code-bg", "deck theme variables token com/code bg"),
    ("--cmh-deck-tok-op", "--cmh-deck-code-bg", "deck theme variables token op/code bg"),
    ("--cmh-deck-table-head-fg", "--cmh-deck-table-head-bg", "deck theme variables table head fg/bg"),
    ("--cmh-deck-mermaid-label", "--cmh-deck-mermaid-node-fill",
     "deck theme variables mermaid label/node"),
    ("--cmh-deck-mermaid-edge-label-fg", "--cmh-deck-mermaid-edge-label-bg",
     "deck theme variables mermaid edge-label fg/bg"),
)
DEFAULT_MAX_SLIDE_LINES = 24
DEFAULT_MAX_SLIDE_ELEMENTS = 40
DEFAULT_MAX_BOARD_CARD_LINES = 6
DEFAULT_MAX_BOARD_CARD_ELEMENTS = 12
DEFAULT_OVERLOAD_LINE_CHARS = 90

# Active-content and egress checks run through an HTML parser rather than regex, so an attacker
# cannot bypass them with a solidus attribute separator (<svg/onload=...>), an entity-encoded
# scheme (&#106;avascript:), an unquoted attribute (<img src=//evil>), or an SVG <image>/<use>.
_ACTIVE_TAGS = {"iframe", "object", "embed"}
_URL_ATTRS = {"href", "src", "xlink:href", "poster", "background", "lowsrc", "action", "formaction", "data"}
# Elements whose URL attribute triggers a network FETCH on load (egress), not a mere hyperlink.
# A <link> or <base> with a remote href is egress/redirect just like remote media, so they are
# included; a plain <a href="https://..."> hyperlink is deliberately NOT (it fetches nothing).
_EGRESS_ATTRS = {
    "img": {"src", "srcset"}, "video": {"src", "poster"}, "audio": {"src"},
    "source": {"src", "srcset"}, "track": {"src"}, "input": {"src"},
    "image": {"href", "xlink:href", "src", "srcset"}, "use": {"href", "xlink:href"},
    "iframe": {"src"}, "embed": {"src"}, "object": {"data"},
    "link": {"href"}, "base": {"href"},
}
# Legacy presentational URL attributes that fetch on ANY element (a browser rewrites a bare
# <image> to <img>, and body/table background / img lowsrc still load), independent of tag.
_EGRESS_ANY_ATTRS = {"background", "lowsrc"}
_DANGER_SCHEME_RE = re.compile(r"^\s*(?:javascript|vbscript|livescript|mocha)\s*:", re.I)
_DATA_HTML_RE = re.compile(r"^\s*data\s*:\s*text/html", re.I)
_REMOTE_URL_RE = re.compile(r"^\s*(?:https?:)?//", re.I)
_SKIP_AUTHORED_CONTENT_TAGS = {"script", "style", "template", "noscript", "pre"}
_AUTHORED_ELEMENT_TAGS = {
    "article", "blockquote", "canvas", "dd", "dt", "figcaption", "figure",
    "h1", "h2", "h3", "h4", "h5", "h6", "img", "li", "ol", "p", "pre",
    "svg", "table", "tbody", "td", "tfoot", "th", "thead", "tr", "ul",
}
_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
              "meta", "param", "source", "track", "wbr"}


def _srcset_urls(value):
    return [part.strip().split()[0] for part in value.split(",") if part.strip()]


class _ActiveContentScanner(HTMLParser):
    """Collect active-content / egress violations from parsed tags and attributes.

    Character references in attribute values are decoded by HTMLParser, and <script>/<style>
    bodies are treated as CDATA, so a chart's init script or the inlined CSS never trips a check.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.errors = []
        self._svg_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "svg":
            self._svg_depth += 1
        self._scan(tag, attrs)

    def handle_endtag(self, tag):
        if tag.lower() == "svg" and self._svg_depth > 0:
            self._svg_depth -= 1

    def handle_startendtag(self, tag, attrs):
        self._scan(tag, attrs)

    def _scan(self, tag, attrs):
        tag = tag.lower()
        if tag in _ACTIVE_TAGS:
            self.errors.append(f"deck: <{tag}> is not allowed in the deck body")
        if tag == "script":
            # An inline HTML <script> (no src) is allowed for chart init; an EXTERNAL script
            # (src/href) fetches and runs remote code, and an SVG-nested <script> executes on
            # render - both are RCE/egress vectors, so fail closed on them.
            if self._svg_depth > 0:
                self.errors.append("deck: <script> inside <svg> is not allowed in the deck body")
            if any((n or "").lower() in ("src", "href", "xlink:href") for n, _ in attrs):
                self.errors.append("deck: external <script> (src/href) is not allowed in the deck body")
            return
        if tag == "meta":
            attr_map = {(n or "").lower(): (v or "") for n, v in attrs}
            if attr_map.get("http-equiv", "").lower() == "refresh":
                self.errors.append("deck: <meta http-equiv=refresh> (redirect) is not allowed in the deck body")
        egress = _EGRESS_ATTRS.get(tag, set())
        for raw_name, raw_value in attrs:
            name = (raw_name or "").lower()
            value = raw_value or ""
            if name.startswith("on"):
                self.errors.append(f"deck: inline event-handler attribute ({name}=) in the deck body")
                continue
            if name != "srcset" and name not in _URL_ATTRS:
                continue
            for cand in (_srcset_urls(value) if name == "srcset" else [value]):
                if _DANGER_SCHEME_RE.match(cand) or _DATA_HTML_RE.match(cand):
                    self.errors.append("deck: dangerous URL scheme (javascript:/vbscript:/data:text/html) in the deck body")
                if "../" in cand.replace("\\", "/"):
                    self.errors.append("deck: parent-directory (../) asset reference in the deck body")
                if (name in egress or name in _EGRESS_ANY_ATTRS) and _REMOTE_URL_RE.match(cand):
                    self.errors.append("deck: remote media/resource in the deck body - vendor it locally")


def _active_content_errors(body: str):
    scanner = _ActiveContentScanner()
    try:
        scanner.feed(body)
        scanner.close()
    except Exception:  # pragma: no cover - HTMLParser is lenient; fail closed if it ever raises
        return ["deck: could not parse the deck body for active-content checks"]
    seen, out = set(), []
    for e in scanner.errors:
        if e not in seen:
            seen.add(e)
            out.append(e)
    return out


class _AuthoredContentRegion:
    def __init__(self, kind, label, depth, elements=0):
        self.kind = kind
        self.label = label
        self.depth = depth
        self.lines = 0
        self.elements = elements


def _attr_map(attrs):
    return {(n or "").lower(): (v or "") for n, v in attrs}


def _classes(attrs):
    return set((attrs.get("class") or "").split())


def _authored_element_count(tag, attrs):
    return tag in _AUTHORED_ELEMENT_TAGS or "data-cm-part" in attrs


def _estimated_lines(text, line_chars):
    total = 0
    for line in text.splitlines() or [text]:
        compact = " ".join(line.split())
        if compact:
            total += max(1, (len(compact) + line_chars - 1) // line_chars)
    return total


class _AuthoredContentScanner(HTMLParser):
    def __init__(self, line_chars):
        super().__init__(convert_charrefs=True)
        self.line_chars = max(1, line_chars)
        self.regions = []
        self._active = []
        self._skip_depth = 0
        self._slide_count = 0
        self._card_count = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        self._start(tag, attrs, self_closing=tag in _VOID_TAGS)

    def handle_startendtag(self, tag, attrs):
        self._start(tag.lower(), attrs, self_closing=True)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in _SKIP_AUTHORED_CONTENT_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        closed = []
        for region in self._active:
            region.depth -= 1
            if region.depth <= 0:
                closed.append(region)
        if closed:
            self.regions.extend(closed)
            self._active = [region for region in self._active if region.depth > 0]

    def handle_data(self, data):
        if self._skip_depth:
            return
        lines = _estimated_lines(data, self.line_chars)
        if lines:
            for region in self._active:
                region.lines += lines

    def _start(self, tag, attrs, self_closing):
        attrs = _attr_map(attrs)
        countable = not self._skip_depth and _authored_element_count(tag, attrs)
        for region in self._active:
            region.depth += 1
            if countable:
                region.elements += 1
        if tag in _SKIP_AUTHORED_CONTENT_TAGS:
            self._skip_depth += 1

        is_slide = tag == "section" and "slide" in _classes(attrs)
        is_card = "data-cm-part" in attrs
        if is_slide:
            self._slide_count += 1
            label = attrs.get("data-slide-id") or f"#{self._slide_count}"
            self._active.append(_AuthoredContentRegion("slide", label, 1))
        if is_card:
            self._card_count += 1
            label = attrs.get("data-cm-part-label") or attrs.get("data-cm-part") or f"#{self._card_count}"
            self._active.append(_AuthoredContentRegion("board card", label, 1, 1 if countable else 0))

        if self_closing:
            self.handle_endtag(tag)


def _content_overload_warnings(body, max_slide_lines, max_slide_elements,
                               max_board_card_lines, max_board_card_elements, line_chars):
    scanner = _AuthoredContentScanner(line_chars)
    try:
        scanner.feed(body)
        scanner.close()
    except Exception:  # pragma: no cover - HTMLParser is lenient; advisory checks never fail closed
        return []
    warnings = []
    for region in scanner.regions:
        if region.kind == "slide":
            max_lines, max_elements = max_slide_lines, max_slide_elements
            advice = "split content across slides or move detail to speaker notes"
        else:
            max_lines, max_elements = max_board_card_lines, max_board_card_elements
            advice = "split the card or move detail to a follow-up slide"
        if region.lines > max_lines or region.elements > max_elements:
            warnings.append(
                "deck: content overload advisory: "
                f"{region.kind} {region.label} has {region.lines} line(s) / "
                f"{region.elements} element(s), above budget {max_lines} line(s) / "
                f"{max_elements} element(s); {advice}")
    return warnings


def _content_region(html: str):
    bi = html.find(BEGIN_MARK)
    ei = html.rfind(END_MARK)
    if bi == -1 or ei == -1 or ei <= bi:
        return None
    close = html.find("-->", bi)
    if close == -1 or close > ei:
        return None
    return html[close + 3:ei]


def deck_checks(html: str):
    return deck_checks_with_options(html)


def deck_checks_with_options(html: str, contrast_threshold=contrast.DEFAULT_MIN_CONTRAST_RATIO):
    errors = []
    body = _content_region(html)
    if body is None:
        return ["deck: could not locate the CONTENT region markers"]

    # The real content root is the LAST <main id="commentRoot"> - the template's
    # top-of-file doc comment contains a decoy first match.
    roots = re.findall(r'<main\b[^>]*\bid="commentRoot"[^>]*>', html)
    if not roots or 'data-cmh-mode="deck"' not in roots[-1]:
        errors.append('deck: #commentRoot is missing data-cmh-mode="deck"')

    if 'class="deck-viewport"' not in body and "class='deck-viewport'" not in body:
        errors.append("deck: missing .deck-viewport wrapper")
    stages = len(re.findall(r'class="[^"]*\bdeck-stage\b', body))
    if stages != 1:
        errors.append(f"deck: expected exactly one .deck-stage, found {stages}")

    slide_opens = re.findall(r'<section\b([^>]*\bclass="[^"]*\bslide\b[^"]*"[^>]*)>', body)
    if not slide_opens:
        errors.append("deck: no <section class=\"slide\"> found")
    ids = []
    for attrs in slide_opens:
        m = re.search(r'data-slide-id\s*=\s*"([^"]*)"', attrs)
        if not m:
            errors.append("deck: a slide is missing data-slide-id")
            continue
        if not SLIDE_ID_RE.match(m.group(1)):
            errors.append(f"deck: invalid data-slide-id '{m.group(1)}'")
        ids.append(m.group(1))
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        errors.append(f"deck: duplicate slide id(s): {', '.join(dupes)}")

    if re.search(r"<\s*deck-stage\b", body, re.I) or "data-deck-active" in body:
        errors.append("deck: the <deck-stage> web component is not allowed in a generated deck")
    if "prefers-reduced-motion" not in body:
        errors.append("deck: missing a prefers-reduced-motion rule")
    if "edit-toggle" in body and EDIT_TOGGLE_RE.search(body):
        errors.append("deck: the upstream inline editor (edit-toggle) must be stripped")

    if REMOTE_FONT_RE.search(body) or FONTFACE_REMOTE_RE.search(body):
        errors.append("deck: remote font reference in the deck body - self-host fonts (no egress)")
    if IMPORT_REMOTE_RE.search(body):
        errors.append("deck: remote CSS @import in the deck body")
    if CSS_URL_REMOTE_RE.search(body) or CSS_IMAGE_SET_RE.search(body):
        errors.append("deck: remote CSS url() in the deck body - vendor the asset locally")
    # Parser-based active-content / egress checks (event handlers, dangerous schemes, remote
    # media, iframe/object/embed, ../ traversal) - robust to solidus, entities, and quoting.
    errors.extend(_active_content_errors(body))
    for issue in contrast.find_low_contrast_pairs(
            body, threshold=contrast_threshold, variable_pairs=DECK_CONTRAST_VARIABLE_PAIRS):
        errors.append("deck: " + issue.message())
    return errors


def deck_warnings(html: str):
    return deck_warnings_with_options(html)


def deck_warnings_with_options(html: str, max_slide_lines=DEFAULT_MAX_SLIDE_LINES,
                               max_slide_elements=DEFAULT_MAX_SLIDE_ELEMENTS,
                               max_board_card_lines=DEFAULT_MAX_BOARD_CARD_LINES,
                               max_board_card_elements=DEFAULT_MAX_BOARD_CARD_ELEMENTS,
                               line_chars=DEFAULT_OVERLOAD_LINE_CHARS):
    body = _content_region(html)
    if body is None:
        return []
    return _content_overload_warnings(
        body, max_slide_lines=max_slide_lines, max_slide_elements=max_slide_elements,
        max_board_card_lines=max_board_card_lines, max_board_card_elements=max_board_card_elements,
        line_chars=line_chars)


def validate_deck(path, contrast_threshold=contrast.DEFAULT_MIN_CONTRAST_RATIO,
                  max_slide_lines=DEFAULT_MAX_SLIDE_LINES,
                  max_slide_elements=DEFAULT_MAX_SLIDE_ELEMENTS,
                  max_board_card_lines=DEFAULT_MAX_BOARD_CARD_LINES,
                  max_board_card_elements=DEFAULT_MAX_BOARD_CARD_ELEMENTS):
    html = Path(path).read_text(encoding="utf-8")
    base_errors = []
    base_warnings = []
    if _base is not None:  # pragma: no branch
        base_errors, base_warnings = _base.validate(path)
    deck_errors = deck_checks_with_options(html, contrast_threshold=contrast_threshold)
    deck_warnings_found = deck_warnings_with_options(
        html, max_slide_lines=max_slide_lines, max_slide_elements=max_slide_elements,
        max_board_card_lines=max_board_card_lines, max_board_card_elements=max_board_card_elements)
    return base_errors, base_warnings + deck_warnings_found, deck_errors


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate a commentable-html deck.")
    ap.add_argument("file")
    ap.add_argument("--strict", action="store_true", help="treat validator warnings as errors too")
    ap.add_argument("--contrast-threshold", type=float, default=contrast.DEFAULT_MIN_CONTRAST_RATIO,
                    help="minimum WCAG contrast ratio for explicit text/background color pairs")
    ap.add_argument("--max-slide-lines", type=int, default=DEFAULT_MAX_SLIDE_LINES,
                    help="warn when a slide exceeds this estimated authored line count")
    ap.add_argument("--max-slide-elements", type=int, default=DEFAULT_MAX_SLIDE_ELEMENTS,
                    help="warn when a slide exceeds this authored element count")
    ap.add_argument("--max-board-card-lines", type=int, default=DEFAULT_MAX_BOARD_CARD_LINES,
                    help="warn when a board card exceeds this estimated authored line count")
    ap.add_argument("--max-board-card-elements", type=int, default=DEFAULT_MAX_BOARD_CARD_ELEMENTS,
                    help="warn when a board card exceeds this authored element count")
    args = ap.parse_args(argv)

    base_errors, base_warnings, deck_errors = validate_deck(
        args.file, contrast_threshold=args.contrast_threshold,
        max_slide_lines=args.max_slide_lines, max_slide_elements=args.max_slide_elements,
        max_board_card_lines=args.max_board_card_lines,
        max_board_card_elements=args.max_board_card_elements)
    print(f"deck_validate: {args.file}")
    for e in base_errors + deck_errors:
        print(f"  ERROR: {e}", file=sys.stderr)
    for w in base_warnings:
        print(f"  WARNING: {w}", file=sys.stderr)

    failed = bool(base_errors or deck_errors) or (args.strict and bool(base_warnings))
    if failed:
        print("deck_validate: FAILED", file=sys.stderr)
        return 1
    print("deck_validate: OK")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
