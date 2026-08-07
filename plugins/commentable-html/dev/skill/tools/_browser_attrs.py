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

A partial install (the `validate` tool missing) degrades rather than failing: a degraded read is
better than a tool that cannot run, and the fallback is WARNED about once, the way every other
optional-tool import in the skill is. What degrades is narrower than it once was, but only on ONE
path: in the RAW start-tag attribute reading (`raw_attrs_pairs` / `raw_attrs_class_tokens`) the
value DECODE, the NUL fold and the attribute-name ASCII fold are the shared rules, applied from
pinned local copies, because two callers (`deck/deck_scaffold.py`, `kusto/kql_highlight.py`)
RE-SERIALIZE a start tag from what they read and so write any difference into the document. The
three boundary readings a source-text WALK needs are pinned copies for the same reason - the
start-tag extent (`scan_start_tag`), the end-tag close (`end_tag_close`) and the comment close
(`comment_close`) - since the deck scaffold LOCATES the slide it rewrites with them and SPLICES
the document at what they return, so a boundary drawn any other way is written back rather than
merely read; `raw_text_elements()` likewise hands back the shared set itself. Everything else
still degrades to the host: the PARSED views (`attrs()` / `attrs_dict()` / `StartTagParser`) fall
back to the host's own `HTMLParser` and its attribute list, `ascii_lower()` and
`_FallbackTagNames._browser_tag()` fall back to Python's UNICODE `.lower()` (so the clause-7 tag
name differential above is back on that path), and a start tag's extent WITHIN those parsed views
is decided by whichever regex the host ships rather than by the vendored character-by-character
scan, so the eof-in-tag error an unterminated quoted value earns is not applied there.
"""
import html as _html
import os
import re as _re
import sys
from html.entities import html5 as _HTML5_ENTITIES
from html.parser import HTMLParser

_TOOLS_ROOT = os.path.dirname(os.path.abspath(__file__))
_VALIDATE_ROOT = os.path.join(_TOOLS_ROOT, "validate")
for _root in (_TOOLS_ROOT, _VALIDATE_ROOT):
    if _root not in sys.path:
        sys.path.insert(0, _root)

_parsing = None

# The fallback's copy of the shared ATTRIBUTE-VALUE decode, for a partial install only, pinned to
# `checks/parsing`'s (patterns and table as TEXT, behavior answer-for-answer) by parity tests. The
# host's own `html.unescape` is NOT that rule and disagrees on both halves: it resolves a NAMED
# reference that is only a PREFIX of the value or is followed by `=` (`x&ampy` becomes `x&y`,
# `&notit;` becomes `\u00acit;`), and its NUMERIC branch DELETES the code points it considers
# invalid (`&#1;`, `&#x7f;`, `&#xfffe;` all vanish) where a browser keeps them. A caller that
# RE-SERIALIZES a start tag from the decoded value - the deck scaffold, the KQL run-link refresh -
# writes that difference into the document, so a degraded install would silently rewrite an
# authored `id`, `title` or `aria-label` into something the rendered DOM never carries.
_FALLBACK_ATTR_CHARREF_RE = _re.compile(r"&(#[0-9]+|#[xX][0-9a-fA-F]+|[a-zA-Z][a-zA-Z0-9]*)[;=]?")

_FALLBACK_C1_CHARREF_REPLACEMENTS = {
    0x80: "\u20ac", 0x82: "\u201a", 0x83: "\u0192", 0x84: "\u201e", 0x85: "\u2026",
    0x86: "\u2020", 0x87: "\u2021", 0x88: "\u02c6", 0x89: "\u2030", 0x8a: "\u0160",
    0x8b: "\u2039", 0x8c: "\u0152", 0x8e: "\u017d", 0x91: "\u2018", 0x92: "\u2019",
    0x93: "\u201c", 0x94: "\u201d", 0x95: "\u2022", 0x96: "\u2013", 0x97: "\u2014",
    0x98: "\u02dc", 0x99: "\u2122", 0x9a: "\u0161", 0x9b: "\u203a", 0x9c: "\u0153",
    0x9e: "\u017e", 0x9f: "\u0178",
}

_FALLBACK_MAX_CHARREF_DIGITS = {10: len("1114111"), 16: len("10FFFF")}

_FALLBACK_HTML5_ENTITY_NAMES = frozenset(_HTML5_ENTITIES)


def _fallback_numeric_charref(body):
    """The code point a NUMERIC reference names, by the HTML numeric-character-reference end
    state - the shared `checks/parsing._numeric_charref`. The digit run is BOUNDED before any
    integer conversion, so an arbitrarily long reference resolves cheaply rather than raising."""
    if body[1] in "xX":
        digits, base = body[2:], 16
    else:
        digits, base = body[1:], 10
    digits = digits.lstrip("0")
    if not digits:
        return "\ufffd"
    if len(digits) > _FALLBACK_MAX_CHARREF_DIGITS[base]:
        return "\ufffd"
    num = int(digits, base)
    if num in _FALLBACK_C1_CHARREF_REPLACEMENTS:
        return _FALLBACK_C1_CHARREF_REPLACEMENTS[num]
    if num > 0x10FFFF or 0xD800 <= num <= 0xDFFF:
        return "\ufffd"
    return chr(num)


def _fallback_replace_attr_charref(m):
    ref = m.group(0)
    body = m.group(1)
    if body[0] == "#":
        trailing = ref[len(body) + 1:]
        return _fallback_numeric_charref(body) + ("" if trailing == ";" else trailing)
    if not ref.endswith("=") and ref[1:] in _FALLBACK_HTML5_ENTITY_NAMES:
        return _html.unescape(ref)
    return ref


def _fallback_unescape_attr_value(value):
    return _FALLBACK_ATTR_CHARREF_RE.sub(_fallback_replace_attr_charref, value)


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
    reference resolves only on an exact match not followed by `=`, and a numeric one resolves
    through the tokenizer's end state rather than through `html.unescape`).

    The partial-install fallback applies that SAME rule from its own copy above rather than
    degrading to `html.unescape`, because a caller that RE-SERIALIZES a start tag writes the
    decoded value back into the document: the host's decode would silently rewrite an authored
    `x&ampy` as `x&y` and delete the character `&#1;` names.
    """
    shared = getattr(_parsing, "_unescape_attr_value", None)
    return shared(value or "") if shared else _fallback_unescape_attr_value(value or "")


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
_shared_comment_close = getattr(_parsing, "comment_close", None)
_shared_end_tag_close = getattr(_parsing, "end_tag_close", None)
_shared_html_ws_tokens = getattr(_parsing, "html_ws_tokens", None)
_shared_raw_attrs_class_tokens = getattr(_parsing, "raw_attrs_class_tokens", None)
_shared_raw_attrs_pairs = getattr(_parsing, "raw_attrs_pairs", None)
_shared_raw_attrs_pairs_consumed = getattr(_parsing, "raw_attrs_pairs_consumed", None)
_shared_raw_text_elements = getattr(_parsing, "raw_text_elements", None)
_shared_raw_text_spans = getattr(_parsing, "raw_text_spans", None)
_shared_scan_start_tag = getattr(_parsing, "scan_start_tag", None)
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
# one answers. It is a stand-in for the SPLIT only, not for the tokenizer: it decides a tag's
# EXTENT by these patterns rather than by the vendored character-by-character scan, so it does not
# apply the eof-in-tag error an unterminated quoted value earns. Its NAME fold and its value DECODE
# are the shared rules, from the copies above.
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


