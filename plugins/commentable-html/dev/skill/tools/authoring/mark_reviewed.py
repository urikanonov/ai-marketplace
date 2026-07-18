#!/usr/bin/env python3
"""Bake section-review markers into a commentable-html document's reviewedSections block.

The runtime writes review markers when the reader marks a section reviewed in the browser and bakes
them on Export as Portable. This helper does the same deterministically from the CLI so an agent can
mark sections reviewed (or clear them) without a browser, mirroring mark_handled.py. Each marker is
computed with the SAME section content hash the runtime uses (tools/authoring/section_hash.py), so a
freshly-marked section loads as "reviewed", not "changed".

The markers live in `<script type="application/json" id="reviewedSections">` (an object keyed by
heading id) inside the EMBEDDED COMMENTS region; if the block is absent (an older document) it is
inserted right after the embeddedComments block. A file's dominant newline style is preserved.

The section hash covers the section's STABLE prose: cm-skip chrome and runtime-transformed blocks
(rendered diffs, KQL/code, mermaid, chart canvases, editable notes) are excluded from the hash on
BOTH the runtime (assets/js/84-section-review.js) and this tool (section_hash.py), so a marker baked
here loads as "reviewed" regardless of those blocks. Editing the surrounding prose still invalidates
the marker; editing only a rendered diff/chart/note does not (those are reviewed visually in-browser).

Usage (run from the skill root):
    python tools/authoring/mark_reviewed.py <file.html> <heading-id> [<heading-id> ...]   # mark
    python tools/authoring/mark_reviewed.py <file.html> --clear <heading-id> ...          # remove
    python tools/authoring/mark_reviewed.py <file.html> --list                            # print
Exit 0 on success (including nothing to do), 1 on error.
"""
import argparse
import datetime
import json
import os
import re
import sys
from html.parser import HTMLParser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import section_hash  # noqa: E402

SAFE_ID_RE = re.compile(r"^[A-Za-z][\w.:-]{0,199}$")
SAFE_HASH_RE = re.compile(r"^[0-9a-z]{1,16}$")


class _BlockLocator(HTMLParser):
    """Locate the real <script id="reviewedSections"> content range (comments/templates excluded)."""

    def __init__(self, text, block_id):
        super().__init__(convert_charrefs=False)
        self._offsets = [0]
        for m in re.finditer("\n", text):
            self._offsets.append(m.end())
        self._block_id = block_id
        self._active = False
        self._content_start = None
        self._template_depth = 0
        self.spans = []

    def _idx(self):
        lineno, col = self.getpos()
        return self._offsets[lineno - 1] + col

    def _is_target(self, tag, attrs):
        if tag.lower() != "script":
            return False
        d = {}
        for k, v in attrs:
            kl = (k or "").lower()
            if kl not in d:
                d[kl] = v if v is not None else ""
        return d.get("id") == self._block_id

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "template":
            self._template_depth += 1
            return
        if self._template_depth == 0 and self._is_target(tag, attrs):
            self._content_start = self._idx() + len(self.get_starttag_text())
            self._active = True

    def handle_startendtag(self, tag, attrs):
        if tag.lower() == "template":
            return
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag.lower() == "template":
            if self._template_depth > 0:
                self._template_depth -= 1
            return
        if self._active and tag.lower() == "script":
            self.spans.append((self._content_start, self._idx()))
            self._active = False


def _locate_block(html, block_id):
    p = _BlockLocator(html, block_id)
    try:
        p.feed(html)
        p.close()
    except Exception:
        pass
    return p.spans


def _format_object(markers):
    if not markers:
        return "{}"
    return json.dumps(markers, indent=2, ensure_ascii=False).replace("<", "\\u003c")


def _read(path):
    with open(path, "r", encoding="utf-8", newline="") as fh:
        raw = fh.read()
    crlf = raw.count("\r\n")
    lf = raw.count("\n") - crlf
    nl = "\r\n" if crlf > lf else "\n"
    return raw.replace("\r\n", "\n").replace("\r", "\n"), nl


