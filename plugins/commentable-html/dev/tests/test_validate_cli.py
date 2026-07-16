from _validate_helpers import *


class ValidateCliTests(unittest.TestCase):
    def _run(self, *args):
        return subprocess.run([sys.executable, VALIDATE_PY, *args], capture_output=True, text=True)

    def _write(self, d, name, content, raw=None):
        p = os.path.join(d, name)
        if raw is not None:
            with open(p, "wb") as fh:
                fh.write(raw)
        else:
            with open(p, "w", encoding="utf-8", newline="") as fh:
                fh.write(content)
        return p

    def test_no_args_exit_2(self):
        self.assertEqual(self._run().returncode, 2)

    def test_both_flags_exit_2(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d, "ok.html", build())
            self.assertEqual(self._run("--charts-only", "--layer-only", p).returncode, 2)

    def test_unknown_flag_exit_2(self):
        # An unrecognized --flag must fail loudly rather than being silently ignored.
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d, "ok.html", build())
            r = self._run("--layer-onyl", p)
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            self.assertIn("unknown flag", r.stderr)
            self.assertIn("--layer-onyl", r.stderr)

    def test_layer_only_suppresses_chart_errors(self):
        # Layer-valid doc with an unskipped <canvas> (a chart E1). --layer-only must
        # skip the chart half, so exit 0 and no chart error text.
        doc = build().replace("</main>", '<canvas id="z" role="img" aria-label="x"></canvas></main>')
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d, "layeronly.html", doc)
            r = self._run("--layer-only", p)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertNotIn("not inside a cm-skip", r.stdout)

    def test_charts_only_suppresses_layer_errors(self):
        # Layer-broken doc (a mangled region marker) but no <canvas>. --charts-only
        # skips the layer half, so exit 0 with no region error.
        doc = build().replace("BEGIN: commentable-html - CSS", "BEGIN: commentable-html - BROKEN")
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d, "chartsonly.html", doc)
            r = self._run("--charts-only", p)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertNotIn("region", r.stdout)

    def test_valid_file_exit_0(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d, "ok.html", build())
            r = self._run(p)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("OK (0 warning(s))", r.stdout)

    def test_warning_only_file_exit_0(self):
        main = '<main id="commentRoot" data-cmh-content-root data-comment-key="k" data-doc-label="l"><p>x</p></main>'
        doc = build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION])
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d, "warn.html", doc)
            r = self._run(p)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("WARNING", r.stdout)

    def test_broken_file_exit_1(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d, "bad.html", "not a commentable document")
            self.assertEqual(self._run(p).returncode, 1)

    def test_kql_figure_missing_run_link_exit_1(self):
        # A framed figure.cmh-kql without a run link is a hard error, so the CLI must
        # exit non-zero in the DEFAULT (non-strict) mode, not merely print a warning.
        fig = ('<figure class="cmh-kql"><figcaption class="cm-skip">'
               '<button class="cmh-kql-title" type="button">cluster</button></figcaption>'
               '<pre><code class="language-kusto">T | take 1</code></pre></figure>')
        main = MAIN.replace("<p>content</p>", "<p>content</p>" + fig)
        doc = build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION])
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d, "kqlnorun.html", doc)
            r = self._run(p)
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertIn("Run in Azure Data Explorer", r.stdout)

    def test_non_utf8_does_not_crash(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d, "bin.html", None, raw=b"\xff\xfe\x00\x01 not utf-8")
            r = self._run(p)
            out = r.stdout + r.stderr
            self.assertNotIn("Traceback (most recent call last)", out)
            self.assertIn("cannot read file", out)
            self.assertEqual(r.returncode, 1)

    def test_batch_continues_after_bad_file(self):
        with tempfile.TemporaryDirectory() as d:
            bad = self._write(d, "bin.html", None, raw=b"\xff\xfe garbage")
            good = self._write(d, "good.html", build())
            r = self._run(bad, good)
            out = r.stdout + r.stderr
            self.assertNotIn("Traceback (most recent call last)", out)
            self.assertIn("cannot read file", out)
            self.assertIn("OK (0 warning(s))", out)
            self.assertEqual(r.returncode, 1)

    def test_directory_argument_is_reported_not_crashed(self):
        with tempfile.TemporaryDirectory() as d:
            r = self._run(d)
            out = r.stdout + r.stderr
            self.assertNotIn("Traceback (most recent call last)", out)
            self.assertIn("cannot read file", out)
            self.assertEqual(r.returncode, 1)

