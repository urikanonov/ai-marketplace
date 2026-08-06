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
import _browser_attrs  # noqa: E402
import _browser_boundaries  # noqa: E402
from deck_common import SLIDE_ID_RE  # noqa: E402
try:
    from checks.resources import (CSS_HOST_CHAR, CSS_NETWORK_IMAGE_SET_RE,  # noqa: E402
                                  CSS_NETWORK_IMPORT_RE, CSS_NETWORK_PREFIX, CSS_NETWORK_URL_RE,
                                  CSS_WS, css_image_set_args, is_network_url, srcset_candidate_urls)
except Exception:  # pragma: no cover - only a broken/partial install reaches this
    CSS_HOST_CHAR = CSS_NETWORK_IMAGE_SET_RE = CSS_NETWORK_IMPORT_RE = CSS_NETWORK_PREFIX = None
    CSS_NETWORK_URL_RE = css_image_set_args = None
    CSS_WS = is_network_url = srcset_candidate_urls = None
    _toolpath.warn_missing_tool(
        "checks.resources", "the shared network-URL predicate and srcset candidate tokenization")
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
# A remote @font-face, for the self-host-fonts MESSAGE. It is deliberately scheme-literal and is
# NOT the remote-detection backstop: a slash-run font spelling (`@font-face{src:url(//h/f.woff)}`)
# is caught by the shared `url()` reading below, under the generic remote-CSS message.
FONTFACE_REMOTE_RE = re.compile(r"@font-face[^}]*url\(\s*['\"]?https?:", re.I | re.S)
# The SHARED CSS readings, not this gate's own: the strict validator's `url()` and `@import`
# patterns take `https?:/*`, so `url(https:host/x.png)` and `url(https:/host/x.png)` - which the
# URL parser resolves to the same host as `url(https://host/x.png)` - are seen here too (#1129).
# A broken install (the import above already warned) degrades to a strictly OVER-inclusive local
# reading (no host character required), so the gate still fails CLOSED on egress. The choice is
# made per CALL, not bound here, so the degraded reading is reachable from a test.
_CSS_FALLBACK_PREFIX = r"(?:https?:/*|[/\\]{2,})"
_CSS_URL_FALLBACK_RE = re.compile(
    r"url\([\t\n\f\r ]*['\"]?[\t\n\f\r ]*" + _CSS_FALLBACK_PREFIX, re.IGNORECASE | re.ASCII)
_CSS_IMPORT_FALLBACK_RE = re.compile(
    r"@import[\t\n\f\r ]*(?:url\([\t\n\f\r ]*)?['\"]?[\t\n\f\r ]*" + _CSS_FALLBACK_PREFIX,
    re.IGNORECASE | re.ASCII)
# `image-set()` can carry a bare remote string with no `url()` wrapper, which the shared `url()`
# pattern cannot see. Both the candidate-list READER and its candidate pattern now live in the
# shared CSS reading (`checks/resources.py`), because the strict gate needs the same question
# answered in shareable mode (#1166); this module keeps only the DEGRADED spellings a broken
# install falls back to. The degraded READER is a local COPY of the same quote- and paren-aware
# scanner rather than a cruder regex, and that duplication is deliberate: a regex that stops at an
# unquoted `;`/`{`/`}` truncates at the `;` INSIDE a quoted `data:` candidate and drops every
# candidate after it, so `image-set("data:image/png;base64,AAAA" 1x, "//evil/x.png" 2x)` read clean
# in the degraded path - a fail-OPEN in the one path whose whole point is to fail CLOSED (found by
# the round-1 multi-duck panel, 6 of 8 ducks). Sharing the PATTERN is what #1129 asks for; the
# fallback scanner is by definition the code that runs when nothing is shared.
_IMAGE_SET_TOKEN_START = r"(?:^|['\",(]|" + (CSS_WS or r"[\t\n\f\r ]") + r")"
_CSS_IMAGE_SET_FALLBACK_RE = re.compile(
    _IMAGE_SET_TOKEN_START + _CSS_FALLBACK_PREFIX, re.IGNORECASE | re.ASCII)
