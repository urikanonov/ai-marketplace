#!/usr/bin/env python3
"""Store the COLD bulk of a document compressed, and keep the semantic skeleton literal.

#1250 measured that a generated body compresses about 18.7x, so compressing it is a large win on
disk - but compressing the WHOLE body would be an experience downgrade: `Ctrl+F` would miss text
before hydration, a no-JS read would render nothing, an AI reader or search indexer would extract
no prose, and deep-link anchors would dangle. So the document is TIERED instead.

ALWAYS PLAIN, never compressed: the title, every heading, the table of contents, prose, summary and
abstract blocks, chart/diagram sources, every table's caption and `<thead>`, and the FIRST
`keep_rows` rows of every large table body. That set is guaranteed BY CONSTRUCTION here, because
the only thing this module is ever allowed to take is the TAIL ROWS of a `<tbody>` - it never sees,
and so can never touch, a heading or a paragraph.

ELIGIBLE (cold): rows after the first `keep_rows` of a `<tbody>` that holds more than `min_rows`
rows, inside the CONTENT ROOT, in a table that is not nested inside another table and not inside a
`<template>`, and only when no tail row - or any of its descendants - carries something another
part of the layer resolves structurally. A candidate that fails any test is left plain: refusing to
compress only costs bytes, while compressing something an anchor, a renderer or a source-scanning
tool needs at parse time would be a behavior change.

WHERE THE PAYLOAD GOES, and why it is not simply "the end of the body". The runtime loader is part
of the layer's inline `<script>`, which a browser runs DURING PARSE - so anything after that script
does not exist yet when the loader looks for it. A payload placed just before `</body>` (where
`vendored_libs.py` correctly puts its own, which is read at click time rather than at load time) is
therefore invisible to hydration, and the cold rows silently vanish. The block goes immediately
AFTER the content root's `</main>` instead: still after every byte of authored content, still ahead
of every other machinery block, and - crucially - already parsed when the loader runs.

`compress` and `expand` are exact inverses: expanding a compressed document reproduces the original
bytes, which is what makes the generation flag ("emit today's fully-plain structure") a real,
testable escape hatch rather than a promise. `expand` RAISES `ColdTierError` when a payload is
present but cannot be put back, so an orphaned payload fails loudly instead of reading as "this
document was already plain" - which is how authored rows would otherwise be lost for good.
"""
import base64
import gzip
import json
import os
import re
import sys
import zlib
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tools/ root
import _toolpath  # noqa: E402
_toolpath.ensure()
import _atomic_io  # noqa: E402
import _browser_attrs  # noqa: E402

BLOB_ID = "cmhColdTier"
BLOB_TYPE = "application/json"
SLOT_CLASS = "cmh-cold-slot"
PART_ATTR = "data-cmh-cold-part"
FENCE_OPEN = "<!-- BEGIN: commentable-html - COLD TIER (generated machinery; safe to skip) -->"
FENCE_CLOSE = "<!-- END: commentable-html - COLD TIER -->"
PAYLOAD_VERSION = 1

MAX_EXPANDED_BYTES = 64 * 1024 * 1024

# The `cmh-cold-N` shape a part id may take. The runtime pins the same pattern, so neither side
# ever has to escape an id into a selector - both look a slot up by attribute VALUE instead.
PART_ID_RE = re.compile(r"^cmh-cold-[0-9]+$")

# Defaults chosen so an ordinary review table is never touched: a table has to be genuinely large
# before any of it goes cold, and what stays plain is still more rows than fit on a first screen.
DEFAULT_MIN_ROWS = 40
DEFAULT_KEEP_ROWS = 20

# A tail row carrying one of these - at ANY depth below it - is left plain. Each is resolved
# structurally by some other part of the layer or by an authoring tool: an anchor target, a
# renderer hook, a nested disclosure, a nested table (whose own rows would overlap this candidate),
# or - for `link` / `base` / `meta` - one of the egress channels `CMH-SEC-06` says the offline
# STRIPS, not the CSP, are what enforce.
_DISQUALIFYING = frozenset((
    "h1", "h2", "h3", "h4", "h5", "h6", "script", "style", "canvas", "iframe",
    "template", "details", "summary", "svg", "object", "embed", "noscript",
    "link", "base", "meta", "table",
))

