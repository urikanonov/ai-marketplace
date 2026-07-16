#!/usr/bin/env python3
"""Deck theme presets for commentable-html decks (CMH-DECK-THEME-01).

A preset is a named JSON profile under ``tools/deck/themes/<name>.theme.json`` of allowlisted deck
CSS custom properties (system-font stacks plus colors, and optional local ``data:`` fonts). It
renders a single ``<style id="cmh-deck-theme" class="cm-skip">`` block scoped to the deck stage.

The block is ``cm-skip`` so the runtime comment TreeWalker never counts its text: a re-theme of any
length therefore never shifts the absolute ``{start,end}`` offsets stored for existing comments.
Value/font safety reuses the brand-profile validators so both authoring paths share one guard and
cannot drift. Color tokens are additionally type-checked as parseable colors, and the preset's own
declared contrast pairs are verified AA at load time (fail-closed) independent of any deck content.
"""
from dataclasses import dataclass
import html as _html
import json
import os
from pathlib import Path
import re

import _toolpath
_toolpath.ensure()
import _brand_profile as _bp  # noqa: E402  shared value/font validators (single source of truth)
import deck_validate  # noqa: E402  shared DECK_CONTRAST_VARIABLE_PAIRS (single source of truth)
from cmhval import contrast  # noqa: E402

THEMES_DIR = Path(__file__).resolve().parent / "themes"

# Allowlisted deck theme tokens. Font tokens are font stacks; every other token is a color.
_FONT_TOKENS = frozenset({"--font-body", "--font-display"})
_COLOR_TOKENS = frozenset({
    "--stage-bg", "--slide-bg", "--slide-fg", "--slide-fg-muted", "--slide-accent",
    "--slide-accent-fg", "--slide-border", "--slide-link",
    "--cmh-deck-code-bg", "--cmh-deck-code-bg-soft", "--cmh-deck-code-border",
    "--cmh-deck-code-text", "--cmh-deck-code-muted", "--cmh-deck-code-soft",
    "--cmh-deck-tok-kw", "--cmh-deck-tok-fn", "--cmh-deck-tok-str", "--cmh-deck-tok-num",
    "--cmh-deck-tok-com", "--cmh-deck-tok-op",
    "--cmh-deck-table-head-bg", "--cmh-deck-table-head-fg", "--cmh-deck-table-head-border",
    "--cmh-deck-diff-add-fg", "--cmh-deck-diff-del-fg", "--cmh-deck-diff-hunk-fg",
    "--cmh-deck-mermaid-node-fill", "--cmh-deck-mermaid-node-stroke", "--cmh-deck-mermaid-label",
    "--cmh-deck-mermaid-edge", "--cmh-deck-mermaid-edge-label-bg", "--cmh-deck-mermaid-edge-label-fg",
})
ALLOWED_TOKENS = _FONT_TOKENS | _COLOR_TOKENS

# Text composites over these surfaces, so a translucent value makes contrast indeterminate (the static
# gate cannot resolve it). Require them opaque, fail-closed at load.
_BACKDROP_TOKENS = frozenset({
    "--stage-bg", "--slide-bg", "--slide-accent", "--cmh-deck-code-bg", "--cmh-deck-code-bg-soft",
    "--cmh-deck-table-head-bg", "--cmh-deck-mermaid-node-fill", "--cmh-deck-mermaid-edge-label-bg",
})

# Declaring the tokens on this selector list makes stage tokens (--stage-bg) reach the letterbox
# ancestors (.deck-viewport / .deck-stage), overrides :root ROOT_VARS (more specific), and, at equal
# specificity to 90-deck.css's `.slide` component vars, wins by later source order (the block is
# injected into the content body, after the head layer sheet).
_SELECTOR = (
    '#commentRoot[data-cmh-mode="deck"] .deck-viewport,\n'
    '#commentRoot[data-cmh-mode="deck"] .deck-stage,\n'
    '#commentRoot[data-cmh-mode="deck"] .slide'
)
_MIN_AA = 4.5
_STAGE_MARK = '<style id="cmh-deck-stage">'
THEME_ID = "cmh-deck-theme"
# Match ONLY the theme tag - no surrounding whitespace - so inserting or replacing it changes no
# text node outside the cm-skip block, keeping every stored comment offset byte-stable.
_THEME_BLOCK_RE = re.compile(r'<style id="cmh-deck-theme".*?</style>', re.S)


