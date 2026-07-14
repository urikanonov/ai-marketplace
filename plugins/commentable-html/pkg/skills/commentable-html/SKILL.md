---
name: commentable-html
description: Turn a standalone HTML report, plan, dashboard, or design doc into a commentable review surface. Reviewers select any paragraph, table cell, code block, KQL query, chart, image, Mermaid diagram, or heading, leave inline comments, and export the whole thread back to the agent as a machine-readable bundle. Use when the user asks to add inline comments, leave review feedback, or add a code-review UI on an HTML report, plan, dashboard, or design doc, or wants to retrofit an existing HTML file or a Markdown doc into one portable, self-contained review file. Also triggers on the shorthand cmh.
---

# Commentable HTML

## Problem this skill solves

Commentable HTML is a code-review surface for plans, reports, dashboards, and design docs. AI increasingly returns rich HTML because HTML handles spatial layout, diagrams, charts, diffs, collapsible sections, and tabs better than Markdown. The review pain starts when a user must alt-tab between that HTML and chat to describe what should change.

This skill keeps the review inside the artifact: inline comments on the exact prose, code, diff, diagram, chart, image, heading, widget, or table; a structured **Copy all** bundle back to the agent; handled ids written into the same file; and a Portable or Offline export when another reviewer needs the file.

Why not just plan in chat, Markdown, or plain HTML?

| Medium | What breaks during review |
| --- | --- |
| Chat / terminal | The plan scrolls past, structure collapses, and feedback is prose about prose. |
| Markdown file | It survives on disk but stays flat: weak layout, charts, diagrams, and interaction. |
| Plain HTML | Rich and readable, as described in https://claude.com/blog/using-claude-code-the-unreasonable-effectiveness-of-html, but feedback is still out-of-band. |
| **Commentable HTML** | Keeps rich HTML and adds PR-style inline review, portable handoff, and agent-readable comment bundles. |

## Review loops

- **Self review loop:** generate the artifact, open it, comment inline, click **Copy all**, paste the bundle to the agent, let the agent update the HTML and mark handled ids, then reload so handled comments disappear.
- **Peer review loop:** self-review first, click **Export as Portable**, share the downloaded HTML, receive the peer's Portable HTML with embedded comments, then feed those comments back to the agent.
- **Reviewer loop:** when someone sends Markdown, first render it to HTML and pass that to `tools/new_document.py --content`; when they send existing HTML, retrofit it with `tools/retrofit.py`. Review inline, then send back a Portable file with embedded comments.

The runtime supports text selection, right-click fallback, multiple open composers, composer drag handles, a highlight bubble for link-wrapped highlights, `localStorage` persistence, embedded comments, and handled-id pruning. See [Interaction model](references/interaction-model.md) for the full walkthrough and edge cases.

## Preconditions and postconditions

**Preconditions:** the target is a standalone HTML artifact or a content fragment about to become one; it will open in a modern browser with `localStorage` and Clipboard API access; it is not inside a sandbox that blocks those APIs.

**Postconditions:** the HTML has the five layer regions, one configured `#commentRoot`, a `commentableHtmlLayer` descriptor, the handled-id and embedded-comment JSON blocks, and passes `python tools/validate.py --strict <file.html>`.

## Steps

**Defaults from a brief request.** A short request like "make me a commentable HTML for X, cover: <topics>" is enough. Default to a **NonPortable** document for fast local iteration, add a table of contents for multi-section reports, write polished sectioned prose, and use tables, charts, mermaid diagrams, images, KQL blocks, code blocks, widgets, and code-review diffs when they aid understanding. Use **Export as Portable** when the file needs to travel.

### Step 1 - Decide whether to add the layer

Use this skill for iterative plans, reports, dashboards, design docs, migration plans, and HTML artifacts where the user will leave feedback. Do not use it for short HTML emails, one-shot views, or sandboxed HTML where `localStorage` or clipboard APIs are unavailable.

### Step 2 - Create, retrofit, or upgrade with the right tool

**TOOL ROUTING contract:**

