"""Self-contained / offline / NonShareable resource checks: external and network
resource detection, the offline CSP contract, companion-asset reference parsing,
and the NonShareable vs Shareable/offline determination."""

import re
import os
import json
import tempfile
from html.parser import HTMLParser
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname
from .parsing import (REGIONS, FETCHING_LINK_RELS, SPECULATIVE_LINK_RELS, _DocParser, _HTML_WHITESPACE,
                      _ascii_lower, _parse_document, link_rel_tokens, script_code_runs,
                      url_ends_trim)

# A Chart.js loader filename, as a whole path segment: chart(.umd)?(.min)?.js,
# optionally followed by a query string / fragment; OR the bare pinned form
# chart.js@X.Y.Z that jsdelivr auto-resolves. Excludes flowchart.min.js,
# barchart.js, chart-utils.js, org-chart.js, etc.
CHARTJS_SRC_RE = re.compile(
    r"(?:^|/)chart(?:\.umd)?(?:\.min)?\.js(?:$|[?#])"
    r"|(?:^|/)chart\.js@\d+\.\d+\.\d+(?:$|[/?#])",
    re.IGNORECASE)

# `FETCHING_LINK_RELS` is imported above rather than defined here: the parser needs the same set for
# its own "can this element fetch before the policy?" test, and two copies would drift.

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

# What each required directive may carry BESIDES its required token. "The token is present" was
# never the question a fetch directive answers - a browser reads the whole source list, so
# `script-src 'unsafe-inline' https://evil.example` allows inline script AND remote script. The
# `'none'` directives were already exclusive; these four were not, which left `--strict` certifying
# a document as offline-clean while a real browser fetched and executed a remote script (issue
# #968). It matters beyond the direct hole, because the recorded reason for leaving the CSS and
# attribute network-literal gates at their slashes-required shape (CMH-VAL-08) is that this policy
# closes those fetch channels.
#
# The rule is an ALLOWLIST of source expressions that provably cannot cause a fetch, not an exact
# match on the string the exporter emits, so a legitimate hand-authored policy is not rejected for
# no reason. Each listed token permits inline content, evaluation, or a URL whose bytes are already
# in the file. Four shapes that LOOK inert are deliberately NOT listed:
#   'self'           - a `file://` document has an opaque origin, so what it matches is unspecified
#                      and has historically meant the containing directory: a fetch off the file.
#   'sha256-...'     - CSP3 matches a hash against an EXTERNAL script carrying `integrity`, so a
#                      hash in script-src is a network source.
#   'strict-dynamic' - grants whatever an already-trusted script loads, network included.
#   'nonce-...'      - only meaningful for markup the author controls, and it propagates trust
#                      through 'strict-dynamic'; an offline file has no use for one.
OFFLINE_CSP_ALLOWED = {
    "script-src": frozenset(("'unsafe-inline'", "'unsafe-eval'", "'wasm-unsafe-eval'",
                             "'unsafe-hashes'", "'report-sample'")),
    "style-src": frozenset(("'unsafe-inline'", "'unsafe-hashes'", "'report-sample'")),
    "img-src": frozenset(("data:", "blob:")),
    "font-src": frozenset(("data:", "blob:")),
}

# Directives that carry no SOURCE LIST at all, so the "may only tighten" test below cannot be asked
# of them: their values are a sink group, a policy name, or a sandbox flag, and none of the three
# can name a network host. `upgrade-insecure-requests` and `block-all-mixed-content` take no value.
# `sandbox` is IGNORED in a meta-delivered policy, and the Trusted Types pair only tightens the
# document, so tolerating all five costs the offline guarantee nothing and stops the gate rejecting
# a hand-authored file that layers on extra hardening. `report-uri`/`report-to` are deliberately
# absent - see the extra-directive loop for why.
OFFLINE_CSP_NON_FETCH = frozenset((
    "upgrade-insecure-requests", "block-all-mixed-content",
    "require-trusted-types-for", "trusted-types", "sandbox",
))

# HTML/CSP's own whitespace set: TAB, LF, FF, CR and SPACE, and nothing else. See `_csp_directives`
# for why Python's Unicode-aware `str.strip()`/`str.split()` cannot be used to tokenize a policy.
_CSP_ASCII_WS = "\t\n\f\r "
_CSP_ASCII_WS_RE = re.compile(r"[\t\n\f\r ]+")

# The `localhost` exclusion is spelled as the URL PARSER compares a host, not as a literal, because
# the parser percent-decodes a file host and lowercases it through domain-to-ASCII BEFORE the
# file-host state turns the exact string `localhost` into the EMPTY host: `file://local%68ost/x`
# parses to href `file:///x` in a real WHATWG parser, exactly like `file://localhost/x`. A literal
# test therefore reported a local reference as egress, which deletes the author's value and leaves
# the gate rejecting a file with no egress at all. One alternation per character, with BOTH hex rows
# per letter, because `re.IGNORECASE` folds `%6c` onto `%6C` but never onto `%4c` - and `%4c`
# decodes to `L`, which domain-to-ASCII lowercases back. Nothing that decodes to anything OTHER than
# `localhost` can match, so this cannot smuggle a host past the gate: `%2F` and `%00` are forbidden
# host code points and fail to parse outright (both checked), and a host that merely STARTS with
# `localhost` is stopped by the terminator that follows. Mirrored character for character in the
# exporter's `_OFFLINE_PCT_LOCALHOST`, and pinned to it by a TEXT-equality parity assertion (matching
# verdicts over a corpus cannot see a drift on a spelling the corpus does not carry).
# It covers PERCENT-ENCODING and CASE, which is the half of canonicalization a regex can model. It
# does NOT model the IDNA/UTS-46 half, so a spelling that only IDNA maps onto `localhost` is an
# ACCEPTED, deliberate over-detection: `file://<U+FF4C>ocalhost/x`, its percent-encoded UTF-8
# `file://%EF%BD%8Cocalhost/x`, `file://LOCALHO<U+017F>T/x` and the soft-hyphen `file://local%C2%ADhost/x`
# all parse to href `file:///x` (measured) and are still reported here. That residual is deliberate
# rather than an oversight: UTS-46 mapping cannot be written as a regex either side would agree on,
# and Python's `re.IGNORECASE` folds `s` onto U+017F where a JS `/i` never does, so ATTEMPTING it is
# how the two engines drift. Over-detecting costs the author's rare reference; under-detecting is a
# beacon the gate blesses, so the boundary is drawn on the safe side and the corpus pins these
# spellings as network so a future edit cannot move them silently.
_PCT_LOCALHOST = (r"(?:l|%[46]c)(?:o|%[46]f)(?:c|%[46]3)(?:a|%[46]1)(?:l|%[46]c)"
                  r"(?:h|%[46]8)(?:o|%[46]f)(?:s|%[57]3)(?:t|%[57]4)")
# What may FOLLOW that host for the exclusion to fire: the end of the value, a `?` or `#`, or a
# SINGLE path slash. A second slash is an egress MISS, not a local path:
# `file://localhost//not-a-host/x.js` empties the host and keeps `//not-a-host/x.js` as the PATH, so
# the parser canonicalizes it to `file:////not-a-host/x.js` (measured in a spec-conformant WHATWG
# parser; Chromium 149 instead KEEPS host `localhost` for that exact spelling, but re-parsing the
# canonical form is what reaches host `not-a-host`, so counting it is the fail-CLOSED reading either
# way) - which the four-or-more-slash
# arm right here calls an off-machine SMB load. The backslash spelling
# `file://localhost/\not-a-host/x.js` reaches it too, since the cleanup maps `\` onto `/`. The cost
# is that `file://localhost//C:/x.js`, canonically the LOCAL `file:////C:/x.js`, is over-reported;
# that is the fail-CLOSED direction this predicate takes everywhere else. "The end of the value" is
# what `file_network_arm`'s `stop` parameter decides, which is why the terminator is spelled inside
# the builder rather than as a constant beside the host.
# The rule both of the following exist to keep is CANONICALIZATION STABILITY: a value and the href
# the URL parser canonicalizes it to must get the SAME verdict, or a spelling hides an authority
# that only the parser sees. Two shapes broke it, and neither is reachable by a test that reads only
# the START of the value, because the parser's path state runs AFTER the host is emptied.
# (1) A DOUBLE-DOT segment pops the segment before it - including the very label an exclusion just
# matched. `file:////localhost/../not-a-host/x` and `file:////C:/../x.js` both canonicalize onto the
# four-separator UNC form with a different leading label, so a `..` anywhere in the path makes the
# arm match REGARDLESS of the exclusions. Every spelling the parser treats as a double-dot segment
# is covered - `..`, `.%2e`, `%2e.`, `%2e%2e`, case-insensitively.
# (2) An EMPTY path segment IS the four-separator form: `file:///.//x.js` and `file:/a/..//x.js`
# canonicalize to `file:////x.js` from a THREE-slash or even slash-less value the arms above never
# look at, so it needs an arm of its own that ignores the leading separator count entirely. The
# leading `/*(?!/)` consumes the whole separator run unbacktrackably, so only a `//` in the PATH
# counts, and the path scan stops at the query - which cannot change the path - and at whatever ends
# the value in the caller's context (`file_network_arm`'s `stop`).
# A fuzz of 421,560 values against a real URL parser measured the result: ZERO remain where the
# predicate says local while the value's own canonical form is egress. The cost is over-detection in
# the safe direction (93,789 of those values, all absurd spellings): an authored `file:///C:/a//b.png`
# or `file://localhost/a/../b.js` is now reported. Corpus rows pin both directions.
_FILE_DOTDOT_SEGMENT = r"(?:\.|%2e)(?:\.|%2e)"

# The `file:` AUTHORITY arm, written ONCE and read by every gate that asks "does this fetch?": the
# attribute predicate `NETWORK_URL_RE` below, and - through `CSS_NETWORK_START` - the CSS
# `url(...)`, `@import` and `image-set()` readers, the nested `srcdoc` scan that reuses them, and
# the deck gate that imports them. The CSS side used to carry NO `file:` arm at all, so
# `url(file://evil.example/x.png)` read LOCAL while the byte-identical attribute value read as
# egress (issue #1230). The recorded reason for leaving the CSS gates narrower was that the
# zero-network CSP closes those channels, and that is true of OFFLINE mode only: a SHAREABLE
# document has no CSP behind the gate, so one passed `--strict`, earned the
# `commentable-html-validated` stamp, and made an SMB request off the reader's Windows machine on
# open. Sharing the arm rather than hand-writing a second `file:` rule is the point: the separator
# arithmetic, both exclusions, the non-empty-authority rule and the two canonicalization arms below
# have exactly one definition, so neither side can be widened without the other.
# `stop` is the character-class BODY of whatever ENDS a value in the caller's context - empty for an
# attribute value, which runs to the end of the string, and `CSS_VALUE_STOP` for a stylesheet, where
# a quote, a `)`, CSS whitespace or a declaration/block terminator ends it. It is a PARAMETER rather
# than a constant because the arm's exclusions ask what FOLLOWS a host: `file://localhost` is a
# local reference either way, but only the caller knows that the `)` in `url(file://localhost)` is
# the end of the value and not a path character. Reading on past it called an author's local
# reference egress. The reasoning for each arm is recorded with `NETWORK_URL_RE` below, which is the
# predicate they were measured against.
def file_network_arm(stop=""):
    """The `file:` arms of the network predicate, for a value the caller's context ends at `stop`."""
    end = (r"[" + stop + r"]|\Z") if stop else r"\Z"
    seg = r"[^?#" + stop + r"]"
    return (r"file:(?://(?!/)|/{4,}(?!/))(?![?#]|" + end + r")"
            r"(?:(?=" + seg + r"*/" + _FILE_DOTDOT_SEGMENT + r"(?:[/?#]|" + end + r"))"
            r"|(?!" + _PCT_LOCALHOST + r"(?:[?#]|" + end + r"|/(?!/)))(?![A-Za-z][:|]))"
            r"|file:/*(?!/)" + seg + r"*?//")


