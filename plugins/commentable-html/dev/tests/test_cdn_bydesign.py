#!/usr/bin/env python3
"""CMH-SEC-04: guard the by-design mermaid/Chart.js CDN accepted-risk decision.

The runtime auto-loads mermaid from a version-pinned jsDelivr URL on the online render path. The
maintainer decision (#451) is to KEEP that CDN import as an accepted supply-chain risk, because the
import is pinned to an immutable artifact on a top-tier CDN and a fully zero-network artifact is
available via Export Offline (which inlines the vendored copies). These tests keep that decision
honest: the import must stay version-pinned (never a floating tag), the accepted risk must stay
documented in the security spec so a future security scan treats it as out of scope, and the vendored
libraries must keep their MIT attribution. Standard library only.
"""
import json
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402  shared pkg/dev split path constants

PACKAGE_JSON = os.path.join(_paths.DEV, "package.json")
BUILT_TEMPLATE = _paths.TEMPLATE  # dev/skill/dist/PORTABLE.html (the stamped, built stage)
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
        built = _read(BUILT_TEMPLATE)
        expected = "https://cdn.jsdelivr.net/npm/mermaid@%s/dist/mermaid.esm.min.mjs" % base
        self.assertIn(expected, built)
        # A floating tag or an unstamped placeholder would defeat the "pinned to an immutable
        # artifact" property the accepted-risk decision rests on.
        self.assertNotIn("mermaid@latest", built)
        self.assertNotIn("mermaid@{{MERMAID_VERSION}}", built)
        # The source template must keep the single-source placeholder + jsDelivr host, so the pin
        # can only ever come from package.json via build.py, never a hardcoded floating tag.
        shell = _read(SHELL_SOURCE)
        self.assertIn("cdn.jsdelivr.net/npm/mermaid@{{MERMAID_VERSION}}", shell)

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
