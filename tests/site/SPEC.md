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
| SITE-BUILD-05 | The demo reports under `site/commentable-html/demo/` are synced from the skill's `examples/`; a content difference or a missing destination is flagged under `--check` and fixed on a full run, and an orphaned demo is removed. Orphans are discovered and reported in deterministic sorted order so `--check` output does not depend on directory-listing order. | `scripts/test_build_site_data.py` - `SyncDemosDriftTests`, `SyncOrphanTests` (including `test_orphans_reported_in_sorted_order`) |
| SITE-BUILD-06 | Tutorial images are synced from the skill's `docs/tutorial-images/`; a content difference is flagged then synced, an orphaned image whose source is gone is removed, and a missing source directory orphans the committed images. | `scripts/test_build_site_data.py` - `SyncTutorialImagesTests` |
| SITE-BUILD-07 | Every committed HTML page references its CSS and JS with a content-hash cache-busting query stamp at every path prefix (`assets/`, `./assets/`, `../assets/`); stamping replaces a stale stamp, is idempotent, leaves non-asset URLs untouched, and the committed pages carry current stamps with no stale or unstamped asset ref. | `scripts/test_build_site_data.py` - `StampAssetsTests`, `StampWiringTests` |
| SITE-BUILD-08 | `build_site_data.py --check` exits non-zero if the committed `site/` is stale versus its sources: a stale generated region, a drifted demo or tutorial image, or a stale asset stamp all fail the check (the required `site` check runs it on every pull request). | `scripts/test_build_site_data.py` - `CheckDriftTests`, `SyncDemosDriftTests`, `SyncTutorialImagesTests`, `StampWiringTests` |
| SITE-BUILD-09 | `replace_region` replaces exactly one delimited region and refuses to run when a marker region is missing or duplicated, so a generation step can never silently no-op or double-write. | `scripts/test_build_site_data.py` - `ReplaceRegionTests` |
| SITE-BUILD-10 | Changelog plugin matching is anchored and case-insensitive so a plugin name matches its own heading but not a mid-text mention or another plugin. | `scripts/test_build_site_data.py` - `MentionsPluginTests` |
| SITE-BUILD-11 | The changelog shows the two most recent releases inline and folds the next five into a collapsed `<details>`; any releases beyond those seven are not rendered inline but are summarized with a link to the full changelog in source, so the page never grows without bound. | `scripts/test_build_site_data.py` - `ChangelogInlineTests.test_older_releases_capped_and_rest_linked_to_source` |
| SITE-BUILD-12 | Each plugin card renders its manifest `category` as a badge and its `keywords` as chips; for `commentable-html` this is the "planning and analysis" category badge and the analysis/plan/report keyword chips. | `scripts/test_build_site_data.py` - `RenderPluginsTests.test_real_manifest_commentable_badge_and_chips` |
| SITE-BUILD-13 | The served `site/assets/styles.css` is assembled by `build_site_data.py` from ordered source partials under `site-src/css/` (concatenated in a fixed, cascade-preserving order); the committed stylesheet is byte-identical to the concatenation and `--check` fails if it drifts from the partials. | `scripts/test_build_site_data.py` - `StylesConcatTests.test_concat_matches_committed_stylesheet`, `StylesConcatTests.test_parts_exist_and_base_loads_first` |
| SITE-BUILD-14 | The hub, plugin, and tutorial pages are pure build artifacts: their hand-edited SOURCE lives under `site-src/pages/` and `build_site_data.py` assembles the committed `site/**` pages from it, injecting a `GENERATED FILE - DO NOT EDIT` banner (and a `/* ... */` banner in `styles.css`) that names the source. Because the source is independent of the artifact, `--check` compares the whole built page (not just the marker regions) to the committed file, so a hand-edit to any part of a built page - or a built page missing entirely - fails `--check`. The hub and plugin pages are REQUIRED: a missing source raises a clear `SystemExit` (they cannot be dropped). The tutorial page is OPTIONAL: removing its source removes the page (its built artifact is deleted on a normal build and its `llms.txt`/sitemap link is dropped), and a built tutorial artifact left behind after its source was removed is flagged as an orphan by `--check`. `build_page` fails loudly (`SystemExit`) on a source with no doctype or an unknown region-filler kind, and the editable sources under `site-src/pages/` never carry the generated banner. | `scripts/test_build_site_data.py` - `CheckDriftTests.test_check_flags_a_hand_edited_built_page`, `test_check_flags_an_orphaned_page_whose_source_was_removed`, `test_check_flags_a_missing_built_page_when_its_source_exists`, `test_write_removes_an_orphaned_page_whose_source_was_removed`, `test_removing_tutorial_source_drops_its_llms_link`, `test_missing_required_page_source_errors_clearly` (end-to-end via `main(["--check"])`); `PageBannerAndGuardTests` (banner present/idempotent, `build_page` fills+banners+rejects unknown kind and no-doctype, hand-edit differs from a fresh build, missing artifact is drift, committed sources are banner-free, stylesheet carries the banner) |

