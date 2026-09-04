#!/usr/bin/env python3
"""Tests for environment isolation used by the commentable-html test suite."""
import os
import unittest

import _test_env


class PatchedEnvironmentTests(unittest.TestCase):
    def test_patch_replaces_the_mapping_without_mutating_the_process_environment(self):
        process_environment = os.environ
        before = dict(process_environment)

        with _test_env.patch({"ONLY_IN_TEST": "yes"}, clear=True):
            self.assertIsNot(os.environ, process_environment)
            self.assertEqual(dict(os.environ), {"ONLY_IN_TEST": "yes"})

        self.assertIs(os.environ, process_environment)
        self.assertEqual(dict(os.environ), before)


if __name__ == "__main__":
    unittest.main()
