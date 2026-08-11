#!/usr/bin/env python3
"""The cold tier stores the bulk compressed WITHOUT downgrading the document (CMH-COLD).

The trap these tests exist to pin is the one #1250 warns about: compressing the whole body would
be a smaller file and a worse document - `Ctrl+F` would miss text before hydration, a no-JS read
would render nothing, an AI reader or a search indexer would extract no prose, and deep links
would dangle. So the tests assert what must NEVER be compressed at least as hard as they assert
that anything is compressed at all, and they assert the round trip is byte-exact, because an
"optimisation" that cannot be undone is a one-way door.
"""
import base64
import glob
import gzip
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402
sys.path.insert(0, _paths.TOOLS)
import cold_tier  # noqa: E402
import content_extract  # noqa: E402
import content_replace  # noqa: E402
import finalize  # noqa: E402
import mark_reviewed  # noqa: E402
import new_document  # noqa: E402
import section_hash  # noqa: E402
import validate  # noqa: E402

# Fixture sizes derive from the SHIPPED thresholds rather than repeating them: retuning the
# defaults (CMH-COLD-10) must not silently turn an eligibility test into a no-op. The invariants
# below are asserted at import time because each one is a way this module has already gone vacuous:
# BIG must clear the eligibility bar, and SMALL must sit BETWEEN keep_rows and min_rows so
# "a small table is left alone" really exercises the min_rows gate rather than simply having no
# tail to take.
MIN = cold_tier.DEFAULT_MIN_ROWS
KEEP = cold_tier.DEFAULT_KEEP_ROWS
BIG = max(MIN, KEEP) + 1
SMALL = KEEP + max(1, (MIN - KEEP) // 2)
HALF = KEEP + (BIG - KEEP) // 2  # a split point genuinely INSIDE the compressible tail
LAST_ROW = "<td>r%d</td>" % (BIG - 1)

# Most of this module is about the payload shape, the round trip, the failure paths and the runtime
# wiring - none of which depend on the SHIPPED thresholds, only on there being a compressible tail.
# Those tests pass explicit small thresholds so that retuning a default cannot add minutes to a CI
# shard for no extra coverage (at 2000/4000 every fixture would otherwise be a 4001-row document).
# The tests that genuinely pin the shipped defaults - eligibility, the skeleton guarantee, and the
# browser-fixture pins - keep the derived sizes above.
TEST_MIN = 40
TEST_KEEP = 20
TEST_BIG = TEST_MIN + TEST_KEEP
TEST_LAST_ROW = "<td>r%d</td>" % (TEST_BIG - 1)


def _compress(html, min_rows=TEST_MIN, keep_rows=TEST_KEEP):
    return cold_tier.compress(html, min_rows=min_rows, keep_rows=keep_rows)

PREAMBLE = os.path.join(_paths.ASSETS, "js", "00-preamble.js")
SWEEP = os.path.join(_paths.DEV, "tools", "cold-tier-threshold-sweep.json")
LOADER = os.path.join(_paths.ASSETS, "js", "01-cold-tier.js")
STARTUP = os.path.join(_paths.ASSETS, "js", "95-startup.js")


def _read(path):
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def _rows(count, start=0, cells=("r%d", "value %d", "note %d")):
    return "\n".join(
        "    <tr>" + "".join("<td>" + (c % i) + "</td>" for c in cells) + "</tr>"
        for i in range(start, start + count))


def _doc(content, root_attrs=""):
    return ("<!DOCTYPE html>\n<html><head><title>t</title></head><body>\n"
            '<main id="commentRoot"%s>\n' % root_attrs
            + content
            + "\n</main>\n</body></html>\n")


def _table(row_count, head="  <thead><tr><th>a</th><th>b</th><th>c</th></tr></thead>\n",
           caption="  <caption>Rows</caption>\n", extra_rows=""):
    return ("<table>\n" + caption + head + "  <tbody>\n"
            + _rows(row_count) + extra_rows + "\n  </tbody>\n</table>")


def _big_doc(row_count=BIG):
    return _doc("<h1>Title</h1>\n<p>Prose stays plain.</p>\n" + _table(row_count))


def _payload(html):
    span = cold_tier.find_blob(html)
    assert span is not None, "no payload in document"
    inner = html[span[0]:span[1]]
    return json.loads(inner[inner.index(">") + 1:inner.rindex("</")])


def _sign_test_p(hits, n):
    """Exact one-sided binomial tail P(X >= hits) for X ~ Binomial(n, 1/2).

    Recomputed here rather than read out of the artifact, so a transcribed p-value cannot be wrong
    while the suite stays green.
    """
    if not n:
        return 1.0
    return sum(math.comb(n, k) for k in range(hits, n + 1)) / float(2 ** n)


def _clopper_pearson_upper(hits, n, alpha):
    """One-sided exact upper bound on the rate given *hits* of *n*.

    A non-rejection says only that the data do not exclude zero; this says what they DO exclude,
    which is the honest form of "the residual is small".
    """
    def cdf(p):
        return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(0, hits + 1))

    lo, hi = 0.0, 1.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if cdf(mid) > alpha:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _spec_row(feature_id):
    head = "| " + feature_id + " |"
    for path in sorted(glob.glob(os.path.join(_paths.DEV, "spec", "*.md"))):
        with open(path, "r", encoding="utf-8-sig") as fh:
            for line in fh:
                if line.startswith(head):
                    return line
    return ""


