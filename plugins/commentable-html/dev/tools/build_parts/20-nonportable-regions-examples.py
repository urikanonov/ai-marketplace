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
    Mirrors tools/authoring/upgrade.py so example regeneration and end-user upgrades agree."""
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
