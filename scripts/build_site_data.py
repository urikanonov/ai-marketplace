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


def esc(value):
    return html.escape(str(value), quote=True)


def safe_url(url):
    """Allow only https and in-repo relative / mailto URLs; neutralize anything else
    (javascript:, data:, protocol-relative) so fetched manifest links cannot inject."""
    u = (url or "").strip()
    if re.match(r"^(https://|\./|\.\./|/|#|mailto:)", u):
        return u
    return "#"


def read_text(path):
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read().replace("\r\n", "\n").replace("\r", "\n")


def write_text(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


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
    return new_text


def replace_region_inline(text, name, inner):
    pattern = re.compile(
        r"<!-- BEGIN:%s -->.*?<!-- END:%s -->" % (re.escape(name), re.escape(name)),
        re.DOTALL)
    replacement = "<!-- BEGIN:%s -->%s<!-- END:%s -->" % (name, inner, name)
    new_text, count = pattern.subn(lambda m: replacement, text)
    if count == 0:
        raise SystemExit("region not found: %s" % name)
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
        primary = ('<a class="btn btn-primary" href="%s">Learn more</a>' % esc(page)) if page else ""
        source = ('<a class="btn" href="%s">Source</a>' % esc(safe_url(homepage))) if homepage else ""
        card = (
            '<article class="card plugin-card">\n'
            '  <div class="head">\n'
            '    <span class="name">%s</span>\n'
            '    <span class="badge version">v%s</span>%s\n'
            '  </div>\n'
            '  <p class="desc">%s</p>\n'
            '  <div class="keywords">%s</div>\n'
            '  <div class="cmd">\n'
            '    <span class="prompt">$</span>\n'
            '    <pre>%s</pre>\n'
            '    <button class="copy-btn" type="button" data-copy="%s">copy</button>\n'
            '  </div>\n'
            '  <div class="foot">%s%s</div>\n'
            '</article>'
        ) % (esc(name), esc(version), category_badge, esc(description), chips,
             esc(install), esc(install), primary, source)
        cards.append(card)
    return "\n".join(cards)


def clean_entry(text, plugin):
    stripped = text.replace("`", "")
    if plugin:
        stripped = re.sub(r"^%s\s+v?\d+\.\d+\.\d+\s*[-:]\s*" % re.escape(plugin), "", stripped)
    return stripped.strip()


def resolve_changelog(root, explicit):
    """Locate the changelog source. Prefer the marketplace root CHANGELOG.md (filter
    to the plugin's bullets); fall back to a per-plugin CHANGELOG.md (all bullets) so
    the site keeps building if the changelog is ever split per plugin. Returns
    (path_or_None, filter_plugin) where filter_plugin is None for a per-plugin file."""
    if explicit:
        return explicit, CHANGELOG_PLUGIN
    candidates = [
        (os.path.join(root, "CHANGELOG.md"), CHANGELOG_PLUGIN),
        (os.path.join(root, "plugins", CHANGELOG_PLUGIN, "CHANGELOG.md"), None),
    ]
    for path, filter_plugin in candidates:
        if os.path.exists(path):
            return path, filter_plugin
    return None, None


def parse_changelog(text, plugin):
    releases = []
    current_release = None
    current_type = None
    buffer = None

    def flush():
        nonlocal buffer
        if buffer is not None and current_release is not None and current_type is not None:
            if plugin is None or plugin in buffer:
                current_release["groups"].setdefault(current_type, []).append(
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


def render_changelog(releases):
    if not releases:
        return ('<p class="empty">No changelog entries yet. '
                'See the full marketplace changelog on GitHub.</p>')
    blocks = []
    for release in releases:
        parts = ['<div class="release">',
                 '  <div class="rel-head"><h3>%s</h3></div>' % esc(release["name"])]
        for change_type, items in release["groups"].items():
            parts.append('  <div class="group-label">%s</div>' % esc(change_type))
            parts.append('  <ul>')
            for item in items:
                parts.append('    <li>%s</li>' % esc(item))
            parts.append('  </ul>')
        parts.append('</div>')
        blocks.append("\n".join(parts))
    return "\n".join(blocks)


def sync_demos(root, check):
    src_dir = os.path.join(root, EXAMPLES_REL)
    dst_dir = os.path.join(root, DEMO_REL)
    drift = []
    for name in DEMO_FILES:
        src = os.path.join(src_dir, name)
        dst = os.path.join(dst_dir, name)
        if not os.path.exists(src):
            raise SystemExit("demo source missing: %s" % src)
        with open(src, "rb") as fh:
            src_bytes = fh.read()
        if check:
            if not os.path.exists(dst) or open(dst, "rb").read() != src_bytes:
                drift.append(name)
        else:
            os.makedirs(dst_dir, exist_ok=True)
            with open(dst, "wb") as fh:
                fh.write(src_bytes)
    return drift


def plugin_version(manifest, name):
    for plugin in manifest.get("plugins", []):
        if plugin.get("name") == name:
            return plugin.get("version", "")
    return ""


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
    changelog_path, changelog_filter = resolve_changelog(root, args.changelog)

    with open(manifest_path, "r", encoding="utf-8") as fh:
        manifest = json.load(fh)

    plugins_html = render_plugins(manifest)
    if changelog_path is None:
        changelog_html = render_changelog([])
    else:
        changelog_text = read_text(changelog_path)
        changelog_html = render_changelog(parse_changelog(changelog_text, changelog_filter))
    version = plugin_version(manifest, CHANGELOG_PLUGIN)

    hub_path = os.path.join(root, "site", "index.html")
    plugin_path = os.path.join(root, "site", "commentable-html", "index.html")

    hub_src = read_text(hub_path)
    hub_out = replace_region_block(hub_src, "plugins", plugins_html)

    plugin_src = read_text(plugin_path)
    plugin_out = replace_region_inline(plugin_src, "version", "v" + esc(version))
    plugin_out = replace_region_block(plugin_out, "changelog", changelog_html)

    demo_drift = sync_demos(root, args.check)

    if args.check:
        problems = []
        if hub_out != hub_src:
            problems.append("site/index.html plugins region is stale")
        if plugin_out != plugin_src:
            problems.append("site/commentable-html/index.html version/changelog region is stale")
        if demo_drift:
            problems.append("demo reports differ from source: " + ", ".join(demo_drift))
        if problems:
            for problem in problems:
                sys.stderr.write("drift: %s\n" % problem)
            sys.stderr.write("fix: run python scripts/build_site_data.py and commit\n")
            return 1
        print("site data up to date")
        return 0

    write_text(hub_path, hub_out)
    write_text(plugin_path, plugin_out)
    print("site data generated (plugins, version v%s, changelog, demos)" % version)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
