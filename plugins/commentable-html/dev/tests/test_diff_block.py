#!/usr/bin/env python3
"""Regression tests for diff_block.py."""
import contextlib
import html
import io
import os
import re
import runpy
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

import diff_block as D  # noqa: E402
import validate  # noqa: E402

DIFF_BLOCK_PY = os.path.join(TOOLS, "diff_block.py")
TEMPLATE = os.path.join(ROOT, "dist", "PORTABLE.html")
_CONTENT_START = "<!-- BEGIN: commentable-html - CONTENT (agent edits ONLY between these markers) -->"
_CONTENT_END = "<!-- END: commentable-html - CONTENT -->"


class _BinaryStdin:
    def __init__(self, text):
        self.buffer = io.BytesIO(text.encode("utf-8"))


def _normalize(text):
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _inner_html(block):
    match = re.search(r"(?s)^<pre\b[^>]*>(.*)</pre>$", block)
    if not match:
        raise AssertionError("not a pre block: %r" % block)
    return match.group(1)


class DiffBlockRenderTests(unittest.TestCase):
    def test_diff_body_is_escaped_and_roundtrips(self):
        diff_text = "@@ -1 +1 @@\n-<script>alert(1)</script> & keep\n+ok > done\n"
        block = D.render_diff_block(diff_text, "src/app.py")
        inner = _inner_html(block)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", inner)
        self.assertIn("&amp; keep", inner)
        self.assertIn("ok &gt; done", inner)
        self.assertNotIn("<script", inner)
        self.assertNotIn("<", inner)
        self.assertEqual(html.unescape(inner), _normalize(diff_text))

    def test_wrapper_has_class_label_and_optional_lang(self):
        with_lang = D.render_diff_block("@@\n-old\n+new", "src/x.py", "python")
        self.assertIn('class="cmh-diff"', with_lang)
        self.assertIn('data-diff-label="src/x.py"', with_lang)
        self.assertIn('data-diff-lang="python"', with_lang)

        without_lang = D.render_diff_block("@@\n-old\n+new", "src/x.py")
        self.assertIn('class="cmh-diff"', without_lang)
        self.assertIn('data-diff-label="src/x.py"', without_lang)
        self.assertNotIn("data-diff-lang=", without_lang)

    def test_attribute_values_are_escaped(self):
        block = D.render_diff_block("@@\n-old\n+new", 'a"<b.py', 'py"<thon>')
        self.assertIn('data-diff-label="a&quot;&lt;b.py"', block)
        self.assertIn('data-diff-lang="py&quot;&lt;thon&gt;"', block)

    def test_crlf_and_lf_inputs_render_identically(self):
        lf = "@@ -1 +1 @@\n-old\n+new\n"
        crlf = lf.replace("\n", "\r\n")
        self.assertEqual(D.render_diff_block(lf, "x.txt"), D.render_diff_block(crlf, "x.txt"))


class DiffBlockDiffTests(unittest.TestCase):
    def test_unified_diff_contains_file_headers_and_hunks(self):
        old_text = "line1\nline2\n"
        new_text = "line1\nline3\n"
        diff_text = D.unified_diff(old_text, new_text, "x.txt")
        self.assertIn("--- a/x.txt", diff_text)
        self.assertIn("+++ b/x.txt", diff_text)
        self.assertIn("@@", diff_text)
        self.assertIn("-line2", diff_text)
        self.assertIn("+line3", diff_text)

    def test_unified_diff_is_deterministic(self):
        old_text = "a\nb\n"
        new_text = "a\nc\n"
        self.assertEqual(
            D.unified_diff(old_text, new_text, "demo.txt"),
            D.unified_diff(old_text, new_text, "demo.txt"),
        )

    def test_final_newline_only_difference_is_preserved(self):
        # Old ends with a trailing newline; new does not. The only difference is that
        # missing final newline, which splitlines() would erase. The diff must be
        # non-empty and carry the standard git no-newline marker.
        old_text = "alpha\nbeta\n"
        new_text = "alpha\nbeta"
        diff_text = D.unified_diff(old_text, new_text, "x.txt")
        self.assertNotEqual(diff_text.strip(), "")
        self.assertIn("@@", diff_text)
        self.assertIn("\\ No newline at end of file", diff_text)
        self.assertIn("-beta", diff_text)
        self.assertIn("+beta", diff_text)

    def test_matching_final_newlines_emit_no_marker(self):
        diff_text = D.unified_diff("a\nb\n", "a\nc\n", "x.txt")
        self.assertNotIn("No newline at end of file", diff_text)


