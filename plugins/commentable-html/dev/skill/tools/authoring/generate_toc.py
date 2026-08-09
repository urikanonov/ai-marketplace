#!/usr/bin/env python3
"""Generate a commentable-html table of contents from document headings."""
import argparse
import html as html_lib
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tools/ root
import _atomic_io  # noqa: E402
import _browser_boundaries  # noqa: E402
import _browser_attrs  # noqa: E402

HEADING_TAGS = {"h2", "h3"}
# Every heading a browser recognizes. Only h2/h3 are LISTED, but HTML5's h1-h6 start-tag rule pops
# an open heading of ANY level, so an `<h4>` ends an open `<h2>` just as another `<h2>` does.
ALL_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
SLUG_RE = re.compile(r"[^a-z0-9]+")
# The document-overview strip doc_stats.py bakes directly under the <h1> title.
STATS_ATTR = "data-cmh-doc-stats"
# A leading author section number (e.g. "1.", "3.1", "2)") that the ordered-list TOC would
# otherwise double-number. Mirrors the runtime side-toc pattern in assets/js/82-toc.js.
SECTION_NUMBER_RE = re.compile(r"^(?:\d+(?:\.\d+)*[.)]|\d+\.\d+(?:\.\d+)*)\s+")
# The same shape, but ASCII-only, for READING the number a heading displays. JavaScript's `\d` is
# ASCII while Python's also matches every Unicode decimal digit, so without this a full-width or
# Devanagari "1." would be a section number here and not to the runtime - and because the number
# source is a WHOLE-LIST decision, one such heading would flip an entire otherwise-unnumbered
# document into doc-number mode and leave every other entry bare.
LEADING_SECTION_NUMBER_RE = re.compile(r"^(?:[0-9]+(?:\.[0-9]+)*[.)]|[0-9]+\.[0-9]+(?:\.[0-9]+)*)\s+")
SHADOW_ROOT_MODES = frozenset(("open", "closed"))


