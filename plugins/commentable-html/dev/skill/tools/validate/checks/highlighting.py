"""Author-time code-block syntax-highlighting checks (a language-labelled block
that shipped without highlight spans)."""

import _toolpath
from .parsing import _CLASS_ATTR_RE, _CODE_TAG_RE, _PRE_TAG_RE

_toolpath.ensure()
import _highlight_core  # noqa: E402

# Kusto labels the document highlight path bakes via the KQL tokenizer (CMH-KQL-09), so
# an unhighlighted one is a real warning here rather than an ignorable label.
_KQL_LANGUAGES = frozenset(("kusto", "kql"))


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
    """The XXX of a `language-XXX` class token on a <code> element, or None."""
    for m in _CLASS_ATTR_RE.finditer(attrs):
        value = next((g for g in m.groups() if g is not None), "")
        for token in value.split():
            if token.lower().startswith("language-"):
                return token[len("language-"):]
    return None


def check_code_highlighting(html):
    """Return (errors, warnings) for author-time code-block highlighting. Warn when a
    `<pre><code class="language-XXX">` block declares a HIGHLIGHTABLE language but carries no
    `cmh-code-*` token spans, i.e. it was authored with a language label but never run through
    tools/highlight_code.py, so it renders as monochrome text. Only block code inside a <pre> is
    checked (inline <code> is never highlighted); a `language-text`/unknown label is skipped
    (not highlightable); an empty block is skipped. All findings are warnings so --strict
    escalates them while a highlight-free document is unaffected."""
    configs, aliases = _highlight_language_table()
    if not configs:
        return [], []
    warnings = []
    for pm in _PRE_TAG_RE.finditer(html):
        for cm in _CODE_TAG_RE.finditer(pm.group(2)):
            code_attrs, code_inner = cm.group(1), cm.group(2)
            raw_lang = _code_block_language(code_attrs)
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
                warnings.append(
                    'a <pre><code class="language-%s"> block carries markup the highlighter '
                    "did not emit (a nested, malformed, or hand-written span) - the authoring "
                    "tools will refuse to rewrite it, so fix the markup or remove the "
                    "language label" % raw_lang)
                continue
            warnings.append(
                'a <pre><code class="language-%s"> block is not syntax-highlighted (no cmh-code-* '
                'spans) - run "python tools/highlight_code.py %s" over the code (or use '
                'highlight_block()) so it renders highlighted instead of as monochrome text'
                % (raw_lang, lang))
    return [], warnings
