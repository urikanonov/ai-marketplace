#!/usr/bin/env python3
"""Carry the vendored rich-libraries payload only in documents that can actually use it.

`cmhVendoredRichLibs` is a gzip+base64 bundle of mermaid and Chart.js that the OFFLINE EXPORT
inlines so a shared file renders diagrams and charts with no network. It was stamped into the
HEAD of every document unconditionally: measured on the shipped examples it is 1,363 KB, 55 to
61 percent of a 2.3 MB file, and it landed on line 7 - so a prose-and-code review document paid
for a renderer it could never call, and any tool that reads the head of the file hit a
megabyte-long line immediately.

This module decides, keeps, drops, and (re-)places that payload. Two properties matter:

1. DETECTION IS SCOPED TO THE CONTENT REGION. The built review layer's own JavaScript contains
   `pre.mermaid, div.mermaid, figure.chart canvas, canvas.cmh-chart` as a literal selector
   string, so a whole-document scan matches EVERY document and the feature silently becomes a
   no-op. Only the authored fragment between the CONTENT markers counts.
2. THE DECISION IS RE-EVALUATED, NOT MADE ONCE. A document that gains a diagram after it was
   stripped must get the payload back, or its offline export breaks. `apply` therefore both
   removes and restores, and finalize runs it on every write-back.

The selector set is deliberately the SAME one the runtime uses to decide whether it needs the
bundle (`_offlineLiveDocNeedsRichLibs` / `_offlineDocUsesMermaid` / `_offlineDocUsesCharts` in
assets/js/68-export-offline.js). If the two ever disagree, a document could ship without a
payload its exporter then demands, so a test pins them together.
"""
import os
import re
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tools/ root
import _toolpath  # noqa: E402
_toolpath.ensure()

import new_document  # noqa: E402

BLOB_ID = "cmhVendoredRichLibs"

_BLOB_RE = re.compile(
    r'[ \t]*<script\b[^>]*\sid\s*=\s*(["\'])' + BLOB_ID + r'\1[^>]*>[\s\S]*?</script>[ \t]*\r?\n?',
    re.IGNORECASE)

# Mirrors the runtime's selectors. Matching on the tag OPENING avoids parsing a multi-megabyte
# document just to answer a yes/no question, and the CONTENT region is small (0.1 - 1.3% of the
# file), so a regex over it is cheap and linear.
_USES_RE = re.compile(
    r'<pre\b[^>]*\bclass\s*=\s*["\'][^"\']*\bmermaid\b'
    r'|<div\b[^>]*\bclass\s*=\s*["\'][^"\']*\bmermaid\b'
    r'|<figure\b[^>]*\bclass\s*=\s*["\'][^"\']*\bchart\b'
    r'|<canvas\b[^>]*\bclass\s*=\s*["\'][^"\']*\bcmh-chart\b'
    r'|<canvas\b[^>]*\bdata-cmh-chart\b',
    re.IGNORECASE)


USES = "uses"
UNUSED = "unused"
UNKNOWN = "unknown"


def content_state(html):
    """Classify the document: `USES`, `UNUSED`, or `UNKNOWN`.

    `UNKNOWN` means the CONTENT region could not be located, so the document is left ENTIRELY
    alone - neither stripped (it might rely on the payload) nor given one (a document that never
    carried the payload must not suddenly grow by 1.3 MB because its markers were unreadable).
    Only a positively classified document is ever rewritten.
    """
    try:
        begin, end, _main_start, _tag_end = new_document._find_active_root(html)
    except Exception:
        return UNKNOWN
    if begin is None or end is None or end <= begin:
        return UNKNOWN
    fragment = html[begin + len(new_document.BEGIN_MARKER):end]
    return USES if _USES_RE.search(fragment) else UNUSED


def content_needs_rich_libs(html):
    """True when the document must keep the payload - it uses rich content, or is unclassifiable.

    Fails SAFE: stripping a payload a document relies on breaks its offline export, while
    keeping an unnecessary one only costs bytes. Use `content_state` when the difference between
    "definitely uses" and "cannot tell" matters (it decides whether to ADD a payload).
    """
    return content_state(html) != UNUSED


