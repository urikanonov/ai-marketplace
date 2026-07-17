#!/usr/bin/env python3
"""WCAG contrast checks for author-time HTML tooling."""
from dataclasses import dataclass
from html.parser import HTMLParser
import math
import re

DEFAULT_MIN_CONTRAST_RATIO = 4.5
DEFAULT_MIN_STROKE_CONTRAST_RATIO = 3.0

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
    kind: str = "text"

    def message(self):
        label = "text contrast" if self.kind == "text" else "stroke contrast"
        role = "foreground" if self.kind == "text" else "stroke"
        return (
            f"{self.source}: low {label} - {role} {self.foreground} on "
            f"background {self.background} has contrast {self.ratio:.2f}:1 below "
            f"{self.threshold:.2f}:1; adjust one color before publishing."
        )


@dataclass
class _DomNode:
    tag: str
    attrs: dict
    parent: object = None
    children: object = None
    text_parts: object = None
    order: int = 0
    color_raw: str = None
    background_raw: str = None
    stroke_raw: str = None
    variables: object = None

    def __post_init__(self):
        if self.children is None:
            self.children = []
        if self.text_parts is None:
            self.text_parts = []
        if self.variables is None:
            self.variables = {}


@dataclass(frozen=True)
class _SelectorRule:
    selector: str
    parts: tuple
    specificity: tuple
    order: int
    items: tuple


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


def _composite_rgba(foreground, background):
    alpha = foreground[3] + background[3] * (1 - foreground[3])
    if alpha <= 0:
        return 0, 0, 0, 0.0
    return tuple(
        round((foreground[i] * foreground[3] + background[i] * background[3] * (1 - foreground[3])) / alpha)
        for i in range(3)
    ) + (alpha,)


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
        self.style_media = []
        self.style_is_brand = []
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
            self.style_media.append((self._style_attrs or {}).get("media", ""))
            self.style_is_brand.append("data-cmh-brand" in (self._style_attrs or {}))
            self._style_attrs = None
            self._style_body = []


class _DocumentScanner(_StyleScanner):
    def __init__(self):
        super().__init__()
        self.root = _DomNode("__doc__", {})
        self._stack = [self.root]
        self._order = 0

    @staticmethod
    def _node(tag, attrs, order):
        return _DomNode(tag.lower(), attrs, order=order)

    def _push_node(self, tag, attrs):
        node = self._node(tag, attrs, self._order)
        self._order += 1
        node.parent = self._stack[-1]
        node.parent.children.append(node)
        self._stack.append(node)
        return node

    def handle_starttag(self, tag, attrs):
        super().handle_starttag(tag, attrs)
        self._push_node(tag, self._attrs_dict(attrs))

    def handle_startendtag(self, tag, attrs):
        super().handle_startendtag(tag, attrs)
        node = self._node(tag, self._attrs_dict(attrs), self._order)
        self._order += 1
        node.parent = self._stack[-1]
        node.parent.children.append(node)

    def handle_data(self, data):
        super().handle_data(data)
        if self._stack:
            self._stack[-1].text_parts.append(data)

    def handle_endtag(self, tag):
        super().handle_endtag(tag)
        low = tag.lower()
        while len(self._stack) > 1:
            node = self._stack.pop()
            if node.tag == low:
                return


def _element_source(tag, attrs):
    label = tag
    if attrs.get("id"):
        label += "#" + attrs["id"]
    classes = [part for part in attrs.get("class", "").split() if part]
    if classes:
        label += "." + ".".join(classes)
    return f"element <{label}>"


def _collect_variables(style_blocks):
    variables = {}
    for css in style_blocks:
        for _selector, body in _iter_css_rules(css):
            declarations = _parse_declarations(body)
            for name, value in declarations.items():
                if name.startswith("--"):
                    variables[name] = value
    return variables


def _split_selector_parts(selector):
    out = []
    cur = []
    depth = 0
    quote = None
    for ch in selector:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
            cur.append(ch)
        elif ch in ("[", "("):
            depth += 1
            cur.append(ch)
        elif ch in ("]", ")"):
            depth = max(0, depth - 1)
            cur.append(ch)
        elif ch.isspace() and depth == 0:
            if cur:
                out.append("".join(cur).strip())
                cur = []
        else:
            cur.append(ch)
    if cur:
        out.append("".join(cur).strip())
    return out


