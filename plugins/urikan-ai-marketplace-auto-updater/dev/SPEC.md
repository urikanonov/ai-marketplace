# Auto-updater feature spec

The `urikan-ai-marketplace-auto-updater` plugin runs a session-start hook that updates the other
plugins installed from this marketplace, ships an on-demand `marketplace-update` skill for forcing
an update in free text, and ships an `update-schedule` skill for choosing how often the hook checks
for updates (the cadence). It works for BOTH agents: the GitHub Copilot CLI (a Copilot-format
`hooks.json`) and Claude Code (a `hooks/hooks.json` `SessionStart` matcher group), driven by one
agent-aware `pkg/hooks/marketplace-update.ps1` (`-Agent copilot|claude`, with `-SetCadence` /
`-ShowCadence` management modes). This spec maps each promised
behavior to the automated test that covers it. Every behavior change must update a row here and its
named test in the same change (see the repo `AGENTS.md` "Spec-and-test discipline").

Covering test suite: `plugins/urikan-ai-marketplace-auto-updater/dev/tests/updater.Tests.ps1`
(a pwsh script; runs on `windows-latest` and `ubuntu-latest` via
`.github/workflows/auto-updater-tests.yml`). It exercises the real
`pkg/hooks/marketplace-update.ps1` against isolated temp `COPILOT_HOME` / `CLAUDE_CONFIG_DIR` sandboxes
with stubbed `copilot` / `claude` commands, so no real updates and no network calls occur.

