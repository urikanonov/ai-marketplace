def _check_self_contained(html, parser):
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
    #      fallback markup a scripting-disabled browser parses and really does load. The CSS
    #      egress scans further down do the same, through `_find_noscript_styles()` /
    #      `_find_noscript_inline_styles()`, because a fallback stylesheet's `@import` and
    #      `url(...)` are live for exactly the reader who cannot run the layer.
    def _is_network(v):
        return is_network_url(v)
    descriptor = _layer_descriptor_data(parser) or {}
    # The offline rules follow the DECLARED mode, not the NonShareable lineage. The exporter runs
    # its offline strips on whatever it stamps `mode: offline`, and it reaches that stamp from the
    # NonShareable path too (`_buildStandaloneHtml` inlines the companions and drops the bootstrap
    # block first), so scoping this with `not nonshareable` keyed the GATE to a classification the
    # STRIPS never consult. A document stamped offline that still carried a companion reference -
    # a mangled or missing CSS/JS region marker leaves one behind, and a hand-authored file can
    # carry both - then switched OFF every offline-only rule below: the zero-network CSP
    # requirement, the media/form/background egress checks, the inline-script navigation and import
    # scans, the active-data rules, and the event-handler and meta-refresh gates. That never
    # certified the file - the descriptor rule rejects the NonShareable+offline pair on its own -
    # but it cost the REPORT (a live `on*` handler and a missing CSP were not named at all, and the
    # egress that was named carried the shareable wording) and it made this gate's SCOPE depend on
    # a different check being right. Reading the declared mode alone restores that layer and adds
    # no false rejection: the descriptor error and these errors are simply reported together, and a
    # document that declares `nonshareable` is untouched. A descriptor that is MISSING or malformed
    # still leaves these rules off and is left to the descriptor rule on purpose - defaulting those
    # to offline would only add wrong `offline mode:` errors to an ordinary shareable document
    # whose descriptor failed to parse, and none of them validates clean either way.
    offline_mode = (descriptor.get("mode") == "offline")
    def _network_values(value, srcset=False):
        if srcset:
            return srcset_candidate_urls(value)
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
    # A <base href> is not itself a load, which is why neither this gate nor the export strip used
    # to look at one - and both treat a RELATIVE reference as safe, which is the whole control case.
    # A base element REBASES every relative reference in the document onto the base it names, so the
    # very relative image or script reference both sides read as local fetches off-host while
    # passing every check above. That blast radius is why it is held to the stricter
    # `offline_is_non_local_ref` (any scheme, or an authority of two slashes/backslashes in either
    # order, after the URL parser's own input cleanup) rather than the `//`-requiring
    # `NETWORK_URL_RE` the per-resource checks use: a browser resolves a slash-less `https:host/`
    # and a backslash-authority `https:/\host/` to a remote host too, and for a base that would
    # defeat the check outright. The export strip clears exactly this set, so the two agree. Not
    # scoped to offline mode: the self-contained guarantee is not offline-only, and unlike offline a
    # shareable file has no zero-network CSP behind it. A relative base is left alone - it reaches
    # no network at all (the ordinary local-path rules already cover where it points).
    for el in _find_tag_attrs_egress(html, "base"):
        val = el.get("href", "")
        if val and offline_is_non_local_ref(val):
            label = '<base href="%s">' % val[:80]
            if offline_mode:
                errors.append("offline mode: %s rebases every relative reference in the document "
                              "onto a base the file cannot resolve on its own - remove it" % label)
            else:
                errors.append("%s rebases every relative reference in the document onto a base the "
                              "file cannot resolve on its own and breaks the self-contained "
                              "guarantee - make the base relative, or drop it and write the "
                              "affected href/src values out in full" % label)
    if offline_mode:
        # A parse that could not be built was already reported at the top of this function, so the
        # lookups below are best-effort on a PARTIAL index rather than gated on it - they can only
        # add to a report that already says the document could not be read.
        errors.extend(_offline_csp_errors(parser))
        media_attrs = (
            ("video", "src", False), ("video", "poster", False),
            ("audio", "src", False), ("source", "src", False), ("source", "srcset", True),
            ("object", "data", False), ("embed", "src", False), ("track", "src", False),
            ("image", "href", False), ("image", "xlink:href", False),
            ("use", "href", False), ("use", "xlink:href", False),
            # An SVG filter primitive fetches exactly like an `<image>` or a `<use>`, but was in
            # neither this list nor the export strip, so a document carrying one rode into a
            # zero-network export and `--strict` certified it clean (#992). `HTMLParser` lowercases
            # the tag, so the lookup key is `feimage` while the export selector spells it
            # `feImage`: CSS compares a type selector case-SENSITIVELY for an SVG-namespaced
            # element and case-INSENSITIVELY for an HTML one, so that one portable spelling reaches
            # both and the two sides stay namespace-blind together (a current Chromium is laxer
            # still and matches any casing, which is an implementation detail neither side relies
            # on).
            ("feimage", "href", False), ("feimage", "xlink:href", False),
        )
        for tag, attr, is_srcset in media_attrs:
            for el in _find_tag_attrs_egress(html, tag):
                _check_network_attr(tag, el, attr, srcset=is_srcset)
        for el in _find_tag_attrs_egress(html, "input"):
            if (el.get("type") or "").lower() == "image":
                _check_network_attr("input", el, "src")
        # An `<iframe srcdoc>` carries a WHOLE NESTED DOCUMENT as an attribute VALUE, which neither
        # side of the offline contract can see into: the export's strips walk ELEMENTS, so nothing
        # descends into the string, and this gate's tag index tokenizes the document, so that markup
        # is attribute text and never becomes tags. So an inline handler, a meta refresh, or a
        # network loader used to ride through an export AND past `--strict` - and the offline CSP
        # does not save it, because a `srcdoc` frame is content the policy is INHERITED into rather
        # than a fetch `frame-src 'none'` blocks, and the inherited policy still allows inline
        # script, which can navigate the top-level document. The direction taken (issue #996, the
        # way #926 settled the meta-refresh one) is that an offline document may not carry `srcdoc`
        # at all: the export clears the attribute unconditionally and this rejects any that remain,
        # so the two agree by construction. Parsing the nested document recursively on both sides is
        # the alternative, and keeping two independent parsers in step is exactly the drift these
        # rows exist to prevent. PRESENCE is the test, not a network-looking value: the export
        # clears an empty or inert one too, so anything narrower would bless a file the export
        # changes. Read off the shared EGRESS index, so a `<template>`-parked frame, a `<noscript>`
        # fallback, and a self-closed foreign element are all judged the same - and namespace-blind
        # like every other rule here, matching the exporter's own namespace-blind element walk.
        for el in _find_tag_attrs_egress(html, "iframe"):
            if "srcdoc" in el:
                errors.append('offline mode: <iframe srcdoc="%s"> carries a nested document that '
                              "neither the offline strips nor this gate can inspect, and the "
                              "offline CSP is inherited into it rather than blocking it - the "
                              "export clears the attribute, so remove it here too"
                              % ((el.get("srcdoc") or "")[:80]))
        for el in _find_tag_attrs_egress(html, "form"):
            _check_network_attr("form", el, "action")
        for tag in ("button", "input"):
            for el in _find_tag_attrs_egress(html, tag):
                _check_network_attr(tag, el, "formaction")
        # Hyperlink auditing: a click POSTs to every URL in `ping`, so the attribute is egress that
        # no resource check above looked at. CSP Level 3 folds auditing into `connect-src`, which
        # the offline policy does set to `'none'`, so a current browser most likely absorbs it -
        # but this gate and the export strip are the layer that is not supposed to DEPEND on the
        # CSP, and the directive's `ping-src` history makes that coverage version-dependent.
        # EVERY ping that names a URL is rejected, not only one naming a NETWORK URL, for the
        # reason the meta refresh above is: the exporter removes the attribute whatever it names (a
        # relative ping still POSTs, shows the reader nothing, and is meaningless in a single-file
        # export), so accepting a relative one would bless a file an export would change - and an
        # unconditional rule is one the two sides cannot drift apart on. The network wording is
        # kept for a value that does carry one, so the message still names the beacon.
        #
        # What "names a URL" means is read off HTML's own tokenization rather than off either
        # engine's whitespace class: the list is split on ASCII whitespace ONLY, written as literal
        # code points with `re.ASCII` for the same reason every other predicate here is. A
        # `str.strip()` would have drifted from the strip's `String.trim()` in both directions -
        # they disagree about NBSP, U+FEFF and U+001C-U+001F - and would have blessed an NBSP ping,
        # which a browser resolves as a relative target and POSTs to (`/%C2%A0`, measured in a real
        # Chromium). An empty or ASCII-whitespace-only value names nothing, so a browser sends
        # nothing, and BOTH sides leave those bytes exactly as the author wrote them.
        for tag in ("a", "area"):
            for el in _find_tag_attrs_egress(html, tag):
                targets = [t for t in re.split(r"[\t\n\f\r ]+", el.get("ping") or "", flags=re.ASCII) if t]
                if not targets:
                    continue
                beacon = next((u for u in targets if _is_network(u)), "")
                label = '<%s ping="%s">' % (tag, (el.get("ping") or "")[:80])
                if beacon:
                    errors.append("offline mode: %s POSTs to a network URL (%s) on every click - "
                                  "remove the attribute" % (label, beacon[:80]))
                else:
                    errors.append("offline mode: %s audits every click by POSTing to the URLs it "
                                  "names, which a single-file export can neither need nor show the "
                                  "reader, so the export removes it whatever it points at - remove "
                                  "the attribute here too" % label)
        for el in _find_tag_attrs_egress(html, "meta"):
            if (el.get("http-equiv") or "").lower() != "refresh":
                continue
            # EVERY refresh is rejected, not only one whose target is a network URL, because the
            # exporter removes every `meta[http-equiv=refresh]` whatever its target: a file
            # carrying a relative one is a file an export would change. It is also the fail-closed
            # reading of the channel - a refresh is a TOP-LEVEL NAVIGATION no meta-delivered CSP
            # can restrict, and an injected `<base href>` rebases a relative target onto the
            # network (that rebasing is a WIDER, still-open gap, tracked as issue #924 - every
            # other relative reference this file accepts is exposed to it too; rejecting the
            # refresh outright is what takes this ONE channel out of its reach). The network
            # wording is kept for a target that IS one, so the message still names the beacon when
            # there is one to name.
            if meta_refresh_navigates_to_network(el.get("content", "")):
                errors.append("offline mode: meta refresh points at a network URL - remove it")
            else:
                errors.append("offline mode: a meta refresh declaration is removed by the export "
                              "whatever its target, and one that does navigate is a top-level "
                              "navigation no meta-delivered CSP can restrict - remove it")
        for tag in ("body", "table", "td", "th", "div"):
            for el in _find_tag_attrs_egress(html, tag):
                _check_network_attr(tag, el, "background")
        # The exporter removes EVERY `on*` attribute, template content included, so a gate that did
        # not look would certify a hand-authored offline file the export would have changed - and an
        # inline handler is exactly the channel the CSP cannot close, since `script-src
        # 'unsafe-inline'` allows it and no meta-delivered policy restricts top-level navigation.
        # Read off the shared EGRESS index, the same view every resource check above asks, so the
        # scrub's DOM walk and this gate see the same elements (a self-closed foreign element and a
        # `<noscript>` fallback body included).
        for handler in _find_event_handler_attrs_egress(html):
            errors.append('offline mode: <%s %s="..."> begins with `on`, so the export scrubs it '
                          "(its test is a literal `^on`, which also takes `once`/`onward`); a real "
                          "inline handler runs with the document's own privileges, and the offline "
                          "CSP allows inline script and cannot stop a navigation, so remove or "
                          "rename the attribute here too"
                          % (handler.get("tag", "element"), handler.get("attr", "on...")))
        for style in parser.styles + parser.template_styles + _find_noscript_styles(html):
            # The `@import` gate and the `url(...)` one below are mirrored by the exporter's own
            # CSS strips, so the two sides were widened TOGETHER (issue #961, spec row CMH-VAL-08):
            # both now read the slash run after a special scheme rather than requiring two, so the
            # scheme-only `@import "https:host/t.css"` a browser resolves to the same host is
            # caught, and both require a non-empty host so neither reports a parse failure the
            # strip leaves behind.
            for m in CSS_NETWORK_IMPORT_RE.finditer(style.get("body", "")):
                errors.append('offline mode: @import "%s" loads over the network - inline or remove it' % m.group(1)[:80])
            if CSS_NETWORK_URL_RE.search(style.get("body", "")):
                errors.append("offline mode: style block contains a network url(...) - inline or remove it")
        for style in (parser.inline_styles + parser.template_inline_styles
                      + _find_noscript_inline_styles(html)):
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
    _hids = [h.get("id") for h in parser.headings if h.get("id") and not h.get("shadow")]
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
