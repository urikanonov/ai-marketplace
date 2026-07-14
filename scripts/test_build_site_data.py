"""Unit tests for scripts/build_site_data.py.

Run by the validate CI job via `python -m unittest discover -s scripts -p "test_*.py"`,
so the site generator's escaping, URL allowlist, and changelog parsing are covered by a
required status check.
"""
import json
import os
import re
import tempfile
import unittest
from unittest import mock

import build_site_data as bsd


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
        # The keyword chips include analysis, plan, and report.
        for chip in ("analysis", "plan", "report"):
            self.assertIn('<span class="chip">%s</span>' % chip, out)


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


class SyncOrphanTests(unittest.TestCase):
    def test_orphan_flagged_then_removed(self):
        import os as _os
        import tempfile
        base = tempfile.mkdtemp()
        dst = _os.path.join(base, "dst")
        _os.makedirs(dst)
        open(_os.path.join(dst, "keep.png"), "wb").close()
        open(_os.path.join(dst, "orphan.png"), "wb").close()
        drift = bsd._orphans(dst, ["keep.png"], check=True)
        self.assertTrue(any("orphan.png" in item for item in drift))
        bsd._orphans(dst, ["keep.png"], check=False)
        self.assertFalse(_os.path.exists(_os.path.join(dst, "orphan.png")))
        self.assertTrue(_os.path.exists(_os.path.join(dst, "keep.png")))

    def test_orphans_reported_in_sorted_order(self):
        # Determinism: the orphan sweep must report drift in a stable, sorted order regardless
        # of the order os.listdir happens to return, so `--check` output and CI logs never flip
        # across platforms. Reverting the sorted() around the directory scan turns this red.
        names = ["c.html", "a.html", "b.html"]
        with tempfile.TemporaryDirectory() as d:
            for name in names:
                open(os.path.join(d, name), "wb").close()
            with mock.patch.object(bsd.os, "listdir", return_value=list(names)):
                drift = bsd._orphans(d, [], check=True)
        self.assertEqual(drift, ["a.html (orphaned)", "b.html (orphaned)", "c.html (orphaned)"])


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


class SyncDemosDriftTests(unittest.TestCase):
    def _make_root(self):
        import os as _os
        import tempfile
        root = tempfile.mkdtemp()
        src = _os.path.join(root, bsd.EXAMPLES_REL)
        dst = _os.path.join(root, bsd.DEMO_REL)
        _os.makedirs(src)
        _os.makedirs(dst)
        for name in bsd.DEMO_FILES:
            with open(_os.path.join(src, name), "wb") as fh:
                fh.write(b"<html>source " + name.encode() + b"</html>\n")
        return root, src, dst

    def test_content_difference_flagged_then_synced(self):
        import os as _os
        root, _src, dst = self._make_root()
        with open(_os.path.join(dst, bsd.DEMO_FILES[0]), "wb") as fh:
            fh.write(b"<html>STALE</html>\n")
        drift = bsd.sync_demos(root, check=True)
        self.assertIn(bsd.DEMO_FILES[0], drift)
        self.assertFalse(bsd.sync_demos(root, check=False))
        self.assertFalse(bsd.sync_demos(root, check=True))

    def test_missing_destination_flagged(self):
        root, _src, _dst = self._make_root()
        drift = bsd.sync_demos(root, check=True)
        self.assertEqual(sorted(drift), sorted(bsd.DEMO_FILES))


class SyncTutorialImagesTests(unittest.TestCase):
    def _make_root(self, with_src=True):
        import os as _os
        import tempfile
        root = tempfile.mkdtemp()
        if with_src:
            src = _os.path.join(root, bsd.TUTORIAL_IMAGES_SRC)
            _os.makedirs(src)
            with open(_os.path.join(src, "a.png"), "wb") as fh:
                fh.write(b"IMG-A")
        _os.makedirs(_os.path.join(root, bsd.TUTORIAL_IMAGES_DST))
        return root

    def test_content_difference_flagged_then_synced(self):
        import os as _os
        root = self._make_root()
        dst = _os.path.join(root, bsd.TUTORIAL_IMAGES_DST)
        with open(_os.path.join(dst, "a.png"), "wb") as fh:
            fh.write(b"STALE")
        self.assertIn("a.png", bsd.sync_tutorial_images(root, check=True))
        self.assertFalse(bsd.sync_tutorial_images(root, check=False))
        self.assertFalse(bsd.sync_tutorial_images(root, check=True))

    def test_orphan_removed_when_source_file_gone(self):
        import os as _os
        root = self._make_root()
        dst = _os.path.join(root, bsd.TUTORIAL_IMAGES_DST)
        bsd.sync_tutorial_images(root, check=False)
        with open(_os.path.join(dst, "gone.png"), "wb") as fh:
            fh.write(b"ORPHAN")
        self.assertTrue(any("gone.png" in d for d in bsd.sync_tutorial_images(root, check=True)))
        bsd.sync_tutorial_images(root, check=False)
        self.assertFalse(_os.path.exists(_os.path.join(dst, "gone.png")))
        self.assertTrue(_os.path.exists(_os.path.join(dst, "a.png")))

    def test_missing_source_dir_orphans_committed_images(self):
        import os as _os
        root = self._make_root(with_src=False)
        dst = _os.path.join(root, bsd.TUTORIAL_IMAGES_DST)
        with open(_os.path.join(dst, "stale.png"), "wb") as fh:
            fh.write(b"X")
        self.assertTrue(any("stale.png" in d for d in bsd.sync_tutorial_images(root, check=True)))
        bsd.sync_tutorial_images(root, check=False)
        self.assertFalse(_os.path.exists(_os.path.join(dst, "stale.png")))


