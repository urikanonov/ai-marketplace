"""CMH-SIZE-05/03/04: the content-first document layout.

Every shipped template and every built example must put the authored content FIRST in source
order and park all generated machinery - the layer stylesheet, the comment-UI markup, the saved
comment state, the optional loaders, the vendored rich-content payload, and the runtime - behind
one explicitly fenced trailer. A tool that reads the first N KB of the raw file must get the
title and the opening of the content rather than a megabyte of base64 and a minified runtime.
"""
import glob
import os
import re
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _paths  # noqa: E402

sys.path.insert(0, os.path.join(_paths.DEV, "skill", "tools", "authoring"))
import upgrade  # noqa: E402

# The budget the issue states: a machine reading the first 50 KB of a document must reach the title
# and the opening of the authored content, and must not have to wade through machinery to do it.
HEAD_BUDGET = 50 * 1024
MACHINERY_BEGIN = "BEGIN: commentable-html - MACHINERY"
MACHINERY_END = "END: commentable-html - MACHINERY"
FIRST_PAINT_BEGIN = "BEGIN: commentable-html - FIRST PAINT"
CONTENT_BEGIN = "BEGIN: commentable-html - CONTENT"
CONTENT_END = "END: commentable-html - CONTENT"
SKIP_NOTE = "commentable-html machinery (non-content"
LAYER_REGIONS = ("CSS", "HANDLED IDS", "EMBEDDED COMMENTS", "COMMENT UI", "JS")


def _read(path):
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def _documents():
    """(label, html) for every shipped template and every built example."""
    out = []
    for name in ("SHAREABLE.html", "NONSHAREABLE.html"):
        out.append(("dist/" + name, _read(os.path.join(_paths.DIST, name))))
    for path in sorted(glob.glob(os.path.join(_paths.EXAMPLES, "*.html"))):
        out.append(("examples/" + os.path.basename(path), _read(path)))
    return out


def _marker_offset(html, kind, name):
    """The offset of a region marker, located the way the validator locates it (line-anchored), so
    a quotation of the marker inside authored content or inside the runtime never counts."""
    matches = upgrade._region_marker_matches(html, kind, name)
    assert len(matches) == 1, "%s: %s marker for %s appears %d times" % (
        kind, name, name, len(matches))
    return matches[0].start()


def _fence_bounds(html):
    """(start, end) of the MACHINERY fence, located the way PRODUCTION locates it - line-anchored
    - so a test can never pin the boundary more loosely than the code it guards."""
    begins = upgrade._region_marker_matches(html, "BEGIN", "MACHINERY")
    ends = upgrade._region_marker_matches(html, "END", "MACHINERY")
    assert len(begins) == 1 and len(ends) == 1, "expected exactly one MACHINERY marker pair"
    return begins[0].start(), ends[0].start()


def _assert_skip_notes_lead_blocks(case, html, where):
    """Every named region inside the fence is preceded by a skip note that no OTHER fenced block
    sits between - the LEADING half of the acceptance criterion, which a single note at the top of
    the fence would otherwise satisfy for all five."""
    fence, _fence_end = _fence_bounds(html)
    begins = {name: _marker_offset(html, "BEGIN", name) for name in LAYER_REGIONS}
    for name in LAYER_REGIONS:
        begin = begins[name]
        note = html.rfind(SKIP_NOTE, fence, begin)
        case.assertNotEqual(note, -1,
                            "%s: region %s must be announced as skippable machinery"
                            % (where, name))
        intruders = [other for other, at in begins.items() if other != name and note < at < begin]
        case.assertEqual(intruders, [],
                         "%s: the skip note before region %s actually leads %s"
                         % (where, name, ", ".join(intruders)))


