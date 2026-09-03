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


CHANGELOG = os.path.join(_paths.PLUGIN_ROOT, "CHANGELOG.md")


def _read_release_date():
    """The current version's release date (YYYY-MM-DD) from the dated CHANGELOG heading."""
    version = _read_version()
    m = re.search(r"(?m)^## \[" + re.escape(version) + r"\][ \t]*-[ \t]*(\d{4}-\d{2}-\d{2})[ \t]*$",
                  _read(CHANGELOG))
    if not m:
        raise AssertionError("no dated CHANGELOG heading '## [%s] - <date>'" % version)
    return m.group(1)


def _all_example_docs():
    ex_dir = _paths.EXAMPLES
    return sorted(
        os.path.join(ex_dir, name) for name in os.listdir(ex_dir)
        if (name.startswith("report-") or name.startswith("deck-")) and name.endswith(".html"))


def _report_paths():
    ex_dir = _paths.EXAMPLES
    return sorted(
        os.path.join(ex_dir, name) for name in os.listdir(ex_dir)
        if name.startswith("report-") and name.endswith(".html"))


def _companion_prompt(report_path):
    stem = os.path.basename(report_path)[len("report-"):-len(".html")]
    return os.path.join(_paths.EXAMPLES, "prompt-" + stem + ".md")


def _active_root_attr(html, attr):
    # Scope to before the CONTENT marker (mirroring the build's _stamp_content_root_hook /
    # _stamp_generated_date), so a decoy <main id="commentRoot"> inside authored content never
    # shadows the real container root.
    marker = html.find("BEGIN: commentable-html - CONTENT")
    head = html[:marker] if marker != -1 else html
    matches = list(re.finditer(r'<main\b[^>]*\bid="commentRoot"[^>]*\b' + re.escape(attr) + r'="([^"]*)"', head))
    if not matches:
        matches = list(re.finditer(r'<main\b[^>]*\b' + re.escape(attr) + r'="([^"]*)"[^>]*\bid="commentRoot"', head))
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
            const = _paths.CMH_VERSION_CONST_RE.search(html)
            self.assertIsNotNone(meta, "no version <meta> in " + os.path.basename(path))
            self.assertIsNotNone(const, "no CMH_VERSION const in " + os.path.basename(path))
            self.assertEqual(meta.group(1), version,
                             "%s <meta> version is stale (run build.py)" % os.path.basename(path))
            self.assertEqual(const.group(1), version,
                             "%s CMH_VERSION is stale (run build.py)" % os.path.basename(path))

    def test_examples_generated_date_is_release_date_and_in_sync(self):
        # CMH-BUILD-15: build.py stamps every shipped example's content-root data-generated with the
        # current release date (single-sourced from CHANGELOG), so the sidebar "Generated on" line is
        # correct (not an authored in-story date like the taxi report's 2014) and identical across all
        # examples. An authored data-generated in a source is overridden, and one is added where absent.
        release_date = _read_release_date()
        docs = _all_example_docs()
        self.assertTrue(docs, "no shipped examples found")
        seen = {}
        for path in docs:
            generated = _active_root_attr(_read(path), "data-generated")
            self.assertEqual(
                generated, release_date,
                "%s data-generated is %r, expected the release date %r (run build.py)"
                % (os.path.basename(path), generated, release_date))
            seen[generated] = seen.get(generated, 0) + 1
        self.assertEqual(list(seen), [release_date],
                         "example generated dates are out of sync: %r" % seen)

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
            poisoned = _paths.CMH_VERSION_CONST_RE.sub(
                'const CMH_VERSION="0.0.0";//', html, count=1)
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


def _vendored_chartjs_sri():
    """The SHA-384 of the vendored Chart.js, in `integrity` form - the single source of truth."""
    import base64
    import hashlib
    with open(os.path.join(_paths.ASSETS, "vendor", "chart.umd.min.js"), "rb") as fh:
        return "sha384-" + base64.b64encode(hashlib.sha384(fh.read()).digest()).decode("ascii")


