"""Document-kind, section-reference-link, and mermaid-render structural checks."""

import re

# Document kind. Every commentable-html document declares its kind in a
# <meta name="commentable-html-kind" content="..."> so per-type rules can apply and
# the document is self-describing. Title-bearing kinds (a report or a plan) must carry
# a top-level <h1> in #commentRoot; a slide deck, a board, or a generic document does
# not. The set is intentionally small and closed so an unknown kind is a clear error.
_KIND_META_NAME = "commentable-html-kind"

_DOC_KINDS = ("report", "plan", "slides", "board", "generic")

_KINDS_REQUIRING_H1 = ("report", "plan")

_SECTION_DIR_RE = re.compile(
    r'\b(?:section|appendix|sub-?section|chapter)s?\s+(?:above|below)\b'
    r'|\b(?:above|below|previous|next|following|preceding|earlier|later|prior)\s+'
    r'(?:section|appendix|sub-?section|chapter)s?\b',
    re.IGNORECASE)


def check_document_kind(parser):
    """Require a declared document kind and enforce its per-type rules.

    Every commentable-html document carries a <meta name="commentable-html-kind"
    content="..."> declaring one of _DOC_KINDS. The kind is mandatory (so the document
    is self-describing and per-type rules can apply) and title-bearing kinds (report,
    plan) must have a top-level <h1> in #commentRoot; a slide deck, a board, or a generic
    document is exempt. Returns a list of error strings.
    """
    kind = (parser.metas.get(_KIND_META_NAME) or "").strip().lower()
    if not kind:
        return ['missing <meta name="%s" content="..."> - declare the document kind '
                "(one of: %s)" % (_KIND_META_NAME, ", ".join(_DOC_KINDS))]
    if kind not in _DOC_KINDS:
        return ['unknown document kind "%s" in <meta name="%s"> - use one of: %s'
                % (kind, _KIND_META_NAME, ", ".join(_DOC_KINDS))]
    if kind in _KINDS_REQUIRING_H1:
        # A visible top-level <h1> satisfies the title: either a direct child of #commentRoot,
        # or one wrapped in a top-level <header class="cmh-lede"> (an empty cmh-lede does NOT).
        has_top_level_h1 = any(h.get("tag") == "h1" and (h.get("text") or "").strip()
                               and (h.get("top_level") or h.get("in_lede")) for h in parser.headings)
        if not has_top_level_h1:
            return ['kind "%s" requires a top-level <h1> title inside #commentRoot, but the '
                    "document has none - add a top-level <h1> (or a top-level "
                    '<header class="cmh-lede"> title), or set the kind to '
                    '"slides", "board", or "generic" if no title is wanted' % kind]
    return []


def check_section_reference_links(parser):
    """Warn when a section cross-reference in #commentRoot prose is NOT a link.

    Only UNLINKED text reaches parser.commentroot_prose (link text and cm-skip are
    excluded), so every hit is a plain-text cross reference that the content conventions
    say should be an in-page anchor. Detection is deterministic; the fix (wrapping it in
    an <a href="#section-id">) is left to the author/agent.
    """
    prose = re.sub(r"\s+", " ", "".join(parser.commentroot_prose)).strip()
    if not prose:
        return []
    hits = []
    for m in _SECTION_DIR_RE.finditer(prose):
        hits.append(m.group(0).strip())
    # Named references: "see <Heading>" / "refer to <Heading>" / "<Heading> section",
    # where <Heading> is an actual heading title in this document (so it is linkable).
    titles = sorted({h["text"] for h in parser.headings if h.get("text") and len(h["text"]) >= 3},
                    key=len, reverse=True)
    if len(parser.headings) >= 2:
        for title in titles:
            t = re.escape(title)
            named = re.compile(
                r'\b(?:see|refer(?:s|red)?\s+to)\s+(?:the\s+)?[\u2018\u2019\'"]?' + t + r'\b'
                r'|\b' + t + r'\s+section\b',
                re.IGNORECASE)
            m = named.search(prose)
            if m:
                hits.append(m.group(0).strip())
    if not hits:
        return []
    seen = []
    for h in hits:
        if h.lower() not in {s.lower() for s in seen}:
            seen.append(h)
    sample = "; ".join(seen[:5])
    more = "" if len(seen) <= 5 else (" (and %d more)" % (len(seen) - 5))
    return ['section cross-reference(s) in prose are not links: "%s"%s - wrap each in an '
            'in-page anchor (<a href="#section-id">...</a>) per the content conventions '
            '(give the target heading a stable id)' % (sample, more)]


def check_mermaid_renders(parser):
    """Warn when the document has mermaid diagrams that will NOT render on open.

    A doc with pre/div.mermaid blocks needs a loader script that imports mermaid AND
    triggers a render (m.run() or startOnLoad:true), and that loader must not be hidden
    behind a URL query-param gate. Deterministic detection; otherwise the diagrams
    silently stay as source text, which reads as "mermaid is broken".
    """
    if not parser.mermaid_blocks:
        return []
    if all(mb.get("has_svg") for mb in parser.mermaid_blocks):
        return []
    loader = None
    for s in parser.scripts:
        body = s.get("body") or ""
        if re.search(r"mermaid", body, re.I) and (
                "import(" in body or re.search(r"mermaid\.(?:esm|min)", body, re.I)
                or re.search(r"\bmermaid\.(?:initialize|run)\b", body)):
            loader = body
            break
    if loader is None:
        return ["the document has mermaid diagram(s) (pre/div.mermaid) but no mermaid loader "
                "script was found - the diagrams will not render (they stay as source text); "
                "add a mermaid loader that imports mermaid and calls run()"]
    if not (re.search(r"\.run\s*\(", loader) or re.search(r"startOnLoad\s*:\s*true", loader)):
        return ["the mermaid loader never triggers a render (no .run() call and startOnLoad is "
                "not true), so the diagrams will not render"]
    if re.search(r"URLSearchParams", loader) and re.search(r"\.get\(\s*[\"']mermaid[\"']\s*\)", loader):
        return ["the mermaid loader only runs when a URL query parameter is set (e.g. ?mermaid=1), "
                "so the diagrams will NOT render by default - remove the query-param gate so "
                "mermaid renders when the file is opened normally"]
    return []
