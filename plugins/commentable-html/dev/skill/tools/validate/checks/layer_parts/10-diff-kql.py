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


def _is_kql_code(code):
    """True when a parsed <code> element carries a language-kusto / language-kql class token."""
    return (parsed_attrs_have_class(code["attrs"], "language-kusto")
            or parsed_attrs_have_class(code["attrs"], "language-kql"))


# The `target` keywords that do NOT open an auxiliary browsing context, so no `window.opener` is
# handed to the opened page: the absent/empty value and the three keywords that navigate a context
# that already exists. Matched ASCII case-insensitively, the way HTML matches the keywords, and
# UNTRIMMED - a padded ` _blank` is not the keyword at all, it is a NAME.
_SAME_CONTEXT_TARGETS = frozenset(("", "_self", "_parent", "_top"))

# The elements that DECLARE a named browsing context inside this document. A `target` naming one of
# them navigates a context that already exists (an `<iframe name="win1">`), which gets no opener -
# so the gate below must not call that reverse-tabnabbing. Names are matched EXACTLY, as HTML
# matches a browsing-context name (only the four keywords are case-insensitive).
_NAMED_CONTEXT_TAGS = ("iframe", "frame", "object")


def _named_browsing_contexts(html):
    """The browsing-context names this document declares."""
    names = set()
    for tag in _NAMED_CONTEXT_TAGS:
        for el in _find_tag_attrs(html, tag):
            if el.get("name"):
                names.add(el["name"])
    return names


def _check_kql_blocks(html):
    errors, warnings = [], []
    named_contexts = _named_browsing_contexts(html)
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
        # The condition is the one a BROWSER actually applies: does this target CREATE an auxiliary
        # browsing context, whose `window.opener` points back at this document? HTML matches the
        # four keywords ASCII case-insensitively and does NOT trim the value, so `_BLANK` is the
        # keyword, a padded ` _blank` is a NAME, and a name that resolves to nothing in this
        # document creates a new auxiliary context just as `_blank` does. A Python `==` against the
        # literal `_blank` saw none of those, so a run link carrying no `rel` at all passed in
        # silence (#1120). A name that DOES resolve - an `<iframe name="win1">` written in the same
        # document - navigates a context that already exists and gets no opener, so it is exempt:
        # warning there would be a false positive, and taking the advice would CHANGE behavior
        # (`noopener` makes a named target stop reusing the frame and open a new tab instead).
        #
        # This gate is the ONLY reverse-tabnabbing control on a `cmh-kql-run` link: CMH-KQL-01 puts
        # the run link inside `figcaption.cm-skip`, and BOTH the render-time stamper
        # (`assets/js/31-links.js` returns early on `.cm-skip`) and `checks/links.py` (which skips a
        # skip-marked anchor) pass it by.
        raw_target = a.get("target") or ""
        target = _ascii_lower(raw_target)
        opens_auxiliary = (target not in _SAME_CONTEXT_TARGETS
                           and (target == "_blank" or raw_target not in named_contexts))
        if opens_auxiliary and "noopener" not in link_rel_tokens(a.get("rel")):
            # `%r` because the value is authored text: the covered spellings include control
            # characters (a tab, a newline, a vertical tab), and interpolating one raw would break
            # the diagnostic across lines or drive the reader's terminal.
            warnings.append('a "cmh-kql-run" link opens an auxiliary browsing context '
                            '(target=%r) without rel="noopener" (reverse-tabnabbing risk); '
                            'add rel="noopener noreferrer"' % raw_target[:40])

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
    # Blocks come from PARSED elements (checks/parsing.code_block_spans, shared with the
    # highlighting scan CMH-VAL-11), so a `<pre>` or `language-kusto` mentioned inside CSS, JS, a
    # comment, a raw-text element or a CDATA section is text and contributes nothing, the
    # figure.cmh-kql exemption comes from real ancestry, and the marker is read from the parsed
    # <pre> attributes so a `>` inside a quoted attribute value cannot hide it.
    spans = code_block_spans(html)
    if spans.failed:
        # The scan produced NO blocks, so "no unrunnable KQL found" would be a lie. This gate is
        # a hard error, so say so rather than let a document through on an empty result.
        errors.append("the document could not be parsed to locate its KQL code blocks, so the "
                      "runnable-KQL rule could not be applied - fix the markup rather than "
                      "trusting a clean result")
        return errors, warnings
    for pre in spans.pres:
        if not any(_is_kql_code(c) for c in pre["codes"]):
            continue
        if pre["in_kql_figure"]:
            continue  # inside a figure.cmh-kql - the run-link rule (11d) governs this block
        if "data-cmh-kql-no-cluster" in pre["attrs"]:
            continue  # explicitly marked highlight-only (no known cluster)
        errors.append('a KQL code block (<pre><code class="language-kusto">) is not runnable: wrap it '
                      'in a figure.cmh-kql with a "Run in Azure Data Explorer" link (build it with '
                      'tools/kusto/kql_highlight.py <cluster> <database> <title>), or - only if there '
                      'is genuinely no cluster to run it on - mark the <pre> data-cmh-kql-no-cluster '
                      '(tools/kusto/kql_highlight.py --code-only stamps that marker)')
    return errors, warnings
