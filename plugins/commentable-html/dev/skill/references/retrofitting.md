# Retrofitting


## Contents

- [Add the layer to an existing HTML](#add-the-layer-to-an-existing-html)
- [Manual paste fallback](#manual-paste-fallback)
  - [Avoiding CSS collisions when retrofitting](#avoiding-css-collisions-when-retrofitting)
- [Upgrade an existing instance to a new dist/PORTABLE.html](#upgrade-an-existing-instance-to-a-new-distportablehtml)
  - [Upgrade safety and check mode](#upgrade-safety-and-check-mode)
- [Introspection globals (for tests and tooling)](#introspection-globals-for-tests-and-tooling)

## Add the layer to an existing HTML

Use `tools/authoring/retrofit.py` as the primary path for unlayered standalone HTML:

```bash
python tools/authoring/retrofit.py existing.html --label "My Report" --key auto --source existing.html --out existing-commentable.html
python tools/authoring/retrofit.py existing.html --label "My Report" --root-selector "#content" --skip-selectors "#toolbar,.modal" --out existing-commentable.html
python tools/authoring/retrofit.py existing.html --label "My Report" --portable --out shareable.html
```

The tool parses the real HTML token stream with Python's standard `html.parser`; it does not regex-match `<head>` or
`<body>` in comments or strings. It fails closed when `<head>` or `<body>` is missing, duplicated, malformed, or
ambiguous.

By default it wraps the existing `<body>` children in:

```html
<main id="commentRoot" data-cmh-content-root data-comment-key="..." data-doc-label="..." data-doc-source="...">
 ...
</main>
```

Use `--root-selector "#id"` when the host already has an outer content wrapper and wrapping `body > *` would break its
CSS. The selector grammar is intentionally limited to a single `#id`; the matched element is stamped as
`id="commentRoot"` and receives `data-cmh-content-root`, `data-comment-key`, `data-doc-label`, and `data-doc-source`.

`--key auto` derives a unique non-demo key from the label and output path. The tool refuses template/demo keys and
ignores a commented example `#commentRoot`, so it never binds to the template's documentation sample. It also refuses
an already-layered file and tells you to use `tools/authoring/upgrade.py` instead.

Use `--skip-selectors "sel,sel"` for host floating panels, modals, toolbars, navs, or sticky headers that should not
receive comments. Each selector may be `#id`, `.class`, or a tag name. Matching elements receive `class="cm-skip"`;
normal code blocks should stay commentable.

For NonPortable output the companion asset options match `new_document.py`: default absolute `file://` references to
the skill `dist/`, `--assets-relative`, `--copy-assets`, or `--assets-href PREFIX`. `--portable` inlines the layer into
one file.

Before writing, `retrofit.py` validates the candidate with the same `validate.py` checks. It writes through a temp file
and atomic replace, so a validation failure never clobbers the target. It also warns, without failing, when host CSS
appears to define `--cp-*`, `cm-*`, `color-scheme`, or `z-index` values at or above the layer's UI band.

There are no top-of-script constants to set, no `getElementById` calls to add, and no per-document JS edits.

## Manual paste fallback

Use manual paste only when Python is unavailable or the host HTML is too malformed for the tool and you choose to fix it
by hand. The five `BEGIN/END: commentable-html - <REGION>` blocks in `dist/PORTABLE.html` are designed to be copied
verbatim into another document:

1. **Open `dist/PORTABLE.html`** and locate the five region pairs. Each region is one contiguous block bracketed by
   HTML or CSS comments stamped `commentable-html`.
2. **Paste CSS region** at the end of any `<style>` block in `<head>` or create one. It includes the `--cp-*` variables
   it needs.
3. **Paste HANDLED IDS region** as the first child of `<body>`.
4. **Paste EMBEDDED COMMENTS region** immediately after HANDLED IDS. Leave its payload as `[]`; **Export as Portable**
   writes into it.
5. **Paste COMMENT UI region** immediately after EMBEDDED COMMENTS.
6. **Paste JS region** at the end of `<body>`, after scripts that render content.
7. **Mark the content root.** Prefer stamping the host's existing outermost content container. If there is no wrapper,
   wrap the reviewable content in `<main id="commentRoot" data-cmh-content-root data-comment-key="..."
   data-doc-label="..." data-doc-source="...">`.
8. **Avoid the duplicate-root footgun.** `dist/PORTABLE.html` contains a commented example `#commentRoot` with key
   `my-doc`; the real root is inside `<body>`. Target the body/last active root and give it a unique non-demo key.
9. **Add `cm-skip`** only to host chrome that must be excluded from selection, and run `tools/validate/validate.py --strict`.

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




## Upgrade an existing instance to a new dist/PORTABLE.html

When a newer version of the skill ships, upgrading a deployed HTML is mechanical:

1. **Locate each `BEGIN: commentable-html - <REGION>` / `END: commentable-html - <REGION>` pair** in the deployed HTML (five pairs: CSS, HANDLED IDS, EMBEDDED COMMENTS, COMMENT UI, JS).
2. **For CSS, COMMENT UI, and JS:** delete everything between the markers (markers inclusive) and replace it with the same region from the new `dist/PORTABLE.html`. These three regions are byte-identical across deployments.
3. **For HANDLED IDS and EMBEDDED COMMENTS:** keep the existing regions intact. The agent owns the HANDLED IDS array and **Export as Portable** owns the EMBEDDED COMMENTS snapshot; the skill never overwrites them on upgrade.
4. **Leave the `#commentRoot` element alone.** Its `data-*` attributes carry the document's per-instance config, so `data-comment-key` continues to point at the same `localStorage` bucket and comments survive the upgrade.

Net result: an upgrade is "replace three regions (CSS, COMMENT UI, JS), leave three things alone (HANDLED IDS, EMBEDDED COMMENTS, `#commentRoot`), done". No merge, no per-doc patching. The `upgrade.py` helper additionally re-emits the shell-baked mermaid loader bootstrap in `<head>` (outside the regions) so deck/mermaid shell fixes reach already-generated documents; a hand-vendored offline loader (relative mermaid `import(...)`) is left alone so the upgrade never re-points it at the CDN.

### Upgrade safety and check mode

Use the deterministic helper instead of hand-swapping regions whenever Python is available:

```bash
python tools/authoring/upgrade.py <file.html>
python tools/authoring/upgrade.py <file.html> --check
```

`--check` does not write. It prints that the file is up to date and exits 0 when no layer region would
change; it prints the stale region list and exits 1 when CSS, COMMENT UI, JS, the shell mermaid loader
bootstrap, or the default kind-meta migration would change.

The JS region has one load-bearing footgun: the real `END: commentable-html - JS` marker is the LAST real
region marker in the file. `dist/PORTABLE.html` contains earlier marker-like strings inside the JS body, so
a naive first-match replacement can truncate the runtime. `upgrade.py` uses a line-anchored marker parser and
validates before replacing the target; if you must update by hand, locate the actual region comments and treat
the final JS END marker as the boundary.



## Introspection globals (for tests and tooling)

The layer publishes a few `window` globals so an external harness (a Playwright spec, a health check, an upgrade script) can observe it without reaching into the closure. They are stable, read-only signals - do not treat them as a configuration surface.

- `window.__commentableHtmlReady` (boolean) - set to `true` once the layer has fully initialized. Wait on this before driving the UI.
- `window.__commentableHtmlVersion` (string) - the running layer's `CMH_VERSION`, e.g. `"1.7.0"`. Compare against an expected version to detect a stale deployment.
- `window.__cmhToMarkdown()` (function) - returns the current document serialized to the same Markdown that **Export to Markdown** writes, without triggering a download. Useful for asserting export output in a test.
- `window.__COMMENTABLE_ASSETS__` (object `{ version, css, js }` or absent) - present only in the non-portable (companion `commentable-html.assets.js`) shape; it carries the layer CSS/JS strings that **Export as Portable/Standalone** inlines. Its `version` must equal `__commentableHtmlVersion`; a mismatch aborts a standalone export by design.