# AI Marketplace

A personal marketplace of AI-oriented plugins for the [GitHub Copilot CLI](https://github.com/github/copilot-cli). It bundles reusable skills, hooks, and MCP servers that you can install into any Copilot session with a single command.

Every plugin here is designed to make AI-assisted development workflows faster and more repeatable. Install what you need by name, or add the whole marketplace and browse.

**Website:** [urikanonov.github.io/ai-marketplace](https://urikanonov.github.io/ai-marketplace/) - browse the plugins and try the commentable-html review surface live in your browser.

## Available Plugins

| Plugin | Description | Install |
|--------|-------------|---------|
| `urikan-ai-marketplace-auto-updater` | Automatically updates all installed plugins from this marketplace on session start (opt-in) | `copilot plugin install urikan-ai-marketplace-auto-updater@urikan-ai-marketplace` |
| `commentable-html` | Turn any standalone HTML into an offline, single-file commentable review surface: reviewers select any paragraph, table cell, code block, KQL, chart, image, or diagram and leave inline comments, then export a bundle back to an agent | `copilot plugin install commentable-html@urikan-ai-marketplace` |

## Getting Started

### From your terminal

**1. Add the marketplace**
```bash
copilot plugin marketplace add https://github.com/urikanonov/ai-marketplace
```

**2. Install a plugin**
```bash
copilot plugin install urikan-ai-marketplace-auto-updater@urikan-ai-marketplace
```

**3. Verify**
```bash
copilot plugin list
```

### From inside a Copilot session

You can manage plugins without leaving your session using the built-in `/plugin` slash command:

```
/plugin marketplace add https://github.com/urikanonov/ai-marketplace
/plugin install commentable-html@urikan-ai-marketplace
/plugin list
/plugin marketplace browse urikan-ai-marketplace
/plugin update <PLUGIN_NAME>
/plugin uninstall <PLUGIN_NAME>
```

## Updating

When new plugins or updates are pushed to this repo:

```bash
copilot plugin update <PLUGIN_NAME>
```

Or install `urikan-ai-marketplace-auto-updater` to update every installed plugin from this marketplace automatically on session start.

> The auto-updater runs a PowerShell session-start hook. On macOS and Linux it needs PowerShell 7 (`pwsh`) on your PATH; if `pwsh` is not installed the hook simply does nothing (it never blocks session startup). Install it with `brew install --cask powershell` or your distro's package (`apt install -y powershell`).

## Repository Layout

```
ai-marketplace/
  .github/
    plugin/marketplace.json               # marketplace manifest: lists every published plugin
    schemas/                              # JSON Schemas for the manifest and plugin.json
    workflows/                            # CI: validate.yml + plugin-tests.yml (Playwright)
    CODEOWNERS
  plugins/
    urikan-ai-marketplace-auto-updater/   # session-start hook that auto-updates plugins
    commentable-html/                      # plugin-dir source (the recommended shape)
      pkg/                                 # shipped: plugin.json + skills/commentable-html/
      dev/                                 # NOT shipped: Playwright tests, dev docs
  scripts/validate_marketplace.py         # marketplace validator (CI + pre-commit)
  scripts/validate_markdown.py            # Markdown hygiene validator (CI + pre-commit)
  .githooks/pre-commit                    # runs the validator before each commit
  AGENTS.md  CONTRIBUTING.md  SECURITY.md  MAINTAINING.md  LICENSE  README.md
```

The marketplace manifest lives at `.github/plugin/marketplace.json`. Each entry points at a plugin directory (or a single skill directory) via its `source` field. **Only a plugin's registered `source` is distributed on install** - a `dev/` folder beside it (tests, build tooling, sources) stays in the repo and is never shipped. See [CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](AGENTS.md).

## Trust and safety

Plugins here can ship skills, MCP servers, and session hooks that run code on your machine (for example, the auto-updater runs a PowerShell hook on session start). Review a plugin's contents before installing it. To report a security issue privately, see [SECURITY.md](SECURITY.md). Uninstall anything with `copilot plugin uninstall <name>`.

Every change to `main` is validated in CI: `validate` checks the marketplace manifest, each `plugin.json`, and each `SKILL.md` against JSON Schemas and for consistent `source` paths and versions, and runs the Markdown validator (`scripts/validate_markdown.py`) over the repo's docs; `plugin-tests` runs each plugin's Playwright suite. Run the validators locally with `python scripts/validate_marketplace.py` and `python scripts/validate_markdown.py`, or as a pre-commit hook via `git config core.hooksPath .githooks`.

**Auto-updater note:** installing `urikan-ai-marketplace-auto-updater` is a standing grant - on every session start it runs `copilot plugin update` for your installed plugins, so it silently applies whatever the maintainer later merges. If you prefer to review each update, do not install it and run `copilot plugin update <name>` yourself. See [SECURITY.md](SECURITY.md).

## Reporting Issues

Found a bug in a plugin? [Open an issue](https://github.com/urikanonov/ai-marketplace/issues/new/choose) using the plugin issue form. It asks for the plugin name and version, a description, repro steps, screenshots or attachments, and your environment so problems can be reproduced and fixed quickly.

## Contributing

The `main` branch is protected: every change - including the maintainer's - lands through a pull request that passes CI. Direct pushes to `main` are blocked for everyone. See [CONTRIBUTING.md](CONTRIBUTING.md) for the full workflow and the template for adding a new plugin.

## License

[MIT](LICENSE) (c) Uri Kanonov
