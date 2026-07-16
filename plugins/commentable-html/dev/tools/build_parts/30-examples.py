_LAYER_REGIONS = ("CSS", "HANDLED IDS", "EMBEDDED COMMENTS", "COMMENT UI", "JS")
_EXAMPLE_SWAP_REGIONS = ("CSS", "COMMENT UI", "JS")
_EXAMPLE_NAME_RE = re.compile(r"^(?:report|deck)-.*\.html$")
# A shipped one-shot authoring prompt (examples/prompt-*.md) is plain Markdown with no layer,
# version, or mermaid pin to stamp, so its dev/examples/src source is copied VERBATIM to the
# shipped file. Assembling from an independent source is what lets --check catch a stale or
# hand-edited shipped prompt instead of comparing it to itself.
_PROMPT_NAME_RE = re.compile(r"^prompt-.*\.md$")
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


def build_examples(portable_html, version, mermaid_version, examples_dir):
    """Regenerate every report-*.html and deck-*.html under examples_dir from its INDEPENDENT
    content source in dev/examples/src/ (not from the shipped file itself). Returns {out_path: text}.
    An absent examples_dir (e.g. a temp-dir build) or an absent source dir yields no entries.
    Assembling from an independent source is what lets --check catch a stale or hand-edited example
    instead of comparing it to itself."""
    result = {}
    if not os.path.isdir(examples_dir) or not os.path.isdir(EXAMPLES_SRC):
        return result
    for name in sorted(os.listdir(EXAMPLES_SRC)):
        if not _EXAMPLE_NAME_RE.match(name):
            continue
        src_path = os.path.join(EXAMPLES_SRC, name)
        out_path = os.path.join(examples_dir, name)
        result[out_path] = regen_example(read(src_path), portable_html, version, mermaid_version, name)
    return result


def build_prompt_examples(examples_dir):
    """Copy every dev/examples/src/prompt-*.md VERBATIM to examples_dir/<same-name>.md.
    A one-shot prompt is plain Markdown with no layer/version/mermaid to stamp, so its 'assembly'
    is a byte copy from its independent source; --check then catches a stale or hand-edited
    prompt. Only prompts that HAVE a source are written, so hand-maintained prompts without one are
    left untouched. Returns {out_path: text}; an absent examples or source dir yields no entries."""
    result = {}
    if not os.path.isdir(examples_dir) or not os.path.isdir(EXAMPLES_SRC):
        return result
    for name in sorted(os.listdir(EXAMPLES_SRC)):
        if not _PROMPT_NAME_RE.match(name):
            continue
        src_path = os.path.join(EXAMPLES_SRC, name)
        out_path = os.path.join(examples_dir, name)
        result[out_path] = read(src_path)
    return result


def _orphan_examples(examples_dir):
    """report-*.html or deck-*.html under examples_dir that have NO dev/examples/src source.
    build_examples only assembles examples that have a source, so an orphan would otherwise be a
    pure artifact validated against nothing (the exact self-sourced hole this split closed). --check
    reports it so it cannot drift undetected; the fix is to add its source or delete it."""
    if not os.path.isdir(examples_dir) or not os.path.isdir(EXAMPLES_SRC):
        return []
    sources = set(os.listdir(EXAMPLES_SRC))
    return [name for name in sorted(os.listdir(examples_dir))
            if _EXAMPLE_NAME_RE.match(name) and name not in sources]


def build_all(assets_dir=None, out_dir=None, examples_dir=None):
    out_dir = HERE if out_dir is None else out_dir
    examples_dir = os.path.join(out_dir, "examples") if examples_dir is None else examples_dir
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
    outputs.update(build_examples(portable, version, mermaid_version, examples_dir))
    outputs.update(build_prompt_examples(examples_dir))
    return outputs, version