_IMAGE_SET_OPEN_FALLBACK_RE = re.compile(r"image-set\(", re.IGNORECASE | re.ASCII)
_IMAGE_SET_FALLBACK_MARKUP = "<>"
_IMAGE_SET_FALLBACK_STOP = "<>;{}"
_CSS_IMAGE_SET_RE = CSS_NETWORK_IMAGE_SET_RE
# The characters the URL parser removes from a reference that CSS also permits inside a quoted
# string. It removes ASCII tab (and LF/CR) from ANYWHERE, but every OTHER C0 control only from the
# LEADING run - so the two are normalized differently: deleting a mid-token `\x01` would turn the
# local `url("/\x01/host")` into `url("//host")` and reject a reference that loads nothing.
# Searching a copy normalized this way is what lets the shared patterns - whose host-character
# class excludes tab, and whose whitespace class is CSS's, not the parser's C0-or-space - see
# `url("//<TAB>host/x")` and `url("<VT>//host/x")`, both of which really load. LF and CR are
# deliberately KEPT: a newline inside a CSS string makes a bad-string token and the declaration is
# dropped, so nothing loads.
_CSS_LEADING_C0_RE = re.compile(r"([('\",\t\n\f\r ])[\x00-\x08\x0b\x0c\x0e-\x1f]+")


def _image_set_args_fallback(text):
    """The degraded copy of the shared reader, used only when `checks.resources` did not import."""
    out, pos = [], 0
    while True:
        m = _IMAGE_SET_OPEN_FALLBACK_RE.search(text, pos)
        if not m:
            return out
        stop, closed = _scan_image_set_fallback(text, m.end(), False)
        if not closed:
            stop = _scan_image_set_fallback(text, m.end(), True)[0]
        out.append(text[m.end():stop])
        pos = stop + 1


def _scan_image_set_fallback(text, start, markup_ends_a_string):
    """Where one `image-set(` argument list ends, and whether it CLOSED with its own `)`."""
    depth, i, quote, end = 1, start, "", len(text)
    while i < end:
        ch = text[i]
        if ch == "\\":       # a CSS escape: whatever follows is a literal, never a delimiter
            i += 2
            continue
        if quote:
            if ch == quote:
                quote = ""
            elif markup_ends_a_string and ch in _IMAGE_SET_FALLBACK_MARKUP:
                return i, False
        elif ch in "'\"":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i, True
        elif ch in _IMAGE_SET_FALLBACK_STOP:
            return i, False
        i += 1
    return end, False


def _image_set_args(text):
    """Every `image-set(...)` argument list, from the shared reader (or the degraded copy)."""
    if css_image_set_args is not None:
        return css_image_set_args(text)
    return _image_set_args_fallback(text)


def _css_bodies(body):
    # The body as written AND with the parser-removed controls normalized away, computed ONCE per
    # check: a deck can be megabytes of inlined base64, so neither copy is made per pattern.
    normalized = _CSS_LEADING_C0_RE.sub(r"\1", body.replace("\t", ""))
    return (body,) if normalized == body else (body, normalized)


def _css_import_is_remote(bodies):
    pattern = CSS_NETWORK_IMPORT_RE or _CSS_IMPORT_FALLBACK_RE
    return any(pattern.search(b) for b in bodies)


def _css_url_is_remote(bodies):
    pattern = CSS_NETWORK_URL_RE or _CSS_URL_FALLBACK_RE
    if any(pattern.search(b) for b in bodies):
        return True
    image_set = _CSS_IMAGE_SET_RE or _CSS_IMAGE_SET_FALLBACK_RE
    return any(image_set.search(args) for b in bodies for args in _image_set_args(b))



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
# The strictly OVER-inclusive stand-in for the shared network predicate, used only by a broken or
# partial install (the import above already warned): no non-empty authority is required and the
# `file:` local-name exclusions are not applied, so it fails CLOSED rather than waving a reference
# through. The tab/LF/CR removal is the URL parser's own input cleanup, so `ht<TAB>tps:host/x` -
# which a browser fetches - is not read as a relative reference.
_REMOTE_URL_FALLBACK_RE = re.compile(r"[\x00-\x20]*(?:https?:|file:|[/\\]{2,})",
                                     re.IGNORECASE | re.ASCII)
