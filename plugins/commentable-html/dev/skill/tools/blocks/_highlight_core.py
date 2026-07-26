#!/usr/bin/env python3
"""Shared emission and the lossless inverse for commentable-html token highlighting.

Every highlighted code block in a document - whatever the language, KQL included - is a
flat sequence of escaped text and `<span class="cmh-{code,kql}-KIND">escaped</span>`
tokens. Flat means no span ever contains another span, and escaping means a correctly
generated inner holds no literal `<` or `>`. Those two properties together are what make
`dehighlight` a provable inverse rather than a best-effort unwrap: strip the recognized
spans in ONE pass and anything left over that still contains `<` or `>` was not produced
by these emitters, so it is refused instead of mangled.

Why one pass and not a loop: a loop would peel nested spans from the inside out and hand
back plausible-looking but corrupted source, silently defeating the refusal check. A
single pass leaves the outer tag of a nested structure in place, which trips the check.

The inverse is a LEFT inverse over newline-normalized input: both emitters fold CRLF and
CR to LF, so `dehighlight(highlight(x)) == normalize_newlines(x)`. For content that is
ALREADY stored highlighted - the only thing the review loop ever round-trips - newlines
are already LF, so dehighlight followed by re-highlight is byte-identical.

`dehighlight` must be applied to stored inner HTML exactly ONCE. It ends in an unescape,
so feeding its own output back in would decode source that legitimately contains `&amp;`.
"""
import html as _html
import re

# The token kinds each emitter actually produces. An exact allowlist (rather than a
# loose character class) is what lets `dehighlight` refuse a class it never wrote, and
# `test_highlight_core` asserts these stay in step with the emitters, so adding a kind
# without listing it here fails loudly instead of silently breaking the inverse.
CODE_KINDS = frozenset(("com", "fn", "key", "kw", "num", "op", "str"))
KQL_KINDS = frozenset(("com", "fn", "kw", "num", "op", "str"))

_TOKEN_SPAN_RE = re.compile(
    r'<span class="(?:cmh-code-(?:%s)|cmh-kql-(?:%s))">([^<]*)</span>'
    % ("|".join(sorted(CODE_KINDS)), "|".join(sorted(KQL_KINDS))))
# After stripping, a correctly generated inner is fully escaped, so a surviving angle
# bracket proves the content was hand-written, nested, or malformed.
_ANGLE_RE = re.compile(r"[<>]")


def esc(text):
    """Escape text for a token span body. Quotes stay literal, matching both emitters."""
    return _html.escape(text, quote=False)


def unesc(text):
    """Exact inverse of `esc`. Order matters: `&amp;` LAST, so `&amp;lt;` decodes to
    the literal text `&lt;` rather than being decoded twice into `<`."""
    return text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


def span(cls, text):
    """The single emission point for a token span."""
    return '<span class="%s">%s</span>' % (cls, esc(text))


def normalize_newlines(text):
    """Fold CRLF and lone CR to LF, as both highlighters do before tokenizing."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _strip_tokens(inner):
    return _TOKEN_SPAN_RE.sub(lambda m: m.group(1), inner or "")


def _is_canonically_escaped(text):
    """True when `text` is exactly what `esc` would emit. Deliberately stricter than
    `html.unescape`, which would also decode `&quot;`, `&#x3C;` and `&eacute;` - none of
    which these emitters ever write - and would silently rewrite hand-authored content."""
    return esc(unesc(text)) == text


def dehighlight(inner):
    """Return the original source for a highlighted inner, or None to refuse it.

    None means the content is not something these emitters produced - hand-written
    markup, a nested or malformed span, an unknown token kind, extra attributes, or
    non-canonical escaping - and callers must leave such a block untouched rather than
    rewrite it.
    """
    stripped = _strip_tokens(inner)
    if _ANGLE_RE.search(stripped) or not _is_canonically_escaped(stripped):
        return None
    return unesc(stripped)


def is_flat(inner):
    """True when `inner` is exactly escaped text plus non-nested recognized token spans."""
    return dehighlight(inner) is not None


def classify(inner):
    """Return 'highlighted', 'raw', or 'hand-written' for a code block's inner HTML."""
    stripped = _strip_tokens(inner)
    if _ANGLE_RE.search(stripped) or not _is_canonically_escaped(stripped):
        return "hand-written"
    return "highlighted" if stripped != (inner or "") else "raw"
