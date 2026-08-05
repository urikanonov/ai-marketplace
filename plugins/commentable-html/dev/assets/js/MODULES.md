# commentable-html JS modules

The runtime ships as `NN-topic.js` partials in this directory. `build.py` assembles them by
DIRECTORY SORT (numeric prefix) into one artifact; the sort order is the single-IIFE statement
order, so it is load-bearing. Edit the owning partial - never recreate a `commentable-html.js`
monolith (a test enforces its absence). This map ties each module to the SPEC feature-id areas it
implements; `tests/test_module_coverage.py` checks every partial is listed here exactly once, in
this same directory-sort order, and that every listed area is a real, test-backed area in
`dev/SPEC.md`. The sort is Python `sorted()` BYTE order, not numeric-then-intuition: `-` (0x2D)
sorts before `.` (0x2E), so a future `26-highlight-md.js` would sort BEFORE `26-highlight.js`. Keep
the rows in the order the directory listing gives.

Conventions for these partials (they share ONE closure scope after concatenation):
- Cross-module functions are `function` declarations (hoisted), never `const fn = () =>` (a `const`
  is not hoisted and would throw a load-time ReferenceError across modules).
- The FIRST partial (`00-preamble.js`) must stay first: it captures `SNAPSHOT_HTML` and
  `document.currentScript` before any DOM access, and opens the IIFE. The LAST partial
  (`95-startup.js`) closes the IIFE and runs startup. Do not reorder these two.
- Shared infrastructure used across modules: the content-root boundary helpers `cmhContentRootState` /
  `cmhContentRoot` / `cmhLayerIdOwners` / `cmhLayerBlocks` / `cmhLayerBlock` and the reserved-block
  reader `cmhReadLayerBlock` (which diagnoses "nothing resolved" and "more than one resolved" in one
  place, CMH-EXP-20) (`01-config.js`),
  the rich-content selector vocabulary (`03-selectors.js`),
  the viewport vocabulary (`04-viewport.js`),
  the layer-chrome identity registry `cmhMarkLayerChrome` / `cmhClickHitsLayerChrome` (`00-preamble.js`),
  which every module that injects an interactive control INSIDE the content root registers its
  control with, and the comment dialog's outside-click swallow reads,
  `widgetStateChanges` (35-widgets), and the export
  primitives `SNAPSHOT_HTML` / `CMH_LAYER_SCRIPT` / `CMH_INJECTED_CHROME` / `_stripTransientBodyClasses`
  / `_snapshotWithTail` (65-export-shareable) are consumed by later export modules - move with care.
  One dependency runs the OTHER way: `_cmhIsInertDataScript` (65-export-shareable) calls
  `_offlineIsRunnableScriptType` (68-export-offline), the single HTML "JavaScript MIME type" test, so
  the descriptor retarget and the offline strips can never disagree about what would run. It is legal
  because the partials share one hoisted IIFE scope, but move either one with that pairing in mind.
  One dependency runs the OTHER way: `_cmhIsInertDataScript` (65-export-shareable) calls
  `_offlineIsRunnableScriptType` (68-export-offline), the single HTML "JavaScript MIME type" test, so
  the descriptor retarget and the offline strips can never disagree about what would run. It is legal
  because the partials share one hoisted IIFE scope, but move either one with that pairing in mind.

