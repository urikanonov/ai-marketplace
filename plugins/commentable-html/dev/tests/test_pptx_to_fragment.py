#!/usr/bin/env python3
"""Tests for deck/pptx_to_fragment.py (CMH-DECK-03a).

Extracted PowerPoint text must be HTML-escaped (no injection), one section per slide with a
stable data-slide-id, speaker notes ignored, and the local --pptx fallback must fail closed.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402

DECK = os.path.join(_paths.PKG, "deck")
sys.path.insert(0, DECK)
import pptx_to_fragment as p2f  # noqa: E402
from deck_common import SLIDE_ID_RE  # noqa: E402

TOOL = os.path.join(DECK, "pptx_to_fragment.py")

HOSTILE = [
    {
        "title": '<script>alert(1)</script> & "friends"',
        "content": [
            {"type": "text", "content": "close --> comment; entity &amp; and <b>bold</b>"},
            {"type": "text", "content": "RTL \u05d0\u05d1\u05d2 emoji \U0001f600 done"},
        ],
        "images": [{"path": "assets/s1.png"}],
        "notes": "SECRET-NOTE-SHOULD-NOT-APPEAR",
    }
]


class PptxToFragmentTests(unittest.TestCase):
    def test_hostile_text_is_escaped(self):
        frag = p2f.slides_to_fragment(HOSTILE)
        self.assertNotIn("<script>", frag)
        self.assertNotIn("</script>", frag)
        self.assertIn("&lt;script&gt;", frag)
        self.assertIn("&lt;b&gt;bold&lt;/b&gt;", frag)
        # a literal ampersand from the source is escaped, and an existing entity is not double-decoded
        self.assertIn("&amp;", frag)
        self.assertIn("--&gt; comment", frag)
        # non-ASCII passes through as text (escaping does not touch RTL/emoji)
        self.assertIn("\u05d0\u05d1\u05d2", frag)
        self.assertIn("\U0001f600", frag)

    def test_notes_are_ignored(self):
        frag = p2f.slides_to_fragment(HOSTILE)
        self.assertNotIn("SECRET-NOTE-SHOULD-NOT-APPEAR", frag)

    def test_structure_and_stable_id(self):
        frag = p2f.slides_to_fragment(HOSTILE)
        self.assertEqual(frag.count('<section class="slide"'), 1)
        self.assertIn('<h2 class="cmh-slide-title">', frag)
        self.assertIn('<img src="assets/s1.png" alt="">', frag)
        sid = frag.split('data-slide-id="', 1)[1].split('"', 1)[0]
        self.assertRegex(sid, SLIDE_ID_RE)
        # deterministic across runs
        self.assertEqual(frag, p2f.slides_to_fragment(HOSTILE))

    def test_duplicate_slides_get_distinct_ids(self):
        slides = [
            {"title": "Same", "content": [{"type": "text", "content": "body"}]},
            {"title": "Same", "content": [{"type": "text", "content": "body"}]},
        ]
        frag = p2f.slides_to_fragment(slides)
        ids = [seg.split('"', 1)[0] for seg in frag.split('data-slide-id="')[1:]]
        self.assertEqual(len(ids), 2)
        self.assertNotEqual(ids[0], ids[1])
        self.assertTrue(ids[1].endswith("-2"))

    def test_cli_stdin_to_stdout(self):
        proc = subprocess.run(
            [sys.executable, TOOL, "--input", "-"],
            input=json.dumps(HOSTILE), capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('<section class="slide"', proc.stdout)
        self.assertNotIn("<script>", proc.stdout)

    def test_non_list_input_errors(self):
        proc = subprocess.run(
            [sys.executable, TOOL, "--input", "-"],
            input=json.dumps({"not": "a list"}), capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 1)

    def test_pptx_fallback_fails_closed(self):
        proc = subprocess.run(
            [sys.executable, TOOL, "--pptx", os.path.join(HERE, "does-not-exist.pptx")],
            capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("pptx_to_fragment:", proc.stderr)


    def test_main_in_process_covers_branches(self):
        import contextlib
        import io
        import shutil
        from unittest import mock
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        inp = os.path.join(d, "in.json")
        Path(inp).write_text(json.dumps(HOSTILE), encoding="utf-8")
        out = os.path.join(d, "out.html")
        self.assertEqual(p2f.main(["--input", inp, "--out", out]), 0)
        self.assertIn("<section", Path(out).read_text(encoding="utf-8"))

        # stdout path (capture the binary buffer write)
        holder = type("H", (), {})()
        holder.buffer = io.BytesIO()
        with mock.patch.object(sys, "stdout", holder):
            self.assertEqual(p2f.main(["--input", inp]), 0)
        self.assertIn(b"<section", holder.buffer.getvalue())

        # stdin path
        with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(HOSTILE))):
            holder2 = type("H", (), {})()
            holder2.buffer = io.BytesIO()
            with mock.patch.object(sys, "stdout", holder2):
                self.assertEqual(p2f.main(["--input", "-"]), 0)

        # non-list input
        obj = os.path.join(d, "obj.json")
        Path(obj).write_text("{}", encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(p2f.main(["--input", obj]), 1)

        # --pptx fail closed (local extractor errors on a missing file / missing python-pptx)
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                p2f.main(["--pptx", os.path.join(d, "nope.pptx")])

        # --pptx with the vendored extractor missing
        with mock.patch.object(p2f, "VENDOR_EXTRACTOR", Path(d) / "no-extractor.py"):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    p2f.main(["--pptx", os.path.join(d, "x.pptx")])

        # --pptx where the extractor exits 0 but writes no JSON
        dummy = Path(d) / "dummy_extractor.py"
        dummy.write_text("import sys; sys.exit(0)\n", encoding="utf-8")
        with mock.patch.object(p2f, "VENDOR_EXTRACTOR", dummy):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    p2f.main(["--pptx", os.path.join(d, "x.pptx")])


    def test_non_text_and_empty_blocks_skipped(self):
        slides = [{"title": "T", "content": [
            {"type": "image", "content": "ignored"},
            {"type": "text", "content": "   "},
            {"type": "text", "content": "kept"},
        ]}]
        frag = p2f.slides_to_fragment(slides)
        self.assertIn("<p>kept</p>", frag)
        self.assertNotIn("ignored", frag)
        self.assertEqual(frag.count("<p>"), 1)

    def test_local_extract_error_hints(self):
        import contextlib
        import io
        from unittest import mock
        for stderr in ("ModuleNotFoundError: No module named 'pptx'", "boom generic error"):
            result = type("R", (), {"returncode": 1, "stderr": stderr, "stdout": ""})()
            with mock.patch("subprocess.run", return_value=result):
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        p2f.main(["--pptx", "any.pptx"])


    def test_local_extract_no_json(self):
        import contextlib
        import io
        from unittest import mock
        ok = type("R", (), {"returncode": 0, "stderr": "", "stdout": ""})()
        with mock.patch("subprocess.run", return_value=ok):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    p2f.main(["--pptx", "any.pptx"])


    def test_local_extract_success(self):
        import contextlib
        import io
        from unittest import mock

        def fake_run(cmd, **kw):
            Path(cmd[3], "extracted-slides.json").write_text(
                json.dumps([{"title": "T", "content": [{"type": "text", "content": "hi"}]}]),
                encoding="utf-8")
            return type("R", (), {"returncode": 0, "stderr": "", "stdout": ""})()

        out = os.path.join(tempfile.mkdtemp(), "o.html")
        with mock.patch("subprocess.run", side_effect=fake_run):
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(p2f.main(["--pptx", "any.pptx", "--out", out]), 0)
        self.assertIn("<section", Path(out).read_text(encoding="utf-8"))


    def test_slide_without_title_has_no_heading(self):
        frag = p2f.slides_to_fragment([{"content": [{"type": "text", "content": "body"}]}])
        self.assertNotIn("cmh-slide-title", frag)
        self.assertIn("<p>body</p>", frag)

    def test_remote_and_unsafe_image_paths_rejected(self):
        for bad in ("http://evil/x.png", "https://evil/x.png", "//evil/x.png",
                    "data:text/html,<script>alert(1)</script>", "/etc/passwd", "../secret.png",
                    "sub/../../../x.png", "javascript:alert(1)"):
            with self.subTest(path=bad):
                with self.assertRaises(ValueError):
                    p2f.slides_to_fragment([{"title": "T", "images": [{"path": bad}]}])

    def test_data_image_uri_is_accepted(self):
        frag = p2f.slides_to_fragment([{"title": "T", "images": [{"path": "data:image/png;base64,AAAA"}]}])
        self.assertIn('<img src="data:image/png;base64,AAAA" alt="">', frag)

    def test_local_pptx_inlines_extracted_images_as_data_uri(self):
        import base64
        import contextlib
        import io
        from unittest import mock
        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")

        def fake_run(cmd, **kw):
            outdir = Path(cmd[3])
            (outdir / "assets").mkdir(parents=True, exist_ok=True)
            (outdir / "assets" / "s1.png").write_bytes(png)
            (outdir / "extracted-slides.json").write_text(
                json.dumps([{"title": "T", "images": [{"path": "assets/s1.png"}]}]), encoding="utf-8")
            return type("R", (), {"returncode": 0, "stderr": "", "stdout": ""})()

        out = os.path.join(tempfile.mkdtemp(), "o.html")
        with mock.patch("subprocess.run", side_effect=fake_run):
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(p2f.main(["--pptx", "any.pptx", "--out", out]), 0)
        html = Path(out).read_text(encoding="utf-8")
        # the extracted image is inlined (survives the deleted temp dir), not a dangling assets/ ref
        self.assertIn('<img src="data:image/png;base64,', html)
        self.assertNotIn("assets/s1.png", html)

    def test_inline_local_images_leaves_odd_and_missing_paths(self):
        import tempfile as _tf
        d = _tf.mkdtemp()
        slides = ["not-a-dict", {"images": ["str", {"path": "../x.png"}, {"path": "missing.png"},
                                             {"path": "data:image/png;base64,AAAA"}, {"path": ""}]}]
        # non-list returns as-is; odd/traversing/missing/data/empty paths are left untouched
        self.assertEqual(p2f._inline_local_images("x", d), "x")
        out = p2f._inline_local_images(slides, d)
        paths = [i.get("path") for i in out[1]["images"] if isinstance(i, dict)]
        self.assertEqual(paths, ["../x.png", "missing.png", "data:image/png;base64,AAAA", ""])

    def test_backslash_image_path_normalized(self):
        frag = p2f.slides_to_fragment([{"title": "T", "images": [{"path": "assets\\s1.png"}]}])
        self.assertIn('<img src="assets/s1.png" alt="">', frag)

    def test_empty_image_path_skipped_not_error(self):
        frag = p2f.slides_to_fragment(
            [{"title": "T", "content": [{"type": "text", "content": "x"}],
              "images": [{"path": "   "}, {"path": None}]}])
        self.assertNotIn("<img", frag)
        self.assertIn("<p>x</p>", frag)

    def test_empty_slide_list_rejected(self):
        with self.assertRaises(ValueError):
            p2f.slides_to_fragment([])

    def test_slide_with_no_content_rejected(self):
        with self.assertRaises(ValueError):
            p2f.slides_to_fragment([{"title": "  ", "content": [], "images": []}])

    def test_non_dict_slide_rejected(self):
        with self.assertRaises(ValueError):
            p2f.slides_to_fragment(["not a dict"])

    def test_non_list_content_or_images_rejected(self):
        with self.assertRaises(ValueError):
            p2f.slides_to_fragment([{"title": "T", "content": "nope"}])
        with self.assertRaises(ValueError):
            p2f.slides_to_fragment([{"title": "T", "images": "nope"}])

    def test_non_dict_content_block_or_image_rejected(self):
        with self.assertRaises(ValueError):
            p2f.slides_to_fragment([{"title": "T", "content": ["str-block"]}])
        with self.assertRaises(ValueError):
            p2f.slides_to_fragment([{"title": "T", "images": ["str-image"]}])

    def test_cli_empty_list_exits_nonzero(self):
        proc = subprocess.run(
            [sys.executable, TOOL, "--input", "-"],
            input="[]", capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("no slides", proc.stderr)


if __name__ == "__main__":
    unittest.main()
