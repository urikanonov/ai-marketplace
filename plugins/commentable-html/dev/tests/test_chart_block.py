#!/usr/bin/env python3
"""Regression tests for chart_block.py."""
import contextlib
import io
import json
import os
import re
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
import chart_block  # noqa: E402

CHART_BLOCK_PY = os.path.join(TOOLS, "chart_block.py")

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
        # chart_block must add its own tools dir to sys.path so `import validate` (and
        # thus self-validation) is not silently skipped under a non-standard invocation.
        # Load the module fresh with the tools dir removed from sys.path and the cached
        # modules dropped: it must re-add its own dir so validate becomes importable.
        import importlib.util
        saved_path = list(sys.path)
        saved_modules = {k: sys.modules[k] for k in ("validate", "chart_block") if k in sys.modules}
        try:
            for k in ("validate", "chart_block"):
                sys.modules.pop(k, None)
            here = os.path.abspath(chart_block.HERE)
            sys.path[:] = [p for p in sys.path if os.path.abspath(p) != here]
            spec = importlib.util.spec_from_file_location(
                "chart_block", os.path.join(TOOLS, "chart_block.py"))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            self.assertIn(mod.HERE, sys.path)
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


if __name__ == "__main__":
    unittest.main()
