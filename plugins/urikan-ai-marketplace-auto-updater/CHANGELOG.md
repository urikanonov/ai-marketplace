# Changelog

All notable changes to the `urikan-ai-marketplace-auto-updater` plugin are documented here. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.3] - 2026-07-15

### Fixed

- The Claude `SessionStart` hook surfaced a `hook error` notice on every macOS/Linux session start.
  Claude runs every handler in a matched group, so the exec-form `powershell` handler (kept for
  Windows without Git Bash) tried to spawn a `powershell` binary that does not exist on macOS/Linux
  and failed. The two handlers are now collapsed into a single `bash` handler that dispatches by
  `uname`: `pwsh` on macOS/Linux, Windows PowerShell (or `pwsh`) on Windows. Exactly one clean
  invocation runs per platform, with no cross-platform spawn failure. (UPD-15)

### Changed

- The update pass now logs a `pass complete: N plugin(s) checked` line so a completed pass is visible
  in the log (previously only failures and skips were logged), matching the documented logging
  behavior. (UPD-16)

## [1.2.2] - 2026-07-15

### Changed

- Dual-agent audit follow-ups: the shipped `pkg/README.md` now documents both agents (Copilot and
  Claude Code hooks, both config-home log/throttle paths, and the on-demand skill) instead of being
  framed as a GitHub Copilot CLI plugin.

### Fixed

- The Claude `SessionStart` hook could run the update twice on Windows when both Git Bash and a
  PowerShell were present (the bash and powershell handlers both fired). The bash handler now no-ops
  on Windows (`uname` MINGW/MSYS/CYGWIN), so exactly one handler runs per platform: powershell on
  Windows, bash+pwsh on macOS/Linux. Updates are idempotent and throttled, so this was harmless but
  is now clean. (UPD-15)

## [1.2.1] - 2026-07-15

### Fixed

- The plugin failed to load in Claude Code with "Duplicate hooks file detected" because
  `.claude-plugin/plugin.json` redundantly referenced `./hooks/hooks.json`, which Claude Code already
  auto-loads from the standard `hooks/hooks.json` location. Removed the redundant `hooks` manifest
  field so the plugin loads cleanly; `claude plugin validate --strict` accepted the manifest either
  way, so this was caught only by a real `claude plugin install`. (UPD-14)

## [1.2.0] - 2026-07-15

### Added

- Claude Code support: the plugin now ships a `.claude-plugin/plugin.json` and a Claude-format
  `hooks/hooks.json` (a `SessionStart` matcher group), so it installs AND auto-updates under Claude
  Code as well as the GitHub Copilot CLI, and it is listed in the repo-root
  `.claude-plugin/marketplace.json`. The single `hooks/marketplace-update.ps1` is now agent-aware via
  a `-Agent copilot|claude` switch: under Claude it reads `~/.claude/settings.json` `enabledPlugins`
  and runs `claude plugin update`, throttling and logging under `~/.claude/plugin-data`. (UPD-09,
  UPD-10, UPD-11)
- On-demand manual update: a bundled `marketplace-update` skill (agent-agnostic) lets you force an
  update in free text - for example "update cmh", "update commentable html", "update the marketplace
  plugins", or "force update" - and the agent runs the plugin update for the current CLI without
  waiting for the throttled session-start pass. (UPD-12)

## [1.1.0] - 2026-07-15

### Changed

- Moved `CHANGELOG.md` out of the shipped `pkg/` to the plugin root so it is no longer distributed with the
  plugin, mirroring the `commentable-html` layout, and added a minimal root `README.md` describing the
  `pkg/` (shipped) and `dev/` (not shipped) split. The changelog is now also surfaced on the plugin's
  website page.

## [1.0.3] - 2026-07-12

### Fixed

- Aligned the shipped plugin description with the marketplace manifest so the validator can enforce metadata parity.

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
