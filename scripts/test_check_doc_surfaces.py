#!/usr/bin/env python3
"""Tests for scripts/check_doc_surfaces.py (pure, no git required)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_doc_surfaces as docs  # noqa: E402


MAIN_HEADER = "| Feature id | Behavior | Covering tests |\n| --- | --- | --- |\n"
# Registry rows are recognised only under the "Doc-surface registry" heading, so every test
# spec that carries a registry places this section header before its rows.
REG_HEADER = (
    "### Doc-surface registry\n"
    "| Feature id | Doc surface | Deck |\n| --- | --- | --- |\n"
)


def main_row(fid, behavior="does a thing", tests="`tests/x.spec.js` - `t (%s)`"):
    return "| %s | %s | %s |\n" % (fid, behavior, tests % fid)


def reg_row(fid, value, deck="deck"):
    return "| %s | %s | %s |\n" % (fid, value, deck)


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
        # `deck` is a separate dimension (its own column), NOT a doc surface.
        self.assertIsNotNone(docs.surface_value_error("deck"))
        self.assertIsNotNone(docs.surface_value_error("tutorial, deck"))

    def test_empty_fails(self):
        self.assertIsNotNone(docs.surface_value_error(""))
        self.assertIsNotNone(docs.surface_value_error("   "))


class DeckValueTests(unittest.TestCase):
    def test_deck_literal_is_valid(self):
        self.assertIsNone(docs.deck_value_error("deck"))
        self.assertIsNone(docs.deck_value_error(" DECK "))

    def test_opt_out_with_reason_is_valid(self):
        self.assertIsNone(docs.deck_value_error("opt-out: purely internal, no slide"))

    def test_opt_out_without_reason_or_colon_fails(self):
        self.assertIsNotNone(docs.deck_value_error("opt-out"))
        self.assertIsNotNone(docs.deck_value_error("opt-out:"))
        self.assertIsNotNone(docs.deck_value_error("opt-out no colon"))

    def test_doc_surface_tokens_are_not_valid_deck_values(self):
        # The deck column does not accept tutorial/site/help; it is `deck` or `opt-out: ...`.
        for s in ("tutorial", "site", "help", "tutorial, help"):
            self.assertIsNotNone(docs.deck_value_error(s))

    def test_empty_fails(self):
        self.assertIsNotNone(docs.deck_value_error(""))
        self.assertIsNotNone(docs.deck_value_error("   "))


class ParsingTests(unittest.TestCase):
    def test_feature_ids_reads_main_rows_only(self):
        spec = (
            MAIN_HEADER
            + main_row("CMH-FOO-01")
            + main_row("CMH-BAR-02")
            + REG_HEADER
            + reg_row("CMH-FOO-01", "help")
        )
        # The registry row for CMH-FOO-01 must not add a phantom id, and must not be mistaken
        # for a main feature row even though it now has three columns.
        self.assertEqual(docs.feature_ids(spec), {"CMH-FOO-01", "CMH-BAR-02"})

    def test_registry_reads_rows_under_heading_only(self):
        spec = (
            MAIN_HEADER
            + main_row("CMH-FOO-01")
            + REG_HEADER
            + reg_row("CMH-FOO-01", "tutorial, help", "deck")
        )
        self.assertEqual(docs.registry(spec), {"CMH-FOO-01": ("tutorial, help", "deck")})

    def test_three_column_row_outside_registry_is_a_feature_not_a_registry_entry(self):
        # Without the registry heading, a three-cell feature-id row is a feature row.
        spec = MAIN_HEADER + main_row("CMH-FOO-01")
        self.assertEqual(docs.feature_ids(spec), {"CMH-FOO-01"})
        self.assertEqual(docs.registry(spec), {})

    def test_headers_and_separators_ignored(self):
        self.assertEqual(docs.feature_ids(MAIN_HEADER), set())
        self.assertEqual(docs.registry(REG_HEADER), {})

    def test_has_registry_heading(self):
        self.assertTrue(docs.has_registry_heading(REG_HEADER))
        self.assertFalse(docs.has_registry_heading(MAIN_HEADER))

    def test_registry_region_survives_a_fenced_code_block(self):
        # A `#` line inside a fenced code block under the registry must NOT terminate the region,
        # so a registry row after the fence is still parsed as a registry entry.
        spec = (
            MAIN_HEADER
            + main_row("CMH-FOO-01")
            + main_row("CMH-BAR-02")
            + REG_HEADER
            + reg_row("CMH-FOO-01", "help")
            + "```python\n# not a heading\n```\n"
            + reg_row("CMH-BAR-02", "site")
        )
        reg = docs.registry(spec)
        self.assertIn("CMH-FOO-01", reg)
        self.assertIn("CMH-BAR-02", reg)

    def test_registry_heading_inside_code_fence_is_not_detected(self):
        spec = MAIN_HEADER + main_row("CMH-FOO-01") + "```\n### Doc-surface registry\n```\n"
        self.assertFalse(docs.has_registry_heading(spec))

    def test_nested_mismatched_fence_does_not_expose_a_sample_registry(self):
        # A ```-fence nested inside a ~~~ example must NOT close the ~~~ fence, so an embedded
        # "### Doc-surface registry" heading + table stays literal (fenced), not a live registry.
        spec = (
            MAIN_HEADER
            + main_row("CMH-FOO-01")
            + "~~~markdown\n"
            + "### Doc-surface registry\n"
            + "```\n"
            + "| CMH-FAKE-01 | help | deck |\n"
            + "```\n"
            + "~~~\n"
        )
        self.assertFalse(docs.has_registry_heading(spec))
        self.assertEqual(set(docs.registry(spec)), set())
        # Because there is no real registry heading, evaluate must fail closed rather than pass.
        self.assertTrue(any("Doc-surface registry" in f for f in docs.evaluate(spec, base_spec=None)))

    def test_fenced_example_rows_are_ignored(self):
        # An example table row inside a fenced code block (a doc sample) must NOT be parsed as a
        # feature row or a registry entry.
        spec = (
            MAIN_HEADER
            + main_row("CMH-FOO-01")
            + "```\n| CMH-EXAMPLE-99 | help | deck |\n```\n"
            + REG_HEADER
            + reg_row("CMH-FOO-01", "help")
            + "```\n| CMH-SAMPLE-98 | site | deck |\n```\n"
        )
        self.assertEqual(docs.feature_ids(spec), {"CMH-FOO-01"})
        self.assertEqual(set(docs.registry(spec)), {"CMH-FOO-01"})


class EvaluateTests(unittest.TestCase):
    def _spec(self, main_ids, reg_pairs):
        text = MAIN_HEADER + "".join(main_row(i) for i in main_ids)
        text += REG_HEADER + "".join(reg_row(i, v, d) for i, v, d in reg_pairs)
        return text

    def test_new_id_with_registry_entry_passes(self):
        base = self._spec(["CMH-FOO-01"], [])
        head = self._spec(["CMH-FOO-01", "CMH-BAR-02"], [("CMH-BAR-02", "help", "deck")])
        self.assertEqual(docs.evaluate(head, base), [])

    def test_new_id_without_registry_entry_fails(self):
        base = self._spec(["CMH-FOO-01"], [])
        head = self._spec(["CMH-FOO-01", "CMH-BAR-02"], [])
        failures = docs.evaluate(head, base)
        self.assertTrue(any("CMH-BAR-02" in f and "registry" in f.lower() for f in failures))

    def test_new_id_with_opt_out_deck_passes(self):
        base = self._spec(["CMH-FOO-01"], [])
        head = self._spec(
            ["CMH-FOO-01", "CMH-BAR-02"],
            [("CMH-BAR-02", "help", "opt-out: conceptual, no demo")],
        )
        self.assertEqual(docs.evaluate(head, base), [])

    def test_new_id_missing_deck_column_fails(self):
        # A registry row with only two cells lacks deck coverage and must fail.
        base = MAIN_HEADER + main_row("CMH-FOO-01") + REG_HEADER
        head = (
            MAIN_HEADER
            + main_row("CMH-FOO-01")
            + main_row("CMH-BAR-02")
            + REG_HEADER
            + "| CMH-BAR-02 | help |\n"
        )
        failures = docs.evaluate(head, base)
        self.assertTrue(any("CMH-BAR-02" in f and "deck" in f.lower() for f in failures))

    def test_invalid_deck_value_fails(self):
        head = self._spec(["CMH-FOO-01"], [("CMH-FOO-01", "help", "slideshow")])
        failures = docs.evaluate(head, base_spec=head)
        self.assertTrue(any("CMH-FOO-01" in f and "deck" in f.lower() for f in failures))

    def test_refined_existing_id_not_forced(self):
        # An id present at base is not "new" even if its row text changed; no entry required.
        base = self._spec(["CMH-FOO-01"], [])
        head = MAIN_HEADER + main_row("CMH-FOO-01", behavior="does a NEW thing") + REG_HEADER
        self.assertEqual(docs.evaluate(head, base), [])

    def test_stale_registry_entry_fails(self):
        head = self._spec(["CMH-FOO-01"], [("CMH-GONE-99", "help", "deck")])
        failures = docs.evaluate(head, base_spec=head)
        self.assertTrue(any("CMH-GONE-99" in f and "stale" in f.lower() for f in failures))

    def test_invalid_registry_value_fails(self):
        head = self._spec(["CMH-FOO-01"], [("CMH-FOO-01", "blog", "deck")])
        failures = docs.evaluate(head, base_spec=head)
        self.assertTrue(any("CMH-FOO-01" in f for f in failures))

    def test_duplicate_registry_entry_fails(self):
        head = self._spec(
            ["CMH-FOO-01"],
            [("CMH-FOO-01", "help", "deck"), ("CMH-FOO-01", "tutorial", "deck")],
        )
        failures = docs.evaluate(head, base_spec=head)
        self.assertTrue(any("duplicate" in f.lower() and "CMH-FOO-01" in f for f in failures))

    def test_no_base_skips_new_id_gate(self):
        # With no base, legacy ids must NOT be treated as new (only registry consistency checked).
        head = self._spec(["CMH-FOO-01", "CMH-BAR-02"], [])
        self.assertEqual(docs.evaluate(head, base_spec=None), [])

    def test_missing_registry_heading_fails_closed(self):
        # If the registry heading is renamed/removed, the check must fail closed rather than
        # silently parse an empty registry and stop validating coverage.
        head = MAIN_HEADER + main_row("CMH-FOO-01")  # no registry section at all
        failures = docs.evaluate(head, base_spec=None)
        self.assertTrue(any("Doc-surface registry" in f for f in failures))


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
