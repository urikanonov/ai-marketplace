#!/usr/bin/env python3
"""Cross-implementation parity for the syntax highlighter (GH-REGRESS-HIGHLIGHT-PARITY).

The author-time Python tool (highlight_code.py) and the runtime JS diff highlighter
(cmhHighlightCode in assets/commentable-html.js) are parallel reimplementations of the same
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


if __name__ == "__main__":
    unittest.main()