class EligibilityTests(unittest.TestCase):
    """Only a large table's row TAIL is ever taken, and only when it is safe to take."""

    def test_a_large_table_tail_is_compressed(self):
        out, changed = cold_tier.compress(_big_doc(BIG))
        self.assertTrue(changed)
        self.assertEqual(cold_tier.state(out), "compressed")
        self.assertEqual(_payload(out)["parts"][0]["rows"], BIG - KEEP)

    def test_a_small_table_is_left_alone(self):
        # At the default min-rows, a table this size is entirely first-screen material.
        out, changed = cold_tier.compress(_big_doc(SMALL))
        self.assertFalse(changed)
        self.assertEqual(cold_tier.state(out), "plain")

    def test_a_table_exactly_at_the_threshold_is_left_alone(self):
        out, changed = cold_tier.compress(_big_doc(cold_tier.DEFAULT_MIN_ROWS))
        self.assertFalse(changed)

    def test_only_the_tail_beyond_keep_rows_is_taken(self):
        out, _ = cold_tier.compress(_big_doc(60), min_rows=10, keep_rows=5)
        self.assertEqual(_payload(out)["parts"][0]["rows"], 55)
        self.assertEqual(out.count("<tr><td>r"), 5)

    def test_every_large_body_in_the_document_is_taken(self):
        html = _doc("<h1>T</h1>\n" + _table(BIG) + "\n" + _table(BIG))
        out, changed = cold_tier.compress(html)
        self.assertTrue(changed)
        self.assertEqual(len(_payload(out)["parts"]), 2)

    def test_a_tail_row_holding_a_heading_disqualifies_the_table(self):
        html = _doc("<h1>T</h1>\n" + _table(BIG, extra_rows='\n    <tr><td><h3 id="deep">Deep</h3></td></tr>'))
        out, changed = cold_tier.compress(html)
        self.assertFalse(changed, "a heading (an anchor target) must never be compressed")

    def test_a_document_this_feature_cannot_parse_is_left_to_its_own_checks(self):
        # A plain document must never be REFUSED by a pre-pass belonging to a feature it does not
        # use: expansion is not a second, stricter gate in front of the validator.
        for html in ("", "not html at all", "<html><body><p>plain</p></body></html>",
                     '<main id="commentRoot"><table><tbody><tr><td>x</td></tr>'):
            with self.subTest(html=html[:24]):
                out, changed = cold_tier.expand(html)
                self.assertFalse(changed)
                self.assertEqual(out, html)

    def test_a_first_wins_duplicate_attribute_is_read_the_way_a_browser_reads_it(self):
        html = ("<!DOCTYPE html>\n<html><head><title>t</title></head><body>\n"
                '<main id="commentRoot">\n<h1>T</h1>\n' + _table(BIG) + "\n</main>\n"
                '<script type="text/plain" type="application/json" id="cmhColdTier">x</script>\n'
                "</body></html>\n")
        # A browser keeps the FIRST `type`, so this is NOT an inert JSON payload.
        self.assertEqual(cold_tier.state(html), "plain")

    def test_the_disqualifier_set_is_what_it_is_meant_to_be(self):
        # Pinned INDEPENDENTLY of the implementation: iterating the module's own set would delete
        # a case the moment someone deleted the entry it was meant to guard.
        self.assertEqual(cold_tier._DISQUALIFYING, frozenset((
            "h1", "h2", "h3", "h4", "h5", "h6", "script", "style", "canvas", "iframe",
            "template", "details", "summary", "svg", "object", "embed", "noscript",
            "link", "base", "meta", "table")))
        self.assertEqual(cold_tier._DISQUALIFYING_CLASSES,
                         frozenset(("mermaid", "chart", "cmh-chart")))
        self.assertEqual(cold_tier._DISQUALIFYING_ATTR_PREFIXES, ("data-cmh-chart", "on"))

    def test_every_disqualifying_tag_really_disqualifies(self):
        # The guard set is the anti-data-loss rule; a future edit dropping one entry would start
        # compressing an anchor target or a renderer hook silently.
        for tag in sorted(cold_tier._DISQUALIFYING):
            with self.subTest(tag=tag):
                markup = ("<%s>" % tag) if tag in ("link", "base", "meta", "embed") \
                    else "<%s></%s>" % (tag, tag)
                html = _doc("<h1>T</h1>\n"
                            + _table(BIG, extra_rows="\n    <tr><td>" + markup + "</td></tr>"))
                _out, changed = cold_tier.compress(html)
                self.assertFalse(changed, tag)

    def test_a_tail_row_holding_rich_content_disqualifies_the_table(self):
        for markup in ('<canvas class="cmh-chart"></canvas>',
                       '<pre class="mermaid">graph TD; a-->b;</pre>',
                       '<figure class="chart"><span>x</span></figure>',
                       '<span data-cmh-chart-points="1,2"></span>',
                       '<span onclick="void 0"></span>',
                       "<script>void 0;</script>",
                       "<style>a{}</style>",
                       "<iframe></iframe>",
                       "<svg></svg>",
                       "<object></object>",
                       "<embed>",
                       "<noscript>x</noscript>",
                       '<link rel="preconnect" href="https://example.test">',
                       '<base href="https://example.test/">',
                       '<meta name="x" content="y">',
                       "<details><summary>s</summary>x</details>",
                       "<template><i>x</i></template>",
                       "<table><tbody><tr><td>nested</td></tr></tbody></table>"):
            with self.subTest(markup=markup):
                html = _doc("<h1>T</h1>\n"
                            + _table(BIG, extra_rows="\n    <tr><td>" + markup + "</td></tr>"))
                _out, changed = cold_tier.compress(html)
                self.assertFalse(changed, markup)

    def test_a_nested_table_does_not_hide_a_disqualifying_element(self):
        # A single "current row" let the INNER row swallow every check, so a heading, a script or
        # a diagram nested one table deep was compressed anyway.
        for markup in ('<h3 id="deep">Deep</h3>', "<script>void 0;</script>",
                       '<div class="mermaid">graph TD; a-->b;</div>'):
            with self.subTest(markup=markup):
                nested = ("<table><tbody><tr><td>" + markup + "</td></tr></tbody></table>")
                html = _doc("<h1>T</h1>\n"
                            + _table(BIG, extra_rows="\n    <tr><td>" + nested + "</td></tr>"))
                out, changed = cold_tier.compress(html)
                self.assertFalse(changed, markup)
                self.assertIn(markup, out)

    def test_a_table_inside_a_template_is_never_compressed(self):
        # Its placeholder would live in `template.content`, which the loader cannot reach - so
        # hydration would fail for the WHOLE document, not just that table.
        html = _doc("<h1>T</h1>\n<template>\n" + _table(BIG) + "\n</template>")
        _out, changed = cold_tier.compress(html)
        self.assertFalse(changed)

    def test_non_whitespace_text_between_tail_rows_disqualifies_the_table(self):
        # A browser foster-parents such text out of the table, and the loader hands back only the
        # parsed tbody - so it would be silently dropped on hydration.
        html = _doc("<h1>T</h1>\n<table>\n  <tbody>\n"
                    + _rows(HALF) + "\n stray text \n" + _rows(BIG - HALF, start=HALF)
                    + "\n  </tbody>\n</table>")
        _out, changed = cold_tier.compress(html)
        self.assertFalse(changed)

    def test_a_comment_between_tail_rows_is_fine(self):
        html = _doc("<h1>T</h1>\n<table>\n  <tbody>\n"
                    + _rows(HALF) + "\n<!-- a note -->\n" + _rows(BIG - HALF, start=HALF)
                    + "\n  </tbody>\n</table>")
        out, changed = cold_tier.compress(html)
        self.assertTrue(changed)
        back, _ = cold_tier.expand(out)
        self.assertEqual(back, html)

    def test_a_table_outside_the_content_root_is_never_touched(self):
        html = ("<!DOCTYPE html>\n<html><head><title>t</title></head><body>\n"
                + _table(BIG) + '\n<main id="commentRoot">\n<p>only prose</p>\n</main>\n'
                "</body></html>\n")
        _out, changed = cold_tier.compress(html)
        self.assertFalse(changed)

    def test_a_document_with_no_content_root_is_left_entirely_alone(self):
        html = "<!DOCTYPE html>\n<html><body>\n" + _table(BIG) + "\n</body></html>\n"
        _out, changed = cold_tier.compress(html)
        self.assertFalse(changed)

    def test_an_implicitly_closed_row_refuses_the_whole_body(self):
        # Cutting at a guessed offset would cost content; refusing only costs bytes.
        rows = "\n".join("    <tr><td>r%d</td>" % i for i in range(BIG))
        html = _doc("<h1>T</h1>\n<table>\n  <tbody>\n" + rows + "\n  </tbody>\n</table>")
        _out, changed = cold_tier.compress(html)
        self.assertFalse(changed)

    def test_a_quoted_angle_bracket_does_not_confuse_the_scan(self):
        # The regex failure mode `vendored_libs.py` paid for: `[^>]*` stops inside the attribute.
        rows = "\n".join(
            '    <tr title="a > b"><td>r%d</td><td>x</td><td>y</td></tr>' % i for i in range(BIG))
        html = _doc("<h1>T</h1>\n<table>\n  <tbody>\n" + rows + "\n  </tbody>\n</table>")
        out, changed = cold_tier.compress(html)
        self.assertTrue(changed)
        back, _ = cold_tier.expand(out)
        self.assertEqual(back, html)


class SkeletonTests(unittest.TestCase):
    """The semantic skeleton is literal text in the raw file, always."""

    def test_headings_prose_caption_and_thead_stay_literal(self):
        html = _doc("<h1>Title</h1>\n<h2>Sub</h2>\n<p>Prose stays plain.</p>\n" + _table(BIG))
        out, _ = cold_tier.compress(html)
        for literal in ("<h1>Title</h1>", "<h2>Sub</h2>", "<p>Prose stays plain.</p>",
                        "<caption>Rows</caption>", "<th>a</th>"):
            self.assertIn(literal, out, literal)

    def test_the_first_rows_of_a_compressed_table_stay_literal(self):
        out, _ = cold_tier.compress(_big_doc(BIG))
        self.assertIn("<td>r0</td>", out)
        self.assertIn("<td>r%d</td>" % (KEEP - 1), out)
        self.assertNotIn("<td>r%d</td>" % KEEP, out)
        self.assertEqual(out.count("<tr><td>r"), cold_tier.DEFAULT_KEEP_ROWS)

    def test_the_compressed_text_is_recoverable_offline_with_the_standard_library_alone(self):
        # The documented reconstruction procedure: read the JSON, base64-decode, gunzip.
        out, _ = cold_tier.compress(_big_doc(BIG))
        part = _payload(out)["parts"][0]
        text = gzip.decompress(base64.b64decode(part["data"])).decode("utf-8")
        self.assertIn("<td>r%d</td>" % (BIG - 1), text)


class RoundTripTests(unittest.TestCase):
    def test_expanding_reproduces_the_original_bytes(self):
        for rows in (TEST_MIN + 1, TEST_MIN + TEST_KEEP, TEST_MIN * 2):
            self.assertGreater(rows, max(TEST_MIN, TEST_KEEP))
            with self.subTest(rows=rows):
                html = _big_doc(rows)
                out, changed = _compress(html)
                self.assertTrue(changed)
                back, expanded = cold_tier.expand(out)
                self.assertTrue(expanded)
                self.assertEqual(back, html)

    def test_the_whitespace_between_rows_survives(self):
        html = _doc("<h1>T</h1>\n<table>\n<tbody>\n"
                    + "\n\n".join("<tr><td>r%d</td></tr>" % i for i in range(TEST_BIG))
                    + "\n</tbody>\n</table>")
        out, _ = _compress(html)
        back, _ = cold_tier.expand(out)
        self.assertEqual(back, html)

    def test_a_unicode_cell_survives_the_round_trip(self):
        rows = "\n".join(
            "    <tr><td>r%d</td><td>caf\u00e9 \u4e2d\u6587 \U0001f680</td></tr>" % i
            for i in range(TEST_BIG))
        html = _doc("<h1>T</h1>\n<table>\n  <tbody>\n" + rows + "\n  </tbody>\n</table>")
        out, changed = _compress(html)
        self.assertTrue(changed)
        back, _ = cold_tier.expand(out)
        self.assertEqual(back, html)

    def test_compressing_an_already_compressed_document_is_a_no_op(self):
        out, _ = _compress(_big_doc(TEST_BIG))
        again, changed = _compress(out)
        self.assertFalse(changed)
        self.assertEqual(again, out)

    def test_expanding_a_plain_document_is_a_no_op(self):
        html = _big_doc(TEST_BIG)
        out, changed = cold_tier.expand(html)
        self.assertFalse(changed)
        self.assertEqual(out, html)

    def test_compression_is_deterministic(self):
        html = _big_doc(TEST_BIG)
        first, _ = _compress(html)
        second, _ = _compress(html)
        self.assertEqual(first, second, "a timestamped payload would churn every finalize")


