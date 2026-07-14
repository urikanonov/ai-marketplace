"""Mermaid diagram syntax checks (a shipped, dependency-free, zero-false-positive
subset of the real mermaid parser).

The full mermaid grammar is only reproducible by mermaid itself, so this module
does NOT try to reimplement it. It flags a small set of mistakes that are
DEFINITELY invalid in every mermaid version - each rule is proven by the mermaid
grammar and calibrated against a large corpus of real, valid diagrams (see
dev/tests/test_mermaid_corpus.py and the differential oracle
dev/tools/validate_render.mjs) so it never rejects a diagram the real parser
accepts. The repo-side oracle covers everything this module conservatively skips.

Rules (all ERRORS, because a syntactically broken diagram renders as mermaid's
"Syntax error in text" bomb instead of a diagram):

  MERMAID SEQUENCE - semicolon splits a message into a dangling statement.
    In a sequenceDiagram, `;` is a statement separator, so
    `A->>B: validate; map X -> Y` is parsed as the signal `A->>B: validate`
    followed by a second statement `map X -> Y`. A statement that contains a
    message arrow but no `:` message is an invalid signal - the exact class of
    the bug this checker was built for. Only NON-keyword-led segments are
    checked, so a `participant A as "x->y"` alias is never mis-flagged.

  MERMAID FLOWCHART - an unbalanced double quote.
    In flowchart/graph node text a literal `"` must be escaped (`#quot;` /
    `&quot;`); an odd count of raw quotes (after removing comments, directives,
    and escaped quotes) is always a parse error.

Everything else (unknown diagram types, other diagram families, deeper flowchart
structure) is intentionally NOT flagged here to keep the guarantee of no false
positives; the Node/Playwright oracle validates those repo-side.
"""

import re

# Diagram-type keywords we understand well enough to deep-check. Detection mirrors
# mermaid: the type is the first token of the first meaningful line (after any
# YAML frontmatter, `%%{init}%%` directives, and `%%` comment lines). Any other /
# unknown type is accepted without deep checks so a new mermaid diagram type can
# never be a false positive.
_SEQUENCE_TYPES = ("sequencediagram",)
_FLOWCHART_TYPES = ("flowchart", "graph")

# Sequence message arrows, longest-first so alternation is greedy. These are the
# ONLY sequence statements that carry an arrow, and every one of them requires a
# trailing `: message`, which is what makes "arrow but no colon" an unambiguous
# error.
_SEQ_ARROW = re.compile(r"<<-->>|<<->>|-->>|-->|->>|->|--x|-x|--\)|-\)")

# Statement-leading keywords in a sequenceDiagram. A segment that starts with one
# of these is a non-signal statement (or a free-text-bearing one such as
# `participant ... as ...`), so it is never checked for the arrow-without-colon
# rule - that is what prevents a `participant A as "a->b"` false positive.
_SEQ_KEYWORDS = frozenset((
    "participant", "actor", "create", "destroy", "box", "end",
    "activate", "deactivate", "note", "loop", "alt", "else", "opt", "par",
    "and", "critical", "option", "break", "rect", "autonumber",
    "title", "acctitle", "accdescr", "link", "links", "properties", "details",
))

_FRONTMATTER_RE = re.compile(r"^\s*---\r?\n.*?\r?\n---[ \t]*\r?\n", re.DOTALL)
# An inline `%%` comment runs to end of line, but `%%{ ... }%%` is an init
# directive, not a comment - do not strip that.
_INLINE_COMMENT_RE = re.compile(r"%%(?!\{).*$")


def block_source(block):
    """Joined, entity-decoded source text of a parsed mermaid block, or "" ."""
    parts = block.get("src_parts")
    if parts:
        return "".join(parts)
    return block.get("src", "") or ""


def _meaningful_lines(src):
    """(diagram_type, [body_line, ...]) after stripping YAML frontmatter, the
    leading `%%{init}%%` directive(s), `%%` comment lines, and blank lines.
    diagram_type is lowercase; body_line keeps the ORIGINAL text (arrows intact)
    but with any trailing inline `%%` comment removed."""
    body = _FRONTMATTER_RE.sub("", src, count=1)
    raw_lines = body.splitlines()
    dtype = None
    out = []
    for raw in raw_lines:
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith("%%"):
            continue  # `%%{init}%%` directive or a full-line comment
        line = _INLINE_COMMENT_RE.sub("", raw).rstrip()
        if not line.strip():
            continue
        if dtype is None:
            dtype = line.strip().split()[0].lower() if line.strip().split() else ""
            continue
        out.append(line)
    return dtype, out


