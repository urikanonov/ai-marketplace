def write_or_check(path, content, check):
    """Write `content` (normalized to LF) to `path`, or in check mode return a one-item drift list
    when the committed file differs. Mirrors the demo/tutorial-image sync so a stale generated file
    fails `--check`."""
    data = content.replace("\r\n", "\n").replace("\r", "\n")
    if check:
        existing = _read_normalized(path).decode("utf-8") if os.path.exists(path) else None
        return [os.path.basename(path)] if existing != data else []
    write_text(path, data)
    return []


def render_demo_fullscreen_link():
    return (
        '<a class="demo-fs" id="demo-fullscreen" href="demo/report-taxi.html" '
        'target="_blank" rel="noopener noreferrer" '
        'aria-label="Open this demo full screen in a new tab" '
        'title="Open this demo in a full browser tab">Full screen &#8599;</a>'
    )


def clean_entry(text, plugin):
    stripped = text
    if plugin:
        stripped = re.sub(r"^`?%s`?(\s+v?\d+\.\d+\.\d+)?\s*[-:]\s*" % re.escape(plugin), "",
                          stripped, flags=re.IGNORECASE)
    return stripped.strip()


def mentions_plugin(text, plugin):
    """True when a changelog bullet is about `plugin`: after stripping leading Markdown
    emphasis/link/code punctuation, the text starts with the plugin name (case-insensitive).
    Anchoring to the start avoids over-matching a bullet that only mentions it mid-sentence."""
    cleaned = re.sub(r"^[\[\*_`\s]+", "", text or "")
    return cleaned.lower().startswith(plugin.lower())


def changelog_candidates(root, explicit):
    """The per-plugin CHANGELOG.md is the single source of truth for a plugin page's
    changelog (the marketplace has no aggregate changelog, and it is also the file the
    version+changelog-sync CI check enforces). An explicit --changelog path overrides it
    and is read in the same per-plugin format (no plugin-name filtering)."""
    if explicit:
        return [(explicit, None)]
    return [(os.path.join(root, "plugins", CHANGELOG_PLUGIN, "CHANGELOG.md"), None)]


def parse_changelog(text, plugin):
    releases = []
    current_release = None
    current_type = None
    buffer = None

    def flush():
        nonlocal buffer
        if buffer is not None and current_release is not None:
            group = current_type if current_type is not None else ""
            if plugin is None or mentions_plugin(buffer, plugin):
                current_release["groups"].setdefault(group, []).append(
                    clean_entry(buffer, plugin))
        buffer = None

    for raw in text.split("\n"):
        line = raw.rstrip()
        release_match = re.match(r"^##\s+(.*)$", line)
        type_match = re.match(r"^###\s+(.*)$", line)
        bullet_match = re.match(r"^[-*]\s+(.*)$", line)
        if release_match:
            flush()
            current_release = {"name": release_match.group(1).strip(), "groups": {}}
            releases.append(current_release)
            current_type = None
        elif type_match:
            flush()
            current_type = type_match.group(1).strip()
        elif bullet_match:
            flush()
            buffer = bullet_match.group(1).strip()
        elif line.strip() == "":
            flush()
        elif buffer is not None:
            buffer += " " + line.strip()
    flush()
    return [r for r in releases if r["groups"]]


def _render_release(release):
    parts = ['<div class="release">',
             '  <div class="rel-head"><h3>%s</h3></div>' % esc(release["name"])]
    for change_type, items in release["groups"].items():
        if change_type:
            parts.append('  <div class="group-label">%s</div>' % esc(change_type))
        parts.append('  <ul>')
        for item in items:
            parts.append('    <li>%s</li>' % _md_inline(esc(item)))
        parts.append('  </ul>')
    parts.append('</div>')
    return "\n".join(parts)


def render_changelog(releases, expanded_count=2, older_count=5, github_url=None):
    """Show the latest `expanded_count` releases (counted in number of releases, default
    2) inline; fold the next `older_count` releases (default 5) into a single <details>
    that stays collapsed by default so the page stays short. Any releases beyond that are
    not rendered - a link to the full changelog in source is shown instead, so the page
    never grows without bound."""
    if github_url is None:
        github_url = CHANGELOG_GITHUB_URL
    if not releases:
        return ('<p class="empty">No changelog entries yet. '
                'See the full marketplace changelog on GitHub.</p>')
    blocks = [_render_release(release) for release in releases[:expanded_count]]
    older = releases[expanded_count:expanded_count + older_count]
    remaining = len(releases) - expanded_count - len(older)
    if older:
        count = len(older)
        summary = "Show %d older release%s" % (count, "" if count == 1 else "s")
        details = ['<details class="older-releases">',
                   '  <summary>%s</summary>' % esc(summary)]
        details.extend(_render_release(release) for release in older)
        if remaining > 0:
            details.append(
                '  <p class="changelog-more">{n} earlier release{s} in the '
                '<a href="{url}">full changelog on GitHub</a>.</p>'.format(
                    n=remaining, s="" if remaining == 1 else "s", url=esc(github_url)))
        details.append('</details>')
        blocks.append("\n".join(details))
    return "\n".join(blocks)


