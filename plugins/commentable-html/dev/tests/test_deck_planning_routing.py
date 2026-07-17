"""CMH-DECK-14: SKILL.md routes deck DESIGN to the native CMH theme presets first.

When a user asks to plan or design a deck (not just scaffold one), the deck section of SKILL.md
must route the agent to the native deck theme presets and recipe classes BEFORE scaffolding, with
the vendored frontend-slides subtree demoted to provenance / a bespoke-only reference. This is a
string-presence check on the shipped SKILL.md deck section.
"""
import os
import unittest

import _paths

SKILL_MD = os.path.join(_paths.PKG, "SKILL.md")
_HEADING = "## Deck capability"


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class DeckPlanningRoutingTests(unittest.TestCase):
    def _deck_section(self):
        text = _read(SKILL_MD)
        self.assertIn(_HEADING, text)
        return text.split(_HEADING, 1)[1].split("\n## ", 1)[0]

    def test_plan_step_routes_to_native_theme_presets(self):
        deck = self._deck_section()
        for ref in ("tools/deck/themes", "--theme", "deck_theme.py"):
            self.assertIn(ref, deck, f"deck section must name {ref} for native theming")
        self.assertIn("recipe", deck.lower())

    def test_native_theming_precedes_scaffolding(self):
        deck = self._deck_section().lower()
        # Native theme selection must be described as a first design step, before scaffolding.
        self.assertIn("before scaffolding", deck)
        theme_pos = deck.find("--theme")
        vendor_pos = deck.find("vendor/frontend-slides")
        self.assertNotEqual(theme_pos, -1)
        # The vendored path, if named at all, is a fallback that appears after the native theme flow.
        if vendor_pos != -1:
            self.assertLess(theme_pos, vendor_pos,
                            "native --theme flow must be introduced before the vendored fallback")

    def test_ask_first_lists_the_conditional_questions(self):
        deck = self._deck_section()
        self.assertIn("Ask first", deck)
        low = deck.lower()
        for token in ("duration", "audience", "handed off", "running example", "install call-to-action", "theme"):
            self.assertIn(token, low, f"deck section must prompt for {token!r} up front")

    def test_plan_step_routes_to_the_deck_design_playbook(self):
        deck = self._deck_section()
        self.assertIn("references/deck-design.md", deck)

    def test_deck_design_playbook_exists_and_covers_key_conventions(self):
        path = os.path.join(_paths.PKG, "references", "deck-design.md")
        self.assertTrue(os.path.isfile(path), "references/deck-design.md must exist")
        text = _read(path).lower()
        for token in (
            "ask first",
            "fill the fixed stage",
            "transform-only",
            "pain before mechanism",
            "copy all",
            "data-slide-id",
        ):
            self.assertIn(token, text, f"deck-design.md must cover {token!r}")


if __name__ == "__main__":
    unittest.main()
