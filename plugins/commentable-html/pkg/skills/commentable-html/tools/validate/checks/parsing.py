"""Shared HTML parsing infrastructure for the commentable-html validator: the
single-pass `_DocParser`, region-marker detection, tag/script attribute helpers,
and the constants (regions, ids, regexes) every check builds on."""

import re
from html.parser import HTMLParser

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

_CODE_TAG_RE = re.compile(r"<code\b([^>]*)>(.*?)</code>", re.DOTALL | re.IGNORECASE)

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


# dist/PORTABLE.html ships a working DEMO: its content root carries these placeholder
# values. A finished consumer document must (a) give its content root a unique
# data-comment-key - not the demo one - and (b) never leave real content commented
# out. The two checks below are written so the pristine dist/PORTABLE.html (demo key
# + demo <title>) still passes with zero findings, while a botched retrofit (a script
# that replaced the WRONG "<main id=commentRoot>" and buried the consumer's real
# content in a comment, leaving the demo as the live root) is caught. A single
# commented "<main id=commentRoot data-comment-key=my-doc>" documentation example is
# still tolerated, so authoring guidance may carry one without tripping the guard.
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
        self.inline_styles = []
        self.has_comment_root = False
        self.js_end_marker_pos = None
        self.all_ids = []        # every element id value, in document order
        self.metas = {}          # {meta name (lowercased): content} for <meta name content>
        self.comment_root_attrs = None   # attrs dict of the id=commentRoot element
        self.body_attrs = None           # attrs dict of the REAL <body> start tag (first one)
        self.mermaid_blocks = []         # [{"cm_skip": bool, "has_svg": bool}] for pre/div.mermaid
        self._mermaid_stack = []         # parallel to self.stack: current mermaid block index, or None
        self._cur_script = None   # (pos, attrs_dict) while inside a <script>
        self._cur_style = None    # (pos, attrs_dict) while inside a <style>
        self._cur_body = []
        self.commentroot_prose = []  # #commentRoot text NOT inside <a> or a cm-skip element
        self._cr_depth = None        # stack depth at which #commentRoot was entered
        self._cr_closed = False      # True once #commentRoot (or an ancestor) has closed
        self.headings = []           # [{"id": str|None, "text": str, "top_level": bool}] in #commentRoot
        self._cur_heading = None     # (tag, id, [parts], top_level) while capturing a heading's text
        self.has_top_level_lede = False  # a direct child of #commentRoot carries class cmh-lede
        self._lede_depth = None      # stack depth of the current top-level cmh-lede (for title h1)
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
        if tag == "body" and self.body_attrs is None:
            self.body_attrs = ad
        if tag == "meta":
            nm = (ad.get("name") or "").strip().lower()
            if nm and nm not in self.metas:
                self.metas[nm] = ad.get("content") or ""
        if tag == "canvas":
            self.canvases.append({"skip": self._skip_ancestor() or own_skip, "attrs": ad})
        elif tag == "figcaption":
            self.figcaptions.append({"skip": self._skip_ancestor() or own_skip,
                                     "in_canvas": self._in_canvas(),
                                     "in_chart_figure": any(self._figure_chart)})
        if "data-cm-offline-chart" in ad:
            self.has_offline_chart = True
        if "style" in ad:
            self.inline_styles.append({"tag": tag, "value": ad.get("style", "")})
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
        # A top-level (direct-child) element of #commentRoot carrying cmh-lede is the document's
        # own title header (new_document.ensure_doc_title emits <header class="cmh-lede"><h1>).
        if (self._cr_depth is not None and not self._cr_closed
                and len(self.stack) == self._cr_depth + 1
                and "cmh-lede" in set((ad.get("class") or "").split())):
            self.has_top_level_lede = True
            self._lede_depth = len(self.stack)

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
            top_level = (len(self.stack) == self._cr_depth + 1)
            in_lede = self._lede_depth is not None and len(self.stack) > self._lede_depth
            self._cur_heading = (tag, ad.get("id"), [], top_level, in_lede)
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
                self.headings.append({"tag": self._cur_heading[0],
                                      "id": self._cur_heading[1], "text": text,
                                      "top_level": self._cur_heading[3],
                                      "in_lede": self._cur_heading[4]})
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
                if self._lede_depth is not None and i <= self._lede_depth:
                    self._lede_depth = None
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
