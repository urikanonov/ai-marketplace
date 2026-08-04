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
import re  # noqa: E402
from html.parser import HTMLParser  # noqa: E402
from unittest import mock  # noqa: E402

from checks import checklist, density, kind, notes, parsing, theme_contrast  # noqa: E402
from cmhval import contrast  # noqa: E402
import _browser_attrs  # noqa: E402
import _favicon  # noqa: E402
import deck_validate  # noqa: E402
import doc_stats  # noqa: E402
import generate_toc  # noqa: E402
import new_document  # noqa: E402
import retrofit  # noqa: E402
import section_hash  # noqa: E402
import upgrade  # noqa: E402

# Every parser OUTSIDE the checks package that reads a whole document's text. They share the same
# bounded decode through the `_browser_attrs` shim, so a document the validator reads is one the
# tools beside it can also stamp, hash, count, index, retrofit and upgrade (CMH-VAL-21).
_TOOL_PARSERS = (contrast._StyleScanner, doc_stats._StatsParser, generate_toc._TocParser,
                 section_hash._SectionParser, new_document._TitleDetector,
                 retrofit._StructureParser, upgrade._KindMetaFinder, upgrade._RootSourceFinder,
                 _favicon._FaviconFinder, deck_validate._ActiveContentScanner,
                 deck_validate._AuthoredContentScanner)

# Every HTML raw-text / RCDATA element: its CONTENT is text a reader SEES, never markup.
RAW_TEXT_ELEMENTS = ("script", "style", "textarea", "title", "xmp", "iframe",
                     "noembed", "noframes", "noscript")

# U+212A KELVIN SIGN: the ONLY character outside ASCII whose `str.lower()` is an ASCII letter
# ("k"), so it is the whole reachable surface of a Unicode fold turning a tag or attribute name
# into a name a browser never sees.
KELVIN = "\u212a"

def _ids(html):
    return parsing._parse_document(html).all_ids


def _anchors(html):
    return parsing._parse_document(html).anchors


class DocParserTemplateRawTextTests(unittest.TestCase):
    """A `<template>`-parked `<script>`/`<style>` body is recorded in the template-only views the
    OFFLINE checks read, and reaches no view that treats it as authored content."""

    CR = '<main id="commentRoot">'

    def _doc(self, inner):
        return parsing._parse_document(self.CR + inner + "<p>real prose</p></main>")

    def test_a_template_parked_raw_text_body_is_not_commentroot_prose(self):
        # `_cur_script`/`_cur_style` are deliberately not set inside a template (their bodies are
        # not live script or live CSS), so the SOURCE TEXT of a parked block reaches `handle_data`
        # with neither set. It must not fall through into `commentroot_prose`, which every prose
        # reader treats as words the author wrote and a reader can see.
        doc = self._doc('<template id="parked"><script>var LEAK = "not prose";</script>'
                        "<style>.leak { color: #123456; }</style></template>")
        prose = [t.strip() for t in doc.commentroot_prose if t.strip()]
        self.assertEqual(prose, ["real prose"])

    def test_a_template_parked_raw_text_body_lands_in_the_template_views_only(self):
        doc = self._doc('<template id="parked"><script>var LEAK = 1;</script>'
                        "<style>.leak { color: #123456; }</style></template>")
        self.assertEqual([s["body"] for s in doc.template_scripts], ["var LEAK = 1;"])
        self.assertEqual([s["body"] for s in doc.template_styles], [".leak { color: #123456; }"])
        self.assertEqual(doc.scripts, [])
        self.assertEqual(doc.styles, [])


class DocParserTemplateBoundaryTests(unittest.TestCase):
    """An END TAG written inside an open `<template>` cannot close an element opened OUTSIDE it.

    `template` is a scoping element and its contents are parsed into their own DocumentFragment,
    so a browser IGNORES such a closer and the markup that follows stays inert inside the
    template. Matching an ancestor across the boundary popped the template early, which made
    every template-aware view - prose, ids, headings, anchors, the layer/marker views - read
    inert markup as live.
    """

    CR = '<main id="commentRoot">'

    def _doc(self, inner):
        return parsing._parse_document(self.CR + inner)

    def _prose(self, doc):
        return [t.strip() for t in doc.commentroot_prose if t.strip()]

    def test_an_explicit_paragraph_closer_does_not_close_an_ancestor(self):
        doc = self._doc('<p><template>inside</p>'
                        '<p id="after">See the section below</p></template></main>')
        self.assertEqual(self._prose(doc), [])
        self.assertEqual(doc.all_ids, ["commentRoot"])

    def test_an_explicit_list_item_closer_does_not_close_an_ancestor(self):
        doc = self._doc('<ul><li><template>inside</li>'
                        '<li id="after">See the section below</li></template></ul></main>')
        self.assertEqual(self._prose(doc), [])
        self.assertEqual(doc.all_ids, ["commentRoot"])

    def test_an_ancestor_closer_does_not_end_the_comment_root(self):
        doc = self._doc('<template>inside</main><p id="after">inert</p></template>'
                        '<p id="outside">live prose</p></main>')
        self.assertEqual(self._prose(doc), ["live prose"])
        self.assertEqual(doc.all_ids, ["commentRoot", "outside"])

    def test_a_heading_behind_an_ignored_closer_is_still_inert(self):
        doc = self._doc('<p><template>inside</p>'
                        '<h2 id="h">Heading</h2></template></main>')
        self.assertEqual([h["text"] for h in doc.headings], [])
        self.assertEqual(doc.all_ids, ["commentRoot"])

    def test_a_block_start_tag_does_not_implicitly_close_an_ancestor_paragraph(self):
        # The implicit `</p>` path already stops at the boundary (`template` is in
        # `_P_CLOSE_BOUNDARY`); pinned so it cannot regress with the explicit one.
        doc = self._doc('<p><template>inside<p id="after">inert</p></template>'
                        "live prose</p></main>")
        self.assertEqual(self._prose(doc), ["live prose"])
        self.assertEqual(doc.all_ids, ["commentRoot"])

    def test_a_list_item_start_tag_does_not_implicitly_close_an_ancestor_item(self):
        doc = self._doc('<ul><li><template>inside<li id="after">inert</template>'
                        "live prose</li></ul></main>")
        self.assertEqual(self._prose(doc), ["live prose"])
        self.assertEqual(doc.all_ids, ["commentRoot"])

    def test_the_templates_own_end_tag_still_closes_it(self):
        doc = self._doc('<p><template><span id="inert"></span></template>'
                        '<span id="live"></span>live prose</p></main>')
        self.assertEqual(self._prose(doc), ["live prose"])
        self.assertEqual(doc.all_ids, ["commentRoot", "live"])

    def test_the_namespace_view_is_not_popped_across_the_boundary(self):
        # The foreign-content bookkeeping runs PARALLEL to the element stack, so an ignored
        # closer must leave it alone too. Observed through CDATA: `<![CDATA[` opens a real
        # section only while the CURRENT NODE is foreign, so with the `<foreignObject>` still
        # open the payload is TEXT. Popping it made the same payload a bogus comment ending at
        # its first `>`, which exposed the element written after it as live markup.
        doc = self._doc('<svg><foreignObject><template>inside</foreignObject></svg></template>'
                        '<![CDATA[><span id="cdata"></span>]]>'
                        "</foreignObject></svg></main>")
        self.assertEqual(doc.all_ids, ["commentRoot"])

    def test_the_tag_index_is_not_popped_across_the_boundary_either(self):
        # The same shape asked of the resource views' tag index, which the offline / egress
        # checks read: the element the bogus comment would have exposed is inside a real CDATA
        # section, so it is TEXT and no resource is indexed.
        html = ('<svg><foreignObject><template>x</foreignObject></svg></template>'
                '<![CDATA[><img src="//evil.example/x.png">]]>'
                "</foreignObject></svg>")
        self.assertEqual(parsing._find_tag_attrs(html, "img"), [])

    def test_a_head_closer_inside_a_template_does_not_end_the_head(self):
        # A closer a browser IGNORES must not reach the parser's STATE MACHINES either. This one
        # ended the head, so the favicon `<link>` a browser keeps IN the head was dropped.
        doc = parsing._parse_document(
            '<head><template></head></template><link rel="icon" href="a.ico"></head>'
            '<body><main id="commentRoot"><p>x</p></main></body>')
        self.assertEqual([lk["href"] for lk in doc.icon_links], ["a.ico"])

    def test_a_foreign_template_is_not_a_scope_boundary(self):
        # Only an HTML-namespace `<template>` scopes an end tag. An SVG element that merely
        # happens to be called `template` is an ordinary foreign element, so the `</svg>` inside
        # it still closes the svg and the paragraph after it is live, as in a browser.
        doc = self._doc('<svg><template>x</svg><p id="after">after</p></main>')
        self.assertEqual(doc.all_ids, ["commentRoot", "after"])
        self.assertEqual(self._prose(doc), ["after"])

    def test_a_heading_closer_inside_a_template_does_not_end_the_heading(self):
        # Same hole, seen from the heading capture: the ignored `</h2>` flushed the heading the
        # author opened OUTSIDE the template, so its text stopped at the template and the rest
        # of it was collected as ordinary prose instead.
        doc = self._doc('<h2 id="h">Before <template></h2></template>After</h2></main>')
        self.assertEqual([h["text"] for h in doc.headings], ["Before After"])
        self.assertEqual(self._prose(doc), [])

    def test_a_matched_head_inside_a_template_does_not_end_the_outer_head(self):
        # The closer MATCHES here - an inner `<head>` really is open inside the template - so the
        # floor alone does not catch it. What the state machines must key on is the element being
        # closed, not the tag NAME: the head this ends is the template's own, and the favicon
        # `<link>` after it is still in the document's head.
        doc = parsing._parse_document(
            '<head><template><head></head></template>'
            '<link rel="icon" href="a.ico"></head>'
            '<body><main id="commentRoot"><p>x</p></main></body>')
        self.assertEqual([lk["href"] for lk in doc.icon_links], ["a.ico"])

    def test_a_matched_heading_inside_a_template_does_not_end_the_outer_heading(self):
        # The mirror image for the heading capture: the `</h2>` closes the template's OWN `<h2>`,
        # so the heading the author opened outside the template goes on collecting its text.
        doc = self._doc('<h2 id="h">Before <template><h2>Hidden</h2></template>'
                        "After</h2></main>")
        self.assertEqual([h["text"] for h in doc.headings], ["Before After"])
        self.assertEqual(self._prose(doc), [])


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

    def test_an_unclosed_raw_text_body_reaches_eof_on_every_host(self):
        # An unclosed raw-text element runs to EOF in a browser, so its BODY is live text -
        # a `<style>` with no closing tag really does hide host elements. html.parser only
        # hands that tail to handle_data from CPython 3.12.11 / 3.13.5 (gh-135462); before
        # that it leaves it unparsed in its own buffer, so the same document came back with an
        # EMPTY style body on an older patch release and a full one on a newer one. CI proved
        # the split: its two runner images resolved different 3.12 patches.
        for elem, sink in (("style", "styles"), ("script", "scripts")):
            with self.subTest(elem=elem):
                html = "<html><head><%s>\n[hidden] { display: none !important; }" % elem
                doc = parsing._parse_document(html)
                bodies = getattr(doc, sink)
                self.assertTrue(bodies, "an unclosed <%s> must still be captured" % elem)
                self.assertIn("[hidden]", bodies[0]["body"],
                              "the unclosed <%s> body must run to EOF" % elem)

    def test_an_unclosed_raw_text_body_is_read_the_same_way_when_fed_incrementally(self):
        # close() is the end of the document on the incremental path too, so the tail flush
        # must not depend on parse_document() having been the entry point - and a body split
        # across feed() chunks (each of which leaves the parser mid-raw-text) must land whole.
        html = "<html><head><style>\n[hidden] { display: none !important; }"
        p = parsing._DocParser(html)
        for k in range(0, len(html), 7):
            p.feed(html[k:k + 7])
        p.close()
        self.assertTrue(p.styles)
        self.assertIn("[hidden]", p.styles[0]["body"])

    def test_the_tail_of_an_unclosed_raw_text_body_is_flushed_exactly_once(self):
        # The flush runs after the host's own close(), so on a FIXED host (3.12.11+/3.13.5+)
        # the tail has already been handed to handle_data - flushing it again would duplicate
        # the body and, worse, double-count the tokens the CSS checks read. close() is also
        # idempotent: a second call must not re-flush a buffer it already drained.
        css = "\n[hidden] { display: none !important; }"
        html = "<html><head><style>" + css
        p = parsing._DocParser(html)
        p.parse_document(html)
        p.close()
        self.assertEqual([s["body"] for s in p.styles], [css])

    def test_the_tail_is_flushed_even_when_the_host_leaves_it_buffered(self):
        """The flush is pinned on EVERY interpreter, not only a pre-3.12.11 one.

        The two tests above go red on a host that buffers the tail (pre-3.12.11 / pre-3.13.5),
        which in CI is only whichever runner image happens to resolve such a patch - so on a
        fixed host they would pass with the flush deleted and stop guarding it. Simulate the
        buffering host directly instead: after feed(), EVERY host still holds the tail in
        `rawdata` with cdata mode open (it cannot know more input is not coming), so neutering
        the HOST's close() reproduces the old behavior exactly. Our close() must still flush.
        """
        html = "<html><head><style>\n[hidden] { display: none !important; }"
        p = parsing._DocParser(html)
        p.feed(html)
        self.assertEqual(p.cdata_elem, "style")
        self.assertIn("[hidden]", p.rawdata, "the host is expected to buffer the tail here")
        with mock.patch.object(HTMLParser, "close", lambda _self: None):
            p.close()
        self.assertTrue(p.styles, "the buffered tail was dropped")
        self.assertEqual(p.styles[0]["body"].count("[hidden]"), 1, p.styles[0]["body"])

    def test_a_buffered_truncated_end_tag_is_not_flushed_as_body(self):
        # Same simulated buffering host, but the buffer holds a closer that never finished.
        # EOF discards the tag, so the flush must stop at it rather than hand its characters
        # to the element body.
        html = "<script>ok</script " + parsing.READY_TOKEN
        p = parsing._DocParser(html)
        p.feed(html)
        self.assertTrue(p.rawdata.startswith("</script"), p.rawdata)
        with mock.patch.object(HTMLParser, "close", lambda _self: None):
            p.close()
        self.assertEqual([s["body"] for s in p.scripts], ["ok"])
        self.assertFalse(p.layer_ready_token)

    def test_a_truncated_end_tag_at_eof_is_not_part_of_the_body(self):
        """EOF inside an end TAG discards the tag; its text is not raw-text content.

        Once `</script` is followed by whitespace or `/` a browser is tokenizing an end tag, so
        an EOF there drops it. Flushing the buffered characters verbatim would let a document
        inject its own trailing text into the script body - enough to forge the layer's ready
        token - on exactly the hosts the flush exists for.
        """
        for tail in ("</script data-x", "</script\n", "</script/"):
            with self.subTest(tail=tail):
                doc = parsing._parse_document("<script>ok" + tail)
                self.assertEqual([s["body"] for s in doc.scripts], ["ok"])

    def test_a_truncated_end_tag_at_eof_cannot_forge_the_ready_token(self):
        html = "<script>ok</script " + parsing.READY_TOKEN
        self.assertFalse(parsing._parse_document(html).layer_ready_token,
                         "a discarded end tag's text must not count as layer script body")

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