def _expand_where(selector):
    m = re.search(r":where\(", selector)
    if not m:
        return [selector]
    open_index = m.end() - 1
    close = _matching_paren(selector, open_index)
    if close < 0:
        return [selector]
    prefix = selector[:m.start()]
    suffix = selector[close + 1:]
    inner = selector[open_index + 1:close]
    expanded = []
    for option in _split_top_level(inner, ","):
        expanded.extend(_expand_where(prefix + option.strip() + suffix))
    return expanded


def _parse_selector_compound(raw):
    raw = raw.strip()
    if not raw:
        return None
    token = {"tag": None, "id": None, "classes": set(), "attrs": [], "root": False}
    i = 0
    while i < len(raw):
        if raw.startswith(":root", i):
            token["root"] = True
            i += 5
            continue
        ch = raw[i]
        if ch == "*":
            i += 1
            continue
        if ch == ".":
            m = re.match(r"\.([A-Za-z0-9_-]+)", raw[i:])
            if not m:
                return None
            token["classes"].add(m.group(1))
            i += len(m.group(0))
            continue
        if ch == "#":
            m = re.match(r"#([A-Za-z0-9_-]+)", raw[i:])
            if not m:
                return None
            token["id"] = m.group(1)
            i += len(m.group(0))
            continue
        if ch == "[":
            end = raw.find("]", i + 1)
            if end < 0:
                return None
            inner = raw[i + 1:end].strip()
            if "=" in inner:
                name, value = inner.split("=", 1)
                name = name.strip().lower()
                value = value.strip().strip('"').strip("'")
                token["attrs"].append((name, value))
            else:
                token["attrs"].append((inner.lower(), None))
            i = end + 1
            continue
        if ch == ":":
            return None
        m = re.match(r"[A-Za-z][A-Za-z0-9_-]*", raw[i:])
        if not m:
            return None
        token["tag"] = m.group(0).lower()
        i += len(m.group(0))
    return token


def _parse_selector(selector):
    if any(ch in selector for ch in (">", "+", "~")):
        return None
    parts = []
    for raw in _split_selector_parts(selector):
        compound = _parse_selector_compound(raw)
        if compound is None:
            return None
        parts.append(compound)
    return tuple(parts) if parts else None


def _selector_specificity(parts):
    ids = 0
    classes = 0
    tags = 0
    for part in parts:
        ids += 1 if part["id"] else 0
        classes += len(part["classes"]) + len(part["attrs"]) + (1 if part["root"] else 0)
        tags += 1 if part["tag"] else 0
    return ids, classes, tags


def _selector_matches_part(node, part):
    if part["root"] and not (node.parent and node.parent.tag == "__doc__"):
        return False
    if part["tag"] and node.tag != part["tag"]:
        return False
    if part["id"] and node.attrs.get("id") != part["id"]:
        return False
    classes = {cls for cls in node.attrs.get("class", "").split() if cls}
    if not part["classes"].issubset(classes):
        return False
    for name, value in part["attrs"]:
        if name not in node.attrs:
            return False
        if value is not None and node.attrs.get(name) != value:
            return False
    return True


def _selector_matches(node, parts):
    cur = node
    for part in reversed(parts):
        while cur is not None and not _selector_matches_part(cur, part):
            cur = cur.parent
        if cur is None or cur.tag == "__doc__":
            return False
        cur = cur.parent
    return True


def _collect_rules(style_blocks):
    rules = []
    order = 0
    for css in style_blocks:
        for selector_text, body in _iter_css_rules(css):
            items = tuple(_parse_declaration_items(body))
            for selector in _split_top_level(selector_text, ","):
                for expanded in _expand_where(selector.strip()):
                    parts = _parse_selector(expanded)
                    if parts is None:
                        continue
                    rules.append(_SelectorRule(
                        selector=expanded.strip(),
                        parts=parts,
                        specificity=_selector_specificity(parts),
                        order=order,
                        items=items,
                    ))
                    order += 1
    return rules


def _winner_beats(current_key, new_key):
    return current_key is None or new_key >= current_key


