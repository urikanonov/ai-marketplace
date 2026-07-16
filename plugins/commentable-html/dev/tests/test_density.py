#!/usr/bin/env python3
"""Tests for the information-density authoring advisory (CMH-VAL-15): a non-fatal validator
warning when a report/plan section is a wall of consecutive long paragraphs with no layout-bearing
block (table, list, figure, diff, chart, or diagram) to break it up."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402

sys.path.insert(0, os.path.join(_paths.TOOLS, "validate"))
from checks import density  # noqa: E402

# A paragraph comfortably past the default "long" threshold (~240 chars).
LONG = "This sentence is deliberately padded out with plenty of filler words " * 4
SHORT = "A short line."


def _p(text):
    return "<p>%s</p>" % text


def _doc(inner, kind="report"):
    return (
        '<!doctype html><html><head>'
        '<meta name="commentable-html-kind" content="%s" />'
        '</head><body><main id="commentRoot" data-cmh-content-root>'
        "<h1>Title</h1><section><h2>Section</h2>%s</section>"
        "</main></body></html>" % (kind, inner)
    )


def _doc_body(body_html, kind="report"):
    # A document whose #commentRoot holds body_html verbatim (no auto <section> wrapper), for
    # exercising nested/headless sections and malformed markup.
    return (
        '<!doctype html><html><head>'
        '<meta name="commentable-html-kind" content="%s" />'
        '</head><body><main id="commentRoot" data-cmh-content-root>'
        "<h1>Title</h1>%s</main></body></html>" % (kind, body_html)
    )


class DensityAdvisoryTests(unittest.TestCase):
    def test_cmh_val_15_prose_wall_warns(self):
        errors, warnings = density.check_density(_doc(_p(LONG) * 4))
        self.assertEqual(errors, [])
        self.assertTrue(warnings, "expected a density advisory for a 4-paragraph prose wall")

    def test_cmh_val_15_layout_bearing_section_is_clean(self):
        # A table breaks the run so no sub-run reaches the threshold.
        inner = _p(LONG) * 2 + "<table><tr><td>x</td></tr></table>" + _p(LONG) * 2
        errors, warnings = density.check_density(_doc(inner))
        self.assertEqual(warnings, [])

    def test_cmh_val_15_short_paragraphs_are_clean(self):
        errors, warnings = density.check_density(_doc(_p(SHORT) * 8))
        self.assertEqual(warnings, [])

    def test_cmh_val_15_heading_breaks_the_run(self):
        inner = _p(LONG) * 3 + "<h3>Sub</h3>" + _p(LONG) * 3
        errors, warnings = density.check_density(_doc(inner))
        self.assertEqual(warnings, [])

    def test_cmh_val_15_slides_and_board_are_exempt(self):
        for kind in ("slides", "board"):
            errors, warnings = density.check_density(_doc(_p(LONG) * 6, kind=kind))
            self.assertEqual(warnings, [], msg="kind %s should be exempt" % kind)

    def test_cmh_val_15_cm_skip_is_ignored(self):
        inner = '<div class="cm-skip">%s</div>' % (_p(LONG) * 6)
        errors, warnings = density.check_density(_doc(inner))
        self.assertEqual(warnings, [])

    def test_cmh_val_15_content_outside_root_is_ignored(self):
        # A prose wall in host chrome outside #commentRoot must not be flagged.
        html = (
            '<!doctype html><html><head>'
            '<meta name="commentable-html-kind" content="report" /></head><body>'
            "<header>%s</header>"
            '<main id="commentRoot" data-cmh-content-root><h1>t</h1><section><h2>s</h2>%s</section></main>'
            "</body></html>" % (_p(LONG) * 6, _p(SHORT))
        )
        errors, warnings = density.check_density(html)
        self.assertEqual(warnings, [])

    def test_cmh_val_15_threshold_is_tunable(self):
        # A 3-paragraph section is clean at the default max but warns at a stricter max_run.
        doc = _doc(_p(LONG) * 3)
        self.assertEqual(density.check_density(doc)[1], [])
        self.assertTrue(density.check_density(doc, max_run=3)[1])

    def test_cmh_val_15_paragraphs_inside_layout_do_not_count(self):
        # Long <p> inside a SINGLE list/figure are layout content, not a prose wall (this fixture
        # is red without the layout_depth exclusion and green with it).
        inner = "<ul>%s</ul>" % (("<li>%s</li>" % _p(LONG)) * 6)
        errors, warnings = density.check_density(_doc(inner))
        self.assertEqual(warnings, [])

    def test_cmh_val_15_unclosed_paragraphs_still_warn(self):
        # </p> is optional in HTML5; a wall written without closing tags must still be caught.
        errors, warnings = density.check_density(_doc(("<p>%s" % LONG) * 4))
        self.assertTrue(warnings, "expected a wall of unclosed paragraphs to warn")

    def test_cmh_val_15_generic_and_missing_kind_are_exempt(self):
        self.assertEqual(density.check_density(_doc(_p(LONG) * 6, kind="generic"))[1], [])
        no_meta = (
            '<!doctype html><html><head></head><body>'
            '<main id="commentRoot" data-cmh-content-root><h1>t</h1><section><h2>s</h2>%s</section>'
            "</main></body></html>" % (_p(LONG) * 6)
        )
        self.assertEqual(density.check_density(no_meta)[1], [])

    def test_cmh_val_15_first_kind_meta_wins(self):
        # A later duplicate/template kind meta must not flip the scope away from report.
        doc = _doc(_p(LONG) * 6).replace(
            "</head>", '<meta name="commentable-html-kind" content="slides" /></head>')
        self.assertTrue(density.check_density(doc)[1], "first (report) kind meta should win")

    def test_cmh_val_15_whitespace_does_not_inflate_length(self):
        # Near-threshold: raw text (with source newlines/indentation) exceeds min_chars but the
        # whitespace-collapsed text does not, so it is NOT a long paragraph.
        near = "\n        ".join(["word"] * 40)  # ~433 raw chars, ~199 collapsed
        self.assertEqual(density.check_density(_doc(("<p>%s</p>" % near) * 4))[1], [])

    def test_cmh_val_15_short_paragraph_breaks_consecutiveness(self):
        # Long paragraphs separated by short ones are not "consecutive long paragraphs".
        self.assertEqual(density.check_density(_doc((_p(LONG) + _p(SHORT)) * 5))[1], [])

    def test_cmh_val_15_cm_skip_block_breaks_the_run(self):
        # A cm-skip block between paragraphs (e.g. a non-commentable embedded table) interrupts the
        # consecutive-long count, so paragraphs either side are separate short runs.
        inner = (_p(LONG) * 2
                 + '<div class="cm-skip"><table><tr><td>x</td></tr></table></div>'
                 + _p(LONG) * 2)
        self.assertEqual(density.check_density(_doc(inner))[1], [])

    def test_cmh_val_15_self_closing_layout_breaks_the_run(self):
        # A self-closing layout element must break the run (pins the removal of handle_startendtag,
        # which previously swallowed self-closing tags).
        inner = _p(LONG) * 2 + '<canvas class="cmh-chart" />' + _p(LONG) * 2
        self.assertEqual(density.check_density(_doc(inner))[1], [])

    def test_cmh_val_15_headless_section_is_not_mislabeled(self):
        # A headless wall section following a headed clean section must be labeled
        # "(untitled section)", not the previous heading.
        html = (
            '<!doctype html><html><head>'
            '<meta name="commentable-html-kind" content="report" /></head><body>'
            '<main id="commentRoot" data-cmh-content-root><h1>T</h1>'
            "<section><h2>Clean</h2>%s</section>"
            "<section>%s</section></main></body></html>" % (_p(LONG) * 2, _p(LONG) * 4)
        )
        _errors, warnings = density.check_density(html)
        self.assertTrue(any('"(untitled section)"' in w for w in warnings))
        self.assertFalse(any('"Clean"' in w for w in warnings))

    def test_cmh_val_15_inline_cm_skip_does_not_split_a_paragraph(self):
        # An inline cm-skip span inside a paragraph excludes only its own text; the paragraph is
        # still one long unit, so a wall of such paragraphs is still flagged.
        para = '<p>%s <span class="cm-skip">ignore</span> %s</p>' % (LONG, LONG)
        self.assertTrue(density.check_density(_doc(para * 4))[1],
                        "inline cm-skip must not truncate its paragraph")

    def test_cmh_val_15_min_chars_is_tunable(self):
        med = "word " * 24  # ~120 chars: short at the default, long at a smaller min_chars
        doc = _doc(("<p>%s</p>" % med) * 4)
        self.assertEqual(density.check_density(doc)[1], [])
        self.assertTrue(density.check_density(doc, min_chars=100)[1])

    def test_cmh_val_15_two_headless_walls_are_both_reported(self):
        body = "<section>%s</section><section>%s</section>" % (_p(LONG) * 4, _p(LONG) * 4)
        _errors, warnings = density.check_density(_doc_body(body))
        self.assertEqual(len([w for w in warnings if "wall of" in w]), 2,
                         "two distinct headless walls must each be reported")

    def test_cmh_val_15_prose_after_nested_section_uses_outer_heading(self):
        body = ("<section><h2>Outer</h2>"
                "<section><h3>Inner</h3><p>short</p></section>"
                "%s</section>" % (_p(LONG) * 4))
        _errors, warnings = density.check_density(_doc_body(body))
        self.assertTrue(any('"Outer"' in w for w in warnings),
                        "a wall in the outer section after a nested one must keep the outer label")

    def test_cmh_val_15_stray_close_section_does_not_suppress(self):
        # A dangling </section> with no matching open must not silently break a real wall.
        body = "%s</section>%s" % (_p(LONG) * 2, _p(LONG) * 2)
        self.assertTrue(density.check_density(_doc_body(body))[1],
                        "a stray unmatched </section> must not suppress a genuine wall")

    def test_cmh_val_15_wired_into_validate(self):
        import tempfile
        sys.path.insert(0, os.path.join(_paths.TOOLS, "validate"))
        import validate  # noqa: E402
        doc = _doc(_p(LONG) * 5)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "doc.html")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(doc)
            _errors, warnings = validate.validate(path)
        self.assertTrue(any("wall of" in w for w in warnings),
                        msg="check_density must be wired into validate.validate")


if __name__ == "__main__":
    unittest.main()