class ContentComesFirstTests(unittest.TestCase):
    """CMH-SIZE-05: machinery follows the authored content in source order."""

    def test_every_document_puts_its_content_before_the_machinery_fence(self):
        for label, html in _documents():
            with self.subTest(document=label):
                content = html.find(CONTENT_BEGIN)
                fence = html.find(MACHINERY_BEGIN)
                self.assertNotEqual(content, -1, "no CONTENT region")
                self.assertNotEqual(fence, -1, "no MACHINERY fence")
                self.assertLess(content, fence,
                                "the authored content must precede the machinery fence")

    def test_every_layer_region_sits_inside_the_machinery_fence(self):
        for label, html in _documents():
            with self.subTest(document=label):
                fence = html.index(MACHINERY_BEGIN)
                fence_end = html.index(MACHINERY_END, fence + len(MACHINERY_BEGIN))
                content_end = html.index(CONTENT_END)
                for name in LAYER_REGIONS:
                    begin = _marker_offset(html, "BEGIN", name)
                    end = _marker_offset(html, "END", name)
                    self.assertGreater(begin, content_end,
                                       "region %s must follow the authored content" % name)
                    self.assertTrue(fence < begin < end < fence_end,
                                    "region %s must sit inside the machinery fence" % name)

    def test_the_vendored_payload_never_precedes_the_content(self):
        for label, html in _documents():
            with self.subTest(document=label):
                at = html.find('id="cmhVendoredRichLibs"')
                if at == -1:
                    continue          # a prose-only document legitimately carries no payload
                self.assertGreater(at, html.index(CONTENT_END),
                                   "the vendored payload must follow the authored content")
                fence = html.index(MACHINERY_BEGIN)
                fence_end = html.index(MACHINERY_END, fence)
                self.assertTrue(fence < at < fence_end,
                                "the payload must sit INSIDE the machinery fence, not after it")

    def test_the_first_50kb_yields_the_title_and_the_opening_of_the_content(self):
        for label, html in _documents():
            with self.subTest(document=label):
                head = html[:HEAD_BUDGET]
                self.assertIn("<title>", head, "the title must be readable in the first 50 KB")
                self.assertIn(CONTENT_BEGIN, head,
                              "the content must start within the first 50 KB")

    def test_no_machinery_precedes_the_content(self):
        for label, html in _documents():
            with self.subTest(document=label):
                prefix = html[:html.index(CONTENT_BEGIN)]
                self.assertNotIn("cmhVendoredRichLibs", prefix,
                                 "no base64 payload may precede the content")
                self.assertIsNone(_paths.CMH_VERSION_CONST_RE.search(prefix),
                                  "no minified runtime may precede the content")
                self.assertNotIn("BEGIN: commentable-html - CSS", prefix,
                                 "no layer stylesheet may precede the content")
                self.assertNotIn("BEGIN: commentable-html - COMMENT UI", prefix,
                                 "no comment-UI markup may precede the content")

    def test_a_head_script_data_escape_cannot_swallow_the_content(self):
        # A `<script>` in the HEAD whose bytes open a script-data escape leaves the tokenizer
        # swallowing everything after it until the next `</script>`. With the machinery first that
        # was a state block; with the content first it would be the authored document. The one
        # thing the layer puts before the content is a terminator carrying those exact bytes.
        for label, html in _documents():
            with self.subTest(document=label):
                body = html.index(">", html.index("<body")) + 1
                content = html.index(CONTENT_BEGIN)
                # Well-formed, not a stray end tag: the bytes are raw text inside a `<style>`, so a
                # browser (and every tool that parses this document) reads them as a CSS comment.
                style_open = html.find("<style", body, content)
                self.assertNotEqual(style_open, -1,
                                    "the escape terminator must precede the authored content")
                style_close = html.index("</style>", style_open)
                self.assertIn("</script", html[style_open:style_close],
                              "the terminator must carry the script end-tag bytes")
                self.assertLess(style_close, content,
                                "the terminator must be closed before the authored content")

    def test_the_shell_template_source_is_content_first_too(self):
        # The shell is the single source every template, example, and generated document derives
        # from, so the property has to hold there rather than only in the build output.
        shell = _read(os.path.join(_paths.ASSETS, "template.shell.html"))
        self.assertLess(shell.index(CONTENT_BEGIN), shell.index(MACHINERY_BEGIN))
        for placeholder in ("{{CMH_CSS}}", "{{CMH_JS}}", "{{CMH_VENDORED_RICH_LIBS}}"):
            self.assertGreater(shell.index(placeholder), shell.index(CONTENT_END),
                               "%s must be stamped after the authored content" % placeholder)

    def test_every_example_source_is_content_first_too(self):
        # `regen_example` swaps region CONTENT in place; it does NOT reorder. So a NEW example
        # source authored in the old (machinery-first) shape would ship machinery-first, and the
        # built-artifact tests above would fail with no hint of where to fix it. Pin the SOURCES
        # directly, with a message that names the shell as the model to copy.
        sources = sorted(glob.glob(os.path.join(_paths.DEV, "examples", "src", "*.html")))
        self.assertTrue(sources, "no example sources found")
        for path in sources:
            with self.subTest(source=os.path.basename(path)):
                html = _read(path)
                self.assertIn(MACHINERY_BEGIN, html,
                              "an example source must carry the machinery fence - copy the layout "
                              "of assets/template.shell.html (content first, machinery fenced)")
                self.assertLess(html.index(CONTENT_BEGIN), html.index(MACHINERY_BEGIN),
                                "the authored content must precede the machinery fence")


