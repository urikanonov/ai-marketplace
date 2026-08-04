"""CMH-VAL-21: the tools OUTSIDE the validator's `checks` package draw the SAME element boundaries.

`tools/_browser_attrs.py` gave them the shared attribute DECODE. These tests pin the other half -
where one element ENDS and the next begins - for every locator and scanner that used to be a plain
`html.parser.HTMLParser`: `wrap_sections`, `generate_toc`, `doc_stats`, `fix_skip`, the deck
validator's two scanners and the contrast scanner's style/document scanners.

Every case pins a boundary the HOST gets wrong, so the module cannot pass vacuously:

  - the RAW-TEXT set, for the AUTHORING tools and the contrast scan. A browser holds the whole set
    as TEXT; `html.parser` grew `xmp`, `iframe`, `noembed` and `noframes` in 3.13 and reads
    `title`/`textarea` as RCDATA there, and it treats `<noscript>` as ordinary markup on every
    version (its own `scripting` flag defaults to off). So a `<main id="commentRoot">`, a
    `<pre class="mermaid">`, a heading or a `style=` an author only QUOTED inside a `<noscript>` was
    a real element to the tool beside the validator - an element a SCRIPTING-ENABLED reader (which
    is the only kind a commentable-html document has, since the layer needs JS) never sees, and one
    an authoring tool would anchor its edit to.
  - the MARKED-SECTION rule, which every host version gets wrong on both 3.12 and 3.13.
    `html.parser` consumes a whole `<![CDATA[ ... ]]>` in every context, where a browser outside
    foreign content treats `<![CDATA[` as a bogus comment ending at the first `>` and the markup
    after it is LIVE. That direction fails OPEN, which is why it is what the deck's egress scan is
    pinned on: the host hid a remote `<img>` the deck really does load.
  - ASCII-only tag-name folding (clause 7), which no host applies.

`DeckNoscriptFallbackTests` is a different kind of pin: the deck's egress scan reads the body TWICE
(as a scripting-ENABLED browser, in which a `<noscript>` body is raw text, and as a scripting-
DISABLED one, in which it is live markup that really is fetched) and unions the findings. Those
cases are regression pins for the SEAM between the two readings - re-parsing only the body the
enabled tokenizer carved out lost a tag straddling its end, which is how a remote resource landed
in neither view.
"""

import os
import sys
import types
import unittest
import importlib.util
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402  shared pkg/dev split path constants + tools bootstrap

sys.path.insert(0, _paths.TOOLS)

import _browser_boundaries  # noqa: E402
import deck_validate  # noqa: E402
import doc_stats  # noqa: E402
import fix_skip  # noqa: E402
import generate_toc  # noqa: E402
import wrap_sections  # noqa: E402
from cmhval import contrast  # noqa: E402


def _tree_ids(node):
    """Every `id` in the WHOLE document tree, not just the root's direct children - an element the
    host merely NESTED (rather than dropped) would otherwise slip past a shallow assertion."""
    found = []
    for child in node.children:
        if child.attrs.get("id"):
            found.append(child.attrs["id"])
        found.extend(_tree_ids(child))
    return found


class SharedBoundariesShimTests(unittest.TestCase):
    """The shim itself: it must resolve the SHIPPED base, and its degraded path must still give a
    tool a working parser rather than crashing it on a broken install."""

    def test_the_shim_resolves_the_shipped_boundaries(self):
        self.assertTrue(_browser_boundaries.IS_SHARED)
        self.assertIsNot(_browser_boundaries.BrowserBoundaries,
                         _browser_boundaries._FallbackBoundaries)

    def test_every_tool_derives_from_the_shared_base(self):
        base = _browser_boundaries.BrowserBoundaries
        for cls in (wrap_sections._TopLevelLocator, wrap_sections._ContentRootLocator,
                    generate_toc._TocParser, doc_stats._StatsParser,
                    fix_skip._MermaidPreLocator, deck_validate._ActiveContentScanner,
                    deck_validate._AuthoredContentScanner, contrast._StyleScanner,
                    contrast._DocumentScanner):
            self.assertTrue(issubclass(cls, base), cls.__name__)

    def test_the_degraded_base_still_parses(self):
        # Only a broken/partial install gets here (the warning is emitted at import). It must keep
        # the tool WORKING with the host's own boundaries - the pre-CMH-VAL-21 behavior - rather
        # than raising on a missing method.
        seen = []

        class _Probe(_browser_boundaries._FallbackBoundaries):
            def handle_starttag(self, tag, attrs):
                tag = self._browser_tag(tag)
                ad = self._attrs_dict(tag, attrs)
                ns = self._child_namespace(tag, ad)
                self._implicit_close(tag)
                self._push_ns(tag, ns, ad)
                self._enter_raw_text(tag, ns)
                seen.append((tag, ad.get("id"), self._off(), self._start_tag_end()))

        html = '<DIV ID="a">x</div>'
        probe = _Probe(html)
        probe.parse_document(html)
        self.assertEqual(seen, [("div", "a", 0, len('<DIV ID="a">'))])
        self.assertFalse(probe._foreign_self_closes("html"))


