from _validate_helpers import *


class NonPortableTests(unittest.TestCase):
    """Dual-mode validation: the nonportable branch and its guardrails."""

    def _validate(self, content, companions=("css", "js", "assets"), version=NONPORTABLE_VERSION):
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

    def assertNonPortableError(self, content, needle, **kw):
        errors, _ = self._validate(content, **kw)
        self.assertTrue(any(needle in e for e in errors),
                        "expected an error containing %r, got: %r" % (needle, errors))

    def assertNonPortableWarn(self, content, needle, **kw):
        errors, warnings = self._validate(content, **kw)
        self.assertEqual(errors, [], "expected no errors, got: %r" % errors)
        self.assertTrue(any(needle in w for w in warnings),
                        "expected a warning containing %r, got: %r" % (needle, warnings))

    # -- positive controls -------------------------------------------------- #
    def test_minimal_nonportable_is_clean(self):
        errors, warnings = self._validate(build_nonportable())
        self.assertEqual(errors, [], "nonportable errors: %r" % errors)
        self.assertEqual(warnings, [], "nonportable warnings: %r" % warnings)

    def test_nonportable_document_rejects_offline_mode(self):
        html = build_nonportable().replace('"mode":"nonportable"', '"mode":"offline"', 1)
        self.assertNonPortableError(html, 'commentableHtmlLayer.mode must be "nonportable"')

    def test_real_nonportable_template_is_clean(self):
        eco = os.path.join(ROOT, "dist", "NONPORTABLE.html")
        self.assertTrue(os.path.exists(eco), "dist/NONPORTABLE.html not found - run python tools/build.py")
        errors, warnings = validate.validate(eco)
        self.assertEqual(errors, [], "dist/NONPORTABLE.html errors: %r" % errors)
        self.assertEqual(warnings, [], "dist/NONPORTABLE.html warnings: %r" % warnings)

    def test_is_nonportable_detection(self):
        self.assertTrue(validate._is_nonportable(build_nonportable()))
        self.assertFalse(validate._is_nonportable(build()))

    def test_nonportable_detection_ignores_attribute_substrings(self):
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
        self.assertFalse(validate._is_nonportable(decoy))

    def test_nonportable_detection_accepts_unquoted_and_reordered_attrs(self):
        # Unquoted href/src and a reordered <meta content=.. name=..> are valid
        # HTML that the browser loads, so nonportable detection must recognize them.
        v = NONPORTABLE_VERSION
        unquoted = (
            "<!DOCTYPE html>\n<html><head>\n"
            "<link rel=stylesheet href=commentable-html.css>\n"
            "<script src=commentable-html.js></script>\n"
            "</head><body>\n"
            + "\n".join([HANDLED_REGION, EMBEDDED_REGION, comment_ui(), MAIN])
            + "\n</body></html>\n")
        self.assertTrue(validate._is_nonportable(unquoted))
        self.assertEqual(validate._nonportable_css_refs(unquoted), ["commentable-html.css"])
        # Reordered meta (content before name) is still read for the version.
        reordered = '<meta content="%s" name="commentable-html-version">' % v
        self.assertEqual(validate._nonportable_meta_versions(reordered), [v])

    def test_nonportable_detection_is_case_insensitive(self):
        # The "commentable-html" substring and the extension are matched
        # case-insensitively, so a mixed-case companion reference is still detected.
        v = NONPORTABLE_VERSION
        mixed = (
            "<!DOCTYPE html>\n<html><head>\n"
            '<link rel="stylesheet" href="Commentable-HTML.CSS">\n'
            '<script src="Commentable-HTML.JS"></script>\n'
            "</head><body>\n"
            + "\n".join([HANDLED_REGION, EMBEDDED_REGION, comment_ui(), MAIN])
            + "\n</body></html>\n")
        self.assertTrue(validate._is_nonportable(mixed))
        self.assertEqual(validate._nonportable_css_refs(mixed), ["Commentable-HTML.CSS"])
        self.assertEqual(validate._nonportable_js_refs(mixed), ["Commentable-HTML.JS"])

    def test_nonportable_detection_ignores_gt_in_value_and_decoys(self):
        # The HTMLParser-based scan must (a) not be fooled by a '>' inside a quoted
        # attribute value, and (b) ignore link/script tags that only appear inside an
        # HTML comment or a <script>/<style> body (CDATA), which a naive regex matched.
        v = NONPORTABLE_VERSION
        gt_in_value = '<link rel="stylesheet" title="a>b" href="commentable-html.css">'
        self.assertEqual(validate._nonportable_css_refs(gt_in_value), ["commentable-html.css"])
        commented = '<!-- <link rel="stylesheet" href="commentable-html.css"> -->'
        self.assertEqual(validate._nonportable_css_refs(commented), [])
        in_script = '<script>var s = "<link href=\'commentable-html.css\'>";</script>'
        self.assertEqual(validate._nonportable_css_refs(in_script), [])

    def test_nonportable_detection_accepts_cache_busted_refs(self):
        # A ?query / #fragment cache-buster is stripped by the browser before it
        # fetches the file, so detection and the on-disk check must ignore it too.
        busted = (
            '<link rel="stylesheet" href="commentable-html.css?v=1.7.0">'
            '<script src="commentable-html.js#build9"></script>'
            '<script src="commentable-html.assets.js?v=1.7.0"></script>')
        self.assertEqual(validate._nonportable_css_refs(busted), ["commentable-html.css"])
        self.assertEqual(validate._nonportable_js_refs(busted),
                         ["commentable-html.js", "commentable-html.assets.js"])

    def test_cache_busted_companion_refs_validate_clean(self):
        doc = (build_nonportable()
               .replace('href="commentable-html.css"', 'href="commentable-html.css?v=1.7.0"')
               .replace('src="commentable-html.assets.js"', 'src="commentable-html.assets.js?v=1.7.0"')
               .replace('src="commentable-html.js"', 'src="commentable-html.js?v=1.7.0"'))
        errors, warnings = self._validate(doc)
        self.assertEqual(errors, [], "cache-busted refs should validate clean: %r" % errors)
        self.assertEqual(warnings, [], "cache-busted refs should not warn: %r" % warnings)


    def test_missing_stylesheet_link_errors(self):
        self.assertNonPortableError(build_nonportable(link=False), "no commentable-html stylesheet")

    def test_missing_runtime_script_errors(self):
        self.assertNonPortableError(build_nonportable(runtime=False), "no commentable-html runtime")

    def test_missing_assets_js_warns(self):
        self.assertNonPortableWarn(build_nonportable(assets=False), "Export with embedded comments", companions=("css", "js"))

    def test_missing_version_meta_warns(self):
        self.assertNonPortableWarn(build_nonportable(meta=False), 'missing <meta name="commentable-html-version"')

    def test_version_meta_does_not_compare_to_versionless_filenames(self):
        html = build_nonportable(version="9.9.9")
        errors, warnings = self._validate(html)
        self.assertEqual(errors, [])
        self.assertFalse(any("must match" in w for w in warnings), warnings)

    def test_missing_banner_errors(self):
        self.assertNonPortableError(build_nonportable(banner=False), "#cmhAssetBanner")

    def test_missing_watchdog_warns(self):
        self.assertNonPortableWarn(build_nonportable(watchdog=False), "bootstrap watchdog")

    def test_missing_companion_file_errors(self):
        # HTML references the runtime but the .js file is absent on disk.
        self.assertNonPortableError(build_nonportable(), "companion file not found", companions=("css", "assets"))

    def test_nonportable_state_regions_still_validated(self):
        # Dropping the inline HANDLED IDS region must still fail in nonportable mode.
        html = build_nonportable().replace(HANDLED_REGION, "")
        self.assertNonPortableError(html, "handledCommentIds")

    def test_nonportable_uses_marker_wrapped_companion_regions(self):
        html = build_nonportable()
        self.assertIn("BEGIN: commentable-html - CSS", html)
        self.assertIn("BEGIN: commentable-html - JS", html)

    def test_absolute_companion_path_warns(self):
        # An absolute path is usable but leaks a local directory - warn, do not error.
        with tempfile.TemporaryDirectory() as d:
            css = os.path.join(d, "commentable-html.css")
            for c, ext in (("css", ".css"), ("js", ".js"), ("assets", ".assets.js")):
                with open(os.path.join(d, "commentable-html%s" % ext), "w") as fh:
                    fh.write("/* stub */")
            html = build_nonportable().replace(
                'href="commentable-html.css"',
                'href="%s"' % css.replace("\\", "/"))
            p = os.path.join(d, "doc.html")
            with open(p, "w", encoding="utf-8", newline="") as fh:
                fh.write(html)
            errors, warnings = validate.validate(p)
        self.assertEqual(errors, [], errors)
        self.assertTrue(any("absolute path" in w for w in warnings), warnings)

    def test_file_url_companion_refs_validate_clean(self):
        with tempfile.TemporaryDirectory() as d:
            urls = {}
            for ext in (".css", ".js", ".assets.js"):
                p = os.path.join(d, "commentable-html%s" % ext)
                with open(p, "w", encoding="utf-8") as fh:
                    fh.write("/* stub */")
                urls[ext] = Path(p).resolve().as_uri()
            html = (build_nonportable()
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
        # NonPortable may point at the skill dist/ folder via a ../ path; if the target
        # resolves to an existing file it is valid (no "escapes the folder" error).
        with tempfile.TemporaryDirectory() as d:
            sub = os.path.join(d, "reports")
            os.makedirs(sub)
            for ext in (".css", ".js", ".assets.js"):
                with open(os.path.join(d, "commentable-html%s" % ext), "w") as fh:
                    fh.write("/* stub */")
            html = (build_nonportable()
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
        # A subdirectory reference (e.g. the skill's dist/) is the intended nonportable
        # workflow, so it is valid as long as the file exists at the resolved path.
        with tempfile.TemporaryDirectory() as d:
            dist = os.path.join(d, "dist")
            os.makedirs(dist)
            for ext in (".css", ".js", ".assets.js"):
                with open(os.path.join(dist, "commentable-html%s" % ext), "w") as fh:
                    fh.write("/* stub */")
            html = (build_nonportable()
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
        html = build_nonportable().replace(
            'href="commentable-html.css"',
            'href="https://cdn.example.com/commentable-html.css"')
        self.assertNonPortableError(html, "remote/CDN URL")

    def test_protocol_relative_companion_url_errors(self):
        html = build_nonportable().replace(
            'href="commentable-html.css"',
            'href="//cdn.example.com/commentable-html.css"')
        self.assertNonPortableError(html, "remote/CDN URL")

    def test_non_file_scheme_companion_ref_errors(self):
        html = build_nonportable().replace(
            'src="commentable-html.js"',
            'src="vscode://extension/commentable-html.js"')
        self.assertNonPortableError(html, "non-file URL scheme")

    def test_nonportable_demo_key_survivor_is_flagged(self):
        # The real nonportable template (nonportable demo key + nonportable demo title) is clean,
        # but changing only the title while keeping the demo key is a survived retrofit.
        eco = os.path.join(ROOT, "dist", "NONPORTABLE.html")
        with open(eco, encoding="utf-8") as fh:
            html = fh.read()
        mutated = html.replace("<title>Commentable HTML - NonPortable Demo</title>",
                               "<title>My Real NonPortable Doc</title>")
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "NONPORTABLE.html")
            with open(p, "w", encoding="utf-8", newline="") as fh:
                fh.write(mutated)
            for c in ("css", "js", "assets"):
                ext = {"css": ".css", "js": ".js", "assets": ".assets.js"}[c]
                with open(os.path.join(d, "commentable-html%s" % ext), "w", encoding="utf-8") as fh:
                    fh.write("/* stub */")
            errors, _ = validate.validate(p)
        self.assertTrue(any("demo content root survived" in e for e in errors), errors)

class NonPortableBaseDirTests(unittest.TestCase):
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
            p = self._write(d, build_nonportable())
            errors_default, _ = validate.validate(p)
            errors_none, _ = validate.validate(p, base_dir=None)
        self.assertTrue(any("not found" in e for e in errors_default),
                        "default base_dir should flag missing companions: %r" % errors_default)
        self.assertFalse(any("not found" in e for e in errors_none),
                         "base_dir=None should skip the existence check: %r" % errors_none)

    def test_base_dir_none_still_runs_structural_checks(self):
        # A remote companion URL is a structural error that must fire even when the
        # existence check is deferred with base_dir=None.
        content = build_nonportable().replace('href="commentable-html.css"',
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
            p = self._write(a, build_nonportable())
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
