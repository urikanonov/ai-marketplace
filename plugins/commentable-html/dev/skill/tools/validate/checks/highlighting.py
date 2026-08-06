"""Author-time code-block syntax-highlighting checks (a language-labelled block
that shipped without highlight spans)."""

import re

import _toolpath
from .parsing import code_block_spans, html_ws_tokens, _ascii_lower

_toolpath.ensure()
import _highlight_core  # noqa: E402

# Kusto labels the document highlight path bakes via the KQL tokenizer (CMH-KQL-09), so
# an unhighlighted one is a real warning here rather than an ignorable label.
_KQL_LANGUAGES = frozenset(("kusto", "kql"))

# A deliberately hand-written code block is legitimate - the authoring tools leave it exactly
# as written - so the author can never clear that finding. It carries a stable prefix (like the
# theme-contrast advisories) so a fail-closed caller keeps it out of its hard-fail path.
HIGHLIGHT_ADVISORY_PREFIX = "code highlighting advisory: "

# The only markup shape recognized as deliberate hand-highlighting: a well-formed open or close
# tag of an INERT inline formatting element, carrying at most a quoted `class`. Everything else -
# an unrecognized tag, ANY other attribute, an unquoted or malformed attribute, a stray `<` - is
# NOT inert and keeps the finding FATAL. The rule is deliberately conservative in the SAFE
# direction: a false "not inert" only keeps the behavior this check always had (every
# hand-written block was fatal), while a false "inert" would let markup that executes, loads or
# navigates pass --strict and be stamped. A `<pre>` body is parsed as markup, so a raw <script>,
# <iframe> or <img onerror> there really does run - the same line the diff-block rule draws for
# `<pre class="cmh-diff">`. Matching whole tags (rather than scanning for dangerous attributes)
# is what makes this safe: an attribute scanner has to model quoting to know where a tag ends,
# and any mistake there hides the NEXT tag - exactly how `<b x=1'><script>...` slips through.
_INERT_TAGS = (
    "span", "mark", "b", "i", "em", "strong", "u", "s", "del", "ins", "sub", "sup",
    "small", "abbr", "cite", "q", "var", "samp", "kbd", "code", "br", "wbr",
)
_INERT_TAG_RE = re.compile(
    r"</?(?:%s)(?:\s+class\s*=\s*(?:\"[^\"<>]*\"|'[^'<>]*'))?\s*/?>" % "|".join(_INERT_TAGS),
    re.IGNORECASE)


def _is_inert_markup(inner):
    """True when EVERY `<` in a code block's inner opens a well-formed inert inline tag.

    Text between the tags is never inspected: it is escaped source, so a code sample that merely
    MENTIONS `onclick=` or `javascript:` is inert (scanning the whole inner for those strings
    made such a sample fatal with an "escape it" message the author could not act on).
    """
    i = 0
    while True:
        j = inner.find("<", i)
        if j < 0:
            return True
        m = _INERT_TAG_RE.match(inner, j)
        if not m:
            return False
        i = m.end()



def _highlight_language_table():
    """Import the author-time highlighter's language table (configs + aliases) from the sibling
    highlight_code module, so 'is this a highlightable language' has a single source of truth.
    Returns ({}, {}) if the module cannot be imported (the check then no-ops)."""
    try:
        import highlight_code
    except ImportError:
        # _toolpath.ensure() (called at the CLI entrypoint) already puts every tools/ topic
        # directory - including blocks/, where highlight_code lives - on sys.path, so a failure
        # here means a broken/partial install, not a path gap. Make it VISIBLE and no-op.
        _toolpath.warn_missing_tool("highlight_code", "the highlightable-language table")
        return {}, {}
    return getattr(highlight_code, "LANGUAGE_CONFIGS", {}), getattr(highlight_code, "ALIASES", {})


def _code_block_language(attrs):
    """The XXX of a `language-XXX` class token on a parsed <code> element, or None.

    The ORDERED reading (`html_ws_tokens`), not the `class_tokens` set: this is a FIRST-WINS
    read, so a `class="language-python language-kusto"` must always answer `python` - out of a
    set it answered whichever token the process's hash seed put first. The `language-` PREFIX is
    folded ASCII-only, so a `LANGUAGE-` spelling is still a label while a `\u212a` look-alike is
    not a `k`; the LABEL itself is then normalized by the highlighter's own `str.lower()`, which
    folds the way a JS `toLowerCase()` does, so the two sides agree there too.
    """
    for token in html_ws_tokens(attrs.get("class")):
        if _ascii_lower(token).startswith("language-"):
            return token[len("language-"):]
    return None


