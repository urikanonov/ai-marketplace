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
- Every eligible code block is wrapped at runtime in `.cmh-code-wrap` and gets an always-visible top-right **Copy** button. The button is `cm-skip`, so it never affects selections or text offsets.

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

Highlight code blocks with `tools/highlight_code.py`, a standard-library highlighter that bakes token spans at author time:

```bash
python tools/highlight_code.py <language> "<code>" # code as an argument
python tools/highlight_code.py <language> < snippet.txt # or piped on stdin
python tools/highlight_code.py --list # supported languages
```

It emits a `<pre><code class="language-<lang>">...</code></pre>` block whose tokens are wrapped in `<span class="cmh-code-...">` (kw, fn, str, num, com, op). The spans only add structure, so `textContent` is the exact original code (LF-normalized), selecting and commenting still see raw code, and every character is HTML-escaped. The layer CSS ships token colors for light and dark themes. Unknown languages fall back to a safely escaped unhighlighted block.
