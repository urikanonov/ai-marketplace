---
id: TASK-41
title: Add an Install link to the commentable-html page top nav
status: In Progress
assignee:
  - '@me'
created_date: '2026-07-15 09:52'
updated_date: '2026-07-15 09:56'
labels: []
dependencies: []
ordinal: 34000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The commentable-html plugin page has an #install section but the top navbar (Features, Try it, Privacy, Tutorial, Changelog, GitHub, Marketplace) has no Install link, so users cannot jump to it from the nav.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 The commentable-html page top nav includes an Install link that targets #install and is always visible (not hidden on small screens)
- [ ] #2 A SITE-PLUGIN spec row and a covering Playwright test assert the nav Install link exists and points to #install
- [ ] #3 build_site_data.py --check is clean and the site suite + generator tests pass
- [ ] #4 The auto-updater callout in the CMH Install section is a clearly-visible card (not plain muted text) that shows the auto-updater plugin icon
- [ ] #5 On the auto-updater page Why section, the urikan-ai-marketplace text links to the marketplace hub page (../)
- [ ] #6 On the auto-updater page Install section, the PowerShell prerequisite note is visibly spaced below the command box (not cramped against it)
<!-- AC:END -->



## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. CMH page: add an Install nav link to #install (always visible). 2. CMH Install section: replace the plain install-note paragraph with a clearly-visible callout card (whole-card link to ../urikan-ai-marketplace-auto-updater/) showing the updater icon + title + description; add .install-updater-cta CSS to site/css/32-install.css. 3. Auto-updater page Why section: link the urikan-ai-marketplace code text to ../ (hub). 4. Tests first (RED): add SITE-PLUGIN-17 nav Install test; extend SITE-UPDATER-06 to assert the callout icon; add SITE-UPDATER-07 for the updater-page marketplace link; update SPEC.md rows. 5. Rebuild site, run site suite + generator tests + validators + --check.
<!-- SECTION:PLAN:END -->
