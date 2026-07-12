#!/usr/bin/env python3
"""Generate the static, build-time content for the GitHub Pages site.

The site is fully static: the plugins grid, the commentable-html version badge, and
the commentable-html changelog are generated from the repository's own sources
(`.github/plugin/marketplace.json` and `CHANGELOG.md`) and written into marker
regions of the HTML. This keeps the pages self-contained (no client-side fetch, so
no CORS/file:// breakage, no GitHub API rate limits, and no runtime DOM injection),
and it is regenerated on every deploy so the published site never drifts from source.

All text is HTML-escaped and URLs are allowlisted (https or in-repo relative) before
being written, so repository content can never inject markup into the page.

Usage:
    python scripts/build_site_data.py            # write the generated regions + sync demos
    python scripts/build_site_data.py --check     # fail if the committed output is stale
"""
import argparse
import hashlib
import html
import json
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PLUGIN_PAGES = {"commentable-html": "./commentable-html/"}
CHANGELOG_PLUGIN = "commentable-html"
DEMO_FILES = ["report-taxi.html", "report-community-garden.html"]
EXAMPLES_REL = os.path.join(
    "plugins", "commentable-html", "pkg", "skills", "commentable-html", "examples")
DEMO_REL = os.path.join("site", "commentable-html", "demo")
TUTORIAL_SRC = os.path.join(
    "plugins", "commentable-html", "pkg", "skills", "commentable-html", "docs", "TUTORIAL.md")
TUTORIAL_IMAGES_SRC = os.path.join(
    "plugins", "commentable-html", "pkg", "skills", "commentable-html", "docs", "tutorial-images")
TUTORIAL_PAGE = os.path.join("site", "commentable-html", "tutorial", "index.html")
TUTORIAL_IMAGES_DST = os.path.join("site", "commentable-html", "tutorial", "tutorial-images")

# The commentable-html skill root. The tutorial references example files with
# skill-root-relative display paths; locally (in the shipped skill) those links resolve to
# the local asset, while on the generated site they are rewritten to point at the live demo
# page (the site does not host the skill's examples/ tree at that path, but it does host the
# same reports under commentable-html/demo/).

# The full per-plugin changelog on GitHub, linked from the plugin page when older releases
# are folded away (the page shows only the most recent releases; the rest live in source).
CHANGELOG_GITHUB_URL = (
    "https://github.com/urikanonov/ai-marketplace/blob/main/plugins/"
    + CHANGELOG_PLUGIN + "/CHANGELOG.md")


def esc(value):
    return html.escape(str(value), quote=True)


def safe_url(url):
    """Allow https, mailto, and in-repo relative URLs; neutralize anything with a
    dangerous or insecure scheme (javascript:, data:, http:, ...) or a protocol-relative
    //host. Strip C0 control chars, DEL, and whitespace first, because browsers remove
    tabs/newlines from URLs (so a tab inside "javascript" would otherwise hide the scheme),
    and fold backslashes to forward slashes because browsers treat \\host like //host."""
    u = re.sub(r"[\x00-\x20\x7f]", "", url or "").replace("\\", "/")
    if u.startswith("//"):
        return "#"
    scheme = re.match(r"^([a-zA-Z][a-zA-Z0-9+.\-]*):", u)
    if scheme and scheme.group(1).lower() not in ("https", "mailto"):
        return "#"
    return u


def read_text(path):
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read().replace("\r\n", "\n").replace("\r", "\n")


