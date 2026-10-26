"""Execute the Pages dependency step without package installation or network access."""
import os
from pathlib import Path
import shutil
import subprocess
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
BASH = shutil.which("bash")
if os.name == "nt" and shutil.which("git"):
    git_bash = Path(shutil.which("git")).resolve().parents[1] / "bin" / "bash.exe"
    BASH = str(git_bash) if git_bash.is_file() else None


def site_job():
    return yaml.safe_load(
        (ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
    )["jobs"]["site"]


def install_step():
    return next(step for step in site_job()["steps"]
                if step["name"] == "Install ffmpeg for the clip scan")


@unittest.skipUnless(BASH, "Bash is required to exercise the Linux dependency step")
class PagesFfmpegTests(unittest.TestCase):
    def run_install(self, fail_install="", fail_update=""):
        harness = """
set -euo pipefail
install_calls=0
sudo() {
  printf 'APT %s\\n' "$*"
  case " $* " in
    *" install "*)
      install_calls=$((install_calls + 1))
      if [ "$FAIL_INSTALL" = all ] ||
         { [ "$FAIL_INSTALL" = first ] && [ "$install_calls" = 1 ]; }; then
        return 23
      fi ;;
    *" update "*)
      if [ "$FAIL_UPDATE" = yes ]; then return 17; fi ;;
    *) return 99 ;;
  esac
}
"""
        result = subprocess.run(
            [BASH, "--noprofile", "--norc", "-c", harness + install_step()["run"]],
            env={**os.environ, "FAIL_INSTALL": fail_install, "FAIL_UPDATE": fail_update},
            text=True, encoding="utf-8", capture_output=True, check=False, timeout=10,
        )
        calls = [line for line in result.stdout.splitlines() if line.startswith("APT ")]
        return result, calls

    def test_cached_indexes_avoid_an_unnecessary_global_update(self):
        result, calls = self.run_install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(calls), 1)
        self.assertIn(" install ", calls[0])
        self.assertIn("--no-install-recommends ffmpeg", calls[0])

    def test_stale_indexes_refresh_only_ubuntu_and_retry_install(self):
        result, calls = self.run_install(fail_install="first")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(calls), 3)
        self.assertIn(" install ", calls[0])
        self.assertTrue(calls[1].endswith(" update"))
        self.assertIn("Dir::Etc::sourcelist=sources.list.d/ubuntu.sources", calls[1])
        self.assertIn("Dir::Etc::sourceparts=-", calls[1])
        self.assertIn("APT::Update::Error-Mode=any", calls[1])
        self.assertIn(" install ", calls[2])
        self.assertIn("::warning::", result.stdout)

    def test_failed_refresh_stops_without_a_success_shaped_fallback(self):
        result, calls = self.run_install(fail_install="first", fail_update="yes")
        self.assertEqual(result.returncode, 17)
        self.assertEqual(len(calls), 2)

    def test_failed_retry_is_fatal(self):
        result, calls = self.run_install(fail_install="all")
        self.assertEqual(result.returncode, 23)
        self.assertEqual(len(calls), 3)

    def test_all_package_operations_have_finite_network_and_lock_waits(self):
        _, calls = self.run_install(fail_install="first")
        self.assertEqual(len(calls), 3)
        for call in calls:
            for option in ("Acquire::Retries=2", "Acquire::http::Timeout=30",
                           "Acquire::https::Timeout=30", "DPkg::Lock::Timeout=60"):
                self.assertIn(option, call)


class PagesFfmpegWiringTests(unittest.TestCase):
    def test_install_is_bounded_and_the_decoder_scan_remains_mandatory(self):
        self.assertEqual(install_step()["timeout-minutes"], 10)
        self.assertEqual(site_job()["timeout-minutes"], 15)
        steps = site_job()["steps"]
        scan = next(step for step in steps if "check_clip_chrome.py" in step.get("run", ""))
        self.assertIn("--require-ffmpeg", scan["run"])
        self.assertNotIn("if", scan)
        self.assertNotIn("continue-on-error", install_step())
        self.assertLess(steps.index(install_step()), steps.index(scan))
