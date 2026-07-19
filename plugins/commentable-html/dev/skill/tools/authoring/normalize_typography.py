#!/usr/bin/env python3
"""Rewrite AI "smart" typography to plain ASCII in a commentable-html document's PROSE.

AI-authored content routinely substitutes em/en dashes, an ellipsis glyph, curly quotes, and a
non-breaking space for their plain-ASCII equivalents, which violate the repo's ASCII-only house
style (see scripts/validate_markdown.py, whose AI_CHARACTERS map this mirrors). The document
producers run this as a deterministic build/export step so every report, plan, and deck is emitted
clean without a hand pass.

Only visible PROSE text is rewritten. VERBATIM regions - `<script>` (the layer JS and its embedded
comment / handled-id JSON), `<style>`, `<pre>` (code/diff/kql blocks), inline `<code>`, and HTML
comments - are left byte-for-byte untouched, so machine data, code samples, and reviewer-typed
comment text are never corrupted. Tag markup (element names and attributes) is skipped too; only the
text BETWEEN tags is normalized.

Usage (run from the skill root):
    python tools/authoring/normalize_typography.py file.html          # rewrite in place
    python tools/authoring/normalize_typography.py file.html --check   # report only, exit 1 if any
    python tools/authoring/normalize_typography.py file.html --out OUT  # write elsewhere

Exit code 0 on success (including "nothing to normalize"), 1 on error or (with --check) when at
least one AI character remains. Pure standard library.
"""
import argparse
import os
import re
import sys
from html.parser import HTMLParser

# Unicode "smart" characters AI tools emit, mapped to their plain-ASCII replacement. Kept as \u
# escapes so this source stays pure ASCII. Mirrors AI_CHARACTERS in scripts/validate_markdown.py; an
# empty replacement removes the character entirely.
AI_CHARACTERS = {
    "\u2014": " - ",   # em-dash
    "\u2013": "-",     # en-dash
    "\u2026": "...",   # horizontal ellipsis
    "\u201C": '"',     # left double quote
    "\u201D": '"',     # right double quote
    "\u2018": "'",     # left single quote
    "\u2019": "'",     # right single quote
    "\u00A0": " ",     # non-breaking space
    "\uFEFF": "",      # zero-width no-break space / BOM
    "\u200B": "",      # zero-width space
}

# Elements whose text content is VERBATIM and must never be normalized: code/data blocks and raw-
# text / inert containers. Protection is tracked by a stack of ONLY these elements (all other tags
# are ignored), so it is O(1) per tag, immune to misnested non-verbatim markup, and fail-closed: an
# unterminated verbatim element keeps everything after it protected rather than rewriting code.
_VERBATIM = frozenset(("script", "style", "pre", "code", "textarea", "template"))

# HTML void elements never take a matching end tag, so a self-closing/void tag never opens content.
_VOID = frozenset((
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
))

# Raw markup whose interior is NOT prose even though Python's HTMLParser can mis-terminate it at a
# quoted ">" and then report the tail as data: HTML comments, CDATA, and (quote-aware) declarations /
# doctypes / processing instructions. Their source ranges are subtracted from the prose spans so a
# ">" inside a quoted doctype/PI can never cause the tail to be rewritten.
_RAW_RE = re.compile(
    r"<!--.*?-->"
    r"|<!\[CDATA\[.*?\]\]>"
    r"|<[!?][^>'\"]*(?:(?:\"[^\"]*\"|'[^']*')[^>'\"]*)*>",
    re.DOTALL,
)


class _ProseSpans(HTMLParser):
    """Collect the exact source spans of PROSE text nodes (data outside any verbatim element).

    Using the standard-library HTML tokenizer instead of a regex makes the scan quote-aware (a `>`
    inside a quoted attribute cannot end a tag), correct for nested verbatim elements, and linear.
    Only the VERBATIM elements drive a small stack; every other tag is ignored, so misnested or
    unmatched non-verbatim markup cannot flip protection and cannot cause an O(n^2) stack scan.
    Attribute values are never emitted as data, so tag markup - including machine-data attributes -
    is left byte-for-byte untouched. Offsets are exact character positions (mirrors wrap_sections)."""

    def __init__(self, html):
        super().__init__(convert_charrefs=False)
        self._offsets = [0]
        for m in re.finditer("\n", html):
            self._offsets.append(m.end())
        self._verbatim = []       # stack of open verbatim element names
        self.spans = []           # [(start, end)] of candidate prose data runs

    def _idx(self):
        lineno, col = self.getpos()
        return self._offsets[lineno - 1] + col

    def _open(self, tag):
        if tag in _VERBATIM:
            self._verbatim.append(tag)

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag not in _VOID:
            self._open(tag)

    def handle_startendtag(self, tag, attrs):
        # HTML ignores a trailing "/" on a non-void element (it is an OPEN tag). A void self-close
        # has no content. So a self-closing verbatim (`<pre/>`, `<code/>`) opens protection, matching
        # the browser, while a void self-close opens nothing.
        tag = tag.lower()
        if tag not in _VOID:
            self._open(tag)

    def handle_endtag(self, tag):
        # Only close the innermost verbatim element when the end tag matches it. An end tag that does
        # not match the top of the verbatim stack (misnested, or a non-verbatim tag) is ignored, so
        # protection is conservative (never dropped early) and never scans a deep stack.
        tag = tag.lower()
        if self._verbatim and self._verbatim[-1] == tag:
            self._verbatim.pop()

    def handle_data(self, data):
        # Only real text nodes reach here (attribute values do not). With convert_charrefs=False a
        # data run is a contiguous source slice of len(data) - entities and tags split it - so its
        # exact source span is [start, start+len(data)].
        if self._verbatim or not data:
            return
        start = self._idx()
        self.spans.append((start, start + len(data)))


