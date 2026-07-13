# Changelog

All notable changes to the `commentable-html` plugin are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
