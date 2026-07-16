#!/usr/bin/env python3
"""Build the commentable-html distributable set from the canonical sources.

Single source of truth
----------------------
  VERSION                       - the release version (semver). This is the ONE
                                  place the version is hand-edited; build stamps
                                  it into the layer const, plugin.json, the
                                  marketplace entry, and each document's
                                  <meta name="commentable-html-version">.
  package.json (mermaid dep)    - the ONE place the mermaid CDN version is set;
                                  build reads it and stamps the mermaid@<ver> import
                                  into the shipped templates and the example reports,
                                  so they never drift from the version the tests
                                  vendor. Dependabot bumps it; --check flags drift.
  assets/css/NN-topic.css       - the layer CSS as numbered topic partials (directory-sorted,
                                  concatenated by build; the sort order is the cascade)
  assets/js/NN-topic.js         - the runtime JS as numbered topic partials (directory-sorted,
                                  concatenated by build; the sort order is the single-IIFE
                                  statement order). One partial declares CMH_VERSION, stamped
                                  from VERSION by build. See assets/js/MODULES.md.
  assets/template.shell.html    - the page shell with {{CMH_CSS}} / {{CMH_JS}} /
                                  {{CMH_VERSION}} / {{MERMAID_VERSION}} placeholders
                                  and the demo content.

Generated (never hand-edit; `--check` fails if they drift)
----------------------------------------------------------
  dist/PORTABLE.html                  - inline / standalone template (self-contained)
  dist/commentable-html.css           - external layer stylesheet (version-agnostic name)
  dist/commentable-html.js            - external runtime
  dist/commentable-html.assets.js     - asset registry (css+js as strings) used by
                                        "Export as Portable" to rebuild a portable file
  dist/manifest.json                  - version + sha256 of each companion file
  dist/NONPORTABLE.html               - nonportable template, sitting next to its companions

Bumping the version: edit VERSION, then run this builder (it re-stamps every
spot and regenerates dist). Companion filenames are version-agnostic, so a bump
never renames dist files.

Usage (flat layout, run from the skill root):
  python tools/build.py            # (re)generate everything, print a size report
  python tools/build.py --check    # verify on-disk generated files match a fresh build

Split layout (canonical assets and generated outputs in different directories, e.g.
the ai-marketplace pkg/dev split - run from dev/):
  python tools/build.py --assets-dir assets --out-dir ../pkg/skills/commentable-html
  python tools/build.py --assets-dir assets --out-dir ../pkg/skills/commentable-html --check

--assets-dir defaults to <skill>/assets and --out-dir defaults to the skill root (the
directory that receives dist/PORTABLE.html and dist/). --check compares the files already
present in --out-dir against a fresh build.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

# Flat-layout defaults: assets sit next to the generated outputs under the skill root.
# The split layout overrides these per-call via --assets-dir / --out-dir (and the
# functions below accept explicit dirs so a caller can point them anywhere).
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(HERE, "assets")
DIST = os.path.join(HERE, "dist")
# The Playwright fixtures embed the runtime version, so a version bump that regenerates
# dist/ can leave them stale. build.py --check --check-fixtures runs the fixtures'
# own generate.mjs --check so the single dist gate also owns fixture freshness.
FIXTURES_GEN = os.path.join(HERE, "tests", "fixtures", "generate.mjs")
# Independent CONTENT source for the shipped examples. Each dev/examples/src/report-*.html or
# dev/examples/src/deck-*.html is the source of truth for a demo's own content (and handled/
# embedded-comment data); build.py assembles the shipped pkg examples/<same-name>.html from it by
# swapping in the current layer and re-stamping the version. Because the shipped example is a pure
# artifact of this source (not of itself), --check compares it to a fresh assembly and CATCHES a
# hand-edit or a stale/clobbered committed example - closing the self-sourced hole that the site
# pages had before #91. The layer regions inside a source file are ignored (build.py overwrites
# them), kept only so the source is itself a valid, openable commentable-html document.
# A dev/examples/src/prompt-*.md (a one-shot authoring prompt) is plain Markdown with no layer to
# swap, so build.py copies it VERBATIM to the shipped examples/<same-name>.md and --check flags any
# drift the same way.
EXAMPLES_SRC = os.path.join(HERE, "examples", "src")


# --------------------------------------------------------------------------- #
# IO helpers (everything is LF)
# --------------------------------------------------------------------------- #
def _lf(s):
    return s.replace("\r\n", "\n").replace("\r", "\n")


def read(path):
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return _lf(fh.read())


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(_lf(text))


def sha256(text):
    return hashlib.sha256(_lf(text).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# Version: the VERSION file at the dev root is the single source of truth. build
# reads it and stamps it into the layer const, plugin.json, the marketplace
# entry, and the per-document <meta>. --check verifies every stamped spot.
# --------------------------------------------------------------------------- #
VERSION_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "VERSION")
PACKAGE_JSON = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "package.json")
_SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
# The mermaid CDN import in the shipped templates/examples, so build can stamp it
# from the single source (package.json) and --check can catch drift. The version
# segment is matched liberally (any non-slash token, not just an exact X.Y.Z) so a
# drifted major-only or malformed pin is still detected and repaired; it is scoped
# to the .../mermaid@<ver>/dist/ import path so it never rewrites unrelated text.
_MERMAID_CDN_RE = re.compile(r"(cdn\.jsdelivr\.net/npm/mermaid@)[^/]+(/dist/)")
_CMH_CONST_RE = re.compile(r'(?m)^(\s*const\s+CMH_VERSION\s*=\s*")[0-9]+\.[0-9]+\.[0-9]+("\s*;)')
_JSON_VERSION_RE = re.compile(r'("version"\s*:\s*")([0-9]+\.[0-9]+\.[0-9]+)(")')
_MARKETPLACE_VERSION_RE = re.compile(
    r'("name"\s*:\s*"commentable-html"[\s\S]*?"version"\s*:\s*")([0-9]+\.[0-9]+\.[0-9]+)(")')
# The visible, human-readable version line stamped into SKILL.md and dist/README.md.
_MD_VERSION_RE = re.compile(r'(\*\*Version:\*\* `)([0-9]+\.[0-9]+\.[0-9]+)(`)')


def read_version(version_file=None):
    version_file = VERSION_FILE if version_file is None else version_file
    with open(version_file, "r", encoding="utf-8") as fh:
        v = fh.read().strip()
    if not _SEMVER_RE.match(v):
        raise SystemExit("build: VERSION must be a semver like 1.2.3, got %r" % v)
    return v


def read_mermaid_version(package_json=None):
    """The mermaid CDN version is single-sourced from the dev package.json's
    mermaid dependency. build stamps it into the shipped templates and examples so
    they never drift from the version the tests vendor (dev/tests/helpers.js
    routeMermaidLocal fails when the served template's major differs from the
    node_modules major). The declared range (e.g. ^11.16.0) is pinned to its exact
    base version (11.16.0) in the stamped output."""
    package_json = PACKAGE_JSON if package_json is None else package_json
    with open(package_json, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    spec = ((data.get("devDependencies") or {}).get("mermaid")
            or (data.get("dependencies") or {}).get("mermaid"))
    if not spec:
        raise SystemExit("build: no mermaid dependency found in %s" % package_json)
    # Only an exact pin or a caret/tilde range maps unambiguously to a single CDN
    # version. Reject comparator ranges (>=, <, <=, >), unions, wildcards (11.x, *),
    # tags (latest), and prereleases - lstrip-style char stripping would silently
    # mis-pin those (e.g. "<12.0.0" -> "12.0.0"), so fail loudly instead.
    m = re.match(r"^[\^~]?(\d+\.\d+\.\d+)$", spec.strip())
    if not m:
        raise SystemExit("build: the mermaid dependency must be an exact version or a ^/~ pin "
                         "like 11.16.0 or ^11.16.0 (comparator ranges/tags are unsupported), "
                         "got %r in %s" % (spec, package_json))
    return m.group(1)


def example_stamps(out_dir, mermaid_version):
    """Return {path: stamped_text} for hand-maintained example files that build_examples
    does NOT fully regenerate, with only their mermaid CDN version rewritten to the single
    source (package.json). report-*.html and deck-*.html files are owned by build_examples
    (which stamps mermaid itself), so they are skipped here to avoid two producers writing
    the same path. --check flags drift."""
    stamps = {}
    ex_dir = os.path.join(out_dir, "examples")
    if not os.path.isdir(ex_dir):
        return stamps
    for name in sorted(os.listdir(ex_dir)):
        if not name.endswith(".html") or _EXAMPLE_NAME_RE.match(name):
            continue
        path = os.path.join(ex_dir, name)
        text = read(path)
        new, n = _MERMAID_CDN_RE.subn(lambda m: m.group(1) + mermaid_version + m.group(2), text)
        if n:
            stamps[path] = new
    return stamps


def _stamp_const(text, version, label):
    new, n = _CMH_CONST_RE.subn(lambda m: m.group(1) + version + m.group(2), text)
    if n != 1:
        raise SystemExit("build: expected exactly one CMH_VERSION declaration in %s, found %d" % (label, n))
    return new


def _stamp_plugin_json(text, version):
    # Stamp ONLY the top-level "version" (a schema-valid manifest may carry a
    # nested version, e.g. author.version), preserving the file's formatting.
    data = json.loads(text)
    if not isinstance(data, dict) or "version" not in data:
        raise SystemExit("build: plugin.json has no top-level version field")
    m = _JSON_VERSION_RE.search(text)
    if not m or m.group(2) != str(data["version"]):
        raise SystemExit("build: could not locate the top-level version in plugin.json "
                         "(a nested version appears before it)")
    return text[:m.start(2)] + version + text[m.end(2):]


def _stamp_marketplace(text, version):
    # Rewrite ONLY the commentable-html entry's version, leaving all other
    # entries and the file's formatting untouched (so an unrelated edit to the
    # manifest cannot make build --check fail on formatting grounds).
    json.loads(text)  # validate the manifest is well-formed before stamping
    new, n = _MARKETPLACE_VERSION_RE.subn(lambda m: m.group(1) + version + m.group(3), text, count=1)
    if n != 1:
        raise SystemExit("build: no commentable-html entry version found in marketplace.json")
    return new


def _stamp_md_version(text, version, label):
    # Re-stamp the single human-readable `**Version:** `x.y.z`` line so SKILL.md and
    # dist/README.md show the current version and never drift from dev/VERSION.
    new, n = _MD_VERSION_RE.subn(lambda m: m.group(1) + version + m.group(3), text)
    if n != 1:
        raise SystemExit("build: expected exactly one '**Version:** `x.y.z`' line in %s, found %d" % (label, n))
    return new


def _find_marketplace(start):
    cur = os.path.abspath(start)
    while True:
        cand = os.path.join(cur, ".github", "plugin", "marketplace.json")
        if os.path.exists(cand):
            return cand
        # Stop at the repo root: never escape the current repo into an ancestor
        # checkout that might have its own marketplace.json.
        if os.path.exists(os.path.join(cur, ".git")):
            return None
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent


def source_stamps(version, assets_dir, out_dir):
    """Return {path: stamped_text} for the hand-maintained files that carry the
    version: the layer const, plugin.json (Copilot and Claude), the marketplace entry
    (Copilot and Claude), and the visible `**Version:**` line in SKILL.md and dist/README.md.
    Only files that exist are included, so non-standard layouts degrade gracefully. Examples
    are NOT stamped here - they embed the whole layer and are regenerated from dist, which
    already carries the version."""
    stamps = {}
    js_path = _js_version_part(assets_dir)
    stamps[js_path] = _stamp_const(read(js_path), version, os.path.basename(js_path))
    plugin_json = os.path.join(os.path.dirname(os.path.dirname(out_dir)), "plugin.json")
    if os.path.exists(plugin_json):
        stamps[plugin_json] = _stamp_plugin_json(read(plugin_json), version)
    # The Claude Code manifest mirrors the Copilot plugin.json (identity fields incl. version),
    # so it is a version spot too - stamp it the same way to keep the mirror in sync on every bump.
    claude_plugin_json = os.path.join(
        os.path.dirname(os.path.dirname(out_dir)), ".claude-plugin", "plugin.json")
    if os.path.exists(claude_plugin_json):
        stamps[claude_plugin_json] = _stamp_plugin_json(read(claude_plugin_json), version)
    marketplace = _find_marketplace(out_dir)
    if marketplace:
        stamps[marketplace] = _stamp_marketplace(read(marketplace), version)
        # The Claude marketplace (repo-root .claude-plugin/marketplace.json) mirrors the Copilot
        # marketplace entry, so stamp its commentable-html entry version alongside.
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(marketplace)))
        claude_marketplace = os.path.join(repo_root, ".claude-plugin", "marketplace.json")
        if os.path.exists(claude_marketplace):
            stamps[claude_marketplace] = _stamp_marketplace(read(claude_marketplace), version)
    # Human-readable version lines: the shipped SKILL.md and dist/README.md so a reader can see
    # which version they have. Only stamped when present (a bare --assets-dir build has neither).
    skill = os.path.join(out_dir, "SKILL.md")
    if os.path.exists(skill):
        stamps[skill] = _stamp_md_version(read(skill), version, "SKILL.md")
    readme = os.path.join(out_dir, "dist", "README.md")
    if os.path.exists(readme):
        stamps[readme] = _stamp_md_version(read(readme), version, "dist/README.md")
    return stamps


# --------------------------------------------------------------------------- #
# Sources + version
# --------------------------------------------------------------------------- #
# The layer CSS and runtime JS ship as small topic partials under assets/css/ and assets/js/,
# each named `NN-topic.ext` with a zero-padded 2-digit prefix. build.py assembles them by
# DIRECTORY SORT (no hand-maintained order list in this script, so adding a partial does not edit
# build.py and two PRs adding partials do not collide here). The sorted order is load-bearing:
# for JS it is the single-IIFE statement order; for CSS it is the cascade. The concatenation is
