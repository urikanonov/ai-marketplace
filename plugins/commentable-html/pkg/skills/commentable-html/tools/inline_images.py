#!/usr/bin/env python3
"""Inline local ``<img src="...">`` references as ``data:`` URIs.

Local images referenced by a report live alongside the HTML (in a folder you point
at with ``--base``). This tool bundles them into the generated HTML so the artifact is a
single self-contained file: it finds every ``<img>`` whose ``src`` is a local relative
path (not ``http(s):``, ``data:``, ``//`` or a ``#`` fragment), reads the referenced
file relative to a base directory, base64-encodes it with the right MIME type, and
rewrites the ``src`` to a ``data:`` URI. Remote and already-inlined sources are left
untouched.

Usage::

    python tools/inline_images.py <file.html> [--base DIR] [--out FILE] [--strict]

``--base`` defaults to the HTML file's directory; ``--out`` defaults to editing in
place; ``--strict`` exits non-zero if any local image cannot be read.
"""
import argparse
import base64
import os
import re
import sys
import urllib.parse

_MIME = {
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

# Find the REAL src within a single <img ...> tag: the tag body is tokenized as bare chars
# OR whole quoted strings so a "src=" inside another attribute's quoted value (e.g. alt) is
# skipped, and (?<![\w-]) avoids matching data-src / other *-src attributes. Group 3 is the
# src value, group 2 its quote. Only <img src> is inlined - srcset and SVG <image xlink:href>
# are intentionally out of scope for this build tool.
_IMG_SRC_RE = re.compile(
    r'''(<img\b(?:[^>"']|"[^"]*"|'[^']*')*?(?<![\w-])src\s*=\s*)(["'])(.*?)\2''',
    re.IGNORECASE)

# One left-to-right scan: a raw-text block (script/style/textarea, closing tag optional at
# EOF so a malformed unclosed block still protects the rest) OR a whole <img ...> start tag.
# Only the img branch is rewritten, so an <img> is never split across a protected region and
# an "<img ...>" appearing as a string literal inside a raw-text block is left alone. <pre>
# and <code> are NOT protected: their content is normal HTML, so a real <img> there is inlined
# (an escaped code sample reads as "&lt;img&gt;" and never matches the <img> pattern anyway).
_RAW_OR_IMG_RE = re.compile(
    r'''<(?P<raw>script|style|textarea)\b[\s\S]*?(?:</(?P=raw)\s*>|\Z)'''
    r'''|(?P<img><img\b(?:[^>"']|"[^"]*"|'[^']*')*?/?>)''',
    re.IGNORECASE)


def _is_local(src):
    """True for a relative local path, False for a scheme (http:, C:), a leading / or \\, // or #."""
    s = src.strip()
    return bool(s) and re.match(r'^(?:[a-zA-Z][a-zA-Z0-9+.\-]*:|[/\\]|#)', s) is None


def inline_images(html, base_dir):
    """Return ``(new_html, inlined_count, missing_list)``."""
    stats = {"inlined": 0, "missing": []}
    # realpath (not abspath) so the containment guard survives symlinks: both the base
    # and the resolved target are canonicalized, so an <img src> that only stays "under"
    # base_dir textually but escapes it via a symlink is still rejected.
    base_abs = os.path.realpath(base_dir)

    def src_repl(match):
        pre, quote, src = match.group(1), match.group(2), match.group(3)
        if not _is_local(src):
            return match.group(0)
        # Drop any URL query/fragment and percent-decode before the filesystem lookup.
        clean = re.split(r'[?#]', src, maxsplit=1)[0]
        try:
            clean = urllib.parse.unquote(clean)
        except Exception:
            pass
        path = os.path.realpath(os.path.join(base_abs, clean))
        # Refuse to read outside the base directory (e.g. src="../../secret.png"): a
        # build tool should only inline images that live under the intended tree.
        if path != base_abs and not path.startswith(base_abs + os.sep):
            stats["missing"].append(src)
            return match.group(0)
        ext = os.path.splitext(path)[1].lower()
        mime = _MIME.get(ext)
        if not mime or not os.path.isfile(path):
            stats["missing"].append(src)
            return match.group(0)
        with open(path, "rb") as fh:
            data = base64.b64encode(fh.read()).decode("ascii")
        stats["inlined"] += 1
        return pre + quote + "data:" + mime + ";base64," + data + quote

    def scan(match):
        if match.group("img") is None:
            return match.group(0)  # raw-text block: leave verbatim
        return _IMG_SRC_RE.sub(src_repl, match.group("img"), count=1)

    return (_RAW_OR_IMG_RE.sub(scan, html), stats["inlined"], stats["missing"])


def main(argv=None):
    parser = argparse.ArgumentParser(description="Inline local <img src> files as data: URIs.")
    parser.add_argument("html", help="HTML file to process")
    parser.add_argument("--base", help="base dir for relative src (default: the HTML file's dir)")
    parser.add_argument("--out", help="output file (default: edit in place)")
    parser.add_argument("--strict", action="store_true", help="exit non-zero if any local image is missing")
    args = parser.parse_args(argv)

    try:
        with open(args.html, encoding="utf-8") as fh:
            html = fh.read()
    except OSError as exc:
        sys.stderr.write("inline_images: cannot read %s: %s\n" % (args.html, exc))
        return 1
    base = args.base or os.path.dirname(os.path.abspath(args.html))
    out, inlined, missing = inline_images(html, base)
    if missing and args.strict:
        sys.stderr.write("inline_images: missing local image(s): %s\n" % ", ".join(missing))
        return 2
    dest = args.out or args.html
    with open(dest, "w", encoding="utf-8", newline="") as fh:
        fh.write(out)
    print("inline_images: inlined %d image(s), %d missing -> %s" % (inlined, len(missing), dest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
