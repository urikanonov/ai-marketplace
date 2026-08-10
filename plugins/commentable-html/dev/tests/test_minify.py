#!/usr/bin/env python3
"""The build-time comment strip and the per-component size budget (#1250, CMH-BUILD-26/27).

The strip is the one build step that rewrites every byte of the shipped runtime, so these tests
pin the two properties that make it safe to run unattended:

- it only ever DELETES comments and layout whitespace, never a byte of a string, template literal
  or regex literal, and never a line terminator that automatic semicolon insertion depends on;
- when its scanner desyncs it FAILS THE BUILD rather than shipping a rewritten program.

The remaining coverage is the whole browser suite: every Playwright spec runs against the built
stage, which is the stripped layer.
"""
import json
import os
import re
import shutil
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402
sys.path.insert(0, _paths.DEV_TOOLS)
import build  # noqa: E402

ASSETS = _paths.ASSETS
DIST = os.path.join(_paths.DEV, "skill", "dist")


def _read(path):
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def _concat(ext):
    d = os.path.join(ASSETS, ext)
    return "".join(_read(os.path.join(d, n)) for n in sorted(os.listdir(d))
                   if n.endswith("." + ext))


class JsCommentStripTests(unittest.TestCase):
    def test_line_and_block_comments_go_and_the_code_stays(self):
        out = build.minify_js("// leading note\nconst a = 1;\n/* block\n   note */\nconst b = 2;\n")
        self.assertNotIn("note", out)
        self.assertIn("const a=1;", out)
        self.assertIn("const b=2;", out)

    def test_indentation_and_blank_lines_go(self):
        out = build.minify_js("function f() {\n\n      return 1;\n\n}\n")
        self.assertEqual(out, "function f(){\nreturn 1;\n}")

    def test_a_multi_line_block_comment_leaves_a_line_terminator_behind(self):
        # ASI: `return` followed by a line terminator returns undefined. A block comment that spans
        # lines IS a line terminator to the spec, so collapsing it to a space would silently change
        # this program's meaning.
        out = build.minify_js("function f() {\n  return/* a\n b */1;\n}\n")
        self.assertIn("return\n1;", out)

    def test_an_inline_block_comment_leaves_a_separator_only_where_one_is_needed(self):
        self.assertEqual(build.minify_js("const/* x */a = 1;"), "const a=1;")
        self.assertEqual(build.minify_js("f(a/* x */, b);"), "f(a,b);")

    def test_a_newline_is_never_traded_for_a_space(self):
        out = build.minify_js("let a = 1\nlet b = 2\n")
        self.assertEqual(out, "let a=1\nlet b=2")

    def test_comment_openers_inside_strings_are_data(self):
        for src in ('const s = "// not a comment";',
                    "const s = '/* not a comment */';",
                    'const s = "a\\" // still a string";'):
            self.assertEqual(build.minify_js(src), src.replace(" = ", "= "), src)

    def test_a_template_literal_keeps_its_newlines_and_indentation(self):
        src = "const t = `line one\n    indented\n`;\n"
        self.assertEqual(build.minify_js(src), "const t=`line one\n    indented\n`;")

    def test_a_template_expression_is_scanned_as_code(self):
        out = build.minify_js("const t = `a${ /* drop me */ b }c`;")
        self.assertEqual(out, "const t=`a${b}c`;")

    def test_nested_template_literals_round_trip(self):
        src = "const t = `a${`b${ c /* x */ }d`}e`;"
        self.assertEqual(build.minify_js(src), "const t=`a${`b${c}d`}e`;")

    def test_a_regex_literal_containing_comment_openers_survives(self):
        src = 'const re = /\\/\\/|\\/\\*/g;\nconst s = "x";\n'
        out = build.minify_js(src)
        self.assertIn("/\\/\\/|\\/\\*/g", out)
        self.assertIn('const s= "x";', out)

    def test_a_regex_containing_a_quote_does_not_open_a_string(self):
        out = build.minify_js("const re = /['\"]/g; // note\nconst n = 1;")
        self.assertNotIn("note", out)
        self.assertIn("const n=1;", out)

    def test_division_is_not_read_as_a_regex(self):
        out = build.minify_js("const q = a / b; // note\nconst r = c / d;\n")
        self.assertNotIn("note", out)
        self.assertEqual(out, "const q=a/b;\nconst r=c/d;")

    def test_division_after_an_increment_is_not_read_as_a_regex(self):
        out = build.minify_js("let i = 0;\nconst q = i++ / 2; // note\nconst r = 3;\n")
        self.assertNotIn("note", out)
        self.assertIn("i++/2;", out)

    def test_a_regex_after_return_is_a_regex(self):
        out = build.minify_js("function f(s) { return /a\\/b/.test(s); /* note */ }")
        self.assertNotIn("note", out)
        self.assertIn("return/a\\/b/.test(s);", out)

    def test_a_division_after_a_string_or_template_is_not_a_regex(self):
        # A string or a template literal ENDS a value, so the `/` after one divides. Reading it as
        # a regex swallowed the following line comment into "code" (so it shipped), and on
        # `const r = "5" / 2; // it's ok` the apostrophe opened a string and failed the build on
        # perfectly legal source. All three quoting forms, because each is a separate list entry.
        out = build.minify_js("const n = `x` / y; // note\nconst m = 1;\n")
        self.assertNotIn("note", out)
        self.assertIn("const n=`x`/y;", out)
        out = build.minify_js("const r = \"5\" / 2; // it's ok\nlet z = 1;\n")
        self.assertNotIn("it's ok", out)
        self.assertIn("\"5\"/2;", out)
        self.assertIn("let z=1;", out)
        out = build.minify_js("const r = 'hello' / 2; // note\nlet z = 1;\n")
        self.assertNotIn("note", out)
        self.assertIn("'hello'/2;", out)
        self.assertIn("let z=1;", out)

    def test_an_identifier_token_does_not_fuse_across_whitespace(self):
        # `word` is the token ending at the previous significant character. Accumulating across a
        # whitespace or comment run made `x = y\nreturn ...` look like the identifier `yreturn`,
        # which is not in the regex-keyword list, so the regex after it was read as division.
        out = build.minify_js("x = y\nreturn /\\d+ \\w+/.test(z);\n")
        self.assertIn("/\\d+ \\w+/", out)
        out = build.minify_js("let ok = 1;\ntypeof /a b/;\n")
        self.assertIn("/a b/", out)


