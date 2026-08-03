"""Shared HTML parsing infrastructure for the commentable-html validator: the
single-pass `_DocParser`, region-marker detection, tag/script attribute helpers,
and the constants (regions, ids, regexes) every check builds on."""

import functools
import re
from html import unescape
from html.entities import html5 as _HTML5_ENTITIES
from html.parser import HTMLParser
from types import MappingProxyType

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
_JS_END_MARKER_COMMENT_RE = re.compile(
    r"<!--[ \t]*(?:\r?\n[ \t]*)?(?:=+[ \t]*)?"
    + re.escape(JS_END_MARKER_TEXT)
    + r"[ \t]*(?:=+[ \t]*)?(?:\r?\n[ \t]*)?-->")

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

    def start(self):
        return self._marker_start

    def end(self):
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
    for line in (html or "").splitlines(True):
        body = line[:-1] if line.endswith("\n") else line
        if body.endswith("\r"):
            body = body[:-1]
        m = inline.match(body)
        if m is None and state in ("html", "css"):
            m = bare.match(body)
        if m is not None:
            matches.append(_MarkerMatch(offset + m.start(1), offset + m.end(1)))
        state = _advance_comment_state(body, state)
        offset += len(line)
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
_RAW_TEXT_ELEMENTS = frozenset((
    "script", "style", "textarea", "title", "xmp", "iframe", "noembed", "noframes", "noscript",
    "plaintext",
))

# `<plaintext>` is the one raw-text element a browser NEVER leaves: everything after it, closing
# tag or not, is text to the end of the document. html.parser enters that mode only from 3.13, so
# it is switched on here too and its region is deliberately given no closer.
_PLAINTEXT = "plaintext"

# Only script and style stay raw text inside FOREIGN content; the rest are ordinary parsed
# elements there (an SVG `<title>` is not HTML's RCDATA `<title>`).
_FOREIGN_RAW_TEXT_ELEMENTS = frozenset(("script", "style"))

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


