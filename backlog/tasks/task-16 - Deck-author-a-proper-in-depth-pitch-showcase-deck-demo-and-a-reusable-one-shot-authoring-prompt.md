---
id: TASK-16
title: >-
  Deck: author a proper in-depth pitch/showcase deck demo and a reusable
  one-shot authoring prompt
status: To Do
assignee: []
created_date: '2026-07-14 17:21'
labels: []
dependencies:
  - TASK-7
  - TASK-8
  - TASK-9
ordinal: 15000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The current sample/demo deck is low quality and has no proper theme. Deliver two things: (1) a carefully written, reusable one-shot prompt that instructs an AI agent to generate a strong commentable deck in a single pass - walking through the plugins features (comment on anything, rich content: Chart.js, Mermaid, drag-and-drop triage board, code/KQL diffs, checklist; round-trip to agent; Portable/Offline/Plain/Markdown exports; handled-comment pruning; deck present/comment modes and navigation; privacy/offline story); and (2) the generated showcase deck itself, properly themed, that pitches and demonstrates commentable-html in depth and replaces the current weak demo deck on the site. Plan the deck structure (slide outline) before writing the prompt. The showcase deck must be built on a fixed deck engine, so it depends on the drag-drop, Mermaid, and theme-contrast fixes.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 A reusable one-shot authoring prompt is committed (e.g. under the plugins examples) that, given to an agent, produces a good full showcase deck in one pass; the prompt enumerates the features to cover and the required slide structure
- [ ] #2 A properly themed showcase/pitch deck is generated and wired in as the deck demo on the site (replacing the current weak deck), with legible theme, working drag-and-drop triage slide, and correctly rendered Mermaid
- [ ] #3 The deck demonstrates the breadth of commentable-html features listed in the description and is itself commentable (present and comment modes both work)
- [ ] #4 Example/source lives under dev/ (examples-src or examples) and the shipped/site copies are rebuilt via python scripts/rebuild_all.py with --check clean
- [ ] #5 Add feature-id rows in plugins/commentable-html/dev/SPEC.md and tests/site/SPEC.md naming covering tests (deck renders/mounts; demo tab loads it); bump plugin version and update CHANGELOG.md
<!-- AC:END -->