def _fallback_fold_nul(text):
    """A NUL, replaced with U+FFFD the way a browser replaces it - the shared reading's
    `checks/parsing._fold_nul`, for a partial install (pinned to it by a parity test).

    HTML5's tag-name, attribute-name and attribute-value states all append U+FFFD for a NUL, so a
    caller that RE-SERIALIZES a start tag from these pairs - the deck scaffold - would otherwise
    write back a literal NUL and give the document a value its own DOM never carries.
    """
    return text.replace("\x00", "\ufffd") if "\x00" in text else text


# The fallback's copy of the shared START-TAG SCAN's character classes and of the scan itself, for
# a partial install only, pinned to `checks/parsing`'s (the classes as TEXT, the scan
# answer-for-answer) by parity tests. This one is a copy rather than a degradation because the
# caller that needs it - the deck scaffold's slide locator - RE-SERIALIZES the start tag it finds:
# a boundary drawn any other way does not merely read the document differently, it writes that
# difference back, either skipping a slide a browser builds or promoting markup a browser discards
# (#1197).
_FALLBACK_TAG_WS = "\t\n\r\f "
_FALLBACK_TAG_WS_SLASH = "\t\n\r\f /"
_FALLBACK_TAG_NAME_STOP = "\t\n\r\f />"
_FALLBACK_ATTR_NAME_STOP = "\t\n\r\f /=>"
_FALLBACK_UNQUOTED_VALUE_STOP = "\t\n\r\f >"