class MachineryFenceTests(unittest.TestCase):
    """CMH-SIZE-06: every machinery block is explicitly delimited and announced."""

    def test_the_fence_is_a_single_matched_pair_that_says_what_it_holds(self):
        for label, html in _documents():
            with self.subTest(document=label):
                begins = upgrade._region_marker_matches(html, "BEGIN", "MACHINERY")
                ends = upgrade._region_marker_matches(html, "END", "MACHINERY")
                self.assertEqual(len(begins), 1, "exactly one MACHINERY BEGIN marker")
                self.assertEqual(len(ends), 1, "exactly one MACHINERY END marker")
                self.assertLess(begins[0].start(), ends[0].start())
                lead = html[begins[0].start():html.index("-->", begins[0].start())]
                self.assertIn("NON-CONTENT MACHINERY", lead.upper(),
                              "the fence must say the block below it is non-content machinery")

    def test_every_block_in_the_fence_carries_a_leading_skip_note(self):
        for label, html in _documents():
            with self.subTest(document=label):
                _assert_skip_notes_lead_blocks(self, html, label)

    def test_the_fence_ends_the_body(self):
        for label, html in _documents():
            with self.subTest(document=label):
                end = html.index(MACHINERY_END)
                after = html[html.index("-->", end) + 3:]
                self.assertEqual(after.split(), ["</body>", "</html>"],
                                 "nothing but the closing tags may follow the fence")


class GeneratedDocumentLayoutTests(unittest.TestCase):
    """CMH-SIZE-05: the layout holds for the documents the TOOLS generate, not just the templates.

    `retrofit.py` builds its own layer layout rather than copying the shell wholesale, so it is
    the one generation path that can silently keep emitting machinery-first documents while every
    template-based test stays green.
    """

    FRAGMENT = "<h1>Generated</h1>\n<p>Some prose so the content is not empty.</p>"

    def _assert_content_first(self, html, where):
        self.assertIn(MACHINERY_BEGIN, html, "%s: no machinery fence" % where)
        self.assertLess(html.index(CONTENT_BEGIN), html.index(MACHINERY_BEGIN),
                        "%s: the authored content must precede the machinery" % where)
        prefix = html[:html.index(CONTENT_BEGIN)]
        self.assertNotIn("BEGIN: commentable-html - CSS", prefix,
                         "%s: no layer stylesheet may precede the content" % where)
        self.assertNotIn("BEGIN: commentable-html - COMMENT UI", prefix,
                         "%s: no comment-UI markup may precede the content" % where)
        self.assertIn(FIRST_PAINT_BEGIN, html[:html.index("</head>")],
                      "%s: the first-paint guard must be in the head" % where)

    def test_new_document_is_content_first(self):
        import new_document
        html = new_document.make_document(
            _read(_paths.TEMPLATE), self.FRAGMENT, key="layout-test", label="Layout",
            source="doc.html", kind="report")
        self._assert_content_first(html, "new_document")

    def test_retrofit_is_content_first_in_both_modes(self):
        import retrofit
        for shareable in (True, False):
            with self.subTest(shareable=shareable):
                head, body_top, body_bottom = retrofit._layer_parts(shareable, "report")
                self.assertEqual(body_top, "",
                                 "nothing may be injected ahead of the host's own content")
                self.assertNotIn("BEGIN: commentable-html - CSS", head,
                                 "the layer stylesheet must not go in the head")
                self.assertIn(FIRST_PAINT_BEGIN, head, "the first-paint guard belongs in the head")
                fence = body_bottom.index(MACHINERY_BEGIN)
                fence_end = body_bottom.index(MACHINERY_END, fence)
                for name in LAYER_REGIONS:
                    at = body_bottom.index("BEGIN: commentable-html - " + name)
                    self.assertTrue(fence < at < fence_end,
                                    "region %s must sit inside the machinery fence" % name)
                order = [body_bottom.index("BEGIN: commentable-html - " + n) for n in LAYER_REGIONS]
                self.assertEqual(order, sorted(order),
                                 "the five regions must keep the order the validator enforces")
                _assert_skip_notes_lead_blocks(self, body_bottom, "retrofit trailer")

    def test_retrofit_refuses_a_host_that_already_carries_the_fence(self):
        # Two tools now depend on the machinery fence being a single unambiguous pair, so a host
        # page that already has one must be refused rather than given a second.
        import retrofit
        host = ("<!DOCTYPE html><html><head><title>Host</title></head><body>\n"
                "<!-- BEGIN: commentable-html - MACHINERY -->\n"
                "<!-- END: commentable-html - MACHINERY -->\n</body></html>\n")
        parser = retrofit._parse_structure(host)
        self.assertTrue(retrofit._has_layer(host, parser),
                        "a host carrying a MACHINERY fence must be refused")


