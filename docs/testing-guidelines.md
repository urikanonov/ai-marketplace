# Testing guidelines

The conventions every test in this repository follows, and the pitfalls that past refactors paid for
so they are not repeated. Read this before you write or change any test. It complements the
spec-and-test rules in [../AGENTS.md](../AGENTS.md); where they overlap, AGENTS.md is authoritative.

## Where the tests live

- Site behavior (the GitHub Pages hub, plugin pages, tutorial): Playwright specs under
  `site/tests/tests/`, served by `site/tests/serve.js` from the built `site/` folder. Spec of record:
  `site/tests/SPEC.md`.
- Site generator (`scripts/build_site_data.py`): Python `unittest` cases in
  `scripts/test_build_site_data.py`.
- A plugin's runtime and tooling: Playwright specs under `plugins/<plugin>/dev/tests/` (for example
  `plugins/commentable-html/dev/tests/`), plus any Python tool tests beside them. Spec of record:
  `plugins/<plugin>/dev/SPEC.md`.
- Nothing under `dev/` is distributed, so plugin test tooling never ships.

## Core principles

- **Test-driven, always.** Write the test before the code. For a bug fix the test is written first,
  run, and confirmed RED against the current code, then the fix turns it green - both in the same pull
  request. A change whose test never failed on the old code is not test-driven.
- **Make the test genuinely red first.** Assert the NEW behavior, not something the old output already
  satisfies. A frequent trap: a new assertion passes against the current page because the words it looks
  for happen to appear elsewhere already. Pin the change to a marker only the change introduces (a new
  element, class, or exact phrase) and re-run to confirm it is red before implementing.
- **One behavior, one stable feature id.** Every behavior gets an `AREA-NN` id (for example
  `SITE-DEMO-08`, `CMH-DIFF-11`). Reuse an id when you refine its behavior; never renumber or delete a
  shipped id. The spec row must name the covering test by its exact title, and the test title must keep
  the id in parentheses so the two stay searchable together.
- **Assert observable behavior, not tautologies.** Prove the real outcome (an element is visible, a
  block scrolls, a value navigates), not a metric that is true by construction. A prior mobile
  scroll test was rewritten because it asserted scroll numbers that could not fail; test what a user
  would see instead.
- **Keep tests deterministic and hermetic.** No dependence on wall-clock, network, or ordering. Sort
  any collected output before asserting on it.

## Playwright specifics

- **Block every non-local host.** The site suite aborts all requests except `127.0.0.1`/`localhost`
  and `data:` in a `beforeEach`, so a flaky GitHub API, the star-widget CDN, or the mermaid CDN can
  never fail the deploy gate. Validate the built static output only; do not reach the network.
- **Test the built output, then rebuild before asserting.** The suite serves `site/`, which is
  generated. After editing a CSS source partial under `site/css/`, a page source under
  `site/pages/`, the plugin content, or the generator, run `python scripts/build_site_data.py` so
  `site/` reflects the change before the browser sees it. Asserting against a stale `site/` gives a
  false red or false green.
- **Set an explicit viewport for layout assertions, and pick one where the premise holds.** A layout
  test can be invalidated by a spacing change at a specific width. Example: a "breaks out of the content
  column" test only means something at a viewport wider than the content column; after side margins grew,
  the assertion had to move to a wider viewport so the breakout was still real. Choose the viewport that
  makes the behavior observable.
- **Use visibility, not computed style, for show/hide behavior.** `getComputedStyle` still returns
  values for a `display:none` element, so a font-size or color read can silently measure the hidden twin.
  When a change swaps one element for another across a breakpoint, assert `toBeVisible()` /
  `toBeHidden()` on each, not a style read on `.first()`.
- **Prefer role and text locators over brittle DOM paths.** Match ARIA roles, accessible names, and
  visible text. When a widget implements an ARIA contract (tabs, dialog), test the contract
  (`aria-selected`, `aria-controls`, roving `tabindex`, keyboard keys), not just the happy-path click.
