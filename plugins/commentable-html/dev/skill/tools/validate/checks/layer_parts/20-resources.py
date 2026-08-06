# The offline-export notice on an `<iframe srcdoc>` (CMH-VAL-24) reports what a DIFFERENT mode's
# export would REMOVE, so it must never be the thing that blocks a document: it carries a stable
# prefix so `validate.ADVISORY_PREFIXES` keeps it out of every fail-closed path. That classification
# is scoped to the CONTENT-LOSS question and is NOT a ruling that a nested document is safe; what
# the frame FETCHES is a separate question, answered beside it by a BLOCKING finding from
# `_srcdoc_network_findings()` - an error, except a nested loading `<link>`, which is a warning
# mirroring the top-level rule (CMH-VAL-25, issue #1125).
SRCDOC_ADVISORY_PREFIX = "offline export advisory: "

# Whatever `str.split()` does not already treat as whitespace: the C0 controls (NUL, BEL,
# backspace, and ESC, which starts an ANSI escape sequence) and the C1 range.
_REPORT_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
# Far more than 80 collapsed characters can ever need, and it bounds the work on a `srcdoc` that
# carries a whole document.
_REPORT_SCAN_LIMIT = 4096


def _report_value(value):
    """Normalize an attribute value for a report message: bounded, one line, printable.

    A report line is printed line-oriented, and a `srcdoc` carries a whole DOCUMENT, so the raw
    value would split one finding across untagged lines. It is also authored text on its way to a
    terminal, so the non-whitespace C0/C1 controls that `str.split()` does NOT touch (NUL, BEL,
    backspace, and ESC, which starts an ANSI escape sequence) are replaced rather than passed
    through. The value is bounded BEFORE it is normalized, since normalizing megabytes of nested
    document to keep 80 characters is pure waste.
    """
    text = _REPORT_CONTROL_RE.sub(" ", (value or "")[:_REPORT_SCAN_LIMIT])
    out = " ".join(text.split())[:80]
    # A value that opens with a long run of blank or control text (a licence comment, deep
    # indentation) would otherwise report identically to a genuinely empty one.
    if not out and value:
        return "..."
    return out


# Every (tag, attr) pair a browser fetches to RENDER the document, beyond the five load-bearing
# groups (`img`, `script`, `iframe`, a loading `link`, `base`) the shareable rules always read.
# Each is an AUTOMATIC subresource load: it happens on open, with no user action, which is exactly
# what the `commentable-html-validated` stamp tells a recipient does not happen. They used to be
# checked in OFFLINE mode only (#1145), so a shareable document carrying `<video
# src="https://...">` validated STRICT-CLEAN and was stamped. Shared with `_SRCDOC_LOAD_ATTRS`
# below so the nested read cannot drift from the top-level set. The third field says whether the
# value is a `srcset` LIST rather than a single URL.
_MEDIA_LOAD_ATTRS = (
    ("video", "src", False), ("video", "poster", False),
    ("audio", "src", False), ("source", "src", False), ("source", "srcset", True),
    ("object", "data", False), ("embed", "src", False), ("track", "src", False),
    ("image", "href", False), ("image", "xlink:href", False),
    ("use", "href", False), ("use", "xlink:href", False),
    # An SVG filter primitive fetches exactly like an `<image>` or a `<use>`, but was in
    # neither this list nor the export strip, so a document carrying one rode into a
    # zero-network export and `--strict` certified it clean (#992). `HTMLParser` lowercases
    # the tag, so the lookup key is `feimage` while the export selector spells it `feImage`:
    # CSS compares a type selector case-SENSITIVELY for an SVG-namespaced element and
    # case-INSENSITIVELY for an HTML one, so that one portable spelling reaches both and the
    # two sides stay namespace-blind together (a current Chromium is laxer still and matches
    # any casing, which is an implementation detail neither side relies on).
    ("feimage", "href", False), ("feimage", "xlink:href", False),
)

# The legacy presentational `background` attribute, which fetches an image. NOT a tag list: the
# offline export's own strip selects the universal `[background]`, and a hand-maintained list was
# NARROWER than it - it named `body`, `table`, `td`, `th`, `div` and so missed the table PARTS
# (`tr`, `tbody`, `thead`, `tfoot`), where the attribute really is a presentation hint that fetches.
# Asking the attribute question instead of the tag question (`_find_attr_egress`) makes the two
# sides agree by construction and removes the list as a maintenance surface. The over-detection that
# comes with it - `div`, and now any other element where a browser ignores the attribute - is the
# same over-detection the strip already has, so neither side can reject what the other leaves.
_BACKGROUND_ATTR = "background"

