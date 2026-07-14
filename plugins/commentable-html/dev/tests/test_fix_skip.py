#!/usr/bin/env python3
"""Regression tests for fix_skip.py (the cm-skip-on-mermaid-<pre> fixer)."""
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
import fix_skip  # noqa: E402

FIX_PY = os.path.join(TOOLS, "authoring", "fix_skip.py")


class FixSkipCoreTests(unittest.TestCase):
    def test_adds_cm_skip_to_bare_mermaid_pre(self):
        html = '<html><body><pre class="mermaid">graph TD; A-->B;</pre></body></html>'
        new_html, count = fix_skip.fix(html)
        self.assertEqual(count, 1)
        self.assertIn('<pre class="mermaid cm-skip">', new_html)
        self.assertIn("graph TD; A-->B;</pre>", new_html)

    def test_already_tagged_is_untouched_and_idempotent(self):
        html = '<pre class="mermaid cm-skip">graph TD; A-->B;</pre>'
        new_html, count = fix_skip.fix(html)
        self.assertEqual(count, 0)
        self.assertEqual(new_html, html)
        # Running again on the (already clean) output changes nothing further.
        new_html2, count2 = fix_skip.fix(new_html)
        self.assertEqual(count2, 0)
        self.assertEqual(new_html2, new_html)

    def test_fix_is_idempotent_across_two_runs(self):
        html = '<pre class="mermaid">graph TD;</pre>'
        once, count1 = fix_skip.fix(html)
        twice, count2 = fix_skip.fix(once)
        self.assertEqual(count1, 1)
        self.assertEqual(count2, 0)
        self.assertEqual(once, twice)

    def test_plain_pre_code_block_never_gets_cm_skip(self):
        html = "<pre><code>print('hi')</code></pre>"
        new_html, count = fix_skip.fix(html)
        self.assertEqual(count, 0)
        self.assertEqual(new_html, html)

    def test_plain_pre_with_other_class_never_gets_cm_skip(self):
        html = '<pre class="language-python">print(1)</pre>'
        new_html, count = fix_skip.fix(html)
        self.assertEqual(count, 0)
        self.assertEqual(new_html, html)

    def test_preserves_class_order_and_other_attributes(self):
        html = '<pre id="d1" class="foo mermaid bar" data-x="y">text</pre>'
        new_html, count = fix_skip.fix(html)
        self.assertEqual(count, 1)
        self.assertIn('<pre id="d1" class="foo mermaid bar cm-skip" data-x="y">', new_html)

    def test_single_quoted_class_attribute_preserved_style(self):
        html = "<pre class='mermaid'>text</pre>"
        new_html, count = fix_skip.fix(html)
        self.assertEqual(count, 1)
        self.assertIn("<pre class='mermaid cm-skip'>text</pre>", new_html)

    def test_unquoted_class_attribute_gets_quoted(self):
        html = "<pre class=mermaid>text</pre>"
        new_html, count = fix_skip.fix(html)
        self.assertEqual(count, 1)
        self.assertIn('<pre class="mermaid cm-skip">text</pre>', new_html)

    def test_multiple_mermaid_blocks_all_fixed(self):
        html = (
            '<pre class="mermaid">a</pre>'
            "<pre><code>code block, not touched</code></pre>"
            '<pre class="mermaid">b</pre>'
            '<pre class="mermaid cm-skip">c</pre>'
        )
        new_html, count = fix_skip.fix(html)
        self.assertEqual(count, 2)
        # 2 newly fixed plus the 1 that already had cm-skip.
        self.assertEqual(new_html.count('class="mermaid cm-skip"'), 3)
        self.assertIn("<pre><code>code block, not touched</code></pre>", new_html)

    def test_decoy_mermaid_class_inside_html_comment_not_fixed(self):
        html = '<!-- <pre class="mermaid">decoy</pre> --><pre><code>real code</code></pre>'
        new_html, count = fix_skip.fix(html)
        self.assertEqual(count, 0)
        self.assertEqual(new_html, html)

    def test_decoy_mermaid_class_inside_attribute_string_not_fixed(self):
        html = ('<div data-x=\'<pre class="mermaid">\'>x</div>'
                "<pre><code>real code</code></pre>")
        new_html, count = fix_skip.fix(html)
        self.assertEqual(count, 0)
        self.assertEqual(new_html, html)

    def test_decoy_mermaid_class_inside_script_body_not_fixed(self):
        html = '<script>var s = \'<pre class="mermaid">x</pre>\';</script><pre><code>y</code></pre>'
        new_html, count = fix_skip.fix(html)
        self.assertEqual(count, 0)
        self.assertEqual(new_html, html)

    def test_no_pre_tags_at_all(self):
        html = "<html><body><p>nothing here</p></body></html>"
        new_html, count = fix_skip.fix(html)
        self.assertEqual(count, 0)
        self.assertEqual(new_html, html)

    def test_self_closing_pre_like_tag_is_handled(self):
        # Not realistic HTML, but exercises handle_startendtag without crashing.
        html = '<pre class="mermaid"/>'
        new_html, count = fix_skip.fix(html)
        self.assertEqual(count, 1)
        self.assertIn("cm-skip", new_html)

    def test_div_mermaid_is_not_touched_only_pre_is_in_scope(self):
        html = '<div class="mermaid">graph TD;</div>'
        new_html, count = fix_skip.fix(html)
        self.assertEqual(count, 0)
        self.assertEqual(new_html, html)

    def test_multiline_document_positions_are_tracked_correctly(self):
        html = (
            "<html>\n<body>\n"
            '<pre><code>x = 1</code></pre>\n'
            '<pre class="mermaid">\n'
            "graph TD;\nA-->B;\n"
            "</pre>\n"
            "</body>\n</html>\n"
        )
        new_html, count = fix_skip.fix(html)
        self.assertEqual(count, 1)
        self.assertIn('<pre class="mermaid cm-skip">\n', new_html)
        self.assertIn("<pre><code>x = 1</code></pre>", new_html)

    def test_add_cm_skip_returns_tag_unchanged_when_no_class_attribute(self):
        # Defensive fallback: _add_cm_skip is only ever called after the caller
        # has verified a class attribute exists; direct call exercises the guard.
        tag_text = '<pre id="x">'
        self.assertEqual(fix_skip._add_cm_skip(tag_text), tag_text)