def _compute_tree_styles(root, rules):
    interesting = {"color", "background", "background-color", "stroke", "stroke-width"}

    def walk(node, inherited_color=None, inherited_vars=None):
        inherited_vars = dict(inherited_vars or {})
        winners = {}
        for rule in rules:
            if not _selector_matches(node, rule.parts):
                continue
            for idx, (name, value) in enumerate(rule.items):
                if name not in interesting and not name.startswith("--"):
                    continue
                key = rule.specificity + (rule.order, idx)
                if _winner_beats(winners.get(name, (None, None))[0], key):
                    winners[name] = (key, value)

        inline_items = _parse_declaration_items(node.attrs.get("style", ""))
        inline_spec = (10_000, 0, 0)
        for idx, (name, value) in enumerate(inline_items):
            if name not in interesting and not name.startswith("--"):
                continue
            key = inline_spec + (node.order, idx)
            if _winner_beats(winners.get(name, (None, None))[0], key):
                winners[name] = (key, value)

        variables = dict(inherited_vars)
        for name, (_key, value) in winners.items():
            if name.startswith("--"):
                variables[name] = _resolve_vars(value, variables)

        raw_color = winners.get("color", (None, inherited_color))[1] or inherited_color
        if raw_color and parse_css_color(raw_color, variables) is None:
            raw_color = inherited_color

        bg = None
        bg_key = None
        for prop in ("background-color", "background"):
            if prop in winners and _winner_beats(bg_key, winners[prop][0]):
                bg_key = winners[prop][0]
                bg = winners[prop][1]

        stroke = winners.get("stroke", (None, None))[1]
        if stroke and stroke.strip().lower() in ("currentcolor", "current-color"):
            stroke = raw_color

        node.color_raw = raw_color
        node.background_raw = bg
        node.stroke_raw = stroke
        node.variables = variables
        for child in node.children:
            walk(child, inherited_color=raw_color, inherited_vars=variables)

    for child in root.children:
        walk(child)


def _rgba_to_token(color):
    return f"rgb({color[0]}, {color[1]}, {color[2]})"


def _effective_background(node):
    cur = node
    carry = None
    while cur is not None and cur.tag != "__doc__":
        token = _extract_css_color(cur.background_raw, cur.variables) if cur.background_raw else None
        if token:
            color = parse_css_color(token, cur.variables)
            if color is None:
                token = None
            elif carry is None:
                if color[3] >= 1:
                    return token, color
                carry = color
            else:
                top = carry
                if top[3] < 1:
                    carry = _composite_rgba(top, color)
                else:
                    return _rgba_to_token(top), top
                if color[3] >= 1:
                    return _rgba_to_token(carry), carry
        cur = cur.parent
    if carry is not None and carry[3] >= 1:
        return _rgba_to_token(carry), carry
    return None, None


def _node_text_content(node):
    text = list(node.text_parts)
    for child in node.children:
        if child.tag in ("style", "script"):
            continue
        text.append(_node_text_content(child))
    return "".join(text)


def _has_visible_text(node):
    if node.tag in ("style", "script", "svg", "path", "marker"):
        return False
    return bool(_node_text_content(node).strip())


def _connectorish(node):
    if node.tag not in ("path", "line", "polyline", "polygon"):
        return False
    if node.parent and node.parent.tag == "marker":
        return True
    label = " ".join([
        node.tag,
        node.attrs.get("class", ""),
        node.parent.attrs.get("class", "") if node.parent else "",
    ]).lower()
    return any(token in label for token in ("edge", "arrow", "connector", "flowchart-link"))


def _issue_for_tokens(source, fg_token, bg_token, threshold, variables=None, kind="text"):
    if not fg_token or not bg_token:
        return None
    try:
        ratio = contrast_ratio(fg_token, bg_token, variables)
    except ValueError:
        return None
    if ratio >= threshold:
        return None
    return ContrastIssue(source, fg_token, bg_token, ratio, threshold, kind=kind)


def _computed_element_issues(scanner, threshold, stroke_threshold):
    rules = _collect_rules(scanner.style_blocks)
    if not rules and not scanner.inline_styles:
        return []
    _compute_tree_styles(scanner.root, rules)
    issues = []
    stack = list(scanner.root.children)
    while stack:
        node = stack.pop()
        stack.extend(reversed(node.children))
        if _has_visible_text(node):
            bg_token, _bg = _effective_background(node)
            fg_token = _extract_css_color(node.color_raw, node.variables) if node.color_raw else None
            issue = _issue_for_tokens(_element_source(node.tag, node.attrs), fg_token, bg_token,
                                      threshold, node.variables, kind="text")
            if issue:
                issues.append(issue)
        if _connectorish(node):
            bg_token, _bg = _effective_background(node)
            stroke_token = _extract_css_color(node.stroke_raw, node.variables) if node.stroke_raw else None
            issue = _issue_for_tokens(_element_source(node.tag, node.attrs), stroke_token, bg_token,
                                      stroke_threshold, node.variables, kind="stroke")
            if issue:
                issues.append(issue)
    return issues


