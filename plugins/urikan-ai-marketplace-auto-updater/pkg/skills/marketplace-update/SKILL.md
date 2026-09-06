---
name: marketplace-update
description: Update installed urikan-ai-marketplace plugins, configure the auto-update cadence, or diagnose updater health. Use when the user asks to update or force-update a marketplace plugin, check updater health or status, explain why updates were skipped or failed, show installed and available versions, change the update schedule or frequency, update every session, or stop auto-updating. Uses the current agent's CLI and updater-owned status under plugin-data.
---

# Marketplace update (on demand)

Update one or more plugins installed from the `urikan-ai-marketplace` immediately, without waiting for the auto-updater's throttled session-start pass. This skill also sets the auto-updater's cadence (how often it runs) in a way that survives plugin updates.

## When to use

Trigger when the user asks, in free text, to:

- Update a marketplace plugin now - for example: "update cmh", "update commentable html", "update commentable-html", "update the marketplace plugins", "force update", "get the latest commentable html", "refresh my plugins". Do the "Update now" steps below.
- Change how often the auto-updater runs - for example: "change update schedule", "change update cadence", "change update frequency", "update every session", "set update frequency to 12 hours", "check for updates once a day", "update weekly", "stop auto-updating". Do the "Set the update cadence" steps below.
- Diagnose the updater - for example: "check updater health", "show updater status", "why did updates skip?", "is the updater stale?", or "which plugin versions are pending?". Do the "Check updater health" steps below.

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

When the updater itself is updated, restart either agent before relying on its new session-start hook.
The currently executing hook finishes safely, but a running agent cannot reload hook code in place.

## Check updater health

1. Determine the current agent (`copilot` or `claude`) and locate this installed plugin's root.
2. Run its shipped health mode without invoking any plugin update:
   - Windows PowerShell: `powershell -NoProfile -ExecutionPolicy Bypass -File <plugin-root>/hooks/marketplace-update.ps1 -Agent <agent> -Mode health`
   - PowerShell 7: `pwsh -NoProfile -File <plugin-root>/hooks/marketplace-update.ps1 -Agent <agent> -Mode health`
3. Parse the returned JSON and report:
   - whether the updater is installed and enabled;
   - active and marketplace updater versions;
   - each plugin's installed and marketplace versions;
   - last attempt, last successful pass, next eligible pass, and catalog-check cadence;
   - the last result/reason, lock state, and whether restart is required;
   - the provided remediation, status path, and log path when action is needed.
4. Do not treat `another-pass-running` or a throttle skip as a failure. Do not edit the status JSON.

## Set the update cadence

The auto-updater has two cadences:

- `catalogCheckHours` (default `1`) refreshes this marketplace's catalog. A due successful refresh runs
  the plugin checks immediately, even inside the normal install throttle.
- `throttleHours` (default `24`) is the fallback interval between successful plugin passes.

Set user-chosen values in a persistent config file. It lives under `plugin-data/`, which is OUTSIDE the installed-plugins subtree a plugin update replaces, so the settings are NOT reset when the plugin updates itself.

1. Figure out the target hours (`throttleHours`, a decimal from `0` through `87600`):
   - If the user already named a value, map it directly: "every session", "always", "no throttle" -> `0`; "every N hours" -> `N`; "twice a day" -> `12`; "once a day", "daily" -> `24`; "weekly" -> `168`.
   - If the user asked to change the schedule WITHOUT naming a value (for example "change update schedule", "change the update cadence", "change update frequency", "how often should it update?"), ask them this four-way choice and wait for their answer:

     > How often should the auto-updater check for plugin updates?
     > 1. Each session (check on every session start)
     > 2. Every 1 hour
     > 3. Every 24 hours (the default)
     > 4. Custom - a number of hours you choose

     Map the answer to `throttleHours`: choice 1 -> `0`, choice 2 -> `1`, choice 3 -> `24`, choice 4 -> the number of hours they give (a positive number no greater than `87600`; decimals are allowed).
2. Pick the config path for the current agent's config home:
   - GitHub Copilot CLI: `<COPILOT_HOME or ~/.copilot>/plugin-data/urikan-ai-marketplace-auto-updater.config.json`
   - Claude Code: `<CLAUDE_CONFIG_DIR or ~/.claude>/plugin-data/urikan-ai-marketplace-auto-updater.config.json`
3. Write (creating the folder if needed) that file with exactly:

   ```json
   { "throttleHours": <N>, "catalogCheckHours": <M> }
   ```

   Preserve any other keys already in the file; only set the value the user requested.
4. Report the new cadence back to the user (for example "the auto-updater will now run on every session" for `0`, or "at most once every 12 hours"). It takes effect on the next session start.

## Notes

- The on-demand update is the manual counterpart to the plugin's automatic session-start hook; running it on demand does not disturb the auto-update throttle.
- A plugin update is idempotent, so it is safe to re-run: an already-current plugin is a no-op.
- A one-off override without editing the config: set the `URIKAN_AI_MARKETPLACE_THROTTLE_HOURS` environment variable, which takes precedence over the config file for that session.
- Status is written atomically to `<config-home>/plugin-data/urikan-ai-marketplace-auto-updater.status.json`; logs rotate at 256 KiB with three archives.