- **Guard the security invariants.** Keep the tests that assert the content-security-policy stays as
  tight as each page needs. The tutorial page stays fully tight (`script-src 'self'`, no widget host or
  `'unsafe-inline'`); the hub and the three plugin pages embed the GitHub star widget, so they carry the
  widget-scoped relaxation instead (the `buttons.github.io` script/frame host, the `api.github.com`
  connect host, and `'unsafe-inline'` in `style-src`) - assert that policy EXACTLY so a future broadening
  of a directive still fails. Also keep the tests that assert no internal link or asset uses a
  root-relative path (it would break the project sub-path), and that no link or asset 404s. These catch
  real breakage, not style.

## Generator and Python tests

- **Assert the escape-first, allowlist invariants.** The generator HTML-escapes all text and passes
  every URL through the `safe_url` allowlist before writing. Cover both the rendered-content path and the
  rejection path (a `javascript:`/`data:`/protocol-relative URL neutralizes to `#`) so manifest or
  changelog content can never inject markup.
- **Gate generated output with `--check`.** After any source change that feeds the site, confirm
  `python scripts/build_site_data.py --check` is clean; it fails when `site/` (or the assembled
  `site/assets/styles.css`) is stale versus its sources. The required `site` CI check runs the same
  guard.

## Regenerating derived test artifacts

Some tests read generated fixtures. A source change that does not touch the fixture will pass locally and
fail in CI unless the fixture is regenerated in the same change:

- **commentable-html Playwright fixtures embed the runtime version.** After any version bump, from
  `plugins/commentable-html/dev` run `node tests/fixtures/generate.mjs`. The fixtures are gated by the
  required `plugin-tests` job (`fixtures --check`) but are NOT covered by `build.py --check` or the
  pre-push hook, so a bump that regenerates `dist/` and `site/` can still fail CI on stale fixtures.
- **Highlighter golden tests.** After changing the highlighter, regenerate the goldens with
  `python build_highlight_fixtures.py` (from the commentable-html dev tests) so the `.sample`/`.html`
  goldens match the new output.
- **Committed build outputs.** The commentable-html shipped `dist/` and the site are generated. Rebuild
  them (`python plugins/commentable-html/dev/tools/build.py ...` then
  `python scripts/build_site_data.py`) rather than hand-editing; the `dist-in-sync` and `site` checks
  enforce it.

## Running tests locally

- Site suite: from `site/tests`, `npm ci --ignore-scripts`, `npx playwright install chromium`, then
  `npx playwright test`. Filter with `-g "SITE-DEMO-08"` while iterating.
- A plugin suite: from `plugins/<plugin>/dev`, the same `npm ci` / install / `npm test` flow.
- Generator tests: `python scripts/test_build_site_data.py`.
- The `pre-push` hook and CI run the validators, the Python script unit tests, the changelog/version
  gates, and the `--check` drift guards on every push. The browser (Playwright) suites are the slower,
  occasionally flaky gates: they do NOT run in the pre-push hook by default (set `RUN_E2E=1` to include
  them), and CI is their authoritative gate. Run the relevant browser suite yourself before you push a
  change that touches it.

## Pitfall checklist

- Did the new test fail on the OLD code? If it passed before your change, it is not pinning the change.
- For a CSS or content change, did you run `build_site_data.py` before running the browser suite?
- For a layout assertion, is the viewport one where the behavior is actually observable?
- For a show/hide change, are you asserting visibility rather than a computed style on a hidden element?
- After a version bump, did you regenerate the fixtures (`node tests/fixtures/generate.mjs`)?
- Did you add or refine the spec row (`AREA-NN`) and keep the test title in sync with it?
- Is a workflow's `on:` trigger list valid? One invalid event makes the whole workflow startup-fail and
  silently skip a required check; `actionlint` does not catch every such case.
