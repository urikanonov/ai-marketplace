---
id: TASK-6
title: 'Site: add a Checklist demo to the Try it live tabs'
status: In Progress
assignee:
  - '@me'
created_date: '2026-07-14 17:19'
updated_date: '2026-07-14 18:31'
labels: []
dependencies: []
ordinal: 5000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The Try it live tab strip on the commentable-html site page (site-src/pages/commentable-html/index.html: demo-tab buttons) exposes NYC Taxi Report, Community Garden Plan, Triage Board, and Visuals Matrix, but there is no demo showing the layered checklist feature (data-cmh-checklist). Add a fifth demo report that showcases checklist mode so visitors can try it live.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 A new example report exercising checklist mode exists under plugins/commentable-html/dev/examples-src/ and is built into the shipped pkg examples and the site demo/ folder
- [x] #2 A new Checklist demo tab appears in the Try it live tab strip and loads the checklist report in the iframe
- [x] #3 The new tab is added after the existing tabs and does not regress the lazy-loaded demo iframe (SITE-PLUGIN-04 still passes)
- [x] #4 Edit the site source under site-src/ and example source under dev/examples-src/, rebuild via python scripts/build_site_data.py plus the layer build.py, and confirm both --check gates are clean
- [x] #5 Add feature-id rows and covering tests: a tests/site/SPEC.md row for the new tab and a plugin SPEC row if new example content is added
<!-- AC:END -->



## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Trace how report-checklist.html is built into shipped examples and site demos. 2. Add a Checklist Try it live tab after the existing tabs without moving the demo iframe. 3. Add the site spec row and Playwright coverage for the new tab. 4. Rebuild generated site artifacts, validate checks, commit, push, and open the PR.
<!-- SECTION:PLAN:END -->