class DeckThemeError(ValueError):
    pass


@dataclass(frozen=True)
class DeckTheme:
    label: str
    tokens: tuple      # ((name, value), ...)
    fonts: tuple       # (_bp.FontFace, ...)


def list_presets():
    if not THEMES_DIR.is_dir():
        return []
    suffix = ".theme.json"
    return sorted(p.name[:-len(suffix)] for p in THEMES_DIR.glob("*" + suffix))


def _resolve_spec(spec):
    text = str(spec)
    looks_like_path = (
        text.endswith(".json")
        or os.sep in text
        or (os.altsep and os.altsep in text)
    )
    if looks_like_path:
        return Path(spec)
    cand = THEMES_DIR / (text + ".theme.json")
    if not cand.is_file():
        raise DeckThemeError(
            "unknown deck theme preset %r (available: %s)"
            % (text, ", ".join(list_presets()) or "none"))
    return cand


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        raise DeckThemeError("deck theme preset not found: %s" % path)
    except OSError as exc:
        raise DeckThemeError("cannot read deck theme preset: %s" % exc)
    except json.JSONDecodeError as exc:
        raise DeckThemeError("deck theme preset is not valid JSON: %s" % exc)
    if not isinstance(data, dict):
        raise DeckThemeError("deck theme preset must be a JSON object")
    return data


def _tokens(data):
    raw = data.get("tokens")
    if not isinstance(raw, dict) or not raw:
        raise DeckThemeError("deck theme preset must define a non-empty tokens object")
    out = []
    for name, value in raw.items():
        if name not in ALLOWED_TOKENS:
            raise DeckThemeError("unknown deck theme token %r" % name)
        try:
            clean = _bp._validate_token_value(name, value, ALLOWED_TOKENS)
        except _bp.BrandProfileError as exc:
            raise DeckThemeError(str(exc))
        if name in _COLOR_TOKENS:
            rgba = contrast.parse_css_color(clean)
            if rgba is None:
                raise DeckThemeError(
                    "deck theme token %s value %r is not a valid color" % (name, clean))
            # Alpha from the authoritative parser covers every translucent syntax it admits
            # (transparent, rgba(), space/slash and % alpha), not just comma-form rgba().
            alpha = rgba[3] if len(rgba) > 3 else 1.0
            if name in _BACKDROP_TOKENS and alpha < 1.0:
                raise DeckThemeError(
                    "deck theme backdrop token %s must be opaque (text composites over it): %r"
                    % (name, clean))
        out.append((name, clean))
    return tuple(out)


def _self_check_contrast(label, tokens, data):
    pairs = data.get("contrastPairs")
    if pairs in (None, ""):
        return
    if not isinstance(pairs, list):
        raise DeckThemeError("deck theme contrastPairs must be an array")
    values = dict(tokens)
    for pair in pairs:
        if not isinstance(pair, list) or len(pair) != 2:
            raise DeckThemeError("deck theme contrastPairs entries must be [fg, bg] arrays")
        fg_name, bg_name = pair
        if fg_name not in values or bg_name not in values:
            raise DeckThemeError(
                "deck theme %s contrast pair %s/%s references an undeclared token"
                % (label, fg_name, bg_name))
        try:
            ratio = contrast.contrast_ratio(values[fg_name], values[bg_name])
        except ValueError:
            ratio = None
        if ratio is None:
            # A declared pair must be between opaque, resolvable colours; a translucent/indeterminate
            # member cannot be statically verified, so reject rather than silently skip.
            raise DeckThemeError(
                "deck theme %s contrast pair %s/%s is indeterminate (a member is translucent); "
                "declare pairs only between opaque colours" % (label, fg_name, bg_name))
        if ratio < _MIN_AA:
            raise DeckThemeError(
                "deck theme %s pair %s/%s contrast %.2f is below AA %.1f (%s on %s)"
                % (label, fg_name, bg_name, ratio, _MIN_AA, values[fg_name], values[bg_name]))


def load(spec):
    path = _resolve_spec(spec)
    data = _read_json(path)
    label = str(data.get("label") or Path(path).name[:-len(".theme.json")]).strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,39}", label):
        raise DeckThemeError("deck theme label %r is invalid" % label)
    tokens = _tokens(data)
    try:
        fonts = _bp._font_faces(data)
    except _bp.BrandProfileError as exc:
        raise DeckThemeError(str(exc))
    _check_effective_contrast(label, tokens)
    _self_check_contrast(label, tokens, data)
    return DeckTheme(label, tokens, fonts)


