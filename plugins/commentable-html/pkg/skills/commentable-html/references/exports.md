# Exports


## Export as Portable

> UI label: **Export as Portable** (in the toolbar **...** overflow menu and the sidebar header). Earlier builds labeled it "Save comments" / "Save in HTML"; the behavior is the same, and in nonportable mode it now always produces a combined single file (see below).

The fifth region, **EMBEDDED COMMENTS**, is an optional in-file snapshot of the comments array so a single HTML file can travel with its own review state:

```html
<script type="application/json" id="embeddedComments">
[]
</script>
```

The overflow menu and sidebar both expose an **Export as Portable** button. Clicking it:

1. Fetches the on-disk HTML (`fetch(location.href)`). If that fails (file://, network unavailable, CSP), falls back to a snapshot of `document.documentElement.outerHTML` captured on the very first line of the layer's IIFE, before any DOM mutation.
2. Replaces the contents of the `<script id="embeddedComments">` block with the current `comments` array (pretty-printed JSON, two-space indent, for git-friendly diffs).
3. Triggers a blob download via `<a download>` renamed to `<stem>-portable.html` (or `commentable-portable.html` if the URL had no `.html` segment). Existing `-comments` or `-portable` suffixes are stripped first, so `foo-comments.html` becomes `foo-portable.html` and repeated exports stay `foo-portable.html`. The browser saves it to the user's downloads folder; the user can keep the copy or replace the original.

We deliberately do NOT try to overwrite the original file in place. An earlier version of this feature used the File System Access API (`window.showSaveFilePicker` + cached `FileSystemFileHandle` in IndexedDB) to attempt silent overwrites, but the semantics were confusing - the cached handle pointed at whatever file the user first picked, which is not necessarily the URL the page was loaded from. Always-download is unambiguous: every click produces a fresh self-contained file, and the user controls what to do with it.

On load, embedded comments are not displayed directly; they are merged into `localStorage` first. For each id that appears in both stores, the entry with the later `updatedAt` (fallback `createdAt`) wins. Ids that only appear in one store pass through unchanged. After merge the layer writes the resulting set back to localStorage so subsequent reloads converge on a single source of truth.

This means:

- A shared HTML file with embedded comments can be opened by anyone, and they immediately see the same comments without any extra step.
- A user can keep editing comments locally (composer save bumps `updatedAt`); their localStorage version wins until they click **Export as Portable** again.
- The agent's `handledCommentIds` contract is unchanged: appending an id there prunes the comment from localStorage on next load. To remove it from the embedded snapshot, click **Export as Portable** after the prune so the downloaded copy reflects the pruned state.

The `<script id="embeddedComments">` block is the **only** part of the file that **Export as Portable** ever rewrites (aside from inlining the layer in nonportable mode, below). It does not regenerate any other markup, does not re-run mermaid, does not change `handledCommentIds`, and does not modify the five pasteable regions.

In **nonportable** mode, **Export as Portable** additionally inlines the CSS and runtime so the downloaded file is ONE portable, self-contained document (see below) - so the same button always yields a combined file whether the source was inline or nonportable.


## Combined file from a nonportable document

There is no separate "Export standalone" button: **Export as Portable** does this automatically in nonportable mode. The live nonportable page only references the layer via `<link>` / `<script src>`, so the export rebuilds ONE self-contained inline file: it embeds the current comments, then inlines the CSS and runtime by reading their string payloads from the loaded `commentable-html.assets.js` registry (`window.__COMMENTABLE_ASSETS__`). Because that registry loaded as a classic `<script src>`, the payloads are already in memory - so the rebuild works even when the page was opened by double-click (`file://`), where `fetch()` of the sibling files is blocked. The downloaded file uses the same `-portable.html` suffix rule as inline export. External companion references, the version `<meta>`, and the NONPORTABLE BOOTSTRAP are stripped, and the CSS/JS region markers are restored so it passes `validate.py` in inline mode.


## Export to Plain HTML

> UI label: **Export to Plain HTML** (overflow menu and sidebar). Earlier builds labeled it "Export plain" / "Save as plain".

The overflow menu and sidebar also expose an **Export to Plain HTML** button. It downloads a standalone copy of the document with the commenting *ability* removed but its appearance intact, so the artifact can be shared or published without the review UI while looking exactly like the original. The downloaded file uses the original name with a `.plain.html` suffix (e.g. `report.html` -> `report.plain.html`). It handles both modes: in inline mode it keeps the whole inline CSS region and strips the comment regions + JS; in nonportable mode it keeps the companion `<link>` (so the content stays styled) and drops only the `<script src>` runtime companion.

What it strips and what it keeps:

- **Removes** the four HTML-comment regions (HANDLED IDS, EMBEDDED COMMENTS, COMMENT UI, JS) in full - no toolbar, sidebar, composer, menus, scripts, or stored ids.
- **Keeps every stylesheet.** The inline CSS region (or the nonportable companion `<link>`) is preserved in full, so the document's own content styling - tables, sections, code, diff, KQL, images - is identical to the original. The now-unused `.cm-*` UI rules are inert because their elements are gone. (Earlier builds reduced the CSS region to only the `--cp-*` theme variables, which stripped the shipped content styling and left the plain file looking unstyled - that is fixed: "plain" removes the commenting ability, not the styling.)
- **Keeps everything else untouched** - the host content, the host's own `<style>` rules, and host scripts such as the mermaid loader and theme detection. Mermaid diagrams still render in the plain copy.
- Strips the `sidebar-open` body class. It does **not** sanitize highlight marks, rings, or `data-cid` out of the content, and does not need to: the source it copies (the on-disk file or the load-time snapshot taken on the first line of the layer's IIFE) predates every runtime change, so those artifacts were never in it. Attempting document-wide regex cleanup would risk corrupting legitimate host markup (code samples, host `data-cid` attributes, script literals), so it is deliberately avoided.
- The region strip anchors each region's END on its own `<!-- ... END ... -->` comment. Because embedded comment notes escape every `<` as `\u003c`, a note can never forge a `<!--`, so note text like `END: commentable-html - EMBEDDED COMMENTS -->` cannot terminate the region early and leak the comments that follow it. As a final data-safety net, the export aborts (with a toast, no download) if a `handledCommentIds` / `embeddedComments` script somehow survives.

Implementation detail worth knowing when modifying this feature:

- **The JS region is anchored on its own `</script>`, not its END marker.** When the file is opened from `file://`, `fetch(location.href)` is blocked, so the source is taken from a DOM snapshot captured while the layer's own script is still executing. At that point the HTML parser has not yet reached the trailing `<!-- END: commentable-html - JS -->` comment, so it is absent from the snapshot. Matching the JS region by its closing `</script>` (with an optional trailing END marker) strips it correctly in both the `file://` snapshot path and the fetched on-disk path.

**Export to Plain HTML** never modifies the open document, `localStorage`, `handledCommentIds`, or the embedded comments; it only produces a downloaded copy.
