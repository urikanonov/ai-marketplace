#!/usr/bin/env python3
"""CMH-CHECK-13: checklist_apply.py cements checklist states into source HTML."""
import os
import re
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402
sys.path.insert(0, _paths.TOOLS)
import checklist_apply  # noqa: E402

LIST_DOC = (
    "<!DOCTYPE html><html><body>\n"
    '<div class="cmh-checklist" data-cmh-checklist="release" data-cmh-checklist-label="Release">\n'
    "  <ul>\n"
    '    <li data-cmh-item="backend" data-cmh-state="blank">Backend\n'
    "      <ul>\n"
    '        <li data-cmh-item="mig" data-cmh-state="check">Migrations</li>\n'
    '        <li data-cmh-item="load" data-cmh-state="check">Load</li>\n'
    "      </ul>\n"
    "    </li>\n"
    '    <li data-cmh-item="rel" data-cmh-state="blank">Release notes</li>\n'
    "  </ul>\n"
    "</div>\n"
    "</body></html>\n"
)


class ChecklistApplyTests(unittest.TestCase):
    def _tmp(self, content):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        p = os.path.join(d, "doc.html")
        with open(p, "w", encoding="utf-8", newline="") as fh:
            fh.write(content)
        return p

    def test_applies_states_from_map(self):
        p = self._tmp(LIST_DOC)
        n = checklist_apply.apply_states(p, {"release": {"rel": "check", "load": "cross"}})
        self.assertEqual(n, 2)
        html = open(p, encoding="utf-8").read()
        self.assertRegex(html, r'data-cmh-item="rel"[^>]*data-cmh-state="check"')
        self.assertRegex(html, r'data-cmh-item="load"[^>]*data-cmh-state="cross"')
        self.assertRegex(html, r'data-cmh-item="mig"[^>]*data-cmh-state="check"')  # untouched

    def test_idempotent(self):
        p = self._tmp(LIST_DOC)
        checklist_apply.apply_states(p, {"release": {"rel": "check"}})
        self.assertEqual(checklist_apply.apply_states(p, {"release": {"rel": "check"}}), 0)

    def test_from_bundle_parses_state_line(self):
        bundle = 'noise\nCHECKLIST_STATE_JSON: {"release":{"rel":"question"}}\nmore\n'
        self.assertEqual(checklist_apply.states_from_bundle(bundle), {"release": {"rel": "question"}})

    def test_positional_key_without_item_id(self):
        doc = ('<div class="cmh-checklist" data-cmh-checklist="c"><ul>'
               '<li data-cmh-state="blank">A</li><li data-cmh-state="blank">B</li></ul></div>')
        p = self._tmp(doc)
        n = checklist_apply.apply_states(p, {"c": {"2": "check"}})
        self.assertEqual(n, 1)
        lis = re.findall(r"<li[^>]*>", open(p, encoding="utf-8").read())
        self.assertIn('data-cmh-state="check"', lis[1])
        self.assertNotIn('data-cmh-state="check"', lis[0])

    def test_invalid_token_is_skipped(self):
        p = self._tmp(LIST_DOC)
        n = checklist_apply.apply_states(p, {"release": {"rel": "bogus"}}, warn=lambda m: None)
        self.assertEqual(n, 0)

    def test_inserts_state_when_absent(self):
        doc = '<div class="cmh-checklist" data-cmh-checklist="c"><ul><li data-cmh-item="z">Z</li></ul></div>'
        p = self._tmp(doc)
        n = checklist_apply.apply_states(p, {"c": {"z": "cross"}})
        self.assertEqual(n, 1)
        self.assertRegex(open(p, encoding="utf-8").read(), r'data-cmh-item="z"[^>]*data-cmh-state="cross"')


if __name__ == "__main__":
    unittest.main()
