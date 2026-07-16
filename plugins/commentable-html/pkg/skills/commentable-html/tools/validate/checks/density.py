#!/usr/bin/env python3
"""Information-density authoring advisory (CMH-VAL-15).

Content conventions ask authors to build real layouts (tables, lists, figures, diffs, charts,
diagrams), not stacked walls of prose. This dedicated HTMLParser pass warns when a report/plan
section is a run of consecutive LONG paragraphs with no layout-bearing block breaking it up. It is
scoped to `#commentRoot`, ignores `cm-skip` subtrees, and is exempt for slides/board (which do not
use section cards). All findings are non-fatal warnings, matching the section-wrapping advisory
(CMH-VAL-14) precedent.
"""
from html.parser import HTMLParser

MIN_LONG_PARAGRAPH_CHARS = 240
MAX_CONSECUTIVE_LONG = 4

_KIND_META_NAME = "commentable-html-kind"
_EXEMPT_KINDS = ("slides", "board")

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
        self.current_heading = ""
        self.findings = []        # section labels whose prose run reached the threshold
        self._p_prose = False     # inside a prose-level <p>
        self._p_text = []
        self._heading_capture = False
        self._heading_text = []

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

    def _break_run(self):
        self.run = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        d = self._attrs(attrs)
        if tag == "meta" and (d.get("name") or "").lower() == _KIND_META_NAME:
            self.kind = (d.get("content") or "").strip().lower()
        is_root = self._is_root(tag, d)
        is_skip = "cm-skip" in self._classes(d)
        is_layout = self.root_depth > 0 and self.skip_depth == 0 and self._is_layout(tag, d)
        # A layout block, a heading, or a <section> boundary breaks a consecutive prose run.
        if self.root_depth > 0 and self.skip_depth == 0 and (is_layout or tag in _HEADINGS or tag == "section"):
            self._break_run()
        if tag in _HEADINGS and self.root_depth > 0 and self.skip_depth == 0:
            self._heading_capture = True
            self._heading_text = []
        # Count a paragraph only when it sits at prose level (inside root, not skip, not layout).
        if tag == "p" and self.root_depth > 0 and self.skip_depth == 0 and self.layout_depth == 0:
            self._p_prose = True
            self._p_text = []
        if tag in _VOID:
            return
        self._stack.append((tag, {"root": is_root, "skip": is_skip, "layout": is_layout}))
        if is_root:
            self.root_depth += 1
        if is_skip:
            self.skip_depth += 1
        if is_layout:
            self.layout_depth += 1

    def handle_startendtag(self, tag, attrs):
        tag = tag.lower()
        d = self._attrs(attrs)
        if tag == "meta" and (d.get("name") or "").lower() == _KIND_META_NAME:
            self.kind = (d.get("content") or "").strip().lower()

    def handle_data(self, data):
        if self._p_prose:
            self._p_text.append(data)
        if self._heading_capture:
            self._heading_text.append(data)

    def _close_paragraph(self):
        text = "".join(self._p_text).strip()
        self._p_prose = False
        self._p_text = []
        if len(text) >= self.min_chars:
            self.run += 1
            if self.run == self.max_run:
                self.findings.append(self.current_heading or "(untitled section)")
        else:
            # A short paragraph interrupts consecutiveness of long ones.
            self._break_run()

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "p" and self._p_prose:
            self._close_paragraph()
        if tag in _HEADINGS and self._heading_capture:
            self.current_heading = "".join(self._heading_text).strip()
            self._heading_capture = False
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                popped = self._stack[i:]
                del self._stack[i:]
                for _t, contrib in reversed(popped):
                    if contrib["root"]:
                        self.root_depth -= 1
                        self._break_run()  # leaving the content root ends any open run
                    if contrib["skip"]:
                        self.skip_depth -= 1
                    if contrib["layout"]:
                        self.layout_depth -= 1
                break
        if tag == "section" and self.root_depth > 0:
            self._break_run()  # a section boundary ends the run


def check_density(html, min_chars=MIN_LONG_PARAGRAPH_CHARS, max_run=MAX_CONSECUTIVE_LONG):
    """Return (errors, warnings). Warn once per report/plan section whose content is a run of
    `max_run` or more consecutive long paragraphs with no layout-bearing block. slides/board are
    exempt; a parse failure degrades to no findings. All findings are warnings."""
    p = _DensityParser(min_chars, max_run)
    try:
        p.feed(html)
        p.close()
    except Exception:
        return [], []
    if p.kind in _EXEMPT_KINDS:
        return [], []
    warnings = []
    for label in p.findings:
        warnings.append(
            'section "%s" is a wall of %d or more consecutive long paragraphs with no table, '
            "list, figure, diff, chart, or diagram to break it up - author a real layout so it is "
            "skimmable (see references/content-conventions.md)" % (label, max_run))
    return [], warnings
