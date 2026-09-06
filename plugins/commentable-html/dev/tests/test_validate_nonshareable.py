from _validate_helpers import *


class NonShareableTests(unittest.TestCase):
    """Dual-mode validation: the nonshareable branch and its guardrails."""

    def _validate(self, content, companions=("css", "js", "assets"), version=NONSHAREABLE_VERSION):
        exts = {"css": ".css", "js": ".js", "assets": ".assets.js"}
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "doc.html")
            with open(p, "w", encoding="utf-8", newline="") as fh:
                fh.write(content)
            for c in companions:
                with open(os.path.join(d, "commentable-html%s" % exts[c]), "w",
                          encoding="utf-8") as fh:
                    fh.write("/* stub */")
            return validate.validate(p)

    def assertNonShareableError(self, content, needle, **kw):
        errors, _ = self._validate(content, **kw)
        self.assertTrue(any(needle in e for e in errors),
                        "expected an error containing %r, got: %r" % (needle, errors))

    def assertNonShareableWarn(self, content, needle, **kw):
        errors, warnings = self._validate(content, **kw)
        self.assertEqual(errors, [], "expected no errors, got: %r" % errors)
        self.assertTrue(any(needle in w for w in warnings),
                        "expected a warning containing %r, got: %r" % (needle, warnings))

    # -- positive controls -------------------------------------------------- #
    def test_minimal_nonshareable_is_clean(self):
        errors, warnings = self._validate(build_nonshareable())
        self.assertEqual(errors, [], "nonshareable errors: %r" % errors)
        self.assertEqual(warnings, [], "nonshareable warnings: %r" % warnings)

    def test_nonshareable_document_rejects_offline_mode(self):
        html = build_nonshareable().replace('"mode":"nonshareable"', '"mode":"offline"', 1)
        self.assertNonShareableError(html, 'commentableHtmlLayer.mode must be "nonshareable"')

    # -- the offline gate follows the DECLARED mode, not the lineage --------- #
    # The exporter runs the offline strips on whatever it stamps `mode: offline`, and the
    # NonShareable path reaches them too (`_buildStandaloneHtml` inlines the companions first).
    # Scoping the offline rules with `not nonshareable` keyed the GATE to a classification the
    # STRIPS never consult, so a document stamped offline that still carried a companion
    # reference switched every offline-only rule OFF. The descriptor rule failed such a file
    # anyway, so what was lost was the REPORT, not the verdict: the offline-only errors were not
    # named at all and the egress that was named carried the shareable wording.
    def _offline_lineage_doc(self, csp=False):
        html = build_nonshareable().replace('"mode":"nonshareable"', '"mode":"offline"', 1)
        if csp:
            html = html.replace(
                "<head>\n",
                '<head>\n<meta http-equiv="Content-Security-Policy" content="%s">\n' % OFFLINE_CSP,
                1)
        return html.replace(
            "<p>content</p>",
            '<p>content</p>\n'
            '  <button id="go" onclick="location.href=\'https://evil.example/x\'">go</button>\n'
            '  <img src="https://evil.example/beacon.png" alt="x">\n'
            '  <iframe src="https://evil.example/f.html"></iframe>')

    def test_offline_rules_run_on_a_nonshareable_lineage_offline_document(self):
        errors, _ = self._validate(self._offline_lineage_doc())
        # The event-handler gate: the export scrubs every `on*`, so a file it would change must
        # not be certified. This is the shape the issue names in dist/NONSHAREABLE.html.
        self.assertTrue(any("the export scrubs it" in e for e in errors), errors)
        # The zero-network CSP requirement.
        self.assertTrue(any("missing Content-Security-Policy meta tag" in e for e in errors), errors)
        # Egress is reported with the OFFLINE wording (an error with no Chart.js exemption),
        # not the shareable self-contained wording.
        for ref in ("beacon.png", "f.html"):
            self.assertTrue(any("offline mode:" in e and ref in e for e in errors), (ref, errors))
        # The descriptor rule still fires alongside them, so both problems are reported at once.
        self.assertTrue(any('mode must be "nonshareable"' in e for e in errors), errors)

    def test_offline_media_and_active_data_rules_run_on_a_nonshareable_lineage_document(self):
        # A second, independent offline-only family (media egress and the importmap rule), so the
        # coverage is not pinned to the one attribute the issue happened to name. This one carries
        # a VALID offline CSP, so the rules are shown to run on their own rather than riding along
        # with the missing-policy error - which is why the absence of that error is asserted too
        # (it also pins that the `csp=True` insertion really took effect).
        html = self._offline_lineage_doc(csp=True).replace(
            "<p>content</p>",
            '<p>content</p>\n'
            '  <video src="https://evil.example/v.mp4"></video>\n'
            '  <script type="importmap">{"imports": {"lib": "https://evil.example/lib.js"}}</script>')
        errors, _ = self._validate(html)
        self.assertFalse(any("missing Content-Security-Policy" in e for e in errors), errors)
        self.assertTrue(any("offline mode:" in e and "v.mp4" in e for e in errors), errors)
        self.assertTrue(any("import map" in e for e in errors), errors)

    def test_a_nonshareable_document_that_is_not_offline_keeps_its_own_rules(self):
        # The control the direction rests on: the offline rules key off the DECLARED mode, so a
        # legitimate NonShareable document is untouched by this change. Its companion `<link>` and
        # `<script src>` stay local references, its bootstrap dismiss button keeps its `onclick`,
        # and nothing gains an `offline mode:` error.
        html = self._offline_lineage_doc().replace('"mode":"offline"', '"mode":"nonshareable"', 1)
        errors, _ = self._validate(html)
        self.assertFalse(any("offline mode:" in e for e in errors), errors)
        self.assertFalse(any("the export scrubs it" in e for e in errors), errors)
        # It is not silently clean either - the shareable self-contained guarantee still applies.
        self.assertTrue(any("self-contained" in e and "f.html" in e for e in errors), errors)

    # -- offline chart snapshots contradict the companion-file mode --------- #
    # The `data-cm-offline-chart` image is the artifact of a SELF-CONTAINED Offline export, so a
    # document that loads its layer from companion files can never be one. The forcing rule used
    # to sit in the non-NonShareable branch alone, so this shape drew no error at all while the
    # runtime's legacy snapshot signal still read it as an offline document (CMH-OFFLINE-09).
    def _with_offline_chart(self, html):
        out = html.replace(
            "<p>content</p>",
            '<p>content</p>\n'
            '  <img class="cmh-chart" data-cm-offline-chart="true" '
            'src="data:image/png;base64,AA==" alt="Offline chart snapshot">')
        self.assertIn('data-cm-offline-chart="true"', out)
        return out

    def test_nonshareable_document_rejects_offline_chart_snapshots(self):
        self.assertNonShareableError(
            self._with_offline_chart(build_nonshareable()),
            'commentableHtmlLayer.mode is "nonshareable" but the document carries offline chart '
            "snapshots")

    def test_nonshareable_document_rejects_offline_chart_snapshots_in_the_legacy_spelling(self):
        # The pre-rename `nonportable` spelling is baked into every document produced before the
        # rename, so the rule must reach it too - and the error must quote the mode the document
        # actually declares rather than the current spelling.
        html = self._with_offline_chart(
            build_nonshareable().replace('"mode":"nonshareable"', '"mode":"nonportable"', 1))
        self.assertIn('"mode":"nonportable"', html)
        self.assertNonShareableError(
            html,
            'commentableHtmlLayer.mode is "nonportable" but the document carries offline chart '
            "snapshots")

    def test_nonshareable_document_reports_a_wrong_mode_and_its_snapshots_in_one_pass(self):
        # The snapshot rule stands on its own: a companion-file document whose descriptor ALSO
        # declares the wrong mode must learn both problems from one run, not one per run.
        html = self._with_offline_chart(
            build_nonshareable().replace('"mode":"nonshareable"', '"mode":"offline"', 1))
        self.assertIn('"mode":"offline"', html)
        errors, _ = self._validate(html)
        self.assertTrue(any('mode must be "nonshareable"' in e for e in errors), errors)
        self.assertTrue(any("carries offline chart snapshots" in e for e in errors), errors)
        # The message quotes the mode the document actually declares, whatever that is.
        self.assertTrue(any('mode is "offline" but' in e for e in errors), errors)

    def test_nonshareable_document_without_offline_chart_snapshots_is_clean(self):
        # Control: the rule fires on the SNAPSHOT, not on the nonshareable classification, so an
        # ordinary companion-file document stays clean.
        errors, warnings = self._validate(build_nonshareable())
        self.assertEqual(errors, [], errors)
        self.assertEqual(warnings, [], warnings)

    def test_an_offline_chart_attribute_outside_the_content_root_is_not_a_snapshot(self):
        # Scope control: the runtime reads `#commentRoot [data-cm-offline-chart]`, so the validator
        # must not fail a companion-file document for the attribute sitting in host chrome outside
        # the content root - it is not evidence either side would act on.
        html = build_nonshareable().replace(
            "<!-- BEGIN: commentable-html - NONSHAREABLE BOOTSTRAP -->",
            "<!-- BEGIN: commentable-html - NONSHAREABLE BOOTSTRAP -->\n"
            '<img class="cmh-chart" data-cm-offline-chart="true" '
            'src="data:image/png;base64,AA==" alt="Outside the content root">',
            1)
        self.assertIn('data-cm-offline-chart="true"', html)
        errors, warnings = self._validate(html)
        self.assertEqual(errors, [], errors)
        self.assertEqual(warnings, [], warnings)

    def test_a_nonshareable_document_may_carry_an_inline_event_handler(self):
        # Both places a NonShareable document legitimately carries an `on*`: the shipped bootstrap
        # dismiss button (which `_inlineNonShareableAssets` deletes with the whole NONSHAREABLE
        # BOOTSTRAP block before any export) and an authored one in the CONTENT region (which
        # survives the standalone rebuild and is removed by the offline build's
        # `_stripOfflineEventHandlers`). Neither is an offline document, so the handler gate must
        # not reach either.
        html = build_nonshareable().replace(
            "<p>content</p>",
            '<p>content</p>\n  <button type="button" onclick="this.hidden = true;">X</button>')
        html = html.replace(
            '<div id="cmhAssetBanner" class="cm-skip" role="alert" hidden>missing</div>',
            '<div id="cmhAssetBanner" class="cm-skip" role="alert" hidden>missing'
            '<button type="button" onclick="var b=this.closest(\'#cmhAssetBanner\');'
            ' if (b) b.hidden=true;">X</button></div>')
        # Both rewrites are string replacements against the helper's markup, so pin that each one
        # landed - otherwise a helper change makes one silently no-op and the test keeps passing
        # while covering half of what it claims.
        self.assertIn('onclick="this.hidden = true;"', html)
        self.assertIn("this.closest('#cmhAssetBanner')", html)
        errors, warnings = self._validate(html)
        self.assertEqual(errors, [], errors)
        self.assertEqual(warnings, [], warnings)

    def test_real_nonshareable_template_is_clean(self):
        eco = os.path.join(ROOT, "dist", "NONSHAREABLE.html")
        self.assertTrue(
            os.path.exists(eco),
            "dist/NONSHAREABLE.html not found - run the canonical build command in dev/README.md")
        errors, warnings = validate.validate(eco)
        self.assertEqual(errors, [], "dist/NONSHAREABLE.html errors: %r" % errors)
        self.assertEqual(warnings, [], "dist/NONSHAREABLE.html warnings: %r" % warnings)

    def test_is_nonshareable_detection(self):
        self.assertTrue(validate._is_nonshareable(build_nonshareable()))
        self.assertFalse(validate._is_nonshareable(build()))

    def test_nonshareable_detection_ignores_attribute_substrings(self):
        # A decoy tag whose attribute NAME merely contains "href"/"src" as a
        # substring (data-href / data-src) must NOT be treated as a real
        # companion reference - the browser would never load it.
        decoy = (
            '<!DOCTYPE html>\n<html><head>\n'
            '<link rel="preload" data-href="commentable-html.css">\n'
            '<script type="application/json" data-src="commentable-html.js">{}</script>\n'
            '</head><body>\n'
            + "\n".join([HANDLED_REGION, EMBEDDED_REGION, comment_ui(), MAIN])
            + '\n</body></html>\n')
        self.assertFalse(validate._is_nonshareable(decoy))

    def test_nonshareable_detection_accepts_unquoted_and_reordered_attrs(self):
        # Unquoted href/src and a reordered <meta content=.. name=..> are valid
        # HTML that the browser loads, so nonshareable detection must recognize them.
        v = NONSHAREABLE_VERSION
        unquoted = (
            "<!DOCTYPE html>\n<html><head>\n"
            "<link rel=stylesheet href=commentable-html.css>\n"
            "<script src=commentable-html.js></script>\n"
            "</head><body>\n"
            + "\n".join([HANDLED_REGION, EMBEDDED_REGION, comment_ui(), MAIN])
            + "\n</body></html>\n")
        self.assertTrue(validate._is_nonshareable(unquoted))
        self.assertEqual(validate._nonshareable_css_refs(unquoted), ["commentable-html.css"])
        # Reordered meta (content before name) is still read for the version.
        reordered = '<meta content="%s" name="commentable-html-version">' % v
        self.assertEqual(validate._nonshareable_meta_versions(reordered), [v])

    def test_nonshareable_detection_is_case_insensitive(self):
        # The "commentable-html" substring and the extension are matched
        # case-insensitively, so a mixed-case companion reference is still detected.
        v = NONSHAREABLE_VERSION
        mixed = (
            "<!DOCTYPE html>\n<html><head>\n"
            '<link rel="stylesheet" href="Commentable-HTML.CSS">\n'
            '<script src="Commentable-HTML.JS"></script>\n'
            "</head><body>\n"
            + "\n".join([HANDLED_REGION, EMBEDDED_REGION, comment_ui(), MAIN])
            + "\n</body></html>\n")
        self.assertTrue(validate._is_nonshareable(mixed))
        self.assertEqual(validate._nonshareable_css_refs(mixed), ["Commentable-HTML.CSS"])
        self.assertEqual(validate._nonshareable_js_refs(mixed), ["Commentable-HTML.JS"])

    def test_nonshareable_detection_ignores_gt_in_value_and_decoys(self):
        # The HTMLParser-based scan must (a) not be fooled by a '>' inside a quoted
        # attribute value, and (b) ignore link/script tags that only appear inside an
        # HTML comment or a <script>/<style> body (CDATA), which a naive regex matched.
        v = NONSHAREABLE_VERSION
        gt_in_value = '<link rel="stylesheet" title="a>b" href="commentable-html.css">'
        self.assertEqual(validate._nonshareable_css_refs(gt_in_value), ["commentable-html.css"])
        commented = '<!-- <link rel="stylesheet" href="commentable-html.css"> -->'
        self.assertEqual(validate._nonshareable_css_refs(commented), [])
        in_script = '<script>var s = "<link href=\'commentable-html.css\'>";</script>'
        self.assertEqual(validate._nonshareable_css_refs(in_script), [])

    def test_nonshareable_detection_accepts_cache_busted_refs(self):
        # A ?query / #fragment cache-buster is stripped by the browser before it
        # fetches the file, so detection and the on-disk check must ignore it too.
        busted = (
            '<link rel="stylesheet" href="commentable-html.css?v=1.7.0">'
            '<script src="commentable-html.js#build9"></script>'
            '<script src="commentable-html.assets.js?v=1.7.0"></script>')
        self.assertEqual(validate._nonshareable_css_refs(busted), ["commentable-html.css"])
        self.assertEqual(validate._nonshareable_js_refs(busted),
                         ["commentable-html.js", "commentable-html.assets.js"])

    def test_cache_busted_companion_refs_validate_clean(self):
        doc = (build_nonshareable()
               .replace('href="commentable-html.css"', 'href="commentable-html.css?v=1.7.0"')
               .replace('src="commentable-html.assets.js"', 'src="commentable-html.assets.js?v=1.7.0"')
               .replace('src="commentable-html.js"', 'src="commentable-html.js?v=1.7.0"'))
        errors, warnings = self._validate(doc)
        self.assertEqual(errors, [], "cache-busted refs should validate clean: %r" % errors)
        self.assertEqual(warnings, [], "cache-busted refs should not warn: %r" % warnings)


    # -- authored CONTENT never decides the mode (CMH-VAL-19) --------------- #
    _DEMO_MARKUP = ('  <p>Legacy files load the layer with:</p>\n'
                    '  <link rel="stylesheet" href="commentable-html.css">\n'
                    '  <script src="commentable-html.js"></script>\n')

    def _in_content(self, doc, markup):
        """Put `markup` inside the authored CONTENT region of a builder document."""
        out = doc.replace("  <p>content</p>\n", markup, 1)
        self.assertNotEqual(out, doc, "fixture premise: the CONTENT region was substituted")
        return out

    def test_companion_markup_in_authored_content_does_not_make_a_document_nonshareable(self):
        # A document ABOUT commentable-html legitimately demonstrates the companion markup in
        # its content. The real references always sit OUTSIDE the CONTENT region (the CSS link
        # in <head>, the scripts at the end of <body>), so an occurrence inside the region is
        # authored prose and must not flip the document into NonShareable mode.
        doc = self._in_content(build(), self._DEMO_MARKUP)
        self.assertFalse(validate._is_nonshareable(doc))
        self.assertEqual(validate._nonshareable_css_refs(doc), [])
        self.assertEqual(validate._nonshareable_js_refs(doc), [])
        errors, warnings = _validate_text(doc)
        self.assertEqual(errors, [], "authored demonstration should validate clean: %r" % errors)
        self.assertEqual(warnings, [], "authored demonstration should not warn: %r" % warnings)

    def test_a_real_nonshareable_document_that_also_demonstrates_the_markup_is_clean(self):
        doc = self._in_content(build_nonshareable(), self._DEMO_MARKUP)
        self.assertTrue(validate._is_nonshareable(doc))
        self.assertEqual(validate._nonshareable_css_refs(doc), ["commentable-html.css"])
        self.assertEqual(validate._nonshareable_js_refs(doc),
                         ["commentable-html.assets.js", "commentable-html.js"])
        errors, warnings = self._validate(doc)
        self.assertEqual(errors, [], "nonshareable errors: %r" % errors)
        self.assertEqual(warnings, [], "nonshareable warnings: %r" % warnings)

    def test_companion_markup_in_authored_content_does_not_stand_in_for_a_real_reference(self):
        # Still NonShareable (the assets companion is referenced for real), but the authored
        # quote must not satisfy the stylesheet / runtime requirements.
        doc = self._in_content(build_nonshareable(link=False, runtime=False), self._DEMO_MARKUP)
        self.assertTrue(validate._is_nonshareable(doc))
        self.assertNonShareableError(doc, "no commentable-html stylesheet")
        self.assertNonShareableError(doc, "no commentable-html runtime")

    def test_an_asset_banner_in_authored_content_does_not_satisfy_the_bootstrap(self):
        doc = self._in_content(
            build_nonshareable(banner=False),
            '  <div id="cmhAssetBanner" class="cm-skip" role="alert" hidden>missing</div>\n')
        self.assertNonShareableError(doc, "missing the #cmhAssetBanner element")

    def test_a_watchdog_mention_in_authored_content_does_not_satisfy_the_bootstrap(self):
        doc = self._in_content(build_nonshareable(watchdog=False),
                               "  <p>The bootstrap sets __commentableHtmlReady.</p>\n")
        self.assertNonShareableWarn(doc, "bootstrap watchdog")

    def test_a_version_meta_in_authored_content_does_not_satisfy_the_handshake(self):
        doc = self._in_content(
            build_nonshareable(meta=False),
            '  <meta name="commentable-html-version" content="%s">\n' % NONSHAREABLE_VERSION)
        self.assertNonShareableWarn(doc, 'missing <meta name="commentable-html-version"')

    # -- the CONTENT region is the one the PARSE agrees on ------------------ #
    def test_a_content_begin_marker_outside_commentroot_does_not_hide_the_layer(self):
        # MOVING the BEGIN marker into <head>, ahead of the real stylesheet link, keeps exactly
        # one marker of each kind, so the marker-count check stays silent. A text-offset view of
        # the region would blank the real <link> and report this document as Shareable; the parse
        # opens the region only inside #commentRoot, so the layer stays visible.
        doc = build_nonshareable().replace(CONTENT_BEGIN + "\n", "", 1)
        doc = doc.replace("<head>\n", "<head>\n" + CONTENT_BEGIN + "\n", 1)
        self.assertEqual(doc.count(CONTENT_BEGIN), 1, "fixture premise: the marker was moved")
        self.assertTrue(validate._is_nonshareable(doc))
        self.assertEqual(validate._nonshareable_css_refs(doc), ["commentable-html.css"])

    def test_a_content_end_marker_after_commentroot_does_not_hide_the_layer(self):
        # Likewise for the END marker moved to the end of <body>, past the runtime scripts.
        # #commentRoot closing ends the region regardless, so the scripts stay visible.
        doc = build_nonshareable().replace(CONTENT_END + "\n", "", 1)
        doc = doc.replace("\n</body>", "\n" + CONTENT_END + "\n</body>", 1)
        self.assertEqual(doc.count(CONTENT_END), 1, "fixture premise: the marker was moved")
        self.assertTrue(validate._is_nonshareable(doc))
        self.assertEqual(validate._nonshareable_js_refs(doc),
                         ["commentable-html.assets.js", "commentable-html.js"])

    def test_a_style_straddling_the_content_markers_does_not_hide_the_layer(self):
        # A <style> opened BEFORE the BEGIN marker and closed INSIDE the region puts the marker
        # itself in CDATA, so a browser never sees a CONTENT region here at all. Blanking the
        # marker-to-marker text would have deleted the closing </style> with it and left the
        # whole rest of the document parsing as CDATA - hiding the real companion scripts.
        doc = build_nonshareable().replace(CONTENT_BEGIN + "\n", "<style>\n" + CONTENT_BEGIN + "\n", 1)
        doc = doc.replace(CONTENT_END, "</style>\n" + CONTENT_END, 1)
        self.assertTrue(validate._is_nonshareable(doc))
        self.assertEqual(validate._nonshareable_js_refs(doc),
                         ["commentable-html.assets.js", "commentable-html.js"])

    def test_an_unterminated_script_in_authored_content_still_hides_the_runtime(self):
        # The reverse direction: an unterminated <script> in the authored content makes a browser
        # read everything after it - the runtime <script src> included - as script TEXT, so the
        # layer never loads. The validator must agree and still report the missing runtime.
        doc = self._in_content(build_nonshareable(), "  <script>var broken = 1;\n")
        self.assertEqual(validate._nonshareable_js_refs(doc), [])
        self.assertNonShareableError(doc, "no commentable-html runtime")

    def test_companion_markup_inside_a_template_is_inert(self):
        # <template> contents are an inert DocumentFragment: the scripts never run and the
        # stylesheet never loads, so they must not make a document NonShareable. The head case is
        # the one that uniquely pins the template guard - a template INSIDE the CONTENT region is
        # already excluded by the region itself.
        in_head = build().replace(
            "<head>\n", "<head>\n<template>\n" + self._DEMO_MARKUP + "</template>\n", 1)
        self.assertFalse(validate._is_nonshareable(in_head))
        self.assertEqual(validate._nonshareable_css_refs(in_head), [])
        in_content = build().replace(
            "  <p>content</p>\n",
            "  <template>\n" + self._DEMO_MARKUP + "  </template>\n", 1)
        self.assertFalse(validate._is_nonshareable(in_content))

    # -- a foreign-namespace element is not the HTML element it is named after #
    # No <template> is involved in any of these: an element merely NAMED `script` or `link` inside
    # <math> is an ordinary unknown MathML element a browser never runs, never loads and never
    # reveals. (`meta` cannot get there at all - it is an HTML5 foreign BREAKOUT start tag, so a
    # browser pops the open foreign elements and inserts it in the HTML namespace, which is why
    # its gate is a provable no-op and has no case here.) The layer views must apply the rule a
    # BROWSER applies PER NAMESPACE, which is why the SVG control below stays live rather than
    # being rejected too.
    _WATCHDOG_JS = ("window.setTimeout(function () { "
                    "if (!window.__commentableHtmlReady) {} }, 3000);")

    def _in_layer(self, doc, markup):
        """Put `markup` in the LAYER's own half of a builder document (outside #commentRoot)."""
        out = doc.replace("<body>\n", "<body>\n" + markup + "\n", 1)
        self.assertNotEqual(out, doc, "fixture premise: the layer markup was inserted")
        return out

    def _foreign_watchdog(self, root):
        return "<%s><script>%s</script></%s>" % (root, self._WATCHDOG_JS, root)

    def test_a_mathml_script_does_not_satisfy_the_bootstrap_watchdog(self):
        # A browser does not RUN a MathML <script>, so the watchdog never arms and the
        # missing-asset banner would never reveal itself.
        doc = self._in_layer(build_nonshareable(watchdog=False), self._foreign_watchdog("math"))
        self.assertNonShareableWarn(doc, "bootstrap watchdog")

    def test_an_svg_script_still_satisfies_the_bootstrap_watchdog(self):
        # The control that keeps the rule browser-accurate rather than "reject every foreign
        # namespace": SVG really defines <script> and a browser really runs an inline one.
        doc = self._in_layer(build_nonshareable(watchdog=False), self._foreign_watchdog("svg"))
        errors, warnings = self._validate(doc)
        self.assertEqual(errors, [], "svg watchdog errors: %r" % errors)
        self.assertFalse(any("bootstrap watchdog" in w for w in warnings), warnings)

    def test_a_mathml_companion_link_does_not_satisfy_the_stylesheet(self):
        doc = self._in_layer(build_nonshareable(link=False),
                             '<math><link rel="stylesheet" href="commentable-html.css"></math>')
        self.assertEqual(validate._nonshareable_css_refs(doc), [])
        self.assertNonShareableError(doc, "no commentable-html stylesheet")

    def test_a_mathml_companion_script_ref_does_not_satisfy_the_runtime(self):
        # An SVG script loads from `href`/`xlink:href` and a MathML one loads nothing at all, so
        # `src` is only a companion reference in the HTML namespace.
        doc = self._in_layer(build_nonshareable(runtime=False),
                             '<math><script src="commentable-html.js"></script></math>')
        self.assertEqual(validate._nonshareable_js_refs(doc), ["commentable-html.assets.js"])
        self.assertNonShareableError(doc, "no commentable-html runtime")

    def test_mathml_companion_markup_does_not_make_a_document_nonshareable(self):
        doc = self._in_layer(build(),
                             '<math><link rel="stylesheet" href="commentable-html.css">'
                             '<script src="commentable-html.js"></script></math>')
        self.assertFalse(validate._is_nonshareable(doc))
        self.assertEqual(validate._nonshareable_css_refs(doc), [])
        self.assertEqual(validate._nonshareable_js_refs(doc), [])

    def test_a_mathml_asset_banner_does_not_satisfy_the_bootstrap(self):
        # The runtime reveals and hides the banner through `.hidden`, an HTMLElement property the
        # namespace-scoped UA `[hidden]` rule follows, so a MathML element carrying the id is
        # found by getElementById and then can never be shown or hidden.
        doc = self._in_layer(build_nonshareable(banner=False),
                             '<math id="cmhAssetBanner" class="cm-skip"></math>')
        self.assertNonShareableError(doc, "missing the #cmhAssetBanner element")

    # The SVG half of the same rule. SVG is NOT simply "foreign, therefore rejected": it runs an
    # inline <script> (above), but it defines no `link`, its script loads from `href`/`xlink:href`
    # rather than `src`, and an SVGElement has no `.hidden`. These three pin that the layer TAG and
    # ID views are `ns == "html"` and not the wider execute set, so unifying the two gates - the
    # obvious later refactor - fails here instead of silently reopening the hole for SVG.
    def test_an_svg_companion_link_does_not_satisfy_the_stylesheet(self):
        doc = self._in_layer(build_nonshareable(link=False),
                             '<svg><link rel="stylesheet" href="commentable-html.css"></svg>')
        self.assertEqual(validate._nonshareable_css_refs(doc), [])
        self.assertNonShareableError(doc, "no commentable-html stylesheet")

    def test_an_svg_companion_script_ref_does_not_satisfy_the_runtime(self):
        doc = self._in_layer(build_nonshareable(runtime=False),
                             '<svg><script src="commentable-html.js"></script></svg>')
        self.assertEqual(validate._nonshareable_js_refs(doc), ["commentable-html.assets.js"])
        self.assertNonShareableError(doc, "no commentable-html runtime")

    def test_an_svg_asset_banner_does_not_satisfy_the_bootstrap(self):
        # Also covers the SELF-CLOSED foreign shape, which is recorded but never pushed.
        for markup in ('<svg id="cmhAssetBanner" class="cm-skip"></svg>',
                       '<svg id="cmhAssetBanner" class="cm-skip"/>'):
            with self.subTest(markup=markup):
                doc = self._in_layer(build_nonshareable(banner=False), markup)
                self.assertNonShareableError(doc, "missing the #cmhAssetBanner element")

    # The POSITIVE direction, which an "is there a <math>/<svg> ancestor?" implementation would
    # get wrong: at an HTML integration point a browser puts the child back in the HTML namespace,
    # so the layer's own markup written there is live and must still count.
    def test_an_html_integration_point_script_still_satisfies_the_watchdog(self):
        doc = self._in_layer(
            build_nonshareable(watchdog=False),
            "<svg><foreignObject><script>%s</script></foreignObject></svg>" % self._WATCHDOG_JS)
        errors, warnings = self._validate(doc)
        self.assertEqual(errors, [], "foreignObject watchdog errors: %r" % errors)
        self.assertFalse(any("bootstrap watchdog" in w for w in warnings), warnings)

    def test_an_html_integration_point_companion_link_still_counts(self):
        # Both integration-point kinds, so an "is there a <math>/<svg> ancestor?" implementation
        # fails here rather than silently dropping the layer's own markup.
        for wrapper in ("<math><mtext>%s</mtext></math>",
                        "<svg><foreignObject>%s</foreignObject></svg>"):
            with self.subTest(wrapper=wrapper):
                doc = self._in_layer(
                    build(),
                    wrapper % '<link rel="stylesheet" href="commentable-html.css">')
                self.assertEqual(validate._nonshareable_css_refs(doc), ["commentable-html.css"])

    def test_a_padded_annotation_xml_encoding_is_not_an_html_integration_point(self):
        # HTML5 matches the `encoding` VALUE exactly (ASCII case-insensitively), with no trimming,
        # so ` text/html` keeps the subtree in MathML and its <script> never runs. Accepting the
        # padded value reopened this very bypass through one space. Both members of the accepted
        # set are exercised, so trimming the set down to `text/html` is caught too.
        for enc in ("text/html", "application/xhtml+xml"):
            for padded in (" %s" % enc, "%s " % enc, "\t%s" % enc):
                with self.subTest(encoding=padded):
                    doc = self._in_layer(
                        build_nonshareable(watchdog=False),
                        '<math><annotation-xml encoding="%s"><script>%s</script>'
                        "</annotation-xml></math>" % (padded, self._WATCHDOG_JS))
                    self.assertNonShareableWarn(doc, "bootstrap watchdog")

    def test_an_unpadded_annotation_xml_encoding_is_still_an_html_integration_point(self):
        for enc in ("text/html", "TEXT/HTML", "application/xhtml+xml", "APPLICATION/XHTML+XML"):
            with self.subTest(encoding=enc):
                doc = self._in_layer(
                    build_nonshareable(watchdog=False),
                    '<math><annotation-xml encoding="%s"><script>%s</script>'
                    "</annotation-xml></math>" % (enc, self._WATCHDOG_JS))
                errors, warnings = self._validate(doc)
                self.assertEqual(errors, [], "annotation-xml watchdog errors: %r" % errors)
                self.assertFalse(any("bootstrap watchdog" in w for w in warnings), warnings)

    def test_a_watchdog_in_an_externally_loaded_script_does_not_count(self):
        # A browser that fetches an external script IGNORES the element's own child text, so a
        # token folded into the companion tag never runs. The attribute is per namespace: `src`
        # on an HTML script, `href`/`xlink:href` on an SVG one (an SVG script has no `src`). The
        # test is attribute PRESENCE, not value: `<script src="">` fires an error event and still
        # never runs the inline body, so the empty spellings are pinned alongside the real ones.
        for markup in ('<script src="commentable-html.js">%s</script>',
                       '<script src="">%s</script>',
                       '<svg><script href="x.js">%s</script></svg>',
                       '<svg><script href="">%s</script></svg>',
                       '<svg><script xlink:href="x.js">%s</script></svg>',
                       '<svg><script xlink:href="">%s</script></svg>'):
            with self.subTest(markup=markup):
                doc = self._in_layer(build_nonshareable(watchdog=False),
                                     markup % self._WATCHDOG_JS)
                self.assertNonShareableWarn(doc, "bootstrap watchdog")

    def test_a_source_attribute_of_the_other_namespace_does_not_suppress_the_watchdog(self):
        # The positive half of the same rule, and the control that keeps it PER NAMESPACE: an SVG
        # script has no `src` (so one there is an inert unknown attribute and the inline body still
        # runs), and an HTML script ignores `href`/`xlink:href` the same way. A gate that tested
        # the union of the attributes would wrongly report these documents as having no watchdog.
        for markup in ('<script href="x.js">%s</script>',
                       '<script xlink:href="x.js">%s</script>',
                       '<svg><script src="x.js">%s</script></svg>'):
            with self.subTest(markup=markup):
                doc = self._in_layer(build_nonshareable(watchdog=False),
                                     markup % self._WATCHDOG_JS)
                errors, warnings = self._validate(doc)
                self.assertEqual(errors, [], "errors: %r" % errors)
                self.assertFalse(any("bootstrap watchdog" in w for w in warnings), warnings)

    # -- CMH-VAL-28: a companion reference a browser would not run is not the runtime ------- #
    # `_nonshareable_js_refs` counted any `<script src="commentable-html.js">` by NAME and `src`
    # alone, so an inert TYPE (or `nomodule`) satisfied "the runtime is here" while the layer
    # never loaded and the document validated clean - the same fail-OPEN class the loader search
    # in `charts.py` already closed with `_is_executable_js`.
    def test_an_inert_typed_companion_script_does_not_satisfy_the_runtime(self):
        for attr in ('type="application/json"', 'type="text/plain"', "nomodule"):
            with self.subTest(attr=attr):
                doc = self._in_layer(
                    build_nonshareable(runtime=False),
                    '<script %s src="commentable-html.js"></script>' % attr)
                self.assertEqual(validate._nonshareable_js_refs(doc),
                                 ["commentable-html.assets.js"])
                self.assertNonShareableError(doc, "no commentable-html runtime")

    def test_a_runnable_typed_companion_script_still_satisfies_the_runtime(self):
        # The controls that keep the rule the BROWSER's rule rather than "only a bare tag counts":
        # an explicit JS type, a legacy runnable type, an EMPTY type (which HTML reads as classic),
        # a `language` naming JavaScript, and a MODULE script - on which `nomodule` has no effect
        # at all, since the spec tests it on the CLASSIC branch only.
        for attr in ('type="text/javascript"', 'type="TEXT/JavaScript"', 'type="text/jscript"',
                     'type=""', 'language="JavaScript"', 'type="module"', 'nomodule type="module"'):
            with self.subTest(attr=attr):
                doc = self._in_layer(
                    build_nonshareable(runtime=False),
                    '<script %s src="commentable-html.js"></script>' % attr)
                errors, _ = self._validate(doc)
                self.assertEqual([e for e in errors if "no commentable-html runtime" in e], [],
                                 errors)

    def test_a_companion_script_type_must_be_a_whole_essence_match(self):
        # HTML matches the type string as a WHOLE against the JavaScript MIME type essences, so a
        # MIME PARAMETER defeats the match and a whitespace-only value is not "absent" - neither
        # executes in any modern browser, so neither is the runtime. (`_is_executable_js`, the
        # type test the offline strips share with the exporter, deliberately splits at `;` because
        # over-inclusion is the safe direction THERE; here it would be fail-OPEN.)
        for attr in ('type="text/javascript; charset=utf-8"', 'type="module; charset=utf-8"',
                     'type=" "', 'language="vbscript"'):
            with self.subTest(attr=attr):
                doc = self._in_layer(
                    build_nonshareable(runtime=False),
                    '<script %s src="commentable-html.js"></script>' % attr)
                self.assertNonShareableError(doc, "no commentable-html runtime")

    def test_an_inert_typed_remote_companion_is_still_refused_as_a_network_load(self):
        # Dropping a reference from this list must not drop it from the EGRESS gate. The
        # self-contained scan reads the shared tag index and is deliberately type- and
        # namespace-blind, so the remote URL is still an error - the narrowing above changes which
        # message names the document, never whether it is refused.
        doc = self._in_layer(
            build_nonshareable(),
            '<script type="application/json" src="https://evil.example/commentable-html.x.js">'
            "</script>")
        errors, _ = self._validate(doc)
        self.assertTrue(any("evil.example" in e for e in errors), errors)

    def test_a_companion_stylesheet_link_must_really_be_a_stylesheet(self):
        # The CSS half of the same question: a browser applies a stylesheet only because the `rel`
        # list says `stylesheet`, so a preload/no-rel link leaves the layer unstyled - and neither
        # does a `disabled` one, whose whole meaning is "not applied" and which nothing in the
        # runtime ever enables.
        for attrs in ('rel="preload" as="style"', 'rel="modulepreload"', "",
                      'rel="stylesheet" disabled', 'rel="stylesheet" type="text/plain"'):
            with self.subTest(attrs=attrs):
                doc = self._in_layer(
                    build_nonshareable(link=False),
                    '<link %s href="commentable-html.css">' % attrs)
                self.assertEqual(validate._nonshareable_css_refs(doc), [])
                self.assertNonShareableError(doc, "no commentable-html stylesheet")

    def test_a_companion_reference_a_browser_ignores_still_reports_a_leaked_path(self):
        # The narrowing above changed only the CLASSIFICATION. Whether a baked absolute path leaks
        # a local directory is a property of the ref STRING and is true whether or not a browser
        # runs or applies the element - the disclosure is in the shipped bytes either way - and
        # nothing else in the validator reports a local path on a script or link.
        for markup in ('<script type="application/json" src="/srv/priv/commentable-html.js">'
                       "</script>",
                       '<link rel="preload" as="style" href="/srv/priv/commentable-html.css">'):
            with self.subTest(markup=markup[:40]):
                doc = self._in_layer(build_nonshareable(), markup)
                _errors, warnings = self._validate(doc)
                self.assertTrue(any("is an absolute path" in w for w in warnings), warnings)

    def test_a_document_whose_every_companion_is_unusable_is_not_nonshareable_at_all(self):
        # The BOUNDARY of the test above, pinned so it is a decision rather than an accident.
        # These are NonShareable-mode diagnostics, and a file whose EVERY companion reference is
        # one a browser cannot use never enters that mode: it is a Shareable document carrying a
        # stray inert reference, so it must not be judged - or reported - against a companion
        # contract it never entered. That is exactly the misclassification CMH-VAL-28 fixes.
        doc = self._in_layer(
            build(),
            '<script type="application/json" src="/srv/priv/commentable-html.js"></script>\n'
            '<link rel="preload" as="style" href="/srv/priv/commentable-html.css">')
        self.assertFalse(validate._is_nonshareable(doc))
        errors, warnings = self._validate(doc)
        self.assertEqual([m for m in errors + warnings if "nonshareable mode:" in m], [],
                         errors + warnings)

    def test_a_real_stylesheet_rel_still_satisfies_the_stylesheet(self):
        for rel in ('rel="stylesheet"', 'rel="STYLESHEET"', 'rel="stylesheet preload"',
                    'rel="stylesheet" type="text/css"', 'rel="stylesheet" type=" TEXT/CSS "'):
            with self.subTest(rel=rel):
                doc = self._in_layer(
                    build_nonshareable(link=False),
                    '<link %s href="commentable-html.css">' % rel)
                errors, _ = self._validate(doc)
                self.assertEqual([e for e in errors if "no commentable-html stylesheet" in e], [],
                                 errors)

    def test_an_inert_typed_companion_script_does_not_make_a_document_nonshareable(self):
        # The mode determination reads the same list, so a Shareable document that carries an
        # inert-typed companion tag must not be judged by the NonShareable rule set.
        doc = self._in_layer(build(), '<script type="application/json" '
                                      'src="commentable-html.js"></script>')
        self.assertEqual(validate._nonshareable_js_refs(doc), [])
        self.assertFalse(validate._is_nonshareable(doc))

    # -- CMH-VAL-29: an SVG script body written as a CDATA section really executes ---------- #
    def test_an_svg_cdata_watchdog_still_satisfies_the_bootstrap(self):
        # Inside foreign content `<![CDATA[` opens a REAL section and its content is character
        # data, so this is the same DOM - and the same running script - as writing the body
        # directly. The payload never reached the capture, so a watchdog that really does arm was
        # reported missing: a false positive on a valid document.
        doc = self._in_layer(build_nonshareable(watchdog=False),
                             "<svg><script><![CDATA[%s]]></script></svg>" % self._WATCHDOG_JS)
        errors, warnings = self._validate(doc)
        self.assertEqual(errors, [], "svg CDATA watchdog errors: %r" % errors)
        self.assertFalse(any("bootstrap watchdog" in w for w in warnings), warnings)

    def test_a_mathml_cdata_watchdog_does_not_count(self):
        # The MathML control: a section is real there too (MathML is foreign content), so the body
        # is captured - but a browser runs no MathML script, so it still does not arm the watchdog.
        doc = self._in_layer(build_nonshareable(watchdog=False),
                             "<math><script><![CDATA[%s]]></script></math>" % self._WATCHDOG_JS)
        self.assertNonShareableWarn(doc, "bootstrap watchdog")

    def test_a_cdata_spelling_in_an_html_script_is_just_more_script_text(self):
        # The HTML control the routing must not disturb: in HTML content `<![CDATA[` opens no
        # section at all, and inside a raw-text `<script>` body it is simply more text - which is
        # also what a browser runs, so this one DOES arm the watchdog.
        doc = self._in_layer(build_nonshareable(watchdog=False),
                             "<script><![CDATA[%s]]></script>" % self._WATCHDOG_JS)
        errors, warnings = self._validate(doc)
        self.assertEqual(errors, [], "errors: %r" % errors)
        self.assertFalse(any("bootstrap watchdog" in w for w in warnings), warnings)

    def test_a_watchdog_token_split_across_two_chunks_still_counts(self):
        # A browser runs the element's whole text; this parser delivers it in as many pieces as the
        # source has. A section is a piece of its own, and foreign content splits at every child,
        # so a per-chunk match reported a watchdog that really does arm as missing.
        head, tail = "window.__commentable", "HtmlReady = window.__commentableHtmlReady;"
        for body in ("<![CDATA[%s]]><![CDATA[%s]]>" % (head, tail),
                     "<![CDATA[%s]]>%s" % (head, tail),
                     "%s<g/>%s" % (head, tail)):
            with self.subTest(body=body[:40]):
                doc = self._in_layer(build_nonshareable(watchdog=False),
                                     "<svg><script>%s</script></svg>" % body)
                errors, warnings = self._validate(doc)
                self.assertEqual(errors, [], "errors: %r" % errors)
                self.assertFalse(any("bootstrap watchdog" in w for w in warnings), warnings)

    def test_an_svg_script_ignores_nomodule(self):
        # `nomodule` is an HTMLScriptElement attribute; SVG defines none, so a browser runs an SVG
        # script that carries one. Applying the skip in every executing namespace would have been a
        # new false positive on a document that really works - the exact direction CMH-VAL-19's
        # per-namespace rule exists to avoid.
        doc = self._in_layer(build_nonshareable(watchdog=False),
                             "<svg><script nomodule>%s</script></svg>" % self._WATCHDOG_JS)
        errors, warnings = self._validate(doc)
        self.assertEqual(errors, [], "errors: %r" % errors)
        self.assertFalse(any("bootstrap watchdog" in w for w in warnings), warnings)

    def test_an_html_script_honors_nomodule(self):
        doc = self._in_layer(build_nonshareable(watchdog=False),
                             "<script nomodule>%s</script>" % self._WATCHDOG_JS)
        self.assertNonShareableWarn(doc, "bootstrap watchdog")

    def test_an_svg_script_ignores_the_legacy_language_attribute(self):
        # `language` is an HTMLScriptElement attribute too, so an SVG script carrying one is still
        # a classic script a browser runs. Applying the HTML fallback in every namespace would
        # have refused a document that works.
        doc = self._in_layer(build_nonshareable(watchdog=False),
                             '<svg><script language="vbscript">%s</script></svg>'
                             % self._WATCHDOG_JS)
        errors, warnings = self._validate(doc)
        self.assertEqual(errors, [], "errors: %r" % errors)
        self.assertFalse(any("bootstrap watchdog" in w for w in warnings), warnings)

    def test_an_html_script_honors_the_legacy_event_for_pair(self):
        # HTML skips a CLASSIC script carrying both `event` and `for` unless they name the window
        # load handler, so a watchdog written that way never arms.
        doc = self._in_layer(build_nonshareable(watchdog=False),
                             '<script event="y" for="x">%s</script>' % self._WATCHDOG_JS)
        self.assertNonShareableWarn(doc, "bootstrap watchdog")
        ok = self._in_layer(build_nonshareable(watchdog=False),
                            '<script event="onload" for="window">%s</script>' % self._WATCHDOG_JS)
        errors, warnings = self._validate(ok)
        self.assertEqual(errors, [], "errors: %r" % errors)
        self.assertFalse(any("bootstrap watchdog" in w for w in warnings), warnings)

    # -- a region that does not PARSE where it reads is refused ------------- #
    def test_a_content_end_marker_swallowed_by_a_style_body_errors(self):
        # The layer view is derived from the parse, so a region that does not open and close where
        # the text says it does must be refused rather than guessed: markup after the broken
        # boundary would otherwise be silently misattributed to the author or to the layer.
        doc = build_nonshareable().replace(CONTENT_END, "<style>\n" + CONTENT_END + "\n</style>", 1)
        self.assertEqual(doc.count(CONTENT_END), 1, "fixture premise: still exactly one marker")
        self.assertNonShareableError(doc, "does not parse with a well-formed region")

    def test_an_unclosed_template_hiding_the_content_end_marker_errors(self):
        doc = self._in_content(build_nonshareable(), "  <template>\n")
        self.assertEqual(doc.count(CONTENT_END), 1, "fixture premise: still exactly one marker")
        self.assertNonShareableError(doc, "does not parse with a well-formed region")

    def test_an_unbalanced_root_close_in_authored_content_errors(self):
        # An extra </main> ends #commentRoot mid-region, so everything after it would be read as
        # the layer's own markup.
        doc = self._in_content(build_nonshareable(), "  <p>content</p>\n</main>\n")
        self.assertNonShareableError(doc, "does not parse with a well-formed region")

    def test_a_watchdog_token_outside_an_executable_script_does_not_count(self):
        # The watchdog IS an inline script. A reviewer note in the embedded-comments JSON, or an
        # inert <template>, that merely contains the token must not satisfy the check.
        doc = build_nonshareable(watchdog=False).replace(
            '<script type="application/json" id="embeddedComments">[]</script>',
            '<script type="application/json" id="embeddedComments">'
            '[{"id":"cab12345","quote":"q","note":"__commentableHtmlReady","created":"2026-01-01"}]'
            '</script>', 1)
        self.assertNonShareableWarn(doc, "bootstrap watchdog")

    def test_missing_stylesheet_link_errors(self):
        self.assertNonShareableError(build_nonshareable(link=False), "no commentable-html stylesheet")

    def test_missing_runtime_script_errors(self):
        self.assertNonShareableError(build_nonshareable(runtime=False), "no commentable-html runtime")

    def test_missing_assets_js_warns(self):
        self.assertNonShareableWarn(build_nonshareable(assets=False), "Export with embedded comments", companions=("css", "js"))

    def test_missing_version_meta_warns(self):
        self.assertNonShareableWarn(build_nonshareable(meta=False), 'missing <meta name="commentable-html-version"')

    def test_version_meta_does_not_compare_to_versionless_filenames(self):
        html = build_nonshareable(version="9.9.9")
        errors, warnings = self._validate(html)
        self.assertEqual(errors, [])
        self.assertFalse(any("must match" in w for w in warnings), warnings)

    def test_missing_banner_errors(self):
        self.assertNonShareableError(build_nonshareable(banner=False), "#cmhAssetBanner")

    def test_missing_watchdog_warns(self):
        self.assertNonShareableWarn(build_nonshareable(watchdog=False), "bootstrap watchdog")

    def test_missing_companion_file_errors(self):
        # HTML references the runtime but the .js file is absent on disk.
        self.assertNonShareableError(build_nonshareable(), "companion file not found", companions=("css", "assets"))

    def test_nonshareable_state_regions_still_validated(self):
        # Dropping the inline HANDLED IDS region must still fail in nonshareable mode.
        html = build_nonshareable().replace(HANDLED_REGION, "")
        self.assertNonShareableError(html, "handledCommentIds")

    def test_nonshareable_uses_marker_wrapped_companion_regions(self):
        html = build_nonshareable()
        self.assertIn("BEGIN: commentable-html - CSS", html)
        self.assertIn("BEGIN: commentable-html - JS", html)

    def test_absolute_companion_path_warns(self):
        # An absolute path is usable but leaks a local directory - warn, do not error.
        with tempfile.TemporaryDirectory() as d:
            css = os.path.join(d, "commentable-html.css")
            for c, ext in (("css", ".css"), ("js", ".js"), ("assets", ".assets.js")):
                with open(os.path.join(d, "commentable-html%s" % ext), "w") as fh:
                    fh.write("/* stub */")
            html = build_nonshareable().replace(
                'href="commentable-html.css"',
                'href="%s"' % css.replace("\\", "/"))
            p = os.path.join(d, "doc.html")
            with open(p, "w", encoding="utf-8", newline="") as fh:
                fh.write(html)
            errors, warnings = validate.validate(p)
        self.assertEqual(errors, [], errors)
        self.assertTrue(any("absolute path" in w for w in warnings), warnings)

    def test_file_url_companion_ref_in_temp_dir_errors(self):
        # CMH-VAL-16: a file:// companion ref BAKED into a temp directory that is NOT the
        # document's own folder is an ERROR - the OS reaps the temp dir and the shared
        # document silently loses its whole layer (the exact real-world failure).
        with tempfile.TemporaryDirectory() as docdir, tempfile.TemporaryDirectory() as tmpassets:
            urls = {}
            for ext in (".css", ".js", ".assets.js"):
                p = os.path.join(tmpassets, "commentable-html%s" % ext)
                with open(p, "w", encoding="utf-8") as fh:
                    fh.write("/* stub */")
                urls[ext] = Path(p).resolve().as_uri()
            html = (build_nonshareable()
                    .replace('href="commentable-html.css"', 'href="%s"' % urls[".css"])
                    .replace('src="commentable-html.js"', 'src="%s"' % urls[".js"])
                    .replace('src="commentable-html.assets.js"', 'src="%s"' % urls[".assets.js"]))
            doc = os.path.join(docdir, "doc.html")
            with open(doc, "w", encoding="utf-8", newline="") as fh:
                fh.write(html)
            errors, _ = validate.validate(doc)
        self.assertTrue(any("temporary directory" in e for e in errors),
                        "expected a temp-directory error, got: %r" % errors)

    def test_absolute_companion_path_in_temp_dir_errors(self):
        # CMH-VAL-16: a plain absolute path (not file://) into a temp directory other than
        # the document's folder is also an error, not merely the soft absolute-path warning.
        with tempfile.TemporaryDirectory() as docdir, tempfile.TemporaryDirectory() as tmpassets:
            paths = {}
            for ext in (".css", ".js", ".assets.js"):
                p = os.path.join(tmpassets, "commentable-html%s" % ext)
                with open(p, "w", encoding="utf-8") as fh:
                    fh.write("/* stub */")
                paths[ext] = p.replace("\\", "/")
            html = (build_nonshareable()
                    .replace('href="commentable-html.css"', 'href="%s"' % paths[".css"])
                    .replace('src="commentable-html.js"', 'src="%s"' % paths[".js"])
                    .replace('src="commentable-html.assets.js"', 'src="%s"' % paths[".assets.js"]))
            doc = os.path.join(docdir, "doc.html")
            with open(doc, "w", encoding="utf-8", newline="") as fh:
                fh.write(html)
            errors, _ = validate.validate(doc)
        self.assertTrue(any("temporary directory" in e for e in errors),
                        "expected a temp-directory error, got: %r" % errors)

    def test_project_tmp_folder_absolute_ref_is_not_temp_flagged(self):
        # CMH-VAL-16 false-positive guard: a durable project folder literally named "tmp"
        # (the "/tmp/" segment is NOT at the filesystem root) must never be treated as an OS
        # temp dir. Anchoring the fragment match to the root is what prevents this.
        durable = "file:///home/user/tmp/my_project/commentable-html.css"
        html = build_nonshareable().replace('href="commentable-html.css"', 'href="%s"' % durable)
        with tempfile.TemporaryDirectory() as docdir:
            doc = os.path.join(docdir, "doc.html")
            with open(doc, "w", encoding="utf-8", newline="") as fh:
                fh.write(html)
            errors, _ = validate.validate(doc)
        self.assertFalse(any("temporary directory" in e for e in errors),
                         "a durable project folder named 'tmp' must not be temp-flagged: %r" % errors)

    def test_cross_machine_mac_temp_fragment_errors(self):
        # CMH-VAL-16 cross-machine fallback: a file:// ref hard-coded into a macOS per-user temp
        # path (/private/var/folders/...) is flagged even on a non-mac validating machine (where
        # it never matches _temp_roots), because the anchored path fragment recognizes it.
        mac = "file:///private/var/folders/ab/cd/T/cmh-x/dist/commentable-html.css"
        html = build_nonshareable().replace('href="commentable-html.css"', 'href="%s"' % mac)
        with tempfile.TemporaryDirectory() as docdir:
            doc = os.path.join(docdir, "doc.html")
            with open(doc, "w", encoding="utf-8", newline="") as fh:
                fh.write(html)
            errors, _ = validate.validate(doc)
        self.assertTrue(any("temporary directory" in e for e in errors),
                        "a baked macOS temp path must be flagged cross-machine: %r" % errors)

    def test_temp_absolute_ref_errors_with_base_dir_none(self):
        # CMH-VAL-16 with deferred placement: base_dir=None still catches a baked absolute temp
        # companion ref, because an absolute path is broken regardless of the file's final home.
        with tempfile.TemporaryDirectory() as tmpassets:
            p = os.path.join(tmpassets, "commentable-html.css")
            with open(p, "w", encoding="utf-8") as fh:
                fh.write("/* stub */")
            url = Path(p).resolve().as_uri()
        html = build_nonshareable().replace('href="commentable-html.css"', 'href="%s"' % url)
        with tempfile.TemporaryDirectory() as docdir:
            doc = os.path.join(docdir, "doc.html")
            with open(doc, "w", encoding="utf-8", newline="") as fh:
                fh.write(html)
            errors, _ = validate.validate(doc, base_dir=None)
        self.assertTrue(any("temporary directory" in e for e in errors),
                        "base_dir=None must still catch a baked absolute temp ref: %r" % errors)

    def test_cross_machine_windows_temp_on_posix_form_errors(self):
        # CMH-VAL-16 cross-machine fallback: a Windows drive baked into a file:// path can appear
        # as "/C:/Windows/Temp/..." when validated on POSIX (url2pathname keeps the leading slash),
        # or as "<cwd>/C:/Windows/Temp/..." after os.path.abspath rewrites a bare drive ref on POSIX.
        # Both anchor at the drive-letter boundary and must be recognized as temp paths.
        from checks import resources as _r
        self.assertTrue(_r._is_temp_path("/C:/Windows/Temp/cmh/commentable-html.js"))
        self.assertTrue(_r._is_temp_path("/C:/Users/x/AppData/Local/Temp/cmh/commentable-html.js"))
        self.assertTrue(_r._is_temp_path("/home/runner/work/repo/C:/Windows/Temp/cmh/x.js"))
        self.assertTrue(_r._is_temp_path("/home/runner/work/repo/C:/Users/x/AppData/Local/Temp/cmh/x.js"))
        # Durable look-alikes (a "windows/temp" or "appdata/local/temp" segment NOT at a drive/user
        # root) must NOT be flagged.
        self.assertFalse(_r._is_temp_path("/C:/repo/windows/temp/commentable-html.js"))
        self.assertFalse(_r._is_temp_path("/D:/repo/appdata/local/temp/commentable-html.js"))
        self.assertFalse(_r._is_temp_path("/home/user/appdata/local/temp/commentable-html.js"))

    def test_relative_companion_ref_is_not_temp_flagged(self):
        # CMH-VAL-16 carve-out: a RELATIVE companion ref bakes no absolute location, so even
        # when the document itself is validated from a temp directory it is never temp-flagged
        # (the default hermetic test harness lives under the OS temp dir).
        errors, warnings = self._validate(build_nonshareable())
        self.assertFalse(any("temporary directory" in e for e in errors),
                         "relative refs must never be temp-flagged: %r" % errors)
        self.assertEqual(errors, [], errors)

    def test_beside_document_absolute_temp_path_is_not_temp_flagged(self):
        # CMH-VAL-16 carve-out: an absolute companion path that sits BESIDE the document (same
        # directory) keeps the existing absolute-path warning and is NOT escalated to a temp
        # error, even though the shared harness dir is under the OS temp root.
        with tempfile.TemporaryDirectory() as d:
            for ext in (".css", ".js", ".assets.js"):
                with open(os.path.join(d, "commentable-html%s" % ext), "w") as fh:
                    fh.write("/* stub */")
            css = os.path.join(d, "commentable-html.css").replace("\\", "/")
            html = build_nonshareable().replace('href="commentable-html.css"', 'href="%s"' % css)
            doc = os.path.join(d, "doc.html")
            with open(doc, "w", encoding="utf-8", newline="") as fh:
                fh.write(html)
            errors, warnings = validate.validate(doc)
        self.assertFalse(any("temporary directory" in e for e in errors),
                         "a beside-the-doc absolute path must not be temp-flagged: %r" % errors)
        self.assertTrue(any("absolute path" in w for w in warnings), warnings)

    def test_file_url_companion_refs_validate_clean(self):
        with tempfile.TemporaryDirectory() as d:
            urls = {}
            for ext in (".css", ".js", ".assets.js"):
                p = os.path.join(d, "commentable-html%s" % ext)
                with open(p, "w", encoding="utf-8") as fh:
                    fh.write("/* stub */")
                urls[ext] = Path(p).resolve().as_uri()
            html = (build_nonshareable()
                    .replace('href="commentable-html.css"', 'href="%s"' % urls[".css"])
                    .replace('src="commentable-html.js"', 'src="%s"' % urls[".js"])
                    .replace('src="commentable-html.assets.js"', 'src="%s"' % urls[".assets.js"]))
            p = os.path.join(d, "doc.html")
            with open(p, "w", encoding="utf-8", newline="") as fh:
                fh.write(html)
            errors, warnings = validate.validate(p)
        self.assertEqual(errors, [], errors)
        self.assertFalse(any("remote/CDN URL" in w or "absolute path" in w for w in warnings), warnings)

    def test_percent_encoded_file_host_resolves_like_localhost(self):
        # CMH-VAL-05: the URL parser PERCENT-DECODES a `file:` host and maps it through
        # domain-to-ASCII BEFORE the file-host state empties the exact string `localhost`, so
        # `file://local%68ost/x` is the same purely LOCAL reference as `file://localhost/x` (both
        # parse to href `file:///x`). Comparing the RAW netloc to the literal sent the encoded
        # spellings down the `//netloc+path` branch instead. A BACKSLASH ends the host in the
        # file-host state exactly as a `/` does, so that spelling is local too; the cased spellings
        # already worked and are controls.
        from checks import resources as _r
        plain = _r._file_url_to_path("file://localhost/dist/commentable-html.js")
        self.assertEqual(plain, _r._file_url_to_path("file:///dist/commentable-html.js"))
        for spelling in ("file://local%68ost/dist/commentable-html.js",
                         "file://LOCALHOST/dist/commentable-html.js",
                         "file://LOCAL%48OST/dist/commentable-html.js",
                         "file://%6Cocalhost/dist/commentable-html.js",
                         "file://%6c%6F%63%61%6c%68%6F%73%74/dist/commentable-html.js",
                         "file://localhost\\dist\\commentable-html.js",
                         "file://local%68ost\\dist\\commentable-html.js"):
            self.assertEqual(_r._file_url_to_path(spelling), plain,
                             "%s must resolve like file://localhost/..." % spelling)

    def test_trailing_dot_file_host_keeps_a_real_authority(self):
        # CMH-VAL-05 control: the file-host state special-cases the EXACT string `localhost`, and
        # `localhost.` is not it, so `file://localhost./x` keeps a NON-EMPTY host and really is the
        # SMB path `\\localhost.\x`. That is the call the egress predicate already makes
        # (the `_PCT_LOCALHOST` terminator `file_network_arm` builds), so decoding the host must not
        # fold the trailing-dot spelling - in any encoding - onto the local path.
        from checks import resources as _r
        local = _r._file_url_to_path("file://localhost/dist/commentable-html.js")
        for spelling in ("file://localhost./dist/commentable-html.js",
                         "file://local%68ost./dist/commentable-html.js",
                         "file://localhost%2E/dist/commentable-html.js",
                         "file://not-a-host/dist/commentable-html.js"):
            self.assertNotEqual(_r._file_url_to_path(spelling), local,
                                "%s carries a real authority" % spelling)

    def test_percent_encoded_localhost_companion_refs_validate_clean(self):
        # CMH-VAL-05 end to end: a companion ref whose host is spelled `local%68ost` points at a
        # file that is right there on disk, so it must validate exactly like the plain
        # `file://localhost/...` spelling instead of resolving to a bogus UNC path and reporting
        # "referenced companion file not found". This is an INTEGRATION control, and it bites on
        # POSIX only: a real temp path carries a Windows drive letter, and `nturl2path` drops any
        # host that precedes one, so the branch itself is pinned red-first by
        # `test_percent_encoded_file_host_resolves_like_localhost` above (drive-letter free, so it
        # fails on both platforms without the fix).
        with tempfile.TemporaryDirectory() as d:
            urls = {}
            for ext in (".css", ".js", ".assets.js"):
                p = os.path.join(d, "commentable-html%s" % ext)
                with open(p, "w", encoding="utf-8") as fh:
                    fh.write("/* stub */")
                urls[ext] = "file://local%68ost" + Path(p).resolve().as_uri()[len("file://"):]
            html = (build_nonshareable()
                    .replace('href="commentable-html.css"', 'href="%s"' % urls[".css"])
                    .replace('src="commentable-html.js"', 'src="%s"' % urls[".js"])
                    .replace('src="commentable-html.assets.js"', 'src="%s"' % urls[".assets.js"]))
            doc = os.path.join(d, "doc.html")
            with open(doc, "w", encoding="utf-8", newline="") as fh:
                fh.write(html)
            errors, warnings = validate.validate(doc)
        self.assertEqual(errors, [], errors)
        self.assertFalse(any("remote/CDN URL" in w or "absolute path" in w for w in warnings), warnings)

    def test_file_host_locality_agrees_with_the_egress_predicate(self):
        # CMH-VAL-05 parity, scoped to the LOCALHOST decision: this resolver and the egress
        # predicate (`is_network_url`) must read a `file:` host the same way, or a ref one side
        # calls purely local is resolved by the other as an off-machine authority. That is also
        # what settles the TRAILING DOT: the file-host state special-cases the exact string
        # `localhost`, so `file://localhost./x` keeps a real host on BOTH sides, while every
        # percent-encoded and cased spelling of `localhost` is local on both. A BACKSLASH host
        # terminator is carried because it is how the two last disagreed: the predicate reads the
        # value after the parser's input cleanup, so the resolver has to as well. The IDNA/UTS-46
        # spellings are carried too: neither side models UTS-46, so both read them as an
        # authority - the accepted over-detection `_PCT_LOCALHOST` records, pinned here so a
        # future edit cannot move one side alone. (The egress predicate's separate DRIVE-LETTER
        # exclusion and its `..`/empty-segment over-detection are deliberately outside this parity
        # claim; see `_file_host_is_local`.)
        from checks import resources as _r
        local = _r._file_url_to_path("file:///dist/commentable-html.js")
        for spelling in ("file://localhost/dist/commentable-html.js",
                         "file://local%68ost/dist/commentable-html.js",
                         "file://%6Cocalhost/dist/commentable-html.js",
                         "file://LOCALHOS%54/dist/commentable-html.js",
                         "file://localhost\\dist\\commentable-html.js",
                         "file://localhost./dist/commentable-html.js",
                         "file://localhost%2Fevil.example/dist/commentable-html.js",
                         "file://local%68ostx/dist/commentable-html.js",
                         "file://%EF%BD%8Cocalhost/dist/commentable-html.js",
                         "file://LOCALHO%C5%BFT/dist/commentable-html.js",
                         "file://local%C2%ADhost/dist/commentable-html.js",
                         "file://evil.example/dist/commentable-html.js",
                         "file://evil.example\\dist\\commentable-html.js"):
            self.assertEqual(_r._file_url_to_path(spelling) == local,
                             not _r.is_network_url(spelling),
                             "%s: the companion path resolver and the egress predicate disagree "
                             "about whether the host is this machine" % spelling)

    def test_trailing_dot_localhost_companion_ref_is_rejected_as_egress(self):
        # CMH-VAL-05 end-to-end control: because `localhost.` keeps a real authority, a companion
        # ref written that way is an SMB load off the machine, and the self-contained gate rejects
        # it - the trailing dot is never quietly folded onto the local file beside the document.
        with tempfile.TemporaryDirectory() as d:
            urls = {}
            for ext in (".css", ".js", ".assets.js"):
                p = os.path.join(d, "commentable-html%s" % ext)
                with open(p, "w", encoding="utf-8") as fh:
                    fh.write("/* stub */")
                urls[ext] = "file://localhost." + Path(p).resolve().as_uri()[len("file://"):]
            html = (build_nonshareable()
                    .replace('href="commentable-html.css"', 'href="%s"' % urls[".css"])
                    .replace('src="commentable-html.js"', 'src="%s"' % urls[".js"])
                    .replace('src="commentable-html.assets.js"', 'src="%s"' % urls[".assets.js"]))
            doc = os.path.join(d, "doc.html")
            with open(doc, "w", encoding="utf-8", newline="") as fh:
                fh.write(html)
            errors, _ = validate.validate(doc)
        self.assertTrue(any("loads over the network" in e for e in errors),
                        "a trailing-dot host is an authority, not the local file: %r" % errors)

    def test_companion_parent_relative_ref_ok(self):
        # NonShareable may point at the skill dist/ folder via a ../ path; if the target
        # resolves to an existing file it is valid (no "escapes the folder" error).
        with tempfile.TemporaryDirectory() as d:
            sub = os.path.join(d, "reports")
            os.makedirs(sub)
            for ext in (".css", ".js", ".assets.js"):
                with open(os.path.join(d, "commentable-html%s" % ext), "w") as fh:
                    fh.write("/* stub */")
            html = (build_nonshareable()
                    .replace('href="commentable-html.css"',
                             'href="../commentable-html.css"')
                    .replace('src="commentable-html.js"',
                             'src="../commentable-html.js"')
                    .replace('src="commentable-html.assets.js"',
                             'src="../commentable-html.assets.js"'))
            p = os.path.join(sub, "doc.html")
            with open(p, "w", encoding="utf-8", newline="") as fh:
                fh.write(html)
            errors, warnings = validate.validate(p)
        self.assertEqual(errors, [], errors)

    def test_companion_in_subfolder_ok(self):
        # A subdirectory reference (e.g. the skill's dist/) is the intended nonshareable
        # workflow, so it is valid as long as the file exists at the resolved path.
        with tempfile.TemporaryDirectory() as d:
            dist = os.path.join(d, "dist")
            os.makedirs(dist)
            for ext in (".css", ".js", ".assets.js"):
                with open(os.path.join(dist, "commentable-html%s" % ext), "w") as fh:
                    fh.write("/* stub */")
            html = (build_nonshareable()
                    .replace('href="commentable-html.css"',
                             'href="dist/commentable-html.css"')
                    .replace('src="commentable-html.js"',
                             'src="dist/commentable-html.js"')
                    .replace('src="commentable-html.assets.js"',
                             'src="dist/commentable-html.assets.js"'))
            p = os.path.join(d, "doc.html")
            with open(p, "w", encoding="utf-8", newline="") as fh:
                fh.write(html)
            errors, warnings = validate.validate(p)
        self.assertEqual(errors, [], errors)

    def test_remote_companion_url_errors(self):
        html = build_nonshareable().replace(
            'href="commentable-html.css"',
            'href="https://cdn.example.com/commentable-html.css"')
        self.assertNonShareableError(html, "remote/CDN URL")

    def test_protocol_relative_companion_url_errors(self):
        html = build_nonshareable().replace(
            'href="commentable-html.css"',
            'href="//cdn.example.com/commentable-html.css"')
        self.assertNonShareableError(html, "remote/CDN URL")

    def test_non_file_scheme_companion_ref_errors(self):
        html = build_nonshareable().replace(
            'src="commentable-html.js"',
            'src="vscode://extension/commentable-html.js"')
        self.assertNonShareableError(html, "non-file URL scheme")

    # `file:` refs that name no path at all: an IPv6 literal, a host:port and its `|` spelling (the
    # same drive delimiter to `nturl2path`), and the bracketed authorities `urlsplit` ITSELF
    # rejects - those raise on every platform, unlike the Windows-only `url2pathname` raise.
    _MALFORMED_FILE_HOST_REFS = ("file://[::1]/dist/commentable-html.css",
                                 "file://host:8080/dist/commentable-html.css",
                                 "file://host|8080/dist/commentable-html.css",
                                 "file://host%7C8080/dist/commentable-html.css",
                                 "file://[foo]/dist/commentable-html.css",
                                 "file://[127.0.0.1]/dist/commentable-html.css",
                                 "file://[::1/dist/commentable-html.css",
                                 "file://host]/dist/commentable-html.css",
                                 "file://c:evil:80/dist/commentable-html.css",
                                 "file:////host:8080/dist/commentable-html.css",
                                 "file:////host%7C8080/dist/commentable-html.css")

    # `file:` refs whose PATH - not host - is a shape the platform resolver rejects. Their verdict
    # is legitimately platform-specific (`nturl2path` rejects them, the POSIX resolver hands the
    # string back), so what is pinned for these is crash-safety, not parity.
    _RESOLVER_REJECTED_PATH_REFS = ("file::/dist/commentable-html.css",
                                    "file:|dist/commentable-html.css",
                                    "file:/:/commentable-html.css",
                                    "file:///C:/dir/a:b/commentable-html.css")

    def _malformed_file_host_doc(self, spelling):
        return build_nonshareable().replace('href="commentable-html.css"',
                                            'href="%s"' % spelling)

    def test_malformed_file_host_companion_ref_reports_a_finding(self):
        # CMH-VAL-05: `nturl2path.url2pathname` RAISES ("Bad URL: //[||1]/dist/...") on an authority
        # it cannot map to a UNC path, and `urlsplit` raises on a bracketed authority it refuses to
        # parse at all, and nothing caught either, so a companion ref spelled
        # `file://[::1]/dist/commentable-html.css` killed `validate()` with a raw traceback. Every
        # fail-closed caller (`retrofit.py`, `content_replace.py`, `chart_block.py`,
        # `finalize.py`) then saw a traceback instead of a finding, and a validator that crashes on
        # hostile or merely odd input is strictly worse than one that reports the problem. The
        # finding has to name the REAL problem - the ref resolves to no local file - so resolving
        # to `None` instead is not the fix: that falls through to the "non-file URL scheme" branch
        # and blames the scheme, which is the one part of the ref that is right.
        for spelling in self._MALFORMED_FILE_HOST_REFS:
            errors, _ = self._validate(self._malformed_file_host_doc(spelling))
            self.assertTrue(any("does not resolve to a local file path" in e for e in errors),
                            "%s: expected a local-file finding, got: %r" % (spelling, errors))
            self.assertFalse(any("non-file URL scheme" in e for e in errors),
                             "%s: the scheme IS `file:` - what follows it is what cannot be "
                             "resolved: %r" % (spelling, errors))

    def test_malformed_file_host_verdict_does_not_depend_on_the_platform_resolver(self):
        # CMH-VAL-05: the pinned claim is the SHARED verdict, not one platform's exception.
        # `url2pathname` is platform-specific - the Windows implementation raises on these
        # authorities while the POSIX one hands the string straight back - so the resolver must
        # settle these shapes ITSELF rather than letting the platform decide. All three
        # implementations below (the native one, a POSIX stand-in, and one that raises on
        # everything) must therefore reach exactly the same errors and warnings. The residual
        # try/except that survives a RAISING resolver is pinned separately by
        # `test_a_raising_path_resolver_becomes_a_finding_too`, because these refs are settled
        # before `url2pathname` is reached at all - which is the point of this test.
        from unittest import mock
        from urllib.parse import unquote
        from checks import resources as _r

        def _raises(url):
            raise OSError("Bad URL: " + url)

        for spelling in self._MALFORMED_FILE_HOST_REFS:
            html = self._malformed_file_host_doc(spelling)
            native = self._validate(html)
            for name, impl in (("posix", unquote), ("raising", _raises)):
                with mock.patch.object(_r, "url2pathname", impl):
                    self.assertEqual(self._validate(html), native,
                                     "%s: the %s resolver must reach the same verdict as the "
                                     "native one" % (spelling, name))

    def test_a_raising_path_resolver_becomes_a_finding_too(self):
        # CMH-VAL-05: the screened host shapes never reach `url2pathname`, so the residual
        # try/except - the half of the guarantee that covers everything a host test cannot see -
        # needs its own pin, or deleting it would leave every other test green. It is not
        # defensive-only: `nturl2path` rejects PATH shapes too (`file:///C:/dir/a:b/x.css` carries
        # two drive delimiters), and this asserts the resolver is genuinely REACHED so the test
        # cannot rot into another screened case.
        from unittest import mock
        from checks import resources as _r
        calls = []

        def _raises(url):
            calls.append(url)
            raise OSError("Bad URL: " + url)

        html = self._malformed_file_host_doc("file://server/share/commentable-html.css")
        with mock.patch.object(_r, "url2pathname", _raises):
            errors, _ = self._validate(html)
        self.assertTrue(calls, "the patched resolver must actually be reached")
        self.assertTrue(any("does not resolve to a local file path" in e for e in errors),
                        "a raising resolver must become a finding, not a traceback: %r" % errors)

    def test_a_resolver_rejected_path_shape_is_a_finding_not_a_traceback(self):
        # CMH-VAL-05: the companion refs above are settled before `url2pathname` is reached and the
        # test above reaches it only through a MOCK, so neither drives the REAL resolver into a
        # rejection - and the real one rejects a path shape with more than one exception type.
        # `nturl2path` raises `OSError('Bad URL')` for `/C:/dir/a:b/x.css` but `IndexError` when the
        # drive delimiter LEADS the path (`file::/x`, `file:|x`, where it indexes an empty first
        # component), which is why the residual catch is by outcome and not an enumerated tuple.
        # Only the VERDICT CLASS is shared here: the POSIX resolver accepts these strings and
        # reports a missing companion instead, so what every platform owes is a finding rather than
        # a traceback (the first two spellings are red on Windows without the catch).
        for spelling in self._RESOLVER_REJECTED_PATH_REFS:
            errors, _ = self._validate(self._malformed_file_host_doc(spelling))
            self.assertTrue(any(spelling in e for e in errors),
                            "%s: expected a finding naming the ref, got: %r" % (spelling, errors))

    def test_an_unparseable_non_file_ref_still_reports_the_scheme(self):
        # CMH-VAL-05 control for the other half of the parse guard: a ref the URL parser REFUSES is
        # only unresolvable when it is a `file:` URL. `vscode://[foo]/x` is refused for the same
        # bracket reason, but its problem really is the scheme, so it must keep the scheme finding
        # rather than inherit the new one - without this, collapsing the guard to always return the
        # sentinel would leave every other test green. The PADDED spellings carry the other half of
        # the claim: the resolver reads the ref the way the URL parser does (leading C0-or-space
        # stripped), so the caller's ANCHORED classification regexes have to read the same value or
        # the parser's own padding hides the scheme from them and a remote or wrong-scheme
        # companion is quietly resolved as a relative path instead.
        from checks import resources as _r
        for ref in ("vscode://[foo]/commentable-html.js",
                    " vscode://[foo]/commentable-html.js",
                    "\tvscode://extension/commentable-html.js"):
            self.assertIsNone(_r._file_url_to_path(ref), ref)
            html = build_nonshareable().replace('src="commentable-html.js"', 'src="%s"' % ref)
            errors, _ = self._validate(html)
            self.assertTrue(any("non-file URL scheme" in e for e in errors),
                            "%r: %r" % (ref, errors))
            self.assertFalse(any("does not resolve to a local file path" in e for e in errors),
                             "%r: %r" % (ref, errors))
        html = build_nonshareable().replace('href="commentable-html.css"',
                                            'href=" https://cdn.example.com/commentable-html.css"')
        errors, _ = self._validate(html)
        self.assertTrue(any("remote/CDN URL" in e for e in errors),
                        "a padded remote URL is still remote: %r" % errors)

    def test_malformed_file_url_resolves_to_the_unresolvable_sentinel(self):
        # CMH-VAL-05 unit control: the resolver distinguishes "not a `file:` URL at all" (None,
        # which the caller reads as a scheme problem) from "a `file:` URL that names no local
        # path" (the sentinel). A well-formed host still resolves to a path, so the sentinel does
        # not swallow the ordinary UNC/local spellings - and a Windows DRIVE-LETTER authority is
        # exempt in every spelling the URL parser reads as a drive, including the separatorless
        # `file://c:evil.example/x` the egress predicate also calls local, so this does not quietly
        # widen what the validator rejects.
        from checks import resources as _r
        for spelling in self._MALFORMED_FILE_HOST_REFS:
            self.assertIs(_r._file_url_to_path(spelling), _r._UNRESOLVABLE_FILE_URL, spelling)
        self.assertIsNone(_r._file_url_to_path("vscode://extension/commentable-html.js"))
        for spelling in ("file:///dist/commentable-html.js",
                         "file://localhost/dist/commentable-html.js",
                         "file://server/share/commentable-html.js",
                         "file://C:/dist/commentable-html.js",
                         "file://C|/dist/commentable-html.js",
                         "file://c:evil.example/dist/commentable-html.js"):
            self.assertIsInstance(_r._file_url_to_path(spelling), str, spelling)

    def test_nonshareable_demo_key_survivor_is_flagged(self):
        # The real nonshareable template (nonshareable demo key + nonshareable demo title) is clean,
        # but changing only the title while keeping the demo key is a survived retrofit.
        eco = os.path.join(ROOT, "dist", "NONSHAREABLE.html")
        with open(eco, encoding="utf-8") as fh:
            html = fh.read()
        mutated = html.replace("<title>Commentable HTML - NonShareable Demo</title>",
                               "<title>My Real NonShareable Doc</title>")
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "NONSHAREABLE.html")
            with open(p, "w", encoding="utf-8", newline="") as fh:
                fh.write(mutated)
            for c in ("css", "js", "assets"):
                ext = {"css": ".css", "js": ".js", "assets": ".assets.js"}[c]
                with open(os.path.join(d, "commentable-html%s" % ext), "w", encoding="utf-8") as fh:
                    fh.write("/* stub */")
            errors, _ = validate.validate(p)
        self.assertTrue(any("demo content root survived" in e for e in errors), errors)

