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


# A start tag with a QUOTE-AWARE attribute region, and one attribute out of it in any of HTML's
# three quoting forms. The test reads a run link the way the VALIDATOR does - an `<a>` element
# carrying `cmh-kql-run` as a class TOKEN - rather than by the literal `class="cmh-kql-run" href="`
# spelling, which is the very reading under test.
import re as _re  # noqa: E402

_A_TAG_RE = _re.compile(r"""<a(?![^\t\n\f\r />])((?:"[^"]*"|'[^']*'|[^>"'])*)>""", _re.IGNORECASE)


def _attr(attrs, name):
    m = _re.search(r"""(?<![-\w])%s[\t\n\f\r ]*=[\t\n\f\r ]*(?:"([^"]*)"|'([^']*)'|([^\t\n\f\r >]+))"""
                   % name, attrs, _re.IGNORECASE)
    return next((g for g in m.groups() if g is not None), None) if m else None


def _run_href(figure):
    """The href of the figure's run link, located by the class-TOKEN reading."""
    for m in _A_TAG_RE.finditer(figure):
        if "cmh-kql-run" in (_attr(m.group(1), "class") or "").split():
            return _attr(m.group(1), "href")
    return None


def _canonical_figure():
    return kql_highlight.render_block("help.kusto.windows.net", "Samples", "Demo", QUERY)


def _run_link_of(figure):
    """The figure's run-link START TAG, as authored text."""
    m = next(mm for mm in _A_TAG_RE.finditer(figure)
             if "cmh-kql-run" in (_attr(mm.group(1), "class") or "").split())
    return m.group(0)


def _with_run_tag(template):
    """The canonical figure with its run-link START TAG rewritten to `template % href`.

    Every shape produced this way is validator-clean (CMH-KQL-05/07 read `cmh-kql-run` as a class
    token off the parsed element), so the rewriter must be able to rebuild each of them.
    """
    figure = _canonical_figure()
    m = next(mm for mm in _A_TAG_RE.finditer(figure)
             if "cmh-kql-run" in (_attr(mm.group(1), "class") or "").split())
    return figure[:m.start()] + (template % _attr(m.group(1), "href")) + figure[m.end():]


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


