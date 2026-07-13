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
DEMO_FILES = ["report-taxi.html", "report-community-garden.html", "report-triage.html", "report-metrics.html"]
EXAMPLES_REL = os.path.join(
    "plugins", "commentable-html", "pkg", "skills", "commentable-html", "examples")
DEMO_REL = os.path.join("site", "commentable-html", "demo")
TUTORIAL_SRC = os.path.join(
    "plugins", "commentable-html", "pkg", "skills", "commentable-html", "docs", "TUTORIAL.md")
TUTORIAL_IMAGES_SRC = os.path.join(
    "plugins", "commentable-html", "pkg", "skills", "commentable-html", "docs", "tutorial-images")
TUTORIAL_PAGE = os.path.join("site", "commentable-html", "tutorial", "index.html")
TUTORIAL_IMAGES_DST = os.path.join("site", "commentable-html", "tutorial", "tutorial-images")

# Site pages: the hand-edited SOURCE templates live under site-src/pages/ and the committed pages
# under site/ are PURE build artifacts assembled by build_page(). Keeping the source separate from
# the artifact (mirroring the site-src/css/ partials) is what lets --check cover the ENTIRE page,
# so a hand-edit or a stale copy committed by a concurrent PR fails CI instead of silently landing.
HUB_SRC = os.path.join("site-src", "pages", "index.html")
HUB_OUT = os.path.join("site", "index.html")
PLUGIN_SRC = os.path.join("site-src", "pages", "commentable-html", "index.html")
PLUGIN_OUT = os.path.join("site", "commentable-html", "index.html")
TUTORIAL_PAGE_SRC = os.path.join("site-src", "pages", "commentable-html", "tutorial", "index.html")

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

# Absolute production URLs, used for canonical/OG links (hand-authored in the page heads) and for
# the JSON-LD graph, sitemap, and llms.txt generated below. The site is served from this fixed
# project sub-path on github.io, so these never vary per environment.
SITE_BASE_URL = "https://urikanonov.github.io/ai-marketplace/"
SITE_NAME = "ai-marketplace"
OWNER_GITHUB_URL = "https://github.com/urikanonov"
OWNER_LINKEDIN_URL = "https://www.linkedin.com/in/uri-kanonov-946761119"


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


# The served site/assets/styles.css is assembled from ordered source partials under
# site-src/css/, so concurrent edits land in disjoint files. The concatenation is byte-for-byte
# the served bundle (same CSP, same cache-bust); the partial order is load-bearing (CSS cascade).
CSS_PARTS = (
    "10-base.css",
    "20-nav-hero.css",
    "30-components.css",
    "40-demo-changelog.css",
    "50-media-footer.css",
)


def build_styles(root):
    css = "".join(
        read_text(os.path.join(root, "site-src", "css", name)) for name in CSS_PARTS)
    return css_banner() + css


# Generated site artifacts carry a "DO NOT EDIT" banner that names their source, so a human who
# opens the built file under site/ is told to edit the source and rebuild instead. `--check` then
# guarantees the committed artifact still equals a fresh build, so a hand-edit (or a stale copy
# committed by a concurrent PR) fails CI instead of silently shipping.
GENERATED_BANNER_PREFIX = "GENERATED FILE - DO NOT EDIT."
_RUN_HINT = "run: python scripts/build_site_data.py"


def css_banner():
    return ("/* %s Built from site-src/css/*.css by scripts/build_site_data.py; %s */\n"
            % (GENERATED_BANNER_PREFIX, _RUN_HINT))


def page_banner(source_rel):
    return ("<!-- %s Built from %s by scripts/build_site_data.py; %s -->"
            % (GENERATED_BANNER_PREFIX, source_rel.replace(os.sep, "/"), _RUN_HINT))


_PAGE_BANNER_RE = re.compile(
    r"^[ \t]*<!-- %s.*?-->[ \t]*\r?\n?" % re.escape(GENERATED_BANNER_PREFIX), re.MULTILINE)
_DOCTYPE_RE = re.compile(r"(?i)^\s*<!doctype html>[^\n]*\n?")


def apply_page_banner(html, source_rel):
    """Insert the DO NOT EDIT banner right after the doctype (replacing any prior banner), so the
    built page self-identifies as an artifact and points at its source."""
    html = _PAGE_BANNER_RE.sub("", html, count=1)
    banner = page_banner(source_rel) + "\n"
    m = _DOCTYPE_RE.match(html)
    if m:
        return html[:m.end()] + banner + html[m.end():]
    return banner + html


