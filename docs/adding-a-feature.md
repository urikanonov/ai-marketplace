# Adding a feature

The end-to-end workflow for adding a new feature to a plugin in this repository (most often a new
`commentable-html` behavior). It is the single checklist to follow so a feature ships complete on the
first pass instead of rediscovering the gates one CI failure at a time. It complements
[AGENTS.md](../AGENTS.md) (authoritative where they overlap) and
[testing-guidelines.md](./testing-guidelines.md) (authoritative for tests).

The worked example throughout is the editable notes field (`data-cmh-note`): an authored element that a
reviewer types into, whose edit is tracked, handed back through Copy all, and cemented into the source
with a tool. It touched every surface below, so it is a good template.

## 0. Before any code: track it and branch it

1. **Backlog first (non-negotiable).** Search the backlog, then create or reuse a Backlog.md task, set
   it `In Progress`, and assign it to yourself. Drive it through the `backlog` CLI; never hand-edit a task
   file. Capture any follow-up you discover as its own task the moment it comes up.
2. **Fresh worktree off the latest `origin/main`.** `git fetch origin`, then
   `git worktree add -b <branch> .worktrees/<name> origin/main`. Never edit the primary tree in place.
   Enable the hooks once per worktree: `git config core.hooksPath .githooks`.
3. **Plan and get approval.** For a user-facing change, write the plan (a commentable-HTML plan by
   default), review it, and get a go-ahead before writing code.

## 1. Write the test first (TDD, genuinely red)

Every feature ships with a covering automated test in the same PR, and the test is written first and
confirmed RED against the current code. Read [testing-guidelines.md](./testing-guidelines.md) before you
start; the traps it documents (pinning the change to a marker only the change introduces, rebuilding
generated output before asserting, hermetic Playwright specs, choosing an observable viewport) are the
ones most often relearned the hard way.

- Runtime behavior goes in a Playwright spec under `plugins/<plugin>/dev/tests/NN-topic.spec.js`; author
  tooling goes in a Python `unittest`/`pytest` module beside it.
- Use inputs that cannot pass by accident. The notes tests use a normalization-hostile value (leading and
  trailing spaces, an internal double space, an entity, a newline) so a shallow implementation is caught.
- Playwright specs load the BUILT `dist`, so run the build (step 3) before asserting a runtime change, or
  the spec measures stale code.

## 2. Give the behavior a spec row

Add an `AREA-NN` row to the owning spec (`plugins/<plugin>/dev/SPEC.md`, or `site/tests/SPEC.md` for the
site) for every behavior, and name the exact covering test in the row. Reuse an id when you refine a
behavior; never renumber or delete a shipped id. A behavior the spec does not tie to a passing test is
not done. The notes feature added `CMH-NOTE-01..15` plus a `CMH-DEMO-05` row for its demo.

## 3. Implement in the owning split partial (never a monolith)

The `commentable-html` runtime and CSS live only as numbered partials under
`dev/assets/js/NN-topic.js` and `dev/assets/css/NN-topic.css`; `build.py` concatenates each directory by
sort order, so adding a behavior is usually adding one partial (the notes runtime is
`37-notes.js` + `86-notes.css`). Never recombine them into a `commentable-html.js`/`.css` monolith - a
test forbids it.

Wire the behavior into the shared layers it needs (the notes feature touched all of these; a smaller
feature touches fewer):

- **Sidebar** (`50-sidebar.js`): a change card and a click-handler branch, merged into the
  position-sorted card list and the empty-state guard.
- **Search** (`51-comment-search.js`): if the card should be findable.
- **Copy all** (`56-copy-clear.js`): a bundle section, a machine-readable JSON line, and the "has changes"
  gate (`_copyAllState`).
- **Clear** (`62-sortable-tables.js`): whether the global Clear should reset the new state.
- **Badge** (`70-mode-badge.js`): a Not-portable reason while the state is unsaved.
- **Exports** (`65/66/67/68`): a bake so the exported source carries the state.
- **Startup** (`95-startup.js`): the init call (mind ORDERING - anything that adds `cm-skip` and removes
  its text from the offset system must run before offset restoration, like the diff and notes layers do)
  and the open-sidebar-on-load gate.

