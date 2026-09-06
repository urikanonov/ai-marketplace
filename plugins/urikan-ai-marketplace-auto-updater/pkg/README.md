# urikan-ai-marketplace auto-updater

A plugin for both Claude Code and the GitHub Copilot CLI that, on each session start, checks for and
installs updates for the other plugins you have installed from the `urikan-ai-marketplace`. It is
opt-in: install it only if you want automatic updates. It also ships an on-demand `marketplace-update`
skill, so you can force an update in free text (for example "update cmh").

## How it works

The plugin registers a session-start hook for each agent, both of which run the same PowerShell script
`hooks/marketplace-update.ps1` (agent-aware via a `-Agent copilot|claude` switch):

- GitHub Copilot CLI: a `sessionStart` hook in `hooks.json`. On Windows it runs the script via
  `powershell -NoProfile -ExecutionPolicy Bypass -File ...` (the `-ExecutionPolicy Bypass` matters:
  the default Windows machine policy is `Restricted`, which would otherwise block the script); on
  macOS and Linux it runs under PowerShell 7 (`pwsh`). It enumerates the plugins under
  `<COPILOT_HOME or ~/.copilot>/installed-plugins/urikan-ai-marketplace/` and runs
  `copilot plugin update <name>@urikan-ai-marketplace` for each.
- Claude Code: a `SessionStart` hook in `hooks/hooks.json` (Claude auto-loads that standard location).
  It reads the enabled `@urikan-ai-marketplace` plugins from `<CLAUDE_CONFIG_DIR or ~/.claude>/settings.json`
  and runs `claude plugin update <name>@urikan-ai-marketplace` for each.

The hook is non-blocking by design: all work is wrapped in `try/catch`, failures are logged and never
surfaced to the session, and each plugin is updated in isolation so one failure does not stop the rest.
Plugins are processed in name-sorted order. The updater updates itself only after every other plugin has
been processed, then records that the agent must restart before the new hook is active. An exclusive,
non-waiting file lock prevents overlapping passes from simultaneous session starts.

## Update cadence (persistent across updates)

The updater refreshes the marketplace catalog every `catalogCheckHours` (default `1`) and immediately
checks installed plugins after a due successful refresh. `throttleHours` (default `24`) remains the
fallback interval between successful install passes. Configure either value in a file that SURVIVES
plugin updates because it lives under `plugin-data/` (outside the `installed-plugins/` subtree):

- GitHub Copilot CLI: `<COPILOT_HOME or ~/.copilot>/plugin-data/urikan-ai-marketplace-auto-updater.config.json`
- Claude Code: `<CLAUDE_CONFIG_DIR or ~/.claude>/plugin-data/urikan-ai-marketplace-auto-updater.config.json`

Write it as:

```json
{ "throttleHours": 24, "catalogCheckHours": 1 }
```

Both values must be numeric hours from `0` through `87600` (10 years). Boolean, negative, non-finite,
and larger values are ignored in favor of the corresponding default.

`0` means "no throttle" for that cadence. Use `1` for hourly, `12` for twice a day, `24`
for daily, `168` for weekly, and so on. The easiest way to set it is to just ask in free
text ("change update schedule", "update every session", "set update frequency to 12 hours"); the bundled
`marketplace-update` skill offers a four-way choice (each session / every 1 hour / every 24 hours / a
custom interval) and writes this file for you. A one-off override without editing the file is the
`URIKAN_AI_MARKETPLACE_THROTTLE_HOURS` environment variable, which takes precedence for that session. Any
invalid or unreadable value falls back to its default and never blocks the hook.

## Health

Ask "check updater health" or "why did updates skip?" to use the bundled skill. It runs the hook in
read-only `health` mode and reports installation/enabled state, active and marketplace versions,
per-plugin versions, last attempt and success, next eligibility, throttle reason, lock state, restart
requirement, and remediation. Health mode never runs a plugin or catalog update.

If the updater changes version, restart the GitHub Copilot CLI by ending the current CLI process and
starting a new session. In Claude Code, restart Claude Code (or use its plugin reload command when
available). The current pass completes with the old in-memory script; the next session loads the new
hook version.

## Prerequisite on macOS and Linux: PowerShell 7 (`pwsh`)

The updater logic is a PowerShell script, so on macOS and Linux it needs **PowerShell 7 (`pwsh`)** on
your `PATH`, in both agents. Install it from
https://learn.microsoft.com/powershell/scripting/install/installing-powershell.

If `pwsh` is not installed, the hook does not update anything; instead it appends a dated skip note to
its per-agent log so the skip is discoverable rather than silent. On Windows no extra install is needed
(Windows PowerShell 5.1 is used).

## Logs

Each pass writes normalized per-plugin outcomes to an atomic JSON status file and appends a concise log.
CLI output is not persisted. Logs rotate at 256 KiB and retain three archives:

- GitHub Copilot CLI: `<COPILOT_HOME or ~/.copilot>/plugin-data/urikan-ai-marketplace-auto-updater.log`
  (status: `urikan-ai-marketplace-auto-updater.status.json`).
- Claude Code: `<CLAUDE_CONFIG_DIR or ~/.claude>/plugin-data/urikan-ai-marketplace-auto-updater.log`
  (status: `urikan-ai-marketplace-auto-updater.status.json`).
