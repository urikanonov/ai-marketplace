#!/usr/bin/env python3
"""The vendored rich-libraries payload: its canonical shape, and the only safe way to emit it.

This module is deliberately DEPENDENCY-FREE (standard library only, no sibling tool imports) for
one reason: both the BUILD (`dev/tools/build_parts/10-sources.py`, which stamps the payload into
the shipped templates) and the SHIPPED authoring tool (`vendored_libs.py`, which right-sizes it per
document) have to produce byte-identical output for identical input. Two copies of the
serialize-and-escape rule would drift, and the drift would be invisible: the payload is a megabyte
of base64 that no reviewer reads.

Two invariants live here.

1. THE ESCAPE IS NOT OPTIONAL. The payload is inert JSON inside a `<script>` element, so a raw
   `</script>` in any value would close the element early and spill the remainder into the document
   as markup. `<`, `>` and `&` are therefore emitted as `\\u003C`, `\\u003E` and `\\u0026`. Today the
   real payload is pure base64 and licence prose, so the escape is a no-op on production data -
   which is exactly why it needs a guard and a test rather than trust.
2. A LIBRARY IS ITS BYTES AND ITS NOTICE, TOGETHER. MIT requires the notice to accompany the copy,
   and the offline exporter refuses to inline a library whose notice is missing. So `carried_libs`
   counts a library only when BOTH fields are present, are strings, and are non-blank. Key presence
   alone is not enough: a payload holding orphan bytes reads as NOT carrying that library, which is
   what makes the reconciler drop them rather than silently ship unlicensed bytes. Note the LIMIT of
   that guarantee: reconciliation drops orphans whenever it can rebuild the payload at all, but a
   needed pair that neither the document nor a reachable template can supply makes `reconcile`
   return None, and the document is then left byte-identical - orphans included. That is the
   deliberate fail-safe: leaving the file alone lets the export fail loudly, where half-writing a
   payload would hand back a document that looks healthy and is not.
"""

import json

# The exact order `build_vendored_rich_libs_json` emits. Reconciliation rebuilds in this order so a
# payload is a pure function of (content, template bytes) rather than of the document's finalize
# history - otherwise two identical documents could differ byte for byte.
CANONICAL_KEYS = ("encoding", "mermaidGzipBase64", "chartjsGzipBase64",
                  "mermaidLicense", "chartjsLicense")

LIB_FIELDS = {
    "mermaid": ("mermaidGzipBase64", "mermaidLicense"),
    "chartjs": ("chartjsGzipBase64", "chartjsLicense"),
}

LIBRARIES = ("mermaid", "chartjs")

DEFAULT_ENCODING = "gzip+base64"


def serialize_payload(obj):
    """Serialize a payload object exactly the way the build does. Raises ValueError if unsafe.

    ValueError, never SystemExit: `apply()` runs from `finalize` before validation, and a
    BaseException would escape every caller's guard and abort an agent's write-back. The build
    translates this to SystemExit at its own level, where aborting is the right answer.

    `allow_nan=False` because Python's default emits bare `NaN` / `Infinity`, which are not JSON and
    which a browser's `JSON.parse` REFUSES - the payload's only consumer parses it in a browser. A
    value we cannot represent portably therefore raises, the caller leaves the document alone, and
    we never write a payload the runtime cannot read.
    """
    text = (json.dumps(obj, separators=(",", ":"), allow_nan=False)
            .replace("<", "\\u003C").replace(">", "\\u003E").replace("&", "\\u0026"))
    if "</script" in text.lower():
        # Belt and braces, and deliberately unreachable today: the replace above removes every `<`,
        # so nothing can spell a closing tag. It is kept because it guards the PROPERTY that
        # matters (the payload can never close its own element) rather than the mechanism that
        # currently provides it - a future change to the escape set would be caught here instead of
        # in a reader's browser.
        raise ValueError("vendored payload still contains a raw </script after escaping")
    return text


def parse_payload(text):
    """The payload object, or None when the text is anything we cannot safely reason about.

    None covers invalid syntax AND every valid-but-wrong JSON shape (`null`, `[]`, `"x"`, `17`),
    because the callers all do mapping lookups. RecursionError is caught too: it is raised by
    json for a deeply nested document and is neither a ValueError nor a TypeError.
    """
    try:
        obj = json.loads(text)
    except (ValueError, TypeError, RecursionError):
        return None
    return obj if isinstance(obj, dict) else None


def _field(obj, key):
    value = obj.get(key)
    return value if isinstance(value, str) and value.strip() else None


def carried_libs(obj):
    """The libraries this payload actually carries - both fields present, string, and non-blank."""
    if not isinstance(obj, dict):
        return set()
    return {lib for lib in LIBRARIES
            if all(_field(obj, key) is not None for key in LIB_FIELDS[lib])}


def payload_matches(obj, needed):
    """True when the payload carries EXACTLY `needed` and nothing belonging to any other library.

    Deliberately stricter than `carried_libs(obj) == needed`. A payload holding mermaid BYTES whose
    licence went missing carries no mermaid by the `carried_libs` rule, so on a chart-only document
    the two sets would agree and the reconciler would leave ~1,265 KB of unlicensed bytes sitting in
    the file forever. An orphan field is therefore a mismatch, which sends the payload through
    `reconcile` and drops it.
    """
    if carried_libs(obj) != needed:
        return False
    obj = obj if isinstance(obj, dict) else {}
    return not any(key in obj
                   for lib in LIBRARIES if lib not in needed
                   for key in LIB_FIELDS[lib])


def reconcile(obj, needed, source_obj=None):
    """Rebuild the payload so it carries exactly `needed`, or None when that is impossible.

    A library's pair is taken from the document when the document already carries it, otherwise
    from `source_obj` (the full built template). Returning None means "leave the document alone":
    fail-safe here is never to invent bytes, and never to write a payload that is missing a pair the
    content needs.

    Any key that is not part of the library schema is PRESERVED, in its original order, after the
    canonical ones. Rebuilding from a fixed key list alone would silently discard whatever a future
    (or older) producer had put there, and quietly dropping data we merely do not recognise is the
    kind of loss this module exists to prevent.

    THE POLICY WHEN THOSE TWO GOALS COLLIDE, stated explicitly because it is a real trade: an
    unknown value that cannot be serialized portably (`NaN`, `Infinity`, or an overflowing literal
    such as `1e400`, none of which are JSON and all of which a browser's `JSON.parse` refuses) makes
    `serialize_payload` raise, the caller decline, and the document stay byte-identical - so such a
    document is never right-sized. That is deliberate. The alternative is to drop the offending key,
    which is the data loss this preservation exists to prevent, and the affected document is one a
    hand edit already made unreadable to the payload's only consumer, so its export is broken either
    way. Declining changes nothing and reports honestly; dropping would destroy evidence.
    """
    obj = obj if isinstance(obj, dict) else {}
    source_obj = source_obj if isinstance(source_obj, dict) else {}
    have = carried_libs(obj)
    source_has = carried_libs(source_obj)
    out = {}
    encoding = _field(obj, "encoding") or _field(source_obj, "encoding") or DEFAULT_ENCODING
    out["encoding"] = encoding
    for lib in LIBRARIES:
        if lib not in needed:
            continue
        if lib in have:
            source = obj
        elif lib in source_has:
            source = source_obj
        else:
            return None
        for key in LIB_FIELDS[lib]:
            out[key] = source[key]
    rebuilt = {key: out[key] for key in CANONICAL_KEYS if key in out}
    schema = set(CANONICAL_KEYS)
    for key, value in obj.items():
        if key not in schema:
            rebuilt[key] = value
    return rebuilt