# The same reason, by CLASS or ATTRIBUTE rather than tag name. The rich-content classes are the
# hooks `vendored_libs.py` scans the CONTENT REGION of the SOURCE for when it decides whether a
# document must carry the mermaid/Chart.js bundle: a diagram hidden inside a compressed payload
# would be invisible to that scan, so the document would be stripped of a payload its offline
# export then demands - a broken export, not merely a missed optimisation. An `on*` handler is
# excluded for the same reason `link`/`base` are: the offline strips read it out of the SOURCE.
_DISQUALIFYING_CLASSES = frozenset(("mermaid", "chart", "cmh-chart"))
_DISQUALIFYING_ATTR_PREFIXES = ("data-cmh-chart", "on")

_VOID = frozenset((
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
    "param", "source", "track", "wbr"))

_COMMENT_RE = re.compile(r"<!--[\s\S]*?-->")


class ColdTierError(Exception):
    """A document carries a payload that cannot be put back where it came from."""


class _Scan(_browser_attrs.BrowserTagNames):
    """One quote-, comment- and raw-text-aware pass that finds every compressible row tail.

    A regex cannot do this: `<td title="a > b">` ends a `[^>]*` scan early, a `</tbody>` inside an
    HTML comment truncates a naive region, and a document that DOCUMENTS this feature can show a
    payload script as an authored example. `vendored_libs.py` paid for all three; use the same
    standard-library tokenizer, which reads the document the way a browser does.

    Rows are tracked as a STACK, not a single slot. A nested `<table>` inside a cell otherwise
    overwrote the OUTER row and then cleared it, so that row was never recorded (its offsets simply
    dropped out of the body) and every disqualifying element between the two `</tr>`s was
    attributed to the INNER row - which let a heading, a `<script>` and a diagram all be compressed.
    """

    def __init__(self, html):
        _browser_attrs.BrowserTagNames.__init__(self, convert_charrefs=False)
        self._html = html
        self._line_offsets = [0]
        for line in html.split("\n")[:-1]:
            self._line_offsets.append(self._line_offsets[-1] + len(line) + 1)
        self._stack = []
        self.root_span = None
        self.root_end = None           # offset just PAST the content root's `</main>`
        self.body_end = None
        self.blob_spans = []           # outer spans of payload <script>s OUTSIDE the root
        self.slot_ids = []             # placeholder rows already present, in document order
        self.slot_spans = {}           # part id -> outer span of its placeholder <tr>
        self.bodies = []               # candidate tbodies: {"rows": [...], "cols": n, "ok": bool}
        self._root_inner_start = None
        self._root_depth = None
        self._blob_start = None
        self._pending_blob = False
        self._body_stack = []
        self._rows = []                # open <tr> frames, outermost first
        self._table_depth = 0
        self._template_depth = 0

    # -- offsets -------------------------------------------------------------
    def _offset(self):
        line, col = self.getpos()
        return self._line_offsets[line - 1] + col

    def _end_of_current_tag(self):
        text = self.get_starttag_text() or ""
        return self._offset() + len(text)

    def _in_root(self):
        return self._root_inner_start is not None and self.root_span is None

    def _disqualify_open_rows(self):
        for row in self._rows:
            row["ok"] = False

    # -- handlers ------------------------------------------------------------
    def handle_starttag(self, tag, attrs):
        tag = self._browser_tag(tag)
        pairs = {}
        for name, value in attrs:
            # FIRST wins, the way a browser reads a duplicate attribute; `dict(attrs)` keeps the
            # LAST, so the two sides could disagree about a document's own `type` or `id`.
            pairs.setdefault(name, value)
        classes = _browser_attrs.class_tokens(pairs.get("class"))
        if tag == "main" and pairs.get("id") == "commentRoot" and self._root_inner_start is None:
            self._root_inner_start = self._end_of_current_tag()
            self._root_depth = len(self._stack)
        if (tag == "script" and pairs.get("id") == BLOB_ID and not self._in_root()
                and (pairs.get("type") or "").strip().lower() == BLOB_TYPE):
            # Parity with the runtime loader, which also requires the inert JSON type. Without it
            # the two sides disagree about what the infrastructure payload IS, and an authored
            # example with another type would silently disable compression for the document.
            self._blob_start = self._offset()
            self._pending_blob = True
        if tag == "template":
            self._template_depth += 1
        if self._in_root():
            if tag == "table":
                self._table_depth += 1
                if self._table_depth > 1:
                    # A nested table: refuse the whole chain rather than risk two candidate spans
                    # that overlap, or an outer row whose descendants were never inspected.
                    self._disqualify_open_rows()
                    for body in self._body_stack:
                        body["ok"] = False
            elif tag == "tbody":
                self._body_stack.append({
                    "rows": [], "cols": 0,
                    "ok": self._template_depth == 0 and self._table_depth == 1})
            elif tag == "tr":
                body = self._body_stack[-1] if self._body_stack else None
                if body is not None and self._rows and self._rows[-1]["body"] is body:
                    # An implicitly closed row. Rather than guess where it ended, refuse the whole
                    # body: not compressing costs bytes, cutting at the wrong offset costs content.
                    body["ok"] = False
                is_slot = bool(pairs.get(PART_ATTR)) and SLOT_CLASS in classes
                self._rows.append({"start": self._offset(), "cells": 0, "ok": True,
                                   "body": body,
                                   "slot": pairs.get(PART_ATTR) if is_slot else None})
            elif tag in ("td", "th"):
                if self._rows:
                    try:
                        span = max(1, int((pairs.get("colspan") or "1").strip()))
                    except (TypeError, ValueError):
                        span = 1
                    self._rows[-1]["cells"] += span
            if tag in _DISQUALIFYING:
                self._disqualify_open_rows()
        if self._rows and (classes & _DISQUALIFYING_CLASSES
                           or any(name.startswith(_DISQUALIFYING_ATTR_PREFIXES) for name in pairs)):
            self._disqualify_open_rows()
        if tag not in _VOID:
            self._stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        tag = self._browser_tag(tag)
        if tag not in _VOID and self._stack and self._stack[-1] == tag:
            self._stack.pop()
        if tag == "template" and self._template_depth > 0:
            self._template_depth -= 1

    def handle_endtag(self, tag):
        tag = self._browser_tag(tag)
        if tag == "script" and self._pending_blob:
            close = self._html.find(">", self._offset())
            end = (close + 1) if close != -1 else (self._offset() + len("</script>"))
            self.blob_spans.append((self._blob_start, end))
            self._pending_blob = False
        if tag == "body" and self.body_end is None:
            self.body_end = self._offset()
        if tag == "template" and self._template_depth > 0:
            self._template_depth -= 1
        if self._in_root():
            if tag == "tr" and self._rows:
                close = self._html.find(">", self._offset())
                end = (close + 1) if close != -1 else (self._offset() + len("</tr>"))
                row = self._rows.pop()
                if row["slot"] is not None:
                    if self._template_depth == 0:
                        self.slot_ids.append(row["slot"])
                        self.slot_spans[row["slot"]] = (row["start"], end)
                elif row["body"] is not None:
                    row["end"] = end
                    row["body"]["rows"].append(row)
                    if row["cells"] > row["body"]["cols"]:
                        row["body"]["cols"] = row["cells"]
            elif tag == "tbody" and self._body_stack:
                body = self._body_stack.pop()
                while self._rows and self._rows[-1]["body"] is body:
                    # A row left open at `</tbody>`: same reasoning as an implicit close.
                    body["ok"] = False
                    self._rows.pop()
                self.bodies.append(body)
            elif tag == "table" and self._table_depth > 0:
                self._table_depth -= 1
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i] == tag:
                if (tag == "main" and self._root_depth is not None
                        and i == self._root_depth and self.root_span is None):
                    self.root_span = (self._root_inner_start, self._offset())
                    close = self._html.find(">", self._offset())
                    self.root_end = (close + 1) if close != -1 else None
                del self._stack[i:]
                return


