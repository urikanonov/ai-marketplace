---
name: update-schedule
description: Choose or change how often the urikan-ai-marketplace auto-updater checks for plugin updates. Use when the user wants to set up the update schedule after installing the auto-updater, or asks to "change update schedule", "change update cadence", "change update frequency", "how often should plugins update", "update every hour/day", "check for updates every session", or "configure auto-update". Ask the four-way choice (each session, every 1 hour, every 24 hours, or a custom interval) and persist it.
---

# Auto-update schedule (cadence)

Let the user pick how often the `urikan-ai-marketplace-auto-updater` checks for plugin updates, and change it later. The choice is persisted per agent and read by the session-start hook as its throttle interval. The default, when never set, is **every 24 hours**.

## When to use

Trigger when the user wants to set up the schedule right after installing the auto-updater, or asks to change it in free text - for example: "change update schedule", "change update cadence", "change update frequency", "update the plugins every hour", "check for updates every session", "only update once a day", or "how often do my plugins update?".

## What to do

1. Determine which CLI runs this session: the GitHub Copilot CLI (`copilot`) or Claude Code (`claude`). Use the agent you are running inside; if only one of the two is on `PATH`, use that one.
2. (Optional) Show the current setting first by running the script in `-ShowCadence` mode (see step 4 for how to locate and invoke it), so the user knows what they are changing.
3. Ask the user this exact multiple-choice question and wait for their answer:

   > How often should the auto-updater check for plugin updates?
   > 1. Each session (check on every session start)
   > 2. Every 1 hour
   > 3. Every 24 hours (default)
   > 4. Custom - a number of hours you choose

   If they pick **Custom**, ask for the number of hours (a positive number; decimals are allowed, e.g. `0.5` for 30 minutes).

4. Persist the choice by running the plugin's `marketplace-update.ps1` in `-SetCadence` mode. The script lives beside this skill in the same plugin, at `../../hooks/marketplace-update.ps1` relative to this `SKILL.md`; resolve that to an absolute path. Map the answer to a cadence token: `session` (choice 1), `1h` (choice 2), `24h` (choice 3), or `<N>h` for a custom N (choice 4, e.g. `6h`).

   - Windows: `powershell -NoProfile -ExecutionPolicy Bypass -File <script> -Agent <copilot|claude> -SetCadence <token>`
   - macOS/Linux: `pwsh -NoProfile -File <script> -Agent <copilot|claude> -SetCadence <token>`

   If you cannot resolve or run the script, fall back to writing the cadence file directly (see "Cadence file" below).
5. Confirm the new cadence back to the user, and note that it takes effect from the next session start (a cadence of "each session" makes every session start check for updates).

## Cadence file (fallback and reference)

The setting is a small JSON file under the agent's `plugin-data` folder, named per agent:

- GitHub Copilot CLI: `<COPILOT_HOME or ~/.copilot>/plugin-data/urikan-ai-marketplace-auto-updater.cadence`
- Claude Code: `<CLAUDE_CONFIG_DIR or ~/.claude>/plugin-data/urikan-ai-marketplace-auto-updater.claude.cadence`

Its contents are `{"cadence":"<label>","hours":<number>}`, where `hours` is the throttle interval in hours and `0` means "each session". Examples: `{"cadence":"session","hours":0}`, `{"cadence":"1h","hours":1}`, `{"cadence":"24h","hours":24}`, `{"cadence":"6h","hours":6}`. Prefer the `-SetCadence` script (it validates the value); write the file directly only if the script cannot be run.

## Notes

- The cadence is per agent, so setting it under the Copilot CLI does not change the Claude Code schedule and vice versa.
- This does not force an immediate update. To update now, use the on-demand `marketplace-update` skill (for example "update cmh").
- An invalid custom value (zero, negative, or non-numeric) is rejected; ask again for a positive number of hours.
