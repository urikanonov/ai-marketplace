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
TRIAGE = os.path.join(SKILL, "examples", "report-triage.html")
METRICS = os.path.join(SKILL, "examples", "report-metrics.html")
EXAMPLES = (EXAMPLE, TAXI, TRIAGE, METRICS)
BUILD_PY = os.path.join(_paths.DEV_TOOLS, "build.py")


def _read_version():
    with open(os.path.join(_paths.DEV, "VERSION"), encoding="utf-8") as fh:
        return fh.read().strip()


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _report_paths():
    ex_dir = _paths.EXAMPLES
    return sorted(
        os.path.join(ex_dir, name) for name in os.listdir(ex_dir)
        if name.startswith("report-") and name.endswith(".html"))


def _companion_prompt(report_path):
    stem = os.path.basename(report_path)[len("report-"):-len(".html")]
    return os.path.join(_paths.EXAMPLES, "prompt-" + stem + ".md")


def _active_root_attr(html, attr):
    matches = list(re.finditer(r'<main\b[^>]*\bid="commentRoot"[^>]*\b' + re.escape(attr) + r'="([^"]*)"', html))
    if not matches:
        matches = list(re.finditer(r'<main\b[^>]*\b' + re.escape(attr) + r'="([^"]*)"[^>]*\bid="commentRoot"', html))
    return matches[-1].group(1) if matches else None


