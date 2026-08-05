def _check_marker_parse_agreement(html, parser, active_regions, counted):
    """Every marker the region COUNT accepts must be one a browser really parses as a comment,
    and the JS END boundary the chart guard reads must be the SAME marker.

    The count view is TEXT. It counts a marker written where a browser builds no comment node at
    all - inside an inert `<template>`, inside a CDATA section in foreign content, inside a
    raw-text body such as `<script>`/`<textarea>`/`<title>`/`<noscript>` - so a document could
    satisfy this region check with a marker that silently disables a parse-driven check. The
    chart-init guard is where that bit end to end: `check_charts` SKIPS E5 when the parse found no
    `END: commentable-html - JS` comment - deliberately, so a plain chart page that is not a
    commentable-html document is never flagged (CMH-CHART-02) - so a `new Chart(` before such a
    marker went unreported and the whole document validated with zero errors and zero warnings.

    The test is "is there a real comment here", not "is the comment source byte-canonical",
    because the shipped documents write their BEGIN markers inside a decorated comment (a rule of
    `=` lines plus prose) that the count view reads a marker line out of. The one sanctioned
    non-comment marker is the Shareable CSS region's, a `/* ... */` comment inside `<style>` that
    a browser never turns into a comment NODE, so it is matched against that `<style>` body.

    The JS END marker gets one extra rule, because it is the only counted marker a check reads a
    POSITION from: `js_end_marker_pos` accepts a narrower comment source than the count view does,
    so a decorated or `--!>`-closed comment satisfied the count while leaving the guard's boundary
    unset. The two must name the same comment or the document is refused.
    """
    errors = []
    spans = raw_text_spans(html)
    if spans is None:
        # The raw-text pass blew up while the document parser did not, so the two views cannot be
        # reconciled. Refuse rather than accept every counted marker unchecked: this guard exists
        # precisely so a marker the parse cannot see is never blessed.
        return ["the region markers could not be cross-checked against the document's raw-text "
                "boundaries (the raw-text pass failed on markup the document parser accepted) - "
                "fix the markup so both agree"]
    # A `<style>` parked inside an inert `<template>` is not a live stylesheet, so it may not host
    # the CSS region's `/* */` markers either: that let a whole dead CSS region validate clean.
    style_spans = [(s, e) for s, e, tag, in_tpl in spans if tag == "style" and not in_tpl]
    raw_spans = [(s, e) for s, e, _tag, _in_tpl in spans]
    scan = content_marker_scan(html)
    live = parser.marker_comment_spans
    for region in active_regions:
        for kind in MARKER_KINDS:
            matches = counted.get((region, kind), ())
            # Blanking a raw-text body deletes whatever closed an open comment state in the RAW
            # view, so the scan can count a bare marker line the raw view rejects - a marker the
            # loop below structurally cannot see, and one that silently empties the layer-region
            # ALLOW-list (`layer_regions_text`, which counts in the scan). The scan may count
            # FEWER (that is the CSS region, whose markers it blanks); more is a divergence.
            if len(_region_marker_matches(scan, kind, region)) > len(matches):
                errors.append(
                    "region '%s': the %s marker count disagrees between the raw document and the "
                    "view that blanks raw-text bodies, so a marker only one view sees would "
                    "silently move the region boundary; remove the stray comment delimiter that "
                    "a <script>/<style>/<textarea> body closes" % (region, kind))
            for m in matches:
                pos = m.start()
                covering = next((sp for sp in live if sp[0] <= pos < sp[1]), None)
                if covering is not None:
                    if region == "JS" and kind == "END":
                        errors.extend(_check_js_end_boundary(parser, covering))
                    continue
                if region == "CSS" and any(s <= pos < e for s, e in style_spans):
                    continue
                if any(s <= pos < e for s, e in parser.template_comment_spans):
                    where = "an inert <template>, whose content a browser never parses as part of the document"
                elif any(s <= pos < e for s, e in parser.shadow_comment_spans):
                    where = "a declarative shadow tree, which is outside the document's layer regions"
                elif any(s <= pos < e for s, e in raw_spans):
                    where = ("a raw-text body (<script>, <style>, <textarea>, <title>, <noscript>, ...), "
                             "which holds TEXT a reader sees rather than markup")
                else:
                    where = ("content the document does not parse as a comment at all (a CDATA section "
                             "in <svg>/<math>, for example)")
                errors.append(
                    "region '%s': the %s marker is inside %s - it is still COUNTED as text, so checks "
                    "keyed on this region would silently pass while a browser reads no boundary there; "
                    "write the marker as its own `<!-- %s: commentable-html - %s -->` comment in the "
                    "document proper" % (region, kind, where, kind, region))
    return errors


