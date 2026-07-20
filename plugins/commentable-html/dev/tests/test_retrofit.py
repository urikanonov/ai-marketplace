#!/usr/bin/env python3
"""Regression tests for tools/retrofit.py."""
import contextlib
import io
import os
import re
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
        if "--kind" not in argv:
            argv = argv[:1] + ["--kind", "generic"] + argv[1:]
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = retrofit.main(argv)
        return code, out.getvalue(), err.getvalue()

    def _strict_clean(self, path):
        errors, warnings = validate.validate(path)
        self.assertEqual(errors, [], "validation errors: %r" % errors)
        self.assertEqual(warnings, [], "validation warnings: %r" % warnings)

    def _theme_vars_block(self, html):
        match = re.search(r'<style data-cmh-theme-vars>\s*(.*?)\s*</style>', html, re.S)
        self.assertIsNotNone(match)
        return match.group(1)

    _RAW_CODE_HOST = ('<!doctype html><html><head><title>H</title></head><body>'
                      '<h1>Doc</h1><pre><code class="language-python">def f(): return 1</code></pre>'
                      '</body></html>')

    def test_bakes_syntax_highlighting_by_default(self):
        # CMH-HL-04: retrofit bakes highlighting so a retrofitted document is never raw.
        d = self._tmpdir()
        src = self._write(d, "host.html", self._RAW_CODE_HOST)
        out = os.path.join(d, "out.html")
        code, _stdout, stderr = self._run(["retrofit.py", src, "--label", "H", "--out", out])
        self.assertEqual(code, 0, stderr)
        self.assertIn('<span class="cmh-code-kw">def</span>', _read_text(out))

    def test_no_highlight_with_raw_code_is_blocked_by_validation(self):
        # CMH-HL-04: with --no-highlight the raw block stays raw, and retrofit fails closed on the
        # resulting "not syntax-highlighted" warning, so it never writes a raw document.
        d = self._tmpdir()
        src = self._write(d, "host.html", self._RAW_CODE_HOST)
        out = os.path.join(d, "out.html")
        code, _stdout, stderr = self._run(
            ["retrofit.py", src, "--label", "H", "--out", out, "--no-highlight"])
        self.assertEqual(code, 1)
        self.assertIn("not syntax-highlighted", stderr)
        self.assertFalse(os.path.exists(out), "a raw document must not be written")

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
        self.assertIn('data-doc-source="host.html"', html)
        self.assertNotIn(os.path.dirname(src), html)
        self.assertRegex(html, r'data-comment-key="[^"]+"')
        self.assertIn('id="handledCommentIds"', html)
        self.assertIn('id="embeddedComments"', html)
        self.assertIn("<section><h2 id=\"intro\">Intro</h2><p>Hello review.</p></section>", html)
        self.assertIn('id="commentableHtmlLayer"', html)
        self._strict_clean(out)

    def test_explicit_source_provenance_is_basename_only_cmh_sec_03(self):
        d = self._tmpdir()
        src = self._write(d, "host.html", HOST_HTML)
        out = os.path.join(d, "out.html")
        sensitive = r"C:\Users\alice\Internal Project\source\host-input.html"
        code, _stdout, stderr = self._run([
            "retrofit.py", src, "--label", "Host Report", "--source", sensitive,
            "--out", out,
        ])
        self.assertEqual(code, 0, stderr)
        html = _read_text(out)
        self.assertIn('data-doc-source="host-input.html"', html)
        self.assertNotIn("alice", html)
        self.assertNotIn("Internal Project", html)

    def test_preserves_crlf_line_endings(self):
        # CMH-TOOL-15: a Windows-authored (CRLF) host file keeps its dominant newline through
        # the retrofit instead of being silently normalized to LF.
        d = self._tmpdir()
        src = self._write(d, "host.html", HOST_HTML.replace("\n", "\r\n"))
        out = os.path.join(d, "out.html")
        code, _stdout, stderr = self._run(["retrofit.py", src, "--label", "Host Report", "--out", out])
        self.assertEqual(code, 0, stderr)
        raw = _read_bytes(out)
        self.assertIn(b"\r\n", raw)
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))  # no lone LF introduced
        self._strict_clean(out)

    def test_keeps_lf_when_lf_is_dominant_despite_a_stray_crlf(self):
        # CMH-TOOL-15: newline preservation follows the DOMINANT style, not the mere presence of
        # a CRLF. A mostly-LF host with one stray CRLF stays LF after retrofit.
        d = self._tmpdir()
        src = self._write(d, "host.html", HOST_HTML.replace("\n", "\r\n", 1))
        out = os.path.join(d, "out.html")
        code, _stdout, stderr = self._run(["retrofit.py", src, "--label", "Host Report", "--out", out])
        self.assertEqual(code, 0, stderr)
        raw = _read_bytes(out)
        self.assertNotIn(b"\r\n", raw)  # dominant LF preserved; the stray CRLF did not win
        self._strict_clean(out)

    def test_kind_is_stamped_and_required(self):
        d = self._tmpdir()
        src = self._write(d, "host.html", HOST_HTML)
        out = os.path.join(d, "out.html")
        # The retrofitted document declares the requested kind (self-validates as a board,
        # which does not require a title, so the host content needs no <h1>).
        code, _stdout, stderr = self._run(
            ["retrofit.py", src, "--label", "Host Board", "--kind", "board", "--out", out])
        self.assertEqual(code, 0, stderr)
        self.assertIn('<meta name="commentable-html-kind" content="board"', _read_text(out))
        # Omitting --kind is a usage error.
        with self.assertRaises(SystemExit) as cm:
            with contextlib.redirect_stderr(io.StringIO()):
                retrofit.main(["retrofit.py", src, "--label", "X", "--out", out])
        self.assertEqual(cm.exception.code, 2)

    def test_existing_kind_meta_is_replaced_not_duplicated(self):
        # #81 hardening: a host that already declares a commentable-html-kind meta must not end
        # up with TWO kind metas after a retrofit. The existing meta is REPLACED with the
        # requested kind, so exactly one remains and it is the requested one. A report needs a
        # top-level <h1>, which the host provides, so the result self-validates clean.
        d = self._tmpdir()
        host = HOST_HTML.replace(
            "<title>Host Report</title>",
            '<title>Host Report</title>\n<meta name="commentable-html-kind" content="generic" />')
        host = host.replace("<section>", '<h1 id="doc-title">Host Report</h1>\n<section>')
        src = self._write(d, "host.html", host)
        out = os.path.join(d, "out.html")
        code, _stdout, stderr = self._run(
            ["retrofit.py", src, "--label", "Host Report", "--kind", "report", "--out", out])
        self.assertEqual(code, 0, stderr)
        html = _read_text(out)
        self.assertEqual(html.count("commentable-html-kind"), 1,
                         "retrofit duplicated the kind meta: %d present" % html.count("commentable-html-kind"))
        self.assertIn('<meta name="commentable-html-kind" content="report"', html)
        self.assertNotIn('content="generic"', html)
        self._strict_clean(out)

    def test_reordered_existing_kind_meta_is_replaced(self):
        # The existing kind meta is detected order-independently (content before name), so a
        # non-canonical attribute order still triggers a replace, not a duplicate append.
        d = self._tmpdir()
        host = HOST_HTML.replace(
            "<title>Host Report</title>",
            '<title>Host Report</title>\n<meta content="board" name="commentable-html-kind">')
        src = self._write(d, "host.html", host)
        out = os.path.join(d, "out.html")
        code, _stdout, stderr = self._run(
            ["retrofit.py", src, "--label", "Host Board", "--kind", "board", "--out", out])
        self.assertEqual(code, 0, stderr)
        html = _read_text(out)
        self.assertEqual(html.count("commentable-html-kind"), 1,
                         "retrofit duplicated the kind meta: %d present" % html.count("commentable-html-kind"))
        self.assertIn('content="board"', html)
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
        self.assertLess(html.index("BEGIN: commentable-html - CONTENT"), html.index("END: commentable-html - CONTENT"))
        self.assertLess(html.index("END: commentable-html - CONTENT"), html.index("BEGIN: commentable-html - JS"))
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

    def test_rejects_non_optional_implicit_closure_malformed_html(self):
        d = self._tmpdir()
        cases = {
            "span.html": "<!doctype html><html><head><title>x</title></head><body><div><span>x</div></body></html>",
            "div-body.html": "<!doctype html><html><head><title>x</title></head><body><div>x</body></html>",
        }
        for name, html in cases.items():
            with self.subTest(name=name):
                src = self._write(d, name, html)
                out = os.path.join(d, "out-" + name)
                code, _stdout, stderr = self._run(["retrofit.py", src, "--label", "Bad", "--out", out])
                self.assertEqual(code, 2)
                self.assertIn("malformed HTML", stderr)
                self.assertFalse(os.path.exists(out))

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

    def test_root_selector_refuses_implicitly_closed_root(self):
        d = self._tmpdir()
        html = """<!doctype html>
<html>
<head><meta charset="utf-8"><title>Implicit root</title></head>
<body><section><p id="content">Loose paragraph</section></body>
</html>
"""
        src = self._write(d, "host.html", html)
        out = os.path.join(d, "out.html")
        code, _stdout, stderr = self._run([
            "retrofit.py", src, "--label", "Host", "--root-selector", "#content", "--out", out])
        self.assertEqual(code, 2)
        self.assertIn("explicit closing tag", stderr)
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

    def test_theme_vars_block_contains_only_theme_css(self):
        d = self._tmpdir()
        src = self._write(d, "host.html", HOST_HTML)
        cases = {
            "nonportable.html": [],
            "portable.html": ["--portable"],
        }
        for name, extra_args in cases.items():
            with self.subTest(name=name):
                out = os.path.join(d, name)
                code, _stdout, stderr = self._run([
                    "retrofit.py", src, "--label", "Host", "--out", out] + extra_args)
                self.assertEqual(code, 0, stderr)
                theme = self._theme_vars_block(_read_text(out))
                self.assertIn("--cp-", theme)
                for leaked in ("<meta", "HANDLED IDS", "<!DOCTYPE"):
                    self.assertNotIn(leaked, theme)

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

    def test_favicon_is_added_when_host_head_has_none(self):
        # A host with no <link rel="icon"> would leave the browser tab showing the generic
        # globe and trip the validator's favicon check; retrofit injects the CMH favicon.
        self.assertNotIn('rel="icon"', HOST_HTML, "fixture must start without a favicon")
        d = self._tmpdir()
        src = self._write(d, "host.html", HOST_HTML)
        out = os.path.join(d, "fav.html")
        code, _stdout, stderr = self._run([
            "retrofit.py", src, "--label", "Fav Host", "--portable", "--out", out])
        self.assertEqual(code, 0, stderr)
        html = _read_text(out)
        self.assertEqual(len(re.findall(r'<link\b[^>]*\brel="icon"', html)), 1,
                         "retrofit should inject exactly one CMH favicon")
        self._strict_clean(out)

    def test_existing_host_favicon_is_not_duplicated(self):
        # A host that already declares a favicon keeps its own and gets no injected duplicate.
        host = HOST_HTML.replace("<title>Host Report</title>",
                                 '<title>Host Report</title>\n<link rel="icon" href="/host.ico">')
        d = self._tmpdir()
        src = self._write(d, "host.html", host)
        out = os.path.join(d, "fav.html")
        code, _stdout, stderr = self._run([
            "retrofit.py", src, "--label", "Fav Host", "--portable", "--out", out])
        self.assertEqual(code, 0, stderr)
        html = _read_text(out)
        self.assertIn('href="/host.ico"', html)
        self.assertEqual(len(re.findall(r'<link\b[^>]*\brel="icon"', html)), 1,
                         "retrofit must not add a second favicon when the host already has one")
        self._strict_clean(out)

    def test_apple_touch_icon_only_host_still_gets_a_real_favicon(self):
        # A host whose only icon-ish link is rel="apple-touch-icon" has no browser-tab favicon, so
        # retrofit must still inject the CMH favicon (detection is token-exact, matching the
        # validator) - otherwise the output would trip the validator's favicon check.
        host = HOST_HTML.replace("<title>Host Report</title>",
                                 '<title>Host Report</title>\n<link rel="apple-touch-icon" href="/a.png">')
        d = self._tmpdir()
        src = self._write(d, "host.html", host)
        out = os.path.join(d, "fav.html")
        code, _stdout, stderr = self._run([
            "retrofit.py", src, "--label", "Fav Host", "--portable", "--out", out])
        self.assertEqual(code, 0, stderr)
        html = _read_text(out)
        self.assertIn('rel="apple-touch-icon"', html)
        self.assertIn('rel="icon"', html)
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

    _REPORT_HOST = (
        "<!doctype html>\n<html><head><meta charset=\"utf-8\"><title>Plan</title></head>\n<body>\n"
        "<h1>Migration Plan</h1>\n"
        '<section><h2 id="a">1. Goals</h2><p>Some goal text for the plan review.</p></section>\n'
        '<section><h2 id="b">2. Scope</h2><p>Scope details for the plan review.</p></section>\n'
        "</body></html>\n")

    def test_report_gets_doc_stats_by_default(self):
        # CMH-STATS-01: retrofitting a report bakes the overview strip.
        d = self._tmpdir()
        src = self._write(d, "host.html", self._REPORT_HOST)
        out = os.path.join(d, "out.html")
        code, _stdout, stderr = self._run(
            ["retrofit.py", src, "--label", "Migration Plan", "--kind", "report", "--out", out])
        self.assertEqual(code, 0, stderr)
        html = _read_text(out)
        self.assertIn("data-cmh-doc-stats", html)
        self.assertIn("<strong>2</strong> sections", html)
        self._strict_clean(out)

    def test_no_stats_flag_skips_the_overview_strip(self):
        # CMH-STATS-01: --no-stats keeps retrofit from baking the overview strip.
        d = self._tmpdir()
        src = self._write(d, "host.html", self._REPORT_HOST)
        out = os.path.join(d, "out.html")
        code, _stdout, stderr = self._run(
            ["retrofit.py", src, "--label", "Migration Plan", "--kind", "report", "--out", out, "--no-stats"])
        self.assertEqual(code, 0, stderr)
        self.assertNotIn("data-cmh-doc-stats", _read_text(out))

    def test_dedups_existing_numbered_ordered_toc(self):
        # CMH-TOC-10: retrofitting de-dups an author-numbered ordered-list .cm-toc.
        d = self._tmpdir()
        host = self._REPORT_HOST.replace(
            "<h1>Migration Plan</h1>\n",
            "<h1>Migration Plan</h1>\n"
            '<nav class="cm-toc"><ol><li><a href="#a">1. Goals</a></li>'
            '<li><a href="#b">2. Scope</a></li></ol></nav>\n')
        src = self._write(d, "host.html", host)
        out = os.path.join(d, "out.html")
        code, _stdout, stderr = self._run(
            ["retrofit.py", src, "--label", "Migration Plan", "--kind", "report", "--out", out])
        self.assertEqual(code, 0, stderr)
        html = _read_text(out)
        self.assertIn('<a href="#a">Goals</a>', html)
        self.assertIn('<a href="#b">Scope</a>', html)
        self._strict_clean(out)


