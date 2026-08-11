#!/usr/bin/env python3
"""Measure what the `class` attribute actually costs in a generated document, and what the ceiling
of every candidate reduction is (CMH-SIZE-04).

Maintainer-only; nothing here ships. It exists so the measurement that closed issue #1267 is
REPRODUCIBLE - re-runnable against any document, including one a user reports as large - instead of
a number quoted once in a spec row and never checkable again.

It reports four things per document:

* what the class attributes occupy, as the bytes they really take up in the source (the separator,
  the attribute name, the `=`, the quotes as written, and the value);
* the CEILING of each candidate reduction. `quote_elision` is EXACT: it is a syntax-only rewrite
  that provably leaves the class VALUE untouched. `rename` and `normalize` are over-estimates -
  they assume the transform is free, always applies, and is sound. `hoist` is the one figure that
  is NOT a bound of either kind: what a hoist can reach depends on the tree shape, so it is an
  OBSERVATION on the parsed tree. The shape-free upper bound on ANY class reduction is the
  delete-every-class-attribute line, which is reported too and exceeds all of them;
* the class-rewrite HAZARDS the document contains - constructs whose presence means a static tool
  cannot prove a class rewrite render-identical, because the tool cannot resolve what they match;
* what the whole class budget is worth once the file is compressed.

Usage (run from anywhere):
    python dev/tools/class_cost.py <document.html> [more.html ...]
    python dev/tools/class_cost.py --json <document.html>
"""
import argparse
import gzip
import html as html_module
import json
import os
import re
import sys
from collections import Counter
from html.parser import HTMLParser

VOID_ELEMENTS = frozenset((
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
))

# Elements a start tag implicitly CLOSES. `html.parser` does no implicit closing, so without this a
# `<li class="row"><li class="row">` pair parses as parent and child rather than as the two
# siblings a browser builds - and the hoist figure, which is entirely about siblings, reads far too
# low on exactly the row-heavy markup the 1725-row document behind this question is made of.
BLOCK_ELEMENTS = frozenset((
    "address", "article", "aside", "blockquote", "details", "div", "dl", "fieldset", "figcaption",
    "figure", "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hgroup", "hr",
    "main", "menu", "nav", "ol", "p", "pre", "section", "table", "ul",
))
_IMPLIED = {
    "li": {"li"},
    "dt": {"dt", "dd"}, "dd": {"dt", "dd"},
    "tr": {"tr", "td", "th"}, "td": {"td", "th"}, "th": {"td", "th"},
    "thead": {"thead", "tbody", "tfoot", "tr", "td", "th"},
    "tbody": {"thead", "tbody", "tfoot", "tr", "td", "th"},
    "tfoot": {"thead", "tbody", "tfoot", "tr", "td", "th"},
    "option": {"option"}, "optgroup": {"option", "optgroup"},
    "rt": {"rt", "rp"}, "rp": {"rt", "rp"},
}
IMPLIED_END = {}
for _tag in set(_IMPLIED) | BLOCK_ELEMENTS:
    _closes = set(_IMPLIED.get(_tag, ()))
    if _tag in BLOCK_ELEMENTS or _tag in ("li", "dt", "dd", "tr", "td", "th"):
        _closes.add("p")          # an open paragraph is closed by any block-level start tag
    IMPLIED_END[_tag] = frozenset(_closes)

# Elements an implied close may look THROUGH. A browser closes an open `<li>` when the next `<li>`
# starts even if a `<p>` or some formatting is still open inside it, but it never closes one across
# a real container boundary - so a `<table>` or `<ul>` stops the search.
TRANSPARENT = frozenset((
    "a", "abbr", "b", "bdi", "bdo", "big", "cite", "code", "data", "del", "dfn", "em", "font", "i",
    "ins", "kbd", "label", "mark", "nobr", "output", "p", "q", "rb", "rtc", "ruby", "s", "samp",
    "small", "span", "strike", "strong", "sub", "sup", "time", "tt", "u", "var",
))

