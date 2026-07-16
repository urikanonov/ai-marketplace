# Comment data shape


## Contents

- [Per-comment data shape](#per-comment-data-shape)
  - [Text comments (default)](#text-comments-default)
  - [Mermaid-node comments (`anchorType: "mermaid"`)](#mermaid-node-comments-anchortype-mermaid)
  - [Diff-line comments (`anchorType: "diff"`)](#diff-line-comments-anchortype-diff)
  - [Widget/part comments (`anchorType: "widget"`)](#widgetpart-comments-anchortype-widget)
  - [Document-wide comments (`anchorType: "document"`)](#document-wide-comments-anchortype-document)

## Per-comment data shape

Each comment captures concrete pinpoint info, not just the user's note - enough for the agent to find the exact spot in the source files without re-opening the document.

### Text comments (default)

```json
{
 "id": "c<timestamp><random>",
 "quote": "exact selected text",
 "note": "user's comment body",
 "start": 1234,
 "end": 1267,
 "section": "nearest preceding heading text, or null",
 "headingPath": [{"level":1,"text":"..."}, {"level":2,"text":"..."}, ...],
 "before": "...up to ~80 chars before the selection",
 "after": "up to ~80 chars after the selection...",
 "occurrence": 2,
 "occurrenceTotal": 5,
 "blockTag": "li",
 "blockText": "full text of the containing <li>/<p>/<td>/... element, capped at ~280 chars",
 "isCode": false,
 "codeLanguage": null,
 "createdAt": "ISO-8601",
 "updatedAt": "ISO-8601 (only set after edit)"
}
```

### Mermaid-node comments (`anchorType: "mermaid"`)

When the user clicks the floating **Add Comment** button on a rendered mermaid node, gantt task/bar, or sequence/gantt text, the comment is anchored to the diagram + node rather than to character offsets. When the user clicks **Comment on diagram**, `nodeKey` is `"__diagram__"` and the anchor is the whole diagram:

```json
{
 "id": "c<timestamp><random>",
 "anchorType": "mermaid",
 "diagramIndex": 0,
 "nodeKey": "AsmGate",
 "nodeLabel": "ASM machine?",
 "quote": "ASM machine?",
 "note": "user's comment body",
 "section": "Processor flow",
 "headingPath": [{"level":1,"text":"..."}, {"level":2,"text":"Processor flow"}],
 "createdAt": "ISO-8601",
 "updatedAt": "ISO-8601 (only set after edit)"
}
```

- **`diagramIndex`** - 0-based position of the `<pre class="mermaid">` / `<div class="mermaid">` host inside `#commentRoot`, in document order.
- **`nodeKey`** - stable identifier for the node. Resolved in this order: `nodeEl.dataset.id` (mermaid v10+ sets this from the source label, e.g. `AsmGate`), the source name extracted from a mermaid-generated id such as `flowchart-AsmGate-3` or `gantt-Task-3`, a raw `id:<id>` fallback, or `label:<node text content>`. Whole-diagram comments use `__diagram__`.
- **`nodeLabel`** - human-readable node text, whitespace-normalized. Useful for the agent because mermaid sources usually contain this verbatim, e.g. `AsmGate{"ASM machine?"}`.
- **`section`/`headingPath`** - computed by walking every `H1-H6` preceding the diagram host (same algorithm as text comments, just keyed on the host position rather than a text offset). Lets the agent locate the source diagram by section without grepping the entire markdown.
- No `start/end/before/after/blockTag/blockText` - those are text-anchor fields and are intentionally absent.
- Pie slices and actors are whole-diagram-only from the user's point of view, so expect `nodeKey: "__diagram__"` for that feedback.

### Diff-line comments (`anchorType: "diff"`)

When the user hovers a line inside a rendered diff block and clicks the floating **Add Comment** button, the comment is anchored to the logical diff line - by `(diffIndex, lineKey)` - rather than to character offsets, so it survives the side-by-side / inline layout toggle, reload, copy, and Export as Portable:

```json
{
 "id": "c<timestamp><random>",
 "anchorType": "diff",
 "diffIndex": 0,
 "lineKey": "3",
 "side": "new",
 "lineType": "add",
 "oldNo": null,
 "newNo": 2,
 "diffLabel": "src/reducer.py",
 "quote": "+ acc = x if acc is None else fn(acc, x)",
 "isCode": true,
 "note": "user's comment body",
 "section": "Code review diffs",
 "headingPath": [{"level":2,"text":"Code review diffs"}],
 "createdAt": "ISO-8601"
}
```

- **`diffIndex`** - 0-based position of the `pre.cmh-diff` / `div.cmh-diff` host inside `#commentRoot`, in document order.
- **`lineKey`** - stable index of the logical line within the parsed unified diff. Both layouts render the same logical lines, so this key re-attaches the highlight regardless of side-by-side vs inline.
- **`lineType`** - `add` | `del` | `ctx`. **`oldNo`/`newNo`** - the old-file / new-file line numbers (one is `null` for pure add/del lines). **`side`** - which pane the anchor was created from (`old`/`new`/`both`).
- **`diffLabel`** - the file name from the block's `data-diff-label`, surfaced in the sidebar pinpoint and Copy bundle (e.g. `Anchor: diff src/reducer.py, added line 2`).
- **`quote`** - the diff line including its `+`/`-`/space sign; emitted as a fenced ```` ```diff ```` block in Copy all. `isCode` is always `true`.
- No `start/end` - like mermaid comments, diff comments are skipped by `backfillContext()` and restored by `setupDiffLayer()`.

### Widget/part comments (`anchorType: "widget"`)

A part of a commentable widget (any `data-cm-part` inside a `data-cm-widget`, including an SVG `<g>`) anchors by widget name + part id rather than by character offsets:

```json
{
 "id": "c<timestamp><random>",
 "anchorType": "widget",
 "widget": "triage",
 "part": "t-101",
 "partLabel": "Add SSE backpressure",
 "slot": "Now",
 "quote": "Add SSE backpressure",
 "note": "user's comment body",
 "section": "nearest preceding heading text, or null",
 "headingPath": [{"level":2,"text":"..."}],
 "createdAt": "ISO-8601"
}
```

- **`widget`/`part`** - the `data-cm-widget` name and `data-cm-part` id; the highlight restores by this pair via `setupWidgetLayer()`.
- **`partLabel`** - the `data-cm-part-label` (or the part's trimmed text). **`slot`** - the `data-cm-slot` the part was in at save time, or `null`.
- No `start/end` - like mermaid/diff/image comments, widget comments are skipped by the text backfill.
- Widget **layout changes** are NOT stored as comments: they are computed live from the DOM against the load-time slot baseline and surfaced only in the sidebar and the Copy-all "Widget layout changes" section.

### Document-wide comments (`anchorType: "document"`)

A comment not tied to any element, raised by right-clicking empty space:

```json
{
 "id": "c<timestamp><random>",
 "anchorType": "document",
 "quote": "(document-wide)",
 "note": "user's comment body",
 "section": null,
 "headingPath": [],
 "createdAt": "ISO-8601"
}
```

- No anchor fields and no highlight; it sorts to the top of the panel and copies as `Anchor: document-wide (not tied to a specific element)`.

All context fields for text comments are computed by `captureContext(start, end, range)` at save time:

- **`headingPath`** - full heading breadcrumb (H1 -> H2 -> H3 ...) by walking every preceding heading and popping deeper-or-equal levels each time a higher-level heading appears.
- **`section`** - last entry's text (kept for backward compatibility with older comments).
- **`occurrence` / `occurrenceTotal`** - 1-based index and count of exact matches for `quote` within the current section (bounded by the next heading of same-or-higher level). `occurrenceTotal === 1` means the quote is unique inside its section; higher values mean the agent must use the surrounding context to disambiguate.
- **`blockTag` / `blockText`** - tag (lowercase) of the nearest containing block-level ancestor (`<p>`, `<li>`, `<td>`, `<th>`, `<h1-h6>`, `<blockquote>`, `<pre>`, `<dd>`, `<dt>`, etc.) and its full whitespace-normalized text, capped at ~280 chars. This is the single most useful field for the agent because it can grep this exact string against the source markdown/HTML to locate the comment.

On load, `backfillContext()` repopulates all of these for any pre-existing text comments that lack them. Mermaid comments are skipped by the backfill (they have no `start`/`end`) and their highlights are restored separately by `setupMermaidLayer()`. Both the sidebar card and the copy payload surface every field, so an isolated quote like `"Archive"` is always shipped with its disambiguating heading path, containing block, and match index.

