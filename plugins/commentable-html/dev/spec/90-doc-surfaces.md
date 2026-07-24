## Doc-surface coverage (feature visibility)

Every user-facing feature must be discoverable from at least one documentation SURFACE, and every new
feature must declare where it is surfaced (or opt out) in the same pull request. The three surfaces are:

- `tutorial` - the guided walkthrough in `docs/TUTORIAL.md` (the site tutorial page is generated from it).
- `site` - the marketplace pages under `site/pages/commentable-html` (a highlights page, not exhaustive).
- `help` - the in-runtime Help/About panel (`dev/assets/js/75-help.js`).

Governance rule (enforced): when a pull request adds a NEW feature-id row to this spec, it must also add
a row for that id to the "Doc-surface registry" table below whose value is either one or more surfaces
(a comma-separated subset of `tutorial`, `site`, `help`) OR `opt-out: <reason>` for a change that is not
user-facing (internal hardening, build/authoring tooling, a robustness invariant, a security guard, an
agent-facing export format, etc.). `scripts/check_doc_surfaces.py` fails a PR whose newly added feature
ids lack a registry entry, and fails if a registry row names an id that no longer exists. Prefer a real
surface; use `opt-out` only when the behavior is genuinely not something a reader needs documented.

### Coverage matrix (by area)

A human summary of where each major user-facing area is surfaced today. Internal / tooling / hardening
areas are surfaced as `opt-out` in the registry and omitted here.

| Area | Surfaced in |
| --- | --- |
| Leaving and managing comments (CORE, NOTE editing, SIDE) | tutorial, site, help |
| Rich content: charts, KQL, code, diffs, mermaid, images (CHART, KQL, CODE, DIFF, MMD, IMG) | tutorial, site, help |
| Rich-text comment formatting (RICH) | tutorial, help |
| Review checklists (CHECK) | tutorial, help |
| Section review badges and the section menu / search / filter (REVIEW, TOC, SEARCH) | tutorial, help |
| Threads, inline replies, and author names (THREAD, AUTHOR) | tutorial, help |
| Counting note and checklist changes in the badge (NOTE-04, CHECK-06) | tutorial, help |
| Copy all and sending comments to an agent (COPY, HANDLED) | tutorial, help |
| Exports: Portable, Offline, Plain HTML, Markdown, Save as PDF (EXP, OFFLINE, PRINT) | tutorial, site, help |
| Storage manager, pie-chart breakdown, and per-document browsing (STORE) | tutorial, help |
| Board and deck document kinds (BOARD, DECK, MODE) | tutorial (board), site (deck), help (board) |
| Portability / offline badge and privacy (PKG-portability, PRIVACY) | tutorial, site, help |
| Commentable widgets and SVG nodes (WIDGET) | help |

### Doc-surface registry

Machine-checked by `scripts/check_doc_surfaces.py`. Each new feature-id row above must add a matching
entry here. A `Doc surface` value is a comma-separated subset of `tutorial`, `site`, `help`, or
`opt-out: <reason>`.

| Feature id | Doc surface |
| --- | --- |
| CMH-HELP-COUNT-01 | help |
| CMH-HELP-THREADS-01 | help |
| CMH-HELP-STORE-01 | help |
| CMH-STORE-13 | tutorial, help |
| CMH-STORE-14 | tutorial, help |
| CMH-STORE-15 | tutorial, help |
| CMH-NOTE-04 | tutorial, help |
| CMH-NOTE-05 | tutorial |
| CMH-CHECK-06 | tutorial, help |
| CMH-THREAD-01 | tutorial, help |
| CMH-THREAD-06 | tutorial, help |
| CMH-THREAD-07 | help |
| CMH-THREAD-08 | help |
| CMH-THREAD-09 | opt-out: internal draft-preservation robustness, not separately documented |
| CMH-AUTHOR-01 | tutorial, help |
| CMH-AUTHOR-02 | tutorial, help |
| CMH-AUTHOR-03 | opt-out: agent-facing Copy all attribution format and injection hardening |
| CMH-MMD-11 | opt-out: keyboard-accessibility parity (WCAG 2.1.1) for the already-documented diagram commenting, mirroring the image keyboard path; no new user-facing capability to document |
