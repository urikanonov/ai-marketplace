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
import _io_faults  # noqa: E402
import finalize  # noqa: E402

TEMPLATE = os.path.join(ROOT, "dist", "SHAREABLE.html")


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

        def fake_validate(doc_path, html=None, **kwargs):
            calls.append("validate")
            # Validation now receives the IN-MEMORY document rather than re-reading the file,
            # so assert on what it was handed. That is the stronger check anyway: it pins that
            # every earlier phase's output was threaded through to validation.
            self.assertEqual(html, "<html><body>seed</body></html>[toc][fix-skip][inline-images]")
            # The file must NOT have been written yet - the single write happens after
            # validation and stamping (CMH-BUILD-20).
            with open(doc_path, "r", encoding="utf-8") as fh:
                self.assertEqual(fh.read(), "<html><body>seed</body></html>")
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
        # Mock the PHASE TRANSFORMS the pipeline actually calls. Mocking the old per-file
        # `_run_*` wrappers made this vacuous once they stopped being the call path: the
        # assertions passed because nothing called them, not because the steps were skipped.
        with mock.patch.object(finalize, "_apply_toc", return_value=("", False)) as apply_toc, \
                mock.patch.object(finalize, "_apply_fix_skip", return_value=("", False, 0)) as apply_fix, \
                mock.patch.object(finalize, "_apply_inline_images",
                                  return_value=("", False, 0, [])) as apply_inline, \
                mock.patch.object(finalize.validate, "validate", return_value=([], [])):
            code, _out, err = self._run_main(["finalize.py", path])
        self.assertEqual(code, 0, err)
        apply_toc.assert_not_called()
        apply_fix.assert_not_called()
        apply_inline.assert_not_called()

    def test_step_flags_enable_each_step(self):
        directory = self._tmpdir()
        path = os.path.join(directory, "doc.html")
        source = "<html><body>x</body></html>"
        self._write(path, source)
        images_base = os.path.join(directory, "images")
        os.mkdir(images_base)
        # Each phase must receive the document TEXT (threaded in memory), not a path, and the
        # inline-images phase must still be handed the images base directory.
        with mock.patch.object(finalize, "_apply_toc",
                               side_effect=lambda h: (h, False)) as apply_toc, \
                mock.patch.object(finalize, "_apply_fix_skip",
                                  side_effect=lambda h: (h, False, 0)) as apply_fix, \
                mock.patch.object(finalize, "_apply_inline_images",
                                  side_effect=lambda h, b: (h, False, 0, [])) as apply_inline, \
                mock.patch.object(finalize.validate, "validate", return_value=([], [])):
            code, _out, err = self._run_main(
                ["finalize.py", path, "--toc", "--fix-skip", "--inline-images", "--images-base", images_base]
            )
        self.assertEqual(code, 0, err)
        apply_toc.assert_called_once()
        apply_fix.assert_called_once()
        apply_inline.assert_called_once()
        self.assertEqual(apply_inline.call_args[0][1], images_base)
        for call in (apply_toc.call_args, apply_fix.call_args, apply_inline.call_args):
            self.assertIsInstance(call[0][0], str)
            self.assertNotEqual(call[0][0], path)

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
            code, out, err = self._run_main(["finalize.py", path, "--strict"])
        self.assertEqual(code, 1, err)
        # Guardrail (issue #584 #4): the strict-fail reminds the author to end with a clean strict
        # pass to re-stamp, so the runtime "not validated" banner is cleared.
        self.assertIn("re-run", out)
        self.assertIn("--strict", out)
        self.assertIn("banner", out)

    def test_advisory_warnings_do_not_fail_strict_and_still_stamp(self):
        # CMH-VAL-11 / CMH-THEME-02: an ADVISORY warning describes something the author cannot
        # clear (a deliberately hand-written code block, an unresolvable contrast chain), so it
        # must not fail --strict and must not withhold the validated stamp - otherwise the
        # runtime "not validated" banner could never be cleared for such a document.
        directory = self._tmpdir()
        path = os.path.join(directory, "doc.html")
        self._write(path, "<html><head></head><body>x</body></html>")
        advisory = finalize.validate.HIGHLIGHT_ADVISORY_PREFIX + "hand-written span"
        with mock.patch.object(finalize.validate, "validate", return_value=([], [advisory])):
            code, out, err = self._run_main(["finalize.py", path, "--strict"])
        self.assertEqual(code, 0, err)
        self.assertIn("hand-written span", out)  # reported, never hidden
        with open(path, "r", encoding="utf-8") as fh:
            self.assertIn("commentable-html-validated", fh.read())

    def test_a_fatal_warning_beside_an_advisory_still_fails_strict(self):
        directory = self._tmpdir()
        path = os.path.join(directory, "doc.html")
        self._write(path, "<html><head></head><body>x</body></html>")
        advisory = finalize.validate.HIGHLIGHT_ADVISORY_PREFIX + "hand-written span"
        with mock.patch.object(finalize.validate, "validate",
                               return_value=([], [advisory, "real warning"])):
            code, _out, err = self._run_main(["finalize.py", path, "--strict"])
        self.assertEqual(code, 1, err)
        with open(path, "r", encoding="utf-8") as fh:
            self.assertNotIn("commentable-html-validated", fh.read())

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

    def test_normalizes_ai_typography_in_prose_by_default(self):
        # CMH-ASCII-01: finalize rewrites AI smart-typography in prose to ASCII, leaving code verbatim.
        directory = self._tmpdir()
        path = os.path.join(directory, "doc.html")
        self._write(path, "<html><body><p>alpha\u2014beta \u2026 done</p>"
                          "<pre><code>x\u2014y</code></pre></body></html>")
        with mock.patch.object(finalize.validate, "validate", return_value=([], [])):
            code, out, err = self._run_main(["finalize.py", path, "--no-highlight", "--no-stamp"])
        self.assertEqual(code, 0, err)
        with open(path, "r", encoding="utf-8") as fh:
            result = fh.read()
        self.assertIn("alpha - beta ... done", result)     # prose normalized
        self.assertIn("<code>x\u2014y</code>", result)      # code left verbatim
        self.assertNotIn("alpha\u2014beta", result)
        self.assertIn("normalize", out)

    def test_no_normalize_flag_preserves_ai_typography(self):
        directory = self._tmpdir()
        path = os.path.join(directory, "doc.html")
        original = "<html><body><p>alpha\u2014beta</p></body></html>"
        self._write(path, original)
        with mock.patch.object(finalize.validate, "validate", return_value=([], [])):
            code, _out, err = self._run_main(
                ["finalize.py", path, "--no-normalize", "--no-highlight", "--no-stamp"])
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

    def test_an_interrupted_finalize_write_leaves_the_original_document_intact(self):
        # CMH-STAMP-02: finalize rewrites the user's only copy in one write. Opening the target
        # with "w" truncates it before the replacement bytes exist, so an interrupted write
        # (a full disk, a killed run) destroyed a document that had just passed validation.
        directory = self._tmpdir()
        path = os.path.join(directory, "doc.html")
        self._write(path, "<html><head></head><body>x</body></html>")
        with open(path, "rb") as fh:
            original = fh.read()

        for target, real in (("io.open", io.open), ("builtins.open", open)):
            patcher = mock.patch(target, _io_faults.half_writing_opener(real))
            patcher.start()
            self.addCleanup(patcher.stop)
        with mock.patch.object(finalize.validate, "validate", return_value=([], [])):
            code, _out, err = self._run_main(["finalize.py", path])
        # Assert on the RETURN CODE, not on a caught exception: finalize must REPORT a failed
        # write, so an uncaught traceback has to fail this test rather than pass it.
        self.assertEqual(code, 1, "a failed write must be reported, not swallowed")
        self.assertIn("finalize:", err)
        with open(path, "rb") as fh:
            self.assertEqual(fh.read(), original,
                             "a failed finalize write must leave the document byte for byte")
        leftovers = [n for n in os.listdir(directory) if n.startswith(".cmh-")]
        self.assertEqual(leftovers, [], "a staged write must clean up after itself")

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
                ["finalize.py", path, "--no-highlight", "--no-wrap-sections", "--no-stats", "--no-stamp"])
        self.assertEqual(code, 0, err)
        with open(path, "r", encoding="utf-8") as fh:
            self.assertEqual(fh.read(), original)  # unchanged

    def test_bakes_doc_stats_for_report_by_default(self):
        # CMH-STATS-01: finalize bakes the overview strip for a report by default.
        directory = self._tmpdir()
        path = os.path.join(directory, "doc.html")
        self._write(path, self._report_doc(kind="report"))
        with mock.patch.object(finalize.validate, "validate", return_value=([], [])):
            code, out, err = self._run_main(["finalize.py", path, "--no-highlight"])
        self.assertEqual(code, 0, err)
        with open(path, "r", encoding="utf-8") as fh:
            result = fh.read()
        self.assertIn("data-cmh-doc-stats", result)
        self.assertIn("<strong>2</strong> sections", result)
        self.assertIn("doc-stats", out)

    def test_toc_lands_below_the_title_and_the_overview_strip(self):
        # CMH-TOOL-11: the reader meets the title and its reading-time strip before the TOC.
        directory = self._tmpdir()
        path = os.path.join(directory, "doc.html")
        self._write(path, self._report_doc(kind="report"))
        with mock.patch.object(finalize.validate, "validate", return_value=([], [])):
            code, _out, err = self._run_main(["finalize.py", path, "--toc", "--no-highlight"])
        self.assertEqual(code, 0, err)
        with open(path, "r", encoding="utf-8") as fh:
            result = fh.read()
        self.assertLess(result.index("<h1>Title</h1>"), result.index("data-cmh-doc-stats"))
        self.assertLess(result.index("data-cmh-doc-stats"), result.index('<nav class="cm-toc"'))

    def test_no_stats_flag_skips_the_overview_strip(self):
        # CMH-STATS-01: --no-stats keeps finalize from baking the overview strip.
        directory = self._tmpdir()
        path = os.path.join(directory, "doc.html")
        self._write(path, self._report_doc(kind="report"))
        with mock.patch.object(finalize.validate, "validate", return_value=([], [])):
            code, _out, err = self._run_main(["finalize.py", path, "--no-highlight", "--no-stats"])
        self.assertEqual(code, 0, err)
        with open(path, "r", encoding="utf-8") as fh:
            self.assertNotIn("data-cmh-doc-stats", fh.read())

    def test_stats_skipped_for_non_card_kind(self):
        # A generic document does not get the report/plan overview strip.
        directory = self._tmpdir()
        path = os.path.join(directory, "doc.html")
        self._write(path, self._report_doc(kind="generic"))
        with mock.patch.object(finalize.validate, "validate", return_value=([], [])):
            code, _out, err = self._run_main(["finalize.py", path, "--no-highlight", "--no-stamp"])
        self.assertEqual(code, 0, err)
        with open(path, "r", encoding="utf-8") as fh:
            self.assertNotIn("data-cmh-doc-stats", fh.read())

    def test_dedups_existing_ordered_toc_numbers(self):
        # CMH-TOC-10: finalize strips redundant author numbers from an ordered-list .cm-toc.
        directory = self._tmpdir()
        path = os.path.join(directory, "doc.html")
        self._write(path, (
            "<html><head>\n"
            '<meta name="commentable-html-kind" content="plan">\n'
            "</head><body>\n"
            '<main id="commentRoot" data-cmh-content-root data-comment-key="k">\n'
            "  <h1>Title</h1>\n"
            '  <nav class="cm-toc"><ol><li><a href="#a">1. Executive summary</a></li>'
            '<li><a href="#b">2. Scope</a></li></ol></nav>\n'
            '  <section aria-labelledby="a"><h2 id="a">1. Executive summary</h2><p>x</p></section>\n'
            '  <section aria-labelledby="b"><h2 id="b">2. Scope</h2><p>y</p></section>\n'
            "</main>\n</body></html>\n"))
        with mock.patch.object(finalize.validate, "validate", return_value=([], [])):
            code, out, err = self._run_main(["finalize.py", path, "--no-highlight", "--no-stats", "--no-stamp"])
        self.assertEqual(code, 0, err)
        with open(path, "r", encoding="utf-8") as fh:
            result = fh.read()
        self.assertIn('<a href="#a">Executive summary</a>', result)
        self.assertIn('<a href="#b">Scope</a>', result)
        self.assertIn("toc-numbers", out)

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
