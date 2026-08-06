#!/usr/bin/env python3
"""Tests for deck/deck_validate.py (CMH-DECK-04).

A scaffolded deck passes; each injected violation (missing deck mode, remote font, remote media,
remote CSS url(), event handler, iframe, javascript: URL, ../ ref, <deck-stage>, duplicate slide
id) fails closed.
"""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402

DECK = os.path.join(_paths.PKG, "tools", "deck")
sys.path.insert(0, DECK)
import deck_validate  # noqa: E402

sys.path.insert(0, os.path.join(_paths.TOOLS, "validate"))
from checks import resources  # noqa: E402  the gate's measured presentation-attribute list

SCAFFOLD = os.path.join(DECK, "deck_scaffold.py")
# Insert a snippet as real markup just before the end-of-content comment (inside the region).
END_MARK = "<!-- END: commentable-html - CONTENT -->"
# Build a synthetic content region (a proper comment-delimited region the validator will parse).
BEGIN_OPEN = deck_validate.BEGIN_MARK + " (agent edits) -->"


def _inject(html, snippet):
    return html.replace(END_MARK, snippet + "\n" + END_MARK, 1)


def _wrap(inner, deck_mode=True):
    mode = ' data-cmh-mode="deck"' if deck_mode else ""
    return f'<main id="commentRoot"{mode}>{BEGIN_OPEN}{inner}{END_MARK}</main>'


def _errors(html):
    return deck_validate.deck_checks(html)


def _warnings(html, **kwargs):
    return deck_validate.deck_warnings_with_options(html, **kwargs)


class DeckValidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        out = os.path.join(cls.tmp, "deck.html")
        proc = subprocess.run(
            [sys.executable, SCAFFOLD, "--slides", "3", "--label", "V", "--source", out, "--out", out],
            capture_output=True, text=True, encoding="utf-8",
        )
        assert proc.returncode == 0, proc.stderr
        cls.html = Path(out).read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        __import__("shutil").rmtree(cls.tmp, ignore_errors=True)

    def _assert_error(self, mutated, needle):
        errs = _errors(mutated)
        self.assertTrue(any(needle in e for e in errs), f"expected '{needle}' in {errs}")

    def test_valid_deck_passes(self):
        self.assertEqual(_errors(self.html), [])

    def test_missing_deck_mode_fails(self):
        self._assert_error(self.html.replace(' data-cmh-mode="deck"', "", 1), "data-cmh-mode")

    def test_remote_font_fails(self):
        bad = _inject(self.html, '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=X">')
        self._assert_error(bad, "remote font")

    def test_event_handler_fails(self):
        self._assert_error(_inject(self.html, '<div onclick="steal()">x</div>'), "event-handler")

    def test_iframe_fails(self):
        self._assert_error(_inject(self.html, '<iframe src="x"></iframe>'), "iframe")

    def test_javascript_url_fails(self):
        self._assert_error(_inject(self.html, '<a href="javascript:evil()">x</a>'), "javascript:")

    def test_parent_traversal_fails(self):
        self._assert_error(_inject(self.html, '<img src="../../secret.png">'), "parent-directory")

    def test_deckstage_component_fails(self):
        self._assert_error(_inject(self.html, "<deck-stage></deck-stage>"), "deck-stage")

    def test_duplicate_slide_id_fails(self):
        ids = re.findall(r'data-slide-id="([^"]+)"', self.html)
        dup = self.html.replace(f'data-slide-id="{ids[1]}"', f'data-slide-id="{ids[0]}"', 1)
        self._assert_error(dup, "duplicate slide id")

    def test_cli_passes_on_valid_deck(self):
        out = os.path.join(self.tmp, "cli.html")
        Path(out).write_text(self.html, encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, os.path.join(DECK, "deck_validate.py"), out],
            capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)


    def test_main_in_process_covers_branches(self):
        import contextlib
        import io
        from unittest import mock
        valid = os.path.join(self.tmp, "valid.html")
        Path(valid).write_text(self.html, encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(deck_validate.main([valid]), 0)
        # a deck with a deck-error fails
        bad = os.path.join(self.tmp, "bad.html")
        Path(bad).write_text(_inject(self.html, "<iframe></iframe>"), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(deck_validate.main([bad]), 1)
        # base validator unavailable branch
        with mock.patch.object(deck_validate, "_base", None):
            self.assertEqual(deck_validate.validate_deck(valid)[0], [])

    def test_content_region_missing_reports_error(self):
        errs = deck_validate.deck_checks("<html><body>no markers</body></html>")
        self.assertTrue(any("CONTENT region markers" in e for e in errs))

    def test_missing_stage_and_slides_report(self):
        errs = deck_validate.deck_checks(_wrap("<div>no stage here</div>"))
        self.assertTrue(any("deck-viewport" in e for e in errs))
        self.assertTrue(any("deck-stage" in e for e in errs))
        self.assertTrue(any('class="slide"' in e for e in errs))

    def test_slide_without_id_and_bad_id_report(self):
        body = _wrap(
            '<div class="deck-viewport"><div class="deck-stage">'
            '<section class="slide"><p>no id</p></section>'
            '<section class="slide" data-slide-id="not-valid"><p>bad</p></section>'
            'prefers-reduced-motion'
            '</div></div>')
        errs = deck_validate.deck_checks(body)
        self.assertTrue(any("missing data-slide-id" in e for e in errs))
        self.assertTrue(any("invalid data-slide-id" in e for e in errs))

    def test_missing_reduced_motion_reports(self):
        errs = deck_validate.deck_checks(_wrap(
            '<div class="deck-viewport"><div class="deck-stage">'
            '<section class="slide" data-slide-id="slide-00000000"><p>x</p></section>'
            '</div></div>'))
        self.assertTrue(any("prefers-reduced-motion" in e for e in errs))

    def test_remote_import_and_editor_report(self):
        errs = deck_validate.deck_checks(_inject(self.html, "<style>@import url(https://evil/x.css);</style>"))
        self.assertTrue(any("@import" in e for e in errs))
        # a protocol-relative @import WITHOUT url() is still remote egress
        errs2 = deck_validate.deck_checks(_inject(self.html, '<style>@import "//evil/x.css";</style>'))
        self.assertTrue(any("@import" in e for e in errs2))
        errs3 = deck_validate.deck_checks(_inject(self.html, '<div class="edit-toggle"></div>'))
        self.assertTrue(any("edit-toggle" in e for e in errs3))


    def test_remote_media_fails(self):
        for snippet, needle in (
            ('<img src="http://evil/x.png">', "remote media"),
            ('<img src="https://evil/x.png">', "remote media"),
            ('<video src="//evil/x.mp4"></video>', "remote media"),
            ('<audio><source src="https://evil/a.mp3"></audio>', "remote media"),
        ):
            with self.subTest(snippet=snippet):
                self._assert_error(_inject(self.html, snippet), needle)

    def test_remote_css_url_fails(self):
        self._assert_error(
            _inject(self.html, '<div style="background:url(https://evil/bg.png)">x</div>'),
            "remote CSS url()")
        self._assert_error(
            _inject(self.html, "<style>.x{background:url(//evil/bg.png)}</style>"),
            "remote CSS url()")

    # #1186: the SVG presentation attributes the strict layer gate and the offline export now read
    # as CSS egress. The deck gate needs no fourth reading of the same question - its CSS `url()`
    # check runs over the whole deck BODY, so the reference is caught wherever it is written, in an
    # attribute value included. Pinned here so that coverage is a tested property of the deck gate
    # rather than an accident of how broadly its CSS reading is scoped.
    def test_a_remote_presentation_attribute_url_fails(self):
        for attr in resources.SVG_URL_PRESENTATION_ATTRS:
            snippet = ('<svg width="10" height="10"><rect width="10" height="10" %s='
                       '"url(https://evil/x.svg#r)"/></svg>' % attr)
            with self.subTest(attr=attr):
                self._assert_error(_inject(self.html, snippet), "remote CSS url()")
        # ... and a LOCAL reference, which is how these attributes are normally written, is clean.
        errs = _errors(_inject(self.html, '<svg width="10" height="10"><rect width="10" '
                                          'height="10" clip-path="url(#c)" fill="#336699"/></svg>'))
        self.assertEqual([e for e in errs if "remote CSS url()" in e], [], errs)

    def test_cmh_deck_12_low_contrast_css_pair_fails_with_selector(self):
        bad = _inject(
            self.html,
            '<style>.bad-table th { color: #777; background-color: #777; }</style>'
            '<table class="bad-table"><thead><tr><th>Theme</th></tr></thead></table>')
        errs = _errors(bad)
        self.assertTrue(any("low text contrast" in e and ".bad-table th" in e for e in errs), errs)

    def test_cmh_deck_12_background_shorthand_overrides_background_color(self):
        bad = _inject(
            self.html,
            '<style>.shorthand-bg { color:#fff; background-color:#000; background:#eee; }</style>'
            '<p class="shorthand-bg">Low contrast</p>')
        errs = _errors(bad)
        self.assertTrue(any(
            "low text contrast" in e and ".shorthand-bg" in e and "background #eee" in e
            for e in errs), errs)

    def test_cmh_deck_12_low_contrast_theme_variables_fail(self):
        bad = _inject(self.html, "<style>:root{--slide-fg:#777;--slide-bg:#777;}</style>")
        errs = _errors(bad)
        self.assertTrue(any("--slide-fg/--slide-bg" in e for e in errs), errs)

    def test_cmh_deck_theme_03_component_variable_pair_fails(self):
        # deck_validate.py's DECK_CONTRAST_VARIABLE_PAIRS gates the new themed component surfaces
        # directly (not only via the theme loader): a collapsed code text/bg pair fails.
        bad = _inject(self.html,
                      "<style>:root{--cmh-deck-code-text:#777;--cmh-deck-code-bg:#777;}</style>")
        errs = _errors(bad)
        self.assertTrue(any("code text/bg" in e for e in errs), errs)

    def test_cmh_deck_theme_03_ref_link_over_code_bg_pair_fails(self):
        # The .cmh-refs a reference pill draws --slide-link over --cmh-deck-code-bg; a custom theme
        # that collapses that pair to near-identical dark values must be rejected by deck_validate.
        bad = _inject(self.html,
                      "<style>:root{--slide-link:#334155;--cmh-deck-code-bg:#1e293b;}</style>")
        errs = _errors(bad)
        self.assertTrue(any("ref-link/code bg" in e for e in errs), errs)

    def test_cmh_deck_12_non_finite_rgb_does_not_crash(self):
        self.assertEqual(_errors(_inject(
            self.html, '<p style="color:#000; background:rgb(inf 0 0)">Bad color</p>')), [])
        self.assertEqual(_errors(_inject(
            self.html, '<p style="color:#000; background:rgb(1e309 0 0)">Bad color</p>')), [])

    def test_cmh_deck_12_semi_transparent_background_is_skipped(self):
        self.assertEqual(_errors(_inject(
            self.html, '<p style="color:#000; background:rgba(255,255,255,0.2)">Readable</p>')), [])
        self.assertEqual(_errors(_inject(
            self.html, '<p style="color:#fff; background:rgba(255,255,255,0.2)">Unknown backdrop</p>')), [])

    def test_cmh_deck_12_good_contrast_inline_pair_passes(self):
        self.assertEqual(
            _errors(_inject(self.html, '<p style="color: #fff; background-color: #000">Readable</p>')),
            [])

    def test_cmh_deck_19_overloaded_slide_warns_without_error(self):
        import contextlib
        import io
        extra = "".join(f"<p>Dense authored point {i}</p>" for i in range(1, 8))
        overloaded = self.html.replace("</section>", extra + "</section>", 1)
        self.assertEqual(_errors(overloaded), [])
        warnings = _warnings(overloaded, max_slide_lines=4, max_slide_elements=4)
        self.assertTrue(any("content overload advisory" in w and "slide " in w for w in warnings), warnings)
        out = os.path.join(self.tmp, "overloaded.html")
        Path(out).write_text(overloaded, encoding="utf-8")
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            self.assertEqual(deck_validate.main([
                "--max-slide-lines", "4", "--max-slide-elements", "4", out]), 0)
        self.assertIn("WARNING: deck: content overload advisory", err.getvalue())

    def test_cmh_deck_19_normal_slide_has_no_overload_warning(self):
        self.assertEqual(_warnings(self.html), [])

    def test_cmh_deck_19_overloaded_board_card_warns(self):
        card = (
            '<div data-cm-widget="board" data-cm-draggable><div data-cm-slot="todo">'
            '<article data-cm-part="heavy-card" data-cm-part-label="Heavy card">'
            + "".join(f"<p>Card detail {i}</p>" for i in range(1, 7)) +
            "</article></div></div>")
        warnings = _warnings(_inject(self.html, card), max_board_card_lines=3, max_board_card_elements=3)
        self.assertTrue(any("board card Heavy card" in w for w in warnings), warnings)

    def test_cmh_deck_12_kql_run_link_with_computed_background_fails(self):
        bad = _inject(
            self.html,
            '<style>.cmh-kql-cap{background:#111827}.cmh-kql-run{color:#b11f4b}</style>'
            '<figure class="cmh-kql"><figcaption class="cmh-kql-cap">'
            '<a class="cmh-kql-run" href="https://dataexplorer.azure.com/">Run in Azure Data Explorer</a>'
            '</figcaption><pre><code class="language-kusto">T | take 1</code></pre></figure>')
        errs = _errors(bad)
        self.assertTrue(any("cmh-kql-run" in e and "low text contrast" in e for e in errs), errs)

    def test_cmh_deck_12_low_contrast_connector_stroke_fails(self):
        bad = _inject(
            self.html,
            '<style>.slide-shell{background:#f7f4ef}.connector{stroke:#cbd5e1;stroke-width:1.5;fill:none}</style>'
            '<div class="slide-shell"><svg viewBox="0 0 100 20" aria-hidden="true">'
            '<path class="connector" d="M 0 10 L 100 10"></path></svg></div>')
        errs = _errors(bad)
        self.assertTrue(any("connector" in e and "stroke contrast" in e for e in errs), errs)

    def test_local_media_and_data_uri_pass(self):
        # A local relative image and a data: URI are NOT egress and must not trip the media check.
        self.assertEqual(_errors(_inject(self.html, '<img src="assets/local.png" alt="">')), [])
        self.assertEqual(
            _errors(_inject(self.html, '<img src="data:image/png;base64,AAAA" alt="">')), [])

    def test_unquoted_javascript_and_traversal_fail(self):
        self._assert_error(_inject(self.html, "<a href=javascript:evil()>x</a>"), "javascript:")
        self._assert_error(_inject(self.html, "<img src=../../secret.png>"), "parent-directory")

    def test_edit_toggle_plaintext_is_not_a_false_positive(self):
        # The word "edit-toggle" appearing in slide prose must NOT be flagged; only the real
        # <edit-toggle> element or a .edit-toggle control is the upstream editor.
        self.assertEqual(
            _errors(_inject(self.html, "<p>We removed the edit-toggle control upstream.</p>")), [])
        self._assert_error(_inject(self.html, "<edit-toggle></edit-toggle>"), "edit-toggle")

    def test_a_single_quoted_or_unquoted_deck_structure_validates(self):
        # UNDER-match: a class is the same class to a browser however it is quoted, and a
        # `deck-viewport` beside another class is still the viewport. The structural checks used
        # to be raw-text regexes that only saw the double-quoted, whole-literal spelling, so a
        # hand-authored deck failed with "no <section class=\"slide\"> found" and every per-slide
        # check then inspected nothing (#1159).
        body = _wrap(
            "<div class=\"deck-viewport theme-dark\"><div class=deck-stage>"
            "<section class='slide' data-slide-id='slide-00000001'><p>x</p></section>"
            "</div></div>prefers-reduced-motion")
        self.assertEqual(_errors(body), [])
        # ...and the editor guard misses nothing for the same reason: an unquoted `.edit-toggle`
        # control is the upstream editor just as a double-quoted one is.
        self._assert_error(_inject(self.html, "<div class=edit-toggle></div>"), "edit-toggle")

    def test_a_class_that_merely_contains_a_structural_name_is_not_that_structure(self):
        # OVER-match: `\bdeck-stage\b` is a substring test, so `my-deck-stage` satisfied the
        # "exactly one .deck-stage" check for an element a browser never matches `.deck-stage`
        # on - and `my-slide` was read as a slide (then reported as missing its id), and
        # `not-edit-toggle` as the upstream editor.
        bad = _inject(self.html,
                      '<div class="my-deck-stage"></div>'
                      '<section class="my-slide"><p>x</p></section>'
                      '<div class="not-edit-toggle"></div>')
        self.assertEqual(_errors(bad), [])

    def test_a_structural_class_named_in_prose_or_a_script_is_not_structure(self):
        # The checks read PARSED elements, so a class a reader merely SEES - in slide prose, or
        # inside a <script> body, which is text to a browser - is not deck structure.
        prose = _inject(self.html, '<p>Each stage carries class="deck-stage" on its wrapper.</p>')
        self.assertEqual(_errors(prose), [])
        scripted = _wrap(
            "<script>var t = '<div class=\"deck-viewport\"><div class=\"deck-stage\">"
            "<section class=\"slide\" data-slide-id=\"slide-00000001\"></section>"
            "</div></div>';</script>prefers-reduced-motion")
        errs = deck_validate.deck_checks(scripted)
        self.assertTrue(any("deck-viewport" in e for e in errs), errs)
        self.assertTrue(any("deck-stage" in e for e in errs), errs)
        self.assertTrue(any('class="slide"' in e for e in errs), errs)

    def test_a_noscript_parked_stage_editor_or_duplicate_id_is_still_structure(self):
        # A reader is on one side of scripting or the other, so the structural scan reads the body
        # BOTH ways and unions the findings - exactly as the active-content scan does. To a
        # scripting-DISABLED browser a <noscript> body is live markup, so a second stage, an
        # un-stripped editor or a duplicate slide id parked in one is real (and the raw-text
        # regexes this replaced saw them).
        self._assert_error(
            _inject(self.html, '<noscript><div class="deck-stage"></div></noscript>'),
            "expected exactly one .deck-stage")
        self._assert_error(
            _inject(self.html, "<noscript><edit-toggle></edit-toggle></noscript>"), "edit-toggle")
        first = re.findall(r'data-slide-id="([^"]+)"', self.html)[0]
        self._assert_error(
            _inject(self.html,
                    '<noscript><section class="slide" data-slide-id="%s"></section></noscript>'
                    % first),
            "duplicate slide id")
        # A finding only the scripting-DISABLED reading has is NAMED as such, so two readings of
        # one body never merge into a report that reads as a self-contradiction.
        self._assert_error(
            _inject(self.html, '<noscript><div class="deck-stage"></div></noscript>'),
            "(with scripting disabled)")

    def test_template_content_is_not_deck_structure_but_a_templated_editor_still_fails(self):
        # A <template> holds a fragment a browser renders nowhere, and the runtime finds the stage
        # and viewport with root.querySelector(".deck-stage") / ".deck-viewport", which reaches
        # neither a template fragment nor a shadow root a declarative template attaches - so a deck
        # whose only structure is parked in one has no structure at all.
        errs = deck_validate.deck_checks(_wrap(
            "<template><div class=\"deck-viewport\"><div class=\"deck-stage\">"
            "<section class=\"slide\" data-slide-id=\"slide-00000001\"></section>"
            "</div></div></template>prefers-reduced-motion"))
        self.assertTrue(any("deck-viewport" in e for e in errs), errs)
        self.assertTrue(any("deck-stage" in e for e in errs), errs)
        self.assertTrue(any('class="slide"' in e for e in errs), errs)
        # ...and a templated demo beside the real stage does not make a second one.
        self.assertEqual(
            _errors(_inject(self.html, '<template><div class="deck-stage"></div></template>')), [])
        # The EDITOR guard stays inclusive of templates and fails CLOSED: an <edit-toggle> parked
        # in one is still upstream editor chrome a generated deck should not carry.
        self._assert_error(
            _inject(self.html, "<template><edit-toggle></edit-toggle></template>"), "edit-toggle")

    def test_a_template_elements_own_class_is_still_structure(self):
        # Only the CONTENT of a <template> leaves the document tree; the element itself stays in
        # it, so root.querySelector(".deck-stage") really does return a <template class=deck-stage>
        # - and then finds no slides under it. Skipping the element as well as its subtree would
        # pass a deck that renders nothing.
        self._assert_error(
            _inject(self.html, '<template class="deck-stage"></template>'),
            "expected exactly one .deck-stage, found 2")
        self.assertEqual(_errors(_wrap(
            '<template class="deck-viewport"></template><div class="deck-stage">'
            '<section class="slide" data-slide-id="slide-00000001"></section>'
            "</div>prefers-reduced-motion")), [])

    def test_structure_in_a_foreign_namespace_is_still_structure(self):
        # An undeclared-namespace type selector and a class selector both match in ANY namespace,
        # so the runtime's own query finds these; filtering to ns == "html" would make this scan
        # disagree with the query it models.
        self.assertEqual(_errors(_wrap(
            '<div class="deck-viewport"><div class="deck-stage">'
            '<svg><section class="slide" data-slide-id="slide-00000001"></section></svg>'
            "</div></div>prefers-reduced-motion")), [])

    def test_a_class_or_slide_id_is_read_the_way_a_browser_resolves_the_attribute(self):
        # A duplicated attribute resolves FIRST-wins, and a character reference in the value is
        # decoded - both the shared reading, and neither visible to a raw double-quoted regex.
        self.assertEqual(_errors(_wrap(
            '<div class="deck&#45;viewport"><div class="deck&#45;stage">'
            '<section class="slide" data-slide-id="slide-00000001"'
            ' data-slide-id="not-valid"></section>'
            "</div></div>prefers-reduced-motion")), [])
        self._assert_error(
            _inject(self.html, '<div class="edit&#45;toggle"></div>'), "edit-toggle")

    def test_a_valueless_slide_id_reads_as_missing_not_as_an_empty_duplicate(self):
        # A valueless `data-slide-id` decodes to "" like an empty one, and neither names a slide.
        for attr in ("data-slide-id", 'data-slide-id=""'):
            with self.subTest(attr=attr):
                errs = deck_validate.deck_checks(_wrap(
                    '<div class="deck-viewport"><div class="deck-stage">'
                    '<section class="slide" %s></section>'
                    '<section class="slide" %s></section>'
                    "</div></div>prefers-reduced-motion" % (attr, attr)))
                self.assertTrue(any("missing data-slide-id" in e for e in errs), errs)
                self.assertFalse(any("duplicate slide id" in e for e in errs), errs)
                self.assertFalse(any("invalid data-slide-id" in e for e in errs), errs)

    def test_an_editor_named_only_in_script_text_is_not_the_editor(self):
        # The editor guard is an ELEMENT reading like the other three, so the upstream control's
        # markup quoted inside a <script> body - text to a browser - is not the editor. The real
        # control in either spelling still fails, which is what keeps the narrowing honest.
        self.assertEqual(_errors(_inject(
            self.html,
            "<script>var t = '<button class=\"edit-toggle\">edit</button>'"
            " + '<edit-toggle></edit-toggle>';</script>")), [])
        self._assert_error(_inject(self.html, "<edit-toggle></edit-toggle>"), "edit-toggle")
        self._assert_error(_inject(self.html, '<div class="edit-toggle"></div>'), "edit-toggle")

    def test_solidus_and_whitespace_separated_event_handler_fails(self):
        # HTML5 allows a solidus or any whitespace as an attribute separator; the parser catches both.
        self._assert_error(_inject(self.html, "<svg/onload=alert(1)></svg>"), "event-handler")
        self._assert_error(_inject(self.html, "<img\tonerror=alert(1) src=x>"), "event-handler")

    def test_entity_encoded_javascript_url_fails(self):
        # &#106; decodes to 'j' -> javascript:; the parser decodes character references before the check.
        self._assert_error(_inject(self.html, '<a href="&#106;avascript:alert(1)">x</a>'), "javascript:")

    def test_unquoted_remote_media_fails(self):
        for snippet in ("<img src=//evil.example/o.gif>", "<img src=https://evil/x.png>",
                        "<source srcset=//evil/x 1x>",
                        # The remote candidate SECOND, so a reader that only ever returned the head
                        # of the list would go blind while every other deck test stayed green.
                        '<img src="local.png" srcset="local.png 1x, https://evil/x.png 2x">'):
            with self.subTest(snippet=snippet):
                self._assert_error(_inject(self.html, snippet), "remote media/resource")

    def test_svg_image_and_use_remote_href_fails(self):
        self._assert_error(_inject(self.html, '<svg><image href="https://evil/x.svg"/></svg>'),
                           "remote media/resource")
        self._assert_error(_inject(self.html, '<svg><use xlink:href="//evil/x#i"/></svg>'),
                           "remote media/resource")

    def test_html_image_alias_background_and_image_set_egress_fail(self):
        # A bare <image> is rewritten to <img> by browsers (src/srcset fetch); the legacy
        # background attribute and a bare-string image-set() are egress too.
        for snippet, needle in (
            ('<image src="//evil/track.png">', "remote media/resource"),
            ('<image srcset="https://evil/x.png 1x">', "remote media/resource"),
            ('<td background="//evil/bg.png"></td>', "remote media/resource"),
            ('<div style="background:image-set(\'//evil/x.png\' 1x)">x</div>', "remote CSS url()"),
        ):
            with self.subTest(snippet=snippet):
                self._assert_error(_inject(self.html, snippet), needle)

    def test_svg_feimage_remote_href_fails(self):
        # An SVG filter primitive fetches exactly like an <image> or a <use>. The strict validator
        # and the offline export strip have covered it since #992; this gate did not, and outside
        # descriptor mode `offline` it is the ONLY checker a deck gets - so a deck could fetch
        # through one (#1179). `HTMLParser` lowercases the tag, so either spelling is caught.
        for snippet in ('<svg><filter><feImage href="https://evil/x.png"/></filter></svg>',
                        '<svg><filter><feImage xlink:href="//evil/x.png"/></filter></svg>',
                        '<svg><filter><feimage href="https://evil/x.png"/></filter></svg>'):
            with self.subTest(snippet=snippet):
                self._assert_error(_inject(self.html, snippet), "remote media/resource")

    def test_a_local_feimage_reference_is_not_reported(self):
        # The negative control for the rule above: `feImage` is overwhelmingly authored with a
        # LOCAL fragment reference into the same document, so a widening that rejected those would
        # be a false positive on the common case rather than a closed hole.
        for snippet in ('<svg><filter><feImage href="#local"/></filter></svg>',
                        '<svg><filter><feImage href="art/x.png"/></filter></svg>',
                        '<svg><filter><feImage xlink:href="data:image/png;base64,AAAA"/></filter>'
                        '</svg>'):
            with self.subTest(snippet=snippet):
                errs = _errors(_inject(self.html, snippet))
                self.assertEqual([e for e in errs if "remote media/resource" in e], [],
                                 (snippet, errs))

    def test_a_legacy_lowsrc_is_not_reported_as_egress_or_traversal(self):
        # `lowsrc` was retired from this gate in #1179: it does not load (HTML lists it as a
        # non-conforming legacy feature with no step in the loading algorithm, it has no
        # browser-compat entry, and it is measured not to fetch in the engine CI runs -
        # `tests/62-deck-regressions.spec.js`), the strict validator never had a rule for it and
        # the offline export strips none - so this gate was rejecting a deck over an inert
        # attribute, and the `_URL_ATTRS` membership that came with it reported an authored
        # `lowsrc="../x.png"` as a traversal as well.
        for snippet in ('<img lowsrc="https://evil/low.png" src="local.png">',
                        '<img lowsrc="../secret.png" src="local.png">'):
            with self.subTest(snippet=snippet):
                errs = _errors(_inject(self.html, snippet))
                self.assertEqual([e for e in errs
                                  if "remote media/resource" in e or "parent-directory" in e],
                                 [], (snippet, errs))

    # The deck gate reads a `srcset` with the SHARED candidate reader, so it agrees with the
    # strict validator and the offline strip. Splitting on the comma cut a `data:` URL in half at
    # its own media-type separator and rejected a deck that reaches no network at all (#1084).
    def test_a_data_srcset_candidate_carrying_a_comma_is_not_remote(self):
        for value in ("data:text/plain,https://evil.example/payload 1x",
                      "local.png (a,https://evil.example/x.png) 1x"):
            with self.subTest(value=value):
                errs = _errors(_inject(self.html, '<img src="local.png" srcset="%s">' % value))
                self.assertEqual([e for e in errs if "remote media/resource" in e], [], (value, errs))

    # The candidate list feeds the dangerous-scheme and traversal checks too, not only the remote
    # one, so the narrower candidates have a blast radius. A payload buried where HTML puts no
    # candidate boundary is not a candidate a browser ever acts on (measured: no request, no
    # `currentSrc`, no execution), while a genuine comma-separated one must still be rejected.
    def test_srcset_dangerous_scheme_and_traversal_follow_the_html_candidate_boundary(self):
        for value, needle in (
            ("local.png 1x, javascript:alert(1) 2x", "javascript:"),
            ("local.png 1x, data:text/html,<b>x</b> 2x", "javascript:"),
            ("local.png 1x, ../secret.png 2x", "parent-directory"),
        ):
            with self.subTest(value=value, rejected=True):
                self._assert_error(_inject(self.html, '<img src="local.png" srcset="%s">' % value),
                                   needle)
        for value in ("local.png (a,javascript:alert(1)) 1x",
                      "local.png (a,../secret.png) 1x",
                      "data:image/png,javascript:alert(1) 1x"):
            with self.subTest(value=value, rejected=False):
                errs = _errors(_inject(self.html, '<img src="local.png" srcset="%s">' % value))
                self.assertEqual([e for e in errs
                                  if "dangerous URL scheme" in e or "parent-directory" in e],
                                 [], (value, errs))

    # ...and it must be the SHARED reader, not a third reading that merely happens to agree on the
    # two values above. Compared over the same corpus that pins the exporter and the strict
    # validator to each other, so all three surfaces are held to one candidate boundary.
    def test_the_deck_gate_tokenizes_a_srcset_with_the_shared_candidate_reader(self):
        from checks.resources import srcset_candidate_urls
        for value in ("data:text/plain,https://evil.example/payload 1x",
                      "local.png 1x, https://evil.example/x.png 2x",
                      "local.png (a(b), https://evil.example/x.png) 1x",
                      "local.png, 1x, https://evil.example/x.png 2x",
                      "a.png,b.png 1x"):
            with self.subTest(value=value):
                self.assertEqual(deck_validate._srcset_urls(value),
                                 srcset_candidate_urls(value), value)

    # The deck gate used to decide "is this remote" with its own `^(?:https?:)?//`, which REQUIRES
    # the two slashes. The URL parser does not: its special-authority states CONSUME the slash run
    # after a special scheme, so `https:host/x.png`, `https:/host/x.png` and `https:\host/x.png`
    # all resolve to the same host as `https://host/x.png` and really are fetched. Outside
    # descriptor mode `offline` the base validator's media rules do not run, so for a deck this
    # gate is the only checker for `source[srcset]` - the miss was egress (#1129).
    def test_scheme_only_and_single_slash_remote_media_fails(self):
        for value in ("https:evil.example/x.png", "https:/evil.example/x.png",
                      "https:\\evil.example/x.png", "http:evil.example/x.png"):
            for snippet in ('<img src="%s">' % value,
                            '<img src="local.png" srcset="%s 1x">' % value,
                            '<picture><source srcset="%s 1x"></picture>' % value):
                with self.subTest(snippet=snippet):
                    self._assert_error(_inject(self.html, snippet), "remote media/resource")

    # ...and it must be the SHARED predicate, not a fourth reading that merely agrees on those
    # spellings: `checks/resources.py`'s `is_network_url` is what the strict validator and the
    # offline strip both ask, so all three surfaces agree about what a browser fetches.
    def test_the_deck_gate_decides_remote_with_the_shared_network_predicate(self):
        from checks.resources import is_network_url
        for value in ("https:host/x.png", "https:/host/x.png", "https:\\host/x.png",
                      "https://host/x.png", "//host/x.png", "\\\\host/x.png", "https://",
                      "https:", "HTTPS:host/x.png", "//", "///", "//?q", "//#f",
                      "////host/x.png", "assets/local.png", "./img/local.png", "local.png",
                      "data:image/png;base64,AAAA", "data:text/plain,//host/x", "",
                      "file://host/x.png", "file:///C:/x.png", "file://localhost/x.png",
                      "file://localhost//host/x.png", "file:////host/x.png", "file://C:/x.png",
                      "file:///C:/a//b.png", "#anchor", "?q=1", "ftp://host/x.png",
                      "ws://host/x", "\thttps:/host/x.png", "\u00a0//host/x.png",
                      "\x01\x0bhttps://host/x.png", "  //host/x.png"):
            with self.subTest(value=value):
                self.assertEqual(deck_validate._is_remote_url(value), is_network_url(value), value)

    # Widening the predicate must add no FALSE rejection: the existing deck controls still pass.
    def test_widening_the_remote_predicate_adds_no_false_rejection(self):
        for snippet in ('<img src="assets/local.png" alt="">',
                        '<img src="./img/local.png" alt="">',
                        '<img src="data:image/png;base64,AAAA" alt="">',
                        '<img src="local.png" srcset="local.png 1x, ./img/local.png 2x">',
                        '<picture><source srcset="data:image/png;base64,AAAA 1x"></picture>',
                        '<a href="https:evil.example/x">doc</a>'):
            with self.subTest(snippet=snippet):
                self.assertEqual(_errors(_inject(self.html, snippet)), [], snippet)

    # A broken/partial install warns and degrades to the strictly OVER-inclusive local reading, so
    # the gate still fails CLOSED on egress rather than crashing or waving a reference through.
    def test_a_broken_install_falls_back_to_the_over_inclusive_remote_reading(self):
        saved = deck_validate.is_network_url
        deck_validate.is_network_url = None
        try:
            for value in ("https:evil.example/x.png", "https:/evil.example/x.png",
                          "https:\\evil.example/x.png", "https://evil.example/x.png",
                          "//evil.example/x.png", "\\\\evil.example\\x.png",
                          "  https:evil.example/x.png", "ht\ttps:evil.example/x.png"):
                with self.subTest(value=value, remote=True):
                    self.assertTrue(deck_validate._is_remote_url(value), value)
            for value in ("assets/local.png", "./img/local.png", "local.png", "",
                          "data:image/png;base64,AAAA", "#anchor"):
                with self.subTest(value=value, remote=False):
                    self.assertFalse(deck_validate._is_remote_url(value), value)
        finally:
            deck_validate.is_network_url = saved

    # The same slash-run blindness sat in the gate's CSS readings one line above the attribute one.
    # They now ask the SHARED `url()` / `@import` patterns the strict validator asks, and the
    # deck-only `image-set()` reader carries the same prefix.
    def test_scheme_only_and_single_slash_remote_css_fails(self):
        for snippet in ('<div style="background:url(https:evil.example/bg.png)">x</div>',
                        "<style>.x{background:url(https:/evil.example/bg.png)}</style>",
                        '<div style="background:image-set(\'https:evil.example/x.png\' 1x)">x</div>',
                        '<div style="background:image-set(\'https:/evil.example/x.png\' 1x)">x</div>'):
            with self.subTest(snippet=snippet):
                self._assert_error(_inject(self.html, snippet), "remote CSS url()")
        for snippet in ("<style>@import url(https:evil.example/x.css);</style>",
                        '<style>@import "https:/evil.example/x.css";</style>'):
            with self.subTest(snippet=snippet):
                self._assert_error(_inject(self.html, snippet), "remote CSS @import")

    def test_local_css_url_and_import_are_not_reported(self):
        for snippet in ('<div style="background:url(assets/bg.png)">x</div>',
                        "<style>.x{background:url('./img/bg.png')}</style>",
                        "<style>@import url(local.css);</style>",
                        '<div style="background:image-set(\'local.png\' 1x)">x</div>',
                        '<div style="background:image-set(url(\'a.png\') 1x, \'b.png\' 2x)">x</div>',
                        '<div style="background:image-set(\'data:image/png;base64,AAAA\' 1x, \'b.png\' 2x)">x</div>'):
            with self.subTest(snippet=snippet):
                self.assertEqual(_errors(_inject(self.html, snippet)), [], snippet)

    # An ASCII TAB inside a quoted CSS URL: the URL parser DELETES it, and CSS allows a raw tab
    # inside a string, so `url("//<TAB>host/x.png")` really is fetched from `//host/x.png` - but
    # the shared host-character class excludes tab, so the pattern only sees it in a tab-free copy
    # of the body. LF/CR need no such pass (a newline in a CSS string is a bad-string token and the
    # declaration is dropped). Found by the round-1 multi-duck panel: swapping in the shared
    # patterns without this pass DROPPED a spelling the gate's own regex used to catch.
    def test_a_tab_inside_a_quoted_css_url_is_still_remote(self):
        for snippet in ('<style>.x{background:url("//\tevil.example/x.png")}</style>',
                        '<style>.x{background:url("https://\tevil.example/x.png")}</style>',
                        '<div style=\'background:image-set("//\tevil.example/x.png" 1x)\'>x</div>'):
            with self.subTest(snippet=snippet):
                self._assert_error(_inject(self.html, snippet), "remote CSS url()")
        self._assert_error(_inject(self.html, '<style>@import "//\tevil.example/x.css";</style>'),
                           "remote CSS @import")

    # `image-set()` is a candidate LIST. Anchoring on the open paren read only the first one, so a
    # remote candidate at 2x sailed through while the 1x candidate was local.
    def test_a_later_image_set_candidate_is_still_remote(self):
        for value in ("'local.png' 1x, 'https://evil.example/x.png' 2x",
                      "'local.png' 1x, 'https:evil.example/x.png' 2x",
                      "'local.png' 1x, '//evil.example/x.png' 2x",
                      "local.png 1x, //evil.example/x.png 2x"):
            with self.subTest(value=value):
                self._assert_error(
                    _inject(self.html, '<div style="background:image-set(%s)">x</div>' % value),
                    "remote CSS url()")

    # The CSS reads pick their pattern per CALL, so a broken install's degraded reading is
    # reachable here. It must be a strict SUPERSET of the shared one: anything the shared pattern
    # calls remote, the fallback must too, or the degraded gate fails OPEN.
    def test_a_broken_install_falls_back_to_the_over_inclusive_css_reading(self):
        saved = (deck_validate.CSS_NETWORK_URL_RE, deck_validate.CSS_NETWORK_IMPORT_RE,
                 deck_validate.css_network_image_set)
        deck_validate.CSS_NETWORK_URL_RE = None
        deck_validate.CSS_NETWORK_IMPORT_RE = None
        deck_validate.css_network_image_set = None
        try:
            for snippet in ('<div style="background:url(https:evil.example/bg.png)">x</div>',
                            '<div style="background:url(//evil.example/bg.png)">x</div>',
                            "<style>.x{background:url(https:/evil.example/bg.png)}</style>",
                            '<div style="background:image-set(\'a.png\' 1x, \'https:e.example/x\' 2x)">x</div>'):
                with self.subTest(snippet=snippet, remote=True):
                    self._assert_error(_inject(self.html, snippet), "remote CSS url()")
            self._assert_error(_inject(self.html, "<style>@import url(https:evil.example/x.css);</style>"),
                               "remote CSS @import")
            for snippet in ('<div style="background:url(assets/bg.png)">x</div>',
                            "<style>@import url(local.css);</style>",
                            '<div style="background:image-set(\'local.png\' 1x)">x</div>'):
                with self.subTest(snippet=snippet, remote=False):
                    self.assertEqual(_errors(_inject(self.html, snippet)), [], snippet)
        finally:
            (deck_validate.CSS_NETWORK_URL_RE, deck_validate.CSS_NETWORK_IMPORT_RE,
             deck_validate.css_network_image_set) = saved

    # The `url()` and `@import` readings must BE the shared objects, not copies that agree today.
    def test_the_deck_gate_holds_the_shared_css_pattern_objects(self):
        from checks import resources
        self.assertIs(deck_validate.CSS_NETWORK_URL_RE, resources.CSS_NETWORK_URL_RE)
        self.assertIs(deck_validate.CSS_NETWORK_IMPORT_RE, resources.CSS_NETWORK_IMPORT_RE)
        self.assertIs(deck_validate.is_network_url, resources.is_network_url)
        # ...and so must the image-set reading: the whole PREDICATE, not just its pattern, because
        # the strict gate asks the same question in shareable mode (#1166) and a copy here that
        # merely agreed today is exactly the drift that split the two gates in the first place.
        self.assertIs(deck_validate.css_network_image_set, resources.css_network_image_set)
        self.assertIs(deck_validate.css_image_set_args, resources.css_image_set_args)
        self.assertIs(deck_validate._CSS_IMAGE_SET_RE, resources.CSS_NETWORK_IMAGE_SET_RE)
        self.assertIn(resources.CSS_NETWORK_PREFIX, deck_validate._CSS_IMAGE_SET_RE.pattern)
        self.assertIn(resources.CSS_HOST_CHAR, deck_validate._CSS_IMAGE_SET_RE.pattern)

    # The degraded ARGUMENT-LIST reader has the same superset duty as the degraded pattern: with the
    # shared reading gone it must still see a candidate the shared one sees. The `;`, `{` and `<`
    # cases are the ones a regex-shaped fallback got WRONG - each of those characters is legal
    # inside a quoted candidate (a `data:` payload carries `;`), and stopping there dropped every
    # candidate after it, so the degraded path failed OPEN (round-1 multi-duck panel, 6 of 8 ducks).
    def test_a_broken_install_falls_back_to_the_over_inclusive_image_set_reader(self):
        saved = (deck_validate.css_image_set_args, deck_validate.css_network_image_set)
        deck_validate.css_image_set_args = None
        deck_validate.css_network_image_set = None
        try:
            for snippet in (
                    '<div style="background:image-set(\'a.png\' 1x, \'//evil.example/x\' 2x)">x</div>',
                    '<div style="background:image-set(url(\'a.png\') 1x, \'https:e.example/x\' 2x)">x</div>',
                    '<div style="background:image-set(\'data:image/png;base64,AAAA\' 1x, '
                    "'//evil.example/x' 2x)\">x</div>",
                    '<div style="background:image-set(\'a{b.png\' 1x, \'//evil.example/x\' 2x)">x</div>',
                    '<div style="background:image-set(\'a<b.png\' 1x, \'//evil.example/x\' 2x)">x</div>',
                    # An escaped delimiter inside a candidate exercises the scanner's `\\` arm, the
                    # branch most likely to be lost if the two copies ever diverge.
                    '<div style="background:image-set(\'a\\)b.png\' 1x, \'//evil.example/x\' 2x)">x</div>'):
                with self.subTest(snippet=snippet, remote=True):
                    self._assert_error(_inject(self.html, snippet), "remote CSS url()")
            clean = '<div style="background:image-set(\'local.png\' 1x)">x</div>'
            self.assertEqual(_errors(_inject(self.html, clean)), [], clean)
        finally:
            (deck_validate.css_image_set_args, deck_validate.css_network_image_set) = saved

    # The duplicated degraded scanner is the one place the deck can silently drift from the shared
    # reader, and it is the path whose whole purpose is to fail closed - so the two are pinned to
    # each other over a corpus rather than by a handful of literals (round-2 panel, 4 ducks).
    def test_the_degraded_scanner_reads_the_same_argument_lists_as_the_shared_one(self):
        from checks import resources
        corpus = (
            "image-set('a.png' 1x, '//evil.example/x' 2x)",
            'image-set(url("a.png") 1x, "https://evil.example/x" 2x)',
            "image-set('data:image/png;base64,AAAA' 1x, '//evil/x' 2x)",
            "image-set('a{b.png' 1x, '//evil/x' 2x)",
            "image-set('a<b.png' 1x, '//evil/x' 2x)",
            "image-set('a\\)b.png' 1x, '//evil/x' 2x)",
            "image-set(url(a.png) type('image/png'), 'https:evil/x' 2x)",
            "image-set('a(b.png' 1x, 'https:/evil/x' 2x)",
            "background:image-set('local.png' 1x",          # never closes
            "image-set(",                                    # nothing after the open paren
            "image-set('x' 1x); background:image-set('//evil/y' 1x)",   # two lists
            "a { background: image-set('//evil/x' 1x) } b { color: red }",
            'a { background: image-set("broken\n} b { background: image-set(\'//evil/x\' 1x) }',
        )
        for text in corpus:
            with self.subTest(text=text):
                self.assertEqual(deck_validate._image_set_args_fallback(text),
                                 resources.css_image_set_args(text))

    # Declared, deliberate behavior, pinned so a later change is a decision rather than an
    # accident. (a) The CSS reads are a whole-body TEXT search, not a parse of style contexts, so a
    # slide that merely DISPLAYS remote CSS text is reported - the fail-closed direction, and the
    # gate's behavior before this change too. (b) An EMPTY authority is not reported: no browser
    # fetches from one, and reporting it would delete an author's value over a reference that
    # loads nothing (the shared predicate's own documented rule, now inherited here).
    def test_declared_css_reading_boundaries(self):
        self._assert_error(_inject(self.html, "<pre><code>url(https:example.test/x.png)</code></pre>"),
                           "remote CSS url()")
        for snippet in ('<div style="background:url(//)">x</div>',
                        '<div style="background:image-set(\'//\' 1x)">x</div>',
                        "<style>@import url(https://);</style>"):
            with self.subTest(snippet=snippet):
                self.assertEqual(_errors(_inject(self.html, snippet)), [], snippet)

    # An `image-set()` argument list is not `[^)]*`: the first `)` in real CSS is usually the one
    # closing a nested `url(...)` / `type(...)`, or a literal `)` inside a quoted candidate. A
    # regex that stopped there hid every candidate after it - the same missed 2x-DPR fetch, one
    # level out. Found by the round-2 multi-duck panel (6 of 8 ducks).
    def test_an_image_set_candidate_after_a_nested_paren_is_still_remote(self):
        for value in ('url("local.png") 1x, "https://evil.example/x.png" 2x',
                      "url(local.png) 1x, '//evil.example/x.png' 2x",
                      'url(a.png) type("image/png"), "https:evil.example/x.png" 2x',
                      '"a).png" 1x, "//evil.example/x.png" 2x',
                      # ...and a `data:` candidate's own `;` separator must not truncate the list
                      # before a later remote candidate either.
                      '"data:image/png;base64,AAAA" 1x, "//evil.example/x.png" 2x',
                      "'a(b.png' 1x, 'https:/evil.example/x.png' 2x"):
            with self.subTest(value=value):
                self._assert_error(
                    _inject(self.html, '<div style="background:image-set(%s)">x</div>' % value),
                    "remote CSS url()")

    # ...and the same reader must not run away: an UNCLOSED `image-set(` (in a code sample, say)
    # stops at the declaration boundary instead of swallowing the rest of the slide, where an
    # allowed external hyperlink would otherwise be reported as a remote CSS reference.
    def test_an_unclosed_image_set_does_not_swallow_the_rest_of_the_slide(self):
        for snippet in ('<pre><code>background:image-set(</code></pre>'
                        '<a href="https://learn.microsoft.com/x">doc</a>',
                        '<div style="background:image-set(\'local.png\' 1x">x</div>'
                        '<a href="https://learn.microsoft.com/x">doc</a>'):
            with self.subTest(snippet=snippet):
                self.assertEqual(_errors(_inject(self.html, snippet)), [], snippet)

    # Every C0 control the URL parser REMOVES from a reference, which CSS also permits inside a
    # quoted string: the old `\s*` reading caught the vertical tab and U+001C-U+001F, and CSS's own
    # whitespace class does not, so the normalized copy has to cover them all - not just the tab.
    def test_a_c0_control_inside_a_quoted_css_url_is_still_remote(self):
        for ctrl in ("\t", "\x0b", "\x0c", "\x01", "\x1c", "\x1f"):
            for snippet in ('<style>.x{background:url("%s//evil.example/x.png")}</style>',
                            '<div style=\'background:image-set("%s//evil.example/x.png" 1x)\'>x</div>'):
                with self.subTest(ctrl=repr(ctrl), snippet=snippet):
                    self._assert_error(_inject(self.html, snippet % ctrl), "remote CSS url()")
            with self.subTest(ctrl=repr(ctrl), at_import=True):
                self._assert_error(
                    _inject(self.html, '<style>@import "%s//evil.example/x.css";</style>' % ctrl),
                    "remote CSS @import")

    # A `<` is a legal CSS string character, so a CLOSED candidate list must keep the
    # quote-faithful reading: stopping at it would let `image-set("a<b.png" 1x, "//evil/x" 2x)`
    # hide the candidate a browser selects. (Raised by the Copilot reviewer on PR #1155.)
    def test_a_markup_character_inside_a_closed_image_set_candidate_does_not_hide_the_next_one(self):
        for value in ('"local<file.png" 1x, "//evil.example/x.png" 2x',
                      "'a>b.png' 1x, 'https:evil.example/x.png' 2x"):
            with self.subTest(value=value):
                self._assert_error(
                    _inject(self.html, '<div style="background:image-set(%s)">x</div>' % value),
                    "remote CSS url()")

    # The URL parser removes ASCII tab from ANYWHERE but every other C0 control only from the
    # LEADING run, so a mid-token control leaves a LOCAL reference local: normalizing it away would
    # reject a reference that loads nothing. (Raised by the Copilot reviewer on PR #1155.)
    def test_a_mid_token_c0_control_does_not_make_a_local_css_url_remote(self):
        for snippet in ('<style>.x{background:url("/\x01/evil.example/x.png")}</style>',
                        '<style>.x{background:url("/\x0b/evil.example/x.png")}</style>',
                        '<div style=\'background:image-set("/\x01/evil.example/x.png" 1x)\'>x</div>'):
            with self.subTest(snippet=snippet):
                self.assertEqual(_errors(_inject(self.html, snippet)), [], snippet)
        # ...while the tab, which the parser removes from anywhere, still is.
        self._assert_error(
            _inject(self.html, '<style>.x{background:url("/\t/evil.example/x.png")}</style>'),
            "remote CSS url()")

    def test_external_hyperlink_is_allowed(self):
        # A hyperlink to a remote page is NOT egress (nothing fetches on load); it must not be flagged.
        self.assertEqual(_errors(_inject(self.html, '<a href="https://learn.microsoft.com/x">doc</a>')), [])

    def test_injected_end_marker_does_not_truncate_validation(self):
        # A slide that contains the bare end-marker TEXT must not cut the region short and hide
        # later active content (the real markers are HTML comments; escaped text cannot forge one).
        self._assert_error(
            _inject(self.html, '<p>END: commentable-html - CONTENT</p><iframe src="x"></iframe>'),
            "iframe")

    def test_begin_marker_without_close_reports_missing_region(self):
        # A begin marker whose closing --> only appears at/after the end marker is malformed.
        html = "x" + deck_validate.BEGIN_MARK + " no close " + END_MARK + "y"
        errs = deck_validate.deck_checks(html)
        self.assertTrue(any("CONTENT region markers" in e for e in errs))

    def test_duplicate_active_content_is_deduplicated(self):
        errs = _errors(_inject(self.html, "<iframe src=a></iframe><iframe src=b></iframe>"))
        self.assertEqual(len([e for e in errs if "iframe" in e]), 1)

    def test_svg_and_external_scripts_fail_inline_chart_script_allowed(self):
        # An SVG-nested <script> (inline or external) executes on render; an external <script src>
        # fetches and runs remote code - both fail closed. An inline chart-init <script> is allowed.
        self._assert_error(_inject(self.html, '<svg><script href="https://evil/x.js"></script></svg>'),
                           "<script> inside <svg>")
        self._assert_error(_inject(self.html, "<svg><script>alert(1)</script></svg>"),
                           "<script> inside <svg>")
        self._assert_error(_inject(self.html, '<script src="https://evil/x.js"></script>'),
                           "external <script>")
        self.assertEqual(_errors(_inject(
            self.html, '<canvas id="c"></canvas><script>new Chart(document.getElementById("c"),{});</script>')), [])

    def test_stray_svg_close_and_benign_meta_are_handled(self):
        # An unbalanced </svg> must not push the depth negative (a later inline script stays allowed),
        # and a non-refresh <meta> is fine.
        self.assertEqual(_errors(_inject(
            self.html, "<svg></svg></svg><script>ok()</script><meta name='x' content='y'>")), [])

    def test_remote_link_base_and_meta_refresh_fail_local_link_allowed(self):
        self._assert_error(_inject(self.html, '<link rel="stylesheet" href="https://evil/x.css">'),
                           "remote media/resource")
        self._assert_error(_inject(self.html, '<base href="https://evil/">'), "remote media/resource")
        self._assert_error(_inject(self.html, '<meta http-equiv="refresh" content="0;url=https://evil">'),
                           "refresh")
        self.assertEqual(_errors(_inject(self.html, '<link rel="stylesheet" href="local.css">')), [])

    def test_main_prints_base_warnings_and_strict(self):
        import contextlib
        import io
        from unittest import mock
        valid = os.path.join(self.tmp, "warn2.html")
        Path(valid).write_text(self.html, encoding="utf-8")
        with mock.patch.object(deck_validate, "validate_deck", return_value=([], ["w1"], [])):
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(deck_validate.main([valid]), 0)          # warnings printed, not failing
                self.assertEqual(deck_validate.main(["--strict", valid]), 1)  # strict promotes to failure

    def test_main_advisory_warning_does_not_fail_strict(self):
        # CMH-VAL-18: the deck path shares the advisory contract. A deliberately hand-written
        # inert code block cannot be cleared by the author, so `deck_validate.py --strict` - the
        # command the skill tells deck authors to finish with - must not block on it, exactly as
        # validate.py --strict and finalize.py --strict do not.
        import contextlib
        import io
        from unittest import mock
        import validate as base
        valid = os.path.join(self.tmp, "warn3.html")
        Path(valid).write_text(self.html, encoding="utf-8")
        advisory = base.HIGHLIGHT_ADVISORY_PREFIX + "a hand-written span"
        with mock.patch.object(deck_validate, "validate_deck", return_value=([], [advisory], [])):
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(deck_validate.main(["--strict", valid]), 0)
        with mock.patch.object(deck_validate, "validate_deck",
                               return_value=([], [advisory, "w1"], [])):
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(deck_validate.main(["--strict", valid]), 1)


if __name__ == "__main__":
    unittest.main()