class PayloadTests(unittest.TestCase):
    def test_the_payload_is_one_inert_script_after_the_content(self):
        out, _ = _compress(_big_doc(TEST_BIG))
        self.assertEqual(out.count('id="cmhColdTier"'), 1)
        self.assertIn('<script type="application/json" id="cmhColdTier">', out)
        self.assertGreater(out.index("cmhColdTier"), out.index("</main>"))
        self.assertLess(out.index("cmhColdTier"), out.index("</body>"))

    def test_the_payload_precedes_the_layer_script_that_reads_it(self):
        """The bug that made the whole feature a silent no-op.

        The layer is an inline classic script the browser runs DURING PARSE, so a payload placed
        just before `</body>` - where `vendored_libs.py` correctly puts its own, because that one
        is read at CLICK time - simply does not exist yet when the loader looks for it. Every
        compressed document would have rendered a truncated table with no error anywhere.
        """
        with open(_paths.TEMPLATE, "r", encoding="utf-8", newline="") as fh:
            template = fh.read()
        content = ("<h1>Cold tier</h1>\n<p>Prose.</p>\n" + _table(TEST_BIG))
        doc = new_document.make_document(template, content, "cold-order-test", "Cold order test",
                                         source="cold.html", kind="report")
        out, changed = _compress(doc)
        self.assertTrue(changed)
        payload_at = out.index('id="cmhColdTier"')
        layer_at = out.index("__commentableHtmlReady")
        self.assertLess(payload_at, layer_at,
                        "the payload must be parsed before the script that inflates it")
        self.assertGreater(payload_at, out.index("</main>"))

    def test_the_payload_is_fenced_as_skippable_machinery(self):
        out, _ = _compress(_big_doc(TEST_BIG))
        self.assertIn(cold_tier.FENCE_OPEN, out)
        self.assertIn(cold_tier.FENCE_CLOSE, out)
        self.assertIn("safe to skip", cold_tier.FENCE_OPEN)
        self.assertLess(out.index(cold_tier.FENCE_OPEN), out.index("cmhColdTier"))
        self.assertGreater(out.index(cold_tier.FENCE_CLOSE), out.index("cmhColdTier"))

    def test_the_payload_carries_no_executable_script_and_no_url(self):
        out, _ = _compress(_big_doc(TEST_BIG))
        payload = _payload(out)
        self.assertEqual(payload["v"], cold_tier.PAYLOAD_VERSION)
        for part in payload["parts"]:
            self.assertEqual(part["enc"], "gzip+base64")
            self.assertRegex(part["data"], r"^[A-Za-z0-9+/=]+$")

    def test_an_authored_payload_inside_the_content_is_not_the_infrastructure_one(self):
        # A document that DOCUMENTS this feature may show the element as an example. Treating
        # that as the payload is the data-loss shape `vendored_libs.py` was bitten by twice.
        html = _doc('<h1>T</h1>\n<p>Example:</p>\n'
                    '<script type="application/json" id="cmhColdTier">{"v":1,"parts":[]}</script>\n'
                    + _table(TEST_BIG))
        self.assertEqual(cold_tier.state(html), "plain")
        out, changed = _compress(html)
        self.assertTrue(changed)
        self.assertIn('<p>Example:</p>', out)
        self.assertEqual(out.count('id="cmhColdTier"'), 2)
        back, _ = cold_tier.expand(out)
        self.assertEqual(back, html)

    def test_a_payload_script_of_another_type_is_not_the_infrastructure_one(self):
        # The runtime requires the inert JSON type before it trusts a payload; without the same
        # test here the two sides disagree about what the payload IS, and an authored example
        # outside the content root would silently disable compression for the document.
        html = ("<!DOCTYPE html>\n<html><head><title>t</title></head><body>\n"
                '<main id="commentRoot">\n<h1>T</h1>\n' + _table(TEST_BIG) + "\n</main>\n"
                '<script type="text/plain" id="cmhColdTier">not the payload</script>\n'
                "</body></html>\n")
        self.assertEqual(cold_tier.state(html), "plain")
        _out, changed = _compress(html)
        self.assertTrue(changed)

    def test_the_payload_cannot_close_its_own_script_element(self):
        with self.assertRaises(ValueError):
            cold_tier._payload_script([{"id": "x</script>", "enc": "gzip+base64", "data": ""}])

    def test_the_document_stays_a_single_self_contained_file(self):
        out, _ = _compress(_big_doc(TEST_BIG))
        span = cold_tier.find_blob(out)
        self.assertNotIn("src=", out[span[0]:span[1]])
        self.assertNotIn("http", out[span[0]:span[1]])


class NoscriptTests(unittest.TestCase):
    def test_the_placeholder_explains_itself_without_scripting(self):
        out, _ = _compress(_big_doc(TEST_BIG))
        slot = re.search(r"<tr class=\"cmh-cold-slot[^\"]*\"[\s\S]*?</tr>", out).group(0)
        self.assertIn("<noscript>", slot)
        self.assertIn("stored compressed", slot)
        self.assertIn("scripting is enabled", slot)
        self.assertIn("No network access is needed", slot)

    def test_the_note_is_hidden_by_this_versions_stylesheet_not_by_an_attribute(self):
        # An OLDER runtime carries neither the loader nor this rule, so it must SHOW the note
        # rather than render an unexplained empty row - which a `hidden` attribute would have done.
        out, _ = _compress(_big_doc(TEST_BIG))
        slot = re.search(r"<tr class=\"cmh-cold-slot[^\"]*\"[\s\S]*?</tr>", out).group(0)
        self.assertIn('<span class="cmh-cold-note">', slot)
        self.assertNotIn('class="cmh-cold-note" hidden', slot)
        self.assertIn("not expanded", slot)
        css = _read(os.path.join(_paths.ASSETS, "css", "51-cold-tier.css"))
        self.assertIn("#commentRoot .cmh-cold-note { display: none; }", css)
        self.assertIn('note.style.display = "inline"', _read(LOADER))

    def test_the_placeholder_spans_the_full_table_width(self):
        out, _ = _compress(_big_doc(TEST_BIG))
        self.assertIn('<td colspan="3">', out)


class FailureShapeTests(unittest.TestCase):
    """A payload that cannot be put back must FAIL LOUDLY, never read as "already plain".

    Silence is the dangerous answer here: `finalize` would go on to validate and stamp a document
    whose hidden rows can no longer be recovered from it, and nothing on screen or in any log would
    say so.
    """

    def _broken(self, mutate):
        out, _ = _compress(_big_doc(TEST_BIG))
        return mutate(out)

    def test_a_compression_bomb_is_refused_before_it_is_materialized(self):
        # `gzip.decompress` builds the WHOLE member before anything can check its size, so a small
        # bomb would exhaust the authoring process instead of raising. Every consumer - validate,
        # finalize, the section hash, the edit loop - runs this on documents from elsewhere.
        bomb = gzip.compress(b"\0" * (cold_tier.MAX_EXPANDED_BYTES + 1))
        self.assertLess(len(bomb), 200000, "the probe must be small relative to what it expands to")
        with self.assertRaises(ValueError):
            cold_tier._bounded_gunzip(bomb, cold_tier.MAX_EXPANDED_BYTES)
        # A legitimate payload of the same shape still round-trips.
        payload = b"<tr><td>ok</td></tr>" * 1000
        self.assertEqual(
            cold_tier._bounded_gunzip(gzip.compress(payload), cold_tier.MAX_EXPANDED_BYTES),
            payload)

    def test_the_expand_budget_is_spent_across_the_whole_payload(self):
        src = _read(os.path.join(_paths.TOOLS, "authoring", "cold_tier.py"))
        body = src[src.index("def expand("):]
        self.assertIn("budget = MAX_EXPANDED_BYTES", body)
        self.assertIn("budget -= len(raw)", body)

    def test_a_corrupt_payload_raises(self):
        broken = self._broken(lambda out: re.sub(
            r'"data":"[A-Za-z0-9+/=]{20}', '"data":"AAAAAAAAAAAAAAAAAAAA', out, count=1))
        with self.assertRaises(cold_tier.ColdTierError):
            cold_tier.expand(broken)

    def test_a_payload_with_no_matching_placeholder_raises(self):
        # Exactly what an agent editing that table does: the placeholder goes, the payload stays.
        orphaned = self._broken(lambda out: re.sub(
            r"<tr class=\"cmh-cold-slot[\s\S]*?</tr>", "", out, count=1))
        with self.assertRaises(cold_tier.ColdTierError):
            cold_tier.expand(orphaned)

    def test_an_unknown_payload_version_raises(self):
        future = self._broken(lambda out: out.replace('"v":1', '"v":99'))
        with self.assertRaises(cold_tier.ColdTierError):
            cold_tier.expand(future)

    def test_malformed_json_raises(self):
        broken = self._broken(lambda out: out.replace('{"parts"', '{"parts"broken', 1))
        with self.assertRaises(cold_tier.ColdTierError):
            cold_tier.expand(broken)

    def test_a_duplicated_section_id_raises(self):
        out, _ = _compress(_big_doc(TEST_BIG))
        part = re.search(r'\{"data":"[^"]+","enc":"gzip\+base64","id":"cmh-cold-1","rows":\d+\}', out)
        self.assertIsNotNone(part)
        doubled = out.replace(part.group(0), part.group(0) + "," + part.group(0), 1)
        with self.assertRaises(cold_tier.ColdTierError):
            cold_tier.expand(doubled)

    def test_a_duplicate_placeholder_raises(self):
        out, _ = _compress(_big_doc(TEST_BIG))
        slot = re.search(r"<tr class=\"cmh-cold-slot[\s\S]*?</tr>", out).group(0)
        with self.assertRaises(cold_tier.ColdTierError):
            cold_tier.expand(out.replace(slot, slot + slot, 1))

    def test_a_placeholder_the_block_does_not_name_raises(self):
        out, _ = _compress(_big_doc(TEST_BIG))
        slot = re.search(r"<tr class=\"cmh-cold-slot[\s\S]*?</tr>", out).group(0)
        extra = slot.replace('"cmh-cold-1"', '"cmh-cold-7"')
        with self.assertRaises(cold_tier.ColdTierError):
            cold_tier.expand(out.replace(slot, slot + extra, 1))

    def test_two_payload_blocks_raise_rather_than_stripping_both(self):
        out, _ = _compress(_big_doc(TEST_BIG))
        span = cold_tier.find_blob(out)
        doubled = out[:span[1]] + out[span[0]:span[1]] + out[span[1]:]
        with self.assertRaises(cold_tier.ColdTierError):
            cold_tier.expand(doubled)

    def test_a_document_that_already_has_a_placeholder_is_never_recompressed(self):
        # A generated id landing on top of a stale placeholder would make `expand` restore the
        # wrong rows into it.
        out, _ = _compress(_big_doc(TEST_BIG))
        stripped, _ = cold_tier._strip_blob(out)
        again, changed = _compress(stripped)
        self.assertFalse(changed)


