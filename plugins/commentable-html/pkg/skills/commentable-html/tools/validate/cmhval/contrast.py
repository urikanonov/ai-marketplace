#!/usr/bin/env python3
"""WCAG contrast checks for author-time HTML tooling."""
from dataclasses import dataclass
from html.parser import HTMLParser
import math
import re

DEFAULT_MIN_CONTRAST_RATIO = 4.5

_NAMED_COLORS = {
    "black": (0, 0, 0, 1.0),
    "white": (255, 255, 255, 1.0),
    "red": (255, 0, 0, 1.0),
    "green": (0, 128, 0, 1.0),
    "blue": (0, 0, 255, 1.0),
    "gray": (128, 128, 128, 1.0),
    "grey": (128, 128, 128, 1.0),
    "transparent": (0, 0, 0, 0.0),
}
_HEX_RE = re.compile(r"#([0-9a-f]{3}|[0-9a-f]{6})\b", re.IGNORECASE)
_RGB_FUNC_RE = re.compile(r"rgba?\([^)]*\)", re.IGNORECASE)
_VAR_FUNC_RE = re.compile(r"var\(", re.IGNORECASE)


@dataclass(frozen=True)
class ContrastIssue:
    source: str
    foreground: str
    background: str
    ratio: float
    threshold: float

    def message(self):
        return (
            f"{self.source}: low text contrast - foreground {self.foreground} on "
            f"background {self.background} has contrast {self.ratio:.2f}:1 below "
            f"{self.threshold:.2f}:1; adjust one color before publishing."
        )


def _matching_paren(value, open_index):
    depth = 0
    quote = None
    for i in range(open_index, len(value)):
        ch = value[i]
        if quote:
            if ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
    return -1


def _split_top_level(value, sep):
    out = []
    cur = []
    depth = 0
    quote = None
    for ch in value:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
            cur.append(ch)
        elif ch == "(":
            depth += 1
            cur.append(ch)
        elif ch == ")":
            depth = max(0, depth - 1)
            cur.append(ch)
        elif ch == sep and depth == 0:
            out.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur).strip())
    return out


def _resolve_vars(value, variables=None):
    if not variables:
        return value
    out = value
    for _ in range(8):
        m = _VAR_FUNC_RE.search(out)
        if not m:
            return out
        open_index = m.end() - 1
        close = _matching_paren(out, open_index)
        if close < 0:
            return out
        inner = out[open_index + 1:close]
        parts = _split_top_level(inner, ",")
        name = parts[0].strip() if parts else ""
        fallback = parts[1].strip() if len(parts) > 1 else ""
        replacement = variables.get(name, fallback)
        out = out[:m.start()] + replacement + out[close + 1:]
    return out


def _parse_channel(token):
    token = token.strip()
    try:
        raw = float(token[:-1]) if token.endswith("%") else float(token)
        if not math.isfinite(raw):
            return None
        if token.endswith("%"):
            value = round(raw * 255 / 100)
        else:
            value = round(raw)
    except (OverflowError, ValueError):
        return None
    if 0 <= value <= 255:
        return int(value)
    return None


def _parse_alpha(token):
    token = token.strip()
    try:
        raw = float(token[:-1]) if token.endswith("%") else float(token)
        if not math.isfinite(raw):
            return None
        value = raw / 100 if token.endswith("%") else raw
    except (OverflowError, ValueError):
        return None
    if 0 <= value <= 1:
        return value
    return None


def _parse_rgb_function(value):
    try:
        m = re.fullmatch(r"rgba?\((.*)\)", value, re.IGNORECASE)
        if not m:
            return None
        body = m.group(1).strip()
        if "," in body:
            parts = _split_top_level(body, ",")
            if len(parts) not in (3, 4):
                return None
            channels = parts[:3]
            alpha_part = parts[3] if len(parts) == 4 else None
        else:
            raw = body.replace("/", " / ").split()
            alpha_part = None
            if raw.count("/") > 1:
                return None
            if "/" in raw:
                slash = raw.index("/")
                if slash != 3 or len(raw) != 5:
                    return None
                alpha_part = raw[slash + 1]
                raw = raw[:slash]
            elif len(raw) != 3:
                return None
            channels = raw
        if len(channels) != 3:
            return None
        rgb = [_parse_channel(part) for part in channels]
        if any(part is None for part in rgb):
            return None
        alpha = 1.0 if alpha_part is None else _parse_alpha(alpha_part)
        if alpha is None:
            return None
        return rgb[0], rgb[1], rgb[2], alpha
    except (OverflowError, ValueError):
        return None


