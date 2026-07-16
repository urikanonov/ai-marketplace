#!/usr/bin/env python3
"""Tests for the shipped SessionStart hooks and the minimal packaged skill (pkg/dev split).

The plugin ships a compact skills/commentable-html (SKILL.md, LICENSE, skill-resources.zip) plus a
SessionStart hook that extracts the zip on first run. These tests pin the shipped wiring:

- CMH-PKG-07 the shipped skill dir is minimal (only SKILL.md, LICENSE, skill-resources.zip);
- CMH-PKG-08 the zip carries the runtime dirs (tools/references/dist/vendor) and NOT the large
  tutorial/examples, and unpacks to reproduce the runtime tools;
- CMH-PKG-09 both hook configs (Copilot hooks.json + Claude hooks/hooks.json) do a version-stamped
  marker existence check on the HOT PATH before ever invoking Python, and only run the extractor on
  the cold path;
- CMH-PKG-10 the hook marker version is stamped to dev/VERSION (no drift), and the extractor script
  ships next to the hooks.

Standard library only. Run from the skill root:
  python -m unittest discover -s tests -p "test_session_hooks.py" -v
"""
import importlib.util
import json
import os
import re
import unittest
import zipfile

import _paths

DEV = _paths.DEV
PKG_SHIPPED = _paths.PKG_SHIPPED
HOOKS = _paths.HOOKS
PLUGIN_DIR = os.path.dirname(os.path.dirname(PKG_SHIPPED))  # pkg/
COPILOT_HOOKS = os.path.join(PLUGIN_DIR, "hooks.json")
CLAUDE_HOOKS = os.path.join(PLUGIN_DIR, "hooks", "hooks.json")
PS1 = os.path.join(PLUGIN_DIR, "hooks", "session-extract.ps1")
ZIP = os.path.join(PKG_SHIPPED, "skill-resources.zip")


def _version():
    with open(os.path.join(DEV, "VERSION"), encoding="utf-8") as fh:
        return fh.read().strip()


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _load_extractor():
    path = os.path.join(HOOKS, "extract_resources.py")
    spec = importlib.util.spec_from_file_location("extract_resources", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class MinimalPackageTests(unittest.TestCase):
    # CMH-PKG-07
    def test_shipped_skill_dir_is_minimal(self):
        entries = sorted(os.listdir(PKG_SHIPPED))
        self.assertEqual(entries, ["LICENSE", "SKILL.md", "skill-resources.zip"],
                         "the shipped skill dir must carry only SKILL.md, LICENSE, and the zip; "
                         "everything else ships inside skill-resources.zip")

    # CMH-PKG-08
    def test_zip_carries_runtime_dirs_but_not_tutorial_or_examples(self):
        with zipfile.ZipFile(ZIP) as zf:
            names = zf.namelist()
        tops = {n.split("/", 1)[0] for n in names}
        self.assertEqual(tops, {"tools", "references", "vendor", "dist"},
                         "the zip must carry exactly the runtime dirs, not docs/ or examples/")
        # A couple of load-bearing members are present.
        self.assertTrue(any(n == "dist/PORTABLE.html" for n in names))
        self.assertTrue(any(n.startswith("tools/") and n.endswith(".py") for n in names))
        # No machine-specific junk leaked in.
        self.assertFalse(any("__pycache__" in n or n.endswith(".pyc") for n in names))

    def test_zip_extracts_to_a_working_tools_tree(self):
        import tempfile

        extractor = _load_extractor()
        dest = tempfile.mkdtemp(prefix="cmh-pkg-")
        self.addCleanup(self._rmtree, dest)
        rc = extractor.run(dest, _version(), zip_path=ZIP)
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.isfile(os.path.join(dest, "tools", "validate", "validate.py")))
        self.assertTrue(os.path.isfile(os.path.join(dest, "dist", "PORTABLE.html")))
        self.assertTrue(os.path.isfile(
            os.path.join(dest, ".skill-resources-" + _version() + ".ok")))

    @staticmethod
    def _rmtree(path):
        import shutil

        shutil.rmtree(path, ignore_errors=True)


