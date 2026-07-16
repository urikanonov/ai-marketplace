"""Self-contained / offline / NonPortable resource checks: external and network
resource detection, the offline CSP contract, companion-asset reference parsing,
and the NonPortable vs Portable/offline determination."""

import re
import os
from html.parser import HTMLParser
from urllib.parse import urlparse
from urllib.request import url2pathname
from .parsing import REGIONS, _find_tag_attrs

# A Chart.js loader filename, as a whole path segment: chart(.umd)?(.min)?.js,
# optionally followed by a query string / fragment; OR the bare pinned form
# chart.js@X.Y.Z that jsdelivr auto-resolves. Excludes flowchart.min.js,
# barchart.js, chart-utils.js, org-chart.js, etc.
CHARTJS_SRC_RE = re.compile(
    r"(?:^|/)chart(?:\.umd)?(?:\.min)?\.js(?:$|[?#])"
    r"|(?:^|/)chart\.js@\d+\.\d+\.\d+(?:$|[/?#])",
    re.IGNORECASE)

FETCHING_LINK_RELS = {
    "stylesheet", "preload", "modulepreload", "prefetch", "prerender",
    "preconnect", "dns-prefetch", "icon", "apple-touch-icon",
    "apple-touch-icon-precomposed", "manifest",
}

OFFLINE_CSP_REQUIRED = {
    "default-src": ("'none'",),
    "script-src": ("'unsafe-inline'",),
    "style-src": ("'unsafe-inline'",),
    "img-src": ("data:",),
    "font-src": ("data:",),
    "connect-src": ("'none'",),
    "frame-src": ("'none'",),
    "object-src": ("'none'",),
    "base-uri": ("'none'",),
    "form-action": ("'none'",),
    "frame-ancestors": ("'none'",),
}

CSS_NETWORK_URL_RE = re.compile(r"url\(\s*(['\"]?)(?:https?:)?//", re.IGNORECASE)

META_REFRESH_NETWORK_RE = re.compile(r"(?:^|[;,\s])url\s*=\s*(['\"]?)(?:https?:)?//", re.IGNORECASE)

NONPORTABLE_REGIONS = REGIONS

_ADX_RUN_HOST = "dataexplorer.azure.com"


def _is_adx_run_href(href):
    """True only for an https URL whose host is exactly the ADX web UX host.

    The href is already HTML-entity-decoded by the parser, so an encoded scheme
    (&#106;avascript:) is caught. Parsing the URL (not a substring match) means a
    javascript:/data: scheme or a look-alike host (dataexplorer.azure.com.evil.example)
    cannot pass."""
    try:
        u = urlparse((href or "").strip())
        host = (u.hostname or "").lower()
    except ValueError:
        return False
    return u.scheme == "https" and host == _ADX_RUN_HOST


def _link_loads(attrs):
    rels = set((attrs.get("rel") or "").lower().split())
    return bool(rels & FETCHING_LINK_RELS)


def _csp_directives(content):
    directives = {}
    for part in (content or "").split(";"):
        bits = part.strip().split()
        if bits:
            directives[bits[0].lower()] = bits[1:]
    return directives


def _offline_csp_errors(html):
    csp = [
        meta.get("content", "")
        for meta in _find_tag_attrs(html, "meta")
        if (meta.get("http-equiv") or "").lower() == "content-security-policy"
    ]
    if not csp:
        return ["offline mode: missing Content-Security-Policy meta tag with restrictive offline directives"]
    directives = _csp_directives(csp[0])
    errors = []
    for name, required_tokens in OFFLINE_CSP_REQUIRED.items():
        values = directives.get(name)
        if values is None:
            errors.append("offline mode: Content-Security-Policy must include %s %s"
                          % (name, " ".join(required_tokens)))
            continue
        missing = [token for token in required_tokens if token not in values]
        if missing:
            errors.append("offline mode: Content-Security-Policy %s must include %s"
                          % (name, " ".join(missing)))
        if "'none'" in required_tokens and values != ["'none'"]:
            errors.append("offline mode: Content-Security-Policy %s must be exactly 'none'" % name)
    return errors


# NonPortable companion references are detected by parsing real link/script/meta
# attributes with the tolerant HTMLParser (not a regex), so a '>' in a quoted
# value, an unquoted href/src, a reordered <meta content=.. name=..>, or a decoy
# tag inside a comment/script body is handled the same way as the rest of the
# validator.
def _ref_path(ref):
    """The path portion of a companion ref, without a ?query or #fragment cache-buster
    (e.g. 'commentable-html.js?v=1.7.0' -> 'commentable-html.js'), so suffix detection
    and the on-disk existence check ignore the cache-buster the browser strips too."""
    return re.split(r"[?#]", ref or "", maxsplit=1)[0]


def _file_url_to_path(ref):
    parsed = urlparse(ref or "")
    if parsed.scheme.lower() != "file":
        return None
    raw = ("//" + parsed.netloc + parsed.path) if parsed.netloc and parsed.netloc.lower() != "localhost" else parsed.path
    return os.path.abspath(url2pathname(raw))


