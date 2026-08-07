#!/usr/bin/env python3
"""CMH-VAL-21: ONE escape writes an ATTRIBUTE value and ONE writes a TEXT run.

HTML's input-stream preprocessing turns every CR (and every CRLF) into a single LF BEFORE
tokenization, so a LITERAL CR written into a document is not the character the value named - a
browser reads LF. `html.escape` has never had that rule, so every tool that GENERATED a value from
a CLI argument or a JSON field silently downgraded an authored CR. Worse, once the shared start-tag
re-serializer applied the rule, ONE `--label` could reach a browser as TWO different values in the
same document: `&#13;` in `data-doc-label` and a folded LF in the `<title>` beside it.

These tests read every generated value the way a browser reads it - preprocessing FIRST, then the
shared decode - which is the browser's own order, and the order that makes the defect visible at
all (reading the raw text without the fold is exactly what let it through).
"""
import html as _html
import io
import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402  shared pkg/dev split path constants + tools bootstrap

sys.path.insert(0, _paths.TOOLS)

import _browser_attrs  # noqa: E402
import chart_block  # noqa: E402
import checklist_scaffold  # noqa: E402
import diff_block  # noqa: E402
import highlight_code  # noqa: E402
import kql_highlight  # noqa: E402
import new_document  # noqa: E402
import notes_scaffold  # noqa: E402
import retrofit  # noqa: E402

TEMPLATE = os.path.join(_paths.PKG, "dist", "SHAREABLE.html")

CR_LABEL = "Q3 review\rand sign-off"