def write_text(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


# Render-critical assets whose URLs carry a content-hash query, so a browser never serves a
# stale stylesheet or script after a deploy (the query changes exactly when the file does).
# Icons are omitted: they change rarely and a cached favicon does not misrender page content.
# The generated pages always use double-quoted attributes, which this pattern targets.
CACHE_BUSTED_ASSETS = ("styles.css", "site.js")
_ASSET_REF_RE = re.compile(
    r'(?P<attr>href|src)="(?P<path>(?:\.{1,2}/)*assets/(?P<file>%s))(?:[?#][^"]*)?"'
    % "|".join(re.escape(name) for name in CACHE_BUSTED_ASSETS))


def _asset_hash(root, name):
    path = os.path.join(root, "site", "assets", name)
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except FileNotFoundError:
        raise SystemExit("cache-busted asset missing: %s" % path)
    return hashlib.sha256(data).hexdigest()[:12]


def stamp_assets(text, root):
    """Append a ?v=<content-hash> query to every reference to a cache-busted asset, replacing any
    existing query or fragment on it. The stamp is idempotent and always matches the committed
    asset, so the URL busts the browser cache exactly when the asset's bytes change."""
    cache = {}

    def repl(match):
        name = match.group("file")
        if name not in cache:
            cache[name] = _asset_hash(root, name)
        return '%s="%s?v=%s"' % (match.group("attr"), match.group("path"), cache[name])

    return _ASSET_REF_RE.sub(repl, text)


def replace_region_block(text, name, inner):
    pattern = re.compile(
        r"([ \t]*)<!-- BEGIN:%s -->.*?<!-- END:%s -->" % (re.escape(name), re.escape(name)),
        re.DOTALL)

    def repl(match):
        indent = match.group(1)
        lines = inner.strip("\n").split("\n")
        body = "\n".join((indent + ln) if ln.strip() else "" for ln in lines)
        return "%s<!-- BEGIN:%s -->\n%s\n%s<!-- END:%s -->" % (indent, name, body, indent, name)

    new_text, count = pattern.subn(repl, text)
    if count == 0:
        raise SystemExit("region not found: %s" % name)
    if count > 1:
        raise SystemExit("duplicate region: %s" % name)
    return new_text


def replace_region_inline(text, name, inner):
    pattern = re.compile(
        r"<!-- BEGIN:%s -->.*?<!-- END:%s -->" % (re.escape(name), re.escape(name)),
        re.DOTALL)
    replacement = "<!-- BEGIN:%s -->%s<!-- END:%s -->" % (name, inner, name)
    new_text, count = pattern.subn(lambda m: replacement, text)
    if count == 0:
        raise SystemExit("region not found: %s" % name)
    if count > 1:
        raise SystemExit("duplicate region: %s" % name)
    return new_text


def render_plugins(manifest):
    suffix = manifest.get("name", "")
    cards = []
    for plugin in manifest.get("plugins", []):
        name = plugin.get("name", "")
        version = plugin.get("version", "")
        description = plugin.get("description", "")
        category = plugin.get("category", "")
        keywords = plugin.get("keywords", []) or []
        homepage = plugin.get("homepage", "")
        page = PLUGIN_PAGES.get(name)
        install = "copilot plugin install %s@%s" % (name, suffix)
        chips = "".join('<span class="chip">%s</span>' % esc(k) for k in keywords)
        category_badge = ('\n    <span class="badge">%s</span>' % esc(category)) if category else ""
        title = '<span class="name">%s</span>' % esc(name)
        source = ('<a class="btn" href="%s">Source</a>' % esc(safe_url(homepage))) if homepage else ""
        learn_more = ('<a class="btn learn-more" href="%s">Learn more</a>' % esc(page)) if page else ""
        foot = learn_more + source
        card = (
            '<article class="card plugin-card">\n'
            '  <div class="head">\n'
            '    %s\n'
            '    <span class="badge version">v%s</span>%s\n'
            '  </div>\n'
            '  <p class="desc">%s</p>\n'
            '  <div class="keywords">%s</div>\n'
            '  <div class="cmd">\n'
            '    <span class="prompt">$</span>\n'
            '    <pre>%s</pre>\n'
            '    <button class="copy-btn" type="button" data-copy="%s">copy</button>\n'
            '  </div>\n'
            '  <div class="foot">%s</div>\n'
            '</article>'
        ) % (title, esc(version), category_badge, esc(description), chips,
             esc(install), esc(install), foot)
        cards.append(card)
    return "\n".join(cards)


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


def render_changelog(releases, expanded_count=2, older_count=5):
    """Show the latest `expanded_count` releases (counted in number of releases, default
    2) inline; fold the next `older_count` releases (default 5) into a single <details>
    that stays collapsed by default so the page stays short. Any releases beyond that are
    not rendered - a link to the full changelog in source is shown instead, so the page
    never grows without bound."""
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
                    n=remaining, s="" if remaining == 1 else "s", url=esc(CHANGELOG_GITHUB_URL)))
        details.append('</details>')
        blocks.append("\n".join(details))
    return "\n".join(blocks)


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
            os.remove(os.path.join(dst_dir, name))
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
            os.makedirs(dst_dir, exist_ok=True)
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
            os.makedirs(dst_dir, exist_ok=True)
            with open(dst, "wb") as fh:
                fh.write(data)
    drift.extend(_orphans(dst_dir, src_names, check))
    return drift


