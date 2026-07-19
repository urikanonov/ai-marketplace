#!/usr/bin/env python3
"""CMH-STAMP-01/02: provenance stamps - new_document stamps commentable-html-created, and
validate.py stamps commentable-html-validated only on a strict-clean pass (opt out --no-stamp)."""
import contextlib
import io
import os
from pathlib import Path
import re
import shutil
import subprocess
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

    def test_stamp_session_sets_id_and_agent(self):
        out = doc_stamp.stamp_session("<head></head>", "sess-123", agent="copilot")
        self.assertEqual(doc_stamp.get_meta(out, doc_stamp.SESSION_META), "sess-123")
        self.assertEqual(doc_stamp.get_meta(out, doc_stamp.AGENT_META), "copilot")

    def test_stamp_session_without_agent_omits_agent_meta(self):
        out = doc_stamp.stamp_session("<head></head>", "sess-123")
        self.assertEqual(doc_stamp.get_meta(out, doc_stamp.SESSION_META), "sess-123")
        self.assertIsNone(doc_stamp.get_meta(out, doc_stamp.AGENT_META))

    def test_stamp_session_is_idempotent(self):
        once = doc_stamp.stamp_session("<head></head>", "first", agent="copilot")
        twice = doc_stamp.stamp_session(once, "second", agent="claude")
        self.assertEqual(doc_stamp.get_meta(twice, doc_stamp.SESSION_META), "first")
        self.assertEqual(doc_stamp.get_meta(twice, doc_stamp.AGENT_META), "copilot")

    def test_stamp_session_blank_is_noop(self):
        self.assertNotIn(doc_stamp.SESSION_META, doc_stamp.stamp_session("<head></head>", ""))
        self.assertNotIn(doc_stamp.SESSION_META, doc_stamp.stamp_session("<head></head>", None))

    def test_source_basename_strips_posix_and_windows_directories(self):
        self.assertEqual(
            doc_stamp.source_basename("/home/alice/internal/report.html"),
            "report.html",
        )
        self.assertEqual(
            doc_stamp.source_basename(r"C:\Users\alice\internal\report.html"),
            "report.html",
        )

    def test_source_basename_never_falls_back_to_sensitive_path_parts(self):
        self.assertEqual(doc_stamp.source_basename(r"C:\Users\alice\reports\\"), "document")
        self.assertEqual(
            doc_stamp.source_basename("https://internal.example/report.html?user=alice#draft"),
            "report.html",
        )
        self.assertEqual(doc_stamp.source_basename("C:report.html"), "report.html")
        self.assertEqual(doc_stamp.source_basename("/tmp/report#1.html"), "report#1.html")
        self.assertEqual(doc_stamp.source_basename("/tmp/report?1.html"), "report?1.html")

    def test_committed_html_source_provenance_is_basename_only(self):
        repo = Path(_paths.PLUGIN_ROOT).parents[1]
        tracked = subprocess.check_output(
            ["git", "ls-files", "*.html"], cwd=repo, text=True).splitlines()
        leaks = []
        attr_re = re.compile(r'data-doc-source\s*=\s*(["\'])(.*?)\1', re.IGNORECASE)
        for relative in tracked:
            html = (repo / relative).read_text(encoding="utf-8")
            for match in attr_re.finditer(html):
                if "/" in match.group(2) or "\\" in match.group(2):
                    leaks.append("%s: %s" % (relative, match.group(2)))
        self.assertEqual(leaks, [], "path-bearing source provenance: %r" % leaks)

    def test_detect_session_reads_copilot_env(self):
        self.assertEqual(doc_stamp.detect_session({"COPILOT_AGENT_SESSION_ID": "cop-1"}),
                         ("cop-1", "copilot"))

    def test_detect_session_reads_claude_env(self):
        self.assertEqual(doc_stamp.detect_session({"CLAUDE_CODE_SESSION_ID": "cc-1"}),
                         ("cc-1", "claude"))

    def test_detect_session_reads_claude_legacy_env(self):
        self.assertEqual(doc_stamp.detect_session({"CLAUDE_SESSION_ID": "cl-1"}),
                         ("cl-1", "claude"))

    def test_detect_session_prefers_copilot_when_both_present_and_no_runtime_marker(self):
        self.assertEqual(
            doc_stamp.detect_session({"COPILOT_AGENT_SESSION_ID": "cop-1", "CLAUDE_CODE_SESSION_ID": "cc-1"}),
            ("cop-1", "copilot"))

    def test_detect_session_prefers_the_running_agent_when_both_present(self):
        # A tool run by Claude under a Copilot parent inherits both session ids; the CLAUDECODE
        # runtime marker attributes it to the agent actually executing the tool.
        self.assertEqual(
            doc_stamp.detect_session({"COPILOT_AGENT_SESSION_ID": "cop-1", "CLAUDE_CODE_SESSION_ID": "cc-1",
                                      "CLAUDECODE": "1", "COPILOT_CLI": "1"}),
            ("cc-1", "claude"))
        self.assertEqual(
            doc_stamp.detect_session({"COPILOT_AGENT_SESSION_ID": "cop-1", "CLAUDE_CODE_SESSION_ID": "cc-1",
                                      "COPILOT_CLI": "1"}),
            ("cop-1", "copilot"))

    def test_detect_session_absent_is_none(self):
        self.assertEqual(doc_stamp.detect_session({}), (None, None))
        self.assertEqual(doc_stamp.detect_session({"COPILOT_AGENT_SESSION_ID": "  "}), (None, None))


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