# A script whose type is not JavaScript never RUNS, so its body is DATA, not code. The layer's own
# `embeddedComments` island is exactly that, and reading it as code let a reviewer's prose raise a
# scripted-class hazard - evidence from the document's text rather than from the layer. The list is
# the HTML standard's JavaScript MIME type essences, legacy spellings included, so gating on type
# cannot silently MISS a script that really executes.
JS_TYPES = frozenset((
    "", "module",
    "application/ecmascript", "application/javascript", "application/x-ecmascript",
    "application/x-javascript", "text/ecmascript", "text/javascript", "text/javascript1.0",
    "text/javascript1.1", "text/javascript1.2", "text/javascript1.3", "text/javascript1.4",
    "text/javascript1.5", "text/jscript", "text/livescript", "text/x-ecmascript",
    "text/x-javascript",
))

# The event-handler content attributes. Matching every `on*` name instead flagged ordinary
# attributes (`once`, `ongoing`) as executable code.
EVENT_HANDLERS = frozenset("""
onabort onauxclick onafterprint onbeforeinput onbeforematch onbeforeprint onbeforetoggle
onbeforeunload onblur oncancel oncanplay oncanplaythrough onchange onclick onclose oncontextlost
oncontextmenu oncontextrestored oncopy oncuechange oncut ondblclick ondrag ondragend ondragenter
ondragleave ondragover ondragstart ondrop ondurationchange onemptied onended onerror onfocus
onformdata onhashchange oninput oninvalid onkeydown onkeypress onkeyup onlanguagechange onload
onloadeddata onloadedmetadata onloadstart onmessage onmessageerror onmousedown onmouseenter
onmouseleave onmousemove onmouseout onmouseover onmouseup onoffline ononline onpagehide onpagereveal
onpageshow onpageswap onpaste onpause onplay onplaying onpopstate onprogress onratechange onrejected
onreset onresize onscroll onscrollend onsecuritypolicyviolation onseeked onseeking onselect
onselectionchange onselectstart onslotchange onstalled onstorage onsubmit onsuspend ontimeupdate
ontoggle onunhandledrejection onunload onvolumechange onwaiting onwheel
""".split())

# A rule that selects on the class ATTRIBUTE STRING rather than on a token: what it matches depends
# on the literal spelling, on substrings, and on token order, none of which a rewrite preserves.
ATTR_SELECTOR_RE = re.compile(r"\[\s*class\s*(?:[~^$*|]?=|\])", re.IGNORECASE)
# A class selector written with a CSS escape (`.\74 ok` is `.tok`): invisible to a token scan.
ESCAPED_SELECTOR_RE = re.compile(r"\.[A-Za-z0-9_-]*\\")
# Rules the tool never sees, so it cannot know which tokens they select.
IMPORT_RE = re.compile(r"@import\b", re.IGNORECASE)
# Script that reads, writes, or matches a class string; a rewrite would have to follow the value
# through arbitrary code.
SCRIPTED_CLASS_RES = (
    re.compile(r"""(?:get|set)Attribute\(\s*['"]class['"]""", re.IGNORECASE),
    re.compile(r"\.className\b"),
    re.compile(r"getElementsByClassName\("),
    re.compile(r"""classList\.(?:contains|toggle|replace|add|remove)\(\s*['"`]"""),
    re.compile(r"""(?:querySelectorAll?|closest|matches)\(\s*['"`][^'"`]*\.[A-Za-z_-]"""),
    re.compile(r"""(?:querySelectorAll?|closest|matches)\(\s*['"`][^'"`]*\[\s*class""",
               re.IGNORECASE),
)

HAZARD_HELP = {
    "attribute_selector": "a selector matches on the class attribute STRING ([class*=...]), so a "
                          "rewrite changes what it matches",
    "escaped_selector": "a class selector is written with a CSS escape, so a token scan never sees it",
    "external_stylesheet": "rules arrive from a linked or imported stylesheet the tool never reads",
    "external_script": "code arrives from an external script the tool never reads",
    "scripted_class": "script reads, writes, or matches class strings, so the rewrite would have to "
                      "follow the value through code",
    "inline_handler": "an inline event handler or javascript: URI carries code the tool does not "
                      "analyse",
}

