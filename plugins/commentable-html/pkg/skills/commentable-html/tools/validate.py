#!/usr/bin/env python3
"""Validate a commentable-html document against the skill's invariants.

This is the single, unified checker. It always validates the commentable LAYER
(region markers, required/forbidden ids, the two JSON blocks, theme variables,
mermaid cm-skip, ...) and, when the document embeds Chart.js charts, it also
checks the chart-embedding invariants that used to live in validate_charts.py.
Not all chart checks are enforced equally: a missing/broken loader, wrong chart
init ordering, and invalid chart-data JSON are hard ERRORS, while a non-pinned or
un-SRI loader, missing canvas accessibility (role/aria-label), and a missing
`typeof Chart` network-failure guard are advisory WARNINGS.

Both halves share ONE tolerant HTML parse (see _DocParser), so script tags are
read via the parser's own attribute handling rather than a fragile regex: a `>`
inside a quoted attribute, a loader or `new Chart(` inside an HTML comment, and
`data-src` / `data-type` masquerading as `src` / `type` are all handled
correctly.

Usage (run from the skill root):
    python tools/validate.py path/to/file.html [more.html ...]
    python tools/validate.py --charts-only file.html      # only the Chart.js checks
    python tools/validate.py --layer-only  file.html      # only the layer checks

Exit code 0 when every file passes (warnings allowed), 1 when any file has
errors, 2 on a usage problem. Pure standard library, no third-party packages.

Note: the layer checks expect human-readable (non-minified) HTML - the region
markers must sit on their own lines, which is how the skill emits them.
"""

import json
import os
import re
import sys
import traceback
from collections import Counter
from html.parser import HTMLParser
from urllib.parse import urlparse
from urllib.request import url2pathname

# --------------------------------------------------------------------------- #
# Layer contract
# --------------------------------------------------------------------------- #

REGIONS = ["CSS", "HANDLED IDS", "EMBEDDED COMMENTS", "COMMENT UI", "JS"]
LAYER_DESCRIPTOR_ID = "commentableHtmlLayer"
CONTENT_BEGIN = "<!-- BEGIN: commentable-html - CONTENT (agent edits ONLY between these markers) -->"
CONTENT_END = "<!-- END: commentable-html - CONTENT -->"

