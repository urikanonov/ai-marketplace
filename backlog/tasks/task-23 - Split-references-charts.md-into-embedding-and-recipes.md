---
id: TASK-23
title: Split references/charts.md into embedding and recipes
status: To Do
assignee: []
created_date: '2026-07-15 00:10'
labels: []
dependencies: []
ordinal: 21000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Audit lane-3 finding: charts.md (~25KB) is the largest on-demand reference. Split into charts-embedding.md (dependencies, the four rules, minimal recipe, tooltip options) and charts-recipes.md (per-chart-type recipes, data hygiene, dark theme), updating pointers, so an agent fixing a chart does not load 10KB of unrelated variations.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 charts.md content is split into two focused references with correct pointers
<!-- AC:END -->