def find_blob(html):
    """Return the (start, end) span of the payload script, or None when it is absent."""
    m = _BLOB_RE.search(html)
    return (m.start(), m.end()) if m else None


def blob_script(source_html):
    """Return the payload script element (with a trailing newline) taken from a built template."""
    m = _BLOB_RE.search(source_html)
    if not m:
        return None
    text = m.group(0).strip("\r\n \t")
    return text + "\n"


def strip_blob(html):
    span = find_blob(html)
    if not span:
        return html, False
    return html[:span[0]] + html[span[1]:], True


def _insert_before_body_end(html, script):
    idx = html.lower().rfind("</body>")
    if idx == -1:
        return html, False
    return html[:idx] + script + html[idx:], True


def _is_at_end_of_body(html, span):
    """True when the payload already sits after the document content, near the body end.

    Used so an ALREADY well-placed payload is never rewritten - a relocation churns bytes in
    every document that has one, and an idempotent pass must not do that.
    """
    body_end = html.lower().rfind("</body>")
    if body_end == -1:
        return True
    head_end = html.lower().find("</head>")
    return span[0] > head_end and span[1] <= body_end


def apply(html, source_blob=None):
    """Add, remove, or leave the payload so the document carries it exactly when it can use it.

    `source_blob` is the payload script to restore with (see `blob_script`); pass None when only
    removal is wanted or no built template is reachable. Returns (html, changed) and is
    idempotent: a document already in the right state is returned byte-identical.
    """
    state = content_state(html)
    if state == UNKNOWN:
        # Cannot classify: touch nothing. Never grow a document that may not even be one of ours.
        return html, False
    span = find_blob(html)
    if state == UNUSED:
        return strip_blob(html)
    if span:
        if _is_at_end_of_body(html, span):
            return html, False
        # Present but in the head: move it out so the top of the file stays readable.
        without = html[:span[0]] + html[span[1]:]
        moved, ok = _insert_before_body_end(without, html[span[0]:span[1]].strip("\r\n \t") + "\n")
        return (moved, True) if ok else (html, False)
    if not source_blob:
        return html, False
    return _insert_before_body_end(html, source_blob)


def apply_file(path, source_blob=None):
    """Apply the decision to a file in place. Returns (changed, state)."""
    with open(path, "r", encoding="utf-8", newline="") as fh:
        html = fh.read()
    state = content_state(html)
    out, changed = apply(html, source_blob)
    if changed:
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(out)
    return changed, state


def main(argv):
    import argparse
    parser = argparse.ArgumentParser(
        prog="vendored_libs.py",
        description="Carry the vendored mermaid/Chart.js payload only in a document whose "
                    "content uses a diagram or a chart, and keep it out of the document head. "
                    "finalize.py runs this automatically; use it directly to inspect or fix a "
                    "single document.")
    parser.add_argument("file", help="HTML document to inspect or rewrite")
    parser.add_argument("--check", action="store_true",
                        help="report the decision and exit without writing")
    parser.add_argument("--template", default=None,
                        help="a built PORTABLE.html to take the payload from when it must be "
                             "restored (default: the skill's own dist/PORTABLE.html)")
    args = parser.parse_args(argv[1:])

    try:
        with open(args.file, "r", encoding="utf-8", newline="") as fh:
            html = fh.read()
    except (OSError, UnicodeDecodeError) as exc:
        sys.stderr.write("vendored_libs: %s\n" % exc)
        return 1

    state = content_state(html)
    present = find_blob(html) is not None
    if args.check:
        print("vendored_libs: content=%s payload=%s" % (state, "present" if present else "absent"))
        return 0

    source_blob = None
    template = args.template or os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "dist", "PORTABLE.html")
    try:
        with open(template, "r", encoding="utf-8", newline="") as fh:
            source_blob = blob_script(fh.read())
    except (OSError, UnicodeDecodeError):
        source_blob = None

    out, changed = apply(html, source_blob)
    if changed:
        with open(args.file, "w", encoding="utf-8", newline="") as fh:
            fh.write(out)
    print("vendored_libs: content=%s -> %s" % (state, "rewritten" if changed else "unchanged"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
