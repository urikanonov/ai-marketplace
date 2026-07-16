from _validate_helpers import *


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

    def test_bare_kusto_without_no_cluster_marker_errors(self):
        # CMH-KQL-08: a bare KQL code block that is neither framed in a figure.cmh-kql (with a Run in
        # Azure Data Explorer link) nor explicitly marked data-cmh-kql-no-cluster is a hard error -
        # a KQL block must either run on a cluster or be a deliberate no-cluster snippet. Prefer
        # providing a cluster; the marker is the rare escape hatch.
        block = '<pre><code class="language-kusto">T | take 1</code></pre>'
        main = MAIN.replace("<p>content</p>", "<p>content</p>" + block)
        self.assertError(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]),
                         "not runnable")

    def test_bare_kusto_with_no_cluster_marker_is_clean(self):
        # CMH-KQL-08: the explicit data-cmh-kql-no-cluster override marks a deliberate highlight-only
        # snippet (no known cluster to run it on), so it is validator-clean.
        block = '<pre data-cmh-kql-no-cluster><code class="language-kusto">T | take 1</code></pre>'
        main = MAIN.replace("<p>content</p>", "<p>content</p>" + block)
        self.assertOkNoWarn(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]))

    def test_bare_kusto_inside_kql_figure_is_not_double_flagged(self):
        # CMH-KQL-08: the <pre><code class="language-kusto"> that lives inside a figure.cmh-kql is
        # covered by the figure run-link rule (11d), so it must NOT also be flagged as a bare block.
        fig = ('<figure class="cmh-kql"><figcaption class="cm-skip">'
               '<button class="cmh-kql-title" type="button">cluster</button>'
               '<a class="cmh-kql-run" href="https://dataexplorer.azure.com/x" '
               'target="_blank" rel="noopener noreferrer">Run in Azure Data Explorer</a></figcaption>'
               '<pre><code class="language-kusto">T | take 1</code></pre></figure>')
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
               '<pre><code class="language-kusto">T | take 1</code></pre></figure>')
        main = MAIN.replace("<p>content</p>", "<p>content</p>" + style + fig)
        self.assertOkNoWarn(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]))

    def test_kql_figure_without_run_link_errors(self):
        # A framed KQL figure MUST carry a Run in Azure Data Explorer link; a missing one
        # is a hard validation ERROR (not a warning) so the reader can always open the query.
        fig = ('<figure class="cmh-kql"><figcaption class="cm-skip">'
               '<button class="cmh-kql-title" type="button">cluster</button></figcaption>'
               '<pre><code class="language-kusto">T | take 1</code></pre></figure>')
        main = MAIN.replace("<p>content</p>", "<p>content</p>" + fig)
        self.assertError(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]),
                         'figure.cmh-kql has no "Run in Azure Data Explorer" link')

    def test_kql_figure_with_run_link_is_clean(self):
        fig = ('<figure class="cmh-kql"><figcaption class="cm-skip">'
               '<button class="cmh-kql-title" type="button">cluster</button>'
               '<a class="cmh-kql-run" href="https://dataexplorer.azure.com/x" '
               'target="_blank" rel="noopener noreferrer">Run in Azure Data Explorer</a></figcaption>'
               '<pre><code class="language-kusto">T | take 1</code></pre></figure>')
        main = MAIN.replace("<p>content</p>", "<p>content</p>" + fig)
        self.assertOkNoWarn(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]))

    def _kql_figure(self, run_link_html):
        return ('<figure class="cmh-kql"><figcaption class="cm-skip">'
                '<button class="cmh-kql-title" type="button">cluster</button>'
                + run_link_html +
                '</figcaption><pre><code class="language-kusto">T | take 1</code></pre></figure>')

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