class DocParserMarkerProvenanceTests(unittest.TestCase):
    """A region marker is a comment the AUTHORING TOOLS wrote, not merely a comment NODE.

    A browser really does create a comment node for `<!BEGIN: ...>`, `<?BEGIN: ...>` and
    `</ BEGIN: ...>` - each is a BOGUS COMMENT - so routing them to `handle_comment()` is
    correct. What is not correct is letting one BE a marker: the skill only ever emits a real
    `<!-- ... -->` comment, so a bogus one carries no provenance and must not open or close the
    CONTENT region or set the JS end marker.
    """

    ROOT_OPEN = '<main id="commentRoot" data-comment-key="k" data-doc-label="l">'
    BEGIN_TEXT = parsing.CONTENT_BEGIN[4:-3].strip()

    # Every shape a browser turns into a bogus comment, spelled with the marker text. The `<?`
    # one keeps its leading `?` in the comment DATA (the bogus-comment state starts at the `?`),
    # so it could never match a marker even before provenance existed - it is asserted for
    # symmetry, and `test_a_bogus_comment_carries_no_source` is what pins its provenance.
    def _bogus(self, text):
        return ("<!%s>" % text, "<?%s>" % text, "</ %s>" % text)

    def test_a_bogus_comment_carries_no_source(self):
        # Provenance is recorded ONLY on the `<!--` path, so every other route to
        # handle_comment() - including the base parser's own end-of-input fallbacks - is bogus
        # by DEFAULT and a route added later can only ever fail CLOSED.
        class _Recorder(parsing._DocParser):
            def __init__(self, html):
                super().__init__(html)
                self.seen = []

            def handle_comment(self, data):
                self.seen.append((data, self.comment_raw, self.comment_is_bogus))
                super().handle_comment(data)

        bogus_here = ("<!x>", "<?x>", "<![CDATA[x]]>",
                      "<!x", "<?x", "</ x")     # the last three are unterminated at EOF
        for html in bogus_here:
            with self.subTest(html=html):
                p = _Recorder(html)
                p.parse_document(html)
                self.assertTrue(p.seen, "%r must still produce a comment node" % html)
                for _data, raw, is_bogus in p.seen:
                    self.assertIsNone(raw, "%r must carry no comment source" % html)
                    self.assertTrue(is_bogus)

        # A TERMINATED `</` + junk is resolved by the HOST, which differs: before 3.13
        # `endtagfind` allows whitespace after `</`, so `</ x>` is an END TAG there and no
        # comment node exists at all (tracked separately). Either reading is safe here - what
        # must hold is that a comment one of them DOES produce still carries no source.
        for html in ("</ x>", "<//>"):
            with self.subTest(html=html):
                p = _Recorder(html)
                p.parse_document(html)
                for _data, raw, is_bogus in p.seen:
                    self.assertIsNone(raw, "%r must carry no comment source" % html)
                    self.assertTrue(is_bogus)

        for html in ("<!-- x -->", "<!-- x --!>", "<!-->", "<!--->", "<!-- x"):
            with self.subTest(html=html):
                p = _Recorder(html)
                p.parse_document(html)
                self.assertTrue(p.seen, "%r must produce a comment node" % html)
                for _data, raw, is_bogus in p.seen:
                    self.assertEqual(raw, html, "%r is a REAL comment" % html)
                    self.assertFalse(is_bogus)

    def test_a_bogus_comment_cannot_open_the_content_region(self):
        for forged in self._bogus(self.BEGIN_TEXT):
            with self.subTest(forged=forged):
                html = self.ROOT_OPEN + forged + "<p>x</p>" + parsing.CONTENT_END + "</main>"
                p = parsing._parse_document(html)
                self.assertFalse(p.content_region_opened,
                                 "%s must not open the CONTENT region" % forged)

    def test_a_bogus_comment_cannot_close_the_content_region(self):
        end_text = parsing.CONTENT_END[4:-3].strip()
        for forged in self._bogus(end_text):
            with self.subTest(forged=forged):
                html = (self.ROOT_OPEN + parsing.CONTENT_BEGIN + forged
                        + "<p>x</p>" + parsing.CONTENT_END + "</main>")
                p = parsing._parse_document(html)
                self.assertTrue(p.content_region_closed)
                # The real END is what closed it, so the region was still open at the forged one.
                self.assertTrue(p.content_region_opened)

        # And a forged END alone leaves the region unclosed.
        for forged in self._bogus(end_text):
            with self.subTest(forged=forged, alone=True):
                html = self.ROOT_OPEN + parsing.CONTENT_BEGIN + "<p>x</p>" + forged + "</main>"
                p = parsing._parse_document(html)
                self.assertFalse(p.content_region_closed,
                                 "%s must not close the CONTENT region" % forged)

    def test_a_bogus_comment_cannot_set_the_js_end_marker(self):
        for forged in self._bogus(parsing.JS_END_MARKER_TEXT):
            with self.subTest(forged=forged):
                html = "<div>x</div>" + forged + "<div>y</div>"
                self.assertIsNone(parsing._parse_document(html).js_end_marker_pos,
                                  "%s must not be the JS end marker" % forged)

    def test_an_unterminated_bogus_construct_cannot_set_the_js_end_marker(self):
        # It runs to the end of the document as comment DATA (the browser rule), but it is
        # still bogus, so it is still not a marker. `</ ` is here too: a bare `</` + junk at
        # EOF is its own end-of-input path, and only the `<!`/`<?` ones would otherwise be
        # exercised.
        for opener in ("<!", "<?", "</ "):
            with self.subTest(opener=opener):
                html = "<div>x</div>" + opener + parsing.JS_END_MARKER_TEXT
                self.assertIsNone(parsing._parse_document(html).js_end_marker_pos)

    def test_a_real_marker_comment_still_opens_and_closes_the_region(self):
        html = (self.ROOT_OPEN + parsing.CONTENT_BEGIN + "<p>x</p>"
                + parsing.CONTENT_END + "</main>")
        p = parsing._parse_document(html)
        self.assertTrue(p.content_region_opened)
        self.assertTrue(p.content_region_closed)

    def test_a_real_marker_comment_still_sets_the_js_end_marker(self):
        html = "<div>x</div><!-- %s --><div>y</div>" % parsing.JS_END_MARKER_TEXT
        pos = parsing._parse_document(html).js_end_marker_pos
        self.assertIsNotNone(pos)
        self.assertEqual(pos, html.index("<!--"))

    def test_the_multi_line_js_end_marker_comment_still_counts(self):
        # The layer's region markers are also written on their own lines inside one comment,
        # which `_region_marker_matches` accepts - so the parse view must accept it too.
        html = "<div>x</div><!--\n%s\n--><div>y</div>" % parsing.JS_END_MARKER_TEXT
        self.assertIsNotNone(parsing._parse_document(html).js_end_marker_pos)

    def test_a_comment_the_marker_count_does_not_see_cannot_open_the_region(self):
        # Provenance is not only "a real comment": the CONTENT markers are COUNTED in the text
        # as the exact literal the authoring tools emit (CMH-VAL-20), so a real comment the
        # count view does not see must not open the region either - otherwise the two views
        # disagree and a forged one stands in for the real marker exactly as a bogus comment did.
        text = parsing.CONTENT_BEGIN[4:-3].strip()
        for forged in ("<!--%s-->" % text,                     # no padding
                       "<!--   %s   -->" % text,               # extra padding
                       "<!--\n%s\n-->" % text,                 # its own lines
                       "<!-- %s --!>" % text):                 # the legacy close
            with self.subTest(forged=forged):
                self.assertNotEqual(forged, parsing.CONTENT_BEGIN, "fixture premise")
                html = (self.ROOT_OPEN + forged + "<p>x</p>"
                        + parsing.CONTENT_END + "</main>")
                p = parsing._parse_document(html)
                self.assertFalse(p.content_region_opened,
                                 "%s is not the marker the count view sees" % forged)

    def test_a_comment_the_marker_count_does_not_see_cannot_close_the_region(self):
        text = parsing.CONTENT_END[4:-3].strip()
        for forged in ("<!--%s-->" % text,
                       "<!--   %s   -->" % text,
                       "<!--\n%s\n-->" % text,
                       "<!-- %s --!>" % text):
            with self.subTest(forged=forged):
                self.assertNotEqual(forged, parsing.CONTENT_END, "fixture premise")
                html = self.ROOT_OPEN + parsing.CONTENT_BEGIN + "<p>x</p>" + forged + "</main>"
                p = parsing._parse_document(html)
                self.assertTrue(p.content_region_opened)
                self.assertFalse(p.content_region_closed,
                                 "%s is not the marker the count view sees" % forged)

    def test_a_padding_the_marker_count_does_not_accept_is_not_the_js_end_marker(self):
        # `_region_marker_matches` pads with `[ \t]` only, but `str.strip()` also strips NBSP,
        # a vertical tab and the other characters Python calls whitespace - so a comment padded
        # with one is NOT a counted marker and must not be the E5 boundary either.
        for pad in ("\u00a0", "\x0b", "\x0c", "\u2028", "\u1680"):
            with self.subTest(pad=repr(pad)):
                html = "<div>x</div><!--%s%s%s--><div>y</div>" % (
                    pad, parsing.JS_END_MARKER_TEXT, pad)
                self.assertIsNone(parsing._parse_document(html).js_end_marker_pos,
                                  "%r padding is not counted as a marker" % pad)

    def test_the_counted_js_end_marker_shapes_still_set_the_boundary(self):
        for shape in ("<!-- %s -->", "<!--%s-->", "<!--\n%s\n-->", "<!--\t%s\t-->",
                      "<!-- ==== %s ==== -->"):
            with self.subTest(shape=shape):
                html = "<div>x</div>" + (shape % parsing.JS_END_MARKER_TEXT) + "<div>y</div>"
                self.assertIsNotNone(parsing._parse_document(html).js_end_marker_pos,
                                     "%r is a counted marker shape" % shape)

    def test_a_legacy_closed_comment_cannot_set_the_js_end_marker(self):
        # `--!>` closes a comment in a browser, but `_region_marker_matches` (which counts the
        # layer's region markers) accepts only a `-->` close, so a `--!>` one is not a marker
        # there and must not be the E5 boundary here.
        html = "<div>x</div><!-- %s --!><div>y</div>" % parsing.JS_END_MARKER_TEXT
        self.assertIsNone(parsing._parse_document(html).js_end_marker_pos)


