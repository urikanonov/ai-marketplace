#!/usr/bin/env python3
"""Regression tests for tools/retrofit.py."""
import contextlib
import io
import os
import sys
import unittest
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402

TOOLS = _paths.TOOLS
sys.path.insert(0, TOOLS)
import retrofit  # noqa: E402
import validate  # noqa: E402


HOST_HTML = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Host Report</title>
</head>
<body>
<section><h2 id="intro">Intro</h2><p>Hello review.</p></section>
</body>
</html>
"""


def _read_text(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _read_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


def _rmtree(path):
    import shutil
    shutil.rmtree(path, ignore_errors=True)


class RetrofitCliTests(unittest.TestCase):
    def _tmpdir(self):
        root = os.path.normpath(os.path.join(_paths.DEV, "..", "..", "..", "tmp"))
        os.makedirs(root, exist_ok=True)
        d = os.path.join(root, "test-retrofit-" + uuid.uuid4().hex)
        os.mkdir(d)
        self.addCleanup(lambda: _rmtree(d))
        return d

    def _write(self, directory, name, text):
        path = os.path.join(directory, name)
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        return path

    def _run(self, argv):
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = retrofit.main(argv)
        return code, out.getvalue(), err.getvalue()

    def _strict_clean(self, path):
        errors, warnings = validate.validate(path)
        self.assertEqual(errors, [], "validation errors: %r" % errors)
        self.assertEqual(warnings, [], "validation warnings: %r" % warnings)

    def test_wraps_body_children_and_strict_validates(self):
        d = self._tmpdir()
        src = self._write(d, "host.html", HOST_HTML)
        out = os.path.join(d, "out.html")
        code, stdout, stderr = self._run(["retrofit.py", src, "--label", "Host Report", "--out", out])
        self.assertEqual(code, 0, stderr)
        self.assertIn("wrote", stdout)
        html = _read_text(out)
        self.assertIn('<main id="commentRoot"', html)
        self.assertIn("data-cmh-content-root", html)
        self.assertIn('data-doc-label="Host Report"', html)
        self.assertIn('data-doc-source="%s"' % src.replace("\\", "\\\\"), html.replace("\\", "\\\\"))
        self.assertIn("<section><h2 id=\"intro\">Intro</h2><p>Hello review.</p></section>", html)
        self.assertIn('id="commentableHtmlLayer"', html)
        self._strict_clean(out)

    def test_root_selector_stamps_existing_element(self):
        d = self._tmpdir()
        src = self._write(d, "host.html", HOST_HTML.replace("<section", '<div id="content"><section').replace("</section>", "</section></div>"))
        out = os.path.join(d, "out.html")
        code, _stdout, stderr = self._run([
            "retrofit.py", src, "--label", "Host Report", "--root-selector", "#content", "--out", out])
        self.assertEqual(code, 0, stderr)
        html = _read_text(out)
        self.assertIn('<div id="commentRoot"', html)
        self.assertIn("BEGIN: commentable-html - CONTENT", html)
        self._strict_clean(out)

    def test_root_selector_stamps_empty_element(self):
        d = self._tmpdir()
        html = HOST_HTML.replace("<section><h2 id=\"intro\">Intro</h2><p>Hello review.</p></section>", '<div id="content"></div>')
        src = self._write(d, "host.html", html)
        out = os.path.join(d, "out.html")
        code, _stdout, stderr = self._run([
            "retrofit.py", src, "--label", "Host Report", "--root-selector", "#content", "--out", out])
        self.assertEqual(code, 0, stderr)
        html = _read_text(out)
        self.assertIn('<div id="commentRoot"', html)
        self.assertLess(html.index("BEGIN: commentable-html - CONTENT"), html.index("END: commentable-html - CONTENT"))
        self._strict_clean(out)

    def test_valid_html5_implicit_closed_tags_retrofit(self):
        d = self._tmpdir()
        html = """<!doctype html>
