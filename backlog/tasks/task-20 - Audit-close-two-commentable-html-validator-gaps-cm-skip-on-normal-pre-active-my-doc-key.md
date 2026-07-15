---
id: TASK-20
title: >-
  Audit: close two commentable-html validator gaps (cm-skip on normal pre;
  active my-doc key)
status: Done
assignee:
  - '@me'
created_date: '2026-07-14 22:43'
updated_date: '2026-07-14 23:51'
labels: []
dependencies: []
ordinal: 18000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Close two latent validator enforcement gaps that SKILL.md documents but validate.py does not enforce: warn when cm-skip is applied to normal code blocks, and reject active data-comment-key="my-doc" while keeping the sanctioned commented example valid.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Validator warns when a non-mermaid pre or pre code block carries cm-skip because it would not be commentable.
- [x] #2 Validator rejects an active data-comment-key of my-doc without rejecting the legitimate commented-out example.
- [x] #3 Each new behavior has a SPEC.md feature-id row and a covering red-first pytest.
- [x] #4 commentable-html is bumped to 1.60.0 with changelog and regenerated artifacts in sync.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Add a positive test proving host chrome pre.cm-skip outside #commentRoot does not warn, and tighten the active my-doc assertion phrase.
2. Scope parser collection of cm-skip code-block misuse to direct cm-skip on pre/code inside the live #commentRoot CONTENT markers only.
3. Re-run targeted validator tests, rebuild/check generated artifacts, validators, pre-push, then force-push the PR branch.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Red-first confirmation: test_normal_pre_cmskip_warns_CMH_VAL_12, test_normal_pre_code_cmskip_warns_CMH_VAL_12, and test_active_my_doc_key_is_error_CMH_VAL_13 failed before validator changes and passed after. Validation passed: targeted validator tests, full test_validate.py, scripts/rebuild_all.py --check, scripts/validate_marketplace.py, scripts/validate_markdown.py, and git diff --check.

Review follow-up: scope CMH-VAL-12 warning to code blocks directly marked cm-skip inside the live content region only; add a host-chrome positive test and tighten the my-doc assertion phrase.

Review follow-up validation: test_host_chrome_pre_cmskip_is_not_flagged_CMH_VAL_12 failed before the parser scoping fix and passed after. Targeted CMH-VAL-12/13 tests, full test_validate.py, rebuild_all.py --check, validate_marketplace.py, and validate_markdown.py passed.

Rebase follow-up: origin/main advanced to commentable-html 1.59.0 with a shrunk SKILL.md. Rebase onto origin/main, keep validator/spec/tests, keep 1.60.0, rebuild artifacts, validate, and force-push.

Rebase validation: rebased onto origin/main at commentable-html 1.59.0, resolved SKILL.md by starting from main shrink and keeping only two lean validate.py --strict pointers, rebuilt generated artifacts, and verified rebuild_all.py, rebuild_all.py --check, validate_marketplace.py, validate_markdown.py, and full test_validate.py.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Rebased onto origin/main 1.59.0, kept validator/test/spec changes and 1.60.0 release files, resolved SKILL.md leanly against main, rebuilt generated artifacts, validated locally, and prepared the branch for force-push.
<!-- SECTION:FINAL_SUMMARY:END -->
