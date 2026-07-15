#!/usr/bin/env python3
"""Regression tests for finalize.py."""
import contextlib
import io
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402  shared pkg/dev split path constants
ROOT = _paths.PKG
TOOLS = _paths.TOOLS
sys.path.insert(0, TOOLS)
import finalize  # noqa: E402

TEMPLATE = os.path.join(ROOT, "dist", "PORTABLE.html")


class FinalizeTests(unittest.TestCase):
    def _tmpdir(self):
        directory = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(directory, ignore_errors=True))
        return directory

    def _write(self, path, text):
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)

    def _run_main(self, argv):
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = finalize.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_fixed_order_is_toc_then_fix_skip_then_inline_then_validate(self):
        directory = self._tmpdir()
        path = os.path.join(directory, "doc.html")
        self._write(path, "<html><body>seed</body></html>")
        calls = []

        def fake_toc(source):
            calls.append("toc")
            return source + "[toc]"

        def fake_fix(source):
            calls.append("fix-skip")
            return source + "[fix-skip]", 1

        def fake_inline(source, base_dir):
            calls.append("inline-images")
            self.assertEqual(base_dir, os.path.dirname(os.path.abspath(path)))
            return source + "[inline-images]", 1, []

        def fake_validate(doc_path):
            calls.append("validate")
            with open(doc_path, "r", encoding="utf-8") as fh:
                current = fh.read()
            self.assertEqual(current, "<html><body>seed</body></html>[toc][fix-skip][inline-images]")
            return [], []

        with mock.patch.object(finalize.generate_toc, "rewrite_html", side_effect=fake_toc), \
                mock.patch.object(finalize.fix_skip, "fix", side_effect=fake_fix), \
                mock.patch.object(finalize.inline_images, "inline_images", side_effect=fake_inline), \
                mock.patch.object(finalize.validate, "validate", side_effect=fake_validate):
            code, _out, err = self._run_main(
                ["finalize.py", path, "--inline-images", "--toc", "--fix-skip"]
            )
        self.assertEqual(code, 0, err)
        self.assertEqual(calls, ["toc", "fix-skip", "inline-images", "validate"])

    def test_no_step_flags_runs_validation_only(self):
        directory = self._tmpdir()
        path = os.path.join(directory, "doc.html")
        self._write(path, "<html><body>x</body></html>")
        with mock.patch.object(finalize, "_run_toc", return_value=False) as run_toc, \
                mock.patch.object(finalize, "_run_fix_skip", return_value=(False, 0)) as run_fix, \
                mock.patch.object(finalize, "_run_inline_images", return_value=(False, 0, [])) as run_inline, \
                mock.patch.object(finalize.validate, "validate", return_value=([], [])):
            code, _out, err = self._run_main(["finalize.py", path])
        self.assertEqual(code, 0, err)
        run_toc.assert_not_called()
        run_fix.assert_not_called()
        run_inline.assert_not_called()

    def test_step_flags_enable_each_step(self):
        directory = self._tmpdir()
        path = os.path.join(directory, "doc.html")
        self._write(path, "<html><body>x</body></html>")
        images_base = os.path.join(directory, "images")
        os.mkdir(images_base)
        with mock.patch.object(finalize, "_run_toc", return_value=False) as run_toc, \
                mock.patch.object(finalize, "_run_fix_skip", return_value=(False, 0)) as run_fix, \
                mock.patch.object(finalize, "_run_inline_images", return_value=(False, 0, [])) as run_inline, \
                mock.patch.object(finalize.validate, "validate", return_value=([], [])):
            code, _out, err = self._run_main(
                ["finalize.py", path, "--toc", "--fix-skip", "--inline-images", "--images-base", images_base]
            )
        self.assertEqual(code, 0, err)
        run_toc.assert_called_once_with(path)
        run_fix.assert_called_once_with(path)
        run_inline.assert_called_once_with(path, images_base)

    def test_warnings_only_are_allowed_without_strict(self):
        directory = self._tmpdir()
        path = os.path.join(directory, "doc.html")
        self._write(path, "<html><body>x</body></html>")
        with mock.patch.object(finalize.validate, "validate", return_value=([], ["warn"])):
            code, _out, err = self._run_main(["finalize.py", path])
        self.assertEqual(code, 0, err)

    def test_warnings_fail_with_strict(self):
        directory = self._tmpdir()
        path = os.path.join(directory, "doc.html")
        self._write(path, "<html><body>x</body></html>")
        with mock.patch.object(finalize.validate, "validate", return_value=([], ["warn"])):
            code, _out, err = self._run_main(["finalize.py", path, "--strict"])
        self.assertEqual(code, 1, err)

    def test_errors_fail_in_all_modes(self):
        directory = self._tmpdir()
        path = os.path.join(directory, "doc.html")
        self._write(path, "<html><body>x</body></html>")
        with mock.patch.object(finalize.validate, "validate", return_value=(["boom"], [])):
            code1, _out1, err1 = self._run_main(["finalize.py", path])
            code2, _out2, err2 = self._run_main(["finalize.py", path, "--strict"])
        self.assertEqual(code1, 1, err1)
        self.assertEqual(code2, 1, err2)

    def test_highlights_code_blocks_by_default(self):
        directory = self._tmpdir()
        path = os.path.join(directory, "doc.html")
        self._write(path, '<html><body><pre><code class="language-python">'
                          "def f():\n    return 1</code></pre></body></html>")
        with mock.patch.object(finalize.validate, "validate", return_value=([], [])):
            code, out, err = self._run_main(["finalize.py", path])
        self.assertEqual(code, 0, err)
        with open(path, "r", encoding="utf-8") as fh:
            result = fh.read()
        self.assertIn("cmh-code-", result)  # the raw language block was highlighted in place
        self.assertIn("highlight", out)

    def test_no_highlight_flag_skips_highlighting(self):
        directory = self._tmpdir()
        path = os.path.join(directory, "doc.html")
        original = ('<html><body><pre><code class="language-python">'
                    "def f():\n    return 1</code></pre></body></html>")
        self._write(path, original)
        with mock.patch.object(finalize.validate, "validate", return_value=([], [])):
            code, _out, err = self._run_main(["finalize.py", path, "--no-highlight", "--no-stamp"])
        self.assertEqual(code, 0, err)
        with open(path, "r", encoding="utf-8") as fh:
            self.assertEqual(fh.read(), original)  # unchanged

    def test_stamps_validated_on_a_strict_clean_finalize(self):
        # CMH-STAMP-02: a strict-clean finalize writes the commentable-html-validated stamp.
        directory = self._tmpdir()
        path = os.path.join(directory, "doc.html")
        self._write(path, "<html><head></head><body>x</body></html>")
        with mock.patch.object(finalize.validate, "validate", return_value=([], [])):
            code, _out, err = self._run_main(["finalize.py", path])
        self.assertEqual(code, 0, err)
        with open(path, "r", encoding="utf-8") as fh:
            self.assertIn("commentable-html-validated", fh.read())

    def test_no_stamp_flag_skips_the_validated_stamp(self):
        # CMH-STAMP-02: --no-stamp keeps a finalize run from writing the validated stamp.
        directory = self._tmpdir()
        path = os.path.join(directory, "doc.html")
        self._write(path, "<html><head></head><body>x</body></html>")
        with mock.patch.object(finalize.validate, "validate", return_value=([], [])):
            code, _out, err = self._run_main(["finalize.py", path, "--no-stamp"])
        self.assertEqual(code, 0, err)
        with open(path, "r", encoding="utf-8") as fh:
            self.assertNotIn("commentable-html-validated", fh.read())

    def _report_doc(self, kind="report"):
        # A minimal full document with a #commentRoot whose report/plan content sits under
        # two bare top-level <h2> headings and no <section> - the flat-card case.
        return (
            "<html><head>\n"
            '<meta name="commentable-html-kind" content="%s">\n' % kind
            + "</head><body>\n"
            '<main id="commentRoot" data-cmh-content-root data-comment-key="k">\n'
            "  <h1>Title</h1>\n"
            '  <h2 id="a">One</h2>\n  <p>a</p>\n'
            '  <h2 id="b">Two</h2>\n  <p>b</p>\n'
            "</main>\n</body></html>\n")

    def test_wraps_sections_for_report_kind_by_default(self):
        # CMH-TOOL-17: finalize wraps bare top-level <h2> blocks in <section> for a report.
        directory = self._tmpdir()
        path = os.path.join(directory, "doc.html")
        self._write(path, self._report_doc(kind="report"))
        with mock.patch.object(finalize.validate, "validate", return_value=([], [])):
            code, out, err = self._run_main(["finalize.py", path, "--no-highlight"])
        self.assertEqual(code, 0, err)
        with open(path, "r", encoding="utf-8") as fh:
            result = fh.read()
        self.assertEqual(result.count("<section"), 2)
        self.assertIn('<section aria-labelledby="a">', result)
        self.assertIn("wrap-sections", out)

    def test_no_wrap_sections_flag_skips_wrapping(self):
        directory = self._tmpdir()
        path = os.path.join(directory, "doc.html")
        original = self._report_doc(kind="report")
        self._write(path, original)
        with mock.patch.object(finalize.validate, "validate", return_value=([], [])):
            code, _out, err = self._run_main(
                ["finalize.py", path, "--no-highlight", "--no-wrap-sections", "--no-stamp"])
        self.assertEqual(code, 0, err)
        with open(path, "r", encoding="utf-8") as fh:
            self.assertEqual(fh.read(), original)  # unchanged

    def test_wrap_sections_skips_non_card_kind(self):
        # A generic document has its own layout; finalize must not wrap its <h2> blocks.
        directory = self._tmpdir()
        path = os.path.join(directory, "doc.html")
        original = self._report_doc(kind="generic")
        self._write(path, original)
        with mock.patch.object(finalize.validate, "validate", return_value=([], [])):
            code, _out, err = self._run_main(["finalize.py", path, "--no-highlight", "--no-stamp"])
        self.assertEqual(code, 0, err)
        with open(path, "r", encoding="utf-8") as fh:
            self.assertNotIn("<section", fh.read())

    def test_clean_template_finalizes_to_exit_zero(self):
        directory = self._tmpdir()
        path = os.path.join(directory, "doc.html")
        with open(TEMPLATE, "r", encoding="utf-8") as fh:
            self._write(path, fh.read())
        code, out, err = self._run_main(["finalize.py", path, "--toc", "--fix-skip", "--inline-images"])
        self.assertEqual(code, 0, err)
        self.assertIn("0 error(s), 0 warning(s)", out)


if __name__ == "__main__":
    unittest.main()
