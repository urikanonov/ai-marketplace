#!/usr/bin/env python3
"""Regression tests for highlight_code.py."""
import contextlib
import html
import io
import os
import re
import runpy
import subprocess
import sys
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402  shared pkg/dev split path constants
TOOLS = _paths.TOOLS
sys.path.insert(0, TOOLS)
import highlight_code as H  # noqa: E402

HIGHLIGHT_PY = os.path.join(TOOLS, "highlight_code.py")

SNIPPETS = {
    "python": 'def foo(x):\n    s = "hi"\n    return 42  # comment\n',
    "javascript": 'function foo() { const s = "hi"; return 42; // comment\n/* block */ }\n',
    "typescript": 'interface T { value: number }\nconst s = "hi"; foo(42); // comment\n/* block */\n',
    "json": '{"flag": true, "n": 42, "s": "hi"} // comment\n',
    "bash": 'if foo; then\n  s="hi"\n  echo 42 # comment\nfi\n',
    "sql": "SELECT foo(42), 'hi' FROM t -- comment\n/* block */\n",
    "csharp": 'public class C { string s = "hi"; // comment\n/* block */ void M(){ Foo(42); } }\n',
    "java": 'public class C { String s = "hi"; // comment\n/* block */ void m(){ foo(42); } }\n',
    "go": 'func main() { s := "hi"; n := 42 // comment\n/* block */\nfoo()\n}\n',
    "yaml": 'flag: true\nname: "hi"\ncount: 42 # comment\n',
    "c": 'int main(){ char* s = "hi"; // comment\n/* block */ foo(42); }\n',
    "cpp": 'class C { public: void m(){ auto s = "hi"; // comment\n/* block */ foo(42); } };\n',
    "xml": '<!-- comment --><root attr="hi">42</root>\n',
    "html": '<!-- comment --><div class="hi">42</div>\n',
    "rust": 'fn main() { let s = "hi"; foo(42); // comment\n/* block */ }\n',
    "ruby": 'def foo\n  s = "hi"\n  puts 42 # comment\nend\n',
    "php": 'function foo() { $s = "hi"; bar(42); // comment\n/* block */ }\n',
    "swift": 'func foo() { let s = "hi"; bar(42); // comment\n/* block */ }\n',
    "kotlin": 'fun foo() { val s = "hi"; bar(42); // comment\n/* block */ }\n',
    "scala": 'def foo() { val s = "hi"; bar(42); // comment\n/* block */ }\n',
    "dart": 'void foo() { var s = "hi"; bar(42); // comment\n/* block */ }\n',
    "r": 'foo <- function(x) {\n  s <- "hi"\n  bar(42) # comment\n}\n',
    "perl": 'sub foo {\n  my $s = "hi";\n  bar(42); # comment\n}\n',
    "powershell": 'function Foo {\n  $s = "hi"\n  Write-Output 42 # comment\n  <# block #>\n}\n',
    "lua": 'function foo()\n  local s = "hi"\n  bar(42) -- comment\n  --[[ block ]]\nend\n',
    "toml": 'title = "hi"\nenabled = true\ncount = 42 # comment\n',
    "css": 'a { content: "hi"; z-index: 42; color: inherit; /* comment */ }\n',
    "groovy": 'def foo() { String s = "hi"; bar(42); // comment\n/* block */ }\n',
    "elixir": 'def foo do\n  s = "hi"\n  bar(42) # comment\nend\n',
    "haskell": 'foo :: Int -> String\nfoo x = let s = "hi" in bar 42 -- comment\n{- block -}\n',
    "objectivec": '- (void)foo { char *s = "hi"; bar(42); // comment\n/* block */ }\n',
    "batch": '@echo off\nset MSG="hi"\necho 42\nrem comment\n',
}

ROUNDTRIP_SNIPPETS = dict(SNIPPETS, **{
    "sh": SNIPPETS["bash"],
    "shell": SNIPPETS["bash"],
    "cs": SNIPPETS["csharp"],
    "golang": SNIPPETS["go"],
    "yml": SNIPPETS["yaml"],
    "c++": SNIPPETS["cpp"],
    "rs": SNIPPETS["rust"],
    "rb": SNIPPETS["ruby"],
    "kt": SNIPPETS["kotlin"],
    "pl": SNIPPETS["perl"],
    "ps1": SNIPPETS["powershell"],
    "ps": SNIPPETS["powershell"],
    "objc": SNIPPETS["objectivec"],
    "hs": SNIPPETS["haskell"],
    "ex": SNIPPETS["elixir"],
    "exs": SNIPPETS["elixir"],
    "bat": SNIPPETS["batch"],
    "cmd": SNIPPETS["batch"],
})

