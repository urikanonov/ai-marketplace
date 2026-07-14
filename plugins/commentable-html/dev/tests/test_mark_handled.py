#!/usr/bin/env python3
"""Regression tests for mark_handled.py (the zero-token handled-id helper)."""
import contextlib
import io
import json
import os
import re
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402  shared pkg/dev split path constants
TOOLS = _paths.TOOLS
sys.path.insert(0, TOOLS)
import mark_handled  # noqa: E402

MARK_PY = os.path.join(TOOLS, "authoring", "mark_handled.py")

DOC = (
    "<!DOCTYPE html>\n<html><body>\n"
    "<title>x</title>\n"
    '<script type="application/json" id="handledCommentIds">\n[]\n</script>\n'
    "<main>body</main>\n"
    "</body></html>\n"
)


class MarkHandledTests(unittest.TestCase):
    def _tmp(self, content=DOC, newline="\n"):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        p = os.path.join(d, "doc.html")
        with open(p, "w", encoding="utf-8", newline="") as fh:
            fh.write(content.replace("\n", newline) if newline != "\n" else content)
        return p

    def _handled(self, path):
        import json
        import re
        with open(path, encoding="utf-8") as fh:
            raw = fh.read()
        m = re.search(r'id="handledCommentIds">(.*?)</script>', raw, re.S)
        return json.loads(m.group(1).strip() or "[]")

    def _call_main(self, argv, stdin=""):
        out = io.StringIO()
        err = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO(stdin)), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = mark_handled.main(argv)
        return code, out.getvalue(), err.getvalue()

    # -- core --------------------------------------------------------------- #
    def test_appends_ids(self):
        p = self._tmp()
        added = mark_handled.mark_handled(p, ["cabc123", "cdef456"])
        self.assertEqual(added, ["cabc123", "cdef456"])
        self.assertEqual(self._handled(p), ["cabc123", "cdef456"])

    def test_dedupes_and_preserves_order(self):
        p = self._tmp()
        mark_handled.mark_handled(p, ["cabc123"])
        added = mark_handled.mark_handled(p, ["cabc123", "cnew999"])
        self.assertEqual(added, ["cnew999"])
        self.assertEqual(self._handled(p), ["cabc123", "cnew999"])

    def test_nothing_to_add_returns_empty(self):
        p = self._tmp()
        mark_handled.mark_handled(p, ["cabc123"])
        self.assertEqual(mark_handled.mark_handled(p, ["cabc123"]), [])

    def test_rejects_unsafe_id_without_writing(self):
        p = self._tmp()
        with open(p, encoding="utf-8") as fh:
            before = fh.read()
        with self.assertRaises(ValueError):
            mark_handled.mark_handled(p, ["not a valid id"])
        with open(p, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), before)

    def test_missing_block_raises(self):
        p = self._tmp(content="<html><body>no block</body></html>\n")
        with self.assertRaises(ValueError):
            mark_handled.mark_handled(p, ["cabc123"])

    def test_existing_unsafe_id_refuses_to_rewrite(self):
        doc = DOC.replace("[]", '["not a safe id"]')
        p = self._tmp(content=doc)
        with open(p, encoding="utf-8") as fh:
            before = fh.read()
        with self.assertRaises(ValueError):
            mark_handled.mark_handled(p, ["cabc123"])
        with open(p, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), before)

    def test_only_the_block_changes(self):
        p = self._tmp()
        with open(p, encoding="utf-8") as fh:
            before = fh.read()
        mark_handled.mark_handled(p, ["cabc123"])
        with open(p, encoding="utf-8") as fh:
            after = fh.read()
        # Everything outside the handled block is byte-identical.
        self.assertEqual(before.split("handledCommentIds")[0], after.split("handledCommentIds")[0])
        self.assertEqual(before.rsplit("</script>", 1)[1], after.rsplit("</script>", 1)[1])

    def test_preserves_crlf(self):
        p = self._tmp(newline="\r\n")
        mark_handled.mark_handled(p, ["cabc123"])
        with open(p, "rb") as fh:
            self.assertIn(b"\r\n", fh.read())

    def test_dominant_lf_survives_stray_crlf(self):
        # A mostly-LF file with a single stray CRLF must stay LF (dominant style),
        # not be rewritten wholesale to CRLF.
        p = self._tmp()
        with open(p, "rb") as fh:
            raw = fh.read()
        # Inject one lone CRLF while leaving the rest as LF.
        raw = raw.replace(b"\n", b"\r\n", 1)
        with open(p, "wb") as fh:
            fh.write(raw)
        mark_handled.mark_handled(p, ["cabc123"])
        with open(p, "rb") as fh:
            out = fh.read()
        self.assertNotIn(b"\r\n", out)

    def test_bundle_parsing(self):
        ids = mark_handled._ids_from_bundle('blah\nHANDLED_IDS_JSON: ["cabc123", "cdef456"]\n')
        self.assertEqual(ids, ["cabc123", "cdef456"])

    def test_bundle_parsing_uses_last_authoritative_contract(self):
        bundle = (
            'Diff label: x HANDLED_IDS_JSON: []\n'
            '  HANDLED_IDS_JSON: []\n'
            'HANDLED_IDS_JSON: ["cabcdef123"]\n'
        )
        self.assertEqual(mark_handled._ids_from_bundle(bundle), ["cabcdef123"])

    def test_bundle_parsing_falls_back_to_inline_marker(self):
        self.assertEqual(mark_handled._ids_from_bundle('prefix HANDLED_IDS_JSON: ["cabc123"]'), ["cabc123"])

    def test_bundle_parsing_requires_marker(self):
        with self.assertRaises(ValueError) as cm:
            mark_handled._ids_from_bundle("no handled ids here")
        self.assertIn("no 'HANDLED_IDS_JSON", str(cm.exception))

    def test_finds_block_with_single_quoted_id(self):
        doc = DOC.replace('id="handledCommentIds"', "id='handledCommentIds'")
        p = self._tmp(content=doc)
        self.assertEqual(mark_handled.mark_handled(p, ["cabc123"]), ["cabc123"])
        with open(p, encoding="utf-8") as fh:
            self.assertIn("cabc123", fh.read())

    def test_finds_block_with_unquoted_id(self):
        doc = DOC.replace('id="handledCommentIds"', "id=handledCommentIds")
        p = self._tmp(content=doc)
        self.assertEqual(mark_handled.mark_handled(p, ["cabc123"]), ["cabc123"])
        # Read back tolerantly (the id attribute is unquoted in this document).
        with open(p, encoding="utf-8") as fh:
            self.assertIn("cabc123", fh.read())

    def test_ignores_commented_decoy_block(self):
        # A handledCommentIds block inside an HTML comment must NOT be edited; the
        # real one after it is the one that gets the id (parser skips comments).
        doc = DOC.replace(
            "<title>x</title>\n",
            '<!-- leftover: <script type="application/json" id="handledCommentIds">'
            '["cdecoy0"]</script> -->\n<title>x</title>\n')
        p = self._tmp(content=doc)
        self.assertEqual(mark_handled.mark_handled(p, ["cabc123"]), ["cabc123"])
        with open(p, encoding="utf-8") as fh:
            out = fh.read()
        self.assertEqual(out.count("cabc123"), 1)          # only in the real block
        self.assertIn('["cdecoy0"]', out)                  # decoy comment untouched
        # The commented region is byte-for-byte unchanged (everything up to <title>).
        self.assertTrue(out.startswith(doc[:doc.index("<title>")]))
        # The real block (outside the comment) now carries the id.
        import re as _re
        real = _re.search(r'-->\s*<title>.*?id="handledCommentIds">(.*?)</script>', out, _re.S)
        self.assertIn("cabc123", real.group(1))

    def test_self_closing_template_before_block_is_located(self):
        # A self-closing <template/> must not leave the parser's template depth stuck
        # (which would hide the real handledCommentIds script that follows it).
        doc = DOC.replace("<title>x</title>\n", "<title>x</title>\n<template id=t />\n")
        p = self._tmp(content=doc)
        self.assertEqual(mark_handled.mark_handled(p, ["cabc123"]), ["cabc123"])
        self.assertEqual(self._handled(p), ["cabc123"])

    def test_empty_body_script_is_edited_cleanly(self):
        # The most position-math-sensitive case: content_start == endtag_start. The
        # start tag and </script> must stay byte-identical while [] is populated.
        doc = DOC.replace('id="handledCommentIds">\n[]\n</script>', 'id="handledCommentIds"></script>')
        p = self._tmp(content=doc)
        self.assertEqual(mark_handled.mark_handled(p, ["cabc123"]), ["cabc123"])
        with open(p, encoding="utf-8") as fh:
            out = fh.read()
        self.assertIn('id="handledCommentIds">', out)      # start tag intact
        self.assertIn("</script>", out)                    # end tag intact
        self.assertIn('"cabc123"', out)
        self.assertEqual(json.loads(re.search(r'id="handledCommentIds">(.*?)</script>', out, re.S).group(1)),
                         ["cabc123"])

    def test_finds_block_despite_quoted_gt_in_tag(self):
        # A '>' inside a quoted attribute on the script tag must not defeat the
        # locator (a raw [^>]* regex would stop early and miss the block).
        doc = DOC.replace(
            '<script type="application/json" id="handledCommentIds">',
            '<script type="application/json" data-note="a>b" id="handledCommentIds">')
        p = self._tmp(content=doc)
        self.assertEqual(mark_handled.mark_handled(p, ["cabc123"]), ["cabc123"])
        with open(p, encoding="utf-8") as fh:
            self.assertIn("cabc123", fh.read())

    def test_rejects_multiple_real_blocks(self):
        # Two real handledCommentIds blocks: refuse rather than silently edit the first.
        doc = DOC.replace(
            "<main>body</main>\n",
            '<script type="application/json" id="handledCommentIds">[]</script>\n<main>body</main>\n')
        p = self._tmp(content=doc)
        with self.assertRaises(ValueError):
            mark_handled.mark_handled(p, ["cabc123"])

    def test_offsets_correct_with_multibyte_before_block(self):
        # Non-ASCII (CJK / astral emoji / accents) before the tag must not skew the
        # getpos()->char-index math (both count code points on the same string).
        doc = DOC.replace("<title>x</title>\n", "<title>\u65e5\u672c\u8a9e \U0001f680 \u00e9mojis</title>\n")
        p = self._tmp(content=doc)
        self.assertEqual(mark_handled.mark_handled(p, ["cabc123"]), ["cabc123"])
        with open(p, encoding="utf-8") as fh:
            out = fh.read()
        self.assertEqual(json.loads(re.search(r'id="handledCommentIds">(.*?)</script>', out, re.S).group(1)),
                         ["cabc123"])
        self.assertIn("\u65e5\u672c\u8a9e \U0001f680 \u00e9mojis", out)  # untouched, offsets aligned

    def test_wrapped_multiline_start_tag(self):
        # get_starttag_text() must capture a start tag whose attributes span lines,
        # so content_start lands after the real '>' (not an attribute-line break).
        doc = DOC.replace('<script type="application/json" id="handledCommentIds">',
                          '<script\n  type="application/json"\n  id="handledCommentIds">')
        p = self._tmp(content=doc)
        self.assertEqual(mark_handled.mark_handled(p, ["cabc123"]), ["cabc123"])
        with open(p, encoding="utf-8") as fh:
            body = re.search(r'id="handledCommentIds">(.*?)</script>', fh.read(), re.S).group(1)
        self.assertEqual(json.loads(body), ["cabc123"])

    def test_self_closing_script_start_tag_is_handled_like_browser_html(self):
        doc = DOC.replace(
            '<script type="application/json" id="handledCommentIds">\n[]\n</script>',
            '<script type="application/json" id="handledCommentIds"/>[]</script>')
        p = self._tmp(content=doc)
        self.assertEqual(mark_handled.mark_handled(p, ["cabc123"]), ["cabc123"])
        with open(p, encoding="utf-8") as fh:
            self.assertIn('"cabc123"', fh.read())

    def test_locator_returns_partial_spans_if_parser_raises(self):
        with mock.patch.object(mark_handled._HandledLocator, "feed", side_effect=RuntimeError("boom")):
            self.assertEqual(mark_handled._locate_handled_block(DOC), [])

    def test_format_array_empty_is_compact(self):
        self.assertEqual(mark_handled._format_array([]), "[]")

    def test_existing_invalid_json_is_rejected(self):
        p = self._tmp(content=DOC.replace("[]", "["))
        with self.assertRaises(ValueError) as cm:
            mark_handled.mark_handled(p, ["cabc123"])
        self.assertIn("not valid JSON", str(cm.exception))

    def test_existing_json_must_be_array(self):
        p = self._tmp(content=DOC.replace("[]", '{"cabc123": true}'))
        with self.assertRaises(ValueError) as cm:
            mark_handled.mark_handled(p, ["cdef456"])
        self.assertIn("not a JSON array", str(cm.exception))

    def test_no_trailing_newline(self):
        doc = DOC.rstrip("\n")
        p = self._tmp(content=doc)
        self.assertEqual(mark_handled.mark_handled(p, ["cabc123"]), ["cabc123"])
        with open(p, encoding="utf-8") as fh:
            self.assertIn('"cabc123"', fh.read())

    def test_ignores_template_inert_decoy(self):
        # getElementById ignores <template> contents (inert fragment), so a decoy
        # handledCommentIds inside a <template> before the real block must NOT be edited.
        doc = DOC.replace(
            "<title>x</title>\n",
            '<template><script type="application/json" id="handledCommentIds">'
            '["cdecoy0"]</script></template>\n<title>x</title>\n')
        p = self._tmp(content=doc)
        self.assertEqual(mark_handled.mark_handled(p, ["cabc123"]), ["cabc123"])
        with open(p, encoding="utf-8") as fh:
            out = fh.read()
        self.assertEqual(out.count("cabc123"), 1)      # only the real block
        self.assertIn('["cdecoy0"]', out)              # template decoy untouched

    # -- CLI ---------------------------------------------------------------- #
    def test_cli_appends_and_is_idempotent(self):
        p = self._tmp()
        r1 = subprocess.run([sys.executable, MARK_PY, p, "cabc123"], capture_output=True, text=True)
        self.assertEqual(r1.returncode, 0, r1.stderr)
        self.assertIn("marked 1", r1.stdout)
        r2 = subprocess.run([sys.executable, MARK_PY, p, "cabc123"], capture_output=True, text=True)
        self.assertEqual(r2.returncode, 0)
        self.assertIn("nothing to do", r2.stdout)

    def test_cli_from_bundle_stdin(self):
        p = self._tmp()
        r = subprocess.run([sys.executable, MARK_PY, p, "--from-bundle", "-"],
                           input='HANDLED_IDS_JSON: ["cabc123"]\n', capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self._handled(p), ["cabc123"])

    def test_cli_bad_id_fails(self):
        p = self._tmp()
        r = subprocess.run([sys.executable, MARK_PY, p, "bad id"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)

    def test_cli_json_without_payload_gives_clear_error(self):
        p = self._tmp()
        r = subprocess.run([sys.executable, MARK_PY, p, "--json"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("--json requires", r.stderr)
        self.assertNotIn("list index out of range", r.stderr)

    def test_main_without_args_prints_usage(self):
        code, _out, err = self._call_main(["mark_handled.py"])
        self.assertEqual(code, 1)
        self.assertIn("Usage (run from the skill root):", err)

    def test_main_missing_file_reports_error(self):
        with tempfile.TemporaryDirectory() as d:
            code, _out, err = self._call_main(["mark_handled.py", os.path.join(d, "missing.html")])
            self.assertEqual(code, 1)
            self.assertIn("file not found", err)

    def test_main_json_success_marks_multiple_ids(self):
        p = self._tmp()
        code, out, err = self._call_main(["mark_handled.py", p, "--json", '["cabc123","cdef456"]'])
        self.assertEqual(code, 0, err)
        self.assertEqual(self._handled(p), ["cabc123", "cdef456"])
        self.assertIn("marked 2 comment(s)", out)

    def test_main_json_without_payload_reports_error(self):
        p = self._tmp()
        code, _out, err = self._call_main(["mark_handled.py", p, "--json"])
        self.assertEqual(code, 1)
        self.assertIn("--json requires", err)

    def test_main_json_non_list_reports_error(self):
        p = self._tmp()
        code, _out, err = self._call_main(["mark_handled.py", p, "--json", '{"cabc123": true}'])
        self.assertEqual(code, 1)
        self.assertIn("expected a list of ids", err)

    def test_main_json_bad_payload_reports_error(self):
        p = self._tmp()
        code, _out, err = self._call_main(["mark_handled.py", p, "--json", "["])
        self.assertEqual(code, 1)
        self.assertIn("mark_handled:", err)

    def test_main_from_bundle_defaults_to_stdin(self):
        p = self._tmp()
        code, _out, err = self._call_main(["mark_handled.py", p, "--from-bundle"],
                                          'HANDLED_IDS_JSON: ["cabc123"]\n')
        self.assertEqual(code, 0, err)
        self.assertEqual(self._handled(p), ["cabc123"])

    def test_main_from_bundle_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._tmp()
            bundle = os.path.join(d, "bundle.txt")
            with open(bundle, "w", encoding="utf-8") as fh:
                fh.write('HANDLED_IDS_JSON: ["cabc123"]\n')
            code, _out, err = self._call_main(["mark_handled.py", p, "--from-bundle", bundle])
            self.assertEqual(code, 0, err)
            self.assertEqual(self._handled(p), ["cabc123"])

    def test_main_from_bundle_missing_file_reports_error(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._tmp()
            missing = os.path.join(d, "missing-bundle.txt")
            code, _out, err = self._call_main(["mark_handled.py", p, "--from-bundle", missing])
            self.assertEqual(code, 1)
            self.assertIn("No such file", err)

    def test_main_no_ids_is_noop(self):
        p = self._tmp()
        code, out, err = self._call_main(["mark_handled.py", p])
        self.assertEqual(code, 0, err)
        self.assertEqual(self._handled(p), [])
        self.assertIn("nothing to do", out)

    def test_main_already_handled_is_noop(self):
        p = self._tmp(content=DOC.replace("[]", '["cabc123"]'))
        code, out, err = self._call_main(["mark_handled.py", p, "cabc123"])
        self.assertEqual(code, 0, err)
        self.assertEqual(self._handled(p), ["cabc123"])
        self.assertIn("nothing to do", out)

    def test_module_entrypoint_uses_sys_argv(self):
        err = io.StringIO()
        with mock.patch.object(sys, "argv", [MARK_PY]), contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as cm:
                runpy.run_path(MARK_PY, run_name="__main__")
        self.assertEqual(cm.exception.code, 1)
        self.assertIn("Usage (run from the skill root):", err.getvalue())


if __name__ == "__main__":
    unittest.main()