class AmbiguousSlashTests(unittest.TestCase):
    """`)` and `}` are the two closers that can precede either a regex or a division. The scanner
    decides from what OPENED them, so a regex is only ever scanned where one can legally be."""

    def test_a_regex_after_a_control_paren_keeps_its_interior_whitespace(self):
        for src in (r"if (ok) /\d+ \w+/.test(s);",
                    "if (ok) /[a-z] [0-9]/.test(s);",
                    "while (ok) / +/.exec(s);",
                    "for (;;) /a  b/.test(s);"):
            out = build.minify_js(src)
            self.assertIn(src[src.index("/"):src.rindex("/") + 1], out, src)

    def test_a_regex_after_a_block_brace_keeps_its_interior_whitespace(self):
        out = build.minify_js("function f(){}\n/\\d+ \\w+/.test(s);\n")
        self.assertIn("/\\d+ \\w+/", out)

    def test_a_division_after_a_grouping_paren_is_a_division(self):
        # The case that made the previous "copy the ambiguous span verbatim" design unsound: the
        # candidate window ran through a comment, a string or a LATER regex and rewrote it.
        checks = (
            ("var x = (a + b) / c; // note\nvar y = 1;\n", ("var x=(a+b)/c;", "var y=1;"), "note"),
            ("var v = arr[0] / s.split(/,  /).length;\n", ("/,  /",), None),
            ("var v = f(a) / b.replace(/x  y/g, '');\n", ("/x  y/g",), None),
            ('var a = 8; var n = (a) / "/".length;\n', ('"/".length',), None),
            ("var x = (a) / b;\nvar t = 'keep   me';\n", ("'keep   me'",), None),
            ("const q = (a + b) / c / d;\n", ("(a+b)/c/d;",), None),
        )
        for src, present, absent in checks:
            out = build.minify_js(src)
            for text in present:
                self.assertIn(text, out, src)
            if absent:
                self.assertNotIn(absent, out, src)

    def test_a_division_never_swallows_a_comment_that_follows_it(self):
        # A swallowed `/*` opener shipped the comment body, and a comment body can carry markup
        # that ends the <script> element the layer is inlined in.
        out = build.minify_js(
            "function f(x, foo, bar) { return (x) / foo /*<" + "!--<script>*/ + bar; }")
        self.assertNotIn("script", out)
        self.assertIn("return(x)/foo+bar;", out)

    def test_a_commented_division_chain_after_every_closer_still_builds(self):
        for opener in ("(16)", "[16][0]", "({v: 16}).v"):
            src = "const c = 4, d = 2;\nconst out = %s/*a*/ / /*b*/c/*c*/ / /*d*/d;\n" % opener
            out = build.minify_js(src)
            self.assertNotIn("/*", out, src)
            self.assertIn("/c/d;", out, src)

    def test_a_keyword_used_as_a_property_name_divides(self):
        for src in ("var x = {return: 8};\nvar y = x.return / 2 / 2;\n",
                    "var o = {in: 4};\nvar y = o.in / 2 / 2;\n"):
            out = build.minify_js(src)
            self.assertIn("/2/2;", out, src)

    def test_a_regex_keyword_that_is_missing_would_fail_the_build_loudly(self):
        # `extends` and `default` open regex context too. When a keyword is missing from the list
        # the `/` reads as a division, a `/*` inside the regex body opens a phantom comment, and
        # the strip REFUSES rather than shipping the truncation - so this is a build-breaking
        # false positive, not a silent corruption. Pin the two that were missing.
        for src in ("class A extends /a[/*]b/.constructor {}\n",
                    "export default /a[/*]b/;\n"):
            out = build.minify_js(src)
            self.assertIn("/a[/*]b/", out, src)

    def test_a_comment_opener_inside_a_regex_is_not_eaten(self):
        out = build.minify_js(
            "if (ok) /a[/*]b/.test(s);\nconst keep = 1;\n/* drop me */\nconst last = 2;\n")
        self.assertIn("/a[/*]b/.test(s);", out)
        self.assertIn("const keep=1;", out)
        self.assertIn("const last=2;", out)
        self.assertNotIn("drop me", out)

    def test_a_line_comment_opener_inside_a_regex_is_not_eaten(self):
        out = build.minify_js("if (ok) /[//]x/.test(s);\nconst keep = 1;\n")
        self.assertIn("/[//]x/.test(s);", out)
        self.assertIn("const keep=1;", out)

    def test_the_separator_after_a_regex_is_never_dropped(self):
        # `/re/ instanceof X` closing up into `/re/instanceof` would read `instanceof` as flags.
        out = build.minify_js("var t = /re/ instanceof RegExp;\n")
        self.assertIn("/re/ instanceof", out)

    def test_a_numeric_literal_ending_in_a_dot_divides(self):
        # `const ratio = 1. / 2;` is legal: the value ends at the dot, so the `/` divides. Reading
        # it as a regex lets a later `/` or comment be segmented into the phantom literal.
        out = build.minify_js("const ratio = 1. / 2; // note\nconst r = 3;\n")
        self.assertNotIn("note", out)
        self.assertIn("const r=3;", out)

    def test_a_function_or_class_expression_body_divides(self):
        # `const f = function(){} / 2` is a value divided; `function f(){}` then a regex is a
        # declaration followed by a statement. The brace looks identical - the keyword's position
        # is what differs.
        for src in ("const f = function(){} / 2 / 3; // note\nconst r = 1;\n",
                    "const C = class X {} / 2 / 3; // note\nconst r = 1;\n"):
            out = build.minify_js(src)
            self.assertNotIn("note", out, src)
            self.assertIn("const r=1;", out, src)
        out = build.minify_js("function f(){}\n/a  b/.test(s);\n")
        self.assertIn("/a  b/", out)
        out = build.minify_js("class X {}\n/a  b/.test(s);\n")
        self.assertIn("/a  b/", out)

    def test_the_shipped_source_needs_no_grammar_guess(self):
        # `)` and `}` are the only two positions where the reading depends on parse context rather
        # than on the token itself. Pin that the real runtime never puts a regex there, so the
        # riskiest path is not load-bearing today and a partial that starts using it is a
        # deliberate, reviewable change rather than a silent one.
        segs, problems = build._minify_js_scan(_concat("js"))
        self.assertEqual(problems, [])
        self.assertTrue(any(kind == "rx" for kind, _t in segs), "no regex literals found at all")
        from_close = [t for kind, t in segs if kind == "rxc"]
        self.assertEqual(from_close, [],
                         "a shipped regex is now read out of a `)`/`}` context: %r" % from_close[:3])