def check_code_highlighting(html):
    """Return (errors, warnings) for author-time code-block highlighting. Warn when a
    `<pre><code class="language-XXX">` block declares a HIGHLIGHTABLE language but carries no
    `cmh-code-*` token spans, i.e. it was authored with a language label but never run through
    tools/highlight_code.py, so it renders as monochrome text. Only block code inside a <pre> is
    checked (inline <code> is never highlighted); a `language-text`/unknown label is skipped
    (not highlightable); an empty block is skipped. Blocks are LOCATED as PARSED ELEMENTS
    (checks/parsing.code_block_spans, shared with the KQL runnable scan CMH-KQL-08), so layer
    prose that merely mentions <pre>/<code> inside a script, style, comment, raw-text element
    or CDATA section contributes no block, and a `>` inside a quoted attribute cannot truncate
    a tag. Every payload is sliced from the ORIGINAL document, so the language, emptiness and
    highlight state are decided on the bytes that actually ship. All findings are warnings so
    --strict escalates them; the hand-written-markup finding is ADVISORY when the leftover
    markup is inert (the author cannot clear a deliberate hand-written block) and stays fatal
    when it could execute."""
    configs, aliases = _highlight_language_table()
    if not configs:
        return [], []
    warnings = []
    spans = code_block_spans(html)
    # Fail CLOSED when the structure is destroyed. A raw <script>, <style> or <!-- opened
    # INSIDE a `<pre><code>` and closed outside it swallows the intervening `</code>` (and
    # possibly the `</pre>`), so the block would disappear from the scan - and that is the
    # payload the fatal branch exists for (the browser's raw-text mode swallows those closers
    # too, and the script RUNS). The parser reports any `<pre>`/`<code>` that never got its
    # own end tag, which covers both levels: an unpaired `<pre>`, and - inside an otherwise
    # well-formed `<pre>` - an unpaired `<code>`, the shape that survives when the raw region
    # closes before `</pre>` does.
    if spans.failed:
        warnings.append(
            "the document could not be parsed to locate its code blocks, so none of them could "
            "be inspected - fix the markup (or report this document) rather than trusting a "
            "clean result")
    elif spans.unclosed:
        warnings.append(
            "a <pre> or <code> element has no matching closing tag in the authored markup - a "
            "raw <script>, <style> or <!-- comment opened inside it swallows the rest of the "
            "block, so it could not be inspected; escape it (< as &lt;, > as &gt;, & as &amp;)")
    for pre in spans.pres:
        for code in pre["codes"]:
            if code["inner"] is None:
                continue  # never closed; already reported through the fail-closed branch
            code_inner = html[code["inner"][0]:code["inner"][1]]
            raw_lang = _code_block_language(code["attrs"])
            if not raw_lang or not code_inner.strip():
                continue
            lang = raw_lang.strip().lower()
            lang = aliases.get(lang, lang)
            if lang not in configs and lang not in _KQL_LANGUAGES:
                continue  # a non-highlightable label (language-text, ...) is fine
            state = _highlight_core.classify(code_inner)
            if state == "highlighted":
                continue
            if state == "hand-written":
                # A substring probe for "cmh-code-" accepted malformed or hand-edited
                # spans, which is exactly what the strict scanner exists to catch.
                if _is_inert_markup(code_inner):
                    # Deliberate hand-highlighting: nothing to fix. Say so, rather than repeating
                    # the fatal branch's remediation for markup the tools keep on purpose.
                    warnings.append(
                        HIGHLIGHT_ADVISORY_PREFIX +
                        'a <pre><code class="language-%s"> block carries hand-written inert '
                        "markup the highlighter did not emit - it is preserved verbatim and the "
                        "authoring tools will not rewrite it, so no action is needed; remove the "
                        "language label only if you want the block re-highlighted" % raw_lang)
                else:
                    warnings.append(
                        'a <pre><code class="language-%s"> block carries markup the highlighter '
                        "did not emit (a nested, malformed, or hand-written span) and the "
                        "leftover markup is not inert - it can execute, load, or navigate once "
                        "the browser parses the <pre> body, so escape it (< as &lt;, > as &gt;, "
                        "& as &amp;)" % raw_lang)
                continue
            warnings.append(
                'a <pre><code class="language-%s"> block is not syntax-highlighted (no cmh-code-* '
                'spans) - run "python tools/highlight_code.py %s" over the code (or use '
                'highlight_block()) so it renders highlighted instead of as monochrome text'
                % (raw_lang, lang))
    return [], warnings
