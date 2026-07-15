---
id: TASK-50
title: >-
  Claude support sweep: dual Claude/Copilot messaging + tabbed split install
  commands
status: To Do
assignee: []
created_date: '2026-07-15 13:05'
labels: []
dependencies: []
ordinal: 41000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
commentable-html is already installable in Claude Code (PR #153), but README, the marketplace manifest metadata, SKILL.md, and the whole GitHub Pages site still present the marketplace as GitHub-Copilot-only. Claude Code users cannot tell these plugins work for them, and the install snippets show only the copilot commands. This sweep makes the dual-agent support visible everywhere and redesigns the install command block into a tabbed (Copilot / Claude), split-row (Install Marketplace / Install Plugin) UI with a copy button per row, inspired by the reference mock.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 README, the .github/plugin/marketplace.json metadata description, and every site surface (hub hero/eyebrow, plugin pages, meta descriptions, JSON-LD operatingSystem, llms.txt) state the plugins work with BOTH Claude Code and the GitHub Copilot CLI, not Copilot-only
- [ ] #2 SKILL.md and the commentable-html site page state the skill is invokable from both the CLI and the Desktop apps
- [ ] #3 Every plugin install block on the site (hub plugin cards and each plugin page) is a tabbed UI switching between a Copilot tab and a Claude tab, with the marketplace-add command and the plugin-install command on SEPARATE rows, each row carrying its own copy button
- [ ] #4 The Claude tab appears only for Claude-supported plugins (commentable-html); the auto-updater (Claude support tracked separately) shows only the Copilot install path and does not advertise a Claude one
- [ ] #5 New/updated spec rows in plugins/commentable-html/dev/SPEC.md and site/tests/SPEC.md name covering tests (generator unit tests in scripts/test_build_site_data.py, Playwright specs in site/tests, and the SKILL.md docs test), and all generated artifacts are rebuilt in sync so site --check, dist-in-sync, and fixtures --check pass
<!-- AC:END -->