| Feature id | Behavior | Covering test |
| --- | --- | --- |
| UPD-01 | The updater updates each installed marketplace plugin but never itself (self-exclusion by folder name). | `updater.Tests.ps1` -> "UPD-01 self-exclusion" |
| UPD-02 | When the `copilot` CLI is not on `PATH`, the pass is skipped, the skip is logged, and no throttle stamp is written (so the next session retries). | `updater.Tests.ps1` -> "UPD-02 missing CLI skip + log" |
| UPD-03 | A failing `copilot plugin update` for one plugin is isolated and logged; the remaining plugins are still attempted. | `updater.Tests.ps1` -> "UPD-03 per-plugin failure isolation" |
| UPD-04 | When `COPILOT_HOME` is unset, paths fall back to `$HOME/.copilot`. | `updater.Tests.ps1` -> "UPD-04 COPILOT_HOME fallback" |
| UPD-05 | Installed plugins are processed in a deterministic, name-sorted order, so the log order is stable across platforms. | `updater.Tests.ps1` -> "UPD-05 deterministic sorted log order" |
| UPD-06 | On Windows the hook is invoked with `powershell -NoProfile -ExecutionPolicy Bypass -File ...`, so the default `Restricted` policy cannot silently block it. | `updater.Tests.ps1` -> "UPD-06 ExecutionPolicy-bypass invocation" |
| UPD-07 | On macOS/Linux, when `pwsh` (PowerShell 7) is missing the bash field writes a dated skip note to the plugin-data log instead of silently no-opping, then succeeds. | `updater.Tests.ps1` -> "UPD-07 missing-pwsh log signal" |
| UPD-08 | A last-run throttle skips the whole update pass when the previous pass ran less than the configured cadence (default ~24 hours) ago (logged), and a completed pass refreshes the stamp. | `updater.Tests.ps1` -> "UPD-08 last-run throttle" |
| UPD-09 | Under `-Agent claude` the updater enumerates the enabled `@urikan-ai-marketplace` plugins from `~/.claude/settings.json` `enabledPlugins`, updates each with `claude plugin update`, and never updates itself. | `updater.Tests.ps1` -> "UPD-09 Claude enumerates enabledPlugins and excludes self" |
| UPD-10 | Under `-Agent claude` the updater updates only ENABLED plugins from this marketplace: a disabled plugin (`false`) and a plugin from another marketplace are both skipped. | `updater.Tests.ps1` -> "UPD-10 Claude skips disabled and other-marketplace plugins" |
| UPD-11 | The plugin ships a Claude-format `hooks/hooks.json` (a `SessionStart` matcher group) that invokes the shared `marketplace-update.ps1` with `-Agent claude` via the `${CLAUDE_PLUGIN_ROOT}` placeholder, so the auto-update runs on Claude Code session start. | `updater.Tests.ps1` -> "UPD-11 Claude SessionStart hook config" |
| UPD-12 | The plugin ships a bundled, agent-agnostic `marketplace-update` skill whose front matter names it and whose description triggers on on-demand update phrasings (e.g. "update cmh"), instructing the agent to run the plugin update command for the current CLI. | `updater.Tests.ps1` -> "UPD-12 on-demand manual-update skill" |
| UPD-13 | Under `-Agent claude` a recent per-agent throttle stamp (`<self>.claude.last-run`) skips and logs the pass, and a config with no enabled `@urikan-ai-marketplace` plugins is a clean no-op (no crash, no update). | `updater.Tests.ps1` -> "UPD-13 Claude throttle and empty/missing config are no-ops" |
| UPD-14 | The Claude `.claude-plugin/plugin.json` does NOT set a `hooks` field pointing at the standard `./hooks/hooks.json`, which Claude Code auto-loads - a redundant reference causes a "Duplicate hooks file detected" load failure at install time (which `claude plugin validate --strict` does not catch); the standard `hooks/hooks.json` still ships for auto-load. | `updater.Tests.ps1` -> "UPD-14 Claude plugin.json does not redundantly reference the standard hooks file" |
| UPD-15 | The Claude `SessionStart` group has exactly ONE handler: a single `bash` handler that dispatches by `uname` (runs `pwsh` on macOS/Linux, Windows PowerShell or `pwsh` on Windows MINGW/MSYS/CYGWIN). Claude runs every handler in a matched group, so a second exec-form `powershell` handler would spawn-fail on macOS/Linux (no `powershell` binary) and surface a `hook error` notice; the single per-platform dispatcher gives exactly one clean invocation per platform with no cross-platform spawn failure. | `updater.Tests.ps1` -> "UPD-15 Claude SessionStart hook is a single per-platform bash dispatcher (no cross-platform spawn failure)" |
| UPD-16 | The update pass logs a `pass complete: N plugin(s) checked` line on completion, so a completed pass is visible in the per-agent log (previously only failures and skips were logged). | `updater.Tests.ps1` -> "UPD-16 The update script logs a completed pass" |
| UPD-17 | The session-start throttle interval is the user-configurable cadence, persisted per agent in a `plugin-data` cadence file (`<self>.cadence` for Copilot, `<self>.claude.cadence` for Claude) and read as the number of hours; when no cadence is configured the default is 24 hours. | `updater.Tests.ps1` -> "UPD-17 configurable cadence drives the throttle (default 24h)" |
| UPD-18 | An "each session" cadence (hours = 0) disables the throttle entirely, so the update pass runs on every session start regardless of how recently it last ran. | `updater.Tests.ps1` -> "UPD-18 'each session' cadence disables the throttle" |
| UPD-19 | The shared script's `-SetCadence <session\|1h\|24h\|Nh>` mode persists the chosen cadence to the per-agent cadence file (normalizing friendly tokens and a bare/`h`-suffixed custom number) and runs NO plugin updates; an invalid value is reported and not persisted. | `updater.Tests.ps1` -> "UPD-19 -SetCadence persists the choice without running updates" |
| UPD-20 | The shared script's `-ShowCadence` mode prints the current cadence (`source=configured`) or, when none is set, the 24h default (`source=default`), and runs no updates. | `updater.Tests.ps1` -> "UPD-20 -ShowCadence reports the current or default cadence" |
| UPD-21 | The plugin ships an agent-agnostic `update-schedule` skill whose front matter names it (only loader-safe name/description keys) and whose description triggers on "change update schedule/cadence/frequency" and first-time setup; it instructs the agent to ask the four-way choice (each session / 1h / 24h / custom) and persist it via `-SetCadence`. | `updater.Tests.ps1` -> "UPD-21 update-schedule cadence skill" |
| UPD-22 | The cadence is per agent: a `-Agent claude -SetCadence` writes only the Claude-scoped cadence file (not the Copilot one), and the Claude session-start pass honors an "each session" Claude cadence even with a fresh throttle stamp. | `updater.Tests.ps1` -> "UPD-22 cadence is per-agent (Claude cadence file is independent)" |

## Coverage gaps

- The UPD-07 functional check (actually executing the bash else-branch and asserting the log line) runs
  only on POSIX shells, which is where that field runs; on Windows the powershell field is used
  instead and git-bash mangles Windows paths, so on Windows UPD-07 falls back to structural assertions
  on the `hooks.json` bash field. This is intentional, not a missing test.
- A per-plugin update timeout is intentionally NOT implemented. A `Start-Job`/`Wait-Job` wrapper would
  add its own hang and PowerShell 5.1 compatibility risk, which conflicts with the non-blocking
  guarantee. The `hooks.json` `timeoutSec` (the CLI-enforced total budget) plus the UPD-08 last-run
  throttle bound the cost instead. Tracked here so the decision is explicit.
