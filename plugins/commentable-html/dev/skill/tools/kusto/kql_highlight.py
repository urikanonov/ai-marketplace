#!/usr/bin/env python3
"""Author-time KQL syntax highlighter for commentable-html reports.

A commentable report is static and self-contained, so highlighting is baked in at author
time (rather than by a runtime script that would have to coexist with the comment
layer). This tokenizes a KQL query and wraps keywords, functions, strings, numbers,
comments, and operators in escaped `<span class="cmh-kql-...">` tags. The result is
placed inside a normal `<pre><code class="language-kusto">` block, so:

- The token spans only add structure - `textContent` is the original query (with
  line endings normalized to LF), so selecting/commenting on the code and the Copy
  bundle still see raw KQL.
- Every character is HTML-escaped, so a query containing markup cannot inject HTML.

The layer CSS (`.cmh-kql`, `.cmh-kql-*`) styles the frame and token colors, so no
per-report CSS is needed. `render_block` also emits the adjacent "Run in Azure Data Explorer"
deep link (via kusto_link), producing the full figure the convention calls for.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tools/ root
import _toolpath  # noqa: E402
_toolpath.ensure()
import _browser_attrs  # noqa: E402
import kusto_link  # noqa: E402
import _highlight_core as _core  # noqa: E402
from urllib.parse import unquote, urlsplit  # noqa: E402

# KQL query/tabular operators and control keywords (lowercased). Hyphenated forms
# (mv-expand, project-away, ...) are matched whole by the identifier rule below.
KEYWORDS = frozenset("""
and as asc between by consume contains contains_cs count desc distinct evaluate
extend facet find fork from getschema has has_any has_cs hasprefix hassuffix hint
in invoke join kind let limit lookup make-series materialize matches mv-apply
mv-expand notcontains nulls of on or order parse parse-where partition print
project project-away project-keep project-rename project-reorder range regex
render sample sample-distinct search serialize set sort startswith step summarize
take to top top-nested typeof union where with
""".split())

# A modest set of built-in functions; any identifier immediately followed by '('
# is also treated as a function call, so this is only a fallback.
FUNCTIONS = frozenset("""
abs ago array_concat array_length array_slice avg avgif bin case coalesce count
countif dcount dcountif endofday endofmonth endofweek endofyear extract extract_all
floor format_datetime gettype iff iif isempty isnotempty isnotnull isnull make_bag
make_list make_set max maxif min minif now pack pack_array parse_json percentile
percentiles pow replace round split startofday startofmonth startofweek startofyear
stdev strcat strcat_delim strlen substring sum sumif tobool todatetime todouble
toint tolong tolower toreal toscalar tostring totimespan toupper trim variance
""".split())

# Hyphenated KQL operators (mv-expand, project-away, ...) are matched as whole
# tokens BEFORE the plain identifier rule, so a bare `a-b` subtraction is tokenized
# as ident/op/ident rather than being swallowed into one identifier.
_HYPHENATED = sorted((k for k in KEYWORDS if "-" in k), key=len, reverse=True)
_HKW_PAT = "|".join(re.escape(k) for k in _HYPHENATED)

_TOKEN_RE = re.compile(r"""
    (?P<com>//[^\n]*)
  | (?P<str>@"(?:[^"]|"")*"|@'(?:[^']|'')*'|"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')
  | (?P<num>\b\d[\w.]*\b)
  | (?P<hkw>(?:%s)\b)
  | (?P<ident>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<pipe>\|)
  | (?P<op>[=!<>+\-*/%%(){}\[\],.;:~])
  | (?P<ws>\s+)
  | (?P<other>.)
