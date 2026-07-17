#!/usr/bin/env python3
"""Add class="cm-skip" to bare <pre class="mermaid"> blocks that lack it.

This is the one unambiguous slice of the retrofit "cm-skip tagging" step (see
SKILL.md Step 3 and references/mermaid-diagrams.md): the ONLY <pre> that needs
cm-skip is <pre class="mermaid"> (the mermaid layer attaches independently via
the `mermaid` class, so its source text must be excluded from the selection
layer). A normal <pre> or <pre><code> code block must NEVER get cm-skip - code
blocks are commentable by default. validate.py's own mermaid-block check (the
"a mermaid block is missing class \"cm-skip\"" warning) detects this exact
condition; this tool reuses the same html.parser-based approach so a decoy
`mermaid` class inside a comment, a <script>/<style> body, or a quoted
attribute string is never mistaken for a real <pre> and is not falsely fixed.

Usage:
    python tools/fix_skip.py <file.html>            # fix in place
    python tools/fix_skip.py <file.html> --check     # report only, exit 1 if any missing
    python tools/fix_skip.py <file.html> --out FILE  # write the fixed doc elsewhere

Exit code 0 on success (including "nothing to fix"), 1 on error or (with
--check) when at least one mermaid block is missing cm-skip.
"""
import argparse
import os
import re
import sys
from html.parser import HTMLParser

# Attribute-token matcher for editing an already-located <pre ...> start tag's
# source text in place: name, then an optional ="quoted"/'quoted'/bare value.
_ATTR_RE = re.compile(r'([^\s"\'>/=]+)(\s*=\s*("[^"]*"|\'[^\']*\'|[^\s>]+))?')


class _MermaidPreLocator(HTMLParser):
    """Locate real <pre class="mermaid"> start tags missing cm-skip.

    Only tags the tolerant HTML parser itself resolves as real start tags are
    considered, so a `mermaid` class written inside an HTML comment, inside a
    <script>/<style> body, or inside a quoted attribute string never counts.
    """

    def __init__(self, html):
        super().__init__(convert_charrefs=False)
        self._offsets = [0]
        for m in re.finditer("\n", html):
            self._offsets.append(m.end())
        self.spans = []  # (start, end) char offsets of each tag needing the fix

    def _idx(self):
        lineno, col = self.getpos()
        return self._offsets[lineno - 1] + col

    @staticmethod
    def _attrs_dict(attrs):
        # HTML5 keeps the FIRST occurrence of a duplicated attribute.
        d = {}
        for k, v in attrs:
            kl = (k or "").lower()
            if kl not in d:
                d[kl] = v if v is not None else ""
        return d

    def _check(self, tag, attrs):
        if tag.lower() != "pre":
            return
        ad = self._attrs_dict(attrs)
        classes = set((ad.get("class") or "").split())
        if "mermaid" in classes and "cm-skip" not in classes:
            start = self._idx()
            text = self.get_starttag_text()
            self.spans.append((start, start + len(text)))

    def handle_starttag(self, tag, attrs):
        self._check(tag, attrs)

    def handle_startendtag(self, tag, attrs):
        self._check(tag, attrs)


def _add_cm_skip(tag_text):
    """Append 'cm-skip' to the class attribute value inside a <pre ...> tag's
    raw source text, preserving quote style, attribute order, and every other
    attribute untouched."""
    matches = list(_ATTR_RE.finditer(tag_text))
    for m in matches[1:]:  # matches[0] is the tag name token itself
        if m.group(1).lower() != "class" or m.group(3) is None:
            continue
        value_tok = m.group(3)
        if value_tok[0] in "\"'":
            quote = value_tok[0]
            new_tok = quote + value_tok[1:-1] + " cm-skip" + quote
        else:
            new_tok = '"' + value_tok + ' cm-skip"'
        start, end = m.span(3)
        return tag_text[:start] + new_tok + tag_text[end:]
    return tag_text  # no class attribute found; caller already verified one exists


def fix(html):
    """Add cm-skip to every real <pre class="mermaid"> block missing it.

    Returns (new_html, count_fixed). Byte-for-byte identical to the input
    except for the class-attribute edits; idempotent when re-run.
    """
    locator = _MermaidPreLocator(html)
    try:
        locator.feed(html)
        locator.close()
    except Exception:
        pass
    if not locator.spans:
        return html, 0
    out = []
    pos = 0
    for start, end in locator.spans:
        out.append(html[pos:start])
        out.append(_add_cm_skip(html[start:end]))
        pos = end
    out.append(html[pos:])
    return "".join(out), len(locator.spans)


def main(argv):
    parser = argparse.ArgumentParser(
        prog="fix_skip.py",
        description='Add class="cm-skip" to bare <pre class="mermaid"> blocks that lack it.',
    )
    parser.add_argument("file", help="the .html file to fix")
    parser.add_argument("--check", action="store_true",
                         help="report the count missing cm-skip and exit 1 if any, without writing")
    parser.add_argument("--out", metavar="FILE", help="write the fixed document to FILE instead of in place")
    args = parser.parse_args(argv[1:])

    if not os.path.exists(args.file):
        sys.stderr.write("fix_skip: file not found: %s\n" % args.file)
        return 1
    try:
        with open(args.file, "r", encoding="utf-8", newline="") as fh:
            html = fh.read()
    except OSError as exc:
        sys.stderr.write("fix_skip: %s\n" % exc)
        return 1

    new_html, count = fix(html)

    if args.check:
        if count:
            print("%d mermaid block(s) missing cm-skip in %s" % (count, args.file))
            return 1
        print("no mermaid blocks missing cm-skip in %s" % args.file)
        return 0

    out_path = args.out if args.out else args.file
    if count:
        with open(out_path, "w", encoding="utf-8", newline="") as fh:
            fh.write(new_html)
        print("fixed %d mermaid block(s) in %s" % (count, out_path))
    elif args.out:
        with open(out_path, "w", encoding="utf-8", newline="") as fh:
            fh.write(new_html)
        print("no mermaid blocks missing cm-skip in %s" % args.file)
    else:
        print("no mermaid blocks missing cm-skip in %s" % args.file)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
