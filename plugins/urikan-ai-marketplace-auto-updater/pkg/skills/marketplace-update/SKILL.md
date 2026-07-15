---
name: marketplace-update
description: Update installed urikan-ai-marketplace plugins on demand. Use when the user asks to update or force-update a marketplace plugin, for example "update commentable-html", "update cmh", "update the marketplace plugins", "force update", "get the latest commentable html", or "refresh my plugins". Runs the plugin update command for whichever agent CLI is in use.
---

# Marketplace update (on demand)

Update one or more plugins installed from the `urikan-ai-marketplace` immediately, without waiting for the auto-updater's throttled session-start pass.

## When to use

Trigger when the user asks, in free text, to update a marketplace plugin now - for example: "update cmh", "update commentable html", "update commentable-html", "update the marketplace plugins", "force update", "get the latest commentable html", "refresh my plugins".

## What to do

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

## Notes

- This is the manual counterpart to the plugin's automatic session-start hook; running it on demand does not disturb the auto-update throttle.
- A plugin update is idempotent, so it is safe to re-run: an already-current plugin is a no-op.
