#!/usr/bin/env python3
"""Regression tests for new_document.py (the template-clone document builder)."""
import builtins
import contextlib
import hashlib
import io
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402  shared pkg/dev split path constants
ROOT = _paths.PKG
TOOLS = _paths.TOOLS
sys.path.insert(0, TOOLS)
import new_document  # noqa: E402

NEW_DOC_PY = os.path.join(TOOLS, "authoring", "new_document.py")
TEMPLATE = os.path.join(ROOT, "dist", "SHAREABLE.html")

CONTENT = '<section><h2 id="a">Hi</h2><p>x</p></section>'


def _skill_drive_tmpdir():
    """A scratch dir on the SAME DRIVE as the skill.

    `--assets-relative` computes a path from --out's directory to the skill's dist/, and
    Windows has no relative path across drives, so the tool correctly refuses there. The GitHub
    Windows runner checks the repo out on `D:` while TEMP is on `C:`, so a plain mkdtemp() has
    the test exercise that refusal by accident instead of the relative-ref behavior it names.
    Fall back to the repo's gitignored `tmp/`, which is on the skill's drive by construction.
    """
    def drive(path):
        return os.path.splitdrive(os.path.abspath(path))[0].lower()

    if drive(tempfile.gettempdir()) == drive(_paths.DIST):
        return tempfile.mkdtemp()
    scratch = os.path.join(os.path.dirname(os.path.dirname(_paths.PLUGIN_ROOT)), "tmp")
    os.makedirs(scratch, exist_ok=True)
    return tempfile.mkdtemp(dir=scratch)


def _template():
    with open(TEMPLATE, encoding="utf-8") as fh:
        return fh.read()


class MakeDocumentTests(unittest.TestCase):
    def test_happy_path_replaces_content_and_sets_attrs(self):
        out = new_document.make_document(_template(), CONTENT, "my-report-v1", "My Report", "src.md")
        # Content fragment is present between the markers, demo body is gone.
        self.assertIn('<h2 id="a">Hi</h2>', out)
        self.assertNotIn("This is a small playground", out)
        # The active root carries our attributes.
        self.assertIn('data-comment-key="my-report-v1"', out)
        self.assertIn("data-cmh-content-root", out)
        self.assertIn('data-doc-label="My Report"', out)
        self.assertIn('data-doc-source="src.md"', out)
        # The demo content-root key was replaced, not left as a second live root.
        self.assertNotIn("commentable-html-demo", out)
        # Title is synced to the label (best effort).
        self.assertIn("<title>My Report</title>", out)

    def test_source_provenance_is_basename_only_cmh_sec_03(self):
        source = r"C:\Users\alice\Internal Project\reports\quarterly.md"
        out = new_document.make_document(
            _template(), CONTENT, "my-report-v1", "My Report", source)
        self.assertIn('data-doc-source="quarterly.md"', out)
        self.assertNotIn("alice", out)
        self.assertNotIn("Internal Project", out)

    def test_output_validates_clean(self):
        out = new_document.make_document(_template(), CONTENT, "my-report-v1", "My Report", "src.md")
        result = new_document._self_validate(out)
        self.assertIsNotNone(result, "the document could not be checked at all")
        errors, _warnings = result
        self.assertEqual(errors, [], "expected no validation errors, got: %r" % errors)

    def test_generated_document_does_not_bake_sidebar_open_body_class(self):
        # CMH-BUILD-06: a freshly generated document must not ship the transient runtime
        # sidebar-open body-state class; the runtime re-derives the sidebar state on load.
        out = new_document.make_document(_template(), CONTENT, "my-report-v1", "My Report", "src.md")
        m = re.search(r"<body\b[^>]*>", out, re.IGNORECASE)
        self.assertIsNotNone(m, "no <body> open tag in the generated document")
        self.assertNotIn("sidebar-open", m.group(0),
                         "the generated document bakes the transient sidebar-open class into <body>")

    def test_doc_comment_example_root_is_not_the_one_edited(self):
        # A commented-out decoy `<main id="commentRoot" data-comment-key="my-doc">`
        # placed BEFORE the real content root (an authoring example left in a comment)
        # must survive untouched, and OUR key must land on the real (last) root instead.
        base = _template()
        _b, _e, main_start, _t = new_document._find_active_root(base)
        decoy = (
            "<!-- example only, not the live root:\n"
            '  <main id="commentRoot" data-comment-key="my-doc"\n'
            '        data-doc-label="My Document"> ... </main>\n-->\n'
        )
        seeded = base[:main_start] + decoy + base[main_start:]
        out = new_document.make_document(seeded, CONTENT, "my-report-v1", "My Report")
        self.assertIn('data-comment-key="my-doc"', out)     # decoy untouched
        # The LAST content root before the CONTENT marker carries our key.
        begin = out.index(new_document.BEGIN_MARKER)
        last_root = None
        for m in new_document._MAIN_ROOT_RE.finditer(out, 0, begin):
            last_root = m
        self.assertIsNotNone(last_root)
        tag = out[last_root.start():new_document._tag_end(out, last_root.start()) + 1]
        self.assertIn('data-comment-key="my-report-v1"', tag)
        self.assertNotIn("my-doc", tag)

    def test_source_omitted_drops_stale_attribute(self):
        out = new_document.make_document(_template(), CONTENT, "my-report-v1", "My Report")
        begin = out.index(new_document.BEGIN_MARKER)
        last_root = None
        for m in new_document._MAIN_ROOT_RE.finditer(out, 0, begin):
            last_root = m
        tag = out[last_root.start():new_document._tag_end(out, last_root.start()) + 1]
        self.assertNotIn("data-doc-source", tag)  # template's dist/SHAREABLE.html source is dropped

    def test_html_special_chars_in_label_are_escaped(self):
        out = new_document.make_document(_template(), CONTENT, "my-report-v1", 'A & B "<x>"')
        self.assertIn('data-doc-label="A &amp; B &quot;&lt;x&gt;&quot;"', out)
        self.assertIn("<title>A &amp; B &quot;&lt;x&gt;&quot;</title>", out)

    def test_generated_attribute_is_set_when_requested(self):
        out = new_document.make_document(
            _template(),
            CONTENT,
            "my-report-v1",
            "My Report",
            generated="2026-07-09T20:30:00Z",
        )
        begin = out.index(new_document.BEGIN_MARKER)
        last_root = None
        for m in new_document._MAIN_ROOT_RE.finditer(out, 0, begin):
            last_root = m
        tag = out[last_root.start():new_document._tag_end(out, last_root.start()) + 1]
        self.assertIn('data-generated="2026-07-09T20:30:00Z"', tag)

    def test_resolve_key_auto_is_stable_and_non_demo(self):
        k1 = new_document.resolve_key("auto", "My Report", source="report-a.html")
        k2 = new_document.resolve_key("auto", "My Report", source="report-a.html")
        k3 = new_document.resolve_key("auto", "Another Report", source="report-b.html")
        self.assertEqual(k1, k2)
        self.assertNotEqual(k1, k3)
        self.assertTrue(k1.startswith("cmh-"))
        self.assertEqual(len(k1), 16)
        self.assertNotIn(k1, new_document.REFUSED_KEYS)

    def test_resolve_key_auto_same_label_distinct_identity_does_not_collide(self):
        # Regression: two documents that share a label must NOT share a key just because
        # the label matches; the key is derived from the document identity, not the label.
        a = new_document.resolve_key("auto", "Quarterly Report", out="q1/report.html")
        b = new_document.resolve_key("auto", "Quarterly Report", out="q2/report.html")
        self.assertNotEqual(a, b)
        c = new_document.resolve_key("auto", "Quarterly Report", source="q1.html")
        d = new_document.resolve_key("auto", "Quarterly Report", source="q2.html")
        self.assertNotEqual(c, d)

    def test_resolve_key_auto_without_identity_requires_explicit_key(self):
        with self.assertRaises(ValueError) as cm:
            new_document.resolve_key("auto", "Just A Label")
        self.assertIn("identity", str(cm.exception).lower())

    def test_resolve_key_key_from_source_derivation(self):
        key = new_document.resolve_key("auto", "Label", key_from_source="logical-id")
        expected = "cmh-" + hashlib.sha256("logical-id".encode("utf-8")).hexdigest()[:12]
        self.assertEqual(key, expected)

    def test_resolve_key_explicit_key_overrides_key_from_source(self):
        key = new_document.resolve_key("explicit-v1", "Label", key_from_source="logical-id")
        self.assertEqual(key, "explicit-v1")

    def test_refuses_demo_key(self):
        for bad in ("commentable-html-demo", "my-doc", "commentable-html-nonshareable-demo"):
            with self.assertRaises(ValueError) as cm:
                new_document.make_document(_template(), CONTENT, bad, "My Report")
            self.assertIn("demo", str(cm.exception).lower())

    def test_refuses_empty_key(self):
        with self.assertRaises(ValueError):
            new_document.make_document(_template(), CONTENT, "   ", "My Report")

    def test_refuses_empty_label(self):
        with self.assertRaises(ValueError):
            new_document.make_document(_template(), CONTENT, "my-report-v1", "")

    def test_refuses_missing_content_marker(self):
        tpl = _template().replace(new_document.BEGIN_MARKER, "<!-- no marker here -->")
        with self.assertRaises(ValueError) as cm:
            new_document.make_document(tpl, CONTENT, "my-report-v1", "My Report")
        self.assertIn("marker", str(cm.exception).lower())

    def test_refuses_missing_content_root(self):
        # Markers present but no `<main id=commentRoot>` before CONTENT-BEGIN.
        tpl = (
            "<html><head><title>t</title></head><body>\n"
            + new_document.BEGIN_MARKER + "\nold\n" + new_document.END_MARKER
            + "\n</body></html>\n"
        )
        with self.assertRaises(ValueError) as cm:
            new_document.make_document(tpl, CONTENT, "my-report-v1", "My Report")
        self.assertIn("commentRoot", str(cm.exception))

    def test_end_before_begin_is_rejected(self):
        tpl = (
            '<main id="commentRoot" data-comment-key="x">\n'
            + new_document.END_MARKER + "\nmid\n" + new_document.BEGIN_MARKER + "\n</main>\n"
        )
        with self.assertRaises(ValueError):
            new_document.make_document(tpl, CONTENT, "my-report-v1", "My Report")

    def test_unquoted_and_boolean_attrs_are_preserved(self):
        tpl = (
            "<html><head><title>t</title></head><body>\n"
            "<main id=commentRoot data-comment-key=old data-flag>\n"
            + new_document.BEGIN_MARKER + "\nold\n" + new_document.END_MARKER
            + "\n</main></body></html>\n"
        )
        out = new_document.make_document(tpl, CONTENT, "my-report-v1", "My Report")
        self.assertIn("data-flag", out)
        self.assertIn('data-comment-key="my-report-v1"', out)
        self.assertIn('<h2 id="a">Hi</h2>', out)

    def test_tag_end_rejects_unterminated_tag(self):
        with self.assertRaises(ValueError):
            new_document._tag_end("<main id=commentRoot", 0)

    def test_self_validate_reports_the_cause_when_the_validator_is_missing(self):
        # CMH-TOOL-07: an unusable validator is a REASON ("could not check"), never a
        # (None, None) that main() would read as "no errors, no warnings" and write anyway.
        with mock.patch.dict(sys.modules, {"validate": None}):
            result, reason = new_document._self_validate_result("<html></html>")
            self.assertIsNone(result)
            self.assertIn("validate", reason)
            self.assertIsNone(new_document._self_validate("<html></html>"))


