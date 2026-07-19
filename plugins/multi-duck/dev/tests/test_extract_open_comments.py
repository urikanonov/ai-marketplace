#!/usr/bin/env python3
"""Covering tests for the shipped multi-duck open-comments extractor (MDUCK-EXTRACT-09).

The multi-duck skill ships tools/extract_open_comments.py so the panel runs a real file instead of
rehydrating the parser from SKILL.md on every activation. These tests feed sample commentable HTML
with embeddedComments/handledCommentIds and assert the extractor returns the OPEN comments (embedded
minus handled) plus the doc label, source, and rendered plan text. Standard library only; discovered
by the plugin-tests `python` job and the pre-push hook (plugins/*/dev/tests/test_*.py).
"""
import os
import subprocess
import sys
import tempfile
import unittest

# tests -> dev -> multi-duck -> plugins -> repo root (five levels up from this file).
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
EXTRACTOR = os.path.join(
    REPO_ROOT, "plugins", "multi-duck", "pkg", "skills", "multi-duck",
    "tools", "extract_open_comments.py")

SAMPLE_HTML = """<!DOCTYPE html>
<!-- BEGIN: commentable-html v2 -->
<html>
<body>
<main id="commentRoot" data-comment-key="demo-key" data-doc-label="My Plan"
      data-doc-source="plan.md">
  <h1>Rollout plan</h1>
  <p>Ship the migration in two phases.</p>
</main>
<script id="embeddedComments" type="application/json">
[
  {"id": "c1", "note": "phase one looks risky", "quote": "two phases",
   "headingPath": [{"text": "Rollout plan"}]},
  {"id": "c2", "note": "already handled", "quote": "migration",
   "headingPath": [{"text": "Rollout plan"}]},
  {"id": "c3", "note": "add a rollback step", "section": "Rollout plan"}
]
</script>
<script id="handledCommentIds" type="application/json">["c2"]</script>
</body>
</html>
"""


def _run(html_text):
    """Write html_text to a temp file, run the shipped extractor on it, return stdout."""
    fd, path = tempfile.mkstemp(suffix=".html")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(html_text)
        proc = subprocess.run(
            [sys.executable, EXTRACTOR, path],
            capture_output=True, text=True, encoding="utf-8")
        assert proc.returncode == 0, "extractor failed: %s" % proc.stderr
        return proc.stdout
    finally:
        os.remove(path)


class ExtractOpenCommentsTests(unittest.TestCase):
    def test_extractor_is_shipped_under_tools(self):
        self.assertTrue(os.path.isfile(EXTRACTOR),
                        "multi-duck must ship tools/extract_open_comments.py")

    def test_open_comments_are_embedded_minus_handled(self):
        out = _run(SAMPLE_HTML)
        # Three embedded comments, one handled (c2), so two open (c1 and c3).
        self.assertIn("OPEN_COMMENTS: 2 of 3 embedded", out)
        self.assertIn("[c1]", out)
        self.assertIn("[c3]", out)
        self.assertNotIn("[c2]", out)
        # The open comment bodies come through.
        self.assertIn("phase one looks risky", out)
        self.assertIn("add a rollback step", out)
        self.assertNotIn("already handled", out)

    def test_label_source_and_plan_text_are_extracted(self):
        out = _run(SAMPLE_HTML)
        self.assertIn("LABEL: My Plan", out)
        self.assertIn("SOURCE: plan.md", out)
        # PLAN_TEXT is the rendered #commentRoot text, not the script JSON.
        self.assertIn("PLAN_TEXT:", out)
        self.assertIn("Ship the migration in two phases.", out)
        self.assertNotIn("looks risky", out.split("PLAN_TEXT:", 1)[1])

    def test_no_embedded_comments_yields_zero_open(self):
        html = SAMPLE_HTML.replace(
            '<script id="handledCommentIds" type="application/json">["c2"]</script>',
            '<script id="handledCommentIds" type="application/json">["c1","c2","c3"]</script>')
        out = _run(html)
        # Every embedded id is handled, so no comment is open.
        self.assertIn("OPEN_COMMENTS: 0 of 3 embedded", out)

    def test_falls_back_to_body_when_no_comment_root(self):
        html = SAMPLE_HTML.replace('id="commentRoot"', 'id="notARoot"')
        out = _run(html)
        # With no #commentRoot the plan text falls back to <body>.
        self.assertIn("Ship the migration in two phases.", out)


if __name__ == "__main__":
    unittest.main()