class FenceLookupParityTests(unittest.TestCase):
    """CMH-SIZE-05: the three production copies of the fence lookup must agree.

    `upgrade.py` (the authoring tool), `tools/build_parts/30-examples.py` (the build's mirror) and
    `tools/authoring/vendored_libs.py` (the payload placer) each locate the fence. The repo already
    pins the mermaid-loader mirror this way; a one-sided change here would show up as a document
    whose loader stops being refreshed, or whose payload lands outside the fence, on a rare path.
    """

    CASES = (
        ("no fence", "<html><body><p>hi</p></body></html>"),
        ("clean fence",
         "<html><body>\n<main id=\"commentRoot\">\n"
         "<!-- BEGIN: commentable-html - CONTENT -->\n<p>hi</p>\n"
         "<!-- END: commentable-html - CONTENT -->\n</main>\n"
         "<!-- BEGIN: commentable-html - MACHINERY -->\n"
         "<!-- END: commentable-html - MACHINERY -->\n</body></html>"),
        ("quoted fence inside the content",
         "<html><body>\n<main id=\"commentRoot\">\n"
         "<!-- BEGIN: commentable-html - CONTENT -->\n"
         "<!-- BEGIN: commentable-html - MACHINERY -->\n<p>a quoted example</p>\n"
         "<!-- END: commentable-html - MACHINERY -->\n"
         "<!-- END: commentable-html - CONTENT -->\n</main>\n"
         "<!-- BEGIN: commentable-html - MACHINERY -->\n"
         "<!-- END: commentable-html - MACHINERY -->\n</body></html>"),
    )

    def test_the_three_fence_lookups_agree(self):
        import vendored_libs
        sys.path.insert(0, os.path.join(_paths.DEV, "tools"))
        import build  # noqa: E402  the assembled build script exposes the mirror

        for label, html in self.CASES:
            with self.subTest(case=label):
                def _upgrade():
                    try:
                        return upgrade._machinery_fence(html)
                    except ValueError:
                        return "ambiguous"

                def _build():
                    try:
                        return build._machinery_fence(html)
                    except SystemExit:
                        return "ambiguous"

                self.assertEqual(_upgrade(), _build(),
                                 "the authoring tool and the build mirror disagree")
                fence = _upgrade()
                root_end = html.find("</main>")
                end = vendored_libs._machinery_fence_end(html, root_end if root_end != -1 else None)
                if fence in (None, "ambiguous"):
                    self.assertIsNone(end, "the payload placer must not find a fence either")
                else:
                    self.assertIsNotNone(end, "the payload placer must find the same fence")
                    self.assertTrue(fence[0] < end < fence[1],
                                    "the payload anchor must sit inside the located fence")


