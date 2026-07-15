---
id: TASK-43
title: >-
  Move the auto-updater CHANGELOG above pkg and add a minimal root README,
  mirroring commentable-html
status: In Progress
assignee:
  - '@me'
created_date: '2026-07-15 10:00'
updated_date: '2026-07-15 10:01'
labels: []
dependencies: []
ordinal: 36000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The auto-updater ships its CHANGELOG.md inside pkg/ (distributed to users). commentable-html keeps CHANGELOG.md and a minimal README.md at the plugin ROOT (not shipped) with pkg/ and dev/ below. Mirror that layout for the auto-updater: move the changelog out of pkg and add a minimal root README describing the pkg/dev split.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 plugins/urikan-ai-marketplace-auto-updater/CHANGELOG.md lives at the plugin root (not inside pkg/), and check_changelog_sync still enforces it
- [ ] #2 A minimal plugins/urikan-ai-marketplace-auto-updater/README.md exists at the root, mirroring commentable-html's root README (describes pkg/ and dev/)
- [ ] #3 The auto-updater plugin version is bumped in pkg/plugin.json and the manifest with a matching CHANGELOG entry; validators pass
<!-- AC:END -->
