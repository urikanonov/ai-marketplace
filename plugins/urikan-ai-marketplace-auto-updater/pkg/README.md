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
Plugins are processed in name-sorted order for a deterministic log. A per-agent last-run throttle skips
the whole pass when the previous pass for that agent ran less than the configured cadence (24 hours by
default) ago. The plugin always excludes itself (a plugin cannot update itself while its own hook is
running).

## Update cadence (persistent across updates)

How often the updater runs is controlled by a `throttleHours` value: the session-start pass is skipped
when the previous pass ran less than that many hours ago. It defaults to `24` (once a day), and you set
your own cadence in a config file that SURVIVES plugin updates, because it lives under `plugin-data/`
(outside the `installed-plugins/` subtree a plugin update replaces):

- GitHub Copilot CLI: `<COPILOT_HOME or ~/.copilot>/plugin-data/urikan-ai-marketplace-auto-updater.config.json`
- Claude Code: `<CLAUDE_CONFIG_DIR or ~/.claude>/plugin-data/urikan-ai-marketplace-auto-updater.config.json`

Write it as:

```json
{ "throttleHours": 0 }
```

`0` means "no throttle" - update on every session start. Use `1` for hourly, `12` for twice a day, `24`
for daily (the default), `168` for weekly, and so on. The easiest way to set it is to just ask in free
text ("change update schedule", "update every session", "set update frequency to 12 hours"); the bundled
`marketplace-update` skill offers a four-way choice (each session / every 1 hour / every 24 hours / a
custom interval) and writes this file for you. A one-off override without editing the file is the
`URIKAN_AI_MARKETPLACE_THROTTLE_HOURS` environment variable, which takes precedence for that session. Any
invalid or unreadable value falls back to the 24h default and never blocks the hook.

## Prerequisite on macOS and Linux: PowerShell 7 (`pwsh`)

The updater logic is a PowerShell script, so on macOS and Linux it needs **PowerShell 7 (`pwsh`)** on
your `PATH`, in both agents. Install it from
https://learn.microsoft.com/powershell/scripting/install/installing-powershell.

If `pwsh` is not installed, the hook does not update anything; instead it appends a dated skip note to
its per-agent log so the skip is discoverable rather than silent. On Windows no extra install is needed
(Windows PowerShell 5.1 is used).

## Logs

Each pass, skip, and failure is logged per agent, and a completed pass is stamped beside the log:

- GitHub Copilot CLI: `<COPILOT_HOME or ~/.copilot>/plugin-data/urikan-ai-marketplace-auto-updater.log`
  (stamp: `urikan-ai-marketplace-auto-updater.last-run`).
- Claude Code: `<CLAUDE_CONFIG_DIR or ~/.claude>/plugin-data/urikan-ai-marketplace-auto-updater.log`
  (stamp: `urikan-ai-marketplace-auto-updater.claude.last-run`).