def _check_js_end_boundary(parser, span):
    pos = parser.js_end_marker_pos
    if pos is not None and span[0] <= pos < span[1]:
        return []
    return ["region 'JS': the END marker is counted, but the chart-init guard's boundary reader "
            "does not accept the comment carrying it (it takes only the marker itself, optionally "
            "on its own line and `=`-decorated, closed with `-->`) - so `new Chart(` calls before "
            "the region end would go unreported; write it as its own "
            "`<!-- END: commentable-html - JS -->` comment"]


def check_layer(html, parser, base_dir=None):
    errors, warnings = [], []
    nonshareable = _is_nonshareable(parser)
    active_regions = NONSHAREABLE_REGIONS if nonshareable else REGIONS

    # 1) Exactly one BEGIN and one END marker per (active) region, BEGIN before END.
    begin_idx, end_idx = {}, {}
    counted = {}
    for region in active_regions:
        begins = _region_marker_matches(html, "BEGIN", region)
        ends = _region_marker_matches(html, "END", region)
        counted[(region, "BEGIN")] = begins
        counted[(region, "END")] = ends
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

    errors.extend(_check_marker_parse_agreement(html, parser, active_regions, counted))

    # 2) Region ordering.
    order = [r for r in active_regions if r in begin_idx]
    positions = [begin_idx[r] for r in order]
    if len(positions) >= 2 and positions != sorted(positions):
        errors.append("regions are out of order (expected order: %s)" % ", ".join(active_regions))

    errors.extend(_check_layer_descriptor(parser, nonshareable, active_regions))

    e, w = _check_content_markers(html, parser)
    errors += e
    warnings += w

    e, w = _check_comment_root(parser, html)
    errors += e
    warnings += w
    e, w = _check_offset_within(html, begin_idx, end_idx)
    errors += e
    warnings += w

    e, w = _check_state_json_blocks(html, parser, begin_idx, end_idx, nonshareable)
    errors += e
    warnings += w

    e, w = _check_element_ids(parser, html)
    errors += e
    warnings += w

    e, w = _check_theme_and_skip(html, parser, nonshareable)
    errors += e
    warnings += w

    # 11a) Section cross-references in prose should be in-page anchor links (deterministic
    #      detection; only UNLINKED references reach commentroot_prose).
    warnings.extend(check_section_reference_links(parser))
    warnings.extend(check_section_wrapping(parser))

    # 11a0) Author links must open in a new tab: warn on a document reference in #commentRoot
    #       that sets an explicit target other than _blank (it would open in the same tab).
    warnings.extend(check_links(parser))

    # 11a1) Document kind: the doc must declare a known kind, and title-bearing kinds
    #       (report/plan) must carry a top-level <h1> in #commentRoot.
    errors.extend(check_document_kind(parser))
    errors.extend(check_shadow_root_exports(parser))

    # 11a2) Mermaid diagrams must actually render on open (loader present, triggers a
    #       render, and is not hidden behind a query-param gate).
    warnings.extend(check_mermaid_renders(parser))

    # 11a3) Favicon: every document should declare the CMH favicon so a browser tab shows
    #       the CMH mark rather than the generic globe (advisory; enforced under --strict).
    warnings.extend(check_favicon(parser))

    e, w = _check_diff_blocks(html)
    errors += e
    warnings += w

    e, w = _check_kql_blocks(html)
    errors += e
    warnings += w

    # No `nonshareable` argument: the offline gates key off the DECLARED descriptor mode, so this
    # check must not be able to consult the lineage at all (see 20-resources.py).
    e, w = _check_self_contained(html, parser)
    errors += e
    warnings += w

    e, w = _check_heading_ids(parser)
    errors += e
    warnings += w

    e, w = _check_transient_body_classes(parser)
    errors += e
    warnings += w

    # 12) NonShareable-mode-only invariants (companion refs, version handshake, banner,
    #     referenced files exist).
    if nonshareable:
        id_counts = Counter(parser.layer_ids)
        e, w = _check_nonshareable(parser, base_dir, id_counts)
        errors += e
        warnings += w

    return errors, warnings
