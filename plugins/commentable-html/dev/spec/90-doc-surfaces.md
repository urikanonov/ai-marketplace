## Doc-surface coverage (feature visibility)

Every user-facing feature must be discoverable from at least one documentation SURFACE, and every new
feature must declare where it is surfaced (or opt out) in the same pull request. The reader-facing
surfaces are:

- `tutorial` - the guided walkthrough in `docs/TUTORIAL.md` (the site tutorial page is generated from it).
- `site` - the marketplace pages under `site/pages/commentable-html` (a highlights page, not exhaustive).
- `help` - the in-runtime Help/About panel (`dev/assets/js/75-help.js`).

There is also a fourth SHOWCASE surface, tracked as its own required dimension:

- `deck` - the showcase presentation (`examples/deck-showcase.html`, built from
  `dev/examples/src/deck-showcase.html`), which runs the real runtime and demonstrates features as live
  interactive slides (or, where a live demo is impractical, a screenshot or an explicit on-slide
  mention). Because the deck has its own requirement - every user-facing feature should be demonstrated
  on a slide - it is a SEPARATE column in the registry, not one of the reader-doc surfaces above.

Governance rule (enforced): when a pull request adds a NEW feature-id row to this spec, it must also add
a row for that id to the "Doc-surface registry" table below with BOTH:

- a `Doc surface` value: one or more surfaces (a comma-separated subset of `tutorial`, `site`, `help`)
  OR `opt-out: <reason>` for a change that is not user-facing (internal hardening, build/authoring
  tooling, a robustness invariant, a security guard, an agent-facing export format, etc.), and
- a `Deck` value: `deck` when the feature is demonstrated on a showcase-deck slide (live demo,
  screenshot, or an explicit mention), OR `opt-out: <reason>` when it genuinely does not warrant a
  slide (a non-user-facing change, an in-runtime-panel-only detail, an internal robustness invariant).

`scripts/check_doc_surfaces.py` fails a PR whose newly added feature ids lack a registry entry, fails a
registry row that is missing either column or carries a malformed value, and fails if a registry row
names an id that no longer exists. Prefer a real surface and a real deck slide; use `opt-out` only when
the behavior is genuinely not something a reader needs documented or a viewer needs shown.

### Coverage matrix (by area)

A human summary of where each major user-facing area is surfaced today, including whether the showcase
deck demonstrates it. Internal / tooling / hardening areas are surfaced as `opt-out` in the registry and
omitted here.

| Area | Surfaced in |
| --- | --- |
| Leaving and managing comments (CORE, NOTE editing, SIDE) | tutorial, site, help, deck |
| Rich content: charts, KQL, code, diffs, mermaid, images (CHART, KQL, CODE, DIFF, MMD, IMG) | tutorial, site, help, deck |
| Rich-text comment formatting (RICH) | tutorial, help, deck |
| Review checklists (CHECK) | tutorial, help, deck |
| Section review badges and the section menu / search / filter (REVIEW, TOC, SEARCH) | tutorial, help, deck |
| Threads, inline replies, and author names (THREAD, AUTHOR) | tutorial, help, deck |
| Counting note and checklist changes in the badge (NOTE-04, CHECK-06) | tutorial, help, deck |
| Copy all and sending comments to an agent (COPY, HANDLED) | tutorial, help, deck |
| Exports: Portable, Offline, Plain HTML, Markdown, Save as PDF (EXP, OFFLINE, PRINT) | tutorial, site, help, deck |
| Storage manager, pie-chart breakdown, and per-document browsing (STORE) | tutorial, help, deck |
| Board and deck document kinds (BOARD, DECK, MODE) | tutorial (board), site (deck), help (board), deck |
| Portability / offline badge and privacy (PKG-portability, PRIVACY) | tutorial, site, help, deck |
| Commentable widgets and SVG nodes (WIDGET) | help, deck |

### Doc-surface registry

Machine-checked by `scripts/check_doc_surfaces.py`. Each new feature-id row above must add a matching
entry here. A `Doc surface` value is a comma-separated subset of `tutorial`, `site`, `help`, or
`opt-out: <reason>`. A `Deck` value is `deck` (demonstrated on a showcase-deck slide) or
`opt-out: <reason>`.

