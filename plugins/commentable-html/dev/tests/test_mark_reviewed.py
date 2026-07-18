#!/usr/bin/env python3
"""CMH-REVIEW-07: mark_reviewed.py bakes/updates the reviewedSections block deterministically."""
import json
import os
import re
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402
import section_hash  # noqa: E402
import mark_reviewed  # noqa: E402

TOOLS = _paths.TOOLS
MARK_PY = os.path.join(TOOLS, "authoring", "mark_reviewed.py")

DOC = (
    "<!doctype html>\n<html><head></head><body>\n"
    '<script type="application/json" id="handledCommentIds">\n[]\n</script>\n'
    '<script type="application/json" id="embeddedComments">\n[]\n</script>\n'
    '<script type="application/json" id="reviewedSections">\n{}\n</script>\n'
    '<main id="commentRoot" data-cmh-content-root>\n'
    '<h2 id="goals">Goals</h2><p>The goals of the plan.</p>\n'
    '<h2 id="plan">Plan</h2><p>The plan body.</p>\n'
    "</main>\n</body></html>\n"
)
DOC_NO_BLOCK = DOC.replace('<script type="application/json" id="reviewedSections">\n{}\n</script>\n', "")


def _markers(path):
    with open(path, encoding="utf-8") as fh:
        html = fh.read()
    m = re.search(r'<script[^>]*id="reviewedSections"[^>]*>(.*?)</script>', html, re.S)
    return json.loads(m.group(1).strip()) if m else None


class MarkReviewedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "doc.html")
        with open(self.path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(DOC)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_mark_writes_marker_with_the_runtime_hash(self):
        marked, cleared, missing = mark_reviewed.mark_reviewed(self.path, ["goals"], [], at="2026-01-01T00:00:00Z")
        self.assertEqual((marked, cleared, missing), (["goals"], [], []))
        markers = _markers(self.path)
        self.assertIn("goals", markers)
        expected = {s["id"]: s for s in section_hash.extract_sections(DOC)}["goals"]["hash"]
        self.assertEqual(markers["goals"]["hash"], expected)
        self.assertEqual(markers["goals"]["level"], 2)
        self.assertEqual(markers["goals"]["headingText"], "Goals")
        self.assertEqual(markers["goals"]["reviewedAt"], "2026-01-01T00:00:00Z")

    def test_clear_removes_marker(self):
        mark_reviewed.mark_reviewed(self.path, ["goals", "plan"], [], at="2026-01-01T00:00:00Z")
        mark_reviewed.mark_reviewed(self.path, [], ["goals"])
        markers = _markers(self.path)
        self.assertNotIn("goals", markers)
        self.assertIn("plan", markers)

    def test_missing_heading_id_is_reported(self):
        marked, cleared, missing = mark_reviewed.mark_reviewed(self.path, ["nope"], [], at="x")
        self.assertEqual(missing, ["nope"])
        self.assertEqual(_markers(self.path), {})

    def test_unsafe_heading_id_is_refused(self):
        with self.assertRaises(ValueError):
            mark_reviewed.mark_reviewed(self.path, ['goals" onclick=x'], [], at="x")

    def test_block_is_inserted_when_absent(self):
        p = os.path.join(self.tmp, "noblock.html")
        with open(p, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(DOC_NO_BLOCK)
        mark_reviewed.mark_reviewed(p, ["goals"], [], at="2026-01-01T00:00:00Z")
        markers = _markers(p)
        self.assertIn("goals", markers)

    def test_dominant_newline_is_preserved(self):
        p = os.path.join(self.tmp, "crlf.html")
        with open(p, "w", encoding="utf-8", newline="") as fh:
            fh.write(DOC.replace("\n", "\r\n"))
        mark_reviewed.mark_reviewed(p, ["goals"], [], at="x")
        with open(p, "rb") as fh:
            raw = fh.read()
        self.assertIn(b"\r\n", raw)
        self.assertNotIn(b"\n\n", raw.replace(b"\r\n", b"\n\n").replace(b"\n\n", b"\r\n"))  # no lone LF introduced

    def test_left_untouched_json_stays_valid_and_angle_escaped(self):
        # A heading text with "<" must be escaped as \u003c in the baked JSON (like embedded comments).
        p = os.path.join(self.tmp, "angle.html")
        html = DOC.replace("<h2 id=\"goals\">Goals</h2>", '<h2 id="goals">Goals &lt;v2&gt;</h2>')
        with open(p, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(html)
        mark_reviewed.mark_reviewed(p, ["goals"], [], at="x")
        with open(p, encoding="utf-8") as fh:
            raw = fh.read()
        block = re.search(r'id="reviewedSections"[^>]*>(.*?)</script>', raw, re.S).group(1)
        self.assertNotIn("<v2>", block)  # raw "<" must not appear
        self.assertIn("\\u003c", block)

    def test_cli_smoke(self):
        import subprocess
        r = subprocess.run([sys.executable, MARK_PY, self.path, "goals", "--at", "x"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("goals", _markers(self.path))
        r2 = subprocess.run([sys.executable, MARK_PY, self.path, "--list"], capture_output=True, text=True)
        self.assertIn("goals", r2.stdout)

    def test_numeric_hash_in_existing_block_is_refused(self):
        p = os.path.join(self.tmp, "numhash.html")
        html = DOC.replace(
            '<script type="application/json" id="reviewedSections">\n{}\n</script>',
            '<script type="application/json" id="reviewedSections">\n'
            '{"goals": {"hash": 123, "level": 2}}\n</script>')
        with open(p, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(html)
        with self.assertRaises(ValueError):
            mark_reviewed.mark_reviewed(p, ["plan"], [], at="x")

    def test_decoy_embedded_block_in_comment_is_not_the_insertion_anchor(self):
        # A commented-out decoy embeddedComments block must not receive the inserted reviewedSections.
        p = os.path.join(self.tmp, "decoy.html")
        decoy = '<!-- <script type="application/json" id="embeddedComments">[]</script> -->\n'
        html = DOC_NO_BLOCK.replace(
            '<script type="application/json" id="embeddedComments">\n[]\n</script>\n',
            decoy + '<script type="application/json" id="embeddedComments">\n[]\n</script>\n')
        with open(p, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(html)
        mark_reviewed.mark_reviewed(p, ["goals"], [], at="x")
        with open(p, encoding="utf-8") as fh:
            out = fh.read()
        # The block is inserted after the REAL block (which sits after the decoy comment), not inside it.
        self.assertEqual(out.count('id="reviewedSections"'), 1)
        self.assertGreater(out.index('id="reviewedSections"'), out.index("-->"))
        self.assertIn("goals", _markers(p))

    def test_uppercase_or_spaced_script_close_inserts_correctly(self):
        # A non-canonical </SCRIPT> / </script > close must not splice the new block INSIDE the JSON.
        for closer in ("</SCRIPT>", "</script >"):
            p = os.path.join(self.tmp, "close.html")
            html = DOC_NO_BLOCK.replace(
                '<script type="application/json" id="embeddedComments">\n[]\n</script>\n',
                '<script type="application/json" id="embeddedComments">\n[]\n' + closer + "\n")
            with open(p, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(html)
            mark_reviewed.mark_reviewed(p, ["goals"], [], at="x")
            markers = _markers(p)
            self.assertIn("goals", markers, closer)
            # embeddedComments JSON is still valid (the block was not spliced inside it).
            with open(p, encoding="utf-8") as fh:
                out = fh.read()
            ec = re.search(r'id="embeddedComments"[^>]*>(.*?)</', out, re.S | re.I).group(1)
            self.assertEqual(json.loads(ec.strip()), [])


if __name__ == "__main__":
    unittest.main()
