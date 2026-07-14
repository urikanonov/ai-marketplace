#!/usr/bin/env python3
"""Tests for generate_toc.py."""
import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402  shared pkg/dev split path constants
ROOT = _paths.PKG
TOOLS = _paths.TOOLS
sys.path.insert(0, TOOLS)
import generate_toc  # noqa: E402

GENERATE_TOC_PY = os.path.join(TOOLS, "authoring", "generate_toc.py")


def doc(body):
    return (
        "<!doctype html>\n"
        "<html><body>\n"
        '<header><h2 id="chrome">Chrome</h2></header>\n'
        '<main id="commentRoot" data-comment-key="k">\n'
        + body
        + "\n</main>\n"
        "</body></html>\n"
    )


class GenerateTocTests(unittest.TestCase):
    def test_existing_ids_are_used_in_links(self):
        toc = generate_toc.build_toc(doc('<section><h2 id="alpha">Alpha</h2></section>'))
        self.assertIn('<li><a href="#alpha">Alpha</a></li>', toc)

    def test_missing_ids_get_stable_slugs(self):
        toc = generate_toc.build_toc(doc("<h2>Alpha Beta!</h2><h3>Child Topic</h3>"))
        self.assertIn('<li><a href="#alpha-beta">Alpha Beta!</a></li>', toc)
        self.assertIn('<li class="is-sub"><a href="#child-topic">Child Topic</a></li>', toc)

    def test_duplicate_heading_texts_are_deduplicated(self):
        html = doc('<h2 id="alpha">Alpha</h2><h2>Alpha</h2><h3>Alpha</h3>')
        toc = generate_toc.build_toc(html)
        self.assertIn('<li><a href="#alpha">Alpha</a></li>', toc)
        self.assertIn('<li><a href="#alpha-2">Alpha</a></li>', toc)
        self.assertIn('<li class="is-sub"><a href="#alpha-3">Alpha</a></li>', toc)

    def test_void_element_ids_are_reserved_for_generated_slugs(self):
        html = doc('<img id="alpha" /><h2>Alpha</h2>')
        toc = generate_toc.build_toc(html)
        self.assertIn('<a href="#alpha-2">Alpha</a>', toc)

    def test_headings_after_root_close_are_ignored(self):
        html = (
            "<!doctype html>\n<html><body>\n"
            '<main id="commentRoot" data-comment-key="k">'
            '<h2 id="inside">Inside</h2>'
            "</main>\n"
            '<footer><h2 id="after-root">After Root</h2></footer>\n'
            "</body></html>\n"
        )
        toc = generate_toc.build_toc(html)
        self.assertIn("#inside", toc)
        self.assertNotIn("after-root", toc)
        self.assertNotIn("After Root", toc)

    def test_only_headings_inside_comment_root_and_not_cm_skip_are_included(self):
        html = (
            '<h2 id="outside">Outside</h2>'
            '<main id="commentRoot">'
            '<div class="cm-skip"><h2 id="skip">Skip</h2></div>'
            "<h2>Inside</h2>"
            "</main>"
        )
        toc = generate_toc.build_toc(html)
        self.assertIn("#inside", toc)
        self.assertNotIn("outside", toc)
        self.assertNotIn("skip", toc)

    def test_heading_text_is_html_escaped(self):
        toc = generate_toc.build_toc(doc("<h2>Fish &amp; <em>Chips</em> &lt;ok&gt;</h2>"))
        self.assertIn("Fish &amp; Chips &lt;ok&gt;", toc)
        self.assertNotIn("Fish & Chips <ok>", toc)

    def test_rewrite_injects_ids_and_inserts_nav_at_top_of_root(self):
        html = doc('<p>Intro</p>\n<h2 class="x">Alpha</h2>\n<h3>Alpha</h3>')
        out = generate_toc.rewrite_html(html)
        self.assertIn('<main id="commentRoot" data-comment-key="k">\n<nav class="cm-toc"', out)
        self.assertIn('<h2 class="x" id="alpha">Alpha</h2>', out)
        self.assertIn('<h3 id="alpha-2">Alpha</h3>', out)
        self.assertLess(out.index('<nav class="cm-toc"'), out.index("<p>Intro</p>"))

    def test_rewrite_replaces_existing_nav_and_is_idempotent(self):
        html = doc(
            '<nav class="cm-toc" aria-label="Table of contents"><ol><li>Old</li></ol></nav>\n'
            '<h2>Alpha</h2>'
        )
        once = generate_toc.rewrite_html(html)
        twice = generate_toc.rewrite_html(once)
        self.assertEqual(once, twice)
        self.assertEqual(once.count('class="cm-toc"'), 1)
        self.assertNotIn("Old", once)

    def test_rewrite_removes_nested_existing_nav(self):
        html = doc(
            '<nav class="cm-toc" aria-label="Table of contents"><nav><ol><li>Old</li></ol></nav></nav>\n'
            '<h2>Alpha</h2>'
        )
        out = generate_toc.rewrite_html(html)
        self.assertEqual(out.count("<nav"), 1)
        self.assertNotIn("Old", out)

    def test_rewrite_uses_dominant_crlf_for_inserted_nav(self):
        html = doc("<h2>Alpha</h2>").replace("\n", "\r\n")
        out = generate_toc.rewrite_html(html)
        self.assertIn("\r\n<nav class=\"cm-toc\"", out)
        self.assertNotIn("\n<nav class=\"cm-toc\"", out.replace("\r\n", ""))

    def test_rewrite_raises_without_comment_root(self):
        with self.assertRaises(ValueError):
            generate_toc.rewrite_html("<html><body><h2>Alpha</h2></body></html>")

    def test_private_position_helpers_cover_malformed_inputs(self):
        self.assertEqual(generate_toc._end_tag_end("</nav", 0), 0)
        self.assertEqual(generate_toc._id_insert_pos(10, "<h2"), 13)
        self.assertEqual(generate_toc._id_insert_pos(0, "<h2 />"), 4)

    def test_print_mode_leaves_file_unchanged(self):
        source = doc("<h2>Alpha</h2>")
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "doc.html")
            with open(path, "w", encoding="utf-8", newline="") as handle:
                handle.write(source)
            result = subprocess.run([sys.executable, GENERATE_TOC_PY, path], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('<a href="#alpha">Alpha</a>', result.stdout)
            with open(path, encoding="utf-8", newline="") as handle:
                self.assertEqual(handle.read(), source)

    def test_cli_in_place_rewrites_file(self):
        source = doc("<h2>Alpha</h2>")
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "doc.html")
            with open(path, "w", encoding="utf-8", newline="") as handle:
                handle.write(source)
            result = subprocess.run(
                [sys.executable, GENERATE_TOC_PY, path, "--in-place"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            with open(path, encoding="utf-8", newline="") as handle:
                out = handle.read()
            self.assertIn('<nav class="cm-toc"', out)
            self.assertIn('<h2 id="alpha">Alpha</h2>', out)

    def test_main_missing_file_reports_error(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = generate_toc.main(["generate_toc.py", os.path.join("missing", "file.html")])
        self.assertEqual(code, 1)
        self.assertIn("file not found", err.getvalue())

    def test_main_prints_toc(self):
        source = doc("<h2>Alpha</h2>")
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "doc.html")
            with open(path, "w", encoding="utf-8", newline="") as handle:
                handle.write(source)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = generate_toc.main(["generate_toc.py", path])
            self.assertEqual(code, 0)
            self.assertIn('<a href="#alpha">Alpha</a>', out.getvalue())

    def test_main_in_place_rewrites_file(self):
        source = doc("<h2>Alpha</h2>")
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "doc.html")
            with open(path, "w", encoding="utf-8", newline="") as handle:
                handle.write(source)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = generate_toc.main(["generate_toc.py", path, "--in-place"])
            self.assertEqual(code, 0)
            self.assertIn("updated", out.getvalue())
            with open(path, encoding="utf-8", newline="") as handle:
                self.assertIn('<h2 id="alpha">Alpha</h2>', handle.read())

    def test_main_reports_rewrite_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "doc.html")
            with open(path, "w", encoding="utf-8", newline="") as handle:
                handle.write("<html><body><h2>Alpha</h2></body></html>")
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = generate_toc.main(["generate_toc.py", path, "--in-place"])
            self.assertEqual(code, 1)
            self.assertIn("commentRoot", err.getvalue())

    def test_module_entrypoint_uses_sys_argv(self):
        err = io.StringIO()
        with mock.patch.object(sys, "argv", [GENERATE_TOC_PY]), contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as cm:
                runpy = __import__("runpy")
                runpy.run_path(GENERATE_TOC_PY, run_name="__main__")
        self.assertNotEqual(cm.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
