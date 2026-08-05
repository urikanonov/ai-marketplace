"""Shared HTML parsing infrastructure for the commentable-html validator: the
single-pass `_DocParser`, region-marker detection, tag/script attribute helpers,
and the constants (regions, ids, regexes) every check builds on."""

import functools
import re
import unicodedata
from html import unescape
from html import parser as _html_parser
from html.entities import html5 as _HTML5_ENTITIES
from html.parser import HTMLParser
from types import FunctionType, MappingProxyType
from typing import NamedTuple

REGIONS = ["CSS", "HANDLED IDS", "EMBEDDED COMMENTS", "COMMENT UI", "JS"]

# The regions that hold the layer's OWN markup. The two omitted ones (HANDLED IDS, EMBEDDED
# COMMENTS) exist to CARRY user text - a reviewer's comment bodies, the reviewed-section headings
# an export bakes in - so a check asking "does the LAYER contain X?" must never read them.
LAYER_MARKUP_REGIONS = ["CSS", "COMMENT UI", "JS"]

LAYER_DESCRIPTOR_ID = "commentableHtmlLayer"

CONTENT_BEGIN = "<!-- BEGIN: commentable-html - CONTENT (agent edits ONLY between these markers) -->"

CONTENT_END = "<!-- END: commentable-html - CONTENT -->"

# The token the NonShareable bootstrap watchdog sets/reads. The parser records whether it appears
# OUTSIDE the authored CONTENT region, so a document that merely MENTIONS it in prose does not
# look like it carries a watchdog.
READY_TOKEN = "__commentableHtmlReady"

# Structural ids the layer's JS wires up. Missing ones make the layer throw or
# silently no-op, so their absence is an error. (handledCommentIds and
# embeddedComments are <script> blocks, validated separately below. commentRoot
# is checked by its own dedicated-block error, not listed here to avoid a
# duplicate diagnostic.)
REQUIRED_IDS = [
    "sidebar", "commentList", "contextMenu", "mermaidAddBtn", "diffAddBtn", "imageAddBtn", "linkAddBtn", "hlBubble", "toast",
    "toolbarCount", "sidebarCount",
    "btnToggleSidebar", "btnCopyAll", "btnCopyAllTop", "btnClearAll", "btnSort",
    "btnCloseSidebar", "menuComment",
    "btnToolbarMenu", "toolbarMenu",
    "btnMoreMenu", "sidebarMoreMenu", "btnSearchToggle",
    "btnAutoOpenPanel", "btnAutoOpenPanelOverride",
    "btnSaveHtml", "btnSaveHtmlTop", "btnSavePlain", "btnSavePlainTop",
    "btnExportOffline", "btnExportOfflineTop",
    "btnStorage", "btnStorageTop",
    "headingAddBtn", "widgetAddBtn", "menuDocComment", "menuSlideComment",
    "cmIdentity", "cmIdentityName", "btnEditIdentity", "cmIdentityEdit",
    "cmIdentityInput", "btnSaveIdentity", "btnCancelIdentity",
]

# Export/Import was removed before the 1.0.0 release (redundant with Export with embedded comments). Its presence
# means an augmentation reintroduced the retired feature.
FORBIDDEN_IDS = [
    "btnExport", "btnExportTop", "btnImport", "btnImportTop",
    "importModal", "btnImportCancel", "btnImportDo", "importBlobInput", "importErr",
]

SAFE_ID_RE = re.compile(r"^c[a-z0-9]{6,63}$")

_PRE_TAG_RE = re.compile(r"<pre\b([^>]*)>(.*?)</pre>", re.DOTALL | re.IGNORECASE)

_CLASS_ATTR_RE = re.compile(r"""\bclass\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+))""", re.IGNORECASE)

# Transient runtime UI-state classes the layer toggles on document.body (sidebar open, active
# sidebar resize, active widget drag). They must never be baked into a shipped <body>: a persisted
# "sidebar-open" makes the document render full width with an empty sidebar gutter (the
# body.sidebar-open .app layout rule) for a sidebar that is not shown. The runtime re-derives the
# sidebar state on load, so these classes are redundant in a static file.
_TRANSIENT_BODY_CLASSES = ("sidebar-open", "cm-sidebar-resizing", "cm-widget-dragging")


def _attrs_have_class(attrs, class_name):
    wanted = class_name.casefold()
    for m in _CLASS_ATTR_RE.finditer(attrs):
        value = next((g for g in m.groups() if g is not None), "")
        if any(part.casefold() == wanted for part in value.split()):
            return True
    return False


def parsed_attrs_have_class(ad, class_name):
    """Whether a PARSED attribute dict carries `class_name` as a class token. Matching is
    case-insensitive, like the raw-attribute `_attrs_have_class` it replaces for parsed input."""
    wanted = class_name.casefold()
    return any(part.casefold() == wanted for part in (ad.get("class") or "").split())


# dist/SHAREABLE.html ships a working DEMO: its content root carries these placeholder
# values. A finished consumer document must (a) give its content root a unique
# data-comment-key - not the demo one - and (b) never leave real content commented
# out. The two checks below are written so the pristine dist/SHAREABLE.html (demo key
# + demo <title>) still passes with zero findings, while a botched retrofit (a script
# that replaced the WRONG "<main id=commentRoot>" and buried the consumer's real
# content in a comment, leaving the demo as the live root) is caught. A single
# commented "<main id=commentRoot data-comment-key=my-doc>" documentation example is
# still tolerated, so authoring guidance may carry one without tripping the guard.
DEMO_TITLE = "Commentable HTML - Demo"

DEMO_COMMENT_KEY = "commentable-html-demo"

DEMO_NONSHAREABLE_TITLE = "Commentable HTML - NonShareable Demo"

DEMO_NONSHAREABLE_COMMENT_KEY = "commentable-html-nonshareable-demo"

# Each pristine demo content-root key maps to the <title> its generated template
# keeps. A customized retrofit that leaves the demo root in place (changed title,
# same demo key) is flagged for both the inline and the nonshareable template.
DEMO_KEYS = {
    DEMO_COMMENT_KEY: DEMO_TITLE,
    DEMO_NONSHAREABLE_COMMENT_KEY: DEMO_NONSHAREABLE_TITLE,
    # The pre-rename spellings the NONPORTABLE.html demo template used. They stay in the map so an
    # already-shipped legacy demo is still recognized as a pristine demo root.
    "commentable-html-nonportable-demo": "Commentable HTML - NonPortable Demo",
}

DOC_EXAMPLE_COMMENT_KEY = "my-doc"

_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)

# <script>/<style> bodies are blanked before the commented-root scan so a "<!-- -->"
# that appears only inside script/style data (which the browser parses as text, not
# a comment) cannot be mistaken for a real HTML comment.
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1\s*>", re.DOTALL | re.IGNORECASE)

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)

# id is case-sensitive (getElementById("commentRoot") is exact-case), but the value
# may be quoted or unquoted; the lookahead stops "commentRootX" from matching.
_COMMENT_ROOT_ATTR_RE = re.compile(r'(?<![\w:-])(?i:id)\s*=\s*["\']?commentRoot["\']?(?=[\s>/])')

_DATA_KEY_RE = re.compile(r'(?i:data-comment-key)\s*=\s*["\']?([^\s"\'<>]+)')

# The real region marker is an HTML comment, not bare text in prose.
JS_END_MARKER_TEXT = "END: commentable-html - JS"

# ...and its comment SOURCE, in exactly the shapes `_region_marker_matches` COUNTS: `[ \t]`
# padding, the optional `=` decoration, the marker inline or on its own line, and a `-->` close.
# The comment DATA cannot decide this: `str.strip()` also strips NBSP, a vertical tab and every
# other character Python calls whitespace, so a comment padded with one read as the marker here
# while the count view saw only the canonical one - two views disagreeing about which comment is
# the boundary, which is what lets a forged one stand in for it.
@functools.lru_cache(maxsize=None)
def _region_marker_comment_re(kind, region):
    return re.compile(
        r"<!--[ \t]*(?:\r?\n[ \t]*)?(?:=+[ \t]*)?"
        + re.escape("%s: commentable-html - %s" % (kind, region))
        + r"[ \t]*(?:=+[ \t]*)?(?:\r?\n[ \t]*)?-->")


# The JS end marker is one of those, built from the same shape so the boundary `check_charts`
# reads and the boundary the layer check accepts can never drift apart.
_JS_END_MARKER_COMMENT_RE = _region_marker_comment_re("END", "JS")

# The two halves every region marker comes in.
MARKER_KINDS = ("BEGIN", "END")

# The text a comment must mention before it can be a region marker. A cheap gate that keeps the
# per-comment bookkeeping below off every ordinary comment in a document.
_MARKER_HINT = "commentable-html - "

# JSON <script> ids owned by the commentable layer, not chart data.
LAYER_JSON_IDS = {"handledCommentIds", "embeddedComments", LAYER_DESCRIPTOR_ID}

# The optional section-review state block. It is not in LAYER_JSON_IDS (that set also decides which
# blocks the content-JSON and chart checks skip, and this one is validated by its own shape check),
# but the runtime resolves it by id just like the others, so it must be just as unique.
REVIEW_STATE_ID = "reviewedSections"

# Every reserved id whose element must be unique across the active DOM: a duplicate makes an
# id lookup bind a decoy, silently reading or writing the wrong element.
UNIQUE_JSON_IDS = LAYER_JSON_IDS | {REVIEW_STATE_ID}

# HTML void elements never get pushed on the stack.
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr"}

_HEADING_TAGS = frozenset(("h1", "h2", "h3", "h4", "h5", "h6"))

# Elements allowed in <head>. The first START tag outside this set (and every <body> / closing
# </head>) ends the head, so a favicon <link> is only counted while it is head-scoped. This
# mirrors tools/authoring/_favicon.py so the validator and the authoring tools agree.
_HEAD_TAGS = frozenset(("html", "head", "base", "link", "meta", "title", "noscript", "style",
                        "script", "template"))

# Elements a Content-Security-Policy <meta> may follow and still be the whole document's policy. A
# meta-delivered policy is NOT retroactive: it governs only what the parser reaches after it, so
# anything that fetches or executes above it happens with no policy in force. Membership here is
# only the FIRST test - `_csp_predecessor_fetches` decides a <link> and a <script> by CAPABILITY
# instead, because a `rel=canonical` link loads nothing and a `type=application/json` block neither
# runs nor loads, and rejecting a policy written after one would be a false rejection carrying a
# message that claims something the element cannot do. The six listed here can do neither whatever
# their attributes: the two wrappers, another <meta>, the <title>'s RCDATA, a <base>, which only
# resolves references later elements make, and a <template>, whose contents are inert. `meta` is
# safe because the one meta that DOES reach the network - a `http-equiv=refresh` - has its own
# offline gate that rejects every one of them; that gate is what makes this entry sound, so do not
# weaken it without revisiting this.
_CSP_INERT_PREDECESSORS = frozenset(("html", "head", "meta", "title", "base", "template"))

# Link relations that make a <link> FETCH. Defined here, beside the parser's own "can this element
# fetch before the policy?" test, and re-exported by the resource checks (`_link_loads`), so the two
# readers of the same question cannot drift apart.
FETCHING_LINK_RELS = frozenset((
    "stylesheet", "preload", "modulepreload", "prefetch", "prerender",
    "preconnect", "dns-prefetch", "icon", "apple-touch-icon",
    "apple-touch-icon-precomposed", "manifest",
))

# The head-content set for the CSP view. `_HEAD_TAGS` above deliberately mirrors
# `tools/authoring/_favicon.py`, so the three obsolete elements the "in head" insertion mode also
# holds are added here rather than there: without them a `<basefont>`/`<bgsound>`/`<noframes>`
# would end this view early and a policy written after one would be dropped as unapplied.
_CSP_HEAD_TAGS = _HEAD_TAGS | frozenset(("basefont", "bgsound", "noframes"))

# The end tags that END the CSP head view. "in head" and "after head" both treat an end tag named
# body, html or br as "anything else": the head is popped and a <body> is inserted, so a policy
# <meta> written after one is a BODY child whose pragma never runs. Every OTHER end tag in those
# modes is IGNORED and leaves a following meta in the head, which is why this set must not be
# widened - and why `</head>` is absent (see `csp_metas`).
_CSP_HEAD_CLOSERS = frozenset(("body", "html", "br"))

# HTML's own whitespace set. Deliberately not `str.strip()`/`str.isspace()`, which also take
# U+00A0 and the rest of Unicode: a browser ends the head on a NBSP character token, so treating
# one as whitespace would keep the head open for exactly the character that closes it.
_HTML_WHITESPACE = "\t\n\f\r "

# A start tag that implicitly closes an open <p> (a pragmatic HTML5 subset).
P_CLOSERS = {
    "address", "article", "aside", "blockquote", "details", "div", "dl",
    "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3",
    "h4", "h5", "h6", "header", "hr", "main", "menu", "nav", "ol", "p",
    "pre", "section", "table", "ul", "li",
}

# Elements a <p> cannot be implicitly closed across (HTML5 "button scope"); the
# scan for the open <p> stops if one of these is hit first. <li> additionally
# stops at ol/ul (list-item scope).
_P_CLOSE_BOUNDARY = {"applet", "caption", "html", "table", "td", "th",
                     "marquee", "object", "template", "button"}

_LI_CLOSE_BOUNDARY = _P_CLOSE_BOUNDARY | {"ol", "ul"}

# The elements the scan for an open <p> / <li> stops at: the target itself and its scope
# boundaries. Everything else is TRANSPARENT to the scan, which is why the scan itself is not
# needed - the nearest one of these is tracked incrementally as the stack is pushed.
_P_SCOPE_STOPS = frozenset(_P_CLOSE_BOUNDARY | {"p"})
_LI_SCOPE_STOPS = frozenset(_LI_CLOSE_BOUNDARY | {"li"})

# The FOREIGN half of the same scope: markup under an `<svg><foreignObject>` is HTML again, but a
# <p> outside the <svg> is not in scope, so it must not be popped (which would pop the svg with
# it). These names are only boundaries in their own namespace - an HTML element that happens to be
# called <desc> is an ordinary unknown element and stops nothing.
_FOREIGN_SCOPE_BOUNDARY = frozenset(("foreignobject", "desc", "title",
                                     "mi", "mo", "mn", "ms", "mtext", "annotation-xml"))


class _MarkerMatch:
    def __init__(self, marker_start, marker_end):
        self._marker_start = marker_start
        self._marker_end = marker_end

    # Group 0 and group 1 are DELIBERATELY the same span: the only group this match carries is
    # the marker itself. Any other group is refused rather than answered with a plausible wrong
    # offset, so a caller written against a real re.Match fails loudly instead of silently
    # slicing the wrong text.
    def _check_group(self, group):
        if group not in (0, 1):
            raise IndexError("no such group")

    def start(self, group=0):
        self._check_group(group)
        return self._marker_start

    def end(self, group=0):
        self._check_group(group)
        return self._marker_end


def _advance_comment_state(line, state):
    i = 0
    while i < len(line):
        if state == "html":
            close = line.find("-->", i)
            if close < 0:
                return "html"
            state = ""
            i = close + 3
            continue
        if state == "css":
            close = line.find("*/", i)
            if close < 0:
                return "css"
            state = ""
            i = close + 2
            continue
        html_open = line.find("<!--", i)
        css_open = line.find("/*", i)
        if html_open >= 0 and (css_open < 0 or html_open < css_open):
            state = "html"
            i = html_open + 4
            continue
        if css_open >= 0:
            state = "css"
            i = css_open + 2
            continue
        return ""
    return state


def _region_marker_matches(html, kind, region):
    marker = "%s: commentable-html - %s" % (kind, region)
    marker_re = re.escape(marker)
    bare = re.compile(r"^[ \t]*(?:=+[ \t]*)?(%s)[ \t]*(?:=+[ \t]*)?$" % marker_re)
    inline = re.compile(r"^[ \t]*(?:<!--[ \t]*|/\*[ \t]*)(?:=+[ \t]*)?(%s)[ \t]*(?:=+[ \t]*)?(?:-->|\*/)[ \t]*$" % marker_re)
    matches = []
    state = ""
    offset = 0
    # Lines break on "\n" ONLY, the way the runtime - and the browser that opens the document -
    # sees them. str.splitlines() also breaks on \x0b \x0c \x1c \x1d \x1e \x85 \u2028 \u2029 and
    # treats a lone \r as a terminator, so a marker "line" that exists only after one of those
    # splits would be counted here and ignored by the runtime that reads the file back - two
    # views disagreeing about which comment IS the boundary (CMH-VAL-22).
    lines = (html or "").split("\n")
    last = len(lines) - 1
    for i, line in enumerate(lines):
        body = line[:-1] if (i < last and line.endswith("\r")) else line
        m = inline.match(body)
        if m is None and state in ("html", "css"):
            m = bare.match(body)
        if m is not None:
            matches.append(_MarkerMatch(offset + m.start(1), offset + m.end(1)))
        state = _advance_comment_state(body, state)
        offset += len(line) + (1 if i < last else 0)
    return matches


def _line_starts(html):
    starts, pos = [0], html.find("\n")
    while pos != -1:
        starts.append(pos + 1)
        pos = html.find("\n", pos + 1)
    return starts


# --------------------------------------------------------------------------- #
# The tokenizer boundaries a BROWSER draws - shared by BOTH tolerant parsers.
# --------------------------------------------------------------------------- #

# Elements whose CONTENT is text, not markup (the browser's raw-text and RCDATA modes).
# Markup written inside one of them is prose a reader SEES, never an element of the document,
# so no scan may look inside. Every one is switched on EXPLICITLY rather than relying on
# html.parser's own table, which knows only script/style on older interpreters (3.13 added
# xmp/iframe/noembed/noframes/textarea/title, and knows `noscript` on no version) - so the
# boundary is identical on every Python the skill runs on. `noscript` is raw text in a
# scripting-ENABLED browser, which is the only mode a commentable document ever runs in.
#
# The set applies in the HTML namespace ONLY: NOTHING is raw text inside FOREIGN content. HTML5's
# "in foreign content" insertion mode takes a `<script>` or `<style>` start tag through "any other
# start tag", which inserts a FOREIGN element and leaves the TOKENIZER in the data state, so the
# content is MARKUP, not text (an SVG `<title>` is not HTML's RCDATA `<title>` either). Chromium
# confirms it - `<svg><script><img src=...></script>` really does build the `img`, because `img` is
# a breakout tag that pops the open foreign elements and inserts it in the HTML namespace. Reading
# such a body as raw text hid that live, network-loading element from the tag lookup AND the
# document parse, which is the exact pair the self-contained and offline resource gates read - so a
# document that fetches was certified self-contained. `_enter_raw_text()` refuses OUTRIGHT there.
_RAW_TEXT_ELEMENTS = frozenset((
    "script", "style", "textarea", "title", "xmp", "iframe", "noembed", "noframes", "noscript",
    "plaintext",
))

# `<plaintext>` is the one raw-text element a browser NEVER leaves: everything after it, closing
# tag or not, is text to the end of the document. html.parser enters that mode only from 3.13, so
# it is switched on here too and its region is deliberately given no closer.
_PLAINTEXT = "plaintext"

# A comment ends at `-->` or at the legacy `--!>` (the HTML comment-end-bang state), and a
# `<!-->` / `<!--->` closes abruptly. A whitespace-separated `-- >` does NOT close one, which is
# why the boundary cannot be left to html.parser: before 3.13 it delegates to
# `_markupbase._commentclose = re.compile(r'--\s*>')`, which both accepts `-- >` (a false close,
# so quoted markup after it is read as live) and rejects `--!>` (so a comment ending that way
# stayed open to the document's NEXT `-->` - the layer always supplies one - blanking the authored
# markup between). parse_comment is overridden below so the boundary is exact on every host.
_COMMENT_CLOSE_RE = re.compile(r"--!?>")
_COMMENT_ABRUPT_CLOSE_RE = re.compile(r"-?>")