class UnterminatedSourceTests(unittest.TestCase):
    """A construct the scan cannot close would silently truncate the shipped bytes."""

    def test_an_unterminated_block_comment_fails_the_build(self):
        with self.assertRaises(SystemExit):
            build.minify_js("const x = 1;\n/* never closed\n")
        with self.assertRaises(SystemExit):
            build.minify_css(".a { color: red; }\n/* never closed\n")

    def test_an_unterminated_string_fails_the_build(self):
        with self.assertRaises(SystemExit):
            build.minify_js('const s = "never closed;\n')

    def test_an_unterminated_template_literal_fails_the_build(self):
        with self.assertRaises(SystemExit):
            build.minify_js("const t = `never closed;\n")

    def test_an_unterminated_substitution_fails_the_build(self):
        # The scan ends in CODE mode here, not in template mode, so the open `${` is only visible
        # in the template stack. Without this the strip returned invalid output whenever node was
        # unavailable to catch it.
        with self.assertRaises(SystemExit):
            build.minify_js("const t = `a${b\n")
        with self.assertRaises(SystemExit):
            build.minify_js("const t = `a${ `b${ c\n")


class LineTerminatorTests(unittest.TestCase):
    """ASI and the extent of a `//` comment are decided by every ES line terminator, not by LF."""

    def test_a_non_lf_terminator_ends_a_line_comment(self):
        for eol in ("\r", "\u2028", "\u2029"):
            out = build.minify_js("let a = 1; // note" + eol + "let b = 2;")
            self.assertNotIn("note", out, repr(eol))
            self.assertIn("let b=2;", out, repr(eol))

    def test_a_block_comment_carrying_a_non_lf_terminator_leaves_a_newline(self):
        for eol in ("\r", "\u2028", "\u2029"):
            out = build.minify_js("function f() { return/*" + eol + "*/1; }")
            self.assertIn("return\n1;", out, repr(eol))


