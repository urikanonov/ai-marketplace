#!/usr/bin/env python3
"""Tests for dev/tools/fs_theme_convert.py (CMH-DECK-THEME-04).

The converter is a deterministic bootstrap: given a frontend-slides STYLE_PRESETS.md style it emits a
STARTER <name>.theme.json whose colours map to CMH deck tokens by a documented luminance/saturation
heuristic and whose fonts are substituted for the approved system stacks (never a remote family). It is
a maintainer aid, so the STARTER is not required to pass the strict theme validator - but every token it
emits must be in the theme allowlist, it must be deterministic, hermetic (an inline preset needs no
network and no vendored file), and carry frontend-slides provenance. Written as unittest so CI's
`unittest discover` gates it.
"""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402  shared pkg/dev split path constants; also puts tools/ buckets on sys.path

sys.path.insert(0, _paths.DEV_TOOLS)
import fs_theme_convert as conv  # noqa: E402
import deck_fix_fonts as ff  # noqa: E402  shipped font-stack mapping the converter reuses
import _deck_theme  # noqa: E402  shipped theme loader (source of the token allowlist)

APPROVED_STACKS = {ff.SANS_STACK, ff.SERIF_STACK, ff.DISPLAY_STACK, ff.MONO_STACK}

# A self-contained preset section in the STYLE_PRESETS.md shape, so the heuristic tests never depend on
# the vendored file's exact current content (which changes on an upstream refresh).
INLINE_MD = """\
### 1. Sample Vibe

**Typography:**
- Display: `Archivo Black` (900)
- Body: `Space Grotesk` (400)

**Colors:**
```css
:root {
    --bg-primary: #101014;
    --bg-gradient: linear-gradient(135deg, #101014 0%, #202028 100%);
    --card-bg: #22cc66;
    --text-primary: #f5f5f7;
    --muted: #767680;
}
```

### 2. Other Vibe

**Colors:**
```css
:root {
    --bg: #ffffff;
    --fg: #000000;
}
```

### 3. Unknown Fonts

**Typography:**
- Display: `Poppins` (700)
- Body: `Nunito` (400)

**Colors:**
```css
:root {
    --bg: #0a0a0a;
    --fg: #fafafa;
    --accent: #4488ff;
}
```

### 4. Single Colour

**Colors:**
```css
:root {
    --only: #ff3300;
}
```
"""

# A fixed sentinel so the heuristic tests are hermetic - they never read the vendored UPSTREAM.md.
SENTINEL_COMMIT = "0123456789abcdef0123456789abcdef01234567"