class ExampleTests(unittest.TestCase):
    def test_example_exists(self):
        for path in EXAMPLES:
            self.assertTrue(os.path.isfile(path), "example is missing: " + os.path.basename(path))

    def test_example_validates_clean(self):
        r = subprocess.run(
            [sys.executable, os.path.join(SKILL, "tools", "validate.py"), *EXAMPLES],
            capture_output=True, text=True, cwd=SKILL)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertRegex(r.stdout, r"\b0 warning")

    def test_example_images_are_inlined_and_self_contained(self):
        html = _read(EXAMPLE)
        srcs = re.findall(r'<img\b[^>]*\bsrc\s*=\s*"([^"]*)"', html)
        self.assertTrue(srcs, "the example should contain images")
        for s in srcs:
            self.assertTrue(s.startswith("data:"), "example image not inlined (still references a file): " + s)

    def test_example_data_doc_source_matches_shipped_filename(self):
        # After the file renames, each example's data-doc-source must name the file that
        # actually ships (a stale value hands an agent a filename removed by this batch).
        for path in EXAMPLES:
            html = _read(path)
            source = _active_root_attr(html, "data-doc-source")
            self.assertIsNotNone(source, "example is missing data-doc-source: " + path)
            self.assertEqual(source, os.path.basename(path),
                             "data-doc-source does not match the shipped filename in " + path)
            self.assertTrue(os.path.isfile(os.path.join(SKILL, "examples", source)),
                            "data-doc-source names a file that does not exist: " + source)

    def test_example_exercises_every_feature(self):
        html = _read(EXAMPLE)
        self.assertIn('class="cm-toc"', html)                 # author TOC (drives the side menu)
        self.assertRegex(html, r'<h2 id=')                    # sectioned headings
        self.assertIn("dataexplorer.azure.com", html)         # Run in Azure Data Explorer link
        self.assertIn("<canvas", html)                        # Chart.js chart
        self.assertIn('class="mermaid cm-skip"', html)        # mermaid diagram(s)
        self.assertIn('class="cmh-diff"', html)               # code-review diff
        self.assertIn("<table", html)                         # tables
        self.assertIn('class="cmh-code-kw"', html)            # highlighted code block

    def test_new_showcase_examples_cover_triage_and_visuals(self):
        triage = _read(TRIAGE)
        self.assertIn('data-cm-widget="incident-triage-board"', triage)
        for slot in ("New", "Investigating", "Fixed"):
            self.assertIn('data-cm-slot="' + slot + '"', triage)
        self.assertIn('data-cm-part-label="API saturation"', triage)
        self.assertIn("<table", triage)
        self.assertIn("<canvas", triage)

        metrics = _read(METRICS)
        for snippet in ("flowchart LR", "sequenceDiagram", "gantt", "stateDiagram-v2",
                        "classDiagram", "erDiagram", "pie title"):
            self.assertIn(snippet, metrics)
        for canvas_id in ("metricsBarChart", "metricsLineChart", "metricsPieChart", "metricsDoughnutChart"):
            self.assertIn('id="' + canvas_id + '"', metrics)
        self.assertIn('class="cmh-diff"', metrics)
        self.assertIn('class="cmh-kql"', metrics)

    def test_examples_have_unique_comment_keys(self):
        keys = {}
        for path in EXAMPLES:
            html = _read(path)
            key = _active_root_attr(html, "data-comment-key")
            self.assertIsNotNone(key, "example is missing data-comment-key: " + path)
            keys.setdefault(key, []).append(os.path.basename(path))
        dupes = {k: v for k, v in keys.items() if len(v) > 1}
        self.assertEqual(dupes, {})

    def test_examples_embed_current_version(self):
        # The examples embed the WHOLE layer, so a version bump must re-stamp them. Both
        # the <meta> and the runtime CMH_VERSION const must equal dev/VERSION.
        version = _read_version()
        for path in EXAMPLES:
            html = _read(path)
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
            html = _read(taxi)
            poisoned = html.replace('const CMH_VERSION = "', 'const CMH_VERSION = "0.0.0"; //', 1)
            self.assertNotEqual(poisoned, html, "could not poison the example CMH_VERSION")
            with open(taxi, "w", encoding="utf-8", newline="") as fh:
                fh.write(poisoned)
            r = subprocess.run(base + ["--check"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertIn("report-taxi.html", r.stdout + r.stderr)

    def test_build_check_flags_an_orphaned_example_with_no_source(self):
        # A shipped example with NO dev/examples/src source is a pure artifact validated against
        # nothing; --check must flag it as orphaned instead of silently ignoring it (build_examples
        # only assembles examples that have a source).
        with tempfile.TemporaryDirectory() as d:
            assets = os.path.join(d, "assets")
            out_dir = os.path.join(d, "skill")
            shutil.copytree(_paths.ASSETS, assets)
            shutil.copytree(_paths.DIST, os.path.join(out_dir, "dist"))
            shutil.copytree(_paths.EXAMPLES, os.path.join(out_dir, "examples"))
            base = [sys.executable, BUILD_PY, "--assets-dir", assets, "--out-dir", out_dir]
            self.assertEqual(subprocess.run(base + ["--check"], capture_output=True, text=True).returncode, 0,
                             "freshly copied tree should be in sync")
            # A shipped example that has no counterpart under dev/examples/src/.
            orphan = os.path.join(out_dir, "examples", "report-orphan.html")
            shutil.copyfile(os.path.join(out_dir, "examples", "report-taxi.html"), orphan)
            r = subprocess.run(base + ["--check"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertIn("report-orphan.html", r.stdout + r.stderr)
        # GH-CLOBBER-EXAMPLES: the shipped example is a pure artifact of its independent source in
        # dev/examples/src/, so a hand-edit (or a stale/clobbered copy) of the example's own CONTENT
        # - not just its layer - is now caught by --check. Before the source split, build.py read the
        # content back from the example itself, so a content edit compared equal to itself and passed.
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
            html = _read(taxi)
            # Poison the CONTENT region (inside #commentRoot), which build.py preserves from the
            # source and never rewrites - so drift here is only catchable because the source is
            # independent of the shipped file.
            poisoned = re.sub(r'(<main\b[^>]*\bid="commentRoot"[^>]*>)',
                              r'\1<p>POISON-CONTENT-DRIFT</p>', html, count=1)
            self.assertNotEqual(poisoned, html, "could not poison the example content region")
            with open(taxi, "w", encoding="utf-8", newline="") as fh:
                fh.write(poisoned)
            r = subprocess.run(base + ["--check"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertIn("report-taxi.html", r.stdout + r.stderr)


class ExamplePromptTests(unittest.TestCase):
    """CMH-DEMO-02: every shipped example report has a companion example-prompt file
    (prompt-<name>.md) with the standard headings and a non-empty blockquote prompt."""

    _REQUIRED_HEADINGS = ("# Example prompt", "## Prompt", "## What you get")

    def test_every_report_has_a_companion_prompt_file(self):
        reports = _report_paths()
        self.assertTrue(reports, "no example reports found to check")
        for report in reports:
            prompt = _companion_prompt(report)
            base = os.path.basename(prompt)
            self.assertTrue(
                os.path.isfile(prompt),
                "example report %s has no companion %s" % (os.path.basename(report), base))
            text = _read(prompt)
            for heading in self._REQUIRED_HEADINGS:
                self.assertRegex(
                    text, r"(?m)^" + re.escape(heading) + r"\b",
                    "%s is missing the heading %r" % (base, heading))
            quotes = [ln.lstrip(">").strip() for ln in text.splitlines() if ln.lstrip().startswith(">")]
            self.assertTrue(any(q for q in quotes), base + " has no non-empty blockquote prompt")


class ExampleNoTemplateHeaderTests(unittest.TestCase):
    """CMH-BUILD-05 (examples): the shipped example reports carry none of the removed
    'TEMPLATE / DEMO' documentation-header phrases, so no example is mislabeled as a
    bare template or demo shell."""

    _HEADER_PHRASES = (
        "TEMPLATE / DEMO",
        "marker-delimited regions",
        "Regions (each",
        "Upgrade workflow",
        "Per-document configuration lives",
    )

    def test_examples_carry_no_template_header(self):
        for path in EXAMPLES:
            html = _read(path)
            for phrase in self._HEADER_PHRASES:
                self.assertNotIn(
                    phrase, html,
                    "%s still carries the removed template header phrase %r"
                    % (os.path.basename(path), phrase))


class ExampleNoSidebarOpenBodyTests(unittest.TestCase):
    """CMH-BUILD-06 (examples): the shipped example reports must not bake the transient
    runtime sidebar-open body-state class into the <body> open tag."""

    def test_examples_do_not_bake_sidebar_open_body_class(self):
        for path in EXAMPLES:
            html = _read(path)
            m = re.search(r"<body\b[^>]*>", html, re.IGNORECASE)
            self.assertIsNotNone(m, "no <body> open tag in " + os.path.basename(path))
            self.assertNotIn("sidebar-open", m.group(0),
                             "%s bakes the transient sidebar-open class into <body>"
                             % os.path.basename(path))


class ChecklistExampleTests(unittest.TestCase):
    """CMH-DEMO-04: the layered-checklist demo report ships, validates clean, carries both
    checklist shapes, and uses a unique comment key at the current version."""

    _EX = os.path.join(SKILL, "examples", "report-checklist.html")

    def test_checklist_example_ships_and_validates_strict(self):
        self.assertTrue(os.path.isfile(self._EX), "report-checklist.html is missing")
        r = subprocess.run(
            [sys.executable, os.path.join(SKILL, "tools", "validate.py"), "--strict", self._EX],
            capture_output=True, text=True, cwd=SKILL)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_checklist_example_has_both_shapes(self):
        html = _read(self._EX)
        self.assertIn('data-cmh-checklist="release"', html)   # nested-list shape
        self.assertIn('data-cmh-checklist="audit"', html)     # table shape
        self.assertIn('data-cmh-parent="network"', html)      # table hierarchy link
        self.assertIn('data-cmh-item="backend"', html)

    def test_checklist_example_key_is_unique_and_versioned(self):
        html = _read(self._EX)
        key = _active_root_attr(html, "data-comment-key")
        self.assertIsNotNone(key, "checklist example is missing data-comment-key")
        others = [_active_root_attr(_read(p), "data-comment-key") for p in EXAMPLES]
        self.assertNotIn(key, others, "checklist example reuses another example's comment key")
        self.assertIn('const CMH_VERSION = "%s"' % _read_version(), html)


if __name__ == "__main__":
    unittest.main()
