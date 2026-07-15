"""The commentable-html layer contract: `check_layer` (the orchestrator that runs
the region, id, root, descriptor, kind, resource, and content checks) and the
layer descriptor validation."""

import re
import json
from collections import Counter
from .parsing import CONTENT_BEGIN, CONTENT_END, DEMO_KEYS, DOC_EXAMPLE_COMMENT_KEY, FORBIDDEN_IDS, LAYER_DESCRIPTOR_ID, LAYER_JSON_IDS, REGIONS, REQUIRED_IDS, SAFE_ID_RE, _COMMENT_ROOT_ATTR_RE, _DATA_KEY_RE, _HTML_COMMENT_RE, _PRE_TAG_RE, _SCRIPT_STYLE_RE, _TITLE_RE, _TRANSIENT_BODY_CLASSES, _attrs_have_class, _find_tag_attrs, _is_executable_js, _is_json_attrs, _js_scan, _parser_script, _region_marker_matches
from .resources import CHARTJS_SRC_RE, CSS_NETWORK_URL_RE, META_REFRESH_NETWORK_RE, NONPORTABLE_REGIONS, _check_nonportable, _is_adx_run_href, _is_nonportable, _link_loads, _offline_csp_errors
from .kind import check_document_kind, check_mermaid_renders, check_section_reference_links, check_section_wrapping


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


def _check_content_markers(html):
    errors, warnings = [], []
    content_begin_count = html.count(CONTENT_BEGIN)
    content_end_count = html.count(CONTENT_END)
    if content_begin_count != 1:
        errors.append("CONTENT region: expected 1 BEGIN marker, found %d" % content_begin_count)
    if content_end_count != 1:
        errors.append("CONTENT region: expected 1 END marker, found %d" % content_end_count)
    if content_begin_count == 1 and content_end_count == 1 and html.index(CONTENT_BEGIN) >= html.index(CONTENT_END):
        errors.append("CONTENT region: END marker appears before its BEGIN marker")
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

    # 8) Export/Import must stay removed (dropped before the 1.0.0 release).
    present_forbidden = [uid for uid in FORBIDDEN_IDS if uid in id_counts]
    if present_forbidden or "--START-COMMENTS-EXPORT--" in html:
        warnings.append("Export/Import UI detected - this was removed before the 1.0.0 release (redundant with Export with embedded comments): "
                        + ", ".join(present_forbidden or ["--START-COMMENTS-EXPORT-- marker"]))
    return errors, warnings


def _check_theme_and_skip(html, parser, nonportable):
    errors, warnings = [], []
    # 9) The global [hidden] reset must be scoped to the layer.
    if re.search(r"(?m)^[ \t]*\[hidden\]\s*\{\s*display:\s*none", html):
        warnings.append("found an unscoped '[hidden] { display: none }' rule - scope it to '.cm-skip[hidden], .cm-skip [hidden]' so it cannot hide host elements")
    if not nonportable and ".cm-skip[hidden]" not in html:
        warnings.append("missing the scoped '.cm-skip[hidden]' rule (the layer's own hidden elements may not hide)")

    # 10) The --cp-* theme variables must be DEFINED.
    if not re.search(r"--cp-bg\s*:", html):
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


def _check_diff_blocks(html):
    errors, warnings = [], []
    # 11b) An authored diff block (<pre class="cmh-diff">) must carry ESCAPED diff
    #      text: a raw HTML tag inside it is parsed and can execute before the diff
    #      layer runs, so an unescaped diff is an HTML-injection hazard and must
    #      FAIL validation (like the chart-JSON breakout checks), not just warn.
    #      Only inspect <pre> sources (a rendered/exported host is a
    #      <div class="cmh-diff-host"> full of the layer's own safe markup).
    _diff_n = 0
    for m in _PRE_TAG_RE.finditer(html):
        if not _attrs_have_class(m.group(1), "cmh-diff"):
            continue
        _diff_n += 1
        _bad = re.search(r"<\s*[a-zA-Z!/]", m.group(2))
        if _bad:
            _snip = m.group(2)[_bad.start():_bad.start() + 24].replace("\n", " ")
            errors.append('diff block #%d (<pre class="cmh-diff">) contains a raw HTML tag (%r) - '
                          'escape the diff text (< as &lt;, > as &gt;, & as &amp;) so embedded '
                          'markup cannot execute before the diff renders' % (_diff_n, _snip))
    return errors, warnings


