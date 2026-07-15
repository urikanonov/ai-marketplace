#!/usr/bin/env python3
"""Tests for scripts/validate_claude_compat.py.

The unit tests are hermetic (temp manifests, no `claude` CLI). One integration test runs the
structural check against the real repository so manifest drift fails in CI even where the
`claude` CLI is absent.
"""
import importlib.util
import json
import os
import tempfile
import unittest

_MODULE_PATH = os.path.join(os.path.dirname(__file__), "validate_claude_compat.py")
_spec = importlib.util.spec_from_file_location("validate_claude_compat", _MODULE_PATH)
vcc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vcc)

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh)


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _good_repo(root):
    """Build a minimal compatible repo layout under root and return it."""
    plugin = {
        "name": "demo",
        "version": "1.0.0",
        "description": "demo plugin",
        "author": {"name": "A", "email": "a@example.com"},
        "license": "MIT",
        "keywords": ["x"],
    }
    entry = {"name": "demo", "version": "1.0.0", "source": "./plugins/demo/pkg"}
    _write(os.path.join(root, ".github", "plugin", "marketplace.json"), {"plugins": [entry]})
    _write(os.path.join(root, ".claude-plugin", "marketplace.json"), {"plugins": [entry]})
    _write(os.path.join(root, "plugins", "demo", "pkg", "plugin.json"), plugin)
    claude_pj = dict(plugin, skills="./skills/")
    _write(os.path.join(root, "plugins", "demo", "pkg", ".claude-plugin", "plugin.json"), claude_pj)
    os.makedirs(os.path.join(root, "plugins", "demo", "pkg", "skills"), exist_ok=True)
    return root


class TestStructuralHappyPath(unittest.TestCase):
    def test_compatible_repo_has_no_errors(self):
        with tempfile.TemporaryDirectory() as root:
            _good_repo(root)
            self.assertEqual(vcc.structural_errors(root), [])


class TestStructuralFailures(unittest.TestCase):
    def test_missing_claude_marketplace(self):
        with tempfile.TemporaryDirectory() as root:
            _write(os.path.join(root, ".github", "plugin", "marketplace.json"), {"plugins": []})
            errs = vcc.structural_errors(root)
            self.assertTrue(any("missing Claude marketplace" in e for e in errs))

    def test_version_mismatch_between_marketplaces(self):
        with tempfile.TemporaryDirectory() as root:
            _good_repo(root)
            path = os.path.join(root, ".claude-plugin", "marketplace.json")
            data = _read(path)
            data["plugins"][0]["version"] = "9.9.9"
            _write(path, data)
            errs = vcc.structural_errors(root)
            self.assertTrue(any("version" in e for e in errs))

    def test_claude_plugin_not_in_copilot(self):
        with tempfile.TemporaryDirectory() as root:
            _good_repo(root)
            path = os.path.join(root, ".claude-plugin", "marketplace.json")
            data = _read(path)
            data["plugins"].append({"name": "ghost", "version": "1.0.0", "source": "./plugins/ghost/pkg"})
            _write(path, data)
            errs = vcc.structural_errors(root)
            self.assertTrue(any("ghost" in e and "not the Copilot" in e for e in errs))

    def test_mirror_field_mismatch(self):
        with tempfile.TemporaryDirectory() as root:
            _good_repo(root)
            path = os.path.join(root, "plugins", "demo", "pkg", ".claude-plugin", "plugin.json")
            data = _read(path)
            data["description"] = "different"
            _write(path, data)
            errs = vcc.structural_errors(root)
            self.assertTrue(any("description" in e for e in errs))

    def test_marketplace_field_drift_between_marketplaces(self):
        # A shared marketplace-entry field (here description) that drifts between the two manifests
        # must be caught, not only version/source. Guards the exact drift class the audit found.
        with tempfile.TemporaryDirectory() as root:
            _good_repo(root)
            gh_path = os.path.join(root, ".github", "plugin", "marketplace.json")
            gh = _read(gh_path)
            gh["plugins"][0]["description"] = "copilot description"
            _write(gh_path, gh)
            cl_path = os.path.join(root, ".claude-plugin", "marketplace.json")
            cl = _read(cl_path)
            cl["plugins"][0]["description"] = "claude description"
            _write(cl_path, cl)
            errs = vcc.structural_errors(root)
            self.assertTrue(any("description" in e for e in errs))

    def test_category_and_strict_may_differ_between_marketplaces(self):
        # `category` and `strict` are Copilot-marketplace-specific fields not defined by the Claude
        # schema, so their presence only on the Copilot side must NOT be flagged as drift.
        with tempfile.TemporaryDirectory() as root:
            _good_repo(root)
            gh_path = os.path.join(root, ".github", "plugin", "marketplace.json")
            gh = _read(gh_path)
            gh["plugins"][0]["category"] = "infrastructure"
            gh["plugins"][0]["strict"] = False
            _write(gh_path, gh)
            self.assertEqual(vcc.structural_errors(root), [])

    def test_missing_claude_plugin_manifest(self):
        with tempfile.TemporaryDirectory() as root:
            _good_repo(root)
            os.remove(os.path.join(root, "plugins", "demo", "pkg", ".claude-plugin", "plugin.json"))
            errs = vcc.structural_errors(root)
            self.assertTrue(any("missing Claude plugin manifest" in e for e in errs))

    def test_skills_path_must_resolve(self):
        with tempfile.TemporaryDirectory() as root:
            _good_repo(root)
            import shutil
            shutil.rmtree(os.path.join(root, "plugins", "demo", "pkg", "skills"))
            errs = vcc.structural_errors(root)
            self.assertTrue(any("skills path" in e for e in errs))


class TestRealRepo(unittest.TestCase):
    def test_repo_manifests_are_claude_compatible(self):
        self.assertEqual(vcc.structural_errors(_REPO_ROOT), [])


if __name__ == "__main__":
    unittest.main()