class DocParserEofTests(unittest.TestCase):
    """What a TRUNCATED document resolves to, decided here rather than by the host.

    CPython's EOF handling changed in 3.12.11 / 3.13.5 (gh-135462): before it, an unfinished
    construct's SOURCE is handed back as DATA at end of input; after it, tags are dropped and
    comments/declarations are closed. That is the whole gh-135462 family, not just the raw-text
    body the CI failure exposed, and CI now runs BOTH sides of the split (its two runner images
    resolve different 3.12 patches), so each construct is resolved explicitly.

    The parse hooks are exercised DIRECTLY, because the outcome is what a fixed host already
    does: a black-box assertion would pass on a fixed host with these overrides deleted and
    would therefore stop guarding them everywhere but the older runner.
    """

    CR = '<main id="commentRoot">'

    class _Recorder(parsing._DocParser):
        def __init__(self, html):
            super().__init__(html)
            self.comments_seen = []

        def handle_comment(self, data):
            self.comments_seen.append(data)
            super().handle_comment(data)

    def _at_eof(self, rawdata):
        p = self._Recorder(rawdata)
        p.rawdata = rawdata
        p._final = True
        return p

    def test_a_truncated_start_tag_at_eof_is_dropped(self):
        for tail in ('<div class="x', "<div", "<div data-a=1"):
            with self.subTest(tail=tail):
                p = self._at_eof(tail)
                self.assertEqual(p.parse_starttag(0), len(tail),
                                 "EOF inside a start tag must discard it, not emit its source")

    def test_a_truncated_end_tag_at_eof_is_dropped(self):
        for tail in ("</div", '</div class="x'):
            with self.subTest(tail=tail):
                p = self._at_eof(tail)
                self.assertEqual(p.parse_endtag(0), len(tail))

    def test_a_truncated_tag_still_waits_for_more_input_before_the_end(self):
        # The drop is an END-OF-INPUT rule; mid-stream the parser must still ask for more data,
        # or an incremental caller loses a tag that was merely split across two feed() chunks.
        p = self._Recorder("<div")
        p.rawdata = "<div"
        self.assertEqual(p.parse_starttag(0), -1)
        p.rawdata = "</div"
        self.assertEqual(p.parse_endtag(0), -1)

    def test_a_processing_instruction_is_a_bogus_comment(self):
        # A browser has no PI: `<?` opens a bogus comment that ends at the FIRST `>`, so the
        # markup after that `>` is live.
        p = self._at_eof('<?php echo "x">rest')
        self.assertEqual(p.parse_pi(0), len('<?php echo "x">'))
        self.assertEqual(p.comments_seen, ['?php echo "x"'])

    def test_an_unterminated_processing_instruction_runs_to_the_end(self):
        p = self._at_eof('<?php echo "x"')
        self.assertEqual(p.parse_pi(0), len(p.rawdata))
        self.assertEqual(p.comments_seen, ['?php echo "x"'])

    def test_an_unterminated_bogus_declaration_runs_to_the_end(self):
        p = self._at_eof("<!BEGIN: commentable-html - CONTENT")
        self.assertEqual(p.parse_html_declaration(0), len(p.rawdata))
        self.assertEqual(p.comments_seen, ["BEGIN: commentable-html - CONTENT"])

    def test_a_truncated_construct_contributes_no_prose(self):
        # The browser-visible outcome of all of the above, through the public parse.
        for tail in ('<div class="x', "</div id=", '<?php echo "x"',
                     "<!BEGIN: commentable-html - CONTENT", "<!-- note"):
            with self.subTest(tail=tail):
                doc = parsing._parse_document(self.CR + "hi" + tail)
                self.assertEqual([t.strip() for t in doc.commentroot_prose], ["hi"])

    def test_a_bare_end_tag_open_at_eof_is_text(self):
        # `</` with nothing after it is TEXT in a browser, not a dropped tag.
        doc = parsing._parse_document(self.CR + "hi</")
        self.assertEqual([t.strip() for t in doc.commentroot_prose], ["hi", "</"])

    def test_an_invalid_end_tag_open_at_eof_is_a_bogus_comment(self):
        # `</` followed by anything that is not a tag NAME opens a bogus comment, so its text is
        # comment data - neither prose nor a dropped tag. Dropping it silently (or leaking it as
        # prose, which an older host does) both misread the document.
        for tail in ("</ junk", "<//", "</ BEGIN: commentable-html - CONTENT"):
            with self.subTest(tail=tail):
                p = self._Recorder(self.CR + "hi" + tail)
                p.parse_document(self.CR + "hi" + tail)
                self.assertEqual([t.strip() for t in p.commentroot_prose], ["hi"])
                self.assertEqual(p.comments_seen, [tail[2:]])

    def test_a_bare_quote_does_not_end_an_end_tag_early_or_late(self):
        """A quoted value exists only AFTER `=`, so a bare quote is an (invalid) name character.

        Treating any quote as opening a value made `</script " >` look unfinished, which ran the
        raw-text region to the end of the document and hid the author's real code block from the
        highlighting and KQL checks - the exact fail-open those checks exist to prevent.
        """
        html = ('<script>ok</script " >'
                '<pre><code class="language-python">real</code></pre>')
        doc = parsing._parse_document(html)
        self.assertEqual([s["body"] for s in doc.scripts], ["ok"])
        self.assertEqual(len(parsing.code_block_spans(html).pres), 1)

    def test_a_gt_inside_a_quoted_attribute_value_still_does_not_end_the_tag(self):
        # The other half of the same rule: after `=`, a quoted value really does hide a `>`.
        html = '<script>ok</script data-x="a > b"><div id="live"></div>'
        self.assertEqual(parsing._parse_document(html).all_ids, ["live"])
        self.assertEqual(parsing._end_tag_close('</p a="x>y">z', 0), len('</p a="x>y">'))
        self.assertEqual(parsing._end_tag_close('</p a="x', 0), -1)


class DocParserHeadingEofTests(unittest.TestCase):
    """When a heading ENDS: its own end tag, an ancestor closing, or end of input.

    A browser renders `<h2 id="sec">Title` at the end of a truncated document as that heading,
    so `close()` must finalize it the way an end tag does. Dropping it blinded every
    heading-derived check (the id and TOC/anchor scans, and the heading path a comment anchors
    to) to the LAST heading of such a document - the adjacent half of the raw-text flush above.
    An ancestor's end tag ends the heading for the same reason: a browser closes it there, so
    the text after it belongs to no heading.
    """

    CR = '<main id="commentRoot">'

    def test_a_heading_left_open_at_eof_is_still_collected(self):
        closed = parsing._parse_document(self.CR + '<h2 id="sec">Title text</h2>').headings
        self.assertEqual(closed, [{"tag": "h2", "id": "sec", "text": "Title text",
                                   "top_level": True, "in_lede": False}])
        truncated = parsing._parse_document(self.CR + '<h2 id="sec">Title text').headings
        self.assertEqual(truncated, closed,
                         "a document truncated inside a heading must keep that heading")

    def test_an_open_heading_at_eof_keeps_its_id_and_flags(self):
        # The whole record, not just the text: a nested (non-top-level) heading inside the
        # document's cmh-lede header, whose text is whitespace-collapsed the same way.
        html = self.CR + '<header class="cmh-lede"><h1 id="title">The  title\n  text'
        self.assertEqual(parsing._parse_document(html).headings,
                         [{"tag": "h1", "id": "title", "text": "The title text",
                           "top_level": False, "in_lede": True}])

    def test_an_empty_heading_at_eof_contributes_nothing(self):
        # The closed path drops a text-less heading, so the EOF path must drop it too.
        for tail in ('<h2 id="sec">', '<h2 id="sec">   \n '):
            with self.subTest(tail=tail):
                self.assertEqual(parsing._parse_document(self.CR + tail).headings, [])

    def test_an_open_heading_is_collected_on_the_incremental_path_too(self):
        # close() is the end of the document however the caller fed it, and heading text split
        # across feed() chunks must still land whole.
        html = self.CR + '<h2 id="sec">Title text'
        p = parsing._DocParser(html)
        for k in range(0, len(html), 5):
            p.feed(html[k:k + 5])
        p.close()
        self.assertEqual([h["text"] for h in p.headings], ["Title text"])

    def test_an_open_heading_is_flushed_exactly_once(self):
        # close() is idempotent everywhere else; a second call must not duplicate the heading.
        html = self.CR + '<h2 id="sec">Title text'
        p = parsing._DocParser(html)
        p.parse_document(html)
        p.close()
        self.assertEqual(len(p.headings), 1)

    def test_heading_text_the_host_only_emits_at_eof_is_kept(self):
        # A host can hold trailing text back while a character reference may still be unfinished
        # and hand it over during ITS close(), so the heading has to be finalized AFTER
        # super().close() or the last run of text is silently missing. Simulated directly, so the
        # ordering is pinned on every interpreter rather than on one host's buffering.
        html = self.CR + '<h2 id="sec">Title'
        p = parsing._DocParser(html)
        p.feed(html)
        with mock.patch.object(HTMLParser, "close", lambda _self: _self.handle_data("&")):
            p.close()
        self.assertEqual([h["text"] for h in p.headings], ["Title&"])

    def test_a_heading_quoted_in_a_raw_text_body_at_eof_is_still_not_collected(self):
        # The flush must not resurrect a heading a reader only SEES: an unclosed raw-text
        # element runs to EOF, so the markup inside it is text, not an open heading.
        html = self.CR + '<h2 id="real">Live</h2><script>var s = "<h2 id=\'quoted\'>Quoted";'
        self.assertEqual([h["id"] for h in parsing._parse_document(html).headings], ["real"])

    def test_an_ancestors_end_tag_ends_the_heading(self):
        # A browser closes an open heading when its ancestor closes, so the prose after that
        # ancestor is NOT heading text - and the next heading is a heading of its own. Left
        # capturing, one stale heading swallowed the rest of the document as its own text.
        html = (self.CR + "<section><h2 id=\"sec\">Title</section>"
                "<p>Prose after the section</p><h3 id=\"next\">Next</h3>")
        headings = parsing._parse_document(html).headings
        self.assertEqual([(h["id"], h["text"]) for h in headings],
                         [("sec", "Title"), ("next", "Next")])

    def test_a_heading_the_comment_root_closed_over_stops_there(self):
        # The same rule at the root boundary, in a TRUNCATED document: what close() flushes must
        # be the heading's OWN text, not everything a browser puts outside #commentRoot.
        html = self.CR + '<h2 id="sec">Title</main><p>Prose outside the root'
        self.assertEqual(parsing._parse_document(html).headings,
                         [{"tag": "h2", "id": "sec", "text": "Title",
                           "top_level": True, "in_lede": False}])

    def test_a_new_heading_ends_the_open_one(self):
        # HTML5's h1-h6 start tag pops an open heading that is the CURRENT node, so
        # `<h2 id="a">A<h2 id="b">B` is TWO headings. Left capturing, the first swallowed the
        # second's text and the second's id was never collected at all - and the truncated form
        # is the shape this whole class is about.
        for tail, want in ((self.CR + '<h2 id="a">A<h2 id="b">B',
                            [("a", "A"), ("b", "B")]),
                           (self.CR + '<h2 id="a">A<p>prose</p><h2 id="b">B</h2>',
                            [("a", "Aprose"), ("b", "B")])):
            with self.subTest(tail=tail):
                headings = parsing._parse_document(tail).headings
                self.assertEqual([(h["id"], h["text"]) for h in headings], want)

    def test_a_child_element_inside_a_heading_does_not_end_it(self):
        # The other side of the boundary: only the heading's OWN level (or above) ends it, so an
        # inline child's end tag, and a void child that is never pushed, keep the text whole.
        for html, want in ((self.CR + '<h2 id="a">Ti<em>t</em>le</h2>', "Title"),
                           (self.CR + '<h2 id="a">Ti<em>t</em>le', "Title"),
                           (self.CR + '<h2 id="a">A<img>B</h2>', "AB"),
                           (self.CR + '<h2 id="a">A<img>B', "AB")):
            with self.subTest(html=html):
                self.assertEqual([h["text"] for h in parsing._parse_document(html).headings],
                                 [want])


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


class _CountingStack(list):
    """A list that counts every ELEMENT inspection, so a stack RESCAN is visible without a clock.

    Slice reads, iteration and reversed iteration all count the entries they expose, because the
    scans this guards against take all three shapes.
    """

    reads = 0

    def __getitem__(self, index):
        if isinstance(index, slice):
            self.reads += len(range(*index.indices(len(self))))
        else:
            self.reads += 1
        return list.__getitem__(self, index)

    def __iter__(self):
        self.reads += len(self)
        return list.__iter__(self)

    def __reversed__(self):
        self.reads += len(self)
        return list.__reversed__(self)


class _CountingIndex(dict):
    """A `tag -> open indices` mapping whose lists count their inspections the same way.

    The per-tag index is a dict of lists rather than a list, so wrapping the parser's list
    attributes alone would leave the end-tag lookup unmeasured - and a regression that searched
    one of these lists instead of taking its last entry is exactly what the budget exists to see.
    A bucket that empties is DELETED by the parser, so its reads are banked on the way out or the
    count would silently reset with it.
    """

    banked = 0

    def setdefault(self, key, default=None):
        if key not in self:
            dict.__setitem__(self, key, _CountingStack(default or ()))
        return dict.__getitem__(self, key)

    def __delitem__(self, key):
        self.banked += dict.__getitem__(self, key).reads
        dict.__delitem__(self, key)

    @property
    def reads(self):
        return self.banked + sum(v.reads for v in self.values())


