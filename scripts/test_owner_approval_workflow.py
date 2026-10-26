"""Regression coverage for the fork-safe owner-approval workflow."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "require-owner-approval.yml"


def workflow():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


class OwnerApprovalWorkflowTests(unittest.TestCase):
    def test_review_wakes_a_trusted_evaluator_without_fork_write_permissions(self):
        doc = workflow()
        triggers = doc.get("on", doc.get(True))
        self.assertNotIn("pull_request_review", triggers)
        self.assertEqual(triggers["workflow_run"], {
            "workflows": ["Require Resolved Conversations"],
            "types": ["completed"],
        })
        upstream = yaml.safe_load(
            (WORKFLOW.parent / "require-resolved-conversations.yml").read_text(encoding="utf-8"))
        self.assertIn("pull_request_review", upstream.get("on", upstream.get(True)))
        self.assertNotIn("statuses", upstream["permissions"])
        self.assertNotIn("statuses", doc["permissions"])
        for job in doc["jobs"].values():
            self.assertEqual(job["permissions"], {
                "contents": "read", "pull-requests": "read", "statuses": "write",
            })
        self.assertEqual(doc["concurrency"]["group"],
                         "require-owner-approval-${{ github.event.pull_request.head.sha || "
                         "github.event.workflow_run.head_sha }}")
        self.assertIs(doc["concurrency"]["cancel-in-progress"], False)
        self.assertNotIn("if", doc["jobs"]["discover"])
        self.assertEqual(doc["jobs"]["discover"]["steps"][0]["with"]["retries"], 3)
        for job in doc["jobs"].values():
            for step in job.get("steps", []):
                self.assertNotIn("actions/checkout", step.get("uses", ""))
                self.assertNotIn("download-artifact", step.get("uses", ""))
        evaluator = doc["jobs"]["evaluate"]
        self.assertEqual(evaluator["needs"], "discover")
        self.assertIn("needs.discover.outputs.prs", evaluator["strategy"]["matrix"]["pr"])
        env = evaluator["steps"][0]["env"]
        self.assertEqual(env["HEAD_SHA"], "${{ matrix.pr.sha }}")
        self.assertEqual(env["PR_NUMBER"], "${{ matrix.pr.number }}")
        self.assertEqual(env["PR_AUTHOR"], "${{ matrix.pr.author }}")

    def test_existing_current_head_and_revocation_checks_are_preserved(self):
        script = workflow()["jobs"]["evaluate"]["steps"][0]["run"]
        self.assertIn('post_status pending "Checking for a maintainer approval..."', script)
        self.assertIn('.state == "APPROVED" and .commit_id == $h', script)
        self.assertIn('.state == "CHANGES_REQUESTED" or .state == "DISMISSED"', script)
        self.assertIn('finalize failure "Could not read reviews', script)
        self.assertIn('finalize failure "Needs an approving review', script)
        self.assertIn('exit 1', script)
        self.assertIn('--paginate', script)


@unittest.skipUnless(shutil.which("node"), "Node.js is required to execute the inline discovery script")
class ApprovalDiscoveryTests(unittest.TestCase):
    def discover(self, event, payload, pulls=(), fail=False):
        script = workflow()["jobs"]["discover"]["steps"][0]["with"]["script"]
        fixture = {
            "event": event, "payload": payload, "pulls": list(pulls), "fail": fail,
        }
        harness = """
const fs = require('fs');
const {script, fixture: f} = JSON.parse(fs.readFileSync(0, 'utf8'));
const calls = [];
const context = {eventName: f.event, payload: f.payload, repo: {owner: 'owner', repo: 'repo'}};
const github = {
  rest: {pulls: {list: 'list'}, repos: {createCommitStatus: async args => {
    calls.push(['status', args]);
    return {data: {}};
  }}},
  paginate: async (route, args) => {
    calls.push(['paginate', route, args]);
    if (f.fail) throw new Error('API unavailable');
    return f.pulls;
  }
};
const AsyncFunction = Object.getPrototypeOf(async function(){}).constructor;
new AsyncFunction('github', 'context', script)(github, context)
  .then(result => console.log(JSON.stringify({result, calls})))
  .catch(error => {
    console.log(JSON.stringify({calls}));
    console.error(error.message); process.exitCode = 1;
  });
