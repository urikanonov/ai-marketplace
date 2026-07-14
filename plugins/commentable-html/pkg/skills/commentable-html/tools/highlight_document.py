#!/usr/bin/env python3
"""Bake syntax highlighting into every un-highlighted code block of a commentable-html document.

Finds each `<pre><code class="language-XXX">` block whose XXX is a language `tools/highlight_code.py`
supports (aliases resolved, e.g. cs -> csharp) and whose inner is still RAW - no `cmh-code-*` spans
and no HTML tags - and rewrites the inner through the highlighter so the block ships highlighted
instead of as plain monochrome text. This is the one-pass, author-time way to prevent a code block
that was labelled with a language but never highlighted.

Idempotent and conservative: an already-highlighted block, a non-highlightable label
(`language-text`, `language-kusto`, ...), an inline `<code>` in prose, and a block that already
carries markup are all left untouched.

Usage (run from the skill root):
    python tools/highlight_document.py file.html            # rewrite in place
    python tools/highlight_document.py --check file.html    # exit 1 if any block needs highlighting
    python tools/highlight_document.py -                    # read stdin, write highlighted HTML to stdout
"""
import argparse
import html as _html
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import highlight_code  # noqa: E402

# A block code element: <pre ...><code ...>INNER</code></pre> (optional whitespace between tags).
_PRE_CODE_RE = re.compile(r"(<pre\b[^>]*>\s*<code\b([^>]*)>)(.*?)(</code>\s*</pre>)",
                          re.DOTALL | re.IGNORECASE)
_LANG_RE = re.compile(r"(?:^|\s)language-([\w#+.\-]+)", re.IGNORECASE)
# The start of a real HTML tag inside the inner (an escaped &lt; never matches).
_TAG_RE = re.compile(r"<[a-zA-Z/!]")
_CLASS_RE = re.compile(r"""\bclass\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+))""", re.IGNORECASE)


def _lang(code_attrs):
    m = _CLASS_RE.search(code_attrs or "")
    if not m:
        return None
    value = next((g for g in m.groups() if g is not None), "")
    for token in value.split():
        if token.lower().startswith("language-"):
            return token[len("language-"):]
    return None


def highlight_document(html):
    """Return (new_html, count) with every raw, highlightable code block highlighted in place."""
    counter = [0]

    def repl(m):
        open_tag, code_attrs, inner, close_tag = m.group(1), m.group(2), m.group(3), m.group(4)
        raw_lang = _lang(code_attrs)
        if not raw_lang:
            return m.group(0)
        lang = highlight_code._normalize_language(raw_lang)
        if lang not in highlight_code.LANGUAGE_CONFIGS:
            return m.group(0)  # not a highlightable language (text, kusto, an unknown label)
        if "cmh-code-" in inner or _TAG_RE.search(inner):
            return m.group(0)  # already highlighted or carries markup - leave it alone
        if not inner.strip():
            return m.group(0)
        code = _html.unescape(inner)
        highlighted = highlight_code.highlight_code(lang, code)
        counter[0] += 1
        return open_tag + highlighted + close_tag

    return _PRE_CODE_RE.sub(repl, html), counter[0]


def _read(path):
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def _write(path, text):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)
    parser = argparse.ArgumentParser(
        prog="highlight_document.py",
        description="Bake syntax highlighting into raw, language-labelled code blocks.")
    parser.add_argument("file", help='HTML file to highlight in place, or "-" for stdin -> stdout')
    parser.add_argument("--check", action="store_true",
                        help="do not write; exit 1 if any block needs highlighting")
    args = parser.parse_args(argv[1:])

    if args.file == "-":
        out, count = highlight_document(sys.stdin.read())
        if args.check:
            sys.stderr.write("highlight_document: %d block(s) need highlighting\n" % count)
            return 1 if count else 0
        sys.stdout.write(out)
        return 0

    if not os.path.exists(args.file):
        sys.stderr.write("highlight_document: file not found: %s\n" % args.file)
        return 2

    source = _read(args.file)
    out, count = highlight_document(source)
    if args.check:
        if count:
            sys.stderr.write("highlight_document: %d code block(s) are not highlighted in %s "
                             "- run: python tools/highlight_document.py %s\n"
                             % (count, args.file, args.file))
            return 1
        print("highlight_document: all code blocks are highlighted")
        return 0
    if out != source:
        _write(args.file, out)
    print("highlight_document: highlighted %d code block(s)" % count)
    return 0


if __name__ == "__main__":
    sys.exit(main())