class _BrowserTagNames(HTMLParser):
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
    if not any(n == tag or n.split("\x00", 1)[0] == tag
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
        if value and "&" in value:
            value = _unescape_attr_value(value)
        out.append((_ascii_lower(name), value))
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


class _BrowserStartTag(_BrowserTagNames):
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

    SCOPE: attribute values only. An oversized reference in TEXT is decoded by the host's
    `goahead()` (`convert_charrefs=True`) and still fails the parse closed, as it always has.
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
        before 3.13, and `noscript` on no version);
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
    """

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self._starts = _line_starts(html)
        self._final = False   # the whole document has been handed to feed()
        self._ns = []         # [(tag, namespace, is_integration_point)], parallel to the stack
        self._comment_raw = None      # source of the REAL comment being handled (see below)

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
        # handle_starttag on 3.13 for its RCDATA table): inside FOREIGN content only script and
        # style are raw text, so an SVG `<title>` must be parsed, not swallowed as text.
        if self._ns:
            tag, ns, _integration = self._ns[-1]
            if (tag == elem.lower() and ns != "html"
                    and elem.lower() not in _FOREIGN_RAW_TEXT_ELEMENTS):
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
        k = super().parse_endtag(i)
        if k >= 0 or not self._final:
            return k
        if _TAG_NAME_START_RE.match(rawdata, i + 2):
            return len(rawdata)         # EOF inside a real end tag: the tag is discarded
        if i + 2 >= len(rawdata):
            self.handle_data(rawdata[i:])       # a bare `</` at EOF is TEXT
            return len(rawdata)
        self.handle_comment(rawdata[i + 2:])    # `</` + junk opens a BOGUS COMMENT
        return len(rawdata)

    def parse_starttag(self, i):
        return self._drop_if_truncated(super().parse_starttag(i))

    def _drop_if_truncated(self, k):
        """EOF inside a TAG discards the tag, as a browser does (the HTML5 eof-in-tag error).

        The host signals "incomplete" with -1 and then resolves it its own way at end of input:
        before 3.12.11 / 3.13.5 the unfinished tag's SOURCE is handed to handle_data (so
        `<p>hi<div class="x` leaves `hi<div class="x` as prose, and inside raw text it lands in
        the element body), while a fixed host drops it. Resolve it here instead of inheriting
        whichever the host does.
        """
        if k < 0 and self._final:
            return len(self.rawdata)
        return k

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
        handler(self.rawdata[start:])
        return len(self.rawdata)

    def _enter_raw_text(self, tag, ns):
        """Switch a raw-text / RCDATA element's CONTENT to text, as a browser does. Called by
        the subclass AFTER the element is pushed, so the foreign carve-out can see it."""
        raw = _RAW_TEXT_ELEMENTS if ns == "html" else _FOREIGN_RAW_TEXT_ELEMENTS
        if tag in raw:
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
        self._ns.append((tag, ns, self._is_integration_point(tag, ns, ad)))

    def _truncate_stacks(self, depth):
        """Truncate every parallel element stack to `depth`. Subclasses extend this with their
        own stacks so no truncation path can leave the namespace view out of step."""
        del self._ns[depth:]

    def _before_truncate(self, depth):
        """Hook: the elements from `depth` up are about to be popped WITHOUT their own end tag."""

    def _implicit_close(self, tag):
        # HTML5 "close a p element": a block-level start tag closes an open <p> even through
        # intervening inline elements (a browser pops the <p> and everything under it), and a
        # new <li> closes an open <li>. Both tolerant parsers apply it, so a `<canvas>` whose
        # only cm-skip ancestor is such a <p> is not falsely protected and a `<pre>` a browser
        # puts inside a `figure.cmh-kql` is not judged outside it.
        if tag in P_CLOSERS:
            self._close_scoped("p", _P_CLOSE_BOUNDARY)
        if tag == "li":
            self._close_scoped("li", _LI_CLOSE_BOUNDARY)

    def _close_scoped(self, target, boundary):
        for i in range(len(self._ns) - 1, -1, -1):
            t, ns, _integration = self._ns[i]
            if ns != "html":
                if t in _FOREIGN_SCOPE_BOUNDARY:
                    return  # an integration point: the target is not in scope across it
                continue
            if t == target:
                self._before_truncate(i)
                self._truncate_stacks(i)
                return
            if t in boundary:
                return  # target is not in scope; do not close it


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
        # Every `on*` attribute in the document, template content INCLUDED, as (tag, attr). The
        # offline strip removes all of them, so the gate needs its own view to agree; the test is
        # the exporter's literal `^on` one, which also catches `once` - matching it exactly is the
        # point, since a validator that disagreed would reject the file the exporter just produced.
        self.event_handler_attrs = []
        self.has_comment_root = False
        self.js_end_marker_pos = None
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
        self.icon_links = []     # [{"rel": str, "href": str}] for every head <link rel~="icon">
        self._head_ended = False # True once the head is over (a <body>/</head>/first flow element)
        self.comment_root_attrs = None   # attrs dict of the id=commentRoot element
        self.body_attrs = None           # attrs dict of the REAL <body> start tag (first one)
        self.mermaid_blocks = []         # [{"cm_skip": bool, "has_svg": bool}] for pre/div.mermaid
        self.cm_skip_code_blocks = []    # [{"kind": "<pre>"|"<pre><code>"}] for direct cm-skip misuse
        self._mermaid_stack = []         # parallel to self.stack: current mermaid block index, or None
        self._cur_script = None   # (pos, attrs_dict) while inside a <script>
        self._cur_style = None    # (pos, attrs_dict) while inside a <style>
        self._cur_tpl_raw = None  # (tag, attrs_dict, [body parts]) while inside a TEMPLATE-parked
                                  # <script>/<style>; kept apart from the two above so template
                                  # content never leaks into a check that must ignore it.
        self._cur_body = []
        self.commentroot_prose = []  # #commentRoot text NOT inside <a> or a cm-skip element
        self._cr_depth = None        # stack depth at which #commentRoot was entered
        self._cr_closed = False      # True once #commentRoot (or an ancestor) has closed
        self._in_content_region = False
        self.headings = []           # [{"id": str|None, "text": str, "top_level": bool}] in #commentRoot
        self._cur_heading = None     # (tag, id, [parts], top_level) while capturing a heading's text
        self._cur_heading_depth = None   # stack depth of that heading, so an ancestor's close ends it
        self.has_top_level_lede = False  # a direct child of #commentRoot carries class cmh-lede
        self._lede_depth = None      # stack depth of the current top-level cmh-lede (for title h1)
        self._figure_chart = []      # stack of bool: is each open <figure> a chart figure
        self.has_offline_chart = False

    def _skip_ancestor(self):
        return any(skip for (_t, skip) in self.stack)

    def _in_canvas(self):
        return any(t == "canvas" for (t, _s) in self.stack)

    def _in_template(self):
        # A <template>'s contents live in an inert DocumentFragment: they are not
        # active DOM (getElementById does not see them, scripts do not run), so
        # ids / canvases / scripts inside a template must not be counted.
        return any(t == "template" for (t, _s) in self.stack)

    def _in_comment_root(self):
        return self._cr_depth is not None and not self._cr_closed and len(self.stack) > self._cr_depth

    def _in_commentable_content(self):
        return self._in_content_region and self._in_comment_root()

    def _note_ready_token(self, text):
        """Record the NonShareable bootstrap watchdog token, but ONLY from the body of an
        executable <script> belonging to the LAYER - outside the authored CONTENT region (and, by
        construction of `_cur_script`, outside an inert <template>). The watchdog IS such a script,
        so authored prose, a reviewer note in the embedded-comments JSON, or a template that merely
        contains the token must not stand in for it."""
        if self.layer_ready_token or self._cur_script is None:
            return
        if not _is_executable_js(self._cur_script[1]):
            return
        if READY_TOKEN in (text or "") and not self._in_commentable_content():
            self.layer_ready_token = True

    def _flush_template_raw(self):
        """Record a template-parked <script>/<style> body in its own view and clear the state."""
        if self._cur_tpl_raw is None:
            return
        ttag, tad, parts, _depth = self._cur_tpl_raw
        sink = self.template_scripts if ttag == "script" else self.template_styles
        sink.append({"pos": None, "attrs": tad, "body": "".join(parts)})
        self._cur_tpl_raw = None

    def _truncate_stacks(self, depth):
        # Every truncation path - an end tag, an implicit </p>/</li> close, a foreign-content
        # breakout - runs through here, so the parallel views can never fall out of step.
        # A template-parked raw-text element can never outlive the <template> that holds it: an
        # unterminated one would otherwise keep collecting, and the next parked block's body would
        # be concatenated onto it into a body no browser would ever see.
        if self._cur_tpl_raw is not None and depth <= self._cur_tpl_raw[3]:
            self._flush_template_raw()
        for (t, _s) in self.stack[depth:]:
            if t == "figure" and self._figure_chart:
                self._figure_chart.pop()
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
        del self._mermaid_stack[depth:]

    def _record(self, tag, ad, own_skip):
        if self._in_template():
            if "style" in ad:
                self.template_inline_styles.append({"tag": tag, "value": ad.get("style", "")})
            return  # inert template content
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
                                     "in_chart_figure": any(self._figure_chart)})
        if tag == "a":
            # SVG-namespaced <a> (tagName "a", not "A") is never stamped by the runtime, so exclude
            # it. But an <a> inside an SVG <foreignObject> is at an HTML integration point (tagName
            # "A") and IS stamped - detect the nearest svg/foreignObject ancestor, not any svg.
            in_svg = False
            for (t, _s) in reversed(self.stack):
                if t == "svg":
                    in_svg = True
                    break
                if t == "foreignobject":
                    break
            self.anchors.append({"href": ad.get("href"), "target": ad.get("target"),
                                 "skip": self._skip_ancestor() or own_skip,
                                 "in_svg": in_svg,
                                 "in_root": self._in_comment_root()})
        if "data-cm-offline-chart" in ad:
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
              and any(t == "pre" for (t, _s) in self.stack)):
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

    def handle_starttag(self, tag, attrs):
        tag = self._browser_tag(tag)
        ad = self._attrs_dict(tag, attrs)
        ns = self._child_namespace(tag, ad)
        if ns == "html":
            self._implicit_close(tag)
            # HTML5's h1-h6 start tag POPS an open heading that is the current node, so
            # `<h2 id="a">A<h2 id="b">B` is two headings: without this the first one ran on and
            # swallowed the second's text, and the second's id was never collected at all.
            if (tag in _HEADING_TAGS and self._cur_heading is not None
                    and self._cur_heading_depth == len(self.stack) - 1):
                self._truncate_stacks(self._cur_heading_depth)
        own_skip = "cm-skip" in set((ad.get("class") or "").split())
        for _attr in ad:
            if _attr[:2].lower() == "on":
                self.event_handler_attrs.append({"tag": tag, "attr": _attr})
        before_mermaid = len(self.mermaid_blocks)
        self._record(tag, ad, own_skip)
        if tag == "svg" and self._mermaid_stack:
            idx = self._mermaid_stack[-1]
            if idx is not None:
                self.mermaid_blocks[idx]["has_svg"] = True
        if tag == "script" and not self._in_template():
            self._cur_script = (self._off(), ad)
            self._cur_body = []
        if tag == "style" and not self._in_template():
            self._cur_style = (self._off(), ad)
            self._cur_body = []
        if tag in ("script", "style") and self._in_template() and self._cur_tpl_raw is None:
            # The stack DEPTH is carried so the state can never outlive its template: html.parser
            # keeps a raw-text element open to EOF, which matches a browser, but if any future path
            # ever left one open past `</template>` the next parked block's body would silently be
            # concatenated onto it and the offline check would read a body no browser would see.
            self._cur_tpl_raw = (tag, ad, [], len(self.stack))
        if (tag in _HEADING_TAGS and self._cur_heading is None and self._cr_depth is not None
                and not self._cr_closed and len(self.stack) > self._cr_depth and not own_skip
                and not self._skip_ancestor() and not self._in_template()):
            top_level = (len(self.stack) == self._cr_depth + 1)
            in_lede = self._lede_depth is not None and len(self.stack) > self._lede_depth
            self._cur_heading = (tag, ad.get("id"), [], top_level, in_lede)
            self._cur_heading_depth = len(self.stack)
        # A VOID element has no content and no end tag, so it is never pushed. (A foreign
        # element is never void: `<svg><rect/>` is self-closing markup, handled below.)
        if tag not in VOID or ns != "html":
            self.stack.append((tag, own_skip))
            self._push_ns(tag, ns, ad)
            current_mermaid = self._mermaid_stack[-1] if self._mermaid_stack else None
            if len(self.mermaid_blocks) > before_mermaid:
                current_mermaid = len(self.mermaid_blocks) - 1
            self._mermaid_stack.append(current_mermaid)
            if tag == "figure":
                self._figure_chart.append("chart" in set((ad.get("class") or "").split()))
        else:
            self._close_zero_width()
        self._enter_raw_text(tag, ns)

    def _close_zero_width(self):
        """An element that is never PUSHED (a void tag, a self-closed foreign one) has no
        content, so any depth-keyed state `_record` just opened at this depth ends immediately.
        Without this a `<svg id="commentRoot"/>` or `<img id="commentRoot">` would leave
        `_in_comment_root()` true for every later sibling, and CONTENT markers a browser puts
        OUTSIDE the empty root would be read as inside it."""
        self._truncate_stacks(len(self.stack))

    def handle_startendtag(self, tag, attrs):
        # HTML5: a trailing slash on a NON-void HTML tag is ignored by browsers, which treat it
        # as an open start tag needing an explicit end tag. Delegate so the element stack and
        # figure tracking stay in sync with the DOM (a void tag then simply is not pushed, but
        # still implicitly closes an open <p>). A self-closed FOREIGN element really is closed
        # at once, so it is RECORDED but never pushed - `<svg><rect id="x"/></svg>` is still an
        # element with an id, and a bare `<svg/>` must not be left open (a stale foreign current
        # node would make a following `<![CDATA[` hide live markup).
        tag = self._browser_tag(tag)
        ad = self._attrs_dict(tag, attrs)
        ns = self._child_namespace(tag, ad)
        if self._foreign_self_closes(ns):
            if tag == "svg" and self._mermaid_stack:
                idx = self._mermaid_stack[-1]
                if idx is not None:
                    self.mermaid_blocks[idx]["has_svg"] = True
            self._record(tag, ad, "cm-skip" in set((ad.get("class") or "").split()))
            self._close_zero_width()
            return
        self.handle_starttag(tag, attrs)

    def handle_data(self, data):
        self._note_ready_token(data)
        # A template-parked <script>/<style> body is collected ALONGSIDE the ordinary flow (never
        # instead of it), so adding this view cannot change what any existing check sees.
        if self._cur_tpl_raw is not None:
            self._cur_tpl_raw[2].append(data)
        # Capture the raw source text of the current mermaid block (entities are already
        # decoded because convert_charrefs=True), so the mermaid syntax checker can read it.
        # Only meaningful before the diagram renders to <svg>; a rendered block's has_svg
        # flag lets the checker skip it.
        if self._mermaid_stack and self._mermaid_stack[-1] is not None:
            self.mermaid_blocks[self._mermaid_stack[-1]].setdefault("src_parts", []).append(data)
        if self._cur_script is not None:
            self._cur_body.append(data)
            return
        if self._cur_style is not None:
            self._cur_body.append(data)
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
                and not any(t == "a" for (t, _s) in self.stack)):
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
            self.headings.append({"tag": self._cur_heading[0],
                                  "id": self._cur_heading[1], "text": text,
                                  "top_level": self._cur_heading[3],
                                  "in_lede": self._cur_heading[4]})
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
        for cur, sink in ((self._cur_script, self.scripts), (self._cur_style, self.styles)):
            if cur is not None:
                pos, ad = cur
                sink.append({"pos": pos, "attrs": ad, "body": "".join(self._cur_body)})
        self._cur_script = None
        self._cur_style = None
        self._cur_body = []
        self._flush_template_raw()
        self._flush_heading()

    def handle_endtag(self, tag):
        tag = self._browser_tag(tag)
        if tag == "head":
            self._head_ended = True
        if tag == "script" and self._cur_script is not None:
            pos, ad = self._cur_script
            self.scripts.append({"pos": pos, "attrs": ad, "body": "".join(self._cur_body)})
            self._cur_script = None
            self._cur_body = []
        if tag == "style" and self._cur_style is not None:
            pos, ad = self._cur_style
            self.styles.append({"pos": pos, "attrs": ad, "body": "".join(self._cur_body)})
            self._cur_style = None
            self._cur_body = []
        if self._cur_tpl_raw is not None and tag == self._cur_tpl_raw[0]:
            self._flush_template_raw()
        if self._cur_heading is not None and tag == self._cur_heading[0]:
            self._flush_heading()
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                self._truncate_stacks(i)
                return

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
                and _JS_END_MARKER_COMMENT_RE.fullmatch(raw)):
            self.js_end_marker_pos = self._off()
        if not self._in_template():
            if raw == CONTENT_BEGIN and self._in_comment_root():
                self._in_content_region = True
                self.content_region_opened = True
            elif raw == CONTENT_END:
                if self._in_content_region:
                    self.content_region_closed = True
                self._in_content_region = False


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
        self.pres = []
        self.unclosed = False

    # -- element tracking -------------------------------------------------- #

    def _open_pre(self):
        for entry in reversed(self._stack):
            if entry[0] == "pre":
                return entry[1]
        return None

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

    def handle_starttag(self, tag, attrs):
        tag = self._browser_tag(tag)
        ad = self._attrs_dict(tag, attrs)
        ns = self._child_namespace(tag, ad)
        if ns == "html":
            self._implicit_close(tag)
        rec = None
        if tag == "pre" and ns == "html":
            rec = {"attrs": ad, "start": self._off(), "inner_start": self._start_tag_end(),
                   "inner": None, "codes": [],
                   "in_kql_figure": any(e[2] for e in self._stack)}
            self.pres.append(rec)
        elif tag == "code" and ns == "html":
            owner = self._open_pre()
            if owner is not None:
                rec = {"attrs": ad, "start": self._off(),
                       "inner_start": self._start_tag_end(), "inner": None}
                owner["codes"].append(rec)
        # A VOID element has no content and no end tag, so it never owns a code block and never
        # needs to be popped. Keeping voids off the stack matches _DocParser and keeps a
        # void-heavy document from growing the stack (and every unmatched end tag's scan of it).
        # (A foreign element is never void: `<svg><rect/>` is self-closing markup, handled below.)
        if tag not in VOID or ns != "html":
            self._stack.append((tag, rec,
                                tag == "figure" and ns == "html"
                                and parsed_attrs_have_class(ad, "cmh-kql")))
            self._push_ns(tag, ns, ad)
        self._enter_raw_text(tag, ns)

    def handle_startendtag(self, tag, attrs):
        # HTML5: a trailing slash on a NON-void HTML tag is ignored, so `<pre/>` opens an element
        # that still needs `</pre>` and `<textarea/>` still opens raw text; a void tag is not
        # pushed but still implicitly closes an open <p> (`<hr/>`), exactly as in _DocParser.
        # In FOREIGN content the slash really does close the element, so `<svg><rect/>` - and a
        # bare `<svg/>` - leave nothing open.
        tag = self._browser_tag(tag)
        ad = self._attrs_dict(tag, attrs)
        if self._foreign_self_closes(self._child_namespace(tag, ad)):
            return  # a self-closed foreign element: opened and closed at once
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        tag = self._browser_tag(tag)
        end = self._off()
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] != tag:
                continue
            self._mark_unclosed(i + 1)   # implicitly closed: they never got their own closer
            own = self._stack[i][1]
            if own is not None:
                own["inner"] = (own["inner_start"], end)
            self._truncate_stacks(i)
            return
        # An end tag with no open element is ignored, exactly as a browser ignores it.

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
        self._raw = None          # (tag, body_start) while inside a raw-text element
        self._length = len(html)
        self.raw_spans = []

    def handle_starttag(self, tag, attrs):
        super().handle_starttag(tag, attrs)
        if self._raw is None and self.cdata_elem is not None:
            self._raw = (self.cdata_elem, self._start_tag_end())

    def handle_endtag(self, tag):
        if self._raw is not None and self._browser_tag(tag) == self._raw[0]:
            self.raw_spans.append((self._raw[1], self._off()))
            self._raw = None
        super().handle_endtag(tag)

    def close(self):
        super().close()
        if self._raw is not None:
            # A browser runs an unclosed raw-text element to the end of the document.
            self.raw_spans.append((self._raw[1], self._length))
            self._raw = None


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
    p = _RawTextSpanParser(html)
    try:
        p.parse_document(html)
    except Exception:
        return html
    out = list(html)
    for start, end in p.raw_spans:
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
        self.found = {}
        self.noscript_found = {}
        self.failed = False
        self.eof_in_tag = False

    def _truncate_stacks(self, depth):
        super()._truncate_stacks(depth)
        del self._stack[depth:]

    def _record(self, tag, ad):
        self.found.setdefault(tag, []).append(ad)

    def handle_data(self, data):
        if self._noscript is not None:
            self._noscript.append(data)

    def _enter_raw_text(self, tag, ns):
        if tag == "noscript" and self._fallback:
            return   # scripting is off in this pass, so <noscript> holds markup, not text
        super()._enter_raw_text(tag, ns)

    def _drop_if_truncated(self, k):
        if k < 0 and self._final:
            self.eof_in_tag = True
        return super()._drop_if_truncated(k)

    def _flush_noscript(self):
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
        for source in (inner.found, inner.noscript_found):
            for tag, ads in source.items():
                self.noscript_found.setdefault(tag, []).extend(ads)

    def handle_starttag(self, tag, attrs):
        tag = self._browser_tag(tag)
        ad = self._attrs_dict(tag, attrs)
        ns = self._child_namespace(tag, ad)
        if ns == "html":
            self._implicit_close(tag)
        self._record(tag, ad)
        # A VOID element has no content and no end tag, so it is never pushed. (A foreign
        # element is never void: `<svg><rect/>` is self-closing markup, handled below.)
        if tag not in VOID or ns != "html":
            self._stack.append(tag)
            self._push_ns(tag, ns, ad)
        self._enter_raw_text(tag, ns)
        if tag == "noscript" and self.cdata_elem == "noscript":
            self._noscript = []

    def handle_startendtag(self, tag, attrs):
        # HTML5 ignores a trailing slash on a non-void HTML tag, so it opens an element; a
        # self-closed FOREIGN element really is closed at once - still an element with
        # attributes, but never left open.
        tag = self._browser_tag(tag)
        ad = self._attrs_dict(tag, attrs)
        if self._foreign_self_closes(self._child_namespace(tag, ad)):
            self._record(tag, ad)
            return
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        tag = self._browser_tag(tag)
        if tag == "noscript" and self._noscript is not None:
            self._flush_noscript()
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i] == tag:
                self._truncate_stacks(i)
                return
        # An end tag with no open element is ignored, exactly as a browser ignores it.

    def close(self):
        # The base flushes the tail of an UNCLOSED raw-text element first, so a `<noscript>` that
        # never closes still contributes its fallback markup (a browser runs it to EOF too).
        super().close()
        if self._noscript is not None:
            self._flush_noscript()


@functools.lru_cache(maxsize=32)
def _tag_attr_index(html):
    """`(found, noscript_found, failed)` for `html`: every start tag mapped to its
    browser-decoded attribute dicts, the `<noscript>` fallback markup indexed separately, and
    whether the parse blew up.

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
    failed = failed or (p is not None and p.failed)
    return (_freeze_tag_attrs(found), _freeze_tag_attrs(noscript_found), failed)

