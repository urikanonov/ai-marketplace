from _validate_helpers import *

from checks import parsing  # noqa: E402


class SectionReferenceLinkTests(unittest.TestCase):
    """Deterministic detection of section cross-references in prose that are NOT links."""

    HEADS = '<h2 id="a">Alpha</h2><h2 id="b">Beta plan</h2>'

    def _main(self, content):
        return ('<main id="commentRoot" data-cmh-content-root data-comment-key="k" data-doc-label="l" data-doc-source="s">\n'
                + content + "\n</main>")

    def _warns(self, content):
        errors, warnings = _validate_text(
            build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), self._main(content), JS_REGION]))
        self.assertEqual(errors, [], errors)
        return any("cross-reference" in w for w in warnings)

    def test_unlinked_directional_reference_warns(self):
        self.assertTrue(self._warns(self.HEADS + "<p>See the section below for details.</p>"))

    def test_previous_section_reference_warns(self):
        self.assertTrue(self._warns(self.HEADS + "<p>As in the previous section, retries apply.</p>"))

    def test_linked_directional_reference_ok(self):
        self.assertFalse(self._warns(self.HEADS + '<p>See <a href="#b">the section below</a> for details.</p>'))

    def test_unlinked_named_reference_warns(self):
        self.assertTrue(self._warns(self.HEADS + "<p>Refer to Beta plan for the rollout.</p>"))

    def test_named_reference_with_section_suffix_warns(self):
        self.assertTrue(self._warns(self.HEADS + "<p>The Beta plan section covers rollout.</p>"))

    def test_linked_named_reference_ok(self):
        self.assertFalse(self._warns(self.HEADS + '<p>Refer to <a href="#b">Beta plan</a> for the rollout.</p>'))

    def test_benign_directional_word_not_flagged(self):
        # "below freezing" has no section word adjacent, so it is not a cross reference.
        self.assertFalse(self._warns(self.HEADS + "<p>Temperatures were below freezing overnight.</p>"))

    def test_reference_inside_cm_skip_ignored(self):
        self.assertFalse(self._warns(self.HEADS + '<nav class="cm-skip"><p>see the section above</p></nav><p>body</p>'))

    def test_reference_after_root_close_ignored(self):
        # A directional cross-reference in a sibling <footer> AFTER </main id=commentRoot>
        # is outside the reviewable content and must not be validated as prose.
        body = [HANDLED_REGION, EMBEDDED_REGION, comment_ui(),
                self._main(self.HEADS + "<p>Body text.</p>"),
                '<footer><h2 id="c">Gamma plan</h2>'
                "<p>See the section below for details.</p></footer>",
                JS_REGION]
        errors, warnings = _validate_text(build(body=body))
        self.assertEqual(errors, [], errors)
        self.assertFalse(any("cross-reference" in w for w in warnings), warnings)

    def test_reference_inside_a_template_ignored(self):
        # A <template> body is inert - a browser never renders it - so a cross reference a
        # document merely SHOWS there is not prose its author could be asked to link.
        self.assertFalse(self._warns(
            self.HEADS + "<template><p>See the section below for details.</p></template>"
            "<p>Body text.</p>"))

    def test_reference_inside_a_declarative_shadow_root_warns(self):
        for mode in ("open", "closed"):
            with self.subTest(mode=mode):
                self.assertTrue(self._warns(
                    self.HEADS
                    + '<div><template shadowrootmode="%s" shadowrootserializable>'
                      "<p>See the section below for details.</p>"
                      "</template></div>" % mode))

    def test_named_reference_to_nonexistent_heading_not_flagged(self):
        self.assertFalse(self._warns(self.HEADS + "<p>Refer to Gamma plan for details.</p>"))

    def test_single_heading_document_skips_named_check(self):
        self.assertFalse(self._warns('<h2 id="a">Overview</h2><p>The overview covers scope.</p>'))


