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
import io
import json
import os
import re
import subprocess
import sys
import zipfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

UPDATER_PLUGIN = "urikan-ai-marketplace-auto-updater"
PLUGIN_PAGES = {
    "commentable-html": "./commentable-html/",
    UPDATER_PLUGIN: "./" + UPDATER_PLUGIN + "/",
}
CHANGELOG_PLUGIN = "commentable-html"
DEMO_FILES = ["report-taxi.html", "report-community-garden.html", "report-triage.html", "report-metrics.html", "report-checklist.html", "deck-showcase.html"]
EXAMPLES_REL = os.path.join(
    "plugins", "commentable-html", "pkg", "skills", "commentable-html", "examples")
# Site layout (all under site/): sources and the generated publishable output live together.
#   site/pages/  page templates (source)        site/css/  CSS partials (source)
#   site/src/    hand-maintained static asset sources (site.js, logos, og-cover.png)
#   site/dist/   the generated publishable site (the Pages deploy artifact); DO NOT hand-edit
#   site/tests/  the site's Playwright suite
SITE_OUT = os.path.join("site", "dist")
SITE_PAGES = os.path.join("site", "pages")
SITE_STATIC_SRC = os.path.join("site", "src")

DEMO_REL = os.path.join(SITE_OUT, "commentable-html", "demo")
TUTORIAL_SRC = os.path.join(
    "plugins", "commentable-html", "pkg", "skills", "commentable-html", "docs", "TUTORIAL.md")
TUTORIAL_IMAGES_SRC = os.path.join(
    "plugins", "commentable-html", "pkg", "skills", "commentable-html", "docs", "assets")
TUTORIAL_PAGE = os.path.join(SITE_OUT, "commentable-html", "tutorial", "index.html")
TUTORIAL_IMAGES_DST = os.path.join(SITE_OUT, "commentable-html", "tutorial", "assets")

# Site pages: the hand-edited SOURCE templates live under site/pages/ and the committed pages
# under site/dist/ are PURE build artifacts assembled by build_page(). Keeping the source separate
# from the artifact (mirroring the site/css/ partials) is what lets --check cover the ENTIRE page,
# so a hand-edit or a stale copy committed by a concurrent PR fails CI instead of silently landing.
HUB_SRC = os.path.join(SITE_PAGES, "index.html")
HUB_OUT = os.path.join(SITE_OUT, "index.html")
PLUGIN_SRC = os.path.join(SITE_PAGES, "commentable-html", "index.html")
PLUGIN_OUT = os.path.join(SITE_OUT, "commentable-html", "index.html")
# The auto-updater plugin page: a REQUIRED page like the hub and the commentable-html page (its
# source must exist), built from its own site/pages source with only the version badge filled from
# the manifest so it never drifts from the shipped plugin version.
UPDATER_SRC = os.path.join(SITE_PAGES, UPDATER_PLUGIN, "index.html")
UPDATER_OUT = os.path.join(SITE_OUT, UPDATER_PLUGIN, "index.html")
TUTORIAL_PAGE_SRC = os.path.join(SITE_PAGES, "commentable-html", "tutorial", "index.html")

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

# The plugins here install into BOTH Claude Code and the GitHub Copilot CLI. The install block is
# tabbed by agent: each agent shares the same marketplace name and git URL and differs only in the
# leading CLI binary. INSTALL_AGENTS is (key, tab label, CLI binary); Copilot is first (the default
# tab). The repo-root .claude-plugin/marketplace.json lists which plugins are Claude-installable, so
# the Claude tab is offered only for those (both currently shipped plugins are dual-agent; the
# carve-out remains for any future Copilot-only plugin). Both CLIs and their Desktop apps invoke the
# same installed skill.
MARKETPLACE_GIT_URL = "https://github.com/urikanonov/ai-marketplace"
CLAUDE_MARKETPLACE_REL = os.path.join(".claude-plugin", "marketplace.json")
INSTALL_AGENTS = [
    ("copilot", "GitHub Copilot", "copilot"),
    ("claude", "Claude Code", "claude"),
]

# Claude Desktop / claude.ai import a skill as a ZIP through Settings > Features (Pro/Max/Team/
# Enterprise with code execution). The install block offers a third "Claude Desktop" tab for the
# plugins listed here, linking to a downloadable ZIP of the shipped skill. The auto-updater is
# intentionally absent: its value is the session-start hook, which a Desktop skill import cannot
# provide, so it offers CLI tabs only. Each entry: skill_dir (repo-relative, the shipped skill
# whose contents are zipped under a single top-level `skill/` folder), skill (the folder/skill
# name), and zip (the site/dist-relative output path).
DESKTOP_SKILLS = {
    "commentable-html": {
        "skill_dir": "plugins/commentable-html/pkg/skills/commentable-html",
        "skill": "commentable-html",
        "zip": "skills/commentable-html.zip",
    },
}

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
        return fh.read().replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")


