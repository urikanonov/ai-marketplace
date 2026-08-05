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
import ast
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
import section_hash  # noqa: E402
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
                    section_hash._SectionParser,
                    fix_skip._MermaidPreLocator, deck_validate._ActiveContentScanner,
                    deck_validate._AuthoredContentScanner, contrast._StyleScanner,
                    contrast._DocumentScanner):
            self.assertTrue(issubclass(cls, base), cls.__name__)

    def test_section_hash_does_not_build_an_unused_line_offset_index(self):
        html = '<main id="commentRoot">\n<p>one</p>\n<p>two</p></main>'
        parser = section_hash._SectionParser(html=html)
        parser.parse_document(html)
        self.assertEqual(parser._starts, [0])

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

    def test_the_degraded_base_can_find_an_open_end_tag_target(self):
        probe = _browser_boundaries._FallbackBoundaries("")
        probe._push_ns("div", "html", {})
        probe._push_ns("span", "html", {})
        self.assertEqual(probe._innermost_open("div"), 0)
        self.assertEqual(probe._innermost_open("span"), 1)
        self.assertEqual(probe._innermost_open("p"), -1)


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


class _HookOnlyBase(object):
    """The body of a parser that implements ONLY the collect hooks - no tag handler of its own.

    Deliberately the smallest thing a new subclass could be: it says what it wants to COLLECT and
    where its own stack lives, and nothing about raw text, void elements, foreign self-closing or
    the implicit `</p>` / `</li>` close. Everything it does NOT say is what the shared skeleton
    supplies, so these tests fail the moment the sequence stops being shared. Mixed onto the
    SHIPPED base below and onto the degraded one, so both are held to the same hooks.
    """

    def __init__(self, html=""):
        super().__init__(html)
        self.stack = []
        self.seen = []        # (tag, ns, opens) per start tag reaching `_visit_start`
        self.closed = []      # (tag, index) per end tag reaching `_visit_end`
        self.own_close = []   # tags whose truncation the base flagged as their OWN end tag
        self.voided = []      # (tag, info) per element the skeleton never pushed
        self.pushed = []      # (tag, info) per element it did
        self.after = []       # (tag, opens, the raw-text element open once the start tag is done)
        self.text = []

    def _truncate_stacks(self, depth):
        if self._end_tag_close:
            self.own_close.append(depth)
        super()._truncate_stacks(depth)
        del self.stack[depth:]

    def _visit_start(self, tag, ad, ns, opens):
        self.seen.append((tag, ns, opens))
        return "info:" + tag        # routed back to `_push_element` / `_visit_void`

    def _push_element(self, tag, ad, ns, info):
        self.pushed.append((tag, info))
        self.stack.append(tag)

    def _visit_void(self, tag, ad, ns, info):
        self.voided.append((tag, info))

    def _after_start(self, tag, ad, ns, opens):
        self.after.append((tag, opens, self.cdata_elem))

    def _visit_end(self, tag, index):
        self.closed.append((tag, index))

    def handle_data(self, data):
        self.text.append(data)


class _HookOnlyParser(_HookOnlyBase, _browser_boundaries.BrowserBoundaries):
    pass


def _hook_only(html, cls=_HookOnlyParser):
    parser = cls(html)
    parser.parse_document(html)
    return parser


