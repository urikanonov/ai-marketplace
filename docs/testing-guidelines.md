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
  the id in parentheses so the two stay searchable together. One id also owns exactly ONE spec row:
  `check_spec_test_refs.py` fails when an id is the id cell of two rows in the same target, because the
  other directions all merge same-id rows, so a test cited by either row would satisfy the other (issue
  #904 found seven such ids). If a behavior needs a row of its own, give it a free id; a renamed row
  records its old id in the row text AND in the spec's "Renamed feature ids" ledger, so an older
  reference to the old id (a released `CHANGELOG.md` entry, say) still leads somewhere.
- **Do not borrow another file's feature id.** `scripts/check_spec_test_refs.py` fails when one id is
  carried by test titles in MORE THAN ONE file and a spec row that owns the id does not cite every
  one of them. Two tests in the SAME spec file may share an id (a single behavior asserted from
  several angles is the existing convention here), but the owning row must still list EVERY title:
  the reverse direction below demands a citation for each carrier, same-file ones included. The
  duplicate direction only escalates when the id also appears in another file. A test in a
  different file that reuses an id is therefore either a new behavior that needs its own id, or
  genuine extra coverage the row must name. That is the gate the `DEMO-TRIM-06`/`DEMO-TRIM-07` reuse
  slipped past (#800). Hiding the reuse in a `describe(...)` wrapper does not help: a suite title
  still counts toward "how many files carry this id", and its id must have a row of its own.
  The same checker also verifies the reverse
  direction - every JS `test`/`it` title that carries an id is owned by that id's row, across the
  WHOLE `*.spec.*` / `*.test.*` corpus of every shipped target (an ordinary `tests/45-foo.spec.js`
  is checked exactly like a `*regressions*.spec.*` one), and that row must CITE the title. A
  `describe(...)` suite title is checked for ownership only, since a row cannot cite one. Any
  `AREA-NN`-shaped token in a title is read as a feature id, so do not put one in a title
  incidentally (`decodes UTF-8 input` would be read as the id `UTF-8`). Write a
  covering-tests cell file-first - `` `tests/x.spec.js` - `a title`,
  `another title` `` - because a title only counts as cited when it appears AFTER its file
  reference and before the next one (or the next `;`). Keep prose semicolons OUT of a coverage
  cell for that reason: a `;` outside a code span ENDS the clause, so every citation after it is
  unreachable (that is how the `CMH-OFFLINE-04` row lost its newest citation to both directions).
- **Assert observable behavior, not tautologies.** Prove the real outcome (an element is visible, a
  block scrolls, a value navigates), not a metric that is true by construction. A prior mobile
  scroll test was rewritten because it asserted scroll numbers that could not fail; test what a user
  would see instead.
- **Keep tests deterministic and hermetic.** No dependence on wall-clock, network, or ordering. Sort
  any collected output before asserting on it.
- **Never write a scratch file with a bare relative name.** A test that opens `"a.md"` puts it in the
  caller's working directory, which for the `pre-push` hook and CI is the repository root - so the tree
  is dirty after every push (a following `git rebase` then refuses to run), and an unrelated PR's
  `git add -A` can commit the residue. That is exactly how `a.md` and `old.md` reached `main` (#791).
  Build every fixture under a `tempfile.TemporaryDirectory()` (or another ABSOLUTE temp path) and pass
  absolute paths. Likewise, spawn `git` with an explicit `-C <tempdir>` or `cwd=`, and route its
  environment through `scripts/_git_test_env.clean_git_env()` so an inherited `GIT_DIR` cannot redirect
  it at the real repository (#778). `scripts/run_script_tests.py` runs the whole suite from a throwaway
  cwd and fails if anything is left in it or if the repository tree changed, so a regression here is
  caught on the very first push - but write the test hermetically in the first place.

## Playwright specifics

- **Do not trust the `[N/M]` progress line when reading a failure (`--reporter=line` only).** The
  suite's configured reporter is `list`, which attributes correctly: every row and every failure
  header carries the index and title of the test it belongs to. The `[N/M] <file:line> <title>`
  form comes only from an ad-hoc `--reporter=line` run, and there it names the test that started
  LAST, not the one that failed: it is written from `onTestBegin` and redrawn in place with cursor
  escapes (`ESC[1A ESC[2K`). Under `fullyParallel`, one worker's failure block is emitted next to
  another worker's progress line, and in a captured (non-TTY) log - where nothing replays the
  cursor moves - the two end up adjacent, so the failure reads as if it belonged to the named test.
  That is how #814 came to be filed against SITE-VIDEO-15 for a `toHaveCount` assertion that test
  does not contain; the real failure was a demo-iframe assertion in another spec. Take the failing
  test's name from the `N) file:line > title` failure header or the final `N failed` summary list,
  and prefer the configured `list` reporter when running the suite by hand. If the named test's
  source does not contain the failing matcher, the attribution is the artifact, not a mystery in
  that test.
- **Open a shipped commentable-html example with `routeExampleLibsLocal`, nothing else.** The
  examples load mermaid and Chart.js from a pinned CDN by design (`CMH-SIZE-08`/`CMH-SIZE-09`), and
  the two halves come from different places: mermaid's ESM entry point plus its ~20 chunks from
  `node_modules/mermaid`, and the pinned Chart.js from `assets/vendor/`. The export-scoped
  `routeOfflineExportLibs` covers only what the Offline EXPORT downloads (the UMD `mermaid.min.js`,
  a URL the viewer never asks for), so a spec that installed it alone looked hermetic and fetched
  mermaid from jsDelivr on every run, leaving an unbounded round trip that could render a diagram
  after the measurement it was about to take (#1305). `routeExampleLibsLocal` installs both local
  routes over a recording deny-all, so anything unrouted is aborted and shows up in
  `page.__external` instead of going out. Serving them locally makes a diagram render FAST rather
  than never, so a spec that MEASURES layout must also `await awaitMermaidRendered(page)` after
  `ready()` - otherwise a render lands mid-measurement and you have traded a slow race for a fast
  one. `CMH-BUILD-30` is the guard, and it checks BOTH halves: it sweeps every `examples/*.html`
  through the helper, and it fails any other spec that navigates to a shipped example without
  installing a hermetic deny-all.
- **Never let an assertion absorb a heavy load.** A locator assertion with a fixed timeout in front
  of a multi-megabyte (or lazily loaded) document makes ONE budget cover the download AND the
  behavior, so a cold runner fails in the content assertion and blames the content. Wait for the
  load explicitly first - the site suite's `demoFrameReady` helper scrolls the lazy demo iframe in
  and waits for that document to reach `readyState === "complete"` - and give the test a real budget
  with `test.slow()`. `SITE-DEMO-14` is the guard that keeps both in place.
- **Never assert live on state that reverts on a timer.** The site's copy buttons set their label,
  their state class, and their live-region text only when the clipboard call RESOLVES, then revert
  all three 1500ms (success) or 2000ms (failure) later. A live locator assertion therefore races
  that revert three ways: a poll can miss the window when a cold clipboard round trip pushes the
  state past the 5s expect default, consecutive assertions spend the window one after another so
  the later ones read an already-reverted button, and a fixed budget shorter than the default is
  shorter still than a loaded runner delays the timer by (#859). Install the site suite's
  `recordCopyFeedback` helper BEFORE the click - it records every state the button passes through -
  assert on the recorded snapshot, and give the test a real budget with `test.slow()`. Where the
  FINAL state matters, wait for the recorded log to go quiet (`waitForSettled`) rather than sampling
  a state that a second, slower round trip is about to change. `SITE-COPY-04` is the guard.
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

### Regenerating the tutorial screenshots (container-rendered - CMH-BUILD-16)

The committed tutorial PNGs under `plugins/commentable-html/docs/assets/` are produced by a real
browser, and font rasterization is decided by the OS image that browser runs on - not by the browser
version. So there is exactly ONE renderer, on both sides: the digest-pinned
`mcr.microsoft.com/playwright` container renders and verifies them on every developer machine AND in
the required `playwright-heavy` CI job. Nothing renders them with a host browser.

Use the npm scripts, from `plugins/commentable-html/dev`:

```bash
npm run shots                # regenerate in the pinned container
npm run shots:check          # verify; skips with a note when Docker is unavailable
npm run shots:digest         # re-pin the container by digest (after a @playwright/test bump)
```

All of them route through `tools/shots_linux.py`, so the short, habitual command is the safe one,
and extra `capture_tutorial.mjs` arguments (`[example] [outDir] [prefix]`, `--print-paths`) pass
straight through - a single-scene recapture never has to leave the guarded path.

- **The image is pinned on both axes that decide the pixels**: the `@playwright/test` version
  resolved in `package-lock.json` (the chromium binary) and the Ubuntu release in the image variant
  (the FONTS). Neither is hardcoded at a call site - CI resolves the reference with
  `python tools/shots_linux.py --print-image`.
- **It is pinned by DIGEST, not merely by tag.** `tools/shots-image.lock` records the sha256 the tag
  resolved to, so a registry rebuild of `v<version>-noble` on a newer base OS (different font
  packages) cannot silently change the renderer. After bumping `@playwright/test`, run
  `npm run shots:digest` and commit the lock; until you do, a developer run falls back to the tag
  with a loud note (a bump degrades the pin, it never blocks a local regeneration) while **CI
  refuses to render at all** rather than validate against whatever the registry serves that day, and
  `test_the_committed_lock_pins_the_version_the_package_lock_resolves` reds until it is re-recorded.
  The lock is only as honest as the command that wrote it: nothing re-verifies a hand-edited digest
  against the registry, so always re-record it with `npm run shots:digest` rather than editing it.
- The run also pins `--platform linux/amd64`, so an Apple Silicon host does not render with the
  arm64 stack, and `--user` on a Linux host (including the CI runner) so the container leaves no
  root-owned files in the worktree. In CI it also forwards `CI=true`, which is what makes the
  capture double its settle deadlines - docker inherits no host environment, so without it the
  required gate would silently get the tighter, flakier timings.
- **The container brings the browser and the fonts; the JS comes from the mounted `node_modules`.**
  That half is pinned by `package-lock.json`, not by digest, so install it with `npm ci` (or
  `python scripts/setup_dev.py`) - a hand-drifted `node_modules` is the one input the image does not
  fix for you. The run also pins a writable `HOME` and `--ipc=host` (the image's documented
  invocation - the default 64 MB `/dev/shm` can crash chromium mid-capture).
- **Docker is required only by the shots commands** - never for normal development or for the test
  suites. `npm run shots:check` (which `npm test` runs) SKIPS with a note when Docker is missing or
  its daemon is down, so a developer without Docker is never blocked. It NEVER skips in CI, where it
  is the required drift gate, and the write direction never skips anywhere. Each precondition
  failure names what is missing and what to do (Docker absent, daemon down, `node_modules` missing).
- `--native` renders with the host browser. It is an explicit, non-authoritative escape hatch that
  warns on every run; no npm script uses it and CI must never use it.

#### Fixing a stale screenshot without Docker: adopt the drift artifact (CMH-BUILD-28)

A shot that goes stale on `main` reddens the required `playwright-heavy` gate for EVERY open pull
request, not just the one that caused it - so it has to be fixable by whoever notices, not only by
whoever has a renderer. It is: the failing gate already uploads the PNGs the pinned container just
rendered as the `tutorial-shots-drift` artifact (CMH-BUILD-18), and those bytes ARE the
authoritative render for that commit. Adopt them, from `plugins/commentable-html/dev`:

```bash
python tools/shots_linux.py --adopt-run <run-id>   # fetch this repo's artifact with gh, then adopt
python tools/shots_linux.py --adopt <dir>          # adopt an artifact you already unzipped
```

`<run-id>` is the number in the failing run's URL (`.../actions/runs/<run-id>`). Commit what it
rewrites; the pinned container's `shots:check` - the required gate - is what confirms it.

- **Prefer `npm run shots` when you have Docker.** Adopting installs a render made for the commit
  that ran, so it is the recovery path, not the routine one. `--adopt-run` prints what produced the
  bytes - the commit, the branch, the run URL and the triggering EVENT - and warns both when the run
  rendered a different commit and when its event is not `push`. Heed the second one: the drift
  artifact is uploaded by `pull_request` runs too, and those pixels were rendered from that pull
  request's own source, so adopt a `push` run of the branch you are fixing.
- **It relaxes nothing.** Adopting is a re-baseline from the same renderer the gate uses, never a
  verdict that the screenshots are right; only `shots:check` in the container says that.
- **It refuses as a whole rather than partly applying**, and decides (and reads every byte on both
  sides) before writing anything. A PNG whose name is not a committed shot, a file that is not a
  usable PNG (the chunk stream is walked with CRCs, requiring a 13-byte `IHDR` with non-zero
  dimensions, at least one `IDAT` that inflates to a non-empty result and reaches its zlib
  end-of-stream, bounded by what the declared dimensions could hold so a decompression bomb is
  refused rather than inflated, and an empty terminal `IEND` with nothing trailing - a signature
  test would not catch a truncated download, and the gate DECODES these files), a symlink or a
  linked directory (an NTFS junction is walked into by `os.walk`, so every
  candidate must resolve inside the artifact), a file far larger than any screenshot, one name
  appearing twice under the root, a path that is not a directory, or an empty directory each refuse
  the whole adoption and write nothing. The `*.diff.png` files the check writes beside a failing
  render are skipped - they are magenta-marked reports of the failure, not renders.
- **The writes are all-or-nothing too**: each baseline is replaced through a sibling temp file and
  `os.replace` (carrying the baseline's own file mode across), so a failure cannot truncate one in
  place, and if any exception interrupts the loop - including a Ctrl-C - every file already written
  is restored from the bytes the plan read.
- It does NOT require the artifact to cover every committed shot, because a mid-capture crash
  legitimately uploads only the scenes rendered before the throw. The no-drift report therefore
  states the artifact's own coverage rather than implying the whole set is fresh.
- On a refused ADOPTION the downloaded artifact is kept and its path named, so you can inspect it
  and re-run `--adopt <dir>` without downloading again. A failed DOWNLOAD removes it instead, since
  there is nothing to inspect.
- It cannot be combined with `--check`, `--native`, `--print-image`, `--record-digest` or
  `--skip-without-renderer`: it installs pixels another run rendered, so rendering here at the same
  time would leave it ambiguous which pixels won. A green run uploads no artifact (it is produced
  only on failure), and artifacts expire.

**Scope of the guarantee.** This is equivalence by CONSTRUCTION, not by agreement: both sides
execute the same image content-addressed by digest, so a GitHub runner-image update (which used to
be able to move the CI renderer under a `runs-on: ubuntu-24.04` label without any change in this
repo) can no longer affect a single pixel. That is why `playwright-heavy` tracks `ubuntu-latest`
again and the old runner/variant coupling test is gone (an amd64 runner is still a precondition -
the container is pinned to `linux/amd64`). CI remains the authoritative GATE - it is the run that
must be green - but it is no longer a second RENDERER that has to agree with yours. The honest
caveat left is cost: running the container is not free - `npm test` and `rebuild_all.py` now render
on any Docker-capable machine where they used to skip, and the first run pulls ~900 MB.

#### What the drift comparison actually allows (CMH-BUILD-19)

The comparison is EXACT: no differing pixels are allowed. It used to downsample 2x, quantize colors
onto a 64-step ladder and tolerate a channel delta of 96 across up to 20% of the pixels - a budget
sized back when two different renderers had to agree - which meant a real visual regression could
pass unseen. With one pinned renderer that slack buys nothing, and issue #710 measured what the
renderer actually gives: two independent renders of all 19 committed shots are **byte-identical**,
in the container and on a host browser alike, including under four concurrent captures and a
6-worker stress run. So `tools/shot_compare.mjs` applies no normalization at all and allows zero
differing pixels (`MAX_DIFF_PIXELS = 0`).

Two things make that practical rather than brittle:

- **The volatile build stamps are frozen at capture time, not bought off with an allowance.** The
  runtime paints its version badge (`v1.255.0`) and the document's "Generated on" date into its own
  UI; both change on a release with no behavior change (and the date falls back to
  `document.lastModified`, which is volatile per checkout). `tools/shot_stamps.mjs` rewrites them to
  fixed placeholders (`v1.x`, `Jan 1, 2026`) just before each shot is measured and taken, so a
  version bump never repaints a screenshot. Doing it this way rather than allowing a few thousand
  differing pixels matters: an allowance applies to the WHOLE image (it would hide a small real
  regression anywhere, which is the exact class of miss this change removes), and the same comparison
  drives the WRITE path, so `npm run shots` would refuse to update a shot whose intended change fell
  inside it. The freeze is deliberately NARROW - only the elements the runtime stamps those values
  into, and only the value inside them - so rendered comment text that merely looks like a stamp is
  never rewritten, the authored document (`#commentRoot`) is untouched, each label is kept, and a
  value that is not a real date (`unknown`, a malformed stamp) is left alone so it still fails the
  gate. The date VALUE itself is therefore deliberately un-gated by the screenshots; its formatting
  is covered by the sidebar's own tests.
- **A channel tolerance of 2 is kept as insurance, and only that.** A pixel counts as different when
  any channel differs by more than 2. Nothing measured needs it (within a machine the difference is
  zero); it covers the one input the container digest does not pin, the host CPU, since Chromium
  rasterizes in software and Skia dispatches on CPU features, so another runner could round a blended
  edge pixel by a least significant bit or two. Two steps out of 255 are invisible, and the smallest
  regression still caught is a delta-3 wash - where the retired budget waved through delta 96.

If a comparison ever fails for a reason that turns out to be renderer jitter rather than a real
change, re-size the tolerance from THAT measurement rather than widening it pre-emptively:
`compareImages` reports what differed - a dimension mismatch, or the differing-pixel count and ratio
against the budget - so a red `--check` run or determinism assertion names the magnitude instead of
only saying "differs". `--print-paths` reports the budget and the placeholders, and
`tests/80-shot-clip.spec.js` asserts the tool and the suite agree, so the gate and the specs that
mirror it cannot drift apart.

One boundary worth stating plainly: byte-identical renders are measured EVIDENCE for one machine and
one image, not a guarantee the container extends to every host. What the digest pin does guarantee is
that the browser, the OS image and the fonts are the same everywhere. Note also that the heavy
`54-tutorial-shots.spec.js` determinism tests run the capture with the RUNNER's own browser rather
than in the container: they share the comparator with the `--check` gate, not the renderer, and they
compare two runs in the same environment.



`capture_tutorial.mjs` refuses to render or verify the COMMITTED screenshots unless the wrapper
invoked it (it sets a renderer marker in the environment), so a raw
`node tools/capture_tutorial.mjs` cannot rewrite them with the host's fonts. Capturing into any
other directory - what the test suite does - is unaffected.

`rebuild_all.py` drives the same wrapper, so it now regenerates the screenshots correctly on any
host with Docker; without Docker it skips that one step with a note pointing here rather than
producing a CI-failing artifact. If your change does not affect the shots, restore them with
`git checkout origin/main -- plugins/commentable-html/docs/assets` and confirm with
`npm run shots:check`.

**When the CI drift gate fails, download the pixels it saw (CMH-BUILD-19).** Because the container
is the only renderer, a contributor without Docker cannot reproduce a drift failure locally, so the
failed run carries the evidence: the `playwright-heavy` job uploads the freshly rendered PNGs as the
`tutorial-shots-drift` artifact (found under "Artifacts" on the failed run's summary page). Unzip it
and you get the `<pid>/<scene>/` tree the check rendered into `tmp/tutorial-shots-check/` on the
runner, so compare each PNG in it against the committed
`plugins/commentable-html/docs/assets/` file of the SAME NAME to see what actually moved. Start with
the `<scene>-<name>.diff.png` beside each fresh PNG: the check paints every pixel that differs by
more than the gate's own channel tolerance in magenta over a faded copy of the committed shot, so the
change is visible at a glance instead of by eyeballing two near-identical screenshots. A diff is
written only for a FAILING shot, and only when it can be rendered - it is evidence, never a verdict,
so it cannot change the pass/fail outcome. The upload is tied to that gate step's own outcome, so a
green run never pays for it. What it can upload is what the check kept, and the check now keeps its
renders on ANY unsuccessful run - a stale or missing shot, and equally a crash mid-capture, which
used to delete the shots it had already rendered. The artifact is kept for 14 days, so grab it while
the run is fresh; re-running the failed job replaces it rather than erroring on the existing one.

#### Why a shot can drift by a few pixels with no content change (CMH-BUILD-17)

The drift is FONT METRICS, not the browser. Issue #698 probed `.cmh-checklist` under the exact capture
context on a Windows host and in the pinned container, with an identical lockfile-pinned chromium and
identical CSS (`font-size: 15px`, `line-height: 23.25px`):

| measurement | Windows | pinned container |
| --- | --- | --- |
| element `offsetHeight` | 228 CSS px | 230 CSS px |
| per-row rendered height | 23.250 | 23.391 |
| element `offsetWidth` | 1222 CSS px | 1222 CSS px |
| resulting PNG | 2444x456 | 2444x460 |

The capture is not using the report's own font stack: `freezeMotion` pins it to
`font-family: Arial, sans-serif !important`, and that pin is only as portable as Arial is. Windows
resolves real Arial; the pinned Linux container ships no Arial at all (`fc-list` finds none) and
fontconfig substitutes **Liberation Sans**. Liberation Sans is metric-compatible with Arial in ADVANCE
WIDTHS - which is exactly why the width is identical to the pixel and no shot has ever drifted
horizontally - but its VERTICAL metrics differ, so each text row grows by 0.141 CSS px.

That only moves ELEMENT-clipped shots, whose clip height comes from the element's content-derived
`offsetHeight`; full-viewport clips are stable by construction. `deviceScaleFactor: 2` then doubles a
2 CSS px rounding difference into the 4 device px PNG delta.

`tools/shot_clip.mjs` closes this: every content-derived clip height is snapped onto `CLIP_QUANTUM`,
so the drift collapses onto one value and both renderers emit the same dimensions (the checklist scene
is 2444x464 on either). A clip bounded by the viewport or a panel is quantized LAST and DOWNWARD
(`clampedClipHeight`), so a clamped clip lands on the grid too - quantizing up and then clamping would
leave an off-grid height, and an element that clamps on one renderer but not the other would then
differ by an arbitrary sub-quantum amount, which is the same bug moved rather than fixed. The
guarantee holds while the per-shot drift stays UNDER one quantum (about 0.6% of a clip height for the
measured font pair, so roughly 5.4 px at the 900 px viewport ceiling); a wider gap moves two quanta and
fails loudly, which is the signal to raise the quantum, not to widen the budget.

Because no pure function of a drifting measurement can be boundary-free - two heights either side of a
grid line land one quantum apart - the `--check` height comparison allows exactly one non-zero value,
one whole quantum (`DIMENSION_DELTA_PX`), and only BETWEEN TWO HEIGHTS THAT ARE BOTH ON THE GRID.
Both halves matter. An exact value rather than a band keeps a sub-quantum delta failing, because that
can only be real content added or removed at the bottom edge and is invisible to the overlap-cropped
pixel diff, whereas quantizing already absorbs sub-quantum content changes into an IDENTICAL height,
where the pixel diff does see them. Requiring both heights on the grid keeps the allowance away from
clips that are not quantized: a fixed-viewport shot is 1800 device px tall (off-grid), so appending or
removing exactly one quantum of visible rows there is real content and still fails. Width is not
quantized (it comes from the fixed viewport) and keeps its own strict budget. The comparison lives
once in `tools/shot_compare.mjs` - its dimension gate in Node, only the pixel diff in the browser -
and is imported by both the capture tool and the heavy freshness spec. Do not re-declare any of these
at a call site; import them (`--print-paths` reports them, and a test asserts the tool agrees).

- **Highlighter golden tests.** After changing the highlighter, regenerate the goldens with
  `python build_highlight_fixtures.py` (from the commentable-html dev tests) so the `.sample`/`.html`
  goldens match the new output.
- **Committed build outputs.** The commentable-html shipped `dist/` and the site are generated. Rebuild
  them (`python plugins/commentable-html/dev/tools/build.py ...` then
  `python scripts/build_site_data.py`) rather than hand-editing; the `dist-in-sync` and `site` checks
  enforce it.

## Keeping the CI Playwright shards balanced

The `plugin-tests` critical path is the SLOWEST shard of the sharded jobs, so a lopsided shard wastes
the whole fan-out. Balance is kept automatically - do not hand-tune shard assignments - but three
conventions keep it that way, and you must follow them when you add or materially change a test:

- **The `fast` Playwright job is sharded by DURATION, not test count.** CI passes
  `PLAYWRIGHT_FAST_SHARD=i/N` and `playwright.config.js` (via `tests/_shard.mjs`) runs only the specs
  that longest-processing-time (LPT) bin-packing assigns to shard i from the committed per-spec
  timings in `tests/spec-timings.json`. This keeps every shard within ~1% on time even though the few
  slow specs would otherwise cluster on one shard. **After adding a new `fast` spec, or materially
  changing an existing one's run time, run `npm run shard:timings`** (from `plugins/commentable-html/dev`)
  to regenerate the timings and commit them; the assignment then rebalances itself. The `CMH-BUILD-13`
  guard (`tests/00-projects.spec.js`) FAILS if a spec has no timing (or a timing is orphaned), so a
  forgotten refresh is caught in CI, not silently unbalanced. (The fast job is currently
  commentable-html-specific: another plugin's `fast` project must honor `PLAYWRIGHT_FAST_SHARD` the
  same way - copy `playwright.config.js` + `tests/_shard.mjs` + a `spec-timings.json` - or its suite
  runs UNSHARDED on every runner. Keep all fast specs directly under `tests/`; a nested spec is keyed
  by basename and the `CMH-BUILD-13` guard fails to force the flat convention.)
- **When one test is itself too slow to balance, SPLIT it - do not try to shard around it.** Sharding
  can only distribute WHOLE tests; a single test that runs far longer than a shard's fair share becomes
  an irreducible floor. The `CMH-BUILD-13` guard's 1.5x-of-even tripwire flags a `fast` spec that grew
  too big. The `heavy` job hit the same thing: one mermaid-heavy tutorial-screenshot scene test ran ~90s
  as a monolith, so it was split into three focused tests (regenerate / determinism / stale) that the
  shards parallelize (issue #543). Prefer splitting a slow monolith into independent focused tests over
  any clever sharding.
- **Write multi-case test generators TYPE-grouped so their cases spread across shards.** The `heavy`
  job still uses Playwright's count-based `--shard`, which chunks tests by declaration order, so a
  `for (const scene of SCENES) { test(a); test(b); test(c); }` loop piles one scene's three tests
  adjacent and onto one shard. Emit them in separate loops (all `a`, then all `b`, then all `c`) so each
  scene's cases land on different shards (issue #543). The same applies to any new parameterized heavy
  suite.
- **Measure CI-representatively.** Windows and an unloaded laptop are not the CI runner. To reason about
  real shard times, run in the pinned Linux container with the CI settle scale, e.g.
  `docker run --rm --cpus=4 -e CI=1 -v <plugin>:/work mcr.microsoft.com/playwright:v<ver>-noble ...`;
  trust RELATIVE per-shard results (a bind-mount inflates absolute times). CI itself is the
  authoritative number.

The `python` plugin suite is already balanced by round-robin file distribution
(`scripts/run_plugin_python_tests.py select_shard`); a `ShardMatrixContiguityTests` guard keeps each
sharded job's matrix a complete `1..N` cover so an entry can never be silently dropped.

## Running tests locally

- Site suite: from `site/tests`, `npm ci --ignore-scripts`, `npx playwright install chromium`, then
  `npx playwright test`. Filter with `-g "SITE-DEMO-08"` while iterating.
- A plugin suite: from `plugins/<plugin>/dev`, the same `npm ci` / install / `npm test` flow.
- Generator tests: `python scripts/run_script_tests.py --pattern test_build_site_data.py`.
- The whole `scripts/` suite: `python scripts/run_script_tests.py --jobs auto` (leave off `--jobs`
  for one serial run). Always use the runner rather than
  `unittest discover` directly - it runs the suite from a throwaway working directory and fails if a
  test left a file behind or changed the repository tree, which is the guard that keeps scratch
  fixtures out of the repo root. `--jobs` keeps that guard: the PARENT creates and inspects each
  worker's sandbox (so a test cannot exit the process to skip the check) and takes the repository
  snapshot once around the whole run, while each worker runs a deterministic stride of the
  discovered tests (987.0s serial -> 74.6s across 16 workers here; the same suite is only ~20s on a
  4-CPU CI runner, so the CI win is much smaller). The workers must all discover the same number of
  tests and, between them, run every one exactly once, or the run reds - a green run in which tests
  silently never executed is the failure mode that check exists for.
  Because a worker runs a
  SLICE of a module rather than the whole file, class and module fixtures are re-paid once per
  worker (the speedup is sublinear), and a test that depends on another test in its class
  having run first will only fail under `--jobs` - fix the dependency, do not go back to serial.
  Build fixtures with `tempfile.mkdtemp()`/`TemporaryDirectory()`, never in the repository's own
  `tmp/` (or `.plans/`, `.worktrees/`, `plugins/tmp/`): those paths are gitignored, so neither leak
  guard can see them, and workers race on them
  (`test_suite_hermeticity.py` now fails the suite for it).
  If you are editing files while the suite runs, the tree diff
  will flag YOUR edits; pass `--no-worktree-check` for that case - the sandbox check still applies.
  A SIBLING worktree is not your problem though: the snapshot compares only the refs this worktree
  owns (the branch HEAD is on, plus the per-worktree `refs/bisect/*`, `refs/rewritten/*` and
  `refs/worktree/*`), so another agent committing in `.worktrees/<other>`, or a concurrent
  `git fetch` writing remote-tracking refs, no longer trips the guard (#830) and there is nothing to
  opt out of (a fetch that fast-forwards THIS branch is still a change, since a leaking suite could
  have moved it). The accepted
  cost is that a stray BRANCH, TAG or STASH a test leaves behind is no longer caught - those live in
  the shared store and cannot be told apart from a sibling's work - while a stray FILE, the leak the
  guard exists for, still is. The two verdicts read differently on purpose (#930): a path left in
  the sandbox names the file and the scratch-file fix, while a changed repository prints a per-probe
  DIFF of the before/after snapshot and no scratch-file advice - `[status]`, `[diff]` and
  `[untracked]` mean a file in the checkout moved, `[head]`, `[branch]` and `[refs]` mean this
  worktree's git state did.
- The `pre-push` hook and CI run the validators, the changelog/version gates, and the `--check` drift
  guards on every push. The TEST SUITES are opt-in in the hook (`PREPUSH_TESTS=1 git push`, which adds
  the Python script unit tests and the changed plugins' suites, run in parallel), because running them
  inline measured ~30 minutes and most pushes ended up using `--no-verify` instead. The browser
  (Playwright) suites are opt-in too (`RUN_E2E=1`). CI is the authoritative gate for all of them and
  runs them on every PR. Run the relevant suite yourself before you push a change that touches it.
  In PowerShell, set the variable first: `$env:PREPUSH_TESTS = '1'; git push`.

## Pitfall checklist

- Did the new test fail on the OLD code? If it passed before your change, it is not pinning the change.
- Does every scratch file the test writes live under a `tempfile.TemporaryDirectory()`, and does every
  `git` spawn name its directory (`-C` / `cwd=`) with `clean_git_env()`? A bare relative name dirties
  the repository root.
- For a CSS or content change, did you run `build_site_data.py` before running the browser suite?
- For a layout assertion, is the viewport one where the behavior is actually observable?
- For a show/hide change, are you asserting visibility rather than a computed style on a hidden element?
- After a version bump, did you regenerate the fixtures (`node tests/fixtures/generate.mjs`)?
- Did you add or refine the spec row (`AREA-NN`) and keep the test title in sync with it?
- Is a workflow's `on:` trigger list valid? One invalid event makes the whole workflow startup-fail and
  silently skip a required check; `actionlint` does not catch every such case.
- Reading a parallel-run failure: did you take the test name from the `N) ...` failure header rather
  than a `[N/M]` progress line above it? Under `--reporter=line` that progress line names the last
  test to START, not the one that failed.
