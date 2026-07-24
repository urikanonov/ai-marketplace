#!/usr/bin/env python3
"""Tests for scripts/check_doc_surfaces.py (pure, no git required)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_doc_surfaces as docs  # noqa: E402


MAIN_HEADER = "| Feature id | Behavior | Covering tests |\n| --- | --- | --- |\n"
REG_HEADER = "| Feature id | Doc surface |\n| --- | --- |\n"


def main_row(fid, behavior="does a thing", tests="`tests/x.spec.js` - `t (%s)`"):
    return "| %s | %s | %s |\n" % (fid, behavior, tests % fid)


def reg_row(fid, value):
    return "| %s | %s |\n" % (fid, value)


class SurfaceValueTests(unittest.TestCase):
    def test_single_surface_is_valid(self):
        for s in ("tutorial", "site", "help"):
            self.assertIsNone(docs.surface_value_error(s))

    def test_comma_list_is_valid(self):
        self.assertIsNone(docs.surface_value_error("tutorial, help"))
        self.assertIsNone(docs.surface_value_error("site,tutorial,help"))

    def test_opt_out_with_reason_is_valid(self):
        self.assertIsNone(docs.surface_value_error("opt-out: internal hardening"))
        self.assertIsNone(docs.surface_value_error("opt-out: build tooling (authoring)"))

    def test_opt_out_without_colon_fails(self):
        self.assertIsNotNone(docs.surface_value_error("opt-out tutorial"))
        self.assertIsNotNone(docs.surface_value_error("opt-out (build tooling)"))

    def test_opt_out_without_reason_fails(self):
        self.assertIsNotNone(docs.surface_value_error("opt-out"))
        self.assertIsNotNone(docs.surface_value_error("opt-out:"))
        # A reason must contain a visible character; whitespace / zero-width / punctuation-only
        # reasons are rejected.
        self.assertIsNotNone(docs.surface_value_error("opt-out:    "))
        self.assertIsNotNone(docs.surface_value_error("opt-out: \u200b"))
        self.assertIsNotNone(docs.surface_value_error("opt-out: ---"))

    def test_opt_out_lookalike_is_not_an_opt_out(self):
        # A token that merely starts with the letters "opt-out" (e.g. a typo) must NOT be
        # accepted as an opt-out; it falls through to surface parsing and is rejected.
        self.assertIsNotNone(docs.surface_value_error("opt-outage"))
        self.assertIsNotNone(docs.surface_value_error("opt-outer without a colon"))

    def test_malformed_surface_list_fails(self):
        # Empty elements from a trailing or doubled comma are rejected.
        self.assertIsNotNone(docs.surface_value_error("tutorial,"))
        self.assertIsNotNone(docs.surface_value_error("tutorial,,help"))
        self.assertIsNotNone(docs.surface_value_error(",help"))

    def test_unknown_surface_fails(self):
        self.assertIsNotNone(docs.surface_value_error("readme"))
        self.assertIsNotNone(docs.surface_value_error("tutorial, blog"))

    def test_empty_fails(self):
        self.assertIsNotNone(docs.surface_value_error(""))
        self.assertIsNotNone(docs.surface_value_error("   "))


class ParsingTests(unittest.TestCase):
    def test_feature_ids_reads_main_rows_only(self):
        spec = (
            MAIN_HEADER
            + main_row("CMH-FOO-01")
            + main_row("CMH-BAR-02")
            + REG_HEADER
            + reg_row("CMH-FOO-01", "help")
        )
        # The 2-cell registry row for CMH-FOO-01 must not add a phantom id, and must not be
        # mistaken for a main feature row.
        self.assertEqual(docs.feature_ids(spec), {"CMH-FOO-01", "CMH-BAR-02"})

    def test_registry_reads_two_cell_rows_only(self):
        spec = (
            MAIN_HEADER
            + main_row("CMH-FOO-01")
            + REG_HEADER
            + reg_row("CMH-FOO-01", "tutorial, help")
        )
        self.assertEqual(docs.registry(spec), {"CMH-FOO-01": "tutorial, help"})

    def test_headers_and_separators_ignored(self):
        self.assertEqual(docs.feature_ids(MAIN_HEADER), set())
        self.assertEqual(docs.registry(REG_HEADER), {})


class EvaluateTests(unittest.TestCase):
    def _spec(self, main_ids, reg_pairs):
        text = MAIN_HEADER + "".join(main_row(i) for i in main_ids)
        text += REG_HEADER + "".join(reg_row(i, v) for i, v in reg_pairs)
        return text

    def test_new_id_with_registry_entry_passes(self):
        base = self._spec(["CMH-FOO-01"], [])
        head = self._spec(["CMH-FOO-01", "CMH-BAR-02"], [("CMH-BAR-02", "help")])
        self.assertEqual(docs.evaluate(head, base), [])

    def test_new_id_without_registry_entry_fails(self):
        base = self._spec(["CMH-FOO-01"], [])
        head = self._spec(["CMH-FOO-01", "CMH-BAR-02"], [])
        failures = docs.evaluate(head, base)
        self.assertTrue(any("CMH-BAR-02" in f and "registry" in f.lower() for f in failures))

    def test_refined_existing_id_not_forced(self):
        # An id present at base is not "new" even if its row text changed; no entry required.
        base = self._spec(["CMH-FOO-01"], [])
        head = MAIN_HEADER + main_row("CMH-FOO-01", behavior="does a NEW thing") + REG_HEADER
        self.assertEqual(docs.evaluate(head, base), [])

    def test_stale_registry_entry_fails(self):
        head = self._spec(["CMH-FOO-01"], [("CMH-GONE-99", "help")])
        failures = docs.evaluate(head, base_spec=head)
        self.assertTrue(any("CMH-GONE-99" in f and "stale" in f.lower() for f in failures))

    def test_invalid_registry_value_fails(self):
        head = self._spec(["CMH-FOO-01"], [("CMH-FOO-01", "blog")])
        failures = docs.evaluate(head, base_spec=head)
        self.assertTrue(any("CMH-FOO-01" in f for f in failures))

    def test_duplicate_registry_entry_fails(self):
        head = self._spec(["CMH-FOO-01"], [("CMH-FOO-01", "help"), ("CMH-FOO-01", "tutorial")])
        failures = docs.evaluate(head, base_spec=head)
        self.assertTrue(any("duplicate" in f.lower() and "CMH-FOO-01" in f for f in failures))

    def test_no_base_skips_new_id_gate(self):
        # With no base, legacy ids must NOT be treated as new (only registry consistency checked).
        head = self._spec(["CMH-FOO-01", "CMH-BAR-02"], [])
        self.assertEqual(docs.evaluate(head, base_spec=None), [])


class RealSpecTests(unittest.TestCase):
    def test_committed_spec_registry_is_self_consistent(self):
        # The real SPEC.md registry must reference only real ids with valid values.
        if not docs.SPEC_PATH.is_file():
            self.skipTest("SPEC.md not present")
        text = docs.SPEC_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")
        failures = docs.evaluate(text, base_spec=None)
        self.assertEqual(failures, [], "\n".join(failures))


if __name__ == "__main__":
    unittest.main()
