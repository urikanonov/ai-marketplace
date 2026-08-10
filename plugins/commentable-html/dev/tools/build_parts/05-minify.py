# Ship the runtime without the developer commentary, keep the source fully commented.
#
# The layer's JS partials are 1.2 MB and its CSS 210 KB, and roughly 44 percent of the JS is
# comments and leading indentation (#1250 measured 461 KB of line comments, 32 KB of block
# comments and 58 KB of indentation on one document). Those comments explain parser boundary
# decisions to a maintainer reading `assets/js/`; inside a document handed to a reviewer they are
# pure payload, and they ride along in EVERY generated file, the asset registry, and every offline
# export. So the build strips them, and `assets/js/**` stays the single readable source of truth.
#
# The transform is deliberately NOT a general minifier: no identifier mangling, no statement
# joining, no semicolon insertion. It only DELETES comments and layout whitespace, and it never
# touches a byte inside a string, template literal or regex literal. Three properties make that
# safe:
#
# 1. ASI IS PRESERVED EXACTLY. A line terminator is what decides automatic semicolon insertion, so
#    wherever the source had one this emits one. A block comment that CONTAINS a line terminator is
#    itself a line terminator to the spec, so it collapses to a newline rather than to a space.
#    Blank lines and indentation carry no meaning and go.
# 2. AN AMBIGUOUS `/` IS DECIDED BY THE GRAMMAR, NEVER GUESSED. Regex-literal versus division is
#    the one character JavaScript cannot tokenize without parse context, and the context that
#    decides it is small enough to track: after `]`, after an identifier, a number, a string or a
#    template literal, an expression has ENDED, so `/` divides; after `)` it opens a regex only
#    when that paren closed an `if` / `for` / `while` / `with` HEADER; after `}` only when that
#    brace closed a BLOCK rather than an object literal or an arrow body; and a keyword only opens
#    regex context when it is a keyword rather than a property name (`x.return / 2` divides). So a
#    regex is only ever SCANNED where a regex can legally be, and a regex literal - flags included
#    - is then copied through verbatim with a separator after it that is never dropped (`/re/ x`
#    must not become `/re/x`, where `x` would read as a flag).
# 3. THE RESULT IS RE-READ AND COMPARED, and separately SYNTAX-CHECKED. `minify_js` re-scans its
#    own output and requires the literal segments and the whitespace-free code to match the
#    source's, which catches an assembly that dropped or invented a byte. That check shares a
#    scanner with the thing it checks, so it is NOT a defence against a scanner misread - property
#    2 is. The independent check is `verify_js_syntax`, which the build runs on the stripped bytes
#    through `node --check` when node is present.
# 4. A SOURCE THAT DOES NOT CLOSE WHAT IT OPENS IS REFUSED. An unterminated comment, string or
#    template literal would otherwise be stripped away silently, shipping whatever prefix of the
#    file was still valid.

_MINIFY_JS_SPACE = " \t\r\n\f\v\u2028\u2029"
# The characters ECMAScript counts as LINE TERMINATORS. ASI and the extent of a `//` comment are
# decided by these, not by `\n` alone, so a lone CR (a CRLF checkout that lost its LF) or a
# U+2028/U+2029 must not silently join two statements or swallow a line of code.
_MINIFY_JS_EOL = "\n\r\u2028\u2029"
_MINIFY_ID_CH = frozenset("$_0123456789"
                          "abcdefghijklmnopqrstuvwxyz"
                          "ABCDEFGHIJKLMNOPQRSTUVWXYZ")
# After one of these words a `/` opens a REGEX, not a division: they all end a position where an
# expression may begin. Everything else that ends an identifier (a variable, a property, `this`)
# is a value, so `/` after it divides - and so does a `/` after one of THESE words when it is used
# as a property name (`x.return / 2`), which is why the decision also looks at what preceded it.
_MINIFY_REGEX_WORDS = frozenset((
    "await", "case", "catch", "debugger", "default", "delete", "do", "else", "extends", "finally",
    "in", "instanceof", "new", "of", "return", "throw", "typeof", "void", "yield"))
# A `(` that follows one of these opens a STATEMENT HEADER, so a `/` after its `)` opens a regex
# (`if (x) /re/.test(s)`). A `(` anywhere else is a call or a grouping, and its `)` ends a value.
_MINIFY_HEADER_WORDS = frozenset(("if", "for", "while", "with"))
# A `{` that follows one of these - or `;`, `{`, `}`, `)` or the start of input - opens a BLOCK, so
# a `/` after its `}` opens a regex. A `{` anywhere else is an object literal or an arrow body,
# whose `}` ends a value.
_MINIFY_BLOCK_WORDS = frozenset(("do", "else", "finally", "try"))
_MINIFY_BLOCK_BEFORE = frozenset(";{})")
# Comments a minifier must never drop: the conventional legal-notice markers.
_MINIFY_KEEP_COMMENT = ("/*!", "@license", "@preserve")


