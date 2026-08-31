#!/usr/bin/env python3
"""CMH-SEC-04: guard the by-design mermaid CDN accepted-risk decision (#451).

The runtime auto-loads mermaid from a version-pinned jsDelivr URL on the online render path. The
maintainer decision (#451) is to KEEP that mermaid CDN import as an accepted supply-chain risk,
because the import is version-pinned and a fully zero-network artifact is available via Export
Offline (which inlines the vendored copies). The accepted risk is scoped to that ONE mermaid import;
Chart.js never auto-loads from a CDN and stays in scope. These tests keep the decision honest: every
remote mermaid reference in each built runtime template must be exactly the pinned jsDelivr URL (never
a floating tag or a different host), the accepted risk must stay documented in the security spec so a
future scan treats only it as out of scope, and the vendored libraries must keep their MIT attribution.
Standard library only.
"""
import json
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402  shared pkg/dev split path constants

PACKAGE_JSON = os.path.join(_paths.DEV, "package.json")
BUILT_SHAREABLE = _paths.TEMPLATE  # dev/skill/dist/SHAREABLE.html (the stamped, built stage)
BUILT_NONSHAREABLE = os.path.join(_paths.DIST, "NONSHAREABLE.html")
SHELL_SOURCE = os.path.join(_paths.ASSETS, "template.shell.html")
SECURITY_SPEC = os.path.join(_paths.DEV, "spec", "50-security.md")
VENDOR_UPSTREAM = os.path.join(_paths.ASSETS, "vendor", "UPSTREAM.md")


def _read(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _mermaid_base_version():
    """The single-sourced mermaid version, pinned from dev/package.json like build.py does."""
    data = json.loads(_read(PACKAGE_JSON))
    spec = ((data.get("devDependencies") or {}).get("mermaid")
            or (data.get("dependencies") or {}).get("mermaid"))
    m = re.match(r"^[\^~]?(\d+\.\d+\.\d+)$", (spec or "").strip())
    assert m, "mermaid must be pinned to an exact or ^/~ version in package.json, got %r" % spec
    return m.group(1)


class CdnByDesignTests(unittest.TestCase):
    def test_runtime_mermaid_import_is_pinned_jsdelivr(self):
        base = _mermaid_base_version()
        # TWO pinned URLs are legitimate, both on the same jsDelivr version pin. The runtime imports
        # the ESM entry to render (the accepted risk this row is about); since CMH-SIZE-08 the
        # vendored payload also NAMES the UMD build, which Export Offline downloads and then
        # verifies against a build-recorded SHA-384 before inlining - so that second reference
        # carries an integrity guarantee the dynamic import cannot.
        allowed = {
            "https://cdn.jsdelivr.net/npm/mermaid@%s/dist/mermaid.esm.min.mjs" % base,
            "https://cdn.jsdelivr.net/npm/mermaid@%s/dist/mermaid.min.js" % base,
        }
        esm = "https://cdn.jsdelivr.net/npm/mermaid@%s/dist/mermaid.esm.min.mjs" % base
        url_re = re.compile(r'https?://[^\s"\'()<>]+')
        # The accepted-risk property is that EVERY remote mermaid reference in each built runtime
        # template is one of those pinned jsDelivr URLs - not merely that a pinned URL appears
        # somewhere. A presence-only check would stay green if the active import moved to unpkg, a
        # bare host, or mermaid@latest while the expected string lingered in a comment or dead code.
        for path in (BUILT_SHAREABLE, BUILT_NONSHAREABLE):
            built = _read(path)
            mermaid_urls = [u for u in url_re.findall(built) if "mermaid" in u.lower()]
            self.assertIn(esm, mermaid_urls, "no remote mermaid import found in %s" % path)
            for u in mermaid_urls:
                self.assertIn(
                    u, allowed,
                    "unexpected/unpinned mermaid CDN URL in %s: %r" % (os.path.basename(path), u))
        # The source shell keeps the single-source placeholder + jsDelivr host, so the pin can only
        # ever come from package.json via build.py, never a hardcoded floating tag.
        shell = _read(SHELL_SOURCE)
        self.assertIn("cdn.jsdelivr.net/npm/mermaid@{{MERMAID_VERSION}}", shell)
        self.assertNotIn("mermaid@latest", shell)

    def test_security_spec_documents_the_accepted_cdn_risk(self):
        spec = _read(SECURITY_SPEC)
        self.assertIn("CMH-SEC-04", spec)
        low = spec.lower()
        self.assertIn("jsdelivr", low)
        self.assertIn("accepted", low)
        self.assertIn("mermaid", low)
        # The row must name this covering test so the spec-and-test tie stays intact.
        self.assertIn("test_cdn_bydesign.py", spec)

    def test_vendored_rich_libraries_are_credited(self):
        upstream = _read(VENDOR_UPSTREAM)
        self.assertIn("mermaid", upstream)
        self.assertIn("Chart.js", upstream)
        self.assertIn("MIT", upstream)


if __name__ == "__main__":
    unittest.main()
