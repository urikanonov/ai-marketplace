#!/usr/bin/env python3
"""Smoke test for the maintainer theme-evaluation harness (dev/eval/theme_eval.py).

The relocation moved the skill tools from pkg/skills/commentable-html/tools to dev/skill/tools, so
theme_eval.py (which imports those tools) must resolve the relocated stage. This pins that its CLI
loads without a ModuleNotFoundError - the exact breakage a relocation can silently introduce in a
tool that is not exercised by the main suites.

Run from the skill root:  python -m unittest discover -s tests -p "test_theme_eval_smoke.py" -v
"""
import os
import subprocess
import sys
import unittest

import _paths  # noqa: E402  shared pkg/dev split path constants

EVAL = os.path.join(_paths.DEV, "eval", "theme_eval.py")


class ThemeEvalSmokeTests(unittest.TestCase):
    @unittest.skipUnless(os.path.isfile(EVAL), "theme_eval.py not present")
    def test_cli_loads_and_resolves_relocated_tools(self):
        # --help forces the module (and its `import <tool>` from the relocated dev/skill/tools) to
        # load; a stale pre-relocation path would raise ModuleNotFoundError before argparse runs.
        r = subprocess.run([sys.executable, EVAL, "--help"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, "theme_eval.py --help must exit 0; stderr:\n" + r.stderr)
        self.assertIn("theme", (r.stdout + r.stderr).lower())


if __name__ == "__main__":
    unittest.main()
