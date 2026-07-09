# Development notes (not distributed)

This `dev/` folder is NOT shipped when someone installs `commentable-html` from the marketplace.
Only the plugin's registered `source` (`../pkg`, which holds `plugin.json` and
`skills/commentable-html/`) is copied to the user's machine. Everything here - the canonical
sources, the build tooling, the Python and Playwright test suites, and the spec - stays in the
repo, versioned and testable, but never reaches end users.

## Layout

```
dev/
  assets/                 canonical sources the build compiles (CSS, JS, template shell)
  tools/                  maintainer-only tools: build.py, capture_tutorial.mjs
  tests/                  Python (test_*.py) + Playwright (*.spec.js) suites and fixtures
  docs/DEVELOPMENT.md     the shipped skill's own contributor doc (referenced from the skill)
  SPEC.md                 the behavioral spec
  package.json, package-lock.json, playwright.config.js
../pkg/skills/commentable-html/
  TEMPLATE.html, dist/    GENERATED outputs (committed, shipped) - do not hand-edit
  tools/                  the 13 RUNTIME tools that ship and that the tests import
  SKILL.md, references/, examples/, docs/, ...
```

## The generated artifacts

`pkg`'s `TEMPLATE.html` and `dist/` (the economy build plus its versioned companions and
`manifest.json`) are BUILT from `dev/assets/` by `tools/build.py`. They are committed into `pkg`
so install ships them directly (install runs no build step). Never hand-edit them - change the
sources in `dev/assets/` and rebuild.

`CMH_VERSION` in `dev/assets/commentable-html.js` is the single source of truth for the version.

## Build (regenerate the shipped artifacts)

Run from `dev/`:

```bash
python tools/build.py --assets-dir assets --out-dir ../pkg/skills/commentable-html
# or: npm run build
```

Verify the committed artifacts are in sync with a fresh build (this is what CI checks):

```bash
python tools/build.py --assets-dir assets --out-dir ../pkg/skills/commentable-html --check
# or: npm run build:check
```

`build.py` defaults to the flat layout (assets and outputs under one skill root); the
`--assets-dir` / `--out-dir` flags point it at the split layout used here.

## Tests

The tests exercise the REAL shipped tools and artifacts under `../pkg` - the Python suite adds
`../pkg/skills/commentable-html/tools` to `sys.path` and reads `TEMPLATE.html`, `dist/`, and
`examples/` from `pkg`, so a green suite proves what actually ships. Run from `dev/`:

```bash
# Python (standard library only)
python -m unittest discover -s tests -p "test_*.py"
# or: npm run test:py

# Playwright (browser E2E)
npm ci
npx playwright install chromium
npx playwright test --reporter=line
# or: npm test
```

Test fixtures live under `tests/fixtures/` and are DERIVED from the shipped `TEMPLATE.html` +
`dist/` by `tests/fixtures/generate.mjs`. After changing the layer, rebuild then regenerate:

```bash
npm run build
npm run fixtures        # or: node tests/fixtures/generate.mjs
npm run fixtures:check  # fails if committed fixtures are stale (wired into the suite)
```

## Validate the shipped skill

```bash
python tools/validate.py --strict \
  ../pkg/skills/commentable-html/TEMPLATE.html \
  ../pkg/skills/commentable-html/examples/community-garden.html \
  ../pkg/skills/commentable-html/examples/nyc-taxi-2014.html
```

`validate.py` is a runtime tool, so it ships in `pkg`; it is invoked here from `pkg/tools` the
same way the tests invoke it.
