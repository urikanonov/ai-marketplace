# urikan-ai-marketplace auto-updater

A plugin for both Claude Code and the GitHub Copilot CLI that, on each session start, checks for and
installs updates for the other plugins you have installed from the `urikan-ai-marketplace`. It is
opt-in: install it only if you want automatic updates. It also ships two on-demand skills: an
`marketplace-update` skill, so you can force an update in free text (for example "update cmh"), and an
`update-schedule` skill, so you can choose how often it checks for updates (for example "change update
schedule").

## Update cadence (how often it checks)

You choose how often the auto-updater checks for updates. The default, when you never set it, is
**every 24 hours**. To change it, just ask in natural language - for example "change update schedule",
"change update cadence", "change update frequency", "check for updates every session", or "only update
once a day". The agent (via the bundled `update-schedule` skill) offers four options and remembers your
choice:

- **Each session** - check on every session start (no throttle).
- **Every 1 hour**.
- **Every 24 hours** (the default).
- **Custom** - any number of hours you choose (decimals allowed, e.g. `0.5` for 30 minutes).

The choice is saved per agent as a small JSON cadence file under your `plugin-data` folder and read by
the session-start hook as its throttle interval:

- GitHub Copilot CLI: `<COPILOT_HOME or ~/.copilot>/plugin-data/urikan-ai-marketplace-auto-updater.cadence`
- Claude Code: `<CLAUDE_CONFIG_DIR or ~/.claude>/plugin-data/urikan-ai-marketplace-auto-updater.claude.cadence`

Its contents are `{"cadence":"<label>","hours":<number>}`, where `hours` is the interval in hours and
`0` means "each session". Because it is per agent, changing the schedule under one CLI does not affect
the other.

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
the whole pass when the previous pass for that agent ran less than your configured cadence (default 24
hours) ago; an "each session" cadence disables the throttle so the pass runs on every session start. The
plugin always excludes itself (a plugin cannot update itself while its own hook is running).

## Prerequisite on macOS and Linux: PowerShell 7 (`pwsh`)

The updater logic is a PowerShell script, so on macOS and Linux it needs **PowerShell 7 (`pwsh`)** on
your `PATH`, in both agents. Install it from
https://learn.microsoft.com/powershell/scripting/install/installing-powershell.

If `pwsh` is not installed, the hook does not update anything; instead it appends a dated skip note to
its per-agent log so the skip is discoverable rather than silent. On Windows no extra install is needed
(Windows PowerShell 5.1 is used).

## Logs

Each pass, skip, and failure is logged per agent, and a completed pass is stamped beside the log. The
current cadence is stored beside them:

- GitHub Copilot CLI: `<COPILOT_HOME or ~/.copilot>/plugin-data/urikan-ai-marketplace-auto-updater.log`
  (stamp: `urikan-ai-marketplace-auto-updater.last-run`; cadence:
  `urikan-ai-marketplace-auto-updater.cadence`).
- Claude Code: `<CLAUDE_CONFIG_DIR or ~/.claude>/plugin-data/urikan-ai-marketplace-auto-updater.log`
  (stamp: `urikan-ai-marketplace-auto-updater.claude.last-run`; cadence:
  `urikan-ai-marketplace-auto-updater.claude.cadence`).
