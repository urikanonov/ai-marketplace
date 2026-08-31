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
                  "mermaidUrl", "mermaidIntegrity", "chartjsUrl", "chartjsIntegrity",
                  "mermaidLicense", "chartjsLicense")

# A library can be carried two ways. BYTES are the legacy form, still honoured so documents already
# in the wild keep exporting with no network at all. A SOURCE descriptor - a pinned URL plus the
# SRI hash to verify what comes back - is what new documents carry, because the viewer never reads
# the payload (it imports mermaid from the CDN) and the bytes were pre-staging a possible future
# Offline export at a cost of ~1,265 KB on every reader.
LIB_BYTES = {"mermaid": "mermaidGzipBase64", "chartjs": "chartjsGzipBase64"}

LIB_SOURCE = {"mermaid": ("mermaidUrl", "mermaidIntegrity"),
              "chartjs": ("chartjsUrl", "chartjsIntegrity")}

LIB_LICENSE = {"mermaid": "mermaidLicense", "chartjs": "chartjsLicense"}

# Every key that BELONGS to a library, in canonical order. `payload_matches` reads this to decide
# whether a payload holds anything belonging to a library the content cannot use, so a new field
# added above must appear here or an orphan of it would survive reconciliation forever.
LIB_FIELDS = {
    lib: (LIB_BYTES[lib],) + LIB_SOURCE[lib] + (LIB_LICENSE[lib],)
    for lib in ("mermaid", "chartjs")
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
    """The libraries this payload actually carries - a usable source AND a non-blank MIT notice.

    A library is carried when its notice is present and EITHER its bytes are, or a complete source
    descriptor (URL plus SRI hash) is. Both halves are required in each case: bytes with no notice
    are orphans the reconciler must drop rather than ship unlicensed, and a URL with no integrity
    hash is unverifiable, so accepting it would let an export inline whatever the network returned.
    """
    if not isinstance(obj, dict):
        return set()
    return {lib for lib in LIBRARIES
            if _field(obj, LIB_LICENSE[lib]) is not None and _lib_source(obj, lib) is not None}


def _lib_source(obj, lib):
    """The KEYS supplying this library's code, or None when neither form is complete."""
    if _field(obj, LIB_BYTES[lib]) is not None:
        return (LIB_BYTES[lib],)
    descriptor = LIB_SOURCE[lib]
    if all(_field(obj, key) is not None for key in descriptor):
        return descriptor
    return None


def lib_source_keys(obj, lib):
    """Public alias of `_lib_source`, for a caller that must copy one library as a whole FORM.

    A library is carried as BYTES or as a URL+integrity descriptor, never both, so anything that
    rebuilds a payload from several copies has to move the winning copy's form as a unit rather than
    key by key - otherwise the two forms coexist and the byte-preferring `_lib_source` makes the
    loser win (`vendored_libs.apply`, the duplicate-payload merge).
    """
    return _lib_source(obj, lib)


def _reconcile_source_keys(obj, lib):
    """Like `_lib_source`, but preferring the DESCRIPTOR when a source carries both forms.

    `_lib_source` answers "which form would be USED", and the runtime uses the bytes, so it must
    keep preferring them. Reconciliation answers a different question - "which form should this
    document KEEP" - and there the descriptor is the right answer: it is the smaller, verifiable,
    current form, and collapsing a mixed payload onto its bytes would make the megabyte canonical
    and permanent for a document that had already been right-sized.
    """
    descriptor = LIB_SOURCE[lib]
    if all(_field(obj, key) is not None for key in descriptor):
        return descriptor
    return _lib_source(obj, lib)


def payload_matches(obj, needed):
    """True when the payload carries EXACTLY `needed` and nothing belonging to any other library.

    Deliberately stricter than `carried_libs(obj) == needed`. A payload holding mermaid BYTES whose
    licence went missing carries no mermaid by the `carried_libs` rule, so on a chart-only document
    the two sets would agree and the reconciler would leave ~1,265 KB of unlicensed bytes sitting in
    the file forever. An orphan field is therefore a mismatch, which sends the payload through
    `reconcile` and drops it.

    A library carrying BOTH forms at once is a mismatch too. Only one of them can ever be used
    (`_lib_source` prefers the bytes), so the other is dead weight - and when it is the bytes that
    win, a document that was right-sized to a descriptor would keep paying for the megabyte it was
    supposed to have shed. Sending it through `reconcile` collapses it back to one form.
    """
    if carried_libs(obj) != needed:
        return False
    obj = obj if isinstance(obj, dict) else {}
    if any(_field(obj, LIB_BYTES[lib]) is not None
           and all(_field(obj, key) is not None for key in LIB_SOURCE[lib])
           for lib in needed):
        return False
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
        # Copy the form this source actually carries - a descriptor stays a descriptor, so a
        # right-sized document is never re-inflated back to the megabyte it just shed - plus the
        # notice, which travels with the library in either form. When a source carries BOTH forms
        # (only a hand edit or a stale merge produces that), the DESCRIPTOR wins here even though
        # `_lib_source` prefers bytes elsewhere: collapsing to the bytes would make the megabyte
        # canonical and permanent, which is the opposite of what reconciling a mixed payload is for.
        for key in _reconcile_source_keys(source, lib) + (LIB_LICENSE[lib],):
            out[key] = source[key]
    rebuilt = {key: out[key] for key in CANONICAL_KEYS if key in out}
    schema = set(CANONICAL_KEYS)
    for key, value in obj.items():
        if key not in schema:
            rebuilt[key] = value
    return rebuilt