class FixSkipCliTests(unittest.TestCase):
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
            code = fix_skip.main(argv)
        return code, out.getvalue(), err.getvalue()

    def _read(self, path):
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_check_reports_count_and_exits_1_when_dirty(self):
        p, _d = self._tmp('<pre class="mermaid">a</pre><pre class="mermaid">b</pre>')
        code, out, _err = self._call_main(["fix_skip.py", p, "--check"])
        self.assertEqual(code, 1)
        self.assertIn("2 mermaid block(s)", out)
        # --check must not write.
        self.assertEqual(self._read(p), '<pre class="mermaid">a</pre><pre class="mermaid">b</pre>')

    def test_check_exits_0_when_clean(self):
        p, _d = self._tmp('<pre class="mermaid cm-skip">a</pre>')
        code, out, _err = self._call_main(["fix_skip.py", p, "--check"])
        self.assertEqual(code, 0)
        self.assertIn("no mermaid blocks missing cm-skip", out)

    def test_fixes_in_place_by_default(self):
        p, _d = self._tmp('<pre class="mermaid">a</pre>')
        code, out, _err = self._call_main(["fix_skip.py", p])
        self.assertEqual(code, 0)
        self.assertIn("fixed 1 mermaid block(s)", out)
        self.assertIn('class="mermaid cm-skip"', self._read(p))

    def test_in_place_fix_is_idempotent_on_second_run(self):
        p, _d = self._tmp('<pre class="mermaid">a</pre>')
        self._call_main(["fix_skip.py", p])
        first = self._read(p)
        code, out, _err = self._call_main(["fix_skip.py", p])
        self.assertEqual(code, 0)
        self.assertIn("no mermaid blocks missing cm-skip", out)
        self.assertEqual(self._read(p), first)

    def test_out_option_writes_elsewhere_and_leaves_source_untouched(self):
        p, d = self._tmp('<pre class="mermaid">a</pre>')
        out_path = os.path.join(d, "fixed.html")
        code, out, _err = self._call_main(["fix_skip.py", p, "--out", out_path])
        self.assertEqual(code, 0)
        self.assertIn("fixed 1 mermaid block(s)", out)
        self.assertIn('class="mermaid cm-skip"', self._read(out_path))
        self.assertEqual(self._read(p), '<pre class="mermaid">a</pre>')

    def test_out_option_writes_clean_copy_when_already_fixed(self):
        p, d = self._tmp('<pre class="mermaid cm-skip">a</pre>')
        out_path = os.path.join(d, "copy.html")
        code, out, _err = self._call_main(["fix_skip.py", p, "--out", out_path])
        self.assertEqual(code, 0)
        self.assertIn("no mermaid blocks missing cm-skip", out)
        self.assertEqual(self._read(out_path), '<pre class="mermaid cm-skip">a</pre>')

    def test_missing_file_reports_error(self):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        missing = os.path.join(d, "nope.html")
        code, _out, err = self._call_main(["fix_skip.py", missing])
        self.assertEqual(code, 1)
        self.assertIn("file not found", err)

    def test_cli_subprocess_smoke(self):
        p, _d = self._tmp('<pre class="mermaid">a</pre>')
        r = subprocess.run([sys.executable, FIX_PY, p, "--check"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        r2 = subprocess.run([sys.executable, FIX_PY, p], capture_output=True, text=True)
        self.assertEqual(r2.returncode, 0)
        with open(p, encoding="utf-8") as fh:
            self.assertIn("cm-skip", fh.read())

    def test_open_failure_reports_error(self):
        # args.file exists (it's a directory) but open() on it raises OSError,
        # exercising the read-failure branch distinct from the not-found check.
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        code, _out, err = self._call_main(["fix_skip.py", d])
        self.assertEqual(code, 1)
        self.assertNotEqual(err, "")

    def test_module_entrypoint_uses_sys_argv(self):
        p, _d = self._tmp('<pre class="mermaid">a</pre>')
        out = io.StringIO()
        with mock.patch.object(sys, "argv", [FIX_PY, p, "--check"]), contextlib.redirect_stdout(out):
            with self.assertRaises(SystemExit) as cm:
                runpy.run_path(FIX_PY, run_name="__main__")
        self.assertEqual(cm.exception.code, 1)
        self.assertIn("mermaid block(s)", out.getvalue())


if __name__ == "__main__":
    unittest.main()