class ValidateMainTests(unittest.TestCase):
    def test_main_guards_each_file_against_internal_errors(self):
        # A crash inside validate() for one file must be reported as an internal
        # error but must not abort the batch: the second file still validates.
        buf = io.StringIO()
        with mock.patch.object(validate, "validate", side_effect=[RuntimeError("boom"), ([], [])]):
            with contextlib.redirect_stdout(buf):
                rc = validate.main(["validate.py", "a.html", "b.html"])
        out = buf.getvalue()
        self.assertEqual(rc, 1)
        self.assertIn("internal validator error", out)
        self.assertIn("a.html", out)
        self.assertIn("b.html", out)
        self.assertIn("OK", out)  # b.html still validated

    def test_main_returns_0_when_all_clean(self):
        buf = io.StringIO()
        with mock.patch.object(validate, "validate", return_value=([], [])):
            with contextlib.redirect_stdout(buf):
                rc = validate.main(["validate.py", "x.html"])
        self.assertEqual(rc, 0)

    def test_help_flag_prints_usage(self):
        # CMH-TOOL-01: -h/--help print usage plus the flag list and exit 0.
        for flag in ("--help", "-h"):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = validate.main(["validate.py", flag])
            out = buf.getvalue()
            self.assertEqual(rc, 0, out)
            self.assertIn("usage:", out)
            self.assertIn("--charts-only", out)
            self.assertIn("--strict", out)

    def test_double_dash_separator_treats_following_token_as_path(self):
        # CMH-TOOL-01: a bare "--" ends options, so a following dash-led token is a
        # PATH, not an unknown flag. A missing such file exits 1 (a read error), not
        # 2 (which is what an unrecognized flag before "--" would produce).
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = validate.main(["validate.py", "--", "--not-a-flag.html"])
        out = buf.getvalue()
        self.assertEqual(rc, 1, out)
        self.assertIn("--not-a-flag.html", out)
        self.assertIn("cannot read file", out)

class ErrorPathTests(unittest.TestCase):
    """The validator's failure and resilience paths: unreadable input, unparseable
    markup, unknown CLI flags, and a check that throws mid-batch."""

    def _tmp(self, text):
        fd, p = tempfile.mkstemp(suffix=".html")
        os.close(fd)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)
        self.addCleanup(lambda: os.path.exists(p) and os.remove(p))
        return p

    def test_validate_unreadable_file_returns_error(self):
        missing = os.path.join(tempfile.gettempdir(), "cmh-does-not-exist-xyz.html")
        errors, warnings = validate.validate(missing)
        self.assertTrue(errors and errors[0].startswith("cannot read file:"))
        self.assertEqual(warnings, [])

    def test_validate_charts_unreadable_file_returns_error(self):
        missing = os.path.join(tempfile.gettempdir(), "cmh-does-not-exist-xyz.html")
        errors, warnings, n = validate.validate_charts(missing)
        self.assertTrue(errors and errors[0].startswith("cannot read file:"))
        self.assertEqual((warnings, n), ([], 0))

    def test_validate_unparseable_markup_reports_parse_failure(self):
        p = self._tmp("<html>ignored</html>")
        with mock.patch.object(validate, "_parse", return_value=(None, False)):
            errors, warnings = validate.validate(p)
        self.assertEqual(errors, [validate._PARSE_FAIL])
        self.assertEqual(warnings, [])

    def test_validate_charts_unparseable_with_canvas_reports_parse_failure(self):
        p = self._tmp("<html><canvas></canvas></html>")
        with mock.patch.object(validate, "_parse", return_value=(None, False)):
            errors, warnings, n = validate.validate_charts(p)
        self.assertEqual(errors, [validate._PARSE_FAIL])
        self.assertEqual(n, 1)

    def test_main_rejects_unknown_flag(self):
        p = self._tmp("<html></html>")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = validate.main(["validate.py", "--bogus", p])
        self.assertEqual(rc, 2)
        self.assertIn("unknown flag(s): --bogus", err.getvalue())

    def test_main_no_files_prints_usage(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = validate.main(["validate.py"])
        self.assertEqual(rc, 2)
        self.assertIn("usage:", err.getvalue())

    def test_main_internal_check_error_does_not_abort_batch(self):
        p = self._tmp("<html></html>")
        out = io.StringIO()
        with mock.patch.object(validate, "validate", side_effect=RuntimeError("boom")):
            with contextlib.redirect_stdout(out):
                rc = validate.main(["validate.py", p])
        self.assertEqual(rc, 1)
        self.assertIn("internal validator error", out.getvalue())


if __name__ == "__main__":
    unittest.main()
