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


# Exception types that catch an import failure: ImportError, its subclass ModuleNotFoundError, and
# the broad catches that also swallow one. A handler of any of these that guards a sibling-tool
# import must not be silent.
_IMPORT_FAILURE_TYPES = frozenset({"ImportError", "ModuleNotFoundError", "Exception", "BaseException"})
# Standard-library top-level module names, so a guarded `import os`/`import json` is not mistaken for
# a sibling tool. `_toolpath` is the sys.path bootstrap, not a sibling tool, and its own guard cannot
# call warn_missing_tool (which lives IN _toolpath) - a bootstrap failure surfaces loudly via the
# hard sibling imports that immediately follow it - so it is excluded too.
_STDLIB = frozenset(getattr(sys, "stdlib_module_names", ())) | frozenset((
    "os", "sys", "re", "io", "json", "ast", "importlib", "subprocess", "tempfile", "shutil"))


def _handler_catches_import_failure(handler):
    t = handler.type
    if t is None:
        return True  # a bare except swallows an import failure too
    if isinstance(t, ast.Tuple):
        return any(isinstance(e, ast.Name) and e.id in _IMPORT_FAILURE_TYPES for e in t.elts)
    return isinstance(t, ast.Name) and t.id in _IMPORT_FAILURE_TYPES


def _catches_specific_import_error(handler):
    # True when the handler catches ImportError/ModuleNotFoundError SPECIFICALLY - such a handler
    # consumes the import failure, so a later broad `except Exception` on the same try no longer sees
    # it (and need not be import-visible).
    t = handler.type
    specific = {"ImportError", "ModuleNotFoundError"}
    if isinstance(t, ast.Tuple):
        return any(isinstance(e, ast.Name) and e.id in specific for e in t.elts)
    return isinstance(t, ast.Name) and t.id in specific


def _import_guarding_handlers(try_node):
    """The handlers, in order, that would actually catch an import failure for this try - stopping
    once ImportError/ModuleNotFoundError is caught (a later broad `except Exception` for a non-import
    error then never sees the import failure and is not required to be import-visible)."""
    out = []
    for h in try_node.handlers:
        if _handler_catches_import_failure(h):
            out.append(h)
        if _catches_specific_import_error(h):
            break
    return out


def _guarded_sibling_imports(try_node):
    """Top-level module names imported in the try body that look like SIBLING TOOLS - a bare import
    that is neither stdlib nor the `_toolpath` bootstrap. A Try that imports one of these is an
    import-guard whose handlers must be non-silent, and every such name must resolve."""
    names = []
    for node in try_node.body:
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.append(node.module)
    return [n for n in names if n.split(".")[0] != "_toolpath" and n.split(".")[0] not in _STDLIB]


def _is_warn_call(node):
    if not isinstance(node, ast.Call):
        return False
    f = node.func
    return ((isinstance(f, ast.Attribute) and f.attr == "warn_missing_tool")
            or (isinstance(f, ast.Name) and f.id == "warn_missing_tool"))


def _handler_is_silent(handler):
    # A handler guarding a sibling import is NON-silent only if it makes the failure visible: it
    # calls warn_missing_tool, UNCONDITIONALLY re-raises (a top-level `raise`), or recovers by
    # re-importing. Anything else - pass / assign a sentinel / return, even with a nested CONDITIONAL
    # raise - is SILENT and would hide a broken install (the #584 class).
    for stmt in handler.body:
        if isinstance(stmt, ast.Raise):
            return False  # a top-level, unconditional re-raise is loud
    for stmt in handler.body:
        for node in ast.walk(stmt):
            if isinstance(node, (ast.Import, ast.ImportFrom)) or _is_warn_call(node):
                return False
    return True


def _resolves(name):
    try:
        return importlib.util.find_spec(name) is not None
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
                if isinstance(node, ast.Try) and _guarded_sibling_imports(node):
                    for h in _import_guarding_handlers(node):
                        if _handler_is_silent(h):
                            offenders.append("%s:%d" % (os.path.relpath(path, TOOLS), h.lineno))
        self.assertEqual(
            offenders, [],
            "silent import fallback(s) found - a missing sibling tool would degrade silently. Call "
            "_toolpath.warn_missing_tool (or re-raise / re-import) in the handler: %r" % offenders)

    def test_every_guarded_sibling_import_resolves_in_the_shipped_layout(self):
        checked = 0
        missing = []
        for path in _tool_py_files():
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Try) and any(
                        _handler_catches_import_failure(h) for h in node.handlers):
                    for name in _guarded_sibling_imports(node):
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
        # Force a fresh import of deck_theme with the sibling 'validate' unimportable and assert its
        # fallback both degrades (_base is None) and WARNS via warn_missing_tool - never silent (the
        # #584 class, made loud). mock.patch.dict snapshots and fully restores sys.modules, so this is
        # hermetic and cannot leave a degraded module cached for other tests; spying on
        # warn_missing_tool pins deck_theme's OWN warning regardless of any transitive tool imports.
        real_import = builtins.__import__

        def fake(name, *a, **k):
            if name == "validate":
                raise ModuleNotFoundError("blocked for test", name="validate")
            return real_import(name, *a, **k)

        with mock.patch.dict(sys.modules), \
                mock.patch.object(_toolpath, "warn_missing_tool") as spy, \
                mock.patch.object(builtins, "__import__", fake):
            sys.modules.pop("deck_theme", None)
            sys.modules.pop("validate", None)
            mod = importlib.import_module("deck_theme")
            self.assertIsNone(mod._base, "the guarded import should have degraded to None")
            calls = [tuple(c.args) for c in spy.call_args_list]
            self.assertIn(
                ("validate", "deck theme validation"), calls,
                "deck_theme must warn about the missing 'validate' sibling; calls=%r" % calls)


if __name__ == "__main__":
    unittest.main()
