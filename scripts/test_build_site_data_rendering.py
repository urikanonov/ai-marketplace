from build_site_data_test_support import *  # noqa: F401,F403
import build_site_data_test_support as _support
globals().update({k: v for k, v in vars(_support).items() if k.startswith("_") and not k.startswith("__")})

class SafeUrlTests(unittest.TestCase):
    def test_allows_https_relative_anchor_mailto(self):
        for url in ["https://example.com", "./x.html", "../a/b", "/root", "#frag", "mailto:a@b.c",
                    "index.html", "docs/page.html"]:
            self.assertEqual(bsd.safe_url(url), url)

    def test_neutralizes_dangerous_or_offsite(self):
        for url in ["//evil.example", "javascript:alert(1)", "data:text/html,x", "http://x", "ftp://x"]:
            self.assertEqual(bsd.safe_url(url), "#")

    def test_neutralizes_control_char_scheme_smuggling(self):
        for url in ["java\tscript:alert(1)", "\x00javascript:alert(1)", "\x00//evil.example",
                    "  javascript:alert(1)"]:
            self.assertEqual(bsd.safe_url(url), "#")

    def test_neutralizes_backslash_protocol_relative(self):
        for url in ["\\\\evil.example/a", "\\/evil.example", "/\\evil.example"]:
            self.assertEqual(bsd.safe_url(url), "#")
        self.assertEqual(bsd.safe_url("a\\b/c"), "a/b/c")

class MentionsPluginTests(unittest.TestCase):
    def test_anchored_case_insensitive(self):
        self.assertTrue(bsd.mentions_plugin("`commentable-html` 2.5.0 - x", "commentable-html"))
        self.assertTrue(bsd.mentions_plugin("Commentable-html - x", "commentable-html"))
        self.assertTrue(bsd.mentions_plugin("**commentable-html**: bolded", "commentable-html"))

    def test_rejects_midtext_and_other_plugins(self):
        self.assertFalse(bsd.mentions_plugin("see commentable-html for details", "commentable-html"))
        self.assertFalse(bsd.mentions_plugin("`other-plugin` 1.0.0 - x", "commentable-html"))

class CleanEntryTests(unittest.TestCase):
    def test_strips_name_and_optional_version(self):
        self.assertEqual(bsd.clean_entry("`commentable-html` 1.2.3 - did a thing", "commentable-html"),
                         "did a thing")
        self.assertEqual(bsd.clean_entry("commentable-html - no version here", "commentable-html"),
                         "no version here")

    def test_preserves_body_backticks_for_code_spans(self):
        self.assertEqual(bsd.clean_entry("`commentable-html` 1.2.3 - uses `code`", "commentable-html"),
                         "uses `code`")

    def test_no_filter_preserves_backticks(self):
        self.assertEqual(bsd.clean_entry("uses `code` here", None), "uses `code` here")

class ParseChangelogTests(unittest.TestCase):
    def test_root_format_filters_to_plugin(self):
        text = ("## [Unreleased]\n### Added\n"
                "- `commentable-html` 1.2.3 - kept\n"
                "- `other-plugin` 1.0.0 - dropped\n"
                "- mentions commentable-html mid text, dropped\n")
        releases = bsd.parse_changelog(text, "commentable-html")
        self.assertEqual(len(releases), 1)
        self.assertEqual(releases[0]["groups"]["Added"], ["kept"])

    def test_per_plugin_format_keeps_all_bullets(self):
        text = "## [1.0.0]\n### Added\n- First feature\n- Second feature\n"
        releases = bsd.parse_changelog(text, None)
        self.assertEqual(releases[0]["groups"]["Added"], ["First feature", "Second feature"])

    def test_ungrouped_bullets_are_not_dropped(self):
        text = "## [1.0.0]\n- Ungrouped item\n"
        releases = bsd.parse_changelog(text, None)
        self.assertEqual(releases[0]["groups"][""], ["Ungrouped item"])

    def test_continuation_lines_join(self):
        text = "## [1.0.0]\n### Added\n- First line\n  continues here\n"
        releases = bsd.parse_changelog(text, None)
        self.assertEqual(releases[0]["groups"]["Added"], ["First line continues here"])

