---
id: TASK-44
title: >-
  Deck one-shot authoring prompt: dev-side source + fresh-session
  reproducibility smoke test
status: To Do
assignee: []
created_date: '2026-07-15 10:12'
updated_date: '2026-07-15 10:15'
labels: []
dependencies:
  - TASK-42
ordinal: 37000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Give examples/prompt-showcase.md a dev-side source and a fresh-session smoke test that regenerates the deck in one pass and passes deck_validate --strict + rebuild_all --check, so task-16 AC#1 (single-pass reproduction) is verified rather than asserted. The prompt must enumerate the exact outline, theme tokens, constraints, running example, and cwd-safe commands.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 prompt-showcase.md has an independent dev-side source and is checked in the build
- [ ] #2 A smoke test proves the prompt regenerates a valid deck (deck_validate --strict) and rebuild_all --check stays clean
<!-- AC:END -->
