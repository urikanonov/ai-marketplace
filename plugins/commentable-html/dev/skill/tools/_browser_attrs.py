"""Browser-accurate HTML parsing for the tools OUTSIDE the validator's `checks` package.

`checks/parsing` decodes an attribute value the way a BROWSER decodes it, re-derived from the RAW
start tag so the host `html.parser` is never trusted: a NAMED character reference resolves only on
an exact match not followed by `=` (so `class="a &nbspcm-skip"` keeps the literal token
`&nbspcm-skip`, where Python 3.12 turns it into a `cm-skip` token that was never authored), the
attribute SPLIT uses HTML whitespace and a single `=`, and a duplicated attribute keeps the FIRST
occurrence as HTML5 does. The same package also owns the start-tag PARSER that rule runs inside,
whose tag extent is scanned by a vendored tokenizer and whose numeric decode is bounded, so an
oversized reference resolves to U+FFFD instead of raising; the contrast scanner reads that parser
from here too (`StartTagParser`), which is the start-tag parse only - the wider element boundaries
stay each consumer's own. It also folds a tag or attribute NAME ASCII-only, as a browser does
(CMH-VAL-21 clause 7): U+212A KELVIN SIGN is the one character outside ASCII whose `str.lower()`
is an ASCII letter ("k"), so the host's Unicode fold reads `<lin\u212a>` as a `<link>`,
`</mar\u212a>` as a `<mark>` closer and `data-cmh-chec\u212alist` as `data-cmh-checklist`.

The deck validator, the contrast scanner and the authoring tools each used to keep their own
host-trusting attribute dict and their own `tag.lower()`, so the same document was read one way by
the validator and another way by the tool beside it (CMH-VAL-21). They all read the rule from here
instead: `attrs()` / `attrs_dict()` for the attribute view, and the `BrowserTagNames` base (whose
`_browser_tag()` names each element) for the tag.

A partial install (the `validate` tool missing) falls back to the host's own list, fold and
`HTMLParser` rather than failing: a degraded read is better than a tool that cannot run, and the
fallback is WARNED about once, the way every other optional-tool import in the skill is.
"""
import html as _html
import os
import re as _re
import sys
from html.parser import HTMLParser

_TOOLS_ROOT = os.path.dirname(os.path.abspath(__file__))
_VALIDATE_ROOT = os.path.join(_TOOLS_ROOT, "validate")
for _root in (_TOOLS_ROOT, _VALIDATE_ROOT):
    if _root not in sys.path:
        sys.path.insert(0, _root)

_parsing = None


def text_goahead(default):
    """`HTMLParser.goahead` bound to the shared BOUNDED text decode (CMH-VAL-21), so a scanner
    outside the `checks` package reads a document's TEXT the way the validator's own parsers do:
    an oversized numeric character reference resolves to U+FFFD instead of raising, and a control
    character or noncharacter a browser keeps is not deleted.

    Returns `default` (the caller's own `goahead`) on a partial install, or on a host whose
    `goahead` cannot be re-bound - a degraded decode beats a tool that cannot run.

    Defined ABOVE the decoder import below, and resolving through `_parsing` lazily, because
    callers use it in a CLASS BODY (at import time), unlike the call-time helpers at the bottom.
    """
    return getattr(_parsing, "text_goahead", None) or default


def unescape_text(text):
    """A text run decoded by the browser rule, for a tool that decodes one ITSELF rather than
    through a parser. Degrades to the host's `html.unescape`."""
    shared = getattr(_parsing, "_unescape_text", None)
    return shared(text or "") if shared else _html.unescape(text or "")


def unescape_attr_value(value):
    """An ATTRIBUTE VALUE decoded by the browser rule (a different rule from text: a named
    reference resolves only on an exact match not followed by `=`). Degrades the same way."""
    shared = getattr(_parsing, "_unescape_attr_value", None)
    return shared(value or "") if shared else _html.unescape(value or "")


def visible_text(text):
    """`text` with the characters a reader cannot SEE removed, by the shared rule every check
    uses. Degrades to `text` unchanged."""
    shared = getattr(_parsing, "visible_text", None)
    return shared(text) if shared else (text or "")

# A HARD import, like every other tool's: `_toolpath` sits beside this file, so it resolves in any
# real install, and the fallback handler below needs it bound to WARN rather than degrade silently.
import _toolpath  # noqa: E402


