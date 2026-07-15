---
id: TASK-50
title: >-
  Claude support sweep: dual Claude/Copilot messaging + tabbed split install
  commands
status: Done
assignee: []
created_date: '2026-07-15 13:05'
updated_date: '2026-07-15 15:09'
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
- [x] #1 README, the .github/plugin/marketplace.json metadata description, and every site surface (hub hero/eyebrow, plugin pages, meta descriptions, JSON-LD operatingSystem, llms.txt) state the plugins work with BOTH Claude Code and the GitHub Copilot CLI, not Copilot-only
- [x] #2 SKILL.md and the commentable-html site page state the skill is invokable from both the CLI and the Desktop apps
- [x] #3 Every plugin install block on the site (hub plugin cards and each plugin page) is a tabbed UI switching between a Copilot tab and a Claude tab, with the marketplace-add command and the plugin-install command on SEPARATE rows, each row carrying its own copy button
- [x] #4 The Claude tab appears only for Claude-supported plugins (commentable-html); the auto-updater (Claude support tracked separately) shows only the Copilot install path and does not advertise a Claude one
- [x] #5 New/updated spec rows in plugins/commentable-html/dev/SPEC.md and site/tests/SPEC.md name covering tests (generator unit tests in scripts/test_build_site_data.py, Playwright specs in site/tests, and the SKILL.md docs test), and all generated artifacts are rebuilt in sync so site --check, dist-in-sync, and fixtures --check pass
<!-- AC:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Shipped in PR #226 (v1.77.0). Dual Claude Code + GitHub Copilot messaging across README, marketplace metadata, SKILL.md, and the site (hub/plugin pages, meta, per-plugin JSON-LD operatingSystem, llms.txt). New tabbed (Copilot/Claude), split-row (Install marketplace / Install plugin) install UI with a copy button per row, via data-driven render_install(); Claude tab only for plugins in .claude-plugin/marketplace.json (auto-updater stays Copilot-only, tracked as TASK-51). Covered by CMH-DOC-12, SITE-INSTALL-01..04, SITE-DUAL-01. Hardened over two multi-duck review rounds (per-plugin support, id slugging, malformed-manifest robustness, restored a rebase-clobbered SKILL.md bullet).
<!-- SECTION:FINAL_SUMMARY:END -->
