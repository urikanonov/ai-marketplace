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
TUTORIAL_MD = os.path.join(_paths.PKG, "docs", "TUTORIAL.md")
REFERENCES = os.path.join(_paths.PKG, "references")


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
        self.assertIn("| **Commentable HTML** |", text)
        for medium in ("Chat / terminal", "Markdown file", "Plain HTML"):
            self.assertIn(medium, text)
        self.assertIn(BLOG_URL, text)

    def test_skill_cites_the_blog_reference(self):
        self.assertIn(BLOG_URL, _read(SKILL_MD))


class NewFeatureDocsTests(unittest.TestCase):
    """CMH-DOC-02: the shipped guidance covers widget drag opt-in, Offline state, and Export Offline."""

    def test_skill_documents_widget_drag_and_offline_modes(self):
        text = _read(SKILL_MD)
        for snippet in (
            "NonPortable is for fast iteration",
            "Portable is for peer review",
            "Offline is for zero-network handoff",
            "data-cm-draggable",
            "Only direct `data-cm-part` children of a slot are movable",
            "Export Offline",
            "after mermaid diagrams and charts have rendered",
        ):
            self.assertIn(snippet, text)

    def test_tutorial_documents_offline_export(self):
        text = _read(TUTORIAL_MD)
        for snippet in (
            "Offline",
            "Export Offline",
            "zero-network handoff",
            "after Mermaid diagrams and charts have rendered",
        ):
            self.assertIn(snippet, text)


class SkillTrimDocsTests(unittest.TestCase):
    """CMH-DOC-03: SKILL.md stays lean while routing moved detail to real references."""

    def test_skill_is_lean_and_keeps_generation_critical_contracts(self):
        text = _read(SKILL_MD)
        self.assertLess(os.path.getsize(SKILL_MD), 36 * 1024)
        for snippet in (
            "TOOL ROUTING contract",
            "tools/new_document.py",
            "tools/retrofit.py",
            "tools/upgrade.py",
            "tools/finalize.py <file> [--toc --fix-skip --inline-images --images-base DIR] --strict",
            "python tools/validate.py --strict <file.html>",
            "python tools/mark_handled.py <file.html> --from-bundle -",
            "Trust boundary (MUST)",
            "Portable != offline",
        ):
            self.assertIn(snippet, text)

    def test_moved_detail_lives_in_references_that_skill_links(self):
        skill = _read(SKILL_MD)
        checks = {
            "document-layout.md": (
                "runtime toolbar",
                "Clear Comments",
                "Per-document configuration example",
            ),
            "interaction-model.md": (
                "staggers by 28px",
                "composer popover",
                "Handled comments stay handled",
            ),
            "exports.md": (
                "Producing a NonPortable document",
                "Guardrails that make NonPortable safe",
                "Network requirements and CDN caveats",
            ),
            "retrofitting.md": (
                "tools/retrofit.py",
                "Manual paste fallback",
                "--root-selector",
            ),
        }
        for name, snippets in checks.items():
            with self.subTest(reference=name):
                self.assertIn("references/" + name, skill)
                text = _read(os.path.join(REFERENCES, name))
                for snippet in snippets:
                    self.assertIn(snippet, text)


if __name__ == "__main__":
    unittest.main()