class StampAssetsTests(unittest.TestCase):
    def test_stamps_css_and_js_with_content_hash_at_every_prefix(self):
        css = bsd._asset_hash(bsd.REPO_ROOT, "styles.css")
        js = bsd._asset_hash(bsd.REPO_ROOT, "site.js")
        html = ('<link rel="stylesheet" href="assets/styles.css" />\n'
                '<link rel="stylesheet" href="../assets/styles.css" />\n'
                '<script src="../../assets/site.js"></script>')
        out = bsd.stamp_assets(html, bsd.REPO_ROOT)
        self.assertIn('href="assets/styles.css?v=%s"' % css, out)
        self.assertIn('href="../assets/styles.css?v=%s"' % css, out)
        self.assertIn('src="../../assets/site.js?v=%s"' % js, out)

    def test_replaces_an_existing_stale_stamp(self):
        css = bsd._asset_hash(bsd.REPO_ROOT, "styles.css")
        out = bsd.stamp_assets('<link href="assets/styles.css?v=deadbeef" />', bsd.REPO_ROOT)
        self.assertIn('href="assets/styles.css?v=%s"' % css, out)
        self.assertNotIn("deadbeef", out)

    def test_is_idempotent(self):
        html = '<link href="../../assets/styles.css" /><script src="../../assets/site.js"></script>'
        once = bsd.stamp_assets(html, bsd.REPO_ROOT)
        self.assertEqual(once, bsd.stamp_assets(once, bsd.REPO_ROOT))

    def test_leaves_other_assets_untouched(self):
        html = '<link rel="icon" href="../assets/commentable-html.svg" />'
        self.assertEqual(bsd.stamp_assets(html, bsd.REPO_ROOT), html)

    def test_replaces_any_existing_query_or_fragment(self):
        css = bsd._asset_hash(bsd.REPO_ROOT, "styles.css")
        for ref in ["assets/styles.css?v=ABC123&t=1", "../assets/styles.css?foo=bar",
                    "assets/styles.css#frag"]:
            out = bsd.stamp_assets('<link href="%s" />' % ref, bsd.REPO_ROOT)
            self.assertRegex(out, r'href="(?:\.\./)*assets/styles\.css\?v=%s"' % css)
            for stale in ("ABC123", "foo=bar", "#frag"):
                self.assertNotIn(stale, out)

    def test_matches_dot_slash_prefix(self):
        css = bsd._asset_hash(bsd.REPO_ROOT, "styles.css")
        out = bsd.stamp_assets('<link href="./assets/styles.css" />', bsd.REPO_ROOT)
        self.assertIn('href="./assets/styles.css?v=%s"' % css, out)