class DocParserScopeCostTests(unittest.TestCase):
    """CMH-VAL-21: the shared boundaries cost O(1) of open-element stack per start tag.

    The HTML5 "close a p element" / "close an li element" step used to scan the WHOLE open-element
    stack on every block-level start tag, stopping only at a scope boundary, so a document that
    opens elements which are neither the target nor a boundary - `<div>` repeated with no closing
    tags - cost O(n) per tag and O(n^2) overall, in pure Python: 3200 `<div>`s took 1.31s and a
    5000-`<div>` document (~25 KB) had not finished after 240 seconds. `validate()` parses every
    document with `_DocParser`, and the resource checks parse it again with `_TagAttrParser`, so a
    merely pathological ~25 KB document could hang the validator.

    The budget is asserted on INSPECTIONS, not on a clock, so it is deterministic on a loaded CI
    runner and fails for the real reason rather than for a slow machine.
    """

    PARSERS = ("_DocParser", "_CodeSpanParser", "_TagAttrParser", "_RawTextSpanParser")

    # Three shapes. The first two grow the open-element stack without ever closing it - the pure
    # implicit-close case, and one that also RECORDS an element at every depth, which is what asks
    # the ancestor questions (`cm-skip` ancestry, the nearest `<svg>`, the owning `<pre>`, the
    # enclosing chart figure, an open `<a>` around prose) that used to walk the stack in their
    # turn. The third closes elements it never opened, which is the OTHER way to make a parser walk
    # the stack per tag: an end tag matches the innermost open element of its name, and finding
    # that there is none used to cost a full scan.
    SHAPES = (
        ("nested divs", "<div>"),
        ("recorded elements at depth",
         '<div id="commentRoot"><a href="x.html">t</a>text<pre><code>c</code></pre>'
         '<figure class="chart"><figcaption>f</figcaption></figure><canvas></canvas>'),
        ("stray end tags at depth", "<div></span>"),
    )

    @staticmethod
    def _stack_reads(name, html):
        parser = getattr(parsing, name)(html)
        counters = []
        for attr in ("_ns", "stack", "_stack", "_anc", "_p_stop", "_li_stop", "_mermaid_stack"):
            current = getattr(parser, attr, None)
            if isinstance(current, list):
                counted = _CountingStack(current)
                setattr(parser, attr, counted)
                counters.append(counted)
        index = _CountingIndex(parser._open_by_tag)
        parser._open_by_tag = index
        counters.append(index)
        parser.parse_document(html)
        return sum(c.reads for c in counters)

    def test_the_implicit_close_does_not_rescan_the_open_element_stack(self):
        depth = 3000
        for label, unit in self.SHAPES:
            html = unit * depth
            tags = html.count("<")
            for name in self.PARSERS:
                with self.subTest(shape=label, parser=name):
                    reads = self._stack_reads(name, html)
                    self.assertLess(
                        reads, 20 * tags,
                        "%s inspected %d open elements over %d tags (%d %s) - that is a stack "
                        "scan per start tag, so the parse is quadratic again"
                        % (name, reads, tags, depth, label))

    def test_the_open_element_stack_cost_grows_linearly_with_depth(self):
        # State the SCALING directly as well: twice the document must not cost ~four times the
        # work. A constant-factor allowance of 3x absorbs the per-parse fixed cost.
        for label, unit in self.SHAPES:
            for name in self.PARSERS:
                with self.subTest(shape=label, parser=name):
                    small = self._stack_reads(name, unit * 1000)
                    large = self._stack_reads(name, unit * 2000)
                    self.assertLess(
                        large, max(3 * small, 6000),
                        "%s inspected %d open elements over 1000 %s and %d over 2000 - that is "
                        "superlinear growth, so the stack scan is back"
                        % (name, small, label, large))

    def test_the_open_element_index_holds_only_currently_open_elements(self):
        # The end-tag lookup is answered from an index of the open elements by name, so it must
        # shrink back as they close: a document that opens and closes many DISTINCT names must
        # grow it by open depth, not by how large its tag vocabulary is. Every parallel view is
        # also asserted to be the SAME LENGTH as the namespace stack, because each replacement
        # reads one view with an index derived from another - `_CodeSpanParser.handle_endtag`
        # slices a `<pre>` body out of `_stack` at an index that came from the base's `_ns` map -
        # and nothing else states that invariant.
        names = ["x%d" % i for i in range(500)]
        for name in self.PARSERS:
            with self.subTest(parser=name):
                flat = "".join("<%s></%s>" % (t, t) for t in names)
                parser = getattr(parsing, name)(flat)
                parser.parse_document(flat)
                self.assertEqual(parser._open_by_tag, {},
                                 "closed elements are still indexed as open")
                self._assert_parallel(parser, 0)
                nested = "".join("<%s>" % t for t in names)
                parser = getattr(parsing, name)(nested)
                parser.parse_document(nested)
                self.assertEqual(sorted(parser._open_by_tag), sorted(names))
                self.assertTrue(all(len(v) == 1 for v in parser._open_by_tag.values()))
                self._assert_parallel(parser, len(names))

    def _assert_parallel(self, parser, depth):
        views = {"_ns": parser._ns, "_p_stop": parser._p_stop, "_li_stop": parser._li_stop,
                 "_tpl_stop": parser._tpl_stop}
        for attr in ("stack", "_stack", "_anc"):
            current = getattr(parser, attr, None)
            if isinstance(current, list):
                views[attr] = current
        for attr, view in views.items():
            self.assertEqual(len(view), depth,
                             "%s is %d deep beside a %d-deep namespace stack - the parallel views "
                             "have drifted, so an index taken from one no longer addresses the "
                             "other" % (attr, len(view), depth))

    def test_the_scope_boundaries_are_unchanged_at_depth(self):
        # The cheap path must still be the CORRECT path: a <p> deep under many open <div>s is
        # still implicitly closed, and one behind a scope boundary still is not.
        opened = "<div>" * 200
        closes = _anchors('<p class="cm-skip">' + opened
                          + '<div><a href="p.html" target="_self">x</a></div>')
        self.assertEqual([a["skip"] for a in closes], [False])
        blocked = _anchors('<p class="cm-skip"><button>' + opened
                           + '<div><a href="p.html" target="_self">x</a></div>')
        self.assertEqual([a["skip"] for a in blocked], [True])
        # The same for <li>, whose scope additionally stops at <ol>/<ul>.
        li_closes = _anchors('<li class="cm-skip">' + opened
                             + '<li><a href="p.html" target="_self">x</a>')
        self.assertEqual([a["skip"] for a in li_closes], [False])
        li_blocked = _anchors('<li class="cm-skip"><ul>' + opened
                              + '<li><a href="p.html" target="_self">x</a>')
        self.assertEqual([a["skip"] for a in li_blocked], [True])

    def test_the_ancestor_summary_answers_every_predicate_it_replaced(self):
        # Each running count / index stands in for a walk of the open elements, so pin each of
        # them: cm-skip ancestry, the inert <template>, the enclosing <canvas>, the chart <figure>,
        # the nearest <svg> versus <foreignObject>, and an open <a> around prose.
        html = ('<main id="commentRoot">'
                '<div class="cm-skip"><canvas id="c1"></canvas>'
                '<figure class="chart"><figcaption>a</figcaption></figure></div>'
                '<figure class="chart"><figcaption>b</figcaption></figure>'
                '<figure><figcaption>c</figcaption></figure>'
                '<canvas id="c2"><figcaption>d</figcaption></canvas>'
                '<template><canvas id="tpl"></canvas><a href="t.html">t</a></template>'
                '<svg><a href="s.html">s</a>'
                '<foreignObject><a href="f.html">f</a></foreignObject></svg>'
                '<a href="l.html">linked</a>prose</main>')
        doc = parsing._parse_document(html)
        self.assertEqual([(c["attrs"].get("id"), c["skip"]) for c in doc.canvases],
                         [("c1", True), ("c2", False)])
        self.assertEqual([(f["skip"], f["in_canvas"], f["in_chart_figure"])
                          for f in doc.figcaptions],
                         [(True, False, True), (False, False, True),
                          (False, False, False), (False, True, False)])
        self.assertEqual([(a["href"], a["in_svg"]) for a in doc.anchors],
                         [("s.html", True), ("f.html", False), ("l.html", False)])
        prose = "".join(doc.commentroot_prose)
        self.assertIn("prose", prose)
        self.assertNotIn("linked", prose)   # text inside an <a> is not unlinked prose


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


