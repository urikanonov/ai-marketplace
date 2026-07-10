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


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.outputs, self.version = build.build_all()

    # -- single source of truth -------------------------------------------- #
    def test_check_subprocess_passes(self):
        r = subprocess.run(
            [sys.executable, BUILD_PY, "--check", "--assets-dir", _paths.ASSETS, "--out-dir", ROOT],
            capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

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
        css, js, shell, _v = build.load_sources()
        rebuilt = build.build_inline(css, js, shell)
        self.assertEqual(rebuilt, _read(os.path.join(ROOT, "dist", "PORTABLE.html")))

    # -- versioning / manifest --------------------------------------------- #
    def test_version_is_single_sourced(self):
        js = _read(os.path.join(build.ASSETS, "commentable-html.js"))
        m = re.search(r'const\s+CMH_VERSION\s*=\s*"([\d.]+)"', js)
        self.assertTrue(m)
        v = m.group(1)
        manifest = json.loads(_read(os.path.join(DIST, "manifest.json")))
        self.assertEqual(manifest["version"], v)
        for name in manifest["files"]:
            self.assertIn(".v%s." % v, name)
        eco = _read(os.path.join(DIST, "NONPORTABLE.html"))
        self.assertIn('content="%s"' % v, eco)

    def test_manifest_hashes_match_dist_files(self):
        manifest = json.loads(_read(os.path.join(DIST, "manifest.json")))
        for name, meta in manifest["files"].items():
            content = _read(os.path.join(DIST, name))
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            self.assertEqual(meta["sha256"], digest, "hash mismatch for %s" % name)

    # -- asset registry (Export standalone payload) ------------------------ #
    def test_registry_has_no_raw_script_close(self):
        reg = _read(os.path.join(DIST, "commentable-html.v%s.assets.js" % self.version))
        self.assertIsNone(re.search(r"</\s*script", reg, re.IGNORECASE),
                          "assets registry must not contain a raw </script>")

    def test_registry_payload_matches_companion_files(self):
        reg = _read(os.path.join(DIST, "commentable-html.v%s.assets.js" % self.version))
        obj = json.loads(re.search(r"=\s*(\{.*\})\s*;", reg, re.S).group(1))
        css = _read(os.path.join(DIST, "commentable-html.v%s.css" % self.version)).rstrip("\n")
        js = _read(os.path.join(DIST, "commentable-html.v%s.js" % self.version)).rstrip("\n")
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

    # -- diff / code-review layer ships in the generated artifacts --------- #
    def test_diff_layer_present_in_artifacts(self):
        tpl = _read(os.path.join(ROOT, "dist", "PORTABLE.html"))
        self.assertIn('class="cmh-diff"', tpl, "diff demo block missing from dist/PORTABLE.html")
        self.assertIn("setupDiffLayer", tpl, "diff runtime missing from inline dist/PORTABLE.html")
        self.assertIn("cmh-diff-view", tpl, "diff CSS missing from inline dist/PORTABLE.html")
        eco_js = _read(os.path.join(DIST, "commentable-html.v%s.js" % self.version))
        self.assertIn("setupDiffLayer", eco_js, "diff runtime missing from nonportable companion JS")
        eco_css = _read(os.path.join(DIST, "commentable-html.v%s.css" % self.version))
        self.assertIn("cmh-diff-view", eco_css, "diff CSS missing from nonportable companion CSS")

    # -- stale-artifact detection ------------------------------------------ #
    def test_stale_dist_files_are_detected(self):
        # A companion from an older version, not in the current build, is flagged.
        with tempfile.TemporaryDirectory() as d:
            for name in ("commentable-html.v9.9.9.css", "commentable-html.v2.5.0.css"):
                with open(os.path.join(d, name), "w", encoding="utf-8") as fh:
                    fh.write("x")
            orig = build.DIST
            try:
                build.DIST = d
                expected = [os.path.join(d, "commentable-html.v2.5.0.css")]
                stale = build._unexpected_dist_files(expected)
            finally:
                build.DIST = orig
        self.assertEqual(stale, ["commentable-html.v9.9.9.css"])

    def test_version_must_be_single_declaration(self):
        # Two CMH_VERSION declarations must fail the build loudly.
        js = 'const CMH_VERSION = "2.5.0";\nconst CMH_VERSION = "2.6.0";\n'
        with mock.patch.object(build, "read", side_effect=lambda p: js if p.endswith(".js") else "x{{CMH_CSS}}{{CMH_JS}}"):
            with self.assertRaises(SystemExit):
                build.load_sources()

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
            build.build_inline("css", "js", "<style>{{CMH_CSS}}</style>")
        self.assertIn("missing a placeholder", str(cm.exception))

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
            (shell.replace("BEGIN: commentable-html v2 - CSS", "BEGIN: broken CSS", 1), "CSS region"),
            (shell.replace("</style>\n</head>", "</style></head>", 1), "</style></head>"),
            (shell.replace("BEGIN: commentable-html v2 - JS", "BEGIN: broken JS", 1), "JS region"),
            (no_body_shell, "<body> tag"),
            (shell + "\n{{CMH_LEFT}}\n", "unresolved placeholder"),
        ]
        for bad_shell, message in cases:
            with self.subTest(message=message):
                with self.assertRaises(SystemExit) as cm:
                    build.build_nonportable(bad_shell, version)
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
                    contextlib.redirect_stdout(out):
                code = build.main(["build.py", "--check"])
            self.assertEqual(code, 0)
            self.assertIn("build --check OK (2 generated files in sync, version 1.2.3)", out.getvalue())

    def test_main_writes_outputs_removes_stale_and_reports_sizes(self):
        with tempfile.TemporaryDirectory() as d:
            dist = os.path.join(d, "dist")
            os.makedirs(dist)
            tpl = os.path.join(d, "dist", "PORTABLE.html")
            css = os.path.join(dist, "commentable-html.v1.2.3.css")
            eco = os.path.join(dist, "NONPORTABLE.html")
            stale = os.path.join(dist, "commentable-html.v0.0.1.css")
            with open(stale, "w", encoding="utf-8") as fh:
                fh.write("stale")
            outputs = {tpl: "inline body", css: "css body", eco: "eco"}
            out = io.StringIO()
            with mock.patch.object(build, "HERE", d), mock.patch.object(build, "DIST", dist), \
                    mock.patch.object(build, "build_all", return_value=(outputs, "1.2.3")), \
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
        argv = [BUILD_PY, "--check", "--assets-dir", _paths.ASSETS, "--out-dir", ROOT]
        with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(out):
            with self.assertRaises(SystemExit) as cm:
                runpy.run_path(BUILD_PY, run_name="__main__")
        self.assertEqual(cm.exception.code, 0)
        self.assertIn("build --check OK", out.getvalue())


if __name__ == "__main__":
    unittest.main()