def _issue_for_pair(source, fg_value, bg_value, variables, threshold):
    return _issue_for_tokens(
        source,
        _extract_css_color(fg_value, variables),
        _extract_css_color(bg_value, variables),
        threshold,
        variables,
        kind="text",
    )


def find_low_contrast_pairs(html, threshold=DEFAULT_MIN_CONTRAST_RATIO, variable_pairs=(),
                            stroke_threshold=DEFAULT_MIN_STROKE_CONTRAST_RATIO):
    scanner = _DocumentScanner()
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

    issues.extend(_computed_element_issues(scanner, threshold, stroke_threshold))

    seen = set()
    unique = []
    for issue in issues:
        key = (issue.kind, issue.source, issue.foreground, issue.background, round(issue.ratio, 4))
        if key not in seen:
            seen.add(key)
            unique.append(issue)
    return unique


_DARK_SELECTOR_RE = re.compile(r"data-theme\s*[~|^$*]?=\s*['\"]?\s*dark", re.IGNORECASE)
_NOT_GROUP_RE = re.compile(r":not\([^)]*\)", re.IGNORECASE)


def _selector_is_dark(selector):
    # A selector scopes the dark theme when it targets [data-theme="dark"] OUTSIDE a :not(...)
    # (so html:not([data-theme="dark"]) - an explicit light selector - stays in the light env).
    stripped = _NOT_GROUP_RE.sub("", selector or "")
    return bool(_DARK_SELECTOR_RE.search(stripped))


def _media_query_applies_to_screen(query):
    """True when a media query part CAN apply to a screen (so a screen palette resolver includes
    it). 'screen' / 'all' / a bare feature query like '(min-width: 40em)' / 'not print' -> True;
    'print' / 'speech' / 'not screen' / 'not all' -> False. A group that never applies on screen
    (print, speech, or the negation of screen) must be excluded so it cannot masquerade as the
    screen palette."""
    p = (query or "").strip().lower()
    negate = False
    if p.startswith("not "):
        negate = True
        p = p[4:].strip()
    m = re.match(r"(?:only\s+)?([a-z-]+)", p)
    # No leading type token means a bare feature query, which applies to all media (incl. screen).
    applies = True if m is None else m.group(1) in ("screen", "all")
    return (not applies) if negate else applies


_AT_KEYWORD_RE = re.compile(r"^@([a-z-]+)", re.IGNORECASE)


def _at_group_recurses(prelude):
    """Whether a block at-rule GROUPS ordinary style rules a screen palette should see. Conditional
    groups (@media that may apply to screen, @supports, @layer{}, @container, @scope) recurse;
    @keyframes, @font-face, @page, screen-inapplicable @media (print/speech/not screen), and
    unknown at-rules are skipped. The keyword is parsed independently of whitespace so a compact
    `@media(max-width:600px)` / `@supports(display:grid)` is still recognized."""
    m = _AT_KEYWORD_RE.match((prelude or "").strip())
    head = m.group(1).lower() if m else ""
    if head in ("supports", "layer", "container", "scope"):
        return True
    if head == "media":
        query = (prelude or "").strip()[m.end():].strip()
        parts = [p.strip() for p in query.split(",")] or [""]
        return any(_media_query_applies_to_screen(p) for p in parts)
    return False


def _next_top_delim(text, start):
    """Index of the next top-level ';' or '{' from `start`, ignoring quotes and parentheses; None
    if neither remains. Used to separate statement at-rules (@charset/@import/@layer a,b;) from
    block rules without a fragile whole-string search."""
    quote = None
    depth = 0
    for k in range(start, len(text)):
        ch = text[k]
        if quote:
            if ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif depth == 0 and ch in (";", "{"):
            return k
    return None


# Screen conditional groups can nest, but real palette CSS is 0-1 levels deep. Cap the recursion
# so pathological input (thousands of nested at-rules) degrades gracefully instead of raising an
# uncaught RecursionError that would abort the whole validate()/finalize run for every caller.
_MAX_RULE_DEPTH = 40


