#!/usr/bin/env python3
"""Regression tests for build.py (the commentable-html asset pipeline).

Standard library only. Verifies the single-source-of-truth guarantees: the shell
+ canonical assets deterministically regenerate dist/PORTABLE.html and the dist/ set,
the on-disk generated files are in sync (--check), the manifest hashes are
correct, the version is single-sourced, and the asset registry round-trips.

Run from the skill root:  python -m unittest discover -s tests -p "test_build.py" -v
"""
import hashlib
import contextlib
import io
import json
import os
import re
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402  shared pkg/dev split path constants
ROOT = _paths.PKG          # shipped outputs (dist/PORTABLE.html, dist/)
TOOLS = _paths.TOOLS       # shipped runtime tools (for `import validate`)
sys.path.insert(0, TOOLS)
sys.path.insert(0, _paths.DEV_TOOLS)  # maintainer-only build tool (build.py lives in dev/)
import build  # noqa: E402  (from dev/tools)
import validate  # noqa: E402  (from pkg/tools)

# Point build's module globals at the split layout so a no-arg build.build_all() reads the
# canonical assets from dev/ and targets the shipped outputs under pkg/. The individual tests
# below still monkeypatch these for their temp-dir scenarios.
build.ASSETS = _paths.ASSETS
build.HERE = ROOT
build.DIST = os.path.join(ROOT, "dist")

DIST = os.path.join(ROOT, "dist")
BUILD_PY = os.path.join(_paths.DEV_TOOLS, "build.py")


def _read(path):
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read().replace("\r\n", "\n").replace("\r", "\n")


def _body_open_tag(html):
    m = re.search(r"<body\b[^>]*>", html, re.IGNORECASE)
    return m.group(0) if m else None


class BuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # build_all() outputs are immutable for a given source tree, so build once per
        # class instead of per test method.
        cls.outputs, cls.version = build.build_all()

    def _write_checked_tree(self, root):
        # Copy the REAL partial source dirs (assets/js/, assets/css/) and the shell into a temp
        # assets tree, then build from THAT tree - so build_all/--check are exercised against a
        # passed --assets-dir, not the default. (Writing single monolith files here would no longer
        # match load_sources, which reads the numbered partials.)
        assets = os.path.join(root, "assets")
        out_dir = os.path.join(root, "skill")
        os.makedirs(assets)
        shutil.copytree(os.path.join(build.ASSETS, "js"), os.path.join(assets, "js"))
        shutil.copytree(os.path.join(build.ASSETS, "css"), os.path.join(assets, "css"))
        shutil.copy2(os.path.join(build.ASSETS, "template.shell.html"),
                     os.path.join(assets, "template.shell.html"))
        outputs, version = build.build_all(assets, out_dir)
        for path, text in outputs.items():
            build.write(path, text)
        for path, text in build.source_stamps(version, assets, out_dir).items():
            build.write(path, text)
        return assets, out_dir

    # -- single source of truth -------------------------------------------- #
    def test_check_subprocess_passes(self):
        with tempfile.TemporaryDirectory() as d:
            assets, out_dir = self._write_checked_tree(d)
            r = subprocess.run(
                [sys.executable, BUILD_PY, "--check", "--assets-dir", assets, "--out-dir", out_dir],
                capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_check_fixtures_passes_and_is_reported(self):
        # --check-fixtures runs the fixtures' own generate.mjs --check against the committed
        # fixtures (which are in sync). It passes whether node is present (real check) or absent
        # (graceful skip) - either way it must not fail a clean tree, and it reports its status.
        with tempfile.TemporaryDirectory() as d:
            assets, out_dir = self._write_checked_tree(d)
            r = subprocess.run(
                [sys.executable, BUILD_PY, "--check", "--check-fixtures",
                 "--assets-dir", assets, "--out-dir", out_dir],
                capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("fixtures --check", r.stdout)

    def test_check_fixtures_fails_when_generator_is_missing(self):
        # A missing generate.mjs when fixtures are explicitly checked is a repo problem, not a
        # soft skip - otherwise deleting the generator would make the fixture gate vacuous.
        orig = build.FIXTURES_GEN
        build.FIXTURES_GEN = os.path.join(tempfile.gettempdir(), "no-such-generate-mjs-xyz.mjs")
        try:
            ok, msg = build._check_fixtures()
        finally:
            build.FIXTURES_GEN = orig
        self.assertFalse(ok, msg)
        self.assertIn("missing", msg)

    def test_generated_files_match_disk(self):
        for path, text in self.outputs.items():
            self.assertTrue(os.path.exists(path), "missing generated file: %s" % path)
            self.assertEqual(_read(path), text.replace("\r\n", "\n"),
                             "on-disk %s is stale - run python tools/build.py" % os.path.relpath(path, ROOT))

    def test_build_is_idempotent(self):
        again, _ = build.build_all()
        self.assertEqual(set(again), set(self.outputs))
        for k in self.outputs:
            self.assertEqual(again[k], self.outputs[k])

    def test_inline_template_round_trips_from_shell_and_assets(self):
        css, js, shell, version = build.load_sources()
        js = build._stamp_const(js, version, "commentable-html.js")
        rebuilt = build.build_inline(css, js, shell, version, build.read_mermaid_version())
        self.assertEqual(rebuilt, _read(os.path.join(ROOT, "dist", "PORTABLE.html")))

    # -- versioning / manifest --------------------------------------------- #
    def test_version_is_single_sourced(self):
        v = build.read_version()
        self.assertRegex(v, r"^\d+\.\d+\.\d+$")
        manifest = json.loads(_read(os.path.join(DIST, "manifest.json")))
        self.assertEqual(manifest["version"], v)
        self.assertEqual(set(manifest["files"]), {
            "commentable-html.css",
            "commentable-html.js",
            "commentable-html.assets.js",
        })
        companion_js = _read(os.path.join(DIST, "commentable-html.js"))
        self.assertIn('const CMH_VERSION = "%s";' % v, companion_js)
        for name in ("PORTABLE.html", "NONPORTABLE.html"):
            html = _read(os.path.join(DIST, name))
            self.assertIn('<meta name="commentable-html-version" content="%s"' % v, html)

    def test_source_stamps_include_visible_version_in_skill_and_dist_readme(self):
        # The human-readable version line in SKILL.md and dist/README.md is stamped from the
        # single source (dev/VERSION), so `build.py` re-stamps it and `--check` catches drift.
        v = build.read_version()
        stamps = build.source_stamps(v, build.ASSETS, ROOT)
        skill = os.path.join(ROOT, "SKILL.md")
        readme = os.path.join(ROOT, "dist", "README.md")
        self.assertIn(skill, stamps)
        self.assertIn(readme, stamps)
        self.assertIn("**Version:** `%s`" % v, stamps[skill])
        self.assertIn("**Version:** `%s`" % v, stamps[readme])

    def test_source_stamps_include_claude_manifests(self):
        # CMH-TOOL-06: the Claude Code manifests mirror the Copilot ones, so build stamps their
        # version too - otherwise a version bump leaves the Claude plugin.json behind and the
        # claude-manifest/version-bump guards fail on the next release.
        v = build.read_version()
        stamps = build.source_stamps(v, build.ASSETS, ROOT)
        claude_pj = [p for p in stamps
                     if p.replace("\\", "/").endswith(".claude-plugin/plugin.json")]
        claude_mkt = [p for p in stamps
                      if p.replace("\\", "/").endswith(".claude-plugin/marketplace.json")]
        # Present in this repo layout; assert they are stamped when present.
        for p in claude_pj + claude_mkt:
            self.assertIn('"version": "%s"' % v, stamps[p],
                          "%s not stamped to %s" % (p, v))
        self.assertTrue(claude_pj, "Claude plugin.json was not stamped by build")
        self.assertTrue(claude_mkt, "Claude marketplace.json was not stamped by build")

    def test_mermaid_version_is_single_sourced(self):
        mv = build.read_mermaid_version()
        self.assertRegex(mv, r"^\d+\.\d+\.\d+$")
        # read_mermaid_version pins the package.json mermaid dependency (exact or ^/~) to its base.
        pkg = json.loads(_read(build.PACKAGE_JSON))
        spec = pkg["devDependencies"]["mermaid"]
        self.assertEqual(re.match(r"^[\^~]?(\d+\.\d+\.\d+)$", spec).group(1), mv)
        # Any shipped mermaid CDN import (dist + examples), whatever its version shape, must already
        # be the single-sourced version; the dist templates must actually carry an import (so the
        # assertion is not vacuous). Examples that do not use mermaid are simply not required to.
        ref_re = re.compile(r"cdn\.jsdelivr\.net/npm/mermaid@([^/]+)/dist/")
        shipped = [os.path.join(DIST, "PORTABLE.html"), os.path.join(DIST, "NONPORTABLE.html")]
        ex_dir = os.path.join(ROOT, "examples")
        if os.path.isdir(ex_dir):
            shipped += [os.path.join(ex_dir, n) for n in os.listdir(ex_dir) if n.endswith(".html")]
        seen = 0
        for path in shipped:
            for found in ref_re.findall(_read(path)):
                seen += 1
                self.assertEqual(found, mv, "%s pins mermaid@%s but package.json single-sources %s; run build.py"
                                 % (os.path.relpath(path, ROOT), found, mv))
        self.assertGreaterEqual(seen, 2, "expected the dist PORTABLE/NONPORTABLE templates to carry mermaid imports")

    def test_example_stamps_repairs_mermaid_drift(self):
        mv = build.read_mermaid_version()
        # example_stamps owns non-report example html (report-*.html is regenerated in full
        # by build_examples, which stamps mermaid itself). Repair any drifted version shape:
        # exact, major-only, and major.minor pins all get pinned back.
        for bad in ("9.9.9", "11", "10.1"):
            drift = ('x <script>import("https://cdn.jsdelivr.net/npm/mermaid@%s/'
                     'dist/mermaid.esm.min.mjs")</script> y' % bad)
            with tempfile.TemporaryDirectory() as d:
                os.makedirs(os.path.join(d, "examples"))
                p = os.path.join(d, "examples", "guide-drift.html")
                with open(p, "w", encoding="utf-8") as fh:
                    fh.write(drift)
                stamps = build.example_stamps(d, mv)
                self.assertIn(p, stamps)
                self.assertIn("mermaid@%s/dist/" % mv, stamps[p])
                self.assertNotIn("mermaid@%s/dist/" % bad, stamps[p])

    def test_example_stamps_skips_report_examples(self):
        # report-*.html is fully regenerated by build_examples; example_stamps must not also
        # produce it (two producers writing the same path would break the build and --check).
        mv = build.read_mermaid_version()
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "examples"))
            drift = ('x <script>import("https://cdn.jsdelivr.net/npm/mermaid@9.9.9/'
                     'dist/mermaid.esm.min.mjs")</script> y')
            p = os.path.join(d, "examples", "report-drift.html")
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(drift)
            self.assertNotIn(p, build.example_stamps(d, mv))

    def test_example_stamps_skips_non_mermaid_and_is_idempotent(self):
        mv = build.read_mermaid_version()
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "examples"))
            # A non-mermaid example is skipped (not in the stamp set), not errored.
            none_p = os.path.join(d, "examples", "no-mermaid.html")
            with open(none_p, "w", encoding="utf-8") as fh:
                fh.write("<p>no mermaid here {{ vue }} and A{{hex}} too</p>")
            # An already-correct example is a no-op: it round-trips to identical bytes.
            ok = 'a <script>import("https://cdn.jsdelivr.net/npm/mermaid@%s/dist/mermaid.esm.min.mjs")</script> b' % mv
            ok_p = os.path.join(d, "examples", "guide-ok.html")
            with open(ok_p, "w", encoding="utf-8") as fh:
                fh.write(ok)
            stamps = build.example_stamps(d, mv)
            self.assertNotIn(none_p, stamps)
            self.assertEqual(stamps[ok_p], ok)

    def test_build_examples_stamps_report_mermaid(self):
        # build_examples owns report-*.html end to end: it swaps the layer regions AND
        # re-pins the mermaid CDN to the single source, so a drifted report is repaired.
        mv = build.read_mermaid_version()
        version = _read(os.path.join(_paths.DEV, "VERSION")).strip()
        portable = _read(os.path.join(DIST, "PORTABLE.html"))
        src = _read(os.path.join(_paths.EXAMPLES, "report-taxi.html"))
        drifted = src.replace("mermaid@%s/dist/" % mv, "mermaid@9.9.9/dist/")
        self.assertNotEqual(drifted, src, "fixture should contain a mermaid pin to drift")
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "examples"))
            p = os.path.join(d, "examples", "report-taxi.html")
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(drifted)
            out = build.build_examples(portable, version, mv, d)
            self.assertIn(p, out)
            self.assertIn("mermaid@%s/dist/" % mv, out[p])
            self.assertNotIn("mermaid@9.9.9/dist/", out[p])

    def test_region_inner_rejects_duplicate_begin_marker(self):
        text = ("/* ============================================================\n"
                "   BEGIN: commentable-html - CSS\n"
                "   ============================================================ */\n"
                "body { color: red; }\n"
                "/* ============================================================\n"
                "   BEGIN: commentable-html - CSS\n"
                "   ============================================================ */\n"
                "body { color: blue; }\n"
                "/* ============================================================\n"
                "   END: commentable-html - CSS\n"
                "   ============================================================ */\n")
        with self.assertRaisesRegex(SystemExit, "duplicate region: CSS"):
            build._region_inner(text, "CSS", "<duplicate>")

    def test_region_inner_rejects_duplicate_end_marker(self):
        text = ("/* ============================================================\n"
                "   BEGIN: commentable-html - JS\n"
                "   ============================================================ */\n"
                "body();\n"
                "<!-- END: commentable-html - JS -->\n"
                "<!-- END: commentable-html - JS -->\n")
        with self.assertRaisesRegex(SystemExit, "duplicate region: JS"):
            build._region_inner(text, "JS", "<duplicate>")

    def test_regen_example_rejects_duplicate_state_region_end(self):
        portable = _read(os.path.join(DIST, "PORTABLE.html"))
        example = portable.replace(
            "<!-- END: commentable-html - EMBEDDED COMMENTS -->",
            "<!-- END: commentable-html - EMBEDDED COMMENTS -->\n"
            "<!-- END: commentable-html - EMBEDDED COMMENTS -->",
            1)
        with self.assertRaisesRegex(SystemExit, "duplicate region: EMBEDDED COMMENTS"):
            build.regen_example(example, portable, build.read_version(), build.read_mermaid_version(), "<duplicate>")

    def test_region_inner_rejects_trailing_authored_text(self):
        text = ("     BEGIN: commentable-html - CSS as documented in this authored note\n"
                "poison-before\n"
                "/* ============================================================\n"
                "   BEGIN: commentable-html - CSS\n"
                "body\n"
                "   END: commentable-html - CSS\n"
                "   ============================================================ */\n")
        b, e = build._region_inner(text, "CSS", "<t>")
        inner = text[b:e]
        self.assertIn("body", inner)
        self.assertNotIn("poison-before", inner)
        self.assertNotIn("authored note", inner)

    def test_region_inner_ignores_marker_text_inside_pre_content(self):
        text = ("<pre>\nBEGIN: commentable-html - JS\n</pre>\n"
                "<!-- ============================================================\n"
                "     BEGIN: commentable-html - JS\n"
                "     ============================================================ -->\n"
                "body();\n"
                "<!-- END: commentable-html - JS -->\n")
        b, e = build._region_inner(text, "JS", "<t>")
        inner = text[b:e]
        self.assertIn("body();", inner)
        self.assertNotIn("<pre>", inner)

    def test_manifest_hashes_match_dist_files(self):
        manifest = json.loads(_read(os.path.join(DIST, "manifest.json")))
        for name, meta in manifest["files"].items():
            content = _read(os.path.join(DIST, name))
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            self.assertEqual(meta["sha256"], digest, "hash mismatch for %s" % name)

    def test_manifest_is_deterministically_key_sorted(self):
        raw = self.outputs[os.path.join(DIST, "manifest.json")]
        manifest = json.loads(raw)
        self.assertEqual(list(manifest.keys()), sorted(manifest.keys()))
        for value in manifest.values():
            if isinstance(value, dict):
                self.assertEqual(list(value.keys()), sorted(value.keys()))
        self.assertEqual(raw, json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    # -- asset registry (Export standalone payload) ------------------------ #
    def test_registry_has_no_raw_script_close(self):
        reg = _read(os.path.join(DIST, "commentable-html.assets.js"))
        self.assertIsNone(re.search(r"</\s*script", reg, re.IGNORECASE),
                          "assets registry must not contain a raw </script>")

    def test_registry_payload_matches_companion_files(self):
        reg = _read(os.path.join(DIST, "commentable-html.assets.js"))
        obj = json.loads(re.search(r"=\s*(\{.*\})\s*;", reg, re.S).group(1))
        css = _read(os.path.join(DIST, "commentable-html.css")).rstrip("\n")
        js = _read(os.path.join(DIST, "commentable-html.js")).rstrip("\n")
        self.assertEqual(obj["version"], self.version)
        self.assertEqual(obj["css"], css)
        self.assertEqual(obj["js"], js)

    # -- token win --------------------------------------------------------- #
    def test_nonportable_is_much_smaller_than_inline(self):
        inline = self.outputs[os.path.join(ROOT, "dist", "PORTABLE.html")]
        eco = self.outputs[os.path.join(DIST, "NONPORTABLE.html")]
        self.assertLess(len(eco), len(inline) * 0.4,
                        "nonportable template should be dramatically smaller than inline")

    # -- both generated templates validate --------------------------------- #
    def test_both_templates_validate_clean(self):
        for rel in ("dist/PORTABLE.html", os.path.join("dist", "NONPORTABLE.html")):
            errors, warnings = validate.validate(os.path.join(ROOT, rel))
            self.assertEqual(errors, [], "%s errors: %r" % (rel, errors))
            self.assertEqual(warnings, [], "%s warnings: %r" % (rel, warnings))

    # -- transient body-state is never baked into a shipped template ------- #
    def test_dist_templates_do_not_bake_sidebar_open_body_class(self):
        # CMH-BUILD-06: sidebar-open is a transient runtime UI-state class the layer toggles on
        # document.body; baking it into a shipped <body> makes the document render full width with
        # an empty sidebar gutter (the body.sidebar-open .app rule) before the runtime re-derives
        # state on load.
        for name in ("PORTABLE.html", "NONPORTABLE.html"):
            body = _body_open_tag(_read(os.path.join(DIST, name)))
            self.assertIsNotNone(body, "no <body> open tag in dist/%s" % name)
            self.assertNotIn("sidebar-open", body,
                             "dist/%s bakes the transient sidebar-open class into <body>" % name)

    def test_template_shell_does_not_bake_sidebar_open_body_class(self):
        # CMH-BUILD-06: the canonical shell is the single source; if it carries sidebar-open on
        # <body> every generated artifact inherits it.
        _css, _js, shell, _version = build.load_sources()
        body = _body_open_tag(shell)
        self.assertIsNotNone(body, "no <body> open tag in template.shell.html")
        self.assertNotIn("sidebar-open", body,
                         "template.shell.html bakes the transient sidebar-open class into <body>")

    # -- diff / code-review layer ships in the generated artifacts --------- #
    def test_diff_layer_present_in_artifacts(self):
        tpl = _read(os.path.join(ROOT, "dist", "PORTABLE.html"))
        self.assertIn('class="cmh-diff"', tpl, "diff demo block missing from dist/PORTABLE.html")
        self.assertIn("setupDiffLayer", tpl, "diff runtime missing from inline dist/PORTABLE.html")
        self.assertIn("cmh-diff-view", tpl, "diff CSS missing from inline dist/PORTABLE.html")
        eco_js = _read(os.path.join(DIST, "commentable-html.js"))
        self.assertIn("setupDiffLayer", eco_js, "diff runtime missing from nonportable companion JS")
        eco_css = _read(os.path.join(DIST, "commentable-html.css"))
        self.assertIn("cmh-diff-view", eco_css, "diff CSS missing from nonportable companion CSS")

    # -- stale-artifact detection ------------------------------------------ #
    def test_stale_dist_files_are_detected(self):
        # A companion from an older version, not in the current build, is flagged.
        with tempfile.TemporaryDirectory() as d:
            for name in ("commentable-html.css", "commentable-html.v9.9.9.css", "commentable-html.v2.5.0.css"):
                with open(os.path.join(d, name), "w", encoding="utf-8") as fh:
                    fh.write("x")
            orig = build.DIST
            try:
                build.DIST = d
                expected = [os.path.join(d, "commentable-html.css")]
                stale = build._unexpected_dist_files(expected)
            finally:
                build.DIST = orig
        self.assertEqual(stale, ["commentable-html.v2.5.0.css", "commentable-html.v9.9.9.css"])

    def test_version_must_be_single_declaration(self):
        # Two CMH_VERSION declarations must fail the build loudly.
        js = 'const CMH_VERSION = "2.5.0";\nconst CMH_VERSION = "2.6.0";\n'
        with self.assertRaises(SystemExit):
            build._stamp_const(js, "1.0.0", "commentable-html.js")

    def test_write_creates_parent_and_normalizes_lf(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "nested", "out.txt")
            build.write(path, "a\r\nb\rc")
            with open(path, "rb") as fh:
                self.assertEqual(fh.read(), b"a\nb\nc")

    def test_unexpected_dist_files_missing_dist_is_empty(self):
        orig = build.DIST
        with tempfile.TemporaryDirectory() as d:
            try:
                build.DIST = os.path.join(d, "dist")
                self.assertEqual(build._unexpected_dist_files([]), [])
            finally:
                build.DIST = orig

    def test_build_inline_requires_both_placeholders(self):
        with self.assertRaises(SystemExit) as cm:
            build.build_inline("css", "js", "<style>{{CMH_CSS}}</style>", "1.0.0", "11.16.0")
        self.assertIn("missing placeholder", str(cm.exception))

    def test_build_assets_js_rejects_raw_script_close(self):
        with self.assertRaises(SystemExit) as cm:
            build.build_assets_js("</script>", "js", "1.2.3")
        self.assertIn("raw </script>", str(cm.exception))

    def test_build_nonportable_reports_malformed_shells(self):
        _css, _js, shell, version = build.load_sources()
        head_end = shell.index("</head>")
        body_pos = shell.index("<body", head_end)
        no_body_shell = shell[:body_pos] + "<main" + shell[body_pos + len("<body"):]
        cases = [
            (shell.replace("BEGIN: commentable-html - CSS", "BEGIN: broken CSS", 1), "CSS region"),
            (shell.replace("</style>\n</head>", "</style></head>", 1), "</style></head>"),
            (shell.replace("BEGIN: commentable-html - JS", "BEGIN: broken JS", 1), "JS region"),
            (no_body_shell, "<body> tag"),
            (shell + "\n{{CMH_LEFT}}\n", "unresolved placeholder"),
        ]
        for bad_shell, message in cases:
            with self.subTest(message=message):
                with self.assertRaises(SystemExit) as cm:
                    build.build_nonportable(bad_shell, version, "11.16.0")
                self.assertIn(message, str(cm.exception))

    def test_main_check_reports_missing_outdated_and_stale(self):
        with tempfile.TemporaryDirectory() as d:
            dist = os.path.join(d, "dist")
            os.makedirs(dist)
            tpl = os.path.join(d, "dist", "PORTABLE.html")
            missing = os.path.join(dist, "NONPORTABLE.html")
            stale = os.path.join(dist, "commentable-html.v0.0.1.css")
            with open(tpl, "w", encoding="utf-8") as fh:
                fh.write("old")
            with open(stale, "w", encoding="utf-8") as fh:
                fh.write("stale")
            outputs = {tpl: "new", missing: "eco"}
            err = io.StringIO()
            with mock.patch.object(build, "HERE", d), mock.patch.object(build, "DIST", dist), \
                    mock.patch.object(build, "build_all", return_value=(outputs, "1.2.3")), \
                    mock.patch.object(build, "source_stamps", return_value={}), \
                    contextlib.redirect_stderr(err):
                code = build.main(["build.py", "--check"])
            self.assertEqual(code, 1)
            self.assertIn("dist%sPORTABLE.html (out of date)" % os.sep, err.getvalue())
            self.assertIn("dist%sNONPORTABLE.html (missing)" % os.sep, err.getvalue())
            self.assertIn("commentable-html.v0.0.1.css", err.getvalue())

    def test_main_check_ok_prints_version(self):
        with tempfile.TemporaryDirectory() as d:
            dist = os.path.join(d, "dist")
            os.makedirs(dist)
            tpl = os.path.join(d, "dist", "PORTABLE.html")
            eco = os.path.join(dist, "NONPORTABLE.html")
            outputs = {tpl: "tpl", eco: "eco"}
            for path, text in outputs.items():
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(text)
            out = io.StringIO()
            with mock.patch.object(build, "HERE", d), mock.patch.object(build, "DIST", dist), \
                    mock.patch.object(build, "build_all", return_value=(outputs, "1.2.3")), \
                    mock.patch.object(build, "source_stamps", return_value={}), \
                    contextlib.redirect_stdout(out):
                code = build.main(["build.py", "--check"])
            self.assertEqual(code, 0)
            self.assertIn("build --check OK (2 generated files in sync, version 1.2.3)", out.getvalue())

    def test_main_writes_outputs_removes_stale_and_reports_sizes(self):
        with tempfile.TemporaryDirectory() as d:
            dist = os.path.join(d, "dist")
            os.makedirs(dist)
            tpl = os.path.join(d, "dist", "PORTABLE.html")
            css = os.path.join(dist, "commentable-html.css")
            eco = os.path.join(dist, "NONPORTABLE.html")
            stale = os.path.join(dist, "commentable-html.v0.0.1.css")
            with open(stale, "w", encoding="utf-8") as fh:
                fh.write("stale")
            outputs = {tpl: "inline body", css: "css body", eco: "eco"}
            out = io.StringIO()
            with mock.patch.object(build, "HERE", d), mock.patch.object(build, "DIST", dist), \
                    mock.patch.object(build, "build_all", return_value=(outputs, "1.2.3")), \
                    mock.patch.object(build, "source_stamps", return_value={}), \
                    contextlib.redirect_stdout(out):
                code = build.main(["build.py"])
            self.assertEqual(code, 0)
            self.assertFalse(os.path.exists(stale))
            self.assertEqual(_read(tpl), "inline body")
            self.assertEqual(_read(css), "css body")
            self.assertIn("removed 1 stale dist file(s): commentable-html.v0.0.1.css", out.getvalue())
            self.assertIn("commentable-html build - version 1.2.3", out.getvalue())

    def test_module_entrypoint_uses_sys_argv(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as d:
            assets, out_dir = self._write_checked_tree(d)
            argv = [BUILD_PY, "--check", "--assets-dir", assets, "--out-dir", out_dir]
            with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(out):
                with self.assertRaises(SystemExit) as cm:
                    runpy.run_path(BUILD_PY, run_name="__main__")
        self.assertEqual(cm.exception.code, 0)
        self.assertIn("build --check OK", out.getvalue())


class StampHelperTests(unittest.TestCase):
    def test_read_version_rejects_non_semver(self):
        with tempfile.TemporaryDirectory() as d:
            vf = os.path.join(d, "VERSION")
            for bad in ("1.0", "1.0.0-rc1", "x", "1.2.3 extra"):
                with open(vf, "w", encoding="utf-8") as fh:
                    fh.write(bad)
                with self.assertRaises(SystemExit):
                    build.read_version(vf)
            with open(vf, "w", encoding="utf-8") as fh:
                fh.write("1.2.3\n")
            self.assertEqual(build.read_version(vf), "1.2.3")

    def test_stamp_md_version_updates_the_single_marker(self):
        text = "# dist\n\n**Version:** `1.0.0`\n\nbody\n"
        out = build._stamp_md_version(text, "2.0.0", "x")
        self.assertIn("**Version:** `2.0.0`", out)
        self.assertNotIn("1.0.0", out)

    def test_stamp_md_version_requires_exactly_one_marker(self):
        with self.assertRaises(SystemExit):
            build._stamp_md_version("no version marker here\n", "2.0.0", "x")
        with self.assertRaises(SystemExit):
            build._stamp_md_version("**Version:** `1.0.0` `2.0.0` not\n"
                                    "**Version:** `1.0.0`\n", "3.0.0", "x")

    def test_stamp_plugin_json_preserves_format_and_sets_top_level(self):
        text = '{\n  "name": "x",\n  "version": "1.0.0",\n  "keywords": ["a", "b"]\n}\n'
        out = build._stamp_plugin_json(text, "2.0.0")
        self.assertIn('"version": "2.0.0"', out)
        self.assertIn('"keywords": ["a", "b"]', out)

    def test_stamp_plugin_json_stamps_top_level_and_preserves_nested_version(self):
        # A schema-valid manifest may carry a nested version (e.g. author.version);
        # only the top-level version is stamped, and it is not rejected.
        text = '{\n  "name": "x",\n  "version": "1.0.0",\n  "author": {"version": "9.9.9"}\n}\n'
        out = build._stamp_plugin_json(text, "2.0.0")
        parsed = json.loads(out)
        self.assertEqual(parsed["version"], "2.0.0")
        self.assertEqual(parsed["author"]["version"], "9.9.9")

    def test_stamp_plugin_json_fails_on_malformed(self):
        with self.assertRaises(Exception):
            build._stamp_plugin_json("{bad json", "2.0.0")

    def test_stamp_marketplace_updates_only_target_entry(self):
        data = {"plugins": [
            {"name": "other", "source": "./x", "version": "3.3.3"},
            {"name": "commentable-html", "source": "./y", "version": "1.0.0"}]}
        parsed = json.loads(build._stamp_marketplace(json.dumps(data, indent=2), "2.0.0"))
        self.assertEqual(parsed["plugins"][0]["version"], "3.3.3")
        self.assertEqual(parsed["plugins"][1]["version"], "2.0.0")

    def test_stamp_marketplace_roundtrips_real_file_byte_for_byte(self):
        # Stamping the real manifest to its current version must be a no-op, proving
        # the targeted stamp does not reformat unrelated entries.
        mk = build._find_marketplace(ROOT)
        self.assertIsNotNone(mk)
        original = _read(mk)
        current = next(p["version"] for p in json.loads(original)["plugins"]
                       if p["name"] == "commentable-html")
        self.assertEqual(build._stamp_marketplace(original, current), original)

    def test_stamp_marketplace_fails_when_entry_missing(self):
        with self.assertRaises(SystemExit):
            build._stamp_marketplace('{"plugins": []}', "2.0.0")

    def test_find_marketplace_stops_at_repo_root_without_escaping(self):
        with tempfile.TemporaryDirectory() as d:
            # An outer marketplace.json above the repo boundary must NOT be found.
            outer = os.path.join(d, ".github", "plugin")
            os.makedirs(outer)
            open(os.path.join(outer, "marketplace.json"), "w").close()
            repo = os.path.join(d, "repo")
            os.makedirs(os.path.join(repo, ".git"))
            sub = os.path.join(repo, "a", "b")
            os.makedirs(sub)
            self.assertIsNone(build._find_marketplace(sub))  # bounded by repo/.git
            mk = os.path.join(repo, ".github", "plugin")
            os.makedirs(mk)
            open(os.path.join(mk, "marketplace.json"), "w").close()
            self.assertEqual(os.path.normcase(build._find_marketplace(sub)),
                             os.path.normcase(os.path.join(mk, "marketplace.json")))


if __name__ == "__main__":
    unittest.main()