# HTML closes a raw-text element on `</name` followed by whitespace, `/` or `>`, so
# `</script data-x>` and `</script/>` ARE the end tag (with a parse error for the ignored
# attribute). An end tag is still a TAG, so a `>` inside a quoted attribute value there does not
# end it. html.parser only honours the canonical `</script>` before 3.13 AND decides where to
# stop scanning raw text with its own `interesting` regex, so the base class overrides BOTH
# set_cdata_mode (the scan boundary) and parse_endtag (the closer itself) - overriding only the
# latter would leave a pre-3.13 parser consuming `</script data-x>` as raw data and running the
# region on to the document's next canonical closer, swallowing the authored markup between.
# `</` opens an end TAG only when a tag NAME follows; `</ junk` opens a bogus comment instead.
_TAG_NAME_START_RE = re.compile(r"[a-zA-Z]")

# `<![CDATA[ ... ]]>` is a CDATA section only when the CURRENT NODE is a foreign (SVG/MathML)
# element; when it is an HTML element a browser treats `<!` + junk as a BOGUS COMMENT that ends
# at the very first `>`, so markup after that `>` is LIVE. html.parser consumes the whole marked
# section in every context (and, before 3.13, raises on an unknown section keyword), which would
# hide real elements from every check built on the parse.
_FOREIGN_ROOTS = frozenset(("svg", "math"))

# Children of these are inserted in the HTML namespace, so foreign content ends at them.
_SVG_HTML_INTEGRATION = frozenset(("foreignobject", "desc", "title"))
_MATHML_TEXT_INTEGRATION = frozenset(("mi", "mo", "mn", "ms", "mtext"))
_MATHML_GLYPH_TAGS = frozenset(("mglyph", "malignmark"))
_ANNOTATION_HTML_ENCODINGS = frozenset(("text/html", "application/xhtml+xml"))

# The HTML start tags that BREAK OUT of foreign content: a browser pops the open foreign
# elements and inserts these in the HTML namespace. Without them a malformed foreign wrapper
# (`<svg><p><![CDATA[>...`) would keep a stale `svg` on the stack and hide live markup.
_FOREIGN_BREAKOUT_TAGS = frozenset((
    "b", "big", "blockquote", "body", "br", "center", "code", "dd", "div", "dl", "dt", "em",
    "embed", "h1", "h2", "h3", "h4", "h5", "h6", "head", "hr", "i", "img", "li", "listing",
    "menu", "meta", "nobr", "ol", "p", "pre", "ruby", "s", "small", "span", "strong", "strike",
    "sub", "sup", "table", "tt", "u", "ul", "var",
))
_FONT_BREAKOUT_ATTRS = ("color", "face", "size")

# An ATTRIBUTE VALUE's character references, decoded the way a BROWSER decodes them: a NUMERIC
# reference always resolves, a NAMED one only when it is an exact match that is not followed by
# `=` - so `id="&notit;"` keeps the literal `&notit;`. Python 3.13 applies that rule; 3.12
# unescapes the whole value with `html.unescape()`, which resolves the `&not` inside `&notit;`
# and yields `\u00acit;`. Left to the host, one document would carry different `id`, `class`,
# `href`, `src`, `content` and `data-*` values per interpreter - a different duplicate-id,
# link, meta-handshake or companion-resource verdict for the same bytes. So the rule and the
# start-tag attribute tokenizer it runs over are vendored here and applied to the RAW start
# tag, and the host's own decoding is never read (CMH-VAL-21).
#
# The three regexes and `_replace_attr_charref` come from CPython 3.13's `Lib/html/parser.py`
# (`attr_charref`, `tagfind_tolerant`, `attrfind_tolerant`, `_replace_attr_charref`), which is
# the browser-correct version; keep them in step with that file, not with whatever the running
# interpreter happens to ship. ONE deliberate DIVERGENCE: `_replace_attr_charref`'s NUMERIC
# branch resolves through `_numeric_charref()` below (the HTML tokenizer's end state) instead of
# CPython's `html.unescape()`, which is not the browser rule - do NOT resync that branch to
# CPython, or the deleted-control-character and oversized-reference bugs come back. Only the
# regexes and the NAMED branch track CPython.
_ATTR_CHARREF_RE = re.compile(r"&(#[0-9]+|#[xX][0-9a-fA-F]+|[a-zA-Z][a-zA-Z0-9]*)[;=]?")

# The C1 replacement table the HTML "numeric character reference end state" applies. The five
# code points in 0x80-0x9F that are NOT listed (0x81, 0x8D, 0x8F, 0x90, 0x9D) are kept as
# themselves, as any other control character is.
_C1_CHARREF_REPLACEMENTS = {
    0x80: "\u20ac", 0x82: "\u201a", 0x83: "\u0192", 0x84: "\u201e", 0x85: "\u2026",
    0x86: "\u2020", 0x87: "\u2021", 0x88: "\u02c6", 0x89: "\u2030", 0x8a: "\u0160",
    0x8b: "\u2039", 0x8c: "\u0152", 0x8e: "\u017d", 0x91: "\u2018", 0x92: "\u2019",
    0x93: "\u201c", 0x94: "\u201d", 0x95: "\u2022", 0x96: "\u2013", 0x97: "\u2014",
    0x98: "\u02dc", 0x99: "\u2122", 0x9a: "\u0161", 0x9b: "\u203a", 0x9c: "\u0153",
    0x9e: "\u017e", 0x9f: "\u0178",
}

# The largest scalar value a reference can name, as a digit COUNT: anything longer than this
# already exceeds 0x10FFFF, so it resolves without an integer conversion (see _numeric_charref).
_MAX_CHARREF_DIGITS = {10: len("1114111"), 16: len("10FFFF")}

# A numeric reference the HOST's own attribute decode must never see: a decimal run past
# Python's integer conversion limit RAISES there, and a hex run has no such limit and builds a
# big integer whose value is then thrown away. The two bases are kept apart so a decimal run
# cannot match hex digits (`&#aaaa...` is not a numeric reference at all). The threshold is far
# above anything an authored document contains and far below the interpreter's limit (~4300
# digits), which is what keeps the recovery path unreachable by ordinary markup: routing a
# merely zero-padded `&#0000065;` onto a second tokenizer would decide "is this tag an element,
# and where does it end" by a different rule than the rest of the document - the
# one-document-two-views hazard this module exists to close. Each alternative is one greedy
# quantifier with no preceding optional run, so a hostile digit sequence cannot make it
# backtrack.
_BIG_CHARREF_RE = re.compile(r"&#(?:[xX][0-9a-fA-F]{32,}|[0-9]{32,})")

# RCDATA (and with it `set_cdata_mode`'s `escapable` keyword) reached `html.parser` in CPython
# 3.13; an older host has no such notion, so its start-tag branch has none either.
_HOST_RCDATA_ELEMENTS = frozenset(getattr(HTMLParser, "RCDATA_CONTENT_ELEMENTS", ()))

# Frozen at import so the membership test cannot follow a mutation of the host's table. (The
# expansion below still calls `html.unescape`, which reads the live table, so this is a
# lookup-side snapshot, not a full freeze of the entity data.)
_HTML5_ENTITY_NAMES = frozenset(_HTML5_ENTITIES)

_TAG_NAME_RE = re.compile(r"([a-zA-Z][^\t\n\r\f />]*)(?:[\t\n\r\f ]|/(?!>))*")

# A browser folds a tag or attribute NAME ASCII-case-insensitively; Python's `str.lower()` folds
# outside ASCII too. U+212A KELVIN SIGN is the only character that collides (it lowercases to an
# ASCII "k"), and that is enough to read `data-\u212aey` as `data-key`, `<lin\u212a>` as `<link>`
# and `</mar\u212a>` as `</mark>` - names a browser keeps distinct. `html.parser` hands its
# handlers the Unicode fold, so every name the checks key on is re-folded here, the way the
# raw-text closer already is through `re.ASCII` (CMH-VAL-21 clause 7).
_ASCII_LOWER = {c: c + 32 for c in range(ord("A"), ord("Z") + 1)}

# A tag name survives UNFOLDED only in the source, so it is stashed as each tag is parsed (see
# `_BrowserTagNames`). Everything up to HTML whitespace, `/` or `>` is the name.
_RAW_TAG_NAME_RE = re.compile(r"[^\t\n\r\f />]*")


def _ascii_lower(name):
    return name.translate(_ASCII_LOWER)


_SHADOW_HOST_NAMES = frozenset((
    "article", "aside", "blockquote", "body", "div", "footer", "h1", "h2", "h3", "h4",
    "h5", "h6", "header", "main", "nav", "p", "section", "span",
))
_RESERVED_CUSTOM_ELEMENT_NAMES = frozenset((
    "annotation-xml", "color-profile", "font-face", "font-face-src", "font-face-uri",
    "font-face-format", "font-face-name", "missing-glyph",
))


def _is_pcen_char(ch):
    cp = ord(ch)
    return (
        ch in "-._" or "0" <= ch <= "9" or "a" <= ch <= "z" or cp == 0xB7
        or 0xC0 <= cp <= 0xD6 or 0xD8 <= cp <= 0xF6 or 0xF8 <= cp <= 0x37D
        or 0x37F <= cp <= 0x1FFF or 0x200C <= cp <= 0x200D
        or 0x203F <= cp <= 0x2040 or 0x2070 <= cp <= 0x218F
        or 0x2C00 <= cp <= 0x2FEF or 0x3001 <= cp <= 0xD7FF
        or 0xF900 <= cp <= 0xFDCF or 0xFDF0 <= cp <= 0xFFFD
        or 0x10000 <= cp <= 0xEFFFF
    )


def _can_host_shadow_root(tag, namespace="html"):
    """Whether an element can be an attachShadow()/declarative-shadow host."""
    name = _ascii_lower(tag or "")
    if namespace != "html":
        return False
    if name in _SHADOW_HOST_NAMES:
        return True
    return (
        bool(name) and "a" <= name[0] <= "z" and "-" in name
        and name not in _RESERVED_CUSTOM_ELEMENT_NAMES
        and all(_is_pcen_char(ch) for ch in name)
    )


# The document's TEXT character references, decoded by the same BROWSER rule the attribute path
# uses (CMH-VAL-21). With `convert_charrefs=True` the host decodes each text run inside
# `goahead()` with `html.unescape()`, which is not that rule: it DELETES the code points it
# deems invalid (so `&#1;` and `&#xfffe;` vanish from prose a browser keeps) and RAISES on a
# numeric reference past Python's integer conversion limit. That `ValueError` escapes `feed()`,
# and every parse entry point swallows an exception into a truncated parse - so ONE oversized
# reference in prose reported the whole document as unparseable, where a browser renders U+FFFD
# and reads on.
#
# Only the NUMERIC branch diverges from the host; the NAMED branch is html.unescape's own
# longest-match rule, which IS the text rule (`&notit;` is `\u00ac` + `it;` - deliberately not
# the attribute rule above, where the same source stays literal).
_TEXT_CHARREF_RE = re.compile(r"&(#[0-9]+;?|#[xX][0-9a-fA-F]+;?|[^\t\n\f <&#;]{1,32};?)")


def _replace_text_charref(m):
    body = m.group(1)
    if body[0] == "#":
        # `_numeric_charref()` (below) is the HTML tokenizer's end state, and it BOUNDS the digit
        # run before any integer conversion, so an oversized reference is U+FFFD and cheap.
        return _numeric_charref(body.rstrip(";"))
    if body in _HTML5_ENTITY_NAMES:
        return _HTML5_ENTITIES[body]
    for x in range(len(body) - 1, 1, -1):
        if body[:x] in _HTML5_ENTITY_NAMES:
            return _HTML5_ENTITIES[body[:x]] + body[x:]
    return "&" + body


def _unescape_text(text):
    if "&" not in text:
        return text
    return _TEXT_CHARREF_RE.sub(_replace_text_charref, text)


# The code points that RENDER NOTHING, for a check asking "is there text a reader can SEE?".
# `Cc` (the C0/C1 controls and DEL) and `Cf` (the format characters - a zero-width space, a bidi
# mark, a BOM) are read from the running interpreter's Unicode data, which is safe because an
# ASSIGNED code point never changes category. The NONCHARACTERS are tested arithmetically rather
# than as the `Cn` category, because `Cn` also covers everything UNASSIGNED in the host's Unicode
# version - so a character assigned in a newer Unicode (which a browser on a current OS really
# draws) would be invisible on one interpreter and visible on the next, the exact
# one-document-two-verdicts hazard this module exists to close (CMH-VAL-21).
# U+FFFD is deliberately VISIBLE: a browser draws the replacement glyph.
_INVISIBLE_CATEGORIES = frozenset(("Cc", "Cf"))


def _is_noncharacter(cp):
    return 0xFDD0 <= cp <= 0xFDEF or (cp & 0xFFFE) == 0xFFFE


def visible_text(text):
    """`text` with the characters a reader cannot SEE removed. Whitespace is KEPT, so a caller
    decides for itself whether whitespace-only counts as text.

    Shared because more than one check asks the question - the document-title requirement and the
    contrast scan's "does this element show text?" - and they must answer it identically. It
    matters at all because a TEXT character reference is decoded by the BROWSER rule rather than
    deleted by `html.unescape`, so `&#1;` now reaches a check as U+0001 instead of vanishing.
    """
    return "".join(c for c in (text or "")
                   if unicodedata.category(c) not in _INVISIBLE_CATEGORIES
                   and not _is_noncharacter(ord(c)))


def _bind_text_goahead():
    """The host's OWN `goahead`, with its single `unescape` global rebound to the decode above.

    The two alternatives were both worse. Rewriting `rawdata` is not an option: every check
    reads RAW offsets into the original document (`code_block_spans()`, `content_marker_scan()`,
    every span this module reports). Switching to `convert_charrefs=False` would change how
    every text run is DELIVERED - one `handle_data` per run becomes one per fragment between
    references - which is a different document to every check that reads text, for a defect that
    is only about how a run is decoded. Re-binding one global keeps the tokenizer byte-for-byte
    the host's (same run boundaries, same positions, same dispatch) and replaces only the decode.

    Returns None if the host's `goahead` no longer resolves `unescape` as a global, in which case
    the parsers keep the host's method and an oversized reference in TEXT fails the parse closed
    the way it always did (never silently, since the covering tests pin this).
    """
    host = HTMLParser.goahead
    if "unescape" not in host.__code__.co_names or host.__closure__:
        return None
    namespace = dict(_html_parser.__dict__)
    namespace["unescape"] = _unescape_text
    bound = FunctionType(host.__code__, namespace, host.__name__, host.__defaults__)
    bound.__kwdefaults__ = host.__kwdefaults__
    return bound


_TEXT_GOAHEAD = _bind_text_goahead()
_TEXT_CHARREF_BOUNDED = _TEXT_GOAHEAD is not None


class _BrowserTextCharrefs(HTMLParser):
    """Text runs decoded by the BROWSER rule rather than by `html.unescape` (CMH-VAL-21).

    Every parser in this package derives from it, so an oversized reference in prose can no
    longer report a whole document as unparseable, and a control character or noncharacter a
    browser keeps is not silently deleted from the text the checks read.
    """

    goahead = _TEXT_GOAHEAD or HTMLParser.goahead


class _BrowserTagNames(_BrowserTextCharrefs):
    """Tag names folded the way a BROWSER folds them: ASCII-only (CMH-VAL-21 clause 7).

    Mixed into every parser in this package that keys on a tag name, because `html.parser` folds
    with `str.lower()` before it calls a handler - which would make `<lin\u212a>` a `<link>` and
    `</mar\u212a>` a `</mark>` closer.
    """

    _raw_tag_name = ""

    def parse_starttag(self, i):
        self._stash_tag_name(i + 1)
        return super().parse_starttag(i)

    def parse_endtag(self, i):
        self._stash_tag_name(i + 2)
        return super().parse_endtag(i)

    def _stash_tag_name(self, i):
        m = _RAW_TAG_NAME_RE.match(self.rawdata, i)
        self._raw_tag_name = m.group(0) if m else ""

    def _browser_tag(self, tag):
        """`tag` as a BROWSER names it. The stashed raw name is used only when it is THIS tag
        under the host's own fold; anything else - a name the host truncated at a NUL, a handler
        reached with a tag it was passed rather than one it just parsed - folds `tag` itself,
        which leaves it exactly as it already was."""
        raw = self._raw_tag_name
        return _ascii_lower(raw) if raw and raw.lower() == tag else _ascii_lower(tag)


_ATTR_RE = re.compile(r"""
  ((?<=['"\t\n\r\f /])[^\t\n\r\f />][^\t\n\r\f /=>]*)   # attribute name
  ([\t\n\r\f ]*=[\t\n\r\f ]*                            # value indicator
    ('[^']*'                                            # single-quoted value
    |"[^"]*"                                            # double-quoted value
    |(?!['"])[^>\t\n\r\f ]*                             # bare value
    )
   )?
  (?:[\t\n\r\f ]|/(?!>))*                               # trailing whitespace
""", re.VERBOSE)


def _numeric_charref(body):
    """The code point a NUMERIC character reference names, resolved the way a BROWSER resolves
    it (the HTML "numeric character reference end state"), not the way `html.unescape` does
    (CMH-VAL-21).

    `html.unescape` is not the browser rule, and the two disagree on the same bytes on EVERY
    interpreter - this is not the 3.12/3.13 attribute drift the rest of this section is about:

      - it DELETES the code points it considers invalid, so `&#1;`, `&#x7f;` and `&#xfffe;`
        vanish where a browser keeps U+0001, U+007F and U+FFFE. A validator-visible `id`,
        `content`, `href` or `data-*` then differs from the DOM value, which is exactly the
        class of mismatch this module exists to close;
      - it raises `ValueError` on a reference with more digits than Python's integer conversion
        limit, where a browser just yields U+FFFD.

    So the end state is implemented here: U+FFFD for the null character, for a surrogate and
    for anything past U+10FFFF, the C1 remapping above, and every other code point kept. The
    digit run is BOUNDED before any integer conversion, so the decode is total (and cheap) for
    an arbitrarily long reference.
    """
    if body[1] in "xX":
        digits, base = body[2:], 16
    else:
        digits, base = body[1:], 10
    digits = digits.lstrip("0")
    if not digits:
        return "\ufffd"                             # `&#0;` is a null character reference
    if len(digits) > _MAX_CHARREF_DIGITS[base]:
        return "\ufffd"                             # past U+10FFFF without converting it
    num = int(digits, base)
    if num in _C1_CHARREF_REPLACEMENTS:
        return _C1_CHARREF_REPLACEMENTS[num]
    if num > 0x10FFFF or 0xD800 <= num <= 0xDFFF:
        return "\ufffd"
    return chr(num)


def _replace_attr_charref(m):
    ref = m.group(0)
    body = m.group(1)
    if body[0] == "#":
        trailing = ref[len(body) + 1:]
        # A numeric reference resolves with or without the `;`; a `;` is consumed and any other
        # trailing character (`=`) is reconsumed as part of the value, as a browser does.
        return _numeric_charref(body) + ("" if trailing == ";" else trailing)
    if not ref.endswith("=") and ref[1:] in _HTML5_ENTITY_NAMES:
        return unescape(ref)
    return ref


def _unescape_attr_value(value):
    return _ATTR_CHARREF_RE.sub(_replace_attr_charref, value)


# The character classes the HTML5 tokenizer's tag states switch on. CR counts as whitespace
# because a browser normalizes CR / CRLF to LF before tokenizing, so it can never be anything
# else here (CPython's own tag regexes take the same shortcut).
_TAG_WS = "\t\n\r\f "
_TAG_WS_SLASH = "\t\n\r\f /"
_TAG_NAME_STOP = "\t\n\r\f />"
_ATTR_NAME_STOP = "\t\n\r\f /=>"
_UNQUOTED_VALUE_STOP = "\t\n\r\f >"


def _fold_nul(text):
    """A NUL, replaced with U+FFFD the way a browser replaces it.

    HTML5's tag-name, attribute-name and attribute-value states all report an
    unexpected-null-character parse error and append U+FFFD. html.parser does neither: before
    3.13 it TRUNCATES a tag name at a NUL (so `<div\x00x>` is a real `<div>`) and from 3.13 it
    keeps the NUL, so one document carried a different element name per interpreter."""
    return text.replace("\x00", "\ufffd") if "\x00" in text else text


