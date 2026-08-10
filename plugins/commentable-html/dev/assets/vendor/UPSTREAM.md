# Vendored rich-content libraries for Offline export

These files are checked-in local copies used only to build fully self-contained
`Export Offline` artifacts:

- `mermaid.min.js` - copied from `mermaid@11.16.1/dist/mermaid.min.js` - MIT
  - bundles `DOMPurify 3.4.0` (upstream prebuilds its dependencies into this file, so the
    `dompurify` version resolved in `package-lock.json` does NOT reach these bytes)
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
   change between versions). For mermaid, also refresh the `bundles \`DOMPurify x.y.z\`` line above
   to whatever the new bundle's `@license DOMPurify` banner reports - a test asserts they agree,
   because upstream prebuilds that dependency in and a lockfile bump never reaches these bytes.
4. Run `python tools/build.py --regen-vendor-gz` to refresh the committed `.gz` artifacts.
5. Rebuild (`python scripts/rebuild_all.py`) - this regenerates `THIRD_PARTY_NOTICES.md` and the
   offline bundle from the updated licenses - and run the offline-export Playwright coverage.

### If `npm ci` cannot resolve the new version

Step 2 fails on a network whose npm registry is a corporate mirror that lags public npm, and public
`registry.npmjs.org` may itself be unreachable behind TLS interception. That is not hypothetical: the
`mermaid@11.16.1` security bump was vendored this way. Do NOT skip the bump - vendor it from a public
npm CDN and verify the bytes, then let CI re-verify them against the real tarball:

1. Fetch the file from an npm CDN that serves the published tarball verbatim - `unpkg.com` and
   jsDelivr (`fastly.jsdelivr.net`, `gcore.jsdelivr.net`) are two INDEPENDENT origins:
   `https://unpkg.com/mermaid@<version>/dist/mermaid.min.js`.
2. Verify it. unpkg publishes a per-file SRI in its directory listing
   (`https://unpkg.com/mermaid@<version>/dist/?meta`); compare
   `sha256-<base64>` of what you downloaded against the `integrity` it lists, and cross-check that a
   second origin serves byte-identical content. Fetch the upstream `LICENSE` the same way.
3. Take the `package-lock.json` `version` / `resolved` / `integrity` triple from the Dependabot PR
   for the same bump rather than hand-writing it, so the lockfile carries npm's real hash.
4. Continue from step 4 above.

CI closes the loop: `npm ci` verifies each tarball against the lockfile `integrity` hash, and
`CMH-BUILD-25` (`dev/tests/01-vendor-provenance.spec.js`) then asserts the vendored file is
byte-identical to `node_modules/mermaid/dist/mermaid.min.js`. So a wrong or tampered CDN copy fails
the build regardless of where it came from.