def _is_shipped(module):
    """Whether `module` really is the decoder that ships beside this file.

    `import checks.parsing` resolves through `sys.modules` FIRST, so a host process that already
    imported some other top-level `checks` package would otherwise hand these tools a foreign
    decoder with no signal. (The validator itself imports the same name the same way, so pinning
    by PATH here - loading a second copy - would give the two different module state; refusing an
    unexpected origin is the safe half.)"""
    origin = os.path.abspath(getattr(module, "__file__", "") or "")
    return bool(origin) and origin.startswith(_VALIDATE_ROOT + os.sep)


try:
    from checks import parsing as _parsing
except ImportError:  # pragma: no cover - only a broken/partial install gets here
    _parsing = None
    _toolpath.warn_missing_tool("validate", "browser-accurate attribute decoding")
else:
    if not _is_shipped(_parsing):  # pragma: no cover - needs a hijacked `checks` in sys.modules
        _parsing = None
        _toolpath.warn_missing_tool("validate", "browser-accurate attribute decoding")

_shared_attrs = getattr(_parsing, "browser_attrs", None)
_shared_attrs_dict = getattr(_parsing, "browser_attrs_dict", None)
_shared_ascii_lower = getattr(_parsing, "ascii_lower", None)
_shared_can_host_shadow_root = getattr(_parsing, "can_host_shadow_root", None)
_shared_link_rel_tokens = getattr(_parsing, "link_rel_tokens", None)
_shared_link_href_is_set = getattr(_parsing, "link_href_is_set", None)


_shared_class_tokens = getattr(_parsing, "class_tokens", None)
_shared_html_ws_tokens = getattr(_parsing, "html_ws_tokens", None)
_shared_raw_attrs_class_tokens = getattr(_parsing, "raw_attrs_class_tokens", None)
_shared_raw_attrs_pairs = getattr(_parsing, "raw_attrs_pairs", None)
_shared_raw_text_spans = getattr(_parsing, "raw_text_spans", None)
_shared_tag_names = getattr(_parsing, "BrowserTagNames", None)

# The fallback's copy of the shared attribute-list split, for a partial install only. HTML tokenizes
# a `rel` or `class` list on ASCII whitespace ONLY: Python's argument-less `str.split()` also splits
# on the vertical tab, NBSP and U+001C-U+001F, so it names relations a browser never matches (#1120)
# and classes a browser never has (#1139). Spelled out as literal escapes, like the shared one it
# degrades from, and pinned to it by a parity test. `_FALLBACK_REL_WS_RE` is the name that pin
# reads.
_FALLBACK_HTML_WS_RE = _re.compile(r"[\t\n\f\r ]+")
_FALLBACK_REL_WS_RE = _FALLBACK_HTML_WS_RE
_FALLBACK_ASCII_UPPER_RE = _re.compile(r"[A-Z]")

# The fallback's copy of the URL parser's end trim, for the href emptiness test. Python's
# argument-less `str.strip()` reaches past ASCII into U+00A0, U+2028, U+3000 and U+0085, which the
# URL parser KEEPS, so it calls an href a browser resolves and fetches EMPTY (#1140). Pinned to the
# shared reading BEHAVIOR-for-behavior by a parity test, like the split above.
_FALLBACK_URL_ENDS_TRIM = "".join(chr(c) for c in range(0x21))


def ascii_lower(name):
    """`name` folded the way a BROWSER folds a tag or attribute name: ASCII-only."""
    if _shared_ascii_lower is None:
        return (name or "").lower()
    return _shared_ascii_lower(name or "")


def link_rel_tokens(value):
    """The relations a `rel` attribute names, read the way HTML tokenizes the list.

    The shared reading (`checks/parsing.link_rel_tokens`), so a tool outside the validator's
    `checks` package - the favicon helper the authoring tools inject from - matches the gate that
    would warn about the same document.

    The partial-install fallback folds ASCII-only ITSELF rather than through `ascii_lower`, whose
    own fallback degrades to Python's UNICODE `.lower()` under exactly this condition: that fold
    maps U+212A onto `k` and U+017F onto `s`, so a look-alike would become a real relation on the
    degraded path alone.
    """
    if _shared_link_rel_tokens is None:
        return set(_FALLBACK_ASCII_UPPER_RE.sub(lambda m: m.group(0).lower(), t)
                   for t in _FALLBACK_HTML_WS_RE.split(value or "") if t)
    return _shared_link_rel_tokens(value)


