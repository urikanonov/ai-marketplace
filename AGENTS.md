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
  ISSUE_TEMPLATE/             # bug form, feature-request form, new-plugin-idea form, config
  CODEOWNERS, dependabot.yml, pull_request_template.md
plugins/
  <plugin>/pkg/               # shipped source: plugin.json + skills/ (+ hooks/ or .mcp.json)
  <plugin>/dev/               # development-only, NEVER distributed (tests, build tooling, sources, SPEC.md)
site/                         # generated static GitHub Pages site (hub, plugin pages, tutorial)
tests/site/                   # site Playwright suite + SPEC.md (the site's feature spec; not shipped)
scripts/build_site_data.py          # regenerates site/ from sources; --check gates drift in CI
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
`npx playwright install --with-deps chromium`, then `npm test`. The `plugin-tests` job fails if no plugin
test suite is discovered, so an accidentally removed suite cannot pass the gate silently.

To add browser tests to a plugin, drop these under its `dev/` folder (see `plugins/commentable-html/dev/` for a
working example):

- `package.json` with `@playwright/test` and a `"test": "playwright test"` script,
- `playwright.config.js` with `testDir: "./tests"`,
- specs under `dev/tests/`,
- a committed `package-lock.json` (so CI can `npm ci`).

Nothing under `dev/` is distributed. `node_modules/`, `test-results/`, and `playwright-report/` are gitignored.

## Spec-and-test discipline (do not add a feature without a spec row and a test)

Every user-facing surface in this repo has a feature specification that maps each behavior to the
automated test that covers it:

- Each skill/plugin has one at `plugins/<plugin>/dev/SPEC.md` (for example
  `plugins/commentable-html/dev/SPEC.md`).
- The GitHub Pages site has one at `tests/site/SPEC.md`.

The spec is the source of truth for what the surface promises, and every row must name a covering
test. The rule is simple and non-negotiable:

- Do NOT add or change a feature or user-visible behavior without, in the SAME pull request,
  updating the owning spec (add or edit a feature-id row) AND adding or updating an automated test
  that the row names. A feature that is not in the spec, or that the spec does not tie to a passing
  test, is not done.
- Give each behavior a stable `AREA-NN` feature id (for example `CMH-DIFF-11`, `SITE-DEMO-06`).
  Reuse an existing id when you refine its behavior; never renumber or delete a shipped id.
- If a behavior genuinely cannot be automated (a manual authoring convention or an intentional
  non-feature), still add the spec row, mark its coverage `manual`, and list it under that spec's
  "Coverage gaps" section with the reason. Prefer a real test; use `manual` only when automation is
  not possible.
- Removing a feature means removing its spec row and its now-dead test together; for a published
  plugin, also bump the version and update the changelog.

This applies to skill runtime/tooling changes, to the site's pages and its generator
(`scripts/build_site_data.py`), and to any new surface added later. The required CI checks run these
tests (`summary` for the plugin suites, `build` for the site suite and generator unit tests), so a
spec row whose test does not exist or does not pass will not merge.

## Parallel work: use git worktrees under the repo root