def _scan_start_tag(rawdata, i):
    """The extent of the start tag opening at `i` (a `<` followed by an ASCII letter), decided
    the way a BROWSER decides it: `(end, tag, self_closing)`, where `end` is the index just
    past the `>`, or None when the tag never finishes.

    This is the HTML5 tag-open / tag-name / before-attribute-name / attribute-name /
    after-attribute-name / before-attribute-value / attribute-value / after-attribute-value /
    self-closing-start-tag states, applied EXPLICITLY (CMH-VAL-21). html.parser leaves the same
    question to `check_for_whole_start_tag`, which reads whichever regex the host ships -
    `locatestarttagend_tolerant` before 3.13, `locatetagend` from 3.13 - and neither is the
    browser's rule, so the two interpreters disagree about where a pathological start tag ends,
    and sometimes about whether there is a start tag at all. The two known drivers:

      - a NUL in the tag name (pre-3.13 stops the name there, so `<script\x00>` opens a raw-text
        region that swallows the rest of the document; a browser keeps the name with a U+FFFD
        and opens nothing);
      - an UNTERMINATED quoted attribute value. A browser runs the value to its matching quote
        and, finding EOF instead, applies the eof-in-tag error: the whole tag is DISCARDED, and
        with it every character after the opening quote. Both hosts instead fail to match a
        value, re-read what follows as further attribute NAMES, and close the tag at the next
        `>` - resurrecting elements a browser never builds.

    Returning None is that eof-in-tag case; the caller resolves it (drop at end of input, ask
    for more data before it). Scanned character by character rather than matched with one
    regex: the "a quote only opens a value after `=`" rule needs nested alternation to express,
    which backtracks exponentially on a hostile document, and this parser reads untrusted input.
    """
    n = len(rawdata)
    j = i + 1
    name_start = j
    while j < n and rawdata[j] not in _TAG_NAME_STOP:
        j += 1
    tag = _fold_nul(_ascii_lower(rawdata[name_start:j]))
    while True:
        # before-attribute-name / after-attribute-value: a `/` here is the self-closing slash
        # only when the `>` follows it immediately; anywhere else it is just skipped.
        slash = False
        while j < n and rawdata[j] in _TAG_WS_SLASH:
            slash = rawdata[j] == "/"
            j += 1
        if j >= n:
            return None
        if rawdata[j] == ">":
            return j + 1, tag, slash
        # attribute-name: the FIRST character is taken unconditionally, so a `=` where a name
        # belongs starts a name called `=` rather than a value.
        j += 1
        while j < n and rawdata[j] not in _ATTR_NAME_STOP:
            j += 1
        # after-attribute-name: only whitespace may sit between the name and its `=`.
        k = j
        while k < n and rawdata[k] in _TAG_WS:
            k += 1
        if k >= n:
            return None
        if rawdata[k] != "=":
            continue                      # a bare attribute; re-dispatch on rawdata[j]
        k += 1
        while k < n and rawdata[k] in _TAG_WS:
            k += 1
        if k >= n:
            return None
        quote = rawdata[k]
        if quote in "\"'":
            close = rawdata.find(quote, k + 1)
            if close < 0:
                return None               # the value ran to EOF: the tag is discarded
            j = close + 1
            continue
        if quote == ">":
            return k + 1, tag, False      # missing-attribute-value: the tag ends here
        while k < n and rawdata[k] not in _UNQUOTED_VALUE_STOP:
            k += 1
        if k >= n:
            return None
        j = k


def _browser_attrs(parser, tag, attrs):
    """The start tag's `(name, value)` attributes, re-derived from the RAW start tag `parser`
    just accepted and decoded by the browser rule above, so they are the same on every
    interpreter.

    The re-tokenization is NOT skipped for a tag whose raw text carries no `&`. That looks
    safe but is not: the pre-3.13 host splits attributes with `\\s` and `=+` where the browser
    (and the tokenizer above) use HTML whitespace and a single `=`, so `<div id==x>` is
    `id="x"` there and `id="=x"` here, and `<div id=a\\xa0b>` is two attributes there and one
    here - both without a single character reference. Only the DECODE is short-circuited
    below, per value, which is the part a missing `&` really does make a no-op.

    Falls back to the host's own list only when the raw start tag cannot be trusted to be THIS
    tag's: `html.parser` clears it in `parse_starttag()` alone, so a caller outside a start-tag
    handler would otherwise silently read the PREVIOUS element's attributes. The pre-3.13 host
    TRUNCATES a tag name at a NUL where a browser (and the vendored tokenizer) do not, so a
    name that matches up to a NUL is still THIS tag and is accepted - falling back there would
    hand the host's drifting values straight back."""
    raw = parser.get_starttag_text()
    if not raw:
        return attrs
    found = _tokenize_raw_tag(raw, tag)
    if found is None:
        return attrs
    return found[0]


def _tokenize_raw_tag(raw, tag):
    """`tag`'s `(name, value)` attributes read from its RAW start tag text, paired with the
    offset attribute tokenization stopped at (which is what tells a caller whether the tag
    really closed). None when `raw` is not this tag's own start tag."""
    m = _TAG_NAME_RE.match(raw, 1)
    if m is None:
        return None
    name = m.group(1)
    # Accepted under EITHER fold: a caller inside a start-tag handler passes the ASCII-folded
    # name, while one reading `html.parser`'s own `tag` passes the Unicode fold, and neither may
    # lose the browser decoding by looking foreign.
    if not any(n == tag or n.split("\x00", 1)[0] == tag or _fold_nul(n) == tag
               for n in (_ascii_lower(name), name.lower())):
        return None
    out = []
    k, end = m.end(), len(raw)
    while k < end:
        m = _ATTR_RE.match(raw, k)
        if m is None:
            break
        name, has_value, value = m.group(1, 2, 3)
        if not has_value:
            value = None
        elif value[:1] == "'" == value[-1:] or value[:1] == '"' == value[-1:]:
            value = value[1:-1]
        if value:
            value = _fold_nul(value)
            if "&" in value:
                value = _unescape_attr_value(value)
        out.append((_fold_nul(_ascii_lower(name)), value))
        k = m.end()
    return out, k


def _browser_attrs_dict(parser, tag, attrs):
    """The start tag's attribute dict, with browser-decoded values. HTML5 (and browsers) keep
    the FIRST occurrence of a duplicated attribute, so `<main id="a" id="b">` is id="a"; a dict
    comprehension would keep the last, so set-if-absent is what matches the browser."""
    d = {}
    for k, v in _browser_attrs(parser, tag, attrs):
        kl = _ascii_lower(k or "")
        if kl not in d:
            d[kl] = v if v is not None else ""
    return d


# The PUBLIC names of the two helpers above, for the tools OUTSIDE this package - the deck
# validator, the contrast scanner and the authoring tools - which reach them through the
# `tools/_browser_attrs.py` shim. Each of those kept its own host-trusting attribute dict, so
# one document was read one way by the validator and another way by the tool beside it
# (CMH-VAL-21). Callers pass the parser they are handling a start tag for; everything else is
# the same rule the two tolerant passes here apply.
browser_attrs = _browser_attrs
browser_attrs_dict = _browser_attrs_dict

# A TAG name folds by the same rule, so those tools read it from the same place rather than
# keeping a second copy of clause 7: they derive their scanners from `BrowserTagNames` (through
# the same shim) and name each element with its `_browser_tag()`.
ascii_lower = _ascii_lower
can_host_shadow_root = _can_host_shadow_root
BrowserTagNames = _BrowserTagNames

# The same package-shared TEXT decode, for the one scanner OUTSIDE this package that parses a whole
# document (`cmhval/contrast.py`). None when the host's `goahead` cannot be re-bound; the shim beside
# the tools passes its own default in that case.
text_goahead = _TEXT_GOAHEAD


class _BrowserStartTagExtent(_BrowserTagNames):
    """Every start tag's EXTENT, decided by the vendored scanner instead of by the host
    (CMH-VAL-21).

    `html.parser.parse_starttag()` asks `check_for_whole_start_tag()` where the tag ends, and
    that reads whichever regex the interpreter ships, so the same bytes tokenize differently on
    Python 3.12 and 3.13 (see `_scan_start_tag`). Replacing the whole method - not just the
    extent - is what closes it: the host also derives the tag NAME with its own
    `tagfind_tolerant` (which truncates at a NUL before 3.13) and falls back to emitting the
    tag's SOURCE AS DATA whenever its own attribute regex stops short of the end it found.

    Every parser in the checks package that reads attributes derives from this, so a document
    cannot be two documents depending on which check is asking or which Python is running.
    `check_for_whole_start_tag()` is vendored too, so the oversized-reference recovery path in
    the subclass below - the one place a start tag still reaches the host's own machinery -
    draws the same boundary.
    """

    # The end-of-input flag the eof-in-tag drop is armed by. Exactly one of `close()` (the
    # incremental callers) and `parse_document()` (the whole-document one) must set it before
    # the final `goahead`; `reset()` clears it for the next document. A subclass that overrides
    # `close()` without calling super() would silently stop discarding a truncated tag.
    _final = False

    def reset(self):
        # `HTMLParser` instances are reusable, and `reset()` is what starts the next document -
        # so the end-of-input flag has to be cleared here, not only set in `close()`. Leaving it
        # set would make every later mid-stream "incomplete" look like EOF and silently discard
        # a tag that was merely split across two `feed()` chunks. (`HTMLParser.__init__` calls
        # this, so a fresh instance starts clean too.) It clears THIS class's state only: a
        # subclass's own per-document stacks survive, so reuse is safe for the incremental
        # scanners and a new parser is still the right thing per document elsewhere.
        self._final = False
        super().reset()

    def close(self):
        self._final = True
        super().close()

    def check_for_whole_start_tag(self, i):
        scanned = _scan_start_tag(self.rawdata, i)
        return -1 if scanned is None else scanned[0]

    def parse_starttag(self, i):
        rawdata = self.rawdata
        # The host stamps the raw tag here before decoding anything, and `_browser_attrs()`
        # reads it back through `get_starttag_text()`; this path never reaches the host, so it
        # stamps it itself - same name, same lifetime.
        self._HTMLParser__starttag_text = None
        scanned = _scan_start_tag(rawdata, i)
        if scanned is None:
            return self._drop_if_truncated(-1)
        end, tag, self_closing = scanned
        raw = rawdata[i:end]
        self._HTMLParser__starttag_text = raw
        self._stash_tag_name(i + 1)
        self.lasttag = tag
        found = _tokenize_raw_tag(raw, tag)
        attrs = found[0] if found is not None else []
        if self_closing:
            self.handle_startendtag(tag, attrs)
        else:
            self.handle_starttag(tag, attrs)
            self._enter_cdata_mode(tag)
        return end

    def _drop_if_truncated(self, k):
        """EOF inside a TAG discards the tag, as a browser does (the HTML5 eof-in-tag error).

        Mid-stream the same shape only means "not yet complete", so -1 is returned and the base
        class asks for more input - an incremental caller must not lose a tag merely split
        across two `feed()` chunks. At end of input the host resolves it its own way instead:
        before 3.12.11 / 3.13.5 the unfinished tag's SOURCE is handed to handle_data (so
        `<p>hi<div class="x` leaves `hi<div class="x` as prose, and inside raw text it lands in
        the element body), while a fixed host drops it.
        """
        if k < 0 and self._final:
            return len(self.rawdata)
        return k

    def _enter_cdata_mode(self, tag):
        """Enter raw text exactly as the host would have, since this class replaces the
        method that used to do it. WHICH elements hold text is a separate boundary and is
        deliberately untouched here: getting it right without a namespace stack is not
        possible (an `<svg><title>` is an HTML integration point whose children a browser
        really does build, so calling it RCDATA would hide them), so the tolerant passes
        apply the browser set from their own handle_starttag - where the namespace IS
        known - and every other parser keeps the set it already had."""
        self._enter_host_cdata_mode(tag)


class _BrowserStartTag(_BrowserStartTagExtent):
    """A start tag the HOST's own attribute decode cannot handle is still a start tag
    (CMH-VAL-21).

    `html.parser` decodes every attribute value inside `parse_starttag()`, and its decoder
    RAISES on a numeric character reference with more digits than Python's integer conversion
    limit. That `ValueError` escapes `feed()`, and every parse entry point here swallows an
    exception into a TRUNCATED parse - so ONE oversized reference hid every finding after that
    tag, where a browser simply resolves it to U+FFFD and carries on.

    Such a tag is therefore taken away from the host BEFORE it decodes anything and dispatched
    from its RAW text through the vendored tokenizer, whose numeric decode is bounded. Detecting
    it up front rather than catching the host's `ValueError` is what makes this safe: the host
    calls `handle_starttag()` / `handle_startendtag()` / `handle_data()` INSIDE
    `parse_starttag()`, so catching would also swallow a `ValueError` from a subclass's own
    handler and dispatch that tag a SECOND time. It also keeps the host from converting a huge
    hex reference (which has no digit limit) whose value is discarded.

    SCOPE: attribute values only, because the host decodes them inside `parse_starttag()`. An
    oversized reference in the document's TEXT is decoded in `goahead()` instead, by the bounded
    rule `_BrowserTextCharrefs` installs there.
    """

    _big_charref_scanned = None   # the rawdata buffer `_big_charref_found` was computed from
    _big_charref_found = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._big_charref_scanned = None
        self._big_charref_found = False

    def parse_starttag(self, i):
        if self._buffer_has_big_charref():
            endpos = self.check_for_whole_start_tag(i)
            if endpos >= 0 and _BIG_CHARREF_RE.search(self.rawdata, i, endpos):
                self._stash_tag_name(i + 1)
                return self._starttag_from_raw(i, endpos)
        return super().parse_starttag(i)

    def _buffer_has_big_charref(self):
        """Whether the buffer holds such a reference AT ALL, memoized per `feed()` chunk. The
        per-tag probe above costs a second `check_for_whole_start_tag()`, so it is gated on one
        linear scan that no real document ever answers yes to."""
        rawdata = self.rawdata
        if self._big_charref_scanned is not rawdata:
            self._big_charref_scanned = rawdata
            self._big_charref_found = _BIG_CHARREF_RE.search(rawdata) is not None
        return self._big_charref_found

    def _starttag_from_raw(self, i, endpos):
        raw = self.rawdata[i:endpos]
        # The host stamps this before decoding; the fallback never reaches the host, and
        # `_browser_attrs()` reads it back through `get_starttag_text()`, so stamp it here.
        self._HTMLParser__starttag_text = raw
        m = _TAG_NAME_RE.match(raw, 1)
        # ASCII-only folding, as a browser names a tag (clause 7) - `str.lower()` here would
        # make `<lin\u212a>` a `<link>` on exactly this path.
        tag = None if m is None else _ascii_lower(m.group(1))
        found = None if tag is None else _tokenize_raw_tag(raw, tag)
        if found is None:
            self.handle_data(raw)
            return endpos
        self.lasttag = tag
        attrs, k = found
        # The host decides start-vs-startend from the tail attribute tokenization STOPPED at,
        # never from the raw text: an unquoted value swallows a trailing `/`, so `<div a=b/>` is
        # a normal start tag whose value is `b/`. Reading `raw` instead would self-close it and
        # skip the raw-text mode below, exposing a `<script>`/`<textarea>` body as markup.
        end = raw[k:].strip()
        if end not in (">", "/>"):
            self.handle_data(raw)
            return endpos
        if end == "/>":
            self.handle_startendtag(tag, attrs)
        else:
            self.handle_starttag(tag, attrs)
            self._enter_host_cdata_mode(tag)
        return endpos

    def _enter_host_cdata_mode(self, tag):
        """The host's OWN post-dispatch raw-text branch, mirrored so a tag taken off the fallback
        path enters exactly the mode every other tag in the same parser enters. (A
        `_BrowserBoundaries` subclass installs the BROWSER's wider set from its own
        `handle_starttag`, exactly as it does on the host path; a plain `HTMLParser` subclass
        gets the host's set, which is what it gets for every other tag.)"""
        if tag in self.CDATA_CONTENT_ELEMENTS:
            escapable = False
        elif not _HOST_RCDATA_ELEMENTS:
            return                      # a pre-3.13 host's branch ends here
        elif tag == "plaintext" or (getattr(self, "scripting", False) and tag == "noscript"):
            escapable = False
        elif tag in getattr(self, "RCDATA_CONTENT_ELEMENTS", ()):
            escapable = True
        else:
            return
        if _HOST_RCDATA_ELEMENTS:
            self.set_cdata_mode(tag, escapable=escapable)
        else:
            self.set_cdata_mode(tag)


# The PUBLIC name of the start-tag base above, for the tools OUTSIDE this package, which reach it
# through the `tools/_browser_attrs.py` shim for the same reason they reach the attribute helpers
# there. A parser built on a bare `html.parser.HTMLParser` draws the tag EXTENT with whatever regex
# the interpreter ships and lets the host decode the attribute values, so it raises on an oversized
# numeric reference the rest of the validator now resolves to U+FFFD - which silently disabled a
# whole check on a document every other parse reads (CMH-VAL-21).
browser_start_tag_parser = _BrowserStartTag


def _end_tag_close(rawdata, i):
    """Index just past the `>` that ends the tag starting at `i`, or -1 if it never closes.

    A browser ends a tag at the first `>` that is not inside a QUOTED ATTRIBUTE VALUE, and a
    quoted value only begins AFTER `=` - so a bare `"` sitting where an attribute NAME belongs
    (`</script " >`) is just an invalid name character and does not swallow the `>`. Scanned
    rather than matched with one regex: expressing "quoted only after =" as nested alternation
    backtracks exponentially on a hostile document, and this parser reads untrusted input.
    """
    n = len(rawdata)
    j = i
    while j < n:
        c = rawdata[j]
        if c == ">":
            return j + 1
        if c == "=":
            j += 1
            while j < n and rawdata[j] in " \t\n\r\f":
                j += 1
            if j < n and rawdata[j] in "\"'":
                k = rawdata.find(rawdata[j], j + 1)
                if k < 0:
                    return -1
                j = k + 1
            continue
        j += 1
    return -1


