#!/usr/bin/env python3
"""Tests for the shared highlight core: a lossless inverse of the token-span emitters.

Covers CMH-HL-09 (dehighlight is a left inverse of highlight), CMH-HL-10 (the strict
single-pass scanner refuses anything outside the generated grammar instead of
corrupting it), and CMH-HL-11 (both emitters share one emission point, so the
inverse provably covers every language including KQL).
"""
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402  shared pkg/dev split path constants
TOOLS = _paths.TOOLS
sys.path.insert(0, TOOLS)
import _highlight_core as C  # noqa: E402
import highlight_code as H  # noqa: E402
import kql_highlight as K  # noqa: E402


# Sources chosen to stress escaping, not to look realistic: each carries at least one
# character or sequence that a naive strip-and-unescape would corrupt.
ADVERSARIAL = {
    "python": [
        'def run(x):\n    return x + 1\n',
        's = "a < b & c > d"\n',
        's = "</span> literal inside a string"\n',
        's = "already &amp; escaped"\n',
        's = "&lt;pre&gt; entity soup"\n',
        'u = "caf\u00e9 \u2603 \U0001f600"\n',
        'def f():\n    """A docstring\n    spanning lines\n    """\n    return 1\n',
        's = "tab\there"\n',
        'x = 1\n\n\n\ny = 2\n',
    ],
    "javascript": [
        'const a = `template ${x} </span>`;\n',
        'const re = /<[a-z]+>/g;\n',
        '/* block\n   comment\n   lines */\nconst a = 1;\n',
    ],
    "html": ['<div class="x">&amp;</div>\n'],
    "xml": ['<a b="&amp;">t</a>\n'],
    "json": ['{"k": "<v> & \\"q\\""}\n'],
    "bash": ['echo "<a> & b" | grep -o "</span>"\n'],
    "sql": ["SELECT * FROM t WHERE a < 1 AND b > '&';\n"],
    "go": ['s := "<x> & </span>"\n'],
    "yaml": ['key: "<v> & x"\n'],
}

KQL_SOURCES = [
    'StormEvents | where State == "<TX>" and Deaths > 1\n',
    'T | where s == "</span>"\n',
    'T | where s == "a & b"\n',
    '// comment with <tag>\nT | count\n',
    'T\n| where s == @"multi\nline"\n| count\n',
    'T | mv-expand x | summarize count() by y\n',
]

# Broad snippets used only to sweep the emitters for every token kind they can produce,
# so the allowlist guard is driven by real output rather than a hand-kept list.
_KIND_PROBE_SOURCES = [
    'def f(a=1):\n  """d"""\n  # c\n  return "s" + f"{a}"\n',
    '{"k": 1, "b": true} // c\n/* x */\n',
    '<a b="c">&amp;</a>\n',
    "SELECT a FROM t WHERE x=1; -- c\n",
    "const a=`t${x}`; /*c*/ // l\nlet re=/x/g;\n",
    "# H\n*em* `c` [l](u)\n- i\n1. n\n```py\nx=1\n```\n",
    'package main\nfunc f() { s := "x" }\n',
    'a: 1 # c\nb: "s"\n',
    "class A { void f() { int i = 0; } }\n",
    "fn main(){ let x: i32 = 1; }\n",
    "#include <s.h>\nint m(){return 0;}\n",
]

_KQL_KIND_PROBE_SOURCES = [
    'T | where a=="s" and n>1 | summarize count() by x // c\n',
    'T | mv-expand y | project @"v" | take 10\n',
    'StormEvents | where State=="TX" | extend f=strcat("a","b")\n',
]


