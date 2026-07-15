---
id: TASK-38
title: >-
  Add a dedicated auto-updater plugin site page, icon, and link it from CMH
  Install
status: In Progress
assignee:
  - '@me'
created_date: '2026-07-15 09:07'
updated_date: '2026-07-15 09:34'
labels: []
dependencies: []
ordinal: 33000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The auto-updater plugin has no site page: on the hub its card is linkless and it only links to the GitHub source. Give it a first-class marketing page (full pitch), a dedicated brand icon in the crimson theme, wire it into the generator/JSON-LD/sitemap/llms, and reference it from the commentable-html page Install section so readers can opt into auto-updates.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 A dedicated auto-updater page is generated at site/dist/urikan-ai-marketplace-auto-updater/index.html with a full pitch and is linked from the hub (card title + Learn more) and included in sitemap.xml, llms.txt, and hub JSON-LD
- [x] #2 A dedicated auto-updater icon SVG in the crimson (#b11f4b) theme is added under site/src and used as the page favicon and hero logo
- [x] #3 The commentable-html page Install section references the auto-updater page and explains it keeps the plugin auto-updated
- [x] #4 New SITE-UPDATER spec rows and covering tests exist; SITE-HUB-06 linkless-card coverage is updated; build_site_data.py --check is clean and the site Playwright suite and generator unit tests pass
<!-- AC:END -->



## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Add crimson-theme icon site/src/urikan-ai-marketplace-auto-updater.svg (circular refresh, white+pink two-tone). 2. Create page source site/pages/urikan-ai-marketplace-auto-updater/index.html: tight CSP, canonical/OG/Twitter, SoftwareApplication+BreadcrumbList JSON-LD, nav, hero with version marker, full-pitch sections, footer. 3. Generalize scripts/build_site_data.py: add page to PLUGIN_PAGES, build+version-fill, require source, add --check drift. 4. Edit CMH page Install section to reference the auto-updater page. 5. Tests first (RED): SITE-UPDATER spec rows + Playwright + generator unit tests; update SITE-HUB-06 linkless test and crawl lists. 6. Regenerate site and run rebuild_all --check + suites + validators.
<!-- SECTION:PLAN:END -->
