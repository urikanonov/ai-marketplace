#!/usr/bin/env python3
"""Regression tests for build.py (the commentable-html asset pipeline).

Standard library only. Verifies the single-source-of-truth guarantees: the shell
+ canonical assets deterministically regenerate dist/SHAREABLE.html and the dist/ set,
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
import zipfile
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402  shared pkg/dev split path constants
ROOT = _paths.PKG          # shipped outputs (dist/SHAREABLE.html, dist/)
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
        shutil.copytree(os.path.join(build.ASSETS, "vendor"), os.path.join(assets, "vendor"))
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
                             "on-disk %s is stale - run %s"
                             % (os.path.relpath(path, ROOT), build.CANONICAL_BUILD_COMMAND))

    def test_build_is_idempotent(self):
        again, _ = build.build_all()
        self.assertEqual(set(again), set(self.outputs))
        for k in self.outputs:
            self.assertEqual(again[k], self.outputs[k])

    def test_inline_template_round_trips_from_shell_and_assets(self):
        css, js, shell, version = build.load_sources()
        # The shipped bytes are the STRIPPED layer (CMH-BUILD-26), stripped after the version
        # stamp, so a round trip has to run the same two steps build_all does.
        js = build.minify_js(build._stamp_const(js, version, "commentable-html.js"))
        rebuilt = build.build_inline(build.minify_css(css), js, shell, version,
                                     build.read_mermaid_version())
        self.assertEqual(rebuilt, _read(os.path.join(ROOT, "dist", "SHAREABLE.html")))

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
        stamped = _paths.CMH_VERSION_CONST_RE.search(companion_js)
        self.assertIsNotNone(stamped, "the built layer no longer declares CMH_VERSION")
        self.assertEqual(stamped.group(1), v)
        for name in ("SHAREABLE.html", "NONSHAREABLE.html"):
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
        stamps = build.source_stamps(v, build.ASSETS, ROOT, _paths.PKG_SHIPPED)
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
        shipped = [os.path.join(DIST, "SHAREABLE.html"), os.path.join(DIST, "NONSHAREABLE.html")]
        ex_dir = _paths.EXAMPLES
        if os.path.isdir(ex_dir):
            shipped += [os.path.join(ex_dir, n) for n in os.listdir(ex_dir) if n.endswith(".html")]
        seen = 0
        for path in shipped:
            for found in ref_re.findall(_read(path)):
                seen += 1
                self.assertEqual(found, mv, "%s pins mermaid@%s but package.json single-sources %s; run build.py"
                                 % (os.path.relpath(path, ROOT), found, mv))
        self.assertGreaterEqual(seen, 2, "expected the dist SHAREABLE/NONSHAREABLE templates to carry mermaid imports")

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
                stamps = build.example_stamps(os.path.join(d, "examples"), mv)
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
            self.assertNotIn(p, build.example_stamps(os.path.join(d, "examples"), mv))

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
            stamps = build.example_stamps(os.path.join(d, "examples"), mv)
            self.assertNotIn(none_p, stamps)
            self.assertEqual(stamps[ok_p], ok)

    def test_build_examples_stamps_report_mermaid(self):
        # build_examples owns report-*.html end to end: it swaps the layer regions AND
        # re-pins the mermaid CDN to the single source, so a drifted report is repaired.
        mv = build.read_mermaid_version()
        version = _read(os.path.join(_paths.DEV, "VERSION")).strip()
        shareable = _read(os.path.join(DIST, "SHAREABLE.html"))
        src = _read(os.path.join(_paths.EXAMPLES, "report-taxi.html"))
        drifted = src.replace("mermaid@%s/dist/" % mv, "mermaid@9.9.9/dist/")
        self.assertNotEqual(drifted, src, "fixture should contain a mermaid pin to drift")
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "examples"))
            p = os.path.join(d, "examples", "report-taxi.html")
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(drifted)
            out = build.build_examples(shareable, version, mv, os.path.join(d, "examples"))
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
        shareable = _read(os.path.join(DIST, "SHAREABLE.html"))
        example = shareable.replace(
            "<!-- END: commentable-html - EMBEDDED COMMENTS -->",
            "<!-- END: commentable-html - EMBEDDED COMMENTS -->\n"
            "<!-- END: commentable-html - EMBEDDED COMMENTS -->",
            1)
        with self.assertRaisesRegex(SystemExit, "duplicate region: EMBEDDED COMMENTS"):
            build.regen_example(example, shareable, build.read_version(), build.read_mermaid_version(), "<duplicate>")

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
    def test_nonshareable_is_much_smaller_than_inline(self):
        inline = self.outputs[os.path.join(ROOT, "dist", "SHAREABLE.html")]
        eco = self.outputs[os.path.join(DIST, "NONSHAREABLE.html")]
        self.assertLess(len(eco), len(inline) * 0.8,
                        "nonshareable template should stay materially smaller than inline even with offline rich-content support")

    # -- both generated templates validate --------------------------------- #
    def test_both_templates_validate_clean(self):
        for rel in ("dist/SHAREABLE.html", os.path.join("dist", "NONSHAREABLE.html")):
            errors, warnings = validate.validate(os.path.join(ROOT, rel))
            self.assertEqual(errors, [], "%s errors: %r" % (rel, errors))
            self.assertEqual(warnings, [], "%s warnings: %r" % (rel, warnings))

    # -- transient body-state is never baked into a shipped template ------- #
    def test_dist_templates_do_not_bake_sidebar_open_body_class(self):
        # CMH-BUILD-06: sidebar-open is a transient runtime UI-state class the layer toggles on
        # document.body; baking it into a shipped <body> makes the document render full width with
        # an empty sidebar gutter (the body.sidebar-open .app rule) before the runtime re-derives
        # state on load.
        for name in ("SHAREABLE.html", "NONSHAREABLE.html"):
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
        tpl = _read(os.path.join(ROOT, "dist", "SHAREABLE.html"))
        self.assertIn('class="cmh-diff"', tpl, "diff demo block missing from dist/SHAREABLE.html")
        self.assertIn("setupDiffLayer", tpl, "diff runtime missing from inline dist/SHAREABLE.html")
        self.assertIn("cmh-diff-view", tpl, "diff CSS missing from inline dist/SHAREABLE.html")
        eco_js = _read(os.path.join(DIST, "commentable-html.js"))
        self.assertIn("setupDiffLayer", eco_js, "diff runtime missing from nonshareable companion JS")
        eco_css = _read(os.path.join(DIST, "commentable-html.css"))
        self.assertIn("cmh-diff-view", eco_css, "diff CSS missing from nonshareable companion CSS")

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

    def test_build_nonshareable_reports_malformed_shells(self):
        _css, _js, shell, version = build.load_sources()
        fence = shell.index(build.MACHINERY_BEGIN)
        style_close = shell.index("</style>\n", fence)
        no_style_shell = (shell[:style_close] + "</style>"
                          + shell[style_close + len("</style>\n"):])
        no_fence_shell = shell.replace(build.MACHINERY_BEGIN, "BEGIN: broken MACHINERY", 1)
        cases = [
            (shell.replace("BEGIN: commentable-html - CSS", "BEGIN: broken CSS", 1), "CSS region"),
            (no_style_shell, "</style> after the shell's MACHINERY fence"),
            (shell.replace("BEGIN: commentable-html - JS", "BEGIN: broken JS", 1), "JS region"),
            (no_fence_shell, "MACHINERY fence"),
            (shell + "\n{{CMH_LEFT}}\n", "unresolved placeholder"),
        ]
        for bad_shell, message in cases:
            with self.subTest(message=message):
                with self.assertRaises(SystemExit) as cm:
                    build.build_nonshareable(bad_shell, version, "11.16.0")
                self.assertIn(message, str(cm.exception))

    def test_main_check_reports_missing_outdated_and_stale(self):
        with tempfile.TemporaryDirectory() as d:
            dist = os.path.join(d, "dist")
            os.makedirs(dist)
            tpl = os.path.join(d, "dist", "SHAREABLE.html")
            missing = os.path.join(dist, "NONSHAREABLE.html")
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
            self.assertIn(build.CANONICAL_BUILD_COMMAND, err.getvalue())
            self.assertIn("dist%sSHAREABLE.html (out of date)" % os.sep, err.getvalue())
            self.assertIn("dist%sNONSHAREABLE.html (missing)" % os.sep, err.getvalue())
            self.assertIn("commentable-html.v0.0.1.css", err.getvalue())

    def test_main_check_ok_prints_version(self):
        with tempfile.TemporaryDirectory() as d:
            dist = os.path.join(d, "dist")
            os.makedirs(dist)
            tpl = os.path.join(d, "dist", "SHAREABLE.html")
            eco = os.path.join(dist, "NONSHAREABLE.html")
            outputs = {tpl: "tpl", eco: "eco"}
            for path, text in outputs.items():
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(text)
            out = io.StringIO()
            with mock.patch.object(build, "HERE", d), mock.patch.object(build, "DIST", dist), \
                    mock.patch.object(build, "build_all", return_value=(outputs, "1.2.3")), \
                    mock.patch.object(build, "read_size_budget",
                                      return_value={os.path.join("dist", "SHAREABLE.html"): 1000,
                                                    os.path.join("dist", "NONSHAREABLE.html"): 1000}), \
                    mock.patch.object(build, "source_stamps", return_value={}), \
                    contextlib.redirect_stdout(out):
                code = build.main(["build.py", "--check"])
            self.assertEqual(code, 0)
            self.assertIn("build --check OK (2 generated files in sync, version 1.2.3)", out.getvalue())

    def test_main_writes_outputs_removes_stale_and_reports_sizes(self):
        with tempfile.TemporaryDirectory() as d:
            dist = os.path.join(d, "dist")
            os.makedirs(dist)
            tpl = os.path.join(d, "dist", "SHAREABLE.html")
            css = os.path.join(dist, "commentable-html.css")
            eco = os.path.join(dist, "NONSHAREABLE.html")
            stale = os.path.join(dist, "commentable-html.v0.0.1.css")
            with open(stale, "w", encoding="utf-8") as fh:
                fh.write("stale")
            outputs = {tpl: "inline body", css: "css body", eco: "eco"}
            out = io.StringIO()
            with mock.patch.object(build, "HERE", d), mock.patch.object(build, "DIST", dist), \
                    mock.patch.object(build, "build_all", return_value=(outputs, "1.2.3")), \
                    mock.patch.object(build, "read_size_budget",
                                      return_value={os.path.join("dist", "SHAREABLE.html"): 1000,
                                                    os.path.join("dist", "commentable-html.css"): 1000,
                                                    os.path.join("dist", "NONSHAREABLE.html"): 1000}), \
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


class BuildOutputSafetyTests(unittest.TestCase):
    """CMH-BUILD-30: build output must not enter the development source trees."""

    def test_build_refuses_to_write_into_example_source_tree(self):
        with tempfile.TemporaryDirectory() as d:
            dev = os.path.join(d, "dev")
            examples_src = os.path.join(dev, "examples", "src")
            os.makedirs(examples_src)
            unsafe = [
                ["build.py"],
                ["build.py", "--out-dir", os.path.join(dev, "skill"),
                 "--examples-dir", examples_src],
                ["build.py", "--out-dir", os.path.join(dev, "skill"),
                 "--examples-dir", os.path.join(examples_src, "generated")],
                ["build.py", "--out-dir", os.path.join(dev, "skill"),
                 "--examples-dir", os.path.join(examples_src, "..", ".", "src")],
            ]
            for argv in unsafe:
                with self.subTest(argv=argv):
                    err = io.StringIO()
                    with mock.patch.object(build, "HERE", dev), \
                            mock.patch.object(build, "EXAMPLES_SRC", examples_src), \
                            mock.patch.object(
                                build, "build_all",
                                side_effect=AssertionError("unsafe build reached build_all")), \
                            contextlib.redirect_stderr(err):
                        with self.assertRaises(SystemExit) as cm:
                            build.main(argv)
                    self.assertEqual(cm.exception.code, 2)
                    self.assertIn("refusing to write build output into the development source root "
                                  "or example source tree",
                                  err.getvalue())
                    self.assertIn(
                        "python tools/build.py --assets-dir assets --out-dir skill "
                        "--pkg-dir ../pkg/skills/commentable-html --examples-dir ../examples",
                        err.getvalue())

    def test_build_refuses_default_out_dir_even_with_safe_examples(self):
        with tempfile.TemporaryDirectory() as d:
            dev = os.path.join(d, "dev")
            examples_src = os.path.join(dev, "examples", "src")
            safe_examples = os.path.join(d, "examples")
            os.makedirs(examples_src)
            with contextlib.redirect_stderr(io.StringIO()):
                with mock.patch.object(build, "HERE", dev), \
                        mock.patch.object(build, "EXAMPLES_SRC", examples_src), \
                        mock.patch.object(
                            build, "build_all",
                            side_effect=AssertionError("unsafe build reached build_all")):
                    with self.assertRaises(SystemExit) as cm:
                        build.main(["build.py", "--examples-dir", safe_examples])
            self.assertEqual(cm.exception.code, 2)

    def test_build_refuses_out_dir_inside_example_source_tree(self):
        with tempfile.TemporaryDirectory() as d:
            dev = os.path.join(d, "dev")
            examples_src = os.path.join(dev, "examples", "src")
            safe_examples = os.path.join(d, "examples")
            os.makedirs(examples_src)
            with contextlib.redirect_stderr(io.StringIO()):
                with mock.patch.object(build, "HERE", dev), \
                        mock.patch.object(build, "EXAMPLES_SRC", examples_src), \
                        mock.patch.object(
                            build, "build_all",
                            side_effect=AssertionError("unsafe build reached build_all")):
                    with self.assertRaises(SystemExit) as cm:
                        build.main([
                            "build.py",
                            "--out-dir", os.path.join(examples_src, "generated"),
                            "--examples-dir", safe_examples,
                        ])
            self.assertEqual(cm.exception.code, 2)

    def test_resolved_examples_alias_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            dev = os.path.join(d, "dev")
            examples_src = os.path.join(dev, "examples", "src")
            alias = os.path.join(d, "examples-alias")
            os.makedirs(examples_src)
            source_parent = os.path.dirname(examples_src)
            resolved_paths = [
                source_parent,
                source_parent,
                os.path.join(dev, "skill"),
                dev,
            ]

            with contextlib.redirect_stderr(io.StringIO()):
                with mock.patch.object(build, "HERE", dev), \
                        mock.patch.object(build, "EXAMPLES_SRC", examples_src), \
                        mock.patch.object(os.path, "realpath", side_effect=resolved_paths), \
                        mock.patch.object(
                            build, "build_all",
                            side_effect=AssertionError("unsafe build reached build_all")):
                    with self.assertRaises(SystemExit) as cm:
                        build.main([
                            "build.py",
                            "--out-dir", os.path.join(dev, "skill"),
                            "--examples-dir", alias,
                        ])
            self.assertEqual(cm.exception.code, 2)

    def test_unrelated_drive_is_not_treated_as_source_containment(self):
        with tempfile.TemporaryDirectory() as d:
            dev = os.path.join(d, "dev")
            examples_src = os.path.join(dev, "examples", "src")
            os.makedirs(examples_src)
            sentinel = RuntimeError("unrelated build reached build_all")
            with mock.patch.object(build, "HERE", dev), \
                    mock.patch.object(build, "EXAMPLES_SRC", examples_src), \
                    mock.patch.object(os.path, "commonpath", side_effect=ValueError), \
                    mock.patch.object(build, "build_all", side_effect=sentinel):
                with self.assertRaisesRegex(RuntimeError, str(sentinel)):
                    build.main([
                        "build.py",
                        "--out-dir", os.path.join(dev, "skill"),
                        "--examples-dir", os.path.join(d, "examples"),
                    ])

    def test_canonical_examples_destination_remains_allowed(self):
        with tempfile.TemporaryDirectory() as d:
            dev = os.path.join(d, "dev")
            examples_src = os.path.join(dev, "examples", "src")
            os.makedirs(examples_src)
            sentinel = RuntimeError("canonical build reached build_all")
            with mock.patch.object(build, "HERE", dev), \
                    mock.patch.object(build, "EXAMPLES_SRC", examples_src), \
                    mock.patch.object(build, "build_all", side_effect=sentinel):
                with self.assertRaisesRegex(RuntimeError, str(sentinel)):
                    build.main([
                        "build.py",
                        "--out-dir", os.path.join(dev, "skill"),
                        "--examples-dir", os.path.join(d, "examples"),
                    ])


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


class PackageTests(unittest.TestCase):
    """CMH-PKG-11: build.py assembles a deterministic skill-resources.zip and --check (check_package)
    catches drift in the zip contents or the shipped SKILL.md/LICENSE/THIRD_PARTY_NOTICES.md/hook stamps."""

    def test_resources_zip_is_deterministic(self):
        a = build.build_resources_zip_bytes(_paths.PKG)
        b = build.build_resources_zip_bytes(_paths.PKG)
        self.assertEqual(a, b, "the zip must be byte-identical for an unchanged source tree")

    def test_resources_zip_carries_each_path_exactly_once(self):
        # A freshly built zip and the COMMITTED shipped one must both carry every path once: a
        # duplicated member bloats the shipped artifact while a name->bytes map compares it equal.
        with zipfile.ZipFile(io.BytesIO(build.build_resources_zip_bytes(_paths.PKG))) as zf:
            fresh = [info.filename for info in zf.infolist()]
        self.assertEqual(len(fresh), len(set(fresh)),
                         sorted(n for n in set(fresh) if fresh.count(n) > 1))
        shipped = os.path.join(_paths.PKG_SHIPPED, build.PACKAGE_ZIP_NAME)
        if not os.path.isfile(shipped):
            self.skipTest("shipped skill-resources.zip not built yet")
        with zipfile.ZipFile(shipped) as zf:
            names = [info.filename for info in zf.infolist()]
        self.assertEqual(len(names), len(set(names)),
                         sorted(n for n in set(names) if names.count(n) > 1))

    def test_packager_rejects_duplicate_member_paths(self):
        # Fail closed rather than write a path twice, whatever produced the member list.
        with self.assertRaises(SystemExit):
            build._reject_duplicate_members([("dist/manifest.json", "a"), ("dist/manifest.json", "b")])

    def test_write_package_keeps_an_unchanged_zip_and_replaces_a_duplicated_one(self):
        # DEFLATE bytes are not identical across zlib builds, so an unchanged archive must be left
        # alone (no multi-MB churn on a host switch); a duplicated or corrupt one is replaced.
        import warnings
        v = build.read_version()
        with tempfile.TemporaryDirectory() as d:
            pkg = os.path.join(d, "pkg", "skills", "commentable-html")
            os.makedirs(pkg)
            build.write_package(_paths.PKG, pkg, v)
            zip_path = build.resources_zip_path(pkg)
            # A byte-different but logically identical archive (weaker per-member compression, which
            # is how another host's zlib would differ) is left as is.
            members = build._iter_zip_members(_paths.PKG)
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for rel, full in members:
                    info = zipfile.ZipInfo(rel, date_time=(1980, 1, 1, 0, 0, 0))
                    info.external_attr = 0o644 << 16
                    info.create_system = 3
                    info.compress_type = zipfile.ZIP_DEFLATED
                    zf.writestr(info, build._member_bytes(full), compresslevel=1)
            other = buf.getvalue()
            self.assertNotEqual(other, build.build_resources_zip_bytes(_paths.PKG),
                                "the fixture must differ in BYTES to prove no rewrite happened")
            with open(zip_path, "wb") as fh:
                fh.write(other)
            build.write_package(_paths.PKG, pkg, v)
            with open(zip_path, "rb") as fh:
                self.assertEqual(fh.read(), other, "an unchanged zip must not be rewritten")
            self.assertEqual(build.check_package(_paths.PKG, pkg, v), [])
            # A DUPLICATED archive is not "current" (the ValueError branch): it is replaced clean.
            buf = io.BytesIO()
            with warnings.catch_warnings():  # zipfile warns on each intentional duplicate
                warnings.simplefilter("ignore", UserWarning)
                with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                    for rel, full in members + members:
                        zf.writestr(rel, build._member_bytes(full))
            with open(zip_path, "wb") as fh:
                fh.write(buf.getvalue())
            build.write_package(_paths.PKG, pkg, v)
            with zipfile.ZipFile(zip_path) as zf:
                names = [info.filename for info in zf.infolist()]
            self.assertEqual(len(names), len(set(names)))
            self.assertEqual(build.check_package(_paths.PKG, pkg, v), [])
            # A CORRUPT archive (truncated central directory) is replaced too.
            with open(zip_path, "wb") as fh:
                fh.write(other[:-1])
            build.write_package(_paths.PKG, pkg, v)
            self.assertEqual(build.check_package(_paths.PKG, pkg, v), [])
            # A NONCANONICAL container - same contents, stored uncompressed - is replaced as well,
            # so a bloated archive cannot sit there merely because its logical members match.
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
                for rel, full in members:
                    info = zipfile.ZipInfo(rel, date_time=(1980, 1, 1, 0, 0, 0))
                    info.external_attr = 0o644 << 16
                    info.create_system = 3
                    zf.writestr(info, build._member_bytes(full))
            stored = buf.getvalue()
            with open(zip_path, "wb") as fh:
                fh.write(stored)
            build.write_package(_paths.PKG, pkg, v)
            with open(zip_path, "rb") as fh:
                self.assertNotEqual(fh.read(), stored, "a noncanonical container must be replaced")
            self.assertEqual(build.check_package(_paths.PKG, pkg, v), [])

    def test_resources_zip_is_current_treats_an_unreadable_archive_as_stale(self):
        # Reading a member can raise beyond a malformed container (RuntimeError for an encrypted
        # member, NotImplementedError for an unsupported method). Report stale, never crash.
        v = build.read_version()
        with tempfile.TemporaryDirectory() as d:
            pkg = os.path.join(d, "pkg", "skills", "commentable-html")
            os.makedirs(pkg)
            build.write_package(_paths.PKG, pkg, v)
            zip_path = build.resources_zip_path(pkg)
            fresh = build.build_resources_zip_bytes(_paths.PKG)
            self.assertTrue(build._resources_zip_is_current(zip_path, fresh))
            for exc in (RuntimeError("encrypted"), NotImplementedError("compression")):
                with mock.patch.object(build, "_zip_layout", side_effect=exc):
                    self.assertFalse(build._resources_zip_is_current(zip_path, fresh))

    def test_package_check_detects_zip_drift(self):
        v = build.read_version()
        with tempfile.TemporaryDirectory() as d:
            pkg = os.path.join(d, "pkg", "skills", "commentable-html")
            os.makedirs(pkg)
            build.write_package(_paths.PKG, pkg, v)
            self.assertEqual(build.check_package(_paths.PKG, pkg, v), [],
                             "a freshly packaged tree must be in sync")
            # A drift in a shipped text stamp is caught.
            with open(os.path.join(pkg, "SKILL.md"), "a", encoding="utf-8") as fh:
                fh.write("\nDRIFT\n")
            self.assertTrue(any("SKILL.md" in x for x in build.check_package(_paths.PKG, pkg, v)))
            # A drift in a zipped source file is caught by the CONTENT comparison.
            stage2 = os.path.join(d, "stage")
            shutil.copytree(_paths.PKG, stage2)
            ref = os.path.join(stage2, "references", "validation.md")
            with open(ref, "a", encoding="utf-8") as fh:
                fh.write("\nDRIFT\n")
            drift = build.check_package(stage2, pkg, v)
            self.assertTrue(any("skill-resources.zip" in x for x in drift),
                            "a changed zipped source file must be reported as zip drift")

    def test_member_bytes_normalizes_text_crlf_but_not_binary(self):
        with tempfile.TemporaryDirectory() as d:
            txt = os.path.join(d, "a.py")
            with open(txt, "wb") as fh:
                fh.write(b"line1\r\nline2\r\n")
            self.assertEqual(build._member_bytes(txt), b"line1\nline2\n",
                             "text members must be LF-normalized for a host-stable zip")
            png = os.path.join(d, "img.png")
            raw = b"\x89PNG\r\n\x1a\n\r\nbinary\r\n"
            with open(png, "wb") as fh:
                fh.write(raw)
            self.assertEqual(build._member_bytes(png), raw,
                             "binary members must be copied byte-for-byte (no CRLF rewrite)")

    def test_resources_zip_metadata_is_host_neutral(self):
        import io as _io
        with zipfile.ZipFile(_io.BytesIO(build.build_resources_zip_bytes(_paths.PKG))) as zf:
            for info in zf.infolist():
                self.assertEqual(info.create_system, 3, info.filename + ": create_system must be unix(3)")
                self.assertEqual(info.date_time, (1980, 1, 1, 0, 0, 0),
                                 info.filename + ": timestamp must be the fixed epoch")
                self.assertEqual(info.external_attr >> 16, 0o644,
                                 info.filename + ": mode must be a fixed 0o644")

    def test_packager_fails_on_missing_shipped_file(self):
        # A stage missing a required shipped file (SKILL.md/LICENSE/THIRD_PARTY_NOTICES.md) must fail closed, so --check and
        # write cannot silently leave a stale shipped copy in place.
        with tempfile.TemporaryDirectory() as d:
            stage = self._minimal_stage(d)  # has the 4 runtime dirs but no SKILL.md / LICENSE
            with self.assertRaises(SystemExit) as cm:
                build.package_text_stamps(stage, os.path.join(d, "pkg"), build.read_version())
            self.assertIn("SKILL.md", str(cm.exception))

    def test_packager_fails_on_missing_license(self):
        with tempfile.TemporaryDirectory() as d:
            stage = self._minimal_stage(d)
            with open(os.path.join(stage, "SKILL.md"), "w", encoding="utf-8") as fh:
                fh.write("# skill\n")
            with self.assertRaises(SystemExit) as cm:
                build.package_text_stamps(stage, os.path.join(d, "pkg"), build.read_version())
            self.assertIn("LICENSE", str(cm.exception))

    def test_packager_fails_on_missing_third_party_notices(self):
        # THIRD_PARTY_NOTICES.md is a required shipped file (MIT compliance): the packager must fail
        # closed if the stage lacks it, so a build can never ship the vendored libraries without them.
        with tempfile.TemporaryDirectory() as d:
            stage = self._minimal_stage(d)
            for name in ("SKILL.md", "LICENSE"):
                with open(os.path.join(stage, name), "w", encoding="utf-8") as fh:
                    fh.write("x\n")
            with self.assertRaises(SystemExit) as cm:
                build.package_text_stamps(stage, os.path.join(d, "pkg"), build.read_version())
            self.assertIn("THIRD_PARTY_NOTICES.md", str(cm.exception))

    def test_package_check_detects_hook_stamp_drift(self):
        v = build.read_version()
        with tempfile.TemporaryDirectory() as d:
            pkg = os.path.join(d, "pkg", "skills", "commentable-html")
            os.makedirs(pkg)
            hook = os.path.join(d, "pkg", "hooks.json")
            with open(hook, "w", encoding="utf-8") as fh:
                fh.write('{"cmd": ".skill-resources-0.0.1.ok --version 0.0.1"}\n')
            build.write_package(_paths.PKG, pkg, v)  # stamps the hook to the real version
            self.assertEqual(build.check_package(_paths.PKG, pkg, v), [])
            with open(hook, "w", encoding="utf-8") as fh:
                fh.write('{"cmd": ".skill-resources-0.0.1.ok --version 0.0.1"}\n')  # re-drift
            drift = build.check_package(_paths.PKG, pkg, v)
            self.assertTrue(any("hooks.json" in x for x in drift),
                            "a stale hook version stamp must be reported as drift")

    def test_check_package_reports_corrupt_zip(self):
        v = build.read_version()
        with tempfile.TemporaryDirectory() as d:
            pkg = os.path.join(d, "pkg", "skills", "commentable-html")
            os.makedirs(pkg)
            build.write_package(_paths.PKG, pkg, v)
            with open(os.path.join(pkg, "skill-resources.zip"), "wb") as fh:
                fh.write(b"not a zip")
            drift = build.check_package(_paths.PKG, pkg, v)
            self.assertTrue(any("invalid or corrupt" in x for x in drift))

    @staticmethod
    def _minimal_stage(d):
        """A minimal but COMPLETE stage: one file in every required runtime dir, so the packager's
        all-dirs-present guard is satisfied and a test can then perturb one thing in isolation."""
        stage = os.path.join(d, "skill")
        for sub in build.PACKAGE_BULKY_DIRS:
            os.makedirs(os.path.join(stage, sub))
            with open(os.path.join(stage, sub, "f.txt"), "w", encoding="utf-8") as fh:
                fh.write(sub + "\n")
        return stage

    def test_packager_rejects_missing_runtime_dir(self):
        with tempfile.TemporaryDirectory() as d:
            stage = self._minimal_stage(d)
            shutil.rmtree(os.path.join(stage, "references"))
            with self.assertRaises(SystemExit) as cm:
                build.build_resources_zip_bytes(stage)
            self.assertIn("references", str(cm.exception))

    def test_packager_rejects_empty_runtime_dir(self):
        with tempfile.TemporaryDirectory() as d:
            stage = self._minimal_stage(d)
            os.remove(os.path.join(stage, "vendor", "f.txt"))  # dir present but contributes nothing
            with self.assertRaises(SystemExit) as cm:
                build.build_resources_zip_bytes(stage)
            self.assertIn("vendor", str(cm.exception))

    def test_check_flags_duplicate_zip_member(self):
        v = build.read_version()
        with tempfile.TemporaryDirectory() as d:
            pkg = os.path.join(d, "pkg", "skills", "commentable-html")
            os.makedirs(pkg)
            build.write_package(_paths.PKG, pkg, v)
            # Rewrite the committed zip with a duplicated member name (which a name->bytes map would
            # silently collapse) and confirm --check refuses to treat it as in sync.
            zp = os.path.join(pkg, "skill-resources.zip")
            with zipfile.ZipFile(zp, "w") as zf:
                zf.writestr("tools/a.py", "one\n")
                zf.writestr("tools/a.py", "two\n")
            drift = build.check_package(_paths.PKG, pkg, v)
            self.assertTrue(any("duplicate member" in x for x in drift),
                            "a duplicated zip member must be reported, not silently collapsed")

    def test_packager_rejects_a_case_insensitive_member_collision(self):
        # `tools/X.py` and `tools/x.py` are distinct in git and in a ZIP on Linux, but extract to
        # ONE file on Windows and macOS, where the second silently overwrites the first. Fail
        # closed naming both paths rather than ship an archive that unpacks differently by OS
        # (CMH-PKG-15).
        with self.assertRaises(SystemExit) as cm:
            build._reject_duplicate_members([("tools/X.py", "a"), ("tools/x.py", "b")])
        self.assertIn("tools/X.py", str(cm.exception))
        self.assertIn("tools/x.py", str(cm.exception))

    def test_packager_rejects_a_unicode_normalization_member_collision(self):
        # Same failure mode one step further out: macOS normalizes filenames, so a precomposed and
        # a decomposed spelling of the same name are one file on extraction (CMH-PKG-15).
        with self.assertRaises(SystemExit):
            build._reject_duplicate_members([("docs/caf\u00e9.md", "a"),
                                             ("docs/cafe\u0301.md", "b")])

    def test_packager_allows_member_paths_that_cannot_collide(self):
        # The guard must not reject names that merely LOOK similar (CMH-PKG-15).
        members = [("tools/x.py", "a"), ("tools/xx.py", "b")]
        self.assertEqual(build._reject_duplicate_members(members), members)

    def test_a_zipfile_level_compresslevel_is_inert_for_zipinfo_members(self):
        # Why the packager passes no compresslevel: zipfile applies the ZipFile-level one only to
        # members written from a bare arcname, so with a manually constructed ZipInfo - what this
        # packager writes - every level yields IDENTICAL bytes. Only the per-member argument has
        # any effect, and it is deliberately not used (CMH-PKG-15).
        payload = b"deflate me, please. " * 500

        def pack(zipfile_level, member_level):
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED,
                                 compresslevel=zipfile_level) as zf:
                info = zipfile.ZipInfo("tools/x.py", date_time=(1980, 1, 1, 0, 0, 0))
                info.external_attr = 0o644 << 16
                info.create_system = 3
                info.compress_type = zipfile.ZIP_DEFLATED
                zf.writestr(info, payload, compresslevel=member_level)
            return buf.getvalue()

        self.assertEqual(pack(1, None), pack(9, None),
                         "a ZipFile-level compresslevel must be provably inert here")
        self.assertEqual(pack(None, None), pack(9, None))
        self.assertNotEqual(pack(None, None), pack(None, 1),
                            "only the PER-MEMBER level changes the bytes")

    def test_the_packager_claims_no_inert_compresslevel(self):
        # A level the writer cannot apply is a claim the code does not keep, and --check compares
        # the zip's LAYOUT and CONTENTS (never the compressed bytes, which vary with the host
        # zlib) so no level is even observable. Guard the source so it cannot come back
        # (CMH-PKG-15).
        import ast
        src = os.path.join(_paths.DEV_TOOLS, "build_parts", "40-package.py")
        with open(src, "r", encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=src)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name != "ZipFile":
                continue
            self.assertNotIn("compresslevel", [kw.arg for kw in node.keywords],
                             "zipfile.ZipFile(..., compresslevel=...) is inert for the ZipInfo "
                             "members this packager writes; pass it per member or not at all")

    def test_packager_rejects_a_collision_that_only_case_folding_decomposes(self):
        # Folding must be sandwiched between normalizations: casefold() can itself emit a
        # decomposed sequence, so NFC(name).casefold() gave these two canonically equivalent names
        # different keys and let the pair through (CMH-PKG-15).
        with self.assertRaises(SystemExit):
            build._reject_duplicate_members([("tools/\u015a.py", "a"),
                                             ("tools/\u017f\u0301.py", "b")])

    @unittest.skipUnless(os.name == "nt", "Windows directory junctions")
    def test_packager_packages_a_link_shared_between_two_bases(self):
        # The cycle guard is per-BASE: two runtime dirs reaching the same directory package it
        # under two different member prefixes, which is a DAG, not a loop, and must not be
        # mistaken for one (CMH-PKG-15).
        with tempfile.TemporaryDirectory() as d:
            stage = self._minimal_stage(d)
            rc = subprocess.run(["cmd", "/c", "mklink", "/J",
                                 os.path.join(stage, "vendor", "shared"),
                                 os.path.join(stage, "tools")],
                                capture_output=True, text=True)
            if rc.returncode != 0:
                self.skipTest("could not create a junction: " + rc.stderr.strip())
            rels = [rel for rel, _ in build._iter_zip_members(stage)]
            self.assertIn("tools/f.txt", rels)
            self.assertIn("vendor/shared/f.txt", rels)

    @unittest.skipUnless(os.name == "nt", "Windows directory junctions")
    def test_packager_rejects_a_junction_cycle(self):
        # A junction pointing at its own ancestor passes containment (it resolves INSIDE the stage)
        # but os.walk follows it, so the walk would recurse until the build died on the path
        # length. Reject a directory reached twice instead (CMH-PKG-15).
        with tempfile.TemporaryDirectory() as d:
            stage = self._minimal_stage(d)
            rc = subprocess.run(["cmd", "/c", "mklink", "/J",
                                 os.path.join(stage, "tools", "loop"), stage],
                                capture_output=True, text=True)
            if rc.returncode != 0:
                self.skipTest("could not create a junction: " + rc.stderr.strip())
            with self.assertRaises(SystemExit) as cm:
                build.build_resources_zip_bytes(stage)
            self.assertIn("cycle", str(cm.exception))

    @unittest.skipUnless(os.name == "nt", "Windows directory junctions")
    def test_packager_rejects_a_junction_input(self):
        # os.path.islink misses junctions; the packager's realpath containment must still reject one.
        with tempfile.TemporaryDirectory() as d:
            stage = self._minimal_stage(d)
            outside = os.path.join(d, "outside")
            os.makedirs(outside)
            with open(os.path.join(outside, "secret.txt"), "w", encoding="utf-8") as fh:
                fh.write("secret\n")
            junction = os.path.join(stage, "tools", "linked")
            rc = subprocess.run(["cmd", "/c", "mklink", "/J", junction, outside],
                                capture_output=True, text=True)
            if rc.returncode != 0:
                self.skipTest("could not create a junction: " + rc.stderr.strip())
            with self.assertRaises(SystemExit):
                build.build_resources_zip_bytes(stage)

    def test_packager_rejects_a_symlinked_input(self):
        with tempfile.TemporaryDirectory() as d:
            stage = self._minimal_stage(d)
            outside = os.path.join(d, "secret.txt")
            with open(outside, "w", encoding="utf-8") as fh:
                fh.write("secret\n")
            link = os.path.join(stage, "tools", "leak.txt")
            try:
                os.symlink(outside, link)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks not creatable in this environment")
            with self.assertRaises(SystemExit):
                build.build_resources_zip_bytes(stage)


class MermaidRerenderMirrorTests(unittest.TestCase):
    """CMH-MMD-12: the Export Offline re-init is a hand-written MIRROR of the shell mermaid loader.

    Both must carry the same render self-check contract - a pristine pre-render snapshot of every
    diagram element, the `window.__cmhMermaidRerender` repair hook, a re-published
    `window.__cmhMermaidReady`, and the label-mode restore - or an exported document silently loses
    the protection the live document has. Nothing else compares the two, so pin both that the shared
    steps are present AND that the two hook bodies stay STRUCTURALLY equivalent, which is what
    catches a step added to only one side.
    """

    # (name, shell spelling, offline spelling) for each step that must exist on BOTH sides.
    STEPS = (
        ("pristine snapshot map", "const pristine = new WeakMap();", "var pristine = new WeakMap();"),
        ("snapshot before render",
         "pristine.set(el, el.cloneNode(true))", "pristine.set(el, el.cloneNode(true))"),
        ("repair hook", "window.__cmhMermaidRerender =", "window.__cmhMermaidRerender ="),
        ("render from the snapshot, not serialized text",
         "src.cloneNode(true)", "src.cloneNode(true)"),
        ("label-mode switch", "initLabels(want)", "initLabels(want)"),
        ("readiness covers the repair", "window.__cmhMermaidReady = chain", "window.__cmhMermaidReady = chain"),
    )

    # Spellings that legitimately differ between an ES-module loader and the emitted ES5 string.
    NORMALIZE = (
        ("() => false", "() => { return false; }"),
        ("window.mermaid.run", "m.run"),
        ("var ", "const "),
        ("let ", "const "),
        ("function (", "("),
        (") =>", ")"),
        ("initLabels(base)", "initLabels(htmlLabels)"),
        ("'", '"'),
    )
    # Applied after whitespace is stripped. The offline bootstrap has no enclosing `htmlLabels`
    # const to close over (it re-derives the document's default label mode per call), so that one
    # extra statement is dropped rather than treated as drift.
    POST_NORMALIZE = ('constbase=!document.querySelector(".deck-stage");',)

    def setUp(self):
        self.shell = _read(os.path.join(_paths.ASSETS, "template.shell.html"))
        self.offline = _read(os.path.join(_paths.ASSETS, "js", "68-export-offline.js"))

    @staticmethod
    def _offline_bootstrap(text):
        """Join the emitted mermaid re-init back into the script it becomes at export time."""
        # Anchor on the bootstrap's own FIRST LINE, not on the emitting call: since 1.837.0 the
        # exporter emits a second `(function(){` block through the same helper (the Chart.js
        # defaults shim), so the call spelling alone no longer identifies this one.
        start = text.index('"  if (!window.mermaid || !window.mermaid.initialize')
        start = text.rindex('"(function(){', 0, start)
        end = text.index('{ "data-cmh-offline-lib-init": "mermaid" }', start)
        parts = re.findall(r'^\s*\+?\s*"((?:[^"\\]|\\.)*)"\s*$', text[start:end], re.M)
        if not parts:
            raise AssertionError("could not extract the offline mermaid bootstrap string")
        return "".join(p.encode().decode("unicode_escape") for p in parts)

    @classmethod
    def _hook_body(cls, text):
        """The `window.__cmhMermaidRerender` body, normalized to a comparable token sequence."""
        start = text.index("window.__cmhMermaidRerender =")
        depth, i, opened = 0, text.index("{", start), False
        while i < len(text):
            if text[i] == "{":
                depth += 1
                opened = True
            elif text[i] == "}":
                depth -= 1
                if opened and depth == 0:
                    break
            i += 1
        body = text[start:i + 1]
        body = re.sub(r"//[^\n]*", "", body)
        for src, dst in cls.NORMALIZE:
            body = body.replace(src, dst)
        body = re.sub(r"\s+", "", body)
        for drop in cls.POST_NORMALIZE:
            body = body.replace(drop, "")
        return body

    def test_offline_reinit_mirrors_the_shell_rerender_hook_cmh_mmd_12(self):
        for name, shell_spelling, offline_spelling in self.STEPS:
            with self.subTest(step=name):
                self.assertIn(shell_spelling, self.shell,
                              "the shell mermaid loader lost its %s" % name)
                self.assertIn(offline_spelling, self.offline,
                              "the Export Offline re-init lost its %s" % name)

    def test_offline_rerender_hook_is_structurally_identical_cmh_mmd_12(self):
        # A substring check only catches a REMOVED step; this catches a step added to one side, a
        # reordering, or a changed argument, which is the drift a hand-written mirror actually risks.
        shell_body = self._hook_body(self.shell)
        offline_body = self._hook_body(self._offline_bootstrap(self.offline))
        self.assertEqual(
            offline_body, shell_body,
            "the Export Offline mermaid re-render hook has drifted from the shell loader's; keep "
            "the two bodies in step (see CMH-MMD-12)")

    def test_neither_loader_rerenders_from_serialized_text_cmh_mmd_12(self):
        # mermaid reads a diagram from innerHTML (it normalizes `<br/>` in a node label), so
        # re-rendering from a textContent round-trip would drop the authored line breaks and produce
        # a DIFFERENT diagram. Both loaders must snapshot the element itself instead, so pin the
        # shapes an actual regression would take.
        offline_script = self._offline_bootstrap(self.offline)
        for name, text in (("shell", self.shell), ("offline", offline_script)):
            with self.subTest(loader=name):
                self.assertNotIn("pristine.set(el, el.textContent", text)
                self.assertNotIn("pristine.set(el, el.innerHTML", text)
                hook = self._hook_body(text)
                self.assertNotIn(".textContent)", hook)
                self.assertNotIn("data-cmh-md-src", hook)
                self.assertIn("src.cloneNode(true)", hook)


class ReleaseDateTests(unittest.TestCase):
    """read_release_date single-sources the examples' 'Generated on' build date from the dated
    CHANGELOG heading, deterministically (CMH-BUILD-15)."""

    def _changelog(self, body):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        path = os.path.join(d, "CHANGELOG.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)
        return path

    def test_reads_iso_date_of_the_current_version_heading(self):
        path = self._changelog(
            "# Changelog\n\n## [1.245.0] - 2026-07-25\n\n### Fixed\n\n- x\n\n"
            "## [1.244.0] - 2026-07-20\n")
        self.assertEqual(build.read_release_date("1.245.0", path), "2026-07-25")
        self.assertEqual(build.read_release_date("1.244.0", path), "2026-07-20")

    def test_missing_or_undated_heading_fails_loudly(self):
        # A version with no heading, and a heading with no date, both hard-fail so a bump that forgets
        # the CHANGELOG date cannot silently ship a wrong "Generated on" line.
        undated = self._changelog("# Changelog\n\n## [1.245.0]\n")
        with self.assertRaises(SystemExit):
            build.read_release_date("1.245.0", undated)
        with self.assertRaises(SystemExit):
            build.read_release_date("9.9.9", undated)

    def test_date_must_be_on_the_heading_line_not_a_following_bullet(self):
        # The date is matched with horizontal whitespace only, so an undated heading followed by a
        # bullet that is exactly a date does not leak across the newline into a false match (the old
        # `\s*` regex, which spans newlines, WOULD have matched this bullet).
        leaky = self._changelog("# Changelog\n\n## [1.245.0]\n\n- 2026-07-25\n")
        with self.assertRaises(SystemExit):
            build.read_release_date("1.245.0", leaky)

    def test_calendar_invalid_date_fails_loudly(self):
        bad = self._changelog("# Changelog\n\n## [1.245.0] - 2026-99-99\n")
        with self.assertRaises(SystemExit):
            build.read_release_date("1.245.0", bad)

    def test_committed_changelog_has_a_date_for_the_current_version(self):
        version = build.read_version()
        self.assertRegex(build.read_release_date(version), r"^\d{4}-\d{2}-\d{2}$")


class StampGeneratedDateTests(unittest.TestCase):
    """_stamp_generated_date targets the real content root and is quote/idempotent-safe (CMH-BUILD-15)."""

    def test_replaces_an_authored_date_in_place(self):
        text = '<main id="commentRoot" data-generated="2014-12-31">x</main>'
        out = build._stamp_generated_date(text, "2026-07-25")
        self.assertEqual(out, '<main id="commentRoot" data-generated="2026-07-25">x</main>')

    def test_adds_the_attribute_when_absent(self):
        text = '<main id="commentRoot">x</main>'
        out = build._stamp_generated_date(text, "2026-07-25")
        self.assertEqual(out, '<main data-generated="2026-07-25" id="commentRoot">x</main>')

    def test_targets_root_before_content_marker_not_a_decoy(self):
        # A decoy <main id="commentRoot"> AFTER the CONTENT marker (e.g. in authored example content)
        # must not be stamped instead of the real container root before the marker.
        real = '<main id="commentRoot" data-generated="2014-12-31">'
        decoy = '<main id="commentRoot">'
        text = real + "\n// BEGIN: commentable-html - CONTENT\nbody " + decoy + " more"
        out = build._stamp_generated_date(text, "2026-07-25")
        self.assertIn('<main id="commentRoot" data-generated="2026-07-25">', out)
        self.assertTrue(out.endswith("body " + decoy + " more"))
        self.assertEqual(out.count("data-generated="), 1)

    def test_empty_date_is_a_noop(self):
        text = '<main id="commentRoot">x</main>'
        self.assertEqual(build._stamp_generated_date(text, None), text)
        self.assertEqual(build._stamp_generated_date(text, ""), text)


if __name__ == "__main__":
    unittest.main()