class BrandCascadeTests(unittest.TestCase):
    """CMH-SIZE-05: a brand profile must still WIN the cascade against the layer's own `:root`.

    That is the whole reason the brand `<style>` moved; before this test only its PRESENCE was
    asserted, which holds no matter which side wins.
    """

    PROFILE = '{"tokens": {"--cp-accent": "#123456"}}'

    def _branded(self, template_path):
        import _brand_profile
        import new_document
        html = new_document.make_document(
            _read(template_path), "<h1>Brand</h1>\n<p>Prose.</p>", key="brand-cascade",
            label="Brand", source="doc.html", kind="report")
        directory = tempfile.mkdtemp(prefix="cmh-brand-cascade-")
        self.addCleanup(shutil.rmtree, directory, True)
        path = os.path.join(directory, "brand.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(self.PROFILE)
        branded, _warnings = _brand_profile.apply_brand(html, path)
        return branded

    def test_the_brand_style_follows_the_layer_stylesheet(self):
        for name in ("SHAREABLE.html", "NONSHAREABLE.html"):
            with self.subTest(template=name):
                html = self._branded(os.path.join(_paths.DIST, name))
                brand = html.index("data-cmh-brand")
                css_end = _marker_offset(html, "END", "CSS")
                self.assertGreater(brand, css_end,
                                   "the brand tokens must be parsed AFTER the layer stylesheet, "
                                   "or the layer wins every equal-specificity :root tie")


class PrintStylePlacementTests(unittest.TestCase):
    """CMH-SIZE-05: the runtime print `<style>` must still be the LAST stylesheet parsed.

    Its `@page{margin:PAD}` and its tall-diagram measurement cap only win by source order, and the
    layer stylesheet is no longer in `<head>` - so injecting into the head would silently lose
    every tie and reintroduce the multi-page spill the tall rule exists to prevent.
    """

    def test_the_print_style_is_appended_to_the_body(self):
        source = _read(os.path.join(_paths.ASSETS, "js", "83-print.js"))
        at = source.index('styleEl.id = "cmhPrintSinglePage"')
        window = source[at:at + 900]
        self.assertNotIn("document.head.appendChild(styleEl)", window,
                         "the print style must not be injected into the head")
        self.assertIn("appendChild(styleEl)", window)
        body_at = window.index("document.body")
        root_at = window.index("document.documentElement")
        # The OPERAND ORDER matters, not merely the presence of both names: `documentElement ||
        # body` would always append to <html>, which is not after the layer stylesheet.
        self.assertLess(body_at, root_at,
                        "the body must be the preferred append target, with documentElement only "
                        "as the fallback")


class FirstPaintGuardTests(unittest.TestCase):
    """CMH-SIZE-07: moving the stylesheet behind the content must not flash unstyled content."""

    def test_the_guard_hides_the_body_until_the_stylesheet_is_parsed(self):
        for label, html in _documents():
            with self.subTest(document=label):
                guard = html.find(FIRST_PAINT_BEGIN)
                self.assertNotEqual(guard, -1, "the first-paint guard must be present")
                head = html[:html.index("</head>")]
                self.assertLess(guard, len(head),
                                "the guard must run before anything can paint")
                self.assertIn("cmh-awaiting-style", head)
                self.assertIn("visibility: hidden", head)

    def test_the_guard_paints_the_theme_canvas_before_the_stylesheet_arrives(self):
        # `visibility: hidden` suppresses the content but not the page canvas, and the theme
        # background is one of the tokens the trailing stylesheet carries - so without this a
        # dark-theme document flashes white before the reveal.
        for label, html in _documents():
            with self.subTest(document=label):
                head = html[:html.index("</head>")]
                self.assertRegex(head, r"html\.cmh-awaiting-style\s*\{[^}]*background:",
                                 "the guard must paint the light canvas")
                self.assertRegex(
                    head,
                    r'html\.cmh-awaiting-style\[data-theme="dark"\]\s*\{[^}]*background:',
                    "the guard must paint the dark canvas too")

    def test_the_reveal_runs_immediately_after_the_layer_stylesheet(self):
        for label, html in _documents():
            with self.subTest(document=label):
                css_end = _marker_offset(html, "END", "CSS")
                reveal = html.find("__cmhRevealDocument", css_end)
                self.assertNotEqual(reveal, -1, "the reveal script must follow the stylesheet")
                self.assertLess(reveal, _marker_offset(html, "BEGIN", "HANDLED IDS"),
                                "the reveal must not wait for the rest of the machinery")

    def test_a_scripting_off_document_is_never_hidden(self):
        # The guard rule keys on a class only the guard's own script adds, so a document opened
        # with scripting disabled paints normally instead of staying blank forever.
        for label, html in _documents():
            with self.subTest(document=label):
                head = html[:html.index("</head>")]
                rule = re.search(r"html\.cmh-awaiting-style\s+body\s*\{[^}]*\}", head)
                self.assertIsNotNone(rule, "the guard rule must be class-gated")
                self.assertIn("classList.add(\"cmh-awaiting-style\")", head)

    def test_the_guard_reveals_even_if_the_stylesheet_never_arrives(self):
        for label, html in _documents():
            with self.subTest(document=label):
                head = html[:html.index("</head>")]
                self.assertIn("DOMContentLoaded", head,
                              "a parse that never reaches the stylesheet still reveals")
                self.assertRegex(head, r"setTimeout\(\s*reveal\s*,\s*\d+\s*\)",
                                 "a timeout failsafe must reveal the document")


if __name__ == "__main__":
    unittest.main()
