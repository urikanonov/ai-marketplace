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
_VENDORED_RICH_LIBS_RE = re.compile(
    r'<script\b[^>]*\sid\s*=\s*(["\'])cmhVendoredRichLibs\1[^>]*>[\s\S]*?</script>\s*',
    re.IGNORECASE)
_LAYER_DESCRIPTOR_INSERT_RE = re.compile(
    r'(<meta name="commentable-html-version" content="[0-9]+\.[0-9]+\.[0-9]+" />?\s*)',
    re.IGNORECASE)
_CONTENT_BEGIN_TEXT = "BEGIN: commentable-html - CONTENT"
_CONTENT_ROOT_RE = re.compile(r'<main\b[^>]*?\bid\s*=\s*(["\'])commentRoot\1[^>]*>', re.IGNORECASE)
# The mermaid loader block (the "<!-- Mermaid loader ... -->" comment plus its lone
# <script type="module">) baked into the head. regen_example re-emits the CANONICAL loader from
# PORTABLE.html so an example never keeps a stale/naive loader (issue #520): the canonical loader
# serializes renders (mermaid shares internal state, so rendering many diagrams at once corrupts
# them) and renders a hidden diagram off-screen instead of in place (a zero-size box). The loader is
# located the same head-scoped, import-based way as tools/authoring/upgrade.py (CMH-MMD-09) - by a
# <head> module <script> that boots mermaid via a dynamic `import("...mermaid...")`, NOT by an exact
# comment/attribute spelling - so a template reword can never silently no-op the swap, and an authored
# module <script> in the body can never be mistaken for the loader.
_HEAD_RE = re.compile(r"<head\b[^>]*>.*?</head>", re.IGNORECASE | re.DOTALL)
_MODULE_SCRIPT_RE = re.compile(
    r'<script\b[^>]*\btype=(["\'])module\1[^>]*>(.*?)</script>', re.IGNORECASE | re.DOTALL)
_MERMAID_LOADER_COMMENT_RE = re.compile(
    r'[ \t]*<!--\s*Mermaid loader\b.*?-->[ \t]*\r?\n?', re.IGNORECASE | re.DOTALL)
# A dynamic mermaid `import("...mermaid...")`, keyed on "mermaid" INSIDE the string literal so a
# script that only mentions mermaid in a comment is not mistaken for the loader.
_MERMAID_IMPORT_RE = re.compile(
    r'import\(\s*(["\'])([^"\']*mermaid[^"\']*)\1', re.IGNORECASE | re.DOTALL)
# A remote specifier: scheme-bearing (`https://`) or protocol-relative (`//host/...`). Anything else
# (`./x`, `../x`, `/x`, bare) is a locally vendored path.
_URL_SCHEME_RE = re.compile(r'[a-z][a-z0-9+.-]*://', re.IGNORECASE)
# A rendered mermaid host (`<pre class="mermaid ...">` / `<div class="mermaid ...">`). Used to fail
# closed: a diagram-bearing example with no head loader would silently ship diagrams that never
# render, so the build must reject it rather than skip the swap. `mermaid` must be a whole class
# TOKEN (delimited by whitespace or the quote), so a highlighted `class="language-mermaid"` CODE
# sample - which is not a diagram host - is not matched (a `-` is a word boundary, so a plain
# `\bmermaid\b` would wrongly match it).
_MERMAID_HOST_RE = re.compile(
    r'<(?:pre|div)\b[^>]*\bclass\s*=\s*(["\'])[^"\']*(?<![\w-])mermaid(?![\w-])', re.IGNORECASE)


def _preceding_loader_comment(scope, start):
    """The `<!-- Mermaid loader -->` comment immediately preceding offset `start` in `scope` (only
    whitespace between the comment and `start`), or None."""
    comment = None
    for c in _MERMAID_LOADER_COMMENT_RE.finditer(scope[:start]):
        comment = c  # keep the last (nearest-preceding) match
    if comment is not None and scope[comment.end():start].strip() == "":
        return comment
    return None