TOKEN_CASES = {
    "python": ("def", '"hi"', "# comment", "42", None),
    "javascript": ("function", '"hi"', "// comment", "42", "/* block */"),
    "typescript": ("interface", '"hi"', "// comment", "42", "/* block */"),
    "json": ("true", '"hi"', "// comment", "42", None),
    "bash": ("if", '"hi"', "# comment", "42", None),
    "sql": ("SELECT", "'hi'", "-- comment", "42", "/* block */"),
    "csharp": ("public", '"hi"', "// comment", "42", "/* block */"),
    "java": ("public", '"hi"', "// comment", "42", "/* block */"),
    "go": ("func", '"hi"', "// comment", "42", "/* block */"),
    "yaml": ("true", '"hi"', "# comment", "42", None),
    "c": ("int", '"hi"', "// comment", "42", "/* block */"),
    "cpp": ("class", '"hi"', "// comment", "42", "/* block */"),
    "xml": ("root", '"hi"', "<!-- comment -->", "42", "<!-- comment -->"),
    "html": ("div", '"hi"', "<!-- comment -->", "42", "<!-- comment -->"),
    "rust": ("fn", '"hi"', "// comment", "42", "/* block */"),
    "ruby": ("def", '"hi"', "# comment", "42", None),
    "php": ("function", '"hi"', "// comment", "42", "/* block */"),
    "swift": ("func", '"hi"', "// comment", "42", "/* block */"),
    "kotlin": ("fun", '"hi"', "// comment", "42", "/* block */"),
    "scala": ("def", '"hi"', "// comment", "42", "/* block */"),
    "dart": ("void", '"hi"', "// comment", "42", "/* block */"),
    "r": ("function", '"hi"', "# comment", "42", None),
    "perl": ("sub", '"hi"', "# comment", "42", None),
    "powershell": ("function", '"hi"', "# comment", "42", "<# block #>"),
    "lua": ("function", '"hi"', "-- comment", "42", "--[[ block ]]"),
    "toml": ("true", '"hi"', "# comment", "42", None),
    "css": ("inherit", '"hi"', "/* comment */", "42", "/* comment */"),
    "groovy": ("def", '"hi"', "// comment", "42", "/* block */"),
    "elixir": ("def", '"hi"', "# comment", "42", None),
    "haskell": ("let", '"hi"', "-- comment", "42", "{- block -}"),
    "objectivec": ("void", '"hi"', "// comment", "42", "/* block */"),
    "batch": ("echo", '"hi"', "rem comment", "42", None),
}


class _BinaryStdin:
    def __init__(self, text):
        self.buffer = io.BytesIO(text.encode("utf-8"))


def _text_content(fragment):
    return html.unescape(re.sub(r"<[^>]+>", "", fragment))


def _normalized(text):
    return text.replace("\r\n", "\n").replace("\r", "\n")


class HighlightCodeRoundTripTests(unittest.TestCase):
    def test_roundtrips_each_supported_language(self):
        self.assertEqual(sorted(ROUNDTRIP_SNIPPETS), H.supported_languages())
        for language, snippet in ROUNDTRIP_SNIPPETS.items():
            with self.subTest(language=language):
                crlf = snippet.replace("\n", "\r\n")
                self.assertEqual(_text_content(H.highlight_block(language, crlf)), _normalized(crlf))

    def test_unknown_language_escape_only_roundtrips(self):
        code = "++[>++<-]\na < b && c > d\n"
        block = H.highlight_block("brainfuck", code)
        self.assertTrue(block.startswith('<pre><code class="language-brainfuck">'))
        self.assertNotIn("cmh-code-", block)
        self.assertIn("a &lt; b &amp;&amp; c &gt; d", block)
        self.assertEqual(_text_content(block), code)


