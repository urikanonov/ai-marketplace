#!/usr/bin/env python3
"""LOCAL, on-demand E2E check that GitHub Copilot CLI stamps its session id (CMH-STAMP-04).

This is NOT a CI test - it drives the real `copilot` CLI, which the check-in gate cannot do, and it
is named without a `test_` prefix so pytest / unittest never auto-collect it. The shared flow lives
in `_session_e2e.py`; this wrapper only supplies Copilot's non-interactive CLI invocation
(`--prompt` + `--allow-all-tools --allow-all-paths` so it runs the generator without prompting).

Usage (from anywhere):
    python plugins/commentable-html/dev/tests/copilot_e2e_check.py
    python .../copilot_e2e_check.py --copilot "C:\\Users\\me\\AppData\\Local\\GitHubCopilotCLI\\copilot.exe"
    COPILOT_BIN=/path/to/copilot python .../copilot_e2e_check.py

Exit codes: 0 = PASS, 1 = ran but the stamp was wrong, 2 = could not run (copilot not found / timeout).
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import _session_e2e as core  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description="Local GitHub Copilot CLI E2E session-id stamp check.")
    ap.add_argument("--copilot", default=None, help="path to the copilot CLI")
    ap.add_argument("--timeout", type=int, default=300, help="seconds to wait for copilot")
    args = ap.parse_args(argv)

    copilot = core.resolve_bin(args.copilot, "COPILOT_BIN", "copilot",
                               r"%LOCALAPPDATA%\GitHubCopilotCLI\copilot.exe")

    def make_argv(cli_bin, prompt):
        return [cli_bin, "--prompt", prompt, "--allow-all-tools", "--allow-all-paths"]

    return core.run_e2e("copilot", copilot, make_argv, "copilot", timeout=args.timeout)


if __name__ == "__main__":
    sys.exit(main())
