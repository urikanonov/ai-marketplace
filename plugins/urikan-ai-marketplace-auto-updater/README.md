# urikan-ai-marketplace-auto-updater

An opt-in plugin for both Claude Code and the GitHub Copilot CLI that, on each session start, checks for and
installs updates to the other plugins you have installed from the `urikan-ai-marketplace`. Install it only if
you want automatic updates. It also ships an on-demand `marketplace-update` skill for forcing an update in
free text (for example "update cmh").

## Repository layout

This plugin is split into two directories:

- [`pkg/`](pkg/README.md) - the shipped marketplace plugin users install. It contains `plugin.json`, the
  Copilot session-start hook (`hooks.json`), the Claude Code manifest and hook (`.claude-plugin/plugin.json`
  and `hooks/hooks.json`), the shared agent-aware update script (`hooks/marketplace-update.ps1`), the
  on-demand `skills/marketplace-update` skill, and its README.
- `dev/` - the development home.
  It contains the feature spec ([`dev/SPEC.md`](dev/SPEC.md)) and the automated hook test suite, and it is
  never shipped.

The plugin `CHANGELOG.md` lives here at the plugin root (not inside `pkg/`), so it is tracked and surfaced
on the website but never distributed with the plugin.
