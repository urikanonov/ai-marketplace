#!/usr/bin/env python3
"""CMH-TOOL-IMPORTS-01: guarded sibling imports in the shipped tools are never SILENT.

The #584 root cause was a guarded, deferred `import doc_stamp` swallowed by `except (OSError,
ImportError): pass`, so a broken sibling import degraded a whole feature (stamping) with no signal.
`test_cli_help.py` catches a MODULE-LOAD import failure (it runs each tool's --help as a subprocess)
but not a guarded import inside a function that fires only on a specific path. This test closes that
gap two ways:

  1) RESOLUTION: in the shipped layout every `except ImportError`-guarded sibling import actually
     RESOLVES, so a missing/renamed sibling fails loudly here instead of silently degrading at
     runtime.
  2) NO-SILENT: no ImportError handler in the shipped tools is silent - each must warn (via
     `_toolpath.warn_missing_tool`), re-raise, re-import, or define fallback stubs, never merely
     `pass`/assign a sentinel. This enforces the invariant for FUTURE code too.
"""
import ast
import builtins
import importlib
import importlib.util
import io
import os
import sys
import unittest
from contextlib import redirect_stderr
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402  shared pkg/dev split path constants
TOOLS = _paths.TOOLS
sys.path.insert(0, TOOLS)
import _toolpath  # noqa: E402
_toolpath.ensure()


def _tool_py_files():
    out = []
    for root, dirs, files in os.walk(TOOLS):
        dirs[:] = [d for d in dirs if not d.startswith((".", "__pycache__"))]
        for name in files:
            if name.endswith(".py"):
                out.append(os.path.join(root, name))
    return sorted(out)


def _catches_import_error(handler):
    t = handler.type
    if isinstance(t, ast.Tuple):
        return any(isinstance(e, ast.Name) and e.id == "ImportError" for e in t.elts)
    return isinstance(t, ast.Name) and t.id == "ImportError"


def _guarded_import_names(try_node):
    names = []
    for node in try_node.body:
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.append(node.module)
    return names


def _handler_is_silent(handler):
    # Silent = the handler does nothing visible - only pass / assignments / constant exprs. A handler
    # that raises, CALLS anything (e.g. warn_missing_tool), re-imports, or defines fallback stubs is
    # NOT silent.
    for stmt in handler.body:
        for node in ast.walk(stmt):
            if isinstance(node, (ast.Raise, ast.Call, ast.Import, ast.ImportFrom,
                                 ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                return False
    return True


def _resolves(name):
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError, AttributeError):
        try:
            return importlib.util.find_spec(name.split(".")[0]) is not None
        except Exception:
            return False


class ImportGuardTests(unittest.TestCase):
    def test_there_are_tools_to_scan(self):
        self.assertTrue(_tool_py_files(), "no shipped tool .py files discovered")

    def test_no_shipped_import_fallback_is_silent(self):
        offenders = []
        for path in _tool_py_files():
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Try):
                    for h in node.handlers:
                        if _catches_import_error(h) and _handler_is_silent(h):
                            offenders.append("%s:%d" % (os.path.relpath(path, TOOLS), h.lineno))
        self.assertEqual(
            offenders, [],
            "silent ImportError handler(s) found - a missing sibling would degrade silently. "
            "Call _toolpath.warn_missing_tool (or re-raise/re-import) instead: %r" % offenders)

    def test_every_guarded_sibling_import_resolves_in_the_shipped_layout(self):
        checked = 0
        missing = []
        for path in _tool_py_files():
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Try) and any(_catches_import_error(h) for h in node.handlers):
                    for name in _guarded_import_names(node):
                        checked += 1
                        if not _resolves(name):
                            missing.append("%s: %s" % (os.path.relpath(path, TOOLS), name))
        self.assertGreater(checked, 0, "no guarded sibling imports were discovered to check")
        self.assertEqual(
            missing, [],
            "guarded sibling import(s) do not resolve in the shipped layout - a packaging/path "
            "regression would silently degrade the tool: %r" % missing)


class WarnMissingToolTests(unittest.TestCase):
    def test_warn_missing_tool_writes_a_visible_stderr_warning(self):
        buf = io.StringIO()
        with redirect_stderr(buf):
            _toolpath.warn_missing_tool("doc_stamp", "the validated stamp")
        out = buf.getvalue()
        self.assertIn("doc_stamp", out)
        self.assertIn("WARNING", out)
        self.assertIn("the validated stamp", out)

    def test_warn_missing_tool_never_raises(self):
        # Best-effort: even a broken stderr must not turn a degraded run into a crash.
        buf = io.StringIO()
        with redirect_stderr(buf):
            _toolpath.warn_missing_tool("x")  # no feature suffix

    def test_a_module_level_fallback_warns_when_a_sibling_is_missing(self):
        # Force a fresh import of deck_theme with the sibling 'validate' unimportable and assert the
        # fallback both degrades (_base is None) and WARNS (never silent) - the #584 class, made loud.
        real_import = builtins.__import__

        def fake(name, *a, **k):
            if name == "validate":
                raise ImportError("blocked for test")
            return real_import(name, *a, **k)

        buf = io.StringIO()
        for mod in ("deck_theme", "validate"):
            sys.modules.pop(mod, None)
        try:
            with redirect_stderr(buf), mock.patch.object(builtins, "__import__", fake):
                mod = importlib.import_module("deck_theme")
            self.assertIsNone(mod._base, "the guarded import should have degraded to None")
            self.assertIn("validate", buf.getvalue())
            self.assertIn("WARNING", buf.getvalue())
        finally:
            # Restore a clean, real import so later tests see a working module.
            sys.modules.pop("deck_theme", None)
            importlib.import_module("deck_theme")


if __name__ == "__main__":
    unittest.main()
