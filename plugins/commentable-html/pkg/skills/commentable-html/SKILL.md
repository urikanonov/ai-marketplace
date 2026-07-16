---
name: commentable-html
description: Turn a standalone HTML report, plan, dashboard, or design doc into a commentable review surface. Reviewers select any paragraph, table cell, code block, KQL query, chart, image, Mermaid diagram, or heading, leave inline comments, and export the whole thread back to the agent as a machine-readable bundle. Use when the user asks to add inline comments, leave review feedback, or add a code-review UI on an HTML report, plan, dashboard, or design doc, or wants to retrofit an existing HTML file or a Markdown doc into one portable, self-contained review file. Also triggers on the shorthand cmh.
---

# Commentable HTML

**Version:** `1.85.0`

Commentable HTML turns a standalone HTML artifact into an in-browser review surface: reviewers comment on exact prose, code, diffs, diagrams, charts, images, headings, widgets, or table cells, then copy or export structured feedback for the agent to apply.

This plugin installs into both Claude Code and the GitHub Copilot CLI (add the marketplace, then `claude plugin install commentable-html@urikan-ai-marketplace` or `copilot plugin install commentable-html@urikan-ai-marketplace`), and the skill is invokable from each agent's CLI and Desktop app. The output is a portable HTML file that works with any agent.

## Review loops

- **Self review:** generate the artifact, open it, comment inline, click **Copy all**, paste the bundle to the agent, let the agent update the HTML and mark handled ids, then reload.
- **Peer review:** self-review first, click **Export as Portable**, share the downloaded HTML, receive the peer's Portable HTML with embedded comments, then feed those comments back to the agent.
- **Reviewer loop:** render Markdown to HTML and pass it to `tools/authoring/new_document.py --content`, or retrofit existing HTML with `tools/authoring/retrofit.py`, then return a Portable file with embedded comments.

The runtime supports text selection, right-click fallback, multiple open composers, composer drag handles, link-wrapped highlight bubbles, `localStorage` persistence, embedded comments, and handled-id pruning. See [Interaction model](references/interaction-model.md) for the full walkthrough.

## Preconditions and postconditions

**Preconditions:** the target is a standalone HTML artifact or a content fragment about to become one; it opens in a modern browser with `localStorage` and Clipboard API access; it is not inside a sandbox that blocks those APIs.

**Postconditions (MUST):** the HTML has the five layer regions, one configured `#commentRoot`, a `commentableHtmlLayer` descriptor, handled-id and embedded-comment JSON blocks, and it MUST pass `python tools/validate/validate.py --strict <file.html>`. Every HTML this skill emits - whether returned to the user, written to disk, or shared - MUST be finalized (`tools/authoring/finalize.py`, which bakes syntax highlighting) and strict-validated before handoff. A document that skipped finalize or strict validation is NOT done: it can ship with monochrome code or other defects. The authoring tools (`new_document.py`, `retrofit.py`, `deck_scaffold.py`) bake highlighting by default and surface validator warnings so a freshly created document is never raw, but that does NOT replace the final `finalize.py ... --strict` + strict-validate pass, which is mandatory on the finished artifact.

## Steps

**Defaults from a brief request.** A request like "make me a commentable HTML for X, cover: <topics>" is enough. Default to a **NonPortable** document for fast local iteration, add a table of contents for multi-section reports, write polished sectioned prose, and use richer blocks only when they aid review. Use **Export as Portable** when the file needs to travel.

### Step 1 - Decide whether to add the layer

Use this skill for iterative plans, reports, dashboards, design docs, migration plans, and HTML artifacts where the user will leave feedback. Do not use it for short HTML emails, one-shot views, or sandboxed HTML where `localStorage` or clipboard APIs are unavailable. See [Interaction model](references/interaction-model.md) for the problem statement, self-review loop, peer-review loop, reviewer loop, gestures, and edge cases. Plain HTML is valuable for rich artifacts, as described in https://claude.com/blog/using-claude-code-the-unreasonable-effectiveness-of-html; this layer adds in-artifact review and structured handoff.

