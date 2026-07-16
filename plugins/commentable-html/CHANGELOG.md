# Changelog

All notable changes to the `commentable-html` plugin are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.118.0] - 2026-07-16

### Added

- Deck navigation: dimmed edge hover-arrows for previous/next slide and Enter/Space to advance when the deck stage is focused (issue #292).

## [1.117.1] - 2026-07-16

### Changed

- Split the shipped layer validator check module into focused assembled topic parts while preserving the public `check_layer` entry point and validation behavior.

## [1.117.0] - 2026-07-16

### Added

- Document-overview strip for report/plan documents: a `cm-skip` `div.cmh-doc-stats` placed
  directly under the `<h1>` title shows the section count, word count, and approximate reading time
  (words / 200 wpm, rounded up). `tools/authoring/doc_stats.py` computes and injects it, and
  `new_document.py`, `finalize.py`, and `retrofit.py` bake it by default for report/plan documents
  (opt out with `--no-stats`). It is idempotent (counts refresh in place), excluded from its own
  word count, and baked into the content so it survives Plain / Standalone export. (CMH-STATS-01)
- Per-version upgrade anti-regression corpus under `dev/upgrade-corpus/`: `tests/test_upgrade_corpus.py`
  upgrades each checked-in fully layered snapshot with the current `tools/authoring/upgrade.py` and
  asserts a strict-clean, idempotent result, so a layer or tool change that breaks upgrading a
  document produced by an older version fails the gate. Snapshots are added per change when a
  version warrants one. (CMH-TOOL-20)

### Fixed

- The generated table of contents no longer double-numbers author-numbered sections. When a heading
  already begins with a section number (for example `1. Executive summary`), `generate_toc.py` strips
  the redundant leading number from the ordered-list entry so the `<ol>` supplies the single number,
  and `finalize.py` / `retrofit.py` de-dup an existing author `<ol>` `.cm-toc` in place. A `<ul>`
  `.cm-toc` (where the author supplies the number deliberately) is left untouched. (CMH-TOC-10)

## [1.116.0] - 2026-07-16

### Changed

- Reworked the showcase deck's Act 4 "behind the scenes" run so it now teaches the
  deterministic region split, the website-style portability model, how the skill is
  assembled from `SKILL.md`, on-demand references, and authoring/validation tools,
  plus the cross-platform Playwright-and-Python validation methodology behind the
  shipped experience. (CMH-DECK-SHOWCASE-06)

## [1.115.0] - 2026-07-16

### Added

- The runtime footer now shows a small copy icon that copies the creating AI agent's
  session id to the clipboard when the document carries a `commentable-html-session-id`
  provenance stamp; the button's accessible label and tooltip name the agent (Copilot or
  Claude), and the control never leaks into a Plain HTML export. (CMH-FOOT-04)
- The document-producing tools (`new_document.py`, `deck_scaffold.py`) stamp that session
  id by default, taking it from `--session-id` or, when absent, an auto-detected
  environment variable (`COPILOT_AGENT_SESSION_ID` for Copilot, `CLAUDE_CODE_SESSION_ID`
  for Claude). `--agent` overrides the label and `--no-session-id` opts out. When several
  agents' session ids are visible at once (a nested launch), the agent actually running the
  tool wins. A local, non-CI live check that drives the real `copilot`/`claude` CLIs is at
  `dev/tests/copilot_e2e_check.py` and `dev/tests/claude_e2e_check.py`. (CMH-STAMP-04)

## [1.108.1] - 2026-07-16

### Changed

- Restructured the showcase deck's narrative flow: added a dedicated header/pitch slide,
  moved the website-style medium comparison and shipped-example prompts earlier, removed
  the redundant recap slide, and replaced the close with a "What's next?" hub plus a
  trailing "Questions?" slide while keeping the shipped widget defaults unchanged.
  (CMH-DECK-SHOWCASE-05)
## [1.107.0] - 2026-07-16

### Changed

- Hardened the information-density advisory (CMH-VAL-15) for authoring edge cases: an inline
  `cm-skip` inside a paragraph now excludes only its own text instead of splitting the paragraph;
  sections are tracked as a heading stack so nested and headless sections are labeled by their own
  heading and two distinct prose walls are each reported; a stray or unmatched `</section>` no
  longer suppresses a genuine wall; and a `<section>` embedded in a layout block no longer reframes
  the enclosing prose section. (CMH-VAL-15)

## [1.106.0] - 2026-07-16

### Added

- `deck/deck_validate.py` now emits a non-fatal per-slide or board-card overload advisory
  when authored content exceeds tunable line or element budgets, helping authors split dense deck
  content before sharing. (CMH-DECK-19)

## [1.105.0] - 2026-07-16

### Changed

- Split the Chart.js reference into focused embedding/tooltips and recipes/data-hygiene guides, leaving `charts.md` as a thin router so agents can load only the chart guidance they need. (CMH-DOC-16)

## [1.104.0] - 2026-07-16

### Added

- `npm run shots` now regenerates all tutorial screenshots from the community-garden example with
  pinned capture state, and `npm run shots:check` plus `rebuild_all.py --check` catch missing or
  stale committed tutorial screenshots before the site syncs them. (CMH-TUT-SHOTS-01)

## [1.102.0] - 2026-07-16

### Added

- The validator now emits a non-fatal information-density advisory for `report` and `plan`
  documents: it warns when a section is a wall of four or more consecutive long paragraphs with no
  table, list, figure, diff, chart, or diagram to break it up, nudging authors toward a real
  skimmable layout. The check uses a dedicated density pass scoped to `#commentRoot`, ignores
  `cm-skip` and paragraphs nested inside layout blocks, resets at any layout block, heading, or
  section boundary, and runs only for `report` and `plan` (`slides`, `board`, `generic`, and a
  missing or unknown kind are exempt). Its thresholds are tunable. (CMH-VAL-15)

## [1.101.0] - 2026-07-16

### Added

- The flat-document validator now checks authored `--cp-*` theme overrides for WCAG contrast,
  evaluating the light and dark theme environments separately so a token overridden only in one
  theme is judged against that theme's value. It runs only on tokens changed from the shipped
  defaults (the accepted defaults are never flagged): text and link pairs use a 4.5:1 target (a
  3.0-4.49:1 near-miss is an advisory warning, below 3.0:1 is an error) and non-text UI pairs use
  a 3.0:1 bar. An override that cannot be resolved to two concrete colors is reported as
  'not evaluated' (a static check, no computed-style parity). A new `--suggest` flag prints a
  compliant nudged value when one is reachable, and the near-miss/unresolved advisories stay out of
  `retrofit.py`'s hard-fail path unless the contrast is actually bad. (CMH-THEME-02)

## [1.100.0] - 2026-07-16

### Added

- Added `tools/deck/deck_fix_fonts.py` to strip copied remote deck font loaders and
  deterministically map web-font stacks to approved system stacks before deck validation.
  (CMH-DECK-18)

## [1.98.0] - 2026-07-16

### Added

- `new_document.py`, `retrofit.py`, and `deck_scaffold.py` now accept `--brand brand.json`
  to stamp validated `--cp-*` theme tokens plus optional local data-URI font faces into
  generated documents, reject unknown or injection-shaped token values, and print a
  low-contrast advisory for unsafe brand color pairs. (CMH-TOOL-19)

## [1.96.0] - 2026-07-16

### Fixed

- Clear now restores slot-level draggable boards to their load-time sibling order,
  including interleaved non-part nodes, while clean boards are left untouched.
  (CMH-BOARD-05)

## [1.94.0] - 2026-07-16

### Added

- Authors can set `data-cm-density="compact"` or `data-cm-density="comfortable"` on
  `#commentRoot` to tune review chrome spacing and font scale through shared
  `--cp-chrome-*` tokens, while documents without the attribute keep the existing
  default density. (CMH-DENSITY-01)

## [1.93.0] - 2026-07-16

### Added

- `tools/authoring/recommend_kind.py` now recommends `--kind report`, `--kind plan`, or
  `--kind slides` from filename and content signals, prints the evidence behind the
  recommendation, and emits advisory mismatch warnings when an explicit kind contradicts
  the signals without changing the chosen kind. (CMH-KIND-04)

## [1.92.0] - 2026-07-16

### Added

- Deck documents now deep-link by stable `data-slide-id`: loading a slide hash opens that slide,
  slide navigation updates the URL hash with `history.replaceState`, and browser hash changes
  navigate without adding runtime history entries. (CMH-DECK-17)

## [1.88.0] - 2026-07-16

### Added

- Flat commentable documents now print and export to PDF cleanly: print media hides runtime chrome,
  expands collapsed sections, resets fixed or shadowed UI into a readable paper flow, appends current
  comments as a print-only appendix, and keeps decks at one slide per page. (CMH-PRINT-01)

## [1.87.0] - 2026-07-16

### Added

- The layer now honors the operating-system "reduce motion" setting
  (`prefers-reduced-motion: reduce`): non-essential animations and transitions (the composer flash,
  the mermaid and diff pulses, the checklist and notes flashes) - including their delays and
  repeat loops - are clamped to a near-instant single pass so they do not animate for
  motion-sensitive readers, while everything still lands in its final state. Programmatic smooth
  scrolls (jump-to-comment, scroll-to-top/bottom, deep links) also become instant under the
  preference. (The deck slide stage keeps the vendored slide engine's own reduced-motion rule for
  its essential slide transition.) (CMH-A11Y-07)

## [1.86.0] - 2026-07-16

### Fixed

- `new_document.py --out` now preserves an existing target by writing the first free
  `-2` / `-3` suffixed sibling unless `--force` is supplied, and derives `--key auto`
  from that final resolved path so colliding document creations do not share keys.
  (CMH-TOOL-18)

## [1.85.0] - 2026-07-16

### Fixed

- Updated stale shipped-doc tool paths, including the plugin README's validation,
  document-creation, and handled-comment paths, to the current `tools/<topic>/...` buckets.
  Added a docs test so future tool-layout refactors cannot leave stale README paths behind.
  (CMH-DOC-15)

