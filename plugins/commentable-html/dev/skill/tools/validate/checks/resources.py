"""Self-contained / offline / NonShareable resource checks: external and network
resource detection, the offline CSP contract, companion-asset reference parsing,
and the NonShareable vs Shareable/offline determination."""

import re
import os
import json
import tempfile
from html.parser import HTMLParser
from urllib.parse import urlparse
from urllib.request import url2pathname
from .parsing import REGIONS, _DocParser, _find_tag_attrs, _parse_document

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

# A network URL in a CSS `url(...)`. This keeps the slashes-required `(?:https?:)?//` shape on
# purpose, unlike the meta-refresh gate below: a CSS fetch is closed by the offline CSP, and the
# pattern is mirrored by the exporter's own CSS strip in `assets/js/68-export-offline.js`, so
# widening this copy ALONE would make the gate reject a file the exporter just produced. Issue #961
# widens both sides together; see the CMH-VAL-08 spec row.
CSS_NETWORK_URL_RE = re.compile(r"url\(\s*(['\"]?)(?:https?:)?//", re.IGNORECASE)

# A network URL in an attribute value, read AFTER the URL parser's own input cleanup (see
# `normalize_url_value` below), so the spellings a browser normalizes into a network load - an
# embedded ASCII tab or newline, a backslash authority - are not read as relative references. The
# character ranges are written out as literal code points because the offline export carries an
# INDEPENDENT JavaScript copy of this predicate (`_OFFLINE_NETWORK_URL_RE` in
# `assets/js/68-export-offline.js`) and the two engines do not agree about what `\s` means (Python's
# is Unicode-aware and matches U+001C-U+001F; JS's excludes them but includes U+FEFF). A drift here
# is the CMH-OFFLINE-04 failure mode - the gate blesses a file the strip would have cleaned, or
# rejects one the exporter just produced. `re.ASCII` is on for the same reason: Python's
# `re.IGNORECASE` case-folds across the whole of Unicode, so `s` also matches U+017F (LATIN SMALL
# LETTER LONG S) and `http<U+017F>://host` would be a network URL to the gate but not to a JS `/i`
# regex, which never folds a non-ASCII character onto an ASCII one.
# An explicit `file:` authority counts as a network load for the same reason the meta-refresh gate
# below counts it: on Windows `file://host/x.js` is an SMB fetch off the machine. How many
# separators open that authority is NOT "two or more" - a real Chromium (checked, not assumed) reads
# exactly two OR four-or-more as an authority, while THREE is the empty host of an ordinary local
# path (`file:///C:/x`), so `file:////evil.example/x.js` really does fetch and a `(?!/)` test alone
# called it local. Two host spellings that stay on the machine are excluded whatever the separator
# count: `localhost`, the local machine by definition, and a Windows DRIVE LETTER, which the
# file-host state turns into a path rather than a host, because reporting either would reject an
# offline file with no egress at all - and make the exporter delete the author's local reference.
# The drive-letter test deliberately does NOT require a separator after the `:` or `|`: a real
# Chromium resolves EVERY `file://` authority that STARTS with one to a local drive path, so
# `file://C:/x`, `file://C:foo/x` and even `file://c:evil.example/x` are all the local file
# `file:///C:/...` with an empty host, and demanding the separator over-detected the last two.
# The `(?!/)` after the long run is what stops the engine BACKTRACKING out of those exclusions: a
# greedy `/{4,}` alone matches five slashes, fails the `localhost` lookahead, gives a slash back and
# then matches on the four-slash reading, so `file://///localhost/x` (local) came out network.
# Every arm requires a NON-EMPTY authority. An authority terminated immediately by `?`, `#` or the
# end of the value is an empty host, which no browser fetches from: for a special scheme it is a
# parse FAILURE (`//?q`, `https://`, and the Windows extended-length path `\\?\C:\x`, which the
# backslash mapping turns into `//?/C:/x`, were all checked to fail parsing), and from a `file:`
# document it is the local root. Reporting one would delete an author's value over a reference that
# loads nothing.
# `\Z` rather than `$` in those lookaheads: Python's `$` also matches before a trailing newline
# where a JS `$` matches only at the end of input, so `$` here would be a silent engine drift for
# any caller that reached the pattern without `normalize_url_value` (which removes newlines) first.
# The http/https arm still requires the `//`, unlike the meta-refresh gate below: an attribute fetch
# is closed by the offline CSP, and widening only this copy would reject a file the exporter just
# produced. Issue #961 moves both sides together; see the CMH-VAL-08 spec row.
NETWORK_URL_RE = re.compile(
    r"(?:(?:https?:)?//(?![?#]|\Z)"
    r"|file:(?://(?!/)|/{4,}(?!/))(?![?#]|\Z)(?!localhost(?:[/?#]|\Z))(?![A-Za-z][:|]))",
    re.IGNORECASE | re.ASCII)

# Every character a URL parser removes from its input before it parses: leading and trailing C0
# controls or spaces (U+0000-U+0020), and ASCII tab, LF and CR ANYWHERE inside the value.
_URL_LEADING_TRAILING_STRIP = "".join(chr(c) for c in range(0x21))
_URL_INNER_REMOVE_RE = re.compile(r"[\t\n\r]")