def main(argv):
    parser = argparse.ArgumentParser(description="Generate static site data.")
    parser.add_argument("--check", action="store_true",
                        help="fail (exit 1) if the committed output is stale instead of writing")
    parser.add_argument("--root", default=REPO_ROOT, help="repository root")
    parser.add_argument("--manifest", default=None, help="path to marketplace.json")
    parser.add_argument("--changelog", default=None, help="path to CHANGELOG.md")
    args = parser.parse_args(argv[1:])

    root = args.root
    manifest_path = args.manifest or os.path.join(root, ".github", "plugin", "marketplace.json")

    with open(manifest_path, "r", encoding="utf-8") as fh:
        manifest = json.load(fh)

    plugins_html = render_plugins(manifest)
    changelog_html = render_changelog([])
    for path, filter_plugin in changelog_candidates(root, args.changelog):
        if not os.path.exists(path):
            continue
        releases = parse_changelog(read_text(path), filter_plugin)
        if releases:
            changelog_html = render_changelog(releases)
            break
    version = plugin_version(manifest, CHANGELOG_PLUGIN)

    hub_path = os.path.join(root, "site", "index.html")
    plugin_path = os.path.join(root, "site", "commentable-html", "index.html")

    hub_src = read_text(hub_path)
    hub_out = replace_region_block(hub_src, "plugins", plugins_html)
    hub_out = stamp_assets(hub_out, root)

    plugin_src = read_text(plugin_path)
    plugin_out = replace_region_inline(plugin_src, "version", "v" + esc(version))
    plugin_out = replace_region_block(plugin_out, "changelog", changelog_html)
    plugin_out = replace_region_inline(
        plugin_out, "demo-fullscreen", render_demo_fullscreen_link())
    plugin_out = stamp_assets(plugin_out, root)

    tutorial_page_path = os.path.join(root, TUTORIAL_PAGE)
    tutorial_src_path = os.path.join(root, TUTORIAL_SRC)
    tutorial_src = None
    tutorial_out = None
    if os.path.exists(tutorial_page_path):
        if not os.path.exists(tutorial_src_path):
            raise SystemExit(
                "tutorial source missing: %s (restore it, or remove the tutorial page it generates)"
                % tutorial_src_path)
        tutorial_src = read_text(tutorial_page_path)
        tutorial_out = replace_region_block(
            tutorial_src, "tutorial",
            render_markdown(site_tutorial_markdown(read_text(tutorial_src_path))))
        tutorial_out = stamp_assets(tutorial_out, root)

    demo_drift = sync_demos(root, args.check)
    tutorial_img_drift = sync_tutorial_images(root, args.check)

    if args.check:
        problems = []
        if hub_out != hub_src:
            problems.append("site/index.html plugins region is stale")
        if plugin_out != plugin_src:
            problems.append("site/commentable-html/index.html version/changelog region is stale")
        if tutorial_out is not None and tutorial_out != tutorial_src:
            problems.append("site/commentable-html/tutorial/index.html is stale vs TUTORIAL.md")
        if demo_drift:
            problems.append("demo reports differ from source: " + ", ".join(demo_drift))
        if tutorial_img_drift:
            problems.append("tutorial images differ from source: " + ", ".join(tutorial_img_drift))
        if problems:
            for problem in problems:
                sys.stderr.write("drift: %s\n" % problem)
            sys.stderr.write("fix: run python scripts/build_site_data.py and commit\n")
            return 1
        print("site data up to date")
        return 0

    write_text(hub_path, hub_out)
    write_text(plugin_path, plugin_out)
    if tutorial_out is not None:
        write_text(tutorial_page_path, tutorial_out)
    print("site data generated (plugins, version v%s, changelog, demos, tutorial)" % version)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
