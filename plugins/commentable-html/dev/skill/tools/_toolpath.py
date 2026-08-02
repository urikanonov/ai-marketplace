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

SHAREABLE_TEMPLATE = "SHAREABLE.html"
NONSHAREABLE_TEMPLATE = "NONSHAREABLE.html"
# The pre-rename names of the same two templates. A stage/checkout built by an older release still
# carries only these, so every tool resolves the current name FIRST and falls back to the legacy one
# rather than failing with a missing-template error.
LEGACY_TEMPLATE_NAMES = {
    SHAREABLE_TEMPLATE: "PORTABLE.html",
    NONSHAREABLE_TEMPLATE: "NONPORTABLE.html",
}


def dist_template(name=SHAREABLE_TEMPLATE, dist_dir=None, root=None):
    """Absolute path to a dist template, preferring the current name and falling back to the
    pre-rename legacy name when only that exists. When neither exists the CURRENT name is
    returned, so a missing-file error names the file a fresh build produces."""
    d = dist_dir if dist_dir is not None else os.path.join(root or SKILL_ROOT, "dist")
    primary = os.path.join(d, name)
    if os.path.exists(primary):
        return primary
    legacy = LEGACY_TEMPLATE_NAMES.get(name)
    if legacy:
        candidate = os.path.join(d, legacy)
        if os.path.exists(candidate):
            return candidate
    return primary


# The reverse map, for a caller that still NAMES a template by its pre-rename filename.
_CURRENT_TEMPLATE_NAMES = {legacy: current for current, legacy in LEGACY_TEMPLATE_NAMES.items()}


def resolve_template_path(path):
    """Map a caller-supplied template path onto the file that exists today.

    An existing script or recipe may still pass `--template <dist>/PORTABLE.html` (or
    `NONPORTABLE.html`). Those files were renamed, so the path no longer resolves; when the
    missing file is one of the two pre-rename template names and its current-name sibling IS
    present, return that instead. Any other path is returned untouched, so a caller's own custom
    template is never redirected."""
    if not path or os.path.exists(path):
        return path
    current = _CURRENT_TEMPLATE_NAMES.get(os.path.basename(path))
    if not current:
        return path
    candidate = os.path.join(os.path.dirname(path), current)
    return candidate if os.path.exists(candidate) else path


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


def warn_missing_tool(name, feature=""):
    """Emit a one-line stderr WARNING that an optional sibling tool could not be imported, so a
    degraded run is never SILENT. In a correct install every sibling ships in the skill and resolves,
    so this only ever fires on a broken/partial install - and it must be VISIBLE, not swallowed (the
    silent-import class of bug that hid the #584 root cause). Best-effort: it never raises."""
    try:
        suffix = " (%s is degraded)" % feature if feature else ""
        sys.stderr.write(
            "commentable-html: WARNING - optional tool '%s' could not be imported%s; this indicates "
            "a broken or partial install (re-install or re-extract the skill).\n" % (name, suffix))
    except Exception:  # pragma: no cover - a broken stderr must not crash a degraded run
        pass
