---
name: commentable-html
description: Turn any standalone HTML into a commentable review surface with inline comments, iterated locally and exported to a single portable file for sharing.
---

# Commentable HTML

This skill turns any standalone HTML file into a code-review surface:

1. User selects text in the document.
2. An "Add Comment" popup appears automatically just below the selection (right-click is also supported as a fallback).
3. A composer popover appears; the user writes a note. The composer has a drag handle at the top (grip icon + "drag to move") so it can be repositioned anywhere on screen if it is covering the text being commented on. Multiple composers can be open at the same time - selecting another piece of text and clicking "Add comment" creates a second composer alongside the first, neither closes the other. New composers stagger by 28px if they would land on top of an existing one, and the focused composer is brought to the front.
4. The selection becomes a highlighted span; the comment appears in a right-hand sidebar.
 - Clicking a highlight opens its comment in the sidebar. Because a highlight can wrap
 a link or other clickable element (which would otherwise swallow the click and
 navigate instead), hovering any highlight also pops a small **comment bubble**
 (`#hlBubble`); clicking that bubble opens the comment regardless of what the text
 links to. This is why the ADO-links / cross-reference conventions below are safe to
 apply even on commented text.
5. Comments persist in `localStorage` per document, and can additionally be embedded into the HTML file itself via **Export as Portable** so they travel with the document.
6. **Copy all** emits a Markdown bundle plus a `HANDLED_IDS_JSON: [...]` line.
7. The agent processes the comments, then appends the processed ids to a `<script id="handledCommentIds">` block inside the same HTML file.
8. On the next reload, those ids are pruned from `localStorage` and their highlights disappear, leaving only unprocessed comments.
9. **Export as Portable** downloads a fresh copy of the HTML with the current comments embedded in the `<script id="embeddedComments">` block. The browser saves the copy into the user's downloads folder renamed to `<stem>-portable.html` (after stripping any existing `-comments` or `-portable` suffix); the user can keep the copy, replace the original with it, or share it with someone else who can open it directly and see all the comments immediately.

The HTML file itself is the durable source of truth for which comments have been handled. `localStorage` is just an unsynchronized cache. When `<script id="embeddedComments">` is non-empty, it is treated as the shareable snapshot of the comments themselves: on load it is merged into `localStorage` by id, with the entry carrying the later `updatedAt` (fallback `createdAt`) winning per id.


## Preconditions and postconditions

**Preconditions**

- Target HTML artifact exists (or is about to be generated)
- HTML will be opened in a modern browser supporting localStorage and the Clipboard API
- HTML is not served from a sandbox that disables localStorage or clipboard access
- For "Export as Portable" the browser must allow `<a download>` triggered downloads. All modern browsers do; sandboxed iframes with the download permission removed do not.

**Postconditions**

- HTML contains the five `BEGIN/END: commentable-html - <REGION>` blocks (CSS, HANDLED IDS, EMBEDDED COMMENTS, COMMENT UI, JS)
- Content is wrapped in `<main id="commentRoot" data-comment-key=... data-doc-label=...>` with `data-doc-source=...` set whenever the agent needs to edit a specific source file
- User can select text, attach inline comments, copy a markdown bundle for the agent, and Export as Portable to embed the comments into the file so they travel with it
- `<script id="handledCommentIds">` block exists and is the agent-owned source of truth for which comments have been processed
- `<script id="embeddedComments">` block exists and is the user-owned, "Export as Portable"-owned in-file snapshot of the comments array

## Steps

