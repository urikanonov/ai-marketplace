---
id: TASK-24
title: Add deck_fix_fonts.py to deterministically map web fonts to system stacks
status: To Do
assignee: []
created_date: '2026-07-15 00:10'
labels: []
dependencies: []
ordinal: 22000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Audit lane-2 finding: the deck font-override mapping is a manual 5-bucket transform narrated in the skill (now in deck-contract.md). The deck validator rejects remote fonts but cannot fix them. Add tools/deck/deck_fix_fonts.py (or a deck_scaffold --map-fonts mode) that strips remote link/@import/@font-face and rewrites each font-family to the prescribed system stack (serif->Iowan; slab/display->Impact; geometric->system-ui; mono->Cascadia; CJK->drop), validated by deck_validate.py, so the mapping becomes deterministic and the prose shrinks further.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 deck_fix_fonts rewrites remote/web fonts to the prescribed system stacks and strips remote loaders
- [ ] #2 Output passes deck_validate.py; tests cover the mapping and remote-strip
<!-- AC:END -->