| Input | Tool | Key behavior |
| --- | --- | --- |
| New document from a content fragment | `tools/new_document.py` | Builds the full shell, sets `data-comment-key`, `data-doc-label`, optional `data-doc-source`, the `commentable-html-kind` meta from `--kind`, adds `data-cmh-content-root`, and validates before writing. |
| New animated slide **deck** | `deck/deck_scaffold.py` | Builds a fixed-stage 1920x1080 deck runtime (`data-cmh-mode="deck"`, `.deck-viewport > .deck-stage`, stable per-slide ids), self-validates against the deck contract, and is create-only. See "Deck capability (frontend-slides)" below - this is the ONLY tool that produces a real deck. |
| Unlayered existing standalone HTML | `tools/retrofit.py` | Injects the layer into that HTML, wraps body children or stamps `--root-selector "#id"`, sets the same data attributes and descriptor, and validates before writing. |
| Already-layered commentable HTML | `tools/upgrade.py` | Replaces only CSS, COMMENT UI, and JS regions while preserving content, handled ids, embedded comments, and root attrs. |

`--key auto` derives a stable non-demo key; an explicit `--key` must be unique per document on the same origin. `--label` becomes `data-doc-label` for the Copy header. `--source` becomes `data-doc-source` so the agent knows what source file to edit. `--kind` (required) declares the document type in a `<meta name="commentable-html-kind">`: `report` and `plan` must have a top-level `<h1>` title (auto-added from `--label` when the fragment has none), while `slides`, `board`, and `generic` do not. The validator enforces this, so a title-bearing document can never ship without a title.

```
# New NonPortable document (default): companions referenced from the skill dist/ by file:// URLs
python tools/new_document.py --content fragment.html --key auto --label "My Report" --kind report --out my-report.html
# Relative refs for a movable folder on this machine:
python tools/new_document.py --content fragment.html --key auto --label "My Report" --kind report --assets-relative --out my-report.html
# Copy companions next to the file for a movable folder:
python tools/new_document.py --content fragment.html --key auto --label "My Report" --kind report --copy-assets --out my-report.html
# Single self-contained Portable file:
python tools/new_document.py --content fragment.html --key auto --label "My Report" --kind report --portable --out my-report.html
# A titleless flat "slides"-kind document (NOT the animated deck runtime; for a real
# fixed-stage, navigable deck see "Deck capability (frontend-slides)" below and use deck/deck_scaffold.py):
python tools/new_document.py --content slides.html --key auto --label "My Notes" --kind slides --portable --out my-notes.html
# Retrofit an existing unlayered host HTML:
python tools/retrofit.py existing.html --label "My Report" --kind report --key auto --source existing.html --out existing-commentable.html
# Retrofit without wrapping body children when the host already has a content wrapper:
python tools/retrofit.py existing.html --label "My Report" --kind report --root-selector "#content" --skip-selectors "#toolbar,.modal" --out existing-commentable.html
# Upgrade an existing layered file (adds a default generic kind if the document predates kinds):
python tools/upgrade.py existing-commentable.html
```