class _BrowserBoundaries(_BrowserStartTag):
    """Where one element ENDS and the next begins, decided the way a BROWSER decides it and
    IDENTICALLY on every interpreter (CMH-VAL-21).

    Both tolerant passes over a document derive from this - `_DocParser` (the chart, link, id,
    heading, meta and anchor view) and `_CodeSpanParser` (the `<pre>`/`<code>` spans) - so one
    document can never be two different documents depending on which check is asking or which
    Python is running. Every boundary the host interpreter gets wrong is applied here:

      - the whole raw-text / RCDATA set is raw text (html.parser knows only `script`/`style`
        before 3.13, and `noscript` on no version), and NOTHING is raw text inside FOREIGN
        content, where even a `<script>` or `<style>` body is markup a browser builds;
      - a raw-text element closes on `</name` followed by whitespace, `/` or `>`;
      - a comment closes at `-->`, at the legacy `--!>`, and abruptly at `<!-->` / `<!--->` -
        and at nothing else, in particular NOT at `-- >`;
      - an unterminated comment or declaration consumes the rest of the document;
      - `<![CDATA[ ... ]]>` is a section only inside foreign content, elsewhere a bogus comment
        ending at the first `>`.

    The CDATA rule needs to know the namespace of the CURRENT NODE, so the base also keeps the
    foreign-content bookkeeping (`svg`/`math`, integration points, breakout start tags) in one
    stack that runs PARALLEL to each subclass's own element stack: subclasses push through
    `_push_ns()` and truncate through `_truncate_stacks()`, so the two never drift apart.

    The three tag handlers themselves live here too (see "the shared handler skeleton" below), so
    the ORDER those steps run in is written down ONCE and a subclass overrides only what it
    COLLECTS.
    """

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self._starts = _line_starts(html)
        self._ns = []         # [(tag, namespace, is_integration_point)], parallel to the stack
        # Parallel to `_ns`: the index of the nearest enclosing element the <p> / <li> implicit
        # close stops at (the target itself or one of its scope boundaries), or -1 when there is
        # none. Every other element is transparent to that scan, so tracking the nearest stop as
        # the stack grows answers it in O(1) instead of rescanning the stack per start tag.
        self._p_stop = []
        self._li_stop = []
        # Parallel to `_ns` too: the index of the nearest enclosing HTML-namespace <template>, or
        # -1 when there is none. An END TAG may not match an ancestor across it (see
        # `_end_tag_floor`), and reading it costs the same O(1) as the scope stops above.
        self._tpl_stop = []
        # tag -> the indices of the open elements with that name, innermost last. An end tag
        # matches the INNERMOST open element of its name, which was a backwards scan of the whole
        # stack per end tag - quadratic on a document that closes many elements it never opened.
        self._open_by_tag = {}
        self._comment_raw = None      # source of the REAL comment being handled (see below)
        # Whether the input ran out inside a comment / declaration / marked section, which a
        # browser resolves by consuming the rest of the document. Recorded because a caller
        # parsing a FRAGMENT of a larger document (the `<noscript>` fallback body) needs to know
        # that the fragment did not end in the DATA state, and so cannot be reconciled with the
        # surrounding parse.
        self.eof_unterminated = False
        # Whether the truncation running right now came from an element's OWN end tag rather than
        # from an implicit close, an ancestor's closer, a foreign-content breakout or end of
        # input. Only an end tag has a closer whose SOURCE EXTENT belongs to the element, which is
        # what a tool that REWRITES the element's bytes must know; owned here so every subclass
        # reads one answer instead of each keeping its own flag around its own truncation.
        self._end_tag_close = False
        # The HOST's own `(name, value)` list for the start tag being handled. A hook is handed
        # the browser-decoded DICT, which has already resolved a duplicated attribute the way a
        # browser resolves it; a subclass that wants every authored pair re-derives them with
        # `browser_attrs(self, tag, self._host_attrs)`, whose fallback is exactly this list.
        self._host_attrs = ()

    def parse_document(self, html):
        """Parse a COMPLETE document. Feeding the whole string at once is what lets an
        unterminated comment be resolved the way a browser resolves it (it runs to the end of
        the document) instead of the way the host interpreter happens to resolve it."""
        self._final = True
        self.feed(html)
        self.close()

    # -- offsets ----------------------------------------------------------- #

    def _off(self):
        ln, col = self.getpos()
        return self._starts[ln - 1] + col

    def _start_tag_end(self):
        return self._off() + len(self.get_starttag_text() or "")

    def _attrs_dict(self, tag, attrs):
        # The VALUES come from `_browser_attrs_dict`, not from the host, whose attribute-value
        # character-reference decoding differs across interpreters (see _ATTR_CHARREF_RE).
        return _browser_attrs_dict(self, tag, attrs)

    # -- comment provenance -------------------------------------------------- #

    @property
    def comment_raw(self):
        """The SOURCE of the comment `handle_comment()` is handling, or None when a browser
        SYNTHESIZED it from bogus markup - `<!` + junk, `<?` + anything, or `</` + junk.

        A browser really does create a comment NODE for each of those, so routing them to
        `handle_comment()` is right. What is NOT right is letting one carry the authority of a
        comment the skill's tools wrote: the region markers are a `<!-- ... -->` convention,
        and a subclass that reads them must be able to tell a marker from a comment that merely
        parses like one. Otherwise `<!BEGIN: commentable-html - CONTENT ...>` opens the content
        region and `<!END: commentable-html - JS>` sets the JS end marker, which is enough to
        validate a document whose REAL markers sit somewhere a browser would refuse.

        Only `parse_comment()` (the `<!--` path) fills this in, so a comment that reaches
        `handle_comment()` by ANY other route - including the base parser's own bogus-comment
        and end-of-input fallbacks - is bogus by DEFAULT, and a new path can only ever fail
        CLOSED. The raw source is kept rather than a bare flag because the marker COUNT views
        match exact source text (CMH-VAL-20), so a marker reader that only compared the comment
        DATA would still accept a real comment those views do not count.
        """
        return self._comment_raw

    @property
    def comment_is_bogus(self):
        return self._comment_raw is None

    def _real_comment(self, data, raw):
        self._comment_raw = raw
        try:
            self.handle_comment(data)
        finally:
            self._comment_raw = None

    # -- cross-version comment, raw-text and CDATA boundaries --------------- #

    def parse_comment(self, i, report=True):
        rawdata = self.rawdata
        if not rawdata.startswith("<!--", i):
            raise AssertionError("unexpected call to parse_comment()")
        m = _COMMENT_ABRUPT_CLOSE_RE.match(rawdata, i + 4) or _COMMENT_CLOSE_RE.search(rawdata, i + 4)
        if m:
            if report:
                self._real_comment(rawdata[i + 4:m.start()], rawdata[i:m.end()])
            return m.end()
        # Unterminated: a browser treats the rest of the document as comment data. Say so
        # explicitly rather than leaving it to the host - before 3.13 html.parser resumes
        # tokenizing after the next `>`, which resurrects markup a browser never renders.
        return self._unterminated(i + 4,
                                  (lambda d: self._real_comment(d, rawdata[i:])) if report
                                  else (lambda _d: None))

    def set_cdata_mode(self, elem, **kwargs):
        # Install the raw-text scan boundary a BROWSER uses: the region ends at `</name`
        # followed by whitespace, `/` or `>`. Before 3.13 html.parser stops only at the
        # canonical `</script>`, so `</script data-x>` is consumed as raw data and the region
        # runs on to the document's next canonical closer - swallowing the authored markup
        # between. parse_endtag below then consumes the whole end tag from that point.
        # The guard also REFUSES the base parser's own call (which fires right after
        # handle_starttag on 3.13 for its RCDATA table): NOTHING is raw text inside FOREIGN
        # content, so an SVG `<title>` - and an SVG `<script>` or `<style>` - must be parsed,
        # not swallowed as text.
        if self._ns:
            tag, ns, _integration = self._ns[-1]
            if tag == elem.lower() and ns != "html":
                return
        # The host's `escapable` argument is dropped on purpose: 3.13 decodes character
        # references inside RCDATA (`title`/`textarea`) and 3.12 has no such notion at all, so
        # honouring it would make one document's raw text differ per interpreter. Nothing here
        # reads raw text as anything but opaque prose, so it stays undecoded everywhere.
        super().set_cdata_mode(elem)
        if self.cdata_elem == _PLAINTEXT:
            # A browser never leaves plaintext mode - not even for `</plaintext>` - so the region
            # runs to the end of the document. Say so explicitly: before 3.13 html.parser has no
            # plaintext mode at all, and installing the usual closer would end it early.
            self.interesting = re.compile(r"\Z")
            return
        # ASCII-only folding, as a browser matches a tag name (so `</\u017fcript>`
        # is not a `<script>` closer, which full Unicode folding would make it).
        self.interesting = re.compile(r"</%s(?=[\t\n\r\f />])" % re.escape(self.cdata_elem),
                                      re.IGNORECASE | re.ASCII)

    def close(self):
        # Whatever has been fed is now the WHOLE document, so an unterminated comment or
        # declaration resolves the browser's way (running to the end) on this path too - a caller
        # that fed incrementally gets the same result as `parse_document()`.
        self._final = True
        super().close()
        # An UNCLOSED raw-text element runs to EOF in a browser, so its remaining body is live
        # text. html.parser only hands that tail to handle_data from CPython 3.12.11 / 3.13.5
        # (gh-135462); older hosts stall in cdata mode and leave it unparsed in `rawdata`, which
        # silently emptied the body of an unclosed `<style>`/`<script>` and hid a real unscoped
        # rule from CMH-VAL-20. Flush it here so the body reads the same on every interpreter -
        # after the host's own close(), and only while still IN cdata mode, so a host that has
        # already flushed it (and cleared the buffer) cannot double-count it.
        #
        # The tail stops at a TRUNCATED closer: once `</name` + whitespace/`/` has been seen, a
        # browser is tokenizing an end TAG, and EOF inside a tag discards it - the characters are
        # NOT part of the body. Flushing them verbatim would let `<script>x</script data-` inject
        # its own trailing text into the script body (enough to forge the layer's ready token) on
        # exactly the hosts this flush exists for.
        if self.cdata_elem is not None and self.rawdata:
            tail = self.rawdata
            truncated = self.interesting.search(tail)
            body = tail[:truncated.start()] if truncated else tail
            if body:
                self.handle_data(body)
                self.updatepos(0, len(body))
            self.rawdata = ""
        self.clear_cdata_mode()

    def parse_endtag(self, i):
        # Stashed here too: the raw-text branch below returns without ever delegating to the
        # base's own parse_endtag, so it would otherwise read the PREVIOUS tag's name.
        self._stash_tag_name(i + 2)
        elem = self.cdata_elem
        rawdata = self.rawdata
        if elem is not None and elem != _PLAINTEXT and self.interesting.match(rawdata, i):
            # `</name` followed by whitespace, `/` or `>` ends the raw-text region; the rest of
            # the END TAG is then consumed (its own quoted attribute values cannot end it early).
            close = _end_tag_close(rawdata, i)
            if close >= 0:
                self.handle_endtag(elem)
                self.clear_cdata_mode()
                return close
            if self._final:
                # A closer that never finishes: `<script>x</script data-<EOF>`. `</name` plus
                # whitespace or `/` has already moved a browser into the end-TAG states, and EOF
                # inside a tag DISCARDS the tag - those characters are not raw-text content.
                # Before 3.12.11 / 3.13.5 html.parser hands them to handle_data as element BODY
                # (enough to plant CSS in a `<style>` or forge the layer's ready token), while a
                # fixed host drops them, so the same document read two ways.
                return len(rawdata)
            return -1   # more input may still finish the tag
        if not _TAG_NAME_START_RE.match(rawdata, i + 2):
            # `</` followed by anything that is not an ASCII letter NEVER opens an end tag: a
            # browser's end-tag-open state takes EOF as the TEXT `</`, `</>` as nothing at all,
            # and everything else - `</ p>`, `<//>` - into the BOGUS COMMENT state, which ends at
            # the first `>`. Resolved here rather than delegated, because the host disagrees with
            # itself: `endtagfind` allowed whitespace after `</` before 3.13, so a terminated
            # `</ main>` CLOSED an element on an older interpreter and was a comment on a newer
            # one - the same document with a different element stack, and so a different cm-skip
            # ancestry, `#commentRoot` scope and raw-text bookkeeping.
            if i + 2 >= len(rawdata):
                if not self._final:
                    return -1       # more input may still name the tag
                # TEXT, not an unterminated CONSTRUCT: the characters are emitted rather than
                # swallowing the rest of the document, so `eof_unterminated` stays off here.
                self.handle_data(rawdata[i:])   # a bare `</` at EOF is TEXT
                return len(rawdata)
            if rawdata.startswith("</>", i):
                return i + 3        # "missing-end-tag-name": nothing is emitted at all
            gt = rawdata.find(">", i + 2)
            if gt < 0:
                return self._unterminated(i + 2, self.handle_comment)
            self.handle_comment(rawdata[i + 2:gt])
            return gt + 1
        k = super().parse_endtag(i)
        if k >= 0 or not self._final:
            return k
        return len(rawdata)         # EOF inside a real end tag: the tag is discarded

    def _enter_cdata_mode(self, tag):
        # Off: this family enters raw text from its own handle_starttag (`_enter_raw_text`),
        # where the element's NAMESPACE is known, so an SVG `<title>` is parsed rather than
        # swallowed. Doing it here as well would defeat that carve-out.
        pass

    def parse_pi(self, i):
        # A browser has no processing instructions: `<?` opens a BOGUS COMMENT that ends at the
        # first `>`, and an unterminated one runs to the end of the document. html.parser calls
        # handle_pi instead and, before the EOF fix, leaks an unterminated one back out as DATA,
        # so the same truncated document read two ways.
        rawdata = self.rawdata
        j = rawdata.find(">", i + 2)
        if j < 0:
            return self._unterminated(i + 1, self.handle_comment)
        self.handle_comment(rawdata[i + 1:j])
        return j + 1

    def parse_html_declaration(self, i):
        # Replaced wholesale so `<!...>` is resolved identically on every interpreter. Only
        # inside FOREIGN content is `<![CDATA[ ... ]]>` a CDATA section; everywhere else a
        # browser treats `<!` + junk as a BOGUS COMMENT that ends at the very first `>`, so
        # markup after that `>` is LIVE. html.parser instead consumes the whole marked section
        # in every context (and, before 3.13, raises on an unknown section keyword), which would
        # hide real markup behind a `<![CDATA[` an author never meant as one.
        rawdata = self.rawdata
        if rawdata.startswith("<!--", i):
            return self.parse_comment(i)
        if rawdata[i:i + 9].lower() == "<!doctype":
            gt = rawdata.find(">", i + 9)
            if gt < 0:
                return self._unterminated(i + 2, self.handle_decl)
            self.handle_decl(rawdata[i + 2:gt])
            return gt + 1
        if rawdata.startswith("<![CDATA[", i) and self._current_is_foreign():
            j = rawdata.find("]]>", i + 9)
            if j < 0:
                return self._unterminated(i + 3, self.unknown_decl)
            self.unknown_decl(rawdata[i + 3:j])
            return j + 3
        # A bogus comment that never closes runs to the end of the document, as a browser does;
        # before the host's EOF fix an unterminated one leaks back out as DATA instead, so a
        # truncated `<!BEGIN: ...` read as a comment on one interpreter and as prose on another.
        k = self.parse_bogus_comment(i)
        if k < 0 and self._final:
            return self._unterminated(i + 2, self.handle_comment)
        return k

    def _unterminated(self, start, handler):
        """A construct with no closer: a browser consumes the rest of the document."""
        if not self._final:
            return -1   # more data may still arrive; the base class re-tries
        self.eof_unterminated = True
        handler(self.rawdata[start:])
        return len(self.rawdata)

    def _enter_raw_text(self, tag, ns):
        """Switch a raw-text / RCDATA element's CONTENT to text, as a browser does. Called by
        the subclass AFTER the element is pushed, so the foreign carve-out can see it."""
        if ns != "html":
            return   # nothing is raw text inside foreign content (see _RAW_TEXT_ELEMENTS)
        if tag in _RAW_TEXT_ELEMENTS:
            self.set_cdata_mode(tag)

    # -- foreign content ---------------------------------------------------- #

    def _current_is_foreign(self):
        """Whether the CURRENT NODE is an SVG/MathML element. That - not merely having a
        foreign ANCESTOR - is what decides whether `<![CDATA[` opens a section: a browser only
        recognizes one when the adjusted current node is outside the HTML namespace."""
        return bool(self._ns) and self._ns[-1][1] != "html"

    def _foreign_self_closes(self, ns):
        """Whether a trailing slash really closes THIS element. HTML5 ignores it on a non-void
        HTML tag (`<pre/>` still needs `</pre>`), but a self-closed FOREIGN element is opened
        and closed at once, so `<svg><rect/>` - and a bare `<svg/>` - leave nothing open."""
        return ns != "html"

    def _child_namespace(self, tag, ad):
        """The namespace a new `tag` is inserted in, applying HTML5's foreign-content rules:
        integration points and MathML text integration points put their children back in the
        HTML namespace, and a BREAKOUT start tag pops the open foreign elements first."""
        top = self._ns[-1] if self._ns else None
        parent_tag = top[0] if top is not None else None
        parent_ns = top[1] if top is not None else "html"
        parent_integration = top[2] if top is not None else False
        if parent_integration and tag in _MATHML_GLYPH_TAGS and parent_ns == "math":
            # `mglyph`/`malignmark` in a MathML TEXT integration point stay MathML, so a
            # `<![CDATA[` under them is still a real section.
            return "math"
        if parent_ns == "html" or parent_integration:
            return "svg" if tag == "svg" else ("math" if tag == "math" else "html")
        if parent_tag == "annotation-xml" and parent_ns == "math" and tag == "svg":
            return "svg"   # an SVG root inside a non-HTML annotation-xml is SVG, not MathML
        if tag in _FOREIGN_BREAKOUT_TAGS or (
                tag == "font" and any(a in ad for a in _FONT_BREAKOUT_ATTRS)):
            self._break_out_of_foreign()
            return "html"
        return parent_ns

    def _break_out_of_foreign(self):
        """Pop foreign elements until the current node is HTML or an integration point, as a
        browser does for a breakout start tag. Without it `<svg><p>` would leave a stale `svg`
        current and a following `<![CDATA[` would hide live markup."""
        depth = len(self._ns)
        while depth > 0:
            _tag, ns, integration = self._ns[depth - 1]
            if ns == "html" or integration:
                break
            depth -= 1
        if depth < len(self._ns):
            self._before_truncate(depth)
            self._truncate_stacks(depth)

    @staticmethod
    def _is_integration_point(tag, ns, ad):
        """Whether this element's CHILDREN are inserted in the HTML namespace."""
        if ns == "svg":
            return tag in _SVG_HTML_INTEGRATION
        if ns == "math":
            if tag in _MATHML_TEXT_INTEGRATION:
                return True
            return (tag == "annotation-xml"
                    and (ad.get("encoding") or "").strip().lower() in _ANNOTATION_HTML_ENCODINGS)
        return False

    # -- the element stack the namespace view runs parallel to --------------- #

    def _push_ns(self, tag, ns, ad):
        depth = len(self._ns)
        self._ns.append((tag, ns, self._is_integration_point(tag, ns, ad)))
        self._open_by_tag.setdefault(tag, []).append(depth)
        # A FOREIGN element stops the scan only when it is an integration point by NAME, and an
        # HTML element only when it is the target or one of its boundaries - so the two sets are
        # applied per namespace, exactly as the scan applied them.
        if ns == "html":
            p_stops, li_stops = tag in _P_SCOPE_STOPS, tag in _LI_SCOPE_STOPS
        else:
            p_stops = li_stops = tag in _FOREIGN_SCOPE_BOUNDARY
        self._p_stop.append(depth if p_stops else (self._p_stop[-1] if depth else -1))
        self._li_stop.append(depth if li_stops else (self._li_stop[-1] if depth else -1))
        self._tpl_stop.append(depth if (ns == "html" and tag == "template")
                              else (self._tpl_stop[-1] if depth else -1))

    def _end_tag_floor(self, tag):
        """The lowest stack index an END TAG may match at.

        A `<template>`'s contents are parsed into their own DocumentFragment and `template` is a
        SCOPING element, so a closer written inside an open template cannot reach an element
        opened OUTSIDE it: a browser ignores it, and the markup that follows stays inert inside
        the template. Matching across the boundary popped the template early, which turned every
        template-aware view - prose, ids, headings, anchors, the layer/marker views - into a view
        of markup a reader never sees. `</template>` itself really does pop the template, so for
        that tag the floor IS the template's own index.

        Read off `_tpl_stop`, which is parallel to the namespace stack every subclass keeps
        parallel to its own element stack, so the foreign-content bookkeeping can never be
        truncated across the boundary either and the answer stays O(1). Only an HTML-namespace
        `<template>` scopes: an SVG element that happens to be called `template` is an ordinary
        foreign element and stops nothing.
        """
        i = self._tpl_stop[-1] if self._tpl_stop else -1
        if i < 0:
            return 0
        return i if tag == "template" else i + 1

    def _innermost_open(self, tag):
        """The index of the innermost open element named `tag` an end tag may MATCH, or -1 when
        there is none. This is the element an end tag closes, so every subclass's `handle_endtag`
        reads it instead of walking the stack. A match BELOW the template floor is not one a
        browser would make, so it is reported as no match at all."""
        open_at = self._open_by_tag.get(tag)
        if not open_at:
            return -1
        i = open_at[-1]
        return i if i >= self._end_tag_floor(tag) else -1

    def _truncate_stacks(self, depth):
        """Truncate every parallel element stack to `depth`. Subclasses extend this with their
        own stacks so no truncation path can leave the namespace view out of step."""
        for tag, _ns, _integration in self._ns[depth:]:
            open_at = self._open_by_tag[tag]
            open_at.pop()
            if not open_at:
                # Keep the index to CURRENTLY OPEN elements only, so a document that opens and
                # closes many distinct names grows it by open depth rather than by vocabulary.
                del self._open_by_tag[tag]
        del self._ns[depth:]
        del self._p_stop[depth:]
        del self._li_stop[depth:]
        del self._tpl_stop[depth:]

    def _before_truncate(self, depth):
        """Hook: the elements from `depth` up are about to be popped WITHOUT their own end tag."""

    def _implicit_close(self, tag):
        # HTML5 "close a p element": a block-level start tag closes an open <p> even through
        # intervening inline elements (a browser pops the <p> and everything under it), and a
        # new <li> closes an open <li>. Both tolerant parsers apply it, so a `<canvas>` whose
        # only cm-skip ancestor is such a <p> is not falsely protected and a `<pre>` a browser
        # puts inside a `figure.cmh-kql` is not judged outside it.
        if tag in P_CLOSERS:
            self._close_scoped("p", self._p_stop)
        if tag == "li":
            self._close_scoped("li", self._li_stop)

    def _close_scoped(self, target, stops):
        """Close an open `target` if it is in scope, in O(1) rather than a stack scan.

        `stops` carries the index of the nearest enclosing element the scan would have stopped at,
        so the whole scan reduces to reading it: the target closes when the nearest stop IS the
        target, and nothing happens when it is a boundary (the target is out of scope) or when
        there is no stop at all (no open target).
        """
        i = stops[-1] if stops else -1
        if i < 0:
            return
        tag, ns, _integration = self._ns[i]
        if ns == "html" and tag == target:
            self._before_truncate(i)
            self._truncate_stacks(i)

    # -- the shared handler skeleton ---------------------------------------- #
    #
    # The ORDER of the steps below IS the CMH-VAL-21 boundary invariant, so it is written down in
    # exactly ONE place. Every parser here and every rebased tool outside this package drives it
    # through the hooks under it and overrides only what it COLLECTS; none of them repeats the
    # sequence. That is structural, not stylistic: this base deliberately disables the host's own
    # `_enter_cdata_mode()` (see below), so a copy of the skeleton that forgot `_enter_raw_text()`
    # would parse a `<script>` body as markup, and one that ran `_implicit_close()` after its own
    # bookkeeping would key that bookkeeping on a stack a browser had already popped - neither of
    # which any gate could see.

    def _opens_element(self, tag, ns):
        """Whether this start tag leaves an element OPEN on the stack. A VOID element has no
        content and no end tag, so it is never pushed; a FOREIGN element is never void
        (`<svg><rect/>` is self-closing markup, which `handle_startendtag()` resolves)."""
        return tag not in VOID or ns != "html"

    def handle_starttag(self, tag, attrs):
        tag = self._browser_tag(tag)
        self._host_attrs = attrs
        ad = self._attrs_dict(tag, attrs)
        ns = self._child_namespace(tag, ad)
        if ns == "html":
            self._implicit_close(tag)
        opens = self._opens_element(tag, ns)
        info = self._visit_start(tag, ad, ns, opens)
        if opens:
            self._push_element(tag, ad, ns, info)
            self._push_ns(tag, ns, ad)
        else:
            self._visit_void(tag, ad, ns, info)
        self._enter_raw_text(tag, ns)
        self._after_start(tag, ad, ns, opens)

    def handle_startendtag(self, tag, attrs):
        # HTML5 IGNORES a trailing slash on a non-void HTML tag - `<pre/>` opens an element that
        # still needs `</pre>`, and `<hr/>` is a void tag that still implicitly closes an open
        # `<p>` - so both go through the start-tag path. Only a FOREIGN element really is opened
        # and closed at once, so `<svg><rect id="x"/>` is still an element with attributes and a
        # bare `<svg/>` must not be left open (a stale foreign current node would make a following
        # `<![CDATA[` hide live markup).
        tag = self._browser_tag(tag)
        self._host_attrs = attrs
        ad = self._attrs_dict(tag, attrs)
        ns = self._child_namespace(tag, ad)
        if not self._foreign_self_closes(ns):
            self.handle_starttag(tag, attrs)
            return
        self._visit_self_closed(tag, ad, ns)

    def handle_endtag(self, tag):
        tag = self._browser_tag(tag)
        index = self._innermost_open(tag)
        if self._visit_end(tag, index) is False:
            return
        if index < 0:
            # An end tag with no open element is IGNORED, exactly as a browser ignores it.
            return
        self._end_tag_close = True
        try:
            self._truncate_stacks(index)
        finally:
            self._end_tag_close = False

    # -- what a subclass overrides ------------------------------------------ #

    def _visit_start(self, tag, ad, ns, opens):
        """Collect whatever this parser wants from a start tag, BEFORE the element is pushed.

        `ad` is the browser-decoded attribute dict, `ns` the namespace the element is inserted in,
        and `opens` whether it will be pushed. Runs after HTML5's implicit `</p>` / `</li>` close,
        so the stack is the one a browser has at this point. Whatever it RETURNS is handed back to
        `_push_element()` / `_visit_void()`, so a record built here (and the depth-keyed state that
        goes with it) needs no scratch attribute to survive the two steps.
        """
        return None

    def _push_element(self, tag, ad, ns, info):
        """Push the element onto the subclass's OWN stack, which runs parallel to `_ns`. Called
        only when `_opens_element()` said so, and immediately before `_push_ns()`, so both stacks
        take the same index."""

    def _visit_void(self, tag, ad, ns, info):
        """The element is never pushed (a void tag), so it has no content: any depth-keyed state
        `_visit_start()` just opened at this depth ends immediately."""

    def _after_start(self, tag, ad, ns, opens):
        """After `_enter_raw_text()` - the one place a subclass can see whether the element it
        just opened put the tokenizer into raw text."""

    def _visit_self_closed(self, tag, ad, ns):
        """A FOREIGN element written self-closed: a real element with attributes that is opened
        and closed at once, so it is never pushed and never enters raw text. By default it is
        reported as a start tag that opens nothing, so a subclass that only writes `_visit_start()`
        still SEES it - `<svg><rect id="x"/>` is an element with an id. Override to collect less
        (a subclass whose start hook also opens depth-keyed state has nothing here to key it on)."""
        self._visit_void(tag, ad, ns, self._visit_start(tag, ad, ns, False))

    def _visit_end(self, tag, index):
        """An end tag, before anything is truncated. `index` is the stack index of the element it
        closes, or -1 when a browser would ignore it (nothing open by that name, or the only match
        sits below the `<template>` floor). Return False to keep a matched element open."""


