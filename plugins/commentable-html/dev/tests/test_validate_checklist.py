#!/usr/bin/env python3
"""CMH-CHECK-15: validate.py flags checklist authoring mistakes (all as strict-escalated
warnings, and a no-op for checklist-free documents)."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402
sys.path.insert(0, _paths.TOOLS)
import validate  # noqa: E402


def _wrap(inner):
    return "<!DOCTYPE html><html><body>" + inner + "</body></html>"


class ChecklistValidateTests(unittest.TestCase):
    def test_clean_checklist_has_no_warnings(self):
        inner = ('<div class="cmh-checklist" data-cmh-checklist="a"><ul>'
                 '<li data-cmh-item="x" data-cmh-state="check">X</li></ul></div>')
        errors, warnings = validate.check_checklists(_wrap(inner))
        self.assertEqual(errors, [])
        self.assertEqual([w for w in warnings if "checklist" in w.lower()], [])

    def test_duplicate_container_id(self):
        inner = ('<div class="cmh-checklist" data-cmh-checklist="dup"><ul><li data-cmh-item="a">A</li></ul></div>'
                 '<div class="cmh-checklist" data-cmh-checklist="dup"><ul><li data-cmh-item="b">B</li></ul></div>')
        _, w = validate.check_checklists(_wrap(inner))
        self.assertTrue(any("appears on 2 containers" in x for x in w), w)

    def test_invalid_state_token(self):
        inner = ('<div class="cmh-checklist" data-cmh-checklist="a"><ul>'
                 '<li data-cmh-item="x" data-cmh-state="bogus">X</li></ul></div>')
        _, w = validate.check_checklists(_wrap(inner))
        self.assertTrue(any("invalid data-cmh-state" in x for x in w), w)

    def test_empty_checklist(self):
        _, w = validate.check_checklists(_wrap('<div class="cmh-checklist" data-cmh-checklist="a"></div>'))
        self.assertTrue(any("has no items" in x for x in w), w)

    def test_unresolved_parent(self):
        inner = ('<table class="cmh-checklist" data-cmh-checklist="a"><tbody>'
                 '<tr data-cmh-item="x" data-cmh-parent="ghost"><td></td><td>X</td></tr></tbody></table>')
        _, w = validate.check_checklists(_wrap(inner))
        self.assertTrue(any("does not resolve" in x for x in w), w)

    def test_duplicate_item_id(self):
        inner = ('<div class="cmh-checklist" data-cmh-checklist="a"><ul>'
                 '<li data-cmh-item="x">A</li><li data-cmh-item="x">B</li></ul></div>')
        _, w = validate.check_checklists(_wrap(inner))
        self.assertTrue(any('duplicate data-cmh-item id "x"' in x for x in w), w)

    def test_no_checklist_is_noop(self):
        self.assertEqual(validate.check_checklists(_wrap("<p>hello</p>")), ([], []))


if __name__ == "__main__":
    unittest.main()
