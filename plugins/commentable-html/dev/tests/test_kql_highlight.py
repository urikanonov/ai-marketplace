#!/usr/bin/env python3
"""Regression tests for kql_highlight.py (author-time KQL syntax highlighter)."""
import contextlib
import html
import io
import os
import re
import runpy
import subprocess
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402  shared pkg/dev split path constants
TOOLS = _paths.TOOLS
sys.path.insert(0, TOOLS)
import kql_highlight as K  # noqa: E402

KQL_PY = os.path.join(TOOLS, "kusto", "kql_highlight.py")

QUERY = (
    "cluster('c.kusto.windows.net').database('db').MyTable\n"
    '| where PCCode == "P21006035" and Count > 5   // a trailing comment\n'
    "| summarize Usd = round(sum(CostInUsd)) by Month = startofmonth(Timestamp)\n"
    "| order by Month asc"
)


class _BinaryStdin:
    def __init__(self, text):
        self.buffer = io.BytesIO(text.encode("utf-8"))


def _text_content(fragment):
    """textContent of an HTML fragment: strip tags, decode entities."""
    return html.unescape(re.sub(r"<[^>]+>", "", fragment))


class KqlHighlightTests(unittest.TestCase):
    def test_inner_roundtrips_to_exact_query(self):
        self.assertEqual(_text_content(K.highlight_inner(QUERY)), QUERY)

    def test_crlf_query_roundtrips_to_lf(self):
        self.assertEqual(_text_content(K.highlight_inner(QUERY.replace("\n", "\r\n"))), QUERY)

    def test_markup_in_query_is_escaped(self):
        q = 'T | where x < 5 and y > 3 | extend h = "<script>alert(1)</script>" & z'
        inner = K.highlight_inner(q)
        self.assertNotIn("<script>", inner)
        self.assertIn("&lt;script&gt;", inner)
        self.assertIn("&amp;", inner)
        self.assertEqual(_text_content(inner), q)

    def test_keyword_function_string_comment_number_classes(self):
        inner = K.highlight_inner(QUERY)
        self.assertIn('<span class="cmh-kql-kw">where</span>', inner)
        self.assertIn('<span class="cmh-kql-kw">summarize</span>', inner)  # keyword, not followed by (
        self.assertIn('<span class="cmh-kql-fn">round</span>', inner)      # round( -> function
        self.assertIn('<span class="cmh-kql-str">"P21006035"</span>', inner)
        self.assertIn("cmh-kql-com", inner)   # the // comment
        self.assertIn('<span class="cmh-kql-num">5</span>', inner)

    def test_summarize_is_keyword_not_function(self):
        # 'summarize' is a keyword even though it is not followed by '('.
        self.assertIn('<span class="cmh-kql-kw">summarize</span>', K.highlight_inner("| summarize x"))

    def test_verbatim_string_with_backslashes(self):
        # KQL verbatim strings (@"...") treat backslash literally, so a path ending
        # in a separator must still be one string token (no C-escape over-consume).
        q = r'T | where Path == @"C:\Windows\System32\" and X == 1'
        inner = K.highlight_inner(q)
        self.assertEqual(_text_content(inner), q)
        self.assertIn(r'<span class="cmh-kql-str">@"C:\Windows\System32\"</span>', inner)

    def test_hyphenated_operator_is_one_keyword(self):
        self.assertIn('<span class="cmh-kql-kw">mv-expand</span>', K.highlight_inner("| mv-expand col"))

    def test_render_code_wraps_language_kusto(self):
        block = K.render_code(QUERY)
        self.assertTrue(block.startswith('<pre><code class="language-kusto">'))
        self.assertTrue(block.endswith("</code></pre>"))
        self.assertEqual(_text_content(block), QUERY)

    def test_render_code_no_cluster_marks_pre(self):
        # CMH-KQL-08: render_code(no_cluster=True) stamps data-cmh-kql-no-cluster on the <pre> (the
        # explicit override for a bare, non-runnable KQL block); the default (used by the runnable
        # figure) does NOT stamp it.
        self.assertNotIn("data-cmh-kql-no-cluster", K.render_code(QUERY))
        marked = K.render_code(QUERY, no_cluster=True)
        self.assertTrue(marked.startswith('<pre data-cmh-kql-no-cluster><code class="language-kusto">'))
        self.assertEqual(_text_content(marked), QUERY)

    def test_render_block_is_full_figure(self):
        block = K.render_block("help.kusto.windows.net", "Samples", "My & <title>", QUERY)
        self.assertIn('<figure class="cmh-kql">', block)
        self.assertIn('<figcaption class="cm-skip cmh-kql-cap">', block)
        self.assertIn('class="cmh-kql-run" href="https://dataexplorer.azure.com/', block)
        self.assertIn('target="_blank" rel="noopener noreferrer"', block)
        # The run link is labelled for Azure Data Explorer (not the old "Run in Kusto").
        self.assertIn("Run in Azure Data Explorer", block)
        self.assertNotIn("Run in Kusto", block)
        self.assertIn('<pre><code class="language-kusto">', block)
        # The title is HTML-escaped.
        self.assertIn("My &amp; &lt;title&gt;", block)
        # The code textContent still equals the query (tags + caption stripped).
        code = re.search(r"(?s)<pre><code[^>]*>(.*?)</code></pre>", block).group(1)
        self.assertEqual(_text_content(code), QUERY)

    def test_render_block_rejects_bad_cluster(self):
        with self.assertRaises(ValueError):
            K.render_block('evil" x', "db", "t", QUERY)

    def test_render_block_title_is_cluster_copy(self):
        # The caption title (cluster / database) is itself the click-to-copy button
        # for the cluster name; there is no separate middle chip.
        block = K.render_block("help.kusto.windows.net", "Samples", "help.kusto.windows.net / Samples", QUERY)
        self.assertIn(
            '<button type="button" class="cmh-kql-title cmh-kql-cluster cm-skip" '
            'data-cmh-copy="help.kusto.windows.net"',
            block)
        self.assertIn(">help.kusto.windows.net / Samples</button>", block)

    def test_deterministic(self):
        self.assertEqual(K.render_block("c.kusto.windows.net", "db", "t", QUERY),
                         K.render_block("c.kusto.windows.net", "db", "t", QUERY))

    def test_cli_code_only(self):
        r = subprocess.run([sys.executable, KQL_PY, "--code-only"], input=QUERY,
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        # CMH-KQL-08: --code-only stamps the explicit no-cluster marker so the bare block is clean.
        self.assertTrue(r.stdout.strip().startswith(
            '<pre data-cmh-kql-no-cluster><code class="language-kusto">'))
        self.assertEqual(_text_content(r.stdout.strip()), QUERY)

    def test_cli_full_block(self):
        r = subprocess.run([sys.executable, KQL_PY, "c.kusto.windows.net", "db", "Title", QUERY],
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('<figure class="cmh-kql">', r.stdout)
        self.assertIn('class="cmh-kql-run"', r.stdout)

    def test_cli_full_block_stdin(self):
        # The full-figure mode with 3 positional args reads the query from stdin.
        r = subprocess.run([sys.executable, KQL_PY, "c.kusto.windows.net", "db", "Title"],
                           input=QUERY, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('<figure class="cmh-kql">', r.stdout)
        code = re.search(r"(?s)<pre><code[^>]*>(.*?)</code></pre>", r.stdout).group(1)
        self.assertEqual(_text_content(code), QUERY)

    def test_cli_usage_without_args(self):
        r = subprocess.run([sys.executable, KQL_PY], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 2)
        self.assertIn("usage:", r.stderr)

    def test_cli_too_many_args_rejected(self):
        # An unquoted multi-word query would split across argv; reject rather than
        # silently encode only the first tokens.
        r = subprocess.run([sys.executable, KQL_PY, "c", "db", "title", "SELECT", "extra"],
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 2)
        self.assertIn("usage:", r.stderr)

    def test_cli_code_only_too_many_args_rejected(self):
        r = subprocess.run([sys.executable, KQL_PY, "--code-only", "q1", "q2"],
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 2)

    def test_cli_unknown_flag_rejected(self):
        r = subprocess.run([sys.executable, KQL_PY, "--bogus", "c", "db", "t", "q"],
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 2)
        self.assertIn("unknown flag", r.stderr)

    def test_main_code_only_arg(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = K.main(["kql_highlight.py", "--code-only", "T | take 1"])
        self.assertEqual(code, 0)
        self.assertIn("data-cmh-kql-no-cluster", out.getvalue())
        self.assertEqual(_text_content(out.getvalue().strip()), "T | take 1")

    def test_main_double_dash_separator_allows_flag_like_positional(self):
        # A bare "--" ends flag parsing, so a positional value beginning with "--" is
        # taken literally instead of being treated as an unknown flag.
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = K.main(["kql_highlight.py", "--code-only", "--", "--weird | take 1"])
        self.assertEqual(code, 0)
        self.assertEqual(_text_content(out.getvalue().strip()), "--weird | take 1")

    def test_main_code_only_empty_stdin_rejected(self):
        err = io.StringIO()
        with mock.patch.object(sys, "stdin", _BinaryStdin(" \r\n")), contextlib.redirect_stderr(err):
            code = K.main(["kql_highlight.py", "--code-only"])
        self.assertEqual(code, 2)
        self.assertIn("empty query", err.getvalue())

    def test_main_code_only_too_many_args_returns_usage(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = K.main(["kql_highlight.py", "--code-only", "q1", "q2"])
        self.assertEqual(code, 2)
        self.assertIn("usage:", err.getvalue())

    def test_main_full_block_stdin(self):
        out = io.StringIO()
        with mock.patch.object(sys, "stdin", _BinaryStdin(QUERY + "\n")), contextlib.redirect_stdout(out):
            code = K.main(["kql_highlight.py", "c.kusto.windows.net", "db", "Title"])
        self.assertEqual(code, 0)
        self.assertIn('<figure class="cmh-kql">', out.getvalue())
        code_html = re.search(r"(?s)<pre><code[^>]*>(.*?)</code></pre>", out.getvalue()).group(1)
        self.assertEqual(_text_content(code_html), QUERY)

    def test_main_full_block_invalid_cluster_reports_error(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = K.main(["kql_highlight.py", "bad cluster", "db", "Title", "T | take 1"])
        self.assertEqual(code, 2)
        self.assertIn("invalid cluster host", err.getvalue())

    def test_main_unknown_flag_returns_usage(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = K.main(["kql_highlight.py", "--bad", "c", "db", "t", "q"])
        self.assertEqual(code, 2)
        self.assertIn("unknown flag", err.getvalue())
        self.assertIn("usage:", err.getvalue())

    def test_main_wrong_arg_count_returns_usage(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = K.main(["kql_highlight.py", "c", "db"])
        self.assertEqual(code, 2)
        self.assertIn("usage:", err.getvalue())

    def test_module_entrypoint_uses_sys_argv(self):
        err = io.StringIO()
        with mock.patch.object(sys, "argv", [KQL_PY]), contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as cm:
                runpy.run_path(KQL_PY, run_name="__main__")
        self.assertEqual(cm.exception.code, 2)
        self.assertIn("usage:", err.getvalue())


class KqlTokenizerEdgeTests(unittest.TestCase):
    # A frozen known-good render for a canonical query. If tokenization drifts (e.g.
    # a keyword/class rename, or the str/com alternation order flips so `//` inside a
    # string becomes a comment), this fails with a visible diff.
    GOLDEN_CODE = (
        '<pre><code class="language-kusto">T <span class="cmh-kql-op">|</span> '
        '<span class="cmh-kql-kw">where</span> U <span class="cmh-kql-op">=</span>'
        '<span class="cmh-kql-op">=</span> <span class="cmh-kql-str">"http://x.com/y"</span> '
        '<span class="cmh-kql-op">|</span> <span class="cmh-kql-kw">take</span> '
        '<span class="cmh-kql-num">5</span></code></pre>'
    )

    def test_golden_render_code(self):
        self.assertEqual(K.render_code('T | where U == "http://x.com/y" | take 5'), self.GOLDEN_CODE)

    def test_double_slash_inside_string_is_not_a_comment(self):
        inner = K.highlight_inner('where U == "http://x.com/y" and V == 1')
        self.assertIn('<span class="cmh-kql-str">"http://x.com/y"</span>', inner)
        self.assertNotIn("cmh-kql-com", inner)  # no comment token
        self.assertIn('<span class="cmh-kql-num">1</span>', inner)  # rest of line still tokenized

    def test_escaped_quote_in_string_stays_one_token(self):
        q = r'where Name == "a\"b" and X == 1'
        inner = K.highlight_inner(q)
        self.assertEqual(_text_content(inner), q)
        self.assertIn(r'<span class="cmh-kql-str">"a\"b"</span>', inner)

    def test_bare_subtraction_is_operator_not_identifier(self):
        # `a-b` must tokenize as ident / op / ident, not one hyphenated identifier.
        self.assertIn("a<span class=\"cmh-kql-op\">-</span>b", K.highlight_inner("extend d = a-b"))

    def test_hyphenated_keyword_still_whole(self):
        for kw in ("mv-expand", "project-away", "make-series"):
            self.assertIn('<span class="cmh-kql-kw">%s</span>' % kw, K.highlight_inner("| " + kw + " x"))

    def test_hyphenated_keyword_is_case_insensitive(self):
        # Consistent with the non-hyphenated keyword branch (which lowercases), a
        # mixed-case hyphenated operator is still highlighted as one keyword.
        for kw in ("MV-EXPAND", "Project-Away"):
            self.assertIn('<span class="cmh-kql-kw">%s</span>' % kw, K.highlight_inner("| " + kw + " x"))
        # ...but a longer identifier that merely starts like one is NOT a keyword:
        # the \b boundary + no-hyphen ident rule split it into ident/op/ident.
        self.assertIn('mv<span class="cmh-kql-op">-</span>expandx', K.highlight_inner("| mv-expandx col"))

    def test_unterminated_verbatim_string_degrades_gracefully(self):
        # An unterminated @"... must still roundtrip exactly (chars fall through the
        # `other` branch) - no crash, no unescaped output.
        for q in ('@"foo', 'x | where p == @"C:\\a', "y == @'unclosed"):
            self.assertEqual(_text_content(K.highlight_inner(q)), q)

    def test_verbatim_string_doubled_quote(self):
        # KQL verbatim strings escape a quote by doubling it (@"a""b" is the string
        # a"b), so the whole thing is one string token and the code after it still
        # tokenizes (a naive @"[^"]*" would split it and flip quote parity).
        q = 'where M == @"She said ""hi""" and X == 1'
        inner = K.highlight_inner(q)
        self.assertEqual(_text_content(inner), q)
        self.assertIn('<span class="cmh-kql-str">@"She said ""hi"""</span>', inner)
        self.assertIn('<span class="cmh-kql-num">1</span>', inner)

    def test_template_demo_figure_matches_helper(self):
        # The #kql demo figure embedded in the template must equal the helper output,
        # so a tokenizer/class change cannot silently desync the shipped example.
        shell = os.path.join(_paths.ASSETS, "template.shell.html")
        with open(shell, encoding="utf-8") as fh:
            html_text = fh.read()
        m = re.search(r'(?s)(<figure class="cmh-kql">.*?</figure>)', html_text)
        self.assertIsNotNone(m, "no cmh-kql figure in template.shell.html")
        demo_q = (
            "StormEvents\n"
            "| where StartTime between (datetime(2007-01-01) .. datetime(2007-12-31))\n"
            '| where State == "TEXAS"\n'
            "| summarize Events = count(), Damage = sum(DamageProperty) by State  // group by state\n"
            "| top 10 by Damage desc"
        )
        expected = K.render_block("help.kusto.windows.net", "Samples", "help / Samples", demo_q)
        self.assertEqual(m.group(1), expected)