class HighlightCodeTokenTests(unittest.TestCase):
    def test_expected_token_classes_per_language(self):
        for language, snippet in SNIPPETS.items():
            keyword, string, line_comment, number, block_comment = TOKEN_CASES[language]
            with self.subTest(language=language):
                inner = H.highlight_code(language, snippet)
                self.assertIn('<span class="cmh-code-kw">%s</span>' % html.escape(keyword, quote=False), inner)
                self.assertIn('<span class="cmh-code-str">%s</span>' % html.escape(string, quote=False), inner)
                self.assertIn('<span class="cmh-code-com">%s</span>' % html.escape(line_comment, quote=False), inner)
                self.assertIn('<span class="cmh-code-num">%s</span>' % number, inner)
                if block_comment:
                    self.assertIn('<span class="cmh-code-com">%s</span>' % html.escape(block_comment, quote=False), inner)

    def test_function_call_identifier_is_wrapped(self):
        inner = H.highlight_code("python", "foo(42)")
        self.assertIn('<span class="cmh-code-fn">foo</span><span class="cmh-code-op">(</span>', inner)

    def test_keyword_inside_string_or_comment_is_not_retokenized(self):
        inner = H.highlight_code("python", '"for" # while')
        self.assertIn('<span class="cmh-code-str">"for"</span>', inner)
        self.assertIn('<span class="cmh-code-com"># while</span>', inner)
        self.assertNotIn("cmh-code-kw", inner)

    def test_aliases_use_canonical_language_configs(self):
        self.assertIn('<code class="language-bash">', H.highlight_block("sh", "if true; then echo 1; fi"))
        self.assertIn('<span class="cmh-code-kw">class</span>', H.highlight_code("cs", "class C {}"))
        self.assertIn('<span class="cmh-code-kw">func</span>', H.highlight_code("golang", "func main() {}"))
        self.assertIn('<span class="cmh-code-kw">true</span>', H.highlight_code("yml", "flag: true"))
        self.assertIn('<span class="cmh-code-kw">class</span>', H.highlight_code("c++", "class C {};"))


class HighlightCodeSafetyTests(unittest.TestCase):
    def test_markup_and_operators_are_escaped(self):
        code = "<script>alert(1)</" + "script>\na < b && c > d\n"
        block = H.highlight_block("javascript", code)
        text_without_tags = re.sub(r"<[^>]+>", "", block)
        self.assertNotIn("<script>", block)
        self.assertNotIn("</" + "script>", block)
        self.assertNotIn("<", text_without_tags)
        self.assertNotIn(">", text_without_tags)
        self.assertIn("&lt;script&gt;alert(1)&lt;/" + "script&gt;", text_without_tags)
        self.assertIn("a &lt; b &amp;&amp; c &gt; d", text_without_tags)
        self.assertEqual(_text_content(block), code)

    def test_block_wrapper(self):
        block = H.highlight_block("python", "def foo():\n    return 1\n")
        self.assertTrue(block.startswith('<pre><code class="language-python">'))
        self.assertTrue(block.endswith("</code></pre>"))

    def test_empty_keyword_set_has_no_pattern(self):
        self.assertEqual(H._keyword_pattern({"keywords": frozenset()}), "")


