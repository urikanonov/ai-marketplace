#!/usr/bin/env python3
"""Author-time Markdown syntax highlighting (CMH-HL-07).

Markdown is structural and line-oriented rather than keyword-based, so highlight_code.py gives it a
dedicated tokenizer instead of the shared comment/string/keyword one. These tests pin the token
mapping (headings/bold -> kw, emphasis/strikethrough/HTML comments -> com, code and link
destinations -> str, link text and labels -> fn, ordered-list numbers -> num, structural
punctuation -> op) and the invariants every highlighter here must keep: the rendered text is the
original code character for character, and every character is escaped exactly once.
"""
import html
import os
import re
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402  shared pkg/dev split path constants
sys.path.insert(0, _paths.TOOLS)
import highlight_code as H  # noqa: E402

SPAN_RE = re.compile(r'<span class="cmh-code-([a-z]+)">(.*?)</span>', re.S)


def render(code, language="markdown"):
    return H.highlight_code(language, code)


def spans(code, language="markdown"):
    """[(class, text)] for every token span, in order, with the text unescaped."""
    return [(cls, html.unescape(body)) for cls, body in SPAN_RE.findall(render(code, language))]


def by_class(code, language="markdown"):
    """{class: [texts]} for every token span."""
    out = {}
    for cls, text in spans(code, language):
        out.setdefault(cls, []).append(text)
    return out


def text_of(rendered):
    """The text a browser would show for a rendered fragment."""
    return html.unescape(re.sub(r"<[^>]+>", "", rendered))


class MarkdownLanguageRegistrationTests(unittest.TestCase):
    def test_markdown_is_a_configured_language(self):
        self.assertIn("markdown", H.LANGUAGE_CONFIGS)
        self.assertIn("markdown", H.supported_languages())

    def test_md_aliases_resolve_to_markdown(self):
        for alias in ("md", "mdown", "MD", "Markdown"):
            with self.subTest(alias=alias):
                self.assertEqual(
                    render("# Title", alias),
                    render("# Title", "markdown"),
                    "%r must highlight as markdown" % alias)