def normalize_url_value(value):
    """A reference as the URL PARSER sees it, so a literal test reads what a browser will fetch.

    Three cleanups, all of them the parser's own: strip leading and trailing C0-or-space, remove
    ASCII tab/LF/CR from anywhere, and map every backslash onto a slash (for a special scheme the
    parser's relative and authority-slash states treat the two alike, so `https:/\\host/x.js` and
    `\\\\host/x.js` both open an authority). Mirrored byte-for-byte in the exporter's
    `_offlineNormalizeUrlValue`; `tests/test_vendored_libs.py` pins the pair through the real JS
    engine.
    """
    return _URL_INNER_REMOVE_RE.sub("", str(value or "")).strip(_URL_LEADING_TRAILING_STRIP).replace("\\", "/")


def is_network_url(value):
    """True when an attribute value names a resource a browser would fetch over the network."""
    return bool(NETWORK_URL_RE.match(normalize_url_value(value)))


# HTML's srcset parser splits candidates on ASCII whitespace ONLY - tab, LF, FF, CR and space - so
# tokenizing with the ENGINE's idea of whitespace was wrong twice over: U+000B is engine whitespace
# but not ASCII whitespace, so `"\u0001\u000bhttps://host/x 1x"` was cut at the U+000B and both
# sides tested `"\u0001"` while the browser fetched the host; and the two engines disagree about the
# rest (Python's `str.strip()`/`split()` take U+001C-U+001F, JS's `trim()` takes U+FEFF), which is
# the CMH-OFFLINE-04 drift. Only the candidate BOUNDARY is decided here; every character the URL
# parser itself removes is left to `normalize_url_value`. Mirrored in the exporter's
# `_offlineSrcsetCandidateUrl` / `_offlineSrcsetHasNetwork`.
_SRCSET_WS_RE = re.compile(r"[\t\n\f\r ]+")


def srcset_candidate_urls(value):
    """Every string in a `srcset` a browser could load, tokenized the way HTML's parser does.

    Two readings are collected, because splitting on the comma ALONE is not what HTML does: its
    srcset parser collects a run of non-ASCII-whitespace as the URL, so a comma INSIDE that run
    belongs to the URL (`srcset="https://,host/x.png 1x"` requests `https://,host/x.png` - measured
    in a real Chromium). A comma-split alone therefore tests the truncated `https://`, which is an
    empty authority and local. The whitespace-run reading alone is not enough either, because two
    candidates may be separated by a comma with no space around it. Taking the UNION costs nothing:
    a descriptor (`1x`, `320w`) can never match the network predicate. Mirrored in the exporter's
    `_offlineSrcsetCandidateUrls`.
    """
    text = str(value or "")
    urls = []
    for part in text.split(","):
        url = _SRCSET_WS_RE.split(part.lstrip("\t\n\f\r "))[0]
        if url:
            urls.append(url)
    for token in _SRCSET_WS_RE.split(text):
        token = token.strip(",")
        if token and token not in urls:
            urls.append(token)
    return urls


def srcset_has_network(value):
    """True when any candidate in a `srcset` names a network resource."""
    return any(is_network_url(url) for url in srcset_candidate_urls(value))


# Every attribute through which a <script> can LOAD its code. An SVG <script> uses none of the
# HTML `src` spelling: it loads through SVG2 `href` or the legacy `xlink:href`, and its body is
# empty, so a `src`-only check saw nothing at all. Kept beside the predicate above because the
# offline strip carries the same list as `_OFFLINE_SCRIPT_LOAD_ATTRS`, and
# `test_the_python_and_js_script_load_attributes_agree` pins the two together.
SCRIPT_LOAD_ATTRS = ("src", "href", "xlink:href")


