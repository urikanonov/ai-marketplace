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
    # CMH-PKG-13
    def test_pkg_root_ships_license_matching_repo_root(self):
        pkg_license = os.path.join(PLUGIN_DIR, "LICENSE")
        self.assertTrue(os.path.isfile(pkg_license),
                        "the shipped pkg root must carry a LICENSE covering the hooks: %s" % pkg_license)
        repo_license = os.path.normpath(os.path.join(PLUGIN_DIR, "..", "..", "..", "LICENSE"))
        self.assertEqual(_read(pkg_license), _read(repo_license),
                         "the pkg root LICENSE must match the repository root LICENSE")

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

    # CMH-PKG-09: the marker hot-path check must be FILE-specific (bash `-f`, PowerShell -PathType
    # Leaf), matching run()'s os.path.isfile, so a directory that shares the marker name does not
    # short-circuit the hook before Python and permanently suppress extraction.
    def test_hook_marker_check_is_file_specific(self):
        copilot = json.loads(_read(COPILOT_HOOKS))["hooks"]["sessionStart"][0]["bash"]
        claude = json.loads(_read(CLAUDE_HOOKS))["hooks"]["SessionStart"][0]["hooks"][0]["command"]
        for cmd, label in ((copilot, "copilot bash"), (claude, "claude bash")):
            self.assertIn('[ -f "$m" ]', cmd, label + " marker guard must use -f (a real file)")
            self.assertNotIn('[ -e "$m" ]', cmd, label + " must not use -e (true for a directory)")
        self.assertIn("-PathType Leaf", _read(PS1),
                      "session-extract.ps1 marker check must use -PathType Leaf")

    # CMH-PKG-09: the SHIPPED bash hook commands (Copilot + Claude), run verbatim under a real bash,
    # actually extract cold, no-op warm, and are NOT short-circuited by a marker-named directory.
    def test_shipped_bash_hooks_extract_end_to_end(self):
        import shutil
        import subprocess
        import tempfile
        bash = shutil.which("bash")
        if not bash:
            self.skipTest("no bash on PATH")
        # The hook discovers python3/python/py; skip if none is usable under this bash.
        probe = subprocess.run([bash, "-c",
                                'for c in python3 python py; do command -v "$c" >/dev/null 2>&1 && '
                                'exit 0; done; exit 1'], capture_output=True)
        if probe.returncode != 0:
            self.skipTest("no python discoverable by the hook under bash")
        version = _version()
        marker_name = ".skill-resources-" + version + ".ok"
        cases = (
            ("copilot", json.loads(_read(COPILOT_HOOKS))["hooks"]["sessionStart"][0]["bash"], None),
            ("claude",
             json.loads(_read(CLAUDE_HOOKS))["hooks"]["SessionStart"][0]["hooks"][0]["command"],
             "PLUGIN_ROOT"),
        )
        for agent, command, root_mode in cases:
            with self.subTest(agent=agent):
                sandbox = tempfile.mkdtemp(prefix="cmh-hook-" + agent + "-")
                self.addCleanup(shutil.rmtree, sandbox, ignore_errors=True)
                shutil.copytree(PLUGIN_DIR, sandbox, dirs_exist_ok=True)
                sk = os.path.join(sandbox, "skills", "commentable-html")
                env = dict(os.environ)
                if root_mode == "PLUGIN_ROOT":
                    env["CLAUDE_PLUGIN_ROOT"] = sandbox
                # Cold run: extracts and writes the marker file.
                r1 = subprocess.run([bash, "-c", command], cwd=sandbox, env=env, capture_output=True)
                self.assertEqual(r1.returncode, 0, agent + " cold hook must exit 0")
                self.assertTrue(os.path.isfile(os.path.join(sk, marker_name)),
                                agent + ": cold run must write the marker file")
                self.assertTrue(os.path.isfile(os.path.join(sk, "tools", "validate", "validate.py")),
                                agent + ": cold run must extract the tools tree")
                # Warm run: marker present -> the hot path must exit BEFORE spawning Python. Prove
                # it by swapping the extractor for a canary that would leave a sentinel if invoked.
                extractor = os.path.join(sandbox, "hooks", "extract_resources.py")
                real_extractor = _read(extractor)
                sentinel = os.path.join(sandbox, "canary-ran")
                with open(extractor, "w", encoding="utf-8") as fh:
                    fh.write("import sys\nopen(r'" + sentinel + "', 'w').close()\n")
                r2 = subprocess.run([bash, "-c", command], cwd=sandbox, env=env, capture_output=True)
                self.assertEqual(r2.returncode, 0, agent + " warm hook must exit 0")
                self.assertFalse(os.path.exists(sentinel),
                                 agent + ": warm hot path must not spawn Python (marker present)")
                with open(extractor, "w", encoding="utf-8") as fh:
                    fh.write(real_extractor)  # restore the real extractor for the marker-dir case
                # Marker-DIRECTORY: replace the marker file with a directory of the same name; the
                # -f guard must NOT treat it as done, so extraction runs again and restores a file.
                os.remove(os.path.join(sk, marker_name))
                os.mkdir(os.path.join(sk, marker_name))
                r3 = subprocess.run([bash, "-c", command], cwd=sandbox, env=env, capture_output=True)
                self.assertEqual(r3.returncode, 0, agent + " marker-dir hook must exit 0")
                self.assertTrue(os.path.isfile(os.path.join(sk, marker_name)),
                                agent + ": a marker-named directory must not suppress extraction")

    # CMH-PKG-09: the shipped PowerShell launcher, run verbatim, cold-extracts, is not fooled by a
    # marker-named directory (-PathType Leaf), and always exits 0. Windows-only; skips if no usable
    # Python is discoverable (the launcher still exits 0, it just does no work).
    @unittest.skipUnless(os.name == "nt", "Windows PowerShell launcher")
    def test_powershell_launcher_extracts_end_to_end(self):
        import shutil
        import subprocess
        import tempfile
        pwsh = shutil.which("powershell") or shutil.which("pwsh")
        if not pwsh:
            self.skipTest("no PowerShell on PATH")
        version = _version()
        marker_name = ".skill-resources-" + version + ".ok"
        sandbox = tempfile.mkdtemp(prefix="cmh-ps1-")
        self.addCleanup(shutil.rmtree, sandbox, ignore_errors=True)
        shutil.copytree(PLUGIN_DIR, sandbox, dirs_exist_ok=True)
        sk = os.path.join(sandbox, "skills", "commentable-html")
        ps1 = os.path.join(sandbox, "hooks", "session-extract.ps1")

        def _run():
            return subprocess.run([pwsh, "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
                                   "Bypass", "-File", ps1, "-Version", version],
                                  cwd=sandbox, capture_output=True)
        r1 = _run()
        self.assertEqual(r1.returncode, 0, "the launcher must always exit 0")
        if not os.path.isfile(os.path.join(sk, marker_name)):
            self.skipTest("the launcher found no usable Python on this host")
        self.assertTrue(os.path.isfile(os.path.join(sk, "tools", "validate", "validate.py")),
                        "cold run must extract the tools tree")
        # Marker-DIRECTORY: -PathType Leaf must not treat it as done, so extraction runs again.
        os.remove(os.path.join(sk, marker_name))
        os.mkdir(os.path.join(sk, marker_name))
        r2 = _run()
        self.assertEqual(r2.returncode, 0, "the launcher must exit 0 on the marker-dir case")
        self.assertTrue(os.path.isfile(os.path.join(sk, marker_name)),
                        "a marker-named directory must not suppress the PowerShell launcher")

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
