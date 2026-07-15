---
id: TASK-37
title: Adapt the auto-updater plugin for Claude Code (manifest + SessionStart hook)
status: To Do
assignee: []
created_date: '2026-07-15 08:41'
labels: []
dependencies: []
ordinal: 34000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The urikan-ai-marketplace-auto-updater ships a Copilot-format hooks.json (sessionStart, bash/powershell keys). Claude Code supports a SessionStart hook but with a different hooks.json shape (PascalCase events, command type, matcher). Add a .claude-plugin/plugin.json and a Claude-format hooks config so the auto-updater installs AND auto-updates under Claude, then add the auto-updater to .claude-plugin/marketplace.json. Split out from the commentable-html Claude adaptation.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 auto-updater ships a .claude-plugin/plugin.json validated by claude plugin validate --strict
- [ ] #2 A Claude SessionStart hook runs the marketplace update non-blocking; pwsh tests cover it
- [ ] #3 auto-updater added to .claude-plugin/marketplace.json; validate_claude_compat.py passes; version bump + changelog
<!-- AC:END -->
