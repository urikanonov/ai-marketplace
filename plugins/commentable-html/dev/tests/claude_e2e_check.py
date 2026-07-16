#!/usr/bin/env python3
"""LOCAL, on-demand E2E check that Claude Code stamps its session id (CMH-STAMP-04).

This is NOT a CI test - it drives the real `claude` CLI, which the check-in gate cannot do, and it
is named without a `test_` prefix so pytest / unittest never auto-collect it. The shared flow lives
in `_session_e2e.py`; this wrapper only supplies Claude's CLI invocation.

Usage (from anywhere):
    python plugins/commentable-html/dev/tests/claude_e2e_check.py
    python .../claude_e2e_check.py --claude "C:\\Users\\me\\.local\\bin\\claude.exe" --effort low
    CLAUDE_BIN=/path/to/claude python .../claude_e2e_check.py

Exit codes: 0 = PASS, 1 = ran but the stamp was wrong, 2 = could not run (claude not found / timeout).
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import _session_e2e as core  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description="Local Claude Code E2E session-id stamp check.")
    ap.add_argument("--claude", default=None, help="path to the claude CLI")
    ap.add_argument("--effort", default="medium", help="claude --effort level (default: medium)")
    ap.add_argument("--timeout", type=int, default=300, help="seconds to wait for claude")
    args = ap.parse_args(argv)

    claude = core.resolve_bin(args.claude, "CLAUDE_BIN", "claude",
                              r"%USERPROFILE%\.local\bin\claude.exe")

    def make_argv(cli_bin, prompt):
        return [cli_bin, "--print", "--dangerously-skip-permissions",
                "--effort", args.effort, prompt]

    return core.run_e2e("claude", claude, make_argv, "claude", timeout=args.timeout)


if __name__ == "__main__":
    sys.exit(main())
