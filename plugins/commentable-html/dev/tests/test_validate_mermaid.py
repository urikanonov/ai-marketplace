#!/usr/bin/env python3
"""Tests for the mermaid syntax checker (cmhval/mermaid.py).

The differential test proves the shipped, dependency-free Python checker has ZERO
false positives: it loads the real-parser-labeled corpus in
`tests/fixtures/mermaid-corpus.json` (each entry's `valid` is stamped by the real
mermaid parser via `tools/validate_render.mjs`) and asserts the Python checker
flags an entry if and only if the entry is marked `py_flag`. Because `py_flag`
implies `valid == false` (enforced by the corpus generator) and every `valid`
entry has `py_flag == false`, a Python flag on a real-parser-valid diagram would
fail here.

Standard library only (unittest), matching the shipped tools.

    python -m unittest tests.test_validate_mermaid   # from plugins/commentable-html/dev
"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402
sys.path.insert(0, _paths.TOOLS)

import validate  # noqa: E402  (re-exports the mermaid checks)
from cmhval import mermaid as M  # noqa: E402

CORPUS = os.path.join(HERE, "fixtures", "mermaid-corpus.json")


def _flag(src):
    """True when the checker flags `src`."""
    return bool(M.check_mermaid_source(src))


class MermaidCorpusDifferential(unittest.TestCase):
    """CMH-SYN-03: the Python checker never contradicts the real parser in the
    false-positive direction, and catches every target bad case."""

    def setUp(self):
        with open(CORPUS, "r", encoding="utf-8") as fh:
            self.corpus = json.load(fh)
        self.assertGreaterEqual(len(self.corpus), 40, "corpus should be broad")

    def test_no_false_positives_and_catches_flagged(self):
        for entry in self.corpus:
            src = entry["src"]
            with self.subTest(name=entry["name"]):
                flagged = _flag(src)
                self.assertEqual(
                    flagged, entry["py_flag"],
                    "%s: expected py_flag=%s but checker %s" % (
                        entry["name"], entry["py_flag"],
                        "flagged" if flagged else "did not flag"))
                # A flag must never land on a real-parser-valid diagram.
                if entry["valid"]:
                    self.assertFalse(
                        flagged, "%s is valid per the real parser but was flagged "
                                 "(false positive)" % entry["name"])

    def test_every_flagged_entry_is_really_invalid(self):
        # Guards the corpus itself: nothing we flag may be valid per the real parser.
        for entry in self.corpus:
            if entry["py_flag"]:
                with self.subTest(name=entry["name"]):
                    self.assertFalse(
                        entry["valid"],
                        "%s is py_flag=true but labeled valid - regenerate the "
                        "corpus" % entry["name"])


class MermaidSequenceRule(unittest.TestCase):
    """CMH-SYN-01: a ';' that splits a sequence message into a dangling signal."""

    def test_flags_original_bug(self):
        src = ("sequenceDiagram\n"
               "  SEQ->>SEQ: validate against allowlist; map ActionType -> observation CLR type(s)")
        errs = M.check_mermaid_source(src)
        self.assertTrue(errs)
        self.assertIn("map ActionType -> observation CLR type(s)", errs[0])

    def test_valid_multi_signal_not_flagged(self):
        self.assertFalse(_flag("sequenceDiagram\n  A->>B: hi; C->>D: bye"))

    def test_arrow_in_message_without_semicolon_not_flagged(self):
        self.assertFalse(_flag("sequenceDiagram\n  A->>B: project observations -> TceBehaviorInfo"))

    def test_participant_alias_with_arrow_not_flagged(self):
        self.assertFalse(_flag('sequenceDiagram\n  participant A as "a->b"\n  A->>A: x'))

    def test_semicolon_then_keyword_not_flagged(self):
        self.assertFalse(_flag("sequenceDiagram\n  A->>B: hi; activate B"))

    def test_bare_word_tail_conservatively_skipped(self):
        # Invalid in mermaid, but not the arrow-without-colon class, so we do not
        # flag it (a safe false negative, never a false positive).
        self.assertFalse(_flag("sequenceDiagram\n  A->>B: hi; world"))


class MermaidFlowchartRule(unittest.TestCase):
    """CMH-SYN-02: an unbalanced double quote in a flowchart node label."""

    def test_flags_unbalanced_quote(self):
        self.assertTrue(_flag('flowchart TD\n  A["unterminated --> B'))

    def test_balanced_quotes_not_flagged(self):
        self.assertFalse(_flag('flowchart TD\n  A["one"] --> B["two"]'))

    def test_quot_escape_not_flagged(self):
        self.assertFalse(_flag('flowchart TD\n  A["say #quot;hi#quot;"] --> B'))

    def test_edge_label_quotes_not_flagged(self):
        self.assertFalse(_flag('flowchart LR\n  A -->|"yes"| B\n  A -->|"no"| C'))


class MermaidTypeGating(unittest.TestCase):
    """CMH-SYN-01/02: unknown or unhandled diagram types are never flagged."""

    def test_other_types_not_flagged(self):
        for src in (
            "classDiagram\n  Animal <|-- Dog",
            "erDiagram\n  A ||--o{ B : has",
            "gantt\n  title x\n  section s\n  t: a1, 2024-01-01, 1d",
            "pie title P\n  \"a\": 1",
            "wibbleDiagram\n  A -> B",  # unknown type: skip, never a false positive
        ):
            with self.subTest(src=src.split("\n")[0]):
                self.assertFalse(_flag(src))

    def test_rendered_block_skipped(self):
        # A block that already rendered to <svg> is not diagram source; skip it.
        class P:
            mermaid_blocks = [{"has_svg": True, "src_parts": ["not mermaid at all;;;"]}]
        errs, _ = M.check_mermaid_syntax(P())
        self.assertEqual(errs, [])


class MermaidWiredIntoValidate(unittest.TestCase):
    """CMH-SYN-01: validate() surfaces the mermaid syntax error end to end."""

    def test_validate_flags_broken_sequence_in_document(self):
        html = (
            '<pre class="mermaid cm-skip">sequenceDiagram\n'
            '  A-&gt;&gt;B: step one; then X -&gt; Y happens\n'
            '</pre>')
        parser, ok = validate._parse(html)
        self.assertTrue(ok)
        errs, _ = validate.check_mermaid_syntax(parser)
        self.assertTrue(errs)
        self.assertIn("Syntax error", errs[0])


if __name__ == "__main__":
    unittest.main()
