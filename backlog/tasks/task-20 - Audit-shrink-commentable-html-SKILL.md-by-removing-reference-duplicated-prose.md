---
id: TASK-20
title: 'Audit: shrink commentable-html SKILL.md by removing reference-duplicated prose'
status: Done
assignee:
  - '@me'
created_date: '2026-07-14 22:44'
updated_date: '2026-07-14 23:38'
labels: []
dependencies: []
ordinal: 18000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Reduce the always-loaded commentable-html skill entry by replacing guidance that already exists in on-demand references with concise pointers, while preserving required always-on routing and invariants.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 SKILL.md keeps the tool router, trust boundary, strict validation requirement, minimal iteration loop, and unique deck invariants.
- [x] #2 Sections duplicated by existing references are replaced with concise pointers to those reference docs.
- [x] #3 commentable-html is bumped to 1.59.0 with a changelog entry unless main already uses that version.
- [x] #4 python scripts/rebuild_all.py, python scripts/rebuild_all.py --check, python scripts/validate_marketplace.py, and python scripts/validate_markdown.py pass.
- [x] #5 Final report includes before and after SKILL.md byte size plus percent reduction.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Verify deck and upgrade tool behavior against shipped tool code.
2. Move the missing deck design/font, deck command/limitation, and upgrade-safety guidance into references without expanding SKILL.md beyond pointers.
3. Run rebuild_all --check, marketplace validation, markdown validation, amend the PR commit, and force-push.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Verified references before collapsing duplicated SKILL.md sections. Validation passed: python scripts/rebuild_all.py; python scripts/rebuild_all.py --check; python scripts/validate_marketplace.py; python scripts/validate_markdown.py.

Follow-up relocated missing cut guidance into references: deck design/font mapping and deck commands/PPTX limits in deck-contract.md; upgrade --check and JS marker warning in retrofitting.md. Verified actual flags with tool --help and code inspection. Validation passed: python scripts/rebuild_all.py --check; python scripts/validate_marketplace.py; python scripts/validate_markdown.py; python -m unittest discover -s plugins\\commentable-html\\dev\\tests -p test_*.py.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Shrank the commentable-html SKILL.md entry point from 37226 bytes to 18148 bytes while keeping always-on routing, validation, trust-boundary, iteration-loop, and deck invariants. Relocated the removed deck design/font, deck command/PPTX, and upgrade-safety guidance into on-demand references; bumped commentable-html to 1.59.0 and regenerated artifacts.
<!-- SECTION:FINAL_SUMMARY:END -->