class JsSeparatorSafetyTests(unittest.TestCase):
    """Removing a space is only safe when the two characters cannot fuse into another token."""

    def test_identifiers_keep_their_separator(self):
        self.assertEqual(build.minify_js("const a = 1;"), "const a=1;")
        self.assertEqual(build.minify_js("typeof  x"), "typeof x")

    def test_a_number_keeps_its_space_before_a_member_access(self):
        self.assertEqual(build.minify_js("const s = 1 .toFixed(2);"), "const s=1 .toFixed(2);")

    def test_unary_plus_after_binary_plus_keeps_its_separator(self):
        self.assertEqual(build.minify_js("const n = a + +b;"), "const n=a+ +b;")
        self.assertEqual(build.minify_js("const n = a - -b;"), "const n=a- -b;")

    def test_a_division_before_a_regex_never_opens_a_comment(self):
        out = build.minify_js("const n = a / /b/.source.length;")
        self.assertNotIn("//", out)
        self.assertNotIn("/*", out)

    def test_the_strip_never_manufactures_a_markup_delimiter(self):
        # The layer is inlined inside a <script> element, so fusing `<` with `/` (or `<` with `!`,
        # or `-` with `>`) would close the element early and kill the runtime in every document.
        for src, forbidden in (("const b = a < /re/.source.length;", "</"),
                               ("const b = a < !c;", "<!"),
                               ("const b = a-- > c;", "-->")):
            self.assertNotIn(forbidden, build.minify_js(src), src)

    def test_the_strip_never_manufactures_an_html_attribute(self):
        # `el.title = "Close"` fused to `el.title="Close"` puts a literal `title="Close"` inside a
        # document's own script, where any regex scanning document text for that attribute matches
        # the runtime instead of the content. Keeping one byte between `=` and the quote costs
        # about 0.2% of the bundle and closes the whole class.
        for src in ('el.title = "Close";', "el.id = 'x';", 'node.width = "";'):
            out = build.minify_js(src)
            self.assertIsNone(re.search(r'[\w-]+=["\']', out),
                              "%r fused into attribute-shaped text: %r" % (src, out))

    def test_an_identifier_never_fuses_with_a_unicode_escape(self):
        # `let \u0061 = 1` fused to `let\u0061=1` is the single identifier `leta`.
        self.assertEqual(build.minify_js("let \\u0061 = 1;"), "let \\u0061=1;")


