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
def _no_shared_reading():
    """`_browser_attrs` as a PARTIAL install sees it: the shared raw-attribute split gone, so the
    degraded local `_fallback_attr_pairs` answers instead. Self-verifying, so a future rename of
    the shared binding cannot turn every test built on it into a vacuous pass."""
    with mock.patch.object(_browser_attrs, "_shared_raw_attrs_pairs", None):
        assert _browser_attrs.raw_attrs_pairs('a="1"') == [("a", "1")], (
            "the degraded split was not actually exercised")
        yield


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
        # away wholesale, so the value decode really is the degraded one too - which is the COPIED
        # browser rule, not the host's `html.unescape` (`&amp;` still decodes, and the shapes the
        # two rules disagree about have their own test below).
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
            # An attribute NAME folds ASCII-only, as a browser folds one: `ascii_lower` degrades
            # to Python's UNICODE `.lower()` under exactly this condition, and that fold maps
            # U+212A onto `k`, so a `data-\u212aey` would be RE-SERIALIZED as `data-key` - an
            # attribute the authored document never had - on the partial-install path alone.
            self.assertEqual(_browser_attrs.raw_attrs_pairs(' data-\u212aey=v CLASS=x'),
                             [("data-\u212aey", "v"), ("class", "x")])
            self.assertEqual(_browser_attrs.raw_attrs_pairs_consumed(' data-\u212aey=v'),
                             ([("data-\u212aey", "v")], True))
        with mock.patch.object(_browser_attrs, "_parsing", None), \
                mock.patch.object(_browser_attrs, "_shared_raw_attrs_class_tokens", None), \
                mock.patch.object(_browser_attrs, "_shared_raw_attrs_pairs", None):
            # The two degraded readings are ONE reading: the class comes off the same split.
            self.assertEqual(_browser_attrs.raw_attrs_class_tokens(' title=" class=cmh-kql"'), [])
            self.assertEqual(_browser_attrs.raw_attrs_class_tokens(' class="a" class="b"'), ["a"])

    def test_the_shared_serializer_cannot_fuse_two_valueless_attributes(self):
        # #1195: the READING has a matching WRITING, and it lives in one place. A re-serializer
        # that writes a valueless attribute back as a BARE NAME drops the `/` HTML uses to
        # terminate an attribute name, so the NEXT attribute - whose name legally begins with `=`
        # (HTML5's unexpected-equals-sign-before-attribute-name state) - fuses into it and gains a
        # value the input never had. `name=""` is the same attribute to a browser (an absent value
        # IS the empty string) and cannot be terminated that way.
        def norm(pairs):
            return [(n, v or "") for n, v in pairs]

        for attrs in ('data-a/=onload',
                      'data-a/=x data-b',
                      'hidden',
                      'data-a=""',
                      'data-a/=',
                      'data-a/==x',
                      'data-a=""/=x',
                      'id="commentRoot" data-a/=onload',
                      'title="a &amp; b" data-a/=onclick=alert(1)',
                      # An attribute NAME may legally carry `"`, `'` and `<` (each a parse error
                      # that the tokenizer nonetheless appends to the name), and the writer emits
                      # a name verbatim because HTML has no escape for one. The round trip still
                      # closes because a name can never contain `=`, so the writer's own `="`
                      # unambiguously starts the value.
                      'a"b=1 data-c/=x',
                      "a'b data-c/=x",
                      'a<b data-c/=x'):
            pairs = _browser_attrs.raw_attrs_pairs(attrs)
            tag = _browser_attrs.serialize_start_tag("section", pairs)
            self.assertTrue(tag.startswith("<section") and tag.endswith(">"), attrs)
            # The round trip itself: reading the tag it just wrote answers what it was handed.
            self.assertEqual(norm(_browser_attrs.raw_attrs_pairs(tag[len("<section"):-1])),
                             norm(pairs), attrs)
            # And the FORM the round trip rests on: EVERY attribute is written in the one
            # canonical ` name="value"` shape, so none is left bare for a following name's `=` to
            # terminate. (The other faithful spelling - re-emitting the `/` name terminator - is
            # deliberately ruled out: written LAST it lands as the self-closing `/>` solidus.)
            self.assertEqual(
                tag,
                "<section%s>" % "".join(' %s="%s"' % (n, _html.escape(v, quote=True))
                                        for n, v in norm(pairs)), attrs)
        # A value is escaped exactly ONCE from its DECODED form, so an authored `&amp;` comes back
        # as `&amp;` rather than as the literal `&amp;amp;`. Spelled as an expected LITERAL rather
        # than against another `_html.escape` call, so the escaping CHOICE is pinned and not just
        # its self-consistency.
        self.assertEqual(_browser_attrs.serialize_start_tag("a", [("title", "a & b")]),
                         '<a title="a &amp; b">')
        self.assertEqual(_browser_attrs.serialize_start_tag("a", [("x", 'a"<b>&c')]),
                         '<a x="a&quot;&lt;b&gt;&amp;c">')
        self.assertEqual(_browser_attrs.serialize_start_tag("br", []), "<br>")
        # A FOREIGN self-closing element keeps its own ` /` terminator. Dropping it un-closed the
        # element, so inside an inline `<svg>` the next sibling became its CHILD and stopped
        # rendering. It is safe only because every attribute now ends in `"`: a trailing ` /`
        # cannot terminate an attribute NAME.
        self.assertEqual(
            _browser_attrs.serialize_start_tag("rect", [("width", "4")], self_closing=True),
            '<rect width="4" />')
        self.assertEqual(_browser_attrs.serialize_start_tag("br", [], self_closing=True), "<br />")

    def test_every_start_tag_re_serializer_uses_the_shared_one(self):
        # The four call sites that rebuild a start tag from parsed pairs each kept their own copy
        # of this rule and drifted: #1191 fixed ONE of them and left three carrying the identical
        # fusion bug. Pin that each of the four rewrite entry points invokes the shared writer at
        # RUN TIME and RETURNS what it produced - a source grep would pass on a comment or on dead
        # code, and a spy that only counted calls would pass on a caller that invoked the shared
        # writer and then returned a hand-built tag anyway.
        import deck_scaffold  # noqa: E402
        import kql_highlight  # noqa: E402
        import new_document  # noqa: E402
        import retrofit  # noqa: E402

        seen = []
        real = _browser_attrs.serialize_start_tag

        def spy(tag, pairs, **kwargs):
            out = real(tag, pairs, **kwargs)
            seen.append((tag, out))
            return out

        figure = kql_highlight.render_block(
            "help.kusto.windows.net", "Samples", "Demo", "StormEvents | take 1")
        host = ('<!doctype html><html><head><title>H</title></head><body>'
                '<p class="skipme" data-a/=onload>x</p></body></html>')
        with mock.patch.object(_browser_attrs, "serialize_start_tag", spy):
            prepared, _ids = deck_scaffold.prepare_slides(
                '<section class="slide" data-a/=onload><p>x</p></section>')
            refreshed = kql_highlight.refresh_block(figure, "StormEvents | take 2")
            main_tag = new_document._build_main_tag(
                ' id="commentRoot" data-a/=onload', "k", "L", None)
            skipped, _warnings = retrofit._apply_skip_selectors(host, [".skipme"])
        # Every entry point reached the shared writer: dropping one (a hand-rolled builder coming
        # back) drops its tag from this set.
        self.assertEqual(sorted({tag for tag, _out in seen}), ["a", "main", "p", "section"])
        # ... and every tag it produced is the tag that actually LANDED in that caller's output,
        # so invoking it and then returning something else fails here.
        landed = "\n".join((prepared, refreshed, main_tag, skipped))
        for _tag, out in seen:
            self.assertIn(out, landed)
        # ... and the SHAPE fusion turns on, read back off each caller's OWN output rather than
        # off the writer's: the two adjacent valueless attributes stay two attributes. A writer
        # that regressed to bare names would answer `data-a="onload"` and no `=onload` at all.
        for text, tag in ((prepared, "section"), (main_tag, "main"), (skipped, "p")):
            m = next((mm for mm in re.finditer(
                r'<%s\b((?:"[^"]*"|\'[^\']*\'|[^>"\'])*)>' % tag, text)
                if "data-a" in mm.group(1)), None)
            self.assertIsNotNone(m, text)
            pairs = dict(_browser_attrs.raw_attrs_pairs(m.group(1)))
            self.assertEqual(pairs.get("data-a"), "", text)
            self.assertEqual(pairs.get("=onload"), "", text)
    def test_the_degraded_start_tag_scan_is_pinned_to_the_shared_one(self):
        # The shim's start-tag EXTENT scan is a COPY of the vendored one rather than a pattern
        # (#1197): the deck scaffold LOCATES the slide it re-serializes with it, so a boundary
        # drawn any other way on a partial install is written into the deck rather than merely
        # read. A copy is only worth having while it answers what it copies, so it is pinned
        # answer-for-answer over the shapes that make the two readings differ from a quote-aware
        # regex - a quote inside an attribute NAME, an unterminated quoted value (the eof-in-tag
        # drop), the missing-attribute-value and self-closing states, an unquoted value, and a NUL
        # in the tag name - and its character classes are pinned as TEXT, like every other copy.
        self.assertEqual(_browser_attrs._FALLBACK_TAG_WS, parsing._TAG_WS)
        self.assertEqual(_browser_attrs._FALLBACK_TAG_WS_SLASH, parsing._TAG_WS_SLASH)
        self.assertEqual(_browser_attrs._FALLBACK_TAG_NAME_STOP, parsing._TAG_NAME_STOP)
        self.assertEqual(_browser_attrs._FALLBACK_ATTR_NAME_STOP, parsing._ATTR_NAME_STOP)
        self.assertEqual(_browser_attrs._FALLBACK_UNQUOTED_VALUE_STOP,
                         parsing._UNQUOTED_VALUE_STOP)
        cases = [
            '<section class="slide" a"b>', "<section class=slide foo\" bar=\"x>",
            '<section class="slide">', "<section class=slide>", "<section>", "<section/>",
            "<section />", "<section class=slide/>", "<section class='slide'>",
            "<section class=>", "<section class>", "<section class =\t'a b' id=x>",
            "<section a=1 b=2>", "<section a='>'>", '<section a=">">', "<section a=",
            "<section a='", '<section a="', "<section", "<section ", "<sec\x00tion class=slide>",
            "<SECTION CLASS=Slide>", "<section\x00>", "<section a/=b>", "<section a//b>",
            "<section a=b/>", "<section a=b c>", "<section =x>", "<section a==x>",
            "<section a=x y=z><p>after</p></section>", "<section a='b'c=d>",
            "<section a\u212ab=c>", "<section \u017f=1>", "<p>text</p>",
            # The whitespace-around-`=` states. Without these the after-attribute-name and
            # before-attribute-value whitespace skips could be DELETED from the copy with the
            # whole corpus still green - and they change the answer only on an unterminated
            # value, which is exactly the eof-in-tag drop this fix rests on.
            '<section class="slide" foo= "bar>', '<section class="slide" foo ="bar>',
            '<section a = "b">', "<section a =b>", "<section a= b>", "<section a =>",
            # ...and the tag NAME's own ASCII-only fold, which the copy applies itself rather than
            # through `ascii_lower` (that helper degrades to Python's UNICODE `.lower()` under
            # exactly this condition). Without these a regression to `.lower()` in the copy would
            # read `<lin\u212a>` as a `<link>` on the partial-install path alone.
            "<lin\u212a>", "<SECTIO\u212a>", "<\u017fection class=slide>",
        ]
        for raw in cases:
            self.assertEqual(_browser_attrs._fallback_scan_start_tag(raw, 0),
                             parsing.scan_start_tag(raw, 0), repr(raw))
            # ...and from a non-zero offset too, which is how a scanner walking a fragment calls
            # it: an index the copy read as absolute would silently answer for another tag.
            padded = "<p>x</p>\n" + raw
            self.assertEqual(_browser_attrs._fallback_scan_start_tag(padded, 9),
                             parsing.scan_start_tag(padded, 9), repr(raw))
        # The shim resolves the SHIPPED scan, not the copy - a renamed shared reading would
        # otherwise leave every tool on the fallback silently, for good.
        self.assertIsNotNone(_browser_attrs._shared_scan_start_tag)
        self.assertIs(_browser_attrs._shared_scan_start_tag, parsing.scan_start_tag)
        for raw in cases:
            self.assertEqual(_browser_attrs.scan_start_tag(raw, 0), parsing.scan_start_tag(raw, 0))

    def test_the_degraded_end_tag_close_is_pinned_to_the_shared_one(self):
        # The END-tag half of the same walk (#1197). A browser ends a tag at the first `>` OUTSIDE
        # a quoted value, and a value only opens after an `=`, so an end tag's own (ignored but
        # still tokenized) attributes cannot end it early and a stray quote where a name belongs
        # cannot swallow the `>`. The caller SPLICES the document at this boundary, so the
        # partial-install stand-in is a pinned copy rather than a degradation, like the scan above.
        self.assertIsNotNone(_browser_attrs._shared_end_tag_close)
        self.assertIs(_browser_attrs._shared_end_tag_close, parsing.end_tag_close)
        cases = ["</section>", "</section >", "</section\n>", "</section/>",
                 '</section foo="a>b">', "</section foo='a>b'>", '</section ">',
                 '</section a= "b>c">', '</section a ="b>c">', "</section a=>", "</section a=",
                 '</section a="', "</section", "</section ", "</section a=b>", "<section a=b>",
                 "</section\x00>", "</SECTION>", ">", "",
                 # The whole HTML whitespace class around the `=`, not only space and LF: a copy
                 # that dropped `\r` or `\f` from it would mis-close at the `>` inside the value.
                 '</section a=\t"b>c">', '</section a=\r"b>c">', '</section a=\f"b>c">',
                 '</section a\t="b>c">', '</section a\r="b>c">', '</section a\f="b>c">']
        for raw in cases:
            self.assertEqual(_browser_attrs._fallback_end_tag_close(raw, 0),
                             parsing.end_tag_close(raw, 0), repr(raw))
            self.assertEqual(_browser_attrs.end_tag_close(raw, 0),
                             parsing.end_tag_close(raw, 0), repr(raw))
            padded = "<p>x</p>\n" + raw
            self.assertEqual(_browser_attrs._fallback_end_tag_close(padded, 9),
                             parsing.end_tag_close(padded, 9), repr(raw))
        # The shapes the literal `</section>` search this replaced got wrong, pinned as ANSWERS
        # and not only as parity - a deletion made on BOTH sides at once keeps parity green.
        self.assertEqual(parsing.end_tag_close("</section >", 0), 11)
        self.assertEqual(parsing.end_tag_close('</section foo="a>b">', 0), 20)
        self.assertEqual(parsing.end_tag_close('</section a= "b>c">', 0), 19)
        self.assertEqual(parsing.end_tag_close('</section a ="b>c">', 0), 19)
        self.assertEqual(parsing.end_tag_close('</section a="', 0), -1)

    def test_the_degraded_comment_close_is_pinned_to_the_shared_one(self):
        # The third leg of the same walk (#1197): a COMMENT is prose, so a tag-shaped string in
        # one is not a tag - and a commented-out tag with an unterminated quoted value would
        # otherwise run a start-tag scan through the LIVE markup after it and swallow a real
        # slide. HTML's boundary is `-->` or the legacy `--!>`, `<!-->` and `<!--->` close
        # abruptly, a whitespace-separated `-- >` does NOT close, and an unterminated comment runs
        # to the end of the input.
        self.assertIsNotNone(_browser_attrs._shared_comment_close)
        self.assertIs(_browser_attrs._shared_comment_close, parsing.comment_close)
        self.assertEqual(_browser_attrs._FALLBACK_COMMENT_CLOSE_RE.pattern,
                         parsing._COMMENT_CLOSE_RE.pattern)
        self.assertEqual(_browser_attrs._FALLBACK_COMMENT_ABRUPT_CLOSE_RE.pattern,
                         parsing._COMMENT_ABRUPT_CLOSE_RE.pattern)
        cases = ["<!-- x -->tail", "<!---->tail", "<!-->tail", "<!--->tail", "<!--x--!>tail",
                 "<!-- x -- > y -->tail", "<!-- unterminated", "<!--", "<!--<section>-->tail",
                 '<!-- <a href="x -->tail', "<!--a-->b-->tail"]
        for raw in cases:
            self.assertEqual(_browser_attrs._fallback_comment_close(raw, 0),
                             parsing.comment_close(raw, 0), repr(raw))
            self.assertEqual(_browser_attrs.comment_close(raw, 0),
                             parsing.comment_close(raw, 0), repr(raw))
            padded = "<p>x</p>\n" + raw
            self.assertEqual(_browser_attrs._fallback_comment_close(padded, 9),
                             parsing.comment_close(padded, 9), repr(raw))
        # Pinned as ANSWERS too, so a both-sides edit cannot keep parity while moving the
        # boundary: the abrupt closers end at their `>`, `-- >` does not close, and an
        # unterminated comment answers the end of the input rather than a position inside it.
        self.assertEqual(parsing.comment_close("<!-->tail", 0), 5)
        self.assertEqual(parsing.comment_close("<!--->tail", 0), 6)
        self.assertEqual(parsing.comment_close("<!--x--!>tail", 0), 9)
        self.assertEqual(parsing.comment_close("<!-- x -- > y -->tail", 0), 17)
        self.assertEqual(parsing.comment_close("<!-- unterminated", 0), len("<!-- unterminated"))

    def test_the_shared_raw_text_element_set_is_one_set(self):
        # A walk that consumes tags must skip a raw-text BODY whole for the same reason it skips a
        # comment. The shim hands back the shared set itself rather than a second opinion about
        # which elements hold text, and its partial-install copy is pinned to it as DATA.
        self.assertIs(_browser_attrs.raw_text_elements(), parsing.raw_text_elements)
        self.assertEqual(_browser_attrs._FALLBACK_RAW_TEXT_ELEMENTS, parsing._RAW_TEXT_ELEMENTS)
        with mock.patch.object(_browser_attrs, "_parsing", None), \
                mock.patch.object(_browser_attrs, "_shared_raw_text_elements", None):
            self.assertEqual(_browser_attrs.raw_text_elements(), parsing._RAW_TEXT_ELEMENTS)

    def test_the_degraded_split_reports_whether_it_consumed_the_whole_region(self):
        # The consumed flag is what lets a caller that REWRITES a start tag fail closed rather
        # than re-serialize a reading that stopped short and silently drop every attribute past
        # that point (#1197). It must answer the same on both paths, including for the tag-close
        # leftovers (HTML whitespace and the self-closing solidus) that are NOT attributes.
        self.assertIsNotNone(_browser_attrs._shared_raw_attrs_pairs_consumed)
        for attrs, want in ((None, True), ('', True), (' class="slide"', True),
                            (' class=slide', True), (" class='slide' id=x", True),
                            (' a"b', True), (' class="slide"/', True), (' class="slide" ', True),
                            (' data-a/=onload', True), (' =x', True), (' a=">"', True),
                            (' a=b c', True), (' hidden', True), (' a=b"c', True),
                            (' \x00', True), (' "', True),
                            # ...and the FALSE half, which no start tag the browser scan accepts
                            # can produce (the two readings agree on every such shape) but a
                            # caller handing over a truncated attribute region can: tokenization
                            # stops at the unterminated value and leaves an attribute-name
                            # character behind, which is precisely what must not be
                            # re-serialized as if it were the whole tag.
                            (' a="', False), (" a='", False), (' a="b', False),
                            (' a=">', False), (' >', False)):
            shared = _browser_attrs.raw_attrs_pairs_consumed(attrs)
            self.assertEqual(shared, parsing.raw_attrs_pairs_consumed(attrs), repr(attrs))
            self.assertIs(shared[1], want, repr(attrs))
            with mock.patch.object(_browser_attrs, "_parsing", None), \
                    mock.patch.object(_browser_attrs, "_shared_raw_attrs_pairs_consumed", None):
                self.assertEqual(_browser_attrs.raw_attrs_pairs_consumed(attrs), shared,
                                 repr(attrs))
            # The pairs half stays exactly what the pairs-only reading answers, so a caller that
            # switched to this one cannot start reading a different attribute list.
            self.assertEqual(shared[0], _browser_attrs.raw_attrs_pairs(attrs), repr(attrs))

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


