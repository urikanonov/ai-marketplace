# Changelog

All notable changes to the `urikan-ai-marketplace-auto-updater` plugin are documented here. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.1] - 2026-07-10

### Changed

- The updater now checks `$LASTEXITCODE` after each `copilot plugin update` and logs failures.
  Native-command failures were previously swallowed by the `catch`.

## [1.0.0] - 2026-07-10

### Added

- Session-start hook that checks for and installs plugin updates from this marketplace. Opt-in: install
  only if you want automatic updates.
