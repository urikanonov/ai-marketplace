#!/usr/bin/env python3
"""Information-density authoring advisory (CMH-VAL-15).

Content conventions ask authors to build real layouts (tables, lists, figures, diffs, charts,
diagrams), not stacked walls of prose. This dedicated HTMLParser pass warns when a report/plan
section is a run of consecutive LONG paragraphs with no layout-bearing block breaking it up. It is
scoped to `#commentRoot`, ignores `cm-skip` subtrees, and is exempt for slides/board (which do not
use section cards). All findings are non-fatal warnings, matching the section-wrapping advisory
(CMH-VAL-14) precedent.
"""
import re
from html.parser import HTMLParser

MIN_LONG_PARAGRAPH_CHARS = 240
MAX_CONSECUTIVE_LONG = 4

_KIND_META_NAME = "commentable-html-kind"
# The advisory is scoped to the title-bearing prose kinds; slides/board/generic and an unknown or
# missing kind are exempt.
_SCOPED_KINDS = ("report", "plan")

_VOID = frozenset(
    "area base br col embed hr img input link meta param source track wbr".split())
_HEADINGS = frozenset("h1 h2 h3 h4 h5 h6".split())
# Layout-bearing containers: their presence breaks a prose run, and their inner paragraphs are
# layout content, not a wall.
_LAYOUT_TAGS = frozenset("table ul ol dl figure pre blockquote canvas".split())
_LAYOUT_CLASSES = ("cmh-diff", "mermaid", "cmh-mermaid", "cmh-chart", "cmh-kql")
_LAYOUT_ATTRS = ("data-cmh-checklist", "data-cm-widget")