# Structural ids the layer's JS wires up. Missing ones make the layer throw or
# silently no-op, so their absence is an error. (handledCommentIds and
# embeddedComments are <script> blocks, validated separately below. commentRoot
# is checked by its own dedicated-block error, not listed here to avoid a
# duplicate diagnostic.)
REQUIRED_IDS = [
    "sidebar", "commentList", "contextMenu", "mermaidAddBtn", "diffAddBtn", "imageAddBtn", "hlBubble", "toast",
    "toolbarCount", "sidebarCount",
    "btnToggleSidebar", "btnCopyAll", "btnCopyAllTop", "btnClearAll",
    "btnCloseSidebar", "menuComment",
    "btnToolbarMenu", "toolbarMenu",
    "btnSaveHtml", "btnSaveHtmlTop", "btnSavePlain", "btnSavePlainTop",
    "btnExportOffline", "btnExportOfflineTop",
    "headingAddBtn", "widgetAddBtn", "menuDocComment",
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


def _attrs_have_class(attrs, class_name):
    wanted = class_name.casefold()
    for m in _CLASS_ATTR_RE.finditer(attrs):
        value = next((g for g in m.groups() if g is not None), "")
        if any(part.casefold() == wanted for part in value.split()):
            return True
    return False

# --------------------------------------------------------------------------- #
# Retrofit / demo-leftover contract
# --------------------------------------------------------------------------- #
# dist/PORTABLE.html ships a working DEMO: its content root carries these placeholder
# values, and its top-of-file documentation comment contains ONE example
# "<main id=commentRoot data-comment-key=my-doc>". A finished consumer
# document must (a) give its content root a unique data-comment-key - not the
# demo one - and (b) never leave real content commented out. The two checks
# below are written so the pristine dist/PORTABLE.html (demo key + demo <title>, and
# only the "my-doc" example commented) still passes with zero findings, while
# a botched retrofit (a script that replaced the WRONG "<main id=commentRoot>"
# and buried the consumer's real content in the top comment, leaving the demo as
# the live root) is caught.
DEMO_TITLE = "Commentable HTML - Demo"
DEMO_COMMENT_KEY = "commentable-html-demo"
DEMO_NONPORTABLE_TITLE = "Commentable HTML - NonPortable Demo"
DEMO_NONPORTABLE_COMMENT_KEY = "commentable-html-nonportable-demo"
# Each pristine demo content-root key maps to the <title> its generated template
# keeps. A customized retrofit that leaves the demo root in place (changed title,
# same demo key) is flagged for both the inline and the nonportable template.
DEMO_KEYS = {DEMO_COMMENT_KEY: DEMO_TITLE, DEMO_NONPORTABLE_COMMENT_KEY: DEMO_NONPORTABLE_TITLE}
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

# --------------------------------------------------------------------------- #
# Chart contract
# --------------------------------------------------------------------------- #

# The real region marker is an HTML comment, not bare text in prose.
JS_END_MARKER_TEXT = "END: commentable-html - JS"
# JSON <script> ids owned by the commentable layer, not chart data.
LAYER_JSON_IDS = {"handledCommentIds", "embeddedComments", LAYER_DESCRIPTOR_ID}
# HTML void elements never get pushed on the stack.
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr"}
_HEADING_TAGS = frozenset(("h1", "h2", "h3", "h4", "h5", "h6"))
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
# A Chart.js loader filename, as a whole path segment: chart(.umd)?(.min)?.js,
# optionally followed by a query string / fragment; OR the bare pinned form
# chart.js@X.Y.Z that jsdelivr auto-resolves. Excludes flowchart.min.js,
# barchart.js, chart-utils.js, org-chart.js, etc.
CHARTJS_SRC_RE = re.compile(
    r"(?:^|/)chart(?:\.umd)?(?:\.min)?\.js(?:$|[?#])"
    r"|(?:^|/)chart\.js@\d+\.\d+\.\d+(?:$|[/?#])",
    re.IGNORECASE)
# A real network-failure guard (typeof Chart ==/===/!=/!== "undefined", optionally
# parenthesised as typeof(Chart)), not the bare substring "typeof Chart".
GUARD_RE = re.compile(r"typeof\s*\(?\s*Chart\s*\)?\s*[!=]={1,2}\s*(['\"])undefined\1", re.IGNORECASE)
# Executable chart init: `new Chart(` or a global-qualified `new window.Chart(` /
# `new globalThis.Chart(` / `new self.Chart(`.
NEW_CHART_RE = re.compile(r"\bnew\s+(?:Chart|(?:window|globalThis|self)\.Chart)\s*\(")
# An inline canvas draw: `<ctx>.getContext(...)` (2D or webgl). Lets a plain drawn
# canvas count as a renderer even without Chart.js.
CANVAS_RENDER_RE = re.compile(r"\.getContext\s*\(")


# --------------------------------------------------------------------------- #
# Layer helpers (region markers). Element / id / attribute / script-body checks
# all read from the shared _DocParser (below), so a `>` inside a quoted attribute
# or an `id="..."` sitting inside another attribute's value never fools them.
# --------------------------------------------------------------------------- #

def _begin_re(region):
    return re.compile(r"(?m)^[ \t]*BEGIN: commentable-html - " + re.escape(region) + r"[ \t]*$")


def _end_re(region):
    # Banner form ("   END: ... CSS") or inline HTML comment ("<!-- END: ... JS -->").
    return re.compile(
        r"(?m)^[ \t]*(?:<!--[ \t]*)?END: commentable-html - "
        + re.escape(region) + r"(?:[ \t]*-->)?[ \t]*$"
    )


# --------------------------------------------------------------------------- #
# Shared tolerant parse (used by the layer and chart checks)
# --------------------------------------------------------------------------- #

def _line_starts(html):
    starts, pos = [0], html.find("\n")
    while pos != -1:
        starts.append(pos + 1)
        pos = html.find("\n", pos + 1)
    return starts


class _DocParser(HTMLParser):
    """One tolerant pass over the document. Collects, for the chart checks:

      - canvases  [{"skip": bool, "attrs": {..}}]
      - figcaptions [{"skip": bool, "in_canvas": bool}]
      - scripts   [{"pos": int, "attrs": {..}, "body": str}]  (executable + json)
      - has_comment_root: a real element with id=commentRoot exists
      - js_end_marker_pos: offset of the real "END: ... JS" comment, or None

    cm-skip ancestry, the HTML5 implicit close of <p>/<li> (so an unclosed
    cm-skip <p> does not leak), and <script>/<style> CDATA + comment opacity all
    fall out of the parser, so a <canvas>/loader/new Chart in a string or comment
    is not counted, and a `>` inside a quoted attribute does not mis-slice a tag.
    """

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self._starts = _line_starts(html)
        self.stack = []          # list of (tag, is_cm_skip)
        self.canvases = []
        self.figcaptions = []
        self.scripts = []
        self.styles = []
        self.has_comment_root = False
        self.js_end_marker_pos = None
        self.all_ids = []        # every element id value, in document order
        self.comment_root_attrs = None   # attrs dict of the id=commentRoot element
        self.mermaid_blocks = []         # [{"cm_skip": bool, "has_svg": bool}] for pre/div.mermaid
        self._mermaid_stack = []         # parallel to self.stack: current mermaid block index, or None
        self._cur_script = None   # (pos, attrs_dict) while inside a <script>
        self._cur_style = None    # (pos, attrs_dict) while inside a <style>
        self._cur_body = []
        self.commentroot_prose = []  # #commentRoot text NOT inside <a> or a cm-skip element
        self._cr_depth = None        # stack depth at which #commentRoot was entered
        self._cr_closed = False      # True once #commentRoot (or an ancestor) has closed
        self.headings = []           # [{"id": str|None, "text": str}] for headings in #commentRoot
        self._cur_heading = None     # (tag, id, [parts]) while capturing a heading's text
        self._figure_chart = []      # stack of bool: is each open <figure> a chart figure
        self.has_offline_chart = False

    def _off(self):
        ln, col = self.getpos()
        return self._starts[ln - 1] + col

    @staticmethod
    def _attrs_dict(attrs):
        # HTML5 (and browsers) keep the FIRST occurrence of a duplicated attribute,
        # so `<main id="a" id="b">` is id="a". A dict comprehension would keep the
        # last; iterate and set-if-absent to match the browser.
        d = {}
        for k, v in attrs:
            kl = (k or "").lower()
            if kl not in d:
                d[kl] = v if v is not None else ""
        return d

    def _skip_ancestor(self):
        return any(skip for (_t, skip) in self.stack)

    def _in_canvas(self):
        return any(t == "canvas" for (t, _s) in self.stack)

    def _in_template(self):
        # A <template>'s contents live in an inert DocumentFragment: they are not
        # active DOM (getElementById does not see them, scripts do not run), so
        # ids / canvases / scripts inside a template must not be counted.
        return any(t == "template" for (t, _s) in self.stack)

    def _implicit_close(self, tag):
        # HTML5 "close a p element" / li handling: a block-level start tag closes an
        # open <p> even through intervening inline elements (a browser pops the <p>
        # and everything under it), and a new <li> closes an open <li>. Scan the
        # stack back to the target, stopping at a scope boundary it cannot cross, so
        # a canvas whose only cm-skip ancestor is such a <p> is not falsely protected.
        if tag in P_CLOSERS:
            self._close_element("p", _P_CLOSE_BOUNDARY)
        if tag == "li":
            self._close_element("li", _LI_CLOSE_BOUNDARY)

    def _close_element(self, target, boundary):
        idx = None
        for i in range(len(self.stack) - 1, -1, -1):
            t = self.stack[i][0]
            if t == target:
                idx = i
                break
            if t in boundary:
                return  # target is not in scope; do not close it
        if idx is not None:
            del self.stack[idx:]
            del self._mermaid_stack[idx:]

    def _record(self, tag, ad, own_skip):
        if self._in_template():
            return  # inert template content
        if tag == "canvas":
            self.canvases.append({"skip": self._skip_ancestor() or own_skip, "attrs": ad})
        elif tag == "figcaption":
            self.figcaptions.append({"skip": self._skip_ancestor() or own_skip,
                                     "in_canvas": self._in_canvas(),
                                     "in_chart_figure": any(self._figure_chart)})
        if "data-cm-offline-chart" in ad:
            self.has_offline_chart = True
        if tag in ("pre", "div") and "mermaid" in set((ad.get("class") or "").split()):
            self.mermaid_blocks.append({"cm_skip": own_skip, "has_svg": False})
        idv = ad.get("id")
        if idv:
            self.all_ids.append(idv)
            if idv == "commentRoot":
                self.has_comment_root = True
                if self.comment_root_attrs is None:
                    self.comment_root_attrs = ad
                    self._cr_depth = len(self.stack)  # commentRoot is pushed at this index

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        self._implicit_close(tag)
        ad = self._attrs_dict(attrs)
        own_skip = "cm-skip" in set((ad.get("class") or "").split())
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
        if (tag in _HEADING_TAGS and self._cur_heading is None and self._cr_depth is not None
                and not self._cr_closed and len(self.stack) > self._cr_depth and not own_skip
                and not self._skip_ancestor() and not self._in_template()):
            self._cur_heading = (tag, ad.get("id"), [])
        if tag not in VOID:
            self.stack.append((tag, own_skip))
            current_mermaid = self._mermaid_stack[-1] if self._mermaid_stack else None
            if len(self.mermaid_blocks) > before_mermaid:
                current_mermaid = len(self.mermaid_blocks) - 1
            self._mermaid_stack.append(current_mermaid)
            if tag == "figure":
                self._figure_chart.append("chart" in set((ad.get("class") or "").split()))

    def handle_startendtag(self, tag, attrs):
        # HTML5: a trailing slash on a NON-void tag is ignored by browsers, which treat it
        # as an open start tag needing an explicit end tag. Delegate so the element stack
        # and figure tracking stay in sync with the DOM; only true void tags are terminal.
        if tag.lower() not in VOID:
            self.handle_starttag(tag, attrs)
            return
        tag = tag.lower()
        self._implicit_close(tag)
        ad = self._attrs_dict(attrs)
        own_skip = "cm-skip" in set((ad.get("class") or "").split())
        if tag == "svg" and self._mermaid_stack:
            idx = self._mermaid_stack[-1]
            if idx is not None:
                self.mermaid_blocks[idx]["has_svg"] = True
        self._record(tag, ad, own_skip)

    def handle_data(self, data):
        if self._cur_script is not None:
            self._cur_body.append(data)
            return
        if self._cur_style is not None:
            self._cur_body.append(data)
            return
        if self._cur_heading is not None:
            self._cur_heading[2].append(data)
            return  # heading text is captured separately, not treated as cross-ref prose
        # Prose inside #commentRoot but NOT inside a link or a cm-skip element. A cross
        # reference that IS a link never lands here, so only UNLINKED references remain.
        if (self._cr_depth is not None and not self._cr_closed and len(self.stack) > self._cr_depth
                and not self._skip_ancestor()
                and not any(t == "a" for (t, _s) in self.stack)):
            self.commentroot_prose.append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()
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
        if self._cur_heading is not None and tag == self._cur_heading[0]:
            text = re.sub(r"\s+", " ", "".join(self._cur_heading[2])).strip()
            if text:
                self.headings.append({"id": self._cur_heading[1], "text": text})
            self._cur_heading = None
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                removed_figures = sum(1 for (t, _s) in self.stack[i:] if t == "figure")
                for _ in range(removed_figures):
                    if self._figure_chart:
                        self._figure_chart.pop()
                # Closing #commentRoot (or an ancestor of it) ends the root subtree for
                # good, so headings/prose in a later sibling container are not collected.
                if self._cr_depth is not None and i <= self._cr_depth:
                    self._cr_closed = True
                del self.stack[i:]
                del self._mermaid_stack[i:]
                return

    def handle_comment(self, data):
        # Exact match, so a prose comment that merely mentions the marker text
        # ("<!-- note: END: commentable-html - JS is the marker -->") is ignored;
        # a marker inside an inert <template> is ignored too.
        if (self.js_end_marker_pos is None and not self._in_template()
                and data.strip() == JS_END_MARKER_TEXT):
            self.js_end_marker_pos = self._off()


def _is_json_attrs(ad):
    return (ad.get("type", "") or "").split(";")[0].strip().lower() == "application/json"


# Script types the browser executes natively as classic/module JavaScript. A
# loader or a `new Chart(` in any other type (application/json, importmap,
# text/plain, and transpiler-only text/babel / text/jsx which need a runtime the
# validator cannot assume) does not run, so it must not satisfy loader / init.
_JS_TYPES = {"", "text/javascript", "application/javascript", "text/ecmascript",
             "application/ecmascript", "module"}


def _is_executable_js(ad):
    return (ad.get("type", "") or "").split(";")[0].strip().lower() in _JS_TYPES


def _js_scan(body):
    """Single left-to-right pass over a script body that is string / template /
    comment aware, returning two length-preserving views:
      - guard_src: JS comments blanked, string literals KEPT (a real
        `typeof Chart === "undefined"` guard needs its "undefined" string).
      - init_src:  JS comments AND string / template literals blanked (a real
        `new Chart(` is executable code, never inside a string).
    Because it is one pass, a `//` or `/*` that lives INSIDE a string can never
    start a fake comment (the string is entered first), and a quote inside a
    comment can never open a fake string. Regex literals are not modeled (a rare,
    documented residual - see SKILL.md Design decisions)."""
    n = len(body)
    guard = list(body)   # comments -> space, strings kept
    init = list(body)    # comments AND strings -> space
    i, state = 0, None   # state: None | "'" | '"' | '`' | 'line' | 'block'
    while i < n:
        ch = body[i]
        nx = body[i + 1] if i + 1 < n else ""
        if state is None:
            if ch == "/" and nx == "/":
                guard[i] = guard[i + 1] = " "; init[i] = init[i + 1] = " "; state = "line"; i += 2; continue
            if ch == "/" and nx == "*":
                guard[i] = guard[i + 1] = " "; init[i] = init[i + 1] = " "; state = "block"; i += 2; continue
            if ch in ("'", '"', "`"):
                init[i] = " "; state = ch; i += 1; continue
            i += 1; continue
        if state == "line":
            if ch == "\n":
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
            init[i] = " "; state = None; i += 1; continue
        if ch != "\n":
            init[i] = " "
        i += 1; continue
    return "".join(guard), "".join(init)


# --------------------------------------------------------------------------- #
# Layer checks
# --------------------------------------------------------------------------- #

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


# --------------------------------------------------------------------------- #
# NonPortable mode: the layer's CSS/JS live in companion commentable-html.{css,js,assets.js}
# files referenced via <link>/<script src> instead of being inlined. Only CSS
# and JS leave the document; HANDLED IDS, EMBEDDED COMMENTS and COMMENT UI stay
# inline (document-owned state + controls). CSS and JS are marker-delimited
# companion references, so the same region descriptor works in both modes.
# --------------------------------------------------------------------------- #
NONPORTABLE_REGIONS = REGIONS


class _TagAttrParser(HTMLParser):
    """Collect the attribute dict of every occurrence of one tag using the tolerant
    HTMLParser, so a '>' inside a quoted value is handled correctly and a tag that
    only appears inside an HTML comment or a <script>/<style> body (which HTMLParser
    treats as CDATA) is NOT matched."""

    def __init__(self, want):
        super().__init__(convert_charrefs=True)
        self._want = want.lower()
        self.found = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != self._want:
            return
        d = {}
        for k, v in attrs:
            kl = (k or "").lower()
            if kl not in d:
                d[kl] = v if v is not None else ""
        self.found.append(d)


def _find_tag_attrs(html, tag):
    p = _TagAttrParser(tag)
    try:
        p.feed(html)
        p.close()
    except Exception:
        pass
    return p.found


# NonPortable companion references are detected by parsing real link/script/meta
# attributes with the tolerant HTMLParser (not a regex), so a '>' in a quoted
# value, an unquoted href/src, a reordered <meta content=.. name=..>, or a decoy
# tag inside a comment/script body is handled the same way as the rest of the
# validator.
def _ref_path(ref):
    """The path portion of a companion ref, without a ?query or #fragment cache-buster
    (e.g. 'commentable-html.js?v=1.7.0' -> 'commentable-html.js'), so suffix detection
    and the on-disk existence check ignore the cache-buster the browser strips too."""
    return re.split(r"[?#]", ref or "", maxsplit=1)[0]


def _file_url_to_path(ref):
    parsed = urlparse(ref or "")
    if parsed.scheme.lower() != "file":
        return None
    raw = ("//" + parsed.netloc + parsed.path) if parsed.netloc and parsed.netloc.lower() != "localhost" else parsed.path
    return os.path.abspath(url2pathname(raw))


def _nonportable_css_refs(html):
    return [_ref_path(a["href"]) for a in _find_tag_attrs(html, "link")
            if "commentable-html" in a.get("href", "").lower()
            and _ref_path(a.get("href", "")).lower().endswith(".css")]


def _nonportable_js_refs(html):
    return [_ref_path(a["src"]) for a in _find_tag_attrs(html, "script")
            if "commentable-html" in a.get("src", "").lower()
            and _ref_path(a.get("src", "")).lower().endswith(".js")]


def _nonportable_meta_versions(html):
    return [a.get("content", "") for a in _find_tag_attrs(html, "meta")
            if a.get("name", "").lower() == "commentable-html-version"]


def _is_nonportable(html):
    """NonPortable = the document references external commentable-html companion files."""
    return bool(_nonportable_css_refs(html) or _nonportable_js_refs(html))


def _layer_descriptor_data(parser):
    scripts = [s for s in parser.scripts if s["attrs"].get("id") == LAYER_DESCRIPTOR_ID]
    if not scripts:
        return None
    try:
        data = json.loads((scripts[0]["body"] or "").strip())
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _check_layer_descriptor(parser, nonportable, active_regions):
    errors = []
    scripts = [s for s in parser.scripts if s["attrs"].get("id") == LAYER_DESCRIPTOR_ID]
    if not scripts:
        return ['missing <script id="%s" type="application/json"> layer descriptor' % LAYER_DESCRIPTOR_ID]
    if len(scripts) > 1:
        errors.append('<script id="%s"> appears %d times (must be unique)' % (LAYER_DESCRIPTOR_ID, len(scripts)))
    script = scripts[0]
    if not _is_json_attrs(script["attrs"]):
        errors.append('the <script id="%s"> block must be type="application/json"' % LAYER_DESCRIPTOR_ID)
    try:
        data = json.loads((script["body"] or "").strip())
    except json.JSONDecodeError as exc:
        errors.append("%s is not valid JSON: %s" % (LAYER_DESCRIPTOR_ID, exc))
        return errors
    if not isinstance(data, dict):
        errors.append("%s must be a JSON object" % LAYER_DESCRIPTOR_ID)
        return errors
    version = data.get("version")
    if not isinstance(version, str) or not version.strip():
        errors.append('%s.version must be a non-empty string' % LAYER_DESCRIPTOR_ID)
    mode = data.get("mode")
    if nonportable:
        if mode != "nonportable":
            errors.append('%s.mode must be "nonportable" for this document' % LAYER_DESCRIPTOR_ID)
    else:
        if mode not in ("portable", "offline"):
            errors.append('%s.mode must be "portable" or "offline" for this document' % LAYER_DESCRIPTOR_ID)
        if parser.has_offline_chart and mode != "offline":
            errors.append('%s.mode must be "offline" when offline chart snapshots are present' % LAYER_DESCRIPTOR_ID)
    if data.get("regions") != active_regions:
        errors.append("%s.regions must list exactly the active region markers in order: %s"
                      % (LAYER_DESCRIPTOR_ID, ", ".join(active_regions)))
    return errors


_SECTION_DIR_RE = re.compile(
    r'\b(?:section|appendix|sub-?section|chapter)s?\s+(?:above|below)\b'
    r'|\b(?:above|below|previous|next|following|preceding|earlier|later|prior)\s+'
    r'(?:section|appendix|sub-?section|chapter)s?\b',
    re.IGNORECASE)


def check_section_reference_links(parser):
    """Warn when a section cross-reference in #commentRoot prose is NOT a link.

    Only UNLINKED text reaches parser.commentroot_prose (link text and cm-skip are
    excluded), so every hit is a plain-text cross reference that the content conventions
    say should be an in-page anchor. Detection is deterministic; the fix (wrapping it in
    an <a href="#section-id">) is left to the author/agent.
    """
    prose = re.sub(r"\s+", " ", "".join(parser.commentroot_prose)).strip()
    if not prose:
        return []
    hits = []
    for m in _SECTION_DIR_RE.finditer(prose):
        hits.append(m.group(0).strip())
    # Named references: "see <Heading>" / "refer to <Heading>" / "<Heading> section",
    # where <Heading> is an actual heading title in this document (so it is linkable).
    titles = sorted({h["text"] for h in parser.headings if h.get("text") and len(h["text"]) >= 3},
                    key=len, reverse=True)
    if len(parser.headings) >= 2:
        for title in titles:
            t = re.escape(title)
            named = re.compile(
                r'\b(?:see|refer(?:s|red)?\s+to)\s+(?:the\s+)?[\u2018\u2019\'"]?' + t + r'\b'
                r'|\b' + t + r'\s+section\b',
                re.IGNORECASE)
            m = named.search(prose)
            if m:
                hits.append(m.group(0).strip())
    if not hits:
        return []
    seen = []
    for h in hits:
        if h.lower() not in {s.lower() for s in seen}:
            seen.append(h)
    sample = "; ".join(seen[:5])
    more = "" if len(seen) <= 5 else (" (and %d more)" % (len(seen) - 5))
    return ['section cross-reference(s) in prose are not links: "%s"%s - wrap each in an '
            'in-page anchor (<a href="#section-id">...</a>) per the content conventions '
            '(give the target heading a stable id)' % (sample, more)]


def check_mermaid_renders(parser):
    """Warn when the document has mermaid diagrams that will NOT render on open.

    A doc with pre/div.mermaid blocks needs a loader script that imports mermaid AND
    triggers a render (m.run() or startOnLoad:true), and that loader must not be hidden
    behind a URL query-param gate. Deterministic detection; otherwise the diagrams
    silently stay as source text, which reads as "mermaid is broken".
    """
    if not parser.mermaid_blocks:
        return []
    if all(mb.get("has_svg") for mb in parser.mermaid_blocks):
        return []
    loader = None
    for s in parser.scripts:
        body = s.get("body") or ""
        if re.search(r"mermaid", body, re.I) and (
                "import(" in body or re.search(r"mermaid\.(?:esm|min)", body, re.I)
                or re.search(r"\bmermaid\.(?:initialize|run)\b", body)):
            loader = body
            break
    if loader is None:
        return ["the document has mermaid diagram(s) (pre/div.mermaid) but no mermaid loader "
                "script was found - the diagrams will not render (they stay as source text); "
                "add a mermaid loader that imports mermaid and calls run()"]
    if not (re.search(r"\.run\s*\(", loader) or re.search(r"startOnLoad\s*:\s*true", loader)):
        return ["the mermaid loader never triggers a render (no .run() call and startOnLoad is "
                "not true), so the diagrams will not render"]
    if re.search(r"URLSearchParams", loader) and re.search(r"\.get\(\s*[\"']mermaid[\"']\s*\)", loader):
        return ["the mermaid loader only runs when a URL query parameter is set (e.g. ?mermaid=1), "
                "so the diagrams will NOT render by default - remove the query-param gate so "
                "mermaid renders when the file is opened normally"]
    return []


def _check_nonportable(html, base_dir, id_counts):
    """NonPortable-mode-only invariants. Returns (errors, warnings)."""
    errors, warnings = [], []

    css_refs = _nonportable_css_refs(html)
    js_refs = _nonportable_js_refs(html)
    runtime_refs = [s for s in js_refs if not s.lower().endswith(".assets.js")]
    assets_refs = [s for s in js_refs if s.lower().endswith(".assets.js")]

    if not css_refs:
        errors.append('nonportable mode: no commentable-html stylesheet <link ... .css> found (the layer will be unstyled)')
    if not runtime_refs:
        errors.append('nonportable mode: no commentable-html runtime <script src ... .js> found (the layer will not load)')
    if not assets_refs:
        warnings.append('nonportable mode: no commentable-html.*.assets.js is referenced - "Export with embedded comments" cannot rebuild a portable file (add the assets companion or ship a standalone copy)')

    # Version stamp: a <meta name="commentable-html-version"> records the skill
    # version that produced the file and lets the runtime detect a stale companion
    # by comparing it against the loaded runtime's CMH_VERSION.
    metas = _nonportable_meta_versions(html)
    if not metas:
        warnings.append('nonportable mode: missing <meta name="commentable-html-version" content="X"> - the runtime cannot detect a stale/mismatched companion file')

    # Mandatory missing-asset banner: if the external runtime never loads, the
    # page must say so instead of looking fine but dead.
    if id_counts.get("cmhAssetBanner", 0) == 0:
        errors.append('nonportable mode: missing the #cmhAssetBanner element (a broken companion load would fail silently) - keep the NONPORTABLE BOOTSTRAP block')
    if "__commentableHtmlReady" not in html:
        warnings.append('nonportable mode: no bootstrap watchdog (looked for __commentableHtmlReady) - the missing-asset banner will never reveal itself')

    # Referenced companion files must resolve to a local file that exists. NonPortable
    # intentionally points at the skill's dist/ folder (a relative subdirectory or a
    # ../ path, or an absolute file:// URL), so a subfolder / parent reference is
    # allowed. Network URLs and non-file schemes are rejected, absolute filesystem
    # paths are warned about, and a missing target errors.
    # The remote-URL and absolute-path checks are structural (they inspect the ref
    # string only), so they always run. Only the on-disk existence check needs a
    # base_dir; when base_dir is None the placement is deferred (e.g. generation-time
    # validation of a not-yet-placed document), so existence is not checked - the
    # structure is still validated.
    for ref in css_refs + js_refs:
        if re.match(r"(?:https?:)?//", ref, re.I):
            errors.append('nonportable mode: companion reference "%s" must be a local file, not a remote/CDN URL (the layer must stay self-contained)' % ref)
            continue
        norm = ref.replace("\\", "/")
        file_target = _file_url_to_path(ref)
        if file_target is not None:
            target = file_target
        elif re.match(r"[a-zA-Z][a-zA-Z0-9+.\-]*:", ref) and not re.match(r"[a-zA-Z]:[\\/]", ref):
            errors.append('nonportable mode: companion reference "%s" must be a local file, not a non-file URL scheme' % ref)
            continue
        elif norm.startswith("/") or re.match(r"[a-zA-Z]:", ref):
            # Absolute path: usable but leaks a local directory and is not portable.
            warnings.append('nonportable mode: companion reference "%s" is an absolute path (it leaks a local directory and is not portable) - prefer a relative path to the skill dist/ folder' % ref)
            target = os.path.abspath(ref)
        elif base_dir is not None:
            # Relative ref resolved against the document folder; a subdirectory or
            # ../ path to the skill dist/ folder is the intended nonportable workflow.
            target = os.path.abspath(os.path.join(os.path.abspath(base_dir), norm))
        else:
            target = None
        if target is not None and (base_dir is not None or file_target is not None) and not os.path.exists(target):
            errors.append('nonportable mode: referenced companion file not found: %s (point the <link>/<script src> at the skill dist/ folder, or copy dist/ next to the document)' % ref)

    return errors, warnings


def check_layer(html, parser, base_dir=None):
    errors, warnings = [], []
    nonportable = _is_nonportable(html)
    active_regions = NONPORTABLE_REGIONS if nonportable else REGIONS

    # 1) Exactly one BEGIN and one END marker per (active) region, BEGIN before END.
    begin_idx, end_idx = {}, {}
    for region in active_regions:
        begins = list(_begin_re(region).finditer(html))
        ends = list(_end_re(region).finditer(html))
        if len(begins) != 1:
            errors.append(f"region '{region}': expected 1 BEGIN marker, found {len(begins)}")
        else:
            begin_idx[region] = begins[0].start()
        if len(ends) != 1:
            errors.append(f"region '{region}': expected 1 END marker, found {len(ends)}")
        else:
            end_idx[region] = ends[0].start()
    for region in active_regions:
        if region in begin_idx and region in end_idx and begin_idx[region] >= end_idx[region]:
            errors.append(f"region '{region}': END marker appears before its BEGIN marker")

    # 2) Region ordering.
    order = [r for r in active_regions if r in begin_idx]
    positions = [begin_idx[r] for r in order]
    if len(positions) >= 2 and positions != sorted(positions):
        errors.append("regions are out of order (expected order: %s)" % ", ".join(active_regions))

    errors.extend(_check_layer_descriptor(parser, nonportable, active_regions))

    content_begin_count = html.count(CONTENT_BEGIN)
    content_end_count = html.count(CONTENT_END)
    if content_begin_count != 1:
        errors.append("CONTENT region: expected 1 BEGIN marker, found %d" % content_begin_count)
    if content_end_count != 1:
        errors.append("CONTENT region: expected 1 END marker, found %d" % content_end_count)
    if content_begin_count == 1 and content_end_count == 1 and html.index(CONTENT_BEGIN) >= html.index(CONTENT_END):
        errors.append("CONTENT region: END marker appears before its BEGIN marker")

    # 3) #commentRoot present (real element id, via the parser) with required data-* attributes.
    n_roots = parser.all_ids.count("commentRoot")
    if n_roots == 0:
        errors.append('no element with id="commentRoot" (content root is missing)')
    elif n_roots > 1:
        errors.append(f'id="commentRoot" appears {n_roots} times (must be unique)')
    else:
        attrs = parser.comment_root_attrs or {}
        if "data-cmh-content-root" not in attrs:
            errors.append('#commentRoot is missing data-cmh-content-root (stable hook for content/infra tooling)')
        if not attrs.get("data-comment-key", "").strip():
            errors.append('#commentRoot is missing a non-empty data-comment-key (the layer falls back to "commentable-html:" + location.pathname, but set an explicit key so comments do not collide across pages on the same origin)')
        if not attrs.get("data-doc-label", "").strip():
            warnings.append("#commentRoot has no data-doc-label (falls back to document.title / location.pathname; set it for a stable label in review loops)")
        if not attrs.get("data-doc-source", "").strip():
            warnings.append("#commentRoot has no data-doc-source (falls back to location.pathname; set it for real review loops)")
        # 3a) The ACTIVE content root must not still be a pristine template demo. If
        #     a retrofit changed the <title> but left the demo content root in place,
        #     the demo - not the consumer's content - renders. The generated templates
        #     keep their own demo <title>, so this stays green for them.
        _active_key = attrs.get("data-comment-key", "").strip()
        if _active_key in DEMO_KEYS:
            _tm = _TITLE_RE.search(html)
            _title = (_tm.group(1).strip() if _tm else "")
            if _title and _title != DEMO_KEYS[_active_key]:
                errors.append(
                    'the active #commentRoot still uses the template demo '
                    'data-comment-key "%s" while the document <title> was customized '
                    "- the demo content root survived the retrofit; give your content "
                    "root a unique data-comment-key and replace the demo body"
                    % _active_key)

    # 3b) No REAL content root may be hidden inside an HTML comment. Guards the
    #     retrofit failure where a script replaced the WRONG "<main id=commentRoot>"
    #     - the template ships one as a documentation EXAMPLE inside the top-of-file
    #     comment - so the consumer's real content ends up commented out and the
    #     browser renders the leftover demo. The only sanctioned commented root is
    #     that example (data-comment-key="my-doc"); any other commented content
    #     root (a different key, or none) means content was commented by mistake.
    #     Scan with <script>/<style> bodies blanked so comment-like text inside them
    #     (which the browser treats as script/style data, not a comment) is ignored.
    _comment_scan_src = _SCRIPT_STYLE_RE.sub(" ", html)
    for _cm in _HTML_COMMENT_RE.finditer(_comment_scan_src):
        _block = _cm.group(0)
        _hit = False
        for _rm in _COMMENT_ROOT_ATTR_RE.finditer(_block):
            _win = _block[max(0, _rm.start() - 40):_rm.end() + 300]
            _km = _DATA_KEY_RE.search(_win)
            if not _km or _km.group(1) != DOC_EXAMPLE_COMMENT_KEY:
                _hit = True
                break
        if _hit:
            errors.append(
                'an element with id="commentRoot" is inside an HTML comment '
                "(per-document content was commented out during retrofit); only the "
                'template documentation example (data-comment-key="%s") may be '
                "commented" % DOC_EXAMPLE_COMMENT_KEY)
            break

    # Region byte ranges, so the JSON blocks below are read from inside their own
    # region and a decoy <script> with the same id elsewhere is ignored.
    def _bounds(name):
        if name in begin_idx and name in end_idx and begin_idx[name] < end_idx[name]:
            return begin_idx[name], end_idx[name]
        return None, None

    # 3c) Text-anchoring robustness. The layer's offsetWithin() must normalize a range
    #     boundary that lands on an element node (element, childIndex) to a text node,
    #     or a selection starting/ending at a block edge (e.g. a heading selected from
    #     its start yields a (h3, 0) boundary) returns -1 and the composer aborts with
    #     "Could not anchor that selection". Require a real normalizeBoundary() function
    #     AND a call to it from within offsetWithin()'s body (brace-matched on the
    #     string/comment-blanked source via _js_scan, so a normalizeBoundary token that
    #     lives only in a comment or a string literal cannot satisfy the check and a `}`
    #     inside a string cannot prematurely close the body). Gate on offsetWithin so the
    #     stub JS used by the test fixtures (which has neither symbol) stays exempt.
    _jlo, _jhi = _bounds("JS")
    if _jlo is not None:
        _scan = _js_scan(html[_jlo:_jhi])[1]  # init view: comments AND strings blanked
        _decl = re.search(r"function\s+offsetWithin\s*\([^)]*\)\s*\{", _scan)
        if _decl is not None:
            _has_decl = re.search(r"function\s+normalizeBoundary\s*\(", _scan) is not None
            _calls = False
            _m = _decl
            if _m:
                _depth, _body_start = 0, _m.end()
                for _j in range(_m.end() - 1, len(_scan)):
                    if _scan[_j] == "{":
                        _depth += 1
                    elif _scan[_j] == "}":
                        _depth -= 1
                        if _depth == 0:
                            _calls = re.search(r"\bnormalizeBoundary\s*\(", _scan[_body_start:_j]) is not None
                            break
            if not (_has_decl and _calls):
                errors.append(
                    "the JS region defines offsetWithin() but does not both declare a "
                    "normalizeBoundary() function and call it from within offsetWithin(); a "
                    'selection whose start or end lands on an element boundary will fail to '
                    'anchor ("Could not anchor that selection")')

    # 4) handledCommentIds is a JSON array of safe ids.
    hlo, hhi = _bounds("HANDLED IDS")
    handled_script = _parser_script(parser, "handledCommentIds", hlo, hhi)
    handled = handled_script["body"] if handled_script is not None else None
    if handled is None:
        errors.append('missing <script id="handledCommentIds"> block')
    else:
        if not _is_json_attrs(handled_script["attrs"]):
            errors.append('the <script id="handledCommentIds"> block must be type="application/json" '
                          "(without it the browser executes the JSON as JavaScript)")
        try:
            arr = json.loads(handled.strip() or "[]")
            if not isinstance(arr, list):
                errors.append("handledCommentIds is not a JSON array")
            else:
                bad = [x for x in arr if not (isinstance(x, str) and SAFE_ID_RE.match(x))]
                if bad:
                    errors.append(f"handledCommentIds has {len(bad)} id(s) not matching the safe pattern "
                                  f"{SAFE_ID_RE.pattern}: {bad[:3]} - mark_handled.py will refuse to edit "
                                  "this file until they are corrected")
        except json.JSONDecodeError as exc:
            errors.append(f"handledCommentIds is not valid JSON: {exc}")

    # 5) embeddedComments is a JSON array.
    elo, ehi = _bounds("EMBEDDED COMMENTS")
    embedded_script = _parser_script(parser, "embeddedComments", elo, ehi)
    embedded = embedded_script["body"] if embedded_script is not None else None
    if embedded is None:
        errors.append('missing <script id="embeddedComments"> block')
    else:
        if not _is_json_attrs(embedded_script["attrs"]):
            errors.append('the <script id="embeddedComments"> block must be type="application/json" '
                          "(without it the browser executes the JSON as JavaScript)")
        try:
            arr = json.loads(embedded.strip() or "[]")
            if not isinstance(arr, list):
                errors.append("embeddedComments is not a JSON array")
            else:
                # Each embedded comment must have a safe string id (the runtime keys
                # merge/dedupe on it and getElementById-style lookups assume it is safe);
                # a null/non-string/unsafe id silently drops or breaks the comment at load.
                bad = [i for i, item in enumerate(arr)
                       if not (isinstance(item, dict) and isinstance(item.get("id"), str)
                               and SAFE_ID_RE.match(item["id"]))]
                if bad:
                    errors.append("embeddedComments: %d item(s) have a missing or unsafe id "
                                  "(indices %s) - each item must be an object whose id matches %s"
                                  % (len(bad), bad[:5], SAFE_ID_RE.pattern))
        except json.JSONDecodeError as exc:
            errors.append(f"embeddedComments is not valid JSON: {exc}")

    # 6) The JS region must contain exactly one real </script>.
    if not nonportable and "JS" in begin_idx and "JS" in end_idx:
        lo, hi = sorted((begin_idx["JS"], end_idx["JS"]))
        js_slice = html[lo:hi]
        n_close = len(re.findall(r"</script\s*>", js_slice, re.IGNORECASE))
        if n_close == 0:
            errors.append("JS region has no closing </script> before its END marker (malformed)")
        elif n_close > 1:
            errors.append(f"JS region contains {n_close} </script> tags - a literal </script> in the script body must be escaped as <\\/script>")

    # 7) Required UI ids present exactly once (a duplicate means a decoy could
    # satisfy the check while the real control is missing, and getElementById may
    # bind the layer to the wrong element).
    id_counts = Counter(parser.all_ids)
    for uid in REQUIRED_IDS:
        c = id_counts.get(uid, 0)
        if c == 0:
            errors.append(f'required element id="{uid}" is missing')
        elif c > 1:
            errors.append(f'required element id="{uid}" appears {c} times (must be unique)')

    # 7b) The document-owned JSON script blocks must also be unique across the
    # whole active DOM. A duplicated id makes getElementById() bind to a decoy,
    # silently reading/writing the wrong element. Absence is already reported by
    # dedicated checks above, so only flag duplicates.
    for uid in sorted(LAYER_JSON_IDS):
        c = id_counts.get(uid, 0)
        if c > 1:
            if uid == LAYER_DESCRIPTOR_ID:
                errors.append(f'id="{uid}" appears {c} times (must be unique)')
            else:
                errors.append(f'<script id="{uid}"> appears {c} times (must be unique)')

    # 8) Export/Import must stay removed (dropped before the 1.0.0 release).
    present_forbidden = [uid for uid in FORBIDDEN_IDS if uid in id_counts]
    if present_forbidden or "--START-COMMENTS-EXPORT--" in html:
        warnings.append("Export/Import UI detected - this was removed before the 1.0.0 release (redundant with Export with embedded comments): "
                        + ", ".join(present_forbidden or ["--START-COMMENTS-EXPORT-- marker"]))

    # 9) The global [hidden] reset must be scoped to the layer.
    if re.search(r"(?m)^[ \t]*\[hidden\]\s*\{\s*display:\s*none", html):
        warnings.append("found an unscoped '[hidden] { display: none }' rule - scope it to '.cm-skip[hidden], .cm-skip [hidden]' so it cannot hide host elements")
    if not nonportable and ".cm-skip[hidden]" not in html:
        warnings.append("missing the scoped '.cm-skip[hidden]' rule (the layer's own hidden elements may not hide)")

    # 10) The --cp-* theme variables must be DEFINED.
    if not re.search(r"--cp-bg\s*:", html):
        errors.append("the --cp-* theme variables are not defined (looked for a '--cp-bg:' declaration; the layer and its host will render unstyled)")

    # 11) Mermaid blocks should keep cm-skip.
    if any(not mb["cm_skip"] for mb in parser.mermaid_blocks):
        warnings.append("a mermaid block is missing class \"cm-skip\" (its source text becomes selectable)")

    # 11a) Section cross-references in prose should be in-page anchor links (deterministic
    #      detection; only UNLINKED references reach commentroot_prose).
    warnings.extend(check_section_reference_links(parser))

    # 11a2) Mermaid diagrams must actually render on open (loader present, triggers a
    #       render, and is not hidden behind a query-param gate).
    warnings.extend(check_mermaid_renders(parser))

    # 11b) An authored diff block (<pre class="cmh-diff">) must carry ESCAPED diff
    #      text: a raw HTML tag inside it is parsed and can execute before the diff
    #      layer runs, so an unescaped diff is an HTML-injection hazard and must
    #      FAIL validation (like the chart-JSON breakout checks), not just warn.
    #      Only inspect <pre> sources (a rendered/exported host is a
    #      <div class="cmh-diff-host"> full of the layer's own safe markup).
    _diff_n = 0
    for m in _PRE_TAG_RE.finditer(html):
        if not _attrs_have_class(m.group(1), "cmh-diff"):
            continue
        _diff_n += 1
        _bad = re.search(r"<\s*[a-zA-Z!/]", m.group(2))
        if _bad:
            _snip = m.group(2)[_bad.start():_bad.start() + 24].replace("\n", " ")
            errors.append('diff block #%d (<pre class="cmh-diff">) contains a raw HTML tag (%r) - '
                          'escape the diff text (< as &lt;, > as &gt;, & as &amp;) so embedded '
                          'markup cannot execute before the diff renders' % (_diff_n, _snip))

    # 11c) "Run in Azure Data Explorer" links (class cmh-kql-run) must point at the ADX web UX over
    #      https and open safely. This fires ONLY on the explicit run-link class, so
    #      it never false-positives on a plain KQL code block or a syntax example.
    for a in _find_tag_attrs(html, "a"):
        if "cmh-kql-run" not in (a.get("class") or "").split():
            continue
        href = a.get("href", "")
        if not href.startswith("https://dataexplorer.azure.com/"):
            warnings.append('a "cmh-kql-run" link does not point at https://dataexplorer.azure.com/ '
                            "(build it with tools/kusto_link.py): " + (href[:80] or "(empty href)"))
        if a.get("target", "") == "_blank" and "noopener" not in (a.get("rel") or "").lower().split():
            warnings.append('a "cmh-kql-run" link uses target="_blank" without rel="noopener" '
                            "(reverse-tabnabbing risk); add rel=\"noopener noreferrer\"")

    # 11d) A framed KQL figure (figure.cmh-kql) with no "Run in Azure Data Explorer" link (class
    #      cmh-kql-run) is a usability gap: the reader cannot open the query in ADX.
    #      Warn per such figure so authors add a link built with tools/kusto_link.py.
    for fm in re.finditer(r"<figure\b([^>]*)>(.*?)</figure>", html, re.IGNORECASE | re.DOTALL):
        if not _attrs_have_class(fm.group(1), "cmh-kql"):
            continue
        if "cmh-kql-run" not in fm.group(2):
            warnings.append('a figure.cmh-kql has no "Run in Azure Data Explorer" link (class cmh-kql-run); '
                            "build one with tools/kusto_link.py so readers can open the query in ADX")

    # 11e) Self-contained guarantee: the finished document must not pull resources over the
    #      network (the core promise is a single self-contained file). <a href> links
    #      are navigation, not resource loads, so they are exempt; Chart.js from a CDN
    #      is a documented opt-in in portable mode (its SRI/version are checked in
    #      check_charts); mermaid CDN imports are handled by check_mermaid_renders.
    #      Offline mode is stricter: no network-loading resource is allowed.
    def _is_network(v):
        return bool(re.match(r"(?:https?:)?//", v or "", re.I))
    descriptor = _layer_descriptor_data(parser) or {}
    offline_mode = (not nonportable and descriptor.get("mode") == "offline")
    def _network_values(value, srcset=False):
        if srcset:
            return [part.strip().split()[0] for part in (value or "").split(",") if part.strip()]
        return [value or ""]
    def _network_error(tag, attr, val):
        label = "<%s %s=\"%s\">" % (tag, attr, val[:80])
        if offline_mode:
            if tag == "script" and CHARTJS_SRC_RE.search(val):
                return "offline mode: %s loads Chart.js over the network - inline it or export offline after rendering" % label
            return "offline mode: %s loads over the network - inline or remove it" % label
        return None
    def _check_network_attr(tag, attrs, attr, srcset=False):
        val = attrs.get(attr, "")
        if not val:
            return
        for item in _network_values(val, srcset=srcset):
            if not _is_network(item):
                continue
            e = _network_error(tag, attr, item)
            if e:
                errors.append(e)
                continue
            if tag == "script" and CHARTJS_SRC_RE.search(item):
                continue
            if tag == "link":
                warnings.append('<link %s="%s"> loads over the network and breaks the self-contained '
                                "guarantee - inline or remove it" % (attr, item[:80]))
            else:
                errors.append('<%s %s="%s"> loads over the network and breaks the self-contained guarantee - '
                              "inline or remove it" % (tag, attr, item[:80]))
    for img in _find_tag_attrs(html, "img"):
        src = img.get("src", "")
        if src and not src.startswith("data:"):
            if _is_network(src):
                e = _network_error("img", "src", src)
                if e:
                    errors.append(e)
                else:
                    errors.append('<img src="%s"> loads over the network - inline it with '
                                  "tools/inline_images.py (external images break self-contained use and portability)"
                                  % src[:80])
            elif not re.match(r"[a-z][a-z0-9+.\-]*:", src, re.I):
                warnings.append('<img src="%s"> is a local path - run tools/inline_images.py to embed '
                                "it as a data: URI so the image travels with the file" % src[:80])
        _check_network_attr("img", img, "srcset", srcset=True)
    for tag, attr in (("link", "href"), ("script", "src"), ("iframe", "src")):
        for el in _find_tag_attrs(html, tag):
            _check_network_attr(tag, el, attr)
    if offline_mode:
        media_attrs = (
            ("video", "src", False), ("video", "poster", False),
            ("audio", "src", False), ("source", "src", False), ("source", "srcset", True),
            ("object", "data", False), ("embed", "src", False), ("track", "src", False),
            ("image", "href", False), ("image", "xlink:href", False),
            ("use", "href", False), ("use", "xlink:href", False),
        )
        for tag, attr, is_srcset in media_attrs:
            for el in _find_tag_attrs(html, tag):
                _check_network_attr(tag, el, attr, srcset=is_srcset)
        for el in _find_tag_attrs(html, "input"):
            if (el.get("type") or "").lower() == "image":
                _check_network_attr("input", el, "src")
        for tag in ("body", "table", "td", "th", "div"):
            for el in _find_tag_attrs(html, tag):
                _check_network_attr(tag, el, "background")
        for style in parser.styles:
            for m in re.finditer(r"@import\s+(?:url\()?['\"]?((?:https?:)?//[^;'\"\)]+)", style.get("body", ""), re.I):
                errors.append('offline mode: @import "%s" loads over the network - inline or remove it' % m.group(1)[:80])
        for script in parser.scripts:
            if not _is_executable_js(script["attrs"]):
                continue
            body = script.get("body", "")
            if (re.search(r"\bimport\s*\(", body) and re.search(r"(?:https?:)?//", body, re.I)) or \
                    re.search(r"\b(?:import|from)\s+['\"](?:https?:)?//", body, re.I):
                errors.append("offline mode: inline script imports a network module - inline or remove it")

    # 11f) Duplicate heading ids collide in-page anchors: the TOC and prose links bind
    #      to the first occurrence, so later sections become unreachable.
    _hids = [h.get("id") for h in parser.headings if h.get("id")]
    _dup_hids = sorted(hid for hid, cnt in Counter(_hids).items() if cnt > 1)
    if _dup_hids:
        warnings.append("duplicate heading id(s) detected: %s - in-page anchors and the generated TOC "
                        "bind to the first occurrence; give each heading a unique id"
                        % ", ".join(_dup_hids[:5]))

    # 12) NonPortable-mode-only invariants (companion refs, version handshake, banner,
    #     referenced files exist).
    if nonportable:
        e, w = _check_nonportable(html, base_dir, id_counts)
        errors += e
        warnings += w

    return errors, warnings


# --------------------------------------------------------------------------- #
# Chart checks
# --------------------------------------------------------------------------- #

def check_charts(html, parser):
    """Return (errors, warnings, n_canvas). No-op (0 canvas) when the document
    embeds no <canvas>. Assumes `parser` already fed `html` successfully."""
    errors, warnings = [], []

    n_canvas = len(parser.canvases)
    if n_canvas == 0:
        return errors, warnings, 0

    marker_pos = parser.js_end_marker_pos
    has_layer = parser.has_comment_root or marker_pos is not None

    # Executable (classic/module JS) scripts: where `new Chart(` may run, and the
    # guard. A script with a `src` has its inline body ignored by the browser, so
    # do not scan it. Comments and string literals are blanked so they cannot
    # false-trigger.
    new_chart_positions = []
    guard_present = False
    inline_canvas_render = False
    for s in parser.scripts:
        if not _is_executable_js(s["attrs"]):
            continue
        if s["attrs"].get("src") is not None:
            continue  # <script src=...> inline content is dead code in the browser
        guard_src, init_src = _js_scan(s["body"])
        if NEW_CHART_RE.search(init_src):
            new_chart_positions.append(s["pos"])
        # An inline getContext draw renders a canvas WITHOUT any library. A bare
        # `new Chart(` does NOT count here: it needs the Chart.js loader (E3 still
        # fires if the loader is missing).
        if CANVAS_RENDER_RE.search(init_src):
            inline_canvas_render = True
        if GUARD_RE.search(guard_src):
            guard_present = True

    # The first executable Chart.js loader tag (by document position). A
    # non-executable script (e.g. type="application/json") with a chart.js src
    # does not load Chart, so it is not a loader.
    loader_attrs, loader_src, loader_pos = None, None, None
    for s in parser.scripts:
        src = s["attrs"].get("src")
        if src and CHARTJS_SRC_RE.search(src) and _is_executable_js(s["attrs"]):
            loader_attrs, loader_src, loader_pos = s["attrs"], src, s["pos"]
            break

    # E1) Every <canvas> must sit inside a cm-skip element (layer docs only).
    unskipped = sum(1 for c in parser.canvases if not c["skip"])
    if has_layer and unskipped:
        errors.append(f"{unskipped} of {n_canvas} <canvas> element(s) are not inside a cm-skip "
                      f"wrapper (the chart pixels become selectable; put cm-skip on the .chart-wrap)")

    # E2) A chart's <figcaption> must stay commentable. Flag only captions inside a
    # chart <figure> that got swept into cm-skip (the author put cm-skip on the
    # <figure> instead of the .chart-wrap). Other cm-skip captions (e.g. the KQL
    # caption chrome) are intentional and not chart captions.
    capped = sum(1 for f in parser.figcaptions
                 if f["skip"] and not f["in_canvas"] and f.get("in_chart_figure"))
    if has_layer and capped:
        errors.append(f"{capped} chart <figcaption>(s) are inside a cm-skip element and cannot be "
                      f"commented on - put cm-skip on the .chart-wrap around the <canvas>, not on the <figure>")

    # E3) A canvas needs a renderer or nothing shows: either the Chart.js loader,
    # or an inline script that draws to a canvas (getContext) / builds a Chart.
    if loader_attrs is None and not inline_canvas_render:
        errors.append("a <canvas> is present but no renderer was found (no Chart.js <script src> "
                      "and no inline canvas draw) - the chart will not render")

    # E4) Chart-data JSON must be valid and free of a "</script"/"<!--" breakout.
    for s in parser.scripts:
        if not _is_json_attrs(s["attrs"]):
            continue
        jid = s["attrs"].get("id") or None
        if jid in LAYER_JSON_IDS:
            continue  # owned by the commentable layer, not chart data
        where = f'id="{jid}"' if jid else "(no id)"
        body = s["body"]
        if "<!--" in body:
            errors.append(f'chart-data <script type="application/json"> {where} contains a "<!--" '
                          f'that can break out of the block - escape "<" as \\u003C when serializing')
            continue
        stripped = body.strip()
        if not stripped:
            errors.append(f'chart-data <script type="application/json"> {where} is empty - '
                          f'JSON.parse() will throw at chart init; emit valid JSON (e.g. [] or {{}})')
            continue
        try:
            json.loads(stripped)
        except json.JSONDecodeError:
            errors.append(f'chart-data <script type="application/json"> {where} is not valid JSON - a raw '
                          f'"</script>" likely truncated it; serialize with an encoder and escape "<" as \\u003C')

    # E5) Chart init must come AFTER the JS END marker comment (Save-as-plain
    # keeps it) AND after the Chart.js loader (or Chart is undefined when it runs).
    if marker_pos is not None:
        if any(pos < marker_pos for pos in new_chart_positions):
            errors.append("chart init (`new Chart(`) appears before the `END: commentable-html - JS` "
                          "marker - place chart scripts after it so Save-as-plain preserves the chart")
    if loader_pos is not None:
        if any(pos < loader_pos for pos in new_chart_positions):
            errors.append("chart init (`new Chart(`) appears before the Chart.js `<script src>` loader - "
                          "load Chart.js first, or Chart is undefined when the init runs")

    # ---- warnings ----
    if loader_attrs is not None:
        integ = loader_attrs.get("integrity")
        has_cross = "crossorigin" in loader_attrs
        if not (integ and integ.strip()) or not has_cross:
            warnings.append("the Chart.js CDN tag has no (non-empty) Subresource Integrity hash + crossorigin - "
                            'add integrity="sha384-..." crossorigin="anonymous" for a shareable artifact')
        typ = (loader_attrs.get("type") or "").lower()
        if "defer" in loader_attrs or "async" in loader_attrs or typ == "module":
            warnings.append("the Chart.js CDN tag is deferred/async/module - the inline init can run before "
                            "Chart is defined; load it synchronously before the init")
        if not re.search(r"chart\.js@\d+\.\d+\.\d+", loader_src or "", re.IGNORECASE):
            warnings.append("the Chart.js CDN URL is not pinned to a full version (use chart.js@X.Y.Z, not "
                            "@latest or @4) - a floating version can change under you and break the SRI hash")

    n_missing_aria = sum(1 for c in parser.canvases
                         if c["attrs"].get("role", "").lower() != "img"
                         or not c["attrs"].get("aria-label", "").strip())
    if n_missing_aria:
        warnings.append("%d of %d <canvas> element(s) are missing role=\"img\" + a non-empty "
                        "aria-label (a canvas is opaque to screen readers; add an accessible "
                        "label to each)" % (n_missing_aria, n_canvas))

    if new_chart_positions and not guard_present:
        warnings.append("the chart init does not guard with `typeof Chart === \"undefined\"` - a network-unavailable / "
                        "CDN-blocked load will throw instead of degrading to a blank canvas")

    # W6) A loaded canvas with no executable `new Chart(` renders nothing.
    if loader_attrs is not None and not new_chart_positions:
        warnings.append("a <canvas> and the Chart.js loader are present but no executable `new Chart(` init "
                        "was found - the canvas will render blank (build the chart in an executable script)")

    return errors, warnings, n_canvas


# --------------------------------------------------------------------------- #
# Entry points
# --------------------------------------------------------------------------- #

def _read(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _parse(html):
    """Feed `html` to a fresh _DocParser. Returns (parser, ok); ok is False if
    HTMLParser raised on markup too malformed to tokenize."""
    parser = _DocParser(html)
    try:
        parser.feed(html)
        parser.close()
        return parser, True
    except Exception:
        return parser, False


_PARSE_FAIL = ("the document could not be parsed as HTML (malformed markup) - "
               "fix the markup and re-run")


_BASE_DIR_UNSET = object()


def validate(path, layer=True, charts=True, base_dir=_BASE_DIR_UNSET):
    """Unified check. Returns (errors, warnings). Runs the layer checks and,
    when the document has a <canvas>, the chart checks too.

    base_dir controls how NonPortable companion references are resolved for the
    existence/remote/absolute checks: by default it is the document's own directory.
    Pass an explicit directory to resolve refs against the file's FINAL location (used
    when validating before the file is written there), or None to skip the companion
    path checks entirely (structure is still validated) - appropriate when the
    companions are supplied separately or placement is deferred."""
    try:
        html = _read(path)
    except (OSError, UnicodeDecodeError) as exc:
        return [f"cannot read file: {exc}"], []
    parser, ok = _parse(html)
    if not ok:
        return [_PARSE_FAIL], []
    errors, warnings = [], []
    if layer:
        bd = os.path.dirname(os.path.abspath(path)) if base_dir is _BASE_DIR_UNSET else base_dir
        e, w = check_layer(html, parser, base_dir=bd)
        errors += e
        warnings += w
    if charts:
        e, w, _n = check_charts(html, parser)
        errors += e
        warnings += w
    return errors, warnings


def validate_charts(path):
    """Chart-only check. Returns (errors, warnings, n_canvas)."""
    try:
        html = _read(path)
    except (OSError, UnicodeDecodeError) as exc:
        return [f"cannot read file: {exc}"], [], 0
    parser, ok = _parse(html)
    if not ok:
        n = len(re.findall(r"<canvas(?![-\w])", html, re.IGNORECASE))
        return ([_PARSE_FAIL] if n else []), [], n
    return check_charts(html, parser)


_USAGE = "usage: python tools/validate.py [--charts-only|--layer-only] [--strict] <file.html> [more.html ...]"


def _wants_help(tokens):
    # Honor -h/--help only before an end-of-options "--"; a -h AFTER "--" is a filename.
    for t in tokens:
        if t == "--":
            return False
        if t in ("-h", "--help"):
            return True
    return False


def main(argv):
    raw = argv[1:]
    if _wants_help(raw):
        print(_USAGE)
        print("\nValidate one or more commentable-html documents.")
        print("  --charts-only  run only the Chart.js checks")
        print("  --layer-only   run only the commentable-html layer checks")
        print("  --strict       exit non-zero if any warning remains")
        return 0
    # A bare "--" ends options: everything after it is a positional path, even if it
    # begins with a dash. Flags are only recognized before the separator.
    if "--" in raw:
        sep = raw.index("--")
        before, after = raw[:sep], raw[sep + 1:]
    else:
        before, after = raw, []
    args = [a for a in before if not a.startswith("--")] + after
    flags = {a for a in before if a.startswith("--")}
    known_flags = {"--charts-only", "--layer-only", "--strict"}
    unknown = sorted(flags - known_flags)
    if unknown:
        sys.stderr.write("unknown flag(s): %s\n" % ", ".join(unknown))
        sys.stderr.write(_USAGE + "\n")
        return 2
    layer = "--charts-only" not in flags
    charts = "--layer-only" not in flags
    strict = "--strict" in flags
    if not args or (not layer and not charts):
        sys.stderr.write(_USAGE + "\n")
        return 2
    any_errors = False
    any_warnings = False
    for path in args:
        try:
            errors, warnings = validate(path, layer=layer, charts=charts)
        except Exception:
            # A bug in one file's checks must never abort the whole batch.
            errors, warnings = [f"internal validator error:\n{traceback.format_exc().strip()}"], []
        print(f"commentable-html validate: {path}")
        for w in warnings:
            print(f"  WARNING: {w}")
        for e in errors:
            print(f"  ERROR:   {e}")
        if warnings:
            any_warnings = True
        if errors:
            any_errors = True
            print(f"  FAILED ({len(errors)} error(s), {len(warnings)} warning(s))")
        elif strict and warnings:
            print(f"  FAILED (strict): {len(warnings)} warning(s) - resolve every warning before handoff")
        else:
            print(f"  OK ({len(warnings)} warning(s))")
    if any_errors:
        return 1
    if strict and any_warnings:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
