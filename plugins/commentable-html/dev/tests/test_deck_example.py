"""CMH-DECK-SHOWCASE-01: the shipped showcase deck example is a valid commentable-html deck
(kind=slides, `data-cmh-mode="deck"`, unique slide ids, no remote egress) AND rebuilds
byte-identically from its independent source in dev/examples/src/.

The byte-identical rebuild is the guard against a hand-edit or a stale/clobbered committed
copy of the shipped deck, mirroring the report-example self-source contract in
tests/test_examples.py.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import contextlib
import io
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402
SKILL = _paths.PKG
DECK = os.path.join(_paths.EXAMPLES, "deck-showcase.html")
DECK_SRC = os.path.join(_paths.DEV, "examples", "src", "deck-showcase.html")
DECK_PROMPT = os.path.join(_paths.EXAMPLES, "prompt-showcase.md")
BUILD_PY = os.path.join(_paths.DEV_TOOLS, "build.py")
DECK_VALIDATE = os.path.join(SKILL, "tools", "deck", "deck_validate.py")


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _read_version():
    with open(os.path.join(_paths.DEV, "VERSION"), encoding="utf-8") as fh:
        return fh.read().strip()


class DeckScaffoldHighlightTests(unittest.TestCase):
    """CMH-HL-04: deck_scaffold bakes syntax highlighting by default (opt out with --no-highlight)
    and surfaces validator warnings, so a scaffolded deck is never raw."""

    _SLIDE = ('<section class="slide"><h2>S</h2>'
              '<pre><code class="language-python">def f(): return 1</code></pre></section>')

    def _scaffold(self, fragment, extra=None):
        import deck_scaffold  # noqa: E402
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        out = os.path.join(d, "deck.html")
        argv = ["--content", "-", "--label", "Deck", "--out", out] + (extra or [])
        err = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO(fragment)), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = deck_scaffold.main(argv)
        return code, out, err.getvalue()

    def test_scaffold_bakes_highlighting_by_default(self):
        code, out, err = self._scaffold(self._SLIDE)
        self.assertEqual(code, 0, err)
        self.assertIn('<span class="cmh-code-kw">def</span>', _read(out))

    def test_scaffold_no_highlight_leaves_raw_and_warns(self):
        code, out, err = self._scaffold(self._SLIDE, extra=["--no-highlight"])
        self.assertEqual(code, 0, err)
        html = _read(out)
        self.assertNotIn('<span class="cmh-code-kw">def</span>', html)
        self.assertIn("warning", err.lower())


class DeckExampleTests(unittest.TestCase):
    def test_deck_example_and_prompt_exist(self):
        self.assertTrue(os.path.isfile(DECK), "shipped deck example is missing: " + DECK)
        self.assertTrue(os.path.isfile(DECK_SRC), "deck example source is missing: " + DECK_SRC)
        self.assertTrue(os.path.isfile(DECK_PROMPT), "deck prompt is missing: " + DECK_PROMPT)

    def test_showcase_prompt_prescribes_features_and_slide_outline(self):
        prompt = _read(DECK_PROMPT)
        for required in [
            "Comment on anything",
            "Chart.js charts",
            "Mermaid diagrams",
            "drag-and-drop triage board",
            "rendered code diffs",
            "syntax-highlighted code and KQL",
            "layered checklist",
            "Copy all",
            "handled-comment pruning",
            "Export Offline",
            "split-screen slide-overview navigator",
            "strict validator",
            "Slide outline",
        ]:
            self.assertIn(required, prompt)

    def test_deck_declares_slides_kind_and_deck_mode(self):
        html = _read(DECK)
        m = re.search(r'<meta name="commentable-html-kind" content="([^"]+)"', html)
        self.assertIsNotNone(m, "no commentable-html-kind meta in the deck example")
        self.assertEqual(m.group(1), "slides",
                         "the deck example must declare kind=slides, got " + m.group(1))
        roots = re.findall(r'<main\b[^>]*\bid="commentRoot"[^>]*>', html)
        self.assertTrue(roots, "no <main id=commentRoot> in the deck example")
        self.assertIn('data-cmh-mode="deck"', roots[-1],
                      "the deck example's active #commentRoot must carry data-cmh-mode=deck")

    def test_deck_validates_clean(self):
        r = subprocess.run([sys.executable, DECK_VALIDATE, DECK], capture_output=True, text=True, cwd=SKILL)
        self.assertEqual(r.returncode, 0,
                         "deck_validate failed:\nstdout=" + r.stdout + "\nstderr=" + r.stderr)

    def test_deck_embeds_current_version(self):
        version = _read_version()
        html = _read(DECK)
        meta = re.search(r'<meta name="commentable-html-version" content="([0-9.]+)"', html)
        const = re.search(r'const CMH_VERSION = "([0-9.]+)"', html)
        self.assertIsNotNone(meta, "no version <meta> in the deck example")
        self.assertIsNotNone(const, "no CMH_VERSION const in the deck example")
        self.assertEqual(meta.group(1), version, "deck <meta> version is stale (run build.py)")
        self.assertEqual(const.group(1), version, "deck CMH_VERSION is stale (run build.py)")

    def test_deck_data_doc_source_matches_shipped_filename(self):
        html = _read(DECK)
        m = re.search(r'<main\b[^>]*\bid="commentRoot"[^>]*\bdata-doc-source="([^"]*)"', html)
        if m is None:
            m = re.search(r'<main\b[^>]*\bdata-doc-source="([^"]*)"[^>]*\bid="commentRoot"', html)
        self.assertIsNotNone(m, "the deck example is missing data-doc-source")
        self.assertEqual(m.group(1), os.path.basename(DECK),
                         "deck example data-doc-source does not match the shipped filename")

    def test_build_check_flags_a_hand_edit_to_the_deck_content(self):
        # The shipped deck is a pure artifact of its independent source in dev/examples/src/;
        # --check must catch a hand-edit inside the CONTENT region.
        with tempfile.TemporaryDirectory() as d:
            assets = os.path.join(d, "assets")
            out_dir = os.path.join(d, "skill")
            shutil.copytree(_paths.ASSETS, assets)
            shutil.copytree(_paths.DIST, os.path.join(out_dir, "dist"))
            shutil.copytree(_paths.EXAMPLES, os.path.join(out_dir, "examples"))
            base = [sys.executable, BUILD_PY, "--assets-dir", assets, "--out-dir", out_dir]
            self.assertEqual(subprocess.run(base + ["--check"], capture_output=True, text=True).returncode, 0,
                             "freshly copied tree should be in sync")
            deck = os.path.join(out_dir, "examples", "deck-showcase.html")
            html = _read(deck)
            poisoned = re.sub(r'(<main\b[^>]*\bid="commentRoot"[^>]*>)',
                              r'\1<p>POISON-DECK-DRIFT</p>', html, count=1)
            self.assertNotEqual(poisoned, html, "could not poison the deck content region")
            with open(deck, "w", encoding="utf-8", newline="") as fh:
                fh.write(poisoned)
            r = subprocess.run(base + ["--check"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertIn("deck-showcase.html", r.stdout + r.stderr)

    def test_build_check_flags_an_orphaned_deck_with_no_source(self):
        # A shipped deck-*.html with no dev/examples/src source is a pure artifact validated
        # against nothing; --check must flag it as orphaned (regressed if _EXAMPLE_NAME_RE
        # drops deck- support).
        with tempfile.TemporaryDirectory() as d:
            assets = os.path.join(d, "assets")
            out_dir = os.path.join(d, "skill")
            shutil.copytree(_paths.ASSETS, assets)
            shutil.copytree(_paths.DIST, os.path.join(out_dir, "dist"))
            shutil.copytree(_paths.EXAMPLES, os.path.join(out_dir, "examples"))
            base = [sys.executable, BUILD_PY, "--assets-dir", assets, "--out-dir", out_dir]
            self.assertEqual(subprocess.run(base + ["--check"], capture_output=True, text=True).returncode, 0,
                             "freshly copied tree should be in sync")
            orphan = os.path.join(out_dir, "examples", "deck-orphan.html")
            shutil.copyfile(os.path.join(out_dir, "examples", "deck-showcase.html"), orphan)
            r = subprocess.run(base + ["--check"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertIn("deck-orphan.html", r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