def _has_class(attrs, class_name):
    return class_name in _browser_attrs.class_tokens(attrs.get("class"))


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
        self._shadow_frames = []  # shadow/template facts parallel to stack and namespace
        self.root_depth = None
        self.root_start = None
        self.root_closed = False
        self.root_seen = False
        self.root_start_end = None
        self.ids = []                  # (element id, element start offset), in document order
        self.headings = []
        self.toc_spans = []            # spans a rewrite may replace (own end tag closed them)
        self.toc_unclosed_spans = []   # spans an ancestor's closer or EOF ended; read-only
        self._heading = None
        self._heading_index = None
        self._toc_index = None
        self._toc_start = None
        self._title_index = None
        self.title_container_end = None   # end of the top-level container holding the <h1>
        self.title_own_close = False
        self._stats_index = None
        self.stats_start = None           # start of the direct-child doc-stats overview strip
        self.stats_end = None             # end of the direct-child doc-stats overview strip
        self.stats_own_close = False

    def _truncate_stacks(self, depth):
        # EVERY close runs through here - the element's own end tag, an ANCESTOR's end tag, HTML5's
        # implicit `</p>` / `</li>`, a foreign-content breakout, and end of input - so state keyed
        # on a stack index can never be left open past the element a browser closed. Only the
        # element's OWN end tag is part of it: an ancestor's `</div>` closes it at the START of that
        # tag, so the span must not swallow it (this tool REPLACES those bytes).
        if self._heading is not None and self._heading_index >= depth:
            self._finish_heading()
        if (self._title_index is not None and self.title_container_end is None
                and depth <= self._title_index):
            self.title_own_close = self._end_tag_close and depth == self._title_index
            self.title_container_end = self._extent_end(self.title_own_close)
        if (self._stats_index is not None and self.stats_end is None
                and depth <= self._stats_index):
            self.stats_own_close = self._end_tag_close and depth == self._stats_index
            self.stats_end = self._extent_end(self.stats_own_close)
        if self._toc_start is not None and self._toc_index >= depth:
            # Only a region the browser closed with its OWN end tag has a span that can be
            # REPLACED: one an ancestor's closer (or end of input) ended runs past every following
            # sibling, and deleting it would take the document's body with it. The extent is still
            # recorded - it is the browser's - but as an UNCLOSED span the rewriter must not edit.
            own = self._end_tag_close and depth == self._toc_index
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
        del self._shadow_frames[depth:]

    def _extent_end(self, own):
        # Only the element's OWN end tag belongs to it; an ancestor's closer (or end of input)
        # ends it at that point, which is still a position AFTER the element's content.
        return (_browser_boundaries.end_tag_end(self._text, self._off())
                if (self._end_tag_close and own) else self._off())

    def _record_id(self, element_id, start):
        # One list of pairs, so the id and the offset that decides whether it survives the rewrite
        # cannot desynchronize - two parallel lists silently truncated the zip when an append site
        # updated only one of them.
        self.ids.append((element_id, start))

    @property
    def all_ids(self):
        return [element_id for element_id, _start in self.ids]

    def _finish_heading(self):
        text = re.sub(r"\s+", " ", "".join(self._heading["text_parts"])).strip()
        if text:
            self.headings.append({
                "tag": self._heading["tag"],
                "id": self._heading["id"],
                "text": text,
                "start": self._heading["start"],
                "start_text": self._heading["start_text"],
                "shadow_host": self._heading["shadow_host"],
                "toc_start": self._heading["toc_start"],
            })
        self._heading = None
        self._heading_index = None

    def _in_template(self):
        return any(frame["inert"] for frame in self._shadow_frames)

    def _skip_ancestor(self):
        return any(skip for _tag, skip in self.stack)

    def _in_shadow_tree(self):
        return any(frame["shadow"] for frame in self._shadow_frames)

    def _current_shadow_host(self):
        for frame in self._shadow_frames:
            if frame["shadow"]:
                return frame["shadow_host"]
        return None

    def _attaches_shadow_root(self, tag, attrs, ns):
        host_ns = self._ns[-1][1] if self._ns else None
        if (tag != "template" or ns != "html" or self._in_template()
                or _browser_attrs.ascii_lower(attrs.get("shadowrootmode") or "")
                not in SHADOW_ROOT_MODES
                or not self.stack or not self._shadow_frames[-1]["hostable"]
                or self._shadow_frames[-1]["shadow_used"]
                or not _browser_attrs.can_host_shadow_root(self.stack[-1][0], host_ns)):
            return False
        self._shadow_frames[-1]["shadow_used"] = True
        return True

    def _inside_root(self):
        return (self.root_depth is not None and not self.root_closed
                and len(self.stack) > self.root_depth)

    def _visit_start(self, tag, ad, ns, opens):
        # The shared browser attribute decode (CMH-VAL-21): the id this tool reads (and links
        # the table of contents at) is the id a browser gives the element.
        attrs_dict = ad
        if ns == "html":
            # HTML5's h1-h6 start tag POPS an open heading that is the CURRENT node, so
            # `<h2 id="a">A<h2 id="b">B` is two headings: without this the first one ran on and
            # swallowed the second's text, and the second's id was never listed at all. The rule
            # is STRUCTURAL - a browser pops whatever open heading is the current node - so a
            # heading this tool never LISTS (an h1/h4-h6, a cm-skip one) is popped too. The
            # validator's _DocParser reads the same boundary (CMH-VAL-21).
            if (tag in ALL_HEADING_TAGS and self.stack
                    and self.stack[-1][0] in ALL_HEADING_TAGS):
                self._truncate_stacks(len(self.stack) - 1)
        own_skip = _has_class(attrs_dict, "cm-skip")
        is_shadow = self._attaches_shadow_root(tag, attrs_dict, ns)
        inert_template = tag == "template" and ns == "html" and not is_shadow
        start = self._off()
        start_text = self.get_starttag_text() or ""
        is_toc = tag == "nav" and opens and _has_class(attrs_dict, "cm-toc")
        if (is_toc and self._toc_start is None and self._inside_root()
                and not self._in_template() and not self._in_shadow_tree()):
            self._toc_start = start
            self._toc_index = len(self.stack)

        if not self._in_template() and not self._in_shadow_tree() and not is_shadow:
            element_id = attrs_dict.get("id")
            if element_id:
                self._record_id(element_id, start)
                if element_id == "commentRoot" and not self.root_seen:
                    self.root_seen = True
                    if opens:
                        self.root_depth = len(self.stack)
                        self.root_start = start
                        self.root_start_end = start + len(start_text)
                    else:
                        self.root_closed = True

        if (tag in HEADING_TAGS and self._heading is None and self._inside_root()
                and not own_skip and not self._skip_ancestor() and not self._in_template()):
            self._heading = {
                "tag": tag,
                "id": attrs_dict.get("id"),
                "text_parts": [],
                "start": start,
                "start_text": start_text,
                "shadow_host": self._current_shadow_host(),
                "toc_start": self._toc_start,
            }
            self._heading_index = len(self.stack)

        if (self._inside_root() and not self._in_template() and not self._in_shadow_tree()
                and not self._skip_ancestor()):
            if tag == "h1" and self._title_index is None and not own_skip:
                # The title's top-level container is the direct child of #commentRoot at this
                # index, whether that is the <h1> itself or a wrapper (e.g. header.cmh-lede).
                # doc_stats.py anchors its overview strip on the same boundary.
                self._title_index = self.root_depth + 1
            if (opens and self._stats_index is None and STATS_ATTR in attrs_dict
                    and len(self.stack) == self.root_depth + 1):
                # The strip is itself cm-skip, so `own_skip` is expected here. Only the
                # direct-child strip doc_stats.py bakes under the title moves the table of
                # contents down; a deeper one already sits inside the title container.
                self._stats_index = len(self.stack)
                self.stats_start = start
        return (own_skip, inert_template, is_shadow, start, start_text)

    def _push_element(self, tag, ad, ns, info):
        own_skip, inert_template, is_shadow, start, start_text = info
        shadow_host = None
        if is_shadow:
            host = self._shadow_frames[-1]
            shadow_host = {
                "start": host["start"],
                "start_text": host["start_text"],
                "id": host["id"],
            }
        self.stack.append((tag, own_skip if not is_shadow else False))
        self._shadow_frames.append({
            "inert": inert_template,
            "shadow_used": False,
            "hostable": not is_shadow,
            "shadow": is_shadow,
            "start": start,
            "start_text": start_text,
            "id": ad.get("id"),
            "shadow_host": shadow_host,
        })

    def _visit_self_closed(self, tag, ad, ns):
        # A self-closed FOREIGN element is still an element with an id a browser gives it.
        if not self._in_template() and not self._in_shadow_tree():
            element_id = ad.get("id")
            if element_id:
                self._record_id(element_id, self._off())
                if element_id == "commentRoot" and not self.root_seen:
                    # The first matching DOM element is the runtime root even when it self-closes.
                    # It has no insertion point for a generated TOC and no heading descendants.
                    self.root_seen = True
                    self.root_closed = True

    def handle_data(self, data):
        # A nested <template>'s text is inert (a browser renders none of it), so it is not part
        # of the heading a reader sees - the same rule the validator's heading capture applies.
        if (self._heading is not None and not self._in_template()
                and self.cdata_elem not in ("script", "style")):
            self._heading["text_parts"].append(data)

    def _visit_end(self, tag, index):
        # HTML5 changes insertion mode for these end tags without popping an HTML element. A
        # same-named foreign element is real element content and still closes normally.
        return not (index >= 0 and tag in ("body", "html") and self._ns[index][1] == "html")

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
    # A `nav.cm-toc` the rewrite REPLACES is navigation chrome, not document content: its headings
    # are links to sections, and its ids die with it. Listing one invented a phantom entry pointing
    # at an anchor the rewrite deletes, and generating an id for it queued an insertion INSIDE the
    # deleted span, which corrupted the document. Only a REPLACED span is excluded - a `.cm-toc`
    # this rewrite leaves in place (one an ancestor's end tag or EOF closed, one outside
    # `#commentRoot`, one in a template or a shadow tree) still holds live headings and live ids.
    replaced = {start for start, _end in parser.toc_spans}
    used = {element_id for element_id, start in parser.ids
            if not any(span_start <= start < span_end
                       for span_start, span_end in parser.toc_spans)}
    items = []
    generated_hosts = {}
    listed_shadow_hosts = set()
    for heading in parser.headings:
        if heading["toc_start"] in replaced:
            continue
        heading_id = heading["id"]
        generated = False
        shadow_host = heading.get("shadow_host")
        anchor_generated = False
        if shadow_host is not None:
            if shadow_host["start"] in listed_shadow_hosts:
                continue
            listed_shadow_hosts.add(shadow_host["start"])
            heading_id = shadow_host["id"]
            if not heading_id:
                key = shadow_host["start"]
                heading_id = generated_hosts.get(key)
                if heading_id is None:
                    heading_id = _unique_slug(
                        (heading["id"] or heading["text"]) + "-shadow-host", used)
                    generated_hosts[key] = heading_id
                    anchor_generated = True
        elif not heading_id:
            heading_id = _unique_slug(heading["text"], used)
            generated = True
        items.append({
            "tag": heading["tag"],
            "id": heading_id,
            "text": heading["text"],
            "start": heading["start"],
            "start_text": heading["start_text"],
            "generated": generated,
            "anchor_generated": anchor_generated,
            "anchor_start": shadow_host["start"] if shadow_host is not None else None,
            "anchor_start_text": shadow_host["start_text"] if shadow_host is not None else None,
        })
    return items