def _minify_keep_comment(text):
    return text.startswith("/*!") or "@license" in text or "@preserve" in text


def _minify_has_eol(text):
    return any(ch in text for ch in _MINIFY_JS_EOL)


def _minify_quoted_end(src, i):
    """Offset just past the `'`/`"` string starting at i, or -1 when it is unterminated."""
    quote = src[i]
    n = len(src)
    j = i + 1
    while j < n:
        c = src[j]
        if c == "\\":
            j += 2
            continue
        if c == quote:
            return j + 1
        j += 1
    return -1


def _minify_regex_end(src, i):
    """Offset just past the regex literal starting at i, flags included, or -1 when no regex
    literal can start there (it is unterminated, or a line terminator intervenes - a regex literal
    cannot span lines)."""
    n = len(src)
    j = i + 1
    in_class = False
    while j < n:
        c = src[j]
        if c == "\\":
            j += 2
            continue
        if c in _MINIFY_JS_EOL:
            return -1
        if c == "[":
            in_class = True
        elif c == "]":
            in_class = False
        elif c == "/" and not in_class:
            j += 1
            while j < n and src[j] in _MINIFY_ID_CH:
                j += 1
            return j
        j += 1
    return -1


def _minify_js_scan(src):
    """Split JS into ("code"|"lit"|"rx"|"line"|"block"|"space", text) segments.

    `lit` is any run whose bytes are meaningful as data - a string or a template literal chunk -
    and `rx` is a regex literal, which is the same except that the separator after it is never
    dropped (`/re/ x` must not close up into `/re/x`, where `x` would read as a flag). Both are
    copied through verbatim. Template `${...}` interiors are scanned as code, so a comment inside
    one is stripped like any other.

    Whether a `/` opens a regex is decided from parse context, never guessed: `pstack` remembers
    which `(` opened a statement HEADER and `bstack` which `{` opened a BLOCK, so `)` and `}` -
    the two closers that can precede either reading - are resolved rather than assumed.

    Returns (segments, problems); `problems` names each construct the scan could not close, so a
    caller can refuse to ship a truncated file rather than emit whatever was still valid.
    """
    segs = []
    problems = []
    n = len(src)
    i = last = 0
    prev = prev2 = ""      # the two most recent significant code characters
    word = ""              # the identifier/keyword token ending at or before `prev`
    word_open = False      # ... and whether the next identifier character extends it
    word_prev = ""         # the significant character just before `word` began
    tstack = []            # (brace stack, paren stack) saved on entering each `${`
    pstack = []            # per open `(`: True when it opened a statement header
    bstack = []            # per open `{`: True when it opened a block
    closed_regex_ok = False  # whether the `)` or `}` just consumed allows a regex after it
    in_tmpl = False

    def flush(to):
        if to > last:
            segs.append(("code", src[last:to]))

    def at(index):
        return "offset %d (line %d)" % (index, src.count("\n", 0, index) + 1)

    def regex_allowed():
        """Can a `/` at this point open a regex literal? Decided by what precedes it."""
        if not prev:
            return True         # start of input
        if prev in ")}":
            return closed_regex_ok
        if prev in "]\"'`":
            return False        # a subscript, a string or a template literal ENDS a value
        if prev in _MINIFY_ID_CH:
            return bool(word) and word in _MINIFY_REGEX_WORDS and word_prev != "."
        if prev in "+-" and prev2 == prev:
            return False        # `i++ / 2` divides
        return True             # after an operator or a punctuator

    while i < n:
        c = src[i]
        if in_tmpl:
            j = i
            closed = False
            while j < n:
                d = src[j]
                if d == "\\":
                    j += 2
                    continue
                if d == "`":
                    j += 1
                    in_tmpl = False
                    closed = True
                    break
                if d == "$" and j + 1 < n and src[j + 1] == "{":
                    j += 2
                    tstack.append((bstack, pstack))
                    bstack, pstack = [], []
                    in_tmpl = False
                    closed = True
                    break
                j += 1
            if not closed:
                problems.append("unterminated template literal at " + at(i))
                j = n
            chunk = src[i:j]
            segs.append(("lit", chunk))
            i = last = j
            # A chunk ends either at the closing backtick (a template VALUE, so `/` after it
            # divides) or at `${` (an expression position, where `/` opens a regex).
            prev, prev2 = ("{" if chunk.endswith("${") else "`"), ""
            word, word_open, word_prev = "", False, ""
            continue
        if c in _MINIFY_JS_SPACE:
            j = i
            while j < n and src[j] in _MINIFY_JS_SPACE:
                j += 1
            flush(i)
            segs.append(("space", src[i:j]))
            i = last = j
            word_open = False   # whitespace ENDS a token; it does not erase which token it was
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            j = next((k for k in range(i, n) if src[k] in _MINIFY_JS_EOL), n)
            flush(i)
            segs.append(("line", src[i:j]))
            i = last = j
            word_open = False
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            j = src.find("*/", i + 2)
            if j < 0:
                problems.append("unterminated block comment at " + at(i))
                j = n
            else:
                j += 2
            flush(i)
            segs.append(("block", src[i:j]))
            i = last = j
            word_open = False
            continue
        if c in "'\"":
            j = _minify_quoted_end(src, i)
            if j < 0:
                problems.append("unterminated string literal at " + at(i))
                j = n
            flush(i)
            segs.append(("lit", src[i:j]))
            i = last = j
            prev, prev2 = c, ""
            word, word_open, word_prev = "", False, ""
            continue
        if c == "`":
            flush(i)
            segs.append(("lit", "`"))
            i = last = i + 1
            in_tmpl = True
            continue
        if c == "/":
            if regex_allowed():
                j = _minify_regex_end(src, i)
                if j > 0:
                    flush(i)
                    segs.append(("rx", src[i:j]))
                    i = last = j
                    prev, prev2 = "/", ""
                    word, word_open, word_prev = "", False, ""
                    continue
        if c == "(":
            pstack.append(word in _MINIFY_HEADER_WORDS and word_prev != ".")
        elif c == ")":
            closed_regex_ok = pstack.pop() if pstack else False
        elif c == "{":
            # A block, or an object literal / arrow body? What precedes the brace decides, and only
            # a BLOCK can be followed by a regex.
            bstack.append(not prev or prev in _MINIFY_BLOCK_BEFORE
                          or (bool(word) and word in _MINIFY_BLOCK_WORDS and word_prev != "."))
        elif c == "}":
            if not bstack and tstack:
                bstack, pstack = tstack.pop()
                flush(i)
                segs.append(("lit", "}"))
                i = last = i + 1
                in_tmpl = True
                continue
            closed_regex_ok = bstack.pop() if bstack else False
        if c in _MINIFY_ID_CH:
            if word_open:
                word += c
            else:
                word, word_prev = c, prev
            word_open = True
        else:
            word, word_open, word_prev = "", False, ""
        prev2, prev = prev, c
        i += 1
    flush(n)
    return segs, problems


