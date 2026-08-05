"""Author link target check: document-reference links must open in a new tab.

Mirrors the runtime new-tab stamping (assets/js/31-links.js, CMH-LINK-01): a
document reference (http/https/file, or a relative/root-relative/protocol-relative
URL that inherits the document protocol) is always opened in a NEW tab so a reviewer
is not navigated away from the report and their comments. The runtime forces this at
render time; this check warns the author when the source sets an explicit target that
would open the link in the SAME tab, so the intent is caught before handoff. Same-page
`#` fragments, `.cm-skip` UI chrome, and non-document schemes (mailto:/tel:/javascript:/
data:/...) are exempt - a new tab for those would strand a dead tab.
"""

import re

# Schemes that ARE document references (mirrors _cmhCommentableLink, which stamps only
# http/https/file). Everything else with an explicit scheme (mailto/tel/javascript/data/
# blob/...) is exempt from the new-tab rule.
_DOC_SCHEMES = ("http", "https", "file")

_SCHEME_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*:")

# Browsers (WHATWG URL parsing) strip ASCII tab, LF, and CR from ANYWHERE in a URL before
# parsing its scheme, so `java&#9;script:` normalizes to `javascript:`. Mirror that here (the
# document parser has already decoded the entity to a real control char) so an obfuscated
# non-document scheme is not misread as a relative document reference.
_URL_STRIP_RE = re.compile(r"[\t\n\r]")


def _href_scheme(href):
    """Return the lowercased URL scheme of href, or "" for a protocol-relative,
    root-relative, or relative URL (which inherits the document's protocol). The scheme
    regex is anchored and its character class excludes `/`, `?`, and `#`, so a ":" that
    belongs to a path/query/fragment (e.g. "path/to:x") never matches as a scheme."""
    m = _SCHEME_RE.match(href)
    if not m:
        return ""
    return m.group(0)[:-1].lower()  # matched text includes the trailing ":"


def _is_document_reference(href):
    raw = _URL_STRIP_RE.sub("", href or "").strip()
    if not raw or raw[0] == "#":
        return False
    scheme = _href_scheme(raw)
    return scheme == "" or scheme in _DOC_SCHEMES


def check_links(parser):
    """Warn when an author <a href> document reference inside #commentRoot sets an
    explicit target other than _blank (it would open in the SAME tab, navigating the
    reviewer away from the report and their comments). Any explicit target attribute whose
    trimmed value is not _blank is flagged, INCLUDING an empty/whitespace target (which the
    browser treats as the current tab); only a link with NO target attribute is exempt (the
    runtime defaults it to a new tab). mailto:/tel:/javascript:/data: schemes, same-page
    #fragments, and .cm-skip chrome are exempt, as is an <a> in ANY foreign namespace (SVG or
    MathML), which the runtime does not stamp because its tagName is "a", not "A". An <a> at an
    HTML integration point (<svg><foreignObject>, <math><mtext>) is HTML and IS checked. Returns
    a list of warning strings."""
    seen = []
    for a in parser.anchors:
        if a.get("skip") or a.get("foreign") or not a.get("in_root"):
            continue
        target = a.get("target")
        if target is None:
            continue
        if target.strip().lower() == "_blank":
            continue
        if not _is_document_reference(a.get("href")):
            continue
        entry = ((a.get("href") or "").strip(), target.strip())
        if entry not in seen:
            seen.append(entry)
    if not seen:
        return []
    sample = "; ".join('%s (target="%s")' % (href[:80] or "(no href)", tgt[:40])
                       for href, tgt in seen[:5])
    more = "" if len(seen) <= 5 else (" (and %d more)" % (len(seen) - 5))
    return ['link(s) open in the same tab instead of a new tab: %s%s - a document link must '
            'open in a new tab so the reviewer keeps their place and comments; remove the '
            'target (the runtime defaults to a new tab) or set target="_blank"' % (sample, more)]