class RenderPluginsTests(unittest.TestCase):
    def test_escapes_text_and_neutralizes_bad_homepage(self):
        manifest = {
            "name": "urikan-ai-marketplace",
            "plugins": [{
                "name": "x", "version": "1.0.0",
                "description": "<script>bad</script>", "keywords": ["a"],
                "homepage": "//evil.example",
            }],
        }
        out = bsd.render_plugins(manifest)
        self.assertNotIn("<script>bad", out)
        self.assertIn("&lt;script&gt;bad", out)
        self.assertNotIn('href="//evil.example"', out)

    def test_plugin_card_title_and_learn_more_link_to_page(self):
        manifest = {
            "name": "urikan-ai-marketplace",
            "plugins": [{
                "name": "commentable-html",
                "version": "1.0.0",
                "description": "Review HTML",
                "homepage": "https://example.com/source",
            }],
        }
        out = bsd.render_plugins(manifest)
        # The title is a keyboard-focusable link to the plugin page; CSS stretches it over the card.
        self.assertIn('<span class="name"><a href="./commentable-html/">commentable-html</a></span>', out)
        # The Learn more button also links to the page.
        self.assertIn('<a class="btn learn-more" href="./commentable-html/">Learn more</a>', out)
        # Two generated links (title + Learn more) point at the page; CSS supplies the stretched area.
        self.assertEqual(out.count('href="./commentable-html/"'), 2)
        # The Source link is still present and independent of the page links.
        self.assertIn('<a class="btn" href="https://example.com/source">Source</a>', out)
        self.assertNotIn("card-link", out)

    def test_card_without_page_has_no_learn_more(self):
        manifest = {
            "name": "urikan-ai-marketplace",
            "plugins": [{"name": "no-page", "version": "1.0.0", "description": "x"}],
        }
        out = bsd.render_plugins(manifest)
        self.assertNotIn("learn-more", out)
        self.assertIn('<span class="name">no-page</span>', out)

    def test_real_manifest_commentable_badge_and_chips(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, ".github", "plugin", "marketplace.json"),
                  encoding="utf-8") as fh:
            manifest = json.load(fh)
        out = bsd.render_plugins(manifest)
        # The commentable-html card badge renders the "planning and analysis" category.
        self.assertIn('<span class="badge">planning and analysis</span>', out)
        # The keyword chips include the cmh shorthand, analysis, plan, and report.
        for chip in ("cmh", "analysis", "plan", "report"):
            self.assertIn('<span class="chip">%s</span>' % chip, out)

    def test_card_install_shows_claude_tab_only_for_claude_plugins(self):
        manifest = {
            "name": "urikan-ai-marketplace",
            "plugins": [
                {"name": "commentable-html", "version": "1.0.0", "description": "d"},
                {"name": "auto-updater", "version": "1.0.0", "description": "d"},
            ],
        }
        out = bsd.render_plugins(manifest, claude_names={"commentable-html"})
        # The Claude-supported plugin's card offers a Claude tab and the claude install command...
        self.assertIn('id="install-card-commentable-html-claude-tab"', out)
        self.assertIn("claude plugin install commentable-html@urikan-ai-marketplace", out)
        # ...while the Copilot-only plugin's card has no Claude tab and no claude command.
        self.assertNotIn("install-card-auto-updater-claude", out)
        self.assertNotIn("claude plugin install auto-updater", out)

