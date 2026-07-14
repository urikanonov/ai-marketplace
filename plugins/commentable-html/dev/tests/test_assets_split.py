#!/usr/bin/env python3
"""Assembly-integrity and structural-invariant tests for the split commentable-html sources.

The runtime and layer CSS ship as `NN-topic.{js,css}` partials that `build.py` concatenates by
directory sort. These tests lock the invariants that make a cut-only, byte-identical split safe
(GH: modularization multi-duck panel):
- the assembled JS is ONE arrow-IIFE (opener in the first partial, closer in the last);
- the preamble that captures SNAPSHOT_HTML / document.currentScript stays FIRST;
- the numbered-partial directory sort is deterministic, non-empty, and rejects stray files;
- exactly one partial declares CMH_VERSION (so build.py stamps exactly one place);
- build_all honors a passed --assets-dir (not a vacuous default);
- the deleted monoliths cannot silently return.
"""
import os
import re
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402
sys.path.insert(0, _paths.DEV_TOOLS)
import build  # noqa: E402

build.ASSETS = _paths.ASSETS
ASSETS = _paths.ASSETS


class AssemblyIntegrityTests(unittest.TestCase):
    def test_assembled_js_is_one_arrow_iife(self):
        _css, js, _shell, _v = build.load_sources(ASSETS)
        self.assertTrue(js.startswith("(() => {"), "assembled JS must open the arrow IIFE")
        self.assertTrue(js.rstrip().endswith("})();"), "assembled JS must close the arrow IIFE")
        # Exactly one column-0 arrow-IIFE opener (inner IIFEs are `(function () {` and/or indented).
        self.assertEqual(len(re.findall(r"(?m)^\(\(\) => \{", js)), 1,
                         "assembled JS must contain exactly one top-level arrow IIFE wrapper")

    def test_preamble_partial_is_first_and_captures_the_snapshot(self):
        parts = build.ordered_parts(ASSETS, "js")
        first = os.path.basename(parts[0])
        self.assertEqual(first, "00-preamble.js", "the preamble partial must sort first")
        text = build.read(parts[0])
        self.assertIn("SNAPSHOT_HTML", text)
        self.assertIn("currentScript", text)
        # No earlier partial touches the DOM before the snapshot line - the preamble IS first, and
        # its snapshot capture precedes any other partial by construction.
        self.assertTrue(text.index("(() => {") < text.index("SNAPSHOT_HTML"))

    def test_ordered_parts_are_sorted_nonempty_and_named(self):
        for ext in ("js", "css"):
            parts = build.ordered_parts(ASSETS, ext)
            self.assertTrue(parts, "no %s partials found" % ext)
            names = [os.path.basename(p) for p in parts]
            self.assertEqual(names, sorted(names), "%s partials must be in sorted order" % ext)
            for p in parts:
                self.assertRegex(os.path.basename(p), r"^\d\d+-[a-z0-9-]+\." + ext + r"$")
                self.assertTrue(build.read(p).strip(), "%s is empty" % p)

    def test_ordered_parts_rejects_a_stray_unnumbered_file(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        os.makedirs(os.path.join(tmp, "js"))
        with open(os.path.join(tmp, "js", "00-a.js"), "w", encoding="utf-8") as fh:
            fh.write("x")
        with open(os.path.join(tmp, "js", "helpers.js"), "w", encoding="utf-8") as fh:
            fh.write("y")
        with self.assertRaises(SystemExit):
            build.ordered_parts(tmp, "js")

    def test_exactly_one_js_partial_declares_cmh_version(self):
        with_version = [p for p in build.ordered_parts(ASSETS, "js")
                        if re.search(r'CMH_VERSION\s*=\s*"', build.read(p))]
        self.assertEqual(len(with_version), 1,
                         "exactly one JS partial must declare CMH_VERSION (build.py stamps it)")
        # _js_version_part resolves to that partial and _stamp_const finds exactly one match there.
        vp = build._js_version_part(ASSETS)
        self.assertEqual(vp, with_version[0])
        stamped = build._stamp_const(build.read(vp), "9.9.9", os.path.basename(vp))
        self.assertIn('CMH_VERSION = "9.9.9"', stamped)

    def test_build_all_reads_the_passed_assets_dir_not_the_default(self):
        # Sentinel: copy the real partial dirs into a temp assets tree, inject a unique marker into a
        # CSS partial there, and confirm the built PORTABLE.html reflects the temp tree - proving the
        # build honors --assets-dir rather than vacuously reading the canonical default.
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        assets = os.path.join(tmp, "assets")
        out_dir = os.path.join(tmp, "skill")
        os.makedirs(assets)
        shutil.copytree(os.path.join(ASSETS, "js"), os.path.join(assets, "js"))
        shutil.copytree(os.path.join(ASSETS, "css"), os.path.join(assets, "css"))
        shutil.copy2(os.path.join(ASSETS, "template.shell.html"),
                     os.path.join(assets, "template.shell.html"))
        marker = "/* SENTINEL-MARKER-xyz */"
        base_css = os.path.join(assets, "css", "00-base.css")
        with open(base_css, "a", encoding="utf-8") as fh:
            fh.write("\n" + marker + "\n")
        outputs, _v = build.build_all(assets, out_dir)
        portable = outputs[os.path.join(out_dir, "dist", "PORTABLE.html")]
        self.assertIn(marker, portable, "build_all did not read the passed --assets-dir")

    def test_the_monolith_sources_do_not_exist(self):
        # Cement "work in split mode": the old single-file sources must never return (a stale rebase
        # or a copy-paste-back-into-one-file would reintroduce the whole-file clobber class).
        self.assertFalse(os.path.exists(os.path.join(ASSETS, "commentable-html.js")),
                         "dev/assets/commentable-html.js must not exist - edit assets/js/ partials")
        self.assertFalse(os.path.exists(os.path.join(ASSETS, "commentable-html.css")),
                         "dev/assets/commentable-html.css must not exist - edit assets/css/ partials")


if __name__ == "__main__":
    unittest.main()
