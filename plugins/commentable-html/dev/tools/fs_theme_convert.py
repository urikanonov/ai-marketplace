#!/usr/bin/env python3
"""Convert a frontend-slides STYLE_PRESETS.md style into a STARTER native deck theme preset (#336).

A deterministic bootstrap for the maintainer refresh flow: it reads a style's ``:root`` colour palette
and typography from the vendored ``STYLE_PRESETS.md``, maps the remote display/body/mono fonts to the
approved system stacks (reusing ``deck_fix_fonts``), and assigns the palette to CMH deck tokens by a
documented luminance/saturation heuristic. The output is a STARTER a human reviews and runs through
``deck_theme.py`` / ``deck_validate.py`` (which enforce AA contrast and opaque backdrops) before it
ships - the upstream->CMH mapping needs judgment, which is exactly why the port happens once at merge
time rather than per deck. It never writes into ``tools/deck/themes/`` itself.

Usage (run from the skill root):
    python dev/tools/fs_theme_convert.py --preset "Terminal Green"
    python dev/tools/fs_theme_convert.py --preset "Bold Signal" --out tmp/bold-signal.theme.json
"""
import argparse
import json
import os
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent / "skill"  # relocated stage (dev/skill); was pkg/skills/commentable-html
VENDOR = SKILL / "vendor" / "frontend-slides"
sys.path.insert(0, str(SKILL / "tools" / "deck"))
import deck_fix_fonts as _ff  # noqa: E402  reuse the approved font-stack mapping

_HEX_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b")
_VAR_RE = re.compile(r"(--[a-z0-9-]+)\s*:\s*([^;]+);", re.I)
_FONT_LINE_RE = re.compile(r"-\s*(Display|Body|Mono)\s*:\s*`([^`]+)`", re.I)
_TYPO_INLINE_RE = re.compile(r"\*\*Typography:\*\*\s*`([^`]+)`(?:\s*\+\s*`([^`]+)`)?", re.I)


class ConvertError(ValueError):
    pass


def _slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")


