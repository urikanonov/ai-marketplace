# Changelog

All notable changes to this marketplace and its plugins are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

When you change a published plugin, bump its version (see [CONTRIBUTING.md](CONTRIBUTING.md)) and add an
entry below under that plugin's name.

## [Unreleased]

### Added

- `urikan-ai-marketplace-auto-updater` 1.0.0 - session-start hook that updates installed plugins from this marketplace.
- `hello-world` 1.0.0 - example and starter-template skill.
- Repository scaffolding: marketplace manifest, JSON Schemas for the manifest and `plugin.json`, CI validation (`.github/workflows/validate.yml`), a pre-commit hook (`.githooks/pre-commit`) that runs the same validator locally, issue and PR templates, `CODEOWNERS`, `SECURITY.md`, and Dependabot.
- Public/development split convention: a plugin's `dev/` folder (tests, build tooling, canonical sources) stays in the repo but is never distributed; the validator ignores `dev/` and rejects a `source` that would ship it.
