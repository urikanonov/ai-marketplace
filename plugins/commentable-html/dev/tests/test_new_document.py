#!/usr/bin/env python3
"""Regression tests for new_document.py (the template-clone document builder)."""
import contextlib
import hashlib
import io
import os
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

    def test_doc_comment_example_root_is_not_the_one_edited(self):
        # The template's top documentation comment holds a decoy
        # `<main id="commentRoot" data-comment-key="my-doc">`. It must survive
        # untouched, and OUR key must land on the real (last) root instead.
        out = new_document.make_document(_template(), CONTENT, "my-report-v1", "My Report")
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
        k1 = new_document.resolve_key("auto", "My Report")
        k2 = new_document.resolve_key("auto", "My Report")
        k3 = new_document.resolve_key("auto", "Another Report")
        self.assertEqual(k1, k2)
        self.assertNotEqual(k1, k3)
        self.assertTrue(k1.startswith("cmh-"))
        self.assertEqual(len(k1), 16)
        self.assertNotIn(k1, new_document.REFUSED_KEYS)

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


class MainCliTests(unittest.TestCase):
    def _tmpdir(self):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: _rmtree(d))
        return d

    def _call_main(self, argv, stdin=""):
        out = io.StringIO()
        err = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO(stdin)), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = new_document.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_stdin_content_to_stdout(self):
        code, out, err = self._call_main(
            ["new_document.py", "--content", "-", "--key", "cli-v1", "--label", "CLI Doc"],
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

    def test_key_auto_derives_stable_key_from_label(self):
        code, out, err = self._call_main(
            ["new_document.py", "--content", "-", "--key", "auto", "--label", "Auto Key Label"],
            stdin=CONTENT,
        )
        self.assertEqual(code, 0, err)
        expected = "cmh-" + hashlib.sha256("Auto Key Label".encode("utf-8")).hexdigest()[:12]
        self.assertIn('data-comment-key="%s"' % expected, out)

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
                "--generated",
                "2026-07-09T20:30:00Z",
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
            [sys.executable, NEW_DOC_PY, "--content", "-", "--key", "sub-v1", "--label", "Sub"],
            input=CONTENT, capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('data-comment-key="sub-v1"', r.stdout)


def _rmtree(path):
    import shutil
    shutil.rmtree(path, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