def _freeze_tag_attrs(found):
    return {tag: tuple(MappingProxyType(ad) for ad in ads) for tag, ads in found.items()}


def _find_tag_attrs(html, tag):
    """The attribute dict of every occurrence of `tag`, as a browser with scripting ENABLED sees
    the document - the view a PRESENCE question must ask ("does this document declare X?")."""
    found, _noscript_found, _failed = _tag_attr_index(html or "")
    return [dict(ad) for ad in found.get(_ascii_lower(tag), ())]


def _find_tag_attrs_egress(html, tag):
    """The same, PLUS the `<noscript>` fallback markup a scripting-DISABLED browser parses and
    loads - the view an EGRESS question must ask ("does this document load anything over the
    network?"). Deliberately a separate function rather than a flag on the one above: a missed
    argument would be a silent hole in one direction and a fail-open policy check in the other."""
    found, noscript_found, _failed = _tag_attr_index(html or "")
    key = _ascii_lower(tag)
    return ([dict(ad) for ad in found.get(key, ())]
            + [dict(ad) for ad in noscript_found.get(key, ())])


def _tag_attrs_failed(html):
    """Whether the shared tag index could not be built, so every lookup on this document is
    incomplete and its consumers must fail CLOSED rather than read a partial answer as clean."""
    return _tag_attr_index(html or "")[2]



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
