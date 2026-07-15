---
id: TASK-45
title: >-
  Deck exports on a slides-kind deck: verify + test Portable, Offline, Plain
  HTML, and Markdown
status: To Do
assignee: []
created_date: '2026-07-15 10:12'
updated_date: '2026-07-15 10:15'
labels: []
dependencies:
  - TASK-42
ordinal: 38000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
task-16 requires all four export destinations and the plan disambiguates portability (single-file) from the network model. Verify each export works correctly on a slides-kind deck (Portable inlines the layer; Offline snapshots mermaid/charts and is zero-network; Plain HTML strips the layer keeping styling; Markdown is a structural export) and add covering tests, including an Offline reopen-with-network-disabled check.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Portable, Offline, Plain HTML, and Markdown exports each verified on a deck with covering tests
- [ ] #2 Offline export reopens and validates with the network disabled
<!-- AC:END -->
