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
import os
import re
import shutil
import sys
import unittest
from html.parser import HTMLParser

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402
sys.path.insert(0, _paths.TOOLS)
import vendored_libs  # noqa: E402
import new_document  # noqa: E402


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
        with open(os.path.join(_paths.DIST, "PORTABLE.html"), "r", encoding="utf-8",
                  newline="") as fh:
            self.portable = fh.read()
        self.blob = vendored_libs.blob_script(self.portable)
        self.assertTrue(self.blob, "the built PORTABLE template must carry the blob")

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
    (`pre.mermaid, div.mermaid, figure.chart canvas, canvas.cmh-chart`) over every shipped
    example's CONTENT region and require the fast regex to reach the same verdict.
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
        # A DELIBERATE superset of the exporter's selectors: the live renderer draws
        # `canvas[data-cmh-chart-points]` even without the cmh-chart class. Keeping the payload
        # errs toward a larger document rather than a chart that renders and then breaks on
        # export. See issue filed for the underlying runtime inconsistency.
        self.assertEqual(vendored_libs.content_state(_doc(
            '<h1>C</h1>\n<canvas id="a" data-cmh-chart-points="1,2,3"></canvas>')),
            vendored_libs.USES)


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
        with open(os.path.join(_paths.DIST, "PORTABLE.html"), "r", encoding="utf-8",
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


class RuntimeParityTests(unittest.TestCase):
    """CMH-SIZE-01: the author-time decision uses the same selectors as the runtime exporter."""

    def _runtime_source(self):
        path = os.path.join(_paths.DEV, "assets", "js", "68-export-offline.js")
        with open(path, "r", encoding="utf-8", newline="") as fh:
            return fh.read()

    def test_the_selector_set_matches_the_runtimes_exactly(self):
        """Two-directional: catches the runtime ADDING a selector, not just removing one.

        Asserting only that the four known selectors are still present would keep passing if
        someone taught the exporter a NEW chart shape, while the stripper silently missed it -
        exactly the false negative that deletes a payload the export then demands.

        The selectors are taken from the offline-usage functions and NOT filtered on the
        words "chart"/"mermaid": a keyword filter would silently drop a future selector such as
        `canvas[data-cmh-visual]` and quietly re-open the hole this test exists to close.

        `_offlineDocNeedsChartLib` is in the list because it is the function that actually decides
        whether the export inlines Chart.js; it repeats the chart-canvas selector, so pinning it
        here is what stops that copy from drifting away from the one this module strips against.
        Functions that scan `script` elements for evidence (`_offlineDocReferencesChartLib`) are
        deliberately NOT in the list - their selector is not a content shape.

        The per-function assertion below is what makes that pinning real: a UNION alone would still
        pass if one function's copy of the chart selector were narrowed or dropped, because another
        function contributes the same strings.
        """
        source = self._runtime_source()
        found = set()
        per_function = {}
        for fn in ("_offlineLiveDocNeedsRichLibs", "_offlineDocUsesMermaid", "_offlineDocUsesCharts",
                   "_offlineDocNeedsChartLib"):
            start = source.find("function " + fn)
            self.assertNotEqual(start, -1,
                                "the runtime no longer defines %s; the parity check is stale "
                                "and must be re-pointed at whatever replaced it" % fn)
            body = source[start:source.find("\n}", start)]
            selectors = set()
            for m in re.finditer(r'querySelector(?:All)?\(\s*"([^"]*)"', body):
                for part in m.group(1).split(","):
                    if part.strip():
                        selectors.add(part.strip())
            per_function[fn] = selectors
            found |= selectors
        chart_selectors = {"figure.chart canvas", "canvas.cmh-chart"}
        for fn in ("_offlineDocUsesCharts", "_offlineDocNeedsChartLib"):
            self.assertEqual(
                per_function[fn], chart_selectors,
                "%s must query exactly the pinned chart-canvas selectors. Both the shape gate and "
                "the inline-the-library decision carry this literal; if one is narrowed, a document "
                "whose chart the other still recognises loses the library its export needs." % fn)
        self.assertTrue(found, "could not extract any selector from the runtime usage functions")
        self.assertEqual(
            found, set(vendored_libs.RUNTIME_SELECTORS),
            "the runtime's rich-content selectors and vendored_libs.RUNTIME_SELECTORS have "
            "diverged. Update RUNTIME_SELECTORS *and* the detector, or a document using the new "
            "shape will be stripped of a payload its own offline export needs.")

    def test_every_runtime_selector_is_recognised_by_the_author_time_detector(self):
        markup = {
            "pre.mermaid": '<pre class="mermaid cm-skip">graph TD; A--&gt;B;</pre>',
            "div.mermaid": '<div class="mermaid">graph TD; A--&gt;B;</div>',
            "figure.chart canvas": '<figure class="chart"><canvas id="a"></canvas></figure>',
            "canvas.cmh-chart": '<canvas class="cmh-chart" id="b"></canvas>',
        }
        self.assertEqual(set(markup), set(vendored_libs.RUNTIME_SELECTORS),
                         "add example markup for every declared runtime selector")
        for selector, fragment in markup.items():
            self.assertTrue(
                vendored_libs.content_needs_rich_libs(_doc("<h1>H</h1>\n" + fragment)),
                "content matching the runtime selector %r must be detected as needing the "
                "libraries" % selector)


if __name__ == "__main__":
    unittest.main()
