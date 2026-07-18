#!/usr/bin/env python3
"""Every shipped tool answers --help (and -h) with exit 0 and prints usage to stdout.

A CLI that treats --help as a filename, or exits non-zero on --help, is broken for
anyone discovering the tool. This guards CMH-TOOL-HELP-01 across the whole tools/ set.
"""
import importlib
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402  shared pkg/dev split path constants
TOOLS = _paths.TOOLS
sys.path.insert(0, TOOLS)

# Discover every shipped CLI tool directly under a topic bucket (tools/<topic>/<name>.py).
# deck_common and doc_stamp are shared libraries (no CLI) and nested helper packages
# (validate/cmhval/) are not standalone tools, so none is included in the --help contract.
_NO_CLI = {"deck_common.py", "doc_stamp.py", "section_hash.py"}
SHIPPED_TOOLS = sorted(
    os.path.join(TOOLS, topic, name)
    for topic in os.listdir(TOOLS)
    if os.path.isdir(os.path.join(TOOLS, topic)) and not topic.startswith(("_", "."))
    for name in os.listdir(os.path.join(TOOLS, topic))
    if name.endswith(".py") and not name.startswith("_") and name not in _NO_CLI
    and os.path.isfile(os.path.join(TOOLS, topic, name)))

# Tools that parse argv themselves and honor a "--" end-of-options separator so a data
# value that looks like a flag (a filename/query/id of "-h") is not mistaken for --help.
END_OF_OPTIONS_TOOLS = ("validate", "kql_highlight", "kusto_link", "mark_handled")


class CliHelpTests(unittest.TestCase):
    def test_there_are_tools_to_check(self):
        self.assertTrue(SHIPPED_TOOLS, "no shipped tools discovered under tools/")

    def test_every_tool_answers_help_with_exit_zero(self):
        for tool in SHIPPED_TOOLS:
            rel = os.path.relpath(tool, TOOLS)
            for flag in ("--help", "-h"):
                with self.subTest(tool=rel, flag=flag):
                    r = subprocess.run(
                        [sys.executable, tool, flag],
                        capture_output=True, text=True, cwd=TOOLS, timeout=60)
                    self.assertEqual(
                        r.returncode, 0,
                        "%s %s exited %d\nstdout:%s\nstderr:%s"
                        % (rel, flag, r.returncode, r.stdout, r.stderr))
                    self.assertIn("usage", (r.stdout + r.stderr).lower(),
                                  "%s %s printed no usage text" % (rel, flag))


class EndOfOptionsHelpTests(unittest.TestCase):
    def test_help_flag_before_end_of_options_triggers_help(self):
        for name in END_OF_OPTIONS_TOOLS:
            mod = importlib.import_module(name)
            with self.subTest(tool=name):
                self.assertTrue(mod._wants_help(["-h"]))
                self.assertTrue(mod._wants_help(["--help"]))
                self.assertTrue(mod._wants_help(["--code-only", "-h"]))

    def test_help_flag_after_end_of_options_is_data(self):
        # A "-h"/"--help" appearing AFTER a bare "--" is a positional value, not a request
        # for help; scanning all argv (the old behavior) wrongly printed help instead.
        for name in END_OF_OPTIONS_TOOLS:
            mod = importlib.import_module(name)
            with self.subTest(tool=name):
                self.assertFalse(mod._wants_help(["--", "-h"]))
                self.assertFalse(mod._wants_help(["--code-only", "--", "-h"]))
                self.assertFalse(mod._wants_help(["file.html", "--", "--help"]))

    def test_dash_h_after_separator_is_treated_as_data_end_to_end(self):
        # kusto_link takes cluster/database/query positionals; "-h" after "--" must be used
        # as the query (a real URL), never trigger the usage/help path.
        r = subprocess.run(
            [sys.executable, os.path.join(TOOLS, "kusto", "kusto_link.py"), "help", "db", "--", "-h"],
            capture_output=True, text=True, cwd=TOOLS, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("usage:", r.stdout.lower())
        self.assertIn("http", r.stdout.lower())


if __name__ == "__main__":
    unittest.main()