def _safe_makedirs(directory):
    """Create a directory tree, turning a directory-vs-file path conflict into a clear SystemExit
    instead of a raw NotADirectoryError/FileExistsError traceback."""
    if not directory:
        return
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError as exc:
        raise SystemExit("cannot create output directory %s (%s); a file may exist where a "
                         "directory is expected" % (directory, exc))


def write_text(path, text):
    _safe_makedirs(os.path.dirname(path))
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
    # styles.css is itself a build artifact (assembled from site/css/ partials), so hash the
    # freshly-built stylesheet rather than the on-disk copy: the page's ?v= stamp then reflects the
    # SOURCE partials directly (a pure artifact), it is normalization-independent, and a missing or
    # stale site/dist/assets/styles.css cannot crash --check or embed a stale hash. Other assets
    # (site.js) are copied verbatim from their site/src/ source, so the served bytes are the source.
    if name == "styles.css":
        return hashlib.sha256(build_styles(root).encode("utf-8")).hexdigest()[:12]
    path = os.path.join(root, SITE_OUT, "assets", name)
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as exc:
        raise SystemExit("cannot read required cache-busted asset %s (%s); it is a committed "
                         "source, not generated - restore it" % (path, exc))
    return hashlib.sha256(data).hexdigest()[:12]


# The served site/dist/assets/styles.css is assembled from ALL ordered source partials under
# site/css/, discovered by directory sort (no hand-maintained list, so adding a partial does
# not edit this script and two PRs adding partials do not collide here). Each partial is named
# `NN-topic.css` with a zero-padded 2-digit prefix; the sorted order is the load-bearing CSS
# cascade. The concatenation is byte-for-byte the served bundle (same CSP, same cache-bust).
CSS_DIR = ("site", "css")
_CSS_PART_RE = re.compile(r"^\d{2}-[a-z0-9-]+\.css$")


def ordered_css_parts(root):
    css_dir = os.path.join(root, *CSS_DIR)
    if not os.path.isdir(css_dir):
        raise SystemExit("CSS source directory missing: %s" % css_dir)
    names = [n for n in os.listdir(css_dir) if os.path.isfile(os.path.join(css_dir, n)) and n.lower().endswith(".css")]
    stray = [n for n in names if not _CSS_PART_RE.match(n)]
    if stray:
        raise SystemExit("site/css/ holds .css files that are not `NN-topic.css` partials: %s "
                         "(rename to the numbered convention or remove them)" % ", ".join(sorted(stray)))
    if not names:
        raise SystemExit("no CSS partials found under %s" % css_dir)
    return sorted(names)


def build_styles(root):
    css_dir = os.path.join(root, *CSS_DIR)
    parts = [read_text(os.path.join(css_dir, name)) for name in ordered_css_parts(root)]
    return css_banner() + "".join(parts)


# Generated site artifacts carry a "DO NOT EDIT" banner that names their source, so a human who
# opens the built file under site/ is told to edit the source and rebuild instead. `--check` then
# guarantees the committed artifact still equals a fresh build, so a hand-edit (or a stale copy
# committed by a concurrent PR) fails CI instead of silently shipping.
GENERATED_BANNER_PREFIX = "GENERATED FILE - DO NOT EDIT."
_RUN_HINT = "run: python scripts/build_site_data.py"


def css_banner():
    return ("/* %s Built from site/css/*.css by scripts/build_site_data.py; %s */\n"
            % (GENERATED_BANNER_PREFIX, _RUN_HINT))


def page_banner(source_rel):
    return ("<!-- %s Built from %s by scripts/build_site_data.py; %s -->"
            % (GENERATED_BANNER_PREFIX, source_rel.replace(os.sep, "/"), _RUN_HINT))


_PAGE_BANNER_RE = re.compile(
    r"^[ \t]*<!-- %s[^\n]*?-->[ \t]*\r?\n?" % re.escape(GENERATED_BANNER_PREFIX))
_DOCTYPE_RE = re.compile(r"(?i)^(\s*<!doctype[^>]*>)([ \t]*\r?\n?)")


