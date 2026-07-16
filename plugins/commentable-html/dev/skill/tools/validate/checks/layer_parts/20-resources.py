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
