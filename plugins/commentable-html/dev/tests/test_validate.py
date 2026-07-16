#!/usr/bin/env python3
"""Compatibility imports for the split validate.py regression suite.

The tests that used to live here are now auto-discovered from focused
``test_validate_<topic>.py`` modules in this directory. Shared fixtures remain
importable from this module for older sibling tests.
"""

from _validate_helpers import *  # noqa: F401,F403


if __name__ == "__main__":
    import unittest

    unittest.main(module=None)
