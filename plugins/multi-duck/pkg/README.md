# multi-duck

**Convene a panel of independent rubber-duck reviewers over your in-flight work - each on a
different model, all in parallel - then consolidate their findings and apply the safe fixes.**

One reviewer has one set of blind spots. A single model, however strong, misses the same class of
bug every time. multi-duck runs a *panel* of reviewers where each duck is a different high-capability
model, so their blind spots do not overlap: the bug your usual model always glosses over is the one
another family's model flags on sight. The disagreement is the point.

It runs end to end with **no extra prompt**. Invoke it bare and it discovers what to review on its
own, launches the panel, waits for every duck, merges the results into one ranked list, and
autonomously applies the fixes that are safe to apply, leaving the risky ones for you to decide.

## What it is good for

- **A second (and third, and fourth) opinion before you ship.** Point it at a branch, an open PR, or
  a design and get a cross-model read on whether it is safe to merge.
- **Catching the bug a single reviewer misses.** Model diversity is uncorrelated failure: correctness
  slips, edge cases, race conditions, security and data-safety issues, missing tests, and
  backward-compat risks that one model would wave through, another catches.
- **Reviewing plans and proposals, not just code.** It discovers active HTML and commentable-HTML
  plans and mines their open inline comments, so the panel reviews the proposal and the feedback
  already on it.
- **High-confidence verification of a focused question.** In consensus mode every duck answers the
  same question ("is this migration safe?"), so agreement across independent models becomes a real
  confidence signal.
- **Autonomous cleanup.** The safe, local, well-verified fixes get applied for you; the judgment calls
  are surfaced with a recommended action.

## Two modes

- **prisms** (default): the panel is split by review aspect (correctness, edge cases, security,
  tests, performance, migration), with at least two differently-modeled ducks per aspect, so every
  aspect gets two independent opinions and coverage is wide. Best for a broad review of a large
  change.
- **consensus**: every duck chases the same goal, so cross-model agreement (k of N) is a strong
  signal. Best for a focused question or a high-confidence go/no-go.

## How it works

1. **Discover** the work in flight (diff, PR, plan, tests, commentable-HTML plans and their open
   comments) and build one self-contained context bundle every duck can read.
2. **Pick a model-diverse roster** - the strongest, most different models your host exposes, one per
   family first - and assign each duck a lens (prisms) or the shared goal (consensus).
3. **Launch every duck in parallel** as review-only subagents.
4. **Consolidate**: cluster findings, weigh agreement, rank by severity, and adjudicate conflicts.
5. **Act**: apply the safe fixes and verify them with the narrowest test/build; defer the risky ones
   with a recommendation.

The ducks are strictly review-only; every change is made by the main agent under explicit safe-fix
criteria (no API, dependency, migration, security, or history-rewriting changes are ever applied
autonomously).

## Dual-host

multi-duck runs on both **Claude Code** and the **GitHub Copilot CLI**. The skill uses host-neutral
terms and gives a mapping for the reviewer subagent, per-duck model selection, parallel launch, result
collection, and the tracking store, so the same panel works on either agent.

## Install

Add the marketplace, then install the plugin:

```
# GitHub Copilot CLI
copilot plugin marketplace add https://github.com/urikanonov/ai-marketplace
copilot plugin install multi-duck@urikan-ai-marketplace

# Claude Code
claude plugin marketplace add https://github.com/urikanonov/ai-marketplace
claude plugin install multi-duck@urikan-ai-marketplace
```

Then just say **"multi-duck"** (or "run 6 ducks", "duck this PR", "consensus ducks: is this migration
safe?") and the panel takes it from there.
