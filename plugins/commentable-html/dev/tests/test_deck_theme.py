#!/usr/bin/env python3
"""Tests for deck theme presets (CMH-DECK-THEME-01).

A deck theme preset is a named JSON profile of allowlisted deck CSS custom properties
(system-font stacks + colors). `_deck_theme.load()` validates it fail-closed (unknown token,
unsafe value, non-color color token, and a preset whose own declared contrast pairs fall below
AA all raise), and `render()` emits a single `<style id="cmh-deck-theme" class="cm-skip">` block
(cm-skip so it never shifts comment text offsets) scoped to the deck stage. `deck_scaffold.py
--theme terminal` produces a deck that still passes `deck_validate.py`.
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
import _deck_theme  # noqa: E402

SCAFFOLD = os.path.join(DECK, "deck_scaffold.py")
THEMES_DIR = os.path.join(DECK, "themes")


class DeckThemeLoadTests(unittest.TestCase):
    def _write(self, obj):
        fd, path = tempfile.mkstemp(suffix=".theme.json")
        os.close(fd)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        Path(path).write_text(json.dumps(obj), encoding="utf-8")
        return path

    def test_terminal_preset_ships_and_lists(self):
        self.assertIn("terminal", _deck_theme.list_presets())
        self.assertTrue(os.path.isfile(os.path.join(THEMES_DIR, "terminal.theme.json")))

    def test_render_emits_cm_skip_scoped_block_with_tokens(self):
        theme = _deck_theme.load("terminal")
        css = _deck_theme.render(theme)
        self.assertIn('id="cmh-deck-theme"', css)
        self.assertIn("cm-skip", css)  # anchor-neutral: never counted in comment offsets
        self.assertIn('data-cmh-deck-theme="terminal"', css)
        # Stage tokens must reach the letterbox/stage ancestors, not only .slide.
        self.assertIn(".deck-viewport", css)
        self.assertIn(".deck-stage", css)
        self.assertIn(".slide", css)
        for token in ("--slide-bg", "--slide-fg", "--stage-bg", "--slide-link",
                      "--cmh-deck-code-bg", "--cmh-deck-tok-kw", "--cmh-deck-table-head-bg"):
            self.assertIn(token, css)

    def test_unknown_token_rejected(self):
        path = self._write({"label": "x", "tokens": {"--slide-bg": "#000", "--cp-evil": "#000"}})
        with self.assertRaises(_deck_theme.DeckThemeError):
            _deck_theme.load(path)

    def test_non_color_value_for_color_token_rejected(self):
        path = self._write({"label": "x", "tokens": {"--slide-bg": "notacolor"}})
        with self.assertRaises(_deck_theme.DeckThemeError):
            _deck_theme.load(path)

    def test_unsafe_value_rejected(self):
        path = self._write({"label": "x", "tokens": {"--slide-bg": "#000;} body{display:none"}})
        with self.assertRaises(_deck_theme.DeckThemeError):
            _deck_theme.load(path)

    def test_preset_level_contrast_self_check_fails_closed(self):
        # A preset whose own declared pair is below AA must fail at load, independent of deck content.
        path = self._write({
            "label": "bad",
            "tokens": {"--slide-bg": "#777777", "--slide-fg": "#888888"},
            "contrastPairs": [["--slide-fg", "--slide-bg"]],
        })
        with self.assertRaises(_deck_theme.DeckThemeError):
            _deck_theme.load(path)

    def test_partial_override_checked_against_defaults(self):
        # Overriding ONLY the code background (leaving the default light code text) is caught by the
        # effective-contrast check, even though the preset does not declare the whole pair.
        path = self._write({"label": "part", "tokens": {"--cmh-deck-code-bg": "#ffffff"}})
        with self.assertRaises(_deck_theme.DeckThemeError):
            _deck_theme.load(path)

    def test_table_head_fg_over_translucent_default_bg_gated(self):
        # A dark table-head text over the DEFAULT translucent table-head background (composited over
        # the slide bg) is caught - the translucent default no longer slips through.
        path = self._write({"label": "t", "tokens": {"--cmh-deck-table-head-fg": "#000000"}})
        with self.assertRaises(_deck_theme.DeckThemeError):
            _deck_theme.load(path)

    def test_diff_fg_checked_over_composited_row(self):
        # A low-contrast diff add colour is caught against the ACTUAL translucent-row-over-code-bg
        # surface, not the bare code background.
        path = self._write({"label": "d", "tokens": {"--cmh-deck-diff-add-fg": "#808080"}})
        with self.assertRaises(_deck_theme.DeckThemeError):
            _deck_theme.load(path)

    def test_diff_body_text_checked_over_composited_row(self):
        # Diff BODY text (code-text) is dim enough to pass over the bare code bg (~4.5:1) but sub-AA
        # over the composited add-row surface - the effective check catches it.
        path = self._write({"label": "b", "tokens": {"--cmh-deck-code-text": "#808080"}})
        with self.assertRaises(_deck_theme.DeckThemeError):
            _deck_theme.load(path)

    def test_default_tokens_match_source(self):
        # _DEFAULT_TOKENS must mirror the real 90-deck.css / ROOT_VARS defaults per token (not just
        # "value appears somewhere"), or the effective-contrast check would gate a partial preset
        # against wrong colours. Also assert every contrast-pair token has a default.
        import re as _re
        import deck_validate
        css = Path(os.path.join(_paths.DEV, "assets", "css", "90-deck.css")).read_text(encoding="utf-8")
        scaffold = Path(os.path.join(DECK, "deck_scaffold.py")).read_text(encoding="utf-8")
        src = css + "\n" + scaffold
        pair_tokens = set()
        for fg, bg, _ in deck_validate.DECK_CONTRAST_VARIABLE_PAIRS:
            pair_tokens.update((fg, bg))
        for tok in pair_tokens:
            self.assertIn(tok, _deck_theme._DEFAULT_TOKENS, f"{tok} missing from _DEFAULT_TOKENS")

        def norm(v):
            return v.strip().replace(" ", "").lower()

        for tok, expected in _deck_theme._DEFAULT_TOKENS.items():
            bindings = set()
            esc = _re.escape(tok)
            for m in _re.finditer(r"var\(\s*" + esc + r"\s*,\s*(rgba?\([^)]*\)|[^)]+)\)", src):
                bindings.add(norm(m.group(1)))
            for m in _re.finditer(esc + r"\s*:\s*([^;}\n]+)", src):
                bindings.add(norm(m.group(1)))
            self.assertIn(norm(expected), bindings,
                          f"{tok} default {expected} not bound in source (drift?); bindings={bindings}")

    def test_terminal_preset_pairs_pass_self_check(self):
        # Should not raise: the shipped preset is AA-clean on its own declared pairs.
        _deck_theme.load("terminal")

    def test_terminal_diff_surfaces_are_aa_over_translucent_rows(self):
        # The diff add/del/hunk row fills are fixed translucent overlays in 90-deck.css; the diff text
        # composites over (tint over code-bg). Verify the terminal token choices clear AA there, since
        # the static validator cannot resolve a translucent backdrop.
        from cmhval import contrast
        tok = dict(_deck_theme.load("terminal").tokens)
        code_bg = tuple(int(tok["--cmh-deck-code-bg"].lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))

        def over(tint, a):
            return "rgb(%d, %d, %d)" % tuple(round(a * t + (1 - a) * b) for t, b in zip(tint, code_bg))
        del_bg = over((248, 113, 113), 0.22)
        add_bg = over((34, 197, 94), 0.20)
        hunk_bg = over((96, 165, 250), 0.16)
        for fg_tok, bg in (("--cmh-deck-diff-del-fg", del_bg), ("--cmh-deck-diff-add-fg", add_bg),
                           ("--cmh-deck-diff-hunk-fg", hunk_bg), ("--cmh-deck-code-soft", del_bg)):
            ratio = contrast.contrast_ratio(tok[fg_tok], bg)
            self.assertGreaterEqual(ratio, 4.5, f"{fg_tok} {tok[fg_tok]} on {bg} = {ratio:.2f}")

    def test_font_bearing_preset_renders_local_font_face(self):
        path = self._write({
            "label": "fonty",
            "tokens": {"--slide-bg": "#000000", "--slide-fg": "#ffffff",
                       "--font-body": "MyFont, monospace"},
            "fonts": [{"family": "MyFont", "src": "data:font/woff2;base64,AAAA", "weight": "400"}],
        })
        css = _deck_theme.render(_deck_theme.load(path))
        self.assertIn("@font-face", css)
        self.assertIn("MyFont", css)

    def test_remote_font_src_rejected(self):
        path = self._write({
            "label": "bad",
            "tokens": {"--slide-bg": "#000000"},
            "fonts": [{"family": "Evil", "src": "https://evil.example/f.woff2"}],
        })
        with self.assertRaises(_deck_theme.DeckThemeError):
            _deck_theme.load(path)

    def test_translucent_backdrop_token_rejected(self):
        # A backdrop that text composites over (--slide-bg) must be opaque - fail closed. Every
        # translucent syntax the color validator admits is rejected (not just comma-form rgba()).
        for value in ("rgba(0,0,0,0.8)", "transparent", "rgb(0 0 0 / 50%)", "rgba(0,0,0,50%)"):
            path = self._write({"label": "trans", "tokens": {"--slide-bg": value, "--slide-fg": "#fff"}})
            with self.assertRaises(_deck_theme.DeckThemeError, msg=value):
                _deck_theme.load(path)

    def test_indeterminate_declared_pair_rejected(self):
        # A declared contrast pair with a translucent (indeterminate) member is rejected fail-closed,
        # not silently skipped - declare pairs only between opaque colours.
        path = self._write({
            "label": "t",
            "tokens": {"--slide-fg": "#ffffff", "--slide-border": "rgba(0,0,0,0.4)",
                       "--slide-bg": "#000000"},
            "contrastPairs": [["--slide-fg", "--slide-border"]],
        })
        with self.assertRaises(_deck_theme.DeckThemeError):
            _deck_theme.load(path)


class DeckThemeScaffoldTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        self.out = os.path.join(self.tmp, "deck.html")

    def _scaffold(self, *args):
        proc = subprocess.run(
            [sys.executable, SCAFFOLD, "--label", "Themed Deck", "--source", self.out,
             "--out", self.out, *args],
            capture_output=True, text=True, encoding="utf-8",
        )
        return proc

    def test_scaffold_theme_terminal_is_valid_and_themed(self):
        proc = self._scaffold("--slides", "3", "--theme", "terminal")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        html = Path(self.out).read_text(encoding="utf-8")
        self.assertIn('id="cmh-deck-theme"', html)
        self.assertIn('data-cmh-deck-theme="terminal"', html)
        self.assertIn("cm-skip", html)
        self.assertIn("#0d1117", html)  # terminal slide bg baked in

    def test_scaffold_unknown_theme_fails_closed(self):
        proc = self._scaffold("--slides", "2", "--theme", "nope")
        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse(os.path.exists(self.out))

    def test_component_override_collapse_is_rejected(self):
        # A preset with a readable slide level but a collapsed COMPONENT pair (code text == code bg)
        # is rejected - proving DECK_CONTRAST_VARIABLE_PAIRS covers the component surfaces, and the
        # effective check resolves defaults for the members the preset does not override.
        bad = {"--slide-bg": "#0d1117", "--slide-fg": "#ffffff",
               "--cmh-deck-code-bg": "#808080", "--cmh-deck-code-text": "#808080"}
        path = os.path.join(self.tmp, "badcode.theme.json")
        Path(path).write_text(json.dumps({"label": "badcode", "tokens": bad}), encoding="utf-8")
        proc = self._scaffold("--slides", "1", "--theme", path)
        self.assertNotEqual(proc.returncode, 0)
        self.assertRegex(proc.stderr, r"code text/bg|below AA")


def _rel_luminance(hex_color):
    v = hex_color.lstrip("#")
    r, g, b = (int(v[i:i + 2], 16) / 255.0 for i in (0, 2, 4))

    def lin(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


class LightPresetTests(unittest.TestCase):
    """CMH-DECK-THEME-06: the shipped light presets (paper, editorial) load, self-check AA, and are
    genuinely light (a distinct family from the dark terminal preset)."""

    NEW_PRESETS = ("paper", "editorial")

    def test_new_light_presets_ship_and_list(self):
        listed = _deck_theme.list_presets()
        for name in self.NEW_PRESETS:
            self.assertIn(name, listed)
            self.assertTrue(os.path.isfile(os.path.join(THEMES_DIR, name + ".theme.json")))

    def test_every_shipped_preset_loads_and_self_checks(self):
        # load() runs both the composited effective-contrast check and the preset's own contrastPairs
        # self-check, so a clean load IS the per-preset AA "golden". Covers any future preset too.
        for name in _deck_theme.list_presets():
            with self.subTest(preset=name):
                theme = _deck_theme.load(name)  # raises DeckThemeError on any AA/opacity violation
                self.assertTrue(theme.tokens)

    def test_new_presets_are_light(self):
        # A light preset has a high-luminance slide background and a low-luminance foreground - the
        # opposite of the dark terminal preset, pinning the new family so a regression to dark fails.
        for name in self.NEW_PRESETS:
            with self.subTest(preset=name):
                tokens = json.loads(Path(os.path.join(THEMES_DIR, name + ".theme.json")).read_text(
                    encoding="utf-8"))["tokens"]
                self.assertGreater(_rel_luminance(tokens["--slide-bg"]), 0.7)
                self.assertLess(_rel_luminance(tokens["--slide-fg"]), 0.15)

    def test_new_presets_carry_frontend_slides_provenance(self):
        for name in self.NEW_PRESETS:
            with self.subTest(preset=name):
                data = json.loads(Path(os.path.join(THEMES_DIR, name + ".theme.json")).read_text(encoding="utf-8"))
                self.assertIn("frontend-slides", data.get("adaptedFrom", ""))
                self.assertRegex(str(data.get("sourceCommit", "")), r"^[0-9a-f]{7,40}$")

    def test_new_presets_render_a_scoped_labelled_block(self):
        for name in self.NEW_PRESETS:
            with self.subTest(preset=name):
                css = _deck_theme.render(_deck_theme.load(name))
                self.assertIn('id="cmh-deck-theme"', css)
                self.assertIn("cm-skip", css)
                self.assertIn('data-cmh-deck-theme="%s"' % name, css)
                for token in ("--slide-bg", "--slide-fg", "--cmh-deck-code-bg", "--cmh-deck-table-head-bg"):
                    self.assertIn(token, css)


if __name__ == "__main__":
    unittest.main()
