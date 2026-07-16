#!/usr/bin/env python3
"""Tests for reusable authoring brand profiles (CMH-TOOL-19)."""
import contextlib
import io
import json
import os
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import _paths  # noqa: E402

sys.path.insert(0, _paths.TOOLS)
sys.path.insert(0, _paths.DECK)
import deck_scaffold  # noqa: E402
import new_document  # noqa: E402
import retrofit  # noqa: E402
import validate  # noqa: E402


CONTENT = '<section><h2 id="a">Hi</h2><p>Readable text.</p></section>'
HOST_HTML = """<!doctype html>
<html>
<head><meta charset="utf-8"><title>Host</title></head>
<body><section><h2 id="intro">Intro</h2><p>Hello review.</p></section></body>
</html>
"""


def _rmtree(path):
    import shutil
    shutil.rmtree(path, ignore_errors=True)


class BrandProfileTests(unittest.TestCase):
    def _tmpdir(self):
        root = os.path.normpath(os.path.join(_paths.DEV, "..", "..", "..", "tmp"))
        os.makedirs(root, exist_ok=True)
        path = os.path.join(root, "test-brand-profile-" + uuid.uuid4().hex)
        os.mkdir(path)
        self.addCleanup(lambda: _rmtree(path))
        return path

    def _write_json(self, directory, name, value):
        path = os.path.join(directory, name)
        with open(path, "w", encoding="utf-8", newline="") as fh:
            json.dump(value, fh, sort_keys=True)
        return path

    def _run_new_document(self, argv, stdin=CONTENT):
        out = io.StringIO()
        err = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO(stdin)), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = new_document.main(argv)
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def _run_retrofit(self, argv):
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = retrofit.main(argv)
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def _run_deck_scaffold(self, argv):
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = deck_scaffold.main(argv)
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def test_cmh_tool_19_new_document_stamps_tokens_and_local_font_profile(self):
        d = self._tmpdir()
        brand = self._write_json(d, "brand.json", {
            "tokens": {
                "--cp-bg": "#101820",
                "--cp-text": "#f7f7f7",
                "--cp-accent": "rgb(20, 120, 220)",
            },
            "fonts": [{
                "family": "Brand Sans",
                "src": "data:font/woff2;base64,QUJDRA==",
                "weight": "400",
            }],
            "fontStack": ["Brand Sans", "Segoe UI", "sans-serif"],
        })

        code, html, err = self._run_new_document([
            "new_document.py", "--content", "-", "--key", "brand-v1", "--label", "Brand Doc",
            "--kind", "generic", "--portable", "--brand", brand,
        ])

        self.assertEqual(code, 0, err)
        self.assertIn('<style data-cmh-brand="brand.json">', html)
        self.assertIn(":root {", html)
        self.assertIn("html[data-theme=\"dark\"] {", html)
        self.assertIn("  --cp-bg: #101820;", html)
        self.assertIn("  --cp-accent: rgb(20, 120, 220);", html)
        self.assertIn("@font-face", html)
        self.assertIn('font-family: "Brand Sans";', html)
        self.assertIn('src: url("data:font/woff2;base64,QUJDRA==") format("woff2");', html)
        self.assertIn('body { font-family: "Brand Sans", "Segoe UI", sans-serif; }', html)
        out_path = os.path.join(d, "brand-doc.html")
        Path(out_path).write_text(html, encoding="utf-8")
        errors, _warnings = validate.validate(out_path)
        self.assertEqual(errors, [])

    def test_cmh_tool_19_rejects_unknown_tokens_and_unsafe_values(self):
        d = self._tmpdir()
        cases = {
            "unknown.json": ({"tokens": {"--cp-not-real": "#ffffff"}}, "unknown --cp-* token"),
            "unsafe.json": ({"tokens": {"--cp-bg": "#ffffff; color: red"}}, "must not contain"),
        }
        for name, (profile, needle) in cases.items():
            with self.subTest(name=name):
                brand = self._write_json(d, name, profile)
                code, out, err = self._run_new_document([
                    "new_document.py", "--content", "-", "--key", "brand-bad", "--label", "Bad",
                    "--kind", "generic", "--portable", "--brand", brand,
                ])
                self.assertEqual(code, 2)
                self.assertIn(needle, err)
                self.assertNotIn("data-cmh-brand", out)

    def test_cmh_tool_19_retrofit_brand_low_contrast_prints_advisory(self):
        d = self._tmpdir()
        src = os.path.join(d, "host.html")
        out_path = os.path.join(d, "out.html")
        Path(src).write_text(HOST_HTML, encoding="utf-8")
        brand = self._write_json(d, "low-contrast.json", {
            "tokens": {
                "--cp-bg": "#777777",
                "--cp-text": "#777777",
            },
        })

        code, _stdout, err = self._run_retrofit([
            "retrofit.py", src, "--label", "Host", "--kind", "generic", "--out", out_path,
            "--brand", brand,
        ])

        self.assertEqual(code, 0, err)
        self.assertIn("low text contrast", err)
        html = Path(out_path).read_text(encoding="utf-8")
        self.assertIn('<style data-cmh-brand="low-contrast.json">', html)
        self.assertIn("  --cp-text: #777777;", html)

    def test_cmh_tool_19_deck_scaffold_accepts_the_same_brand_profile(self):
        d = self._tmpdir()
        out_path = os.path.join(d, "deck.html")
        brand = self._write_json(d, "deck-brand.json", {
            "tokens": {
                "--cp-bg": "#0b1020",
                "--cp-text": "#f8fafc",
                "--cp-link": "#93c5fd",
            },
            "fontStack": ["Segoe UI", "system-ui", "sans-serif"],
        })

        code, _stdout, err = self._run_deck_scaffold([
            "--slides", "1", "--label", "Deck", "--out", out_path, "--brand", brand,
        ])

        self.assertEqual(code, 0, err)
        html = Path(out_path).read_text(encoding="utf-8")
        self.assertIn('<style data-cmh-brand="deck-brand.json">', html)
        self.assertIn("  --cp-link: #93c5fd;", html)


if __name__ == "__main__":
    unittest.main()