class DehighlightLeftInverseTests(unittest.TestCase):
    """CMH-HL-09: dehighlight recovers the source the highlighter was given."""

    def test_code_round_trip_recovers_normalized_source(self):
        for lang, sources in ADVERSARIAL.items():
            norm = H._normalize_language(lang)
            if norm not in H.LANGUAGE_CONFIGS:
                continue
            for src in sources:
                with self.subTest(lang=lang, src=src):
                    inner = H.highlight_code(norm, src)
                    self.assertEqual(C.dehighlight(inner), C.normalize_newlines(src))

    def test_kql_round_trip_recovers_normalized_source(self):
        for src in KQL_SOURCES:
            with self.subTest(src=src):
                inner = K.highlight_inner(src)
                self.assertEqual(C.dehighlight(inner), C.normalize_newlines(src))

    def test_crlf_is_normalized_not_preserved(self):
        # The emitters normalize newlines, so the inverse is a LEFT inverse over the
        # normalized domain. Pin that explicitly so the contract is not mistaken for
        # byte-exact recovery of arbitrary input.
        inner = H.highlight_code("python", "x = 1\r\ny = 2\r\n")
        self.assertEqual(C.dehighlight(inner), "x = 1\ny = 2\n")

    def test_rehighlight_of_stored_content_is_byte_identical(self):
        # The invariant the review loop actually depends on: content already stored
        # highlighted survives dehighlight -> rehighlight unchanged, so an untouched
        # block never churns bytes.
        for lang, sources in ADVERSARIAL.items():
            norm = H._normalize_language(lang)
            if norm not in H.LANGUAGE_CONFIGS:
                continue
            for src in sources:
                with self.subTest(lang=lang, src=src):
                    stored = H.highlight_code(norm, src)
                    again = H.highlight_code(norm, C.dehighlight(stored))
                    self.assertEqual(again, stored)

    def test_kql_rehighlight_of_stored_content_is_byte_identical(self):
        for src in KQL_SOURCES:
            with self.subTest(src=src):
                stored = K.highlight_inner(src)
                again = K.highlight_inner(C.dehighlight(stored))
                self.assertEqual(again, stored)

    def test_empty_and_whitespace_only_blocks(self):
        for src in ("", "\n", "   \n", "\t\n"):
            with self.subTest(src=src):
                inner = H.highlight_code("python", src)
                self.assertEqual(C.dehighlight(inner), C.normalize_newlines(src))


class StrictScannerTests(unittest.TestCase):
    """CMH-HL-10: anything outside the generated grammar is refused, never corrupted."""

    def test_nested_spans_are_refused_not_unwound(self):
        # A loop-based stripper would silently flatten this and hand back corrupted
        # source. The single-pass scanner must refuse it instead.
        nested = ('<span class="cmh-code-str">"'
                  '<span class="cmh-code-esc">\\n</span>"</span>')
        self.assertIsNone(C.dehighlight(nested))
        self.assertEqual(C.classify(nested), "hand-written")

    def test_author_markup_is_refused(self):
        for inner in ('<span class="cmh-code-kw">def</span> <mark>run</mark>',
                      '<span class="cmh-code-kw">def</span> <span class="note">x</span>',
                      'plain <a href="#x">link</a>',
                      '<span class="cmh-code-kw">def</span> <?pi?>'):
            with self.subTest(inner=inner):
                self.assertIsNone(C.dehighlight(inner))
                self.assertEqual(C.classify(inner), "hand-written")

    def test_malformed_span_is_refused(self):
        # The exact case that ships silently today: an agent edited a highlighted block
        # and left a truncated span behind.
        for inner in ('<span class="cmh-code-kw">def run',
                      '<span class="cmh-code-kw">def</span></span>',
                      '<span class="cmh-code-kw" data-x="1">def</span>'):
            with self.subTest(inner=inner):
                self.assertIsNone(C.dehighlight(inner))

    def test_unknown_token_class_is_refused(self):
        # An unknown FAMILY and an unknown KIND within a known family are both refused:
        # the allowlist is exact, so dehighlight never rewrites a class it did not write.
        self.assertIsNone(C.dehighlight('<span class="cmh-other-kw">x</span>'))
        self.assertIsNone(C.dehighlight('<span class="cmh-code-404">x</span>'))
        self.assertIsNone(C.dehighlight('<span class="cmh-code-bogus">x</span>'))
        self.assertIsNone(C.dehighlight('<span class="cmh-kql-key">x</span>'))

    def test_non_canonical_escaping_is_refused(self):
        # The emitters only ever write &amp;, &lt; and &gt;. Anything else is
        # hand-authored, and decoding it would silently rewrite the author's content.
        for inner in ('<span class="cmh-code-str">&quot;</span>',
                      "&#x3C;",
                      "&#60;",
                      "caf&eacute;",
                      "bare & ampersand",
                      "&amp"):
            with self.subTest(inner=inner):
                self.assertIsNone(C.dehighlight(inner))
                self.assertEqual(C.classify(inner), "hand-written")

    def test_double_application_is_refused_rather_than_corrupting(self):
        # dehighlight ends in an unescape, so applying it twice would decode source that
        # legitimately contains &amp;. The canonical-escaping check catches that.
        once = C.dehighlight(H.highlight_code("python", 's = "a & b"\n'))
        self.assertEqual(once, 's = "a & b"\n')
        self.assertIsNone(C.dehighlight(once))

    def test_entity_bearing_source_still_round_trips(self):
        # The stricter check must not reject legitimate source that CONTAINS entity text.
        for src in ('s = "already &amp; escaped"\n', 's = "&lt;pre&gt;"\n', 's = "a & b"\n'):
            with self.subTest(src=src):
                inner = H.highlight_code("python", src)
                self.assertEqual(C.dehighlight(inner), src)

    def test_raw_escaped_text_is_accepted(self):
        self.assertEqual(C.dehighlight("plain &amp; text &lt;here&gt;"), "plain & text <here>")
        self.assertEqual(C.classify("plain &amp; text"), "raw")

    def test_highlighted_content_classifies_as_highlighted(self):
        inner = H.highlight_code("python", "x = 1\n")
        self.assertEqual(C.classify(inner), "highlighted")


