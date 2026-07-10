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

    def test_no_filter_only_removes_backticks(self):
        self.assertEqual(bsd.clean_entry("uses `code` here", None), "uses code here")


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


if __name__ == "__main__":
    unittest.main()
