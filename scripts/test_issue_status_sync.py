#!/usr/bin/env python3
"""Structural regression tests for .github/workflows/issue-status-sync.yml.

These pin the label-lifecycle behavior so it cannot silently regress: the workflow
must ADD `status: in progress` when a closing PR opens and REMOVE it when the linked
task issue closes (a merged PR closes the issue via "Closes #N"). A GitHub Actions
workflow has no runtime unit-test harness, so this asserts the wiring statically.
"""
import os
import unittest

import yaml

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW = os.path.join(REPO_ROOT, ".github", "workflows", "issue-status-sync.yml")


def _load():
    with open(WORKFLOW, encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    # PyYAML (YAML 1.1) parses a bare `on:` key as the boolean True.
    triggers = doc.get("on", doc.get(True))
    return doc, triggers


class IssueStatusSyncWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.doc, self.triggers = _load()
        self.mark = self.doc["jobs"]["mark-in-progress"]
        self.clear = self.doc["jobs"]["clear-in-progress"]

    def test_triggers_on_pr_target_and_issue_closed(self):
        self.assertIn("pull_request_target", self.triggers)
        self.assertIn("issues", self.triggers)
        self.assertEqual(self.triggers["issues"]["types"], ["closed"])

    def test_jobs_are_guarded_by_event_name(self):
        # Each job runs only for its own event so an issues event never runs the PR
        # job (which reads github.event.pull_request, absent on an issues event).
        self.assertEqual(self.mark["if"], "github.event_name == 'pull_request_target'")
        self.assertEqual(self.clear["if"], "github.event_name == 'issues'")

    def test_clear_job_removes_the_in_progress_label_from_a_task_issue(self):
        run = self.clear["steps"][0]["run"]
        self.assertIn('--remove-label "status: in progress"', run)
        # Gated to task issues so it never relabels an unrelated closed issue.
        self.assertIn('grep -qx "task"', run)
        # A no-op when the label is absent (does not error).
        self.assertIn('grep -qx "status: in progress"', run)

    def test_mark_job_self_heals_a_close_label_race(self):
        # After adding the label it must re-check state and remove it if the issue
        # closed meanwhile, so a close/label race cannot leave a closed issue stuck.
        run = self.mark["steps"][0]["run"]
        self.assertIn('--add-label "status: in progress"', run)
        self.assertIn('.state', run)
        self.assertIn('CLOSED', run)
        self.assertIn('--remove-label "status: in progress"', run)

    def test_permissions_are_least_privilege_per_job(self):
        # Top-level grants nothing; each job requests exactly what it needs. The clear
        # job never touches pull requests, so it must not hold pull-requests scope.
        self.assertEqual(self.doc.get("permissions"), {})
        self.assertEqual(self.mark["permissions"].get("issues"), "write")
        self.assertEqual(self.mark["permissions"].get("pull-requests"), "read")
        self.assertEqual(self.clear["permissions"].get("issues"), "write")
        self.assertNotIn("pull-requests", self.clear["permissions"])


if __name__ == "__main__":
    unittest.main()