def _iter_style_rules(text, _depth=0):
    """Yield (selector, declarations_body) for every SCREEN-applicable ordinary style rule in the
    (comment-stripped) CSS `text`, recursing through screen conditional groups and skipping
    screen-inapplicable media, keyframes/font-face, and statement at-rules. Tokenizing top-level by
    both ';' and '{' means a leading `@charset "...";` / `@import ...;` never swallows the rule
    after it, and a declaration value containing a literal '{' (e.g. `content: "{"`) never drops
    its rule."""
    if _depth > _MAX_RULE_DEPTH:
        return
    i, n = 0, len(text)
    while i < n:
        j = _next_top_delim(text, i)
        if j is None:
            return
        if text[j] == ";":
            i = j + 1  # a statement at-rule (@charset/@import/@layer a,b;) - consume and skip
            continue
        prelude = text[i:j].strip()
        close = _matching_brace(text, j)
        if close < 0:
            return
        body = text[j + 1:close]
        if prelude.startswith("@"):
            if _at_group_recurses(prelude):
                yield from _iter_style_rules(body, _depth + 1)
        elif prelude and ":" in body:
            yield prelude, body
        i = close + 1


def theme_environments(html):
    """Resolve the effective custom-property palette for each theme environment separately.

    Returns {"light": {name: value, ...}, "dark": {...}}: the light map is built from the SCREEN
    non-dark selectors (`:root`, `html`, ...) and the dark map is that light map overlaid with the
    declarations from selectors scoped to `[data-theme="dark"]`, matching custom-property cascade,
    so a token overridden only in the dark theme is evaluated against its dark value. Screen
    conditional groups (`@media` that may apply to screen, `@supports`, `@layer`, ...) are traversed
    so an override wherever the author placed it is seen, while screen-inapplicable media (an
    `@media print`/`not screen` block or a `<style media="print">`) is excluded so a non-screen
    palette never masquerades as the screen dark palette. Grouped selectors are split on top-level
    commas and each part classified independently. Only custom properties (names starting with
    `--`) are collected. Returns {} when the document declares no custom properties."""
    scanner = _StyleScanner()
    scanner.feed(html)
    scanner.close()
    base, dark_overlay = {}, {}
    for css, media, is_brand in zip(scanner.style_blocks, scanner.style_media, scanner.style_is_brand):
        if is_brand:
            continue  # a <style data-cmh-brand> palette is validated by the --brand tooling (CMH-TOOL-19)
        media_parts = [p.strip() for p in (media or "").split(",") if p.strip()]
        if media_parts and not any(_media_query_applies_to_screen(p) for p in media_parts):
            continue  # a screen-inapplicable <style media="print"> never defines the screen palette
        for selector, body in _iter_style_rules(_strip_css_comments(css)):
            decls = {k: v for k, v in _parse_declarations(body).items() if k.startswith("--")}
            if not decls:
                continue
            for part in _split_top_level(selector, ","):
                (dark_overlay if _selector_is_dark(part) else base).update(decls)
    if not base and not dark_overlay:
        return {}
    dark = dict(base)
    dark.update(dark_overlay)
    return {"light": base, "dark": dark}


def _to_hex(rgb):
    return "#%02x%02x%02x" % (rgb[0], rgb[1], rgb[2])


def nudge_to_ratio(foreground, background, target, variables=None):
    """Return a hex color near `foreground` that meets `target` contrast against `background`,
    walking the foreground toward black and toward white and preferring the smaller move. Returns
    None when neither extreme reaches the target (a mid-tone background where the target is
    unreachable) or when either color cannot be resolved to a concrete value."""
    fg = parse_css_color(foreground, variables)
    bg = parse_css_color(background, variables)
    if fg is None or bg is None or bg[3] < 1:
        return None
    if fg[3] < 1:
        fg = _composite(fg, bg)
    fg_rgb, bg_hex = fg[:3], _to_hex(bg[:3])
    candidates = []
    for extreme in ((0, 0, 0), (255, 255, 255)):
        for i in range(1, 257):
            t = i / 256
            trial = tuple(round(fg_rgb[k] + (extreme[k] - fg_rgb[k]) * t) for k in range(3))
            if contrast_ratio(_to_hex(trial), bg_hex) >= target:
                candidates.append((t, _to_hex(trial)))
                break
    if not candidates:
        return None
    candidates.sort(key=lambda c: c[0])
    return candidates[0][1]