def _check_kql_blocks(html):
    errors, warnings = [], []
    # 11c) "Run in Azure Data Explorer" links (class cmh-kql-run) must point at the ADX web UX over
    #      https and open safely. This fires ONLY on the explicit run-link class, so
    #      it never false-positives on a plain KQL code block or a syntax example.
    for a in _find_tag_attrs(html, "a"):
        if "cmh-kql-run" not in (a.get("class") or "").split():
            continue
        href = a.get("href", "")
        if not href.startswith("https://dataexplorer.azure.com/"):
            warnings.append('a "cmh-kql-run" link does not point at https://dataexplorer.azure.com/ '
                            "(build it with tools/kusto_link.py): " + (href[:80] or "(empty href)"))
        if a.get("target", "") == "_blank" and "noopener" not in (a.get("rel") or "").lower().split():
            warnings.append('a "cmh-kql-run" link uses target="_blank" without rel="noopener" '
                            "(reverse-tabnabbing risk); add rel=\"noopener noreferrer\"")

    # 11d) A framed KQL figure (figure.cmh-kql) must carry a working "Run in Azure Data Explorer"
    #      link (a real <a class="cmh-kql-run"> element) so the reader can open the query in ADX.
    #      A missing run link is a hard ERROR; so is a PRESENT run link whose href is not an
    #      https URL on host dataexplorer.azure.com (a javascript:/data:/non-ADX href must never
    #      pass). The run link is detected by an actual <a> element carrying the cmh-kql-run class
    #      token (parsed, entity-decoded) - NOT a raw substring - so query text that merely
    #      mentions "cmh-kql-run" does not satisfy the requirement. Bare, unframed KQL in a plain
    #      <pre> is intentionally exempt (an illustrative query belongs in a <pre> code block).
    for fm in re.finditer(r"<figure\b([^>]*)>(.*?)</figure>", html, re.IGNORECASE | re.DOTALL):
        if not _attrs_have_class(fm.group(1), "cmh-kql"):
            continue
        run_links = [a for a in _find_tag_attrs(fm.group(2), "a")
                     if "cmh-kql-run" in (a.get("class") or "").split()]
        if not run_links:
            errors.append('a figure.cmh-kql has no "Run in Azure Data Explorer" link (class cmh-kql-run); '
                          "build one with tools/kusto_link.py so readers can open the query in ADX "
                          "(or use a plain <pre> code block if the query is purely illustrative)")
            continue
        for a in run_links:
            if not _is_adx_run_href(a.get("href", "")):
                errors.append('a figure.cmh-kql "Run in Azure Data Explorer" link (class cmh-kql-run) '
                              "does not point at an https://dataexplorer.azure.com/ URL (href="
                              "%r) - build it with tools/kusto_link.py so the query opens safely in ADX"
                              % ((a.get("href", "") or "")[:80]))

    # 11e) CMH-KQL-08: every KQL code block must be RUNNABLE - framed in a figure.cmh-kql that carries
    #      a "Run in Azure Data Explorer" link (governed by 11d) - UNLESS it is EXPLICITLY marked
    #      data-cmh-kql-no-cluster (there is genuinely no cluster to run it on). A bare
    #      <pre><code class="language-kusto"> that is neither framed nor marked is a hard error, so a
    #      missing cluster is a conscious choice, not an accidental omission. Prefer providing a
    #      cluster (build the figure with tools/kusto/kql_highlight.py); reserve the marker for the
    #      rare clusterless snippet (tools/kusto/kql_highlight.py --code-only stamps it).
    # Mask <script>/<style> bodies and HTML comments (blanking to spaces preserves offsets) so a
    # `<pre>` or `language-kusto` mentioned in CSS/JS or a comment cannot start a spurious match that
    # swallows a real KQL block.
    _blank = lambda m: " " * len(m.group(0))
    masked = _HTML_COMMENT_RE.sub(_blank, _SCRIPT_STYLE_RE.sub(_blank, html))
    kql_figure_spans = [(fm.start(), fm.end()) for fm in
                        re.finditer(r"<figure\b([^>]*)>.*?</figure>", masked, re.IGNORECASE | re.DOTALL)
                        if _attrs_have_class(fm.group(1), "cmh-kql")]
    for pm in _PRE_TAG_RE.finditer(masked):
        if not re.search(r'<code\b[^>]*\bclass\s*=\s*["\'][^"\']*\blanguage-(?:kusto|kql)\b',
                         pm.group(2), re.IGNORECASE):
            continue
        if any(start <= pm.start() < end for start, end in kql_figure_spans):
            continue  # inside a figure.cmh-kql - the run-link rule (11d) governs this block
        if re.search(r"\bdata-cmh-kql-no-cluster\b", pm.group(1), re.IGNORECASE):
            continue  # explicitly marked highlight-only (no known cluster)
        errors.append('a KQL code block (<pre><code class="language-kusto">) is not runnable: wrap it '
                      'in a figure.cmh-kql with a "Run in Azure Data Explorer" link (build it with '
                      'tools/kusto/kql_highlight.py <cluster> <database> <title>), or - only if there '
                      'is genuinely no cluster to run it on - mark the <pre> data-cmh-kql-no-cluster '
                      '(tools/kusto/kql_highlight.py --code-only stamps that marker)')
    return errors, warnings


