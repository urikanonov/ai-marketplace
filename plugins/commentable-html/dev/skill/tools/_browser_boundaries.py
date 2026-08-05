"""Browser-accurate element BOUNDARIES for the tools OUTSIDE the validator's `checks` package.

`checks/parsing._BrowserBoundaries` decides where one element ends and the next begins the way a
BROWSER decides it, and identically on every interpreter (CMH-VAL-21): the whole raw-text / RCDATA
set holds TEXT, a raw-text element closes on `</name` followed by whitespace / `/` / `>`, a comment
closes at `-->` / `--!>` / abruptly and at nothing else, an unterminated comment or declaration
consumes the rest of the document, `<![CDATA[` opens a section only inside foreign content, and a
tag truncated at end of input is discarded.

`tools/_browser_attrs.py` already gave these tools the shared attribute rule; this gives them the
shared element rule, so a `<main id="commentRoot">` or a `<pre class="mermaid">` written inside a
`<textarea>`, `<title>`, `<noscript>` or `<iframe>` body is raw TEXT to an authoring tool exactly as
it is to a browser and to the validator - instead of being a real start tag an authoring tool would
anchor its edit to, differently on 3.12 than on 3.13.

A subclass keeps its OWN element stack parallel to the shared namespace stack, but it does NOT
repeat the tag-handler sequence: `handle_starttag()`, `handle_startendtag()` and `handle_endtag()`
live in the shared base and drive overridable hooks (`_visit_start()`, `_push_element()`,
`_visit_void()`, `_after_start()`, `_visit_self_closed()`, `_visit_end()`), so a subclass overrides
only what it COLLECTS and the boundary order - including `_enter_raw_text()`, which the base's own
`_enter_cdata_mode()` is deliberately off for - is written down once.
`checks/parsing._TagAttrParser` is the smallest worked example.

A partial install (the `validate` tool missing) falls back to a host-semantics base with the same
API rather than failing: a degraded parse is better than a tool that cannot run, and the fallback is
WARNED about once, exactly as the attribute shim's is.
"""
import os
import sys
from html.parser import HTMLParser

_VOID = frozenset((
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
))

_TOOLS_ROOT = os.path.dirname(os.path.abspath(__file__))
if _TOOLS_ROOT not in sys.path:
    sys.path.insert(0, _TOOLS_ROOT)

# Both hard imports, like every other tool's: they sit beside this file, so they resolve in any
# real install. `_browser_attrs` is reused rather than re-resolved so the shipped-origin check that
# refuses a foreign `checks.parsing` (one already in `sys.modules`) is written down ONCE and the two
# shims can never disagree about which decoder-and-boundaries module they are reading.
import _browser_attrs  # noqa: E402
import _toolpath  # noqa: E402


def _is_shipped_sibling(module):
    """Whether `module` really is the attribute shim that ships beside this file.

    `import _browser_attrs` resolves through `sys.modules` FIRST, so a host process that already
    imported some other module by that name would otherwise hand this shim the base class with no
    signal - which would defeat the very origin check being reused. Confirming the ORIGIN here
    keeps the guarantee end to end rather than one indirection short of it."""
    origin = os.path.abspath(getattr(module, "__file__", "") or "")
    return origin == os.path.join(_TOOLS_ROOT, "_browser_attrs.py")


_BASE = None
if _is_shipped_sibling(_browser_attrs):
    _BASE = getattr(_browser_attrs._parsing, "_BrowserBoundaries", None)
if _BASE is None:  # pragma: no cover - only a broken/partial install gets here
    _toolpath.warn_missing_tool("validate", "browser-accurate element boundaries")


def _line_starts(text):
    starts = [0]
    for i, ch in enumerate(text or ""):
        if ch == "\n":
            starts.append(i + 1)
    return starts