def _hex_to_rgb(value):
    v = value.strip().lstrip("#")
    if len(v) in (3, 4):
        v = "".join(c * 2 for c in v)
    if len(v) < 6:
        return None
    try:
        return tuple(int(v[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None


def _luminance(rgb):
    def lin(c):
        c /= 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def _saturation(rgb):
    r, g, b = (c / 255.0 for c in rgb)
    mx, mn = max(r, g, b), min(r, g, b)
    return 0.0 if mx == 0 else (mx - mn) / mx


# Candidate accent-text colours - the deck's near-black ink and pure white (NOT pure black, so the
# choice is made by real contrast, not a luminance threshold that assumes #000).
_DARK_FG = "#0b0b0f"
_LIGHT_FG = "#ffffff"


def _contrast(rgb_a, rgb_b):
    la, lb = _luminance(rgb_a), _luminance(rgb_b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _best_text_color(rgb):
    dark = _contrast(rgb, _hex_to_rgb(_DARK_FG))
    light = _contrast(rgb, _hex_to_rgb(_LIGHT_FG))
    return _DARK_FG if dark >= light else _LIGHT_FG


def _font_stack(family):
    cat = _ff._category(_ff._normalize_family(family), set())
    return _ff._stack_for(cat) or _ff.SANS_STACK


def _vendored_commit():
    text = (VENDOR / "UPSTREAM.md").read_text(encoding="utf-8")
    m = re.search(r"Vendored commit:\s*`([0-9a-f]{7,40})`", text)
    return m.group(1) if m else "unknown"


def _find_section(md, preset):
    want = preset.strip().lower()
    blocks = re.split(r"^###\s+", md, flags=re.M)
    for block in blocks[1:]:
        lines = block.splitlines()
        if not lines:
            continue
        heading = lines[0].strip()
        # Headings look like "1. Bold Signal"; match on the name part.
        name = re.sub(r"^\d+\.\s*", "", heading).strip()
        if want in name.lower():
            return name, block
    raise ConvertError("preset %r not found in STYLE_PRESETS.md" % preset)


def _collect_colors(block):
    colors = []
    css = re.search(r"```css(.*?)```", block, re.S)
    scope = css.group(1) if css else block
    for name, value in _VAR_RE.findall(scope):
        hexes = _HEX_RE.findall(value)
        if len(hexes) != 1:  # skip gradients / multi-colour values
            continue
        rgb = _hex_to_rgb(hexes[0])
        if rgb is not None:
            colors.append((name.lower(), hexes[0].lower(), rgb))
    # A prose "Colors:" line (specialty themes have no css block) - harvest bare hexes too.
    if not colors:
        for hx in _HEX_RE.findall(block):
            rgb = _hex_to_rgb(hx)
            if rgb is not None:
                colors.append(("", hx.lower(), rgb))
    if not colors:
        raise ConvertError("no colours found in the preset section")
    return colors


def _fonts(block):
    out = {}
    for kind, fam in _FONT_LINE_RE.findall(block):
        out[kind.lower()] = fam.split(",")[0].strip()
    if not out:
        m = _TYPO_INLINE_RE.search(block)
        if m:
            out["display"] = m.group(1).split(",")[0].strip()
            if m.group(2):
                out["body"] = m.group(2).split(",")[0].strip()
    return out


def convert(preset, md_text=None, commit=None):
    md = md_text if md_text is not None else (VENDOR / "STYLE_PRESETS.md").read_text(encoding="utf-8")
    name, block = _find_section(md, preset)
    colors = _collect_colors(block)
    if len({c[1] for c in colors}) < 2:
        raise ConvertError(
            "preset %r yields fewer than 2 distinct colours (%r) - too few to seed a legible theme; "
            "author the palette by hand" % (preset, sorted({c[1] for c in colors})))
    by_lum = sorted(colors, key=lambda c: _luminance(c[2]))
    darkest = by_lum[0]
    lightest = by_lum[-1]
    # Accent: the most saturated colour that is neither the darkest bg nor the lightest fg.
    mids = [c for c in colors if c[1] not in (darkest[1], lightest[1])] or colors
    accent = max(mids, key=lambda c: _saturation(c[2]))
    # Accent text: the deck-ink or white candidate with the higher real WCAG contrast on the accent.
    accent_fg = _best_text_color(accent[2])
    # Muted: a mid-luminance colour distinct from bg/fg/accent, else a neutral gray.
    muted_pool = [c for c in colors if c[1] not in (darkest[1], lightest[1], accent[1])]
    muted = (sorted(muted_pool, key=lambda c: _luminance(c[2]))[len(muted_pool) // 2][1]
             if muted_pool else "#a1a1aa")
    fonts = _fonts(block)
    display = _font_stack(fonts.get("display", ""))
    body = _font_stack(fonts.get("body") or fonts.get("mono") or fonts.get("display") or "")
    tokens = {
        "--stage-bg": darkest[1],
        "--slide-bg": darkest[1],
        "--slide-fg": lightest[1],
        "--slide-fg-muted": muted,
        "--slide-accent": accent[1],
        "--slide-accent-fg": accent_fg,
        "--slide-border": "rgba(255,255,255,0.22)",
        "--slide-link": accent[1],
        "--font-body": body,
        "--font-display": display,
    }
    commit = commit if commit is not None else _vendored_commit()
    return {
        "label": _slug(name),
        "displayName": name,
        "_starter": True,
        "_review": ("STARTER generated by dev/tools/fs_theme_convert.py - review the token mapping, "
                    "add the component (--cmh-deck-*) tokens and contrastPairs, then validate with "
                    "deck_theme.py / deck_validate.py (AA contrast + opaque backdrops are enforced)."),
        "adaptedFrom": ("Color and name inspired by frontend-slides STYLE_PRESETS.md '%s' "
                        "(Zara Zhang, MIT)." % name),
        "sourceCommit": commit,
        "tokens": tokens,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Convert a frontend-slides style to a STARTER deck theme.")
    ap.add_argument("--preset", required=True, help="STYLE_PRESETS.md style name (e.g. 'Bold Signal')")
    ap.add_argument("--out", help="write the starter JSON here (default: stdout)")
    args = ap.parse_args(argv)
    try:
        data = convert(args.preset)
    except ConvertError as exc:
        print("fs_theme_convert: %s" % exc, file=sys.stderr)
        return 1
    text = json.dumps(data, indent=2) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print("fs_theme_convert: wrote starter preset to %s (review before shipping)" % args.out)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
