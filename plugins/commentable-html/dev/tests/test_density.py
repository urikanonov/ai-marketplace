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
        # still one long unit, so a wall of such paragraphs is still flagged. Even an inline
        # cm-skip that WRAPS block content is shielded (skip_depth gates the inner table out).
        para = ('<p>%s <span class="cm-skip">ignore</span> '
                '<span class="cm-skip"><table><tr><td>x</td></tr></table></span> %s</p>' % (LONG, LONG))
        _errors, warnings = density.check_density(_doc(para * 4))
        self.assertEqual(len(warnings), 1)
        self.assertIn('"Section"', warnings[0])

    def test_cmh_val_15_block_cm_skip_breaks_run_after_unclosed_paragraph(self):
        # A block-level cm-skip implicitly closes an open (unclosed) paragraph and breaks the run,
        # so paragraphs separated by block cm-skip blocks are not one consecutive wall.
        inner = (("<p>%s" % LONG) + '<div class="cm-skip"><table><tr><td>x</td></tr></table></div>') * 4
        self.assertEqual(density.check_density(_doc(inner))[1], [],
                         "block cm-skip after an unclosed <p> must still break the run")

    def test_cmh_val_15_phrasing_cm_skip_does_not_split_a_paragraph(self):
        # Phrasing/void controls carrying cm-skip (img, br, button, input) inside a paragraph are
        # inline: they exclude only their own text and never split the paragraph.
        para = ('<p>%s <img class="cm-skip" alt="x"> <button class="cm-skip">b</button> '
                '<input class="cm-skip"> %s</p>' % (LONG, LONG))
        _errors, warnings = density.check_density(_doc(para * 4))
        self.assertEqual(len(warnings), 1)
        self.assertIn('"Section"', warnings[0])

    def test_cmh_val_15_two_flat_top_level_walls_are_both_reported(self):
        # Two headed walls at the top level (no <section> wrappers) must each report, not dedupe
        # into one.
        body = "<h2>Alpha</h2>%s<h2>Beta</h2>%s" % (_p(LONG) * 4, _p(LONG) * 4)
        _errors, warnings = density.check_density(_doc_body(body))
        self.assertEqual(len([w for w in warnings if "wall of" in w]), 2)
        self.assertTrue(any('"Alpha"' in w for w in warnings) and any('"Beta"' in w for w in warnings))

    def test_cmh_val_15_section_in_layout_block_does_not_reframe(self):
        # A <section> structurally embedded in a layout block must not relabel the enclosing prose
        # section; a wall after it in the outer section keeps the outer heading.
        body = ("<section><h2>Outer</h2>"
                "<figure><section><h3>Inner</h3><p>x</p></section></figure>"
                "%s</section>" % (_p(LONG) * 4))
        _errors, warnings = density.check_density(_doc_body(body))
        self.assertTrue(any('"Outer"' in w for w in warnings))
        self.assertFalse(any('"Inner"' in w for w in warnings))

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

    def test_cmh_val_15_two_walls_in_one_section_are_both_reported(self):
        # Two genuine walls under the same heading, separated by a short intervening child section,
        # must both be reported (per-run, not per-section dedup - regression guard).
        body = ("<section><h2>Outer</h2>" + _p(LONG) * 4
                + "<section><h3>Inner</h3><p>short</p></section>"
                + _p(LONG) * 4 + "</section>")
        _errors, warnings = density.check_density(_doc_body(body))
        self.assertEqual(len([w for w in warnings if "wall of" in w]), 2,
                         "both walls under the same heading must be reported, not deduped away")

    def test_cmh_val_15_phrasing_cm_skip_between_paragraphs_breaks_run(self):
        # A phrasing cm-skip element BETWEEN paragraphs (not inside a <p>) must still break the
        # run - the inline exemption only applies inside an open paragraph.
        inner = _p(LONG) * 2 + '<span class="cm-skip">widget</span>' + _p(LONG) * 2
        self.assertEqual(density.check_density(_doc(inner))[1], [],
                         "phrasing cm-skip between paragraphs must break the prose run")

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

    def test_cmh_val_15_template_paragraphs_are_inert(self):
        # A <template>'s contents live in an inert DocumentFragment a browser never renders, so
        # parked paragraphs are markup an author is SHOWING, not prose a reader can restructure.
        inner = "<template>%s</template>" % (_p(LONG) * 6)
        self.assertEqual(density.check_density(_doc(inner))[1], [],
                         "paragraphs parked inside a <template> must not count as prose")

    def test_cmh_val_15_unclosed_template_swallows_the_rest(self):
        # An unclosed <template> is never closed by a browser either: everything to the end of the
        # input stays in the inert fragment, so nothing after it counts.
        inner = "<template>%s" % (_p(LONG) * 6)
        self.assertEqual(density.check_density(_doc(inner))[1], [],
                         "an unclosed <template> must keep the rest of the input inert")

    def test_cmh_val_15_template_heading_does_not_label_a_wall(self):
        # A heading parked in a template is not the heading a reader sees, so a real wall after it
        # keeps the enclosing section's own label.
        inner = "<template><h2>Parked</h2></template>" + _p(LONG) * 4
        _errors, warnings = density.check_density(_doc(inner))
        self.assertTrue(warnings, "the real wall after the template must still be reported")
        self.assertTrue(all("Parked" not in w for w in warnings),
                        "a template-parked heading must not label the section")

    def test_cmh_val_15_template_does_not_break_a_real_wall(self):
        # A template renders nothing, so it cannot visually break up a wall - neither the element
        # itself nor a layout block or heading parked inside it may reset the run.
        inner = (_p(LONG) * 2
                 + "<template><table><tr><td>x</td></tr></table><h3>Sub</h3></template>"
                 + _p(LONG) * 2)
        self.assertTrue(density.check_density(_doc(inner))[1],
                        "an inert template between paragraphs must not break the prose run")

    def test_cmh_val_15_template_end_tag_does_not_close_an_outer_element(self):
        # An end tag inside the fragment must not reach an element opened outside it: a parked
        # </main> must not retire the content root and end the run early.
        inner = "<template></main></template>" + _p(LONG) * 4
        self.assertTrue(density.check_density(_doc(inner))[1],
                        "a template-parked end tag must not close the content root")

    def test_cmh_val_15_template_kind_meta_does_not_set_the_scope(self):
        # The kind meta the browser applies is the live one; an inert copy must not flip the scope
        # (the same rule the document parser applies).
        html = (
            '<!doctype html><html><head><template>'
            '<meta name="commentable-html-kind" content="slides" /></template>'
            '<meta name="commentable-html-kind" content="report" /></head>'
            '<body><main id="commentRoot" data-cmh-content-root><h1>Title</h1>'
            "<section><h2>Section</h2>%s</section></main></body></html>" % (_p(LONG) * 4)
        )
        self.assertTrue(density.check_density(html)[1],
                        "a template-parked kind meta must not exempt a real report")

    def test_cmh_val_15_self_closed_template_still_opens_the_fragment(self):
        # HTML5 ignores a trailing slash on a non-void tag, so `<template/>` OPENS the fragment
        # rather than opening and closing it.
        inner = "<template/>%s" % (_p(LONG) * 6)
        self.assertEqual(density.check_density(_doc(inner))[1], [],
                         "a self-closed <template/> must still open the inert fragment")

    def test_cmh_val_15_mixed_case_template_is_inert(self):
        inner = "<TEMPLATE>%s</TEMPLATE>" % (_p(LONG) * 6)
        self.assertEqual(density.check_density(_doc(inner))[1], [],
                         "a browser folds a tag name ASCII-case-insensitively")

    def test_cmh_val_15_nested_templates_stay_inert_until_both_close(self):
        # The inner `</template>` must not re-activate the pass while the outer one is open.
        still_open = "<template><template></template>" + _p(LONG) * 6
        self.assertEqual(density.check_density(_doc(still_open))[1], [],
                         "an inner </template> must not close the outer fragment")
        both_closed = "<template><template></template></template>" + _p(LONG) * 4
        self.assertTrue(density.check_density(_doc(both_closed))[1],
                        "prose after BOTH templates close is live again")

    def test_cmh_val_15_stray_close_template_does_not_corrupt_the_stack(self):
        # A dangling </template> with no matching open must not disturb the live document.
        inner = "</template>" + _p(LONG) * 4
        self.assertTrue(density.check_density(_doc(inner))[1],
                        "a stray unmatched </template> must not suppress a genuine wall")

    def test_cmh_val_15_template_does_not_split_an_open_paragraph(self):
        # `<p>a<template>x</template>b</p>` is one "ab" paragraph to a browser. Each HALF is
        # below the long-paragraph floor, so this wall fires only if the two halves stay ONE
        # paragraph - which pins the deliberate no-flush choice on entering a template.
        half = LONG[:len(LONG) // 2]
        para = "<p>%s<template>parked</template>%s</p>" % (half, half)
        self.assertTrue(density.check_density(_doc(para * 4))[1],
                        "an inline template must not split the paragraph around it")

        # A block inside a template belongs to the fragment's own tree. It cannot trigger HTML's
        # implicit paragraph close in the outer document.
        para = "<p>%s<template><div>parked</div></template>%s</p>" % (half, half)
        self.assertTrue(density.check_density(_doc(para * 4))[1],
                        "a template-parked block must not close the outer paragraph")

        # The inner paragraph and its closer are scoped to the inert fragment; closing it must not
        # finalize the live paragraph capture that surrounds the template.
        para = "<p>%s<template><p>parked</p></template>%s</p>" % (half, half)
        self.assertTrue(density.check_density(_doc(para * 4))[1],
                        "an inner </p> must not finalize the outer paragraph")

        body = "<h2>Live <template><h2>Parked</h2></template>Heading</h2>%s" % (_p(LONG) * 4)
        _errors, warnings = density.check_density(_doc_body(body))
        self.assertTrue(any('"Live Heading"' in warning for warning in warnings))
        self.assertFalse(any('"Live"' in warning for warning in warnings))

    def test_cmh_val_15_template_token_in_raw_text_is_not_a_tag(self):
        # Raw-text and RCDATA content is prose a reader SEES, so a `<template>` written inside
        # <title>/<textarea>/<noscript> is text, not a tag, and cannot switch the pass off. The
        # boundary is installed here rather than taken from the host, whose raw-text table
        # differs by interpreter (CMH-VAL-21).
        for parked in ("<title>Using <template> in reports</title>",
                       "<title>Using <template> in reports</title data-x>",
                       "<textarea><template></textarea/>",
                       "<textarea><template></textarea>",
                       "<noscript><template/></noscript foo>",
                       "<noscript><template/></noscript>"):
            inner = parked + _p(LONG) * 4
            self.assertTrue(density.check_density(_doc(inner))[1],
                            msg="a <template> token inside %s is text, not a tag" % parked)

        # A raw-text element the author never closed runs to EOF in a browser, so a `<template>`
        # inside it stays text and there is no live prose left to count either way.
        self.assertEqual(density.check_density(_doc("<textarea><template>" + _p(LONG) * 4))[1], [],
                         "an unclosed raw-text element runs to EOF")

    def test_cmh_val_15_foreign_self_closed_template_is_not_inert(self):
        # A trailing slash really closes a FOREIGN element. An SVG element named `template` is
        # neither HTML's inert template nor left open, so the prose after the SVG stays live.
        inner = "<svg><template/></svg>" + _p(LONG) * 4
        self.assertTrue(density.check_density(_doc(inner))[1],
                        "a self-closed foreign template must not suppress the following prose")

    def test_cmh_val_15_foreign_raw_text_names_are_parsed_as_markup(self):
        # SVG title/script bodies stay in the tokenizer's data state. The table in either body is
        # therefore a real layout boundary, not text swallowed by HTML raw-text handling.
        for foreign in (
                "<svg><title><table><tr><td>x</td></tr></table></title></svg>",
                "<svg><script><table><tr><td>x</td></tr></table></script></svg>"):
            inner = _p(LONG) * 2 + foreign + _p(LONG) * 2
            self.assertEqual(density.check_density(_doc(inner))[1], [],
                             msg="foreign title/script markup must break the prose run: %s" % foreign)

        # A foreign element that merely shares an HTML layout/section name has none of that HTML
        # element's semantics, so it cannot split an otherwise continuous prose wall.
        for name in ("figure", "canvas", "section"):
            inner = _p(LONG) * 2 + "<svg><%s/></svg>" % name + _p(LONG) * 2
            self.assertTrue(density.check_density(_doc(inner))[1],
                            msg="a foreign <%s> must not act as an HTML boundary" % name)

    def test_cmh_val_15_self_closed_html_section_stays_open(self):
        # HTML ignores the slash on a non-void start tag. The wall belongs to the newly opened
        # headless section, exactly as it does for an ordinary `<section>` start tag.
        inner = "<section><h2>Outer</h2><section/>%s</section>" % (_p(LONG) * 4)
        _errors, warnings = density.check_density(_doc_body(inner))
        self.assertTrue(any('"(untitled section)"' in warning for warning in warnings))
        self.assertFalse(any('"Outer"' in warning for warning in warnings))

    def test_cmh_val_15_template_parked_script_body_does_not_close_the_fragment(self):
        # A `</template>` inside a parked <script> body is script text, not the fragment's closer.
        inner = "<template><script>var s='</template>';</script>%s</template>" % (_p(LONG) * 6)
        self.assertEqual(density.check_density(_doc(inner))[1], [],
                         "a </template> inside a script body must not close the fragment")

    def test_cmh_val_15_declarative_shadow_root_template_is_not_inert(self):
        # A declarative shadow root is the one <template> a browser DOES render: it is attached
        # as the host's shadow tree, so its prose is a wall a reader actually sees.
        for mode in ("open", "closed", "OPEN", "op&#x65;n"):
            inner = '<template shadowrootmode="%s">%s</template>' % (mode, _p(LONG) * 4)
            self.assertTrue(density.check_density(_doc(inner))[1],
                            msg="shadowrootmode=%s renders, so its prose counts" % mode)
        # `shadowrootmode` is an ENUMERATED attribute: an unrecognized value, or one padded with
        # whitespace, attaches nothing, so the fragment stays inert.
        for mode in ("nope", " open", "open ", "open\u00a0"):
            inner = '<template shadowrootmode="%s">%s</template>' % (mode, _p(LONG) * 6)
            self.assertEqual(density.check_density(_doc(inner))[1], [],
                             msg="shadowrootmode=%r attaches nothing and stays inert" % mode)

    def test_cmh_val_15_only_the_first_shadow_root_on_a_host_renders(self):
        # A host element gets ONE declarative shadow root; a second template[shadowrootmode]
        # under the same parent stays an ordinary inert template, so its prose is not a wall.
        inner = ('<div><template shadowrootmode="open"><p>short</p></template>'
                 '<template shadowrootmode="open">%s</template></div>' % (_p(LONG) * 6))
        self.assertEqual(density.check_density(_doc(inner))[1], [],
                         "only the first declarative shadow root on a host is rendered")

    def test_cmh_val_15_shadow_template_on_an_ineligible_host_stays_inert(self):
        inner = '<button><template shadowrootmode="open">%s</template></button>' % (
            _p(LONG) * 6)
        self.assertEqual(density.check_density(_doc(inner))[1], [],
                         "a button cannot host a shadow root")

    def test_cmh_val_15_autonomous_custom_element_can_host_a_shadow_root(self):
        inner = '<review-card><template shadowrootmode="open">%s</template></review-card>' % (
            _p(LONG) * 4)
        self.assertTrue(density.check_density(_doc(inner))[1],
                        "an autonomous custom element can host a shadow root")

    def test_cmh_val_15_foreign_custom_element_cannot_host_a_shadow_root(self):
        source = '<svg><x-host><template shadowrootmode="open"><text>foreign</text>'
        parser = density._DensityParser(source, min_chars=10, max_run=2)
        parser.feed(source)
        self.assertFalse(
            any(frame["shadow"] for _tag, frame in parser._stack),
            "a custom-named SVG element is not an HTML shadow host",
        )

    def test_cmh_val_15_shadow_root_inside_a_template_stays_inert(self):
        # Its host is itself inside a fragment a browser never renders, so no shadow tree is
        # ever attached.
        inner = '<template><div><template shadowrootmode="open">%s</template></div></template>' % (
            _p(LONG) * 6)
        self.assertEqual(density.check_density(_doc(inner))[1], [],
                         "a shadow root parked inside an inert template is inert too")

    def test_cmh_val_15_shadow_root_kind_meta_does_not_set_the_scope(self):
        # A browser renders a shadow tree but never applies its metadata to the document, so a
        # kind meta parked in one must not decide whether the advisory runs.
        html = (
            '<!doctype html><html><head><div><template shadowrootmode="open">'
            '<meta name="commentable-html-kind" content="slides" /></template></div>'
            '<meta name="commentable-html-kind" content="report" /></head>'
            '<body><main id="commentRoot" data-cmh-content-root><h1>Title</h1>'
            "<section><h2>Section</h2>%s</section></main></body></html>" % (_p(LONG) * 4)
        )
        self.assertTrue(density.check_density(html)[1],
                        "a shadow-tree kind meta must not exempt a real report")

    def test_cmh_val_15_shadow_root_cannot_establish_the_content_root(self):
        html = (
            '<!doctype html><html><head><meta name="commentable-html-kind" content="report" /></head>'
            '<body><div><template shadowrootmode="open"><main id="commentRoot">'
            "%s</main></template></div>"
            '<main id="realRoot"><h1>Real title</h1><p>short</p></main></body></html>'
            % (_p(LONG) * 4)
        )
        self.assertEqual(density.check_density(html)[1], [])

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
