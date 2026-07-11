# Site feature specification

The GitHub Pages site under `site/` is a fully static marketing and documentation surface for the
marketplace. It has a hub page (`site/index.html`), one generated plugin page per published plugin
(`site/commentable-html/index.html`), and a generated tutorial page
(`site/commentable-html/tutorial/index.html`). The client-side script (`site/assets/site.js`) is
progressive enhancement only: it wires up the copy buttons, the footer year, the demo slider, and
the tutorial image lightbox, and never fetches or injects remote data.

The core invariant is static self-containment. Every dynamic-looking region (the plugins grid, the
version badge, the changelog, the tutorial body, the synced demos and tutorial images) is generated
at build time by `scripts/build_site_data.py` from the repository's own sources
(`.github/plugin/marketplace.json` and the plugin `CHANGELOG.md` / `TUTORIAL.md`) and written into
marker regions of the committed HTML. The published site never fetches at runtime (no CORS or
`file://` breakage, no GitHub API rate limits, no runtime DOM injection), all text is HTML-escaped,
and every URL is allowlisted before it is written. The one deliberate remote dependency is the hub's
GitHub star widget, which is CSP-scoped and degrades to a plain link when blocked.

Coverage notation: each row lists the strongest automated coverage I found. `manual` means the
behavior is a documented convention rather than an automated test. Browser (E2E) rows cite
`tests/site/tests/site.spec.js`; generator rows cite `scripts/test_build_site_data.py`. The site is
gated on `main` by the required `site` check, which runs the generator unit tests and the browser
suite (see `.github/workflows/pages.yml`).

## Build pipeline: generation, escaping, and drift

| Feature id | Behavior | Covering tests |
| --- | --- | --- |
| SITE-BUILD-01 | The plugins grid, the version badge, and the changelog are generated from `marketplace.json` and the plugin `CHANGELOG.md` and written into named marker regions (`BEGIN:...`/`END:...`); the site performs no client-side fetch. | `scripts/test_build_site_data.py` - `RenderPluginsTests`, `ReplaceRegionTests`, `ChangelogInlineTests` |
| SITE-BUILD-02 | All repository text is HTML-escaped and every URL is passed through `safe_url`, which allows only https, mailto, and in-repo relative URLs and neutralizes dangerous or off-site schemes, control-char scheme smuggling, and backslash protocol-relative hosts, so repository content can never inject markup or an active link. | `scripts/test_build_site_data.py` - `SafeUrlTests`, `RenderPluginsTests.test_escapes_text_and_neutralizes_bad_homepage`, `RenderMarkdownTests.test_xss_neutralized_in_alt_and_raw_html`, `RenderMarkdownTests.test_dangerous_link_scheme_neutralized` |
| SITE-BUILD-03 | The changelog parser filters the root changelog to the target plugin, keeps all bullets for a per-plugin changelog, does not drop ungrouped bullets, joins continuation lines, strips the leading plugin name and version from an entry, and renders each bullet as inline Markdown that preserves code spans. | `scripts/test_build_site_data.py` - `ParseChangelogTests`, `CleanEntryTests`, `ChangelogCandidatesTests`, `ChangelogInlineTests`, `MdInlineTests` |
| SITE-BUILD-04 | The tutorial page is rendered from the skill's `docs/TUTORIAL.md`: headings offset, lists, bold, code spans and fenced blocks, images, and links render safely, and skill-root-relative example links are rewritten to the live demo report under `../demo/` that the site hosts. | `scripts/test_build_site_data.py` - `RenderMarkdownTests`, `RenderMarkdownOrderingTests`, `SiteTutorialMarkdownTests.test_rewrites_local_example_links_to_demo` |
| SITE-BUILD-05 | The demo reports under `site/commentable-html/demo/` are synced from the skill's `examples/`; a content difference or a missing destination is flagged under `--check` and fixed on a full run, and an orphaned demo is removed. | `scripts/test_build_site_data.py` - `SyncDemosDriftTests`, `SyncOrphanTests` |
| SITE-BUILD-06 | Tutorial images are synced from the skill's `docs/tutorial-images/`; a content difference is flagged then synced, an orphaned image whose source is gone is removed, and a missing source directory orphans the committed images. | `scripts/test_build_site_data.py` - `SyncTutorialImagesTests` |
| SITE-BUILD-07 | Every committed HTML page references its CSS and JS with a content-hash cache-busting query stamp at every path prefix (`assets/`, `./assets/`, `../assets/`); stamping replaces a stale stamp, is idempotent, leaves non-asset URLs untouched, and the committed pages carry current stamps with no stale or unstamped asset ref. | `scripts/test_build_site_data.py` - `StampAssetsTests`, `StampWiringTests` |
| SITE-BUILD-08 | `build_site_data.py --check` exits non-zero if the committed `site/` is stale versus its sources: a stale generated region, a drifted demo or tutorial image, or a stale asset stamp all fail the check (the required `site` check runs it on every pull request). | `scripts/test_build_site_data.py` - `CheckDriftTests`, `SyncDemosDriftTests`, `SyncTutorialImagesTests`, `StampWiringTests` |
| SITE-BUILD-09 | `replace_region` replaces exactly one delimited region and refuses to run when a marker region is missing or duplicated, so a generation step can never silently no-op or double-write. | `scripts/test_build_site_data.py` - `ReplaceRegionTests` |
| SITE-BUILD-10 | Changelog plugin matching is anchored and case-insensitive so a plugin name matches its own heading but not a mid-text mention or another plugin. | `scripts/test_build_site_data.py` - `MentionsPluginTests` |
| SITE-BUILD-11 | The changelog shows the two most recent releases inline and folds the next five into a collapsed `<details>`; any releases beyond those seven are not rendered inline but are summarized with a link to the full changelog in source, so the page never grows without bound. | `scripts/test_build_site_data.py` - `ChangelogInlineTests.test_older_releases_capped_and_rest_linked_to_source` |

