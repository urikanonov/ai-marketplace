import os
import re
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402  shared pkg/dev split path constants
SKILL = _paths.PKG
EXAMPLE = os.path.join(SKILL, "examples", "report-community-garden.html")
TAXI = os.path.join(SKILL, "examples", "report-taxi.html")


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


if __name__ == "__main__":
    unittest.main()