def _check_self_contained(html, parser, nonportable):
    errors, warnings = [], []
    # 11e) Self-contained guarantee: the finished document must not pull resources over the
    #      network (the core promise is a single self-contained file). <a href> links
    #      are navigation, not resource loads, so they are exempt; Chart.js from a CDN
    #      is a documented opt-in in portable mode (its SRI/version are checked in
    #      check_charts); mermaid CDN imports are handled by check_mermaid_renders.
    #      Offline mode is stricter: no network-loading resource is allowed.
    def _is_network(v):
        return bool(re.match(r"(?:https?:)?//", v or "", re.I))
    descriptor = _layer_descriptor_data(parser) or {}
    offline_mode = (not nonportable and descriptor.get("mode") == "offline")
    def _network_values(value, srcset=False):
        if srcset:
            return [part.strip().split()[0] for part in (value or "").split(",") if part.strip()]
        return [value or ""]
    def _network_error(tag, attr, val):
        label = "<%s %s=\"%s\">" % (tag, attr, val[:80])
        if offline_mode:
            if tag == "script" and CHARTJS_SRC_RE.search(val):
                return "offline mode: %s loads Chart.js over the network - inline it or export offline after rendering" % label
            return "offline mode: %s loads over the network - inline or remove it" % label
        return None
    def _check_network_attr(tag, attrs, attr, srcset=False):
        if tag == "link" and attr == "href" and not _link_loads(attrs):
            return
        val = attrs.get(attr, "")
        if not val:
            return
        for item in _network_values(val, srcset=srcset):
            if not _is_network(item):
                continue
            e = _network_error(tag, attr, item)
            if e:
                errors.append(e)
                continue
            if tag == "script" and CHARTJS_SRC_RE.search(item):
                continue
            if tag == "link":
                warnings.append('<link %s="%s"> loads over the network and breaks the self-contained '
                                "guarantee - inline or remove it" % (attr, item[:80]))
            else:
                errors.append('<%s %s="%s"> loads over the network and breaks the self-contained guarantee - '
                              "inline or remove it" % (tag, attr, item[:80]))
    for img in _find_tag_attrs(html, "img"):
        src = img.get("src", "")
        if src and not src.startswith("data:"):
            if _is_network(src):
                e = _network_error("img", "src", src)
                if e:
                    errors.append(e)
                else:
                    errors.append('<img src="%s"> loads over the network - inline it with '
                                  "tools/inline_images.py (external images break self-contained use and portability)"
                                  % src[:80])
            elif not re.match(r"[a-z][a-z0-9+.\-]*:", src, re.I):
                warnings.append('<img src="%s"> is a local path - run tools/inline_images.py to embed '
                                "it as a data: URI so the image travels with the file" % src[:80])
        _check_network_attr("img", img, "srcset", srcset=True)
    for tag, attr in (("link", "href"), ("script", "src"), ("iframe", "src")):
        for el in _find_tag_attrs(html, tag):
            _check_network_attr(tag, el, attr)
    if offline_mode:
        errors.extend(_offline_csp_errors(html))
        media_attrs = (
            ("video", "src", False), ("video", "poster", False),
            ("audio", "src", False), ("source", "src", False), ("source", "srcset", True),
            ("object", "data", False), ("embed", "src", False), ("track", "src", False),
            ("image", "href", False), ("image", "xlink:href", False),
            ("use", "href", False), ("use", "xlink:href", False),
        )
        for tag, attr, is_srcset in media_attrs:
            for el in _find_tag_attrs(html, tag):
                _check_network_attr(tag, el, attr, srcset=is_srcset)
        for el in _find_tag_attrs(html, "input"):
            if (el.get("type") or "").lower() == "image":
                _check_network_attr("input", el, "src")
        for el in _find_tag_attrs(html, "form"):
            _check_network_attr("form", el, "action")
        for tag in ("button", "input"):
            for el in _find_tag_attrs(html, tag):
                _check_network_attr(tag, el, "formaction")
        for el in _find_tag_attrs(html, "meta"):
            if (el.get("http-equiv") or "").lower() == "refresh" and META_REFRESH_NETWORK_RE.search(el.get("content", "")):
                errors.append("offline mode: meta refresh points at a network URL - remove it")
        for tag in ("body", "table", "td", "th", "div"):
            for el in _find_tag_attrs(html, tag):
                _check_network_attr(tag, el, "background")
        for style in parser.styles:
            for m in re.finditer(r"@import\s+(?:url\()?['\"]?((?:https?:)?//[^;'\"\)]+)", style.get("body", ""), re.I):
                errors.append('offline mode: @import "%s" loads over the network - inline or remove it' % m.group(1)[:80])
            if CSS_NETWORK_URL_RE.search(style.get("body", "")):
                errors.append("offline mode: style block contains a network url(...) - inline or remove it")
        for style in parser.inline_styles:
            if CSS_NETWORK_URL_RE.search(style.get("value", "")):
                errors.append("offline mode: inline style on <%s> contains a network url(...) - inline or remove it"
                              % style.get("tag", "element"))
        for script in parser.scripts:
            if not _is_executable_js(script["attrs"]):
                continue
            body = script.get("body", "")
            if re.search(r"\bimport\s*\(\s*['\"](?:https?:)?//", body, re.I) or \
                    (re.search(r"\bimport\s*\(", body) and re.search(r"['\"](?:https?:)?//[^'\"]*['\"]", body, re.I)) or \
                    re.search(r"\b(?:import|from)\s+['\"](?:https?:)?//", body, re.I):
                errors.append("offline mode: inline script imports a network module - inline or remove it")
    return errors, warnings