class HookWiringTests(unittest.TestCase):
    def test_extractor_ships_next_to_the_hooks(self):
        self.assertTrue(os.path.isfile(os.path.join(HOOKS, "extract_resources.py")))

    # CMH-PKG-10
    def test_hook_marker_version_matches_dev_version(self):
        version = _version()
        for hook in (COPILOT_HOOKS, CLAUDE_HOOKS):
            text = _read(hook)
            self.assertIn(".skill-resources-" + version + ".ok", text,
                          hook + " marker is not stamped to dev/VERSION")
            self.assertNotRegex(
                text, r"\.skill-resources-(?!" + re.escape(version) + r"\.ok)[0-9]+\.[0-9]+\.[0-9]+\.ok",
                hook + " carries a stale marker version")

    # CMH-PKG-09: the hot path checks the marker before any Python spawn. The Copilot bash path does
    # it inline; the Windows path does it in the -File launcher session-extract.ps1.
    def test_copilot_hook_checks_marker_before_python(self):
        entry = json.loads(_read(COPILOT_HOOKS))["hooks"]["sessionStart"][0]
        bash = entry["bash"]
        self._assert_marker_before_python(bash, "copilot bash")
        # The PowerShell field is a thin -File launcher; the logic lives in the .ps1.
        self.assertIn("session-extract.ps1", entry["powershell"])
        self.assertIn("-File", entry["powershell"])
        self._assert_marker_before_python(_read(PS1), "session-extract.ps1")

    def test_claude_hook_checks_marker_before_python(self):
        entry = json.loads(_read(CLAUDE_HOOKS))["hooks"]["SessionStart"][0]
        self.assertEqual(entry.get("matcher"), "startup|resume")
        self._assert_marker_before_python(entry["hooks"][0]["command"], "claude bash")

    def test_plugin_json_wires_the_copilot_hooks(self):
        pj = json.loads(_read(os.path.join(PLUGIN_DIR, "plugin.json")))
        self.assertEqual(pj.get("hooks"), "hooks.json")

    # CMH-PKG-09: the interpreter is probed (skip the Windows Store python3 alias stub) and isolated,
    # and the PowerShell launcher forces a success exit (non-blocking).
    def test_hooks_probe_interpreter_and_skip_windowsapps_stub(self):
        copilot = json.loads(_read(COPILOT_HOOKS))["hooks"]["sessionStart"][0]
        claude = json.loads(_read(CLAUDE_HOOKS))["hooks"]["SessionStart"][0]["hooks"][0]["command"]
        for cmd in (copilot["bash"], claude, _read(PS1)):
            self.assertIn("WindowsApps", cmd, "hook must skip the WindowsApps python alias stub")
            self.assertIn("-c", cmd, "hook must probe that the interpreter actually runs")
            # Pin the exact probe body: `-c pass` (a no-op statement). The round-2 Windows-breaker
            # was `-c ''` - PowerShell drops the empty positional, so `python -I -c` is a syntax
            # error and the probe rejects every real interpreter, silently disabling extraction.
            self.assertRegex(cmd, r"-c\s+['\"]?pass['\"]?",
                             "hook interpreter probe must run `-c pass`, never an empty `-c ''`")
            self.assertIn(" -I ", " " + cmd + " ", "hook must run the extractor isolated (-I)")

    def test_powershell_launcher_forces_success_exit(self):
        self.assertRegex(_read(PS1).rstrip() + "\n", r"exit 0\s*$",
                         "session-extract.ps1 must force exit 0 so a failed extraction is "
                         "non-blocking")

    # CMH-PKG-09: the Windows launcher resolves its paths from $PSScriptRoot (the script's own
    # directory), NOT the process CWD, so it works regardless of where Copilot invokes the hook.
    def test_powershell_launcher_is_scriptroot_anchored(self):
        self.assertIn("$PSScriptRoot", _read(PS1),
                      "session-extract.ps1 must anchor its paths to $PSScriptRoot, not the CWD")

    def _assert_marker_before_python(self, cmd, label):
        cmd = self._strip_comments(cmd)
        marker_at = cmd.find(".skill-resources-")
        py_at = self._first_python_index(cmd)
        self.assertNotEqual(marker_at, -1, label + ": no marker check")
        self.assertNotEqual(py_at, -1, label + ": no python invocation")
        self.assertLess(marker_at, py_at,
                        label + ": the marker check must precede the python invocation")
        self.assertIn("extract_resources.py", cmd)

    @staticmethod
    def _strip_comments(cmd):
        # Drop whole-line comments (PowerShell/# lines) so a comment mentioning "python" does not
        # register as an invocation before the marker check.
        return "\n".join(ln for ln in cmd.splitlines() if not ln.lstrip().startswith("#"))

    @staticmethod
    def _first_python_index(cmd):
        idxs = [cmd.find(tok) for tok in ("python3", "python") if cmd.find(tok) != -1]
        return min(idxs) if idxs else -1


if __name__ == "__main__":
    unittest.main()
