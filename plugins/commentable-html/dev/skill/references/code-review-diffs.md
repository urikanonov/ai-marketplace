# Code review diffs


## Code review diffs (side-by-side or inline)

The layer renders unified-diff blocks into a colored, commentable code-review view. It is fully self-contained, with no diff2html or CDN dependency.

### Markup

Put a unified diff as the text content of a `pre` or `div` with `class="cmh-diff"`. Name the file with `data-diff-label` and optionally set `data-diff-lang` for syntax highlighting:

```html
<pre class="cmh-diff" data-diff-label="src/reducer.py" data-diff-lang="python">@@ -1,5 +1,6 @@
 def reduce(items, fn, acc=None):
- for x in items:
- acc = fn(acc, x) if acc is not None else x
+ for x in items:
+ acc = x if acc is None else fn(acc, x)
+ # None is now a valid seed value
 return acc
</pre>
```

- **Do NOT add `cm-skip`** yourself. The layer replaces the block with a `.cm-skip` rendered host automatically.
- **HTML-escape the diff text.** Write `<` as `&lt;`, `>` as `&gt;`, and `&` as `&amp;`. `tools/validate/validate.py` errors on raw tags inside `pre.cmh-diff`.
- Standard unified-diff syntax is supported. Very large diffs over 2000 logical lines render as inert raw text with per-line commenting disabled.

### How it behaves at runtime

1. `setupDiffLayer()` parses each `pre.cmh-diff` / `div.cmh-diff`, stores the raw diff in a hidden text script, and renders a `.cmh-diff-view`.
2. Each diff has a **Side-by-side view** / **Inline view** toggle. The choice persists per document in `localStorage` and defaults to side-by-side.
3. If the language is known, each diff has a **Syntax: on/off** toggle. Runtime highlighting stays in-page, defaults on, persists per document, and falls back to in-memory state when `localStorage` is blocked. The tokenizer wraps tokens and gaps with escaped `.cmh-code-*` spans, so HTML cannot leak from diff text.
4. Hovering a changed or context line shows **Add Comment**; clicking it or pressing <kbd>Enter</kbd> on a focused line comments the whole line. Selecting a region within one diff line comments just that substring.
5. Saving anchors the comment to `(diffIndex, lineKey)` plus `(subStart, subEnd)` for region comments. Highlights survive layout toggles, reload, copy, and **Export as Shareable**.
6. **Copy all** emits each diff comment with `Anchor: diff <label>, <added|removed|context> line <n>` and the quote as a fenced diff block.
7. Selecting text within one side highlights only that side, even when the selection spans several rows. Normal browser **Copy** copies only the selected source text, without line numbers, diff markers, or the opposite side. Code and unclassified diffs preserve source line breaks and blank lines; visual wrapping adds no newlines.
8. For prose, use `diff_block.py --lang text` (or `data-diff-lang="text"`). Plain-text `.txt` labels also select prose copying. Consecutive nonblank source lines copy with a space between them, while blank paragraph separators and partial selection endpoints survive. Explicit `plain`, `plaintext`, and `prose` language labels behave the same way. Code and Markdown diffs keep their source formatting; an unknown language is never guessed to be prose.

### When to use it

Use **Copy before** or **Copy after** in the diff header to copy all source lines supplied
for that side, including shared context, in either layout. The buttons follow the same
prose/code formatting policy as selected-text copying and can copy an empty side.
They do not reconstruct original-file lines omitted from a partial diff. On oversized
raw diffs the buttons are disabled; header controls wrap on narrow screens.

Use a diff block whenever the artifact is a code review or a plan whose change is best shown as a before/after. For non-diff before/after values, prefer a normal two-column table.
