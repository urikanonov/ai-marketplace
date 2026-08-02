#!/usr/bin/env python3
"""Regression tests for chart_block.py."""
import builtins
import contextlib
import io
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402  shared pkg/dev split path constants
ROOT = _paths.PKG
TOOLS = _paths.TOOLS
sys.path.insert(0, TOOLS)
import chart_block  # noqa: E402

CHART_BLOCK_PY = os.path.join(TOOLS, "blocks", "chart_block.py")

SPEC = {
    "type": "bar",
    "data": {
        "labels": ["Apr", "May", "Jun"],
        "datasets": [
            {
                "label": "Water need",
                "data": [12, 18, 24],
            }
        ],
    },
    "options": {
        "responsive": True,
        "maintainAspectRatio": False,
        "plugins": {
            "title": {
                "display": True,
                "text": "Growing <season>",
            }
        },
    },
}


class _TextStdin:
    def __init__(self, text):
        self._text = text

    def read(self):
        return self._text


def _extract_json_payload(html_output, data_id):
    match = re.search(
        r'<script id="%s" type="application/json">\n(.*?)\n</script>' % re.escape(data_id),
        html_output,
        re.DOTALL,
    )
    if not match:
        raise AssertionError("missing chart data script for %s" % data_id)
    return match.group(1)


class ChartBlockRenderTests(unittest.TestCase):
    def test_render_contains_expected_figure_shape(self):
        out = chart_block.render_output(SPEC, "wateringNeedsChart", "Weekly water use", title="Garden chart")
        self.assertIn('<figure class="chart" aria-labelledby="wateringNeedsChart-caption">', out)
        self.assertIn('class="chart-wrap cm-skip" style="position: relative; height: 360px; max-height: min(60vh, 480px); overflow: hidden;"', out)
        self.assertIn(
            '<canvas id="wateringNeedsChart" role="img" aria-label="Chart: Garden chart. Weekly water use"></canvas>',
            out,
        )
        self.assertIn('<figcaption id="wateringNeedsChart-caption">Weekly water use</figcaption>', out)

    def test_aria_label_derivation(self):
        self.assertEqual(chart_block.derive_aria_label("Cap", title="Title"), "Chart: Title. Cap")
        self.assertEqual(chart_block.derive_aria_label("Same", title="Same"), "Chart: Same")
        self.assertEqual(chart_block.derive_aria_label("Caption"), "Chart: Caption")

    def test_spec_json_escapes_lt_and_round_trips(self):
        fragments = chart_block.render_chart_fragments(SPEC, "chartA", "Caption", title="Title")
        self.assertIn("\\u003Cseason>", fragments["spec_json"])
        self.assertNotIn("<season>", fragments["spec_json"])
        parsed = json.loads(fragments["spec_json"])
        self.assertEqual(parsed, SPEC)

    def test_self_validate_clean(self):
        fragments = chart_block.render_chart_fragments(SPEC, "chartA", "Caption", title="Title")
        result = chart_block._self_validate(fragments["figure"], fragments["scripts"])
        self.assertIsNotNone(result)
        errors, warnings = result
        self.assertEqual(errors, [], errors)
        self.assertEqual(warnings, [], warnings)

    def test_tools_dir_is_on_sys_path_for_self_validation(self):
        # chart_block runs the tools/_toolpath.py bootstrap at import so `import validate` (and
        # thus self-validation) is not silently skipped under a non-standard invocation. Load the
        # module fresh with the validate bucket (and the tools dirs) removed from sys.path and the
        # cached modules dropped: the bootstrap must re-add them so validate becomes importable.
        import importlib.util
        saved_path = list(sys.path)
        saved_modules = {k: sys.modules[k]
                         for k in ("validate", "chart_block", "_toolpath") if k in sys.modules}
        try:
            for k in ("validate", "chart_block", "_toolpath"):
                sys.modules.pop(k, None)
            validate_dir = os.path.abspath(os.path.join(TOOLS, "validate"))
            drop = {os.path.abspath(TOOLS), validate_dir,
                    os.path.abspath(os.path.join(TOOLS, "blocks"))}
            sys.path[:] = [p for p in sys.path if os.path.abspath(p) not in drop]
            spec = importlib.util.spec_from_file_location(
                "chart_block", os.path.join(TOOLS, "blocks", "chart_block.py"))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            self.assertIn(validate_dir, [os.path.abspath(p) for p in sys.path])
            importlib.import_module("validate")
        finally:
            sys.path[:] = saved_path
            sys.modules.update(saved_modules)

    def test_init_forces_bounded_responsive_options(self):
        fragments = chart_block.render_chart_fragments(SPEC, "chartA", "Caption", title="Title")
        self.assertIn("config.options.responsive = true;", fragments["scripts"])
        self.assertIn("config.options.maintainAspectRatio = false;", fragments["scripts"])

    def test_invalid_canvas_id_rejected(self):
        with self.assertRaises(ValueError):
            chart_block.render_chart_fragments(SPEC, "bad id", "Caption")

    def test_non_object_spec_rejected(self):
        with self.assertRaises(ValueError):
            chart_block.render_chart_fragments([], "chartA", "Caption")


