#!/usr/bin/env python3
"""Generate a commentable-html table of contents from document headings."""
import argparse
import html as html_lib
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tools/ root
import _browser_boundaries  # noqa: E402

HEADING_TAGS = {"h2", "h3"}
VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}
SLUG_RE = re.compile(r"[^a-z0-9]+")
# A leading author section number (e.g. "1.", "3.1", "2)") that the ordered-list TOC would
# otherwise double-number. Mirrors the runtime side-toc pattern in assets/js/82-toc.js.
SECTION_NUMBER_RE = re.compile(r"^(?:\d+(?:\.\d+)*[.)]|\d+\.\d+(?:\.\d+)*)\s+")


def _has_class(attrs, class_name):
    return class_name in set((attrs.get("class") or "").split())


class _TocParser(_browser_boundaries.BrowserBoundaries):
    """Collect the headings a reader sees, and the extent of any existing `nav.cm-toc`.

    Derives from the SHARED element boundaries (CMH-VAL-21), so a heading, an id or a `nav` a
    reader only SEES quoted inside a raw-text body (`<textarea>`, `<title>`, `<noscript>`, ...),
    inside a comment or behind a bogus `<![CDATA[` marked section contributes no element - the same
    view the validator's heading and id checks take, on every interpreter. The element stack runs
    parallel to the shared namespace stack, so no truncation path can leave the two out of step.
    """

    def __init__(self, text):
        super().__init__(text)
        self._text = text
        self.stack = []
        self.root_depth = None
        self.root_closed = False
        self.root_start_end = None
        self.all_ids = []
        self.headings = []
        self.toc_spans = []            # spans a rewrite may replace (own end tag closed them)
        self.toc_unclosed_spans = []   # spans an ancestor's closer or EOF ended; read-only
        self._heading = None
        self._heading_index = None
        self._toc_index = None
        self._toc_start = None
        self._end_tag = False     # the truncation below came from an end TAG, not an implicit close

    def _truncate_stacks(self, depth):
        # EVERY close runs through here - the element's own end tag, an ANCESTOR's end tag, HTML5's
        # implicit `</p>` / `</li>`, a foreign-content breakout, and end of input - so state keyed
        # on a stack index can never be left open past the element a browser closed. Only the
        # element's OWN end tag is part of it: an ancestor's `</div>` closes it at the START of that
        # tag, so the span must not swallow it (this tool REPLACES those bytes).
        if self._heading is not None and self._heading_index >= depth:
            self._finish_heading()
        if self._toc_start is not None and self._toc_index >= depth:
            # Only a region the browser closed with its OWN end tag has a span that can be
            # REPLACED: one an ancestor's closer (or end of input) ended runs past every following
            # sibling, and deleting it would take the document's body with it. The extent is still
            # recorded - it is the browser's - but as an UNCLOSED span the rewriter must not edit.
            own = self._end_tag and depth == self._toc_index
            span = (self._toc_start,
                    _browser_boundaries.end_tag_end(self._text, self._off()) if own
                    else self._off())
            (self.toc_spans if own else self.toc_unclosed_spans).append(span)
            self._toc_start = None
            self._toc_index = None
        if self.root_depth is not None and depth <= self.root_depth:
            # Closing #commentRoot (or an ancestor of it) ends the root subtree for good, so
            # headings/refs in a later sibling container are not collected.
            self.root_closed = True
        super()._truncate_stacks(depth)
        del self.stack[depth:]

    def _finish_heading(self):
        text = re.sub(r"\s+", " ", "".join(self._heading["text_parts"])).strip()
        if text:
            self.headings.append({
                "tag": self._heading["tag"],
                "id": self._heading["id"],
                "text": text,
                "start": self._heading["start"],
                "start_text": self._heading["start_text"],
            })
        self._heading = None
        self._heading_index = None

    def _in_template(self):
        return any(tag == "template" for tag, _skip in self.stack)

    def _skip_ancestor(self):
        return any(skip for _tag, skip in self.stack)

    def _inside_root(self):
        return (self.root_depth is not None and not self.root_closed
                and len(self.stack) > self.root_depth)

    def handle_starttag(self, tag, attrs):
        tag = self._browser_tag(tag)
        # The shared browser attribute decode (CMH-VAL-21): the id this tool reads (and links
        # the table of contents at) is the id a browser gives the element.
        attrs_dict = self._attrs_dict(tag, attrs)
        ns = self._child_namespace(tag, attrs_dict)
        if ns == "html":
            self._implicit_close(tag)
        own_skip = _has_class(attrs_dict, "cm-skip")
        opens = tag not in VOID_TAGS or ns != "html"
        start = self._off()
        start_text = self.get_starttag_text() or ""
        if (tag == "nav" and opens and self._toc_start is None and self._inside_root()
                and not self._in_template() and _has_class(attrs_dict, "cm-toc")):
            self._toc_start = start
            self._toc_index = len(self.stack)

        if not self._in_template():
            element_id = attrs_dict.get("id")
            if element_id:
                self.all_ids.append(element_id)
                if element_id == "commentRoot" and self.root_start_end is None:
                    self.root_depth = len(self.stack)
                    self.root_start_end = start + len(start_text)

        if (tag in HEADING_TAGS and self._heading is None and self._inside_root()
                and not own_skip and not self._skip_ancestor() and not self._in_template()):
            self._heading = {
                "tag": tag,
                "id": attrs_dict.get("id"),
                "text_parts": [],
                "start": start,
                "start_text": start_text,
            }
            self._heading_index = len(self.stack)

        if opens:
            self.stack.append((tag, own_skip))
            self._push_ns(tag, ns, attrs_dict)
        self._enter_raw_text(tag, ns)

    def handle_startendtag(self, tag, attrs):
        # HTML5 ignores a trailing slash on a non-void HTML tag (it opens an element) and on a VOID
        # one (it was already terminal), so both go through the start-tag path - which is also
        # where the implicit `</p>` close lives. Only a FOREIGN element really self-closes.
        tag = self._browser_tag(tag)
        attrs_dict = self._attrs_dict(tag, attrs)
        if not self._foreign_self_closes(self._child_namespace(tag, attrs_dict)):
            self.handle_starttag(tag, attrs)
            return
        if not self._in_template():
            element_id = attrs_dict.get("id")
            if element_id:
                self.all_ids.append(element_id)

    def handle_data(self, data):
        # A nested <template>'s text is inert (a browser renders none of it), so it is not part
        # of the heading a reader sees - the same rule the validator's heading capture applies.
        if self._heading is not None and not self._in_template():
            self._heading["text_parts"].append(data)

    def handle_endtag(self, tag):
        tag = self._browser_tag(tag)
        for index in range(len(self.stack) - 1, self._end_tag_floor(tag) - 1, -1):
            if self.stack[index][0] == tag:
                self._end_tag = True
                try:
                    self._truncate_stacks(index)
                finally:
                    self._end_tag = False
                return
        # An end tag with no open element is ignored, exactly as a browser ignores it.

    def close(self):
        super().close()
        # A browser renders a heading (or a `nav.cm-toc`) still open at end of input, so it is
        # finalized rather than dropped.
        self._truncate_stacks(0)


