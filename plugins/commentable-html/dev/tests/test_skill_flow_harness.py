"""CMH-HARNESS-01: hermetic tests for the local skill-flow regression harness.

These exercise the harness PLUMBING only - the CI guard, the scratch-under-tmp invariant, the prompt
corpus completeness, the copilot command construction, the validator wiring, and the content checks -
WITHOUT ever invoking the ``copilot`` executable or a live model (which the suite forbids and which is
inherently non-deterministic). The end-to-end live invocation is a documented manual coverage gap in
dev/SPEC.md.
"""
import contextlib
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402  shared pkg/dev split path constants

sys.path.insert(0, _paths.DEV_TOOLS)
import skill_flow_harness as harness  # noqa: E402
import skill_flow_prompts as prompts  # noqa: E402

KNOWN_VALIDATORS = {"validate", "deck_validate", "portable", "stamp"}


class CiGuardTests(unittest.TestCase):
    def test_detects_common_ci_vars(self):
        for var in ("CI", "GITHUB_ACTIONS", "CONTINUOUS_INTEGRATION", "TF_BUILD", "GITLAB_CI",
                    "JENKINS_URL", "CIRCLECI", "BUILDKITE"):
            self.assertTrue(harness.is_ci_environment({var: "true"}), var)
        self.assertTrue(harness.is_ci_environment({"CI": "1"}))

    def test_ignores_absent_or_falsey(self):
        self.assertFalse(harness.is_ci_environment({}))
        for falsey in ("", "0", "false", "FALSE", "no"):
            self.assertFalse(harness.is_ci_environment({"CI": falsey}), falsey)

    def test_main_refuses_a_real_run_under_ci(self):
        with mock.patch.dict(os.environ, {"CI": "true"}, clear=False):
            rc = harness.main(["--flows", "create"])
        self.assertEqual(rc, 3)

    def test_dry_run_is_allowed_even_under_ci(self):
        with mock.patch.dict(os.environ, {"CI": "true"}, clear=False):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = harness.main(["--dry-run"])
        self.assertEqual(rc, 0)
        text = out.getvalue()
        for name in prompts.flow_names():
            self.assertIn("flow: %s" % name, text)
        self.assertIn("--allow-all-tools", text)

    def test_run_flow_raises_and_never_spawns_under_ci(self):
        # Defense in depth: calling run_flow directly under CI must refuse before any subprocess.
        with mock.patch.dict(os.environ, {"CI": "true"}, clear=False), \
                mock.patch("subprocess.run") as spawned:
            with self.assertRaises(RuntimeError):
                harness.run_flow(prompts.FLOWS[0], harness.scratch_root() / "should-not-exist")
        spawned.assert_not_called()

    def test_run_flow_rejects_run_dir_outside_scratch_root(self):
        # A caller must not be able to make the harness write into a tracked tree.
        with mock.patch.object(harness, "is_ci_environment", return_value=False), \
                mock.patch("subprocess.run") as spawned:
            with self.assertRaises(ValueError):
                harness.run_flow(prompts.FLOWS[0], Path(tempfile.gettempdir()) / "cmh-outside-root")
        spawned.assert_not_called()

    def test_run_flow_fails_on_timeout(self):
        # A hung/looping agent (TimeoutExpired -> rc None) is a FAIL even if a stale artifact exists.
        run_dir = harness.scratch_root() / "unit-timeout"
        self.addCleanup(shutil.rmtree, run_dir, ignore_errors=True)

        def fake_prep(flow, ws):
            ws.mkdir(parents=True, exist_ok=True)

        with mock.patch.object(harness, "is_ci_environment", return_value=False), \
                mock.patch.object(harness, "_prepare_workspace", side_effect=fake_prep), \
                mock.patch("subprocess.run",
                           side_effect=subprocess.TimeoutExpired("copilot", 1)):
            result = harness.run_flow(prompts.flows_by_name()["create"], run_dir)
        self.assertFalse(result["ok"])
        self.assertIn("timed out", result["error"])
        self.assertEqual(result["validators"], [])


class ScratchTests(unittest.TestCase):
    def test_scratch_root_is_under_repo_tmp(self):
        root = harness.scratch_root()
        expected_tmp = harness.REPO_ROOT / "tmp"
        self.assertTrue(str(root).startswith(str(expected_tmp)),
                        "scratch %s must be under %s" % (root, expected_tmp))
        self.assertEqual(root.name, "skill-flow-harness")
        # tmp/ is gitignored, so nothing the harness writes can dirty a tracked tree.
        self.assertIn("tmp", root.parts)


