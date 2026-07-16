#!/usr/bin/env python3
"""Compatibility runner for the split site-generator unit tests.

The real tests live in topic modules named ``test_build_site_data_*.py`` so
``python -m unittest discover -s scripts`` discovers them directly. Running this
file still executes the same topic modules for older local commands.
"""
import importlib
import unittest

_TEST_MODULES = [
    "test_build_site_data_rendering",
    "test_build_site_data_assets",
    "test_build_site_data_pages",

]


def load_tests(loader, tests, pattern):
    if __name__ != "__main__":
        return unittest.TestSuite()
    suite = unittest.TestSuite()
    for name in _TEST_MODULES:
        suite.addTests(loader.loadTestsFromModule(importlib.import_module(name)))
    return suite


if __name__ == "__main__":
    unittest.main()
