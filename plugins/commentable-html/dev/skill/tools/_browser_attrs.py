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
and ASCII-only tag-name folding stay each consumer's own.

The deck validator, the contrast scanner and the authoring tools each used to keep their own
host-trusting attribute dict, so the same document was read one way by the validator and another
way by the tool beside it (CMH-VAL-21). They all read the rule from here instead.

A partial install (the `validate` tool missing) falls back to the host's own list and the host's own
`HTMLParser` rather than failing: a degraded parse is better than a tool that cannot run, and the
fallback is WARNED about once, the way every other optional-tool import in the skill is.
"""
import html as _html
import os
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


def _start_tag_parser(parsing_module):
    """The shared start-tag parser base, or the host's own `HTMLParser` when it is unavailable.

    Kept a function so the degraded install has a reachable, tested path: the class itself is
    bound once at import, as every consumer subclasses it at import time too."""
    base = getattr(parsing_module, "browser_start_tag_parser", None)
    if isinstance(base, type) and issubclass(base, HTMLParser):
        return base
    return HTMLParser


# The start-tag base for a consumer outside `checks` that needs the tag EXTENT and the bounded
# numeric decode, not only the attribute rule - today the contrast scanner (`cmhval/contrast.py`),
# the one such scanner inside the validator. It shares the START TAG parse only: the wider element
# boundaries (`_BrowserBoundaries`) and ASCII-only tag-name folding are still each consumer's own
# (CMH-VAL-21).
StartTagParser = _start_tag_parser(_parsing)


def attrs(parser, tag, raw_attrs):
    """The start tag's `(name, value)` pairs, browser-decoded. `parser` is the HTMLParser
    currently handling the start tag (its raw start-tag text is what the rule is applied to)."""
    if _shared_attrs is None:
        return [((k or "").lower(), v) for k, v in raw_attrs]
    return _shared_attrs(parser, (tag or "").lower(), raw_attrs)


def attrs_dict(parser, tag, raw_attrs):
    """The start tag's attribute dict, browser-decoded, first occurrence winning."""
    if _shared_attrs_dict is None:
        d = {}
        for k, v in raw_attrs:
            kl = (k or "").lower()
            if kl not in d:
                d[kl] = v if v is not None else ""
        return d
    return _shared_attrs_dict(parser, (tag or "").lower(), raw_attrs)
