#!/usr/bin/env python3
"""Compatibility runner for the split validator tests.

Pytest discovers the topic modules named ``test_validate_*.py`` directly. Running
this file as a script still executes those modules through unittest discovery.
"""
import importlib
import unittest

from validate_test_support import *  # noqa: F401,F403
import validate_test_support as _support
globals().update({k: v for k, v in vars(_support).items() if k.startswith("_") and not k.startswith("__")})

_TEST_MODULES = [
    "test_validate_core",
    "test_validate_nonportable",
    "test_validate_cli",

]


def _suite():
    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite()
    for name in _TEST_MODULES:
        suite.addTests(loader.loadTestsFromModule(importlib.import_module(name)))
    return suite


if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2)
    raise SystemExit(0 if runner.run(_suite()).wasSuccessful() else 1)