def apply_page_banner(html, source_rel):
    """Insert the DO NOT EDIT banner right after the doctype (replacing any prior banner in that
    exact slot), so the built page self-identifies as an artifact and points at its source. The
    strip is anchored to the position right after the doctype, so a body comment that happens to
    start with the banner prefix is never removed; the doctype match tolerates any doctype variant."""
    banner = page_banner(source_rel)
    m = _DOCTYPE_RE.match(html)
    if m:
        rest = _PAGE_BANNER_RE.sub("", html[m.end():], count=1)
        return m.group(1) + (m.group(2) or "\n") + banner + "\n" + rest
    return banner + "\n" + _PAGE_BANNER_RE.sub("", html, count=1)


def build_page(root, source_rel, region_fillers):
    """Assemble one site page ARTIFACT from its site/pages SOURCE: fill each marker region,
    cache-bust asset references, and inject the DO NOT EDIT banner. The source is independent of
    the built artifact under site/, so `--check` (comparing this result to the committed artifact)
    covers the whole page - not just the marker regions - which is what closes the site clobber gap."""
    out = read_text(os.path.join(root, source_rel))
    if not _DOCTYPE_RE.match(out):
        raise SystemExit("page source %s must begin with a <!doctype ...> declaration"
                         % source_rel.replace(os.sep, "/"))
    # Count only line-leading doctype declarations (how a real duplicate from a bad merge appears),
    # so a literal "<!doctype" embedded in prose, a script string, or a comment never false-trips.
    if len(re.findall(r"(?im)^[ \t]*<!doctype\b", out)) != 1:
        raise SystemExit("page source %s must contain exactly one <!doctype ...> declaration "
                         "(a second one is usually a merge artifact)" % source_rel.replace(os.sep, "/"))
    for kind, name, value in region_fillers:
        if kind == "inline":
            out = replace_region_inline(out, name, value)
        elif kind == "block":
            out = replace_region_block(out, name, value)
        else:
            raise SystemExit("build_page: unknown region filler kind %r (use 'inline' or 'block')" % kind)
    out = stamp_assets(out, root)
    return apply_page_banner(out, source_rel)


def _read_artifact(path):
    """Return the committed artifact text, or None when it is missing (or is not a regular file) so
    an absent built page counts as drift under --check."""
    return read_text(path) if os.path.isfile(path) else None


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


def claude_plugin_names(root):
    """Names of the plugins that are installable in Claude Code, read from the repo-root
    .claude-plugin/marketplace.json. The install block offers a Claude tab only for these, so a
    plugin whose Claude support is not shipped never advertises a Claude install path (both
    currently shipped plugins are dual-agent; the carve-out remains for any future Copilot-only
    plugin). Returns an empty set when the file is absent, unreadable, or structurally
    malformed (a non-object root, a non-list `plugins`, or non-object entries), so a broken mirror
    fails closed to Copilot-only rather than crashing the build."""
    path = os.path.join(root, CLAUDE_MARKETPLACE_REL)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return set()
    if not isinstance(data, dict):
        return set()
    plugins = data.get("plugins")
    if not isinstance(plugins, list):
        return set()
    return {p["name"] for p in plugins
            if isinstance(p, dict) and isinstance(p.get("name"), str) and p["name"]}


def _slug_id(text):
    """A safe HTML id fragment for an element id or ARIA target: keep only letters, digits, hyphen,
    and underscore, mapping every other character to '-'. Ids are derived from repo-controlled
    plugin names, but the manifest schema does not restrict the name to a slug, so this guarantees
    the generated id is a valid, injection-proof attribute value regardless of the name."""
    return re.sub(r"[^A-Za-z0-9_-]", "-", text)



def _install_command(binary, kind, name, suffix):
    if kind == "marketplace":
        return "%s plugin marketplace add %s" % (binary, MARKETPLACE_GIT_URL)
    return "%s plugin install %s@%s" % (binary, name, suffix)


def _install_row(step, label, command):
    """One labelled, copyable install command row: an optional step badge, a label, and the
    reused .cmd command box with its own copy button (so every command is copyable on its own)."""
    badge = ('<span class="install-step" aria-hidden="true">%d</span>\n          ' % step
             if step else "")
    return (
        '<div class="install-row">\n'
        '          %s<div class="install-cmd">\n'
        '            <span class="install-label">%s</span>\n'
        '            <div class="cmd">\n'
        '              <span class="prompt">$</span>\n'
        '              <pre>%s</pre>\n'
        '              <button class="copy-btn" type="button" data-copy="%s">copy</button>\n'
        '            </div>\n'
        '          </div>\n'
        '        </div>'
    ) % (badge, esc(label), esc(command), esc(command))


