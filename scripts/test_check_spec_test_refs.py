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
        # A PRIVATE temp directory, never a fixed path inside the repository: this used to be
        # `<repo>/tmp/test_check_spec_test_refs`, which two runners (or two workers of
        # `run_script_tests.py --jobs`) share - one test's setUp then deletes the tree another
        # test is still using, and the suite fails on a race rather than on a defect.
        self.sandbox = Path(tempfile.mkdtemp(prefix="spec-refs-"))
        self.addCleanup(shutil.rmtree, self.sandbox, ignore_errors=True)
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

    def _spec(self, coverage):
        return self._spec_rows((("DEMO-01", coverage),))

    def _spec_rows(self, rows):
        spec = self.sandbox / "SPEC.md"
        spec.write_text(
            "# Spec\n\n"
            "| Feature id | Behavior | Covering tests |\n"
            "| --- | --- | --- |\n"
            + "".join(
                "| %s | Demo behavior. | %s |\n" % (feature_id, coverage)
                for feature_id, coverage in rows
            ),
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

        self.assertEqual(
            ["feature id `ORPHAN-99` has no spec row"],
            [issue.message for issue in issues if "ORPHAN-99" in issue.message],
        )

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

    def test_reverse_map_covers_test_mjs_suites(self):
        (self.base / "tests" / "trim.test.mjs").write_text(
            "test('an unmapped mjs behavior (ORPHAN-77)', () => {});\n",
            encoding="utf-8",
            newline="\n",
        )
        spec = self._spec("`tests/demo.spec.js` - `real browser title (DEMO-01)`")

        issues = refs.check_all(((spec, self.base),))

        # The COMPLETE list, so a spurious or duplicated report from `check_all`'s two-half split
        # is caught too. DEMO-02/DEMO-03 come from setUp's demo.spec.js, which the ownership half
        # now reads because it is an ordinary `*.spec.js`.
        self.assertEqual(
            [
                "feature id `ORPHAN-77` has no spec row",
                "feature id `DEMO-02` has no spec row",
                "feature id `DEMO-03` has no spec row",
            ],
            [issue.message for issue in issues],
        )

    def test_reverse_map_checks_a_suite_title_id_for_ownership_only(self):
        # A row cannot CITE a suite title (issue #629), so no citation is demanded for one - but
        # an id no row owns, parked in a suite title, is a satisfiable demand and must be caught.
        regression = self.base / "tests" / "suite-regressions.spec.js"
        regression.write_text(
            "describe('a suite group (ORPHAN-88)', () => {\n"
            "  test('DEMO-01: a mapped regression', async () => {});\n"
            "});\n",
            encoding="utf-8",
            newline="\n",
        )
        owned = self._spec_rows((
            ("DEMO-01", "`tests/suite-regressions.spec.js` - `DEMO-01: a mapped regression`"),
            ("ORPHAN-88", "`tests/suite-regressions.spec.js` - `DEMO-01: a mapped regression`"),
        ))

        self.assertEqual(refs.check_test_id_mappings(owned, self.base, (regression,)), [])

        unowned = self._spec_rows((
            ("DEMO-01", "`tests/suite-regressions.spec.js` - `DEMO-01: a mapped regression`"),
        ))
        issues = refs.check_test_id_mappings(unowned, self.base, (regression,))

        self.assertEqual(len(issues), 1)
        self.assertIn("feature id `ORPHAN-88` has no spec row", issues[0].message)
        self.assertIn("a suite title cannot be cited", issues[0].message)

    def test_reverse_map_reads_a_test_fail_declaration(self):
        # `test.fail(title, body)` is a real Playwright declaration, so a feature id parked in one
        # must not be invisible to the reverse map.
        (self.base / "tests" / "failing.test.js").write_text(
            "test.fail('an expected-failure behavior (ORPHAN-44)', async () => {});\n",
            encoding="utf-8",
            newline="\n",
        )
        spec = self._spec("`tests/demo.spec.js` - `real browser title (DEMO-01)`")

        issues = refs.check_all(((spec, self.base),))

        self.assertEqual(
            ["feature id `ORPHAN-44` has no spec row"],
            [issue.message for issue in issues if "ORPHAN-44" in issue.message],
        )

    def test_a_test_fail_title_can_be_cited_by_a_spec_row(self):
        # The forward half of the same grammar: a row citing a `test.fail(...)` title must be
        # accepted as an exact test reference, not rejected as prose.
        (self.base / "tests" / "failing.spec.js").write_text(
            "test.fail('a known-failing behavior (DEMO-45)', async () => {});\n",
            encoding="utf-8",
            newline="\n",
        )
        spec = self._spec_rows((
            ("DEMO-01", "`tests/demo.spec.js` - `real browser title (DEMO-01)`"),
            ("DEMO-45", "`tests/failing.spec.js` - `a known-failing behavior (DEMO-45)`"),
        ))

        self.assertEqual(refs.check_spec(spec, self.base), [])

    def test_tests_dir_prefers_the_spec_directory_over_the_base(self):
        # The site target's base is the repo root, so a `<base>/tests` preference would let a
        # future repo-root `tests/` shadow `site/tests/tests` and silently stop checking it.
        nested = self.sandbox / "outer"
        (nested / "tests").mkdir(parents=True)
        spec = nested / "SPEC.md"
        spec.write_text("# Spec\n", encoding="utf-8", newline="\n")
        (self.sandbox / "tests").mkdir()

        self.assertEqual(refs._tests_dir(spec, self.sandbox), nested / "tests")
        # A spec that does not sit beside a tests dir still falls back to the base.
        bare = self.sandbox / "bare"
        bare.mkdir()
        self.assertEqual(refs._tests_dir(bare / "SPEC.md", self.base), self.base / "tests")

    def test_test_corpus_finds_nested_test_files(self):
        nested = self.base / "tests" / "sub"
        nested.mkdir()
        (nested / "deep.test.mjs").write_text(
            "test('a nested behavior (DEMO-31)', () => {});\n",
            encoding="utf-8",
            newline="\n",
        )
        spec = self._spec("`tests/demo.spec.js` - `real browser title (DEMO-01)`")

        corpus = refs._test_corpus(spec, self.base)

        self.assertIn(nested / "deep.test.mjs", corpus)
        self.assertTrue(refs._is_reverse_mapped((nested / "deep.test.mjs").name))

    def test_test_corpus_covers_every_playwright_test_extension(self):
        for name in ("extra.test.js", "extra.spec.ts", "extra.spec.cjs", "extra.test.mts"):
            (self.base / "tests" / name).write_text(
                "test('a behavior in %s (DEMO-32)', () => {});\n" % name,
                encoding="utf-8",
                newline="\n",
            )
        spec = self._spec("`tests/demo.spec.js` - `real browser title (DEMO-01)`")

        corpus = {path.name for path in refs._test_corpus(spec, self.base)}

        self.assertLessEqual(
            {"extra.test.js", "extra.spec.ts", "extra.spec.cjs", "extra.test.mts"},
            corpus,
        )

    def test_test_corpus_skips_a_directory_that_matches_the_glob(self):
        (self.base / "tests" / "fixture.spec.js").mkdir()
        spec = self._spec("`tests/demo.spec.js` - `real browser title (DEMO-01)`")

        corpus = refs._test_corpus(spec, self.base)

        self.assertNotIn(self.base / "tests" / "fixture.spec.js", corpus)

    def test_row_cites_requires_the_title_in_its_own_file_clause(self):
        # A cell listing two files must not let the first file claim the second's title.
        coverage = ["`tests/a.spec.js` - `A title (DEMO-01)`; "
                    "`tests/b.spec.js` - `B title (DEMO-01)`"]

        self.assertTrue(refs._row_cites(coverage, "tests/a.spec.js", "A title (DEMO-01)"))
        self.assertTrue(refs._row_cites(coverage, "tests/b.spec.js", "B title (DEMO-01)"))
        self.assertFalse(refs._row_cites(coverage, "tests/a.spec.js", "B title (DEMO-01)"))

    def test_duplicate_check_is_not_satisfied_by_another_files_citation(self):
        (self.base / "tests" / "other.spec.js").write_text(
            "test('a borrowed behavior (DEMO-01)', async () => {});\n",
            encoding="utf-8",
            newline="\n",
        )
        # The row names other.spec.js, but only for a title that file does not contain, so the
        # borrowed test is NOT cited even though both strings appear in the cell.
        spec = self._spec(
            "`tests/demo.spec.js` - `real browser title (DEMO-01)`, `a borrowed behavior "
            "(DEMO-01)`; `tests/other.spec.js` - `something else entirely (DEMO-01)`"
        )

        issues = refs.check_duplicate_feature_ids(((spec, self.base),))

        self.assertEqual(len(issues), 1)
        self.assertIn("a borrowed behavior (DEMO-01)", issues[0].message)

    def test_duplicate_check_skips_an_id_no_spec_row_owns(self):
        # `HTTP-404` matches the feature-id shape but is prose, so it must not red the gate.
        for name in ("first.spec.js", "second.spec.js"):
            (self.base / "tests" / name).write_text(
                "test('a request that answers HTTP-404 in %s', async () => {});\n" % name,
                encoding="utf-8",
                newline="\n",
            )
        spec = self._spec("`tests/demo.spec.js` - `real browser title (DEMO-01)`")

        self.assertEqual(refs.check_duplicate_feature_ids(((spec, self.base),)), [])

    def test_duplicate_check_uses_resolved_paths_as_file_identity(self):
        # Two targets can each hold a `tests/shared.test.mjs`; collapsing them by their
        # spec-relative spelling would hide the reuse.
        other_base = self.sandbox / "other"
        (other_base / "tests").mkdir(parents=True)
        (other_base / "tests" / "shared.test.mjs").write_text(
            "test('the borrowing behavior (DEMO-55)', () => {});\n",
            encoding="utf-8",
            newline="\n",
        )
        (self.base / "tests" / "shared.test.mjs").write_text(
            "test('the owning behavior (DEMO-55)', () => {});\n",
            encoding="utf-8",
            newline="\n",
        )
        spec = self._spec_rows((
            ("DEMO-01", "`tests/demo.spec.js` - `real browser title (DEMO-01)`"),
            ("DEMO-55", "`tests/shared.test.mjs` - `the owning behavior (DEMO-55)`"),
        ))
        other_spec = other_base / "SPEC.md"
        other_spec.write_text("# Spec\n", encoding="utf-8", newline="\n")

        issues = refs.check_duplicate_feature_ids(((spec, self.base), (other_spec, other_base)))

        self.assertEqual(len(issues), 1)
        self.assertIn("the borrowing behavior (DEMO-55)", issues[0].message)

    def test_duplicate_check_does_not_let_another_spec_excuse_a_use(self):
        other_base = self.sandbox / "other"
        (other_base / "tests").mkdir(parents=True)
        (other_base / "tests" / "borrow.spec.js").write_text(
            "test('the borrowing behavior (DEMO-01)', async () => {});\n",
            encoding="utf-8",
            newline="\n",
        )
        spec = self._spec("`tests/demo.spec.js` - `real browser title (DEMO-01)`")
        other_spec = other_base / "SPEC.md"
        other_spec.write_text("# Spec\n", encoding="utf-8", newline="\n")

        issues = refs.check_duplicate_feature_ids(((spec, self.base), (other_spec, other_base)))

        self.assertEqual(len(issues), 1)
        self.assertIn("the borrowing behavior (DEMO-01)", issues[0].message)

    def test_a_cross_file_use_also_demands_citations_for_the_same_file_pair(self):
        (self.base / "tests" / "pair.spec.js").write_text(
            "test('the first assertion (DEMO-42)', async () => {});\n"
            "test('the second assertion (DEMO-42)', async () => {});\n",
            encoding="utf-8",
            newline="\n",
        )
        (self.base / "tests" / "elsewhere.spec.js").write_text(
            "test('a third file also uses it (DEMO-42)', async () => {});\n",
            encoding="utf-8",
            newline="\n",
        )
        spec = self._spec_rows((
            ("DEMO-01", "`tests/demo.spec.js` - `real browser title (DEMO-01)`"),
            ("DEMO-42", "`tests/pair.spec.js` - `the first assertion (DEMO-42)`"),
        ))

        issues = refs.check_duplicate_feature_ids(((spec, self.base),))

        self.assertEqual(len(issues), 2)
        self.assertEqual(
            sorted(
                title
                for title in ("the second assertion (DEMO-42)",
                              "a third file also uses it (DEMO-42)")
                if any(title in issue.message for issue in issues)
            ),
            ["a third file also uses it (DEMO-42)", "the second assertion (DEMO-42)"],
        )

    def test_reports_feature_id_reused_by_a_test_in_another_file(self):
        (self.base / "tests" / "other.spec.js").write_text(
            "test('a different behavior that borrows the id (DEMO-01)', async () => {});\n",
            encoding="utf-8",
            newline="\n",
        )
        spec = self._spec("`tests/demo.spec.js` - `real browser title (DEMO-01)`")

        issues = refs.check_duplicate_feature_ids(((spec, self.base),))

        self.assertEqual(len(issues), 1)
        self.assertIn("feature id `DEMO-01` is also used by test", issues[0].message)
        self.assertIn("a different behavior that borrows the id (DEMO-01)", issues[0].message)

    def test_accepts_a_feature_id_whose_spec_row_cites_every_test_that_carries_it(self):
        (self.base / "tests" / "other.spec.js").write_text(
            "test('the same behavior asserted end to end (DEMO-01)', async () => {});\n",
            encoding="utf-8",
            newline="\n",
        )
        spec = self._spec(
            "`tests/demo.spec.js` - `real browser title (DEMO-01)`; "
            "`tests/other.spec.js` - `the same behavior asserted end to end (DEMO-01)`"
        )

        self.assertEqual(refs.check_duplicate_feature_ids(((spec, self.base),)), [])

    def test_allows_two_tests_in_one_file_to_share_a_feature_id(self):
        (self.base / "tests" / "pair.spec.js").write_text(
            "test('the first assertion (DEMO-42)', async () => {});\n"
            "test('the second assertion (DEMO-42)', async () => {});\n",
            encoding="utf-8",
            newline="\n",
        )
        spec = self._spec_rows((
            ("DEMO-01", "`tests/demo.spec.js` - `real browser title (DEMO-01)`"),
            ("DEMO-42", "`tests/pair.spec.js` - `the first assertion (DEMO-42)`"),
        ))

        self.assertEqual(refs.check_duplicate_feature_ids(((spec, self.base),)), [])

    def test_duplicate_check_does_not_report_a_describe_suite_title(self):
        # A describe title cannot be cited by a row (issue #629), so it is never REPORTED - but it
        # does still count toward "how many files carry this id" (see the test below).
        (self.base / "tests" / "other.spec.js").write_text(
            "describe('a suite that mentions the id (DEMO-01)', () => {\n"
            "  test('an unrelated assertion', async () => {});\n"
            "});\n",
            encoding="utf-8",
            newline="\n",
        )
        spec = self._spec("`tests/demo.spec.js` - `real browser title (DEMO-01)`")

        self.assertEqual(refs.check_duplicate_feature_ids(((spec, self.base),)), [])

    def test_a_describe_title_still_makes_an_id_span_files(self):
        # Hiding the borrow in a suite title is the obvious evasion: the id now spans two files,
        # so the real test that carries it must be cited.
        (self.base / "tests" / "other.spec.js").write_text(
            "describe('a suite that borrows the id (DEMO-01)', () => {\n"
            "  test('an unrelated assertion', async () => {});\n"
            "});\n",
            encoding="utf-8",
            newline="\n",
        )
        spec = self._spec("`tests/demo.spec.js` - prose only, no cited title")

        issues = refs.check_duplicate_feature_ids(((spec, self.base),))

        self.assertEqual(
            ["real browser title (DEMO-01)"],
            [title for title in ("real browser title (DEMO-01)",)
             if any(title in issue.message for issue in issues)],
        )

    def test_row_cites_stops_at_a_source_trailer(self):
        coverage = ["`tests/a.spec.js` - `A title (DEMO-01)`; "
                    "source: `assets/js/x.js` - `borrowed title (DEMO-01)`"]

        self.assertTrue(refs._row_cites(coverage, "tests/a.spec.js", "A title (DEMO-01)"))
        self.assertFalse(refs._row_cites(coverage, "tests/a.spec.js", "borrowed title (DEMO-01)"))

    def test_a_typescript_test_file_can_be_cited_and_checked(self):
        (self.base / "tests" / "typed.spec.ts").write_text(
            "test('a typed behavior (DEMO-61)', async () => {});\n",
            encoding="utf-8",
            newline="\n",
        )
        spec = self._spec_rows((
            ("DEMO-01", "`tests/demo.spec.js` - `real browser title (DEMO-01)`"),
            ("DEMO-61", "`tests/typed.spec.ts` - `a typed behavior (DEMO-61)`"),
        ))

        self.assertEqual(refs.check_spec(spec, self.base), [])

    def test_duplicate_check_flags_a_new_id_in_a_known_area_without_a_row(self):
        # Most of the `*.spec.*` corpus is not reverse-mapped, so an id with no row yet must still
        # be caught when it spans files - that is the borrow this gate exists for.
        for name in ("first.spec.js", "second.spec.js"):
            (self.base / "tests" / name).write_text(
                "test('a behavior in %s (DEMO-88)', async () => {});\n" % name,
                encoding="utf-8",
                newline="\n",
            )
        spec = self._spec("`tests/demo.spec.js` - `real browser title (DEMO-01)`")

        issues = refs.check_duplicate_feature_ids(((spec, self.base),))

        self.assertEqual(len(issues), 2)
        self.assertIn("DEMO-88", issues[0].message)

    def test_duplicate_check_reads_the_owning_specs_rows_not_the_finding_specs(self):
        for name in ("first.spec.js", "second.spec.js"):
            (self.base / "tests" / name).write_text(
                "test('a behavior in %s (DEMO-91)', async () => {});\n" % name,
                encoding="utf-8",
                newline="\n",
            )
        empty_spec = self.sandbox / "EMPTY_SPEC.md"
        empty_spec.write_text("# Spec\n", encoding="utf-8", newline="\n")
        owning_spec = self._spec_rows((
            ("DEMO-01", "`tests/demo.spec.js` - `real browser title (DEMO-01)`"),
            ("DEMO-91",
             "`tests/first.spec.js` - `a behavior in first.spec.js (DEMO-91)`; "
             "`tests/second.spec.js` - `a behavior in second.spec.js (DEMO-91)`"),
        ))

        issues = refs.check_duplicate_feature_ids(
            ((empty_spec, self.base), (owning_spec, self.base)))

        self.assertEqual([], [issue.format() for issue in issues if "DEMO-91" in issue.message])

    def test_test_corpus_matches_test_file_names_case_insensitively(self):
        (self.base / "tests" / "Odd.Spec.JS").write_text(
            "test('an oddly cased behavior (DEMO-71)', async () => {});\n",
            encoding="utf-8",
            newline="\n",
        )
        spec = self._spec("`tests/demo.spec.js` - `real browser title (DEMO-01)`")

        corpus = {path.name for path in refs._test_corpus(spec, self.base)}

        self.assertIn("Odd.Spec.JS", corpus)

    def test_check_all_runs_the_duplicate_feature_id_check(self):
        (self.base / "tests" / "other.spec.js").write_text(
            "test('a different behavior that borrows the id (DEMO-01)', async () => {});\n",
            encoding="utf-8",
            newline="\n",
        )
        spec = self._spec("`tests/demo.spec.js` - `real browser title (DEMO-01)`")

        issues = refs.check_all(((spec, self.base),))

        self.assertEqual(
            1,
            len([issue for issue in issues if "is also used by test" in issue.message]),
        )

    def test_check_all_reverse_maps_the_whole_corpus_of_a_fully_mapped_spec(self):
        # A spec that has finished the cleanup gets its ORDINARY `*.spec.js` files reverse-mapped
        # for CITATIONS too, not just for ownership (which a restricted target already gets).
        (self.base / "tests" / "plain.spec.js").write_text(
            "test('an uncited behavior (DEMO-01)', async () => {});\n",
            encoding="utf-8",
            newline="\n",
        )
        spec = self._spec("`tests/demo.spec.js` - `real browser title (DEMO-01)`")

        restricted = refs.check_all(((spec, self.base),), frozenset())
        full = refs.check_all(((spec, self.base),), frozenset({spec.resolve()}))

        self.assertEqual(
            [], [i.message for i in restricted if "is not cited by its" in i.message])
        uncited = [i.message for i in full if "is not cited by its" in i.message]
        self.assertEqual(1, len(uncited))
        self.assertIn(
            "test title `an uncited behavior (DEMO-01)` is not cited by its `DEMO-01` spec row",
            uncited[0],
        )
        self.assertIn("covering-tests cell", uncited[0])

    def test_the_site_spec_is_fully_reverse_mapped(self):
        self.assertIn(
            (self.root / "site" / "tests" / "SPEC.md").resolve(),
            refs.FULLY_REVERSE_MAPPED_SPECS,
        )

    def test_every_spec_target_is_fully_reverse_mapped(self):
        # No shipped JS target is still restricted to the `*.test.*` / regressions subset, and a
        # target that genuinely must be restricted registers itself in
        # `INTENTIONALLY_RESTRICTED_SPECS`, so the exemption is a reviewed one-line edit rather
        # than a silent omission. One target is listed today: the flat Python `scripts/SPEC.md`,
        # whose `Class.method` test names cannot carry a hyphenated feature id, so it has no
        # reverse citation to graduate to.
        restricted = {spec.resolve() for spec, _base in refs.SPEC_TARGETS
                      if spec.resolve() not in refs.FULLY_REVERSE_MAPPED_SPECS}

        self.assertEqual(refs.INTENTIONALLY_RESTRICTED_SPECS, frozenset(restricted))

    def test_a_restricted_target_still_gets_the_ownership_half_of_the_reverse_map(self):
        # A target waiting to graduate must not be a hiding place: its plain `*.spec.js` files are
        # exempt from CITATIONS, never from OWNERSHIP.
        (self.base / "tests" / "plain.spec.js").write_text(
            "test('an unowned behavior (ORPHAN-66)', async () => {});\n"
            "test('an uncited but owned behavior (DEMO-01)', async () => {});\n",
            encoding="utf-8",
            newline="\n",
        )
        spec = self._spec("`tests/demo.spec.js` - `real browser title (DEMO-01)`")

        restricted = refs.check_all(((spec, self.base),), frozenset())

        self.assertIn(
            "feature id `ORPHAN-66` has no spec row",
            [issue.message for issue in restricted],
        )
        self.assertEqual(
            [],
            [issue.message for issue in restricted if "is not cited by its" in issue.message],
        )

    def test_the_commentable_html_corpus_reverse_maps_its_plain_spec_files(self):
        # The widening is only real if the corpus `check_all` reverse-maps for the
        # commentable-html target now includes its ORDINARY `*.spec.js` files, not just the
        # `*.test.*` / `*regressions*.spec.*` subset it was limited to.
        spec = (self.root / "plugins" / "commentable-html" / "dev" / "SPEC.md").resolve()
        base = spec.parent
        self.assertIn(spec, refs.FULLY_REVERSE_MAPPED_SPECS)
        # `check_all` sends a fully mapped target's WHOLE corpus through the citation half.
        corpus = refs._test_corpus(spec, base)
        plain = [path.name for path in corpus if not refs._is_reverse_mapped(path.name)]

        self.assertTrue(plain, "no plain .spec.js file is reverse-mapped for commentable-html")

    def test_a_fully_mapped_spec_reports_a_same_file_uncited_carrier_once(self):
        # An INVARIANT test, not a guard on the `FULLY_REVERSE_MAPPED_SPECS` membership change
        # (that is what the two tests above pin): it passes the mapping in explicitly. What it
        # pins is the answer to issue #853's third question - the duplicate direction still
        # relaxes the same-file case, and that is not a hole, because the REVERSE direction
        # demands the citation and the relaxation keeps the same miss from being reported twice.
        base = self.sandbox / "solo-base"
        (base / "tests").mkdir(parents=True)
        (base / "tests" / "solo.spec.js").write_text(
            "test('one angle (DEMO-01)', async () => {});\n"
            "test('another angle (DEMO-01)', async () => {});\n",
            encoding="utf-8",
            newline="\n",
        )
        spec = self.sandbox / "SOLO_SPEC.md"
        spec.write_text(
            "# Spec\n\n"
            "| Feature id | Behavior | Covering tests |\n"
            "| --- | --- | --- |\n"
            "| DEMO-01 | Demo behavior. | `tests/solo.spec.js` - `one angle (DEMO-01)` |\n",
            encoding="utf-8",
            newline="\n",
        )

        self.assertEqual([], refs.check_duplicate_feature_ids(((spec, base),)))
        issues = refs.check_all(((spec, base),), frozenset({spec.resolve()}))
        self.assertEqual(1, len(issues))
        self.assertIn(
            "test title `another angle (DEMO-01)` is not cited by its `DEMO-01` spec row",
            issues[0].message,
        )

    def test_a_target_with_no_tests_directory_fails_closed(self):
        # With no tests dir the reverse and duplicate directions are silent no-ops, so a mistyped
        # base would look like a permanently clean target.
        bare = self.sandbox / "bare"
        bare.mkdir()
        spec = bare / "SPEC.md"
        spec.write_text("# Spec\n", encoding="utf-8", newline="\n")

        issues = refs.check_all(((spec, bare),))

        self.assertEqual(1, len(issues))
        self.assertIn("no tests directory found for this target", issues[0].message)

    def test_real_specs_have_current_test_references(self):
        issues = refs.check_all()
        self.assertEqual([], [issue.format() for issue in issues])


class FlatPythonSuiteTests(unittest.TestCase):
    """A target whose tests are a FLAT `test_*.py` set beside the code, not a `tests/` directory.

    `scripts/SPEC.md` is that shape (issue #1002). Before it was taught, `_tests_dir` looked only
    at `<spec dir>/tests` and `<base>/tests`, so `check_all` failed closed with "no tests directory
    found" and the spec had to be held to a second, per-suite copy of the same check. Registering
    the shape is what lets the ONE registry gate it.
    """

    def setUp(self):
        self.root = Path(__file__).resolve().parent.parent
        self.sandbox = Path(tempfile.mkdtemp(prefix="flat-py-"))
        self.addCleanup(shutil.rmtree, self.sandbox, ignore_errors=True)
        # A real `test_*.py` beside the spec, so the registered directory holds a suite. The
        # CITATIONS point at the repository's own `scripts/` suites, which is the spelling a flat
        # target uses - `_resolve_test_path` resolves a `scripts/` path from the repo root.
        (self.sandbox / "test_sandbox_guard.py").write_text(
            "import unittest\n\n\nclass SandboxTests(unittest.TestCase):\n"
            "    def test_ok(self):\n        pass\n",
            encoding="utf-8",
            newline="\n",
        )

    def _spec(self, rows):
        return self._write_spec(self.sandbox / "SPEC.md", rows)

    def _spec_at(self, directory, feature_id):
        """A minimal, fully covered spec in *directory*, for a test about the DIRECTORY."""
        return self._write_spec(
            directory / "SPEC.md",
            ((feature_id,
              "`scripts/test_check_forbidden_files.py` - "
              "`IsForbiddenTest.test_allows_safe_files`"),),
        )

    def _write_spec(self, spec, rows):
        spec.write_text(
            "# Spec\n\n"
            "| Feature id | Behavior | Covering tests |\n"
            "| --- | --- | --- |\n"
            + "".join(
                "| %s | Demo behavior. | %s |\n" % (feature_id, coverage)
                for feature_id, coverage in rows
            ),
            encoding="utf-8",
            newline="\n",
        )
        return spec

    def _check_all(self, spec, flat=None):
        registered = frozenset({spec.resolve()}) if flat is None else flat
        with mock.patch.object(refs, "FLAT_PYTHON_SUITES", registered):
            return refs.check_all(((spec, self.root),), frozenset())

    def test_a_flat_python_suite_target_is_located_and_passes(self):
        spec = self._spec(((
            "GUARD-01",
            "`scripts/test_check_forbidden_files.py` - `IsForbiddenTest.test_allows_safe_files`",
        ),))

        self.assertEqual([issue.format() for issue in self._check_all(spec)], [])

    def test_a_missing_cited_file_fails(self):
        spec = self._spec((
            ("GUARD-01", "`scripts/test_not_a_real_suite.py` - `SandboxTests.test_ok`"),
        ))

        messages = [issue.message for issue in self._check_all(spec)]

        self.assertEqual(1, len(messages), messages)
        self.assertIn("missing test file `scripts/test_not_a_real_suite.py`", messages[0])

    def test_a_renamed_method_fails(self):
        spec = self._spec(((
            "GUARD-01",
            "`scripts/test_check_forbidden_files.py` - `IsForbiddenTest.test_renamed_away`",
        ),))

        messages = [issue.message for issue in self._check_all(spec)]

        self.assertEqual(1, len(messages), messages)
        self.assertIn(
            "`IsForbiddenTest.test_renamed_away` not found in "
            "`scripts/test_check_forbidden_files.py`",
            messages[0],
        )

    def test_a_duplicate_row_fails(self):
        cell = ("`scripts/test_check_forbidden_files.py` - "
                "`IsForbiddenTest.test_allows_safe_files`")
        spec = self._spec((("GUARD-01", cell), ("GUARD-01", cell)))

        messages = [issue.message for issue in self._check_all(spec)]

        self.assertEqual(1, len(messages), messages)
        self.assertIn("feature id `GUARD-01` is the id cell of 2 spec rows", messages[0])

    def test_a_registered_directory_with_no_python_suite_fails_closed(self):
        bare = self.sandbox / "bare"
        bare.mkdir()
        spec = self._spec_at(bare, "GUARD-01")

        messages = [issue.message for issue in self._check_all(spec)]

        self.assertEqual(1, len(messages), messages)
        self.assertIn("no tests directory found for this target", messages[0])
        self.assertIn("test_*.py", messages[0])

    def test_the_corpus_is_the_flat_python_suite(self):
        spec = (self.root / "scripts" / "SPEC.md").resolve()

        corpus = {path.name for path in refs._test_corpus(spec, self.root)}

        self.assertIn("test_check_forbidden_files.py", corpus)
        self.assertIn("test_check_workflow_policy.py", corpus)
        self.assertNotIn("check_forbidden_files.py", corpus)

    def test_the_js_grammar_directions_skip_a_python_file(self):
        # A flat Python corpus is FULL of feature-id-shaped fixture strings (`CMH-FOO-01`,
        # `DEMO-01`, `ORPHAN-99`, `HTTP-404`) written for the checkers' own unit tests. Reading a
        # `.py` file with the JS title grammar would turn every one of them into a bogus
        # "has no spec row", so the reverse and duplicate directions read JS/TS files only.
        carrier = self.sandbox / "test_carrier.py"
        carrier.write_text(
            "FIXTURE = '''\n"
            "test('a borrowed behavior (ORPHAN-99)', async () => {});\n"
            "'''\n",
            encoding="utf-8",
            newline="\n",
        )
        spec = self._spec((("GUARD-01", "prose only"),))

        self.assertEqual([], refs.check_test_id_mappings(spec, self.root, (carrier,)))
        with mock.patch.object(refs, "FLAT_PYTHON_SUITES", frozenset({spec.resolve()})):
            self.assertEqual([], refs.check_duplicate_feature_ids(((spec, self.root),)))

    def test_a_bare_file_citation_with_no_test_names_fails(self):
        # The gap the per-suite checks this registry replaced used to cover: a row that points at a
        # real suite but names nothing in it. A JS target is caught from the other side (the
        # reverse direction demands the citation), but a flat Python target has no other side.
        spec = self._spec((("GUARD-01", "`scripts/test_check_forbidden_files.py`"),))

        messages = [issue.message for issue in self._check_all(spec)]

        self.assertEqual(1, len(messages), messages)
        self.assertIn("is cited with no ` - ` clause naming a test", messages[0])

    def test_a_bare_file_citation_is_still_allowed_for_a_js_target(self):
        # The same shape is legitimate in a JS spec, which records partial or manual coverage that
        # way ("partial - `tests/16-formatting.spec.js` verifies ..."), so the new demand must not
        # leak outside the flat Python shape.
        base = self.sandbox / "js-base"
        (base / "tests").mkdir(parents=True)
        (base / "tests" / "demo.spec.js").write_text(
            "test('a behavior (DEMO-01)', async () => {});\n",
            encoding="utf-8",
            newline="\n",
        )
        spec = base / "SPEC.md"
        spec.write_text(
            "# Spec\n\n"
            "| Feature id | Behavior | Covering tests |\n"
            "| --- | --- | --- |\n"
            "| DEMO-01 | Demo behavior. | partial - `tests/demo.spec.js` covers the happy path |\n",
            encoding="utf-8",
            newline="\n",
        )

        self.assertEqual([], refs.check_spec(spec, base))

    def test_a_row_that_cites_nothing_at_all_fails(self):
        # The other half of the same gap: not a bare FILE reference but no reference at all. A JS
        # target is caught from the other side (its test titles carry the id); a Python
        # `Class.method` name cannot, so the row itself must name the test.
        spec = self._spec((("GUARD-01", "Manual verification covers the behavior."),))

        messages = [issue.message for issue in self._check_all(spec)]

        self.assertEqual(1, len(messages), messages)
        self.assertIn("row `GUARD-01` names no covering test", messages[0])

    def test_a_row_may_still_record_manual_coverage(self):
        # AGENTS.md keeps `manual` for a behavior that genuinely cannot be automated, so the row
        # rule must demand a NAMED test rather than forbid the documented escape hatch - provided
        # the row is also listed under "Coverage gaps", which is the other half of that bargain.
        spec = self.sandbox / "SPEC.md"
        spec.write_text(
            "# Spec\n\n"
            "| Feature id | Behavior | Covering tests |\n"
            "| --- | --- | --- |\n"
            "| GUARD-01 | Demo behavior. | `manual` - an agent convention, not automatable |\n"
            "\n## Coverage gaps\n\n"
            "GUARD-01 is a prompt-level convention with no automatable surface.\n",
            encoding="utf-8",
            newline="\n",
        )

        self.assertEqual([issue.format() for issue in self._check_all(spec)], [])

    def test_a_manual_row_must_be_listed_under_coverage_gaps(self):
        spec = self._spec((("GUARD-01", "`manual` - an agent convention, not automatable"),))

        messages = [issue.message for issue in self._check_all(spec)]

        self.assertEqual(1, len(messages), messages)
        self.assertIn("is not listed under \"Coverage gaps\"", messages[0])

    def test_a_registered_spec_with_no_feature_rows_fails(self):
        # The per-suite checks this replaced asserted their spec still declared rows. Without that,
        # an emptied or renamed table would leave a vacuously green gate behind.
        spec = self.sandbox / "SPEC.md"
        spec.write_text("# Spec\n\nProse only.\n", encoding="utf-8", newline="\n")

        messages = [issue.message for issue in self._check_all(spec)]

        self.assertEqual(1, len(messages), messages)
        self.assertIn("declares no feature rows", messages[0])

    def test_a_directory_named_like_a_test_file_is_not_a_suite(self):
        # `_test_corpus` skips a directory, so accepting one here would hand back an empty corpus
        # while reporting the target as located - the silent no-op the fail-closed branch exists
        # to prevent.
        bare = self.sandbox / "dir-suite"
        (bare / "test_not_a_file.py").mkdir(parents=True)
        spec = self._spec_at(bare, "GUARD-01")

        messages = [issue.message for issue in self._check_all(spec)]

        self.assertEqual(1, len(messages), messages)
        self.assertIn("no tests directory found for this target", messages[0])

    def test_an_uppercase_extension_still_carries_js_titles(self):
        # `_JS_TEST_FILE_RE` admits `foo.spec.JS`, so such a file IS in the corpus; bounding the
        # JS-title directions by a case-SENSITIVE suffix would have let it evade both of them.
        base = self.sandbox / "shouty"
        (base / "tests").mkdir(parents=True)
        carrier = base / "tests" / "loud.SPEC.JS"
        carrier.write_text(
            "test('an unowned behavior (ORPHAN-99)', async () => {});\n",
            encoding="utf-8",
            newline="\n",
        )
        spec = base / "SPEC.md"
        spec.write_text(
            "# Spec\n\n"
            "| Feature id | Behavior | Covering tests |\n"
            "| --- | --- | --- |\n"
            "| DEMO-01 | Demo behavior. | `tests/loud.SPEC.JS` - "
            "`an unowned behavior (ORPHAN-99)` |\n",
            encoding="utf-8",
            newline="\n",
        )

        self.assertTrue(refs._carries_js_titles(carrier))
        self.assertIn(
            "feature id `ORPHAN-99` has no spec row",
            [issue.message for issue in refs.check_test_id_mappings(spec, base, (carrier,))],
        )

    def test_a_partial_marker_does_not_excuse_a_flat_row(self):
        # `partial` asserts a test EXISTS, so a flat row must name it. Only `manual` - a behavior
        # that genuinely cannot be automated - is a no-test declaration here.
        spec = self._spec((("GUARD-01", "partial - covered elsewhere"),))

        messages = [issue.message for issue in self._check_all(spec)]

        self.assertEqual(1, len(messages), messages)
        self.assertIn("row `GUARD-01` names no covering test", messages[0])

    def test_a_row_missing_its_trailing_pipe_is_reported_not_skipped(self):
        # GFM makes the trailing `|` optional, so this renders as an ordinary row - but neither
        # `_row_cells` nor the coverage gate reads it, and a flat target has no reverse direction
        # to notice. Skipping it would reopen the bare-citation gap on a row that looks normal.
        spec = self.sandbox / "SPEC.md"
        spec.write_text(
            "# Spec\n\n"
            "| Feature id | Behavior | Covering tests |\n"
            "| --- | --- | --- |\n"
            "| GUARD-01 | Demo behavior. | `scripts/test_check_forbidden_files.py`\n",
            encoding="utf-8",
            newline="\n",
        )

        messages = [issue.message for issue in self._check_all(spec)]

        self.assertEqual(1, len(messages), messages)
        self.assertIn("row `GUARD-01` is not a well-formed table row", messages[0])

    def test_every_flat_python_suite_is_a_registered_target(self):
        # A `FLAT_PYTHON_SUITES` entry that is not also in `SPEC_TARGETS` is dead weight: nothing
        # would ever ask for its tests directory, so the registration would look done and check
        # nothing.
        registered = {spec.resolve() for spec, _base in refs.SPEC_TARGETS}

        self.assertLessEqual(refs.FLAT_PYTHON_SUITES, registered)

    def test_the_scripts_spec_is_a_registered_flat_python_target(self):
        spec = (self.root / "scripts" / "SPEC.md").resolve()

        self.assertIn(spec, {path.resolve() for path, _base in refs.SPEC_TARGETS})
        self.assertIn(spec, refs.FLAT_PYTHON_SUITES)
        # A Python method name cannot carry a hyphenated feature id, so there is no reverse
        # citation to demand; the target is registered restricted with that reason recorded.
        self.assertIn(spec, refs.INTENTIONALLY_RESTRICTED_SPECS)
        self.assertEqual(refs._tests_dir(spec, self.root), self.root / "scripts")


class DuplicateSpecRowTests(unittest.TestCase):
    """One feature id owns exactly ONE spec row (issue #904).

    Seven ids used to own two rows each - `CMH-BUILD-13`, `CMH-CONTENT-01` through
    `CMH-CONTENT-04`, and `CMH-DECK-21` on the commentable-html spec, plus `SITE-NAV-02` on the
    site spec - and nothing failed: `_spec_rows` merges same-id rows, so a test cited by EITHER row
    satisfied the other and a citation for those ids was ambiguous.
    """

    def setUp(self):
        self.sandbox = Path(tempfile.mkdtemp(prefix="spec-refs-dup-rows-"))
        self.addCleanup(shutil.rmtree, self.sandbox, ignore_errors=True)
        self.base = self.sandbox / "base"
        (self.base / "tests").mkdir(parents=True)
        (self.base / "tests" / "demo.spec.js").write_text(
            "test('real browser title (DEMO-01)', async () => {});\n"
            "test('another real title (DEMO-02)', async () => {});\n",
            encoding="utf-8",
            newline="\n",
        )

    def _write(self, body, name="SPEC.md"):
        spec = self.sandbox / name
        spec.write_text(body, encoding="utf-8", newline="\n")
        return spec

    def _feature_table(self, rows, header="| Feature id | Behavior | Covering tests |\n"):
        return (
            "# Spec\n\n"
            + header
            + "| --- | --- | --- |\n"
            + "".join(
                "| %s | Demo behavior. | `tests/demo.spec.js` - `%s` |\n" % (fid, title)
                for fid, title in rows
            )
        )

    def _expected_lines(self, spec, feature_id):
        """The 1-based line numbers whose row id cell is *feature_id*, read off the fixture.

        Derived rather than hard-coded so a harmless edit to the fixture helper does not fail a
        test that is really about duplicate detection.
        """
        return [
            index
            for index, line in enumerate(spec.read_text(encoding="utf-8").splitlines(), 1)
            if line.startswith("| %s |" % feature_id)
        ]

    def test_flags_a_feature_id_that_is_the_id_cell_of_two_rows(self):
        spec = self._write(self._feature_table((
            ("DEMO-01", "real browser title (DEMO-01)"),
            ("DEMO-01", "another real title (DEMO-02)"),
        )))

        issues = refs.check_duplicate_spec_rows(((spec, self.base),))

        self.assertEqual(1, len(issues), [issue.format() for issue in issues])
        self.assertIn("`DEMO-01`", issues[0].message)
        self.assertIn("2 spec rows", issues[0].message)
        self.assertIn(
            "lines %s" % ", ".join(str(n) for n in self._expected_lines(spec, "DEMO-01")),
            issues[0].message,
        )
        self.assertIn("one feature id, one behavior", issues[0].message)

    def test_a_spec_whose_ids_are_unique_passes(self):
        spec = self._write(self._feature_table((
            ("DEMO-01", "real browser title (DEMO-01)"),
            ("DEMO-02", "another real title (DEMO-02)"),
        )))

        self.assertEqual([], refs.check_duplicate_spec_rows(((spec, self.base),)))

    def test_the_doc_surface_registry_repeats_an_id_without_being_a_second_row(self):
        # The registry table's rows also start with a feature id, so a duplicate gate that read
        # every feature-id row would red every registered id in the real commentable-html spec.
        spec = self._write(
            self._feature_table((("DEMO-01", "real browser title (DEMO-01)"),))
            + "\n### Doc-surface registry\n\n"
            "| Feature id | Doc surface | Deck |\n"
            "| --- | --- | --- |\n"
            "| DEMO-01 | tutorial | deck |\n"
        )

        self.assertEqual([], refs.check_duplicate_spec_rows(((spec, self.base),)))

    def test_an_unrecognised_behavior_header_still_counts(self):
        # Fail CLOSED: excluding every table whose second header cell is not spelled exactly
        # `Behavior` hid a real duplicate behind a header the parser merely did not recognise.
        for header in (
            "| Feature id | **Behavior** | Covering tests |\n",
            "| Feature id | Behaviour | Covering tests |\n",
            "| Feature id | Behavior / invariant | Covering tests |\n",
        ):
            with self.subTest(header=header.strip()):
                spec = self._write(self._feature_table((
                    ("DEMO-01", "real browser title (DEMO-01)"),
                    ("DEMO-01", "another real title (DEMO-02)"),
                ), header=header))

                issues = refs.check_duplicate_spec_rows(((spec, self.base),))

                self.assertEqual(1, len(issues), [issue.format() for issue in issues])
                self.assertIn("`DEMO-01`", issues[0].message)

    def test_a_headerless_table_still_counts(self):
        spec = self._write(
            "# Spec\n\n"
            "| DEMO-01 | Demo behavior. | `tests/demo.spec.js` - `real browser title (DEMO-01)` |\n"
            "| DEMO-01 | Demo behavior. | `tests/demo.spec.js` - `another real title (DEMO-02)` |\n"
        )

        issues = refs.check_duplicate_spec_rows(((spec, self.base),))

        self.assertEqual(1, len(issues), [issue.format() for issue in issues])

    def test_a_registry_header_does_not_leak_into_the_next_table(self):
        # The header is per TABLE: a non-feature header must not excuse rows in a later,
        # headerless table.
        spec = self._write(
            self._feature_table((("DEMO-01", "real browser title (DEMO-01)"),))
            + "\n### Doc-surface registry\n\n"
            "| Feature id | Doc surface | Deck |\n"
            "| --- | --- | --- |\n"
            "| DEMO-01 | tutorial | deck |\n"
            "\n"
            "| DEMO-01 | Demo behavior. | `tests/demo.spec.js` - `another real title (DEMO-02)` |\n"
        )

        issues = refs.check_duplicate_spec_rows(((spec, self.base),))

        self.assertEqual(1, len(issues), [issue.format() for issue in issues])
        self.assertIn("2 spec rows", issues[0].message)

    def test_a_decorated_id_cell_is_still_the_same_id(self):
        spec = self._write(
            self._feature_table((("DEMO-01", "real browser title (DEMO-01)"),))
            + "| **DEMO-01** | Demo behavior. | `tests/demo.spec.js` - `another real title "
              "(DEMO-02)` |\n"
        )

        issues = refs.check_duplicate_spec_rows(((spec, self.base),))

        self.assertEqual(1, len(issues), [issue.format() for issue in issues])
        self.assertIn("`DEMO-01`", issues[0].message)

    def test_a_sample_table_in_a_fenced_code_block_is_not_a_row(self):
        for open_marker, close_marker in (
            ("```markdown", "```"),
            ("~~~markdown", "~~~"),
            ("````", "````"),
        ):
            with self.subTest(fence=open_marker):
                spec = self._write(
                    self._feature_table((("DEMO-01", "real browser title (DEMO-01)"),))
                    + "\nHow to add a row:\n\n"
                    + open_marker + "\n"
                    "| Feature id | Behavior | Covering tests |\n"
                    "| --- | --- | --- |\n"
                    "| DEMO-01 | Sample. | `tests/demo.spec.js` - `real browser title "
                    "(DEMO-01)` |\n"
                    + close_marker + "\n"
                )

                self.assertEqual([], refs.check_duplicate_spec_rows(((spec, self.base),)))

    def test_a_tilde_line_inside_a_backtick_fence_does_not_end_it(self):
        # Closing on ANY 3+ run would reopen the scan mid-sample and read the sample rows as real.
        spec = self._write(
            self._feature_table((("DEMO-01", "real browser title (DEMO-01)"),))
            + "\n```markdown\n"
            "~~~\n"
            "| DEMO-01 | Sample. | `tests/demo.spec.js` - `real browser title (DEMO-01)` |\n"
            "```\n"
        )

        self.assertEqual([], refs.check_duplicate_spec_rows(((spec, self.base),)))

    def test_a_short_closer_does_not_end_a_longer_fence(self):
        spec = self._write(
            self._feature_table((("DEMO-01", "real browser title (DEMO-01)"),))
            + "\n````markdown\n"
            "```\n"
            "| DEMO-01 | Sample. | `tests/demo.spec.js` - `real browser title (DEMO-01)` |\n"
            "````\n"
        )

        self.assertEqual([], refs.check_duplicate_spec_rows(((spec, self.base),)))

    def test_an_indented_code_block_never_opens_a_fence(self):
        # A 4-space-indented `~~~` is indented CODE, not a fence; treating it as one used to
        # swallow every real row after it.
        spec = self._write(
            "# Spec\n\n"
            "Example:\n\n"
            "    ~~~\n\n"
            + self._feature_table((
                ("DEMO-01", "real browser title (DEMO-01)"),
                ("DEMO-01", "another real title (DEMO-02)"),
            )).split("# Spec\n\n", 1)[1]
        )

        issues = refs.check_duplicate_spec_rows(((spec, self.base),))

        self.assertEqual(1, len(issues), [issue.format() for issue in issues])

    def test_a_blockquoted_row_is_still_a_row(self):
        spec = self._write(
            self._feature_table((("DEMO-01", "real browser title (DEMO-01)"),))
            + "\n> | DEMO-01 | Demo behavior. | `tests/demo.spec.js` - `another real title "
              "(DEMO-02)` |\n"
        )

        issues = refs.check_duplicate_spec_rows(((spec, self.base),))

        self.assertEqual(1, len(issues), [issue.format() for issue in issues])

    def test_a_two_cell_row_is_still_a_row(self):
        spec = self._write(
            self._feature_table((("DEMO-01", "real browser title (DEMO-01)"),))
            + "| DEMO-01 | A malformed row with no coverage cell. |\n"
        )

        issues = refs.check_duplicate_spec_rows(((spec, self.base),))

        self.assertEqual(1, len(issues), [issue.format() for issue in issues])

    def test_a_spec_with_no_tables_passes(self):
        spec = self._write("# Spec\n\nProse only, no tables here.\n")

        self.assertEqual([], refs.check_duplicate_spec_rows(((spec, self.base),)))

    def test_an_unterminated_fence_is_reported_not_silently_skipped(self):
        # An unclosed fence swallows every row after it, so the direction would go green over a
        # spec it never read - and dev/SPEC.md is a concatenation of partials, so one imbalance
        # early on un-checks every later section.
        spec = self._write(
            "# Spec\n\n```markdown\nan unclosed sample\n\n"
            + self._feature_table((
                ("DEMO-01", "real browser title (DEMO-01)"),
                ("DEMO-01", "another real title (DEMO-02)"),
            )).split("# Spec\n\n", 1)[1]
        )

        issues = refs.check_duplicate_spec_rows(((spec, self.base),))

        self.assertEqual(
            ["code fence opened here is never closed, so the spec rows after it cannot be read; "
             "close the fence"],
            [issue.message for issue in issues],
        )
        self.assertEqual(3, issues[0].line)

    def test_a_registry_row_is_not_a_coverage_cell_for_its_id(self):
        # `_spec_rows` feeds the citation checks, so it must read the SAME rows this direction
        # enforces over: an `opt-out:` reason that happens to quote a real test would otherwise
        # satisfy a citation for an id whose actual row cites nothing.
        spec = self._write(
            self._feature_table((("DEMO-01", "real browser title (DEMO-01)"),))
            + "\n### Doc-surface registry\n\n"
            "| Feature id | Doc surface | Deck |\n"
            "| --- | --- | --- |\n"
            "| DEMO-01 | opt-out: shown by `tests/demo.spec.js` - `another real title (DEMO-02)` "
            "| deck |\n"
        )

        self.assertEqual(1, len(refs._spec_rows(spec)["DEMO-01"]))
        self.assertFalse(refs._row_cites(
            refs._spec_rows(spec)["DEMO-01"], "tests/demo.spec.js",
            "another real title (DEMO-02)"))

    def test_a_fenced_sample_row_is_not_a_coverage_cell_either(self):
        spec = self._write(
            self._feature_table((("DEMO-01", "real browser title (DEMO-01)"),))
            + "\n```markdown\n"
            "| DEMO-01 | Sample. | `tests/demo.spec.js` - `another real title (DEMO-02)` |\n"
            "```\n"
        )

        self.assertEqual(1, len(refs._spec_rows(spec)["DEMO-01"]))
        self.assertFalse(refs._row_cites(
            refs._spec_rows(spec)["DEMO-01"], "tests/demo.spec.js",
            "another real title (DEMO-02)"))

    def test_the_same_id_in_two_different_targets_is_not_a_duplicate(self):
        first = self._write(
            self._feature_table((("DEMO-01", "real browser title (DEMO-01)"),)), "FIRST.md")
        second = self._write(
            self._feature_table((("DEMO-01", "real browser title (DEMO-01)"),)), "SECOND.md")

        self.assertEqual(
            [], refs.check_duplicate_spec_rows(((first, self.base), (second, self.base))))

    def test_a_doc_surface_header_outside_the_registry_section_does_not_excuse_a_row(self):
        # Keying only on the header text let a duplicate hide under a table that merely SPELLS its
        # column `Doc surface` anywhere in the spec.
        spec = self._write(
            self._feature_table((("DEMO-01", "real browser title (DEMO-01)"),))
            + "\n### Some other section\n\n"
            "| Feature id | Doc surface | Deck |\n"
            "| --- | --- | --- |\n"
            "| DEMO-01 | tutorial | deck |\n"
        )

        issues = refs.check_duplicate_spec_rows(((spec, self.base),))

        self.assertEqual(1, len(issues), [issue.format() for issue in issues])
        self.assertIn("2 spec rows", issues[0].message)

    def test_a_reordered_or_decorated_registry_header_still_excuses_its_rows(self):
        # The deny-list matches ANY header cell as a PREFIX, so inserting a column before
        # `Doc surface`, decorating it, or renaming it `Doc surfaces` does not turn every
        # registered id into a duplicate.
        for header in (
            "| Feature id | Owner | **Doc surface** | Deck |\n",
            "| Feature id | Doc surfaces | Deck |\n",
        ):
            with self.subTest(header=header.strip()):
                columns = header.count("|") - 1
                spec = self._write(
                    self._feature_table((("DEMO-01", "real browser title (DEMO-01)"),))
                    + "\n### Doc-surface registry\n\n"
                    + header
                    + "| " + " | ".join(["---"] * columns) + " |\n"
                    + "| DEMO-01 | " + " | ".join(["tutorial"] * (columns - 1)) + " |\n"
                )

                self.assertEqual([], refs.check_duplicate_spec_rows(((spec, self.base),)))

    def test_a_registry_header_does_not_latch_onto_an_adjacent_table(self):
        # The header comes from the line above each DELIMITER row (GFM), so a table butted
        # straight against the registry with no blank line gets its OWN header rather than
        # inheriting the registry's. (A row appended INSIDE the registry table is genuinely a
        # registry row; `check_doc_surfaces.py` rejects that one, since its cells are not a valid
        # doc-surface/deck pair.)
        spec = self._write(
            self._feature_table((("DEMO-01", "real browser title (DEMO-01)"),))
            + "\n### Doc-surface registry\n\n"
            "| Feature id | Doc surface | Deck |\n"
            "| --- | --- | --- |\n"
            "| DEMO-01 | tutorial | deck |\n"
            "| Feature id | Behavior | Covering tests |\n"
            "| --- | --- | --- |\n"
            "| DEMO-01 | Demo behavior. | `tests/demo.spec.js` - `another real title (DEMO-02)` |"
            "\n"
        )

        issues = refs.check_duplicate_spec_rows(((spec, self.base),))

        self.assertEqual(1, len(issues), [issue.format() for issue in issues])
        self.assertIn("2 spec rows", issues[0].message)

    def test_a_row_with_no_trailing_pipe_is_still_a_row(self):
        spec = self._write(
            self._feature_table((("DEMO-01", "real browser title (DEMO-01)"),))
            + "| DEMO-01 | Demo behavior. | `tests/demo.spec.js` - `another real title (DEMO-02)`"
              "\n"
        )

        issues = refs.check_duplicate_spec_rows(((spec, self.base),))

        self.assertEqual(1, len(issues), [issue.format() for issue in issues])

    def test_a_malformed_row_owns_its_id_but_supplies_no_coverage(self):
        # Enforced is a SUPERSET of consumed: a blockquoted, two-cell, or unclosed row counts for
        # the duplicate gate, but must not OWN a citation - an illustrative row quoted in prose
        # would otherwise satisfy the reverse direction.
        for shape in (
            "> | DEMO-01 | Demo. | `tests/demo.spec.js` - `another real title (DEMO-02)` |\n",
            "| DEMO-01 | `tests/demo.spec.js` - `another real title (DEMO-02)` |\n",
            "| DEMO-01 | Demo. | `tests/demo.spec.js` - `another real title (DEMO-02)`\n",
        ):
            with self.subTest(shape=shape.strip()):
                spec = self._write(
                    self._feature_table((("DEMO-01", "real browser title (DEMO-01)"),)) + shape)

                self.assertEqual(1, len(refs._spec_rows(spec)["DEMO-01"]))
                self.assertFalse(refs._row_cites(
                    refs._spec_rows(spec)["DEMO-01"], "tests/demo.spec.js",
                    "another real title (DEMO-02)"))
                self.assertEqual(
                    1, len(refs.check_duplicate_spec_rows(((spec, self.base),))))

    def test_an_id_that_merely_contains_decoration_is_not_normalised(self):
        # Stripping every `*` would turn `DEM*O-01` into `DEMO-01` and invent a duplicate.
        spec = self._write(
            self._feature_table((("DEMO-01", "real browser title (DEMO-01)"),))
            + "| DEM*O-01 | Demo behavior. | `tests/demo.spec.js` - `another real title "
              "(DEMO-02)` |\n"
        )

        self.assertEqual([], refs.check_duplicate_spec_rows(((spec, self.base),)))

    def test_decoration_is_stripped_whatever_the_marker(self):
        for decorated in (
            "**DEMO-01**", "_DEMO-01_", "`DEMO-01`", "~~DEMO-01~~", "[DEMO-01](#demo-01)",
            "<code>DEMO-01</code>",
        ):
            with self.subTest(decorated=decorated):
                spec = self._write(
                    self._feature_table((("DEMO-01", "real browser title (DEMO-01)"),))
                    + "| %s | Demo behavior. | `tests/demo.spec.js` - `another real title "
                      "(DEMO-02)` |\n" % decorated
                )

                issues = refs.check_duplicate_spec_rows(((spec, self.base),))

                self.assertEqual(1, len(issues), [issue.format() for issue in issues])
                self.assertIn("`DEMO-01`", issues[0].message)

    def test_a_behavior_table_under_the_registry_heading_still_counts(self):
        # BOTH gates must agree before a row is excused; a real feature table parked under the
        # registry heading is still a feature table.
        spec = self._write(
            self._feature_table((("DEMO-01", "real browser title (DEMO-01)"),))
            + "\n### Doc-surface registry\n\n"
            "| Feature id | Behavior | Covering tests |\n"
            "| --- | --- | --- |\n"
            "| DEMO-01 | Demo behavior. | `tests/demo.spec.js` - `another real title (DEMO-02)` |"
            "\n"
        )

        issues = refs.check_duplicate_spec_rows(((spec, self.base),))

        self.assertEqual(1, len(issues), [issue.format() for issue in issues])
        self.assertIn("2 spec rows", issues[0].message)

    def test_a_legal_indented_fence_still_opens_and_a_longer_closer_still_closes(self):
        spec = self._write(
            self._feature_table((("DEMO-01", "real browser title (DEMO-01)"),))
            + "\n   ```markdown\n"
            "| DEMO-01 | Sample. | `tests/demo.spec.js` - `real browser title (DEMO-01)` |\n"
            "   `````\n"
        )

        self.assertEqual([], refs.check_duplicate_spec_rows(((spec, self.base),)))

    def test_a_backtick_info_string_containing_a_backtick_does_not_open_a_fence(self):
        # CommonMark forbids a backtick in a backtick fence's info string, so this line is text -
        # treating it as a fence would swallow the duplicate below it.
        spec = self._write(
            "# Spec\n\n```a`b\n\n"
            + self._feature_table((
                ("DEMO-01", "real browser title (DEMO-01)"),
                ("DEMO-01", "another real title (DEMO-02)"),
            )).split("# Spec\n\n", 1)[1]
        )

        issues = refs.check_duplicate_spec_rows(((spec, self.base),))

        self.assertEqual(1, len(issues), [issue.format() for issue in issues])
        self.assertIn("2 spec rows", issues[0].message)

    def test_a_table_row_inside_an_indented_code_block_is_not_a_row(self):
        spec = self._write(
            self._feature_table((("DEMO-01", "real browser title (DEMO-01)"),))
            + "\nExample:\n\n"
            "    | DEMO-01 | Sample. | `tests/demo.spec.js` - `real browser title (DEMO-01)` |\n"
        )

        self.assertEqual([], refs.check_duplicate_spec_rows(((spec, self.base),)))

    def test_check_all_reports_only_the_fence_for_an_unreadable_spec(self):
        # A blanked row set would otherwise make the citation directions shout "has no spec row"
        # for every test after the fence and bury the one actionable cause.
        spec = self._write(
            "# Spec\n\n```markdown\nan unclosed sample\n\n"
            + self._feature_table((("DEMO-01", "real browser title (DEMO-01)"),))
            .split("# Spec\n\n", 1)[1]
        )

        issues = refs.check_all(((spec, self.base),))

        self.assertEqual(1, len(issues), [issue.format() for issue in issues])
        self.assertIn("never closed", issues[0].message)

    def test_three_rows_for_one_id_are_reported_once_naming_every_line(self):
        spec = self._write(self._feature_table((
            ("DEMO-01", "real browser title (DEMO-01)"),
            ("DEMO-01", "another real title (DEMO-02)"),
            ("DEMO-01", "real browser title (DEMO-01)"),
        )))

        issues = refs.check_duplicate_spec_rows(((spec, self.base),))

        self.assertEqual(1, len(issues), [issue.format() for issue in issues])
        self.assertIn("3 spec rows", issues[0].message)
        self.assertIn(
            "lines %s" % ", ".join(str(n) for n in self._expected_lines(spec, "DEMO-01")),
            issues[0].message,
        )

    def test_check_all_runs_the_duplicate_spec_row_check(self):
        spec = self._write(self._feature_table((
            ("DEMO-01", "real browser title (DEMO-01)"),
            ("DEMO-01", "another real title (DEMO-02)"),
        )))

        issues = refs.check_all(((spec, self.base),))

        self.assertEqual(
            1, len([issue for issue in issues if "spec rows" in issue.message]),
            [issue.format() for issue in issues])


if __name__ == "__main__":
    unittest.main()
