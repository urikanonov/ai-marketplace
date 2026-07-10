# File inventory

This inventory lists the files that ship with the skill. Development sources, the spec, and the test suites live in the project's source repository and are not part of the installed plugin.

## Shipped skill root

| Path | Purpose |
| --- | --- |
| `SKILL.md` | Public skill instructions, generation steps, validation, and review loop. |
| `dist/README.md` | Terse pointer for generated dist artifacts. |
| `dist/PORTABLE.html` | Standalone inline template and demo. |
| `dist/NONPORTABLE.html` | NonPortable starting shell. |
| `dist/commentable-html.v<V>.css` | Versioned stylesheet companion. |
| `dist/commentable-html.v<V>.js` | Versioned runtime companion. |
| `dist/commentable-html.v<V>.assets.js` | Asset registry used by Export as Portable. |
| `dist/manifest.json` | Version and SHA-256 metadata for companions. |
| `tools/` | Runtime Python helpers that ship with the skill. |
| `references/` | Detailed generated-report references. |
| `docs/TUTORIAL.md` | Tutorial using `examples/report-community-garden.html`. |
| `docs/tutorial-images/` | Tutorial screenshots. |
| `examples/prompt-community-garden.md` | Prompt for the community garden example. |
| `examples/prompt-taxi.md` | Prompt for the NYC taxi example. |
| `examples/report-community-garden.html` | Portable community garden example report. |
| `examples/report-taxi.html` | Portable NYC taxi example report. |

## Runtime tools

Run any tool with `python tools\<name>.py --help` from `pkg\skills\commentable-html`.

- `validate.py` - structural invariant checker for generated files. Use `--strict` before handoff.
- `mark_handled.py` - appends handled comment ids from explicit ids or a copied bundle.
- `new_document.py` - builds a fresh standalone document from a content fragment.
- `upgrade.py` - upgrades CSS, COMMENT UI, and JS regions from the current `dist/PORTABLE.html`.
- `finalize.py` - runs safe assembly steps, then validates.
- `diff_block.py` - emits escaped `pre.cmh-diff` review blocks.
- `chart_block.py` - emits a validator-clean Chart.js figure, loader, data block, and init.
- `kql_highlight.py` and `kusto_link.py` - build KQL figures and Run in Azure Data Explorer deep links.
- `highlight_code.py` - emits highlighted code blocks.
- `generate_toc.py` - creates a `nav.cm-toc` from headings.
- `fix_skip.py` - adds `cm-skip` to bare Mermaid blocks.
- `inline_images.py` - inlines local images as data URIs.

## References

- `references/charts.md` - Chart.js embedding, tooltip, portability, data hygiene, and verification guidance.
- `references/code-blocks.md` - Code comment behavior and copy buttons.
- `references/code-review-diffs.md` - Unified diff rendering and anchors.
- `references/comment-data-shape.md` - Comment JSON and pinpoint fields.
- `references/content-conventions.md` - ADO links and stable cross-references.
- `references/copy-payload.md` - `Copy all` Markdown and handled-id contract.
- `references/design-decisions.md` - Intentional behaviors reviewers should not flag.
- `references/document-layout.md` - Themes, TOC, sections, cards, and tables.
- `references/exports.md` - Portable, Plain HTML, and NonPortable export semantics.
- `references/file-inventory.md` - This file.
- `references/images-commentable.md` - Image and chart canvas comments.
- `references/interaction-model.md` - Add-comment gestures and sidebar lifecycle.
- `references/kusto-query-blocks.md` - KQL blocks and deep links.
- `references/limitations.md` - Known limitations to disclose.
- `references/mermaid-diagrams.md` - Mermaid loading, anchors, and comments.
- `references/retrofitting.md` - Adding or upgrading the layer in existing HTML.
- `references/validation.md` - Validator behavior and manual verification.