def plugin_changelog_github_url(plugin_name):
    return ("https://github.com/urikanonov/ai-marketplace/blob/main/plugins/"
            + plugin_name + "/CHANGELOG.md")


def render_plugin_changelog(root, plugin_name):
    """Render a plugin's CHANGELOG.md (at plugins/<plugin>/CHANGELOG.md) into the page changelog HTML,
    folding older releases behind a link to the full changelog on GitHub. Used for plugin pages whose
    changelog needs no root-changelog filtering (the whole file is that plugin's history)."""
    path = os.path.join(root, "plugins", plugin_name, "CHANGELOG.md")
    github_url = plugin_changelog_github_url(plugin_name)
    if not os.path.exists(path):
        return render_changelog([], github_url=github_url)
    releases = parse_changelog(read_text(path), None)
    return render_changelog(releases, github_url=github_url)


def _read_normalized(path):
    with open(path, "rb") as fh:
        return fh.read().replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _orphans(dst_dir, allowed_names, check):
    """Flag (in check mode) or delete (in write mode) destination files whose source was
    removed or renamed, so a stale synced copy cannot silently ship."""
    drift = []
    if not os.path.isdir(dst_dir):
        return drift
    for name in sorted(os.listdir(dst_dir)):
        if not os.path.isfile(os.path.join(dst_dir, name)) or name in allowed_names:
            continue
        if check:
            drift.append(name + " (orphaned)")
        else:
            try:
                os.remove(os.path.join(dst_dir, name))
            except OSError as exc:
                sys.stderr.write("warning: could not remove orphaned file %s (%s); "
                                 "delete it manually\n" % (os.path.join(dst_dir, name), exc))
    return drift


def sync_static_assets(root, check):
    """Copy the hand-maintained static assets (site.js, the logos, og-cover.png) from their
    site/src/ SOURCE into the published site/dist/assets/. They are byte-for-byte copies, and
    --check compares them so a stale copy fails CI. styles.css is excluded from the orphan sweep
    because it is a generated artifact assembled from site/css/, not a site/src source."""
    src_dir = os.path.join(root, SITE_STATIC_SRC)
    dst_dir = os.path.join(root, SITE_OUT, "assets")
    drift = []
    src_names = []
    if os.path.isdir(src_dir):
        src_names = [n for n in sorted(os.listdir(src_dir)) if os.path.isfile(os.path.join(src_dir, n))]
    for name in src_names:
        with open(os.path.join(src_dir, name), "rb") as fh:
            data = fh.read()
        dst = os.path.join(dst_dir, name)
        if check:
            existing = None
            if os.path.exists(dst):
                with open(dst, "rb") as fh:
                    existing = fh.read()
            if existing != data:
                drift.append(name)
        else:
            _safe_makedirs(dst_dir)
            with open(dst, "wb") as fh:
                fh.write(data)
    drift.extend(_orphans(dst_dir, set(src_names) | {"styles.css"}, check))
    return drift


def sync_demos(root, check):
    src_dir = os.path.join(root, EXAMPLES_REL)
    dst_dir = os.path.join(root, DEMO_REL)
    drift = []
    for name in DEMO_FILES:
        src = os.path.join(src_dir, name)
        dst = os.path.join(dst_dir, name)
        if not os.path.exists(src):
            raise SystemExit("demo source missing: %s" % src)
        src_bytes = _read_normalized(src)
        if check:
            if not os.path.exists(dst) or _read_normalized(dst) != src_bytes:
                drift.append(name)
        else:
            _safe_makedirs(dst_dir)
            with open(dst, "wb") as fh:
                fh.write(src_bytes)
    drift.extend(_orphans(dst_dir, DEMO_FILES, check))
    return drift


def plugin_version(manifest, name):
    for plugin in manifest.get("plugins", []):
        if plugin.get("name") == name:
            return plugin.get("version", "")
    return ""


_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")
_MD_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_MD_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_MD_CODE = re.compile(r"`([^`]+)`")


