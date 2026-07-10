"""Shared path constants for the commentable-html test suite (marketplace pkg/dev split).

The runtime skill ships under pkg/skills/commentable-html; the tests, canonical assets, and
build tooling live here under dev/. Tests import the REAL shipped tools from PKG/tools (each
test adds it to sys.path) so a green suite proves exactly what ships. Build inputs (assets)
and the maintainer-only build tool live under dev/.

Set CMH_PKG_DIR to override the shipped-skill location (e.g. to test a staged copy).
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))              # dev/tests
DEV = os.path.dirname(HERE)                                    # dev
PKG = os.environ.get("CMH_PKG_DIR") or os.path.normpath(
    os.path.join(DEV, "..", "pkg", "skills", "commentable-html"))
TOOLS = os.path.join(PKG, "tools")                             # shipped runtime tools
DIST = os.path.join(PKG, "dist")
TEMPLATE = os.path.join(PKG, "dist", "PORTABLE.html")
EXAMPLES = os.path.join(PKG, "examples")
ASSETS = os.path.join(DEV, "assets")                           # build inputs (dev-only)
DEV_TOOLS = os.path.join(DEV, "tools")                         # maintainer-only tools (build.py)