class NoTemplateDemoHeaderTests(unittest.TestCase):
    """CMH-BUILD-05: neither the shipped dist templates nor a freshly generated
    document carries the old leading 'TEMPLATE / DEMO' documentation header comment."""

    _HEADER_PHRASES = (
        "TEMPLATE / DEMO",
        "marker-delimited regions",
        "Regions (each",
        "Upgrade workflow",
        "Per-document configuration lives",
    )

    def _assert_no_header(self, html, where):
        for phrase in self._HEADER_PHRASES:
            self.assertNotIn(
                phrase, html,
                "%s still carries the removed template header phrase %r" % (where, phrase))

    def test_shipped_dist_templates_carry_no_header(self):
        for name in ("SHAREABLE.html", "NONSHAREABLE.html"):
            with open(os.path.join(ROOT, "dist", name), encoding="utf-8") as fh:
                self._assert_no_header(fh.read(), "dist/" + name)

    def test_generated_document_carries_no_header(self):
        out = new_document.make_document(_template(), CONTENT, "my-report-v1", "My Report")
        self._assert_no_header(out, "a freshly generated document")


class MainCliTests(unittest.TestCase):
    def _tmpdir(self):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: _rmtree(d))
        return d

    def _call_main(self, argv, stdin=""):
        if "--kind" not in argv:
            argv = argv[:1] + ["--kind", "generic"] + argv[1:]
        out = io.StringIO()
        err = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO(stdin)), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = new_document.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_stdin_content_to_stdout(self):
        code, out, err = self._call_main(
            ["new_document.py", "--content", "-", "--key", "cli-v1", "--label", "CLI Doc",
             "--shareable"],
            stdin=CONTENT)
        self.assertEqual(code, 0, err)
        self.assertIn('data-comment-key="cli-v1"', out)
        self.assertIn('<h2 id="a">Hi</h2>', out)
        self.assertIn("<title>CLI Doc</title>", out)

    def test_content_file_out_to_file(self):
        d = self._tmpdir()
        cpath = os.path.join(d, "body.html")
        with open(cpath, "w", encoding="utf-8") as fh:
            fh.write(CONTENT)
        opath = os.path.join(d, "out.html")
        code, _out, err = self._call_main(
            ["new_document.py", "--content", cpath, "--key", "file-v1",
             "--label", "File Doc", "--source", "body.html", "--out", opath])
        self.assertEqual(code, 0, err)
        self.assertTrue(os.path.exists(opath))
        with open(opath, encoding="utf-8") as fh:
            written = fh.read()
        self.assertIn('data-comment-key="file-v1"', written)
        self.assertIn('data-doc-source="body.html"', written)

    def test_cmh_tool_18_out_collision_suffixes_without_overwriting(self):
        d = self._tmpdir()
        opath = os.path.join(d, "out.html")
        opath_2 = os.path.join(d, "out-2.html")
        opath_3 = os.path.join(d, "out-3.html")
        for path, text in ((opath, "original"), (opath_2, "second")):
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)

        code, _out, err = self._call_main(
            ["new_document.py", "--content", "-", "--key", "collision-v1",
             "--label", "Collision Doc", "--shareable", "--out", opath],
            stdin=CONTENT)

        self.assertEqual(code, 0, err)
        with open(opath, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "original")
        with open(opath_2, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "second")
        self.assertTrue(os.path.exists(opath_3))
        self.assertIn("wrote %s" % opath_3, err)
        with open(opath_3, encoding="utf-8") as fh:
            written = fh.read()
        self.assertIn('data-comment-key="collision-v1"', written)

    def test_cmh_tool_18_force_overwrites_out_target(self):
        d = self._tmpdir()
        opath = os.path.join(d, "out.html")
        with open(opath, "w", encoding="utf-8") as fh:
            fh.write("original")

        code, _out, err = self._call_main(
            ["new_document.py", "--content", "-", "--key", "force-v1",
             "--label", "Force Doc", "--shareable", "--force", "--out", opath],
            stdin=CONTENT)

        self.assertEqual(code, 0, err)
        self.assertIn("wrote %s" % opath, err)
        self.assertFalse(os.path.exists(os.path.join(d, "out-2.html")))
        with open(opath, encoding="utf-8") as fh:
            written = fh.read()
        self.assertIn('data-comment-key="force-v1"', written)
        self.assertNotEqual(written, "original")

    def test_cli_bakes_syntax_highlighting_by_default(self):
        # CMH-HL-04: new_document bakes highlighting so a created doc is never raw. This is the
        # root-cause fix for the notes-feature-plan.html defect (a raw language block shipped
        # unbaked because baking lived only in the separate, manual finalize step).
        frag = ('<section><h2 id="a">Code</h2>'
                '<pre><code class="language-python">def f(): return 1</code></pre></section>')
        code, out, err = self._call_main(
            ["new_document.py", "--content", "-", "--key", "hl-v1", "--label", "HL", "--shareable"],
            stdin=frag)
        self.assertEqual(code, 0, err)
        self.assertIn('<span class="cmh-code-kw">def</span>', out)
        self.assertNotIn('<code class="language-python">def f(): return 1</code>', out)

    def test_cli_no_highlight_flag_leaves_code_raw(self):
        # CMH-HL-04: --no-highlight opts out of the default baking (parity with finalize.py).
        frag = ('<section><h2 id="a">Code</h2>'
                '<pre><code class="language-python">def f(): return 1</code></pre></section>')
        code, out, err = self._call_main(
            ["new_document.py", "--content", "-", "--key", "raw-v1", "--label", "Raw",
             "--shareable", "--no-highlight"],
            stdin=frag)
        self.assertEqual(code, 0, err)
        self.assertNotIn('<span class="cmh-code-kw">def</span>', out)
        self.assertIn('<code class="language-python">def f(): return 1</code>', out)

    def test_cli_surfaces_validator_warnings(self):
        # CMH-HL-04: self-validation warnings are PRINTED (previously silently discarded), so a
        # non-commentable code block or an unbaked-highlight warning is visible at creation.
        frag = ('<section><h2 id="a">Hi</h2>'
                '<pre class="cm-skip"><code>plain code {}</code></pre></section>')
        code, out, err = self._call_main(
            ["new_document.py", "--content", "-", "--key", "warn-v1", "--label", "Warn",
             "--shareable"],
            stdin=frag)
        self.assertEqual(code, 0, err)
        self.assertIn("warning", err.lower())
        self.assertIn("will not be commentable", err)

    def test_demo_key_exits_2(self):
        code, _out, err = self._call_main(
            ["new_document.py", "--content", "-", "--key", "my-doc", "--label", "X"],
            stdin=CONTENT)
        self.assertEqual(code, 2)
        self.assertIn("new_document:", err)

    def test_key_auto_derives_stable_key_from_out_path(self):
        d = self._tmpdir()
        op = os.path.join(d, "auto-report.html")
        code, out, err = self._call_main(
            ["new_document.py", "--content", "-", "--key", "auto", "--label", "Auto Key Label",
             "--shareable", "--out", op],
            stdin=CONTENT,
        )
        self.assertEqual(code, 0, err)
        expected = "cmh-" + hashlib.sha256(os.path.abspath(op).encode("utf-8")).hexdigest()[:12]
        html = open(op, encoding="utf-8").read()
        self.assertIn('data-comment-key="%s"' % expected, html)

    def test_cmh_tool_18_key_auto_derives_from_collision_resolved_out_path(self):
        d = self._tmpdir()
        op = os.path.join(d, "auto-report.html")
        with open(op, "w", encoding="utf-8") as fh:
            fh.write("original")
        resolved = os.path.join(d, "auto-report-2.html")

        code, _out, err = self._call_main(
            ["new_document.py", "--content", "-", "--key", "auto", "--label", "Auto Key Label",
             "--shareable", "--out", op],
            stdin=CONTENT,
        )

        self.assertEqual(code, 0, err)
        with open(op, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "original")
        expected = "cmh-" + hashlib.sha256(os.path.abspath(resolved).encode("utf-8")).hexdigest()[:12]
        with open(resolved, encoding="utf-8") as fh:
            html = fh.read()
        self.assertIn('data-comment-key="%s"' % expected, html)

    def test_key_auto_without_identity_exits_2(self):
        code, _out, err = self._call_main(
            ["new_document.py", "--content", "-", "--key", "auto", "--label", "Auto Key Label"],
            stdin=CONTENT,
        )
        self.assertEqual(code, 2)
        self.assertIn("identity", err.lower())

    def test_key_from_source_derives_key_from_logical_id(self):
        code, out, err = self._call_main(
            [
                "new_document.py",
                "--content",
                "-",
                "--key",
                "auto",
                "--key-from-source",
                "logical-id",
                "--label",
                "Ignored Label",
                "--shareable",
            ],
            stdin=CONTENT,
        )
        self.assertEqual(code, 0, err)
        expected = "cmh-" + hashlib.sha256("logical-id".encode("utf-8")).hexdigest()[:12]
        self.assertIn('data-comment-key="%s"' % expected, out)

    def test_generated_cli_option_sets_data_generated_attribute(self):
        code, out, err = self._call_main(
            [
                "new_document.py",
                "--content",
                "-",
                "--key",
                "auto",
                "--label",
                "Generated Label",
                "--source",
                "generated.html",
                "--generated",
                "2026-07-09T20:30:00Z",
                "--shareable",
            ],
            stdin=CONTENT,
        )
        self.assertEqual(code, 0, err)
        self.assertIn('data-generated="2026-07-09T20:30:00Z"', out)

    def test_explicit_key_still_wins_with_key_from_source(self):
        code, out, err = self._call_main(
            [
                "new_document.py",
                "--content",
                "-",
                "--key",
                "explicit-v1",
                "--key-from-source",
                "logical-id",
                "--label",
                "Label",
                "--shareable",
            ],
            stdin=CONTENT,
        )
        self.assertEqual(code, 0, err)
        self.assertIn('data-comment-key="explicit-v1"', out)

    def test_missing_content_file_errors(self):
        d = self._tmpdir()
        missing = os.path.join(d, "nope.html")
        code, _out, err = self._call_main(
            ["new_document.py", "--content", missing, "--key", "x-v1", "--label", "X"])
        self.assertEqual(code, 1)
        self.assertIn("cannot read content", err)

    def test_missing_template_errors(self):
        d = self._tmpdir()
        missing = os.path.join(d, "missing-shareable-source.html")
        code, _out, err = self._call_main(
            ["new_document.py", "--content", "-", "--key", "x-v1", "--label", "X",
             "--template", missing], stdin=CONTENT)
        self.assertEqual(code, 1)
        self.assertIn("cannot read template", err)

    def test_missing_marker_template_exits_2(self):
        d = self._tmpdir()
        tpath = os.path.join(d, "tpl.html")
        with open(tpath, "w", encoding="utf-8") as fh:
            fh.write("<html><body>no markers</body></html>")
        code, _out, err = self._call_main(
            ["new_document.py", "--content", "-", "--key", "x-v1", "--label", "X",
             "--template", tpath], stdin=CONTENT)
        self.assertEqual(code, 2)
        self.assertIn("marker", err.lower())

    def test_validation_failure_exits_1(self):
        # A template whose root keeps a DUPLICATE id triggers a validate error, so
        # a produced-but-invalid document is caught and not written.
        d = self._tmpdir()
        out_html = new_document.make_document(_template(), CONTENT, "x-v1", "X")
        with mock.patch.object(new_document, "make_document", return_value=out_html), \
                mock.patch.object(new_document, "_self_validate_result",
                                  return_value=((["boom"], []), None)):
            code, _out, err = self._call_main(
                ["new_document.py", "--content", "-", "--key", "x-v1", "--label", "X"],
                stdin=CONTENT)
        self.assertEqual(code, 1)
        self.assertIn("does not validate", err)
        self.assertIn("boom", err)

    def test_default_template_is_skill_template(self):
        self.assertEqual(os.path.abspath(new_document._default_template()), os.path.abspath(TEMPLATE))

    def test_cli_subprocess_stdout(self):
        r = subprocess.run(
            [sys.executable, NEW_DOC_PY, "--content", "-", "--key", "sub-v1", "--label", "Sub",
             "--kind", "generic", "--shareable"],
            input=CONTENT, capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('data-comment-key="sub-v1"', r.stdout)


def _rmtree(path):
    import shutil
    shutil.rmtree(path, ignore_errors=True)


class ActiveRootAndReservedKeyTests(unittest.TestCase):
    def test_active_root_attrs_returns_root_attributes(self):
        out = new_document.make_document(_template(), CONTENT, "cmh-abc123", "Lbl", "src.md")
        attrs = dict(new_document.active_root_attrs(out))
        self.assertEqual(attrs.get("data-comment-key"), "cmh-abc123")
        self.assertEqual(attrs.get("data-doc-label"), "Lbl")
        self.assertEqual(attrs.get("data-doc-source"), "src.md")

    def test_allow_reserved_key_permits_demo_key(self):
        # A brand-new document still refuses a demo key ...
        with self.assertRaises(ValueError):
            new_document.make_document(_template(), CONTENT, "commentable-html-demo", "L")
        # ... but re-stamping an existing document that owns it (export) is allowed.
        out = new_document.make_document(
            _template(), CONTENT, "commentable-html-demo", "L", allow_reserved_key=True)
        self.assertIn('data-comment-key="commentable-html-demo"', out)


class NonShareableCliTests(unittest.TestCase):
    _LINK_RE = re.compile(r'<link\b[^>]*href="[^"]*commentable-html\.css"')

    def _tmpdir(self):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: _rmtree(d))
        return d

    def _run(self, argv, stdin=CONTENT):
        if "--kind" not in argv:
            argv = argv[:1] + ["--kind", "generic"] + argv[1:]
        # NonShareable is no longer a DEFAULT this skill produces - the mode follows the resolved
        # template. These tests are specifically about the retained NonShareable behaviour, so they
        # ask for that template explicitly, which is exactly how a caller reaches it now.
        if "--template" not in argv and "--shareable" not in argv:
            argv = argv[:1] + ["--template", os.path.join(_paths.DIST, "NONSHAREABLE.html")] + argv[1:]
        out = io.StringIO()
        err = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO(stdin)), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = new_document.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_the_default_mode_is_now_shareable(self):
        """CMH-PORT-03: Shareable is the only mode this skill generates by default.

        Deliberately does NOT go through self._run, which injects the NonShareable template.
        """
        d = self._tmpdir()
        op = os.path.join(d, "p.html")
        argv = ["new_document.py", "--kind", "generic", "--content", "-", "--key", "auto",
                "--label", "P", "--out", op]
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO(CONTENT)), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = new_document.main(argv)
        self.assertEqual(code, 0, err.getvalue())
        html = open(op, encoding="utf-8").read()
        # Assert the EXACT bootstrap marker, not the bare phrase: the Shareable layer's own
        # export JS mentions that phrase inside a regex literal, so a loose substring check
        # fails on a perfectly good Shareable document.
        self.assertNotIn(new_document.NONSHAREABLE_MARKER, html)
        self.assertIn('"mode":"shareable"', html.replace(" ", ""))
        # A Shareable document references no companions at all.
        self.assertNotIn('href="commentable-html.css"', html)
        self.assertNotIn('src="commentable-html.js"', html)

    def test_an_explicit_nonshareable_template_still_builds_one(self):
        """CMH-PORT-03: the legacy mode remains reachable on purpose, just never by default."""
        d = self._tmpdir()
        op = os.path.join(d, "r.html")
        code, _o, err = self._run(
            ["new_document.py", "--content", "-", "--key", "auto", "--label", "NP", "--out", op])
        self.assertEqual(code, 0, err)
        html = open(op, encoding="utf-8").read()
        self.assertIn(new_document.NONSHAREABLE_MARKER, html)
        self.assertIn('"mode":"nonshareable"', html.replace(" ", ""))

    def test_explicit_nonshareable_refs_resolve_to_dist(self):
        d = self._tmpdir()
        op = os.path.join(d, "r.html")
        code, _o, err = self._run(
            ["new_document.py", "--content", "-", "--key", "auto", "--label", "NP", "--out", op])
        self.assertEqual(code, 0, err)  # validates only because the refs resolve to the skill dist/
        html = open(op, encoding="utf-8").read()
        self.assertIn("BEGIN: commentable-html - CSS", html)
        css_url = Path(os.path.join(_paths.DIST, "commentable-html.css")).resolve().as_uri()
        js_url = Path(os.path.join(_paths.DIST, "commentable-html.js")).resolve().as_uri()
        self.assertIn('href="%s"' % css_url, html)
        self.assertIn('src="%s"' % js_url, html)

    def test_a_copy_of_the_nonshareable_template_is_still_repointed(self):
        """CMH-PORT-03: a template is recognized by what it CONTAINS, not by where it lives.

        --template is now the standard way to reach the legacy mode, and a caller may well pass a
        copy of NONSHAREABLE.html (a staged skill, a vendored tree). Deciding "this is a custom
        template, leave its references alone" from the PATH silently produced a document with
        bare companion refs and no companions beside it - and exited 0, because the existence
        check was skipped too.
        """
        d = self._tmpdir()
        copied = os.path.join(d, "copy-of-nonshareable.html")
        shutil.copyfile(os.path.join(_paths.DIST, "NONSHAREABLE.html"), copied)
        op = os.path.join(d, "r.html")
        code, _o, err = self._run(
            ["new_document.py", "--content", "-", "--key", "auto", "--label", "NP",
             "--template", copied, "--out", op])
        self.assertEqual(code, 0, err)
        html = open(op, encoding="utf-8").read()
        css_url = Path(os.path.join(_paths.DIST, "commentable-html.css")).resolve().as_uri()
        self.assertIn('href="%s"' % css_url, html)
        self.assertNotIn('href="commentable-html.css"', html,
                         "a bare companion ref would not resolve beside the output")

    def test_authored_content_demonstrating_the_runtime_is_not_repointed(self):
        """CMH-PORT-03: the companion repoint rewrites the REAL reference, not an authored one.

        The repoint runs after the content is injected and rewrites the FIRST occurrence, but the
        real runtime reference sits at the END of the template - AFTER the content. A document
        whose own content demonstrates `<script src="commentable-html.js"></script>` therefore
        had its authored markup rewritten while the real reference stayed bare and unresolvable.
        """
        d = self._tmpdir()
        op = os.path.join(d, "r.html")
        fragment = ('<h1>Docs</h1>\n<p>Legacy files load it with:</p>\n'
                    '<script src="commentable-html.js"></script>\n')
        code, _o, err = self._run(
            ["new_document.py", "--content", "-", "--key", "auto", "--label", "NP",
             "--template", os.path.join(_paths.DIST, "NONSHAREABLE.html"), "--out", op],
            stdin=fragment)
        self.assertEqual(code, 0, err)
        html = open(op, encoding="utf-8").read()
        begin = html.index("BEGIN: commentable-html - CONTENT", html.index("</head>"))
        end = html.index("<!-- END: commentable-html - CONTENT")
        self.assertIn('<script src="commentable-html.js"></script>', html[begin:end],
                      "the authored demonstration must be preserved verbatim")
        js_url = Path(os.path.join(_paths.DIST, "commentable-html.js")).resolve().as_uri()
        self.assertIn('src="%s"' % js_url, html[end:],
                      "the REAL runtime reference must be the one repointed")

    def test_assets_relative_restores_relative_dist_refs(self):
        # The scratch dir must be on the skill's drive: Windows has no relative path across
        # drives, and the GitHub runner's TEMP (C:) is not the checkout's drive (D:).
        d = _skill_drive_tmpdir()
        self.addCleanup(lambda: _rmtree(d))
        op = os.path.join(d, "r.html")
        code, _o, err = self._run(
            ["new_document.py", "--content", "-", "--key", "auto", "--label", "NP",
             "--assets-relative", "--out", op])
        self.assertEqual(code, 0, err)
        html = open(op, encoding="utf-8").read()
        self.assertRegex(html, r'<link\b[^>]*href="[^"]*/dist/commentable-html\.css"')

    def test_assets_relative_across_drives_exits_2_with_guidance(self):
        """A cross-drive --out has NO relative path, so refusing is the correct answer.

        Windows `os.path.relpath` raises ValueError when the two paths sit on different drives
        (or UNC roots). Emitting a broken relative ref, or crashing with a bare traceback, would
        both be worse than exiting 2 and naming the two flags that DO work from there. Simulated
        rather than staged, so the branch is covered on every OS.
        """
        d = self._tmpdir()
        op = os.path.join(d, "r.html")
        real_relpath = os.path.relpath

        def cross_drive(path, start=os.curdir):
            # Only the companion computation is cross-drive; everything else keeps working.
            if os.path.basename(path) == "dist":
                raise ValueError("path is on mount 'D:', start on mount 'C:'")
            return real_relpath(path, start)

        with mock.patch.object(new_document.os.path, "relpath", side_effect=cross_drive):
            code, _o, err = self._run(
                ["new_document.py", "--content", "-", "--key", "auto", "--label", "NP",
                 "--assets-relative", "--out", op])
        self.assertEqual(code, 2, err)
        self.assertIn("cannot compute a relative companion path", err)
        self.assertIn("--assets-href", err)
        self.assertIn("--copy-assets", err)
        self.assertFalse(os.path.exists(op), "a refused run must write no document")

    def test_shareable_flag_inlines_layer(self):
        d = self._tmpdir()
        op = os.path.join(d, "r.html")
        code, _o, err = self._run(
            ["new_document.py", "--content", "-", "--key", "auto", "--label", "P",
             "--shareable", "--out", op])
        self.assertEqual(code, 0, err)
        html = open(op, encoding="utf-8").read()
        self.assertIn("BEGIN: commentable-html - CSS", html)      # layer CSS inlined
        self.assertIsNone(self._LINK_RE.search(html))             # no companion <link>

    def test_copy_assets_copies_companions_and_uses_bare_refs(self):
        d = self._tmpdir()
        op = os.path.join(d, "r.html")
        code, _o, err = self._run(
            ["new_document.py", "--content", "-", "--key", "auto", "--label", "C",
             "--copy-assets", "--out", op])
        self.assertEqual(code, 0, err)
        for name in new_document.COMPANIONS:
            self.assertTrue(os.path.exists(os.path.join(d, name)), "missing companion %s" % name)
        html = open(op, encoding="utf-8").read()
        self.assertIn('href="commentable-html.css"', html)

    def test_assets_href_prefixes_refs(self):
        d = self._tmpdir()
        op = os.path.join(d, "r.html")
        code, _o, err = self._run(
            ["new_document.py", "--content", "-", "--key", "auto", "--label", "H",
             "--assets-href", "assets", "--out", op])
        self.assertEqual(code, 0, err)
        html = open(op, encoding="utf-8").read()
        self.assertIn('href="assets/commentable-html.css"', html)
        self.assertIn('src="assets/commentable-html.js"', html)

    def test_copy_assets_without_out_exits_2(self):
        code, _o, err = self._run(
            ["new_document.py", "--content", "-", "--key", "auto", "--label", "X", "--copy-assets"])
        self.assertEqual(code, 2)
        self.assertIn("--copy-assets needs --out", err)

    def test_nonshareable_stdout_uses_absolute_file_urls(self):
        code, out, err = self._run(
            ["new_document.py", "--content", "-", "--key", "auto", "--label", "S", "--source", "s.html"])
        self.assertEqual(code, 0, err)
        self.assertIn("file://", out)

    def test_assets_relative_without_out_exits_2(self):
        code, _out, err = self._run(
            ["new_document.py", "--content", "-", "--key", "auto", "--label", "S",
             "--source", "s.html", "--assets-relative"])
        self.assertEqual(code, 2)
        self.assertIn("--assets-relative needs --out", err)

    def test_nonshareable_stdout_ok_with_assets_href(self):
        code, out, err = self._run(
            ["new_document.py", "--content", "-", "--key", "auto", "--label", "S",
             "--source", "s.html", "--assets-href", "assets"])
        self.assertEqual(code, 0, err)
        self.assertIn('href="assets/commentable-html.css"', out)

    def test_nonshareable_stdout_ok_when_shareable(self):
        code, out, err = self._run(
            ["new_document.py", "--content", "-", "--key", "auto", "--label", "S",
             "--source", "s.html", "--shareable"])
        self.assertEqual(code, 0, err)
        self.assertNotIn('<link rel="stylesheet" href="commentable-html.css"', out)

    def test_shareable_and_nonshareable_are_mutually_exclusive(self):
        with self.assertRaises(SystemExit):
            self._run(["new_document.py", "--content", "-", "--key", "auto", "--label", "X",
                       "--shareable", "--nonshareable"])

    def test_default_template_nonshareable_is_dist_nonshareable(self):
        self.assertEqual(
            os.path.abspath(new_document._default_template(nonshareable=True)),
            os.path.abspath(os.path.join(_paths.DIST, "NONSHAREABLE.html")))