def _md_inline(escaped):
    """Apply inline markdown to already-HTML-escaped text. Code spans are parsed first and
    stashed so their content stays literal; images and links are then parsed and their
    generated tags are also stashed, so a later bold pass can never turn a `**` inside a
    URL into <strong> or corrupt an emitted tag. Captured URLs are already HTML-escaped
    (attribute-safe), so they pass through safe_url without re-escaping. Placeholders are
    restored last, repeatedly, so a code span nested in a link is also emitted. The NUL
    sentinel char is stripped from the input first so source text can never collide with a
    placeholder."""
    tokens = []

    def _stash(markup):
        tokens.append(markup)
        return "\x00%d\x00" % (len(tokens) - 1)

    escaped = escaped.replace("\x00", "")
    escaped = _MD_CODE.sub(lambda m: _stash("<code>%s</code>" % m.group(1)), escaped)
    escaped = _MD_IMAGE.sub(
        lambda m: _stash('<img src="%s" alt="%s" loading="lazy" />' % (safe_url(m.group(2)), m.group(1))),
        escaped)
    escaped = _MD_LINK.sub(
        lambda m: _stash('<a href="%s">%s</a>' % (safe_url(m.group(2)),
                                                  _MD_BOLD.sub(r"<strong>\1</strong>", m.group(1)))),
        escaped)
    escaped = _MD_BOLD.sub(r"<strong>\1</strong>", escaped)
    for _ in range(len(tokens) + 1):
        escaped, replaced = re.subn(r"\x00(\d+)\x00", lambda m: tokens[int(m.group(1))], escaped)
        if not replaced:
            break
    return escaped


def render_markdown(md, heading_offset=1):
    """A small, escape-first Markdown-to-HTML renderer for the tutorial page. Handles
    headings, paragraphs, unordered/ordered lists, fenced code blocks, images, links,
    bold, and inline code. All text is HTML-escaped before any markup is applied, so
    raw HTML in the source cannot inject."""
    lines = md.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out = []
    para = []
    list_items = []
    state = {"list_tag": None, "code": None}

    def flush_para():
        if para:
            out.append("<p>%s</p>" % _md_inline(esc(" ".join(para))))
            del para[:]

    def flush_list():
        if list_items:
            out.append("<%s>" % state["list_tag"])
            for item in list_items:
                out.append("<li>%s</li>" % _md_inline(esc(item)))
            out.append("</%s>" % state["list_tag"])
            del list_items[:]
        state["list_tag"] = None

    for raw in lines:
        stripped = raw.strip()
        if state["code"] is not None:
            if stripped.startswith("```"):
                out.append("<pre><code>%s</code></pre>" % esc("\n".join(state["code"])))
                state["code"] = None
            else:
                state["code"].append(raw)
            continue
        if stripped.startswith("```"):
            flush_para()
            flush_list()
            state["code"] = []
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            flush_para()
            flush_list()
            level = min(6, len(heading.group(1)) + heading_offset)
            out.append("<h%d>%s</h%d>" % (level, _md_inline(esc(heading.group(2).strip())), level))
            continue
        bullet = re.match(r"^[-*]\s+(.*)$", stripped)
        ordered = re.match(r"^\d+\.\s+(.*)$", stripped)
        if bullet or ordered:
            flush_para()
            want = "ul" if bullet else "ol"
            if state["list_tag"] and state["list_tag"] != want:
                flush_list()
            state["list_tag"] = want
            list_items.append((bullet or ordered).group(1).strip())
            continue
        if stripped == "":
            flush_para()
            flush_list()
            continue
        if state["list_tag"]:
            flush_list()
        para.append(stripped)
    if state["code"] is not None:
        out.append("<pre><code>%s</code></pre>" % esc("\n".join(state["code"])))
        state["code"] = None
    flush_para()
    flush_list()
    return "\n".join(out)


def site_tutorial_markdown(md):
    """Rewrite the tutorial's example-file links for the generated site. In the shipped
    TUTORIAL.md the example is a link whose display text is the skill-root-relative path
    (no `..`) and whose target is the local file (`../examples/NAME`), so a reader of the
    skill opens the local asset. On the site that local file does not exist at that path,
    so the link target is rewritten to the live demo page under `../demo/NAME`, which the
    site does host - clicking it opens the actual commentable HTML in the browser. Only the
    link target changes; the skill-root-relative display text is left untouched."""
    for name in DEMO_FILES:
        md = md.replace("(../examples/" + name + ")", "(../demo/" + name + ")")
    return md


def sync_tutorial_images(root, check):
    src_dir = os.path.join(root, TUTORIAL_IMAGES_SRC)
    dst_dir = os.path.join(root, TUTORIAL_IMAGES_DST)
    drift = []
    if not os.path.isdir(src_dir):
        drift.extend(_orphans(dst_dir, [], check))
        return drift
    src_names = [n for n in sorted(os.listdir(src_dir)) if os.path.isfile(os.path.join(src_dir, n))]
    for name in src_names:
        src = os.path.join(src_dir, name)
        dst = os.path.join(dst_dir, name)
        with open(src, "rb") as fh:
            data = fh.read()
        if check:
            existing = None
            if os.path.exists(dst):
                with open(dst, "rb") as fh:
                    existing = fh.read()
            if existing != data:
                drift.append(name)
        else:
            _safe_makedirs(dst_dir)
            with open(dst, "wb") as fh:
                fh.write(data)
    drift.extend(_orphans(dst_dir, src_names, check))
    return drift
