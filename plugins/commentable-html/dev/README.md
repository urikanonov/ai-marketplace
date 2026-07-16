# commentable-html development

This `dev/` folder is the development home for `commentable-html`. It is not copied when users install the marketplace plugin. The editable + built skill tree (the STAGE) lives beside it at `dev/skill/`; `build.py` assembles the STAGE's bulky runtime into a single `skill-resources.zip`, and the plugin ships a minimal `../pkg` (`plugin.json`, the SessionStart hook, and `skills/commentable-html/` holding only `SKILL.md`, `LICENSE`, and `skill-resources.zip`) so the installer writes very few files. A SessionStart hook extracts the zip on first run. This folder keeps the canonical assets, build tooling, tests, fixtures, and spec in the source repository.

## Directory layout

```text
dev/
  assets/                 canonical CSS, JS, and template shell sources
  tools/                  maintainer-only build and screenshot tools
  skill/                  STAGE: the full editable + built skill (source of truth for tests)
    SKILL.md              shipped skill instructions
    dist/                 generated PORTABLE.html, NONPORTABLE.html, companions, manifest.json
    tools/                runtime Python tools
    references/           reference docs the agent consults
    vendor/               deck vendor templates
  tests/                  Python test_*.py suites, Playwright *.spec.js suites, helpers, and fixtures
  SPEC.md                 behavioral spec (generated from dev/spec/ partials by build_spec.py)
  package.json, package-lock.json, playwright.config.js
../pkg/
  plugin.json             marketplace plugin manifest
  hooks.json, hooks/      the SessionStart extractor hook (Copilot + Claude configs, extract_resources.py)
  skills/commentable-html/
    SKILL.md, LICENSE     shipped unzipped (the agent discovers the skill before extraction)
    skill-resources.zip   the bulky runtime (tools/references/dist/vendor), extracted on first run
../docs/                   tutorial and tutorial images (NOT shipped; published on the site)
../examples/               worked prompts and example reports (NOT shipped; published on the site)
```

## Single source of truth

Edit `dev/assets/` only when changing the review layer:

- `assets/css/NN-topic.css` - layer stylesheet partials (directory-sorted into one bundle by the build).
- `assets/js/NN-topic.js` - runtime partials (directory-sorted into one bundle by the build). One partial declares the `CMH_VERSION` const, stamped from `VERSION` by the build; do not hand-edit the const.
- `assets/template.shell.html` - shell with the five commentable regions, toolbar, sidebar, and demo content.

The version lives in `dev/VERSION` (plain-text semver) and is the only hand-edited version. `build.py` reads it and stamps the runtime `CMH_VERSION` const, `../pkg/plugin.json`, the marketplace entry, and each generated document's `<meta name="commentable-html-version">`. Companion filenames are version-agnostic, so a version bump never renames dist files.

Everything under `dev/skill/dist/` is generated (and packed into `skill-resources.zip`) so installs do not run a build step. Do not hand-edit `dist/PORTABLE.html`, `dist/NONPORTABLE.html`, the companions, or `manifest.json`.

## Build pipeline

The one-command build from the repo root regenerates every artifact in order (dist -> SPEC -> fixtures -> screenshots -> site):

```powershell
python scripts\rebuild_all.py            # or --check to verify drift without writing
```

To run only the layer build, from `dev/` point the builder at the STAGE and the minimal shipped pkg:

```powershell
python tools\build.py --assets-dir assets --out-dir skill --pkg-dir ..\pkg\skills\commentable-html --examples-dir ..\examples
```

Add `--check` to any of these for the CI drift guard (write nothing, fail on drift).