def _check_heading_ids(parser):
    errors, warnings = [], []
    # 11f) Duplicate heading ids collide in-page anchors: the TOC and prose links bind
    #      to the first occurrence, so later sections become unreachable.
    _hids = [h.get("id") for h in parser.headings if h.get("id")]
    _dup_hids = sorted(hid for hid, cnt in Counter(_hids).items() if cnt > 1)
    if _dup_hids:
        warnings.append("duplicate heading id(s) detected: %s - in-page anchors and the generated TOC "
                        "bind to the first occurrence; give each heading a unique id"
                        % ", ".join(_dup_hids[:5]))
    return errors, warnings


def _check_transient_body_classes(parser):
    errors, warnings = [], []
    # 11g) Transient runtime UI-state classes must never be baked into the shipped <body> open
    #      tag. A persisted "sidebar-open" makes the document render full width with an empty
    #      sidebar gutter (the body.sidebar-open .app layout rule) for a sidebar that is not
    #      shown; the runtime re-derives the sidebar state on load, so the class is redundant.
    #      Inspect the REAL parsed <body> element (not the first raw "<body ...>" token) so a
    #      decoy "<body ...>" literal inside a head <script>/comment cannot hide a dirty real
    #      body or false-flag a benign mention.
    if parser.body_attrs is not None:
        _body_classes = set((parser.body_attrs.get("class") or "").split())
        for _cls in _TRANSIENT_BODY_CLASSES:
            if _cls in _body_classes:
                errors.append('<body> carries the transient runtime UI-state class "%s" - it must '
                              "never be baked into a shipped document (the layer re-derives it on "
                              "load); remove it from the <body> open tag" % _cls)
    return errors, warnings


def _region_bounds(begin_idx, end_idx, name):
    """Byte range [lo, hi) of a region's content, or (None, None) when its
    markers are missing or out of order, so a state JSON block is read from inside
    its own region and a decoy <script> with the same id elsewhere is ignored."""
    if name in begin_idx and name in end_idx and begin_idx[name] < end_idx[name]:
        return begin_idx[name], end_idx[name]
    return None, None


