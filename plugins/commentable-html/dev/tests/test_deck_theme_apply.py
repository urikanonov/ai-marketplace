#!/usr/bin/env python3
"""Tests for in-place deck re-theming (CMH-DECK-THEME-02).

`deck_theme.py apply` must be idempotent, swap only the cmh-deck-theme block, and be comment-safe:
because the block is cm-skip and is inserted before the slide viewport, no slide text moves, so
stored comment offsets and every slide id survive a re-theme (including re-theming to a
different-length preset). Applying to a non-deck or a repo example fails closed.
"""
import json
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
sys.path.insert(0, _paths.TOOLS)
import _toolpath  # noqa: E402
_toolpath.ensure()
import deck_theme  # noqa: E402

SCAFFOLD = os.path.join(DECK, "deck_scaffold.py")
VIEWPORT = '<div class="deck-viewport">'
# Independent of the implementation's own regex, so the anchor-neutral check cannot silently agree
# with an over-broad impl pattern.
import re  # noqa: E402
_THEME_TAG = re.compile(r'<style id="cmh-deck-theme".*?</style>', re.S)


def _scaffold(out, *args):
    proc = subprocess.run(
        [sys.executable, SCAFFOLD, "--label", "Apply Deck", "--source", out, "--out", out, *args],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    return Path(out).read_text(encoding="utf-8")


class DeckThemeApplyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        self.deck = os.path.join(self.tmp, "deck.html")

    def _apply(self, *args):
        return deck_theme.main(["apply", self.deck, *args])

    def _write_small_theme(self):
        path = os.path.join(self.tmp, "small.theme.json")
        Path(path).write_text(json.dumps({
            "label": "small",
            "tokens": {"--slide-bg": "#101010", "--slide-fg": "#fafafa"},
        }), encoding="utf-8")
        return path

    def test_apply_is_comment_safe_and_idempotent(self):
        html0 = _scaffold(self.deck, "--slides", "3")
        # Raw bytes (newline-preserving) BEFORE apply, to prove the write is byte-neutral outside the
        # theme block on every platform (including CRLF-authored decks on Windows).
        with open(self.deck, encoding="utf-8", newline="") as fh:
            raw0 = fh.read()
        tail0 = html0[html0.index(VIEWPORT):]
        self.assertEqual(self._apply("--theme", "terminal"), 0)
        html1 = Path(self.deck).read_text(encoding="utf-8")
        self.assertIn('id="cmh-deck-theme"', html1)
        self.assertIn("cm-skip", html1)
        # Slide viewport onward is byte-identical: no slide text moved, so no comment offset shifts.
        self.assertEqual(html1[html1.index(VIEWPORT):], tail0)
        # Stronger: removing the (cm-skip) theme block from the RAW bytes yields the original unthemed
        # deck byte-for-byte (newlines preserved), proving the write touched nothing outside the block.
        with open(self.deck, encoding="utf-8", newline="") as fh:
            raw1 = fh.read()
        self.assertEqual(_THEME_TAG.sub("", raw1), raw0)
        # Idempotent: applying the same theme again is a no-op.
        self.assertEqual(self._apply("--theme", "terminal"), 0)
        html2 = Path(self.deck).read_text(encoding="utf-8")
        self.assertEqual(html2, html1)
        self.assertEqual(html2.count('id="cmh-deck-theme"'), 1)

    def test_retheme_to_different_length_preserves_slides_and_comment_blocks(self):
        html0 = _scaffold(self.deck, "--slides", "2")
        emb = html0[html0.index('id="embeddedComments"'):html0.index('id="handledCommentIds"')]
        self.assertEqual(self._apply("--theme", "terminal"), 0)
        # Re-theme to a shorter preset: still only one theme block, slides + comment blocks intact.
        self.assertEqual(self._apply("--theme", self._write_small_theme()), 0)
        html2 = Path(self.deck).read_text(encoding="utf-8")
        self.assertEqual(html2.count('id="cmh-deck-theme"'), 1)
        self.assertIn('data-cmh-deck-theme="small"', html2)
        self.assertEqual(html2[html2.index(VIEWPORT):], html0[html0.index(VIEWPORT):])
        self.assertEqual(
            html2[html2.index('id="embeddedComments"'):html2.index('id="handledCommentIds"')], emb)

    def test_non_deck_fails_closed(self):
        plain = os.path.join(self.tmp, "plain.html")
        Path(plain).write_text("<!doctype html><html><body><p>not a deck</p></body></html>",
                               encoding="utf-8")
        before = Path(plain).read_text(encoding="utf-8")
        rc = deck_theme.main(["apply", plain, "--theme", "terminal"])
        self.assertNotEqual(rc, 0)
        self.assertEqual(Path(plain).read_text(encoding="utf-8"), before)  # untouched

    def test_unknown_preset_fails_closed(self):
        _scaffold(self.deck, "--slides", "1")
        before = Path(self.deck).read_text(encoding="utf-8")
        self.assertNotEqual(self._apply("--theme", "does-not-exist"), 0)
        self.assertEqual(Path(self.deck).read_text(encoding="utf-8"), before)

    def test_list_presets(self):
        rc = deck_theme.main(["list"])
        self.assertEqual(rc, 0)

    def test_out_writes_target_and_leaves_source_unchanged(self):
        html0 = _scaffold(self.deck, "--slides", "2")
        out = os.path.join(self.tmp, "themed-copy.html")
        self.assertEqual(deck_theme.main(["apply", self.deck, "--theme", "terminal", "--out", out]), 0)
        # Source is untouched; the themed result lands in --out.
        self.assertEqual(Path(self.deck).read_text(encoding="utf-8"), html0)
        self.assertIn('data-cmh-deck-theme="terminal"', Path(out).read_text(encoding="utf-8"))

    def test_refuses_repo_example_without_force(self):
        # A path under a repo examples/ dir is refused unless --force (it is rebuilt from dev/src).
        ex_dir = os.path.join(self.tmp, "plugins", "commentable-html", "examples")
        os.makedirs(ex_dir)
        ex = os.path.join(ex_dir, "deck-showcase.html")
        html0 = _scaffold(ex, "--slides", "1")
        self.assertNotEqual(deck_theme.main(["apply", ex, "--theme", "terminal"]), 0)
        self.assertEqual(Path(ex).read_text(encoding="utf-8"), html0)  # untouched
        self.assertEqual(deck_theme.main(["apply", ex, "--theme", "terminal", "--force"]), 0)
        self.assertIn('data-cmh-deck-theme="terminal"', Path(ex).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