class HookOnlySubclassTests(unittest.TestCase):
    """CMH-VAL-21: the start / start-end / end sequence lives in ONE place, so a subclass that
    writes only its hooks gets every boundary of it for free.

    Each case pins a step the eleven hand-written copies of the skeleton each had to remember:
    forgetting `_enter_raw_text()` parsed a `<script>` body as markup (the base deliberately
    disables the host's own `_enter_cdata_mode()`), mis-ordering `_implicit_close()` keyed the
    subclass's own bookkeeping on a stack a browser had already popped, and the void / foreign
    self-closing carve-outs decide what is left OPEN at all.
    """

    def test_the_hook_only_parser_really_writes_no_tag_handler(self):
        # The framing assertion: without it every case below could be passing on a handler the
        # subclass wrote for itself, which is exactly what this refactor removed.
        for name in ("handle_starttag", "handle_startendtag", "handle_endtag"):
            self.assertNotIn(name, _HookOnlyBase.__dict__)
            self.assertNotIn(name, _HookOnlyParser.__dict__)

    def test_raw_text_is_text_for_free(self):
        # `<noscript>` is raw text to a scripting-ENABLED browser and ordinary markup to
        # html.parser on every version, so a subclass that forgot `_enter_raw_text()` would
        # collect the `<img>` as an element.
        parser = _hook_only("<noscript><img src=x></noscript><p>after")
        self.assertNotIn("img", [tag for tag, _ns, _opens in parser.seen])
        self.assertIn("<img src=x>", "".join(parser.text))
        self.assertEqual(parser.stack, ["p"])

    def test_a_script_body_is_never_parsed_as_markup(self):
        parser = _hook_only("<script><b id=x></script>")
        self.assertNotIn("b", [tag for tag, _ns, _opens in parser.seen])

    def test_a_void_element_is_never_left_open(self):
        parser = _hook_only("<img src=x><p>a")
        self.assertEqual(parser.seen[0], ("img", "html", False))
        self.assertEqual(parser.stack, ["p"])

    def test_a_self_closed_foreign_element_is_opened_and_closed_at_once(self):
        parser = _hook_only("<svg><rect/></svg><p>a")
        self.assertIn(("rect", "svg", False), parser.seen)
        self.assertEqual(parser.stack, ["p"])

    def test_a_bare_self_closed_svg_leaves_nothing_open(self):
        parser = _hook_only("<svg/><p>a")
        self.assertEqual(parser.stack, ["p"])

    def test_a_self_closed_html_element_still_opens(self):
        # HTML5 IGNORES the trailing slash on a non-void HTML tag, so `<pre/>` still needs `</pre>`.
        parser = _hook_only("<pre/>")
        self.assertEqual(parser.stack, ["pre"])

    def test_the_implicit_paragraph_close_applies_for_free(self):
        parser = _hook_only("<p>a<div>b")
        self.assertEqual(parser.stack, ["div"])

    def test_the_implicit_list_item_close_applies_for_free(self):
        parser = _hook_only("<ul><li>a<li>b")
        self.assertEqual(parser.stack, ["ul", "li"])

    def test_a_visit_start_hook_sees_the_stack_a_browser_has(self):
        # The implicit close runs BEFORE the hook, so a subclass keying state on the stack depth
        # keys it on the depth a browser is at - the ordering half of the invariant.
        parser = _HookOnlyParser("<p>a<div>b")
        depths = []
        parser._visit_start = lambda tag, ad, ns, opens: depths.append((tag, len(parser.stack)))
        parser.parse_document("<p>a<div>b")
        self.assertEqual(depths, [("p", 0), ("div", 0)])

    def test_an_end_tag_reports_the_element_it_closes(self):
        parser = _hook_only("<div><span></span></div></em>")
        self.assertEqual(parser.closed, [("span", 1), ("div", 0), ("em", -1)])
        self.assertEqual(parser.stack, [])

    def test_only_an_end_tags_truncation_is_flagged_as_its_own(self):
        # `_end_tag_close` is the base-owned answer two rewriting tools key their span on: only a
        # close the element's OWN end tag caused may carry that closer's source extent.
        own = _hook_only("<div><span></span></div>")
        self.assertEqual(own.own_close, [1, 0])
        implicit = _hook_only("<p>a<div>b")
        self.assertEqual(implicit.own_close, [])   # the implicit `</p>` close is not an end tag

    def test_the_start_hooks_payload_reaches_the_push_and_void_hooks(self):
        parser = _hook_only("<div><img src=x>")
        self.assertEqual(parser.pushed, [("div", "info:div")])
        self.assertEqual(parser.voided, [("img", "info:img")])

    def test_the_after_start_hook_sees_the_raw_text_the_element_opened(self):
        parser = _hook_only("<title>x</title><p>a")
        self.assertIn(("title", True, "title"), parser.after)
        self.assertIn(("p", True, None), parser.after)

    def test_a_closer_scoped_away_by_a_template_matches_nothing(self):
        parser = _hook_only("<div><template></div>")
        self.assertEqual(parser.closed, [("div", -1)])
        self.assertEqual(parser.stack, ["div", "template"])

    def test_the_degraded_base_drives_the_same_hooks(self):
        # A broken/partial install must still give a hook-only subclass a working parser: what
        # degrades is the host's raw-text set, never WHICH steps run.
        degraded = type("BrowserBoundaries",
                        (_browser_boundaries._RefreshedLineStarts,
                         _browser_boundaries._FallbackBoundaries), {})
        cls = type("_DegradedHookOnly", (_HookOnlyBase, degraded), {})
        parser = _hook_only("<img src=x><p>a<div>b</div>", cls)
        self.assertEqual(parser.seen[0], ("img", "html", False))
        self.assertEqual([tag for tag, _index in parser.closed], ["div"])
        self.assertEqual(parser.stack, ["p"])