# A network URL in a CSS `url(...)`, and the `@import` form beside it, recognized in the prefixes a
# browser resolves to a network host: scheme plus slashes, protocol-relative, and SCHEME-ONLY -
# `url(https:evil.example/x.png)` with NO slashes after the colon, which the URL parser's
# special-authority states resolve to the same host as `url(https://evil.example/x.png)`. Requiring
# the two slashes left the whole CSS channel open to a one-token spelling change. Those states
# IGNORE any run of `/` after the scheme, which is why the run is consumed rather than counted, and
# they need a non-empty HOST, which is why one host character is required: `url(https://)` and
# `url(//)` are parse failures that fetch nothing, and reporting one would reject a file with no
# egress at all (the exporter's strips never touched them either, so the gate used to reject what
# the strip left behind). That one character is an APPROXIMATION of the URL parser's host state, in
# the fail-CLOSED direction: a malformed authority is still reported, because a gate whose miss is a
# beacon should over-report rather than under-report - the same trade `NETWORK_URL_RE` below
# makes.
# Whitespace is spelled out as the ASCII set rather than written `\s` for the reason the srcset
# tokenizer below spells it out: the exporter's mirror runs in a JavaScript engine whose `\s` also
# takes U+00A0 and U+FEFF where Python's (under `re.ASCII`) does not, and neither is CSS whitespace,
# so a `\s` on both sides would classify `url(<U+FEFF>https:host/x)` differently in the two engines.
# `re.ASCII` for the reason `NETWORK_URL_RE` carries it: `re.IGNORECASE` would otherwise fold `s`
# onto U+017F and flag a `url(http<U+017F>://host)` a JS `/i` never matches. Both are mirrored by
# the exporter's own `_offlineCssNoNetwork` in `assets/js/68-export-offline.js` - the two sides move
# TOGETHER (issue #961), or the gate rejects a file the exporter just produced (the CMH-OFFLINE-04
# drift); `tests/test_vendored_libs.py` pins the pair by running the exporter's strip in the real JS
# engine over a shared corpus. What NEITHER side reads is a CSS ESCAPE (`url(https:\65 vil/x)`) or a
# comment between the at-keyword and its URL, so they agree there too; issue #1029 tracks giving
# both a CSS-token-aware reader, and #1166 re-weighed and kept that residual for the same reason
# (it is a paired gate-and-strip change, and it is the CSP that enforces egress offline).
# `CSS_WS`, `CSS_NETWORK_PREFIX`, `CSS_HOST_CHAR` and `CSS_NETWORK_START` are PUBLIC because the
# `image-set()` reader below and the deck gate's degraded fallback are assembled from them rather
# than from a hand copy of the prefix and host-character rule - which is exactly the drift #1129
# closed. `_CSS_AT_SEP` stays private - it is an `@import` assembly detail with no other consumer.
CSS_WS = r"[\t\n\f\r ]"
# The at-keyword's separator: whitespace, OR nothing at all when a quote follows. `@import"x.css";`
# is valid CSS - a `"` cannot continue an ident, so the at-keyword ends there - and really fetches,
# while a whitespace-only separator read it as unremarkable text. The lookahead is what keeps a
# DIFFERENT at-keyword (`@importurl(...)`) from matching.
_CSS_AT_SEP = CSS_WS + r"+|(?=['\"])"
# The same CLOSED scheme set as `NETWORK_URL_RE` below, for the same measured reason: a
# `url(ftp://host/x)` or `@import "ws://host/t.css"` fetches nothing from a `file:` document.
CSS_NETWORK_PREFIX = r"(?:https?:/*|/{2,})"
CSS_HOST_CHAR = r"[^/?#'\")\t\n\f\r ]"
# What ENDS a CSS value, as a character-class BODY: either quote character, the `)` that closes a
# `url()` or an `image-set()`, CSS whitespace, and the `;`/`{`/`}` that end a declaration or a block
# (the last three matter for the unquoted `@import` form and for the unterminated tokens a browser
# still fetches). `CSS_HOST_CHAR` is deliberately NOT the same set - it also excludes the URL
# STRUCTURE characters `/?#`, which end a host but not the value. This is what the shared `file:`
# arm is parameterized by, so `url(file://localhost)` reads local: the `)` is the end of the value,
# and reading on past it would report an author's local reference as egress.
CSS_VALUE_STOP = r"'\");{}\t\n\f\r "
# The one place a CSS reader decides "this reference reaches the network". Both arms come from a
# SHARED definition: http/https plus scheme-relative from `CSS_NETWORK_PREFIX`, and the `file:`
# authority from `file_network_arm` - the SAME arm `NETWORK_URL_RE` reads, so the separator
# arithmetic, the `localhost` and Windows drive-letter exclusions and the non-empty-authority rule
# cannot answer differently in a stylesheet than in an attribute (issue #1230). The `file:` arm
# consumes its own authority and needs no trailing `CSS_HOST_CHAR`, which the http/https arm still
# requires so an empty authority (`url(https://)`, `url(//)`) stays local.
CSS_NETWORK_START = (r"(?:" + CSS_NETWORK_PREFIX + CSS_HOST_CHAR
                     + r"|" + file_network_arm(CSS_VALUE_STOP) + r")")
CSS_NETWORK_URL_RE = re.compile(
    r"url\(" + CSS_WS + r"*(?:['\"]" + CSS_WS + r"*)?" + CSS_NETWORK_START,
    re.IGNORECASE | re.ASCII)
CSS_NETWORK_IMPORT_RE = re.compile(
    r"@import(?:" + _CSS_AT_SEP + r")(?:url\(" + CSS_WS + r"*)?(?:['\"]" + CSS_WS + r"*)?("
    + CSS_NETWORK_START + r"[^;'\")]*)",
    re.IGNORECASE | re.ASCII)

# `image-set()` (and its `-webkit-` alias) takes a BARE string candidate with no `url()` wrapper, so
# `background-image: image-set("https://evil.example/x.png" 1x)` really fetches and the `url()`
# pattern above cannot see it at all - a stamped shareable file carried one and validated
# STRICT-CLEAN (issue #1166). The reader lives HERE rather than beside its first caller because the
# deck gate already needed it: it was written there first (#1155) and hand-copying it into the
# strict gate is exactly the drift #1129 closed. The candidate pattern is assembled from the SAME
# `CSS_NETWORK_PREFIX` + `CSS_HOST_CHAR` fragments as the `url()` reading beside it, so the two
# cannot answer differently about a host, and the token-start alternation is what keeps a candidate
# ANYWHERE in the list visible: `image-set('local.png' 1x, '//evil/x.png' 2x)` really does fetch the
# second one at 2x DPR, and anchoring on the open paren saw only the first.
CSS_IMAGE_SET_OPEN_RE = re.compile(r"image-set\(", re.IGNORECASE | re.ASCII)
CSS_NETWORK_IMAGE_SET_RE = re.compile(
    r"(?:^|['\",(]|" + CSS_WS + r")" + CSS_NETWORK_START,
    re.IGNORECASE | re.ASCII)
# An unquoted one of these ends a CSS declaration or is markup, so the scan stops there. A `<` or
# `>` inside a QUOTE is a legal CSS string character, so it only stops the scan on the SECOND
# reading below - the one used when the list never closed. A NEWLINE inside a quote is different
# again: an unescaped LF, CR or FF makes a bad-string token, so the declaration is dropped and the
# string does not continue. Reading on past it let a broken earlier declaration swallow a later
# valid rule - and with it a real remote candidate the browser does fetch, because it recovers at
# the `}` (raised by the Copilot reviewer on this PR).
_CSS_IMAGE_SET_MARKUP = "<>"
_CSS_IMAGE_SET_STOP = "<>;{}"
_CSS_BAD_STRING = "\n\r\f"
# A candidate is read ANCHORED at its own start, exactly as `CSS_NETWORK_URL_RE` anchors immediately
# after `url(` and its optional quote. Searching the args string for a network prefix ANYWHERE
# instead was wrong in both directions: it reported a bare `data:image/svg+xml,<svg
# xmlns='http://www.w3.org/2000/svg'>` candidate - which fetches nothing at all - as egress, while a
# blanking pass added to keep the two readings from double-reporting one declaration could be made
# to swallow a LATER remote candidate (`image-set("x.png?q=url(" 1x, "https://evil/x.png" 2x)`
# validated clean). Reading candidate by candidate removes the need to blank anything: a candidate
# that IS a function token is simply skipped, because `url(...)` is the other reading's to report
# and `var(...)` is the recorded residual.
_CSS_ANCHORED_NETWORK_RE = re.compile(CSS_NETWORK_START, re.IGNORECASE | re.ASCII)
_CSS_FUNC_START_RE = re.compile(r"[A-Za-z-][A-Za-z0-9-]*\(", re.ASCII)
_CSS_WS_CHARS = "\t\n\f\r "


def _css_image_set_scan(text, start, markup_ends_a_string):
    """Where one `image-set(` argument list ends, and whether it CLOSED with its own `)`."""
    depth, i, quote, end = 1, start, "", len(text)
    while i < end:
        ch = text[i]
        if ch == "\\":       # a CSS escape: whatever follows is a literal, never a delimiter
            i += 2
            continue
        if quote:
            if ch == quote:
                quote = ""
            elif ch in _CSS_BAD_STRING:
                return i, False
            elif markup_ends_a_string and ch in _CSS_IMAGE_SET_MARKUP:
                return i, False
        elif ch in "'\"":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i, True
        elif ch in _CSS_IMAGE_SET_STOP:
            return i, False
        i += 1
    return end, False


def css_image_set_args(text):
    """Every `image-set(...)` argument list, read with a depth counter rather than a regex.

    A `[^)]*` capture stopped at the FIRST `)`, which in real CSS is the `)` of a nested
    `url(...)`/`type(...)` or a literal `)` inside a quoted candidate - so
    `image-set(url("a.png") 1x, "//evil/x.png" 2x)` hid the candidate a 2x browser fetches.

    A list that never CLOSES is re-read with markup as a hard boundary, even inside a quote: the
    open quote is then almost certainly the one ending a `style` attribute rather than a CSS
    string, and reading on would swallow the rest of the document and report an allowed `<a href>`
    further down as a remote CSS reference. A CLOSED list keeps the quote-faithful reading, so a
    legal `<` inside a candidate (`image-set("a<b.png" 1x, "//evil/x.png" 2x)`) cannot hide the
    candidate after it.
    """
    out, pos = [], 0
    while True:
        m = CSS_IMAGE_SET_OPEN_RE.search(text, pos)
        if not m:
            return out
        stop, closed = _css_image_set_scan(text, m.end(), False)
        if not closed:
            stop = _css_image_set_scan(text, m.end(), True)[0]
        out.append(text[m.end():stop])
        pos = stop + 1


def _css_image_set_candidates(args):
    """Split one `image-set(...)` argument list on its TOP-LEVEL commas.

    Quote-, paren- and escape-aware, so a comma inside `url("a,b.png")` or inside a quoted `data:`
    payload does not start a new candidate.
    """
    out, start, i, depth, quote, end = [], 0, 0, 0, "", len(args)
    while i < end:
        ch = args[i]
        if ch == "\\":
            i += 2
            continue
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "'\"":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            out.append(args[start:i])
            start = i + 1
        i += 1
    out.append(args[start:])
    return out


def _css_quoted_string_body(text):
    """The contents of the quoted string `text` STARTS with, honoring backslash escapes."""
    quote, i, end = text[0], 1, len(text)
    body = []
    while i < end:
        ch = text[i]
        if ch == "\\":
            body.append(text[i:i + 2])
            i += 2
            continue
        if ch == quote:
            break
        body.append(ch)
        i += 1
    return "".join(body)


def _css_image_set_candidate_is_network(candidate):
    """True when ONE `image-set()` candidate is a network reference."""
    text = candidate.strip(_CSS_WS_CHARS)
    if not text:
        return False
    func = _CSS_FUNC_START_RE.match(text)
    if func:
        # A well-formed function candidate belongs to another reading: `url(...)` is what
        # `CSS_NETWORK_URL_RE` reports, and `var(...)` is the recorded residual. One that never
        # CLOSES is a bad token whose declaration a browser drops, but it is read with the
        # unanchored pattern anyway - over-reporting is the safe direction for a malformed list.
        if _css_image_set_scan(text, func.end(), False)[1]:
            return False
        return bool(CSS_NETWORK_IMAGE_SET_RE.search(text))
    if text[0] in "'\"":
        text = _css_quoted_string_body(text)
    return bool(_CSS_ANCHORED_NETWORK_RE.match(text))


