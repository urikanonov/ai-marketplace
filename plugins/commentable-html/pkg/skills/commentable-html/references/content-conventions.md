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