class SelfClosedForeignCollectionTests(unittest.TestCase):
    """The shared skeleton reports a self-closed FOREIGN element as a start tag that opens
    nothing, so a hook-only subclass still SEES `<svg><rect id="x"/>`. A tool whose start hook is
    not namespace-gated must opt out of that default, and `doc_stats` is the one that must: it
    measures the reading content a browser lays out, and a `<svg id="commentRoot"/>` - closed at
    once, with no body a reader can see - would otherwise become the root it counts and rewrites.
    (A `<h2/>` inside an `<svg>` is not a case: HTML5 makes h1-h6 BREAK OUT of foreign content, so
    it is an ordinary HTML start tag both before and after this change.)"""

    def test_a_foreign_self_closed_root_is_not_the_content_root(self):
        html = '<svg id="commentRoot"/><h2>outside</h2>'
        parser = doc_stats._StatsParser(html)
        parser.parse_document(html)
        self.assertIsNone(parser.root_depth)
        self.assertEqual(parser.word_count(), 0)

    def test_a_foreign_self_closed_element_is_still_seen_by_default(self):
        # The other side of the same rule: the locators and scanners that DO want every element
        # get one from the shared default, with no hook of their own.
        parser = _hook_only('<svg><rect id="x"/></svg>')
        self.assertIn(("rect", "svg", False), parser.seen)
        self.assertEqual(parser.voided[-1][0], "rect")
        self.assertEqual(parser.stack, [])