class RenderInstallTests(unittest.TestCase):
    URL = "https://github.com/urikanonov/ai-marketplace"

    def test_dual_agent_tabs_with_split_rows_and_per_row_copy(self):
        out = bsd.render_install("commentable-html", "urikan-ai-marketplace", True, "install-x")
        # A tab per agent, Copilot first and selected by default.
        self.assertIn("data-install-tabs", out)
        self.assertIn(">GitHub Copilot</button>", out)
        self.assertIn(">Claude Code</button>", out)
        self.assertIn('aria-selected="true"', out)
        # The marketplace-add and plugin-install commands are on SEPARATE, labelled rows.
        self.assertIn('<span class="install-label">Install marketplace</span>', out)
        self.assertIn('<span class="install-label">Install plugin</span>', out)
        # Each agent's rows use that agent's CLI binary.
        self.assertIn("copilot plugin marketplace add " + self.URL, out)
        self.assertIn("copilot plugin install commentable-html@urikan-ai-marketplace", out)
        self.assertIn("claude plugin marketplace add " + self.URL, out)
        self.assertIn("claude plugin install commentable-html@urikan-ai-marketplace", out)
        # Every command row carries its own copy button with the exact command (2 agents x 2 rows).
        self.assertEqual(out.count('class="copy-btn"'), 4)
        self.assertIn('data-copy="claude plugin install commentable-html@urikan-ai-marketplace"', out)

    def test_copilot_only_plugin_has_no_claude_tab_or_command(self):
        out = bsd.render_install("auto-updater", "urikan-ai-marketplace", False, "install-y")
        self.assertIn("install-solo", out)
        self.assertNotIn("install-tab", out)
        self.assertNotIn("data-install-tabs", out)
        self.assertNotIn("claude plugin", out)
        # Still split into a marketplace row and a plugin row, each independently copyable.
        self.assertIn('<span class="install-label">Install marketplace</span>', out)
        self.assertIn('<span class="install-label">Install plugin</span>', out)
        self.assertEqual(out.count('class="copy-btn"'), 2)

    def test_marketplace_only_block_omits_the_plugin_row_but_keeps_both_tabs(self):
        out = bsd.render_install("", "urikan-ai-marketplace", True, "install-hub",
                                 marketplace_only=True)
        self.assertIn('<span class="install-label">Install marketplace</span>', out)
        self.assertNotIn("Install plugin", out)
        self.assertIn(">GitHub Copilot</button>", out)
        self.assertIn(">Claude Code</button>", out)
        # A single-row block shows no step badges (they only number a multi-step flow).
        self.assertNotIn("install-step", out)

    def test_ids_are_unique_per_block_for_aria_wiring(self):
        out = bsd.render_install("commentable-html", "urikan-ai-marketplace", True,
                                 "install-card-commentable-html")
        self.assertIn('id="install-card-commentable-html-claude-tab"', out)
        self.assertIn('aria-controls="install-card-commentable-html-claude"', out)
        self.assertIn('data-install-target="install-card-commentable-html-claude"', out)

    def test_idbase_is_slugged_so_a_name_cannot_inject_into_id_attributes(self):
        # A plugin name is only schema-constrained to minLength, so a name with HTML-significant
        # characters must not break out of the id/aria attributes it derives.
        hostile = 'x" onmouseover="alert(1)'
        idbase = "install-card-" + hostile
        out = bsd.render_install("commentable-html", "urikan-ai-marketplace", True, idbase)
        # No attribute breakout: the hostile quote/space/parens are slugged, so no event-handler
        # attribute and no executable payload survive (the word "onmouseover" may remain only as an
        # inert id fragment, never as `onmouseover="..."`).
        self.assertNotIn('onmouseover="', out)
        self.assertNotIn("alert(1)", out)
        self.assertNotIn('"x"', out)
        expected_tab = bsd._slug_id(idbase) + "-copilot-tab"
        self.assertIn('id="%s"' % expected_tab, out)
        self.assertRegex(expected_tab, r"^[A-Za-z0-9_-]+$")

    def test_claude_desktop_tab_offers_a_zip_download_when_desktop_zip_set(self):
        # A skill plugin gains a third "Claude Desktop" tab whose panel is a ZIP download plus
        # import steps, alongside the two CLI tabs (SITE-INSTALL-05).
        out = bsd.render_install("commentable-html", "urikan-ai-marketplace", True,
                                 "install-cmh", desktop_zip="skills/commentable-html.zip",
                                 desktop_skill="commentable-html")
        self.assertIn("data-install-tabs", out)
        self.assertIn(">GitHub Copilot</button>", out)
        self.assertIn(">Claude Code</button>", out)
        self.assertIn(">Claude Desktop</button>", out)
        # The Desktop panel links to the skill ZIP as a download, not a CLI command row.
        self.assertIn('href="skills/commentable-html.zip"', out)
        self.assertIn("download", out)
        self.assertIn("install-download", out)
        # It tells the user where to import it (Settings > Features) without a CLI command.
        self.assertIn("Settings", out)

    def test_no_claude_desktop_tab_when_desktop_zip_is_absent(self):
        out = bsd.render_install("commentable-html", "urikan-ai-marketplace", True, "install-x")
        self.assertNotIn(">Claude Desktop</button>", out)
        self.assertNotIn("install-download", out)

    def test_marketplace_only_block_never_shows_a_desktop_tab(self):
        # The hub hero "add the marketplace" block is generic (no specific skill), so even if a
        # desktop_zip is passed it must not render a Desktop download tab.
        out = bsd.render_install("", "urikan-ai-marketplace", True, "install-hub",
                                 marketplace_only=True, desktop_zip="skills/commentable-html.zip",
                                 desktop_skill="commentable-html")
        self.assertNotIn(">Claude Desktop</button>", out)
        self.assertNotIn("install-download", out)