class LicenseCommentTests(unittest.TestCase):
    def test_legal_notices_are_kept(self):
        for src in ("/*! keep me */\nconst a = 1;\n",
                    "/* @license keep me */\nconst a = 1;\n",
                    "/* @preserve keep me */\nconst a = 1;\n"):
            self.assertIn("keep me", build.minify_js(src), src)

    def test_an_ordinary_block_comment_is_not_kept(self):
        self.assertNotIn("drop me", build.minify_js("/* drop me */\nconst a = 1;\n"))

    def test_the_lz_string_attribution_travels_with_the_shipped_bytes(self):
        # MIT requires the notice to accompany the redistributed copy. For lz-string that copy IS
        # the runtime baked into every generated document and every offline export - unlike mermaid
        # and Chart.js, whose notices the offline exporter emits beside the inlined library - so
        # the inline comment is the only in-band notice there is. It survives only because it is
        # spelled `/*!` + `@license`; an ordinary comment would be stripped.
        # NONSHAREABLE.html is excluded on purpose: it loads the layer from the companion file
        # above, which carries the notice, rather than inlining it.
        for name in ("commentable-html.js", "commentable-html.assets.js", "SHAREABLE.html"):
            text = _read(os.path.join(DIST, name))
            self.assertIn("pieroxy", text, "%s lost the lz-string MIT attribution" % name)
            self.assertIn("MIT license", text, name)


class RoundTripGuardTests(unittest.TestCase):
    """The strip re-reads its own output and refuses to hand back a rewritten program.

    This checks the ASSEMBLY, not the scan: the scan's decisions depend only on code characters,
    which the strip preserves, so re-scanning reaches the same decisions - right or wrong. What
    keeps a `/` from being misread in the first place is `AmbiguousSlashTests` (the reading is
    decided by the grammar); what catches an invalid result is `verify_js_syntax`, an independent
    parser.
    """

    def test_a_corrupted_result_fails_the_build(self):
        original = build._minify_assemble

        def corrupt(segs, keep, needs=None, comment_is_space=True):
            return original(segs, keep, needs, comment_is_space) + "\nconst injected = 1;"

        build._minify_assemble = corrupt
        try:
            with self.assertRaises(SystemExit):
                build.minify_js("const a = 1;\n")
            with self.assertRaises(SystemExit):
                build.minify_css("a { color: red; }\n")
        finally:
            build._minify_assemble = original

    def test_every_shipped_source_partial_round_trips(self):
        # The signature is the literals plus the whitespace-free code, so this asserts the strip
        # removed comments and nothing else from the real sources.
        for ext, minify, signature in (("js", build.minify_js, build._minify_js_signature),
                                       ("css", build.minify_css, build._minify_css_signature)):
            src = _concat(ext)
            self.assertEqual(signature(minify(src)), signature(src), ext)


