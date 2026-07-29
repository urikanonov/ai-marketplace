"""Direct unit tests for the parsed <pre>/<code> span tokenizer that CMH-VAL-11 and
CMH-KQL-08 share (checks/parsing.code_block_spans).

The end-to-end behavior of both checks is covered by test_validate_highlighting.py and
test_validate_kql.py; these pin the tokenizer contract itself - the offsets, the
raw-text/CDATA/comment boundaries, and the fail-closed `unclosed` flag - so a regression is
reported against the one component instead of only through its two callers.
"""

from _validate_helpers import *  # noqa: F401,F403  (unittest + sys.path wiring)

from checks.parsing import code_block_spans  # noqa: E402


class CodeBlockSpansTests(unittest.TestCase):
    def setUp(self):
        code_block_spans.cache_clear()

    def _spans(self, html):
        code_block_spans.cache_clear()
        return code_block_spans(html)

    def _inners(self, html):
        return [html[c["inner"][0]:c["inner"][1]]
                for pre in self._spans(html).pres for c in pre["codes"]
                if c["inner"] is not None]

    def test_inner_span_slices_the_original_document(self):
        html = '<p>x</p><pre><code class="language-python">a &lt;b&gt; c</code></pre>'
        self.assertEqual(self._inners(html), ["a &lt;b&gt; c"])

    def test_a_gt_inside_a_quoted_attribute_does_not_end_the_tag(self):
        html = '<pre title="a > b"><code title=\'x > y\' class="language-python">q</code></pre>'
        spans = self._spans(html)
        self.assertEqual(len(spans.pres), 1)
        self.assertEqual(spans.pres[0]["attrs"].get("title"), "a > b")
        self.assertEqual(spans.pres[0]["codes"][0]["attrs"].get("class"), "language-python")
        self.assertEqual(self._inners(html), ["q"])

    def test_raw_text_and_rcdata_bodies_hold_no_blocks(self):
        for elem in ("script", "style", "textarea", "title", "xmp", "iframe",
                     "noembed", "noframes", "noscript"):
            with self.subTest(elem=elem):
                html = "<%s><pre><code>x</code></pre></%s>" % (elem, elem)
                spans = self._spans(html)
                self.assertEqual(spans.pres, [], "%s body must contribute no block" % elem)
                self.assertFalse(spans.unclosed,
                                 "%s body must not look like a destroyed structure" % elem)

    def test_a_raw_text_body_does_not_hide_a_later_block(self):
        html = ('<textarea>see <pre><code class="language-python"></textarea>'
                '<pre><code class="language-python">real</code></pre>')
        self.assertEqual(self._inners(html), ["real"])

    def test_cdata_in_foreign_content_holds_no_block(self):
        html = ('<svg><![CDATA[ <pre><code class="language-python">quoted ]]></svg>'
                '<pre><code class="language-python">real</code></pre>')
        spans = self._spans(html)
        self.assertEqual(len(spans.pres), 1)
        self.assertFalse(spans.unclosed)
        self.assertEqual(self._inners(html), ["real"])

    def test_a_comment_holds_no_block(self):
        html = ('<!-- <pre><code class="language-python">quoted</code></pre> -->'
                '<pre><code class="language-python">real</code></pre>')
        self.assertEqual(self._inners(html), ["real"])

    def test_the_legacy_bang_comment_close_ends_the_comment(self):
        # `--!>` is the HTML comment-end-bang close. Missing it left the comment running to the
        # document's next `-->`, blanking every authored block between.
        html = ('<!-- quoted --!><pre><code class="language-python">real</code></pre>'
                '<!-- trailing -->')
        self.assertEqual(self._inners(html), ["real"])

    def test_an_abruptly_closed_comment_ends_at_its_own_close(self):
        for prefix in ("<!-->", "<!--->"):
            with self.subTest(prefix=prefix):
                html = prefix + '<pre><code class="language-python">real</code></pre>'
                self.assertEqual(self._inners(html), ["real"])

    def test_an_unclosed_pre_is_reported(self):
        self.assertTrue(self._spans('<div><pre><code>x</code></div>').unclosed)

    def test_an_unclosed_code_inside_a_closed_pre_is_reported(self):
        self.assertTrue(self._spans("<pre><code>x</pre>").unclosed)

    def test_a_raw_script_opened_inside_a_block_destroys_the_structure(self):
        # The browser's raw-text mode swallows `</code></pre>` the same way, so the script RUNS -
        # the shape the callers must fail CLOSED on rather than silently inspecting nothing.
        self.assertTrue(self._spans(
            '<pre><code class="language-python">x <script>alert(1)</code></pre>').unclosed)

    def test_a_well_formed_document_is_not_flagged_unclosed(self):
        self.assertFalse(self._spans(
            '<pre><code class="language-python">x</code></pre>').unclosed)

    def test_an_inline_code_outside_a_pre_is_not_a_block(self):
        spans = self._spans('<p>see <code class="language-python">x</code></p>')
        self.assertEqual(spans.pres, [])
        self.assertFalse(spans.unclosed)

    def test_a_block_inside_a_kql_figure_is_marked(self):
        html = ('<figure class="cmh-kql"><pre><code class="language-kusto">T</code></pre></figure>'
                '<pre><code class="language-kusto">U</code></pre>')
        spans = self._spans(html)
        self.assertEqual([p["in_kql_figure"] for p in spans.pres], [True, False])

    def test_a_self_closed_pre_still_needs_its_end_tag(self):
        # HTML5 ignores the trailing slash on a non-void element, so `<pre/>` opens an element.
        self.assertTrue(self._spans("<pre/><code>x</code>").unclosed)

    def test_the_result_is_cached_per_document(self):
        html = '<pre><code class="language-python">x</code></pre>'
        code_block_spans.cache_clear()
        self.assertIs(code_block_spans(html), code_block_spans(html))
        code_block_spans.cache_clear()


if __name__ == "__main__":
    unittest.main()