class HighlightCodeCliTests(unittest.TestCase):
    def test_cli_arg_code(self):
        result = subprocess.run([sys.executable, HIGHLIGHT_PY, "python", "def foo(): return 1"],
                                capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('<pre><code class="language-python">', result.stdout)
        self.assertEqual(_text_content(result.stdout), "def foo(): return 1")

    def test_cli_stdin_code(self):
        code = "SELECT 1\n"
        result = subprocess.run([sys.executable, HIGHLIGHT_PY, "sql"], input=code,
                                capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(_text_content(result.stdout), code)

    def test_cli_list(self):
        result = subprocess.run([sys.executable, HIGHLIGHT_PY, "--list"],
                                capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("python", result.stdout.splitlines())
        self.assertIn("c++", result.stdout.splitlines())
        self.assertIn("rust", result.stdout.splitlines())

    def test_main_list_direct(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = H.main(["--list"])
        self.assertEqual(code, 0)
        self.assertIn("python", out.getvalue().splitlines())

    def test_main_requires_language(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as cm:
                H.main([])
        self.assertEqual(cm.exception.code, 2)
        self.assertIn("language is required", err.getvalue())

    def test_main_reads_code_from_stdin(self):
        code_text = "SELECT 1\r\n"
        out = io.StringIO()
        with mock.patch.object(sys, "stdin", _BinaryStdin(code_text)), contextlib.redirect_stdout(out):
            code = H.main(["sql"])
        self.assertEqual(code, 0)
        self.assertEqual(_text_content(out.getvalue()), "SELECT 1\n")

    def test_module_entrypoint_uses_sys_argv(self):
        out = io.StringIO()
        with mock.patch.object(sys, "argv", [HIGHLIGHT_PY, "--list"]), contextlib.redirect_stdout(out):
            with self.assertRaises(SystemExit) as cm:
                runpy.run_path(HIGHLIGHT_PY, run_name="__main__")
        self.assertEqual(cm.exception.code, 0)
        self.assertIn("python", out.getvalue().splitlines())


class HighlightCodeCaseSensitivityTests(unittest.TestCase):
    def test_case_sensitive_languages_reject_wrong_case_keywords(self):
        # An identifier that merely case-folds to a keyword must NOT be colored as a keyword in
        # a case-sensitive language (e.g. C# `String` vs keyword `string`, Python `IF` vs `if`).
        cases = {
            "python": "true false none IF Def Class Return",
            "csharp": "String Object VOID Int Class",
            "java": "String INT Class Void",
            "javascript": "FUNCTION Const LET Return",
            "typescript": "Interface Type CONST",
            "rust": "IF Fn Impl LET Struct",
            "go": "FUNC Var Type Package",
            "cpp": "CLASS Int Void Namespace",
            "ruby": "DEF Class Module Return",
            "kotlin": "FUN Val Var Class",
        }
        for language, code in cases.items():
            with self.subTest(language=language):
                self.assertNotIn("cmh-code-kw", H.highlight_code(language, code))

    def test_case_sensitive_languages_still_match_correct_case(self):
        self.assertIn('<span class="cmh-code-kw">def</span>', H.highlight_code("python", "def f(): pass"))
        self.assertIn('<span class="cmh-code-kw">class</span>', H.highlight_code("csharp", "class C {}"))
        self.assertIn('<span class="cmh-code-kw">fn</span>', H.highlight_code("rust", "fn main() {}"))

    def test_case_insensitive_languages_match_any_case(self):
        self.assertIn('<span class="cmh-code-kw">SELECT</span>', H.highlight_code("sql", "SELECT 1"))
        self.assertIn('<span class="cmh-code-kw">IF</span>', H.highlight_code("batch", "IF exist x del x"))
        self.assertIn('<span class="cmh-code-kw">Function</span>', H.highlight_code("powershell", "Function Foo {}"))
        self.assertIn('<span class="cmh-code-kw">DIV</span>', H.highlight_code("html", "<DIV></DIV>"))
        self.assertIn('<span class="cmh-code-kw">INHERIT</span>', H.highlight_code("css", "a{color:INHERIT}"))


class HighlightCodeCommentAndStringEdgeTests(unittest.TestCase):
    def test_secondary_line_comment_prefixes(self):
        # PHP has both // and #; batch has both rem and ::. Both prefixes must be highlighted.
        self.assertIn('<span class="cmh-code-com"># hash note</span>', H.highlight_code("php", "$x = 1; # hash note"))
        self.assertIn('<span class="cmh-code-com">:: colon note</span>',
                      H.highlight_code("batch", "set x=1\n:: colon note"))

    def test_batch_rem_needs_word_boundary(self):
        self.assertIn('<span class="cmh-code-com">rem note</span>', H.highlight_code("batch", "echo hi\nrem note"))
        self.assertIn('<span class="cmh-code-com">rem\tnote</span>', H.highlight_code("batch", "echo hi\nrem\tnote"))
        self.assertIn('<span class="cmh-code-com">rem</span>', H.highlight_code("batch", "echo hi\nrem"))
        self.assertNotIn('cmh-code-com">rem', H.highlight_code("batch", "set remainder=1"))

    def test_swift_and_dart_multiline_strings(self):
        swift = H.highlight_code("swift", 'let s = """\nline\n"""')
        self.assertIn('<span class="cmh-code-str">"""\nline\n"""</span>', swift)
        dart = H.highlight_code("dart", "var s = '''\nline\n''';")
        self.assertIn("<span class=\"cmh-code-str\">'''\nline\n'''</span>", dart)

    def test_toml_literal_string_preserves_backslash(self):
        out = H.highlight_code("toml", "path = 'C:\\Users\\me'")
        self.assertIn("<span class=\"cmh-code-str\">'C:\\Users\\me'</span>", out)

    def test_line_continuation_stays_inside_string(self):
        out = H.highlight_code("javascript", '"a \\\nb"')
        self.assertIn('<span class="cmh-code-str">"a \\\nb"</span>', out)

    def test_unterminated_block_comment_highlights_to_end(self):
        out = H.highlight_code("c", "int x; /* todo: finish")
        self.assertIn('<span class="cmh-code-com">/* todo: finish</span>', out)

    def test_unterminated_string_highlights_to_end_of_line(self):
        out = H.highlight_code("python", 'x = "oops\ny = 1\n')
        self.assertIn('<span class="cmh-code-str">"oops</span>', out)
        # The next line is not swallowed into the string.
        self.assertIn('<span class="cmh-code-num">1</span>', out)

    def test_single_quote_sigils_are_not_swallowed_as_strings(self):
        # A lone ' is common in real code, so single-quote styles require a closing quote and never
        # run to end of line: Rust lifetimes, YAML apostrophes, and C++ digit separators stay intact.
        rust = H.highlight_code("rust", 'fn f() -> &\'static str { "hi" }')
        self.assertEqual(rust.count('class="cmh-code-str"'), 1)  # only "hi", not the 'static lifetime
        self.assertIn('<span class="cmh-code-str">"hi"</span>', rust)
        self.assertNotIn('class="cmh-code-str"', H.highlight_code("yaml", "title: don't stop"))
        self.assertNotIn('class="cmh-code-str"', H.highlight_code("cpp", "int n = 1'000;"))

    def test_char_literal_languages_color_chars_not_lifetimes(self):
        # C/C++/C#/Java/Go/Rust/Objective-C use ' for a one-character char/rune literal, not a string.
        for lang in ("c", "cpp", "csharp", "java", "go", "rust", "objectivec"):
            with self.subTest(language=lang):
                self.assertIn("<span class=\"cmh-code-str\">'x'</span>", H.highlight_code(lang, "c = 'x';"))
        # Even paired Rust lifetimes are never mis-colored as a string.
        self.assertNotIn('class="cmh-code-str"',
                         H.highlight_code("rust", "fn longest<'a>(x: &'a str, y: &'a str) -> &'a str {"))
        # A multi-character single-quoted string in a string-quote language still highlights.
        self.assertIn("<span class=\"cmh-code-str\">'hi'</span>", H.highlight_code("python", "s = 'hi'"))
        # Escaped and unicode char literals highlight too, not only single raw chars.
        self.assertIn("<span class=\"cmh-code-str\">'\\n'</span>", H.highlight_code("c", "c = '\\n';"))
        self.assertIn("<span class=\"cmh-code-str\">'\\x41'</span>", H.highlight_code("c", "c = '\\x41';"))
        self.assertIn("<span class=\"cmh-code-str\">'\\u0041'</span>", H.highlight_code("java", "c = '\\u0041';"))
        self.assertIn("<span class=\"cmh-code-str\">'\\u{2764}'</span>", H.highlight_code("rust", "let c = '\\u{2764}';"))

    def test_pathological_escaped_quote_input_is_linear(self):
        # A run of `"\` never closes; a backtracking tokenizer rescans to EOF at every quote
        # (quadratic). The unrolled string patterns keep this linear - a big input is instant.
        code = '"\\' * 20000
        start = time.perf_counter()
        out = H.highlight_code("javascript", code)
        elapsed = time.perf_counter() - start
        self.assertEqual(_text_content(out), code)
        self.assertLess(elapsed, 3.0, "string tokenization must be linear, not superlinear")


class HighlightCodeSanitizationTests(unittest.TestCase):
    def test_class_language_only_emits_safe_characters(self):
        for label in ["c++", "f#", "  spaced name  ", "../../etc/passwd", '"><script>', "语言"]:
            with self.subTest(label=label):
                self.assertRegex(H._class_language(label), r"^[A-Za-z0-9_+.-]*$")
                block = H.highlight_block(label, "x = 1")
                self.assertTrue(block.startswith('<pre><code class="language-'))
                self.assertNotIn('"><', block)

    def test_literal_highlight_span_in_source_is_escaped(self):
        code = '<span class="cmh-code-kw">danger</span>'
        block = H.highlight_block("html", code)
        # The injected angle brackets must be escaped, and the text must roundtrip exactly, so
        # the source cannot inject real markup even though html marks up `span`/`class` tokens.
        self.assertIn("&lt;", block)
        self.assertIn("&gt;", block)
        self.assertEqual(_text_content(block), code)


class HighlightCodeListExactTests(unittest.TestCase):
    def test_main_list_is_exact_and_sorted(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            H.main(["--list"])
        listed = [line for line in out.getvalue().split(os.linesep) if line]
        self.assertEqual(listed, H.supported_languages())


if __name__ == "__main__":
    unittest.main()