def _scan(html):
    scan = _Scan(html)
    try:
        scan.feed(html)
        scan.close()
    except Exception:
        return None
    if scan.root_span is None and scan._root_inner_start is not None:
        # An UNCLOSED content root: a browser closes it at end of input, so recover the span the
        # same way. `root_end` stays unset - there is no `</main>` to place a payload after, so
        # `compress` declines rather than guessing an insertion point.
        scan.root_span = (scan._root_inner_start, len(html))
    while scan._body_stack:
        body = scan._body_stack.pop()
        body["ok"] = False
        scan.bodies.append(body)
    if scan.body_end is None:
        scan.body_end = len(html)
    return scan


def _escape_attr(value):
    return (value.replace("&", "&amp;").replace('"', "&quot;")
            .replace("<", "&lt;").replace(">", "&gt;"))


def _placeholder(part_id, cols, rows):
    # TWO messages, for two different readers. The `<noscript>` one is what a reader with scripting
    # OFF sees. The `<span>` is for a reader with scripting ON whose rows did NOT come back - either
    # because expansion failed, or because the document is being read by a runtime that predates
    # this feature and has no loader at all. It is hidden by THIS version's stylesheet (see
    # `assets/css/51-cold-tier.css`) rather than by a `hidden` attribute, precisely so that an older
    # runtime - which does not carry that rule - shows it instead of an unexplained empty row.
    unit = "table row" if rows == 1 else "table rows"
    verb = "is" if rows == 1 else "are"
    explain = ("%d %s here %s stored compressed further down in this same file (see the COLD TIER "
               "block) and %s restored automatically when scripting is enabled. No network access "
               "is needed either way." % (rows, unit, verb, verb))
    note = ("%d %s here %s stored compressed further down in this same file (see the COLD TIER "
            "block) and %s not expanded. Open this file in a browser with scripting enabled, or "
            "run the skill's cold_tier.py --expand on it, to read them."
            % (rows, unit, verb, "was" if rows == 1 else "were"))
    return ('<tr class="%s cm-skip" %s="%s"><td colspan="%d">'
            '<noscript>%s</noscript>'
            '<span class="cmh-cold-note">%s</span>'
            '</td></tr>' % (SLOT_CLASS, PART_ATTR, _escape_attr(part_id), cols, explain, note))


