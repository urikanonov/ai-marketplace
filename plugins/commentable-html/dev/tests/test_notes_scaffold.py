#!/usr/bin/env python3
"""CMH-NOTE-14: notes_scaffold.py emits validator-clean data-cmh-note markup."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402
sys.path.insert(0, _paths.TOOLS)
import notes_scaffold  # noqa: E402
from checks.notes import check_notes  # noqa: E402


class NotesScaffoldTests(unittest.TestCase):
    def test_emits_id_label_and_escaped_text(self):
        out = notes_scaffold.scaffold("risk-summary", "Reviewer risk summary",
                                      "No blocking risks yet.")
        self.assertIn('class="cmh-note"', out)
        self.assertIn('data-cmh-note="risk-summary"', out)
        self.assertIn('data-cmh-note-label="Reviewer risk summary"', out)
        self.assertIn("No blocking risks yet.", out)
        self.assertTrue(out.endswith("\n"))

    def test_escapes_html_in_text_and_label(self):
        out = notes_scaffold.scaffold("n", 'A & B <tag>', 'x < y & z')
        self.assertNotIn("<tag>", out)
        self.assertIn("&lt;tag&gt;", out)
        self.assertIn("x &lt; y &amp; z", out)

    def test_multiline_flag_adds_attribute(self):
        out = notes_scaffold.scaffold("n", "", "seed", multiline=True)
        self.assertIn('data-cmh-note-multiline="true"', out)
        plain = notes_scaffold.scaffold("n", "", "seed")
        self.assertNotIn("data-cmh-note-multiline", plain)

    def test_foldable_flag_adds_attribute(self):
        out = notes_scaffold.scaffold("n", "", "seed", foldable=True)
        self.assertIn('data-cmh-note-foldable="true"', out)
        plain = notes_scaffold.scaffold("n", "", "seed")
        self.assertNotIn("data-cmh-note-foldable", plain)
        # A foldable note is still validator-clean.
        doc = "<!DOCTYPE html><html><body>%s</body></html>" % out
        errors, warnings = check_notes(doc)
        self.assertEqual((errors, warnings), ([], []))

    def test_output_is_validator_clean(self):
        out = notes_scaffold.scaffold("risk", "Risk", "No blocking risks yet.")
        doc = "<!DOCTYPE html><html><body>%s</body></html>" % out
        errors, warnings = check_notes(doc)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_bad_id_is_rejected(self):
        self.assertEqual(notes_scaffold.main(["notes_scaffold.py", "--id", "bad id"]), 1)
        self.assertEqual(notes_scaffold.main(["notes_scaffold.py", "--id", "ok-id", "--text", "hi"]), 0)


if __name__ == "__main__":
    unittest.main()
