# urikan-ai-marketplace auto-updater

A GitHub Copilot CLI plugin that, on each session start, checks for and installs updates for the other
plugins you have installed from the `urikan-ai-marketplace`. It is opt-in: install it only if you want
automatic updates.

## How it works

The plugin registers a `sessionStart` hook (`hooks.json`). On Windows it runs the PowerShell script
`hooks/marketplace-update.ps1` via `powershell -NoProfile -ExecutionPolicy Bypass -File ...` (the
`-ExecutionPolicy Bypass` matters: the default Windows machine policy is `Restricted`, which would
otherwise block the script). On macOS and Linux it runs the same script under PowerShell 7 (`pwsh`).

The hook is non-blocking by design: all work is wrapped in `try/catch`, failures are logged and never
surfaced to the session, and each plugin is updated in isolation so one failure does not stop the rest.
Plugins are processed in name-sorted order for a deterministic log. A last-run throttle skips the whole
pass when the previous pass ran less than about 20 hours ago.

## Prerequisite on macOS and Linux: PowerShell 7 (`pwsh`)

The updater logic is a PowerShell script, so on macOS and Linux it needs **PowerShell 7 (`pwsh`)** on
your `PATH`. Install it from https://learn.microsoft.com/powershell/scripting/install/installing-powershell.

If `pwsh` is not installed, the hook does not update anything; instead it appends a dated skip note to
its log so the skip is discoverable rather than silent:

```
<COPILOT_HOME or ~/.copilot>/plugin-data/urikan-ai-marketplace-auto-updater.log
```

On Windows no extra install is needed (Windows PowerShell 5.1 is used).

## Logs

Activity and failures are logged to
`<COPILOT_HOME or ~/.copilot>/plugin-data/urikan-ai-marketplace-auto-updater.log`, and the last
successful pass is stamped in `urikan-ai-marketplace-auto-updater.last-run` beside it.
