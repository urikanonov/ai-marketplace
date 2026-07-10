#!/usr/bin/env python3
"""Build the commentable-html distributable set from the canonical sources.

Single source of truth
----------------------
  assets/commentable-html.css   - the layer CSS (region body)
  assets/commentable-html.js    - the runtime JS (region body); the CMH_VERSION
                                  constant in here is the ONE place the version
                                  is defined.
  assets/template.shell.html    - the page shell with {{CMH_CSS}} / {{CMH_JS}}
                                  placeholders and the demo content.

Generated (never hand-edit; `--check` fails if they drift)
----------------------------------------------------------
  dist/PORTABLE.html                       - inline / standalone template (self-contained)
  dist/commentable-html.v<V>.css      - external layer stylesheet
  dist/commentable-html.v<V>.js       - external runtime
  dist/commentable-html.v<V>.assets.js- asset registry (css+js as strings) used by
                                        "Export standalone" to rebuild a portable file
  dist/manifest.json                  - version + sha256 of each companion file
  dist/NONPORTABLE.html                   - nonportable template, sitting next to its companions

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
# Sources + version
# --------------------------------------------------------------------------- #
def load_sources(assets_dir=None):
    assets_dir = ASSETS if assets_dir is None else assets_dir
    css = read(os.path.join(assets_dir, "commentable-html.css")).rstrip("\n")
    js = read(os.path.join(assets_dir, "commentable-html.js")).rstrip("\n")
    shell = read(os.path.join(assets_dir, "template.shell.html"))
    # Anchor to a real top-level declaration line and require exactly one, so a
    # commented-out or string occurrence elsewhere cannot be picked up.
    matches = re.findall(r'(?m)^\s*const\s+CMH_VERSION\s*=\s*"([0-9]+\.[0-9]+\.[0-9]+)"\s*;', js)
    if len(matches) != 1:
        raise SystemExit("build: expected exactly one CMH_VERSION declaration in assets/commentable-html.js, found %d" % len(matches))
    return css, js, shell, matches[0]


def _unexpected_dist_files(expected_paths, dist_dir=None):
    """Versioned dist companions present on disk but NOT in the freshly built set -
    i.e. stale artifacts left behind by an earlier version."""
    dist_dir = DIST if dist_dir is None else dist_dir
    if not os.path.isdir(dist_dir):
        return []
    expected = {os.path.normcase(os.path.abspath(p)) for p in expected_paths}
    stale = []
    for name in os.listdir(dist_dir):
        if re.match(r"commentable-html\.v[0-9.]+\.(css|js|assets\.js)$", name):
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


def _names(version):
    base = "commentable-html.v" + version
    return base + ".css", base + ".js", base + ".assets.js"


# --------------------------------------------------------------------------- #
# Output builders
# --------------------------------------------------------------------------- #
def build_inline(css, js, shell):
    if "{{CMH_CSS}}" not in shell or "{{CMH_JS}}" not in shell:
        raise SystemExit("build: shell is missing a placeholder")
    return shell.replace("{{CMH_CSS}}", css).replace("{{CMH_JS}}", js)


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
    r"/\*[^\n]*\n\s*BEGIN: commentable-html v2 - CSS.*?END: commentable-html v2 - CSS[^*]*\*/",
    re.S)
_JS_REGION_RE = re.compile(
    r"<!--[^\n]*\n\s*BEGIN: commentable-html v2 - JS.*?<!-- END: commentable-html v2 - JS -->",
    re.S)

_BOOTSTRAP = (
    "<!-- BEGIN: commentable-html v2 - NONPORTABLE BOOTSTRAP -->\n"
    '<div id="cmhAssetBanner" class="cm-skip" role="alert" hidden>\n'
    "  Commentable-html could not load its companion files. Keep\n"
    "  <code>__JSNAME__</code>, <code>__ASSETSNAME__</code> and <code>__CSSNAME__</code>\n"
    "  in the same folder as this HTML, or open the standalone copy instead.\n"
    "</div>\n"
    "<script>\n"
    "  window.setTimeout(function () {\n"
    "    if (!window.__commentableHtmlReady) {\n"
    '      var b = document.getElementById("cmhAssetBanner");\n'
    "      if (b) b.hidden = false;\n"
    "    }\n"
    "  }, 3000);\n"
    "</scr" + "ipt>\n"
    "<!-- END: commentable-html v2 - NONPORTABLE BOOTSTRAP -->\n"
)


def build_nonportable(shell, version):
    css_name, js_name, assets_name = _names(version)
    t = shell

    # 1) Remove the inline layer-CSS region from inside <style>; link it instead.
    if not _CSS_REGION_RE.search(t):
        raise SystemExit("build: could not locate the CSS region in the shell")
    t = _CSS_REGION_RE.sub("", t)
    head_add = ('<link rel="stylesheet" href="' + css_name + '">\n'
                '<meta name="commentable-html-assets" content="' + version + '">\n')
    if "</style>\n</head>" not in t:
        raise SystemExit("build: could not locate </style></head> in the shell")
    t = t.replace("</style>\n</head>", "</style>\n" + head_add + "</head>", 1)

    # 2) Replace the inline JS region with external <script src> companions.
    js_add = ("<!-- commentable-html v2 - layer loaded from companion files (nonportable mode) -->\n"
              '<script src="' + assets_name + '"></script>\n'
              '<script src="' + js_name + '"></script>\n'
              "<!-- END: commentable-html v2 - JS -->")
    if not _JS_REGION_RE.search(t):
        raise SystemExit("build: could not locate the JS region in the shell")
    t = _JS_REGION_RE.sub(lambda _m: js_add, t)

    # 3) Inject the missing-asset banner + bootstrap right after the real body
    #    tag. Anchor after </head> so the "<body>" mentioned in the top-of-file
    #    documentation comment is never matched.
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
    t = t.replace('data-comment-key="commentable-html-demo-v1"',
                  'data-comment-key="commentable-html-nonportable-demo-v1"', 1)
    t = t.replace('data-doc-source="PORTABLE.html"', 'data-doc-source="NONPORTABLE.html"', 1)
    t = t.replace("<title>Commentable HTML - Demo</title>",
                  "<title>Commentable HTML - NonPortable Demo</title>", 1)

    # 5) Clarify in the header comment that this is the nonportable build (CSS/JS load
    #    from companion files), so the inline "five regions" description below is not
    #    misleading to someone starting from NONPORTABLE.html.
    t = t.replace(
        "This file is a fully working demo of the commentable-html skill.\n"
        "  Open it in a browser to confirm the behavior, then copy the\n"
        "  five marker-delimited regions below into your own HTML.",
        "This file is the NONPORTABLE build of the commentable-html demo: the CSS and JS\n"
        "  load from companion files (see the <link> / <script src> references), NOT\n"
        "  from inline regions. Open it in a browser (with the companion files\n"
        "  alongside) to confirm the behavior. The numbered region list below\n"
        "  describes the inline dist/PORTABLE.html; in nonportable mode you copy only the\n"
        "  in-body regions (HANDLED IDS, EMBEDDED COMMENTS, COMMENT UI) and keep the\n"
        "  companion <link> / <script> references.",
        1)

    t = re.sub(r"\n{3,}", "\n\n", t)
    if "{{CMH_" in t:
        raise SystemExit("build: an unresolved placeholder remains in NONPORTABLE.html")
    return t


def build_all(assets_dir=None, out_dir=None):
    assets_dir = ASSETS if assets_dir is None else assets_dir
    out_dir = HERE if out_dir is None else out_dir
    dist_dir = os.path.join(out_dir, "dist")
    css, js, shell, version = load_sources(assets_dir)
    css_name, js_name, assets_name = _names(version)
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
    return {
        os.path.join(dist_dir, "PORTABLE.html"): build_inline(css, js, shell),
        os.path.join(dist_dir, css_name): css_file,
        os.path.join(dist_dir, js_name): js_file,
        os.path.join(dist_dir, assets_name): assets_js,
        os.path.join(dist_dir, "manifest.json"): json.dumps(manifest, indent=2) + "\n",
        os.path.join(dist_dir, "NONPORTABLE.html"): build_nonportable(shell, version),
    }, version


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
    stale = _unexpected_dist_files(outputs.keys(), dist_dir)
    legacy = [p for p in _legacy_generated_files(out_dir) if os.path.exists(p)]
    if ns.check:
        drift = []
        for path, text in outputs.items():
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
    if stale:
        print("removed %d stale dist file(s): %s" % (len(stale), ", ".join(stale)))
    _report(outputs, version, out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
