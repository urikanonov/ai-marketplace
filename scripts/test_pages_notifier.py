#!/usr/bin/env python3
"""Covering tests for the `pages` failure notifier (SITE-NOTIFY-*).

The notifier is automated ISSUE CREATION, so it needs the same bar as any other automated filing:
it must not manufacture a tracked issue out of noise. Two real non-defects reached `main` as issues
before this was gated - #1148 and #1190 - one from a concurrency-superseded run and one from a
GitHub infrastructure outage ("Failed to resolve action download info. Error: Service Unavailable"),
where the `site` job had actually SUCCEEDED.

Run by the validate CI job via `python scripts/run_script_tests.py`. Standard library only.
"""
import os
import re
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGES_WF = os.path.join(REPO_ROOT, ".github", "workflows", "pages.yml")


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _notify_job(text):
    """The `notify:` job block, from its key to the next top-level job key."""
    m = re.search(r"^  notify:\n(.*?)(?=^  [a-z][a-z0-9_-]*:\n|\Z)", text, re.S | re.M)
    assert m, "pages.yml has no `notify:` job"
    return m.group(0)


class PagesNotifierTests(unittest.TestCase):
    def setUp(self):
        self.text = _read(PAGES_WF)
        self.job = _notify_job(self.text)

    def test_a_cancelled_run_does_not_file_an_issue(self):
        # SITE-NOTIFY-01: a cancelled `pages` run is almost always a concurrency-superseded run - the
        # normal result of pushing twice - not a failure. Filing an issue for it is pure noise.
        cond = re.search(r"if: \$\{\{(.*?)\}\}", self.job, re.S)
        self.assertIsNotNone(cond, "the notify job has no `if:` condition")
        self.assertNotIn(
            "cancelled", cond.group(1),
            "the notify job must not treat a CANCELLED run as a failure: a superseded run is normal"
            " and filing an issue for it produced pure noise (#1190).",
        )

    def test_a_recovered_run_closes_the_open_failure_issue(self):
        # SITE-NOTIFY-02: the notifier deduped only against OPEN issues and never closed anything, so
        # closing a stale failure issue GUARANTEED the next blip filed a brand-new duplicate. That is
        # exactly the #1148 -> #1190 sequence. A run that succeeds must close the open issue.
        self.assertIn(
            'state: "closed"', self.job,
            "the notifier must CLOSE the open failure issue when a later run succeeds, otherwise a"
            " recovered outage leaves a stale issue behind and the next failure files a duplicate.",
        )
        self.assertIn(
            "state_reason", self.job,
            "closing should record a state_reason so a recovered-not-planned close is auditable",
        )

    def test_the_notifier_still_runs_on_a_real_failure(self):
        # SITE-NOTIFY-03: the gate above must not silence genuine breakage - a failed site build or a
        # failed deploy still has to open (or update) the tracking issue.
        self.assertIn("failure", self.job)
        self.assertIn("issues.create", self.job)
        self.assertIn("issues.createComment", self.job)

    def test_the_notifier_job_still_runs_on_every_completed_main_run(self):
        # SITE-NOTIFY-02 needs the job to execute on SUCCESS too (that is when it closes the issue),
        # so it must stay `always()`-gated on main rather than only running when something failed.
        self.assertIn("always()", self.job)
        self.assertIn("refs/heads/main", self.job)


if __name__ == "__main__":
    unittest.main()
