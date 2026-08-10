#!/usr/bin/env python3
"""CMH-BUILD-25: the vendored mermaid bytes are pinned to the version the repo declares.

`assets/vendor/mermaid.min.js` is HAND-COPIED (see `assets/vendor/UPSTREAM.md`), and it is the copy
an `Export Offline` artifact inlines - so it is the only mermaid a reader of an offline document ever
runs. Nothing else in the build looks at its CONTENT: `build.py` stamps the CDN pin for the ONLINE
path from `package.json`, and its `--check` only proves the committed `.gz` decompresses to the
committed `.js` (`CMH-BUILD-11`). A vendored file left at the old version, or fetched from the wrong
place, would therefore sail through every gate while the shipped offline bytes silently disagreed
with the version the changelog, `THIRD_PARTY_NOTICES.md` and the online pin all advertise.

That is not hypothetical: this file was added with the 11.16.1 security bump, which had to be
hand-vendored because the local npm registry could not resolve the new version.

Two further things are pinned here because the 11.16.1 bump proved a reader cannot infer them:

- The BUNDLED DOMPurify version. Upstream mermaid prebuilds its dependencies into
  `dist/mermaid.min.js`, so the `dompurify` version `package-lock.json` resolves does NOT reach the
  shipped bytes - `mermaid@11.16.1` inlines DOMPurify `3.4.0` regardless. Reading a lockfile bump as
  a fix for a bundled-DOMPurify advisory is exactly the mistake this pins against, so `UPSTREAM.md`
  must state the bundled version and it must match what the bundle actually reports.
- The MIT license text travels with the bytes (`CMH-LICENSE-01`), so a re-vendor that updates the
  `.js` and forgets the `.LICENSE` is caught here rather than by a licence audit.

The strongest link - that these bytes are the npm tarball `package-lock.json` pins, not merely
something claiming that version - needs `node_modules`, so it lives in the Playwright guard spec
`tests/00-projects.spec.js` (the `fast` CI job runs after `npm ci`, which verifies the tarball
against the lockfile's integrity hash). This module is the part that holds everywhere, with no
install and no network.
"""
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402
sys.path.insert(0, _paths.DEV_TOOLS)
import build  # noqa: E402

VENDOR = os.path.join(_paths.ASSETS, "vendor")
BUNDLE = os.path.join(VENDOR, "mermaid.min.js")
UPSTREAM = os.path.join(VENDOR, "UPSTREAM.md")

# mermaid's own getVersion() source, the single place the bundle states its identity.
_BUNDLE_VERSION = re.compile(r"version:\s*[\"'](\d+\.\d+\.\d+)[\"']")
# The banner esbuild emits for each bundled dependency's licence.
_BUNDLED_DOMPURIFY = re.compile(r"@license DOMPurify (\d+\.\d+\.\d+)")


def _read(path, encoding="utf-8"):
    with open(path, encoding=encoding, errors="replace") as fh:
        return fh.read()


class VendoredMermaidProvenanceTests(unittest.TestCase):
    """CMH-BUILD-25"""

    def setUp(self):
        self.bundle = _read(BUNDLE)
        self.upstream = _read(UPSTREAM)

    def test_the_bundle_reports_the_version_package_json_pins(self):
        declared = build.read_mermaid_version()
        found = _BUNDLE_VERSION.findall(self.bundle)
        self.assertEqual(
            len(found), 1,
            "expected exactly one version literal in the vendored mermaid bundle, got %r - the "
            "anchor this check reads has moved upstream and needs re-deriving" % (found,))
        self.assertEqual(
            found[0], declared,
            "the vendored assets/vendor/mermaid.min.js reports mermaid %s, but package.json pins "
            "%s. An offline export inlines the VENDORED bytes, so they would ship a different "
            "mermaid than the online pin, the changelog and THIRD_PARTY_NOTICES.md all claim. "
            "Re-vendor per assets/vendor/UPSTREAM.md." % (found[0], declared))

    def test_upstream_md_names_the_version_that_is_actually_vendored(self):
        declared = build.read_mermaid_version()
        self.assertIn(
            "mermaid@%s/dist/mermaid.min.js" % declared, self.upstream,
            "assets/vendor/UPSTREAM.md must name the vendored mermaid version (%s); it is the only "
            "human-readable record of where these bytes came from" % declared)

    def test_upstream_md_records_the_dompurify_version_the_bundle_really_inlines(self):
        found = _BUNDLED_DOMPURIFY.findall(self.bundle)
        self.assertTrue(
            found, "the vendored mermaid bundle no longer carries a DOMPurify licence banner - if "
                   "upstream stopped bundling DOMPurify, update UPSTREAM.md and this check together")
        bundled = sorted(set(found))
        self.assertEqual(len(bundled), 1, "more than one DOMPurify version bundled: %r" % (bundled,))
        self.assertIn(
            "bundles `DOMPurify %s`" % bundled[0], self.upstream,
            "assets/vendor/UPSTREAM.md must state that the vendored mermaid bundle inlines DOMPurify "
            "%s. mermaid prebuilds its dependencies, so a `dompurify` bump in package-lock.json does "
            "NOT reach these bytes, and recording the real bundled version is what stops a lockfile "
            "bump being read as a fix for a bundled-DOMPurify advisory." % bundled[0])

    def test_the_mit_licence_travels_with_the_vendored_bytes(self):
        for name in ("mermaid.LICENSE", "chart.umd.LICENSE"):
            path = os.path.join(VENDOR, name)
            self.assertTrue(os.path.exists(path), "%s is missing (CMH-LICENSE-01)" % name)
            self.assertIn("MIT", _read(path), "%s does not look like the upstream MIT text" % name)


if __name__ == "__main__":
    unittest.main()