# A DIRECT scripted top-level navigation to a network URL, in an inline script an offline file
# still carries. It is a SCAN rather than one pattern, and the shared parts below are BYTE-IDENTICAL
# to the same-named regex literals in assets/js/68-export-offline.js (including the JS-only `\/`
# escapes, which Python also reads as a literal `/`); tests/test_vendored_libs.py pins that equality
# plus a behavioural corpus that runs the exporter's own scanner through the real JS engine whenever
# node is present. The exporter's strips drop such a script, and this gate must not then certify a
# hand-authored offline file that keeps one. Top-level navigation is the one egress channel the
# offline CSP cannot close - `navigate-to` was dropped from CSP Level 3 and `sandbox` is ignored in
# a meta-delivered policy - so the check is where the guarantee is enforced at all.
# WHY A SCAN. The single pattern this replaced carried the global-prefix chain as an unbounded
# repetition in front of the sink, so the engine re-entered that chain at every position a prefix
# could follow, and a long NEAR-match cost quadratic time: `window . ` repeated took 2.3s at 18 KB
# and 174s at 144 KB here, 4x the time for 2x the input. Both callers feed it unbounded
# document-supplied text - every runnable inline script, and (in the exporter) the vendored
# payload's INFLATED bytes, where a few hundred base64 bytes buy megabytes of near-match. Every
# shape recognized here requires the literal `location` or `open`, so the scan is driven from THOSE
# anchors: forward from an anchor the tail is a regex matched ANCHORED at that offset, with every
# unbounded whitespace run followed by a distinct non-whitespace literal so no run can be split two
# ways; backward from an anchor the prefix chain is walked once in code. Prefix chains for two
# different anchors cannot overlap, because no sink name is a prefix name, so the scan is linear.
# Every metacharacter whose meaning DIFFERS between the two engines is spelled out rather than
# shared: `\w` is ASCII-only in JS but Unicode-aware in Python, and JS whitespace includes U+FEFF
# while Python's does not. Sharing them made the copies disagree on real inputs - a `location.href`
# assignment separated from its URL by a U+FEFF is valid JS that the exporter stripped and this
# gate then certified as offline-clean.
# `re.ASCII` is REQUIRED, not cosmetic: Python's `re.IGNORECASE` otherwise case-folds several
# non-ASCII letters onto ASCII ones (the dotless i, the long s, the Kelvin sign) that JS's `/i`
# does not, so `locat<dotless-i>on.href = <url>` - source the exporter PRESERVES, because it is
# not a real `location` - would be rejected here. The prefix-name comparison is ASCII-folded in
# code for the same reason. That is the false-rejection direction of the same drift the spelled-out
# classes close, and the parity test asserts the flag is set.
# The URL literal is recognized in the literal prefixes a browser resolves to a network host, and in
# the spellings that NORMALIZE into one of those first - by the URL parser, or by the JavaScript
# parser that produced the string: scheme plus slashes, protocol-relative (slashes only), and
# SCHEME-ONLY - a quoted `https:`/`http:` with NO slashes after it, which a browser resolves to the
# same host, so requiring the slashes left the whole channel open to a one-token spelling change. On
# top of any of those the literal may carry the leading C0-or-space padding the URL parser strips
# (U+0001 to U+0020, NOT U+0000, because the HTML parser replaces a NUL in script data with U+FFFD,
# which the URL parser does not strip, so a NUL-padded literal can never navigate and matching it
# here would reject a file the exporter - which reads the PARSED text - preserves), an ASCII tab, LF
# or CR anywhere inside the scheme or between the two slashes, a backslash in place of either slash
# (for a special scheme the parser treats the two alike; a literal spends two source backslashes per
# runtime one), a LineContinuation - a backslash followed by a line terminator, which evaluates to
# nothing at all - and an escaping backslash before any literal element, since a backslash before a
# character that begins no escape sequence evaluates to that character. What is still missed is the
# class raw source cannot READ: a MULTI-character escape that ENCODES one of those characters
# (a `u0068` / `x68` / octal escape), which needs a string-literal decoder rather than a regex, and
# a `javascript:` wrapper that assigns the real URL at runtime - the latter a deliberate trade
# rather than a visibility limit, since a script able to write it already runs arbitrary code. Both
# are listed in the CMH-OFFLINE-05 residual.
OFFLINE_NAV_ANCHOR_RE = re.compile(r"location|open", re.IGNORECASE | re.ASCII)
OFFLINE_NAV_PROP_TAIL_RE = re.compile(
    r"[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*(?:\?[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*)?\.[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*"
    r"(?:href[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*=(?!=)|(?:assign|replace)[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*\()[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*"
    r"""["'`](?:\\?[\u0001-\u0020]|\\[\u2028\u2029])*(?:\\?h(?:\\?[\t\n\r]|\\[\u2028\u2029])*\\?t(?:\\?[\t\n\r]|\\[\u2028\u2029])*\\?t(?:\\?[\t\n\r]|\\[\u2028\u2029])*\\?p(?:\\?[\t\n\r]|\\[\u2028\u2029])*(?:\\?s(?:\\?[\t\n\r]|\\[\u2028\u2029])*)?\\?:|(?:\\?\/|\\\\)(?:\\?[\t\n\r]|\\[\u2028\u2029])*(?:\\?\/|\\\\))""",
    re.IGNORECASE | re.ASCII)
OFFLINE_NAV_ASSIGN_TAIL_RE = re.compile(r"[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*=(?!=)[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*"
    r"""["'`](?:\\?[\u0001-\u0020]|\\[\u2028\u2029])*(?:\\?h(?:\\?[\t\n\r]|\\[\u2028\u2029])*\\?t(?:\\?[\t\n\r]|\\[\u2028\u2029])*\\?t(?:\\?[\t\n\r]|\\[\u2028\u2029])*\\?p(?:\\?[\t\n\r]|\\[\u2028\u2029])*(?:\\?s(?:\\?[\t\n\r]|\\[\u2028\u2029])*)?\\?:|(?:\\?\/|\\\\)(?:\\?[\t\n\r]|\\[\u2028\u2029])*(?:\\?\/|\\\\))""", re.IGNORECASE | re.ASCII)
OFFLINE_NAV_OPEN_TAIL_RE = re.compile(r"[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*\([ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*"
    r"""["'`](?:\\?[\u0001-\u0020]|\\[\u2028\u2029])*(?:\\?h(?:\\?[\t\n\r]|\\[\u2028\u2029])*\\?t(?:\\?[\t\n\r]|\\[\u2028\u2029])*\\?t(?:\\?[\t\n\r]|\\[\u2028\u2029])*\\?p(?:\\?[\t\n\r]|\\[\u2028\u2029])*(?:\\?s(?:\\?[\t\n\r]|\\[\u2028\u2029])*)?\\?:|(?:\\?\/|\\\\)(?:\\?[\t\n\r]|\\[\u2028\u2029])*(?:\\?\/|\\\\))""", re.IGNORECASE | re.ASCII)
OFFLINE_NAV_WS_RE = re.compile(r"[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]", re.ASCII)
OFFLINE_NAV_IDENT_RE = re.compile(r"[.A-Za-z0-9_$]", re.ASCII)
OFFLINE_NAV_STATEMENT_RE = re.compile(r"[;})>\n\r\u2028\u2029]", re.ASCII)
OFFLINE_NAV_LINE_BREAK_RE = re.compile(r"[\n\r\u2028\u2029]", re.ASCII)
OFFLINE_NAV_PREFIX_NAMES = ("window", "self", "top", "parent", "globalThis", "document", "frames")


# The PREFIXED-only sinks (`window.location...`, `top.open(...)`) are selected with the
# `prefixed_only` argument below: the prefix chain is mandatory there, and the bare
# statement-position `location =` alternative is dropped. Used when the script declares its own
# `location`, further down.

