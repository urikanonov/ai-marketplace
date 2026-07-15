---
id: TASK-41
title: >-
  Deck: surface an install CTA early with site + GitHub links and dual
  Claude/Copilot install
status: Done
assignee:
  - '@urikanonov'
created_date: '2026-07-15 09:53'
updated_date: '2026-07-15 14:35'
labels: []
dependencies:
  - TASK-42
ordinal: 34000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Per plan review comment (refinement of task-16, the deck showcase): the shipped deck-showcase.html surfaces an install/CTA only as a plain text pill on the final Close slide, with no site or GitHub links, no install commands, and no Claude coverage (zero Claude mentions in the deck). Move a real install/CTA affordance earlier (end of the 5-10 min hook and/or a persistent footer) with links to the site and the GitHub repo, and provide install instructions for BOTH Claude and Copilot so viewers who drop off still get a concrete next step.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 An install/CTA with site + GitHub links appears early in the deck (not only on the final slide)
- [x] #2 Install instructions cover both Claude and Copilot
- [x] #3 Deck example rebuilt and validated (deck_validate + build); SPEC row + covering test added; validators green
<!-- AC:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Folded into the deck rework (task-42): early install CTA on slide 9 (Act 2, non-final) plus primary CTA slide 12 and close slide 17, each with both copilot and claude install commands as code blocks and site/GitHub/tutorial links. Covered by CMH-DECK-SHOWCASE-03 (asserts both agents appear before the final slide).
<!-- SECTION:FINAL_SUMMARY:END -->
