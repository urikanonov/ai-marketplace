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

CI hardening already in place: `permissions: contents: read`, `persist-credentials: false`, workflows trigger
on `pull_request` (never `pull_request_target`), `npm ci --ignore-scripts`, per-job `timeout-minutes`, and no
secrets are referenced. The blast radius of untrusted CI code is therefore compute/egress, not secret theft -
but still read the PR before approving.

## Before you merge

- New plugins are maintainer-authored: close external PRs that add a new plugin directory or a new
  `marketplace.json` entry, and ask the contributor to open a plugin request instead.
- Confirm both required checks are green: `validate` and `summary` (the `plugin-tests` gate job).
- Changes to shipped executable content (hooks, `*.ps1`, MCP) ship to end users via the auto-updater - review
  them with extra care.

## Local safety

The pre-commit hook runs `scripts/validate_marketplace.py` from your working tree, so after checking out a PR
branch that script and `.githooks/pre-commit` are the PR's versions. Do not run them on a branch you have not
read; when in doubt validate from a clean `main` checkout.
