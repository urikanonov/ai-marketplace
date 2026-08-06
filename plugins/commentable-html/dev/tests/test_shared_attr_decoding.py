"""CMH-VAL-21: the tools OUTSIDE the validator's `checks` package decode attribute values with
the SAME shared browser rule.

`checks/parsing._browser_attrs_dict()` is the one place an attribute value is decoded, applied to
the RAW start tag so the host `html.parser` is never trusted: a browser resolves a NAMED character
reference in an attribute value only on an exact match, so `class="a &nbspcm-skip"` carries the
literal token `&nbspcm-skip`, while Python 3.12 unescapes the whole value and turns it into a
`cm-skip` token that was never authored. HTML5 also keeps the FIRST occurrence of a duplicated
attribute, where a dict comprehension keeps the last.

The deck validator, the contrast scanner and the authoring tools each kept their own host-trusting
attribute dict, so the same document was read one way by the validator and another way by the tool
beside it. These tests pin each of those views on every interpreter.
"""

import contextlib
import html as _html
import html.parser as _html_parser
import os
import re
import sys
import types
import unittest
from html.parser import HTMLParser
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402  shared pkg/dev split path constants + tools bootstrap

sys.path.insert(0, _paths.TOOLS)

import _browser_attrs  # noqa: E402
import deck_validate  # noqa: E402
import doc_stats  # noqa: E402
import fix_skip  # noqa: E402
import generate_toc  # noqa: E402
import wrap_sections  # noqa: E402
from checks import parsing  # noqa: E402
from cmhval import contrast  # noqa: E402