# The ancestor facts each tolerant parser asks about an element while it is being recorded. They
# are running COUNTS (and, for `svg`, the index of the nearest `svg`/`foreignObject`), kept
# parallel to the element stack so each question is O(1) instead of a walk of the open elements.
class _DocAncestors(NamedTuple):
    skip: int
    html_template: int
    shadow: int
    canvas: int
    pre: int
    chart_figure: int
    anchor: int
    svg: int


class _CodeAncestors(NamedTuple):
    pre: int
    kql_figure: int


class _DocParser(_BrowserBoundaries):
    """One tolerant pass over the document. Collects, for the chart checks:

      - canvases  [{"skip": bool, "attrs": {..}}]
      - figcaptions [{"skip": bool, "in_canvas": bool}]
      - scripts   [{"pos": int, "attrs": {..}, "body": str}]  (executable + json)
      - has_comment_root: a real element with id=commentRoot exists
      - js_end_marker_pos: offset of the real "END: ... JS" comment, or None

    cm-skip ancestry, the HTML5 implicit close of <p>/<li> (so an unclosed
    cm-skip <p> does not leak), and raw-text + comment opacity all fall out of the
    parser, so a <canvas>/loader/new Chart in a string or comment is not counted,
    and a `>` inside a quoted attribute does not mis-slice a tag. The element
    boundaries themselves come from _BrowserBoundaries, so this view of a document
    is exactly the code-block tokenizer's view of it (CMH-VAL-21).
    """

    def __init__(self, html):
        super().__init__(html)
        self.stack = []          # list of (tag, is_cm_skip)
        self.canvases = []
        self.figcaptions = []
        self.scripts = []
        self.styles = []
        self.inline_styles = []
        # The same three views for content parked inside a `<template>`. Template content is INERT
        # (it does not run, does not load, and `getElementById` never sees it), so every ordinary
        # check must keep ignoring it - but serialization preserves it verbatim and a script can
        # adopt the fragment and insert it, which is why the offline strips walk into templates.
        # These lists exist so the OFFLINE checks can see exactly what those strips see, without
        # changing what any other check counts.
        self.template_scripts = []
        self.template_styles = []
        self.template_inline_styles = []
        self.has_comment_root = False
        self.js_end_marker_pos = None
        # Every real comment that could carry a region marker, as `(start, end)` spans into the
        # document, split by whether a browser parses it as part of the document. The marker COUNT
        # view (`_region_marker_matches`) is TEXT: it counts a marker written where a browser
        # builds no comment node at all - inside an inert `<template>`, inside a CDATA section,
        # inside a raw-text body - so a document could satisfy the layer's region check with a
        # marker that is not a boundary, and every parse-driven check keyed on that region then
        # failed OPEN. `check_layer` cross-checks the counted markers against these spans.
        self.marker_comment_spans = []      # real comments a browser parses
        self.template_comment_spans = []    # the same, parked inside an inert <template>
        self.shadow_comment_spans = []      # real comments parsed inside a shadow tree
        self.all_ids = []        # every element id value, in document order
        # The LAYER's own markup: everything the parser sees OUTSIDE the authored CONTENT region
        # (`_in_commentable_content()`). A document about commentable-html can DEMONSTRATE the
        # companion markup in its prose, so the mode determination and the NonShareable checks read
        # these instead of the whole document. Tracking it in the parse (rather than by marker
        # offsets) means the region is exactly what a browser would agree it is: real HTML comment
        # markers, inside the live #commentRoot, outside an inert <template> and outside CDATA.
        self.layer_ids = []
        self.layer_tags = {"link": [], "meta": [], "script": []}
        self.layer_ready_token = False
        # Whether the CONTENT region is well-formed AS PARSED: opened by a real BEGIN comment
        # inside the live #commentRoot and closed again by a real END comment. When it is not,
        # the layer view above cannot be trusted and the layer check errors rather than guessing.
        self.content_region_opened = False
        self.content_region_closed = False
        self.anchors = []        # [{"href", "target", "skip", "in_root"}] for every <a> element
        self.metas = {}          # {meta name (lowercased): content} for <meta name content>
        # Every <meta http-equiv=content-security-policy> a browser really APPLIES, in document
        # order, as {"content", "late"}. Collected here rather than off the shared tag index
        # because that index deliberately records EVERY start tag: a policy parked in an inert
        # <template> satisfied the offline CSP requirement while enforcing nothing. `_record`
        # already drops template content; `_csp_head_over` is the head test the HTML pragma
        # directives require, and `late` says a fetch- or execute-capable element already preceded
        # the policy, so it cannot be the document's guarantee.
        self.csp_metas = []
        # NOT `_head_ended`: the "after head" insertion mode RE-PUSHES the head element for a
        # base/link/meta/script/style/title/template start tag, so a `</head>` does not stop a meta
        # from being a head child, and dropping one written there would reject a clean document.
        # What does end it is a start tag the head cannot hold (a <body>, or any flow content), or
        # non-whitespace text (see `handle_data`).
        self._csp_head_over = False
        self._csp_fetch_seen = False
        self.icon_links = []     # [{"rel": str, "href": str}] for every head <link rel~="icon">
        self._head_ended = False # True once the head is over (a <body>/</head>/first flow element)
        self.comment_root_attrs = None   # attrs dict of the id=commentRoot element
        self.body_attrs = None           # attrs dict of the REAL <body> start tag (first one)
        self.mermaid_blocks = []         # [{"cm_skip": bool, "has_svg": bool}] for pre/div.mermaid
        self.declarative_shadow_roots = []  # rendered roots and their export-durability attrs
        self._active_shadow_roots = []      # open root records, innermost last
        self.cm_skip_code_blocks = []    # [{"kind": "<pre>"|"<pre><code>"}] for direct cm-skip misuse
        self._mermaid_stack = []         # parallel to self.stack: current mermaid block index, or None
        self._shadow_hosts = []          # host state parallel to stack; None for consumed DSD template
        # Open `<script>`/`<style>` captures, innermost LAST: [{"tag", "pos", "attrs", "depth",
        # "parts", "in_content"}]. A STACK rather than one scalar per kind because outside the HTML
        # namespace those two hold MARKUP, so one really can contain another (`<svg><style><style>`)
        # and a BREAKOUT start tag can pop one before its own end tag ever arrives. With a scalar,
        # the inner element silently replaced the outer capture and the outer body - the CSS a
        # browser still applies, `@import url(...)` included - never reached `styles`, hiding egress
        # from the offline gate that reads it. Each capture is finalized from `_truncate_stacks()`,
        # so every close a browser performs (its own end tag, an ancestor's, a breakout, EOF)
        # records it, and DATA goes only to the capture that is the CURRENT NODE - see
        # `_current_raw_capture()`.
        self._raw_captures = []
        # The same, for a TEMPLATE-parked <script>/<style>, kept apart from the above so template
        # content never leaks into a check that must ignore it. A stack for the same reason, and so
        # a NESTED parked script is recorded with its OWN attributes: the export path walks every
        # `<script>` in a template, so folding an inner executable one into an outer inert record
        # would let the offline gate skip a network import the exporter really carries.
        self._tpl_captures = []
        self.commentroot_prose = []  # #commentRoot text NOT inside <a> or a cm-skip element
        self._cr_depth = None        # stack depth at which #commentRoot was entered
        self._cr_closed = False      # True once #commentRoot (or an ancestor) has closed
        self._in_content_region = False
        self.headings = []           # [{"id": str|None, "text": str, "top_level": bool}] in #commentRoot
        self._cur_heading = None     # (tag, id, [parts], top_level) while capturing a heading's text
        self._cur_heading_depth = None   # stack depth of that heading, so an ancestor's close ends it
        self.has_top_level_lede = False  # a direct child of #commentRoot carries class cmh-lede
        self._lede_depth = None      # stack depth of the current top-level cmh-lede (for title h1)
        self._anc = []               # parallel to self.stack: the ancestor summary (see below)
        self.has_offline_chart = False

    # Parallel to `self.stack`: the ancestor facts `_record` asks about, as running counts (and,
    # for the nearest svg / foreignObject, an index). Asking them of the open-element stack was a
    # walk per recorded element, which is quadratic on a deeply nested document.
    _NO_ANCESTORS = _DocAncestors(0, 0, 0, 0, 0, 0, 0, -1)

    def _ancestors(self):
        return self._anc[-1] if self._anc else self._NO_ANCESTORS

    def _push_ancestors(self, tag, own_skip, is_chart_figure,
                        html_template=False, shadow=False):
        prev = self._ancestors()
        self._anc.append(_DocAncestors(prev.skip + bool(own_skip),
                                       prev.html_template + bool(html_template),
                                       prev.shadow + bool(shadow),
                                       prev.canvas + (tag == "canvas"),
                                       prev.pre + (tag == "pre"),
                                       prev.chart_figure + bool(is_chart_figure),
                                       prev.anchor + (tag == "a"),
                                       len(self._anc) if tag in ("svg", "foreignobject")
                                       else prev.svg))

    def _skip_ancestor(self):
        return self._ancestors().skip > 0

    def _in_canvas(self):
        return self._ancestors().canvas > 0

    def _in_template(self):
        # An ordinary template is inert; a declarative shadow root contributes shadow ancestry.
        # NAMESPACE-AWARE: only an HTML-namespace <template> is inert. An element merely NAMED
        # `template` under <math>/<svg> is an ordinary unknown foreign element a browser keeps
        # in the DOM and in its ancestor's textContent - and whose raw-text children a browser
        # treats exactly as it would without that wrapper (an SVG <script>/<style> really does
        # execute and apply). Counting it by NAME hid content a reader sees from the prose,
        # heading and element views at once, and parked such a body in the template-only views.
        return self._ancestors().html_template > 0

    def _in_shadow_tree(self):
        return self._ancestors().shadow > 0

    def _attaches_shadow_root(self, tag, ad, ns):
        host_ns = self._ns[-1][1] if self._ns else None
        host = self._shadow_hosts[-1] if self._shadow_hosts else None
        if (tag != "template" or ns != "html" or self._in_template()
                or _ascii_lower(ad.get("shadowrootmode") or "") not in ("open", "closed")
                or host is None or host["used"]
                or not _can_host_shadow_root(self.stack[-1][0], host_ns)):
            return False
        host["used"] = True
        return True

    def _mark_light_child(self):
        if not self._shadow_hosts:
            return
        host = self._shadow_hosts[-1]
        if host is None:
            return
        host["light"] = True
        if host["root"] is not None:
            host["root"]["mixed_light"] = True

    def _in_html_template(self):
        # The textContent view: the inert-template floor above (already namespace-aware) plus a
        # declarative shadow root, whose content a browser DOES render but into a SHADOW tree
        # that is still outside the host's textContent.
        return self._in_template() or self._in_shadow_tree()

    def _in_comment_root(self):
        return self._cr_depth is not None and not self._cr_closed and len(self.stack) > self._cr_depth

    def _in_commentable_content(self):
        return self._in_content_region and self._in_comment_root()

    def _note_ready_token(self, text):
        """Record the NonShareable bootstrap watchdog token, but ONLY from the body of an
        executable <script> belonging to the LAYER - outside the authored CONTENT region (and, by
        construction of the capture stack, outside an inert <template>). The watchdog IS such a
        script, so authored prose, a reviewer note in the embedded-comments JSON, or a template that
        merely contains the token must not stand in for it. The script must be the CURRENT NODE and
        must itself have been OPENED outside the content region, so text a browser reads as some
        other element's - or a script the author opened inside their own content and left open past
        the end marker - cannot stand in for the layer's watchdog either."""
        if self.layer_ready_token or self._in_shadow_tree():
            return
        cap = self._current_raw_capture()
        if cap is None or cap["tag"] != "script" or cap["in_content"]:
            return
        if not _is_executable_js(cap["attrs"]):
            return
        if READY_TOKEN in (text or "") and not self._in_commentable_content():
            self.layer_ready_token = True

    def _open_raw_capture(self, tag, ad):
        """Start collecting a `<script>`/`<style>` body. Recorded BEFORE the element is pushed, so
        its `depth` is the index it occupies and any truncation that removes it finalizes it."""
        self._raw_captures.append({"tag": tag, "pos": self._off(), "attrs": ad,
                                   "depth": len(self.stack), "parts": [],
                                   "in_content": self._in_commentable_content()})

    def _flush_raw_captures(self, depth):
        """Finalize every capture the element at `depth` (or an ancestor of it) closed, innermost
        first, so an element a browser closed implicitly still contributes its body."""
        while self._raw_captures and self._raw_captures[-1]["depth"] >= depth:
            cap = self._raw_captures.pop()
            sink = self.scripts if cap["tag"] == "script" else self.styles
            sink.append({"pos": cap["pos"], "attrs": cap["attrs"],
                         "body": "".join(cap["parts"])})

    def _current_raw_capture(self):
        """The open `<script>`/`<style>` whose element is the CURRENT NODE, if any.

        A browser reads an element's script or CSS from its own CHILD text nodes, so text under a
        nested element belongs to that element, not to the ancestor holding it - only reachable in
        foreign content, where these two hold markup. Crediting it to the ancestor would let text
        no browser treats as the outer element's source satisfy a PRESENCE check (a required
        `[hidden]` rule, a chart's `.getContext(`), which fails OPEN."""
        if not self._raw_captures:
            return None
        cap = self._raw_captures[-1]
        return cap if cap["depth"] == len(self.stack) - 1 else None

    def _flush_template_raw(self, depth=0):
        """Record each template-parked <script>/<style> body the element at `depth` (or an ancestor
        of it) closed, innermost first, in its own view."""
        while self._tpl_captures and self._tpl_captures[-1]["depth"] >= depth:
            cap = self._tpl_captures.pop()
            sink = self.template_scripts if cap["tag"] == "script" else self.template_styles
            sink.append({"pos": None, "attrs": cap["attrs"], "body": "".join(cap["parts"])})

    def _truncate_stacks(self, depth):
        # Every truncation path - an end tag, an implicit </p>/</li> close, a foreign-content
        # breakout - runs through here, so the parallel views can never fall out of step.
        # A template-parked raw-text element can never outlive the <template> that holds it: an
        # unterminated one would otherwise keep collecting, and the next parked block's body would
        # be concatenated onto it into a body no browser would ever see.
        self._flush_template_raw(depth)
        self._flush_raw_captures(depth)
        while (self._active_shadow_roots
               and self._active_shadow_roots[-1]["depth"] >= depth):
            self._active_shadow_roots.pop()
        # Closing #commentRoot (or an ancestor of it) ends the root subtree for
        # good, so headings/prose in a later sibling container are not collected.
        if self._cr_depth is not None and depth <= self._cr_depth:
            self._cr_closed = True
            self._in_content_region = False
        if self._lede_depth is not None and depth <= self._lede_depth:
            self._lede_depth = None
        # A browser ends an open heading when an ANCESTOR closes, so its text stops there. Left
        # capturing, it went on swallowing prose - and the next heading's text - as one heading.
        # (This follows the stack as parsed, so an end tag a browser would IGNORE rather than pop
        # - `</span>` around a heading, which is invalid markup anyway - ends the heading here a
        # little early. A known, chosen approximation: the pop itself predates this.)
        if self._cur_heading_depth is not None and depth <= self._cur_heading_depth:
            self._flush_heading()
        super()._truncate_stacks(depth)
        del self.stack[depth:]
        del self._anc[depth:]
        del self._mermaid_stack[depth:]
        del self._shadow_hosts[depth:]

    def _record(self, tag, ad, own_skip):
        if self._in_template() or self._in_shadow_tree():
            if "style" in ad:
                self.template_inline_styles.append({"tag": tag, "value": ad.get("style", "")})
            return
        if tag in self.layer_tags and not self._in_commentable_content():
            self.layer_tags[tag].append(ad)
        if not self._head_ended and (tag == "body" or tag not in _HEAD_TAGS):
            self._head_ended = True
        if tag == "body" and self.body_attrs is None:
            self.body_attrs = ad
        if tag == "meta":
            nm = (ad.get("name") or "").strip().lower()
            if nm and nm not in self.metas:
                self.metas[nm] = ad.get("content") or ""
        if not self._csp_head_over and (tag == "body" or tag not in _CSP_HEAD_TAGS):
            self._csp_head_over = True
        if tag == "meta" and not self._csp_head_over:
            # `_ascii_lower`, not `str.lower()`: a Unicode fold can map a non-ASCII look-alike onto
            # an ASCII letter, and here that direction is fail-OPEN - it would read a policy off a
            # meta whose http-equiv a browser never matches, and bless a document that has none.
            # No trimming, for the same reason and to match the exporter's own literal test: the
            # pragma is looked up by the attribute value EXACTLY, so ` content-security-policy` is
            # not one.
            if _ascii_lower(ad.get("http-equiv") or "") == "content-security-policy":
                self.csp_metas.append({"content": ad.get("content") or "",
                                       "late": self._csp_fetch_seen})
        if not self._csp_fetch_seen and _csp_predecessor_fetches(tag, ad):
            self._csp_fetch_seen = True
        if tag == "link" and not self._head_ended:
            # Head-scoped: only a <link rel~="icon"> in the head is a favicon a browser tab honors,
            # so a body-level icon link does not satisfy the favicon check.
            rels = (ad.get("rel") or "").lower().split()
            if "icon" in rels:
                self.icon_links.append({"rel": ad.get("rel") or "", "href": ad.get("href") or ""})
        if tag == "canvas":
            self.canvases.append({"skip": self._skip_ancestor() or own_skip, "attrs": ad})
        elif tag == "figcaption":
            self.figcaptions.append({"skip": self._skip_ancestor() or own_skip,
                                     "in_canvas": self._in_canvas(),
                                     "in_chart_figure": self._ancestors().chart_figure > 0})
        if tag == "a":
            # SVG-namespaced <a> (tagName "a", not "A") is never stamped by the runtime, so exclude
            # it. But an <a> inside an SVG <foreignObject> is at an HTML integration point (tagName
            # "A") and IS stamped - detect the nearest svg/foreignObject ancestor, not any svg.
            nearest = self._ancestors().svg
            in_svg = nearest >= 0 and self.stack[nearest][0] == "svg"
            self.anchors.append({"href": ad.get("href"), "target": ad.get("target"),
                                 "skip": self._skip_ancestor() or own_skip,
                                 "in_svg": in_svg,
                                 "in_root": self._in_comment_root()})
        if "data-cm-offline-chart" in ad and self._in_comment_root():
            # Scoped to the content root because that is where the Offline export puts a snapshot,
            # and because the runtime's own signal is `#commentRoot [data-cm-offline-chart]`: a
            # wider view here would fail a document the runtime never reads as offline (a snapshot
            # in host chrome or in layer-owned markup). Template and shadow content never reach
            # here at all (`_record` returns above).
            self.has_offline_chart = True
        if "style" in ad:
            self.inline_styles.append({"tag": tag, "value": ad.get("style", "")})
        classes = set((ad.get("class") or "").split())
        is_mermaid_host = tag in ("pre", "div") and "mermaid" in classes
        if is_mermaid_host:
            self.mermaid_blocks.append({"cm_skip": own_skip, "has_svg": False})
        elif tag == "pre" and own_skip and self._in_commentable_content():
            self.cm_skip_code_blocks.append({"kind": "<pre>"})
        elif (tag == "code" and own_skip and self._in_commentable_content()
              and self._ancestors().pre > 0):
            current_mermaid = self._mermaid_stack[-1] if self._mermaid_stack else None
            if current_mermaid is None:
                self.cm_skip_code_blocks.append({"kind": "<pre><code>"})
        idv = ad.get("id")
        if idv:
            self.all_ids.append(idv)
            if not self._in_commentable_content():
                self.layer_ids.append(idv)
            if idv == "commentRoot":
                self.has_comment_root = True
                if self.comment_root_attrs is None:
                    self.comment_root_attrs = ad
                    self._cr_depth = len(self.stack)  # commentRoot is pushed at this index
        # A top-level (direct-child) element of #commentRoot carrying cmh-lede is the document's
        # own title header (new_document.ensure_doc_title emits <header class="cmh-lede"><h1>).
        if (self._cr_depth is not None and not self._cr_closed
                and len(self.stack) == self._cr_depth + 1
                and "cmh-lede" in set((ad.get("class") or "").split())):
            self.has_top_level_lede = True
            self._lede_depth = len(self.stack)

    def _visit_start(self, tag, ad, ns, opens):
        if ns == "html":
            # HTML5's h1-h6 start tag POPS an open heading that is the CURRENT node, so
            # `<h2 id="a">A<h2 id="b">B` is two headings: without this the first one ran on and
            # swallowed the second's text, and the second's id was never collected at all. The
            # rule is STRUCTURAL - a browser pops whatever open heading is the current node, so a
            # heading this parser does not CAPTURE (a cm-skip one, one outside #commentRoot) is
            # popped too; keyed on the capture instead, such a heading stayed open and the
            # visible heading after it inherited its cm-skip and vanished from every check.
            if (tag in _HEADING_TAGS and self.stack
                    and self.stack[-1][0] in _HEADING_TAGS):
                self._truncate_stacks(len(self.stack) - 1)
        own_skip = "cm-skip" in set((ad.get("class") or "").split())
        is_shadow = self._attaches_shadow_root(tag, ad, ns)
        if not is_shadow and tag != "template":
            self._mark_light_child()
        if is_shadow:
            root_record = {
                "mode": _ascii_lower(ad.get("shadowrootmode") or ""),
                "serializable": "shadowrootserializable" in ad,
                "mixed_light": self._shadow_hosts[-1]["light"],
                "has_slot": False,
                "host_is_comment_root": self._shadow_hosts[-1]["id"] == "commentRoot",
                "depth": len(self.stack),
                "host_depth": len(self.stack) - 1,
            }
            self.declarative_shadow_roots.append(root_record)
            self._active_shadow_roots.append(root_record)
            self._shadow_hosts[-1]["root"] = root_record
        inert_template = tag == "template" and ns == "html" and not is_shadow
        if (tag == "slot" and ns == "html" and not self._in_template()
                and self._active_shadow_roots and self._in_shadow_tree()):
            self._active_shadow_roots[-1]["has_slot"] = True
        before_mermaid = len(self.mermaid_blocks)
        if not is_shadow:
            self._record(tag, ad, own_skip)
        if tag == "svg" and self._mermaid_stack:
            idx = self._mermaid_stack[-1]
            if idx is not None:
                self.mermaid_blocks[idx]["has_svg"] = True
        if tag in ("script", "style") and not self._in_template() and not self._in_shadow_tree():
            self._open_raw_capture(tag, ad)
        if tag in ("script", "style") and (self._in_template() or self._in_shadow_tree()):
            # The stack DEPTH is carried so the state can never outlive its template: html.parser
            # keeps a raw-text element open to EOF, which matches a browser, but if any future path
            # ever left one open past `</template>` the next parked block's body would silently be
            # concatenated onto it and the offline check would read a body no browser would see.
            self._tpl_captures.append({"tag": tag, "attrs": ad, "depth": len(self.stack),
                                       "parts": []})
        if (tag in _HEADING_TAGS and self._cur_heading is None and self._cr_depth is not None
                and not self._cr_closed and len(self.stack) > self._cr_depth and not own_skip
                and not self._skip_ancestor() and not self._in_template()):
            shadow_top_level = (
                bool(self._active_shadow_roots)
                and self._active_shadow_roots[0]["host_depth"] == self._cr_depth + 1)
            top_level = (len(self.stack) == self._cr_depth + 1) or shadow_top_level
            in_lede = self._lede_depth is not None and len(self.stack) > self._lede_depth
            self._cur_heading = (
                tag, ad.get("id"), [], top_level, in_lede, self._in_shadow_tree())
            self._cur_heading_depth = len(self.stack)
        return (own_skip and not is_shadow, before_mermaid, inert_template, is_shadow)

    def _push_element(self, tag, ad, ns, info):
        own_skip, before_mermaid, inert_template, is_shadow = info
        self.stack.append((tag, own_skip))
        self._push_ancestors(tag, own_skip,
                             tag == "figure" and "chart" in set((ad.get("class") or "").split()),
                             html_template=inert_template, shadow=is_shadow)
        self._shadow_hosts.append(
            None if is_shadow else {
                "used": False, "light": False, "root": None, "id": ad.get("id")})
        current_mermaid = self._mermaid_stack[-1] if self._mermaid_stack else None
        if len(self.mermaid_blocks) > before_mermaid:
            current_mermaid = len(self.mermaid_blocks) - 1
        self._mermaid_stack.append(current_mermaid)

    def _visit_void(self, tag, ad, ns, info):
        self._close_zero_width()

    def _close_zero_width(self):
        """An element that is never PUSHED (a void tag, a self-closed foreign one) has no
        content, so any depth-keyed state `_record` just opened at this depth ends immediately.
        Without this a `<svg id="commentRoot"/>` or `<img id="commentRoot">` would leave
        `_in_comment_root()` true for every later sibling, and CONTENT markers a browser puts
        OUTSIDE the empty root would be read as inside it."""
        self._truncate_stacks(len(self.stack))

    def _visit_self_closed(self, tag, ad, ns):
        # A self-closed FOREIGN element is RECORDED but never pushed - `<svg><rect id="x"/></svg>`
        # is still an element with an id, and a bare `<svg/>` must not be left open (a stale
        # foreign current node would make a following `<![CDATA[` hide live markup).
        if tag == "svg" and self._mermaid_stack:
            idx = self._mermaid_stack[-1]
            if idx is not None:
                self.mermaid_blocks[idx]["has_svg"] = True
        self._mark_light_child()
        self._record(tag, ad, "cm-skip" in set((ad.get("class") or "").split()))
        self._close_zero_width()

    def handle_data(self, data):
        if data.strip(_HTML_WHITESPACE):
            self._mark_light_child()
        self._note_ready_token(data)
        # A non-whitespace character token in "in head" POPS the head and opens the body, so a
        # <meta> written after it is a child of BODY - and the HTML pragma directives return early
        # for a meta that is not a head child. Tracking the head on start tags alone recorded such
        # a policy as the document's, which is the same bypass class the head test exists to close.
        # Scoped to text at html/head level so a <title>/<script>/<style> body - legal head
        # content, and raw text to the tokenizer - does not end it.
        if (not self._csp_head_over and data.strip(_HTML_WHITESPACE)
                and not self._in_template()
                and not self._in_shadow_tree()
                and (not self.stack or self.stack[-1][0] in ("html", "head"))):
            self._csp_head_over = True
        # A template-parked <script>/<style> body is collected ALONGSIDE the ordinary flow (never
        # instead of it), so adding this view cannot change what any existing check sees.
        if self._tpl_captures and self._tpl_captures[-1]["depth"] == len(self.stack) - 1:
            self._tpl_captures[-1]["parts"].append(data)
            return
        # Capture the raw source text of the current mermaid block (entities are already
        # decoded because convert_charrefs=True), so the mermaid syntax checker can read it.
        # Only meaningful before the diagram renders to <svg>; a rendered block's has_svg
        # flag lets the checker skip it. Text parked in a nested HTML <template> is NOT part of
        # the host's textContent (it lives in the template's inert DocumentFragment), which
        # is exactly what mermaid renders from - so it is no more diagram source than a
        # template-parked heading is heading text, and `_record()` already declines to
        # register a mermaid host that is itself inside a template. The check is
        # namespace-aware: a foreign element merely NAMED `template` (under <math> or <svg>)
        # is ordinary content a browser keeps in textContent, so it hides nothing.
        if (self._mermaid_stack and self._mermaid_stack[-1] is not None
                and not self._in_html_template()):
            self.mermaid_blocks[self._mermaid_stack[-1]].setdefault("src_parts", []).append(data)
        if self._raw_captures:
            cap = self._current_raw_capture()
            if cap is not None:
                cap["parts"].append(data)
            return
        if self._cur_heading is not None:
            # Same inertness rule as the prose branch below: a browser renders none of a
            # template's text, so it is not part of the heading a reader sees (which feeds the
            # named cross-reference and document-title checks).
            if not self._in_template():
                self._cur_heading[2].append(data)
            return  # heading text is captured separately, not treated as cross-ref prose
        # Prose inside #commentRoot but NOT inside a link or a cm-skip element, and NOT inside
        # an inert <template> (a browser never renders a template's contents, so text there is
        # not authored prose - `_record()` and the heading capture already decline it). A cross
        # reference that IS a link never lands here, so only UNLINKED references remain.
        if (self._cr_depth is not None and not self._cr_closed and len(self.stack) > self._cr_depth
                and not self._skip_ancestor()
                and not self._in_template()
                and self._ancestors().anchor == 0):
            self.commentroot_prose.append(data)

    def _flush_heading(self):
        """Finalize the heading being captured: its whitespace-collapsed text, its id, and the
        top_level / in_lede flags. Shared by the end tag, by an ancestor's close and by `close()`
        so the paths cannot drift - a heading with no text is dropped by all of them."""
        if self._cur_heading is None:
            self._cur_heading_depth = None
            return
        text = re.sub(r"\s+", " ", "".join(self._cur_heading[2])).strip()
        if text:
            heading = {"tag": self._cur_heading[0],
                       "id": self._cur_heading[1], "text": text,
                       "top_level": self._cur_heading[3],
                       "in_lede": self._cur_heading[4]}
            if self._cur_heading[5]:
                heading["shadow"] = True
            self.headings.append(heading)
        self._cur_heading = None
        self._cur_heading_depth = None

    def close(self):
        """Flush a `<script>`/`<style>`, and a heading, still open at end of input.

        A browser treats an unclosed raw-text element as running to EOF, so its body is LIVE.
        Dropping it here would let a `<style>` with no closing tag hide a real rule from every
        check that reads `parser.styles` (the unscoped-`[hidden]` rule, CMH-VAL-20). A heading
        left open at EOF is live the same way - a browser renders it - so dropping it hid the
        last heading of a truncated document from every heading-derived check. The base close()
        runs FIRST so any buffered trailing data reaches `handle_data` before either flush.
        """
        super().close()
        self._flush_raw_captures(0)
        self._flush_template_raw()
        self._flush_heading()
        # Nested captures finalize innermost FIRST (only reachable in foreign content), so restore
        # DOCUMENT order, which is what every consumer of these two reads them in. A no-op for an
        # ordinary document, where one element closes before the next opens.
        self.scripts.sort(key=lambda s: s["pos"])
        self.styles.sort(key=lambda s: s["pos"])

    def _visit_end(self, tag, index):
        matched_foreign = index >= 0 and self._ns[index][1] != "html"
        if index < 0 and self._end_tag_floor(tag) > 0:
            # A closer an open `<template>` scopes away is one a browser IGNORES, so it must not
            # reach the STATE MACHINES either. Both holes were live: a `</head>` parked in a
            # template ended the head, dropping the favicon `<link>` a browser keeps IN it, and a
            # `</h2>` flushed a heading the author opened OUTSIDE the template - stopping that
            # heading's text at the template and collecting the rest of it as ordinary prose.
            return False
        if (tag == "head" and not matched_foreign and not self._in_template()
                and not self._in_shadow_tree()):
            # The head a `</head>` inside a template ends is the TEMPLATE's own; ending the
            # document's head there dropped the favicon `<link>` written after it.
            self._head_ended = True
        if (not self._csp_head_over and tag in _CSP_HEAD_CLOSERS
                and not matched_foreign and not self._in_template()
                and not self._in_shadow_tree()):
            # `</body>`, `</html>` and `</br>` are "anything else" in both "in head" and "after
            # head": the head is popped and a <body> is inserted, so a policy <meta> written after
            # one is a BODY child whose pragma never runs. `</head>` deliberately does NOT do this
            # (see `csp_metas`), and no other end tag does either - both modes ignore the rest.
            self._csp_head_over = True
        # In the HTML namespace these end tags switch insertion mode without popping. A same-named
        # foreign element is ordinary content and still closes normally.
        if index >= 0 and tag in ("body", "html") and self._ns[index][1] == "html":
            return False
        # The base truncates to `index` from here (the heading ends where the ELEMENT being closed
        # ends, which `_truncate_stacks()` decides by DEPTH - flushing on the tag NAME alone let a
        # same-named heading nested inside a `<template>` end the one the author opened outside
        # it), and an end tag with no open element is IGNORED, as a browser ignores it. That is
        # why the `<script>`/`<style>` captures are finalized from `_truncate_stacks()` and not by
        # name here: a stray `</style>` must not end a capture no element of it ever opened. A
        # template-parked `<script>`/`<style>` is finalized the same way, so an INNER closer (only
        # reachable in foreign content, where those two hold markup) cannot end the outer block
        # early and drop the CSS or code a browser still reads from it.
        return True

    def handle_comment(self, data):
        # A region marker is a comment the AUTHORING TOOLS wrote, so only a REAL comment whose
        # SOURCE is the marker they emit can be one. A browser also creates a comment node for
        # a bogus comment (`<!BEGIN: ...>`, `<?END: ...>`, `</ END: ...>`), which is why those
        # reach this handler at all, and the marker COUNT views match exact source text
        # (CMH-VAL-20) - so matching the comment DATA alone let both a bogus comment and a real
        # but uncounted one (`<!--BEGIN: ...-->`, a `--!>` close) stand in for the real marker.
        raw = self.comment_raw
        if raw is None:
            return
        # Exact match, so a prose comment that merely mentions the marker text
        # ("<!-- note: END: commentable-html - JS is the marker -->") is ignored;
        # a marker inside an inert <template> is ignored too. The JS end marker keeps the
        # padding and decoration tolerance `_region_marker_matches` has (the layer writes its
        # region markers on their own lines inside one comment) - and only that.
        if (self.js_end_marker_pos is None and not self._in_template()
                and not self._in_shadow_tree()
                and _JS_END_MARKER_COMMENT_RE.fullmatch(raw)):
            self.js_end_marker_pos = self._off()
        if _MARKER_HINT in raw:
            self._record_region_marker_comment(raw)
        if not self._in_template() and not self._in_shadow_tree():
            if raw == CONTENT_BEGIN and self._in_comment_root():
                self._in_content_region = True
                self.content_region_opened = True
            elif raw == CONTENT_END:
                if self._in_content_region:
                    self.content_region_closed = True
                self._in_content_region = False

    def _record_region_marker_comment(self, raw):
        # Any REAL comment that could carry a region marker, recorded as a span. The layer check
        # asks only "does the parse have a comment here?", because the shipped documents write
        # their BEGIN markers inside a decorated comment (a rule of `=` lines plus prose) that the
        # count view happily reads a marker line out of - so demanding a byte-canonical comment
        # source would refuse every real document. `_in_template()` (not the namespace-aware form)
        # is deliberate: it is the predicate the parse-driven consumers above use, and the whole
        # contract here is that this list and they agree about which comments are live.
        off = self._off()
        span = (off, off + len(raw))
        if self._in_template():
            self.template_comment_spans.append(span)
        elif self._in_shadow_tree():
            self.shadow_comment_spans.append(span)
        else:
            self.marker_comment_spans.append(span)


