# Contributing

Thanks for your interest in adding to this AI marketplace. This guide covers the branch rules and the exact steps to publish a new plugin.

## Branch rules

- `main` is protected.
- The repository owner (`urikanonov`) can push to `main` directly.
- Everyone else contributes through a pull request. Fork the repo (or push a feature branch if you are a collaborator), open a PR against `main`, and wait for it to be reviewed and merged. Direct pushes to `main` from non-owners are rejected.

## Adding a new plugin

A plugin is a directory under `plugins/` plus one entry in `.github/plugin/marketplace.json`.

### 1. Create the plugin directory

For a skills plugin, the minimal layout is:

```
plugins/<your-plugin>/
  plugin.json
  skills/
    <your-skill>/
      SKILL.md
```

`plugin.json` describes the plugin:

```json
{
  "name": "your-plugin",
  "description": "What this plugin does.",
  "version": "1.0.0",
  "author": { "name": "Uri Kanonov", "email": "urikanonov@gmail.com" },
  "keywords": ["ai", "example"],
  "skills": "skills/"
}
```

`SKILL.md` starts with YAML front matter (a `name` and a `description`), followed by the instructions the model should follow:

```markdown
---
name: your-skill
description: >
  One or two sentences describing what the skill does and when to use it.
---

# Your Skill

Step-by-step guidance goes here.
```

Copy `plugins/example-skills/` as a starting point.

### 2. Register it in the marketplace manifest

Add an entry to the `plugins` array in `.github/plugin/marketplace.json`:

```json
{
  "name": "your-skill",
  "description": "What this skill does.",
  "version": "1.0.0",
  "source": "./plugins/your-plugin/skills/your-skill",
  "author": { "name": "Uri Kanonov", "email": "urikanonov@gmail.com" },
  "homepage": "https://github.com/urikanonov/ai-marketplace/tree/main/plugins/your-plugin/skills/your-skill",
  "repository": "https://github.com/urikanonov/ai-marketplace",
  "license": "MIT",
  "category": "example",
  "keywords": ["ai", "example"]
}
```

`source` may point at a whole plugin directory (for hook or MCP plugins) or at a single skill directory (for individual skills), matching the pattern of the existing entries.

### 3. Validate and open a PR

Run the validator locally before opening a PR. It also runs in CI and is a required status check on `main`:

```bash
python scripts/validate_marketplace.py
```

It verifies the manifest against its JSON Schema, that every `source` path exists, that plugin-directory
sources have a `plugin.json` whose version matches the manifest entry, and that skill sources have a
`SKILL.md` with `name` and `description` front matter. Then open a pull request against `main`.

### Versioning: which file is the source of truth

There are two shapes of manifest entry, and they version differently:

- Plugin-directory source (for example the auto-updater, `source: ./plugins/<plugin>`): the directory has
  its own `plugin.json`. Bump the version in BOTH `plugin.json` and the manifest entry, and keep them
  equal - CI enforces that they match.
- Single-skill source (for example `hello-world`, `source: ./plugins/<plugin>/skills/<skill>`): the skill
  directory has only a `SKILL.md` and no `plugin.json` of its own, so the manifest entry is the single
  source of truth. Bump the version only in the manifest entry.

Add a matching entry to [CHANGELOG.md](CHANGELOG.md) whenever you bump a version.

## Conventions

- Author every plugin as `Uri Kanonov <urikanonov@gmail.com>`.
- Keep skill descriptions action-oriented so the model knows when to trigger them.
- Use semantic versioning for every `version` field.