class ChartBlockCliTests(unittest.TestCase):
    def test_cli_reads_spec_file(self):
        with tempfile.TemporaryDirectory() as directory:
            spec_path = os.path.join(directory, "spec.json")
            with open(spec_path, "w", encoding="utf-8", newline="") as fh:
                json.dump(SPEC, fh)
            result = subprocess.run(
                [sys.executable, CHART_BLOCK_PY, "--spec", spec_path, "--canvas-id", "chartA", "--caption", "Caption"],
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = _extract_json_payload(result.stdout, "chartA-data")
        self.assertEqual(json.loads(payload), SPEC)

    def test_cli_reads_stdin_with_dash(self):
        result = subprocess.run(
            [sys.executable, CHART_BLOCK_PY, "--spec", "-", "--canvas-id", "chartA", "--caption", "Caption"],
            input=json.dumps(SPEC),
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('<canvas id="chartA"', result.stdout)
        payload = _extract_json_payload(result.stdout, "chartA-data")
        self.assertEqual(json.loads(payload), SPEC)

    def test_main_stdin_without_buffer_fallback(self):
        out = io.StringIO()
        err = io.StringIO()
        with mock.patch.object(sys, "stdin", _TextStdin(json.dumps(SPEC))), \
                contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(err):
            code = chart_block.main(
                ["chart_block.py", "--spec", "-", "--canvas-id", "chartA", "--caption", "Caption"]
            )
        self.assertEqual(code, 0, err.getvalue())
        self.assertIn('id="chartA-data"', out.getvalue())

    def test_an_advisory_warning_does_not_block_the_output(self):
        # CMH-VAL-18: an advisory names something the author cannot clear, so it is reported but
        # must not fail this self-validating generator; every other warning still does.
        import validate  # noqa: E402
        advisory = validate.HIGHLIGHT_ADVISORY_PREFIX + "a hand-written span"
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "stdin", _TextStdin(json.dumps(SPEC))), \
                mock.patch.object(chart_block, "_self_validate_result",
                                  return_value=(([], [advisory]), None)), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = chart_block.main(
                ["chart_block.py", "--spec", "-", "--canvas-id", "chartA", "--caption", "Caption"]
            )
        self.assertEqual(code, 0, err.getvalue())
        self.assertIn("ADVISORY", err.getvalue())
        self.assertIn('id="chartA-data"', out.getvalue())

    def test_a_fatal_warning_still_blocks_the_output(self):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "stdin", _TextStdin(json.dumps(SPEC))), \
                mock.patch.object(chart_block, "_self_validate_result",
                                  return_value=(([], ["a real warning"]), None)), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = chart_block.main(
                ["chart_block.py", "--spec", "-", "--canvas-id", "chartA", "--caption", "Caption"]
            )
        self.assertEqual(code, 1)
        self.assertIn("do not validate cleanly", err.getvalue())

    def test_invalid_json_spec_exits_non_zero(self):
        result = subprocess.run(
            [sys.executable, CHART_BLOCK_PY, "--spec", "-", "--canvas-id", "chartA", "--caption", "Caption"],
            input="{bad json}",
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("chart_block:", result.stderr)

    def test_missing_spec_file_exits_non_zero(self):
        result = subprocess.run(
            [sys.executable, CHART_BLOCK_PY, "--spec", "missing-spec.json", "--canvas-id", "chartA", "--caption", "Caption"],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("chart_block:", result.stderr)

    def test_non_object_spec_exits_non_zero(self):
        result = subprocess.run(
            [sys.executable, CHART_BLOCK_PY, "--spec", "-", "--canvas-id", "chartA", "--caption", "Caption"],
            input="[]",
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("spec must be a JSON object", result.stderr)


class ChartBlockUnvalidatedOutputTests(unittest.TestCase):
    """CMH-TOOL-13: the generator's one guarantee is that what it prints validates.

    `_self_validate` returns None when the sibling `validate` module cannot be imported -
    a broken or partial install. Printing the fragments anyway would drop that guarantee
    exactly where something is already wrong, so the default is to fail closed.
    """

    ARGV = ["chart_block.py", "--spec", "-", "--canvas-id", "chartA", "--caption", "Caption"]

    @contextlib.contextmanager
    def _validator_unimportable(self):
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "validate":
                raise ModuleNotFoundError("No module named 'validate'", name="validate")
            return real_import(name, *args, **kwargs)

        with mock.patch.dict(sys.modules), mock.patch.object(builtins, "__import__", fake_import):
            sys.modules.pop("validate", None)
            yield

    def _run(self, extra_argv=()):
        out, err = io.StringIO(), io.StringIO()
        with self._validator_unimportable(), \
                mock.patch.object(sys, "stdin", _TextStdin(json.dumps(SPEC))), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = chart_block.main(list(self.ARGV) + list(extra_argv))
        return code, out.getvalue(), err.getvalue()

    def test_an_unimportable_validator_fails_instead_of_printing_fragments(self):
        code, out, err = self._run()
        self.assertNotEqual(code, 0)
        self.assertEqual(out, "", "fragments must not be printed when they could not be validated")
        self.assertIn("could not be self-validated", err)
        # The message must name the actual cause, not just say something went wrong.
        self.assertIn("'validate' tool could not be imported", err)
        self.assertIn("No module named 'validate'", err)
        self.assertIn("--allow-unvalidated-output", err)

    def test_the_explicit_opt_out_still_prints_with_a_warning(self):
        code, out, err = self._run(["--allow-unvalidated-output"])
        self.assertEqual(code, 0, err)
        self.assertIn('id="chartA-data"', out)
        self.assertIn("not self-validated", err)

    def test_a_partial_install_whose_validator_lacks_its_own_deps_also_fails_closed(self):
        # The likelier partial install: validate.py is present but one of ITS imports is
        # missing. That must take the same gate, not surface as a traceback.
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "validate":
                raise ModuleNotFoundError("No module named 'checks.links'", name="checks.links")
            return real_import(name, *args, **kwargs)

        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(sys.modules), mock.patch.object(builtins, "__import__", fake_import), \
                mock.patch.object(sys, "stdin", _TextStdin(json.dumps(SPEC))), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            sys.modules.pop("validate", None)
            code = chart_block.main(list(self.ARGV))
        self.assertNotEqual(code, 0)
        self.assertEqual(out.getvalue(), "")
        self.assertIn("checks.links", err.getvalue(), "the error must name what is actually missing")

    def test_a_foreign_validate_module_is_not_accepted_as_the_checker(self):
        # An unrelated `validate` earlier on sys.path must not be able to hand back a clean
        # verdict it never computed.
        foreign = types.ModuleType("validate")
        foreign.__file__ = os.path.join(tempfile.gettempdir(), "validate.py")
        foreign.validate = lambda path: ([], [])
        with mock.patch.dict(sys.modules, {"validate": foreign}):
            module, reason = chart_block._load_validator()
        self.assertIsNone(module)
        self.assertIn("not this skill's", reason)

    def test_a_non_string_module_file_is_refused_rather_than_raising(self):
        # Every cause must come back as a REASON; a cached module whose __file__ is not a
        # path must not escape as a traceback (which would also make the opt-out
        # unreachable, since _load_validator runs outside the caller's try block).
        odd = types.ModuleType("validate")
        odd.__file__ = object()
        odd.validate = lambda path: ([], [])
        with mock.patch.dict(sys.modules, {"validate": odd}):
            module, reason = chart_block._load_validator()
            self.assertIsNone(module)
            self.assertIn("not this skill's", reason)
            out, err = io.StringIO(), io.StringIO()
            with mock.patch.object(sys, "stdin", _TextStdin(json.dumps(SPEC))), \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = chart_block.main(list(self.ARGV))
            self.assertNotEqual(code, 0)
            self.assertEqual(out.getvalue(), "")
            self.assertIn("could not be self-validated", err.getvalue())
            self.assertIn("--allow-unvalidated-output", err.getvalue())
            # The named reason means the opt-out is reachable rather than pre-empted.
            out, err = io.StringIO(), io.StringIO()
            with mock.patch.object(sys, "stdin", _TextStdin(json.dumps(SPEC))), \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = chart_block.main(list(self.ARGV) + ["--allow-unvalidated-output"])
        self.assertEqual(code, 0, err.getvalue())
        self.assertIn('id="chartA-data"', out.getvalue())

    def test_contained_refuses_a_non_path_value_without_raising(self):
        for value in (object(), 3, b"tools/validate/validate.py", None, ""):
            with self.subTest(value=value):
                self.assertFalse(chart_block._contained(value))

    def test_a_misbehaving_pathlike_file_is_refused_rather_than_raising(self):
        # os.PathLike is accepted by the guard, but a PathLike is only a promise of
        # __fspath__ - one that hands back bytes, or raises, must still be refused rather
        # than reaching realpath/startswith and escaping as a traceback.
        class BytesPath:
            def __fspath__(self):
                return b"tools/validate/validate.py"

        class BrokenPath:
            def __fspath__(self):
                raise RuntimeError("no path here")

        for value in (BytesPath(), BrokenPath()):
            with self.subTest(value=type(value).__name__):
                self.assertFalse(chart_block._contained(value))
        # ...and a well-behaved PathLike naming the real validator is still accepted, so
        # the refusal above is a guard, not a blanket rejection of every PathLike.
        real = pathlib.Path(TOOLS) / "validate" / "validate.py"
        self.assertTrue(chart_block._contained(real))

    def test_an_unformattable_module_file_still_comes_back_as_a_reason(self):
        # The refusal MESSAGE interpolates __file__, so a value that cannot be formatted
        # (a tuple, or one whose __str__ raises) must not turn the named reason back into
        # the traceback this seam exists to replace.
        class Hostile:
            def __str__(self):
                raise RuntimeError("nope")

        for value in ((1, 2), Hostile()):
            with self.subTest(value=type(value).__name__):
                odd = types.ModuleType("validate")
                odd.__file__ = value
                odd.validate = lambda path: ([], [])
                with mock.patch.dict(sys.modules, {"validate": odd}):
                    module, reason = chart_block._load_validator()
                self.assertIsNone(module)
                self.assertIn("not this skill's", reason)

    def _run_with_template(self, template_path, extra_argv=()):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(chart_block, "DEFAULT_TEMPLATE", template_path), \
                mock.patch.object(sys, "stdin", _TextStdin(json.dumps(SPEC))), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = chart_block.main(list(self.ARGV) + list(extra_argv))
        return code, out.getvalue(), err.getvalue()

    def test_a_missing_validation_template_also_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            # A path inside a fresh directory that is deliberately never created, so the test
            # cannot be satisfied (or flapped) by a leftover file from an earlier run.
            code, out, err = self._run_with_template(os.path.join(directory, "absent.html"))
        self.assertNotEqual(code, 0)
        self.assertEqual(out, "")
        self.assertIn("template could not be prepared", err)

    def test_a_corrupt_validation_template_also_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            corrupt = os.path.join(directory, "corrupt.html")
            with open(corrupt, "w", encoding="utf-8", newline="") as fh:
                fh.write("<html><body>no content markers here</body></html>")
            code, out, err = self._run_with_template(corrupt)
            self.assertNotEqual(code, 0)
            self.assertEqual(out, "")
            self.assertIn("template could not be prepared", err)
            # The same shape is opt-out-able, like every other "could not be checked" cause.
            code, out, err = self._run_with_template(corrupt, ["--allow-unvalidated-output"])
        self.assertEqual(code, 0, err)
        self.assertIn('id="chartA-data"', out)
        self.assertIn("not self-validated", err)

    def test_a_crashing_validator_fails_closed_rather_than_raising(self):
        boom = types.SimpleNamespace(validate=mock.Mock(side_effect=RuntimeError("kaboom")))
        with mock.patch.object(chart_block, "_load_validator", return_value=(boom, None)):
            out, err = io.StringIO(), io.StringIO()
            with mock.patch.object(sys, "stdin", _TextStdin(json.dumps(SPEC))), \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = chart_block.main(list(self.ARGV))
        self.assertNotEqual(code, 0)
        self.assertEqual(out.getvalue(), "")
        self.assertIn("validator could not run", err.getvalue())
        self.assertIn("kaboom", err.getvalue())

    def test_a_corrupt_validator_source_fails_closed_rather_than_raising(self):
        # The most literal partial install: validate.py is present but truncated, so importing
        # it raises SyntaxError. That must take the same gate as any other "could not check".
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "validate":
                raise SyntaxError("unterminated triple-quoted string literal")
            return real_import(name, *args, **kwargs)

        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(sys.modules), mock.patch.object(builtins, "__import__", fake_import), \
                mock.patch.object(sys, "stdin", _TextStdin(json.dumps(SPEC))), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            sys.modules.pop("validate", None)
            code = chart_block.main(list(self.ARGV))
        self.assertNotEqual(code, 0)
        self.assertEqual(out.getvalue(), "")
        self.assertIn("SyntaxError", err.getvalue())

    def test_a_validator_answering_in_an_unexpected_shape_is_not_treated_as_clean(self):
        # A validator that returns None must not be laundered into "checked and clean", and
        # must not become an emitted-anyway result under the opt-out either.
        for outcome in (None, ([], [], []), (None, None), ([], None), ("", "")):
            with self.subTest(outcome=outcome):
                broken = types.SimpleNamespace(validate=mock.Mock(return_value=outcome))
                with mock.patch.object(chart_block, "_load_validator", return_value=(broken, None)):
                    out, err = io.StringIO(), io.StringIO()
                    with mock.patch.object(sys, "stdin", _TextStdin(json.dumps(SPEC))), \
                            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                        code = chart_block.main(list(self.ARGV))
                self.assertNotEqual(code, 0)
                self.assertEqual(out.getvalue(), "")
                self.assertIn("unexpected result", err.getvalue())

    def test_the_opt_out_does_not_suppress_a_real_validation_failure(self):
        # The flag means "I accept fragments that could not be CHECKED", never "skip the
        # check". Widening it into the latter must fail this test.
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(chart_block, "_self_validate_result",
                               return_value=((["boom"], []), None)), \
                mock.patch.object(sys, "stdin", _TextStdin(json.dumps(SPEC))), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = chart_block.main(list(self.ARGV) + ["--allow-unvalidated-output"])
        self.assertNotEqual(code, 0)
        self.assertEqual(out.getvalue(), "")
        self.assertIn("do not validate cleanly", err.getvalue())

    def test_a_working_validator_with_the_flag_still_validates_and_succeeds(self):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "stdin", _TextStdin(json.dumps(SPEC))), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = chart_block.main(list(self.ARGV) + ["--allow-unvalidated-output"])
        self.assertEqual(code, 0, err.getvalue())
        self.assertIn('id="chartA-data"', out.getvalue())
        # It ran the real check, so it must NOT have taken the unvalidated warning path.
        self.assertNotIn("not self-validated", err.getvalue())


if __name__ == "__main__":
    unittest.main()