def build_page(root, source_rel, region_fillers):
    """Assemble one site page ARTIFACT from its site-src/pages SOURCE: fill each marker region,
    cache-bust asset references, and inject the DO NOT EDIT banner. The source is independent of
    the built artifact under site/, so `--check` (comparing this result to the committed artifact)
    covers the whole page - not just the marker regions - which is what closes the site clobber gap."""
    out = read_text(os.path.join(root, source_rel))
    for kind, name, value in region_fillers:
        if kind == "inline":
            out = replace_region_inline(out, name, value)
        else:
            out = replace_region_block(out, name, value)
    out = stamp_assets(out, root)
    return apply_page_banner(out, source_rel)


def _read_artifact(path):
    """Return the committed artifact text, or None when it is missing so an absent built page
    counts as drift under --check."""
    return read_text(path) if os.path.exists(path) else None


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
        if page:
            title = '<span class="name"><a href="%s">%s</a></span>' % (esc(page), esc(name))
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


def _plugin_app_url(plugin):
    """The canonical URL for a plugin: its own generated site page when it has one, else its
    manifest homepage (allowlisted), falling back to the site root."""
    page = PLUGIN_PAGES.get(plugin.get("name", ""))
    if page:
        return SITE_BASE_URL + page.lstrip("./")
    return safe_url(plugin.get("homepage", "")) or SITE_BASE_URL


def _jsonld_script(data):
    """Serialize a JSON-LD graph and neutralize the three characters that could otherwise break
    out of the <script> block or the surrounding HTML, so manifest-sourced text can never inject.
    The escapes are valid JSON string escapes, so the block still parses as JSON-LD."""
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    payload = payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return '<script type="application/ld+json">\n%s\n</script>' % payload


def render_jsonld(manifest):
    """The hub's structured-data graph: the WebSite, its author (Person), and an ItemList of the
    published plugins as SoftwareApplication entries, all built from the manifest so it stays in
    sync as plugins are added or changed."""
    description = manifest.get("metadata", {}).get("description", "")
    owner = manifest.get("owner", {}).get("name", "")
    items = []
    for position, plugin in enumerate(manifest.get("plugins", []), start=1):
        items.append({
            "@type": "ListItem",
            "position": position,
            "item": {
                "@type": "SoftwareApplication",
                "name": plugin.get("name", ""),
                "applicationCategory": "DeveloperApplication",
                "operatingSystem": "Cross-platform (GitHub Copilot CLI)",
                "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
                "description": plugin.get("description", ""),
                "url": _plugin_app_url(plugin),
            },
        })
    data = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "WebSite",
                "@id": SITE_BASE_URL + "#website",
                "url": SITE_BASE_URL,
                "name": SITE_NAME,
                "description": description,
                "author": {"@id": SITE_BASE_URL + "#person"},
            },
            {
                "@type": "Person",
                "@id": SITE_BASE_URL + "#person",
                "name": owner,
                "url": OWNER_GITHUB_URL,
                "sameAs": [OWNER_GITHUB_URL, OWNER_LINKEDIN_URL],
            },
            {
                "@type": "ItemList",
                "name": "Plugins",
                "itemListElement": items,
            },
        ],
    }
    return _jsonld_script(data)


def site_page_urls(root):
    """Absolute URLs of the indexable HTML pages: the hub, each plugin page, and the tutorial when
    its source page exists. Used for the sitemap."""
    urls = [SITE_BASE_URL]
    for page in PLUGIN_PAGES.values():
        urls.append(SITE_BASE_URL + page.lstrip("./"))
    if os.path.exists(os.path.join(root, TUTORIAL_PAGE_SRC)):
        rel = os.path.relpath(TUTORIAL_PAGE, "site").replace(os.sep, "/")
        urls.append(SITE_BASE_URL + rel[: -len("index.html")])
    return urls


def render_sitemap(root):
    locs = "\n".join("  <url><loc>%s</loc></url>" % esc(url) for url in site_page_urls(root))
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            "%s\n</urlset>\n") % locs