def css_network_image_set(text):
    """True when a BARE `image-set()` candidate in `text` is a network reference.

    Read candidate by candidate and ANCHORED at each candidate's start, the way
    `CSS_NETWORK_URL_RE` anchors after `url(`. A candidate that is itself a function token is left
    to the reading that owns it, so one declaration spelling both is reported once without any
    blanking pass - and a `data:` payload that merely CONTAINS a URL further in cannot be mistaken
    for egress.
    """
    for args in css_image_set_args(text or ""):
        for candidate in _css_image_set_candidates(args):
            if _css_image_set_candidate_is_network(candidate):
                return True
    return False

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
# below counts it: on Windows `file://host/x.js` is an SMB fetch off the machine. That arm is not
# written here - it comes from the SHARED `file_network_arm` above, which the CSS readers ask for
# too (issue #1230), so a widening cannot land on one side only. The reasoning behind each of its
# pieces is recorded here, because this is the predicate they were measured against. How many
# separators open that authority is NOT "two or more" - a real Chromium (checked, not assumed) reads
# two OR four-or-more as an authority, while THREE is the empty host of an ordinary local
# path (`file:///C:/x`), so `file:////evil.example/x.js` really does fetch and a `(?!/)` test alone
# called it local. That count is empirical because Chromium DEVIATES from the spec here, so reading
# the standard would have got it wrong: measured in Chromium 149, `file:////evil.example/x.js`
# parses to host `evil.example` and re-serializes as `file://evil.example/x.js`, where a
# spec-conformant parser takes the WHATWG file-host state's EMPTY host and leaves
# `//evil.example/x.js` as the path. That deviation is also PLATFORM-specific, and the arm is
# deliberately fail-CLOSED about it: the same engine build parses `file:////evil.example/x` to host
# `evil.example` on WINDOWS but to the EMPTY-host local `file:///evil.example/x` on LINUX (measured
# in the pinned CI container), and this arm counts it on both, because Windows is the platform where
# the UNC fetch exists.
# What the two counted arms are is the BASE-INDEPENDENT set, which is the reason to count exactly
# them rather than a claim that no other spelling ever reaches a host. Measured in the same Chromium
# 149 ON WINDOWS: parsed ABSOLUTE (no base), ZERO and ONE separator also give host
# `evil.example` (`file:evil.example/x.js`, `file:/evil.example/x.js`) - a Windows-only reading,
# since the same build parsed base-less on LINUX gives an EMPTY host for zero, one AND four
# separators, leaving only the two-separator form an authority there (measured in the pinned CI
# container). Resolved against the `file:` base an
# exported document actually has they INHERIT that base's host and are local
# (`file:///C:/docs/evil.example/x.js`), while the two counted arms give host `evil.example` from
# ANY base. So zero and one carry no authority of their own; they can only reach one the base
# already had, and a non-`file:` base is separately gated as a network `<base href>`.
# Issue #1229 asked whether any surface makes that inherited host reachable, and the answer is
# SETTLED here rather than left open: no, and the reason their leading run cannot open an authority
# is structural. `file:` IS a special scheme - so the backslash mapping in `normalize_url_value`
# applies to it exactly as to the others, and `file:\\evil.example/x` IS counted - but it does not
# take the special-authority-(ignore-)slashes states that collapse the slash-less `https:host/x`
# onto a host; the scheme state routes it to the FILE state, which resolves against the base and
# reads the leading run as PATH. Every surface that consumes this predicate resolves against that
# base: an attribute, a refresh target, and an `iframe srcdoc` (which inherits its parent's
# base). The CSS readers are on that list TOO, as of issue #1230: they are assembled from
# `CSS_NETWORK_START`, which carries this very arm, and a stylesheet resolves a reference against
# the same document base - so the exemption reasoned about here holds for them by the same argument,
# rather than by their having no `file:` arm to reach the question with (which is what it used to be).
# The refresh case was CAPTURED rather than reasoned about - a real Chromium
# navigating out of a `file:///C:/dir/report.html` document went to `file:///C:/dir/evil.example/x`,
# never the SMB share - and from a UNC base the value takes that document's OWN host, which it
# cannot choose, exactly as the plain relative `evil.example/x` beside it does.
# Two contexts were measured rather than assumed, so the answer does not rest on the one case. A
# `<base href>` onto a non-`file:` base does rebase them onto a host the value names, and that is
# closed one layer up and unconditionally - a `<base href>` is held to the stricter
# `offline_is_non_local_ref` in EVERY mode and the offline strip removes it (issue #924) - so the
# compound needs an element this gate already rejects. A document whose AMBIENT base is not a
# `file:` one - a report SERVED over http/https - does resolve them to a host the value names, and
# that case rests on the ENGINE rather than on this arm: a `file:` load from an http(s) document is
# refused outright (`Not allowed to load local resource`), measured for the already-counted
# two-separator spelling equally, so counting the short runs would buy nothing there while costing
# the false positive of calling an authored `file:notes.html` a beacon. Both are Chromium
# measurements, like the closed scheme set below, and nothing is claimed for other engines.
# The exemption is scoped to the LEADING run and no further: a zero- or one-separator value whose
# PATH canonicalizes onto the four-separator form is still counted by `_FILE_DOTDOT_SEGMENT` and
# `_FILE_EMPTY_SEGMENT` (`file:/..//x.js` and `file:a//b.png` are corpus rows, both NETWORK). Those
# two arms are base-LESS canonicalization arguments and stay a deliberate over-detection in the safe
# direction; nothing here narrows them. Read the `localhost` and drive-letter exclusions below with
# that in mind: they are lookaheads INSIDE the authority arm, so they exclude a local AUTHORITY, not
# a value. A slash-poor spelling carrying an empty path segment reaches the empty-segment arm
# REGARDLESS of them - `file:localhost//x.js` and `file:C://x.js` are corpus rows, both NETWORK -
# and a slash-poor `file:localhost/x.js` is local because its leading run is PATH, not because the
# `localhost` lookahead fired on it.
# The whole measurement is re-run on every CI pass by the `CMH-VAL-08: a real Chromium resolves a
# slash-poor file: reference against the document's own base` spec, which compares the engine to
# this predicate's own verdicts, so an engine that ever changed its mind reds a test instead of
# silently invalidating this paragraph.
# Two host spellings that stay on the machine are excluded
# whatever the separator count of the AUTHORITY arm they appear in - and only there, since
# both are lookaheads inside that arm, so the `..` and empty-segment arms still count a value
# carrying one (see above):
# `localhost` - in every PERCENT-ENCODED and CASE spelling, see `_PCT_LOCALHOST` above for
# what that does and does not cover - and a Windows DRIVE LETTER, which the
# file-host state turns into a path rather than a host, because reporting either would reject an
# offline file with no egress at all - and make the exporter delete the author's local reference.
# The percent-tolerance is right for the FOUR-or-more-slash arm too: that arm's long run opens a real
# HOST to Chromium (the same deviation above), and a real Chromium was measured percent-decoding it
# before comparing, so `file:////local%68ost/x.js` parses to host `localhost` - the same excluded
# host that `file:////localhost/x.js` reaches.
# A TRAILING DOT is deliberately outside that exclusion, and that is the parser-faithful reading
# rather than an accepted over-detection: the file-host state special-cases the exact string
# `localhost`, and `localhost.` is not it, so `file://localhost./x` keeps a NON-EMPTY host (checked:
# the href stays `file://localhost./x`) and on Windows resolves to the SMB path `\\localhost.\x`.
# That is the same call the scheme-relative `\\localhost\C$\x` gets - an authority-bearing share is
# egress even to the loopback - so excluding it would be the inconsistency. Percent-encoding cannot
# reach the DRIVE-LETTER exclusion the way it reaches this one: the drive test reads the raw buffer
# the file-host state reads, and `%3A`/`%7C` decode to forbidden host code points that fail to parse.
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
# The http/https arm reads the slash run rather than counting it, so the scheme-only
# `https:host/x.js` and the single-slash `https:/host/x.js` - which the special-authority states
# resolve to the same host as `https://host/x.js` - are network URLs too, and one host character is
# required so an empty authority stays local. That widening landed with the CSS gates and the
# exporter's CSS strips it mirrors, both sides at once (issue #961); see the CMH-VAL-08 spec row.
# The scheme set is CLOSED at http/https, scheme-relative and `file:`, and that is EVIDENCE rather
# than an omission: from a `file:` document a current Chromium produces no connection at all for
# `ftp:`, `ws:`, `wss:`, `filesystem:` or a custom scheme with no registered handler, through any
# automatic subresource channel this gate reads (`net::ERR_UNKNOWN_URL_SCHEME`; Chromium removed FTP in
# 88, and `filesystem:` is refused as a local resource), while the http and https controls in the
# same document connect. Reporting one would therefore reject a file with no egress at all and make
# the exporter delete the author's reference - the same over-detection trade the `localhost` and
# drive-letter exclusions make. Four limits are recorded rather than implied, because each is a
# channel this predicate cannot be the layer for: a SCRIPTED `WebSocket` does reach the network in
# `ws:`/`wss:`, but no attribute carries it and the export's `connect-src 'none'` closes it
# (measured with and without the policy); a REGISTERED protocol handler turns a navigation into a
# fetch of the handler's own https template - one cannot be registered from a `file:` document, so
# the measured case is the UNREGISTERED one and a reader's pre-installed OS handler stays
# unmeasured; a
# `preconnect`/`dns-prefetch` leak is a name resolution rather than a connection (#1076); and the
# measurement is Chromium's - `ws:`/`wss:`/`filesystem:` were not observed as subresource-fetchable
# in the engine under test and nothing is claimed for others, while FTP removal is an
# implementation choice, so that is the row to re-measure. What travels with an already-exported
# file is the export's own zero-network CSP, which refuses these subresources whatever a future
# engine decides; this predicate is what keeps a NEW export clean without leaning on it. The
# probe in `tests/49-offline-export.spec.js` re-runs the measurement on every CI pass with a
# per-channel control, and the shared corpus in `tests/test_vendored_libs.py` holds this predicate
# and the exporter's to the same verdicts, so a deliberate widening later has to move both sides at
# once.
NETWORK_URL_RE = re.compile(
    r"(?:(?:https?:/*|/{2,})[^/?#]"
    r"|" + file_network_arm() + r")",
    re.IGNORECASE | re.ASCII)

# Every character a URL parser removes from its input before it parses: leading and trailing C0
# controls or spaces (U+0000-U+0020, the shared `url_ends_trim`), and ASCII tab, LF and CR ANYWHERE
# inside the value.
_URL_INNER_REMOVE_RE = re.compile(r"[\t\n\r]")


def normalize_url_value(value):
    """A reference as the URL PARSER sees it, so a literal test reads what a browser will fetch.

    Three cleanups, all of them the parser's own: strip leading and trailing C0-or-space (through
    the shared `url_ends_trim`, the one definition of that trim), remove ASCII tab/LF/CR from
    anywhere, and map every backslash onto a slash (for a special scheme the parser's relative and
    authority-slash states treat the two alike, so `https:/\\host/x.js` and `\\\\host/x.js` both
    open an authority). Mirrored byte-for-byte in the exporter's `_offlineNormalizeUrlValue`;
    `tests/test_vendored_libs.py` pins the pair through the real JS engine.
    """
    return url_ends_trim(_URL_INNER_REMOVE_RE.sub("", str(value or ""))).replace("\\", "/")


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
# `_OFFLINE_SRCSET_WS` / `_offlineSrcsetHasNetwork`.
_SRCSET_WS = "\t\n\f\r "


def srcset_candidate_urls(value):
    """Every string in a `srcset` a browser could load, tokenized the way HTML's parser does.

    This is HTML's own srcset candidate state machine, not an approximation of it: skip a run of
    ASCII whitespace and commas, collect a run of NON-whitespace as the URL, and then either strip
    that URL's trailing commas (which end the candidate with no descriptors at all) or run the
    descriptor tokenizer forward to the first comma OUTSIDE parentheses.

    It replaced a UNION of two approximations - a comma split and a whitespace split - that was
    deliberately over-inclusive on the reasoning that a descriptor (`1x`, `320w`) can never match
    the network predicate. A `data:` URL breaks that reasoning, because a comma is legal INSIDE one
    (it separates the media type from the data): `data:text/plain,https://example.com/payload 1x`
    was comma-split into `data:text/plain` and `https://example.com/payload`, and the second half
    matched. Fail-CLOSED (an over-strip and an over-rejection, never a missed load), but it made an
    offline export clear a `srcset` that reaches no network and the strict validator reject a
    document with no egress (issue #1084). Both cases the union existed for survive: a comma inside
    the URL run belongs to the URL (`srcset="https://,host/x.png 1x"` really does request
    `https://,host/x.png`), and a comma that follows the DESCRIPTORS still separates two candidates
    even with no space around it (`local.png 1x,https://host/x.png 2x` is two). A comma that abuts
    the URL run is NOT a separator: `a.png,b.png` is the single relative reference `a.png,b.png`,
    which a browser resolves against the document and never fetches off-host. All three measured in
    a real Chromium.

    One step of HTML's algorithm is deliberately NOT taken: descriptor VALIDATION. HTML appends a
    candidate only once its descriptors parse cleanly, so it DISCARDS `https://host/x.png 1x 2x`
    (repeated `x`) and never fetches it; both sides here keep the candidate and report the load.
    That is the fail-CLOSED direction, and the alternative is a second, larger state machine (the
    `w`/`x`/`h`/`d` grammar and its duplicate rules) to hold identical across two languages - the
    drift this pair exists to prevent - where a mistake would cost a MISSED load rather than an
    over-strip. Mirrored in the exporter's `_offlineSrcsetCandidateUrls`.
    """
    text = str(value or "")
    urls = []
    pos = 0
    end = len(text)
    while pos < end:
        while pos < end and (text[pos] in _SRCSET_WS or text[pos] == ","):
            pos += 1
        start = pos
        while pos < end and text[pos] not in _SRCSET_WS:
            pos += 1
        url = text[start:pos]
        if url.endswith(","):
            url = url.rstrip(",")
            if url:
                urls.append(url)
            continue
        if url:
            urls.append(url)
        # Descriptor tokenizer: everything up to the first comma outside parentheses belongs to
        # this candidate's descriptors, so a comma parked inside `(...)` is not a separator.
        in_parens = False
        while pos < end:
            c = text[pos]
            pos += 1
            if in_parens:
                if c == ")":
                    in_parens = False
            elif c == ",":
                break
            elif c == "(":
                in_parens = True
    return urls


def srcset_has_network(value):
    """True when any candidate in a `srcset` names a network resource."""
    return any(is_network_url(url) for url in srcset_candidate_urls(value))


# Every attribute through which a <script> can LOAD its code. An SVG <script> uses none of the
# HTML `src` spelling: it loads through SVG2 `href` or the legacy `xlink:href`, and its body is
# empty, so a `src`-only check saw nothing at all. Kept beside the predicate above because the
# offline strip carries the same list as `_OFFLINE_SCRIPT_LOAD_ATTRS`, and
# `test_the_python_and_js_script_load_attributes_agree` pins the two together. WHICH scripts really
# load through `src` is a further question, decided by whether a browser REQUESTS the resource
# (`script_src_fetches`, pinned to the exporter's `_offlineScriptSrcIsFetched`); the two SVG spellings stay
# unconditional, since this tokenizer has no namespace to consult.
SCRIPT_LOAD_ATTRS = ("src", "href", "xlink:href")


# The SVG PRESENTATION ATTRIBUTES whose value is a CSS `<url>` that a browser FETCHES on open
# (issue #1186). They are not (tag, attribute) URL pairs like `src` or `poster` - the value is a CSS
# declaration value, so the CSS `url()` reading is what reads them - and they are not part of a
# stylesheet either, so neither the element rules nor the `style=` / `<style>` CSS reads saw them:
# `<rect mask="url(https://evil.example/x.svg#m)">` validated STRICT-CLEAN, was given the
# `commentable-html-validated` stamp, and fetched the moment a recipient opened it. In SHAREABLE
# mode there is no CSP behind the gate, so this reading is the only layer.
#
# WHICH attributes are in scope is decided by MEASUREMENT, not by the list of properties the specs
# say accept a `<url>` (`tests/62-deck-regressions.spec.js`, Chromium 149, every request routed and
# aborted, each probe written in the shape a browser actually HONOURS and the page settled to
# network-idle):
#   REQUESTED  clip-path, mask, fill, stroke, marker-start, marker-mid, marker-end, cursor
#   not        filter, mask-image, mask-border-source, the `marker` shorthand, color-profile
# The probe SHAPE decides the answer, which is why the spec writes one per attribute rather than one
# for all: `cursor` needs a fallback keyword (`url(...), auto`) to be a valid declaration at all, and
# measured as INERT while it was probed without one - a `<rect cursor="url(https://host/x.cur),
# auto">` really is fetched, and `getComputedStyle` shows the value honoured, so the bare-url probe
# was measuring its own invalidity.
# `filter` is carried anyway, and that is the one deliberate over-detection here: Chromium REMOVED
# external filter references, so its negative is an engine decision rather than a structural one
# (other engines have honoured them), and a rule that fires only on a NETWORK url costs an author
# with a local `url(#f)` nothing. The remaining negatives are NOT carried, for the reason `lowsrc`
# left the deck gate (#1179): a rule no engine needs is a rule nobody can retire later. The
# measurement is a tripwire - if an engine ever revives one, that spec goes red and this list, the
# offline strip's list, and the spec row move together.
SVG_URL_PRESENTATION_ATTRS = ("clip-path", "cursor", "fill", "filter", "marker-end", "marker-mid",
                              "marker-start", "mask", "stroke")

