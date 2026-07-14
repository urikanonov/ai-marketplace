# commentable-html JS modules

The runtime ships as `NN-topic.js` partials in this directory. `build.py` assembles them by
DIRECTORY SORT (numeric prefix) into one artifact; the sort order is the single-IIFE statement
order, so it is load-bearing. Edit the owning partial - never recreate a `commentable-html.js`
monolith (a test enforces its absence). This map ties each module to the SPEC feature-id areas it
implements; `tests/test_module_coverage.py` checks every partial is listed here and every listed
area is a real, test-backed area in `dev/SPEC.md`.

Conventions for these partials (they share ONE closure scope after concatenation):
- Cross-module functions are `function` declarations (hoisted), never `const fn = () =>` (a `const`
  is not hoisted and would throw a load-time ReferenceError across modules).
- The FIRST partial (`00-preamble.js`) must stay first: it captures `SNAPSHOT_HTML` and
  `document.currentScript` before any DOM access, and opens the IIFE. The LAST partial
  (`95-startup.js`) closes the IIFE and runs startup. Do not reorder these two.
- Shared infrastructure used across modules: `widgetStateChanges` (35-widgets), and the export
  primitives `SNAPSHOT_HTML` / `CMH_LAYER_SCRIPT` / `CMH_INJECTED_CHROME` / `_stripTransientBodyClasses`
  / `_snapshotWithTail` (65-export-portable) are consumed by later export modules - move with care.

| Module | SPEC areas | Purpose |
| --- | --- | --- |
| `00-preamble.js` | CMH-CORE, CMH-EXP | IIFE opener; captures `SNAPSHOT_HTML` and `document.currentScript` before any DOM access. |
| `01-config.js` | CMH-CORE, CMH-FWDCOMPAT | Auto-discovered config; declares `CMH_VERSION` (build.py stamps it). |
| `05-persistence.js` | CMH-PERSIST, CMH-EXP | localStorage load/merge/save of the comments array. |
| `10-offsets.js` | CMH-CORE, CMH-TEXT | Text-offset anchoring helpers. |
| `15-context.js` | CMH-CORE, CMH-COPY | Section + surrounding-text context capture. |
| `20-mermaid.js` | CMH-MMD, CMH-MMDLOAD | Mermaid diagram commenting layer. |
| `25-diff.js` | CMH-DIFF | Unified-diff / code-review rendering and anchoring. |
| `26-highlight.js` | CMH-DIFF, CMH-HL, CMH-TOOL | In-page diff syntax highlighter (`cmhHighlightCode`) and the runtime fallback that highlights un-highlighted prose code blocks (`highlightCodeBlocks`). |
| `30-images.js` | CMH-IMG, CMH-CHART | Image and chart-canvas comment layer. |
| `35-widgets.js` | CMH-WIDGET | Commentable widgets / SVG nodes; `widgetStateChanges` infra. |
| `36-checklist.js` | CMH-CHECK | Layered checklist: four-state items, aggregation, minimal persistence, per-list state card, export bake. |
| `40-doc-comments.js` | CMH-DOCCMT | Document-wide comments. |
| `41-selection.js` | CMH-SEL, CMH-CORE | Selection handling and the add-comment popup. |
| `45-composer.js` | CMH-A11Y, CMH-CORE | Per-instance comment composer (parallel-safe). |
| `50-sidebar.js` | CMH-SIDE | Sidebar rendering. |
| `51-comment-search.js` | CMH-SEARCH | Comment search / filter row: case-insensitive filter of the rendered cards, shown/total count, clear button. |
| `52-hover-bubble.js` | CMH-CORE | Hover bubble to open a comment. |
| `54-sidebar-toggle.js` | CMH-SIDE, CMH-A11Y | Sidebar open/close. |
| `55-toolbar-menu.js` | CMH-MENU, CMH-UI | Toolbar overflow menu. |
| `56-copy-clear.js` | CMH-COPY | Copy all + Clear all. |
| `60-export-markdown.js` | CMH-MD | Export to Markdown. |
| `62-sortable-tables.js` | CMH-CONTENT | Sortable tables. |
| `65-export-portable.js` | CMH-EXP | Export as Portable + shared export snapshot primitives. |
| `66-export-plain.js` | CMH-EXP | Save as plain HTML (strip the comment layer). |
| `67-export-standalone.js` | CMH-MODE | Export standalone (nonportable -> single file). |
| `68-export-offline.js` | CMH-OFFLINE | Export Offline (portable + rich-content snapshots). |
| `70-mode-badge.js` | CMH-MODE | Mode badge + asset-version handshake. |
| `75-help.js` | CMH-HELP, CMH-A11Y | Help dialog. |
| `80-sort-comments.js` | CMH-SIDE | Sort comments by time. |
| `82-toc.js` | CMH-TOC | Table-of-contents side menu. |
| `90-toast.js` | CMH-A11Y | Toast notifications. |
| `95-startup.js` | CMH-HANDLED, CMH-EXP | Handled-id pruning; startup; closes the IIFE. |
