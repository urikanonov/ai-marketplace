"""Direct unit tests for the parsed <pre>/<code> span tokenizer that CMH-VAL-11 and
CMH-KQL-08 share (checks/parsing.code_block_spans).

The end-to-end behavior of both checks is covered by test_validate_highlighting.py and
test_validate_kql.py; these pin the tokenizer contract itself - the offsets, the
raw-text/CDATA/comment boundaries, and the fail-closed `unclosed` flag - so a regression is
reported against the one component instead of only through its two callers.
"""

from _validate_helpers import *  # noqa: F401,F403  (unittest + sys.path wiring)

from checks import parsing  # noqa: E402
from checks.parsing import code_block_spans  # noqa: E402


class CodeBlockSpansTests(unittest.TestCase):
    def setUp(self):
        code_block_spans.cache_clear()

    def tearDown(self):
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
                self.assertEqual(spans.pres, (), "%s body must contribute no block" % elem)
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

    def test_cdata_outside_foreign_content_is_a_bogus_comment(self):
        # Only inside <svg>/<math> is `<![CDATA[` a CDATA section. In ordinary HTML a browser
        # treats `<!` + junk as a bogus comment that ends at the FIRST `>`, so the block after it
        # is LIVE - consuming the whole marked section there would hide a real code block.
        html = ('<div><![CDATA[ x > <pre><code class="language-python">real</code></pre> ]]></div>')
        self.assertEqual(self._inners(html), ["real"])

    def test_a_cdata_opener_immediately_followed_by_gt_hides_nothing(self):
        # The tightest form of the bypass: `<![CDATA[>` closes the bogus comment at once, so
        # everything after it is live markup a browser really renders.
        html = '<![CDATA[><pre><code class="language-kusto">evil</code></pre>]]>'
        self.assertEqual(self._inners(html), ["evil"])

    def test_cdata_at_an_html_integration_point_is_a_bogus_comment(self):
        # An HTML integration point puts its CHILDREN in the HTML namespace, and `<![CDATA[` is a
        # section only when the CURRENT NODE is foreign. So inside a `<div>` under a
        # `<foreignObject>` it is a bogus comment ending at the first `>`, and the block is LIVE.
        for host in ("foreignObject", "desc", "title"):
            with self.subTest(host=host):
                html = ('<svg><%s><div><![CDATA[><pre><code class="language-python">real'
                        '</code></pre>]]></div></%s></svg>' % (host, host))
                self.assertEqual(self._inners(html), ["real"])

    def test_cdata_directly_inside_a_foreign_element_is_still_a_section(self):
        # The current node there is the SVG element itself, which IS foreign, so a browser really
        # does open a CDATA section - reading its quoted markup as live would be a false positive.
        html = '<svg><foreignObject><![CDATA[><pre><code class="language-python">q</code></pre>]]>'
        self.assertEqual(self._spans(html).pres, ())

    def test_annotation_xml_is_an_integration_point_only_with_an_html_encoding(self):
        # Without `encoding="text/html"` its contents stay MathML foreign content, so the CDATA
        # section there is real; with one, its children are HTML and the block after `>` is live.
        bare = ('<math><annotation-xml><![CDATA[><pre><code class="language-python">q'
                '</code></pre>]]></annotation-xml></math>')
        self.assertEqual(self._spans(bare).pres, ())
        html_enc = ('<math><annotation-xml encoding="text/html"><div><![CDATA[>'
                    '<pre><code class="language-python">real</code></pre>]]></div>'
                    '</annotation-xml></math>')
        self.assertEqual(self._inners(html_enc), ["real"])

    def test_a_breakout_start_tag_ends_foreign_content(self):
        # A browser pops the open foreign elements at an HTML breakout start tag, so the CDATA
        # after it is a bogus comment and the block is live. Keeping a stale `svg` on the stack
        # hid a real block from BOTH guardrails.
        html = ('<svg><p><![CDATA[><pre><code class="language-python">real</code></pre>]]>'
                '</p></svg>')
        self.assertEqual(self._inners(html), ["real"])

    def test_a_raw_text_name_inside_foreign_content_is_parsed_normally(self):
        # An SVG `<title>` is not HTML's RCDATA `<title>`; only script/style stay raw text there.
        html = '<svg><title><div><pre><code class="language-python">real</code></pre></div></title></svg>'
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
        self.assertEqual(spans.pres, ())
        self.assertFalse(spans.unclosed)

    def test_a_block_inside_a_kql_figure_is_marked(self):
        html = ('<figure class="cmh-kql"><pre><code class="language-kusto">T</code></pre></figure>'
                '<pre><code class="language-kusto">U</code></pre>')
        spans = self._spans(html)
        self.assertEqual([p["in_kql_figure"] for p in spans.pres], [True, False])

    def test_the_kql_figure_class_match_is_case_insensitive(self):
        # The raw-attribute helper this replaced matched class tokens case-insensitively; an exact
        # match would make an uppercase class a spurious FATAL "not runnable" error.
        html = '<figure class="CMH-KQL"><pre><code class="language-kusto">T</code></pre></figure>'
        self.assertEqual([p["in_kql_figure"] for p in self._spans(html).pres], [True])

    def test_a_block_level_start_tag_closes_an_open_p_before_it_nests(self):
        # HTML5 closes an open <p> when <figure> starts, so the later stray </p> pops nothing and
        # the block really is inside the figure. Popping the figure with that </p> instead would
        # judge a framed KQL block unframed.
        html = ('<p><figure class="cmh-kql"></p>'
                '<pre><code class="language-kusto">T</code></pre></figure>')
        self.assertEqual([p["in_kql_figure"] for p in self._spans(html).pres], [True])

    def test_a_p_is_not_closed_across_a_scope_boundary(self):
        # The implicit close must respect HTML5 scope: a <div> inside a <table> cell does not
        # reach back past the table to close a <p> outside it.
        html = ('<p><table><td><div>'
                '<pre><code class="language-python">real</code></pre></div></td></table>')
        self.assertEqual(self._inners(html), ["real"])

    def test_a_self_closed_pre_still_needs_its_end_tag(self):
        # HTML5 ignores the trailing slash on a non-void element, so `<pre/>` opens an element.
        self.assertTrue(self._spans("<pre/><code>x</code>").unclosed)

    def test_a_raw_text_closer_carrying_attributes_ends_the_region(self):
        # HTML closes a raw-text element on `</name` followed by whitespace, `/` or `>`, so
        # `</script data-x>` and `</script/>` ARE the end tag. html.parser only honours the
        # canonical `</script>` before 3.13, so the parser must apply this boundary itself or the
        # region runs on to the document's next canonical closer and swallows the real block.
        for closer in ("</script data-x>", "</script/>", "</script\n>"):
            with self.subTest(closer=closer):
                html = ('<script>var u = "<pre><code class=\'language-python\'>X";' + closer
                        + '<pre><code class="language-python">real</code></pre>'
                        + "<script>var a = 1;</script>")
                self.assertEqual(self._inners(html), ["real"])

    def test_a_style_closer_does_not_end_a_script_region(self):
        # The closer must be the region's OWN element: a `"</style>"` string literal inside a
        # script - which the layer's export code really emits - must not end the script.
        html = ('<script>var css = "</style>"; var u = "<pre><code class=\'language-python\'>X";'
                "</script>"
                '<pre><code class="language-python">real</code></pre>')
        self.assertEqual(self._inners(html), ["real"])

    def test_a_spaced_comment_close_does_not_end_the_comment(self):
        # Only `-->` / `--!>` close a comment; `-- >` does not (html.parser's pre-3.13 delegate
        # accepts it, which would resurrect commented-out markup as a live block).
        html = ('<!-- docs -- ><pre><code class="language-python">quoted</code></pre> -->'
                '<pre><code class="language-python">real</code></pre>')
        self.assertEqual(self._inners(html), ["real"])

    def test_an_unterminated_comment_runs_to_the_end_of_the_document(self):
        # A browser treats the rest of the document as comment data. Before 3.13 html.parser
        # resumes tokenizing after the next `>`, which resurrects markup a browser never renders.
        html = '<!-- note <i> <pre><code class="language-python">x</code></pre>'
        spans = self._spans(html)
        self.assertEqual(spans.pres, ())
        self.assertFalse(spans.unclosed)

    def test_void_elements_do_not_accumulate_on_the_element_stack(self):
        html = "<br>" * 500 + '<pre><code class="language-python">real</code></pre>'
        self.assertEqual(self._inners(html), ["real"])

    def test_a_parse_failure_reports_no_blocks_and_flags_the_failure(self):
        # A partial block list would let a check conclude the rest of the document is clean.
        html = '<pre><code class="language-python">x</code></pre>'
        code_block_spans.cache_clear()
        with mock.patch.object(parsing._CodeSpanParser, "parse_document",
                               side_effect=RuntimeError("boom")):
            spans = code_block_spans(html)
        code_block_spans.cache_clear()
        self.assertEqual(spans.pres, ())
        self.assertTrue(spans.unclosed)
        self.assertTrue(spans.failed)

    def test_the_records_are_read_only(self):
        # The result is CACHED and shared between checks, so a consumer that stamped a field on a
        # record - or on its nested attribute mapping - would silently poison the next check's
        # view of the same document.
        spans = self._spans('<pre><code class="language-python">x</code></pre>')
        with self.assertRaises(TypeError):
            spans.pres[0]["in_kql_figure"] = True
        with self.assertRaises(TypeError):
            spans.pres[0]["attrs"]["class"] = "x"
        with self.assertRaises(TypeError):
            spans.pres[0]["codes"][0]["attrs"] = {}
        with self.assertRaises(TypeError):
            spans.pres[0]["codes"][0]["attrs"]["class"] = "language-kusto"

    def test_the_result_is_cached_per_document(self):
        html = '<pre><code class="language-python">x</code></pre>'
        code_block_spans.cache_clear()
        self.assertIs(code_block_spans(html), code_block_spans(html))
        code_block_spans.cache_clear()


if __name__ == "__main__":
    unittest.main()