class WrapSectionsBoundaryTests(unittest.TestCase):
    """`wrap_sections` decides WHERE to insert a `<section>` from element positions, so a boundary
    it gets wrong edits the document at an offset a browser's DOM does not have."""

    def test_a_section_hidden_by_a_bogus_marked_section_still_blocks_nothing(self):
        # `<![CDATA[` in HTML content is a BOGUS COMMENT ending at the first `>`, so the `<h2>`
        # after it is a real top-level heading a browser renders and this tool must wrap. The host
        # swallows the whole marked section instead, so the tool saw no heading and did nothing.
        html = '<![CDATA[><h2 id="real">Real</h2>\n<p>body</p>]]>'
        wrapped, count = wrap_sections.wrap_fragment(html)
        self.assertEqual(count, 1, wrapped)
        self.assertIn('<section aria-labelledby="real">', wrapped)

    def test_the_content_root_is_not_one_quoted_in_a_raw_text_body(self):
        # The FIRST real `#commentRoot` is the content root. A quoted one is not an element at
        # all, so scoping to it wrapped the wrong bytes.
        html = ('<noscript><main id="commentRoot"><p>fallback</p></main></noscript>'
                '<main id="commentRoot"><p>real</p></main>')
        span = wrap_sections._locate_content_region(html)
        self.assertIsNotNone(span)
        start, end = span
        self.assertEqual(html[start:end], "<p>real</p>")


class GenerateTocBoundaryTests(unittest.TestCase):
    """`generate_toc` anchors a link at every heading it finds, so a heading a browser never
    creates becomes a table-of-contents entry that goes nowhere."""

    def test_a_heading_quoted_in_a_raw_text_body_is_not_a_heading(self):
        parser = generate_toc._parse(
            '<main id="commentRoot">'
            '<noscript><h2 id="ghost">Ghost</h2></noscript>'
            '<h2 id="real">Real</h2></main>')
        self.assertEqual([h["id"] for h in parser.headings], ["real"])
        self.assertEqual(parser.all_ids, ["commentRoot", "real"])

    def test_a_closer_inside_a_template_does_not_end_a_heading_outside_it(self):
        # The shared template floor reaches the tools too: `template` scopes an END TAG, so the
        # `</h2>` parked in one cannot close the author's heading. Without it the TOC entry read
        # "Real" where a browser (which renders none of the template) shows "RealTail".
        parser = generate_toc._parse(
            '<main id="commentRoot"><h2 id="a">Real<template></h2></template>'
            "Tail</h2></main>")
        self.assertEqual([(h["id"], h["text"]) for h in parser.headings], [("a", "RealTail")])


class DocStatsBoundaryTests(unittest.TestCase):
    """`doc_stats` publishes the section count a reader sees, so a heading held as text must not
    inflate it."""

    def test_a_heading_quoted_in_a_raw_text_body_is_not_counted(self):
        html = ('<main id="commentRoot"><h1>T</h1>'
                '<noscript><h2>Ghost</h2></noscript>'
                '<h2>Real</h2></main>')
        self.assertEqual(doc_stats.count_sections(html), 1)