def _leading_section_number(text):
    """Return the section number a heading already displays ("10.3", "2"), or "".

    Mirrors the runtime `_cmTocLeadingNumber()` in `assets/js/82-toc.js` so the in-document
    Contents list and the side navigation menu read the document's own numbering identically.
    """
    match = LEADING_SECTION_NUMBER_RE.match(text or "")
    if not match:
        return ""
    return match.group(0).strip().rstrip(".)")


def _entry_levels(items):
    """1-based menu levels, from an open-depth stack over the heading tags.

    The same rule the runtime `_cmAssignTocLevels()` applies, so a document that skips a heading
    level keeps equal-depth headings as peers instead of nesting them one step further each time.
    """
    levels = []
    stack = []
    for item in items:
        raw = int(item["tag"][1:])
        while stack and stack[-1] >= raw:
            stack.pop()
        stack.append(raw)
        levels.append(len(stack))
    return levels


def _entry_numbers(items, levels):
    """The number each entry displays, in the runtime's order of preference (CMH-TOC-11).

    The number the HEADING itself displays wins, so the Contents list never renumbers a document
    that numbers its own sections; otherwise a hierarchical number is computed from the levels.
    Which of the two applies is a WHOLE-LIST decision, so an unnumbered entry in an otherwise
    numbered document is left unnumbered rather than given a computed number that could collide.
    """
    doc_numbers = [_leading_section_number(item["text"]) for item in items]
    if any(doc_numbers):
        return doc_numbers
    numbers = []
    counters = []
    for level in levels:
        del counters[level:]
        while len(counters) < level:
            counters.append(0)
        counters[level - 1] += 1
        numbers.append(".".join(str(n) for n in counters))
    return numbers


