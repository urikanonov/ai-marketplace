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

from .parsing import effective_link_target, url_ends_trim

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


def _browser_href(href):
    """`href` with the input cleanup a URL parser applies, so classification and the reported
    entry read the same string.

    Two cleanups: ASCII tab/LF/CR removed from anywhere (`_URL_STRIP_RE`), then the shared end
    trim (`url_ends_trim`, C0 controls and space). The parser trims the ends FIRST and removes the
    inner characters second; the order does not matter here because tab/LF/CR are themselves
    inside the trimmed range, so the surviving string is the same either way.

    The backslash-to-slash mapping `normalize_url_value` also applies is deliberately NOT done
    here: it cannot change a scheme (a `\\` never matches `_SCHEME_RE`), a leading `#`, or
    emptiness, which is all this reader decides. It is therefore NOT a canonical URL - do not
    reuse it for an ORIGIN decision (use `normalize_url_value`), and note that two hrefs a browser
    resolves to the same URL can still differ here (case, percent-encoding, `./..` segments).
    """
    return url_ends_trim(_URL_STRIP_RE.sub("", href or ""))


def _is_document_reference(href):
    """Whether `href` names a DOCUMENT a click would navigate to, read the way a browser reads it.

    The reading is `_browser_href`. Python's argument-less `str.strip()` was the wrong end trim -
    it reaches past ASCII into NBSP, U+2028, U+3000 and U+0085, which the parser KEEPS - and it
    failed PERMISSIVELY: stripping the NBSP off `href="&#xa0;mailto:x"` let `_href_scheme` see
    `mailto:` and exempted the link, where the runtime stamper resolves the same href through
    `new URL(...)`, gets the document's own protocol, and treats it as the document reference it
    is. The `#` test moves the same way: `href="&#xa0;#frag"` is NOT a same-page fragment (a
    browser resolves it to a DIFFERENT document, `%C2%A0#frag`), so an author-set `target="_self"`
    on one really does navigate the reviewer away from the report and their comments (#1156).
    """
    raw = _browser_href(href)
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
    HTML integration point (<svg><foreignObject>, <svg><desc>, <svg><title>, <math><mtext> and the
    other MathML text integration points, or an <annotation-xml> whose encoding a browser matches
    exactly) is HTML and IS checked. Returns a list of warning strings.

    The AUTHORED target is read through the shared `effective_link_target` (CMH-LINK-01) so the
    `<`-coercion applies here too: `target="x&#10;<"` is a name HTML replaces with `_blank`, so it
    opens a NEW tab and reporting it as opening in the same one is a false positive - fatal under
    `--strict`. The document's `<base target>` is deliberately NOT fed in: this check's question is
    whether the AUTHOR asked for the same tab, and the runtime overrides a document reference to
    `_blank` regardless of what the base says, so inheriting one here would invent a warning about
    markup the author never wrote on the link."""
    seen = []
    for a in parser.anchors:
        if a.get("skip") or a.get("foreign") or not a.get("in_root"):
            continue
        target = a.get("target")
        if target is None:
            continue
        if effective_link_target(target, None).strip().lower() == "_blank":
            continue
        if not _is_document_reference(a.get("href")):
            continue
        entry = (_browser_href(a.get("href")), target.strip())
        if entry not in seen:
            seen.append(entry)
    if not seen:
        return []
    # `%r` on the href for the same reason the KQL run-link diagnostic uses it: this check now
    # reports the paddings a browser-accurate reading keeps (NBSP, U+2028, U+0085), and
    # interpolating one raw would split the WARNING line or drive the reader's terminal.
    sample = "; ".join('%s (target="%s")' % (repr(href[:80]) if href else "(no href)", tgt[:40])
                       for href, tgt in seen[:5])
    more = "" if len(seen) <= 5 else (" (and %d more)" % (len(seen) - 5))
    return ['link(s) open in the same tab instead of a new tab: %s%s - a document link must '
            'open in a new tab so the reviewer keeps their place and comments; remove the '
            'target (the runtime defaults to a new tab) or set target="_blank"' % (sample, more)]