**Defaults from a brief request.** A short request such as "make me a commentable HTML for X, cover: <topics>" is enough on its own. Fill in the rest by default: produce a **NonPortable** document (the layer's CSS/JS load from companion files, so the document is small and cheap to iterate on), add a table of contents, write polished sectioned prose, and add tables, charts, mermaid diagrams, images, KQL blocks, and code-review diffs wherever they aid understanding - all commentable. The user should not have to ask for the review layer, the table of contents, NonPortable output, or rich content; those are the skill's defaults. Export to a single Portable file only when sharing (see Step 2).

### Step 1 - Decide whether to add the layer

**MUST** confirm the use case fits ("When to use" section below). Do not add the layer to short HTML emails, one-shot views, or HTML rendered inside a sandbox that disables `localStorage` or clipboard APIs.

### Step 2 - Create the document (deterministic tools first)

**Default to NonPortable.** `tools/new_document.py` produces a **NonPortable** document by DEFAULT: the ~89 KB of layer CSS/JS is referenced from the companion `commentable-html.{css,js,assets.js}` files instead of inlined, so the document (and every regeneration during a review loop) is small and cheap to edit. Pass `--portable` for a single self-contained file (see "Output modes" for the trade-off).

**For a NEW document, MUST use `tools/new_document.py`** when Python is available. It clones the dist template, drops in only your content fragment, sets the `#commentRoot` data attributes, refuses demo keys, repoints the companion references, and self-validates before writing. Do NOT hand-copy the regions for a fresh document - that is the highest-token, most error-prone path and it walks straight into the duplicate-root footgun described in Step 3.

```
# NonPortable (default): companions referenced from the skill's dist/ by a relative path
python tools/new_document.py --content fragment.html --key auto --label "My Report" --out my-report.html
# ... or copy the companions next to the file for a movable folder:
python tools/new_document.py --content fragment.html --key auto --label "My Report" --copy-assets --out my-report.html
# Single self-contained Portable file (for sharing / archiving):
python tools/new_document.py --content fragment.html --key auto --label "My Report" --portable --out my-report.html
# --key auto derives a stable, collision-free key from the label (CMH-PERSIST-02);
# pass --generated <ISO-8601> for a reproducible "Generated on" line instead of the file mtime.
```

**"Make it portable" - getting a single file to share.** A NonPortable document needs its companions reachable, so it is for local iteration, not sharing. There is deliberately **no CLI export**: a tool (even a headless browser) cannot read the browser's `localStorage`, so a CLI export would silently drop comments the user typed but has not saved into the file. Instead:
- If the document has NO in-browser comments yet (e.g. one you just generated), regenerate it with `--portable` from the same content fragment - safe and complete.
- If the user has been leaving comments in the browser, only the page itself can read them: use the in-page **Export as Portable** button (or **Save in HTML** first). That is the single source of a complete, self-contained copy.

**Only when RETROFITTING an existing host HTML you cannot regenerate**, copy all five `BEGIN/END: commentable-html - <REGION>` blocks verbatim, in this order: CSS (in `<head>`), HANDLED IDS (top of `<body>`), EMBEDDED COMMENTS (immediately after HANDLED IDS), COMMENT UI (immediately after EMBEDDED COMMENTS), JS (just before `</body>`). See "Add the layer to an existing HTML" for the full recipe. To bring an already-layered file up to a newer `dist/PORTABLE.html`, **MUST** use `tools/upgrade.py` (it swaps only the CSS/COMMENT UI/JS regions, preserves your content and state, and leaves the file untouched if the result would fail validation) rather than hand-swapping regions.

### Step 3 - Wrap content in `#commentRoot` and set the data attributes

**MUST** wrap the commentable content in `<main id="commentRoot" data-comment-key="..." data-doc-label="...">`. `data-comment-key` must be unique per document on the same origin or comments will leak across pages.

**Pitfall when scripting the content swap.** `dist/PORTABLE.html` contains a **second** `<main id="commentRoot"> ... </main>` - an *example* inside the top-of-file documentation comment (its `data-comment-key` is the placeholder `my-doc`). If you replace the demo content with a script (regex / `str.index`), a naive "find the first `<main id="commentRoot">`" match hits that **commented example**, so your real content lands inside the comment and the browser silently renders the leftover demo instead. The real content root is the **last** `<main id="commentRoot">` and lives inside `<body>` - target that (e.g. `rindex`, or anchor on the demo `data-comment-key="commentable-html-demo"`), and give your root a **unique** `data-comment-key` (never reuse the demo key). `validate.py` now fails both of these mistakes (see Step 4).

**SHOULD** also set `data-doc-source="..."` whenever the agent will be editing a known source file (it is written into the Copy bundle's `Source:` line and the agent-instructions block). If omitted, the layer falls back to `location.pathname` - fine for ad-hoc demos, but ambiguous for real review loops.

**SHOULD** add `class="cm-skip"` to any pre-existing floating panels, modals, toolbars, or navs that must be excluded from the selection layer. **Do NOT** add `cm-skip` to `<pre>` or `<pre><code>` blocks - code blocks are commentable by default and the layer ships dedicated styling and a fenced-block Copy payload for them. The only `<pre>` that needs `cm-skip` is `<pre class="mermaid">` (the mermaid layer attaches independently via the `mermaid` class).

### Step 3b - Assemble rich content with the deterministic helpers

**MUST**, when Python is available, generate rich content artifacts with the tools below instead of hand-authoring them. The AI cannot reliably escape HTML, base64+gzip a Kusto link, or hand-build an CDN-failure-guarded chart loader; hand-authoring wastes tokens and causes validator failures. Use the tool every time the artifact appears:

- KQL block + Run in Azure Data Explorer link: `tools/kql_highlight.py` (never build the ADX deep link by hand; `tools/kusto_link.py` builds a bare link).
- Unified code diff: `tools/diff_block.py` (emits the escaped `pre.cmh-diff`).
- Highlighted source code: `tools/highlight_code.py`.
- Chart: `tools/chart_block.py` (emits the full `figure.chart` + the CDN-failure-guarded loader + init from a Chart.js spec JSON).
- Table of contents + heading ids: `tools/generate_toc.py --in-place`.
- Mermaid `cm-skip`: `tools/fix_skip.py`.
- Local images in a standalone doc: `tools/inline_images.py --strict`.

Then run `tools/finalize.py <file> [--toc --fix-skip --inline-images --images-base DIR] --strict` to execute the safe assembly steps in a fixed, deterministic order and strict-validate in one shot.

### Step 4 - Verify the retrofit

**MUST** run the verification checks in "Quick verification after retrofitting" below before handing the HTML to the user (skip the mermaid check if the document has no `<pre class="mermaid">` blocks). The most important invariant: appending a handled id to `<script id="handledCommentIds">` and reloading must prune that comment from **Copy all** output (this applies equally to text and mermaid comments).

**MUST** also run the automated validator before handoff when Python is available: `python tools/validate.py --strict <file.html>`. `--strict` treats every warning as a failure, so one run surfaces *all* issues at once (missing self-contained inlining, un-escaped diffs, broken Kusto links, duplicate heading ids, unlabeled canvases, and more) - iterate until it reports `OK (0 warning(s))`. Do not skip it and do not hand off with outstanding warnings. It also runs as the final step of `finalize.py`. It codifies the structural invariants (regions, `#commentRoot` wiring, JSON script blocks, escaped `</script>`, required ids, the self-contained guarantee) and fails two retrofit-specific mistakes: the demo content root surviving the swap (the active `#commentRoot` still carries `data-comment-key="commentable-html-demo"` while the `<title>` was customized) and a real content root left buried inside an HTML comment.

### Step 5 - Iteration loop (recurring)

When the user pastes a **Copy all** bundle back into the conversation:

1. Read the comments in order and act on each. If a comment is ambiguous, ask the user to clarify before marking it handled.
2. Parse the `HANDLED_IDS_JSON: [...]` line at the end of the bundle (machine-readable contract - never regenerate ids from the human-readable section).
3. Read the current `<script id="handledCommentIds">` JSON array from the HTML file.
4. Merge: append every id from `HANDLED_IDS_JSON`, preserve existing ids, deduplicate.
5. Write the new array back into the same `<script>` block, on its own line for diff-friendliness.
6. Tell the user to reload (Ctrl+F5 to bust cache). Processed comments will be pruned automatically.

**MUST**, when Python is available, use the `mark_handled.py` helper for steps 3-5 instead of editing by hand - it appends the ids surgically (touching only the handled-ids array, no LLM re-emission of surrounding boilerplate) and validates each id:

```
python tools/mark_handled.py <file.html> <id1> <id2> ...
python tools/mark_handled.py <file.html> --from-bundle - # pipe the pasted Copy-all bundle on stdin
```

This is the near-zero-token iteration step - it never rewrites the document body, which matters most in nonportable mode where the boilerplate lives in companion files.

**MUST NOT** edit the user's `localStorage` directly. Only the HTML file is the agent's surface.

## Return to Caller

When invoked by another skill or workflow:
1. Report SUCCESS once the five regions are pasted, `#commentRoot` is wired up, and the verification checks pass.
2. Provide artifacts: path to the modified HTML file and a one-line note explaining how the user opens it and leaves comments.
3. Return to the calling workflow's next step.

When invoked directly by the user:
1. Confirm the HTML has been retrofitted and tell the user how to open it, select text, leave a comment, and use **Copy all** / **Export as Portable**.
2. Stay ready for the next round of pasted comments.

## Handled comments stay handled (defense in depth)

Once a comment id is in the `<script id="handledCommentIds">` array, it must never resurface - whether the user reloads or re-copies. The layer enforces this at every read path:

- **On load,** `pruneHandled()` filters handled ids out of the in-memory comment list and unconditionally writes the survivors back to `localStorage`. The `localStorage` bucket can never drift back into containing a handled id.
- **Copy all** filters via `withoutHandled(comments)` before building the bundle. Handled comments are not in the markdown, not in `HANDLED_IDS_JSON`, and not counted in the "Copied N" toast.

This is the single most important invariant of the skill: the agent's edit to `handledCommentIds` is the final word on what is gone.

## Output modes: standalone (inline) vs nonportable

The layer ships in two interchangeable forms. Both share the exact same runtime and CSS (built from one source, see "Build pipeline"), and both keep the document-owned state (HANDLED IDS, EMBEDDED COMMENTS) inline. They differ only in whether the ~89 KB of CSS + JS boilerplate is inlined or referenced from companion files.

| | **Standalone (inline)** - `dist/PORTABLE.html` | **NonPortable** - `dist/NONPORTABLE.html` + companions |
|---|---|---|
| Layer CSS/JS | inlined in the file | referenced by `<link>` / `<script src>` from the skill's `dist/` folder (not copied into the report folder) |
| Portability | one self-contained file - email/move freely | needs the `commentable-html.{css,js,assets.js}` assets reachable at the referenced path; use **Export as Portable** for a self-contained copy |
| Per (re)generation cost | agent emits the whole ~106 KB file | agent emits a ~17 KB shell; the boilerplate is **referenced from the skill folder**, never emitted (~84% smaller) |
| Best for | one-shot artifacts, things you email or archive | dashboards/plans you iterate on locally, where regeneration speed and token cost matter |

**Default to NonPortable.** It is the skill's default output because a review document is edited many times and NonPortable keeps each regeneration ~84% smaller. A loose NonPortable HTML opened where it cannot reach its companions is broken, so it is for local iteration; get a self-contained copy to share by regenerating with `--portable` (for a document with no in-browser comments yet) or via the in-page **Export as Portable** button (the only path that captures comments the user typed in the browser). Choose Portable up front only for a one-shot artifact you will email or archive without iterating.

### Producing a nonportable document

The easiest and recommended way is `tools/new_document.py` (NonPortable by default): it starts from `dist/NONPORTABLE.html`, repoints the companion `<link>`/`<script src>` references (a relative path to the skill's `dist/` by default, bare names with `--copy-assets`, or a custom prefix with `--assets-href`), sets the version `<meta>`, and self-validates. If you must hand-produce one:

1. Point the shell's asset references at the skill's `dist/` folder rather than copying the files into the report folder: set the head `<link href>` and the two `<script src>` to a path that resolves to `.../commentable-html/dist/commentable-html.{css,js,assets.js}`. **Prefer a relative path** from the target HTML; use an absolute path only for clearly local-only documents (an absolute path embeds your local directory / username in the file and breaks for anyone else unless you run **Export as Portable** first). The three assets are **referenced, never regenerated**. (Copying them next to the HTML still works if you want a movable bundle instead.)
2. Use `dist/NONPORTABLE.html` as the starting shell (head `<link>` + version `<meta>`, the NONPORTABLE BOOTSTRAP banner, the inline state/UI regions, and the two `<script src>` companions at the end of `<body>`); repoint the `href`/`src` at the skill `dist/` path. Replace the demo content inside the CONTENT markers with your own; set a unique `data-comment-key`.
3. Keep the version `<meta name="commentable-html-version" content="<V>">` matching the referenced asset version.

### Guardrails that make nonportable safe (built in)

- **Version stamp and handshake.** Every generated document (portable and nonportable) carries `<meta name="commentable-html-version" content="<V>">` in `<head>` and shows `Commentable HTML v<V>` in the runtime footer. In nonportable mode the runtime reads that meta and warns loudly via a banner if the loaded companion version differs (stale cache / mismatched files).
- **Missing-asset banner.** The NONPORTABLE BOOTSTRAP block reveals a visible red banner if the companion runtime does not initialize within 3 s, so a broken share never fails silently.
- **Export as Portable embeds everything.** In nonportable mode the export action is labeled **Export as Portable**: it rebuilds ONE self-contained inline file - reading the CSS/JS string payloads from the loaded `.assets.js` registry (works from `file://` without `fetch`), inlining them, and embedding the current comments - so the downloaded file no longer depends on the skill folder or any companion. A user always gets a portable single file, even starting from a nonportable document. Producing the nonportable (referenced-asset) variant is the agent's job at generation time, not an in-page conversion.

### Toolbar

The toolbar is intentionally minimal: **Copy all**, the open-comment **count bubble**, a **Hide** toggle, and a **... more** button (which holds a **document-type badge**, a **Show** entry to reopen the panel, **Export as Portable**, **Export to Plain HTML**, and **Help**). When the panel is collapsed, the toolbar toggle reads **Show** and wears a distinct filled bubble so it stands out. The sidebar header pins, top to bottom: a **meta row** (the document-type bubble, the layer **version** `v<x.y.z>`, and a right-aligned **Help** + **Hide** pair, where Hide carries a right-facing collapse chevron), then **Comments (count)** with **Copy all** next to it and two **sort-by-time arrows** (oldest-first / newest-first; click the active one again for document order, and the choice persists), then a single-line **info row** (**Generated on** and **Last comment** timestamps side by side), then a compact one-row group of icon buttons - **Export as Portable**, **Export to Plain HTML**, and **Clear** (the full labels are preserved as `aria-label`s). Every control shows a styled hover/focus tooltip via a dependency-free layer that upgrades the native `title` (moving it to `data-cmh-tip` so the browser tooltip never doubles up); no jQuery or CDN.

**Attribution footer.** A runtime-generated `cm-skip` footer at the bottom of the page shows the layer brand icon, the **version**, the **generated-on** timestamp, and a **Help & about** link that opens the Help modal (the source-repo link, Raise-an-issue link, and author live in Help, not the footer). Like the TOC side menu it is runtime-only, so it is absent from a **Plain HTML** export (where the layer is removed) and regenerates whenever the layer is active. When the comments panel is open the footer stays centered in the visible (non-panel) area. The brand icon is also embedded as the file's favicon and shown in the sidebar meta row and the Help About section.

**Timestamps and the card body.** Comment times render in an unambiguous 24-hour local format with a month NAME (e.g. `Jul 9, 2026, 13:07`, so it reads the same in M/D/Y and D/M/Y locales; no AM/PM) on the card and in the Copy bundle. The card shows reader-facing anchor info only; the internal pinpoint (`in <li> - match 2 of 4`) is omitted from the card but still emitted on the Copy bundle's `Pinpoint:` line for the agent. "Generated on" reads an optional `data-generated` attribute on `#commentRoot` (set it for a deterministic value) and otherwise falls back to the file's last-modified time.

**Document-type bubble.** The bubble shows whether the open file is **Portable** or **Not portable**. Hover **Not portable** to see the reason: the page references nonportable companion assets, has live comments that are not embedded, or still contains embedded comments that were deleted this session and need a re-export to leave the file. Deleting an embedded comment is durable across reload via a tombstone, but the file stays **Not portable** until **Export as Portable** writes a fresh copy.

**Help.** The Help button (sidebar meta row, overflow menu, and the footer **Help & about** link) opens a modal whose content is grouped into **collapsible topics** with a **live search box** (focused on open) that filters topics and their entries as you type and shows an empty-state when nothing matches. Topics cover leaving a comment, managing comments, the panel and toolbar, Portable / Not portable, exporting and sharing, sending comments to an agent, navigation, reading aids, keyboard and accessibility, self-contained and privacy, and an **About** section (layer version, source-repo link `github.com/urikanonov/ai-marketplace`, Raise-an-issue link, and author). It is trusted static content, traps Tab focus inside itself (including the search box and topic summaries), closes on Escape / backdrop / the X, and restores focus.

**Table-of-contents side menu.** When the document has a table of contents (an author `.cm-toc`, else `h2`/`h3` ids), a collapsible section menu appears fixed on the **left on wide screens** (>= 1400px), top-aligned with the toolbar. Entries are **numbered** unless headings already carry their own numbers. It scroll-spies the current section, collapses to `Navigation >>`, expands with `<<`, offers icon-bearing **Expand All** / **Collapse All** when sections are collapsible, and includes icon-bearing **Scroll to Top** / **Scroll to Bottom**. It is `cm-skip` and runtime-generated, so it never appears in plain/portable exports.

**Section deep-links and heading comments.** Every heading inside `#commentRoot` gets a stable id (generated from its text when absent) and becomes a deep-link: a plain click updates the URL to `#<id>` and scrolls there. Hovering a heading shows an Add Comment affordance that comments the whole heading text, so headings are linkable and commentable.

**Collapsible sections and scroll progress.** Every authored `<section>` with a direct heading gets an enlarged, easy-to-click caret. Collapsing hides that section body without removing nodes, and jumping to a comment auto-expands any collapsed ancestors first. A small bottom-right bubble shows scroll percentage and moves left when the comments panel is open.

**Boxed/wider content.** Standalone code blocks and `figure.chart` render as boxed figures, and the template content max width is 1480px for wide reports and dashboards.

**Callouts and theme-safe styling.** For boxed asides, use the theme-aware `cmh-callout` (plus `cmh-callout-info`, `-success`, `-warning`, `-danger`) classes, and the `cmh-lede` box for a lead paragraph. They stay readable in both light and dark themes. Never hardcode colors in report content: use the theme CSS variables (`var(--cp-text)`, `var(--cp-surface)`, `var(--cp-danger-soft)`, and so on) so text never renders dark-on-dark. See [Content conventions](references/content-conventions.md).

**Long `<pre>` blocks wrap.** Content `<pre>` / `<pre><code>` blocks (logs, code) use `white-space: pre-wrap` so long lines wrap instead of overflowing the card horizontally. Diff and mermaid blocks keep their own whitespace handling.

**Clear Comments** wears a persistent warning (danger) color and opens a confirm dialog whose default is **Cancel** (Enter or Escape cancels); only **OK** clears every comment. **Hide** carries a distinct filled color so it reads apart from the outline export buttons.

## Editing the skill (maintainer)

Editing the skill's own layer code is a maintainer task done in the project's source repository, not per generated document; packaged installs do not include that development harness. Per generated document, the only thing to run is `tools/validate.py` below.

## When to use

- The user explicitly asks for inline comments, code-review UI, or "let me leave feedback on this HTML".
- You generated an HTML artifact (plan, report, dashboard, design doc, migration plan) that the user is likely to iterate on across several turns.
- The user wants a structured way to feed section-level feedback back into the conversation instead of pasting prose.

Do not use this skill for:

- Short HTML emails or one-shot views the user will not iterate on.
- HTML that will be rendered inside a sandbox that disables `localStorage` or clipboard APIs.

## Required HTML structure

Five drop-in regions, all included in `dist/PORTABLE.html` and clearly bracketed with `BEGIN: commentable-html - <REGION>` / `END: commentable-html - <REGION>` comments so you can grep them out and paste them as a unit:

1. **CSS** - paste inside any `<style>` block in `<head>`.
2. **HANDLED IDS** - a `<script type="application/json" id="handledCommentIds">[]</script>` block plus a comment explaining its purpose. Paste near the top of `<body>`. The agent appends processed ids here.
3. **EMBEDDED COMMENTS** - a `<script type="application/json" id="embeddedComments">[]</script>` block. Paste immediately after the HANDLED IDS region. **Export as Portable** writes the current comments into it so a review can travel with the file.
4. **COMMENT UI** - toolbar + sidebar + context menu + composer + toast. Paste immediately after the EMBEDDED COMMENTS region, before any visible content.
5. **JS** - the commenting engine, wrapped in an IIFE so nothing leaks into the host page. Paste just before `</body>`, after every other script that renders content.

Plus one structural anchor in the host document:

- **`<main id="commentRoot" data-comment-key="..." data-doc-label="..." data-doc-source="...">`** wrapping everything the user is allowed to comment on. The three `data-*` attributes are the only per-document configuration; everything else in the five regions is byte-identical across documents.
- **`.cm-skip`** class on every UI surface that must be excluded from selection (toolbar, sidebar, menus, composer, toast). The five pasted regions already carry this; only add it manually if you have other floating panels of your own.

If `#commentRoot` is missing entirely the layer falls back to `document.body` with `data-comment-key = "commentable-html:" + location.pathname` and `data-doc-label = document.title`. That is enough to demo the feature on any HTML in one paste, but for a real document you want the explicit attrs so comments do not collide across files served from the same origin.

## Per-document configuration (data attributes)

All per-document state lives as `data-*` attributes on the `#commentRoot` element. No JS edits are required to add the layer to a new document or to upgrade an existing one.

| Attribute | Required | Purpose |
| ------------------ | -------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `data-comment-key` | yes | `localStorage` key for this document's comments. Must be unique per document on the same origin or comments leak across pages. |
| `data-doc-label` | yes | Human-readable name used in the Copy header and Agent Instructions block. e.g. `"Q3 architecture review"`. |
| `data-doc-source` | no | Source path used in the Copy `Source:` line and in the Agent Instructions block (so the agent knows which file to edit). Falls back to `location.pathname`. |

Example:

```html
<main id="commentRoot"
 data-comment-key="migration-plan-comments"
 data-doc-label="Migration Plan review"
 data-doc-source="docs/Archive/Migration-Plan.html">
 ...content...
</main>
```

## Per-comment data shape

Comment records carry pinpoint metadata so the agent can locate text, mermaid, diff, image, and code feedback without reopening the browser. See [Per-comment data shape](references/comment-data-shape.md) for JSON shapes and field details.

## Code blocks

Code selections are commentable by default and keep language, indentation, and fenced-copy formatting. Each commentable block also gets an always-visible top-right **Copy** button. See [Code blocks](references/code-blocks.md) for markup, stored fields, copy buttons, and runtime behavior.

## Kusto query blocks (Run in Azure Data Explorer deep link)

KQL blocks should pair a commentable `<pre><code class="language-kusto">` with a safe Run in Azure Data Explorer deep link. The caption title is the click-to-copy cluster affordance, so do not add a separate cluster chip. See [Kusto query blocks](references/kusto-query-blocks.md) for link generation, data-safety rules, and markup.

## Mermaid diagrams

Mermaid nodes, gantt task labels/bars, sequence/gantt text, and whole diagrams can receive structural comments keyed by diagram index and node id (or `__diagram__`) while raw diagram source stays out of text selection. Pie slices and actors use the whole-diagram path. See [Mermaid diagrams](references/mermaid-diagrams.md) for markup, restore behavior, and loader guidance.

## Code review diffs (side-by-side or inline)

Unified diffs can be rendered as self-contained, line-commentable review blocks with inline and side-by-side layouts plus an in-page **Syntax: on/off** highlighting toggle. See [Code review diffs](references/code-review-diffs.md) for markup, escaping, anchoring, and use cases.

## Charts with tooltips

Chart.js charts are supported when the canvas lives in `figure.chart`, the wrapper is `cm-skip` for text offsets, and init runs after the commentable JS region. The canvas itself is commentable as `imageKind: "chart"`. Chart.js loads from a CDN by default via a guarded loader that falls back gracefully; self-host or inline it for a fully self-contained file. See [Charts with tooltips](references/charts.md) for embedding and verification details.

## Network requirements

The commentable review layer is bundled into the single HTML file - its CSS, state, UI, and runtime all travel inside the document. Optional rich content loads from a CDN: mermaid diagrams and Chart.js charts (and any tooltip library a host page adds) fetch their library from a CDN by default and fall back gracefully when they cannot (mermaid to readable source text, a chart to a blank canvas). For a fully self-contained file that renders identically wherever it is opened, self-host or inline those assets. Treat CDN loading as an explicit choice, since it means the finished report depends on the network to render that content.

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

## Leaving comments (interaction model)

All anchor types use the same Add Comment control and sidebar lifecycle, while duplicate anchors reopen existing comments where possible. See [Interaction model](references/interaction-model.md) for prose, code, diff, mermaid, and image gestures.

## Content conventions (ADO links and cross-references)

Make source references actionable with real ADO links and stable in-page cross-references. See [Content conventions](references/content-conventions.md) for URL shapes and anchor-link rules.

## Export as Portable

The export action downloads a fresh copy with the current comments written into `#embeddedComments`; in nonportable mode it also inlines the companion assets into one portable file. See [Exports](references/exports.md) for merge semantics and implementation details.

## Combined file from a nonportable document

NonPortable exports inline the loaded CSS and runtime from the asset registry so the downloaded file is portable. See [Exports](references/exports.md) for the exact rebuild behavior.

## Export to Plain HTML

Plain export removes the review UI and runtime while keeping the document styling and content intact. See [Exports](references/exports.md) for strip rules, safety checks, and mode differences.

## Add the layer to an existing HTML

Retrofitting is a marker-by-marker copy from `dist/PORTABLE.html` plus a `#commentRoot` wrapper and optional `cm-skip` exclusions. See [Retrofitting](references/retrofitting.md) for the full paste order and host-page checklist.

### Avoiding CSS collisions when retrofitting

See [Retrofitting](references/retrofitting.md) for class, CSS-variable, hidden-state, z-index, reset, and layout collision checks.

## Upgrade an existing instance to a new dist/PORTABLE.html

Upgrades replace the CSS, COMMENT UI, and JS regions while preserving handled ids, embedded comments, and `#commentRoot`. **SHOULD** run the deterministic helper instead of swapping regions by hand (the JS body contains marker-like text, so the JS region END is the LAST occurrence - a naive hand/regex swap truncates it):

```
python tools/upgrade.py <file.html> # upgrade in place from dist/PORTABLE.html
python tools/upgrade.py <file.html> --check # report stale regions without writing
```

It refuses nonportable documents (companion assets), preserves the document's state/content, and self-validates the result. See [Retrofitting](references/retrofitting.md) for the mechanical upgrade recipe.

## Layout recipes

The fixed 400px sidebar needs reserved space when `body.sidebar-open` is active. See [Document layout](references/document-layout.md) for centered, full-bleed, and default-open recipes.

## Copy payload format

Copy all emits a Markdown bundle plus the machine-readable `HANDLED_IDS_JSON` contract. See [Copy payload format](references/copy-payload.md) for the full payload shape and anchor-type differences.

## What the agent does when the user pastes the bundle back

The core loop is in Step 5: act on comments, parse `HANDLED_IDS_JSON`, merge ids into `handledCommentIds`, and tell the user to reload. See [Copy payload format](references/copy-payload.md) for the expanded checklist.

## Limitations to call out

Call out anchor and browser limitations when they affect a generated document, especially dynamic content, mermaid source changes, and clipboard constraints. See [Limitations](references/limitations.md) for the full list.

## Files

Use these files and folders when producing, validating, or maintaining commentable HTML:

- **`dist/PORTABLE.html`** - complete inline template and demo; copy its five regions for standalone mode.
- **`dist/`** - nonportable shell and companion CSS/JS/assets bundle for local iterative documents.
- **`tools/*`** - deterministic, stdlib-only Python helpers you SHOULD prefer over hand-editing (they remove AI variance and are self-validating). Run any with `python tools/<name>.py --help`:
 - `validate.py [--strict] <file>` - structural/invariant checker (run after every retrofit; `--strict` fails on any warning so one run surfaces everything).
 - `new_document.py --content <file|-> --key K|auto --label L [--source S] [--generated ISO]` - build a fresh standalone commentable doc from a content fragment (safely fills the CONTENT region and `#commentRoot` attrs; avoids the duplicate-root footgun; `--key auto` derives a stable key).
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
