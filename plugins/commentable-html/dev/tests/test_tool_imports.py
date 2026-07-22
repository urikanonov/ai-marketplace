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
     `_toolpath.warn_missing_tool`), unconditionally re-raise, or re-import the guarded sibling,
     never merely `pass`/assign a sentinel/return. This enforces the invariant for FUTURE code too.

Accepted static-analysis limitations (documented, not gaps we rely on): the detector only sees
STATIC `import`/`from` statements (a guarded `importlib.import_module(...)`/`__import__(...)` is
invisible) and a dotted relative re-import (`from .sub import x`); no shipped guard uses either, and
`test_cli_help.py` still exercises every tool's module-load imports as a subprocess backstop.
"""
import ast
import builtins
import importlib
import importlib.util
import io
import os
import sys
import textwrap
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


def _type_name(node):
    """The exception class name for an ``except`` clause type node - the bare name for `ImportError`
    and the trailing attribute for a qualified `builtins.ImportError`, so a qualified handler is not
    silently skipped."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _handler_catches_import_failure(handler):
    t = handler.type
    if t is None:
        return True  # a bare except swallows an import failure too
    if isinstance(t, ast.Tuple):
        return any(_type_name(e) in _IMPORT_FAILURE_TYPES for e in t.elts)
    return _type_name(t) in _IMPORT_FAILURE_TYPES