class SyntaxOracleTests(unittest.TestCase):
    """The independent check: the strip cannot certify its own output, `node --check` can."""

    def test_valid_javascript_passes(self):
        if not shutil.which("node"):
            self.skipTest("node is not on PATH; CI runs this check")
        self.assertIn("syntax check OK", build.verify_js_syntax("const a = 1;\n"))

    def test_the_oracle_reports_a_skip_only_when_node_is_absent(self):
        # The message must distinguish "the parser ran and was happy" from "no parser ran", or a
        # green result proves nothing on a machine without node.
        msg = build.verify_js_syntax("const a = 1;\n")
        self.assertEqual("skipped" in msg, shutil.which("node") is None)

    def test_invalid_javascript_fails_the_build(self):
        if not shutil.which("node"):
            self.skipTest("node is not on PATH; CI runs this check")
        with self.assertRaises(SystemExit):
            build.verify_js_syntax("const a = ;\n")

    def test_the_shipped_layer_parses(self):
        if not shutil.which("node"):
            self.skipTest("node is not on PATH; CI runs this check")
        build.verify_js_syntax(_read(os.path.join(DIST, "commentable-html.js")))


class CssCommentStripTests(unittest.TestCase):
    def test_comments_indentation_and_blank_lines_go(self):
        out = build.minify_css("/* note */\n.a {\n\n  color: red;\n}\n")
        self.assertNotIn("note", out)
        self.assertEqual(out, ".a {\ncolor: red;\n}")

    def test_a_comment_between_two_tokens_never_becomes_a_space(self):
        # A CSS comment is removed at tokenization and leaves NO whitespace token, so `.a/**/.b`
        # is the compound selector `.a.b`. Turning it into a space would make it a descendant
        # selector and silently restyle the page.
        self.assertEqual(build.minify_css(".a/**/.b { color: red; }"), ".a.b { color: red; }")
        self.assertIn(".a", build.minify_css(".a /**/ .b { color: red; }"))

    def test_a_comment_that_would_fuse_two_tokens_is_kept_as_an_empty_comment(self):
        # ... but a comment does TERMINATE the token before it, so `bl/**/ue` is not the color
        # `blue` and `1px/**/2px` is not the dimension `1px2px`. Neither a space nor nothing is
        # right there; an empty comment is.
        for src in (":root { --x: bl/**/ue; }", ".x { margin: 1px/**/2px; }", "a/**/b { color: red }"):
            self.assertIn("/**/", build.minify_css(src), src)

    def test_a_descendant_combinator_keeps_its_space(self):
        self.assertIn(".a .b", build.minify_css(".a .b { color: red; }"))

    def test_calc_keeps_the_spaces_its_grammar_requires(self):
        self.assertIn("calc(100% - 2px)", build.minify_css(".a { width: calc(100% - 2px); }"))

    def test_a_comment_opener_inside_a_string_is_data(self):
        out = build.minify_css('.a::after { content: "/* not a comment */"; }')
        self.assertIn('"/* not a comment */"', out)

    def test_a_url_with_a_double_slash_survives(self):
        out = build.minify_css(".a { background: url(data:image/svg+xml,%3Csvg%2F%3E); }")
        self.assertIn("url(data:image/svg+xml,%3Csvg%2F%3E)", out)