class FixSkipBoundaryTests(unittest.TestCase):
    """`fix_skip` REWRITES the bytes of every `<pre class="mermaid">` it finds, so a boundary it
    gets wrong edits text a browser renders verbatim."""

    def test_a_mermaid_block_quoted_in_a_raw_text_body_is_not_edited(self):
        html = ('<noscript><pre class="mermaid">graph TD;</pre></noscript>'
                '<pre class="mermaid">graph TD;</pre>')
        fixed, count = fix_skip.fix(html)
        self.assertEqual(count, 1, fixed)
        self.assertIn('<noscript><pre class="mermaid">graph TD;</pre></noscript>', fixed)
        self.assertIn('<pre class="mermaid cm-skip">graph TD;</pre>', fixed)


class DeckValidateBoundaryTests(unittest.TestCase):
    """The deck validator's two scanners, pinned on the marked-section rule - the boundary whose
    host behavior fails OPEN, so the deck body really did load a resource the scan never saw."""

    def test_a_remote_resource_behind_a_bogus_marked_section_is_still_egress(self):
        errors = deck_validate._active_content_errors(
            '<![CDATA[><img src="//cdn.example/logo.png">]]>')
        self.assertTrue(any("remote media" in e for e in errors), errors)

    def test_authored_elements_behind_a_bogus_marked_section_are_counted(self):
        scanner = deck_validate._AuthoredContentScanner(80)
        body = ('<section class="slide" data-slide-id="s1">'
                '<![CDATA[><p>a</p><p>b</p>]]></section>')
        scanner.parse_document(body)
        slides = [r for r in scanner.regions if r.kind == "slide"]
        self.assertEqual([r.label for r in slides], ["s1"])
        self.assertEqual(slides[0].elements, 2)


class ContrastScannerBoundaryTests(unittest.TestCase):
    """The contrast scanner reports the colours a reader sees, so an element held as text has no
    colours to report."""

    def test_an_inline_style_quoted_in_a_raw_text_body_is_not_a_declaration(self):
        scanner = contrast._StyleScanner()
        scanner.parse_document('<noscript><p style="color:#eee">fallback</p></noscript>'
                               '<p style="color:#111">real</p>')
        self.assertEqual([value for _tag, _attrs, value in scanner.inline_styles],
                         ["color:#111"])

    def test_an_element_quoted_in_a_raw_text_body_is_not_in_the_document_tree(self):
        scanner = contrast._DocumentScanner()
        scanner.parse_document('<noscript><p id="ghost">fallback</p></noscript>'
                               '<p id="real">real</p>')
        self.assertEqual(_tree_ids(scanner.root), ["real"])

    def test_the_tree_keeps_siblings_apart_across_an_implicit_close(self):
        # HTML5 closes an open `<p>` for a block-level start tag, so these are SIBLINGS. If the
        # node stack drifted out of step with the element stack the `<div>` would be nested inside
        # the `<p>`, and every ancestor-derived colour would be resolved against the wrong parent.
        scanner = contrast._DocumentScanner()
        scanner.parse_document('<p id="a">x<div id="b">y</div>')
        self.assertEqual([node.attrs.get("id") for node in scanner.root.children], ["a", "b"])

    def test_a_closer_inside_a_template_does_not_pop_an_ancestor_node(self):
        # The same floor, seen from the node tree: the `</p>` parked in the template cannot close
        # the `<p>`, so the element after the template is still that paragraph's CHILD and its
        # inherited colours resolve against the right parent.
        scanner = contrast._DocumentScanner()
        scanner.parse_document('<p id="a"><template></p></template><span id="b">y</span></p>')
        self.assertEqual([node.attrs.get("id") for node in scanner.root.children], ["a"])
        self.assertIn("b", _tree_ids(scanner.root))

    def test_a_foreign_template_is_not_a_scope_boundary(self):
        # Only an HTML-namespace `<template>` scopes an end tag. An SVG element that merely
        # happens to be called `template` is an ordinary foreign element, so the `</svg>` written
        # inside it still closes the svg exactly as a browser closes it.
        scanner = contrast._DocumentScanner()
        scanner.parse_document('<svg><template>x</svg><p id="after">after</p>')
        self.assertIn("after", _tree_ids(scanner.root))


