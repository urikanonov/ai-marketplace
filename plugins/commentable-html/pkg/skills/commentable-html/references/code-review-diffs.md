# Code review diffs

Detailed reference content moved out of `SKILL.md` to keep the core skill under the governance line limit.

## Code review diffs (side-by-side or inline)

The layer renders unified-diff blocks into a colored, commentable code-review view. It is fully offline and self-contained, with no diff2html or CDN dependency.

### Markup

Put a unified diff as the text content of a `pre` or `div` with `class="cmh-diff"`. Name the file with `data-diff-label` and optionally set `data-diff-lang` for syntax highlighting:

```html
<pre class="cmh-diff" data-diff-label="src/reducer.py" data-diff-lang="python">@@ -1,5 +1,6 @@
 def reduce(items, fn, acc=None):
-    for x in items:
-        acc = fn(acc, x) if acc is not None else x
+    for x in items:
+        acc = x if acc is None else fn(acc, x)
+    # None is now a valid seed value
     return acc
</pre>
```

- **Do NOT add `cm-skip`** yourself. The layer replaces the block with a `.cm-skip` rendered host automatically.
- **HTML-escape the diff text.** Write `<` as `&lt;`, `>` as `&gt;`, and `&` as `&amp;`. `tools/validate.py` errors on raw tags inside `pre.cmh-diff`.
- Standard unified-diff syntax is supported. Very large diffs over 2000 logical lines render as inert raw text with per-line commenting disabled.

### How it behaves at runtime

1. `setupDiffLayer()` parses each `pre.cmh-diff` / `div.cmh-diff`, stores the raw diff in a hidden text script, and renders a `.cmh-diff-view`.
2. Each diff has a **Side-by-side view** / **Inline view** toggle. The choice persists per document in `localStorage` and defaults to side-by-side.
3. If the language is known, each diff has a **Syntax: on/off** toggle. Runtime highlighting is offline, defaults on, persists per document, and falls back to in-memory state when `localStorage` is blocked. The tokenizer wraps tokens and gaps with escaped `.cmh-code-*` spans, so HTML cannot leak from diff text.
4. Hovering a changed or context line shows **Add Comment**; clicking it or pressing <kbd>Enter</kbd> on a focused line comments the whole line. Selecting a region within one diff line comments just that substring.
5. Saving anchors the comment to `(diffIndex, lineKey)` plus `(subStart, subEnd)` for region comments. Highlights survive layout toggles, reload, copy, and **Export as Portable**.
6. **Copy all** emits each diff comment with `Anchor: diff <label>, <added|removed|context> line <n>` and the quote as a fenced diff block.

### When to use it

Use a diff block whenever the artifact is a code review or a plan whose change is best shown as a before/after. For non-diff before/after values, prefer a normal two-column table.