## Hub page

| Feature id | Behavior | Covering tests |
| --- | --- | --- |
| SITE-HUB-01 | The hub renders the marketplace title, the brand logo, at least two plugin cards including `commentable-html`, and the one-time `marketplace add` install command. | `tests/site/tests/site.spec.js` - `hub renders with plugins, install command, and logo` |
| SITE-HUB-02 | The crimson theme is applied: the `--cp-accent` custom property resolves to `#b11f4b`. | `tests/site/tests/site.spec.js` - `theme variables are present (light + crimson)` |
| SITE-HUB-03 | The hub embeds the GitHub star widget and its Content-Security-Policy permits exactly what the widget needs: the `buttons.github.io` script/frame host, the `api.github.com` connect host for the star count, and `'unsafe-inline'` in `style-src` for the style the widget injects. | `tests/site/tests/site.spec.js` - `hub embeds the GitHub star widget and its CSP permits it` |
| SITE-HUB-04 | The star widget degrades to a visible plain link to the repository when its script is blocked. | `tests/site/tests/site.spec.js` - `star widget degrades to a visible plain link when its script is blocked` |
| SITE-HUB-05 | The footer year is filled in at load with the current calendar year. | `tests/site/tests/site.spec.js` - `footer year is filled in with the current year` |

## Plugin page

