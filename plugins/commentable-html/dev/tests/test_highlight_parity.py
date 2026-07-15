#!/usr/bin/env python3
"""Cross-implementation parity for the syntax highlighter (GH-REGRESS-HIGHLIGHT-PARITY).

The author-time Python tool (highlight_code.py) and the runtime JS diff highlighter
(cmhHighlightCode in assets/js/26-highlight.js) are parallel reimplementations of the same
tokenizer. They can drift silently - the PR #33 regression (single quotes swallowing Rust
lifetimes, YAML apostrophes, C++ digit separators as strings) had to be fixed in both. This test
pins the PYTHON side to the shared fixture tests/fixtures/highlight_parity.json; tests/57-highlight-parity.spec.js
pins the RUNTIME side to the SAME fixture, so a divergence fails one of the two suites.
"""
import html
import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402
TOOLS = _paths.TOOLS
sys.path.insert(0, TOOLS)
import highlight_code as H  # noqa: E402

PARITY_FIXTURE = os.path.join(HERE, "fixtures", "highlight_parity.json")
SPAN_RE = re.compile(r'<span class="cmh-code-([a-z]+)">(.*?)</span>', re.S)
HIGHLIGHT_JS = os.path.join(_paths.ASSETS, "js", "26-highlight.js")
# A key inside the _HL_FAMILY object literal: a bareword (javascript) or a quoted token ("c++")
# immediately before a colon. Values ("c", "hash") never precede a colon, so they are not captured.
_HL_FAMILY_KEY_RE = re.compile(r'("[^"]+"|[A-Za-z_$][A-Za-z0-9_$+.#-]*)\s*:')


def runtime_known_languages():
    """The set of language labels the runtime tokenizer knows (keys of _HL_FAMILY in
    assets/js/26-highlight.js). diffLangKnown() gates both the diff highlighter and the
    runtime fallback on membership in this set."""
    with open(HIGHLIGHT_JS, "r", encoding="utf-8") as fh:
        src = fh.read()
    m = re.search(r"const _HL_FAMILY\s*=\s*\{(.*?)\};", src, re.S)
    assert m, "could not locate the _HL_FAMILY object literal in 26-highlight.js"
    keys = set()
    for km in _HL_FAMILY_KEY_RE.finditer(m.group(1)):
        key = km.group(1)
        if key.startswith('"'):
            key = key[1:-1]
        keys.add(key.lower())
    return keys


def classes_to_text(inner_html):
    """Return {class: concatenated unescaped text} for every cmh-code-* span in the output."""
    out = {}
    for cls, body in SPAN_RE.findall(inner_html):
        out.setdefault(cls, "")
        out[cls] += html.unescape(body)
    return out


def load_cases():
    with open(PARITY_FIXTURE, "r", encoding="utf-8") as fh:
        return json.load(fh)["cases"]


class HighlightParityPythonTests(unittest.TestCase):
    def test_python_tool_matches_the_shared_parity_fixture(self):
        for case in load_cases():
            lang, code = case["lang"], case["code"]
            spans = classes_to_text(H.highlight_code(lang, code))
            with self.subTest(lang=lang, code=code):
                for tok in case.get("str", []):
                    self.assertIn(tok, spans.get("str", ""),
                                  "%s: %r should be a string token" % (lang, tok))
                for tok in case.get("com", []):
                    self.assertIn(tok, spans.get("com", ""),
                                  "%s: %r should be a comment token" % (lang, tok))
                for tok in case.get("kw", []):
                    self.assertIn(tok, spans.get("kw", ""),
                                  "%s: %r should be a keyword token" % (lang, tok))
                for tok in case.get("notStr", []):
                    self.assertNotIn(tok, spans.get("str", ""),
                                     "%s: %r must NOT be swallowed as a string" % (lang, tok))


class RuntimeLanguageCoverageTests(unittest.TestCase):
    def test_runtime_knows_every_author_time_language(self):
        # CMH-HL-03: the runtime tokenizer (diffLangKnown / _HL_FAMILY) must know every language the
        # author-time highlighter supports (highlight_code.LANGUAGE_CONFIGS). Otherwise a supported
        # language that was authored raw renders monochrome at runtime, because the runtime fallback
        # (highlightCodeBlocks, CMH-HL-01) and the diff highlighter only fire for a known language.
        # This guard fails the moment an author-time language is added without runtime coverage.
        known = runtime_known_languages()
        missing = sorted(set(H.LANGUAGE_CONFIGS) - known)
        self.assertEqual(missing, [],
                         "runtime _HL_FAMILY must cover every author-time language; missing: %r "
                         "(add them to _HL_FAMILY in assets/js/26-highlight.js)" % missing)


if __name__ == "__main__":
    unittest.main()