## Hub page

| Feature id | Behavior | Covering tests |
| --- | --- | --- |
| SITE-HUB-01 | The hub renders the marketplace title, the brand logo, at least two plugin cards including `commentable-html`, and the one-time `marketplace add` install command. | `tests/site/tests/site.spec.js` - `hub renders with plugins, install command, and logo` |
| SITE-HUB-02 | The crimson theme is applied: the `--cp-accent` custom property resolves to `#b11f4b`. | `tests/site/tests/site.spec.js` - `theme variables are present (light + crimson)` |
| SITE-HUB-03 | The hub embeds the GitHub star widget and its Content-Security-Policy permits exactly what the widget needs: the `buttons.github.io` script/frame host, the `api.github.com` connect host for the star count, and `'unsafe-inline'` in `style-src` for the style the widget injects. | `tests/site/tests/site.spec.js` - `hub embeds the GitHub star widget and its CSP permits it` |
| SITE-HUB-04 | The star widget degrades to a visible plain link to the repository when its script is blocked. | `tests/site/tests/site.spec.js` - `star widget degrades to a visible plain link when its script is blocked` |
| SITE-HUB-05 | The footer year is filled in at load with the current calendar year. | `tests/site/tests/site.spec.js` - `footer year is filled in with the current year` |
| SITE-HUB-06 | A plugin card is a whole-card click target to its plugin page via the title link and progressive card handler, while the install/copy block and the foot buttons stay independently clickable above it (no navigation, no cursor flicker). The card body carries a pointer cursor so it reads as clickable, while the install/copy block stays a text surface (not pointer). | `tests/site/tests/site.spec.js` - `a plugin card is clickable across its body, navigating to the plugin page (SITE-HUB-06)`, `the card copy button and Learn more stay independently clickable over the card link (SITE-HUB-06)`, `the plugin card body shows a pointer cursor so it reads as clickable (SITE-HUB-06)` |
| SITE-HUB-07 | The plugin card `Learn more` button uses the brand accent color (`--cp-accent`), not the former amber. | `tests/site/tests/site.spec.js` - `the hub Learn more button uses the brand accent color, not yellow (SITE-HUB-07)` |
| SITE-HUB-08 | Selecting text in a plugin-card description or keyword suppresses stretched-card navigation so users can copy the text, while a plain body click with no selection still navigates to the plugin page. | `tests/site/tests/site.spec.js` - `plugin card text can be selected without navigation and plain body clicks still navigate (SITE-HUB-08)` |

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
| SITE-PLUGIN-08 | The plugin page hero leads with the H1 and CTAs; the identity line (logo, name, and version badge) sits below the call-to-action buttons and links to the plugin's source directory on GitHub. | `tests/site/tests/site.spec.js` - `the plugin page identity line (logo, name, version) sits below the call-to-action buttons` |
| SITE-PLUGIN-09 | The portability section presents three modes (Non-portable, Portable, Offline), each with a source graph (`.mode-sources`) of color-coded chips showing where every part comes from; Offline shows the mermaid/charts inlined (no CDN chip) while Non-portable keeps a CDN chip. | `tests/site/tests/site.spec.js` - `the portability section shows three modes including Offline with a source graph (SITE-PLUGIN-09)` |
| SITE-PLUGIN-10 | The portability section carries a footnote (`.modes-note`) explaining that the CDN chip is a network dependency: a Non-portable or Portable report that uses mermaid diagrams or charts needs an internet connection to render them, and Export Offline inlines them to remove that dependency. | `tests/site/tests/site.spec.js` - `the portability section explains the CDN chip needs a network connection and Offline removes it (SITE-PLUGIN-10)` |
| SITE-PLUGIN-11 | The "What you get" section covers exporting an Offline, zero-network copy (mermaid/chart snapshots inlined, remote loaders stripped) alongside Portable. | `tests/site/tests/site.spec.js` - `the What you get section covers exporting an Offline, zero-network copy (SITE-PLUGIN-11)` |
| SITE-WHY-01 | The review-loop diagram lives in the "Why commentable-html" section (moved out of "How the review loop works"), which keeps its heading and the three self/peer/reviewer step columns. | `tests/site/tests/site.spec.js` - `the review-loop diagram lives in the Why section, not the loop section` |
| SITE-WHY-02 | The "Why commentable-html" section includes a medium-comparison table (chat / Markdown / plain HTML / commentable-html) with commentable-html as the highlighted `compare-hero` row, and references Anthropic's "unreasonable effectiveness of HTML" blog post (opens in a new tab, `rel=noopener`). | `tests/site/tests/site.spec.js` - `the Why section presents the medium comparison table and the HTML blog reference` |
| SITE-WHY-03 | On a narrow (mobile) viewport the medium-comparison table stacks each row into a labeled card (column names exposed via `td[data-label]::before`) with no horizontal overflow; the tablet/desktop table layout is unchanged. | `tests/site/tests/site.spec.js` - `the medium comparison table stacks without horizontal overflow on a narrow viewport` |
| SITE-WHY-04 | On a narrow (mobile) viewport the review-loop diagram swaps from the wide horizontal SVG (`.loop-fig-h`) to a tall vertical SVG (`.loop-fig-v`, taller than it is wide) so its labels are not cramped against the boxes; the horizontal variant is shown on desktop/tablet and the two live in the single `.loop-figure` container. The vertical variant numbers each transfer with a badge (`.loop-fig-badge`) anchored to its directional arrow (agent-to-you down on the left, you-to-agent up on the right) with `Comment inline` at You and a `reload and repeat` caption, so the flow direction and who-does-what stay clear without the desktop layout. | `tests/site/tests/site.spec.js` - `the review-loop diagram swaps to a vertical, uncramped layout on a mobile viewport (SITE-WHY-04)` |
| SITE-WHY-05 | On a narrow (mobile) viewport the medium-comparison cards drop the full-cell hero fill and instead tint only each verdict (green good, red bad) and show a good/total score next to each card title (e.g. `3/5`, `5/5`); the tablet/desktop table is unchanged. | `tests/site/tests/site.spec.js` - `mobile comparison cards color only the verdicts and show a good/total score (SITE-WHY-05)` |
| SITE-WHY-06 | The "Why" section states that Commentable HTML drastically shortens the AI planning and iteration loop. | `tests/site/tests/site.spec.js` - `the Why section states commentable-html shortens the AI planning loop` |
| SITE-NAV-01 | Every section with an `id` and a `.section-title` heading (on the hub and plugin pages) has its heading text wrapped in a `.header-anchor` link with `href="#<section-id>"`, so clicking the heading text itself links directly to that section. There is no separate `#` marker glyph; the whole heading is the link. Clicking updates the URL fragment and copies the section's full URL to the clipboard when available; that URL is built from the anchor's own resolved `href`, so it stays a valid absolute URL for any protocol/base (including `file://`, where `location.origin` is the string "null") and preserves the current query string. A heading that already holds an interactive element (`a`/`button`) is skipped, so the enhancement never nests an `<a>` inside an `<a>`. The anchor is a progressive enhancement wired by `site.js`. | `tests/site/tests/site.spec.js` - `every section header is a linkable anchor that updates the URL fragment (SITE-NAV-01)`, `section header anchor copies a shareable URL that keeps the query string (SITE-NAV-01)`, `initHeaderAnchors leaves a section whose title already holds a link untouched (SITE-NAV-01)` |
| SITE-WHY-07 | The "Why" section opens by framing HTML as the de-facto standard for planning and reporting with AI agents (rather than claiming agents "increasingly answer with HTML"). | `tests/site/tests/site.spec.js` - `the Why section frames HTML as the de-facto standard for AI planning and reporting (SITE-WHY-07)` |