<html>
<head><meta charset="utf-8"><title>Implicit</title></head>
<body>
<section><h2 id="items">Items</h2><p>Text<p>More<ul><li>One<li>Two</ul></section>
</body>
</html>
"""
        src = self._write(d, "implicit.html", html)
        out = os.path.join(d, "out.html")
        code, _stdout, stderr = self._run(["retrofit.py", src, "--label", "Implicit", "--out", out])
        self.assertEqual(code, 0, stderr)
        self._strict_clean(out)

    def test_default_wrap_uses_div_when_body_already_has_main(self):
        d = self._tmpdir()
        html = HOST_HTML.replace("<section>", "<main><section>").replace("</section>", "</section></main>")
        src = self._write(d, "host.html", html)
        out = os.path.join(d, "out.html")
        code, _stdout, stderr = self._run(["retrofit.py", src, "--label", "Host", "--out", out])
        self.assertEqual(code, 0, stderr)
        html = _read_text(out)
        self.assertIn('<div id="commentRoot"', html)
        self.assertIn("<main><section>", html)
        self.assertRegex(html, r'<div id="commentRoot"[^>]*>\s*<!-- BEGIN: commentable-html - CONTENT')
        self._strict_clean(out)

    def test_root_selector_refuses_self_closing_non_void_element(self):
        d = self._tmpdir()
        html = HOST_HTML.replace("<section><h2 id=\"intro\">Intro</h2><p>Hello review.</p></section>", '<div id="content"/>')
        src = self._write(d, "host.html", html)
        out = os.path.join(d, "out.html")
        code, _stdout, stderr = self._run([
            "retrofit.py", src, "--label", "Host", "--root-selector", "#content", "--out", out])
        self.assertEqual(code, 2)
        self.assertIn("self-closing non-void", stderr)
        self.assertFalse(os.path.exists(out))

    def test_comment_and_script_tag_text_do_not_create_fake_containers(self):
        d = self._tmpdir()
        html = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Fake tags</title>
<script>const fake = "<head><body></body></head>";</script>
</head>
<body>
<!-- <head></head><body></body> -->
<section><h2 id="intro">Intro</h2><p>Hello review.</p></section>
</body>
</html>
"""
        src = self._write(d, "host.html", html)
        out = os.path.join(d, "out.html")
        code, _stdout, stderr = self._run(["retrofit.py", src, "--label", "Host", "--out", out])
        self.assertEqual(code, 0, stderr)
        self._strict_clean(out)

    def test_portable_inlines_layer_and_strict_validates(self):
        d = self._tmpdir()
        src = self._write(d, "host.html", HOST_HTML)
        out = os.path.join(d, "portable.html")
        code, _stdout, stderr = self._run([
            "retrofit.py", src, "--label", "Portable Host", "--portable", "--out", out])
        self.assertEqual(code, 0, stderr)
        html = _read_text(out)
        self.assertIn('"mode":"portable"', html)
        self.assertNotIn('href="commentable-html.css"', html)
        self._strict_clean(out)

    def test_nonportable_asset_options_match_new_document(self):
        d = self._tmpdir()
        src = self._write(d, "host.html", HOST_HTML)

        href_out = os.path.join(d, "href.html")
        code, _stdout, stderr = self._run([
            "retrofit.py", src, "--label", "Href Host", "--assets-href", "assets", "--out", href_out])
        self.assertEqual(code, 0, stderr)
        href_html = _read_text(href_out)
        self.assertIn('href="assets/commentable-html.css"', href_html)
        self.assertIn('src="assets/commentable-html.js"', href_html)

        rel_out = os.path.join(d, "relative.html")
        code, _stdout, stderr = self._run([
            "retrofit.py", src, "--label", "Relative Host", "--assets-relative", "--out", rel_out])
        self.assertEqual(code, 0, stderr)
        rel_html = _read_text(rel_out)
        self.assertIn("dist/commentable-html.css", rel_html.replace("\\", "/"))

        copy_dir = os.path.join(d, "copied")
        os.mkdir(copy_dir)
        copy_out = os.path.join(copy_dir, "copy.html")
        code, _stdout, stderr = self._run([
            "retrofit.py", src, "--label", "Copy Host", "--copy-assets", "--out", copy_out])
        self.assertEqual(code, 0, stderr)
        copy_html = _read_text(copy_out)
        self.assertIn('href="commentable-html.css"', copy_html)
        for name in ("commentable-html.css", "commentable-html.js", "commentable-html.assets.js"):
            self.assertTrue(os.path.exists(os.path.join(copy_dir, name)), name)

    def test_refuses_demo_key_and_duplicate_existing_root(self):
        d = self._tmpdir()
        src = self._write(d, "host.html", HOST_HTML)
        out = os.path.join(d, "bad.html")
        code, _stdout, stderr = self._run([
            "retrofit.py", src, "--label", "Host", "--key", "my-doc", "--out", out])
        self.assertEqual(code, 2)
        self.assertIn("demo", stderr.lower())
        self.assertFalse(os.path.exists(out))

        src2 = self._write(d, "has-root.html", HOST_HTML.replace("<section", '<main id="commentRoot"><section').replace("</section>", "</section></main>"))
        code, _stdout, stderr = self._run(["retrofit.py", src2, "--label", "Host"])
        self.assertEqual(code, 2)
        self.assertIn("commentroot", stderr.lower())

    def test_commented_demo_root_is_ignored(self):
        d = self._tmpdir()
        html = HOST_HTML.replace("<body>", '<body>\n<!-- <main id="commentRoot" data-comment-key="my-doc">demo</main> -->')
        src = self._write(d, "host.html", html)
        out = os.path.join(d, "out.html")
        code, _stdout, stderr = self._run(["retrofit.py", src, "--label", "Host", "--out", out])
        self.assertEqual(code, 0, stderr)
        self._strict_clean(out)

    def test_refuses_already_layered_file_with_upgrade_guidance(self):
        d = self._tmpdir()
        src = self._write(d, "layered.html", _read_text(_paths.TEMPLATE))
        code, _stdout, stderr = self._run(["retrofit.py", src, "--label", "Layered"])
        self.assertEqual(code, 2)
        self.assertIn("upgrade.py", stderr)

    def test_missing_or_ambiguous_head_body_fails_closed(self):
        d = self._tmpdir()
        cases = {
            "missing-head.html": "<html><body><p>x</p></body></html>",
            "duplicate-head.html": "<html><head></head><head></head><body><p>x</p></body></html>",
            "missing-body.html": "<html><head><title>x</title></head><p>x</p></html>",
            "duplicate-body.html": "<html><head></head><body>x</body><body>y</body></html>",
        }
        for name, html in cases.items():
            with self.subTest(name=name):
                src = self._write(d, name, html)
                code, _stdout, stderr = self._run(["retrofit.py", src, "--label", "Host"])
                self.assertEqual(code, 2)
                self.assertTrue("head" in stderr.lower() or "body" in stderr.lower())

    def test_root_selector_miss_or_multi_match_fails(self):
        d = self._tmpdir()
        src = self._write(d, "host.html", HOST_HTML)
        code, _stdout, stderr = self._run([
            "retrofit.py", src, "--label", "Host", "--root-selector", "#missing"])
        self.assertEqual(code, 2)
        self.assertIn("root-selector", stderr)

        dup = HOST_HTML.replace("<section", '<div id="content"></div><section id="content"')
        src2 = self._write(d, "dup.html", dup)
        code, _stdout, stderr = self._run([
            "retrofit.py", src2, "--label", "Host", "--root-selector", "#content"])
        self.assertEqual(code, 2)
        self.assertIn("matched 2", stderr)

    def test_non_utf8_input_is_refused(self):
        d = self._tmpdir()
        src = os.path.join(d, "bad.html")
        with open(src, "wb") as fh:
            fh.write(b"\xff\xfe\xfa")
        code, _stdout, stderr = self._run(["retrofit.py", src, "--label", "Bad"])
        self.assertEqual(code, 2)
        self.assertIn("utf-8", stderr.lower())

    def test_validation_failure_leaves_target_untouched(self):
        d = self._tmpdir()
        bad = HOST_HTML.replace("</section>", '<img src="https://example.com/x.png"></section>')
        src = self._write(d, "host.html", bad)
        before = _read_bytes(src)
        code, _stdout, stderr = self._run(["retrofit.py", src, "--label", "Host"])
        self.assertEqual(code, 1)
        self.assertIn("validation", stderr.lower())
        self.assertEqual(_read_bytes(src), before)
        leftovers = [name for name in os.listdir(d) if name.startswith(".cmh-retrofit-")]
        self.assertEqual(leftovers, [])

    def test_skip_selectors_adds_cm_skip_to_host_chrome(self):
        d = self._tmpdir()
        html = HOST_HTML.replace("<body>", '<body><aside id="hostPanel" class="panel">Host</aside>')
        src = self._write(d, "host.html", html)
        out = os.path.join(d, "out.html")
        code, _stdout, stderr = self._run([
            "retrofit.py", src, "--label", "Host", "--skip-selectors", "#hostPanel", "--out", out])
        self.assertEqual(code, 0, stderr)
        html = _read_text(out)
        self.assertIn('id="hostPanel" class="panel cm-skip"', html)
        self._strict_clean(out)

    def test_css_collision_check_warns_without_failing(self):
        d = self._tmpdir()
        html = HOST_HTML.replace(
            "</head>",
            "<style>:root { --cp-bg: red; color-scheme: dark; } .cm-host { z-index: 301; }</style></head>",
        )
        src = self._write(d, "host.html", html)
        out = os.path.join(d, "out.html")
        code, _stdout, stderr = self._run(["retrofit.py", src, "--label", "Host", "--out", out])
        self.assertEqual(code, 0, stderr)
        self.assertIn("retrofit warning", stderr)
        self.assertIn("--cp-", stderr)
        self.assertIn("z-index", stderr)
        self._strict_clean(out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
