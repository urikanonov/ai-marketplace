"""Shared HTML parsing infrastructure for the commentable-html validator: the
single-pass `_DocParser`, region-marker detection, tag/script attribute helpers,
and the constants (regions, ids, regexes) every check builds on."""

import functools
import re
from html.parser import HTMLParser
from types import MappingProxyType

REGIONS = ["CSS", "HANDLED IDS", "EMBEDDED COMMENTS", "COMMENT UI", "JS"]

LAYER_DESCRIPTOR_ID = "commentableHtmlLayer"

CONTENT_BEGIN = "<!-- BEGIN: commentable-html - CONTENT (agent edits ONLY between these markers) -->"

CONTENT_END = "<!-- END: commentable-html - CONTENT -->"

# The token the NonPortable bootstrap watchdog sets/reads. The parser records whether it appears
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
        # The LAYER's own markup: everything the parser sees OUTSIDE the authored CONTENT region
        # (`_in_commentable_content()`). A document about commentable-html can DEMONSTRATE the
        # companion markup in its prose, so the mode determination and the NonPortable checks read
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
        self._cur_body = []
        self.commentroot_prose = []  # #commentRoot text NOT inside <a> or a cm-skip element
        self._cr_depth = None        # stack depth at which #commentRoot was entered
        self._cr_closed = False      # True once #commentRoot (or an ancestor) has closed
        self._in_content_region = False
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

    def _in_comment_root(self):
        return self._cr_depth is not None and not self._cr_closed and len(self.stack) > self._cr_depth

    def _in_commentable_content(self):
        return self._in_content_region and self._in_comment_root()

    def _note_ready_token(self, text):
        """Record the NonPortable bootstrap watchdog token, but ONLY from the body of an
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
        self._note_ready_token(data)
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
                    self._in_content_region = False
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
        if not self._in_template():
            marker = data.strip()
            if marker == CONTENT_BEGIN[4:-3].strip() and self._in_comment_root():
                self._in_content_region = True
                self.content_region_opened = True
            elif marker == CONTENT_END[4:-3].strip():
                if self._in_content_region:
                    self.content_region_closed = True
                self._in_content_region = False


# --------------------------------------------------------------------------- #
# Parsed <pre>/<code> spans - the scan boundary CMH-VAL-11 and CMH-KQL-08 share.
# --------------------------------------------------------------------------- #

# Elements whose CONTENT is text, not markup (the browser's raw-text and RCDATA modes).
# A `<pre>`/`<code>` written inside one of them is prose a reader SEES, never an authored
# code block, so a code-block scan must not look inside. Every one is switched on
# EXPLICITLY rather than relying on html.parser's own table, which knows only script/style
# on older interpreters (3.13 added xmp/iframe/noembed/noframes/textarea/title) - so the
# boundary is identical on every Python the skill runs on. `noscript` is raw text in a
# scripting-ENABLED browser, which is the only mode a commentable document ever runs in.
# The set is applied unconditionally, including inside SVG/MathML where a browser would
# parse an element of the same name normally: a code block inside an SVG `<title>` is not a
# real shape, and a rule that depended on foreign-content state would land differently on
# 3.13 (whose parser makes its own raw-text decisions) than on 3.12.
_RAW_TEXT_ELEMENTS = frozenset((
    "script", "style", "textarea", "title", "xmp", "iframe", "noembed", "noframes", "noscript",
))

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
# attribute). html.parser only honours the canonical `</script>` before 3.13, which lets the
# raw-text region run on to the document's next canonical closer and swallow the authored block
# between - so _CodeSpanParser.parse_endtag applies this boundary itself on every host.
_RAW_TEXT_CLOSE_RES = {}

# `<![CDATA[ ... ]]>` is only a CDATA section inside FOREIGN content. Everywhere else a browser
# treats `<!` + junk as a BOGUS COMMENT that ends at the very first `>`, so markup after that `>`
# is LIVE - while html.parser consumes the whole marked section, which would hide a real code
# block (and, before 3.13, raises on an unknown section keyword).
_FOREIGN_ROOTS = frozenset(("svg", "math"))


def _raw_text_close_re(elem):
    rx = _RAW_TEXT_CLOSE_RES.get(elem)
    if rx is None:
        rx = re.compile(r"</%s(?=[\t\n\r\f />])[^>]*>" % re.escape(elem), re.IGNORECASE)
        _RAW_TEXT_CLOSE_RES[elem] = rx
    return rx


class _CodeSpanParser(HTMLParser):
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
        super().__init__(convert_charrefs=True)
        self._starts = _line_starts(html)
        self._stack = []   # [(tag, record or None, is_kql_figure)]
        self._final = False   # the whole document has been handed to feed()
        self.pres = []
        self.unclosed = False

    def parse_document(self, html):
        """Parse a COMPLETE document. Feeding the whole string at once is what lets an
        unterminated comment be resolved the way a browser resolves it (it runs to the end of
        the document) instead of the way the host interpreter happens to resolve it."""
        self._final = True
        self.feed(html)
        self.close()

    # -- offsets ---------------------------------------------------------- #

    def _off(self):
        ln, col = self.getpos()
        return self._starts[ln - 1] + col

    def _start_tag_end(self):
        return self._off() + len(self.get_starttag_text() or "")

    # -- cross-version comment and raw-text boundaries --------------------- #

    def parse_comment(self, i, report=True):
        rawdata = self.rawdata
        if not rawdata.startswith("<!--", i):
            raise AssertionError("unexpected call to parse_comment()")
        m = _COMMENT_ABRUPT_CLOSE_RE.match(rawdata, i + 4) or _COMMENT_CLOSE_RE.search(rawdata, i + 4)
        if m:
            if report:
                self.handle_comment(rawdata[i + 4:m.start()])
            return m.end()
        # Unterminated: a browser treats the rest of the document as comment data. Say so
        # explicitly rather than leaving it to the host - before 3.13 html.parser resumes
        # tokenizing after the next `>`, which resurrects markup a browser never renders.
        return self._unterminated(i + 4, self.handle_comment if report else (lambda _d: None))

    def parse_endtag(self, i):
        elem = self.cdata_elem
        if elem is not None:
            m = _raw_text_close_re(elem).match(self.rawdata, i)
            if m:
                self.handle_endtag(elem)
                self.clear_cdata_mode()
                return m.end()
        return super().parse_endtag(i)

    def parse_html_declaration(self, i):
        # Replaced wholesale so `<!...>` is resolved identically on every interpreter. Only
        # inside FOREIGN content is `<![CDATA[ ... ]]>` a CDATA section; everywhere else a
        # browser treats `<!` + junk as a BOGUS COMMENT that ends at the very first `>`, so
        # markup after that `>` is LIVE. html.parser instead consumes the whole marked section
        # in every context (and, before 3.13, raises on an unknown section keyword), which would
        # hide a real code block behind a `<![CDATA[` an author never meant as one.
        rawdata = self.rawdata
        if rawdata.startswith("<!--", i):
            return self.parse_comment(i)
        if rawdata[i:i + 9].lower() == "<!doctype":
            gt = rawdata.find(">", i + 9)
            if gt < 0:
                return self._unterminated(i + 2, self.handle_decl)
            self.handle_decl(rawdata[i + 2:gt])
            return gt + 1
        if rawdata.startswith("<![CDATA[", i) and self._in_foreign():
            j = rawdata.find("]]>", i + 9)
            if j < 0:
                return self._unterminated(i + 3, self.unknown_decl)
            self.unknown_decl(rawdata[i + 3:j])
            return j + 3
        return self.parse_bogus_comment(i)

    def _unterminated(self, start, handler):
        """A construct with no closer: a browser consumes the rest of the document."""
        if not self._final:
            return -1   # more data may still arrive; the base class re-tries
        handler(self.rawdata[start:])
        return len(self.rawdata)

    # -- element tracking -------------------------------------------------- #

    def _in_foreign(self):
        return any(t in _FOREIGN_ROOTS for (t, _r, _k) in self._stack)

    def _open_pre(self):
        for (t, rec, _k) in reversed(self._stack):
            if t == "pre":
                return rec
        return None

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        ad = _DocParser._attrs_dict(attrs)
        rec = None
        if tag == "pre":
            rec = {"attrs": ad, "start": self._off(), "inner_start": self._start_tag_end(),
                   "inner": None, "codes": [],
                   "in_kql_figure": any(k for (_t, _r, k) in self._stack)}
            self.pres.append(rec)
        elif tag == "code":
            owner = self._open_pre()
            if owner is not None:
                rec = {"attrs": ad, "start": self._off(),
                       "inner_start": self._start_tag_end(), "inner": None}
                owner["codes"].append(rec)
        # A VOID element has no content and no end tag, so it never owns a code block and never
        # needs to be popped. Keeping voids off the stack matches _DocParser and keeps a
        # void-heavy document from growing the stack (and every unmatched end tag's scan of it).
        if tag not in VOID:
            self._stack.append((tag, rec,
                                tag == "figure" and parsed_attrs_have_class(ad, "cmh-kql")))
        if tag in _RAW_TEXT_ELEMENTS:
            self.set_cdata_mode(tag)

    def handle_startendtag(self, tag, attrs):
        # HTML5: a trailing slash on a NON-void tag is ignored, so `<pre/>` opens an element
        # that still needs `</pre>` and `<textarea/>` still opens raw text.
        if tag.lower() not in VOID:
            self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        tag = tag.lower()
        end = self._off()
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] != tag:
                continue
            for (t, rec, _k) in self._stack[i + 1:]:
                if t in ("pre", "code") and rec is not None:
                    self.unclosed = True   # implicitly closed: it never got its own closer
            own = self._stack[i][1]
            if own is not None:
                own["inner"] = (own["inner_start"], end)
            del self._stack[i:]
            return
        # An end tag with no open element is ignored, exactly as a browser ignores it.

    def close(self):
        super().close()
        for (t, rec, _k) in self._stack:
            if t in ("pre", "code") and rec is not None:
                self.unclosed = True


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
        rec["codes"] = tuple(MappingProxyType(dict(c)) for c in pre["codes"])
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


def _parse_document(html):
    """A tolerant `_DocParser` pass over `html`.

    The shared entry point for helpers that accept EITHER an already-parsed document (the normal
    path - `validate()` parses once) or raw html (tests and callers holding only a string), so a
    parser-derived view of the document never needs a second, divergent notion of its structure."""
    text = html or ""
    p = _DocParser(text)
    try:
        p.feed(text)
        p.close()
    except Exception:
        pass
    return p
