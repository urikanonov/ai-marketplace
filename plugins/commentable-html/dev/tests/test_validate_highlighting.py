from _validate_helpers import *

from checks import highlighting  # noqa: E402


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

    def test_the_language_label_is_read_first_wins_and_folded_ascii_only(self):
        # CMH-VAL-21 clause 11 (#1139). Two pins on the label reader:
        # (a) it is a FIRST-WINS read, so it must answer the FIRST `language-*` token the author
        #     wrote. Reading it out of a `class_tokens` SET made the answer depend on the
        #     process's hash seed, so this document's verdict alternated run to run. The helper is
        #     asserted directly, in BOTH author orders: a set cannot satisfy both, while running
        #     one order N times in ONE process proves nothing (set order is stable per process).
        # (b) the label is folded ASCII-only, matching the highlighter that consumes it: an
        #     uppercase label is still that language, but U+212A KELVIN SIGN is not a `k`.
        self.assertEqual(
            highlighting._code_block_language({"class": "language-csharp language-text"}), "csharp")
        self.assertEqual(
            highlighting._code_block_language({"class": "language-text language-csharp"}), "text")
        doc = self._doc_with_code(
            '<pre><code class="language-csharp language-text">public sealed class X {}</code></pre>')
        self.assertWarn(doc, "is not syntax-highlighted")
        doc = self._doc_with_code(
            '<pre><code class="language-CSHARP">public sealed class X {}</code></pre>')
        self.assertWarn(doc, "is not syntax-highlighted")
        doc = self._doc_with_code(
            '<pre><code class="language-cshar\u212a">public sealed class X {}</code></pre>')
        self.assertOkNoWarn(doc)

    def test_a_kusto_language_label_is_read_first_wins_by_both_readers(self):
        # The KQL gate and the highlighting advisory must give the SAME effective language for a
        # block: reading the KQL side as set MEMBERSHIP made `class="language-csharp
        # language-kusto"` C# to the highlighter and Kusto to CMH-KQL-08, which then fired "not
        # runnable" on a block the reader sees as C#.
        doc = self._doc_with_code(
            '<pre><code class="language-csharp language-kusto">public sealed class X {}</code></pre>')
        errors, _ = _validate_text(doc)
        self.assertEqual([e for e in errors if "not runnable" in e], [],
                         "the first label wins, and it is not kusto: %r" % errors)

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

    # ----------------------------------------------------------------- #
    # CMH-VAL-11 scan boundary: <script>/<style> bodies and HTML comments
    # are never code the author wrote, so they are masked before the scan.
    # ----------------------------------------------------------------- #

    _CSS_MENTIONING_PRE = CSS_REGION.replace(
        ":root {", "/* Code-block highlights: the mark lives inside <pre>/<code>. */\n:root {", 1)
    _JS_MENTIONING_PRE = JS_REGION.replace(
        "<script>\n",
        "<script>\n// Treat the selection as code only inside a <pre> block (optionally\n"
        "// wrapping an inner <code>); an inline <code> in prose must not flip it.\n",
        1)

    def _doc_with_code_and_layer_prose(self, code_html):
        """The Shareable shape that hid the defect: the inlined layer CSS and JS both mention
        <pre> and <code> in prose, on either side of the author's real code block."""
        main = (
            '<main id="commentRoot" data-cmh-content-root data-comment-key="k" '
            'data-doc-label="l" data-doc-source="s">\n'
            + CONTENT_BEGIN + "\n" + code_html + "\n" + CONTENT_END + "\n</main>"
        )
        return build(css=self._CSS_MENTIONING_PRE,
                     body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main,
                           self._JS_MENTIONING_PRE])

    def test_layer_css_and_js_prose_does_not_blind_the_check(self):
        # CMH-VAL-11: a Shareable document inlines the layer CSS and JS, whose prose mentions
        # <pre> and <code>. Scanning the RAW document let one of those mentions start a greedy
        # match that swallowed the real block, so the check reported nothing at all and every
        # Shareable document shipped its raw blocks unflagged.
        doc = self._doc_with_code_and_layer_prose(
            '<pre><code class="language-python">def f(): return 1</code></pre>')
        self.assertWarn(doc, "is not syntax-highlighted")

    def test_a_code_block_quoted_inside_a_script_body_is_not_flagged(self):
        # The mirror of the rule above: markup quoted inside a <script> body is data, not
        # authored content, so a raw language-labelled block there must never be flagged.
        quoted = JS_REGION.replace(
            "<script>\n",
            '<script>\nvar tpl = "<pre><code class=\'language-python\'>def f(): pass'
            '</code></pre>";\n',
            1)
        doc = build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), MAIN, quoted])
        self.assertOkNoWarn(doc)

    def test_a_code_block_quoted_inside_an_html_comment_is_not_flagged(self):
        doc = self._doc_with_code(
            '<!-- example: <pre><code class="language-python">def f(): pass</code></pre> -->')
        self.assertOkNoWarn(doc)

    def test_a_script_named_inside_a_comment_does_not_mask_the_real_block(self):
        # The masking must run as ONE left-to-right pass. Masking <script>/<style> BEFORE
        # comments let a "<script" mentioned inside an authored comment open a mask that ran to
        # the document's next real </script> - in a Shareable document the layer JS always
        # supplies one - blanking the author's block and silencing the check all over again.
        doc = self._doc_with_code(
            '<!-- move the <script> tag later -->\n'
            '<pre><code class="language-python">def f(): return 1</code></pre>')
        self.assertWarn(doc, "is not syntax-highlighted")

    def test_a_comment_opened_inside_a_script_body_does_not_mask_the_real_block(self):
        # The mirror direction: a "<!--" that appears only inside script DATA is not a comment,
        # so it must not open a mask that swallows the block after it. (This direction was
        # already correct under the old two-pass order; it pins that a future swap to a
        # comments-first pass would not break it.)
        js = JS_REGION.replace("<script>\n", '<script>\nvar s = "<!-- not a comment";\n', 1)
        main = (
            '<main id="commentRoot" data-cmh-content-root data-comment-key="k" '
            'data-doc-label="l" data-doc-source="s">\n'
            + CONTENT_BEGIN + "\n"
            + '<pre><code class="language-python">def f(): return 1</code></pre>\n'
            + CONTENT_END + "\n</main>"
        )
        doc = build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), js, main])
        self.assertWarn(doc, "is not syntax-highlighted")

    def test_a_script_is_not_closed_by_a_style_closer(self):
        # The mask alternation must keep the opener/closer PAIRED. Without the backreference a
        # <script> region ended at a `"</style>"` string literal - which the layer's own export
        # code really does emit - so the tail of the script leaked back into the scan and its
        # unfinished `<pre>` swallowed the author's real block.
        js = JS_REGION.replace(
            "<script>\n",
            '<script>\nvar css = "</style>";\nvar u = "<pre><code class=\'language-python\'>X";\n',
            1)
        main = (
            '<main id="commentRoot" data-cmh-content-root data-comment-key="k" '
            'data-doc-label="l" data-doc-source="s">\n'
            + CONTENT_BEGIN + "\n"
            + '<pre><code class="language-python">def f(): return 1</code></pre>\n'
            + CONTENT_END + "\n</main>"
        )
        doc = build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), js, main])
        self.assertWarn(doc, "is not syntax-highlighted")

    def test_a_raw_text_closer_carrying_attributes_still_ends_the_mask(self):
        # HTML closes a raw-text element on `</script` followed by whitespace, `/` or `>`, so
        # `</script data-x>` and `</script/>` ARE the end tag (with a parse error for the
        # ignored attribute). A mask that only accepted `</script>` skipped the browser's real
        # closer and ran on to the next canonical one, swallowing the authored block. Checked at
        # the check level: the layer's own JS region separately requires a canonical `</script>`,
        # so a whole-document fixture cannot carry this shape.
        for closer in ("</script data-x>", "</script/>"):
            with self.subTest(closer=closer):
                html = ('<html><body><script>var u = "<pre><code class=\'language-python\'>X";'
                        + closer
                        + '<pre><code class="language-python">def f(): return 1</code></pre>'
                        + "<script>var a = 1;</script></body></html>")
                _errors, warnings = validate.check_code_highlighting(html)
                self.assertTrue(any("is not syntax-highlighted" in w for w in warnings),
                                "expected the real block to be seen, got: %r" % warnings)

    def test_a_mask_delimiter_inside_a_tag_attribute_opens_no_mask(self):
        # A browser recognizes `<script` and `<!--` only in the DATA state, so a delimiter sitting
        # inside another tag's quoted attribute value is just text. Letting it open a mask blanked
        # everything up to the layer's next real closer, hiding the authored block.
        for attr in ('title="<script fake"', 'title="<!-- x"'):
            with self.subTest(attr=attr):
                doc = self._doc_with_code(
                    '<div %s>hi</div>'
                    '<pre><code class="language-python">def f(): return 1</code></pre>' % attr)
                self.assertWarn(doc, "is not syntax-highlighted")

    def test_a_pre_swallowed_by_a_raw_script_fails_closed(self):
        # A raw <script> (or <!--) opened INSIDE a code block and closed outside it blanks the
        # intervening </code> (and maybe the </pre>), so the block would vanish from the scan -
        # and the browser's raw-text mode swallows those closers the same way, so the script RUNS.
        # Both levels must be detected: the second case closes the script BEFORE </pre>, leaving
        # the <pre> perfectly paired while the <code> inside it is destroyed.
        for inner in ('<pre><code class="language-python">x <script>alert(1)</code></pre>',
                      '<pre><code class="language-python">x<script>alert(1);/*</code>*/'
                      '</script></pre>'):
            with self.subTest(inner=inner):
                doc = self._doc_with_code(inner)
                _errors, warnings = _validate_text(doc)
                hits = [w for w in warnings if "no matching closing tag" in w]
                self.assertTrue(hits, "expected an unpaired-element warning, got: %r" % warnings)
                for w in hits:
                    self.assertFalse(validate.is_advisory(w), "this must stay fatal, got: %r" % w)

    def test_the_block_payload_is_read_from_the_original_document(self):
        # The tokenizer only LOCATES blocks; the language, emptiness and highlight state must
        # be decided on the bytes that ship. Reading the masked bytes made a block whose inner
        # is a raw <script> look empty, so the rawest shape of all was silently skipped.
        doc = self._doc_with_code(
            '<pre><code class="language-python">&lt;ok&gt;<script>alert(1)</script></code></pre>')
        errors, warnings = _validate_text(doc)
        self.assertEqual(errors, [], "expected no errors, got: %r" % errors)
        self.assertTrue(any("markup the highlighter did not emit" in w for w in warnings),
                        "expected the block to be inspected, got: %r" % warnings)

    # ------------------------------------------------------------------ #
    # CMH-VAL-11 scan boundary: blocks come from PARSED element spans, so the
    # four blind spots a text scan had are closed (#759).
    # ------------------------------------------------------------------ #

    _RAW_TEXT_ELEMENTS = ("textarea", "title", "xmp", "iframe", "noembed", "noframes", "noscript")

    def test_a_raw_text_element_body_cannot_swallow_the_real_block(self):
        # #759 blind spot 1: <script>/<style> were not the only elements whose body is TEXT.
        # Every HTML raw-text / RCDATA element parses its content as characters, so a
        # `<pre><code class="language-python">` mentioned inside one is prose, not authored
        # markup - and a text scan let that mention start a match that ran to the author's real
        # closer, hiding the raw block behind it.
        for elem in self._RAW_TEXT_ELEMENTS:
            with self.subTest(elem=elem):
                doc = self._doc_with_code(
                    '<%s>docs mention <pre><code class="language-python"></%s>\n' % (elem, elem)
                    + '<pre><code class="language-python">def f(): return 1</code></pre>')
                _errors, warnings = _validate_text(doc)
                self.assertTrue(any("is not syntax-highlighted" in w for w in warnings),
                                "%s body hid the real block, got: %r" % (elem, warnings))
                self.assertFalse(any("no matching closing tag" in w for w in warnings),
                                 "%s body must not look like a destroyed structure, got: %r"
                                 % (elem, warnings))

    def test_cdata_in_foreign_content_cannot_swallow_the_real_block(self):
        # #759 blind spot 2: inside <svg>/<math> a `<![CDATA[ ... ]]>` section is a declaration
        # whose content is character data. A text scan both flagged the block quoted there and
        # let its unpaired opener swallow the author's real (already highlighted) block.
        doc = self._doc_with_code(
            '<svg class="cm-skip" aria-hidden="true">'
            '<![CDATA[ <pre><code class="language-python"> ]]></svg>\n'
            '<pre><code class="language-python">'
            '<span class="cmh-code-kw">def</span> f(): <span class="cmh-code-kw">return</span> 1'
            '</code></pre>')
        self.assertOkNoWarn(doc)

    def test_the_legacy_comment_close_ends_the_comment(self):
        # #759 blind spot 3: `--!>` is a legal comment close (the HTML comment-end-bang state).
        # Not recognizing it left the comment "open" to the document's NEXT `-->` - the layer
        # always supplies one - blanking the authored block between and silencing the check.
        doc = self._doc_with_code(
            '<!-- example: <pre><code class="language-python">x</code></pre> --!>\n'
            '<pre><code class="language-python">def f(): return 1</code></pre>')
        self.assertWarn(doc, "is not syntax-highlighted")

    def test_a_gt_inside_a_quoted_attribute_does_not_truncate_the_tag(self):
        # #759 blind spot 4: matching attributes with `[^>]*` ends the tag at the FIRST `>`, even
        # one sitting inside a quoted value. That truncated the attribute text, so the
        # `language-python` token was never seen and the raw block was skipped entirely.
        doc = self._doc_with_code(
            '<pre title="a > b"><code title="x > y" class="language-python">'
            'def f(): return 1</code></pre>')
        self.assertWarn(doc, "is not syntax-highlighted")

    def test_hand_written_markup_in_a_code_block_is_an_advisory(self):
        # CMH-VAL-11: a deliberately hand-written code block is legitimate - the authoring tools
        # leave it exactly as written - so the author can never clear this finding. It is reported
        # as an ADVISORY so it never blocks a fail-closed tool and never withholds the stamp.
        doc = self._doc_with_code(
            '<pre><code class="language-python">x = <mark>1</mark></code></pre>')
        errors, warnings = _validate_text(doc)
        self.assertEqual(errors, [], "expected no errors, got: %r" % errors)
        hits = [w for w in warnings if "markup the highlighter did not emit" in w]
        self.assertTrue(hits, "expected a hand-written-markup warning, got: %r" % warnings)
        for w in hits:
            self.assertTrue(validate.is_advisory(w), "expected an advisory warning, got: %r" % w)

    def test_the_advisory_wording_asks_for_no_remediation(self):
        # An advisory-only document is DONE, so the message must not repeat the fatal branch's
        # "fix the markup" remediation for markup the tools deliberately keep verbatim.
        doc = self._doc_with_code(
            '<pre><code class="language-python">x = <mark>1</mark></code></pre>')
        _errors, warnings = _validate_text(doc)
        hits = [w for w in warnings if validate.is_advisory(w)]
        self.assertTrue(hits, warnings)
        for w in hits:
            self.assertIn("preserved verbatim", w)
            self.assertIn("no action is needed", w)
            self.assertNotIn("fix the markup", w)

    def test_non_inert_markup_in_a_code_block_stays_fatal(self):
        # The other side of the advisory line: a <pre> body is parsed as MARKUP, so a raw
        # <script>, an <img onerror>, or a javascript: link in a code block executes. That is an
        # escaping bug, not hand highlighting, so it must keep blocking a fail-closed caller.
        # The unquoted-attribute and entity-encoded cases are the evasions a whole-tag allowlist
        # closes and an attribute scanner does not: mis-reading where one tag ends hides the next.
        for inner in ('<script>alert(1)</script>',
                      '<img src=x onerror="alert(1)">',
                      '<a href="javascript:alert(1)">x</a>',
                      '<a href="&#106;avascript:alert(1)">x</a>',
                      '<iframe src="evil"></iframe>',
                      "<b x=1'><script>alert(1)</script>'</b>",
                      '<span style="background:url(https://evil.example/x)">x</span>',
                      '<span is="x-probe">x</span>',
                      '<span data-onerror="nope">x</span>',
                      '<!doctype html>'):
            with self.subTest(inner=inner):
                doc = self._doc_with_code(
                    '<pre><code class="language-python">%s</code></pre>' % inner)
                _errors, warnings = _validate_text(doc)
                hits = [w for w in warnings
                        if "markup the highlighter did not emit" in w or "no matching </pre>" in w]
                self.assertTrue(hits, "expected a warning for %r, got: %r" % (inner, warnings))
                for w in hits:
                    self.assertFalse(validate.is_advisory(w),
                                     "%r must stay fatal, got advisory: %r" % (inner, w))

    def test_escaped_code_text_mentioning_a_handler_stays_advisory(self):
        # Text BETWEEN inert tags is escaped source, not markup. Scanning the whole inner for
        # "onclick=" / "javascript:" made an ordinary JS sample fatal with an "escape it"
        # message the author could not act on - the block is already escaped.
        for inner in ('btn.onclick = () =&gt; alert(1)',
                      '<mark>btn.onclick</mark> = handler',
                      'link.href = &quot;javascript:void(0)&quot;'):
            with self.subTest(inner=inner):
                doc = self._doc_with_code(
                    '<pre><code class="language-javascript">%s</code></pre>' % inner)
                _errors, warnings = _validate_text(doc)
                for w in warnings:
                    if "markup the highlighter did not emit" in w:
                        self.assertTrue(validate.is_advisory(w),
                                        "%r must stay advisory, got fatal: %r" % (inner, w))

    def test_the_theme_contrast_advisory_is_not_globally_exempt(self):
        # CMH-THEME-02's near-miss band ships a concrete --suggest fix, so it IS clearable and
        # must keep failing --strict. Only retrofit carves it out (its own long-standing rule).
        self.assertNotIn(validate.ADVISORY_PREFIX, validate.ADVISORY_PREFIXES)
        self.assertFalse(validate.is_advisory(validate.ADVISORY_PREFIX + "near miss"))

    def test_the_not_highlighted_warning_stays_fatal(self):
        # The other half of the split: a raw block IS fixable (bake it), so it stays fatal and
        # keeps blocking retrofit / content_replace.
        doc = self._doc_with_code(
            '<pre><code class="language-python">def f(): return 1</code></pre>')
        _errors, warnings = _validate_text(doc)
        hits = [w for w in warnings if "is not syntax-highlighted" in w]
        self.assertTrue(hits, "expected a raw-block warning, got: %r" % warnings)
        for w in hits:
            self.assertFalse(validate.is_advisory(w), "expected a fatal warning, got: %r" % w)
        fatal, advisory = validate.partition_warnings(warnings)
        self.assertEqual(advisory, [])
        self.assertEqual(fatal, warnings)


if __name__ == "__main__":
    unittest.main()
