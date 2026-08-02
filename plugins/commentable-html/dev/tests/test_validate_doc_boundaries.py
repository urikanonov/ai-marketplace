"""CMH-VAL-21: the document parser draws the SAME tokenizer boundaries as the code-block
tokenizer, on every interpreter.

`checks/parsing._DocParser` is the tolerant pass the chart, link, id, heading, meta and
anchor checks all read. It used to rely on `html.parser`'s native tables, so a `<canvas>`,
an `<a>` or an `id` written inside a `<textarea>`, a `<title>` or a `<noscript>` - or placed
after a `--!>` comment close - was read differently by different Pythons and differently from
the `<pre>`/`<code>` scans. These tests pin the shared boundary through the real consumers
(charts, links) and directly on the parser's collected view.
"""

from _validate_helpers import *  # noqa: F401,F403  (unittest + sys.path wiring)

from checks import parsing  # noqa: E402

# Every HTML raw-text / RCDATA element: its CONTENT is text a reader SEES, never markup.
RAW_TEXT_ELEMENTS = ("script", "style", "textarea", "title", "xmp", "iframe",
                     "noembed", "noframes", "noscript")

def _ids(html):
    return parsing._parse_document(html).all_ids


def _anchors(html):
    return parsing._parse_document(html).anchors


class DocParserRawTextTests(unittest.TestCase):
    """The raw-text / RCDATA set, applied explicitly so it does not drift with the host."""

    def test_a_raw_text_body_contributes_no_elements(self):
        for elem in RAW_TEXT_ELEMENTS:
            with self.subTest(elem=elem):
                html = '<div id="wrap"><%s><span id="quoted"></span></%s></div>' % (elem, elem)
                self.assertEqual(_ids(html), ["wrap"],
                                 "%s body must contribute no element" % elem)

    def test_a_raw_text_body_does_not_hide_a_later_element(self):
        html = ('<textarea>see <div id="quoted"></textarea>'
                '<div id="real"></div>')
        self.assertEqual(_ids(html), ["real"])

    def test_a_raw_text_closer_carrying_attributes_ends_the_region(self):
        # HTML closes a raw-text element on `</name` followed by whitespace, `/` or `>`, so
        # `</script data-x>` IS the end tag. Missing it ran the region on to the document's
        # next canonical closer and swallowed every element between.
        for closer in ("</script data-x>", "</script/>", "</script\n>"):
            with self.subTest(closer=closer):
                html = ('<script>var u = "<div id=\'quoted\'>";' + closer
                        + '<div id="real"></div>'
                        + "<script>var a = 1;</script>")
                self.assertEqual(_ids(html), ["real"])

    def test_a_raw_text_name_inside_foreign_content_is_parsed_normally(self):
        # An SVG <title> is not HTML's RCDATA <title>; only script/style stay raw text there.
        html = '<svg><title><div id="real"></div></title></svg>'
        self.assertEqual(_ids(html), ["real"])

    def test_an_unclosed_raw_text_element_runs_to_the_end_of_the_document(self):
        self.assertEqual(_ids('<div id="wrap"></div><noscript><div id="quoted">'), ["wrap"])

    def test_plaintext_swallows_the_rest_of_the_document(self):
        # A browser never leaves plaintext mode, not even for a `</plaintext>` that looks like a
        # closer, so everything after it is text - including the whole review layer.
        html = '<div id="wrap"></div><plaintext><div id="a"></plaintext><div id="b">'
        self.assertEqual(_ids(html), ["wrap"])

    def test_plaintext_is_incrementally_fed_the_same_way(self):
        # The feed()/close() path must resolve an unterminated construct exactly as
        # parse_document() does; close() is the end of the document either way.
        html = '<div id="wrap"></div><!-- note <div id="quoted">'
        p = parsing._DocParser(html)
        p.feed(html)
        p.close()
        self.assertEqual(p.all_ids, ["wrap"])


class DocParserCommentTests(unittest.TestCase):
    """The comment closes a BROWSER honours - and only those."""

    def test_the_legacy_bang_comment_close_ends_the_comment(self):
        html = '<!-- quoted --!><div id="real"></div><!-- trailing -->'
        self.assertEqual(_ids(html), ["real"])

    def test_an_abruptly_closed_comment_ends_at_its_own_close(self):
        for prefix in ("<!-->", "<!--->"):
            with self.subTest(prefix=prefix):
                self.assertEqual(_ids(prefix + '<div id="real"></div>'), ["real"])

    def test_a_spaced_comment_close_does_not_end_the_comment(self):
        # `-- >` does NOT close a comment (html.parser's pre-3.13 delegate accepts it, which
        # resurrects commented-out markup as live elements).
        html = '<!-- docs -- ><div id="quoted"></div> --><div id="real"></div>'
        self.assertEqual(_ids(html), ["real"])

    def test_an_unterminated_comment_runs_to_the_end_of_the_document(self):
        # A browser treats the rest of the document as comment data. Before 3.13 html.parser
        # resumes tokenizing after the next `>`, resurrecting markup it never renders.
        html = '<div id="wrap"></div><!-- note <i> <div id="quoted"></div>'
        self.assertEqual(_ids(html), ["wrap"])