def link_href_is_set(value):
    """True when an `href` still names something once the URL parser trims its ends.

    The shared reading (`checks/parsing.link_href_is_set`), so the favicon helper the authoring
    tools inject from measures an href's emptiness exactly the way the gate that would warn about
    the same document does. EMPTINESS only - it says nothing about reachability, scheme, or
    inertness.
    """
    if _shared_link_href_is_set is None:
        return bool((value or "").strip(_FALLBACK_URL_ENDS_TRIM))
    return _shared_link_href_is_set(value)


def html_ws_tokens(value):
    """The tokens of a space-separated attribute list, IN ORDER, split HTML's way - the shared
    reading (`checks/parsing.html_ws_tokens`), for a caller that REWRITES the attribute and so
    must put the tokens back in the order the author wrote them."""
    if _shared_html_ws_tokens is None:
        return [t for t in _FALLBACK_HTML_WS_RE.split(value or "") if t]
    return _shared_html_ws_tokens(value)


def class_tokens(value):
    """The classes a `class` attribute names, read the way HTML reads them.

    The shared reading (`checks/parsing.class_tokens`), so a tool outside the validator's `checks`
    package - the deck tools, the authoring tools - reads a `class` exactly as the gate that would
    flag the same document does: split on ASCII whitespace ONLY, and matched by EXACT code points
    (which is how a standards-mode document matches a class selector, and how the runtime's own
    `classList` reads one). There is no fold to degrade, so unlike `link_rel_tokens` the fallback
    needs nothing beyond the split.
    """
    if _shared_class_tokens is None:
        return set(_FALLBACK_HTML_WS_RE.split(value or "")) - {""}
    return _shared_class_tokens(value)


# The fallback's copy of the shared start-tag split, for a partial install only: the same tag-name
# and attribute patterns `checks/parsing._tokenize_raw_tag` walks (pinned to them as TEXT by a
# parity test, like the whitespace splits above), so the degraded reading answers what the shared
# one answers on the shapes that matter. It is a DEGRADED stand-in, not the tokenizer: it decodes a
# value with the host's `html.unescape` rather than the browser's numeric end state, and it does
# not fold a NUL. Both are exactly why it runs only in the shared reading's absence, which the shim
# warns about at import.
_FALLBACK_TAG_NAME_RE = _re.compile(r"([a-zA-Z][^\t\n\r\f />]*)(?:[\t\n\r\f ]|/(?!>))*")
_FALLBACK_ATTR_RE = _re.compile(r"""
  ((?<=['"\t\n\r\f /])[^\t\n\r\f />][^\t\n\r\f /=>]*)   # attribute name
  ([\t\n\r\f ]*=[\t\n\r\f ]*                            # value indicator
    ('[^']*'                                            # single-quoted value
    |"[^"]*"                                            # double-quoted value
    |(?!['"])[^>\t\n\r\f ]*                             # bare value
    )
   )?
  (?:[\t\n\r\f ]|/(?!>))*                               # trailing whitespace
""", _re.VERBOSE)


def _fallback_attr_pairs(attrs):
    """A degraded `(name, value)` split of a RAW start-tag attribute string, in order.

    Walked over the same synthetic `<x ...>` wrapper the shared reader uses (see
    `raw_attrs_class_tokens`), so a caller holding only the attribute text is served. The name is
    folded ASCII-ONLY here rather than through `ascii_lower`, whose own fallback degrades to
    Python's UNICODE `.lower()` under exactly this condition - that fold maps U+212A onto `k` and
    U+017F onto `s`, so `cla\u017f\u017f=` would become a real `class=`.
    """
    raw = "<x " + (attrs or "") + ">"
    m = _FALLBACK_TAG_NAME_RE.match(raw, 1)
    if m is None:  # pragma: no cover - the synthetic wrapper always names a tag
        return []
    out, k, end = [], m.end(), len(raw)
    while k < end:
        m = _FALLBACK_ATTR_RE.match(raw, k)
        if m is None:
            break
        name, has_value, value = m.group(1, 2, 3)
        if not has_value:
            value = None
        else:
            if value[:1] == "'" == value[-1:] or value[:1] == '"' == value[-1:]:
                value = value[1:-1]
            if "&" in value:
                value = unescape_attr_value(value)
        out.append((_FALLBACK_ASCII_UPPER_RE.sub(lambda mm: mm.group(0).lower(), name), value))
        k = m.end()
    return out


