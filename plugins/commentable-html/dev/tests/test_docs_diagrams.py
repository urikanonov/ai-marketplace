"""Shipped-doc checks for the portability-mode diagrams (CMH-MODE-08).

The Output modes reference must carry two mermaid diagrams (one Portable, one NonPortable)
showing what is bundled in the file versus fetched from where, and SKILL.md must point at them.
"""
import os
import re
import unittest

import _paths

EXPORTS_MD = os.path.join(_paths.PKG, "references", "exports.md")
SKILL_MD = os.path.join(_paths.PKG, "SKILL.md")


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class PortabilityDiagramsTests(unittest.TestCase):
    def test_exports_has_two_mode_mermaid_diagrams(self):
        text = _read(EXPORTS_MD)
        heading = "## What is bundled in the file vs fetched from where"
        self.assertIn(heading, text)
        section = text.split(heading, 1)[1].split("\n## ", 1)[0]
        fences = re.findall(r"```mermaid\b", section)
        self.assertGreaterEqual(len(fences), 2, "expected two mermaid diagrams in the section")
        # Portable inlines the layer CSS/JS; NonPortable loads the companions from dist/.
        self.assertIn("(inlined)", section)
        for companion in ("commentable-html.css", "commentable-html.js", "commentable-html.assets.js"):
            self.assertIn(companion, section)
        # Both modes keep content and comments inline and fetch optional libraries from a CDN.
        self.assertIn("EMBEDDED COMMENTS", section)
        self.assertIn("CDN", section)

    def test_skill_output_modes_references_the_diagrams(self):
        text = _read(SKILL_MD)
        self.assertIn(
            "references/exports.md#what-is-bundled-in-the-file-vs-fetched-from-where",
            text)


PLUGIN_README = os.path.normpath(os.path.join(_paths.PKG, "..", "..", "README.md"))
BLOG_URL = "https://claude.com/blog/using-claude-code-the-unreasonable-effectiveness-of-html"


class MotivationDocsTests(unittest.TestCase):
    """CMH-DOC-01: the shipped README and SKILL.md carry the medium-comparison motivation
    and cite the "unreasonable effectiveness of HTML" blog post."""

    def test_readme_has_comparison_table_and_blog_reference(self):
        text = _read(PLUGIN_README)
        self.assertIn("Why not just plan in chat, Markdown, or plain HTML?", text)
        self.assertIn("| **commentable-html** |", text)
        for medium in ("Chat / terminal", "Markdown file", "Plain HTML"):
            self.assertIn(medium, text)
        self.assertIn(BLOG_URL, text)

    def test_skill_cites_the_blog_reference(self):
        self.assertIn(BLOG_URL, _read(SKILL_MD))


if __name__ == "__main__":
    unittest.main()
