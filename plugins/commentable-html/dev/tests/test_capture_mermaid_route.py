#!/usr/bin/env python3
"""CMH-BUILD-24: the tutorial capture's mermaid route survives a mermaid version bump.

`tools/capture_tutorial.mjs` renders the tutorial screenshots with every remote fetch aborted, and
registers ONE narrower route that serves mermaid's version-pinned jsDelivr import from the local
`node_modules/mermaid/dist`. That route is the only thing standing between the capture and the
catch-all abort, so if its pattern stops matching the URL the built shell actually requests, mermaid
never loads, `waitForMermaid` times out, and `npm run shots` fails - with nothing pointing at the
cause.

The pattern used to carry a LITERAL `mermaid@11.16.0`, while the URL it must match is single-sourced
from `package.json` (`build.read_mermaid_version`, restamped into the shell and every example on each
build). So the two drifted apart the moment the dependency was bumped - which is exactly when a
maintainer is least able to tell a broken capture from a broken bump. This test pins them together:
whatever form the route argument takes, it must match the real, current CDN URL.
"""
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402
sys.path.insert(0, _paths.DEV_TOOLS)
import build  # noqa: E402

CAPTURE = os.path.join(_paths.DEV_TOOLS, "capture_tutorial.mjs")
# The first argument of the `context.route(...)` call inside routeVendoredMermaid: either a quoted
# glob string or a regex literal.
_ROUTE_CALL = re.compile(
    r"routeVendoredMermaid\s*\([^)]*\)\s*\{.*?context\.route\(\s*(?P<arg>\"[^\"]+\"|'[^']+'|/.+?/[a-z]*)\s*,",
    re.S)


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _route_argument():
    m = _ROUTE_CALL.search(_read(CAPTURE))
    if not m:
        raise AssertionError("could not find the context.route(...) call in routeVendoredMermaid")
    return m.group("arg")


def _as_python_pattern(arg):
    """Translate the JS route argument into an equivalent Python regex.

    Playwright accepts either a glob string (`**` spans path separators, `*` does not) or a regex
    that is tested against the whole URL. Both forms are supported here so the test pins the
    BEHAVIOR (does this route match the URL?) rather than one particular spelling of it.
    """
    if arg.startswith("/"):
        body = arg[1:arg.rindex("/")]
        return re.compile(body), False
    literal = arg[1:-1]
    out = []
    i = 0
    while i < len(literal):
        if literal.startswith("**", i):
            out.append(".*")
            i += 2
        elif literal[i] == "*":
            out.append("[^/]*")
            i += 1
        elif literal[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(literal[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$"), True


def _cdn_urls():
    """The mermaid URLs the capture must serve: the shell's pinned entry module, plus a relative
    chunk it imports (those resolve against the same CDN base and are intercepted by the same
    route)."""
    version = build.read_mermaid_version()
    base = "https://cdn.jsdelivr.net/npm/mermaid@%s/dist/" % version
    return [base + "mermaid.esm.min.mjs", base + "chunks/mermaid.esm.min/blockDiagram-abc123.mjs"]


class CaptureMermaidRouteTests(unittest.TestCase):
    """CMH-BUILD-24"""

    def test_the_capture_route_matches_the_current_pinned_mermaid_cdn_url(self):
        pattern, anchored = _as_python_pattern(_route_argument())
        for url in _cdn_urls():
            hit = pattern.match(url) if anchored else pattern.search(url)
            self.assertIsNotNone(
                hit,
                "capture_tutorial.mjs's mermaid route does not match %s - the capture would abort "
                "the import and waitForMermaid would time out. The route must not pin a literal "
                "mermaid version; the URL is single-sourced from package.json." % url)

    def test_the_capture_route_does_not_pin_a_literal_mermaid_version(self):
        self.assertNotRegex(
            _route_argument(), r"mermaid@\d",
            "the mermaid CDN version is single-sourced from package.json, so hard-coding it in the "
            "capture route silently breaks screenshot capture on the next bump")

    def test_the_route_still_only_matches_mermaid_on_the_pinned_cdn(self):
        pattern, anchored = _as_python_pattern(_route_argument())
        for url in ("https://cdn.jsdelivr.net/npm/chart.js@4.5.1/dist/chart.umd.min.js",
                    "https://evil.example/npm/mermaid@11.16.1/dist/mermaid.esm.min.mjs"):
            hit = pattern.match(url) if anchored else pattern.search(url)
            self.assertIsNone(hit, "the route must stay narrow; it matched %s" % url)


if __name__ == "__main__":
    unittest.main()
