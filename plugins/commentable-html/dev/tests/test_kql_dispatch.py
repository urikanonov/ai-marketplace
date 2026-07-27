#!/usr/bin/env python3
"""Tests for wiring KQL into the document highlight path.

Covers CMH-KQL-09 (a KQL block is re-baked by the same document highlight path as every
other language) and CMH-KQL-10 (editing a query regenerates the Run in Azure Data
Explorer link, so the button can never run pre-edit text).
"""
import os
import sys
import unittest
from urllib.parse import unquote, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402  shared pkg/dev split path constants
TOOLS = _paths.TOOLS
sys.path.insert(0, TOOLS)
import highlight_document  # noqa: E402
import kql_highlight  # noqa: E402
import kusto_link  # noqa: E402

QUERY = 'StormEvents | where State == "TX" | take 10'
EDITED = 'StormEvents | where State == "WA" | take 99'


def _href(figure):
    import re
    m = re.search(r'class="cmh-kql-run" href="([^"]*)"', figure)
    return m.group(1) if m else None


def _decode_link(href):
    """Return (cluster, database, query) carried by an ADX deep link."""
    import html as _html
    parsed = urlparse(_html.unescape(href))
    parts = parsed.path.strip("/").split("/")
    cluster, database = unquote(parts[1]), unquote(parts[3])
    payload = parsed.query.split("query=", 1)[1]
    return cluster, database, kusto_link.decode_query(unquote(payload))


class KqlDocumentDispatchTests(unittest.TestCase):
    """CMH-KQL-09."""

    def test_a_raw_kusto_block_is_highlighted_by_the_document_path(self):
        raw = '<pre><code class="language-kusto">%s</code></pre>' % (
            QUERY.replace('"', "&quot;"))
        out, count = highlight_document.highlight_document(raw)
        self.assertEqual(count, 1, "kusto must be dispatched like every other language")
        self.assertIn("cmh-kql-kw", out)

    def test_an_already_highlighted_kusto_block_is_left_alone(self):
        inner = kql_highlight.highlight_inner(QUERY)
        block = '<pre><code class="language-kusto">%s</code></pre>' % inner
        out, count = highlight_document.highlight_document(block)
        self.assertEqual(count, 0)
        self.assertEqual(out, block)

    def test_kusto_output_matches_the_kql_highlighter_byte_for_byte(self):
        # The document path must not become a second, divergent implementation.
        raw = '<pre><code class="language-kusto">%s</code></pre>' % (
            QUERY.replace('"', "&quot;"))
        out, _ = highlight_document.highlight_document(raw)
        self.assertIn(kql_highlight.highlight_inner(QUERY), out)


class AdxLinkRegenerationTests(unittest.TestCase):
    """CMH-KQL-10."""

    def test_the_run_link_encodes_the_query(self):
        figure = kql_highlight.render_block("help.kusto.windows.net", "Samples", "Demo", QUERY)
        cluster, database, query = _decode_link(_href(figure))
        self.assertEqual(cluster, "help.kusto.windows.net")
        self.assertEqual(database, "Samples")
        self.assertEqual(query, QUERY)

    def test_editing_the_query_regenerates_the_link(self):
        # The defect: re-highlighting only the <code> inner leaves the button running
        # the PRE-EDIT query, silently, with nothing catching it.
        figure = kql_highlight.render_block("help.kusto.windows.net", "Samples", "Demo", QUERY)
        updated = kql_highlight.refresh_block(figure, EDITED)
        _cluster, _database, query = _decode_link(_href(updated))
        self.assertEqual(query, EDITED, "the Run link must decode to the EDITED query")
        self.assertNotIn("TX", _href(updated))

    def test_refresh_preserves_the_frame_caption_and_cluster_affordance(self):
        figure = kql_highlight.render_block("help.kusto.windows.net", "Samples", "Demo", QUERY)
        updated = kql_highlight.refresh_block(figure, EDITED)
        for keep in ('<figure class="cmh-kql">', "cmh-kql-cap",
                     "cmh-kql-title cmh-kql-cluster cm-skip",
                     'data-cmh-copy="help.kusto.windows.net"', ">Demo<",
                     'class="cmh-kql-run"'):
            self.assertIn(keep, updated)

    def test_refresh_is_a_no_op_for_an_unchanged_query(self):
        figure = kql_highlight.render_block("help.kusto.windows.net", "Samples", "Demo", QUERY)
        self.assertEqual(kql_highlight.refresh_block(figure, QUERY), figure)

    def test_refresh_refuses_a_figure_it_cannot_understand(self):
        with self.assertRaises(ValueError):
            kql_highlight.refresh_block("<figure class=\"cmh-kql\">no link</figure>", EDITED)


if __name__ == "__main__":
    unittest.main()
