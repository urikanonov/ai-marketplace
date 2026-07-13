#!/usr/bin/env python3
"""Regression tests for new_document.py (the template-clone document builder)."""
import contextlib
import hashlib
import io
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402  shared pkg/dev split path constants
ROOT = _paths.PKG
TOOLS = _paths.TOOLS
sys.path.insert(0, TOOLS)
import new_document  # noqa: E402

NEW_DOC_PY = os.path.join(TOOLS, "new_document.py")
TEMPLATE = os.path.join(ROOT, "dist", "PORTABLE.html")

CONTENT = '<section><h2 id="a">Hi</h2><p>x</p></section>'


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

    def test_output_validates_clean(self):
        out = new_document.make_document(_template(), CONTENT, "my-report-v1", "My Report", "src.md")
        errors = new_document._self_validate(out)
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
        self.assertNotIn("data-doc-source", tag)  # template's dist/PORTABLE.html source is dropped

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
        for bad in ("commentable-html-demo", "my-doc", "commentable-html-nonportable-demo"):
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

    def test_self_validate_degrades_when_validator_missing(self):
        with mock.patch.dict(sys.modules, {"validate": None}):
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
        for name in ("PORTABLE.html", "NONPORTABLE.html"):
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
             "--portable"],
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
             "--portable", "--out", op],
            stdin=CONTENT,
        )
        self.assertEqual(code, 0, err)
        expected = "cmh-" + hashlib.sha256(os.path.abspath(op).encode("utf-8")).hexdigest()[:12]
        html = open(op, encoding="utf-8").read()
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
                "--portable",
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
                "--portable",
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
                "--portable",
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
        missing = os.path.join(d, "missing-portable-source.html")
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
                mock.patch.object(new_document, "_self_validate", return_value=["boom"]):
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
             "--kind", "generic", "--portable"],
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


class NonPortableCliTests(unittest.TestCase):
    _LINK_RE = re.compile(r'<link\b[^>]*href="[^"]*commentable-html\.css"')

    def _tmpdir(self):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: _rmtree(d))
        return d

    def _run(self, argv, stdin=CONTENT):
        if "--kind" not in argv:
            argv = argv[:1] + ["--kind", "generic"] + argv[1:]
        out = io.StringIO()
        err = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO(stdin)), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = new_document.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_default_mode_is_nonportable_and_refs_resolve_to_dist(self):
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

    def test_assets_relative_restores_relative_dist_refs(self):
        d = self._tmpdir()
        op = os.path.join(d, "r.html")
        code, _o, err = self._run(
            ["new_document.py", "--content", "-", "--key", "auto", "--label", "NP",
             "--assets-relative", "--out", op])
        self.assertEqual(code, 0, err)
        html = open(op, encoding="utf-8").read()
        self.assertRegex(html, r'<link\b[^>]*href="[^"]*/dist/commentable-html\.css"')

    def test_portable_flag_inlines_layer(self):
        d = self._tmpdir()
        op = os.path.join(d, "r.html")
        code, _o, err = self._run(
            ["new_document.py", "--content", "-", "--key", "auto", "--label", "P",
             "--portable", "--out", op])
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

    def test_nonportable_stdout_uses_absolute_file_urls(self):
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

    def test_nonportable_stdout_ok_with_assets_href(self):
        code, out, err = self._run(
            ["new_document.py", "--content", "-", "--key", "auto", "--label", "S",
             "--source", "s.html", "--assets-href", "assets"])
        self.assertEqual(code, 0, err)
        self.assertIn('href="assets/commentable-html.css"', out)

    def test_nonportable_stdout_ok_when_portable(self):
        code, out, err = self._run(
            ["new_document.py", "--content", "-", "--key", "auto", "--label", "S",
             "--source", "s.html", "--portable"])
        self.assertEqual(code, 0, err)
        self.assertNotIn('<link rel="stylesheet" href="commentable-html.css"', out)

    def test_portable_and_nonportable_are_mutually_exclusive(self):
        with self.assertRaises(SystemExit):
            self._run(["new_document.py", "--content", "-", "--key", "auto", "--label", "X",
                       "--portable", "--nonportable"])

    def test_default_template_nonportable_is_dist_nonportable(self):
        self.assertEqual(
            os.path.abspath(new_document._default_template(nonportable=True)),
            os.path.abspath(os.path.join(_paths.DIST, "NONPORTABLE.html")))


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
                 "--label", "Titled Doc", "--kind", "generic", "--portable"])
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
                 "--label", "No Title Doc", "--kind", "generic", "--portable", "--no-title"])
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
                               "--label", "L", "--portable"])
        self.assertEqual(cm.exception.code, 2)
        self.assertIn("kind", err.getvalue())

    def test_kind_stamps_meta(self):
        code, out, err = self._call(
            ["new_document.py", "--content", "-", "--key", "k-v1", "--label", "L",
             "--kind", "slides", "--portable"],
            stdin="<section>slide</section>")
        self.assertEqual(code, 0, err)
        self.assertIn('<meta name="commentable-html-kind" content="slides"', out)

    def test_slides_kind_does_not_add_title(self):
        code, out, err = self._call(
            ["new_document.py", "--content", "-", "--key", "k-v1", "--label", "Deck",
             "--kind", "slides", "--portable"],
            stdin="<section>slide</section>")
        self.assertEqual(code, 0, err)
        self.assertNotIn("<h1>Deck</h1>", out)

    def test_report_kind_adds_title_and_validates(self):
        code, out, err = self._call(
            ["new_document.py", "--content", "-", "--key", "k-v1", "--label", "Rep",
             "--kind", "report", "--portable"],
            stdin="<p>body</p>")
        self.assertEqual(code, 0, err)
        self.assertIn("<h1>Rep</h1>", out)
        self.assertIn('content="report"', out)

    def test_make_document_stamps_kind(self):
        out = new_document.make_document(_template(), CONTENT, "mk-v1", "L", kind="board")
        self.assertIn('<meta name="commentable-html-kind" content="board"', out)


if __name__ == "__main__":
    unittest.main()
