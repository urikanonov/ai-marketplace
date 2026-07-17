_PART_RE = {"js": re.compile(r"^\d{2}-[a-z0-9-]+\.js$"), "css": re.compile(r"^\d{2}-[a-z0-9-]+\.css$")}


def ordered_parts(assets_dir, ext):
    """Return the absolute paths of the `NN-topic.<ext>` partials under assets_dir/<ext>/, in
    directory-sorted (load-bearing) order. Rejects a stray unnumbered file so a partial cannot be
    silently dropped from or misordered in the bundle."""
    d = os.path.join(assets_dir, ext)
    if not os.path.isdir(d):
        raise SystemExit("commentable-html source directory missing: %s "
                         "(sources live under assets/js/ and assets/css/)" % d)
    names = [n for n in os.listdir(d) if os.path.isfile(os.path.join(d, n)) and n.lower().endswith("." + ext)]
    stray = [n for n in names if not _PART_RE[ext].match(n)]
    if stray:
        raise SystemExit("%s/ holds .%s files that are not `NN-topic.%s` partials: %s "
                         "(rename to the numbered convention or remove them)"
                         % (d, ext, ext, ", ".join(sorted(stray))))
    if not names:
        raise SystemExit("no %s partials found under %s" % (ext, d))
    return [os.path.join(d, n) for n in sorted(names)]


def _concat_parts(assets_dir, ext):
    # Concatenate the exact partial bytes; rstrip the FINAL newline ONCE on the whole aggregate
    # (the old monolith read did `.rstrip("\n")`) - never per partial, or a boundary would gain a
    # byte and break byte-identity.
    return "".join(read(p) for p in ordered_parts(assets_dir, ext))


def _js_version_part(assets_dir):
    """The single JS partial that declares `const CMH_VERSION = "..."` (build.py stamps it from
    dev/VERSION). Located by the SAME strict declaration regex build.py stamps with, so a mere
    mention of CMH_VERSION in a comment or string cannot be mistaken for the declaration."""
    for p in ordered_parts(assets_dir, "js"):
        if _CMH_CONST_RE.search(read(p)):
            return p
    raise SystemExit("no assets/js/ partial declares CMH_VERSION")


def load_sources(assets_dir=None):
    assets_dir = ASSETS if assets_dir is None else assets_dir
    css = _concat_parts(assets_dir, "css").rstrip("\n")
    js = _concat_parts(assets_dir, "js").rstrip("\n")
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
def build_vendored_rich_libs_json(assets_dir):
    vendor_dir = os.path.join(assets_dir, "vendor")
    mermaid = read_vendor_script(os.path.join(vendor_dir, "mermaid.min.js")).encode("utf-8")
    chartjs = read_vendor_script(os.path.join(vendor_dir, "chart.umd.min.js")).encode("utf-8")
    payload = {
        "encoding": "gzip+base64",
        "mermaidGzipBase64": base64.b64encode(deterministic_gzip(mermaid, compresslevel=9)).decode("ascii"),
        "chartjsGzipBase64": base64.b64encode(deterministic_gzip(chartjs, compresslevel=9)).decode("ascii"),
    }
    return (json.dumps(payload, separators=(",", ":"))
            .replace("<", "\\u003C")
            .replace(">", "\\u003E")
            .replace("&", "\\u0026"))


def build_inline(css, js, shell, version, mermaid_version, vendored_rich_libs_json=None):
    if vendored_rich_libs_json is None:
        vendored_rich_libs_json = build_vendored_rich_libs_json(ASSETS)
    for ph in ("{{CMH_CSS}}", "{{CMH_JS}}", "{{CMH_VERSION}}", "{{MERMAID_VERSION}}", "{{CMH_VENDORED_RICH_LIBS}}"):
        if ph not in shell:
            raise SystemExit("build: shell is missing placeholder " + ph)
    return (shell.replace("{{CMH_CSS}}", css)
                 .replace("{{CMH_JS}}", js)
                 .replace("{{CMH_VERSION}}", version)
                 .replace("{{MERMAID_VERSION}}", mermaid_version)
                 .replace("{{CMH_VENDORED_RICH_LIBS}}", vendored_rich_libs_json))


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
