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
import deck_common  # noqa: E402
import diff_block  # noqa: E402
import doc_stamp  # noqa: E402
import highlight_code  # noqa: E402
import kql_highlight  # noqa: E402
import new_document  # noqa: E402
import notes_apply  # noqa: E402
import notes_scaffold  # noqa: E402
import pptx_to_fragment  # noqa: E402
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
    """The text a browser ends up with inside the FIRST `<tag>` element in `document`.

    The tag strip is valid only because every input these tests feed in is known to contain no
    `<`: a browser reads `<b>` inside `<title>` (RCDATA) as literal TEXT, not markup, so a helper
    that deletes `<...>` would silently swallow an under-escaped `<` there. `<` escaping is
    pinned directly instead (`test_both_escape_everything_html_escape_does`), and the assertion
    below refuses an input that would make this helper lie.
    """
    doc = _preprocess(document)
    match = re.search(r"(?is)<%s\b[^>]*>(.*?)</%s\s*>" % (tag, tag), doc)
    if match is None:
        raise AssertionError("no <%s> element in %r" % (tag, document[:400]))
    inner = match.group(1)
    stripped = re.sub(r"(?s)<[^>]*>", "", inner)
    if "<" in inner:
        # In RCDATA a `<` is TEXT, and in the DATA state these fragments are known to contain
        # none - either way a strip here would DELETE an under-escaped `<` and let the caller's
        # equality assertion pass on markup a browser really built.
        raise AssertionError(
            "<%s> contains a `<`: this helper cannot strip tags without lying about what a "
            "browser read" % tag)
    return _browser_attrs.unescape_text(stripped)


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

    def test_the_fold_runs_before_the_escape_and_the_cr_rule_runs_after(self):
        # Both orderings matter, and each is asserted with an input that DISCRIMINATES. The fold
        # must run BEFORE `html.escape`, so its U+FFFD lands beside an escaped neighbour rather
        # than being escaped itself; the CR rule must run AFTER, because `&#13;` carries an `&`
        # of its own that a later escape would turn into `&amp;#13;`.
        for escape in (_browser_attrs.escape_attr_value, _browser_attrs.escape_text):
            self.assertEqual(escape("\x00&"), "\ufffd&amp;")
            self.assertEqual(escape("\ud800<"), "\ufffd&lt;")
            self.assertEqual(escape("&\r"), "&amp;&#13;")

    def test_a_text_run_survives_a_code_point_sweep(self):
        # The totality claim covers BOTH escapes, and text decodes in a different tokenizer
        # state from an attribute value, so sweep it separately rather than by analogy.
        for start in range(0, 0x110000, 977):
            raw = "x%sy" % chr(start)
            written = "<p>%s</p>" % _browser_attrs.escape_text(raw)
            expected = raw
            if start == 0 or 0xd800 <= start <= 0xdfff:
                expected = "x\ufffdy"
            self.assertEqual(_text_a_browser_reads(written, "p"), expected,
                             "text run differs for U+%04X" % start)

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

    def test_a_checklist_label_keeps_its_cr_and_an_item_label_is_written_as_text(self):
        out = checklist_scaffold.scaffold("Ship it\n", "release", CR_LABEL, "list")
        self.assertEqual(_attr_a_browser_reads(out, "data-cmh-checklist-label"), CR_LABEL)
        table = checklist_scaffold.scaffold("Ship it\n", "release", CR_LABEL, "table")
        self.assertEqual(_attr_a_browser_reads(table, "data-cmh-checklist-label"), CR_LABEL)
        # An ITEM label cannot carry a CR - `parse_outline` splits the outline into lines - so
        # what distinguishes the TEXT escape there is that it leaves a quote alone where the
        # attribute escape would spell it `&quot;`. Pin both shapes: these are the two lines the
        # change actually touched, and a reversion to the attribute rule fails here.
        quoted = 'He said "go"'
        as_list = checklist_scaffold.scaffold(quoted + "\n", "release", "L", "list")
        self.assertEqual(_text_a_browser_reads(as_list, "li"), quoted)
        self.assertIn(">" + quoted + "<", as_list)
        as_table = checklist_scaffold.scaffold(quoted + "\n", "release", "L", "table")
        # The SECOND `<td>` is the label cell; the first is the always-empty checkbox cell, so
        # reading the first would assert nothing.
        label_cell = re.search(r"(?s)<td[^>]*>.*?</td>\s*(<td[^>]*>.*?</td>)", as_table)
        self.assertIsNotNone(label_cell, as_table)
        self.assertEqual(_text_a_browser_reads(label_cell.group(1), "td"), quoted)
        self.assertIn(">" + quoted + "<", as_table)

    def test_a_notes_label_and_seed_text_keep_their_cr(self):
        out = notes_scaffold.scaffold("risk", CR_LABEL, CR_LABEL)
        self.assertEqual(_attr_a_browser_reads(out, "data-cmh-note-label"), CR_LABEL)
        # The SOURCE keeps the CR. The note WIDGET is a different matter and deliberately not
        # asserted here: a `<textarea>` value is normalized to LF by HTML itself, and
        # `assets/js/37-notes.js` normalizes to LF to match, so the note's runtime text model is
        # LF-only by design. Writing `&#13;` is still the correct WRITE (a literal CR would not
        # even survive the file), and `notes_apply.py` now uses the same escape, so cementing a
        # note no longer rewrites the seed.
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

    def test_the_language_class_reduction_strips_a_cr_before_any_escape_sees_it(self):
        # Deliberately NOT a routing test: `_class_language` reduces the value to
        # [A-Za-z0-9_+.-] first, so the shared escape and `html.escape` are byte-identical here
        # and no input can tell them apart. `highlight_block` is on the shared rule for
        # uniformity; what is testable, and what this pins, is the reduction that makes the
        # routing unobservable.
        block = highlight_code.highlight_block("py\rthon", "x = 1")
        self.assertEqual(_attr_a_browser_reads(block, "class"), "language-py-thon")
        self.assertNotIn("\r", block)


    def test_cementing_a_note_does_not_rewrite_the_seed_the_scaffold_wrote(self):
        # `notes_apply` builds a TEXT run from a JSON field - the issue's own definition of a
        # generator. On `html.escape` it wrote a literal CR, which its own read then folds to
        # LF, so the comparison reported a change on EVERY run and the authored CR was lost.
        import pathlib
        import tempfile
        seed = "a\rb"
        fragment = notes_scaffold.scaffold("risk", "L", seed)
        document = "<!DOCTYPE html><html><body>%s</body></html>" % fragment
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "note.html")
            with io.open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(document)
            before = pathlib.Path(path).read_bytes()
            # A CONTROL first: the tool really does act, so a later 0 means "nothing to do"
            # rather than "this implementation never changes anything".
            self.assertEqual(notes_apply.apply_notes(path, {"risk": "different"},
                                                     warn=lambda _m: None), 1)
            self.assertEqual(notes_apply.apply_notes(path, {"risk": seed},
                                                     warn=lambda _m: None), 1)
            self.assertEqual(pathlib.Path(path).read_bytes(), before,
                             "cementing the scaffold's own seed did not restore it byte for byte")
            # Now the real pin: re-cementing the value already in the file is a no-op, twice.
            for _ in range(2):
                self.assertEqual(notes_apply.apply_notes(path, {"risk": seed},
                                                         warn=lambda _m: None), 0)
                self.assertEqual(pathlib.Path(path).read_bytes(), before)
            with io.open(path, encoding="utf-8", newline="") as fh:
                self.assertEqual(_text_a_browser_reads(fh.read(), "div"), seed)