class _DensityParser(HTMLParser):
    def __init__(self, min_chars, max_run):
        super().__init__(convert_charrefs=True)
        self.min_chars = min_chars
        self.max_run = max_run
        self.kind = ""
        self._stack = []          # (tag, contrib dict)
        self.root_depth = 0
        self.skip_depth = 0
        self.layout_depth = 0
        self.run = 0
        # Section identity/heading stack so a nested or trailing section is labeled by its OWN
        # heading, and a headless section restores the parent heading on close. `_section_id`
        # keys per-section dedup so two distinct walls (even two headless ones) are both reported.
        self._sections = []       # stack of [section_id, heading]
        self._next_section_id = 0
        self._root_heading = ""   # heading of top-level (unsectioned) content
        self.findings = []        # (section_id, label) whose prose run reached the threshold
        self._p_prose = False     # inside a prose-level <p>
        self._p_text = []
        self._heading_capture = False
        self._heading_text = []

    @property
    def current_heading(self):
        return self._sections[-1][1] if self._sections else self._root_heading

    @property
    def _current_section_id(self):
        return self._sections[-1][0] if self._sections else 0

    def _attrs(self, attrs):
        d = {}
        for k, v in attrs:
            kl = (k or "").lower()
            if kl not in d:
                d[kl] = v if v is not None else ""
        return d

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
        # Keep the FIRST kind meta (matching the main parser), so a later duplicate or an inert
        # template copy cannot flip the scope.
        if not self.kind and (d.get("name") or "").lower() == _KIND_META_NAME:
            self.kind = (d.get("content") or "").strip().lower()

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        d = self._attrs(attrs)
        if tag == "meta":
            self._note_kind(d)
        is_root = self._is_root(tag, d)
        is_skip = "cm-skip" in self._classes(d)
        is_layout = self.root_depth > 0 and self.skip_depth == 0 and self._is_layout(tag, d)
        in_scope = self.root_depth > 0 and self.skip_depth == 0
        # A cm-skip subtree BETWEEN paragraphs (a non-commentable embedded table/widget) breaks a
        # prose run. An INLINE cm-skip inside an open paragraph must NOT: it only excludes its own
        # text (via the skip_depth gate in handle_data), keeping the surrounding prose one unit.
        entering_skip = is_skip and self.root_depth > 0 and self.skip_depth == 0 and not self._p_prose
        is_boundary = in_scope and (is_layout or tag in _HEADINGS or tag == "section")
        # A new paragraph, a boundary, or entering a skip block closes an open prose paragraph; a
        # boundary/skip-entry also breaks the run (a new paragraph continues it).
        if tag == "p" or is_boundary or entering_skip:
            self._flush_open_paragraph()
        if is_boundary or entering_skip:
            self.run = 0
        # A new section pushes a fresh (id, heading) frame so it is labeled by its OWN heading and
        # a nested section restores the parent heading when it closes. Gated to prose level so a
        # <section> structurally embedded in a layout block does not reframe the prose section.
        pushes_section = tag == "section" and in_scope and self.layout_depth == 0
        if pushes_section:
            self._next_section_id += 1
            self._sections.append([self._next_section_id, ""])
        # Only a prose-level heading (not one buried in a layout block like a <figcaption>) names
        # the current section.
        if tag in _HEADINGS and in_scope and self.layout_depth == 0:
            self._heading_capture = True
            self._heading_text = []
        # Count a paragraph only when it sits at prose level (inside root, not skip, not layout).
        if tag == "p" and in_scope and self.layout_depth == 0:
            self._p_prose = True
            self._p_text = []
        if tag in _VOID:
            return
        self._stack.append((tag, {"root": is_root, "skip": is_skip, "layout": is_layout,
                                  "section": pushes_section}))
        if is_root:
            self.root_depth += 1
        if is_skip:
            self.skip_depth += 1
        if is_layout:
            self.layout_depth += 1

    def handle_data(self, data):
        if self._p_prose and self.skip_depth == 0 and self.layout_depth == 0:
            self._p_text.append(data)
        if self._heading_capture:
            self._heading_text.append(data)

    def _set_current_heading(self, text):
        if self._sections:
            self._sections[-1][1] = text
        else:
            self._root_heading = text

    def _close_paragraph(self):
        text = re.sub(r"\s+", " ", "".join(self._p_text)).strip()
        self._p_prose = False
        self._p_text = []
        if len(text) >= self.min_chars:
            self.run += 1
            if self.run == self.max_run:
                key = self._current_section_id
                label = self.current_heading or "(untitled section)"
                if not any(sid == key for sid, _ in self.findings):
                    self.findings.append((key, label))
        else:
            # A short paragraph interrupts consecutiveness of long ones; reset without recursing
            # back through _break_run (the paragraph is already closed).
            self.run = 0

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "p" and self._p_prose:
            self._close_paragraph()
        if tag in _HEADINGS and self._heading_capture:
            self._set_current_heading("".join(self._heading_text).strip())
            self._heading_capture = False
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                popped = self._stack[i:]
                del self._stack[i:]
                for _t, contrib in reversed(popped):
                    if contrib["section"]:
                        # Flush/attribute the closing section's wall to it, then restore the parent
                        # heading. (A section inside cm-skip was never pushed, so this never fires
                        # there.)
                        self._break_run()
                        if self._sections:
                            self._sections.pop()
                    if contrib["root"]:
                        self._break_run()  # leaving the content root ends any open run
                        self.root_depth -= 1
                    if contrib["skip"]:
                        self.skip_depth -= 1
                    if contrib["layout"]:
                        self.layout_depth -= 1
                break


def check_density(html, min_chars=MIN_LONG_PARAGRAPH_CHARS, max_run=MAX_CONSECUTIVE_LONG):
    """Return (errors, warnings). Warn once per report/plan section whose content is a run of
    `max_run` or more consecutive long paragraphs with no layout-bearing block. Only report/plan
    are checked (slides/board/generic/unknown are exempt); a parse failure degrades to no findings.
    All findings are warnings."""
    p = _DensityParser(min_chars, max_run)
    try:
        p.feed(html)
        p.close()
        p._flush_open_paragraph()  # count a paragraph whose </p> and enclosing tags are all omitted
    except Exception:
        return [], []
    if p.kind not in _SCOPED_KINDS:
        return [], []
    warnings = []
    for _section_id, label in p.findings:
        warnings.append(
            'section "%s" is a wall of %d or more consecutive long paragraphs with no table, '
            "list, figure, diff, chart, or diagram to break it up - author a real layout so it is "
            "skimmable (see references/content-conventions.md)" % (label, max_run))
    return [], warnings