class ConvertHeuristicTests(unittest.TestCase):
    def setUp(self):
        self.theme = conv.convert("Sample Vibe", md_text=INLINE_MD, commit=SENTINEL_COMMIT)
        self.tokens = self.theme["tokens"]

    def test_darkest_colour_becomes_the_slide_and_stage_background(self):
        self.assertEqual(self.tokens["--slide-bg"], "#101014")
        self.assertEqual(self.tokens["--stage-bg"], "#101014")

    def test_lightest_colour_becomes_the_foreground(self):
        self.assertEqual(self.tokens["--slide-fg"], "#f5f5f7")

    def test_most_saturated_mid_colour_becomes_the_accent(self):
        self.assertEqual(self.tokens["--slide-accent"], "#22cc66")
        self.assertEqual(self.tokens["--slide-link"], "#22cc66")

    def test_accent_fg_is_the_higher_contrast_of_black_or_white(self):
        # #22cc66 is a light-ish green, so the deck-ink candidate (#0b0b0f) out-contrasts white.
        self.assertEqual(self.tokens["--slide-accent-fg"], "#0b0b0f")

    def test_muted_is_a_distinct_mid_colour_not_the_accent(self):
        self.assertEqual(self.tokens["--slide-fg-muted"], "#767680")
        self.assertNotEqual(self.tokens["--slide-fg-muted"], self.tokens["--slide-accent"])

    def test_muted_falls_back_to_a_neutral_gray_when_no_spare_colour(self):
        theme = conv.convert("Other Vibe", md_text=INLINE_MD, commit=SENTINEL_COMMIT)
        self.assertEqual(theme["tokens"]["--slide-fg-muted"], "#a1a1aa")

    def test_fonts_are_substituted_for_approved_system_stacks(self):
        for key in ("--font-body", "--font-display"):
            self.assertIn(self.tokens[key], APPROVED_STACKS, "%s is not an approved system stack" % key)

    def test_unrecognized_font_family_maps_to_a_system_stack_not_null(self):
        # Poppins / Nunito are not in deck_fix_fonts' explicit tables (category "unknown"); the
        # converter must still emit a real system stack, never a JSON null the theme loader rejects.
        theme = conv.convert("Unknown Fonts", md_text=INLINE_MD, commit=SENTINEL_COMMIT)
        for key in ("--font-body", "--font-display"):
            self.assertIsNotNone(theme["tokens"][key])
            self.assertIn(theme["tokens"][key], APPROVED_STACKS)

    def test_no_token_carries_a_remote_or_upstream_font_family(self):
        blob = json.dumps(self.tokens).lower()
        for remote in ("archivo", "grotesk", "http", "fonts.googleapis", "@import"):
            self.assertNotIn(remote, blob)

    def test_every_emitted_token_is_in_the_theme_allowlist(self):
        for name in self.tokens:
            self.assertIn(name, _deck_theme.ALLOWED_TOKENS, "%s is not an allowlisted deck token" % name)

    def test_output_is_a_flagged_starter_with_frontend_slides_provenance(self):
        self.assertTrue(self.theme.get("_starter"))
        self.assertIn("review", self.theme.get("_review", "").lower())
        self.assertIn("frontend-slides", self.theme["adaptedFrom"])
        self.assertTrue(str(self.theme.get("sourceCommit", "")).strip())

    def test_label_is_slugified(self):
        self.assertEqual(self.theme["label"], "sample-vibe")

    def test_conversion_is_deterministic(self):
        self.assertEqual(
            conv.convert("Sample Vibe", md_text=INLINE_MD, commit=SENTINEL_COMMIT), self.theme)

    def test_degenerate_single_colour_palette_raises(self):
        # A prose-only palette that encodes just one hex must fail closed, not emit an all-identical
        # (zero-contrast) starter that looks valid.
        with self.assertRaises(conv.ConvertError):
            conv.convert("Single Colour", md_text=INLINE_MD, commit=SENTINEL_COMMIT)

    def test_four_digit_hex_with_alpha_is_parsed(self):
        self.assertEqual(conv._hex_to_rgb("#1234"), (17, 34, 51))
        self.assertEqual(conv._hex_to_rgb("#123"), (17, 34, 51))

    def test_unknown_preset_raises(self):
        with self.assertRaises(conv.ConvertError):
            conv.convert("No Such Preset", md_text=INLINE_MD, commit=SENTINEL_COMMIT)

    def test_partial_name_match_is_case_insensitive(self):
        self.assertEqual(
            conv.convert("sample", md_text=INLINE_MD, commit=SENTINEL_COMMIT)["displayName"],
            "Sample Vibe")


class ConvertRealFileTests(unittest.TestCase):
    """Smoke test against the actually vendored STYLE_PRESETS.md so the parser tracks the real format."""

    def test_bold_signal_from_the_vendored_presets_file(self):
        theme = conv.convert("Bold Signal")
        # Bold Signal: bg #1a1a1a, card #FF5722, text #ffffff.
        self.assertEqual(theme["tokens"]["--slide-bg"], "#1a1a1a")
        self.assertEqual(theme["tokens"]["--slide-fg"], "#ffffff")
        self.assertEqual(theme["tokens"]["--slide-accent"], "#ff5722")
        # sourceCommit comes from the vendored UPSTREAM.md, matching the ships-with commit.
        self.assertRegex(theme["sourceCommit"], r"^[0-9a-f]{7,40}$")


class ConvertCliTests(unittest.TestCase):
    def test_cli_writes_a_starter_file(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        out = os.path.join(tmp, "sample.theme.json")
        # The CLI reads the vendored STYLE_PRESETS.md, so exercise it on a real preset name and confirm
        # it produces valid, loadable-shaped JSON.
        rc = conv.main(["--preset", "Bold Signal", "--out", out])
        self.assertEqual(rc, 0)
        data = json.loads(Path(out).read_text(encoding="utf-8"))
        self.assertTrue(data.get("_starter"))
        self.assertIn("tokens", data)

    def test_cli_unknown_preset_exits_nonzero(self):
        rc = conv.main(["--preset", "Definitely Not A Preset Name"])
        self.assertEqual(rc, 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