# A LOCAL binding named `location` - a declaration keyword, a destructuring declaration naming it,
# a function parameter, or a catch binding. Every quantifier is bounded, so it cannot backtrack.
OFFLINE_LOCAL_LOCATION_RE = re.compile(
    r"(?:^|[^.A-Za-z0-9_$])(?:(?:var|let|const|function|class)[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]+location(?![A-Za-z0-9_$])|(?:var|let|const)[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*"
    r"[{\[][^}\]]{0,400}location(?![A-Za-z0-9_$])|function[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*"
    r"[A-Za-z0-9_$]{0,100}[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*"
    r"\([^)]{0,400}location(?![A-Za-z0-9_$])|catch[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*"
    r"\([ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]*"
    r"location(?![A-Za-z0-9_$]))",
    re.IGNORECASE | re.ASCII)


def _offline_nav_ascii_lower(text):
    """ASCII-only case folding, mirroring `_offlineNavAsciiLower` in the exporter.

    `str.lower()` would fold non-ASCII letters onto ASCII ones (and change the string LENGTH for
    a few of them), which is the same drift `re.ASCII` closes for the patterns above.
    """
    out = []
    for ch in text:
        code = ord(ch)
        out.append(chr(code + 32) if 65 <= code <= 90 else ch)
    return "".join(out)


OFFLINE_NAV_PREFIX_LOWER = tuple(_offline_nav_ascii_lower(name)
                                 for name in OFFLINE_NAV_PREFIX_NAMES)
OFFLINE_NAV_PREFIX_MAX = max(len(name) for name in OFFLINE_NAV_PREFIX_LOWER)


def _offline_nav_skip_ws_back(src, pos):
    while pos > 0 and OFFLINE_NAV_WS_RE.match(src, pos - 1):
        pos -= 1
    return pos


def _offline_nav_boundary_ok(src, pos):
    return pos == 0 or not OFFLINE_NAV_IDENT_RE.match(src, pos - 1)


def _offline_nav_prefix_start(src, pos):
    """Start index of a global prefix name ending at `pos`, or -1.

    One ASCII fold per chain element rather than one per candidate name: the tail is folded once at
    the longest name's width and every name is then tested against it. Seven folds per element cost
    3s on a 1.4 MB chain of them, which is linear but with a constant big enough to matter.
    """
    tail = src[max(0, pos - OFFLINE_NAV_PREFIX_MAX):pos]
    # `str.lower()` is C-fast and, on an ASCII slice, is exactly the ASCII fold; the per-character
    # fold is only needed when the slice carries a non-ASCII character, which is where `str.lower()`
    # would part company with the JS engine.
    tail = tail.lower() if tail.isascii() else _offline_nav_ascii_lower(tail)
    for name in OFFLINE_NAV_PREFIX_LOWER:
        if pos >= len(name) and tail.endswith(name):
            return pos - len(name)
    return -1


def _offline_nav_chain_ok(src, index, require_prefix):
    r"""The global-prefix chain read BACKWARDS from a sink, mirroring `_offlineNavChainOk`.

    Stands in for the old pattern's `(?:^|[^.A-Za-z0-9_$])(?:PREFIX WS* (?:\? WS*)? \. WS*)*`
    head. The boundary is tested at EVERY chain length rather than only the longest, because a
    shorter chain can end on a whitespace character that is itself a legal boundary - `$window . `
    in front of a bare sink matches with no chain at all.
    """
    pos = index
    taken = 0
    while True:
        if (taken > 0 or not require_prefix) and _offline_nav_boundary_ok(src, pos):
            return True
        scan = _offline_nav_skip_ws_back(src, pos)
        if scan == 0 or src[scan - 1] != ".":
            return False
        scan = _offline_nav_skip_ws_back(src, scan - 1)
        if scan > 0 and src[scan - 1] == "?":
            scan = _offline_nav_skip_ws_back(src, scan - 1)
        start = _offline_nav_prefix_start(src, scan)
        if start < 0:
            return False
        pos = start
        taken += 1


def _offline_nav_statement_start(src, index):
    """The `(?:^|[;})>\n\r\u2028\u2029])WS*` head a bare statement-position sink must follow.

    The run is inspected rather than skipped because a line break inside it is itself a legal
    delimiter. Mirrors `_offlineNavStatementStart`.
    """
    pos = index
    while pos > 0 and OFFLINE_NAV_WS_RE.match(src, pos - 1):
        if OFFLINE_NAV_LINE_BREAK_RE.match(src, pos - 1):
            return True
        pos -= 1
    return pos == 0 or bool(OFFLINE_NAV_STATEMENT_RE.match(src, pos - 1))


def offline_nav_sink_index(src, prefixed_only):
    """Index of the first sink that navigates to a network URL literal, or -1.

    Mirrors `_offlineNavSinkIndex` in assets/js/68-export-offline.js. `prefixed_only` drops the two
    UNPREFIXED shapes, for a script that declares its own `location` binding.
    """
    pos = 0
    while True:
        m = OFFLINE_NAV_ANCHOR_RE.search(src, pos)
        if not m:
            return -1
        at, after = m.start(), m.end()
        pos = at + 1
        if after - at == 4:
            if OFFLINE_NAV_OPEN_TAIL_RE.match(src, after) and _offline_nav_chain_ok(src, at, True):
                return at
            continue
        if (OFFLINE_NAV_PROP_TAIL_RE.match(src, after)
                and _offline_nav_chain_ok(src, at, prefixed_only)):
            return at
        if OFFLINE_NAV_ASSIGN_TAIL_RE.match(src, after) and (
                _offline_nav_chain_ok(src, at, True)
                or (not prefixed_only and _offline_nav_statement_start(src, at))):
            return at


