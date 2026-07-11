"""Unit tests for scripts/build_site_data.py.

Run by the validate CI job via `python -m unittest discover -s scripts -p "test_*.py"`,
so the site generator's escaping, URL allowlist, and changelog parsing are covered by a
required status check.
"""
import unittest

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
    def test_rewrites_example_paths_to_site_demo(self):
        md = "Open `examples/report-community-garden.html` then `examples/report-taxi.html`."
        out = bsd.site_tutorial_markdown(md)
        self.assertIn("../demo/report-community-garden.html", out)
        self.assertIn("../demo/report-taxi.html", out)
        self.assertNotIn("examples/report-", out)


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


if __name__ == "__main__":
    unittest.main()