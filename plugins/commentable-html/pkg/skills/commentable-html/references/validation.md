# Validation


## Validating a generated file (tools/validate.py)

`tools/validate.py` is a standard-library-only Python script (no third-party packages) that codifies the skill's structural invariants so a generated or augmented file can be checked automatically. **MUST** run it before handing a file to the user whenever Python is available (`python` or `python3`); only skip it when Python is not installed:

```
python tools/validate.py --strict path/to/file.html [more.html ...]
```

It prints one `ERROR` / `WARNING` line per issue. By default it exits `0` when every file passes (warnings allowed) and `1` when any file has errors; `--strict` also fails on any warning, so a single run surfaces *everything* to fix and you iterate until it reports `OK (0 warning(s))`. When the document embeds Chart.js charts (a `<canvas>` is present), it **also** runs the chart-embedding checks automatically (see `charts.md`); pass `--charts-only` or `--layer-only` to run just one half. If Python is not installed, skip it and fall back to the manual [Quick verification after retrofitting](#quick-verification-after-retrofitting) checks.

**Errors (block - the file will not work):**

- Each of the five regions (CSS, HANDLED IDS, EMBEDDED COMMENTS, COMMENT UI, JS) appears exactly once, in order, with JS last.
- Exactly one `id="commentRoot"` element carrying a non-empty `data-comment-key` (a missing `data-doc-label` or `data-doc-source` is a warning, not an error, since the layer falls back to the document title / path).
- `<script id="handledCommentIds">` and `<script id="embeddedComments">` are present, are `type="application/json"`, each contains a valid JSON array, and each id appears **exactly once** (a duplicate would make `getElementById` bind a decoy block). Any `handledCommentIds` id outside the safe pattern `^c[a-z0-9]{6,63}$` is an error (mark_handled.py refuses to edit such a file).
- The JS region contains exactly one real `</script>` (a literal `</script>` in the body must be escaped as `<\/script>`).
- Every structural UI id the JS wires up is present (`sidebar`, `commentList`, `contextMenu`, `mermaidAddBtn`, `hlBubble`, `toast`, the toolbar/sidebar buttons, `menuComment`).
- The `--cp-*` theme variables are defined.
- A `<pre class="cmh-diff">` diff block contains a raw HTML tag (unescaped diff text is an HTML-injection hazard - escape `<`/`>`/`&`).

**Warnings (advisory):**

- `#commentRoot` has no `data-doc-source`.
- An unscoped `[hidden] { display: none }` rule exists (should be `.cm-skip[hidden], .cm-skip [hidden]`), or the scoped rule is missing.
- Export/Import UI is present (removed before the 1.0.0 release).
- A mermaid block is missing `class="cm-skip"`.
- A `cmh-kql-run` ("Run in Azure Data Explorer") link does not point at `https://dataexplorer.azure.com/`, or uses `target="_blank"` without `rel="noopener"`.
- A **section cross-reference in prose is not a link**. The checker reads the `#commentRoot` prose with `<a>` text and `cm-skip` regions removed, so only UNLINKED references remain, then flags directional references ("the section below", "previous section") and named references ("see `<Heading>`", "`<Heading>` section" where `<Heading>` is an actual heading in the document). The fix is to wrap the reference in an in-page anchor (`<a href="#section-id">`); detection is deterministic, the fix is the author's.
- A **mermaid diagram will not render on open**. When the document has `pre`/`div.mermaid` blocks, the checker warns if there is no mermaid loader script, if the loader never triggers a render (no `.run()` call and `startOnLoad` is not `true`), or if the loader is hidden behind a URL query-param gate (e.g. `?mermaid=1`) so the diagrams stay as source text by default. Mermaid must render by default; do not gate it.

The checker parses the document with a tolerant HTML parser and reads real elements, attributes and `<script>` bodies (not a regex over raw text), so an `id="..."` sitting inside another attribute's value, a `>` inside a quoted attribute, or example markup inside a comment / `<pre>` / a JS string literal does not trigger a false positive.

When a `<canvas>` is present, additional **chart** checks run: `cm-skip` on the canvas wrapper (not the `<figure>`), valid non-empty chart-data JSON with no `</script>` / `<!--` breakout, chart init after the JS END marker **and** after the loader, canvas `role`/`aria-label`, and a `typeof Chart` network-failure guard. Use a local or inline Chart.js loader by default; if a CDN loader is explicitly chosen, pin it and add SRI plus `crossorigin`. See [Charts with tooltips](charts.md).


## Quick verification after retrofitting

1. Reload the page. No console errors.
1b. **Confirm your content is the one that rendered, not the template demo.** The `#commentRoot` should show your document (your `<h1>`/sections), not the "Commentable HTML demo" playground. If you see the demo, your content swap targeted the wrong `<main id="commentRoot">` (the commented example) and got buried in a comment - re-run against the last/real root. `validate.py` catches this automatically.
2. Select text inside `#commentRoot` -> popup menu appears automatically just below the selection. Right-click on the same selection also opens it.
3. Save a comment -> highlight appears and sidebar card renders.
4. Reload the page -> highlight is restored from `localStorage`.
5. Click **Copy all** -> clipboard contains the Markdown bundle with `HANDLED_IDS_JSON`.
6. Append one of the ids to the `<script id="handledCommentIds">` array manually and reload -> that comment is gone, others remain, toast confirms the count. **Click Copy all again -> the handled comment must not appear in the output.**
7. **(If the document contains mermaid diagrams.)** Wait for mermaid to render. Hover a node, gantt task label/bar, or sequence/gantt text -> `Add Comment` appears. Hover empty diagram area -> `Comment on diagram` appears. Save -> the target gains `class="cm-mermaid-hl"` and a sidebar card. Reload -> the ring is restored after mermaid finishes. Append the mermaid comment id to `handledCommentIds` and reload -> the ring is gone and the comment is pruned from **Copy all**.
8. Click **Export as Portable**. The browser downloads a fresh copy renamed to `<stem>-portable.html` (or `commentable-portable.html` if the URL had no `.html` segment). Existing `-comments` or `-portable` suffixes should not stack. Open the downloaded copy and confirm `<script id="embeddedComments">` contains the JSON array of comments. **Edge case:** seed `localStorage` and the embedded block with two comments that share an id but differ in `updatedAt`, reload -> the entry with the later `updatedAt` wins; ids only in one side are kept.
9. **(If the document contains code blocks.)** Select a multi-line span across a `<pre><code>` block -> popup menu appears, the composer shows the selection in monospace with `white-space: pre-wrap` preserved, and the highlight paints a clean rectangle on every wrapped visual line. Save -> sidebar card pin reads `code (lang)` or `code block`. Click **Copy all** -> the comment's `Quoted text:` is a fenced ` ``` ` block (with language when known), and the `In context:` / `Containing <pre>:` lines are absent.
10. **(If a highlight can wrap a link.)** Hover a highlighted span that wraps or sits inside an `<a>` -> a small comment bubble (`#hlBubble`) appears at its top-right. Click the bubble -> the comment opens in the sidebar and the link is NOT navigated. Clicking the link text itself still follows the link. Start a drag-select across a highlight -> the bubble must NOT pop mid-drag; scroll the highlight off-screen -> the bubble hides rather than clinging to the viewport edge.

If any of those steps fails, the most likely cause is content rendered after the commenting JS ran (anchors empty), a missing `.cm-skip` on a UI element catching the selection event, or - for mermaid - a host page that loads mermaid with `startOnLoad: true` via async ESM import without calling `mermaid.run()` after the import resolves (the diagram block never gets a `data-processed="true"` stamp and the layer never attaches). See "Mermaid loader (host page responsibility)" for the recommended pattern.

For step 8, the most common failure modes are: a literal `</script>` in the JS region (breaks out of the surrounding `<script>` tag - always escape as `<\/script>` in source); a missing EMBEDDED COMMENTS region (the save throws `Could not find <script id="embeddedComments">`); or a sandboxed iframe that strips the download permission (the click is silently no-oped).

