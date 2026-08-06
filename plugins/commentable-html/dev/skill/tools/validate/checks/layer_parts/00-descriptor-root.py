"""The commentable-html layer contract: `check_layer` (the orchestrator that runs
the region, id, root, descriptor, kind, resource, and content checks) and the
layer descriptor validation."""

import re
import json
from collections import Counter
from .parsing import SPECULATIVE_LINK_RELS, FETCHING_LINK_RELS, CONTENT_BEGIN, CONTENT_END, DEMO_KEYS, DOC_EXAMPLE_COMMENT_KEY, FORBIDDEN_IDS, LAYER_DESCRIPTOR_ID, LAYER_JSON_IDS, MARKER_KINDS, REGIONS, REQUIRED_IDS, SAFE_ID_RE, UNIQUE_JSON_IDS, _COMMENT_ROOT_ATTR_RE, _DATA_KEY_RE, _HTML_COMMENT_RE, _PRE_TAG_RE, _SCRIPT_STYLE_RE, _TITLE_RE, _TRANSIENT_BODY_CLASSES, _ascii_lower, _attrs_have_class, _find_event_handler_attrs_egress, _find_noscript_inline_styles, _find_noscript_styles, _find_tag_attrs, _find_tag_attrs_egress, _is_executable_js, _is_json_attrs, _js_scan, _parser_script, _region_marker_matches, _tag_attrs_failed, code_block_spans, content_marker_scan, layer_regions_text, link_rel_tokens, raw_text_spans, parsed_attrs_have_class, class_tokens, html_ws_tokens
from .resources import CHARTJS_SRC_RE, CSS_NETWORK_IMPORT_RE, CSS_NETWORK_URL_RE, NONSHAREABLE_REGIONS, REFERRER_POLICY_ELEMENTS, SCRIPT_LOAD_ATTRS, _check_nonshareable, _is_adx_run_href, _is_nonshareable, _link_loads, _link_speculates, _offline_csp_errors, is_network_url, meta_refresh_navigates_to_network, offline_active_data_block_is_removable, offline_active_data_script_type, offline_head_noscript_promotions, offline_is_non_local_ref, offline_script_navigates_to_network, referrer_meta_policy, referrer_policy_attr, srcset_candidate_urls
from .kind import check_document_kind, check_favicon, check_mermaid_renders, check_section_reference_links, check_section_wrapping, check_shadow_root_exports
from .links import check_links


# Layer-descriptor mode values. The SECOND entry of each tuple is the PRE-RENAME spelling
# ("portable" / "nonportable"): it is baked into every document produced before the rename, so it
# stays accepted with identical behavior and those documents keep validating with no error and no
# warning. Do not drop it.
SHAREABLE_MODES = ("shareable", "portable")
NONSHAREABLE_MODES = ("nonshareable", "nonportable")


def _descriptor_scripts(parser):
    """Every `<script id="commentableHtmlLayer">` the LAYER owns, in document order.

    The boundary is the one the runtime and the exporter already enforce: `cmhLayerBlocks`
    (`assets/js/01-config.js`) drops any owner the content ROOT contains, because "a
    content-region decoy must not be able to declare what this document IS", and
    `65-export-shareable.js` refuses a document whose only owner sits there. Reading the whole
    document instead certified a file the layer resolves no descriptor for and no export will
    produce - and, since the DECLARED mode became the sole key for the offline rule set, let
    authored content pick the rule set that judges it.

    The boundary is the whole `#commentRoot` SUBTREE, not just the part between the CONTENT
    markers, because that is what `cmhLayerBlocks` tests (`root.contains(node)`): a descriptor
    parked inside the root but ahead of the BEGIN marker is equally invisible to the layer. That
    subtree contains the authored region, so the authored-DEMONSTRATION case `layer_tags` handles
    is covered by the same test.
    """
    return [s for s in parser.scripts
            if s["attrs"].get("id") == LAYER_DESCRIPTOR_ID and not _in_content_root(s)]


def _in_content_root(script):
    """Whether the `#commentRoot` subtree contains this script.

    An ABSENT flag fails CLOSED (treated as inside the root, so not layer-owned): every entry
    `_flush_raw_captures` puts in `parser.scripts` carries it, and a future writer that forgot it
    must not silently revert this boundary to the "first script anywhere" rule it replaced. The
    sibling `in_content` flag is deliberately NOT consulted - it is this flag AND the marker
    region by construction, so it can never be true when this one is false.
    """
    return bool(script.get("in_content_root", True))


def _missing_descriptor_error(parser):
    msg = 'missing <script id="%s" type="application/json"> layer descriptor' % LAYER_DESCRIPTOR_ID
    if any(s["attrs"].get("id") == LAYER_DESCRIPTOR_ID and _in_content_root(s)
           for s in parser.scripts):
        # Say WHY, as the runtime and the exporter do: the element is right there in the file.
        # Phrased without an ownership COUNT, because this predicate only proves that at least
        # one such script is inside the root - a duplicate, or a non-script owner elsewhere, is
        # reported by the dedicated uniqueness checks instead.
        msg += (" - a <script> carrying that id sits inside the content root, where authored"
                " content lives, so the layer does not resolve it; move the descriptor above the"
                " content root (or re-generate the document)")
    return msg