class DocParserNameFoldTests(unittest.TestCase):
    """Tag and ATTRIBUTE names fold ASCII-case-insensitively, the way a browser folds them
    (CMH-VAL-21 clause 7).

    `html.parser` hands its handlers `name.lower()` - Python's UNICODE fold - and U+212A KELVIN
    SIGN lowercases to an ASCII "k". So `data-<K>ey` arrives as `data-key`, `<lin<K>>` as
    `<link>` and `</mar<K>>` as a `</mark>` closer, while a browser keeps every one of them a
    DIFFERENT name. "k" is the whole reachable surface: no other character outside ASCII
    lowercases to an ASCII letter, so only a name spelled with a "k" can collide.

    Every pin here is red if its name is folded with `str.lower()` instead - EXCEPT the last,
    `test_an_ascii_uppercase_name_still_folds`, which is deliberately green on the old code: it
    is the non-regression half of the rule (ASCII case must still fold).
    """

    def test_an_attribute_name_folds_ascii_case_only(self):
        html = '<div id="commentRoot" DATA-%sEY="v"></div>' % KELVIN
        self.assertEqual(dict(parsing._parse_document(html).comment_root_attrs),
                         {"id": "commentRoot", "data-%sey" % KELVIN: "v"})

    def test_the_shared_attribute_helper_folds_names_ascii_case_only(self):
        # The one helper every attribute view in the checks package builds its dict from, so
        # the checklist, notes, density and tag-lookup passes fold the same way by construction.
        parser = _StaleRawTagParser('<div DATA-%sEY="v" DATA-B="w">' % KELVIN)
        self.assertEqual(parser.attrs_for("div", []),
                         {"data-%sey" % KELVIN: "v", "data-b": "w"})

    def test_a_tag_lookup_folds_ascii_case_only(self):
        self.assertEqual(parsing._find_tag_attrs('<lin%s rel="icon">' % KELVIN, "link"), [])
        self.assertEqual(parsing._find_tag_attrs('<LINK rel="icon">', "link"), [{"rel": "icon"}])

    def test_a_start_tag_name_folds_ascii_case_only(self):
        # `<lin<K>>` is not a `<link>`, so it contributes no favicon link - and, not being VOID,
        # it is an ordinary element a browser leaves OPEN.
        html = '<head><lin%s rel="icon" href="f.ico"></head>' % KELVIN
        self.assertEqual(parsing._parse_document(html).icon_links, [])
        self.assertEqual(parsing._parse_document(
            '<head><LINK rel="icon" href="f.ico"></head>').icon_links,
            [{"rel": "icon", "href": "f.ico"}])

    def test_the_code_block_tokenizer_folds_tag_names_ascii_case_only(self):
        # `</mar<K>>` is not a `</mark>`, so it does not pop the `<mark>` - and with it the open
        # `<pre>`, which would destroy the code block's span and fail every consumer closed.
        spans = parsing.code_block_spans(
            '<mark><pre>x</mar%s>y</pre></mark>' % KELVIN)
        self.assertEqual(len(spans.pres), 1)
        self.assertFalse(spans.unclosed)
        self.assertIsNotNone(spans.pres[0]["inner"])

    def test_an_end_tag_name_folds_ascii_case_only(self):
        # `</mar<K>>` is not a `</mark>`, so the cm-skip `<mark>` is still open and still covers
        # the canvas after it.
        html = ('<div id="commentRoot"><mark class="cm-skip">x</mar%s>'
                '<canvas id="c"></canvas></div>' % KELVIN)
        self.assertEqual([c["skip"] for c in parsing._parse_document(html).canvases], [True])

    def test_the_checklist_pass_folds_tag_names_ascii_case_only(self):
        # `<lin<K>>` is not a `<link>`, so it is not VOID: it is pushed, and its end tag really
        # closes the container, leaving the later item OUTSIDE it.
        parser = checklist._ChecklistParser()
        parser.feed('<lin%s data-cmh-checklist="c"><li data-cmh-item="a"></li></lin%s>'
                    '<li data-cmh-item="b"></li>' % (KELVIN, KELVIN))
        parser.close()
        self.assertEqual([[i["item_id"] for i in inst["items"]] for inst in parser.instances],
                         [["a"]])

    def test_the_notes_pass_folds_tag_names_ascii_case_only(self):
        # Same non-VOID consequence for a note: it is a real element that can hold children.
        parser = notes._NotesParser()
        parser.feed('<lin%s data-cmh-note="n"><span>x</span></lin%s>' % (KELVIN, KELVIN))
        parser.close()
        self.assertEqual([(n["void"], n["has_child"]) for n in parser.notes], [(False, True)])

    def test_the_density_pass_folds_tag_names_ascii_case_only(self):
        # `<bloc<K>quote>` is not a `<blockquote>`, so it is not a layout-bearing block and does
        # not break the prose run: the four long paragraphs are still one wall.
        long_p = "<p>%s</p>" % ("This sentence is deliberately padded out with filler words " * 5)
        for name, expect_wall in (("bloc%squote" % KELVIN, True), ("blockquote", False)):
            with self.subTest(name=name):
                inner = long_p * 2 + "<%s></%s>" % (name, name) + long_p * 2
                html = ('<!doctype html><html><head>'
                        '<meta name="commentable-html-kind" content="report"></head><body>'
                        '<main id="commentRoot" data-cmh-content-root><h1>T</h1>'
                        '<section><h2>S</h2>%s</section></main></body></html>' % inner)
                _errors, warnings = density.check_density(html)
                self.assertEqual(bool(warnings), expect_wall, warnings)

    def test_an_ascii_uppercase_name_still_folds(self):
        # The other half of the rule: ASCII case is still folded, so a browser-equivalent
        # spelling is not read as a different element or attribute.
        html = '<DIV ID="commentRoot" CLASS="cm-skip"><CANVAS></CANVAS></DIV>'
        parser = parsing._parse_document(html)
        self.assertEqual(dict(parser.comment_root_attrs),
                         {"id": "commentRoot", "class": "cm-skip"})
        self.assertEqual([c["skip"] for c in parser.canvases], [True])


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

    def test_a_control_character_reference_is_preserved_in_an_attribute(self):
        # A BROWSER's numeric character reference end state only reports a parse error for a
        # control character - it KEEPS the code point - so `id="a&#1;b"` really is `a\x01b` in
        # the DOM. `html.unescape` DELETES the whole reference, so the validator read a
        # different id, href, class, meta content or companion-resource path than the document
        # carries, on every interpreter (this is not the 3.12/3.13 drift; both agree, and both
        # disagree with the browser).
        for source, expected in (("a&#1;b", "a\x01b"), ("a&#x1;b", "a\x01b"),
                                 ("a&#11;b", "a\x0bb"), ("a&#x7f;b", "a\x7fb"),
                                 ("a&#129;b", "a\x81b"), ("a&#x8d;b", "a\x8db")):
            with self.subTest(source=source):
                self.assertEqual(_ids('<div id="%s"></div>' % source), [expected])

    def test_a_noncharacter_reference_is_preserved_in_an_attribute(self):
        # Same rule for the noncharacters: a parse error, not a deletion.
        for source, expected in (("a&#xfdd0;b", "a\ufdd0b"), ("a&#xffff;b", "a\uffffb"),
                                 ("a&#x1fffe;b", "a\U0001fffeb")):
            with self.subTest(source=source):
                self.assertEqual(_ids('<div id="%s"></div>' % source), [expected])

    def test_a_c1_reference_is_remapped_in_an_attribute(self):
        # The WHOLE C1 (0x80-0x9F) replacement table the HTML tokenizer applies, entry by entry -
        # a sampled test would let a typo in any unsampled row ship. The five code points the
        # table does NOT list (0x81, 0x8D, 0x8F, 0x90, 0x9D) are kept as themselves, like any
        # other control character. (`html.unescape` agrees on the 27 mapped rows, so those are
        # positive confirmation rather than red-before; the five unmapped ones are the ones it
        # deletes, and they are covered by the control-character test above.)
        table = {
            0x80: "\u20ac", 0x82: "\u201a", 0x83: "\u0192", 0x84: "\u201e", 0x85: "\u2026",
            0x86: "\u2020", 0x87: "\u2021", 0x88: "\u02c6", 0x89: "\u2030", 0x8a: "\u0160",
            0x8b: "\u2039", 0x8c: "\u0152", 0x8e: "\u017d", 0x91: "\u2018", 0x92: "\u2019",
            0x93: "\u201c", 0x94: "\u201d", 0x95: "\u2022", 0x96: "\u2013", 0x97: "\u2014",
            0x98: "\u02dc", 0x99: "\u2122", 0x9a: "\u0161", 0x9b: "\u203a", 0x9c: "\u0153",
            0x9e: "\u017e", 0x9f: "\u0178",
        }
        for code in range(0x80, 0xa0):
            expected = table.get(code, chr(code))
            for source in ("&#%d;" % code, "&#x%x;" % code, "&#X%X;" % code):
                with self.subTest(source=source):
                    self.assertEqual(_ids('<div id="a%sb"></div>' % source), ["a%sb" % expected])
        self.assertEqual(parsing._C1_CHARREF_REPLACEMENTS, table)

    def test_a_reference_the_host_can_decode_is_left_to_the_host(self):
        # The recovery path decides "is this tag an element, and where does it end" with a SECOND
        # tokenizer, so ordinary markup must never reach it: a merely long or zero-padded
        # reference is still handed to the host, and only a run no authored document contains
        # (and that the host would raise on) is taken away.
        for value in ("&#65;", "&#0000065;", "&#1114111;", "&#x10FFFF;", "&#%s;" % ("0" * 20),
                      "&#%s;" % ("a" * 64)):
            with self.subTest(value=value):
                self.assertIsNone(parsing._BIG_CHARREF_RE.search('<div id="%s">' % value))
        self.assertIsNotNone(parsing._BIG_CHARREF_RE.search('<div id="&#%s;">' % ("9" * 5000)))
        self.assertIsNotNone(parsing._BIG_CHARREF_RE.search('<div id="&#x%s;">' % ("f" * 64)))

    def test_an_out_of_range_or_surrogate_reference_is_the_replacement_character(self):
        for source in ("&#0;", "&#x0;", "&#xd800;", "&#xdfff;", "&#x110000;", "&#1114112;"):
            with self.subTest(source=source):
                self.assertEqual(_ids('<div id="%s"></div>' % source), ["\ufffd"])

    def test_an_oversized_numeric_reference_resolves_to_the_replacement_character(self):
        # A reference with more digits than Python's integer conversion limit makes
        # `html.unescape` RAISE, and the HOST's own `parse_starttag` decodes the value before
        # this module is reached - so the whole parse was swallowed into a TRUNCATED one and
        # every finding after that tag disappeared. A browser just resolves anything past
        # 0x10FFFF to U+FFFD, so the decode is bounded and total, and the start tag is
        # re-dispatched from its RAW text when the host refuses it.
        for ref in ("&#%s;" % ("9" * 5000), "&#x%s;" % ("f" * 5000), "&#%s" % ("9" * 5000)):
            with self.subTest(ref=ref):
                self.assertEqual(parsing._unescape_attr_value("a" + ref + "b"), "a\ufffdb")
                self.assertEqual(_ids('<div id="a%sb"></div>' % ref), ["a\ufffdb"])
                metas = parsing._find_tag_attrs(
                    '<meta name="x" content="a%sb">' % ref, "meta")
                self.assertEqual([d.get("content") for d in metas], ["a\ufffdb"])

    def test_a_start_tag_the_host_refused_to_decode_does_not_truncate_the_parse(self):
        # The re-dispatch keeps the REST of the document live: a self-closed tag still reaches
        # handle_startendtag, a raw-text element still enters its text region, and the elements
        # after the offending tag are still collected.
        ref = "&#%s;" % ("9" * 5000)
        html = ('<meta id="m%s"/>'
                '<script id="s%s">var u = "<div id=\'quoted\'>";</script>'
                '<div id="after"></div>') % (ref, ref)
        self.assertEqual(_ids(html), ["m\ufffd", "s\ufffd", "after"])

    def test_the_raw_tag_path_dispatches_exactly_what_the_host_would(self):
        # The tag taken away from the host must produce the SAME event stream the host produces -
        # otherwise the recovery path is its own dialect. The comparison is run on the SAME bytes
        # both ways (the routing regex is widened so an ordinary `&#65;` takes the recovery path),
        # so attribute VALUES and data payloads are compared too, not just the event shape.
        # Pinned over the shapes that decide start-vs-startend and raw-text entry, including an
        # UNQUOTED value that swallows a trailing `/` (`<div a=b/>` is a normal start tag whose
        # value is `b/`, NOT a self-closed tag) and a tag whose attributes stop before the close.
        for shape in ('<div id="&#65;" a=b/>x</div>', '<div id="&#65;"/>x</div>',
                      '<div id=&#65;/>x</div>', '<div a=1 id="&#65;" />x</div>',
                      '<script id="&#65;">var u = "<b id=\'q\'>";</script>',
                      '<textarea id="&#65;"><b id="q"></b></textarea>',
                      '<title id="&#65;"><b id="q"></b></title>',
                      '<plaintext id="&#65;"><b id="q"></b>',
                      '<div id="&#65;" a="1"b>x</div>', '<div id="&#65;">x</div>',
                      '<div id="&#65;" a="1" a="2">x</div>', '<svg><rect id="&#65;"/></svg>'):
            with self.subTest(shape=shape):
                host = _EventProbe()
                host.parse_document(shape)
                ours = _EventProbe()
                with _force_raw_tag_path():
                    ours.parse_document(shape)
                self.assertEqual(ours.events, host.events, shape)

    def test_an_oversized_reference_keeps_every_shared_parser_reading(self):
        # Each check-local parser derives from the shared base for the same reason, and each one
        # swallows a parse failure its own way - so pin, per parser, that the elements AFTER the
        # offending tag are still seen. Without the shared base these all go silently empty.
        ref = "&#%s;" % ("9" * 5000)
        _errors, warnings = checklist.check_checklists(
            '<div data-cmh-checklist="c1">'
            '<li data-cmh-state="check" data-cmh-item="a%s">a</li>'
            '<li data-cmh-state="check" data-cmh-item="dup">b</li>'
            '<li data-cmh-state="check" data-cmh-item="dup">c</li></div>' % ref)
        self.assertTrue(any('duplicate data-cmh-item id "dup"' in w for w in warnings), warnings)

        note_parser = notes._NotesParser()
        note_parser.feed('<p data-cmh-note="a%s">n</p><p data-cmh-note="after">m</p>' % ref)
        note_parser.close()
        self.assertEqual([n["id"] for n in note_parser.notes], ["a\ufffd", "after"])

        parsing.code_block_spans.cache_clear()
        try:
            spans = parsing.code_block_spans(
                '<pre id="a%s"><code class="language-python">x</code></pre>' % ref)
        finally:
            parsing.code_block_spans.cache_clear()
        self.assertFalse(spans.failed)
        self.assertEqual(spans.pres[0]["attrs"]["id"], "a\ufffd")

        wall = "<p>%s</p>" % ("word " * 80)
        _derrors, dwarnings = density.check_density(
            '<meta name="commentable-html-kind" content="report">'
            '<main id="commentRoot"><section id="s%s"><h2>H</h2>%s</section></main>'
            % (ref, wall * 5))
        self.assertTrue(dwarnings, "the density pass saw nothing after the offending tag")

    def test_an_oversized_reference_in_an_attribute_still_yields_contrast_findings(self):
        # The contrast scanners were the last parse path in the validator on a bare `HTMLParser`,
        # so the host's attribute decode raised and `check_theme_contrast` degraded the WHOLE
        # advisory to nothing (or, once that was noticed, to "could not be read"). Sharing the
        # start-tag base makes the same reference resolve to U+FFFD, so the document is read and
        # its authored override is judged like any other.
        ref = "&#%s;" % ("9" * 5000)
        doc = ('<div id="a%s"></div>'
               "<style>:root{--cp-text:#eeeeee;--cp-bg:#ffffff;}</style>" % ref)
        findings = theme_contrast.theme_contrast_findings(doc)
        self.assertTrue(
            any(f.label == "body text" and f.severity == "error" for f in findings), findings)
        errors, _warnings = theme_contrast.check_theme_contrast(doc)
        self.assertTrue(any("body text" in e for e in errors), errors)
        self.assertFalse(
            any("oversized numeric character reference" in e for e in errors), errors)

    def test_a_document_the_contrast_scan_cannot_read_is_reported_not_skipped(self):
        # Both shapes are bounded now: the scan's START TAGS through the shared start-tag base,
        # and its TEXT through the shared bounded decode (issue #946) - which this scan now
        # inherits along with the element BOUNDARIES. So the document is READ, its authored
        # override is judged like any other, and the "could not be read for contrast" report
        # that stood in for the refusal is gone with the refusal.
        ref = "&#%s;" % ("9" * 5000)
        attr_errors, _aw = theme_contrast.check_theme_contrast(
            '<div id="a%s"></div><style>:root{--cp-text:#fff;}</style>' % ref)
        self.assertEqual(attr_errors, [])
        # And the same in the document's TEXT, which used to raise there: the override is
        # judged rather than the whole check being disabled by one reference.
        errors, _warnings = theme_contrast.check_theme_contrast(
            "<p>a%sb</p><style>:root{--cp-text:#eeeeee;--cp-bg:#ffffff;}</style>" % ref)
        self.assertTrue(any("body text" in e for e in errors), errors)
        self.assertFalse(
            any("oversized numeric character reference" in e for e in errors), errors)
        self.assertEqual(theme_contrast.check_theme_contrast("<div id=a></div>")[0], [])

    def test_the_raw_tag_path_dispatches_each_tag_exactly_once(self):
        # A recovery that ran BESIDE the host's own dispatch (rather than instead of it) would
        # double-record the element - a duplicate id, a duplicate checklist item, a duplicate
        # note - so pin the count, not just the value.
        ref = "&#%s;" % ("9" * 5000)
        probe = _EventProbe()
        probe.parse_document('<div id="a%s"></div>' % ref)
        self.assertEqual(probe.events,
                         [("start", "div", (("id", "a\ufffd"),)), ("end", "div")])

    def test_a_handler_error_is_not_mistaken_for_a_host_decode_refusal(self):
        # The host calls handle_starttag INSIDE parse_starttag, so RECOVERING BY CATCHING would
        # swallow a subclass's own ValueError and dispatch the tag a second time. The refusal is
        # detected up front instead, so a handler bug still propagates.
        class _Boom(_EventProbe):
            def handle_starttag(self, tag, attrs):
                raise ValueError("handler bug")

        for source in ('<div id="a"></div>', '<div id="a&#%s;"></div>' % ("9" * 5000)):
            with self.subTest(source=source):
                with self.assertRaises(ValueError):
                    _Boom().parse_document(source)

    def test_an_incomplete_start_tag_still_waits_for_more_input(self):
        # `check_for_whole_start_tag` says "not yet" with -1; the recovery path must pass that
        # through rather than inventing a tag out of a partial one.
        probe = _EventProbe()
        probe.feed('<div id="a&#%s;" ' % ("9" * 5000))
        self.assertEqual(probe.events, [])
        probe.feed('class="c">')
        probe.close()
        self.assertEqual(probe.events, [("start", "div", (("id", "a\ufffd"), ("class", "c")))])


