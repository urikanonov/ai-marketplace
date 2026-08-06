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

    def test_a_timed_out_deploy_still_alerts_because_main_never_supersedes(self):
        # SITE-NOTIFY-01: `cancelled` must NOT be dismissed as noise on main. `cancel-in-progress` is
        # false for refs/heads/main, so a main run is never superseded - a cancellation there means
        # the job hit `timeout-minutes` or a human cancelled it. GitHub reports a TIMED-OUT job as
        # `cancelled`, not `failure` (run 31111831920's deploy ran 14:45:07-14:55:09, exactly the
        # configured 10 minutes), so treating cancellations as benign would silence a stale site.
        self.assertRegex(
            self.job,
            r'const bad = \["failure", "cancelled"\]',
            "a cancelled job on main is a timeout or a manual cancel, never a supersede, so it must"
            " still open the alert - dropping it would hide a genuinely undeployed site.",
        )
        self.assertRegex(
            self.job,
            r"const failed = bad\.includes\(siteResult\) \|\| bad\.includes\(deployResult\)",
            "the alert must fire when EITHER job is failed or cancelled",
        )

    def test_the_main_branch_never_cancels_a_run_in_progress(self):
        # The premise the rule above rests on. If `cancel-in-progress` ever became true for main,
        # cancellations would once again be routine supersedes and SITE-NOTIFY-01's reasoning would
        # be wrong, so pin the concurrency setting that makes a main cancellation meaningful.
        self.assertIn(
            "cancel-in-progress: ${{ github.ref != 'refs/heads/main' }}", self.text,
            "SITE-NOTIFY-01 treats a cancelled main run as a real failure precisely because main"
            " does not cancel in-progress runs; changing that invalidates the rule.",
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

    def test_the_close_is_gated_on_a_full_recovery_not_merely_on_not_failing(self):
        # SITE-NOTIFY-02, the correctness-critical half: closing must require BOTH jobs to have
        # SUCCEEDED. `deploy` is skipped whenever `site` did not succeed, so a laxer gate (anything
        # that is not `failure`) would retire the alert on a cancelled or skipped run - marking the
        # site recovered while it was never actually rebuilt or republished.
        close = re.search(r"if \(existing && (.*?)\) \{", self.job, re.S)
        self.assertIsNotNone(close, "could not find the close guard in the notify script")
        guard = close.group(1)
        self.assertIn('siteResult === "success"', guard)
        self.assertIn('deployResult === "success"', guard)

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
