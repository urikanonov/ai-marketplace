from _validate_helpers import *

import kql_highlight  # noqa: E402


# kusto is dispatched by the document highlight path (CMH-KQL-09), so a clean fixture
# carries real token spans exactly as a generated document does.
KQL_INNER = kql_highlight.highlight_inner("T | take 1")


class ValidateDiffAndKqlTests(ValidateAssertions, unittest.TestCase):
    def test_diff_block_is_tolerated(self):
        # A cmh-diff code-review block is authored content; the validator must
        # accept it (no false errors) and it must not disturb region/root checks.
        main_with_diff = (
            '<main id="commentRoot" data-cmh-content-root data-comment-key="k" data-doc-label="l" data-doc-source="s">\n'
            "  <p>content</p>\n"
            '  <pre class="cmh-diff" data-diff-label="a.py">@@ -1,2 +1,2 @@\n'
            " keep\n-old\n+new\n</pre>\n"
            "</main>"
        )
        body = [HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main_with_diff, JS_REGION]
        self.assertOkNoWarn(build(body=body))

    def test_diff_block_raw_html_errors_double_quoted_class(self):
        main = MAIN.replace("<p>content</p>", '<pre class="cmh-diff">@@ -1 +1 @@\n<img src=x>\n</pre>')
        self.assertError(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]),
                         "raw HTML tag")

    def test_diff_block_raw_html_errors_single_quoted_class(self):
        main = MAIN.replace("<p>content</p>", "<pre class='cmh-diff'>@@ -1 +1 @@\n<img src=x>\n</pre>")
        self.assertError(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]),
                         "raw HTML tag")

    def test_diff_block_raw_html_errors_unquoted_class(self):
        main = MAIN.replace("<p>content</p>", "<pre class=cmh-diff>@@ -1 +1 @@\n<img src=x>\n</pre>")
        self.assertError(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]),
                         "raw HTML tag")

    def test_diff_block_escaped_text_does_not_warn(self):
        main = MAIN.replace("<p>content</p>", '<pre class="cmh-diff">@@ -1 +1 @@\n-&lt;old&gt;\n+new\n</pre>')
        self.assertOkNoWarn(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]))

    def test_diff_block_reports_every_bad_block_in_one_pass(self):
        # Two offending diffs must both be surfaced (no early break) so the AI fixes
        # everything in a single validation iteration.
        two = ('<pre class="cmh-diff">@@ -1 +1 @@\n<img src=x>\n</pre>'
               '<pre class="cmh-diff">@@ -2 +2 @@\n<script>bad</script>\n</pre>')
        main = MAIN.replace("<p>content</p>", two)
        errors, _ = _validate_text(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]))
        raw = [e for e in errors if "raw HTML tag" in e]
        self.assertEqual(len(raw), 2, "both bad diff blocks should be reported, got: %r" % raw)
        self.assertIn("diff block #1", raw[0])
        self.assertIn("diff block #2", raw[1])

    def test_diff_block_class_is_read_the_way_a_browser_reads_it(self):
        # CMH-VAL-21 clause 11 (#1139). The 11b gate keys on `pre.cmh-diff`, which the layer
        # matches as a CSS SELECTOR, so it is matched by EXACT code points: `<pre class="CMH-DIFF">`
        # is not an authored diff block to a browser either (nothing renders it as one), so the
        # escaped-diff-text requirement does not apply to it.
        main = MAIN.replace("<p>content</p>", '<pre class="CMH-DIFF">@@ -1 +1 @@\n<img src=x>\n</pre>')
        errors, _ = _validate_text(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]))
        self.assertEqual([e for e in errors if "raw HTML tag" in e], [],
                         "an uppercase class is not `cmh-diff` in a standards-mode document")
        # A character reference IS decoded, exactly as `classList` decodes it, so this really is
        # a `cmh-diff` block and the gate must fire: reading the RAW text with a `class=` regex
        # missed it and failed a hard gate open.
        main = MAIN.replace("<p>content</p>",
                            '<pre class="cmh-&#100;iff">@@ -1 +1 @@\n<img src=x>\n</pre>')
        self.assertError(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]),
                         "raw HTML tag")

    def test_minimal_document_crlf_is_clean(self):
        errors, warnings = _validate_text(build(), crlf=True)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_kusto_run_link_valid_is_clean(self):
        link = ('<a class="cmh-kql-run" href="https://dataexplorer.azure.com/clusters/c/databases/d?query=H4sI" '
                'target="_blank" rel="noopener noreferrer">Run in Azure Data Explorer</a>')
        main = MAIN.replace("<p>content</p>", "<p>content</p>" + link)
        self.assertOkNoWarn(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]))

    def test_kusto_run_link_wrong_origin_warns(self):
        link = '<a class="cmh-kql-run" href="https://evil.example.com/x" target="_blank" rel="noopener">Run</a>'
        main = MAIN.replace("<p>content</p>", "<p>content</p>" + link)
        self.assertWarn(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]),
                        "does not point at https://dataexplorer.azure.com/")

    def test_kusto_run_link_blank_without_noopener_warns(self):
        link = ('<a class="cmh-kql-run" href="https://dataexplorer.azure.com/x" target="_blank">Run</a>')
        main = MAIN.replace("<p>content</p>", "<p>content</p>" + link)
        self.assertWarn(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]),
                        'without rel="noopener"')

    def test_kusto_run_link_rel_is_tokenized_the_way_html_tokenizes_it(self):
        # CMH-KQL-05: HTML splits a `rel` list on ASCII whitespace ONLY, so `noopener<U+000B>x` is
        # ONE opaque relation a browser never matches - `window.opener` stays exposed and the opened
        # page can navigate the document the reader is looking at. Python's argument-less
        # `str.split()` is Unicode-aware and additionally splits on the vertical tab, NBSP and
        # U+001C-U+001F, so it saw the token `noopener` and passed the gate on a link a browser
        # leaves unprotected. Read through the shared `link_rel_tokens` instead, so the gate and the
        # browser tokenize the same attribute the same way.
        for sep in ("\u000b", "\u00a0", "\u001c", "\u001f"):
            link = ('<a class="cmh-kql-run" href="https://dataexplorer.azure.com/x" '
                    'target="_blank" rel="noopener%sx">Run</a>' % sep)
            main = MAIN.replace("<p>content</p>", "<p>content</p>" + link)
            self.assertWarn(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]),
                            'without rel="noopener"')
        # The control: an ordinary ASCII-space-separated list really does name `noopener`, so it
        # must still pass - the fix must not turn a protected link into a false warning.
        link = ('<a class="cmh-kql-run" href="https://dataexplorer.azure.com/x" '
                'target="_blank" rel="noopener noreferrer">Run</a>')
        main = MAIN.replace("<p>content</p>", "<p>content</p>" + link)
        self.assertOkNoWarn(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]))

    def test_kusto_run_link_class_is_tokenized_the_way_html_tokenizes_it(self):
        # CMH-VAL-21 clause 11 (#1139), the FALSE-POSITIVE direction: 11c is a WARNING gate keyed
        # on the run-link class, so a class reader that sees more tokens than a browser warns about
        # a link that is not a run link at all. `class="cmh-kql-run\u000bx"` is ONE opaque class to
        # a browser - `.cmh-kql-run` never matches it - so nothing about it is a Run link and the
        # author has nothing to fix. Python's argument-less `str.split()` split it and warned.
        for sep in ("\u000b", "\u00a0", "\u001c", "\u001f"):
            link = ('<a class="cmh-kql-run%sx" href="https://evil.example.com/x" '
                    'target="_blank">Run</a>' % sep)
            main = MAIN.replace("<p>content</p>", "<p>content</p>" + link)
            _, warnings = _validate_text(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(),
                                                     main, JS_REGION]))
            self.assertEqual([w for w in warnings if "cmh-kql-run" in w], [],
                             "%r joins the class into one opaque token, so no run-link gate "
                             "applies" % sep)
        # The control: a real, ASCII-space-separated `cmh-kql-run` class still trips both arms.
        link = ('<a class="cmh-kql-run extra" href="https://evil.example.com/x" '
                'target="_blank">Run</a>')
        main = MAIN.replace("<p>content</p>", "<p>content</p>" + link)
        _, warnings = _validate_text(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(),
                                                 main, JS_REGION]))
        self.assertTrue([w for w in warnings if "does not point at https://dataexplorer.azure.com/" in w],
                        "the control must still be read as a run link: %r" % warnings)
        self.assertTrue([w for w in warnings if 'without rel="noopener"' in w],
                        "the control must still be read as a run link: %r" % warnings)

    def test_kusto_run_link_blank_target_is_read_the_way_a_browser_reads_it(self):
        # CMH-KQL-05: the condition is the one a browser applies - does the target open an AUXILIARY
        # browsing context, whose `window.opener` points back at this document? HTML matches the four
        # keywords ASCII case-insensitively and does NOT trim, so `_BLANK`, a padded ` _blank` (a
        # NAMED context) and any other name all keep an opener. A Python `==` against the literal
        # `_blank` saw none of them, so a run link carrying no `rel` at all passed in silence - and
        # this gate is the only control there is, because CMH-KQL-01 puts the run link inside
        # `figcaption.cm-skip`, which both the render-time stamper and `checks/links.py` skip.
        for target in ("_BLANK", "_Blank", " _blank ", "\t_blank\n", "\u00a0_blank",
                       "\u000b_blank", "win1", "_blank"):
            link = ('<a class="cmh-kql-run" href="https://dataexplorer.azure.com/x" '
                    'target="%s">Run</a>' % target)
            main = MAIN.replace("<p>content</p>", "<p>content</p>" + link)
            _, warnings = _validate_text(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]))
            self.assertTrue(any('without rel="noopener"' in w for w in warnings),
                            "%r: %r" % (target, warnings))
        # The controls: a target that navigates a context which ALREADY EXISTS hands the opened page
        # no opener, so none of these is this gate's business...
        for target in ("_self", "_TOP", "_parent", ""):
            link = ('<a class="cmh-kql-run" href="https://dataexplorer.azure.com/x" '
                    'target="%s">Run</a>' % target)
            main = MAIN.replace("<p>content</p>", "<p>content</p>" + link)
            _, warnings = _validate_text(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]))
            self.assertFalse(any('without rel="noopener"' in w for w in warnings),
                             "%r: %r" % (target, warnings))
        # ...and a NAME that resolves to a browsing context this document already declares navigates
        # THAT context, which gets no opener. Warning there would be a false positive, and taking the
        # advice would change behavior: `noopener` stops a named target reusing the frame.
        link = ('<a class="cmh-kql-run" href="https://dataexplorer.azure.com/x" '
                'target="win1">Run</a><iframe name="win1" title="f"></iframe>')
        main = MAIN.replace("<p>content</p>", "<p>content</p>" + link)
        _, warnings = _validate_text(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]))
        self.assertFalse(any('without rel="noopener"' in w for w in warnings), warnings)
        # ...and a `_BLANK` that does carry `noopener` is clean.
        link = ('<a class="cmh-kql-run" href="https://dataexplorer.azure.com/x" '
                'target="_BLANK" rel="noopener noreferrer">Run</a>')
        main = MAIN.replace("<p>content</p>", "<p>content</p>" + link)
        self.assertOkNoWarn(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]))

        # `_blank` stays the keyword even when a frame claims the name - HTML checks the keywords
        # FIRST - so the exemption above cannot be used to silence the gate.
        link = ('<a class="cmh-kql-run" href="https://dataexplorer.azure.com/x" '
                'target="_blank">Run</a><iframe name="_blank" title="f"></iframe>')
        main = MAIN.replace("<p>content</p>", "<p>content</p>" + link)
        _, warnings = _validate_text(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]))
        self.assertTrue(any('without rel="noopener"' in w for w in warnings), warnings)

    def test_kusto_run_link_target_is_the_effective_one_a_browser_resolves(self):
        # CMH-KQL-05: the operand is HTML's "get an element's target" - the EFFECTIVE target - not the
        # raw attribute. Two rules the raw read does not model, both shared with the runtime stamper
        # (CMH-LINK-01) through one reading:
        #   1. `<base target>` INHERITANCE: a run link with NO target of its own inherits the
        #      document's first `<base target>`, so in a `<base target="_blank">` document it opens an
        #      auxiliary context with a live `window.opener` while the raw read saw the absent value
        #      and stayed silent.
        #   2. The `<`-COERCION: a target containing BOTH an ASCII tab-or-newline and a U+003C is
        #      replaced by `_blank`, so `x\n<` is the keyword rather than a name.
        base = '<base target="%s">'
        run = ('<a class="cmh-kql-run" href="https://dataexplorer.azure.com/x"%s>Run</a>')

        def warnings_for(head_extra, link_extra, tail=""):
            main = MAIN.replace("<p>content</p>",
                                head_extra + "<p>content</p>" + (run % link_extra) + tail)
            _, warnings = _validate_text(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(),
                                                     main, JS_REGION]))
            return warnings

        # 1. Inherited from `<base target>`: the link carries no target at all and still opens a new tab.
        for inherited in ("_blank", "_BLANK", "win-that-does-not-exist"):
            warnings = warnings_for(base % inherited, "")
            self.assertTrue(any('without rel="noopener"' in w for w in warnings),
                            "%r: %r" % (inherited, warnings))
        # The link's OWN target wins over the base, in both directions: an explicit same-context
        # keyword is not overridden by a `_blank` base...
        warnings = warnings_for(base % "_blank", ' target="_self"')
        self.assertFalse(any('without rel="noopener"' in w for w in warnings), warnings)
        # ...and a same-context base does not excuse an explicit `_blank`.
        warnings = warnings_for(base % "_self", ' target="_blank"')
        self.assertTrue(any('without rel="noopener"' in w for w in warnings), warnings)
        # A base naming a context this document DECLARES navigates a frame that already exists, which
        # gets no opener - the same exemption an explicit name earns.
        warnings = warnings_for(base % "win1", "", '<iframe name="win1" title="f"></iframe>')
        self.assertFalse(any('without rel="noopener"' in w for w in warnings), warnings)
        # A same-context base keyword is inherited as such, so an untargeted link stays clean.
        for inherited in ("_self", "_parent", "_TOP", ""):
            warnings = warnings_for(base % inherited, "")
            self.assertFalse(any('without rel="noopener"' in w for w in warnings),
                             "%r: %r" % (inherited, warnings))
        # Only the FIRST `<base target>` is inherited; a later one is ignored, as HTML ignores it.
        warnings = warnings_for((base % "_self") + (base % "_blank"), "")
        self.assertFalse(any('without rel="noopener"' in w for w in warnings), warnings)

        # 2. The `<`-coercion. `x&#10;<` carries both an ASCII newline and a U+003C, so HTML replaces
        #    the name with `_blank` - and a coerced `_blank` is the KEYWORD, so a frame claiming the
        #    literal name cannot exempt it.
        for spelling in ("x&#10;&lt;", "&lt;&#9;x", "a&#13;b&lt;c"):
            warnings = warnings_for("", ' target="%s"' % spelling)
            self.assertTrue(any('without rel="noopener"' in w for w in warnings),
                            "%r: %r" % (spelling, warnings))
        warnings = warnings_for("", ' target="x&#10;&lt;"', '<iframe name="x&#10;&lt;" title="f"></iframe>')
        self.assertTrue(any('without rel="noopener"' in w for w in warnings), warnings)
        # The coercion needs BOTH characters: a `<` with no tab/newline is an ordinary name, and a
        # newline with no `<` likewise - each stays subject to the named-context exemption.
        for spelling, frame in (("x&lt;", '<iframe name="x&lt;" title="f"></iframe>'),
                                ("x&#10;y", '<iframe name="x&#10;y" title="f"></iframe>')):
            warnings = warnings_for("", ' target="%s"' % spelling, frame)
            self.assertFalse(any('without rel="noopener"' in w for w in warnings),
                             "%r: %r" % (spelling, warnings))
        # The coercion applies to an INHERITED target too - HTML runs it after the base lookup.
        warnings = warnings_for(base % "x&#10;&lt;", "", '<iframe name="x&#10;&lt;" title="f"></iframe>')
        self.assertTrue(any('without rel="noopener"' in w for w in warnings), warnings)

    def test_bare_kusto_without_no_cluster_marker_errors(self):
        # CMH-KQL-08: a bare KQL code block that is neither framed in a figure.cmh-kql (with a Run in
        # Azure Data Explorer link) nor explicitly marked data-cmh-kql-no-cluster is a hard error -
        # a KQL block must either run on a cluster or be a deliberate no-cluster snippet. Prefer
        # providing a cluster; the marker is the rare escape hatch.
        block = '<pre><code class="language-kusto">%s</code>' % KQL_INNER + '</pre>'
        main = MAIN.replace("<p>content</p>", "<p>content</p>" + block)
        self.assertError(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]),
                         "not runnable")

    def test_bare_kusto_with_no_cluster_marker_is_clean(self):
        # CMH-KQL-08: the explicit data-cmh-kql-no-cluster override marks a deliberate highlight-only
        # snippet (no known cluster to run it on), so it is validator-clean.
        block = '<pre data-cmh-kql-no-cluster><code class="language-kusto">%s</code>' % KQL_INNER + '</pre>'
        main = MAIN.replace("<p>content</p>", "<p>content</p>" + block)
        self.assertOkNoWarn(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]))

    def test_bare_kusto_inside_kql_figure_is_not_double_flagged(self):
        # CMH-KQL-08: the <pre><code class="language-kusto"> that lives inside a figure.cmh-kql is
        # covered by the figure run-link rule (11d), so it must NOT also be flagged as a bare block.
        fig = ('<figure class="cmh-kql"><figcaption class="cm-skip">'
               '<button class="cmh-kql-title" type="button">cluster</button>'
               '<a class="cmh-kql-run" href="https://dataexplorer.azure.com/x" '
               'target="_blank" rel="noopener noreferrer">Run in Azure Data Explorer</a></figcaption>'
               '<pre><code class="language-kusto">%s</code>' % KQL_INNER + '</pre></figure>')
        main = MAIN.replace("<p>content</p>", "<p>content</p>" + fig)
        self.assertOkNoWarn(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]))

    def test_bare_kusto_mention_in_style_is_not_a_false_positive(self):
        # CMH-KQL-08 must not scan <style>/<script>/comment bodies: a `<pre>` mentioned in a CSS
        # comment must not start a spurious match that swallows a later real KQL block (which broke
        # the report-taxi example the naive scan flagged).
        style = '<style>/* the mark lives inside <pre>/<code> language-kusto */ .x{color:red}</style>'
        fig = ('<figure class="cmh-kql"><figcaption class="cm-skip">'
               '<button class="cmh-kql-title" type="button">cluster</button>'
               '<a class="cmh-kql-run" href="https://dataexplorer.azure.com/x" '
               'target="_blank" rel="noopener noreferrer">Run in Azure Data Explorer</a></figcaption>'
               '<pre><code class="language-kusto">%s</code>' % KQL_INNER + '</pre></figure>')
        main = MAIN.replace("<p>content</p>", "<p>content</p>" + style + fig)
        self.assertOkNoWarn(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]))

    def test_kql_scan_is_not_blinded_by_a_script_named_inside_a_comment(self):
        # CMH-KQL-08 shares the tokenizer (checks/parsing.code_block_spans). A "<script" NAMED
        # INSIDE A COMMENT must not open a raw-text region that runs to the document's next real
        # </script> - the layer JS always supplies one - blanking the authored block, which let
        # an unrunnable KQL block silently pass this hard-ERROR gate.
        bare = ('<!-- move the <script> tag later -->'
                '<pre><code class="language-kusto">%s</code></pre>' % KQL_INNER)
        main = MAIN.replace("<p>content</p>", "<p>content</p>" + bare)
        doc = build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION])
        self.assertError(doc, "is not runnable")

    def test_kql_scan_pairs_the_script_opener_with_its_own_closer(self):
        # A raw-text region must end at its OWN closer: a <script> region that ended at a
        # `"</style>"` string literal left an unfinished `<pre>` that swallowed the real block.
        js = JS_REGION.replace(
            "<script>\n",
            '<script>\nvar css = "</style>";\nvar u = "<pre><code class=\'language-kusto\'>X";\n',
            1)
        bare = '<pre><code class="language-kusto">%s</code></pre>' % KQL_INNER
        main = MAIN.replace("<p>content</p>", "<p>content</p>" + bare)
        doc = build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), js, main])
        self.assertError(doc, "is not runnable")

    # ------------------------------------------------------------------ #
    # CMH-KQL-08 scan boundary: blocks come from PARSED element spans, so the
    # four blind spots a text scan had are closed (#759).
    # ------------------------------------------------------------------ #

    _RAW_TEXT_ELEMENTS = ("textarea", "title", "xmp", "iframe", "noembed", "noframes", "noscript")

    def _bare_kusto(self, pre_attrs=""):
        return ('<pre%s><code class="language-kusto">%s</code></pre>' % (pre_attrs, KQL_INNER))

    def _kql_content(self, html):
        main = MAIN.replace("<p>content</p>", "<p>content</p>" + html)
        return build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION])

    def test_a_raw_text_element_body_cannot_swallow_a_bare_kql_block(self):
        # #759 blind spot 1: every HTML raw-text / RCDATA element parses its content as
        # characters, so a `<pre data-cmh-kql-no-cluster>` quoted inside one is prose. A text
        # scan matched that quoted opener, saw its marker, skipped it - and consumed the real
        # block's closer on the way, so the unrunnable block passed this hard-ERROR gate.
        for elem in self._RAW_TEXT_ELEMENTS:
            with self.subTest(elem=elem):
                doc = self._kql_content(
                    '<%s>example: <pre data-cmh-kql-no-cluster><code class="language-kusto">'
                    'T</%s>\n' % (elem, elem)
                    + self._bare_kusto())
                self.assertError(doc, "is not runnable")

    def test_cdata_in_foreign_content_cannot_swallow_a_bare_kql_block(self):
        # #759 blind spot 2: inside <svg>/<math> a `<![CDATA[ ... ]]>` section is a declaration
        # whose content is character data, so a marked opener quoted there must neither be read
        # as authored markup nor swallow the real block that follows.
        doc = self._kql_content(
            '<svg class="cm-skip" aria-hidden="true">'
            '<![CDATA[ <pre data-cmh-kql-no-cluster><code class="language-kusto">T ]]></svg>\n'
            + self._bare_kusto())
        self.assertError(doc, "is not runnable")

    def test_the_legacy_comment_close_ends_the_comment_for_the_kql_scan(self):
        # #759 blind spot 3: `--!>` is a legal comment close, so markup after it is live. Not
        # recognizing it left the comment open to the document's next `-->` (the layer always
        # supplies one), blanking the authored block and silencing the runnable gate.
        doc = self._kql_content(
            '<!-- example: <pre><code class="language-kusto">T</code></pre> --!>\n'
            + self._bare_kusto())
        self.assertError(doc, "is not runnable")

    def test_a_gt_inside_a_quoted_attribute_does_not_hide_the_no_cluster_marker(self):
        # #759 blind spot 4: matching attributes with `[^>]*` ends the tag at the FIRST `>`, even
        # one inside a quoted value, so an explicit data-cmh-kql-no-cluster marker sitting after
        # such a value was never seen and a deliberate clusterless snippet was falsely rejected.
        doc = self._kql_content(self._bare_kusto(' title="a > b" data-cmh-kql-no-cluster'))
        self.assertOkNoWarn(doc)

    def test_a_failed_parse_is_a_hard_error(self):
        # CMH-KQL-08 is a hard gate, so an empty block list from a FAILED parse must not read as
        # "no unrunnable KQL found" - the tokenizer hands back no blocks and the rule refuses.
        doc = self._kql_content(self._bare_kusto())
        from checks import parsing as _parsing
        validate.code_block_spans.cache_clear()
        with mock.patch.object(_parsing._CodeSpanParser, "parse_document",
                               side_effect=RuntimeError("boom")):
            errors, _warnings = _validate_text(doc)
        validate.code_block_spans.cache_clear()
        self.assertTrue(any("could not be parsed to locate its KQL code blocks" in e
                            for e in errors),
                        "expected a fail-closed KQL error, got: %r" % errors)

    def test_kql_figure_without_run_link_errors(self):
        # A framed KQL figure MUST carry a Run in Azure Data Explorer link; a missing one
        # is a hard validation ERROR (not a warning) so the reader can always open the query.
        fig = ('<figure class="cmh-kql"><figcaption class="cm-skip">'
               '<button class="cmh-kql-title" type="button">cluster</button></figcaption>'
               '<pre><code class="language-kusto">%s</code>' % KQL_INNER + '</pre></figure>')
        main = MAIN.replace("<p>content</p>", "<p>content</p>" + fig)
        self.assertError(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]),
                         'figure.cmh-kql has no "Run in Azure Data Explorer" link')

    def test_kql_figure_with_run_link_is_clean(self):
        fig = ('<figure class="cmh-kql"><figcaption class="cm-skip">'
               '<button class="cmh-kql-title" type="button">cluster</button>'
               '<a class="cmh-kql-run" href="https://dataexplorer.azure.com/x" '
               'target="_blank" rel="noopener noreferrer">Run in Azure Data Explorer</a></figcaption>'
               '<pre><code class="language-kusto">%s</code>' % KQL_INNER + '</pre></figure>')
        main = MAIN.replace("<p>content</p>", "<p>content</p>" + fig)
        self.assertOkNoWarn(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]))

    def _kql_figure(self, run_link_html):
        return ('<figure class="cmh-kql"><figcaption class="cm-skip">'
                '<button class="cmh-kql-title" type="button">cluster</button>'
                + run_link_html +
                '</figcaption><pre><code class="language-kusto">%s</code>' % KQL_INNER + '</pre></figure>')

    def _kql_doc(self, fig):
        main = MAIN.replace("<p>content</p>", "<p>content</p>" + fig)
        return build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION])

    def test_a_quoted_gt_in_the_start_tag_does_not_hide_a_diff_or_kql_gate(self):
        # HTML lets a `>` sit inside a QUOTED attribute value, so a `[^>]*` scan truncated the
        # start tag before its class and both HARD gates then skipped an element a browser really
        # does render as a diff block / a framed KQL figure.
        main = MAIN.replace("<p>content</p>",
                            '<pre title="a>b" class="cmh-diff">@@ -1 +1 @@\n<img src=x>\n</pre>')
        self.assertError(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]),
                         "raw HTML tag")
        fig = ('<figure title="a>b" class="cmh-kql"><figcaption class="cm-skip">'
               '<button class="cmh-kql-title" type="button">cluster</button></figcaption>'
               '<pre><code class="language-kusto">%s</code></pre></figure>' % KQL_INNER)
        self.assertError(self._kql_doc(fig),
                         'figure.cmh-kql has no "Run in Azure Data Explorer" link')

    def test_a_kql_figure_nested_in_a_plain_figure_is_still_gated(self):
        # A plain outer `<figure>` used to consume the inner `cmh-kql` figure through the FIRST
        # `</figure>`, so the inner frame's missing Run link passed a hard gate in silence.
        inner = ('<figure class="cmh-kql"><figcaption class="cm-skip">'
                 '<button class="cmh-kql-title" type="button">cluster</button></figcaption>'
                 '<pre><code class="language-kusto">%s</code></pre></figure>' % KQL_INNER)
        self.assertError(self._kql_doc("<figure><figcaption>wrap</figcaption>%s</figure>" % inner),
                         'figure.cmh-kql has no "Run in Azure Data Explorer" link')

    def test_kql_figure_javascript_run_link_errors(self):
        # CMH-KQL-07 hardening: a PRESENT cmh-kql-run link with a non-https / non-ADX href on a
        # framed figure is a hard ERROR, not a warning - a javascript: URL must never pass.
        fig = self._kql_figure('<a class="cmh-kql-run" href="javascript:alert(1)">Run</a>')
        self.assertError(self._kql_doc(fig), "https://dataexplorer.azure.com/")

    def test_kql_figure_data_run_link_errors(self):
        fig = self._kql_figure('<a class="cmh-kql-run" href="data:text/html,x">Run</a>')
        self.assertError(self._kql_doc(fig), "https://dataexplorer.azure.com/")

    def test_kql_figure_http_non_adx_run_link_errors(self):
        fig = self._kql_figure('<a class="cmh-kql-run" href="http://dataexplorer.azure.com/x">Run</a>')
        self.assertError(self._kql_doc(fig), "https://dataexplorer.azure.com/")

    def test_kql_figure_lookalike_host_run_link_errors(self):
        # A look-alike host must not pass a substring test: parse the URL and require the host be
        # exactly dataexplorer.azure.com.
        fig = self._kql_figure('<a class="cmh-kql-run" href="https://dataexplorer.azure.com.evil.example/x">Run</a>')
        self.assertError(self._kql_doc(fig), "https://dataexplorer.azure.com/")

    def test_kql_figure_entity_encoded_javascript_run_link_errors(self):
        # The href is HTML-entity-decoded before parsing, so an encoded javascript: scheme is caught.
        fig = self._kql_figure('<a class="cmh-kql-run" href="&#106;avascript:alert(1)">Run</a>')
        self.assertError(self._kql_doc(fig), "https://dataexplorer.azure.com/")

    def test_kql_figure_run_link_only_in_query_text_errors_missing(self):
        # CMH-KQL-07: the run link must be a real <a class="cmh-kql-run"> element, not a raw
        # substring. A figure whose QUERY TEXT merely mentions "cmh-kql-run" (with no real link)
        # must be reported as MISSING the run link.
        fig = ('<figure class="cmh-kql"><figcaption class="cm-skip">'
               '<button class="cmh-kql-title" type="button">cluster</button></figcaption>'
               '<pre><code class="language-kusto">T | where note == "cmh-kql-run"</code></pre></figure>')
        self.assertError(self._kql_doc(fig), 'figure.cmh-kql has no "Run in Azure Data Explorer" link')

    def test_kql_figure_run_link_class_is_tokenized_the_way_html_tokenizes_it(self):
        # CMH-VAL-21 clause 11 (#1139), the UNDER-REJECTION direction: 11d is a PRESENCE
        # requirement, so a class reader that sees more tokens than a browser accepts a figure the
        # reader can never run. HTML splits a `class` on ASCII whitespace ONLY, so
        # `class="cmh-kql-run\u000bx"` is ONE opaque class: `.cmh-kql-run` never matches it, the
        # layer never styles or binds it, and no Run link is rendered at all. Python's
        # argument-less `str.split()` saw the token `cmh-kql-run` and passed the figure.
        for sep in ("\u000b", "\u00a0", "\u001c", "\u001f"):
            fig = self._kql_figure('<a class="cmh-kql-run%sx" href="https://dataexplorer.azure.com/x" '
                                   'target="_blank" rel="noopener noreferrer">Run</a>' % sep)
            self.assertError(self._kql_doc(fig),
                             'figure.cmh-kql has no "Run in Azure Data Explorer" link')
        # A Unicode fold is no way in either: U+212A KELVIN SIGN casefolds onto `k`, so
        # `cmh-\u212aql-run` was a run link for the validator and never for a browser.
        fig = self._kql_figure('<a class="cmh-\u212aql-run" href="https://dataexplorer.azure.com/x" '
                               'target="_blank" rel="noopener noreferrer">Run</a>')
        self.assertError(self._kql_doc(fig),
                         'figure.cmh-kql has no "Run in Azure Data Explorer" link')
        # The control: an ordinary ASCII-space-separated class really does name `cmh-kql-run`, so
        # the figure must still pass - the fix must not reject a document a browser renders.
        fig = self._kql_figure('<a class="cmh-kql-run extra" href="https://dataexplorer.azure.com/x" '
                               'target="_blank" rel="noopener noreferrer">Run</a>')
        self.assertOkNoWarn(self._kql_doc(fig))

    def test_kql_figure_class_is_matched_by_exact_code_points(self):
        # CMH-VAL-21 clause 11 (#1139): a standards-mode document matches a class selector by
        # EXACT code points, so `class="cmh-\u212aql"` is NOT a `.cmh-kql` figure - the frame the
        # gate assumes is there is not rendered. `casefold()` mapped U+212A KELVIN SIGN onto `k`
        # and read it as one, which is the FALSE-POSITIVE direction: it demanded a Run link on a
        # figure a reader never sees framed. Read exactly, the block is simply unframed, which
        # CMH-KQL-08 reports as what it is.
        fig = ('<figure class="cmh-\u212aql"><figcaption class="cm-skip">'
               '<button class="cmh-kql-title" type="button">cluster</button></figcaption>'
               '<pre><code class="language-kusto">%s</code></pre></figure>' % KQL_INNER)
        errors, _ = _validate_text(self._kql_doc(fig))
        self.assertFalse([e for e in errors if 'figure.cmh-kql has no' in e],
                         "a look-alike class is not a cmh-kql figure, got: %r" % errors)
        self.assertTrue([e for e in errors if "not runnable" in e or "figure.cmh-kql" in e],
                        "the block is unframed, so CMH-KQL-08 must report it: %r" % errors)

    def test_a_kql_figure_class_is_decoded_before_it_is_matched(self):
        # CMH-VAL-21 clause 11 (#1139): the raw-start-tag reader decodes character references, as
        # `classList` does, so `class="cmh-&#107;ql"` IS a framed KQL figure and its missing Run
        # link is the hard error it should be. Reading the raw text with a `class=` regex saw an
        # undecoded `cmh-&#107;ql`, so this document passed the gate a browser would have failed.
        fig = ('<figure class="cmh-&#107;ql"><figcaption class="cm-skip">'
               '<button class="cmh-kql-title" type="button">cluster</button></figcaption>'
               '<pre><code class="language-kusto">%s</code></pre></figure>' % KQL_INNER)
        self.assertError(self._kql_doc(fig),
                         'figure.cmh-kql has no "Run in Azure Data Explorer" link')

    def test_a_kusto_language_label_is_folded_ascii_only_not_matched_exactly(self):
        # The class LIST is tokenized exactly, but a `language-XXX` LABEL inside a token is read
        # as a LABEL, not matched as a CSS selector: the highlighter that consumes it and the
        # runtime's own `language-` pattern both fold it ASCII-insensitively, so `language-KUSTO`
        # must still be a KQL block - matching it exactly would have stopped CMH-KQL-08's "not
        # runnable" error firing on a block a reader still sees highlighted as Kusto.
        main = MAIN.replace("<p>content</p>",
                            '<pre><code class="language-KUSTO">T | take 1</code></pre>')
        self.assertError(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]),
                         "not runnable")
        # ...and the Unicode fold that is gone: U+212A must NOT become a `k`.
        main = MAIN.replace("<p>content</p>",
                            '<pre><code class="language-\u212austo">T | take 1</code></pre>')
        errors, _ = _validate_text(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]))
        self.assertEqual([e for e in errors if "not runnable" in e], [],
                         "a look-alike language label is not kusto, got: %r" % errors)


if __name__ == "__main__":
    unittest.main()
