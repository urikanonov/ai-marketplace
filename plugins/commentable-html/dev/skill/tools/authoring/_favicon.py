"""Shared favicon detection for the authoring tools (retrofit, upgrade).

A favicon is a `<link>` in the head whose `rel` attribute, split on whitespace, contains the
exact token `icon` (so `rel="icon"` and `rel="shortcut icon"` count, but `apple-touch-icon`,
`mask-icon`, and `fluid-icon` do NOT) AND whose `href` is non-empty. This mirrors the validator's
check (checks/kind.py `check_favicon` over the parser's `icon_links`, which uses
`"icon" in rel.split()` plus a non-empty href), so the tools inject a favicon exactly when the
validator would warn. Keeping this in one place stops the tools' detection from drifting away from
the validator's. Detection is quote-style and attribute-order agnostic and ignores links inside
HTML comments (a commented-out `<link>` does not count).
"""
import re

_LINK_TAG_RE = re.compile(r"<link\b[^>]*>", re.IGNORECASE)
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def rel_is_favicon(rel_value):
    """True when the rel attribute's whitespace-separated tokens include the exact token `icon`."""
    return "icon" in (rel_value or "").lower().split()


def _attr(tag, name):
    """Return the value of attribute `name` in a single start tag (double/single/unquoted), or None."""
    m = re.search(r'\b%s\s*=\s*("([^"]*)"|\'([^\']*)\'|([^\s"\'>]+))' % name, tag, re.IGNORECASE)
    if not m:
        return None
    return m.group(2) if m.group(2) is not None else (
        m.group(3) if m.group(3) is not None else m.group(4))


def _favicon_link_tags(head_html):
    """Yield each favicon `<link>` start tag in `head_html` (comments stripped)."""
    scope = _HTML_COMMENT_RE.sub("", head_html or "")
    for m in _LINK_TAG_RE.finditer(scope):
        tag = m.group(0)
        if rel_is_favicon(_attr(tag, "rel")) and (_attr(tag, "href") or "").strip():
            yield tag


def head_has_favicon(head_html):
    """True when `head_html` declares at least one usable favicon link."""
    for _tag in _favicon_link_tags(head_html):
        return True
    return False


def template_favicon_tag(template_html):
    """Return the favicon `<link>` tag from a template's head, or None when it has none."""
    for tag in _favicon_link_tags(template_html):
        return tag
    return None
