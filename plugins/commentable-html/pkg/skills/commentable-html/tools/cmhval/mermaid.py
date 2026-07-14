"""Mermaid diagram syntax checks (a shipped, dependency-free, zero-false-positive
subset of the real mermaid parser).

The full mermaid grammar is only reproducible by mermaid itself, so this module
does NOT try to reimplement it. It deep-checks exactly ONE thing, because it is
both the reported bug class and provably safe: a `sequenceDiagram` message that a
`;` splits into a dangling statement. Every OTHER diagram family (flowchart,
class, state, er, gantt, pie, ...) is recognized but intentionally left
unchecked - reproducing their grammar in Python kept producing false positives
(a flowchart label may legitimately contain `%%` or a literal `"` inside a
slash/round/hex shape, a `click` callback may carry unbalanced quotes), and the
zero-false-positive guarantee matters more than catching those in the shipped
checker. The repo-side real-parser oracle (dev/tools/validate_render.mjs) does
validate every diagram family with the authoritative parser in CI.

The sequence rule (all ERRORS, because a broken diagram renders as mermaid's
"Syntax error in text" bomb instead of a diagram):

  In a sequenceDiagram, `;` is a statement separator, so
  `A->>B: validate; map X -> Y` is parsed as the signal `A->>B: validate`
  followed by a second statement `map X -> Y`. A statement that carries a message
  arrow but no `:` message is an invalid signal - the exact class of the bug this
  checker was built for. To stay zero-false-positive:
    - Only a line whose FIRST `;`-segment is a real signal (an arrow WITH a `:`
      message after it) is inspected; a directive like `accTitle: A -> B` (whose
      colon precedes the arrow) is never mistaken for one.
    - Only NON-keyword-led tail segments are flagged, so a `participant`,
      `activate`, `Note`, `loop`, etc. after the `;` is a valid statement.
    - `%%{ ... }%%` init directives and `%%` comments are stripped first, so a
      `;` or arrow inside a directive/comment is never split on.
"""

import re

# Diagram-type keywords we deep-check. Detection mirrors mermaid: the type is the
# first token of the first meaningful line (after YAML frontmatter, `%%{...}%%`
# directives, and `%%` comments). Any other type is accepted without deep checks
# so a new/other diagram family can never be a false positive.
_SEQUENCE_TYPES = ("sequencediagram",)

# Sequence message arrows, longest-first so alternation is greedy. These are the
# ONLY sequence statements that carry an arrow, and every one requires a trailing
# `: message`, which is what makes "arrow but no colon" an unambiguous error.
_SEQ_ARROW = re.compile(r"<<-->>|<<->>|-->>|-->|->>|->|--x|-x|--\)|-\)")

# Statement-leading keywords in a sequenceDiagram. A tail segment that starts with
# one of these is a valid non-signal statement, so it is never flagged - that is
# what prevents a `participant ... as ...`, `activate`, `Note`, or `accTitle:`
# false positive. A trailing `:` on the token (`accTitle:`) is tolerated.
_SEQ_KEYWORDS = frozenset((
    "participant", "actor", "create", "destroy", "box", "end",
    "activate", "deactivate", "note", "loop", "alt", "else", "opt", "par",
    "and", "critical", "option", "break", "rect", "autonumber",
    "title", "acctitle", "accdescr", "link", "links", "properties", "details",
))

_FRONTMATTER_RE = re.compile(r"^\s*---\r?\n.*?\r?\n---[ \t]*\r?\n", re.DOTALL)
# A `%%{ ... }%%` init/config directive (may span lines) - NOT a comment; remove it
# wholesale so a `;`/arrow inside it is never split on.
_DIRECTIVE_RE = re.compile(r"%%\{.*?\}%%", re.DOTALL)
# A `%%` comment runs to end of line. Applied only AFTER directives are removed, so
# it never eats a `%%{ ... }%%`.
_LINE_COMMENT_RE = re.compile(r"%%.*$")


def block_source(block):
    """Joined, entity-decoded source text of a parsed mermaid block, or "" ."""
    parts = block.get("src_parts")
    if parts:
        return "".join(parts)
    return block.get("src", "") or ""


def _diagram_type_and_lines(src):
    """(lowercase diagram type or None, [body line, ...]) after removing YAML
    frontmatter, `%%{...}%%` directives, `%%` comments, and blank lines. Body lines
    keep their arrows and text intact so the sequence check can inspect them."""
    body = _FRONTMATTER_RE.sub("", src, count=1)
    body = _DIRECTIVE_RE.sub("", body)
    dtype = None
    out = []
    for raw in body.splitlines():
        line = _LINE_COMMENT_RE.sub("", raw)
        if not line.strip():
            continue
        if dtype is None:
            dtype = line.strip().split()[0].lower()
            continue
        out.append(line)
    return dtype, out


def _is_signal(segment):
    """True when a segment is a real sequence signal: a message arrow followed by a
    `: message`. The colon must come AFTER the arrow, which distinguishes a signal
    from a directive such as `accTitle: A -> B` (colon before the arrow)."""
    m = _SEQ_ARROW.search(segment)
    return bool(m) and ":" in segment[m.end():]


def _tail_is_invalid_signal(segment):
    """True when a NON-keyword-led tail segment carries a message arrow but has no
    `:` after it - a signal without its message, which mermaid always rejects."""
    seg = segment.strip()
    if not seg:
        return False
    first = seg.split()[0].lower().rstrip(":")  # tolerate `accTitle:` / `accDescr:`
    if first in _SEQ_KEYWORDS:
        return False
    m = _SEQ_ARROW.search(seg)
    if not m:
        return False
    return ":" not in seg[m.end():]


def _check_sequence(lines, where):
    errors = []
    for line in lines:
        segments = line.split(";")
        if len(segments) < 2:
            continue  # no `;`, so mermaid parses the line as a single statement
        if not _is_signal(segments[0]):
            continue  # only a real message line splits into a dangling signal
        for seg in segments[1:]:
            if _tail_is_invalid_signal(seg):
                errors.append(
                    "%s: a ';' in a sequence message splits it into a separate statement, and "
                    "the text after it (\"%s\") is parsed as a signal with no message - "
                    "mermaid reports \"Syntax error in text\". Remove the ';' or rephrase the "
                    "message (a ';' is a statement separator in mermaid)." % (where, seg.strip())
                )
                break  # one finding per line is enough
    return errors


def check_mermaid_source(src):
    """Validate one raw mermaid source string. Returns a list of error strings
    (empty when the checker has nothing to flag)."""
    src = (src or "").strip()
    if not src:
        return []
    dtype, lines = _diagram_type_and_lines(src)
    if dtype in _SEQUENCE_TYPES:
        return _check_sequence(lines, "mermaid diagram")
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
        dtype, lines = _diagram_type_and_lines(src)
        if dtype in _SEQUENCE_TYPES:
            errors.extend(_check_sequence(lines, "mermaid diagram #%d" % (i + 1)))
    return errors, warnings
