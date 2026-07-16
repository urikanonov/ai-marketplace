from _validate_helpers import *


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

    def test_named_reference_to_nonexistent_heading_not_flagged(self):
        self.assertFalse(self._warns(self.HEADS + "<p>Refer to Gamma plan for details.</p>"))

    def test_single_heading_document_skips_named_check(self):
        self.assertFalse(self._warns('<h2 id="a">Overview</h2><p>The overview covers scope.</p>'))


if __name__ == "__main__":
    unittest.main()
