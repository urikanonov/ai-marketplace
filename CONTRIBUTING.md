# Contributing

Thanks for your interest in this AI marketplace. This guide covers how contributions work, the branch rules, and how to improve an existing plugin.

## How contributions work

This is a personal marketplace. Every plugin is authored and maintained by Uri Kanonov, so authorship and support stay consistent across the catalog.

- Improving an existing plugin is the main way to contribute. Bug fixes, clearer skill instructions, better docs, and portability fixes are all welcome as pull requests.
- New plugins are added by the maintainer. If you have an idea for a new plugin or skill, please open a [plugin or feature request](https://github.com/urikanonov/ai-marketplace/issues/new/choose) instead of submitting a new plugin. The maintainer will author it. This keeps every plugin under a single, supportable authorship.

## Branch rules

- `main` is protected: every change lands through a pull request that passes CI.
- Direct pushes to `main` are blocked for everyone, including the owner. The maintainer's own changes go through a PR too.
- Contribute through a pull request: fork the repo (or push a feature branch if you are a collaborator) and open a PR against `main`. External pull requests require an approving review from the maintainer (@urikanonov) before they can merge - the `require-owner-approval` check enforces this. Conversation resolution is required, stale approvals are dismissed when you push new commits, and force-push and deletion are disallowed. Every non-draft PR is also sent to Copilot for an advisory review automatically.
- What must be green to merge: the required checks `validate` (schema, script unit tests, Markdown, changelog sync, and a secret-bearing-file guard), `version-bump` (a shipped-source change needs a version bump), `build-check` (the commentable-html layer's committed `dist/` matches its `dev/` source), `build` (the site regenerates cleanly and its Playwright suite passes), `summary` (the `plugin-tests` gate), and `require-owner-approval` (external PRs carry the maintainer's approving review). New plugins are maintainer-authored (see [MAINTAINING.md](MAINTAINING.md)).

## One-time setup

Enable the pre-commit hook so the validator runs automatically before every commit (it needs python with
`jsonschema` and `pyyaml`). This catches issues locally before CI, even for the maintainer:

```bash
pip install jsonschema pyyaml
git config core.hooksPath .githooks
```

Skip the hook for a single commit with `git commit --no-verify`.

## Improving an existing plugin

1. Find the plugin under `plugins/`. A plugin is either a single skill directory (a `SKILL.md` with `name` and `description` front matter) or a plugin directory with a `plugin.json` (used by hook and MCP plugins, such as the auto-updater).
2. Make your change: fix a hook, sharpen a `SKILL.md`'s instructions, correct docs, or improve portability.
3. Bump the version (see Versioning below) and add a matching entry to that plugin's `CHANGELOG.md` (for example `plugins/commentable-html/CHANGELOG.md`).
4. Run the validators, then open a pull request against `main`:
   ```bash
   python scripts/validate_marketplace.py
   python scripts/validate_markdown.py
   ```
   They also run in CI and are required status checks on `main`. `validate_marketplace.py` verifies the manifest against its JSON Schema, that every `source` path exists, that plugin-directory sources have a `plugin.json` whose version matches the manifest entry, and that skill sources have a `SKILL.md` with `name` and `description` front matter. `validate_markdown.py` checks every Markdown file for non-ASCII "smart" characters, local filesystem paths, and broken relative links.

   CI runs two more checks that need git history and so are awkward to run locally: `check_changelog_sync.py` (every plugin's current version must have a matching `CHANGELOG.md` release heading, and already-released changelog history must not be edited) runs inside the required `validate` job, and `check_version_bump.py` (changing a plugin's shipped source requires a version bump) runs in the required `version-bump` job. If you change a plugin's `CHANGELOG.md`, `docs/TUTORIAL.md`, or an example report that the site embeds, also regenerate the site data with `python scripts/build_site_data.py` and commit the result; the required `build` check fails if the committed `site/` is stale versus its sources.

### Versioning: which file is the source of truth

There are two shapes of manifest entry, and they version differently:

- Plugin-directory source (recommended - for example `commentable-html` at `source: ./plugins/commentable-html/pkg`, or the auto-updater): the source directory has its own `plugin.json`. Bump the version in BOTH `plugin.json` and the manifest entry, and keep them equal - CI enforces that they match.
- Single-skill source (minimal - `source: ./plugins/<plugin>/skills/<skill>`): the skill directory has only a `SKILL.md` and no `plugin.json`, so the manifest entry is the single source of truth. Bump the version only in the manifest entry.

## Adding a new plugin (maintainer)

New plugins are authored by the maintainer. A plugin is a directory under `plugins/` plus one entry in `.github/plugin/marketplace.json`. The mechanics are documented in [AGENTS.md](AGENTS.md), which is also the guide for developing in this repo with an AI agent.

## Tests and development files

Only a plugin's registered `source` is distributed when someone installs it. Keep tests, build tooling, canonical sources, and maintainer docs in a `dev/` folder beside the shipped source (`plugins/<plugin>/dev/`). That folder stays in the repo - versioned and testable - but is never shipped. The validator ignores `dev/` and rejects any `source` that would ship it. Browser tests (Playwright) placed under `plugins/<plugin>/dev/` are run automatically by the `plugin-tests` workflow; see `plugins/commentable-html/dev/` for a working example. See [AGENTS.md](AGENTS.md) for the full structure and how to choose the source shape.

## Conventions

- Every plugin is authored as `Uri Kanonov <urikanonov@gmail.com>`.
- Keep skill descriptions action-oriented so the model knows when to trigger them.
- Use semantic versioning for every `version` field.
- Text is plain ASCII (no em or en dashes, no ellipsis characters) and files use LF line endings, per `.editorconfig` and `.gitattributes`.