class StampWiringTests(unittest.TestCase):
    PAGES = ["site/index.html", "site/commentable-html/index.html",
             "site/commentable-html/tutorial/index.html"]

    def test_committed_pages_carry_current_asset_stamps(self):
        import os as _os
        css = bsd._asset_hash(bsd.REPO_ROOT, "styles.css")
        js = bsd._asset_hash(bsd.REPO_ROOT, "site.js")
        for rel in self.PAGES:
            text = bsd.read_text(_os.path.join(bsd.REPO_ROOT, *rel.split("/")))
            self.assertIn("styles.css?v=%s" % css, text)
            self.assertIn("site.js?v=%s" % js, text)

    def test_no_site_html_has_a_stale_or_unstamped_asset_ref(self):
        import os as _os
        import glob
        want = {name: "?v=" + bsd._asset_hash(bsd.REPO_ROOT, name) for name in bsd.CACHE_BUSTED_ASSETS}
        alternation = "|".join(re.escape(name) for name in bsd.CACHE_BUSTED_ASSETS)
        pat = re.compile(r'(?:href|src)="[^"]*?assets/(%s)([^"]*)"' % alternation)
        bad = []
        for path in sorted(glob.glob(_os.path.join(bsd.REPO_ROOT, "site", "**", "*.html"), recursive=True)):
            for m in pat.finditer(bsd.read_text(path)):
                if m.group(2) != want[m.group(1)]:
                    bad.append(_os.path.relpath(path, bsd.REPO_ROOT) + ": " + m.group(0))
        self.assertEqual(bad, [])


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
        text = bsd.render_llms(bsd.REPO_ROOT, manifest)
        self.assertTrue(text.startswith("# ai-marketplace"))
        self.assertIn("> Marketplace summary.", text)
        self.assertIn("copilot plugin install <name>@urikan-ai-marketplace", text)
        self.assertIn("[commentable-html](%scommentable-html/): d1" % bsd.SITE_BASE_URL, text)
        self.assertIn("commentable-html/tutorial/)", text)


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