def _vendored_chartjs_version():
    """The version the vendored bundle reports about itself (its `Chart.js v<x.y.z>` banner)."""
    with open(os.path.join(_paths.ASSETS, "vendor", "chart.umd.min.js"), encoding="utf-8",
              errors="replace") as fh:
        head = fh.read(4000)
    m = re.search(r"Chart\.js v(\d+\.\d+\.\d+)", head)
    if not m:
        raise RuntimeError(
            "dev/assets/vendor/chart.umd.min.js carries no `Chart.js v<x.y.z>` banner, so the "
            "version the shipped loaders must pin cannot be read. If upstream dropped the banner, "
            "read the version from node_modules/chart.js/package.json here instead, then re-pin "
            "dev/examples/src/report-taxi.html and report-community-garden.html and recompute "
            "their integrity from this file.")
    return m.group(1)


class ExampleNoInlinedLibraryTests(unittest.TestCase):
    """CMH-SIZE-09: no shipped example carries a third-party library BODY of its own.

    Two examples used to inline Chart.js v4.4.0 (205,031 bytes each) as authored content, from the
    era when a self-contained file had to carry its own renderer. Since CMH-SIZE-01/CMH-SIZE-08 the
    document does not: the viewer loads a pinned CDN copy and Export Offline downloads, SRI-verifies
    and inlines the vendored one. So the authored copy was pure weight - it made those two the
    largest shipped documents - and it was stale: 4.4.0, while the payload pins 4.5.1.

    It also inverted the export's provenance guarantee. The exporter hoists author code BELOW the
    library it inlines so a constructing script cannot run before its dependency; that hoist put the
    authored copy after the verified one, so the UNVERIFIED 4.4.0 deterministically won
    `window.Chart` while the downloaded, hash-checked 4.5.1 sat inert. Measured, not inferred.

    A library body here is anything the vendored-provenance guards (CMH-BUILD-25 for mermaid,
    CMH-SIZE-08 for Chart.js) do not cover, so nothing checks its version, integrity or licence.
    """

    # Big enough that no ordinary authored snippet reaches it, small enough to catch a minified
    # library: the real ones are 205 KB (Chart.js) and 3.5 MB (mermaid).
    LIBRARY_BYTES = 50000
    # `</script >`, `</SCRIPT>` and even `</script\n bar>` all close a script element as far as a
    # browser is concerned, so all of them are accepted here: a guard that a library body can slip
    # past by changing its case or its spacing is not a guard. `\b` keeps `</scriptfoo>` out.
    # (Flagged by CodeQL's bad-HTML-filtering-regexp rule.)
    SCRIPT = re.compile(r"<script([^>]*)>([\s\S]*?)</script\b[^>]*>", re.I)
    SCRIPT_OPEN = re.compile(r"<script([^>]*)>", re.I)
    # Vendor banners the minified bundles carry.
    BANNERS = re.compile(r"Chart\.js v[\d.]+|mermaid@[\d.]+|/\*!\s*Chart\.js", re.I)

    def test_no_example_inlines_a_third_party_library_body(self):
        offenders = []
        for path in _all_example_docs():
            html = _read(path)
            for attrs, body in self.SCRIPT.findall(html):
                # The vendored-library PAYLOAD is exempt: it is a build artifact with its own
                # provenance guards (CMH-SIZE-08 for Chart.js, CMH-BUILD-25 for mermaid), and under
                # the `--vendor-bytes` escape hatch it legitimately carries megabytes of library.
                # Matched on the id build.py stamps, not on a marker an author could simply add.
                if 'id="cmhVendoredRichLibs"' in attrs:
                    continue
                if len(body) >= self.LIBRARY_BYTES and self.BANNERS.search(body):
                    offenders.append("%s: %d bytes, %r"
                                     % (os.path.basename(path), len(body),
                                        self.BANNERS.search(body).group(0)))
        self.assertEqual(
            offenders, [],
            "a shipped example inlines a third-party library body. The document does not need one: "
            "the viewer loads the pinned CDN copy and Export Offline inlines the vendored, "
            "SRI-verified one. An authored copy is unversioned weight that no provenance guard "
            "checks, and it WINS over the verified copy in an export. Use the pinned CDN loader "
            "with SRI, as report-metrics and report-triage do. Offenders: " + "; ".join(offenders))

    def test_the_script_scanner_is_not_evaded_by_case_or_spacing(self):
        # The rule is only as good as its scanner. `<SCRIPT>` and `</script >` are both legal HTML,
        # so a library body written either way must still be seen - otherwise the guard is
        # cosmetic. Exercised on synthetic markup rather than on the corpus, which by construction
        # contains no offender to find.
        body = "/*! Chart.js v9.9.9 */" + ("x" * self.LIBRARY_BYTES)
        for name, html in (
            ("upper-case tags", "<SCRIPT>%s</SCRIPT>" % body),
            ("spaced end tag", "<script>%s</script >" % body),
            ("mixed case and spacing", "<ScRiPt>%s</ScRiPt  >" % body),
            ("junk in the end tag", "<script>%s</script\t\n bar>" % body),
        ):
            found = [b for _, b in self.SCRIPT.findall(html)
                     if len(b) >= self.LIBRARY_BYTES and self.BANNERS.search(b)]
            self.assertEqual(len(found), 1, "%s evaded the library-body scanner" % name)
        # ...but a DIFFERENT element must not be mistaken for the end tag, or a body could be
        # truncated at the wrong place and scan as too small.
        self.assertEqual(
            self.SCRIPT.findall("<script>%s</scriptfoo></script>" % body)[0][1],
            body + "</scriptfoo>",
            "`</scriptfoo>` is not a script end tag and must not terminate the body")
        opens = self.SCRIPT_OPEN.findall('<SCRIPT src="https://cdn.jsdelivr.net/npm/chart.js@1.2.3/'
                                         'dist/chart.umd.min.js"></SCRIPT>')
        self.assertEqual(len(opens), 1, "an upper-case loader tag evaded the loader scanner")

    def test_the_chart_examples_still_load_chartjs_somehow(self):
        # The companion assertion, so the rule above can never be satisfied by simply deleting the
        # library and leaving the charts dead. Every example that constructs a Chart must still
        # reach one, and the only sanctioned way is a version-pinned loader with Subresource
        # Integrity and `crossorigin` (without which SRI cannot be enforced cross-origin).
        #
        # Attributes are matched INDEPENDENTLY rather than in one ordered regex: HTML attribute
        # order is free, so an ordered pattern would fail a perfectly correct tag that happens to
        # write `crossorigin` before `integrity`.
        for path in _all_example_docs():
            html = _read(path)
            if "new Chart(" not in html:
                continue
            name = os.path.basename(path)
            tag = None
            tag_at = None
            for m in self.SCRIPT_OPEN.finditer(html):
                if "cdn.jsdelivr.net/npm/chart.js@" in m.group(1):
                    tag = m.group(1)
                    tag_at = m.start()
                    break
            self.assertIsNotNone(tag, "%s constructs a Chart but loads no Chart.js" % name)
            # A FULL version, never a floating jsDelivr specifier: `@4` and `@4.5` silently follow
            # upstream releases, which is exactly what an integrity hash cannot survive.
            src = re.search(r'src="(https://cdn\.jsdelivr\.net/npm/chart\.js@'
                            r'(\d+\.\d+\.\d+)/dist/chart\.umd(\.min)?\.js)"', tag)
            self.assertIsNotNone(
                src, "%s: Chart.js loader is not pinned to an exact version: %r" % (name, tag))
            self.assertRegex(tag, r'integrity="sha384-[A-Za-z0-9+/]+={0,2}"',
                             "%s: Chart.js loader has no well-formed SHA-384 integrity" % name)
            # `crossorigin` may legally be written bare (equivalent to `anonymous`), so match the
            # attribute NAME rather than the `name=` prefix - the ordered-regex trap again.
            self.assertRegex(tag, r'\bcrossorigin\b',
                             "%s: Chart.js loader has no crossorigin, so SRI cannot be enforced" % name)
            # Chart.js is a classic synchronous script and the init runs at parse time, so a
            # deferred, async or module loader leaves `Chart` undefined when the init looks.
            self.assertNotRegex(tag, r'\b(defer|async)\b',
                                "%s: the Chart.js loader is deferred/async, so the parse-time init "
                                "runs before the library exists" % name)
            self.assertNotRegex(tag, r'type="module"',
                                "%s: the Chart.js loader is a module, so it is deferred by "
                                "definition and the parse-time init runs first" % name)

            # THE POINT of this assertion. A loader that names the MINIFIED build is naming the file
            # this repository vendors, so its hash must be that file's hash - checked by VALUE, not
            # by shape. Without this, bumping the vendored Chart.js moves `assets/vendor/`, the
            # payload descriptor and the CMH-SIZE-08 provenance guard while leaving these loaders
            # behind; SRI then blocks the script and the `typeof Chart === "undefined"` guard
            # swallows it, so the charts go blank with no error and no failing test.
            if src.group(3):
                self.assertIn(
                    'integrity="%s"' % _vendored_chartjs_sri(), tag,
                    "%s: the loader names the vendored minified Chart.js but its integrity is not "
                    "that file's SHA-384. Recompute it from dev/assets/vendor/chart.umd.min.js "
                    "(and check the pinned @version still matches)." % name)
                self.assertIn("chart.js@%s/" % _vendored_chartjs_version(), src.group(1),
                              "%s: the loader's pinned version does not match the vendored "
                              "Chart.js bundle" % name)

            # ORDER matters as much as presence. Chart.js is a classic synchronous script and the
            # init is guarded with `typeof Chart === "undefined"`, so a loader placed AFTER the
            # first `new Chart(...)` no-ops into a permanently blank canvas with no error - the
            # precise failure this companion test exists to prevent, and one that "the loader is
            # somewhere in the file" cannot see.
            #
            # Both positions are taken from real SPANS, never from a substring search over the
            # whole document: `html.index(<url>)` would happily match the same URL inside the
            # payload descriptor or a comment, and `html.index("new Chart(")` would match the
            # phrase quoted in prose or in a fenced code sample. Either would flip this into a
            # false failure whose message reads like a genuine ordering bug.
            init_at = None
            for m in self.SCRIPT.finditer(html):
                if "new Chart(" in m.group(2):
                    init_at = m.start() + m.group(2).index("new Chart(")
                    break
            self.assertIsNotNone(
                init_at, "%s: `new Chart(` appears only outside a <script> body" % name)
            self.assertLess(
                tag_at, init_at,
                "%s: the Chart.js loader comes AFTER the first new Chart(...) call, so the init "
                "runs before the library exists and the canvas stays blank" % name)