class CommandTests(unittest.TestCase):
    def test_build_copilot_command_shape(self):
        cmd = harness.build_copilot_command("PROMPT-TEXT", Path("/ws"), model="m1", copilot_bin="cop")
        self.assertEqual(cmd[0], "cop")
        self.assertIn("-p", cmd)
        self.assertIn("PROMPT-TEXT", cmd)
        self.assertIn("--allow-all-tools", cmd)   # required for non-interactive mode
        # File access is SCOPED to the workspace, not opened to all paths.
        self.assertNotIn("--allow-all-paths", cmd)
        self.assertNotIn("--allow-all", cmd)
        ci = cmd.index("-C")
        self.assertEqual(cmd[ci + 1], str(Path("/ws")))
        ad = cmd.index("--add-dir")
        self.assertEqual(cmd[ad + 1], str(Path("/ws")))
        mi = cmd.index("--model")
        self.assertEqual(cmd[mi + 1], "m1")

    def test_no_model_omits_flag(self):
        cmd = harness.build_copilot_command("p", Path("/ws"))
        self.assertNotIn("--model", cmd)
        self.assertEqual(cmd[0], "copilot")

    def test_validator_command_maps_kinds(self):
        vc = harness.validator_command("validate", "/a.html", python_exe="py")
        self.assertEqual(vc[0], "py")
        self.assertTrue(vc[1].replace("\\", "/").endswith("validate/validate.py"))
        # Harness re-validation is READ-ONLY: --no-stamp keeps it from writing the validated stamp.
        self.assertEqual(vc[-3:], ["--strict", "--no-stamp", "/a.html"])
        dc = harness.validator_command("deck_validate", "/d.html", python_exe="py")
        self.assertTrue(dc[1].replace("\\", "/").endswith("deck/deck_validate.py"))
        self.assertEqual(dc[-2:], ["--strict", "/d.html"])
        self.assertIsNone(harness.validator_command("portable", "/x.html"))
        self.assertIsNone(harness.validator_command("stamp", "/x.html"))
        with self.assertRaises(ValueError):
            harness.validator_command("bogus", "/x.html")


class ContentCheckTests(unittest.TestCase):
    _LAYER = '<div data-comment-key="doc-x">body</div>'

    def test_portable_rejects_companion_reference(self):
        bad = self._LAYER + '<link rel="stylesheet" href="commentable-html.css">'
        ok, _ = harness._content_check("portable", bad)
        self.assertFalse(ok)
        bad_js = self._LAYER + '<script src="./commentable-html.assets.js"></script>'
        ok2, _ = harness._content_check("portable", bad_js)
        self.assertFalse(ok2)

    def test_portable_accepts_self_contained_with_layer(self):
        ok, _ = harness._content_check("portable", "<html><body>%s</body></html>" % self._LAYER)
        self.assertTrue(ok)

    def test_portable_rejects_bare_html_without_layer(self):
        # A plain page with no companion ref must still fail - it carries no review layer.
        ok, _ = harness._content_check("portable", "<html><body>just prose</body></html>")
        self.assertFalse(ok)

    def test_portable_rejects_any_local_sidecar_but_allows_embedded_and_remote(self):
        # A portable file must need NO companion file - an arbitrary local sidecar (not just a
        # commentable-html.* one) fails; embedded data URIs and remote URLs are fine.
        local = self._LAYER + '<script src="sidecar.js"></script>'
        self.assertFalse(harness._content_check("portable", local)[0])
        local_css = self._LAYER + '<link rel="stylesheet" href="./theme.css">'
        self.assertFalse(harness._content_check("portable", local_css)[0])
        remote = self._LAYER + '<script src="https://cdn.example.com/x.js"></script>'
        self.assertTrue(harness._content_check("portable", remote)[0])
        data_uri = self._LAYER + '<img src="data:image/png;base64,AAAA">'
        self.assertTrue(harness._content_check("portable", data_uri)[0])

    def test_portable_rejects_non_src_href_companion_vectors(self):
        # Copilot review: companion files can also sneak in via srcset/poster/object data/svg image/
        # use href and CSS url(). Each local form must FAIL; the self-contained forms must PASS.
        for markup in (
            '<img srcset="small.jpg 1x, big.jpg 2x">',
            '<video poster="thumb.jpg"></video>',
            '<object data="report.pdf"></object>',
            '<image href="diagram.svg"></image>',
            '<use xlink:href="sprite.svg#icon"></use>',
            '<style>.hero{background:url(bg.png)}</style>',
            '<div style="background:url(\'panel.png\')"></div>',
        ):
            self.assertFalse(harness._content_check("portable", self._LAYER + markup)[0], markup)
        for markup in (
            '<img srcset="data:image/png;base64,AAAA 1x">',
            '<video poster="https://cdn.example.com/t.jpg"></video>',
            '<use xlink:href="#icon"></use>',
            '<style>.hero{background:url(data:image/png;base64,AAAA)}</style>',
        ):
            self.assertTrue(harness._content_check("portable", self._LAYER + markup)[0], markup)

    def test_portable_ignores_src_assignment_in_inline_script(self):
        # The runtime's inline JS assigns element.src; that must NOT be read as a companion ref.
        js = self._LAYER + '<script>var img=new Image(); img.src="whatever.png";</script>'
        self.assertTrue(harness._content_check("portable", js)[0])

    def test_stamp_requires_real_meta_tag(self):
        ok, _ = harness._content_check(
            "stamp", '<meta name="%s" content="2026-01-01T00:00:00Z">' % harness.STAMP_TOKEN)
        self.assertTrue(ok)

    def test_stamp_rejects_bare_token_in_script(self):
        # The bare token appears in the runtime JS, so a substring check would be vacuous.
        bare = 'var VALIDATED = "%s"; // not a meta tag' % harness.STAMP_TOKEN
        ok, _ = harness._content_check("stamp", bare)
        self.assertFalse(ok)
        empty, _ = harness._content_check("stamp", '<meta name="%s" content="">' % harness.STAMP_TOKEN)
        self.assertFalse(empty)
        none, _ = harness._content_check("stamp", "<html>no stamp</html>")
        self.assertFalse(none)