# The (tag, attr) pairs whose value a browser FETCHES, applied INSIDE a nested `srcdoc` document:
# exactly the set the element-level rules below enforce on the top-level document in a mode that
# makes no zero-network promise. A `<base href>` is not itself a load and is handled beside this on
# the stricter `offline_is_non_local_ref`, the way the top-level rule handles it. An
# `<input type=image>`, the legacy `background` attribute and a `meta` refresh are handled beside it
# too, since none of them is keyed on the TAG alone.
_SRCDOC_LOAD_ATTRS = ((("img", "src", False), ("img", "srcset", True), ("iframe", "src", False),
                       ("link", "href", False))
                      + tuple(("script", attr, False) for attr in SCRIPT_LOAD_ATTRS)
                      + _MEDIA_LOAD_ATTRS)



# A nested document is entity-escaped once per level of nesting, so each level costs the level
# outside it about twice its own size and a real document bottoms out after one or two (a `srcdoc`
# can alternate quote styles for a level or so before `<` has to be escaped at all). The cap is far
# above anything an author writes and exists only so the walk can never be the thing that runs
# away. Reaching it is REPORTED rather than passed, because an unaudited frame is not a clean one.
_SRCDOC_MAX_DEPTH = 8


def _srcdoc_network_findings(value, depth=1):
    """Every network reference a nested `srcdoc` document carries, as (kind, tag, attr, value).

    The nested markup is read as a FRAGMENT through the SAME shared tag index every other rule here
    reads - the fragment lookup `_tag_attr_index` already serves for a KQL figure's inner HTML - so
    an `<a href>` stays navigation, a relative reference and a `data:` URI stay local, and a nested
    element gets the same verdict its top-level twin gets, at the same SEVERITY (the caller routes a
    nested `link` into `warnings`, exactly as the top-level rule does). The one deliberate
    difference is the Chart.js CDN loader, which is exempt at the top level and not here - see the
    `load` branch below for why the exemption cannot travel into a frame.

    A raw TEXT SCAN over the attribute value is the cheaper option and is deliberately NOT taken:
    it cannot tell a link, a `data:` URI or a URL written in prose from a load, so it would BLOCK
    benign nested markup, and a false rejection is the one failure mode a gate that withholds the
    validated stamp cannot afford. Reading the fragment costs no drift either, because - unlike the
    offline `srcdoc` rule (CMH-OFFLINE-04) - shareable mode has no exporter strip pass to keep in
    step, so this gate is the only implementation of the rule.

    The total work is bounded by the DOCUMENT, not by the branching factor: a frame's content is
    physically contained in its parent's attribute value (and shrinks by one round of entity
    escaping per level), so the nested text summed over every frame at every depth cannot exceed
    the document size times the depth cap. Each distinct value costs a FIXED TWO passes, not one:
    the per-tag lookups below all hit `_tag_attr_index`'s cache, and `_find_fragment_styles` adds
    one uncached scripting-disabled pass for the `<style>` bodies that index deliberately does not
    buffer. Two is a constant, so a wide or deep nest still costs work linear in the text it
    actually carries.
    """
    text = value or ""
    out = []
    # An empty answer from a parse that blew up means "could not look", never "loads nothing".
    if _tag_attrs_failed(text):
        return [("parse", None, None, None)]
    for tag, attr, is_srcset in _SRCDOC_LOAD_ATTRS:
        for el in _find_tag_attrs_egress(text, tag):
            if tag == "link" and not _link_loads(el):
                continue
            val = el.get(attr, "")
            if not val:
                continue
            for item in (srcset_candidate_urls(val) if is_srcset else [val]):
                # The top-level Chart.js CDN exemption exists for the ONE documented opt-in: the
                # loader that draws this document's `<canvas>` charts, whose version and SRI
                # `check_charts` audits when the document renders one. A copy parked inside a
                # nested document can never be that loader - a frame cannot draw into its host's
                # canvas - so the exemption has nothing to exempt here and does not travel with
                # the spelling.
                if is_network_url(item):
                    out.append(("load", tag, attr, item))
    # An `<input>` fetches only when its TYPE says so, so it cannot ride the flat pair list above.
    for el in _find_tag_attrs_egress(text, "input"):
        if (el.get("type") or "").lower() != "image":
            continue
        val = el.get("src", "")
        if val and is_network_url(val):
            out.append(("load", "input", "src", val))
    # The legacy `background` attribute, asked as an ATTRIBUTE question for the reason
    # `_BACKGROUND_ATTR` records - the strip's selector is the universal `[background]`.
    for el in _find_attr_egress(text, _BACKGROUND_ATTR):
        val = el.get("value", "")
        if val and is_network_url(val):
            out.append(("load", el.get("tag", "element"), _BACKGROUND_ATTR, val))
    # A refresh inside a frame navigates THAT frame automatically, on open, with no user action -
    # the same reason the top-level rule reports one. Only a NETWORK target: a relative refresh
    # inside a nested document reaches no network, and this mode has no strip to keep parity with.
    for el in _find_tag_attrs_egress(text, "meta"):
        if (el.get("http-equiv") or "").lower() != "refresh":
            continue
        if meta_refresh_navigates_to_network(el.get("content", "")):
            out.append(("refresh", "meta", "content", el.get("content", "")))
    # CSS egress carried in a nested `style=` attribute or a nested `<style>` BODY. The style
    # bodies need their own fallback parse (`_find_fragment_styles`) because the shared attribute
    # index deliberately does not buffer ordinary style bodies; scanning the raw nested TEXT for a
    # `url(...)` instead is the false-rejection trade CMH-VAL-25 rejected.
    for style in _find_inline_styles_egress(text):
        if CSS_NETWORK_URL_RE.search(style.get("value", "")):
            out.append(("style", style.get("tag", "element"), "style", style.get("value", "")))
    fragment_styles, styles_failed = _find_fragment_styles(text)
    if styles_failed:
        out.append(("parse", None, None, None))
    for style in fragment_styles:
        for m in CSS_NETWORK_IMPORT_RE.finditer(style.get("body", "")):
            out.append(("import", "style", "@import", m.group(1)))
        if CSS_NETWORK_URL_RE.search(style.get("body", "")):
            out.append(("sheet", "style", "url", ""))
    # A speculation ruleset inside a frame prefetches exactly as one at the top level does, and the
    # nested read is not allowed to be narrower than the top-level rule. PRESENCE is the test here
    # too - a document-source ruleset names no URL at all - so only the `type` is read and the
    # nested body is never parsed as JSON.
    for el in _find_tag_attrs_egress(text, "script"):
        if offline_active_data_script_type(el) == "speculationrules":
            out.append(("rules", "script", "type", "speculationrules"))
    for el in _find_tag_attrs_egress(text, "base"):
        val = el.get("href", "")
        if val and offline_is_non_local_ref(val):
            out.append(("base", "base", "href", val))
    for el in _find_tag_attrs_egress(text, "iframe"):
        if "srcdoc" in el:
            if depth >= _SRCDOC_MAX_DEPTH:
                out.append(("depth", None, None, None))
                continue
            out.extend(_srcdoc_network_findings(el.get("srcdoc"), depth + 1))
    return out


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
        label = "<%s %s=\"%s\">" % (_report_value(tag), attr, _report_value(val))
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
            if tag == "link" and attr == "href":
                warnings.append('<link %s="%s"> loads over the network and breaks the self-contained '
                                "guarantee - inline or remove it" % (attr, _report_value(item)))
            else:
                errors.append('<%s %s="%s"> loads over the network and breaks the self-contained guarantee - '
                              "inline or remove it" % (_report_value(tag), attr, _report_value(item)))
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
                                  % _report_value(src))
            elif not re.match(r"[a-z][a-z0-9+.\-]*:", src, re.I):
                warnings.append('<img src="%s"> is a local path - run tools/inline_images.py to embed '
                                "it as a data: URI so the image travels with the file" % _report_value(src))
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
    # to `src` as a deliberate NARROWING: `check_charts` does now audit an SVG `href`/`xlink:href`
    # loader's version pin and SRI (CMH-VAL-27), so the old "nothing else checks it" reason no
    # longer holds - but the exemption is a hole punched in the self-contained guarantee for ONE
    # documented opt-in, and widening it to a spelling no real document writes would give up a real
    # guarantee for nothing. The consequence is recorded rather than implied: an SVG-`href` CDN tag
    # IS a loader to `check_charts` and is still REFUSED here.
    # Parsed once per TAG (not once per tag/attribute pair): `_find_tag_attrs_egress` runs a full
    # pure-Python tokenizer pass over the whole document, and the widened script set would
    # otherwise triple that cost for scripts alone.
    for tag, attrs in (("link", ("href",)), ("script", SCRIPT_LOAD_ATTRS), ("iframe", ("src",))):
        for el in _find_tag_attrs_egress(html, tag):
            # A speculative-connection hint is rejected on its REL alone, before the href is read at
            # all (#1076): an offline document may not carry one whatever it points at, because the
            # network-URL predicate cannot be the layer for a channel whose leak is a name
            # RESOLUTION rather than a fetch (the measurement that settled that predicate's scheme
            # boundary is a TCP listener, which structurally cannot see one, and a DNS-capable
            # observer measured no resolver activity even for the http CONTROL hints - so no scheme
            # is evidenced inert). Deleting one costs no content: unlike a stylesheet or an icon it
            # shows a reader nothing. The export strip drops exactly this set of TOKENS
            # unconditionally, so the two sides agree by construction. The loader rule below is
            # skipped only for a link that is NOTHING BUT hints: on a mixed `rel="preconnect
            # stylesheet"` the strip keeps the element as a stylesheet, so its network href is a
            # second, separate defect and reporting only the hint would hand the author one error
            # per run.
            if tag == "link" and offline_mode and _link_speculates(el):
                errors.append('offline mode: <link rel="%s"> asks the browser to reach out to a '
                              "host before anything needs it - remove it (it shows a reader "
                              "nothing, so nothing is lost)" % (el.get("rel", "")[:80]))
                if not (link_rel_tokens(el.get("rel")) - SPECULATIVE_LINK_RELS) & FETCHING_LINK_RELS:
                    continue
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
            label = '<base href="%s">' % _report_value(val)
            if offline_mode:
                errors.append("offline mode: %s rebases every relative reference in the document "
                              "onto a base the file cannot resolve on its own - remove it" % label)
            else:
                errors.append("%s rebases every relative reference in the document onto a base the "
                              "file cannot resolve on its own and breaks the self-contained "
                              "guarantee - make the base relative, or drop it and write the "
                              "affected href/src values out in full" % label)
    # The rest of the AUTOMATIC-SUBRESOURCE set, in EVERY mode (#1145). Until this moved out of the
    # `offline_mode` branch below, the shareable half of the self-contained guarantee was enforced
    # on five element/attribute groups only, so `<video src="https://evil.example/v.mp4">`,
    # `<object data=...>`, `<embed src=...>`, `<input type=image src=...>`, an SVG `image`/`use`/
    # `feImage`, a legacy `background=`, and CSS `@import` / `url(...)` all validated STRICT-CLEAN
    # and were STAMPED - the one promise the stamp makes to a recipient who did not author the file.
    # Offline has a zero-network CSP behind it; a shareable file has nothing, so this gate is the
    # only layer. What an offline report SAYS is unchanged - `_check_network_attr` and `_css_error`
    # both pick their wording off `offline_mode`, and no offline error is added or removed - but the
    # ORDER shifts: these findings now precede the offline-only ones (the CSP, `srcdoc`, form, ping,
    # meta refresh, `on*`) instead of being interleaved with them. Nothing consumes the order (the
    # report is printed as a list and the tests match by content), so that is the whole delta.
    #
    # What is DELIBERATELY not widened is USER-INITIATED egress: `<a href>` (already exempt),
    # `form action` / `formaction`, and `a`/`area` `ping`. Each needs a click, so none of them
    # happens when a recipient merely OPENS the file, and the offline rules that reject them serve
    # the zero-network promise (and the export strips they are pinned to), not the self-contained
    # one. A `meta http-equiv=refresh` is NOT in that group and IS reported here - it fires with no
    # user action at all - which is the correction the review panel made to the first cut of this
    # rule; see the network-target check below. The speculative link rels need nothing here either:
    # `preconnect` and `dns-prefetch` are in `FETCHING_LINK_RELS`, so a NETWORK href on one is
    # already the ordinary shareable `link` warning above, and the offline-only extra is the
    # PRESENCE rule (#1076), which a relative hint - reaching no network at all - gives this
    # guarantee no reason to copy.
    #
    # Two deliberate OVER-detections ride along, kept because this gate fails closed and because
    # narrowing either would need the parent chain a flat tag index does not have: a `<source src>`
    # parked under a `<picture>` (where `src` is ignored) and a `<track src>` (which loads when a
    # text track is enabled rather than on open) are both reported. A third joins them with the
    # refresh rule below: a `<meta http-equiv=refresh>` parked in a `<template>` never fires (a
    # refresh is a PARSE-TIME pragma, so adopting the fragment later does not navigate), unlike a
    # template-parked `<img>`, which really does fetch the moment a script inserts it - so the
    # template-inclusion argument that carries the element rules does not carry this one, and it is
    # named here rather than glossed. Removing a reference that reaches no network costs an author
    # nothing; missing one costs the recipient the guarantee.
    for tag, attr, is_srcset in _MEDIA_LOAD_ATTRS:
        for el in _find_tag_attrs_egress(html, tag):
            _check_network_attr(tag, el, attr, srcset=is_srcset)
    # An `<input>` fetches only when its TYPE says so, so it is checked beside the flat pair list.
    for el in _find_tag_attrs_egress(html, "input"):
        if (el.get("type") or "").lower() == "image":
            _check_network_attr("input", el, "src")
    for el in _find_attr_egress(html, _BACKGROUND_ATTR):
        _check_network_attr(el.get("tag", "element"),
                            {_BACKGROUND_ATTR: el.get("value", "")}, _BACKGROUND_ATTR)
    # A meta refresh to a NETWORK target is not navigation a reader chose: `content="0;url=https://"`
    # fires the instant the document is parsed, with no click, so opening the file really does reach
    # the network - the one thing the validated stamp tells a recipient will not happen. That is what
    # separates it from `<a href>`, `form action`/`formaction` and `a ping`, which stay out of scope
    # because they need a user action. Only a NETWORK target here: a relative refresh reaches no
    # network at all, and shareable mode has no export strip to keep unconditional parity with, which
    # is why offline (which does, and rejects every refresh) keeps its own stricter rule below rather
    # than sharing this one. Gated on `not offline_mode` so one refresh is never reported twice.
    if not offline_mode:
        for el in _find_tag_attrs_egress(html, "meta"):
            if (el.get("http-equiv") or "").lower() != "refresh":
                continue
            if meta_refresh_navigates_to_network(el.get("content", "")):
                errors.append('<meta http-equiv="refresh" content="%s"> navigates to a network URL '
                              "the moment the document opens, with no user action, and breaks the "
                              "self-contained guarantee - remove it, or point it at a target inside "
                              "this file" % _report_value(el.get("content", "")))
    # CSS egress. The `@import` gate and the `url(...)` one are mirrored by the exporter's own CSS
    # strips, so the two sides were widened TOGETHER (issue #961, spec row CMH-VAL-08): both read
    # the slash run after a special scheme rather than requiring two, so the scheme-only
    # `@import "https:host/t.css"` a browser resolves to the same host is caught, and both require a
    # non-empty host so neither reports a parse failure the strip leaves behind. Running them in
    # shareable mode too adds no drift, because shareable mode runs no strip pass at all: the strips
    # are an OFFLINE-export step, so there is no second implementation to stay in step with here.
    def _css_error(offline_text, shareable_text):
        errors.append(("offline mode: " + offline_text) if offline_mode else shareable_text)
    for style in parser.styles + parser.template_styles + _find_noscript_styles(html):
        for m in CSS_NETWORK_IMPORT_RE.finditer(style.get("body", "")):
            _css_error('@import "%s" loads over the network - inline or remove it'
                       % _report_value(m.group(1)),
                       '@import "%s" loads over the network and breaks the self-contained '
                       "guarantee - inline or remove it" % _report_value(m.group(1)))
        if CSS_NETWORK_URL_RE.search(style.get("body", "")):
            _css_error("style block contains a network url(...) - inline or remove it",
                       "style block contains a network url(...) and breaks the self-contained "
                       "guarantee - inline or remove it")
    for style in (parser.inline_styles + parser.template_inline_styles
                  + _find_noscript_inline_styles(html)):
        if CSS_NETWORK_URL_RE.search(style.get("value", "")):
            _css_error("inline style on <%s> contains a network url(...) - inline or remove it"
                       % _report_value(style.get("tag", "element")),
                       "inline style on <%s> contains a network url(...) and breaks the "
                       "self-contained guarantee - inline or remove it"
                       % _report_value(style.get("tag", "element")))
    # A `<script type="speculationrules">` is the one ACTIVE-DATA block that reaches the network by
    # itself, with no user action and no code running: the browser reads the ruleset and prefetches
    # or prerenders. That is the same test every element rule above is drawn on, so it belongs in
    # shareable mode too - the review panel measured a stamped shareable file carrying one. It is
    # rejected whatever the ruleset SAYS, exactly as offline rejects it: a `"source": "document"`
    # ruleset names no URL at all and turns the document's own `<a href>` links - which this
    # guarantee deliberately exempts, because a reader has to CLICK them - into automatic fetches,
    # so there is no body that can be read as safe. An IMPORT MAP is deliberately NOT reported here:
    # it re-points where a bare specifier resolves and fetches nothing on its own, so it only
    # matters through a module load that the script rules would have to catch anyway; offline keeps
    # its stricter rule on it for export-strip parity. Gated on `not offline_mode` so one block is
    # never reported twice.
    if not offline_mode:
        for script in parser.scripts + parser.template_scripts:
            if offline_active_data_script_type(script["attrs"]) == "speculationrules":
                errors.append('<script type="speculationrules"> makes the browser prefetch or '
                              "prerender on its own the moment the document opens, with no user "
                              "action, and breaks the self-contained guarantee - remove the "
                              "ruleset (a document-source ruleset needs no URL of its own, so "
                              "there is no body that keeps the file self-contained)")
    if offline_mode:
        # A parse that could not be built was already reported at the top of this function, so the
        # lookups below are best-effort on a PARTIAL index rather than gated on it - they can only
        # add to a report that already says the document could not be read.
        errors.extend(_offline_csp_errors(parser))
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
                              % _report_value(el.get("srcdoc")))
        # A `<noscript>` in the HEAD is not an ordinary element to the scripting-DISABLED parse the
        # export re-parses with: the "in head noscript" insertion mode allows only `link`, `style`,
        # `meta`, `basefont`, `bgsound`, `noframes`, comments and whitespace, and anything else POPS
        # the fallback and REPROCESSES that node - and everything after it - under the "in head"
        # rules, so it becomes a head SIBLING (a `<script>`) or ends the head and lands in the body.
        # So a `<script>` parked there is promoted out INSIDE `DOMParser`, before any strip can see
        # it, and the export ACTIVATES code the source document never ran (with scripting on, a head
        # fallback is inert raw text). A promoted node is indistinguishable in the DOM from an
        # authored sibling, so the export judges the SOURCE STRING before it parses and drops such a
        # fallback whole; this rejects the same shape, so the two agree by construction rather than
        # leaving the exporter to emit a file its own gate would have to bless. What the mode ALLOWS
        # is untouched on both sides, so an ordinary head fallback is not content loss.
        for body in offline_head_noscript_promotions(html):
            errors.append('offline mode: a <noscript> in the document head ("%s") carries content '
                          'the "in head noscript" insertion mode does not allow, so a '
                          "scripting-disabled parse promotes it out of the fallback and into the "
                          "head - where markup a reader only ever sees as inert text becomes live "
                          "content the export would activate; the export removes such a fallback, "
                          "so remove it here too" % body.strip()[:80])
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
                label = '<%s ping="%s">' % (tag, _report_value(el.get("ping")))
                if beacon:
                    errors.append("offline mode: %s POSTs to a network URL (%s) on every click - "
                                  "remove the attribute" % (label, _report_value(beacon)))
                else:
                    errors.append("offline mode: %s audits every click by POSTing to the URLs it "
                                  "names, which a single-file export can neither need nor show the "
                                  "reader, so the export removes it whatever it points at - remove "
                                  "the attribute here too" % label)
        # CMH-OFFLINE-10. The referrer surface, the offline hardening the export does that this
        # gate had no counterpart for. No meta-delivered CSP can restrict TOP-LEVEL NAVIGATION, so
        # a reader's click is not blockable and the only thing left to control is that it carries
        # no provenance. The export therefore removes every `referrerpolicy` attribute and replaces
        # any authored referrer meta with `no-referrer`, while a hand-authored offline file
        # carrying `referrerpolicy="unsafe-url"` validated clean.
        #
        # What is reported is what a browser would HONOUR as a policy WEAKER than no-referrer, not
        # the mere presence of the attribute: an element policy that restates `no-referrer`, and a
        # value that names no policy at all (which a browser ignores in favour of the document
        # one), change nothing, so rejecting them would only cost an author content. That is the
        # same contract shape the CSP rule above has - the export replaces the policy
        # unconditionally while the gate accepts anything that MEETS the contract.
        #
        # Scoped to the elements the attribute has any meaning on (`REFERRER_POLICY_ELEMENTS`),
        # the way the `ping` rule is scoped to `a`/`area`, and read through the shared EGRESS
        # index so a `<template>`-parked element, a `<noscript>` fallback and a self-closed foreign
        # element are judged alike. An `a`/`area` whose `rel` carries `noreferrer` is skipped: HTML
        # sets that navigation's referrer to no-referrer regardless of the attribute, so the
        # attribute there weakens nothing. That skip is namespace-blind like every other rule here,
        # so an SVG `<a rel="noreferrer">` gets it too, and `rel` on `SVGAElement` is recent
        # (Chrome 89, Firefox 79, Safari 15) - on an older engine the `rel` is inert and the
        # attribute would apply. The residual is accepted rather than closed by dropping the skip:
        # it reaches only a HAND-AUTHORED offline file (the export removes the attribute whatever
        # it says), while dropping the skip would report the far commoner HTML anchor whose `rel`
        # really does deliver no-referrer.
        for tag in REFERRER_POLICY_ELEMENTS:
            for el in _find_tag_attrs_egress(html, tag):
                if "referrerpolicy" not in el:
                    continue
                policy = referrer_policy_attr(el.get("referrerpolicy", ""))
                if not policy or policy == "no-referrer":
                    continue
                if tag in ("a", "area") and "noreferrer" in link_rel_tokens(el.get("rel")):
                    continue
                errors.append('offline mode: <%s referrerpolicy="%s"> overrides the document\'s '
                              "no-referrer policy for that request, so a navigation from it "
                              "carries this document's own URL - the export removes every "
                              "referrerpolicy attribute, so remove it here too"
                              % (tag, (el.get("referrerpolicy") or "")[:80]))
        # The document half of the same surface. The policy is read the way HTML processes a
        # referrer meta - the WHOLE content value, ASCII-lowercased, with the legacy aliases folded
        # - rather than as the comma-separated list the HTTP header grammar uses, because that is
        # what a real Chromium was measured doing (`content="no-referrer, unsafe-url"` and a padded
        # `content=" unsafe-url "` both set NO policy there). Every permissive meta is reported
        # rather than only the last one that wins: the flat tag index cannot tell a live meta from
        # a `<template>`-parked one, so suppressing an earlier permissive meta because a later one
        # restates `no-referrer` could be masked by an inert meta, and the export removes every one
        # of them anyway, so "remove it" is the right remediation for each. The
        # `http-equiv="referrer-policy"` pragma is deliberately NOT checked: it is not an HTML
        # pragma directive and a real Chromium was measured ignoring it entirely, so it can weaken
        # nothing; the export still strips it, which is the same canonicalizing over-reach the CSP
        # meta gets.
        for el in _find_tag_attrs_egress(html, "meta"):
            if _ascii_lower(el.get("name") or "") != "referrer":
                continue
            policy = referrer_meta_policy(el.get("content", ""))
            if not policy or policy == "no-referrer":
                continue
            errors.append('offline mode: <meta name="referrer" content="%s"> declares a referrer '
                          "policy weaker than no-referrer - the export replaces it with "
                          "no-referrer, so set it to no-referrer or remove it"
                          % ((el.get("content") or "")[:80]))
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
                          % (_report_value(handler.get("tag", "element")),
                             _report_value(handler.get("attr", "on..."))))
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
    else:
        # The other half of the srcdoc decision (issue #1080). Sanitizing the nested document was
        # weighed against clearing it and REJECTED: it needs two independent recursive parsers -
        # this pure-Python tokenizer and the exporter's browser DOM - to agree at every depth on
        # serialization, doctype and rendering mode, fixed-point settling under reparse, and one
        # shared parse budget, which is exactly the drift the clear-outright rule removes; and it
        # would not even end the loss, since a value that will not settle still has to go. The cost
        # that is left is real but smaller than it was: the export empties the FRAME, and keeps the
        # nested markup beside it as escaped inert text (issue #1119), so what stops is the
        # RENDERING. The author used to meet even that only in a toast AFTER exporting, which is
        # why this says it while they are still AUTHORING. Presence, off the same shared EGRESS
        # index the offline rule reads, so it names the same frames the export will really empty
        # and still parses nothing nested.
        # ADVISORY, not a blocking warning: this branch is "not known to be offline" rather than
        # "known to be shareable" (a MISSING or malformed descriptor lands here too), and a
        # `srcdoc` is legitimate content in every mode that makes no zero-network promise. A
        # blocking warning would fail `--strict`, withhold the validated stamp - leaving the
        # runtime "not validated" banner permanently up - and make `retrofit` refuse to write, so
        # the only way to a clean run would be DELETING the nested document: the very loss this
        # exists to announce (see ADVISORY_PREFIXES in validate.py).
        # The value is collapsed before truncation because a `srcdoc` is a whole DOCUMENT and is
        # almost always multi-line, and a report line is printed line-oriented.
        for el in _find_tag_attrs_egress(html, "iframe"):
            if "srcdoc" in el:
                nested = el.get("srcdoc") or ""
                # The "kept" half is only promised where the exporter really keeps something. An
                # EMPTY or whitespace-only value keeps nothing (there is no nested document), and
                # that case is trivially visible to this tokenizer, so it is branched here rather
                # than glossed - a gate that describes behavior the exporter does not have is the
                # one-sided rule CMH-OFFLINE-04 exists to prevent. WHICH whitespace matters: the
                # literal HTML ASCII set, matching the exporter's `_OFFLINE_SRCDOC_CONTENT_RE`
                # character for character, because `str.strip()` also takes U+001C-U+001F and U+0085
                # while JS `trim()` also takes NBSP and U+FEFF - so the two engines' defaults
                # disagreed in BOTH directions on real values (`&#xFEFF;`, `&#28;`). The exporter's
                # other bound, a frame in a FOREIGN namespace, is not visible to a flat tokenizer
                # with no namespace to consult, so the wording carries it instead of branching on
                # it: what is kept is what could have RENDERED, and an `<iframe>` inside `<svg>`
                # renders nothing.
                kept = ("with the nested markup kept beside it as inert escaped text wherever "
                        "that markup could have rendered; author the snippet as content "
                        "yourself if it has to keep RENDERING in an offline copy"
                        if nested.strip(" \t\n\f\r") else
                        "and this one carries no nested document to keep")
                warnings.append(SRCDOC_ADVISORY_PREFIX +
                                '<iframe srcdoc="%s"> carries a nested document that Export '
                                "Offline removes from the frame - an offline export deliberately "
                                "does not inspect a document carried inside an attribute value - "
                                "so an offline copy of this file shows whatever local `src` the "
                                "frame also carries, or an empty frame, %s"
                                % (_report_value(nested), kept))
                # CMH-VAL-25, the OTHER half of what a nested document hides (issue #1125). The
                # advisory above answers the CONTENT-LOSS question and is deliberately not a ruling
                # that a nested document is SAFE: every self-contained rule above reads ELEMENTS,
                # so the byte-identical load that is a hard error written as `<img src="https://x">`
                # rode through untouched when it was written inside a `srcdoc`, and a shareable file
                # could carry the `commentable-html-validated` stamp and still phone home. It is
                # reported, not advised: unlike the content-loss notice there IS a way to a clean
                # run that keeps the nested document (make its references local), and the recipient
                # of a stamped file is entitled to the guarantee every other spelling is held to.
                # The SEVERITY mirrors the top-level rule element for element - a `link` is a
                # warning there, so it is a warning here (a non-advisory warning fails `--strict`
                # and withholds the stamp just the same, but a plain run must not report the nested
                # spelling of a reference more harshly than the top-level one). Offline mode is
                # untouched - it rejects a `srcdoc` on PRESENCE, which is strictly stronger, so the
                # two branches never double-report the same frame.
                # An `id` rides along in the label when the frame has one, because the value itself
                # is truncated and several frames in a document often open with the same
                # boilerplate - without it a report cannot say WHICH frame it means.
                frame_id = el.get("id")
                label = '<iframe%s srcdoc="%s">' % (
                    ' id="%s"' % _report_value(frame_id) if frame_id else "",
                    _report_value(el.get("srcdoc")))
                for kind, tag, attr, val in _srcdoc_network_findings(el.get("srcdoc")):
                    if kind == "load":
                        report = ('%s carries a nested <%s %s="%s"> that loads over the network '
                                  "and breaks the self-contained guarantee - a load written inside "
                                  "a nested document is the same load written as an element; make "
                                  "the reference local (inline it as a data: URI), or remove the "
                                  "frame" % (label, _report_value(tag), attr, _report_value(val)))
                        (warnings if (tag == "link" and attr == "href") else errors).append(report)
                    elif kind == "base":
                        errors.append('%s carries a nested <base href="%s"> that rebases every '
                                      "relative reference in the nested document onto a base the "
                                      "file cannot resolve on its own and breaks the "
                                      "self-contained guarantee - make the base relative, or "
                                      "remove the frame" % (label, _report_value(val)))
                    elif kind == "style":
                        errors.append("%s carries a nested inline style on <%s> that contains a "
                                      "network url(...) and breaks the self-contained guarantee - "
                                      "inline the reference as a data: URI, or remove the frame"
                                      % (label, _report_value(tag)))
                    elif kind == "import":
                        errors.append('%s carries a nested @import "%s" that loads over the network '
                                      "and breaks the self-contained guarantee - inline or remove "
                                      "the rule, or remove the frame" % (label, _report_value(val)))
                    elif kind == "sheet":
                        errors.append("%s carries a nested <style> block with a network url(...) "
                                      "that breaks the self-contained guarantee - inline the "
                                      "reference as a data: URI, or remove the frame" % label)
                    elif kind == "refresh":
                        errors.append('%s carries a nested meta refresh to a network URL ("%s") '
                                      "that navigates the frame off this file the moment it opens "
                                      "and breaks the self-contained guarantee - remove it, or "
                                      "remove the frame" % (label, _report_value(val)))
                    elif kind == "rules":
                        errors.append('%s carries a nested <script type="speculationrules"> that '
                                      "makes the browser prefetch or prerender on its own the "
                                      "moment the document opens and breaks the self-contained "
                                      "guarantee - remove the ruleset, or remove the frame" % label)
                    elif kind == "parse":
                        errors.append("%s carries a nested document that could not be parsed for "
                                      "the self-contained resource checks - fix the nested markup "
                                      "or remove the frame" % label)
                    else:
                        errors.append("%s nests documents more than %d deep, past the point this "
                                      "gate audits them - flatten the nesting or remove the frame"
                                      % (label, _SRCDOC_MAX_DEPTH))
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
        _body_classes = class_tokens(parser.body_attrs.get("class"))
        for _cls in _TRANSIENT_BODY_CLASSES:
            if _cls in _body_classes:
                errors.append('<body> carries the transient runtime UI-state class "%s" - it must '
                              "never be baked into a shipped document (the layer re-derives it on "
                              "load); remove it from the <body> open tag" % _cls)
    return errors, warnings