class AttributeValueEscapeTests(unittest.TestCase):
    """CMH-DECK-02: `escape_attr_value` is the TOTAL inverse of the browser's attribute-value read.

    Every re-serializer in the skill now writes through one `serialize_start_tag`, which escapes
    each decoded value with this, so the escape must be exact: what a browser decodes out of the
    written attribute has to be the value that went in. `html.escape(quote=True)` is not that
    inverse - it leaves CR (which input-stream preprocessing turns into LF) and NUL and a lone
    surrogate (which no document can hold at all) untouched.
    """

    def _browser_reads(self, escaped):
        """The value a browser holds for `title="<escaped>"`, in the browser's own ORDER: the
        written TEXT is preprocessed first (CR and CRLF alike become LF), and only then is the
        start tag split and its value decoded. Decoding without that first step is exactly the
        blind spot that let a literal CR pass for a CR."""
        preprocessed = re.sub("\r\n?", "\n", '<section title="%s">' % escaped)
        return dict(_browser_attrs.raw_attrs_pairs(preprocessed[len("<section"):-1]))["title"]

    def test_the_escape_round_trips_every_code_point(self):
        # A sweep, not a handful of cases: the point of one shared escape is that no character is
        # left to a caller's judgement. Two code points do not round-trip to THEMSELVES, because
        # no HTML document can hold them - a NUL (the tokenizer folds it) and a lone surrogate (it
        # cannot be encoded as UTF-8 at all) - and for those the escape writes U+FFFD, which IS
        # what a browser ends up holding. This sweep alone cannot fail on either fold, because the
        # read side folds NUL too; the next test is what actually pins them.
        for cp in (list(range(0x00, 0x120))
                   + [0xD7FF, 0xD800, 0xDC00, 0xDFFF, 0xE000]
                   + [0x2028, 0x2029, 0x2192, 0xFEFF, 0xFFFD, 0x10FFFF]):
            ch = chr(cp)
            want = "\ufffd" if cp == 0 or 0xD800 <= cp <= 0xDFFF else ch
            self.assertEqual(self._browser_reads(_browser_attrs.escape_attr_value("a%sb" % ch)),
                             "a%sb" % want, hex(cp))

    def test_the_unholdable_characters_are_folded_on_the_write_side(self):
        # The sweep above CANNOT catch a missing fold: `raw_attrs_pairs` folds a NUL itself, so a
        # literal NUL written into the tag reads back as U+FFFD either way and deleting the write
        # side leaves every round-trip test green. The fold exists for the readers that do NOT do
        # it - `unescape_attr_value` alone returns a NUL unchanged, and `authoring/upgrade.py`
        # decodes through exactly that - so it is pinned as a SPELLING, on the escape's own output.
        self.assertEqual(_browser_attrs.escape_attr_value("a\x00b"), "a\ufffdb")
        self.assertEqual(_browser_attrs.escape_attr_value("a\ud800b"), "a\ufffdb")
        self.assertEqual(_browser_attrs.escape_attr_value("a\udfffb"), "a\ufffdb")
        self.assertEqual(_browser_attrs.unescape_attr_value("a\x00b"), "a\x00b")
        self.assertEqual(
            _browser_attrs.unescape_attr_value(_browser_attrs.escape_attr_value("a\x00b")),
            "a\ufffdb")
        # A lone surrogate is what makes the fold load-bearing rather than tidy: without it the
        # value cannot be written to a UTF-8 file at all, and the failure lands at the file write,
        # nowhere near the value that caused it.
        _browser_attrs.escape_attr_value("a\ud800b").encode("utf-8")

    def test_a_cr_is_escaped_and_an_lf_is_left_alone(self):
        # The two halves of the CR clause, pinned as SPELLINGS rather than only as behavior, so a
        # regression is reported at the escape and not three layers away. LF must stay literal:
        # preprocessing does not touch it, so escaping it would be a needless rewrite.
        self.assertEqual(_browser_attrs.escape_attr_value("a\rb"), "a&#13;b")
        self.assertEqual(_browser_attrs.escape_attr_value("a\nb"), "a\nb")
        self.assertEqual(_browser_attrs.escape_attr_value("a\tb"), "a\tb")

    def test_an_authored_reference_text_is_not_turned_into_the_character(self):
        # The double-encode trap: a value whose TEXT is `&#13;` (authored `&amp;#13;`) must come
        # back as that text, never as a CR. The `&` is escaped first and the CR replacement runs on
        # the escaped string, so the `&` of the injected `&#13;` can never be re-escaped and an
        # authored one can never be un-escaped.
        self.assertEqual(_browser_attrs.escape_attr_value("&#13;"), "&amp;#13;")
        self.assertEqual(self._browser_reads(_browser_attrs.escape_attr_value("&#13;")), "&#13;")

    def test_it_still_escapes_everything_html_escape_does(self):
        # The CR and fold clauses are ADDED to `html.escape(quote=True)`, never traded against it:
        # dropping `'` or `>` would let a value break out of the attribute it is written into.
        self.assertEqual(_browser_attrs.escape_attr_value("&<>\"'"),
                         "&amp;&lt;&gt;&quot;&#x27;")

    def test_only_none_is_treated_as_the_empty_value(self):
        # A VALUELESS attribute decodes to the empty string, so `None` is accepted. Any other
        # non-string raises `TypeError`: the earlier `value or ""` turned a falsy `0` into `""`,
        # which is the silent-rewrite class this exists to stop. The check is explicit, so the
        # exception no longer depends on which method the argument happens to be missing - `0` used
        # to raise `AttributeError`, `b"x"` `TypeError`, and any object with a `.replace` succeeded
        # and wrote nonsense.
        self.assertEqual(_browser_attrs.escape_attr_value(None), "")
        self.assertEqual(_browser_attrs.escape_attr_value(""), "")
        for bad in (0, False, b"x", ["x"]):
            with self.assertRaises(TypeError):
                _browser_attrs.escape_attr_value(bad)

    def test_the_shared_writer_escapes_through_it(self):
        # The escape is only worth anything if the ONE writer every re-serializer goes through
        # uses it. Pinned on the writer's own output so a later "simplification" back to
        # `html.escape` fails here rather than in one tool's suite.
        self.assertEqual(
            _browser_attrs.serialize_start_tag("section", [("title", "a\rb"), ("data-x", None)]),
            '<section title="a&#13;b" data-x="">')