# The characters HTML forbids in an UNQUOTED attribute value. A value free of them can drop its
# quotes, which is the one class saving that is provably value-preserving.
UNQUOTABLE = frozenset(" \t\n\r\f\"'=<>`")


def attributes(start_tag_text):
    """Yield `(name, offset, span, value_source, quote)` for each attribute in a raw start tag.

    Quote-aware, so ` class=` appearing INSIDE another attribute's quoted value is never mistaken
    for an attribute - the blind-scan defect CMH-SIZE-01 already records paying for once. `offset`
    is where `span` starts within the tag, and `span` includes the whitespace separating the
    attribute from what precedes it: exactly the run of bytes a removal would reclaim, at exactly
    the place it sits, so no caller ever has to search for it again.
    """
    text = start_tag_text
    index = 1
    while index < len(text) and not text[index].isspace() and text[index] not in "/>":
        index += 1
    while index < len(text):
        start = index
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text) or text[index] in "/>":
            return
        name_start = index
        while index < len(text) and not text[index].isspace() and text[index] not in "=/>":
            index += 1
        name = text[name_start:index]
        after = index
        while after < len(text) and text[after].isspace():
            after += 1
        if after < len(text) and text[after] == "=":
            after += 1
            while after < len(text) and text[after].isspace():
                after += 1
            if after < len(text) and text[after] in "\"'":
                quote = text[after]
                end = text.find(quote, after + 1)
                end = len(text) if end < 0 else end + 1
                yield name, start, text[start:end], text[after + 1:end - 1], quote
                index = end
                continue
            end = after
            while end < len(text) and not text[end].isspace() and text[end] != ">":
                end += 1
            yield name, start, text[start:end], text[after:end], ""
            index = end
            continue
        yield name, start, text[start:index], None, ""


def _quote_saving(start_tag, span, offset, source, quote):
    """Bytes eliding this attribute's quotes would save, without changing the value it parses to.

    Eligibility is decided on the SOURCE spelling, not the decoded value: `class="a&#61;b"` decodes
    to `a=b`, which holds a character unquoted syntax forbids, but the source spelling holds none,
    so `class=a&#61;b` is legal and decodes to the same thing.

    Dropping the quotes is only free when what follows them already separates the attribute from
    the rest of the tag. In `<img class="hero"/>` it does not: `class=hero/` parses as the value
    `hero/`, so a space has to go back in and the saving is one byte, not two.
    """
    if not quote or not source or (UNQUOTABLE & set(source)):
        return 0
    following = start_tag[offset + len(span):offset + len(span) + 1]
    return 2 if (following == "" or following == ">" or following.isspace()) else 1