def _fallback_scan_start_tag(rawdata, i):
    """The extent of the start tag opening at `i`, scanned HTML5's way - the shared reading's
    `checks/parsing._scan_start_tag`, for a partial install.

    Character by character rather than by one regex for the reason the shared scan gives: the "a
    quote only opens a value AFTER `=`" rule needs nested alternation to express, which backtracks
    exponentially on a hostile document. The tag name is folded ASCII-ONLY here rather than through
    `ascii_lower`, whose own fallback degrades to Python's UNICODE `.lower()` under exactly this
    condition (U+212A would become a `k`).
    """
    n = len(rawdata)
    j = i + 1
    name_start = j
    while j < n and rawdata[j] not in _FALLBACK_TAG_NAME_STOP:
        j += 1
    tag = _fallback_fold_nul(_FALLBACK_ASCII_UPPER_RE.sub(
        lambda m: m.group(0).lower(), rawdata[name_start:j]))
    while True:
        slash = False
        while j < n and rawdata[j] in _FALLBACK_TAG_WS_SLASH:
            slash = rawdata[j] == "/"
            j += 1
        if j >= n:
            return None
        if rawdata[j] == ">":
            return j + 1, tag, slash
        j += 1
        while j < n and rawdata[j] not in _FALLBACK_ATTR_NAME_STOP:
            j += 1
        k = j
        while k < n and rawdata[k] in _FALLBACK_TAG_WS:
            k += 1
        if k >= n:
            return None
        if rawdata[k] != "=":
            continue
        k += 1
        while k < n and rawdata[k] in _FALLBACK_TAG_WS:
            k += 1
        if k >= n:
            return None
        quote = rawdata[k]
        if quote in "\"'":
            close = rawdata.find(quote, k + 1)
            if close < 0:
                return None
            j = close + 1
            continue
        if quote == ">":
            return k + 1, tag, False
        while k < n and rawdata[k] not in _FALLBACK_UNQUOTED_VALUE_STOP:
            k += 1
        if k >= n:
            return None
        j = k


def _fallback_end_tag_close(rawdata, i):
    """Index just past the `>` that ends the tag starting at `i`, or -1 if it never closes - the
    shared reading's `checks/parsing._end_tag_close`, for a partial install.

    A browser ends a tag at the first `>` that is not inside a QUOTED ATTRIBUTE VALUE, and a
    quoted value only begins AFTER `=`, so a bare quote where an attribute NAME belongs does not
    swallow the `>`. Copied rather than degraded for the reason the start-tag scan above is: the
    caller SPLICES the document at the boundary this returns.
    """
    n = len(rawdata)
    j = i
    while j < n:
        c = rawdata[j]
        if c == ">":
            return j + 1
        if c == "=":
            j += 1
            while j < n and rawdata[j] in " \t\n\r\f":
                j += 1
            if j < n and rawdata[j] in "\"'":
                k = rawdata.find(rawdata[j], j + 1)
                if k < 0:
                    return -1
                j = k + 1
            continue
        j += 1
    return -1


# The fallback's copy of the shared COMMENT boundary and RAW-TEXT element set, pinned to
# `checks/parsing`'s (the patterns and the set as TEXT, the close answer-for-answer) by parity
# tests. A walk that consumes every tag must skip both wholesale or it tokenizes inside prose: a
# tag-shaped string in a comment or a `<script>` body is text a reader SEES, and one carrying an
# unterminated quoted value would run a start-tag scan straight through the live markup after it.
_FALLBACK_COMMENT_CLOSE_RE = _re.compile(r"--!?>")
_FALLBACK_COMMENT_ABRUPT_CLOSE_RE = _re.compile(r"-?>")
_FALLBACK_RAW_TEXT_ELEMENTS = frozenset((
    "script", "style", "textarea", "title", "xmp", "iframe", "noembed", "noframes", "noscript",
    "plaintext",
))