class ToolTagNameFoldTests(unittest.TestCase):
    """Clause 7 of CMH-VAL-21 reaches these tools too, now that they share the base: a tag name
    folds ASCII-case-insensitively ONLY. U+212A KELVIN SIGN is the one character outside ASCII
    whose `str.lower()` is an ASCII letter, so `<lin\u212a>` is not a `<link>` and `<mar\u212a>` is
    not a `<mark>` - and `html.parser` hands every handler the UNICODE fold, so a tool that folded
    the name itself keyed on an element a browser does not have."""

    KELVIN = "\u212a"

    def test_the_deck_scan_does_not_read_a_kelvin_name_as_a_link(self):
        errors = deck_validate._active_content_errors(
            '<lin%s href="//cdn.example/x.css">' % self.KELVIN)
        self.assertEqual(errors, [])
        real = deck_validate._active_content_errors('<link href="//cdn.example/x.css">')
        self.assertTrue(any("remote media" in e for e in real), real)

    def test_the_contrast_document_tree_keeps_the_unfolded_name(self):
        scanner = contrast._DocumentScanner()
        scanner.parse_document("<mar%s>x</mar%s>" % (self.KELVIN, self.KELVIN))
        self.assertEqual([node.tag for node in scanner.root.children], ["mar" + self.KELVIN])

    def test_a_kelvin_name_is_not_the_void_element_it_lowercases_to(self):
        # `<link>` is void, so a heading after one is still a direct child of the scope root;
        # `<lin\u212a>` is an unknown element that stays OPEN, so the heading is ITS child and is
        # not a top-level block to wrap.
        heading = '<h2 id="a">A</h2>\n<p>x</p>'
        self.assertEqual(wrap_sections.wrap_fragment("<lin%s>%s" % (self.KELVIN, heading))[1], 0)
        self.assertEqual(wrap_sections.wrap_fragment("<link>%s" % heading)[1], 1)


class DeckNoscriptFallbackTests(unittest.TestCase):
    """The deck's egress scan reads the body TWICE - as a browser with scripting ON, and as one
    with scripting OFF, in which a `<noscript>` body is live markup that really is fetched. A
    reader is on one side or the other, so the scan reports what EITHER loads."""

    def test_a_remote_resource_inside_a_noscript_body_is_still_egress(self):
        errors = deck_validate._active_content_errors(
            '<noscript><img src="//cdn.example/x.png"></noscript>')
        self.assertTrue(any("remote media" in e for e in errors), errors)

    def test_a_noscript_closer_quoted_in_the_fallback_markup_is_still_egress(self):
        # A scripting-ENABLED tokenizer ends the `<noscript>` body at the first `</noscript`, even
        # one sitting inside a quoted attribute VALUE; a scripting-DISABLED one is in the DATA
        # state there and reads a single `<img>` it then fetches. Re-parsing only the body the
        # enabled view carved out left that tag TRUNCATED, so the resource was in neither view.
        errors = deck_validate._active_content_errors(
            '<noscript><img src="//cdn.example/x.png" alt="</noscript>"></noscript>')
        self.assertTrue(any("remote media" in e for e in errors), errors)

    def test_a_noscript_closer_hidden_in_a_comment_is_still_egress(self):
        # The same seam through a comment: the enabled view ends the body inside `<!--`, and the
        # `<noembed>` that follows then swallows the image as raw text - while a scripting-disabled
        # browser reads one comment and fetches the image after it.
        errors = deck_validate._active_content_errors(
            '<noscript><!-- </noscript><noembed> -->'
            '<img src="//cdn.example/x.png"></noembed>')
        self.assertTrue(any("remote media" in e for e in errors), errors)

    def test_a_nested_noscript_does_not_drop_out_of_the_fallback_view(self):
        # The scripting-disabled reading is TRANSPARENT to `<noscript>` at every depth, so nesting
        # cannot bury a resource below a recursion cap - there is no recursion to cap.
        errors = deck_validate._active_content_errors(
            '<noscript><noscript><img src="//cdn.example/x.png"></noscript></noscript>')
        self.assertTrue(any("remote media" in e for e in errors), errors)

    def test_an_unclosed_noscript_still_contributes_its_fallback_markup(self):
        errors = deck_validate._active_content_errors(
            '<noscript><img src="//cdn.example/x.png">')
        self.assertTrue(any("remote media" in e for e in errors), errors)

    def test_a_resource_is_reported_once_even_though_the_body_is_read_twice(self):
        errors = deck_validate._active_content_errors('<img src="//cdn.example/x.png">')
        self.assertEqual(len([e for e in errors if "remote media" in e]), 1, errors)

    def test_a_noscript_body_that_is_only_text_reports_nothing(self):
        self.assertEqual(
            deck_validate._active_content_errors("<noscript>enable scripting</noscript>"), [])

    def test_a_degraded_install_reports_rather_than_passing_the_body(self):
        # On a broken/partial install the scan falls back to the HOST's boundaries, which consume a
        # whole `<![CDATA[ ... ]]>` in every context and so hide markup a browser leaves live. For
        # an egress question that must REPORT, never pass.
        with mock.patch.object(_browser_boundaries, "IS_SHARED", False):
            errors = deck_validate._active_content_errors("<p>nothing to see</p>")
        self.assertTrue(any("could not check" in e for e in errors), errors)