class MarkdownBlockTokenTests(unittest.TestCase):
    def test_atx_heading_is_a_keyword_token(self):
        self.assertEqual(spans("## Findings"), [("kw", "## Findings")])

    def test_a_hash_without_a_space_is_not_a_heading(self):
        self.assertNotIn("kw", by_class("#hashtag not a heading"))

    def test_setext_underline_is_a_keyword_token(self):
        self.assertEqual(by_class("Title\n=====")["kw"], ["====="])

    def test_a_dash_underline_under_a_paragraph_is_a_setext_heading(self):
        self.assertEqual(by_class("Title\n-----")["kw"], ["-----"])
        # With no paragraph above it, the same run is a thematic break.
        self.assertEqual(spans("intro\n\n-----"), [("op", "-----")])
        # A list item is not a paragraph, so a rule below one stays a break.
        self.assertEqual(by_class("- item\n-----")["op"], ["-", "-----"])

    def test_fence_delimiters_and_an_unlabeled_opaque_body(self):
        code = "```\nx = 1\n```\nafter"
        classes = by_class(code)
        self.assertIn("```", classes["op"])
        self.assertEqual(classes["str"], ["x = 1"])
        # With no info string the body is opaque: no inline markdown is tokenized inside a fence.
        self.assertEqual(spans("```\n**not bold**\n```")[1], ("str", "**not bold**"))

    def test_a_fenced_body_is_tokenized_in_its_info_string_language(self):
        code = '```python\ndef area(r):\n    return "hi"  # note\n```'
        classes = by_class(code)
        self.assertEqual(classes["kw"][0], "python")          # the info string itself
        self.assertIn("def", classes["kw"])                   # tokenized as Python, not opaque
        self.assertIn("return", classes["kw"])
        self.assertIn('"hi"', classes["str"])
        self.assertIn("# note", classes["com"])
        self.assertNotIn('def area(r):', classes.get("str", []))
        self.assertEqual(text_of(render(code)), code)

    def test_an_info_string_alias_resolves_like_the_full_label(self):
        for info in ("js", "mjs", "javascript"):
            with self.subTest(info=info):
                classes = by_class("```%s\nconst a = 1; // n\n```" % info)
                self.assertIn("const", classes["kw"])
                self.assertIn("// n", classes["com"])

    def test_only_the_first_word_of_the_info_string_selects_the_language(self):
        classes = by_class('```python title="x.py"\ndef f(): pass\n```')
        self.assertIn("def", classes["kw"])

    def test_an_unknown_info_string_keeps_an_opaque_body(self):
        for info in ("kusto", "text", "brainfuck"):
            with self.subTest(info=info):
                classes = by_class("```%s\nlet x = 1 // not a comment\n```" % info)
                self.assertEqual(classes["str"], ["let x = 1 // not a comment"])

    def test_a_nested_markdown_fence_is_highlighted_as_markdown_without_recursing(self):
        code = "````markdown\n# Inner heading\n```python\ndef f(): pass\n```\n````"
        classes = by_class(code)
        self.assertIn("# Inner heading", classes["kw"])
        self.assertIn("```", classes["op"])
        self.assertEqual(text_of(render(code)), code)

    def test_a_multiline_construct_in_a_nested_body_is_not_cut_at_the_line_break(self):
        # The body is tokenized as ONE unit, so a construct that spans lines reads the same as it
        # would in a standalone block of that language.
        js = by_class("```js\n/* open\nstill comment\n*/\nlet a = 1;\n```")
        self.assertIn("/* open\nstill comment\n*/", js["com"])
        py = by_class('```python\ns = """one\ntwo"""\n```')
        self.assertIn('"""one\ntwo"""', py["str"])

    def test_markdown_nesting_is_depth_bounded(self):
        # Markdown is the only language whose tokenizer can re-enter itself, so a hostile document
        # (thousands of ```markdown openers) must not recurse without bound. Past the depth cap the
        # body stays opaque; the text still round-trips exactly either way.
        hostile = "```markdown\n" * 5000
        rendered = render(hostile)
        self.assertEqual(text_of(rendered), hostile)

        def nest(levels):
            """A ```markdown fence nested `levels` deep around a `# deep` heading."""
            code = "# deep"
            for level in range(levels):
                fence = "`" * (3 + level)
                code = "%smarkdown\n%s\n%s" % (fence, code, fence)
            return code

        # At the cap the innermost heading is still tokenized as markdown; one level deeper the body
        # is left as a single opaque run instead of recursing again.
        self.assertIn("# deep", by_class(nest(H._MD_MAX_NESTING))["kw"])
        deeper = by_class(nest(H._MD_MAX_NESTING + 1))
        self.assertNotIn("# deep", deeper.get("kw", []))
        self.assertTrue(any("# deep" in run for run in deeper["str"]))

    def test_a_fenced_body_line_that_looks_like_markdown_is_not_markdown(self):
        classes = by_class("```python\n# heading? no, a python comment\n```")
        self.assertIn("# heading? no, a python comment", classes["com"])
        self.assertNotIn("# heading? no, a python comment", classes.get("kw", []))

    def test_a_tilde_fence_is_not_closed_by_a_backtick_fence(self):
        classes = by_class("~~~\n```\nstill code\n~~~")
        self.assertIn("```", classes["str"])
        self.assertIn("still code", classes["str"])

    def test_thematic_break_is_punctuation(self):
        self.assertEqual(spans("---"), [("op", "---")])
        self.assertEqual(spans("* * *"), [("op", "* * *")])

    def test_table_pipes_and_delimiter_row(self):
        classes = by_class("| a | b |\n| --- | ---: |\n| 1 | 2 |")
        self.assertEqual(classes["op"].count("|"), 6)
        self.assertIn("| --- | ---: |", classes["op"])

    def test_a_lone_pipe_in_prose_is_not_a_table_pipe(self):
        self.assertEqual(spans("use a | pipe here"), [])

    def test_blockquote_marker_is_punctuation_and_its_text_still_highlights(self):
        self.assertEqual(spans("> quoted `code`"), [("op", ">"), ("str", "`code`")])

    def test_bullet_marker_is_punctuation(self):
        self.assertEqual(spans("  - item")[0], ("op", "-"))

    def test_ordered_list_number_is_a_number_token(self):
        self.assertEqual(spans("3. third")[:2], [("num", "3"), ("op", ".")])

    def test_task_list_checkbox_is_punctuation(self):
        classes = by_class("- [x] done")
        self.assertEqual(classes["op"], ["-", "[x]"])

    def test_reference_definition_label_and_destination(self):
        classes = by_class('[spec]: https://example.com/spec "Spec"')
        self.assertEqual(classes["fn"], ["spec"])
        self.assertIn("https://example.com/spec", classes["str"])

    def test_a_multiline_html_comment_stays_a_comment_on_every_line(self):
        code = "before\n<!-- hidden\n# not a heading\nstill hidden -->\nafter **bold**"
        classes = by_class(code)
        self.assertEqual(classes["com"], ["<!-- hidden", "# not a heading", "still hidden -->"])
        self.assertEqual(classes["kw"], ["**bold**"])
        self.assertEqual(text_of(render(code)), code)

    def test_the_html_tolerated_comment_terminator_also_closes(self):
        # HTML accepts `--!>` as well as `-->`; both end the comment on one line and across lines.
        self.assertEqual(spans("text <!-- hidden --!> more"), [("com", "<!-- hidden --!>")])
        classes = by_class("<!-- open\nstill --!>\n# heading")
        self.assertEqual(classes["com"], ["<!-- open", "still --!>"])
        self.assertEqual(classes["kw"], ["# heading"])

    def test_an_html_comment_inside_a_code_span_does_not_open_a_comment(self):
        code = "a `<!-- x` b\n# real heading"
        classes = by_class(code)
        self.assertEqual(classes["str"], ["`<!-- x`"])
        self.assertEqual(classes["kw"], ["# real heading"])

    def test_an_html_comment_inside_a_fenced_block_does_not_open_a_comment(self):
        code = "```\n<!-- x\n```\n# real heading"
        self.assertEqual(by_class(code)["kw"], ["# real heading"])


