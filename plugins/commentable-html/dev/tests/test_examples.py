import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402  shared pkg/dev split path constants
SKILL = _paths.PKG
EXAMPLE = os.path.join(SKILL, "examples", "report-community-garden.html")
TAXI = os.path.join(SKILL, "examples", "report-taxi.html")
BUILD_PY = os.path.join(_paths.DEV_TOOLS, "build.py")


def _read_version():
    with open(os.path.join(_paths.DEV, "VERSION"), encoding="utf-8") as fh:
        return fh.read().strip()


class ExampleTests(unittest.TestCase):
    def test_example_exists(self):
        self.assertTrue(os.path.isfile(EXAMPLE), "examples/report-community-garden.html is missing")

    def test_example_validates_clean(self):
        r = subprocess.run(
            [sys.executable, os.path.join(SKILL, "tools", "validate.py"), EXAMPLE],
            capture_output=True, text=True, cwd=SKILL)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertRegex(r.stdout, r"\b0 warning")

    def test_example_images_are_inlined_and_self_contained(self):
        html = open(EXAMPLE, encoding="utf-8").read()
        srcs = re.findall(r'<img\b[^>]*\bsrc\s*=\s*"([^"]*)"', html)
        self.assertTrue(srcs, "the example should contain images")
        for s in srcs:
            self.assertTrue(s.startswith("data:"), "example image not inlined (still references a file): " + s)

    def test_example_data_doc_source_matches_shipped_filename(self):
        # After the file renames, each example's data-doc-source must name the file that
        # actually ships (a stale value hands an agent a filename removed by this batch).
        for path in (EXAMPLE, TAXI):
            html = open(path, encoding="utf-8").read()
            m = re.search(r'data-doc-source="([^"]*)"', html)
            self.assertIsNotNone(m, "example is missing data-doc-source: " + path)
            self.assertEqual(m.group(1), os.path.basename(path),
                             "data-doc-source does not match the shipped filename in " + path)
            self.assertTrue(os.path.isfile(os.path.join(SKILL, "examples", m.group(1))),
                            "data-doc-source names a file that does not exist: " + m.group(1))

    def test_example_exercises_every_feature(self):
        html = open(EXAMPLE, encoding="utf-8").read()
        self.assertIn('class="cm-toc"', html)                 # author TOC (drives the side menu)
        self.assertRegex(html, r'<h2 id=')                    # sectioned headings
        self.assertIn("dataexplorer.azure.com", html)         # Run in Azure Data Explorer link
        self.assertIn("<canvas", html)                        # Chart.js chart
        self.assertIn('class="mermaid cm-skip"', html)        # mermaid diagram(s)
        self.assertIn('class="cmh-diff"', html)               # code-review diff
        self.assertIn("<table", html)                         # tables
        self.assertIn('class="cmh-code-kw"', html)            # highlighted code block

    def test_examples_embed_current_version(self):
        # The examples embed the WHOLE layer, so a version bump must re-stamp them. Both
        # the <meta> and the runtime CMH_VERSION const must equal dev/VERSION.
        version = _read_version()
        for path in (EXAMPLE, TAXI):
            html = open(path, encoding="utf-8").read()
            meta = re.search(r'<meta name="commentable-html-version" content="([0-9.]+)"', html)
            const = re.search(r'const CMH_VERSION = "([0-9.]+)"', html)
            self.assertIsNotNone(meta, "no version <meta> in " + os.path.basename(path))
            self.assertIsNotNone(const, "no CMH_VERSION const in " + os.path.basename(path))
            self.assertEqual(meta.group(1), version,
                             "%s <meta> version is stale (run build.py)" % os.path.basename(path))
            self.assertEqual(const.group(1), version,
                             "%s CMH_VERSION is stale (run build.py)" % os.path.basename(path))

    def test_build_check_catches_example_drift(self):
        # Regenerate a self-contained temp tree, confirm --check passes, then poison an
        # example's embedded layer version and confirm --check flags the example (proving
        # build.py's --check now covers the examples, not just dist/).
        with tempfile.TemporaryDirectory() as d:
            assets = os.path.join(d, "assets")
            out_dir = os.path.join(d, "skill")
            shutil.copytree(_paths.ASSETS, assets)
            shutil.copytree(_paths.DIST, os.path.join(out_dir, "dist"))
            shutil.copytree(_paths.EXAMPLES, os.path.join(out_dir, "examples"))
            base = [sys.executable, BUILD_PY, "--assets-dir", assets, "--out-dir", out_dir]
            self.assertEqual(subprocess.run(base + ["--check"], capture_output=True, text=True).returncode, 0,
                             "freshly copied tree should be in sync")
            taxi = os.path.join(out_dir, "examples", "report-taxi.html")
            html = open(taxi, encoding="utf-8").read()
            poisoned = html.replace('const CMH_VERSION = "', 'const CMH_VERSION = "0.0.0"; //', 1)
            self.assertNotEqual(poisoned, html, "could not poison the example CMH_VERSION")
            with open(taxi, "w", encoding="utf-8", newline="") as fh:
                fh.write(poisoned)
            r = subprocess.run(base + ["--check"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertIn("report-taxi.html", r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