class SafePathTests(unittest.TestCase):
    def test_joins_relative_under_base(self):
        base = harness.scratch_root() / "ws"
        dest = harness._safe_subpath(base, "output/create.html")
        self.assertEqual(dest, (base / "output" / "create.html").resolve())

    def test_clamps_leading_separator(self):
        base = harness.scratch_root() / "ws"
        dest = harness._safe_subpath(base, "/output/a.html")
        self.assertTrue(str(dest).startswith(str(base.resolve())))

    def test_rejects_parent_escape(self):
        base = harness.scratch_root() / "ws"
        with self.assertRaises(ValueError):
            harness._safe_subpath(base, "../escape.html")


class WorkspaceTests(unittest.TestCase):
    def test_prepare_workspace_materializes_shipped_tools(self):
        # Each fresh workspace must contain the extracted shipped tool tree (create/retrofit/deck/
        # export/validate all reference tools/...). Extract into an OS temp dir, never the repo tree.
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td) / "ws"
            harness._prepare_workspace(prompts.flows_by_name()["create"], ws)
            skill = ws / ".github" / "skills" / "commentable-html"
            self.assertTrue((skill / "SKILL.md").is_file())
            self.assertTrue((skill / "tools" / "validate" / "validate.py").is_file())
            self.assertTrue((skill / "tools" / "deck" / "deck_scaffold.py").is_file())


class CorpusTests(unittest.TestCase):
    def test_required_flows_present(self):
        names = set(prompts.flow_names())
        for req in prompts.REQUIRED_FLOWS:
            self.assertIn(req, names, req)

    def test_each_flow_is_well_formed(self):
        for flow in prompts.FLOWS:
            self.assertTrue(flow["name"], flow)
            self.assertTrue(flow["prompt"].strip(), flow["name"])
            self.assertTrue(flow["output"].startswith("output/"), flow["name"])
            self.assertTrue(flow["validators"], flow["name"])
            for kind in flow["validators"]:
                self.assertIn(kind, KNOWN_VALIDATORS, (flow["name"], kind))
                # Must not raise for any listed validator kind.
                harness.validator_command(kind, "x.html")

    def test_flow_specific_validators(self):
        by_name = prompts.flows_by_name()
        self.assertIn("deck_validate", by_name["deck"]["validators"])
        self.assertIn("portable", by_name["export"]["validators"])
        # Every flow re-checks the AGENT left the validated stamp - the harness never writes it
        # (--no-stamp), so this proves the agent actually ran the mandatory finalize/validate handoff.
        for name in prompts.REQUIRED_FLOWS:
            self.assertIn("stamp", by_name[name]["validators"], name)


class PathTests(unittest.TestCase):
    def test_harness_resolves_real_paths(self):
        self.assertTrue(harness.PKG_SKILL.is_dir(), harness.PKG_SKILL)
        self.assertTrue((harness.PKG_SKILL / "SKILL.md").is_file())
        self.assertTrue(harness.VALIDATE_PY.is_file(), harness.VALIDATE_PY)
        self.assertTrue(harness.DECK_VALIDATE_PY.is_file(), harness.DECK_VALIDATE_PY)

    def test_stamp_token_matches_doc_stamp_writer(self):
        # The validated stamp is written by doc_stamp.py's VALIDATED_META, NOT by validate/*.py.
        # Guard STAMP_TOKEN against drifting from the real writer.
        doc_stamp = harness.SKILL_TOOLS / "authoring" / "doc_stamp.py"
        src = doc_stamp.read_text(encoding="utf-8")
        self.assertRegex(src, r'VALIDATED_META\s*=\s*["\']%s["\']' % re.escape(harness.STAMP_TOKEN))


if __name__ == "__main__":
    unittest.main()
