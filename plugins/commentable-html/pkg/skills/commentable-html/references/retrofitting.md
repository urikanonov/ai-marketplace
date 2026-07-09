# Retrofitting

Detailed reference content moved out of `SKILL.md` to keep the core skill under the governance line limit.

## Add the layer to an existing HTML

The five `BEGIN/END: commentable-html v2 - <REGION>` blocks in `TEMPLATE.html` are designed to be copied verbatim into another document - no JS or CSS edits required. The layer is built to overlay an arbitrary existing page: every style is namespaced under a `cm-` class (plus `mark.cm-hl` and a scoped `.cm-skip[hidden]` rule), and the only globals it introduces are the `:root` / `html[data-theme="dark"]` blocks that define the `--cp-*` variables.

1. **Open `TEMPLATE.html`** and locate the five region pairs. Each region is a single contiguous block bracketed by HTML or CSS comments stamped `commentable-html v2`.
2. **Paste CSS region** at the end of any `<style>` block in `<head>` (or create one). It is self-contained: it ships the `--cp-*` variables it needs inside its own `:root` / `html[data-theme="dark"]` blocks, so you do not have to import a theme.
3. **Paste HANDLED IDS region** as the first child of `<body>`.
4. **Paste EMBEDDED COMMENTS region** immediately after the HANDLED IDS region. Leave its payload as `[]`; **Export as Portable** is what writes into it.
5. **Paste COMMENT UI region** immediately after the EMBEDDED COMMENTS region.
6. **Paste JS region** at the very end of `<body>`, after every other script that renders content. The IIFE wrapper ensures none of the script's local variables (`root`, `comments`, `COMMENT_KEY`, ...) leak into the host page's global scope.
7. **Mark the content root.** Prefer adding `id="commentRoot"` plus the `data-*` attributes to the host's existing outermost content container rather than introducing a new `<main>` that could change the host's margins or layout. If there is no single wrapper, add `<main id="commentRoot" data-comment-key="..." data-doc-label="..." data-doc-source="...">` around the body content. Pick a unique `data-comment-key` per document. **If you are scripting the swap of the demo content**, remember `TEMPLATE.html` has an *example* `<main id="commentRoot">` inside its top-of-file documentation comment (placeholder key `my-doc-v1`); target the **last** `<main id="commentRoot">` (the real one, inside `<body>`), not the first, or your content ends up commented out and the demo renders. See the pitfall note in Step 3.
8. **Add `class="cm-skip"`** to any of your own pre-existing floating panels, modals, toolbars, navs, or sticky headers that should not receive comments. Mermaid blocks should keep `cm-skip` too (the mermaid layer attaches via the `mermaid` class, not via the selection layer).
9. **Adjust the layout** so the open sidebar does not crush your main content (see [Layout recipes](document-layout.md#layout-recipes)).

That is the whole retrofit. There are no top-of-script constants to set, no `getElementById` calls to add, no per-document JS edits.

### Avoiding CSS collisions when retrofitting

The layer is designed to coexist with an arbitrary host stylesheet. Walk this checklist when retrofitting a page you did not generate:

- **Class names.** Every layer class is `cm-` prefixed, so collisions are nearly impossible. Before pasting, grep the host for `class="cm-` / `cm-` selectors; if the host already uses a `cm-` class for something else, rename the host's occurrences (the layer's names are fixed).
- **`--cp-*` variables.** The layer defines its palette as `--cp-*` custom properties. Grep the host CSS for `--cp-`. If the host already defines any `--cp-*` token, rename the host's, because the layer's `:root` and the host's `:root` will otherwise fight per-variable depending on source order.
- **`color-scheme`.** The layer's `:root` sets `color-scheme: light` (and `dark` in the dark block) so its own native controls match the theme. If the host manages its own `color-scheme` / native-control theming, delete just the two `color-scheme:` lines from the variable blocks (keep the `--cp-*` values) so the layer does not override the host.
- **`[hidden]`.** The layer scopes its `[hidden] { display: none !important }` reset to `.cm-skip[hidden], .cm-skip [hidden]`, so a host element carrying a `hidden` attribute is never forced hidden by the layer. No action needed; this is called out so you know the layer will not break host toggling.
- **z-index.** The layer UI occupies a high band: toolbar / sidebar / context menu / composer sit around 300-350 and the mermaid add-button sits just above. If the host has elements with `z-index` >= ~300 that must stay above the sidebar, raise the host's value or the layer's `.cm-*` z-indexes so the review UI is not covered (and is not covering critical host chrome).
- **Host element resets.** The layer styles its own controls under `.cm-*` selectors, but page-level element rules (`button { text-transform: uppercase }`, `* { box-sizing: ... }`, global `font`/`line-height`) still cascade into them. This is usually cosmetic. If a host reset visibly breaks the toolbar, sidebar, or composer, copy the offending properties explicitly onto the relevant `.cm-*` rule. The layer never depends on a CSS reset being present or absent.
- **Layout / the fixed sidebar.** The sidebar is `position: fixed`, 400px wide. Reserve room for it with one of the [Layout recipes](document-layout.md#layout-recipes) so it does not overlay the host content when open. The layer toggles `sidebar-open` on `<body>`; if the host already styles `body.sidebar-open`, rename one of them.
- **Verify.** After retrofitting, run "Quick verification after retrofitting". Specifically confirm that no host element vanished (the scoped `[hidden]`), the sidebar reserves space rather than covering content, and the toolbar / composer render correctly against the host's typography.




## Upgrade an existing instance to a new TEMPLATE.html

When a newer version of the skill ships, upgrading a deployed HTML is mechanical:

1. **Locate each `BEGIN: commentable-html v2 - <REGION>` / `END: commentable-html v2 - <REGION>` pair** in the deployed HTML (five pairs: CSS, HANDLED IDS, EMBEDDED COMMENTS, COMMENT UI, JS).
2. **For CSS, COMMENT UI, and JS:** delete everything between the markers (markers inclusive) and replace it with the same region from the new `TEMPLATE.html`. These three regions are byte-identical across deployments.
3. **For HANDLED IDS and EMBEDDED COMMENTS:** keep the existing regions intact. The agent owns the HANDLED IDS array and **Export as Portable** owns the EMBEDDED COMMENTS snapshot; the skill never overwrites them on upgrade.
4. **Leave the `#commentRoot` element alone.** Its `data-*` attributes carry the document's per-instance config, so `data-comment-key` continues to point at the same `localStorage` bucket and comments survive the upgrade.

Net result: an upgrade is "replace three regions (CSS, COMMENT UI, JS), leave three things alone (HANDLED IDS, EMBEDDED COMMENTS, `#commentRoot`), done". No merge, no per-doc patching.


