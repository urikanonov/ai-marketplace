# Maintaining

Notes for the maintainer. External contributors improve existing plugins via pull requests; new plugins are
maintainer-authored. Because CI and the local pre-commit hook execute repository code, treat every fork PR as
untrusted until you have read it.

## Before you click "Approve and run" on a fork PR

CI (`plugin-tests`) runs `npm ci` and the PR's test code, and `validate` runs the PR's validator. Read these
first:

- Every changed `plugins/*/dev/package.json` (especially `scripts.preinstall` / `install` / `postinstall` and
  any new `dependencies` or registries) and the diff of any changed `package-lock.json`.
- Every change under `.github/workflows/**`, `.githooks/**`, `scripts/**`, `plugins/*/hooks/**`,
  `plugins/*/*.ps1`, `plugins/*/.mcp.json`, `plugins/*/plugin.json`, and any `SKILL.md` that adds hook or MCP
  wiring.

CI hardening already in place: `permissions: contents: read`, `persist-credentials: false`, workflows
trigger on `pull_request` rather than `pull_request_target`, with two deliberate exceptions -
`require-owner-approval.yml` and `request-copilot-review.yml` use `pull_request_target` so their logic
runs from the trusted base branch (and, for the Copilot request, so it has a write token on fork PRs).
Neither checks out or runs PR code; they only call the API with the PR number, so no untrusted code
executes. Otherwise: `npm ci --ignore-scripts`, per-job `timeout-minutes`, and no secrets are
referenced. The blast radius of untrusted CI code is therefore compute/egress, not secret theft - but
still read the PR before approving.

## Before you merge

- New plugins are maintainer-authored: close external PRs that add a new plugin directory or a new
  `marketplace.json` entry, and ask the contributor to open a plugin request instead.
- Confirm the required checks are green: `validate`, `version-bump`, `dist-in-sync`, `actionlint`,
  `site`, and `plugin-tests` (the plugin Playwright gate), plus `require-owner-approval` on external PRs (see below). See
  CONTRIBUTING.md / AGENTS.md for what each one enforces.
- External PRs are hard-gated on your approval. The `require-owner-approval` status fails until you
  submit an **Approve** review (a comment or "request changes" does not satisfy it). Because stale
  approvals are dismissed on new commits, a contributor's fresh push re-blocks the PR until you
  re-approve. Your own PRs and Dependabot PRs pass the gate automatically, so you are never blocked.
  The gate runs from the trusted base branch (`pull_request_target`) and posts a commit status, so a
  PR cannot disable it by editing the workflow file. In branch protection the required check is the
  commit-status context `require-owner-approval` (published by the workflow), not the `evaluate`
  Actions check-run.
- Copilot is asked to review every non-draft PR automatically as an advisory second opinion. Its
  threads are subject to conversation resolution, but it never replaces your own read of the diff.
- Changes to shipped executable content (hooks, `*.ps1`, MCP) ship to end users via the auto-updater - review
  them with extra care.

## Local safety

The pre-commit hook runs `scripts/validate_marketplace.py` from your working tree, so after checking out a PR
branch that script and `.githooks/pre-commit` are the PR's versions. Do not run them on a branch you have not
read; when in doubt validate from a clean `main` checkout.