class RuntimeWiringTests(unittest.TestCase):
    """The loader runs FIRST, and the tool and the runtime agree on the vocabulary."""

    def test_the_preamble_hydrates_before_it_snapshots(self):
        src = _read(PREAMBLE)
        self.assertIn("cmhHydrateColdTier()", src)
        self.assertLess(src.index("cmhHydrateColdTier()"), src.index("SNAPSHOT_HTML ="),
                        "hydration must precede the export snapshot, or an export loses rows")

    def test_the_hydration_state_is_declared_with_var(self):
        # It is assigned above every module-level `const`, so a `let`/`const` would be in its
        # temporal dead zone and the whole layer would fail to boot.
        self.assertRegex(_read(PREAMBLE), r"\bvar CMH_COLD_TIER = cmhHydrateColdTier\(\);")

    def test_startup_surfaces_a_failure_as_a_non_blocking_diagnostic(self):
        src = _read(STARTUP)
        self.assertIn("CMH_COLD_TIER", src)
        self.assertIn("showStartupDiagnostic", src)

    def test_the_loader_and_the_tool_agree_on_the_marker_vocabulary(self):
        src = _read(LOADER)
        self.assertIn(cold_tier.BLOB_ID, src)
        self.assertIn(cold_tier.SLOT_CLASS, src)
        self.assertIn(cold_tier.PART_ATTR, src)
        self.assertIn("application/json", src)
        self.assertIn("commentable-html - COLD TIER", src)
        self.assertIn("commentable-html - COLD TIER", cold_tier.FENCE_OPEN)

    def test_the_loader_never_lets_an_exception_escape(self):
        src = _read(LOADER)
        entry = src[src.index("function cmhHydrateColdTier"):]
        self.assertIn("try {", entry)
        self.assertIn("catch (e)", entry)
        self.assertNotIn("throw ", entry)

    def test_the_loader_is_hoisting_safe(self):
        # Everything the entry point touches at call time must be a hoisted declaration or a
        # function-local; a module-level const/let here would be a load-time ReferenceError.
        src = _read(LOADER)
        top_level = [line for line in src.split("\n")
                     if line.startswith("const ") or line.startswith("let ")]
        self.assertEqual(top_level, [])

    def test_the_loader_parses_restored_rows_in_table_context(self):
        # A plain host element foster-parents `<tr>` out of existence, which would silently drop
        # every compressed row while reporting success.
        self.assertIn("<table><tbody>", _read(LOADER))

    def test_the_loader_decodes_everything_before_it_mutates_the_dom(self):
        src = _read(LOADER)
        body = src[src.index("function _cmhColdHydrate"):]
        self.assertLess(body.index("restored.push"), body.index("parent.insertBefore"))

    def test_the_loader_never_builds_a_selector_from_a_payload_id(self):
        # A selector built from a corrupt id throws a SyntaxError, and this code is the layer's
        # FIRST statement - a throw there takes the whole review layer down, not just the tier.
        src = _read(LOADER)
        self.assertNotIn('data-cmh-cold-part="' + "'", src)
        self.assertNotIn("part.id +", src)
        self.assertNotIn("+ part.id", src)
        self.assertIn("_cmhColdSlotMap", src)
        self.assertIn('getAttribute("data-cmh-cold-part")', src)

    def test_the_loader_pins_the_same_part_id_shape_as_the_tool(self):
        self.assertIn("/^cmh-cold-[0-9]+$/", _read(LOADER))
        self.assertEqual(cold_tier.PART_ID_RE.pattern, "^cmh-cold-[0-9]+$")

    def test_the_loader_bounds_what_a_payload_may_inflate_to(self):
        src = _read(LOADER)
        self.assertIn("_cmhColdMaxBytes", src)
        self.assertIn("expanded content is too large", src)

    def test_the_inflate_budget_is_spent_across_the_whole_payload(self):
        # Every decoded fragment is retained until the last part validates, so a PER-PART cap
        # would still let many individually-legal parts add up to many multiples of it.
        src = _read(LOADER)
        body = src[src.index("function _cmhColdHydrate"):]
        self.assertIn("var budget = _cmhColdMaxBytes();", body)
        self.assertIn("budget -= raw.length;", body)
        self.assertLess(body.index("var budget"), body.index("budget -= raw.length;"))

    def test_the_loader_scopes_slot_discovery_to_the_content_root(self):
        # The producer only ever records a slot it saw INSIDE the content root, so a document-wide
        # sweep here would count an authored example row too, fail the bijection check, and hide
        # the real rows behind a failure notice.
        src = _read(LOADER)
        body = src[src.index("function _cmhColdSlots"):src.index("function _cmhColdSlotMap")]
        self.assertIn('getElementById("commentRoot")', body)
        self.assertIn("root.querySelectorAll", body)
        self.assertNotIn("document.querySelectorAll", body)

    def test_the_loader_resolves_the_payload_past_an_authored_decoy(self):
        # `getElementById` binds the FIRST element with the id, which an authored example inside
        # the content root would be - and the loader would then report "no cold tier" and silently
        # leave every row missing.
        src = _read(LOADER)
        self.assertIn('querySelectorAll("script#cmhColdTier")', src)
        self.assertNotIn('getElementById("cmhColdTier")', src)

    def test_a_missing_payload_with_a_surviving_placeholder_is_reported(self):
        src = _read(LOADER)
        self.assertIn("this file's compressed block is missing", src)

    def test_the_loader_documents_why_decompressionstream_is_not_used(self):
        src = _read(LOADER)
        self.assertIn("DecompressionStream", src)
        self.assertNotIn("new DecompressionStream", src)

    def test_the_loader_ships_in_the_built_layer(self):
        built = _read(os.path.join(_paths.DIST, "commentable-html.js"))
        self.assertIn("cmhHydrateColdTier", built)

    def test_an_export_never_starts_from_the_still_compressed_bytes_on_disk(self):
        """`_getBaseHtml` prefers `fetch(location.href)`, which returns the file AS STORED.

        On an http(s)-hosted document that is the compressed source: a Plain export would ship
        placeholder rows with no loader left to expand them, and the offline resource strips would
        run over rows they cannot see. The snapshot is captured after hydration, so it is already
        the fully-plain document.
        """
        src = _read(os.path.join(_paths.ASSETS, "js", "65-export-shareable.js"))
        body = src[src.index("async function _getBaseHtml"):]
        body = body[:body.index("\nfunction ")]
        self.assertIn("CMH_COLD_TIER", body)
        self.assertLess(body.index("CMH_COLD_TIER"), body.index("fetch(location.href"),
                        "the cold-tier bail-out must run BEFORE the fetch it is bailing out of")


