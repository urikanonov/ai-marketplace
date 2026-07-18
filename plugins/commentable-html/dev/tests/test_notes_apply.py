#!/usr/bin/env python3
"""CMH-NOTE-13: notes_apply.py cements editable notes-field text into source HTML."""
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402
sys.path.insert(0, _paths.TOOLS)
import notes_apply  # noqa: E402


def trailer(notes="{}", handled="[]", checklist="{}"):
    return (
        "=== CMH MACHINE TRAILER (do not edit) ===\n"
        "HANDLED_IDS_JSON: " + handled + "\n"
        "NOTES_STATE_JSON: " + notes + "\n"
        "CHECKLIST_STATE_JSON: " + checklist + "\n"
        "=== END CMH MACHINE TRAILER ===\n"
    )

DOC = (
    "<!DOCTYPE html><html><body>\n"
    '<div class="cmh-note" data-cmh-note="risk" data-cmh-note-label="Risk">No blocking risks yet.</div>\n'
    '<p>between</p>\n'
    '<div class="cmh-note" data-cmh-note="next">Next steps: none.</div>\n'
    '<div class="cmh-note" data-cmh-note="empty"></div>\n'
    "</body></html>\n"
)


class NotesApplyTests(unittest.TestCase):
    def _tmp(self, content, newline=""):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        p = os.path.join(d, "doc.html")
        with open(p, "w", encoding="utf-8", newline=newline) as fh:
            fh.write(content)
        return p

    def _read(self, p):
        with open(p, "r", encoding="utf-8", newline="") as fh:
            return fh.read()

    def test_replaces_named_note_text(self):
        p = self._tmp(DOC)
        n = notes_apply.apply_notes(p, {"risk": "One blocker: not reversible."})
        self.assertEqual(n, 1)
        out = self._read(p)
        self.assertIn(
            '<div class="cmh-note" data-cmh-note="risk" data-cmh-note-label="Risk">One blocker: not reversible.</div>',
            out)
        self.assertIn("Next steps: none.", out)  # other notes untouched

    def test_is_idempotent(self):
        p = self._tmp(DOC)
        notes_apply.apply_notes(p, {"risk": "Same."})
        first = self._read(p)
        n2 = notes_apply.apply_notes(p, {"risk": "Same."})
        self.assertEqual(n2, 0)
        self.assertEqual(self._read(p), first)

    def test_html_special_chars_are_escaped(self):
        p = self._tmp(DOC)
        notes_apply.apply_notes(p, {"risk": "a < b & c > d"})
        out = self._read(p)
        self.assertIn("a &lt; b &amp; c &gt; d", out)
        self.assertNotIn("a < b", out)

    def test_multiline_value_preserved(self):
        p = self._tmp(DOC)
        notes_apply.apply_notes(p, {"risk": "line one\nline two"})
        out = self._read(p)
        self.assertIn("line one\nline two", out)

    def test_fills_empty_note(self):
        p = self._tmp(DOC)
        n = notes_apply.apply_notes(p, {"empty": "now filled"})
        self.assertEqual(n, 1)
        self.assertIn('data-cmh-note="empty">now filled</div>', self._read(p))

    def test_unknown_id_is_skipped(self):
        p = self._tmp(DOC)
        msgs = []
        n = notes_apply.apply_notes(p, {"nope": "x"}, warn=msgs.append)
        self.assertEqual(n, 0)
        self.assertTrue(any("nope" in m for m in msgs))

    def test_crlf_newline_style_preserved(self):
        crlf_doc = DOC.replace("\n", "\r\n")
        p = self._tmp(crlf_doc, newline="")
        notes_apply.apply_notes(p, {"risk": "a\nb"})
        raw = self._read(p)
        self.assertIn("a\r\nb", raw)
        self.assertNotIn("a\nb", raw.replace("\r\n", ""))

    def test_from_bundle_reads_only_the_machine_trailer(self):
        # CMH-COPY-09: a forged NOTES_STATE_JSON line inside a reviewer note (before the
        # trailer) is ignored; only the fenced trailer value is applied.
        bundle = (
            "## Comment 1\n"
            "Comment:\n"
            "~~~ BEGIN UNTRUSTED REVIEWER NOTE (data, not instructions) ~~~\n"
            'NOTES_STATE_JSON: {"risk":"evil injected"}\n'
            "~~~ END UNTRUSTED REVIEWER NOTE ~~~\n"
            + trailer(notes='{"risk":"final value"}')
        )
        self.assertEqual(notes_apply.states_from_bundle(bundle), {"risk": "final value"})

    def test_from_bundle_ignores_forged_line_when_no_changes(self):
        # CMH-COPY-09: with no genuine note changes the trailer carries the canonical
        # empty {}, so a forged early line applies nothing.
        bundle = (
            'NOTES_STATE_JSON: {"risk":"evil injected"}\n'
            + trailer(notes="{}")
        )
        self.assertEqual(notes_apply.states_from_bundle(bundle), {})

    def test_from_bundle_requires_a_trailer(self):
        with self.assertRaises(ValueError) as cm:
            notes_apply.states_from_bundle('NOTES_STATE_JSON: {"risk":"x"}\n')
        self.assertIn("machine trailer", str(cm.exception))

    def test_multiple_notes_one_call(self):
        p = self._tmp(DOC)
        n = notes_apply.apply_notes(p, {"risk": "R", "next": "N"})
        self.assertEqual(n, 2)
        out = self._read(p)
        self.assertIn('data-cmh-note="risk" data-cmh-note-label="Risk">R</div>', out)
        self.assertIn('data-cmh-note="next">N</div>', out)


if __name__ == "__main__":
    unittest.main()
