# AI Marketplace

A personal marketplace of AI-oriented plugins for the [GitHub Copilot CLI](https://github.com/github/copilot-cli). It bundles reusable skills, hooks, and MCP servers that you can install into any Copilot session with a single command.

Every plugin here is designed to make AI-assisted development workflows faster and more repeatable. Install what you need by name, or add the whole marketplace and browse.

## Available Plugins

| Plugin | Description | Install |
|--------|-------------|---------|
| `urikan-ai-marketplace-auto-updater` | Automatically updates all installed plugins from this marketplace on session start (opt-in) | `copilot plugin install urikan-ai-marketplace-auto-updater@urikan-ai-marketplace` |
| `hello-world` | Minimal example skill that doubles as a starter template for new plugins | `copilot plugin install hello-world@urikan-ai-marketplace` |

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
/plugin install hello-world@urikan-ai-marketplace
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
    plugin/
      marketplace.json     # marketplace manifest: lists every published plugin
    pull_request_template.md
  plugins/
    urikan-ai-marketplace-auto-updater/   # session-start hook that auto-updates plugins
    example-skills/                        # collection plugin; template for new skills
      skills/
        hello-world/
          SKILL.md
  CONTRIBUTING.md
  LICENSE
  README.md
```

The marketplace manifest lives at `.github/plugin/marketplace.json`. Each entry points at a plugin directory (or a single skill directory) via its `source` field. See [CONTRIBUTING.md](CONTRIBUTING.md) to add your own plugin.

## Trust and safety

Plugins here can ship skills, MCP servers, and session hooks that run code on your machine (for example, the auto-updater runs a PowerShell hook on session start). Review a plugin's contents before installing it. To report a security issue privately, see [SECURITY.md](SECURITY.md). Uninstall anything with `copilot plugin uninstall <name>`.

Every change to `main` is validated in CI (`.github/workflows/validate.yml`): the marketplace manifest, each `plugin.json`, and each `SKILL.md` are checked against JSON Schemas and for consistent `source` paths and versions. You can run the same check locally with `python scripts/validate_marketplace.py`, or enable it as a pre-commit hook with `git config core.hooksPath .githooks`.

## Reporting Issues

Found a bug in a plugin? [Open an issue](https://github.com/urikanonov/ai-marketplace/issues/new/choose) using the plugin issue form. It asks for the plugin name and version, a description, repro steps, screenshots or attachments, and your environment so problems can be reproduced and fixed quickly.

## Contributing

The `main` branch is protected. The repository owner pushes directly; everyone else contributes through a pull request. See [CONTRIBUTING.md](CONTRIBUTING.md) for the full workflow and the template for adding a new plugin.

## License

[MIT](LICENSE) (c) Uri Kanonov