def _collect_imports(nodes):
    """Import/ImportFrom module names reachable in `nodes`, descending through plain control flow
    (if/for/while/with and their else) but NOT into a nested `try` (whose imports belong to the
    INNER handler) or a nested def/class. So `try: if cond: import sib` is still attributed to the
    outer handler, while a nested try's imports are not."""
    names = []
    for node in nodes:
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                names.append(node.module)
            elif node.level > 0 and node.module is None:
                # `from . import doc_stamp` imports sibling submodule(s) by name.
                names += [a.name for a in node.names]
        elif isinstance(node, (ast.Try, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        else:
            for field in ("body", "orelse", "finalbody"):
                child = getattr(node, field, None)
                if isinstance(child, list):
                    names += _collect_imports(child)
    return names


def _guarded_sibling_imports(try_node):
    """Module names imported in the try body that look like SIBLING TOOLS - a bare import that is
    neither stdlib nor the `_toolpath` bootstrap. A Try that imports one of these is an import-guard
    whose handlers must be non-silent, and every such name must resolve under the tools tree."""
    return [n for n in _collect_imports(try_node.body)
            if n.split(".")[0] != "_toolpath" and n.split(".")[0] not in _STDLIB]


def _consumes_all_import_failures(handler):
    # A handler that catches ImportError (the base, which subsumes ModuleNotFoundError), Exception,
    # BaseException, or is a bare except consumes EVERY import failure, so a later handler no longer
    # sees one. A ModuleNotFoundError-only handler does NOT (a plain ImportError falls through).
    t = handler.type
    if t is None:
        return True
    broad = {"ImportError", "Exception", "BaseException"}
    if isinstance(t, ast.Tuple):
        return any(_type_name(e) in broad for e in t.elts)
    return _type_name(t) in broad


def _import_guarding_handlers(try_node):
    """The handlers, in order, that would actually catch an import failure for this try - stopping
    once a handler CONSUMES every import failure (a later broad `except Exception` after such a
    handler never sees the import failure and is not required to be import-visible)."""
    out = []
    for h in try_node.handlers:
        if _handler_catches_import_failure(h):
            out.append(h)
        if _consumes_all_import_failures(h):
            break
    return out


def _is_warn_call(node):
    if not isinstance(node, ast.Call):
        return False
    f = node.func
    return ((isinstance(f, ast.Attribute) and f.attr == "warn_missing_tool")
            or (isinstance(f, ast.Name) and f.id == "warn_missing_tool"))


def _reimports_guarded(stmt, guarded_tops):
    if isinstance(stmt, ast.Import):
        return any(a.name.split(".")[0] in guarded_tops for a in stmt.names)
    if isinstance(stmt, ast.ImportFrom):
        if stmt.level == 0 and stmt.module:
            return stmt.module.split(".")[0] in guarded_tops
        if stmt.level > 0 and stmt.module is None:
            return any(a.name.split(".")[0] in guarded_tops for a in stmt.names)
    return False


def _handler_is_silent(handler, guarded_names):
    # A handler guarding a sibling import is NON-silent only if one of its DIRECT top-level
    # statements makes the failure unconditionally visible: an unconditional `raise`, a
    # warn_missing_tool call, or a re-import of the SAME guarded sibling (a top-level, un-nested
    # re-import propagates its own ImportError on failure, so it is genuinely loud). We check ONLY
    # direct top-level statements - never descending into a conditional, a nested def/class, or a
    # nested `try` - so a warn/re-import that is dead (`if False:`), buried in a nested function, or
    # that could be swallowed by its own recovery `except` does NOT count. Everything else - pass /
    # sentinel / return / an unrelated `import os` - is SILENT and would hide a broken install (the
    # #584 class). This is deliberately CONSERVATIVE: a would-be-loud but non-direct handler is
    # flagged, which just asks the author to warn at the top level (the style we want anyway).
    guarded_tops = {n.split(".")[0] for n in guarded_names}
    for stmt in handler.body:
        if isinstance(stmt, ast.Raise):
            return False
        if isinstance(stmt, ast.Expr) and _is_warn_call(stmt.value):
            return False
        if _reimports_guarded(stmt, guarded_tops):
            return False
        if isinstance(stmt, (ast.Return, ast.Break, ast.Continue)):
            break  # an unconditional exit - any warn/re-import after it is unreachable (silent)
    return True


def _resolves_under_tools(name):
    """True only when `name` resolves to a module/package UNDER the shipped tools tree - so a
    deleted/renamed sibling cannot be masked by an unrelated same-named package elsewhere on
    sys.path."""
    try:
        spec = importlib.util.find_spec(name)
    except Exception:
        return False
    if spec is None:
        return False
    root = os.path.realpath(TOOLS) + os.sep
    locs = []
    if spec.origin and spec.origin not in ("built-in", "frozen"):
        locs.append(spec.origin)
    for loc in (spec.submodule_search_locations or []):
        locs.append(loc)
    return any(os.path.realpath(loc).startswith(root) for loc in locs if loc)


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
                    guarded = _guarded_sibling_imports(node)
                    if guarded:
                        for h in _import_guarding_handlers(node):
                            if _handler_is_silent(h, guarded):
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
                        if not _resolves_under_tools(name):
                            missing.append("%s: %s" % (os.path.relpath(path, TOOLS), name))
        self.assertGreater(checked, 0, "no guarded sibling imports were discovered to check")
        self.assertEqual(
            missing, [],
            "guarded sibling import(s) do not resolve under the shipped tools tree - a packaging/path "
            "regression would silently degrade the tool: %r" % missing)


class DetectorSelfTests(unittest.TestCase):
    """Adversarial self-tests pinning the AST classifier, so a future tightening or bypass is caught
    directly (not only via the real tool files)."""

    def _try(self, src):
        mod = ast.parse(textwrap.dedent(src))
        return next(n for n in ast.walk(mod) if isinstance(n, ast.Try))

    def _lone_guarding_handler_is_silent(self, src):
        t = self._try(src)
        guarded = _guarded_sibling_imports(t)
        handlers = _import_guarding_handlers(t)
        self.assertTrue(guarded, "expected a guarded sibling import in: %s" % src)
        self.assertTrue(handlers, "expected an import-guarding handler in: %s" % src)
        return all(_handler_is_silent(h, guarded) for h in handlers)

    def test_plain_pass_fallback_is_silent(self):
        self.assertTrue(self._lone_guarding_handler_is_silent(
            "try:\n import doc_stamp\nexcept ImportError:\n pass\n"))

    def test_modulenotfounderror_sentinel_fallback_is_silent(self):
        self.assertTrue(self._lone_guarding_handler_is_silent(
            "try:\n import doc_stamp\nexcept ModuleNotFoundError:\n x = None\n"))

    def test_return_fallback_is_silent(self):
        self.assertTrue(self._lone_guarding_handler_is_silent(
            "try:\n import doc_stamp\nexcept ImportError:\n return None\n"))

    def test_a_warn_after_an_unconditional_return_is_silent(self):
        # The warn is unreachable (dead code after `return`), so the failure is still hidden.
        self.assertTrue(self._lone_guarding_handler_is_silent(
            "try:\n import doc_stamp\n"
            "except ImportError:\n return None\n _toolpath.warn_missing_tool('doc_stamp')\n"))

    def test_a_qualified_importerror_handler_is_recognized(self):
        # `except builtins.ImportError: pass` catches the import failure and must be checked (and
        # found silent), not skipped because the type is an attribute rather than a bare name.
        t = self._try(
            "try:\n import doc_stamp\nexcept builtins.ImportError:\n pass\n")
        self.assertTrue(_import_guarding_handlers(t), "qualified ImportError must be caught")
        self.assertTrue(self._lone_guarding_handler_is_silent(
            "try:\n import doc_stamp\nexcept builtins.ImportError:\n pass\n"))

    def test_unrelated_reimport_is_still_silent(self):
        # Re-importing an UNRELATED module (os) does not make the guarded sibling's failure visible.
        self.assertTrue(self._lone_guarding_handler_is_silent(
            "try:\n import doc_stamp\nexcept ImportError:\n import os\n"))

    def test_a_warn_call_is_not_silent(self):
        self.assertFalse(self._lone_guarding_handler_is_silent(
            "try:\n import doc_stamp\nexcept ImportError:\n _toolpath.warn_missing_tool('doc_stamp')\n"))

    def test_a_top_level_reraise_is_not_silent(self):
        self.assertFalse(self._lone_guarding_handler_is_silent(
            "try:\n import doc_stamp\nexcept ImportError:\n raise\n"))

    def test_reimport_of_the_guarded_sibling_is_not_silent(self):
        self.assertFalse(self._lone_guarding_handler_is_silent(
            "try:\n import highlight_code\nexcept ImportError:\n import highlight_code\n"))

    def test_a_dead_conditional_warn_is_still_silent(self):
        # A warn buried under `if False:` never runs, so the failure is still hidden.
        self.assertTrue(self._lone_guarding_handler_is_silent(
            "try:\n import doc_stamp\n"
            "except ImportError:\n if False:\n  _toolpath.warn_missing_tool('doc_stamp')\n"))

    def test_a_warn_defined_in_a_nested_function_is_still_silent(self):
        # Merely DEFINING a function that would warn does not warn when the handler fires.
        self.assertTrue(self._lone_guarding_handler_is_silent(
            "try:\n import doc_stamp\n"
            "except ImportError:\n def _later():\n  _toolpath.warn_missing_tool('doc_stamp')\n"))

    def test_a_conditional_reimport_is_still_silent(self):
        # A re-import under a conditional is not a guaranteed recovery, so it is still silent.
        self.assertTrue(self._lone_guarding_handler_is_silent(
            "try:\n import highlight_code\n"
            "except ImportError:\n if cond:\n  import highlight_code\n"))

    def test_a_reimport_in_a_swallowing_recovery_try_is_silent(self):
        # A re-import nested in a recovery `try` whose own handler swallows the failure hides the
        # original missing import on the success path (side effect) AND the failure path (pass) -
        # exactly the #584 class. The detector only credits DIRECT top-level statements, so this is
        # correctly SILENT (do not descend into nested try bodies/handlers).
        self.assertTrue(self._lone_guarding_handler_is_silent(
            "try:\n import highlight_code\n"
            "except ImportError:\n try:\n  import highlight_code\n except Exception:\n  pass\n"))

    def test_a_warn_in_a_recovery_try_handler_is_conservatively_silent(self):
        # A warn buried in a recovery try's handler does not run when the try body succeeds, so the
        # failure can stay hidden; the conservative detector flags it (the author should warn at the
        # handler's top level instead).
        self.assertTrue(self._lone_guarding_handler_is_silent(
            "try:\n import doc_stamp\n"
            "except ImportError:\n try:\n  fix_path()\n"
            " except Exception:\n  _toolpath.warn_missing_tool('doc_stamp')\n"))

    def test_a_guarded_relative_from_import_is_a_sibling(self):
        # `from . import doc_stamp` must be tracked, or a guarded relative import bypasses the guard.
        t = self._try(
            "try:\n from . import doc_stamp\nexcept ImportError:\n pass\n")
        self.assertIn("doc_stamp", _guarded_sibling_imports(t))
        self.assertTrue(all(_handler_is_silent(h, ["doc_stamp"]) for h in t.handlers))

    def test_import_nested_in_control_flow_is_still_guarded(self):
        # `try: if cond: import sib` must still be attributed to the outer handler.
        t = self._try("try:\n if cond:\n  import doc_stamp\nexcept ImportError:\n pass\n")
        self.assertIn("doc_stamp", _guarded_sibling_imports(t))

    def test_a_nested_try_import_is_not_attributed_to_the_outer(self):
        # The inner try's import belongs to the INNER handler, not the outer one.
        t = self._try(
            "try:\n try:\n  import doc_stamp\n except ImportError:\n  raise\nexcept ValueError:\n pass\n")
        self.assertEqual(_guarded_sibling_imports(t), [])

    def test_stdlib_import_guard_is_not_a_sibling(self):
        self.assertEqual(
            _guarded_sibling_imports(self._try("try:\n import json\nexcept ImportError:\n pass\n")), [])

    def test_toolpath_bootstrap_is_not_a_sibling(self):
        self.assertEqual(
            _guarded_sibling_imports(
                self._try("try:\n import _toolpath\nexcept Exception:\n pass\n")), [])

    def test_broad_except_after_importerror_is_exempt(self):
        # ImportError consumes the import failure; the later broad Exception handler is not required
        # to be import-visible.
        t = self._try("try:\n import doc_stamp\n doc_stamp.run()\n"
                      "except ImportError:\n _toolpath.warn_missing_tool('doc_stamp')\n"
                      "except Exception:\n pass\n")
        self.assertEqual(len(_import_guarding_handlers(t)), 1)

    def test_modulenotfounderror_does_not_consume_a_later_importerror(self):
        # A ModuleNotFoundError-only handler leaves a plain ImportError for a later handler, which
        # must therefore still be checked.
        t = self._try("try:\n import doc_stamp\n"
                      "except ModuleNotFoundError:\n raise\n"
                      "except ImportError:\n pass\n")
        handlers = _import_guarding_handlers(t)
        self.assertEqual(len(handlers), 2)
        guarded = _guarded_sibling_imports(t)
        self.assertTrue(_handler_is_silent(handlers[1], guarded))


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
        # Best-effort: even a BROKEN stderr (whose write() raises) must not turn a degraded run into
        # a crash - warn_missing_tool must swallow it and return normally.
        class _Boom:
            def write(self, *a, **k):
                raise OSError("stderr is broken")

            def flush(self, *a, **k):
                raise OSError("stderr is broken")

        with mock.patch.object(sys, "stderr", _Boom()):
            _toolpath.warn_missing_tool("x")  # must not raise
            _toolpath.warn_missing_tool("x", "some feature")  # must not raise

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