## Demo slider

| Feature id | Behavior | Covering tests |
| --- | --- | --- |
| SITE-DEMO-01 | The demo has a single full-screen button that opens in a new tab with `rel="noopener"` and announces the new-tab behavior in its accessible name, and a four-option slider whose Taxi tab is active by default. | `tests/site/tests/site.spec.js` - `demo has one safe full-screen button and a four-option slider`; `scripts/test_build_site_data.py` - `DemoFullscreenTests.test_link_accessible_name_announces_new_tab` |
| SITE-DEMO-02 | Selecting a slider tab switches the iframe `src`, the demo title, and the full-screen target to the chosen report. | `tests/site/tests/site.spec.js` - `demo slider switches the iframe, title, and full-screen target` |
| SITE-DEMO-03 | The slider is keyboard operable: arrow keys move focus and switch the shown report. | `tests/site/tests/site.spec.js` - `demo tabs are keyboard operable (arrow keys switch the shown report)` |
| SITE-DEMO-04 | The slider implements a complete ARIA tabs contract: `role="tabpanel"` panel, `aria-controls`, `aria-selected`, a roving `tabindex`, an `aria-labelledby` that tracks the active tab, and Home/End jump to the first/last tab. | `tests/site/tests/site.spec.js` - `demo tabs expose a complete ARIA tabs contract` |
| SITE-DEMO-05 | All four demo reports (Taxi, Community Garden, Triage Board, and Visuals Matrix) load standalone and their commentable-html toolbars mount. | `tests/site/tests/site.spec.js` - `all demo reports load and their toolbars mount` |
| SITE-DEMO-06 | The demo frame breaks out of the content column (it is clearly wider than the column), while the "Try it live" heading, its description, and the slider stay aligned with the other section headings in the content column. | `tests/site/tests/site.spec.js` - `the demo frame breaks out of the content column while its heading stays in the content column` |
| SITE-DEMO-07 | The demo full-screen button carries an accent-tinted (light-red) background so it reads as the primary action in the frame bar. | `tests/site/tests/site.spec.js` - `the full-screen button has a light-red (accent-tinted) background` |
| SITE-DEMO-08 | The full-bleed demo frame keeps a comfortable side buffer (~50px each side) so it never runs too wide or touches the viewport edges. | `tests/site/tests/site.spec.js` - `the full-bleed demo frame keeps a comfortable side buffer inside the viewport (SITE-DEMO-08)` |

