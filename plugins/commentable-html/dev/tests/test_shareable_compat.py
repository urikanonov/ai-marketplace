#!/usr/bin/env python3
"""Back-compat guarantees for the Portable -> Shareable rename (CMH-PORT-05..09).

Every document produced BEFORE the rename carries the legacy spellings: a layer descriptor whose
`mode` is the pre-rename value, a companion bootstrap anchor named after the old concept, dist
templates named after it, matching CLI flags, and the old migration-tool filename. Those documents
and scripts must keep working unchanged and keep validating with no new error and no new warning,
so each renamed identifier is pinned here against its legacy spelling.

The legacy spellings are assembled from fragments rather than written literally, so a future
sweeping rename cannot silently rewrite the very strings this suite exists to pin.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import _paths  # noqa: E402
from _validate_helpers import (  # noqa: E402
    EXPECTED_REGIONS, FAVICON_LINK, HANDLED_REGION, EMBEDDED_REGION, MAIN,
    build, build_nonshareable, comment_ui,
)

sys.path.insert(0, _paths.TOOLS)
import validate  # noqa: E402
import _toolpath  # noqa: E402

AUTHORING = os.path.join(_paths.TOOLS, "authoring")

# The pre-rename vocabulary, assembled so no textual sweep can rewrite it here.
_OLD = "PORT" + "ABLE"
_OLD_LOWER = _OLD.lower()
LEGACY_MODE_SHAREABLE = _OLD_LOWER                      # the old single-file mode value
LEGACY_MODE_NONSHAREABLE = "non" + _OLD_LOWER           # the old companion mode value
LEGACY_BOOTSTRAP_BEGIN = "<!-- BEGIN: commentable-html - NON%s BOOTSTRAP -->" % _OLD
LEGACY_BOOTSTRAP_END = "<!-- END: commentable-html - NON%s BOOTSTRAP -->" % _OLD
LEGACY_TEMPLATE = _OLD + ".html"
LEGACY_NONSHAREABLE_TEMPLATE = "NON" + _OLD + ".html"
LEGACY_TOOL = "to_" + _OLD_LOWER + ".py"
LEGACY_FLAG = "--" + _OLD_LOWER
LEGACY_NONSHAREABLE_FLAG = "--non" + _OLD_LOWER
LEGACY_BODY_CLASS = "cm-non" + _OLD_LOWER
LEGACY_ONLY_CLASS = "cm-non" + _OLD_LOWER + "-only"
LEGACY_FILENAME_SUFFIX = "-" + _OLD_LOWER


def _legacy_bootstrap():
    return (LEGACY_BOOTSTRAP_BEGIN + "\n"
            '<div id="cmhAssetBanner" class="cm-skip" role="alert" hidden>missing</div>\n'
            "<script>window.setTimeout(function () { "
            "if (!window.__commentableHtmlReady) {} }, 3000);</script>\n"
            + LEGACY_BOOTSTRAP_END)


def _legacy_companion_document(version="1.0.0"):
    """A companion-mode document exactly as a pre-rename release emitted it: the legacy
    descriptor mode AND the legacy bootstrap anchor."""
    head = [
        '<script type="application/json" id="commentableHtmlLayer">%s</script>'
        % json.dumps({"version": version, "mode": LEGACY_MODE_NONSHAREABLE,
                      "regions": EXPECTED_REGIONS}, separators=(",", ":")),
        FAVICON_LINK,
        "<style>\n:root { --cp-bg: #fff; --cp-text: #000; }\n</style>",
        "<!--\nBEGIN: commentable-html - CSS\n-->\n"
        '<link rel="stylesheet" href="commentable-html.css">\n'
        "<!-- END: commentable-html - CSS -->",
        '<meta name="commentable-html-version" content="%s">' % version,
        '<meta name="commentable-html-kind" content="generic">',
    ]
    body = [
        _legacy_bootstrap(), HANDLED_REGION, EMBEDDED_REGION, comment_ui(), MAIN,
        "<!--\nBEGIN: commentable-html - JS\n-->\n"
        '<script src="commentable-html.assets.js"></script>\n'
        '<script src="commentable-html.js"></script>\n'
        "<!-- END: commentable-html - JS -->",
    ]
    return ('<!DOCTYPE html>\n<html lang="en">\n<head>\n'
            + "\n".join(head)
            + "\n</head>\n<body>\n"
            + "\n".join(body)
            + "\n</body>\n</html>\n")


def _validate_with_companions(content):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "doc.html")
        with open(p, "w", encoding="utf-8", newline="") as fh:
            fh.write(content)
        for ext in (".css", ".js", ".assets.js"):
            with open(os.path.join(d, "commentable-html" + ext), "w", encoding="utf-8") as fh:
                fh.write("/* stub */")
        return validate.validate(p)


def _validate_text(content):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "doc.html")
        with open(p, "w", encoding="utf-8", newline="") as fh:
            fh.write(content)
        return validate.validate(p)


class LegacyDescriptorModeTests(unittest.TestCase):
    """CMH-PORT-06: the pre-rename descriptor mode values stay valid, forever."""

    def test_legacy_single_file_mode_validates_clean(self):
        doc = build().replace('"mode":"shareable"', '"mode":"%s"' % LEGACY_MODE_SHAREABLE, 1)
        self.assertIn('"mode":"%s"' % LEGACY_MODE_SHAREABLE, doc)
        errors, warnings = _validate_text(doc)
        self.assertEqual(errors, [], "legacy single-file mode errors: %r" % errors)
        self.assertEqual(warnings, [], "legacy single-file mode warnings: %r" % warnings)

    def test_new_shareable_mode_validates_clean(self):
        doc = build()
        self.assertIn('"mode":"shareable"', doc)
        errors, warnings = _validate_text(doc)
        self.assertEqual(errors, [], "shareable-mode errors: %r" % errors)
        self.assertEqual(warnings, [], "shareable-mode warnings: %r" % warnings)

    def test_legacy_companion_mode_and_anchor_validate_clean(self):
        errors, warnings = _validate_with_companions(_legacy_companion_document())
        self.assertEqual(errors, [], "legacy companion errors: %r" % errors)
        self.assertEqual(warnings, [], "legacy companion warnings: %r" % warnings)

    def test_new_nonshareable_mode_validates_clean(self):
        doc = build_nonshareable()
        self.assertIn('"mode":"nonshareable"', doc)
        errors, warnings = _validate_with_companions(doc)
        self.assertEqual(errors, [], "nonshareable errors: %r" % errors)
        self.assertEqual(warnings, [], "nonshareable warnings: %r" % warnings)

    def test_a_single_file_document_still_rejects_a_companion_mode(self):
        doc = build().replace('"mode":"shareable"', '"mode":"nonshareable"', 1)
        errors, _ = _validate_text(doc)
        self.assertTrue(any("commentableHtmlLayer.mode" in e for e in errors),
                        "expected a descriptor-mode error, got: %r" % errors)

    def test_an_unknown_mode_is_still_rejected(self):
        doc = build().replace('"mode":"shareable"', '"mode":"movable"', 1)
        errors, _ = _validate_text(doc)
        self.assertTrue(any("commentableHtmlLayer.mode" in e for e in errors),
                        "expected a descriptor-mode error, got: %r" % errors)


class LegacyTemplateNameTests(unittest.TestCase):
    """CMH-PORT-08: dist templates resolve the new name first, the legacy name as fallback."""

    def test_build_emits_the_new_template_names(self):
        for name in ("SHAREABLE.html", "NONSHAREABLE.html"):
            self.assertTrue(os.path.exists(os.path.join(_paths.DIST, name)),
                            "dist/%s not found - run python tools/build.py" % name)

    def test_resolver_prefers_the_new_name(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ("SHAREABLE.html", LEGACY_TEMPLATE):
                with open(os.path.join(d, name), "w", encoding="utf-8") as fh:
                    fh.write(name)
            got = _toolpath.dist_template("SHAREABLE.html", dist_dir=d)
            self.assertEqual(os.path.basename(got), "SHAREABLE.html")

    def test_resolver_falls_back_to_the_legacy_name(self):
        with tempfile.TemporaryDirectory() as d:
            for legacy, new in ((LEGACY_TEMPLATE, "SHAREABLE.html"),
                                (LEGACY_NONSHAREABLE_TEMPLATE, "NONSHAREABLE.html")):
                with open(os.path.join(d, legacy), "w", encoding="utf-8") as fh:
                    fh.write(legacy)
                got = _toolpath.dist_template(new, dist_dir=d)
                self.assertEqual(os.path.basename(got), legacy,
                                 "expected the legacy %s fallback" % legacy)

    def test_resolver_returns_the_current_name_when_neither_exists(self):
        with tempfile.TemporaryDirectory() as d:
            got = _toolpath.dist_template("SHAREABLE.html", dist_dir=d)
            self.assertEqual(os.path.basename(got), "SHAREABLE.html")

    def test_a_legacy_template_path_resolves_forward(self):
        """A script that still passes --template <dist>/PORTABLE.html must keep working: the
        file was renamed, so the pre-rename path is mapped onto the current sibling."""
        with tempfile.TemporaryDirectory() as d:
            for name in ("SHAREABLE.html", "NONSHAREABLE.html"):
                with open(os.path.join(d, name), "w", encoding="utf-8") as fh:
                    fh.write(name)
            for legacy, current in ((LEGACY_TEMPLATE, "SHAREABLE.html"),
                                    (LEGACY_NONSHAREABLE_TEMPLATE, "NONSHAREABLE.html")):
                got = _toolpath.resolve_template_path(os.path.join(d, legacy))
                self.assertEqual(os.path.basename(got), current)

    def test_every_template_taking_tool_resolves_a_legacy_path(self):
        """All three `--template` CLIs must agree; a legacy path that works for one and fails for
        another is worse than none of them accepting it."""
        for tool in ("new_document.py", "upgrade.py", "vendored_libs.py"):
            with open(os.path.join(AUTHORING, tool), encoding="utf-8") as fh:
                source = fh.read()
            self.assertIn("resolve_template_path", source,
                          "%s must map a legacy --template path forward" % tool)

    def test_an_existing_or_custom_template_path_is_never_redirected(self):
        with tempfile.TemporaryDirectory() as d:
            mine = os.path.join(d, "my-template.html")
            with open(mine, "w", encoding="utf-8") as fh:
                fh.write("x")
            self.assertEqual(_toolpath.resolve_template_path(mine), mine)
            # A legacy NAME that still exists on disk is used as-is, not swapped.
            legacy = os.path.join(d, LEGACY_TEMPLATE)
            with open(legacy, "w", encoding="utf-8") as fh:
                fh.write("x")
            with open(os.path.join(d, "SHAREABLE.html"), "w", encoding="utf-8") as fh:
                fh.write("y")
            self.assertEqual(_toolpath.resolve_template_path(legacy), legacy)
            # An unrelated missing path is returned untouched, so the error names what was asked for.
            missing = os.path.join(d, "nope.html")
            self.assertEqual(_toolpath.resolve_template_path(missing), missing)


class LegacyToolPathTests(unittest.TestCase):
    """CMH-PORT-09: the migration tool keeps working from its pre-rename path."""

    def test_to_shareable_exists(self):
        self.assertTrue(os.path.exists(os.path.join(AUTHORING, "to_shareable.py")))

    def test_legacy_shim_exists_and_runs(self):
        shim = os.path.join(AUTHORING, LEGACY_TOOL)
        self.assertTrue(os.path.exists(shim), "the legacy %s shim must stay" % LEGACY_TOOL)
        proc = subprocess.run([sys.executable, shim, "--help"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("to_shareable", proc.stdout + proc.stderr,
                      "the shim must name its replacement")

    def test_legacy_shim_reports_deprecation_on_stderr(self):
        shim = os.path.join(AUTHORING, LEGACY_TOOL)
        proc = subprocess.run([sys.executable, shim, "--help"], capture_output=True, text=True)
        self.assertIn("deprecated", proc.stderr.lower())

    def test_legacy_shim_re_exports_the_module_api(self):
        sys.path.insert(0, AUTHORING)
        shim = __import__(os.path.splitext(LEGACY_TOOL)[0])
        for name in ("to_portable", "is_nonportable", "is_nonshareable", "read_layer"):
            self.assertTrue(hasattr(shim, name), "the shim must re-export %s" % name)


class LegacyCliFlagTests(unittest.TestCase):
    """CMH-PORT-09: the pre-rename mode flags stay accepted as aliases."""

    def _help(self, tool):
        proc = subprocess.run([sys.executable, os.path.join(AUTHORING, tool), "--help"],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout

    def test_new_document_accepts_both_spellings(self):
        text = self._help("new_document.py")
        for flag in ("--shareable", "--nonshareable", LEGACY_FLAG, LEGACY_NONSHAREABLE_FLAG):
            self.assertIn(flag, text, "new_document.py must accept %s" % flag)

    def test_retrofit_accepts_both_spellings(self):
        text = self._help("retrofit.py")
        for flag in ("--shareable", "--nonshareable", LEGACY_FLAG, LEGACY_NONSHAREABLE_FLAG):
            self.assertIn(flag, text, "retrofit.py must accept %s" % flag)

    def _run_new_document(self, flag):
        """Actually RUN new_document.py with `flag` and return the generated document.

        Printing a flag in --help only proves it is declared; running the tool proves argparse
        accepts it AND that the alias still selects the same output mode."""
        with tempfile.TemporaryDirectory() as d:
            content = os.path.join(d, "body.html")
            with open(content, "w", encoding="utf-8") as fh:
                fh.write("<h1>Legacy flag</h1>\n<p>body</p>\n")
            out = os.path.join(d, "doc.html")
            cmd = [sys.executable, os.path.join(AUTHORING, "new_document.py"),
                   "--content", content, "--key", "auto", "--label", "Legacy flag",
                   "--kind", "report", "--out", out, "--force", "--no-session-id"]
            if flag:
                cmd.append(flag)
            proc = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, "%s failed: %s" % (flag, proc.stderr))
            with open(out, encoding="utf-8") as fh:
                return fh.read()

    def test_the_legacy_flag_still_produces_the_same_document_as_the_current_one(self):
        legacy = self._run_new_document(LEGACY_FLAG)
        current = self._run_new_document("--shareable")
        self.assertIn('"mode":"shareable"', current)
        self.assertIn('"mode":"shareable"', legacy,
                      "%s must still select the single-file mode" % LEGACY_FLAG)

    def test_the_legacy_companion_flag_is_still_accepted_and_ignored(self):
        """The pre-rename `--nonportable` was already DEPRECATED-and-ignored; the alias must keep
        exactly that behavior rather than failing or resurrecting companion output."""
        html = self._run_new_document(LEGACY_NONSHAREABLE_FLAG)
        self.assertIn('"mode":"shareable"', html)

    def test_the_two_legacy_flags_stay_mutually_exclusive(self):
        with tempfile.TemporaryDirectory() as d:
            content = os.path.join(d, "body.html")
            with open(content, "w", encoding="utf-8") as fh:
                fh.write("<h1>x</h1>\n")
            proc = subprocess.run(
                [sys.executable, os.path.join(AUTHORING, "new_document.py"),
                 "--content", content, "--key", "auto", "--label", "x", "--kind", "report",
                 "--out", os.path.join(d, "o.html"), LEGACY_FLAG, LEGACY_NONSHAREABLE_FLAG],
                capture_output=True, text=True)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("not allowed with", proc.stderr)

    def test_retrofit_accepts_the_legacy_flag_end_to_end(self):
        with tempfile.TemporaryDirectory() as d:
            host = os.path.join(d, "host.html")
            with open(host, "w", encoding="utf-8") as fh:
                fh.write("<!DOCTYPE html>\n<html lang=\"en\"><head><title>Host</title></head>"
                         "<body>\n<h1>Host</h1>\n<p>body</p>\n</body></html>\n")
            out = os.path.join(d, "out.html")
            proc = subprocess.run(
                [sys.executable, os.path.join(AUTHORING, "retrofit.py"), host,
                 "--label", "Host", "--kind", "report", "--out", out, LEGACY_FLAG],
                capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            with open(out, encoding="utf-8") as fh:
                self.assertIn('"mode":"shareable"', fh.read())


class LegacyBootstrapAnchorTests(unittest.TestCase):
    """CMH-PORT-07: the pre-rename bootstrap anchor stays recognized."""

    def _module(self, name):
        sys.path.insert(0, AUTHORING)
        return __import__(name)

    def test_upgrade_recognizes_both_anchors(self):
        upgrade = self._module("upgrade")
        self.assertIn(LEGACY_BOOTSTRAP_BEGIN, upgrade.NONSHAREABLE_MARKERS)
        self.assertIn("<!-- BEGIN: commentable-html - NONSHAREABLE BOOTSTRAP -->",
                      upgrade.NONSHAREABLE_MARKERS)
        self.assertTrue(upgrade.has_nonshareable_marker(_legacy_bootstrap()))

    def test_new_document_recognizes_both_anchors(self):
        new_document = self._module("new_document")
        self.assertIn(LEGACY_BOOTSTRAP_BEGIN, new_document.NONSHAREABLE_MARKERS)
        self.assertTrue(new_document.has_nonshareable_marker(_legacy_bootstrap()))

    def test_to_shareable_strips_a_legacy_anchor(self):
        to_shareable = self._module("to_shareable")
        html = "<body>\n" + _legacy_bootstrap() + "\n<p>x</p>\n</body>"
        # An empty CONTENT span at end-of-document: the anchor sits outside it, so it is strippable.
        edit = to_shareable._strip_bootstrap_edit(html, (len(html), len(html)))
        self.assertIsNotNone(edit, "the legacy bootstrap anchor must still be recognized")
        start, end, replacement = edit
        self.assertNotIn("cmhAssetBanner", html[:start] + replacement + html[end:])

    def test_to_shareable_reads_the_legacy_descriptor_mode(self):
        to_shareable = self._module("to_shareable")
        self.assertTrue(to_shareable.is_nonshareable(_legacy_companion_document()))
        self.assertFalse(to_shareable.is_nonshareable(
            build().replace('"mode":"shareable"', '"mode":"%s"' % LEGACY_MODE_SHAREABLE, 1)))

    def test_to_shareable_refuses_to_strip_across_an_intervening_begin(self):
        """A well-formed block only ever pairs with its OWN terminator: if a second BEGIN appears
        before the nearest END, the two anchors belong to different blocks and deleting the span
        between them would take authored content with it."""
        to_shareable = self._module("to_shareable")
        current_begin = "<!-- BEGIN: commentable-html - NONSHAREABLE BOOTSTRAP -->"
        current_end = "<!-- END: commentable-html - NONSHAREABLE BOOTSTRAP -->"
        html = ("<body>\n" + current_begin + "\n<p>orphaned begin, no end of its own</p>\n"
                + LEGACY_BOOTSTRAP_BEGIN + "\n<p>a separate block</p>\n" + current_end
                + "\n</body>")
        self.assertIsNone(to_shareable._strip_bootstrap_edit(html, (len(html), len(html))),
                          "an END that belongs to a later block must not be paired")

    def test_the_legacy_marker_constant_name_survives(self):
        """`NONPORTABLE_MARKER` was a cross-module public constant before the rename, so an
        existing caller reading it must keep working."""
        for name in ("upgrade", "new_document"):
            mod = self._module(name)
            legacy = getattr(mod, "NON%s_MARKER" % _OLD, None)
            self.assertIsNotNone(legacy, "%s.NON%s_MARKER must stay available" % (name, _OLD))
            self.assertEqual(legacy, LEGACY_BOOTSTRAP_BEGIN)

    def test_runtime_strips_both_anchors(self):
        """The shipped runtime keeps a stripper that matches the legacy anchor, so a legacy
        companion document can still be exported to a single file - and it requires the SAME
        spelling at both ends (a backreference), so a mixed pair can never make the match run
        from a real bootstrap into an authored quotation of the other spelling."""
        with open(os.path.join(_paths.DIST, "commentable-html.js"), encoding="utf-8") as fh:
            js = fh.read()
        pattern = "NON(SHAREABLE|%s) BOOTSTRAP" % _OLD
        self.assertIn(pattern, js, "the runtime must still match the legacy bootstrap anchor")
        self.assertIn("END: commentable-html - NON\\1 BOOTSTRAP", js,
                      "the runtime must require the same spelling at both ends")

    def test_to_shareable_strips_a_mixed_anchor_pair(self):
        """A hand-edited or partially-migrated document can pair a legacy BEGIN with a current
        END (or the reverse); leaving that block behind would strand a dead companion watchdog."""
        to_shareable = self._module("to_shareable")
        current_end = "<!-- END: commentable-html - NONSHAREABLE BOOTSTRAP -->"
        current_begin = "<!-- BEGIN: commentable-html - NONSHAREABLE BOOTSTRAP -->"
        for begin, end in ((LEGACY_BOOTSTRAP_BEGIN, current_end),
                           (current_begin, LEGACY_BOOTSTRAP_END)):
            html = ("<body>\n" + begin + "\n"
                    '<div id="cmhAssetBanner" class="cm-skip" role="alert" hidden>x</div>\n'
                    + end + "\n<p>x</p>\n</body>")
            edit = to_shareable._strip_bootstrap_edit(html, (len(html), len(html)))
            self.assertIsNotNone(edit, "a mixed %r/%r pair must still be stripped" % (begin, end))
            start, stop, replacement = edit
            self.assertNotIn("cmhAssetBanner", html[:start] + replacement + html[stop:])


class LegacyRuntimeClassTests(unittest.TestCase):
    """CMH-PORT-07: the pre-rename CSS hooks stay in the stylesheet.

    That class is baked into the MARKUP of every already-shipped companion document, and such a
    document loads the CURRENT companion stylesheet - so dropping the selector would leave its
    companion-only controls permanently visible."""

    def test_stylesheet_keeps_the_legacy_selectors(self):
        with open(os.path.join(_paths.DIST, "commentable-html.css"), encoding="utf-8") as fh:
            css = fh.read()
        for selector in ("." + LEGACY_ONLY_CLASS, "body." + LEGACY_BODY_CLASS,
                         ".cm-nonshareable-only", "body.cm-nonshareable"):
            self.assertIn(selector, css, "stylesheet must keep %s" % selector)

    def test_runtime_adds_both_body_classes(self):
        with open(os.path.join(_paths.DIST, "commentable-html.js"), encoding="utf-8") as fh:
            js = fh.read()
        self.assertIn('"cm-nonshareable"', js)
        self.assertIn('"%s"' % LEGACY_BODY_CLASS, js)


class LegacyExportFilenameTests(unittest.TestCase):
    """CMH-EXP-01 / CMH-PORT-07: the pre-rename `-portable` filename suffix is still stripped.

    Every file the earlier releases exported is named `<stem>-portable.html`. Re-exporting one
    must produce `<stem>-shareable.html`, not `<stem>-portable-shareable.html`."""

    def _runtime(self):
        with open(os.path.join(_paths.DIST, "commentable-html.js"), encoding="utf-8") as fh:
            return fh.read()

    def test_shareable_and_offline_filenames_strip_the_legacy_suffix(self):
        js = self._runtime()
        self.assertIn("/-(?:shareable|%s)$/i" % _OLD_LOWER, js,
                      "the export filename must still strip the pre-rename suffix")
        self.assertEqual(js.count("/-(?:shareable|%s)$/i" % _OLD_LOWER), 2,
                         "both the Shareable and the Offline filename must strip it")


class LegacyValidatorApiTests(unittest.TestCase):
    """CMH-PORT-09: validate.py is an import surface, so its pre-rename symbols stay aliased."""

    def test_module_exposes_the_legacy_names(self):
        pairs = [
            ("NON%s_REGIONS" % _OLD, "NONSHAREABLE_REGIONS"),
            ("DEMO_NON%s_COMMENT_KEY" % _OLD, "DEMO_NONSHAREABLE_COMMENT_KEY"),
            ("DEMO_NON%s_TITLE" % _OLD, "DEMO_NONSHAREABLE_TITLE"),
            ("_is_non%s" % _OLD_LOWER, "_is_nonshareable"),
            ("_check_non%s" % _OLD_LOWER, "_check_nonshareable"),
            ("_non%s_css_refs" % _OLD_LOWER, "_nonshareable_css_refs"),
            ("_non%s_js_refs" % _OLD_LOWER, "_nonshareable_js_refs"),
            ("_non%s_meta_versions" % _OLD_LOWER, "_nonshareable_meta_versions"),
        ]
        for legacy, current in pairs:
            self.assertTrue(hasattr(validate, legacy), "validate.%s must stay available" % legacy)
            self.assertIs(getattr(validate, legacy), getattr(validate, current),
                          "validate.%s must be the same object as %s" % (legacy, current))

    def test_the_accepted_mode_spellings_agree_across_the_validator_and_the_migration_tool(self):
        """The validator and to_shareable.py each carry the accepted-mode tuples; if they drift
        apart, a document one accepts becomes one the other refuses to migrate."""
        sys.path.insert(0, AUTHORING)
        to_shareable = __import__("to_shareable")
        from checks import layer as layer_checks
        self.assertEqual(tuple(to_shareable.SHAREABLE_MODES), tuple(layer_checks.SHAREABLE_MODES))
        self.assertEqual(tuple(to_shareable.NONSHAREABLE_MODES),
                         tuple(layer_checks.NONSHAREABLE_MODES))

    def test_the_companion_end_tag_matcher_accepts_every_real_end_tag(self):
        """CodeQL's `py/bad-tag-filter` reads the companion `</script ...>` matcher as unable to
        match `</script >`. It can - HTML lets an end tag carry ignored attributes and trailing
        space, and the pattern allows both - so pin the behavior rather than reshaping the regex
        around a static-analysis false positive."""
        sys.path.insert(0, AUTHORING)
        to_shareable = __import__("to_shareable")
        rx = to_shareable._COMPANION_ELEMENT_RE["script"]
        for end in ("</script>", "</script >", "</script\t>", "</script\n>", "</SCRIPT   >",
                    "</script foo>"):
            self.assertTrue(rx.search('<script src="commentable-html.js">' + end),
                            "the companion matcher must accept %r" % end)


if __name__ == "__main__":
    unittest.main()