_URL_INNER_REMOVE_RE = re.compile(r"[\t\n\r]")
_SKIP_AUTHORED_CONTENT_TAGS = {"script", "style", "template", "noscript", "pre"}
_AUTHORED_ELEMENT_TAGS = {
    "article", "blockquote", "canvas", "dd", "dt", "figcaption", "figure",
    "h1", "h2", "h3", "h4", "h5", "h6", "img", "li", "ol", "p", "pre",
    "svg", "table", "tbody", "td", "tfoot", "th", "thead", "tr", "ul",
}
def _is_remote_url(value):
    # The SHARED network predicate, not a fourth reading of the same question: this gate used to
    # ask its own `^(?:https?:)?//`, which REQUIRES the two slashes. The URL parser does not - its
    # special-authority states CONSUME the slash run after a special scheme - so `https:host/x.png`,
    # `https:/host/x.png` and `https:\host/x.png` all resolve to the same host as
    # `https://host/x.png` and really are fetched (measured in Chromium from `img srcset` and
    # `source srcset`; this helper governs EVERY egress fetch attribute, not only those two). The
    # strict validator and the offline strip were widened for exactly those
    # spellings in #961 (CMH-OFFLINE-04); the deck gate never was, and outside descriptor mode
    # `offline` it is the ONLY checker a deck's `source[srcset]` gets, so the miss was egress
    # (#1129).
    if is_network_url is None:
        return bool(_REMOTE_URL_FALLBACK_RE.match(_URL_INNER_REMOVE_RE.sub("", str(value or ""))))
    return is_network_url(value)


def _srcset_urls(value):
    # The SHARED candidate reader, not a third hand copy: `srcset` is a list, and a comma split
    # cuts a `data:` URL in half at its own media-type separator, so this gate used to reject a
    # deck whose only "remote" reference was the tail of one (#1084). The strict validator and the
    # offline strip both read the list with HTML's candidate state machine, and reading it a third
    # way here made the deck gate DISAGREE with both.
    if srcset_candidate_urls is None:
        # Only a broken install gets here (the import above already warned). Degrade to the UNION
        # of both readings - the strictly over-inclusive one - so a partial install still fails
        # CLOSED on egress rather than crashing the gate or waving a candidate through.
        parts = [p.strip().split()[0] for p in value.split(",") if p.strip()]
        return parts + [t.strip(",") for t in value.split() if t.strip(",") and t.strip(",") not in parts]
    return srcset_candidate_urls(value)