class MarkdownInlineTokenTests(unittest.TestCase):
    def test_inline_code_span_is_a_string(self):
        self.assertEqual(spans("run `build.py --check` now"), [("str", "`build.py --check`")])

    def test_double_backtick_code_span(self):
        self.assertEqual(spans("``a ` b``"), [("str", "``a ` b``")])

    def test_triple_backtick_inline_code_span(self):
        self.assertEqual(spans("use ```a``b``` here"), [("str", "```a``b```")])

    def test_bold_is_a_keyword_token(self):
        self.assertEqual(spans("a **strong** b"), [("kw", "**strong**")])
        self.assertEqual(spans("a __strong__ b"), [("kw", "__strong__")])

    def test_italic_is_a_comment_token(self):
        self.assertEqual(spans("a *soft* b"), [("com", "*soft*")])
        self.assertEqual(spans("a _soft_ b"), [("com", "_soft_")])

    def test_bold_italic_is_a_keyword_token(self):
        self.assertEqual(spans("a ***both*** b"), [("kw", "***both***")])

    def test_strikethrough_is_a_comment_token(self):
        self.assertEqual(spans("a ~~gone~~ b"), [("com", "~~gone~~")])

    def test_link_text_and_destination(self):
        self.assertEqual(
            spans("see [the spec](https://example.com/a_b) now"),
            [("op", "["), ("fn", "the spec"), ("op", "]("), ("str", "https://example.com/a_b"), ("op", ")")])

    def test_image_keeps_its_bang_with_the_bracket(self):
        self.assertEqual(spans("![alt](img.png)")[0], ("op", "!["))

    def test_reference_link_label_is_a_function_token(self):
        classes = by_class("see [the spec][spec] now")
        self.assertEqual(classes["fn"], ["the spec", "spec"])

    def test_footnote_reference(self):
        self.assertEqual(spans("a claim[^1] here"), [("fn", "[^1]")])

    def test_autolink_is_a_string(self):
        self.assertEqual(spans("mail <a@b.com> or <https://x.dev/p>"),
                         [("str", "<a@b.com>"), ("str", "<https://x.dev/p>")])

    def test_html_comment_is_a_comment_token(self):
        self.assertEqual(spans("text <!-- hidden --> more"), [("com", "<!-- hidden -->")])

    def test_inline_html_tag_is_punctuation(self):
        self.assertEqual(spans("hard<br>break"), [("op", "<br>")])