| Module | SPEC areas | Purpose |
| --- | --- | --- |
| `00-preamble.js` | CMH-CORE, CMH-EXP, CMH-CONTENT, CMH-VAL | IIFE opener; captures `SNAPSHOT_HTML` and `document.currentScript` before any DOM access, preserves serializable declarative shadow roots in that snapshot, declares the layer-chrome identity registry (`cmhMarkLayerChrome` / `cmhClickHitsLayerChrome`), and owns the SINGLE copy of the authored-text-preserving slot permutation (`cmhPermuteChildrenInSlots` writer / `cmhPermutedChildNodes` reader, CMH-CONTENT-21) plus `CMH_HASH_EXCLUDED`, the by-construction identity set the content-hash scan honors (kept SEPARATE from the heuristic `CMH_INJECTED_CHROME` export-tail set, where an over-capture is harmless but here would silently subtract document text). Any pass that reorders element children inside `#commentRoot` must go through them - appending instead strands the whitespace between the elements and drifts the content hashes. |
| `01-config.js` | CMH-CORE, CMH-FWDCOMPAT, CMH-DENSITY, CMH-SEC, CMH-EXP | Auto-discovered config; declares `CMH_VERSION` (build.py stamps it) and the content-root boundary helpers (`cmhContentRootState`, `cmhContentRoot`, `cmhLayerIdOwners`, `cmhLayerBlocks`, `cmhLayerBlock`, `cmhReadLayerBlock`, `cmhWarnUnresolvedBlock`, `cmhWarnAmbiguousBlock`) every reader and exporter resolves the layer's own reserved data blocks through. |
| `02-lzstring.js` | CMH-STORE | Vendored lz-string (trimmed `compressToUTF16`/`decompressFromUTF16`, bounded decode) used to pack the comment store. |
| `03-selectors.js` | CMH-CHART, CMH-MMD, CMH-OFFLINE, CMH-PRINT | The one shared rich-content selector vocabulary (`CMH_MERMAID_SEL`, `CMH_CHART_DATA_SEL`, `CMH_CHART_CANVAS_SEL`, `CMH_RICH_CONTENT_SEL`) the chart renderer, the image layer, the Offline exporter, the print/measure cap in `83-print.js`, and the author-time payload detector all derive from. |
| `04-viewport.js` | CMH-CORE | The one shared VIEWPORT vocabulary (`cmhViewportBox`, `cmhViewportRect`, `cmhOnViewportChange`): every floating affordance measures the VISUAL viewport through these and subscribes to its `resize`/`scroll` here, so an on-screen keyboard or a pinch zoom cannot leave one of them off screen. Also hosts the shared SCROLL GUARD (`cmhBeginScrollGuard`), which keeps the browser's scroll anchoring from moving the document out from under a surface being opened. |
| `05-persistence.js` | CMH-PERSIST, CMH-STORE, CMH-EXP | localStorage load/merge/save of the comments array; sync compression codec + quota-aware write helpers. |
| `06-preferences.js` | CMH-MENU-PREF | Scoped reviewer preferences: the cross-document default and the per-document override behind "Auto-open panel on comment", each read/written through a try/catch guard. |
| `10-offsets.js` | CMH-CORE, CMH-TEXT | Text-offset anchoring helpers. |
| `15-context.js` | CMH-CORE, CMH-COPY, CMH-CTX | Section + surrounding-text context capture. |
| `20-mermaid.js` | CMH-MMD, CMH-MMDLOAD, CMH-DECK, CMH-ANCHOR | Mermaid diagram commenting layer; deck diagram contain-fit sizing; hosts the shared `setActiveAdd()` single-affordance sentinel for all structural-anchor layers. |
| `25-diff.js` | CMH-DIFF | Unified-diff / code-review rendering and anchoring. |
| `26-highlight.js` | CMH-DIFF, CMH-HL, CMH-TOOL | In-page diff syntax highlighter (`cmhHighlightCode`), the dedicated Markdown tokenizer (`cmhHighlightMarkdown`), and the runtime fallback that highlights un-highlighted prose code blocks (`highlightCodeBlocks`). |
| `30-images.js` | CMH-IMG, CMH-CHART | Image and chart-canvas comment layer. |
| `31-links.js` | CMH-LINK | Author-facing link layer: render-time new-tab stamping + per-link commenting. |
| `35-widgets.js` | CMH-WIDGET, CMH-STATE | Commentable widgets / SVG nodes; `widgetStateChanges` infra. |
| `36-checklist.js` | CMH-CHECK | Layered checklist: four-state items, aggregation, minimal persistence, per-list state card, export bake. |
| `37-notes.js` | CMH-NOTE | Editable notes fields: textarea upgrade, canonical delta persistence, per-note change card, single/multi-line toggle, export bake. |
| `38-validation-banner.js` | CMH-STAMP | Unvalidated-document fallback banner: shown when a document carries a created stamp but no current validated stamp. |
| `39-callout.js` | CMH-CALLOUT | Callout accessibility: role="note" + variant aria-label (suppressed when an authored leading strong label exists); pairs with the per-variant ::before glyph in 50-content.css. |
| `40-doc-comments.js` | CMH-DOCCMT | Document-wide comments: the `openDocumentComposer` / `openSlideComposer` composer factories and deck slide-meta capture (the menu entry that reaches them lives in `41-selection.js`). |
| `41-selection.js` | CMH-SEL, CMH-CORE, CMH-RICH, CMH-A11Y, CMH-DECK, CMH-DOCCMT | Selection handling and the add-comment popup (desktop `mouseup` and the coarse-pointer `selectionchange` path); keeps the add-comment menu above open composers; owns the `#contextMenu` ARIA menu (roving focus, Escape focus restore) and the shared `__cmhRegisterEscapePopup` stack; routes the deck slide-scoped and document/deck-wide comment entries and honors the deck comments-off state. |
| `42-autogrow.js` | CMH-GROW | Autogrowing authoring textareas: sizes the composer, side-pane inline reply/edit, and in-document dialog editors to their content (capped by each one's `--cmh-grow-max`, enforced here rather than as a CSS `max-height` so a manual drag stays free), re-measures on viewport changes, and yields to a manual resize drag. |
| `43-identity.js` | CMH-AUTHOR | Reviewer identity: per-browser author name (localStorage, seedable via `data-cm-author`), the author pill, and the sidebar identity control (editable, future-comments only). |
| `43-rich-text.js` | CMH-RICH | Rich-text note renderer (`renderRichNote` tokenizer) and the shared formatting toolbar/shortcut helpers (`applyNoteFormat`, `noteFormatBarHtml`, `wireNoteFormatBar`, `handleNoteFormatShortcut`). |
| `44-threads.js` | CMH-THREAD | Single-level comment threads: reply grouping (`threadRoots`/`repliesOf`), `threadIds`, and orphan-reply pruning. |
| `45-composer.js` | CMH-A11Y, CMH-CORE, CMH-RICH | Per-instance comment composer (parallel-safe); hosts the formatting toolbar + shortcuts. |
| `50-sidebar.js` | CMH-SIDE, CMH-PERSIST, CMH-RICH | Sidebar rendering and durable embedded-delete persistence from per-card deletes; renders the reviewer note rich, carries the hidden raw-source element, and gives the inline reply/edit editors the shared formatting toolbar + shortcuts. |
| `51-comment-search.js` | CMH-SEARCH, CMH-RICH | Comment search / filter row: case-insensitive filter of the rendered cards (matching the hidden raw note source so markers/URLs stay searchable), shown/total count, clear button. |
| `52-hover-bubble.js` | CMH-CORE | Hover bubble to open a comment. |
| `53-comment-popover.js` | CMH-CORE, CMH-RICH | Inline on-screen comment dialog opened from the hover bubble (renders the note rich; note + Edit button, whose in-place editor carries the shared formatting toolbar and shortcuts; an outside pointer click closes it, and is swallowed when it lands in the annotated document unless it hits one of the layer's identity-resolved surfaces - an open editor, or a control registered through `cmhMarkLayerChrome` - while a keyboard-activated one is never swallowed). |
| `54-sidebar-toggle.js` | CMH-SIDE, CMH-A11Y | Sidebar open/close. |
| `55-toolbar-menu.js` | CMH-MENU-ICON, CMH-MENU-PREF, CMH-UI | Toolbar overflow menu; renders the menu header's brand icon and running-version text; wires the sidebar More menu's Preferences checkbox rows and its roving focus. |
| `56-copy-clear.js` | CMH-COPY | Copy all + Clear all. |
| `57-storage-manager.js` | CMH-STORE | Cross-document storage manager dialog: document registry, grouping, per-document delete, quota auto-open + retry. |
| `60-export-markdown.js` | CMH-MD, CMH-CODE | Export to Markdown; per-code-block Copy button, language pill, and optional caption. |
| `61-table-scroll.js` | CMH-RESP | Wraps each table in a `.cmh-table-scroll` box so a too-wide table scrolls instead of pushing the page sideways. |
| `62-sortable-tables.js` | CMH-CONTENT, CMH-PERSIST | Sortable tables (reordering is text-neutral: `_reorderBody` permutes the rows through their existing slots via the shared `cmhPermuteChildrenInSlots` in `00-preamble.js`) and durable embedded-delete persistence from Clear. |
| `65-export-shareable.js` | CMH-EXP, CMH-SEC | Export as Shareable + shared export snapshot primitives. |
| `66-export-plain.js` | CMH-EXP | Save as plain HTML (strip the comment layer). |
| `67-export-standalone.js` | CMH-MODE | Export standalone (nonshareable -> single file). |
| `68-export-offline.js` | CMH-OFFLINE | Export Offline (shareable + rich-content snapshots). |
| `70-mode-badge.js` | CMH-MODE | Mode badge + asset-version handshake. |
| `75-help.js` | CMH-HELP, CMH-A11Y | Help dialog. |
| `80-sort-comments.js` | CMH-SIDE | Sort comments by time. |
| `82-toc.js` | CMH-TOC, CMH-REVIEW, CMH-A11Y, CMH-VAL | Table-of-contents side menu; also hosts the section-review TOC filter + per-entry state dots and reads a serializable shadow heading's rendered label when its light-DOM text is empty. |
| `83-print.js` | CMH-PRINT, CMH-RICH, CMH-CONTENT | Print/PDF comment appendix materializer for flat documents, the single continuous no-break page sizer, the deck slide display-pin, and the "Save as PDF" buttons that call native `window.print()`; renders each note rich. Derives its tall-media diagram cap from `03-selectors.js`'s `CMH_MERMAID_SEL`, so it must stay ordered after that partial. |
| `84-section-review.js` | CMH-REVIEW, CMH-EXP | Section review tracking: content hashing, marker store, four-state badges, and TOC-filter helpers. Every content hash goes through `_cmhScanSections` -> `_cmhScanSkip`, which excludes both the skip SELECTOR subtrees and, by IDENTITY, anything the layer registered in `CMH_HASH_EXCLUDED` (today only the print appendix, registered where 83-print.js creates it - dropping that add/delete pair reintroduces a document-hash drift for as long as a print preview is open, CMH-CONTENT-21). The scan also reads the CANONICAL (authored source-order) rows via `_cmhCanonicalChildNodes` - any new hash-sensitive feature must hash through it, never the raw DOM order. The `reviewedSections` block is resolved by the EMBEDDED COMMENTS region among the blocks the content-root boundary accepts (`cmhLayerBlocks`, CMH-EXP-17), on the load side and the export side alike. |
| `90-toast.js` | CMH-A11Y | Toast notifications, including the single post-startup aggregation point for startup diagnostics; declares `cmhFocusRestoreTarget()`, the shared "a control that can really take focus now, else a stable chrome trigger" resolver a toast-launched dialog restores focus with (consumed by `57-storage-manager.js`, which sorts earlier - legal in the one hoisted IIFE scope, but move the pair together). |
| `95-startup.js` | CMH-HANDLED, CMH-EXP, CMH-FOOT | Handled-id pruning; startup; runtime footer (incl. session-id copy); closes the IIFE. |
