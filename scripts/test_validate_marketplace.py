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


if __name__ == "__main__":
    unittest.main()