class _Scan(HTMLParser):
    def __init__(self, line_starts=None):
        HTMLParser.__init__(self, convert_charrefs=False)
        self._line_starts = line_starts or [0]
        self._open = []          # (tag, element_index, script_is_code)
        self._depths = {}        # tag -> [stack depths], so an end tag resolves without a scan
        self.elements = []       # [value, parent, byte_cost, quote_saving, src_tokens, src_value]
        self.css = []
        self.script = []
        self.spans = []          # (absolute start, absolute end) of every class attribute
        self.external_stylesheet = 0
        self.external_script = 0
        self.inline_handler = 0

    def _offset(self):
        line, column = self.getpos()
        return self._line_starts[line - 1] + column

    def _push(self, tag, index, script_is_code=False):
        self._depths.setdefault(tag, []).append(len(self._open))
        self._open.append((tag, index, script_is_code))

    def _pop_to(self, depth):
        for tag, _index, _code in self._open[depth:]:
            stack = self._depths.get(tag)
            while stack and stack[-1] >= depth:
                stack.pop()
        del self._open[depth:]

    def _close_implied(self, tag):
        """Close what this start tag implies, CASCADING as a browser does.

        `<tr>` closes an open `<td>` and then the `<tr>` that held it; a single pop left the new
        row nested inside the old one, which is the difference between a hoist figure of 20 and one
        of 3000 on a 100-row table.
        """
        implied = IMPLIED_END.get(tag)
        if not implied:
            return
        while True:
            depth = len(self._open) - 1
            while depth >= 0:
                open_tag = self._open[depth][0]
                if open_tag in implied:
                    self._pop_to(depth)
                    break
                if open_tag not in TRANSPARENT:
                    return          # a real container boundary; a browser stops here too
                depth -= 1
            else:
                return

    def handle_starttag(self, tag, attrs):
        self._close_implied(tag)

        index = len(self.elements)
        parent = self._open[-1][1] if self._open else -1
        raw = self.get_starttag_text() or ""
        base = self._offset()

        value, cost, quote_saving, source_tokens, source_value = None, 0, 0, [], ""
        for name, offset, span, source, quote in attributes(raw):
            lowered = name.lower()
            if lowered == "class":
                cost += len(_utf8(span))
                self.spans.append((base + offset, base + offset + len(span)))
                quote_saving += _quote_saving(raw, span, offset, source, quote)
                if value is None:
                    # A browser keeps the FIRST spelling of a repeated attribute, so that is the
                    # value the DOM sees - but every copy still costs bytes, and every copy could
                    # still lose its quotes, which is why those two are accumulated above.
                    value = html_module.unescape(source or "")
                    source_value = source or ""
                    source_tokens = source_value.split()
            elif lowered in EVENT_HANDLERS:
                self.inline_handler += 1
            elif source is not None and html_module.unescape(source).strip().lower().startswith(
                    "javascript:"):
                self.inline_handler += 1
        self.elements.append([value, parent, cost, quote_saving, source_tokens, source_value])

        if tag == "link":
            rel = " ".join(v or "" for k, v in attrs if k.lower() == "rel").lower()
            if "stylesheet" in rel.split():
                self.external_stylesheet += 1
        script_is_code = False
        if tag == "script":
            types = [(v or "").strip().lower() for k, v in attrs if k.lower() == "type"]
            script_is_code = (types[0].split(";")[0].strip() if types else "") in JS_TYPES
            if script_is_code and any(k.lower() == "src" for k, _v in attrs):
                self.external_script += 1
        if tag not in VOID_ELEMENTS:
            self._push(tag, index, script_is_code)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        # A self-closing slash is honored for foreign content only; `<script/>` leaves the element
        # OPEN in HTML, so popping it here would hide the code that follows.
        if tag not in ("script", "style") and self._open and self._open[-1][0] == tag:
            self._pop_to(len(self._open) - 1)

    def handle_endtag(self, tag):
        stack = self._depths.get(tag)
        if stack:
            self._pop_to(stack[-1])

    def handle_data(self, data):
        if not self._open:
            return
        tag, _index, script_is_code = self._open[-1]
        if tag == "style":
            self.css.append(data)
        elif tag == "script" and script_is_code:
            self.script.append(data)


def _utf8(text):
    """UTF-8 bytes, tolerating the surrogates a `surrogateescape` decode leaves behind.

    Every byte count in this tool goes through here. A strict encode raised `UnicodeEncodeError` on
    exactly the non-UTF-8 documents `measure()` decodes leniently so it can measure them at all.
    """
    return text.encode("utf-8", "surrogateescape")


def _line_starts(text):
    starts, position = [0], text.find("\n")
    while position >= 0:
        starts.append(position + 1)
        position = text.find("\n", position + 1)
    return starts


def _shortest_names(count):
    """`count` distinct names, shortest first: a, b, ... Z, aa, ab, ..."""
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    names = []
    for n in range(count):
        name, k = "", n
        while True:
            name = alphabet[k % len(alphabet)] + name
            k = k // len(alphabet) - 1
            if k < 0:
                break
        names.append(name)
    return names