class _HostValueProbe(HTMLParser):
    """Records the values the HOST hands a start-tag handler, to verify the simulation below."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.values = []

    def handle_starttag(self, tag, attrs):
        self.values.extend(v for _k, v in attrs if v is not None)


@contextlib.contextmanager
def pre_3_13_host(case):
    """Make the host `html.parser` decode attribute values the way Python 3.12 does - a plain
    `html.unescape`, which resolves a named reference that is only a PREFIX of the value.

    On 3.13+ that reinstates the drift; on 3.12 it is what the host already does, so one test
    pins the browser rule on every interpreter the skill runs on. The simulation verifies
    itself, so a future rename of the private CPython hook cannot make it a silent no-op that
    passes every test built on it vacuously.
    """
    with mock.patch.object(_html_parser, "_unescape_attrvalue", _html.unescape, create=True):
        probe = _HostValueProbe()
        probe.feed('<div id="&nbspx">')
        probe.close()
        case.assertEqual(probe.values, ["\u00a0x"],
                         "the pre-3.13 host decoder was not actually simulated, so any test "
                         "using it would pass vacuously")
        yield


@contextlib.contextmanager
def pre_3_13_split(case):
    """Make the host `html.parser` SPLIT a start tag's attributes the way Python 3.12 does -
    its tolerant matcher accepted `=+`, so `<a href==x>` swallowed the second `=` and yielded
    the value `x` where a browser (and the vendored tokenizer) yield `=x`.

    Patching the DECODE hook is not enough for a split divergence, so this is a separate
    simulation, and it self-verifies for the same reason: on 3.13+ the host already splits the
    browser's way, so without the patch a split test would pass vacuously.
    """
    with mock.patch.object(_html_parser, "attrfind_tolerant", _PRE_3_13_ATTRFIND, create=True):
        probe = _HostValueProbe()
        probe.feed("<a href==javascript:alert(1)>")
        probe.close()
        case.assertEqual(probe.values, ["javascript:alert(1)"],
                         "the pre-3.13 host attribute SPLIT was not actually simulated, so any "
                         "test using it would pass vacuously")
        yield


# CPython 3.12's `attrfind_tolerant`: note the `=+`, which a browser does not do.
_PRE_3_13_ATTRFIND = re.compile(
    r'((?<=[\'"\s/])[^\s/>][^\s/=>]*)(\s*=+\s*'
    r'(\'[^\']*\'|"[^"]*"|(?![\'"])[^>\s]*))?(?:\s|/(?!>))*')


class SharedDecodeShimTests(unittest.TestCase):
    """The shim itself: it must resolve the SHIPPED decoder, and its degraded path must still
    return usable attributes rather than crash a tool on a broken install."""

    def test_the_shim_resolves_the_shipped_decoder(self):
        self.assertIsNotNone(_browser_attrs._shared_attrs)
        self.assertIsNotNone(_browser_attrs._shared_attrs_dict)
        # A renamed or moved shared reading resolves to None SILENTLY (the missing-tool warning
        # fires only when the module itself fails to import), so every tool would quietly run on
        # the fallback copy for good. Pin the lookups themselves.
        self.assertIsNotNone(_browser_attrs._shared_link_rel_tokens)
        self.assertIsNotNone(_browser_attrs._shared_link_href_is_set)
        self.assertTrue(_browser_attrs._is_shipped(_browser_attrs._parsing))

    def test_the_shim_resolves_the_shipped_start_tag_parser(self):
        # The tools outside `checks` must PARSE with the shared base too, not only decode with the
        # shared rule: a bare `HTMLParser` lets the host draw the tag extent and decode the values,
        # so it raises where the rest of the validator resolves the reference and reads on.
        self.assertIs(_browser_attrs.StartTagParser,
                      _browser_attrs._parsing.browser_start_tag_parser)
        self.assertTrue(issubclass(contrast._StyleScanner, _browser_attrs.StartTagParser))
        self.assertTrue(issubclass(contrast._DocumentScanner, _browser_attrs.StartTagParser))

    def test_the_degraded_path_falls_back_to_the_host_parser(self):
        # A partial install must still give a tool a usable parser class, for the same reason the
        # attribute fallback exists: degraded beats unable to run. The fallback is the shim's own
        # `_FallbackTagNames` rather than a bare `HTMLParser`, so a consumer can still name an
        # element with `_browser_tag()` there instead of raising (CMH-VAL-21 clause 7).
        fallback = _browser_attrs._FallbackTagNames
        self.assertTrue(issubclass(fallback, HTMLParser))
        self.assertIs(_browser_attrs._start_tag_parser(None), fallback)
        self.assertIs(_browser_attrs._start_tag_parser(types.ModuleType("checks.parsing")),
                      fallback)
        not_a_parser = types.ModuleType("checks.parsing")
        not_a_parser.browser_start_tag_parser = object
        self.assertIs(_browser_attrs._start_tag_parser(not_a_parser), fallback)

    def test_a_decoder_from_an_unexpected_origin_is_refused(self):
        # `import checks.parsing` resolves through sys.modules first, so a host process that
        # already imported some other top-level `checks` would otherwise hand these tools a
        # foreign decoder with no signal.
        foreign = types.ModuleType("checks.parsing")
        foreign.__file__ = os.path.join(os.path.dirname(HERE), "not-the-skill", "parsing.py")
        self.assertFalse(_browser_attrs._is_shipped(foreign))
        self.assertFalse(_browser_attrs._is_shipped(types.ModuleType("checks.parsing")))

    def test_the_degraded_path_reads_a_rel_list_the_way_html_tokenizes_it(self):
        # The partial-install fallback must not reintroduce the differential the shared reading
        # exists to close (#1120): HTML splits a `rel` list on ASCII whitespace ONLY, and folds a
        # relation keyword ASCII-only. `ascii_lower` degrades to Python's UNICODE `.lower()` under
        # exactly this condition, so the fallback folds ASCII itself; U+212A would otherwise become
        # a `k` and turn a look-alike into a real relation on the degraded path alone.
        with mock.patch.object(_browser_attrs, "_shared_link_rel_tokens", None), \
                mock.patch.object(_browser_attrs, "_shared_ascii_lower", None):
            for sep in ("\u000b", "\u00a0", "\u001c", "\u001f"):
                self.assertEqual(_browser_attrs.link_rel_tokens("icon%sx" % sep),
                                 {"icon%sx" % sep}, repr(sep))
            self.assertEqual(_browser_attrs.link_rel_tokens("ICON x"), {"icon", "x"})
            self.assertEqual(_browser_attrs.link_rel_tokens("\u212a x"), {"\u212a", "x"})
            # ...and the reason it cannot simply reuse `ascii_lower`: that helper degrades to
            # Python's UNICODE `.lower()` under the SAME condition, which maps U+212A onto `k`.
            self.assertEqual(_browser_attrs.ascii_lower("\u212a"), "k")
            self.assertEqual(_browser_attrs.link_rel_tokens(None), set())
            self.assertEqual(_browser_attrs.link_rel_tokens("   "), set())

    def test_the_degraded_rel_split_is_pinned_to_the_shared_one(self):
        # The fallback is a SECOND copy of the ASCII-whitespace class, so it is pinned to the
        # canonical one as TEXT - the same discipline the JS copy is held to. Without this, an edit
        # to the shared pattern silently diverges the degraded reading.
        self.assertEqual(_browser_attrs._FALLBACK_REL_WS_RE.pattern, parsing.LINK_REL_WS_RE.pattern)

    def test_the_degraded_path_measures_an_href_the_way_html_measures_it(self):
        # The href half of the same discipline (#1140): the partial-install fallback must trim the
        # URL parser's own end set (the C0 controls and space), not Python's Unicode one, or the
        # degraded reading calls an href a browser resolves and fetches EMPTY and the tools inject
        # a favicon beside the author's.
        with mock.patch.object(_browser_attrs, "_shared_link_href_is_set", None):
            for ws in ("\u00a0", "\u2028", "\u3000"):
                self.assertTrue(_browser_attrs.link_href_is_set(ws), repr(ws))
            self.assertTrue(_browser_attrs.link_href_is_set(" /f.ico "))
            for ws in (None, "", " ", "\t\n\f\r ", "\u000b", "\u001c\u001f", "\u0001"):
                self.assertFalse(_browser_attrs.link_href_is_set(ws), repr(ws))

    def test_the_degraded_href_reading_is_pinned_to_the_shared_one(self):
        # A SECOND copy of the reading, pinned to the canonical one for the same reason the rel
        # split above is - but pinned BEHAVIOR-for-behavior, not just constant-for-constant: the
        # most likely future edit changes the function BODY (a different trim set), which a
        # constant-equality pin would sail straight past.
        self.assertEqual(_browser_attrs._FALLBACK_URL_ENDS_TRIM, parsing._URL_ENDS_TRIM)
        corpus = (None, "", " ", "\t\n\f\r ", "\u000b", "\u001c\u001f", "\u0001", "\u0000",
                  "\u00a0", "\u2028", "\u3000", "\u0085", " /f.ico ", "x", "\u000b/f.ico")
        with mock.patch.object(_browser_attrs, "_shared_link_href_is_set", None):
            degraded = [_browser_attrs.link_href_is_set(v) for v in corpus]
        self.assertEqual(degraded, [parsing.link_href_is_set(v) for v in corpus])

    def test_the_degraded_path_still_returns_the_hosts_attributes(self):
        # Only a broken/partial install gets here (the warning is emitted at import). It must
        # keep the tool WORKING - a degraded decode beats a tool that cannot run - and keep the
        # HTML5 first-wins rule for the dict.
        raw = [("ID", "first"), ("id", "second"), ("HIDDEN", None)]
        with mock.patch.object(_browser_attrs, "_shared_attrs", None), \
                mock.patch.object(_browser_attrs, "_shared_attrs_dict", None):
            pairs = _browser_attrs.attrs(None, "DIV", raw)
            ad = _browser_attrs.attrs_dict(None, "DIV", raw)
        self.assertEqual(pairs, [("id", "first"), ("id", "second"), ("hidden", None)])
        self.assertEqual(ad, {"id": "first", "hidden": ""})


class DeckValidatorAttributeTests(unittest.TestCase):
    """The deck validator's active-content / egress scan and its authored-content scan."""

    def test_a_duplicated_http_equiv_cannot_hide_a_meta_refresh(self):
        # HTML5 keeps the FIRST occurrence of a duplicated attribute, so this IS a refresh
        # redirect. A dict comprehension keeps the LAST one, which read the decoy instead and
        # let the redirect through.
        errors = deck_validate._active_content_errors(
            '<meta http-equiv="refresh" http-equiv="decoy" content="0;url=//evil.example/">')
        self.assertTrue(any("meta http-equiv=refresh" in e for e in errors), errors)

    def test_a_duplicated_http_equiv_does_not_forge_a_meta_refresh(self):
        # The same rule in the other direction: the first occurrence is not a refresh, so this
        # element redirects nothing and must not be reported.
        errors = deck_validate._active_content_errors(
            '<meta http-equiv="decoy" http-equiv="refresh" content="0;url=//evil.example/">')
        self.assertFalse(any("meta http-equiv=refresh" in e for e in errors), errors)

    def test_a_dangerous_url_is_read_from_the_browsers_attribute_split(self):
        # `<a href=='javascript:...'>` splits differently on the pre-3.13 host, which drops the
        # second `=` and reads a bare `javascript:` value - a finding a browser never sees,
        # because the value really is `=javascript:alert(1)`. The positive control proves the
        # scan still reports the shape a browser DOES execute.
        with pre_3_13_split(self):
            errors = deck_validate._active_content_errors("<a href==javascript:alert(1)>x</a>")
            real = deck_validate._active_content_errors("<a href=javascript:alert(1)>x</a>")
        self.assertFalse(any("dangerous URL scheme" in e for e in errors), errors)
        self.assertTrue(any("dangerous URL scheme" in e for e in real), real)

    def test_the_authored_content_scan_reads_the_first_slide_id(self):
        scanner = deck_validate._AuthoredContentScanner(80)
        scanner.feed('<section class="slide" data-slide-id="first" data-slide-id="second">'
                     "<p>x</p></section>")
        scanner.close()
        self.assertEqual([r.label for r in scanner.regions if r.kind == "slide"], ["first"])


