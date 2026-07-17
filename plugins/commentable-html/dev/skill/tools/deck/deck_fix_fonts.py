#!/usr/bin/env python3
"""Map deck web-font stacks to deterministic system stacks (CMH-DECK-18).

The deck validator rejects remote font egress. This tool removes the common remote font loaders
copied from frontend-slides examples and rewrites CSS font stacks to the deck contract's system
families, so a valid deck with only font-loader defects can pass deck_validate.py afterward.

Usage:
    python tools/deck/deck_fix_fonts.py deck.html            # fix in place
    python tools/deck/deck_fix_fonts.py deck.html --out fixed.html
    python tools/deck/deck_fix_fonts.py deck.html --check    # report only
"""
import argparse
from dataclasses import dataclass
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _toolpath  # noqa: E402
_toolpath.ensure()

SERIF_STACK = '"Iowan Old Style","Palatino Linotype","Georgia",serif'
DISPLAY_STACK = '"Impact","Rockwell","Arial Black",sans-serif'
SANS_STACK = 'system-ui,-apple-system,"Segoe UI",Roboto,sans-serif'
MONO_STACK = '"Cascadia Code","Consolas","Fira Code",ui-monospace,monospace'

REMOTE_FONT_HOST_RE = re.compile(
    r"(?:fonts\.googleapis\.com|fonts\.gstatic\.com|api\.fontshare\.com)", re.I)
LINK_RE = re.compile(r"[ \t]*<link\b[^>]*>\s*(?:\r?\n)?", re.I)
ATTR_RE = re.compile(r"\b([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)")
REMOTE_IMPORT_RE = re.compile(r"@import\s+(?:url\(\s*)?['\"]?\s*(?:https?:)?//[^;]+;\s*", re.I)
FONT_FACE_RE = re.compile(r"@font-face\s*\{[^{}]*\}", re.I | re.S)
REMOTE_URL_RE = re.compile(r"url\(\s*['\"]?\s*(?:https?:)?//", re.I)
DECL_RE = re.compile(
    r"(?P<prefix>(?P<prop>font-family|--[-a-zA-Z0-9_]*font[-a-zA-Z0-9_]*)\s*:\s*)"
    r"(?P<value>[^;{}]+)(?P<semi>;?)",
    re.I,
)
IMPORTANT_RE = re.compile(r"\s*!important\s*$", re.I)
BEGIN_MARK = "<!-- BEGIN: commentable-html - CONTENT"
END_MARK = "<!-- END: commentable-html - CONTENT -->"

CJK_FAMILIES = {
    "long cang", "lxgw wenkai", "lxgw wenkai tc", "noto sans mono cjk sc",
    "noto sans sc", "noto serif sc", "smiley sans oblique", "yozai",
    "zcool kuaile", "zcool xiaowei",
}
MONO_FAMILIES = {
    "cascadia code", "consolas", "courier prime", "dm mono", "fira code",
    "ibm plex mono", "jetbrains mono", "menlo", "sf mono", "ui-monospace",
}
SERIF_FAMILIES = {
    "bodoni moda", "cormorant garamond", "dm serif display", "fraunces",
    "georgia", "instrument serif", "iowan old style", "lora", "newsreader",
    "palatino linotype", "playfair display", "source serif 4", "source serif pro",
}
DISPLAY_FAMILIES = {
    "alfa slab one", "archivo black", "bebas neue", "big shoulders display",
    "bowlby one", "caveat", "caveat brush", "clash display", "fredoka one",
    "impact", "rockwell", "arial black", "shrikhand", "stardos stencil", "zilla slab",
}
SANS_FAMILIES = {
    "albert sans", "archivo narrow", "barlow", "barlow condensed",
    "bricolage grotesque", "dm sans", "hanken grotesk", "helvetica",
    "helvetica neue", "inter", "jost", "manrope", "ms sans serif", "noto sans", "open sans", "quicksand", "roboto",
    "satoshi", "segoe ui", "source sans 3", "space grotesk", "system-ui", "work sans",
}
GENERIC_SERIF = {"serif"}
GENERIC_DISPLAY = {"cursive", "fantasy"}
GENERIC_SANS = {"sans-serif", "system-ui", "-apple-system", "blinkmacsystemfont"}
GENERIC_MONO = {"monospace", "ui-monospace"}