def _check_state_json_blocks(html, parser, begin_idx, end_idx, nonportable):
    errors, warnings = [], []
    # 4) handledCommentIds is a JSON array of safe ids.
    hlo, hhi = _region_bounds(begin_idx, end_idx, "HANDLED IDS")
    handled_script = _parser_script(parser, "handledCommentIds", hlo, hhi)
    handled = handled_script["body"] if handled_script is not None else None
    if handled is None:
        errors.append('missing <script id="handledCommentIds"> block')
    else:
        if not _is_json_attrs(handled_script["attrs"]):
            errors.append('the <script id="handledCommentIds"> block must be type="application/json" '
                          "(without it the browser executes the JSON as JavaScript)")
        try:
            arr = json.loads(handled.strip() or "[]")
            if not isinstance(arr, list):
                errors.append("handledCommentIds is not a JSON array")
            else:
                bad = [x for x in arr if not (isinstance(x, str) and SAFE_ID_RE.match(x))]
                if bad:
                    errors.append(f"handledCommentIds has {len(bad)} id(s) not matching the safe pattern "
                                  f"{SAFE_ID_RE.pattern}: {bad[:3]} - mark_handled.py will refuse to edit "
                                  "this file until they are corrected")
        except json.JSONDecodeError as exc:
            errors.append(f"handledCommentIds is not valid JSON: {exc}")

    # 5) embeddedComments is a JSON array.
    elo, ehi = _region_bounds(begin_idx, end_idx, "EMBEDDED COMMENTS")
    embedded_script = _parser_script(parser, "embeddedComments", elo, ehi)
    embedded = embedded_script["body"] if embedded_script is not None else None
    if embedded is None:
        errors.append('missing <script id="embeddedComments"> block')
    else:
        if not _is_json_attrs(embedded_script["attrs"]):
            errors.append('the <script id="embeddedComments"> block must be type="application/json" '
                          "(without it the browser executes the JSON as JavaScript)")
        try:
            arr = json.loads(embedded.strip() or "[]")
            if not isinstance(arr, list):
                errors.append("embeddedComments is not a JSON array")
            else:
                # Each embedded comment must have a safe string id (the runtime keys
                # merge/dedupe on it and getElementById-style lookups assume it is safe);
                # a null/non-string/unsafe id silently drops or breaks the comment at load.
                bad = [i for i, item in enumerate(arr)
                       if not (isinstance(item, dict) and isinstance(item.get("id"), str)
                               and SAFE_ID_RE.match(item["id"]))]
                if bad:
                    errors.append("embeddedComments: %d item(s) have a missing or unsafe id "
                                  "(indices %s) - each item must be an object whose id matches %s"
                                  % (len(bad), bad[:5], SAFE_ID_RE.pattern))
        except json.JSONDecodeError as exc:
            errors.append(f"embeddedComments is not valid JSON: {exc}")

    # 6) The JS region must contain exactly one real </script>.
    if not nonportable and "JS" in begin_idx and "JS" in end_idx:
        lo, hi = sorted((begin_idx["JS"], end_idx["JS"]))
        js_slice = html[lo:hi]
        n_close = len(re.findall(r"</script\s*>", js_slice, re.IGNORECASE))
        if n_close == 0:
            errors.append("JS region has no closing </script> before its END marker (malformed)")
        elif n_close > 1:
            errors.append(f"JS region contains {n_close} </script> tags - a literal </script> in the script body must be escaped as <\\/script>")
    return errors, warnings