class _FallbackBoundaries(HTMLParser):
    """The degraded base: the HOST's own boundaries, behind the shared base's API.

    Only a broken/partial install reaches this. Every method the shipped base offers a subclass is
    present, so a tool keeps parsing; what it does NOT do is correct the host - raw text is whatever
    set the running `html.parser` happens to ship, and the implicit `</p>` / `</li>` close is not
    applied. That is exactly the pre-CMH-VAL-21 behavior, which is the point: a tool degrades to
    what it used to do rather than crashing.
    """

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self._starts = _line_starts(html)
        self._ns = []
        self._end_tag_close = False
        self._host_attrs = ()

    def parse_document(self, html):
        self.feed(html)
        self.close()

    def _off(self):
        ln, col = self.getpos()
        return self._starts[ln - 1] + col

    def _start_tag_end(self):
        return self._off() + len(self.get_starttag_text() or "")

    def _attrs_dict(self, tag, attrs):
        return _browser_attrs.attrs_dict(self, tag, attrs)

    def _browser_tag(self, tag):
        return (tag or "").lower()

    def _child_namespace(self, tag, _ad):
        parent_ns = self._ns[-1][1] if self._ns else "html"
        if parent_ns != "html":
            return parent_ns
        return "svg" if tag == "svg" else ("math" if tag == "math" else "html")

    def _foreign_self_closes(self, ns):
        return ns != "html"

    def _push_ns(self, tag, ns, _ad):
        self._ns.append((tag, ns, False))

    def _truncate_stacks(self, depth):
        del self._ns[depth:]

    def _implicit_close(self, tag):
        """No-op: the host has no such rule, and reproducing HTML5 scope here would be a second,
        divergent copy of the very thing this shim exists to share."""

    def _end_tag_floor(self, _tag):
        """No template scoping: 0 is "search the whole stack", the pre-CMH-VAL-21 behavior.

        Present because every tool's `handle_endtag` now bounds its search by this, so a degraded
        install must still answer it - degrading to what the tool used to do, not crashing."""
        return 0

    def _enter_raw_text(self, tag, ns):
        """No-op: on this path the host's own `parse_starttag()` has already entered whatever
        raw-text mode it knows about."""

    def _innermost_open(self, _tag):
        """The stack index an end tag would close, or -1. Scanned rather than indexed: the shipped
        base keeps a name index for it, and reproducing that here would be a second copy of
        bookkeeping this shim only needs to answer the handler skeleton below."""
        for i in range(len(self._ns) - 1, -1, -1):
            if self._ns[i][0] == _tag:
                return i
        return -1

    # -- the shared handler skeleton, degraded ------------------------------ #
    #
    # The same sequence and the same hooks as the shipped base, so a subclass written against the
    # hooks keeps parsing on a broken/partial install instead of losing its tag handlers entirely.
    # What degrades is only what the methods above degrade (the host's raw-text set, no implicit
    # close, no `<template>` floor) - never WHICH steps run, or in what order.

    def _opens_element(self, tag, ns):
        return tag not in _VOID or ns != "html"

    def handle_starttag(self, tag, attrs):
        tag = self._browser_tag(tag)
        self._host_attrs = attrs
        ad = self._attrs_dict(tag, attrs)
        ns = self._child_namespace(tag, ad)
        if ns == "html":
            self._implicit_close(tag)
        opens = self._opens_element(tag, ns)
        info = self._visit_start(tag, ad, ns, opens)
        if opens:
            self._push_element(tag, ad, ns, info)
            self._push_ns(tag, ns, ad)
        else:
            self._visit_void(tag, ad, ns, info)
        self._enter_raw_text(tag, ns)
        self._after_start(tag, ad, ns, opens)

    def handle_startendtag(self, tag, attrs):
        tag = self._browser_tag(tag)
        self._host_attrs = attrs
        ad = self._attrs_dict(tag, attrs)
        ns = self._child_namespace(tag, ad)
        if not self._foreign_self_closes(ns):
            self.handle_starttag(tag, attrs)
            return
        self._visit_self_closed(tag, ad, ns)

    def handle_endtag(self, tag):
        tag = self._browser_tag(tag)
        index = self._innermost_open(tag)
        if self._visit_end(tag, index) is False:
            return
        if index < 0:
            return
        self._end_tag_close = True
        try:
            self._truncate_stacks(index)
        finally:
            self._end_tag_close = False

    def _visit_start(self, tag, ad, ns, opens):
        return None

    def _push_element(self, tag, ad, ns, info):
        """Push the element onto the subclass's own stack (see the shipped base)."""

    def _visit_void(self, tag, ad, ns, info):
        """The element is never pushed, so it has no content."""

    def _after_start(self, tag, ad, ns, opens):
        """After `_enter_raw_text()`."""

    def _visit_self_closed(self, tag, ad, ns):
        """A FOREIGN element written self-closed: opened and closed at once, reported as a start
        tag that opens nothing (see the shipped base)."""
        self._visit_void(tag, ad, ns, self._visit_start(tag, ad, ns, False))

    def _visit_end(self, tag, index):
        """An end tag before truncation; return False to keep a matched element open."""


class _RefreshedLineStarts:
    """Recompute the line-start table from the document actually being parsed.

    The shared base builds it in `__init__`, which is right for a parser constructed WITH its
    source - but several scanners keep an `html=""` convenience constructor for callers that only
    `feed()`, and one of those would otherwise report `_off()` offsets into an empty table. Doing it
    here rather than in each subclass keeps the nine tools honest with one line."""

    def parse_document(self, html):
        if getattr(self, "_track_offsets", True):
            self._starts = _line_starts(html)
        super().parse_document(html)


if _BASE is not None:
    class BrowserBoundaries(_RefreshedLineStarts, _BASE):
        pass
else:  # pragma: no cover - only a broken/partial install gets here
    class BrowserBoundaries(_RefreshedLineStarts, _FallbackBoundaries):
        pass


# Whether the SHIPPED boundaries are in use (False only on a broken/partial install).
IS_SHARED = _BASE is not None

_shared_end_tag_close = getattr(_browser_attrs._parsing, "_end_tag_close", None) if IS_SHARED else None


def end_tag_end(text, start):
    """Index just past the `>` that ends the END TAG starting at `start`, or `start` if it never
    closes.

    A browser ends a tag at the first `>` that is not inside a QUOTED ATTRIBUTE VALUE, and a quoted
    value only begins AFTER `=` - so `</nav a=">">` ends at the SECOND `>`. A bare `text.find(">")`
    stops at the first one and leaves the tail (`">`) behind in a document these tools REWRITE.
    The rule is the shared one (`checks/parsing._end_tag_close`); the degraded install falls back to
    the naive scan, which is what these tools used to do everywhere."""
    text = text or ""
    if _shared_end_tag_close is not None:
        close = _shared_end_tag_close(text, start)
        return close if close >= 0 else start
    end = text.find(">", start)
    return start if end == -1 else end + 1
