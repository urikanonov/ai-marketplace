#!/usr/bin/env python3
"""Tests for scripts/check_spec_test_refs.py."""

import collections
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_spec_test_refs as refs  # noqa: E402


class ReadCachingTests(unittest.TestCase):
    """Pin that a file's contents are pulled off disk (and parsed) once per run.

    check_spec resolves every reference independently, so before caching a spec with N rows
    naming the same test file re-read AND re-parsed that file N times. On the real repo that was
    5490 `_read` calls for ~850 files - roughly six reads each - and it made this checker 58.9s,
    about 70% of the always-on pre-push time and part of the required `validate` job (issue #833).

    Caching is safe here because the checker is a short-lived process over a static tree, so there
    is nothing to invalidate. These tests fail on the uncached implementation.
    """

    def setUp(self):
        self.sandbox = Path(tempfile.mkdtemp(prefix="spec-refs-cache-"))
        self.addCleanup(shutil.rmtree, self.sandbox, ignore_errors=True)
        self.base = self.sandbox / "base"
        (self.base / "tests").mkdir(parents=True)
        (self.base / "tests" / "demo.spec.js").write_text(
            "".join("test('browser title (DEMO-%02d)', async () => {});\n" % i
                    for i in range(1, 9)),
            encoding="utf-8", newline="\n",
        )
        (self.base / "tests" / "test_demo.py").write_text(
            "import unittest\n\n"
            "class DemoTests(unittest.TestCase):\n"
            + "".join("    def test_case_%02d(self):\n        pass\n\n" % i
                      for i in range(1, 9)),
            encoding="utf-8", newline="\n",
        )
        rows = "".join(
            "| DEMO-%02d | Behavior %d. | `tests/demo.spec.js` - `browser title (DEMO-%02d)`; "
            "`tests/test_demo.py` - `DemoTests.test_case_%02d` |\n" % (i, i, i, i)
            for i in range(1, 9)
        )
        self.spec = self.sandbox / "SPEC.md"
        self.spec.write_text(
            "# Spec\n\n| Feature id | Behavior | Covering tests |\n| --- | --- | --- |\n" + rows,
            encoding="utf-8", newline="\n",
        )

    def _run_counting_reads(self):
        """Run check_spec, returning a Counter of how often each path was read FROM DISK."""
        counts = collections.Counter()
        original = Path.read_text

        def counting_read_text(self, *args, **kwargs):
            counts[str(self)] += 1
            return original(self, *args, **kwargs)

        refs.clear_caches()
        with mock.patch.object(Path, "read_text", counting_read_text):
            issues = refs.check_spec(self.spec, self.base)
        self.assertEqual(issues, [], "fixture should be clean: %r" % (issues,))
        return counts

    def test_no_file_is_read_from_disk_more_than_once(self):
        counts = self._run_counting_reads()
        repeats = {p: n for p, n in counts.items() if n > 1}
        self.assertEqual(
            repeats, {},
            "these files were re-read from disk; the per-path cache is not in effect: %r"
            % (repeats,))

    def test_the_referenced_test_files_are_read_exactly_once(self):
        counts = self._run_counting_reads()
        for name in ("demo.spec.js", "test_demo.py"):
            hits = [n for p, n in counts.items() if p.endswith(name)]
            self.assertEqual(hits, [1], "%s was not read exactly once: %r" % (name, hits))

    def test_every_caching_layer_processes_each_source_once(self):
        """Each layer must be pinned, not just the file read.

        Counting Path.read_text alone would still pass if the AST parse, the symbol walk, or the
        JS title scan stopped caching - and those were the dominant cost once reads were cached
        (1511 name lookups produced ~6M ast.walk steps). Entering an OUTER scope keeps the caches
        alive past check_spec's own scope so their hit/miss counters can be inspected.
        """
        parses = []
        real_parse = refs.ast.parse

        def counting_parse(*args, **kwargs):
            parses.append(kwargs.get("filename") or (args[1] if len(args) > 1 else "?"))
            return real_parse(*args, **kwargs)

        with mock.patch.object(refs.ast, "parse", counting_parse):
            with refs.cache_scope():
                self.assertEqual(refs.check_spec(self.spec, self.base), [])
                ast_info = refs._python_ast_fingerprinted.cache_info()
                sym_info = refs._python_symbols_fingerprinted.cache_info()
                js_info = refs._js_test_titles.cache_info()
                read_info = refs._read_fingerprinted.cache_info()

        # All 8 rows name the same two test files, so every layer must be re-used.
        self.assertEqual(len(parses), 1, "test_demo.py was parsed more than once: %r" % (parses,))
        self.assertEqual(ast_info.misses, 1, "the AST cache did not collapse to one parse")
        self.assertEqual(sym_info.misses, 1, "the symbol walk ran more than once per module")
        self.assertGreater(sym_info.hits, 0, "the symbol-walk cache was never re-used")
        self.assertGreater(js_info.hits, 0, "the JS title cache was never re-used")
        self.assertGreater(read_info.hits, 0, "the read cache was never re-used")
        # One scan per (source, pattern) pair, not per referencing row.
        self.assertLessEqual(js_info.misses, 2,
                             "demo.spec.js was scanned once per row: %r" % (js_info,))

    def test_a_changed_file_is_picked_up_without_any_cache_clearing(self):
        # Correctness must not depend on a caller remembering to clear. Caches are scoped to one
        # top-level check, so a rewrite between checks is always seen.
        spec = self.sandbox / "SPEC2.md"
        spec.write_text(
            "# Spec\n\n| Feature id | Behavior | Covering tests |\n| --- | --- | --- |\n"
            "| DEMO-01 | B. | `tests/test_demo.py` - `DemoTests.test_case_01` |\n",
            encoding="utf-8", newline="\n",
        )
        self.assertEqual(refs.check_spec(spec, self.base), [])

        (self.base / "tests" / "test_demo.py").write_text(
            "import unittest\n\nclass DemoTests(unittest.TestCase):\n"
            "    def test_renamed(self):\n        pass\n",
            encoding="utf-8", newline="\n",
        )
        issues = refs.check_spec(spec, self.base)
        self.assertTrue(issues, "the rewritten file was served from a previous run's cache")

    def test_a_same_length_rewrite_with_a_restored_mtime_is_still_detected(self):
        """The (mtime_ns, size) fingerprint alone is a HEURISTIC, so it must not be load-bearing.

        A rewrite that keeps the byte length and restores the original mtime is indistinguishable
        from no change. If the caches survived between checks, the renamed method would still be
        served from cache and a spec row whose test no longer exists would PASS - a false green on
        a required gate. Run-scoped caching is what makes this safe, so pin it directly.
        """
        target = self.base / "tests" / "test_demo.py"
        original = target.read_text(encoding="utf-8")
        before = target.stat()

        spec = self.sandbox / "SPEC3.md"
        spec.write_text(
            "# Spec\n\n| Feature id | Behavior | Covering tests |\n| --- | --- | --- |\n"
            "| DEMO-01 | B. | `tests/test_demo.py` - `DemoTests.test_case_01` |\n",
            encoding="utf-8", newline="\n",
        )
        self.assertEqual(refs.check_spec(spec, self.base), [])

        # Same byte length: rename test_case_01 -> test_case_9X (equal length, still 8 methods).
        rewritten = original.replace("def test_case_01(", "def test_case_99(")
        self.assertEqual(len(rewritten), len(original), "fixture rewrite must keep the size equal")
        target.write_text(rewritten, encoding="utf-8", newline="\n")
        os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns))
        self.assertEqual(target.stat().st_size, before.st_size)
        self.assertEqual(target.stat().st_mtime_ns, before.st_mtime_ns)

        issues = refs.check_spec(spec, self.base)
        self.assertTrue(
            issues,
            "a same-size, same-mtime rewrite was served from cache: the renamed method went "
            "undetected, so a stale spec row would pass the gate")

    def test_clear_caches_forces_a_cold_read(self):
        refs.check_spec(self.spec, self.base)
        counts = self._run_counting_reads()  # clears first, so every file is read once
        self.assertTrue(counts, "clear_caches did not force any file to be re-read")