class DocParserCdataTests(unittest.TestCase):
    """`<![CDATA[` opens a section only inside foreign content."""

    def test_cdata_outside_foreign_content_is_a_bogus_comment(self):
        # A browser ends the bogus comment at the very FIRST `>`, so the markup after it is
        # LIVE; consuming the whole marked section hid real elements from every check.
        html = '<div><![CDATA[ x > <div id="real"></div> ]]></div>'
        self.assertEqual(_ids(html), ["real"])

    def test_cdata_directly_inside_a_foreign_element_is_still_a_section(self):
        html = '<svg><![CDATA[ > <div id="quoted"></div> ]]></svg>'
        self.assertEqual(_ids(html), [])

    def test_cdata_at_an_html_integration_point_is_a_bogus_comment(self):
        html = ('<svg><foreignObject><div><![CDATA[><div id="real"></div>]]>'
                '</div></foreignObject></svg>')
        self.assertEqual(_ids(html), ["real"])

    def test_a_breakout_start_tag_ends_foreign_content(self):
        html = '<svg><p><![CDATA[><div id="real"></div>]]></p></svg>'
        self.assertEqual(_ids(html), ["real"])


class DocParserForeignContentTests(unittest.TestCase):
    """The foreign-content model the CDATA rule rests on."""

    def test_a_self_closed_foreign_element_is_recorded_but_not_left_open(self):
        # `<rect id="x"/>` IS an element (a browser puts it in the DOM), so its id counts; the
        # trailing slash really closes it in foreign content, so nothing stays open.
        html = '<svg><rect id="mark"/></svg><div id="after"></div>'
        self.assertEqual(_ids(html), ["mark", "after"])

    def test_a_self_closed_svg_root_does_not_stay_open(self):
        # A stale foreign current node would make the following `<![CDATA[` a real section and
        # hide live markup behind it.
        html = '<svg/><![CDATA[><div id="real"></div>]]>'
        self.assertEqual(_ids(html), ["real"])

    def test_a_void_self_closed_tag_still_closes_an_open_paragraph(self):
        # `<hr/>` is a p-closer, so the <div> after it is NOT inside the cm-skip <p>.
        html = ('<main id="commentRoot"><p class="cm-skip"><hr/>'
                '<a href="p.html" target="_self">x</a></main>')
        anchors = _anchors(html)
        self.assertEqual(len(anchors), 1)
        self.assertFalse(anchors[0]["skip"])

    def test_a_paragraph_is_not_closed_across_a_foreign_integration_point(self):
        # HTML5 button scope stops at `<foreignObject>`, so the <div> inside it must not pop the
        # <p> outside the <svg> (which would pop the svg with it and change every later verdict).
        html = ('<p class="cm-skip"><svg><foreignObject><div>'
                '<a href="p.html" target="_self">x</a></div></foreignObject></svg>'
                '<a href="q.html" target="_self">y</a></p>')
        anchors = _anchors(html)
        self.assertEqual(len(anchors), 2)
        self.assertTrue(all(a["skip"] for a in anchors))

    def test_an_html_element_named_like_a_foreign_scope_boundary_stops_nothing(self):
        # `<desc>` is a scope boundary only in the SVG namespace. In HTML it is an ordinary
        # unknown element, so the <div> after it really does close the <p> - treating it as a
        # boundary would leave the link wrongly marked cm-skip and suppress a real finding.
        html = ('<p class="cm-skip"><desc><div>'
                '<a href="p.html" target="_self">x</a></div>')
        anchors = _anchors(html)
        self.assertEqual(len(anchors), 1)
        self.assertFalse(anchors[0]["skip"])

    def test_an_svg_inside_annotation_xml_is_svg_not_mathml(self):
        # Its `<foreignObject>` is then a real HTML integration point, so a `<section>` under it
        # is HTML (it is not a breakout tag, so nothing else would put it there) and the CDATA
        # after it is a bogus comment whose trailing markup stays live.
        html = ('<math><annotation-xml><svg><foreignObject><section><![CDATA[>'
                '<div id="real"></div>]]></section></foreignObject></svg>'
                "</annotation-xml></math>")
        self.assertEqual(_ids(html), ["real"])

    def test_an_mglyph_inside_a_text_integration_point_stays_mathml(self):
        html = '<math><mi><mglyph><![CDATA[><div id="quoted"></div>]]></mglyph></mi></math>'
        self.assertEqual(_ids(html), [])

    def test_a_raw_text_closer_folds_ascii_case_only(self):
        # A browser matches an end-tag name ASCII-case-insensitively, so the Unicode long s does
        # NOT close a <script>; full Unicode folding would end the region early.
        html = '<script>var u = "</\u017fcript><div id=\'quoted\'>";</script><div id="real"></div>'
        self.assertEqual(_ids(html), ["real"])


