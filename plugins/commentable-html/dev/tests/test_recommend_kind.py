#!/usr/bin/env python3
"""CMH-KIND-04: recommend_kind.py suggests report, plan, or slides from content signals."""
import os
import subprocess
import sys
import unittest
import uuid

import _paths  # noqa: E402

TOOLS = _paths.TOOLS
RECOMMEND_PY = os.path.join(TOOLS, "authoring", "recommend_kind.py")

sys.path.insert(0, TOOLS)
import recommend_kind  # noqa: E402


def _rmtree(path):
    import shutil
    shutil.rmtree(path, ignore_errors=True)


class RecommendKindTests(unittest.TestCase):
    def _tmpdir(self):
        root = os.path.normpath(os.path.join(_paths.DEV, "..", "..", "..", "tmp"))
        os.makedirs(root, exist_ok=True)
        d = os.path.join(root, "test-recommend-kind-" + uuid.uuid4().hex)
        os.mkdir(d)
        self.addCleanup(lambda: _rmtree(d))
        return d

    def _write(self, name, text):
        d = self._tmpdir()
        path = os.path.join(d, name)
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        return path

    def test_recommends_report_from_diff_signals(self):
        content = """# Weekly review

```diff
@@ -10,6 +10,7 @@ def handler():
- old()
+ new()
```
"""
        recommendation = recommend_kind.recommend_kind(content, filename="weekly-review.md")
        self.assertEqual(recommendation.kind, "report")
        self.assertTrue(any("diff" in item.message for item in recommendation.evidence))
        self.assertTrue(any("@@ hunk" in item.message for item in recommendation.evidence))

    def test_recommends_plan_from_comparison_and_callout_signals(self):
        content = """
<table>
<tr><th>Option</th><th>Pros</th><th>Cons</th><th>Decision</th></tr>
<tr><td>A</td><td>Fast</td><td>Risky</td><td>No</td></tr>
</table>
<blockquote><strong>Recommendation:</strong> choose B.</blockquote>
"""
        recommendation = recommend_kind.recommend_kind(content, filename="migration-notes.html")
        self.assertEqual(recommendation.kind, "plan")
        self.assertTrue(any("comparison table" in item.message for item in recommendation.evidence))
        self.assertTrue(any("callout" in item.message for item in recommendation.evidence))

    def test_recommends_slides_from_hr_and_h1_cadence(self):
        content = """
<h1>Opening</h1>
<p>First slide.</p>
<hr>
<h1>Why it matters</h1>
<hr>
<h1>How it works</h1>
<hr>
<h1>Close</h1>
"""
        recommendation = recommend_kind.recommend_kind(content, filename="garden-talk.html")
        self.assertEqual(recommendation.kind, "slides")
        self.assertTrue(any("hr divider" in item.message for item in recommendation.evidence))
        self.assertTrue(any("h1 cadence" in item.message for item in recommendation.evidence))

    def test_filename_hint_contributes_to_the_score(self):
        recommendation = recommend_kind.recommend_kind(
            "<p>Implementation notes.</p>", filename="rollout-plan.md")
        self.assertEqual(recommendation.kind, "plan")
        self.assertTrue(any("filename" in item.message for item in recommendation.evidence))

    def test_cli_prints_recommendation_with_evidence(self):
        path = self._write("q3-plan.html", "<table><tr><th>Option</th><th>Pros</th><th>Cons</th></tr></table>")
        result = subprocess.run(
            [sys.executable, RECOMMEND_PY, path],
            cwd=TOOLS, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Recommended --kind: plan", result.stdout)
        self.assertIn("Evidence:", result.stdout)
        self.assertIn("comparison table", result.stdout)

    def test_mismatch_warning_is_advisory(self):
        path = self._write("deck.html", "<h1>One</h1><hr><h1>Two</h1><hr><h1>Three</h1>")
        result = subprocess.run(
            [sys.executable, RECOMMEND_PY, path, "--kind", "report"],
            cwd=TOOLS, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Recommended --kind: slides", result.stdout)
        self.assertIn("recommend_kind: warning: --kind report differs from recommended --kind slides", result.stderr)


if __name__ == "__main__":
    unittest.main()
