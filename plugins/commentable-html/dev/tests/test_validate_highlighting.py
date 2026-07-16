from _validate_helpers import *


class ValidateHighlightingTests(ValidateAssertions, unittest.TestCase):
    def test_required_ids_contract(self):
        # If this fails, REQUIRED_IDS changed: update EXPECTED_REQUIRED_IDS on
        # purpose (and make sure the template + fixture provide the id).
        self.assertEqual(set(validate.REQUIRED_IDS), set(EXPECTED_REQUIRED_IDS))

    def test_minimal_document_is_clean(self):
        self.assertOkNoWarn(build())

    def _doc_with_code(self, code_html):
        main = (
            '<main id="commentRoot" data-cmh-content-root data-comment-key="k" '
            'data-doc-label="l" data-doc-source="s">\n'
            + CONTENT_BEGIN + "\n" + code_html + "\n" + CONTENT_END + "\n</main>"
        )
        return build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION])

    def test_unhighlighted_language_code_block_warns(self):
        # CMH-VAL-11: a <pre><code class="language-XXX"> block for a highlightable language that
        # carries no cmh-code-* spans was never run through highlight_code.py, so it renders as
        # monochrome text - warn so the author highlights it.
        doc = self._doc_with_code(
            '<pre><code class="language-csharp">public sealed class X { int Y { get; } }</code></pre>')
        self.assertWarn(doc, "is not syntax-highlighted")

    def test_unhighlighted_alias_language_code_block_warns(self):
        # The language token is normalized through the highlighter aliases (cs -> csharp).
        doc = self._doc_with_code('<pre><code class="language-cs">var x = 1;</code></pre>')
        self.assertWarn(doc, "is not syntax-highlighted")

    def test_unhighlighted_markup_language_code_block_warns(self):
        # CMH-VAL-11: markup (html/xml) is a highlightable language, so a raw language-html/xml
        # block with no cmh-code-* spans must be flagged - this is exactly the notes-feature-plan.html
        # defect (a language-html block shipped without baked highlighting).
        for lang in ("html", "xml"):
            doc = self._doc_with_code(
                '<pre><code class="language-%s">&lt;div class="x"&gt;hi&lt;/div&gt;</code></pre>' % lang)
            self.assertWarn(doc, "is not syntax-highlighted")

    def test_highlighted_code_block_is_clean(self):
        doc = self._doc_with_code(
            '<pre><code class="language-python">'
            '<span class="cmh-code-kw">def</span> f(): <span class="cmh-code-kw">return</span> 1'
            '</code></pre>')
        self.assertOkNoWarn(doc)

    def test_non_highlightable_language_code_block_is_clean(self):
        # language-text / an unknown label (e.g. console) is not a highlightable language, so a
        # monochrome block is expected, not a defect. (KQL - language-kusto - has its own runnable
        # rule, CMH-KQL-08, so it is not used here as a plain non-highlightable example.)
        for cls in ("language-text", "language-console"):
            doc = self._doc_with_code('<pre><code class="%s">plain content 123</code></pre>' % cls)
            errors, warnings = _validate_text(doc)
            self.assertEqual(errors, [], "expected no errors for %s, got: %r" % (cls, errors))
            self.assertFalse(any("syntax-highlighted" in w for w in warnings),
                             "%s should not be flagged, got: %r" % (cls, warnings))

    def test_code_block_without_language_is_not_flagged(self):
        doc = self._doc_with_code('<pre><code>just some plain code {}</code></pre>')
        self.assertOkNoWarn(doc)

    def test_normal_pre_cmskip_warns_CMH_VAL_12(self):
        doc = self._doc_with_code('<pre class="cm-skip"><code>just some plain code {}</code></pre>')
        self.assertWarn(doc, "will not be commentable")

    def test_normal_pre_code_cmskip_warns_CMH_VAL_12(self):
        doc = self._doc_with_code('<pre><code class="cm-skip">just some plain code {}</code></pre>')
        self.assertWarn(doc, "will not be commentable")

    def test_host_chrome_pre_cmskip_is_not_flagged_CMH_VAL_12(self):
        doc = build(body=[
            HANDLED_REGION,
            EMBEDDED_REGION,
            comment_ui('<pre class="cm-skip">host chrome</pre>\n'),
            MAIN,
            JS_REGION,
        ])
        errors, warnings = _validate_text(doc)
        self.assertEqual(errors, [], "expected no errors, got: %r" % errors)
        self.assertFalse(any("will not be commentable" in w for w in warnings),
                         "host chrome cm-skip should not be flagged: %r" % warnings)

    def test_inline_language_code_is_not_flagged(self):
        # Only block code (<pre><code>) is author-highlighted; an inline <code class="language-...">
        # in prose is never highlighted, so it must not be flagged.
        doc = self._doc_with_code('<p>see <code class="language-csharp">Foo.Bar()</code> inline</p>')
        self.assertOkNoWarn(doc)


if __name__ == "__main__":
    unittest.main()
