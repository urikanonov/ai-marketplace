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

    def test_solidus_and_whitespace_separated_event_handler_fails(self):
        # HTML5 allows a solidus or any whitespace as an attribute separator; the parser catches both.
        self._assert_error(_inject(self.html, "<svg/onload=alert(1)></svg>"), "event-handler")
        self._assert_error(_inject(self.html, "<img\tonerror=alert(1) src=x>"), "event-handler")

    def test_entity_encoded_javascript_url_fails(self):
        # &#106; decodes to 'j' -> javascript:; the parser decodes character references before the check.
        self._assert_error(_inject(self.html, '<a href="&#106;avascript:alert(1)">x</a>'), "javascript:")

    def test_unquoted_remote_media_fails(self):
        for snippet in ("<img src=//evil.example/o.gif>", "<img src=https://evil/x.png>",
                        "<source srcset=//evil/x 1x>"):
            with self.subTest(snippet=snippet):
                self._assert_error(_inject(self.html, snippet), "remote media/resource")

    def test_svg_image_and_use_remote_href_fails(self):
        self._assert_error(_inject(self.html, '<svg><image href="https://evil/x.svg"/></svg>'),
                           "remote media/resource")
        self._assert_error(_inject(self.html, '<svg><use xlink:href="//evil/x#i"/></svg>'),
                           "remote media/resource")

    def test_html_image_alias_background_and_image_set_egress_fail(self):
        # A bare <image> is rewritten to <img> by browsers (src/srcset fetch); the legacy
        # background/lowsrc attributes and a bare-string image-set() are egress too.
        for snippet, needle in (
            ('<image src="//evil/track.png">', "remote media/resource"),
            ('<image srcset="https://evil/x.png 1x">', "remote media/resource"),
            ('<td background="//evil/bg.png"></td>', "remote media/resource"),
            ('<img lowsrc="https://evil/low.png" src="local.png">', "remote media/resource"),
            ('<div style="background:image-set(\'//evil/x.png\' 1x)">x</div>', "remote CSS url()"),
        ):
            with self.subTest(snippet=snippet):
                self._assert_error(_inject(self.html, snippet), needle)

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


if __name__ == "__main__":
    unittest.main()