class ScannerEndOfInputTests(unittest.TestCase):
    """An element still OPEN at end of input is one a browser still renders, so the scanners that
    accumulate over an element's body finish it rather than dropping it."""

    def test_an_unclosed_slide_region_is_still_reported(self):
        scanner = deck_validate._AuthoredContentScanner(80)
        body = '<section class="slide" data-slide-id="s1"><p>a</p><p>b</p>'
        scanner.parse_document(body)
        slides = [r for r in scanner.regions if r.kind == "slide"]
        self.assertEqual([r.label for r in slides], ["s1"])
        self.assertEqual(slides[0].elements, 2)

    def test_an_unclosed_style_block_still_contributes_its_rules(self):
        scanner = contrast._StyleScanner()
        scanner.parse_document("<div><style>:root{--cp-text:#fff;}")
        self.assertEqual(scanner.style_blocks, [":root{--cp-text:#fff;}"])


class RootAwareImplicitCloseTests(unittest.TestCase):
    """A content root a BLOCK-LEVEL start tag implicitly closes really is closed - HTML5's "close
    a p element". A tool that only ends the root at an end TAG kept reading (and, in
    `wrap_sections`, REWRITING) the sibling content a browser puts outside it."""

    HTML = '<p id="commentRoot">root<h2 id="x">Sibling</h2><p>after</p>'

    def test_the_content_region_ends_where_the_root_is_implicitly_closed(self):
        span = wrap_sections._locate_content_region(self.HTML)
        self.assertIsNotNone(span)
        start, end = span
        self.assertEqual(self.HTML[start:end], "root")

    def test_the_toc_does_not_collect_a_heading_outside_the_implicitly_closed_root(self):
        parser = generate_toc._parse(self.HTML)
        self.assertEqual([h["id"] for h in parser.headings], [])

    def test_the_stats_do_not_count_a_section_outside_the_implicitly_closed_root(self):
        self.assertEqual(doc_stats.count_sections(self.HTML), 0)


class SharedBoundariesShimOriginTests(unittest.TestCase):
    """The shim resolves the boundaries THROUGH the attribute shim, so it must confirm that the
    attribute shim is the one shipped beside it - `import _browser_attrs` resolves through
    `sys.modules` FIRST, so a host process that already imported some other `_browser_attrs` would
    otherwise supply the base class with no signal."""

    def test_a_sibling_shim_from_an_unexpected_origin_is_refused(self):
        foreign = types.ModuleType("_browser_attrs")
        foreign.__file__ = os.path.join(HERE, "not-the-skill", "_browser_attrs.py")
        self.assertFalse(_browser_boundaries._is_shipped_sibling(foreign))
        self.assertFalse(_browser_boundaries._is_shipped_sibling(types.ModuleType("x")))

    def test_the_real_sibling_shim_is_accepted(self):
        import _browser_attrs
        self.assertTrue(_browser_boundaries._is_shipped_sibling(_browser_attrs))


