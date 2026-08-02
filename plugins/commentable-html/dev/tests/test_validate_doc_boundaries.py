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

import contextlib  # noqa: E402
import html as _html  # noqa: E402
import html.parser as _html_parser  # noqa: E402
from html.parser import HTMLParser  # noqa: E402
from unittest import mock  # noqa: E402

from checks import checklist, notes, parsing  # noqa: E402

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
        # The feed()/close() path must resolve a never-closing construct exactly as
        # parse_document() does; close() is the end of the document either way.
        html = '<div id="wrap"></div><plaintext><div id="a"></plaintext><div id="b">'
        p = parsing._DocParser(html)
        p.feed(html)
        p.close()
        self.assertEqual(p.all_ids, ["wrap"])

    def test_a_zero_width_root_does_not_swallow_its_later_siblings(self):
        # A self-closed foreign element and a void element have no CONTENT, so a later sibling is
        # not inside them - reading it as inside would let CONTENT markers a browser puts OUTSIDE
        # an empty #commentRoot define the region.
        for root in ('<svg id="commentRoot"/>', '<img id="commentRoot">'):
            with self.subTest(root=root):
                parser = parsing._parse_document(
                    root + "<section><h2>Later</h2></section>")
                self.assertTrue(parser.has_comment_root)
                self.assertEqual(parser.headings, [])


class DocParserCommentTests(unittest.TestCase):
    """The comment closes a BROWSER honours - and only those."""

    def test_an_unterminated_comment_is_resolved_the_same_way_when_fed_incrementally(self):
        html = '<div id="wrap"></div><!-- note <div id="quoted">'
        p = parsing._DocParser(html)
        p.feed(html)
        p.close()
        self.assertEqual(p.all_ids, ["wrap"])

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