For round-trippable state, follow the scaffold + apply pair: a `tools/<topic>/<topic>_scaffold.py` that
emits the markup and a `tools/<topic>/<topic>_apply.py` that deterministically and idempotently cements a
Copy-all payload back into the source. Add authoring guardrails to `tools/validate/checks/<topic>.py` and
wire them into `validate.py`.

## 4. Document it with a minimal SKILL.md footprint

Put the detail in an on-demand `references/<topic>-contract.md` and add only a short linked line to
`SKILL.md` (and a scaffold-tool mention). The link is a gated invariant: every `references/*.md` must be
reachable from `SKILL.md` or `references/file-inventory.md`, so an unlinked reference fails CI. Update the
`tools/` bucket enumeration in `references/file-inventory.md` when you add a bucket.

## 5. Register the new files with the coverage gates

Adding a partial or a tool trips a coverage gate unless you also update its map:

- A new `dev/assets/js/` or `dev/assets/css/` partial needs a row in that directory's `MODULES.md`, and
  every SPEC area it claims must be a real, test-backed `AREA-NN` row.
- A new shipped tool needs its entry in `dev/tests/test_tools_layout.py`'s `EXPECTED` map.

## 6. Add or extend a demo, then run the E2E audit on it

Ship the feature in a live demo so a user can try it:

- Add `dev/examples/src/report-<name>.html` (a full standalone doc with a unique `data-comment-key`) and a
  companion `examples/prompt-<name>.md`, or extend an existing demo. `build.py` auto-discovers
  `report-*.html`; a report with no `dev/examples/src/` source, or with no companion prompt, fails CI.
- Add a `CMH-DEMO-NN` spec row and a test that names it.
- Run the E2E Playwright audit against the demo (`npx playwright test <spec>`) to confirm every
  interaction works before shipping. The notes feature ships `report-notes.html` and its end-to-end
  round-trip test exercises the demo path.

## 7. Version, changelog, and rebuild every artifact

- Bump `dev/VERSION` (a shipped-source change requires a bump; pick a distinct version lane up front when
  PRs are in flight) and add a matching `## [x.y.z]` heading to the plugin's `CHANGELOG.md`.
- Regenerate everything in one command: `python scripts/rebuild_all.py` (the layer dist, the
  version-stamped Playwright fixtures, and the site). Never hand-edit a generated artifact - each carries a
  `DO NOT EDIT` banner and a `--check` gate.

## 8. Validate, run the suites, and open the PR

```bash
python scripts/validate_marketplace.py
python scripts/validate_markdown.py
python scripts/rebuild_all.py --check          # every generated artifact is in sync
```

Run the Python suite (`python -m pytest` from `plugins/<plugin>/dev/tests`) and the relevant Playwright
spec (`npx playwright test <spec>`). The full browser suite is occasionally flaky under high parallelism -
re-run any failure in isolation before treating it as real; CI is the authoritative Playwright gate. The
pre-push hook mirrors the required checks (validators, changelog sync, version bump, and the `--check`
drift guards), so a push that would fail a required check is caught locally first. Do NOT put the version
in the PR title; describe the change.

## Checklist

- [ ] Backlog task `In Progress` and assigned, fresh worktree off `origin/main`, hooks enabled.
- [ ] Failing test written first and confirmed red; `AREA-NN` spec row names it.
- [ ] Behavior implemented in the owning split partial (no monolith) and wired into every shared layer it
      needs.
- [ ] Scaffold + apply tools and a validator guardrail for round-trippable state.
- [ ] `references/<topic>-contract.md` added and linked; minimal `SKILL.md` line; `file-inventory.md`
      bucket updated.
- [ ] `MODULES.md` row(s) and `test_tools_layout.py` map updated.
- [ ] Demo added or extended, with a companion prompt, a `CMH-DEMO` row, and the E2E audit run against it.
- [ ] `dev/VERSION` bumped, `CHANGELOG.md` updated, `rebuild_all.py` run.
- [ ] Validators, `rebuild_all --check`, the Python suite, and the touched Playwright spec all pass.
