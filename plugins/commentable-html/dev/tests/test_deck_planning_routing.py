"""CMH-DECK-14: SKILL.md routes deck PLANNING to the vendored frontend-slides design system.

When a user asks to plan or design a deck (not just scaffold one), the deck section of SKILL.md
must tell the agent to consult the vendored frontend-slides design docs BEFORE scaffolding. This
is a string-presence check on the shipped SKILL.md deck section.
"""
import os
import unittest

import _paths

SKILL_MD = os.path.join(_paths.PKG, "SKILL.md")
_HEADING = "## Deck capability (frontend-slides)"


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class DeckPlanningRoutingTests(unittest.TestCase):
    def _deck_section(self):
        text = _read(SKILL_MD)
        self.assertIn(_HEADING, text)
        return text.split(_HEADING, 1)[1].split("\n## ", 1)[0]

    def test_plan_step_names_the_frontend_slides_design_docs(self):
        deck = self._deck_section()
        self.assertIn("Plan first", deck)
        for ref in ("selection-index.json", "STYLE_PRESETS.md", "html-template.md", "animation-patterns.md"):
            self.assertIn(ref, deck, f"deck section must name {ref} for planning")

    def test_planning_happens_before_scaffolding(self):
        deck = self._deck_section()
        self.assertRegex(deck.lower(), r"before scaffolding")

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