class _ActiveContentScanner(_browser_boundaries.BrowserBoundaries):
    """Collect active-content / egress violations from parsed tags and attributes.

    Derives from the SHARED element boundaries AND the shared attribute rule (CMH-VAL-21), so this
    scan reads the same document the validator does on every interpreter: a duplicated attribute
    resolves the way a browser resolves it, raw-text bodies (`<script>`, `<style>`, `<textarea>`,
    ...) are text so a chart's init script or the inlined CSS never trips a check, and a
    `<![CDATA[` in HTML content is the BOGUS COMMENT a browser makes of it - which ends at the
    first `>`, leaving whatever follows LIVE. That last one is the direction that fails OPEN: the
    host consumes the whole marked section, so a remote `<img>` the deck really does fetch was
    invisible to this scan.

    `_fallback` selects the SCRIPTING-DISABLED reading of the same body, in which `<noscript>` is
    TRANSPARENT rather than raw text. `_active_content_errors()` runs both and unions the findings,
    because a reader is on one side or the other and this scan must see what EITHER of them loads.
    """

    def __init__(self, html="", _fallback=False):
        super().__init__(html)
        self.errors = []
        self._stack = []
        self._fallback = _fallback   # read the body as a scripting-DISABLED browser reads it

    def _truncate_stacks(self, depth):
        super()._truncate_stacks(depth)
        del self._stack[depth:]

    def _enter_raw_text(self, tag, ns):
        if tag == "noscript" and self._fallback:
            return   # scripting is off in this pass, so <noscript> holds markup, not text
        super()._enter_raw_text(tag, ns)

    def _visit_start(self, tag, ad, ns, opens):
        self._scan(tag, self._host_attrs, ad, ns)

    def _push_element(self, tag, ad, ns, info):
        self._stack.append(tag)

    def _scan(self, tag, raw_attrs, attr_map, ns):
        # Every pair, browser-decoded: the SCAN reads them all (a duplicate is still an authored
        # attribute an author must clean up), while the single-valued question below reads the
        # first-wins dict a browser resolves to.
        attrs = _browser_attrs.attrs(self, tag, raw_attrs)
        if tag in _ACTIVE_TAGS:
            self.errors.append(f"deck: <{tag}> is not allowed in the deck body")
        if tag == "script":
            # An inline HTML <script> (no src) is allowed for chart init; an EXTERNAL script
            # (src/href) fetches and runs remote code, and an SVG-nested <script> executes on
            # render - both are RCE/egress vectors, so fail closed on them.
            if ns != "html" or "svg" in self._stack:
                self.errors.append("deck: <script> inside <svg> is not allowed in the deck body")
            if any(_browser_attrs.ascii_lower(n) in ("src", "href", "xlink:href")
                   for n, _ in attrs):
                self.errors.append("deck: external <script> (src/href) is not allowed in the deck body")
            return
        if tag == "meta":
            if attr_map.get("http-equiv", "").lower() == "refresh":
                self.errors.append("deck: <meta http-equiv=refresh> (redirect) is not allowed in the deck body")
        egress = _EGRESS_ATTRS.get(tag, set())
        for raw_name, raw_value in attrs:
            name = _browser_attrs.ascii_lower(raw_name)
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
                if (name in egress or name in _EGRESS_ANY_ATTRS) and _is_remote_url(cand):
                    self.errors.append("deck: remote media/resource in the deck body - vendor it locally")


def _active_content_errors(body: str):
    if not _browser_boundaries.IS_SHARED:
        # A broken/partial install leaves this scan on the HOST's boundaries, which consume a whole
        # `<![CDATA[ ... ]]>` in every context and so HIDE the markup a browser leaves live after
        # the bogus comment. For an egress question "could not look" must never read as "nothing to
        # find", so the degraded scan reports rather than passes.
        return ["deck: could not check the deck body for active content - the shared element "
                "boundaries are unavailable (broken or partial install); re-install the skill"]
    errors = []
    # TWO readings of the same body, unioned: a browser with scripting ON (in which a `<noscript>`
    # body is raw TEXT) and one with scripting OFF (in which it is live markup that really is
    # fetched). A reader is on one side or the other, so the scan must see what EITHER loads.
    # Reading the WHOLE body a second time - rather than re-parsing the `<noscript>` body a
    # scripting-enabled tokenizer carved out - is what closes the seam between the two views: the
    # enabled tokenizer ends that body at the first `</noscript`, which a disabled one may never
    # reach (it can sit inside a quoted attribute value, or inside a comment that swallows it), and
    # markup straddling the seam then belonged to neither reading.
    #
    # `<noscript>` is the ONLY element the two readings treat differently, so a body that does not
    # name one at all is read once. The test is a plain substring on purpose: a tag name folds
    # ASCII-case-insensitively, so no element a browser calls `noscript` can be spelled without it,
    # and a `<noscript` that turns out to be inert only costs a second pass it did not need.
    passes = (False, True) if "<noscript" in (body or "").lower() else (False,)
    for fallback in passes:
        scanner = _ActiveContentScanner(body, _fallback=fallback)
        try:
            scanner.parse_document(body)
        except Exception:  # pragma: no cover - HTMLParser is lenient; fail closed if it ever raises
            errors.extend(scanner.errors)
            errors.append("deck: could not parse the deck body for active-content checks")
            break
        errors.extend(scanner.errors)
    seen, out = set(), []
    for e in errors:
        if e not in seen:
            seen.add(e)
            out.append(e)
    return out