def _split_statements(line):
    """Split a sequence line into `;`-separated statement segments, matching how
    mermaid treats `;` as a statement terminator."""
    return line.split(";")


def _segment_is_invalid_signal(segment):
    """True when a NON-keyword-led segment carries a message arrow but has no `:`
    after it - a signal without its message, which mermaid always rejects."""
    seg = segment.strip()
    if not seg:
        return False
    first = seg.split()[0].lower()
    # Strip a leading `+`/`-` (activate/deactivate shorthand on a signal target).
    if first in _SEQ_KEYWORDS:
        return False
    m = _SEQ_ARROW.search(seg)
    if not m:
        return False
    return ":" not in seg[m.end():]


def _check_sequence(lines, where):
    errors = []
    for line in lines:
        segments = _split_statements(line)
        if len(segments) < 2:
            continue  # no `;`, so the line is a single statement mermaid parses as-is
        for seg in segments:
            if _segment_is_invalid_signal(seg):
                bad = seg.strip()
                errors.append(
                    "%s: a ';' in a sequence message splits it into a separate statement, and "
                    "the text after it (\"%s\") is parsed as a signal with no message - "
                    "mermaid reports \"Syntax error in text\". Remove the ';' or rephrase the "
                    "message (a ';' is a statement separator in mermaid)." % (where, bad)
                )
                break  # one finding per line is enough
    return errors


# A raw double quote that is NOT an escaped/entity quote. `#quot;` and `&quot;`
# are mermaid/HTML escapes for a literal quote; `\"` is a JS-style escape. After
# removing those, a leftover `"` is a real structural quote.
_ESCAPED_QUOTE_RE = re.compile(r"#quot;|&quot;|&#34;|\\\"")


def _check_flowchart_quotes(lines, where):
    # Count structural double quotes across the whole diagram body (comments and
    # inline `%%` comments are already stripped by _meaningful_lines). An odd
    # count cannot be balanced, so a node label opened with `"` was never closed.
    joined = "\n".join(lines)
    joined = _ESCAPED_QUOTE_RE.sub("", joined)
    if joined.count('"') % 2 == 1:
        return ["%s: a flowchart node label has an unbalanced double quote (an odd number of "
                "unescaped '\"') - close the quote, or escape a literal quote as #quot; . "
                "mermaid reports \"Syntax error in text\"." % where]
    return []


def check_mermaid_source(src):
    """Validate one raw mermaid source string. Returns a list of error strings
    (empty when the checker has nothing to flag). Used by the differential corpus
    test and by callers that already have the diagram text."""
    src = (src or "").strip()
    if not src:
        return []
    dtype, lines = _meaningful_lines(src)
    if dtype is None:
        return []
    where = "mermaid diagram"
    if dtype in _SEQUENCE_TYPES:
        return _check_sequence(lines, where)
    if dtype in _FLOWCHART_TYPES:
        return _check_flowchart_quotes(lines, where)
    return []


def check_mermaid_syntax(parser):
    """Return (errors, warnings). Validates the syntax of every un-rendered
    mermaid block the parser collected. A block that has already rendered to
    <svg> (offline export) is skipped - its text is SVG, not diagram source."""
    errors, warnings = [], []
    blocks = getattr(parser, "mermaid_blocks", None) or []
    for i, block in enumerate(blocks):
        if block.get("has_svg"):
            continue
        src = block_source(block).strip()
        if not src:
            continue
        dtype, lines = _meaningful_lines(src)
        if dtype is None:
            continue
        where = "mermaid diagram #%d" % (i + 1)
        if dtype in _SEQUENCE_TYPES:
            errors.extend(_check_sequence(lines, where))
        elif dtype in _FLOWCHART_TYPES:
            errors.extend(_check_flowchart_quotes(lines, where))
    return errors, warnings