class NewDocumentSessionStampTests(unittest.TestCase):
    """CMH-STAMP-04: new_document stamps the creating AI session id by default (from --session-id
    or the environment), records the agent, and suppresses it with --no-session-id."""

    def test_stamps_session_from_flag(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            code, html, err = _run_new_document(
                ["new_document.py", "--content", "-", "--key", "ss-v1", "--label", "L",
                 "--kind", "report", "--portable", "--session-id", "flag-sess", "--agent", "claude"])
        self.assertEqual(code, 0, err)
        self.assertEqual(doc_stamp.get_meta(html, doc_stamp.SESSION_META), "flag-sess")
        self.assertEqual(doc_stamp.get_meta(html, doc_stamp.AGENT_META), "claude")

    def test_stamps_session_from_environment_by_default(self):
        with mock.patch.dict(os.environ, {"COPILOT_AGENT_SESSION_ID": "env-sess"}, clear=True):
            code, html, err = _run_new_document(
                ["new_document.py", "--content", "-", "--key", "ss-v2", "--label", "L",
                 "--kind", "report", "--portable"])
        self.assertEqual(code, 0, err)
        self.assertEqual(doc_stamp.get_meta(html, doc_stamp.SESSION_META), "env-sess")
        self.assertEqual(doc_stamp.get_meta(html, doc_stamp.AGENT_META), "copilot")

    def test_no_session_id_flag_suppresses_the_stamp(self):
        with mock.patch.dict(os.environ, {"COPILOT_AGENT_SESSION_ID": "env-sess"}, clear=True):
            code, html, err = _run_new_document(
                ["new_document.py", "--content", "-", "--key", "ss-v3", "--label", "L",
                 "--kind", "report", "--portable", "--no-session-id"])
        self.assertEqual(code, 0, err)
        self.assertIsNone(doc_stamp.get_meta(html, doc_stamp.SESSION_META))

    def test_absent_when_no_session_id_is_available(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            code, html, err = _run_new_document(
                ["new_document.py", "--content", "-", "--key", "ss-v4", "--label", "L",
                 "--kind", "report", "--portable"])
        self.assertEqual(code, 0, err)
        self.assertIsNone(doc_stamp.get_meta(html, doc_stamp.SESSION_META))


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