class RunLinkShapeTests(unittest.TestCase):
    """CMH-KQL-10 / CMH-VAL-21 clause 11: what the validator calls a run link is what the
    rewriter can rebuild.

    A literal `<a class="cmh-kql-run" href="` match only saw a run link whose class attribute was
    EXACTLY that one token, double-quoted, and written before `href`. Every shape below is
    validator-clean (CMH-KQL-05/07 read `cmh-kql-run` as a class TOKEN off the parsed element), so
    each was silently left with its PRE-EDIT query in the button - the exact failure CMH-KQL-10
    exists to prevent.
    """

    SHAPES = {
        "an extra class token":
            '<a class="cmh-kql-run extra" href="%s" target="_blank" rel="noopener noreferrer">',
        "a single-quoted class":
            '<a class=\'cmh-kql-run\' href="%s" target="_blank" rel="noopener noreferrer">',
        "an unquoted class":
            '<a class=cmh-kql-run href="%s" target="_blank" rel="noopener noreferrer">',
        "href before class":
            '<a href="%s" class="cmh-kql-run" target="_blank" rel="noopener noreferrer">',
        "an uppercase tag and attribute names":
            '<A CLASS="cmh-kql-run" HREF="%s" target="_blank" rel="noopener noreferrer">',
        "a character-referenced class":
            '<a class="cmh-kql-r&#117;n" href="%s" target="_blank" rel="noopener noreferrer">',
    }

    def test_every_validator_clean_run_link_shape_is_rebuilt(self):
        for label, template in self.SHAPES.items():
            with self.subTest(shape=label):
                updated = kql_highlight.refresh_block(_with_run_tag(template), EDITED)
                _cluster, _database, query = _decode_link(_run_href(updated))
                self.assertEqual(query, EDITED,
                                 "a run link written with %s must be rebuilt" % label)

    def test_a_rebuilt_run_link_keeps_its_other_attributes(self):
        # The rewrite must not cost the link its safety attributes: CMH-KQL-05 warns about a run
        # link that opens an auxiliary context without rel="noopener".
        updated = kql_highlight.refresh_block(
            _with_run_tag(self.SHAPES["an extra class token"]), EDITED)
        m = next(mm for mm in _A_TAG_RE.finditer(updated)
                 if "cmh-kql-run" in (_attr(mm.group(1), "class") or "").split())
        self.assertEqual(_attr(m.group(1), "target"), "_blank")
        self.assertEqual(_attr(m.group(1), "rel"), "noopener noreferrer")
        self.assertIn("extra", _attr(m.group(1), "class").split())

    def test_the_ordinary_single_class_run_link_still_passes(self):
        # The control: the shape the tool itself emits keeps working, byte for byte.
        figure = _canonical_figure()
        updated = kql_highlight.refresh_block(figure, EDITED)
        self.assertIn('<a class="cmh-kql-run" href="', updated)
        _cluster, _database, query = _decode_link(_run_href(updated))
        self.assertEqual(query, EDITED)

    def test_a_class_that_merely_contains_the_token_is_not_a_run_link(self):
        # The mirror of the shapes above: a class token is matched by exact code points, so
        # `cmh-kql-run-ish` is a DIFFERENT class and rebuilding its href would corrupt an
        # unrelated link.
        figure = _with_run_tag('<a class="cmh-kql-run-ish" href="%s">')
        with self.assertRaises(ValueError):
            kql_highlight.refresh_block(figure, EDITED)

    def test_the_kusto_code_label_is_read_by_the_same_token_rule(self):
        # The other half of the same defect: the code block was located by a literal
        # double-quoted `language-kusto` substring, so a single-quoted label raised and the
        # figure kept its pre-edit query just the same.
        figure = _canonical_figure().replace('<code class="language-kusto">',
                                             "<code class='language-kusto highlighted'>")
        self.assertIn("<code class='language-kusto highlighted'>", figure)
        updated = kql_highlight.refresh_block(figure, EDITED)
        _cluster, _database, query = _decode_link(_run_href(updated))
        self.assertEqual(query, EDITED)
        self.assertIn(kql_highlight.highlight_inner(EDITED), updated)

    def test_a_code_label_that_merely_contains_the_kusto_name_is_not_a_kusto_block(self):
        figure = _canonical_figure().replace('<code class="language-kusto">',
                                             '<code class="language-kustomize">')
        with self.assertRaises(ValueError):
            kql_highlight.refresh_block(figure, EDITED)

    def test_a_kql_labelled_block_is_a_kusto_block(self):
        # The document highlight path dispatches BOTH `language-kusto` and `language-kql` to this
        # tokenizer (CMH-KQL-09), so a hand-authored `language-kql` figure must refresh too.
        figure = _canonical_figure().replace('<code class="language-kusto">',
                                             '<code class="language-kql">')
        updated = kql_highlight.refresh_block(figure, EDITED)
        _cluster, _database, query = _decode_link(_run_href(updated))
        self.assertEqual(query, EDITED)
        self.assertIn(kql_highlight.highlight_inner(EDITED), updated)

    def test_a_duplicate_href_is_not_left_behind_as_a_stale_payload(self):
        # HTML keeps the FIRST href, so a second one is inert to a browser - but it would sit in
        # the file still encoding the pre-edit query.
        figure = _with_run_tag('<a class="cmh-kql-run" href="%s" href="STALE-SECOND-HREF">')
        updated = kql_highlight.refresh_block(figure, EDITED)
        self.assertNotIn("STALE-SECOND-HREF", updated)
        m = next(mm for mm in _A_TAG_RE.finditer(updated)
                 if "cmh-kql-run" in (_attr(mm.group(1), "class") or "").split())
        self.assertEqual(m.group(1).count("href="), 1)

    def test_every_run_link_in_the_figure_is_refreshed(self):
        # The validator's figure gate accepts more than one run link and checks them ALL, so
        # refreshing only the first leaves the others executing the pre-edit query.
        figure = _canonical_figure()
        m = next(mm for mm in _A_TAG_RE.finditer(figure)
                 if "cmh-kql-run" in (_attr(mm.group(1), "class") or "").split())
        second = figure[m.start():m.end()] + "Run again</a>"
        figure = figure[:m.start()] + figure[m.start():].replace("</figcaption>",
                                                                 second + "</figcaption>", 1)
        updated = kql_highlight.refresh_block(figure, EDITED)
        hrefs = [_attr(mm.group(1), "href") for mm in _A_TAG_RE.finditer(updated)
                 if "cmh-kql-run" in (_attr(mm.group(1), "class") or "").split()]
        self.assertEqual(len(hrefs), 2)
        for href in hrefs:
            self.assertEqual(_decode_link(href)[2], EDITED)

    def test_a_run_link_inside_a_comment_is_not_the_run_link(self):
        # The validator's anchors come from a real parse, so a commented-out link is not one.
        # Rewriting the decoy and reporting success left the LIVE link with its pre-edit query -
        # the same silent failure, one inert region along.
        figure = _canonical_figure()
        decoy = "<!-- %s -->" % _run_link_of(figure)
        figure = figure.replace("<figcaption", decoy + "<figcaption", 1)
        updated = kql_highlight.refresh_block(figure, EDITED)
        self.assertIn(decoy, updated, "the commented-out decoy must be left exactly as authored")
        live = [_attr(mm.group(1), "href") for mm in _A_TAG_RE.finditer(updated)
                if "cmh-kql-run" in (_attr(mm.group(1), "class") or "").split()
                and mm.start() > updated.index("<figcaption")]
        self.assertEqual(_decode_link(live[0])[2], EDITED)

    def test_a_kusto_block_inside_a_comment_is_not_the_code_block(self):
        figure = _canonical_figure()
        decoy = "<!-- <pre><code class=\"language-kusto\">commented out</code></pre> -->"
        figure = figure.replace("<pre>", decoy + "<pre>", 1)
        updated = kql_highlight.refresh_block(figure, EDITED)
        self.assertIn(decoy, updated, "the commented-out decoy must be left exactly as authored")
        self.assertIn(kql_highlight.highlight_inner(EDITED), updated)

    def test_a_custom_element_is_not_an_anchor(self):
        # `<a\b` was satisfied by the `-` in `<a-run>`, so a custom element was read as the run
        # link and RE-SERIALIZED as `<a>` - markup the author never wrote - while the real link
        # kept its pre-edit query.
        figure = _canonical_figure()
        custom = _run_link_of(figure).replace("<a ", "<a-run ", 1)
        figure = figure.replace("<figcaption", custom + "</a-run><figcaption", 1)
        updated = kql_highlight.refresh_block(figure, EDITED)
        self.assertIn(custom, updated, "the custom element must be left exactly as authored")
        self.assertEqual(_decode_link(_run_href(updated))[2], EDITED)

    def test_a_preceding_unrecognized_block_does_not_hide_the_kusto_block(self):
        # A non-KQL block whose closer this pattern does not recognize (`</pre >`) runs its
        # non-greedy body on to the NEXT closer, swallowing the real KQL block; advancing the scan
        # past that whole match would then step over it and the figure would keep its old query.
        figure = _canonical_figure().replace(
            "<pre>", '<pre><code class="language-text">note</code></pre >\n<pre>', 1)
        updated = kql_highlight.refresh_block(figure, EDITED)
        self.assertEqual(_decode_link(_run_href(updated))[2], EDITED)
        self.assertIn(kql_highlight.highlight_inner(EDITED), updated)
        self.assertIn('<code class="language-text">note</code>', updated)

    def test_the_code_block_pattern_matches_content_extracts(self):
        # `content_extract` READS a block's source and this module REWRITES it, so the two must
        # agree on what a code block is. The import direction (content_extract imports this
        # module) forbids sharing the compiled object, so the copy is pinned as text.
        import content_extract
        self.assertEqual(kql_highlight._CODE_INNER_RE.pattern, content_extract._PRE_CODE_RE.pattern)
        self.assertEqual(kql_highlight._CODE_INNER_RE.flags, content_extract._PRE_CODE_RE.flags)

    def test_tag_shaped_text_inside_an_attribute_value_is_not_a_tag(self):
        # A raw scan reads a `<a ...>` or a `<pre><code ...>` written inside ANOTHER tag's quoted
        # attribute value as an element. Rewriting that text corrupts the attribute that holds it,
        # and taking it as the figure's code block encodes the wrong query into the live link.
        decoy = ('<a class=\'cmh-kql-run\' href=\'https://dataexplorer.azure.com/clusters/'
                 'other/databases/db?query=x\'>')
        figure = _canonical_figure().replace(
            '<figcaption class="cm-skip', '<figcaption title="%s" class="cm-skip' % decoy, 1)
        updated = kql_highlight.refresh_block(figure, EDITED)
        self.assertIn('title="%s"' % decoy, updated,
                      "the attribute value must be left exactly as authored")
        # `_href` reads the canonical double-quoted spelling, which the single-quoted decoy above
        # is not, so this is the LIVE link.
        self.assertEqual(_decode_link(_href(updated))[2], EDITED)

    def test_a_kusto_block_inside_an_attribute_value_is_not_the_code_block(self):
        block = "<pre><code class=\\'language-kusto\\'>FAKE</code></pre>"
        figure = _canonical_figure().replace(
            '<figcaption class="cm-skip', '<figcaption title="%s" class="cm-skip' % block, 1)
        self.assertNotIn("FAKE", kql_highlight.find_kusto_code(figure).group(3))

    def test_a_custom_element_block_is_not_a_code_block(self):
        # `<pre\b` / `<code\b` are satisfied by the `-` in `<pre-run>` / `<code-run>`, so a
        # KQL-labelled custom-element decoy was returned as the figure's code block: the edit loop
        # then read IT as the query and rebuilt the live ADX link with the wrong text.
        decoy = '<pre-run><code-run class="language-kusto">FAKE</code></pre>'
        figure = _canonical_figure().replace("<pre>", decoy + "\n<pre>", 1)
        self.assertNotIn("FAKE", kql_highlight.find_kusto_code(figure).group(3))
        updated = kql_highlight.refresh_block(figure, EDITED)
        self.assertIn(decoy, updated, "the custom element must be left exactly as authored")
        self.assertEqual(_decode_link(_run_href(updated))[2], EDITED)

    def test_a_comment_opener_inside_an_attribute_value_does_not_open_a_comment(self):
        # `<!--` inside an attribute value is literal text to a browser and to the validator's
        # parsed views. Read as a comment opener, it marked the LIVE run link inert, the refresh
        # raised, the caller swallowed it, and the figure kept its pre-edit query.
        figure = _canonical_figure().replace(
            "<button type=", '<button title="write <!-- to comment out" type=', 1)
        figure = figure.replace("</figure>", "<!-- author note --></figure>", 1)
        updated = kql_highlight.refresh_block(figure, EDITED)
        self.assertEqual(_decode_link(_run_href(updated))[2], EDITED)

    def test_an_unterminated_comment_runs_to_the_end(self):
        # A browser keeps consuming an unterminated comment, so everything after it is inert and
        # there is no live run link left to rebuild.
        figure = _canonical_figure().replace("<figcaption", "<!-- unterminated <figcaption", 1)
        with self.assertRaises(ValueError):
            kql_highlight.refresh_block(figure, EDITED)

    def test_an_anchor_inside_the_code_body_is_content_not_a_control(self):
        # Edits are spliced by offset, which is only safe while they are disjoint: a run link
        # written inside the code block's own body would otherwise be rewritten AND then have its
        # region replaced by the re-highlighted query, corrupting the tail of the block.
        inner = _run_link_of(_canonical_figure()).replace("<", "&lt;")
        figure = _canonical_figure().replace('language-kusto">',
                                             'language-kusto">%s' % inner, 1)
        updated = kql_highlight.refresh_block(figure, EDITED)
        self.assertEqual(_decode_link(_run_href(updated))[2], EDITED)
        self.assertIn(kql_highlight.highlight_inner(EDITED), updated)

    def test_find_kusto_code_tolerates_an_empty_input(self):
        self.assertIsNone(kql_highlight.find_kusto_code(None))
        self.assertIsNone(kql_highlight.find_kusto_code(""))

    def test_a_duplicate_attribute_keeps_only_the_first_as_html_does(self):
        figure = _with_run_tag('<a class="cmh-kql-run" href="%s" target="_blank" target="_self">')
        updated = kql_highlight.refresh_block(figure, EDITED)
        m = next(mm for mm in _A_TAG_RE.finditer(updated)
                 if "cmh-kql-run" in (_attr(mm.group(1), "class") or "").split())
        self.assertEqual(m.group(1).count("target="), 1)
        self.assertEqual(_attr(m.group(1), "target"), "_blank")


if __name__ == "__main__":
    unittest.main()