def _check_offset_within(html, begin_idx, end_idx):
    errors, warnings = [], []
    # 3c) Text-anchoring robustness. The layer's offsetWithin() must normalize a range
    #     boundary that lands on an element node (element, childIndex) to a text node,
    #     or a selection starting/ending at a block edge (e.g. a heading selected from
    #     its start yields a (h3, 0) boundary) returns -1 and the composer aborts with
    #     "Could not anchor that selection". Require a real normalizeBoundary() function
    #     AND a call to it from within offsetWithin()'s body (brace-matched on the
    #     string/comment-blanked source via _js_scan, so a normalizeBoundary token that
    #     lives only in a comment or a string literal cannot satisfy the check and a `}`
    #     inside a string cannot prematurely close the body). Gate on offsetWithin so the
    #     stub JS used by the test fixtures (which has neither symbol) stays exempt.
    _jlo, _jhi = _region_bounds(begin_idx, end_idx, "JS")
    if _jlo is not None:
        _scan = _js_scan(html[_jlo:_jhi])[1]  # init view: comments AND strings blanked
        _decl = re.search(r"function\s+offsetWithin\s*\([^)]*\)\s*\{", _scan)
        if _decl is not None:
            _has_decl = re.search(r"function\s+normalizeBoundary\s*\(", _scan) is not None
            _calls = False
            _m = _decl
            if _m:
                _depth, _body_start = 0, _m.end()
                for _j in range(_m.end() - 1, len(_scan)):
                    if _scan[_j] == "{":
                        _depth += 1
                    elif _scan[_j] == "}":
                        _depth -= 1
                        if _depth == 0:
                            _calls = re.search(r"\bnormalizeBoundary\s*\(", _scan[_body_start:_j]) is not None
                            break
            if not (_has_decl and _calls):
                errors.append(
                    "the JS region defines offsetWithin() but does not both declare a "
                    "normalizeBoundary() function and call it from within offsetWithin(); a "
                    'selection whose start or end lands on an element boundary will fail to '
                    'anchor ("Could not anchor that selection")')
    return errors, warnings


def check_layer(html, parser, base_dir=None):
    errors, warnings = [], []
    nonportable = _is_nonportable(html)
    active_regions = NONPORTABLE_REGIONS if nonportable else REGIONS

    # 1) Exactly one BEGIN and one END marker per (active) region, BEGIN before END.
    begin_idx, end_idx = {}, {}
    for region in active_regions:
        begins = _region_marker_matches(html, "BEGIN", region)
        ends = _region_marker_matches(html, "END", region)
        if len(begins) != 1:
            errors.append(f"region '{region}': expected 1 BEGIN marker, found {len(begins)}")
        else:
            begin_idx[region] = begins[0].start()
        if len(ends) != 1:
            errors.append(f"region '{region}': expected 1 END marker, found {len(ends)}")
        else:
            end_idx[region] = ends[0].start()
    for region in active_regions:
        if region in begin_idx and region in end_idx and begin_idx[region] >= end_idx[region]:
            errors.append(f"region '{region}': END marker appears before its BEGIN marker")

    # 2) Region ordering.
    order = [r for r in active_regions if r in begin_idx]
    positions = [begin_idx[r] for r in order]
    if len(positions) >= 2 and positions != sorted(positions):
        errors.append("regions are out of order (expected order: %s)" % ", ".join(active_regions))

    errors.extend(_check_layer_descriptor(parser, nonportable, active_regions))

    e, w = _check_content_markers(html)
    errors += e
    warnings += w

    e, w = _check_comment_root(parser, html)
    errors += e
    warnings += w
    e, w = _check_offset_within(html, begin_idx, end_idx)
    errors += e
    warnings += w

    e, w = _check_state_json_blocks(html, parser, begin_idx, end_idx, nonportable)
    errors += e
    warnings += w

    e, w = _check_element_ids(parser, html)
    errors += e
    warnings += w

    e, w = _check_theme_and_skip(html, parser, nonportable)
    errors += e
    warnings += w

    # 11a) Section cross-references in prose should be in-page anchor links (deterministic
    #      detection; only UNLINKED references reach commentroot_prose).
    warnings.extend(check_section_reference_links(parser))
    warnings.extend(check_section_wrapping(parser))

    # 11a1) Document kind: the doc must declare a known kind, and title-bearing kinds
    #       (report/plan) must carry a top-level <h1> in #commentRoot.
    errors.extend(check_document_kind(parser))

    # 11a2) Mermaid diagrams must actually render on open (loader present, triggers a
    #       render, and is not hidden behind a query-param gate).
    warnings.extend(check_mermaid_renders(parser))

    e, w = _check_diff_blocks(html)
    errors += e
    warnings += w

    e, w = _check_kql_blocks(html)
    errors += e
    warnings += w

    e, w = _check_self_contained(html, parser, nonportable)
    errors += e
    warnings += w

    e, w = _check_heading_ids(parser)
    errors += e
    warnings += w

    e, w = _check_transient_body_classes(parser)
    errors += e
    warnings += w

    # 12) NonPortable-mode-only invariants (companion refs, version handshake, banner,
    #     referenced files exist).
    if nonportable:
        id_counts = Counter(parser.all_ids)
        e, w = _check_nonportable(html, base_dir, id_counts)
        errors += e
        warnings += w

    return errors, warnings