class FlatnessTests(unittest.TestCase):
    """CMH-HL-11: the emitters are flat and share one emission point."""

    def test_emitter_output_is_never_nested(self):
        # Flatness is what makes the regex inverse safe. Pin it so a future tokenizer
        # change that introduces nesting fails here rather than silently breaking
        # dehighlight for every caller.
        for lang, sources in ADVERSARIAL.items():
            norm = H._normalize_language(lang)
            if norm not in H.LANGUAGE_CONFIGS:
                continue
            for src in sources:
                with self.subTest(lang=lang, src=src):
                    self.assertTrue(C.is_flat(H.highlight_code(norm, src)))
        for src in KQL_SOURCES:
            with self.subTest(src=src):
                self.assertTrue(C.is_flat(K.highlight_inner(src)))

    def test_both_emitters_use_the_shared_span(self):
        self.assertIs(H._esc, C.esc)
        self.assertIs(K._esc, C.esc)

    def test_the_kind_allowlist_covers_every_kind_the_emitters_emit(self):
        # The allowlist is what makes an unknown kind refusable. If a tokenizer gains a
        # kind and nobody lists it, dehighlight would start refusing real blocks - so
        # fail here instead, at the point the kind was added.
        seen_code, seen_kql = set(), set()
        for lang in sorted(H.LANGUAGE_CONFIGS):
            for src in _KIND_PROBE_SOURCES:
                inner = H.highlight_code(lang, src)
                seen_code |= set(re.findall(r'class="cmh-code-([a-z0-9]+)"', inner))
        for src in KQL_SOURCES + _KQL_KIND_PROBE_SOURCES:
            inner = K.highlight_inner(src)
            seen_kql |= set(re.findall(r'class="cmh-kql-([a-z0-9]+)"', inner))
        self.assertTrue(seen_code, "probe produced no code tokens")
        self.assertTrue(seen_kql, "probe produced no kql tokens")
        self.assertEqual(seen_code - C.CODE_KINDS, set())
        self.assertEqual(seen_kql - C.KQL_KINDS, set())

    def test_unesc_is_the_exact_inverse_of_esc(self):
        for text in ("a & b", "<x>", "&amp;lt;", "&", "&&&", "", "a\nb", '"q" \'s\''):
            with self.subTest(text=text):
                self.assertEqual(C.unesc(C.esc(text)), text)

    def test_markdown_fuzz_stays_flat_and_reversible(self):
        # markdown is the most complex tokenizer, so exercise it hardest.
        if "markdown" not in H.LANGUAGE_CONFIGS:
            self.skipTest("markdown not supported")
        samples = [
            "# Head\n\nSome *em* and `code` and [l](http://x)\n",
            "- a\n- b\n\n```python\nx = 1\n```\n",
            "> quote & <tag>\n\n| a | b |\n| - | - |\n",
            "text with </span> and &amp; entities\n",
        ]
        for src in samples:
            with self.subTest(src=src):
                inner = H.highlight_code("markdown", src)
                self.assertTrue(C.is_flat(inner))
                self.assertEqual(C.dehighlight(inner), C.normalize_newlines(src))


if __name__ == "__main__":
    unittest.main()