class CaptureChartRouteTests(unittest.TestCase):
    """CMH-SIZE-09: the tutorial capture serves Chart.js from the vendored copy, and only that one.

    The capture is hermetic - it aborts every remote request - so until the chart examples stopped
    inlining Chart.js it never needed a chart route at all. Now it does, and the route has two ways
    to go quietly wrong, both of which end as a BLANK chart in a committed screenshot rather than as
    an error: not matching the URL the examples actually request, or matching too much and answering
    some other document's request with these bytes (which then fails that document's `integrity`).
    """

    def _source(self):
        with open(os.path.join(_paths.DEV, "tools", "capture_tutorial.mjs"), encoding="utf-8") as fh:
            return fh.read()

    def test_the_capture_installs_the_chart_route(self):
        src = self._source()
        # The CALL, not the bare name: `async function routeVendoredChartJs(context)` contains the
        # name-plus-parens too, so asserting on that alone stays green after the call site is
        # deleted - a guard that cannot fail is not a guard.
        self.assertRegex(src, r"(?m)^\s*await routeVendoredChartJs\(context\);\s*$",
                         "the capture never AWAITS the chart route, so the chart shot would be "
                         "blank (a declaration alone installs nothing)")

    def test_the_route_is_built_from_the_pin_module_not_a_wildcard(self):
        # The route used to be a literal here with a `[^/]+` version, which answered a request for
        # ANY minified Chart.js with the vendored bytes - and since the capture can be pointed at an
        # arbitrary example, a document on another version would have had its `integrity` check
        # reject the reply and its chart go silently blank. It is now built from the vendored
        # bundle's own banner by `tools/chartjs_pin.mjs`, which is exercised behaviorally in
        # `tests/01-vendor-provenance.spec.js`. What this asserts is only that the capture still
        # goes through that module and did not regrow a hand-written pattern.
        src = self._source()
        self.assertIn('from "./chartjs_pin.mjs"', src,
                      "the capture must build its Chart.js route from tools/chartjs_pin.mjs")
        self.assertRegex(src, r"await context\.route\(chartJsRoutePattern\(",
                         "the capture must install the pinned route the module builds")
        self.assertNotRegex(
            src, r"context\.route\(/\^https[^\n]*chart\\\.js@",
            "the capture has a hand-written Chart.js route literal again; build it from "
            "chartJsRoutePattern so the version cannot drift into a wildcard")

    def test_no_shipped_example_requests_a_minified_bundle_other_than_the_vendored_one(self):
        # The other half: the route serves ONE file, so any example asking for a different minified
        # build would be answered with the wrong bytes.
        want = "https://cdn.jsdelivr.net/npm/chart.js@%s/dist/chart.umd.min.js" % _vendored_chartjs_version()
        for path in _all_example_docs():
            for url in re.findall(r'src="(https://cdn\.jsdelivr\.net/npm/chart\.js@[^"]+)"', _read(path)):
                if url.endswith("chart.umd.min.js"):
                    self.assertEqual(url, want,
                                     "%s requests a minified Chart.js the capture route does not "
                                     "serve" % os.path.basename(path))
    def test_the_route_serves_the_vendored_bundle(self):
        src = self._source()
        # Quote style and inner whitespace are free; the path segments are what matters.
        self.assertRegex(
            src, r"""["']assets["'],\s*["']vendor["'],\s*["']chart\.umd\.min\.js["']""",
            "the chart route must serve the vendored bundle, whose SHA-384 the examples' "
            "integrity attribute names")

