"""Shared favicon detection for the authoring tools (retrofit, upgrade).

A favicon is a `<link>` in the head whose `rel` attribute, split on whitespace, contains the
exact token `icon` (so `rel="icon"` and `rel="shortcut icon"` count, but `apple-touch-icon`,
`mask-icon`, and `fluid-icon` do NOT) AND whose `href` is non-empty. This mirrors the validator's
check (checks/kind.py `check_favicon` over the parser's `icon_links`, which uses
`"icon" in rel.split()` plus a non-empty href), so the tools inject a favicon exactly when the
validator would warn. Keeping this in one place stops the tools' detection from drifting away from
the validator's.

Detection uses `html.parser.HTMLParser` (the same tokenizer the validator uses) rather than a raw
regex so that: attributes are parsed exactly (a `data-rel` / `data-href` is never mistaken for
`rel` / `href`); a `<link>` that appears only as text inside a `<script>`, `<style>`, or an HTML
comment does NOT count; and adversarial input (unterminated comments/tags) cannot trigger the
quadratic backtracking a two-stage regex scan is prone to. Detection is head-scoped: only links
before the document's body (the `<body>` tag, a `</head>`, or the first flow-content element that
implicitly ends the head) are considered.
"""
from html.parser import HTMLParser

# Elements allowed in <head>; the first START tag outside this set (and every `<body>` /
# closing `</head>`) ends the head, matching how a browser stops head parsing.
_HEAD_TAGS = frozenset({
    "html", "head", "base", "link", "meta", "title", "noscript", "style", "script", "template",
})


def rel_is_favicon(rel_value):
    """True when the rel attribute's whitespace-separated tokens include the exact token `icon`."""
    return "icon" in (rel_value or "").lower().split()


class _FaviconFinder(HTMLParser):
    """Collect the raw text of each favicon `<link>` start tag found in the head, in order."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags = []
        self._head_ended = False

    def _consider(self, tag, attrs):
        if self._head_ended:
            return
        if tag == "body" or tag not in _HEAD_TAGS:
            self._head_ended = True
            return
        if tag != "link":
            return
        ad = {}
        for k, v in attrs:
            k = (k or "").lower()
            if k not in ad:
                ad[k] = v or ""
        if rel_is_favicon(ad.get("rel")) and (ad.get("href") or "").strip():
            self.tags.append(self.get_starttag_text())

    def handle_starttag(self, tag, attrs):
        self._consider(tag.lower(), attrs)

    def handle_startendtag(self, tag, attrs):
        self._consider(tag.lower(), attrs)

    def handle_endtag(self, tag):
        if tag.lower() == "head":
            self._head_ended = True


def _find(html):
    finder = _FaviconFinder()
    try:
        finder.feed(html or "")
        finder.close()
    except Exception:
        pass
    return finder.tags


def head_has_favicon(html):
    """True when `html`'s head declares at least one usable favicon link."""
    return bool(_find(html))


def template_favicon_tag(template_html):
    """Return the verbatim favicon `<link>` tag from a template's head, or None when it has none."""
    tags = _find(template_html)
    return tags[0] if tags else None
