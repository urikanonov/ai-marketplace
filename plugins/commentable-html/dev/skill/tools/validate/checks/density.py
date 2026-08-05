#!/usr/bin/env python3
"""Information-density authoring advisory (CMH-VAL-15).

Content conventions ask authors to build real layouts (tables, lists, figures, diffs, charts,
diagrams), not stacked walls of prose. This dedicated HTMLParser pass warns when a report/plan
section is a run of consecutive LONG paragraphs with no layout-bearing block breaking it up. It is
scoped to `#commentRoot`, ignores `cm-skip` subtrees and inert `<template>` content (but not a
declarative shadow root, which a browser renders), and is exempt for slides/board (which do not use
section cards). All findings are non-fatal warnings, matching the section-wrapping advisory
(CMH-VAL-14) precedent.
"""
import re

from .parsing import _BrowserBoundaries, _ascii_lower, _can_host_shadow_root

MIN_LONG_PARAGRAPH_CHARS = 240
MAX_CONSECUTIVE_LONG = 4

_KIND_META_NAME = "commentable-html-kind"
# The advisory is scoped to the title-bearing prose kinds; slides/board/generic and an unknown or
# missing kind are exempt.
_SCOPED_KINDS = ("report", "plan")

_VOID = frozenset(
    "area base br col embed hr img input link meta param source track wbr".split())
_HEADINGS = frozenset("h1 h2 h3 h4 h5 h6".split())
# Block-level elements that implicitly close an open <p> (the HTML5 paragraph-closing set). A
# cm-skip on one of these breaks the prose run even mid-paragraph; a cm-skip on any other
# (phrasing/void/custom inline) element inside an open paragraph is inline and only excludes its
# own text.
_BLOCK_TAGS = frozenset((
    "address article aside blockquote details dialog div dl fieldset figcaption figure footer form "
    "h1 h2 h3 h4 h5 h6 header hgroup hr main menu nav ol p pre search section table ul canvas").split())
# Layout-bearing containers: their presence breaks a prose run, and their inner paragraphs are
# layout content, not a wall.
_LAYOUT_TAGS = frozenset("table ul ol dl figure pre blockquote canvas".split())
_LAYOUT_CLASSES = ("cmh-diff", "mermaid", "cmh-mermaid", "cmh-chart", "cmh-kql")
_LAYOUT_ATTRS = ("data-cmh-checklist", "data-cm-widget")
# A declarative-shadow-root template is the one <template> a browser DOES render: it is consumed
# at parse time and its children become the host's shadow tree. Only these two modes attach one,
# so any other value (or no attribute) leaves the fragment inert.
_SHADOW_ROOT_MODES = frozenset(("open", "closed"))


def _frame(root=False, skip=False, layout=False, section=False, template=False, shadow=False):
    """The per-element contributions an open frame gives back when it closes."""
    return {"root": root, "skip": skip, "layout": layout, "section": section,
            "template": template, "shadow": shadow, "shadow_used": False}