## [1.82.0] - 2026-07-16

### Added

- The shipped skill now carries the MIT `LICENSE` at its root, so every copy that ships (the
  Copilot/Claude `plugin install` source subtree and the Claude Desktop skill ZIP) redistributes the
  code with its required license notice. (CMH-DOC-14)

## [1.81.0] - 2026-07-16

### Added

- Callouts now carry a non-color cue so their meaning survives grayscale printing,
  color-blindness, and screen readers: each variant (info/success/warning/danger) shows a distinct
  leading glyph, and the runtime stamps `role="note"` with a variant label. An authored leading
  `<strong>` label (or an explicit `aria-label`) is respected so the variant is not announced twice.
  (CMH-CALLOUT-03)

## [1.80.0] - 2026-07-15

### Added

- The wide-screen side navigation menu now has a filter box that searches AS a filter over the
  document: typing hides each matching entry's section (for section-wrapped content) and always its
  menu entry, Escape clears it, and following a link or comment jump to a filtered-out section reveals
  and expands it instead of scrolling to nothing. Filtered sections are hidden with `display:none`
  (comment offsets are unaffected) and are never marked current by the scroll-spy. (CMH-TOC-09)
- The side-navigation scroll-spy now marks the current section's link with
  `aria-current="location"` (kept unique and cleared from the others), so screen readers announce
  the reader's location instead of relying on the visual highlight alone. (CMH-TOC-08)

## [1.79.0] - 2026-07-15

### Changed

- The shipped plugin `README.md` now documents the dual-agent install story (both Claude Code and the
  GitHub Copilot CLI, with the marketplace-add and install commands for each), matching the SKILL.md,
  the marketplace manifests, and the site.

## [1.78.0] - 2026-07-15

### Changed

- Deck presentation chrome is cleaner and stays out of the way. The corner comment-mode toggle now
  hides at every width while the comment side panel is open (its accent colour read poorly over a
  slide, and the panel has its own header controls); hiding the panel brings it back so present mode
  stays reachable. The comments action toolbar (Copy all / Show / ...) no longer appears in a deck at
  all: only the single corner icon and the slide nav bar show. When the panel is hidden in comment
  mode the slide stage spans the full screen width again instead of leaving a reserved black bar.
  (CMH-DECK-15)
- The split-screen slide overview is easier to read and use. Its panel now has a light accent-tinted
  (red-ish) background, the Close button uses the regular accent fill, and the slide count appears
  next to the "Slide overview" title. Clicking the main deck area (outside the panel) closes the
  overview, the grid scrolls reliably when the slides overflow the viewport height, and thumbnails
  force-reveal animated slide content so each one previews the slide's final rendered state.
  (CMH-DECK-16)

## [1.77.0] - 2026-07-15

### Changed

- SKILL.md now states the plugin installs into both Claude Code and the GitHub Copilot CLI and is
  invokable from each agent's CLI and Desktop app, so the dual-agent support is visible in the
  shipped skill doc (its output was always a portable, agent-agnostic HTML file). (CMH-DOC-12)

## [1.76.0] - 2026-07-15

### Changed

- Reworked the showcase deck (`examples/deck-showcase.html`) into a light "Parchment and Amber"
  five-act pitch (pinned `data-theme="light"`, raspberry accent, amber decorative highlight on key
  title words, indigo ink body) that threads a single community-garden plan as its one running
  example instead of unrelated feature samples. Acts 1 to 3 speak to a non-technical viewer and end
  on the primary call to action, Act 4 is the engineers-only deep dive (chart, diff, code, KQL,
  triage board, checklist), and Act 5 is a room-wide close. Retitled the slides to outcome-focused
  headings and rebuilt the shipped and site copies. (CMH-DECK-SHOWCASE-01, CMH-DECK-SHOWCASE-02)
- Rethemed the deck's rich content for the light parchment slides: the chart, Mermaid diagram, code
  diff, syntax-highlighted code and KQL, drag-and-drop triage board, table headers, and layered
  checklist all stay legible and pass the strict contrast validator on the new theme.
  (CMH-DECK-08, CMH-DECK-09, CMH-DECK-10, CMH-DECK-13)

### Added

- Early install call to action: the deck now surfaces both agents' exact install commands (Copilot
  and Claude `plugin marketplace add` plus `plugin install commentable-html@urikan-ai-marketplace`)
  as code blocks on an Act 2 slide well before the close, alongside the live-demo, GitHub, and
  tutorial links, and again as the primary CTA and the closing slide - so a viewer can act within
  the first few minutes rather than only at the end. (CMH-DECK-SHOWCASE-03)

## [1.75.0] - 2026-07-15

### Added

- Section-card auto-wrap for report/plan documents - the deterministic fix for the CMH-VAL-14
  flat-section warning. `tools/authoring/wrap_sections.py` wraps each bare top-level `<h2>` block
  (the heading plus the siblings up to the next top-level `<h2>`) in
  `<section aria-labelledby="the-h2-id">` so a `report`/`plan` renders as boxed section cards
  (`#commentRoot > section`), leaving the title/lede above the cards. It is idempotent, a no-op when
  a top-level `<section>` already exists, and scopes to the `#commentRoot` element for a full
  document or the fragment root for a bare fragment. `new_document.py` (report/plan fragments) and
  `finalize.py` (full docs, gated on the kind meta) run it by default; opt out with
  `--no-wrap-sections`. (CMH-TOOL-17)

### Fixed

- `build.py` now re-stamps the version into the Claude Code manifests (`.claude-plugin/plugin.json`
  and `.claude-plugin/marketplace.json`) alongside the Copilot ones, so a version bump no longer
  leaves the Claude mirror behind (which previously required a manual bump and could fail the
  claude-manifest / version-bump guards). (CMH-TOOL-06)

## [1.74.0] - 2026-07-15

### Added

- Validator warning (non-fatal) when a report/plan/generic document has two or more top-level
  `<h2>` headings with no `<section>` wrapper, so authors restore the boxed section-card
  layout (`#commentRoot > section`). Sectioned content, single-heading docs, and slides/boards
  do not warn. (CMH-VAL-14)

## [1.73.0] - 2026-07-15

### Changed

- Deck authoring: the SKILL.md deck section now routes deck planning (not only the fill step) to
  the vendored frontend-slides design system - shortlist templates from `selection-index.json` and
  read `STYLE_PRESETS.md` / `html-template.md` / `animation-patterns.md` to choose the outline
  and theme before scaffolding. (CMH-DECK-14)

## [1.72.0] - 2026-07-15

### Added

- Claude Code compatibility. The plugin now ships a `.claude-plugin/plugin.json` alongside the
  Copilot `plugin.json`, and the repo publishes a `.claude-plugin/marketplace.json`, so
  commentable-html installs in Claude Code (`claude plugin marketplace add ...` then
  `claude plugin install commentable-html@urikan-ai-marketplace`) as well as the GitHub Copilot
  CLI. A new `scripts/validate_claude_compat.py` validates the Claude manifests structurally and,
  when the `claude` CLI is on PATH, runs `claude plugin validate --strict` on the marketplace and
  each plugin. (CMH-CLAUDE-01)

## [1.71.0] - 2026-07-15

### Changed