def _render_nav(items):
    # The number is written into the entry rather than left to the ordered-list marker, which
    # numbers every `<li>` sequentially and so labelled a subsection as a top-level section while
    # the side menu called the same heading 3.1. The runtime reads this number instead of
    # computing a second one, so both surfaces show one number from one source (CMH-TOC-10).
    #
    # Two details are load-bearing. The number span is `cm-skip`, and it carries its own trailing
    # space, so it adds NO text to the offset space a reader's comments are anchored in - baking a
    # counted character into every entry would have shifted every comment saved below the contents
    # list the first time a document's TOC was regenerated. And the marker suppression is repeated
    # as an inline style rather than left to the layer stylesheet alone: the number lands in the
    # CONTENT region while the rule lives in the layer, and `content_replace.py` -> `finalize.py`
    # regenerates the nav WITHOUT swapping the layer, so a document carrying an older layer would
    # otherwise render the marker and the baked number together ("1. 1.1 Signals").
    levels = _entry_levels(items)
    numbers = _entry_numbers(items, levels)
    lines = [
        '<nav class="cm-toc" aria-label="Table of contents">',
        '  <div class="cm-toc-title">Contents</div>',
        '  <ol class="cm-toc-numbered" style="list-style: none; padding-left: 0;">',
    ]
    for item, level, number in zip(items, levels, numbers):
        class_attr = ' class="is-sub"' if level > 1 else ""
        href = html_lib.escape("#" + item["id"], quote=True)
        text = html_lib.escape(_strip_section_number(item["text"]), quote=False)
        num = ('<span class="cm-toc-num cm-skip">%s </span>'
               % html_lib.escape(number, quote=False)) if number else ""
        lines.append('    <li%s>%s<a href="%s">%s</a></li>' % (class_attr, num, href, text))
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


def _follows_after_removals(html, start, target, removals):
    """True if only whitespace and `.cm-toc` regions being deleted lie between start and target."""
    pos = _leading_ws_end(html, start)
    while pos < target:
        span = next((s for s in removals if s[0] == pos), None)
        if span is None:
            return False
        pos = _leading_ws_end(html, span[1])
    return pos == target