def parse_css_color(value, variables=None):
    value = _resolve_vars((value or "").strip(), variables).strip()
    low = value.lower()
    if low in ("currentcolor", "current-color", "inherit", "initial", "unset", "revert"):
        return None
    m = re.fullmatch(r"#([0-9a-f]{3}|[0-9a-f]{6})", low, re.IGNORECASE)
    if m:
        raw = m.group(1)
        if len(raw) == 3:
            raw = "".join(ch * 2 for ch in raw)
        return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16), 1.0
    parsed = _parse_rgb_function(value)
    if parsed:
        return parsed
    return _NAMED_COLORS.get(low)


def _relative_luminance(color):
    channels = []
    for component in color[:3]:
        c = component / 255
        channels.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _composite(foreground, background):
    alpha = foreground[3]
    return tuple(round(foreground[i] * alpha + background[i] * (1 - alpha)) for i in range(3)) + (1.0,)


def contrast_ratio(foreground, background, variables=None):
    fg = parse_css_color(foreground, variables)
    bg = parse_css_color(background, variables)
    if fg is None or bg is None or bg[3] < 1:
        raise ValueError("both colors must resolve to concrete foreground/background colors")
    if fg[3] < 1:
        fg = _composite(fg, bg)
    lum1 = _relative_luminance(fg)
    lum2 = _relative_luminance(bg)
    hi, lo = max(lum1, lum2), min(lum1, lum2)
    return (hi + 0.05) / (lo + 0.05)