def offline_script_navigates_to_network(body):
    """True when an inline script scripts a top-level navigation to a network URL literal.

    Mirrors `_offlineScriptNavigatesToNetwork` in assets/js/68-export-offline.js. A script that
    declares its OWN `location` is talking about that object, not the document's, so only the
    PREFIXED sinks still count there - `const location = {}; location.href = <url>` navigates
    nothing, and rejecting it would flag a document the exporter deliberately preserves.
    """
    src = body or ""
    if offline_nav_sink_index(src, False) < 0:
        return False
    if OFFLINE_LOCAL_LOCATION_RE.search(src):
        return offline_nav_sink_index(src, True) >= 0
    return True


# The URL a `<meta http-equiv="refresh">` navigates to, decided by APPLYING the HTML "shared
# declarative refresh steps" rather than by matching `url=` in the raw attribute text. A meta
# refresh is a TOP-LEVEL NAVIGATION, so no policy delivered in a `<meta>` can close it (the same
# reason CMH-OFFLINE-05 gives for the scripted sinks above), which makes this gate the only thing
# standing between a hand-authored offline file and the beacon - and a regex over the raw text was
# wrong in BOTH directions. The keyword and its `=` are OPTIONAL: after the time and its `;`, `,`
# or whitespace separator, anything that is not `url` is taken as the URL itself, so
# `content="0;https://evil.example"` navigates while a `url=`-anchored pattern saw nothing. In the
# other direction, a value with NO time (`url=https://evil`) is not a refresh at all, and a QUOTED
# value is truncated at its closing quote, so `url='./x;url=https://evil'` is a local path a text
# scan read as egress. Only ASCII whitespace is skipped, as the algorithm says: `url<NBSP>=...`
# makes the whole tail a relative reference.
_META_REFRESH_ASCII_WS = " \t\n\f\r"
_META_REFRESH_DIGITS = "0123456789"


def meta_refresh_target(content):
    """The URL string a browser would resolve from a refresh meta's `content`, or "" for none.

    Implements the HTML shared declarative refresh steps up to the point the URL is extracted; the
    caller decides what the literal means. An empty return covers both "not a refresh" and "a
    reload with no URL".
    """
    s = content or ""
    n = len(s)
    i = 0
    while i < n and s[i] in _META_REFRESH_ASCII_WS:
        i += 1
    start = i
    while i < n and s[i] in _META_REFRESH_DIGITS:
        i += 1
    if i == start and (i >= n or s[i] != "."):
        return ""
    while i < n and (s[i] in _META_REFRESH_DIGITS or s[i] == "."):
        i += 1
    if i < n:
        if s[i] not in ";," and s[i] not in _META_REFRESH_ASCII_WS:
            return ""
        while i < n and s[i] in _META_REFRESH_ASCII_WS:
            i += 1
        if i < n and s[i] in ";,":
            i += 1
        while i < n and s[i] in _META_REFRESH_ASCII_WS:
            i += 1
    if i >= n:
        return ""
    # Step 1 of the URL branch: the target is the WHOLE remainder, captured BEFORE the `url`
    # keyword is probed. Only a `u`/`U` mismatch falls through to the quote step; a later mismatch
    # (`r`, `l`, or the `=`) jumps straight to PARSE with that untouched remainder, which is why a
    # near miss like `0;urhttps://host` is the relative reference `urhttps://host` and not the
    # network URL the consumed prefix would suggest.
    url = s[i:]
    if s[i] in "Uu":
        i += 1
        if not (i < n and s[i] in "Rr"):
            return url
        i += 1
        if not (i < n and s[i] in "Ll"):
            return url
        i += 1
        while i < n and s[i] in _META_REFRESH_ASCII_WS:
            i += 1
        if not (i < n and s[i] == "="):
            return url
        i += 1
        while i < n and s[i] in _META_REFRESH_ASCII_WS:
            i += 1
    quote = ""
    if i < n and s[i] in "'\"":
        quote = s[i]
        i += 1
    url = s[i:]
    if quote:
        cut = url.find(quote)
        if cut >= 0:
            url = url[:cut]
    return url


# The refresh TARGET as a network literal, read after the URL parser's own input cleanup (ASCII
# tab and newline removed anywhere, leading AND trailing C0-or-space removed) so neither a padded
# nor a tab-split spelling passes as relative, and a value that is only `https:` plus padding is
# still the host-less parse failure a browser makes of it. The literal is recognized in the
# prefixes a browser resolves to a network host: scheme plus slashes, protocol-relative (slashes
# only), and SCHEME-ONLY - `https:evil.example` with NO slashes after the colon, which the URL
# parser sends through the special-authority states and resolves to the same host as
# `https://evil.example`. Requiring the slashes left the channel open to a one-token spelling
# change. Those states IGNORE any run of `/` or `\` after the scheme, which is why the slash run is
# consumed rather than counted, and they need a non-empty HOST, which is why one host character is
# required: `url=https:` and `url=https://` are parse FAILURES a browser does not navigate on, and
# reporting them as network URLs would reject an offline file that has no egress at all. That host
# test is a one-character approximation of the URL parser's, so a MALFORMED authority
# (`https://:80`) is still reported - the fail-CLOSED direction, and the right one for a gate whose
# miss is a beacon. An authority written with BACKSLASHES counts too (`\\host`, `/\host`): a
# special scheme's relative-slash state treats the two alike, so on a `file://` document those
# resolve to `file://host/...` - a UNC fetch off the machine, and a top-level navigation the CSP
# cannot stop either. The same host reached through an EXPLICIT `file:` scheme counts for the same
# reason, with the two spellings that stay on the machine excluded: a third slash means an empty
# host (`file:///C:/x`) and `localhost` is the local machine by definition. A SINGLE leading slash
# or backslash is a path, not an authority, so it stays local.
# `re.ASCII` is on so `re.IGNORECASE`
# cannot fold U+017F onto `s` and report a relative `http<U+017F>:x.html` as a network URL.
# Widening here introduces no exporter/validator drift: offline mode rejects EVERY
# `meta[http-equiv=refresh]` (as the strip removes every one), and this predicate only decides
# WHICH of the two messages that rejection carries - the one that names a network beacon.
# The NEIGHBOURING `(?:https?:)?//` gates deliberately keep the slashes (issue #961) - see the
# CMH-VAL-08 spec row.
META_REFRESH_NETWORK_URL_RE = re.compile(
    r"(?:https?:[/\\]*"
    r"|file:[/\\]{2}(?![/\\])(?!localhost(?:[/\\?#]|$))"
    r"|[/\\][/\\])[^/\\?#]",
    re.IGNORECASE | re.ASCII)

