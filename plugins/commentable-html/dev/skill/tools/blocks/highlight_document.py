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
    python tools/blocks/highlight_document.py file.html            # rewrite in place
    python tools/blocks/highlight_document.py --check file.html    # exit 1 if any block needs highlighting
    python tools/blocks/highlight_document.py -                    # read stdin, write highlighted HTML to stdout
"""
import argparse
import html as _html
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tools/ root
import _toolpath  # noqa: E402
import _atomic_io  # noqa: E402
import _browser_attrs  # noqa: E402
_toolpath.ensure()
import highlight_code  # noqa: E402
import kql_highlight  # noqa: E402

# Kusto labels the document path dispatches to the KQL tokenizer.
_KQL_LANGUAGES = frozenset(("kusto", "kql"))

# A block code element: <pre ...><code ...>INNER</code></pre> (optional whitespace between tags).
# The attribute regions are QUOTE-AWARE: a `>` may sit inside a quoted attribute value, and a
# `[^>]*` region truncated `<code title="a>b" class="language-python">` before its class, so the
# block was silently read as unlabelled. Kept byte-identical to `content_extract._PRE_CODE_RE`, so
# the two tools can never disagree about what counts as a highlightable block.
_PRE_CODE_RE = re.compile(
    r"""(<pre\b(?:"[^"]*"|'[^']*'|[^>"'])*>\s*<code\b((?:"[^"]*"|'[^']*'|[^>"'])*)>)"""
    r"""(.*?)(</code>\s*</pre>)""", re.DOTALL | re.IGNORECASE)
# The start of a real HTML tag inside the inner (an escaped &lt; never matches).
_TAG_RE = re.compile(r"<[a-zA-Z/!]")


def _lang(code_attrs):
    """The `language-XXX` label on a <code> tag, read exactly as `content_extract._language` and
    the validator's `checks/highlighting._code_block_language` read it (CMH-VAL-21 clause 11):
    the class list tokenized on ASCII whitespace ONLY, in order, and the label folded ASCII-only.
    """
    for token in _browser_attrs.raw_attrs_class_tokens(code_attrs):
        if _browser_attrs.ascii_lower(token).startswith("language-"):
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
        is_kql = lang in _KQL_LANGUAGES
        if not is_kql and lang not in highlight_code.LANGUAGE_CONFIGS:
            return m.group(0)  # not a highlightable language (text, an unknown label)
        if "cmh-code-" in inner or "cmh-kql-" in inner or _TAG_RE.search(inner):
            return m.group(0)  # already highlighted or carries markup - leave it alone
        if not inner.strip():
            return m.group(0)
        # The SHARED text decode (CMH-VAL-21): `html.unescape` RAISES on an oversized numeric
        # reference (so highlighting a document the validator now reads would crash) and DELETES
        # the code points a browser keeps - and this is the one path that WRITES the decoded text
        # back, so a deletion here is permanent.
        code = _browser_attrs.unescape_text(inner)
        # KQL keeps its own tokenizer and its own cmh-kql-* class vocabulary (bare
        # function names, hyphenated keywords, @"..." strings); only the DISPATCH is
        # shared, so the document path and the KQL tool can never diverge.
        highlighted = (kql_highlight.highlight_inner(code) if is_kql
                       else highlight_code.highlight_code(lang, code))
        counter[0] += 1
        return open_tag + highlighted + close_tag

    return _PRE_CODE_RE.sub(repl, html), counter[0]


def _read(path):
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def _write(path, text):
    _atomic_io.atomic_write(path, text)


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
                             "- run: python tools/blocks/highlight_document.py %s\n"
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
