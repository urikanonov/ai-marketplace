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
| CMH-DECK-SHOWCASE-19 | site | deck |
