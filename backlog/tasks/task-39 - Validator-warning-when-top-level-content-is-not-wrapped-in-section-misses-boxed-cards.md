---
id: TASK-39
title: >-
  Validator warning when top-level content is not wrapped in <section> (misses
  boxed cards)
status: In Progress
assignee:
  - '@urikanonov'
created_date: '2026-07-15 09:21'
updated_date: '2026-07-15 09:29'
labels: []
dependencies: []
ordinal: 33000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
A commentable-html document whose content uses bare top-level h2 headings instead of <section aria-labelledby> wrappers passes validate.py --strict but renders without the boxed section-card styling (#commentRoot > section), producing a flat off-brand doc. Add a non-fatal validator warning when #commentRoot has multiple top-level headings but no top-level <section> wrappers.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 validate.py warns (non-fatal) when #commentRoot has 2+ top-level h2 and zero top-level <section> wrappers
- [x] #2 No warning when sections are used, or for a deck / single-heading doc
- [x] #3 SPEC row + test; version bump + CHANGELOG
<!-- AC:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
validate.py now warns when a report/plan/generic doc has 2+ top-level h2 with no <section> wrapper (misses the boxed cards). check_section_wrapping in checks/kind.py, wired in layer.py; CMH-VAL-14 + test_section_wrapping.py; v1.69.0.
<!-- SECTION:FINAL_SUMMARY:END -->