def _parse(html):
    parser = _TocParser(html)
    parser.parse_document(html)
    return parser


def _slug(text):
    value = SLUG_RE.sub("-", text.lower()).strip("-")
    return value or "section"


def _strip_section_number(text):
    """Drop a leading author section number so the ordered-list TOC is not double-numbered.

    "1. Executive summary" -> "Executive summary"; "3.1 Goals" -> "Goals"; a title with no
    section-number prefix (e.g. "Overview", "2024 review") is returned unchanged.
    """
    return SECTION_NUMBER_RE.sub("", text, count=1)


def _unique_slug(text, used):
    base = _slug(text)
    candidate = base
    suffix = 2
    while candidate in used:
        candidate = "%s-%d" % (base, suffix)
        suffix += 1
    used.add(candidate)
    return candidate


def _heading_items(parser):
    used = set(parser.all_ids)
    items = []
    for heading in parser.headings:
        heading_id = heading["id"]
        generated = False
        if not heading_id:
            heading_id = _unique_slug(heading["text"], used)
            generated = True
        items.append({
            "tag": heading["tag"],
            "id": heading_id,
            "text": heading["text"],
            "start": heading["start"],
            "start_text": heading["start_text"],
            "generated": generated,
        })
    return items


def _render_nav(items):
    lines = [
        '<nav class="cm-toc" aria-label="Table of contents">',
        '  <div class="cm-toc-title">Contents</div>',
        "  <ol>",
    ]
    for item in items:
        class_attr = ' class="is-sub"' if item["tag"] == "h3" else ""
        href = html_lib.escape("#" + item["id"], quote=True)
        text = html_lib.escape(_strip_section_number(item["text"]), quote=False)
        lines.append('    <li%s><a href="%s">%s</a></li>' % (class_attr, href, text))
    lines.extend(["  </ol>", "</nav>"])
    return "\n".join(lines)


