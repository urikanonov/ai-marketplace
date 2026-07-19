# Code blocks


## Code blocks

Any `<pre>` or `<pre><code>` block inside `#commentRoot` is commentable by default. The layer captures extra metadata for code selections and renders them differently end-to-end so newlines and indentation survive.

### Markup

```html
<pre><code class="language-csharp">
public sealed class FlakeFixer
{
 public void Run() => throw new NotImplementedException();
}
</code></pre>
```

- **Do NOT add `cm-skip`** to a code block. That disables comments on it. The only `<pre>` that should still carry `cm-skip` is `<pre class="mermaid">`.
- **Optional `class="language-XXX"`** on the inner `<code>` is picked up as `codeLanguage` and emitted in the Copy bundle's fence.
- **Optional `data-code-caption="..."`** on the `<pre>` renders a caption/filename line above the block (for example `data-code-caption="trigger.kql"`). See "Optional caption / filename line" below.
- Every eligible code block is wrapped at runtime in `.cmh-code-wrap` and gets an always-visible top-right **Copy** button. The button is `cm-skip`, so it never affects selections or text offsets.

### Optional caption / filename line

Add `data-code-caption` to the `<pre>` to name a code block's source (a filename like `trigger.kql`, or a short description):

```html
<pre data-code-caption="trigger.kql"><code class="language-kusto">SigninLogs
| take 10</code></pre>
```

The runtime renders the value as a `cm-skip` `.cmh-code-caption` bar above the code, inside the block's `.cmh-code-wrap` (which gains a `cmh-has-caption` class), joined seamlessly to the framed block. It is styled consistently in report and deck modes. Because the caption is non-selectable `cm-skip` chrome (like the language pill and Copy button), it stays out of text selection, the offset system, and the Copy payload, so it does not affect syntax highlighting or commenting on the code. An empty or whitespace-only value renders nothing, and a KQL figure (`figure.cmh-kql`) keeps its own `.cmh-kql-cap` and never gets a second caption. Exports serialize the pristine document rather than the runtime-mutated DOM, so the `data-code-caption` opt-in survives Export Offline / Portable and the caption re-renders on reopen without duplicating.

### Per-comment additions

Code-block comments are stored as regular text comments with two extra fields:

- **`isCode: true`** - set automatically when the selection lives inside a `<pre>`.
- **`codeLanguage: "csharp" | null`** - parsed from a `language-XXX` class on the inner `<code>`, lowercased.

### How it behaves at runtime

1. Highlights use `box-decoration-break: clone` so a multi-line code selection paints cleanly on each wrapped line.
2. The composer quote preview and sidebar card render in monospace with `white-space: pre-wrap`.
3. The pinpoint shows `code (csharp)` or `code block` instead of `<pre>`.
4. The Copy bundle emits a fenced code block and skips the prose-only `In context:` / `Containing <pre>:` lines.
5. The per-block **Copy** button copies the block's raw `textContent` without the trailing newline and shows a toast.

### Syntax highlighting (author-time, self-contained)

Highlight code blocks with `tools/blocks/highlight_code.py`, a standard-library highlighter that bakes token spans at author time:

```bash
python tools/blocks/highlight_code.py <language> "<code>" # code as an argument
python tools/blocks/highlight_code.py <language> < snippet.txt # or piped on stdin
python tools/blocks/highlight_code.py --list # supported languages
```

It emits a `<pre><code class="language-<lang>">...</code></pre>` block whose tokens are wrapped in `<span class="cmh-code-...">` (kw, fn, str, num, com, op). The spans only add structure, so `textContent` is the exact original code (LF-normalized), selecting and commenting still see raw code, and every character is HTML-escaped. The layer CSS ships token colors for light and dark themes. Unknown languages fall back to a safely escaped unhighlighted block.

### Highlighting is baked and verified automatically

Never ship a `language-XXX` block that renders as plain monochrome text. Three layers make that hard to get wrong:

- **Bake it in one pass.** `tools/blocks/highlight_document.py <file.html>` highlights every raw, language-labelled `<pre><code>` block in a file at once (aliases like `cs` -> `csharp` resolved); an already-highlighted block, an inline `<code>`, and a non-highlightable label (`language-text`, `language-kusto`) are left untouched. `tools/authoring/finalize.py` runs this step by default (skip it with `--no-highlight`), so the standard finalization bakes highlighting.
- **The validator flags a miss.** `tools/validate/validate.py` warns when a `language-XXX` block for a highlightable language has no `cmh-code-*` spans, and `--strict` turns that warning into a handoff failure, so a block that slipped through is caught before the file reaches the user.
- **The runtime is a safety net.** If a labelled block still ships unhighlighted, the runtime tokenizes it on load with the same `cmh-code-*` classes, so the reader always sees highlighting instead of monochrome text. Baking is still preferred (it survives with scripts disabled and in a Plain HTML export).
