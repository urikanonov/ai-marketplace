# AI Marketplace

A personal marketplace of AI-oriented plugins for the [GitHub Copilot CLI](https://github.com/github/copilot-cli). It bundles reusable skills, hooks, and MCP servers that you can install into any Copilot session with a single command.

Every plugin here is designed to make AI-assisted development workflows faster and more repeatable. Install what you need by name, or add the whole marketplace and browse.

**Website:** [urikanonov.github.io/ai-marketplace](https://urikanonov.github.io/ai-marketplace/) - browse the plugins and try the commentable-html review surface live in your browser.

## Available Plugins

| Plugin | Description | Install |
|--------|-------------|---------|
| `commentable-html` | Turn a standalone HTML report, plan, dashboard, or design doc into a commentable review surface: reviewers select any paragraph, table cell, code block, KQL query, chart, image, or Mermaid diagram, leave inline comments, and export the whole thread back to the agent. Drastically shortens the AI planning and iteration loop by reviewing the artifact in place | `copilot plugin install commentable-html@urikan-ai-marketplace` |
| `urikan-ai-marketplace-auto-updater` | Automatically updates all installed plugins from this marketplace on session start (opt-in) | `copilot plugin install urikan-ai-marketplace-auto-updater@urikan-ai-marketplace` |

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

Every change to `main` goes through a pull request and must pass the required CI checks: `validate` (the marketplace manifest, each `plugin.json`, and each `SKILL.md` against JSON Schemas and for consistent `source` paths and versions, plus the Markdown validator, the script unit tests, and changelog sync), `version-bump` (a shipped-source change needs a version bump), `dist-in-sync` (a plugin's committed build output matches its `dev/` source), `actionlint` (every GitHub Actions workflow lints clean), `site` (the Pages site regenerates cleanly and its Playwright suite passes), and `plugin-tests` (the plugin Playwright gate). Run the validators locally with `python scripts/validate_marketplace.py` and `python scripts/validate_markdown.py`, or enable the git hooks (a `pre-commit` validator and a `pre-push` gate) with `git config core.hooksPath .githooks`. See [CONTRIBUTING.md](CONTRIBUTING.md) for the full gate.

**Auto-updater note:** installing `urikan-ai-marketplace-auto-updater` is a standing grant - on every session start it runs `copilot plugin update` for your installed plugins, so it silently applies whatever the maintainer later merges. If you prefer to review each update, do not install it and run `copilot plugin update <name>` yourself. See [SECURITY.md](SECURITY.md).

## Reporting issues and requesting features

Found a bug in a plugin? [Open a bug report](https://github.com/urikanonov/ai-marketplace/issues/new?template=plugin-issue.yml). It asks for the plugin name and version, a description, repro steps, screenshots or attachments, and your environment so problems can be reproduced and fixed quickly.

Want a plugin to do more? [Request a feature](https://github.com/urikanonov/ai-marketplace/issues/new?template=feature-request.yml) for an existing plugin, or [suggest a brand-new plugin or skill](https://github.com/urikanonov/ai-marketplace/issues/new?template=plugin-request.yml). The [issue chooser](https://github.com/urikanonov/ai-marketplace/issues/new/choose) lists every form.

## Contributing

The `main` branch is protected: every change - including the maintainer's - lands through a pull request that passes CI. Direct pushes to `main` are blocked for everyone. See [CONTRIBUTING.md](CONTRIBUTING.md) for the full workflow, including how to improve an existing plugin and how new plugins are added.

## License

[MIT](LICENSE) (c) Uri Kanonov