def _gaps_are_inert(html, rows):
    """True when nothing but whitespace and comments sits between consecutive rows.

    A browser FOSTER-PARENTS non-whitespace text found directly inside a table OUT of the table,
    and the loader hands back only the parsed `<tbody>` - so such text would be silently dropped on
    hydration. Refuse the tail instead.
    """
    for previous, current in zip(rows, rows[1:]):
        if _COMMENT_RE.sub("", html[previous["end"]:current["start"]]).strip():
            return False
    return True


def _eligible(html, scan, min_rows, keep_rows):
    """The compressible row tails, as (cold_start, cold_end, rows, cols), in document order."""
    out = []
    for body in scan.bodies:
        if not body["ok"]:
            continue
        rows = body["rows"]
        if len(rows) <= max(min_rows, keep_rows):
            continue
        tail = rows[keep_rows:]
        if not tail or not all(row["ok"] for row in tail):
            continue
        if not _gaps_are_inert(html, tail):
            continue
        out.append((tail[0]["start"], tail[-1]["end"], len(tail), body["cols"] or 1))
    out.sort()
    return out


def _payload_script(parts):
    for part in parts:
        if not PART_ID_RE.match(part.get("id") or ""):
            raise ValueError("cold-tier part id %r is not of the form cmh-cold-N" % part.get("id"))
    body = json.dumps({"v": PAYLOAD_VERSION, "parts": parts},
                      separators=(",", ":"), sort_keys=True)
    # An inert data script's content is raw text to the parser, so the sequences that could end it
    # early - or open a comment the parser then swallows - have to be impossible. base64 and the
    # `cmh-cold-N` ids above cannot produce either, but assert it rather than trusting the inputs.
    if "</" in body or "<!--" in body:
        raise ValueError("cold-tier payload would escape its own script element")
    return '<script type="%s" id="%s">%s</script>' % (BLOB_TYPE, BLOB_ID, body)