def build_toc(html):
    """Return a nav.cm-toc snippet for h2 and h3 headings inside #commentRoot."""
    return _render_nav(_heading_items(_parse(html)))


_TOC_ANCHOR_RE = re.compile(r"(<a\b[^>]*>)(.*?)(</a>)", re.IGNORECASE | re.DOTALL)


def strip_toc_numbers(html):
    """De-duplicate an existing author `nav.cm-toc` that uses an ordered list.

    Strips a redundant leading section number from each `<a>` label inside an author
    `.cm-toc` whose list is an `<ol>`, so the ordered list supplies the single number instead
    of double-numbering. A `.cm-toc` built from a `<ul>` (where the author supplies the number
    deliberately) is left untouched. Returns (new_html, stripped_count).
    """
    parser = _parse(html)
    if not parser.toc_spans:
        return html, 0
    counter = {"n": 0}

    def _strip_anchor(match):
        inner = match.group(2)
        new_inner = _strip_section_number(inner)
        if new_inner != inner:
            counter["n"] += 1
        return match.group(1) + new_inner + match.group(3)

    out = html
    for start, end in sorted(parser.toc_spans, reverse=True):
        segment = out[start:end]
        if "<ol" not in segment.lower():
            continue
        out = out[:start] + _TOC_ANCHOR_RE.sub(_strip_anchor, segment) + out[end:]
    return out, counter["n"]


def _id_insert_pos(start, start_text):
    gt = start_text.rfind(">")
    if gt == -1:
        return start + len(start_text)
    before_gt = start_text[:gt].rstrip()
    if before_gt.endswith("/"):
        return start + len(before_gt) - 1
    return start + gt


def _leading_ws_end(html, start):
    end = start
    while end < len(html) and html[end] in " \t\r\n":
        end += 1
    return end


def _toc_removal_span(html, start, end):
    return start, _leading_ws_end(html, end)


def _dominant_newline(html):
    crlf = html.count("\r\n")
    lf = html.count("\n") - crlf
    return "\r\n" if crlf > lf else "\n"


def rewrite_html(html):
    """Return HTML with generated ids injected and nav.cm-toc placed under #commentRoot."""
    parser = _parse(html)
    if parser.root_start_end is None:
        raise ValueError('no element with id="commentRoot" found')
    items = _heading_items(parser)
    newline = _dominant_newline(html)
    nav = _render_nav(items).replace("\n", newline)
    edits = []
    for item in items:
        if item["generated"]:
            pos = _id_insert_pos(item["start"], item["start_text"])
            edits.append((pos, pos, ' id="%s"' % item["id"]))
    for start, end in parser.toc_spans:
        edits.append((*_toc_removal_span(html, start, end), ""))
    edits.append((parser.root_start_end, _leading_ws_end(html, parser.root_start_end), newline + nav + newline))

    out = html
    for start, end, replacement in sorted(edits, key=lambda edit: (edit[0], edit[1]), reverse=True):
        out = out[:start] + replacement + out[end:]
    return out


def main(argv):
    parser = argparse.ArgumentParser(description="Generate a commentable-html table of contents.")
    parser.add_argument("file", help="HTML file to read")
    parser.add_argument("--in-place", action="store_true", help="rewrite the file with the generated table of contents")
    args = parser.parse_args(argv[1:])

    if not os.path.exists(args.file):
        sys.stderr.write("generate_toc: file not found: %s\n" % args.file)
        return 1
    try:
        with open(args.file, "r", encoding="utf-8", newline="") as handle:
            source = handle.read()
        if args.in_place:
            rewritten = rewrite_html(source)
            with open(args.file, "w", encoding="utf-8", newline="") as handle:
                handle.write(rewritten)
            print("updated %s" % args.file)
        else:
            print(build_toc(source))
    except (OSError, ValueError) as exc:
        sys.stderr.write("generate_toc: %s\n" % exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
