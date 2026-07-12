#!/usr/bin/env python3
"""Tests for scripts/validate_marketplace.py."""

import importlib.util
import os
import unittest

_MODULE_PATH = os.path.join(os.path.dirname(__file__), "validate_marketplace.py")
_spec = importlib.util.spec_from_file_location("validate_marketplace", _MODULE_PATH)
vm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vm)


class TestWalkOrdering(unittest.TestCase):
    def test_sorts_directory_and_file_names_in_place(self):
        dirnames = ["zeta", "alpha", "middle"]
        filenames = ["z.json", "a.json", "m.json"]

        vm._sort_walk_entries(dirnames, filenames)

        self.assertEqual(dirnames, ["alpha", "middle", "zeta"])
        self.assertEqual(filenames, ["a.json", "m.json", "z.json"])


class TestEntryPluginParityErrors(unittest.TestCase):
    def _entry(self):
        return {"description": "same description", "keywords": ["alpha", "beta"]}

    def _plugin_json(self):
        return {"description": "same description", "keywords": ["alpha", "beta"]}

    def test_in_sync_entry_has_no_errors(self):
        self.assertEqual(vm.entry_plugin_parity_errors("sample", self._entry(), self._plugin_json()), [])

    def test_keyword_set_mismatch_reports_one_error(self):
        entry = self._entry()
        pj = self._plugin_json()
        pj["keywords"] = ["alpha", "gamma"]

        self.assertEqual(
            vm.entry_plugin_parity_errors("sample", entry, pj),
            ["sample: manifest keywords ['alpha', 'beta'] != plugin.json keywords ['alpha', 'gamma']"],
        )

    def test_keyword_order_does_not_matter(self):
        entry = self._entry()
        pj = self._plugin_json()
        pj["keywords"] = ["beta", "alpha", "alpha"]

        self.assertEqual(vm.entry_plugin_parity_errors("sample", entry, pj), [])

    def test_description_mismatch_reports_one_error(self):
        entry = self._entry()
        pj = self._plugin_json()
        pj["description"] = "different description"

        self.assertEqual(
            vm.entry_plugin_parity_errors("sample", entry, pj),
            [
                "sample: manifest description 'same description' != "
                "plugin.json description 'different description'"
            ],
        )

    def test_missing_field_reports_error(self):
        entry = self._entry()
        pj = self._plugin_json()
        del pj["keywords"]

        self.assertEqual(
            vm.entry_plugin_parity_errors("sample", entry, pj),
            ["sample: manifest keywords ['alpha', 'beta'] != plugin.json keywords <missing>"],
        )


if __name__ == "__main__":
    unittest.main()