class FaviconHelperTests(unittest.TestCase):
    """Direct tests for the shared favicon helper (tools/authoring/_favicon.py). It must match the
    validator's HTMLParser-based, token-exact, head-scoped detection so retrofit/upgrade inject a
    favicon exactly when the validator would warn."""

    def setUp(self):
        import _favicon
        self.f = _favicon

    def test_rel_token_is_exact_not_substring(self):
        self.assertTrue(self.f.rel_is_favicon("icon"))
        self.assertTrue(self.f.rel_is_favicon("shortcut icon"))
        self.assertTrue(self.f.rel_is_favicon("ICON"))
        self.assertFalse(self.f.rel_is_favicon("apple-touch-icon"))
        self.assertFalse(self.f.rel_is_favicon("mask-icon"))
        self.assertFalse(self.f.rel_is_favicon(""))
        self.assertFalse(self.f.rel_is_favicon(None))

    def test_head_has_favicon_true_for_real_icon(self):
        self.assertTrue(self.f.head_has_favicon('<head><link rel="icon" href="/f.ico"></head>'))
        self.assertTrue(self.f.head_has_favicon('<head><link rel="shortcut icon" href="/f.ico" /></head>'))

    def test_empty_or_missing_href_is_not_a_favicon(self):
        self.assertFalse(self.f.head_has_favicon('<head><link rel="icon" href=""></head>'))
        self.assertFalse(self.f.head_has_favicon('<head><link rel="icon"></head>'))

    def test_apple_touch_icon_is_not_a_favicon(self):
        self.assertFalse(self.f.head_has_favicon('<head><link rel="apple-touch-icon" href="/a.png"></head>'))

    def test_data_attributes_do_not_count(self):
        # data-rel / data-href must NOT be read as rel / href (the regex bug round 2 found).
        self.assertFalse(self.f.head_has_favicon('<head><link data-rel="icon" href="/x.ico"></head>'))
        self.assertFalse(self.f.head_has_favicon('<head><link rel="icon" data-href="/x.ico"></head>'))

    def test_link_inside_script_or_style_or_comment_does_not_count(self):
        self.assertFalse(self.f.head_has_favicon(
            '<head><script>var s = "<link rel=\\"icon\\" href=\\"/x.ico\\">";</script></head>'))
        self.assertFalse(self.f.head_has_favicon(
            '<head><style>/* <link rel="icon" href="/x.ico"> */</style></head>'))
        self.assertFalse(self.f.head_has_favicon('<head><!-- <link rel="icon" href="/x.ico"> --></head>'))

    def test_detection_is_head_scoped(self):
        # A favicon after the head (body-level, or after a flow element that implicitly ends the
        # head) does not count.
        self.assertFalse(self.f.head_has_favicon(
            '<head></head><body><link rel="icon" href="/b.ico"></body>'))
        self.assertFalse(self.f.head_has_favicon('<div><link rel="icon" href="/b.ico"></div>'))

    def test_no_quadratic_blowup_on_adversarial_input(self):
        # The old two-stage regex scan was O(n^2) on many unterminated <!-- / <link delimiters;
        # the HTMLParser-based helper must handle a large adversarial head quickly.
        import time
        payload = "<head>" + ("<!--" * 60000) + ("<link " * 60000) + "</head>"
        start = time.monotonic()
        self.assertFalse(self.f.head_has_favicon(payload))
        self.assertLess(time.monotonic() - start, 5.0)

    def test_template_favicon_tag_returns_verbatim_tag(self):
        head = '<head>\n<link rel="icon" href="data:image/svg+xml,%3Csvg%3E%3C/svg%3E" />\n</head>'
        tag = self.f.template_favicon_tag(head)
        self.assertIsNotNone(tag)
        self.assertIn('rel="icon"', tag)
        self.assertIn(tag, head)
        self.assertIsNone(self.f.template_favicon_tag("<head></head>"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