def _minify_signature(segs):
    """The parts of a source a strip must not change: its literal runs, in order, and its code
    with every comment and every whitespace character removed.

    Whitespace is excluded deliberately, because the strip legitimately rewrites it (a comment
    between two tokens becomes a space, indentation goes). It cannot LOSE a separator: the
    assembler only skips emitting one when the output already ends in whitespace.

    Note what this does and does NOT prove. It catches an ASSEMBLY that dropped, reordered or
    invented a byte. It is NOT a defence against a SCANNER misread: the scan's decisions depend
    only on the code characters, which the strip preserves, so scanning the output reaches the same
    decisions - right or wrong - as scanning the source. What keeps a `/` from being misread at all
    is that a regex is only SCANNED where the grammar allows one (property 2 in the module note);
    what catches a genuinely invalid result is `verify_js_syntax`, an independent parser.
    """
    lits, code = [], []
    for kind, text in segs:
        if kind in ("lit", "rx"):
            lits.append(text)
        elif kind == "code":
            code.append(text)
    return tuple(lits), re.sub(r"\s+", "", "".join(code))


def _minify_js_signature(src):
    return _minify_signature(_minify_js_scan(src)[0])


def _minify_js_needs_space(p, q):
    """True when removing the whitespace between code characters `p` and `q` would change how a
    parser reads them: two identifier characters would fuse into one token, `1 .toFixed()` would
    become an invalid `1.toFixed()`, `+ +` would become the increment operator, `/ /` or `/ *`
    would open a comment, and `< !`, `< /` or `- >` would manufacture a markup delimiter."""
    if p in _MINIFY_ID_CH and q in _MINIFY_ID_CH:
        return True
    # A `\` after an identifier character starts a Unicode escape that is PART of an identifier, so
    # `let \u0061 = 1` fused to `let\u0061=1` declares `leta` instead of `a`.
    if p in _MINIFY_ID_CH and q == "\\":
        return True
    if p.isdigit() and q == ".":
        return True
    if p in "+-" and q in "+-":
        return True
    if p == "/" and q in "/*":
        return True
    # Never let the strip MANUFACTURE text that reads as an HTML attribute. `el.title = "Close"`
    # fused to `el.title="Close"` puts a literal `title="Close"` inside a document's own script,
    # where any regex that scans document text for an attribute then matches the runtime instead
    # of the content. Keeping one byte between `=` and the quote costs ~1% of the bundle and
    # closes the whole class.
    if p == "=" and q in "\"'":
        return True
    # Never let the strip MANUFACTURE a markup delimiter. The layer is inlined inside a <script>
    # element, so `<` `/` fusing into `</script` (or `<` `!` into an HTML-like comment opener, or
    # `-` `>` into its closer) would end the element early and silently kill the runtime in every
    # document that embeds it.
    return p == "<" and q in "!/" or p == "-" and q == ">"