""" % _HKW_PAT, re.VERBOSE | re.DOTALL | re.IGNORECASE)


_esc = _core.esc

# Bounded call lookahead (see highlight_inner): spaces/tabs then an open paren.
_CALL_AHEAD_RE = re.compile(r"[ \t]*\(")


def _span(cls, text):
    return _core.span(cls, text)


def highlight_inner(query):
    """Return the query as HTML with token spans (no <pre>/<code> wrapper).

    `textContent` of the result equals the original query (with line endings
    normalized to LF), so the code stays faithful for selection, commenting, and
    the Copy bundle.
    """
    src = _core.normalize_newlines(query)
    out = []
    for m in _TOKEN_RE.finditer(src):
        kind = m.lastgroup
        text = m.group()
        if kind == "com":
            out.append(_span("cmh-kql-com", text))
        elif kind == "str":
            out.append(_span("cmh-kql-str", text))
        elif kind == "num":
            out.append(_span("cmh-kql-num", text))
        elif kind == "hkw":
            out.append(_span("cmh-kql-kw", text))
        elif kind == "pipe":
            out.append(_span("cmh-kql-op", text))
        elif kind == "ident":
            low = text.lower()
            # Look AHEAD with a bounded regex instead of slicing the whole tail on every
            # identifier: `src[m.end():]` copied the rest of the query per token, which is
            # quadratic on a large one. `[ \t]*` (not `\s*`) keeps the exact old semantics -
            # a newline before the paren is NOT a call - so the golden output is unchanged.
            is_call = _CALL_AHEAD_RE.match(src, m.end()) is not None
            if low in KEYWORDS:
                out.append(_span("cmh-kql-kw", text))
            elif is_call or low in FUNCTIONS:
                out.append(_span("cmh-kql-fn", text))
            else:
                out.append(_esc(text))
        elif kind == "op":
            out.append(_span("cmh-kql-op", text))
        else:  # ws / other
            out.append(_esc(text))
    return "".join(out)


def render_code(query, no_cluster=False):
    """Return a highlighted `<pre><code class="language-kusto">...</code></pre>` block.

    Pass no_cluster=True to stamp the `data-cmh-kql-no-cluster` marker on the `<pre>` - the explicit
    metadata override the validator requires for a bare (unframed, non-runnable) KQL block. Prefer a
    full runnable figure (render_block) with a real cluster; use this only when there is genuinely no
    cluster to run the query on."""
    pre_attrs = " data-cmh-kql-no-cluster" if no_cluster else ""
    return '<pre%s><code class="language-kusto">%s</code></pre>' % (pre_attrs, highlight_inner(query))


def render_block(cluster, database, title, query):
    """Return the full `<figure class="cmh-kql">` with caption, Run in Azure Data Explorer link, and
    highlighted code - the complete Kusto-query-block the convention calls for. The
    caption title (cluster / database) is itself the click-to-copy affordance for the
    cluster name."""
    href = _browser_attrs.escape_attr_value(kusto_link.kusto_link(cluster, database, query))
    # `escape_attr_value` / `escape_text`, not `html.escape`: a CR written literally is folded to
    # LF by input-stream preprocessing before a browser tokenizes, in an ATTRIBUTE and in TEXT
    # alike, so either value carrying one would be emitted as something the rendered DOM never
    # has (#1196, #1224). Both halves are needed because this caption writes TWO generated
    # values into one element - `cluster` into `data-cmh-copy` and the `title` argument as the
    # button's visible label - and before this each half had a different rule.
    cluster_attr = _browser_attrs.escape_attr_value(cluster)
    return (
        '<figure class="cmh-kql">\n'
        '<figcaption class="cm-skip cmh-kql-cap">'
        '<button type="button" class="cmh-kql-title cmh-kql-cluster cm-skip" data-cmh-copy="%s" '
        'title="Copy cluster name (%s) to the clipboard">%s</button>'
        '<a class="cmh-kql-run" href="%s" target="_blank" rel="noopener noreferrer">'
        'Run in Azure Data Explorer &#9654;</a>'
        '</figcaption>\n'
        '%s\n'
        '</figure>'
    ) % (cluster_attr, cluster_attr, _browser_attrs.escape_text(title), href, render_code(query))


# An `<a>` START TAG with its raw attributes. The tag name is terminated the way HTML terminates
# one (ASCII whitespace, `/` or `>`), NOT by a `\b` word boundary: `\b` is satisfied by the `-` in
# `<a-run>`, so a custom element would have been read as an anchor and RE-SERIALIZED as `<a>` -
# markup the author never wrote, while the real run link kept its pre-edit query. The attribute
# region is QUOTE-AWARE, so a `>` inside a quoted value cannot truncate the tag before its class.
_A_TAG_RE = re.compile(r"""<a(?![^\t\n\f\r />])((?:"[^"]*"|'[^']*'|[^>"'])*)>""", re.IGNORECASE)
# The figure's `<pre><code>` block, matched exactly as `authoring/content_extract.py` matches one
# (`_PRE_CODE_RE`, pinned to it by `test_the_code_block_pattern_matches_content_extracts`), so the
# tool that READS a block's source and the tool that REWRITES it can never disagree about what a
# code block is. Both tag names are terminated the way HTML terminates one, for the same reason
# `_A_TAG_RE` above is: a `\b` is satisfied by the `-` in `<pre-run>` / `<code-run>`, so a
# KQL-labelled custom-element decoy was read as the figure's code block.
_CODE_INNER_RE = re.compile(
    r"""(<pre(?![^\t\n\f\r />])(?:"[^"]*"|'[^']*'|[^>"'])*>\s*<code(?![^\t\n\f\r />])((?:"[^"]*"|'[^']*'|[^>"'])*)>)"""
    r"""(.*?)(</code>\s*</pre>)""", re.DOTALL | re.IGNORECASE)

# The kusto labels the document highlight path dispatches to this tokenizer (CMH-KQL-09), so a
# figure the validator reads as KQL is one this rewriter can rebuild. Kept local rather than
# imported from `blocks/highlight_document.py`, which imports this module.
_KQL_LABELS = frozenset(("kusto", "kql"))


def is_kusto_code(code_attrs):
    """Whether a `<code>` start tag carries a KQL `language-` label.

    The ORDERED shared class-token reading (CMH-VAL-21 clause 11) with an ASCII-only fold, the
    same one `content_extract._language` and the validator's `_code_block_language` use. A literal
    `class="[^"]*language-kusto[^"]*"` substring both over-matched (`language-kustomize` is not
    kusto) and, being double-quote only, never saw a single-quoted or unquoted label at all.

    Public because `content_replace` must pick the block it takes a figure's SOURCE from by the
    same test this module rewrites by; picking the first block of ANY language wrote a neighbouring
    block's text over the KQL query.
    """
    for token in _browser_attrs.raw_attrs_class_tokens(code_attrs):
        label = _browser_attrs.ascii_lower(token)
        if label.startswith("language-"):
            return label[len("language-"):] in _KQL_LABELS
    return False


def find_kusto_code(html, spans=None):
    """The first LIVE KQL code block in `html` as a match of `_CODE_INNER_RE`, or None.

    A rejected block restarts the scan just past its `<code ...>` open tag rather than past its
    whole match: a non-KQL block whose closer this pattern does not recognize
    (`</code></pre >`) otherwise ran its non-greedy body on to the NEXT `</code></pre>`,
    swallowing the real KQL block, and resuming past the match stepped over it - so the figure
    kept its pre-edit query. Restarting inside the rejected open tag cannot step over a block the
    rejected body swallowed, since such a block begins after that tag.
    """
    html = html or ""
    spans = _browser_attrs.inert_spans(html) if spans is None else spans
    pos = 0
    while True:
        m = _CODE_INNER_RE.search(html, pos)
        if m is None:
            return None
        if not _browser_attrs.in_inert_span(m.start(), spans) and is_kusto_code(m.group(2)):
            return m
        pos = max(m.start() + 1, m.end(1))


def _find_run_links(figure_html, spans):
    """Every LIVE Run link in the figure, as start-tag matches, in document order.

    The links are located by the class-TOKEN reading the VALIDATOR uses (CMH-KQL-05/07, through
    the shared `class_tokens` of CMH-VAL-21 clause 11), never by the literal
    `<a class="cmh-kql-run" href="` spelling: that only saw a run link whose class attribute was
    exactly that one token, double-quoted, and written before `href`, so a validator-clean figure
    written any other way was invisible here and silently kept its PRE-EDIT query (#1160).

    EVERY one of them, not just the first: the validator's 11d gate accepts a figure with more
    than one run link and checks them all, so refreshing only the first left the others executing
    the pre-edit query - the same defect one anchor along. A match inside an INERT region (an HTML
    comment, a raw-text body) is skipped, because the validator's anchors come from a real parse
    and a commented-out link is not one: rewriting the decoy and reporting success left the live
    link stale.
    """
    return [m for m in _A_TAG_RE.finditer(figure_html)
            if not _browser_attrs.in_inert_span(m.start(), spans)
            and _browser_attrs.attrs_have_class(m.group(1), "cmh-kql-run")]


def _adx_target(href):
    """The `(cluster, database)` an ADX deep link names, or None when it is not one."""
    if href is None:
        return None
    parts = urlsplit(href)
    path = parts.path.strip("/").split("/")
    if len(path) < 4 or "query=" not in parts.query:
        return None
    return unquote(path[1]), unquote(path[3])


def _run_link_tag(pairs, href):
    """The run link's start tag RE-SERIALIZED from its parsed attributes, carrying `href`.

    Re-serializing (rather than substituting over the raw text) is what lets the rewriter accept
    every shape the validator accepts: the attributes are located by parsing, so an `href` spelled
    inside another attribute's quoted value is never the one rewritten. Each value is escaped
    exactly once from its DECODED form, so the canonical figure this tool emits round-trips byte
    for byte. A HAND-WRITTEN link is NORMALIZED instead: the tag and attribute names fold to ASCII
    lower case, every value comes back double-quoted and re-escaped from its decoded form, a
    trailing self-closing `/` (which HTML ignores on an `<a>`) is dropped, and a DUPLICATED
    attribute keeps only its first occurrence - all of it the view a browser already has, none of
    it byte-preserving. Dropping the duplicate matters most for `href`: a browser reads the first,
    so a second one would sit in the file still encoding the pre-edit query.

    `pairs` always carries an `href` here: `refresh_block` reads and validates that href before it
    decides to rebuild the link at all, and skips the link when there is none.

    The tag is written by the shared re-serializer, so a VALUELESS attribute comes back as
    `name=""` rather than as a bare name: the bare name drops the `/` HTML uses to terminate an
    attribute name, and the next attribute - whose name legally begins with `=` - fused into it
    and gained a value the authored figure never had (#1195).
    """
    out, seen = [], set()
    for name, value in pairs:
        if name in seen:
            continue
        seen.add(name)
        if name == "href":
            value = href
        out.append((name, value))
    return _browser_attrs.serialize_start_tag("a", out)


def refresh_block(figure_html, query):
    """Return `figure_html` with BOTH its code and its Run link rebuilt for `query`.

    The Run in Azure Data Explorer link encodes the query INSIDE its href, so
    re-highlighting only the `<code>` inner would leave the button executing the
    pre-edit text - silently, since nothing validates the payload. The cluster and
    database are recovered from the existing link, so the caption, the copy affordance
    and the frame are preserved exactly.

    Raises ValueError when the figure carries no readable Run link or code block. Every edit is
    located on the INPUT and applied last, in descending order, so one rewrite cannot shift the
    offsets another was found at - which holds only while the edits are DISJOINT, so an anchor
    written inside the code block's own body is content this rewrites past, not a control to
    rebuild.
    """
    figure_html = figure_html or ""
    spans = _browser_attrs.inert_spans(figure_html)
    code = find_kusto_code(figure_html, spans)
    links = [m for m in _find_run_links(figure_html, spans)
             if code is None or m.end() <= code.start(3) or m.start() >= code.end(3)]
    if not links:
        raise ValueError("no cmh-kql-run link found: not a runnable KQL figure")
    edits = []
    for m in links:
        pairs = _browser_attrs.raw_attrs_pairs(m.group(1))
        target = _adx_target(next((v for n, v in pairs if n == "href"), None))
        if target is None:
            continue  # not a runnable ADX link: the validator's own gate reports that one
        href = kusto_link.kusto_link(target[0], target[1], query)
        edits.append((m.start(), m.end(), _run_link_tag(pairs, href)))
    if not edits:
        raise ValueError("the Run link is not a recognizable ADX deep link")
    if code is None:
        raise ValueError("no language-kusto code block found in the figure")
    edits.append((code.start(3), code.end(3), highlight_inner(query)))
    out = figure_html
    for start, end, text in sorted(edits, reverse=True):
        out = out[:start] + text + out[end:]
    return out


def _usage():
    sys.stderr.write(
        "usage: python tools/kql_highlight.py <cluster> <database> <title> [query]\n"
        "       python tools/kql_highlight.py --code-only [query]\n"
        "       the query is read from stdin when its argument is omitted;\n"
        "       quote a multi-word query so it arrives as one argument.\n")
    return 2


def _wants_help(tokens):
    # Honor -h/--help only before an end-of-options "--"; a -h AFTER "--" is a data value.
    for t in tokens:
        if t == "--":
            return False
        if t in ("-h", "--help"):
            return True
    return False


def main(argv):
    raw = argv[1:]
    if _wants_help(raw):
        sys.stdout.write(
            "usage: python tools/kql_highlight.py <cluster> <database> <title> [query]\n"
            "       python tools/kql_highlight.py --code-only [query]\n"
            "       the query is read from stdin when its argument is omitted;\n"
            "       quote a multi-word query so it arrives as one argument.\n")
        return 0
    # Support a "--" end-of-flags separator (standard CLI convention) so a positional
    # value that begins with "--" can still be passed - everything after a bare "--" is
    # positional, even if it looks like a flag.
    if "--" in raw:
        sep = raw.index("--")
        before, after = raw[:sep], raw[sep + 1:]
    else:
        before, after = raw, []
    args = [a for a in before if not a.startswith("--")] + after
    flags = {a for a in before if a.startswith("--")}
    if flags - {"--code-only"}:
        sys.stderr.write("kql_highlight: unknown flag(s): %s\n" % ", ".join(sorted(flags - {"--code-only"})))
        return _usage()
    if "--code-only" in flags:
        if len(args) > 1:
            return _usage()
        query = args[0] if args else sys.stdin.buffer.read().decode("utf-8", errors="replace")
        query = query.rstrip("\r\n")
        if not query.strip():
            sys.stderr.write("kql_highlight: empty query\n")
            return 2
        print(render_code(query, no_cluster=True))
        return 0
    if len(args) < 3 or len(args) > 4:
        return _usage()
    cluster, database, title = args[0], args[1], args[2]
    query = args[3] if len(args) > 3 else sys.stdin.buffer.read().decode("utf-8", errors="replace")
    query = query.rstrip("\r\n")
    try:
        print(render_block(cluster, database, title, query))
    except ValueError as exc:
        sys.stderr.write("kql_highlight: %s\n" % exc)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