class _EventProbe(parsing._BrowserStartTag):
    """A PLAIN start-tag parser that records the dispatch stream. Deliberately not a
    `_BrowserBoundaries` subclass: that one installs the BROWSER's raw-text set from its own
    `handle_starttag`, which would mask a divergence in the recovery path's raw-text entry."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.events = []

    def parse_document(self, html):
        self.feed(html)
        self.close()

    def _attrs(self, tag, attrs):
        return tuple(parsing._browser_attrs(self, tag, attrs))

    def handle_starttag(self, tag, attrs):
        self.events.append(("start", tag, self._attrs(tag, attrs)))

    def handle_startendtag(self, tag, attrs):
        self.events.append(("startend", tag, self._attrs(tag, attrs)))

    def handle_endtag(self, tag):
        self.events.append(("end", tag))

    def handle_data(self, data):
        self.events.append(("data", data))


@contextlib.contextmanager
def _force_raw_tag_path():
    """Widen the routing regex so an ORDINARY numeric reference is taken away from the host, and
    the recovery path can be compared against the host on byte-identical input."""
    with mock.patch.object(parsing, "_BIG_CHARREF_RE",
                           re.compile(r"&#[xX]?[0-9a-fA-F]{2,}")):
        yield


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


class DocParserTextCharrefTests(unittest.TestCase):
    """The document's TEXT character references, decoded by the same BROWSER rule the attribute
    path uses (CMH-VAL-21).

    With `convert_charrefs=True` the host decodes each text run inside `goahead()` with
    `html.unescape()`, which is not the browser rule: it DELETES the code points it deems
    invalid and RAISES on a numeric reference past Python's integer conversion limit. That
    `ValueError` escaped `feed()`, and every parse entry point swallows an exception into a
    truncated parse - so ONE oversized reference in PROSE reported the whole document as
    unparseable and hid every finding in it, where a browser renders U+FFFD and reads on.
    """

    # The three shapes the host cannot decode: a decimal run past its integer conversion limit,
    # a hex run (no limit, but a big integer built and thrown away), and the same decimal run
    # with no closing semicolon - a reference resolves without one.
    OVERSIZED = ("&#%s;" % ("9" * 5000), "&#x%s;" % ("f" * 5000), "&#%s" % ("9" * 5000))

    def _texts(self, html):
        probe = _EventProbe()
        probe.parse_document(html)
        return [e[1] for e in probe.events if e[0] == "data"]

    def test_an_oversized_reference_in_text_resolves_to_the_replacement_character(self):
        for ref in self.OVERSIZED:
            with self.subTest(ref=ref):
                html = '<p id="p">x%sy</p><div id="after"></div>' % ref
                self.assertEqual(self._texts(html), ["x\ufffdy"])
                self.assertEqual(_ids(html), ["p", "after"])

    def test_an_oversized_reference_in_text_does_not_fail_the_document(self):
        # The validator's own entry point: the parse used to blow up here, so the document was
        # reported as unparseable instead of validated. Every parser the run builds must read it,
        # including the contrast scan's own (which is not built on the shared base), or the
        # document is still refused - just with a different diagnostic.
        html = _validate_html_with("x%sy" % self.OVERSIZED[0])
        self.assertTrue(validate._parse(html)[1], "the document parse still fails closed")
        errors, warnings = _validate_text(html)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])
        self.assertEqual(theme_contrast.check_theme_contrast(
            "<p>x%sy</p><style>:root{--cp-text:#fff;}</style>" % self.OVERSIZED[0]), ([], []))

    def test_an_oversized_reference_in_text_keeps_the_raw_offset_views_exact(self):
        # `code_block_spans()` and `content_marker_scan()` read RAW offsets into the ORIGINAL
        # document, so the decode must never move a single character of it.
        ref = self.OVERSIZED[0]
        html = ('<p>x%sy</p>\n<pre id="code"><code class="language-python">print(1)</code></pre>'
                "\n<script>var quoted = \"<!-- END: commentable-html - CSS -->\";</script>" % ref)
        parsing.code_block_spans.cache_clear()
        parsing.content_marker_scan.cache_clear()
        try:
            spans = parsing.code_block_spans(html)
            scan = parsing.content_marker_scan(html)
        finally:
            parsing.code_block_spans.cache_clear()
            parsing.content_marker_scan.cache_clear()
        self.assertFalse(spans.failed)
        start, end = spans.pres[0]["codes"][0]["inner"]
        self.assertEqual(html[start:end], "print(1)")
        self.assertEqual(len(scan), len(html))
        self.assertEqual(scan.index("<pre"), html.index("<pre"))
        # The raw-text body is blanked in place, so the quoted region marker is not a boundary.
        self.assertNotIn("END: commentable-html - CSS", scan)

    def test_a_text_reference_follows_the_browser_rule_not_html_unescape(self):
        # The same end state the attribute path applies: a control character and a noncharacter
        # are KEPT (`html.unescape` deletes them), the null character, a surrogate and anything
        # past U+10FFFF are U+FFFD, and the C1 table is applied.
        for source, expected in (("a&#1;b", "a\x01b"), ("a&#x1;b", "a\x01b"),
                                 ("a&#x7f;b", "a\x7fb"), ("a&#x8d;b", "a\x8db"),
                                 ("a&#xfdd0;b", "a\ufdd0b"), ("a&#xffff;b", "a\uffffb"),
                                 ("a&#0;b", "a\ufffdb"), ("a&#xd800;b", "a\ufffdb"),
                                 ("a&#x110000;b", "a\ufffdb"), ("a&#128;b", "a\u20acb"),
                                 ("a&#65;b", "aAb"), ("a&#x41;b", "aAb")):
            with self.subTest(source=source):
                self.assertEqual(self._texts("<p>%s</p>" % source), [expected])
                self.assertEqual(parsing._unescape_text(source), expected)

    def test_a_named_text_reference_keeps_the_hosts_longest_match_rule(self):
        # TEXT resolves a named reference by longest match (`&notit;` is `\u00ac` + `it;`), which
        # is what `html.unescape` already does and is NOT the attribute rule (there the same
        # source stays literal). Only the numeric branch diverges from the host, so a
        # differential run over the named shapes must agree with it exactly.
        for source in ("a&amp;b", "a&notit;b", "a&not-it;b", "a&nota;b", "a&not=b",
                       "a&unknownref;b", "a & b", "plain text", "&", "&#", "&#x", "&;",
                       "a&%s;b" % ("z" * 40), "&amp;&amp;", "&lt;div&gt;"):
            with self.subTest(source=source):
                self.assertEqual(parsing._unescape_text(source), _html.unescape(source))
                self.assertEqual(self._texts("<p>%s</p>" % source), [_html.unescape(source)])

    def test_every_shared_parser_reads_text_through_the_bounded_decode(self):
        # One decode for the whole checks package: a parser that kept the host's would make the
        # same document readable to one check and unparseable to another.
        self.assertTrue(parsing._TEXT_CHARREF_BOUNDED,
                        "the host's goahead no longer resolves `unescape` as a global")
        for cls in (parsing._DocParser, parsing._CodeSpanParser, parsing._RawTextSpanParser,
                    parsing._TagAttrParser, density._DensityParser, notes._NotesParser):
            with self.subTest(cls=cls.__name__):
                self.assertIs(cls.goahead, parsing._BrowserTagNames.goahead)
                self.assertIsNot(cls.goahead, HTMLParser.goahead)
        # The contrast scan builds its own parser OUTSIDE the checks package, and reads the same
        # decode through the shim beside the tools.
        self.assertIs(contrast._StyleScanner.goahead, parsing._BrowserTagNames.goahead)

    def test_every_document_reading_tool_reads_the_same_text(self):
        # A document the validator now READS must also be one the tools beside it can stamp,
        # hash, count, index and upgrade - otherwise it validates clean and then cannot be
        # finalized, which is the same defect one step later.
        for cls in _TOOL_PARSERS:
            with self.subTest(cls=cls.__name__):
                self.assertIs(cls.goahead, parsing._BrowserTagNames.goahead)

    def test_the_authoring_tools_survive_an_oversized_reference_in_text(self):
        # Exercised through the real entry points, not just the class attribute.
        ref = self.OVERSIZED[0]
        html = ('<main id="commentRoot"><h2 id="s">Head</h2><p>x%sy</p></main>' % ref)
        self.assertIn("s", section_hash.extract_section_hashes(html))
        self.assertTrue(section_hash.document_content_hash(html))
        self.assertEqual(doc_stats.count_sections(html), 1)
        self.assertTrue(generate_toc.build_toc(html))

    def test_an_invisible_title_does_not_satisfy_the_title_requirement(self):
        # A control character or a zero-width space renders NOTHING, so a heading made only of
        # them is not a title a reader can see. They reach the check at all because a text
        # reference is now decoded by the browser rule instead of being deleted by
        # `html.unescape`, so without this an `<h1>&#1;</h1>` would satisfy a report's title.
        # U+FFFD and a character assigned in a NEWER Unicode than the host's are visible: a
        # browser draws both, and deciding by "unassigned here" would give one document two
        # verdicts depending on the interpreter's Unicode version.
        for title, ok in (("Real title", True), ("&#1;", False), ("&#x7f;", False),
                          ("&#xfffe;", False), ("&#xfdd0;", False), ("\u200b", False),
                          ("&#xfffd;", True), ("\U0001fa89", True),
                          (" \u200b Real \u200b ", True)):
            with self.subTest(title=title):
                doc = build(kind="report",
                            body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(),
                                  MAIN.replace("<p>content</p>",
                                               "<h1>%s</h1><p>content</p>" % title),
                                  JS_REGION])
                errors, _warnings = _validate_text(doc)
                title_errors = [e for e in errors if "requires a top-level <h1> title" in e]
                self.assertEqual(not title_errors, ok, errors)

    def test_the_visible_text_rule_is_the_same_one_every_check_asks(self):
        # The contrast scan asks the same question ("does this element SHOW text?"), so it must
        # get the same answer - otherwise an invisible character is not a title to one check and
        # is text worth a contrast finding to the other, in the SAME run.
        self.assertIs(kind.visible_text, parsing.visible_text)

        def _element_findings(body):
            doc = ('<style>:root{--cp-bg:#ffffff;--cp-text:#f6f6f6;}'
                   ".x{color:var(--cp-text);background:var(--cp-bg);}</style>"
                   '<span class="x">%s</span>' % body)
            return [f for f in contrast.find_low_contrast_pairs(doc)
                    if f.source.startswith("element")]

        self.assertTrue(_element_findings("real text"))
        for source in ("", "&#1;", "&#x7f;", "&#xfffe;", "\u200b"):
            with self.subTest(source=source):
                self.assertEqual(_element_findings(source), [])

    def test_the_bounded_decode_degrades_instead_of_breaking_a_partial_install(self):
        # Both fallbacks the fix promises: a host whose `goahead` cannot be re-bound keeps the
        # host's own method, and a tool that cannot import the decoder keeps its own.
        def _no_unescape(self, end):    # a stand-in host whose goahead never names `unescape`
            return 0

        with mock.patch.object(parsing.HTMLParser, "goahead", _no_unescape):
            self.assertIsNone(parsing._bind_text_goahead())
        sentinel = object()
        with mock.patch.object(_browser_attrs, "_parsing", None):
            self.assertIs(_browser_attrs.text_goahead(sentinel), sentinel)
            self.assertEqual(_browser_attrs.visible_text("a\x01b"), "a\x01b")
            self.assertEqual(_browser_attrs.unescape_text("a&amp;b"), "a&b")
            self.assertEqual(_browser_attrs.unescape_attr_value("a&amp;b"), "a&b")

    def test_the_bounded_decode_leaves_the_hosts_tokenizer_alone(self):
        # Only the DECODE of a text run is replaced; the run boundaries, the positions and the
        # dispatch stay the host's own, so a document with no character reference at all is
        # delivered exactly as the host delivers it.
        source = ('<div id="a">one</div><!-- c --><textarea>raw <b> text</textarea>'
                  "<script>var x = 1;</script><p>two</p>")

        class _Host(_EventProbe):
            goahead = HTMLParser.goahead

        ours, host = _EventProbe(), _Host()
        ours.parse_document(source)
        host.parse_document(source)
        self.assertEqual(ours.events, host.events)


def _validate_html_with(prose):
    """A minimal valid document whose CONTENT region carries `prose`."""
    return build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(),
                       MAIN.replace("<p>content</p>", "<p>%s</p>" % prose), JS_REGION])


class DocParserStartTagExtentTests(unittest.TestCase):
    """Where a start tag ENDS - and whether there is a start tag at all - decided here.

    `html.parser` leaves that to `check_for_whole_start_tag`, which reads whichever regex the
    host happens to ship (`locatestarttagend_tolerant` before 3.13, `locatetagend` from 3.13),
    and neither is the browser's rule: pre-3.13 stops a tag NAME at a NUL, 3.13 keeps the NUL
    where a browser writes U+FFFD, and BOTH resolve an unterminated quoted attribute value by
    closing the tag at some later `>` - reading what a browser swallows as further attribute
    NAMES - instead of discarding the tag at EOF as the HTML5 eof-in-tag error requires. The
    same bytes were three different documents. Most assertions below pin the BROWSER answer,
    which no host produces, so they are red on every interpreter if the vendored scanner goes
    away; the rest are deliberate NON-REGRESSION pins for behavior a host already got right
    (that a truncated tag still waits for more input mid-stream, and that a self-closing tag is
    still dispatched as one), so that vendoring the whole `parse_starttag` cannot quietly lose
    it.
    """

    class _TagRecorder(parsing._DocParser):
        def __init__(self, html):
            super().__init__(html)
            self.tags_seen = []

        def handle_starttag(self, tag, attrs):
            self.tags_seen.append((tag, tuple(attrs)))
            super().handle_starttag(tag, attrs)

    def _tags(self, html):
        p = self._TagRecorder(html)
        p.parse_document(html)
        return [t for t, _attrs in p.tags_seen]

    def test_a_nul_in_a_tag_name_is_a_replacement_character(self):
        # HTML5 tag-name state: a NUL is the unexpected-null-character parse error and becomes
        # U+FFFD. Pre-3.13 html.parser TRUNCATES the name there (so `<div\x00x>` is a real
        # `<div>`) and 3.13 keeps the NUL - one document, three element names.
        self.assertEqual(self._tags('<div\x00x id="real"></div>'), ["div\ufffdx"])

    def test_a_nul_in_a_tag_name_does_not_open_a_raw_text_element(self):
        # The browser-visible consequence of the name: `<script\x00>` is not a `<script>`, so
        # what follows is live markup, not a swallowed raw-text body.
        self.assertEqual(_ids('<script\x00><div id="real"></div>'), ["real"])

    def test_a_nul_in_an_attribute_name_or_value_is_a_replacement_character(self):
        # The same tokenizer rule decides the attribute name and value states, so the id and
        # tag-lookup views must fold a NUL too rather than carry a host-specific one.
        self.assertEqual(_ids('<div id="a\x00b"></div>'), ["a\ufffdb"])
        self.assertEqual(parsing._find_tag_attrs('<meta a\x00b="1">', "meta"),
                         [{"a\ufffdb": "1"}])

    def test_an_unterminated_quoted_attribute_value_discards_the_tag(self):
        # A quoted value runs to its matching quote; EOF inside it is the eof-in-tag error,
        # which DISCARDS the tag - so everything after the opening quote belongs to a tag that
        # never was, not to live markup. The host's value regex simply fails to match and what
        # follows is re-read as attribute NAMES, closing the tag at the next `>` and
        # resurrecting elements a browser never builds.
        for quote in ('"', "'"):
            with self.subTest(quote=quote):
                html = "<div id=wrap></div><p a =%sx><div id=real></div>" % quote
                self.assertEqual(_ids(html), ["wrap"])

    def test_an_unterminated_quoted_attribute_value_is_dropped_at_eof(self):
        raw = '<p a ="x><div id=real>'
        p = self._TagRecorder(raw)
        p.rawdata = raw
        p._final = True
        self.assertEqual(p.parse_starttag(0), len(raw),
                         "EOF inside a quoted attribute value must discard the whole tag")
        self.assertEqual(p.tags_seen, [])

    def test_a_truncated_tag_still_waits_for_more_input_before_the_end(self):
        # The drop is an END-OF-INPUT rule: mid-stream the scanner must still ask for more
        # data, or an incremental caller loses a tag merely split across two feed() chunks.
        raw = '<p a ="x'
        p = self._TagRecorder(raw)
        p.rawdata = raw
        self.assertEqual(p.parse_starttag(0), -1)

    def test_every_attribute_view_shares_the_vendored_extent(self):
        # The extent is not the document parser's alone: the tag lookup and the checklist,
        # notes and density passes read it too, so one document cannot be two documents
        # depending on which check is asking.
        self.assertEqual(parsing._find_tag_attrs('<meta x ="1><meta name=real>', "meta"), [])
        note_parser = notes._NotesParser()
        note_parser.feed('<p x ="1><p data-cmh-note="n1">a</p>')
        note_parser.close()
        self.assertEqual(note_parser.notes, [])
        _errors, warnings = checklist.check_checklists(
            '<div data-cmh-checklist="c1"><li x ="1>'
            '<li data-cmh-state="check" data-cmh-item="i1">a</li></div>')
        self.assertEqual(warnings, [])

    def test_a_reused_parser_does_not_start_the_next_document_at_eof(self):
        # `reset()` starts the NEXT document, so the end-of-input flag must be cleared there and
        # not only set in close(). A leaked flag makes every later mid-stream "incomplete" look
        # like EOF, silently discarding a tag split across two feed() chunks.
        p = notes._NotesParser()
        p.feed('<p data-cmh-note="one">a</p>')
        p.close()
        p.reset()
        p.feed('<p data-cmh-note="t')
        p.feed('wo">a</p><p data-cmh-note="three">b</p>')
        p.close()
        self.assertEqual([n["id"] for n in p.notes], ["one", "two", "three"])

    def test_the_scanner_folds_the_tag_name_ascii_only(self):
        # The scanner now owns the tag name, so CMH-VAL-21 clause 7 has to hold INSIDE it:
        # `str.lower()` folds U+212A KELVIN SIGN to an ASCII "k", which would make `<scrip\u212a>`
        # a `<script>` and put every parser into raw text for an element a browser builds as
        # unknown - swallowing the rest of the document up to the next `</script`.
        self.assertEqual(parsing._scan_start_tag("<scrip\u212a>", 0)[1], "scrip\u212a")
        self.assertEqual(
            parsing._find_tag_attrs("<scrip\u212a><meta name=hidden></scrip\u212a>"
                                    "<meta name=real>", "meta"),
            [{"name": "hidden"}, {"name": "real"}])

    def test_a_narrow_parser_keeps_script_and_style_opaque(self):
        # In HTML content a `<script>`/`<style>` body is TEXT, so a tag a reader only SEES quoted
        # inside one is not an element - for the tag lookup exactly as for the document parser.
        # (What a browser does with those two inside SVG/MathML is a separate, open question,
        # tracked in #959; nothing here exercises it.)
        self.assertEqual(
            parsing._find_tag_attrs('<script>var a = "<meta name=hidden>";</script>'
                                    "<meta name=real>", "meta"),
            [{"name": "real"}])
        self.assertEqual(
            parsing._find_tag_attrs('<style>/* <meta name=hidden> */</style>'
                                    "<meta name=real>", "meta"),
            [{"name": "real"}])

    def test_a_narrow_parser_does_not_swallow_a_foreign_integration_point(self):
        # An `<svg><title>` is an HTML integration point whose children a browser really does
        # build, so treating it as RCDATA would hide a network-loading element from
        # `_find_tag_attrs` - and with it from the offline-resource gate that reads it. Pinned
        # here because the vendored start-tag layer sits under that lookup.
        payload = '<svg><title><script href="//evil.example/x.js"></script></title></svg>'
        self.assertEqual(parsing._find_tag_attrs(payload, "script"),
                         [{"href": "//evil.example/x.js"}])
        self.assertEqual(_ids('<svg><title><div id="real"></div></title></svg>'), ["real"])

    def test_a_self_closing_tag_is_still_recognized(self):
        # The scanner decides self-closing itself (a `/` in TAG position immediately before the
        # `>`), so the startendtag path a void/foreign element reaches must not regress.
        self.assertEqual(_ids('<svg><rect id="real"/></svg>'), ["real"])
        self.assertEqual(_ids('<div id="wrap"><img id="void"/></div>'), ["wrap", "void"])
        # A `/` that is part of an UNQUOTED value is value text, not a self-closing slash.
        self.assertEqual(parsing._find_tag_attrs("<meta name=a/>", "meta"), [{"name": "a/"}])

    def test_only_a_slash_immediately_before_the_gt_self_closes(self):
        # HTML5 self-closing-start-tag: a `/` anywhere else in tag position is the
        # unexpected-solidus-in-tag error and is simply skipped, so only the LAST separator
        # before the `>` decides. A "sticky" slash flag would pass every other test here.
        for raw, expected in (("<p/>", True), ("<p //>", True), ("<p a=1 />", True),
                              ("<p a='1'/>", True), ("<p / >", False), ("<p/ >", False),
                              ("<p a=1/>", False), ("<p>", False)):
            with self.subTest(raw=raw):
                scanned = parsing._scan_start_tag(raw, 0)
                self.assertIsNotNone(scanned, raw)
                end, _tag, self_closing = scanned
                self.assertEqual(end, len(raw), raw)
                self.assertEqual(self_closing, expected, raw)

    def test_the_attribute_tokenizer_consumes_the_whole_scanned_extent(self):
        # The extent is scanned character by character and the attributes are then read off the
        # same raw text with `_ATTR_RE`. The two agree only because their separator classes are
        # the same, and nothing but this test would notice if a later edit desynced them: the
        # attribute loop must always land on the `>` (or the self-closing `/>`) the scan chose.
        for raw in ("<p>", "<p/>", "<p //>", "<p / >", "<p a>", "<p a=1>", "<p a=1/>",
                    "<p a= >", "<p a =b>", "<p a = b >", '<p a="1"b=2>', "<p a='1'/>",
                    "<p id==x>", "<p id=a\u00a0b>", '<p a="x>y" b>', "<p =>", '<p ="x">',
                    "<p a=b=c>", "<p\x00x a=1>", '<p a="&notit;">', "<p a=/>", "<p a b c>"):
            with self.subTest(raw=raw):
                scanned = parsing._scan_start_tag(raw, 0)
                self.assertIsNotNone(scanned, raw)
                self.assertEqual(scanned[0], len(raw), raw)
                m = parsing._TAG_NAME_RE.match(raw, 1)
                k = m.end()
                while k < len(raw):
                    am = parsing._ATTR_RE.match(raw, k)
                    if am is None or am.end() == k:
                        break
                    k = am.end()
                self.assertIn(raw[k:].strip(), (">", "/>"),
                              "the attribute tokenizer stopped short of the scanned extent")


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


class TagAttrLookupBoundaryTests(unittest.TestCase):
    """The tag-attribute lookup the resource checks read draws the SAME element boundaries as
    the document parser (CMH-VAL-21).

    It used to be a bare `HTMLParser`, so the two views of one document disagreed about what an
    element even IS - and the disagreement was exploitable, because the self-contained / offline
    resource checks read the lookup while everything else read the parse.
    """

    def setUp(self):
        parsing._tag_attr_index.cache_clear()
        self.addCleanup(parsing._tag_attr_index.cache_clear)

    def test_a_bogus_cdata_comment_does_not_hide_a_live_script_from_the_tag_lookup(self):
        # In HTML content `<![CDATA[` is a BOGUS COMMENT ending at the first `>`, so the
        # external <script> after it is LIVE markup a browser fetches and runs. `html.parser`
        # consumes the whole marked section instead, which made the lookup report NO script
        # while the document parser reported one - and the self-contained / offline checks read
        # the lookup.
        html = ('<main id="commentRoot"></main>'
                '<![CDATA[><script src="//evil.example/x.js"></script>]]>')
        self.assertEqual([d.get("src") for d in parsing._find_tag_attrs(html, "script")],
                         ["//evil.example/x.js"])
        self.assertEqual([s["attrs"].get("src") for s in parsing._parse_document(html).scripts],
                         ["//evil.example/x.js"])

    def test_the_tag_lookup_ignores_an_element_quoted_in_a_raw_text_body(self):
        # The other direction of the same agreement: an `<img>` a reader only SEES inside a
        # raw-text body loads nothing, so it must not be reported as a network resource.
        # `<noscript>` is the one exception, covered by its own test below: its body is real
        # markup a browser parses (and loads) when scripting is disabled.
        for elem in [e for e in RAW_TEXT_ELEMENTS if e != "noscript"]:
            with self.subTest(elem=elem):
                parsing._tag_attr_index.cache_clear()
                html = '<%s><img src="//evil.example/x.png"></%s>' % (elem, elem)
                self.assertEqual(parsing._find_tag_attrs(html, "img"), [])
                self.assertEqual(len(parsing._find_tag_attrs(html, elem)), 1,
                                 "the raw-text element itself is still an element")

    def test_the_tag_lookup_sees_noscript_fallback_markup(self):
        # With scripting DISABLED a browser parses the `<noscript>` body and loads what it
        # names, so the EGRESS checks must fail CLOSED on it. Sharing the boundary layer
        # would otherwise have hidden a live network `<meta refresh>` / `<img>` behind the one
        # raw-text element whose body is markup in a real browsing mode.
        html = ('<noscript><meta http-equiv="refresh" content="0;url=//evil.example/out">'
                '<img src="//evil.example/x.png"></noscript>')
        self.assertEqual([d.get("src")
                          for d in parsing._find_tag_attrs_egress(html, "img")],
                         ["//evil.example/x.png"])
        self.assertEqual([d.get("content")
                          for d in parsing._find_tag_attrs_egress(html, "meta")],
                         ["0;url=//evil.example/out"])

    def test_noscript_fallback_markup_is_opt_in_not_the_default_view(self):
        # The fallback is a SUPERSET for the egress question only. A PRESENCE check ("does this
        # document declare a CSP / carry a Run link?") must still read the browser's view, or a
        # phantom element inside `<noscript>` - which a scripting-enabled browser never creates -
        # would satisfy a requirement no reader of the layer can see.
        html = '<noscript><meta http-equiv="content-security-policy" content="default-src \'none\'"></noscript>'
        self.assertEqual(parsing._find_tag_attrs(html, "meta"), [])
        self.assertEqual(len(parsing._find_tag_attrs_egress(html, "meta")), 1)

    def test_a_noscript_body_that_is_only_text_contributes_no_element(self):
        # The fallback pass parses the body as MARKUP, so prose in a <noscript> must not
        # invent elements (and a nested raw-text body inside it stays opaque).
        html = ('<noscript>enable JavaScript to comment'
                '<script>var u = "<img src=\'quoted.png\'>";</script></noscript>')
        self.assertEqual(parsing._find_tag_attrs_egress(html, "img"), [])

    def test_a_failed_tag_index_is_reported_instead_of_read_as_a_clean_document(self):
        # A partial index would let the self-contained check conclude that the rest of the
        # document loads nothing, so the failure is FLAGGED and the resource checks fail closed
        # on it - the same contract `code_block_spans` already has.
        html = '<img src="//evil.example/x.png">'
        self.assertFalse(parsing._tag_attrs_failed(html))
        with mock.patch.object(parsing, "_TagAttrParser", side_effect=RuntimeError("boom")):
            parsing._tag_attr_index.cache_clear()
            self.assertTrue(parsing._tag_attrs_failed(html))
            self.assertEqual(parsing._find_tag_attrs(html, "img"), [])
        parsing._tag_attr_index.cache_clear()   # do not leave the failed entry cached

    def test_a_failed_noscript_fallback_parse_is_reported_too(self):
        # The fallback body gets its own parse, so its failure must reach the same flag - a
        # silently empty fallback view reads exactly like "this document loads nothing".
        real = parsing._TagAttrParser.parse_document

        def flaky(parser, html):
            if parser._fallback:
                raise RuntimeError("boom")
            return real(parser, html)

        html = '<noscript><img src="//evil.example/x.png"></noscript>'
        with mock.patch.object(parsing._TagAttrParser, "parse_document", flaky):
            parsing._tag_attr_index.cache_clear()
            self.assertTrue(parsing._tag_attrs_failed(html))
        parsing._tag_attr_index.cache_clear()   # do not leave the failed entry cached

    def test_a_nested_noscript_does_not_drop_out_of_the_fallback_view(self):
        # The fallback pass is a SCRIPTING-DISABLED read, where `<noscript>` is transparent, so
        # nesting cannot bury a network resource below a recursion cap.
        html = ("<noscript>" * 5) + '<img src="//evil.example/x.png">' + ("</noscript>" * 5)
        self.assertEqual([d.get("src")
                          for d in parsing._find_tag_attrs_egress(html, "img")],
                         ["//evil.example/x.png"])
        self.assertFalse(parsing._tag_attrs_failed(html))

    def test_a_noscript_closer_quoted_in_the_fallback_markup_is_reported(self):
        # The body's END is decided by the scripting-ENABLED tokenizer (the first `</noscript`),
        # but a scripting-DISABLED browser is in the DATA state there, so this `</noscript` is
        # just attribute text to it and the `<img>` really does load. The two views disagree
        # about where the body stops and the straddling tag reaches the fallback parse
        # truncated, so it lands in neither index - REPORT that rather than call the document
        # clean.
        for quote in ('"', "'"):
            with self.subTest(quote=quote):
                parsing._tag_attr_index.cache_clear()
                html = ('<noscript><img alt=%s</noscript>%s src="//evil.example/x.png">'
                        "</noscript>" % (quote, quote))
                self.assertTrue(parsing._tag_attrs_failed(html))

    def test_the_fallback_view_carries_the_css_a_noscript_body_declares(self):
        # The element index alone could not answer the CSS egress question: a `<style>` element's
        # attributes say nothing about the `@import` / `url(...)` in its BODY, and the document
        # view holds no style element for a `<noscript>` at all (its body is raw TEXT there).
        html = ('<style>.doc { color: #123456; }</style>'
                '<noscript><style>@import url(//evil.example/x.css);</style>'
                '<div style="background:url(//evil.example/x.png)"></div></noscript>')
        self.assertEqual([s["body"] for s in parsing._find_noscript_styles(html)],
                         ["@import url(//evil.example/x.css);"])
        self.assertEqual(parsing._find_noscript_inline_styles(html),
                         [{"tag": "div", "value": "background:url(//evil.example/x.png)"}])

    def test_an_unclosed_noscript_style_still_contributes_its_css(self):
        # A browser runs an unclosed raw-text element to end of document, so this stylesheet is
        # live for a scripting-disabled reader exactly as a closed one would be.
        html = '<noscript><style>@import url(//evil.example/x.css);'
        self.assertEqual([s["body"] for s in parsing._find_noscript_styles(html)],
                         ["@import url(//evil.example/x.css);"])

    def test_a_nested_noscript_style_does_not_drop_out_of_the_fallback_view(self):
        html = ("<noscript>" * 3) + "<style>@import url(//evil.example/x.css);</style>" \
            + ("</noscript>" * 3)
        self.assertEqual([s["body"] for s in parsing._find_noscript_styles(html)],
                         ["@import url(//evil.example/x.css);"])
        self.assertFalse(parsing._tag_attrs_failed(html))

    def test_the_scripting_enabled_pass_buffers_no_style_body(self):
        # The fallback view is a COMPLEMENT to `_DocParser.styles`, not a second copy of it: the
        # document's own (multi-megabyte) stylesheet must not be buffered again per cached
        # document, and a caller must not be able to double-count it.
        html = '<style>.doc { background: url(//evil.example/x.png); }</style>'
        self.assertEqual(parsing._find_noscript_styles(html), [])
        self.assertEqual([s["body"] for s in parsing._parse_document(html).styles],
                         [".doc { background: url(//evil.example/x.png); }"])

    def test_a_noscript_closer_inside_fallback_raw_text_is_reported(self):
        # The body's END is decided by the scripting-ENABLED tokenizer (the first `</noscript`),
        # but inside a `<style>`/`<script>` body a scripting-DISABLED browser is still in RAW
        # TEXT, so that closer is just CSS to it and the stylesheet runs on past it. The two
        # views then disagree about where the body stops: everything after the seam is CSS to
        # that browser and ordinary markup to this pass, so the network `url(...)` lands in
        # NEITHER view. It cannot be resolved from the buffered text, so it is REPORTED.
        for seam in ("/* </noscript> */", 'a::after{content:"</noscript>"}',
                     "/* </noscript data-x> */", "/* </noscript > */", "/* </noscript/ */",
                     'a::after{content:"</NOSCRIPT>"}'):
            with self.subTest(seam=seam):
                parsing._tag_attr_index.cache_clear()
                html = ("<noscript><style>%s body{background:url(//evil.example/x.png)}"
                        "</style></noscript>" % seam)
                self.assertTrue(parsing._tag_attrs_failed(html))

    def test_a_fallback_style_left_open_at_end_of_document_is_not_reported(self):
        # The mirror image: when the `<noscript>` itself runs to end of document there is no
        # seam to disagree about - the unclosed `<style>` is unclosed for BOTH views, and its
        # body is exactly what a scripting-disabled browser reads, so it is collected, not
        # reported as unreadable.
        html = '<noscript><style>@import url(//evil.example/x.css);'
        self.assertFalse(parsing._tag_attrs_failed(html))
        self.assertEqual([s["body"] for s in parsing._find_noscript_styles(html)],
                         ["@import url(//evil.example/x.css);"])

    def test_two_fallback_styles_are_two_separate_bodies(self):
        # The buffer must not leak from one `<style>` into the next: concatenated bodies would
        # read a `url(...)` out of a block that never declared one (and, worse, could let a
        # closing brace from the first block swallow the second).
        html = ('<noscript><style>a{color:#123456}</style><p>x</p>'
                "<style>@import url(//evil.example/x.css);</style></noscript>")
        self.assertEqual([s["body"] for s in parsing._find_noscript_styles(html)],
                         ["a{color:#123456}", "@import url(//evil.example/x.css);"])

    def test_the_shared_tag_index_cannot_be_mutated_by_a_caller(self):
        # The index is LRU-cached and shared by every check in a run, so a caller that could
        # write into it would corrupt what a later check reads.
        html = '<noscript><style>@import url(//evil.example/x.css);</style></noscript>'
        entry = parsing._tag_attr_index(html).noscript_styles[0]
        with self.assertRaises(TypeError):
            entry["body"] = "mutated"
        with self.assertRaises(TypeError):
            entry["attrs"]["id"] = "mutated"

    def test_a_non_data_seam_state_is_reported_whatever_holds_it(self):
        # The seam is resolvable only when the fallback parse ended in the DATA state. In any
        # other state the two tokenizers disagree about the REST OF THE DOCUMENT: the
        # scripting-disabled reader leaves its raw text (or its comment) at a closer written
        # AFTER the seam and is back in live markup, exactly where the scripting-enabled view
        # has only a comment - so the resource is in neither index. Each of these really does
        # load for a scripting-disabled reader.
        for html in (
                '<noscript><title></noscript><!-- </title><img src="//evil.example/x.png"> -->'
                "</noscript>",
                '<noscript><textarea></noscript><!-- </textarea>'
                '<img src="//evil.example/x.png"> --></noscript>',
                "<noscript><script>//</noscript><!-- </script>"
                "<style>@import url(//evil.example/x.css);</style> --></noscript>",
                '<noscript><!-- </noscript><textarea> --><img src="//evil.example/x.png">'
                "</textarea></noscript>",
                "<noscript><!-- </noscript><textarea> -->"
                "<style>@import url(//evil.example/x.css);</style></textarea></noscript>"):
            with self.subTest(html=html):
                parsing._tag_attr_index.cache_clear()
                self.assertTrue(parsing._tag_attrs_failed(html))

    def test_the_fallback_parse_records_its_end_state_before_the_base_clears_it(self):
        # The seam guard reads `cdata_elem` at the TOP of `close()`, because the base clears the
        # mode on its way out. Pinned directly, not only through the end-to-end symptom: an edit
        # that moved the snapshot after `super().close()` would silently fail OPEN and bring the
        # whole bypass back with every end-to-end test still green.
        p = parsing._TagAttrParser("", _fallback=True)
        p.parse_document("<style>/* </noscript")
        self.assertEqual(p.eof_raw_text_elem, "style")
        q = parsing._TagAttrParser("", _fallback=True)
        q.parse_document("<!-- </noscript")
        self.assertIsNone(q.eof_raw_text_elem)
        self.assertTrue(q.eof_unterminated)
        r = parsing._TagAttrParser("", _fallback=True)
        r.parse_document("<p>plain</p>")
        self.assertIsNone(r.eof_raw_text_elem)
        self.assertFalse(r.eof_unterminated)

    def test_a_fallback_body_that_ends_in_the_data_state_is_not_reported(self):
        # The control: an ordinary fallback leaves the parse in the DATA state at the seam, so
        # both views agree about the rest of the document and nothing is reported.
        html = ('<noscript><style>a{color:#123456}</style><p>enable scripting</p></noscript>'
                '<img src="local.png">')
        self.assertFalse(parsing._tag_attrs_failed(html))
        self.assertEqual([d.get("src") for d in parsing._find_tag_attrs(html, "img")],
                         ["local.png"])

    def test_the_tag_lookup_ends_a_raw_text_region_at_an_attributed_closer(self):
        html = ('<script>var u = "<img src=\'quoted.png\'>";</script data-x>'
                '<img src="real.png"><script>var a = 1;</script>')
        self.assertEqual([d.get("src") for d in parsing._find_tag_attrs(html, "img")],
                         ["real.png"])

    def test_an_unterminated_comment_hides_the_rest_of_the_document_from_the_tag_lookup(self):
        html = '<img src="a.png"><!-- oops <img src="b.png">'
        self.assertEqual([d.get("src") for d in parsing._find_tag_attrs(html, "img")],
                         ["a.png"])

    def test_a_cdata_section_inside_foreign_content_is_still_a_section(self):
        html = '<svg><![CDATA[<image href="//evil.example/x.png">]]></svg>'
        self.assertEqual(parsing._find_tag_attrs(html, "image"), [])


if __name__ == "__main__":
    unittest.main()