class ClaudePluginNamesTests(unittest.TestCase):
    def _write(self, tmp, obj):
        import os as _os
        d = _os.path.join(tmp, ".claude-plugin")
        _os.makedirs(d, exist_ok=True)
        with open(_os.path.join(d, "marketplace.json"), "w", encoding="utf-8") as fh:
            fh.write(obj if isinstance(obj, str) else json.dumps(obj))

    def test_reads_plugin_names(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, {"plugins": [{"name": "a"}, {"name": "b"}, {"noname": 1}]})
            self.assertEqual(bsd.claude_plugin_names(tmp), {"a", "b"})

    def test_missing_file_returns_empty(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(bsd.claude_plugin_names(tmp), set())

    def test_malformed_shapes_fail_closed_to_empty(self):
        import tempfile
        for bad in ("not json", "null", "[]", '{"plugins": null}',
                    '{"plugins": ["scalar", 3]}', '{"plugins": {}}',
                    '{"plugins": [{"name": []}]}', '{"plugins": [{"name": 3}]}'):
            with tempfile.TemporaryDirectory() as tmp:
                self._write(tmp, bad)
                self.assertEqual(bsd.claude_plugin_names(tmp), set(),
                                 "expected empty set for malformed input: %r" % bad)

class DemoFullscreenTests(unittest.TestCase):
    def test_link_accessible_name_announces_new_tab(self):
        out = bsd.render_demo_fullscreen_link()
        self.assertIn('target="_blank"', out)
        self.assertIn('rel="noopener noreferrer"', out)
        self.assertIn('aria-label="Open this demo full screen in a new tab"', out)

class RenderMarkdownTests(unittest.TestCase):
    def test_headings_offset_lists_bold_code(self):
        html = bsd.render_markdown("# Title\n\n## Sub\n\n- a\n- b\n\n1. x\n2. y\n\n**bold** and `code`.")
        self.assertIn("<h2>Title</h2>", html)
        self.assertIn("<h3>Sub</h3>", html)
        self.assertIn("<li>a</li>", html)
        self.assertIn("<li>x</li>", html)
        self.assertIn("<strong>bold</strong>", html)
        self.assertIn("<code>code</code>", html)

    def test_code_span_not_bolded(self):
        html = bsd.render_markdown("`a**b**c`")
        self.assertIn("<code>a**b**c</code>", html)
        self.assertNotIn("<strong>", html)

    def test_fenced_code_block_escaped(self):
        html = bsd.render_markdown("```\n<script>bad()</script>\n```")
        self.assertIn("<pre><code>", html)
        self.assertIn("&lt;script&gt;bad", html)
        self.assertNotIn("<script>bad", html)

    def test_image_and_link_render(self):
        html = bsd.render_markdown("![alt text](tutorial-images/a.png)\n\n[link](https://example.com)")
        self.assertIn('<img src="tutorial-images/a.png" alt="alt text" loading="lazy" />', html)
        self.assertIn('<a href="https://example.com">link</a>', html)

    def test_link_url_single_escaped(self):
        html = bsd.render_markdown("[q](https://x.example/?a=1&b=2)")
        self.assertIn('href="https://x.example/?a=1&amp;b=2"', html)
        self.assertNotIn("&amp;amp;", html)

    def test_xss_neutralized_in_alt_and_raw_html(self):
        html = bsd.render_markdown('![x" onerror="alert(1)](tutorial-images/a.png)')
        self.assertNotIn('onerror="alert(1)"', html)
        self.assertIn("&quot;", html)
        html2 = bsd.render_markdown("<script>alert(1)</script>")
        self.assertNotIn("<script>alert(1)</script>", html2)
        self.assertIn("&lt;script&gt;", html2)

    def test_dangerous_link_scheme_neutralized(self):
        self.assertIn('href="#"', bsd.render_markdown("[x](javascript:alert(1))"))

class ChangelogInlineTests(unittest.TestCase):
    def test_bullets_render_inline_markdown(self):
        html = bsd.render_changelog([{"name": "[1.0.0]", "groups": {"Added": ["Now **bold** and `code`"]}}])
        self.assertIn("<strong>bold</strong>", html)
        self.assertIn("<code>code</code>", html)
        self.assertNotIn("**bold**", html)

    def test_end_to_end_preserves_code_spans(self):
        text = "## [1.0.0]\n### Added\n- Bounded inside `figure.chart` at narrow widths.\n"
        html = bsd.render_changelog(bsd.parse_changelog(text, None))
        self.assertIn("<code>figure.chart</code>", html)

    def test_latest_two_expanded_rest_collapsed(self):
        releases = [{"name": "[%d.0.0]" % n, "groups": {"Added": ["item"]}}
                    for n in (5, 4, 3, 2, 1)]
        html = bsd.render_changelog(releases)
        self.assertIn('<details class="older-releases">', html)
        self.assertIn("<summary>Show 3 older releases</summary>", html)
        # The two newest releases render before the collapsible section.
        self.assertLess(html.index("[5.0.0]"), html.index("<details"))
        self.assertLess(html.index("[4.0.0]"), html.index("<details"))
        self.assertGreater(html.index("[3.0.0]"), html.index("<details"))

    def test_no_details_when_two_or_fewer_releases(self):
        releases = [{"name": "[2.0.0]", "groups": {"Added": ["a"]}},
                    {"name": "[1.0.0]", "groups": {"Added": ["b"]}}]
        html = bsd.render_changelog(releases)
        self.assertNotIn("<details", html)

    def test_single_older_release_uses_singular(self):
        releases = [{"name": "[%d.0.0]" % n, "groups": {"Added": ["item"]}}
                    for n in (3, 2, 1)]
        html = bsd.render_changelog(releases)
        self.assertIn("<summary>Show 1 older release</summary>", html)

    def test_older_releases_capped_and_rest_linked_to_source(self):
        # 2 expanded + 5 collapsed = 7 rendered; anything older is not rendered but is
        # linked to the full changelog in source so the page never grows without bound.
        releases = [{"name": "[1.%d.0]" % n, "groups": {"Added": ["item"]}}
                    for n in range(9, -1, -1)]  # 10 releases
        html = bsd.render_changelog(releases)
        self.assertIn("<summary>Show 5 older releases</summary>", html)
        self.assertIn(bsd.CHANGELOG_GITHUB_URL, html)
        self.assertIn("3 earlier releases", html)
        # The three oldest releases are not rendered inline.
        self.assertNotIn("[1.2.0]", html)
        self.assertNotIn("[1.0.0]", html)

class MdInlineTests(unittest.TestCase):
    def test_code_span_stays_literal_not_a_link(self):
        html = bsd._md_inline(bsd.esc("`[x](https://example.com)`"))
        self.assertIn("<code>[x](https://example.com)</code>", html)
        self.assertNotIn("<a ", html)

    def test_bold_in_url_does_not_corrupt_href(self):
        html = bsd._md_inline(bsd.esc("[x](https://e.com/**a**)"))
        self.assertIn('href="https://e.com/**a**"', html)
        self.assertNotIn("<strong>", html)

    def test_bold_in_link_text_is_rendered(self):
        html = bsd._md_inline(bsd.esc("[**bold**](https://e.com)"))
        self.assertIn("<strong>bold</strong>", html)
        self.assertIn('href="https://e.com"', html)

    def test_code_span_inside_link_text_is_restored(self):
        html = bsd._md_inline(bsd.esc("[`code`](https://e.com)"))
        self.assertIn('<a href="https://e.com"><code>code</code></a>', html)

    def test_nul_sentinel_in_source_cannot_collide(self):
        html = bsd._md_inline(bsd.esc("before \x00\x000\x00 `x` after"))
        self.assertIn("<code>x</code>", html)
        self.assertNotIn("\x00", html)

class RenderMarkdownOrderingTests(unittest.TestCase):
    def test_paragraph_after_list_closes_the_list_first(self):
        html = bsd.render_markdown("- item\ntrailing paragraph")
        self.assertLess(html.index("</ul>"), html.index("<p>trailing paragraph</p>"))

    def test_unclosed_code_fence_is_emitted_at_eof(self):
        html = bsd.render_markdown("before\n\n```\ncode line")
        self.assertIn("<pre><code>code line</code></pre>", html)

class ReplaceRegionTests(unittest.TestCase):
    BLOCK = "x\n  <!-- BEGIN:r -->\n  old\n  <!-- END:r -->\ny"
    INLINE = "a<!-- BEGIN:v -->old<!-- END:v -->b"

    def test_block_replaces_single_region(self):
        out = bsd.replace_region_block(self.BLOCK, "r", "new")
        self.assertIn("  new\n", out)
        self.assertNotIn("old", out)

    def test_block_missing_region_exits(self):
        with self.assertRaises(SystemExit):
            bsd.replace_region_block("no markers here", "r", "new")

    def test_block_duplicate_region_exits(self):
        dup = self.BLOCK + "\n" + self.BLOCK
        with self.assertRaises(SystemExit):
            bsd.replace_region_block(dup, "r", "new")

    def test_inline_replaces_and_guards(self):
        self.assertEqual(bsd.replace_region_inline(self.INLINE, "v", "NEW"),
                         "a<!-- BEGIN:v -->NEW<!-- END:v -->b")
        with self.assertRaises(SystemExit):
            bsd.replace_region_inline("none", "v", "NEW")
        with self.assertRaises(SystemExit):
            bsd.replace_region_inline(self.INLINE + self.INLINE, "v", "NEW")

class ChangelogCandidatesTests(unittest.TestCase):
    def test_only_per_plugin_source_no_root(self):
        cands = bsd.changelog_candidates("/repo", None)
        self.assertEqual(len(cands), 1)
        path, filter_plugin = cands[0]
        self.assertIsNone(filter_plugin)
        self.assertNotIn("repo" + __import__("os").sep + "CHANGELOG.md", path)
        self.assertIn(bsd.CHANGELOG_PLUGIN, path)

    def test_explicit_override_uses_per_plugin_format(self):
        self.assertEqual(bsd.changelog_candidates("/repo", "/tmp/CL.md"), [("/tmp/CL.md", None)])

class SiteTutorialMarkdownTests(unittest.TestCase):
    def test_rewrites_local_example_links_to_demo(self):
        md = ("Open [`examples/report-community-garden.html`](../examples/report-community-garden.html) "
              "then [`examples/report-taxi.html`](../examples/report-taxi.html).")
        out = bsd.site_tutorial_markdown(md)
        # The link target is rewritten to the live demo page the site hosts...
        self.assertIn("(../demo/report-community-garden.html)", out)
        self.assertIn("(../demo/report-taxi.html)", out)
        # ...while the skill-root-relative display text (with no `..`) is preserved.
        self.assertIn("`examples/report-community-garden.html`", out)
        self.assertNotIn("../examples/", out)

class JsonLdTests(unittest.TestCase):
    def _parse(self, script):
        self.assertTrue(script.startswith('<script type="application/ld+json">'))
        self.assertTrue(script.rstrip().endswith("</script>"))
        inner = script[script.index(">") + 1: script.rindex("</script>")]
        return json.loads(inner)

    def test_graph_has_website_person_and_plugin_itemlist(self):
        manifest = {
            "name": "urikan-ai-marketplace",
            "metadata": {"description": "Desc."},
            "owner": {"name": "Uri Kanonov"},
            "plugins": [
                {"name": "commentable-html", "description": "d1"},
                {"name": "other", "description": "d2",
                 "homepage": "https://github.com/urikanonov/ai-marketplace"},
            ],
        }
        graph = self._parse(bsd.render_jsonld(manifest))["@graph"]
        self.assertEqual([n["@type"] for n in graph], ["WebSite", "Person", "ItemList"])
        website, person, itemlist = graph
        self.assertEqual(website["author"]["@id"], person["@id"])
        self.assertIn(bsd.OWNER_LINKEDIN_URL, person["sameAs"])
        apps = [li["item"] for li in itemlist["itemListElement"]]
        self.assertEqual([a["name"] for a in apps], ["commentable-html", "other"])
        # A plugin with a site page links to it; one without falls back to its homepage.
        self.assertEqual(apps[0]["url"], bsd.SITE_BASE_URL + "commentable-html/")
        self.assertEqual(apps[1]["url"], "https://github.com/urikanonov/ai-marketplace")
        self.assertTrue(all(a["applicationCategory"] == "DeveloperApplication" for a in apps))

    def test_script_break_out_is_neutralized(self):
        manifest = {"name": "m", "metadata": {"description": "x</script><b>y"},
                    "owner": {"name": "O"}, "plugins": []}
        script = bsd.render_jsonld(manifest)
        self.assertNotIn("</script><b>", script)
        self.assertIn("\\u003c/script\\u003e", script)
        self.assertEqual(self._parse(script)["@graph"][0]["description"], "x</script><b>y")

    def test_real_manifest_parses_and_lists_both_plugins(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, ".github", "plugin", "marketplace.json"), encoding="utf-8") as fh:
            manifest = json.load(fh)
        itemlist = self._parse(bsd.render_jsonld(manifest))["@graph"][2]
        names = [li["item"]["name"] for li in itemlist["itemListElement"]]
        self.assertIn("commentable-html", names)
        self.assertIn("urikan-ai-marketplace-auto-updater", names)

    def test_operating_system_names_both_agents(self):
        # Per-plugin: a Claude-installable plugin names both agents; a Copilot-only plugin
        # (not in claude_names) must NOT be advertised as Claude-installable.
        manifest = {"name": "m", "metadata": {"description": "d"}, "owner": {"name": "O"},
                    "plugins": [{"name": "commentable-html", "description": "d1"},
                                {"name": "auto-updater", "description": "d2"}]}
        apps = [li["item"] for li in
                self._parse(bsd.render_jsonld(manifest, {"commentable-html"}))["@graph"][2]["itemListElement"]]
        self.assertEqual(apps[0]["operatingSystem"],
                         "Cross-platform (Claude Code, GitHub Copilot CLI)")
        self.assertEqual(apps[1]["operatingSystem"],
                         "Cross-platform (GitHub Copilot CLI)")

