_CSS_REGION_RE = re.compile(
    r"/\*[^\n]*\n\s*BEGIN: commentable-html - CSS.*?END: commentable-html - CSS[^*]*\*/",
    re.S)
_JS_REGION_RE = re.compile(
    r"<!--[^\n]*\n\s*BEGIN: commentable-html - JS.*?<!-- END: commentable-html - JS -->",
    re.S)
# The fence that separates the authored content from the generated machinery (CMH-SIZE-05).
MACHINERY_BEGIN = "BEGIN: commentable-html - MACHINERY"

_BOOTSTRAP = (
    "<!-- BEGIN: commentable-html - NONSHAREABLE BOOTSTRAP -->\n"
    # The banner reports that the companion files are MISSING, and its own `position: fixed`
    # styling lives in that very stylesheet - so in the failure mode it exists for it would render
    # as an unstyled block, and (since CMH-SIZE-05 puts it in the machinery fence) one the reader
    # only meets after scrolling past the whole document. The inline style makes it
    # self-sufficient: it pins itself to the top of the viewport with no stylesheet at all.
    '<div id="cmhAssetBanner" class="cm-skip" role="alert" hidden'
    ' style="position:fixed;top:0;left:0;right:0;z-index:400;display:flex;align-items:center;'
    'justify-content:center;gap:12px;padding:10px 16px;font:13px/1.4 system-ui,sans-serif;'
    'background:#dc2626;color:#fff;text-align:center">\n'
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
    "<!-- END: commentable-html - NONSHAREABLE BOOTSTRAP -->\n"
)


def build_nonshareable(shell, version, mermaid_version, vendored_rich_libs_json=None):
    if vendored_rich_libs_json is None:
        vendored_rich_libs_json = build_vendored_rich_libs_json(ASSETS)
    css_name, js_name, assets_name = _names()
    t = shell

    # 1) Remove the inline layer-CSS region from inside <style>; link it instead. Both live in the
    #    MACHINERY fence after the authored content (CMH-SIZE-05), so the <link> is placed right
    #    after the <style> that carried the region rather than at the end of <head>. A pending
    #    stylesheet blocks the scripts that follow it, so the reveal script just below still runs
    #    only once the companion CSS has loaded.
    if not _CSS_REGION_RE.search(t):
        raise SystemExit("build: could not locate the CSS region in the shell")
    t = _CSS_REGION_RE.sub("", t, count=1)
    css_link = ("<!-- ============================================================\n"
                "     BEGIN: commentable-html - CSS\n"
                "     ============================================================ -->\n"
                '<link rel="stylesheet" href="' + css_name + '">\n'
                "<!-- END: commentable-html - CSS -->\n")
    fence = t.find(MACHINERY_BEGIN)
    if fence == -1:
        raise SystemExit("build: could not locate the MACHINERY fence in the shell")
    style_close = t.find("</style>\n", fence)
    if style_close == -1:
        raise SystemExit("build: could not locate the </style> after the shell's MACHINERY fence")
    cut = style_close + len("</style>\n")
    t = t[:cut] + css_link + t[cut:]

    # 2) Replace the inline JS region with external <script src> companions.
    js_add = ("<!-- ============================================================\n"
              "     BEGIN: commentable-html - JS\n"
              "     ============================================================ -->\n"
              "<!-- commentable-html - layer loaded from companion files (nonshareable mode) -->\n"
              '<script src="' + assets_name + '"></script>\n'
              '<script src="' + js_name + '"></script>\n'
              "<!-- END: commentable-html - JS -->")
    if not _JS_REGION_RE.search(t):
        raise SystemExit("build: could not locate the JS region in the shell")
    t = _JS_REGION_RE.sub(lambda _m: js_add, t)

    # 3) Inject the missing-asset banner + bootstrap at the top of the MACHINERY fence, so the
    #    authored content still comes first in source order (CMH-SIZE-05). The banner is
    #    `position: fixed` and starts hidden, so its DOM position changes nothing on screen.
    fence = t.find(MACHINERY_BEGIN)
    if fence == -1:
        raise SystemExit("build: could not locate the MACHINERY fence in the shell")
    lead_end = t.find("-->\n", fence)
    if lead_end == -1:
        raise SystemExit("build: could not locate the end of the shell's MACHINERY fence comment")
    idx = lead_end + len("-->\n")
    boot = (_BOOTSTRAP.replace("__JSNAME__", js_name)
            .replace("__ASSETSNAME__", assets_name)
            .replace("__CSSNAME__", css_name))
    t = t[:idx] + "\n" + boot + t[idx:]

    # 4) Per-document identity so the nonshareable demo does not collide with the
    #    inline demo in localStorage, and is clearly labelled.
    t = t.replace('data-comment-key="commentable-html-demo"',
                  'data-comment-key="commentable-html-nonshareable-demo"', 1)
    t = t.replace('data-doc-source="SHAREABLE.html"', 'data-doc-source="NONSHAREABLE.html"', 1)
    t = t.replace("<title>Commentable HTML - Demo</title>",
                  "<title>Commentable HTML - NonShareable Demo</title>", 1)
    t = _stamp_layer_descriptor(t, version, "nonshareable")

    t = re.sub(r"\n{3,}", "\n\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    t = t.replace("{{CMH_VERSION}}", version)
    t = t.replace("{{MERMAID_VERSION}}", mermaid_version)
    t = t.replace("{{CMH_VENDORED_RICH_LIBS}}", vendored_rich_libs_json)
    if "{{CMH_" in t or "{{MERMAID_" in t:
        raise SystemExit("build: an unresolved placeholder remains in NONSHAREABLE.html")
    return t


class _MarkerMatch:
    def __init__(self, marker_start, marker_end):
        self._marker_start = marker_start
        self._marker_end = marker_end

    # Group 0 and group 1 are DELIBERATELY the same span: the only group this match carries is
    # the marker itself. Any other group is refused rather than answered with a plausible wrong
    # offset, so a caller written against a real re.Match fails loudly instead of silently
    # slicing the wrong text.
    def _check_group(self, group):
        if group not in (0, 1):
            raise IndexError("no such group")

    def start(self, group=0):
        self._check_group(group)
        return self._marker_start

    def end(self, group=0):
        self._check_group(group)
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
    # Lines break on "\n" ONLY, the way the runtime - and the browser that opens the document -
    # sees them. str.splitlines() also breaks on \x0b \x0c \x1c \x1d \x1e \x85 \u2028 \u2029 and
    # treats a lone \r as a terminator, so a marker "line" that exists only after one of those
    # splits would be counted here and ignored by the runtime that reads the file back - two
    # views disagreeing about which comment IS the boundary (CMH-VAL-22).
    lines = (text or "").split("\n")
    last = len(lines) - 1
    for i, line in enumerate(lines):
        body = line[:-1] if (i < last and line.endswith("\r")) else line
        m = inline.match(body)
        if m is None and state in ("html", "css"):
            m = bare.match(body)
        if m is not None:
            matches.append(_MarkerMatch(offset + m.start(1), offset + m.end(1)))
        state = _advance_comment_state(body, state)
        offset += len(line) + (1 if i < last else 0)
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