class DevExamplesHasNoBuiltCopiesTests(unittest.TestCase):
    """CMH-BUILD-29: `dev/examples/` holds SOURCES only - no built report, deck or prompt.

    `build.py` reads its content sources from `dev/examples/src/` and writes the built documents to
    `--examples-dir`. That flag DEFAULTS to `<out-dir>/examples`, and `--out-dir` defaults to the
    `dev` directory itself, so a build run WITHOUT the canonical flags targets `dev/examples` and
    fills the source directory with its own output beside the sources it reads. That is not an
    exotic mistake with a mis-pointed flag - it is what a bare `python tools/build.py` does, which
    is how #1258 left 12.6 MB tracked and unreferenced until #1293. Always pass
    `--out-dir skill --examples-dir ../examples`.

    That is worse than dead weight, because such a copy keeps the state it was built in and nothing
    refreshes it. Each of the two chart examples there still inlined a 205,031-byte `Chart.js
    v4.4.0` bundle and reached Chart.js through no CDN loader at all, long after `CMH-SIZE-09`
    removed exactly that from the shipped files - so anyone grepping for how an example loads
    Chart.js found the wrong answer in a bigger, more prominent file.

    `src/` and `images/` are the legitimate contents and are untouched by this rule.
    """

    # Derived from the build's OWN name regexes rather than hand-copied, so teaching build.py a
    # fourth output shape cannot quietly give it a way to litter here that this guard never sees.
    # `re.I` widens them: a build writes lower case, but an offender must not escape on case.
    BUILT = re.compile("(?:%s)|(?:%s)" % (build._EXAMPLE_NAME_RE.pattern,
                                          build._PROMPT_NAME_RE.pattern), re.I)

    def test_dev_examples_holds_no_built_documents(self):
        root = os.path.join(_paths.DEV, "examples")
        self.assertTrue(os.path.isdir(root), "dev/examples is missing")
        # No isfile() filter: a DIRECTORY with one of these names is just as wrong, and skipping
        # it would leave the guard a trivially evadable hole.
        strays = sorted(n for n in os.listdir(root) if self.BUILT.match(n))
        self.assertEqual(
            strays, [],
            "dev/examples holds built documents beside its sources: %s. These are build OUTPUT and "
            "nothing reads them - the shipped tree is plugins/commentable-html/examples, which is "
            "also what the site copies its demos from. You most likely ran build.py without its "
            "flags: --examples-dir defaults to <out-dir>/examples and --out-dir defaults to dev, "
            "so a bare `python tools/build.py` writes here. Delete them and rebuild from "
            "plugins/commentable-html/dev with: python tools/build.py --assets-dir assets "
            "--out-dir skill --pkg-dir ../pkg/skills/commentable-html --examples-dir ../examples"
            % ", ".join(strays))

    def test_the_sources_the_build_actually_reads_are_still_there(self):
        # The companion, so the rule above can never be satisfied by emptying the directory: the
        # sources and the garden's source images must survive.
        root = os.path.join(_paths.DEV, "examples")
        src = os.path.join(root, "src")
        self.assertTrue(os.path.isdir(src), "dev/examples/src (the build's content sources) is gone")
        self.assertTrue(os.path.isdir(os.path.join(root, "images")),
                        "dev/examples/images (the garden example's source images) is gone")
        built = sorted(n for n in os.listdir(src) if self.BUILT.match(n))
        self.assertTrue(built, "dev/examples/src has no report/deck/prompt sources left")

    def test_the_guard_accepts_every_name_the_build_can_emit(self):
        # The pattern is derived from build.py's regexes, so this pins the DERIVATION rather than
        # restating it: every shape the build writes into an examples dir must be caught here, and
        # an unrelated file must not be.
        for name in ("report-x.html", "deck-x.html", "prompt-x.md",
                     "REPORT-X.HTML", "Prompt-X.MD"):
            self.assertTrue(self.BUILT.match(name), "%s should be treated as build output" % name)
        for name in ("images", "src", "README.md", "notes.txt", "report.html", "myprompt.md"):
            self.assertFalse(self.BUILT.match(name), "%s is not build output" % name)


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
        stamped = _paths.CMH_VERSION_CONST_RE.search(html)
        self.assertIsNotNone(stamped, "checklist example carries no CMH_VERSION const")
        self.assertEqual(stamped.group(1), _read_version())


