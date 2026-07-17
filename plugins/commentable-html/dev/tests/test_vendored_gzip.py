#!/usr/bin/env python3
"""Reproducible-build tests for the vendored rich-libs gzip blob (CMH-BUILD-11).

The build must NOT recompress the vendored mermaid/chart libraries at build time: gzip DEFLATE
output differs between zlib implementations (stock zlib vs zlib-ng, which Python 3.14 ships), so a
live recompress makes the dist blob depend on the builder's machine and breaks dist-in-sync. Instead
the build reads a committed `<lib>.gz` artifact and base64-encodes it (deterministic everywhere), and
a drift guard verifies the committed .gz DECOMPRESSES to the current source (decompression is
deterministic across zlib impls, so the guard never recompresses).

Standard library only.
"""
import base64
import gzip
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402  shared pkg/dev split path constants
sys.path.insert(0, _paths.DEV_TOOLS)  # maintainer-only build tool (build.py lives in dev/)
import build  # noqa: E402


class VendoredGzipReproTests(unittest.TestCase):
    def _vendor(self, tmp, mermaid=b"MERMAID-BODY", chart=b"CHART-BODY"):
        vendor = os.path.join(tmp, "vendor")
        os.makedirs(vendor)
        with open(os.path.join(vendor, "mermaid.min.js"), "wb") as fh:
            fh.write(mermaid)
        with open(os.path.join(vendor, "chart.umd.min.js"), "wb") as fh:
            fh.write(chart)
        return vendor

    def test_blob_reads_committed_gz_not_recompressed(self):
        # Commit a .gz produced at a DIFFERENT compression level than the build's regen (level 9).
        # If the build recompressed, the blob would differ from these committed bytes; it must not.
        with tempfile.TemporaryDirectory() as tmp:
            vendor = self._vendor(tmp)
            committed = {}
            for name, body in (("mermaid.min.js", b"MERMAID-BODY"), ("chart.umd.min.js", b"CHART-BODY")):
                gz = gzip.compress(body, 1, mtime=0)  # level 1, not the build's level-9 regen
                with open(os.path.join(vendor, name + ".gz"), "wb") as fh:
                    fh.write(gz)
                committed[name] = gz
            js = build.build_vendored_rich_libs_json(tmp)
            payload = json.loads(js)
            self.assertEqual(payload["encoding"], "gzip+base64")
            self.assertEqual(payload["mermaidGzipBase64"],
                             base64.b64encode(committed["mermaid.min.js"]).decode("ascii"))
            self.assertEqual(payload["chartjsGzipBase64"],
                             base64.b64encode(committed["chart.umd.min.js"]).decode("ascii"))

    def test_drift_guard_detects_missing_and_stale_gz(self):
        with tempfile.TemporaryDirectory() as tmp:
            vendor = self._vendor(tmp, mermaid=b"HELLO")
            # No committed .gz yet -> drift.
            self.assertIsNotNone(build.vendored_gz_drift(vendor, "mermaid.min.js"))
            # Regenerate -> in sync.
            build.regen_vendored_gz(vendor, "mermaid.min.js")
            self.assertIsNone(build.vendored_gz_drift(vendor, "mermaid.min.js"))
            # Change the source without regenerating -> drift again.
            with open(os.path.join(vendor, "mermaid.min.js"), "wb") as fh:
                fh.write(b"CHANGED")
            self.assertIsNotNone(build.vendored_gz_drift(vendor, "mermaid.min.js"))

    def test_regen_roundtrips_through_decompression(self):
        # The drift guard relies on decompression matching the source (zlib-impl-independent), and
        # the source is the sourceMappingURL-stripped script that read_vendor_script returns.
        with tempfile.TemporaryDirectory() as tmp:
            vendor = self._vendor(tmp)
            body = b"var x=1;\n//# sourceMappingURL=mermaid.min.js.map"
            with open(os.path.join(vendor, "mermaid.min.js"), "wb") as fh:
                fh.write(body)
            build.regen_vendored_gz(vendor, "mermaid.min.js")
            with open(os.path.join(vendor, "mermaid.min.js.gz"), "rb") as fh:
                gz = fh.read()
            expected = build.read_vendor_script(os.path.join(vendor, "mermaid.min.js")).encode("utf-8")
            self.assertEqual(gzip.decompress(gz), expected)
            self.assertNotIn(b"sourceMappingURL", gzip.decompress(gz))


if __name__ == "__main__":
    unittest.main(verbosity=2)
