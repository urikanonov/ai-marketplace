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
| Selecting comments to hand back or delete only part of a review (PICK) | help, deck |
| Exports: Shareable, Offline, Plain HTML, Markdown, Save as PDF (EXP, OFFLINE, PRINT) | tutorial, site, help, deck |
| Storage manager, pie-chart breakdown, and per-document browsing (STORE) | tutorial, help, deck |
| Board and deck document kinds (BOARD, DECK, MODE) | tutorial (board), site (deck), help (board), deck |
| Shareability / offline badge and privacy (PKG-shareability, PRIVACY) | tutorial, site, help, deck |
| Commentable widgets and SVG nodes (WIDGET) | help, deck |

### Doc-surface registry

Machine-checked by `scripts/check_doc_surfaces.py`. Each new feature-id row above must add a matching
entry here. A `Doc surface` value is a comma-separated subset of `tutorial`, `site`, `help`, or
`opt-out: <reason>`. A `Deck` value is `deck` (demonstrated on a showcase-deck slide) or
`opt-out: <reason>`.

| Feature id | Doc surface | Deck |
| --- | --- | --- |
| CMH-VAL-23 | opt-out: an authoring-time parser correctness fix plus an explicit runtime light-DOM boundary, with no new reader-facing capability | opt-out: parser and walker boundaries have nothing to demonstrate on a slide |
| CMH-VAL-25 | opt-out: an authoring-time security gate that closes an egress hole in the self-contained guarantee - it refuses markup an author should not have written, and adds no reader-facing capability | opt-out: a validator refusal has nothing for a viewer to see on a slide |
| CMH-VAL-26 | opt-out: an authoring-time validator correctness fix - it raises the floor on what a required layer control has to be, and adds no reader-facing capability | opt-out: which namespace the validator counts an id in has nothing for a viewer to see on a slide |
| CMH-VAL-27 | opt-out: an authoring-time validator correctness fix (the will-it-execute question is decided by the browser's per-namespace and per-type rule instead of the tag name); a reader of a document sees no new capability | opt-out: validator internals, with nothing for a viewer to see on a slide |
| CMH-VAL-28 | opt-out: an authoring-time validator correctness fix (the NonShareable companion lists count only a runtime script a browser would really run and a stylesheet link it would really apply, while the structural path checks keep walking every reference the document names); it refuses a document whose layer never loads and adds no reader-facing capability | opt-out: a validator refusal has nothing for a viewer to see on a slide |
| CMH-VAL-29 | opt-out: an authoring-time tokenizer correctness fix that REMOVES a false positive (a CDATA section's payload is character data); a reader of a document sees no new capability | opt-out: tokenizer internals, with nothing to show on a slide |
| CMH-SEC-06 | opt-out: an internal threat-model and review-scope declaration for maintainers and review panels, not a reader-facing behavior - it documents what the export deliberately does NOT promise, and the promises it bounds (the zero-network CSP, CMH-OFFLINE-05) are already surfaced by their own rows | opt-out: a non-goals statement has nothing for a viewer to see on a slide |
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
| CMH-THREAD-11 | opt-out: keyboard-focus robustness after a panel re-render, not a documented behavior | opt-out: focus-restoration robustness, nothing for a viewer to see on a slide |
| CMH-PICK-01 | help | deck |
| CMH-PICK-02 | help | deck |
| CMH-PICK-03 | help | deck |
| CMH-PICK-04 | help | opt-out: an agent-facing bundle-scope line and a change-section exclusion, nothing for a viewer to see on a slide |
| CMH-PICK-05 | help | deck |
| CMH-PICK-06 | help | deck |
| CMH-PICK-07 | help | opt-out: a transience-and-pruning invariant of the selection, with nothing to demonstrate on a slide |
| CMH-PICK-08 | help | deck |
| CMH-UI-12 | opt-out: click-target sizing of the already-documented Open comment bubble, no new capability | opt-out: control sizing, nothing to demonstrate on a slide |
| CMH-UI-13 | help | opt-out: a second entry point into the already-shown clear-all flow; the deck's own toolbar demo covers the overflow menu, and a destructive clear is not a slide to run live |
| CMH-UI-14 | opt-out: a timing repair to the already-documented tooltip layer (CMH-UI-05), restoring the tip a mid-animation focus used to lose; no new capability to document | opt-out: a tooltip-timing repair, nothing a viewer can see on a slide |
| CMH-AUTHOR-01 | tutorial, help | deck |
| CMH-AUTHOR-02 | tutorial, help | deck |
| CMH-AUTHOR-03 | opt-out: agent-facing Copy all attribution format and injection hardening | opt-out: agent-facing Copy all attribution format, not a deck topic |
| CMH-MMD-11 | opt-out: keyboard-accessibility parity (WCAG 2.1.1) for the already-documented diagram commenting, mirroring the image keyboard path; no new user-facing capability to document | opt-out: keyboard-accessibility parity for the already-shown diagram commenting, not a separate slide topic |
| CMH-SEARCH-08 | tutorial, help | deck |
| CMH-EXP-15 | opt-out: a transient confirmation toast on the already-documented export actions; not a separately documented capability | opt-out: a transient export-confirmation toast, nothing to demonstrate on a slide |
| CMH-SIDE-11 | tutorial, help | opt-out: sidebar More-menu grouping detail; the storage manager it houses is shown on the deck, but the menu grouping is not a slide topic |
| CMH-SIDE-12 | opt-out: responsive touch-target sizing for the already-documented Sort control; a mobile accessibility refinement, not a new user-facing capability | opt-out: responsive touch-target refinement, not a deck topic |
| CMH-SIDE-13 | tutorial, help | opt-out: a zone label appended to timestamps the deck panel already shows; it needs no slide of its own |
| CMH-MENU-PREF-10 | tutorial, help | opt-out: an in-runtime panel preference a reviewer sets in the More menu, not something a viewer needs shown on a slide |
| CMH-MENU-PREF-11 | tutorial, help | opt-out: the same timestamps re-labelled UTC; a slide would show a clock in a different zone, which is nothing to demonstrate |
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
| CMH-BUILD-29 | opt-out: a repository-hygiene invariant over the maintainer-only `dev/examples/` source directory (no build output beside the sources); the shipped examples, the site demos and the documents a reader opens are all byte-identical either way | opt-out: a build-output placement rule, with nothing a viewer can be shown |
| CMH-BUILD-28 | opt-out: maintainer recovery tooling for a red CI gate (adopting the drift artifact's PNGs as the committed baselines); documented in docs/testing-guidelines.md, not a reader-facing capability | opt-out: a build/CI tool, nothing a viewer can be shown |
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
| CMH-CONTENT-IO-01 | opt-out: an agent-facing authoring tool that makes the review loop cheaper; readers of a document see no new capability | opt-out: tooling for the agent side of the loop, with nothing to demonstrate on a slide |
| CMH-CONTENT-IO-02 | opt-out: an agent-facing authoring tool (atomic write-back); no reader-visible behavior change | opt-out: a transactional guarantee for tooling, not a deck topic |
| CMH-CONTENT-IO-03 | opt-out: an internal fidelity invariant (untouched sections keep their hashes); readers see no new capability | opt-out: an invariant with nothing to show on a slide |
| CMH-CONTENT-IO-04 | opt-out: an agent-facing export-reading format for the peer-review handoff | opt-out: agent-side tooling, already covered by the documented peer-review loop |
| CMH-BUILD-21 | opt-out: an internal CI gate over the spec-to-test mapping; a reader of a document sees no new capability | opt-out: a spec-hygiene gate, with nothing to show on a slide |
| CMH-BUILD-22 | opt-out: an internal drift guard over three egress lists; a reader of a document sees no new capability | opt-out: a cross-surface consistency guard, with nothing to show on a slide |
| CMH-BUILD-23 | opt-out: an internal source/build invariant over the runtime bundle (one declaration per name in the shared IIFE scope); a reader of a document sees no new capability | opt-out: a build-hygiene guard against a duplicated declaration, with nothing to show on a slide |
| CMH-BUILD-24 | opt-out: maintainer-only screenshot-capture tooling; a reader of a document sees no new capability, and the tutorial images it renders are unchanged | opt-out: a build-tooling invariant about how the capture routes a dependency, with nothing to show on a slide |
| CMH-BUILD-25 | opt-out: an internal supply-chain guard over the vendored mermaid bytes; a reader of a document sees no new capability, only the same library provably at the declared version | opt-out: a provenance guard over build inputs, with nothing to demonstrate on a slide |
| CMH-DECK-43 | opt-out: a deck-theme hover affordance a reviewer discovers by pointing at a cell; the same behavior the renamed row always described | deck |
| CMH-KQL-09 | opt-out: an internal dispatch unification; KQL blocks already rendered highlighted, so readers see no change | opt-out: an internal refactor with no visible behavior change |
| CMH-KQL-10 | site | opt-out: the deck's KQL slide already shows a runnable block; the fix is that the link stays correct after an edit, which a slide cannot show |
| CMH-HL-12 | opt-out: a validator hardening that catches malformed highlighting markup; not a reader-facing capability | opt-out: a validation guard, not a deck topic |
| CMH-HL-13 | opt-out: a gap fix in extension inference for an already-documented capability (diff syntax highlighting); no new reader-facing feature | opt-out: the deck already shows highlighted diffs; the fix is that more file types infer correctly |
| CMH-HL-14 | opt-out: a correctness fix to already-documented syntax highlighting (keyword coloring now matches the baked output); no new capability | opt-out: a tokenizer parity fix, not a deck topic |
| CMH-HL-15 | opt-out: a correctness fix to already-documented SQL highlighting (a double-quoted identifier now colors on both paths) | opt-out: a tokenizer parity fix, not a deck topic |
| CMH-BUILD-20 | opt-out: an internal performance refactor of the authoring pipeline; output is byte-identical so readers see no change | opt-out: an I/O refactor with nothing to demonstrate on a slide |
| CMH-SIZE-01 | site | opt-out: a size and file-layout optimisation with nothing to demonstrate on a slide - the viewer sees the same document, only smaller |
| CMH-SIZE-02 | opt-out: an authoring-time size optimisation - a checklist identity stored once and derived instead of repeated on every row; the reader opens the same document, only smaller | opt-out: an attribute the viewer never saw, with nothing to demonstrate on a slide |
| CMH-SIZE-03 | opt-out: a backwards-compatibility and fail-safe invariant for the trim above, plus the record of two transforms that were measured and deliberately not shipped - a document written before it opens, comments, exports and reopens exactly as it always did; no new reader-facing capability | opt-out: a compatibility invariant behind the actions the deck already demonstrates, with nothing for a viewer to see |
| CMH-SIZE-04 | opt-out: a maintainer-only measurement tool plus a recorded decision NOT to transform anything; a reader gets exactly the document they already got, so there is no capability to document | opt-out: a recorded non-change with nothing to demonstrate on a slide - the viewer sees the same document, byte for byte |
| CMH-OFFLINE-07 | opt-out: a bug fix to the already-documented Export Offline action - the reader gets the download the button always promised, so there is no new capability to document | opt-out: nothing to demonstrate on a slide - a re-exported deck or report renders exactly as the first export already did |
| CMH-OFFLINE-08 | opt-out: a security and licensing-compliance hardening of the already-documented Export Offline action - a reader gets the same offline file from the same button, so there is no new capability to document | opt-out: an export-trust hardening with nothing to demonstrate on a slide - the exported deck renders exactly as it already did |
| CMH-OFFLINE-10 | opt-out: an authoring-time validator gate that mirrors an existing offline export strip; a reader gets the same offline file from the same button, and the rule only tells an author writing an offline document by hand what the export would have changed anyway | opt-out: a validator/strip parity gate with nothing to demonstrate on a slide - the exported deck navigates exactly as it already did |
| CMH-OFFLINE-06 | opt-out: a size correctness fix to the already-documented Offline export; the reader gets the same offline file, only without a library it never called, so there is no new capability to document | opt-out: an export-size optimisation with nothing to demonstrate on a slide - the exported charts render exactly as they already did |
| CMH-OFFLINE-09 | opt-out: an internal consistency fix that makes the runtime and the strict validator read one contradictory document shape the same way; the shape is only reachable by hand-authoring a reserved layer attribute, so a reader has no new capability to learn | opt-out: a validator and mode-resolution invariant with nothing to demonstrate on a slide - every legitimate document keeps the badge and the export it already had |
| CMH-RESP-10 | opt-out: a rendering-correctness fix; a reader sees a table that is no longer broken, with nothing new to learn | opt-out: a layout fix with nothing to demonstrate on a slide |
| CMH-RESP-11 | opt-out: a layout-containment fix; a wide table scrolls in its box exactly as it already did on a phone, so there is no new capability to document | opt-out: a layout fix with nothing to demonstrate on a slide |
| CMH-RESP-12 | opt-out: a placement-correctness fix to floating controls that already promised to respect a clipped container (CMH-RESP-02); the reader sees a bubble that no longer strays over unrelated content, with nothing new to learn or do | opt-out: a placement fix with nothing to demonstrate on a slide - the control behaves exactly as a viewer already expects it to |
| CMH-RESP-13 | opt-out: a mobile touch-target sizing invariant for composers the tutorial and help already document - the reviewer sees the same Cancel / Save row, only large enough to hit with a thumb | opt-out: control sizing on a phone, with nothing new to demonstrate on a slide |
| CMH-RESP-14 | opt-out: a mobile touch-target sizing invariant for a Reply button and an identity row the tutorial and help already document - the reviewer sees the same controls, only large enough to hit with a thumb | opt-out: control sizing on a phone, with nothing new to demonstrate on a slide |
| CMH-RESP-15 | opt-out: a mobile touch-target sizing invariant for a search row, two dropdown menus and a card action the tutorial and help already document - the reviewer sees the same controls, only large enough to hit with a thumb | opt-out: control sizing on a phone, with nothing new to demonstrate on a slide |
| CMH-RESP-16 | opt-out: a layout-containment fix for the side pane on a landscape phone; the reviewer sees the same header and the same comment list, only with the list no longer pushed off the bottom, so there is no new capability to document | opt-out: a phone layout fix with nothing to demonstrate on a slide - a deck slide is not viewed in the side pane's 320px-tall failure case |
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
| CMH-IMG-08 | tutorial, site, help | opt-out: the deck's evidence slide already demonstrates commenting on a whole visual (its chart and image anchors); an inline SVG figure is the same interaction on another media type, so a viewer sees nothing new on a slide |
| CMH-IMG-09 | opt-out: an anchor-resolution robustness invariant - a reader sees a comment stay on the right figure, or no ring at all, with no new capability to learn | opt-out: an anchoring invariant with nothing to demonstrate on a slide |
| CMH-IMG-10 | opt-out: a write-side sanitization invariant for stored media metadata; a reader sees the same card and bundle, only guaranteed inert | opt-out: a security hardening invariant, not something a viewer needs shown on a slide |
| CMH-IMG-11 | opt-out: an anchor-resolution robustness invariant carried in an internal field a reader never sees; the authoring guidance it changes lives in the skill's own `references/images-commentable.md`, not in a reader-facing surface | opt-out: an anchoring invariant with nothing to demonstrate on a slide - the comment simply stays on the figure it was left on |
| CMH-DEMO-08 | opt-out: shipped demo content (an inline SVG figure in the visuals-matrix report) that exercises the documented inline-SVG anchor (CMH-IMG-08), not a separately documented capability | opt-out: demo-report content; the deck's evidence slide already shows commenting on a whole visual |
| CMH-CORE-18 | opt-out: a viewport-fit robustness invariant for a dialog the tutorial and help already document; the reviewer sees the same dialog, only never cut off | opt-out: an internal layout invariant - a short-viewport clamp shows a deck viewer nothing new |
| CMH-CORE-19 | opt-out: a placement invariant for affordances the tutorial and help already document - the hover bubble, dialog, and composer behave exactly as before, they just measure what is actually on screen so a soft keyboard or a pinch zoom cannot hide them | opt-out: an on-screen-fit invariant - a deck viewer sees the same controls, and a mobile on-screen keyboard cannot be demonstrated on a slide |
| CMH-CORE-20 | opt-out: a scroll-stability invariant for the composer the tutorial and help already document - the reviewer sees the same composer over the same selection, only the page no longer jumps out from under it | opt-out: the absence of a jump is not something a slide can show - a deck viewer sees the same composer opening on the same text |
| CMH-CORE-21 | opt-out: a robustness invariant for controls the tutorial, site, and help already document - a reviewer sees the same sort control, caret, review badge, and "Reset moves", they just cannot be suppressed by author markup that happens to reuse their class names | opt-out: a document-integrity invariant with nothing to demonstrate on a slide - a viewer sees the same controls working, which is exactly what they saw before |
| CMH-CORE-22 | help | opt-out: the deck's own slides carry live demo comments, and the only way to demonstrate this action is to destroy one of them behind a browser confirm; the dialog the deck already shows is the same dialog, with one more button in its row |
| CMH-CORE-23 | opt-out: a touch-target sizing invariant for a dialog the tutorial and help already document - the reviewer sees the same Delete / Edit / Close and Cancel / Save row, only large enough to hit with a thumb | opt-out: control sizing on a phone, with nothing new to demonstrate on a slide |
| CMH-CORE-24 | opt-out: a render-determinism fix for a decorative affordance the tutorial and help already show - the reviewer sees the same drag grip on the same handle, drawn instead of typeset, and drags the composer exactly as before | opt-out: no tutorial, site, help or deck copy describes the grip's shape, so the redrawn dots change nothing a slide would say; the deck's own slides already carry the composer this grip sits on |
| CMH-PORT-05 | tutorial, site, help | deck |
| CMH-PORT-06 | opt-out: a compatibility guarantee - an existing document simply keeps validating, with nothing new for a reader to learn | opt-out: the viewer sees an old document continuing to work, which is not a slide |
| CMH-PORT-07 | opt-out: an internal compatibility shim for already-shipped document markup; a reader sees no new capability | opt-out: a compatibility invariant with nothing to demonstrate on a slide |
| CMH-PORT-08 | opt-out: build/authoring tooling detail (how a tool locates its template); not reader-facing | opt-out: a tooling detail with nothing to demonstrate on a slide |
| CMH-PORT-09 | opt-out: a deprecated-alias guarantee for the agent-facing CLI; the reader-facing docs name only the current spelling | opt-out: a CLI alias with nothing to demonstrate on a slide |
| CMH-PRINT-08 | opt-out: a print-fidelity invariant - the printed diagram simply looks right; the on-screen scroll cue is unchanged, so there is nothing new for a reader to learn or do | opt-out: print/PDF fidelity, not something a viewer needs shown on a slide |
| CMH-PRINT-09 | opt-out: a print-layout correctness fix - a tall-narrow diagram simply fills the printable column the way it already fills the reading column on screen, instead of printing as a sliver; there is nothing new for a reader to learn or do | opt-out: print/PDF page-fit correctness, not something a viewer needs shown on a slide |
| CMH-GROW-01 | help | opt-out: the editors simply size themselves to the draft; every commenting slide already shows the editors, and growth is felt while typing rather than shown on a slide |
| CMH-GROW-02 | help | opt-out: a sizing bound and a manual-override invariant for an editor the deck already demonstrates |
| CMH-GROW-03 | opt-out: a readability fix - the reply box is simply rendered at the same size as everything around it; there is no new capability to document | opt-out: a font-size parity fix, not something a viewer needs shown on a slide |
| CMH-EXP-16 | opt-out: an internal export-integrity invariant - the block is resolved structurally instead of by a text scan, so a broken document fails loudly rather than exporting a corrupted runtime; no new reader-facing capability | opt-out: an internal integrity guard on the already-shown export actions, nothing to demonstrate on a slide |
| CMH-REVIEW-16 | opt-out: an internal data-integrity invariant - the review state is simply read from and written to the block that owns it; a reader gains no new capability and the failure it prevents is a malformed document | opt-out: a decoy-shadowing guard with nothing to demonstrate on a slide |
| CMH-EXP-17 | opt-out: an internal export-integrity invariant - which element is the layer's own block is decided by the content-root boundary instead of document position; no new reader-facing capability | opt-out: a resolution rule behind the already-shown export actions, with nothing visible to demonstrate on a slide |
| CMH-EXP-18 | opt-out: an internal export-integrity invariant - no reserved descriptor copy survives an export disagreeing with the mode it declares; no new reader-facing capability | opt-out: a descriptor-consistency guard tooling reads, not something a viewer sees on a slide |
| CMH-EXP-19 | opt-out: a recorded scope boundary - Shareable deliberately does NOT neutralize a reserved-id decoy the way Offline does, because it makes no zero-network promise and preserves author scripts; a stated non-behavior, not a capability | opt-out: a deliberate non-behavior; there is nothing to show on a slide |
| CMH-EXP-20 | opt-out: an internal data-integrity invariant - one recorded ownership rule for the layer's own blocks, plus a report for a duplicate the reader would otherwise never hear about; a reader of a well-formed document gains no new capability | opt-out: a resolution rule (and a warning about a malformed file) behind the already-shown export actions, with nothing to demonstrate on a slide |
| CMH-EXP-21 | opt-out: a diagnostic wording fix on an existing export failure - the Plain export names the block that survived and where it sat instead of guessing "malformed markers"; the export itself is unchanged | opt-out: an error message only a malformed document ever sees, with nothing to demonstrate on a slide |
| CMH-EXP-22 | opt-out: an export-integrity guard on an existing abort path - the runtime refuses a region marker a browser does not read as a boundary, matching the validator; a reader of a well-formed document sees no change at all | opt-out: a refusal only a damaged document ever reaches, with nothing to demonstrate on a slide |
| CMH-EXP-23 | opt-out: an error message on an existing failure path - an export that already failed now says it failed instead of ending in silence; the export itself is unchanged and a reader of a healthy document never sees it | opt-out: a failure toast only a broken export ever produces, with nothing to demonstrate on a slide |
| CMH-EXP-24 | opt-out: an export-fidelity invariant on the existing export paths - a CR the author already wrote simply stops being downgraded to LF on the round trip; a reader gains no new capability and sees no new control | opt-out: a byte-level round-trip invariant behind the export actions the deck already demonstrates, with nothing a viewer could see on a slide |
| CMH-VAL-22 | opt-out: an authoring-time and runtime correctness invariant - the four copies of the region-marker rule are pinned to one canonical answer, so a document cannot be counted one way by the validator and another by the runtime; no reader-facing capability | opt-out: a cross-implementation parity guard, with nothing for a viewer to see on a slide |
| CMH-PKG-15 | opt-out: internal build-tooling hardening of the skill-resources packager - a cross-platform extraction-collision guard and the removal of a compression level the writer never applied; no reader-facing capability | opt-out: a maintainer-side packaging guard, with nothing for a viewer to see on a slide |
| CMH-CONTENT-20 | opt-out: an internal text-neutrality invariant for the existing sort - a reader gains no new capability; it only stops a sorted table from falsely raising the not-validated banner or flipping a reviewed section to changed | opt-out: a whitespace-preservation invariant behind the table sorting the deck already demonstrates, with nothing new to show on a slide |
| CMH-REVIEW-17 | opt-out: a correctness invariant on the existing review badge - a sorted table simply stops flipping a reviewed section to changed; there is no new capability for a reader to learn | opt-out: an invariant behind the review badges the deck already demonstrates, with nothing new to show on a slide |
| CMH-MENU-PREF-01 | help | opt-out: an in-runtime panel preference a reviewer sets in the More menu, not something a viewer needs shown on a slide |
| CMH-MENU-PREF-02 | help | opt-out: the absence of an auto-open is invisible on a slide; the deck already demonstrates commenting itself |
| CMH-MENU-PREF-03 | help | opt-out: a storage-scope detail behind the preference, with nothing for a viewer to see on a slide |
| CMH-MENU-PREF-04 | help | opt-out: a per-document scope detail behind the preference, with nothing for a viewer to see on a slide |
| CMH-MENU-PREF-05 | opt-out: keyboard and roving-focus a11y of the menu rows, not a capability a reader has to be taught | opt-out: menu keyboard behavior, with nothing for a viewer to see on a slide |
| CMH-MENU-PREF-06 | opt-out: private-mode robustness of the preference reads and writes, not a reader-facing capability | opt-out: a storage-denied robustness invariant, with nothing for a viewer to see on a slide |
| CMH-MENU-PREF-07 | help | opt-out: the deck runtime simply honors the same preference; a slide would show the panel NOT opening, which is nothing to see |
| CMH-MENU-PREF-08 | help | opt-out: the panel simply not opening itself on load or on a first note/checklist change; there is nothing for a viewer to see on a slide |
| CMH-MENU-PREF-09 | opt-out: storage-accounting registration behind the preference, not a reader-facing capability | opt-out: a storage-reclaim invariant, with nothing for a viewer to see on a slide |
| CMH-CONTENT-21 | opt-out: an internal robustness invariant - the audit that closed the stranded-authored-text class plus the shared slot-permutation guard behind it; a reader gains no capability, they simply never see a false not-validated banner or a spuriously changed section | opt-out: a whitespace-preservation and DOM-integrity invariant behind features the deck already demonstrates, with nothing new to show on a slide |
| CMH-TOOL-22 | opt-out: internal hardening of the authoring tools (a crash-safe write-back and the static guard behind it); the tools take the same arguments and produce the same output, so a reader gains no capability - they simply cannot lose a document to a failed write | opt-out: a write-safety invariant of the command-line tools, with nothing for a viewer to see on a slide |
| CMH-TOOL-23 | opt-out: internal hardening of the authoring tools (a write target that resolves to a file the tool read is refused); the tools take the same arguments and produce the same output, so a reader gains no capability - they simply cannot lose the file they passed in | opt-out: a write-safety invariant of the command-line tools, with nothing for a viewer to see on a slide |
| CMH-MMD-12 | opt-out: an internal render-fidelity invariant - the runtime verifies mermaid's own output and repairs a bad render; a reader gains no capability, they simply never see a diagram with clipped labels or stranded blank space | opt-out: a render-correctness invariant behind the diagram support the deck already demonstrates; a correct diagram is what a viewer already expects to see |
| CMH-TOC-11 | help | opt-out: the numbering and indentation of the section menu are sidebar chrome a reader meets in a real multi-level report, not something a showcase slide can demonstrate |
| CMH-MENU-ICON-04 | help | opt-out: the floating toolbar this mark lives in is hidden wholesale in deck mode, so the mark cannot appear on a slide; it is a one-click route to the project page from a report's chrome, which a slide would not demonstrate |
| CMH-MENU-ICON-02 | help | opt-out: same mark in the overflow menu, and that menu belongs to the toolbar deck mode hides wholesale, so it cannot appear on a slide |
| CMH-BUILD-26 | opt-out: build tooling - the strip runs at build time and the runtime behaves identically; the readable source stays in the repo, and the only reader-visible consequence is a smaller file, which is not a capability to document | opt-out: a build-time byte transform with nothing for a viewer to see on a slide |
| CMH-BUILD-27 | opt-out: a maintainer-facing CI gate on the size of the generated components; a reader gains no capability and there is nothing on screen | opt-out: a build gate, not a demonstrable behavior |
| CMH-COLD-01 | opt-out: an on-disk packaging optimisation; what a reader sees is unchanged by design | opt-out: the guarantee is that nothing changes on screen, so there is nothing to show on a slide |
| CMH-COLD-02 | opt-out: authoring-tool round-trip invariant | opt-out: build/authoring tooling |
| CMH-COLD-03 | opt-out: generated document layout, addressed to machine readers rather than reviewers | opt-out: file-layout detail with nothing to demonstrate |
| CMH-COLD-04 | opt-out: internal load-order invariant; the visible result is a document identical to the uncompressed one | opt-out: an invariant whose whole point is that a viewer cannot tell |
| CMH-COLD-05 | opt-out: a backwards-compatibility implementation choice inside the loader | opt-out: not user-facing |
| CMH-COLD-06 | opt-out: a degraded-path notice; the document explains itself in its own text and the toast is a diagnostic, not a capability a reader has to learn | opt-out: a degraded-path notice a viewer should never meet |
| CMH-COLD-07 | opt-out: a no-JS fallback the document explains in its own text | opt-out: the explanation ships in the document itself |
| CMH-COLD-08 | opt-out: an authoring-pipeline flag, not a reviewer-facing behavior | opt-out: build/authoring tooling |
| CMH-COLD-09 | opt-out: a development measurement harness and its recorded result; nothing a reader of a document meets | opt-out: a load-time measurement, not a capability to demonstrate |
| CMH-COLD-10 | opt-out: a packaging threshold inside an opt-in authoring flag; no shipped document changes | opt-out: build/authoring tooling, and the guarantee is that nothing on screen changes |
| CMH-SIZE-05 | opt-out: a source-order change with no new reader-facing capability - the rendered document, its chrome and every interaction are identical by design (that is the acceptance criterion); what changed is which bytes a MACHINE reading the raw file meets first | opt-out: nothing to demonstrate on a slide - the viewer sees exactly the same document |
| CMH-SIZE-06 | opt-out: delimiter comments in the raw file for a machine reader; a human opening the document sees nothing at all | opt-out: an in-file annotation with nothing on screen |
| CMH-SIZE-07 | opt-out: a load-order robustness guard whose whole promise is that the reader notices no difference; there is no capability to document | opt-out: an invisible first-paint guard - a slide could only show an unchanged page |
| CMH-SIZE-08 | help | opt-out: the deck already demonstrates Export Offline and the exported deck is unchanged; what changed is that the bytes arrive over the wire once during the export itself, which a slide cannot show |
| CMH-SIZE-09 | opt-out: an example-content and size correction. It is NOT purely "the same document, only smaller": those two examples were self-contained for charts and now load the library from a pinned CDN, so opened with no network their charts are blank (the prose, canvases, captions and comment layer are all intact, and Export Offline still produces a chart-bearing file that needs no network). That is a property of two demo documents rather than a capability a reader of the docs needs told about, so it is recorded in the spec row instead | opt-out: nothing to demonstrate on a slide; the deck already shows charts, and what changed is where their library comes from |
