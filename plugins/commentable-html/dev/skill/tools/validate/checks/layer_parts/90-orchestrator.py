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

    # 11a3) Favicon: every document should declare the CMH favicon so a browser tab shows
    #       the CMH mark rather than the generic globe (advisory; enforced under --strict).
    warnings.extend(check_favicon(parser))

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