# The presentation attributes that take an IMAGE, so a bare remote string inside `image-set(...)` -
# which carries no `url()` wrapper and so is invisible to the pattern above - is fetched from one.
# Measured separately and deliberately NARROWER than the list above, but it is not `mask` alone: a
# `cursor` takes an image too, and `cursor="image-set('https://host/x.cur' 1x), auto"` really is
# requested (round-2 review panel, 4 of 8 ducks - the first cut of this list said "only `mask`", and
# that reasoning, not an oversight, is what left the hole). `fill`, `stroke`, `clip-path` and the
# markers take a paint server or a shape reference and request nothing from a bare candidate, so
# reading `image-set()` on them would REJECT a document that reaches no network at all - the
# false-positive direction this gate cannot afford. Like the `style=` `image-set()` reading it
# mirrors, this is SHAREABLE-only (CMH-VAL-08): offline has the zero-network CSP behind it (proven
# live - the export's `img-src data:` blocks the fetch, `tests/49-offline-export.spec.js`), and
# widening the offline gate alone would reject a file `_offlineCssNoNetwork` just produced.
SVG_IMAGE_SET_PRESENTATION_ATTRS = ("cursor", "mask")


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
# The SINK side keeps a residual of the same shape, and it caps what tightening the URL literal
# further is worth: a UnicodeEscapeSequence that decodes to a legal identifier character may appear
# inside an IdentifierName and names exactly the same property, so an escape in ANY identifier of
# the chain - a prefix name, the sink name, or the property name (`locatio\u006E`, `\u006Fpen`,
# `hre\u0066`, either the `\u006E` or the `\u{6E}` form, at any character position including the
# first) - is invisible to the anchor and tails below, which match those names as literal text. The
# ONE shape that survives the escape is a prefix name separated from its `.` (or `?.`) by
# WHITESPACE: the walk skips that run and finds a legal boundary at it, so the literal remainder of
# the chain qualifies on its own and `windo\u0077 . top.location` is caught where the tight
# `windo\u0077.top.location` is not. That is incidental rather than a defence - the same whitespace
# makes an arbitrary `zzz . location` match - and the corpus pins it beside a non-escaped control.
# The same literal matching cuts the other way in
# `OFFLINE_LOCAL_LOCATION_RE`, and that direction costs an author content rather than letting a
# beacon out: an ESCAPED local `location` declaration does not register as a shadow, so a script
# that navigates nothing is rejected whole. Both are DECIDED, not overlooked. Recognizing each name
# as literal-or-escaped per character is possible without backtracking, but it turns a plain literal
# anchor search into a per-position automaton over every inline script - the exporter's copy of this
# scan runs over the vendored payload's inflated megabytes too - to close a channel computed access
# (`location["href"]`) already leaves open for a shorter edit. Documented in the CMH-OFFLINE-05
# residual and pinned in BOTH engines, in both directions and against their plain-spelled controls,
# by `test_the_escaped_identifier_sink_is_the_documented_residual_in_both_engines`.
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
# An IDENTIFIER character, spelled as the complement of the BOUNDARY characters. It decides where a
# prefix chain may start, so a character it gets wrong in the identifier direction turns a purely
# local binding whose name merely ENDS in `location` (`<non-ASCII letter>location.href = <url>`)
# into the document's own sink and deletes an author's whole script. The class was ASCII-only and
# did exactly that. It cannot be fixed by reaching for `\w`, which is ASCII in JS and Unicode-aware
# in Python - the two engines would then disagree on the very inputs this is about - and no
# Unicode property escape exists in Python's `re`, so the complement is spelled out instead: every
# ASCII character that cannot appear in an identifier EXCEPT `.`, plus the exact whitespace set the
# scan uses. Everything else, ASCII or not, is an identifier character. The `.` exception is not an
# oversight and predates this spelling: a member-expression dot must CONTINUE the chain, so that
# `cfg.location.href = <url>` reads as some other object's `location` and stays benign - treating it
# as a boundary would delete that script. Three more consequences are deliberate.
# Non-ASCII WHITESPACE stays a boundary (a sink one exotic space into the script is still seen),
# which is why the whitespace set is carved back out rather than the class being "any non-ASCII".
# And a non-ASCII character that is NOT a legal IdentifierPart - an em dash, a curly quote - now
# reads as one, so a sink written behind one is not matched; that is the same direction as the rest
# of CMH-OFFLINE-05's residual (an author who writes it has cheaper bypasses already) and it is the
# safe direction, since every widening here can only ever remove matches, never invent one.
# It also settles the ASTRAL case identically in both engines without a second test: a supplementary
# code point is a surrogate PAIR to `charAt` and a single code point to Python, and neither a
# surrogate nor a supplementary code point is in the boundary list, so both read it as identifier.
# The ASCII-only CASE FOLD elsewhere in the scan is untouched and must stay that way - it exists so
# Python's Unicode folding cannot fold a non-ASCII letter ONTO `location` (the dotless i, the long
# s), which is the OPPOSITE failure and is pinned by its own benign samples.
OFFLINE_NAV_IDENT_RE = re.compile(r"[^\u0000-\u0023\u0025-\u002d\u002f\u003a-\u0040\u005b-\u005e\u0060\u007b-\u007f\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]", re.ASCII)
OFFLINE_NAV_STATEMENT_RE = re.compile(r"[;})>\n\r\u2028\u2029]", re.ASCII)
OFFLINE_NAV_LINE_BREAK_RE = re.compile(r"[\n\r\u2028\u2029]", re.ASCII)
OFFLINE_NAV_PREFIX_NAMES = ("window", "self", "top", "parent", "globalThis", "document", "frames")


# The PREFIXED-only sinks (`window.location...`, `top.open(...)`) are selected with the
# `prefixed_only` argument below: the prefix chain is mandatory there, and the bare
# statement-position `location =` alternative is dropped. Used when the script declares its own
# `location`, further down.

# A LOCAL binding named `location`, decided by TOKENIZING the declaration rather than by matching
# a character window over raw source. It answers one question - does this script declare its OWN
# `location`? - and a script that does is measured against the PREFIXED sinks only, so a wrong
# answer costs something in either direction.
# WHAT THIS ARM IS. It is a FALSE-POSITIVE REDUCER, not a security boundary, and that decision sets
# the bar for everything below. An author who wants an unprefixed sink ignored has the aliasing
# bypass the CMH-OFFLINE-05 residual already accepts (`const a = location; a.href = <url>`), which
# is cheaper than any spelling here, so a shape that WRONGLY reports a shadow gives a hostile author
# nothing new. A shape that wrongly reports NO shadow, on the other hand, makes the exporter delete
# a script that navigates nothing and makes `--strict` reject a clean document - real, silent
# content loss. So the over-rejection direction is closed hard, and the cheap under-rejection shapes
# (a `location` in a comment, a string, a parameter default, or a property key renamed away) are
# closed too because tokenizing gets them for free; what remains is stated in the residual rather
# than papered over.
# WHY NOT A REGEX. The window this replaced (`[{\[](?:[^}\]]{0,399}[^}\]A-Za-z0-9_$])?location` and
# a parameter-list twin) was wrong both ways at once. A MENTION disarmed it - `function f(a /*
# location */)`, `function f(q = location)`, `const {location: renamed}` - and a real binding it
# could not see was MISSED: an arrow parameter, a method or `constructor` shorthand, a generator, a
# nested pattern or a default that spends a `}`, `]` or `)` inside the window, a comment between
# `catch (` and the name, a non-ASCII function name, and any binding more than 400 characters into
# the list. Neither could be fixed inside the window: an allowlist of boundary characters rejects
# the legitimate `const {href: location}` rename, and widening the identifier class to non-ASCII
# breaks a real `var location<NBSP>= 1`, because NBSP is JS whitespace and sits in that range.
# The scanner below is one LEFT-TO-RIGHT pass with no backtracking anywhere: each character is
# classified once, each comment, string, template and regex literal is skipped once, and the only
# look-ahead is a peek for the token that follows a `location` or a `)` - which scans the run after
# that token and nothing else, so the runs peeked at are disjoint and the pass stays linear (#973,
# #1045). Every helper is mirrored, name for name, by `_offlineShadow*` in
# assets/js/68-export-offline.js, and `test_the_python_and_js_shadow_scanners_are_mirrored` plus the
# node run of the exporter's own source over the shadow corpus pin the two together.
OFFLINE_SHADOW_IDENT_ASCII_RE = re.compile(r"[A-Za-z0-9_$]", re.ASCII)
# `import` and `using` are here because `import {location} from "./x"` and `using location = res`
# bind the name exactly as `const` does. Neither is a reserved word in every position, so a
# declaration is only recognized when the keyword is FOLLOWED by the name or pattern it binds
# (`_offline_shadow_decl_starts`), which is what keeps `import(...)`, `import.meta`, `using(...)`
# and a `{const: 1}` property key out of binding mode.
OFFLINE_SHADOW_DECL_KEYWORDS = ("var", "let", "const", "import", "using")
# Words that can head a parenthesized group which is NOT a parameter list, so `IDENT ( ... ) {` may
# not be read as a method definition after them: `if (location) {` declares nothing. `function` and
# `catch` are in the list because their parameter list is recognized directly, by keyword.
OFFLINE_SHADOW_NON_METHOD = ("if", "while", "for", "switch", "with", "do", "else", "return",
                             "typeof", "void", "delete", "new", "in", "of", "instanceof", "case",
                             "throw", "yield", "await", "function", "catch", "try", "finally",
                             "var", "let", "const", "class", "import", "export", "default",
                             "break", "continue", "debugger", "this", "super", "null", "true",
                             "false")
# Words after which a `/` begins a REGULAR EXPRESSION rather than a division. Getting this wrong
# either way only mis-skips a literal, but skipping a division as a regex can swallow a real
# binding, so the list is the conservative one: after any other identifier, `/` divides.
OFFLINE_SHADOW_REGEX_PRECEDERS = ("return", "typeof", "instanceof", "in", "of", "new", "delete",
                                  "void", "throw", "case", "do", "else", "yield", "await")
# The characters that, immediately before an `=`, make it a comparison or a compound assignment
# rather than the plain `=` that opens a default-value expression.
OFFLINE_SHADOW_COMPOUND_OPS = ("=", "!", "<", ">", "+", "-", "*", "/", "%", "&", "|", "^")
# The deepest bracket nesting the frame stack tracks. Beyond it the scan keeps COUNTING depth but
# stops allocating, so a hostile script that is nothing but openers costs constant memory instead of
# one object per character - 2 million of them measured 168 MB of heap in node, and the export runs
# in the reviewer's own tab. Real nesting is two orders of magnitude below this.
OFFLINE_SHADOW_MAX_DEPTH = 1000


def _offline_shadow_ident_char(ch):
    """True for a character that can appear inside an identifier, mirroring `_offlineShadowIdentChar`.

    Non-ASCII characters count, so `\u03c0location` and `location\u03c0` are ordinary names that
    merely CONTAIN `location` rather than boundaries around it - except for the non-ASCII JS
    WHITESPACE (NBSP and friends), which is why the class is a test rather than a range.
    """
    if OFFLINE_SHADOW_IDENT_ASCII_RE.match(ch):
        return True
    return ord(ch) >= 128 and not OFFLINE_NAV_WS_RE.match(ch)


def _offline_shadow_line_end(src, i):
    """The index of the next line terminator at or after `i`, or the end of the input."""
    n = len(src)
    while i < n and not OFFLINE_NAV_LINE_BREAK_RE.match(src, i):
        i += 1
    return i


# An HTML comment opener is a line comment in a classic script (Annex B), so text after it is not
# code. It is ASSEMBLED rather than written out to mirror the exporter, whose copy of this file is
# served inside a `<script>` element where a literal one flips the HTML parser into its escaped
# state.
OFFLINE_SHADOW_HTML_COMMENT = "<" + "!--"


def _offline_shadow_skip_comment(src, i):
    """The index after the comment starting at `i`, or -1 when `i` starts no comment."""
    if src.startswith("//", i) or src.startswith(OFFLINE_SHADOW_HTML_COMMENT, i):
        return _offline_shadow_line_end(src, i + 2)
    if src.startswith("/*", i):
        at = src.find("*/", i + 2)
        return len(src) if at < 0 else at + 2
    return -1


def _offline_shadow_next_word(src, i):
    """The identifier that follows `i`, ASCII-folded, or "" when the next token is not one."""
    n = len(src)
    while i < n:
        ch = src[i]
        if OFFLINE_NAV_WS_RE.match(ch):
            i += 1
            continue
        skipped = _offline_shadow_skip_comment(src, i)
        if skipped >= 0:
            i = skipped
            continue
        if not _offline_shadow_ident_char(ch):
            return ""
        j = i + 1
        while j < n and _offline_shadow_ident_char(src[j]):
            j += 1
        return _offline_nav_ascii_lower(src[i:j])
    return ""


def _offline_shadow_next_sig(src, i, same_line=False):
    """The next significant token from `i`: `=>`, a single character, or "" at end of input.

    `same_line` stops at a line terminator and answers "", for the two decisions where the grammar
    forbids one: no LineTerminator may precede `=>`, and a `{` on the next line after a call is a
    separate block statement rather than a method body (ASI puts a `;` between them).
    """
    n = len(src)
    while i < n:
        ch = src[i]
        if OFFLINE_NAV_WS_RE.match(ch):
            if same_line and OFFLINE_NAV_LINE_BREAK_RE.match(ch):
                return ""
            i += 1
            continue
        skipped = _offline_shadow_skip_comment(src, i)
        if skipped >= 0:
            if same_line and OFFLINE_NAV_LINE_BREAK_RE.search(src, i, skipped):
                return ""
            i = skipped
            continue
        return "=>" if src.startswith("=>", i) else ch
    return ""


def _offline_shadow_skip_quoted(src, i):
    """The index after the `'`/`"` literal opened at `i`, or -1 when it does not close.

    Such a literal cannot carry a raw line terminator, so a quote with no partner on its own line
    is punctuation rather than the start of a literal that swallows the rest of the script - and
    swallowing it would hide a real binding, the direction that deletes an author's script. A
    LineContinuation is the exception the check must not trip over: a backslash before CRLF escapes
    BOTH characters, and reading only the CR left the LF looking like a bare line terminator, which
    ended the literal and handed its text to the tokenizer as code.
    """
    quote = src[i]
    n = len(src)
    j = i + 1
    while j < n:
        ch = src[j]
        if ch == "\\":
            j += 3 if src.startswith("\r\n", j + 1) else 2
            continue
        if ch == quote:
            return j + 1
        if OFFLINE_NAV_LINE_BREAK_RE.match(ch):
            return -1
        j += 1
    return -1