def _fallback_comment_close(rawdata, i):
    """Index just past the comment opening at `i`, or the END of the input when it never closes -
    the shared reading's `checks/parsing._comment_close`, for a partial install."""
    m = (_FALLBACK_COMMENT_ABRUPT_CLOSE_RE.match(rawdata, i + 4)
         or _FALLBACK_COMMENT_CLOSE_RE.search(rawdata, i + 4))
    return m.end() if m else len(rawdata)


def _fallback_attr_pairs(attrs):
    """A degraded `(name, value)` split of a RAW start-tag attribute string, in order.
    Walked over the same synthetic `<x ...>` wrapper the shared reader uses (see
    `raw_attrs_class_tokens`), so a caller holding only the attribute text is served. The name is
    folded ASCII-ONLY here rather than through `ascii_lower`, whose own fallback degrades to
    Python's UNICODE `.lower()` under exactly this condition - that fold maps U+212A onto `k` and
    U+017F onto `s`, so `cla\u017f\u017f=` would become a real `class=`.
    """
    return _fallback_attr_pairs_consumed(attrs)[0]


def _fallback_attr_pairs_consumed(attrs):
    """`_fallback_attr_pairs(attrs)` paired with whether the split CONSUMED the whole region -
    the degraded copy of the shared `raw_attrs_pairs_consumed`."""
    raw = "<x " + (attrs or "") + ">"
    m = _FALLBACK_TAG_NAME_RE.match(raw, 1)
    if m is None:  # pragma: no cover - the synthetic wrapper always names a tag
        return [], False
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
            if value:
                value = _fallback_fold_nul(value)
                if "&" in value:
                    value = unescape_attr_value(value)
        out.append((_fallback_fold_nul(
            _FALLBACK_ASCII_UPPER_RE.sub(lambda mm: mm.group(0).lower(), name)), value))
        k = m.end()
    return out, all(c in _FALLBACK_TAG_WS_SLASH for c in raw[k:end - 1])


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
    spelled inside ANOTHER attribute's quoted value and then rewrites THAT. Two callers rewrite
    from it - the KQL run-link refresh and the deck scaffold's slide rewrite - and both
    RE-SERIALIZE the whole start tag from what comes back, so a reading that answers less than
    the shared one does not merely mis-detect: it writes its OWN answer into the document - both
    the attributes it could not see and the values it decoded differently. That is why the
    partial-install fallback is a full split with the shared NUL fold and the shared value decode,
    and not a stand-in for the one attribute a caller happens to want. (`authoring/upgrade.py`
    reads the same value decode through `unescape_attr_value` without rewriting a tag, and gains
    the same fidelity.)
    """
    if _shared_raw_attrs_pairs is None:
        return _fallback_attr_pairs(attrs)
    return _shared_raw_attrs_pairs(attrs)


def serialize_start_tag(tag, pairs, self_closing=False):
    """`tag`'s start tag RE-SERIALIZED from browser-read `(name, value)` `pairs`.

    The one writer for the four tools that rebuild a start tag from what they parsed - the deck
    scaffold's slide rewrite, the KQL run-link refresh, and the two authoring tools' content-root
    stamps. They each kept their own copy of this rule and drifted apart: #1191 fixed ONE of them
    and left three carrying the identical fusion bug, which is why it lives here beside the
    READING it is the inverse of.

    Every attribute is written in the one canonical ` name="value"` shape, and a VALUELESS one is
    written as `name=""` rather than as a bare name. The bare name drops the `/` HTML uses to
    terminate an attribute name, so the NEXT attribute - whose name legally begins with `=` (the
    unexpected-equals-sign-before-attribute-name state) - fused into it and gave it a VALUE the
    input never had (`data-a/=onload` came back as `data-a =onload`, which re-parses as
    `data-a="onload"`). An absent value IS the empty string to a browser, so the quoted empty
    value is the same attribute and cannot be terminated that way. Re-emitting the `/` terminator
    instead would be faithful only until the valueless attribute is written LAST, where it lands
    as the self-closing `/>` solidus.

    Each value is escaped exactly ONCE, from its DECODED form, so a caller that reads through
    `raw_attrs_pairs` round-trips rather than double-escaping an authored `&amp;`.

    `self_closing` re-emits the source tag's own ` /` terminator. Dropping it un-closed a FOREIGN
    self-closing element (`<rect .../>` inside an inline `<svg>`), which turns the next sibling
    into its child and stops it rendering. It is safe here precisely because every attribute now
    ends in `"`: a trailing ` /` can no longer terminate an attribute NAME.

    Keeping only the FIRST of a duplicated attribute, as HTML5 does, is deliberately the CALLER's
    job - each of them already has to decide which occurrence its own rewrite owns (the run link
    keeps the first `href`, the deck scaffold writes one `data-slide-id`, the authoring tools go
    through `_set_attr`). Writing every pair back is faithful either way, since a browser reads
    the first.
    """
    out = []
    for name, value in pairs:
        out.append(' %s="%s"' % (name, _html.escape("" if value is None else value, quote=True)))
    return "<%s%s%s>" % (tag, "".join(out), " /" if self_closing else "")
def raw_attrs_pairs_consumed(attrs):
    """`raw_attrs_pairs(attrs)` paired with whether the tokenizer CONSUMED the whole region.

    The shared reading (`checks/parsing.raw_attrs_pairs_consumed`), for a caller that REWRITES
    the start tag: attribute tokenization stops at the first shape it cannot match, and a caller
    that re-serialized the pairs anyway would silently DROP everything after that point. False
    means the tokenizer and `scan_start_tag` below did not read the same start tag, and the
    caller fails closed instead of writing one back.
    """
    if _shared_raw_attrs_pairs_consumed is None:
        return _fallback_attr_pairs_consumed(attrs)
    return _shared_raw_attrs_pairs_consumed(attrs)


def scan_start_tag(html, i):
    """The extent of the start tag opening at `i`: `(end, tag, self_closing)`, where `end` is the
    index just past its `>`, or None when the tag never finishes.

    The shared reading (`checks/parsing.scan_start_tag`), for a tool that LOCATES an element by
    scanning the source text rather than by parsing it. HTML opens a quoted attribute value only
    AFTER an `=` and takes a stray `"` or `'` INTO the attribute NAME, and a value that reaches
    the end of the input earns the eof-in-tag error - the whole tag is DISCARDED. A quote-aware
    `<tag ...>` regex (which opens a quoted run at any quote, anywhere in the tag) disagrees with
    that in BOTH directions, so a scanner built on one both misses tags a browser builds and
    rewrites markup a browser discards into live markup (#1197).

    The partial-install fallback is a pinned copy of the shared scan rather than a pattern, for
    the same reason the value decode and the NUL fold are: the caller RE-SERIALIZES the start tag
    it locates, so a degraded boundary is not a degraded READING - it is written into the
    document.
    """
    if _shared_scan_start_tag is None:
        return _fallback_scan_start_tag(html, i)
    return _shared_scan_start_tag(html, i)


def end_tag_close(html, i):
    """The index just past the `>` that ends the tag starting at `i`, or -1 when it never closes.

    The shared reading (`checks/parsing.end_tag_close`), the END-tag half of the walk
    `scan_start_tag` serves: a browser ends a tag at the first `>` OUTSIDE a quoted value, so a
    literal `</name>` search is not the rule - it refuses the ordinary `</section >` and
    `</section foo="x">` (attributes on an end tag are ignored, but they are still tokenized).
    """
    if _shared_end_tag_close is None:
        return _fallback_end_tag_close(html, i)
    return _shared_end_tag_close(html, i)


def comment_close(html, i):
    """The index just past the comment opening at `i` (a `<!--`), or the end of `html` when it
    never closes - a browser then reads the rest of the input as comment data.

    The shared reading (`checks/parsing.comment_close`), the third leg of the same walk: a comment
    is PROSE, so a tag-shaped string inside one is not a tag. A walk that tokenized there would not
    merely find a decoy - a commented-out tag with an unterminated quoted value (`<!-- <a href="x
    -->`) runs a start-tag scan through the LIVE markup that follows and swallows the real slide
    after it.
    """
    if _shared_comment_close is None:
        return _fallback_comment_close(html, i)
    return _shared_comment_close(html, i)


def raw_text_elements():
    """The elements whose CONTENT is text rather than markup, the way a browser reads them.

    The shared set (`checks/parsing.raw_text_elements`), for the same walk `comment_close` serves:
    markup written inside a `<script>`, `<style>` or `<textarea>` body is prose a reader SEES, so
    a scan must skip the body whole rather than tokenize in it.
    """
    if _shared_raw_text_elements is None:
        return _FALLBACK_RAW_TEXT_ELEMENTS
    return _shared_raw_text_elements


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
