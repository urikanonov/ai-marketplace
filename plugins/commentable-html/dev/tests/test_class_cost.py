#!/usr/bin/env python3
"""Tests for dev/tools/class_cost.py (CMH-SIZE-04).

Two jobs. First, pin the arithmetic and the hazard detection on crafted inputs, so the numbers the
spec quotes are reproducible rather than a one-off claim, and so the properties the spec RELIES on
(quote elision is exact; rename and normalize are over-estimates; a hazard is evidence from code,
never from the document's text) are enforced rather than asserted.

Second, run the tool over every REAL generated document this repository ships and pin the finding
that closes the question: the whole `class` attribute budget is a rounding error on a real document,
and every one of those documents already contains the specific constructs that defeat a static
class rewrite. Those corpus tests are the TRIPWIRE - if a generated document ever does grow
material class repetition, or ever stops carrying the LOAD-BEARING hazards the analysis names, they
go red and the decision recorded in CMH-SIZE-04 is due a fresh look.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402  shared pkg/dev split path constants

sys.path.insert(0, _paths.DEV_TOOLS)
import class_cost  # noqa: E402

# Headroom over the measured maximum, which is 0.35 percent of the file on the largest shipped
# document. A document that crosses this is not a failure of the tool - it is the signal that the
# premise of CMH-SIZE-04 (the budget is negligible) no longer holds on a document we ship.
MAX_CLASS_PERCENT = 2.0

# The real generated documents, pinned by NAME. Globbing alone would let the tripwire keep passing
# if the corpus were repointed or replaced with documents that are not the layer's own output.
CORPUS_NAMES = (
    "deck-showcase.html",
    "report-checklist.html",
    "report-community-garden.html",
    "report-metrics.html",
    "report-notes.html",
    "report-taxi.html",
    "report-triage.html",
)
CORPUS = tuple(os.path.join(_paths.EXAMPLES, name) for name in CORPUS_NAMES)

# The hazards the CMH-SIZE-04 argument actually rests on. Asserting merely that SOME hazard exists
# would stay green if the deck CSS lost its `[class*=...]` selectors, which is half the argument.
LOAD_BEARING_HAZARDS = ("attribute_selector", "scripted_class")

TOOL = os.path.join(_paths.DEV_TOOLS, "class_cost.py")


def _read(path):
    with open(path, encoding="utf-8", errors="replace") as handle:
        return handle.read()


class AttributeLexerTests(unittest.TestCase):
    def test_a_class_spelling_inside_another_attributes_value_is_not_an_attribute(self):
        # The blind-scan defect CMH-SIZE-01 records paying for once: a quote-unaware scan measures
        # the decoy and never sees the real attribute.
        result = class_cost.scan('<div data-note="see class=\'x y\' here" class="real one">')
        self.assertEqual(result["class_attrs"], 1)
        self.assertEqual(result["top_values"][0][0], "real one")
        self.assertEqual(result["class_bytes"], len(' class="real one"'))

    def test_an_uppercase_spelling_is_measured(self):
        result = class_cost.scan('<p CLASS="a">x</p>')
        self.assertEqual(result["class_attrs"], 1)
        self.assertEqual(result["class_bytes"], len(' CLASS="a"'))

    def test_a_repeated_class_attribute_costs_both_but_takes_the_first_value(self):
        result = class_cost.scan('<p class="a" class="b">x</p>')
        self.assertEqual(result["class_bytes"], len(' class="a"') + len(' class="b"'))
        self.assertEqual(result["top_values"][0][0], "a")

    def test_a_value_written_with_an_entity_is_measured_as_the_browser_reads_it(self):
        # Bytes are what the source spends; TOKENS are what the DOM sees, so `a&#32;b` is two.
        result = class_cost.scan('<p class="a&#32;b">x</p>')
        self.assertEqual(result["class_bytes"], len(' class="a&#32;b"'))
        self.assertEqual(result["distinct_tokens"], 2)

    def test_a_non_ascii_value_is_charged_in_bytes_not_characters(self):
        result = class_cost.scan('<p class="\u00e9">x</p>')
        self.assertEqual(result["class_bytes"], len(' class="\u00e9"'.encode("utf-8")))


class CostArithmeticTests(unittest.TestCase):
    def test_the_cost_counts_the_bytes_the_attribute_actually_occupies(self):
        result = class_cost.scan('<p class="a b">x</p>')
        self.assertEqual(result["class_attrs"], 1)
        self.assertEqual(result["class_bytes"], len(' class="a b"'))

    def test_single_quoted_and_unquoted_spellings_are_measured_as_written(self):
        result = class_cost.scan("<p class='a b'>x</p><i class=solo>y</i>")
        self.assertEqual(result["class_attrs"], 2)
        self.assertEqual(result["class_bytes"], len(" class='a b'") + len(" class=solo"))

    def test_an_element_without_a_class_costs_nothing(self):
        result = class_cost.scan("<p>x</p>")
        self.assertEqual(result["class_attrs"], 0)
        self.assertEqual(result["class_bytes"], 0)

    def test_distinct_values_and_tokens_are_counted_separately(self):
        result = class_cost.scan('<p class="a b"></p><p class="a b"></p><p class="b c"></p>')
        self.assertEqual(result["class_attrs"], 3)
        self.assertEqual(result["distinct_values"], 2)
        self.assertEqual(result["distinct_tokens"], 3)
        self.assertEqual(result["top_values"][0], ("a b", 2))


class CeilingTests(unittest.TestCase):
    def test_the_hoist_ceiling_counts_a_token_every_direct_child_shares(self):
        html = '<ul><li class="row a"></li><li class="row b"></li><li class="row c"></li></ul>'
        self.assertEqual(class_cost.scan(html)["ceiling_hoist"], 3 * (len("row") + 1))

    def test_hoisting_that_empties_a_value_reclaims_the_attribute_syntax_too(self):
        # Both children are left with nothing, so ` class="row"` goes entirely: 4 bytes of token
        # plus the 8 bytes of ` class=""` around it, twice.
        html = '<ul><li class="row"></li><li class="row"></li></ul>'
        self.assertEqual(class_cost.scan(html)["ceiling_hoist"],
                         2 * (len("row") + 1) + 2 * (len(' class="row"') - len("row") - 1))

    def test_a_token_one_sibling_lacks_is_not_hoistable(self):
        html = '<ul><li class="row a"></li><li class="row b"></li><li class="b"></li></ul>'
        self.assertEqual(class_cost.scan(html)["ceiling_hoist"], 0)

    def test_a_lone_child_offers_no_hoist(self):
        self.assertEqual(class_cost.scan('<ul><li class="row a"></li></ul>')["ceiling_hoist"], 0)

    def test_siblings_written_without_end_tags_are_still_siblings(self):
        # html.parser does no implicit closing, so without the IMPLIED_END table these three rows
        # parse as a chain of parents and the hoist figure reads 0 - on exactly the row-heavy
        # markup the 1725-row document behind this question is made of.
        implicit = '<ul><li class="row a"><li class="row b"><li class="row c"></ul>'
        explicit = '<ul><li class="row a"></li><li class="row b"></li><li class="row c"></li></ul>'
        self.assertEqual(class_cost.scan(implicit)["ceiling_hoist"],
                         class_cost.scan(explicit)["ceiling_hoist"])
        self.assertGreater(class_cost.scan(implicit)["ceiling_hoist"], 0)

    def test_table_cells_written_without_end_tags_are_still_siblings(self):
        html = '<table><tr><td class="c x"><td class="c y"><td class="c z"></table>'
        self.assertEqual(class_cost.scan(html)["ceiling_hoist"], 3 * (len("c") + 1))

    def test_table_rows_written_without_end_tags_are_still_siblings(self):
        # A `<tr>` has to close the open `<td>` AND the `<tr>` holding it. Closing only one level
        # nests every row inside its predecessor, which on a 100-row table understated the hoist
        # figure by two orders of magnitude.
        implicit = ('<table><tbody>'
                    + '<tr class="r"><td class="c">a<td class="c">b' * 3
                    + '</tbody></table>')
        explicit = ('<table><tbody>'
                    + '<tr class="r"><td class="c">a</td><td class="c">b</td></tr>' * 3
                    + '</tbody></table>')
        self.assertEqual(class_cost.scan(implicit)["ceiling_hoist"],
                         class_cost.scan(explicit)["ceiling_hoist"])
        self.assertGreater(class_cost.scan(implicit)["ceiling_hoist"], 0)

    def test_an_implied_close_reaches_through_open_inline_markup(self):
        # A browser closes the open `<li>` even though inline markup inside it is still open. The
        # intervening element is not itself something `<li>` closes, so only the look-through rule
        # makes these two items siblings.
        implicit = '<ul><li class="row a"><span>x<li class="row b"><span>y</ul>'
        explicit = '<ul><li class="row a"><span>x</span></li><li class="row b"><span>y</span></li></ul>'
        self.assertEqual(class_cost.scan(implicit)["ceiling_hoist"],
                         class_cost.scan(explicit)["ceiling_hoist"])
        self.assertGreater(class_cost.scan(implicit)["ceiling_hoist"], 0)

    def test_an_implied_close_reaches_through_an_open_paragraph(self):
        implicit = '<ul><li class="row a"><p>x<li class="row b"><p>y</ul>'
        self.assertGreater(class_cost.scan(implicit)["ceiling_hoist"], 0)

    def test_an_implied_close_stops_at_a_container_boundary(self):
        # The inner list's items must NOT close the outer list's item.
        html = ('<ul><li class="outer"><ul><li class="inner x"><li class="inner y"></ul>'
                '</li></ul>')
        result = class_cost.scan(html)
        self.assertEqual(result["class_attrs"], 3)
        # Only the two inner items share a token; the outer item is their ancestor, not a sibling.
        self.assertEqual(result["ceiling_hoist"], 2 * (len("inner") + 1))

    def test_the_rename_ceiling_shortens_the_commonest_token_first(self):
        html = '<p class="alpha"></p><p class="alpha"></p><p class="beta"></p>'
        self.assertEqual(class_cost.scan(html)["ceiling_rename"],
                         (len("alpha") - 1) * 2 + (len("beta") - 1))

    def test_the_rename_ceiling_gives_the_shortest_names_to_the_commonest_tokens(self):
        # With more distinct tokens than one-character names, the ORDER matters: the commonest must
        # get the short names or the ceiling is not the best a renamer could do. Every token here
        # is the same length, so only the ordering can move the number.
        tokens = ["t%03d" % n for n in range(60)]
        html = "".join('<p class="%s"></p>' % t * (60 - n) for n, t in enumerate(tokens))
        best = class_cost.scan(html)["ceiling_rename"]

        counts = {t: 60 - n for n, t in enumerate(tokens)}
        names = class_cost._shortest_names(len(tokens))
        worst = sum(max(0, len(t) - len(name)) * counts[t]
                    for t, name in zip(reversed(tokens), names))
        self.assertGreater(best, worst)

    def test_a_token_shorter_than_its_assigned_name_is_never_lengthened(self):
        # Past 52 distinct tokens the shortest free name is two characters, and a real renamer
        # would simply keep a one-character token - so the term must floor at zero, not go negative.
        # The one-character token has to land BEYOND the 52 single-character names for the floor to
        # be exercised at all, which is why every token here appears exactly once and `z` is last.
        html = "".join('<p class="t%02d"></p>' % n for n in range(52)) + '<p class="z"></p>'
        result = class_cost.scan(html)
        self.assertEqual(result["distinct_tokens"], 53)
        # 52 three-character tokens each save two bytes; `z` is assigned a two-character name and
        # must contribute 0, not -1.
        self.assertEqual(result["ceiling_rename"], 52 * (len("t00") - 1))
        single = "".join('<p class="%s"></p>' % t for t in "abcdefghijklmnopqrstuvwxyz")
        self.assertEqual(class_cost.scan(single)["ceiling_rename"], 0)

    def test_the_normalize_ceiling_covers_padding_and_repeated_tokens(self):
        self.assertEqual(class_cost.scan('<p class="  a   b  a "></p>')["ceiling_normalize"],
                         len("  a   b  a ") - len("a b"))

    def test_the_quote_elision_ceiling_counts_only_values_that_may_lose_their_quotes(self):
        # A single token with no whitespace can be written unquoted, saving exactly two bytes; a
        # multi-token value, an already-unquoted value, and an empty value cannot.
        self.assertEqual(class_cost.scan('<p class="solo"></p>')["ceiling_quote_elision"], 2)
        self.assertEqual(class_cost.scan('<p class="a b"></p>')["ceiling_quote_elision"], 0)
        self.assertEqual(class_cost.scan("<p class=solo></p>")["ceiling_quote_elision"], 0)
        self.assertEqual(class_cost.scan('<p class=""></p>')["ceiling_quote_elision"], 0)

    def test_quote_elision_that_would_need_a_separator_saves_only_one_byte(self):
        # `<img class="hero"/>` cannot simply lose its quotes: `class=hero/` parses as the value
        # `hero/`, so a space has to go back in. The saving is one byte, and the ceiling must say
        # so - this is the single reduction the conclusion calls provably value-preserving.
        self.assertEqual(class_cost.scan('<img class="hero"/>')["ceiling_quote_elision"], 1)
        self.assertEqual(class_cost.scan('<img class="hero" />')["ceiling_quote_elision"], 2)
        self.assertEqual(class_cost.scan('<img class="hero"id="x">')["ceiling_quote_elision"], 1)
        self.assertEqual(class_cost.scan('<img class="hero" id="x">')["ceiling_quote_elision"], 2)

    def test_every_copy_of_a_repeated_class_attribute_can_lose_its_quotes(self):
        # Only the first copy is the value the DOM sees, but both cost bytes and both could be
        # written unquoted, so the ceiling counts both.
        self.assertEqual(class_cost.scan('<p class="a" class="b"></p>')["ceiling_quote_elision"], 4)

    def test_quote_elision_eligibility_is_decided_on_the_source_spelling(self):
        # `class="a&#61;b"` decodes to `a=b`, which holds a character unquoted syntax forbids - but
        # the SOURCE holds none, so `class=a&#61;b` is legal and decodes to exactly the same value.
        self.assertEqual(class_cost.scan('<p class="a&#61;b"></p>')["ceiling_quote_elision"], 2)
        # A literal space in the source really does forbid it.
        self.assertEqual(class_cost.scan('<p class="a b"></p>')["ceiling_quote_elision"], 0)

    def test_a_value_holding_a_character_unquoted_syntax_forbids_keeps_its_quotes(self):
        for value in ("a`b", "a=b", "a<b", "a>b", "a'b"):
            with self.subTest(value=value):
                html = '<p class="%s"></p>' % value
                self.assertEqual(class_cost.scan(html)["ceiling_quote_elision"], 0)

    def test_every_ceiling_counts_bytes_not_characters(self):
        # A reduction removes BYTES from a file. A two-byte token measured as one character makes
        # every ceiling understate what it claims to bound.
        accented = "\u00e9\u00e9"                      # two characters, four UTF-8 bytes
        rename = class_cost.scan('<p class="%s"></p>' % accented)["ceiling_rename"]
        self.assertEqual(rename, len(accented.encode("utf-8")) - 1)

        hoist = class_cost.scan('<ul><li class="%s a"></li><li class="%s b"></li></ul>'
                                % (accented, accented))["ceiling_hoist"]
        self.assertEqual(hoist, 2 * (len(accented.encode("utf-8")) + 1))

        normalize = class_cost.scan('<p class="%s %s"></p>' % (accented, accented))
        self.assertEqual(normalize["ceiling_normalize"], len(accented.encode("utf-8")) + 1)

    def test_a_token_written_as_a_character_reference_is_costed_at_its_source_length(self):
        # `&#233;` occupies six bytes in the file even though it denotes one character, and those
        # six bytes are what a reduction would actually reclaim.
        hoist = class_cost.scan('<ul><li class="&#233; a"></li><li class="&#233; b"></li></ul>'
                                )["ceiling_hoist"]
        self.assertEqual(hoist, 2 * (len("&#233;") + 1))

    def test_every_ceiling_is_bounded_by_the_bytes_the_attributes_occupy(self):
        # The ceilings are savings carved out of the class bytes, so none may exceed those bytes -
        # a ceiling that did would be arithmetic, not evidence.
        for path in CORPUS:
            result = class_cost.scan(_read(path))
            for key in ("ceiling_hoist", "ceiling_rename", "ceiling_normalize",
                        "ceiling_quote_elision"):
                with self.subTest(document=os.path.basename(path), ceiling=key):
                    self.assertLessEqual(result[key], result["class_bytes"])


class StripTests(unittest.TestCase):
    def test_only_real_attributes_are_stripped(self):
        html = '<p class="a">the spelling class="b" in prose stays</p>'
        self.assertEqual(class_cost.strip_class_attributes(html),
                         '<p>the spelling class="b" in prose stays</p>')

    def test_a_class_spelling_inside_a_script_string_is_left_alone(self):
        html = '<p class="a"></p><script>var s = \' class="b"\';</script>'
        stripped = class_cost.strip_class_attributes(html)
        self.assertIn('\' class="b"\'', stripped)
        self.assertNotIn('<p class="a">', stripped)

    def test_a_byte_identical_start_tag_inside_a_script_string_is_left_alone(self):
        # Locating the span by SEARCHING for its start tag struck the copy in the script instead
        # of the element: the strip removed the wrong bytes and left the real attribute in place.
        html = ('<script>var t = \'<p class="lead">hi</p>\';</script>'
                '<p class="lead">real</p>')
        stripped = class_cost.strip_class_attributes(html)
        self.assertIn('\'<p class="lead">hi</p>\'', stripped)
        self.assertIn("<p>real</p>", stripped)

    def test_a_byte_identical_start_tag_inside_a_comment_is_left_alone(self):
        html = '<!-- <i class="x"> --><i class="x"></i>'
        self.assertEqual(class_cost.strip_class_attributes(html),
                         '<!-- <i class="x"> --><i></i>')

    def test_a_repeated_class_attribute_is_removed_along_with_the_first(self):
        html = '<div class="a" class="b">x</div><div class="a" class="b">y</div>'
        self.assertEqual(class_cost.strip_class_attributes(html), "<div>x</div><div>y</div>")

    def test_a_span_whose_text_also_appears_in_an_earlier_attribute_value_is_located_exactly(self):
        html = '<div data-note=\' class="a"\' class="a">x</div>'
        self.assertEqual(class_cost.strip_class_attributes(html),
                         '<div data-note=\' class="a"\'>x</div>')

    def test_every_class_attribute_is_removed(self):
        html = '<p class="a"><i class=b></i><u CLASS=\'c\'></u></p>'
        self.assertEqual(class_cost.strip_class_attributes(html), "<p><i></i><u></u></p>")

    def test_the_bytes_removed_are_exactly_the_bytes_the_class_attributes_cost(self):
        # The report prints both figures side by side, so a strip that missed a span (or took
        # bytes that were not an attribute) would make them silently disagree.
        for path in CORPUS:
            result = class_cost.measure(path)
            with self.subTest(document=os.path.basename(path)):
                self.assertEqual(result["bytes_total"] - result["bytes_without_class"],
                                 result["class_bytes"])

    def test_stripping_leaves_no_class_attribute_behind_in_any_real_document(self):
        for path in CORPUS:
            with self.subTest(document=os.path.basename(path)):
                stripped = class_cost.strip_class_attributes(_read(path))
                self.assertEqual(class_cost.scan(stripped)["class_attrs"], 0)


class HazardTests(unittest.TestCase):
    def test_an_attribute_selector_on_class_is_a_hazard(self):
        result = class_cost.scan('<style>span:not([class*="cmh-code-"]) { color: red }</style>')
        self.assertIn("attribute_selector", result["hazards"])

    def test_an_uppercase_attribute_selector_is_a_hazard(self):
        # Selector attribute names are case-insensitive in HTML documents.
        self.assertIn("attribute_selector",
                      class_cost.scan("<style>[CLASS*=x] { color: red }</style>")["hazards"])

    def test_a_scripted_attribute_selector_is_a_hazard(self):
        # The runtime's `pre code[class*="language-"]` substring-matches an AUTHOR's own tokens at
        # runtime; it selects on the attribute string just as a stylesheet rule would.
        result = class_cost.scan(
            '<script>root.querySelectorAll("pre code[class*=\\"language-\\"]")</script>')
        self.assertIn("attribute_selector", result["hazards"])

    def test_a_plain_class_selector_is_not_an_attribute_selector_hazard(self):
        self.assertNotIn("attribute_selector",
                         class_cost.scan("<style>.plain { color: red }</style>")["hazards"])

    def test_a_css_escaped_class_selector_is_a_hazard(self):
        self.assertIn("escaped_selector",
                      class_cost.scan("<style>.\\74 ok { color: red }</style>")["hazards"])

    def test_a_linked_or_imported_stylesheet_is_a_hazard(self):
        self.assertIn("external_stylesheet",
                      class_cost.scan('<link rel="stylesheet" href="x.css">')["hazards"])
        self.assertIn("external_stylesheet",
                      class_cost.scan('<style>@import "x.css";</style>')["hazards"])
        self.assertIn("external_stylesheet",
                      class_cost.scan('<style>@IMPORT "x.css";</style>')["hazards"])

    def test_a_stylesheet_link_is_recognised_among_several_rel_tokens(self):
        self.assertIn("external_stylesheet",
                      class_cost.scan('<link rel="alternate stylesheet" href="x">')["hazards"])
        self.assertNotIn("external_stylesheet",
                         class_cost.scan('<link rel="icon" href="x">')["hazards"])

    def test_an_external_script_is_a_hazard(self):
        # Code the tool never reads can do anything to a class string.
        self.assertIn("external_script", class_cost.scan('<script src="app.js"></script>')["hazards"])

    def test_an_inert_external_script_is_not_reported_as_code(self):
        # A data block never executes, so naming it as unreadable CODE would be a false positive.
        self.assertNotIn("external_script",
                         class_cost.scan('<script type="application/json" src="d.json"></script>')
                         ["hazards"])

    def test_an_inline_event_handler_or_javascript_uri_is_a_hazard(self):
        self.assertIn("inline_handler",
                      class_cost.scan('<b onclick="this.classList.add(\'x\')">y</b>')["hazards"])
        self.assertIn("inline_handler",
                      class_cost.scan('<a href="javascript:go()">y</a>')["hazards"])

    def test_an_ordinary_attribute_that_merely_starts_with_on_is_not_a_handler(self):
        # Matching every `on*` name flagged plain content attributes as executable code.
        for markup in ('<b once="x">y</b>', '<b ongoing="true">y</b>',
                       '<a href="https://example.com/javascript:void">y</a>'):
            with self.subTest(markup=markup):
                self.assertNotIn("inline_handler", class_cost.scan(markup)["hazards"])

    def test_script_that_reads_writes_or_matches_a_class_string_is_a_hazard(self):
        for js in ('el.getAttribute("class")', "el.className", 'root.querySelectorAll(".x")',
                   "document.getElementsByClassName('x')", 'el.classList.contains("x")',
                   'el.classList.add("x")', 'el.classList.remove("x")'):
            with self.subTest(js=js):
                self.assertIn("scripted_class",
                              class_cost.scan("<script>%s</script>" % js)["hazards"])

    def test_a_document_with_none_of_those_constructs_reports_no_hazard(self):
        result = class_cost.scan('<style>.a { color: red }</style><p class="a">x</p>')
        self.assertEqual(result["hazards"], {})

    def test_a_class_token_in_ordinary_prose_is_not_mistaken_for_a_hazard(self):
        # A hazard is evidence from CSS or code, never from the text of the document.
        result = class_cost.scan('<p class="a">getAttribute("class") and [class*="a"]</p>')
        self.assertEqual(result["hazards"], {})

    def test_a_json_data_island_is_not_read_as_code(self):
        # Every generated document carries the layer's `embeddedComments` island; a reviewer's own
        # prose inside it must not stand in for the layer as evidence of a hazard.
        island = ('<script type="application/json" id="embeddedComments">'
                  '[{"body": "the fix is to stop using el.className here"}]</script>')
        self.assertEqual(class_cost.scan(island)["hazards"], {})
        self.assertIn("scripted_class",
                      class_cost.scan("<script>el.className</script>")["hazards"])

    def test_a_javascript_type_script_is_still_read_as_code(self):
        for spelling in ('type="text/javascript"', 'type="module"', 'TYPE="text/javascript"',
                         'type="text/javascript;charset=utf-8"', 'type=" text/javascript "',
                         'type="application/javascript"', 'type="text/livescript"',
                         'type="application/x-ecmascript"', 'type="text/javascript1.5"'):
            with self.subTest(spelling=spelling):
                html = "<script %s>el.className</script>" % spelling
                self.assertIn("scripted_class", class_cost.scan(html)["hazards"])

    def test_a_non_executable_script_type_is_not_read_as_code(self):
        for spelling in ('type="application/json"', 'type="importmap"', 'type="text/plain"',
                         'type="speculationrules"'):
            with self.subTest(spelling=spelling):
                html = "<script %s>el.className</script>" % spelling
                self.assertEqual(class_cost.scan(html)["hazards"], {})

    def test_a_self_closed_script_does_not_hide_the_code_that_follows(self):
        # `<script/>` leaves the element OPEN in HTML, so what follows is still code.
        self.assertIn("scripted_class", class_cost.scan("<script/>el.className</script>")["hazards"])


class ParserRobustnessTests(unittest.TestCase):
    def test_unmatched_end_tags_do_not_make_the_scan_quadratic(self):
        # A hostile document must not turn a maintainer's measurement into a hang; this shape used
        # to cost 14 s at 16k and hours at a few hundred thousand.
        html = "<div>" * 40000 + "</span>" * 40000
        self.assertEqual(class_cost.scan(html)["class_attrs"], 0)

    def test_an_unclosed_document_still_measures(self):
        result = class_cost.scan('<div class="a"><p class="b">text')
        self.assertEqual(result["class_attrs"], 2)

    def test_a_document_that_is_not_valid_utf8_is_still_measured(self):
        # `measure()` decodes leniently so such a file can be measured at all; every byte count
        # must tolerate what that leaves behind, or the tool raises instead of answering. The
        # invalid byte is put INSIDE a class value as well as in the body, because that is the
        # path that failed first.
        raw = b'<p class="caf\xe9">caf\xe9</p>'
        directory = tempfile.mkdtemp(prefix="cmh-class-cost-")
        try:
            path = os.path.join(directory, "latin1.html")
            with open(path, "wb") as handle:
                handle.write(raw)
            result = class_cost.measure(path)
            self.assertEqual(result["bytes_total"], len(raw))
            self.assertEqual(result["class_attrs"], 1)
            # The strip must round-trip the invalid bytes rather than mangle or drop them.
            self.assertEqual(result["bytes_total"] - result["bytes_without_class"],
                             result["class_bytes"])
        finally:
            shutil.rmtree(directory, ignore_errors=True)


class CliTests(unittest.TestCase):
    def _run(self, *args):
        return subprocess.run([sys.executable, TOOL] + list(args), capture_output=True, text=True)

    def test_a_missing_file_reports_and_exits_non_zero_without_a_traceback(self):
        done = self._run(os.path.join(_paths.EXAMPLES, "no-such-document.html"))
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("cannot read", done.stderr)
        self.assertNotIn("Traceback", done.stderr)

    def test_a_missing_file_does_not_stop_the_documents_that_do_exist(self):
        done = self._run(os.path.join(_paths.EXAMPLES, "no-such-document.html"), CORPUS[1])
        self.assertIn(os.path.basename(CORPUS[1]), done.stdout)

    def test_json_output_is_one_valid_document_for_several_files(self):
        done = self._run("--json", CORPUS[1], CORPUS[4])
        self.assertEqual(done.returncode, 0)
        payload = json.loads(done.stdout)
        self.assertEqual([os.path.basename(r["path"]) for r in payload],
                         [os.path.basename(CORPUS[1]), os.path.basename(CORPUS[4])])


class ShippedCorpusTests(unittest.TestCase):
    """The measurement that answers issue #1267, run against real generated documents."""

    def test_the_corpus_is_the_real_generated_documents(self):
        # Guard the guard: if the examples move, are renamed, or are replaced, the tripwires below
        # would otherwise pass vacuously.
        for path in CORPUS:
            with self.subTest(document=os.path.basename(path)):
                self.assertTrue(os.path.isfile(path), "missing shipped example: %s" % path)
        shipped = sorted(name for name in os.listdir(_paths.EXAMPLES) if name.endswith(".html"))
        self.assertEqual(shipped, sorted(CORPUS_NAMES),
                         "the shipped example set changed; re-measure and update CMH-SIZE-04")

    def test_the_whole_class_budget_is_a_rounding_error_on_every_shipped_document(self):
        for path in CORPUS:
            result = class_cost.scan(_read(path))
            percent = 100.0 * result["class_bytes"] / max(1, result["bytes_total"])
            with self.subTest(document=os.path.basename(path)):
                self.assertLess(
                    percent, MAX_CLASS_PERCENT,
                    "%s spends %.2f%% of its bytes on class attributes; CMH-SIZE-04 concluded "
                    "there is nothing worth reducing because that share is negligible - a "
                    "document above %.1f%% means that conclusion is due a fresh look"
                    % (os.path.basename(path), percent, MAX_CLASS_PERCENT))

    def test_every_shipped_document_carries_the_hazards_the_conclusion_rests_on(self):
        for path in CORPUS:
            hazards = class_cost.scan(_read(path))["hazards"]
            for hazard in LOAD_BEARING_HAZARDS:
                with self.subTest(document=os.path.basename(path), hazard=hazard):
                    self.assertIn(
                        hazard, hazards,
                        "%s no longer carries the %s hazard; CMH-SIZE-04 rests on every real "
                        "document carrying it, so re-read the analysis"
                        % (os.path.basename(path), hazard))

    def test_deleting_every_class_attribute_would_barely_move_the_compressed_file(self):
        # The shape-free bound on ANY class reduction: strictly more than any transform could take.
        # The measured maximum is 1.2 KB; 8 KB leaves the corpus room to grow while still firing on
        # a structural change in how classes are used.
        for path in CORPUS:
            result = class_cost.measure(path)
            saved = result["gzip_bytes"] - result["gzip_bytes_without_class"]
            with self.subTest(document=os.path.basename(path)):
                self.assertLess(
                    saved, 8 * 1024,
                    "%s would shed %d gzipped bytes if every class attribute vanished; "
                    "CMH-SIZE-04 rests on that being negligible" % (os.path.basename(path), saved))


if __name__ == "__main__":
    unittest.main()