class InflateTests(unittest.TestCase):
    """The inlined decoder is the only decoder, so it has to be right (CMH-COLD-05)."""

    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which("node")

    def _run(self, script):
        if not self.node:
            self.skipTest("node is not on PATH")
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "probe.mjs")
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(script)
            proc = subprocess.run([self.node, path], capture_output=True, text=True, timeout=300)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return proc.stdout.strip()

    def _harness(self, body):
        loader = LOADER.replace("\\", "\\\\")
        return (
            'import fs from "node:fs";\nimport zlib from "node:zlib";\n'
            'const src = fs.readFileSync("%s", "utf8");\n'
            'const api = new Function(src + "\\nreturn { gunzip: _cmhColdGunzip, '
            'b64: _cmhColdBase64, utf8: _cmhColdUtf8 };")();\n' % loader) + body

    def test_it_matches_zlib_on_every_deflate_block_type(self):
        out = self._run(self._harness(
            'const cases = [["empty", "", 9], ["short", "hi", 9],\n'
            '  ["stored", "abc", 0],\n'
            '  ["fixed", "<tr><td>x</td></tr>", 9],\n'
            '  ["dynamic", "<tr><td>x</td></tr>\\n".repeat(5000), 9],\n'
            '  ["unicode", "caf\\u00e9 \\u4e2d\\u6587 \\ud83d\\ude80 ".repeat(2000), 9]];\n'
            'for (const [name, text, level] of cases) {\n'
            '  const b64 = zlib.gzipSync(Buffer.from(text, "utf8"), { level }).toString("base64");\n'
            '  const got = api.utf8(api.gunzip(api.b64(b64)));\n'
            '  console.log(name + ":" + (got === text));\n}\n'))
        for line in out.splitlines():
            self.assertTrue(line.endswith(":true"), line)

    def test_it_rejects_a_corrupt_or_truncated_payload_instead_of_returning_garbage(self):
        out = self._run(self._harness(
            'function threw(bytes) { try { api.gunzip(bytes); return false; } catch (e) { return true; } }\n'
            'const gz = zlib.gzipSync(Buffer.from("hello world hello world", "utf8"));\n'
            'const badCrc = Uint8Array.from(gz); badCrc[badCrc.length - 5] ^= 0xff;\n'
            'const badSize = Uint8Array.from(gz); badSize[badSize.length - 1] ^= 0xff;\n'
            'const truncated = Uint8Array.from(gz.subarray(0, gz.length - 6));\n'
            'const notGzip = Uint8Array.from(Buffer.from("not a gzip payload at all really"));\n'
            'const corruptBody = Uint8Array.from(gz); corruptBody[14] ^= 0xff;\n'
            'console.log("crc:" + threw(badCrc));\n'
            'console.log("size:" + threw(badSize));\n'
            'console.log("truncated:" + threw(truncated));\n'
            'console.log("notgzip:" + threw(notGzip));\n'
            'console.log("body:" + threw(corruptBody));\n'
            'console.log("intact:" + (api.utf8(api.gunzip(Uint8Array.from(gz))) === "hello world hello world"));\n'))
        for line in out.splitlines():
            self.assertTrue(line.endswith(":true"), line)

    def test_it_rejects_an_oversized_or_trailing_payload(self):
        # The bomb guard and the trailing-data check, exercised as CODE rather than asserted as a
        # source string: a hostile ISIZE must be refused before a byte is inflated.
        out = self._run(self._harness(
            'function threw(bytes) { try { api.gunzip(bytes); return false; } catch (e) { return true; } }\n'
            'const gz = zlib.gzipSync(Buffer.from("hello world hello world", "utf8"));\n'
            'const huge = Uint8Array.from(gz);\n'
            'huge[huge.length - 4] = 0; huge[huge.length - 3] = 0;\n'
            'huge[huge.length - 2] = 0; huge[huge.length - 1] = 0x40;\n'
            'const trailing = new Uint8Array(gz.length + 3); trailing.set(gz);\n'
            'console.log("oversize:" + threw(huge));\n'
            'console.log("trailing:" + threw(trailing));\n'
            'console.log("intact:" + (api.utf8(api.gunzip(Uint8Array.from(gz))) '
            '=== "hello world hello world"));\n'))
        for line in out.splitlines():
            self.assertTrue(line.endswith(":true"), line)

    def test_it_expands_a_real_payload_this_tool_produced(self):
        rows = TEST_BIG
        compressed, _ = _compress(_big_doc(rows))
        data = _payload(compressed)["parts"][0]["data"]
        out = self._run(self._harness(
            'const text = api.utf8(api.gunzip(api.b64(%s)));\n'
            'console.log("rows:" + (text.match(/<tr>/g) || []).length);\n'
            'console.log("last:" + text.includes("<td>r%d</td>"));\n'
            % (json.dumps(data), rows - 1)))
        self.assertIn("rows:%d" % (rows - TEST_KEEP), out)
        self.assertIn("last:true", out)


class FinalizeWiringTests(unittest.TestCase):
    """How the tier is wired INTO finalize - a property of the pipeline, not of the thresholds.

    These cases run against a small document with `cold_tier.compress` bound to explicit small
    thresholds, so the wiring is exercised without paying for a body over the shipped `min_rows` in
    every one of them: at 4000 that cost was 199 s of this module's runtime. The shipped thresholds
    really flowing through finalize is a separate claim, proved once by
    `ShippedThresholdPipelineTests` below on a real over-threshold document with nothing patched.
    """

    @classmethod
    def setUpClass(cls):
        content = ('<h1>Cold tier</h1>\n<p>Prose stays plain.</p>\n'
                   '<h2 id="rows">Rows</h2>\n' + _table(TEST_BIG))
        cls.document = new_document.make_document(
            _read(_paths.TEMPLATE), content, "cold-tier-test", "Cold tier test",
            source="cold.html", kind="report")

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cmh_cold_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        real_compress = cold_tier.compress
        cold_tier.compress = lambda html, **kw: real_compress(
            html, **dict({"min_rows": TEST_MIN, "keep_rows": TEST_KEEP}, **kw))
        self.addCleanup(setattr, cold_tier, "compress", real_compress)
        self.doc = self.document
        self.path = os.path.join(self.tmp, "doc.html")
        with open(self.path, "w", encoding="utf-8", newline="") as fh:
            fh.write(self.doc)

    def _finalize(self, **kwargs):
        result = finalize.finalize(self.path, run_stats=False, run_normalize=False, **kwargs)
        return _read(self.path), result

    def test_the_default_emits_the_fully_plain_structure(self):
        html, result = self._finalize()
        self.assertEqual(cold_tier.state(html), "plain")
        self.assertNotIn("cold-tier", [name for name, _ in result["steps"]])

    def test_the_flag_compresses(self):
        html, result = self._finalize(cold_tier_enabled=True)
        self.assertEqual(cold_tier.state(html), "compressed")
        self.assertIn(("cold-tier", "compressed"), result["steps"])

    def test_the_flag_off_expands_a_document_that_already_carries_a_tier(self):
        self._finalize(cold_tier_enabled=True)
        html, result = self._finalize()
        self.assertEqual(cold_tier.state(html), "plain")
        self.assertIn(("cold-tier", "expanded"), result["steps"])
        self.assertIn(TEST_LAST_ROW, html)

    def test_repeated_finalize_settles(self):
        first, _ = self._finalize(cold_tier_enabled=True)
        second, _ = self._finalize(cold_tier_enabled=True)
        self.assertEqual(first, second)

    def test_a_compressed_document_validates_clean(self):
        html, _ = self._finalize(cold_tier_enabled=True)
        errors, warnings = validate.validate(self.path, html=html)
        self.assertEqual(errors, [])
        _fatal, advisory = validate.partition_warnings(warnings)
        self.assertEqual([w for w in warnings if w not in advisory], [])

    def test_the_validator_sees_what_is_inside_the_payload(self):
        """A hidden row must not be able to smuggle anything past a source-scanning check.

        Validation used to run on the COMPRESSED document, so the tail rows were base64 by the
        time any check looked. The probe has to be something that is BOTH eligible for compression
        (an `<img src>` is; a `<link rel="preconnect">` is refused outright by the disqualifier
        set) and reported as an error, or the test passes for the wrong reason.
        """
        plain = self.doc.replace(
            TEST_LAST_ROW, TEST_LAST_ROW.replace("</td>", '<img src="https://example.test/x.png"></td>'), 1)
        loud, _ = validate.validate(self.path, html=plain)
        self.assertTrue(loud, "the probe must trip a real check on the plain document")
        compressed, changed = cold_tier.compress(plain)
        self.assertTrue(changed, "the probe must actually end up inside the payload")
        self.assertNotIn("example.test", compressed)
        quiet, _ = validate.validate(self.path, html=compressed)
        self.assertEqual(quiet, loud,
                         "the compressed document must be validated as its expanded self")

    def test_stamping_never_changes_the_tier_on_disk(self):
        """The stamp writer must not rewrite a compressed file in plain form.

        Stamping the document AS STORED is what keeps the tier: expanding and re-compressing here
        would re-tier a document with this build's default thresholds, and when stamping is a no-op
        (a same-second re-run) it wrote the expanded form over the compressed file outright.
        """
        self._finalize(cold_tier_enabled=True, stamp_when_clean=True)
        before = _read(self.path)
        self.assertEqual(cold_tier.state(before), "compressed")
        for _ in range(2):
            validate._stamp_validated_file(self.path)
            after = _read(self.path)
            self.assertEqual(cold_tier.state(after), "compressed")
            self.assertNotIn(TEST_LAST_ROW, after, "the tier must not be expanded on disk")
        strip = lambda text: re.sub(r'<meta name="commentable-html-validated"[^>]*>', "", text)
        self.assertEqual(strip(cold_tier.expanded_view(after)),
                         strip(cold_tier.expanded_view(before)))

    def test_the_content_hash_is_the_same_compressed_or_plain(self):
        # The single hashing entry point expands, so the validated stamp and every review marker
        # reproduce what the runtime computes after hydration.
        plain, _ = self._finalize()
        compressed, changed = cold_tier.compress(plain)
        self.assertTrue(changed)
        self.assertEqual(section_hash.document_content_hash(compressed),
                         section_hash.document_content_hash(plain))

    def test_an_orphaned_placeholder_is_refused_too(self):
        # The mirror of an orphaned payload: the block is gone and the markers remain. Reading
        # that as "already plain" would let finalize stamp a truncated document as valid.
        compressed, _ = self._finalize(cold_tier_enabled=True)
        span = cold_tier.find_blob(compressed)
        orphaned = compressed[:span[0]] + compressed[span[1]:]
        with self.assertRaises(cold_tier.ColdTierError):
            cold_tier.expand(orphaned)

    def test_marking_a_section_reviewed_hashes_the_rows_the_reader_sees(self):
        """`mark_reviewed` bakes a hash the browser must be able to reproduce.

        The placeholder is `cm-skip`, so hashing the compressed source omitted the cold rows and
        every such section opened as "changed".
        """
        plain, _ = self._finalize()
        with open(self.path, "w", encoding="utf-8", newline="") as fh:
            fh.write(plain)
        sections = section_hash.extract_sections(plain)
        self.assertTrue(sections)
        target = sections[0]["id"]
        mark_reviewed.mark_reviewed(self.path, [target], [])
        plain_hash = json.loads(re.search(
            r'id="reviewedSections"[^>]*>([\s\S]*?)</script>', _read(self.path)).group(1))
        compressed, _ = self._finalize(cold_tier_enabled=True)
        mark_reviewed.mark_reviewed(self.path, [target], [])
        after = _read(self.path)
        self.assertEqual(cold_tier.state(after), "compressed", "the tier must survive marking")
        compressed_hash = json.loads(re.search(
            r'id="reviewedSections"[^>]*>([\s\S]*?)</script>', after).group(1))
        self.assertEqual(compressed_hash[target]["hash"], plain_hash[target]["hash"])

    def test_an_embedded_comment_survives_compression_untouched(self):
        # The acceptance criterion is zero data loss for existing threads: compression must not
        # move a byte of the embedded state, and its anchor offsets must still be the plain ones.
        plain, _ = self._finalize()
        block = re.search(r'id="embeddedComments"[^>]*>([\s\S]*?)</script>', plain)
        self.assertIsNotNone(block)
        compressed, _ = cold_tier.compress(plain)
        self.assertEqual(
            re.search(r'id="embeddedComments"[^>]*>([\s\S]*?)</script>', compressed).group(1),
            block.group(1))
        self.assertEqual(cold_tier.expanded_view(compressed), plain)

    def test_the_validator_fails_closed_on_a_tier_it_cannot_expand(self):
        html, _ = self._finalize(cold_tier_enabled=True)
        broken = re.sub(r'"data":"[A-Za-z0-9+/=]{20}', '"data":"AAAAAAAAAAAAAAAAAAAA', html,
                        count=1)
        errors, _warnings = validate.validate(self.path, html=broken)
        self.assertTrue(any("cold-tier" in e for e in errors), errors)

    def test_the_stamp_binds_to_the_rows_the_reader_will_see(self):
        """The content hash must match what the browser hashes AFTER hydration.

        Binding it to the placeholder would leave every compressed document opening with the
        "not validated" banner - a reviewed-section and validation state regression.
        """
        compressed, result = self._finalize(cold_tier_enabled=True, stamp_when_clean=True)
        self.assertTrue(result["stamped"], result["errors"] + result["warnings"])
        expanded = cold_tier.expanded_view(compressed)
        plain, _ = self._finalize(stamp_when_clean=True)
        self.assertEqual(
            re.search(r'commentable-html-validated-hash" content="([^"]*)"', expanded).group(1),
            re.search(r'commentable-html-validated-hash" content="([^"]*)"', plain).group(1))

    def test_finalize_refuses_a_document_whose_payload_is_orphaned(self):
        compressed, _ = self._finalize(cold_tier_enabled=True)
        orphaned = re.sub(r"<tr class=\"cmh-cold-slot[\s\S]*?</tr>", "", compressed, count=1)
        with open(self.path, "w", encoding="utf-8", newline="") as fh:
            fh.write(orphaned)
        with self.assertRaises(cold_tier.ColdTierError):
            self._finalize()
        with open(self.path, "r", encoding="utf-8", newline="") as fh:
            self.assertEqual(fh.read(), orphaned, "a refused finalize must not write")

    def test_the_agent_edit_loop_hands_back_every_row(self):
        """`content_extract` must expand first, or the agent edits a table it cannot fully see."""
        compressed, _ = self._finalize(cold_tier_enabled=True)
        with open(self.path, "r", encoding="utf-8", newline="") as fh:
            fragment = content_extract.extract(fh.read())
        self.assertIn(TEST_LAST_ROW, fragment)
        self.assertNotIn("cmh-cold-slot", fragment)

    def test_replacing_the_content_of_a_compressed_document_keeps_its_rows_and_its_tier(self):
        self._finalize(cold_tier_enabled=True)
        with open(self.path, "r", encoding="utf-8", newline="") as fh:
            fragment = content_extract.extract(fh.read())
        final = content_replace.replace(self.path, fragment.replace("<h1>Cold tier</h1>",
                                                                   "<h1>Cold tier edited</h1>"))
        self.assertIn("<h1>Cold tier edited</h1>", final)
        # The edit loop must not silently un-compress the document, and must not lose a row.
        self.assertEqual(cold_tier.state(final), "compressed")
        self.assertIn(TEST_LAST_ROW, cold_tier.expanded_view(final))

    def test_replacing_the_content_of_a_plain_document_leaves_it_plain(self):
        plain, _ = self._finalize()
        with open(self.path, "r", encoding="utf-8", newline="") as fh:
            fragment = content_extract.extract(fh.read())
        final = content_replace.replace(self.path, fragment.replace("<h1>Cold tier</h1>",
                                                                    "<h1>Still plain</h1>"))
        self.assertEqual(cold_tier.state(final), "plain")
        self.assertIn(TEST_LAST_ROW, final)

