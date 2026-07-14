"""Shared path constants for the commentable-html test suite (marketplace pkg/dev split).

The runtime skill ships under pkg/skills/commentable-html; the tests, canonical assets, and
build tooling live here under dev/. Tests import the REAL shipped tools from PKG/tools so a green
suite proves exactly what ships. The shipped tools are grouped into per-topic subdirectories
(tools/<topic>/); importing this module runs the shipped tools/_toolpath.py bootstrap so a test can
``import <tool>`` by bare name (as the shipped tools do) regardless of which bucket it lives in.
Build inputs (assets) and the maintainer-only build tool live under dev/.

Set CMH_PKG_DIR to override the shipped-skill location (e.g. to test a staged copy).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))              # dev/tests
DEV = os.path.dirname(HERE)                                    # dev
PKG = os.environ.get("CMH_PKG_DIR") or os.path.normpath(
    os.path.join(DEV, "..", "pkg", "skills", "commentable-html"))
TOOLS = os.path.join(PKG, "tools")                             # shipped runtime tools (topic-bucketed)
DECK = os.path.join(TOOLS, "deck")                             # deck tools bucket (tools/deck/)
DIST = os.path.join(PKG, "dist")
TEMPLATE = os.path.join(PKG, "dist", "PORTABLE.html")
EXAMPLES = os.path.join(PKG, "examples")
ASSETS = os.path.join(DEV, "assets")                           # build inputs (dev-only)
DEV_TOOLS = os.path.join(DEV, "tools")                         # maintainer-only tools (build.py)

# Put the tools/ root and every topic subdirectory on sys.path via the shipped bootstrap, so a bare
# `import <tool>` in a test resolves the same way it does for the shipped tools themselves.
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)
try:
    import _toolpath  # noqa: E402
    _toolpath.ensure()
except Exception:  # pragma: no cover - a broken/absent bootstrap surfaces via the import tests
    pass