# Byte-exact defaults for the component tokens that appear in DECK_CONTRAST_VARIABLE_PAIRS, mirroring
# the var() fallbacks in dev/assets/css/90-deck.css and deck_scaffold.ROOT_VARS. A component var's
# default lives in the head layer CSS (outside the content region the static gate scans), so a preset
# that overrides only ONE member of a pair would leave the pair unresolvable and unchecked. Resolving
# the non-overridden member against these defaults lets a partial preset stay author-friendly while a
# dangerous override (e.g. a light code background left with the default light code text) still fails.
# Kept in sync with 90-deck.css by the unthemed "fallback golden" Playwright test.
_DEFAULT_TOKENS = {
    "--stage-bg": "#0b0b0f", "--slide-bg": "#0b0b0f", "--slide-fg": "#f4f4f5",
    "--slide-fg-muted": "#a1a1aa", "--slide-accent": "#93c5fd", "--slide-accent-fg": "#0b0b0f",
    "--slide-link": "#93c5fd",
    "--cmh-deck-code-bg": "#0f172a", "--cmh-deck-code-bg-soft": "#111827",
    "--cmh-deck-code-text": "#f8fafc", "--cmh-deck-code-muted": "#cbd5e1",
    "--cmh-deck-code-soft": "#94a3b8",
    "--cmh-deck-tok-kw": "#d8b4fe", "--cmh-deck-tok-fn": "#93c5fd", "--cmh-deck-tok-str": "#86efac",
    "--cmh-deck-tok-num": "#fbbf24", "--cmh-deck-tok-com": "#94a3b8", "--cmh-deck-tok-op": "#cbd5e1",
    "--cmh-deck-table-head-bg": "rgba(15,23,42,0.92)", "--cmh-deck-table-head-fg": "#f8fafc",
    "--cmh-deck-diff-add-fg": "#86efac", "--cmh-deck-diff-del-fg": "#fca5a5",
    "--cmh-deck-diff-hunk-fg": "#bfdbfe",
    "--cmh-deck-mermaid-node-fill": "#1e293b", "--cmh-deck-mermaid-label": "#f8fafc",
    "--cmh-deck-mermaid-edge-label-bg": "#111827", "--cmh-deck-mermaid-edge-label-fg": "#f8fafc",
}


def _composite(over, base):
    """Composite an (r,g,b[,a]) colour over an opaque (r,g,b) backdrop, returning opaque (r,g,b)."""
    a = over[3] if len(over) > 3 else 1.0
    return tuple(int(round(a * o + (1 - a) * b)) for o, b in zip(over[:3], base[:3]))


def _rgb_str(rgb):
    return "rgb(%d, %d, %d)" % (rgb[0], rgb[1], rgb[2])


# The diff row fills are fixed translucent overlays in 90-deck.css; diff sign/text composites over
# (row fill over the code background), not over the bare code background.
_DIFF_ROW_FILL = {
    "--cmh-deck-diff-add-fg": (34, 197, 94, 0.20),
    "--cmh-deck-diff-del-fg": (248, 113, 113, 0.22),
    "--cmh-deck-diff-hunk-fg": (96, 165, 250, 0.16),
}