class ShippedThresholdPipelineTests(unittest.TestCase):
    """The SHIPPED thresholds really flow through the pipeline, on a real over-threshold body.

    `FinalizeWiringTests` binds small explicit thresholds so the wiring cases do not each pay
    for a body over `min_rows`; that makes this the one place the shipped defaults themselves
    are exercised end to end. It runs the CLI in a SUBPROCESS, which reads the defaults from the
    module rather than from anything this test could patch - so it is also the case that would
    catch a default the pipeline cannot actually use.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cmh_cold_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        content = ('<h1>Cold tier</h1>\n<p>Prose stays plain.</p>\n'
                   '<h2 id="rows">Rows</h2>\n' + _table(BIG))
        doc = new_document.make_document(
            _read(_paths.TEMPLATE), content, "cold-tier-shipped", "Cold tier shipped",
            source="cold.html", kind="report")
        self.path = os.path.join(self.tmp, "doc.html")
        with open(self.path, "w", encoding="utf-8", newline="") as fh:
            fh.write(doc)

    def test_the_cli_reports_and_round_trips(self):
        env = dict(os.environ)
        env["PYTHONPATH"] = _paths.TOOLS + os.pathsep + env.get("PYTHONPATH", "")
        tool = os.path.join(_paths.TOOLS, "authoring", "cold_tier.py")
        before = _read(self.path)
        check = subprocess.run([sys.executable, tool, self.path, "--check"],
                               capture_output=True, text=True, env=env, timeout=300)
        self.assertEqual(check.returncode, 0, check.stderr)
        self.assertIn("state=plain", check.stdout)
        run = subprocess.run([sys.executable, tool, self.path],
                             capture_output=True, text=True, env=env, timeout=300)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(cold_tier.state(_read(self.path)), "compressed")
        back = subprocess.run([sys.executable, tool, self.path, "--expand"],
                              capture_output=True, text=True, env=env, timeout=300)
        self.assertEqual(back.returncode, 0, back.stderr)
        self.assertEqual(_read(self.path), before)

    def test_finalize_compresses_at_the_shipped_defaults(self):
        result = finalize.finalize(self.path, run_stats=False, run_normalize=False,
                                   cold_tier_enabled=True)
        html = _read(self.path)
        self.assertEqual(cold_tier.state(html), "compressed")
        self.assertIn(("cold-tier", "compressed"), result["steps"])
        self.assertIn(LAST_ROW, cold_tier.expanded_view(html))
        self.assertNotIn(LAST_ROW, html)



class SpecFixtureTests(unittest.TestCase):
    """The browser spec builds its own compressed document; keep it honest.

    `tests/85-cold-tier.spec.js` constructs the payload with node's zlib rather than shelling out
    to this tool, so nothing in the browser job depends on a Python interpreter. The cost is that
    the fixture could drift from the real emitter and quietly test a format nobody ships - so pin
    every marker the two sides have to agree on.
    """

    def setUp(self):
        self.spec = _read(os.path.join(_paths.DEV, "tests", "85-cold-tier.spec.js"))

    def test_the_browser_fixture_uses_this_tools_markers(self):
        for literal in (cold_tier.BLOB_ID, cold_tier.SLOT_CLASS, cold_tier.PART_ATTR,
                        cold_tier.FENCE_OPEN, cold_tier.FENCE_CLOSE, "application/json",
                        "gzip+base64"):
            self.assertIn(literal, self.spec, literal)

    def test_the_browser_fixture_matches_a_real_placeholder_and_payload(self):
        out, _ = cold_tier.compress(_big_doc(BIG))
        slot = re.search(r"<tr class=\"cmh-cold-slot[^\"]*\"[\s\S]*?</tr>", out).group(0)
        for sentence in ("stored compressed further down in this same file",
                         "restored automatically when scripting is enabled",
                         "No network access is needed either way",
                         "not expanded. Open this file"):
            self.assertIn(sentence, slot, sentence)
            self.assertIn(sentence, self.spec, sentence)
        self.assertEqual(_payload(out)["v"], 1)
        self.assertIn("v: 1", self.spec)

    def test_the_browser_fixture_pins_the_default_keep_rows(self):
        self.assertIn("const KEEP = %d;" % cold_tier.DEFAULT_KEEP_ROWS, self.spec)

    def test_the_browser_fixture_is_a_body_the_shipped_defaults_would_compress(self):
        # A fixture at or below `min_rows` is a shape `finalize.py --cold-tier` never emits, so the
        # browser suite would be asserting hydration for a document the tool declines. That is the
        # drift this class exists to catch, and raising `keep_rows` is exactly what causes it.
        self.assertIn("const TOTAL = %d;" % (cold_tier.DEFAULT_MIN_ROWS + 1), self.spec)

    def test_the_browser_fixture_cuts_where_the_real_emitter_cuts(self):
        # A fixture that cut the leading indentation too would round-trip to the same text but put
        # the inter-row whitespace on the other side of the boundary - so the "identical DOM"
        # assertion, the spec's load-bearing one, would be testing a construction nobody ships.
        out, _ = cold_tier.compress(_big_doc(BIG))
        part = _payload(out)["parts"][0]
        text = gzip.decompress(base64.b64decode(part["data"])).decode("utf-8")
        self.assertTrue(text.startswith("<tr>"), text[:40])
        self.assertTrue(text.rstrip().endswith("</tr>"))
        slot_at = out.index('<tr class="cmh-cold-slot')
        self.assertEqual(out[slot_at - 4:slot_at], "    ",
                         "the placeholder keeps the row indentation that stayed behind")
        self.assertIn('rows(KEEP, TOTAL).replace(/^ +/, "")', self.spec)

    def test_the_browser_fixture_places_the_payload_where_the_emitter_does(self):
        self.assertIn('html.indexOf("</main>")', self.spec)
        self.assertNotIn('lastIndexOf("</body>")', self.spec)


class DerivedFixtureTests(unittest.TestCase):
    """The derived fixture sizes must stay meaningful at whatever the shipped thresholds become.

    These ran as import-time `assert`s until review pointed out two problems: `python -O` strips
    them, and a tripped one aborts collection instead of reporting a failure. They are ordinary
    tests now, so they always run and they name what broke.
    """

    def test_the_big_fixture_clears_the_eligibility_bar(self):
        self.assertGreater(BIG, max(MIN, KEEP))

    def test_the_small_fixture_has_a_tail_but_is_still_refused_by_min_rows(self):
        # SMALL <= KEEP would have no tail to take, so the table would stay plain even if the
        # min_rows gate stopped working - which is exactly how this test went vacuous once.
        self.assertGreater(SMALL, KEEP)
        self.assertLessEqual(SMALL, MIN)

    def test_the_split_point_lands_inside_the_compressible_tail(self):
        self.assertGreater(HALF, KEEP)
        self.assertLess(HALF, BIG)


class ThresholdChoiceTests(unittest.TestCase):
    """The shipped thresholds are the ones a SWEEP measured, not a guess (CMH-COLD-10).

    What these tests DO cover: that the shipped constants match the pair the recorded sweep chose,
    that the sweep is a sweep (several points, whole corpus, enough iterations), that every recorded
    verdict follows the recorded rule, and that each recorded `blankP` really is the exact sign-test
    p-value for its own recorded counts - so a hand-transcribed number, the one value the whole
    decision hangs on, cannot be wrong while the suite stays green.

    What they deliberately do NOT cover: a wholesale fabrication of the measurement. Nothing here
    re-runs the browser harness, so a self-consistent artifact invented to justify some other
    default would pass. The artifact IS the evidence; these tests keep it internally honest and tied
    to the shipped constants, they do not re-derive it.
    """

    def setUp(self):
        with open(SWEEP, "r", encoding="utf-8") as fh:
            self.sweep = json.load(fh)

    def _measured(self, point):
        """The documents a point actually MEASURED.

        A document the tier DECLINED is byte-identical in both variants, so it carries no
        information about the tier's paint cost - it can neither pass nor fail. `cold_tier_perf.mjs`
        FAILS such a document outright ("nothing was measured"); this sweep records it as unmeasured
        instead and excludes it, which is a deliberate divergence recorded in the artifact's rule.
        """
        return [d for d in point["documents"] if d["engaged"]]

    def _passes(self, doc):
        return all(doc[state]["blankP"] >= self.sweep["alpha"] for state in ("cold", "warm"))

    def test_the_shipped_defaults_are_the_pair_the_sweep_chose(self):
        self.assertEqual(cold_tier.DEFAULT_KEEP_ROWS, self.sweep["chosen"]["keepRows"])
        self.assertEqual(cold_tier.DEFAULT_MIN_ROWS, self.sweep["chosen"]["minRows"])

    def _all_points(self):
        return list(self.sweep["screen"]) + list(self.sweep["confirmation"]["points"])

    def test_the_sweep_is_a_sweep_over_the_whole_corpus(self):
        # Pinned to the EXACT grid and corpus the spec row names: a shape check ("at least four
        # points, at least three documents") passes an artifact with points quietly dropped.
        screen = [(p["keepRows"], p["minRows"]) for p in self.sweep["screen"]]
        self.assertEqual(screen, [(20, 40), (100, 200), (250, 500), (500, 1000),
                                  (1000, 2000), (2000, 4000)])
        confirmed = [(p["keepRows"], p["minRows"]) for p in self.sweep["confirmation"]["points"]]
        self.assertEqual(confirmed, [(20, 40), (1000, 2000), (2000, 4000)])
        names = {"sm-report", "md-report", "xl-tree"}
        for point in self._all_points():
            self.assertEqual({d["name"] for d in point["documents"]}, names)
            self.assertEqual(len([d for d in point["documents"] if d["largest"]]), 1)
            self.assertTrue(self._measured(point), "every point must measure something")
        self.assertGreaterEqual(self.sweep["screenIterations"], 10)

    def test_the_gate_p_value_is_the_sign_test_of_its_own_counts(self):
        # `blankP` is the value the gate is decided on, so it is recomputed - in BOTH stages, not
        # just the screen, since the confirmation is the stage that reversed the decision. `fmpP`
        # and `ttiP` are carried through from the harness for context and are NOT recomputable from
        # this file (it does not record their direction counts); nothing is decided on them, and the
        # artifact says so rather than implying a check that does not happen.
        for point in self._all_points():
            n = point["iterations"]
            for doc in point["documents"]:
                for state in ("cold", "warm"):
                    s = doc[state]
                    with self.subTest(keep=point["keepRows"], doc=doc["name"], state=state):
                        self.assertEqual(s["discordant"], s["onlyOn"] + s["onlyOff"])
                        self.assertAlmostEqual(
                            s["blankP"], _sign_test_p(s["onlyOn"], s["discordant"]), places=12)
                        self.assertEqual(s["blankOn"] - s["blankOff"], s["onlyOn"] - s["onlyOff"])
                        for key in ("blankOn", "blankOff"):
                            self.assertGreaterEqual(s[key], 0)
                            self.assertLessEqual(s[key], n)
                        self.assertLessEqual(s["discordant"], n)
                        # Reported-only statistics: present and in range, nothing more is claimed.
                        for key in ("fmpP", "ttiP"):
                            self.assertIsNotNone(s[key])
                            self.assertGreaterEqual(s[key], 0.0)
                            self.assertLessEqual(s[key], 1.0)
                        self.assertIn("dTti", s)
                self.assertEqual(doc["bytesSaved"], doc["bytesOff"] - doc["bytesOn"])
            self.assertEqual(point["bytesSaved"],
                             sum(d["bytesSaved"] for d in point["documents"]))

    def test_the_artifact_says_which_p_values_are_reproducible_from_it(self):
        # Claiming "every p-value is recomputed" while only the gate's is would be the same class of
        # overclaim this row exists to avoid.
        self.assertIn("reported rather than reproducible here", self.sweep["generatedBy"])

    def test_the_gate_is_described_the_same_way_everywhere(self):
        # Review found `rule`, `metricCaveat` and the implemented `_passes` stating three different
        # ship conditions - and the difference is what decided which pair shipped.
        self.assertIn("GATE, at both stages, is the paired blank-until-parsed sign test",
                      self.sweep["rule"])
        self.assertIn("GATE is the blank rate", self.sweep["metricCaveat"])
        self.assertIn("NOT the gate", self.sweep["metric"])

    def test_the_artifact_enumerates_every_divergence_from_the_named_harness(self):
        # `cold_tier_perf.mjs` fails a document on three independent conditions and this sweep keeps
        # only one of them; claiming a single divergence was factually wrong.
        divergences = self.sweep["divergencesFromHarness"]
        self.assertGreaterEqual(len(divergences), 3)
        joined = " ".join(divergences)
        for topic in ("DECLINED", "FMP sign test", "TTI budget"):
            self.assertIn(topic, joined, topic)

    def test_the_artifact_records_its_own_limits(self):
        # Each of these is a limit a reviewer had to point out because the file did not say it.
        self.assertIn("false-positive floor", self.sweep["nullControl"])
        self.assertIn("BETWEEN points it is not", self.sweep["drift"])
        self.assertIn("EXTRAPOLATED, not observed", self.sweep["coverageLimit"])

    def test_the_artifact_records_the_power_the_rule_actually_has(self):
        # The rule cannot reject below a minimum number of DISCORDANT pairs - a property of that
        # count, not of the iteration count, which is what made the first draft's "at 30 iterations
        # the test can reject" misleading for a point with one discordant pair.
        floor = min(d for d in range(1, 31) if _sign_test_p(d, d) <= self.sweep["alpha"])
        self.assertIn("powerNote", self.sweep)
        self.assertIn(str(floor), self.sweep["powerNote"])
        self.assertIn("discordant", self.sweep["powerNote"].lower())

    def test_the_chosen_pair_is_the_smallest_one_the_confirmation_passes(self):
        # keep_rows and the compression win move in opposite directions, so anything larger than the
        # smallest passing point gives away bytes it did not have to - but "passing" must be read off
        # the CONFIRMATION, not the screen. On the screen the runner-up also passed; at the
        # confirmation's power it did not, and shipping the screen's answer would have shipped a
        # pair that still regresses.
        passing = [p for p in self.sweep["confirmation"]["points"]
                   if all(self._passes(d) for d in self._measured(p))]
        self.assertTrue(passing)
        self.assertEqual(min(p["keepRows"] for p in passing), self.sweep["chosen"]["keepRows"])
        chosen = [p for p in passing if p["keepRows"] == self.sweep["chosen"]["keepRows"]][0]
        self.assertEqual(chosen["minRows"], self.sweep["chosen"]["minRows"])

    def test_the_screen_alone_would_have_chosen_a_pair_the_confirmation_rejects(self):
        # This is the whole reason there are two stages; if it ever stops being true the second
        # stage looks like ceremony, so the artifact has to keep showing the disagreement.
        screened = [p for p in self.sweep["screen"]
                    if all(self._passes(d) for d in self._measured(p))]
        self.assertTrue(screened)
        smallest = min(p["keepRows"] for p in screened)
        self.assertLess(smallest, self.sweep["chosen"]["keepRows"])
        confirmed = [p for p in self.sweep["confirmation"]["points"] if p["keepRows"] == smallest]
        self.assertTrue(confirmed, "the screen's pick must be re-measured, not simply dropped")
        self.assertFalse(all(self._passes(d) for d in self._measured(confirmed[0])))

    def test_the_recorded_verdicts_match_the_recorded_rule(self):
        for point in self.sweep["screen"]:
            for doc in point["documents"]:
                with self.subTest(keep=point["keepRows"], doc=doc["name"]):
                    expected = self._passes(doc) if doc["engaged"] else None
                    self.assertEqual(doc["paintPasses"], expected)
            self.assertEqual(point["paintPasses"],
                             all(d["paintPasses"] for d in self._measured(point)))

    def test_the_sweep_records_why_the_previous_defaults_had_to_change(self):
        # The baseline point is the shipped 20/40 pair #1271 measured as costing cold first paint.
        baseline = [p for p in self.sweep["screen"]
                    if p["keepRows"] == self.sweep["baseline"]["keepRows"]][0]
        self.assertFalse(baseline["paintPasses"])
        regressed = [d["name"] for d in self._measured(baseline) if not d["paintPasses"]]
        self.assertTrue(regressed, "the baseline must record the regression it is the baseline for")

    def test_the_new_defaults_keep_most_of_the_win_on_the_largest_document(self):
        # The trade is stated in bytes, not asserted: the largest document must still get the bulk
        # of its compression, or the tier is not worth carrying at all.
        def largest(keep):
            point = [p for p in self.sweep["screen"] if p["keepRows"] == keep][0]
            return [d for d in point["documents"] if d["largest"]][0]

        before = largest(self.sweep["baseline"]["keepRows"])
        after = largest(self.sweep["chosen"]["keepRows"])
        self.assertTrue(after["engaged"], "the tier must still engage on the largest document")
        # Measured at 82.8 percent. The bound is what makes the tier worth carrying at all: a
        # threshold raised until the largest document keeps only a fraction of its win would be a
        # different feature wearing the same name.
        self.assertGreater(after["bytesSaved"], before["bytesSaved"] * 0.75)

    def test_a_document_the_tier_declines_is_unmeasured_rather_than_passing(self):
        # Where the tier does not engage the two variants are the SAME bytes, so a verdict there
        # would be a comparison that never happened. The recorded controls show how loud that noise
        # is - which is why they are excluded from the gate rather than counted as passes.
        declined = [(p, d) for p in self.sweep["screen"] for d in p["documents"]
                    if not d["engaged"]]
        self.assertTrue(declined)
        for point, doc in declined:
            with self.subTest(keep=point["keepRows"], doc=doc["name"]):
                self.assertEqual(doc["bytesSaved"], 0)
                self.assertEqual(doc["bytesOff"], doc["bytesOn"])
                self.assertIsNone(doc["paintPasses"])

    def test_the_confirmation_run_is_powered_to_reject(self):
        # A rule that cannot reject cannot pass anything either. The confirmation is only worth
        # reading if its sample can produce a significant result - and it must actually produce one
        # on the baseline, or "the new pair is better" is a comparison against nothing.
        confirm = self.sweep["confirmation"]
        self.assertGreater(confirm["iterations"], self.sweep["iterations"])
        floor = min(d for d in range(1, confirm["iterations"] + 1)
                    if _sign_test_p(d, d) <= self.sweep["alpha"])
        self.assertEqual(confirm["signTestFloor"], floor)
        for point in confirm["points"]:
            for doc in point["documents"]:
                for state in ("cold", "warm"):
                    s = doc[state]
                    with self.subTest(keep=point["keepRows"], doc=doc["name"], state=state):
                        self.assertEqual(s["discordant"], s["onlyOn"] + s["onlyOff"])
                        self.assertAlmostEqual(
                            s["blankP"], _sign_test_p(s["onlyOn"], s["discordant"]), places=12)
        chosen = [p for p in confirm["points"]
                  if p["keepRows"] == self.sweep["chosen"]["keepRows"]][0]
        baseline = [p for p in confirm["points"]
                    if p["keepRows"] == self.sweep["baseline"]["keepRows"]][0]
        self.assertFalse(baseline["paintPasses"], "the baseline must be rejected at this power")
        self.assertTrue(chosen["paintPasses"])
        before = [d for d in baseline["documents"] if d["largest"]][0]
        after = [d for d in chosen["documents"] if d["largest"]][0]
        self.assertGreaterEqual(before["cold"]["discordant"], floor)
        self.assertLess(after["cold"]["blankOn"], before["cold"]["blankOn"])
        self.assertLess(after["cold"]["dFmp"], before["cold"]["dFmp"])

    def test_the_artifact_bounds_the_residual_instead_of_claiming_parity(self):
        # The chosen pair is NOT at parity - one blank load in thirty remains - and a non-rejection
        # is not a proof of equivalence. Review read the earlier "the bound holds at this power" as
        # the same error one notch quieter, so the residual is now a QUANTIFIED bound, checked here
        # against the recorded counts rather than against the prose that describes it.
        self.assertIn("NOT a demonstration of parity", self.sweep["residual"])
        bound = self.sweep["residualBound"]
        chosen = [p for p in self.sweep["confirmation"]["points"]
                  if p["keepRows"] == self.sweep["chosen"]["keepRows"]][0]
        largest = [d for d in chosen["documents"] if d["largest"]][0]
        self.assertEqual(bound["document"], largest["name"])
        self.assertEqual(bound["blankOn"], largest[bound["state"]]["blankOn"])
        self.assertEqual(bound["iterations"], chosen["iterations"])
        self.assertGreater(bound["blankOn"], 0,
                           "if the residual reached zero this row should say so instead")
        self.assertAlmostEqual(
            bound["upperBound95"],
            _clopper_pearson_upper(bound["blankOn"], bound["iterations"], self.sweep["alpha"]),
            places=3)
        self.assertIn("%.1f%%" % (bound["upperBound95"] * 100), self.sweep["residual"])

    def test_the_shipped_document_scan_backs_the_no_reader_sees_a_change_claim(self):
        # "Nothing a reader sees changes" rests on a scan of the real documents, so the scan is
        # recorded and re-run here rather than asserted in prose only.
        scan = self.sweep["shippedDocumentScan"]["documents"]
        self.assertGreaterEqual(len(scan), 7)
        for entry in scan:
            path = os.path.join(_paths.EXAMPLES, entry["document"])
            if not os.path.exists(path):
                path = os.path.join(_paths.DEV, "upgrade-corpus", entry["document"])
            with self.subTest(document=entry["document"]):
                self.assertTrue(os.path.exists(path), path)
                html = _read(path)
                try:
                    html, _ = cold_tier.expand(html)
                except cold_tier.ColdTierError:
                    pass
                _out, old = cold_tier.compress(
                    html, min_rows=self.sweep["baseline"]["minRows"],
                    keep_rows=self.sweep["baseline"]["keepRows"])
                _out, new = cold_tier.compress(html)
                self.assertEqual(bool(old), entry["engagedAtBaseline"])
                self.assertEqual(bool(new), entry["engagedAtChosen"])
                self.assertFalse(new, "no shipped document engages the tier at the new defaults")

    def test_the_spec_row_states_the_chosen_pair_and_the_trade(self):
        row = _spec_row("CMH-COLD-10")
        self.assertTrue(row)
        for literal in (str(self.sweep["chosen"]["keepRows"]),
                        str(self.sweep["chosen"]["minRows"]),
                        "cold-tier-threshold-sweep.json"):
            self.assertIn(literal, row, literal)

    def test_the_spec_row_does_not_claim_equivalence_the_test_cannot_support(self):
        # A non-significant sign test is a failure to detect, never a proof of equivalence, and
        # four independent reviewers read the earlier wording as claiming the latter.
        row = _spec_row("CMH-COLD-10")
        self.assertNotIn("statistically indistinguishable", row)

    def test_the_default_thresholds_row_states_the_shipped_numbers(self):
        row = _spec_row("CMH-COLD-01")
        self.assertIn("defaults %d and %d" % (cold_tier.DEFAULT_KEEP_ROWS,
                                              cold_tier.DEFAULT_MIN_ROWS), row)


class SpecTests(unittest.TestCase):
    def test_every_behavior_has_a_spec_row(self):
        for index in list(range(1, 9)) + [10]:
            feature = "CMH-COLD-%02d" % index
            with self.subTest(feature=feature):
                self.assertTrue(_spec_row(feature), feature)

    def test_the_spec_records_why_decompressionstream_is_not_used(self):
        self.assertIn("DecompressionStream", _spec_row("CMH-COLD-05"))


if __name__ == "__main__":
    unittest.main()
