#!/usr/bin/env python3
"""Fail-closed behavior when the sibling cmhval/ package cannot be imported.

The content-syntax checks (mermaid, embedded JSON) live in tools/cmhval/, which
ships alongside validate.py. If a broken/partial install makes cmhval
unimportable, validate.py must fail CLOSED for any content it would have
inspected - a validator that silently passes because its checks vanished is worse
than one that reports it cannot check - while a document with no such content
still passes and the --charts-only path (which does not use cmhval) is unaffected.

This loads validate.py fresh with the cmhval import blocked, exercising the
ImportError fallback stubs directly.

Standard library only (unittest).

    python -m unittest tests.test_validate_failclosed   # from plugins/commentable-html/dev
"""
import builtins
import importlib.util
import os
import sys
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import _paths  # noqa: E402

VALIDATE_PY = os.path.join(_paths.TOOLS, "validate.py")


def _load_validate_without_cmhval():
    """Import validate.py under a throwaway module name with `cmhval` unimportable."""
    real_import = builtins.__import__

    def blocked_import(name, *args, **kwargs):
        if name == "cmhval" or name.startswith("cmhval."):
            raise ImportError("cmhval blocked for fail-closed test")
        return real_import(name, *args, **kwargs)

    saved = {k: v for k, v in sys.modules.items() if k == "cmhval" or k.startswith("cmhval.")}
    for k in list(saved):
        del sys.modules[k]
    builtins.__import__ = blocked_import
    try:
        spec = importlib.util.spec_from_file_location("validate_failclosed_probe", VALIDATE_PY)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        builtins.__import__ = real_import
        sys.modules.update(saved)
        sys.modules.pop("validate_failclosed_probe", None)


class CmhvalImportFailClosed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v = _load_validate_without_cmhval()

    def test_import_failure_is_recorded(self):
        self.assertFalse(self.v._CMHVAL_AVAILABLE)

    def test_mermaid_check_fails_closed_when_content_present(self):
        parser = types.SimpleNamespace(mermaid_blocks=["sequenceDiagram\n  A->>B: hi"])
        errors, _ = self.v.check_mermaid_syntax(parser)
        self.assertTrue(errors)
        self.assertIn("unavailable", errors[0])

    def test_mermaid_check_passes_clean_document(self):
        parser = types.SimpleNamespace(mermaid_blocks=[])
        self.assertEqual(self.v.check_mermaid_syntax(parser), ([], []))

    def test_json_check_fails_closed_when_data_block_present(self):
        parser = types.SimpleNamespace(
            canvases=[],
            scripts=[{"attrs": {"type": "application/json", "id": "chartData"}, "body": "{}"}],
        )
        errors, _ = self.v.check_json_blocks(parser, chart_checks_run=True)
        self.assertTrue(errors)
        self.assertIn("unavailable", errors[0])

    def test_json_check_ignores_layer_state_blocks(self):
        parser = types.SimpleNamespace(
            canvases=[],
            scripts=[{"attrs": {"type": "application/json", "id": "embeddedComments"}, "body": "[]"}],
        )
        self.assertEqual(self.v.check_json_blocks(parser, chart_checks_run=True), ([], []))

    def test_json_check_defers_to_chart_path_when_canvas_present(self):
        parser = types.SimpleNamespace(
            canvases=[{"attrs": {}}],
            scripts=[{"attrs": {"type": "application/json", "id": "chartData"}, "body": "{}"}],
        )
        self.assertEqual(self.v.check_json_blocks(parser, chart_checks_run=True), ([], []))

    def test_json_check_passes_clean_document(self):
        parser = types.SimpleNamespace(canvases=[], scripts=[])
        self.assertEqual(self.v.check_json_blocks(parser, chart_checks_run=True), ([], []))


if __name__ == "__main__":
    unittest.main()
