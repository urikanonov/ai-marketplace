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
        category_badge = ('\n    <span class="badge">%s</span>' % esc(category_label(category))) if category else ""
        title = '<span class="name">%s</span>' % esc(name)
        if page:
            title = '<span class="name"><a href="%s">%s</a></span>' % (esc(page), esc(name))
        source = ('<a class="btn" href="%s">Source</a>' % esc(safe_url(homepage))) if homepage else ""
        learn_more = ('<a class="btn learn-more" href="%s">Learn more</a>' % esc(page)) if page else ""
        foot = learn_more + source
        actions = ('  <div class="foot">%s</div>\n' % foot) if foot else ""
        card = (
            '<article class="card plugin-card" id="plugin-%s">\n'
            '  <div class="head">\n'
            '    %s\n'
            '    <span class="badge version">v%s</span>%s\n'
            '  </div>\n'
            '  <p class="desc">%s</p>\n'
            '  <div class="keywords">%s</div>\n'
            '%s'
            '  <div class="install">\n'
            '    %s\n'
            '  </div>\n'
            '</article>'
        ) % (_slug_id(name), title, esc(version), category_badge, esc(description), chips,
             actions, install_block)
        cards.append(card)
    return "\n".join(cards)


def render_switcher(manifest, current_name, rel_prefix="../"):
    """The nav 'Marketplace' control on a plugin page: a link back to the hub that, on hover or
    keyboard focus, reveals a small flyout of tiles linking to the OTHER plugins, so a reader can
    jump straight between plugin pages without going through the hub. The current plugin is
    excluded, and only plugins that have their own generated page are listed. Returns an empty
    string when there is no other plugin to switch to. Tile labels come from PLUGIN_DISPLAY_NAMES
    (never containing the word 'Marketplace'), so the trigger link stays the only nav element with
    that text."""
    hub_href = esc(safe_url(rel_prefix or "./"))
    tiles = []
    for plugin in manifest.get("plugins", []):
        name = plugin.get("name", "")
        if not name or name == current_name or name not in PLUGIN_PAGES:
            continue
        label = PLUGIN_DISPLAY_NAMES.get(name, name)
        category = plugin.get("category", "")
        href = esc(safe_url(rel_prefix + name + "/"))
        icon = esc(safe_url(rel_prefix + "assets/" + name + ".svg"))
        sub = ('<span class="switch-tile-sub">%s</span>' % esc(category_label(category))) if category else ""
        tiles.append(
            '<a class="switch-tile" href="%s">'
            '<img class="switch-tile-icon" src="%s" alt="%s logo" />'
            '<span class="switch-tile-text"><span class="switch-tile-name">%s</span>%s</span>'
            '</a>' % (href, icon, esc(label), esc(label), sub))
    if not tiles:
        return ""
    tile_html = "\n      ".join(tiles)
    icon_svg = (
        '<svg class="nav-switcher-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/>'
        '<rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>'
        '</svg>')
    return (
        '<div class="nav-switcher">\n'
        '  <a class="nav-switcher-trigger" href="%s">%s<span>Marketplace</span></a>\n'
        '  <div class="nav-switcher-menu">\n'
        '    <span class="nav-switcher-heading">Switch plugin</span>\n'
        '    %s\n'
        '    <a class="switch-tile switch-tile-all" href="%s"><span class="switch-tile-text">'
        '<span class="switch-tile-name">All plugins</span>'
        '<span class="switch-tile-sub">Back to the hub</span></span></a>\n'
        '  </div>\n'
        '</div>'
    ) % (hub_href, icon_svg, tile_html, hub_href)


def _nav_grid_icon():
    """The 2x2 grid glyph shared by the plugin-page 'Marketplace' switcher and the hub 'Plugins'
    dropdown trigger, so the two nav controls read as the same kind of control."""
    return (
        '<svg class="nav-switcher-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/>'
        '<rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>'
        '</svg>')


def render_nav_plugins(manifest):
    """The hub nav 'Plugins' control: like the plugin-page 'Marketplace' switcher, but instead of
    linking to other plugin PAGES it lists every published plugin and, on hover or keyboard focus,
    reveals a flyout of tiles that scroll to each plugin's CARD on this page ('#plugin-<slug>'). The
    trigger itself stays a working link to the plugins SECTION ('#plugins'), so clicking it scrolls
    there exactly as the old plain link did (a pure-CSS progressive enhancement). The menu is
    left-aligned ('.nav-switcher-start') because 'Plugins' is the first nav item, so it opens to the
    right of the trigger. Tile labels come from PLUGIN_DISPLAY_NAMES; the per-plugin icon is shown
    only for a plugin that has its own page (and thus a committed brand SVG) so a link never 404s."""
    tiles = []
    for plugin in manifest.get("plugins", []):
        name = plugin.get("name", "")
        if not name:
            continue
        label = PLUGIN_DISPLAY_NAMES.get(name, name)
        category = plugin.get("category", "")
        href = "#plugin-" + _slug_id(name)
        sub = ('<span class="switch-tile-sub">%s</span>' % esc(category_label(category))) if category else ""
        if name in PLUGIN_PAGES:
            icon = esc(safe_url("assets/" + name + ".svg"))
            icon_html = '<img class="switch-tile-icon" src="%s" alt="%s logo" />' % (icon, esc(label))
        else:
            icon_html = ""
        tiles.append(
            '<a class="switch-tile" href="%s">'
            '%s'
            '<span class="switch-tile-text"><span class="switch-tile-name">%s</span>%s</span>'
            '</a>' % (esc(href), icon_html, esc(label), sub))
    if not tiles:
        return '<a href="#plugins">Plugins</a>'
    tile_html = "\n      ".join(tiles)
    return (
        '<div class="nav-switcher nav-switcher-start">\n'
        '  <a class="nav-switcher-trigger" href="#plugins">%s<span>Plugins</span></a>\n'
        '  <div class="nav-switcher-menu">\n'
        '    <span class="nav-switcher-heading">Jump to plugin</span>\n'
        '    %s\n'
        '    <a class="switch-tile switch-tile-all" href="#plugins"><span class="switch-tile-text">'
        '<span class="switch-tile-name">All plugins</span>'
        '<span class="switch-tile-sub">View the full list</span></span></a>\n'
        '  </div>\n'
        '</div>'
    ) % (_nav_grid_icon(), tile_html)


def render_hero_pills(manifest):
    """A row of hero pills under the CTAs, one per published plugin, each a link that scrolls to that
    plugin's card ('#plugin-<slug>'), so a reader can jump straight to a specific plugin from the
    top of the hub. Labels come from PLUGIN_DISPLAY_NAMES. Returns an empty string when there are no
    plugins so the hero simply omits the row."""
    pills = []
    for plugin in manifest.get("plugins", []):
        name = plugin.get("name", "")
        if not name:
            continue
        label = PLUGIN_DISPLAY_NAMES.get(name, name)
        href = "#plugin-" + _slug_id(name)
        pills.append('<a class="hero-pill" href="%s">%s</a>' % (esc(href), esc(label)))
    if not pills:
        return ""
    return ('<div class="hero-pills" aria-label="Jump to a plugin">\n      %s\n    </div>'
            % "\n      ".join(pills))


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