class ShippedLayerTests(unittest.TestCase):
    """The built stage is what every document, export and fixture embeds."""

    def setUp(self):
        self.js = os.path.join(DIST, "commentable-html.js")
        self.css = os.path.join(DIST, "commentable-html.css")
        for path in (self.js, self.css):
            self.assertTrue(os.path.exists(path),
                            "%s is missing - run `python scripts/rebuild_all.py`" % path)

    def test_the_shipped_runtime_carries_no_developer_commentary(self):
        built = _read(self.js)
        segs, _problems = build._minify_js_scan(built)
        left = [t for kind, t in segs
                if kind in ("line", "block") and not build._minify_keep_comment(t)]
        self.assertEqual(left, [], "the shipped runtime still carries comments: %r" % left[:3])

    def test_the_shipped_stylesheet_carries_no_comments(self):
        segs, _problems = build._minify_css_scan(_read(self.css))
        left = [t for kind, t in segs
                if kind == "block" and not build._minify_keep_comment(t)]
        self.assertEqual(left, [], "the shipped stylesheet still carries comments: %r" % left[:3])

    def test_the_strip_is_worth_running(self):
        # #1250 measured comments and indentation at roughly 44 percent of the runtime. Assert the
        # win is real and durable rather than pinning an exact byte count that every feature moves.
        for source, built in ((_concat("js"), _read(self.js)),
                              (_concat("css"), _read(self.css))):
            self.assertLess(len(built), len(source) * 0.75)

    def test_the_shipped_layer_is_intact(self):
        js = _read(self.js)
        self.assertTrue(js.startswith("(()=>{"), "the arrow IIFE opener survived the strip")
        self.assertTrue(js.rstrip().endswith("})();"), "the arrow IIFE closer survived the strip")
        self.assertNotIn("</script", js.lower())

    def test_the_shipped_layer_manufactures_no_attribute_text(self):
        # Every `name="value"` in the SHIPPED runtime must already be spelled that way in the
        # source. Anything else is text the strip invented, which a regex that scans a document for
        # an HTML attribute would then match inside the layer instead of inside the content.
        source = _concat("js")
        manufactured = sorted({m.group(0) for m in
                               re.finditer(r'[\w-]+=["\'][^"\'\n]{0,60}["\']', _read(self.js))
                               if m.group(0) not in source})
        self.assertEqual(manufactured, [],
                         "the strip invented attribute-shaped text: %r" % manufactured[:5])