def _strip_css_comments(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _matching_brace(value, open_index):
    depth = 0
    quote = None
    for i in range(open_index, len(value)):
        ch = value[i]
        if quote:
            if ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
    return -1


def _iter_css_rules(css, skip_keyframes=False):
    text = _strip_css_comments(css)
    pos = 0
    while True:
        open_index = text.find("{", pos)
        if open_index < 0:
            return
        close = _matching_brace(text, open_index)
        if close < 0:
            return
        selector = text[pos:open_index].strip()
        body = text[open_index + 1:close]
        lower_selector = selector.lower()
        if "{" in body:
            nested_skip = skip_keyframes or lower_selector.startswith("@keyframes")
            if not nested_skip:
                yield from _iter_css_rules(body, skip_keyframes=nested_skip)
        elif selector and not selector.startswith("@") and ":" in body:
            yield selector, body
        pos = close + 1


def _parse_declaration_items(style):
    items = []
    for item in _split_top_level(style, ";"):
        if ":" not in item:
            continue
        name, value = item.split(":", 1)
        name = name.strip().lower()
        value = value.strip()
        if name:
            items.append((name, value))
    return items


def _parse_declarations(style):
    declarations = {}
    for name, value in _parse_declaration_items(style):
        declarations[name] = value
    return declarations


def _strip_ignored_color_text(value):
    out = []
    i = 0
    while i < len(value):
        lower = value[i:].lower()
        if lower.startswith("url("):
            close = _matching_paren(value, i + 3)
            if close >= 0:
                out.append(" ")
                i = close + 1
                continue
        ch = value[i]
        if ch in ("'", '"'):
            quote = ch
            i += 1
            while i < len(value) and value[i] != quote:
                i += 1
            i += 1 if i < len(value) else 0
            out.append(" ")
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _extract_css_color(value, variables=None):
    resolved = _resolve_vars(value or "", variables).strip()
    if not resolved or "gradient(" in resolved.lower():
        return None
    direct = parse_css_color(resolved, variables)
    if direct:
        return resolved
    searchable = _strip_ignored_color_text(resolved)
    for m in _HEX_RE.finditer(searchable):
        if parse_css_color(m.group(0), variables):
            return m.group(0)
    for m in _RGB_FUNC_RE.finditer(searchable):
        if parse_css_color(m.group(0), variables):
            return m.group(0)
    m = _VAR_FUNC_RE.search(value or "")
    if m:
        close = _matching_paren(value, m.end() - 1)
        if close >= 0:
            candidate = value[m.start():close + 1]
            if parse_css_color(candidate, variables):
                return candidate
    for token in re.findall(r"\b[a-zA-Z]+\b", searchable):
        if token.lower() in _NAMED_COLORS:
            return token
    return None


def _background_decl(declarations, items=None):
    if items is not None:
        for name, value in reversed(items):
            if name in ("background", "background-color"):
                return value
    return declarations.get("background-color") or declarations.get("background")


class _StyleScanner(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.style_blocks = []
        self.inline_styles = []
        self._style_attrs = None
        self._style_body = []

    @staticmethod
    def _attrs_dict(attrs):
        return {(name or "").lower(): value or "" for name, value in attrs}

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attr_map = self._attrs_dict(attrs)
        if "style" in attr_map:
            self.inline_styles.append((tag, attr_map, attr_map["style"]))
        if tag == "style":
            self._style_attrs = attr_map
            self._style_body = []

    def handle_startendtag(self, tag, attrs):
        attr_map = self._attrs_dict(attrs)
        if "style" in attr_map:
            self.inline_styles.append((tag.lower(), attr_map, attr_map["style"]))

    def handle_data(self, data):
        if self._style_attrs is not None:
            self._style_body.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "style" and self._style_attrs is not None:
            self.style_blocks.append("".join(self._style_body))
            self._style_attrs = None
            self._style_body = []


def _element_source(tag, attrs):
    label = tag
    if attrs.get("id"):
        label += "#" + attrs["id"]
    classes = [part for part in attrs.get("class", "").split() if part]
    if classes:
        label += "." + ".".join(classes)
    return f"element <{label}> inline style"


def _collect_variables(style_blocks):
    variables = {}
    for css in style_blocks:
        for _selector, body in _iter_css_rules(css):
            declarations = _parse_declarations(body)
            for name, value in declarations.items():
                if name.startswith("--"):
                    variables[name] = value
    return variables


def _issue_for_pair(source, fg_value, bg_value, variables, threshold):
    fg_token = _extract_css_color(fg_value, variables)
    bg_token = _extract_css_color(bg_value, variables)
    if not fg_token or not bg_token:
        return None
    try:
        ratio = contrast_ratio(fg_token, bg_token, variables)
    except ValueError:
        return None
    if ratio >= threshold:
        return None
    return ContrastIssue(source, fg_token, bg_token, ratio, threshold)


def find_low_contrast_pairs(html, threshold=DEFAULT_MIN_CONTRAST_RATIO, variable_pairs=()):
    scanner = _StyleScanner()
    scanner.feed(html)
    scanner.close()
    variables = _collect_variables(scanner.style_blocks)
    issues = []

    for css in scanner.style_blocks:
        for selector, body in _iter_css_rules(css):
            items = _parse_declaration_items(body)
            declarations = dict(items)
            local_vars = dict(variables)
            local_vars.update({k: v for k, v in declarations.items() if k.startswith("--")})
            bg_value = _background_decl(declarations, items)
            if "color" in declarations and bg_value:
                issue = _issue_for_pair(f"selector {selector}", declarations["color"], bg_value,
                                        local_vars, threshold)
                if issue:
                    issues.append(issue)

    for item in variable_pairs:
        fg_name, bg_name = item[:2]
        source = item[2] if len(item) > 2 else f"variables {fg_name}/{bg_name}"
        if fg_name in variables and bg_name in variables:
            issue = _issue_for_pair(source, variables[fg_name], variables[bg_name], variables, threshold)
            if issue:
                issues.append(issue)

    for tag, attrs, style in scanner.inline_styles:
        items = _parse_declaration_items(style)
        declarations = dict(items)
        bg_value = _background_decl(declarations, items)
        if "color" not in declarations or not bg_value:
            continue
        local_vars = dict(variables)
        local_vars.update({k: v for k, v in declarations.items() if k.startswith("--")})
        issue = _issue_for_pair(_element_source(tag, attrs), declarations["color"], bg_value,
                                local_vars, threshold)
        if issue:
            issues.append(issue)

    seen = set()
    unique = []
    for issue in issues:
        key = (issue.source, issue.foreground, issue.background, round(issue.ratio, 4))
        if key not in seen:
            seen.add(key)
            unique.append(issue)
    return unique