class NonShareableBaseDirTests(unittest.TestCase):
    """CMH-VAL-05: the optional base_dir controls how companion refs are resolved."""

    def _write(self, d, content):
        p = os.path.join(d, "doc.html")
        with open(p, "w", encoding="utf-8", newline="") as fh:
            fh.write(content)
        return p

    def test_base_dir_none_skips_existence_check(self):
        # Companions are MISSING on disk. The default base_dir (the file's dir) flags
        # them; base_dir=None defers the existence check (placement not yet done).
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d, build_nonshareable())
            errors_default, _ = validate.validate(p)
            errors_none, _ = validate.validate(p, base_dir=None)
        self.assertTrue(any("not found" in e for e in errors_default),
                        "default base_dir should flag missing companions: %r" % errors_default)
        self.assertFalse(any("not found" in e for e in errors_none),
                         "base_dir=None should skip the existence check: %r" % errors_none)

    def test_base_dir_none_still_runs_structural_checks(self):
        # A remote companion URL is a structural error that must fire even when the
        # existence check is deferred with base_dir=None.
        content = build_nonshareable().replace('href="commentable-html.css"',
                                               'href="https://cdn.example.com/commentable-html.css"')
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d, content)
            errors, _ = validate.validate(p, base_dir=None)
        self.assertTrue(any("remote/CDN URL" in e for e in errors),
                        "remote-URL check must run with base_dir=None: %r" % errors)

    def test_explicit_base_dir_resolves_against_that_dir(self):
        # The document lives in dir A (no companions); companions live in dir B.
        # base_dir=B resolves the refs there and validates clean.
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            p = self._write(a, build_nonshareable())
            for name in ("commentable-html.css", "commentable-html.js", "commentable-html.assets.js"):
                with open(os.path.join(b, name), "w", encoding="utf-8") as fh:
                    fh.write("/* stub */")
            errors_a, _ = validate.validate(p)
            errors_b, _ = validate.validate(p, base_dir=b)
        self.assertTrue(any("not found" in e for e in errors_a),
                        "refs should be missing when resolved against the file's own dir")
        self.assertFalse(any("not found" in e for e in errors_b),
                         "refs should resolve against the explicit base_dir: %r" % errors_b)


if __name__ == "__main__":
    unittest.main()
