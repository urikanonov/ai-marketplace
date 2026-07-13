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
  assets/commentable-html.css   - the layer CSS (region body)
  assets/commentable-html.js    - the runtime JS (region body); its CMH_VERSION
                                  constant is stamped from VERSION by build.
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
import sys

# Flat-layout defaults: assets sit next to the generated outputs under the skill root.
# The split layout overrides these per-call via --assets-dir / --out-dir (and the
# functions below accept explicit dirs so a caller can point them anywhere).
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(HERE, "assets")
DIST = os.path.join(HERE, "dist")


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
    """Return {path: stamped_text} for hand-maintained example reports that build_examples
    does NOT fully regenerate, with only their mermaid CDN version rewritten to the single
    source (package.json). report-*.html files are owned by build_examples (which stamps
    mermaid itself), so they are skipped here to avoid two producers writing the same path.
    --check flags drift."""
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
    version: the layer const, plugin.json, and the marketplace entry. Only files
    that exist are included, so non-standard layouts degrade gracefully. Examples
    are NOT stamped here - they embed the whole layer and are regenerated from
    dist, which already carries the version."""
    stamps = {}
    js_path = os.path.join(assets_dir, "commentable-html.js")
    stamps[js_path] = _stamp_const(read(js_path), version, "commentable-html.js")
    plugin_json = os.path.join(os.path.dirname(os.path.dirname(out_dir)), "plugin.json")
    if os.path.exists(plugin_json):
        stamps[plugin_json] = _stamp_plugin_json(read(plugin_json), version)
    marketplace = _find_marketplace(out_dir)
    if marketplace:
        stamps[marketplace] = _stamp_marketplace(read(marketplace), version)
    return stamps


# --------------------------------------------------------------------------- #
# Sources + version
# --------------------------------------------------------------------------- #
def load_sources(assets_dir=None):
    assets_dir = ASSETS if assets_dir is None else assets_dir
    css = read(os.path.join(assets_dir, "commentable-html.css")).rstrip("\n")
    js = read(os.path.join(assets_dir, "commentable-html.js")).rstrip("\n")
    shell = read(os.path.join(assets_dir, "template.shell.html"))
    return css, js, shell, read_version()


def _unexpected_dist_files(expected_paths, dist_dir=None):
    """Versioned dist companions present on disk but NOT in the freshly built set -
    i.e. stale artifacts left behind by an earlier version."""
    dist_dir = DIST if dist_dir is None else dist_dir
    if not os.path.isdir(dist_dir):
        return []
    expected = {os.path.normcase(os.path.abspath(p)) for p in expected_paths}
    stale = []
    for name in os.listdir(dist_dir):
        if re.match(r"commentable-html(\.v[0-9.]+)?\.(css|js|assets\.js)$", name):
            full = os.path.join(dist_dir, name)
            if os.path.normcase(os.path.abspath(full)) not in expected:
                stale.append(name)
    return sorted(stale)


def _legacy_generated_files(out_dir=None):
    out_dir = HERE if out_dir is None else out_dir
    return [
        os.path.join(out_dir, "TEMPLATE" + ".html"),
        os.path.join(out_dir, "dist", "ECO" + "NOMY" + ".html"),
    ]


def _names():
    # Companion filenames are version-agnostic; each HTML stamps its own version
    # in the <meta name="commentable-html-version"> and the visible footer.
    return "commentable-html.css", "commentable-html.js", "commentable-html.assets.js"


# --------------------------------------------------------------------------- #
# Output builders
# --------------------------------------------------------------------------- #
def build_inline(css, js, shell, version, mermaid_version):
    for ph in ("{{CMH_CSS}}", "{{CMH_JS}}", "{{CMH_VERSION}}", "{{MERMAID_VERSION}}"):
        if ph not in shell:
            raise SystemExit("build: shell is missing placeholder " + ph)
    return (shell.replace("{{CMH_CSS}}", css)
                 .replace("{{CMH_JS}}", js)
                 .replace("{{CMH_VERSION}}", version)
                 .replace("{{MERMAID_VERSION}}", mermaid_version))


def build_assets_js(css, js, version):
    payload = json.dumps({"version": version, "css": css, "js": js}, indent=2)
    reg = ("/* commentable-html v" + version + " asset registry - GENERATED, do not edit.\n"
           "   Loaded as a classic <script src> so it works from file://; defines the\n"
           "   css/js string payloads used by 'Export standalone' to rebuild a portable\n"
           "   single-file copy without fetch(). */\n"
           "window.__COMMENTABLE_ASSETS__ = " + payload + ";\n")
    if re.search(r"</\s*script", reg, re.IGNORECASE):
        raise SystemExit("build: assets registry contains a raw </script> - escaping is broken")
    return reg


_CSS_REGION_RE = re.compile(
    r"/\*[^\n]*\n\s*BEGIN: commentable-html - CSS.*?END: commentable-html - CSS[^*]*\*/",
    re.S)
_JS_REGION_RE = re.compile(
    r"<!--[^\n]*\n\s*BEGIN: commentable-html - JS.*?<!-- END: commentable-html - JS -->",
    re.S)

_BOOTSTRAP = (
    "<!-- BEGIN: commentable-html - NONPORTABLE BOOTSTRAP -->\n"
    '<div id="cmhAssetBanner" class="cm-skip" role="alert" hidden>\n'
    '  <span class="cmh-asset-message">Commentable-html could not load its companion files. Keep\n'
    "  <code>__JSNAME__</code>, <code>__ASSETSNAME__</code> and <code>__CSSNAME__</code>\n"
    "  in the same folder as this HTML, or open the standalone copy instead.</span>\n"
    '  <button type="button" class="cmh-asset-dismiss cm-skip" aria-label="Dismiss" '
    'onclick="var b=this.closest(\'#cmhAssetBanner\'); if (b) b.hidden=true;">X</button>\n'
    "</div>\n"
    "<script>\n"
    "  window.setTimeout(function () {\n"
    "    if (!window.__commentableHtmlReady) {\n"
    '      var b = document.getElementById("cmhAssetBanner");\n'
    "      if (b) b.hidden = false;\n"
    "    }\n"
    "  }, 3000);\n"
    "</scr" + "ipt>\n"
    "<!-- END: commentable-html - NONPORTABLE BOOTSTRAP -->\n"
)


def build_nonportable(shell, version, mermaid_version):
    css_name, js_name, assets_name = _names()
    t = shell

    # 1) Remove the inline layer-CSS region from inside <style>; link it instead.
    if not _CSS_REGION_RE.search(t):
        raise SystemExit("build: could not locate the CSS region in the shell")
    t = _CSS_REGION_RE.sub("", t)
    head_add = ("<!-- ============================================================\n"
                "     BEGIN: commentable-html - CSS\n"
                "     ============================================================ -->\n"
                '<link rel="stylesheet" href="' + css_name + '">\n'
                "<!-- END: commentable-html - CSS -->\n")
    if "</style>\n</head>" not in t:
        raise SystemExit("build: could not locate </style></head> in the shell")
    t = t.replace("</style>\n</head>", "</style>\n" + head_add + "</head>", 1)

    # 2) Replace the inline JS region with external <script src> companions.
    js_add = ("<!-- ============================================================\n"
              "     BEGIN: commentable-html - JS\n"
              "     ============================================================ -->\n"
              "<!-- commentable-html - layer loaded from companion files (nonportable mode) -->\n"
              '<script src="' + assets_name + '"></script>\n'
              '<script src="' + js_name + '"></script>\n'
              "<!-- END: commentable-html - JS -->")
    if not _JS_REGION_RE.search(t):
        raise SystemExit("build: could not locate the JS region in the shell")
    t = _JS_REGION_RE.sub(lambda _m: js_add, t)

    # 3) Inject the missing-asset banner + bootstrap right after the real body
    #    tag. Anchor the search after </head> so only the real <body> tag is matched.
    head_end = t.index("</head>")
    bm = re.search(r"<body[^>]*>", t[head_end:])
    if not bm:
        raise SystemExit("build: could not locate the <body> tag after </head>")
    idx = head_end + bm.end()
    boot = (_BOOTSTRAP.replace("__JSNAME__", js_name)
            .replace("__ASSETSNAME__", assets_name)
            .replace("__CSSNAME__", css_name))
    t = t[:idx] + "\n" + boot + t[idx:]

    # 4) Per-document identity so the nonportable demo does not collide with the
    #    inline demo in localStorage, and is clearly labelled.
    t = t.replace('data-comment-key="commentable-html-demo"',
                  'data-comment-key="commentable-html-nonportable-demo"', 1)
    t = t.replace('data-doc-source="PORTABLE.html"', 'data-doc-source="NONPORTABLE.html"', 1)
    t = t.replace("<title>Commentable HTML - Demo</title>",
                  "<title>Commentable HTML - NonPortable Demo</title>", 1)
    t = _stamp_layer_descriptor(t, version, "nonportable")

    t = re.sub(r"\n{3,}", "\n\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    t = t.replace("{{CMH_VERSION}}", version)
    t = t.replace("{{MERMAID_VERSION}}", mermaid_version)
    if "{{CMH_" in t or "{{MERMAID_" in t:
        raise SystemExit("build: an unresolved placeholder remains in NONPORTABLE.html")
    return t


class _MarkerMatch:
    def __init__(self, marker_start, marker_end):
        self._marker_start = marker_start
        self._marker_end = marker_end

    def start(self, group=0):
        return self._marker_start

    def end(self, group=0):
        return self._marker_end


def _advance_comment_state(line, state):
    i = 0
    while i < len(line):
        if state == "html":
            close = line.find("-->", i)
            if close < 0:
                return "html"
            state = ""
            i = close + 3
            continue
        if state == "css":
            close = line.find("*/", i)
            if close < 0:
                return "css"
            state = ""
            i = close + 2
            continue
        html_open = line.find("<!--", i)
        css_open = line.find("/*", i)
        if html_open >= 0 and (css_open < 0 or html_open < css_open):
            state = "html"
            i = html_open + 4
            continue
        if css_open >= 0:
            state = "css"
            i = css_open + 2
            continue
        return ""
    return state


def _region_marker_matches(text, kind, name):
    marker = "%s: commentable-html - %s" % (kind, name)
    marker_re = re.escape(marker)
    bare = re.compile(r"^[ \t]*(?:=+[ \t]*)?(%s)[ \t]*(?:=+[ \t]*)?$" % marker_re)
    inline = re.compile(r"^[ \t]*(?:<!--[ \t]*|/\*[ \t]*)(?:=+[ \t]*)?(%s)[ \t]*(?:=+[ \t]*)?(?:-->|\*/)[ \t]*$" % marker_re)
    matches = []
    state = ""
    offset = 0
    for line in (text or "").splitlines(True):
        body = line[:-1] if line.endswith("\n") else line
        if body.endswith("\r"):
            body = body[:-1]
        m = inline.match(body)
        if m is None and state in ("html", "css"):
            m = bare.match(body)
        if m is not None:
            matches.append(_MarkerMatch(offset + m.start(1), offset + m.end(1)))
        state = _advance_comment_state(body, state)
        offset += len(line)
    return matches


def _region_inner(text, name, where):
    """Return (start, end) offsets of a layer region's inner content (between the BEGIN
    and END marker lines). The line-anchored match ignores marker-like strings.
    Mirrors tools/upgrade.py so example regeneration and end-user upgrades agree."""
    begins = _region_marker_matches(text, "BEGIN", name)
    if not begins:
        raise SystemExit("build: %s: '%s' region BEGIN marker not found" % (where, name))
    if len(begins) > 1:
        raise SystemExit("duplicate region: %s" % name)
    bm = begins[0]
    b = bm.end(1)
    ends = [m for m in _region_marker_matches(text, "END", name) if m.start(1) >= b]
    if not ends:
        raise SystemExit("build: %s: '%s' region END marker not found after BEGIN" % (where, name))
    if len(ends) > 1:
        raise SystemExit("duplicate region: %s" % name)
    em = ends[0]
    return b, em.start(1)


# Layer regions swapped into each example from the freshly built PORTABLE.html. HANDLED
# IDS, EMBEDDED COMMENTS, CONTENT, and the #commentRoot wrapper are the report's own data
# and are never touched.
_LAYER_REGIONS = ("CSS", "HANDLED IDS", "EMBEDDED COMMENTS", "COMMENT UI", "JS")
_EXAMPLE_SWAP_REGIONS = ("CSS", "COMMENT UI", "JS")
_EXAMPLE_NAME_RE = re.compile(r"^report-.*\.html$")
_META_VERSION_RE = re.compile(
    r'(<meta name="commentable-html-version" content=")[0-9]+\.[0-9]+\.[0-9]+(")')
_LAYER_DESCRIPTOR_RE = re.compile(
    r'<script\b[^>]*\sid\s*=\s*(["\'])commentableHtmlLayer\1[^>]*>[\s\S]*?</script>\s*',
    re.IGNORECASE)
_LAYER_DESCRIPTOR_INSERT_RE = re.compile(
    r'(<meta name="commentable-html-version" content="[0-9]+\.[0-9]+\.[0-9]+" />?\s*)',
    re.IGNORECASE)
_CONTENT_BEGIN_TEXT = "BEGIN: commentable-html - CONTENT"
_CONTENT_ROOT_RE = re.compile(r'<main\b[^>]*?\bid\s*=\s*(["\'])commentRoot\1[^>]*>', re.IGNORECASE)


def _layer_descriptor(version, mode):
    data = {
        "version": version,
        "mode": mode,
        "regions": ["CSS", "HANDLED IDS", "EMBEDDED COMMENTS", "COMMENT UI", "JS"],
    }
    return '<script type="application/json" id="commentableHtmlLayer">' + json.dumps(data, separators=(",", ":")) + "</script>\n"


def _stamp_layer_descriptor(text, version, mode):
    desc = _layer_descriptor(version, mode)
    head_end = text.lower().find("</head>")
    if head_end == -1:
        raise SystemExit("build: could not locate </head> to place the layer descriptor")
    head, tail = text[:head_end], text[head_end:]
    if _LAYER_DESCRIPTOR_RE.search(head):
        return _LAYER_DESCRIPTOR_RE.sub(desc, head, count=1) + tail
    new, n = _LAYER_DESCRIPTOR_INSERT_RE.subn(lambda m: m.group(1) + desc, head, count=1)
    if n != 1:
        raise SystemExit("build: could not locate commentable-html-version <meta> to place the layer descriptor")
    return new + tail


def _stamp_content_root_hook(text):
    marker = text.find(_CONTENT_BEGIN_TEXT)
    if marker == -1:
        return text
    match = None
    for m in _CONTENT_ROOT_RE.finditer(text, 0, marker):
        match = m
    if match is None or re.search(r"\sdata-cmh-content-root(?:[\s=>]|$)", match.group(0), re.IGNORECASE):
        return text
    return text[:match.start() + len("<main")] + " data-cmh-content-root" + text[match.start() + len("<main"):]


def regen_example(example_html, portable_html, version, mermaid_version, where="<example>"):
    """Return the example with its CSS/COMMENT UI/JS regions replaced by the current
    layer from portable_html, its <meta> version re-stamped, and its mermaid CDN pin
    rewritten to the single source. The report's content and embedded comments are
    preserved."""
    out = example_html
    for name in _LAYER_REGIONS:
        _region_inner(portable_html, name, "dist/PORTABLE.html")
        _region_inner(out, name, where)
    for name in _EXAMPLE_SWAP_REGIONS:
        tb, te = _region_inner(portable_html, name, "dist/PORTABLE.html")
        db, de = _region_inner(out, name, where)
        out = out[:db] + portable_html[tb:te] + out[de:]
    out, n = _META_VERSION_RE.subn(lambda m: m.group(1) + version + m.group(2), out, count=1)
    if n != 1:
        raise SystemExit("build: %s has no commentable-html-version <meta> to stamp" % where)
    out = _stamp_layer_descriptor(out, version, "portable")
    out = _stamp_content_root_hook(out)
    out = _MERMAID_CDN_RE.sub(lambda m: m.group(1) + mermaid_version + m.group(2), out)
    return out


def build_examples(portable_html, version, mermaid_version, out_dir):
    """Regenerate every examples/report-*.html found under out_dir. Returns {path: text}.
    An absent examples/ directory (e.g. a temp-dir build) yields no entries."""
    examples_dir = os.path.join(out_dir, "examples")
    result = {}
    if not os.path.isdir(examples_dir):
        return result
    for name in sorted(os.listdir(examples_dir)):
        if not _EXAMPLE_NAME_RE.match(name):
            continue
        path = os.path.join(examples_dir, name)
        result[path] = regen_example(read(path), portable_html, version, mermaid_version, name)
    return result


def build_all(assets_dir=None, out_dir=None):
    out_dir = HERE if out_dir is None else out_dir
    dist_dir = os.path.join(out_dir, "dist")
    css, js, shell, version = load_sources(assets_dir)
    mermaid_version = read_mermaid_version()
    js = _stamp_const(js, version, "commentable-html.js")
    css_name, js_name, assets_name = _names()
    assets_js = build_assets_js(css, js, version)
    css_file, js_file = css + "\n", js + "\n"
    manifest = {
        "version": version,
        "files": {
            css_name: {"sha256": sha256(css_file), "bytes": len(css_file.encode("utf-8"))},
            js_name: {"sha256": sha256(js_file), "bytes": len(js_file.encode("utf-8"))},
            assets_name: {"sha256": sha256(assets_js), "bytes": len(assets_js.encode("utf-8"))},
        },
    }
    portable = build_inline(css, js, shell, version, mermaid_version)
    outputs = {
        os.path.join(dist_dir, "PORTABLE.html"): portable,
        os.path.join(dist_dir, css_name): css_file,
        os.path.join(dist_dir, js_name): js_file,
        os.path.join(dist_dir, assets_name): assets_js,
        os.path.join(dist_dir, "manifest.json"): json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        os.path.join(dist_dir, "NONPORTABLE.html"): build_nonportable(shell, version, mermaid_version),
    }
    outputs.update(build_examples(portable, version, mermaid_version, out_dir))
    return outputs, version


# --------------------------------------------------------------------------- #
# Entry
# --------------------------------------------------------------------------- #
def _report(outputs, version, out_dir=None):
    out_dir = HERE if out_dir is None else out_dir
    portable = outputs[os.path.join(out_dir, "dist", "PORTABLE.html")]
    nonportable = outputs[os.path.join(out_dir, "dist", "NONPORTABLE.html")]
    inline_b = len(portable.encode("utf-8"))
    nonportable_b = len(nonportable.encode("utf-8"))
    saved = inline_b - nonportable_b
    pct = (saved / inline_b * 100) if inline_b else 0
    print("commentable-html build - version %s" % version)
    print("  inline  dist/PORTABLE.html : %6d bytes" % inline_b)
    print("  nonportable dist/NONPORTABLE.html  : %6d bytes" % nonportable_b)
    print("  per-regeneration boilerplate avoided in nonportable mode: %d bytes (%.0f%% smaller)"
          % (saved, pct))


def main(argv):
    parser = argparse.ArgumentParser(prog="build.py", description="Build the commentable-html distributable set.")
    parser.add_argument("--check", action="store_true",
                        help="verify the generated files in --out-dir match a fresh build (no writes)")
    parser.add_argument("--assets-dir", default=None,
                        help="directory holding the canonical sources (default: <skill>/assets)")
    parser.add_argument("--out-dir", default=None,
                        help="directory that receives dist/PORTABLE.html and dist/ (default: the skill root)")
    ns = parser.parse_args(argv[1:])
    assets_dir = ASSETS if ns.assets_dir is None else os.path.abspath(ns.assets_dir)
    out_dir = HERE if ns.out_dir is None else os.path.abspath(ns.out_dir)
    dist_dir = os.path.join(out_dir, "dist")
    outputs, version = build_all(assets_dir, out_dir)
    stamps = source_stamps(version, assets_dir, out_dir)
    stamps.update(example_stamps(out_dir, read_mermaid_version()))
    stale = _unexpected_dist_files(outputs.keys(), dist_dir)
    legacy = [p for p in _legacy_generated_files(out_dir) if os.path.exists(p)]
    if ns.check:
        drift = []
        for path, text in list(outputs.items()) + list(stamps.items()):
            rel = os.path.relpath(path, out_dir)
            if not os.path.exists(path):
                drift.append(rel + " (missing)")
            elif _lf(read(path)) != _lf(text):
                drift.append(rel + " (out of date)")
        for name in stale:
            drift.append(os.path.join("dist", name) + " (stale - not produced by the current build; delete it)")
        for path in legacy:
            drift.append(os.path.relpath(path, out_dir) + " (legacy generated file - delete it)")
        if drift:
            sys.stderr.write("build --check FAILED; run `python tools/build.py`:\n")
            for d in drift:
                sys.stderr.write("  - " + d + "\n")
            return 1
        print("build --check OK (%d generated files in sync, version %s)" % (len(outputs), version))
        return 0
    for name in stale:
        os.remove(os.path.join(dist_dir, name))
    for path in legacy:
        os.remove(path)
    for path, text in outputs.items():
        write(path, text)
    for path, text in stamps.items():
        write(path, text)
    if stale:
        print("removed %d stale dist file(s): %s" % (len(stale), ", ".join(stale)))
    _report(outputs, version, out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