# --------------------------------------------------------------------------- #
# Parsed <pre>/<code> spans - the scan boundary CMH-VAL-11 and CMH-KQL-08 share.
# --------------------------------------------------------------------------- #


class _CodeSpanParser(_BrowserBoundaries):
    """Record the offsets of every real `<pre>` element and of the `<code>` elements inside
    it, so the code-block checks read PARSED elements instead of matching text.

    Each `<pre>` record carries its parsed attributes, the span of its inner content
    (offsets into the ORIGINAL document, so a payload is always sliced from the bytes that
    ship), whether an ancestor is a `figure.cmh-kql`, and the `<code>` elements found under
    it. `unclosed` is True when a `<pre>` or a `<code>` never got its own end tag - the
    shape a raw `<script>`/`<style>`/`<!--` opened inside a code block produces, which the
    browser's raw-text mode swallows the same way, so the callers fail CLOSED on it.

    Everything a text scan got wrong falls out of parsing: a `>` inside a QUOTED attribute
    value no longer ends a tag, comments and raw-text/RCDATA bodies and `<![CDATA[ ]]>`
    sections contribute no elements, and a construct mentioned inside any of them cannot
    start a match that swallows the author's real block.
    """

    def __init__(self, html):
        super().__init__(html)
        self._stack = []   # [(tag, record, is_kql_figure)], parallel to the namespace stack
        self._anc = []     # parallel to _stack: (nearest open <pre> index, open kql figures)
        self.pres = []
        self.unclosed = False

    # -- element tracking -------------------------------------------------- #

    _NO_ANCESTORS = _CodeAncestors(-1, 0)

    def _ancestors(self):
        return self._anc[-1] if self._anc else self._NO_ANCESTORS

    def _push_ancestors(self, is_pre, is_kql_figure):
        prev = self._ancestors()
        self._anc.append(_CodeAncestors(len(self._anc) if is_pre else prev.pre,
                                        prev.kql_figure + bool(is_kql_figure)))

    def _open_pre(self):
        # The nearest open <pre>'s record, tracked as the stack grows: walking the open elements
        # per <code> is quadratic on a deeply nested document.
        i = self._ancestors().pre
        return self._stack[i][1] if i >= 0 else None

    def _mark_unclosed(self, start):
        for entry in self._stack[start:]:
            if entry[0] in ("pre", "code") and entry[1] is not None:
                self.unclosed = True

    def _before_truncate(self, depth):
        # A foreign-content breakout or an implicit </p>/</li> close pops these without their
        # own end tag - the destroyed structure the callers must fail CLOSED on.
        self._mark_unclosed(depth)

    def _truncate_stacks(self, depth):
        super()._truncate_stacks(depth)
        del self._stack[depth:]
        del self._anc[depth:]

    def _visit_start(self, tag, ad, ns, opens):
        rec = None
        if tag == "pre" and ns == "html":
            rec = {"attrs": ad, "start": self._off(), "inner_start": self._start_tag_end(),
                   "inner": None, "codes": [],
                   "in_kql_figure": self._ancestors().kql_figure > 0}
            self.pres.append(rec)
        elif tag == "code" and ns == "html":
            owner = self._open_pre()
            if owner is not None:
                rec = {"attrs": ad, "start": self._off(),
                       "inner_start": self._start_tag_end(), "inner": None}
                owner["codes"].append(rec)
        return rec

    def _push_element(self, tag, ad, ns, info):
        is_kql_figure = (tag == "figure" and ns == "html"
                         and parsed_attrs_have_class(ad, "cmh-kql"))
        self._stack.append((tag, info, is_kql_figure))
        self._push_ancestors(tag == "pre", is_kql_figure)

    def _visit_end(self, tag, index):
        if index < 0:
            return
        self._mark_unclosed(index + 1)   # implicitly closed: they never got their own closer
        own = self._stack[index][1]
        if own is not None:
            own["inner"] = (own["inner_start"], self._off())

    def close(self):
        super().close()
        self._mark_unclosed(0)