def find_blob(html):
    """The (start, end) span of the payload script, or None."""
    scan = _scan(html)
    if not scan or not scan.blob_spans:
        return None
    return scan.blob_spans[0]


def state(html):
    """`compressed` when the document carries a payload, else `plain`."""
    return "compressed" if find_blob(html) is not None else "plain"


def _strip_blob(html):
    """Remove every payload script and its fences. Returns (html, removed)."""
    scan = _scan(html)
    if not scan or not scan.blob_spans:
        return html, False
    out = html
    for start, end in sorted(scan.blob_spans, reverse=True):
        lead = out.rfind(FENCE_OPEN, 0, start)
        if lead != -1 and out[lead + len(FENCE_OPEN):start].strip() == "":
            start = lead
        tail = out.find(FENCE_CLOSE, end)
        if tail != -1 and out[end:tail].strip() == "":
            end = tail + len(FENCE_CLOSE)
        # Absorb the single newline the insert put in front of the block, so expanding is exact.
        if out[start - 1:start] == "\n":
            start -= 1
        out = out[:start] + out[end:]
    return out, True


def compress(html, min_rows=DEFAULT_MIN_ROWS, keep_rows=DEFAULT_KEEP_ROWS):
    """Move every eligible cold row tail into the payload. Returns (html, changed).

    Idempotent, and refuses a document that already carries a payload OR any placeholder row - so
    finalize can run this on every write-back, and a freshly generated id can never land on top of
    a stale placeholder that a later `expand` would then restore into the wrong place.
    """
    scan = _scan(html)
    if scan is None or scan.root_span is None or scan.root_end is None:
        return html, False
    if scan.blob_spans or scan.slot_ids:
        return html, False
    targets = _eligible(html, scan, min_rows, keep_rows)
    if not targets:
        return html, False
    parts = []
    out = html
    insert_at = scan.root_end
    for index, (start, end, rows, cols) in enumerate(reversed(targets)):
        part_id = "cmh-cold-%d" % (len(targets) - index)
        raw = html[start:end]
        data = base64.b64encode(gzip.compress(raw.encode("utf-8"), 9, mtime=0)).decode("ascii")
        parts.append({"id": part_id, "enc": "gzip+base64", "rows": rows, "data": data})
        placeholder = _placeholder(part_id, cols, rows)
        out = out[:start] + placeholder + out[end:]
        insert_at += len(placeholder) - (end - start)
    parts.reverse()
    block = "\n" + FENCE_OPEN + "\n" + _payload_script(parts) + "\n" + FENCE_CLOSE
    if insert_at < 0 or insert_at > len(out):
        return html, False
    return out[:insert_at] + block + out[insert_at:], True


def _read_payload(html, span):
    inner = html[span[0]:span[1]]
    open_end = inner.find(">")
    close_start = inner.rfind("</")
    if open_end == -1 or close_start <= open_end:
        raise ColdTierError("the compressed block is malformed")
    try:
        payload = json.loads(inner[open_end + 1:close_start])
    except ValueError as exc:
        raise ColdTierError("the compressed block is not readable JSON (%s)" % exc)
    if not isinstance(payload, dict) or payload.get("v") != PAYLOAD_VERSION:
        raise ColdTierError(
            "the compressed block is version %r, not %d - a newer tool wrote it, and this one "
            "cannot restore its rows; use the version that produced it, or its --expand"
            % (payload.get("v") if isinstance(payload, dict) else None, PAYLOAD_VERSION))
    parts = payload.get("parts")
    if not isinstance(parts, list) or not parts:
        raise ColdTierError("the compressed block names no content")
    return parts