class DocParserAttributeValueTests(unittest.TestCase):
    """Attribute-value character references, decoded the way a BROWSER decodes them and
    identically on every interpreter.

    Which tests are red on which host, before the fix. The ones that go through
    `_pre_3_13_host()` are red on BOTH, because the simulation puts the 3.12 decoder back. Of
    the ones that read the host straight, the NON-RESOLUTION cases (`&notit;`, `&not=`, and the
    unquoted and split cases) are red on 3.12 - which is what CI runs - and already green on
    3.13, whose `html.parser` applies the browser rule; the resolution and numeric cases are
    positive confirmation, green on both, because the host resolves those the same way."""

    @contextlib.contextmanager
    def _pre_3_13_host(self):
        """Make the host `html.parser` decode attribute values the way Python 3.12 does - a
        plain `html.unescape`, which resolves a named reference with NO trailing semicolon.
        On 3.13+ that reinstates the drift; on 3.12 it is what the host already does, so one
        test pins the browser rule on every interpreter the skill runs on.

        The simulation VERIFIES ITSELF: `_unescape_attrvalue` is a private CPython name, so if
        a future interpreter renames it the patch would silently become a no-op and every test
        built on it would pass vacuously - retiring the only guard this bug has. (On 3.12 the
        host drifts natively, with or without the patch, so the assertion is trivially true
        there; it is the 3.13+ run that the check really protects.)"""
        with mock.patch.object(_html_parser, "_unescape_attrvalue", _html.unescape,
                               create=True):
            probe = _HostAttrProbe()
            probe.feed('<div id="&notit;">')
            probe.close()
            self.assertEqual(probe.values, ["\u00acit;"],
                             "the pre-3.13 host decoder was not actually simulated, so any "
                             "test using it would pass vacuously")
            yield

    def test_a_named_reference_without_a_semicolon_is_not_resolved_in_an_attribute(self):
        # Inside an attribute value a browser resolves a NAMED reference only when it ends in
        # `;` (or is an exact match followed by neither `=` nor an alphanumeric), so
        # `id="&notit;"` is the literal `&notit;`. Python 3.12 unescapes the whole value with
        # html.unescape() and yields `\u00acit;` - a different id, href, class, meta content
        # or companion-resource path for the very same document.
        for source in ("&notit;", "&notx", "&not="):
            with self.subTest(source=source):
                self.assertEqual(_ids('<div id="%s"></div>' % source), [source])

    def test_a_resolvable_named_reference_is_still_resolved_in_an_attribute(self):
        for source, expected in (("&amp;x", "&x"), ("&not;it", "\u00acit"), ("&not", "\u00ac")):
            with self.subTest(source=source):
                self.assertEqual(_ids('<div id="%s"></div>' % source), [expected])

    def test_a_numeric_reference_is_always_resolved_in_an_attribute(self):
        # Numeric references resolve even without the `;`, which is what a browser does.
        for source, expected in (("&#65;b", "Ab"), ("&#x41;b", "Ab"), ("&#65=", "A=")):
            with self.subTest(source=source):
                self.assertEqual(_ids('<div id="%s"></div>' % source), [expected])

    def test_an_unquoted_attribute_value_decodes_the_same_way(self):
        self.assertEqual(_ids("<div id=&notit;></div>"), ["&notit;"])

    def test_the_hosts_attribute_value_decoding_is_not_trusted(self):
        # The rule is APPLIED, not inherited: with the pre-3.13 host decoder in place the
        # parser must still report the browser's values, for the id view and the anchor view.
        with self._pre_3_13_host():
            ids = _ids('<div id="&notit;"></div>')
            anchors = _anchors('<main id="commentRoot"><a href="p.html?a&not=b">x</a></main>')
        self.assertEqual(ids, ["&notit;"])
        self.assertEqual([a.get("href") for a in anchors], ["p.html?a&not=b"])

    def test_the_code_block_tokenizer_decodes_attribute_values_the_same_way(self):
        # Both tolerant passes share the rule, so `_CodeSpanParser` reads the same class the
        # `<pre>`/`<code>` language checks would read on any interpreter.
        html = '<pre id="&notit;"><code class="language-&notit;">x</code></pre>'
        parsing.code_block_spans.cache_clear()
        try:
            with self._pre_3_13_host():
                spans = parsing.code_block_spans(html)
        finally:
            parsing.code_block_spans.cache_clear()
        self.assertEqual(spans.pres[0]["attrs"]["id"], "&notit;")
        self.assertEqual(spans.pres[0]["codes"][0]["attrs"]["class"], "language-&notit;")

    def test_a_tag_attribute_lookup_decodes_attribute_values_the_same_way(self):
        with self._pre_3_13_host():
            found = parsing._find_tag_attrs('<html lang="&notit;"></html>', "html")
        self.assertEqual([d.get("lang") for d in found], ["&notit;"])

    def test_a_self_closed_tag_decodes_attribute_values_the_same_way(self):
        # The companion-resource and meta-handshake checks read VOID tags, usually written
        # self-closing, which reach the parser through handle_startendtag rather than
        # handle_starttag - a separate path that must decode identically.
        with self._pre_3_13_host():
            metas = parsing._find_tag_attrs(
                '<meta name="x" content="&notit;"/>', "meta")
            ids = _ids('<svg><rect id="&notit;"/></svg>')
        self.assertEqual([d.get("content") for d in metas], ["&notit;"])
        self.assertEqual(ids, ["&notit;"])

    def test_the_checklist_and_notes_views_decode_the_same_way(self):
        # Every attribute view in the checks package shares the rule (the density view too,
        # though no density verdict turns on an entity): trusting the host here let a real
        # duplicate `data-cmh-item` id pass validation on Python 3.12, because two spellings
        # of ONE browser value decoded to two different strings.
        html = ('<div data-cmh-checklist="c1">'
                '<li data-cmh-state="check" data-cmh-item="&notit;">a</li>'
                '<li data-cmh-state="check" data-cmh-item="&amp;notit;">b</li></div>')
        note_parser = notes._NotesParser()
        with self._pre_3_13_host():
            _errors, warnings = checklist.check_checklists(html)
            note_parser.feed('<p data-cmh-note="&notit;">n</p>')
            note_parser.close()
        self.assertTrue(any('duplicate data-cmh-item id "&notit;"' in w for w in warnings),
                        warnings)
        self.assertEqual([n["id"] for n in note_parser.notes], ["&notit;"])

    @staticmethod
    def _host_is_browser_correct():
        """Whether the RUNNING host already applies the browser attribute rule. The behavior is
        what matters, not the version: the browser-correct decoder reached the 3.13 series in a
        patch release, so an early 3.13 still decodes the 3.12 way and a version test would run
        this comparison against a host that legitimately disagrees."""
        probe = _HostAttrProbe()
        probe.feed('<div id="&notit;">')
        probe.close()
        return probe.values == ["&notit;"]

    def test_the_vendored_tokenizer_matches_a_browser_correct_host(self):
        # A drift guard for the vendored copy of CPython's start-tag attribute tokenizer and
        # decoder: on a host that already applies the browser rule, our re-derived attribute
        # dict must equal the host's for every one of these shapes. It is dormant on the 3.12
        # CI runner by construction, so it guards a contributor's 3.13+ run; the
        # host-INDEPENDENT pins below are what lock the rule in CI.
        if not self._host_is_browser_correct():
            self.skipTest("this host does not ship the browser-correct attribute decoder")
        probe = _HostAttrProbe()
        for tag in ('<div id="&notit;" class="a b">', "<div id=&not;x>", "<div a b=1 a=2>",
                    '<div id="&#65;&amp;&notin;" data-x=\'&not=\'>', "<div id=x/>",
                    '<div title="a > b" id="i">', "<div>", "<div id= x >",
                    '<div id="&amp;amp;" hidden>'):
            with self.subTest(tag=tag):
                probe.reset()
                probe.feed(tag)
                probe.close()
                self.assertEqual(probe.ours, probe.host, tag)

    def test_an_attribute_split_that_needs_no_character_reference_is_still_the_browsers(self):
        # These are the counterexamples that make a raw-tag-level `if "&" not in raw` fast path
        # WRONG, so they are pinned host-independently and run on every interpreter: the
        # pre-3.13 host splits with `\s` and `=+`, so it reads `id==x` as `x` (swallowing the
        # second `=`) and `id=a\xa0b` as two attributes. A browser - and this tokenizer - use
        # HTML whitespace and a single `=`.
        self.assertEqual(_ids("<div id==x></div>"), ["=x"])
        self.assertEqual(_ids("<div id=a\u00a0b></div>"), ["a\u00a0b"])
        self.assertEqual(_ids("<div id==commentRoot></div>"), ["=commentRoot"])

    def test_a_stale_raw_start_tag_is_not_read_as_this_tags_attributes(self):
        # `html.parser` clears the raw start tag in parse_starttag() alone, so a caller outside
        # a start-tag handler sees the PREVIOUS element's tag text. The helper accepts it only
        # when its tag name matches the tag being handled, and otherwise falls back to the
        # host's own list for THIS element.
        parser = _StaleRawTagParser('<div id="stale">')
        self.assertEqual(parser.attrs_for("span", [("id", "live")]), {"id": "live"})
        self.assertEqual(parser.attrs_for("div", [("id", "ignored")]), {"id": "stale"})

    def test_a_name_the_host_truncated_at_a_nul_is_still_this_tag(self):
        # The pre-3.13 host stops a tag name at a NUL where a browser does not, so its `tag`
        # is a prefix of the raw tag's name. Treating that as a foreign tag would fall back to
        # the host's list - handing back exactly the drifting values this helper exists to
        # replace - so it is accepted as this tag.
        parser = _StaleRawTagParser('<p\x00x id="&notit;">')
        self.assertEqual(parser.attrs_for("p", [("id", "\u00acit;")]), {"id": "&notit;"})

    def test_an_oversized_numeric_reference_does_not_break_the_decode(self):
        # `html.unescape` raises on a reference with more digits than Python's integer
        # conversion limit. Every parse entry point swallows an exception into a TRUNCATED
        # parse, so a raise here would hide every finding after that tag - and the pre-3.13
        # host can hand us such a value in a place its own decoder never looked at (it splits
        # `id=a\xa0&#...;=1` differently). The reference is left literal instead.
        ref = "&#%s;" % ("9" * 5000)
        self.assertEqual(parsing._unescape_attr_value("a" + ref), "a" + ref)


class _HostAttrProbe(HTMLParser):
    """A bare host parser that records, per start tag, the host's own first-wins attribute
    dict and the one the vendored decoder derives from the same raw tag."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.host = []
        self.ours = []
        self.values = []

    def reset(self):
        super().reset()
        self.host = []
        self.ours = []
        self.values = []

    def handle_starttag(self, tag, attrs):
        d = {}
        for k, v in attrs:
            kl = (k or "").lower()
            if kl not in d:
                d[kl] = v if v is not None else ""
        self.host.append(d)
        self.ours.append(parsing._browser_attrs_dict(self, tag.lower(), attrs))
        self.values.extend(v for _k, v in attrs if v is not None)

    handle_startendtag = handle_starttag


class _StaleRawTagParser:
    """A stand-in for a parser whose `get_starttag_text()` is STALE - the raw text of a tag
    other than the one being handled, which is what a caller outside a start-tag handler sees."""

    def __init__(self, raw):
        self._raw = raw

    def get_starttag_text(self):
        return self._raw

    def attrs_for(self, tag, attrs):
        return parsing._browser_attrs_dict(self, tag, attrs)


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
