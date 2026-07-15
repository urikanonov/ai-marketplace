# docs

Maintainer documentation for the ai-marketplace repository.

## Testing guidelines

[`testing-guidelines.md`](./testing-guidelines.md) is the single source of truth for how tests are
written in this repository: where each suite lives, the test-driven and genuinely-red-first workflow,
the hermetic Playwright conventions, the generator and drift-check gates, and the pitfalls past refactors
already paid for. Read it before writing or changing any test. The
[`.github/instructions/testing.instructions.md`](../.github/instructions/testing.instructions.md)
instructions file points agents at it automatically when they touch test files.

## General audit playbook

[`general-audit-playbook.html`](./general-audit-playbook.html) is a reusable,
commentable-HTML playbook for auditing this repository for customer-distribution readiness. It describes the
repeatable process - a model-diverse discovery panel, judge consolidation rounds, disjoint-file workstreams,
the spec-and-test discipline, and the verification rounds before shipping - rather than any one set of
findings, so the same rigor can be re-run whenever the skill or site changes materially.

Open the file in a browser to read it, comment inline on any step you want to tune, and send the notes back
to your agent to refine the process. It is built with the repository's own `commentable-html` skill.

## Adding a feature

[`adding-a-feature.md`](./adding-a-feature.md) is the end-to-end checklist for adding a new feature to a
plugin (most often a new `commentable-html` behavior): backlog-first tracking, a fresh worktree, the
test-first (TDD) and spec-row discipline, editing the owning split partial and wiring the shared layers,
the scaffold + apply tool pattern with a validator guardrail and an on-demand reference doc, the coverage
gates (MODULES.md and the tools-layout map), adding or extending a demo and running the E2E audit on it,
and the version / changelog / rebuild / validate steps. Follow it so a feature ships complete on the first
pass. It uses the editable notes field as its worked example.