def _bounded_gunzip(data, budget):
    """Inflate `data` in chunks, refusing to materialize more than `budget` bytes.

    `gzip.decompress` builds the WHOLE expanded member before anything can look at its size, so a
    small compression bomb would exhaust the authoring process rather than raise. Every consumer of
    this module - validate, finalize, the section hash, the agent edit loop - runs on documents
    that may have come from elsewhere, so bound it here the way `CMH-PKG-14` bounds the shipped
    zip. Returns the bytes, or raises `ValueError`.
    """
    obj = zlib.decompressobj(wbits=16 + zlib.MAX_WBITS)
    chunks = []
    total = 0
    remaining = data
    while True:
        piece = obj.decompress(remaining, min(1 << 20, budget - total + 1))
        remaining = obj.unconsumed_tail
        total += len(piece)
        if total > budget:
            raise ValueError("expanded content is larger than the %d byte limit" % budget)
        if piece:
            chunks.append(piece)
        if obj.eof:
            break
        if not remaining and not piece:
            raise ValueError("the compressed stream is truncated")
    if obj.unused_data.strip(b"\x00"):
        raise ValueError("the compressed stream carries trailing data")
    return b"".join(chunks)


def expand(html):
    """Restore every compressed row tail and drop the payload. Returns (html, changed).

    The exact inverse of `compress`: expanding a compressed document reproduces the original bytes.
    Raises `ColdTierError` when a tier IS present but cannot be put back - orphaned either way
    (a payload with no placeholder, or a placeholder with no payload), corrupt, duplicated, or
    version-unknown. Reporting that as "nothing changed" is how authored rows get lost for good:
    the next write would validate and stamp a document whose content can no longer be recovered.

    A document with no cold-tier markers at all short-circuits before parsing. That is not only a
    saving on every multi-megabyte finalize - it is what keeps this from becoming a SECOND, stricter
    gate in front of the validator: `_scan` reports "unparseable" for shapes the validator's own
    tolerant parser handles, and a plain document must never be refused by a pre-pass belonging to
    a feature it does not use.
    """
    if BLOB_ID not in html and SLOT_CLASS not in html:
        return html, False
    scan = _scan(html)
    if scan is None:
        # Unparseable: there is no payload this can identify, so there is nothing to expand and
        # nothing to lose. Leave the document alone and let the caller's own checks report on it.
        return html, False
    if not scan.blob_spans:
        if scan.slot_ids:
            raise ColdTierError(
                "the document has compressed-section markers (%s) but no compressed block: its "
                "hidden rows are not in this file" % ", ".join(sorted(set(scan.slot_ids))))
        return html, False
    if len(scan.blob_spans) > 1:
        raise ColdTierError("the document carries %d compressed blocks; expected one"
                            % len(scan.blob_spans))
    if len(scan.slot_ids) != len(set(scan.slot_ids)):
        raise ColdTierError("the document carries duplicate compressed-section markers")
    parts = _read_payload(html, scan.blob_spans[0])
    restore = []
    seen = set()
    # ONE budget across the whole payload, not per part: every expanded section is held until the
    # last one decodes, so a per-part cap would let many legal-looking parts add up without limit.
    budget = MAX_EXPANDED_BYTES
    for part in parts:
        if not isinstance(part, dict):
            raise ColdTierError("the compressed block holds an unreadable entry")
        part_id = part.get("id")
        if not isinstance(part_id, str) or not PART_ID_RE.match(part_id):
            raise ColdTierError("the compressed block names an unusable section id %r" % (part_id,))
        if part_id in seen:
            raise ColdTierError("the compressed block names section %s twice" % part_id)
        seen.add(part_id)
        slot = scan.slot_spans.get(part_id)
        if slot is None:
            raise ColdTierError("compressed section %s has no place to go in this document"
                                % part_id)
        if part.get("enc") != "gzip+base64":
            raise ColdTierError("compressed section %s uses an unknown encoding %r"
                                % (part_id, part.get("enc")))
        try:
            raw = _bounded_gunzip(base64.b64decode(part.get("data") or "", validate=True), budget)
            budget -= len(raw)
            restore.append((slot[0], slot[1], raw.decode("utf-8")))
        except Exception as exc:
            raise ColdTierError("compressed section %s could not be expanded (%s)"
                                % (part_id, exc))
    unclaimed = sorted(set(scan.slot_ids) - seen)
    if unclaimed:
        raise ColdTierError("the document has compressed-section markers the block does not name: "
                            + ", ".join(unclaimed))
    out = html
    for start, end, text in sorted(restore, reverse=True):
        out = out[:start] + text + out[end:]
    out, _removed = _strip_blob(out)
    return out, out != html


