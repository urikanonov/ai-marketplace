---
id: TASK-36
title: >-
  Investigate Claude support for the marketplace, skill install, and
  auto-updater
status: In Progress
assignee:
  - '@urikanonov'
created_date: '2026-07-15 08:19'
updated_date: '2026-07-15 08:52'
labels: []
dependencies: []
ordinal: 33000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
commentable-html output is a portable HTML artifact that works with any agent, but the marketplace/install and the session-start auto-updater hook are GitHub Copilot CLI specific today. Investigate whether Claude Code can consume this marketplace / install the skill, and whether a Claude equivalent of the auto-updater hook exists, so task-36/38 messaging is accurate. Conclude feasible or not with the exact commands, or document the gap.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Documented whether Claude Code can install commentable-html from this marketplace, with exact commands if so
- [x] #2 Documented whether a Claude session-start auto-update path exists
- [x] #3 Findings recorded so task-36/38 can state install accurately
- [x] #4 A locally runnable test/script validates a plugin's Claude compatibility (wraps 'claude plugin validate'), runnable without network
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Add .claude-plugin/plugin.json (mirror Copilot fields, skills=./skills/) + repo-root .claude-plugin/marketplace.json (commentable-html). 2. Add scripts/validate_claude_compat.py (structural + live claude plugin validate --strict) and its unit test. 3. Add commentable-html CMH-CLAUDE-01 SPEC row + test_claude_manifest.py. 4. Bump 1.66.0, rebuild, validate. Verified end-to-end: claude plugin marketplace add + install discovered the skill. Auto-updater Claude support split to its own task.
<!-- SECTION:PLAN:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Made commentable-html installable in Claude Code (PR #153): shipped .claude-plugin/plugin.json + repo-root .claude-plugin/marketplace.json, added scripts/validate_claude_compat.py (wraps 'claude plugin validate --strict', skips live check when the CLI is absent) + tests + CMH-CLAUDE-01, v1.67.0. Verified end-to-end against real Claude Code 2.1.210 (marketplace add + install discovered the skill). Auto-updater Claude support split to task-37.
<!-- SECTION:FINAL_SUMMARY:END -->