def _write(path, text, nl):
    if nl != "\n":
        text = text.replace("\n", nl)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def _load_markers(html):
    spans = _locate_block(html, "reviewedSections")
    if not spans:
        return None, None
    if len(spans) > 1:
        raise ValueError('multiple <script id="reviewedSections"> blocks (must be unique)')
    lo, hi = spans[0]
    body = html[lo:hi].strip() or "{}"
    try:
        obj = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError("existing reviewedSections is not valid JSON: %s" % exc)
    if not isinstance(obj, dict):
        raise ValueError("reviewedSections must be a JSON object keyed by heading id")
    return obj, (lo, hi)


def _splice_block(html, span, markers):
    body = _format_object(markers)
    if span is not None:
        lo, hi = span
        return html[:lo] + "\n" + body + "\n" + html[hi:]
    # Insert a fresh block right after the REAL embeddedComments script (located with the tolerant
    # HTML parser, so a decoy id in an HTML comment or <template> cannot hijack the insertion point).
    block = '<script type="application/json" id="reviewedSections">\n' + body + "\n</script>"
    ec_spans = _locate_block(html, "embeddedComments")
    if len(ec_spans) > 1:
        raise ValueError('multiple <script id="embeddedComments"> blocks (must be unique)')
    if ec_spans:
        endtag_start = ec_spans[0][1]
        # endtag_start is where the closing tag begins; match it case-insensitively and tolerate
        # internal whitespace (</SCRIPT>, </script >) so a non-canonical close never splices the new
        # block INSIDE the embeddedComments JSON body.
        m = re.compile(r"</\s*script\s*>", re.IGNORECASE).match(html, endtag_start)
        if not m:
            raise ValueError("could not locate the closing </script> for embeddedComments")
        insert_at = m.end()
        return html[:insert_at] + "\n" + block + html[insert_at:]
    raise ValueError('no <script id="embeddedComments"> block found to anchor reviewedSections after')


def mark_reviewed(path, mark_ids, clear_ids, at=None):
    """Mark or clear review markers. Returns (marked, cleared, missing) id lists."""
    for hid in list(mark_ids) + list(clear_ids):
        if not SAFE_ID_RE.match(hid):
            raise ValueError("refusing unsafe heading id: %r" % hid)
    html, nl = _read(path)
    markers, span = _load_markers(html)
    if markers is None:
        markers, span = {}, None
    sections = {s["id"]: s for s in section_hash.extract_sections(html)}
    reviewed_at = at or datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    marked, missing = [], []
    for hid in mark_ids:
        sec = sections.get(hid)
        if sec is None:
            missing.append(hid)
            continue
        markers[hid] = {"hash": sec["hash"], "headingText": sec["headingText"][:200],
                        "level": sec["level"], "reviewedAt": reviewed_at}
        marked.append(hid)
    cleared = []
    for hid in clear_ids:
        if hid in markers:
            del markers[hid]
            cleared.append(hid)
    # Validate every hash we are about to write (must be a real string, not a JSON number).
    bad = [k for k, v in markers.items()
           if not (isinstance(v, dict) and isinstance(v.get("hash"), str) and SAFE_HASH_RE.match(v["hash"]))]
    if bad:
        raise ValueError("refusing to write markers with an unsafe hash: %r" % bad[:5])
    if marked or cleared or span is None:
        out = _splice_block(html, span, markers)
        _write(path, out, nl)
    return marked, cleared, missing


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path")
    parser.add_argument("ids", nargs="*", help="heading ids to mark reviewed")
    parser.add_argument("--clear", nargs="*", default=[], help="heading ids to clear")
    parser.add_argument("--list", action="store_true", help="print current markers and exit")
    parser.add_argument("--at", default=None, help="reviewedAt timestamp (default: now, UTC)")
    args = parser.parse_args(argv)
    if not os.path.exists(args.path):
        sys.stderr.write("mark_reviewed: file not found: %s\n" % args.path)
        return 1
    try:
        if args.list:
            html, _ = _read(args.path)
            markers, _span = _load_markers(html)
            print(json.dumps(markers or {}, indent=2, ensure_ascii=False))
            return 0
        marked, cleared, missing = mark_reviewed(args.path, args.ids, args.clear, args.at)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        sys.stderr.write("mark_reviewed: %s\n" % exc)
        return 1
    if missing:
        sys.stderr.write("mark_reviewed: no such heading id(s) in %s: %s\n" % (args.path, ", ".join(missing)))
        return 1
    print("marked %d, cleared %d section(s) in %s" % (len(marked), len(cleared), args.path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
