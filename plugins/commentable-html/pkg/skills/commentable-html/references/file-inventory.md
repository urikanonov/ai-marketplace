# File inventory

This inventory lists the files that ship with the skill. Development sources, the spec, and the test suites live in the project's source repository and are not part of the installed plugin.

## Shipped skill root

| Path | Purpose |
| --- | --- |
| `SKILL.md` | Public skill instructions, generation steps, validation, and review loop. |
| `dist/README.md` | Terse pointer for generated dist artifacts. |
| `dist/PORTABLE.html` | Standalone inline template and demo. |
| `dist/NONPORTABLE.html` | NonPortable starting shell. |
| `dist/commentable-html.css` | Layer stylesheet companion. |
| `dist/commentable-html.js` | Runtime companion. |
| `dist/commentable-html.assets.js` | Asset registry used by Export as Portable. |
| `dist/manifest.json` | Version and SHA-256 metadata for companions. |
| `tools/` | Runtime Python helpers that ship with the skill, grouped into per-topic buckets (`tools/deck`, `tools/kusto`, `tools/checklist`, `tools/notes`, `tools/blocks`, `tools/authoring`, `tools/validate`). |
| `references/` | Detailed generated-report references. |
| `docs/TUTORIAL.md` | Tutorial using `examples/report-community-garden.html`. |
| `docs/assets/` | Tutorial screenshots and the review-loop diagram (the diagram is embedded in the plugin README). |
| `examples/prompt-community-garden.md` | Prompt for the community garden example. |
| `examples/prompt-taxi.md` | Prompt for the NYC taxi example. |
| `examples/prompt-triage.md` | Prompt for the incident triage board example. |
| `examples/prompt-metrics.md` | Prompt for the commentable visuals matrix example. |
| `examples/report-community-garden.html` | Portable community garden example report. |
| `examples/report-taxi.html` | Portable NYC taxi example report. |
| `examples/report-triage.html` | Portable incident triage board example report. |
| `examples/report-metrics.html` | Portable commentable visuals matrix example report. |

## Runtime tools

Run any tool with `python tools\<name>.py --help` from `pkg\skills\commentable-html`.

- `validate.py` - structural invariant checker for generated files. Use `--strict` before handoff.
- `mark_handled.py` - appends handled comment ids from explicit ids or a copied bundle.
- `new_document.py` - builds a fresh commentable document from a content fragment (NonPortable by default; `--portable` for a single self-contained file).
- `recommend_kind.py` - recommends `report`, `plan`, or `slides` from filename and content signals before choosing `--kind`.
- `retrofit.py` - injects the layer into an existing unlayered HTML file, validates before writing, and leaves the target unchanged on failure.
- `upgrade.py` - upgrades CSS, COMMENT UI, and JS regions from the current `dist/PORTABLE.html`.
- `finalize.py` - runs safe assembly steps, then validates.
- `diff_block.py` - emits escaped `pre.cmh-diff` review blocks.
- `chart_block.py` - emits a validator-clean Chart.js figure, loader, data block, and init.
- `kql_highlight.py` and `kusto_link.py` - build KQL figures and Run in Azure Data Explorer deep links.
- `highlight_code.py` - emits highlighted code blocks.
- `generate_toc.py` - creates a `nav.cm-toc` from headings.
- `fix_skip.py` - adds `cm-skip` to bare Mermaid blocks.
- `inline_images.py` - inlines local images as data URIs.
- `deck_fix_fonts.py` - strips copied remote deck font loaders and maps web-font stacks to approved system stacks.

## References

- `references/charts.md` - Chart.js embedding, tooltip, portability, data hygiene, and verification guidance.
- `references/code-blocks.md` - Code comment behavior and copy buttons.
- `references/code-review-diffs.md` - Unified diff rendering and anchors.
- `references/commentable-widgets.md` - Widget/SVG-node comments, state-change tracking, document-wide comments.
- `references/comment-data-shape.md` - Comment JSON and pinpoint fields.
- `references/content-conventions.md` - ADO links, cross-references, and authoring guidance (shape, taste, measure, tokens).
- `references/copy-payload.md` - `Copy all` Markdown and handled-id contract.
- `references/design-decisions.md` - Intentional behaviors reviewers should not flag.
- `references/document-layout.md` - Themes, TOC, sections, cards, and tables.
- `references/exports.md` - Portable, Plain HTML, Markdown, and NonPortable export semantics.
- `references/file-inventory.md` - This file.
- `references/forward-compatible-layout.md` - Region layout and descriptor contract for current and future tools.
- `references/images-commentable.md` - Image and chart canvas comments.
- `references/interaction-model.md` - Add-comment gestures and sidebar lifecycle.
- `references/kusto-query-blocks.md` - KQL blocks and deep links.
- `references/limitations.md` - Known limitations to disclose.
- `references/mermaid-diagrams.md` - Mermaid loading, anchors, and comments.
- `references/retrofitting.md` - Adding or upgrading the layer in existing HTML.
- `references/validation.md` - Validator behavior and manual verification.