class ScopeResetTests(unittest.TestCase):
    """Repeat runs agree, and each starts from a cold scope.

    Deliberately uses the sandbox rather than the real tree: `check_all()` on the repo is the very
    cost this change exists to cut, and `test_real_specs_have_current_test_references` already
    asserts the real specs are clean. Re-running it here would just re-pay that cost twice on every
    push for a duplicate assertion.
    """

    def setUp(self):
        self.sandbox = Path(tempfile.mkdtemp(prefix="spec-refs-scope-"))
        self.addCleanup(shutil.rmtree, self.sandbox, ignore_errors=True)
        self.base = self.sandbox / "base"
        (self.base / "tests").mkdir(parents=True)
        (self.base / "tests" / "test_demo.py").write_text(
            "import unittest\n\nclass DemoTests(unittest.TestCase):\n"
            "    def test_case_01(self):\n        pass\n",
            encoding="utf-8", newline="\n",
        )
        self.spec = self.sandbox / "SPEC.md"
        self.spec.write_text(
            "# Spec\n\n| Feature id | Behavior | Covering tests |\n| --- | --- | --- |\n"
            "| DEMO-01 | B. | `tests/test_demo.py` - `DemoTests.test_case_01` |\n",
            encoding="utf-8", newline="\n",
        )

    def test_repeated_runs_agree(self):
        first = refs.check_spec(self.spec, self.base)
        second = refs.check_spec(self.spec, self.base)
        self.assertEqual(first, [])
        self.assertEqual(first, second, "a repeated run disagreed with the first")

    def test_every_cache_is_empty_after_a_top_level_check(self):
        refs.check_spec(self.spec, self.base)
        sizes = {
            "_read": refs._read_fingerprinted.cache_info().currsize,
            "_python_ast": refs._python_ast_fingerprinted.cache_info().currsize,
            "_python_symbols": refs._python_symbols_fingerprinted.cache_info().currsize,
            "_js_test_titles": refs._js_test_titles.cache_info().currsize,
        }
        self.assertEqual({k: v for k, v in sizes.items() if v}, {},
                         "caches outlived the scope, so a later run could be served stale entries")

    def test_the_scope_depth_unwinds_even_when_a_check_raises(self):
        # A stranded depth counter would pin the caches warm for the rest of the process and
        # silently reinstate the stale-hit false pass this scoping exists to prevent.
        with self.assertRaises(OSError):
            refs.check_spec(self.sandbox / "does-not-exist.md", self.base)
        self.assertEqual(refs._cache_depth, 0, "cache scope depth leaked after an exception")


class SpecTestReferenceTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent.parent
        self.sandbox = self.root / "tmp" / "test_check_spec_test_refs"
        shutil.rmtree(self.sandbox, ignore_errors=True)
        self.base = self.sandbox / "base"
        self.base.mkdir(parents=True)
        (self.base / "tests").mkdir()
        (self.base / "tests" / "demo.spec.js").write_text(
            "test('real browser title (DEMO-01)', async () => {});\n"
            "test(`generated ${label} browser title (DEMO-02)`, async () => {});\n"
            "test(\"title with \\\"quoted\\\" text (DEMO-03)\", async () => {});\n",
            encoding="utf-8",
            newline="\n",
        )
        (self.base / "tests" / "test_demo.py").write_text(
            "import unittest\n\n"
            "class DemoTests(unittest.TestCase):\n"
            "    def test_real_case(self):\n"
            "        pass\n",
            encoding="utf-8",
            newline="\n",
        )

    def tearDown(self):
        shutil.rmtree(self.sandbox, ignore_errors=True)

    def _spec(self, coverage):
        spec = self.sandbox / "SPEC.md"
        spec.write_text(
            "# Spec\n\n"
            "| Feature id | Behavior | Covering tests |\n"
            "| --- | --- | --- |\n"
            "| DEMO-01 | Demo behavior. | %s |\n" % coverage,
            encoding="utf-8",
            newline="\n",
        )
        return spec

    def test_accepts_existing_js_title_and_python_class_method_refs(self):
        spec = self._spec(
            "`tests/demo.spec.js` - `real browser title (DEMO-01)`; "
            "`tests/test_demo.py` - `DemoTests`, `DemoTests.test_real_case`"
        )

        self.assertEqual(refs.check_spec(spec, self.base), [])

    def test_reports_missing_test_file(self):
        spec = self._spec("`tests/missing.spec.js` - `real browser title (DEMO-01)`")

        issues = refs.check_spec(spec, self.base)

        self.assertEqual(len(issues), 1)
        self.assertIn("missing test file `tests/missing.spec.js`", issues[0].message)

    def test_reports_unsupported_test_file_reference(self):
        spec = self._spec("`test/demo.spec.js` - `real browser title (DEMO-01)`")

        issues = refs.check_spec(spec, self.base)

        self.assertEqual(len(issues), 1)
        self.assertIn("unsupported test file reference `test/demo.spec.js`", issues[0].message)

    def test_reports_mismatched_test_title(self):
        spec = self._spec("`tests/demo.spec.js` - `stale browser title (DEMO-01)`")

        issues = refs.check_spec(spec, self.base)

        self.assertEqual(len(issues), 1)
        self.assertIn("`stale browser title (DEMO-01)` not found", issues[0].message)

    def test_rejects_prefix_of_existing_js_title(self):
        spec = self._spec("`tests/demo.spec.js` - `real browser title`")

        issues = refs.check_spec(spec, self.base)

        self.assertEqual(len(issues), 1)
        self.assertIn("`real browser title` not found", issues[0].message)

    def test_rejects_prefix_of_existing_python_method(self):
        (self.base / "tests" / "test_demo.py").write_text(
            "import unittest\n\n"
            "class DemoTests(unittest.TestCase):\n"
            "    def test_real_case_extra(self):\n"
            "        pass\n",
            encoding="utf-8",
            newline="\n",
        )
        spec = self._spec("`tests/test_demo.py` - `test_real_case`")

        issues = refs.check_spec(spec, self.base)

        self.assertEqual(len(issues), 1)
        self.assertIn("`test_real_case` not found", issues[0].message)

    def test_rejects_commented_out_js_title(self):
        (self.base / "tests" / "commented.spec.js").write_text(
            "// test('removed browser title (DEMO-99)', async () => {});\n",
            encoding="utf-8",
            newline="\n",
        )
        spec = self._spec("`tests/commented.spec.js` - `removed browser title (DEMO-99)`")

        issues = refs.check_spec(spec, self.base)

        self.assertEqual(len(issues), 1)
        self.assertIn("`removed browser title (DEMO-99)` not found", issues[0].message)

    def test_rejects_test_title_inside_multiline_template_literal(self):
        (self.base / "tests" / "template.spec.js").write_text(
            "const fixture = `\n"
            "test('template-only title (DEMO-97)', async () => {});\n"
            "`;\n",
            encoding="utf-8",
            newline="\n",
        )
        spec = self._spec("`tests/template.spec.js` - `template-only title (DEMO-97)`")

        issues = refs.check_spec(spec, self.base)

        self.assertEqual(len(issues), 1)
        self.assertIn("`template-only title (DEMO-97)` not found", issues[0].message)

    def test_rejects_non_test_js_test_method_call(self):
        (self.base / "tests" / "method.spec.js").write_text(
            "const ok = /DEMO/.test('DEMO-01');\n"
            "await test.step('step title (DEMO-02)', async () => {});\n"
            "const fixture = 'test(\"string title (DEMO-03)\", async () => {})';\n",
            encoding="utf-8",
            newline="\n",
        )
        spec = self._spec(
            "`tests/method.spec.js` - `DEMO-01`, `step title (DEMO-02)`, "
            "`string title (DEMO-03)`"
        )

        issues = refs.check_spec(spec, self.base)

        self.assertEqual(len(issues), 3)

    def test_regex_literals_do_not_break_commented_test_filtering(self):
        (self.base / "tests" / "regex-comment.spec.js").write_text(
            "const q = /[\"']/;\n"
            "function f() { return /[\"']/; }\n"
            "// test('ghost browser title (DEMO-98)', async () => {});\n",
            encoding="utf-8",
            newline="\n",
        )
        spec = self._spec("`tests/regex-comment.spec.js` - `ghost browser title (DEMO-98)`")

        issues = refs.check_spec(spec, self.base)

        self.assertEqual(len(issues), 1)
        self.assertIn("`ghost browser title (DEMO-98)` not found", issues[0].message)

    def test_accepts_dynamic_js_templates_and_escaped_quotes(self):
        spec = self._spec(
            "`tests/demo.spec.js` - `generated ${label} browser title (DEMO-02)`, "
            "`title with \"quoted\" text (DEMO-03)`"
        )

        self.assertEqual(refs.check_spec(spec, self.base), [])

    def test_accepts_js_titles_with_punctuation(self):
        (self.base / "tests" / "punctuation.spec.js").write_text(
            "test('a <body class> title uses key=value (DEMO-06)', async () => {});\n",
            encoding="utf-8",
            newline="\n",
        )
        spec = self._spec(
            "`tests/punctuation.spec.js` - `a <body class> title uses key=value (DEMO-06)`"
        )

        self.assertEqual(refs.check_spec(spec, self.base), [])

    def test_accepts_common_js_test_modifiers(self):
        (self.base / "tests" / "modifiers.spec.js").write_text(
            "test.only('only title (DEMO-07)', async () => {});\n"
            "it.skip('skip title (DEMO-08)', async () => {});\n"
            "test.describe.parallel('parallel group (DEMO-09)', () => {});\n",
            encoding="utf-8",
            newline="\n",
        )
        spec = self._spec(
            "`tests/modifiers.spec.js` - `only title (DEMO-07)`, "
            "`skip title (DEMO-08)`, `parallel group (DEMO-09)`"
        )

        self.assertEqual(refs.check_spec(spec, self.base), [])

    def test_semicolon_inside_test_title_does_not_truncate_clause(self):
        (self.base / "tests" / "semicolon.spec.js").write_text(
            "test('title; with semicolon (DEMO-04)', async () => {});\n"
            "test('after semicolon title (DEMO-05)', async () => {});\n",
            encoding="utf-8",
            newline="\n",
        )
        spec = self._spec(
            "`tests/semicolon.spec.js` - `title; with semicolon (DEMO-04)`, "
            "`after semicolon title (DEMO-05)`"
        )

        self.assertEqual(refs.check_spec(spec, self.base), [])

    def test_bare_feature_id_alone_does_not_satisfy_strict(self):
        # A bare feature id is a valid reference (existence is still checked), but per issue #629 it
        # is NOT an exact test title/method, so a clause citing only one is flagged.
        spec = self._spec("`tests/demo.spec.js` - `DEMO-01`")

        issues = refs.check_spec(spec, self.base)

        self.assertEqual(len(issues), 1)
        self.assertIn("no exact test name cited", issues[0].message)

    def test_feature_id_alongside_an_exact_title_is_accepted_and_validated(self):
        # The exact title satisfies the strict rule; the feature id is still validated to exist.
        spec = self._spec("`tests/demo.spec.js` - `real browser title (DEMO-01)`, `DEMO-03`")

        self.assertEqual(refs.check_spec(spec, self.base), [])

    def test_describe_suite_title_alone_does_not_satisfy_strict(self):
        (self.base / "tests" / "suite.spec.js").write_text(
            "describe('a suite group (DEMO-20)', () => {\n"
            "  test('a real test in the suite (DEMO-21)', async () => {});\n"
            "});\n",
            encoding="utf-8",
            newline="\n",
        )
        spec = self._spec("`tests/suite.spec.js` - `a suite group (DEMO-20)`")

        issues = refs.check_spec(spec, self.base)

        self.assertEqual(len(issues), 1)
        self.assertIn("no exact test name cited", issues[0].message)

    def test_non_test_python_helper_alone_does_not_satisfy_strict(self):
        (self.base / "tests" / "test_helpers.py").write_text(
            "def main():\n"
            "    pass\n\n"
            "class HelperTests:\n"
            "    def setUp(self):\n"
            "        pass\n"
            "    def test_real(self):\n"
            "        pass\n",
            encoding="utf-8",
            newline="\n",
        )
        # `main` (module helper) and `HelperTests.setUp` (non-test method) are not exact tests.
        for citation in ("`main`", "`HelperTests.setUp`"):
            spec = self._spec("`tests/test_helpers.py` - %s" % citation)
            issues = refs.check_spec(spec, self.base)
            self.assertEqual(len(issues), 1, citation)
            self.assertIn("no exact test name cited", issues[0].message)
        # A real test method or the test-case class does satisfy it.
        for citation in ("`HelperTests.test_real`", "`HelperTests`"):
            spec = self._spec("`tests/test_helpers.py` - %s" % citation)
            self.assertEqual(refs.check_spec(spec, self.base), [], citation)

    def test_non_test_helper_class_alone_does_not_satisfy_strict(self):
        (self.base / "tests" / "test_fixtures.py").write_text(
            "class Fixtures:\n"
            "    def build(self):\n"
            "        pass\n",
            encoding="utf-8",
            newline="\n",
        )
        # `Fixtures` is not a TestCase and is not named like a test case, so it is not an exact test.
        spec = self._spec("`tests/test_fixtures.py` - `Fixtures`")

        issues = refs.check_spec(spec, self.base)

        self.assertEqual(len(issues), 1)
        self.assertIn("no exact test name cited", issues[0].message)

    def test_rejects_partial_feature_id_reference(self):
        spec = self._spec("`tests/demo.spec.js` - `DEMO-0`")

        issues = refs.check_spec(spec, self.base)

        self.assertEqual(len(issues), 1)
        self.assertIn("`DEMO-0` not found", issues[0].message)

    def test_accepts_camel_case_python_class_reference(self):
        (self.base / "tests" / "test_demo.py").write_text(
            "import unittest\n\n"
            "class DemoCoverageRule(unittest.TestCase):\n"
            "    def test_real_case(self):\n"
            "        pass\n",
            encoding="utf-8",
            newline="\n",
        )
        spec = self._spec("`tests/test_demo.py` - `DemoCoverageRule`")

        self.assertEqual(refs.check_spec(spec, self.base), [])

    def test_reports_orphan_feature_id_in_regression_title(self):
        regression = self.base / "tests" / "deck-regressions.spec.js"
        regression.write_text(
            "test('ORPHAN-99: unmapped regression', async () => {});\n",
            encoding="utf-8",
            newline="\n",
        )
        spec = self._spec("`tests/demo.spec.js` - `real browser title (DEMO-01)`")

        issues = refs.check_test_id_mappings(spec, self.base, (regression,))

        self.assertEqual(len(issues), 1)
        self.assertIn("feature id `ORPHAN-99` has no spec row", issues[0].message)

    def test_reports_regression_title_mapped_to_wrong_spec_behavior(self):
        regression = self.base / "tests" / "deck-regressions.spec.js"
        regression.write_text(
            "test('DEMO-01: unrelated regression', async () => {});\n",
            encoding="utf-8",
            newline="\n",
        )
        spec = self._spec("`tests/demo.spec.js` - `real browser title (DEMO-01)`")

        issues = refs.check_test_id_mappings(spec, self.base, (regression,))

        self.assertEqual(len(issues), 1)
        self.assertIn("is not cited by its `DEMO-01` spec row", issues[0].message)

    def test_accepts_regression_title_cited_by_matching_spec_row(self):
        regression = self.base / "tests" / "deck-regressions.spec.js"
        title = "DEMO-01: mapped regression"
        regression.write_text(
            "test('%s', async () => {});\n" % title,
            encoding="utf-8",
            newline="\n",
        )
        spec = self._spec("`tests/deck-regressions.spec.js` - `%s`" % title)

        self.assertEqual(
            refs.check_test_id_mappings(spec, self.base, (regression,)),
            [],
        )

    def test_check_all_discovers_regression_id_mappings(self):
        regression = self.base / "tests" / "deck-regressions.spec.js"
        regression.write_text(
            "test('ORPHAN-99: unmapped regression', async () => {});\n",
            encoding="utf-8",
            newline="\n",
        )
        spec = self._spec("`tests/demo.spec.js` - `real browser title (DEMO-01)`")

        issues = refs.check_all(((spec, self.base),))

        self.assertEqual(len(issues), 1)
        self.assertIn("feature id `ORPHAN-99` has no spec row", issues[0].message)

    def test_flags_automated_clause_missing_cited_name(self):
        spec = self._spec("`tests/demo.spec.js` - element-boundary noise test")

        issues = refs.check_spec(spec, self.base)

        self.assertEqual(len(issues), 1)
        self.assertIn("no exact test name cited", issues[0].message)
        self.assertIn("`tests/demo.spec.js`", issues[0].message)

    def test_accepts_automated_clause_with_prose_and_a_cited_name(self):
        spec = self._spec("`tests/demo.spec.js` - noise handling, `real browser title (DEMO-01)`")

        self.assertEqual(refs.check_spec(spec, self.base), [])

    def test_missing_name_flag_is_per_reference_in_a_multi_ref_cell(self):
        spec = self._spec(
            "`tests/demo.spec.js` - `real browser title (DEMO-01)`; "
            "`tests/test_demo.py` - only prose here"
        )

        issues = refs.check_spec(spec, self.base)

        self.assertEqual(len(issues), 1)
        self.assertIn("no exact test name cited", issues[0].message)
        self.assertIn("`tests/test_demo.py`", issues[0].message)

    def test_accepts_single_token_exact_js_title(self):
        (self.base / "tests" / "smoke.spec.js").write_text(
            "test('smoke', async () => {});\n",
            encoding="utf-8",
            newline="\n",
        )
        spec = self._spec("`tests/smoke.spec.js` - `smoke`")

        self.assertEqual(refs.check_spec(spec, self.base), [])

    def test_flags_single_token_that_is_not_a_real_title(self):
        spec = self._spec("`tests/demo.spec.js` - `nope`")

        issues = refs.check_spec(spec, self.base)

        self.assertEqual(len(issues), 1)
        self.assertIn("no exact test name cited", issues[0].message)

    def test_ignores_quoted_code_notes_after_test_references(self):
        spec = self._spec(
            "`tests/demo.spec.js` - `real browser title (DEMO-01)` "
            "(end-to-end via `main([\"--check\"])`, `--check`, and `#commentRoot`)"
        )

        self.assertEqual(refs.check_spec(spec, self.base), [])

    def test_real_specs_have_current_test_references(self):
        issues = refs.check_all()
        self.assertEqual([], [issue.format() for issue in issues])


if __name__ == "__main__":
    unittest.main()