def _minify_css_fuses(p, q):
    """True when removing a comment between CSS characters `p` and `q` would merge two tokens into
    one. A CSS comment produces no whitespace token, but it does TERMINATE the token before it, so
    `bl/**/ue` is `bl ue` (an invalid value) and not the color `blue`, and `1px/**/2px` is not the
    dimension `1px2px`."""
    ident = _MINIFY_ID_CH | set("-%\\")
    return (p in ident or ord(p) > 127) and (q in ident or ord(q) > 127)


def _minify_assemble(segs, keep_comment, needs_space=None, comment_is_space=True):
    """Join segments, replacing each comment and whitespace run with the least whitespace that
    preserves ASI: a newline when the run carried a line terminator, otherwise a single space -
    or nothing at all when `needs_space` says the two neighbouring characters cannot fuse.

    A run that carried a line terminator always keeps one. A line terminator is the byte that
    decides automatic semicolon insertion, so dropping it (or turning it into a space) can silently
    change what the program means; it costs the same single byte as the space it replaces anyway.

    `comment_is_space` is the one place JS and CSS genuinely differ. In JavaScript a comment IS
    whitespace, so `const/*x*/a` must keep a separator. In CSS a comment is removed at tokenization
    and produces NO whitespace token, so `.a/**/.b` is the compound selector `.a.b`; inserting a
    space there would turn it into a descendant selector and silently restyle the page. It does
    still TERMINATE the token before it, so where the two neighbours would fuse (`1px/**/2px`,
    `bl/**/ue`) the comment is kept as an empty `/**/` rather than removed.
    """
    items = []  # ("t"|"r", text) content, ("s", had_newline) separator request
    for kind, text in segs:
        if kind in ("space", "block", "line"):
            if kind != "space" and keep_comment(text):
                items.append(("t", text))
                continue
            if kind == "line":
                continue  # its terminating newline is a separate whitespace run
            if kind == "block" and not comment_is_space:
                items.append(("c", ""))
                continue
            newline = _minify_has_eol(text)
            if items and items[-1][0] == "s":
                items[-1] = ("s", items[-1][1] or newline)
            else:
                items.append(("s", newline))
        else:
            items.append(("r" if kind == "rx" else "t", text))
    out = []
    for pos, (tag, value) in enumerate(items):
        if tag == "t" or tag == "r":
            out.append(value)
            continue
        nxt = next((v for t, v in items[pos + 1:] if t in ("t", "r")), "")
        if tag == "c":
            # A CSS comment: nothing, unless dropping it would fuse the tokens either side.
            if out and nxt and _minify_css_fuses(out[-1][-1], nxt[0]):
                out.append("/**/")
            continue
        if value:
            if out:
                out.append("\n")
            continue
        if not out or not nxt:
            continue
        # A separator after a REGEX literal is never dropped: the literal ends in `/` or a flag,
        # and letting an identifier close up against it (`/re/ x` -> `/re/x`) makes `x` read as a
        # flag instead of the next token.
        after_rx = items[pos - 1][0] == "r" if pos else False
        if ((after_rx and nxt[0] in _MINIFY_ID_CH)
                or needs_space is None or needs_space(out[-1][-1], nxt[0])):
            out.append(" ")
    return "".join(out).strip("\n")


