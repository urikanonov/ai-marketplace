#!/usr/bin/env python3
"""Read just the CONTENT region of a commentable-html document, as editable source.

A generated document is 1.4 - 2.5 MB, of which the CONTENT region - the only part an
agent ever edits - is 0.1 to 1.3 percent. Handing an agent the whole file to change one
paragraph is the dominant cost of the review loop, so this prints ONLY that region.

The fragment stored in the file is FINALIZED output, not authoring source: code blocks
carry `cmh-code-*` / `cmh-kql-*` token spans. Editing span soup by hand is exactly what
an agent does badly, so every block that round-trips losslessly (see
`blocks/_highlight_core.dehighlight`) is handed back as plain source; `content_replace.py`
re-bakes it. A block the inverse REFUSES - hand-written markup inside a `<pre><code>` -
is passed through verbatim instead, so the loop never stalls on the very blocks it exists
to repair, and `content_replace.py` leaves such a block alone.

The region is anchored on the unique CONTENT markers exactly as `new_document.py` does,
so a decoy `<main id="commentRoot">` inside an authoring documentation comment is ignored.

Usage (run from the skill root):
    python tools/authoring/content_extract.py file.html            # print to stdout
    python tools/authoring/content_extract.py file.html --out f.html
"""
import argparse
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tools/ root
import _toolpath  # noqa: E402
_toolpath.ensure()
import _atomic_io  # noqa: E402
import _browser_attrs  # noqa: E402
import _highlight_core as _core  # noqa: E402
import highlight_code  # noqa: E402
import highlight_document  # noqa: E402
import kql_highlight  # noqa: E402
import new_document  # noqa: E402

# A block code element, matched exactly as highlight_document.py matches it so the two
# tools can never disagree about what counts as a highlightable block. The attribute regions are
# QUOTE-AWARE: a `>` may sit inside a quoted attribute value, and a `[^>]*` region truncated
# `<code title="a>b" class="language-python">` before its class, so the block was read as
# unlabelled and left unhighlighted (CMH-VAL-21 clause 11).
_PRE_CODE_RE = re.compile(
    r"""(<pre\b(?:"[^"]*"|'[^']*'|[^>"'])*>\s*<code\b((?:"[^"]*"|'[^']*'|[^>"'])*)>)"""
    r"""(.*?)(</code>\s*</pre>)""", re.DOTALL | re.IGNORECASE)


class ExtractError(Exception):
    """The document does not carry a usable CONTENT region."""


def _language(code_attrs):
    """Return the `language-XXX` label on a <code> tag, or None.

    The ORDERED shared reading (CMH-VAL-21 clause 11) with an ASCII-only fold of the label, so
    this tool and the validator's own `checks/highlighting._code_block_language` read the same
    `<code>` the same way: Python's `str.split()` would additionally split the class list on
    U+000B / NBSP / U+001C-U+001F, and `str.lower()` would map `LANGUAGE-\u212aUSTO` onto a real
    kusto label that no engine on either side reads.
    """
    for token in _browser_attrs.raw_attrs_class_tokens(code_attrs):
        if _browser_attrs.ascii_lower(token).startswith("language-"):
            return token[len("language-"):]
    return None

def _reversible_source(code_attrs, inner):
    """Return the de-highlighted source for a block, or None to leave it stored as is.

    Being able to de-highlight is not enough: the write-back must be able to put the
    block back EXACTLY. Two ways that fails, both of which would silently corrupt the
    document rather than refuse:

    - The label is one `highlight_document.py` does not bake (`language-text`, an
      unknown label), so nothing would re-escape the source.
    - The source contains a `<` immediately followed by a letter - `Array<string>`,
      `vector<int>`, `if x<y:` - which `highlight_document.py` refuses to re-highlight
      because it looks like markup. Extremely common in real code.

    So the test is empirical: re-highlight the de-highlighted source and keep it only if
    that reproduces the stored bytes.
    """
    raw = _language(code_attrs)
    if not raw:
        return None
    lang = highlight_code._normalize_language(raw)
    is_kql = lang in highlight_document._KQL_LANGUAGES
    if not is_kql and lang not in highlight_code.LANGUAGE_CONFIGS:
        return None
    source = _core.dehighlight(inner)
    if source is None:
        return None  # hand written or malformed: never rewrite it
    # The re-bake runs through highlight_document, which SKIPS any block whose inner
    # already looks like markup. Source containing `<` next to a letter therefore never
    # gets re-escaped, so check the real gate, not just the tokenizer.
    if highlight_document._TAG_RE.search(source):
        return None
    rebaked = (kql_highlight.highlight_inner(source) if is_kql
               else highlight_code.highlight_code(lang, source))
    if rebaked != inner:
        return None  # the re-bake would not reproduce this block, so do not touch it
    return source


def content_span(html):
    """Return (start, end) offsets of the fragment between the CONTENT markers."""
    try:
        begin_idx, end_idx, _main_start, _tag_end = new_document._find_active_root(html)
    except ValueError as exc:
        raise ExtractError(str(exc))
    return begin_idx + len(new_document.BEGIN_MARKER), end_idx


def dehighlight_blocks(fragment, refusals=None):
    """Return `fragment` with every VERIFIABLY reversible code block turned into source.

    Pass a list as `refusals` to collect the language labels of blocks handed back as
    stored markup because the inverse refused them (hand-written markup), so a caller can
    tell the agent which blocks are NOT clean source and must be handled by hand.
    """
    def repl(m):
        open_tag, code_attrs, inner, close_tag = m.group(1), m.group(2), m.group(3), m.group(4)
        source = _reversible_source(code_attrs, inner)
        if source is None:
            if refusals is not None and _core.dehighlight(inner) is None:
                refusals.append(_language(code_attrs) or "(unlabelled)")
            return m.group(0)
        return open_tag + source + close_tag

    return _PRE_CODE_RE.sub(repl, fragment)


def extract(html, refusals=None):
    """Return the document's CONTENT fragment as editable source."""
    start, end = content_span(html)
    return dehighlight_blocks(html[start:end], refusals=refusals).strip("\n")


def _read(path):
    with io.open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def main(argv):
    ap = argparse.ArgumentParser(
        description="print the CONTENT region of a commentable-html document as editable source")
    ap.add_argument("file", help="the commentable-html document to read")
    ap.add_argument("--out", help="write to this path instead of stdout")
    args = ap.parse_args(argv)

    refusals = []
    try:
        fragment = extract(_read(args.file), refusals=refusals)
    except (ExtractError, OSError) as exc:
        sys.stderr.write("content_extract: %s\n" % exc)
        return 1

    if refusals:
        sys.stderr.write(
            "content_extract: %d code block(s) carry hand-written markup and were handed "
            "back AS STORED, not as clean source (%s) - edit those by hand and expect "
            "content_replace to leave them untouched\n"
            % (len(refusals), ", ".join(sorted(set(refusals)))))

    if args.out:
        # fallback: the fragment carries the document's own CONTENT region, so a new --out
        # inherits the SOURCE document's visibility rather than the process umask default.
        _atomic_io.atomic_write(args.out, fragment + "\n", fallback=args.file)
        sys.stderr.write("content_extract: wrote %d byte(s) to %s\n"
                         % (len(fragment), args.out))
    else:
        sys.stdout.write(fragment + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
