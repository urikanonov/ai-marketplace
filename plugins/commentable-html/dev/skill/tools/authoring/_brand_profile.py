"""Reusable brand profile support for commentable-html authoring tools."""
from dataclasses import dataclass
import html as _html
import json
import os
from pathlib import Path
import re

import _toolpath
_toolpath.ensure()
from cmhval import contrast  # noqa: E402


class BrandProfileError(ValueError):
    pass


@dataclass(frozen=True)
class FontFace:
    family: str
    src: str
    fmt: str
    weight: str
    style: str
    display: str


@dataclass(frozen=True)
class BrandProfile:
    label: str
    tokens: tuple
    fonts: tuple
    font_stack: tuple
    mono_font_stack: tuple


_TOKEN_MAP_KEYS = ("tokens", "variables", "vars", "theme")
_TOKEN_NAME_RE = re.compile(r"^--cp-[A-Za-z0-9_-]+$")
_SAFE_VALUE_RE = re.compile(r"^[A-Za-z0-9\s#%.,()+*/_-]+$")
_CSS_FUNCTION_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9_-]*)\s*\(")
_ALLOWED_FUNCTIONS = frozenset({"rgb", "rgba", "var", "calc", "clamp", "min", "max"})
_FORBIDDEN_VALUE_RE = re.compile(r"[{};<>`\\]|/\*|\*/|@|url\s*\(|expression\s*\(|javascript\s*:|data\s*:", re.I)
_FONT_FAMILY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,79}$")
_GENERIC_FAMILIES = frozenset({
    "serif", "sans-serif", "monospace", "cursive", "fantasy", "system-ui",
    "ui-serif", "ui-sans-serif", "ui-monospace", "emoji", "math", "fangsong",
})
_FONT_SRC_RE = re.compile(
    r"^data:(font/(woff2?|ttf|otf)|application/font-woff2?);base64,[A-Za-z0-9+/]+={0,2}$",
    re.I,
)
_FONT_WEIGHT_RE = re.compile(r"^(normal|bold|[1-9]00)(\s+[1-9]00)?$", re.I)
_FONT_STYLE_RE = re.compile(r"^(normal|italic|oblique)$", re.I)
_FONT_DISPLAY_RE = re.compile(r"^(auto|block|swap|fallback|optional)$", re.I)
_BRAND_CONTRAST_PAIRS = (
    ("--cp-text", "--cp-bg", "brand variables --cp-text/--cp-bg"),
    ("--cp-text", "--cp-surface", "brand variables --cp-text/--cp-surface"),
    ("--cp-text", "--cp-bg-elevated", "brand variables --cp-text/--cp-bg-elevated"),
    ("--cp-text-muted", "--cp-bg", "brand variables --cp-text-muted/--cp-bg"),
    ("--cp-text-soft", "--cp-bg", "brand variables --cp-text-soft/--cp-bg"),
    ("--cp-accent-fg", "--cp-accent", "brand variables --cp-accent-fg/--cp-accent"),
    ("--cp-link", "--cp-bg", "brand variables --cp-link/--cp-bg"),
)


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        raise BrandProfileError("brand profile is not valid JSON: %s" % exc)
    except OSError as exc:
        raise BrandProfileError("cannot read brand profile: %s" % exc)
    if not isinstance(data, dict):
        raise BrandProfileError("brand profile must be a JSON object")
    return data


def _known_tokens(seed_html=""):
    text = seed_html or ""
    root = Path(_toolpath.SKILL_ROOT)
    for rel in ("dist/PORTABLE.html", "dist/NONPORTABLE.html", "dist/commentable-html.css"):
        try:
            text += "\n" + (root / rel).read_text(encoding="utf-8")
        except OSError:
            pass
    return frozenset(re.findall(r"--cp-[A-Za-z0-9_-]+", text))


def _first_token_map(data):
    found = [(key, data[key]) for key in _TOKEN_MAP_KEYS if key in data]
    if len(found) > 1:
        raise BrandProfileError("brand profile must use only one token map key")
    top_level = {key: value for key, value in data.items() if isinstance(key, str) and key.startswith("--cp-")}
    if found and top_level:
        raise BrandProfileError("brand profile must not mix top-level --cp-* tokens with a token map")
    if not found:
        return top_level
    key, value = found[0]
    if not isinstance(value, dict):
        raise BrandProfileError("brand profile %s must be an object" % key)
    return value


def _validate_token_value(name, value, known):
    if not isinstance(value, str):
        raise BrandProfileError("brand token %s value must be a string" % name)
    raw = value.strip()
    if not raw:
        raise BrandProfileError("brand token %s value must be non-empty" % name)
    if "}" in raw or ";" in raw:
        raise BrandProfileError("brand token %s value must not contain } or ;" % name)
    if _FORBIDDEN_VALUE_RE.search(raw):
        raise BrandProfileError("brand token %s value contains unsafe CSS syntax" % name)
    if not _SAFE_VALUE_RE.fullmatch(raw):
        raise BrandProfileError("brand token %s value contains unsupported CSS characters" % name)
    for fn in _CSS_FUNCTION_RE.findall(raw):
        if fn.lower() not in _ALLOWED_FUNCTIONS:
            raise BrandProfileError("brand token %s value uses unsupported CSS function %s()" % (name, fn))
    for var_name in re.findall(r"var\(\s*(--[A-Za-z0-9_-]+)", raw):
        if var_name not in known:
            raise BrandProfileError("brand token %s references unknown token %s" % (name, var_name))
    return raw