class SitemapTests(unittest.TestCase):
    def test_lists_hub_plugin_and_tutorial(self):
        xml = bsd.render_sitemap(bsd.REPO_ROOT)
        self.assertTrue(xml.startswith('<?xml version="1.0" encoding="UTF-8"?>'))
        self.assertIn("<urlset", xml)
        for url in [bsd.SITE_BASE_URL,
                    bsd.SITE_BASE_URL + "commentable-html/",
                    bsd.SITE_BASE_URL + "commentable-html/tutorial/"]:
            self.assertIn("<loc>%s</loc>" % url, xml)

class LlmsTests(unittest.TestCase):
    def test_contains_summary_install_and_plugin_links(self):
        manifest = {
            "name": "urikan-ai-marketplace",
            "metadata": {"description": "Marketplace summary."},
            "plugins": [{"name": "commentable-html", "description": "d1"}],
        }
        # REPO_ROOT has the tutorial source, so the Documentation link is emitted (gating verified
        # separately in CheckDriftTests.test_removing_tutorial_source_drops_its_llms_link).
        text = bsd.render_llms(bsd.REPO_ROOT, manifest, {"commentable-html"})
        self.assertTrue(text.startswith("# ai-marketplace"))
        self.assertIn("> Marketplace summary.", text)
        self.assertIn("copilot plugin install <name>@urikan-ai-marketplace", text)
        self.assertIn("[commentable-html](%scommentable-html/) (Claude Code and the GitHub Copilot CLI): d1"
                      % bsd.SITE_BASE_URL, text)
        self.assertIn("commentable-html/tutorial/)", text)

    def test_states_both_agents_and_their_install_commands(self):
        manifest = {"name": "urikan-ai-marketplace", "metadata": {"description": "d"},
                    "plugins": [{"name": "commentable-html", "description": "d1"},
                                {"name": "auto-updater", "description": "d2"}]}
        text = bsd.render_llms(bsd.REPO_ROOT, manifest, {"commentable-html"})
        self.assertIn("Claude Code and the GitHub Copilot CLI", text)
        self.assertIn("claude plugin marketplace add", text)
        self.assertIn("claude plugin install <name>@urikan-ai-marketplace", text)
        self.assertIn("copilot plugin install <name>@urikan-ai-marketplace", text)
        # Per-plugin agent labels: the Claude-installable plugin names both agents; the
        # Copilot-only plugin is labelled Copilot-only (not advertised for Claude).
        self.assertIn("[commentable-html](%scommentable-html/) (Claude Code and the GitHub Copilot CLI)"
                      % bsd.SITE_BASE_URL, text)
        self.assertRegex(text, r"\[auto-updater\]\([^)]+\) \(the GitHub Copilot CLI\)")