def _offline_shadow_skip_template(src, i):
    """Scan a template literal from `i` (its backtick, or the `}` that resumes it).

    Returns `(index, opened)` where `opened` says a `${` substitution was entered, so the caller
    reads what follows as CODE - an arrow parameter inside one binds a name like any other.
    """
    n = len(src)
    j = i + 1
    while j < n:
        ch = src[j]
        if ch == "\\":
            j += 3 if src.startswith("\r\n", j + 1) else 2
            continue
        if ch == "`":
            return j + 1, False
        if ch == "$" and j + 1 < n and src[j + 1] == "{":
            return j + 2, True
        j += 1
    return n, False


def _offline_shadow_skip_regex(src, i):
    """The index after the regex literal opened at `i`, or -1 when it does not close on its line."""
    n = len(src)
    j = i + 1
    in_class = False
    while j < n:
        ch = src[j]
        if ch == "\\":
            j += 2
            continue
        if OFFLINE_NAV_LINE_BREAK_RE.match(ch):
            return -1
        if in_class:
            if ch == "]":
                in_class = False
        elif ch == "[":
            in_class = True
        elif ch == "/":
            j += 1
            while j < n and _offline_shadow_ident_char(src[j]):
                j += 1
            return j
        j += 1
    return -1


def _offline_shadow_regex_ok(prev, prev_word):
    """True when a `/` at this point begins a regex literal rather than a division."""
    if prev == "w":
        return prev_word in OFFLINE_SHADOW_REGEX_PRECEDERS
    return prev != ")" and prev != "]"


def _offline_shadow_decl_starts(after):
    """True when `after` is a token a DECLARATION can legally continue with.

    A declaration keyword is followed by the name or pattern it binds, so anything else means the
    word is not opening a declaration at all: `import(...)` and `import.meta` are expressions,
    `import "./x"` and `using(...)` bind nothing, and `{const: 1}` or `{let: 1}` is a property key.
    Every one of those used to put the enclosing frame into binding mode and report a shadow for
    the next `location` it saw, which suppressed a real sink.
    """
    if after == "{" or after == "[" or after == "*":
        return True
    return len(after) == 1 and _offline_shadow_ident_char(after)


def _offline_shadow_frame(ch, binding, decl, key, opener, template):
    return {"ch": ch, "binding": binding, "decl": decl, "key": key, "named": False,
            "in_default": False, "candidate": False, "opener": opener, "template": template}


def offline_local_location_shadow(src):
    """True when the script declares its OWN binding named `location`.

    Mirrors `_offlineLocalLocationShadow` in assets/js/68-export-offline.js. A frame is pushed per
    bracket; a frame is a BINDING context when it is a declaration list (`var`/`let`/`const`/
    `import`/`using`), a parameter list (`function`, a generator, `catch`, a method or
    `constructor` shorthand, an arrow) or a destructuring pattern nested inside one, and an
    EXPRESSION context otherwise. Inside a binding context a name is a binding unless it is a
    property KEY (`{location: renamed}`), a computed key (`{[location]: renamed}`) or sits in a
    default-value expression (`function f(q = location)`) - the shapes that used to disarm the rule
    by merely mentioning the name.
    """
    src = src or ""
    n = len(src)
    stack = [_offline_shadow_frame("", False, False, False, "", False)]
    over_depth = 0
    pending_params = False
    expect_name = False
    pending_break = False
    prev = ""
    prev_word = ""
    no_regex_before = 0
    i = 0
    while i < n:
        frame = stack[-1]
        ch = src[i]
        if OFFLINE_NAV_WS_RE.match(ch):
            if OFFLINE_NAV_LINE_BREAK_RE.match(ch):
                pending_break = True
            i += 1
            continue
        if ch == "/" or ch == "<":
            skipped = _offline_shadow_skip_comment(src, i)
            if skipped >= 0:
                # A comment can carry the line break that ends a declaration, so it feeds the same
                # ASI flag rather than being skipped silently.
                if OFFLINE_NAV_LINE_BREAK_RE.search(src, i, skipped):
                    pending_break = True
                i = skipped
                continue
        # ASI ends a declaration at a line break once it has bound a name, unless the next token
        # continues the list. Without this, `let x` on its own line put every following `location`
        # in binding position and reported a shadow the source never declared. The decision is made
        # HERE, at the first token after the break, rather than by peeking from the break: peeking
        # re-scanned the whole run of trivia at every newline in it, which is quadratic (20,000
        # newlines cost 57s in Python and 4.5s in node).
        if pending_break:
            pending_break = False
            if frame["decl"] and frame["named"] and not frame["in_default"]:
                if not (ch == "," or (ch == "=" and not src.startswith("=>", i))):
                    frame["binding"] = False
                    frame["decl"] = False
                    frame["named"] = False
        if ch == "/":
            if i >= no_regex_before and _offline_shadow_regex_ok(prev, prev_word):
                end = _offline_shadow_skip_regex(src, i)
                if end >= 0:
                    i = end
                    prev, prev_word = "]", ""
                    continue
                # A literal that never closes would be re-scanned from every later `/` on the same
                # line, which is quadratic; one failed scan settles the whole line instead.
                no_regex_before = _offline_shadow_line_end(src, i)
            prev, prev_word = "/", ""
            i += 1
            continue
        if ch == "'" or ch == '"':
            end = _offline_shadow_skip_quoted(src, i)
            if end >= 0:
                i = end
                prev, prev_word = "]", ""
                continue
            prev, prev_word = ch, ""
            i += 1
            continue
        if ch == "`":
            i, opened = _offline_shadow_skip_template(src, i)
            if opened:
                if len(stack) < OFFLINE_SHADOW_MAX_DEPTH:
                    stack.append(_offline_shadow_frame("$", False, False, False, "", True))
                else:
                    over_depth += 1
            prev, prev_word = "]", ""
            continue
        if _offline_shadow_ident_char(ch):
            j = i + 1
            while j < n and _offline_shadow_ident_char(src[j]):
                j += 1
            word = _offline_nav_ascii_lower(src[i:j])
            member = prev == "."
            i = j
            prev, prev_word = "w", "" if member else word
            if member:
                continue
            if expect_name:
                # The name a `function` or `class` declaration binds.
                expect_name = False
                if word == "location":
                    return True
                continue
            if word in OFFLINE_SHADOW_DECL_KEYWORDS:
                if _offline_shadow_decl_starts(_offline_shadow_next_sig(src, i)):
                    frame["binding"] = True
                    frame["decl"] = True
                    frame["named"] = False
                    frame["in_default"] = False
                continue
            if word == "function" or word == "class" or word == "catch":
                # Gated the same way a declaration keyword is: `{class: location}` and
                # `[{catch: 1}, f(location)]` are property KEYS, and letting them arm the
                # name/parameter-list state made an unrelated later call look like a declaration.
                if _offline_shadow_next_sig(src, i) != ":":
                    expect_name = word != "catch"
                    pending_params = word != "class"
                continue
            if ((word == "of" or word == "in") and frame["ch"] == "(" and frame["binding"]):
                # The head of `for (const x of EXPR)` turns to an EXPRESSION after `of`/`in`,
                # exactly as a declarator does after `=`. Without this, the ordinary
                # `for (const [k, v] of Object.entries({location, ...}))` idiom read `location` as
                # a nested pattern and reported a shadow nothing declared.
                frame["in_default"] = True
                continue
            if frame["binding"] and not frame["in_default"]:
                frame["named"] = True
            if word != "location":
                continue
            if _offline_shadow_next_sig(src, i) in (":", ".", "(", "["):
                # A property KEY, a member access, a call or an index - a declarator name is never
                # followed by any of them, so none of these is the binding the arm looks for.
                continue
            if _offline_shadow_next_word(src, i) == "as":
                # `import {location as renamed}` binds `renamed`; the name before `as` is the
                # imported one, exactly like the key half of `{location: renamed}`.
                continue
            if frame["binding"] and not frame["in_default"]:
                return True
            # The arrow test comes BEFORE the default-value skip: `let f = location => {}` reads
            # `location` inside an initializer, and it is still that arrow's parameter.
            if _offline_shadow_next_sig(src, i, True) == "=>":
                return True
            if frame["in_default"]:
                continue
            frame["candidate"] = True
            continue
        if ch == "(" or ch == "[" or ch == "{":
            params = pending_params and ch == "("
            # A `[` where an object pattern expects a KEY is a computed key, not a nested pattern:
            # `const {[location]: x}` reads the outer binding rather than declaring one.
            computed_key = (ch == "[" and frame["ch"] == "{"
                            and (prev == "{" or prev == ","))
            binding = params or (frame["binding"] and not frame["in_default"]
                                 and not computed_key)
            # A parameter list carries no opener, so the method rule below cannot fire on the
            # function's own name: `function f(a = location) {}` declares no `location`. A `]` or a
            # closing quote IS kept, because a computed or quoted method name ends in one.
            opener = "" if params or ch != "(" else ("]" if prev == "]" else prev_word)
            if len(stack) < OFFLINE_SHADOW_MAX_DEPTH:
                stack.append(_offline_shadow_frame(ch, binding, False, computed_key, opener, False))
            else:
                over_depth += 1
            pending_params = False
            expect_name = False
            prev, prev_word = ch, ""
            i += 1
            continue
        if ch == ")" or ch == "]" or ch == "}":
            if over_depth > 0:
                over_depth -= 1
            elif len(stack) > 1:
                done = stack.pop()
                parent = stack[-1]
                if done["template"] and ch == "}":
                    i, opened = _offline_shadow_skip_template(src, i)
                    if opened:
                        if len(stack) < OFFLINE_SHADOW_MAX_DEPTH:
                            stack.append(_offline_shadow_frame("$", False, False, False, "", True))
                        else:
                            over_depth += 1
                    prev, prev_word = "]", ""
                    continue
                if ch == ")" and done["candidate"]:
                    # `=>` may not be preceded by a line terminator, and a `{` on a later line is a
                    # separate block statement - `report(location)` then a block is a CALL, not a
                    # method definition, so both peeks are same-line. A method shorthand also only
                    # exists inside an object literal or a class body.
                    after = _offline_shadow_next_sig(src, i + 1, True)
                    if after == "=>":
                        return True
                    if (after == "{" and parent["ch"] == "{" and done["opener"]
                            and done["opener"] not in OFFLINE_SHADOW_NON_METHOD):
                        return True
                # A name read inside a computed KEY, or inside a default-value expression, is a
                # reference rather than a parameter, so it must not travel outwards and make the
                # group it sits in look like a parameter list: `(q = foo(location)) => {}` and
                # `({[location]: x}) => {}` declare nothing.
                if done["candidate"] and not done["key"] and not parent["in_default"]:
                    parent["candidate"] = True
                if parent["binding"] and not parent["in_default"]:
                    parent["named"] = True
            # A keyword read INSIDE a group cannot arm a bracket outside it.
            pending_params = False
            expect_name = False
            prev, prev_word = ch, ""
            i += 1
            continue
        if ch == "." and src.startswith("...", i):
            # A rest element is a BINDING (`function f(...location)`, `const {a, ...location}`),
            # so its `.`s must not leave the name looking like a member access.
            i += 3
            prev, prev_word = ",", ""
            continue
        if (ch == "+" and src.startswith("++", i)) or (ch == "-" and src.startswith("--", i)):
            # A postfix `++`/`--` ends a VALUE, so the `/` after it divides rather than opening a
            # regex literal whose scan would swallow the declaration behind it.
            i += 2
            prev, prev_word = "]", ""
            continue
        if ch == ";":
            frame["binding"] = False
            frame["decl"] = False
            frame["named"] = False
            frame["in_default"] = False
            pending_params = False
            expect_name = False
        elif ch == ",":
            frame["in_default"] = False
            frame["named"] = False
        elif ch == "=":
            if src.startswith("=>", i):
                i += 2
                prev, prev_word = ">", ""
                continue
            if not src.startswith("==", i) and prev not in OFFLINE_SHADOW_COMPOUND_OPS:
                frame["in_default"] = True
        prev, prev_word = ch, ""
        i += 1
    return False


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
    if offline_local_location_shadow(src):
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


