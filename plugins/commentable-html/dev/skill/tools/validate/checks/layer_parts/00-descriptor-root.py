"""The commentable-html layer contract: `check_layer` (the orchestrator that runs
the region, id, root, descriptor, kind, resource, and content checks) and the
layer descriptor validation."""

import re
import json
from collections import Counter
from .parsing import CONTENT_BEGIN, CONTENT_END, DEMO_KEYS, DOC_EXAMPLE_COMMENT_KEY, FORBIDDEN_IDS, LAYER_DESCRIPTOR_ID, LAYER_JSON_IDS, REGIONS, REQUIRED_IDS, SAFE_ID_RE, _COMMENT_ROOT_ATTR_RE, _DATA_KEY_RE, _HTML_COMMENT_RE, _PRE_TAG_RE, _SCRIPT_STYLE_RE, _TITLE_RE, _TRANSIENT_BODY_CLASSES, _attrs_have_class, _find_tag_attrs, _is_executable_js, _is_json_attrs, _js_scan, _parser_script, _region_marker_matches, code_block_spans, content_marker_scan, layer_regions_text, parsed_attrs_have_class
from .resources import CHARTJS_SRC_RE, CSS_NETWORK_URL_RE, META_REFRESH_NETWORK_RE, NONPORTABLE_REGIONS, _check_nonportable, _is_adx_run_href, _is_nonportable, _link_loads, _offline_csp_errors
from .kind import check_document_kind, check_favicon, check_mermaid_renders, check_section_reference_links, check_section_wrapping
from .links import check_links


def _layer_descriptor_data(parser):
    scripts = [s for s in parser.scripts if s["attrs"].get("id") == LAYER_DESCRIPTOR_ID]
    if not scripts:
        return None
    try:
        data = json.loads((scripts[0]["body"] or "").strip())
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _check_layer_descriptor(parser, nonportable, active_regions):
    errors = []
    scripts = [s for s in parser.scripts if s["attrs"].get("id") == LAYER_DESCRIPTOR_ID]
    if not scripts:
        return ['missing <script id="%s" type="application/json"> layer descriptor' % LAYER_DESCRIPTOR_ID]
    if len(scripts) > 1:
        errors.append('<script id="%s"> appears %d times (must be unique)' % (LAYER_DESCRIPTOR_ID, len(scripts)))
    script = scripts[0]
    if not _is_json_attrs(script["attrs"]):
        errors.append('the <script id="%s"> block must be type="application/json"' % LAYER_DESCRIPTOR_ID)
    try:
        data = json.loads((script["body"] or "").strip())
    except json.JSONDecodeError as exc:
        errors.append("%s is not valid JSON: %s" % (LAYER_DESCRIPTOR_ID, exc))
        return errors
    if not isinstance(data, dict):
        errors.append("%s must be a JSON object" % LAYER_DESCRIPTOR_ID)
        return errors
    version = data.get("version")
    if not isinstance(version, str) or not version.strip():
        errors.append('%s.version must be a non-empty string' % LAYER_DESCRIPTOR_ID)
    mode = data.get("mode")
    if nonportable:
        if mode != "nonportable":
            errors.append('%s.mode must be "nonportable" for this document' % LAYER_DESCRIPTOR_ID)
    else:
        if mode not in ("portable", "offline"):
            errors.append('%s.mode must be "portable" or "offline" for this document' % LAYER_DESCRIPTOR_ID)
        if parser.has_offline_chart and mode != "offline":
            errors.append('%s.mode must be "offline" when offline chart snapshots are present' % LAYER_DESCRIPTOR_ID)
    if data.get("regions") != active_regions:
        errors.append("%s.regions must list exactly the active region markers in order: %s"
                      % (LAYER_DESCRIPTOR_ID, ", ".join(active_regions)))
    return errors


_CSS_STRING_ESCAPE = "\\"
# A browser applies a <style> only when its type is absent, empty, or text/css.
_CSS_STYLE_TYPES = ("", "text/css")


