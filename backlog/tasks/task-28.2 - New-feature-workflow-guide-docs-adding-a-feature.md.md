---
id: TASK-28.2
title: New-feature workflow guide (docs/adding-a-feature.md)
status: Done
assignee: []
created_date: '2026-07-15 04:58'
updated_date: '2026-07-15 06:20'
labels: []
dependencies:
  - TASK-28.1
parent_task_id: TASK-28
ordinal: 26000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Add a repo-tracked guide that captures the full end-to-end workflow for adding a new commentable-html feature, so future additions follow one checklist instead of rediscovering the rules. It must cover: backlog-first task tracking, fresh worktree off origin/main, TDD (red-then-green), the spec-and-test discipline (AREA-NN feature id row naming a covering test), the split-partial edit rule (no monolith), minimal SKILL.md plus an on-demand reference doc, the scaffold+apply tool pattern for round-trippable state, wiring into the shared layers (sidebar card, Copy-all bundle, export bake, mode badge), rebuilding generated artifacts (rebuild_all), version bump + changelog, and the validate/pre-push gates. Link it from AGENTS.md so it is discoverable.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 docs/adding-a-feature.md exists and walks through the full workflow end to end in order
- [x] #2 It uses the notes feature as the worked example and points at the split partials, tools, reference, SPEC, and tests it touched
- [x] #3 AGENTS.md links to the new guide from its Common tasks / spec-and-test sections
- [x] #4 validate_markdown.py passes on the new doc (plain ASCII, no em/en dashes, LF)
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Per user comment 3, docs/adding-a-feature.md must ALSO include these steps (in order): after implementing + wiring, (1) ADD a new demo/example report for the feature OR extend an existing one (dev/examples/src + built examples/ + build.py --check), and (2) RUN the E2E Playwright audit against that demo to confirm every interaction works before shipping. So the guide's ordered checklist is: backlog-first task; fresh worktree off origin/main; write the failing test first (red); add the AREA-NN SPEC row naming that test; edit the owning split partial (no monolith); wire the shared layers (sidebar card + click branch, Copy-all bundle + gates, export bake x4, mode badge, startup open, startup ORDERING vs offsets); add scaffold+apply tools + on-demand reference doc; one-line SKILL.md; ADD/EXTEND A DEMO; RUN THE E2E PLAYWRIGHT AUDIT ON THE DEMO; bump dev/VERSION + CHANGELOG (+ plugin.json/marketplace equality); regenerate all artifacts (scripts/rebuild_all.py) incl. Playwright fixtures (version embed) + MODULES.md entries + file-inventory; run validators + rebuild_all --check + pre-push gate. Link from AGENTS.md (spec-and-test + Common tasks). Must pass validate_markdown.py (plain ASCII, no em/en dashes, repo-relative paths only).
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Shipped in PR #148: docs/adding-a-feature.md, the end-to-end new-feature workflow checklist (backlog-first, worktree, TDD + spec rows, split-partial edit + shared-layer wiring, scaffold+apply tools + reference doc, coverage gates, demo + E2E audit, version/changelog/rebuild/validate), using the notes field as the worked example. Linked from AGENTS.md Common tasks and docs/README.md; validate_markdown clean.
<!-- SECTION:FINAL_SUMMARY:END -->