def meta_refresh_navigates_to_network(content):
    """True when a refresh meta's `content` names a network URL a browser would navigate to."""
    url = _URL_INNER_REMOVE_RE.sub("", meta_refresh_target(content))
    return bool(META_REFRESH_NETWORK_URL_RE.match(url.strip(_URL_LEADING_TRAILING_STRIP)))

# Script types that are ACTIVE without being JavaScript, so `_is_executable_js` never looked at
# them. They get different rules, mirroring `_offlineActiveDataScriptType` /
# `_offlineActiveDataBlockIsRemovable` in assets/js/68-export-offline.js, which
# tests/test_vendored_libs.py pins to these in the real JS engine:
#
# `speculationrules` is rejected outright - it exists only to make the browser fetch early, it shows
# a reader nothing, and a `"source": "document"` ruleset prefetches the document's own links without
# naming a URL at all, so no URL-shaped test could gate it.
#
# `importmap` is rejected only when it carries a reference the file cannot resolve on its own,
# decided by PARSING the JSON (a text scan closes one spelling of a URL and leaves `\u002f`, padding
# and an embedded tab). Every string counts, key as well as value, because an import map's `imports`
# and `scopes` keys are references too; a reference is non-local when it carries a scheme (`data:`
# and `blob:` included - they map a bare specifier onto code the document did not contain) or an
# authority prefix, which accepts a BACKSLASH as well as a slash in either position because a
# special scheme's relative and relative-slash states treat the two alike. An unparseable body, or a
# `src`, is rejected as well.
OFFLINE_ACTIVE_DATA_TYPES = ("importmap", "speculationrules")
OFFLINE_NONLOCAL_REF_RE = re.compile(r"^(?:[A-Za-z][A-Za-z0-9+.\-]*:|[/\\][/\\])")


def offline_active_data_script_type(attrs):
    """The normalized active-but-not-JavaScript script type, or "" when it is not one.

    These are HTML KEYWORD types, not MIME types, so a browser matches them exactly after trimming
    ASCII whitespace - `importmap;charset=utf-8` is inert data and must not be rejected.
    """
    t = (attrs.get("type", "") or "").strip("\t\n\f\r ").lower()
    return t if t in OFFLINE_ACTIVE_DATA_TYPES else ""


def offline_is_non_local_ref(value):
    """True when a reference is not resolvable inside the exported file on its own.

    Mirrors the URL parser's own input cleanup - it strips ASCII tab and newline ANYWHERE and
    leading C0-or-space - so neither a padded nor a tab-split spelling passes as relative.
    """
    s = re.sub(r"[\t\n\r]", "", str(value))
    s = re.sub(r"^[\x00-\x20]+", "", s)
    return bool(OFFLINE_NONLOCAL_REF_RE.match(s))


def _offline_json_has_non_local_ref(value):
    if isinstance(value, str):
        return offline_is_non_local_ref(value)
    if isinstance(value, list):
        return any(_offline_json_has_non_local_ref(v) for v in value)
    if isinstance(value, dict):
        return any(offline_is_non_local_ref(k) or _offline_json_has_non_local_ref(v)
                   for k, v in value.items())
    return False


def _reject_json_constant(name):
    # `JSON.parse` has no NaN/Infinity literals, but Python's json accepts them by default. Rejecting
    # them keeps the two parses deciding the same thing about the same bytes.
    raise ValueError("not valid JSON: %s" % name)


def offline_active_data_block_is_removable(stype, attrs, body):
    """Whether the offline exporter would remove this active-but-not-JavaScript block."""
    if stype == "speculationrules":
        return True
    if "src" in attrs:
        return True
    try:
        # The walk is inside the same guard as the parse, so a body nested deeply enough to hit the
        # recursion limit fails closed like an unparseable one instead of raising out of the check.
        return _offline_json_has_non_local_ref(
            json.loads(body or "", parse_constant=_reject_json_constant))
    except Exception:
        return True


NONSHAREABLE_REGIONS = REGIONS

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


# NonShareable companion references are detected by parsing real link/script/meta
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


