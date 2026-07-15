---
id: TASK-56
title: >-
  Site: unify footers so tutorial and updater pages match the commentable-html
  page footer
status: To Do
assignee: []
created_date: '2026-07-15 13:09'
labels: []
dependencies: []
ordinal: 45000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The commentable-html page footer (site/pages/commentable-html/index.html) has Contribute / Request a feature / File an issue / Plugin source links. The tutorial page (site/pages/commentable-html/tutorial/index.html) has a minimal footer (source: TUTORIAL.md) and the auto-updater page (site/pages/urikan-ai-marketplace-auto-updater/index.html) should match too. Make the tutorial and updater footers consistent with the commentable-html page footer, adjusting the per-page Plugin source link as appropriate; if footers are templated in the generator, unify there.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 The tutorial page footer matches the commentable-html page footer style and links
- [ ] #2 The updater page footer matches the commentable-html page footer style and links (with its own plugin-source link)
- [ ] #3 A SITE-NN spec row and a covering site test are added
<!-- AC:END -->
