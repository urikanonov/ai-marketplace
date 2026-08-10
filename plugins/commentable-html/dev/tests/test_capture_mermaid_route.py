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
# The first argument of the `context.route(...)` call inside routeVendoredMermaid: a quoted glob, a
# regex literal, or an identifier bound to one of those just above (all three are ordinary ways to
# write this, and a guard that reds on a benign refactor is drift waiting to happen).
_ROUTE_CALL = re.compile(
    r"routeVendoredMermaid\s*\([^)]*\)\s*\{(?P<body>.*?)context\.route\(\s*"
    r"(?P<arg>\"[^\"]+\"|'[^']+'|/.+?/[a-z]*|[A-Za-z_$][\w$]*)\s*,",
    re.S)
_PATTERN_LITERAL = r"(\"[^\"]+\"|'[^']+'|/.+?/[a-z]*)"


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _route_argument():
    source = _read(CAPTURE)
    m = _ROUTE_CALL.search(source)
    if not m:
        raise AssertionError("could not find the context.route(...) call in routeVendoredMermaid")
    arg = m.group("arg")
    if arg[0] in "\"'/":
        return arg
    # An identifier: resolve the binding, so moving the pattern into a `const` stays supported.
    bound = re.search(r"\b(?:const|let|var)\s+%s\s*=\s*%s" % (re.escape(arg), _PATTERN_LITERAL),
                      source)
    if not bound:
        raise AssertionError(
            "the route pattern is the identifier %r and its literal binding could not be found; "
            "bind it to a literal in this module or extend _route_argument" % arg)
    return bound.group(1)


def _as_python_pattern(arg):
    """Translate the JS route argument into an equivalent Python regex.

    Playwright accepts either a glob string or a regex that is tested against the whole URL. Both
    forms are handled so the test pins the BEHAVIOR (does this route match the URL?) rather than one
    particular spelling of it - but the equivalence is only claimed for the two shapes this route is
    plausibly written in: a regex literal, and a glob whose wildcards are not the `/**/` form.
    Playwright compiles a `**` flanked by slashes on BOTH sides to an optional group that can also
    match zero segments INCLUDING the slashes, which a naive `.*` does not reproduce; rather than
    model that badly, refuse it and say so.
    """
    if arg.startswith("/"):
        end = arg.rindex("/")
        body, flags = arg[1:end], arg[end + 1:]
        # A dropped flag would silently change what is being asserted, so map what we can and refuse
        # the rest instead of quietly comparing a different pattern than Playwright would evaluate.
        py_flags = 0
        for flag in flags:
            if flag == "i":
                py_flags |= re.IGNORECASE
            elif flag == "s":
                py_flags |= re.DOTALL
            elif flag == "u":
                continue  # Python 3 patterns are already Unicode; JS `u` has no separate effect here.
            else:
                raise AssertionError(
                    "unsupported JS regex flag %r in the route pattern; teach _as_python_pattern "
                    "how it maps to Python re before relying on this test" % flag)
        return re.compile(body, py_flags), False
    literal = arg[1:-1]
    for meta in ("/**/", "{", "}", "["):
        if meta in literal:
            raise AssertionError(
                "the route is a glob containing %r, whose Playwright semantics this translator does "
                "not reproduce (brace alternation, character classes, and a `/**/` that may match "
                "zero segments including its slashes); express the route as a regex literal or "
                "extend _as_python_pattern" % meta)
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

    def test_the_capture_refuses_to_render_with_a_mermaid_that_is_not_the_pinned_one(self):
        """Version-agnostic about the URL must not mean indifferent to the BYTES.

        The route serves the local entry module, whose relative chunk imports resolve back through
        the same route, so a render is internally consistent at WHATEVER version is on disk. Without
        a refusal the capture would happily write the committed PNGs from a mermaid that never
        ships, and the only symptom would be an unexplained exact-pixel drift failure in CI, which
        installs the pinned version.
        """
        source = _read(CAPTURE)
        m = _ROUTE_CALL.search(source)
        self.assertIsNotNone(m, "could not find the context.route(...) call in routeVendoredMermaid")
        # Scope this to the CALLER, not the file: `assertInstalledMermaidIsPinned()` also appears in
        # the function's own declaration, so searching the whole source would stay green with the
        # guard defined and never invoked - exactly the regression it exists to prevent.
        self.assertIn(
            "assertInstalledMermaidIsPinned()", m.group("body"),
            "routeVendoredMermaid must CALL assertInstalledMermaidIsPinned() before registering the "
            "route, or a stale node_modules silently renders the tutorial screenshots")
        guard = re.search(r"function assertInstalledMermaidIsPinned\(\)\s*\{(.*?)\n\}", source, re.S)
        self.assertIsNotNone(guard, "assertInstalledMermaidIsPinned is not defined")
        body = guard.group(1)
        self.assertIn("node_modules", body, "the guard must read the INSTALLED version")
        self.assertIn("package.json", body, "the guard must read the PINNED version")
        self.assertIn("throw", body, "the guard must refuse, not warn - a warning scrolls past")


if __name__ == "__main__":
    unittest.main()