@dataclass(frozen=True)
class FontFixStats:
    remote_loaders_removed: int = 0
    font_stacks_rewritten: int = 0


def _attr_value(tag, name):
    for match in ATTR_RE.finditer(tag):
        if match.group(1).lower() == name:
            value = match.group(2).strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                return value[1:-1]
            return value
    return ""


def _strip_remote_links(html):
    removed = 0

    def repl(match):
        nonlocal removed
        tag = match.group(0)
        href = _attr_value(tag, "href")
        if href and REMOTE_FONT_HOST_RE.search(href):
            removed += 1
            return ""
        return tag

    return LINK_RE.sub(repl, html), removed


def _strip_remote_imports(html):
    return REMOTE_IMPORT_RE.subn("", html)


def _strip_remote_font_faces(html):
    removed = 0

    def repl(match):
        nonlocal removed
        block = match.group(0)
        if REMOTE_URL_RE.search(block):
            removed += 1
            return ""
        return block

    return FONT_FACE_RE.sub(repl, html), removed


def _font_face_families(html):
    families = set()
    for block in FONT_FACE_RE.findall(html):
        for match in DECL_RE.finditer(block):
            if match.group("prop").lower() == "font-family":
                for part in _split_stack(match.group("value")):
                    name = _normalize_family(part)
                    if name:
                        families.add(name)
    return families


def _protect_font_faces(html):
    blocks = []

    def repl(match):
        token = "___CMH_FONT_FACE_%04d___" % len(blocks)
        blocks.append(match.group(0))
        return token

    return FONT_FACE_RE.sub(repl, html), blocks


def _restore_font_faces(html, blocks):
    for i, block in enumerate(blocks):
        html = html.replace("___CMH_FONT_FACE_%04d___" % i, block)
    return html


def _split_stack(value):
    parts = []
    start = 0
    quote = ""
    depth = 0
    for i, ch in enumerate(value):
        if quote:
            if ch == quote:
                quote = ""
            continue
        if ch in "'\"":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")" and depth:
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(value[start:i].strip())
            start = i + 1
    parts.append(value[start:].strip())
    return [p for p in parts if p]


def _normalize_family(part):
    token = part.strip()
    if not token:
        return ""
    if len(token) >= 2 and token[0] == token[-1] and token[0] in "'\"":
        token = token[1:-1]
    return re.sub(r"\s+", " ", token.strip()).lower()


def _category(name, local_faces):
    if not name:
        return None
    if name in local_faces or name.startswith("var("):
        return "local"
    if name in CJK_FAMILIES or " cjk " in (" " + name + " ") or name.startswith("noto sans sc"):
        return "cjk"
    if name in MONO_FAMILIES or " mono" in name or "code" in name:
        return "mono"
    if name in SERIF_FAMILIES or name.endswith(" serif"):
        return "serif"
    if (name in DISPLAY_FAMILIES or "display" in name or "slab" in name or
            "script" in name or "brush" in name or "stencil" in name):
        return "display"
    if name in SANS_FAMILIES or "grotesk" in name or name.endswith(" sans"):
        return "sans"
    if name in GENERIC_MONO:
        return "generic-mono"
    if name in GENERIC_SERIF:
        return "generic-serif"
    if name in GENERIC_DISPLAY:
        return "generic-display"
    if name in GENERIC_SANS:
        return "generic-sans"
    return "unknown"


def _stack_for(category):
    return {
        "mono": MONO_STACK,
        "serif": SERIF_STACK,
        "display": DISPLAY_STACK,
        "sans": SANS_STACK,
        "generic-mono": MONO_STACK,
        "generic-serif": SERIF_STACK,
        "generic-display": DISPLAY_STACK,
        "generic-sans": SANS_STACK,
    }.get(category)