class MarkerScanBoundaryTests(unittest.TestCase):
    """The marker scan and the document parser must agree on what a raw-text body is."""

    def test_a_region_marker_inside_a_raw_text_body_is_blanked(self):
        for elem in ("script", "textarea", "noscript", "title"):
            with self.subTest(elem=elem):
                html = ("<div><%s>\n<!-- BEGIN: commentable-html - CSS -->\n</%s></div>"
                        % (elem, elem))
                scan = parsing.content_marker_scan(html)
                self.assertEqual(len(scan), len(html))
                self.assertNotIn("BEGIN: commentable-html - CSS", scan)

    def test_a_real_marker_comment_survives_the_scan(self):
        html = "<div>\n<!-- BEGIN: commentable-html - CSS -->\n</div>"
        self.assertIn("BEGIN: commentable-html - CSS", parsing.content_marker_scan(html))


class DocParserAnchorTests(unittest.TestCase):
    """The same boundaries applied to the anchor collection check_links reads."""

    def test_an_anchor_quoted_in_a_raw_text_body_is_not_collected(self):
        for elem in RAW_TEXT_ELEMENTS:
            with self.subTest(elem=elem):
                html = ('<main id="commentRoot"><%s><a href="p.html" target="_self">x</a>'
                        "</%s></main>" % (elem, elem))
                self.assertEqual(_anchors(html), [])

    def test_an_anchor_after_a_bang_comment_close_is_collected(self):
        html = '<main id="commentRoot"><!-- x --!><a href="p.html" target="_self">x</a></main>'
        self.assertEqual(len(_anchors(html)), 1)


class ConsumerBoundaryTests(unittest.TestCase):
    """The end-to-end verdicts: a construct quoted inside a raw-text element must not steer a
    real check, and markup a browser keeps live must still be seen."""

    def _doc(self, content, kind="generic"):
        main = ('<main id="commentRoot" data-cmh-content-root data-comment-key="k" '
                'data-doc-label="l" data-doc-source="s">\n'
                + CONTENT_BEGIN + "\n" + content + "\n" + CONTENT_END + "\n</main>")
        return build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION],
                     kind=kind)

    def _result(self, content):
        return _validate_text(self._doc(content))

    def test_a_canvas_quoted_in_a_raw_text_body_is_not_a_chart(self):
        # The chart checks read parser.canvases: a canvas a reader only SEES as text has no
        # renderer and no cm-skip wrapper, so counting it raised two errors on a clean document.
        for elem in RAW_TEXT_ELEMENTS:
            with self.subTest(elem=elem):
                errors, _ = self._result('<p>see <%s><canvas id="c"></canvas></%s></p>'
                                         % (elem, elem))
                self.assertEqual(errors, [], errors)

    def test_a_same_tab_link_quoted_in_a_raw_text_body_is_not_flagged(self):
        for elem in RAW_TEXT_ELEMENTS:
            with self.subTest(elem=elem):
                errors, warnings = self._result(
                    '<p>see <%s><a href="page.html" target="_self">x</a></%s></p>' % (elem, elem))
                self.assertEqual(errors, [], errors)
                self.assertFalse(any("same tab" in w for w in warnings), warnings)

    def test_a_same_tab_link_after_a_raw_text_closer_with_attributes_is_flagged(self):
        errors, warnings = self._result(
            '<script>var u = "<a href=\'q.html\'>";</script data-x>'
            '<p><a href="page.html" target="_self">x</a></p>'
            "<script>var a = 1;</script>")
        self.assertEqual(errors, [], errors)
        self.assertTrue(any("same tab" in w for w in warnings), warnings)

    def test_a_same_tab_link_after_a_bang_comment_close_is_flagged(self):
        errors, warnings = self._result(
            '<!-- note --!><p><a href="page.html" target="_self">x</a></p><!-- tail -->')
        self.assertEqual(errors, [], errors)
        self.assertTrue(any("same tab" in w for w in warnings), warnings)

    def test_a_same_tab_link_behind_a_spaced_comment_close_is_not_flagged(self):
        errors, warnings = self._result(
            '<!-- docs -- ><p><a href="page.html" target="_self">x</a></p> -->')
        self.assertEqual(errors, [], errors)
        self.assertFalse(any("same tab" in w for w in warnings), warnings)

    def test_a_same_tab_link_after_a_cdata_opener_is_flagged(self):
        # Outside foreign content `<![CDATA[` is a bogus comment ending at the first `>`, so
        # the link after it is live markup a reviewer really clicks.
        errors, warnings = self._result(
            '<p><![CDATA[ x > <a href="page.html" target="_self">x</a> ]]></p>')
        self.assertEqual(errors, [], errors)
        self.assertTrue(any("same tab" in w for w in warnings), warnings)

    def test_a_clean_document_still_validates_clean(self):
        errors, warnings = self._result("<p>plain content</p>")
        self.assertEqual(errors, [], errors)
        self.assertEqual(warnings, [], warnings)


if __name__ == "__main__":
    unittest.main()