class CodeSpans:
    """The parsed result.

    `pres` is a read-only tuple of `<pre>` records; each record is a read-only mapping with
    `attrs` (the parsed attribute dict), `inner` (an `(start, end)` offset pair into the
    ORIGINAL document, or None when the element never closed), `codes` (a tuple of the same
    shape for the `<code>` elements inside it) and `in_kql_figure`. INVARIANT: `inner is None`
    implies `unclosed` is True, so a caller that slices `inner` MUST null-check it (the element
    is already reported through the fail-closed flag). `unclosed` is True when a `<pre>`/`<code>`
    never got its own end tag, so the structure cannot be trusted; `failed` is True when the
    parse itself blew up, in which case NO block was collected and every consumer must fail
    closed rather than conclude the document is clean. The records are frozen because the result
    is CACHED and shared between checks - a consumer that stamped a field on one would silently
    poison the next check's view.
    """

    __slots__ = ("pres", "unclosed", "failed")

    def __init__(self, pres, unclosed, failed=False):
        self.pres = pres
        self.unclosed = unclosed
        self.failed = failed


def _freeze_pres(pres):
    frozen = []
    for pre in pres:
        rec = dict(pre)
        rec["attrs"] = MappingProxyType(dict(pre["attrs"]))
        codes = []
        for c in pre["codes"]:
            cr = dict(c)
            cr["attrs"] = MappingProxyType(dict(c["attrs"]))
            codes.append(MappingProxyType(cr))
        rec["codes"] = tuple(codes)
        frozen.append(MappingProxyType(rec))
    return tuple(frozen)


@functools.lru_cache(maxsize=1)
def code_block_spans(html):
    """Parse `html` and return the `CodeSpans` for its `<pre>`/`<code>` elements.

    Cached for the last document because more than one check needs the same spans for the
    same (multi-megabyte) document per validation run. A malformed document never raises: the
    parser is tolerant, and anything it could not close is reported through `unclosed` so the
    callers fail closed instead of silently inspecting nothing.
    """
    p = _CodeSpanParser(html)
    try:
        p.parse_document(html)
    except Exception:
        # A tolerant parse should not raise, but a code-block guardrail must never be the thing
        # that crashes a validation run. Report NOTHING (a partial block list would let a check
        # conclude the rest of the document is clean) and flag the failure so every consumer
        # fails CLOSED.
        return CodeSpans((), True, True)
    return CodeSpans(_freeze_pres(p.pres), p.unclosed)


class _RawTextSpanParser(_CodeSpanParser):
    """Record the body span of every real raw-text / RCDATA element, reusing the shared tokenizer.

    The point is to get raw-text boundaries a BROWSER agrees with without a second text scan:
    a `<script` NAMED inside a comment never opens a raw-text region, a `>` inside a quoted
    attribute value never ends a start tag, and an end tag the browser honours (`</script/>`,
    `</script data-x>`) really closes one. EVERY raw-text element counts, not just
    `<script>`/`<style>`: a region marker written inside a `<textarea>` or the print
    `<noscript>` is TEXT a reader sees, so the marker scan must blank it exactly as the document
    parser ignores it - otherwise the two views disagree about where a region begins.
    """

    def __init__(self, html):
        super().__init__(html)
        self._raw = None          # (tag, body_start, in_template) while inside a raw-text element
        self._length = len(html)
        self.raw_spans = []

    def _raw_in_template(self):
        # The HTML-template floor `_end_tag_floor()` reads, answered in O(1). A raw-text body
        # parked inside an inert `<template>` is not live content, and one caller - the CSS
        # region's `/* */` marker exemption - must not accept a `<style>` that a browser never
        # applies.
        return bool(self._tpl_stop) and self._tpl_stop[-1] >= 0

    def _after_start(self, tag, ad, ns, opens):
        super()._after_start(tag, ad, ns, opens)
        if self._raw is None and self.cdata_elem is not None:
            self._raw = (self.cdata_elem, self._start_tag_end(), self._raw_in_template())

    def _visit_end(self, tag, index):
        if self._raw is not None and tag == self._raw[0]:
            self.raw_spans.append((self._raw[1], self._off(), self._raw[0], self._raw[2]))
            self._raw = None
        super()._visit_end(tag, index)

    def close(self):
        super().close()
        if self._raw is not None:
            # A browser runs an unclosed raw-text element to the end of the document.
            self.raw_spans.append((self._raw[1], self._length, self._raw[0], self._raw[2]))
            self._raw = None


@functools.lru_cache(maxsize=1)
def raw_text_spans(html):
    """`((body_start, body_end, tag, in_template), ...)` for every real raw-text / RCDATA
    element, or None when the parse blew up. The TAG and the template flag matter to one caller:
    the Shareable CSS region's markers are `/* ... */` comments inside a LIVE `<style>`, which a
    browser never turns into comment NODES, so that - and only that - raw-text body may
    legitimately hold a counted region marker."""
    p = _RawTextSpanParser(html)
    try:
        p.parse_document(html)
    except Exception:
        return None
    return tuple(p.raw_spans)


@functools.lru_cache(maxsize=1)
def content_marker_scan(html):
    """The view the CONTENT and region markers are COUNTED and LOCATED in: every RAW-TEXT body
    (`<script>`, `<style>`, `<textarea>`, `<title>`, `<noscript>`, ...) blanked, comments KEPT
    (the markers ARE comments, so unlike a code-block view this must not blank them). A marker
    quoted inside script data or a textarea is not a real boundary, so counting it would both
    forge a duplicate-marker error and disagree with the layer views about where the content
    region is. Blanking preserves offsets AND line breaks, so a caller can locate a
    span here and slice the ORIGINAL string for the payload.

    A parse that blew up falls back to the raw document. That direction is deliberate: an
    unblanked scan can only over-count markers or over-report the export warning, which is noise
    an author can see and act on, whereas an empty view would silently report a document that
    has its markers as having none.
    """
    spans = raw_text_spans(html)
    if spans is None:
        return html
    out = list(html)
    for start, end, _tag, _in_tpl in spans:
        for k in range(start, end):
            if out[k] not in "\r\n":
                out[k] = " "
    return "".join(out)


@functools.lru_cache(maxsize=1)
def layer_regions_text(html):
    """Return only the text inside the layer's own MARKUP regions (an ALLOW-list).

    For "does the LAYER contain X?", a deny-list ("the whole document minus the parts a user
    writes") cannot be made safe: user text reaches `<title>`, `data-doc-label`, `<meta>` and
    every other attribute - `new_document --label` copies the label verbatim into two of them -
    so any of those can forge the verdict. This returns the CSS, COMMENT UI and JS regions only.
    The other two regions (HANDLED IDS, EMBEDDED COMMENTS) exist precisely to CARRY user text -
    a reviewer's comment bodies and the reviewed-section headings an export bakes in - so they
    are state containers, not layer markup, and are never inspected. Regions are located in
    `content_marker_scan`'s view, so a region marker quoted in script data is not a boundary.
    """
    scan = content_marker_scan(html)
    parts = []
    for region in LAYER_MARKUP_REGIONS:
        begins = _region_marker_matches(scan, "BEGIN", region)
        ends = _region_marker_matches(scan, "END", region)
        if len(begins) != 1 or len(ends) != 1:
            continue
        start, end = begins[0].end(), ends[0].start()
        if end > start:
            parts.append(html[start:end])
    return "\n".join(parts)


def _is_json_attrs(ad):
    return (ad.get("type", "") or "").split(";")[0].strip().lower() == "application/json"


# Script types the browser executes natively as classic/module JavaScript. This is the HTML
# spec's "JavaScript MIME type" set plus the empty type and `module`: a LEGACY type such as
# `text/ecmascript`, `application/x-javascript`, `text/jscript`, `text/livescript`, or
# `text/javascript1.0`-`1.5` still RUNS in a browser, so treating one as inert would let a
# loader - or, in offline mode, a remote dynamic import - pass a check whose whole job is to
# notice executable code. It mirrors `_offlineIsRunnableScriptType` in
# assets/js/68-export-offline.js exactly, and tests/test_vendored_libs.py pins the two together
# so the validator and the exporter's strips can never disagree about what runs. A type outside
# it (application/json, importmap, text/plain, and transpiler-only text/babel / text/jsx which
# need a runtime the validator cannot assume) does not run, so it must not satisfy loader / init.
_JS_TYPES = frozenset(
    {"", "module"}
    | {"%s/%sscript" % (top, prefix + family)
       for top in ("text", "application")
       for prefix in ("", "x-")
       for family in ("java", "ecma")}
    | {"text/javascript1.%d" % minor for minor in range(6)}
    | {"text/jscript", "text/livescript"}
)


def _is_executable_js(ad):
    return (ad.get("type", "") or "").split(";")[0].strip().lower() in _JS_TYPES


def _csp_predecessor_fetches(tag, ad):
    """Whether an element parsed BEFORE a policy `<meta>` can fetch or execute, which is what makes
    that policy too late to be the document's guarantee (a meta-delivered policy is not
    retroactive).

    Decided by CAPABILITY rather than by tag name wherever the tag alone cannot answer it: a
    `rel=canonical` link loads nothing and a `type=application/json` block neither runs nor loads,
    so treating either as a fetch would reject a clean document with a message claiming something
    the element cannot do. A `<script>` still counts when it carries any of the load attributes the
    self-contained gate reads (`src`, and the SVG spellings, since an SVG script uses no `src` at
    all), or when its type is one a browser RUNS - which is the exporter's own `_JS_TYPES` set, so
    the two agree about what executes."""
    if tag in _CSP_INERT_PREDECESSORS:
        return False
    if tag == "link":
        return bool(set((ad.get("rel") or "").lower().split()) & FETCHING_LINK_RELS)
    if tag == "script":
        return bool(ad.get("src") or ad.get("href") or ad.get("xlink:href")) or _is_executable_js(ad)
    return True


_REGEX_KEYWORDS = frozenset((
    "return", "typeof", "instanceof", "in", "new", "delete", "void",
    "case", "default", "do", "else", "extends", "throw",
))
# A `)` that closes one of these heads is followed by a statement, so a `/` there
# opens a regex (`if (x) /re/.test(s)`); any other `)` closes a value (division).
_CTRL_HEAD_KEYWORDS = frozenset(("if", "while", "for", "switch", "catch", "with"))
# JS line terminators: none of them may appear inside a regex literal.
_JS_LINE_TERMINATORS = ("\n", "\r", "\u2028", "\u2029")
# Cap on the total regex lookahead per script body, as a multiple of its length.
_REGEX_LOOKAHEAD_FACTOR = 4


def _is_ident_char(c):
    return bool(c) and (c.isalnum() or c in ("_", "$"))


def _regex_can_start(prev_kind, prev_word, prev_is_prop):
    """Whether a `/` at this point opens a regex literal rather than division,
    using the usual prev-significant-token heuristic. `prev_kind` is the kind of
    the last significant token: "" (start of body), "value" (identifier, number,
    closing bracket, postfix `++`/`--`, or a closed string / template / regex
    literal), "word" (an identifier whose text is `prev_word`), or "op" (an
    operator, a punctuator, or a control-head `)`). Only RESERVED words open a
    regex - a contextual keyword that can legally be a variable name (`of`,
    `yield`, `await`) is left out, because reading division as a regex is the
    failure that blanks live code."""
    if prev_kind == "":
        return True
    if prev_kind == "word":
        return not prev_is_prop and prev_word in _REGEX_KEYWORDS
    return prev_kind == "op"


def _scan_regex(body, i, stop):
    """End offset (past the flags) of the regex literal starting at body[i] == '/',
    or None when it does not terminate on that line (then it was division) or when
    it runs past `stop` (the lookahead budget). A `/` inside a [...] character
    class does not terminate the literal."""
    n, j, in_class = len(body), i + 1, False
    while j < stop:
        c = body[j]
        if c in _JS_LINE_TERMINATORS:
            return None
        if c == "\\":
            # An escaped line terminator is not legal in a regex literal either.
            if body[j + 1:j + 2] in ("", "\n", "\r", "\u2028", "\u2029"):
                return None
            j += 2
            continue
        if in_class:
            if c == "]":
                in_class = False
        elif c == "[":
            in_class = True
        elif c == "/":
            j += 1
            while j < n and _is_ident_char(body[j]):
                j += 1
            return j
        j += 1
    return None


def _string_closes_on_its_line(body, i):
    """Whether the '/" string opened at body[i] closes before the line ends. A
    quoted string may not contain a raw line terminator, so one that does not
    close is NOT a string (typically a quote inside a regex literal the
    prev-token heuristic read as division) and must not open a phantom string
    that blanks the rest of the script."""
    n, j, quote = len(body), i + 1, body[i]
    while j < n:
        c = body[j]
        if c == "\\":
            # A line continuation is legal inside a string; CRLF counts as one.
            j += 3 if body[j + 1:j + 3] == "\r\n" else 2
            continue
        if c in _JS_LINE_TERMINATORS:
            return False
        if c == quote:
            return True
        j += 1
    return False


