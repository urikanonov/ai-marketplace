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
        self.assertEqual(_browser_attrs._FALLBACK_HTML_WS_RE.pattern, parsing.HTML_WS_RE.pattern)

    def test_the_degraded_start_tag_split_is_pinned_to_the_shared_one(self):
        # Same discipline for the degraded ATTRIBUTE split: it walks copies of the two patterns
        # `checks/parsing._tokenize_raw_tag` walks, so an edit to either shared pattern cannot
        # silently leave the partial-install reading behind. The FLAGS are pinned too - an added
        # `re.ASCII` or `re.IGNORECASE` on the shared pattern changes what it matches without
        # changing a character of its text.
        self.assertEqual(_browser_attrs._FALLBACK_TAG_NAME_RE.pattern, parsing._TAG_NAME_RE.pattern)
        self.assertEqual(_browser_attrs._FALLBACK_TAG_NAME_RE.flags, parsing._TAG_NAME_RE.flags)
        self.assertEqual(_browser_attrs._FALLBACK_ATTR_RE.pattern, parsing._ATTR_RE.pattern)
        self.assertEqual(_browser_attrs._FALLBACK_ATTR_RE.flags, parsing._ATTR_RE.flags)
        # The NUL fold is a copy too, and a BEHAVIOR rather than a pattern, so it is pinned
        # answer-for-answer against the shared one on the shapes that carry a NUL and the ones
        # that do not (the latter must come back unchanged, and by identity - the shared fold
        # skips the replace entirely, and a copy that always replaced would rebuild every string
        # a start tag has).
        for text in ("a\x00b", "\x00", "", "plain", "\ufffd"):
            self.assertEqual(_browser_attrs._fallback_fold_nul(text), parsing._fold_nul(text),
                             repr(text))
        untouched = "plain"
        self.assertIs(_browser_attrs._fallback_fold_nul(untouched), untouched)

    def test_the_degraded_value_decode_is_the_browser_rule_not_the_hosts(self):
        # The fallback decodes an attribute value with its own copy of the shared rule, NOT with
        # `html.unescape`: the host's decode resolves a named reference that is only a PREFIX of
        # the value or is followed by `=`, and DELETES the code points it considers invalid. A
        # caller that RE-SERIALIZES the start tag (the deck scaffold, the KQL run-link refresh)
        # writes that difference into the document, so a degraded install would silently rewrite
        # an authored `id`, `title` or `aria-label` into a value the rendered DOM never carries.
        named = ["x&ampy", "a&gt1", "&notit;", "&AMP=", "&amp;", "&amp", "&notanentity",
                 "&not", "&notinva;", "&NotEqualTilde;", "&nbsp", "&nbspx"]
        # Every branch of the numeric end state, not a hand-picked few: the C1 remap and its
        # UNLISTED members, the surrogate range, the U+10FFFF boundary either side, the null
        # reference, both hex spellings, and a run past Python's integer-conversion limit (which
        # the host's decode RAISES on). A corpus without these left the copied
        # `_fallback_numeric_charref` body effectively unpinned - its C1 and surrogate clauses
        # could be deleted with every test still green.
        numeric = ["&#%d;" % n for n in (0, 1, 9, 65, 127, 0x80, 0x81, 0x8d, 0x9f, 0xa0,
                                         0xd7ff, 0xd800, 0xdfff, 0xe000, 0xfffe, 0x10ffff,
                                         0x110000)]
        numeric += ["&#x%x;" % n for n in (0x80, 0x9f, 0xd800, 0xfffe, 0x10ffff, 0x110000)]
        numeric += ["&#X%X;" % n for n in (0x41, 0x80, 0xD800)]
        numeric += ["&#x41", "&#65=", "&#65a", "&#0000065;", "&#", "&#x", "&#;",
                    "&#" + "9" * 4600 + ";", "&#x" + "f" * 40 + ";"]
        # ...and each of them wrapped, so the `;` / `=` / other-trailing-character reattachment
        # and the `=` guard on the named branch are exercised in position, not only alone.
        cases = ["", "plain", "&", "&&", "a&b"]
        for ref in named + numeric:
            cases += [ref, "a" + ref, ref + "z", "a" + ref + "z", ref + "=", ref + "&"]
        with mock.patch.object(_browser_attrs, "_parsing", None):
            for value in cases:
                self.assertEqual(_browser_attrs.unescape_attr_value(value),
                                 parsing._unescape_attr_value(value), repr(value[:40]))
            self.assertEqual(_browser_attrs.unescape_attr_value("&#" + "9" * 4600 + ";"), "\ufffd")
            self.assertEqual(_browser_attrs.unescape_attr_value(None), "")
        # Pinned as data too, like the whitespace and start-tag patterns, so an edit to the shared
        # rule cannot silently leave the degraded one behind.
        self.assertEqual(_browser_attrs._FALLBACK_ATTR_CHARREF_RE.pattern,
                         parsing._ATTR_CHARREF_RE.pattern)
        self.assertEqual(_browser_attrs._FALLBACK_C1_CHARREF_REPLACEMENTS,
                         parsing._C1_CHARREF_REPLACEMENTS)
        self.assertEqual(_browser_attrs._FALLBACK_MAX_CHARREF_DIGITS,
                         parsing._MAX_CHARREF_DIGITS)
        self.assertEqual(_browser_attrs._FALLBACK_HTML5_ENTITY_NAMES,
                         parsing._HTML5_ENTITY_NAMES)

    def test_the_inert_scan_reads_a_comment_the_way_a_browser_ends_one(self):
        # Deliberately NOT the shared `_HTML_COMMENT_RE`: that pattern is a comment SEARCH, and a
        # search alone cannot know an opener sits inside an attribute value. The BOUNDARIES are the
        # validator's own, though (`_COMMENT_CLOSE_RE` / `_COMMENT_ABRUPT_CLOSE_RE`), so the two
        # agree on where a comment stops - and a browser keeps consuming an UNTERMINATED one.
        opener_in_attr = '<div title="a <!-- b"><a class="x" href="y">live</a><!-- note --></div>'
        spans = _browser_attrs.inert_spans(opener_in_attr)
        self.assertFalse(_browser_attrs.in_inert_span(opener_in_attr.index('<a class="x"'), spans))
        self.assertTrue(_browser_attrs.in_inert_span(opener_in_attr.index("<!-- note") + 5, spans))
        # An END tag is a tag too, so a `<!--` inside ITS quoted attribute opens nothing.
        end_tag_attr = '</div title="<!--"><a class="x" href="y">live</a><!-- end -->'
        self.assertFalse(_browser_attrs.in_inert_span(end_tag_attr.index('<a class="x"'),
                                                      _browser_attrs.inert_spans(end_tag_attr)))
        # Every close a browser honours ends the comment, so what follows is LIVE.
        for closed in ('<!-- note --!><a class="x" href="y">',
                       '<!--><a class="x" href="y">',
                       '<!---><a class="x" href="y">'):
            self.assertFalse(
                _browser_attrs.in_inert_span(closed.index('<a class="x"'),
                                             _browser_attrs.inert_spans(closed)), closed)
        unterminated = '<p>text<!-- open <a class="x" href="y">'
        self.assertTrue(_browser_attrs.in_inert_span(unterminated.index('<a class="x"'),
                                                     _browser_attrs.inert_spans(unterminated)))
        # A tag-shaped string inside an attribute VALUE is that value, not a tag.
        in_value = '<div title="<a class=\'cmh-kql-run\' href=\'z\'>"><a class="x">live</a></div>'
        spans = _browser_attrs.inert_spans(in_value)
        self.assertTrue(_browser_attrs.in_inert_span(in_value.index("<a class='cmh-kql-run'"),
                                                     spans))
        self.assertFalse(_browser_attrs.in_inert_span(in_value.index('<a class="x"'), spans))

    def test_inert_spans_name_the_regions_a_browser_does_not_parse_as_markup(self):
        # A tool that finds an element by SCANNING the source must skip what the validator's
        # PARSED views never see, or it acts on a decoy: rewriting a commented-out run link and
        # leaving the live one stale is the same silent failure #1160 is about.
        html = ('<figure><!-- <a class="cmh-kql-run" href="x"> -->'
                '<a class="cmh-kql-run" href="y"><script>var a = "<a class=cmh-kql-run>";</script>'
                '</figure>')
        spans = _browser_attrs.inert_spans(html)
        self.assertTrue(_browser_attrs.in_inert_span(html.index("<!--") + 5, spans))
        self.assertTrue(_browser_attrs.in_inert_span(html.index("var a"), spans))
        self.assertFalse(_browser_attrs.in_inert_span(html.index('<a class="cmh-kql-run" href="y"'),
                                                      spans))
        self.assertEqual(_browser_attrs.inert_spans(""), ())
        self.assertEqual(_browser_attrs.inert_spans(None), ())
        self.assertFalse(_browser_attrs.in_inert_span(0, ()))
        with mock.patch.object(_browser_attrs, "_parsing", None), \
                mock.patch.object(_browser_attrs, "_shared_raw_text_spans", None):
            # The degraded path covers comments only: a raw-text body needs the tokenizer, which
            # is exactly what a partial install is missing.
            degraded = _browser_attrs.inert_spans(html)
            self.assertTrue(_browser_attrs.in_inert_span(html.index("<!--") + 5, degraded))
            self.assertFalse(_browser_attrs.in_inert_span(html.index("var a"), degraded))

    def test_the_degraded_path_reads_every_attribute_not_only_the_class(self):
        # A tool that REWRITES a start tag (the KQL run-link refresh, #1160) needs the whole
        # attribute list, so the degraded split offers all of them - in order, first occurrence
        # winning, in every HTML quoting form - rather than the class alone. `_parsing` is patched
        # away wholesale, so the value decode really is the degraded `html.unescape` one too.
        with mock.patch.object(_browser_attrs, "_parsing", None), \
                mock.patch.object(_browser_attrs, "_shared_raw_attrs_pairs", None):
            pairs = _browser_attrs.raw_attrs_pairs(
                ' class="cmh-kql-run x" href=\'/a?q=1&amp;r=2\' TARGET=_blank hidden')
            self.assertEqual(pairs, [("class", "cmh-kql-run x"), ("href", "/a?q=1&r=2"),
                                     ("target", "_blank"), ("hidden", None)])
            # A `class=` spelled inside another attribute's quoted value is that value, not a
            # class - the whole reason a rewrite must parse rather than search.
            self.assertEqual(_browser_attrs.raw_attrs_pairs(' title=" class=cmh-kql" id="x"'),
                             [("title", " class=cmh-kql"), ("id", "x")])
            self.assertEqual(_browser_attrs.raw_attrs_pairs(""), [])
            self.assertEqual(_browser_attrs.raw_attrs_pairs(None), [])
            # A NUL folds to U+FFFD in an attribute NAME and VALUE alike, as the shared reading
            # folds it (`parsing._fold_nul`) and as a browser writes it. Handing back the literal
            # NUL gives a caller that RE-SERIALIZES the start tag - the deck scaffold - a document
            # whose own DOM carries a different value than the one the tool just decided on.
            self.assertEqual(_browser_attrs.raw_attrs_pairs(' data-x="a\x00b" data\x00-y=v'),
                             [("data-x", "a\ufffdb"), ("data\ufffd-y", "v")])
            self.assertEqual(_browser_attrs.raw_attrs_pairs(' data-x="a\x00b"'),
                             parsing.raw_attrs_pairs(' data-x="a\x00b"'))
        with mock.patch.object(_browser_attrs, "_parsing", None), \
                mock.patch.object(_browser_attrs, "_shared_raw_attrs_class_tokens", None), \
                mock.patch.object(_browser_attrs, "_shared_raw_attrs_pairs", None):
            # The two degraded readings are ONE reading: the class comes off the same split.
            self.assertEqual(_browser_attrs.raw_attrs_class_tokens(' title=" class=cmh-kql"'), [])
            self.assertEqual(_browser_attrs.raw_attrs_class_tokens(' class="a" class="b"'), ["a"])

    def test_a_class_list_is_tokenized_the_way_html_tokenizes_it(self):
        # CMH-VAL-21 clause 11 (#1139): HTML splits a `class` list on ASCII whitespace ONLY and
        # matches a token by EXACT code points. Python's argument-less `str.split()` additionally
        # splits on the vertical tab, NBSP and U+001C-U+001F, so it read `class="cm-skip\u000bx"`
        # as carrying `cm-skip` where a browser sees ONE opaque class that `.cm-skip` never
        # matches - the gate's verdict and the rendered document disagreed.
        for sep in ("\u000b", "\u00a0", "\u001c", "\u001f"):
            self.assertEqual(parsing.class_tokens("cm-skip%sx" % sep), {"cm-skip%sx" % sep},
                             repr(sep))
        for ws in ("\t", "\n", "\f", "\r", " "):
            self.assertEqual(parsing.class_tokens("cm-skip%sx" % ws), {"cm-skip", "x"}, repr(ws))
        # No fold at all, so a look-alike cannot ride in: `casefold()` mapped U+212A KELVIN SIGN
        # onto `k`, making `cmh-\u212aql` a `cmh-kql` for the validator and never for a browser.
        self.assertEqual(parsing.class_tokens("cmh-\u212aql"), {"cmh-\u212aql"})
        self.assertEqual(parsing.class_tokens("CM-SKIP"), {"CM-SKIP"})
        self.assertEqual(parsing.class_tokens(None), set())
        self.assertEqual(parsing.class_tokens("   "), set())
        # The ORDERED reading a caller that REWRITES the attribute needs.
        self.assertEqual(parsing.html_ws_tokens("  b   a\tc "), ["b", "a", "c"])

    def test_the_degraded_path_reads_a_class_list_the_way_html_tokenizes_it(self):
        # The partial-install fallback must not reintroduce the differential either.
        with mock.patch.object(_browser_attrs, "_shared_class_tokens", None), \
                mock.patch.object(_browser_attrs, "_shared_html_ws_tokens", None):
            for sep in ("\u000b", "\u00a0", "\u001c", "\u001f"):
                self.assertEqual(_browser_attrs.class_tokens("cm-skip%sx" % sep),
                                 {"cm-skip%sx" % sep}, repr(sep))
            self.assertEqual(_browser_attrs.class_tokens("cm-skip x"), {"cm-skip", "x"})
            self.assertEqual(_browser_attrs.class_tokens("cmh-\u212aql"), {"cmh-\u212aql"})
            self.assertEqual(_browser_attrs.class_tokens(None), set())
            self.assertEqual(_browser_attrs.class_tokens("   "), set())
            self.assertEqual(_browser_attrs.html_ws_tokens(" b  a "), ["b", "a"])

    def test_a_raw_start_tag_class_is_read_through_the_shared_rule(self):
        # A tool that has the start tag as TEXT reads a class through the same rule, in all three
        # HTML quoting forms - a `class="[^"]*cmh-kql[^"]*"` substring regex both over-matched a
        # `my-cmh-kql-ish` class and never saw a single-quoted or unquoted one at all.
        for attrs in (' class="a cmh-kql b"', " class='a cmh-kql'", " class=cmh-kql", " CLASS=cmh-kql"):
            self.assertTrue(_browser_attrs.attrs_have_class(attrs, "cmh-kql"), attrs)
        for attrs in (' class="my-cmh-kql-ish"', ' class="cmh-kql\u000bx"', ' class="CMH-KQL"',
                      ' class="cmh-\u212aql"', "", ' id="x"'):
            self.assertFalse(_browser_attrs.attrs_have_class(attrs, "cmh-kql"), attrs)
        with mock.patch.object(_browser_attrs, "_shared_raw_attrs_class_tokens", None):
            self.assertTrue(_browser_attrs.attrs_have_class(" class='a cmh-kql'", "cmh-kql"))
            self.assertFalse(_browser_attrs.attrs_have_class(' class="my-cmh-kql-ish"', "cmh-kql"))
            self.assertFalse(_browser_attrs.attrs_have_class(None, "cmh-kql"))
            self.assertEqual(_browser_attrs.raw_attrs_class_tokens(' class="b a"'), ["b", "a"])

    def test_a_raw_start_tag_class_is_read_by_the_shared_tokenizer_not_a_regex(self):
        # The raw reader runs the SHARED start-tag tokenizer, so it answers exactly what the
        # parsed twin answers. A `class=` regex over the raw text got four things wrong at once,
        # each of them a way for a HARD gate (the KQL run-link requirement, the escaped-diff-text
        # error) to disagree with the browser:
        cases = [
            # (a) a character reference is DECODED, as `classList` decodes it: this one failed the
            #     gate OPEN, since a browser really does see the class `cmh-kql` here.
            (' class="cmh-&#107;ql"', True),
            (' class="x&#32;cmh-kql"', True),
            # (b) `data-class=` is not `class=`, and neither is a `class=` spelled inside another
            #     attribute's quoted VALUE.
            (' data-class="cmh-kql"', False),
            (" title='class=\"cmh-kql\"'", False),
            # (c) HTML5 keeps the FIRST of a duplicated attribute, so a later decoy loses.
            (' class="x" class="cmh-kql"', False),
            (' class="cmh-kql" class="x"', True),
            # (d) an unquoted value ends at ASCII whitespace, so NBSP stays INSIDE the one class.
            (" class=cmh-kql\u00a0x", False),
            (" class=cmh-kql", True),
        ]
        for attrs, expected in cases:
            self.assertEqual(parsing.attrs_have_class(attrs, "cmh-kql"), expected, repr(attrs))
            self.assertEqual(_browser_attrs.attrs_have_class(attrs, "cmh-kql"), expected,
                             repr(attrs))

    def test_the_degraded_raw_class_regex_is_pinned_to_the_rules_it_can_keep(self):
        # The partial-install fallback cannot decode a character reference (that is what the
        # shared tokenizer is FOR), but it must not give up the rules a regex CAN keep: the
        # attribute-name boundary, HTML's unquoted-value terminator, and an ASCII-only fold.
        with mock.patch.object(_browser_attrs, "_shared_raw_attrs_class_tokens", None):
            self.assertTrue(_browser_attrs.attrs_have_class(" class=cmh-kql", "cmh-kql"))
            self.assertFalse(_browser_attrs.attrs_have_class(' data-class="cmh-kql"', "cmh-kql"))
            self.assertFalse(_browser_attrs.attrs_have_class(" class=cmh-kql\u00a0x", "cmh-kql"))
            self.assertFalse(_browser_attrs.attrs_have_class(' cla\u017f\u017f="cmh-kql"', "cmh-kql"))

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