# The refresh TARGET as a network literal, decided by the SHARED `is_network_url` every other
# egress gate reads rather than by a pattern of this rule's own. A bespoke copy had no way to stay
# in step: it read exactly two leading separators, so the four-or-more-separator `file:` spelling
# the attribute predicate counts was read as local (that one is a REAL AUTHORITY to Chromium, which
# is why the attribute gate counts it, and the separator arithmetic is empirical because Chromium
# DEVIATES from the spec here: measured in Chromium 149, `file:////evil.example/x.html` parses to
# host `evil.example` and re-serializes as `file://evil.example/x.html`, where a spec-conformant
# parser takes the WHATWG file-host state's EMPTY host and leaves `//evil.example/x.html` as the
# path; the two counted arms are the BASE-INDEPENDENT set - the same Chromium gives host
# `evil.example` to a ZERO- or ONE-separator spelling parsed ABSOLUTE, but against the `file:` base a
# document actually has those INHERIT the base's host and are local, so they carry no authority of
# their own; issue #1229 SETTLED that - see the `NETWORK_URL_RE` note above), and so was every
# slash run of three or more, which the
# shared `/{2,}` arm counts
# deliberately - what `///host` resolves to depends on the BASE (that host from a document served
# over http/https, where the special-authority states ignore the run; an empty-host local path from
# a `file:` one, where the file-host state takes the empty buffer), so counting it is the
# fail-CLOSED reading. In the other direction a Windows DRIVE LETTER - a path, not a host, to the
# file-host state - was named a network beacon it never reaches. One predicate cannot drift from
# itself, so the separator counts, the `localhost` and drive-letter exclusions and the
# non-empty-authority rule are all inherited. The backslash spellings the bespoke arms carried
# explicitly are inherited too, through `normalize_url_value`, which maps every backslash onto a
# slash for exactly the reason those arms existed: for a special scheme the parser's relative and
# authority-slash states treat the two alike, so `https:\\evil.example` and `\\evil.example` open
# an authority. `file:` is a special scheme too, so that mapping applies to it identically and
# `0;url=file:\\evil.example/x` IS counted (a corpus row). What makes a slash-poor `file:` target
# LOCAL is the SEPARATOR COUNT rather than any scheme exemption: a real Chromium's refresh
# NAVIGATION out of a `file:///` document was captured resolving `0;url=file:evil.example/x` to the
# local relative path `file:///C:/dir/evil.example/x`, never the SMB share (issue #1229; see
# `NETWORK_URL_RE` above for the full measurement, its Windows/Linux split, and the two neighbouring
# readings). Widening or narrowing here introduces no exporter/validator drift: offline mode
# rejects EVERY `meta[http-equiv=refresh]` (as the strip removes every one), and this predicate
# only decides WHICH of the two messages that rejection carries - the one that names a network
# beacon.
def meta_refresh_navigates_to_network(content):
    """True when a refresh meta's `content` names a target the SHARED egress predicate calls network.

    That predicate is deliberately fail-CLOSED rather than an exact model of what a browser resolves
    from this document's base, so a shape it over-reports (a slash run of three or more, which is a
    host only from an http/https base) reads True here too. Since offline mode rejects every refresh
    whatever its target, the cost of that is the WORDING of a rejection, never the rejection itself.
    """
    return is_network_url(meta_refresh_target(content))

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
# A `<noscript>` in the HEAD is the one shape where the two readings of a fallback body diverge
# before any pass on either side can look at it. The "in head noscript" insertion mode allows only
# `link`, `style`, `meta`, `basefont`, `bgsound`, `noframes`, comments and whitespace; anything else
# is a parse error that POPS the fallback and reprocesses that node - and everything after it - as a
# head SIBLING. The export re-parses with `DOMParser` (scripting off), so the promotion happens
# INSIDE that parse, and a promoted node is indistinguishable in the DOM from one the author wrote
# as a sibling: opening the SOURCE leaves a head `<noscript><script>` inert, opening the export runs
# it. The export therefore drops such a fallback in a PRE-PARSE pass over the source string, and
# this is the mirror of it - written as its own scanner rather than read off the shared tag index
# because it has to model the same tokenizer STATES the strip does, and the two must agree by
# construction rather than by coincidence.
OFFLINE_HEAD_NOSCRIPT_OK = frozenset(("link", "style", "meta", "basefont", "bgsound", "noframes"))
# What keeps a parser in "in head": a start tag outside this set (`<body>` included), an explicit
# `</head>`, or non-whitespace character data ends it, and a `<noscript>` after that is an ordinary
# element both readings agree about.
OFFLINE_HEAD_ELEMENTS = frozenset((
    "html", "head", "base", "basefont", "bgsound", "link", "meta", "noframes", "noscript",
    "script", "style", "template", "title"))
# Elements whose CONTENT a browser reads as text, mirroring the runtime's `_CMH_RAW_TEXT`.
OFFLINE_RAW_TEXT_ELEMENTS = frozenset((
    "script", "style", "textarea", "title", "xmp", "iframe", "noembed", "noframes", "noscript"))
# ASCII whitespace, as HTML defines it - not Python's `\s`, which is Unicode-aware and would read a
# NBSP as a delimiter a browser never treats as one.
OFFLINE_NON_SPACE_RE = re.compile(r"[^\t\n\f\r ]", re.ASCII)
# A character reference that decodes to ASCII whitespace, spelled out because HTML decodes
# references in CHARACTER DATA while a byte scan reads them as content. Measured in chromium: a
# `&Tab;` before a head fallback keeps the parser in the head, and a `&#9;` inside one leaves the
# fallback standing. The numeric forms may omit the semicolon, so each carries the class that stops
# `&#320;` (U+0140) being read as `&#32` plus a `0`.
OFFLINE_WS_CHAR_REF_RE = re.compile(
    r"&(?:Tab;|NewLine;|#(?:0*(?:9|10|12|13|32)(?![0-9])|[xX]0*(?:9|[aAcCdD]|20)(?![0-9A-Fa-f]));?)",
    re.ASCII)
OFFLINE_NAME_END_RE = re.compile(r"[\t\n\f\r />]", re.ASCII)
OFFLINE_TAG_LEAD_RE = re.compile(r"[A-Za-z]", re.ASCII)


def _offline_char_data_has_content(text):
    """Character data as the PARSER reads it rather than as the bytes read: a U+0000 is dropped
    outright and a whitespace character reference is whitespace, so neither ends the head nor pops a
    fallback. Mirrors `_offlineCharDataHasContent` in the runtime."""
    return bool(OFFLINE_NON_SPACE_RE.search(
        OFFLINE_WS_CHAR_REF_RE.sub(" ", (text or "").replace("\x00", ""))))


def _offline_tag_end(html, start):
    """The index of the `>` that ends the tag opening at `start`, or -1. A quote only opens an
    attribute value directly after `=`, so a stray apostrophe inside a tag does not swallow the
    rest of the document."""
    quote = ""
    after_equals = False
    i = start + 1
    while i < len(html):
        ch = html[i]
        if quote:
            if ch == quote:
                quote = ""
        elif ch in ('"', "'"):
            if after_equals:
                quote = ch
            after_equals = False
        elif ch == "=":
            after_equals = True
        elif ch in "\t\n\f\r ":
            pass
        elif ch == ">":
            return i
        else:
            after_equals = False
        i += 1
    return -1


def _offline_tag_name(html, frm):
    """The tag name, folded the way HTML folds one: ASCII ONLY. `str.lower()` is Unicode-aware, so
    it reads `lin<U+212A>` (KELVIN SIGN) as `link` while a browser does not - and that element
    really does POP a head fallback, so folding it into the allowed set would leave the promotion
    undetected. Mirrors `_offlineAsciiTagName` in the runtime."""
    m = OFFLINE_NAME_END_RE.search(html, frm)
    return _ascii_lower(html[frm:(m.start() if m else len(html))])


def _offline_comment_end(html, start):
    """The index just past the comment opening at `start`. `<!-->` and `<!--->` are complete (empty)
    comments and `--!>` also terminates one, so a legal comment cannot swallow the document."""
    i = start + 4
    if html[i:i + 1] == ">":
        return i + 1
    if html[i:i + 2] == "->":
        return i + 2
    m = re.compile(r"--!?>").search(html, i)
    return (m.end() if m else len(html))


def _offline_script_data_close(html, frm):
    """The index of the `</script` that really closes a script body, honouring the escaped and
    double-escaped script-data states (the classic `<!--<script>` idiom)."""
    rx = re.compile(r"<!--|-->|</?script(?=[\t\n\f\r />])", re.IGNORECASE | re.ASCII)
    escaped = False
    doubled = False
    for m in rx.finditer(html, frm):
        tok = m.group(0).lower()
        if tok == "<!--":
            escaped = True
        elif tok.startswith("-"):
            escaped = False
            doubled = False
        elif tok == "<script":
            if escaped:
                doubled = True
        elif doubled:
            doubled = False
        else:
            return m.start()
    return -1


def _offline_raw_text_close(html, name, frm):
    """The index of the end tag that closes the raw-text element `name`. An end tag only closes one
    when its name is followed by whitespace, `/` or `>`, so a `</scriptfoo>` is text."""
    if name == "script":
        return _offline_script_data_close(html, frm)
    m = re.compile("</" + re.escape(name) + r"(?=[\t\n\f\r />])",
                   re.IGNORECASE | re.ASCII).search(html, frm)
    return m.start() if m else -1


def offline_head_noscript_promotes(body):
    """Would a scripting-disabled parse take this HEAD fallback body apart? Mirrors
    `_offlineHeadNoscriptPromotes` in `assets/js/68-export-offline.js` token for token."""
    src = body or ""
    pos = 0
    while pos < len(src):
        lt = src.find("<", pos)
        # Promoted content need not be an element: a character token that is not whitespace is
        # "anything else" too, so a line of fallback prose becomes the start of the BODY.
        if _offline_char_data_has_content(src[pos:] if lt < 0 else src[pos:lt]):
            return True
        if lt < 0:
            return False
        if src[lt:lt + 4] == "<!--":
            pos = _offline_comment_end(src, lt)
            continue
        lead = src[lt + 1:lt + 2]
        if lead in ("!", "?"):
            # A DOCTYPE and a bogus comment are both tokens this mode ignores.
            gt = src.find(">", lt + 1)
            pos = len(src) if gt < 0 else gt + 1
            continue
        if lead == "/":
            end_name = _offline_tag_name(src, lt + 2)
            gt = _offline_tag_end(src, lt)
            # `</br>` is the one end tag the mode treats as "anything else"; every other one is a
            # parse error it ignores, so it promotes nothing.
            if end_name == "br":
                return True
            pos = len(src) if gt < 0 else gt + 1
            continue
        if not OFFLINE_TAG_LEAD_RE.match(lead):
            return True  # a `<` that opens no tag is character data
        end = _offline_tag_end(src, lt)
        if end < 0:
            return True  # a truncated tag: fail closed rather than guess how it ends
        name = _offline_tag_name(src, lt + 1)
        # An `<html>` or a nested `<noscript>` start tag is NOT a pop: this mode processes the first
        # with the in-body rules (which only merge its attributes) and ignores the second as a parse
        # error, and a real chromium agrees with the spec on both. A `<head>` start tag is a parse
        # error the SPEC also says to ignore, but chromium POPS the fallback on it, and the browser
        # that does the promoting is the one that matters, so it is read as "anything else" below.
        if name in ("html", "noscript"):
            pos = end + 1
            continue
        if name not in OFFLINE_HEAD_NOSCRIPT_OK:
            return True
        pos = end + 1
        if name in OFFLINE_RAW_TEXT_ELEMENTS:
            close = _offline_raw_text_close(src, name, pos)
            close_end = -1 if close < 0 else _offline_tag_end(src, close)
            # A raw-text child the fallback never closes runs PAST the seam the scripting-enabled
            # reader stops at, so the two readings disagree about the rest of the document.
            if close_end < 0:
                return True
            pos = close_end + 1
    return False


def offline_head_noscript_promotions(html):
    """The body of every HEAD `<noscript>` a scripting-disabled parse would take apart, in document
    order. Mirrors `_stripOfflineHeadNoscript`, which removes exactly these."""
    src = html or ""
    found = []
    # A leading BOM is dropped when a browser DECODES the file, so a real load never sees it as
    # character data and the head runs on past it. `validate.py` reads the file as plain `utf-8`, so
    # a hand-authored file keeps its BOM here, and reading that as content would stop the walk at
    # position 0 - turning this rule off for exactly the file it exists to catch.
    pos = 1 if src[:1] == "\ufeff" else 0
    template_depth = 0
    while True:
        lt = src.find("<", pos)
        if lt < 0:
            break
        # Character data is only the head's business outside a `<template>`, whose content is parsed
        # in its own fragment and never reaches the "in head noscript" mode at all.
        if template_depth == 0 and _offline_char_data_has_content(src[pos:lt]):
            break
        if src[lt:lt + 4] == "<!--":
            pos = _offline_comment_end(src, lt)
            continue
        lead = src[lt + 1:lt + 2]
        if lead in ("!", "?"):
            gt = src.find(">", lt + 1)
            pos = len(src) if gt < 0 else gt + 1
            continue
        if lead == "/":
            end_name = _offline_tag_name(src, lt + 2)
            gt = _offline_tag_end(src, lt)
            if template_depth > 0:
                if end_name == "template":
                    template_depth -= 1
            elif end_name in ("head", "html", "body", "br"):
                # Every end tag "in head" treats as "anything else" leaves the head, `</br>`
                # included, so a fallback written after one is BODY content this mode never judges.
                break
            pos = len(src) if gt < 0 else gt + 1
            continue
        if not OFFLINE_TAG_LEAD_RE.match(lead):
            if template_depth == 0:
                break
            pos = lt + 1
            continue
        end = _offline_tag_end(src, lt)
        if end < 0:
            break
        name = _offline_tag_name(src, lt + 1)
        if template_depth == 0 and name not in OFFLINE_HEAD_ELEMENTS:
            break
        nxt = end + 1
        if name in OFFLINE_RAW_TEXT_ELEMENTS:
            close = _offline_raw_text_close(src, name, end + 1)
            close_end = -1 if close < 0 else _offline_tag_end(src, close)
            if close_end < 0:
                # The element never closes (or its end tag is truncated), so its body runs to the
                # end of the document for both readings. A head fallback the insertion mode would
                # still take apart is reported rather than left standing - the scripting-disabled
                # parse pops it and promotes what follows just the same.
                if (template_depth == 0 and name == "noscript"
                        and offline_head_noscript_promotes(
                            src[end + 1:(len(src) if close < 0 else close)])):
                    found.append(src[end + 1:(len(src) if close < 0 else close)])
                break
            if (template_depth == 0 and name == "noscript"
                    and offline_head_noscript_promotes(src[end + 1:close])):
                found.append(src[end + 1:close])
            nxt = close_end + 1
        elif name == "template":
            template_depth += 1
        pos = nxt
    return found


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
    """True only for an https URL on the ADX web UX ORIGIN: host exactly the ADX host, default port.

    The href is already HTML-entity-decoded by the parser, so an encoded scheme
    (&#106;avascript:) is caught. Parsing the URL (not a substring match) means a
    javascript:/data: scheme or a look-alike host (dataexplorer.azure.com.evil.example)
    cannot pass.

    Three separate readings had to be the browser's here, and only the first is the `str.strip()`
    differential this predicate was fixed for (#1156):

    - The INPUT CLEANUP is `normalize_url_value`, not `str.strip()`. Python's argument-less strip
      reaches past ASCII and removes an NBSP / U+2028 / U+3000 / U+0085 the URL parser KEEPS, so
      `urlparse` reported the https scheme and the exact ADX host for an href a browser resolves
      RELATIVE to the document.
    - The AUTHORITY is decided after that cleanup's backslash-to-slash mapping, which a special
      scheme applies. `urlparse` keeps a backslash inside the netloc and then takes the host from
      AFTER an `@`, so `https://evil.example\\@dataexplorer.azure.com/x` named the exact ADX host
      while a browser reads the authority as `evil.example`.
    - The PORT is read, because `urlparse` reports a hostname without ever looking at one. An
      invalid or out-of-range port (`:abc`, `:65536`) is a URL the parser FAILS on, so a browser
      opens nothing; a valid but non-default port (`:444`) is a DIFFERENT origin that does not
      serve the ADX web UX. Both used to name the exact ADX host and pass.

    What is deliberately NOT modelled: WHATWG host canonicalization (percent-decoding, IDNA dot
    mapping, so `dataexplorer%2eazure.com` and a U+3002 dot are rejected) and the parser's
    authority-slash tolerance (`https:/host`, `https:///host`). Both gaps can only REJECT a link a
    browser would open, never clear one, so they cost a false positive rather than a bypass. Do
    not read this predicate as a general browser-exact URL parse.
    """
    try:
        u = urlparse(normalize_url_value(href))
        host = (u.hostname or "").lower()
        port = u.port  # the accessor that VALIDATES the port; `.hostname` never looks at one
    except ValueError:
        return False
    return u.scheme == "https" and host == _ADX_RUN_HOST and port in (None, 443)


