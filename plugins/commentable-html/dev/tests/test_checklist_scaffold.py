#!/usr/bin/env python3
"""CMH-CHECK-14: checklist_scaffold.py emits validator-clean list and table markup."""
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402
sys.path.insert(0, _paths.TOOLS)
import checklist_scaffold  # noqa: E402
import validate  # noqa: E402

OUTLINE = "Backend\n\tMigrations applied\n\t[x] Load test\nDocs updated\n"


def _wrap(inner):
    return "<!DOCTYPE html><html><body>" + inner + "</body></html>"


class ChecklistScaffoldTests(unittest.TestCase):
    def test_list_shape_ids_states_and_nesting(self):
        out = checklist_scaffold.scaffold(OUTLINE, "release", "Release readiness", "list")
        self.assertIn('data-cmh-checklist="release"', out)
        self.assertIn('data-cmh-checklist-label="Release readiness"', out)
        self.assertIn("<ul>", out)
        self.assertIn('data-cmh-item="backend"', out)
        self.assertRegex(out, r'data-cmh-item="migrations-applied"[^>]*data-cmh-state="blank"')
        self.assertRegex(out, r'data-cmh-item="load-test"[^>]*data-cmh-state="cross"')  # [x] -> cross
        branch = re.search(r'<li data-cmh-item="backend"[^>]*>', out).group(0)
        self.assertNotIn("data-cmh-state", branch)  # a branch derives its state

    def test_table_shape_uses_parent_links(self):
        out = checklist_scaffold.scaffold(OUTLINE, "audit", "Audit", "table")
        self.assertIn('<table class="cmh-checklist" data-cmh-checklist="audit"', out)
        self.assertRegex(out, r'data-cmh-item="migrations-applied"[^>]*data-cmh-parent="backend"')
        self.assertRegex(out, r'data-cmh-item="load-test"[^>]*data-cmh-parent="backend"')

    def test_scaffold_output_validates_clean(self):
        for shape in ("list", "table"):
            out = checklist_scaffold.scaffold(OUTLINE, "release", "Release", shape)
            errors, warnings = validate.check_checklists(_wrap(out))
            self.assertEqual(errors, [])
            self.assertEqual([w for w in warnings if "checklist" in w.lower() or "data-cmh" in w], [])

    def test_empty_outline_raises(self):
        with self.assertRaises(ValueError):
            checklist_scaffold.scaffold("   \n\n", "x", "", "list")


if __name__ == "__main__":
    unittest.main()
