#!/usr/bin/env python3
"""Tests for deck/deck_scaffold.py (CMH-DECK-02).

The scaffolded deck must validate, be commentable-native (data-cmh-mode + fixed stage), give
every slide a stable data-slide-id with the first active, carry no inline editor or remote
fonts, and be create-only (refuse to overwrite unless --force).
"""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402

DECK = os.path.join(_paths.PKG, "deck")
sys.path.insert(0, DECK)
sys.path.insert(0, _paths.TOOLS)
import deck_scaffold  # noqa: E402
import validate as cmh_validate  # noqa: E402
from deck_common import SLIDE_ID_RE  # noqa: E402

TOOL = os.path.join(DECK, "deck_scaffold.py")


def _scaffold(out, *args):
    return subprocess.run(
        [sys.executable, TOOL, "--label", "Test Deck", "--source", out, "--out", out, *args],
        capture_output=True, text=True, encoding="utf-8",
    )


class DeckScaffoldTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        self.out = os.path.join(self.tmp, "deck.html")

    def _make(self, *args):
        proc = _scaffold(self.out, *args)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return Path(self.out).read_text(encoding="utf-8")

    def test_scaffold_is_valid_and_commentable_native(self):
        html = self._make("--slides", "3")
        errors, _ = cmh_validate.validate(self.out)
        self.assertEqual(errors, [], errors)
        self.assertIn('class="deck-viewport"', html)
        self.assertIn('class="deck-stage"', html)
        # data-cmh-mode must be on the REAL content root (the last one). If the template still
        # ships a decoy <main id="commentRoot"> (older templates carried one in a doc comment),
        # the first root must NOT carry deck mode; a single-root template is also valid.
        roots = re.findall(r'<main[^>]*id="commentRoot"[^>]*>', html)
        self.assertGreaterEqual(len(roots), 1)
        self.assertIn('data-cmh-mode="deck"', roots[-1])
        if len(roots) > 1:
            self.assertNotIn("data-cmh-mode", roots[0])

    def test_slides_have_stable_ids_first_active(self):
        html = self._make("--slides", "3")
        ids = re.findall(r'data-slide-id="([^"]+)"', html)
        self.assertEqual(len(ids), 3)
        for sid in ids:
            self.assertRegex(sid, SLIDE_ID_RE)
        self.assertEqual(len(set(ids)), 3)
        self.assertIn('class="slide active"', html)
        self.assertEqual(html.count('class="slide active"'), 1)

    def test_deck_body_has_no_editor_fonts_or_script(self):
        html = self._make("--slides", "2")
        body = html.split("BEGIN: commentable-html - CONTENT", 1)[1].split(
            "END: commentable-html - CONTENT", 1)[0]
        self.assertNotIn("edit-toggle", body)
        self.assertNotIn("contenteditable", body)
        self.assertNotIn("<deck-stage", body)
        self.assertNotIn("data-deck-active", body)
        self.assertNotIn("fonts.googleapis.com", body)
        self.assertNotIn("api.fontshare.com", body)
        self.assertNotIn("https://", body)   # no remote refs in the deck body
        self.assertNotIn("<script", body)    # no host script; the controller lives in the layer JS
        self.assertIn(".deck-stage {", body)  # the fixed-stage CSS is inlined

    def test_content_ids_preserved_and_missing_ones_minted(self):
        frag = os.path.join(self.tmp, "frag.html")
        Path(frag).write_text(
            '<section class="slide" data-slide-id="slide-deadbeef"><p>one</p></section>\n'
            '<section class="slide"><p>two</p></section>\n',
            encoding="utf-8",
        )
        html = self._make("--content", frag)
        ids = re.findall(r'data-slide-id="([^"]+)"', html)
        self.assertEqual(ids[0], "slide-deadbeef")
        self.assertRegex(ids[1], SLIDE_ID_RE)

    def test_deterministic_ids(self):
        frag = os.path.join(self.tmp, "frag.html")
        Path(frag).write_text('<section class="slide"><p>stable body</p></section>\n', encoding="utf-8")
        a = self._make("--content", frag)
        b = self._make("--content", frag, "--force")
        self.assertEqual(re.findall(r'data-slide-id="([^"]+)"', a),
                         re.findall(r'data-slide-id="([^"]+)"', b))

    def test_create_only_then_force(self):
        self._make("--slides", "1")
        again = _scaffold(self.out, "--slides", "1")
        self.assertEqual(again.returncode, 1)
        self.assertIn("create-only", again.stderr)
        forced = _scaffold(self.out, "--slides", "1", "--force")
        self.assertEqual(forced.returncode, 0, forced.stderr)

    def test_fragment_without_slides_errors(self):
        frag = os.path.join(self.tmp, "empty.html")
        Path(frag).write_text("<section><p>not a slide</p></section>", encoding="utf-8")
        proc = _scaffold(self.out, "--content", frag)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("no <section", proc.stderr)


    def test_main_in_process_covers_branches(self):
        import contextlib
        import io
        from unittest import mock
        out = os.path.join(self.tmp, "ip.html")
        self.assertEqual(deck_scaffold.main(["--slides", "2", "--label", "L", "--out", out]), 0)
        # create-only refusal
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(deck_scaffold.main(["--slides", "2", "--label", "L", "--out", out]), 1)
        # --force overwrites
        self.assertEqual(deck_scaffold.main(["--slides", "2", "--label", "L", "--out", out, "--force"]), 0)
        # --slides 0 invalid
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(deck_scaffold.main(["--slides", "0", "--label", "L", "--out", os.path.join(self.tmp, "z.html")]), 1)
        # --content stdin, explicit key
        with mock.patch.object(sys, "stdin", io.StringIO('<section class="slide"><p>x</p></section>')):
            self.assertEqual(deck_scaffold.main(["--content", "-", "--label", "L", "--key", "deck-explicit-1",
                                                 "--out", os.path.join(self.tmp, "s.html"), "--force"]), 0)
        # fragment with no slide sections -> ValueError branch
        empty = os.path.join(self.tmp, "e.html")
        Path(empty).write_text("<section><p>nope</p></section>", encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(deck_scaffold.main(["--content", empty, "--label", "L",
                                                 "--out", os.path.join(self.tmp, "e2.html")]), 1)
        # refused (demo) key -> make_document ValueError branch
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(deck_scaffold.main(["--slides", "1", "--label", "L", "--key", "commentable-html-demo",
                                                 "--out", os.path.join(self.tmp, "demo.html")]), 1)
        # validator reports errors -> does-not-validate branch
        with mock.patch.object(deck_scaffold._validate, "validate", return_value=(["boom"], [])):
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(deck_scaffold.main(["--slides", "1", "--label", "L",
                                                     "--out", os.path.join(self.tmp, "inv.html")]), 1)
        # validator module unavailable -> skip-validation branch
        with mock.patch.object(deck_scaffold, "_validate", None):
            self.assertEqual(deck_scaffold.main(["--slides", "1", "--label", "L",
                                                 "--out", os.path.join(self.tmp, "noval.html")]), 0)


    def test_existing_ids_and_inject_targets_real_root(self):
        frag = os.path.join(self.tmp, "hasid.html")
        Path(frag).write_text(
            '<section class="slide" data-slide-id="slide-abcdef01"><p>keep</p></section>',
            encoding="utf-8")
        out = os.path.join(self.tmp, "hasid-out.html")
        self.assertEqual(deck_scaffold.main(["--content", frag, "--label", "L", "--out", out]), 0)
        self.assertIn('data-slide-id="slide-abcdef01"', Path(out).read_text(encoding="utf-8"))
        # _inject_deck_mode tags the root carrying the given key, never a decoy with a different key
        html = ('<main id="commentRoot" data-comment-key="my-doc">decoy</main>'
                '<main id="commentRoot" data-comment-key="real-123">real</main>')
        tagged = deck_scaffold._inject_deck_mode(html, "real-123")
        roots = re.findall(r'<main[^>]*id="commentRoot"[^>]*>', tagged)
        self.assertNotIn("data-cmh-mode", roots[0])
        self.assertIn('data-cmh-mode="deck"', roots[1])
        # no-op when the key is absent
        self.assertEqual(deck_scaffold._inject_deck_mode("<main>x</main>", "missing"), "<main>x</main>")
        # idempotent: a second injection does not add a second attribute
        tagged2 = deck_scaffold._inject_deck_mode(tagged, "real-123")
        self.assertEqual(tagged2.count('data-cmh-mode="deck"'), 1)

    def test_scaffold_declares_slides_kind(self):
        html = self._make("--slides", "2")
        self.assertIn('content="slides"', html)

    def test_scaffold_has_legible_presentation_defaults(self):
        html = self._make("--slides", "2")
        body = html.split("BEGIN: commentable-html - CONTENT", 1)[1].split(
            "END: commentable-html - CONTENT", 1)[0]
        # slide content gets an explicit light colour on the dark stage (legible in any theme)
        self.assertIn("--slide-fg", body)
        self.assertIn('data-cmh-mode="deck"] .slide', body)
        # and presentation-scale typography (a large heading size), so it does not render tiny
        self.assertRegex(body, r"font-size:\s*7[0-9]px")

    def test_scaffold_fails_closed_on_remote_media(self):
        # R1: deck_scaffold runs the deck contract (deck_checks), not just base validate.py, so a
        # slide carrying remote media fails closed and NOTHING is written to disk.
        frag = os.path.join(self.tmp, "remote.html")
        Path(frag).write_text(
            '<section class="slide"><img src="http://evil/x.png"><p>x</p></section>',
            encoding="utf-8")
        proc = _scaffold(self.out, "--content", frag)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("remote media", proc.stderr)
        self.assertFalse(os.path.exists(self.out))


if __name__ == "__main__":
    unittest.main()