def _check_effective_contrast(label, tokens):
    declared = dict(tokens)

    def eff(name):
        return declared.get(name, _DEFAULT_TOKENS.get(name))

    def rgba(name):
        v = eff(name)
        return contrast.parse_css_color(v) if v is not None else None

    slide_bg = rgba("--slide-bg")
    code_bg = rgba("--cmh-deck-code-bg")
    for fg, bg, desc in deck_validate.DECK_CONTRAST_VARIABLE_PAIRS:
        # Only check a pair one of whose members the preset actually overrides; a fully-default pair
        # is the shipped, already-verified baseline.
        if fg not in declared and bg not in declared:
            continue
        fg_c = rgba(fg)
        if fg_c is None:
            continue
        # Resolve the ACTUAL opaque backdrop the text renders over, compositing translucent surfaces
        # so no real surface goes unchecked (diff rows over code bg; a translucent bg over slide bg).
        if fg in _DIFF_ROW_FILL and code_bg is not None:
            base = _composite(_DIFF_ROW_FILL[fg], code_bg)
        else:
            bg_c = rgba(bg)
            if bg_c is None:
                continue
            if len(bg_c) > 3 and bg_c[3] < 1:
                if slide_bg is None:
                    continue
                base = _composite(bg_c, slide_bg[:3])
            else:
                base = bg_c[:3]
        fg_rgb = _composite(fg_c, base) if len(fg_c) > 3 and fg_c[3] < 1 else fg_c[:3]
        ratio = contrast.contrast_ratio(_rgb_str(fg_rgb), _rgb_str(base))
        if ratio is None or ratio >= _MIN_AA:
            continue
        raise DeckThemeError(
            "deck theme %s effective %s contrast %.2f is below AA %.1f (%s on %s)"
            % (label, desc, ratio, _MIN_AA, _rgb_str(fg_rgb), _rgb_str(base)))

    # Diff BODY text (--cmh-deck-code-text) and gutter/sign (--cmh-deck-code-soft) also render over
    # the translucent diff rows, not just the bare code background, so verify them over each
    # composited row surface too when the preset touches the code palette.
    if code_bg is not None and any(
            t in declared for t in ("--cmh-deck-code-text", "--cmh-deck-code-soft",
                                     "--cmh-deck-code-bg")):
        for text_tok in ("--cmh-deck-code-text", "--cmh-deck-code-soft"):
            fg_c = rgba(text_tok)
            if fg_c is None:
                continue
            for fill in _DIFF_ROW_FILL.values():
                base = _composite(fill, code_bg[:3])
                fg_rgb = _composite(fg_c, base) if len(fg_c) > 3 and fg_c[3] < 1 else fg_c[:3]
                ratio = contrast.contrast_ratio(_rgb_str(fg_rgb), _rgb_str(base))
                if ratio is not None and ratio < _MIN_AA:
                    raise DeckThemeError(
                        "deck theme %s diff-row text %s contrast %.2f is below AA %.1f (%s on %s)"
                        % (label, text_tok, ratio, _MIN_AA, _rgb_str(fg_rgb), _rgb_str(base)))


def render(theme):
    lines = ['<style id="cmh-deck-theme" class="cm-skip" data-cmh-deck-theme="%s">'
             % _html.escape(theme.label, quote=True)]
    for font in theme.fonts:
        lines.extend((
            "@font-face {",
            "  font-family: %s;" % _bp._css_string(font.family),
            '  src: url(%s) format("%s");' % (_bp._css_string(font.src), font.fmt),
            "  font-weight: %s;" % font.weight,
            "  font-style: %s;" % font.style,
            "  font-display: %s;" % font.display,
            "}",
        ))
    lines.append("%s {" % _SELECTOR)
    for name, value in theme.tokens:
        lines.append("  %s: %s;" % (name, value))
    lines.append("}")
    lines.append("</style>")
    return "\n".join(lines) + "\n"


def insert_or_replace(html, theme_css):
    """Insert the theme block, or replace an existing one, without touching any other text.

    Idempotent and anchor-neutral: the theme block is spliced in with NO surrounding whitespace, so
    neither a first-time insert nor a replace adds or removes any text node outside the cm-skip block
    - every stored comment offset stays byte-stable. If a ``cmh-deck-theme`` block already exists it is
    replaced in place; otherwise the block is inserted immediately after the ``cmh-deck-stage`` block.
    A deck with no ``cmh-deck-stage`` block is rejected (fail-closed).
    """
    block = theme_css.strip()
    # Gate on the real block (not a loose substring) so slide prose mentioning the id can never send
    # us down the replace path and silently no-op; without a real block we fall through and insert.
    if _THEME_BLOCK_RE.search(html):
        return _THEME_BLOCK_RE.sub(lambda _m: block, html, count=1)
    idx = html.find(_STAGE_MARK)
    if idx == -1:
        raise DeckThemeError(
            "deck has no <style id=\"cmh-deck-stage\"> block to anchor the theme (not a deck?)")
    close = html.find("</style>", idx)
    if close == -1:
        raise DeckThemeError("deck <style id=\"cmh-deck-stage\"> block is not closed")
    after = close + len("</style>")
    return html[:after] + block + html[after:]
