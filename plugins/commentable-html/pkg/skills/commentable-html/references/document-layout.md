# Document layout


## Theme (light by default)

The document defaults to a **light** theme. The generated template sets `data-theme="light"` on `<html>` and keeps light unless overridden:

- `?clawpilotTheme=dark` forces the dark theme.
- `?clawpilotTheme=auto` follows the OS `prefers-color-scheme`.
- no parameter is always light.

Default to a light document unless the request is explicitly dark.

## Table of contents (multi-section documents)

For a document with roughly **4+ top-level sections**, add a table of contents so the reader can jump between sections. The layer ships `.cm-toc` styling, so this markup needs no host CSS:

```html
<nav class="cm-toc" aria-label="Table of contents">
 <div class="cm-toc-title">Contents</div>
 <ol>
 <li><a href="#section-id">Section title</a></li>
 </ol>
</nav>
```

- Give each heading a stable, kebab-case `id` derived from its text.
- Place the `nav.cm-toc` at the top of `#commentRoot`, after any intro paragraph.
- Keep it inside `#commentRoot` as normal content. Anchor links still work because highlighted links can be opened through the hover comment bubble.
- The runtime side menu appears on wide screens. It uses author `.cm-toc` links when present, otherwise `h2`/`h3` ids. It numbers entries, scroll-spies the active section, collapses to `Navigation >>`, expands with `<<`, and adds **Scroll to Top** / **Scroll to Bottom**.
- If collapsible sections exist, the side menu also adds **Expand All** and **Collapse All**.
- A runtime `cm-skip` scroll-progress bubble appears at bottom-right and shows the percent scrolled. It moves left when the comments panel is open.

## Sections and document layout

Structure a document as a sequence of `<section>` blocks, each led by a heading. The layer renders top-level sections as cards (surface background, 1px border, 16px radius, padding, and soft shadow) in both light and dark.

- Wrap each top-level topic in its own `<section>` with an `<h2>` and use `<h3>` for sub-topics.
- Every authored `<section>` with a direct heading gets a caret. The caret collapses or expands the section body without removing or reordering nodes, so comment offsets stay valid.
- Jumping to a comment auto-expands collapsed ancestor sections before scrolling.
- Headings get stable ids when missing. A plain click deep-links to the heading, and a hover Add Comment affordance comments the whole heading text.
- For status labels use `<span class="badge">`, `badge ok`, `badge warn`, or `badge danger` rather than ad-hoc inline styles.
- Standalone code blocks and `figure.chart` render as boxed figures. This keeps logs, code, and charts readable without host CSS.

## Tables

The layer ships default `#commentRoot table` styling (collapsed borders, full width, subtle header background, and zebra-striped body rows). Emit plain `<table>` / `<thead>` / `<tbody>` markup inside `#commentRoot`.

Rectangular tables are sortable automatically:

- A table opts in only when it has a header row and every body row has the same cell count with no `colspan` or `rowspan`.
- Each header cell gets up/down chevrons. Click cycles `asc`, `desc`, then original order.
- Numeric-looking columns sort numerically; empty cells sort first in ascending order, and the comparator avoids `NaN` arithmetic.
- Sort state persists in `localStorage` and re-applies before comment restore. After a sort, text-comment offsets are recomputed from live marks. During export, comments are canonicalized back to original row order so a recipient without the sort state gets valid anchors.

For a before/after of code, prefer a [code review diff block](code-review-diffs.md), not a table.

## Layout recipes

The sidebar is `position: fixed` with width 400px. When `body.sidebar-open` is set, the page should reserve room for it.

### Recipe A: centered max-width layout (most pages)

```css
.app { max-width: 1480px; margin: 0 auto; padding: 2.5rem 1.5rem 4rem; }

body.sidebar-open .app { padding-right: 1.5rem; }

@media (min-width: 1100px) {
 body.sidebar-open .app {
 max-width: none;
 margin: 0;
 padding-left: 2rem;
 padding-right: calc(400px + 2rem);
 }
}

@media (min-width: 1900px) {
 body.sidebar-open .app {
 padding-left: calc((100vw - 400px - 1480px) / 2);
 padding-right: calc(400px + (100vw - 400px - 1480px) / 2);
 }
}
```

### Recipe B: full-bleed dashboard layout

```css
body.sidebar-open main { padding-right: 420px; }
```

### Default sidebar state

To start with the sidebar open when comments are restored:

```html
<body class="sidebar-open">
```

The JS toggles this class as the user shows or hides the panel.

