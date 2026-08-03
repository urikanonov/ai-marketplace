"""Browser-accurate attribute decoding for the tools OUTSIDE the validator's `checks` package.

`checks/parsing` decodes an attribute value the way a BROWSER decodes it, re-derived from the RAW
start tag so the host `html.parser` is never trusted: a NAMED character reference resolves only on
an exact match not followed by `=` (so `class="a &nbspcm-skip"` keeps the literal token
`&nbspcm-skip`, where Python 3.12 turns it into a `cm-skip` token that was never authored), the
attribute SPLIT uses HTML whitespace and a single `=`, and a duplicated attribute keeps the FIRST
occurrence as HTML5 does.

The deck validator, the contrast scanner and the authoring tools each used to keep their own
host-trusting attribute dict, so the same document was read one way by the validator and another
way by the tool beside it (CMH-VAL-21). They all read the rule from here instead.

A partial install (the `validate` tool missing) falls back to the host's own list rather than
failing: a degraded decode is better than a tool that cannot run, and the fallback is WARNED about
once, the way every other optional-tool import in the skill is.
"""
import os
import sys

_TOOLS_ROOT = os.path.dirname(os.path.abspath(__file__))
_VALIDATE_ROOT = os.path.join(_TOOLS_ROOT, "validate")
for _root in (_TOOLS_ROOT, _VALIDATE_ROOT):
    if _root not in sys.path:
        sys.path.insert(0, _root)

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