**Mode decision:** NonPortable is for fast iteration, Portable is for peer review, Offline is for zero-network handoff. Portable still fetches optional mermaid / Chart.js from a CDN unless those libraries are vendored or the browser **Export Offline** path snapshots them. Portable != offline. See [Exports](references/exports.md#what-is-bundled-in-the-file-vs-fetched-from-where).

**No CLI export caveat:** a tool or headless browser cannot read the user's browser `localStorage`. If there are no in-browser comments yet, regenerate with `--portable`. If the user already commented in the browser, do not regenerate for handoff because that loses localStorage-only comments. Use the in-page **Export as Portable** button, or **Export Offline** after mermaid diagrams and charts have rendered.

### Step 3 - Wire the content root and avoid the footguns

The reviewable content must be inside the body/last active `#commentRoot`, never the commented demo example from the template. Use a unique non-demo key; never reuse `commentable-html-demo`, `commentable-html-nonportable-demo`, or `my-doc`. `validate.py` catches duplicate active roots, a demo key left on a customized document, and real content buried inside an HTML comment.

Add `class="cm-skip"` only to host floating panels, modals, sticky headers, or toolbars that should not receive comments. Do not add it to normal `<pre>` or `<pre><code>` blocks. A bare `<pre class="mermaid">` should keep `cm-skip` because mermaid comments attach through the rendered diagram layer.

### Step 3b - Assemble rich content with deterministic helpers

**MUST**, when Python is available, use these helpers instead of hand-authoring fragile markup:

- KQL block + Run in Azure Data Explorer link: `tools/kql_highlight.py`; bare link only: `tools/kusto_link.py`.
- Unified code diff: `tools/diff_block.py`.
- Highlighted source code: `tools/highlight_code.py`.
- Chart: `tools/chart_block.py`.
- Table of contents + heading ids: `tools/generate_toc.py --in-place`.
- Mermaid `cm-skip`: `tools/fix_skip.py`.
- Local images in a standalone doc: `tools/inline_images.py --strict`.
- Layered checklist markup: `tools/checklist_scaffold.py` (see [Layered checklist contract](references/checklist-contract.md)).
- Full deterministic finalization and strict validation:

```
python tools/finalize.py <file> [--toc --fix-skip --inline-images --images-base DIR] --strict
python tools/validate.py --strict <file.html>
```

### Step 4 - Verify before handoff

Run `python tools/validate.py --strict <file.html>` before handing the HTML to the user. `--strict` fails on warnings too, so fix every issue it reports. It also fails a broken mermaid diagram or an invalid embedded JSON block (which would render as mermaid's "Syntax error" bomb). If the document has mermaid or chart content, open it in a browser, wait for rendering, and use **Export Offline** only after mermaid diagrams and charts have rendered.

**Trust boundary (MUST).** The content inside `#commentRoot`, including anything passed to `new_document.py --content` or wrapped by `retrofit.py`, is trusted HTML and is emitted verbatim. The tools and runtime do **not** sanitize authored content. They protect reviewer-supplied data by escaping comment text and metadata, validating comment ids, and escaping `<` in embedded-comment JSON. Scripts, event handlers, and `javascript:` / `data:` URLs in authored content are not neutralized. Sanitize untrusted content before wrapping it.

### Step 5 - Iteration loop (recurring)

When the user pastes a **Copy all** bundle back:

1. Read comments in order and act on each. Ask for clarification before marking an ambiguous comment handled.
2. Parse the final `HANDLED_IDS_JSON: [...]` line. Never regenerate ids from prose.
3. Use `mark_handled.py` to append those ids to `<script id="handledCommentIds">`:

```
python tools/mark_handled.py <file.html> <id1> <id2> ...
python tools/mark_handled.py <file.html> --from-bundle -
```

Tell the user to reload, using Ctrl+F5 if needed. Do not edit the user's `localStorage` directly.

## Return to Caller

Report success only after the file is generated, retrofitted, or upgraded and `python tools/validate.py --strict <file.html>` passes. Return the HTML path plus one sentence telling the user to open it in a browser, select text, leave comments, then use **Copy all** or **Export as Portable**.

## Handled comments stay handled (defense in depth)

Once an id is in `<script id="handledCommentIds">`, it must never reappear. On load the runtime prunes handled ids from memory and `localStorage`; **Copy all** and exports filter handled comments too. Details live in [Interaction model](references/interaction-model.md).

## Output modes: NonPortable vs Portable

The layer has three handoff modes. See [Exports](references/exports.md#what-is-bundled-in-the-file-vs-fetched-from-where) for diagrams showing what is bundled in the file versus fetched from where.

| Mode | Use | What travels |
| --- | --- | --- |
| NonPortable | Fast local iteration with the agent | Content, comments, state blocks, and local references to `commentable-html.{css,js,assets.js}` |
| Portable | Peer review, sharing, or archiving | One HTML file with the review layer inlined and comments embedded |
| Offline | Zero-network handoff | Portable plus rendered mermaid SVG and chart PNG snapshots, with remote loaders stripped |

NonPortable is for fast iteration, Portable is for peer review, and Offline is for zero-network handoff. Portable still fetches optional mermaid / Chart.js from a CDN unless you vendor or inline them, or use **Export Offline** after rendering. There is deliberately no CLI export from NonPortable to Portable after comments exist because a CLI cannot read browser `localStorage`; use the in-page **Export as Portable** button.

See [Exports](references/exports.md) for NonPortable production details, guardrails, network requirements, export merge semantics, and version compatibility.

### Runtime UI summary

The runtime toolbar, sidebar, footer, Help modal, timestamps, document-type bubble, Clear-confirm dialog, and export buttons are runtime chrome. Do not re-author them in generated content. See [Document layout](references/document-layout.md#runtime-ui-chrome-and-toolbar) for the full UI contract.

### Compact authoring rules

Use `cmh-callout` plus `cmh-callout-info`, `cmh-callout-success`, `cmh-callout-warning`, or `cmh-callout-danger` for boxed asides, and `cmh-lede` for the lead block. Never hardcode report colors; use the `--cp-*` theme variables so text stays readable in dark and light themes. Use a private class prefix for custom components; never reuse the reserved `cmh-*` class names. Author collapsible sections as `<section>` elements with a direct heading.

## Editing the skill (maintainer)

Editing the skill's own layer code is a maintainer task done in the project's source repository, not per generated document; packaged installs do not include that development harness. Per generated document, the only thing to run is `tools/validate.py` below.

## When to use

- The user explicitly asks for inline comments, code-review UI, or "let me leave feedback on this HTML".
- You generated an HTML artifact (plan, report, dashboard, design doc, migration plan) that the user is likely to iterate on across several turns.
- The user wants a structured way to feed section-level feedback back into the conversation instead of pasting prose.

Do not use this skill for:

- Short HTML emails or one-shot views the user will not iterate on.
- HTML that will be rendered inside a sandbox that disables `localStorage` or clipboard APIs.

## Deck capability (frontend-slides)

This skill can build a real slide **deck** (an animation-rich, fixed 16:9 HTML presentation) that is
also a commentable-html document, so the user can create a deck, comment on the live deck, and iterate -
all in one plugin. The deck engine is a curated, hardened, vendored copy of the MIT-licensed
`frontend-slides` skill (Zara Zhang) under `vendor/frontend-slides/`; the author-time tools live under
`deck/`. See [deck contract](references/deck-contract.md) for the runtime interface.

**Detect and confirm (CMH-DECK-01).** When the request is really a presentation ("slide deck",
"presentation", "pitch deck", "slides for a talk", "convert this ppt"), do NOT silently produce a flat
document. Confirm with the user that they want a real deck; if they decline, fall back to a normal flat
commentable HTML.

**Flow.**

1. **PPTX (optional).** To convert a `.pptx`, prefer the Anthropic `pptx` skill when it is installed
   (more powerful) and fall back to the vendored local `extract-pptx.py`. Either way, pass the extracted
   content through `deck/pptx_to_fragment.py` (via `--input`/stdin, or `--pptx` for the local fallback) so
   every extracted string is HTML-escaped before it enters the deck. Speaker notes are not supported.
2. **Scaffold.** Run `python deck/deck_scaffold.py --content slides.html --label "..." --source <out> --out
   <out>` (or `--slides N` for placeholders). It emits a create-only, commentable-native fixed-stage deck:
   `data-cmh-mode="deck"`, a `.deck-viewport > .deck-stage` at 1920x1080, one `<section class="slide"
   data-slide-id=...>` per slide with the first `.active`, `viewport-base.css` inlined, a `commentable-html-kind`
   of `slides`, a system-font stack (no remote fonts), and no inline editor. It self-validates before writing.
3. **Fill.** Author the slide content (design, layout, copy) inside the existing `.slide` sections. Read
   `vendor/frontend-slides/html-template.md`, `viewport-base.css`, `animation-patterns.md`,
   `STYLE_PRESETS.md`, and the `bold-template-pack/` styles for the design system. Keep the deck body free
   of remote references and any external / SVG `<script>` (the upstream navigation/host script). A
   same-document inline `<script>` for chart init is fine.

   **Font override (important).** The vendored `html-template.md`, `STYLE_PRESETS.md`, and every
   `bold-template-pack/*/design.md` show `<link href="https://fonts.googleapis.com/...">` /
   `https://api.fontshare.com/...` and prescribe specific web fonts. Those are UPSTREAM examples - do NOT
   copy the remote `<link>`/`@import`/`@font-face url(https://...)` into a commentable deck: `deck_validate.py`
   rejects any remote font, `@import`, or `url(//...)` in the deck body, and a remote `<link>` in the head
   trips the base validator too. Keep the style's palette, layout, spacing rhythm, and component grammar, but
   MAP each `font-family` to a system stack that passes with no downloads: serif/editorial ->
   `"Iowan Old Style","Palatino Linotype","Georgia",serif`; slab/display/script (Shrikhand, Bebas Neue,
   Alfa Slab One, Fredoka One, ...) -> `"Impact","Rockwell","Arial Black",sans-serif` with heavier
   `letter-spacing`; geometric/body sans (Space Grotesk, Manrope, Inter, DM Sans, Barlow, ...) ->
   `system-ui,-apple-system,"Segoe UI",Roboto,sans-serif`; mono (JetBrains Mono, IBM Plex Mono, ...) ->
   `"Cascadia Code","Consolas","Fira Code",ui-monospace,monospace`; CJK (Noto Serif/Sans SC, LXGW WenKai
   TC, ...) -> drop and let the system CJK face resolve. If a design truly needs a specific face, obtain the
   `.woff2` locally and embed it as a `@font-face` whose `src` is a `data:font/woff2;base64,...` URI (the
   `data:` scheme is allowed), then re-run `deck_validate.py`.
4. **Validate.** Run `python deck/deck_validate.py --strict <out>`; fix every error before handoff (it enforces the
   fixed-stage structure, no remote fonts, and no dangerous active content on top of the base validator).
5. **Comment and iterate.** The user opens the deck, presents it normally, and comments inline. When they
   paste a Copy-all bundle back, edit the DECK **in place** (never re-run `deck_scaffold.py` without
   `--force`; it is create-only precisely so a re-scaffold cannot renumber slide ids or reset comment
   state), re-validate, and mark the handled ids with `tools/mark_handled.py`.

**Diagrams and offline (corporate-safe sharing).** Mermaid and Chart are supported. While iterating, keep
the deck NonPortable (the layer may load mermaid/Chart from a CDN on the local machine). When the deck is
done and needs to travel or be network-silent for a corporate audience, use **Export Offline**, which
snapshots mermaid to SVG and charts to PNG and strips remote loaders; fonts use a system stack or are
`data:`-embedded, so no font egress remains.

**Resyncing the vendored engine** is a maintainer task documented in
`dev/frontend-slides-upstream-sync.md`; the vendored subtree is kept pristine by the required CI check
`dev/tools/check_vendor.py`.

## Required HTML structure

A valid document has these five layer regions, in this order, plus one configured content root:

1. **CSS** in `<head>`.
2. **HANDLED IDS** near the top of `<body>`: `<script type="application/json" id="handledCommentIds">[]</script>`.
3. **EMBEDDED COMMENTS** immediately after handled ids: `<script type="application/json" id="embeddedComments">[]</script>`.
4. **COMMENT UI** after embedded comments and before visible content.
5. **JS** just before `</body>`, after content and host render scripts.

The content anchor is:

```html
<main id="commentRoot" data-cmh-content-root data-comment-key="..." data-doc-label="..." data-doc-source="...">
 ...content...
</main>
```

For existing HTML, prefer `tools/retrofit.py`; it inserts the five regions, descriptor, content markers, and data attributes without manual paste mistakes. The manual paste recipe is a fallback in [Retrofitting](references/retrofitting.md). The five regions carry a versioned `commentableHtmlLayer` descriptor so tooling can replace the layer without touching content; see [Forward-compatible layout](references/forward-compatible-layout.md) for the descriptor contract and version compatibility.

### Document kind (required)

Every document declares its kind in `<head>`:

```html
<meta name="commentable-html-kind" content="report" />
```

`content` is one of `report`, `plan`, `slides`, `board`, or `generic`, and it is mandatory (the validator errors without it). `report` and `plan` must carry a top-level `<h1>` title inside `#commentRoot`; `slides`, `board`, and `generic` do not. Set it with the tools' `--kind` flag rather than hand-writing the meta - `new_document.py` and `retrofit.py` require `--kind`, and `upgrade.py` adds a default `generic` kind to a document that predates kinds.

## Per-document configuration (data attributes)

| Attribute | Required | Purpose |
| ------------------ | -------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `data-comment-key` | yes | `localStorage` key for this document's comments. Must be unique per document on the same origin or comments leak across pages. |
| `data-doc-label` | yes | Human-readable name used in the Copy header and Agent Instructions block. e.g. `"Q3 architecture review"`. |
| `data-doc-source` | no | Source path used in the Copy `Source:` line and in the Agent Instructions block (so the agent knows which file to edit). Falls back to `location.pathname`. |

See [Document layout](references/document-layout.md#per-document-configuration-example) for a full root example.

## Per-comment data shape

Comment records carry pinpoint metadata so the agent can locate text, mermaid, diff, image, and code feedback without reopening the browser. See [Per-comment data shape](references/comment-data-shape.md) for JSON shapes and field details.

## Code blocks

Code selections are commentable by default and keep language, indentation, and fenced-copy formatting. Each commentable block also gets an always-visible top-right **Copy** button. See [Code blocks](references/code-blocks.md) for markup, stored fields, copy buttons, and runtime behavior.

## Kusto query blocks (Run in Azure Data Explorer deep link)

KQL blocks should pair a commentable `<pre><code class="language-kusto">` with a safe Run in Azure Data Explorer deep link. A framed KQL figure (`figure.cmh-kql`) **must** include a Run in Azure Data Explorer link built with `tools/kusto_link.py` - `validate.py` rejects a framed KQL figure without one as a hard error. If a query is purely illustrative and has no real cluster/database to run against, use a plain `<pre>` code block instead of a framed figure so it is exempt. The caption title is the click-to-copy cluster affordance, so do not add a separate cluster chip. See [Kusto query blocks](references/kusto-query-blocks.md) for link generation, data-safety rules, and markup.

## Mermaid diagrams

Mermaid nodes, gantt task labels/bars, sequence/gantt text, and whole diagrams can receive structural comments keyed by diagram index and node id (or `__diagram__`) while raw diagram source stays out of text selection. Pie slices and actors use the whole-diagram path. See [Mermaid diagrams](references/mermaid-diagrams.md) for markup, restore behavior, and loader guidance.

## Code review diffs (side-by-side or inline)

Unified diffs can be rendered as self-contained, line-commentable review blocks with inline and side-by-side layouts plus an in-page **Syntax: on/off** highlighting toggle. See [Code review diffs](references/code-review-diffs.md) for markup, escaping, anchoring, and use cases.

## Charts with tooltips

Chart.js charts are supported when the canvas lives in `figure.chart`, the wrapper is `cm-skip` for text offsets, and init runs after the commentable JS region. The canvas itself is commentable as `imageKind: "chart"`. Chart.js loads from a CDN by default via a guarded loader that falls back gracefully; self-host or inline it for a fully self-contained file. See [Charts with tooltips](references/charts.md) for embedding and verification details.

## Network requirements

NonPortable loads the review layer from local companion files. Portable inlines the review layer, state, and comments into one file. Portable still fetches optional mermaid / Chart.js from a CDN unless those assets are vendored or inlined; for zero-network fidelity use **Export Offline** after mermaid diagrams and charts have rendered. See [Exports](references/exports.md#network-requirements-and-cdn-caveats).

## Theme (light by default)

Generated documents default to light theme unless the request explicitly asks for dark. See [Document layout](references/document-layout.md) for query parameters and theme behavior.

## Table of contents (multi-section documents)

Use a `nav.cm-toc` for documents with roughly four or more top-level sections, with stable heading ids for links and anchors. The runtime side menu adds Expand All, Collapse All, Scroll to Top, Scroll to Bottom, and a scroll-progress bubble. See [Document layout](references/document-layout.md) for TOC markup and rules.

## Sections and document layout

Structure larger documents as collapsible section cards with stable heading ids, badges, boxed code/chart figures, and plain tables where appropriate. See [Document layout](references/document-layout.md) for section, badge, table, and sidebar layout recipes.

## Tables

Plain rectangular tables inside `#commentRoot` get default themed styling and per-column sorting without host CSS. Complex tables with spans stay unsortable. See [Document layout](references/document-layout.md) for table guidance and when to prefer a diff block.

## Images (commentable)

Images inside `#commentRoot` can receive whole-image comments restored by image index and source fallback. See [Images](references/images-commentable.md) for hover, keyboard, copy, and export behavior.

## Commentable widgets, SVG nodes, and document-wide comments

Interactive widgets and SVG figures become commentable per part via a generic opt-in contract (`data-cm-widget` / `data-cm-part` / `data-cm-slot`); parts inside `data-cm-slot` containers also get deterministic layout-change tracking, and right-clicking empty space adds a document-wide comment. Add `data-cm-draggable` to the widget root or to individual slot containers when cards should be movable. Only direct `data-cm-part` children of a slot are movable, so nested controls and sub-widgets stay stable unless they opt in separately. See [Commentable widgets](references/commentable-widgets.md) for the markup, restore behavior, state-change bundle, and portability effect.

## Leaving comments (interaction model)

All anchor types use the same Add Comment control and sidebar lifecycle, while duplicate anchors reopen existing comments where possible. See [Interaction model](references/interaction-model.md) for prose, code, diff, mermaid, and image gestures.

## Content conventions (ADO links and cross-references)

Make source references actionable with real ADO links and stable in-page cross-references. See [Content conventions](references/content-conventions.md) for URL shapes and anchor-link rules, and for authoring guidance on shaping content in real layouts, taste (avoiding the default-AI look), the readable prose measure, and mapping a product's design tokens onto the `--cp-*` variables.

## Export as Portable

The export action downloads a fresh copy with the current comments written into `#embeddedComments`; in nonportable mode it also inlines the companion assets into one portable file. See [Exports](references/exports.md) for merge semantics and implementation details.

## Export Offline

Use **Export Offline** when the recipient needs a zero-network handoff. It first builds the Portable export, then snapshots rendered mermaid diagrams as inline SVG, snapshots Chart.js canvases as PNG images, and strips remote rich-content loaders. Run it after mermaid diagrams and charts have rendered in the browser; otherwise there is nothing rendered to snapshot.

## Combined file from a nonportable document

NonPortable exports inline the loaded CSS and runtime from the asset registry so the downloaded file is portable. See [Exports](references/exports.md) for the exact rebuild behavior.

## Export to Plain HTML

Plain export removes the review UI and runtime while keeping the document styling and content intact. See [Exports](references/exports.md) for strip rules, safety checks, and mode differences.

## Export to Markdown

Export to Markdown downloads a `.md` file via a deterministic block-by-block conversion (headings, lists, GFM tables, fenced code / diff / mermaid / kusto, callouts as GitHub alerts, charts and SVG as caption notes), with the current comments appended as a section. See [Exports](references/exports.md#export-to-markdown) for the full block mapping.

## Add the layer to an existing HTML

Use `tools/retrofit.py` as the primary path for unlayered host HTML. It uses the same layer regions as the generated templates, parses real `<head>` / `<body>` tags, refuses already-layered files, wraps body children by default, supports `--root-selector "#id"` for an existing wrapper, marks host chrome with `--skip-selectors`, warns about likely CSS collisions, validates before writing, and leaves the target unchanged on failure.

```
python tools/retrofit.py existing.html --label "My Report" --key auto --source existing.html --out existing-commentable.html
python tools/retrofit.py existing.html --label "My Report" --root-selector "#content" --portable --out shareable.html
```

See [Retrofitting](references/retrofitting.md) for the tool contract, CSS collision checklist, and manual paste fallback.

## Upgrade an existing instance to a new dist/PORTABLE.html

Upgrades replace the CSS, COMMENT UI, and JS regions while preserving handled ids, embedded comments, and `#commentRoot`. **SHOULD** run the deterministic helper instead of swapping regions by hand (the JS body contains marker-like text, so the JS region END is the LAST occurrence - a naive hand/regex swap truncates it):

```
python tools/upgrade.py <file.html> # upgrade in place from dist/PORTABLE.html
python tools/upgrade.py <file.html> --check # report stale regions without writing
```

It refuses nonportable documents (companion assets), preserves the document's state/content, and self-validates the result. See [Retrofitting](references/retrofitting.md) for the mechanical upgrade recipe.

## Layout recipes

The resizable sidebar stores its width in localStorage and reserves matching space when `body.sidebar-open` is active. See [Document layout](references/document-layout.md) for centered, full-bleed, and default-open recipes.

## Copy payload format

Copy all emits a Markdown bundle plus the machine-readable `HANDLED_IDS_JSON` contract. See [Copy payload format](references/copy-payload.md) for the full payload shape and anchor-type differences.

## What the agent does when the user pastes the bundle back

The core loop is in Step 5: act on comments, parse `HANDLED_IDS_JSON`, merge ids into `handledCommentIds`, and tell the user to reload. See [Copy payload format](references/copy-payload.md) for the expanded checklist.

## Limitations to call out

Call out anchor and browser limitations when they affect a generated document, especially dynamic content, mermaid source changes, and clipboard constraints. See [Limitations](references/limitations.md) for the full list.

## Files

Use these files and folders when producing, validating, or maintaining commentable HTML:

- **`dist/NONPORTABLE.html`** - default shell for cheap local iteration with shared companion assets.
- **`dist/PORTABLE.html`** - complete inline template and demo for one-file sharing or archiving.
- **`dist/`** - companion CSS/JS/assets bundle used by NonPortable documents and Export as Portable.
- **`tools/*`** - deterministic, stdlib-only Python helpers you SHOULD prefer over hand-editing (they remove AI variance and are self-validating). Run any with `python tools/<name>.py --help`:
 - `validate.py [--strict] <file>` - structural/invariant checker (run after every retrofit; `--strict` fails on any warning so one run surfaces everything).
 - `new_document.py --content <file|-> --key K|auto --label L [--source S] [--generated ISO]` - build a fresh NonPortable commentable doc from a content fragment; pass `--portable` for one self-contained file.
 - `retrofit.py <file.html> --label L [--key auto|K] [--source S] [--root-selector "#id"] [--portable]` - add the layer to an unlayered existing HTML file; validates before writing and leaves the target unchanged on failure.
 - `upgrade.py <file> [--check]` - swap the CSS/COMMENT UI/JS regions of a deployed file to a newer `dist/PORTABLE.html`, preserving comments/state (validates before it commits; never clobbers on failure).
 - `finalize.py <file> [--toc --fix-skip --inline-images --images-base DIR] [--strict]` - run the safe assembly steps in a fixed order then validate, in one command.
 - `mark_handled.py <file> --from-bundle -` - append handled ids from a pasted Copy-all bundle (the iteration loop).
 - `diff_block.py --label L [--lang X] [<diff>|-]` (or `--from-files A B`) - emit an escaped `pre.cmh-diff` code-review block.
 - `chart_block.py --spec <json|-> --canvas-id ID --caption C [--title T]` - emit a validator-clean `figure.chart` + CDN-failure-guarded loader + init from a Chart.js spec.
 - `kql_highlight.py` / `kusto_link.py` - build a full `figure.cmh-kql` and a deterministic Run in Azure Data Explorer deep link (never hand-build the link).
 - `highlight_code.py` - author-time syntax highlighting for a code block.
 - `generate_toc.py <file> [--in-place]` - build a `nav.cm-toc` from the document headings.
 - `fix_skip.py <file> [--check]` - add `cm-skip` to bare `pre.mermaid` blocks.
 - `inline_images.py <file>` - inline local images as data URIs for a portable file.
- **`deck/*`** - author-time deck tools: `deck_scaffold.py` (build a fixed-stage deck), `pptx_to_fragment.py` (escape extracted PowerPoint into a deck fragment), `deck_validate.py` (enforce the deck contract). See "Deck capability (frontend-slides)" and [deck contract](references/deck-contract.md).
- **`vendor/frontend-slides/*`** - the vendored, hardened deck engine (MIT, (c) 2025 Zara Zhang); styles and CSS the deck inlines. Not edited directly; resynced via the dev-side playbook.
- **`docs/*`** - the shipped tutorial (`docs/TUTORIAL.md`) and its screenshots (`docs/tutorial-images/`).
- **`references/`** - detailed reference material moved out of this lean `SKILL.md`.

See [File inventory](references/file-inventory.md) for script-by-script and doc-by-doc details.

## Validating a generated file (tools/validate.py)

Run `python tools/validate.py <file.html>` when Python is available to check the structural invariants. See [Validation](references/validation.md) for error, warning, and chart details.

## Quick verification after retrofitting

Before handoff, reload, add a sample comment, copy all, append a handled id, reload, and confirm pruning. See [Validation](references/validation.md) for the complete manual checklist and failure modes.

## Design decisions (intentional - do not flag)

Several validator and runtime behaviors are deliberate residuals from prior reviews. See [Design decisions](references/design-decisions.md) before reporting one as a bug.

---