def _css_declarations_view(css):
    """Blank CSS comments and string CONTENTS to same-length spaces, keeping line breaks.

    What survives is exactly the part of a stylesheet that can be a selector or a declaration,
    which is what checks 9 and 10 ask about. Commented-out text is not a declaration (a quoted
    `--cp-bg:` must not SATISFY the theme ERROR, and a rule commented out while debugging must
    not still raise the unscoped-`[hidden]` warning), and neither is a string VALUE: live CSS
    such as `content: ".cm-skip[hidden] --cp-bg: x"` declares neither of them. Same-length
    blanking keeps the `(?m)^[ \\t]*` anchor of that warning's regex meaningful.

    This is a small LEXER rather than a regex because every one of these mistakes is reachable:
    `/*` and `*/` inside a quoted string are ordinary characters (treating them as delimiters
    would blank the LIVE declarations between them), an unterminated comment runs to end of
    input in a real parser (leaving it intact would let its text satisfy a check), and a string
    ENDS at a raw newline (a bad-string token), so a stray quote cannot swallow the rest of the
    stylesheet. Escapes are honored, so an escaped quote cannot end a string early and an
    escaped newline continues it.
    """
    out = list(css)
    i, n = 0, len(css)
    quote = None        # the quote character while inside a string
    string_at = -1      # where an open string's CONTENT began, or -1
    comment_at = -1     # where an open comment began, or -1
    while i < n:
        ch = css[i]
        if comment_at >= 0:
            if ch == "*" and i + 1 < n and css[i + 1] == "/":
                _blank_css_span(out, comment_at, i + 2)
                comment_at = -1
                i += 2
                continue
        elif quote is not None:
            if ch == _CSS_STRING_ESCAPE:
                i += 2
                continue
            if ch == quote or ch in "\r\n":
                # A newline ends the string as a bad-string token; the quote itself stays.
                _blank_css_span(out, string_at, i)
                quote = None
        elif ch in "\"'":
            quote = ch
            string_at = i + 1
        elif ch == "/" and i + 1 < n and css[i + 1] == "*":
            comment_at = i
            i += 2
            continue
        i += 1
    if comment_at >= 0:
        _blank_css_span(out, comment_at, n)  # end of input closes an open comment
    elif quote is not None:
        _blank_css_span(out, string_at, n)
    return "".join(out)


def _blank_css_span(out, start, end):
    for k in range(start, end):
        if out[k] not in "\r\n":
            out[k] = " "


def _layer_css(parser):
    """The document's live CSS, one stylesheet at a time.

    Each <style> is lexed INDEPENDENTLY because a browser parses it as its own stylesheet: an
    unterminated comment in one cannot comment out a later element's rules, which - when the
    bodies were joined first - let a stray `/*` anywhere hide a live unscoped reset from
    check 9. A non-CSS `type` is dropped for the same reason it renders nothing.
    """
    bodies = []
    for style in getattr(parser, "styles", []):
        attrs = style.get("attrs") or {}
        if (attrs.get("type") or "").strip().lower() not in _CSS_STYLE_TYPES:
            continue
        bodies.append(_css_declarations_view(style.get("body") or ""))
    return "\n".join(bodies)


def _check_content_markers(html, parser):
    errors, warnings = [], []
    # Count in the SAME view the layer checks locate the markers in (CMH-VAL-20): a marker quoted
    # inside <script>/<style> data is not a real boundary, so counting it here would both forge a
    # spurious duplicate-marker error and let this check disagree with the layer view about where
    # the content region is.
    scan = content_marker_scan(html)
    content_begin_count = scan.count(CONTENT_BEGIN)
    content_end_count = scan.count(CONTENT_END)
    # A marker the mask removed but the raw text still has is one a <script>/<style> body
    # SWALLOWED. Reporting "found 0" there would be true but useless - the author can see the
    # marker in their file - so fall through to the well-formed-region diagnostic below, which
    # names that exact cause.
    swallowed = ((content_begin_count == 0 and html.count(CONTENT_BEGIN) >= 1)
                 or (content_end_count == 0 and html.count(CONTENT_END) >= 1))
    if content_begin_count != 1 and not swallowed:
        errors.append("CONTENT region: expected 1 BEGIN marker, found %d" % content_begin_count)
    if content_end_count != 1 and not swallowed:
        errors.append("CONTENT region: expected 1 END marker, found %d" % content_end_count)
    if content_begin_count == 1 and content_end_count == 1 and scan.index(CONTENT_BEGIN) >= scan.index(CONTENT_END):
        errors.append("CONTENT region: END marker appears before its BEGIN marker")
    elif swallowed or (content_begin_count == 1 and content_end_count == 1 and not (
            parser.content_region_opened and parser.content_region_closed)):
        # The markers are in the TEXT, but the document does not PARSE with a well-formed region.
        # That matters because the layer view (which decides NonPortable mode and its checks) is
        # derived from the parse: if the region a browser sees does not open inside #commentRoot
        # and close again, the layer's own markup cannot be told apart from authored content, and
        # markup after the broken boundary would be silently misattributed. Refuse rather than
        # guess. Causes: a marker inside a <script>/<style> body or an inert <template>, a marker
        # outside #commentRoot, or unbalanced markup closing #commentRoot mid-region.
        errors.append("CONTENT region: the markers are present in the text but the document does "
                      "not parse with a well-formed region inside #commentRoot (a marker swallowed "
                      "by a <script>/<style> body or a <template>, a marker outside #commentRoot, "
                      "or unbalanced markup closing #commentRoot before the END marker) - fix the "
                      "markup so the region opens and closes where it reads")
    return errors, warnings


