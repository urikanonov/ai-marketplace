import base64
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402  shared pkg/dev split path constants
TOOLS = _paths.TOOLS
sys.path.insert(0, TOOLS)

import inline_images  # noqa: E402


class InlineImagesTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.png = os.path.join(self.dir, "pic.png")
        self.png_bytes = b"\x89PNG\r\n\x1a\n123"
        with open(self.png, "wb") as fh:
            fh.write(self.png_bytes)
        self.svg = os.path.join(self.dir, "art.svg")
        with open(self.svg, "w", encoding="utf-8") as fh:
            fh.write("<svg xmlns='http://www.w3.org/2000/svg'></svg>")

    def test_local_png_is_inlined_as_data_uri(self):
        html = '<img alt="x" src="pic.png">'
        out, inlined, missing = inline_images.inline_images(html, self.dir)
        self.assertEqual((inlined, missing), (1, []))
        expected = "data:image/png;base64," + base64.b64encode(self.png_bytes).decode("ascii")
        self.assertIn('src="' + expected + '"', out)
        self.assertIn('alt="x"', out)  # other attributes preserved

    def test_svg_mime_and_single_quotes_preserved(self):
        html = "<img src='art.svg' class='cm-img'>"
        out, inlined, _ = inline_images.inline_images(html, self.dir)
        self.assertEqual(inlined, 1)
        self.assertIn("src='data:image/svg+xml;base64,", out)
        self.assertIn("class='cm-img'", out)

    def test_remote_and_data_and_fragment_sources_are_untouched(self):
        for src in ("https://example.com/a.png", "//cdn/a.png", "data:image/png;base64,AAAA", "#anchor"):
            html = '<img src="%s">' % src
            out, inlined, missing = inline_images.inline_images(html, self.dir)
            self.assertEqual(out, html, src)
            self.assertEqual((inlined, missing), (0, []), src)

    def test_missing_local_image_is_reported_and_left_as_is(self):
        html = '<img src="nope.png">'
        out, inlined, missing = inline_images.inline_images(html, self.dir)
        self.assertEqual(inlined, 0)
        self.assertEqual(missing, ["nope.png"])
        self.assertEqual(out, html)

    def test_unknown_extension_is_treated_as_missing(self):
        weird = os.path.join(self.dir, "f.bmpx")
        with open(weird, "wb") as fh:
            fh.write(b"x")
        html = '<img src="f.bmpx">'
        _out, inlined, missing = inline_images.inline_images(html, self.dir)
        self.assertEqual(inlined, 0)
        self.assertEqual(missing, ["f.bmpx"])

    def test_cli_strict_fails_on_missing(self):
        p = os.path.join(self.dir, "doc.html")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write('<img src="gone.png">')
        self.assertEqual(inline_images.main([p, "--strict"]), 2)

    def test_cli_writes_output_file(self):
        p = os.path.join(self.dir, "doc.html")
        out = os.path.join(self.dir, "out.html")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write('<img src="pic.png">')
        self.assertEqual(inline_images.main([p, "--out", out]), 0)
        with open(out, encoding="utf-8") as fh:
            self.assertIn("data:image/png;base64,", fh.read())

    def test_data_src_and_other_star_src_attrs_are_not_matched(self):
        # The real src (not data-src / lazy attributes) must be the one inlined.
        html = '<img class="lazy" data-src="pic.png" src="pic.png">'
        out, inlined, _ = inline_images.inline_images(html, self.dir)
        self.assertEqual(inlined, 1)
        self.assertIn('data-src="pic.png"', out)           # data-src untouched
        self.assertRegex(out, r'\bsrc="data:image/png;base64,')  # real src inlined

    def test_img_inside_script_style_or_textarea_is_not_rewritten(self):
        for wrapper in ('<script>const s = \'<img src="pic.png">\';</script>',
                        '<style>/* <img src="pic.png"> */</style>',
                        '<textarea><img src="pic.png"></textarea>'):
            out, _inlined, _ = inline_images.inline_images(wrapper, self.dir)
            self.assertEqual(out, wrapper, wrapper)  # raw-text region left verbatim

    def test_unclosed_raw_block_protects_the_rest_of_the_document(self):
        # A malformed unclosed <script> must not expose a following <img> literal to rewriting.
        html = '<script>var x = "<img src=\'pic.png\'>"'  # never closed
        out, inlined, _ = inline_images.inline_images(html, self.dir)
        self.assertEqual((out, inlined), (html, 0))

    def test_real_img_inside_pre_is_inlined_escaped_sample_is_not(self):
        # <pre>/<code> are normal HTML, so a real <img> inside is inlined; an escaped
        # code sample (&lt;img&gt;) is not an element and is left alone.
        html = '<pre>sample &lt;img src="x"&gt; then <img src="pic.png"></pre>'
        out, inlined, _ = inline_images.inline_images(html, self.dir)
        self.assertEqual(inlined, 1)
        self.assertIn('&lt;img src="x"&gt;', out)      # escaped sample untouched
        self.assertIn("data:image/png;base64,", out)   # real img inlined

    def test_local_src_with_query_or_fragment_is_inlined(self):
        html = '<img src="pic.png?v=2#frag">'
        out, inlined, missing = inline_images.inline_images(html, self.dir)
        self.assertEqual((inlined, missing), (1, []))
        self.assertIn("data:image/png;base64,", out)

    def test_absolute_and_root_relative_paths_are_not_local(self):
        for src in ("/etc/passwd", "/img/a.png", "C:/Windows/a.png",
                    "\\Windows\\win.ini", "\\\\server\\share\\x.png"):
            self.assertFalse(inline_images._is_local(src), src)

    def test_src_like_text_inside_another_attribute_is_not_inlined(self):
        # A "src=" that appears inside another attribute's quoted value (e.g. alt) must be
        # skipped; only the real src attribute is inlined and the other attribute is kept.
        html = '<img alt="see src=\'pic.png\' here" src="pic.png">'
        out, inlined, _ = inline_images.inline_images(html, self.dir)
        self.assertEqual(inlined, 1)
        self.assertIn('alt="see src=\'pic.png\' here"', out)   # alt preserved verbatim
        self.assertRegex(out, r'\ssrc="data:image/png;base64,')  # real src inlined

    def test_parent_path_traversal_is_refused(self):
        outside = os.path.join(os.path.dirname(self.dir.rstrip(os.sep)), "cmh_outside_secret.png")
        with open(outside, "wb") as fh:
            fh.write(b"\x89PNG secret")
        try:
            html = '<img src="../%s">' % os.path.basename(outside)
            out, inlined, missing = inline_images.inline_images(html, self.dir)
            self.assertEqual(inlined, 0)          # not inlined
            self.assertEqual(out, html)           # left untouched
            self.assertEqual(missing, ["../" + os.path.basename(outside)])
        finally:
            os.remove(outside)

    def test_percent_decode_exception_fallback(self):
        # urllib.parse.unquote raising must not propagate; the fallback (raw src path) is used.
        # A plain filename without percent-encoded chars resolves identically either way,
        # so the image is still found and inlined via the fallback.
        html = '<img src="pic.png">'
        with mock.patch("urllib.parse.unquote", side_effect=Exception("decode error")):
            out, inlined, missing = inline_images.inline_images(html, self.dir)
        self.assertIsInstance(out, str)
        self.assertIsInstance(inlined, int)
        self.assertIsInstance(missing, list)
        self.assertEqual(inlined, 1)
        self.assertEqual(missing, [])
        self.assertIn("data:image/png;base64,", out)

    def test_symlink_escaping_base_dir_is_refused(self):
        # A symlink inside base_dir that points outside must not let an <img src> escape:
        # realpath canonicalizes both sides so the containment guard still rejects it.
        secret_dir = tempfile.mkdtemp()
        try:
            secret = os.path.join(secret_dir, "secret.png")
            with open(secret, "wb") as fh:
                fh.write(b"\x89PNG secret")
            link = os.path.join(self.dir, "link.png")
            try:
                os.symlink(secret, link)
            except (OSError, NotImplementedError, AttributeError):
                self.skipTest("symlinks not permitted on this host")
            html = '<img src="link.png">'
            out, inlined, missing = inline_images.inline_images(html, self.dir)
            self.assertEqual(inlined, 0)
            self.assertEqual(out, html)
            self.assertEqual(missing, ["link.png"])
        finally:
            import shutil
            shutil.rmtree(secret_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