def _mermaid_bootstrap_span(html, where):
    """Return (start, end) offsets of the shell-baked mermaid loader block - the module <script> in
    <head> that boots mermaid (a dynamic mermaid `import("...mermaid...")`), plus an immediately-
    preceding "Mermaid loader" comment - or None when the head has no such loader. Scoped to <head>
    so an authored module <script> in the body/CONTENT can never be mistaken for the loader. If more
    than one head module script imports mermaid, the one bound to the "Mermaid loader" comment wins;
    if still ambiguous, raise (fail closed)."""
    html = html or ""
    head = _HEAD_RE.search(html)
    if head is None:
        return None
    scope = head.group(0)
    base = head.start()
    candidates = [m for m in _MODULE_SCRIPT_RE.finditer(scope) if _MERMAID_IMPORT_RE.search(m.group(2))]
    if not candidates:
        return None
    if len(candidates) > 1:
        commented = [m for m in candidates if _preceding_loader_comment(scope, m.start())]
        if len(commented) != 1:
            raise SystemExit("build: %s has multiple mermaid loader scripts in <head>" % where)
        candidates = commented
    script = candidates[0]
    start, end = script.start(), script.end()
    comment = _preceding_loader_comment(scope, start)
    if comment is not None:
        start = comment.start()
    return base + start, base + end


def _mermaid_loader_is_vendored(loader):
    """True if the loader imports mermaid from a LOCAL/relative path rather than a remote URL - a
    hand-vendored offline artifact (the SKILL.md vendoring recipe). regen_example must NOT clobber
    that back to the CDN, which would silently reintroduce a network fetch the author removed."""
    for m in _MERMAID_IMPORT_RE.finditer(loader or ""):
        spec = m.group(2).strip()
        if not (_URL_SCHEME_RE.match(spec) or spec.startswith("//")):
            return True
    return False


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


def _vendored_rich_libs_script(portable_html):
    m = _VENDORED_RICH_LIBS_RE.search(portable_html)
    if not m:
        raise SystemExit("build: could not locate the vendored rich-content script in dist/PORTABLE.html")
    return m.group(0) if m.group(0).endswith("\n") else m.group(0) + "\n"


def _stamp_vendored_rich_libs(text, portable_html):
    script = _vendored_rich_libs_script(portable_html)
    head_end = text.lower().find("</head>")
    if head_end == -1:
        raise SystemExit("build: could not locate </head> to place the vendored rich-content script")
    head, tail = text[:head_end], text[head_end:]
    if _VENDORED_RICH_LIBS_RE.search(head):
        return _VENDORED_RICH_LIBS_RE.sub(script, head, count=1) + tail
    new, n = _LAYER_DESCRIPTOR_INSERT_RE.subn(lambda m: m.group(1) + script, head, count=1)
    if n != 1:
        raise SystemExit("build: could not locate commentable-html-version <meta> to place the vendored rich-content script")
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
    # Re-emit the canonical mermaid loader from PORTABLE.html so an example never ships a stale or
    # naive loader (issue #520). Located head-scoped by its mermaid import (see _mermaid_bootstrap_span)
    # so a comment/attribute reword cannot silently no-op the swap. NEVER clobber a hand-vendored
    # offline loader (relative import) back to the CDN. Fail closed: an example with mermaid diagrams
    # but no head loader (or a PORTABLE with none) raises rather than silently shipping a broken doc; a
    # genuinely diagram-free example simply has no loader and no host, so nothing is swapped.
    ex_span = _mermaid_bootstrap_span(out, where)
    if ex_span is None:
        if _MERMAID_HOST_RE.search(out):
            raise SystemExit("build: %s has mermaid diagrams but no head mermaid loader" % where)
    elif not _mermaid_loader_is_vendored(out[ex_span[0]:ex_span[1]]):
        port_span = _mermaid_bootstrap_span(portable_html, "dist/PORTABLE.html")
        if port_span is None:
            raise SystemExit("build: dist/PORTABLE.html has no mermaid loader to re-emit into %s" % where)
        out = out[:ex_span[0]] + portable_html[port_span[0]:port_span[1]] + out[ex_span[1]:]
    out, n = _META_VERSION_RE.subn(lambda m: m.group(1) + version + m.group(2), out, count=1)
    if n != 1:
        raise SystemExit("build: %s has no commentable-html-version <meta> to stamp" % where)
    out = _stamp_vendored_rich_libs(out, portable_html)
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
    vendored_rich_libs_json = build_vendored_rich_libs_json(assets_dir or ASSETS)
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
    portable = build_inline(css, js, shell, version, mermaid_version, vendored_rich_libs_json)
    outputs = {
        os.path.join(dist_dir, "PORTABLE.html"): portable,
        os.path.join(dist_dir, css_name): css_file,
        os.path.join(dist_dir, js_name): js_file,
        os.path.join(dist_dir, assets_name): assets_js,
        os.path.join(dist_dir, "manifest.json"): json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        os.path.join(dist_dir, "NONPORTABLE.html"): build_nonportable(shell, version, mermaid_version, vendored_rich_libs_json),
    }
    outputs.update(build_examples(portable, version, mermaid_version, examples_dir))
    outputs.update(build_prompt_examples(examples_dir))
    return outputs, version
