#!/usr/bin/env python3
"""Tests for tools/highlight_document.py (batch code-block highlighting)."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402  shared pkg/dev split path constants
TOOLS = _paths.TOOLS
sys.path.insert(0, TOOLS)
import highlight_document  # noqa: E402


class HighlightDocumentTests(unittest.TestCase):
    def test_raw_language_block_is_highlighted(self):
        html = '<pre><code class="language-csharp">public sealed class X { }</code></pre>'
        out, count = highlight_document.highlight_document(html)
        self.assertEqual(count, 1)
        self.assertIn('class="cmh-code-kw"', out)
        self.assertIn("language-csharp", out)  # the wrapper class is preserved

    def test_alias_language_is_resolved(self):
        html = '<pre><code class="language-cs">var x = 1;</code></pre>'
        out, count = highlight_document.highlight_document(html)
        self.assertEqual(count, 1)
        self.assertIn("cmh-code-", out)

    def test_already_highlighted_block_is_left_unchanged(self):
        html = ('<pre><code class="language-python">'
                '<span class="cmh-code-kw">def</span> f(): pass</code></pre>')
        out, count = highlight_document.highlight_document(html)
        self.assertEqual(count, 0)
        self.assertEqual(out, html)

    def test_non_highlightable_label_is_left_unchanged(self):
        for cls in ("language-text", "language-kusto"):
            html = '<pre><code class="%s">plain content</code></pre>' % cls
            out, count = highlight_document.highlight_document(html)
            self.assertEqual(count, 0, cls)
            self.assertEqual(out, html, cls)

    def test_code_without_language_is_left_unchanged(self):
        html = "<pre><code>just some code</code></pre>"
        out, count = highlight_document.highlight_document(html)
        self.assertEqual(count, 0)
        self.assertEqual(out, html)

    def test_inline_code_is_not_touched(self):
        html = '<p>see <code class="language-csharp">Foo.Bar()</code> here</p>'
        out, count = highlight_document.highlight_document(html)
        self.assertEqual(count, 0)
        self.assertEqual(out, html)

    def test_escaped_generics_round_trip(self):
        # A raw block escapes < and >; unescape before highlighting, re-escape after, so the
        # rendered text stays List<T> and no markup is injected.
        html = '<pre><code class="language-csharp">List&lt;T&gt; xs;</code></pre>'
        out, count = highlight_document.highlight_document(html)
        self.assertEqual(count, 1)
        self.assertIn("&lt;", out)
        self.assertNotIn("<T>", out)  # the angle brackets stay escaped, never a real tag

    def test_idempotent(self):
        html = '<pre><code class="language-python">def f():\n    return 1</code></pre>'
        once, c1 = highlight_document.highlight_document(html)
        twice, c2 = highlight_document.highlight_document(once)
        self.assertEqual(c1, 1)
        self.assertEqual(c2, 0)
        self.assertEqual(once, twice)


if __name__ == "__main__":
    unittest.main()
