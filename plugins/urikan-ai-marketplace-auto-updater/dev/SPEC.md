# Auto-updater feature spec

The `urikan-ai-marketplace-auto-updater` plugin runs a session-start hook that updates the other
plugins installed from this marketplace, and ships an on-demand `marketplace-update` skill for forcing
an update in free text. It works for BOTH agents: the GitHub Copilot CLI (a Copilot-format
`hooks.json`) and Claude Code (a `hooks/hooks.json` `SessionStart` matcher group), driven by one
agent-aware `pkg/hooks/marketplace-update.ps1` (`-Agent copilot|claude`). This spec maps each promised
behavior to the automated test that covers it. Every behavior change must update a row here and its
named test in the same change (see the repo `AGENTS.md` "Spec-and-test discipline").

Covering test suite: `plugins/urikan-ai-marketplace-auto-updater/dev/tests/updater.Tests.ps1`
(a pwsh script; runs on `windows-latest` and `ubuntu-latest` via
`.github/workflows/pwsh-tests.yml`). It exercises the real
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
| UPD-08 | A last-run throttle skips the whole update pass when the previous pass ran less than the configured cadence (default 24 hours) ago (logged), and a completed pass refreshes the stamp. | `updater.Tests.ps1` -> "UPD-08 last-run throttle" |
| UPD-09 | Under `-Agent claude` the updater enumerates the enabled `@urikan-ai-marketplace` plugins from `~/.claude/settings.json` `enabledPlugins`, updates each with `claude plugin update`, and never updates itself. | `updater.Tests.ps1` -> "UPD-09 Claude enumerates enabledPlugins and excludes self" |
| UPD-10 | Under `-Agent claude` the updater updates only ENABLED plugins from this marketplace: a disabled plugin (`false`) and a plugin from another marketplace are both skipped. | `updater.Tests.ps1` -> "UPD-10 Claude skips disabled and other-marketplace plugins" |
| UPD-11 | The plugin ships a Claude-format `hooks/hooks.json` (a `SessionStart` matcher group) that invokes the shared `marketplace-update.ps1` with `-Agent claude` via the `${CLAUDE_PLUGIN_ROOT}` placeholder, so the auto-update runs on Claude Code session start. | `updater.Tests.ps1` -> "UPD-11 Claude SessionStart hook config" |
| UPD-12 | The plugin ships a bundled, agent-agnostic `marketplace-update` skill whose front matter names it and whose description triggers on on-demand update phrasings (e.g. "update cmh"), instructing the agent to run the plugin update command for the current CLI. | `updater.Tests.ps1` -> "UPD-12 on-demand manual-update skill" |
| UPD-13 | Under `-Agent claude` a recent per-agent throttle stamp (`<self>.claude.last-run`) skips and logs the pass, and a config with no enabled `@urikan-ai-marketplace` plugins is a clean no-op (no crash, no update). | `updater.Tests.ps1` -> "UPD-13 Claude throttle and empty/missing config are no-ops" |
| UPD-14 | The Claude `.claude-plugin/plugin.json` does NOT set a `hooks` field pointing at the standard `./hooks/hooks.json`, which Claude Code auto-loads - a redundant reference causes a "Duplicate hooks file detected" load failure at install time (which `claude plugin validate --strict` does not catch); the standard `hooks/hooks.json` still ships for auto-load. | `updater.Tests.ps1` -> "UPD-14 Claude plugin.json does not redundantly reference the standard hooks file" |
| UPD-15 | The Claude `SessionStart` group has exactly ONE handler: a single `bash` handler that dispatches by `uname` (runs `pwsh` on macOS/Linux, Windows PowerShell or `pwsh` on Windows MINGW/MSYS/CYGWIN). Claude runs every handler in a matched group, so a second exec-form `powershell` handler would spawn-fail on macOS/Linux (no `powershell` binary) and surface a `hook error` notice; the single per-platform dispatcher gives exactly one clean invocation per platform with no cross-platform spawn failure. | `updater.Tests.ps1` -> "UPD-15 Claude SessionStart hook is a single per-platform bash dispatcher (no cross-platform spawn failure)" |
| UPD-16 | The update pass logs a `pass complete: N plugin(s) checked` line on completion, so a completed pass is visible in the per-agent log (previously only failures and skips were logged). | `updater.Tests.ps1` -> "UPD-16 The update script logs a completed pass" |
| UPD-17 | The throttle cadence is read at runtime from a persistent, update-safe source so a user-set cadence survives plugin updates: precedence is the `URIKAN_AI_MARKETPLACE_THROTTLE_HOURS` env override, then a `plugin-data/<self>.config.json` `{ "throttleHours": N }` file (plugin-data is outside the installed-plugins subtree a plugin update replaces), then the 24h default. `throttleHours=0` disables the throttle (runs every session); any invalid, missing, or unreadable value falls back safely to the default and never blocks the pass. | `updater.Tests.ps1` -> "UPD-17 persistent, update-safe throttle cadence (config file + env override)" |
| UPD-18 | The bundled `marketplace-update` skill can SET the cadence from free text (for example "update every session", "set update frequency to 12 hours", "once a day") by writing the persistent `plugin-data/<self>.config.json` `throttleHours` config for the current agent, in addition to its on-demand update role. | `updater.Tests.ps1` -> "UPD-18 the skill can set the cadence in free text" |
| UPD-19 | When the user asks to change the schedule WITHOUT naming a value (for example "change update schedule/cadence/frequency"), the `marketplace-update` skill presents an explicit four-way choice - each session / every 1 hour / every 24 hours (the default) / a custom interval - and maps the answer to `throttleHours` (0 / 1 / 24 / N). | `updater.Tests.ps1` -> "UPD-19 the skill offers a four-way cadence choice with a 24h default" |

## Coverage gaps

- The UPD-07 functional check (actually executing the bash else-branch and asserting the log line) runs
  only on POSIX shells, which is where that field runs; on Windows the powershell field is used
  instead and git-bash mangles Windows paths, so on Windows UPD-07 falls back to structural assertions
  on the `hooks.json` bash field. This is intentional, not a missing test.
- A per-plugin update timeout is intentionally NOT implemented. A `Start-Job`/`Wait-Job` wrapper would
  add its own hang and PowerShell 5.1 compatibility risk, which conflicts with the non-blocking
  guarantee. The `hooks.json` `timeoutSec` (the CLI-enforced total budget) plus the UPD-08 last-run
  throttle bound the cost instead. Tracked here so the decision is explicit.
