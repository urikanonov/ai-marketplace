# commentable-html E2E tests

Browser regression suite (`@playwright/test`) plus the Python `test_*.py` suites
(standard-library `unittest`, for `tools/build.py` / `validate.py` / `mark_handled.py`)
for the commentable-html layer. See `../docs/DEVELOPMENT.md` for the full
development + testing guide.

## One-time setup

```
npm install                     # or: npm install --registry https://registry.npmjs.org
npx playwright install chromium
```

`npm install` also vendors a local copy of mermaid (`node_modules/mermaid`) used
only by these tests.

## Run

```
npx playwright test             # headless, all specs
npx playwright test --ui        # interactive runner
npx playwright test --headed    # visible browser
npx playwright test -g "banner" # filter by title
npx playwright show-report      # open the last HTML report
```

## Notes

- **No internet needed at run time.** Pages load over `file://`; mermaid (which
  normally imports from a CDN) is served from the vendored local copy via route
  interception in `helpers.js` (`routeMermaidLocal`), so mermaid tests run offline.
- `helpers.js` holds the shared fixtures: opening inline/economy documents, the
  select -> popup -> composer flow (`addTextComment`), clipboard capture, the
  static server, and temp-dir staging for broken-share / version-mismatch cases.
- Specs are numbered by area: inline, toolbar, text comments, code+mermaid,
  copy+handled, save/export, economy, noise/fuzz, interactions, misc, and a
  targeted coverage-gaps spec (`11-coverage.spec.js`).
