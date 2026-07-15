---
id: TASK-51
title: Make the auto-updater installable and functional in Claude Code
status: To Do
assignee: []
created_date: '2026-07-15 13:05'
labels: []
dependencies: []
ordinal: 42000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
PR #153 made commentable-html installable in Claude Code but explicitly deferred the auto-updater, whose value is a session-start hook that runs 'copilot plugin update'. Claude Code uses a different plugin/hook format, so making the auto-updater actually update plugins under Claude Code needs its own design (a .claude-plugin manifest plus a Claude-compatible session-start hook, or a documented no-op). Until then the site and docs must NOT advertise a Claude install path for it (handled by the sweep task TASK-50).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 auto-updater ships a .claude-plugin manifest and appears in the repo-root .claude-plugin/marketplace.json, OR a decision is recorded that it stays Copilot-only
- [ ] #2 If shipped for Claude, its session-start update behavior works (or degrades safely) under Claude Code, covered by tests
- [ ] #3 Once functional, the site install block for the auto-updater gains a Claude tab (removing the TASK-50 carve-out) with covering tests
<!-- AC:END -->