class ContrastScannerAttributeTests(unittest.TestCase):
    """The contrast scanner's inline-style and element views."""

    def test_a_duplicated_style_attribute_uses_the_first_declaration(self):
        scanner = contrast._StyleScanner()
        scanner.feed('<p style="color:#111" style="color:#eee">x</p>')
        scanner.close()
        self.assertEqual([value for _tag, _attrs, value in scanner.inline_styles],
                         ["color:#111"])

    def test_an_element_label_carries_the_browsers_class_value(self):
        with pre_3_13_host(self):
            scanner = contrast._DocumentScanner()
            scanner.feed('<p class="a &nbspcm-skip">x</p>')
            scanner.close()
        node = scanner.root.children[0]
        self.assertEqual(contrast._element_source(node.tag, node.attrs),
                         "element <p.a.&nbspcm-skip>")


class AuthoringToolAttributeTests(unittest.TestCase):
    """The four authoring tools that read class / id attributes to decide what to edit."""

    def test_a_mermaid_block_is_not_treated_as_already_skipped(self):
        # `&nbspcm-skip` is ONE class token to a browser. The pre-3.13 host turns it into a
        # separate `cm-skip` token, so the block looked already fixed and kept its diagram
        # commentable - the exact drift the shared decode exists to remove.
        html = '<pre class="mermaid &nbspcm-skip">graph TD;</pre>'
        with pre_3_13_host(self):
            fixed, count = fix_skip.fix(html)
        self.assertEqual(count, 1, fixed)
        self.assertIn("cm-skip", fixed)

    def test_the_document_stats_count_words_the_browser_shows(self):
        # A paragraph whose class is one literal token is NOT a cm-skip block, so its words are
        # part of the document's reading content.
        html = ('<main id="commentRoot"><h1>T</h1>'
                '<p class="lead &nbspcm-skip">alpha beta gamma delta</p></main>')
        with pre_3_13_host(self):
            words = doc_stats.count_words(html)
        self.assertEqual(words, 5)

    def test_the_toc_sees_the_browsers_heading_id(self):
        with pre_3_13_host(self):
            parser = generate_toc._parse('<main id="commentRoot"><h2 id="&nbspx">H</h2></main>')
        self.assertEqual(parser.all_ids, ["commentRoot", "&nbspx"])

    def test_a_wrapped_section_points_at_the_browsers_heading_id(self):
        # The generated `aria-labelledby` must name the id a browser gives the heading;
        # a host-decoded one produced a section pointing at an id that does not exist.
        with pre_3_13_host(self):
            wrapped, count = wrap_sections.wrap_fragment('<h2 id="&nbspx">Heading</h2>\n<p>x</p>')
        self.assertEqual(count, 1)
        self.assertIn('<section aria-labelledby="&nbspx">', wrapped)

    def test_the_content_root_is_located_by_the_browsers_id_value(self):
        # HTML5 keeps the FIRST `id`, so the decoy element is NOT #commentRoot and the section
        # wrapping must scope to the real root. Matching ANY id attribute wrapped the wrong
        # element's content.
        html = ('<main id="decoy" id="commentRoot"><p>x</p></main>'
                '<main id="commentRoot"><p>y</p></main>')
        span = wrap_sections._locate_content_region(html)
        self.assertIsNotNone(span)
        start, end = span
        self.assertEqual(html[start:end], "<p>y</p>")


if __name__ == "__main__":
    unittest.main()
