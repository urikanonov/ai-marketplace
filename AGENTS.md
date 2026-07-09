# AGENTS.md

Guidance for AI coding agents (and humans) developing in this repository. Read this before making changes.

## What this repo is

A personal marketplace of AI-oriented plugins for the GitHub Copilot CLI. Users add the marketplace with
`copilot plugin marketplace add https://github.com/urikanonov/ai-marketplace` and install plugins with
`copilot plugin install <name>@urikan-ai-marketplace`. The marketplace name (used after `@`) is
`urikan-ai-marketplace`, defined in the manifest below.

## Layout

```
.github/
  plugin/marketplace.json     # marketplace manifest: the list of published plugins (source of truth)
  schemas/                    # JSON Schemas for marketplace.json and plugin.json
  workflows/validate.yml      # CI: validates the manifest, plugins, and skills on every PR/push
  ISSUE_TEMPLATE/             # bug form, feature/plugin-request form, config
  CODEOWNERS, dependabot.yml, pull_request_template.md
plugins/
  <plugin>/plugin.json        # plugin manifest (hook/MCP/skills-collection plugins)
  <plugin>/hooks.json, hooks/ # session hooks (see the auto-updater)
  <plugin>/skills/<skill>/SKILL.md   # a skill: YAML front matter (name, description) + instructions
scripts/validate_marketplace.py  # the validator CI runs; also run it locally
CHANGELOG.md, SECURITY.md, CODE_OF_CONDUCT.md, LICENSE
```

## How the manifest maps to plugins

Each object in `marketplace.json`'s `plugins` array has a `source` that points at either:

- a plugin directory that contains a `plugin.json` (for example the auto-updater at
  `./plugins/urikan-ai-marketplace-auto-updater`), or
- a single skill directory that contains a `SKILL.md` and no `plugin.json` of its own (for example
  `./plugins/example-skills/skills/hello-world`).

Both shapes are valid. A `SKILL.md` begins with YAML front matter that must have a non-empty `name` and
`description`; the `description` should say what the skill does and when to trigger it.

## Validate before you commit

```bash
python scripts/validate_marketplace.py        # deps: jsonschema, pyyaml
```

Enable the pre-commit hook once per clone so this runs automatically before every commit (skip a single
commit with `git commit --no-verify`):

```bash
git config core.hooksPath .githooks
```

The validator (the pre-commit hook in `.githooks/pre-commit`, and the `validate` CI job which is a required
status check on `main`) enforces:

- `marketplace.json` matches `.github/schemas/marketplace.schema.json`.
- Every entry has a unique `name`, a semver `version`, and a repo-relative `source` (starts with `./`, no `..`).
- Every `source` path exists; a plugin-dir source's `plugin.json` version equals the manifest entry version;
  a skill-dir source has a `SKILL.md` with `name` and `description` front matter.
- Every `plugins/**/plugin.json` matches `.github/schemas/plugin.schema.json` with a semver `version`.

## Versioning

- Plugin-directory source: bump the version in BOTH `plugin.json` and the manifest entry, and keep them equal.
- Single-skill source: the manifest entry is the only version; bump it there.
- Add a `CHANGELOG.md` entry under the plugin name for every version bump.

## Authorship and contribution policy

- Every plugin is authored as `Uri Kanonov <urikanonov@gmail.com>` in both `plugin.json` and the manifest entry.
- External contributions are for improving EXISTING plugins only. New plugins are authored by the maintainer;
  new-plugin ideas arrive through the plugin/feature request issue form, not as pull requests that add a plugin.

## Branch and PR rules

- `main` is protected: 1-approval PRs required, conversation resolution required, no force-push or deletion.
- The owner (`urikanonov`, an admin) can push to `main` directly; everyone else must open a PR.
- Do not weaken branch protection or bypass the validator.

## The auto-updater hook (portability notes)

`plugins/urikan-ai-marketplace-auto-updater` runs `hooks/marketplace-update.ps1` on session start.

- Keep it non-blocking: wrap work in `try/catch` and log failures under `plugin-data`; never let it throw.
- Use the nested two-argument `Join-Path (Join-Path a b) c`. The three-argument form
  (`Join-Path a b c`) throws on Windows PowerShell 5.1 and would silently disable the updater.
- The bash hook is guarded on `pwsh` being installed; on macOS/Linux the updater needs PowerShell 7.
- It excludes itself by folder name (a plugin cannot update itself while its hook is running).

## House style

- Plain ASCII only. Never use em dashes, en dashes, or ellipsis characters; use `-`, `--`, or `...`.
- LF line endings and the formatting in `.editorconfig`; `.gitattributes` normalizes on commit.
- Comment only what the code cannot say; keep comments minimal.
- Pin third-party GitHub Actions by full commit SHA (Dependabot keeps them current).
- Never commit secrets.

## Common tasks

- Add a skill to an existing collection plugin: create `plugins/<plugin>/skills/<skill>/SKILL.md`, register it
  in `marketplace.json`, bump versions per the rules, update `CHANGELOG.md`, run the validator.
- Fix the auto-updater: edit `hooks/marketplace-update.ps1`, keep it non-blocking and 5.1-safe, bump the plugin
  version in both its `plugin.json` and the manifest entry, update `CHANGELOG.md`, run the validator.