class AutoUpdaterPageTests(unittest.TestCase):
    """The auto-updater plugin has its own generated site page (SITE-UPDATER-01..04): its hub card
    links to that page and the page is wired into the sitemap, llms.txt, and hub JSON-LD."""

    UPDATER = "urikan-ai-marketplace-auto-updater"
    PAGE = "./urikan-ai-marketplace-auto-updater/"

    def _real_manifest(self):
        with open(os.path.join(bsd.REPO_ROOT, ".github", "plugin", "marketplace.json"),
                  encoding="utf-8") as fh:
            return json.load(fh)

    def _jsonld_graph(self, script):
        inner = script[script.index(">") + 1: script.rindex("</script>")]
        return json.loads(inner)["@graph"]

    def test_plugin_pages_includes_the_auto_updater(self):
        self.assertEqual(bsd.PLUGIN_PAGES.get(self.UPDATER), self.PAGE)

    def test_render_plugins_links_the_auto_updater_card_to_its_page(self):
        out = bsd.render_plugins(self._real_manifest())
        self.assertIn(
            '<span class="name"><a href="%s">%s</a></span>' % (self.PAGE, self.UPDATER), out)
        self.assertIn('<a class="btn learn-more" href="%s">Learn more</a>' % self.PAGE, out)

    def test_sitemap_lists_the_auto_updater_page(self):
        xml = bsd.render_sitemap(bsd.REPO_ROOT)
        self.assertIn("<loc>%s%s/</loc>" % (bsd.SITE_BASE_URL, self.UPDATER), xml)

    def test_llms_links_the_auto_updater_page(self):
        text = bsd.render_llms(bsd.REPO_ROOT, self._real_manifest())
        self.assertIn("[%s](%s%s/)" % (self.UPDATER, bsd.SITE_BASE_URL, self.UPDATER), text)

    def test_jsonld_uses_the_auto_updater_site_page_url(self):
        graph = self._jsonld_graph(bsd.render_jsonld(self._real_manifest()))
        itemlist = next(n for n in graph if n["@type"] == "ItemList")
        urls = {li["item"]["name"]: li["item"]["url"] for li in itemlist["itemListElement"]}
        self.assertEqual(urls[self.UPDATER], bsd.SITE_BASE_URL + self.UPDATER + "/")

    def test_render_plugin_changelog_renders_updater_releases(self):
        # The auto-updater CHANGELOG.md now lives at the plugin root and is rendered on its page.
        html = bsd.render_plugin_changelog(bsd.REPO_ROOT, self.UPDATER)
        self.assertIn('class="release"', html)
        self.assertIn("[1.1.0]", html)

class WriteOrCheckTests(unittest.TestCase):
    def test_writes_then_reports_drift_only_on_change(self):
        import shutil
        import tempfile
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        path = os.path.join(d, "sitemap.xml")
        self.assertEqual(bsd.write_or_check(path, "a\nb\n", False), [])
        self.assertEqual(bsd.write_or_check(path, "a\nb\n", True), [])
        self.assertEqual(bsd.write_or_check(path, "a\nc\n", True), ["sitemap.xml"])
        self.assertEqual(bsd.write_or_check(os.path.join(d, "gone.txt"), "x", True), ["gone.txt"])
