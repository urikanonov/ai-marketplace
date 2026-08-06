#!/usr/bin/env python3
"""Carry the vendored rich-libraries payload only in documents that can actually use it.

`cmhVendoredRichLibs` is a gzip+base64 bundle of mermaid and Chart.js that the OFFLINE EXPORT
inlines so a shared file renders diagrams and charts with no network. It was stamped into the
HEAD of every document unconditionally: measured on the shipped examples it is 1,363 KB, 55 to
61 percent of a 2.3 MB file, and it landed on line 7 - so a prose-and-code review document paid
for a renderer it could never call, and any tool that reads the head of the file hit a
megabyte-long line immediately.

This module decides, keeps, drops, and (re-)places that payload. Two properties matter:

1. DETECTION IS SCOPED TO THE CONTENT REGION. The built review layer's own JavaScript contains
   `pre.mermaid, div.mermaid` and the chart canvas selectors as literal strings (they are declared
   once in `assets/js/03-selectors.js`), so a whole-document scan matches EVERY document and the
   feature silently becomes a no-op. Only the authored fragment between the CONTENT markers counts.
2. THE DECISION IS RE-EVALUATED, NOT MADE ONCE. A document that gains a diagram after it was
   stripped must get the payload back, or its offline export breaks. `apply` therefore both
   removes and restores, and finalize runs it on every write-back.

The selector set is deliberately the SAME one the runtime uses to decide whether it needs the
bundle: `68-export-offline.js` (`_offlineLiveDocNeedsRichLibs` / `_offlineDocUsesMermaid` /
`_offlineDocUsesCharts`) queries the shared constants declared in `assets/js/03-selectors.js`, and
so does the live chart renderer in `assets/js/30-images.js`. If the two ever disagree, a document
could ship without a payload its exporter then demands, so a test pins them together.
"""
import os
import re
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tools/ root
import _toolpath  # noqa: E402
_toolpath.ensure()
import _atomic_io  # noqa: E402
import _browser_attrs  # noqa: E402
import new_document  # noqa: E402

BLOB_ID = "cmhVendoredRichLibs"

RUNTIME_SELECTORS = ("pre.mermaid", "div.mermaid", "figure.chart canvas", "canvas.cmh-chart",
                     "canvas[data-cmh-chart-points]", "canvas[data-cmh-chart-source]")

USES = "uses"
UNUSED = "unused"
UNKNOWN = "unknown"

# Void elements never open a scope, so they must not be pushed onto the ancestor stack.
_VOID = frozenset((
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
    "param", "source", "track", "wbr"))


class _DocScan(_browser_attrs.BrowserTagNames):
    """One parser pass that answers everything this module needs.

    A regex CANNOT do this correctly, and the difference is not academic - review found three
    real false negatives and one case of DATA LOSS in the regex version:

    - `<canvas class=cmh-chart>` (CSS does not require quotes) was missed.
    - `<canvas title="A > B" class="cmh-chart">` was missed, because a `[^>]*` scan stops at
      the `>` inside the quoted attribute and never reaches the class.
    - A literal `</main>` inside an HTML COMMENT truncated the scan region, hiding everything
      after it.
    - Worst: a document DOCUMENTING this feature can show the payload element as a
      commented-out example. A regex matched that comment and DELETED authored content.

    A false negative strips a payload the document's own offline export then demands and fails
    on; deleting authored content is worse still. So use the standard-library tokenizer, which
    is quote-aware, comment-aware, and treats `<script>` content as raw text - the same reading
    a browser gives, which is what the runtime selectors are evaluated against.
    """

    def __init__(self, html):
        _browser_attrs.BrowserTagNames.__init__(self, convert_charrefs=False)
        self._html = html
        self._line_offsets = [0]
        for line in html.split("\n")[:-1]:
            self._line_offsets.append(self._line_offsets[-1] + len(line) + 1)
        self._stack = []
        self.root_span = None          # inner span of <main id="commentRoot">
        self.blob_spans = []           # outer spans of payload <script>s OUTSIDE the root
        self.uses = False
        self.body_end = None           # offset of the REAL </body>, parser-recorded
        self._root_depth = None
        self._root_inner_start = None
        self._blob_start = None
        self._pending_blob = False
        self._root_has_chart_figure = False
        self._root_has_canvas = False

    # -- offsets -------------------------------------------------------------
    def _offset(self):
        line, col = self.getpos()
        return self._line_offsets[line - 1] + col

    def _end_of_current_tag(self):
        """Offset just past the tag the parser is reporting."""
        text = self.get_starttag_text() or ""
        return self._offset() + len(text)

    # -- handlers ------------------------------------------------------------
    def handle_starttag(self, tag, attrs):
        tag = self._browser_tag(tag)
        attrs = dict(attrs)
        classes = _browser_attrs.class_tokens(attrs.get("class"))
        if tag == "main" and attrs.get("id") == "commentRoot" and self._root_inner_start is None:
            self._root_inner_start = self._end_of_current_tag()
            self._root_depth = len(self._stack)
        if tag == "script" and attrs.get("id") == BLOB_ID and not self._in_root():
            # Only a script OUTSIDE the content root can be the infrastructure payload. An
            # authored document may legitimately contain one as an EXAMPLE inside its content;
            # treating that as the payload and cutting it out is silent data loss (review found
            # exactly that, twice - once via an HTML comment, once as a real authored element).
            self._blob_start = self._offset()
            self._pending_blob = True
        if self._in_root():
            if tag in ("pre", "div") and "mermaid" in classes:
                self.uses = True
            elif tag == "figure" and "chart" in classes:
                self._root_has_chart_figure = True
            elif tag == "canvas":
                self._root_has_canvas = True
                if "cmh-chart" in classes:
                    self.uses = True
                elif any(t == "figure" and "chart" in c for t, c in self._stack):
                    self.uses = True
                elif any(name in ("data-cmh-chart-points", "data-cmh-chart-source") for name in attrs):
                    # The runtime's own chart selector list (assets/js/03-selectors.js) includes
                    # `canvas[data-cmh-chart-points], canvas[data-cmh-chart-source]`: those are the
                    # canvases the LIVE renderer draws, with or without the `cmh-chart` class, and
                    # the exporter provisions the library for exactly the same set. This is now
                    # parity with the runtime, not the deliberate superset it used to be.
                    self.uses = True
        if tag not in _VOID:
            self._stack.append((tag, classes))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        tag = self._browser_tag(tag)
        if tag not in _VOID and self._stack and self._stack[-1][0] == tag:
            self._stack.pop()

    def handle_endtag(self, tag):
        tag = self._browser_tag(tag)
        if tag == "script" and self._pending_blob:
            # Find the REAL end of the closing tag rather than assuming `len("</script>")`:
            # `</script   >` is valid and a hardcoded length would leave orphaned bytes behind
            # when the span is cut out.
            close = self._html.find(">", self._offset())
            end = (close + 1) if close != -1 else (self._offset() + len("</script>"))
            self.blob_spans.append((self._blob_start, end))
            self._pending_blob = False
        if tag == "body":
            self.body_end = self._offset()
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                if (tag == "main" and self._root_depth is not None
                        and i == self._root_depth and self.root_span is None):
                    self.root_span = (self._root_inner_start, self._offset())
                del self._stack[i:]
                return

    def _in_root(self):
        return self._root_inner_start is not None and self.root_span is None


