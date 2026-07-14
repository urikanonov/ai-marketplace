---
id: TASK-19
title: 'Deck: fix dark slide code, KQL, and diff contrast'
status: Done
assignee:
  - '@me'
created_date: '2026-07-14 20:52'
updated_date: '2026-07-14 21:03'
labels: []
dependencies: []
ordinal: 17000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Requested as TASK-25, but TASK-25 was not present in this worktree or origin/main. Fix the deck dark theme so code, KQL, and diff blocks use coherent dark surfaces and readable syntax colors on deck slides instead of inheriting light-default card surfaces.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Deck theme partial scopes code, KQL, and diff styles under deck slides.
- [x] #2 A Playwright contrast test covers deck-mode code or diff text against its computed background.
- [x] #3 Generated artifacts rebuild clean and validators pass.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Inspect 90-deck.css, 40-diff.css, 70-kql.css, and code CSS to confirm which --cp-* variables and token colors make dark deck code, KQL, and diff surfaces illegible.\n2. Add deck-scoped theme overrides in dev/assets/css/90-deck.css for code, KQL, and diff blocks, including readable dark surfaces, syntax tokens, and add/delete row tints.\n3. Add a CMH-DECK spec row and Playwright contrast test against the showcase deck in deck mode.\n4. Rebuild generated artifacts, run targeted tests, deck validation, rebuild_all --check, marketplace and Markdown validation, then commit and force-push PR #140.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Confirmed root cause: deck slides set light slide text at the slide scope while the document root still carries light --cp-* variables, so pre/KQL/diff backgrounds resolved to light --cp-bg-elevated or --cp-surface and inherited near-white slide text. Added deck-scoped dark code, KQL, and diff theme rules in 90-deck.css and verified computed styles on the showcase deck.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Fixed dark deck slide contrast for code, KQL, and diff blocks with deck-scoped theme rules in 90-deck.css, added CMH-DECK-11 and a Playwright contrast test, rebuilt artifacts, and validated with rebuild_all --check, validators, deck_validate --strict, and deck regression tests.
<!-- SECTION:FINAL_SUMMARY:END -->