### Step 2 - Create, retrofit, upgrade, or author a deck with the right tool

**TOOL ROUTING contract:**

| Input | Tool | Key behavior |
| --- | --- | --- |
| New document from a content fragment | `tools/authoring/new_document.py` | Builds the shell, configures `#commentRoot`, stamps `commentable-html-kind`, bakes syntax highlighting, surfaces validator warnings, and validates before writing. |
| New animated slide **deck** | `tools/deck/deck_scaffold.py` | Builds a fixed-stage deck (`data-cmh-mode="deck"`, stable slide ids), bakes highlighting, and self-validates. This is the ONLY tool that creates a real deck. |
| Unlayered existing standalone HTML | `tools/authoring/retrofit.py` | Injects the layer, wraps or stamps a content root, preserves host content, bakes highlighting, and validates before writing. |
| Already-layered commentable HTML | `tools/authoring/upgrade.py` | Replaces only CSS, COMMENT UI, and JS regions while preserving content, handled ids, embedded comments, and root attributes. |

Canonical commands:

```bash
# New NonPortable document (default, local companion assets).
python tools/authoring/new_document.py --content fragment.html --key auto --label "My Report" --kind report --out my-report.html

# Single self-contained Portable file.
python tools/authoring/new_document.py --content fragment.html --key auto --label "My Report" --kind report --portable --out my-report.html

# Retrofit an existing unlayered host HTML.
python tools/authoring/retrofit.py existing.html --label "My Report" --kind report --key auto --source existing.html --out existing-commentable.html

# Upgrade an existing layered file in place.
python tools/authoring/upgrade.py existing-commentable.html

# Real fixed-stage deck, not a flat slides-kind document.
python tools/deck/deck_scaffold.py --content slides.html --label "My Deck" --source my-deck.html --out my-deck.html
```

`--key auto` derives a stable non-demo key; an explicit key must be unique per document on the same origin. `--label` becomes `data-doc-label`; `--source` becomes `data-doc-source`; `--kind` is required and must be `report`, `plan`, `slides`, `board`, or `generic`. `report` and `plan` need a top-level title; the tools and validator enforce that.

**Mode decision:** NonPortable is for fast iteration, Portable is for peer review, Offline is for zero-network handoff. Portable still fetches optional mermaid or Chart.js from a CDN unless those libraries are vendored or the browser **Export Offline** path snapshots them. Portable != offline. See [Exports](references/exports.md).

**No CLI export caveat:** a tool or headless browser cannot read browser `localStorage`. If there are no in-browser comments yet, regenerate with `--portable`. If the user already commented in the browser, use the in-page **Export as Portable** button, or **Export Offline** after mermaid diagrams and charts have rendered.