def _scan(html):
    scan = _DocScan(html)
    try:
        scan.feed(html)
        scan.close()
    except Exception:
        return None
    if scan.root_span is None and scan._root_inner_start is not None:
        # An UNCLOSED content root: a browser closes it at end of input, so recover the same way
        # rather than reporting UNKNOWN and refusing to act on a document that renders fine.
        scan.root_span = (scan._root_inner_start, len(html))
    if scan.root_span is not None and not scan.uses:
        # Nesting-TOLERANT fallback. `figure.chart canvas` is a descendant selector, but a
        # browser REPAIRS misnested markup (`<p><figure class="chart"></p><canvas></canvas>`
        # puts the canvas back inside the figure) while a token stack does not. If the root
        # holds both a chart figure and a canvas, treat it as usage regardless of how the two
        # nest - a false positive only keeps bytes, a false negative breaks an offline export.
        if scan._root_has_chart_figure and scan._root_has_canvas:
            scan.uses = True
    if scan.body_end is None:
        scan.body_end = len(html)
    return scan


def content_state(html):
    """Classify the document: `USES`, `UNUSED`, or `UNKNOWN`.

    The scan region is `#commentRoot`, matching the RUNTIME exactly (`68-export-offline.js`
    scopes its check to that element). Scanning only the region between the CONTENT markers
    would be NARROWER than the runtime, so rich content placed inside the root but outside the
    markers would be honoured by the exporter and missed here - a false negative.

    `UNKNOWN` means the content root could not be located, so the document is left ENTIRELY
    alone - neither stripped (it might rely on the payload) nor given one (a document that never
    carried the payload must not suddenly grow by 1.3 MB because it could not be parsed).
    """
    scan = _scan(html)
    if scan is None or scan.root_span is None:
        return UNKNOWN
    return USES if scan.uses else UNUSED


def content_needs_rich_libs(html):
    """True when the document must keep the payload - it uses rich content, or is unclassifiable.

    Fails SAFE: stripping a payload a document relies on breaks its offline export, while
    keeping an unnecessary one only costs bytes. Use `content_state` when the difference between
    "definitely uses" and "cannot tell" matters (it decides whether to ADD a payload).
    """
    return content_state(html) != UNUSED


def find_blob(html):
    """Return the (start, end) span of the real payload script element, or None.

    Parser-based and restricted to scripts OUTSIDE the content root, so neither a commented-out
    example nor an authored one inside the document body is ever mistaken for the payload - a
    regex version deleted both.
    """
    scan = _scan(html)
    if not scan or not scan.blob_spans:
        return None
    return scan.blob_spans[0]


def blob_script(source_html):
    """Return the payload script element (with a trailing newline) taken from a built template."""
    span = find_blob(source_html)
    if not span:
        return None
    return source_html[span[0]:span[1]].strip("\r\n \t") + "\n"