class AncestorCloseExtentTests(unittest.TestCase):
    """An element an ANCESTOR's end tag closes ends at the START of that end tag, not after it - a
    browser never gives the ancestor's `</div>` to the child. These tools REPLACE the bytes of the
    spans below, so an extent one end tag too long deletes a structural closer from the document."""

    def test_a_toc_closed_by_an_ancestor_does_not_swallow_the_ancestors_end_tag(self):
        html = ('<div id="commentRoot"><h1>T</h1><nav class="cm-toc"><ul><li>'
                '<a href="#a">A</a></li></ul></div><p>after</p>')
        parser = generate_toc._parse(html)
        # Not a span a rewrite may replace (see NonDestructiveRewriteTests), but its EXTENT is
        # still the browser's: the nav ends at the START of the ancestor's `</div>`.
        self.assertEqual([html[a:b] for a, b in parser.toc_unclosed_spans],
                         ['<nav class="cm-toc"><ul><li><a href="#a">A</a></li></ul>'])
        self.assertEqual(parser.toc_spans, [])

    def test_a_stats_strip_closed_by_an_ancestor_does_not_swallow_its_end_tag(self):
        html = ('<div id="commentRoot"><h1>T</h1><section>'
                '<div data-cmh-doc-stats="1">old</section></div>')
        parser = doc_stats._parse(html)
        self.assertEqual(html[parser.stats_start:parser.stats_end],
                         '<div data-cmh-doc-stats="1">old')
        self.assertFalse(parser.stats_own_close)

    def test_a_title_container_closed_by_an_ancestor_stays_inside_the_root(self):
        # The overview strip is anchored just after the title container, and the module's contract
        # is that it lands INSIDE #commentRoot. Taking the ancestor's `</div>` put it outside.
        html = '<div id="commentRoot"><h1>Title</div><p>tail</p>'
        parser = doc_stats._parse(html)
        self.assertEqual(parser.title_container_end, html.index("</div>"))

    def test_a_stats_strip_left_open_at_end_of_input_still_has_an_end(self):
        # The EXTENT is the browser's: an unclosed strip runs to end of input. But because that
        # extent covers every following sibling, it is marked as NOT closed by its own end tag, and
        # the rewrite must fall back to the non-destructive anchor insert rather than replacing it.
        html = '<div id="commentRoot"><h1>T</h1><div data-cmh-doc-stats="1">old'
        parser = doc_stats._parse(html)
        self.assertEqual(parser.stats_end, len(html))
        self.assertFalse(parser.stats_own_close)


class NonDestructiveRewriteTests(unittest.TestCase):
    """A span the browser did NOT close with the element's own end tag runs past every following
    sibling. These two tools REPLACE the span they find, so editing such a span deletes the
    document's body - the one outcome an authoring tool must never produce."""

    def test_an_unclosed_toc_nav_does_not_delete_the_document_body(self):
        html = ('<html><body><div id="commentRoot">\n<nav class="cm-toc">\n<ol></ol>\n'
                '<h2 id="one">One</h2>\n<p>Real body text.</p>\n'
                '<h2 id="two">Two</h2>\n<p>More body.</p>\n</div></body></html>')
        out = generate_toc.rewrite_html(html)
        self.assertIn("Real body text.", out)
        self.assertIn("More body.", out)

    def test_an_unclosed_stats_strip_does_not_delete_the_document_body(self):
        html = ('<html><body><div id="commentRoot"><h1>T</h1>'
                '<span data-cmh-doc-stats="1">2 sections</span-oops'
                '<h2 id="a">A</h2><p>Body one.</p>'
                '<h2 id="b">B</h2><p>Body two.</p></div></body></html>')
        out = doc_stats.rewrite_html(html)
        self.assertIn("Body one.", out)
        self.assertIn("Body two.", out)

    def test_a_properly_closed_strip_is_still_replaced_in_place(self):
        # The positive control: the replace path is what keeps the tool idempotent, so it must
        # still fire for the ordinary, well-formed shape.
        html = ('<html><body><div id="commentRoot"><h1>T</h1>'
                '<p data-cmh-doc-stats="1">stale</p>'
                '<h2 id="a">A</h2><p>Body.</p></div></body></html>')
        out = doc_stats.rewrite_html(html)
        self.assertNotIn("stale", out)
        self.assertEqual(out.count("data-cmh-doc-stats"), 1)

    def test_an_end_tag_carrying_a_quoted_gt_still_ends_where_a_browser_ends_it(self):
        # A browser ends a tag at the first `>` that is NOT inside a quoted attribute value, and a
        # value only begins after `=` - so `</nav a=">">` ends at the SECOND `>`. Stopping at the
        # first one left the tail (`">`) behind in the document these tools rewrite.
        html = ('<div id="commentRoot"><h1>T</h1><nav class="cm-toc"><ul></ul>'
                '</nav a=">"><p>x</p></div>')
        parser = generate_toc._parse(html)
        self.assertEqual([html[a:b] for a, b in parser.toc_spans],
                         ['<nav class="cm-toc"><ul></ul></nav a=">">'])

    def test_an_elements_own_end_tag_is_part_of_its_span(self):
        # The other branch: when the element's OWN end tag closes it, the span INCLUDES that tag -
        # otherwise a rewrite would leave a stray `</nav>` behind.
        html = '<div id="commentRoot"><h1>T</h1><nav class="cm-toc">x</nav><p>y</p></div>'
        parser = generate_toc._parse(html)
        self.assertEqual([html[a:b] for a, b in parser.toc_spans],
                         ['<nav class="cm-toc">x</nav>'])

    def test_a_stats_strip_ends_where_a_block_tag_implicitly_closes_it(self):
        # An implicit close is not an end tag at all, so the span ends at the START of the block
        # tag that closed it.
        html = ('<div id="commentRoot"><h1>T</h1>'
                '<p data-cmh-doc-stats="1">old<div>after</div>')
        parser = doc_stats._parse(html)
        self.assertEqual(html[parser.stats_start:parser.stats_end],
                         '<p data-cmh-doc-stats="1">old')

    def test_a_heading_and_a_toc_left_open_at_end_of_input_are_finalized(self):
        html = '<div id="commentRoot"><nav class="cm-toc">t</nav><h2 id="a">Open'
        parser = generate_toc._parse(html)
        self.assertEqual([(h["id"], h["text"]) for h in parser.headings], [("a", "Open")])
        html_open_toc = '<div id="commentRoot"><h2 id="a">A</h2><nav class="cm-toc">t'
        open_toc = generate_toc._parse(html_open_toc)
        # End of input closes the nav, so its extent is recorded - as an UNCLOSED span, since
        # replacing one that runs to end of input would delete the rest of the file.
        self.assertEqual([b for _a, b in open_toc.toc_unclosed_spans], [len(html_open_toc)])
        self.assertEqual(open_toc.toc_spans, [])


