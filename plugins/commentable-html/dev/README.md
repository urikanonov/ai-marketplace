# commentable-html development

This `dev/` folder is the development home for `commentable-html`. It is not copied when users install the marketplace plugin. The shipped plugin is `../pkg`, which contains `plugin.json` and `skills/commentable-html/`; this folder keeps the canonical assets, build tooling, tests, fixtures, and spec in the source repository.

## Two-directory layout

```text
dev/
  assets/                 canonical CSS, JS, and template shell sources
  tools/                  maintainer-only build and screenshot tools
  tests/                  Python test_*.py suites, Playwright *.spec.js suites, helpers, and fixtures
  SPEC.md                 behavioral spec
  package.json, package-lock.json, playwright.config.js
../pkg/
  plugin.json             marketplace plugin manifest
  skills/commentable-html/
    SKILL.md              shipped skill instructions
    dist/                 generated PORTABLE.html, NONPORTABLE.html, companions, manifest.json
    tools/                runtime Python tools that ship
    references/           shipped reference docs
    docs/                 shipped tutorial and tutorial images
    examples/             shipped worked prompts and example reports
```

## Single source of truth

Edit `dev/assets/` only when changing the review layer:

- `assets/css/NN-topic.css` - layer stylesheet partials (directory-sorted into one bundle by the build).
- `assets/js/NN-topic.js` - runtime partials (directory-sorted into one bundle by the build). One partial declares the `CMH_VERSION` const, stamped from `VERSION` by the build; do not hand-edit the const.
- `assets/template.shell.html` - shell with the five commentable regions, toolbar, sidebar, and demo content.

The version lives in `dev/VERSION` (plain-text semver) and is the only hand-edited version. `build.py` reads it and stamps the runtime `CMH_VERSION` const, `../pkg/plugin.json`, the marketplace entry, and each generated document's `<meta name="commentable-html-version">`. Companion filenames are version-agnostic, so a version bump never renames dist files.

Everything under `../pkg/skills/commentable-html/dist/` is generated and committed so installs do not run a build step. Do not hand-edit `dist/PORTABLE.html`, `dist/NONPORTABLE.html`, the companions, or `manifest.json`.

## Build pipeline

Run from `dev/`:

```powershell
python tools\build.py --assets-dir assets --out-dir ..\pkg\skills\commentable-html
```

Check for drift without writing:

```powershell
python tools\build.py --assets-dir assets --out-dir ..\pkg\skills\commentable-html --check
```

`--assets-dir` and `--out-dir` point the builder at this split source/shipped layout. The check mode is the CI guard for generated output drift.

To bump the version, edit `VERSION` then run `build.py`; it restamps every version spot (the layer `CMH_VERSION` const, `../pkg/plugin.json`, the marketplace entry, and each document's `<meta name="commentable-html-version">`). Companion filenames are version-agnostic, so the bump does not rename any dist files. `build.py --check` fails if any stamped spot drifts from `VERSION`.

To bump mermaid (usually a Dependabot PR against `package.json`): the mermaid CDN version is single-sourced from the `mermaid` dependency in `package.json`, so after the version changes just run `npm install` (updates `node_modules` + `package-lock.json`) then `python tools/build.py` and `node tests/fixtures/generate.mjs`. The build stamps the new `mermaid@<version>` into `template.shell.html` -> `dist/PORTABLE.html`/`NONPORTABLE.html` and into the `examples/*.html` reports; the fixtures derive from `dist/`, so they follow automatically. `build.py --check` (the `dist-in-sync` gate) fails clearly if any shipped mermaid pin drifts from `package.json`, and `tests/helpers.js` `routeMermaidLocal` only needs the served template's major to match the vendored `node_modules/mermaid` major. Do not hand-edit the `mermaid@<version>` string in any generated file.

## Python suite

The Python tests use standard-library `unittest`. They import the runtime tools from `../pkg/skills/commentable-html/tools` and validate the generated artifacts in `../pkg`, so a pass covers what ships.

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
python ..\pkg\skills\commentable-html\tools\validate.py --strict `
  ..\pkg\skills\commentable-html\dist\PORTABLE.html `
  ..\pkg\skills\commentable-html\examples\report-community-garden.html `
  ..\pkg\skills\commentable-html\examples\report-taxi.html
```

From `pkg\skills\commentable-html`, the same check is:

```powershell
python tools\validate.py --strict dist\PORTABLE.html examples\report-community-garden.html examples\report-taxi.html
```

## Rebuilding the example images

The shipped example reports are single self-contained files with their images inlined as data URIs, so `pkg/skills/commentable-html/examples/` has no `images/` folder. The source images for the community garden example live here in `dev/examples/images/` (kept for reproducibility, not shipped). To re-inline them into a freshly authored example and validate it, run from `dev/`:

```powershell
python ..\pkg\skills\commentable-html\tools\inline_images.py <report>.html --base ..\dev\examples\images --strict
python ..\pkg\skills\commentable-html\tools\validate.py <report>.html
```

The taxi example has no images, so it needs no inlining - just validate it.

## Regenerating tutorial screenshots

The tutorial (`../pkg/skills/commentable-html/docs/TUTORIAL.md`) embeds nine `garden-*.png`
screenshots captured from the community-garden example. Regenerate all of them with one command from
`dev/`:

```powershell
npm run shots
```

`npm run shots` runs `tools/capture_tutorial.mjs` with no arguments: it drives
`../pkg/skills/commentable-html/examples/report-community-garden.html` and writes
`garden-01-top-light.png` through `garden-09-copyall.png` into
`../pkg/skills/commentable-html/docs/assets/` at a fixed 1320x900 viewport (2x scale). It pins the
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
python tools\build.py --assets-dir assets --out-dir ..\pkg\skills\commentable-html
node tests\fixtures\generate.mjs
```

Check fixture freshness:

```powershell
node tests\fixtures\generate.mjs --check
```

## What is committed

Committed source-repo files include `dev/assets/`, `dev/tools/`, `dev/tests/`, `dev/SPEC.md`, `dev/package.json`, `dev/package-lock.json`, `dev/playwright.config.js`, shipped runtime tools under `pkg/skills/commentable-html/tools/`, shipped docs under `pkg/skills/commentable-html/references/` and `docs/`, examples, and generated dist artifacts.

Do not commit `node_modules/`, `test-results/`, or `playwright-report/`; a fresh checkout recreates them with `npm ci` and `npx playwright install chromium`. Packaged marketplace installs include only `pkg/`, not this development harness.
