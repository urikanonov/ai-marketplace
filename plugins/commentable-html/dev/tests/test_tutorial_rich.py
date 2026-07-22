#!/usr/bin/env python3
"""CMH-RICH-14: the tutorial documents the rich-text formatting feature and embeds both shots.

A tutorial section (docs/TUTORIAL.md) is published content, so pin that it actually documents the
markers/shortcuts and references the two committed screenshots - a shot-capture test alone would not
catch the section being removed or the images being unreferenced.
"""
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TUTORIAL = os.path.join(HERE, os.pardir, os.pardir, "docs", "TUTORIAL.md")


class TutorialRichTextTests(unittest.TestCase):
    def test_tutorial_documents_formatting_and_embeds_both_shots(self):
        with open(TUTORIAL, "r", encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("Format your comment", text, "tutorial is missing the formatting section")
        self.assertIn("assets/garden-15-format-toolbar.png", text, "missing the composer-toolbar shot")
        self.assertIn("assets/garden-16-rich-card.png", text, "missing the rendered rich-card shot")
        for token in ("**bold**", "*italic*", "__underline__", "Ctrl/Cmd+K"):
            self.assertIn(token, text, "tutorial does not document %r" % token)


if __name__ == "__main__":
    unittest.main()