def raw_attrs_class_tokens(attrs):
    """The class tokens a RAW start-tag attribute string names, IN ORDER.

    The shared reading (`checks/parsing.raw_attrs_class_tokens`), for a tool that has the start
    tag as TEXT rather than as a parsed attribute dict - the KQL-figure refresh and the two
    `language-XXX` label readers, each of which kept its own `class=` regex before.

    The fallback reads the class off the degraded attribute SPLIT rather than searching for a
    `class=` in the raw text, so - like the shared reading - it cannot be fooled by a `class=`
    spelled inside another attribute's quoted value, and it keeps the FIRST of a duplicated
    attribute as HTML5 does.
    """
    if _shared_raw_attrs_class_tokens is None:
        value = next((v for n, v in _fallback_attr_pairs(attrs) if n == "class"), None)
        return html_ws_tokens(value)
    return _shared_raw_attrs_class_tokens(attrs)


def raw_attrs_pairs(attrs):
    """A RAW start-tag attribute string's `(name, value)` pairs, browser-decoded and in order.

    The shared reading (`checks/parsing.raw_attrs_pairs`), for a tool that REWRITES a start tag
    and so must not locate an attribute by searching the raw text: a `class=` search matches one
    spelled inside ANOTHER attribute's quoted value and then rewrites THAT.
    """
    if _shared_raw_attrs_pairs is None:
        return _fallback_attr_pairs(attrs)
    return _shared_raw_attrs_pairs(attrs)


# One left-to-right scan of the shapes a `<` can OPEN, in the order a tokenizer meets them: a
# COMMENT and a TAG (start or end - an end tag's attributes are ignored by a browser but still
# TOKENIZED as part of the tag, so a `>` or a `<!--` inside one of its quoted values ends nothing).
# The tag names are terminated HTML's way and the attribute region is quote-aware, the same region
# every scan in this repo uses. A comment ends at `-->` or at the legacy `--!>` (the comment-end-bang
# state), `<!-->` and `<!--->` close abruptly, and an UNTERMINATED comment runs to the end of the
# input - the same boundaries the validator's own parser applies
# (`checks/parsing._COMMENT_CLOSE_RE` / `_COMMENT_ABRUPT_CLOSE_RE`), so the two agree on where a
# comment stops. Scanning comments and tags in ONE pass is what makes each shield the other: a
# `<!--` written inside an attribute VALUE is consumed with its own tag and is not a comment opener,
# and a tag-shaped string written inside an attribute value is consumed with that value and is not a
# tag. A comment SEARCH alone (`checks/parsing._HTML_COMMENT_RE`) does neither, which is how an
# attribute-value `<!--` marked a LIVE element inert.
_TAG_OR_COMMENT_RE = _re.compile(
    r"""<!--(?:-?>|.*?(?:--!?>|\Z))"""
    r"""|</?[a-zA-Z][^\t\n\f\r />]*((?:"[^"]*"|'[^']*'|[^>"'])*)>""", _re.DOTALL)


def inert_spans(html):
    """The `(start, end)` regions of `html` where a `<` does NOT open an element: HTML comments,
    raw-text / RCDATA bodies (`<script>`, `<style>`, `<textarea>`, `<title>`, ...), and the
    ATTRIBUTE region of a start tag.

    For a tool that finds an element by SCANNING the source text rather than by parsing it. The
    validator's element views come from a real parse, so a start tag written inside a comment - or
    inside another tag's quoted attribute value - is not an element to it; a raw scanner that
    matched one anyway would act on a decoy: rewriting commented-out markup, or a tag-shaped string
    inside a `title=`, and leaving the LIVE element untouched while reporting success.

    Spans, not a blanked copy, so the caller keeps the authored bytes and can splice the original.

    A raw-text body is inert wholesale, so the scan RESUMES past it rather than reading a `<!--`
    written inside script data as a comment opener. The degraded path (a partial install with no
    `checks/parsing`) has no tokenizer to find those bodies with, so it covers comments and
    attribute regions only.

    Not covered, deliberately: a `</` NOT followed by a tag name opens a BOGUS COMMENT ending at
    the first `>`, and a `<!` + junk does the same. Both are parse-error shapes no authoring tool
    here emits, and reading them as ordinary text can only leave a decoy LIVE, never mark a real
    element inert.
    """
    text = html or ""
    raw = _shared_raw_text_spans(text) if _shared_raw_text_spans is not None else None
    raw_spans = [(start, end) for start, end, _tag, _in_tpl in (raw or ())]
    spans = list(raw_spans)
    pos = 0
    while True:
        m = _TAG_OR_COMMENT_RE.search(text, pos)
        if m is None:
            break
        resume = next((end for start, end in raw_spans if start <= m.start() < end), None)
        if resume is not None:
            pos = resume
            continue
        if m.group(1) is None:
            spans.append(m.span())        # a comment: inert to its closer, or to the end
        elif m.end(1) > m.start(1):
            spans.append(m.span(1))       # a start tag: its attributes are values, not markup
        pos = m.end()
    return tuple(sorted(spans))