def _install_rows(binary, name, suffix, marketplace_only):
    rows = [("marketplace", "Install marketplace")]
    if not marketplace_only:
        rows.append(("plugin", "Install plugin"))
    show_steps = len(rows) > 1
    return "\n        ".join(
        _install_row(i if show_steps else None, label,
                     _install_command(binary, kind, name, suffix))
        for i, (kind, label) in enumerate(rows, start=1))


def _install_desktop_panel(zip_url, skill_name):
    """The Claude Desktop install panel: a download link to the shipped skill ZIP plus short import
    steps. Unlike the CLI panels, there is no command to run - the user uploads the ZIP in Claude's
    Settings > Features (Pro/Max/Team/Enterprise with code execution)."""
    href = esc(safe_url(zip_url))
    return (
        '<div class="install-download">\n'
        '          <a class="btn btn-primary install-download-btn" href="%s" download>'
        'Download the skill (ZIP)</a>\n'
        '          <ol class="install-desktop-steps">\n'
        '            <li>Download the ZIP above.</li>\n'
        '            <li>In Claude (Desktop or claude.ai), open <strong>Settings &gt; Features</strong> '
        'and enable Skills (Pro, Max, Team, or Enterprise with code execution).</li>\n'
        '            <li>Upload the ZIP to add the <code>%s</code> skill, then invoke it in any chat.</li>\n'
        '          </ol>\n'
        '        </div>'
    ) % (href, esc(skill_name))


def render_install(name, suffix, claude, idbase, marketplace_only=False,
                   desktop_zip=None, desktop_skill=None):
    """A tabbed install block: one tab per supported agent (Copilot always, Claude when `claude`,
    and a "Claude Desktop" ZIP-download tab when `desktop_zip` is set and this is a specific plugin),
    each panel splitting the marketplace-add and plugin-install commands into separate rows with
    their own copy buttons. When only one entry is supported the tab chrome is dropped and the panel
    renders on its own, so a Copilot-only plugin never shows an empty or misleading tab. `idbase` is
    slugged so an id/ARIA attribute derived from a plugin name is always valid and safe. Tab/panel
    visibility is driven by the `hidden` attribute (mirrored by the JS); `aria-selected` marks the
    active tab. No cosmetic state class is emitted - the CSS keys off `aria-selected`/`hidden`."""
    idbase = _slug_id(idbase)
    agents = [a for a in INSTALL_AGENTS if a[0] == "copilot" or claude]
    entries = [(key, label, _install_rows(binary, name, suffix, marketplace_only))
               for key, label, binary in agents]
    # The Desktop ZIP tab is a per-plugin download, so it never appears on the generic hub hero
    # (marketplace_only) block, only on a specific plugin's install block.
    if desktop_zip and not marketplace_only:
        entries.append(("desktop", "Claude Desktop",
                        _install_desktop_panel(desktop_zip, desktop_skill or name)))
    if len(entries) == 1:
        return ('<div class="install-block install-solo">\n        %s\n      </div>'
                % entries[0][2])
    tabs = []
    panels = []
    for idx, (key, label, panel_html) in enumerate(entries):
        active = idx == 0
        tab_id = "%s-%s-tab" % (idbase, key)
        panel_id = "%s-%s" % (idbase, key)
        tabs.append(
            '<button class="install-tab" role="tab" type="button" id="%s" '
            'data-install-target="%s" aria-selected="%s" aria-controls="%s" tabindex="%s">%s</button>'
            % (tab_id, panel_id, "true" if active else "false", panel_id,
               "0" if active else "-1", esc(label)))
        panels.append(
            '<div class="install-panel" role="tabpanel" id="%s" aria-labelledby="%s"%s>\n'
            '        %s\n      </div>'
            % (panel_id, tab_id, "" if active else " hidden", panel_html))
    return (
        '<div class="install-block install-tabs" data-install-tabs>\n'
        '      <div class="install-tablist" role="tablist" aria-label="Install with">\n'
        '        %s\n'
        '      </div>\n'
        '      %s\n'
        '    </div>'
    ) % ("\n        ".join(tabs), "\n      ".join(panels))


def _desktop_install_args(plugin_name, rel_prefix=""):
    """The (zip_url, skill_name) to pass render_install for a plugin's Claude Desktop tab, or
    (None, None) when the plugin offers no Desktop skill ZIP. `rel_prefix` adjusts the ZIP URL for
    the calling page's directory depth (empty for the hub, "../" for a plugin subpage)."""
    d = DESKTOP_SKILLS.get(plugin_name)
    if not d:
        return (None, None)
    return (rel_prefix + d["zip"], d["skill"])