class CheckDriftTests(unittest.TestCase):
    # Building the clone is the dominant cost of this suite (~17 tests each copied every tracked
    # file, including the large vendored dev/ subtree that build_site_data.py never reads). Build a
    # filtered template ONCE per class (one git call, dev/ and dist/ excluded) and copytree from that
    # warm local template per test - same inputs build_site_data needs, a fraction of the bytes.
    _template = None
    _template_ok = False

    @classmethod
    def setUpClass(cls):
        import os as _os
        import shutil
        import subprocess
        import tempfile
        try:
            tracked = subprocess.run(["git", "-C", bsd.REPO_ROOT, "ls-files", "-z"],
                                     capture_output=True, check=True).stdout.decode("utf-8").split("\0")
        except (FileNotFoundError, subprocess.CalledProcessError):
            cls._template_ok = False
            return
        cls._template = tempfile.mkdtemp(prefix="cmh-site-template-")
        for rel in tracked:
            if not rel:
                continue
            # build_site_data.py reads site-src/, the plugins' pkg changelogs/docs/examples, and the
            # marketplace manifest - never plugins/*/dev/** or the generated dist/ bundles.
            if "/dev/" in rel or rel.endswith("/dev") or "/dist/" in rel:
                continue
            src = _os.path.join(bsd.REPO_ROOT, rel.replace("/", _os.sep))
            if not _os.path.isfile(src):
                continue
            dst = _os.path.join(cls._template, rel.replace("/", _os.sep))
            _os.makedirs(_os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
        cls._template_ok = True

    @classmethod
    def tearDownClass(cls):
        import shutil
        if cls._template:
            shutil.rmtree(cls._template, ignore_errors=True)

    def _clone_repo(self):
        import shutil
        import tempfile
        if not self._template_ok:
            self.skipTest("git not available on PATH; cannot clone the repo for this test")
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        shutil.copytree(self._template, root, dirs_exist_ok=True)
        return root

    def test_check_flags_a_stale_asset_stamp(self):
        import os as _os
        root = self._clone_repo()
        self.assertEqual(bsd.main(["build_site_data.py", "--root", root]), 0)
        self.assertEqual(bsd.main(["build_site_data.py", "--check", "--root", root]), 0)
        with open(_os.path.join(root, "site", "assets", "styles.css"), "a", encoding="utf-8") as fh:
            fh.write("\n/* mutate without regenerating */\n")
        self.assertEqual(bsd.main(["build_site_data.py", "--check", "--root", root]), 1)

    def test_check_flags_a_hand_edited_built_page(self):
        # The clobber guard, end to end through the real CLI: a hand-edit to a built page's STATIC
        # content (not a marker region) must fail --check, because the page is rebuilt from its
        # independent site-src/pages source. This is the CI gate SITE-BUILD-14 promises.
        import os as _os
        root = self._clone_repo()
        self.assertEqual(bsd.main(["build_site_data.py", "--root", root]), 0)
        self.assertEqual(bsd.main(["build_site_data.py", "--check", "--root", root]), 0)
        page = _os.path.join(root, "site", "commentable-html", "index.html")
        html = bsd.read_text(page)
        self.assertIn("Why Commentable HTML", html)
        with open(page, "w", encoding="utf-8", newline="") as fh:
            fh.write(html.replace("Why Commentable HTML", "HAND EDITED", 1))
        self.assertEqual(bsd.main(["build_site_data.py", "--check", "--root", root]), 1)

    def test_check_flags_an_orphaned_page_whose_source_was_removed(self):
        # If a page's site-src source is removed but its built artifact lingers, --check must flag it
        # so the "pure artifact" invariant never silently ignores a stranded page. Capture stderr so
        # the assertion isolates the orphan guard (a --check would also fail from sitemap/llms drift).
        import contextlib
        import io
        import os as _os
        root = self._clone_repo()
        self.assertEqual(bsd.main(["build_site_data.py", "--root", root]), 0)
        self.assertEqual(bsd.main(["build_site_data.py", "--check", "--root", root]), 0)
        _os.remove(_os.path.join(root, bsd.TUTORIAL_PAGE_SRC))
        self.assertTrue(_os.path.exists(_os.path.join(root, bsd.TUTORIAL_PAGE)))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = bsd.main(["build_site_data.py", "--check", "--root", root])
        self.assertEqual(rc, 1)
        self.assertIn("orphaned", err.getvalue())

    def test_check_flags_a_missing_built_page_when_its_source_exists(self):
        # First-build / forgot-to-commit case: the source exists but the built artifact does not.
        import os as _os
        root = self._clone_repo()
        self.assertEqual(bsd.main(["build_site_data.py", "--root", root]), 0)
        self.assertEqual(bsd.main(["build_site_data.py", "--check", "--root", root]), 0)
        _os.remove(_os.path.join(root, bsd.TUTORIAL_PAGE))
        self.assertEqual(bsd.main(["build_site_data.py", "--check", "--root", root]), 1)

    def test_write_removes_an_orphaned_page_whose_source_was_removed(self):
        import os as _os
        root = self._clone_repo()
        self.assertEqual(bsd.main(["build_site_data.py", "--root", root]), 0)
        _os.remove(_os.path.join(root, bsd.TUTORIAL_PAGE_SRC))
        self.assertEqual(bsd.main(["build_site_data.py", "--root", root]), 0)
        self.assertFalse(_os.path.exists(_os.path.join(root, bsd.TUTORIAL_PAGE)))

    def test_removing_tutorial_source_drops_its_llms_link(self):
        # The llms.txt tutorial link is gated on the tutorial source, so removing the source and
        # rebuilding leaves no llms.txt link pointing at the deleted tutorial page.
        import os as _os
        root = self._clone_repo()
        self.assertEqual(bsd.main(["build_site_data.py", "--root", root]), 0)
        llms = _os.path.join(root, "site", "llms.txt")
        self.assertIn("commentable-html/tutorial/", bsd.read_text(llms))
        _os.remove(_os.path.join(root, bsd.TUTORIAL_PAGE_SRC))
        self.assertEqual(bsd.main(["build_site_data.py", "--root", root]), 0)
        self.assertNotIn("commentable-html/tutorial/", bsd.read_text(llms))

    def test_missing_required_page_source_errors_clearly(self):
        # A hub/plugin page is required: removing its source must raise a clear SystemExit rather
        # than a bare FileNotFoundError traceback (they are not optional like the tutorial).
        import os as _os
        root = self._clone_repo()
        _os.remove(_os.path.join(root, bsd.HUB_SRC))
        with self.assertRaises(SystemExit):
            bsd.main(["build_site_data.py", "--check", "--root", root])

    def test_check_flags_a_missing_built_hub_page(self):
        # The required hub artifact missing (source intact) must be drift, exercising the hub/plugin
        # comparison branch directly (the tutorial-missing test covers only the optional page).
        import os as _os
        root = self._clone_repo()
        self.assertEqual(bsd.main(["build_site_data.py", "--root", root]), 0)
        self.assertEqual(bsd.main(["build_site_data.py", "--check", "--root", root]), 0)
        _os.remove(_os.path.join(root, bsd.HUB_OUT))
        self.assertEqual(bsd.main(["build_site_data.py", "--check", "--root", root]), 1)

    def test_check_flags_a_missing_built_stylesheet_without_crashing(self):
        # A missing site/assets/styles.css must be reported as drift, not crash the build: the page
        # ?v= stamp is derived from the source partials, so build_page never reads the absent file.
        import os as _os
        root = self._clone_repo()
        self.assertEqual(bsd.main(["build_site_data.py", "--root", root]), 0)
        self.assertEqual(bsd.main(["build_site_data.py", "--check", "--root", root]), 0)
        _os.remove(_os.path.join(root, "site", "assets", "styles.css"))
        self.assertEqual(bsd.main(["build_site_data.py", "--check", "--root", root]), 1)

    def test_styles_asset_hash_ignores_a_stale_on_disk_stylesheet(self):
        # The styles.css cache-bust stamp must come from the SOURCE partials, not the on-disk
        # artifact. With a STALE styles.css on disk, _asset_hash must still return the source-derived
        # hash. This discriminates: a regression back to disk-reading would return the stale hash and
        # fail here (a tautology hashing build_styles on both sides could not catch that).
        import hashlib as _hashlib
        import os as _os
        root = self._clone_repo()
        stale = _os.path.join(root, "site", "assets", "styles.css")
        with open(stale, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("/* STALE - not the real bundle */\n")
        source_derived = _hashlib.sha256(bsd.build_styles(root).encode("utf-8")).hexdigest()[:12]
        with open(stale, "rb") as fh:
            stale_disk = _hashlib.sha256(fh.read()).hexdigest()[:12]
        self.assertNotEqual(source_derived, stale_disk)  # the two differ, so the test can discriminate
        self.assertEqual(bsd._asset_hash(root, "styles.css"), source_derived)

    def test_build_writes_nested_artifacts_on_a_fresh_checkout_without_site_tree(self):
        # write_text creates parent dirs, so a build with the nested generated page dir removed
        # recreates the plugin and tutorial pages (and their directories) instead of crashing with
        # FileNotFoundError. site/assets (committed, non-generated, e.g. site.js) is left intact.
        import os as _os
        import shutil
        root = self._clone_repo()
        shutil.rmtree(_os.path.join(root, "site", "commentable-html"))
        self.assertEqual(bsd.main(["build_site_data.py", "--root", root]), 0)
        self.assertTrue(_os.path.isfile(_os.path.join(root, bsd.PLUGIN_OUT)))
        self.assertTrue(_os.path.isfile(_os.path.join(root, bsd.TUTORIAL_PAGE)))

    def test_check_flags_a_hand_edited_built_hub_page(self):
        # The hub page goes through the same build_page/_read_artifact path as the plugin page; prove
        # the whole-page guard at the CLI level for the hub too (SITE-BUILD-14 covers "any built page").
        import os as _os
        root = self._clone_repo()
        self.assertEqual(bsd.main(["build_site_data.py", "--root", root]), 0)
        self.assertEqual(bsd.main(["build_site_data.py", "--check", "--root", root]), 0)
        page = _os.path.join(root, bsd.HUB_OUT)
        html = bsd.read_text(page)
        with open(page, "w", encoding="utf-8", newline="") as fh:
            fh.write(html.replace("</body>", "<p>HAND EDITED</p></body>", 1))
        self.assertEqual(bsd.main(["build_site_data.py", "--check", "--root", root]), 1)

    def test_missing_required_plugin_page_source_errors_clearly(self):
        # Parallel to the hub-source test: removing the plugin page source must also raise SystemExit,
        # so a future refactor cannot break the required-source loop for one page only.
        import os as _os
        root = self._clone_repo()
        _os.remove(_os.path.join(root, bsd.PLUGIN_SRC))
        with self.assertRaises(SystemExit):
            bsd.main(["build_site_data.py", "--check", "--root", root])

    def test_missing_manifest_errors_clearly(self):
        # A missing marketplace manifest must raise a clear SystemExit, not a raw FileNotFoundError.
        import os as _os
        root = self._clone_repo()
        _os.remove(_os.path.join(root, ".github", "plugin", "marketplace.json"))
        with self.assertRaises(SystemExit):
            bsd.main(["build_site_data.py", "--check", "--root", root])

    def test_malformed_manifest_errors_clearly(self):
        # A hand-broken manifest (invalid JSON) must raise a clear SystemExit naming the file, not a
        # raw json.JSONDecodeError traceback.
        import os as _os
        root = self._clone_repo()
        mpath = _os.path.join(root, ".github", "plugin", "marketplace.json")
        with open(mpath, "w", encoding="utf-8") as fh:
            fh.write("{ not valid json, }")
        with self.assertRaises(SystemExit):
            bsd.main(["build_site_data.py", "--check", "--root", root])

    def test_missing_required_site_js_asset_errors_clearly(self):
        # site.js is a committed (non-generated) cache-busted asset: if it is deleted, the build must
        # fail loudly with a clear SystemExit rather than silently stamping or a raw traceback.
        import os as _os
        root = self._clone_repo()
        _os.remove(_os.path.join(root, "site", "assets", "site.js"))
        with self.assertRaises(SystemExit):
            bsd.main(["build_site_data.py", "--check", "--root", root])

    def test_removing_tutorial_source_drops_its_sitemap_entry(self):
        # Parallel to the llms.txt gating: removing the tutorial source and rebuilding must drop the
        # tutorial <loc> from sitemap.xml (the SITE-BUILD-14 sitemap-gating claim).
        import os as _os
        root = self._clone_repo()
        self.assertEqual(bsd.main(["build_site_data.py", "--root", root]), 0)
        sitemap = _os.path.join(root, "site", "sitemap.xml")
        self.assertIn("commentable-html/tutorial/", bsd.read_text(sitemap))
        _os.remove(_os.path.join(root, bsd.TUTORIAL_PAGE_SRC))
        self.assertEqual(bsd.main(["build_site_data.py", "--root", root]), 0)
        self.assertNotIn("commentable-html/tutorial/", bsd.read_text(sitemap))


class StylesConcatTests(unittest.TestCase):
    def test_concat_matches_committed_stylesheet(self):
        import os as _os
        root = bsd.REPO_ROOT
        built = bsd.build_styles(root)
        committed = bsd.read_text(_os.path.join(root, "site", "assets", "styles.css"))
        self.assertEqual(
            built, committed,
            "site/assets/styles.css is stale vs site-src/css/ partials; run build_site_data.py")

    def test_parts_exist_and_base_loads_first(self):
        import os as _os
        root = bsd.REPO_ROOT
        parts = bsd.ordered_css_parts(root)
        self.assertTrue(parts, "no CSS partials discovered under site-src/css/")
        for name in parts:
            self.assertTrue(
                _os.path.exists(_os.path.join(root, "site-src", "css", name)),
                "missing CSS partial: " + name)
        # Order is load-bearing (directory-sorted): the tokens/base partial must come first.
        self.assertEqual(parts[0], "10-base.css")
        self.assertEqual(parts, sorted(parts), "partials must be returned in sorted (cascade) order")

    def test_a_stray_non_numbered_css_file_is_rejected(self):
        import os as _os
        import tempfile
        root = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, root, ignore_errors=True)
        css_dir = _os.path.join(root, "site-src", "css")
        _os.makedirs(css_dir)
        with open(_os.path.join(css_dir, "10-base.css"), "w", encoding="utf-8") as fh:
            fh.write("a{}")
        with open(_os.path.join(css_dir, "helpers.css"), "w", encoding="utf-8") as fh:
            fh.write("b{}")
        with self.assertRaises(SystemExit):
            bsd.ordered_css_parts(root)


class PageBannerAndGuardTests(unittest.TestCase):
    """Site pages are pure artifacts built from site-src/pages/ sources and carry a DO NOT EDIT
    banner; a hand-edit to a built page is caught by comparing it to a fresh build (SITE-BUILD-14)."""

    def _mktemp(self):
        import shutil
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        return d

    def test_page_banner_names_source_and_says_do_not_edit(self):
        b = bsd.page_banner(os.path.join("site-src", "pages", "index.html"))
        self.assertIn("DO NOT EDIT", b)
        self.assertIn("site-src/pages/index.html", b)  # forward slashes even on Windows
        self.assertIn("build_site_data.py", b)

    def test_css_banner_says_do_not_edit(self):
        b = bsd.css_banner()
        self.assertIn("DO NOT EDIT", b)
        self.assertTrue(b.lstrip().startswith("/*"))

    def test_apply_page_banner_inserts_after_doctype_and_is_idempotent(self):
        html = "<!DOCTYPE html>\n<html><head></head><body></body></html>\n"
        once = bsd.apply_page_banner(html, "site-src/pages/index.html")
        self.assertRegex(once, r"^<!DOCTYPE html>\n<!-- GENERATED FILE - DO NOT EDIT\.")
        # Re-applying replaces the prior banner instead of stacking a second one.
        twice = bsd.apply_page_banner(once, "site-src/pages/index.html")
        self.assertEqual(once, twice)
        self.assertEqual(twice.count(bsd.GENERATED_BANNER_PREFIX), 1)

    def test_apply_page_banner_leaves_a_body_comment_with_the_banner_prefix(self):
        # Only the banner in the slot right after the doctype is replaced; a comment elsewhere in
        # the page body that happens to start with the banner prefix must NOT be stripped.
        body_comment = "<!-- %s real body content -->" % bsd.GENERATED_BANNER_PREFIX
        html = "<!DOCTYPE html>\n<html><body>\n%s\n</body></html>\n" % body_comment
        out = bsd.apply_page_banner(html, "site-src/pages/index.html")
        self.assertIn(body_comment, out)
        self.assertEqual(out.count(bsd.GENERATED_BANNER_PREFIX), 2)  # slot banner + body comment
        self.assertEqual(out, bsd.apply_page_banner(out, "site-src/pages/index.html"))  # idempotent

    def test_apply_page_banner_tolerates_a_doctype_with_attributes(self):
        html = '<!DOCTYPE html SYSTEM "about:legacy-compat">\n<html></html>\n'
        out = bsd.apply_page_banner(html, "site-src/pages/index.html")
        # The banner goes AFTER the doctype (never before it, which would trip quirks mode).
        self.assertRegex(
            out, r'^<!DOCTYPE html SYSTEM "about:legacy-compat">\n<!-- GENERATED FILE - DO NOT EDIT\.')

    def _write_source(self, root):
        src_rel = os.path.join("site-src", "pages", "x.html")
        os.makedirs(os.path.join(root, "site-src", "pages"))
        with open(os.path.join(root, src_rel), "w", encoding="utf-8", newline="") as fh:
            fh.write("<!DOCTYPE html>\n<html><body>\n<h1>Real title</h1>\n"
                     "<!-- BEGIN:plugins -->OLD<!-- END:plugins -->\n</body></html>\n")
        return src_rel

    def test_build_page_fills_region_and_banners(self):
        root = self._mktemp()
        src_rel = self._write_source(root)
        art = bsd.build_page(root, src_rel, [("block", "plugins", "GRID")])
        self.assertIn("DO NOT EDIT", art)
        self.assertIn("<h1>Real title</h1>", art)
        self.assertIn("GRID", art)
        self.assertNotIn("OLD", art)

    def test_check_catches_a_hand_edit_to_the_built_page(self):
        # A hand-edit to the built page's STATIC content (not a marker region) differs from a fresh
        # build of its independent source. This is the guard that closes the site clobber gap: the
        # static content used to be self-sourced and invisible to --check.
        root = self._mktemp()
        src_rel = self._write_source(root)
        out_path = os.path.join(root, "site", "x.html")
        os.makedirs(os.path.join(root, "site"))
        fillers = [("block", "plugins", "GRID")]
        art = bsd.build_page(root, src_rel, fillers)
        with open(out_path, "w", encoding="utf-8", newline="") as fh:
            fh.write(art)
        # In sync: a fresh build equals the committed artifact.
        self.assertEqual(bsd.build_page(root, src_rel, fillers), bsd._read_artifact(out_path))
        # Hand-edit the built page -> it no longer equals a fresh build (drift is detected).
        with open(out_path, "w", encoding="utf-8", newline="") as fh:
            fh.write(art.replace("Real title", "HACKED"))
        self.assertNotEqual(bsd.build_page(root, src_rel, fillers), bsd._read_artifact(out_path))

    def test_missing_artifact_counts_as_drift(self):
        self.assertIsNone(bsd._read_artifact(os.path.join(self._mktemp(), "nope.html")))

    def test_write_text_creates_missing_parent_dirs(self):
        # Isolated proof of the makedirs behavior: writing into a not-yet-existing nested path works.
        root = self._mktemp()
        target = os.path.join(root, "deep", "nested", "page.html")
        bsd.write_text(target, "hello\n")
        self.assertEqual(bsd.read_text(target), "hello\n")

    def test_write_text_errors_clearly_when_a_parent_is_a_file(self):
        # A malformed tree where a parent path is a regular file must raise a clear SystemExit
        # (path conflict) instead of a raw NotADirectoryError/FileExistsError traceback.
        root = self._mktemp()
        blocker = os.path.join(root, "blocker")
        with open(blocker, "w", encoding="utf-8") as fh:
            fh.write("i am a file, not a directory")
        target = os.path.join(blocker, "child", "page.html")
        with self.assertRaises(SystemExit):
            bsd.write_text(target, "hello\n")

    def test_build_page_rejects_an_unknown_region_kind(self):
        # build_page only knows "block" (and historically "attr") region kinds; an unknown kind must
        # fail loudly rather than silently leave the marker unfilled in the shipped artifact.
        root = self._mktemp()
        src_rel = self._write_source(root)
        with self.assertRaises(SystemExit):
            bsd.build_page(root, src_rel, [("bogus", "plugins", "GRID")])

    def test_build_page_rejects_a_source_without_a_doctype(self):
        # Every shipped page must start with a doctype so the banner has a slot; a source missing it
        # must raise rather than emit a page the banner cannot be applied to.
        root = self._mktemp()
        os.makedirs(os.path.join(root, "site-src", "pages"))
        src_rel = os.path.join("site-src", "pages", "y.html")
        with open(os.path.join(root, src_rel), "w", encoding="utf-8", newline="") as fh:
            fh.write("<html><body><h1>No doctype</h1></body></html>\n")
        with self.assertRaises(SystemExit):
            bsd.build_page(root, src_rel, [])

    def test_build_page_rejects_a_source_with_two_doctypes(self):
        # A duplicated <!doctype> is the classic malformed-merge artifact: it would build and match
        # its committed copy (passing --check) while shipping invalid HTML, so reject it at build.
        root = self._mktemp()
        os.makedirs(os.path.join(root, "site-src", "pages"))
        src_rel = os.path.join("site-src", "pages", "dup.html")
        with open(os.path.join(root, src_rel), "w", encoding="utf-8", newline="") as fh:
            fh.write("<!DOCTYPE html>\n<html><body>\n<!DOCTYPE html>\n</body></html>\n")
        with self.assertRaises(SystemExit):
            bsd.build_page(root, src_rel, [])

    def test_build_page_allows_a_literal_doctype_inside_content(self):
        # The duplicate-doctype guard counts only LINE-LEADING declarations, so a literal "<!doctype"
        # embedded in a script string or in prose (a real HTML-tooling page could carry one) does not
        # false-trip the guard.
        root = self._mktemp()
        os.makedirs(os.path.join(root, "site-src", "pages"))
        src_rel = os.path.join("site-src", "pages", "lit.html")
        with open(os.path.join(root, src_rel), "w", encoding="utf-8", newline="") as fh:
            fh.write('<!DOCTYPE html>\n<html><body>\n'
                     '<script>var s = "<!doctype html>";</script>\n'
                     '<p>Type <!doctype html> to start a page.</p>\n'
                     '</body></html>\n')
        art = bsd.build_page(root, src_rel, [])
        self.assertIn('var s = "<!doctype html>";', art)  # the literal survived; no SystemExit

    def test_build_styles_errors_on_a_missing_css_directory(self):
        # A missing site-src/css/ directory must raise a clear SystemExit, not a raw OSError.
        root = self._mktemp()
        with self.assertRaises(SystemExit):
            bsd.build_styles(root)

    def test_build_styles_strips_a_bom_from_a_css_partial(self):
        # A BOM saved into any CSS partial must not land inside the concatenated bundle (it would sit
        # mid-file and can break CSS parsing); build_styles strips it like build_page does for pages.
        root = self._mktemp()
        css_dir = os.path.join(root, "site-src", "css")
        os.makedirs(css_dir)
        names = ["10-base.css", "20-mid.css", "30-tail.css"]
        for i, name in enumerate(names):
            enc = "utf-8-sig" if i == 1 else "utf-8"  # a BOM on a non-first partial is the worst case.
            with open(os.path.join(css_dir, name), "w", encoding=enc, newline="") as fh:
                fh.write("/* %s */\n" % name)
        built = bsd.build_styles(root)
        self.assertNotIn("\ufeff", built)
        # A source saved with a UTF-8 BOM still builds (the BOM is stripped before the doctype check),
        # and the built artifact never carries the BOM into the shipped page.
        root = self._mktemp()
        os.makedirs(os.path.join(root, "site-src", "pages"))
        src_rel = os.path.join("site-src", "pages", "bom.html")
        with open(os.path.join(root, src_rel), "w", encoding="utf-8-sig", newline="") as fh:
            fh.write("<!DOCTYPE html>\n<html><body><h1>BOM</h1></body></html>\n")
        art = bsd.build_page(root, src_rel, [])
        self.assertFalse(art.startswith("\ufeff"))
        self.assertRegex(art, r"^<!DOCTYPE html>\n<!-- %s" % bsd.GENERATED_BANNER_PREFIX)

    def test_committed_page_sources_are_banner_free(self):
        # The editable sources under site-src/pages must NOT carry the generated banner; the banner
        # is injected only into the built artifact. If a source picked one up, a rebuild would be a
        # no-op on the banner line and hand-edits could hide there.
        for rel in (bsd.HUB_SRC, bsd.PLUGIN_SRC, bsd.TUTORIAL_PAGE_SRC):
            src = os.path.join(bsd.REPO_ROOT, rel)
            if not os.path.exists(src):
                continue
            self.assertNotIn(bsd.GENERATED_BANNER_PREFIX, bsd.read_text(src),
                             "%s must not contain the generated banner" % rel)

    def test_committed_stylesheet_carries_the_banner(self):
        css = os.path.join(bsd.REPO_ROOT, "site", "assets", "styles.css")
        self.assertIn("DO NOT EDIT", bsd.read_text(css))


if __name__ == "__main__":
    unittest.main()