def in_inert_span(pos, spans):
    """Whether offset `pos` falls inside one of `inert_spans`'s regions."""
    return any(start <= pos < end for start, end in spans)


def attrs_have_class(raw_attrs, class_name):
    """Whether a RAW start-tag attribute string carries `class_name` as a class token.

    The shared reading, so a tool outside the validator's `checks` package matches the gate that
    would flag the same document. Matching a class by SUBSTRING instead - the
    `class="[^"]*cmh-kql[^"]*"` shape a regex invites - both over-matches (`my-cmh-kql-ish` is not
    `cmh-kql`) and under-matches (it never sees a single-quoted or unquoted class at all).
    """
    return class_name in set(raw_attrs_class_tokens(raw_attrs))


def can_host_shadow_root(tag, namespace="html"):
    if _shared_can_host_shadow_root is not None:
        return _shared_can_host_shadow_root(tag, namespace)
    name = ascii_lower(tag or "")
    return namespace == "html" and (
        name in {
            "article", "aside", "blockquote", "body", "div", "footer", "h1", "h2", "h3",
            "h4", "h5", "h6", "header", "main", "nav", "p", "section", "span",
        }
        or ("-" in name and name[:1].isascii() and name[:1].islower())
    )


class _FallbackTagNames(HTMLParser):
    """The degraded base: only a broken/partial install gets here, and a scanner that names a tag
    with the host's Unicode fold still works - it just carries clause 7's differential."""

    def _browser_tag(self, tag):
        return (tag or "").lower()


# Every scanner outside the `checks` package derives from this, so the tag name it keys on is the
# name a browser gives the element.
BrowserTagNames = _shared_tag_names or _FallbackTagNames


def _start_tag_parser(parsing_module):
    """The shared start-tag parser base, or the degraded tag-name base when it is unavailable.

    Kept a function so the degraded install has a reachable, tested path: the class itself is
    bound once at import, as every consumer subclasses it at import time too. The fallback is
    `_FallbackTagNames`, not a bare `HTMLParser`, so a consumer can still name an element with
    `_browser_tag()` on a broken install rather than raising."""
    base = getattr(parsing_module, "browser_start_tag_parser", None)
    if isinstance(base, type) and issubclass(base, HTMLParser):
        return base
    return _FallbackTagNames


# The start-tag base for a consumer outside `checks` that needs the tag EXTENT and the bounded
# numeric decode, not only the attribute rule - today the contrast scanner (`cmhval/contrast.py`),
# the one such scanner inside the validator. It shares the START TAG parse and the ASCII-only
# tag-name fold (it derives from the same `BrowserTagNames` base); the wider element boundaries
# (`_BrowserBoundaries`) are still each consumer's own (CMH-VAL-21).
StartTagParser = _start_tag_parser(_parsing)


def attrs(parser, tag, raw_attrs):
    """The start tag's `(name, value)` pairs, browser-decoded. `parser` is the HTMLParser
    currently handling the start tag (its raw start-tag text is what the rule is applied to)."""
    if _shared_attrs is None:
        return [(ascii_lower(k), v) for k, v in raw_attrs]
    return _shared_attrs(parser, ascii_lower(tag), raw_attrs)


def attrs_dict(parser, tag, raw_attrs):
    """The start tag's attribute dict, browser-decoded, first occurrence winning."""
    if _shared_attrs_dict is None:
        d = {}
        for k, v in raw_attrs:
            kl = ascii_lower(k)
            if kl not in d:
                d[kl] = v if v is not None else ""
        return d
    return _shared_attrs_dict(parser, ascii_lower(tag), raw_attrs)
