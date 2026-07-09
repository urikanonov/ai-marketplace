#!/usr/bin/env python3
"""Coverage gap regression tests for commentable-html helpers."""
import html
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402  shared pkg/dev split path constants
TOOLS = _paths.TOOLS
sys.path.insert(0, TOOLS)
import kql_highlight as K  # noqa: E402


QUERY = (
    "StormEvents\n"
    "| where State == \"TEXAS\"\n"
    "| summarize Events = count() by EventType\n"
    "| top 5 by Events desc"
)


def text_content(fragment):
    return html.unescape(re.sub(r"<[^>]+>", "", fragment))


class CoverageGapTests(unittest.TestCase):
    def test_kql_render_block_emits_full_commentable_figure(self):
        block = K.render_block("help.kusto.windows.net", "Samples", "Storm events", QUERY)
        self.assertIn('<figure class="cmh-kql">', block)
        self.assertRegex(
            block,
            r'<a class="cmh-kql-run" href="https://dataexplorer\.azure\.com/[^"]+" '
            r'target="_blank" rel="noopener noreferrer">',
        )
        self.assertIn('<pre><code class="language-kusto">', block)

        match = re.search(r'(?s)<pre><code class="language-kusto">(.*?)</code></pre>', block)
        self.assertIsNotNone(match)
        self.assertEqual(text_content(match.group(1)), QUERY)


if __name__ == "__main__":
    unittest.main()
