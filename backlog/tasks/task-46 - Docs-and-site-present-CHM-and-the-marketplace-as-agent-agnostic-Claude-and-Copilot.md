---
id: TASK-46
title: >-
  Docs and site: present CHM and the marketplace as agent-agnostic (Claude and
  Copilot)
status: To Do
assignee: []
created_date: '2026-07-15 10:12'
labels: []
dependencies: []
ordinal: 39000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
With the Claude adaptation landed, CHM installs in Claude Code as well as the Copilot CLI. Update the site plugin + hub pages, plugin READMEs, and the tutorial to present CHM and the marketplace as working with both agents, with install/usage guidance for each. Depends on the Claude adaptation PR.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Site plugin + hub pages present CHM as working with Claude and Copilot, with install for both
- [ ] #2 READMEs and tutorial updated where Copilot-specific
- [ ] #3 site tests/SPEC updated; build_site_data --check clean; version bump where a plugin changes
<!-- AC:END -->