def _translit(text):
    """Replace every AI character in a text run. Returns (new_text, count)."""
    count = 0
    for ch, repl in AI_CHARACTERS.items():
        if ch in text:
            count += text.count(ch)
            text = text.replace(ch, repl)
    return text, count


def normalize_text(text):
    """Rewrite AI typography in a PLAIN-TEXT string (not HTML). Returns (new_text, count).

    Use this for values that are literal text and get HTML-escaped later (a document title, a deck
    label), NOT markup - so a stray `<` or `&` is treated as text, not a tag."""
    return _translit(text)


def _raw_ranges(html):
    """Sorted [(start, end)] of raw-markup regions (comments, CDATA, declarations, doctypes, PIs)."""
    return [(m.start(), m.end()) for m in _RAW_RE.finditer(html)]


def normalize_typography(html):
    """Rewrite AI typography to ASCII in the prose text nodes of `html`.

    Returns (new_html, count) where count is the number of AI characters replaced. Byte-for-byte
    identical (count 0) when the document holds none. Idempotent: a second pass replaces nothing.
    Verbatim regions (script/style/pre/code/textarea/template and their descendants), raw markup
    (comments/CDATA/declarations/PIs), and ALL tag markup (element names AND attribute values) are
    left untouched. Fails SAFE: if the markup is too malformed to tokenize, the document is returned
    unchanged rather than risking corruption.

    This is length-changing (em-dash -> " - ", ellipsis -> "...", nbsp -> " ", zero-width -> ""), so
    run it as a PRODUCER step BEFORE a document is first reviewed: normalizing prose after comments
    exist could shift their stored character offsets. It also flattens a legitimately intentional
    non-breaking space; opt out with the caller's --no-normalize when that matters.
    """
    parser = _ProseSpans(html)
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return html, 0
    if not parser.spans:
        return html, 0
    raws = _raw_ranges(html)
    ri = 0

    def _in_raw(pos):
        nonlocal ri
        while ri < len(raws) and raws[ri][1] <= pos:
            ri += 1
        return ri < len(raws) and raws[ri][0] <= pos < raws[ri][1]

    out = []
    total = 0
    pos = 0
    for start, end in parser.spans:
        if start < pos or end > len(html):
            # Offsets should be non-overlapping and in range; bail unchanged if not.
            return html, 0
        out.append(html[pos:start])          # markup / protected verbatim: unchanged
        if _in_raw(start):
            out.append(html[start:end])      # inside a mis-terminated declaration/PI: leave verbatim
        else:
            seg, c = _translit(html[start:end])
            total += c
            out.append(seg)
        pos = end
    out.append(html[pos:])
    if total == 0:
        return html, 0
    return "".join(out), total


def main(argv):
    parser = argparse.ArgumentParser(
        prog="normalize_typography.py",
        description="Rewrite AI smart-typography (em/en dashes, ellipsis, curly quotes, nbsp) to "
                    "plain ASCII in a document's prose, leaving code/script/style/comments verbatim.")
    parser.add_argument("file", help="the .html file to normalize")
    parser.add_argument("--check", action="store_true",
                        help="report the count of AI characters in prose and exit 1 if any, "
                             "without writing")
    parser.add_argument("--out", metavar="FILE",
                        help="write the normalized document to FILE instead of in place")
    args = parser.parse_args(argv[1:])

    if not os.path.exists(args.file):
        sys.stderr.write("normalize_typography: file not found: %s\n" % args.file)
        return 1
    try:
        with open(args.file, "r", encoding="utf-8", newline="") as fh:
            html = fh.read()
    except OSError as exc:
        sys.stderr.write("normalize_typography: %s\n" % exc)
        return 1

    new_html, count = normalize_typography(html)

    if args.check:
        if count:
            print("%d AI character(s) in prose in %s" % (count, args.file))
            return 1
        print("no AI characters in prose in %s" % args.file)
        return 0

    out_path = args.out if args.out else args.file
    if count or args.out:
        try:
            with open(out_path, "w", encoding="utf-8", newline="") as fh:
                fh.write(new_html)
        except OSError as exc:
            sys.stderr.write("normalize_typography: %s\n" % exc)
            return 1
    if count:
        print("normalized %d AI character(s) in %s" % (count, out_path))
    else:
        print("no AI characters to normalize in %s" % args.file)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