class DocTitleTests(unittest.TestCase):
    def test_ensure_doc_title_prepends_h1_when_missing(self):
        out = new_document.ensure_doc_title('<section><h2 id="a">Hi</h2></section>', "My Report")
        self.assertTrue(out.startswith('<header class="cmh-lede">'))
        self.assertIn("<h1>My Report</h1>", out)
        self.assertIn('<h2 id="a">Hi</h2>', out)

    def test_ensure_doc_title_escapes_label(self):
        out = new_document.ensure_doc_title("<p>x</p>", 'A & B "<x>"')
        self.assertIn("A &amp; B", out)
        self.assertNotIn("<x>", out)

    def test_ensure_doc_title_left_alone_when_fragment_has_h1(self):
        frag = "<h1>Author Title</h1><p>x</p>"
        self.assertEqual(new_document.ensure_doc_title(frag, "Ignored"), frag)

    def test_ensure_doc_title_left_alone_when_fragment_has_lede(self):
        frag = '<header class="cmh-lede"><h1>Lede</h1></header><p>x</p>'
        self.assertEqual(new_document.ensure_doc_title(frag, "Ignored"), frag)

    def test_ensure_doc_title_ignores_h1_inside_comment(self):
        # P2: an <h1> that only appears inside an HTML comment is not a rendered title, so
        # the raw-text scan wrongly suppressed the header; the parser-based check prepends one.
        frag = '<!-- <h1>Not a real title</h1> --><section><p>body</p></section>'
        out = new_document.ensure_doc_title(frag, "Real Title")
        self.assertTrue(out.startswith('<header class="cmh-lede">'))
        self.assertIn("<h1>Real Title</h1>", out)

    def test_ensure_doc_title_ignores_h1_inside_script(self):
        # P2: an <h1> inside a <script> body is data, not a rendered title.
        frag = '<script>var t = "<h1>fake</h1>";</script><p>body</p>'
        out = new_document.ensure_doc_title(frag, "Real Title")
        self.assertTrue(out.startswith('<header class="cmh-lede">'))
        self.assertIn("<h1>Real Title</h1>", out)

    def test_ensure_doc_title_ignores_nested_h1_and_lede(self):
        # P2: an h1 or a cmh-lede nested deep in the body is not the document's own top-level
        # title, so a title is still prepended.
        frag = ('<section><div class="cmh-lede"><h1>nested</h1></div>'
                '<article><h1>also nested</h1></article></section>')
        out = new_document.ensure_doc_title(frag, "Top Title")
        self.assertTrue(out.startswith('<header class="cmh-lede">'))
        self.assertIn("<h1>Top Title</h1>", out)

    def test_cli_prepends_visible_title_by_default(self):
        out = io.StringIO()
        err = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO('<section><h2 id="a">Hi</h2></section>')), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = new_document.main(
                ["new_document.py", "--content", "-", "--key", "title-v1",
                 "--label", "Titled Doc", "--kind", "generic", "--shareable"])
        self.assertEqual(code, 0, err.getvalue())
        body = out.getvalue()
        self.assertIn("<h1>Titled Doc</h1>", body)

    def test_cli_no_title_flag_suppresses_added_title(self):
        out = io.StringIO()
        err = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO('<section><h2 id="a">Hi</h2></section>')), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = new_document.main(
                ["new_document.py", "--content", "-", "--key", "notitle-v1",
                 "--label", "No Title Doc", "--kind", "generic", "--shareable", "--no-title"])
        self.assertEqual(code, 0, err.getvalue())
        self.assertNotIn("<h1>No Title Doc</h1>", out.getvalue())

    def test_help_documents_the_trust_boundary(self):
        # CMH-SEC-01: the --content fragment is trusted HTML and is not sanitized;
        # --help must state this so callers sanitize untrusted host HTML themselves.
        r = subprocess.run(
            [sys.executable, NEW_DOC_PY, "--help"],
            capture_output=True, text=True, cwd=TOOLS, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        text = r.stdout.lower()
        self.assertIn("trust boundary", text)
        self.assertIn("sanitize", text)

    def test_key_from_source_help_does_not_claim_label_fallback(self):
        # resolve_key deliberately does NOT fall back to --label; the help must not
        # claim it does, or callers will expect a same-label collision to be safe.
        r = subprocess.run(
            [sys.executable, NEW_DOC_PY, "--help"],
            capture_output=True, text=True, cwd=TOOLS, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        flat = " ".join(r.stdout.split())
        self.assertNotIn("defaults to --label", flat)
        self.assertIn("does not fall back to --label", flat)


class KindTests(unittest.TestCase):
    """The document kind (CMH-KIND): new_document requires --kind, stamps the meta, and
    only auto-adds a title for kinds that carry one."""

    def _call(self, argv, stdin=""):
        out = io.StringIO()
        err = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO(stdin)), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = new_document.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_doc_kinds_match_validate(self):
        sys.path.insert(0, TOOLS)
        import validate  # noqa: E402
        self.assertEqual(tuple(new_document.DOC_KINDS), tuple(validate._DOC_KINDS))

    def test_kind_is_required(self):
        err = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO("<p>x</p>")), \
                contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as cm:
            new_document.main(["new_document.py", "--content", "-", "--key", "k-v1",
                               "--label", "L", "--shareable"])
        self.assertEqual(cm.exception.code, 2)
        self.assertIn("kind", err.getvalue())

    def test_kind_stamps_meta(self):
        code, out, err = self._call(
            ["new_document.py", "--content", "-", "--key", "k-v1", "--label", "L",
             "--kind", "slides", "--shareable"],
            stdin="<section>slide</section>")
        self.assertEqual(code, 0, err)
        self.assertIn('<meta name="commentable-html-kind" content="slides"', out)

    def test_slides_kind_does_not_add_title(self):
        code, out, err = self._call(
            ["new_document.py", "--content", "-", "--key", "k-v1", "--label", "Deck",
             "--kind", "slides", "--shareable"],
            stdin="<section>slide</section>")
        self.assertEqual(code, 0, err)
        self.assertNotIn("<h1>Deck</h1>", out)

    def test_report_kind_adds_title_and_validates(self):
        code, out, err = self._call(
            ["new_document.py", "--content", "-", "--key", "k-v1", "--label", "Rep",
             "--kind", "report", "--shareable"],
            stdin="<p>body</p>")
        self.assertEqual(code, 0, err)
        self.assertIn("<h1>Rep</h1>", out)
        self.assertIn('content="report"', out)

    def test_make_document_stamps_kind(self):
        out = new_document.make_document(_template(), CONTENT, "mk-v1", "L", kind="board")
        self.assertIn('<meta name="commentable-html-kind" content="board"', out)

    def test_kind_mismatch_warning_is_advisory(self):
        code, out, err = self._call(
            ["new_document.py", "--content", "-", "--key", "k-v1", "--label", "Deck",
             "--kind", "report", "--shareable"],
            stdin="<h1>One</h1><hr><h1>Two</h1><hr><h1>Three</h1>")
        self.assertEqual(code, 0, err)
        self.assertIn("recommend_kind: warning: --kind report differs from recommended --kind slides", err)
        self.assertIn('<meta name="commentable-html-kind" content="report"', out)

    def test_report_fragment_is_section_wrapped_by_default(self):
        # CMH-TOOL-17: a report fragment with bare top-level <h2> blocks is wrapped in
        # <section> cards at create time (so the document never renders flat).
        code, out, err = self._call(
            ["new_document.py", "--content", "-", "--key", "k-v1", "--label", "Rep",
             "--kind", "report", "--shareable"],
            stdin='<h2 id="a">One</h2><p>a</p><h2 id="b">Two</h2><p>b</p>')
        self.assertEqual(code, 0, err)
        self.assertIn('<section aria-labelledby="a">', out)
        self.assertIn('<section aria-labelledby="b">', out)

    def test_no_wrap_sections_flag_leaves_fragment_flat(self):
        code, out, err = self._call(
            ["new_document.py", "--content", "-", "--key", "k-v1", "--label", "Rep",
             "--kind", "report", "--shareable", "--no-wrap-sections"],
            stdin='<h2 id="a">One</h2><p>a</p><h2 id="b">Two</h2><p>b</p>')
        self.assertEqual(code, 0, err)
        self.assertNotIn('aria-labelledby="a"', out)
        self.assertNotIn('aria-labelledby="b"', out)

    def test_report_gets_doc_stats_by_default(self):
        # CMH-STATS-01: a created report bakes the section/word/reading-time overview strip.
        code, out, err = self._call(
            ["new_document.py", "--content", "-", "--key", "k-v1", "--label", "Rep",
             "--kind", "report", "--shareable"],
            stdin='<h2 id="a">One</h2><p>a</p><h2 id="b">Two</h2><p>b</p>')
        self.assertEqual(code, 0, err)
        self.assertIn("data-cmh-doc-stats", out)
        self.assertIn("<strong>2</strong> sections", out)

    def test_no_stats_flag_skips_the_overview_strip(self):
        # CMH-STATS-01: --no-stats keeps new_document from baking the overview strip.
        code, out, err = self._call(
            ["new_document.py", "--content", "-", "--key", "k-v1", "--label", "Rep",
             "--kind", "report", "--shareable", "--no-stats"],
            stdin='<h2 id="a">One</h2><p>a</p><h2 id="b">Two</h2><p>b</p>')
        self.assertEqual(code, 0, err)
        self.assertNotIn("data-cmh-doc-stats", out)