def _hoist_ceiling(elements):
    """Bytes a token every direct child shares would free if it moved to the container.

    Works on the SOURCE spellings and counts their UTF-8 BYTES, because bytes in the file are what
    a reduction removes: a shared `&#233;` frees the six bytes it is written with, and a shared `e`
    with an acute accent frees two, not one apiece.

    NOT a shape-free bound: a hoist can only reach what the tree offers, so this is an OBSERVATION
    on the parsed tree, and a differently shaped document offers more or less. Within one tree it
    over-estimates: it charges NOTHING for the container attribute the hoist would have to add,
    counts the whole attribute when hoisting empties a child's value, and asks nothing about
    whether the rewritten selector would still match.
    """
    children = {}
    for index, row in enumerate(elements):
        children.setdefault(row[1], []).append(index)
    saved = 0
    for parent, group in children.items():
        if parent < 0 or len(group) < 2:
            continue
        token_sets = [set(elements[i][4]) for i in group]
        shared = set.intersection(*token_sets)
        if not shared:
            continue
        for token in shared:
            saved += (len(_utf8(token)) + 1) * len(group)
        for index, tokens in zip(group, token_sets):
            if not (tokens - shared):
                # The value is emptied, so the attribute SYNTAX goes too: the per-token bytes above
                # already cover the value plus one separator, leaving the rest of the span.
                saved += elements[index][2] - (len(_utf8(" ".join(sorted(tokens)))) + 1)
    return saved


def scan(html):
    """Measure one document. `html` is the source text; returns a plain dict."""
    parser = _Scan(_line_starts(html))
    parser.feed(html)
    parser.close()

    values = [row[0] for row in parser.elements if row[0] is not None]
    tokens = Counter()
    for value in values:
        tokens.update(value.split())
    value_counts = Counter(values)

    # The ceilings work on the SOURCE spellings and count UTF-8 BYTES: a reduction removes bytes
    # from the file, and two spellings that decode alike are still two different strings a static
    # rewriter would have to reconcile.
    source_tokens = Counter()
    for row in parser.elements:
        source_tokens.update(row[4])
    short = dict(zip([t for t, _ in source_tokens.most_common()],
                     _shortest_names(len(source_tokens))))
    # A renamer would never LENGTHEN a token, so a token already shorter than its assigned name
    # keeps its own spelling and contributes nothing.
    rename = sum(max(0, len(_utf8(t)) - len(_utf8(short[t]))) * n
                 for t, n in source_tokens.items())

    normalize = 0
    for row in parser.elements:
        if row[0] is None:
            continue
        seen, kept = set(), []
        for token in row[4]:
            if token not in seen:
                seen.add(token)
                kept.append(token)
        normalize += len(_utf8(row[5])) - len(_utf8(" ".join(kept)))

    css = "".join(parser.css)
    script = "".join(parser.script)
    hazards, samples = {}, {}

    def note(name, matches):
        if matches:
            hazards[name] = len(matches)
            samples[name] = matches[:3]

    note("attribute_selector",
         [m.group(0) for m in ATTR_SELECTOR_RE.finditer(css)]
         + [m.group(0) for m in ATTR_SELECTOR_RE.finditer(script)])
    note("escaped_selector", [m.group(0) for m in ESCAPED_SELECTOR_RE.finditer(css)])
    note("external_stylesheet",
         ["@import"] * len(IMPORT_RE.findall(css))
         + ["<link rel=stylesheet>"] * parser.external_stylesheet)
    note("external_script", ["<script src>"] * parser.external_script)
    note("scripted_class", [m.group(0) for rx in SCRIPTED_CLASS_RES for m in rx.finditer(script)])
    note("inline_handler", ["on... / javascript:"] * parser.inline_handler)

    raw_bytes = len(_utf8(html))
    class_bytes = sum(row[2] for row in parser.elements)
    return {
        "bytes_total": raw_bytes,
        "elements": len(parser.elements),
        "class_attrs": len(values),
        "class_bytes": class_bytes,
        "class_percent": round(100.0 * class_bytes / max(1, raw_bytes), 3),
        "distinct_values": len(value_counts),
        "distinct_tokens": len(tokens),
        "top_values": value_counts.most_common(3),
        "ceiling_hoist": _hoist_ceiling(parser.elements),
        "ceiling_rename": rename,
        "ceiling_normalize": normalize,
        "ceiling_quote_elision": sum(row[3] for row in parser.elements),
        "hazards": hazards,
        "hazard_samples": samples,
        "spans": parser.spans,
    }