class MarkdownFalsePositiveTests(unittest.TestCase):
    def test_no_emphasis_inside_a_code_span(self):
        self.assertEqual(spans("`a_b_c and *not* bold`"), [("str", "`a_b_c and *not* bold`")])

    def test_intraword_underscores_are_not_emphasis(self):
        self.assertEqual(spans("call some_long_name and MAX_BUF_SIZE"), [])

    def test_a_backslash_escaped_marker_is_not_emphasis(self):
        self.assertEqual(spans(r"literal \*stars\* stay"), [])

    def test_an_escaped_closing_delimiter_does_not_close_emphasis(self):
        # The first `*` of the apparent closer is escaped, so there is no valid closer.
        for line in (r"a **bold\** b", r"a *soft\* b", r"a __bold\__ b", r"a ~~gone\~~ b",
                     r"a ***both\*** b", r"a **\** b"):
            with self.subTest(line=line):
                self.assertEqual(spans(line), [])

    def test_an_escaped_backslash_before_a_closer_still_closes(self):
        # Conservative: a literal backslash immediately before the closer is not highlighted either,
        # which keeps the scan escape-aware without a lookbehind. Pinned so the choice is deliberate.
        self.assertEqual(spans(r"a **bold\\** b"), [])

    def test_an_unterminated_marker_is_left_plain(self):
        for line in ("an unpaired ` backtick", "an unpaired * star", "an unpaired _ score"):
            with self.subTest(line=line):
                self.assertEqual(spans(line), [])

    def test_emphasis_does_not_run_across_lines(self):
        self.assertEqual(spans("open *here\nand close* there"), [])

    def test_a_space_padded_closer_does_not_close_emphasis(self):
        # CommonMark right-flanking: the delimiter must hug the text on both sides.
        for line in ("a **bold ** b", "a *soft * b", "a ~~gone ~~ b", "a __bold __ b"):
            with self.subTest(line=line):
                self.assertEqual(spans(line), [])


class MarkdownFidelityTests(unittest.TestCase):
    SOURCE = (
        "---\n"
        "# Title `code` <tag>\n\n"
        "> a *quoted* & <escaped> line\n\n"
        "1. first **bold** item\n"
        "- [ ] todo ~~old~~\n\n"
        "| a | b |\n| --- | --- |\n| 1 | 2 |\n\n"
        "```js\nconst a = 1 < 2 && \"x\";\n```\n\n"
        "See [docs](https://x.dev/a?b=1&c=2) <!-- note -->\n"
        "[docs]: https://x.dev/a\n")

    def test_rendered_text_is_the_original_source(self):
        self.assertEqual(text_of(render(self.SOURCE)), self.SOURCE)

    def test_every_character_is_escaped_exactly_once(self):
        rendered = render(self.SOURCE)
        self.assertNotIn("&amp;amp;", rendered)
        self.assertNotIn("&amp;lt;", rendered)
        self.assertIn("&amp;", rendered)
        self.assertIn("&lt;", rendered)
        self.assertNotIn("<tag>", rendered)
        self.assertNotIn("<escaped>", rendered)

    def test_crlf_is_normalized_like_every_other_language(self):
        self.assertEqual(render("# a\r\n- b\r\n"), render("# a\n- b\n"))

    def test_empty_and_blank_input_round_trip(self):
        self.assertEqual(render(""), "")
        self.assertEqual(text_of(render("\n\n\n")), "\n\n\n")

    def test_no_empty_token_spans_are_emitted(self):
        self.assertNotIn('"></span>', render(self.SOURCE))