class DiffBlockCliTests(unittest.TestCase):
    def test_cli_reads_stdin_with_dash(self):
        diff_text = "@@ -1 +1 @@\n-old\n+new\n"
        result = subprocess.run(
            [sys.executable, DIFF_BLOCK_PY, "--label", "stdin.patch", "-"],
            input=diff_text,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('data-diff-label="stdin.patch"', result.stdout)
        self.assertEqual(html.unescape(_inner_html(result.stdout)), _normalize(diff_text))

    def test_cli_reads_diff_file(self):
        diff_text = "@@ -1 +1 @@\n-old\n+new\n"
        with tempfile.TemporaryDirectory() as temp_dir:
            diff_path = os.path.join(temp_dir, "change.diff")
            with open(diff_path, "w", encoding="utf-8", newline="") as handle:
                handle.write(diff_text.replace("\n", "\r\n"))
            result = subprocess.run(
                [sys.executable, DIFF_BLOCK_PY, "--label", "file.patch", diff_path],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(html.unescape(_inner_html(result.stdout)), _normalize(diff_text))

    def test_cli_from_files_generates_unified_diff(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            old_path = os.path.join(temp_dir, "old.txt")
            new_path = os.path.join(temp_dir, "new.txt")
            with open(old_path, "w", encoding="utf-8", newline="") as handle:
                handle.write("line1\nline2\n")
            with open(new_path, "w", encoding="utf-8", newline="") as handle:
                handle.write("line1\nline3\n")
            result = subprocess.run(
                [
                    sys.executable,
                    DIFF_BLOCK_PY,
                    "--from-files",
                    old_path,
                    new_path,
                    "--diff-label",
                    "src/file.txt",
                    "--lang",
                    "text",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('data-diff-label="src/file.txt"', result.stdout)
        self.assertIn('data-diff-lang="text"', result.stdout)
        diff_text = html.unescape(_inner_html(result.stdout))
        self.assertIn("@@", diff_text)
        self.assertIn("--- a/src/file.txt", diff_text)
        self.assertIn("+++ b/src/file.txt", diff_text)

    def test_cli_from_files_uses_new_file_basename_when_label_omitted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            old_path = os.path.join(temp_dir, "old.txt")
            new_path = os.path.join(temp_dir, "new-name.txt")
            with open(old_path, "w", encoding="utf-8", newline="") as handle:
                handle.write("x\n")
            with open(new_path, "w", encoding="utf-8", newline="") as handle:
                handle.write("y\n")
            result = subprocess.run(
                [sys.executable, DIFF_BLOCK_PY, "--from-files", old_path, new_path],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('data-diff-label="new-name.txt"', result.stdout)
        diff_text = html.unescape(_inner_html(result.stdout))
        self.assertIn("--- a/new-name.txt", diff_text)
        self.assertIn("+++ b/new-name.txt", diff_text)

    def test_cli_invalid_usage_and_missing_file_return_exit_code_2(self):
        no_args = subprocess.run([sys.executable, DIFF_BLOCK_PY], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(no_args.returncode, 2)
        self.assertIn("usage:", no_args.stderr)

        missing_file = subprocess.run(
            [sys.executable, DIFF_BLOCK_PY, "--label", "x", "no-such-file.diff"],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(missing_file.returncode, 2)
        self.assertIn("diff_block:", missing_file.stderr)


class DiffBlockMainTests(unittest.TestCase):
    def test_main_reports_argument_combinations(self):
        self.assertEqual(D.main(["--label", "x", "--diff-label", "y"]), 2)
        self.assertEqual(D.main(["--from-files", "a", "b", "extra.diff"]), 2)

    def test_main_warns_for_large_diff_without_failing(self):
        huge_diff = "\n".join("+line%d" % i for i in range(2001))
        out = io.StringIO()
        err = io.StringIO()
        with mock.patch.object(sys, "stdin", _BinaryStdin(huge_diff)), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = D.main(["--label", "big.diff", "-"])
        self.assertEqual(code, 0)
        self.assertIn("warning", err.getvalue())
        self.assertIn('data-diff-label="big.diff"', out.getvalue())

    def test_main_from_files_mode_reads_files(self):
        out = io.StringIO()
        err = io.StringIO()
        with tempfile.TemporaryDirectory() as temp_dir:
            old_path = os.path.join(temp_dir, "old.txt")
            new_path = os.path.join(temp_dir, "new.txt")
            with open(old_path, "w", encoding="utf-8", newline="") as handle:
                handle.write("before\nline\n")
            with open(new_path, "w", encoding="utf-8", newline="") as handle:
                handle.write("after\nline\n")
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = D.main(["--from-files", old_path, new_path, "--diff-label", "demo.txt"])
        self.assertEqual(code, 0)
        self.assertEqual(err.getvalue(), "")
        rendered = out.getvalue()
        self.assertIn('data-diff-label="demo.txt"', rendered)
        self.assertIn("@@", html.unescape(_inner_html(rendered)))

    def test_main_reads_diff_file_path(self):
        out = io.StringIO()
        err = io.StringIO()
        with tempfile.TemporaryDirectory() as temp_dir:
            diff_path = os.path.join(temp_dir, "change.diff")
            with open(diff_path, "w", encoding="utf-8", newline="") as handle:
                handle.write("@@ -1 +1 @@\n-old\n+new\n")
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = D.main(["--label", "change.diff", diff_path])
        self.assertEqual(code, 0)
        self.assertEqual(err.getvalue(), "")
        self.assertIn('data-diff-label="change.diff"', out.getvalue())

    def test_main_missing_file_returns_2(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = D.main(["--label", "x", "no-such-file.diff"])
        self.assertEqual(code, 2)
        self.assertIn("diff_block:", err.getvalue())

    def test_warn_if_large_ignores_empty_diff(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            D._warn_if_large("")
        self.assertEqual(err.getvalue(), "")

    def test_module_entrypoint_uses_sys_argv(self):
        err = io.StringIO()
        with mock.patch.object(sys, "argv", [DIFF_BLOCK_PY]), contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as cm:
                runpy.run_path(DIFF_BLOCK_PY, run_name="__main__")
        self.assertEqual(cm.exception.code, 2)
        self.assertIn("usage:", err.getvalue())


class DiffBlockValidatorTests(unittest.TestCase):
    def test_rendered_block_passes_validate_in_template(self):
        with open(TEMPLATE, encoding="utf-8") as handle:
            template_html = handle.read()

        diff_text = "@@ -1 +1 @@\n-<unsafe>\n+safe\n"
        block = D.render_diff_block(diff_text, "src/reducer.py", "python")
        replacement = (
            _CONTENT_START
            + "\n<section>\n  <h2>Diff validation</h2>\n  "
            + block
            + "\n</section>\n"
            + _CONTENT_END
        )
        content_re = re.compile(re.escape(_CONTENT_START) + r"(?s:.*?)" + re.escape(_CONTENT_END))
        rendered, count = content_re.subn(replacement, template_html, count=1)
        self.assertEqual(count, 1)

        with tempfile.TemporaryDirectory() as temp_dir:
            html_path = os.path.join(temp_dir, "diff-check.html")
            with open(html_path, "w", encoding="utf-8", newline="") as handle:
                handle.write(rendered)
            errors, warnings = validate.validate(html_path)

        self.assertEqual(errors, [], "expected no validator errors, got: %r" % errors)
        self.assertEqual(warnings, [], "expected no validator warnings, got: %r" % warnings)


if __name__ == "__main__":
    unittest.main()
