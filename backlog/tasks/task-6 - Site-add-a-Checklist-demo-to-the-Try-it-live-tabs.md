---
id: TASK-6
title: 'Site: add a Checklist demo to the Try it live tabs'
status: To Do
assignee: []
created_date: '2026-07-14 17:19'
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
- [ ] #1 A new example report exercising checklist mode exists under plugins/commentable-html/dev/examples-src/ and is built into the shipped pkg examples and the site demo/ folder
- [ ] #2 A new Checklist demo tab appears in the Try it live tab strip and loads the checklist report in the iframe
- [ ] #3 The new tab is added after the existing tabs and does not regress the lazy-loaded demo iframe (SITE-PLUGIN-04 still passes)
- [ ] #4 Edit the site source under site-src/ and example source under dev/examples-src/, rebuild via python scripts/build_site_data.py plus the layer build.py, and confirm both --check gates are clean
- [ ] #5 Add feature-id rows and covering tests: a tests/site/SPEC.md row for the new tab and a plugin SPEC row if new example content is added
<!-- AC:END -->
