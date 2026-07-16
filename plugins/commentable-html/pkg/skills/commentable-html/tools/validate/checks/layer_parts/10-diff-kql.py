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