class _DensityParser(_BrowserBoundaries):
    """The prose-density advisory's own pass over a document.

    It drives the shared handler skeleton and keeps its contribution frames parallel to the base's
    namespace stack. Its hooks say only what affects prose density; the base owns where elements
    begin and end.
    """

    def __init__(self, html, min_chars, max_run):
        # The SHARED element boundaries, not the host's: the raw-text / RCDATA set, the
        # `</name` + whitespace/`/`/`>` closer, and the EOF rules are what decide whether a
        # `<template>` written inside <title>/<textarea>/<noscript> TEXT is a tag at all, and
        # html.parser answers that differently per interpreter (CMH-VAL-21).
        super().__init__(html)
        self.min_chars = min_chars
        self.max_run = max_run
        self.kind = ""
        self._stack = []          # (tag, contrib dict)
        self.root_depth = 0
        self.skip_depth = 0
        self.layout_depth = 0
        # Indices into `_stack` of the OPEN <template> frames, innermost last. A template's
        # contents are an inert DocumentFragment a browser never renders, so the whole pass is
        # gated off inside one. Kept as indices rather than a bare counter for two reasons: the
        # innermost index IS the end-tag unwind floor, so no end tag has to rescan the stack to
        # find it, and the depth is DERIVED from the frames on the stack, so the two can never
        # drift apart. A template left open at end of input keeps the rest of the document
        # inert, exactly as a browser leaves it in the fragment.
        self._template_floors = []
        # Open declarative-shadow-root frames. Their content IS rendered, so it counts as prose,
        # but it lives in a shadow tree the document's own metadata rules do not reach.
        self.shadow_depth = 0
        self.run = 0
        # Heading stack so a nested or trailing section is labeled by its OWN heading, and a
        # headless/nested section restores the parent heading on close.
        self._sections = []       # stack of section headings (str), innermost last
        self._root_heading = ""   # heading of top-level (unsectioned) content
        self.findings = []        # section labels whose prose run reached the threshold
        self._p_prose = False     # inside a prose-level <p>
        self._p_index = None
        self._p_text = []
        self._heading_capture = False
        self._heading_index = None
        self._heading_text = []

    @property
    def current_heading(self):
        return self._sections[-1] if self._sections else self._root_heading

    @property
    def template_depth(self):
        return len(self._template_floors)

    def _template_frame(self):
        self._template_floors.append(len(self._stack))
        return _frame(template=True)

    def _truncate_stacks(self, depth):
        if self._p_index is not None and depth <= self._p_index:
            self._close_paragraph()
        if self._heading_index is not None and depth <= self._heading_index:
            self._close_heading()
        popped = self._stack[depth:]
        for _tag, contrib in reversed(popped):
            if contrib["section"]:
                # Flush/attribute the closing section's wall to it, then restore the parent
                # heading. (A section inside cm-skip was never pushed, so this never fires there.)
                self._break_run()
                if self._sections:
                    self._sections.pop()
            if contrib["root"]:
                self._break_run()
                self.root_depth -= 1
            if contrib["skip"]:
                self.skip_depth -= 1
            if contrib["layout"]:
                self.layout_depth -= 1
            if contrib["shadow"]:
                self.shadow_depth -= 1
        while self._template_floors and self._template_floors[-1] >= depth:
            self._template_floors.pop()
        super()._truncate_stacks(depth)
        del self._stack[depth:]

    def _attaches_shadow_root(self, d, ns):
        """Whether this `<template>` really becomes the parent's rendered shadow tree.

        Two conditions a browser applies, both of which decide RENDERED vs inert here. The
        `shadowrootmode` value is an ENUMERATED attribute, so it is matched ASCII-case-insensitively
        and EXACTLY - `" open"` is not `open`, and a browser leaves that template inert. And a host
        element gets only ONE declarative shadow root: a second `template[shadowrootmode]` under the
        same parent stays an ordinary inert template.
        """
        if _ascii_lower(d.get("shadowrootmode") or "") not in _SHADOW_ROOT_MODES:
            return False
        if not self._stack:
            return False        # no open host element for the shadow tree to attach to
        host_ns = self._ns[-1][1] if self._ns else None
        if ns != "html" or not _can_host_shadow_root(self._stack[-1][0], host_ns):
            return False
        host = self._stack[-1][1]
        if host.get("shadow_used"):
            return False
        host["shadow_used"] = True
        return True

    @staticmethod
    def _classes(d):
        return (d.get("class") or "").split()

    def _is_root(self, tag, d):
        return "data-cmh-content-root" in d or d.get("id") == "commentRoot"

    def _is_layout(self, tag, d):
        if tag in _LAYOUT_TAGS:
            return True
        if any(a in d for a in _LAYOUT_ATTRS):
            return True
        cls = self._classes(d)
        return any(c in cls for c in _LAYOUT_CLASSES)

    def _flush_open_paragraph(self):
        # Count an open prose paragraph before a boundary or EOF, so a paragraph whose </p> is
        # omitted (optional in HTML5, and HTMLParser does not synthesize it) is not lost.
        if self._p_prose:
            self._close_paragraph()

    def _break_run(self):
        # A boundary ends a consecutive prose run; flush any open paragraph into it first.
        self._flush_open_paragraph()
        self.run = 0

    def _note_kind(self, d):
        # Keep the FIRST kind meta (matching the main parser), so a later duplicate cannot flip
        # the scope. A template-parked copy never reaches here at all - `handle_starttag` returns
        # before the meta branch inside an inert fragment - and one inside a declarative SHADOW
        # tree is skipped too: a browser renders that content but never applies a shadow tree's
        # metadata to the document, so it must not decide whether this advisory runs.
        if self.shadow_depth:
            return
        if not self.kind and (d.get("name") or "").lower() == _KIND_META_NAME:
            self.kind = (d.get("content") or "").strip().lower()

    def _implicit_close(self, tag):
        # Markup authored inside cm-skip is excluded as one source subtree, even when an invalid
        # block child would make the browser implicitly close an outer paragraph.
        if self.skip_depth == 0:
            super()._implicit_close(tag)

    def _visit_start(self, tag, d, ns, opens):
        if self.template_depth > 0:
            # Inert fragment: nothing inside contributes prose, a heading, a section, a layout
            # break, or the kind. Only the nesting is tracked, so `</template>` lands on the
            # right frame. A nested declarative shadow root is inert too - its host is inside a
            # fragment a browser never renders, so no shadow tree is ever attached.
            return self._template_frame() if tag == "template" and ns == "html" else _frame()
        is_html_template = tag == "template" and ns == "html"
        is_shadow = is_html_template and self._attaches_shadow_root(d, ns)
        if is_html_template and not is_shadow:

            # A <template>'s contents live in a DocumentFragment a browser never renders, so the
            # element itself is invisible too: it neither counts as prose nor breaks a run (its
            # own attributes cannot make it a layout block either). A DECLARATIVE SHADOW ROOT is
            # the exception - a browser renders that content - so it falls through and is read as
            # the ordinary transparent container it displays as.
            return self._template_frame()
        if tag == "meta":
            self._note_kind(d)
        is_root = self.shadow_depth == 0 and self._is_root(tag, d)
        is_skip = "cm-skip" in self._classes(d)
        is_layout = self.root_depth > 0 and self.skip_depth == 0 and self._is_layout(tag, d)
        in_scope = self.root_depth > 0 and self.skip_depth == 0
        # A cm-skip subtree BETWEEN paragraphs (a non-commentable embedded table/widget) breaks a
        # prose run. An INLINE cm-skip inside an open paragraph must NOT: it only excludes its own
        # text (via the skip_depth gate in handle_data), keeping the surrounding prose one unit. A
        # BLOCK-level cm-skip element implicitly closes the paragraph, so it still breaks the run
        # even when the </p> was omitted.
        inline_skip_in_paragraph = self._p_prose and tag not in _BLOCK_TAGS
        entering_skip = (is_skip and self.root_depth > 0 and self.skip_depth == 0
                         and not inline_skip_in_paragraph)
        is_boundary = in_scope and (is_layout or tag in _HEADINGS or tag == "section")
        # A new paragraph, a boundary, or entering a skip block closes an open prose paragraph; a
        # boundary/skip-entry also breaks the run (a new paragraph continues it).
        if tag == "p" or is_boundary or entering_skip:
            self._flush_open_paragraph()
        if is_boundary or entering_skip:
            self.run = 0
        # A new section pushes a fresh heading frame so it is labeled by its OWN heading and a
        # nested section restores the parent heading when it closes. Gated to prose level so a
        # <section> structurally embedded in a layout block does not reframe the prose section.
        pushes_section = tag == "section" and in_scope and self.layout_depth == 0
        if pushes_section:
            self._sections.append("")
        # Only a prose-level heading (not one buried in a layout block like a <figcaption>) names
        # the current section.
        if tag in _HEADINGS and in_scope and self.layout_depth == 0:
            self._heading_capture = True
            self._heading_index = len(self._stack)
            self._heading_text = []
        # Count a paragraph only when it sits at prose level (inside root, not skip, not layout).
        if tag == "p" and in_scope and self.layout_depth == 0:
            self._p_prose = True
            self._p_index = len(self._stack)
            self._p_text = []
        return _frame(root=is_root, skip=is_skip, layout=is_layout,
                      section=pushes_section, shadow=is_shadow)

    def _push_element(self, tag, d, ns, info):
        self._stack.append((tag, info))
        if info["root"]:
            self.root_depth += 1
        if info["skip"]:
            self.skip_depth += 1
        if info["layout"]:
            self.layout_depth += 1
        if info["shadow"]:
            self.shadow_depth += 1

    def _visit_self_closed(self, tag, d, ns):
        # The start hook's run/heading effects still apply to a real foreign element, but every
        # depth contribution ends immediately because the element never remains open.
        depth = len(self._stack)
        info = self._visit_start(tag, d, ns, True)
        self._push_element(tag, d, ns, info)
        self._push_ns(tag, ns, d)
        self._truncate_stacks(depth)

    def handle_data(self, data):
        if self.template_depth > 0:
            return  # a browser renders none of a template's text
        if self._p_prose and self.skip_depth == 0 and self.layout_depth == 0:
            self._p_text.append(data)
        if self._heading_capture:
            self._heading_text.append(data)

    def _set_current_heading(self, text):
        if self._sections:
            self._sections[-1] = text
        else:
            self._root_heading = text

    def _close_heading(self):
        self._set_current_heading("".join(self._heading_text).strip())
        self._heading_capture = False
        self._heading_index = None
        self._heading_text = []

    def _close_paragraph(self):
        text = re.sub(r"\s+", " ", "".join(self._p_text)).strip()
        self._p_prose = False
        self._p_index = None
        self._p_text = []
        if len(text) >= self.min_chars:
            self.run += 1
            # The equality fires exactly once per continuous run (when it first reaches the
            # threshold), so each distinct wall is reported once. Two genuine walls in the same
            # section (separated by a layout block or an intervening child section) are distinct
            # problems and are both reported.
            if self.run == self.max_run:
                self.findings.append(self.current_heading or "(untitled section)")
        else:
            # A short paragraph interrupts consecutiveness of long ones; reset without recursing
            # back through _break_run (the paragraph is already closed).
            self.run = 0

def check_density(html, min_chars=MIN_LONG_PARAGRAPH_CHARS, max_run=MAX_CONSECUTIVE_LONG):
    """Return (errors, warnings). Warn once per report/plan section whose content is a run of
    `max_run` or more consecutive long paragraphs with no layout-bearing block. Only report/plan
    are checked (slides/board/generic/unknown are exempt); a parse failure degrades to no findings.
    All findings are warnings."""
    p = _DensityParser(html, min_chars, max_run)
    try:
        p.parse_document(html)
        p._flush_open_paragraph()  # count a paragraph whose </p> and enclosing tags are all omitted
    except Exception:
        return [], []
    if p.kind not in _SCOPED_KINDS:
        return [], []
    warnings = []
    for label in p.findings:
        warnings.append(
            'section "%s" is a wall of %d or more consecutive long paragraphs with no table, '
            "list, figure, diff, chart, or diagram to break it up - author a real layout so it is "
            "skimmable (see references/content-conventions.md)" % (label, max_run))
    return [], warnings
