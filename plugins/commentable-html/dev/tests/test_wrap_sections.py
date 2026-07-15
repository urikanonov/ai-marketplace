#!/usr/bin/env python3
"""Regression tests for wrap_sections.py (the bare-top-level-<h2> -> <section> wrapper)."""
import contextlib
import io
import os
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402  shared pkg/dev split path constants
TOOLS = _paths.TOOLS
sys.path.insert(0, TOOLS)
import wrap_sections  # noqa: E402

WRAP_PY = os.path.join(TOOLS, "authoring", "wrap_sections.py")


def _doc(inner, kind="report"):
    """A minimal full document whose #commentRoot body is `inner`."""
    return (
        "<html><head>\n"
        '<meta name="commentable-html-kind" content="%s">\n' % kind
        + "</head><body>\n"
        '<main id="commentRoot" data-cmh-content-root data-comment-key="k">\n'
        + inner
        + "\n</main>\n</body></html>\n")


class WrapFragmentTests(unittest.TestCase):
    def test_wraps_each_top_level_h2_block(self):
        frag = ('<h1>Title</h1>\n'
                '<h2 id="a">One</h2>\n<p>a</p>\n'
                '<h2 id="b">Two</h2>\n<p>b</p>')
        out, count = wrap_sections.wrap_fragment(frag)
        self.assertEqual(count, 2)
        self.assertEqual(out.count("<section"), 2)
        self.assertIn('<section aria-labelledby="a">', out)
        self.assertIn('<section aria-labelledby="b">', out)
        # The title before the first <h2> stays above the cards.
        self.assertTrue(out.lstrip().startswith("<h1>Title</h1>"))

    def test_h2_without_id_gets_a_bare_section(self):
        frag = '<h2>One</h2>\n<p>a</p>\n<h2>Two</h2>\n<p>b</p>'
        out, count = wrap_sections.wrap_fragment(frag)
        self.assertEqual(count, 2)
        self.assertIn("<section>\n", out)
        self.assertNotIn("aria-labelledby", out)

    def test_noop_when_a_top_level_section_already_exists(self):
        frag = '<section><h2 id="a">One</h2><p>a</p></section>\n<h2 id="b">Two</h2>'
        out, count = wrap_sections.wrap_fragment(frag)
        self.assertEqual(count, 0)
        self.assertEqual(out, frag)

    def test_noop_when_no_top_level_h2(self):
        frag = '<h1>Title</h1>\n<p>just prose</p>'
        out, count = wrap_sections.wrap_fragment(frag)
        self.assertEqual(count, 0)
        self.assertEqual(out, frag)

    def test_idempotent_across_two_runs(self):
        frag = '<h2 id="a">One</h2>\n<p>a</p>\n<h2 id="b">Two</h2>\n<p>b</p>'
        once, c1 = wrap_sections.wrap_fragment(frag)
        twice, c2 = wrap_sections.wrap_fragment(once)
        self.assertEqual(c1, 2)
        self.assertEqual(c2, 0)  # the wrapped output already has top-level sections
        self.assertEqual(once, twice)

    def test_nested_h2_inside_a_div_is_not_top_level(self):
        # Only a DIRECT-child <h2> is a card boundary; an <h2> nested in a wrapper is left alone.
        frag = '<div><h2 id="x">nested</h2></div>\n<h2 id="a">One</h2>\n<p>a</p>'
        out, count = wrap_sections.wrap_fragment(frag)
        self.assertEqual(count, 1)  # only the single top-level <h2>
        self.assertIn('<section aria-labelledby="a">', out)
        # The nested h2's own div is not turned into a section.
        self.assertIn("<div><h2 id=\"x\">nested</h2></div>", out)

    def test_decoy_h2_in_comment_is_not_wrapped(self):
        frag = '<!-- <h2 id="c">decoy</h2> -->\n<p>only prose, no real h2</p>'
        out, count = wrap_sections.wrap_fragment(frag)
        self.assertEqual(count, 0)
        self.assertEqual(out, frag)