def _link_loads(attrs):
    rels = link_rel_tokens(attrs.get("rel"))
    return bool(rels & FETCHING_LINK_RELS)


def _link_speculates(attrs):
    """True for a <link> that only exists to make the browser reach out early.

    Read on its own, without consulting the href: an offline document may not carry one at all
    (#1076). See `SPECULATIVE_LINK_RELS` for why the href predicate is the wrong layer here."""
    return bool(link_rel_tokens(attrs.get("rel")) & SPECULATIVE_LINK_RELS)


# The referrer surface the offline export hardens, and the gate that has to agree with it. No
# meta-delivered CSP can restrict TOP-LEVEL NAVIGATION, so a click the reader makes is not
# blockable and the one thing an offline document can still control is that the navigation carries
# no provenance: the export removes EVERY `referrerpolicy` attribute and replaces any authored
# referrer meta with `no-referrer` (`_stripOfflineNetworkLoads` / `_ensureOfflineCsp` in
# `assets/js/68-export-offline.js`). A per-element policy OVERRIDES the document one for that
# request, so a permissive attribute defeats the `no-referrer` meta on exactly the anchor an
# attacker planted, and the LAST referrer meta a document declares wins, so a permissive meta
# written after ours defeats it too.
#
# What that is worth is stated honestly rather than overclaimed: a document opened from `file://`
# sends no `Referer` at all whatever its policy says (the Referrer Policy standard's "strip url for
# use as a referrer" returns no referrer for a non-HTTP(S) source), so the leak this closes is the
# one an exported report meets once someone SERVES it - over http(s), where `unsafe-url` really
# does hand the full document URL to whatever the reader clicks. The parity argument stands on its
# own either way: the export removes this surface, so a gate that blesses what the export rewrites
# is the CMH-OFFLINE-04 drift.
#
# The gate is a CONTRACT check rather than a byte-for-byte mirror of the strip, exactly as the
# offline CSP rule is: the export REPLACES the CSP meta unconditionally while the gate accepts any
# applied policy that meets the contract. Here the contract is that nothing WEAKENS `no-referrer`,
# so what is reported is exactly what a browser would HONOUR as a weaker policy - which is why the
# attribute and the meta get SEPARATE readings below rather than one shared one, and why each was
# MEASURED in a real Chromium rather than read off the two specifications and hoped for.
REFERRER_POLICIES = frozenset((
    "no-referrer", "no-referrer-when-downgrade", "same-origin", "origin", "strict-origin",
    "origin-when-cross-origin", "strict-origin-when-cross-origin", "unsafe-url",
))
# The legacy spellings HTML still folds onto a modern token when it processes a referrer META.
# Folding them is what stops `always` - an alias for `unsafe-url` - from reading as an unparseable
# value the gate would wave through, and `never` really is honoured as `no-referrer` (both
# measured cross-origin: a document carrying `content="always"` sent the full URL, one carrying
# `content="never"` sent nothing).
REFERRER_POLICY_LEGACY = {
    "never": "no-referrer",
    "default": "no-referrer-when-downgrade",
    "always": "unsafe-url",
    "origin-when-crossorigin": "origin-when-cross-origin",
}
# The elements HTML gives `referrerpolicy` any meaning on. Scoped, the way the `ping` rule is
# scoped to `a`/`area`, because the attribute anywhere else controls no request and so cannot
# weaken anything - reporting `<div referrerpolicy="unsafe-url">` would only cost an author
# content. The SVG-only fetchers this file treats as loaders elsewhere (`image`, `use`, `feImage`)
# are deliberately NOT here: SVG2 lists the attribute on them, but a real Chromium exposes no
# `referrerPolicy` on any of the three (measured - the IDL attribute is absent entirely), so it
# honours nothing there. `a` and `script` are namespace-blind by tag NAME, which is what reaches
# the SVG anchor (measured as supported). The export still removes the attribute from every
# element, which is the same canonicalizing over-reach the CSP meta gets and costs the reader
# nothing.
REFERRER_POLICY_ELEMENTS = ("a", "area", "iframe", "img", "link", "script")


def referrer_policy_attr(value):
    """The policy a `referrerpolicy` ATTRIBUTE sets, or "" when it sets none.

    An enumerated attribute: the value is matched ASCII case-insensitively against the current
    tokens and nothing else. No whitespace trim and no legacy alias, both MEASURED - a real
    Chromium reads `referrerpolicy=" unsafe-url "` and `referrerpolicy="always"` as the invalid
    value state, which sets no policy at all and leaves the document's own in force, so trimming
    or folding here would report an attribute that weakens nothing.
    """
    token = _ascii_lower(value or "")
    return token if token in REFERRER_POLICIES else ""


def referrer_meta_policy(content):
    """The policy a `<meta name="referrer">` sets, or "" when it sets none.

    The WHOLE content value, ASCII-lowercased, with HTML's legacy aliases folded - NOT a
    comma-separated list and NOT trimmed. Measured rather than assumed, because the HTTP header
    grammar is a list and the meta one is not: in a real Chromium `content="no-referrer,
    unsafe-url"`, `content=" unsafe-url "` and `content=" origin-when-crossorigin "` all set NO
    policy (the document fell back to its default), while `content="unsafe-url"`,
    `content="always"` and `content="never"` each set theirs. Reading the meta as a list would
    have reported documents a browser treats as carrying no policy at all.
    """
    token = _ascii_lower(content or "")
    token = REFERRER_POLICY_LEGACY.get(token, token)
    return token if token in REFERRER_POLICIES else ""

def _csp_directives(content):
    """The directives of one policy, as a browser reads them: the FIRST occurrence of a directive
    name wins and every later copy is IGNORED. A plain dict build kept the LAST one, which let a
    permissive first copy be masked by a strict repeat written after it - the browser enforces the
    permissive one. Names are ASCII case-insensitive, so they are folded with `_ascii_lower` rather
    than `str.lower()` (a Unicode fold could map a look-alike onto a real directive name).

    Tokenized on ASCII whitespace ONLY, which is what CSP splits a policy on. Python's `str.split()`
    is Unicode-aware, so a NON-ASCII space - a NBSP, say - separated a directive from its value
    here while a browser read the whole run as ONE unrecognized directive name and enforced nothing
    at all: one character per directive neutralized the policy while this gate reported it
    complete. Tokenizing the browser's way leaves the mangled name unmatched, so the required
    directive is simply MISSING and the document is rejected."""
    directives = {}
    for part in (content or "").split(";"):
        bits = [t for t in _CSP_ASCII_WS_RE.split(part.strip(_CSP_ASCII_WS)) if t]
        if bits:
            directives.setdefault(_ascii_lower(bits[0]), bits[1:])
    return directives


def _offline_csp_policy_errors(content):
    """How one policy falls short of the offline contract, as a list of messages."""
    directives = _csp_directives(content)
    errors = []
    for name, required_tokens in OFFLINE_CSP_REQUIRED.items():
        values = directives.get(name)
        if values is None:
            errors.append("offline mode: Content-Security-Policy must include %s %s"
                          % (name, " ".join(required_tokens)))
            continue
        if not values:
            # A directive with NO sources matches nothing, so it is exactly as strict as `'none'`.
            # Reporting it as missing its required token would reject a browser-equivalent policy.
            continue
        # Source expressions are ASCII case-insensitive too (`DATA:` is `data:`), and folding them
        # the same way is what keeps a look-alike from passing for an allowlisted token.
        lowered = [_ascii_lower(v) for v in values]
        missing = [token for token in required_tokens if token not in lowered]
        if missing:
            errors.append("offline mode: Content-Security-Policy %s must include %s"
                          % (name, " ".join(missing)))
        allowed = OFFLINE_CSP_ALLOWED.get(name)
        if allowed is None:
            if lowered != list(required_tokens):
                errors.append("offline mode: Content-Security-Policy %s must be exactly 'none'" % name)
        else:
            extra = [v for v, low in zip(values, lowered) if low not in allowed]
            if extra:
                errors.append(
                    "offline mode: Content-Security-Policy %s carries the source expression %s, "
                    "which a browser can load over the network (or can grant something that does) "
                    "- an offline document promises zero network, so %s may name only %s"
                    % (name, ", ".join(extra), name, " ".join(sorted(allowed))))
    # The required set is not the whole policy, and an EXTRA directive may only TIGHTEN. CSP's more
    # specific fetch directives OVERRIDE the ones pinned above whenever they are present:
    # `script-src-elem` decides a `<script src>` load rather than `script-src`, `style-src-elem`
    # decides a stylesheet, and `worker-src`/`child-src`/`media-src`/`manifest-src`/`prefetch-src`
    # are safe here only while they are ABSENT and fall back to `default-src 'none'`. Closing the
    # NAME set - rather than enumerating the dangerous names - is the only shape that stays
    # fail-CLOSED against the next directive CSP adds, which is the whole reason for the rule.
    # A source list of exactly `'none'`, or none at all, cannot widen anything, so it passes; and
    # the directives that carry no SOURCE LIST at all are named in `OFFLINE_CSP_NON_FETCH` instead,
    # because running a sink group, a policy name or a sandbox flag through a source-list test asks
    # a question their grammar does not have (and would reject a document that layers on Trusted
    # Types hardening). `report-uri`/`report-to` are deliberately NOT in that set: a meta-delivered
    # policy IGNORES them, so they enforce nothing and a document promising zero network has no use
    # for a reporting endpoint - rejecting them keeps the emitted policy and the accepted one the
    # same shape. That inertness is also what makes the multi-policy short-circuit in
    # `_offline_csp_errors` sound: every effect a second policy could add is either conjunctive
    # (loads only narrow) or ignored in a `<meta>`.
    for name, values in directives.items():
        if name in OFFLINE_CSP_REQUIRED or name in OFFLINE_CSP_NON_FETCH:
            continue
        lowered = [_ascii_lower(v) for v in values]
        if lowered and lowered != ["'none'"]:
            errors.append(
                "offline mode: Content-Security-Policy carries the directive %s %s, which the "
                "offline contract does not pin - a more specific fetch directive overrides the "
                "one it does pin, so an extra directive may only tighten (a source list of "
                "exactly 'none', or none at all)"
                % (name, " ".join(values)))
    return errors


def _offline_csp_errors(doc):
    """The offline CSP contract, read off the policies a browser really APPLIES.

    `doc` is an already-parsed `_DocParser` (the normal path) or raw html. The parser view is what
    scopes this to a real policy: the shared tag index records EVERY start tag, so a policy meta
    parked in an inert `<template>` - or written once the document has left the head, where the
    HTML pragma directives are not processed at all - used to satisfy the requirement while
    enforcing nothing. (A `<noscript>` body was already excluded, since a scripting-enabled browser
    never creates the element inside it.)

    A policy meta is also useless if it arrives LATE. A meta-delivered policy is not retroactive -
    it governs only what the parser reaches after it - so a fetch or an execution written above it
    happens with no policy in force, which is exactly the channel the slashless attribute spellings
    ride. Such a policy is not read at all; it is reported instead.

    Enforcement across several policies is CONJUNCTIVE - a resource must be allowed by every one -
    so a document is offline-clean as soon as ANY applied policy meets the contract, and adding
    more policies can only narrow what loads. When none does, the FIRST policy's shortfalls are
    reported, since that is the one an author wrote to be the document's policy."""
    policies = _as_parser(doc).csp_metas
    if not policies:
        return ["offline mode: missing Content-Security-Policy meta tag with restrictive offline "
                "directives in the document head (a policy parked in a <template> or <noscript>, "
                "or written once the document has left the head, is one a browser never applies)"]
    first = None
    for policy in policies:
        if policy["late"]:
            continue
        errors = _offline_csp_policy_errors(policy["content"])
        if not errors:
            return []
        if first is None:
            first = errors
    if first is not None:
        return first
    return ["offline mode: the Content-Security-Policy meta tag is written after an element that "
            "can fetch or execute - a meta-delivered policy is not retroactive, so it does not "
            "cover what precedes it; put it at the top of the head, where the Offline export puts "
            "it"]


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


