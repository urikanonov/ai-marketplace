# Content conventions

## Content conventions (ADO links and cross-references)

When authoring the content inside `#commentRoot`, follow these conventions so the document is navigable and every reference is actionable. Both coexist with the commenting layer - anchor links and external links inside `#commentRoot` do not affect comment offsets or text selection, and a comment anchored on a link is still openable via the hover comment bubble (see step 10 of [Quick verification after retrofitting](validation.md#quick-verification-after-retrofitting) and the [interaction model](interaction-model.md#leaving-comments-interaction-model)), so wrapping highlighted text in an `<a>` is safe.

- **Link every Azure DevOps repo, file, PR, work item, or build reference.** Never leave an ADO repo name, file path, PR number, or work-item id as bare text - wrap it in an `<a href="...">` that points at the actual ADO resource, so a reader can click straight through to the source of every claim. Common URL shapes (org form `https://dev.azure.com/{org}/{project}` or `https://{org}.visualstudio.com/{project}`):
 - Repo: `.../_git/{repo}`
 - File: `.../_git/{repo}?path=/src/foo.cs&version=GB{branch}` (add `&line={n}&lineEnd={n}` to deep-link a line)
 - Pull request: `.../_git/{repo}/pullrequest/{id}`
 - Work item: `.../_workitems/edit/{id}`
 - Build: `.../_build/results?buildId={id}`
 - Wiki page: `.../_wiki/wikis/{wiki}?pagePath=/{path}`

- **Make section cross-references clickable.** When the document has multiple sections and one section refers to another, that reference must be an in-page anchor link, not prose like "see the section above". Give each heading a short, stable, kebab-case `id` derived from its text and link to it:

 ```html
 <h2 id="methodology">Methodology</h2>
 ...
 <p>See <a href="#methodology">Methodology</a> for how these figures were derived.</p>
 ```

 This is also how an appendix (for example, of the source queries or raw data behind each figure) links back and forth with the sections that use it: the appendix entries get ids and each section links to the appendix entry it relies on.

 `tools/validate.py` **warns** when a section cross-reference in the `#commentRoot` prose is left as plain text: directional references ("the section below", "previous section") and named references ("see `<Heading>`" or "`<Heading>` section" for an actual heading) that are not wrapped in an `<a href="#...">`. Linked references and anything inside a `cm-skip` region are ignored, so the check only fires on real, fixable cases.

## Callouts and theme-safe styling

Use the built-in callout classes for boxed asides instead of hand-rolling colors. They read correctly in both the light and dark themes because they use the theme's CSS variables:

- `<div class="cmh-callout cmh-callout-info">...</div>` - a neutral note.
- `cmh-callout-success` - a good outcome.
- `cmh-callout-warning` - a caution.
- `cmh-callout-danger` - the key takeaway or bottom line.

A leading `<strong>` label (for example `<strong>Bottom line.</strong>`) reads well inside any variant. For a boxed intro under the title, wrap the title and lead paragraph in `<header class="cmh-lede">` (or put `class="cmh-lede"` on the lead `<p>`).

**Never hardcode colors in report content.** A hardcoded hex background with no explicit text color (or a color picked for one theme) breaks in the other theme as a dark-on-dark or washed-out block. If you must style custom content, use the theme variables so text stays readable in both themes: `var(--cp-text)`, `var(--cp-surface)`, `var(--cp-surface-soft)`, `var(--cp-border)`, `var(--cp-accent)` / `var(--cp-accent-soft)`, `var(--cp-danger)` / `var(--cp-danger-soft)`, `var(--cp-warning)` / `var(--cp-warning-soft)`, and `var(--cp-success)` / `var(--cp-success-soft)`.

## Author content in real layouts, not stacked headers

Pick the layout that makes the *shape* of the content visible before writing prose. The commenting layer anchors on whatever you produce, so a well-shaped artifact yields sharper comments. Do not translate a Markdown outline 1:1 into HTML.

- **Comparison** of options: side-by-side columns with the same internal structure, a pro/con table, and a hard-metrics row, then a real recommendation. A two-column table reads as a comparison; stacked bullets read as a sequence.
- **Implementation plan**: a milestones strip, a data-flow diagram (mermaid), a risk table, and an explicit "what we are not doing" section.
- **Incident / post-mortem**: a vertical, timestamped timeline and action items with owners.
- **Status report**: shipped / in-flight / blocked columns, one line per item, and a small chart.
- **Code review**: annotations pinned to lines with severity colors, and a "where to focus" note.

commentable-html already makes tables, charts, mermaid, diffs, code, images, and (via `data-cm-part`) widget parts commentable, so these shapes need no extra wiring - only that you author them.

## Taste: restraint over decoration

Bad-looking HTML is worse than good Markdown. Default to a calm, typographic layout and let color carry meaning, not mood.

- **Avoid the default-AI look**: gradient hero banners, emoji section headers, four shades of indigo doing nothing, glass morphism / frosted blur, cards-on-gray everywhere, and centered everything. If three of those appear, restart the design.
- **Color must do work.** If a color encodes severity, status, category, or an axis, keep it; if it is there for vibe, remove it. Use the theme `--cp-*` variables (above) so every color adapts to light and dark and never renders dark-on-dark.
- **Type and measure.** Body text reads best at roughly 60-75 characters per line. The layer already caps the measure of top-level paragraphs so prose stays readable inside the wide content shell, while tables, figures, code, and diffs keep the full width. Keep paragraphs to that rhythm and do not fight the cap with hardcoded widths.

## Matching a product's design system

To make a generated report match a product's identity, map that product's design tokens onto the layer's `--cp-*` CSS variables **once**, in a small `<style>` in the document head, and reuse it:

```html
<style>
  :root {
    --cp-accent: #5b6cff;    /* the product's primary / brand color */
    --cp-accent-hover: #4a59e0;
    --cp-text: #1a1a1f;      /* body ink */
    --cp-surface: #ffffff;   /* card / panel background */
    --cp-border: #e7e5df;
    /* map only the tokens you have; the rest keep their defaults */
  }
</style>
```

Keep it deterministic: override only the variables you can read directly from the product's theme (Tailwind config, `theme.ts`, CSS custom properties), and leave the rest at their defaults rather than inventing values. Because the layer's own UI also reads these variables, the review chrome stays consistent with the themed content.