| Feature id | Doc surface | Deck |
| --- | --- | --- |
| CMH-HELP-COUNT-01 | help | opt-out: in-runtime Help/About panel topic, not a deck slide |
| CMH-HELP-THREADS-01 | help | opt-out: in-runtime Help/About panel topic, not a deck slide |
| CMH-HELP-STORE-01 | help | opt-out: in-runtime Help/About panel topic, not a deck slide |
| CMH-STORE-13 | tutorial, help | deck |
| CMH-STORE-14 | tutorial, help | deck |
| CMH-STORE-15 | tutorial, help | deck |
| CMH-NOTE-04 | tutorial, help | deck |
| CMH-NOTE-05 | tutorial | deck |
| CMH-CHECK-06 | tutorial, help | deck |
| CMH-THREAD-01 | tutorial, help | deck |
| CMH-THREAD-06 | tutorial, help | deck |
| CMH-THREAD-07 | help | opt-out: sidebar reply-edit-in-place detail, not a distinct slide |
| CMH-THREAD-08 | help | opt-out: identity-prompt-on-first-reply detail, not a distinct slide |
| CMH-THREAD-09 | opt-out: internal draft-preservation robustness, not separately documented | opt-out: internal draft-preservation robustness, not a deck topic |
| CMH-THREAD-10 | help | opt-out: sidebar note-edit-in-place detail, not a distinct slide |
| CMH-UI-12 | opt-out: click-target sizing of the already-documented Open comment bubble, no new capability | opt-out: control sizing, nothing to demonstrate on a slide |
| CMH-AUTHOR-01 | tutorial, help | deck |
| CMH-AUTHOR-02 | tutorial, help | deck |
| CMH-AUTHOR-03 | opt-out: agent-facing Copy all attribution format and injection hardening | opt-out: agent-facing Copy all attribution format, not a deck topic |
| CMH-MMD-11 | opt-out: keyboard-accessibility parity (WCAG 2.1.1) for the already-documented diagram commenting, mirroring the image keyboard path; no new user-facing capability to document | opt-out: keyboard-accessibility parity for the already-shown diagram commenting, not a separate slide topic |
| CMH-SEARCH-08 | tutorial, help | deck |
| CMH-EXP-15 | opt-out: a transient confirmation toast on the already-documented export actions; not a separately documented capability | opt-out: a transient export-confirmation toast, nothing to demonstrate on a slide |
| CMH-SIDE-11 | tutorial, help | opt-out: sidebar More-menu grouping detail; the storage manager it houses is shown on the deck, but the menu grouping is not a slide topic |
| CMH-SIDE-12 | opt-out: responsive touch-target sizing for the already-documented Sort control; a mobile accessibility refinement, not a new user-facing capability | opt-out: responsive touch-target refinement, not a deck topic |
| CMH-LINK-05 | opt-out: an authoring-time validator warning (agent/author-facing) that enforces the already-documented new-tab link behavior; no new reader-facing capability | opt-out: authoring-time validator warning (agent/author-facing), not a deck topic |
| CMH-DECK-SHOWCASE-18 | site | deck |
| CMH-BUILD-15 | opt-out: internal build invariant that stamps the demo examples' build date; the user-facing "Generated on" line itself is CMH-SIDE-03 | opt-out: internal build/authoring invariant, not a deck topic |
| CMH-DECK-SHOWCASE-19 | site | deck |
| CMH-BUILD-14 | opt-out: internal Playwright test-harness reliability (deterministic static-server teardown); not a reader-facing capability | opt-out: internal test-harness reliability, not a deck topic |
| CMH-DECK-41 | opt-out: showcase demo-deck content (a slide's own diagram layout), not a runtime feature documented to readers | deck |
| CMH-DECK-42 | site | deck |
| CMH-BUILD-16 | opt-out: build/authoring tooling for maintainers (how to regenerate the tutorial screenshots with the CI renderer); documented in docs/testing-guidelines.md, not a reader-facing capability | opt-out: maintainer build tooling, not a deck topic |
| CMH-BUILD-17 | opt-out: internal capture geometry that keeps the tutorial screenshots dimension-stable across renderers; documented in docs/testing-guidelines.md, not a reader-facing capability | opt-out: maintainer build tooling, not a deck topic |
| CMH-BUILD-18 | opt-out: CI diagnostics for maintainers and contributors (the drift gate's evidence artifact); documented in docs/testing-guidelines.md, not a reader-facing capability | opt-out: maintainer build tooling, not a deck topic |
| CMH-BUILD-19 | opt-out: internal drift-gate budget for the tutorial screenshots (how strictly the committed PNGs are compared); documented in docs/testing-guidelines.md, not a reader-facing capability | opt-out: maintainer build tooling, not a deck topic |
| CMH-HL-05 | help | opt-out: the syntax-highlighting slide is at its fixed 1080px stage capacity - a third code block overflows it on CI - and JSON is already named in that slide's supported-syntax pills |
| CMH-HL-06 | opt-out: a correctness fix to the already-documented syntax highlighting (a comment abutting an operator was mis-tokenized); no new reader-facing capability | opt-out: a tokenizer correctness fix, not a deck topic |
| CMH-HL-07 | help | deck |
| CMH-HL-08 | help | deck |
| CMH-HL-09 | opt-out: an internal authoring-tool invariant (highlighting is reversible) that enables agent-side content editing; readers see no new capability | opt-out: a round-trip guarantee for tooling, with nothing to show on a slide |
| CMH-HL-10 | opt-out: an internal robustness guard that refuses to rewrite hand-written markup in a code block; no reader-facing capability | opt-out: a safety invariant for tooling, not a deck topic |
| CMH-HL-11 | opt-out: an internal refactor unifying the two highlighters' emission point; output bytes are unchanged and readers see no difference | opt-out: an internal refactor with no visible behavior change |
| CMH-DEMO-07 | opt-out: shipped demo content (a Markdown block in the showcase report) that exercises the documented Markdown highlighting (CMH-HL-07), not a separately documented capability | opt-out: demo-report content; the Markdown language itself is shown on the supported-labels slide |
| CMH-SEL-03 | opt-out: a placement fix for the already-documented Add Comment popup - it appears next to the selected text as the tutorial already shows; no new reader-facing capability | opt-out: a popup-placement correctness invariant for the already-shown text commenting, not a separate slide topic |
| CMH-VAL-17 | opt-out: an authoring-time validator internal (the script scanner's regex-literal handling); agent/author-facing robustness, no new reader-facing capability | opt-out: authoring-time validator internal, not a deck topic |
| CMH-VAL-18 | opt-out: an authoring-time validator/tooling internal (which validator warnings are advisory and therefore non-blocking); readers of a document see no new capability | opt-out: a warning-severity contract for the authoring tools, with nothing to show on a slide |
| CMH-VAL-20 | opt-out: an authoring-time validator correctness fix (three checks read the layer's own markup instead of the whole document); a reader of a document sees no new capability | opt-out: validator internals, with nothing to show on a slide |
| CMH-VAL-21 | opt-out: an authoring-time validator internal (both tolerant parsers share one browser-accurate, version-independent set of element boundaries); a reader of a document sees no new capability | opt-out: tokenizer internals, with nothing to show on a slide |
| CMH-CONTENT-01 | opt-out: an agent-facing authoring tool that makes the review loop cheaper; readers of a document see no new capability | opt-out: tooling for the agent side of the loop, with nothing to demonstrate on a slide |
| CMH-CONTENT-02 | opt-out: an agent-facing authoring tool (atomic write-back); no reader-visible behavior change | opt-out: a transactional guarantee for tooling, not a deck topic |
| CMH-CONTENT-03 | opt-out: an internal fidelity invariant (untouched sections keep their hashes); readers see no new capability | opt-out: an invariant with nothing to show on a slide |
| CMH-CONTENT-04 | opt-out: an agent-facing export-reading format for the peer-review handoff | opt-out: agent-side tooling, already covered by the documented peer-review loop |
| CMH-KQL-09 | opt-out: an internal dispatch unification; KQL blocks already rendered highlighted, so readers see no change | opt-out: an internal refactor with no visible behavior change |
| CMH-KQL-10 | site | opt-out: the deck's KQL slide already shows a runnable block; the fix is that the link stays correct after an edit, which a slide cannot show |
| CMH-HL-12 | opt-out: a validator hardening that catches malformed highlighting markup; not a reader-facing capability | opt-out: a validation guard, not a deck topic |
| CMH-HL-13 | opt-out: a gap fix in extension inference for an already-documented capability (diff syntax highlighting); no new reader-facing feature | opt-out: the deck already shows highlighted diffs; the fix is that more file types infer correctly |
| CMH-HL-14 | opt-out: a correctness fix to already-documented syntax highlighting (keyword coloring now matches the baked output); no new capability | opt-out: a tokenizer parity fix, not a deck topic |
| CMH-HL-15 | opt-out: a correctness fix to already-documented SQL highlighting (a double-quoted identifier now colors on both paths) | opt-out: a tokenizer parity fix, not a deck topic |
| CMH-BUILD-20 | opt-out: an internal performance refactor of the authoring pipeline; output is byte-identical so readers see no change | opt-out: an I/O refactor with nothing to demonstrate on a slide |
| CMH-SIZE-01 | site | opt-out: a size and file-layout optimisation with nothing to demonstrate on a slide - the viewer sees the same document, only smaller |
| CMH-OFFLINE-07 | opt-out: a bug fix to the already-documented Export Offline action - the reader gets the download the button always promised, so there is no new capability to document | opt-out: nothing to demonstrate on a slide - a re-exported deck or report renders exactly as the first export already did |
| CMH-OFFLINE-06 | opt-out: a size correctness fix to the already-documented Offline export; the reader gets the same offline file, only without a library it never called, so there is no new capability to document | opt-out: an export-size optimisation with nothing to demonstrate on a slide - the exported charts render exactly as they already did |
| CMH-RESP-10 | opt-out: a rendering-correctness fix; a reader sees a table that is no longer broken, with nothing new to learn | opt-out: a layout fix with nothing to demonstrate on a slide |
| CMH-RESP-11 | opt-out: a layout-containment fix; a wide table scrolls in its box exactly as it already did on a phone, so there is no new capability to document | opt-out: a layout fix with nothing to demonstrate on a slide |
| CMH-PORT-01 | tutorial | opt-out: a one-off migration command for legacy documents; nothing to demonstrate on a slide |
| CMH-PORT-02 | site | opt-out: a compatibility guarantee - the viewer sees an old document simply continuing to work |
| CMH-PORT-03 | tutorial, site | opt-out: a default-mode change; the slide shows the document, not which mode produced it |
| CMH-PORT-04 | opt-out: internal safety hardening of the migration tool (crash-safe write, hostile-input neutralization, ambiguity refusal); a reader sees no new capability | opt-out: a robustness invariant with nothing to demonstrate on a slide |
| CMH-VAL-19 | opt-out: an authoring-time validator internal (which occurrences of the companion markup decide the document mode); a reader sees no new capability | opt-out: an authoring-time validator internal, not a deck topic |
| CMH-CHART-12 | opt-out: an internal consistency invariant (one shared selector definition) that fixes a bare chart canvas the documented recipes never produce; the documented authoring shapes are unchanged | opt-out: the deck already demonstrates charts; this is a renderer/exporter agreement fix with nothing new to show |
| CMH-RICH-15 | help | opt-out: a parity fix - the deck already demonstrates the formatting toolbar; the same toolbar in the side pane shows nothing new on a slide |
| CMH-RICH-16 | help | opt-out: a parity fix - the deck already demonstrates the formatting shortcuts; the same shortcuts in the side pane show nothing new on a slide |
| CMH-RICH-17 | opt-out: a mobile touch-target invariant for a toolbar the reader already knows about; there is no new capability to document | opt-out: a touch-target size invariant, not something a viewer needs shown on a slide |
| CMH-PRINT-07 | opt-out: a print-layout invariant - a diagram simply fits the printed page; there is nothing for a reader to learn or do | opt-out: print/PDF page-fit correctness, not something a viewer needs shown on a slide |
| CMH-RICH-18 | help | opt-out: a parity fix - the deck already demonstrates the formatting toolbar; the same toolbar in the in-document dialog shows nothing new on a slide |
| CMH-RICH-19 | help | opt-out: a parity fix - the deck already demonstrates the formatting shortcuts; the same shortcuts in the in-document dialog show nothing new on a slide |
| CMH-RICH-20 | opt-out: a mobile touch-target invariant for a toolbar the reader already knows about; there is no new capability to document | opt-out: a touch-target size invariant, not something a viewer needs shown on a slide |
| CMH-RICH-21 | help | opt-out: a keyboard-navigation invariant for a toolbar the deck already demonstrates; a tab stop is not something a viewer sees on a slide |
| CMH-RICH-22 | opt-out: a mobile touch-target invariant for a toolbar the reader already knows about; there is no new capability to document | opt-out: a touch-target size invariant, not something a viewer needs shown on a slide |
