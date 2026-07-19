# Vendored rich-content libraries for Offline export

These files are checked-in local copies used only to build fully self-contained
`Export Offline` artifacts:

- `mermaid.min.js` - copied from `mermaid@11.16.0/dist/mermaid.min.js` - MIT
- `chart.umd.min.js` - copied from `chart.js@4.5.1/dist/chart.umd.min.js` - MIT
- `mermaid.LICENSE` - the upstream MIT license text for mermaid (copied verbatim)
- `chart.umd.LICENSE` - the upstream MIT license text for Chart.js (copied verbatim)

The two `*.LICENSE` files are the single source for the shipped `THIRD_PARTY_NOTICES.md` (assembled by
`build.py` and copied unzipped into the shipped skill dir) and for the MIT notices `Export Offline`
inlines beside each bundled library, so the copyright and permission notices always travel with the
redistributed library bytes as the MIT License requires.

Credit: mermaid (https://mermaid.js.org/) and Chart.js (https://www.chartjs.org/) are third-party
open-source libraries used under the MIT License. The plugin relies on them for diagram and chart
rendering. On the ONLINE render path mermaid is imported from a version-pinned jsDelivr CDN URL
(`https://cdn.jsdelivr.net/npm/mermaid@<version>/dist/mermaid.esm.min.mjs`, single-sourced from
`dev/package.json`), and Chart.js loads from a pinned CDN only on explicit per-document opt-in; the
vendored copies here back the zero-network `Export Offline` path. The accepted-risk decision to keep
ONLY that pinned mermaid CDN import is documented as `CMH-SEC-04` in `dev/spec/50-security.md`;
Chart.js CDN loading stays opt-in (pinned plus SRI) and in scope for review.

Build-time use only:

- `dev/tools/build.py` reads these vetted local files and stamps their source into the
  generated Commentable HTML templates as a JSON blob.
- `assets/js/68-export-offline.js` inlines only the libraries the exported document
  actually needs, so the downloaded offline artifact stays zero-network and does not
  carry unused rich-content code.

Update process:

1. Bump the matching dependency in `dev/package.json`.
2. Run `npm ci` in `plugins/commentable-html/dev`.
3. Copy the new dist file from `node_modules` over the matching vendored file here, AND copy the
   upstream `LICENSE` over the matching `*.LICENSE` file here (the copyright year or holder may
   change between versions).
4. Run `python tools/build.py --regen-vendor-gz` to refresh the committed `.gz` artifacts.
5. Rebuild (`python scripts/rebuild_all.py`) - this regenerates `THIRD_PARTY_NOTICES.md` and the
   offline bundle from the updated licenses - and run the offline-export Playwright coverage.
