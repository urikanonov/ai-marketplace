---
id: TASK-48
title: >-
  Auto-wrap report/plan top-level <h2> blocks in <section> cards (the deterministic
  fix for the CMH-VAL-14 flat-section warning)
status: Done
assignee:
  - '@me'
created_date: '2026-07-15 08:10'
updated_date: '2026-07-15 09:30'
labels: []
dependencies: []
ordinal: 34000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The validator warns (CMH-VAL-14, `check_section_wrapping`) when a `report`/`plan`/`generic` document has two or more bare top-level `<h2>` headings and no `<section>`, because it renders flat with no boxed section cards (`#commentRoot > section`). That warning tells an author what is wrong but leaves them to hand-wrap every block. This task adds the deterministic auto-fix so the card layout is automatic and guided, not a manual chore: wrap the blocks at create/finalize time for the card-rendering kinds.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 `tools/authoring/wrap_sections.py` wraps each bare top-level `<h2>` block (heading plus following siblings up to the next top-level `<h2>`) in `<section aria-labelledby="the-h2-id">`, leaves the title/lede above the cards, is idempotent, and is a no-op when a top-level `<section>` already exists or there is no top-level `<h2>`
- [x] #2 `new_document.py` (report/plan fragments) and `finalize.py` (full docs, gated on the kind meta) run the wrap by default, with a `--no-wrap-sections` opt-out
- [x] #3 SPEC row CMH-TOOL-17 names covering tests; SKILL.md documents the tool; the tools-layout registry lists it; new `test_wrap_sections.py` plus finalize/new_document cases; full Python suite green
- [x] #4 `build.py` re-stamps the version into the Claude manifests (`.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json`) as well as the Copilot ones, so a version bump never leaves the Claude mirror behind (covered by `test_source_stamps_include_claude_manifests`)
- [x] #5 Version bump + CHANGELOG entry; build.py restamp and `--check` clean; fixtures and site data regenerated
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Complements the validator warning shipped in PR #155 (`check_section_wrapping`, CMH-VAL-14) - the warning detects the flat case, this task makes the fix automatic. `wrap_sections.py`: `wrap_fragment(html)` for the create path (bare fragment) and `fix(html)` for the finalize path (an `HTMLParser` depth locator scopes to the `#commentRoot` element, never the layer shell); both idempotent, no-op when a top-level `<section>` exists, comment/script/string safe like `fix_skip.py`. Default-on wiring: `new_document.py` runs `wrap_fragment` after `ensure_doc_title` for report/plan kinds (title stays above the cards); `finalize.py` runs `fix` after the TOC step (so `<h2>` ids exist for `aria-labelledby`), gated on the kind meta. Scoped to report/plan (a `generic` doc that trips the warning is left as authored - auto-carding freeform content could be wrong; the author gets the warning to fix manually). `--no-wrap-sections` opt-out on both. Registered in `test_tools_layout.EXPECTED`. Separately, `build.py.source_stamps` now also stamps the Claude manifests (they mirror the Copilot ones), fixing a latent gap where each bump left `.claude-plugin/plugin.json` behind and required a manual bump.
<!-- SECTION:NOTES:END -->
