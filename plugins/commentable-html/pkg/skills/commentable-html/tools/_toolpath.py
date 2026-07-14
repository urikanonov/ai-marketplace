"""Shared sys.path + resource-root helper for the topic-bucketed tools.

The tools are invoked as standalone scripts (``python tools/<topic>/<name>.py``), and several
import a sibling tool by bare name (for example ``finalize`` imports ``validate``). Because the
tools now live in per-topic subdirectories, a bare import only resolves if every topic directory
is on ``sys.path``. A tool calls ``_toolpath.ensure()`` near the top to put the ``tools/`` root and
all of its topic subdirectories on ``sys.path``, and reads ``SKILL_ROOT`` / ``TOOLS_ROOT`` from here
instead of counting directory levels up from its own file, so a tool keeps working no matter which
bucket it lives in.
"""
import os
import sys

TOOLS_ROOT = os.path.dirname(os.path.abspath(__file__))   # .../skills/commentable-html/tools
SKILL_ROOT = os.path.dirname(TOOLS_ROOT)                   # .../skills/commentable-html


def tool_dirs():
    """The tools/ root followed by every topic subdirectory (sorted), skipping private/dunder
    directories like __pycache__."""
    dirs = [TOOLS_ROOT]
    for name in sorted(os.listdir(TOOLS_ROOT)):
        d = os.path.join(TOOLS_ROOT, name)
        if os.path.isdir(d) and not name.startswith(("_", ".")):
            dirs.append(d)
    return dirs


def ensure():
    """Put the tools/ root and every topic subdirectory on sys.path so a sibling tool resolves by
    bare ``import <name>`` regardless of which bucket either tool sits in."""
    for d in tool_dirs():
        if d not in sys.path:
            sys.path.insert(0, d)