For companion-copy modes, export semantics, network requirements, merge behavior, and Plain HTML / Markdown export details, read [Exports](references/exports.md) and its [bundled-vs-fetched diagrams](references/exports.md#what-is-bundled-in-the-file-vs-fetched-from-where). For retrofit flags, CSS collision checks, manual paste fallback, and the mechanical upgrade recipe, read [Retrofitting](references/retrofitting.md).

### Step 3 - Wire the content root and avoid the footguns

Keep reviewable content inside the live `#commentRoot` with a unique non-demo `data-comment-key`; `python tools/validate/validate.py --strict <file.html>` rejects duplicate roots, demo/example keys, and hidden commented roots.

Use `cm-skip` only for host chrome and bare mermaid source blocks; `python tools/validate/validate.py --strict <file.html>` warns when normal code blocks would become non-commentable.

A valid document has five layer regions in order: CSS, HANDLED IDS, EMBEDDED COMMENTS, COMMENT UI, and JS, plus one configured content root:

```html
<main id="commentRoot" data-cmh-content-root data-comment-key="..." data-doc-label="..." data-doc-source="...">
 ...content...
</main>
```

Use the tools rather than manual region editing. If manual fallback is unavoidable, follow [Forward-compatible layout](references/forward-compatible-layout.md) and [Retrofitting](references/retrofitting.md).

### Step 3b - Assemble rich content with deterministic helpers

**MUST**, when Python is available, use these helpers instead of hand-authoring fragile markup:

- KQL block + Run in Azure Data Explorer link: `tools/kusto/kql_highlight.py`; bare link only: `tools/kusto/kusto_link.py`. Every KQL block MUST be runnable (a `figure.cmh-kql` with a cluster + run link) - prefer a real cluster (example reports and decks use the public `help.kusto.windows.net`); a bare highlight-only block MUST be explicitly marked `data-cmh-kql-no-cluster` (via `--code-only`) or the validator errors (CMH-KQL-08).
- Unified code diff: `tools/blocks/diff_block.py`.
- Highlighted source code: `tools/blocks/highlight_code.py` or the document pass in `tools/blocks/highlight_document.py`.
- Chart: `tools/blocks/chart_block.py`.
- Table of contents + heading ids: `tools/authoring/generate_toc.py --in-place`.
- Mermaid `cm-skip`: `tools/authoring/fix_skip.py`.
- Section cards for a report/plan: `tools/authoring/wrap_sections.py` wraps each bare top-level `<h2>` block in `<section>` so the document renders as boxed cards (`#commentRoot > section`); `new_document.py` (report/plan fragments) and `finalize.py` run it by default, so hand-wrapping is only needed for externally produced HTML. The validator warns (CMH-VAL-14) when top-level content is not sectioned.
- Local images in a standalone doc: `tools/authoring/inline_images.py --strict`.
- Layered checklist markup: `tools/checklist/checklist_scaffold.py`.
- Editable notes-field markup: `tools/notes/notes_scaffold.py`.
- Full deterministic finalization and strict validation:

```bash
python tools/authoring/finalize.py <file> [--toc --fix-skip --inline-images --images-base DIR] --strict
python tools/validate/validate.py --strict <file.html>
```

Use the conditional lookup table below when a document needs a richer feature:

| Need | Reference |
| --- | --- |
| Code blocks, copy buttons, and baked highlighting | [Code blocks](references/code-blocks.md) |
| KQL blocks and ADE run links | [Kusto query blocks](references/kusto-query-blocks.md) |
| Mermaid diagrams and structural comments | [Mermaid diagrams](references/mermaid-diagrams.md) |
| Code review diffs | [Code review diffs](references/code-review-diffs.md) |
| Chart.js figures and tooltips | [Charts](references/charts.md) |
| Themes, TOC, sections, tables, callouts, and layout recipes | [Document layout](references/document-layout.md) |
| Commentable widgets, SVG parts, draggable slots (`data-cm-draggable`), and document-wide comments | [Commentable widgets](references/commentable-widgets.md) |
| Images and chart-canvas comments | [Images](references/images-commentable.md) |
| Layered checklists | [Layered checklist contract](references/checklist-contract.md) |
| Editable notes fields | [Editable notes-field contract](references/notes-contract.md) |
| Comment gestures and sidebar lifecycle | [Interaction model](references/interaction-model.md) |
| ADO links, cross-references, prose shape, and design-token mapping | [Content conventions](references/content-conventions.md) |

Compact authoring rules: use `cmh-callout` variants and `cmh-lede` for asides, prefer `nav.cm-toc` for roughly four or more top-level sections, use stable heading ids, use `--cp-*` theme variables instead of hardcoded report colors, and use a private class prefix for custom components rather than reserved `cmh-*` names. Only direct `data-cm-part` children of a slot are movable, so nested controls and sub-widgets stay stable unless they opt in separately.

### Step 4 - Verify before handoff

**You MUST finalize and strict-validate every HTML you produce before handing it off, saving it, or returning it - no exceptions.** Run `python tools/authoring/finalize.py <file> --strict` (it bakes syntax highlighting and runs the assembly steps in order, then validates) followed by `python tools/validate/validate.py --strict <file.html>`. `--strict` fails on warnings too, so fix every issue it reports until the run is clean. Do NOT hand the user, or write to their Downloads/disk, a document you have not strict-validated - a skipped validation is exactly how a document ships with monochrome code or a broken layer. On a strict-clean pass these tools stamp a `commentable-html-validated` timestamp into the file (creation stamps `commentable-html-created`); if a produced document is opened without a current validated stamp, the runtime shows a small amber "not validated" banner - a last-resort signal that this step was skipped, which you must never rely on. If Python is unavailable, say EXPLICITLY that validation was skipped (so the user knows the document is unverified) and perform the manual checks in [Validation](references/validation.md). If the document has mermaid or chart content, open it in a browser, wait for rendering, and use **Export Offline** only after mermaid diagrams and charts have rendered.

**Trust boundary (MUST).** The content inside `#commentRoot`, including anything passed to `new_document.py --content` or wrapped by `retrofit.py`, is trusted HTML and is emitted verbatim. The tools and runtime do **not** sanitize authored content. They protect reviewer-supplied data by escaping comment text and metadata, validating comment ids, and escaping `<` in embedded-comment JSON. Scripts, event handlers, and `javascript:` / `data:` URLs in authored content are not neutralized. Sanitize untrusted content before wrapping it.

### Step 5 - Iteration loop (recurring)

When the user pastes a **Copy all** bundle back:

1. Read comments in order and act on each. Ask for clarification before marking an ambiguous comment handled.
2. Parse the final `HANDLED_IDS_JSON: [...]` line. Never regenerate ids from prose.
3. Use `mark_handled.py` to append those ids to `<script id="handledCommentIds">`:

```bash
python tools/authoring/mark_handled.py <file.html> <id1> <id2> ...
python tools/authoring/mark_handled.py <file.html> --from-bundle -
```

Tell the user to reload, using Ctrl+F5 if needed. Do not edit the user's `localStorage` directly. Details of the Copy-all payload live in [Copy payload format](references/copy-payload.md).

## Return to caller

Report success only after the file is generated, retrofitted, upgraded, or finalized and `python tools/validate/validate.py --strict <file.html>` passes. Return the HTML path plus one sentence telling the user to open it in a browser, select text, leave comments, then use **Copy all** or **Export as Portable**.

## Handled comments stay handled

Once an id is in `<script id="handledCommentIds">`, it must never reappear. On load the runtime prunes handled ids from memory and `localStorage`; **Copy all** and exports filter handled comments too. See [Interaction model](references/interaction-model.md#handled-comments-stay-handled).

## Deck capability (frontend-slides)

This skill can build a real animated slide **deck** that is also a commentable-html document. A real deck is fixed-stage, navigable, and validated by deck tools; a `--kind slides` flat document is not a deck.

**Detect and confirm (CMH-DECK-01).** When the request is really a presentation (`slide deck`, `presentation`, `pitch deck`, `slides for a talk`, `convert this ppt`), do not silently produce a flat document. Confirm that the user wants a real deck; if they decline, fall back to a normal flat commentable HTML.

**Plan first (frontend-slides).** When asked to plan or design a deck (not just scaffold one), consult the vendored `frontend-slides` design system before scaffolding: read `vendor/frontend-slides/bold-template-pack/selection-index.json` to shortlist templates by mood/tone/scheme/best_for, plus `vendor/frontend-slides/STYLE_PRESETS.md`, `html-template.md`, and `animation-patterns.md` for the style presets, the fixed-stage structure, and entrance animations. Decide the slide outline and theme, and offer a safe, a bold, and a wildcard title-slide option, before writing any slides.

**Deck invariants:**

- Use `tools/deck/deck_scaffold.py` to create the deck. It is create-only and mints stable slide ids.
- Edit the deck **in place** on iteration so comments, handled ids, embedded comments, and slide ids survive. Never re-run the scaffold without `--force` unless you intentionally accept new slide ids and state loss.
- Run `python tools/deck/deck_validate.py --strict <out>` before handoff.
- Keep the deck body free of remote fonts, remote media/resource fetches, external scripts, remote CSS imports, inline event handlers, dangerous URL schemes, and the upstream SVG host script. Use system fonts or locally embedded `data:font/woff2` fonts only.
- For PPTX input, extract with the installed `pptx` skill when available, otherwise the local fallback, then pass extracted text through `tools/deck/pptx_to_fragment.py` so strings are HTML-escaped before they enter the deck.
- Use **Export Offline** for corporate-safe sharing after mermaid diagrams and charts have rendered.

See [Deck runtime interface contract](references/deck-contract.md) for author-time commands, PPTX conversion limits, slide design and font mapping, the runtime interface, stable slide-id contract, controller globals, anchoring model, script and resource restrictions, contrast validation, and limitations. Vendored engine resync is a maintainer task documented in the source repo.

## Output modes and exports

| Mode | Use | What travels |
| --- | --- | --- |
| NonPortable | Fast local iteration with the agent | Content, comments, state blocks, and local references to companion CSS/JS/assets |
| Portable | Peer review, sharing, or archiving | One HTML file with the review layer inlined and comments embedded |
| Offline | Zero-network handoff | Portable plus rendered mermaid SVG and chart PNG snapshots, with remote loaders stripped |

See [Exports](references/exports.md) for bundled-vs-fetched diagrams, NonPortable guardrails, version compatibility, network caveats, export merge semantics, Plain HTML stripping, and Markdown conversion.

## Document identity

Every document declares its kind in `<head>` with `<meta name="commentable-html-kind" content="report" />`. Use the tool `--kind` flag rather than hand-writing the meta. `report` and `plan` require a top-level `<h1>` title inside `#commentRoot`; `slides`, `board`, and `generic` do not.

The content root carries document identity:

| Attribute | Required | Purpose |
| --- | --- | --- |
| `data-comment-key` | yes | Unique `localStorage` bucket for this document on the same origin. |
| `data-doc-label` | yes | Human-readable name used in Copy headers and Agent Instructions. |
| `data-doc-source` | no | Source path for Copy output and agent edits; falls back to `location.pathname`. |

Do not bake transient runtime classes such as `sidebar-open` into saved `<body>` markup. The runtime derives them on load, and strict validation rejects persisted UI state. See [Document layout](references/document-layout.md#per-document-configuration-example).

## Runtime chrome and document layout

The runtime toolbar, sidebar, footer, Help modal, timestamps, document-type bubble, Clear-confirm dialog, and export buttons are runtime chrome. Do not re-author them in generated content. Default documents are light theme unless the user explicitly asks for dark. See [Document layout](references/document-layout.md) for runtime UI, theme behavior, TOC rules, section cards, table sorting, layout recipes, and per-document configuration.

## Comment data and known limits

Comment records carry pinpoint metadata so the agent can locate text, mermaid, diff, image, chart, widget, document-wide, and code feedback without reopening the browser. See [Per-comment data shape](references/comment-data-shape.md) for JSON shapes and field details. Call out anchor and browser limitations when they affect a generated document, especially dynamic content, mermaid source changes, and clipboard constraints; see [Limitations](references/limitations.md).

## Files and maintainer references

Use the shipped tools and docs in the skill root when producing, validating, or maintaining commentable HTML. See [File inventory](references/file-inventory.md) for script-by-script and doc-by-doc details.

Editing the skill's own layer code is a maintainer task done in the source repository, not per generated document; packaged installs do not include the development harness. Per generated document, the thing to run is `tools/validate/validate.py --strict`.

Several validator and runtime behaviors are deliberate residuals from prior reviews. See [Design decisions](references/design-decisions.md) before reporting one as a bug.

---