class NotesExampleTests(unittest.TestCase):
    """CMH-DEMO-05: the editable-notes demo report ships, validates clean, carries a single-line
    and a multi-line note, and uses a unique comment key at the current version."""

    _EX = os.path.join(_paths.EXAMPLES, "report-notes.html")

    def test_notes_example_ships_and_validates_strict(self):
        self.assertTrue(os.path.isfile(self._EX), "report-notes.html is missing")
        r = subprocess.run(
            [sys.executable, os.path.join(SKILL, "tools", "validate", "validate.py"),
             "--strict", "--no-stamp", self._EX],
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
        stamped = _paths.CMH_VERSION_CONST_RE.search(html)
        self.assertIsNotNone(stamped, "notes example carries no CMH_VERSION const")
        self.assertEqual(stamped.group(1), _read_version())


# The mermaid loader lives in <head>, OUTSIDE the swappable CSS/COMMENT UI/JS regions, so a bare
# region swap never reaches it. build.py re-emits it into every example from the canonical SHAREABLE
# loader (mirroring the upgrade.py re-emit, CMH-MMD-09), so an example can never ship a stale
# pre-CMH-MMD-07 loader that renders a collapsed-section diagram as a degenerate ~16px SVG.
_MODULE_SCRIPT_RE = re.compile(
    r'<script\b[^>]*\btype=(["\'])module\1[^>]*>(.*?)</script>', re.IGNORECASE | re.DOTALL)
_MERMAID_IMPORT_RE = re.compile(r'import\(\s*(["\'])([^"\']*mermaid[^"\']*)\1', re.IGNORECASE)


def _mermaid_loader_body(html):
    """The body of the module script that boots mermaid (a dynamic mermaid import), or None.

    Searched in the TEMPLATE-OWNED scopes only - `<head>`, and the MACHINERY fence the
    content-first layout (CMH-SIZE-02) parks the loader in - so an authored module script inside
    the content region can never be read as the loader.
    """
    lo = html.lower()
    scopes = []
    hs, he = lo.find("<head"), lo.find("</head>")
    if hs != -1 and he > hs:
        scopes.append(html[hs:he])
    fb = html.find("BEGIN: commentable-html - MACHINERY")
    fe = html.find("END: commentable-html - MACHINERY", fb + 1) if fb != -1 else -1
    if fb != -1 and fe > fb:
        scopes.append(html[fb:fe])
    if not scopes:
        scopes = [html]
    for scope in scopes:
        for m in _MODULE_SCRIPT_RE.finditer(scope):
            if _MERMAID_IMPORT_RE.search(m.group(2)):
                return m.group(2)
    return None


class ExampleMermaidLoaderTests(unittest.TestCase):
    """CMH-MMD-09 (examples): build.py re-emits the canonical shell-baked mermaid loader into every
    example, so each example single-sources the loader from SHAREABLE and honors CMH-MMD-07 (a
    collapsed-at-load diagram is rendered off-screen, never as a degenerate ~16px in-place SVG)."""

    def test_examples_single_source_the_canonical_mermaid_loader(self):
        shareable = _read(os.path.join(_paths.DIST, "SHAREABLE.html"))
        canonical = _mermaid_loader_body(shareable)
        self.assertIsNotNone(canonical, "no mermaid loader in SHAREABLE.html")
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

    def _shareable(self):
        return _read(os.path.join(_paths.DIST, "SHAREABLE.html"))

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

    def test_span_ignores_comment_marker_in_tag_attribute_cmh_mmd_09(self):
        # A `<!--` inside a QUOTED TAG ATTRIBUTE is NOT an HTML comment, so the state-aware scan does
        # not treat it as one and does not mask past it: a real loader followed by `<meta
        # content="<!--">` is still matched (a naive comment mask would blank the real </head> and
        # return None).
        doc = ('<html><head>\n' + _LOADER + '\n<meta content="<!--">\n</head><body>x</body></html>\n')
        span = build._mermaid_loader_span(doc, "attr-marker")
        self.assertIsNotNone(span)
        self.assertIn("import(\"" + _CDN + "\")", doc[span[0]:span[1]])

    def test_span_ignores_commented_module_inside_real_head_cmh_mmd_09(self):
        # A commented-out mermaid module <script> INSIDE the real head (beside the real loader) is
        # ignored - the candidate scan runs on the comment-masked head, so only the real loader
        # matches; a commented module with no real loader beside it yields None.
        commented_module = ('<!-- <script type="module">'
                            'await import("https://cdn.example/decoy-mermaid.mjs")</script> -->')
        doc = ('<html><head>\n' + commented_module + '\n' + _LOADER + '\n</head><body>x</body></html>\n')
        span = build._mermaid_loader_span(doc, "commented-module")
        self.assertIsNotNone(span)
        self.assertNotIn("decoy-mermaid", doc[span[0]:span[1]])
        self.assertIn("import(\"" + _CDN + "\")", doc[span[0]:span[1]])
        only = ('<html><head>\n' + commented_module + '\n<title>x</title>\n</head><body></body></html>\n')
        self.assertIsNone(build._mermaid_loader_span(only, "commented-module-only"))

    def test_span_raw_text_close_requires_appropriate_end_tag_cmh_mmd_09(self):
        # A `</script-foo>` inside a script body is NOT the script's end tag - HTML requires the
        # end-tag name followed by whitespace, `/`, or `>` - so it must not prematurely end the
        # raw-text body and expose a following `<!--` as a DATA comment that masks the real loader.
        doc = ('<html><head>\n'
               '<script>const s = "</script-foo><!--";</script>\n'
               + _LOADER + '\n</head><body>x</body></html>\n')
        span = build._mermaid_loader_span(doc, "rawtext-close")
        self.assertIsNotNone(span)
        self.assertIn("import(\"" + _CDN + "\")", doc[span[0]:span[1]])

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
        out = build._stamp_mermaid_loader(html, self._shareable())
        self.assertEqual(out, html)                                  # left unchanged
        self.assertIn('import("./mermaid.esm.min.mjs")', out)        # relative import preserved
        self.assertNotIn("cdn.jsdelivr.net/npm/mermaid", out)

    def test_stamp_reemits_canonical_over_build_owned_placeholder_cmh_mmd_09(self):
        # The build-owned src placeholder is matchable and non-vendored, and regen re-emits the
        # canonical SHAREABLE loader over it - so an example single-sources the loader and the src
        # block is genuinely build-owned (an edit there has no effect on the built example).
        shareable = self._shareable()
        self.assertFalse(build._mermaid_loader_is_vendored(BUILD_OWNED_SRC_LOADER))
        html = _doc(BUILD_OWNED_SRC_LOADER)
        pb, pe = build._mermaid_loader_span(shareable, "shareable")
        canonical = shareable[pb:pe]
        self.assertNotIn("renderHidden", html)  # the placeholder is NOT the canonical loader
        out = build._stamp_mermaid_loader(html, shareable)
        ob, oe = build._mermaid_loader_span(out, "out")
        self.assertEqual(out[ob:oe], canonical)  # re-emitted verbatim from SHAREABLE
        self.assertIn("renderHidden", out[ob:oe])

    def test_stamp_reemits_over_loader_with_decoy_local_import_cmh_mmd_09(self):
        # A CDN loader that also carries a decoy relative NON-mermaid import must still be recognized
        # as a CDN loader and re-emitted (not wrongly preserved as vendored) - end-to-end through
        # _stamp_mermaid_loader, mirroring test_upgrade's decoy-local-import case.
        shareable = self._shareable()
        loader = "<!-- Mermaid loader -->\n" + _module(
            "  const _helper = await import(\"./helper.mjs\");\n"
            "  const m = (await import(\"%s\")).default;\n  await m.run();" % _CDN)
        html = _doc(loader)
        sb, se = build._mermaid_loader_span(html, "decoy-local")
        self.assertIn('import("./helper.mjs")', html[sb:se])
        self.assertFalse(build._mermaid_loader_is_vendored(html[sb:se]))  # CDN loader, not vendored
        out = build._stamp_mermaid_loader(html, shareable)
        ob, oe = build._mermaid_loader_span(out, "out")
        pb, pe = build._mermaid_loader_span(shareable, "shareable")
        self.assertEqual(out[ob:oe], shareable[pb:pe])          # re-emitted to the canonical loader
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
        shareable = _read(os.path.join(_paths.DIST, "SHAREABLE.html"))
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
            "shareable": shareable,                                   # the real canonical loader
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
            "attr_marker_after_loader": ('<html><head>\n' + _LOADER
                                         + '\n<meta content="<!--">\n</head><body></body></html>\n'),
            "commented_module_in_head_plus_real": ('<html><head>\n<!-- <script type="module">'
                                                   'await import("https://cdn.example/decoy-mermaid.mjs")'
                                                   '</script> -->\n' + _LOADER
                                                   + '\n</head><body></body></html>\n'),
            "rawtext_close_decoy": ('<html><head>\n<script>const s = "</script-foo><!--";</script>\n'
                                    + _LOADER + '\n</head><body></body></html>\n'),
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
