#!/usr/bin/env python3
"""Tests for dev/tools/build_spec.py (CMH-BUILD-08)."""
import os
import shutil
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

import _paths

sys.path.insert(0, _paths.DEV_TOOLS)
import build_spec  # noqa: E402


class BuildSpecTests(unittest.TestCase):
    def setUp(self):
        root = os.path.abspath(os.path.join(_paths.DEV, "..", "..", ".."))
        self.sandbox = os.path.join(root, "tmp", "test_build_spec")
        self.spec_dir = os.path.join(self.sandbox, "spec")
        self.out = os.path.join(self.sandbox, "SPEC.md")
        shutil.rmtree(self.sandbox, ignore_errors=True)
        os.makedirs(self.spec_dir)

    def tearDown(self):
        shutil.rmtree(self.sandbox, ignore_errors=True)

    def _write(self, path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)

    def _main(self, args):
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            return build_spec.main(args)

    def test_assembles_numbered_partials_by_directory_sort_with_banner(self):
        self._write(os.path.join(self.spec_dir, "20-second.md"), "second\n")
        self._write(os.path.join(self.spec_dir, "10-first.md"), "first\n")

        text = build_spec.assemble_spec(self.spec_dir, self.out)

        self.assertTrue(text.startswith("<!-- GENERATED FILE - DO NOT EDIT."))
        self.assertLess(text.index("first\n"), text.index("second\n"))

    def test_check_mode_flags_generated_spec_drift(self):
        self._write(os.path.join(self.spec_dir, "00-header.md"), "# Spec\n")
        self.assertEqual(self._main(["build_spec.py", "--spec-dir", self.spec_dir, "--out", self.out]), 0)
        self.assertEqual(self._main(["build_spec.py", "--check", "--spec-dir", self.spec_dir,
                                     "--out", self.out]), 0)

        self._write(self.out, "# stale\n")

        self.assertEqual(self._main(["build_spec.py", "--check", "--spec-dir", self.spec_dir,
                                     "--out", self.out]), 1)

    def test_rejects_stray_markdown_files_that_would_not_be_assembled(self):
        self._write(os.path.join(self.spec_dir, "00-header.md"), "# Spec\n")
        self._write(os.path.join(self.spec_dir, "header.md"), "# Stray\n")

        with self.assertRaises(SystemExit):
            build_spec.ordered_parts(self.spec_dir)


if __name__ == "__main__":
    unittest.main()
