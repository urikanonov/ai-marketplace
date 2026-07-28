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
import os
import sys
import unittest

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
        # Fail-safe must mean "leave it alone", NOT "add a payload". A minimal or foreign
        # document has no CONTENT markers; inserting 1.3 MB into it would be far worse than
        # leaving it as it is.
        minimal = "<html><body><main id=\"commentRoot\">hi</main></body></html>\n"
        self.assertEqual(vendored_libs.content_state(minimal), vendored_libs.UNKNOWN)
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


class RuntimeParityTests(unittest.TestCase):
    """CMH-SIZE-01: the author-time decision uses the same selectors as the runtime exporter."""

    def test_every_runtime_selector_is_recognised_by_the_author_time_detector(self):
        # If the two ever disagree, a document could be stripped of a payload its own offline
        # export then demands and fails on. Drive each runtime selector through the detector.
        runtime = os.path.join(_paths.DEV, "assets", "js", "68-export-offline.js")
        with open(runtime, "r", encoding="utf-8", newline="") as fh:
            source = fh.read()
        for selector in ("pre.mermaid", "div.mermaid", "figure.chart canvas", "canvas.cmh-chart"):
            self.assertIn(selector, source,
                          "the runtime no longer uses %r; update the author-time detector "
                          "in vendored_libs.py to match" % selector)
        markup = {
            "pre.mermaid": '<pre class="mermaid cm-skip">graph TD; A--&gt;B;</pre>',
            "div.mermaid": '<div class="mermaid">graph TD; A--&gt;B;</div>',
            "figure.chart canvas": '<figure class="chart"><canvas id="a"></canvas></figure>',
            "canvas.cmh-chart": '<canvas class="cmh-chart" id="b"></canvas>',
        }
        for selector, fragment in markup.items():
            self.assertTrue(
                vendored_libs.content_needs_rich_libs(_doc("<h1>H</h1>\n" + fragment)),
                "content matching the runtime selector %r must be detected as needing the "
                "libraries" % selector)


if __name__ == "__main__":
    unittest.main()
