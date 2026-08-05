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

    def test_kusto_run_link_blank_target_is_read_the_way_a_browser_reads_it(self):
        # CMH-KQL-05: HTML matches the `_blank` keyword ASCII case-insensitively, and the runtime
        # stamper trims the value before matching it, so `_BLANK` and a padded `_blank` both open a
        # new tab with an opener. A Python `==` against the literal missed every spelling but the
        # exact one, so the reverse-tabnabbing gate said nothing about a link carrying no `rel` at
        # all.
        for target in ("_BLANK", "_Blank", " _blank ", "\t_blank\n"):
            link = ('<a class="cmh-kql-run" href="https://dataexplorer.azure.com/x" '
                    'target="%s">Run</a>' % target)
            main = MAIN.replace("<p>content</p>", "<p>content</p>" + link)
            self.assertWarn(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]),
                            'without rel="noopener"')
        # The controls: a NAMED target is not the `_blank` keyword, so THIS gate stays silent about
        # it (`checks/links.py` already tells the author to use `_blank` instead)...
        link = ('<a class="cmh-kql-run" href="https://dataexplorer.azure.com/x" '
                'target="win1">Run</a>')
        main = MAIN.replace("<p>content</p>", "<p>content</p>" + link)
        _, warnings = _validate_text(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]))
        self.assertFalse(any('without rel="noopener"' in w for w in warnings), warnings)
        # ...and a real `_BLANK` that does carry `noopener` is clean.
        link = ('<a class="cmh-kql-run" href="https://dataexplorer.azure.com/x" '
                'target="_BLANK" rel="noopener noreferrer">Run</a>')
        main = MAIN.replace("<p>content</p>", "<p>content</p>" + link)
        self.assertOkNoWarn(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]))

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


if __name__ == "__main__":
    unittest.main()
