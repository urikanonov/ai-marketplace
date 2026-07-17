---
name: marketplace-update
description: Update installed urikan-ai-marketplace plugins on demand, or set how often the auto-updater runs. Use when the user asks to update or force-update a marketplace plugin, for example "update commentable-html", "update cmh", "update the marketplace plugins", "force update", "get the latest commentable html", or "refresh my plugins"; OR when the user asks to change the auto-update cadence, for example "change update schedule", "change update cadence", "change update frequency", "update every session", "set update frequency to 12 hours", "check for updates once a day", or "stop auto-updating". Runs the plugin update command, or writes the persistent cadence config, for whichever agent CLI is in use.
---

# Marketplace update (on demand)

Update one or more plugins installed from the `urikan-ai-marketplace` immediately, without waiting for the auto-updater's throttled session-start pass. This skill also sets the auto-updater's cadence (how often it runs) in a way that survives plugin updates.

## When to use

Trigger when the user asks, in free text, to:

- Update a marketplace plugin now - for example: "update cmh", "update commentable html", "update commentable-html", "update the marketplace plugins", "force update", "get the latest commentable html", "refresh my plugins". Do the "Update now" steps below.
- Change how often the auto-updater runs - for example: "change update schedule", "change update cadence", "change update frequency", "update every session", "set update frequency to 12 hours", "check for updates once a day", "update weekly", "stop auto-updating". Do the "Set the update cadence" steps below.

## Update now

1. Determine which CLI runs this session: the GitHub Copilot CLI (`copilot`) or Claude Code (`claude`). Use the agent you are running inside; if only one of the two is on `PATH`, use that one.
2. Resolve the target plugin(s) from the request:
   - "cmh", "commentable html", "commentable-html" -> `commentable-html`
   - "auto-updater", "updater" -> `urikan-ai-marketplace-auto-updater`
   - "all", "everything", "my plugins", "the marketplace plugins" -> every plugin the user installed from `urikan-ai-marketplace`
3. Run the update for each resolved plugin, always with the marketplace suffix `@urikan-ai-marketplace`:
   - GitHub Copilot CLI: `copilot plugin update <name>@urikan-ai-marketplace`
   - Claude Code: `claude plugin update <name>@urikan-ai-marketplace`

   To update every installed marketplace plugin, first list them (`copilot plugin list` or `claude plugin list`), then update each `<name>@urikan-ai-marketplace` in turn.
4. Report the result briefly: which plugins were updated and their new version. Note that Claude Code applies a plugin update on the next restart.

## Set the update cadence

The auto-updater skips its session-start pass when the previous pass ran less than `throttleHours` hours ago (default 24). Set a user-chosen cadence by writing a persistent config file. It lives under `plugin-data/`, which is OUTSIDE the installed-plugins subtree a plugin update replaces, so the cadence is NOT reset when the plugin updates itself.

1. Figure out the target hours (`throttleHours`, a decimal `>= 0`):
   - If the user already named a value, map it directly: "every session", "always", "no throttle" -> `0`; "every N hours" -> `N`; "twice a day" -> `12`; "once a day", "daily" -> `24`; "weekly" -> `168`.
   - If the user asked to change the schedule WITHOUT naming a value (for example "change update schedule", "change the update cadence", "change update frequency", "how often should it update?"), ask them this four-way choice and wait for their answer:

     > How often should the auto-updater check for plugin updates?
     > 1. Each session (check on every session start)
     > 2. Every 1 hour
     > 3. Every 24 hours (the default)
     > 4. Custom - a number of hours you choose

     Map the answer to `throttleHours`: choice 1 -> `0`, choice 2 -> `1`, choice 3 -> `24`, choice 4 -> the number of hours they give (a positive number; decimals are allowed).
2. Pick the config path for the current agent's config home:
   - GitHub Copilot CLI: `<COPILOT_HOME or ~/.copilot>/plugin-data/urikan-ai-marketplace-auto-updater.config.json`
   - Claude Code: `<CLAUDE_CONFIG_DIR or ~/.claude>/plugin-data/urikan-ai-marketplace-auto-updater.config.json`
3. Write (creating the folder if needed) that file with exactly:

   ```json
   { "throttleHours": <N> }
   ```

   Preserve any other keys already in the file; only set `throttleHours`.
4. Report the new cadence back to the user (for example "the auto-updater will now run on every session" for `0`, or "at most once every 12 hours"). It takes effect on the next session start.

## Notes

- The on-demand update is the manual counterpart to the plugin's automatic session-start hook; running it on demand does not disturb the auto-update throttle.
- A plugin update is idempotent, so it is safe to re-run: an already-current plugin is a no-op.
- A one-off override without editing the config: set the `URIKAN_AI_MARKETPLACE_THROTTLE_HOURS` environment variable, which takes precedence over the config file for that session.