class ScannerOffsetTests(unittest.TestCase):
    """A scanner built without its source text (the `html=""` convenience the deck and contrast
    scanners keep for callers that only `feed()`) must still report real offsets once it is given a
    document, or an offset-reading caller would index into an empty line table."""

    def test_a_scanner_built_empty_still_reports_real_offsets(self):
        scanner = contrast._DocumentScanner()
        scanner.parse_document("a\nb\n<p id=\"x\">y</p>")
        self.assertEqual(scanner._starts, [0, 2, 4])


class DegradedInstallTests(unittest.TestCase):
    """A broken/partial install leaves every tool on the HOST's boundaries. An authoring tool must
    still RUN (a degraded edit beats a tool that cannot start), while the deck's egress scan must
    REPORT instead of passing - the fail-closed rule applies to the security question."""

    def test_an_authoring_tool_still_runs_on_the_degraded_base(self):
        degraded = _reloaded_on_degraded_base(wrap_sections)
        html = '<h2 id="a">A</h2>\n<p>x</p>'
        wrapped, count = degraded.wrap_fragment(html)
        self.assertEqual(count, 1, wrapped)
        self.assertIn('<section aria-labelledby="a">', wrapped)

    def test_the_deck_egress_scan_reports_on_the_degraded_base(self):
        with mock.patch.object(_browser_boundaries, "IS_SHARED", False):
            errors = deck_validate._active_content_errors(
                '<![CDATA[><img src="//cdn.example/x.png">]]>')
        self.assertTrue(any("could not check" in e for e in errors), errors)


def _reloaded_on_degraded_base(module):
    """A private COPY of `module` imported while the shim exports the DEGRADED base - what a
    broken/partial install (no `validate` tool) would load. Imported under its own name so the
    real module the rest of the suite uses is untouched."""
    degraded = type("BrowserBoundaries",
                    (_browser_boundaries._RefreshedLineStarts,
                     _browser_boundaries._FallbackBoundaries), {})
    with mock.patch.object(_browser_boundaries, "BrowserBoundaries", degraded):
        spec = importlib.util.spec_from_file_location(
            module.__name__ + "_degraded_copy", module.__file__)
        copy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(copy)
    return copy


if __name__ == "__main__":
    unittest.main()
