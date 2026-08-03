def _check_self_contained(html, parser, nonshareable):
    errors, warnings = [], []
    # The whole guarantee is read off the shared tag index, so a parse that could not be built
    # must be REPORTED rather than read as "this document loads nothing" (a partial index would
    # hide every resource after the failure point).
    if _tag_attrs_failed(html):
        errors.append("could not parse the document for the self-contained resource checks - "
                      "fix the markup and re-run")
    # 11e) Self-contained guarantee: the finished document must not pull resources over the
    #      network (the core promise is a single self-contained file). <a href> links
    #      are navigation, not resource loads, so they are exempt; Chart.js from a CDN
    #      is a documented opt-in in shareable mode (its SRI/version are checked in
    #      check_charts); mermaid CDN imports are handled by check_mermaid_renders.
    #      Offline mode is stricter: no network-loading resource is allowed.
    #      Every ELEMENT lookup below asks the EGRESS question, so each reads the `<noscript>`
    #      fallback markup a scripting-disabled browser parses and really does load. (The CSS
    #      egress scans further down read `_DocParser`'s styles, which do not see inside a
    #      `<noscript>` - tracked separately.)
    def _is_network(v):
        return bool(NETWORK_URL_RE.match(v or ""))
    descriptor = _layer_descriptor_data(parser) or {}
    offline_mode = (not nonshareable and descriptor.get("mode") == "offline")
    def _network_values(value, srcset=False):
        if srcset:
            return [part.strip().split()[0] for part in (value or "").split(",") if part.strip()]
        return [value or ""]
    def _network_error(tag, attr, val):
        label = "<%s %s=\"%s\">" % (tag, attr, val[:80])
        if offline_mode:
            if tag == "script" and attr == "src" and CHARTJS_SRC_RE.search(val):
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
            if tag == "script" and attr == "src" and CHARTJS_SRC_RE.search(item):
                continue
            if tag == "link":
                warnings.append('<link %s="%s"> loads over the network and breaks the self-contained '
                                "guarantee - inline or remove it" % (attr, item[:80]))
            else:
                errors.append('<%s %s="%s"> loads over the network and breaks the self-contained guarantee - '
                              "inline or remove it" % (tag, attr, item[:80]))
    for img in _find_tag_attrs_egress(html, "img"):
        src = img.get("src", "")
        if src and not src.startswith("data:"):
            if _is_network(src):
                e = _network_error("img", "src", src)
                if e:
                    errors.append(e)
                else:
                    errors.append('<img src="%s"> loads over the network - inline it with '
                                  "tools/inline_images.py (external images break self-contained use and shareability)"
                                  % src[:80])
            elif not re.match(r"[a-z][a-z0-9+.\-]*:", src, re.I):
                warnings.append('<img src="%s"> is a local path - run tools/inline_images.py to embed '
                                "it as a data: URI so the image travels with the file" % src[:80])
        _check_network_attr("img", img, "srcset", srcset=True)
    # An SVG <script> never uses `src`: it loads through `href` (SVG2) or the legacy `xlink:href`,
    # and its body is empty, so neither this loader check nor the inline egress scan below saw it
    # and `--strict` certified such a file as offline-clean. The offline export strips the same
    # attribute set (`SCRIPT_LOAD_ATTRS`), so the gate and the exporter agree by construction.
    # Deliberately NOT scoped to the SVG namespace: `HTMLParser` has none to consult, so a
    # namespace test here could only approximate the one the runtime can make exactly, and an
    # approximation is the drift this row exists to prevent. The cost is that an inert `href` on an
    # HTML <script> is reported too - a shape no real document uses, and one that becomes a live
    # loader the moment the same bytes are parsed as XHTML. The Chart.js CDN exemption stays bound
    # to `src`, since `check_charts` only validates a `src` loader's version and SRI: exempting an
    # `href` would wave through a remote script nothing else checks.
    # Parsed once per TAG (not once per tag/attribute pair): `_find_tag_attrs_egress` runs a full
    # pure-Python tokenizer pass over the whole document, and the widened script set would
    # otherwise triple that cost for scripts alone.
    for tag, attrs in (("link", ("href",)), ("script", SCRIPT_LOAD_ATTRS), ("iframe", ("src",))):
        for el in _find_tag_attrs_egress(html, tag):
            for attr in attrs:
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
            for el in _find_tag_attrs_egress(html, tag):
                _check_network_attr(tag, el, attr, srcset=is_srcset)
        for el in _find_tag_attrs_egress(html, "input"):
            if (el.get("type") or "").lower() == "image":
                _check_network_attr("input", el, "src")
        for el in _find_tag_attrs_egress(html, "form"):
            _check_network_attr("form", el, "action")
        for tag in ("button", "input"):
            for el in _find_tag_attrs_egress(html, tag):
                _check_network_attr(tag, el, "formaction")
        for el in _find_tag_attrs_egress(html, "meta"):
            if (el.get("http-equiv") or "").lower() == "refresh" and META_REFRESH_NETWORK_RE.search(el.get("content", "")):
                errors.append("offline mode: meta refresh points at a network URL - remove it")
        for tag in ("body", "table", "td", "th", "div"):
            for el in _find_tag_attrs_egress(html, tag):
                _check_network_attr(tag, el, "background")
        # The exporter removes EVERY `on*` attribute, template content included, so a gate that did
        # not look would certify a hand-authored offline file the export would have changed - and an
        # inline handler is exactly the channel the CSP cannot close, since `script-src
        # 'unsafe-inline'` allows it and no meta-delivered policy restricts top-level navigation.
        for handler in parser.event_handler_attrs:
            errors.append('offline mode: <%s %s="..."> carries an inline event handler - it runs '
                          "with the document's own privileges (the offline CSP allows inline script "
                          "and cannot stop a navigation), so the export removes it; remove it here too"
                          % (handler.get("tag", "element"), handler.get("attr", "on...")))
        for style in parser.styles + parser.template_styles:
            for m in re.finditer(r"@import\s+(?:url\()?['\"]?((?:https?:)?//[^;'\"\)]+)", style.get("body", ""), re.I):
                errors.append('offline mode: @import "%s" loads over the network - inline or remove it' % m.group(1)[:80])
            if CSS_NETWORK_URL_RE.search(style.get("body", "")):
                errors.append("offline mode: style block contains a network url(...) - inline or remove it")
        for style in parser.inline_styles + parser.template_inline_styles:
            if CSS_NETWORK_URL_RE.search(style.get("value", "")):
                errors.append("offline mode: inline style on <%s> contains a network url(...) - inline or remove it"
                              % style.get("tag", "element"))
        # Template-parked content is inert until a script adopts the fragment and inserts it, at
        # which point a parked script runs and a parked reference loads - so the offline strips walk
        # into templates and this gate reads what they read. Every other check keeps ignoring
        # template content, which is why these are separate views rather than a widened `scripts`.
        for script in parser.scripts + parser.template_scripts:
            active = offline_active_data_script_type(script["attrs"])
            if active:
                if offline_active_data_block_is_removable(active, script["attrs"], script.get("body", "")):
                    errors.append("offline mode: a <script type=\"%s\"> block is active without being "
                                  "JavaScript - a speculation ruleset makes the browser fetch on its "
                                  "own (it needs no URL literal, so it cannot be made offline-safe) "
                                  "and an import map re-points where a bare module specifier "
                                  "resolves; remove the ruleset, and give the import map a valid "
                                  "body whose every reference, key and value, is relative" % active)
                continue
            if not _is_executable_js(script["attrs"]):
                continue
            body = script.get("body", "")
            if re.search(r"\bimport\s*\(\s*['\"](?:https?:)?//", body, re.I) or \
                    (re.search(r"\bimport\s*\(", body) and re.search(r"['\"](?:https?:)?//[^'\"]*['\"]", body, re.I)) or \
                    re.search(r"\b(?:import|from)\s+['\"](?:https?:)?//", body, re.I):
                errors.append("offline mode: inline script imports a network module - inline or remove it")
            if offline_script_navigates_to_network(body):
                errors.append("offline mode: inline script source matches a direct top-level "
                              "navigation to a network URL - such a navigation beacons the whole "
                              "document (reviewer comments included) and no CSP directive in a "
                              "<meta> can stop it; remove the navigation, or reword the comment or "
                              "string literal that matches it")
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
