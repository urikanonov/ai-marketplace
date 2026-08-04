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
import _browser_boundaries  # noqa: E402

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

    def test_heading_text_inside_a_template_is_not_part_of_the_title(self):
        # A nested <template> is inert, so its text is neither rendered nor part of the heading
        # the TOC links to - the validator's heading capture reads it the same way.
        toc = generate_toc.build_toc(
            doc('<h2 id="alpha">Real<template>Hidden</template>Tail</h2>'))
        self.assertIn('<li><a href="#alpha">RealTail</a></li>', toc)
        self.assertNotIn("Hidden", toc)

    def test_a_heading_whose_text_is_only_a_template_is_not_listed(self):
        toc = generate_toc.build_toc(
            doc('<h2 id="alpha"><template>Hidden</template></h2><h2 id="beta">Beta</h2>'))
        self.assertNotIn("Hidden", toc)
        self.assertNotIn("#alpha", toc)
        self.assertIn('<li><a href="#beta">Beta</a></li>', toc)

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

    # CMH-VAL-21: this tool ends a heading exactly where the validator's _DocParser ends it, so a
    # truncated or ancestor-closed document is ONE document to both. The first three pin boundaries
    # the shared BrowserBoundaries base already supplies (regression pins); the h1-h6 pop below is
    # the one this parser was still missing.
    def test_a_heading_left_open_at_end_of_input_is_still_listed(self):
        # A browser renders a heading whose end tag never arrives, so it is a real heading and the
        # last heading of a truncated file must still reach the table of contents.
        toc = generate_toc.build_toc(
            '<main id="commentRoot"><h2 id="alpha">Alpha</h2><h2 id="beta">Beta')
        self.assertIn('<li><a href="#beta">Beta</a></li>', toc)

    def test_an_open_heading_with_no_text_at_end_of_input_is_dropped(self):
        toc = generate_toc.build_toc('<main id="commentRoot"><h2 id="alpha">Alpha</h2><h2 id="beta">')
        self.assertNotIn("#beta", toc)

    def test_an_ancestors_end_tag_ends_the_heading(self):
        # </section> closes over the open h2, so the heading stops there instead of absorbing the
        # prose after it - and the next heading's text and id.
        toc = generate_toc.build_toc(doc(
            '<section><h2 id="alpha">Alpha</section>'
            "<p>loose prose</p>"
            '<h2 id="beta">Beta</h2>'))
        self.assertIn('<li><a href="#alpha">Alpha</a></li>', toc)
        self.assertIn('<li><a href="#beta">Beta</a></li>', toc)
        self.assertNotIn("loose prose", toc)

    def test_a_heading_the_comment_root_closed_over_stops_there(self):
        toc = generate_toc.build_toc(
            '<main id="commentRoot"><h2 id="alpha">Alpha</main>'
            "<footer>outside prose</footer>")
        self.assertIn('<li><a href="#alpha">Alpha</a></li>', toc)
        self.assertNotIn("outside prose", toc)

    def test_a_new_heading_start_ends_the_open_one(self):
        # HTML5's h1-h6 start tag pops an open heading that is the current node, so this is two
        # headings - not one that swallowed the second's text and never saw its id.
        toc = generate_toc.build_toc(doc('<h2 id="alpha">Alpha<h2 id="beta">Beta</h2>'))
        self.assertIn('<li><a href="#alpha">Alpha</a></li>', toc)
        self.assertIn('<li><a href="#beta">Beta</a></li>', toc)

    def test_a_heading_of_another_level_ends_the_open_one_too(self):
        # The pop is not level-matched: an <h4> ends an open <h2> even though only h2/h3 are
        # listed, so the listed entry carries its own text and not the h4's.
        toc = generate_toc.build_toc(doc('<h2 id="alpha">Alpha<h4>Deep</h4><h3 id="gamma">Gamma</h3>'))
        self.assertIn('<li><a href="#alpha">Alpha</a></li>', toc)
        self.assertIn('<li class="is-sub"><a href="#gamma">Gamma</a></li>', toc)
        self.assertNotIn("Deep", toc)

    def test_a_heading_the_toc_did_not_capture_is_still_popped(self):
        # The pop is STRUCTURAL, not keyed on whether this tool captured the open heading: a
        # browser pops any open h1-h6 that is the current node. Keyed on capture, an unterminated
        # cm-skip heading - or one of a level the TOC never lists - stayed on the stack and the
        # visible heading after it inherited the skip and never reached the table of contents.
        # Verified in chromium: in each document below `#shown` is a child of the <main>, its
        # text is "Shown", and `closest(".cm-skip")` is null.
        for body in ('<h2 class="cm-skip">Hidden<h2 id="shown">Shown</h2>',
                     '<h4 class="cm-skip">Hidden<h2 id="shown">Shown</h2>',
                     '<h1>Title<h2 id="shown">Shown</h2>'):
            with self.subTest(body=body):
                toc = generate_toc.build_toc(doc(body))
                self.assertIn('<li><a href="#shown">Shown</a></li>', toc)
                self.assertNotIn("Hidden", toc)

    def test_a_stray_end_tag_for_a_popped_heading_does_not_end_the_new_one(self):
        # Once the <h4> is popped the later </h4> matches no open element, so a browser ignores
        # it and the h2 keeps running to its own end tag.
        toc = generate_toc.build_toc(doc('<h4>Deep<h2 id="shown">Shown</h2></h4><p>tail</p>'))
        self.assertIn('<li><a href="#shown">Shown</a></li>', toc)

    def test_a_child_element_inside_a_heading_does_not_end_it(self):
        toc = generate_toc.build_toc(doc('<h2 id="alpha">Al<em>ph</em>a</h2>'))
        self.assertIn('<li><a href="#alpha">Alpha</a></li>', toc)

    def test_rewrite_injects_an_id_for_a_heading_left_open_at_end_of_input(self):
        out = generate_toc.rewrite_html('<main id="commentRoot"><h2>Trailing Title')
        self.assertIn('<h2 id="trailing-title">Trailing Title', out)
        self.assertIn('<a href="#trailing-title">Trailing Title</a>', out)

    def test_generated_toc_strips_redundant_author_section_numbers(self):
        html = doc('<h2 id="a">1. Executive summary</h2>\n<h2 id="b">2. How the two source plans merge</h2>')
        toc = generate_toc.build_toc(html)
        self.assertIn('<a href="#a">Executive summary</a>', toc)
        self.assertIn('<a href="#b">How the two source plans merge</a>', toc)
        self.assertNotIn("1. Executive", toc)
        self.assertNotIn("2. How", toc)
        # The ordered list is kept; it supplies the single number.
        self.assertIn("<ol>", toc)

    def test_toc_strips_dotted_and_paren_numbering_variants(self):
        html = doc(
            '<h2 id="a">3.1 Goals</h2>'
            '<h2 id="b">2) Scope</h2>'
            '<h3 id="c">1.2.3 Deep item</h3>'
        )
        toc = generate_toc.build_toc(html)
        self.assertIn('<a href="#a">Goals</a>', toc)
        self.assertIn('<a href="#b">Scope</a>', toc)
        self.assertIn('<a href="#c">Deep item</a>', toc)

    def test_toc_keeps_unnumbered_and_year_prefixed_titles(self):
        html = doc('<h2 id="a">Overview</h2><h2 id="b">2024 review</h2>')
        toc = generate_toc.build_toc(html)
        self.assertIn('<a href="#a">Overview</a>', toc)
        # "2024 review" has no section-number separator, so it must not be stripped.
        self.assertIn('<a href="#b">2024 review</a>', toc)

    def test_strip_section_number_helper(self):
        self.assertEqual(generate_toc._strip_section_number("1. Alpha"), "Alpha")
        self.assertEqual(generate_toc._strip_section_number("3.1 Beta"), "Beta")
        self.assertEqual(generate_toc._strip_section_number("2) Gamma"), "Gamma")
        self.assertEqual(generate_toc._strip_section_number("Delta"), "Delta")
        self.assertEqual(generate_toc._strip_section_number("2024 review"), "2024 review")

    def test_strip_toc_numbers_dedups_existing_ordered_toc(self):
        html = doc(
            '<nav class="cm-toc"><div class="cm-toc-title">Contents</div><ol>'
            '<li><a href="#a">1. Executive summary</a></li>'
            '<li><a href="#b">2. How the two source plans merge</a></li>'
            "</ol></nav>"
            '<h2 id="a">1. Executive summary</h2><h2 id="b">2. How the two source plans merge</h2>'
        )
        out, count = generate_toc.strip_toc_numbers(html)
        self.assertEqual(count, 2)
        self.assertIn('<a href="#a">Executive summary</a>', out)
        self.assertIn('<a href="#b">How the two source plans merge</a>', out)

    def test_strip_toc_numbers_leaves_unordered_toc_untouched(self):
        html = doc('<nav class="cm-toc"><ul><li><a href="#a">1. Foo</a></li></ul></nav>'
                   '<h2 id="a">1. Foo</h2>')
        out, count = generate_toc.strip_toc_numbers(html)
        self.assertEqual(count, 0)
        self.assertIn('<a href="#a">1. Foo</a>', out)

    def test_strip_toc_numbers_is_noop_without_a_toc(self):
        out, count = generate_toc.strip_toc_numbers(doc('<h2 id="a">1. Foo</h2>'))
        self.assertEqual(count, 0)
        self.assertNotIn('class="cm-toc"', out)

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
        # The end-tag extent is the SHARED browser scan now (CMH-VAL-21): an unterminated end tag
        # yields its own start, and a `>` inside a quoted attribute value does not end it.
        self.assertEqual(_browser_boundaries.end_tag_end("</nav", 0), 0)
        self.assertEqual(_browser_boundaries.end_tag_end('</nav a=">">', 0), 12)
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
