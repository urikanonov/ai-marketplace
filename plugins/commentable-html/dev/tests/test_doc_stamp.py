#!/usr/bin/env python3
"""CMH-STAMP-01/02: provenance stamps - new_document stamps commentable-html-created, and
validate.py stamps commentable-html-validated only on a strict-clean pass (opt out --no-stamp)."""
import contextlib
import io
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402
sys.path.insert(0, _paths.TOOLS)
import doc_stamp  # noqa: E402
import new_document  # noqa: E402
import validate  # noqa: E402

CONTENT = '<section><h1>Report</h1><h2 id="a">Hi</h2><p>body text</p></section>'


class DocStampUnitTests(unittest.TestCase):
    def test_set_and_get_roundtrip(self):
        out = doc_stamp.set_meta("<html><head></head><body></body></html>",
                                 doc_stamp.CREATED_META, "2026-01-02T03:04:05Z")
        self.assertEqual(doc_stamp.get_meta(out, doc_stamp.CREATED_META), "2026-01-02T03:04:05Z")

    def test_set_meta_updates_existing(self):
        html = '<head><meta name="commentable-html-validated" content="old" /></head>'
        out = doc_stamp.set_meta(html, doc_stamp.VALIDATED_META, "new")
        self.assertEqual(doc_stamp.get_meta(out, doc_stamp.VALIDATED_META), "new")
        self.assertNotIn("old", out)

    def test_get_absent_is_none(self):
        self.assertIsNone(doc_stamp.get_meta("<head></head>", doc_stamp.VALIDATED_META))

    def test_now_iso_is_utc_second_precision(self):
        self.assertRegex(doc_stamp.now_iso(), r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")

    def test_stamp_created_is_idempotent(self):
        once = doc_stamp.stamp_created("<head></head>", when="2026-01-01T00:00:00Z")
        twice = doc_stamp.stamp_created(once, when="2030-01-01T00:00:00Z")
        self.assertEqual(doc_stamp.get_meta(twice, doc_stamp.CREATED_META), "2026-01-01T00:00:00Z")

    def test_content_quote_cannot_break_the_tag(self):
        out = doc_stamp.set_meta("<head></head>", doc_stamp.CREATED_META, 'a"b<c')
        # The value is attribute-escaped; get_meta reads back the escaped form intact.
        self.assertIn("commentable-html-created", out)
        self.assertNotIn('content="a"b', out)


def _run_new_document(argv, stdin=CONTENT):
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.object(sys, "stdin", io.StringIO(stdin)), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = new_document.main(argv)
    return code, out.getvalue(), err.getvalue()


class NewDocumentCreatedStampTests(unittest.TestCase):
    def test_new_document_stamps_created(self):
        code, html, err = _run_new_document(
            ["new_document.py", "--content", "-", "--key", "cs-v1", "--label", "L",
             "--kind", "report", "--portable"])
        self.assertEqual(code, 0, err)
        created = doc_stamp.get_meta(html, doc_stamp.CREATED_META)
        self.assertIsNotNone(created, "new_document must stamp commentable-html-created")
        self.assertRegex(created, r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")

    def test_new_document_does_not_claim_validation(self):
        code, html, err = _run_new_document(
            ["new_document.py", "--content", "-", "--key", "cs-v2", "--label", "L",
             "--kind", "report", "--portable"])
        self.assertEqual(code, 0, err)
        self.assertIsNone(doc_stamp.get_meta(html, doc_stamp.VALIDATED_META),
                          "creation must not claim validation")


class ValidateStampTests(unittest.TestCase):
    def _tmp(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        return d

    def _make_doc(self, content=CONTENT):
        p = os.path.join(self._tmp(), "doc.html")
        code, _out, err = _run_new_document(
            ["new_document.py", "--content", "-", "--key", "vs-v1", "--label", "L",
             "--kind", "report", "--source", "doc.html", "--portable", "--out", p], stdin=content)
        self.assertEqual(code, 0, err)
        return p

    def _read(self, p):
        with open(p, encoding="utf-8") as fh:
            return fh.read()

    def _run_validate(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = validate.main(argv)
        return code, out.getvalue() + err.getvalue()

    def test_validate_stamps_validated_on_clean_file(self):
        p = self._make_doc()
        self.assertIsNone(doc_stamp.get_meta(self._read(p), doc_stamp.VALIDATED_META))
        code, out = self._run_validate(["validate.py", p])
        self.assertEqual(code, 0, out)
        stamp = doc_stamp.get_meta(self._read(p), doc_stamp.VALIDATED_META)
        self.assertIsNotNone(stamp, "validate.py must stamp validated on a strict-clean file")
        self.assertRegex(stamp, r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")

    def test_validate_no_stamp_flag_leaves_file_unstamped(self):
        p = self._make_doc()
        code, out = self._run_validate(["validate.py", "--no-stamp", p])
        self.assertEqual(code, 0, out)
        self.assertIsNone(doc_stamp.get_meta(self._read(p), doc_stamp.VALIDATED_META))

    def test_validate_does_not_stamp_a_doc_with_warnings(self):
        # A cm-skip code block warns (CMH-VAL-12) but does not error, so the doc is NOT strict-clean
        # and must NOT be stamped validated.
        warn_content = (CONTENT[:-len("</section>")]
                        + '<pre class="cm-skip"><code>plain {}</code></pre></section>')
        p = self._make_doc(content=warn_content)
        code, out = self._run_validate(["validate.py", p])
        self.assertEqual(code, 0, out)  # a warning is not a failure without --strict
        self.assertIsNone(doc_stamp.get_meta(self._read(p), doc_stamp.VALIDATED_META),
                          "a doc with warnings is not strict-clean and must not be stamped")


if __name__ == "__main__":
    unittest.main()