def render_plugins(manifest, claude_names=None):
    claude_names = claude_names or set()
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
        desktop_zip, desktop_skill = _desktop_install_args(name)
        install_block = render_install(name, suffix, name in claude_names,
                                       "install-card-" + name,
                                       desktop_zip=desktop_zip, desktop_skill=desktop_skill)
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
            '  <div class="install">\n'
            '    %s\n'
            '  </div>\n'
            '  <div class="foot">%s</div>\n'
            '</article>'
        ) % (title, esc(version), category_badge, esc(description), chips,
             install_block, foot)
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


def render_jsonld(manifest, claude_names=None):
    """The hub's structured-data graph: the WebSite, its author (Person), and an ItemList of the
    published plugins as SoftwareApplication entries, all built from the manifest so it stays in
    sync as plugins are added or changed. `operatingSystem` is set per plugin from `claude_names`
    so a Copilot-only plugin (should one ever ship) is not advertised as Claude-installable."""
    claude_names = claude_names or set()
    description = manifest.get("metadata", {}).get("description", "")
    owner = manifest.get("owner", {}).get("name", "")
    items = []
    for position, plugin in enumerate(manifest.get("plugins", []), start=1):
        os_label = ("Cross-platform (Claude Code, GitHub Copilot CLI)"
                    if plugin.get("name", "") in claude_names
                    else "Cross-platform (GitHub Copilot CLI)")
        items.append({
            "@type": "ListItem",
            "position": position,
            "item": {
                "@type": "SoftwareApplication",
                "name": plugin.get("name", ""),
                "applicationCategory": "DeveloperApplication",
                "operatingSystem": os_label,
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


def _tutorial_source_exists(root):
    """The tutorial is the one OPTIONAL page: its sitemap and llms.txt links are gated on this so the
    two call sites can never silently diverge (both must key off the SOURCE, not the built artifact)."""
    return os.path.isfile(os.path.join(root, TUTORIAL_PAGE_SRC))


def site_page_urls(root):
    """Absolute URLs of the indexable HTML pages: the hub, each plugin page, and the tutorial when
    its source page exists. Used for the sitemap."""
    urls = [SITE_BASE_URL]
    for page in PLUGIN_PAGES.values():
        urls.append(SITE_BASE_URL + page.lstrip("./"))
    if _tutorial_source_exists(root):
        rel = os.path.relpath(TUTORIAL_PAGE, SITE_OUT).replace(os.sep, "/")
        urls.append(SITE_BASE_URL + rel[: -len("index.html")])
    return urls


def render_sitemap(root):
    locs = "\n".join("  <url><loc>%s</loc></url>" % esc(url) for url in site_page_urls(root))
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            "%s\n</urlset>\n") % locs


def render_llms(root, manifest, claude_names=None):
    """An llms.txt (Markdown) front door for LLM crawlers: the marketplace summary, how to install,
    a list of plugins with links and descriptions, and the tutorial link (only when the tutorial
    source exists), all from the manifest. Per-plugin agent support comes from `claude_names` so a
    Copilot-only plugin (should one ever ship) is not listed as Claude-installable."""
    claude_names = claude_names or set()
    description = manifest.get("metadata", {}).get("description", "")
    suffix = manifest.get("name", "")
    lines = ["# " + SITE_NAME, "", "> " + description, ""]
    lines.append(
        "This marketplace works with both Claude Code and the GitHub Copilot CLI, and its skills "
        "are invokable from each agent's CLI and Desktop app. Add the marketplace once with "
        "`copilot plugin marketplace add %s` (or `claude plugin marketplace add %s`), then install a "
        "plugin with `copilot plugin install <name>@%s`; a Claude-installable plugin also supports "
        "`claude plugin install <name>@%s` (per-plugin support is noted below)."
        % (MARKETPLACE_GIT_URL, MARKETPLACE_GIT_URL, suffix, suffix))
    lines.extend(["", "## Plugins"])
    for plugin in manifest.get("plugins", []):
        agents = ("Claude Code and the GitHub Copilot CLI"
                  if plugin.get("name", "") in claude_names else "the GitHub Copilot CLI")
        lines.append("- [%s](%s) (%s): %s" % (
            plugin.get("name", ""), _plugin_app_url(plugin), agents, plugin.get("description", "")))
    if _tutorial_source_exists(root):
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


def build_skill_zip_members(root, skill_dir_rel, skill_name):
    """The ordered [(arcname, bytes)] contents of a skill ZIP: every file under the shipped skill
    directory, placed under a single top-level `<skill_name>/` folder (with SKILL.md at its root),
    which is the structure Claude Desktop / claude.ai skill import expects. Sorted by arcname so the
    archive is deterministic.

    Files are the git-TRACKED set (exactly what `plugin install` ships), so untracked developer
    noise (`.DS_Store`, `__pycache__`, editor temp files) can never leak into the committed ZIP and
    break a clean-checkout `--check`. Outside a git checkout it falls back to a filtered walk."""
    skill_dir = os.path.join(root, skill_dir_rel.replace("/", os.sep))
    if not os.path.isdir(skill_dir):
        raise SystemExit("Claude Desktop skill ZIP: skill directory is missing: %s" % skill_dir_rel)
    rels = _tracked_skill_files(root, skill_dir_rel)
    if rels is None:
        rels = _walk_skill_files(skill_dir)
    members = []
    for rel in sorted(rels):
        full = os.path.join(skill_dir, rel.replace("/", os.sep))
        if not os.path.isfile(full):
            continue
        with open(full, "rb") as fh:
            members.append(("%s/%s" % (skill_name, rel), fh.read()))
    members.sort(key=lambda m: m[0])
    if not any(arcname == "%s/SKILL.md" % skill_name for arcname, _ in members):
        raise SystemExit("Claude Desktop skill ZIP: %s has no SKILL.md at the root of %s"
                         % (skill_name, skill_dir_rel))
    return members


# Untracked developer noise that must never be packaged into a skill ZIP (the git-tracked path
# already excludes all of this; these apply only to the non-git filtered-walk fallback).
_SKILL_ZIP_SKIP_DIRS = {"__pycache__", ".git", "node_modules", ".idea", ".vscode",
                        ".pytest_cache", ".mypy_cache"}
_SKILL_ZIP_SKIP_NAMES = {".DS_Store", "Thumbs.db"}
_SKILL_ZIP_SKIP_SUFFIXES = (".pyc", ".pyo")


def _tracked_skill_files(root, skill_dir_rel):
    """The git-tracked files under the skill dir, relative to the skill dir (forward slashes), or
    None when git is unavailable or this is not a git checkout so the caller can fall back."""
    try:
        out = subprocess.run(["git", "-C", root, "ls-files", "-z", "--", skill_dir_rel],
                             capture_output=True, check=True).stdout.decode("utf-8")
    except (FileNotFoundError, subprocess.CalledProcessError, OSError):
        return None
    prefix = skill_dir_rel.rstrip("/") + "/"
    rels = [p[len(prefix):] for p in out.split("\0") if p and p.startswith(prefix)]
    return rels or None


def _walk_skill_files(skill_dir):
    """Fallback file enumeration for a skill dir outside a git checkout: a filtered walk that skips
    well-known untracked noise so the archive stays deterministic."""
    rels = []
    for dirpath, dirs, names in os.walk(skill_dir):
        dirs[:] = [d for d in dirs if d not in _SKILL_ZIP_SKIP_DIRS]
        for name in names:
            if name in _SKILL_ZIP_SKIP_NAMES or name.endswith(_SKILL_ZIP_SKIP_SUFFIXES):
                continue
            full = os.path.join(dirpath, name)
            rels.append(os.path.relpath(full, skill_dir).replace(os.sep, "/"))
    return rels


def _skill_zip_bytes(members):
    """A deterministic ZIP of `members`: fixed timestamps, permissions, and creator system, plus a
    stable member order, so a rebuild from the same skill files is reproducible across platforms."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for arcname, data in members:
            info = zipfile.ZipInfo(arcname, date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            info.create_system = 3  # Unix, so the host OS never changes the archive bytes.
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    return buf.getvalue()


def _zip_logical_members(path):
    """The logical {arcname -> uncompressed bytes} of a committed ZIP, or None when it is missing or
    cannot be read. Comparing logical members (not raw archive bytes) makes the --check drift guard
    immune to zlib/platform differences in the compressed container. A malformed, encrypted, or
    unsupported-compression archive is treated as unreadable (None) so --check flags it as stale and
    write mode repairs it, rather than crashing the build."""
    if not os.path.isfile(path):
        return None
    try:
        with zipfile.ZipFile(path, "r") as archive:
            return {info.filename: archive.read(info.filename) for info in archive.infolist()}
    except (OSError, zipfile.BadZipFile, NotImplementedError, RuntimeError):
        return None


def sync_skill_zips(root, check, skills=None):
    """Generate (or, in check mode, verify) a downloadable ZIP of each Claude-Desktop skill under
    site/dist/skills/. In check mode a stale or missing ZIP is drift (compared by logical contents,
    so compression/platform differences never cause a false failure). In write mode the ZIP is only
    rewritten when its logical contents changed, so an unchanged skill never produces a spurious
    multi-MB diff. An orphaned ZIP (its skill was removed) is flagged/deleted."""
    skills = list(DESKTOP_SKILLS.values()) if skills is None else skills
    dst_dir = os.path.join(root, SITE_OUT, "skills")
    drift = []
    written = []
    for descriptor in skills:
        zip_name = descriptor["zip"].split("/")[-1]
        written.append(zip_name)
        dst = os.path.join(dst_dir, zip_name)
        members = build_skill_zip_members(root, descriptor["skill_dir"], descriptor["skill"])
        expected = {arcname: data for arcname, data in members}
        if check:
            if _zip_logical_members(dst) != expected:
                drift.append(zip_name)
        elif _zip_logical_members(dst) != expected:
            _safe_makedirs(dst_dir)
            with open(dst, "wb") as fh:
                fh.write(_skill_zip_bytes(members))
    drift.extend(_orphans(dst_dir, set(written), check))
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

    if not os.path.isfile(manifest_path):
        raise SystemExit("manifest missing: %s (expected the marketplace manifest; pass --manifest "
                         "or restore it)" % manifest_path)
    with open(manifest_path, "r", encoding="utf-8") as fh:
        try:
            manifest = json.load(fh)
        except json.JSONDecodeError as exc:
            raise SystemExit("invalid JSON in manifest %s: %s" % (manifest_path, exc))

    # Assemble the served stylesheet from its source partials before anything stamps its hash.
    styles_text = build_styles(root)
    styles_path = os.path.join(root, SITE_OUT, "assets", "styles.css")
    if not args.check:
        write_text(styles_path, styles_text)
    static_drift = sync_static_assets(root, args.check)

    suffix = manifest.get("name", "")
    claude_names = claude_plugin_names(root)
    plugins_html = render_plugins(manifest, claude_names)
    changelog_html = render_changelog([])
    for path, filter_plugin in changelog_candidates(root, args.changelog):
        if not os.path.exists(path):
            continue
        releases = parse_changelog(read_text(path), filter_plugin)
        if releases:
            changelog_html = render_changelog(releases)
            break
    version = plugin_version(manifest, CHANGELOG_PLUGIN)
    updater_version = plugin_version(manifest, UPDATER_PLUGIN)

    for src_rel in (HUB_SRC, PLUGIN_SRC, UPDATER_SRC):
        if not os.path.isfile(os.path.join(root, src_rel)):
            raise SystemExit("page source missing: %s (a built page under site/dist/ has no source "
                             "to rebuild from; restore it)" % src_rel.replace(os.sep, "/"))

    hub_out = build_page(root, HUB_SRC, [
        ("block", "plugins", plugins_html),
        ("block", "install", render_install(
            "", suffix, bool(claude_names), "install-hub", marketplace_only=True)),
        ("block", "jsonld", render_jsonld(manifest, claude_names)),
    ])
    plugin_out = build_page(root, PLUGIN_SRC, [
        ("inline", "version", "v" + esc(version)),
        ("block", "install", render_install(
            CHANGELOG_PLUGIN, suffix, CHANGELOG_PLUGIN in claude_names, "install-cmh",
            desktop_zip=_desktop_install_args(CHANGELOG_PLUGIN, "../")[0],
            desktop_skill=_desktop_install_args(CHANGELOG_PLUGIN, "../")[1])),
        ("block", "changelog", changelog_html),
        ("inline", "demo-fullscreen", render_demo_fullscreen_link()),
    ])
    updater_out = build_page(root, UPDATER_SRC, [
        ("inline", "version", "v" + esc(updater_version)),
        ("block", "install", render_install(
            UPDATER_PLUGIN, suffix, UPDATER_PLUGIN in claude_names, "install-updater")),
        ("block", "changelog", render_plugin_changelog(root, UPDATER_PLUGIN)),
    ])
    hub_out_path = os.path.join(root, HUB_OUT)
    plugin_out_path = os.path.join(root, PLUGIN_OUT)
    updater_out_path = os.path.join(root, UPDATER_OUT)

    tutorial_src_page = os.path.join(root, TUTORIAL_PAGE_SRC)
    tutorial_out_path = os.path.join(root, TUTORIAL_PAGE)
    tutorial_md_path = os.path.join(root, TUTORIAL_SRC)
    tutorial_out = None
    # A built tutorial page whose source was removed is an ORPHAN: --check must flag it and a
    # normal build must delete it, so a stranded artifact can never silently linger.
    tutorial_orphaned = (not os.path.isfile(tutorial_src_page)
                         and os.path.isfile(tutorial_out_path))
    if os.path.isfile(tutorial_src_page):
        if not os.path.isfile(tutorial_md_path):
            raise SystemExit(
                "tutorial markdown missing: %s (restore it, or remove the tutorial source page it feeds)"
                % tutorial_md_path)
        tutorial_out = build_page(root, TUTORIAL_PAGE_SRC, [
            ("block", "tutorial",
             render_markdown(site_tutorial_markdown(read_text(tutorial_md_path)))),
        ])

    demo_drift = sync_demos(root, args.check)
    tutorial_img_drift = sync_tutorial_images(root, args.check)
    skill_zip_drift = sync_skill_zips(root, args.check)
    sitemap_drift = write_or_check(
        os.path.join(root, SITE_OUT, "sitemap.xml"), render_sitemap(root), args.check)
    llms_drift = write_or_check(
        os.path.join(root, SITE_OUT, "llms.txt"), render_llms(root, manifest, claude_names), args.check)

    if args.check:
        problems = []
        if static_drift:
            problems.append("static site assets differ from site/src/: " + ", ".join(static_drift))
        if styles_text != _read_artifact(styles_path):
            problems.append("site/dist/assets/styles.css is stale vs site/css/ partials")
        if hub_out != _read_artifact(hub_out_path):
            problems.append("site/dist/index.html is stale vs its site/pages/index.html source "
                            "(do not hand-edit the built page; edit the source and rebuild)")
        if plugin_out != _read_artifact(plugin_out_path):
            problems.append("site/dist/commentable-html/index.html is stale vs its "
                            "site/pages/commentable-html/index.html source "
                            "(do not hand-edit the built page; edit the source and rebuild)")
        if updater_out != _read_artifact(updater_out_path):
            problems.append("site/dist/%s/index.html is stale vs its "
                            "site/pages/%s/index.html source "
                            "(do not hand-edit the built page; edit the source and rebuild)"
                            % (UPDATER_PLUGIN, UPDATER_PLUGIN))
        if tutorial_out is not None and tutorial_out != _read_artifact(tutorial_out_path):
            problems.append("site/dist/commentable-html/tutorial/index.html is stale vs its "
                            "site/pages/commentable-html/tutorial/index.html source and "
                            "TUTORIAL.md (do not hand-edit the built page; edit the source and rebuild)")
        if tutorial_orphaned:
            problems.append("site/dist/commentable-html/tutorial/index.html is orphaned: its "
                            "site/pages source was removed but the built page lingers; "
                            "run build_site_data.py to remove it")
        if demo_drift:
            problems.append("demo reports differ from source: " + ", ".join(demo_drift))
        if tutorial_img_drift:
            problems.append("tutorial images differ from source: " + ", ".join(tutorial_img_drift))
        if skill_zip_drift:
            problems.append("Claude Desktop skill ZIP is stale or missing: "
                            + ", ".join(skill_zip_drift))
        if sitemap_drift:
            problems.append("site/dist/sitemap.xml is stale")
        if llms_drift:
            problems.append("site/dist/llms.txt is stale")
        if problems:
            for problem in problems:
                sys.stderr.write("drift: %s\n" % problem)
            sys.stderr.write("fix: run python scripts/build_site_data.py and commit\n")
            return 1
        print("site data up to date")
        return 0

    write_text(hub_out_path, hub_out)
    write_text(plugin_out_path, plugin_out)
    write_text(updater_out_path, updater_out)
    if tutorial_out is not None:
        write_text(tutorial_out_path, tutorial_out)
    elif tutorial_orphaned:
        try:
            os.remove(tutorial_out_path)
        except FileNotFoundError:
            pass
        except OSError as exc:
            sys.stderr.write("warning: could not remove orphaned tutorial page %s (%s); "
                             "delete it manually\n" % (tutorial_out_path, exc))
    print("site data generated (plugins, jsonld, version v%s, changelog, demos, tutorial, sitemap, llms)" % version)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
