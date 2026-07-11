# Changelog

All notable changes to the `urikan-ai-marketplace-auto-updater` plugin are documented here. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.2] - 2026-07-11

### Fixed

- Windows session-start invocation now runs `powershell -NoProfile -ExecutionPolicy Bypass -File`. A
  bare `.ps1` path was silently blocked by the default `Restricted` execution policy, so the updater
  never ran on a default Windows setup.

### Added

- On macOS/Linux, when `pwsh` (PowerShell 7) is missing the bash hook now appends a dated skip note to
  the plugin-data log instead of silently no-opping, so the skip is discoverable. Added a README
  documenting the PowerShell 7 prerequisite.
- A last-run throttle: the update pass is skipped (and logged) when the previous pass ran less than
  about 20 hours ago, and a completed pass stamps `urikan-ai-marketplace-auto-updater.last-run`.

### Changed

- Installed plugins are now iterated in name-sorted order (`Sort-Object Name`) for a deterministic log.
- The plugin now uses the `pkg/` shipped-source layout with a sibling `dev/` folder holding the feature
  spec and an automated pwsh test suite (not distributed).

## [1.0.1] - 2026-07-10

### Changed

- The updater now checks `$LASTEXITCODE` after each `copilot plugin update` and logs failures.
  Native-command failures were previously swallowed by the `catch`.

## [1.0.0] - 2026-07-10

### Added

- Session-start hook that checks for and installs plugin updates from this marketplace. Opt-in: install
  only if you want automatic updates.