def _tokens(data, known):
    out = []
    for raw_name, raw_value in _first_token_map(data).items():
        if not isinstance(raw_name, str) or not _TOKEN_NAME_RE.fullmatch(raw_name):
            raise BrandProfileError("unknown --cp-* token %s" % raw_name)
        if raw_name not in known:
            raise BrandProfileError("unknown --cp-* token %s" % raw_name)
        out.append((raw_name, _validate_token_value(raw_name, raw_value, known)))
    return tuple(out)


def _font_format(src):
    mime = src.split(";", 1)[0].split(":", 1)[1].lower()
    if "woff2" in mime:
        return "woff2"
    if "woff" in mime:
        return "woff"
    if "ttf" in mime:
        return "truetype"
    return "opentype"


def _clean_family(value, field="font family"):
    if not isinstance(value, str):
        raise BrandProfileError("%s must be a string" % field)
    family = value.strip().strip("\"'")
    if not family or not _FONT_FAMILY_RE.fullmatch(family):
        raise BrandProfileError("%s contains unsupported characters" % field)
    return family


def _clean_font_stack(value, field):
    if value in (None, ""):
        return ()
    if isinstance(value, str):
        items = [part.strip() for part in value.split(",")]
    elif isinstance(value, list):
        items = value
    else:
        raise BrandProfileError("%s must be a string or array" % field)
    out = []
    for item in items:
        family = _clean_family(item, field)
        out.append(family)
    if not out:
        raise BrandProfileError("%s must contain at least one family" % field)
    return tuple(out)


def _font_faces(data):
    fonts = data.get("fonts")
    if fonts in (None, ""):
        return ()
    if not isinstance(fonts, list):
        raise BrandProfileError("brand profile fonts must be an array")
    out = []
    for index, item in enumerate(fonts, 1):
        if not isinstance(item, dict):
            raise BrandProfileError("brand font %d must be an object" % index)
        family = _clean_family(item.get("family"), "brand font %d family" % index)
        src = item.get("src")
        if not isinstance(src, str) or not _FONT_SRC_RE.fullmatch(src.strip()):
            raise BrandProfileError("brand font %d src must be a local data: font URI" % index)
        src = src.strip()
        weight = str(item.get("weight", "400")).strip()
        style = str(item.get("style", "normal")).strip().lower()
        display = str(item.get("display", "swap")).strip().lower()
        if not _FONT_WEIGHT_RE.fullmatch(weight):
            raise BrandProfileError("brand font %d weight is invalid" % index)
        if not _FONT_STYLE_RE.fullmatch(style):
            raise BrandProfileError("brand font %d style is invalid" % index)
        if not _FONT_DISPLAY_RE.fullmatch(display):
            raise BrandProfileError("brand font %d display is invalid" % index)
        out.append(FontFace(family, src, _font_format(src), weight, style, display))
    return tuple(out)


def load(path, seed_html=""):
    data = _read_json(path)
    known = _known_tokens(seed_html)
    tokens = _tokens(data, known)
    fonts = _font_faces(data)
    font_stack = _clean_font_stack(data.get("fontStack", data.get("font_stack")), "fontStack")
    mono_font_stack = _clean_font_stack(data.get("monoFontStack", data.get("mono_font_stack")), "monoFontStack")
    if not tokens and not fonts and not font_stack and not mono_font_stack:
        raise BrandProfileError("brand profile must define tokens, fonts, fontStack, or monoFontStack")
    return BrandProfile(os.path.basename(path), tokens, fonts, font_stack, mono_font_stack)


def _css_string(value):
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return '"%s"' % escaped


def _font_stack_css(stack):
    parts = []
    for family in stack:
        if family.lower() in _GENERIC_FAMILIES:
            parts.append(family)
        else:
            parts.append(_css_string(family))
    return ", ".join(parts)


def render(profile):
    lines = ['<style data-cmh-brand="%s">' % _html.escape(profile.label, quote=True)]
    for font in profile.fonts:
        lines.extend((
            "@font-face {",
            "  font-family: %s;" % _css_string(font.family),
            "  src: url(%s) format(\"%s\");" % (_css_string(font.src), font.fmt),
            "  font-weight: %s;" % font.weight,
            "  font-style: %s;" % font.style,
            "  font-display: %s;" % font.display,
            "}",
        ))
    if profile.tokens:
        for selector in (":root", 'html[data-theme="dark"]'):
            lines.append("%s {" % selector)
            for name, value in profile.tokens:
                lines.append("  %s: %s;" % (name, value))
            lines.append("}")
    if profile.font_stack:
        lines.append("body { font-family: %s; }" % _font_stack_css(profile.font_stack))
    if profile.mono_font_stack:
        lines.append("code, kbd, .mono { font-family: %s; }" % _font_stack_css(profile.mono_font_stack))
    lines.append("</style>")
    return "\n".join(lines) + "\n"


def _insert_head_style(html, style):
    match = re.search(r"</head\s*>", html, re.I)
    if not match:
        raise BrandProfileError("generated document has no </head> for brand profile")
    return html[:match.start()] + style + html[match.start():]


def contrast_warnings(html):
    warnings = []
    for issue in contrast.find_low_contrast_pairs(html, variable_pairs=_BRAND_CONTRAST_PAIRS):
        warnings.append("brand profile: " + issue.message())
    return warnings


def apply_brand(html, path):
    if not path:
        return html, []
    profile = load(path, seed_html=html)
    branded = _insert_head_style(html, render(profile))
    return branded, contrast_warnings(branded)
