#!/usr/bin/env python3
"""Tests for scripts/check_no_backlog.py."""

import importlib.util
import unittest
from pathlib import Path
from unittest import mock

_MODULE_PATH = Path(__file__).with_name("check_no_backlog.py")
_spec = importlib.util.spec_from_file_location("check_no_backlog", _MODULE_PATH)
cnb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cnb)


class BacklogViolationTest(unittest.TestCase):
    def test_allows_clean_tree(self):
        self.assertEqual(
            cnb.find_violations(
                [
                    "AGENTS.md",
                    ".github/skills/task/SKILL.md",
                    "docs/general-audit-playbook.html",
                    "scripts/check_no_backlog.py",
                ]
            ),
            [],
        )

    def test_flags_backlog_task_file(self):
        self.assertEqual(
            cnb.find_violations(["backlog/tasks/task-1 - Example.md"]),
            ["backlog/tasks/task-1 - Example.md"],
        )

    def test_flags_backlog_tooling_config(self):
        self.assertEqual(
            cnb.find_violations(["tools/backlog.config.yml"]),
            ["tools/backlog.config.yml"],
        )


class MainTest(unittest.TestCase):
    @mock.patch.object(cnb, "tracked_files", return_value=["AGENTS.md"])
    def test_main_passes_on_clean_tree(self, _tracked):
        self.assertEqual(cnb.main(), 0)

    @mock.patch.object(cnb, "tracked_files", return_value=["backlog/tasks/x.md"])
    def test_main_fails_when_backlog_task_is_present(self, _tracked):
        self.assertEqual(cnb.main(), 1)


if __name__ == "__main__":
    unittest.main()
