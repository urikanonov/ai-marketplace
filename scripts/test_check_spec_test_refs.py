#!/usr/bin/env python3
"""Tests for scripts/check_spec_test_refs.py."""

import os
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_spec_test_refs as refs  # noqa: E402


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

    def test_accepts_exact_feature_id_reference(self):
        spec = self._spec("`tests/demo.spec.js` - `DEMO-01`")

        self.assertEqual(refs.check_spec(spec, self.base), [])

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