def _class_defs_in(source, path):
    """Every class defined in one module: `(name, resolved base short names)` pairs.

    Import and assignment ALIASES are resolved, so `from .parsing import _BrowserBoundaries as BB`
    followed by `class X(BB)` still names `_BrowserBoundaries` as the base - otherwise the guard
    below would be one `as` away from being silently switched off. Resolution is deliberately
    CONSERVATIVE rather than flow-sensitive: a name that is bound more than once (rebound later in
    the file, shadowed inside a function, annotated) keeps EVERY target, so any binding that could
    reach a boundary base makes the class inspectable. Over-reporting a base only costs an extra
    class read; under-reporting one is a hole."""
    tree = ast.parse(source, filename=path)
    alias = {}

    def _bind(name, value):
        if isinstance(value, ast.Attribute):
            alias.setdefault(name, set()).add(value.attr)
        elif isinstance(value, ast.Name):
            alias.setdefault(name, set()).add(value.id)

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for name in node.names:
                if name.asname:
                    alias.setdefault(name.asname, set()).add(name.name.rsplit(".", 1)[-1])
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    _bind(target.id, node.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.value is not None:
                _bind(node.target.id, node.value)

    def _resolve(name):
        out, pending = set(), [name]
        while pending:
            current = pending.pop()
            if current in out:
                continue
            out.add(current)
            pending.extend(alias.get(current, ()))
        return out

    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        names = set()
        for base in node.bases:
            if isinstance(base, ast.Attribute):
                names |= _resolve(base.attr)      # `_browser_boundaries.BrowserBoundaries`
            elif isinstance(base, ast.Name):
                names |= _resolve(base.id)
        out.append((node.name, names))
    return out


def _tool_class_bases():
    """Every class defined in the shipped tools, mapped to the SHORT names of its bases.

    Read with `ast` rather than by importing, so a tool module added later is covered whether or
    not any test imports it, and a class is seen even when its module needs an install-shaped
    sys.path to load. A name defined in more than one module keeps EVERY definition, so a second
    class of the same name cannot hide behind the first."""
    bases = {}
    where = {}
    for root, dirs, files in os.walk(_paths.TOOLS):
        dirs[:] = [d for d in dirs if not d.startswith((".", "__pycache__"))]
        for name in sorted(files):
            if not name.endswith(".py"):
                continue
            path = os.path.join(root, name)
            with open(path, encoding="utf-8") as fh:
                source = fh.read()
            for cls, parents in _class_defs_in(source, path):
                bases[cls] = bases.get(cls, set()) | parents
                where.setdefault(cls, []).append(os.path.relpath(path, _paths.TOOLS))
    return bases, where


# The two names the shared skeleton itself lives under: `checks/parsing._BrowserBoundaries` and the
# `tools/_browser_boundaries.BrowserBoundaries` shim every tool outside that package derives from.
_SKELETON_ROOTS = frozenset(("_BrowserBoundaries", "BrowserBoundaries"))
# No subclass may write its own tag handlers; every pass now drives the shared hook sequence.
_HANDLER_ALLOWLIST = {}
_TAG_HANDLERS = ("handle_starttag", "handle_startendtag", "handle_endtag")


class SharedHandlerSkeletonTests(unittest.TestCase):
    """CMH-VAL-21: no subclass may re-copy the boundary sequence.

    The hooks above make the right thing easy; this makes the wrong thing FAIL. Eleven independent
    copies of the same ~25-line skeleton is what the hoist removed, and nothing but this guard
    stops the twelfth from being written - a copy that forgot one step would parse a document
    differently from every other view of it and no other gate would see it.
    """

    def _boundary_subclasses(self):
        bases, where = _tool_class_bases()
        found = set(_SKELETON_ROOTS)
        changed = True
        while changed:
            changed = False
            for name, parents in bases.items():
                if name not in found and parents & found:
                    found.add(name)
                    changed = True
        return sorted(found - _SKELETON_ROOTS), where

    def test_every_boundary_subclass_drives_the_shared_skeleton(self):
        subclasses, where = self._boundary_subclasses()
        offenders = []
        for name in subclasses:
            if name in _HANDLER_ALLOWLIST:
                continue
            for rel in where[name]:
                src = os.path.join(_paths.TOOLS, rel)
                with open(src, encoding="utf-8") as fh:
                    tree = ast.parse(fh.read(), filename=src)
                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef) and node.name == name:
                        for item in node.body:
                            if (isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                                    and item.name in _TAG_HANDLERS):
                                offenders.append("%s.%s (%s)" % (name, item.name, rel))
        self.assertEqual(offenders, [], "these re-copy the shared handler skeleton: %s" % offenders)

    def test_an_aliased_base_does_not_escape_the_guard(self):
        # One `as` away from switching the guard off: the base name a class is written against is
        # resolved through import and assignment aliases, so a subclass cannot hide behind either.
        source = ("from checks.parsing import _BrowserBoundaries as _BB\n"
                  "import _browser_boundaries as _bb\n"
                  "_Shim = _bb.BrowserBoundaries\n"
                  "class Aliased(_BB):\n    pass\n"
                  "class ViaAssignment(_Shim):\n    pass\n")
        defined = dict(_class_defs_in(source, "<synthetic>"))
        self.assertIn("_BrowserBoundaries", defined["Aliased"])
        self.assertIn("BrowserBoundaries", defined["ViaAssignment"])

    def test_a_rebound_or_annotated_alias_does_not_escape_the_guard(self):
        # Resolution is conservative rather than flow-sensitive: a name bound more than once keeps
        # EVERY target, so rebinding it after the class, shadowing it inside a function, or
        # annotating it cannot hide the base that was really used.
        source = ("from checks.parsing import _BrowserBoundaries as _BB\n"
                  "class Rebound(_BB):\n    pass\n"
                  "_BB = object\n"
                  "_Annotated: type = _BB\n"
                  "class ViaAnnotated(_Annotated):\n    pass\n"
                  "def unrelated():\n"
                  "    _BB = object\n"
                  "    return _BB\n")
        defined = dict(_class_defs_in(source, "<synthetic>"))
        self.assertIn("_BrowserBoundaries", defined["Rebound"])
        self.assertIn("_BrowserBoundaries", defined["ViaAnnotated"])

    def test_the_guard_sees_every_boundary_subclass(self):
        # A guard that discovered nothing would pass vacuously, and the fixpoint has to reach the
        # indirect subclasses (a `_DocumentScanner` derives from `_StyleScanner`, not the base).
        subclasses, _where = self._boundary_subclasses()
        for name in ("_DocParser", "_CodeSpanParser", "_RawTextSpanParser", "_TagAttrParser",
                     "_DensityParser", "_TopLevelLocator", "_ContentRootLocator", "_TocParser",
                     "_StatsParser", "_MermaidPreLocator", "_ActiveContentScanner",
                     "_AuthoredContentScanner", "_StyleScanner", "_DocumentScanner"):
            self.assertIn(name, subclasses)

    def test_the_allowlist_does_not_rot(self):
        subclasses, _where = self._boundary_subclasses()
        for name in _HANDLER_ALLOWLIST:
            self.assertIn(name, subclasses, "%s is allowlisted but no longer exists" % name)


if __name__ == "__main__":
    unittest.main()