def expanded_view(html):
    """The document as the reader's browser will have it, for any tool that SCANS the source.

    Every source-scanning consumer - the validator, the section content hash, the word counts -
    must read the rows the reader sees, not the placeholder standing in for them. A plain document
    is returned unchanged, so this is safe to call unconditionally. Raises `ColdTierError` on a
    broken tier, so a caller fails closed rather than scanning content it cannot see.
    """
    return expand(html)[0]


def apply(html, enabled, min_rows=DEFAULT_MIN_ROWS, keep_rows=DEFAULT_KEEP_ROWS):
    """Bring the document to the requested tier state. Returns (html, changed)."""
    if enabled:
        return compress(html, min_rows=min_rows, keep_rows=keep_rows)
    return expand(html)


def apply_file(path, enabled, min_rows=DEFAULT_MIN_ROWS, keep_rows=DEFAULT_KEEP_ROWS):
    with open(path, "r", encoding="utf-8", newline="") as fh:
        html = fh.read()
    out, changed = apply(html, enabled, min_rows=min_rows, keep_rows=keep_rows)
    if changed:
        _atomic_io.atomic_write(path, out)
    return changed, state(out)


def main(argv):
    import argparse
    parser = argparse.ArgumentParser(
        prog="cold_tier.py",
        description="Store the cold bulk of a document (the tail rows of its large tables) as a "
                    "gzip+base64 payload the runtime inflates on load, keeping every heading, "
                    "the TOC, prose and each table's header and first rows literal in the file. "
                    "finalize.py --cold-tier runs this; --expand puts a document back to today's "
                    "fully-plain structure. Prefer running it THROUGH finalize: finalize expands "
                    "before every other phase and validates the EXPANDED document, so no other "
                    "tool ever reads a document whose rows are hidden from it.")
    parser.add_argument("file", help="HTML document to inspect or rewrite")
    parser.add_argument("--check", action="store_true",
                        help="report the state and exit without writing")
    parser.add_argument("--expand", action="store_true",
                        help="restore the compressed rows and drop the payload")
    parser.add_argument("--min-rows", type=int, default=DEFAULT_MIN_ROWS,
                        help="only compress a table body with more rows than this (default %d)"
                             % DEFAULT_MIN_ROWS)
    parser.add_argument("--keep-rows", type=int, default=DEFAULT_KEEP_ROWS,
                        help="leave this many leading rows plain in every compressed body "
                             "(default %d)" % DEFAULT_KEEP_ROWS)
    args = parser.parse_args(argv[1:])

    try:
        with open(args.file, "r", encoding="utf-8", newline="") as fh:
            html = fh.read()
    except (OSError, UnicodeDecodeError) as exc:
        sys.stderr.write("cold_tier: %s\n" % exc)
        return 1

    if args.min_rows < 1 or args.keep_rows < 1:
        sys.stderr.write("cold_tier: --min-rows and --keep-rows must be positive\n")
        return 1
    if args.keep_rows >= args.min_rows:
        sys.stderr.write("cold_tier: --keep-rows (%d) must be below --min-rows (%d), or the "
                         "min-rows threshold has no effect\n" % (args.keep_rows, args.min_rows))
        return 1

    if args.check:
        scan = _scan(html)
        eligible = len(_eligible(html, scan, args.min_rows, args.keep_rows)) if scan else 0
        markers = len(scan.slot_ids) if scan else 0
        # A document that already carries a placeholder is never re-compressed (a generated id
        # could land on a stale marker), so say so rather than reporting a silent zero.
        print("cold_tier: state=%s eligible-bodies=%d slot-markers=%d"
              % (state(html), eligible, markers))
        return 0

    before = state(html)
    try:
        out, changed = apply(html, not args.expand, min_rows=args.min_rows,
                             keep_rows=args.keep_rows)
    except ColdTierError as exc:
        sys.stderr.write("cold_tier: %s\n" % exc)
        return 1
    if changed:
        _atomic_io.atomic_write(args.file, out)
    print("cold_tier: %s -> %s (%s)"
          % (before, state(out), "rewritten" if changed else "unchanged"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
