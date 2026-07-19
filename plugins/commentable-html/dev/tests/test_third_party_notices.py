#!/usr/bin/env python3
"""CMH-LICENSE-01: the shipped THIRD_PARTY_NOTICES.md carries the vendored libraries' MIT notices.

The commentable-html skill redistributes the mermaid and Chart.js library bytes (bundled into the
built templates and inlined into Offline exports), so the MIT License requires their copyright and
permission notices to travel with the distribution. build.py assembles those notices from the vendored
`assets/vendor/*.LICENSE` files into a shipped THIRD_PARTY_NOTICES.md (copied unzipped beside the plugin
LICENSE). These tests keep that notice complete, faithful to the vendored texts, and shipped in both the
stage and the packaged copy. Standard library only.
"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402  shared pkg/dev split path constants
sys.path.insert(0, _paths.DEV_TOOLS)  # maintainer-only build tool (build.py lives in dev/tools)
import build  # noqa: E402

build.ASSETS = _paths.ASSETS

VENDOR_DIR = os.path.join(_paths.ASSETS, "vendor")
STAGE_NOTICES = os.path.join(_paths.PKG, "THIRD_PARTY_NOTICES.md")            # dev/skill (the stage)
SHIPPED_NOTICES = os.path.join(_paths.PKG_SHIPPED, "THIRD_PARTY_NOTICES.md")  # minimal shipped pkg dir


def _read(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read().replace("\r\n", "\n")


class ThirdPartyNoticesTests(unittest.TestCase):
    def test_notices_are_generated_shipped_and_in_sync(self):
        for path in (STAGE_NOTICES, SHIPPED_NOTICES):
            self.assertTrue(os.path.exists(path), "missing shipped notices: %s" % path)
        expected = build.build_third_party_notices(_paths.ASSETS)
        # The committed stage and packaged copies must both equal a fresh assembly (drift gate,
        # independent of build.py --check).
        self.assertEqual(_read(STAGE_NOTICES), expected)
        self.assertEqual(_read(SHIPPED_NOTICES), expected)
        self.assertIn("DO NOT EDIT", expected)

    def test_notices_reproduce_the_vendored_license_texts_and_versions(self):
        notices = _read(STAGE_NOTICES)
        versions = {"mermaid": build.read_mermaid_version(), "Chart.js": build.read_chartjs_version()}
        for label, license_name in build.VENDORED_LICENSE_FILES:
            license_text = build.read_vendored_license(VENDOR_DIR, license_name)
            self.assertIn(license_text, notices,
                          "%s license text is not reproduced verbatim in the notices" % label)
            self.assertIn("## %s %s" % (label, versions[label]), notices)
        self.assertIn("Knut Sveidqvist", notices)          # mermaid copyright holder
        self.assertIn("Chart.js Contributors", notices)    # Chart.js copyright holder

    def test_vendored_licenses_are_mit_and_offline_comment_safe(self):
        markers = {"mermaid.LICENSE": "Knut Sveidqvist", "chart.umd.LICENSE": "Chart.js Contributors"}
        for _label, license_name in build.VENDORED_LICENSE_FILES:
            text = build.read_vendored_license(VENDOR_DIR, license_name)
            self.assertIn("MIT License", text)
            self.assertIn("Permission is hereby granted", text)
            self.assertIn(markers[license_name], text)
            # Offline export emits the license verbatim inside an HTML comment. A run of two or more
            # hyphens ("--", and hence "-->") is the only sequence that can prematurely terminate or
            # invalidate a comment, so the vendored license must contain none - which also makes the
            # offline notice provably VERBATIM (the "--" neutralizer in 68-export-offline.js never
            # fires for a shipped license; it remains only as defense-in-depth for a future refresh).
            self.assertNotIn("--", text)

    def test_offline_bundle_embeds_each_license_verbatim(self):
        payload = json.loads(build.build_vendored_rich_libs_json(_paths.ASSETS))
        self.assertEqual(payload["mermaidLicense"], build.read_vendored_license(VENDOR_DIR, "mermaid.LICENSE"))
        self.assertEqual(payload["chartjsLicense"], build.read_vendored_license(VENDOR_DIR, "chart.umd.LICENSE"))


if __name__ == "__main__":
    unittest.main()
