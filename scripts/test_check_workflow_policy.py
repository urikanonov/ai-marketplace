#!/usr/bin/env python3
"""Tests for scripts/check_workflow_policy.py (the CI trust-boundary gate)."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_workflow_policy as cwp  # noqa: E402


def _write(tmp, name, text):
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


class TriggerParsingTests(unittest.TestCase):
    def test_bare_on_key_is_parsed_as_boolean_true(self):
        # YAML 1.1 (PyYAML) parses a bare `on:` key as the boolean True. _triggers must cope.
        import yaml
        doc = yaml.safe_load("on:\n  pull_request_target:\n    types: [opened]\njobs: {}\n")
        self.assertIn("pull_request_target", cwp._triggers(doc))

    def test_string_and_list_forms(self):
        self.assertEqual(cwp._triggers({"on": "push"}), {"push"})
        self.assertEqual(cwp._triggers({"on": ["push", "pull_request"]}), {"push", "pull_request"})


class RuleATests(unittest.TestCase):
    def test_pull_request_target_with_checkout_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _write(tmp, "wf.yml",
                       "on:\n  pull_request_target:\n"
                       "jobs:\n  j:\n    runs-on: ubuntu-latest\n    steps:\n"
                       "      - uses: actions/checkout@v4\n")
            v = cwp.check_workflow(p)
            self.assertTrue(any("RULE A" in x for x in v), v)

    def test_pull_request_target_with_quoted_checkout_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _write(tmp, "wf.yml",
                       "on:\n  pull_request_target:\n"
                       "jobs:\n  j:\n    runs-on: ubuntu-latest\n    steps:\n"
                       '      - uses: "actions/checkout@v4"\n')
            self.assertTrue(any("RULE A" in x for x in cwp.check_workflow(p)))

    def test_pull_request_target_with_gh_pr_checkout_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _write(tmp, "wf.yml",
                       "on:\n  pull_request_target:\n"
                       "jobs:\n  j:\n    runs-on: ubuntu-latest\n    steps:\n"
                       "      - run: gh pr checkout ${{ github.event.number }}\n")
            self.assertTrue(any("gh pr checkout" in x for x in cwp.check_workflow(p)))

    def test_checkout_in_a_comment_is_not_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _write(tmp, "wf.yml",
                       "on:\n  pull_request_target:\n"
                       "jobs:\n  j:\n    runs-on: ubuntu-latest\n    steps:\n"
                       "      # this job intentionally does not do uses: actions/checkout\n"
                       "      - run: echo safe\n")
            self.assertEqual(cwp.check_workflow(p), [])

    def test_reading_head_sha_for_a_status_is_allowed(self):
        # Reading github.event.pull_request.head.sha to post a commit status (no checkout) is safe.
        with tempfile.TemporaryDirectory() as tmp:
            p = _write(tmp, "wf.yml",
                       "on:\n  pull_request_target:\n"
                       "jobs:\n  j:\n    runs-on: ubuntu-latest\n    steps:\n"
                       "      - run: echo ${{ github.event.pull_request.head.sha }}\n")
            self.assertEqual(cwp.check_workflow(p), [])

    def test_pull_request_target_without_checkout_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _write(tmp, "wf.yml",
                       "on:\n  pull_request_target:\n"
                       "jobs:\n  j:\n    runs-on: ubuntu-latest\n    steps:\n"
                       "      - run: echo hi\n")
            self.assertEqual(cwp.check_workflow(p), [])


class RuleBTests(unittest.TestCase):
    def test_pull_request_with_secrets_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _write(tmp, "wf.yml",
                       "on:\n  pull_request:\n"
                       "jobs:\n  j:\n    runs-on: ubuntu-latest\n    steps:\n"
                       "      - run: echo ${{ secrets.MY_TOKEN }}\n")
            v = cwp.check_workflow(p)
            self.assertTrue(any("RULE B" in x for x in v), v)

    def test_pull_request_with_secrets_bracket_syntax_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _write(tmp, "wf.yml",
                       "on:\n  pull_request:\n"
                       "jobs:\n  j:\n    runs-on: ubuntu-latest\n    steps:\n"
                       "      - run: echo ${{ secrets['MY_TOKEN'] }}\n")
            self.assertTrue(any("RULE B" in x for x in cwp.check_workflow(p)))

    def test_pull_request_with_secrets_inherit_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _write(tmp, "wf.yml",
                       "on:\n  pull_request:\n"
                       "jobs:\n  j:\n    uses: ./.github/workflows/reusable.yml\n    secrets: inherit\n")
            self.assertTrue(any("RULE B" in x for x in cwp.check_workflow(p)))

    def test_pull_request_without_secrets_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _write(tmp, "wf.yml",
                       "on:\n  pull_request:\n"
                       "jobs:\n  j:\n    runs-on: ubuntu-latest\n    steps:\n"
                       "      - run: echo ${{ github.token }}\n")
            self.assertEqual(cwp.check_workflow(p), [])

    def test_pull_request_target_with_secrets_is_allowed(self):
        # A pull_request_target workflow (no PR code, trusted base) MAY use secrets.
        with tempfile.TemporaryDirectory() as tmp:
            p = _write(tmp, "wf.yml",
                       "on:\n  pull_request_target:\n"
                       "jobs:\n  j:\n    runs-on: ubuntu-latest\n    steps:\n"
                       "      - run: echo ${{ secrets.MY_TOKEN }}\n")
            self.assertEqual(cwp.check_workflow(p), [])


class RuleCTests(unittest.TestCase):
    def _run_with_config(self, filename, body):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _write(tmp, filename, body)
            orig = cwp.ACTIONLINT_CONFIGS
            cwp.ACTIONLINT_CONFIGS = (cfg,)
            try:
                return cwp.check_actionlint_config()
            finally:
                cwp.ACTIONLINT_CONFIGS = orig

    def test_nonempty_ignore_fails(self):
        v = self._run_with_config("actionlint.yaml", 'ignore:\n  - "unknown Webhook event"\n')
        self.assertTrue(any("RULE C" in x for x in v), v)

    def test_nonempty_ignore_in_yml_filename_fails(self):
        v = self._run_with_config("actionlint.yml", 'ignore:\n  - "unknown Webhook event"\n')
        self.assertTrue(any("RULE C" in x for x in v), v)

    def test_missing_config_passes(self):
        orig = cwp.ACTIONLINT_CONFIGS
        cwp.ACTIONLINT_CONFIGS = (os.path.join(tempfile.gettempdir(), "does-not-exist-actionlint.yaml"),)
        try:
            self.assertEqual(cwp.check_actionlint_config(), [])
        finally:
            cwp.ACTIONLINT_CONFIGS = orig


class RuleDTests(unittest.TestCase):
    def _v(self, run_lines):
        with tempfile.TemporaryDirectory() as tmp:
            steps = "".join("      - run: %s\n" % ln for ln in run_lines)
            p = _write(tmp, "wf.yml",
                       "on:\n  pull_request:\n"
                       "jobs:\n  j:\n    runs-on: ubuntu-latest\n    steps:\n" + steps)
            return [x for x in cwp.check_workflow(p) if "RULE D" in x]

    def test_dotted_injectable_contexts_fail(self):
        for expr in (
            "github.event.pull_request.body",
            "github.event.pull_request.title",
            "github.event.issue.body",
            "github.event.issue.title",
            "github.event.comment.body",
            "github.event.review.body",
            "github.event.discussion.body",
            "github.event.head_commit.message",
            "github.event.commits[0].message",
            "github.head_ref",
            "github.event.pull_request.head.ref",
            "github.event.pull_request.head.label",
            "github.event.head_commit.author.email",
            "github.event.head_commit.author.name",
        ):
            self.assertTrue(self._v(["echo ${{ %s }}" % expr]), expr)

    def test_bracket_and_index_notation_is_caught(self):
        # Semantically identical to the dotted form; must not evade the guard.
        for expr in (
            "github.event.pull_request['body']",
            'github.event.pull_request["body"]',
            "github['event']['pull_request']['body']",
            "github.event['issue'].title",
            "github.event.commits[0]['message']",
        ):
            self.assertTrue(self._v(["echo ${{ %s }}" % expr]), expr)

    def test_tojson_of_event_object_is_caught(self):
        self.assertTrue(self._v(["echo ${{ toJSON(github.event) }}"]))
        self.assertTrue(self._v(["echo ${{ toJSON(github.event.pull_request) }}"]))

    def test_no_space_and_multiline_expressions_are_caught(self):
        self.assertTrue(self._v(["echo ${{github.event.pull_request.body}}"]))
        with tempfile.TemporaryDirectory() as tmp:
            p = _write(tmp, "wf.yml",
                       "on:\n  pull_request:\n"
                       "jobs:\n  j:\n    runs-on: ubuntu-latest\n    steps:\n"
                       "      - run: |\n"
                       "          echo ${{\n            github.event.pull_request.body\n          }}\n")
            self.assertTrue([x for x in cwp.check_workflow(p) if "RULE D" in x])

    def test_safe_metadata_contexts_pass(self):
        for expr in (
            "github.event.pull_request.head.sha",
            "github.event.pull_request.number",
            "github.event.pull_request.user.login",
            "github.event.pull_request.base.sha",
            "github.sha",
            "github.repository",
        ):
            self.assertEqual(self._v(["echo ${{ %s }}" % expr]), [], expr)

    def test_pr_body_via_env_var_passes(self):
        # The safe pattern the multi-duck-review gate uses: bind to env, reference "$VAR" in run.
        with tempfile.TemporaryDirectory() as tmp:
            p = _write(tmp, "wf.yml",
                       "on:\n  pull_request:\n"
                       "jobs:\n  j:\n    runs-on: ubuntu-latest\n    steps:\n"
                       "      - env:\n          PR_BODY: ${{ github.event.pull_request.body }}\n"
                       "        run: python scripts/check_multi_duck_review.py\n")
            self.assertEqual([x for x in cwp.check_workflow(p) if "RULE D" in x], [])


class RealRepoTests(unittest.TestCase):
    def test_current_workflows_satisfy_the_policy(self):
        self.assertEqual(cwp.main(), 0)


if __name__ == "__main__":
    unittest.main()