def _layer_descriptor_data(parser):
    scripts = _descriptor_scripts(parser)
    if not scripts:
        return None
    try:
        data = json.loads((scripts[0]["body"] or "").strip())
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _check_layer_descriptor(parser, nonshareable, active_regions):
    errors = []
    scripts = _descriptor_scripts(parser)
    if not scripts:
        return [_missing_descriptor_error(parser)]
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
    # An offline chart snapshot is the artifact of a self-contained offline document (a legacy
    # Offline export produced them; today's export inlines Chart.js and keeps the live canvas), so
    # its presence and the declared mode must agree in BOTH branches. A NonShareable document
    # loads its layer from companion files and can never be a self-contained one, so a snapshot
    # there is a contradiction rather than a stale mode (CMH-OFFLINE-09); scoping the rule to the
    # non-NonShareable branch alone left that shape blessed here while the runtime's legacy
    # snapshot signal still read it as offline. The snapshot rule stands on its own rather than
    # hanging off the mode check: a document whose mode is ALSO wrong learns both problems in one
    # pass instead of one per run, which is why the message quotes whatever mode it declares.
    if nonshareable:
        if mode not in NONSHAREABLE_MODES:
            errors.append('%s.mode must be "nonshareable" for this document' % LAYER_DESCRIPTOR_ID)
        if parser.has_offline_chart:
            errors.append("%s.mode is %s but the document carries offline chart snapshots inside "
                          "#commentRoot; a document that loads its layer from companion files is "
                          "not self-contained and can never be offline - remove the reserved "
                          "data-cm-offline-chart attribute (the image itself can stay), or use "
                          "Export Offline, which produces a self-contained offline file"
                          % (LAYER_DESCRIPTOR_ID, json.dumps(mode)))
    else:
        if mode not in SHAREABLE_MODES + ("offline",):
            errors.append('%s.mode must be "shareable" or "offline" for this document' % LAYER_DESCRIPTOR_ID)
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
        # That matters because the layer view (which decides NonShareable mode and its checks) is
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
    # Same split as _check_element_ids (CMH-VAL-26), including that the two halves are reported
    # INDEPENDENTLY: PRESENCE is namespace-SCOPED, because the runtime drives the content root as
    # an HTMLElement (it renders the authored document inside it, and every export re-serializes
    # it), while a `<math>`/`<svg>` carrier - reachable through an HTML integration point, where
    # the CONTENT-region parse succeeds and nothing else objects - is an SVGElement/MathMLElement
    # that cannot host it. DUPLICATES stay namespace-BLIND, because `getElementById` is: a foreign
    # root beside the real one can win the lookup. Coupling the two would report an all-foreign
    # collision as a collision alone, so removing one carrier would reveal a second error that was
    # there all along.
    n_roots = parser.html_ids.count("commentRoot")
    n_any = parser.all_ids.count("commentRoot")
    if n_roots == 0:
        if n_any:
            errors.append('the element with id="commentRoot" is outside the HTML namespace (an '
                          "SVG/MathML element cannot host the authored document the layer renders "
                          "and re-serializes) - the content root must be an HTML element")
        else:
            errors.append('no element with id="commentRoot" (content root is missing)')
    if n_any > 1:
        errors.append(f'id="commentRoot" appears {n_any} times (must be unique)')
    # The data-* audit needs an UNAMBIGUOUS root: `comment_root_attrs` is latched by the first
    # carrier in any namespace, so with a duplicate it may not be the one this check blessed.
    if n_roots == 1 and n_any == 1:
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
    # The two halves read DIFFERENT views on purpose (CMH-VAL-26). PRESENCE is namespace-SCOPED:
    # the layer's companion UI is HTML, and `hidden` - the toggle it uses to reveal and hide many
    # of these controls - is an IDL attribute of `HTMLElement` alone, so `el.hidden = true` on an
    # SVG/MathML carrier writes a plain JS expando, sets no content attribute, and matches neither
    # the UA rule nor the layer's own `.cm-skip[hidden]` rule. DUPLICATES stay namespace-BLIND and
    # are reported INDEPENDENTLY of presence, because `getElementById` really is blind for
    # collisions: a foreign element sharing the id can win the lookup and shadow the real control,
    # and that is just as true when every carrier is foreign. An id at an HTML integration point
    # (`<svg><foreignObject>`, `<math><mtext>`, `<math><annotation-xml encoding="text/html">` or
    # `"application/xhtml+xml"`) counts for both, because a browser really inserts that element in
    # the HTML namespace.
    # The floor this raises is real but partial: the check asks which NAMESPACE the control is in,
    # never whether it renders. It is tag-agnostic (the shipped layer uses a `<span>` for a
    # button), and an HTML element that cannot be seen - in `<head>`, under `display:none`, or
    # under a non-rendering `<svg><title>` - still satisfies it, exactly as before.
    id_counts = Counter(parser.all_ids)
    html_id_counts = Counter(parser.html_ids)
    for uid in REQUIRED_IDS:
        c = id_counts.get(uid, 0)
        if html_id_counts.get(uid, 0) == 0:
            if c:
                carriers = ("the only element carrying it is" if c == 1
                            else f"all {c} elements carrying it are")
                errors.append(f'required element id="{uid}" is missing - {carriers} outside the '
                              "HTML namespace (`hidden` is an HTMLElement-only IDL attribute, so "
                              "the toggle the layer uses to reveal many of these controls does "
                              "nothing on an SVG/MathML element, which cannot take the place of "
                              "the HTML control either way)")
            else:
                errors.append(f'required element id="{uid}" is missing')
        if c > 1:
            errors.append(f'required element id="{uid}" appears {c} times (must be unique)')

    # 7b) The document-owned JSON script blocks must also be unique across the
    # whole active DOM. A duplicated id makes getElementById() bind to a decoy,
    # silently reading/writing the wrong element. Absence is already reported by
    # dedicated checks above, so only flag duplicates.
    for uid in sorted(UNIQUE_JSON_IDS):
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


def _check_theme_and_skip(html, parser, nonshareable):
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
    if not nonshareable and ".cm-skip[hidden]" not in css:
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