def render_llms(manifest):
    """An llms.txt (Markdown) front door for LLM crawlers: the marketplace summary, how to install,
    a list of plugins with links and descriptions, and the tutorial link, all from the manifest."""
    description = manifest.get("metadata", {}).get("description", "")
    suffix = manifest.get("name", "")
    lines = ["# " + SITE_NAME, "", "> " + description, ""]
    lines.append(
        "Add the marketplace once with "
        "`copilot plugin marketplace add https://github.com/urikanonov/ai-marketplace`, then install "
        "any plugin with `copilot plugin install <name>@%s`." % suffix)
    lines.extend(["", "## Plugins"])
    for plugin in manifest.get("plugins", []):
        lines.append("- [%s](%s): %s" % (
            plugin.get("name", ""), _plugin_app_url(plugin), plugin.get("description", "")))
    lines.extend(["", "## Documentation",
                  "- [Commentable HTML tutorial](%scommentable-html/tutorial/)" % SITE_BASE_URL, ""])
    return "\n".join(lines)


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

    # Assemble the served stylesheet from its source partials before anything stamps its hash.
    styles_text = build_styles(root)
    styles_path = os.path.join(root, "site", "assets", "styles.css")
    if not args.check:
        write_text(styles_path, styles_text)

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

    hub_out = build_page(root, HUB_SRC, [
        ("block", "plugins", plugins_html),
        ("block", "jsonld", render_jsonld(manifest)),
    ])
    plugin_out = build_page(root, PLUGIN_SRC, [
        ("inline", "version", "v" + esc(version)),
        ("block", "changelog", changelog_html),
        ("inline", "demo-fullscreen", render_demo_fullscreen_link()),
    ])
    hub_out_path = os.path.join(root, HUB_OUT)
    plugin_out_path = os.path.join(root, PLUGIN_OUT)

    tutorial_src_page = os.path.join(root, TUTORIAL_PAGE_SRC)
    tutorial_out_path = os.path.join(root, TUTORIAL_PAGE)
    tutorial_md_path = os.path.join(root, TUTORIAL_SRC)
    tutorial_out = None
    if os.path.exists(tutorial_src_page):
        if not os.path.exists(tutorial_md_path):
            raise SystemExit(
                "tutorial markdown missing: %s (restore it, or remove the tutorial source page it feeds)"
                % tutorial_md_path)
        tutorial_out = build_page(root, TUTORIAL_PAGE_SRC, [
            ("block", "tutorial",
             render_markdown(site_tutorial_markdown(read_text(tutorial_md_path)))),
        ])

    demo_drift = sync_demos(root, args.check)
    tutorial_img_drift = sync_tutorial_images(root, args.check)
    sitemap_drift = write_or_check(
        os.path.join(root, "site", "sitemap.xml"), render_sitemap(root), args.check)
    llms_drift = write_or_check(
        os.path.join(root, "site", "llms.txt"), render_llms(manifest), args.check)

    if args.check:
        problems = []
        if styles_text != read_text(styles_path):
            problems.append("site/assets/styles.css is stale vs site-src/css/ partials")
        if hub_out != _read_artifact(hub_out_path):
            problems.append("site/index.html is stale vs its site-src/pages/index.html source "
                            "(do not hand-edit the built page; edit the source and rebuild)")
        if plugin_out != _read_artifact(plugin_out_path):
            problems.append("site/commentable-html/index.html is stale vs its "
                            "site-src/pages/commentable-html/index.html source "
                            "(do not hand-edit the built page; edit the source and rebuild)")
        if tutorial_out is not None and tutorial_out != _read_artifact(tutorial_out_path):
            problems.append("site/commentable-html/tutorial/index.html is stale vs its source "
                            "and TUTORIAL.md")
        if demo_drift:
            problems.append("demo reports differ from source: " + ", ".join(demo_drift))
        if tutorial_img_drift:
            problems.append("tutorial images differ from source: " + ", ".join(tutorial_img_drift))
        if sitemap_drift:
            problems.append("site/sitemap.xml is stale")
        if llms_drift:
            problems.append("site/llms.txt is stale")
        if problems:
            for problem in problems:
                sys.stderr.write("drift: %s\n" % problem)
            sys.stderr.write("fix: run python scripts/build_site_data.py and commit\n")
            return 1
        print("site data up to date")
        return 0

    write_text(hub_out_path, hub_out)
    write_text(plugin_out_path, plugin_out)
    if tutorial_out is not None:
        write_text(tutorial_out_path, tutorial_out)
    print("site data generated (plugins, jsonld, version v%s, changelog, demos, tutorial, sitemap, llms)" % version)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