# Well-known OS temporary-directory path shapes, as the cross-machine fallback for when a companion
# ref was baked on a different machine than the one validating it (so the current TMPDIR/gettempdir()
# roots do not match). Every fragment is ANCHORED to a filesystem/drive root so a durable project
# folder that merely CONTAINS a "tmp"/"var"/"appdata/local/temp" segment (e.g. "/home/user/tmp/dist/"
# or "D:/repo/appdata/local/temp/") is never matched - only a genuine root temp is. The match runs
# against the path AT/AFTER a drive-letter boundary, so a foreign Windows path that was abspath'd on
# POSIX ("<cwd>/c:/windows/temp/...") still anchors at its drive root.
_TEMP_ROOT_ANCHORED = (
    "/tmp/", "/var/tmp/", "/var/folders/", "/private/var/folders/",
    "/private/tmp/", "/windows/temp/",
)
# Windows AppData temp is per-user, so it is anchored to a user-profile prefix (/users/<name>/)
# rather than the drive root: a durable ".../appdata/local/temp/" without a /users/ prefix is not it.
_TEMP_USER_PROFILE_RE = re.compile(r"^/users/[^/]+/appdata/local/temp/")


def _canonical(path):
    """Absolute, symlink-resolved, case-normalized path. realpath canonicalizes macOS
    /var -> /private/var and Windows 8.3 short names (when the path exists) so temp-root and
    same-directory comparisons do not diverge on aliases; for a non-existent path it degrades
    to a lexical abspath, which is still correct for the string-fragment fallback."""
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


def _temp_roots():
    """Absolute, canonicalized OS temp roots for this machine (env overrides + gettempdir)."""
    roots = []
    for var in ("TMPDIR", "TEMP", "TMP"):
        val = os.environ.get(var)
        if val:
            roots.append(val)
    try:
        roots.append(tempfile.gettempdir())
    except Exception:
        pass
    out = []
    for r in roots:
        try:
            out.append(_canonical(r))
        except Exception:
            pass
    return out


def _rooted_at_drive(posix):
    """Return the path at/after the first drive-letter boundary (e.g. "c:/windows/temp/x" or
    "<cwd>/c:/windows/temp/x" -> "/windows/temp/x"), or the whole POSIX path when it has no drive
    (already rooted at "/"). This normalizes a foreign Windows path abspath'd on POSIX so temp
    detection anchors at the drive root instead of a spurious "<cwd>/" prefix."""
    m = re.search(r"(?:^|/)[a-z]:(/.*)$", posix)
    return m.group(1) if m else posix


def _is_temp_path(target):
    """True when an absolute filesystem path resolves inside an OS temporary directory,
    which the OS may delete at any time - a baked companion path there is a handoff hazard."""
    if not target:
        return False
    try:
        norm = _canonical(target)
    except Exception:
        norm = None
    if norm is not None:
        for root in _temp_roots():
            if norm == root or norm.startswith(root + os.sep):
                return True
    # Cross-machine fallback: match well-known temp path shapes in the raw ref string, anchored at
    # the filesystem/drive root so a durable folder merely containing a "tmp"/"appdata/local/temp"
    # segment is not mis-flagged, while a foreign Windows temp path abspath'd on POSIX still matches.
    rooted = _rooted_at_drive(target.replace("\\", "/").lower())
    if any(rooted.startswith(frag) for frag in _TEMP_ROOT_ANCHORED):
        return True
    return _TEMP_USER_PROFILE_RE.search(rooted) is not None


def _same_dir(a, b):
    """True when two directory paths are the same location (symlink-resolved, case-normalized)."""
    if not a or not b:
        return False
    try:
        return _canonical(a) == _canonical(b)
    except Exception:
        return False


def _same_dir(a, b):
    """True when two directory paths are the same location (symlink-resolved, case-normalized)."""
    if not a or not b:
        return False
    try:
        return _canonical(a) == _canonical(b)
    except Exception:
        return False


def _as_parser(doc):
    """`doc` is either an already-parsed `_DocParser` (the normal path - `validate()` parses the
    document once) or raw html, parsed here. Explicitly typed on `_DocParser` rather than "not a
    str", so an unexpected value (bytes, a Path) fails at the parse rather than surfacing as an
    AttributeError deep inside a check."""
    return doc if isinstance(doc, _DocParser) else _parse_document(doc)


def _layer_tags(doc, tag):
    """Attrs of every `tag` element the parser saw OUTSIDE the authored CONTENT region.

    `doc` is an already-parsed `_DocParser` (the normal path) or raw html. The LAYER's own
    companion references always sit outside that region - the CSS <link> in <head> before it, the
    runtime <script>s at the end of <body> after it - so an occurrence INSIDE it is the author's
    own prose. A document about commentable-html that DEMONSTRATES the companion markup was being
    read as NonShareable because of its own content.

    The region is taken from the PARSE, not from marker offsets in the text, so it is exactly the
    region a browser would agree on: real HTML comment markers, inside the live `#commentRoot`,
    outside an inert `<template>`, and never inside CDATA. A string-offset view could be steered
    (markers placed around the real references, or a `<style>`/`<script>` straddling the boundary)
    into blanking the layer itself and reporting a broken NonShareable document as Shareable."""
    parser = _as_parser(doc)
    return parser.layer_tags.get(tag, [])


def _nonshareable_css_refs(doc):
    return [_ref_path(a["href"]) for a in _layer_tags(doc, "link")
            if "commentable-html" in a.get("href", "").lower()
            and _ref_path(a.get("href", "")).lower().endswith(".css")]


def _nonshareable_js_refs(doc):
    return [_ref_path(a["src"]) for a in _layer_tags(doc, "script")
            if "commentable-html" in a.get("src", "").lower()
            and _ref_path(a.get("src", "")).lower().endswith(".js")]