def _nav_anchor(html, parser, removals):
    """Return the offset the generated `nav.cm-toc` is inserted at.

    The reader meets the document's title, and the reading-time strip under it, before its table of
    contents, so the nav goes AFTER the top-level title container inside `#commentRoot` - and after
    a direct-child `doc_stats` overview strip when that strip IMMEDIATELY follows the title, which
    is the only shape `doc_stats.py` produces. "Immediately" is measured against the text this
    rewrite is about to LEAVE BEHIND, so an old `.cm-toc` sitting between the two is skipped rather
    than pinning the document at title, nav, strip forever. The TITLE is what earns the move: with
    no usable title candidate the nav keeps its top-of-`#commentRoot` placement, and a strip an
    author put anywhere else never drags the nav down to it. Three things disqualify a candidate:

    - It lands INSIDE a `.cm-toc` region this rewrite is about to delete, so the insert and the
      removal would overlap. A candidate exactly AT a removal's start is kept: those spans are
      adjacent, not overlapping, and the reverse-sorted edit application deletes the old nav before
      inserting the new one at the same offset.
    - Its element was not closed by its OWN end tag. An extent an ancestor's closer, an implicit
      close, or end of input ended is still INSIDE the open element, so the nav would land inside
      the title or the strip.
    - It would land AFTER the first section the nav lists - because the title shares a container
      with every section (a slide deck, or a document written inside one wrapper element), or
      because a section precedes the title. Either way the contents would sit below content it
      indexes. A nav that lists NO sections is held to the same rule rather than exempted from it:
      with nothing to measure against, the title container's extent is exactly as misleading, so
      an empty nav stays at the top of the root where it has always been.
    """
    first_section = min((item["start"] for item in parser.headings), default=None)

    def usable(pos, own):
        return (pos is not None and own and first_section is not None and pos <= first_section
                and not any(start < pos <= end for start, end in removals))

    title_end = parser.title_container_end
    if not usable(title_end, parser.title_own_close):
        return parser.root_start_end
    if (usable(parser.stats_end, parser.stats_own_close)
            and _follows_after_removals(html, title_end, parser.stats_start, removals)):
        return parser.stats_end
    return title_end


def _dominant_newline(html):
    crlf = html.count("\r\n")
    lf = html.count("\n") - crlf
    return "\r\n" if crlf > lf else "\n"


def _apply_edits(html, edits):
    """Apply `(start, end, replacement)` edits highest-offset-first, refusing an overlap.

    Applying in reverse document order is what keeps every span's offsets valid, but only while
    the spans are DISJOINT: an insertion that lands inside a span the same rewrite deletes runs
    first, moves the deletion boundary, and emits corrupt bytes with no error. Refuse instead.
    """
    ordered = sorted(edits, key=lambda edit: (edit[0], edit[1]))
    for previous, current in zip(ordered, ordered[1:]):
        if current[0] < previous[1]:
            raise ValueError("overlapping rewrite spans %r and %r"
                             % (previous[:2], current[:2]))
    out = html
    for start, end, replacement in reversed(ordered):
        out = out[:start] + replacement + out[end:]
    return out


def rewrite_html(html):
    """Return HTML with generated ids injected and nav.cm-toc placed under #commentRoot."""
    parser = _parse(html)
    if parser.root_start_end is None:
        raise ValueError('no element with id="commentRoot" found')
    items = _heading_items(parser)
    if any(item["anchor_start"] == parser.root_start for item in items):
        raise ValueError(
            'id="commentRoot" cannot itself host a declarative shadow TOC; '
            "place the shadow host below #commentRoot")
    newline = _dominant_newline(html)
    nav = _render_nav(items).replace("\n", newline)
    edits = []
    for item in items:
        if item["generated"]:
            pos = _id_insert_pos(item["start"], item["start_text"])
            edits.append((pos, pos, ' id="%s"' % item["id"]))
        if item["anchor_generated"]:
            pos = _id_insert_pos(item["anchor_start"], item["anchor_start_text"])
            edits.append((pos, pos, ' id="%s"' % item["id"]))
    for start, end in parser.toc_spans:
        edits.append((*_toc_removal_span(html, start, end), ""))
    anchor = _nav_anchor(html, parser, [_toc_removal_span(html, start, end)
                                        for start, end in parser.toc_spans])
    edits.append((anchor, _leading_ws_end(html, anchor), newline + nav + newline))

    return _apply_edits(html, edits)


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
            _atomic_io.atomic_write(args.file, rewritten)
            print("updated %s" % args.file)
        else:
            print(build_toc(source))
    except (OSError, ValueError) as exc:
        sys.stderr.write("generate_toc: %s\n" % exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
