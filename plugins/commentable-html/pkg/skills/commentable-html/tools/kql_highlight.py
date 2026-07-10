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
import html as _html
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kusto_link  # noqa: E402

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


def _esc(text):
    return _html.escape(text, quote=False)


def _span(cls, text):
    return '<span class="%s">%s</span>' % (cls, _esc(text))


def highlight_inner(query):
    """Return the query as HTML with token spans (no <pre>/<code> wrapper).

    `textContent` of the result equals the original query (with line endings
    normalized to LF), so the code stays faithful for selection, commenting, and
    the Copy bundle.
    """
    src = query.replace("\r\n", "\n").replace("\r", "\n")
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
            is_call = src[m.end():].lstrip(" \t")[:1] == "("
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


def render_code(query):
    """Return a highlighted `<pre><code class="language-kusto">...</code></pre>` block."""
    return '<pre><code class="language-kusto">%s</code></pre>' % highlight_inner(query)


def render_block(cluster, database, title, query):
    """Return the full `<figure class="cmh-kql">` with caption, Run in Azure Data Explorer link, and
    highlighted code - the complete Kusto-query-block the convention calls for. The
    caption title (cluster / database) is itself the click-to-copy affordance for the
    cluster name."""
    href = _html.escape(kusto_link.kusto_link(cluster, database, query), quote=True)
    cluster_attr = _html.escape(cluster, quote=True)
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
    ) % (cluster_attr, cluster_attr, _html.escape(title), href, render_code(query))


def _usage():
    sys.stderr.write(
        "usage: python tools/kql_highlight.py <cluster> <database> <title> [query]\n"
        "       python tools/kql_highlight.py --code-only [query]\n"
        "       the query is read from stdin when its argument is omitted;\n"
        "       quote a multi-word query so it arrives as one argument.\n")
    return 2


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    flags = {a for a in argv[1:] if a.startswith("--")}
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
        print(render_code(query))
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