class FixDocTests(unittest.TestCase):
    def test_wraps_inside_comment_root_only(self):
        html = _doc('<h1>T</h1>\n<h2 id="a">One</h2>\n<p>a</p>\n<h2 id="b">Two</h2>\n<p>b</p>')
        out, count = wrap_sections.fix(html)
        self.assertEqual(count, 2)
        self.assertIn('<section aria-labelledby="a">', out)
        # The layer shell (head/body/main tags) is untouched.
        self.assertIn('<main id="commentRoot"', out)
        self.assertIn("</main>", out)

    def test_noop_when_already_sectioned(self):
        html = _doc('<h1>T</h1>\n<section aria-labelledby="a"><h2 id="a">One</h2></section>')
        out, count = wrap_sections.fix(html)
        self.assertEqual(count, 0)
        self.assertEqual(out, html)

    def test_noop_when_no_comment_root(self):
        html = "<html><body><h2>One</h2><h2>Two</h2></body></html>"
        out, count = wrap_sections.fix(html)
        self.assertEqual(count, 0)
        self.assertEqual(out, html)

    def test_idempotent(self):
        html = _doc('<h2 id="a">One</h2>\n<p>a</p>\n<h2 id="b">Two</h2>\n<p>b</p>')
        once, c1 = wrap_sections.fix(html)
        twice, c2 = wrap_sections.fix(once)
        self.assertEqual(c1, 2)
        self.assertEqual(c2, 0)
        self.assertEqual(once, twice)


class WrapSectionsCliTests(unittest.TestCase):
    def _tmp(self, content):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        p = os.path.join(d, "doc.html")
        with open(p, "w", encoding="utf-8", newline="") as fh:
            fh.write(content)
        return p, d

    def _call_main(self, argv):
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = wrap_sections.main(argv)
        return code, out.getvalue(), err.getvalue()

    def _read(self, path):
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_check_fragment_reports_count_and_exits_1(self):
        frag = '<h2 id="a">One</h2>\n<p>a</p>\n<h2 id="b">Two</h2>'
        p, _d = self._tmp(frag)
        code, out, _err = self._call_main(["wrap_sections.py", p, "--fragment", "--check"])
        self.assertEqual(code, 1)
        self.assertIn("2 top-level <h2> block(s)", out)
        self.assertEqual(self._read(p), frag)  # --check must not write

    def test_check_exits_0_when_clean(self):
        p, _d = self._tmp('<section><h2 id="a">One</h2></section>')
        code, out, _err = self._call_main(["wrap_sections.py", p, "--fragment", "--check"])
        self.assertEqual(code, 0)
        self.assertIn("no unwrapped top-level <h2>", out)

    def test_fragment_fixes_in_place(self):
        p, _d = self._tmp('<h2 id="a">One</h2>\n<p>a</p>\n<h2 id="b">Two</h2>\n<p>b</p>')
        code, out, _err = self._call_main(["wrap_sections.py", p, "--fragment"])
        self.assertEqual(code, 0)
        self.assertIn("wrapped 2 top-level <h2> block(s)", out)
        self.assertIn("<section", self._read(p))

    def test_full_doc_fixes_in_place(self):
        p, _d = self._tmp(_doc('<h2 id="a">One</h2>\n<p>a</p>\n<h2 id="b">Two</h2>\n<p>b</p>'))
        code, out, _err = self._call_main(["wrap_sections.py", p])
        self.assertEqual(code, 0)
        self.assertIn("wrapped 2", out)
        self.assertIn('<section aria-labelledby="a">', self._read(p))

    def test_out_option_leaves_source_untouched(self):
        original = '<h2 id="a">One</h2>\n<h2 id="b">Two</h2>'
        p, d = self._tmp(original)
        out_path = os.path.join(d, "wrapped.html")
        code, _out, _err = self._call_main(["wrap_sections.py", p, "--fragment", "--out", out_path])
        self.assertEqual(code, 0)
        self.assertIn("<section", self._read(out_path))
        self.assertEqual(self._read(p), original)

    def test_missing_file_reports_error(self):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        code, _out, err = self._call_main(["wrap_sections.py", os.path.join(d, "nope.html")])
        self.assertEqual(code, 1)
        self.assertIn("file not found", err)

    def test_cli_subprocess_smoke(self):
        p, _d = self._tmp(_doc('<h2 id="a">One</h2>\n<h2 id="b">Two</h2>'))
        r = subprocess.run([sys.executable, WRAP_PY, p, "--check"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        r2 = subprocess.run([sys.executable, WRAP_PY, p], capture_output=True, text=True)
        self.assertEqual(r2.returncode, 0)
        self.assertIn("<section", self._read(p))

    def test_module_entrypoint_uses_sys_argv(self):
        p, _d = self._tmp('<h2 id="a">One</h2>\n<h2 id="b">Two</h2>')
        out = io.StringIO()
        with mock.patch.object(sys, "argv", [WRAP_PY, p, "--fragment", "--check"]), \
                contextlib.redirect_stdout(out):
            with self.assertRaises(SystemExit) as cm:
                runpy.run_path(WRAP_PY, run_name="__main__")
        self.assertEqual(cm.exception.code, 1)
        self.assertIn("top-level <h2> block(s)", out.getvalue())


if __name__ == "__main__":
    unittest.main()