def _preprocess(text):
    """HTML's input-stream preprocessing: CRLF and a lone CR fold to LF, before tokenization."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _attr_a_browser_reads(document, name):
    """The value a browser ends up with for the FIRST `name` attribute in `document`.

    Preprocessing is applied to the whole document first (as a browser does), the start tag
    carrying the attribute is located with the shared scan, and its value comes back through the
    shared attribute decode. Reading the raw text instead would hide the very difference these
    tests exist to pin.
    """
    doc = _preprocess(document)
    for match in re.finditer(r"<[a-zA-Z]", doc):
        scanned = _browser_attrs.scan_start_tag(doc, match.start())
        if scanned is None:
            continue
        end, tag, _self_closing = scanned
        interior = doc[match.start() + 1 + len(tag):end - 1]
        for key, value in _browser_attrs.raw_attrs_pairs(interior):
            if key == name:
                return value
    raise AssertionError("no %r attribute in %r" % (name, document[:400]))


def _text_a_browser_reads(document, tag):
    """The text a browser ends up with inside the FIRST `<tag>` element in `document`."""
    doc = _preprocess(document)
    match = re.search(r"(?is)<%s\b[^>]*>(.*?)</%s\s*>" % (tag, tag), doc)
    if match is None:
        raise AssertionError("no <%s> element in %r" % (tag, document[:400]))
    return _browser_attrs.unescape_text(re.sub(r"(?s)<[^>]*>", "", match.group(1)))


class SharedValueEscapeTests(unittest.TestCase):
    """The escape pair itself: the CR rule, the two contexts, and totality."""

    def test_a_cr_is_written_as_a_character_reference_in_both_contexts(self):
        self.assertEqual(_browser_attrs.escape_attr_value("a\rb"), "a&#13;b")
        self.assertEqual(_browser_attrs.escape_text("a\rb"), "a&#13;b")

    def test_a_crlf_keeps_both_characters_because_preprocessing_folds_the_pair(self):
        # CRLF is ONE LF to a browser only when it is literal; the escape names the CR, so the
        # value comes back as the two characters the input actually held.
        self.assertEqual(_browser_attrs.escape_attr_value("a\r\nb"), "a&#13;\nb")
        self.assertEqual(_browser_attrs.escape_text("a\r\nb"), "a&#13;\nb")

    def test_lf_and_tab_are_not_escaped_because_they_already_round_trip(self):
        for escape in (_browser_attrs.escape_attr_value, _browser_attrs.escape_text):
            self.assertEqual(escape("a\nb\tc"), "a\nb\tc")

    def test_only_the_attribute_escape_escapes_quotes(self):
        self.assertEqual(_browser_attrs.escape_attr_value("say \"hi\" it's"),
                         "say &quot;hi&quot; it&#x27;s")
        self.assertEqual(_browser_attrs.escape_text("say \"hi\" it's"), "say \"hi\" it's")

    def test_both_escape_everything_html_escape_does(self):
        raw = "a<b>c&d\"e'f"
        self.assertEqual(_browser_attrs.escape_attr_value(raw), _html.escape(raw, quote=True))
        self.assertEqual(_browser_attrs.escape_text(raw), _html.escape(raw, quote=False))

    def test_an_authored_character_reference_is_not_turned_into_a_live_one(self):
        # The `&` the CR rule introduces is safe because `html.escape` has already run; an
        # authored `&#13;` must come back as text, not as a CR a browser decodes.
        for escape in (_browser_attrs.escape_attr_value, _browser_attrs.escape_text):
            self.assertEqual(escape("a&#13;b"), "a&amp;#13;b")

    def test_the_two_unwritable_code_points_fold_so_the_escape_is_total(self):
        for escape in (_browser_attrs.escape_attr_value, _browser_attrs.escape_text):
            self.assertEqual(escape("a\x00b"), "a\ufffdb")
            self.assertEqual(escape("a\ud800b"), "a\ufffdb")
            self.assertEqual(escape("a\udfffb"), "a\ufffdb")

    def test_the_fold_is_applied_before_the_escape_so_it_cannot_be_spelled_around(self):
        # Folding AFTER `html.escape` would leave a NUL that arrived as part of an escaped run
        # untouched; assert on the escape's own output rather than trusting the order.
        self.assertNotIn("\x00", _browser_attrs.escape_attr_value("<\x00>"))
        self.assertNotIn("\x00", _browser_attrs.escape_text("<\x00>"))

    def test_an_attribute_value_survives_a_code_point_sweep(self):
        # Totality: every code point a Python str can hold reads back as itself (bar the two
        # folds above) once preprocessing and the shared decode have run.
        for start in range(0, 0x110000, 977):
            raw = "x%sy" % chr(start)
            written = '<p title="%s">' % _browser_attrs.escape_attr_value(raw)
            expected = raw
            if start == 0 or 0xd800 <= start <= 0xdfff:
                expected = "x\ufffdy"
            self.assertEqual(_attr_a_browser_reads(written, "title"), expected,
                             "attribute value differs for U+%04X" % start)

    def test_neither_escape_accepts_a_non_string(self):
        for escape in (_browser_attrs.escape_attr_value, _browser_attrs.escape_text):
            self.assertEqual(escape(None), "")
            for bad in (0, 1, b"x", ["x"]):
                with self.assertRaises(TypeError):
                    escape(bad)

    def test_the_shared_start_tag_writer_uses_the_attribute_escape(self):
        tag = _browser_attrs.serialize_start_tag("p", [("title", "a\rb"), ("data-x", None)])
        self.assertEqual(tag, '<p title="a&#13;b" data-x="">')
        self.assertEqual(_attr_a_browser_reads(tag, "title"), "a\rb")


class LabelGeneratorTests(unittest.TestCase):
    """AC-2: one authored label cannot reach a browser as two different values."""

    def test_new_document_writes_one_label_into_the_attribute_title_and_lede(self):
        with open(TEMPLATE, encoding="utf-8") as fh:
            template = fh.read()
        content = new_document.ensure_doc_title("<section><h2 id=\"a\">Hi</h2><p>x</p></section>",
                                                CR_LABEL)
        out = new_document.make_document(template, content, "cr-label-doc", CR_LABEL)
        self.assertEqual(_attr_a_browser_reads(out, "data-doc-label"), CR_LABEL)
        self.assertEqual(_text_a_browser_reads(out, "title"), CR_LABEL)
        self.assertEqual(_text_a_browser_reads(out, "h1"), CR_LABEL)

    def test_retrofit_writes_one_label_into_the_root_attribute_and_the_title(self):
        root = retrofit._root_tag("cr-key", CR_LABEL, "report.html")
        self.assertEqual(_attr_a_browser_reads(root, "data-doc-label"), CR_LABEL)
        title = retrofit._insert_title_if_missing(
            "<html><head></head><body></body></html>", _HeadStub(), CR_LABEL)
        self.assertEqual(_text_a_browser_reads(title, "title"), CR_LABEL)


class _HeadStub(object):
    """The two offsets `_insert_title_if_missing` slices with, for a head that has no title."""
    start_end = len("<html><head>")
    end_start = start_end


class ScaffoldGeneratorTests(unittest.TestCase):
    """The remaining attribute and text generators the issue named."""

    def test_a_checklist_label_keeps_its_cr_in_the_attribute_and_the_item_text(self):
        out = checklist_scaffold.scaffold("Ship it\n", "release", CR_LABEL, "list")
        self.assertEqual(_attr_a_browser_reads(out, "data-cmh-checklist-label"), CR_LABEL)
        table = checklist_scaffold.scaffold("Ship it\n", "release", CR_LABEL, "table")
        self.assertEqual(_attr_a_browser_reads(table, "data-cmh-checklist-label"), CR_LABEL)

    def test_a_notes_label_and_seed_text_keep_their_cr(self):
        out = notes_scaffold.scaffold("risk", CR_LABEL, CR_LABEL)
        self.assertEqual(_attr_a_browser_reads(out, "data-cmh-note-label"), CR_LABEL)
        self.assertEqual(_text_a_browser_reads(out, "div"), CR_LABEL)

    def test_a_diff_block_label_and_language_keep_their_cr(self):
        out = diff_block.render_diff_block("--- a\n+++ b\n@@ -1 +1 @@\n-x\n+y\n",
                                           CR_LABEL, "a\rb")
        self.assertEqual(_attr_a_browser_reads(out, "data-diff-label"), CR_LABEL)
        self.assertEqual(_attr_a_browser_reads(out, "data-diff-lang"), "a\rb")

    def test_a_chart_caption_keeps_its_cr_in_the_figcaption_text(self):
        spec = {"type": "bar",
                "data": {"labels": ["a"], "datasets": [{"label": "d", "data": [1]}]}}
        fragments = chart_block.render_chart_fragments(spec, "cr-chart", CR_LABEL)
        figure = fragments["figure"]
        self.assertEqual(_text_a_browser_reads(figure, "figcaption"), CR_LABEL)
        # The aria label is a DERIVED value, not the caption: `derive_aria_label` collapses
        # runs of whitespace, so a CR cannot reach it and the two are deliberately different
        # strings. That is a normalization the author asked for, not escape drift.
        self.assertEqual(_attr_a_browser_reads(figure, "aria-label"),
                         "Chart: Q3 review and sign-off")

    def test_a_brand_label_keeps_its_cr_in_the_brand_attribute(self):
        import _brand_profile
        profile = _brand_profile.BrandProfile(CR_LABEL, (("--cp-bg", "#fff"),), (), (), ())
        rendered = _brand_profile.render(profile)
        self.assertEqual(_attr_a_browser_reads(rendered, "data-cmh-brand"), CR_LABEL)

    def test_the_language_class_goes_through_the_shared_attribute_escape(self):
        # This site cannot carry a CR: `_class_language` reduces the value to
        # [A-Za-z0-9_+.-] first, so the shared escape is here for ONE rule, not for a
        # behavior difference. Pin the reduction so that stays true.
        block = highlight_code.highlight_block("py\rthon", "x = 1")
        self.assertEqual(_attr_a_browser_reads(block, "class"), "language-py-thon")
        self.assertNotIn("\r", block)


class KqlReadBoundaryTests(unittest.TestCase):
    """The shared writer's PRECONDITION, at the caller whose document keeps its raw CRs."""

    def test_a_literal_cr_in_a_rewritten_run_link_is_not_escaped_back_into_a_cr(self):
        # `content_replace._read` reads with newline="" to preserve the file's newline
        # convention, so a literal CR is still a CR in the text `_run_link_tag`'s pairs come
        # from - where a browser had already folded it to LF. Writing it back as `&#13;` would
        # INVERT the bug the shared escape exists to fix, so the read applies input-stream
        # preprocessing (`raw_attrs_pairs`) before the writer ever sees the value. Go through
        # that real read path rather than handing `_run_link_tag` a CR it can never receive.
        pairs = _browser_attrs.raw_attrs_pairs(
            ' href="https://example.invalid/" title="a\rb"')
        tag = kql_highlight._run_link_tag(pairs, "https://example.invalid/q")
        self.assertNotIn("&#13;", tag)
        self.assertEqual(_attr_a_browser_reads(tag, "title"), "a\nb")


def _brand_profile_module():
    import _brand_profile
    return _brand_profile


if __name__ == "__main__":
    unittest.main()
