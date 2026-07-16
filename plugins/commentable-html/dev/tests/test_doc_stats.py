#!/usr/bin/env python3
"""Tests for doc_stats.py (CMH-STATS-01)."""
import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402  shared pkg/dev split path constants
TOOLS = _paths.TOOLS
sys.path.insert(0, TOOLS)
import doc_stats  # noqa: E402

DOC_STATS_PY = os.path.join(TOOLS, "authoring", "doc_stats.py")


def doc(body):
    return (
        "<!doctype html>\n"
        "<html><body>\n"
        '<header class="cm-skip"><h2 id="chrome">Chrome</h2></header>\n'
        '<main id="commentRoot" data-comment-key="k">\n'
        + body
        + "\n</main>\n"
        "</body></html>\n"
    )


# A report body: h1 title (1 word), intro (3), two sections (h2 + body).
BODY = (
    "<h1>Title</h1>\n"
    "<p>Intro paragraph words</p>\n"
    '<section aria-labelledby="alpha"><h2 id="alpha">Alpha</h2><p>one two three</p></section>\n'
    '<section aria-labelledby="beta"><h2 id="beta">Beta</h2><p>four five</p></section>\n'
)
# Title(1) + intro(3) + Alpha(1) + one/two/three(3) + Beta(1) + four/five(2) = 11.
BODY_WORDS = 11
BODY_SECTIONS = 2


class CountTests(unittest.TestCase):
    def test_count_sections_counts_h2_inside_root(self):
        self.assertEqual(doc_stats.count_sections(doc(BODY)), BODY_SECTIONS)

    def test_count_sections_ignores_cm_skip_and_chrome_h2(self):
        body = BODY + '<div class="cm-skip"><h2 id="x">Skip me</h2></div>'
        self.assertEqual(doc_stats.count_sections(doc(body)), BODY_SECTIONS)

    def test_count_words_counts_content_text(self):
        self.assertEqual(doc_stats.count_words(doc(BODY)), BODY_WORDS)

    def test_count_words_excludes_skip_script_style_and_toc(self):
        body = (
            BODY
            + '<div class="cm-skip">skip these words entirely</div>'
            + "<script>var ignored = 1 + 2 + 3;</script>"
            + "<style>.x{color:red}</style>"
            + '<nav class="cm-toc"><div class="cm-toc-title">Contents</div>'
            + '<ol><li><a href="#alpha">Alpha</a></li><li><a href="#beta">Beta</a></li></ol></nav>'
        )
        self.assertEqual(doc_stats.count_words(doc(body)), BODY_WORDS)

    def test_reading_minutes_rounds_up_and_has_floor_of_one(self):
        self.assertEqual(doc_stats.reading_minutes(0), 1)
        self.assertEqual(doc_stats.reading_minutes(1), 1)
        self.assertEqual(doc_stats.reading_minutes(200), 1)
        self.assertEqual(doc_stats.reading_minutes(201), 2)
        self.assertEqual(doc_stats.reading_minutes(1000), 5)

    def test_reading_minutes_honours_custom_wpm(self):
        self.assertEqual(doc_stats.reading_minutes(300, wpm=100), 3)


class RewriteTests(unittest.TestCase):
    def test_block_is_inserted_once_under_the_title(self):
        out = doc_stats.rewrite_html(doc(BODY))
        self.assertEqual(out.count("data-cmh-doc-stats"), 1)
        self.assertIn('class="cmh-doc-stats cm-skip"', out)
        # Placed after the H1 title, above the intro paragraph.
        self.assertLess(out.index("</h1>"), out.index("cmh-doc-stats"))
        self.assertLess(out.index("cmh-doc-stats"), out.index("<p>Intro paragraph words</p>"))

    def test_block_reports_sections_words_and_reading_time(self):
        out = doc_stats.rewrite_html(doc(BODY))
        self.assertIn("<strong>2</strong> sections", out)
        self.assertIn("<strong>11</strong> words", out)
        self.assertIn("~<strong>1</strong> min read", out)

    def test_singular_labels_when_counts_are_one(self):
        body = "<h1>Solo</h1>\n<section><h2>Only</h2><p>word</p></section>\n"
        out = doc_stats.rewrite_html(doc(body))
        self.assertIn("<strong>1</strong> section", out)
        self.assertNotIn("<strong>1</strong> sections", out)

    def test_block_is_excluded_from_its_own_word_count(self):
        original = doc(BODY)
        out = doc_stats.rewrite_html(original)
        # The stats block is cm-skip, so re-counting the rewritten document is unchanged.
        self.assertEqual(doc_stats.count_words(out), BODY_WORDS)
        self.assertEqual(doc_stats.count_sections(out), BODY_SECTIONS)

    def test_rewrite_is_idempotent(self):
        once = doc_stats.rewrite_html(doc(BODY))
        twice = doc_stats.rewrite_html(once)
        self.assertEqual(once, twice)
        self.assertEqual(twice.count("data-cmh-doc-stats"), 1)

    def test_rewrite_refreshes_stale_counts(self):
        out = doc_stats.rewrite_html(doc(BODY))
        stale = out.replace("<strong>2</strong> sections", "<strong>99</strong> sections")
        refreshed = doc_stats.rewrite_html(stale)
        self.assertIn("<strong>2</strong> sections", refreshed)
        self.assertNotIn("99", refreshed)
        self.assertEqual(refreshed.count("data-cmh-doc-stats"), 1)

    def test_rewrite_uses_dominant_crlf(self):
        out = doc_stats.rewrite_html(doc(BODY).replace("\n", "\r\n"))
        self.assertIn('\r\n<div class="cmh-doc-stats', out)
        self.assertNotIn("\n", out.replace("\r\n", ""))

    def test_rewrite_without_title_inserts_at_top_of_root(self):
        body = '<section><h2 id="a">Alpha</h2><p>one two</p></section>'
        out = doc_stats.rewrite_html(doc(body))
        self.assertIn("data-cmh-doc-stats", out)
        self.assertLess(out.index('data-comment-key="k"'), out.index("cmh-doc-stats"))
        self.assertLess(out.index("cmh-doc-stats"), out.index("<section>"))

    def test_rewrite_raises_without_comment_root(self):
        with self.assertRaises(ValueError):
            doc_stats.rewrite_html("<html><body><h1>x</h1></body></html>")


class CliTests(unittest.TestCase):
    def test_print_mode_leaves_file_unchanged(self):
        source = doc(BODY)
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "doc.html")
            with open(path, "w", encoding="utf-8", newline="") as handle:
                handle.write(source)
            result = subprocess.run([sys.executable, DOC_STATS_PY, path], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("2 sections", result.stdout)
            with open(path, encoding="utf-8", newline="") as handle:
                self.assertEqual(handle.read(), source)

    def test_in_place_rewrites_file(self):
        source = doc(BODY)
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "doc.html")
            with open(path, "w", encoding="utf-8", newline="") as handle:
                handle.write(source)
            result = subprocess.run(
                [sys.executable, DOC_STATS_PY, path, "--in-place"], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            with open(path, encoding="utf-8", newline="") as handle:
                out = handle.read()
            self.assertIn("data-cmh-doc-stats", out)

    def test_main_missing_file_reports_error(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = doc_stats.main(["doc_stats.py", os.path.join("missing", "file.html")])
        self.assertEqual(code, 1)
        self.assertIn("file not found", err.getvalue())


if __name__ == "__main__":
    unittest.main()