class TemplateProseTests(unittest.TestCase):
    """Inert `<template>` content is not `#commentRoot` prose (CMH-CONTENT-16).

    A template's contents live in a DocumentFragment a browser never renders, which is why
    `_record()` and the heading capture already decline them. The prose view must agree, or
    the same markup is content to one check and not to another.
    """

    ROOT = '<main id="commentRoot">'

    def _prose(self, inner):
        doc = parsing._parse_document(self.ROOT + inner)
        return [t.strip() for t in doc.commentroot_prose if t.strip()]

    def test_prose_inside_a_template_is_not_collected(self):
        self.assertEqual(
            self._prose("<p>live</p><template><p>See Section 4</p></template></main>"),
            ["live"])

    def test_prose_inside_an_unclosed_template_is_not_collected(self):
        # A <template> still open at end of input holds its content inert all the way to EOF,
        # so the text after the parked paragraph is not prose either.
        self.assertEqual(
            self._prose("<p>live</p><template><p>See Section 4</p><p>Also parked</p>"),
            ["live"])

    def test_prose_after_a_template_closes_is_still_collected(self):
        self.assertEqual(
            self._prose("<template><p>See Section 4</p></template><p>live</p></main>"),
            ["live"])

    def test_declarative_shadow_root_prose_is_collected(self):
        for mode in ("open", "closed"):
            with self.subTest(mode=mode):
                self.assertEqual(
                    self._prose(
                        '<div><template shadowrootmode="%s"><p>rendered</p>'
                        "</template></div></main>" % mode),
                    ["rendered"])

    def test_shadow_script_and_style_text_is_not_prose(self):
        self.assertEqual(
            self._prose(
                '<div><template shadowrootmode="open">'
                '<script>See the section below</script><style>.x { color: red; }</style>'
                "<p>rendered</p></template></div></main>"),
            ["rendered"])

    def test_an_ineligible_hosts_shadow_template_stays_inert(self):
        self.assertEqual(
            self._prose(
                '<button><template shadowrootmode="open"><p>hidden</p>'
                "</template></button><p>live</p></main>"),
            ["live"])

    def test_an_autonomous_custom_element_can_host_a_shadow_root(self):
        self.assertEqual(
            self._prose(
                '<review-card><template shadowrootmode="open"><p>rendered</p>'
                "</template></review-card></main>"),
            ["rendered"])

    def test_only_the_first_declarative_shadow_root_on_a_host_is_rendered(self):
        self.assertEqual(
            self._prose(
                '<div><template shadowrootmode="open"><p>first</p></template>'
                '<template shadowrootmode="closed"><p>second</p></template></div></main>'),
            ["first"])

    def test_a_declarative_shadow_root_inside_an_inert_template_stays_inert(self):
        self.assertEqual(
            self._prose(
                '<template><div><template shadowrootmode="open"><p>parked</p>'
                "</template></div></template><p>live</p></main>"),
            ["live"])

    def _headings(self, inner):
        return [h["text"] for h in parsing._parse_document(self.ROOT + inner).headings]

    def test_heading_text_excludes_template_content(self):
        # A template nested INSIDE an open heading is inert too: a reader sees "Real", so the
        # named cross-reference and document-title checks must not read "RealHidden".
        self.assertEqual(
            self._headings("<h2>Real<template>Hidden</template>Tail</h2></main>"),
            ["RealTail"])

    def test_a_title_that_exists_only_in_a_template_does_not_satisfy_the_report_kind(self):
        # The one place the emptied heading flips a BLOCKING verdict: a reader sees no title at
        # all, so the report/plan title requirement must error rather than accept an invisible one.
        main = ('<main id="commentRoot" data-cmh-content-root data-comment-key="k" '
                'data-doc-label="l" data-doc-source="s">\n'
                "<h1><template>Parked Title</template></h1><p>content</p>\n</main>")
        errors, _ = _validate_text(build(
            body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION], kind="report"))
        self.assertTrue(any("requires a top-level <h1>" in e for e in errors), errors)

    def test_a_title_rendered_by_a_declarative_shadow_root_satisfies_report_kind(self):
        main = ('<main id="commentRoot" data-cmh-content-root data-comment-key="k" '
                'data-doc-label="l" data-doc-source="s">\n'
                '<h1><template shadowrootmode="open" shadowrootserializable>'
                "Rendered Title</template></h1>"
                "<p>content</p>\n</main>")
        errors, _ = _validate_text(build(
            body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION], kind="report"))
        self.assertFalse(any("requires a top-level <h1>" in e for e in errors), errors)

    def test_a_shadow_h1_under_a_top_level_host_satisfies_report_kind(self):
        main = ('<main id="commentRoot" data-cmh-content-root data-comment-key="k" '
                'data-doc-label="l" data-doc-source="s">\n'
                '<div><template shadowrootmode="open" shadowrootserializable>'
                "<h1>Rendered Title</h1></template></div>"
                "<p>content</p>\n</main>")
        errors, _ = _validate_text(build(
            body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION], kind="report"))
        self.assertFalse(any("requires a top-level <h1>" in e for e in errors), errors)

    def test_shadow_raw_text_alone_does_not_satisfy_report_kind(self):
        main = ('<main id="commentRoot" data-cmh-content-root data-comment-key="k" '
                'data-doc-label="l" data-doc-source="s">\n'
                '<h1><template shadowrootmode="open" shadowrootserializable>'
                "<style>.title { display: block; }</style>"
                "</template></h1><p>content</p>\n</main>")
        errors, _ = _validate_text(build(
            body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION], kind="report"))
        self.assertTrue(any("requires a top-level <h1>" in e for e in errors), errors)

    def test_a_declarative_shadow_root_must_be_serializable_for_exports(self):
        def errors_for(extra):
            main = ('<main id="commentRoot" data-cmh-content-root data-comment-key="k" '
                    'data-doc-label="l" data-doc-source="s">\n'
                    '<div><template shadowrootmode="closed"%s>'
                    "<h1>Durable title</h1></template></div>\n</main>" % extra)
            return _validate_text(build(
                body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION],
                kind="generic"))[0]

        unsafe = errors_for("")
        self.assertTrue(any("shadowrootserializable" in e for e in unsafe), unsafe)
        durable = errors_for(" shadowrootserializable")
        self.assertFalse(any("shadowrootserializable" in e for e in durable), durable)

    def test_a_shadow_host_cannot_mix_light_dom_children(self):
        main = ('<main id="commentRoot" data-cmh-content-root data-comment-key="k" '
                'data-doc-label="l" data-doc-source="s">\n'
                "<div><p>hidden before</p>"
                '<template shadowrootmode="open" shadowrootserializable>'
                "<p>rendered shadow</p></template><p>hidden after</p></div>\n</main>")
        errors, _ = _validate_text(build(
            body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION],
            kind="generic"))
        self.assertTrue(any("light-DOM children" in e for e in errors), errors)

    def test_shadow_slot_distribution_is_rejected_as_unsupported(self):
        main = ('<main id="commentRoot" data-cmh-content-root data-comment-key="k" '
                'data-doc-label="l" data-doc-source="s">\n'
                '<div><template shadowrootmode="open" shadowrootserializable>'
                "<slot><p>fallback</p></slot></template></div>\n</main>")
        errors, _ = _validate_text(build(
            body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION],
            kind="generic"))
        self.assertTrue(any("<slot> distribution" in e for e in errors), errors)


if __name__ == "__main__":
    unittest.main()