## Copy buttons

| Feature id | Behavior | Covering tests |
| --- | --- | --- |
| SITE-COPY-01 | The install copy button copies the exact command to the clipboard and shows a `copied` confirmation. | `tests/site/tests/site.spec.js` - `install command copy button copies the command and shows feedback` |
| SITE-COPY-02 | When both the async clipboard and `execCommand` fail, the copy button shows a platform-neutral manual-copy hint and a `copy-failed` state instead of claiming success. | `tests/site/tests/site.spec.js` - `copy failure gives a platform-neutral manual hint` |
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
| SITE-A11Y-03 | Copy success and failure feedback is exposed through a polite, atomic live region so assistive technology announces the outcome. | `tests/site/tests/site.spec.js` - `install command copy button copies the command and shows feedback`, `copy failure gives a platform-neutral manual hint` |
| SITE-A11Y-04 | A plugin card with a page keeps keyboard-focusable title and Learn more links; the title link stretches over the card and the card handler forwards plain body clicks to it, while the install/copy block and foot buttons remain independently clickable. The Learn more button uses the brand accent color and keeps WCAG AA contrast in light and dark. | `tests/site/tests/site.spec.js` - `plugin card keeps keyboard links plus the stretched overlay and independent controls (SITE-A11Y-04)`, `the Learn more button keeps AA contrast in light and dark themes`; `scripts/test_build_site_data.py` - `RenderPluginsTests.test_plugin_card_title_and_learn_more_link_to_page`, `RenderPluginsTests.test_card_without_page_has_no_learn_more` |
| SITE-A11Y-05 | The portability source chips for CDN and inlined assets meet WCAG AA contrast in the light theme by using readable text color; category color is conveyed by chip accents instead of low-contrast foreground text. | `tests/site/tests/site.spec.js` - `portability source chips keep AA contrast in the light theme (SITE-A11Y-05)` |

## Theme