def _nonportable_css_refs(html):
    return [_ref_path(a["href"]) for a in _find_tag_attrs(html, "link")
            if "commentable-html" in a.get("href", "").lower()
            and _ref_path(a.get("href", "")).lower().endswith(".css")]


def _nonportable_js_refs(html):
    return [_ref_path(a["src"]) for a in _find_tag_attrs(html, "script")
            if "commentable-html" in a.get("src", "").lower()
            and _ref_path(a.get("src", "")).lower().endswith(".js")]


def _nonportable_meta_versions(html):
    return [a.get("content", "") for a in _find_tag_attrs(html, "meta")
            if a.get("name", "").lower() == "commentable-html-version"]


def _is_nonportable(html):
    """NonPortable = the document references external commentable-html companion files."""
    return bool(_nonportable_css_refs(html) or _nonportable_js_refs(html))


def _check_nonportable(html, base_dir, id_counts):
    """NonPortable-mode-only invariants. Returns (errors, warnings)."""
    errors, warnings = [], []

    css_refs = _nonportable_css_refs(html)
    js_refs = _nonportable_js_refs(html)
    runtime_refs = [s for s in js_refs if not s.lower().endswith(".assets.js")]
    assets_refs = [s for s in js_refs if s.lower().endswith(".assets.js")]

    if not css_refs:
        errors.append('nonportable mode: no commentable-html stylesheet <link ... .css> found (the layer will be unstyled)')
    if not runtime_refs:
        errors.append('nonportable mode: no commentable-html runtime <script src ... .js> found (the layer will not load)')
    if not assets_refs:
        warnings.append('nonportable mode: no commentable-html.*.assets.js is referenced - "Export with embedded comments" cannot rebuild a portable file (add the assets companion or ship a standalone copy)')

    # Version stamp: a <meta name="commentable-html-version"> records the skill
    # version that produced the file and lets the runtime detect a stale companion
    # by comparing it against the loaded runtime's CMH_VERSION.
    metas = _nonportable_meta_versions(html)
    if not metas:
        warnings.append('nonportable mode: missing <meta name="commentable-html-version" content="X"> - the runtime cannot detect a stale/mismatched companion file')

    # Mandatory missing-asset banner: if the external runtime never loads, the
    # page must say so instead of looking fine but dead.
    if id_counts.get("cmhAssetBanner", 0) == 0:
        errors.append('nonportable mode: missing the #cmhAssetBanner element (a broken companion load would fail silently) - keep the NONPORTABLE BOOTSTRAP block')
    if "__commentableHtmlReady" not in html:
        warnings.append('nonportable mode: no bootstrap watchdog (looked for __commentableHtmlReady) - the missing-asset banner will never reveal itself')

    # Referenced companion files must resolve to a local file that exists. NonPortable
    # intentionally points at the skill's dist/ folder (a relative subdirectory or a
    # ../ path, or an absolute file:// URL), so a subfolder / parent reference is
    # allowed. Network URLs and non-file schemes are rejected, absolute filesystem
    # paths are warned about, and a missing target errors.
    # The remote-URL and absolute-path checks are structural (they inspect the ref
    # string only), so they always run. Only the on-disk existence check needs a
    # base_dir; when base_dir is None the placement is deferred (e.g. generation-time
    # validation of a not-yet-placed document), so existence is not checked - the
    # structure is still validated.
    for ref in css_refs + js_refs:
        if re.match(r"(?:https?:)?//", ref, re.I):
            errors.append('nonportable mode: companion reference "%s" must be a local file, not a remote/CDN URL (the layer must stay self-contained)' % ref)
            continue
        norm = ref.replace("\\", "/")
        file_target = _file_url_to_path(ref)
        if file_target is not None:
            target = file_target
        elif re.match(r"[a-zA-Z][a-zA-Z0-9+.\-]*:", ref) and not re.match(r"[a-zA-Z]:[\\/]", ref):
            errors.append('nonportable mode: companion reference "%s" must be a local file, not a non-file URL scheme' % ref)
            continue
        elif norm.startswith("/") or re.match(r"[a-zA-Z]:", ref):
            # Absolute path: usable but leaks a local directory and is not portable.
            warnings.append('nonportable mode: companion reference "%s" is an absolute path (it leaks a local directory and is not portable) - prefer a relative path to the skill dist/ folder' % ref)
            target = os.path.abspath(ref)
        elif base_dir is not None:
            # Relative ref resolved against the document folder; a subdirectory or
            # ../ path to the skill dist/ folder is the intended nonportable workflow.
            target = os.path.abspath(os.path.join(os.path.abspath(base_dir), norm))
        else:
            target = None
        if target is not None and (base_dir is not None or file_target is not None) and not os.path.exists(target):
            errors.append('nonportable mode: referenced companion file not found: %s (point the <link>/<script src> at the skill dist/ folder, or copy dist/ next to the document)' % ref)

    return errors, warnings
