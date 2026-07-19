"""Shared path constants for the commentable-html test suite (marketplace pkg/dev split).

The editable + built skill tree (the STAGE) lives here under dev/skill; the plugin ships a minimal
pkg/skills/commentable-html (SKILL.md, LICENSE, THIRD_PARTY_NOTICES.md, skill-resources.zip) that a SessionStart hook
extracts on first run. Tests import the REAL tools and read the REAL dist/examples from the STAGE
(PKG below), which build.py assembles into the shipped skill-resources.zip, so a green suite proves
exactly what ships once extracted. The tools are grouped into per-topic subdirectories
(tools/<topic>/); importing this module runs the tools/_toolpath.py bootstrap so a test can
``import <tool>`` by bare name (as the shipped tools do) regardless of which bucket it lives in.
Build inputs (assets) and the maintainer-only build tool live under dev/.

Set CMH_PKG_DIR to override the STAGE skill location (e.g. to test a staged copy).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))              # dev/tests
DEV = os.path.dirname(HERE)                                    # dev
PKG = os.environ.get("CMH_PKG_DIR") or os.path.join(DEV, "skill")  # STAGE: full editable+built skill
PLUGIN_ROOT = os.path.dirname(DEV)                             # plugins/commentable-html
TOOLS = os.path.join(PKG, "tools")                             # runtime tools (topic-bucketed)
DECK = os.path.join(TOOLS, "deck")                             # deck tools bucket (tools/deck/)
DIST = os.path.join(PKG, "dist")
TEMPLATE = os.path.join(PKG, "dist", "PORTABLE.html")
# The tutorial and worked examples are NOT shipped (not in the skill-resources.zip); they live at
# the plugin top level next to pkg/ and dev/.
EXAMPLES = os.path.join(PLUGIN_ROOT, "examples")
DOCS = os.path.join(PLUGIN_ROOT, "docs")
ASSETS = os.path.join(DEV, "assets")                           # build inputs (dev-only)
DEV_TOOLS = os.path.join(DEV, "tools")                         # maintainer-only tools (build.py)
PKG_SHIPPED = os.path.join(PLUGIN_ROOT, "pkg", "skills", "commentable-html")  # minimal shipped dir
HOOKS = os.path.join(PLUGIN_ROOT, "pkg", "hooks")             # shipped SessionStart hook + extractor

# Put the tools/ root and every topic subdirectory on sys.path via the shipped bootstrap, so a bare
# `import <tool>` in a test resolves the same way it does for the shipped tools themselves.
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)
try:
    import _toolpath  # noqa: E402
    _toolpath.ensure()
except Exception:  # pragma: no cover - a broken/absent bootstrap surfaces via the import tests
    pass