| Feature id | Behavior | Covering tests |
| --- | --- | --- |
| SITE-THEME-01 | The site follows the operating system light or dark color preference with token-based colors that maintain WCAG AA contrast for normal text, links, and primary buttons on page and card backgrounds. | `tests/site/tests/site.spec.js` - `light and dark themes preserve readable contrast` |

## Discoverability (SEO, social, and AI answer engines)

| Feature id | Behavior | Covering tests |
| --- | --- | --- |
| SITE-SEO-01 | Every page carries a self-referencing `<link rel="canonical">` with its absolute production URL, so the trailing-slash/non-slash duplicates do not split indexing. | `tests/site/tests/site.spec.js` - `hub head exposes canonical, Open Graph, and Twitter Card tags`, `plugin and tutorial pages carry a self-referencing canonical and Open Graph metadata` |
| SITE-SEO-02 | Every page emits Open Graph (type, site_name, title, description, url, image + dimensions/alt) and Twitter `summary_large_image` Card tags, so a shared link renders a real preview card on social and chat. | `tests/site/tests/site.spec.js` - `hub head exposes canonical, Open Graph, and Twitter Card tags`, `plugin and tutorial pages carry a self-referencing canonical and Open Graph metadata` |
| SITE-SEO-03 | The hub embeds a JSON-LD graph (WebSite + author Person + an ItemList of the plugins as SoftwareApplication) generated from `marketplace.json`, with `<`, `>`, and `&` escaped so manifest text cannot break out of the `<script>` block; the strict `script-src 'self'` CSP does not block the data block. | `scripts/test_build_site_data.py` - `JsonLdTests`; `tests/site/tests/site.spec.js` - `the hub embeds valid JSON-LD describing the site and its plugins` |
| SITE-SEO-04 | The plugin page embeds a static SoftwareApplication + BreadcrumbList JSON-LD graph (no version field, so it cannot drift). | `tests/site/tests/site.spec.js` - `the plugin page embeds SoftwareApplication and BreadcrumbList JSON-LD` |
| SITE-SEO-05 | `build_site_data.py` generates `site/sitemap.xml` listing the hub, each plugin page, and the tutorial; `--check` fails when the committed sitemap is stale. | `scripts/test_build_site_data.py` - `SitemapTests`, `WriteOrCheckTests`, `CheckDriftTests`; `tests/site/tests/site.spec.js` - `sitemap.xml is served and lists the hub, plugin, and tutorial pages` |
| SITE-SEO-06 | `build_site_data.py` generates `site/llms.txt` (marketplace summary, install commands, per-plugin links and descriptions, and the tutorial link) from the manifest; `--check` fails when it is stale. | `scripts/test_build_site_data.py` - `LlmsTests`, `WriteOrCheckTests`, `CheckDriftTests`; `tests/site/tests/site.spec.js` - `llms.txt is served and links each plugin and the tutorial` |
| SITE-SEO-07 | A 1200x630 social cover image (`site/assets/og-cover.png`) is served and is referenced by `og:image` on every page. | `tests/site/tests/site.spec.js` - `the og:image cover asset is served as a PNG`, `hub head exposes canonical, Open Graph, and Twitter Card tags` |
| SITE-SEO-08 | The hub H1 reads as continuous, correctly spaced text ("A marketplace of AI plugins for the Copilot CLI") so crawlers and screen readers get clean wording despite the styled line break. | `tests/site/tests/site.spec.js` - `the hub H1 reads as continuous text with correct word spacing` |
| SITE-SEO-09 | The plugin and tutorial page titles plus social titles use the display name "Commentable HTML" and "Commentable HTML tutorial", while canonical/OG URLs and the plugin page SoftwareApplication JSON-LD `name` keep the literal `commentable-html` identifier. | `tests/site/tests/site.spec.js` - `plugin and tutorial metadata use display titles while stable identifiers keep the slug (SITE-SEO-09)` |

## Coverage gaps

Every behavior in the tables above has an automated test. The `site/assets/styles.css` visual and
responsive rules are exercised indirectly (the theme accent variable and the ARIA/layout tests
render the real stylesheet) but do not have per-breakpoint pixel assertions; commentable-html has
its own responsive suite under `plugins/commentable-html/dev/tests/`. Add a spec row and a covering
test in the same pull request whenever the site grows a new behavior (see AGENTS.md, "Spec-and-test
discipline").