class _AuthoredContentRegion:
    def __init__(self, kind, label, index, elements=0):
        self.kind = kind
        self.label = label
        # The element-stack INDEX this region's own element occupies. The region ends when the
        # stack is truncated to that index or below - which is what a browser does whether the
        # element's own end tag, an ancestor's end tag or end of input closes it.
        self.index = index
        self.lines = 0
        self.elements = elements


def _classes(attrs):
    return _browser_attrs.class_tokens(attrs.get("class"))


def _authored_element_count(tag, attrs):
    return tag in _AUTHORED_ELEMENT_TAGS or "data-cm-part" in attrs


def _estimated_lines(text, line_chars):
    total = 0
    for line in text.splitlines() or [text]:
        compact = " ".join(line.split())
        if compact:
            total += max(1, (len(compact) + line_chars - 1) // line_chars)
    return total


class _AuthoredContentScanner(_browser_boundaries.BrowserBoundaries):
    """Advisory per-slide / per-card content counts.

    Derives from the SHARED element boundaries (CMH-VAL-21) so an advisory count is never taken
    from a document the validator disagrees with: markup a reader only SEES quoted inside a
    raw-text body contributes nothing, and markup a browser leaves LIVE after a bogus `<![CDATA[`
    is counted (the host swallowed the whole marked section). Each region is keyed on the element
    stack INDEX of the element that opened it, so an ancestor's end tag - or end of input - closes
    it exactly where a browser closes it.
    """

    def __init__(self, line_chars, html=""):
        super().__init__(html)
        self.line_chars = max(1, line_chars)
        self.regions = []
        self._stack = []
        self._skip = []       # stack indices of the open _SKIP_AUTHORED_CONTENT_TAGS elements
        self._active = []
        self._slide_count = 0
        self._card_count = 0

    def _truncate_stacks(self, depth):
        super()._truncate_stacks(depth)
        del self._stack[depth:]
        while self._skip and self._skip[-1] >= depth:
            self._skip.pop()
        closed = [region for region in self._active if region.index >= depth]
        if closed:
            self.regions.extend(closed)
            self._active = [region for region in self._active if region.index < depth]

    def _in_skip(self):
        # A stack of indices rather than a scan of the open elements, so a deeply nested (or
        # hostile) deck body does not make this an O(n^2) walk - it is asked per element AND per
        # text chunk.
        return bool(self._skip)

    def _visit_start(self, tag, ad, ns, opens):
        # The same shared browser decode the active-content scan uses, so an advisory count is
        # never taken from a value the validator disagrees with (CMH-VAL-21).
        self._element(tag, ad, opens)
        if opens and tag in _SKIP_AUTHORED_CONTENT_TAGS:
            self._skip.append(len(self._stack))

    def _push_element(self, tag, ad, ns, info):
        self._stack.append(tag)

    def close(self):
        super().close()
        # A region still open at end of input is a region a browser still renders, so it is
        # reported rather than dropped.
        self._truncate_stacks(0)

    def handle_data(self, data):
        if self._in_skip():
            return
        lines = _estimated_lines(data, self.line_chars)
        if lines:
            for region in self._active:
                region.lines += lines

    def _element(self, tag, attrs, opens):
        countable = not self._in_skip() and _authored_element_count(tag, attrs)
        if countable:
            for region in self._active:
                region.elements += 1

        index = len(self._stack)
        opened = []
        if tag == "section" and "slide" in _classes(attrs):
            self._slide_count += 1
            label = attrs.get("data-slide-id") or f"#{self._slide_count}"
            opened.append(_AuthoredContentRegion("slide", label, index))
        if "data-cm-part" in attrs:
            self._card_count += 1
            label = attrs.get("data-cm-part-label") or attrs.get("data-cm-part") or f"#{self._card_count}"
            opened.append(_AuthoredContentRegion("board card", label, index,
                                                 1 if countable else 0))
        # A region on an element that never opens (a void or self-closed foreign element) has no
        # content, so it is complete the moment it is created.
        (self._active if opens else self.regions).extend(opened)


def _content_overload_warnings(body, max_slide_lines, max_slide_elements,
                               max_board_card_lines, max_board_card_elements, line_chars):
    scanner = _AuthoredContentScanner(line_chars, body)
    try:
        scanner.parse_document(body)
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


class _DeckStructureScanner(_browser_boundaries.BrowserBoundaries):
    """The deck's STRUCTURE - viewport, stage, slides, inline editor - read from PARSED elements.

    These four checks used to be raw-text regexes that matched a class by SUBSTRING and only in
    the DOUBLE-QUOTED form, so they were wrong against a browser in both directions (#1159):
    `class="my-deck-stage"` satisfied the "exactly one .deck-stage" check for an element a browser
    never matches `.deck-stage` on, while `<section class='slide'>` - the same class to a browser -
    was not seen at all, so a hand-authored deck failed for having no slides and every per-slide
    check then inspected nothing. Membership is the SHARED class reading (`class_tokens`,
    CMH-VAL-21 clause 11) the validator's own class gates use, and it is asked of ELEMENTS, so a
    class named in slide prose or inside a `<script>` body is text rather than deck structure.

    A `<template>` subtree carries no STRUCTURE: its content is a fragment a browser renders
    nowhere, and the runtime finds the stage and the viewport with
    `#commentRoot.querySelector(".deck-stage")` / `.deck-viewport`, which reaches neither a
    template fragment nor a shadow root a declarative template attaches. Only the SUBTREE is
    skipped - the `<template>` ELEMENT itself stays in the document tree, so a
    `<template class="deck-stage">` really is what that query returns (and then holds no slides),
    and its own classes are counted. The EDITOR stays inclusive of templates: an `<edit-toggle>`
    parked in one is still upstream editor chrome a generated deck should not carry, and a guard
    fails closed. Namespace is deliberately NOT filtered - an undeclared-namespace type selector
    and a class selector both match in ANY namespace, so `querySelector(".deck-stage")` really
    does find an SVG-namespace element carrying the class, and this scan reads the document the
    way that query does.

    `_fallback` selects the SCRIPTING-DISABLED reading, in which `<noscript>` is TRANSPARENT rather
    than raw text, exactly as `_ActiveContentScanner` does. `_structure_errors()` runs both and
    unions the findings, because a reader is on one side or the other: a second `.deck-stage`, a
    duplicate slide id or an un-stripped editor parked in a `<noscript>` is live markup to a
    scripting-off reader, and the raw-text regexes this replaced saw it.
    """

    def __init__(self, html="", _fallback=False):
        super().__init__(html)
        self.viewports = 0
        self.stages = 0
        self.slides = []      # the browser-decoded attribute dict of each <section class=slide>
        self.editor = False
        self._stack = []
        self._templates = []  # stack indices of the open <template> elements
        self._fallback = _fallback

    def _truncate_stacks(self, depth):
        super()._truncate_stacks(depth)
        del self._stack[depth:]
        while self._templates and self._templates[-1] >= depth:
            self._templates.pop()

    def _push_element(self, tag, ad, ns, info):
        self._stack.append(tag)

    def _enter_raw_text(self, tag, ns):
        if tag == "noscript" and self._fallback:
            return   # scripting is off in this pass, so <noscript> holds markup, not text
        super()._enter_raw_text(tag, ns)

    def _visit_start(self, tag, ad, ns, opens):
        classes = _classes(ad)
        if tag == "edit-toggle" or "edit-toggle" in classes:
            self.editor = True
        # Read BEFORE the push below, so a `<template>`'s own classes are counted and only its
        # content is skipped.
        inside_template = bool(self._templates)
        if tag == "template" and ns == "html" and opens:
            self._templates.append(len(self._stack))
        if inside_template:
            return
        if "deck-viewport" in classes:
            self.viewports += 1
        if "deck-stage" in classes:
            self.stages += 1
        if tag == "section" and "slide" in classes:
            self.slides.append(ad)


def _structure_pass_errors(structure):
    errors = []
    if not structure.viewports:
        errors.append("deck: missing .deck-viewport wrapper")
    if structure.stages != 1:
        errors.append(f"deck: expected exactly one .deck-stage, found {structure.stages}")

    if not structure.slides:
        errors.append("deck: no <section class=\"slide\"> found")
    ids = []
    for attrs in structure.slides:
        # A VALUELESS `data-slide-id` decodes to "" like an empty one, and neither names a slide,
        # so both read as missing. Keeping "" out of `ids` is also what stops the duplicate line
        # below from naming an empty id.
        slide_id = attrs.get("data-slide-id") or ""
        if not slide_id:
            errors.append("deck: a slide is missing data-slide-id")
            continue
        if not SLIDE_ID_RE.match(slide_id):
            errors.append(f"deck: invalid data-slide-id '{slide_id}'")
        ids.append(slide_id)
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        errors.append(f"deck: duplicate slide id(s): {', '.join(dupes)}")

    if structure.editor:
        errors.append("deck: the upstream inline editor (edit-toggle) must be stripped")
    return errors


def _structure_errors(body):
    """The structural errors of BOTH readings of the body, unioned.

    The same two passes `_active_content_errors()` runs, for the same reason: `<noscript>` is raw
    TEXT to a scripting-enabled browser and live markup to a scripting-disabled one, and a reader
    is on one side or the other. A body that names no `<noscript>` at all is read once.

    A finding only the scripting-DISABLED reading has is NAMED as such. Two readings of one body
    otherwise merge into a report an author cannot act on - `found 2` beside `found 3` reads as a
    self-contradiction rather than as two readers seeing two documents.
    """
    passes = (False, True) if "<noscript" in (body or "").lower() else (False,)
    scans = []
    for fallback in passes:
        scanner = _DeckStructureScanner(body, _fallback=fallback)
        try:
            scanner.parse_document(body)
        except Exception:  # pragma: no cover - HTMLParser is lenient; fail closed if it ever raises
            scans.append(["deck: could not parse the deck body for the structural checks"])
            continue
        scans.append(_structure_pass_errors(scanner))
    errors = list(scans[0])
    seen = set(errors)
    for extra in scans[1:]:
        for e in extra:
            if e in seen:
                continue
            seen.add(e)
            errors.append(e + " (with scripting disabled)")
    return errors


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

    errors.extend(_structure_errors(body))

    if re.search(r"<\s*deck-stage\b", body, re.I) or "data-deck-active" in body:
        errors.append("deck: the <deck-stage> web component is not allowed in a generated deck")
    if "prefers-reduced-motion" not in body:
        errors.append("deck: missing a prefers-reduced-motion rule")

    if REMOTE_FONT_RE.search(body) or FONTFACE_REMOTE_RE.search(body):
        errors.append("deck: remote font reference in the deck body - self-host fonts (no egress)")
    css_bodies = _css_bodies(body)
    if _css_import_is_remote(css_bodies):
        errors.append("deck: remote CSS @import in the deck body")
    if _css_url_is_remote(css_bodies):
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
    ap.add_argument("--strict", action="store_true",
                    help="treat BLOCKING validator warnings as errors too (an advisory, which the "
                         "author cannot clear, is reported but never fails strict)")
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

    # CMH-VAL-18: an advisory names something the author cannot clear (a deliberately
    # hand-written inert code block), so it is reported but never fails --strict. Without this
    # the deck path would still block the workflow the skill tells deck authors to finish with,
    # even though validate.py --strict and finalize.py --strict now pass the same document.
    fatal_warnings = base_warnings
    if _base is not None and hasattr(_base, "partition_warnings"):
        fatal_warnings, _advisory = _base.partition_warnings(base_warnings)
    failed = bool(base_errors or deck_errors) or (args.strict and bool(fatal_warnings))
    if failed:
        print("deck_validate: FAILED", file=sys.stderr)
        return 1
    print("deck_validate: OK")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
