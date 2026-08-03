#!/usr/bin/env python3
"""Tests for scripts/check_forbidden_files.py.

Run from the repo root:
    python -m unittest discover -s scripts -p "test_*.py"
"""

import importlib.util
import unittest
from pathlib import Path

_MODULE_PATH = Path(__file__).with_name("check_forbidden_files.py")
_spec = importlib.util.spec_from_file_location("check_forbidden_files", _MODULE_PATH)
cff = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cff)


class IsForbiddenTest(unittest.TestCase):
    def test_flags_secret_bearing_files(self):
        for path in [
            ".env",
            ".env.local",
            "config/prod.pem",
            "deep/nested/server.key",
            "certs/cert.pfx",
            "keystore.p12",
            "home/.ssh/id_rsa",
            "id_ed25519",
            "vendor/keys/id_ecdsa",
            "SERVER.PEM",
            "config/PROD.KEY",
            "ID_RSA",
            "backup.PFX",
            ".envrc",
            "release.env",
            ".netrc",
            ".npmrc",
            "auth/credentials.json",
            "credentials.prod.json",
            "service-account.json",
            "gcp/service-account.ci.json",
            "keys/apns.p8",
            "wallet.kdb",
        ]:
            self.assertTrue(cff.is_forbidden(path), path)

    def test_allows_safe_files(self):
        for path in [
            ".env.example",
            ".env.sample",
            "config/.env.template",
            "config/.ENV.EXAMPLE",
            "README.md",
            "scripts/validate_markdown.py",
            "docs/public.pem.example",
            "notes.txt",
        ]:
            self.assertFalse(cff.is_forbidden(path), path)


class IsScratchArtifactTest(unittest.TestCase):
    """A committed diff dump is how `changes.diff` (180KB, unreferenced) reached main.

    The root-anchored .gitignore block only swallows scratch at the REPO ROOT, so a dump
    written into a subdirectory - which is where an agent's cwd usually is - sails past it
    and gets swept up by `git add -A`.
    """

    def test_flags_scratch_dumps_anywhere_in_the_tree(self):
        for path in [
            "changes.diff",
            ".github/skills/demo-video/changes.diff",
            "plugins/commentable-html/dev/tmp_diff.patch",
            "deep/nested/OUT.DIFF",
        ]:
            with self.subTest(path=path):
                self.assertTrue(cff.is_scratch_artifact(path), f"{path} should be refused")

    def test_leaves_real_files_alone(self):
        for path in [
            "scripts/check_forbidden_files.py",
            "docs/diffing.md",
            "plugins/commentable-html/dev/assets/js/30-diff.js",
            "site/pages/index.html",
        ]:
            with self.subTest(path=path):
                self.assertFalse(cff.is_scratch_artifact(path), f"{path} should be allowed")

    def test_the_repo_tracks_no_scratch_dumps(self):
        files = cff.tracked_files()
        if files is None:
            self.skipTest("git unavailable")
        offenders = [p for p in files if cff.is_scratch_artifact(p)]
        self.assertEqual(offenders, [], f"scratch dumps are tracked: {offenders}")


class RootScratchTest(unittest.TestCase):
    """A probe dropped at the repo ROOT is scratch, whatever its extension.

    An agent's one-off probe lands beside AGENTS.md as `test_svg_exec.html`, `temp.txt`,
    or a bare `x`; the *.diff / *.patch rule never saw those shapes, so a `git add -A`
    could commit one and every gate would stay green. The repo root holds only its
    documented top-level files, so the rule is ANCHORED there - a real report under
    examples/ or a page under site/ is untouched.
    """

    def test_flags_probes_at_the_repo_root(self):
        for path in [
            "test_svg_exec.html",
            "test_importmap.html",
            "TEST_CSP.HTML",
            "test-fp12.js",
            "temp.txt",
            "temp.html",
            "test_out.txt",
            "x",
            "out.json",
            "err.txt",
            "tmp_probe.py",
            "probe_svg.mjs",
            "scratch.ts",
            "diff.txt",
            "js-diff.txt",
            "local.js",
            "old_parsing.py",
        ]:
            with self.subTest(path=path):
                self.assertTrue(cff.is_scratch_artifact(path), f"{path} should be refused")

    def test_leaves_legitimate_files_alone(self):
        for path in [
            "plugins/commentable-html/examples/report-basic.html",
            "site/dist/index.html",
            "site/pages/index.html",
            "plugins/commentable-html/dev/tests/fixtures/report.html",
            "plugins/commentable-html/dev/tests/test_build.py",
            "scripts/test_check_forbidden_files.py",
            "site/src/site.js",
            "docs/notes.txt",
            "plugins/commentable-html/dev/skill/dist/x",
        ]:
            with self.subTest(path=path):
                self.assertFalse(cff.is_scratch_artifact(path), f"{path} should be allowed")

    def test_keeps_the_real_top_level_files(self):
        for path in [
            "README.md",
            "AGENTS.md",
            "CLAUDE.md",
            "LICENSE",
            "SECURITY.md",
            "CONTRIBUTING.md",
            "MAINTAINING.md",
            "CODE_OF_CONDUCT.md",
            ".gitignore",
            ".gitattributes",
            ".editorconfig",
            ".ignore",
            "ai-marketplace.code-workspace",
        ]:
            with self.subTest(path=path):
                self.assertFalse(cff.is_scratch_artifact(path), f"{path} should be allowed")

    def test_every_tracked_root_file_is_allowed(self):
        files = cff.tracked_files()
        if files is None:
            self.skipTest("git unavailable")
        root = [p for p in files if "/" not in p]
        offenders = [p for p in root if cff.is_scratch_artifact(p)]
        self.assertEqual(offenders, [], f"scratch is tracked at the repo root: {offenders}")


if __name__ == "__main__":
    unittest.main()
