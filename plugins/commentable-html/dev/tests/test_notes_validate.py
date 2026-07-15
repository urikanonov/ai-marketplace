#!/usr/bin/env python3
"""CMH-NOTE-15: validate.py flags notes-field authoring mistakes (strict-escalated warnings)."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402
sys.path.insert(0, _paths.TOOLS)
from checks.notes import check_notes  # noqa: E402


def _wrap(body):
    return "<!DOCTYPE html><html><body>%s</body></html>" % body


class NotesValidateTests(unittest.TestCase):
    def test_clean_note_has_no_warnings(self):
        e, w = check_notes(_wrap('<div data-cmh-note="a">text</div>'))
        self.assertEqual(e, [])
        self.assertEqual(w, [])

    def test_no_op_when_note_free(self):
        e, w = check_notes(_wrap('<p>ordinary content</p>'))
        self.assertEqual((e, w), ([], []))

    def test_duplicate_ids_flagged(self):
        e, w = check_notes(_wrap('<div data-cmh-note="a">x</div><div data-cmh-note="a">y</div>'))
        self.assertTrue(any("appears on 2" in m for m in w))

    def test_empty_id_flagged(self):
        e, w = check_notes(_wrap('<div data-cmh-note="">x</div>'))
        self.assertTrue(any("empty id" in m for m in w))

    def test_nested_note_flagged(self):
        e, w = check_notes(_wrap('<div data-cmh-note="outer">a<span data-cmh-note="inner">b</span></div>'))
        self.assertTrue(any("must not nest" in m for m in w))

    def test_void_note_flagged(self):
        e, w = check_notes(_wrap('<input data-cmh-note="v">'))
        self.assertTrue(any("void element" in m for m in w))

    def test_child_element_flagged(self):
        e, w = check_notes(_wrap('<div data-cmh-note="a">hi <b>bold</b></div>'))
        self.assertTrue(any("plain text only" in m for m in w))

    def test_note_inside_checklist_flagged(self):
        body = ('<div data-cmh-checklist="c"><ul><li data-cmh-item="i">'
                '<div data-cmh-note="n">x</div></li></ul></div>')
        e, w = check_notes(_wrap(body))
        self.assertTrue(any("substrate" in m for m in w))


if __name__ == "__main__":
    unittest.main()