class KqlAndDeckGeneratorTests(unittest.TestCase):
    """The two generators the round-1 panel found still on `html.escape`."""

    def test_a_kql_caption_title_keeps_its_cr(self):
        # `title` is `argv[3]` - a CLI-argument value written as the caption button's TEXT. On
        # `html.escape` the CR came out literal, so a browser read a value the author never
        # named, while the `cluster` beside it (an ATTRIBUTE) already kept its own characters.
        block = kql_highlight.render_block("c.kusto.windows.net", "db", CR_LABEL,
                                           "MyTable | take 1")
        self.assertEqual(_text_a_browser_reads(block, "button"), CR_LABEL)
        self.assertEqual(_attr_a_browser_reads(block, "data-cmh-copy"), "c.kusto.windows.net")

    def test_a_deck_slide_built_from_json_keeps_a_cr_in_its_title_and_text(self):
        fragment = pptx_to_fragment.slides_to_fragment([
            {"title": CR_LABEL,
             "content": [{"type": "text", "content": "body\rtext"}]},
        ])
        self.assertEqual(_text_a_browser_reads(fragment, "h2"), CR_LABEL)
        self.assertEqual(_text_a_browser_reads(fragment, "p"), "body\rtext")

    def test_a_session_id_stamp_keeps_its_cr(self):
        # `doc_stamp.set_meta` hand-rolled its own `&`/`"`/`<`/`>` escape - a third private copy
        # of the rule - so a `--session-id` carrying a CR was stamped literally and folded to LF.
        stamped = doc_stamp.set_meta("<html><head></head><body></body></html>",
                                     "commentable-html-session-id", "sess\rion")
        self.assertEqual(_attr_a_browser_reads(stamped, "content"), "sess\rion")
        # The private copy's own job must survive: a quote still cannot break the tag.
        quoted = doc_stamp.set_meta("<html><head></head><body></body></html>",
                                    "commentable-html-session-id", 'a"b<c&d')
        self.assertEqual(_attr_a_browser_reads(quoted, "content"), 'a"b<c&d')

    def test_a_deck_image_path_uses_the_attribute_escape_not_the_text_one(self):
        # `esc` is now the TEXT rule, which leaves a `"` alone - in `src="..."` that would end
        # the value and inject an attribute, so the image path must not go through it. Exercise
        # the real generator, not the two helpers: asserting on `esc` vs `escape_attr_value`
        # alone would still pass if `slides_to_fragment` reverted to `esc(vetted)`.
        fragment = pptx_to_fragment.slides_to_fragment([
            {"title": "T", "images": [{"path": 'a"onerror="alert(1)/x.png'}]},
        ])
        self.assertIn('src="a&quot;onerror=&quot;alert(1)/x.png"', fragment)
        self.assertEqual(_attr_a_browser_reads(fragment, "src"),
                         'a"onerror="alert(1)/x.png')
        self.assertNotIn("onerror=\"alert", _preprocess(fragment).replace("&quot;", ""))


class LabelNormalizationTests(unittest.TestCase):
    """Where a destination deliberately differs, and why that is not escape drift."""

    def test_the_lede_header_is_the_stripped_label_by_design(self):
        # `ensure_doc_title` strips the label before writing the heading, so a leading or
        # trailing CR reaches the `<h1>` as nothing while `data-doc-label` and `<title>` keep it.
        # That is a DISPLAY normalization of a heading, not the escape disagreeing: all three
        # destinations apply the same rule to the characters they are given.
        with open(TEMPLATE, encoding="utf-8") as fh:
            template = fh.read()
        padded = "\rQ3 review\r"
        content = new_document.ensure_doc_title("<section><h2 id=\"a\">Hi</h2><p>x</p></section>",
                                                padded)
        out = new_document.make_document(template, content, "cr-strip-doc", padded)
        self.assertEqual(_attr_a_browser_reads(out, "data-doc-label"), padded)
        self.assertEqual(_text_a_browser_reads(out, "title"), padded)
        self.assertEqual(_text_a_browser_reads(out, "h1"), "Q3 review")


def _brand_profile_module():
    import _brand_profile
    return _brand_profile


if __name__ == "__main__":
    unittest.main()
