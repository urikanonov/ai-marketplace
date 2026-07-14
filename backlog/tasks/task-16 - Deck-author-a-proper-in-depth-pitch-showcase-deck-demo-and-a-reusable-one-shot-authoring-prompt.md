---
id: TASK-16
title: >-
  Deck: author a proper in-depth pitch/showcase deck demo and a reusable
  one-shot authoring prompt
status: Done
assignee:
  - '@me'
created_date: '2026-07-14 17:21'
updated_date: '2026-07-14 22:09'
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
- [x] #1 A reusable one-shot authoring prompt is committed (e.g. under the plugins examples) that, given to an agent, produces a good full showcase deck in one pass; the prompt enumerates the features to cover and the required slide structure
- [x] #2 A properly themed showcase/pitch deck is generated and wired in as the deck demo on the site (replacing the current weak deck), with legible theme, working drag-and-drop triage slide, and correctly rendered Mermaid
- [x] #3 The deck demonstrates the breadth of commentable-html features listed in the description and is itself commentable (present and comment modes both work)
- [x] #4 Example/source lives under dev/ (examples-src or examples) and the shipped/site copies are rebuilt via python scripts/rebuild_all.py with --check clean
- [x] #5 Add feature-id rows in plugins/commentable-html/dev/SPEC.md and tests/site/SPEC.md naming covering tests (deck renders/mounts; demo tab loads it); bump plugin version and update CHANGELOG.md
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Replace the weak roadmap deck with a new showcase deck source at dev/examples/src/deck-showcase.html, scaffolded through the deck tools and rebuilt into shipped examples and site demos.
2. Add examples/prompt-showcase.md as a reusable one-shot prompt. Required slide outline: 1 title promise, 2 broken review loop/problem, 3 comment-on-anything map, 4 rich content matrix, 5 live chart/table/media surface, 6 Mermaid architecture, 7 diff/code/KQL review, 8 drag-and-drop triage board, 9 layered checklist, 10 Copy all to agent, 11 handled pruning/reload, 12 export modes, 13 privacy/offline, 14 deck mode/navigation, 15 tooling and validator, 16 close/ask.
3. Wire deck-showcase.html into build_site_data.py and the plugin page live-demo tab list, removing deck-roadmap.html as the deck demo.
4. Add CMH-DECK-SHOWCASE, SITE-DEMO, and CMH-DECK-13 spec rows plus tests proving the shipped showcase deck validates, mounts in deck mode, is commentable, has working board/Mermaid/chart/diff/checklist content, keeps dark-slide code/KQL/diff token contrast, and the site tab loads it.
5. Set commentable-html version lane to 1.58.0, add the changelog entry, rebuild all generated artifacts, run deck validation, targeted tests, rebuild_all --check, validate_marketplace.py, and validate_markdown.py.
<!-- SECTION:PLAN:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Implemented the showcase deck, one-shot prompt, site demo wiring, specs, tests, 1.58.0 re-lane, changelog, and regenerated artifacts. Folded in the deck-theme fix so dark-slide code, KQL, and diff blocks use dark surfaces, distinct AA-contrast syntax tokens, and readable diff row tints. Verified with rebuild_all, rebuild_all --check, validate_marketplace.py, validate_markdown.py, deck_validate --strict, python plugins/commentable-html/dev/tests/test_deck_example.py, and npx playwright test 62-deck-regressions.spec.js.
<!-- SECTION:FINAL_SUMMARY:END -->