def strip_class_attributes(html, result=None):
    """The document with every class ATTRIBUTE removed - and nothing else.

    The spans are absolute source offsets recorded during the parse, so prose, a script string, or
    a `<pre>` code sample that merely SPELLS `class="..."` is left alone, a repeated attribute on
    one element is removed along with the first, and nothing is ever located by searching for text
    that might occur somewhere else.
    """
    result = scan(html) if result is None else result
    pieces, cursor = [], 0
    for start, end in sorted(result["spans"]):
        if start < cursor:
            continue
        pieces.append(html[cursor:start])
        cursor = end
    pieces.append(html[cursor:])
    return "".join(pieces)


def measure(path):
    """Measure the document at `path`, reading it as BYTES so the sizes are the file's own."""
    with open(path, "rb") as handle:
        raw = handle.read()
    # surrogateescape round-trips invalid bytes exactly, so a non-UTF-8 document is measured as
    # itself rather than as a copy in which every bad byte grew into a replacement character.
    text = raw.decode("utf-8", "surrogateescape")
    result = scan(text)
    result["path"] = path
    result["bytes_total"] = len(raw)
    result["class_percent"] = round(100.0 * result["class_bytes"] / max(1, len(raw)), 3)
    result["gzip_bytes"] = len(gzip.compress(raw, 9))
    without = _utf8(strip_class_attributes(text, result))
    result["gzip_bytes_without_class"] = len(gzip.compress(without, 9))
    result["bytes_without_class"] = len(without)
    result.pop("spans", None)
    return result


def report(result, out=sys.stdout):
    def kb(value):
        return "%.1f KB" % (value / 1024.0)

    out.write("== %s (%s raw, %s gzip)\n"
              % (os.path.basename(result["path"]), kb(result["bytes_total"]),
                 kb(result["gzip_bytes"])))
    out.write("   class attributes    : %d over %d elements, %d distinct values, %d distinct tokens\n"
              % (result["class_attrs"], result["elements"], result["distinct_values"],
                 result["distinct_tokens"]))
    out.write("   class bytes         : %s (%.2f%% of the file)\n"
              % (kb(result["class_bytes"]), result["class_percent"]))
    for label, key in (("quote elision", "ceiling_quote_elision"), ("rename", "ceiling_rename"),
                       ("normalize", "ceiling_normalize"), ("hoist (observed)", "ceiling_hoist")):
        out.write("   ceiling: %-16s: %s (%.2f%% of the file)\n"
                  % (label, kb(result[key]),
                     100.0 * result[key] / max(1, result["bytes_total"])))
    out.write("   deleting EVERY class attribute (the shape-free bound on any reduction) saves "
              "%s raw, %s gzipped\n"
              % (kb(result["bytes_total"] - result["bytes_without_class"]),
                 kb(result["gzip_bytes"] - result["gzip_bytes_without_class"])))
    if result["hazards"]:
        for name, count in sorted(result["hazards"].items()):
            out.write("   hazard: %-20s x%-4d %s\n" % (name, count, HAZARD_HELP[name]))
    else:
        out.write("   hazard: none found\n")
    out.write("\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="+", help="documents to measure")
    parser.add_argument("--json", action="store_true", help="emit the raw measurements as JSON")
    args = parser.parse_args(argv)

    results, failed = [], False
    for path in args.paths:
        try:
            results.append(measure(path))
        except OSError as error:
            sys.stderr.write("class_cost: cannot read %s: %s\n" % (path, error))
            failed = True
    if args.json:
        sys.stdout.write(json.dumps(results, indent=2, sort_keys=True) + "\n")
    else:
        for result in results:
            report(result)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