def _minify_refuse(what, problems):
    raise SystemExit(
        "build: the %s comment strip refuses to run - the source does not close every construct "
        "it opens, so stripping it would silently truncate the shipped bytes:\n  %s"
        % (what, "\n  ".join(problems)))


def minify_js(src):
    """Return `src` without comments, indentation, trailing whitespace or blank lines.

    Raises SystemExit when the source leaves a construct unterminated, or when the result does not
    re-read as the same literals and code: the build must fail loudly rather than ship a runtime it
    silently truncated or rewrote.
    """
    segs, problems = _minify_js_scan(src)
    if problems:
        _minify_refuse("JS", problems)
    out = _minify_assemble(segs, _minify_keep_comment, _minify_js_needs_space)
    if _minify_js_signature(out) != _minify_signature(segs):
        raise SystemExit(
            "build: the JS comment strip did not round-trip - the minified layer does not re-read "
            "as the same literals and code as its source, so the assembly dropped or invented a "
            "byte. Fix tools/build_parts/05-minify.py rather than shipping the result.")
    return out


def verify_js_syntax(text, label="the stripped layer"):
    """Parse `text` with an INDEPENDENT parser and fail the build if it is not valid JavaScript.

    The strip's own re-read shares a scanner with the thing it checks, so it cannot certify that
    the result still parses. `node --check` can, and node is present wherever the fixtures gate
    runs. Returns a one-line report; a genuinely absent node runtime is a soft skip (CI still runs
    the browser suites against these bytes), a node that reports a syntax error is a hard failure.
    """
    node = shutil.which("node")
    if not node:
        return "syntax check skipped (node not found; the browser suites still run these bytes)"
    fd, path = tempfile.mkstemp(suffix=".js")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        proc = subprocess.run([node, "--check", path], capture_output=True, text=True)
    finally:
        os.remove(path)
    if proc.returncode != 0:
        raise SystemExit(
            "build: %s is not valid JavaScript after the comment strip. This is the independent "
            "check on the strip, so trust it over the strip's own re-read:\n%s"
            % (label, ((proc.stderr or proc.stdout or "").strip() or "node --check failed")))
    return "syntax check OK (node --check on the stripped layer)"


def _minify_css_scan(src):
    """Split CSS into ("code"|"lit"|"block"|"space", text) segments, plus the unclosed
    constructs the scan found."""
    segs = []
    problems = []
    n = len(src)
    i = last = 0

    def flush(to):
        if to > last:
            segs.append(("code", src[last:to]))

    while i < n:
        c = src[i]
        if c in _MINIFY_JS_SPACE:
            j = i
            while j < n and src[j] in _MINIFY_JS_SPACE:
                j += 1
            flush(i)
            segs.append(("space", src[i:j]))
            i = last = j
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            j = src.find("*/", i + 2)
            if j < 0:
                problems.append("unterminated block comment at offset %d (line %d)"
                                % (i, src.count("\n", 0, i) + 1))
                j = n
            else:
                j += 2
            flush(i)
            segs.append(("block", src[i:j]))
            i = last = j
            continue
        if c in "'\"":
            j = _minify_quoted_end(src, i)
            if j < 0:
                problems.append("unterminated string at offset %d (line %d)"
                                % (i, src.count("\n", 0, i) + 1))
                j = n
            flush(i)
            segs.append(("lit", src[i:j]))
            i = last = j
            continue
        i += 1
    flush(n)
    return segs, problems


def _minify_css_signature(src):
    return _minify_signature(_minify_css_scan(src)[0])


def minify_css(src):
    """Return `src` without comments, indentation, trailing whitespace or blank lines.

    Unlike the JS pass this never removes a space BETWEEN tokens, and never ADDS one either. In CSS
    whitespace is load bearing in both directions: it is the descendant combinator in a selector
    (`a .b` and `a.b` select different elements), and `calc(1px + 2px)` requires the spaces around
    its `+` and `-`. And a CSS comment is NOT whitespace - it is removed at tokenization and leaves
    nothing behind - so `.a/**/.b` is the compound selector `.a.b`, and turning that comment into a
    space would silently restyle the page.
    """
    segs, problems = _minify_css_scan(src)
    if problems:
        _minify_refuse("CSS", problems)
    out = _minify_assemble(segs, _minify_keep_comment, comment_is_space=False)
    if _minify_css_signature(out) != _minify_signature(segs):
        raise SystemExit(
            "build: the CSS comment strip did not round-trip - the minified stylesheet does not "
            "re-read as the same literals and declarations as its source. Fix "
            "tools/build_parts/05-minify.py rather than shipping the result.")
    return out