def _js_scan(body):
    """Single left-to-right pass over a script body that is string / template /
    regex / comment aware, returning two length-preserving views:
      - guard_src: JS comments and regex literals blanked, string literals KEPT
        (a real `typeof Chart === "undefined"` guard needs its "undefined"
        string; a guard is never written as a regex).
      - init_src:  JS comments AND string / template / regex literals blanked (a
        real `new Chart(` is executable code, never inside a literal).
    Because it is one pass, a `//` or `/*` that lives INSIDE a string can never
    start a fake comment (the string is entered first), a quote inside a comment
    can never open a fake string, and a quote or backtick inside a regex literal
    can never open a fake string or template (which used to blank the rest of the
    script). Where regex-versus-division is genuinely ambiguous the scanner reads
    DIVISION, so mis-reading a division as a literal never blanks live code; a
    quote left unterminated by such a read is contained to its own line (a quoted
    string may not span one). A regex MISSED that way whose body holds a backtick
    can still open a phantom template - the accepted residual is a regex right
    after a `}` (a statement block and an object literal are indistinguishable
    here). Template SUBSTITUTIONS are still treated as string content - see
    SKILL.md Design decisions."""
    n = len(body)
    guard = list(body)   # comments and regex literals -> space, strings kept
    init = list(body)    # comments AND strings AND regex literals -> space
    i, state = 0, None   # state: None | "'" | '"' | '`' | 'line' | 'block'
    # Last significant token: its kind, its text when it is an identifier, and
    # whether that identifier was a property access (`obj.return` is not `return`).
    # `word_open` says the scanner is still INSIDE that identifier, so `else if`
    # does not concatenate into one `elseif` token.
    prev_kind, prev_word, prev_is_prop = "", "", False
    prev_char, prev_kind2, prev_word2, word_open = "", "", "", False
    ctrl_parens = []     # per open `(`: whether it is an if/while/for/... head
    # Total regex lookahead is bounded so a pathological line of unterminated
    # candidates (`x=/[` repeated) cannot make the single pass quadratic; once
    # the budget is spent a `/` simply reads as division, as it did before.
    budget = _REGEX_LOOKAHEAD_FACTOR * n + 1024
    while i < n:
        ch = body[i]
        nx = body[i + 1] if i + 1 < n else ""
        if state is None:
            if ch == "/" and nx == "/":
                guard[i] = guard[i + 1] = " "; init[i] = init[i + 1] = " "
                state, word_open = "line", False; i += 2; continue
            if ch == "/" and nx == "*":
                guard[i] = guard[i + 1] = " "; init[i] = init[i + 1] = " "
                state, word_open = "block", False; i += 2; continue
            if ch == "/":
                end = None
                if budget > 0 and _regex_can_start(prev_kind, prev_word, prev_is_prop):
                    stop = min(n, i + budget)
                    end = _scan_regex(body, i, stop)
                    budget -= (end if end is not None else stop) - i
                if end is not None:
                    for k in range(i, end):
                        guard[k] = init[k] = " "
                    prev_kind2, prev_kind, prev_word = prev_kind, "value", ""
                    prev_is_prop, prev_char, word_open = False, "/", False
                    i = end; continue
            if ch in ("'", '"', "`"):
                if ch == "`" or _string_closes_on_its_line(body, i):
                    init[i] = " "; state = ch; i += 1; continue
                # not a real string opener: treat it as an ordinary character
            if ch.isspace():
                word_open = False
                i += 1; continue
            kind_before = prev_kind
            if _is_ident_char(ch):
                if word_open:
                    prev_word += ch
                else:
                    prev_word2, prev_word, prev_is_prop = prev_word, ch, prev_char == "."
                prev_kind, word_open = "word", True
            else:
                word_open = False
                if ch == "(":
                    head = (prev_kind == "word" and not prev_is_prop
                            and (prev_word in _CTRL_HEAD_KEYWORDS
                                 or (prev_word == "await" and prev_word2 == "for")))
                    ctrl_parens.append(head)
                    prev_kind, prev_word, prev_is_prop = "op", "", False
                elif ch == ")":
                    head = ctrl_parens.pop() if ctrl_parens else False
                    prev_kind, prev_word, prev_is_prop = ("op" if head else "value"), "", False
                elif ch in ("]", "}"):
                    prev_kind, prev_word, prev_is_prop = "value", "", False
                elif ch in ("+", "-") and i > 0 and body[i - 1] == ch:
                    # `x++ /` divides; a PREFIX `++/re/` does not, so the kind
                    # before the first `+`/`-` decides.
                    postfix = prev_kind2 in ("value", "word")
                    prev_kind, prev_word, prev_is_prop = ("value" if postfix else "op"), "", False
                else:
                    prev_kind, prev_word, prev_is_prop = "op", "", False
            prev_kind2 = kind_before
            prev_char = ch
            i += 1; continue
        if state == "line":
            if ch in _JS_LINE_TERMINATORS:
                state = None
            else:
                guard[i] = init[i] = " "
            i += 1; continue
        if state == "block":
            if ch == "*" and nx == "/":
                guard[i] = guard[i + 1] = " "; init[i] = init[i + 1] = " "; state = None; i += 2; continue
            if ch != "\n":
                guard[i] = init[i] = " "
            i += 1; continue
        # inside a string / template literal
        if ch == "\\":
            init[i] = " "
            if i + 1 < n and body[i + 1] != "\n":
                init[i + 1] = " "
            i += 2; continue
        if ch == state:
            init[i] = " "; state = None
            # A closed literal is a value, so a following `/` divides.
            prev_kind2, prev_kind, prev_word = prev_kind, "value", ""
            prev_is_prop, prev_char, word_open = False, ch, False
            i += 1; continue
        if ch != "\n":
            init[i] = " "
        i += 1; continue
    return "".join(guard), "".join(init)


def _parser_script(parser, script_id, lo=None, hi=None):
    """The first <script> dict (attrs+body+pos) whose id == script_id (optionally
    restricted to the [lo, hi) byte range)."""
    for s in parser.scripts:
        if s["attrs"].get("id") != script_id:
            continue
        if lo is not None and not (lo <= s["pos"] < hi):
            continue
        return s
    return None


def _parser_script_body(parser, script_id, lo=None, hi=None):
    """Body of the first <script> whose id == script_id (optionally restricted to
    the [lo, hi) byte range so a decoy with the same id elsewhere is ignored)."""
    s = _parser_script(parser, script_id, lo, hi)
    return s["body"] if s is not None else None


class _TagAttrParser(_BrowserBoundaries):
    """Index every start tag's attribute dict, drawing the SAME element boundaries the document
    parser draws (CMH-VAL-21).

    This used to be a bare `HTMLParser`, so the lookup the resource checks read and the
    `_DocParser` view every other check reads disagreed about what an element even IS - and the
    disagreement was reachable: `html.parser` consumes a whole `<![CDATA[ ... ]]>` marked section
    in any context, where a browser treats one in HTML content as a BOGUS COMMENT ending at the
    first `>`. So `<![CDATA[><script src="//evil.example/x.js"></script>]]>` left a LIVE external
    script that the document parser reported and this lookup did not, and the self-contained /
    offline checks read this lookup.

    Every tag is indexed in ONE pass (`found` maps tag name -> attribute dicts) because a single
    validation run asks about a dozen tags, and re-parsing a multi-megabyte document per tag is
    what the cache on `_tag_attr_index()` below exists to avoid.

    ONE deliberate departure from the shared view, for the EGRESS question only: a `<noscript>`
    body is raw TEXT while scripting is ENABLED. With scripting off a browser parses it as
    markup and really does load what it names, and this lookup is what the self-contained /
    offline resource checks read - so the body is re-parsed and its elements are collected in a
    SEPARATE index (`noscript_found`). A caller asking "does this document load anything over
    the network?" opts into that superset and fails CLOSED on it; a caller asking "does this
    document HAVE element X?" must not, because a scripting-enabled browser never creates it -
    a CSP `<meta>` or a Run link buried in a `<noscript>` would otherwise satisfy a requirement
    no reader of the layer can see.

    The re-parse is a SCRIPTING-DISABLED pass, so `<noscript>` is TRANSPARENT inside it (a
    browser with scripting off parses every nested one as ordinary markup). That keeps the
    fallback exactly one level deep - no recursion to cap, and no depth at which a nested
    `<noscript>`'s resources could silently drop out of the index.
    """

    def __init__(self, html, _fallback=False):
        super().__init__(html)
        self._stack = []   # open element tags, parallel to the namespace stack
        self._fallback = _fallback   # this is the scripting-disabled pass over a <noscript> body
        self._noscript = None        # buffered raw text of the <noscript> body being read
        self._cur_style = []         # open fallback <style> captures: [(attrs, depth, [parts])],
                                     # a STACK for the same reason `_DocParser` keeps one: outside
                                     # the HTML namespace a `<style>` holds MARKUP, so one can
                                     # contain another and a breakout can pop one early. With a
                                     # scalar the outer body - CSS a browser still applies - was
                                     # dropped, hiding its egress from the offline gate.
        self.found = {}
        self.noscript_found = {}
        self.styles = []             # {"attrs", "body"} per <style> seen by a fallback pass
        self.noscript_styles = []    # the same, lifted out of this document's <noscript> bodies
        self.failed = False
        self.eof_in_tag = False
        self.eof_raw_text_elem = None  # raw-text element still open when the input ran out

    def _truncate_stacks(self, depth):
        self._flush_style(depth)
        super()._truncate_stacks(depth)
        del self._stack[depth:]

    def _flush_style(self, depth=0):
        """Record each `<style>` body the element at `depth` (or an ancestor) closed, innermost
        first. Only the scripting-DISABLED pass buffers one: the document's own style bodies are
        read off `_DocParser`, and re-collecting them here would keep a second copy of the whole
        layer stylesheet per cached document."""
        while self._cur_style and self._cur_style[-1][1] >= depth:
            ad, _depth, parts = self._cur_style.pop()
            self.styles.append({"attrs": ad, "body": "".join(parts)})

    def _record(self, tag, ad):
        self.found.setdefault(tag, []).append(ad)

    def handle_data(self, data):
        if self._noscript is not None:
            self._noscript.append(data)
        # Only the capture whose element is the CURRENT NODE, for the reason `_DocParser`'s
        # `_current_raw_capture()` gives: a browser reads a `<style>`'s CSS from its own child
        # text nodes, and text under a nested element (reachable only in foreign content) is that
        # element's, not the ancestor's.
        if self._cur_style and self._cur_style[-1][1] == len(self._stack) - 1:
            self._cur_style[-1][2].append(data)

    def _enter_raw_text(self, tag, ns):
        if tag == "noscript" and self._fallback:
            return   # scripting is off in this pass, so <noscript> holds markup, not text
        super()._enter_raw_text(tag, ns)

    def _drop_if_truncated(self, k):
        if k < 0 and self._final:
            self.eof_in_tag = True
        return super()._drop_if_truncated(k)

    def _flush_noscript(self, at_eof=False):
        """Index the buffered `<noscript>` body as the MARKUP a scripting-disabled browser sees."""
        parts, self._noscript = self._noscript, None
        body = "".join(parts or ())
        if "<" not in body:
            return
        inner = _TagAttrParser(body, _fallback=True)
        try:
            inner.parse_document(body)
        except Exception:
            # Keep whatever it collected - a partial fallback view still fails closed - but SAY
            # so, or "could not look" would read like "nothing more to find".
            self.failed = True
        # The body's END was decided by the scripting-ENABLED tokenizer (the first `</noscript`),
        # but a scripting-DISABLED browser is in the DATA state there, so a `</noscript` inside a
        # quoted attribute VALUE is just text to it. The two views then disagree about where the
        # body stops, and the tag straddling that seam reaches the inner parse truncated - which
        # the browser EOF rule correctly discards, leaving a live resource in NEITHER index. It
        # cannot be resolved from the buffered text, so it is REPORTED instead of dropped.
        self.failed = self.failed or inner.failed or inner.eof_in_tag
        # The same seam, reached from a state the fallback parse could not leave. The body's END
        # is decided by the scripting-ENABLED tokenizer at the first `</noscript`, but a
        # scripting-DISABLED browser reaches that point in whatever state its own parse of the
        # fallback markup put it in. Unless that state is DATA, the two tokenizers disagree about
        # the REST OF THE DOCUMENT, and the disagreement cannot be reconciled from the buffered
        # text - so the document is REPORTED rather than certified.
        #
        # Both non-data end states are live bypasses, not theory:
        #   `<noscript><style>/* </noscript> */ body{background:url(...)}</style></noscript>`
        #     - the sheet runs on past the seam and its CSS fetches;
        #   `<noscript><title></noscript><!-- </title><img src="..."> --></noscript>`
        #     - the disabled reader leaves the raw text at a closer written AFTER the seam and is
        #       back in markup, where the enabled view only has a comment;
        #   `<noscript><!-- </noscript><textarea> --><img src="..."></textarea></noscript>`
        #     - the mirror image, the disabled reader in a comment across the seam.
        # In each the live reference is in NEITHER index, which is why the guard is the tokenizer
        # STATE and not the identity of the element that happens to hold it.
        #
        # Only when a real `</noscript>` drew the seam: a body that ran to end of document has no
        # disagreement to report - it is the end of the document for both views.
        if not at_eof and (inner.eof_raw_text_elem is not None or inner.eof_unterminated):
            self.failed = True
        for source in (inner.found, inner.noscript_found):
            for tag, ads in source.items():
                self.noscript_found.setdefault(tag, []).extend(ads)
        # A nested `<noscript>` is transparent in the fallback pass, so `inner.noscript_styles` is
        # empty there; it is merged anyway so the two indexes are lifted by the same rule.
        self.noscript_styles.extend(inner.styles)
        self.noscript_styles.extend(inner.noscript_styles)

    def _visit_start(self, tag, ad, ns, opens):
        self._record(tag, ad)
        if self._fallback and tag == "style":
            # Recorded BEFORE the push, so the depth is the index this element occupies and any
            # truncation that removes it (its own end tag, an ancestor's, a breakout) flushes it.
            self._cur_style.append((ad, len(self._stack), []))

    def _push_element(self, tag, ad, ns, info):
        self._stack.append(tag)

    def _after_start(self, tag, ad, ns, opens):
        if tag == "noscript" and self.cdata_elem == "noscript":
            self._noscript = []

    def _visit_self_closed(self, tag, ad, ns):
        # Still an element with attributes, but never left open.
        self._record(tag, ad)

    def _visit_end(self, tag, index):
        if tag == "noscript" and self._noscript is not None:
            self._flush_noscript()

    def close(self):
        # The base flushes the tail of an UNCLOSED raw-text element first, so a `<noscript>` that
        # never closes still contributes its fallback markup (a browser runs it to EOF too), and
        # an unclosed `<style>` still contributes the body a browser reads to EOF as CSS. Record
        # that the input ENDED in raw text before the base clears the mode: the caller of a
        # fallback parse needs it to tell a body a `</noscript>` ended from one that ran out, and
        # to tell CSS (which fetches) from inert text.
        self.eof_raw_text_elem = self.cdata_elem
        super().close()
        self._flush_style()
        if self._noscript is not None:
            self._flush_noscript(at_eof=True)


class _TagIndex(NamedTuple):
    """The shared per-document tag index. NAMED rather than a bare tuple because its consumers
    read it by position and one of them - `_tag_attrs_failed()` reading `failed` - is the
    fail-CLOSED guard the whole self-contained guarantee rests on: a later field inserted ahead of
    it would silently make that guard read the wrong slot instead of raising."""
    found: dict
    noscript_found: dict
    noscript_styles: tuple
    failed: bool


@functools.lru_cache(maxsize=32)
def _tag_attr_index(html):
    """A `_TagIndex` for `html`: every start tag mapped to its browser-decoded attribute dicts,
    the `<noscript>` fallback markup indexed separately, the `<style>` bodies that fallback markup
    declares, and whether the parse blew up.

    Cached like `code_block_spans`, because one validation run asks the same (multi-megabyte)
    document about a dozen different tags. Room for more than the last document, because a check
    legitimately interleaves a FRAGMENT lookup (a KQL figure's inner HTML) with the whole
    document's - at maxsize=1 those two would evict each other and re-parse the document every
    time. `validate()` clears the cache when a document's checks are done, so nothing is held
    past the run. The dicts are frozen so a caller can never mutate the shared view.

    A tolerant parse should not raise, but if it does the collected part is kept AND `failed` is
    set, because a silently PARTIAL index would let the self-contained check conclude that the
    rest of the document loads nothing."""
    p, failed = None, False
    try:
        p = _TagAttrParser(html)
        p.parse_document(html)
    except Exception:
        failed = True
    found = p.found if p is not None else {}
    noscript_found = p.noscript_found if p is not None else {}
    noscript_styles = p.noscript_styles if p is not None else []
    failed = failed or (p is not None and p.failed)
    return _TagIndex(
        _freeze_tag_attrs(found), _freeze_tag_attrs(noscript_found),
        tuple(MappingProxyType({"attrs": MappingProxyType(s["attrs"]), "body": s["body"]})
              for s in noscript_styles),
        failed)

def _freeze_tag_attrs(found):
    return {tag: tuple(MappingProxyType(ad) for ad in ads) for tag, ads in found.items()}


def _find_tag_attrs(html, tag):
    """The attribute dict of every occurrence of `tag`, as a browser with scripting ENABLED sees
    the document - the view a PRESENCE question must ask ("does this document declare X?")."""
    found = _tag_attr_index(html or "").found
    return [dict(ad) for ad in found.get(_ascii_lower(tag), ())]


def _find_tag_attrs_egress(html, tag):
    """The same, PLUS the `<noscript>` fallback markup a scripting-DISABLED browser parses and
    loads - the view an EGRESS question must ask ("does this document load anything over the
    network?"). Deliberately a separate function rather than a flag on the one above: a missed
    argument would be a silent hole in one direction and a fail-open policy check in the other."""
    idx = _tag_attr_index(html or "")
    found, noscript_found = idx.found, idx.noscript_found
    key = _ascii_lower(tag)
    return ([dict(ad) for ad in found.get(key, ())]
            + [dict(ad) for ad in noscript_found.get(key, ())])


def _find_noscript_styles(html):
    """The `<style>` bodies a `<noscript>` fallback declares, as [{"attrs", "body"}].

    The EGRESS-only complement to `_DocParser.styles`: with scripting ENABLED a `<noscript>` body
    is raw TEXT, so the document view holds no style element for it at all, but with scripting OFF
    a browser parses that body and its `@import` / `url(...)` really are fetched. Returned as its
    own list rather than folded into the document view, so the offline CSS scans opt in the way
    every other egress lookup does and a PRESENCE question keeps reading the browser's view.

    Like every other egress lookup this reads the SHARED index, so a caller must already have
    consulted `_tag_attrs_failed(html)`: an empty result on a failed parse means "could not
    look", not "no styles"."""
    return [{"attrs": dict(s["attrs"]), "body": s["body"]}
            for s in _tag_attr_index(html or "").noscript_styles]


def _find_noscript_inline_styles(html):
    """The `style=` attributes a `<noscript>` fallback declares, as [{"tag", "value"}] - the same
    EGRESS-only complement, for `_DocParser.inline_styles`."""
    noscript_found = _tag_attr_index(html or "").noscript_found
    return [{"tag": tag, "value": ad.get("style", "")}
            for tag, ads in noscript_found.items() for ad in ads if "style" in ad]


def _is_event_handler_attr(name):
    """Whether an attribute name is an inline event handler, by the EXPORTER's literal `^on` test.

    Its own scrub is `/^on/i`, which also matches `once` and `onward`; matching it exactly is the
    point, since a validator that drew the line anywhere else would bless an attribute the strip
    takes away (or reject one it leaves alone). Kept as a named predicate so the parity test can
    run the two spellings over one corpus.
    """
    return (name or "")[:2].lower() == "on"


def _find_event_handler_attrs_egress(html):
    """Every `on*` attribute in the document, as [{"tag", "attr"}] - the view the OFFLINE
    event-handler gate needs, because the exporter's scrub walks `querySelectorAll("*")` on a
    DOMParser document where scripting is OFF. That walk reaches two shapes the document parser's
    start-tag scan did NOT: a self-closed FOREIGN element (`<svg><rect onload=.../>`, which returns
    before any start-tag bookkeeping), and the markup inside a `<noscript>` (raw TEXT to a
    scripting-ENABLED parse, and live for the reader who cannot run the layer at all).
    `<template>` content was already covered by the scan this replaces and stays covered here,
    since the shared index records every start tag. Reading that index rather than keeping a
    second collection of the same attributes is what stops the gate and the strip from drifting
    apart again.

    Like every other egress lookup this reads the SHARED index, so a caller must already have
    consulted `_tag_attrs_failed(html)`: on a parse that blew up the index is partial, and an
    empty result here means "could not look", not "no handlers".
    """
    idx = _tag_attr_index(html or "")
    found, noscript_found = idx.found, idx.noscript_found
    handlers = []
    for source in (found, noscript_found):
        for tag, ads in source.items():
            for ad in ads:
                for attr in ad:
                    if _is_event_handler_attr(attr):
                        handlers.append({"tag": tag, "attr": attr})
    return handlers


def _tag_attrs_failed(html):
    """Whether the shared tag index could not be built, so every lookup on this document is
    incomplete and its consumers must fail CLOSED rather than read a partial answer as clean."""
    return _tag_attr_index(html or "").failed



def _parse_document(html):
    """A tolerant `_DocParser` pass over `html`.

    The shared entry point for helpers that accept EITHER an already-parsed document (the normal
    path - `validate()` parses once) or raw html (tests and callers holding only a string), so a
    parser-derived view of the document never needs a second, divergent notion of its structure."""
    text = html or ""
    p = _DocParser(text)
    try:
        p.parse_document(text)
    except Exception:
        pass
    return p
