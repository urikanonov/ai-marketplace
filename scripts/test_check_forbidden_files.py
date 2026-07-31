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


if __name__ == "__main__":
    unittest.main()


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
