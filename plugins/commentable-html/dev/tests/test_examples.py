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
EXAMPLE = os.path.join(_paths.EXAMPLES, "report-community-garden.html")
TAXI = os.path.join(_paths.EXAMPLES, "report-taxi.html")
TRIAGE = os.path.join(_paths.EXAMPLES, "report-triage.html")
METRICS = os.path.join(_paths.EXAMPLES, "report-metrics.html")
EXAMPLES = (EXAMPLE, TAXI, TRIAGE, METRICS)
BUILD_PY = os.path.join(_paths.DEV_TOOLS, "build.py")

sys.path.insert(0, _paths.DEV_TOOLS)  # maintainer build tool (build.py lives in dev/tools)
import build  # noqa: E402
import upgrade  # noqa: E402  shipped authoring tool (on path via _paths -> _toolpath)


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
            [sys.executable, os.path.join(SKILL, "tools", "validate", "validate.py"), "--no-stamp", *EXAMPLES],
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
            self.assertTrue(os.path.isfile(os.path.join(_paths.EXAMPLES, source)),
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

    _EX = os.path.join(_paths.EXAMPLES, "report-checklist.html")

    def test_checklist_example_ships_and_validates_strict(self):
        self.assertTrue(os.path.isfile(self._EX), "report-checklist.html is missing")
        r = subprocess.run(
            [sys.executable, os.path.join(SKILL, "tools", "validate", "validate.py"), "--strict", "--no-stamp", self._EX],
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


class NotesExampleTests(unittest.TestCase):
    """CMH-DEMO-05: the editable-notes demo report ships, validates clean, carries a single-line
    and a multi-line note, and uses a unique comment key at the current version."""

    _EX = os.path.join(_paths.EXAMPLES, "report-notes.html")

    def test_notes_example_ships_and_validates_strict(self):
        self.assertTrue(os.path.isfile(self._EX), "report-notes.html is missing")
        r = subprocess.run(
            [sys.executable, os.path.join(SKILL, "tools", "validate", "validate.py"), "--strict", self._EX],
            capture_output=True, text=True, cwd=SKILL)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_notes_example_has_single_and_multiline_notes(self):
        html = _read(self._EX)
        self.assertIn('data-cmh-note="verdict"', html)
        self.assertIn('data-cmh-note="reviewer-notes"', html)
        self.assertIn('data-cmh-note-multiline="true"', html)
        self.assertIn('data-cmh-note-foldable="true"', html)

    def test_notes_example_key_is_unique_and_versioned(self):
        html = _read(self._EX)
        key = _active_root_attr(html, "data-comment-key")
        self.assertIsNotNone(key, "notes example is missing data-comment-key")
        checklist = os.path.join(_paths.EXAMPLES, "report-checklist.html")
        others = [_active_root_attr(_read(p), "data-comment-key") for p in list(EXAMPLES) + [checklist]]
        self.assertNotIn(key, others, "notes example reuses another example's comment key")
        self.assertIn('const CMH_VERSION = "%s"' % _read_version(), html)


# The mermaid loader lives in <head>, OUTSIDE the swappable CSS/COMMENT UI/JS regions, so a bare
# region swap never reaches it. build.py re-emits it into every example from the canonical PORTABLE
# loader (mirroring the upgrade.py re-emit, CMH-MMD-09), so an example can never ship a stale
# pre-CMH-MMD-07 loader that renders a collapsed-section diagram as a degenerate ~16px SVG.
_MODULE_SCRIPT_RE = re.compile(
    r'<script\b[^>]*\btype=(["\'])module\1[^>]*>(.*?)</script>', re.IGNORECASE | re.DOTALL)
_MERMAID_IMPORT_RE = re.compile(r'import\(\s*(["\'])([^"\']*mermaid[^"\']*)\1', re.IGNORECASE)


def _mermaid_loader_body(html):
    """The body of the <head> module script that boots mermaid (a dynamic mermaid import), or None."""
    lo = html.lower()
    hs, he = lo.find("<head"), lo.find("</head>")
    head = html[hs:he] if (hs != -1 and he != -1 and he > hs) else html
    for m in _MODULE_SCRIPT_RE.finditer(head):
        if _MERMAID_IMPORT_RE.search(m.group(2)):
            return m.group(2)
    return None


class ExampleMermaidLoaderTests(unittest.TestCase):
    """CMH-MMD-09 (examples): build.py re-emits the canonical shell-baked mermaid loader into every
    example, so each example single-sources the loader from PORTABLE and honors CMH-MMD-07 (a
    collapsed-at-load diagram is rendered off-screen, never as a degenerate ~16px in-place SVG)."""

    def test_examples_single_source_the_canonical_mermaid_loader(self):
        portable = _read(os.path.join(_paths.DIST, "PORTABLE.html"))
        canonical = _mermaid_loader_body(portable)
        self.assertIsNotNone(canonical, "no mermaid loader in PORTABLE.html")
        # The canonical loader is the CMH-MMD-07 off-screen partition, not the old naive m.run().
        self.assertIn("renderHidden", canonical)
        self.assertIn("isHidden", canonical)
        for path in EXAMPLES + (os.path.join(_paths.EXAMPLES, "deck-showcase.html"),):
            html = _read(path)
            if "class=\"mermaid" not in html and "class='mermaid" not in html:
                continue
            body = _mermaid_loader_body(html)
            self.assertIsNotNone(body, "no mermaid loader in " + os.path.basename(path))
            self.assertEqual(
                body, canonical,
                "%s does not single-source the canonical mermaid loader (stale loader; run build.py)"
                % os.path.basename(path))


# The SAME build-owned placeholder loader the dev/examples/src/*.html sources carry (CMH-MMD-09):
# build.py's regen_example OVERWRITES it with the canonical shell loader on every build, so the src
# block is inert - keeping it here pins that it stays matchable and non-vendored (so the re-emit is
# never skipped as a hand-vendored loader).
BUILD_OWNED_SRC_LOADER = (
    "<!-- Mermaid loader (BUILD-OWNED). tools/build.py re-emits the canonical shell-baked loader\n"
    "     from assets/template.shell.html into every example on each build (CMH-MMD-09), so this\n"
    "     block is a placeholder only - edit the loader in the shell template, not here; an edit\n"
    "     here has no effect on the built example. -->\n"
    "<script type=\"module\">\n"
    "  // Placeholder; build.py overwrites this with the canonical off-screen loader (CMH-MMD-07/08).\n"
    "  if (document.querySelector(\"pre.mermaid, div.mermaid\")) {\n"
    "    await import(\"https://cdn.jsdelivr.net/npm/mermaid@11.16.0/dist/mermaid.esm.min.mjs\");\n"
    "  }\n"
    "</script>"
)


def _doc(head_inner, body_inner=""):
    """A minimal well-formed document with the given <head> inner content and body."""
    return ("<!doctype html>\n<html>\n<head>\n<meta charset=\"utf-8\">\n"
            + head_inner
            + "\n</head>\n<body>\n" + body_inner + "\n</body>\n</html>\n")


def _module(body):
    return "<script type=\"module\">\n" + body + "\n</script>"


_CDN = "https://cdn.jsdelivr.net/npm/mermaid@11.16.0/dist/mermaid.esm.min.mjs"
_LOADER = "<!-- Mermaid loader -->\n" + _module(
    "  const m = (await import(\"%s\")).default;\n  await m.run();" % _CDN)
_LOADER_NO_GUARD_NO_COMMENT = _module(
    "  const m = (await import(\"https://cdn/mermaid@11/mermaid.mjs\")).default;\n  await m.run();")
_VENDORED_LOADER = "<!-- Mermaid loader -->\n" + _module(
    "  const m = (await import(\"./mermaid.esm.min.mjs\")).default;\n  await m.run();")
_DECOY_MODULE = _module("  import(\"./theme.js\"); // mermaid theme wiring")
_BODY_MERMAID_MODULE = _module("  await import(\"" + _CDN + "\");")
# A head module whose OPENING TAG carries a mermaid-import-looking ATTRIBUTE but whose BODY imports a
# non-mermaid module. The matcher keys on the mermaid import in the script BODY, so this is NOT a
# loader (guards against matching an import string that only appears in an attribute).
_ATTR_DECOY_MODULE = ('<script type="module" data-x=\'import("./decoy-mermaid.js")\'>\n'
                      '  import("./theme.js");\n</script>')


class ExampleMermaidLoaderMatcherTests(unittest.TestCase):
    """CMH-MMD-09 (examples): direct edge-case coverage for build.py's mermaid-loader matcher
    (`_mermaid_loader_span` / `_mermaid_loader_is_vendored` / `_stamp_mermaid_loader`), mirroring the
    `tools/authoring/upgrade.py` CMH-MMD-09 suite in `tests/test_upgrade.py`."""

    def _portable(self):
        return _read(os.path.join(_paths.DIST, "PORTABLE.html"))

    def test_span_ignores_head_module_without_mermaid_import_cmh_mmd_09(self):
        # A second head module <script> that only mentions mermaid in a comment (its import is a
        # non-mermaid module) is not a second loader (no false "multiple" crash) and is not selected.
        html = _doc(_DECOY_MODULE + "\n" + _LOADER)
        span = build._mermaid_loader_span(html, "decoy")  # must not raise
        self.assertIsNotNone(span)
        self.assertNotIn("./theme.js", html[span[0]:span[1]])  # matched the real loader
        self.assertIn("import(\"" + _CDN + "\")", html[span[0]:span[1]])

    def test_span_ignores_mermaid_import_in_attribute_cmh_mmd_09(self):
        # A mermaid `import(...)` that appears only in a script's opening-tag ATTRIBUTE (not its body)
        # is NOT the loader: the matcher keys on the script BODY. Alone it yields no loader; beside the
        # real loader the real one is matched.
        self.assertIsNone(build._mermaid_loader_span(_doc(_ATTR_DECOY_MODULE), "attr-only"))
        span = build._mermaid_loader_span(_doc(_ATTR_DECOY_MODULE + "\n" + _LOADER), "attr+real")
        self.assertIsNotNone(span)
        block = _doc(_ATTR_DECOY_MODULE + "\n" + _LOADER)[span[0]:span[1]]
        self.assertNotIn("decoy-mermaid", block)          # the attribute decoy was not matched
        self.assertIn("import(\"" + _CDN + "\")", block)  # matched the real loader body

    def test_span_ambiguous_multiple_head_loaders_raise_cmh_mmd_09(self):
        # Two head module scripts that BOTH import mermaid and neither is bound to a "Mermaid loader"
        # comment is ambiguous - the build must reject it rather than guess.
        loader_a = _module("  const a = (await import(\"%s\")).default;" % _CDN)
        loader_b = _module("  const b = (await import(\"%s\")).default;" % _CDN)
        html = _doc(loader_a + "\n" + loader_b)
        with self.assertRaises(SystemExit):
            build._mermaid_loader_span(html, "ambiguous")

    def test_span_disambiguates_by_loader_comment_cmh_mmd_09(self):
        # When two head modules import mermaid, the one bound to the "Mermaid loader" comment wins.
        bare = _module("  const a = (await import(\"%s\")).default;" % _CDN)
        html = _doc(bare + "\n" + _LOADER)
        span = build._mermaid_loader_span(html, "disambig")
        self.assertIn("<!-- Mermaid loader -->", html[span[0]:span[1]])  # comment included in span
        self.assertIn("await m.run();", html[span[0]:span[1]])           # the commented loader

    def test_span_is_scoped_to_head_cmh_mmd_09(self):
        # An authored module <script> in the document BODY that imports mermaid is never mistaken for
        # the loader: with a head loader present the span stays in <head>; with only a body module the
        # span is None.
        html = _doc(_LOADER, body_inner=_BODY_MERMAID_MODULE)
        span = build._mermaid_loader_span(html, "scoped")
        head_end = html.lower().find("</head>")
        self.assertTrue(span[1] <= head_end)  # matched span is entirely inside <head>
        body_only = _doc("<meta name=\"x\" content=\"y\">", body_inner=_BODY_MERMAID_MODULE)
        self.assertIsNone(build._mermaid_loader_span(body_only, "body-only"))

    def test_span_head_match_ignores_pre_head_header_comment_cmh_mmd_09(self):
        # A `<head`-prefixed string in a PRE-HEAD comment (e.g. a commented-out <header> carrying a
        # module script) must not be mis-scoped as the document head: the matcher keys on `<head\b`,
        # so it slices the REAL head. The commented script is therefore never treated as a loader.
        none_doc = ('<!doctype html><!-- <header><script type="module">'
                    'await import("https://cdn.example/mermaid.mjs")</script></header> -->\n'
                    '<html><head>\n<title>ordinary</title>\n</head><body>x</body></html>\n')
        self.assertIsNone(build._mermaid_loader_span(none_doc, "pre-head"))
        real_doc = ('<!doctype html><!-- <header> decoy -->\n<html><head>\n'
                    + _LOADER + '\n</head><body>x</body></html>\n')
        span = build._mermaid_loader_span(real_doc, "pre-head+real")
        self.assertIsNotNone(span)
        self.assertIn("import(\"" + _CDN + "\")", real_doc[span[0]:span[1]])  # matched the real head loader

    def test_span_matches_legacy_loader_without_diagram_guard_cmh_mmd_09(self):
        # A historical loader identified only by its mermaid dynamic import (no `pre.mermaid,
        # div.mermaid` guard string) is still recognized.
        html = _doc(_LOADER_NO_GUARD_NO_COMMENT)
        span = build._mermaid_loader_span(html, "legacy")
        self.assertIsNotNone(span)
        self.assertNotIn("pre.mermaid, div.mermaid", html[span[0]:span[1]])
        self.assertIn("import(", html[span[0]:span[1]])

    def test_span_ignores_commented_head_before_real_head_cmh_mmd_09(self):
        # A COMMENTED-OUT full <head>...</head> block (carrying a module script that imports mermaid)
        # placed BEFORE the real head must be ignored: the scan is comment-aware, so it slices the
        # REAL head and matches the REAL loader (not the commented decoy), and a commented head alone
        # yields None.
        commented_only = ('<!-- <head><script type="module">'
                          'await import("https://cdn.example/mermaid.mjs")</script></head> -->\n'
                          '<html><head>\n<title>ordinary</title>\n</head><body>x</body></html>\n')
        self.assertIsNone(build._mermaid_loader_span(commented_only, "commented-only"))
        commented_plus_real = ('<!-- <head><script type="module">'
                               'await import("https://cdn.example/decoy-mermaid.mjs")</script></head> -->\n'
                               '<html><head>\n' + _LOADER + '\n</head><body>x</body></html>\n')
        span = build._mermaid_loader_span(commented_plus_real, "commented+real")
        self.assertIsNotNone(span)
        block = commented_plus_real[span[0]:span[1]]
        self.assertNotIn("decoy-mermaid", block)                 # commented decoy not matched
        self.assertIn("import(\"" + _CDN + "\")", block)         # matched the real head loader
        self.assertIn("<!-- Mermaid loader -->", block)          # real loader comment still in span

    def test_span_ignores_unterminated_comment_head_cmh_mmd_09(self):
        # An UNTERMINATED `<!--` (no closing `-->`) runs to EOF in an HTML parser, so a `<head>` /
        # `<script>` inside it is inert. The comment-aware scan masks it through EOF, so no phantom
        # loader is picked from a document whose only "loader" is inside an unclosed comment.
        doc = ('<html><head><!-- disabled <script type="module">'
               'await import("https://cdn.example/mermaid.mjs")</script></head>\n')
        self.assertIsNone(build._mermaid_loader_span(doc, "unterminated"))

    def test_vendored_classification_cmh_mmd_09(self):
        # The vendored check keys on the MERMAID import and treats scheme-bearing and
        # protocol-relative specifiers as remote, so a decoy import or a commented-out CDN line does
        # not misclassify the loader.
        v = build._mermaid_loader_is_vendored
        self.assertFalse(v('const m = await import("%s");' % _CDN))
        self.assertFalse(v('await import("//cdn.jsdelivr.net/npm/mermaid@1/mermaid.mjs");'))  # //host
        self.assertTrue(v('await import("./mermaid.esm.min.mjs");'))
        self.assertTrue(v('await import("../vendor/mermaid.mjs");'))
        self.assertTrue(v('await import("/assets/mermaid.mjs");'))
        # decoy non-mermaid relative import beside a remote mermaid import -> NOT vendored
        self.assertFalse(v('import("./helper.mjs"); await import("https://cdn/mermaid@1/mermaid.mjs");'))
        # commented-out CDN mermaid import above an ACTIVE relative mermaid import -> vendored
        self.assertTrue(v('/* await import("https://cdn/mermaid@1/mermaid.mjs") */ await import("./mermaid.mjs");'))
        self.assertFalse(v('await import("./helper.mjs");'))  # no mermaid import at all

    def test_stamp_preserves_vendored_offline_loader_cmh_mmd_09(self):
        # A hand-vendored offline loader (mermaid imported by a relative path) is NOT clobbered back
        # to the CDN by the re-emit - that would silently reintroduce a network fetch.
        html = _doc(_VENDORED_LOADER)
        out = build._stamp_mermaid_loader(html, self._portable())
        self.assertEqual(out, html)                                  # left unchanged
        self.assertIn('import("./mermaid.esm.min.mjs")', out)        # relative import preserved
        self.assertNotIn("cdn.jsdelivr.net/npm/mermaid", out)

    def test_stamp_reemits_canonical_over_build_owned_placeholder_cmh_mmd_09(self):
        # The build-owned src placeholder is matchable and non-vendored, and regen re-emits the
        # canonical PORTABLE loader over it - so an example single-sources the loader and the src
        # block is genuinely build-owned (an edit there has no effect on the built example).
        portable = self._portable()
        self.assertFalse(build._mermaid_loader_is_vendored(BUILD_OWNED_SRC_LOADER))
        html = _doc(BUILD_OWNED_SRC_LOADER)
        pb, pe = build._mermaid_loader_span(portable, "portable")
        canonical = portable[pb:pe]
        self.assertNotIn("renderHidden", html)  # the placeholder is NOT the canonical loader
        out = build._stamp_mermaid_loader(html, portable)
        ob, oe = build._mermaid_loader_span(out, "out")
        self.assertEqual(out[ob:oe], canonical)  # re-emitted verbatim from PORTABLE
        self.assertIn("renderHidden", out[ob:oe])

    def test_stamp_reemits_over_loader_with_decoy_local_import_cmh_mmd_09(self):
        # A CDN loader that also carries a decoy relative NON-mermaid import must still be recognized
        # as a CDN loader and re-emitted (not wrongly preserved as vendored) - end-to-end through
        # _stamp_mermaid_loader, mirroring test_upgrade's decoy-local-import case.
        portable = self._portable()
        loader = "<!-- Mermaid loader -->\n" + _module(
            "  const _helper = await import(\"./helper.mjs\");\n"
            "  const m = (await import(\"%s\")).default;\n  await m.run();" % _CDN)
        html = _doc(loader)
        sb, se = build._mermaid_loader_span(html, "decoy-local")
        self.assertIn('import("./helper.mjs")', html[sb:se])
        self.assertFalse(build._mermaid_loader_is_vendored(html[sb:se]))  # CDN loader, not vendored
        out = build._stamp_mermaid_loader(html, portable)
        ob, oe = build._mermaid_loader_span(out, "out")
        pb, pe = build._mermaid_loader_span(portable, "portable")
        self.assertEqual(out[ob:oe], portable[pb:pe])          # re-emitted to the canonical loader
        self.assertNotIn('import("./helper.mjs")', out[ob:oe])  # decoy import gone

    def test_src_example_loaders_are_build_owned_cmh_mmd_09(self):
        # AC3: EVERY dev/examples/src report/deck source carries a build-owned placeholder loader
        # (regen overwrites it from the shell template), NOT a stale hand-authored pre-CMH-MMD-07
        # loader - so an editor is pointed at the shell template and does not "fix" an inert copy
        # here. Every discovered source must have one (not just "some"), so none can silently drift
        # back to a hand loader.
        src_dir = os.path.join(_paths.DEV, "examples", "src")
        names = [n for n in sorted(os.listdir(src_dir))
                 if n.startswith(("report-", "deck-")) and n.endswith(".html")]
        self.assertGreaterEqual(len(names), 4, "expected several src example sources")
        for name in names:
            text = _read(os.path.join(src_dir, name))
            span = build._mermaid_loader_span(text, name)
            self.assertIsNotNone(span, "%s src has no recognizable loader (should be build-owned)" % name)
            block = text[span[0]:span[1]]
            self.assertIn("BUILD-OWNED", block, "%s src loader is not build-owned (stale?)" % name)
            self.assertFalse(build._mermaid_loader_is_vendored(block),
                             "%s build-owned loader must be non-vendored so regen re-emits it" % name)


class MermaidLoaderMirrorTests(unittest.TestCase):
    """CMH-MMD-09: build.py's `_mermaid_loader_span`/`_mermaid_loader_is_vendored` (in
    `tools/build_parts/30-examples.py`) are a hand-maintained MIRROR of upgrade.py's
    `_mermaid_bootstrap_span`/`_mermaid_loader_is_vendored`. This cross-implementation differential
    test asserts the two return IDENTICAL spans/behavior on an ambiguous/vendored/decoy corpus, so
    the mirror can never silently diverge. (The one intentional difference is the exception TYPE on
    an ambiguous head - `SystemExit` for the build CLI vs `ValueError` for the library - so the
    ambiguous case asserts both REJECT it, each with its own type.)"""

    def _corpus(self):
        portable = _read(os.path.join(_paths.DIST, "PORTABLE.html"))
        bare = _module("  const a = (await import(\"%s\")).default;" % _CDN)
        # A pre-head comment containing a `<header>` (a `<head`-prefixed string) and a module script:
        # a naive find("<head") head-slice would mis-scope to it, so this pins the `<head\b` head match.
        pre_head_comment = ('<!doctype html><!-- <header><script type="module">'
                            'await import("https://cdn.example/mermaid.mjs")</script></header> -->\n'
                            '<html><head>\n<title>ordinary</title>\n</head><body>x</body></html>\n')
        pre_head_comment_plus_real = ('<!doctype html><!-- <header> decoy -->\n<html><head>\n'
                                      + _LOADER + '\n</head><body>x</body></html>\n')
        # A COMMENTED-OUT full <head> (with a module script) before the real head: comment-aware
        # scanning must ignore it (the None case), and match the real loader when one is present.
        commented_head_only = ('<!-- <head><script type="module">'
                               'await import("https://cdn.example/mermaid.mjs")</script></head> -->\n'
                               '<html><head>\n<title>ordinary</title>\n</head><body>x</body></html>\n')
        commented_head_plus_real = ('<!-- <head><script type="module">'
                                    'await import("https://cdn.example/decoy-mermaid.mjs")</script></head> -->\n'
                                    '<html><head>\n' + _LOADER + '\n</head><body>x</body></html>\n')
        return {
            "portable": portable,                                   # the real canonical loader
            "legacy": _doc(_LOADER_NO_GUARD_NO_COMMENT),            # loader with no diagram guard
            "vendored": _doc(_VENDORED_LOADER),                     # hand-vendored offline loader
            "decoy_plus_real": _doc(_DECOY_MODULE + "\n" + _LOADER),
            "attr_decoy_plus_real": _doc(_ATTR_DECOY_MODULE + "\n" + _LOADER),
            "attr_decoy_only": _doc(_ATTR_DECOY_MODULE),            # both -> None (import only in attr)
            "comment_disambiguated": _doc(bare + "\n" + _LOADER),
            "body_only": _doc("<meta name=\"x\" content=\"y\">", body_inner=_BODY_MERMAID_MODULE),
            "pre_head_header_comment": pre_head_comment,            # both -> None (real head has no loader)
            "pre_head_header_comment_plus_real": pre_head_comment_plus_real,
            "commented_head_only": commented_head_only,             # both -> None (decoy is commented out)
            "commented_head_plus_real": commented_head_plus_real,   # both -> the real loader
            "unterminated_comment": ('<html><head><!-- disabled <script type="module">'
                                     'await import("https://cdn.example/mermaid.mjs")</script></head>\n'),
            "none": _doc("<title>no loader</title>"),
        }

    def test_span_matchers_agree_on_corpus_cmh_mmd_09(self):
        for name, html in self._corpus().items():
            got = build._mermaid_loader_span(html, name)
            want = upgrade._mermaid_bootstrap_span(html, name)
            self.assertEqual(got, want, "span mismatch on corpus item %r" % name)

    def test_vendored_classifiers_agree_on_corpus_cmh_mmd_09(self):
        specs = [
            'const m = await import("%s");' % _CDN,
            'await import("//cdn.jsdelivr.net/npm/mermaid@1/mermaid.mjs");',
            'await import("HTTPS://cdn/mermaid@1/mermaid.mjs");',        # uppercase scheme -> remote
            'await import("./mermaid.esm.min.mjs");',
            'await import("../vendor/mermaid.mjs");',
            'await import("/assets/mermaid.mjs");',
            # a LOCAL specifier whose query/fragment merely contains "://" must not be read as remote
            # (this is exactly where an unanchored '"://" in spec' check diverges from upgrade.py).
            'await import("./mermaid.mjs?src=https://cdn.example/mermaid.esm.mjs");',
            'await import("../vendor/mermaid.min.js#https://x");',
            'await import("blob:https://x/mermaid.js");',               # non-http scheme, no // -> local
            'import("./helper.mjs"); await import("https://cdn/mermaid@1/mermaid.mjs");',
            '/* await import("https://cdn/mermaid@1/mermaid.mjs") */ await import("./mermaid.mjs");',
            'await import("./helper.mjs");',
            '',
        ]
        for spec in specs:
            self.assertEqual(build._mermaid_loader_is_vendored(spec),
                             upgrade._mermaid_loader_is_vendored(spec),
                             "vendored classification mismatch on %r" % spec)

    def test_both_reject_ambiguous_head_loaders_cmh_mmd_09(self):
        loader_a = _module("  const a = (await import(\"%s\")).default;" % _CDN)
        loader_b = _module("  const b = (await import(\"%s\")).default;" % _CDN)
        html = _doc(loader_a + "\n" + loader_b)
        with self.assertRaises(SystemExit):        # build CLI
            build._mermaid_loader_span(html, "ambiguous")
        with self.assertRaises(ValueError):        # upgrade library
            upgrade._mermaid_bootstrap_span(html, "ambiguous")


if __name__ == "__main__":
    unittest.main()