def _check_comment_root(parser, html):
    errors, warnings = [], []
    # 3) #commentRoot present (real element id, via the parser) with required data-* attributes.
    n_roots = parser.all_ids.count("commentRoot")
    if n_roots == 0:
        errors.append('no element with id="commentRoot" (content root is missing)')
    elif n_roots > 1:
        errors.append(f'id="commentRoot" appears {n_roots} times (must be unique)')
    else:
        attrs = parser.comment_root_attrs or {}
        if "data-cmh-content-root" not in attrs:
            errors.append('#commentRoot is missing data-cmh-content-root (stable hook for content/infra tooling)')
        if not attrs.get("data-comment-key", "").strip():
            errors.append('#commentRoot is missing a non-empty data-comment-key (the layer falls back to "commentable-html:" + location.pathname, but set an explicit key so comments do not collide across pages on the same origin)')
        if not attrs.get("data-doc-label", "").strip():
            warnings.append("#commentRoot has no data-doc-label (falls back to document.title / location.pathname; set it for a stable label in review loops)")
        if not attrs.get("data-doc-source", "").strip():
            warnings.append("#commentRoot has no data-doc-source (falls back to location.pathname; set it for real review loops)")
        # 3a) The ACTIVE content root must not still be a pristine template demo. If
        #     a retrofit changed the <title> but left the demo content root in place,
        #     the demo - not the consumer's content - renders. The generated templates
        #     keep their own demo <title>, so this stays green for them.
        _active_key = attrs.get("data-comment-key", "").strip()
        if _active_key in DEMO_KEYS:
            _tm = _TITLE_RE.search(html)
            _title = (_tm.group(1).strip() if _tm else "")
            if _title and _title != DEMO_KEYS[_active_key]:
                errors.append(
                    'the active #commentRoot still uses the template demo '
                    'data-comment-key "%s" while the document <title> was customized '
                    "- the demo content root survived the retrofit; give your content "
                    "root a unique data-comment-key and replace the demo body"
                    % _active_key)
        elif _active_key == DOC_EXAMPLE_COMMENT_KEY:
            errors.append(
                'the active #commentRoot uses documentation example data-comment-key "%s"; '
                "give the live root a unique data-comment-key"
                % DOC_EXAMPLE_COMMENT_KEY)

    # 3b) No REAL content root may be hidden inside an HTML comment. Guards the
    #     retrofit failure where a script replaced the WRONG "<main id=commentRoot>"
    #     so the consumer's real content ends up commented out and the browser renders
    #     the leftover demo. The only sanctioned commented root is the
    #     data-comment-key="my-doc" documentation example (the placeholder authoring
    #     guidance uses); any other commented content root (a different key, or none)
    #     means content was commented by mistake. Scan with <script>/<style> bodies
    #     blanked so comment-like text inside them (which the browser treats as
    #     script/style data, not a comment) is ignored.
    _comment_scan_src = _SCRIPT_STYLE_RE.sub(" ", html)
    for _cm in _HTML_COMMENT_RE.finditer(_comment_scan_src):
        _block = _cm.group(0)
        _hit = False
        for _rm in _COMMENT_ROOT_ATTR_RE.finditer(_block):
            _win = _block[max(0, _rm.start() - 40):_rm.end() + 300]
            _km = _DATA_KEY_RE.search(_win)
            if not _km or _km.group(1) != DOC_EXAMPLE_COMMENT_KEY:
                _hit = True
                break
        if _hit:
            errors.append(
                'an element with id="commentRoot" is inside an HTML comment '
                "(per-document content was commented out during retrofit); only the "
                'template documentation example (data-comment-key="%s") may be '
                "commented" % DOC_EXAMPLE_COMMENT_KEY)
            break
    return errors, warnings