"""
        result = subprocess.run(
            [shutil.which("node"), "-e", harness],
            input=json.dumps({"script": script, "fixture": fixture}),
            text=True, encoding="utf-8", capture_output=True, check=False,
        )
        if fail:
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("API unavailable", result.stderr)
            return json.loads(result.stdout)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_fork_review_without_associated_prs_discovers_live_open_prs(self):
        pulls = [
            {"number": 1, "user": {"login": "external"}, "head": {"sha": "a" * 40}},
            {"number": 2, "user": {"login": "urikanonov"}, "head": {"sha": "b" * 40}},
        ]
        result = self.discover("workflow_run", {
            "workflow_run": {"pull_requests": [], "head_sha": "a" * 40}
        }, pulls)
        self.assertEqual(result["result"], [
            {"number": 1, "author": "external", "sha": "a" * 40},
        ])
        self.assertEqual(result["calls"][0][0], "status")
        self.assertEqual(result["calls"][0][1]["state"], "pending")
        self.assertEqual(result["calls"][0][1]["sha"], "a" * 40)
        self.assertEqual(result["calls"][1], [
            "paginate", "list", {"owner": "owner", "repo": "repo", "state": "open", "per_page": 100},
        ])

    def test_trigger_heads_are_isolated_and_stale_runs_do_not_evaluate_new_heads(self):
        pulls = [
            {"number": 3, "user": {"login": "external"}, "head": {"sha": "c" * 40}},
            {"number": 4, "user": {"login": "external"}, "head": {"sha": "d" * 40}},
        ]
        events = [
            ("workflow_run", {"workflow_run": {"event": "pull_request_review", "head_sha": "c" * 40}},
             [{"number": 3, "author": "external", "sha": "c" * 40}]),
            ("pull_request_target", {"pull_request": {"number": 4, "head": {"sha": "a" * 40}}}, []),
            ("workflow_run", {"workflow_run": {"event": "pull_request", "head_sha": "d" * 40}},
             [{"number": 4, "author": "external", "sha": "d" * 40}]),
        ]
        for event, payload, expected in events:
            with self.subTest(event=event, payload=payload):
                result = self.discover(event, payload, pulls=pulls)
                self.assertEqual(result["result"], expected)
                self.assertEqual(result["calls"][1][0], "paginate")

    def test_discovery_failure_cannot_displace_another_heads_revocation(self):
        group = workflow()["concurrency"]["group"]
        self.assertIn("github.event.pull_request.head.sha || github.event.workflow_run.head_sha", group)
        self.assertNotEqual(group, "require-owner-approval")
        for sha in ("a" * 40, "b" * 40):
            with self.subTest(sha=sha):
                result = self.discover("workflow_run", {
                    "workflow_run": {"head_sha": sha, "pull_requests": []}
                }, fail=True)
                statuses = [call[1] for call in result["calls"] if call[0] == "status"]
                self.assertEqual([(s["sha"], s["state"]) for s in statuses],
                                 [(sha, "pending"), (sha, "failure")])

    def test_empty_sweep_produces_no_matrix_entries(self):
        self.assertEqual(self.discover("workflow_run", {
            "workflow_run": {"head_sha": "a" * 40}
        }, [])["result"], [])
        self.assertIn("needs.discover.outputs.prs != '[]'",
                      workflow()["jobs"]["evaluate"]["if"])

    def test_metadata_api_errors_revoke_trigger_head_status_before_failing(self):
        events = [
            ("workflow_run", {"workflow_run": {"head_sha": "a" * 40}}),
            ("pull_request_target", {"pull_request": {"number": 3, "head": {"sha": "a" * 40}}}),
        ]
        for event, payload in events:
            with self.subTest(event=event):
                result = self.discover(event, payload, fail=True)
                statuses = [args for name, *rest in result["calls"]
                            if name == "status" for args in rest]
                self.assertEqual([s["state"] for s in statuses], ["pending", "failure"])
                self.assertTrue(all(s["sha"] == "a" * 40 for s in statuses))