class SizeBudgetTests(unittest.TestCase):
    def setUp(self):
        self.budget = build.read_size_budget()

    def test_the_committed_budget_covers_the_generated_components(self):
        self.assertTrue(self.budget)
        for name in self.budget:
            path = os.path.join(_paths.DEV, "skill", name)
            self.assertTrue(os.path.exists(path),
                            "%s is budgeted but does not exist in the built stage" % name)

    def test_the_built_stage_is_inside_its_budget(self):
        over = []
        for name, limit in self.budget.items():
            actual = os.path.getsize(os.path.join(_paths.DEV, "skill", name))
            if actual > limit:
                over.append("%s: %d > %d" % (name, actual, limit))
        self.assertEqual(over, [], "the built stage is over budget: %s" % "; ".join(over))

    def test_an_oversize_component_fails(self):
        outputs = {os.path.join("out", "dist", "x.js"): "x" * 100}
        lines, failures = build.size_budget_check(
            outputs, "out", {os.path.join("dist", "x.js"): 10})
        self.assertEqual(len(lines), 1)
        self.assertEqual(len(failures), 1)
        self.assertIn("over its 10 byte budget", failures[0])

    def test_a_component_inside_its_budget_passes(self):
        outputs = {os.path.join("out", "dist", "x.js"): "x" * 8}
        _lines, failures = build.size_budget_check(
            outputs, "out", {os.path.join("dist", "x.js"): 10})
        self.assertEqual(failures, [])

    def test_a_budgeted_component_the_build_no_longer_produces_fails(self):
        # Otherwise renaming an output would silently retire its ceiling.
        _lines, failures = build.size_budget_check({}, "out", {os.path.join("dist", "x.js"): 10})
        self.assertEqual(len(failures), 1)
        self.assertIn("no such file", failures[0])

    def test_a_missing_or_malformed_budget_is_a_build_failure(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            missing = os.path.join(tmp, "nope.json")
            with self.assertRaises(SystemExit):
                build.read_size_budget(missing)
            for bad in ('{"components": {}}', '{}', '{"components": {"a": 0}}',
                        '{"components": {"a": "big"}}', 'not json', '[]', '"a string"',
                        '{"components": []}'):
                path = os.path.join(tmp, "budget.json")
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(bad)
                with self.assertRaises(SystemExit):
                    build.read_size_budget(path)

    def test_the_budget_file_documents_why_it_exists(self):
        with open(build.BUDGET_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertTrue(data.get("_comment"), "the budget file must say what raising it means")

    def test_a_new_payload_component_with_no_ceiling_fails(self):
        # Otherwise the payload just moves into a new dist file that nothing budgets.
        outputs = {os.path.join("out", "dist", "x.js"): "x" * 8,
                   os.path.join("out", "dist", "new-thing.js"): "y" * 8}
        _lines, failures = build.size_budget_check(
            outputs, "out", {os.path.join("dist", "x.js"): 10})
        self.assertTrue(any("no ceiling" in f for f in failures), failures)

    def test_dist_metadata_needs_no_ceiling(self):
        outputs = {os.path.join("out", "dist", "manifest.json"): "{}",
                   os.path.join("out", "dist", "README.md"): "hi",
                   os.path.join("out", "dist", "x.js"): "x" * 8}
        _lines, failures = build.size_budget_check(
            outputs, "out", {os.path.join("dist", "x.js"): 10})
        self.assertEqual(failures, [])

    def test_an_over_budget_check_run_fails_too(self):
        # CMH-BUILD-27 promises `--check` fails on an over-budget component, not only a build.
        import contextlib
        import io
        import tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            dist = os.path.join(d, "dist")
            os.makedirs(dist)
            out_path = os.path.join(dist, "SHAREABLE.html")
            with open(out_path, "w", encoding="utf-8", newline="") as fh:
                fh.write("x" * 100)
            err = io.StringIO()
            with mock.patch.object(build, "HERE", d), mock.patch.object(build, "DIST", dist), \
                    mock.patch.object(build, "build_all",
                                      return_value=({out_path: "x" * 100}, "1.2.3")), \
                    mock.patch.object(build, "read_size_budget",
                                      return_value={os.path.join("dist", "SHAREABLE.html"): 10}), \
                    mock.patch.object(build, "source_stamps", return_value={}), \
                    contextlib.redirect_stderr(err), \
                    contextlib.redirect_stdout(io.StringIO()):
                code = build.main(["build.py", "--check"])
            self.assertEqual(code, 1)
            self.assertIn("size budget exceeded", err.getvalue())

    def test_an_over_budget_build_writes_nothing(self):
        # The gate must REFUSE, not report: leaving oversize artifacts in the tree is how the next
        # `git add -A` commits exactly what the gate rejected.
        import contextlib
        import io
        import tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            dist = os.path.join(d, "dist")
            os.makedirs(dist)
            out_path = os.path.join(dist, "SHAREABLE.html")
            err = io.StringIO()
            with mock.patch.object(build, "HERE", d), mock.patch.object(build, "DIST", dist), \
                    mock.patch.object(build, "build_all",
                                      return_value=({out_path: "x" * 100}, "1.2.3")), \
                    mock.patch.object(build, "read_size_budget",
                                      return_value={os.path.join("dist", "SHAREABLE.html"): 10}), \
                    mock.patch.object(build, "source_stamps", return_value={}), \
                    contextlib.redirect_stderr(err), \
                    contextlib.redirect_stdout(io.StringIO()):
                code = build.main(["build.py"])
            self.assertEqual(code, 1)
            self.assertIn("size budget exceeded", err.getvalue())
            self.assertFalse(os.path.exists(out_path),
                             "an over-budget build must not write the artifact it rejected")


if __name__ == "__main__":
    unittest.main()
