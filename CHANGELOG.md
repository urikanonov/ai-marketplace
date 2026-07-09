# Changelog

All notable changes to this marketplace and its plugins are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

When you change a published plugin, bump its version (see [CONTRIBUTING.md](CONTRIBUTING.md)) and add an
entry below under that plugin's name.

## [Unreleased]

### Added

- `urikan-ai-marketplace-auto-updater` 1.0.0 - session-start hook that updates installed plugins from this marketplace.
- `example-skills` 1.0.0 - example plugin (the `hello-world` starter skill), registered as a forward-compatible plugin-dir source (`pkg/` shipped, `dev/` not shipped).
- Repository scaffolding: marketplace manifest, JSON Schemas for the manifest and `plugin.json`, CI validation (`.github/workflows/validate.yml`), a pre-commit hook (`.githooks/pre-commit`) that runs the same validator locally, issue and PR templates, `CODEOWNERS`, `SECURITY.md`, and Dependabot.
- Public/development split convention: a plugin's `dev/` folder (tests, build tooling, canonical sources) stays in the repo but is never distributed; the validator ignores `dev/` and rejects a `source` that would ship it.
- Playwright CI: `.github/workflows/plugin-tests.yml` discovers and runs each plugin's `dev/` browser suite, demonstrated by `plugins/example-skills/dev/`.

### Changed

- `urikan-ai-marketplace-auto-updater` 1.0.1 - the updater now checks `$LASTEXITCODE` after each `copilot plugin update` and logs failures (native-command failures were previously swallowed by the `catch`).

### Security

- Hardened CI against untrusted fork PRs: `persist-credentials: false` on checkouts, `npm ci --ignore-scripts`, per-job `timeout-minutes`, `concurrency` cancellation, a tightened plugin-discovery pattern with heredoc-safe output, and an always-run `plugin-tests` summary gate.
- Validator now rejects symlinks inside a shipped source, catches case-variant dev folders (e.g. `Node_Modules`) on case-sensitive filesystems, validates that a `plugin.json`'s `hooks`/`skills` targets exist inside the source, requires `plugin.json` name to match the manifest entry, anchors semver with `\Z`, and forbids unknown `plugin.json` keys.
- Added `MAINTAINING.md` (fork-PR review checklist), a SECURITY.md auto-updater trust-model section, and CODEOWNERS coverage for `.githooks/`, `scripts/`, and `*.ps1`.
- Round-2 hardening: the `hooks`/`skills` path check now uses resolved-path containment (rejects Windows-absolute `C:\...` refs the owner's local validator would otherwise read), the shipped-source scan uses a symlink-safe `os.walk` (Python 3.12 `rglob` followed symlinks), the `plugin-tests` `summary` gate also fails when discovery fails, and `cancel-in-progress` no longer cancels `main` runs.