- Pitch: the plugin `README.md` and the site plugin page now surface two value props of the existing
  review flow. First, comments persist in the browser's `localStorage` and survive a browser restart
  or a machine reboot while you iterate, so in-progress review work is not lost (a new "Comments
  survive a restart" card in "What you get"). Second, one `Copy all` returns every comment at once,
  so the agent makes a single coordinated, coherent edit across all your notes instead of a fragile
  one-at-a-time pass (the README `Copy all` bullet and the site "Round-trip to the agent" card now
  say so). No runtime behavior changed; this is documentation and pitch copy for behavior that
  already ships.

## [1.70.0] - 2026-07-15

### Added

- A visible, human-readable version line in the shipped `SKILL.md` and `dist/README.md`, so a reader
  who opens the skill or its `dist/` folder can see which version they have without decoding
  `manifest.json`. The line (`**Version:** ` + a code span) is single-sourced from `dev/VERSION`:
  `build.py` re-stamps it and `--check` fails when either file is stale.

## [1.66.0] - 2026-07-15

### Added

- Provenance stamps and a runtime fallback banner so a document that skipped validation is visible.
  The document-producing tools stamp `commentable-html-created`, and `validate.py` / `finalize.py`
  stamp `commentable-html-validated` only on a strict-clean pass (`--no-stamp` keeps a run read-only).
  On load, the runtime shows a small dismissible amber banner when a document carries a created stamp
  but no current validated stamp - a produced-but-never-strict-validated document. A strict-validated
  document (and any document with no created stamp) shows nothing. This is a last-resort signal; the
  skill MUST always finalize and strict-validate before handoff.

## [1.65.0] - 2026-07-15

### Added

- Editable notes fields: an authored `data-cmh-note` element becomes an editable plain-text
  `<textarea>` (with a single/multi-line toggle) whose baseline is its authored text. A reviewer's
  edit is tracked as a minimal `localStorage` delta, surfaces as a per-note change card (jump +
  reset, searchable), flips the badge to Not portable, is written into the Copy-all bundle as
  `NOTES_STATE_JSON`, and is baked into the source on export. `tools/notes/notes_scaffold.py`
  generates the markup and `tools/notes/notes_apply.py` deterministically cements an edit back into
  the source HTML, so the reviewer-edit round-trip is closed and covered end to end. The global
  Clear all comments also reverts note edits. Ships a `report-notes.html` demo. See the editable
  notes-field contract reference (`references/notes-contract.md`) in the skill. Notes can be marked
  foldable (`data-cmh-note-foldable`) to render as a `+`/`-` disclosure that reveals the field on the
  line below.

## [1.64.0] - 2026-07-15

### Changed

- KQL code blocks must now be runnable or explicitly marked clusterless. A bare
  `<pre><code class="language-kusto">` block that is not framed in a `figure.cmh-kql` with a
  Run in Azure Data Explorer link is now a hard validation error unless the `<pre>` carries an
  explicit `data-cmh-kql-no-cluster` marker (declaring there is genuinely no cluster to run it on).
  Previously a bare KQL block was silently exempt, so a query could ship with no way to run it and
  no cluster. Prefer providing a real cluster; `kql_highlight.py --code-only` now stamps the
  `data-cmh-kql-no-cluster` marker for the rare clusterless case.
- The showcase deck's KQL slide now uses a full runnable figure on the public
  `help.kusto.windows.net` cluster instead of a bare highlighted block.

## [1.63.0] - 2026-07-15

### Changed

- The document-producing tools now bake syntax highlighting by default and surface validator
  warnings instead of discarding them, so a freshly created document is never raw. Previously baking
  lived only in the separate, manual `finalize.py` step, so a document that skipped finalize shipped
  with monochrome code. `new_document.py`, `retrofit.py`, and `deck_scaffold.py` all bake highlighting
  by default (opt out with `--no-highlight`); `new_document.py` and `deck_scaffold.py` print validator
  warnings, and `retrofit.py` continues to fail closed on any warning so it never writes a raw document.
- `SKILL.md` now states as a MUST that every produced HTML is finalized and strict-validated before
  handoff, since the runtime and validator both depend on that final pass.

## [1.62.0] - 2026-07-15

### Fixed

- Raw `language-html` and `language-xml` code blocks that shipped without baked highlighting now
  self-highlight at runtime like every other supported language. The runtime fallback tokenizer only
  fired for languages it knew, and the markup family (html/xml) was missing from that set, so an
  unbaked markup block rendered as plain monochrome text (css/js blocks already self-healed). The
  runtime now colors tag names, attribute-value strings, and `<!-- -->` comments for markup.

### Added

- A drift guard test asserts the runtime tokenizer knows every language the author-time highlighter
  supports, so a supported language can never again ship without runtime highlighting.

## [1.61.0] - 2026-07-15

### Changed

- The comments panel can no longer be dragged so narrow that its controls clip. The resize floor
  is now 256px (was 192px on wide screens and 144px on narrow), the empirically measured minimum at
  which the two-per-row export button labels (`Portable`, `Offline`, `Markdown`, `Plain HTML`) and
  the `Search comments` placeholder stay fully legible; the CSS `min-width` floor matches so the pane
  never renders narrower.
- Widened the comment search field by trimming its side padding and the shown/total count reserve, so
  the full `Search comments` placeholder fits even at the minimum panel width.

## [1.60.0] - 2026-07-15

### Fixed

- Validator now warns when normal `<pre>` or `<pre><code>` blocks carry `cm-skip`, which would make their code content non-commentable.
- Validator now rejects a live `#commentRoot` that still uses the documentation example key `my-doc`, while allowing the commented-out example.

## [1.59.0] - 2026-07-15

### Changed

- Reduced the always-loaded `SKILL.md` token footprint by replacing reference-duplicated guidance with concise pointers to the existing on-demand reference docs while keeping routing, validation, trust-boundary, iteration-loop, and deck invariants in the entry point.

## [1.58.0] - 2026-07-15

### Added

- Replaced the weak roadmap deck demo with a themed, in-depth Commentable HTML showcase deck and a reusable one-shot authoring prompt that prescribes the full slide outline and feature coverage.
- Added the showcase deck to the live site demo tabs so visitors can open the deck-mode review experience directly.

### Fixed

- Deck code, KQL, and diff blocks now use dark, readable surfaces, distinct syntax token colors, and readable add/delete row tints on dark deck slides.

## [1.57.0] - 2026-07-15

### Added

- Added a shipped `tools/validate/cmhval/contrast.py` WCAG contrast helper and wired
  `deck_validate.py` to fail decks whose explicit inline or same-rule CSS text/background color
  pairs fall below the configurable 4.5:1 default threshold, with diagnostics that name the
  selector or element and both colors.

### Fixed

- Hardened the contrast helper so malformed or non-finite `rgb()`/`rgba()` values are skipped
  instead of crashing, semi-transparent backgrounds are skipped, background shorthand follows
  declaration order, and colors embedded only inside `url(...)` or quoted strings do not create
  false positives.

## [1.56.0] - 2026-07-14

### Added

- Added a deck slide-overview navigator with a split-screen thumbnail grid, slide-title tooltips, click-to-jump navigation, and keyboard open, close, and select support in present and comment modes.
- Replaced the deck comment-mode text toggle with the commentable-html brand icon while preserving the Comment Mode tooltip, accessible name, and aria-pressed toggle behavior.
- Hardened the overview so thumbnail clones stay out of the tab order, preserve nested highlight markup, do not receive background deck navigation keys, and are stripped from offline exports.

## [1.55.0] - 2026-07-14

### Added

- Added the Commentable HTML brand icon to the toolbar overflow menu header as a decorative
  top-right mark that does not change the menu's keyboard order.
- Added a Help and About changelog link to the commentable-html plugin changelog.

### Changed

- Copy all now exposes a disabled, tooltip-backed state when there is no copyable review state, and
  re-enables automatically once comments are available.
- Clear now restores checklist state edits and draggable board moves to their authored baselines in
  addition to deleting comments.
- The Help and About author link now has a visible underline and accent color so it reads as a link.

## [1.54.0] - 2026-07-14

### Fixed

- Deck roadmap risk board cards can be dragged between columns inside the scaled deck stage.
- Mermaid diagrams on dark deck slides now render with high-contrast nodes, labels, and connectors.
- Deck table headers now keep readable label contrast on dark slides.

## [1.53.0] - 2026-07-14

### Changed

- Split the 1,959-line `tools/validate/validate.py` into focused, single-purpose modules under a new
  `tools/validate/checks/` package (`parsing`, `resources`, `kind`, `charts`, `checklist`,
  `highlighting`, `layer`), leaving `validate.py` as a thin entry point and orchestrator that
  re-exports each module's public names. The content-syntax checks continue to live in the sibling
  `cmhval/` package. This is a pure internal refactor with no behavior change: every existing test
  passes unchanged and the validator's output on every shipped example and template is identical.
- Decomposed the ~460-line `check_layer` into a 94-line orchestrator plus focused per-check helpers
  (region markers, content root, state JSON blocks, element ids, self-contained resources, KQL, diff
  blocks, headings, and more), so each layer invariant is its own small, testable function.

### Development

- Added CLI tests for `validate.py`'s `-h`/`--help` output and the `--` end-of-options separator
  (`ValidateMainTests`), and refreshed the `CMH-VAL-11` / `CMH-CONTENT-16` spec source pointers to the
  new module paths.


## [1.52.0] - 2026-07-14

### Changed

- Comment search now filters by the comment note text only. A query that appears solely in the
  quoted anchor content (or the section path / pin) no longer keeps a card visible, so reviewers
  filter by what they wrote rather than by the surrounding quote. A query present in the note still
  matches, and the case-insensitive substring, shown/total count, clear button, and no-results
  behaviors are unchanged.

## [1.51.0] - 2026-07-14

### Changed

- Grouped the shipped runtime tools into per-topic buckets under `tools/<topic>/` (`deck`, `kusto`,
  `checklist`, `blocks`, `authoring`, `validate`), moving the former top-level `deck/` under
  `tools/deck/`. A shared `tools/_toolpath.py` bootstrap puts the tools root and every topic
  subdirectory on `sys.path` and exposes `SKILL_ROOT`, so a tool imports its siblings and resolves
  shipped resources (`dist/`, `vendor/`) regardless of which bucket it lives in. Invocation paths in
  `SKILL.md` and the references move to `tools/<topic>/<tool>.py`; there is no runtime behavior change.

## [1.50.0] - 2026-07-14

### Added

- Content-syntax validation in `tools/validate.py`, so a document with a broken mermaid diagram
  or invalid embedded JSON now FAILS validation instead of shipping and rendering as mermaid's
  "Syntax error in text" bomb:
  - Mermaid: a `sequenceDiagram` message that a `;` splits into a dangling statement (the text
    after the `;` carries a message arrow but no `:` message) is an error. The check is calibrated
    to zero false positives against a broad, real-parser-labeled corpus - a valid multi-signal
    (`A->>B: x; C->>D: y`), an arrow inside message text, a `participant ... as "a->b"` alias, an
    `accTitle:`/`accDescr:` directive, and an inline `%%{init}%%` directive or a `%%`, single `%`,
    or `#` comment are never flagged (all confirmed against the real mermaid v11 parser). Only
    `sequenceDiagram` is deep-checked in Python; every other diagram family (flowchart, class,
    state, ...) is delegated to the repo-side real-parser oracle, so a flowchart label with a `%%`
    or a literal quote is never a false positive. An empty mermaid block (which renders as
    mermaid's "No diagram type detected" error) is also flagged.
  - Embedded JSON: an empty or invalid `<script type="application/json">` data block (whose
    `JSON.parse()` would throw at runtime, including a `NaN`/`Infinity` literal or a raw
    `</script>` that truncates the block) is an error when no chart canvas owns it; the chart
    checks continue to own chart-data JSON when a canvas is present.
- The new checks live in a `tools/cmhval/` package (`mermaid.py`, `jsonblocks.py`) so the
  validator does not grow into one giant script; `tools/validate.py` stays the entry point.

### Development

- A repo-side real-parser oracle (`dev/tools/validate_render.mjs`, never shipped) validates every
  mermaid diagram and Chart.js config in the shipped example reports with the real mermaid and
  Chart.js in a headless browser, and re-verifies the differential corpus labels, so the repo
  cannot ship a diagram or chart that renders as a syntax-error bomb and the Python checker's
  zero-false-positive guarantee is gated by the authoritative parser in CI. The oracle also flags
  an empty/whitespace-only `<pre class="mermaid">` host (which the real parser rejects as "No
  diagram type detected") rather than silently skipping it.
- If the sibling `tools/cmhval/` package cannot be imported (a broken/partial install),
  `tools/validate.py` now fails CLOSED for content it would have inspected - a mermaid block or a
  non-layer JSON data block makes validation error instead of silently passing - while a document
  with no such content still validates and `--charts-only` is unaffected.

## [1.49.0] - 2026-07-14

### Changed

- Consolidated the skill's docs assets: the review-loop diagram and the tutorial screenshots now
  live together under `docs/assets/` (previously split across `docs/images/` and
  `docs/tutorial-images/`). Shipped references in `SKILL.md`, `README.md`, `TUTORIAL.md`, and the
  file inventory point at the new location; there is no runtime behavior change.

## [1.48.0] - 2026-07-14

### Added

- Prevent code blocks from shipping without syntax highlighting, in three layers:
  - Runtime fallback: the runtime now highlights any commentable `<pre><code class="language-XXX">`
    block that shipped without highlight spans, on load, so a labelled block never renders as plain
    monochrome text even when highlighting was never baked. It is idempotent, only fires for a
    language the tokenizer knows, and keeps line numbers and comment anchoring consistent.
  - `tools/highlight_document.py`: bakes highlighting into every raw, language-labelled code block
    of a file in one pass (with a `--check` mode). `tools/finalize.py` runs it by default (opt out
    with `--no-highlight`), so the standard finalization bakes highlighting.

## [1.47.0] - 2026-07-14

### Added

- The validator now catches a code block that was labelled with a language but never highlighted.
  `tools/validate.py` warns when a `<pre><code class="language-XXX">` block declares a language the
  author-time highlighter supports (resolving aliases like `cs` to `csharp`) but carries no
  `cmh-code-*` spans, so it renders as plain monochrome text. Inline code, non-highlightable labels
  (`language-text`, `language-kusto`), and already-highlighted blocks are not flagged.

### Fixed

- The showcase demo's Python code block is now syntax-highlighted (it previously shipped as a plain
  `language-python` block, which the new validator check flags).

## [1.46.0] - 2026-07-14

### Added

- Search within comments. The comments panel now has a single search field (with a leading
  magnifier and a clear X button) that filters the comment cards to only those whose text - the
  note, the quoted content, the section path, and the pin - matches the query case-insensitively.
  A shown/total count sits beside the field, a no-results note appears when nothing matches, and
  the filter re-applies after every render so it survives adding, editing, or sorting comments.

## [1.45.0] - 2026-07-14

### Changed

- The comments panel resizes narrower. The drag/keyboard minimum width dropped to 3/5 of the former
  floor - 192px on wide screens (was 320px) and 144px on narrow screens under 700px (was 240px) - so
  the panel can take less horizontal space and leave more room for the document. The panel's CSS
  `min-width` floor was lowered to match, and the width still clamps to the viewport and persists
  across reloads.

## [1.44.0] - 2026-07-14

### Added

- Layered checklists. A `data-cmh-checklist` container turns a nested list (or a table) into
  interactive four-state item checkboxes (blank / check / cross / question) drawn with inline-SVG
  icons. A branch item aggregates over its direct children (all-same shows that state, any
  disagreement shows a neutral mixed marker), and clicking a branch propagates its next state to
  every descendant leaf. Item labels stay ordinary commentable content; only the injected icon
  control is `cm-skip`. Hierarchy comes from DOM nesting for lists, or an explicit `data-cmh-parent`
  reference for tables, which cannot nest rows and may be sorted.
- Minimal checklist persistence. Only leaves whose state differs from their authored `data-cmh-state`
  baseline are stored, as one-character codes under `COMMENT_KEY + "::cl"`; returning a leaf to its
  baseline prunes its entry, so a large checklist with a few edits costs a few bytes.
- Per-list checklist change card. The sidebar renders one non-comment card per checklist with
  changes, placed by document order, with a jump button and a Reset button that reverts that
  checklist to its authored state. Copy all gains a `## Checklist "<id>"` section plus a
  machine-readable `CHECKLIST_STATE_JSON` line, an unsaved change flips the badge to Not portable,
  and every export bakes the current states into `data-cmh-state`. A checklist that loads with a
  persisted change opens the sidebar so the card is seen.
- Two checklist tools. `tools/checklist_scaffold.py` generates list or table markup with stable ids
  from an indented outline, and `tools/checklist_apply.py` cements the reviewer's states from a
  Copy-all bundle (or `--state-json`) back into the source HTML. `validate.py` gains checklist checks
  (duplicate ids, invalid tokens, empty lists, unresolved parents) that a checklist-free document
  ignores. See the bundled `references/checklist-contract.md` for the authoring contract.
- A shipped demo report `examples/report-checklist.html` (Release readiness review) that showcases both
  checklist shapes - a nested-list sign-off checklist and a sortable-table component audit linked by
  `data-cmh-parent` - with its companion authoring prompt `examples/prompt-checklist.md`.

## [1.43.0] - 2026-07-14

### Changed

- Clarify the README privacy wording: the document and comments are "never uploaded, transmitted, or
  sent to any external service - not to us, and not to anyone else", dropping the confusing "not to
  the agent" (you do paste the Copy all bundle to your agent yourself, so listing the agent among the
  never-sent destinations read as contradictory).

## [1.40.0] - 2026-07-14

### Added

- A "Privacy and compliance" section in the packaged README and a "Private by design" section on
  the plugin site page (linked from the nav), emphasizing that the document and every comment stay
  local - in the browser's `localStorage` or embedded in your own HTML file - are never uploaded or
  sent to any external service, and that only the Mermaid/Chart.js rendering libraries load from a
  CDN (not your data) while Export Offline strips even that for air-gapped, sensitive, or regulated
  use.

## [1.39.0] - 2026-07-14

### Changed

- The Help & About panel now links the author's name, "Uri Kanonov", to
  `https://github.com/urikanonov` (opens in a new tab), reusing the existing brand-link style.
- Help panel text now names the triage board's `Reset moves` button and the board-moves comment
  card's `Reset changes` button, and refers to the Help toggle by its exact on-screen label,
  `Help & About`, instead of the shorthand `Help`.

## [1.38.0] - 2026-07-14

### Added

- A shipped example deck `examples/deck-roadmap.html` (Autumn Roadmap Review) plus its companion
  authoring prompt `examples/prompt-roadmap.md`. The deck is a `kind=slides` document with a
  fixed 1920x1080 stage of six commentable slides (title, current-state stats, themes table,
  mermaid architecture diagram, three-column risk board, and the ask), giving reviewers a real
  deck target for the same commenting workflow the report demos exercise.
- `build.py`'s example pipeline now covers `deck-*.html` sources alongside `report-*.html`, so a
  deck source in `dev/examples-src/` regenerates its shipped copy under `pkg/**/examples/` and
  `build.py --check` catches a hand-edit or a stale/clobbered deck example. The site demos list
  syncs the deck under `site/commentable-html/demo/` next to the report demos.

## [1.37.0] - 2026-07-14

### Fixed

- The diff-line Add Comment hover button (`#diffAddBtn`) is now vertically centered on the hovered
  row, so moving the pointer to click no longer jumps to the line above.

### Added

- Commentable code blocks, including KQL query blocks, now show per-line numbers in a
  `.cmh-code-gutter` overlay via CSS-generated counters. The numbers are visible in the UI but
  excluded from text selection and clipboard output, including each block's Copy button.

## [1.36.0] - 2026-07-14

### Added

- The `cmh` shorthand now discovers the skill: it is a `plugin.json` and marketplace keyword, and
  the `SKILL.md` front-matter discovery description ends with an explicit `Also triggers on the
  shorthand cmh.` clause, so typing `cmh` auto-triggers the skill and matches it in marketplace
  search.

## [1.35.0] - 2026-07-14

### Added

- Triage-board (and any `[data-cm-widget][data-cm-draggable]` widget) Reset controls. A moved board
  now grows a runtime-injected "Reset moves" button in its corner whenever its layout differs from
  the load-time baseline; clicking it returns every card to its original slot and order, and the
  button disappears once there are no moves. Static (non-draggable) widgets never get the button.
- Per-widget layout-change state cards. The sidebar now renders one "Layout change" card per widget
  that has moves, each with a jump button that scrolls to and flashes that board and a "Reset
  changes" button that restores only that widget. Each card mirrors a regular comment card's shape:
  an `in: <board>` title (the widget aria-label, else its name) and a meta line showing the
  first-change datetime, alongside the existing explanatory note.

### Fixed

- A chart caption sitting directly below a tall `cm-skip` chart is now commentable. The desktop
  `mouseup` handler evaluates the selection before bailing on a `cm-skip` target, so selecting a
  short caption still offers Add Comment even when the pointer releases over the adjacent chart
  canvas.
- The runtime footer no longer spans wider than the content column. Its box now aligns to the
  `#commentRoot` content width in both the normal and the sidebar-open layout.

## [1.34.0] - 2026-07-13

### Changed

- The shipped example reports (`examples/report-*.html`) are now pure build artifacts assembled
  from an independent content source in `dev/examples-src/`. `build.py --check` compares each
  shipped example to a fresh assembly, so a hand-edit or a stale/clobbered example - of its content
  as well as its layer - now fails the build instead of comparing equal to itself. Edit demo content
  in `dev/examples-src/`, not in the shipped file.

### Accessibility

- The comments-panel toggle and the overflow-menu trigger now declare the element they control with
  `aria-controls` (`#sidebar` and `#toolbarMenu`), so assistive technology can associate each toggle
  with its target.

## [1.33.0] - 2026-07-13

### Fixed

- Export as Portable no longer corrupts a comment whose body contains `$&`, `$1`, `` $` ``, `$'`, or
  `$$`: the saved-HTML builder now uses a function replacer so `String.replace` cannot expand those
  `$`-patterns from the comment text.
- Export as Plain now recognizes region markers with any number of `=` fill characters (matching the
  validator's grammar) when stripping the comment-UI, embedded-comments, and script regions, and the
  post-export leak guard now matches `id="handledCommentIds"` / `id="embeddedComments"` regardless of
  quote style, so a Plain export cannot silently ship comment data.
- The strict validator now rejects a report whose top-level lede exists but is empty: a document must
  carry a non-empty top-level `<h1>` title, not just the lede wrapper class.

### Added

- The plugin site page now showcases the commentable-decks capability in the "What you get" section.

### Changed

- The deck authoring guide runs the deck validator with `--strict`, and the tutorial's Show/Hide
  wording matches the actual toolbar behavior.

## [1.32.0] - 2026-07-13

### Added

- Commentable decks: a built-in deck capability powered by a curated, pristine subset of the frontend-slides skill (MIT, (c) 2025 Zara Zhang) vendored under `vendor/frontend-slides/`. The Vercel deploy script and the PDF-export script are excluded, and a required CI gate (`dev/tools/check_vendor.py` plus a SHA-256 `MANIFEST.sha256`) fails on any unknown, changed, removed, or reintroduced file. See `vendor/frontend-slides/UPSTREAM.md` and `dev/frontend-slides-upstream-sync.md`.
- Author-time deck tools under `deck/`: `deck_scaffold.py` builds a create-only, commentable-native fixed-stage deck with legible presentation defaults (light slide text and presentation-scale typography on the dark stage, overridable by a design pass) - each slide carries a stable `data-slide-id`, the inline editor and localStorage autosave are stripped, and fonts are self-hosted - and fails closed on the deck contract before writing; `pptx_to_fragment.py` HTML-escapes extracted slide text, schema-validates the input, vets every image path as local-relative, and fails closed without `python-pptx` (speaker notes are not supported); `deck_validate.py` enforces the deck contract fail-closed using an HTML parser (robust to solidus, entity-encoded, unquoted, and SVG bypasses), rejecting remote fonts/media/CSS, active content, and `javascript:`/`../` URLs while allowing external hyperlinks. The runtime interface both sides build against is documented in `references/deck-contract.md`.
- A "Deck capability (frontend-slides)" flow in `SKILL.md`: detect a presentation request and confirm, optionally convert a `.pptx` (preferring the Anthropic `pptx` skill when installed, else the local extractor), scaffold, fill, validate, then comment on the live deck and iterate in place. Mermaid and Chart are supported; Export Offline produces the network-silent shareable artifact.
- A runtime deck profile in the commentable-html layer, activated only by `data-cmh-mode="deck"` on the real content root: it exposes a `window.__cmhDeck` controller, scales the fixed 1920x1080 stage (refit via a `ResizeObserver`), and replaces the flow-document chrome (heading anchors, collapsible carets, side TOC, footer, scroll progress) with a full-screen presentation - a **present mode** that hides the comment sidebar/toolbar plus a slide-oriented control bar (Prev, a live `N / total` slide counter, Next, with WCAG-2.5.3 aria-labels and boundary-disabled buttons) and keyboard / id navigation (guarded against out-of-range and editable-target keypresses). A **comment mode** toggle reveals the sidebar, insets and force-reveals the stage, and gates the navigation keys; a comment card jumps to (activates) its owning slide with highlights restoring on hidden slides. Non-deck documents are unaffected.
- Dev tooling: `dev/tools/audit.mjs`, an AI-driven UX audit harness that tours any commentable HTML across viewports and colour schemes and emits screenshots plus machine observations for one or many agents to review (see `dev/AUDIT.md`). Not shipped.

### Changed

- The mermaid CDN import is now gated on the presence of a `pre.mermaid` / `div.mermaid` element, so a diagram-free document (including a deck) makes no external network request at all. A document that contains a diagram still loads and renders mermaid.

## [1.31.0] - 2026-07-13

### Changed

- In the sidebar's narrow layout the export buttons now pack two per row (Portable | Offline, then Markdown | Plain HTML) instead of one full-width button per row, so the actions take less vertical space and are quicker to scan. The Clear button keeps its own full-width row so the destructive action stays visually apart.

## [1.30.0] - 2026-07-13

### Fixed

- Hardening pass from a multi-model audit of the day's merged changes. Six latent robustness and correctness defects are fixed, each covered by a test that reproduces the defect before the fix. No shipped example, template, or fixture changed behavior; they all still validate clean.
- `tools/validate.py` KQL run-link rule (`CMH-KQL-07`) now treats a framed `figure.cmh-kql` whose `cmh-kql-run` link points anywhere other than `https://dataexplorer.azure.com/` as a hard error instead of a warning. The href is HTML-entity decoded and URL-parsed (not substring-matched), so a `javascript:`, `data:`, non-ADX, or look-alike-host link fails validation. The "has a run link" check now looks for a real `<a>` element carrying the `cmh-kql-run` class token, so a figure whose query text merely mentions `cmh-kql-run` no longer passes as if it had a link. A bare `<pre>` KQL block stays exempt.
- `tools/validate.py` transient-body-class guard (`CMH-VAL-10`) now inspects the REAL parsed `<body>` element instead of the first raw `<body ...>` token in the file, so a decoy `<body class="sidebar-open">` inside a `<head>` script or comment can no longer hide a dirty real body or trigger a false positive.
- `tools/validate.py` report/plan title rule (`CMH-KIND-01`) now requires a TOP-LEVEL `<h1>` (a direct child of `#commentRoot`, or a lede-wrapped `<header class="cmh-lede"><h1>`), matching `new_document.py`. An `<h1>` nested only inside a deeper `<section>` no longer satisfies the rule.
- `assets/commentable-html.js` document-comment context menu (`CMH-DOCCMT-02`) no longer vanishes on a macOS-style Ctrl-click: the `mouseup` cleanup is suppressed for any context-menu gesture (`button === 2 || ctrlKey`), not right-click alone.
- `assets/commentable-html.js` export body-class normalizer (`CMH-EXP-09`) now operates only on the first `<body>` open tag, handles double-quoted, single-quoted, and unquoted class values, matches whole class tokens (a superstring like `x-sidebar-open` is preserved), and removes an emptied class attribute, so it can no longer mutate a `<body class=...>` literal that appears later in page content or a script.
- `tools/upgrade.py` and `tools/retrofit.py` kind-meta handling (`CMH-KIND-02`, `CMH-KIND-03`) now detect an existing `commentable-html-kind` meta by parsing head metadata order-independently (including a non-canonical `content`/`name` attribute order). `upgrade.py` no longer appends a duplicate meta to a document that already declares a kind, and `retrofit.py --kind` replaces an existing kind meta in place instead of appending a second one.

### Changed

- `references/validation.md` error list now documents the mandatory/unknown `commentable-html-kind` meta (with the report/plan top-level `<h1>` sub-rule) and the transient body-state class guard, matching the authoritative error list `SKILL.md` points to.

## [1.29.0] - 2026-07-13

### Fixed

- The template and shipped example reports no longer bake the transient runtime `sidebar-open` body class into `<body>`. `sidebar-open` is a UI-state class the layer toggles on `document.body` as the panel opens and closes; hardcoding it in `assets/template.shell.html` meant every generated document, both `dist/` templates, and all four `examples/report-*.html` shipped with `<body class="sidebar-open">`, which rendered a fresh document full width with an empty reserved right gutter (the `body.sidebar-open .app` layout rule) even when the sidebar panel is not shown. The template and examples now ship a plain `<body>`, and the runtime derives the sidebar state on load (open when the document has restored comments, closed otherwise). Where 1.28.0 stripped the class on export, this removes it at the source.

### Added

- `tools/validate.py` now errors when a document's `<body>` open tag carries a transient runtime UI-state class (`sidebar-open`, `cm-sidebar-resizing`, or `cm-widget-dragging`), so a persisted transient state can never ship. The check inspects only the `<body>` open tag, so a legitimate CSS/JS reference to `sidebar-open` is not flagged. New specs `CMH-BUILD-06` (no shipped document bakes the class) and `CMH-VAL-10` (the validator guard), covered by `dev/tests/test_build.py`, `dev/tests/test_new_document.py`, `dev/tests/test_examples.py`, and `dev/tests/test_validate.py`.

## [1.28.0] - 2026-07-13

### Fixed

- Exports no longer bake transient runtime body-state classes into the saved file. Every export path (Save, Export as Portable, Export Offline, and Export to Plain HTML) now strips `sidebar-open`, `cm-sidebar-resizing`, and `cm-widget-dragging` from the exported `<body>` open tag, so a stale or open-sidebar source can no longer persist that state and propagate it across re-exports. A stuck `sidebar-open` made the document render full width with an empty right gutter (the `body.sidebar-open .app` layout rule) for a sidebar that is not shown. Non-transient body classes are preserved, and the live layer re-derives the sidebar state on load. The normalization is centralized in `_getBaseHtml()` (covering the on-disk and `file://` snapshot bases) and shared with the Plain export via a new `_stripTransientBodyClasses()` helper. New spec `CMH-EXP-09` and `dev/tests/54-export-body-normalize.spec.js` cover all four export paths.

## [1.27.0] - 2026-07-13

### Added

- Every shipped example report now has a companion example-prompt file. Added `examples/prompt-triage.md` and `examples/prompt-metrics.md` (matching the existing `prompt-community-garden.md` and `prompt-taxi.md` format) so all four examples document the one-paragraph prompt that generates them.
- Full interaction coverage for the incident triage board and commentable visuals matrix examples: a new `dev/tests/53-more-examples.spec.js` exercises both reports over http with prose commenting, widget/part commenting, UI-control clicks, and a seeded randomized monkey pass, asserting no uncaught page errors and comment persistence across reload. Each of the four shipped examples is now covered by validation, monkey, commenting, and clicking.
- New spec guards: `CMH-DEMO-02` (every report has a companion prompt with the standard headings and a non-empty blockquote) and `CMH-DEMO-03` (each example is exercised by the interaction/monkey suite), plus an example-scoped assertion under `CMH-BUILD-05` that no shipped example carries the removed "TEMPLATE / DEMO" header phrases.

## [1.26.0] - 2026-07-13

### Changed

- The "Run in Azure Data Explorer" deep link is now mandatory on a framed KQL figure. `tools/validate.py` rejects a `figure.cmh-kql` that has no `cmh-kql-run` link as a hard error (non-zero exit in the default, non-strict mode) instead of a warning, so a framed KQL block can never ship without the reader's one-click path into Azure Data Explorer. Build the link with `tools/kusto_link.py`. A purely illustrative query with no real cluster/database should use a plain `<pre>` code block, which remains exempt from the rule.

## [1.25.0] - 2026-07-13

### Changed

- Generated documents no longer carry the leading "Commentable HTML - TEMPLATE / DEMO" documentation comment. That guidance duplicated the skill references and mislabeled real reports as a template or demo, so every shipped report and generated document is now leaner and cleaner without it.

## [1.24.0] - 2026-07-13

### Changed

- Aligned the skill with Anthropic's Agent Skills authoring guidelines (documentation only, no runtime or tool behavior change). Rewrote the `SKILL.md` front-matter description into a what-plus-when discovery string with an explicit `Use when ...` trigger clause scoped to HTML artifacts, linked `references/forward-compatible-layout.md` directly from `SKILL.md` so every reference is one level deep, added a `## Contents` table of contents to each reference longer than 100 lines (charts, exports, document-layout, comment-data-shape, retrofitting), documented the Markdown-to-HTML reviewer path, removed legacy UI-label and past-version wording from the Charts and Exports references, and removed a time-relative phrase from the Interaction-model reference. The repository `README.md` plugin row was aligned with the new description.
- Added spec-covered guards for the above (`CMH-DOC-05` reference tables of contents, `CMH-DOC-06` front-matter description, `CMH-DOC-07` direct reference links, `CMH-DOC-08` SKILL/marketplace description consistency), each validated by a covering test in `dev/tests/test_docs_diagrams.py`.
- Deferred: trimming the `SKILL.md` body toward Anthropic's ~5k-token soft cap is intentionally left to a focused follow-up, because the body carries pinned generation contracts (`CMH-DOC-02`/`CMH-DOC-03`) that a de-duplication pass should not churn in the same change.

## [1.23.0] - 2026-07-13

### Fixed

- A real desktop right-click on empty document space no longer flashes the document-comment menu open and then hides it: the right-button `mouseup` no longer runs the text-selection cleanup that queued a `hideMenu()` clobbering the just-opened menu.

### Changed

- The sidebar Copy all button is larger and bolder so the most-used action is easier to find and click.

## [1.22.0] - 2026-07-13

### Added

- Documents now declare their kind in a mandatory `<meta name="commentable-html-kind">` (report, plan, slides, board, or generic). The validator requires it and enforces per-type rules: report and plan must carry a top-level `<h1>` title, while slides, board, and generic do not.
- `new_document.py` and `retrofit.py` require `--kind` and stamp the meta; report and plan auto-add a title from `--label` when the fragment has none, while slides and board do not.

### Changed

- `upgrade.py` now adds a default `generic` kind meta to a document that predates kinds, so upgrading an older document produces one that still validates.

## [1.21.0] - 2026-07-13

### Added

- Added `tools/retrofit.py` to deterministically inject the commentable layer into existing unlayered HTML with validation-before-write, root selection, Portable output, companion-asset options, and host chrome skip selectors.

### Changed

- Trimmed `SKILL.md` by moving runtime UI, interaction, NonPortable, network, and manual retrofit details into existing references while keeping generation-time routing, caveats, and commands inline.

## [1.20.0] - 2026-07-12

### Fixed

- Offline export now blocks form submissions in CSP, removes remote form targets, keeps benign inline scripts with non-network dynamic import comments, and preserves custom canvas renderers that are not chart snapshots.
- Strict offline validation now requires the restrictive CSP and rejects network form targets, meta refresh redirects, and network CSS `url(...)` values in style blocks or inline styles.
- Offline validation now ignores non-fetching remote links such as canonical and alternate metadata while still blocking fetching link relations.
- Region marker guards in validation, upgrade, build, and runtime export now count only comment-delimited infra markers, so marker text inside prose or code blocks no longer causes duplicate-region failures.

## [1.19.0] - 2026-07-12

### Fixed

- Offline export now adds a zero-network CSP, removes event-handler attributes, strips same-origin absolute media and additional preload/media/SVG/CSS/refresh egress vectors, and validates offline documents with no Chart.js CDN exemption.
- Region replacement tools and runtime export slicers now reject duplicate BEGIN or END markers instead of risking content loss.
- Validator hardening now rejects protocol-relative and non-file companion refs, descriptor id decoys, and commented `data-id="commentRoot"` false positives.
- Save, Portable, and Offline exports now filter handled comments so resolved feedback cannot reappear in exported embedded comment JSON.
- Markdown export now summarizes offline chart snapshots by label instead of embedding base64 chart images.

## [1.18.0] - 2026-07-12

### Added

- Documented widget drag opt-in, the Offline badge state, Export Offline, and when to use NonPortable, Portable, or Offline outputs.

### Fixed

- Exporting after widget moves now refreshes plain-text comment offsets against the exported widget layout, so comments near moved cards reopen on the intended text.
- Floating chart, mermaid, diff, widget, and text-comment bubbles now respect horizontally clipped rich-content containers instead of drifting outside scrolled charts, tables, diagrams, or raw diffs.
- Document-type badges now announce Portable, Offline, and Not portable state changes through a polite live region and expose the reason through `aria-label`.
- The dependency cooldown gate now diffs lockfiles by package name and version, uses lockfile entry names for aliases, discovers package-lock files dynamically, deduplicates registry lookups by package name, applies a global deadline, and warns when changed non-registry dependencies are not cooldown-checked.
- The forward-compatible layout reference now clarifies that `validate.py --strict` validates the current contract only and legacy pre-1.15 documents must be regenerated or upgraded before validation.

## [1.17.0] - 2026-07-12

### Fixed

- Offline export now preserves embedded comment data scripts even when comment text mentions remote imports, strips bare remote module imports, neutralizes remote media attributes, and keeps descriptor decoys from stealing the real offline mode update.
- Widget drag-and-drop now treats drops onto nested slots inside the dragged part as no-ops, always clears drag state, preserves click-to-comment behavior below the drag threshold, avoids reporting origin-slot no-ops as moves, and saves moved widget layouts into Portable exports.
- Example regeneration now rejects duplicate region BEGIN markers instead of silently slicing through authored content.
- The dependency cooldown gate now fails open when npm registry packuments have a null or malformed `time` map.
- The dependency cooldown gate and related test helpers now emit stable sorted failure output.
- The mobile rich-content test now proves genuinely wide chart or mermaid blocks can scroll horizontally instead of relying on tautological scroll metrics.
- Plain export and layer retargeting now ignore `data-id="commentableHtmlLayer"` decoys when locating the real descriptor.

## [1.16.0] - 2026-07-12

### Added

- Offline exports now declare descriptor mode `offline`, reopen with an Offline badge, preserve that mode when
  edited, and validate offline chart snapshots as first-class portable artifacts.
- Triage board cards can opt in to mouse drag-and-drop with `data-cm-draggable`, and moved cards are copied as
  widget layout changes.

### Fixed

- Mermaid diagrams and chart figures now stay inside narrow mobile viewports by scrolling wide rich content inside
  their own blocks.
- Shipped prose now refers to the user-facing skill as Commentable HTML while preserving the `commentable-html`
  identifier in commands, paths, and code.

## [1.15.0] - 2026-07-12

### Added

- Generated documents now publish a machine-readable `commentableHtmlLayer` descriptor that records the
  layer version, output mode, and infra region marker names in document order.
- `#commentRoot` now carries `data-cmh-content-root`, giving future tooling a stable hook for content roots.
- The forward-compatible content/infra layout contract is documented in `references/forward-compatible-layout.md`.

## [1.14.0] - 2026-07-12

### Changed

- Top-level prose is no longer width-capped. Ordinary paragraphs (and the lede) now fill the full
  content column, the same width as tables, figures, code, and callouts, so prose no longer renders
  narrow next to full-width content in wide reports. The previous 72ch readable-measure cap is removed.

## [1.13.0] - 2026-07-12

### Added

- Added two shipped live demo reports: an incident triage board with commentable widget columns and cards, and a
  visuals matrix covering flowchart, sequence, gantt, state, class, ER, and pie mermaid diagrams, four Chart.js
  chart kinds, a code-review diff, a KQL block, and an SVG figure.
- Export to Markdown now preserves `data-cm-widget` boards as a widget note plus a GFM table, so the triage board
  survives Markdown export instead of being skipped as `cm-skip` chrome.

## [1.12.0] - 2026-07-12

### Added

- Added **Export Offline**, which builds a Portable export with current comments, snapshots rendered
  mermaid diagrams as inline SVG, snapshots chart canvases as PNG data images, removes remote rich-content
  loaders, and produces a strict-valid zero-network HTML handoff.

## [1.9.1] - 2026-07-12

### Added

- The shipped plugin `README.md` and `SKILL.md` now explain why commentable-html beats planning in chat, a
  Markdown file, or plain HTML - a medium-comparison table plus a reference to Anthropic's "unreasonable
  effectiveness of HTML" blog post - so the motivation matches the project website.

## [1.9.0] - 2026-07-12

### Added

- `new_document.py` now defaults NonPortable companion references to absolute `file://` URLs that point at
  the installed skill `dist/`, so the generated HTML can move anywhere on the same machine without losing
  its CSS/JS. Use `--assets-relative` to restore the old relative-path behavior for a movable folder bundle.
- The NonPortable asset banner now has an accessible `Dismiss` button. A dismissed version warning stays
  hidden across reloads for that document key and page/runtime version pair.
- The SKILL.md documents the page/runtime compatibility contract: same-major newer runtimes can open older
  same-major pages without warning, and breaking page/runtime changes require a major version bump.

### Changed

- The NonPortable version handshake is now semver-aware. Same-major older pages no longer show a scary
  mismatch banner after a safe skill update, newer same-major pages show a soft update notice, and
  different-major pages show the incompatible-runtime warning.
- `validate.py` treats only `http://` and `https://` companion refs as remote/CDN URLs. Local `file://` refs
  and absolute filesystem paths are accepted, while plain absolute filesystem paths still warn that they are
  local-only.

## [1.8.0] - 2026-07-12

### Added

- Two mermaid diagrams in `references/exports.md` (linked from the SKILL.md Output modes section)
  showing what is bundled in the file versus fetched from where: Portable inlines the layer CSS/JS,
  NonPortable loads the `commentable-html.{css,js,assets.js}` companions from the skill `dist/`, and both
  keep the plan content and comments inline while fetching optional mermaid/Chart.js from a CDN.
- The `analysis`, `plan`, and `report` keywords, and the "drastically shortens the AI planning and
  iteration loop" framing in the SKILL.md intro and the plugin READMEs. The marketplace category is now
  `planning and analysis`.
- The brand mark now links to the project site
  (`https://urikanonov.github.io/ai-marketplace/commentable-html/`) in a new tab, in the footer (icon plus
  versioned name) and on the sidebar meta-row brand icon. The link is chrome, so it never leaks into a Plain
  HTML export.
- The Help modal title now includes the running layer version (`Commentable HTML v<version> - Help`).
- Each overflow (`...`) menu item (Show, Export as Portable, Export to Plain HTML, Export to Markdown,
  Help & About) now carries a leading decorative icon matching the chrome icon style.

### Changed

- `Export to Markdown` is now download-only: it downloads the `.md` file and no longer writes the clipboard.
  The toast, Help topic, button tooltips, SKILL.md, and `references/exports.md` were updated to drop the
  clipboard claim.

### Fixed

- On touch / coarse-pointer devices the "Add Comment" popup now appears when a text selection settles.
  Selecting text on a phone drags the native handles and never fires `mouseup`, so the popup previously
  never showed; a debounced `selectionchange` now raises the same popup (and hides it when the selection
  collapses). Desktop mouse behavior is unchanged.

## [1.7.0] - 2026-07-11

### Fixed

- Export on `file://` no longer drops content authored after the layer script. The export base is now
  captured from the fully parsed DOM at export time (then re-stripped of runtime artifacts) instead of a
  snapshot taken before late content (for example a `chart_block` chart placed after the layer) was parsed.
- `Export as Portable/Standalone` finds the embedded-comments script regardless of its attribute order, and
  aborts with a clear error when the companion assets version does not match the running runtime.
- `Export to Markdown` now serializes `<strong>`/`<em>`/`<a>`/`<code>`/`<img>` that are direct children of a
  list item, and its URL allowlist keeps only image data URLs (a bare `data:` destination is neutralized
  while `data:image` is preserved).
- Image/canvas comment highlights clear and flash correctly on `<canvas>` widgets, not just `<img>`.
- Duplicate persisted comment ids are de-duplicated on load so a corrupted store cannot render twin cards.
- `generate_toc.py` and `validate.py` reset the `#commentRoot` scope on the root's closing tag, so a heading
  or cross-reference in a later footer or sibling container is no longer collected into the TOC or validated
  as document content.
- `validate.py` accepts cache-busted companion references, stripping a `?query`/`#fragment` before the
  `.js`/`.css` suffix and the on-disk existence check.
- `diff_block.py` preserves a file-final-newline-only difference and emits the standard
  `\ No newline at end of file` marker instead of silently dropping it.
- `new_document.py` refuses NonPortable output to stdout unless `--assets-href` is given, because bare
  companion names written to a stream are unreachable; its `--key-from-source` help no longer claims a
  `--label` fallback.
- `chart_block.py` adds its own tools directory to `sys.path` on import so the sibling `validate` module is
  importable and self-validation is never silently skipped.
- `--help`/`-h` now exits 0 with usage on every shipped tool (`validate.py`, `kql_highlight.py`,
  `kusto_link.py`, `mark_handled.py`, and the rest), instead of treating the flag as a filename.
- `new_document.py --key auto` derives the comment key from the output/source path identity rather than the
  label, so two documents that share a title no longer collide and leak comments across each other.
- The lede/intro block is no longer clamped by the 72ch prose measure, so it renders at the section width.
- The confirm dialog always traps Tab and pulls escaped focus back to Cancel; Escape closing the toolbar
  overflow menu or the add-comment menu restores focus and no longer discards an open composer draft; the
  side-TOC highlights the last section once the page is fully scrolled.

### Added

- Headings are keyboard-focusable with a visible focus style and Enter/Space activation for the deep-link /
  add-comment affordance, matching the mouse-only behavior.
- Generated documents carry a visible themed document title (`#commentRoot > h1`); `new_document.py` adds a
  visible `<h1>` from `--label` unless the fragment already has one or `--no-title` is passed.
- The trust boundary is documented in `SKILL.md` and `new_document.py --help`: authored content is trusted
  HTML and is not sanitized; callers must sanitize untrusted host HTML before wrapping it.
- A `new_document.py` quickstart example in the plugin README; `retrofitting.md` documents the
  `window.__cmh*` / `__commentable*` introspection globals.

### Changed

- `validate.py` requires `headingAddBtn`, `widgetAddBtn`, and `menuDocComment`, and its stale version note
  now points at the correct removal version.
- `upgrade.py` matches its replace regions by exact begin/end markers; the composer placeholder documents the
  `Ctrl/Cmd+Enter` save shortcut; `kusto_link.py` and the dev tests use public/generic cluster, path, and
  database names in place of internal ones.
- `build.py` now regenerates the example reports' layer regions and version stamps from the freshly built
  dist and covers them in `--check`.
- Both export modes download `<stem>-portable.html`; the NonPortable "Export as Portable" no longer emits a
  `<stem>.standalone.html` filename.

## [1.6.1] - 2026-07-11

### Added

- The Help `Getting started` topic now embeds the review-loop diagram (the agent-to-you-and-back
  loop) beneath the four steps, themed with the framework's light/dark variables so it follows the
  active theme.
- A `Website and live demo` link in the Help About block, pointing at the plugin's GitHub Pages page.

### Changed

- Merged the `The review workflow` and `Getting started` help topics into a single, default-open
  `Getting started` topic, removing the overlap between them.
- Reworded the `Self-contained and privacy` help topic: comments are stored in this browser's
  `localStorage` (private, never uploaded, no account), and the review layer travels inside the file
  only in Portable mode - a Not portable file references small companion resources. It no longer
  implies the layer is always bundled into the file.

## [1.6.0] - 2026-07-11

### Changed

- Adopted mermaid 11: the shipped page templates (`dist/PORTABLE.html`, `dist/NONPORTABLE.html`) and the
  example reports now load `mermaid@11.16.0` from the CDN, and the commenting layer is verified to render,
  anchor, and comment on mermaid 11 diagrams (full Playwright suite green against mermaid 11). This rode in
  on a dev/test-only dependency bump (mermaid 11.16.0, chart.js 4.5.1, adm-zip 0.6.0); none of those dev
  dependencies ship in the plugin.

## [1.5.1] - 2026-07-11

### Changed

- Polished the review-loop diagram (`docs/images/review-loop.svg` and its site twin): the step labels use
  consistent casing ("1. Generates HTML", "2. Comment Inline"), and the "reload and repeat" caption became
  a fourth curved arrow from the AI agent back to you, so the loop reads as a closed cycle.

## [1.5.0] - 2026-07-11

### Added

- Commentable widgets and SVG nodes. A generic opt-in contract (`data-cm-widget`, `data-cm-part`,
  optional `data-cm-part-label`, and `data-cm-slot`) makes individual parts of an interactive widget
  or a labeled SVG `<g>` node commentable, with a hover/keyboard Add Comment affordance and a
  `widget` anchor type that restores across reloads and exports.
- Widget layout-change tracking. When parts sit in `data-cm-slot` containers, drag/drop moves are
  detected against the load-time baseline and surfaced as a synthetic sidebar card and a "Widget
  layout changes" section in the Copy-all bundle; the document is flagged Not portable until it is
  re-exported.
- Document-wide comments. Right-clicking empty space adds an unanchored, whole-document comment
  (`document` anchor type) that carries no highlight and copies as a document-wide anchor.
- Export to Markdown. A new sidebar and overflow-menu action copies the document content to the
  clipboard and downloads a `.md` file via a deterministic, block-by-block conversion (headings,
  lists, GFM tables, fenced code / diff / mermaid / kusto, callouts as GitHub alerts, charts and
  SVG figures as caption notes), with the current comments appended as a section. Untrusted text,
  attributes, and comment notes are escaped so the exported Markdown cannot inject raw HTML or
  forge document structure.

### Changed

- The overflow-menu portability badge now shares the sidebar badge's coloring and tooltip
  (via `data-doc-type`), so both convey the same Portable / Not portable semantics.
- Authoring guidance: content-conventions now covers shaping content in real layouts, an
  anti-default-look taste checklist, a readable prose measure (top-level paragraphs are capped while
  tables, figures, and code keep full width), and mapping a product's design tokens onto the
  `--cp-*` variables.

## [1.4.0] - 2026-07-11

### Added

- Help & About: a "Tips and shortcuts" topic for power users (right-click to comment, re-select the same
  text to reopen a comment, multiple and draggable composers, sort back to document order, the Expand and
  Collapse controls, the diff Syntax toggle, and the keyboard shortcuts), plus "Request a feature" and
  "Contribute" links in the About block alongside the existing source and issue links.
- A review-loop diagram (`docs/images/review-loop.svg`) embedded in a new "Review workflow" section of the
  plugin README, showing the agent-to-you-and-back loop and naming the self, peer, and reviewer variants.

### Changed

- Help & About now orients a first-time reviewer. The review-workflow topic points a recipient who was
  sent a file straight to leaving a comment (no agent or account needed), the "Getting started" topic is
  retitled for reviewing a shared file, and the search box suggests "shortcuts".
- `docs/TUTORIAL.md` gained a short "you were sent a file to review" quick start and a pointer to the new
  Tips and shortcuts help topic.

## [1.3.1] - 2026-07-11

### Fixed

- Single-quoted string styles now require their closing quote, so a lone `'` in valid code (a Rust
  lifetime like `&'static str`, an apostrophe like `don't`, or a C++ digit separator `1'000`) is no
  longer swallowed as a string to the end of the line. Double-quoted and backtick strings still
  highlight when unterminated, and string scanning stays linear time.
- CSS highlighting now treats only the CSS-wide keywords (`auto`, `none`, `inherit`, `initial`,
  `unset`, `revert`, `important`) as keywords, so class selectors such as `.block` or `.center` are no
  longer colored as keywords.
- The in-browser diff highlighter matches the case-insensitive keywords of SQL, Batch, and PowerShell
  (uppercase keywords now color), scans strings and comments in linear time for the newly added
  languages, maps the `.m` extension to Objective-C, and no longer over-colors common identifiers
  (`data`, `local`, `end`, and similar) as keywords in unrelated diffs.

## [1.3.0] - 2026-07-11

### Added

- Author-time syntax highlighting (`tools/highlight_code.py`) now covers many more popular languages:
  Rust, Ruby, PHP, Swift, Kotlin, Scala, Dart, R, Perl, PowerShell, Lua, TOML, CSS, Groovy, Elixir,
  Haskell, and Objective-C, plus Windows Batch (`batch`, with `bat` and `cmd` aliases), with the usual
  aliases (`rs`, `rb`, `kt`, `pl`, `ps1`, `ps`, `objc`, `hs`, `ex`, `exs`). Shell scripts were already
  covered via the existing `shell` and `sh` aliases for `bash`. Run
  `python tools/highlight_code.py --list` for the full set.
- The in-browser diff highlighter now recognizes the same expanded language set (CSS, Groovy, Elixir,
  Haskell, Objective-C, Lua, PowerShell, and Windows Batch, plus their aliases), so review diffs in
  those languages render with token colors instead of plain text.

### Fixed

- Keywords are now matched case-sensitively except in genuinely case-insensitive languages (SQL, Batch,
  PowerShell, HTML, CSS). Previously a global case-insensitive match mis-colored ordinary identifiers as
  keywords (for example C# `String`, Python `true`/`none`, Rust `Fn`).
- String tokenization is now linear time. Pathological input (a long run of escaped quotes) previously
  drove superlinear rescanning; the string patterns use an unrolled form that stays fast.
- Strings keep a backslash-newline line continuation inside the string, unterminated block comments and
  strings still highlight (to end of input / end of line), Swift and Dart triple-quoted strings and TOML
  literal (single-quoted) strings are recognized, and a Windows Batch `rem` comment is matched on a word
  boundary (so `rem`, `rem<TAB>`, and a bare `rem` are comments, but `remark` is not).

## [1.2.2] - 2026-07-11

### Changed

- Clarified the NonPortable asset-location wording in the skill reference: the default companion
  files are referenced by a relative path (the skill's `dist/` folder by default), not "beside the
  document"; the document sits beside its companions only when they are copied there.

## [1.2.1] - 2026-07-11

### Changed

- Documentation wording now describes the NonPortable default accurately. The skill reference and the
  plugin README no longer call a generated document "single-file" or "Portable" by default: the default
  NonPortable document loads its CSS/JS from companion files, while Export as Portable (or `--portable`)
  produces the one self-contained file.

## [1.2.0] - 2026-07-11

### Fixed

- Mobile responsiveness of generated documents. Wide tables now scroll horizontally inside their own
  box on narrow screens instead of forcing the whole page to overflow. The Kusto query caption stacks
  the cluster title and the "Run in Azure Data Explorer" link onto separate lines below 700px so they
  no longer cramp. The floating Copy/language pills reserve top headroom over every code block (KQL
  figures included) so they no longer overlap the first line of code. Figures use symmetric vertical
  margins with no side indent so embedded images and charts get the full content width.
- On touch / coarse-pointer devices the browser's native selection menu (Copy, Share, Look up) is left
  intact; the reader can copy selected text again, while the floating "Add comment" popup still handles
  commenting.

### Changed

- `docs/TUTORIAL.md` now references the running example with a skill-root-relative display path that links
  to the local file, so the reference reads cleanly without any `..` path traversal.

## [1.1.3] - 2026-07-11

### Fixed

- Documentation accuracy from the agency review pass: the generated-document header comment (and the
  two shipped example reports) now name the Export as Portable download `<stem>-portable.html`, matching
  the current UI (it previously said `<stem>-comments.html`); and `references/design-decisions.md` now
  states correctly that a `<canvas>` renders when either the Chart.js loader OR an inline `getContext`
  draw is present, so a hand-drawn non-Chart.js canvas is accepted and only a canvas with neither is
  flagged (matching `validate.py` E3).

### Notes

- Documentation-only changes; no code or runtime behavior change.

## [1.1.2] - 2026-07-11

### Fixed

- `chart_block.py`: self-validation writes its temporary file to the system temp directory instead of
  the current working directory, so it works from a read-only directory (matching `new_document.py`).
- `kql_highlight.py`: added a `--` end-of-flags separator so a positional value that begins with `--`
  is taken literally instead of being rejected as an unknown flag.

### Notes

- Follow-up robustness fixes from the agency review pass; no change to the runtime review behavior.

## [1.1.1] - 2026-07-11

### Fixed

- `new_document.py`: corrected docstrings that referenced a removed CLI export tool; `--assets-href "/"`
  now produces root-relative companion references instead of dropping the prefix; a cross-drive `--out`
  gives an actionable message instead of a raw `relpath` error; `--copy-assets` copies the companions
  before writing the HTML so a failed copy never leaves a broken file; the write path reports `OSError`
  cleanly; `--copy-assets` / `--assets-href` warn when combined with `--portable`; a custom `--template`
  defers the companion existence check (it previously always failed self-validation); and self-validation
  no longer writes its temp file under the current working directory, so it works from a read-only
  directory.
- `validate.py`: the NonPortable remote-URL and absolute-path checks always run (they are structural),
  and only the on-disk existence check is gated on `base_dir`, so an `--assets-href` remote/absolute path
  is caught at generation time. Added direct `base_dir` unit tests.
- `inline_images.py`: a missing or unreadable input file now reports a clean error and exits 1 instead
  of raising an uncaught `OSError`.

### Notes

- Fixes surfaced by a 6-model rubber-duck review panel on the NonPortable-first change, plus a
  plugin-description wording tidy-up (drop "single-file" now that NonPortable is the default). No change
  to the runtime review behavior.

## [1.1.0] - 2026-07-11

### Added

- Resizable comments sidebar with a keyboard-focusable drag handle, persisted width, viewport clamps, and matching reserved page space.
- Problem statement plus self-review, peer-review, and reviewer-side review-loop documentation for the generated review surface.
- Documentation that explains when to use NonPortable for fast local iteration and when to Export as Portable for sharing or long-term storage.

### Changed

- Runtime left navigation side menu now labels itself as "Navigation" while leaving author-authored table-of-contents titles alone.
- Sidebar header actions wrap into narrower rows instead of overflowing when the viewport or resized sidebar is narrow.

### Fixed

- Chart.js canvases, including pie and doughnut charts, stay bounded inside `figure.chart` at narrow widths.

## [1.0.2] - 2026-07-11

### Changed

- New documents are now **NonPortable by default** (`tools/new_document.py`): the layer CSS/JS load
  from companion files, so authoring and every regeneration during a review loop is materially
  smaller (about 89% less boilerplate re-emitted). Pass `--portable` for a single self-contained file.

### Added

- `tools/new_document.py` gains `--portable`, `--nonportable` (the default), `--copy-assets`, and
  `--assets-href` to control how a NonPortable document references its companion files, plus
  `active_root_attrs` and an `allow_reserved_key` option for re-stamping an existing document.
- `validate.validate()` accepts an optional `base_dir` so NonPortable companion references can be
  resolved against the file's final location, or the path checks skipped (structure only) when
  placement is deferred.

### Notes

- To hand someone a single shareable file, either regenerate with `--portable` (for a document that
  has no in-browser comments yet) or use the in-page **Export as Portable** button. The button is the
  only path that captures comments the user typed in the browser: those live in `localStorage`, which
  no CLI (even a headless browser) can read, so there is deliberately no CLI export.

## [1.0.1] - 2026-07-10

### Changed

- Hardened the CI version-bump gate (`scripts/check_version_bump.py`): it now diffs from the merge
  base so a PR is judged only on its own changes, fails closed on an invalid or unfetched base ref,
  normalizes source paths correctly, and requires a version bump when a plugin's source path changes.
- Hardened `build.py` version stamping and the build `--check` drift guard.

### Fixed

- Quality fixes surfaced by a multi-model (multi-duck) review of the 1.0.0 refactor, including a
  statically pinned Chart.js loader for a stable SRI hash and assorted tool and documentation
  polish. No change to the runtime review behavior.

## [1.0.0] - 2026-07-10

First official release.

### Added

- Offline, single-file commentable HTML review surface: reviewers select any paragraph, table cell,
  code block, KQL block, chart, image, or mermaid diagram and leave inline comments, then copy or
  export a bundle back to an agent, with no network dependency.
- Portable mode (one self-contained file) and NonPortable mode (companion CSS/JS files).
- Deterministic Python tooling (`new_document`, `inline_images`, `chart_block`, `upgrade`, `validate`,
  and more) plus a standard-library validator that enforces the structural invariants of a generated
  file.
- Rich, commentable content: tables, Chart.js charts, mermaid diagrams, KQL blocks, code-review diffs,
  and inlined images.
- Each generated file stamps the skill version that produced it in a
  `<meta name="commentable-html-version">` in the head and in the visible footer.

### Notes

- The injected layer is version-agnostic: the region markers, the companion filenames, and the demo
  storage keys no longer embed a version. The single source of truth for the release version is
  `dev/VERSION`; `build.py` stamps it into the layer constant, `plugin.json`, the marketplace entry,
  and each document's version `<meta>`, and `build.py --check` guards against drift.
