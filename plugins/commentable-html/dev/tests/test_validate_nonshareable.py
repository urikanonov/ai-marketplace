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

    def test_nonshareable_document_without_offline_chart_snapshots_is_clean(self):
        # Control: the rule fires on the SNAPSHOT, not on the nonshareable classification, so an
        # ordinary companion-file document stays clean.
        errors, warnings = self._validate(build_nonshareable())
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
        self.assertTrue(os.path.exists(eco), "dist/NONSHAREABLE.html not found - run python tools/build.py")
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