| Feature id | Behavior | Covering tests |
| --- | --- | --- |
| SITE-PLUGIN-01 | The plugin page renders the plugin title, a semver version badge, at least four feature blocks, at least one changelog release, and the live demo iframe pointing at the taxi report. | `tests/site/tests/site.spec.js` - `plugin page renders version, features, changelog, and demo` |
| SITE-PLUGIN-02 | The plugin page keeps a tight CSP: `script-src 'self'`, no star-widget script host, and no `'unsafe-inline'`. | `tests/site/tests/site.spec.js` - `plugin and tutorial pages keep a tight CSP (no widget relaxations)` |
| SITE-PLUGIN-03 | The plugin page links to its tutorial page. | `tests/site/tests/site.spec.js` - `plugin page links to the tutorial` |
| SITE-PLUGIN-04 | The demo report mounts inside the plugin-page iframe (the CSP permits the same-origin frame and its scripts). | `tests/site/tests/site.spec.js` - `demo mounts inside the iframe on the plugin page (CSP allows it)` |
| SITE-PLUGIN-05 | The plugin page hero shows the plugin logo image with descriptive alt text. | `tests/site/tests/site.spec.js` - `commentable-html hero shows the plugin logo` |
| SITE-PLUGIN-06 | The plugin-page nav brand link stays on the plugin page (does not jump to the hub), and a Marketplace link sits immediately after the GitHub link and returns to the hub. | `tests/site/tests/site.spec.js` - `commentable-html nav keeps the user on the page and offers a Marketplace link` |
| SITE-PLUGIN-07 | The plugin page footer links to the contributing guide, the feature-request form, the issue chooser, the plugin source tree, and the author's LinkedIn profile. | `tests/site/tests/site.spec.js` - `the plugin page footer links to contribute, feature request, issues, source, and the author's LinkedIn` |

## Demo slider

| Feature id | Behavior | Covering tests |
| --- | --- | --- |
| SITE-DEMO-01 | The demo has a single full-screen button that opens in a new tab with `rel="noopener"`, and a two-option slider whose Taxi tab is active by default. | `tests/site/tests/site.spec.js` - `demo has one safe full-screen button and a two-option slider` |
| SITE-DEMO-02 | Selecting a slider tab switches the iframe `src`, the demo title, and the full-screen target to the chosen report. | `tests/site/tests/site.spec.js` - `demo slider switches the iframe, title, and full-screen target` |
| SITE-DEMO-03 | The slider is keyboard operable: arrow keys move focus and switch the shown report. | `tests/site/tests/site.spec.js` - `demo tabs are keyboard operable (arrow keys switch the shown report)` |
| SITE-DEMO-04 | The slider implements a complete ARIA tabs contract: `role="tabpanel"` panel, `aria-controls`, `aria-selected`, a roving `tabindex`, an `aria-labelledby` that tracks the active tab, and Home/End jump to the first/last tab. | `tests/site/tests/site.spec.js` - `demo tabs expose a complete ARIA tabs contract` |
| SITE-DEMO-05 | Both demo reports load standalone and their commentable-html toolbars mount. | `tests/site/tests/site.spec.js` - `both demo reports load and their toolbars mount` |
| SITE-DEMO-06 | The demo frame breaks out of the content column to span the full viewport width, while the "Try it live" heading, its description, and the slider stay aligned with the other section headings in the content column. | `tests/site/tests/site.spec.js` - `the demo frame spans the full viewport width while its heading stays in the content column` |
| SITE-DEMO-07 | The demo full-screen button carries an accent-tinted (light-red) background so it reads as the primary action in the frame bar. | `tests/site/tests/site.spec.js` - `the full-screen button has a light-red (accent-tinted) background` |

## Copy buttons

| Feature id | Behavior | Covering tests |
| --- | --- | --- |
| SITE-COPY-01 | The install copy button copies the exact command to the clipboard and shows a `copied` confirmation. | `tests/site/tests/site.spec.js` - `install command copy button copies the command and shows feedback` |
| SITE-COPY-02 | When both the async clipboard and `execCommand` fail, the copy button shows a `press Ctrl+C` manual-copy hint and a `copy-failed` state instead of claiming success. | `tests/site/tests/site.spec.js` - `copy button shows a manual-copy hint when the clipboard is unavailable` |
| SITE-COPY-03 | A rapid double click restores the copy button's original label after its feedback window. | `tests/site/tests/site.spec.js` - `copy button restores its original label after a rapid double click` |

## Tutorial page

| Feature id | Behavior | Covering tests |
| --- | --- | --- |
| SITE-TUT-01 | The tutorial page renders from `TUTORIAL.md` with a real heading structure and images whose sources all resolve (no broken images). | `tests/site/tests/site.spec.js` - `tutorial page renders from TUTORIAL.md with working images` |
| SITE-TUT-02 | The tutorial page keeps the same tight CSP as the plugin page (no star-widget relaxations, no inline scripts/styles). | `tests/site/tests/site.spec.js` - `plugin and tutorial pages keep a tight CSP (no widget relaxations)` |
| SITE-TUT-03 | Clicking a tutorial content image opens a full-size lightbox overlay showing that image, and Escape (or clicking the overlay) closes it. | `tests/site/tests/site.spec.js` - `clicking a tutorial image opens a full-size lightbox that Escape closes` |
| SITE-TUT-04 | The tutorial-page nav brand link returns to the commentable-html plugin home, not the hub root. | `tests/site/tests/site.spec.js` - `tutorial brand keeps the user in the commentable-html section` |
| SITE-TUT-05 | The tutorial's example-file links resolve to the live demo report under `../demo/` (not a GitHub blob URL), so a reader opens the running report in the browser. | `tests/site/tests/site.spec.js` - `tutorial example links open the live demo, not a GitHub blob` |

## Security, portability, and accessibility

| Feature id | Behavior | Covering tests |
| --- | --- | --- |
| SITE-SEC-01 | The static file server refuses a request whose raw request-target traverses out of `site/` (403), mirroring the deployed Pages boundary the suite validates against. | `tests/site/tests/site.spec.js` - `the static test server refuses path traversal out of site/` |
| SITE-SEC-02 | No internal link or asset on any page uses a root-relative path, because a root-relative path would break under the `/ai-marketplace/` project sub-path. | `tests/site/tests/site.spec.js` - `no internal link or asset uses a root-relative path (would break the project sub-path)` |
| SITE-SEC-03 | Every internal link and asset on the hub, plugin, and tutorial pages resolves (no broken internal URLs). | `tests/site/tests/site.spec.js` - `no broken internal links or assets` |
| SITE-A11Y-01 | Every page exposes a skip-to-content link that targets the `main` region. | `tests/site/tests/site.spec.js` - `every page exposes a skip-to-content link that targets the main region` |
| SITE-A11Y-02 | Every image on the hub, plugin, and tutorial pages carries non-empty alt text. | `tests/site/tests/site.spec.js` - `every image on every page has non-empty alt text` |

## Coverage gaps

Every behavior in the tables above has an automated test. The `site/assets/styles.css` visual and
responsive rules are exercised indirectly (the theme accent variable and the ARIA/layout tests
render the real stylesheet) but do not have per-breakpoint pixel assertions; commentable-html has
its own responsive suite under `plugins/commentable-html/dev/tests/`. Add a spec row and a covering
test in the same pull request whenever the site grows a new behavior (see AGENTS.md, "Spec-and-test
discipline").
