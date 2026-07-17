# Forward-compatible layout

Generated Commentable HTML documents separate user content from the review layer with a small machine-readable contract.

## Layer descriptor

Every generated document contains this head descriptor:

```html
<script type="application/json" id="commentableHtmlLayer">{"version":"<current-runtime-version>","mode":"portable","regions":["CSS","HANDLED IDS","EMBEDDED COMMENTS","COMMENT UI","JS"]}</script>
```

- `version` is the Commentable HTML layer version that generated the document.
  This value equals the runtime version that emitted the document.
- `mode` is `portable`, `offline`, or `nonportable`.
- `regions` lists the infra region marker names in document order. The names are the exact text that appears after `BEGIN: commentable-html - ` and `END: commentable-html - `.

Portable documents inline the CSS and JS region bodies. NonPortable documents keep the same marker names, but their CSS and JS regions contain companion `<link>` and `<script src>` references.
Offline is the same descriptor contract with `mode` set to `offline`, not a second signal. Offline documents are portable documents with remote rich-content loaders removed and vendored mermaid / Chart.js runtimes inlined only when the document uses them.

## Content root

The reviewable content lives under one root:

```html
<main id="commentRoot" data-cmh-content-root ...>
```

The editable content inside that root is delimited by:

```html
<!-- BEGIN: commentable-html - CONTENT (agent edits ONLY between these markers) -->
...
<!-- END: commentable-html - CONTENT -->
```

Tooling should treat everything between those CONTENT markers as the user's document content. The `data-cmh-content-root` attribute is a stable selector for the root that owns the content and document identity attributes.

## Compatibility guarantee

Within a major version, a tool can read `#commentableHtmlLayer.regions`, locate and replace those infra regions in order, and leave the CONTENT region untouched. Region marker names stay stable within the major version. A breaking change to the descriptor shape, marker names, or content-root hook requires a major version bump.

`validate.py --strict` validates the current contract only, so legacy pre-1.15 documents must be regenerated or upgraded before validating.