def _cjk_fallback(generic_categories):
    for category in generic_categories:
        if category == "generic-mono":
            return "monospace"
        if category == "generic-serif":
            return "serif"
        if category == "generic-display":
            return "cursive"
        if category == "generic-sans":
            return "sans-serif"
    return "sans-serif"


def _rewrite_stack(value, local_faces):
    important = ""
    match = IMPORTANT_RE.search(value)
    if match:
        important = " !important"
        value = value[:match.start()].rstrip()
    explicit_categories = []
    generic_categories = []
    saw_cjk = False
    saw_local = False
    for part in _split_stack(value):
        category = _category(_normalize_family(part), local_faces)
        if category == "cjk":
            saw_cjk = True
        elif category == "local":
            saw_local = True
        elif category and category.startswith("generic-"):
            generic_categories.append(category)
        elif category and category != "unknown":
            explicit_categories.append(category)
    if saw_local and not explicit_categories:
        return value + important
    if explicit_categories:
        return _stack_for(explicit_categories[0]) + important
    if saw_cjk:
        return _cjk_fallback(generic_categories) + important
    if generic_categories:
        return value + important
    return SANS_STACK + important


def _rewrite_font_declarations(html, local_faces):
    rewritten = 0
    protected, blocks = _protect_font_faces(html)

    def repl(match):
        nonlocal rewritten
        value = match.group("value")
        new_value = _rewrite_stack(value, local_faces)
        if new_value == value.strip():
            return match.group(0)
        rewritten += 1
        return match.group("prefix") + new_value + match.group("semi")

    fixed = DECL_RE.sub(repl, protected)
    return _restore_font_faces(fixed, blocks), rewritten


def _content_span(html):
    begin = html.find(BEGIN_MARK)
    end = html.rfind(END_MARK)
    if begin == -1 or end == -1 or end <= begin:
        return None
    close = html.find("-->", begin)
    if close == -1 or close > end:
        return None
    return close + 3, end


def _fix_segment(segment):
    segment, link_count = _strip_remote_links(segment)
    segment, import_count = _strip_remote_imports(segment)
    segment, font_face_count = _strip_remote_font_faces(segment)
    local_faces = _font_face_families(segment)
    segment, rewritten = _rewrite_font_declarations(segment, local_faces)
    return segment, FontFixStats(
        remote_loaders_removed=link_count + import_count + font_face_count,
        font_stacks_rewritten=rewritten,
    )


def fix_fonts(html):
    """Return (fixed_html, FontFixStats) after deterministic font cleanup."""
    span = _content_span(html)
    if span is None:
        return _fix_segment(html)
    start, end = span
    fixed, stats = _fix_segment(html[start:end])
    return html[:start] + fixed + html[end:], stats


def main(argv=None):
    parser = argparse.ArgumentParser(description="Map deck web fonts to approved system stacks.")
    parser.add_argument("file", help="the .html deck to fix")
    parser.add_argument("--out", metavar="FILE", help="write the fixed deck to FILE instead of in place")
    parser.add_argument("--check", action="store_true", help="report only; exit 1 if a fix would be made")
    args = parser.parse_args(argv)

    try:
        with open(args.file, "r", encoding="utf-8", newline="") as fh:
            html = fh.read()
    except OSError as exc:
        print("deck_fix_fonts: %s" % exc, file=sys.stderr)
        return 1

    fixed, stats = fix_fonts(html)
    changed = fixed != html
    if args.check:
        if changed:
            print("deck_fix_fonts: %d remote loader(s), %d font stack(s) need fixes in %s" % (
                stats.remote_loaders_removed, stats.font_stacks_rewritten, args.file))
            return 1
        print("deck_fix_fonts: no font fixes needed in %s" % args.file)
        return 0

    out_path = args.out or args.file
    if changed or args.out:
        try:
            with open(out_path, "w", encoding="utf-8", newline="") as fh:
                fh.write(fixed)
        except OSError as exc:
            print("deck_fix_fonts: %s" % exc, file=sys.stderr)
            return 1
    print("deck_fix_fonts: removed %d remote loader(s), rewrote %d font stack(s) in %s" % (
        stats.remote_loaders_removed, stats.font_stacks_rewritten, out_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