class InputStreamPreprocessingTests(unittest.TestCase):
    """CMH-DECK-02: the RAW start-tag reading applies HTML's input-stream preprocessing.

    A browser folds every CR and CRLF to a single LF BEFORE it tokenizes, so no attribute value it
    holds carries a CR unless a character reference put one there. Applying the same fold at the
    read is what makes the write side's `CR -> &#13;` unconditional: without it the two spellings
    are indistinguishable downstream (both decode to `"\\r"`), and escaping a LITERAL CR - which a
    browser reads as LF - would write back a CR the input never meant.
    """

    def test_a_literal_cr_reads_as_an_lf(self):
        # Only a caller that reads with `newline=""` to preserve line endings can even present
        # one (`authoring/content_replace._read`, `authoring/upgrade._read`); a default
        # universal-newline read has already folded the whole file. Both CRLF and a LONE CR fold.
        pairs = dict(_browser_attrs.raw_attrs_pairs('title="a\r\nb\rc" id="x"'))
        self.assertEqual(pairs["title"], "a\nb\nc")
        self.assertEqual(pairs["id"], "x")

    def test_a_character_reference_cr_is_kept(self):
        # The other side of the same rule: preprocessing runs BEFORE tokenization, so a `&#13;` is
        # decoded after it and survives as a real CR. This is the one way a value can hold one.
        pairs = dict(_browser_attrs.raw_attrs_pairs('title="a&#13;b"'))
        self.assertEqual(pairs["title"], "a\rb")

    def test_a_literal_cr_round_trips_through_the_shared_writer_as_an_lf(self):
        # End to end, and the regression this pairing exists to prevent: a CRLF document read with
        # line endings preserved must come back out with the SAME value a browser saw - an LF, not
        # a `&#13;` that would hand the document a CR it never had.
        pairs = _browser_attrs.raw_attrs_pairs('title="a\r\nb" id="x"')
        written = _browser_attrs.serialize_start_tag("section", pairs)
        self.assertEqual(written, '<section title="a\nb" id="x">')
        self.assertNotIn("&#13;", written)

    def test_the_fold_reaches_every_quoting_form_and_the_tag_structure(self):
        # A CR is HTML whitespace, so folding it to LF must leave the SPLIT identical while fixing
        # the value - in all three quoting forms, and wherever else a CR can legally sit in a tag.
        # Pinning the structure is what rules out a fold that quietly merges or splits attributes.
        self.assertEqual(dict(_browser_attrs.raw_attrs_pairs("title='a\r\nb'"))["title"], "a\nb")
        self.assertEqual(dict(_browser_attrs.raw_attrs_pairs('a="1"\r\nb="2"')),
                         {"a": "1", "b": "2"})
        self.assertEqual(dict(_browser_attrs.raw_attrs_pairs('a=1\rb=2')), {"a": "1", "b": "2"})
        self.assertEqual(dict(_browser_attrs.raw_attrs_pairs('a="1"\r')), {"a": "1"})

    def test_the_degraded_reading_folds_the_same_way(self):
        # The partial-install split is a separate implementation, and this fix only holds if BOTH
        # readings answer the same thing - otherwise a degraded install writes a document a full
        # one would not. The fold lives in the wrapper precisely so it covers this path too.
        with _no_shared_reading():
            self.assertEqual(dict(_browser_attrs.raw_attrs_pairs('title="a\r\nb\rc"'))["title"],
                             "a\nb\nc")
            self.assertEqual(dict(_browser_attrs.raw_attrs_pairs('title="a&#13;b"'))["title"],
                             "a\rb")

    def test_the_shared_and_degraded_readings_agree_on_a_cr(self):
        # The parity the CMH-VAL-21 pinning tests assert for the rest of the reading, extended to
        # the fold: the tool, the validator's own shared reading, and the degraded stand-in must
        # not disagree about a document none of them may rewrite differently.
        for attrs in ('title="a\r\nb\rc"', "title='a\rb'", 'title="a&#13;b"', 'a=1\rb=2'):
            shared = parsing.raw_attrs_pairs(attrs)
            wrapped = _browser_attrs.raw_attrs_pairs(attrs)
            with _no_shared_reading():
                degraded = _browser_attrs.raw_attrs_pairs(attrs)
            self.assertEqual(wrapped, shared, attrs)
            self.assertEqual(degraded, shared, attrs)

    def test_a_second_pass_over_a_rewritten_tag_is_stable(self):
        # Both re-serializers can run repeatedly over the same document, so the rewrite has to
        # reach a FIXED POINT rather than drifting a value one spelling further on each pass.
        for attrs in ('title="a&#13;b"', 'title="a\r\nb"', 'title="a&#xD;&#10;b"',
                      'title="&amp;#13;"'):
            once = _browser_attrs.serialize_start_tag(
                "section", _browser_attrs.raw_attrs_pairs(attrs))
            twice = _browser_attrs.serialize_start_tag(
                "section", _browser_attrs.raw_attrs_pairs(once[len("<section"):-1]))
            self.assertEqual(twice, once, attrs)


if __name__ == "__main__":
    unittest.main()
