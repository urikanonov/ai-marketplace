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
  <plugin>/pkg/               # shipped source: plugin.json + skills/ (+ hooks/ or .mcp.json)
  <plugin>/dev/               # development-only, NEVER distributed (tests, build tooling, sources, specs)
scripts/validate_marketplace.py     # the validator CI runs; also run it locally
scripts/validate_markdown.py        # Markdown hygiene validator CI runs; also run it locally
.github/workflows/plugin-tests.yml  # runs each plugin's dev/ Playwright suite
SECURITY.md, CODE_OF_CONDUCT.md, LICENSE     # top-level; each plugin has its own CHANGELOG.md
```

## How the manifest maps to plugins

Each object in `marketplace.json`'s `plugins` array has a `source` that points at either:

- a plugin directory that contains a `plugin.json` (the default shape - for example the auto-updater at
  `./plugins/urikan-ai-marketplace-auto-updater`, or `commentable-html` at `./plugins/commentable-html/pkg`), or
- a single skill directory that contains just a `SKILL.md` (the minimal shape, no `plugin.json`).

A `SKILL.md` begins with YAML front matter that must have a non-empty `name` and `description`; the
`description` should say what the skill does and when to trigger it. Prefer the plugin-directory shape (see
"Choosing the source shape") because it can grow to add hooks, MCP servers, and more skills.

## Shipped vs development files (what gets distributed)

`copilot plugin install` copies ONLY the marketplace entry's `source` subtree onto the user's machine.
Anything else in the repo is never distributed. Use this to keep tests, build tooling, canonical sources,
and specs in the repo without shipping them.

Convention: put non-distributed content in a `dev/` folder beside the shipped source. `dev/` (and
`node_modules/`, `__pycache__/`) is reserved - the validator ignores it, and it rejects any `source` that
resolves into or contains one of these folders (that would ship it).

```
plugins/<plugin>/
  pkg/                   # shipped (the source): plugin.json + skills/ + any runtime assets/scripts
  dev/                   # NOT shipped: tests/, build tooling, canonical sources, SPEC.md, DEVELOPMENT.md
```

If a plugin builds artifacts (a bundled HTML/CSS/JS, for example), commit the BUILT OUTPUTS into the shipped
folder and keep the INPUTS and the builder under `dev/`; install runs no build step. Add a CI check that the
committed outputs match a fresh build.

### Choosing the source shape

Prefer a plugin-dir source; it is the most forward-compatible.

- Plugin-dir source (recommended, `source: ./plugins/<plugin>/pkg`, where `pkg/` contains a `plugin.json`):
  a real plugin manifest that can declare multiple skills, session hooks, and an MCP server, with
  version/author/keywords co-located in the plugin. Because the whole source subtree ships, keep the shipped
  content in `pkg/` and `dev/` as its sibling so dev files stay out of the shipped subtree. The `plugin.json`
  version must equal the manifest entry version (CI enforces this). `commentable-html` uses this shape.
- Skill-dir source (minimal, `source: ./plugins/<plugin>/skills/<skill>`): a single `SKILL.md` with no
  `plugin.json`; the version lives only in the manifest entry. Fine for a one-off skill, but it cannot grow
  to hooks/MCP/multiple skills without converting to a plugin-dir source.

## Testing in CI

`.github/workflows/plugin-tests.yml` discovers every plugin with a Node/Playwright suite at
`plugins/<plugin>/dev/package.json` and runs it in a matrix (one job per plugin): Node 22, `npm ci --ignore-scripts`,
`npx playwright install --with-deps chromium`, then `npm test`. If no plugin has such a suite the job is a
no-op.

To add browser tests to a plugin, drop these under its `dev/` folder (see `plugins/commentable-html/dev/` for a
working example):

- `package.json` with `@playwright/test` and a `"test": "playwright test"` script,
- `playwright.config.js` with `testDir: "./tests"`,
- specs under `dev/tests/`,
- a committed `package-lock.json` (so CI can `npm ci`).

Nothing under `dev/` is distributed. `node_modules/`, `test-results/`, and `playwright-report/` are gitignored.

## Validate before you commit

```bash
python scripts/validate_marketplace.py        # deps: jsonschema, pyyaml
python scripts/validate_markdown.py            # Markdown hygiene; standard library only
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
- Development-only folders (`dev/`, `node_modules/`, `__pycache__/`) are ignored. A gitignored one (for example a generated `__pycache__/`) nested inside a shipped source is pruned, since git can never commit or ship it; a tracked one (for example a nested `dev/`) is rejected.

## Versioning

- Plugin-directory source: bump the version in BOTH `plugin.json` and the manifest entry, and keep them equal.
- Single-skill source: the manifest entry is the only version; bump it there.
- Add an entry to the plugin's own `CHANGELOG.md` (for example `plugins/commentable-html/CHANGELOG.md`) for every version bump.

## Authorship and contribution policy

- Every plugin is authored as `Uri Kanonov <urikanonov@gmail.com>` in both `plugin.json` and the manifest entry.
- External contributions are for improving EXISTING plugins only. New plugins are authored by the maintainer;
  new-plugin ideas arrive through the plugin/feature request issue form, not as pull requests that add a plugin.

## Branch and PR rules

- `main` is protected: 1-approval PRs required, conversation resolution required, no force-push or deletion.
- The owner (`urikanonov`, an admin) can push to `main` directly; everyone else must open a PR.
- Required status checks on `main`: `validate` and `summary` (the `plugin-tests` gate). Changes to owned paths require code-owner review (`CODEOWNERS`).
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
  in `marketplace.json`, bump versions per the rules, update the plugin's `CHANGELOG.md`, run the validator.
- Fix the auto-updater: edit `hooks/marketplace-update.ps1`, keep it non-blocking and 5.1-safe, bump the plugin
  version in both its `plugin.json` and the manifest entry, update the plugin's `CHANGELOG.md`, run the validator.
- Add browser tests to a plugin: add `plugins/<plugin>/dev/package.json` (with `@playwright/test`),
  `playwright.config.js`, and specs under `dev/tests/`; `plugin-tests.yml` runs them automatically (see
  `plugins/commentable-html/dev/`). Everything under `dev/` stays in the repo but is never distributed.