To bump the version, edit `VERSION` then run `build.py`; it restamps every version spot (the layer `CMH_VERSION` const, `../pkg/plugin.json`, the marketplace entry, and each document's `<meta name="commentable-html-version">`). Companion filenames are version-agnostic, so the bump does not rename any dist files. `build.py --check` fails if any stamped spot drifts from `VERSION`.

To bump mermaid (usually a Dependabot PR against `package.json`): the mermaid CDN version is single-sourced from the `mermaid` dependency in `package.json`, so after the version changes just run `npm install` (updates `node_modules` + `package-lock.json`) then `python tools/build.py` and `node tests/fixtures/generate.mjs`. The build stamps the new `mermaid@<version>` into `template.shell.html` -> `dist/PORTABLE.html`/`NONPORTABLE.html` and into the `examples/*.html` reports; the fixtures derive from `dist/`, so they follow automatically. `build.py --check` (the `dist-in-sync` gate) fails clearly if any shipped mermaid pin drifts from `package.json`, and `tests/helpers.js` `routeMermaidLocal` only needs the served template's major to match the vendored `node_modules/mermaid` major. Do not hand-edit the `mermaid@<version>` string in any generated file.

## Python suite

The Python tests use standard-library `unittest`. They import the runtime tools from `dev/skill/tools` (the STAGE, which `build.py` packs into `skill-resources.zip`) and validate the generated artifacts in `dev/skill`, so a pass covers what ships once extracted.

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

| Suite | Coverage |
| --- | --- |
| `tests/test_validate_*.py` | Split validator regressions covering layer structure, validator flags and exit codes, encoding and newline edge cases, NonPortable detection, companion references, version handshake, banner behavior, missing files, and a real `dist/NONPORTABLE.html` positive control. |
| `tests/test_validate_charts.py` | Chart.js embedding checks, including loader safety, chart data JSON, init ordering, accessibility, `cm-skip`, and network-failure guards. |
| `tests/test_build.py` | Build drift, generated file parity, idempotence, inline round trips, version single-sourcing, manifest hashes, registry round trips, template validation, stale dist detection, and duplicate-version rejection. |
| `tests/test_mark_handled.py` | Handled-id append, dedupe, order, unsafe ids, missing or duplicate blocks, surgical edits, newline preservation, bundle parsing, and CLI behavior. |
| `tests/test_kql_highlight.py` | KQL tokenization, theming, HTML safety, and idempotence. |
| `tests/test_kusto_link.py` | Run in Azure Data Explorer deep-link encoding, cluster validation, flags, stdin, and deterministic output. |
| `tests/test_inline_images.py` | Local image inlining, untouched remote/data/fragment sources, protected script/style/pre regions, path traversal refusal, query/fragment handling, missing images, strict mode, and output paths. |
| `tests/test_examples.py` | Worked example presence, validation, self-contained images, and broad content-feature coverage. |

## Playwright suite

Install once from `dev/`:

```powershell
npm ci
npx playwright install chromium
```

Run the browser suite with the tutorial screenshot drift check:

```powershell
npm test
```

Run Playwright directly while iterating on browser-only changes:

```powershell
npx playwright test
npx playwright test --ui
npx playwright test --headed
npx playwright test -g "Export standalone"
npx playwright show-report
```

The browser suite covers load/init, light and dark themes, standalone and NonPortable modes, toolbar and sidebar controls, text selection and composer behavior, comment edit/delete/clear flows, copy bundle fallbacks, handled-id pruning, embedded comments, portable/plain/nonportable exports, Mermaid comments, image and chart comments, code block copy, diff rendering and anchors, KQL blocks, TOC behavior, network-deny flows, stale-anchor degradation, overlapping selection guards, fixture freshness, and randomized anchoring/state-machine checks. Mermaid is served from the locally vendored `node_modules/mermaid` in tests, so the suite does not require a live CDN.

## Validate the shipped skill

Run the shipped validator against generated outputs and examples from `dev/`:

```powershell
python skill\tools\validate\validate.py --strict `
  skill\dist\PORTABLE.html `
  ..\examples\report-community-garden.html `
  ..\examples\report-taxi.html
```

From `dev\skill`, the same check is:

```powershell
python tools\validate\validate.py --strict dist\PORTABLE.html ..\..\examples\report-community-garden.html ..\..\examples\report-taxi.html
```

## Rebuilding the example images

The shipped example reports are single self-contained files with their images inlined as data URIs, so the top-level `../examples/` has no `images/` folder. The source images for the community garden example live here in `dev/examples/images/` (kept for reproducibility, not shipped). To re-inline them into a freshly authored example and validate it, run from `dev/`:

```powershell
python skill\tools\authoring\inline_images.py <report>.html --base examples\images --strict
python skill\tools\validate\validate.py <report>.html
```

The taxi example has no images, so it needs no inlining - just validate it.

## Regenerating tutorial screenshots

The tutorial (`../docs/TUTORIAL.md`) embeds nine `garden-*.png`
screenshots captured from the community-garden example. Regenerate all of them with one command from
`dev/`:

```powershell
npm run shots
```

`npm run shots` runs `tools/capture_tutorial.mjs` with no arguments: it drives
`../examples/report-community-garden.html` and writes
`garden-01-top-light.png` through `garden-09-copyall.png` into
`../docs/assets/` at a fixed 1320x900 viewport (2x scale). It pins the
capture clock, random seed, viewport, locale, timezone, reduced motion, browser font rendering flags,
and capture fonts, then normalizes PNG output so repeated runs produce byte-identical files on the
same browser environment. Check committed screenshots for drift without rewriting them:

```powershell
npm run shots:check
```

To capture a different example, pass overrides:

```powershell
node tools\capture_tutorial.mjs <example.html> <outDir> <prefix>
```

Screenshot rendering is environment-specific (fonts and anti-aliasing differ across operating
systems), so regenerate on the canonical environment where the images are maintained. After
regenerating, rebuild the site so its synced tutorial images stay current: run
`python scripts/rebuild_all.py` from the repo root. `npm test` and
`python scripts/rebuild_all.py --check` both run the screenshot drift check. The determinism is
covered by `tests/54-tutorial-shots.spec.js`.

## Fixtures workflow

Interaction and fuzz tests use generated fixtures under `tests/fixtures/`, including the inline `kitchen-sink.html` and the NonPortable `nonportable/kitchen-sink.html`. They are derived from the current shipped `dist/PORTABLE.html`, `dist/`, and `tests/fixtures/sample-content.html`.

After changing the layer or fixture sample content, rebuild and refresh fixtures:

```powershell
python tools\build.py --assets-dir assets --out-dir skill --pkg-dir ..\pkg\skills\commentable-html --examples-dir ..\examples
node tests\fixtures\generate.mjs
```

Check fixture freshness:

```powershell
node tests\fixtures\generate.mjs --check
```

## What is committed

Committed source-repo files include `dev/assets/`, `dev/tools/`, `dev/tests/`, `dev/SPEC.md`, `dev/package.json`, `dev/package-lock.json`, `dev/playwright.config.js`, the STAGE runtime tools under `dev/skill/tools/`, reference docs under `dev/skill/references/`, the top-level `docs/` and `examples/`, and the generated `dev/skill/dist/` artifacts and shipped `pkg/` (the SessionStart hook and `skill-resources.zip`).

Do not commit `node_modules/`, `test-results/`, or `playwright-report/`; a fresh checkout recreates them with `npm ci` and `npx playwright install chromium`. Packaged marketplace installs include only `pkg/`, not this development harness.