class MarkdownPerformanceTests(unittest.TestCase):
    def test_adversarial_input_does_not_blow_up_quadratically(self):
        # Every failing scan in the inline tokenizer is length-capped, so a long run of unmatched
        # bracket / tag openers cannot be re-scanned to end of line from every position (which took
        # tens of seconds before the caps and would freeze the browser on the runtime path).
        for hostile in ("[" * 30000, "<" * 30000, "![" * 15000, "`" * 30000,
                        "**x " * 8000, "~~x " * 8000, "__x " * 8000, "*x " * 10000,
                        "|-" + "|\t" * 4000 + "x", "|" * 30000, "-" * 30000 + "|x",
                        "```markdown\n" * 5000, "```python\n" + "x = 1  # c\n" * 8000 + "```"):
            with self.subTest(head=hostile[:2]):
                start = time.time()
                rendered = render(hostile)
                elapsed = time.time() - start
                self.assertEqual(text_of(rendered), hostile)
                self.assertLess(elapsed, 5.0, "%r took %.1fs" % (hostile[:2], elapsed))


class MarkdownRuntimeCoverageTests(unittest.TestCase):
    def test_the_runtime_maps_every_markdown_file_extension(self):
        # CMH-HL-08: a diff of a .md file infers the markdown language from the file label, so a
        # Markdown diff is highlighted line by line instead of rendering monochrome.
        with open(os.path.join(_paths.ASSETS, "js", "26-highlight.js"), "r", encoding="utf-8") as fh:
            src = fh.read()
        ext = re.search(r"const _EXT_LANG\s*=\s*\{(.*?)\};", src, re.S)
        self.assertTrue(ext, "could not locate the _EXT_LANG object literal")
        for alias in ("md", "markdown", "mdown", "mkd"):
            with self.subTest(alias=alias):
                self.assertRegex(ext.group(1), r'\b%s:\s*"markdown"' % alias)

    def test_the_runtime_markdown_tokenizer_normalizes_line_endings(self):
        # The author-time tool normalizes CRLF before splitting lines; the runtime must too, or a
        # stray \r hides a fence delimiter from _MD_FENCE_RE and the nested-body behavior silently
        # disappears. The DOM already hands the runtime LF, so this is not reachable from a browser
        # test - the source-level guard is the coverage.
        with open(os.path.join(_paths.ASSETS, "js", "26-highlight.js"), "r", encoding="utf-8") as fh:
            src = fh.read()
        body = re.search(r"function cmhHighlightMarkdown\([^)]*\)\s*\{(.*?)\n\}", src, re.S)
        self.assertTrue(body, "could not locate cmhHighlightMarkdown()")
        self.assertRegex(body.group(1), r"\.replace\(/\\r\\n\?/g,\s*\"\\n\"\)")

    def test_the_runtime_uses_the_same_markdown_nesting_depth_cap(self):
        # The spec promises a nested ```markdown body recurses through the SAME bound on both paths.
        # Nothing else pins the two constants together, and a silent divergence would leave one path
        # recursing deeper than the other on the same document.
        with open(os.path.join(_paths.ASSETS, "js", "26-highlight.js"), "r", encoding="utf-8") as fh:
            src = fh.read()
        self.assertRegex(src, r"const _MD_MAX_NESTING\s*=\s*%d;" % H._MD_MAX_NESTING)


if __name__ == "__main__":
    unittest.main()