class NewDocumentUnvalidatedOutputTests(unittest.TestCase):
    """CMH-TOOL-07: a document this tool could not CHECK is not written.

    `_self_validate` used to return `(None, None)` when the sibling `validate` module was
    unimportable; main() unpacked that into errors/warnings, `if errors:` was falsy, and the
    document was written UNVALIDATED - the one self-check disappearing exactly on the broken
    or partial install it exists for. The default is now to fail closed, with an explicit
    `--allow-unvalidated-output` opt-out (the same treatment chart_block.py got).
    """

    ARGV = ["new_document.py", "--content", "-", "--key", "unval-v1", "--label", "Unval",
            "--kind", "generic", "--shareable"]

    def _tmpdir(self):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: _rmtree(d))
        return d

    @contextlib.contextmanager
    def _import_of_validate_raising(self, exc):
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "validate":
                raise exc
            return real_import(name, *args, **kwargs)

        with mock.patch.dict(sys.modules), mock.patch.object(sys, "path", list(sys.path)), \
                mock.patch.object(builtins, "__import__", fake_import):
            sys.modules.pop("validate", None)
            yield

    def _run(self, extra_argv=(), stdin=CONTENT):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO(stdin)), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = new_document.main(list(self.ARGV) + list(extra_argv))
        return code, out.getvalue(), err.getvalue()

    def test_an_unimportable_validator_writes_nothing_instead_of_an_unchecked_document(self):
        with self._import_of_validate_raising(
                ModuleNotFoundError("No module named 'validate'", name="validate")):
            code, out, err = self._run()
        self.assertNotEqual(code, 0)
        self.assertEqual(out, "", "a document that could not be validated must not be emitted")
        self.assertIn("could not be self-validated", err)
        self.assertIn("'validate' tool could not be imported", err)
        self.assertIn("No module named 'validate'", err)
        self.assertIn("--allow-unvalidated-output", err)

    def test_no_file_is_written_when_the_document_could_not_be_checked(self):
        d = self._tmpdir()
        opath = os.path.join(d, "out.html")
        with self._import_of_validate_raising(
                ModuleNotFoundError("No module named 'validate'", name="validate")):
            code, _out, err = self._run(["--out", opath])
        self.assertNotEqual(code, 0, err)
        self.assertFalse(os.path.exists(opath),
                         "an unvalidatable document must not reach the filesystem")

    def test_a_partial_install_whose_validator_lacks_its_own_deps_also_fails_closed(self):
        # The likelier partial install: validate.py is present but one of ITS imports is
        # missing. That must take the same gate, not surface as a traceback.
        with self._import_of_validate_raising(
                ModuleNotFoundError("No module named 'checks.links'", name="checks.links")):
            code, out, err = self._run()
        self.assertNotEqual(code, 0)
        self.assertEqual(out, "")
        self.assertIn("checks.links", err, "the error must name what is actually missing")

    def test_a_corrupt_validator_source_fails_closed_rather_than_raising(self):
        with self._import_of_validate_raising(
                SyntaxError("unterminated triple-quoted string literal")):
            code, out, err = self._run()
        self.assertNotEqual(code, 0)
        self.assertEqual(out, "")
        self.assertIn("SyntaxError", err)

    def test_a_foreign_validate_module_is_not_accepted_as_the_checker(self):
        # An unrelated `validate` earlier on sys.path must not be able to hand back a clean
        # verdict it never computed.
        foreign = types.ModuleType("validate")
        foreign.__file__ = os.path.join(tempfile.gettempdir(), "validate.py")
        foreign.validate = lambda path, base_dir=None: ([], [])
        with mock.patch.dict(sys.modules, {"validate": foreign}):
            module, reason = new_document._load_validator()
        self.assertIsNone(module)
        self.assertIn("not this skill's", reason)

    def test_the_real_validator_is_accepted_through_a_resolved_path(self):
        # The containment guard must not false-alarm on the genuine validator, including the
        # alternate spellings a real install produces (a differently-cased path, or one that
        # walks through `..`), which is what the two-form comparison exists for.
        module, reason = new_document._load_validator()
        self.assertIsNone(reason)
        self.assertIsNotNone(module)
        real = os.path.join(TOOLS, "validate", "validate.py")
        self.assertTrue(new_document._contained(real))
        self.assertTrue(new_document._contained(
            os.path.join(TOOLS, "authoring", "..", "validate", "validate.py")))
        if os.path.normcase("A") == os.path.normcase("a"):
            self.assertTrue(new_document._contained(real.upper()))

    def test_a_non_string_module_file_is_refused_rather_than_raising(self):
        # Every cause must come back as a REASON; a module whose __file__ is not a path must
        # not escape as a traceback (which would also make the opt-out unreachable).
        odd = types.ModuleType("validate")
        odd.__file__ = object()
        with mock.patch.dict(sys.modules, {"validate": odd}):
            module, reason = new_document._load_validator()
        self.assertIsNone(module)
        self.assertIn("not this skill's", reason)

    def test_a_misbehaving_pathlike_file_is_refused_rather_than_raising(self):
        # A PathLike is only a promise of __fspath__: one that hands back bytes, or raises,
        # must be refused rather than reaching realpath/startswith and escaping as a
        # traceback. A well-behaved PathLike naming the real validator is still accepted.
        class BytesPath:
            def __fspath__(self):
                return b"tools/validate/validate.py"

        class BrokenPath:
            def __fspath__(self):
                raise RuntimeError("no path here")

        for value in (BytesPath(), BrokenPath()):
            with self.subTest(value=type(value).__name__):
                self.assertFalse(new_document._contained(value))
        self.assertTrue(new_document._contained(Path(TOOLS) / "validate" / "validate.py"))

    def test_an_unformattable_module_file_still_comes_back_as_a_reason(self):
        # The refusal MESSAGE interpolates __file__, so a value that cannot be formatted
        # (a tuple, or one whose __str__ raises) must not turn the named reason back into
        # the traceback this seam exists to replace.
        class Hostile:
            def __str__(self):
                raise RuntimeError("nope")

        for value in ((1, 2), Hostile()):
            with self.subTest(value=type(value).__name__):
                odd = types.ModuleType("validate")
                odd.__file__ = value
                with mock.patch.dict(sys.modules, {"validate": odd}):
                    module, reason = new_document._load_validator()
                self.assertIsNone(module)
                self.assertIn("not this skill's", reason)

    def test_contained_refuses_a_non_path_value_without_raising(self):
        # The same input sweep the chart_block seam pins, so the two stay provably
        # behavior-identical rather than drifting apart.
        class HostileStr(str):
            def __bool__(self):
                raise RuntimeError("nope")

        for value in (object(), 3, b"tools/validate/validate.py", None, "",
                      HostileStr("tools/validate/validate.py")):
            with self.subTest(value=type(value).__name__):
                self.assertFalse(new_document._contained(value))

    def test_a_path_that_cannot_be_canonicalized_is_refused_rather_than_raising(self):
        real = os.path.join(TOOLS, "validate", "validate.py")
        for error in (OSError("bad path"), ValueError("embedded null byte")):
            with self.subTest(error=type(error).__name__):
                with mock.patch.object(new_document.os.path, "abspath", side_effect=error):
                    self.assertFalse(new_document._contained(real))

    def test_a_module_whose_file_attribute_raises_is_refused_rather_than_raising(self):
        class LazyModule:
            @property
            def __file__(self):
                raise RuntimeError("still loading")

            def validate(self, path, base_dir=None):
                return ([], [])

        with mock.patch.dict(sys.modules, {"validate": LazyModule()}):
            module, reason = new_document._load_validator()
        self.assertIsNone(module)
        self.assertIn("not this skill's", reason)

    def test_a_foreign_validate_on_sys_path_is_refused_before_its_body_runs(self):
        # The origin is checked BEFORE the import, so an unrelated `validate` earlier on
        # sys.path must be refused without executing its module body at all.
        import importlib

        d = self._tmpdir()
        sentinel = os.path.join(d, "ran.txt")
        with open(os.path.join(d, "validate.py"), "w", encoding="utf-8") as fh:
            fh.write("import pathlib\n"
                     "pathlib.Path(%r).write_text('ran', encoding='utf-8')\n"
                     "def validate(path, base_dir=None):\n"
                     "    return ([], [])\n" % sentinel)
        with mock.patch.dict(sys.modules), mock.patch.object(sys, "path", [d] + list(sys.path)):
            sys.modules.pop("validate", None)
            importlib.invalidate_caches()
            module, reason = new_document._load_validator()
        self.assertIsNone(module)
        self.assertIn("not this skill's", reason)
        self.assertFalse(os.path.exists(sentinel),
                         "the foreign module's body must never be executed")

    def test_a_cached_validate_without_a_file_is_refused(self):
        anonymous = types.ModuleType("validate")
        anonymous.validate = lambda path, base_dir=None: ([], [])
        with mock.patch.dict(sys.modules, {"validate": anonymous}):
            module, reason = new_document._load_validator()
        self.assertIsNone(module)
        self.assertIn("an unknown location", reason)

    def test_a_crashing_validator_fails_closed_rather_than_raising(self):
        boom = types.SimpleNamespace(validate=mock.Mock(side_effect=RuntimeError("kaboom")))
        with mock.patch.object(new_document, "_load_validator", return_value=(boom, None)):
            code, out, err = self._run()
        self.assertNotEqual(code, 0)
        self.assertEqual(out, "")
        self.assertIn("validator could not run", err)
        self.assertIn("kaboom", err)

    def test_a_validator_answering_in_an_unexpected_shape_is_not_treated_as_clean(self):
        # `(None, None)` is the exact old fail-open shape: it satisfies a bare 2-tuple test and
        # then reads as "no errors, no warnings". It must count as "could not check".
        for outcome in (None, ([], [], []), (None, None), ([], None), ("", "")):
            with self.subTest(outcome=outcome):
                broken = types.SimpleNamespace(validate=mock.Mock(return_value=outcome))
                with mock.patch.object(new_document, "_load_validator", return_value=(broken, None)):
                    code, out, err = self._run()
                self.assertNotEqual(code, 0)
                self.assertEqual(out, "")
                self.assertIn("unexpected result", err)

    def test_the_explicit_opt_out_still_writes_with_a_warning(self):
        with self._import_of_validate_raising(
                ModuleNotFoundError("No module named 'validate'", name="validate")):
            code, out, err = self._run(["--allow-unvalidated-output"])
        self.assertEqual(code, 0, err)
        self.assertIn('data-comment-key="unval-v1"', out)
        self.assertIn("not self-validated", err)

    def test_the_opt_out_does_not_suppress_a_real_validation_failure(self):
        # The flag means "I accept a document that could not be CHECKED", never "skip the
        # check". Widening it into the latter must fail this test.
        with mock.patch.object(new_document, "_self_validate_result",
                               return_value=((["boom"], []), None)):
            code, out, err = self._run(["--allow-unvalidated-output"])
        self.assertNotEqual(code, 0)
        self.assertEqual(out, "")
        self.assertIn("does not validate", err)
        self.assertIn("boom", err)

    def test_a_working_validator_with_the_flag_still_validates_and_succeeds(self):
        code, out, err = self._run(["--allow-unvalidated-output"])
        self.assertEqual(code, 0, err)
        self.assertIn('data-comment-key="unval-v1"', out)
        self.assertNotIn("not self-validated", err)


if __name__ == "__main__":
    unittest.main()
