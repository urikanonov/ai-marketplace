# Vendored rich-content libraries for Offline export

These files are checked-in local copies used only to build fully self-contained
`Export Offline` artifacts:

- `mermaid.min.js` - copied from `mermaid@11.16.0/dist/mermaid.min.js` - MIT
- `chart.umd.min.js` - copied from `chart.js@4.5.1/dist/chart.umd.min.js` - MIT

Build-time use only:

- `dev/tools/build.py` reads these vetted local files and stamps their source into the
  generated Commentable HTML templates as a JSON blob.
- `assets/js/68-export-offline.js` inlines only the libraries the exported document
  actually needs, so the downloaded offline artifact stays zero-network and does not
  carry unused rich-content code.

Update process:

1. Bump the matching dependency in `dev/package.json`.
2. Run `npm ci` in `plugins/commentable-html/dev`.
3. Copy the new dist file from `node_modules` over the matching vendored file here.
4. Rebuild and run the offline-export Playwright coverage.