When more than one change is in flight at once (multiple agents, or a human working alongside an
agent), do NOT edit the primary working tree from two places at once - concurrent edits to shared,
generated files (the site under `site/`, a plugin's `pkg/dist/`, `examples/`) collide and produce
merge churn. Instead give each independent workstream its own git worktree, checked out UNDER the
repo root in `.worktrees/<name>` (which is gitignored, so the nested checkout is never committed):

```bash
git fetch origin                                             # pull the latest main first
git worktree add -b <branch> .worktrees/<name> origin/main   # branch from the latest main
# ...edit, commit, push, and open a PR from .worktrees/<name>...
git worktree remove .worktrees/<name>                        # once the PR is merged
```

Rules: always branch from the latest `origin/main` (fetch first); keep the primary tree clean and
do each workstream in its own `.worktrees/<name>`; and resolve any conflict on generated files by
REBUILDING (rerun `python scripts/build_site_data.py` and, for the commentable-html layer,
`plugins/commentable-html/dev/tools/build.py`) rather than hand-merging.

## Concurrent-merge clobbers: confirm your change actually survived

Worktrees stop local collisions, but they do NOT stop a subtler hazard: a long-lived PR that rewrites or
regenerates a shared, semi-generated file can silently DROP another PR's edits to that same file - with no
merge conflict - because it replaces the whole region wholesale. This is not hypothetical. The review-loop
diagram and section reorder that shipped in #34 (`site/commentable-html/index.html`) were wiped out an hour
later when #28 regenerated that page from a snapshot that predated #34, even though #28's branch was based
AFTER #34. The plugin runtime, docs, and `CHANGELOG.md` survived; only the hand-edited site page was lost,
and nothing failed - CI stayed green because the clobbered file was still valid.

Highest-risk files (hand-editable AND regenerated or rewritten by tooling or big feature branches):
everything under `site/` (especially the static sections of `site/commentable-html/index.html` and
`site/index.html`), `pkg/**/dist/**`, generated fixtures, and any asset a build stamps. Treat any file that
more than one in-flight PR touches as CONTENDED.

Before you merge:

- Rebase onto the LATEST `origin/main` immediately before merging (strict "up to date with main" is required
  anyway), then run `git --no-pager diff origin/main -- <contended file>` and read every removal: confirm you
  are not reverting content that landed in the meantime. If you are, re-apply it (or rebuild the file from its
  current source) rather than shipping your stale version.
- Prefer SURGICAL edits to shared static files over wholesale regeneration, so a 3-way merge can keep
  concurrent edits. If your change regenerates a whole file (a site page, a dist bundle), regenerate it from
  the CURRENT `origin/main` sources, not from a local snapshot.

After you merge, if `origin/main` has advanced past your merge, VERIFY your change is still present rather
than assuming it stuck - this is how the #34 clobber was found:

```bash
git fetch origin
git --no-pager log --oneline -S "<distinctive string from your change>" origin/main -- <file>
git --no-pager show origin/main:<file> | grep -F "<distinctive string>"
```

The `-S` pickaxe shows exactly which commits added or removed the string; if a later commit removed it, your
change was clobbered and must be re-applied on top of current `main`. Run this for site pages and for any
file a concurrent PR also touched.

## Resolving plugin conflicts when rebasing onto main

When rebasing a plugin PR onto `main` and the same version number has already been merged into main,
you MUST bump the plugin version before resolving conflicts - the CI version-bump gate and the
validator both enforce that the shipped version is newer than the base branch, and
`check_changelog_sync.py` requires a matching release heading in `CHANGELOG.md`.

Steps for a plugin that uses `dev/VERSION` + `tools/build.py` (e.g. `commentable-html`):

1. **Bump `dev/VERSION`**: write the next semver (e.g. `1.4.0` -> `1.5.0`) and mark it resolved.
2. **Resolve `CHANGELOG.md`**: keep main's released `[x.y.z]` section intact; rename your section
   to the new version number and place it above the previously-released heading.
3. **Resolve source files** (non-generated): take your changes; for content conflicts, merge them.
4. **Do NOT hand-merge generated dist files** (`dist/`, `site/`, `manifest.json`, asset registry):
   - Run the plugin's build script to regenerate them with the correct version and hashes:
     ```bash
     python plugins/<plugin>/dev/tools/build.py --assets-dir assets \
       --out-dir plugins/<plugin>/pkg/skills/<plugin>
     ```
   - Then regenerate the site:
     ```bash
     python scripts/build_site_data.py
     ```
5. `git add` all resolved and regenerated files, then `git rebase --continue`.
6. Repeat for each subsequent commit in the rebase that re-conflicts the dist files (each commit
   that touched the source gets a fresh set of generated hashes; always rebuild instead of taking
   either side of the conflict).
7. Validate at the end: `python scripts/validate_marketplace.py` and
   `python plugins/<plugin>/dev/tools/build.py ... --check` must both pass.

## Validate before you commit

```bash
python scripts/validate_marketplace.py        # deps: jsonschema, pyyaml
python scripts/validate_markdown.py            # Markdown hygiene; standard library only
```

Enable the git hooks once per clone so they run automatically (skip a single commit with
`git commit --no-verify`, or a single push with `git push --no-verify`):

```bash
git config core.hooksPath .githooks
```

This turns on two hooks: `pre-commit` runs the manifest and Markdown validators before each commit,
and `pre-push` runs the deterministic gate that mirrors the required CI checks before each push -
the validators, the script unit tests, `check_changelog_sync`, `check_version_bump`, and the
`build_site_data.py` / layer `build.py` / fixtures `--check` drift guards - so a push that would fail
a required check is caught locally first. The slower, occasionally flaky browser (Playwright) suites
are not run by default; set `RUN_E2E=1 git push` to include them (CI is their authoritative gate).

The validator (the pre-commit hook in `.githooks/pre-commit`, and the `validate` CI job which is a required
status check on `main`) enforces:

- `marketplace.json` matches `.github/schemas/marketplace.schema.json`.
- Every entry has a unique `name`, a semver `version`, and a repo-relative `source` (starts with `./`, no `..`).
- Every `source` path exists; a plugin-dir source's `plugin.json` version equals the manifest entry version;
  a skill-dir source has a `SKILL.md` with `name` and `description` front matter.
- Every `plugins/**/plugin.json` matches `.github/schemas/plugin.schema.json` with a semver `version`.
- Development-only folders (`dev/`, `node_modules/`, `__pycache__/`) are ignored. A gitignored one (for example a generated `__pycache__/`) nested inside a shipped source is pruned, since git can never commit or ship it; a tracked one (for example a nested `dev/`) is rejected.

Two more checks need git history to diff against, so the `pre-commit` hook does not run them, but the
`pre-push` hook and CI both do: `check_changelog_sync.py` (a plugin's current version must have a
matching `CHANGELOG.md` release heading, and already-released history must not be edited) runs inside
the required `validate` job, and `check_version_bump.py` (a change to a plugin's shipped source
requires a version bump) runs in the required `version-bump` job. The required `validate` job also runs
`check_forbidden_files.py`, which fails if a secret-bearing file (`.env`, `*.pem`, `*.key`, a keystore,
or a private SSH key) is ever tracked - the enforceable stand-in for a push rule, since GitHub push
rulesets are unavailable on public user-owned repos. The required `site` check runs
`build_site_data.py --check`, which fails if the committed `site/` is stale versus its sources.

## Versioning

- Plugin-directory source: bump the version in BOTH `plugin.json` and the manifest entry, and keep them equal.
- Single-skill source: the manifest entry is the only version; bump it there.
- Add an entry to the plugin's own `CHANGELOG.md` (for example `plugins/commentable-html/CHANGELOG.md`) for every version bump.

## Authorship and contribution policy

- Every plugin is authored as `Uri Kanonov <urikanonov@gmail.com>` in both `plugin.json` and the manifest entry.
- External contributions are for improving EXISTING plugins only. New plugins are authored by the maintainer;
  new-plugin ideas arrive through the "New plugin or skill idea" issue form, not as pull requests that add a plugin.

## Branch and PR rules

- `main` is protected: every change lands through a pull request that passes CI. Direct pushes to
  `main` are blocked for everyone, including the owner/admin (`enforce_admins` is on), so nothing
  reaches `main` without going through the gate. History is squash-only, linear history is required,
  and branches must be up to date with `main` (strict mode) before they merge.
- Native required approvals are `0` because the solo maintainer cannot self-approve, but external
  pull requests are still gated: the required `require-owner-approval` status fails until `@urikanonov`
  submits an approving review. The maintainer's own PRs and Dependabot PRs pass the gate
  automatically, so the maintainer is never blocked. The gate runs from `pull_request_target` and
  publishes a commit status on the PR head, so it reads its logic from the trusted base branch and a
  PR cannot disable it by editing the workflow. Conversation resolution is required, stale approvals
  are dismissed on new commits, and force-push and deletion are disallowed.
- Every non-draft PR gets an automatic Copilot review request (`request-copilot-review.yml`);
  Copilot's review is advisory, and its comment threads are subject to conversation resolution.
- After addressing a PR review comment (code fix, doc update, or clarification), resolve that
  comment thread on the PR before pushing so the conversation stays clean and reviewers can see
  what is still open at a glance.
- Required status checks on `main` (all must be green to merge): `validate` (schema, script unit
  tests, Markdown, changelog sync, and the secret-bearing-file guard), `version-bump` (a
  shipped-source change requires a version bump), `dist-in-sync` (the commentable-html layer's
  committed `dist/` matches its `dev/` source), `actionlint` (every workflow file lints clean),
  `site` (the `pages` workflow regenerates the site and its Playwright suite passes; it runs on
  every PR), `plugin-tests` (the plugin Playwright gate), `require-owner-approval` (an external
  PR carries the maintainer's approving review), and `All conversations resolved` (every review
  thread must be resolved - the job log lists open threads by file, line, author, and body snippet).
  Every check that can catch a break is required, so nothing merges that would break the build or
  the site.
- Do not weaken branch protection (in particular, do not re-enable direct pushes to `main`, and do
  not drop a required check) or bypass the validator.
- Spec-and-test gate (see "Spec-and-test discipline"): a pull request that adds or changes a feature
  must also update the owning spec and a covering test. This applies to site additions too - a change
  to the site pages, its assets, or its generator (`site/**`, `scripts/build_site_data.py`) must
  update `tests/site/SPEC.md` and its Playwright suite / generator unit tests. The required `site`
  check runs the site suite and `build_site_data.py --check`, and `plugin-tests` runs the plugin
  suites, so a new behavior that lacks a passing spec-named test does not merge.

### Why auto-running CI on outside PRs is safe here (do not break this invariant)

Letting an outside contributor's PR run CI without a manual approval is low risk in THIS repo, and
the safety rests on one invariant: a workflow that holds secrets or a write-scoped token must never
check out or run PR-supplied code.

- The CI gates - the `validate`, `version-bump`, `dist-in-sync`, and `actionlint` checks (all jobs of
  `validate.yml`), the `site` check (the `pages` workflow, `pages.yml`), and the `plugin-tests` check
  (the `plugin-tests` workflow) - trigger on plain `pull_request`. Those jobs DO
  execute PR code (the Python validators, `npm ci`, the Playwright suites), but each workflow declares
  `permissions: contents: read` and references no repository secrets (`secrets.*`). For a PR from a
  fork GitHub adds a second, independent layer: it forces a read-only `GITHUB_TOKEN` and withholds
  secrets no matter what the workflow asks for. For a same-repo branch PR (which is what Copilot's
  agent opens - see the next section) that fork sandbox does NOT engage, so the read-only, no-secrets
  property comes entirely from those explicit `permissions:` blocks and the absence of `secrets.*`.
  Either way the PR code runs with nothing to steal and no write access; the residual risk is
  compute/runner abuse (a PR opened purely to run arbitrary code), which the read-only, no-secrets
  execution contains.
- The privileged workflows run in the trusted base-repo context: `request-copilot-review.yml` on
  `pull_request_target`, and `require-owner-approval.yml` on `pull_request_target` plus
  `pull_request_review`. They DO have a write-capable token and secrets even for fork PRs - but they
  never check out or run PR code; they only call the REST API with the PR number and publish a commit
  status. That is what keeps them safe.
- Merge protection is independent of who runs CI: `main` stays protected and `require-owner-approval`
  still blocks external PRs until `@urikanonov` approves, so auto-running CI never lets anyone merge.

Therefore: never add a checkout of the PR head (or any step that runs PR-authored code) to a
`pull_request_target` job or any job that can read secrets; never add secrets (or a `secrets.*`
reference) to a `pull_request` job; and never remove or widen the least-privilege
`permissions: contents: read` blocks on the `pull_request` gates - on a same-repo PR those blocks,
not any GitHub sandbox, are what keep the token read-only. Doing any of these would turn auto-run
into arbitrary code execution with a privileged token, or leak a secret to every collaborator or
Copilot branch. If you must consume PR code with a privileged token, split it: run the untrusted code
in an unprivileged `pull_request` job and do the privileged action in a separate
`pull_request_target` job that only reads metadata.

One caveat is specific to same-repo PRs (a collaborator's or Copilot's branch, never a fork): their
gates run on `pull_request`, so the workflow definition that executes is the PR's OWN head version.
An edit to a `pull_request` gate that widens its `permissions:` or adds a `secrets.*` reference would
therefore take effect on that PR's first auto-run, before any review - and because
`require-owner-approval` is published as a plain head-SHA commit status (not an app-scoped check-run),
a run that granted itself `statuses: write` could in principle post a `success` on that context. Two
repo settings blunt this (the default `GITHUB_TOKEN` is read-only,
`default_workflow_permissions: read`, and Actions cannot approve PRs,
`can_approve_pull_request_reviews: false`), but the real safeguard is to review any diff under
`.github/workflows/**` (the maintainer PR-template already requires this) BEFORE approving a
non-maintainer PR's run - not after merge. So "residual risk is compute/runner abuse" holds only
while the `pull_request` gates' own `permissions:` blocks are never widened in the PR under test.

### Copilot coding-agent workflow approvals (why they keep prompting)

The Actions "Require approval for first-time contributors" (and the broader "Fork pull request
workflows from outside collaborators") settings do NOT govern Copilot coding-agent PRs, so choosing
them does not stop the recurring "Approve and run workflows" prompt. Two reasons:

- Copilot pushes its branches inside this repo and authors its PRs as a bot actor
  (`copilot-swe-agent[bot]`), so they are same-repository PRs, not fork PRs. The
  first-time-contributor and fork-workflow settings only govern PRs opened from actual forks by
  outside collaborators - a different code path - so they never apply to Copilot's in-repo PRs.
- Instead, GitHub gates Actions on Copilot coding-agent PRs through its own separate policy (the
  agent authors code that would then run in CI), independent of the fork settings above.

To stop the prompts, allow the Copilot coding agent's workflows to run from the Copilot coding-agent
policy (org/repo Settings > Copilot > Coding agent), not from the Actions fork settings. Doing so is
safe here for the reason the section above gives, with one caveat specific to these in-repo PRs: they
are NOT fork-sandboxed, so their safety rests on the `pull_request` gates keeping
`permissions: contents: read` and using no secrets, the privileged `pull_request_target` workflows
never running PR code, and `require-owner-approval` still blocking the merge. The only residual
exposure is compute/runner abuse.

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

- Add a feature to a skill (for example a new commentable-html behavior): implement it, add a
  feature-id row to `plugins/<plugin>/dev/SPEC.md` naming a new or updated automated test, add that
  test under `plugins/<plugin>/dev/tests/`, bump versions per the rules, update the plugin's
  `CHANGELOG.md`, and run the validator and the plugin's test suite.
- Add a skill to an existing collection plugin: create `plugins/<plugin>/skills/<skill>/SKILL.md`, register it
  in `marketplace.json`, bump versions per the rules, update the plugin's `CHANGELOG.md`, run the validator.
- Add or change a site behavior: implement it under `site/` or in `scripts/build_site_data.py`, add a
  feature-id row to `tests/site/SPEC.md` naming a covering test, add that test under
  `tests/site/tests/` (browser) or `scripts/test_build_site_data.py` (generator), then regenerate
  with `python scripts/build_site_data.py` and confirm `--check` is clean.
- Fix the auto-updater: edit `hooks/marketplace-update.ps1`, keep it non-blocking and 5.1-safe, bump the plugin
  version in both its `plugin.json` and the manifest entry, update the plugin's `CHANGELOG.md`, run the validator.
- Add browser tests to a plugin: add `plugins/<plugin>/dev/package.json` (with `@playwright/test`),
  `playwright.config.js`, and specs under `dev/tests/`; `plugin-tests.yml` runs them automatically (see
  `plugins/commentable-html/dev/`). Everything under `dev/` stays in the repo but is never distributed.
- Update the site after changing plugin content: the Pages site under `site/` is generated by
  `python scripts/build_site_data.py` (plugins grid, version badge, per-plugin changelog, and the tutorial page
  built from the skill's `docs/TUTORIAL.md`, plus synced demo reports and tutorial images). After editing a
  plugin's `CHANGELOG.md`, its skill `docs/TUTORIAL.md`, or an embedded example report, rerun it and commit the
  result; the required `site` check enforces freshness with `build_site_data.py --check`.
- Rebase a plugin PR onto a newer main: if `main` already merged the same version number, bump the
  plugin version (see "Resolving plugin conflicts when rebasing onto main" above), run the plugin's
  build script (`tools/build.py`) to regenerate dist files with the new version, run
  `build_site_data.py`, then continue the rebase. Never hand-merge generated dist or site files.
