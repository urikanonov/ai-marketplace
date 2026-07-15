---
id: TASK-38
title: Route deck planning to the vendored frontend-slides design system in SKILL.md
status: In Progress
assignee:
  - '@urikanonov'
created_date: '2026-07-15 09:13'
updated_date: '2026-07-15 09:20'
labels: []
dependencies: []
ordinal: 33000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The commentable-html SKILL.md deck section points at vendor/frontend-slides only implicitly. When a user asks to PLAN or design a deck, the agent should be told to consult the vendored frontend-slides design system (selection-index.json, STYLE_PRESETS.md, html-template.md, animation-patterns.md) to choose a theme and slide structure BEFORE scaffolding. Add an explicit Plan step.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 SKILL.md deck section instructs consulting vendor/frontend-slides during planning (structure + theme), before scaffolding
- [x] #2 A SPEC feature-id row names an automated string-presence test for the routing text
- [x] #3 Version bump + CHANGELOG
<!-- AC:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
SKILL.md deck section now routes planning to frontend-slides (Plan first step); CMH-DECK-14 + test_deck_planning_routing.py; v1.68.0. PR #154.
<!-- SECTION:FINAL_SUMMARY:END -->
