#!/usr/bin/env python3
"""Tests for deck/deck_fix_fonts.py (CMH-DECK-18)."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402

DECK = os.path.join(_paths.PKG, "tools", "deck")
sys.path.insert(0, DECK)
import deck_fix_fonts  # noqa: E402
import deck_validate  # noqa: E402

SCAFFOLD = os.path.join(DECK, "deck_scaffold.py")
TOOL = os.path.join(DECK, "deck_fix_fonts.py")
END_MARK = "<!-- END: commentable-html - CONTENT -->"

SERIF = '"Iowan Old Style","Palatino Linotype","Georgia",serif'
DISPLAY = '"Impact","Rockwell","Arial Black",sans-serif'
SANS = 'system-ui,-apple-system,"Segoe UI",Roboto,sans-serif'
MONO = '"Cascadia Code","Consolas","Fira Code",ui-monospace,monospace'

BAD_FONTS = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Playfair+Display&family=Inter&display=swap">
<link rel="stylesheet" href="https://api.fontshare.com/v2/css?f[]=satoshi@400">
<style>
@import url("https://fonts.googleapis.com/css2?family=Bebas+Neue");
@font-face { font-family: "RemoteSerif"; src: url("https://fonts.gstatic.com/s/remoteserif.woff2") format("woff2"); }
@font-face { font-family: "LocalFace"; src: url(data:font/woff2;base64,AAAA) format("woff2"); }
:root {
  --font-display: "Bebas Neue", "ZCOOL XiaoWei", sans-serif;
  --font-body: "Inter", "Noto Sans SC", sans-serif;
  --font-serif: "Playfair Display", "Noto Serif SC", Georgia, serif;
  --font-mono: "JetBrains Mono", "Noto Sans Mono CJK SC", monospace;
}
.slide .serif { font-family: "Cormorant Garamond", "LXGW WenKai TC", serif; }
.slide .display { font-family: "Alfa Slab One", "Noto Sans SC", cursive; }
.slide .sans { font-family: "Space Grotesk", "Noto Serif SC", sans-serif; }
.slide .mono { font-family: "IBM Plex Mono", "Noto Sans Mono CJK SC", monospace; }
.slide .cjk { font-family: "Noto Sans SC", "LXGW WenKai TC", sans-serif; }
</style>
"""


def _inject(html, snippet):
    return html.replace(END_MARK, snippet + "\n" + END_MARK, 1)


class DeckFixFontsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        self.deck_path = os.path.join(self.tmp, "deck.html")
        proc = subprocess.run(
            [sys.executable, SCAFFOLD, "--slides", "2", "--label", "Font Deck", "--source", self.deck_path,
             "--out", self.deck_path],
            capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.bad_html = _inject(Path(self.deck_path).read_text(encoding="utf-8"), BAD_FONTS)

    def test_cmh_deck_18_maps_web_fonts_and_strips_remote_loaders(self):
        fixed, stats = deck_fix_fonts.fix_fonts(self.bad_html)
        fixed_again, stats_again = deck_fix_fonts.fix_fonts(fixed)
        content_start, _ = deck_fix_fonts._content_span(self.bad_html)
        suffix = self.bad_html[self.bad_html.rfind(END_MARK):]

        self.assertGreater(stats.remote_loaders_removed, 0)
        self.assertGreater(stats.font_stacks_rewritten, 0)
        self.assertEqual(stats_again.remote_loaders_removed, 0)
        self.assertEqual(stats_again.font_stacks_rewritten, 0)
        self.assertEqual(fixed, fixed_again)
        self.assertEqual(fixed[:content_start], self.bad_html[:content_start])
        self.assertTrue(fixed.endswith(suffix))
        self.assertNotIn("fonts.googleapis.com", fixed)
        self.assertNotIn("fonts.gstatic.com", fixed)
        self.assertNotIn("api.fontshare.com", fixed)
        self.assertNotIn("Bebas+Neue", fixed)
        self.assertNotIn("RemoteSerif", fixed)
        self.assertIn('font-family: "LocalFace"', fixed)
        self.assertIn("--font-display: " + DISPLAY, fixed)
        self.assertIn("--font-body: " + SANS, fixed)
        self.assertIn("--font-serif: " + SERIF, fixed)
        self.assertIn("--font-mono: " + MONO, fixed)
        self.assertIn("font-family: " + SERIF, fixed)
        self.assertIn("font-family: " + DISPLAY, fixed)
        self.assertIn("font-family: " + SANS, fixed)
        self.assertIn("font-family: " + MONO, fixed)
        self.assertIn("font-family: sans-serif", fixed)
        for cjk_name in ("Noto Sans SC", "Noto Serif SC", "Noto Sans Mono CJK SC", "LXGW WenKai", "ZCOOL"):
            self.assertNotIn(cjk_name, fixed)
        self.assertEqual(deck_validate.deck_checks(fixed), [])

    def test_cmh_deck_18_cli_writes_deterministic_output(self):
        src = os.path.join(self.tmp, "bad.html")
        out_a = os.path.join(self.tmp, "fixed-a.html")
        out_b = os.path.join(self.tmp, "fixed-b.html")
        Path(src).write_text(self.bad_html, encoding="utf-8")

        for out in (out_a, out_b):
            proc = subprocess.run(
                [sys.executable, TOOL, src, "--out", out],
                capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)

        fixed_a = Path(out_a).read_text(encoding="utf-8")
        fixed_b = Path(out_b).read_text(encoding="utf-8")
        self.assertEqual(fixed_a, fixed_b)
        proc = subprocess.run(
            [sys.executable, os.path.join(DECK, "deck_validate.py"), out_a],
            capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main()