def _check_element_ids(parser, html):
    errors, warnings = [], []
    # 7) Required UI ids present exactly once (a duplicate means a decoy could
    # satisfy the check while the real control is missing, and getElementById may
    # bind the layer to the wrong element).
    id_counts = Counter(parser.all_ids)
    for uid in REQUIRED_IDS:
        c = id_counts.get(uid, 0)
        if c == 0:
            errors.append(f'required element id="{uid}" is missing')
        elif c > 1:
            errors.append(f'required element id="{uid}" appears {c} times (must be unique)')

    # 7b) The document-owned JSON script blocks must also be unique across the
    # whole active DOM. A duplicated id makes getElementById() bind to a decoy,
    # silently reading/writing the wrong element. Absence is already reported by
    # dedicated checks above, so only flag duplicates.
    for uid in sorted(LAYER_JSON_IDS):
        c = id_counts.get(uid, 0)
        if c > 1:
            if uid == LAYER_DESCRIPTOR_ID:
                errors.append(f'id="{uid}" appears {c} times (must be unique)')
            else:
                errors.append(f'<script id="{uid}"> appears {c} times (must be unique)')

    # 8) Export/Import must stay removed (dropped before the 1.0.0 release). The structural
    #    detector is FORBIDDEN_IDS over the parsed DOM. The retired MARKER text is a secondary
    #    heuristic, so it is probed with an ALLOW-list - the layer's own region spans only
    #    (CMH-VAL-20). A deny-list ("the whole document minus the parts a user writes") cannot
    #    work here: `new_document --label` copies the label verbatim into both `<title>` and
    #    `data-doc-label`, so naming a document after the retired marker raised a warning the
    #    author could only clear by renaming it - exactly the false positive this rule removes.
    present_forbidden = [uid for uid in FORBIDDEN_IDS if uid in id_counts]
    if present_forbidden or "--START-COMMENTS-EXPORT--" in layer_regions_text(html):
        warnings.append("Export/Import UI detected - this was removed before the 1.0.0 release (redundant with Export with embedded comments): "
                        + ", ".join(present_forbidden or ["--START-COMMENTS-EXPORT-- marker"]))
    return errors, warnings


def _check_theme_and_skip(html, parser, nonportable):
    errors, warnings = [], []
    # 9/10) These ask about CSS, so they read real <style> BODIES rather than document text
    # (CMH-VAL-20). Text is not a stylesheet: scanning the raw document let authored prose, a
    # reviewer's embedded comment, or even a layer <script> that merely MENTIONS `--cp-bg:`
    # satisfy - or forge - a verdict about what the document actually declares. Every parsed
    # CSS <style> counts wherever it sits, because one an author puts in their own content is
    # still live CSS that really would style (or hide) the page: the narrowing is by CSS-ness,
    # not by region, which is also why a code sample SHOWING a rule is correctly not a rule.
    css = _layer_css(parser)
    if re.search(r"(?m)^[ \t]*\[hidden\]\s*\{\s*display:\s*none", css):
        warnings.append("found an unscoped '[hidden] { display: none }' rule - scope it to '.cm-skip[hidden], .cm-skip [hidden]' so it cannot hide host elements")
    if not nonportable and ".cm-skip[hidden]" not in css:
        warnings.append("missing the scoped '.cm-skip[hidden]' rule (the layer's own hidden elements may not hide)")

    # 10) The --cp-* theme variables must be DEFINED.
    if not re.search(r"--cp-bg\s*:", css):
        errors.append("the --cp-* theme variables are not defined (looked for a '--cp-bg:' declaration; the layer and its host will render unstyled)")

    # 11) Mermaid blocks should keep cm-skip.
    if any(not mb["cm_skip"] for mb in parser.mermaid_blocks):
        warnings.append("a mermaid block is missing class \"cm-skip\" (its source text becomes selectable)")
    for block in getattr(parser, "cm_skip_code_blocks", []):
        warnings.append(
            'a non-mermaid %s block has class "cm-skip" and will not be commentable; '
            "remove cm-skip unless it is host chrome"
            % block["kind"])
    return errors, warnings