def _file_host_is_local(netloc):
    """True when the URL parser would EMPTY this `file:` host, so the reference names a purely
    LOCAL path and must not be resolved as a UNC/SMB share.

    The parser PERCENT-DECODES a file host and maps it through domain-to-ASCII (which lowercases)
    BEFORE the file-host state special-cases the exact string `localhost`, so `file://local%68ost/x`
    and `file://LOCALHOST/x` are the same local reference as `file://localhost/x` (all three parse
    to href `file:///x`). `urlparse` does NOT decode, so comparing its raw netloc to the literal
    sent the encoded spellings down the `//netloc+path` branch, resolved them to a bogus UNC path,
    and reported a companion file that is right there on disk as missing.

    A TRAILING DOT stays OUTSIDE the test: the special case is the exact string `localhost`, so
    `file://localhost./x` keeps a NON-EMPTY host and really is the SMB path `\\\\localhost.\\x`.

    Both calls mirror what the egress predicate's `_PCT_LOCALHOST` / `_PCT_LOCALHOST_END` already
    decide about the LOCALHOST spelling, so the two cannot disagree about it (pinned by
    `tests/test_validate_nonshareable.py` - `test_file_host_locality_agrees_with_the_egress_predicate`).
    That parity is why `_file_url_to_path` runs `normalize_url_value` first: the predicate reads the
    value after the parser's own input cleanup, and without it a BACKSLASH host terminator
    (`file://localhost\\dist\\x.js`, which the parser ends at the `\\` exactly as at a `/`, emptying
    the host) was a fresh instance of this very bug - local to the predicate, a UNC path here.

    Three limits on the parity, all deliberate. The percent-decoding models only the
    PERCENT-ENCODING and CASE half of canonicalization: the IDNA/UTS-46 half is not modelled, so a
    host that only UTS-46 maps onto `localhost` (`file://%EF%BD%8Cocalhost/x`,
    `file://LOCALHO%C5%BFT/x`, the soft-hyphen `file://local%C2%ADhost/x`) is read as a real
    authority here, exactly as the egress predicate reads it - the accepted over-detection
    `_PCT_LOCALHOST` records, kept rather than fixed because UTS-46 cannot be written as a regex the
    Python and JS engines agree on, and the two sides must not drift. The lowercasing is ASCII-only
    for the same reason. Second, the egress predicate ALSO excludes a Windows DRIVE-LETTER authority
    (`file://c:evil.example/x`), which is not mirrored here, so that shape can still resolve to a
    path the parser would not pick. Third, the predicate deliberately OVER-detects a `..` or empty
    path segment (`file://localhost/../dist/x.js`) as egress for canonicalization-stability reasons
    that do not apply to a path resolver, which resolves it the way the parser does. None costs
    anything beyond a rare spurious "companion file not found": this function gates no egress, it
    only resolves a companion ref to a path for an on-disk existence check. (The drive-letter
    shapes ARE partly mirrored one function down: `_file_host_names_no_path` keeps them resolvable
    so this resolver does not reject a host the predicate calls local - edit drive handling there,
    not here.)
    """
    if not netloc:
        return True
    return _ascii_lower(unquote(netloc)) == "localhost"


# Sentinel: the ref IS a `file:` URL, but it names no local path. It is deliberately NOT `None`
# (which means "not a `file:` URL at all"): the caller reports None as a wrong SCHEME, and the
# scheme is the one part of `file://[::1]/x` that is right.
_UNRESOLVABLE_FILE_URL = object()

# The scheme test for a ref the URL parser REFUSED, so `parsed.scheme` is unavailable. The parser
# strips leading C0 controls and spaces before reading a scheme, so this does too.
_FILE_SCHEME_PREFIX_RE = re.compile(r"^[\x00-\x20]*file:", re.I)

# A Windows drive-letter authority PREFIX. The URL parser reads `file://C:/x`, `file://C|/x` and
# even the separatorless `file://c:evil.example/x` as a local drive path rather than a host - the
# same call `NETWORK_URL_RE` makes (all three are non-egress there) - and `nturl2path` resolves
# them to a real local path, so they are not among the hostless shapes below. The test is on the
# RAW netloc: an ENCODED colon (`file://C%3A/x`) is not a drive letter to the parser either, and
# `:` is a forbidden host code point, so that spelling names nothing (the egress predicate calls
# it network for the same reason).
_DRIVE_LETTER_HOST_RE = re.compile(r"^[a-zA-Z][:|]")


def _file_host_names_no_path(netloc):
    """True when this non-local `file:` authority cannot name a local path at all.

    A UNC server name is a bare hostname, so an IPv6 literal (`file://[::1]/x`), a host:port
    (`file://host:8080/x`) and its `|` spelling (`file://host|8080/x`, which `nturl2path` reads as
    the same drive delimiter as `:`) are not one - none resolves to anything an OS could open.

    The test lives HERE, rather than being left to `url2pathname`, because that function is
    PLATFORM-SPECIFIC and disagrees about exactly these shapes: `nturl2path.url2pathname` RAISES
    `OSError('Bad URL: //[||1]/x')` on the IPv6 literal and silently mangles `//host:8080/x` into
    the bogus drive path `T:8080\\x`, while the POSIX implementation hands the string back
    unchanged. Deciding it here is what makes the verdict the same on every platform.

    The host is read PERCENT-DECODED, the same reading `_file_host_is_local` uses, because the URL
    parser decodes a file host before anything else looks at it. A DRIVE-LETTER prefix is dropped
    rather than exempting the whole string: `file://c:evil.example/x` is a drive path to the parser
    and resolves, but `file://c:evil:80/x` is not - screening only the prefix would send it to a
    resolver that rejects it on Windows and accepts it on POSIX, which is the split this function
    exists to remove.
    """
    host = unquote(netloc or "")
    if _DRIVE_LETTER_HOST_RE.match(netloc or ""):
        host = host[2:]
    return any(ch in host for ch in ":[]|")


def _file_url_to_path(ref):
    """The local filesystem path a `file:` companion ref names, or `None` when the ref is not a
    `file:` URL, or `_UNRESOLVABLE_FILE_URL` when it is one that names no local path.

    Nothing here may raise: a validator must REPORT malformed input, and an uncaught exception
    hands every fail-closed caller (`retrofit.py`, `content_replace.py`, `chart_block.py`,
    `finalize.py`) a traceback where a finding belongs. Both stages can throw on hostile input -
    `urlsplit` VALIDATES a bracketed authority, and `nturl2path.url2pathname` rejects authority and
    path shapes it cannot map - so both are guarded."""
    value = normalize_url_value(ref)
    try:
        parsed = urlparse(value)
    except ValueError:
        # `file://[foo]/x`, `file://[127.0.0.1]/x` and the unclosed `file://[::1/x` never reach a
        # host test: the parser rejects the authority first, on EVERY platform. A ref the parser
        # refuses names no local path either.
        return _UNRESOLVABLE_FILE_URL if _FILE_SCHEME_PREFIX_RE.match(value or "") else None
    if parsed.scheme.lower() != "file":
        return None
    if _file_host_is_local(parsed.netloc):
        raw = parsed.path
        # An empty authority can still carry one a slash deeper (`file:////host:8080/x` parses to
        # the PATH `//host:8080/x`), and the resolver maps that exactly as it maps an authority, so
        # it is screened exactly as one - otherwise the guard is one keystroke away from bypassed.
        if raw.startswith("//") and _file_host_names_no_path(raw[2:].split("/", 1)[0]):
            return _UNRESOLVABLE_FILE_URL
    elif _file_host_names_no_path(parsed.netloc):
        return _UNRESOLVABLE_FILE_URL
    else:
        raw = "//" + parsed.netloc + parsed.path
    try:
        return os.path.abspath(url2pathname(raw))
    except Exception:
        # The residual catch: the host shapes are screened above, but `nturl2path` also rejects
        # PATH shapes no host test can see, and it signals that rejection with MORE THAN ONE
        # exception type - `OSError('Bad URL')` for `/C:/dir/a:b/x.css`, but `IndexError` when the
        # drive delimiter LEADS the path (`file::/x`, `file:|x`, where it indexes an empty first
        # component). Catching by outcome rather than by type is deliberate: the try body is two
        # stdlib calls on a string with no logic of ours to mask, and 3.14 replaces the `nturl2path`
        # implementation outright, so an enumerated tuple is a list that goes stale into a crash.
        return _UNRESOLVABLE_FILE_URL


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


def _companion_ref_paths(doc, tag, attr, suffix):
    """Every companion reference by NAME and EXTENSION alone, whatever a browser would do with it.

    This is the pre-CMH-VAL-28 filter, kept because the two lists below answer a DIFFERENT
    question from the one `_check_nonshareable`'s ref-string classification loop asks. Whether a
    baked absolute path leaks a local directory, points into a temp folder, or carries a non-file
    scheme is a property of the STRING that is true whether or not a browser ever runs or applies
    the element - the disclosure is in the shipped bytes either way. Narrowing that loop along
    with the runnability lists dropped those reports with no second layer to catch them, so the
    classification loop iterates THIS list and only the "is the runtime/stylesheet here" decisions
    read the narrowed ones."""
    return [_ref_path(a[attr]) for a in _layer_tags(doc, tag)
            if "commentable-html" in (a.get(attr) or "").lower()
            and _ref_path(a.get(attr) or "").lower().endswith(suffix)]


def _companion_refs(doc):
    """Every companion reference the document names, deduplicated in first-seen order."""
    seen, out = set(), []
    for ref in (_companion_ref_paths(doc, "link", "href", ".css")
                + _companion_ref_paths(doc, "script", "src", ".js")):
        if ref not in seen:
            seen.add(ref)
            out.append(ref)
    return out


def _nonshareable_css_refs(doc):
    """Every external commentable-html companion STYLESHEET a browser would really APPLY.

    Three attributes decide that, and the `rel` one is the CSS half of the question
    `_nonshareable_js_refs` asks below (CMH-VAL-28): a `<link>` is a stylesheet only because its
    `rel` list says so, so a `rel="preload"` / `rel="modulepreload"` / no-`rel` link pointing at
    the companion CSS left the layer unstyled while satisfying "the stylesheet is here" - and,
    through `_is_nonshareable`, deciding the document mode. The list is read through the shared
    `link_rel_tokens` tokenizer, the way every other `rel` in this file is read, so a whitespace
    form `str.split()` would mis-tokenize cannot smuggle one in. `disabled` is the second: it is
    the one attribute whose whole meaning is "not applied", and nothing in the runtime enables
    such a sheet, so a disabled companion link leaves the layer exactly as unstyled as a missing
    one. `type` is the third: a browser obtains a stylesheet link only when the attribute is
    absent, empty, or a CSS MIME type essence match, so `<link rel="stylesheet" type="text/plain">`
    is fetched-and-ignored. All three are fail-CLOSED with no realistic false rejection - a
    document cannot disable, mistype or mis-`rel` the companion stylesheet and still expect it to
    style the layer.

    One shape is deliberately NOT tested: `rel="alternate stylesheet"`, which a browser applies
    only once the user picks it by title. Refusing it would be defensible, but "which alternate is
    active" is a user preference this reader cannot know, and no generator emits one - so it is
    left alone rather than guessed at."""
    return [_ref_path(a["href"]) for a in _layer_tags(doc, "link")
            if "commentable-html" in a.get("href", "").lower()
            and _ref_path(a.get("href", "")).lower().endswith(".css")
            and "stylesheet" in link_rel_tokens(a.get("rel"))
            and "disabled" not in a
            and _ascii_lower((a.get("type") or "").strip(_HTML_WHITESPACE)) in ("", "text/css")]


def _nonshareable_js_refs(doc):
    """Every external commentable-html companion SCRIPT a browser would really RUN (CMH-VAL-28).

    `_layer_tags` already restricts this to HTML-namespace tags outside the authored content
    region, which settles WHERE and in what namespace. `script_code_runs` settles the remaining
    half: a `type="application/json"` / `text/plain` tag, a MIME-parameter type, or a `nomodule`
    one every module-supporting browser skips, fetches nothing a browser executes - so it must not
    satisfy "the runtime is here" while the layer never loads. The loader search in `charts.py`
    already asked this about the same kind of tag; this list did not. `ns="html"` is passed
    explicitly even though it is the default, because the reason it is right lives HERE:
    `_layer_tags` restricts this list to HTML-namespace elements (CMH-VAL-19)."""
    return [_ref_path(a["src"]) for a in _layer_tags(doc, "script")
            if "commentable-html" in a.get("src", "").lower()
            and _ref_path(a.get("src", "")).lower().endswith(".js")
            and script_code_runs(a, "html")]


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
    # It walks `_companion_refs` - every reference the document NAMES - not the runnability-gated
    # lists above (CMH-VAL-28). What follows is a property of the ref STRING: a baked absolute
    # path leaks a local directory, and a temp path or a non-file scheme is wrong, whether or not
    # a browser would ever run or apply that element. Iterating the narrowed lists dropped those
    # reports for an inert-typed or non-`stylesheet` reference sitting BESIDE a working one, and
    # nothing else in the validator reports a local path on a `script`/`link`.
    # The BOUNDARY of that, recorded rather than implied: these are NonShareable-mode diagnostics
    # (every message says so), and this whole function runs only when the document IS NonShareable
    # - which, by CMH-VAL-28's own rule, it is not when EVERY companion reference it names is one
    # a browser cannot use. Such a file has no companion contract to violate: it is a Shareable
    # document carrying a stray inert reference, and reporting it against a contract it never
    # entered is the misclassification CMH-VAL-28 exists to stop.
    # The remote-URL and absolute-path checks are structural (they inspect the ref
    # string only), so they always run. Only the on-disk existence check needs a
    # base_dir; when base_dir is None the placement is deferred (e.g. generation-time
    # validation of a not-yet-placed document), so existence is not checked - the
    # structure is still validated.
    doc_dir = os.path.abspath(base_dir) if base_dir is not None else None
    for ref in _companion_refs(parser):
        # CLASSIFY (is this remote? a non-file scheme? a drive letter?) on the ref as the URL
        # PARSER reads it, the same value `_file_url_to_path` resolves. These regexes are anchored,
        # so reading the raw ref instead let the parser's own leading C0-or-space padding hide a
        # scheme from them: ` https://cdn/x.css` and ` vscode://x.js` both fell past every
        # classification and were resolved as RELATIVE paths, reported as a missing companion
        # rather than as the remote or wrong-scheme reference the browser will actually fetch.
        # Path RESOLUTION below still uses `norm`, which maps backslashes without moving anything.
        probe = normalize_url_value(ref)
        if re.match(r"(?:https?:)?//", probe, re.I):
            errors.append('nonshareable mode: companion reference "%s" must be a local file, not a remote/CDN URL (the layer must stay self-contained)' % ref)
            continue
        norm = ref.replace("\\", "/")
        file_target = _file_url_to_path(ref)
        if file_target is _UNRESOLVABLE_FILE_URL:
            # The scheme is right and what follows it is what is wrong, so this must not fall
            # through to the non-file-scheme branch below (which would blame the scheme). The
            # wording stays cause-neutral: a bad authority and a path shape the platform resolver
            # rejects both land here.
            errors.append('nonshareable mode: companion reference "%s" is a file: URL that does not resolve to a local file path - point the <link>/<script src> at the skill dist/ folder, or copy dist/ next to the document' % ref)
            continue
        baked_absolute = False
        if file_target is not None:
            target = file_target
            baked_absolute = True
        elif re.match(r"[a-zA-Z][a-zA-Z0-9+.\-]*:", probe) and not re.match(r"[a-zA-Z]:[\\/]", probe):
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