def strip_blob(html):
    span = find_blob(html)
    if not span:
        return html, False
    return html[:span[0]] + html[span[1]:], True


def _insert_before_body_end(html, script, body_end=None):
    """Insert `script` immediately before the document's real end of body.

    `body_end` comes from the PARSER. A substring search for `</body>` picks the last literal
    occurrence, which can be inside an HTML comment or a script string - review found a case
    where the 1.3 MB payload was inserted INSIDE a comment, invisible to both the runtime and
    to find_blob, while apply() reported success.
    """
    idx = body_end
    if idx is None:
        scan = _scan(html)
        idx = scan.body_end if scan else None
    if idx is None or idx > len(html):
        return html, False
    return html[:idx] + script + html[idx:], True


def apply(html, source_blob=None):
    """Add, remove, or leave the payload so the document carries it exactly when it can use it.

    `source_blob` is the payload script to restore with (see `blob_script`); pass None when only
    removal is wanted or no built template is reachable. Returns (html, changed) and is
    idempotent: a document already in the right state is returned byte-identical.

    One parser pass answers every question (classification, payload location, body end), so a
    2.5 MB document costs a single ~20 ms scan rather than one per query.
    """
    scan = _scan(html)
    if scan is None or scan.root_span is None:
        # Cannot classify: touch nothing. Never grow a document that may not even be one of ours.
        return html, False
    if not scan.uses:
        if not scan.blob_spans:
            return html, False
        # Remove EVERY payload copy (a refresh can leave a stale second one) in one pass, back
        # to front so earlier offsets stay valid.
        out = html
        for start, end in sorted(scan.blob_spans, reverse=True):
            out = out[:start] + out[end:]
        return out, True
    span = scan.blob_spans[0] if scan.blob_spans else None
    if len(scan.blob_spans) > 1:
        # A rich document keeps exactly ONE payload. The runtime resolves the payload as
        # infrastructure and refuses to guess between two candidates (it fails the Offline export
        # loudly rather than inflate the wrong one), so leaving a stale second copy here - which the
        # UNUSED branch above already collapses - would hand back a finalized document that cannot
        # be exported. Keep the LAST copy (the canonical after-content position when one is already
        # there) and drop the rest, back to front so earlier offsets stay valid, then let the
        # single-copy path below place it.
        out = html
        for start, end in sorted(scan.blob_spans[:-1], reverse=True):
            out = out[:start] + out[end:]
        return apply(out, source_blob)[0], True
    if span:
        # Already after the content root: leave it exactly as it is. Relocating an
        # already-placed payload would churn bytes on every finalize.
        if span[0] >= scan.root_span[1]:
            return html, False
        without = html[:span[0]] + html[span[1]:]
        shift = span[1] - span[0]
        body_end = scan.body_end - shift if scan.body_end > span[1] else scan.body_end
        moved, ok = _insert_before_body_end(
            without, html[span[0]:span[1]].strip("\r\n \t") + "\n", body_end)
        return (moved, True) if ok else (html, False)
    if not source_blob:
        return html, False
    return _insert_before_body_end(html, source_blob, scan.body_end)


def apply_file(path, source_blob=None):
    """Apply the decision to a file in place. Returns (changed, state)."""
    with open(path, "r", encoding="utf-8", newline="") as fh:
        html = fh.read()
    state = content_state(html)
    out, changed = apply(html, source_blob)
    if changed:
        _atomic_io.atomic_write(path, out)
    return changed, state


def main(argv):
    import argparse
    parser = argparse.ArgumentParser(
        prog="vendored_libs.py",
        description="Carry the vendored mermaid/Chart.js payload only in a document whose "
                    "content uses a diagram or a chart, and keep it out of the document head. "
                    "finalize.py runs this automatically; use it directly to inspect or fix a "
                    "single document.")
    parser.add_argument("file", help="HTML document to inspect or rewrite")
    parser.add_argument("--check", action="store_true",
                        help="report the decision and exit without writing")
    parser.add_argument("--template", default=None,
                        help="a built SHAREABLE.html to take the payload from when it must be "
                             "restored (default: the skill's own dist/SHAREABLE.html)")
    args = parser.parse_args(argv[1:])

    try:
        with open(args.file, "r", encoding="utf-8", newline="") as fh:
            html = fh.read()
    except (OSError, UnicodeDecodeError) as exc:
        sys.stderr.write("vendored_libs: %s\n" % exc)
        return 1

    state = content_state(html)
    present = find_blob(html) is not None
    if args.check:
        print("vendored_libs: content=%s payload=%s" % (state, "present" if present else "absent"))
        return 0

    source_blob = None
    template = (_toolpath.resolve_template_path(args.template) if args.template
                else _toolpath.dist_template(_toolpath.SHAREABLE_TEMPLATE))
    try:
        with open(template, "r", encoding="utf-8", newline="") as fh:
            source_blob = blob_script(fh.read())
    except (OSError, UnicodeDecodeError):
        source_blob = None

    out, changed = apply(html, source_blob)
    if changed:
        _atomic_io.atomic_write(args.file, out)
    print("vendored_libs: content=%s -> %s" % (state, "rewritten" if changed else "unchanged"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