def _nonshareable_meta_versions(doc):
    return [a.get("content", "") for a in _layer_tags(doc, "meta")
            if a.get("name", "").lower() == "commentable-html-version"]


def _is_nonshareable(doc):
    """NonShareable = the LAYER references external commentable-html companion files."""
    parser = _as_parser(doc)
    return bool(_nonshareable_css_refs(parser) or _nonshareable_js_refs(parser))


def _check_nonshareable(doc, base_dir, id_counts):
    """NonShareable-mode-only invariants. Returns (errors, warnings).

    `doc` is an already-parsed `_DocParser` or raw html; `id_counts` must count only ids OUTSIDE
    the authored CONTENT region (the parser's `layer_ids`), so an authored demonstration cannot
    stand in for the real bootstrap."""
    errors, warnings = [], []
    parser = _as_parser(doc)

    css_refs = _nonshareable_css_refs(parser)
    js_refs = _nonshareable_js_refs(parser)

    runtime_refs = [s for s in js_refs if not s.lower().endswith(".assets.js")]
    assets_refs = [s for s in js_refs if s.lower().endswith(".assets.js")]

    if not css_refs:
        errors.append('nonshareable mode: no commentable-html stylesheet <link ... .css> found (the layer will be unstyled)')
    if not runtime_refs:
        errors.append('nonshareable mode: no commentable-html runtime <script src ... .js> found (the layer will not load)')
    if not assets_refs:
        warnings.append('nonshareable mode: no commentable-html.*.assets.js is referenced - "Export with embedded comments" cannot rebuild a shareable file (add the assets companion or ship a standalone copy)')

    # Version stamp: a <meta name="commentable-html-version"> records the skill
    # version that produced the file and lets the runtime detect a stale companion
    # by comparing it against the loaded runtime's CMH_VERSION.
    metas = _nonshareable_meta_versions(parser)
    if not metas:
        warnings.append('nonshareable mode: missing <meta name="commentable-html-version" content="X"> - the runtime cannot detect a stale/mismatched companion file')

    # Mandatory missing-asset banner: if the external runtime never loads, the
    # page must say so instead of looking fine but dead.
    if id_counts.get("cmhAssetBanner", 0) == 0:
        errors.append('nonshareable mode: missing the #cmhAssetBanner element (a broken companion load would fail silently) - keep the NONSHAREABLE BOOTSTRAP block')
    if not parser.layer_ready_token:
        warnings.append('nonshareable mode: no bootstrap watchdog (looked for __commentableHtmlReady) - the missing-asset banner will never reveal itself')

    # Referenced companion files must resolve to a local file that exists. NonShareable
    # intentionally points at the skill's dist/ folder (a relative subdirectory or a
    # ../ path, or an absolute file:// URL), so a subfolder / parent reference is
    # allowed. Network URLs and non-file schemes are rejected, absolute filesystem
    # paths are warned about, and a missing target errors.
    # The remote-URL and absolute-path checks are structural (they inspect the ref
    # string only), so they always run. Only the on-disk existence check needs a
    # base_dir; when base_dir is None the placement is deferred (e.g. generation-time
    # validation of a not-yet-placed document), so existence is not checked - the
    # structure is still validated.
    doc_dir = os.path.abspath(base_dir) if base_dir is not None else None
    for ref in css_refs + js_refs:
        if re.match(r"(?:https?:)?//", ref, re.I):
            errors.append('nonshareable mode: companion reference "%s" must be a local file, not a remote/CDN URL (the layer must stay self-contained)' % ref)
            continue
        norm = ref.replace("\\", "/")
        file_target = _file_url_to_path(ref)
        baked_absolute = False
        if file_target is not None:
            target = file_target
            baked_absolute = True
        elif re.match(r"[a-zA-Z][a-zA-Z0-9+.\-]*:", ref) and not re.match(r"[a-zA-Z]:[\\/]", ref):
            errors.append('nonshareable mode: companion reference "%s" must be a local file, not a non-file URL scheme' % ref)
            continue
        elif norm.startswith("/") or re.match(r"[a-zA-Z]:", ref):
            # Absolute path: usable but leaks a local directory and is not shareable.
            warnings.append('nonshareable mode: companion reference "%s" is an absolute path (it leaks a local directory and is not shareable) - prefer a relative path to the skill dist/ folder' % ref)
            target = os.path.abspath(ref)
            baked_absolute = True
        elif base_dir is not None:
            # Relative ref resolved against the document folder; a subdirectory or
            # ../ path to the skill dist/ folder is the intended nonshareable workflow.
            target = os.path.abspath(os.path.join(os.path.abspath(base_dir), norm))
        else:
            target = None
        # CMH-VAL-16: a BAKED absolute/file:// companion ref pointing INTO an OS temp
        # directory that is not the document's own folder is an error, not a soft warning:
        # the OS reaps the temp dir, so the shared document silently loses its whole layer.
        # Relative refs bake no absolute location, and a companion sitting beside the
        # document (even in temp) keeps its existing behavior, so neither is flagged.
        if baked_absolute and target is not None and _is_temp_path(target) \
                and not _same_dir(os.path.dirname(target), doc_dir):
            errors.append('nonshareable mode: companion reference "%s" resolves inside a temporary directory, which the OS deletes - the shared document will lose its layer. Export a Shareable (single-file) copy, or copy dist/ to a durable folder next to the document' % ref)
            continue
        if target is not None and (base_dir is not None or file_target is not None) and not os.path.exists(target):
            errors.append('nonshareable mode: referenced companion file not found: %s (point the <link>/<script src> at the skill dist/ folder, or copy dist/ next to the document)' % ref)

    return errors, warnings
