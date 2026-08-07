#!/usr/bin/env python3
"""Tests for deck/deck_scaffold.py (CMH-DECK-02).

The scaffolded deck must validate, be commentable-native (data-cmh-mode + fixed stage), give
every slide a stable data-slide-id with the first active, carry no inline editor or remote
fonts, and be create-only (refuse to overwrite unless --force).
"""
import html as _html
import os
from pathlib import Path
import re
import contextlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402

DECK = os.path.join(_paths.PKG, "tools", "deck")
sys.path.insert(0, DECK)
sys.path.insert(0, _paths.TOOLS)
import _browser_attrs  # noqa: E402
import deck_scaffold  # noqa: E402
import deck_validate  # noqa: E402
import validate as cmh_validate  # noqa: E402
from deck_common import SLIDE_ID_RE, slide_id  # noqa: E402

TOOL = os.path.join(DECK, "deck_scaffold.py")


@contextlib.contextmanager
def _partial_install():
    """`_browser_attrs` as a PARTIAL install sees it: the resolved decoder gone, every `_shared_*`
    binding it exposes gone with it, and the two classes bound at import (`BrowserTagNames`,
    `StartTagParser`) swapped for their fallbacks - patching `_shared_tag_names` alone would leave
    those still pointing at the shared ones, which is the hybrid this exists to avoid.

    Entered as a context manager so the patches go on in `__enter__` and come off in `__exit__`
    whatever happens: an `ExitStack` populated before the caller's `with` leaks every patch it
    already entered if a later one raises.
    """
    with contextlib.ExitStack() as stack:
        stack.enter_context(mock.patch.object(_browser_attrs, "_parsing", None))
        for name in dir(_browser_attrs):
            if name.startswith("_shared_"):
                stack.enter_context(mock.patch.object(_browser_attrs, name, None))
        stack.enter_context(mock.patch.object(_browser_attrs, "BrowserTagNames",
                                              _browser_attrs._FallbackTagNames))
        stack.enter_context(mock.patch.object(_browser_attrs, "StartTagParser",
                                              _browser_attrs._start_tag_parser(None)))
        yield


def _scaffold(out, *args):
    return subprocess.run(
        [sys.executable, TOOL, "--label", "Test Deck", "--source", out, "--out", out, *args],
        capture_output=True, text=True, encoding="utf-8",
    )


class DeckScaffoldTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        self.out = os.path.join(self.tmp, "deck.html")

    def _make(self, *args):
        proc = _scaffold(self.out, *args)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return Path(self.out).read_text(encoding="utf-8")

    def test_scaffold_is_valid_and_commentable_native(self):
        html = self._make("--slides", "3")
        errors, _ = cmh_validate.validate(self.out)
        self.assertEqual(errors, [], errors)
        self.assertIn('class="deck-viewport"', html)
        self.assertIn('class="deck-stage"', html)
        # data-cmh-mode must be on the REAL content root (the last one). If the template still
        # ships a decoy <main id="commentRoot"> (older templates carried one in a doc comment),
        # the first root must NOT carry deck mode; a single-root template is also valid.
        roots = re.findall(r'<main[^>]*id="commentRoot"[^>]*>', html)
        self.assertGreaterEqual(len(roots), 1)
        self.assertIn('data-cmh-mode="deck"', roots[-1])
        if len(roots) > 1:
            self.assertNotIn("data-cmh-mode", roots[0])

    def test_slides_have_stable_ids_first_active(self):
        html = self._make("--slides", "3")
        ids = re.findall(r'data-slide-id="([^"]+)"', html)
        self.assertEqual(len(ids), 3)
        for sid in ids:
            self.assertRegex(sid, SLIDE_ID_RE)
        self.assertEqual(len(set(ids)), 3)
        self.assertIn('class="slide active"', html)
        self.assertEqual(html.count('class="slide active"'), 1)

    def test_scaffold_normalizes_ai_typography_in_slide_prose(self):
        # CMH-ASCII-01: deck_scaffold rewrites AI smart-typography in slide prose to ASCII,
        # leaving code blocks verbatim.
        content = os.path.join(self.tmp, "slides.html")
        Path(content).write_text(
            '<section class="slide"><h2>Roadmap\u2014Q3</h2>'
            "<p>ship it \u2026 soon</p>"
            "<pre><code>a\u2014b</code></pre></section>",
            encoding="utf-8")
        html = self._make("--content", content)
        self.assertIn("Roadmap - Q3", html)
        self.assertIn("ship it ... soon", html)
        self.assertIn("a\u2014b", html)                 # code left verbatim
        self.assertNotIn("Roadmap\u2014Q3", html)

    def test_no_normalize_flag_preserves_ai_typography(self):
        content = os.path.join(self.tmp, "slides.html")
        Path(content).write_text(
            '<section class="slide"><h2>Roadmap\u2014Q3</h2><p>body text</p></section>',
            encoding="utf-8")
        html = self._make("--content", content, "--no-normalize")
        self.assertIn("Roadmap\u2014Q3", html)

    def test_scaffold_normalizes_ai_typography_in_label(self):
        # CMH-ASCII-01: the plain-text --label is normalized before it is baked into the title and
        # data-doc-label, even when it looks like markup.
        content = os.path.join(self.tmp, "slides.html")
        Path(content).write_text(
            '<section class="slide"><h2>Title</h2><p>body</p></section>', encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, TOOL, "--content", content, "--label", "Draft \u2014 <b>v1</b>",
             "--source", self.out, "--out", self.out],
            capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        html = Path(self.out).read_text(encoding="utf-8")
        self.assertNotIn("\u2014", html)   # no em-dash survives anywhere (title + data-doc-label)

    def test_deck_body_has_no_editor_fonts_or_script(self):
        html = self._make("--slides", "2")
        body = html.split("BEGIN: commentable-html - CONTENT", 1)[1].split(
            "END: commentable-html - CONTENT", 1)[0]
        self.assertNotIn("edit-toggle", body)
        self.assertNotIn("contenteditable", body)
        self.assertNotIn("<deck-stage", body)
        self.assertNotIn("data-deck-active", body)
        self.assertNotIn("fonts.googleapis.com", body)
        self.assertNotIn("api.fontshare.com", body)
        self.assertNotIn("https://", body)   # no remote refs in the deck body
        self.assertNotIn("<script", body)    # no host script; the controller lives in the layer JS
        self.assertIn(".deck-stage {", body)  # the fixed-stage CSS is inlined

    def test_content_ids_preserved_and_missing_ones_minted(self):
        frag = os.path.join(self.tmp, "frag.html")
        Path(frag).write_text(
            '<section class="slide" data-slide-id="slide-deadbeef"><p>one</p></section>\n'
            '<section class="slide"><p>two</p></section>\n',
            encoding="utf-8",
        )
        html = self._make("--content", frag)
        ids = re.findall(r'data-slide-id="([^"]+)"', html)
        self.assertEqual(ids[0], "slide-deadbeef")
        self.assertRegex(ids[1], SLIDE_ID_RE)

    def test_a_slide_class_is_read_in_every_html_quoting_form(self):
        # CMH-VAL-21 clause 11 (#1139): `class\s*=\s*"([^"]*)"` read only the double-quoted form,
        # so `<section class='slide'>` and `<section class=slide>` - the same class to a browser -
        # were silently not slides at all, and, having no attribute-name boundary, the rewrite it
        # drives turned an unrelated `myclass="foo"` into `myclass="foo active"`.
        for spelling in ("class='slide'", "class=slide", 'class="slide"'):
            frag = os.path.join(self.tmp, "q.html")
            Path(frag).write_text("<section %s><p>body</p></section>\n" % spelling, encoding="utf-8")
            out = self._make("--content", frag, "--force")
            self.assertEqual(len(re.findall(r'data-slide-id="([^"]+)"', out)), 1, spelling)
            self.assertNotIn('myclass="foo active"', out)
        frag = os.path.join(self.tmp, "decoy.html")
        Path(frag).write_text(
            '<section myclass="foo" class="slide"><p>body</p></section>\n', encoding="utf-8")
        out = self._make("--content", frag, "--force")
        self.assertIn('myclass="foo"', out,
                      "an unrelated attribute whose name ENDS in `class` must not be rewritten")
        # A `class=` spelled inside ANOTHER attribute's quoted value is not the class either. The
        # scaffold reads it correctly now (it parses the start tag); the deck VALIDATOR's
        # structural scan still matches such a decoy, which is issue #1159, so this pins the
        # scaffold's own reading through `prepare_slides` rather than an end-to-end scaffold.
        prepared, sids = deck_scaffold.prepare_slides(
            '<section title=\' class="slide"\'><p>decoy</p></section>')
        self.assertEqual(sids, [])
        self.assertNotIn("data-slide-id", prepared)

    def test_the_active_class_lands_only_on_the_first_slide(self):
        # CMH-DECK-02 promises the FIRST slide is `.active`. An input fragment that already marks a
        # later slide active must be NORMALIZED, not carried through: a deck with `active` on two
        # slides (or on the wrong one) opens on the wrong slide, and the deck contract now refuses
        # it (CMH-DECK-04), so the scaffold has to emit the deck that contract accepts. `visible`
        # goes with it - the runtime toggles the two in lockstep, and the vendored
        # `viewport-base.css` shows a slide on EITHER, so a later slide left `visible` paints
        # stacked over the one the deck opens on.
        prepared, sids = deck_scaffold.prepare_slides(
            '<section class="slide"><p>one</p></section>'
            '<section class="slide active"><p>two</p></section>'
            "<section class='slide &#97;ctive'><p>three</p></section>"
            '<section class="slide visible"><p>four</p></section>')
        self.assertEqual(len(sids), 4)
        self.assertEqual(prepared.count(" active"), 1)
        self.assertNotIn("visible", prepared)
        self.assertIn('class="slide active"', prepared)
        frag = os.path.join(self.tmp, "later-active.html")
        Path(frag).write_text(
            '<section class="slide"><p>one</p></section>'
            '<section class="slide active"><p>two</p></section>\n', encoding="utf-8")
        html = self._make("--content", frag, "--force")
        self.assertEqual(html.count('class="slide active"'), 1)
        self.assertEqual(deck_validate.deck_checks(html), [])

    def test_the_active_class_lands_only_on_the_first_live_slide(self):
        # The first slide is the first one a BROWSER renders, decided by the SHARED parse
        # (`deck_validate.first_live_slide_offset`). `_section_tags` already keeps a `<section>`
        # inside a comment or a raw-text body out of the walk (#1197), but a `<template>` SUBTREE
        # is tokenized all the same while a browser renders it nowhere - so letting a templated
        # slide consume the FIRST-slide position would put `.active` on markup nothing shows and
        # leave every real slide without it, which the deck contract then REFUSES.
        for inert in (
                '<template><section class="slide"><p>tpl</p></section></template>',
                '<template><template><section class="slide"><p>in</p></section></template>'
                '<section class="slide"><p>tail</p></section></template>',
                '<!-- dropped: <section class="slide"><p>old</p></section> -->',
                "<script>var s = '<section class=\"slide\">x</section>';</script>",
                '<title><section class="slide">x</section></title>',
        ):
            with self.subTest(inert=inert[:24]):
                prepared, _ = deck_scaffold.prepare_slides(
                    inert + '<section class="slide"><p>one</p></section>'
                            '<section class="slide"><p>two</p></section>')
                self.assertEqual(prepared.count(" active"), 1, prepared)
                # ...and it is on the section that holds the first LIVE slide's content.
                head = prepared.partition("<p>one</p>")[0]
                self.assertIn("active", head[head.rindex("<section"):], prepared)

    def test_normalizing_deck_state_does_not_rewrite_a_non_live_sample(self):
        # Only a LIVE slide is normalized. A `<section class="slide active">` an author DISPLAYS as
        # sample text is not a slide, so stripping `active` from it would rewrite the document's
        # own content to satisfy a rule that does not apply to it.
        for sample in ('<title><section class="slide active">sample</section></title>',
                       '<textarea><section class="slide visible">sample</section></textarea>',
                       '<template><section class="slide active">tpl</section></template>'):
            with self.subTest(sample=sample[:12]):
                prepared, _ = deck_scaffold.prepare_slides(
                    '<section class="slide"><p>one</p></section>' + sample)
                self.assertIn("sample" if "sample" in sample else "tpl", prepared)
                tail = prepared[prepared.index(sample[:9]):]
                self.assertIn("active" if "active" in sample else "visible", tail, prepared)

    def test_a_slide_class_is_decoded_before_it_is_read_and_rewritten(self):
        # CMH-VAL-21 clause 11 (#1139): the start tag is PARSED, so a character reference is
        # decoded the way `classList` decodes it (`sl&#105;de` IS `slide`), and every value is
        # re-escaped once from its DECODED form - escaping the RAW text instead turned an authored
        # `x&amp;y` into the literal `x&amp;y`.
        frag = os.path.join(self.tmp, "entity.html")
        Path(frag).write_text(
            '<section class=\'sl&#105;de x&amp;y\'><p>body</p></section>\n', encoding="utf-8")
        out = self._make("--content", frag, "--force")
        self.assertEqual(len(re.findall(r'data-slide-id="([^"]+)"', out)), 1)
        self.assertIn('class="slide x&amp;y active"', out)
        self.assertNotIn("&amp;amp;", out)

    def test_an_existing_slide_id_is_read_in_every_html_quoting_form(self):
        # #1173: the ids already TAKEN in the fragment were collected with
        # `data-slide-id\s*=\s*"([^"]*)"`, the double-quoted form only, so a hand-authored
        # `data-slide-id='...'` or `data-slide-id=...` - the same id to a browser, and the one
        # `deck_validate` compares - was invisible and could be minted again for another slide.
        # The scaffold's own `deck_checks` gate then refused the deck it had just produced.
        body = "<p>two</p>"
        minted = slide_id(deck_scaffold._strip_tags(body), set())
        for spelling in ("data-slide-id='%s'" % minted, "data-slide-id=%s" % minted):
            frag = os.path.join(self.tmp, "taken.html")
            Path(frag).write_text(
                '<section class="slide" %s><p>one</p></section>\n'
                '<section class="slide">%s</section>\n' % (spelling, body),
                encoding="utf-8")
            out = self._make("--content", frag, "--force")
            ids = re.findall(r'data-slide-id="([^"]+)"', out)
            self.assertEqual(len(ids), 2, spelling)
            self.assertEqual(ids[0], minted, spelling)
            self.assertEqual(len(set(ids)), 2,
                             "%s is already taken and must not be minted again" % spelling)

    def test_an_existing_slide_id_is_decoded_before_it_is_compared(self):
        # The value compared is the BROWSER-DECODED one, matching `deck_validate`: an authored
        # `data-slide-id="slide&#45;deadbeef"` IS `slide-deadbeef` to a browser, so a second slide
        # must not mint that id. Comparing the RAW text instead reads the two as different and
        # produces the duplicate the deck contract then rejects.
        body = "<p>encoded</p>"
        minted = slide_id(deck_scaffold._strip_tags(body), set())
        frag = os.path.join(self.tmp, "encoded.html")
        Path(frag).write_text(
            '<section class="slide" data-slide-id="%s"><p>one</p></section>\n'
            '<section class="slide">%s</section>\n' % (minted.replace("-", "&#45;", 1), body),
            encoding="utf-8")
        out = self._make("--content", frag, "--force")
        ids = re.findall(r'data-slide-id="([^"]+)"', out)
        self.assertEqual(ids[0], minted)
        self.assertEqual(len(set(ids)), 2)
        # A `data-slide-id=` spelled inside ANOTHER attribute's quoted value is not an id at all.
        # The phantom is the id the slide's own body mints, so a raw SEARCH would have put it in
        # `taken` and forced this slide onto the `-2` collision branch; the parse leaves it alone.
        phantom = slide_id(deck_scaffold._strip_tags("<p>two</p>"), set())
        prepared, sids = deck_scaffold.prepare_slides(
            '<section class="slide" title=\' data-slide-id="%s"\'><p>two</p></section>' % phantom)
        self.assertEqual(sids, [phantom])
        self.assertIn('data-slide-id="%s"' % phantom, prepared)

    def test_a_duplicated_slide_id_keeps_the_first_occurrence(self):
        # HTML5 keeps the FIRST of a duplicated attribute, and `deck_validate` reads the parsed
        # (first) one - so a valueless or empty first `data-slide-id` names NO id, whatever a later
        # duplicate says. Taking the first NON-EMPTY one instead adopted an id the browser never
        # sees on BOTH sides: the slide kept the shadowed id, and the taken-id pre-scan reserved it,
        # pushing the SECOND slide - whose own body mints exactly that id - onto the `-2` branch.
        # The id is also written back ONCE, so a raw-text scan does not count the slide twice.
        body = "<p>two</p>"
        shadowed = slide_id(deck_scaffold._strip_tags(body), set())
        minted = slide_id(deck_scaffold._strip_tags("<p>one</p>"), set())
        for first in ("data-slide-id", 'data-slide-id=""'):
            frag = os.path.join(self.tmp, "dupe.html")
            Path(frag).write_text(
                '<section class="slide" %s data-slide-id="%s"><p>one</p></section>\n'
                '<section class="slide">%s</section>\n' % (first, shadowed, body),
                encoding="utf-8")
            out = self._make("--content", frag, "--force")
            self.assertEqual(re.findall(r'data-slide-id="([^"]+)"', out), [minted, shadowed], first)

    def test_a_valueless_attribute_cannot_fuse_with_the_next_one(self):
        # #1191: the rewrite RE-SERIALIZES the start tag from the parsed pairs, and a valueless
        # attribute was written back as a bare name - dropping the `/` HTML uses to terminate an
        # attribute name. Two ADJACENT valueless attributes whose second name legally begins with
        # `=` (the unexpected-equals-sign-before-attribute-name state) then FUSED into one attribute
        # WITH a value on the way through: `data-a/=onload` came back as `data-a =onload`, which
        # re-parses as `data-a="onload"`. Writing `name=""` is the same attribute to a browser (an
        # absent value IS the empty string) and cannot be terminated by the next name's `=`.
        def norm(pairs):
            return [(n, v or "") for n, v in pairs]

        for attrs in ('class="slide" data-a/=onload',
                      'class="slide" data-a/=x data-b',
                      'class="slide" hidden',
                      'class="slide" data-a=""',
                      'class="slide" data-a/=',
                      'class="slide" data-a/==x',
                      'class="slide" data-a=""/=x',
                      'class="slide active x" data-a/=onload'):
            prepared, sids = deck_scaffold.prepare_slides(
                "<section %s><p>x</p></section>" % attrs)
            self.assertEqual(len(sids), 1, attrs)
            secs = deck_scaffold._section_tags(prepared)
            self.assertEqual(len(secs), 1, attrs)
            # BOTH sides are read the way a browser reads them - an absent value IS the empty
            # string - so this pins the round trip itself and not the spelling that achieves it.
            # An authored EMPTY value collapses into the same bucket, which is the point: the two
            # are one attribute to a browser and must come back as one. The expected class is
            # DERIVED from the input's own tokens, so a case whose class is not exactly `slide`
            # does not fail for a reason unrelated to fusion.
            got = norm(secs[0].pairs)
            in_pairs = norm(_browser_attrs.raw_attrs_pairs(attrs))
            classes = _browser_attrs.html_ws_tokens(
                next(v for n, v in in_pairs if n == "class"))
            if "active" not in classes:
                classes.append("active")
            want = [(n, " ".join(classes) if n == "class" else v) for n, v in in_pairs]
            want.append(("data-slide-id", sids[0]))
            self.assertEqual(got, want, attrs)
            # And the stronger FORM guard the fix rests on: EVERY attribute is written back in the
            # one canonical ` name="value"` shape, so none is left bare for a following name's `=`
            # to terminate. Asserting the whole attribute region equals that reconstruction is what
            # keeps a later "simplification" from quietly reintroducing a bare spelling. It also
            # deliberately rules out the other faithful spelling, re-emitting the `/` name
            # terminator (` data-a/`): that one lands as the self-closing `/>` solidus whenever the
            # valueless attribute is written LAST - reachable whenever the tag already carries a
            # `data-slide-id`, since nothing is appended after it - while `name=""` is the same
            # attribute to a browser in every position.
            self.assertEqual(
                secs[0].attrs,
                "".join(' %s="%s"' % (n, _html.escape(v, quote=True)) for n, v in got), attrs)
        # End to end, through both gates: the fix makes the scaffold emit an attribute literally
        # NAMED `=onload`, so pin that the base validator and the deck contract still accept it and
        # the deck is written - otherwise a later tightening could turn a writable deck into a hard
        # failure with nothing recording the loss.
        frag = os.path.join(self.tmp, "fuse.html")
        Path(frag).write_text(
            '<section class="slide" data-a/=onload><p>x</p></section>\n', encoding="utf-8")
        out = self._make("--content", frag, "--force")
        self.assertIn('<section class="slide active" data-a="" =onload="" data-slide-id=', out)

    def test_a_slide_start_tag_ends_where_the_shared_reading_ends_it(self):
        # #1197, direction one. HTML opens a quoted attribute value only AFTER an `=`, and its
        # attribute-NAME state takes a stray `"` straight into the name - so
        # `<section class="slide" a"b>` is a real slide carrying an attribute literally named
        # `a"b`, and the shared start-tag scan ends it at that `>`. The scaffold's own
        # quote-aware `<section ...>` regex opened a quoted run at ANY quote instead, ran past
        # the tag's own `>` hunting for a closing one, and SKIPPED the slide entirely: it got no
        # `data-slide-id` and `.active` landed on slide TWO.
        frag = ('<section class="slide" a"b><h2>One</h2></section>\n'
                '<section class="slide"><h2>Two</h2></section>\n'
                '<section class="slide"><h2>Three</h2></section>\n')
        # Pinned against the shared reading rather than against this test's own opinion of HTML.
        self.assertEqual(_browser_attrs.scan_start_tag(frag, 0)[0], frag.index(">") + 1)
        prepared, ids = deck_scaffold.prepare_slides(frag)
        self.assertEqual(len(ids), 3, prepared)
        self.assertEqual(len(set(ids)), 3, ids)
        first = prepared.split("</section>")[0]
        self.assertIn('class="slide active"', first)
        self.assertIn('data-slide-id="%s"' % ids[0], first)
        self.assertEqual(prepared.count("active"), 1, prepared)
        # The attribute a browser sees survives the round trip, named exactly as authored.
        self.assertIn('a"b=""', first)
        # End to end: all three slides reach the written deck, and the deck contract passes.
        content = os.path.join(self.tmp, "quoteinname.html")
        Path(content).write_text(frag, encoding="utf-8")
        html = self._make("--content", content)
        self.assertEqual(len(re.findall(r'data-slide-id="([^"]+)"', html)), 3)

    def test_a_start_tag_a_browser_discards_never_becomes_a_live_slide(self):
        # #1197, direction two, and the one worth closing: `<section class=slide foo" bar="x>`
        # reaches the end of the input inside a quoted value, so HTML5's eof-in-tag error
        # DISCARDS the whole tag - a browser builds no `<section>` here at all. The quote-aware
        # regex matched it anyway and the rewrite RE-SERIALIZED it into a well-formed
        # `<section class="slide active" foo"="" bar="" data-slide-id=...>` that the deck contract
        # then passed: markup a browser throws away turned into a live slide, with nothing able to
        # tell. It must stay exactly as authored, and the scaffold must fail closed.
        frag = '<section class=slide foo" bar="x><h2>Ghost</h2></section>\n'
        self.assertIsNone(_browser_attrs.scan_start_tag(frag, 0))
        prepared, ids = deck_scaffold.prepare_slides(frag)
        self.assertEqual(ids, [])
        self.assertEqual(prepared, frag)
        # The walk ABORTS at that tag rather than skipping it: a browser discards the tag AND
        # every character after the opening quote, so a later `<section class=slide>` is inside a
        # value a browser never leaves and is not a slide either. Pinning it with a SECOND section
        # is what distinguishes abort from skip - a refactor to `continue` past the ghost would
        # resurrect slides a browser never builds and would otherwise pass every test. The trailing
        # markup carries NO quote, because a later `"` would CLOSE the runaway value and make this
        # one long, perfectly real start tag instead - which is what a browser does with it too,
        # and is why the eof-in-tag drop is a property of the whole fragment, not of the tag alone.
        two = frag + "<section class=slide><h2>Real</h2></section>\n"
        self.assertIsNone(_browser_attrs.scan_start_tag(two, 0))
        prepared_two, ids_two = deck_scaffold.prepare_slides(two)
        self.assertEqual(ids_two, [])
        self.assertEqual(prepared_two, two)
        content = os.path.join(self.tmp, "ghost.html")
        Path(content).write_text(frag, encoding="utf-8")
        proc = _scaffold(self.out, "--content", content)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("no <section", proc.stderr)
        self.assertFalse(os.path.exists(self.out))

    def test_a_custom_element_named_like_a_section_is_not_a_section(self):
        # HTML terminates a tag name at ASCII whitespace, `/` or `>` and folds it ASCII-ONLY, so
        # `<section-foo>` and `<\u017fection>` are CUSTOM ELEMENTS. The old `<section\b` matched
        # the first (a `-` ends a word) and Python's `re.IGNORECASE` - which folds UNICODE - the
        # second, and the rewrite emitted a real `<section>` in place of each: an element the
        # input never had, with the authored `</section-foo>` / `</\u017fection>` left behind as
        # an unknown end tag, so the phantom slide never closed and swallowed the real one.
        for tag in ("section-foo", "\u017fection", "sect\u0130on", "sect\u0131on"):
            frag = ('<%s class="slide"><p>x</p></%s>\n'
                    '<section class="slide"><p>y</p></section>\n' % (tag, tag))
            prepared, ids = deck_scaffold.prepare_slides(frag)
            self.assertEqual(len(ids), 1, tag)
            self.assertIn('<%s class="slide"><p>x</p></%s>' % (tag, tag), prepared, tag)
            self.assertIn('<section class="slide active" data-slide-id="%s"><p>y</p></section>'
                          % ids[0], prepared, tag)

    def test_an_end_tag_ends_where_html_ends_it(self):
        # A browser ends an end tag at the first `>` OUTSIDE a quoted value, and it ignores (but
        # still TOKENIZES) any attributes on it - so `</section >` and `</section foo="a>b">` both
        # close the slide. A literal `</section>` search refuses them, and because the walk stops
        # when a section never closes, ONE such end tag left every later slide unscaffolded and
        # failed the whole deck on the contract - a benign document rejected.
        for close in ("</section >", "</section\n>", '</section foo="a>b">', "</SECTION>"):
            frag = ('<section class="slide"><p>x</p>%s\n'
                    '<section class="slide"><p>y</p></section>\n' % close)
            prepared, ids = deck_scaffold.prepare_slides(frag)
            self.assertEqual(len(ids), 2, close)
            self.assertIn('<section class="slide active" data-slide-id="%s"><p>x</p>%s'
                          % (ids[0], close), prepared, close)

    def test_a_section_spelled_inside_another_tags_attribute_value_is_not_a_slide(self):
        # The walk consumes every tag's WHOLE extent, so a `<section>` or `</section>` written
        # inside another tag's quoted attribute value is part of that value and never a candidate.
        # A raw search saw both: it would rewrite the decoy - inserting double quotes that break
        # the tag hosting it - and, for the closing one, end the real slide early.
        frag = ('<div title="<section class=\'slide\' a\'b>fake</section>">t</div>'
                '<section class="slide"><p>real</p></section>')
        prepared, ids = deck_scaffold.prepare_slides(frag)
        self.assertEqual(len(ids), 1)
        self.assertIn('<div title="<section class=\'slide\' a\'b>fake</section>">t</div>', prepared)
        self.assertIn('<section class="slide active" data-slide-id="%s"><p>real</p></section>'
                      % ids[0], prepared)
        frag = '<section class="slide"><div title="</section>">x</div></section>'
        prepared, ids = deck_scaffold.prepare_slides(frag)
        self.assertEqual(len(ids), 1)
        self.assertIn('<div title="</section>">x</div></section>', prepared)

    def test_a_start_tag_the_shared_tokenizer_stops_short_of_is_left_alone(self):
        # The rewrite re-serializes the start tag from the tokenizer's pairs, so a tokenization
        # that stopped BEFORE the tag's close would write the tag back with every attribute past
        # that point silently deleted. The two shared readings agree on every shape found today,
        # so this pins the guard itself: told the region was not fully consumed, the scaffold
        # treats the section as if it were not there - no id reserved, no id minted, no rewrite -
        # which fails the deck closed instead of writing a mangled slide.
        frag = '<section class="slide" data-keep="v"><p>x</p></section>'
        real = _browser_attrs.raw_attrs_pairs_consumed(' class="slide" data-keep="v"')
        self.assertTrue(real[1], "the shapes below no longer diverge; this guard is unpinned")
        with mock.patch.object(_browser_attrs, "raw_attrs_pairs_consumed",
                               lambda attrs: (real[0], False)):
            prepared, ids = deck_scaffold.prepare_slides(frag)
        self.assertEqual(ids, [])
        self.assertEqual(prepared, frag)

    def test_the_partial_install_locates_a_slide_where_the_shared_reading_does(self):
        # The degraded start-tag scan is a pinned COPY, not a pattern, for the same reason the
        # value decode and the NUL fold are: the scaffold RE-SERIALIZES the start tag it locates,
        # so a boundary drawn any other way on a partial install is not read differently - it is
        # WRITTEN into the deck. Both #1197 directions must come out the same either way.
        self.assertIsNotNone(_browser_attrs._shared_scan_start_tag,
                             "this host has no shared reading, so the parity check below would "
                             "compare the degraded answer with itself")
        self.assertIsNotNone(_browser_attrs._shared_end_tag_close)
        self.assertIsNotNone(_browser_attrs._shared_comment_close)
        cases = ('<section class="slide" a"b><h2>One</h2></section>\n'
                 '<section class="slide"><h2>Two</h2></section>',
                 '<section class=slide foo" bar="x><h2>Ghost</h2></section>',
                 '<section-foo class="slide"><p>x</p></section-foo>'
                 '<section class="slide"><p>y</p></section>',
                 '<\u017fection class="slide"><p>x</p></\u017fection>'
                 '<section class="slide"><p>y</p></section>',
                 '<section class="slide"><p>x</p></section foo="a>b">',
                 '<div title="<section class=\'slide\' a\'b>fake</section>">t</div>'
                 '<section class="slide"><p>real</p></section>',
                 '<!-- <a href="x -->\n<section class="slide">A</section>'
                 '<section class="slide">B</section>',
                 '<script>x = "unclosed;</script><section class="slide">A</section>')
        for frag in cases:
            shared = deck_scaffold.prepare_slides(frag)
            with _partial_install():
                self.assertEqual(deck_scaffold.prepare_slides(frag), shared, frag)

    def test_a_section_inside_a_comment_or_raw_text_is_not_markup(self):
        # A COMMENT and a raw-text `<script>` / `<style>` / `<textarea>` body are PROSE: markup
        # written there is text a reader sees, never an element. Tokenizing in one does not merely
        # find a decoy - a commented-out or scripted tag carrying an unterminated quoted value
        # runs a start-tag scan through everything after it, so the real slide that follows is
        # consumed inside the pseudo-tag's extent and DISAPPEARS. That loss is silent whenever the
        # lost slide already carries a `data-slide-id` (every slide `pptx_to_fragment` emits does),
        # because the deck contract then has nothing to object to.
        for label, before in (
                ("comment", '<!-- <a href="x -->\n'),
                ("script", '<script>if(a<b) x = "unclosed;</script>\n'),
                ("style", '<style>/* x = " */</style>\n'),
                ("textarea", '<textarea>x<y z = "q</textarea>\n')):
            frag = before + ('<section class="slide">A</section>\n'
                             '<section class="slide">B</section>\n')
            prepared, ids = deck_scaffold.prepare_slides(frag)
            self.assertEqual(len(ids), 2, label)
            self.assertIn(before, prepared, label)
            self.assertEqual(prepared.count("active"), 1, label)
        # ...and the plain decoy: a slide written inside a comment is not a slide, so it neither
        # takes `.active` nor reserves the id its own body would mint.
        frag = ('<!-- <section class="slide">draft</section> -->\n'
                '<section class="slide">real</section>')
        prepared, ids = deck_scaffold.prepare_slides(frag)
        self.assertEqual(len(ids), 1)
        self.assertIn('<!-- <section class="slide">draft</section> -->', prepared)
        # An UNTERMINATED comment runs to the end of the input, so everything after it is comment
        # data and there is no slide at all - which fails the deck closed rather than scaffolding
        # markup a browser never renders.
        frag = ('<!-- <section class="slide">draft</section>\n'
                '<section class="slide">real</section>')
        self.assertEqual(deck_scaffold.prepare_slides(frag), (frag, []))

    def test_a_section_inside_a_declaration_or_bogus_comment_is_not_markup(self):
        # A `<` that is not followed by an ASCII letter opens something that is NOT an element: a
        # markup declaration (`<!DOCTYPE ...>`) or a BOGUS COMMENT (`<?...`, a `<!` that is not a
        # comment, a `</` with no tag name), each of which a browser ends at its first `>`. A
        # `<section class="slide">` written inside one is a decoy - rewriting it would mint an id
        # for an element the document does not have and hand it `.active`, and the deck contract
        # would not object because it does not gate WHICH slide is active (#1218).
        real = '<section class="slide">real</section>'
        for label, before in (("doctype", "<!DOCTYPE html>\n"),
                              ("pi", '<?xml <section class="slide">decoy</section> ?>\n'),
                              ("bang", '<!x <section class="slide">decoy</section>>\n'),
                              ("slash", '</ <section class="slide">decoy</section>>\n'),
                              # `<![CDATA[` is character data only inside FOREIGN content, and the
                              # walk keeps no namespace stack, so it reads as the bogus comment it
                              # is in the HTML namespace - which still refuses the decoy.
                              ("cdata", '<svg><![CDATA[<section class="slide">decoy</section>]]>'
                                        "</svg>")):
            prepared, ids = deck_scaffold.prepare_slides(before + real)
            self.assertEqual(len(ids), 1, label)
            self.assertIn(before, prepared, label)          # left exactly as authored
            self.assertEqual(prepared.count("data-slide-id"), 1, label)
            self.assertIn('<section class="slide active" data-slide-id="%s">real</section>'
                          % ids[0], prepared, label)
        # A DOCTYPE is ordinary deck-fragment furniture and must not cost a slide.
        prepared, ids = deck_scaffold.prepare_slides(
            "<!DOCTYPE html>\n" + real + '<section class="slide">two</section>')
        self.assertEqual(len(ids), 2)

    def test_a_nested_section_is_body_content_not_a_slide(self):
        # The FIRST `</section>` closes a section, as the non-greedy regex this replaces did. That
        # is a deliberate divergence from a browser (which NESTS sections), and it is what keeps a
        # slide's body - and so the id minted from it - the same text the old scan hashed. A walk
        # that matched closers to openers instead would leave the slide COUNT unchanged and every
        # gate green while silently renaming the first slide, so the body is pinned, not the count.
        frag = ('<section class="slide">a<section>b</section>c</section>'
                '<section class="slide">z</section>')
        secs = deck_scaffold._section_tags(frag)
        self.assertEqual(len(secs), 2)
        self.assertEqual(frag[secs[0].tag_end:secs[0].inner_end], "a<section>b")
        prepared, ids = deck_scaffold.prepare_slides(frag)
        self.assertEqual(ids[0], slide_id(deck_scaffold._strip_tags("a<section>b"), set()))
        self.assertIn('<section class="slide active" data-slide-id="%s">a<section>b</section>'
                      % ids[0], prepared)

    def test_an_authored_cr_in_an_attribute_value_survives_the_rewrite(self):
        # #1196: the rewrite re-escapes each value, and `html.escape` does NOT escape CR - while
        # HTML's input-stream preprocessing turns every CR (and every CRLF) into a single LF BEFORE
        # tokenization. So the literal CR the rewrite wrote was not the character the input named:
        # an authored `title="a&#13;b"` came back as a `title` a browser reads as `a\nb`, silently
        # changing a value the author wrote. `&#13;` is decoded AFTER preprocessing, so it is the
        # spelling that round-trips.
        def browser_read(prepared, msg):
            # What a BROWSER sees, in the browser's ORDER: preprocessing runs over the written
            # TEXT first (CRLF and a lone CR alike become LF), and only then is the start tag
            # tokenized and its values decoded. Reading the raw text without that first step is
            # exactly what let the defect through - it reports the literal CR as if it survived.
            normalized = re.sub("\r\n?", "\n", prepared)
            secs = deck_scaffold._section_tags(normalized)
            self.assertEqual(len(secs), 1, msg)
            return dict(secs[0].pairs)

        for authored, want in (("a&#13;b", "a\rb"),
                               ("a&#13;&#10;b", "a\r\nb"),
                               ("&#13;", "\r"),
                               ("a&#xD;b", "a\rb")):
            prepared, sids = deck_scaffold.prepare_slides(
                '<section class="slide" title="%s"><p>x</p></section>' % authored)
            self.assertEqual(len(sids), 1, authored)
            self.assertEqual(browser_read(prepared, authored).get("title"), want, authored)
        # An LF is NOT re-escaped: preprocessing leaves it alone, so a literal LF already decodes
        # back to itself, and pinning it here keeps the fix to the one character that needs it.
        prepared, _ = deck_scaffold.prepare_slides(
            '<section class="slide" title="a&#10;b"><p>x</p></section>')
        self.assertIn('title="a\nb"', prepared)
        # End to end, through both gates: the deck the tool actually WRITES must carry the escaped
        # form and still pass the base validator and the deck contract, so a later tightening
        # cannot turn a writable deck into a hard failure with nothing recording the loss.
        frag = os.path.join(self.tmp, "cr.html")
        Path(frag).write_text(
            '<section class="slide" title="a&#13;b"><p>x</p></section>\n', encoding="utf-8")
        out = self._make("--content", frag, "--force")
        self.assertIn('title="a&#13;b"', out)
        errors, _ = cmh_validate.validate(self.out)
        self.assertEqual(errors, [], errors)

    def test_a_literal_cr_in_the_fragment_file_is_not_escaped_back_into_a_cr(self):
        # The other half of #1196. Escaping CR to `&#13;` is the right inverse ONLY because the
        # READ applies input-stream preprocessing too: a LITERAL CR in the fragment is a value a
        # browser reads as LF, so writing it back as `&#13;` would hand the deck a CR the input
        # never meant - the inverse of the bug the escape fixes.
        #
        # `deck_scaffold` gets that fold for free from `Path.read_text` / `sys.stdin.read`
        # (Python's default universal-newline mode), so what this pins is the READER belt: the
        # literal CRs are already LF before `raw_attrs_pairs` is reached, and a reader switched to
        # the CR-preserving `newline=""` would fail here. The fold itself is pinned separately, by
        # `test_shared_attr_decoding.InputStreamPreprocessingTests` - do not read this test as its
        # guard, or the fold looks removable.
        frag = os.path.join(self.tmp, "literal-cr.html")
        # Written with `newline=""` so Python's translation is disabled and the CRLF and the lone
        # CR reach the file verbatim; a default text write would translate them on the way out.
        with open(frag, "w", encoding="utf-8", newline="") as fh:
            fh.write('<section class="slide" title="a\r\nb\rc"><p>x</p></section>\n')
        self._make("--content", frag, "--force")
        # Asserted on BYTES. `_make` reads the deck back with `read_text`, which is itself
        # universal-newline, so a literal CR the tool wrote would already have become an LF by the
        # time a text assertion saw it - the positive half would pass either way.
        raw = Path(self.out).read_bytes()
        self.assertIn(b'title="a\nb\nc"', raw)
        # The `&#13;` check is scoped to the slide tag this tool RE-SERIALIZES. The runtime layer
        # the deck carries spells its own CR escape as the literal text `&#13;` (CMH-EXP-24), so a
        # file-wide search would answer about the layer's source rather than about the rewrite.
        # The literal-CR check stays file-wide: no part of a deck may carry one.
        at = raw.find(b'title="a\nb\nc"')
        self.assertNotEqual(at, -1, "no rewritten slide title in the scaffolded deck")
        tag = raw[raw.rfind(b"<", 0, at):raw.find(b">", at) + 1]
        self.assertNotIn(b"&#13;", tag)
        self.assertNotIn(b"\r", raw)


    def test_a_non_slide_section_does_not_reserve_a_slide_id(self):
        # Only a SLIDE's id is reserved. `deck_validate` reads ids from `section.slide` alone, so
        # reserving an unrelated section's would push a real slide onto the `-2` branch and make
        # that slide's supposedly stable id depend on content that is not a slide - deleting the
        # unrelated section would then silently rename the slide.
        body = "<p>two</p>"
        minted = slide_id(deck_scaffold._strip_tags(body), set())
        frag = os.path.join(self.tmp, "nonslide.html")
        Path(frag).write_text(
            '<section data-slide-id="%s"><p>not a slide</p></section>\n'
            '<section class="slide">%s</section>\n' % (minted, body), encoding="utf-8")
        out = self._make("--content", frag, "--force")
        self.assertIn('<section class="slide active" data-slide-id="%s">' % minted, out)

    def test_a_partial_install_rewrites_a_slide_without_losing_its_attributes(self):
        # `prepare_slides` RE-SERIALIZES every slide start tag from the pairs
        # `_browser_attrs.raw_attrs_pairs` hands back, so whatever the DEGRADED reading a partial
        # install falls back to answers differently is written into the deck - silently, and with
        # a zero exit, because the deck contract passes. A class-only stand-in there dropped every
        # other attribute; the host's own value decode rewrote an authored `x&ampy` as `x&y` and
        # DELETED the code points it considers invalid; and an unfolded NUL left a value the
        # rendered DOM never carries.
        self.assertIsNotNone(_browser_attrs._shared_raw_attrs_pairs,
                             "this host has no shared reading, so the parity check below would "
                             "compare the degraded answer with itself")
        frag = ('<section class="slide" id="intro" data-slide-id="slide-aaaaaaaa"'
                ' aria-label="Intro"><p>one</p></section>')
        hostile = ('<section class="slide" data\x00-x="v" aria-label="a\x00b" title="x&ampy"'
                   ' lang="&#1;"><p>two</p></section>')
        shared_out = (deck_scaffold.prepare_slides(frag), deck_scaffold.prepare_slides(hostile))
        with _partial_install():
            degraded, ids = deck_scaffold.prepare_slides(frag)
            degraded_hostile, hostile_ids = deck_scaffold.prepare_slides(hostile)
        self.assertEqual(ids, ["slide-aaaaaaaa"])
        self.assertEqual(degraded,
                         '<section class="slide active" id="intro"'
                         ' data-slide-id="slide-aaaaaaaa" aria-label="Intro">'
                         '<p>one</p></section>')
        self.assertIn('data\ufffd-x="v"', degraded_hostile)
        self.assertIn('aria-label="a\ufffdb"', degraded_hostile)
        self.assertIn('title="x&amp;ampy"', degraded_hostile)
        self.assertIn('lang="\x01"', degraded_hostile)
        # And it is the SAME deck the shared reading writes, so a partial install degrades nothing
        # a document can observe.
        self.assertEqual(shared_out, ((degraded, ids), (degraded_hostile, hostile_ids)))

    def test_a_partial_install_cannot_mint_a_valid_slide_id_from_an_invalid_one(self):
        # The id is the one attribute whose SHAPE is gated - `deck_validate` errors on anything
        # outside `SLIDE_ID_RE` (`slide-[0-9a-f]{8}(-N)?`), so a mangled one fails the scaffold
        # closed rather than shipping. But that gate is only as good as the decode feeding it. The
        # host's decode DELETES the code points it considers invalid, so an authored
        # `data-slide-id="slide-aaaaaaaa&#1;"` - which a browser reads as the SHAPE-INVALID
        # `slide-aaaaaaaa\x01`, and which therefore must fail closed - decoded to the perfectly
        # valid `slide-aaaaaaaa`, passed the contract and was written: the authored id silently
        # RENAMED, which is what create-only exists to prevent. The browser rule keeps the
        # character, so the shape gate sees what a browser sees on both readings.
        frag = '<section class="slide" data-slide-id="slide-aaaaaaaa&#1;"><p>x</p></section>'
        expected = "slide-aaaaaaaa\x01"
        self.assertFalse(SLIDE_ID_RE.match(expected))
        self.assertEqual(deck_scaffold.prepare_slides(frag)[1], [expected])
        with _partial_install():
            self.assertEqual(deck_scaffold.prepare_slides(frag)[1], [expected])

    def test_deterministic_ids(self):
        frag = os.path.join(self.tmp, "frag.html")
        Path(frag).write_text('<section class="slide"><p>stable body</p></section>\n', encoding="utf-8")
        a = self._make("--content", frag)
        b = self._make("--content", frag, "--force")
        self.assertEqual(re.findall(r'data-slide-id="([^"]+)"', a),
                         re.findall(r'data-slide-id="([^"]+)"', b))

    def test_create_only_then_force(self):
        self._make("--slides", "1")
        again = _scaffold(self.out, "--slides", "1")
        self.assertEqual(again.returncode, 1)
        self.assertIn("create-only", again.stderr)
        forced = _scaffold(self.out, "--slides", "1", "--force")
        self.assertEqual(forced.returncode, 0, forced.stderr)

    def test_fragment_without_slides_errors(self):
        frag = os.path.join(self.tmp, "empty.html")
        Path(frag).write_text("<section><p>not a slide</p></section>", encoding="utf-8")
        proc = _scaffold(self.out, "--content", frag)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("no <section", proc.stderr)


    def test_main_in_process_covers_branches(self):
        import contextlib
        import io
        from unittest import mock
        out = os.path.join(self.tmp, "ip.html")
        self.assertEqual(deck_scaffold.main(["--slides", "2", "--label", "L", "--out", out]), 0)
        # create-only refusal
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(deck_scaffold.main(["--slides", "2", "--label", "L", "--out", out]), 1)
        # --force overwrites
        self.assertEqual(deck_scaffold.main(["--slides", "2", "--label", "L", "--out", out, "--force"]), 0)
        # --slides 0 invalid
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(deck_scaffold.main(["--slides", "0", "--label", "L", "--out", os.path.join(self.tmp, "z.html")]), 1)
        # --content stdin, explicit key
        with mock.patch.object(sys, "stdin", io.StringIO('<section class="slide"><p>x</p></section>')):
            self.assertEqual(deck_scaffold.main(["--content", "-", "--label", "L", "--key", "deck-explicit-1",
                                                 "--out", os.path.join(self.tmp, "s.html"), "--force"]), 0)
        # fragment with no slide sections -> ValueError branch
        empty = os.path.join(self.tmp, "e.html")
        Path(empty).write_text("<section><p>nope</p></section>", encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(deck_scaffold.main(["--content", empty, "--label", "L",
                                                 "--out", os.path.join(self.tmp, "e2.html")]), 1)
        # refused (demo) key -> make_document ValueError branch
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(deck_scaffold.main(["--slides", "1", "--label", "L", "--key", "commentable-html-demo",
                                                 "--out", os.path.join(self.tmp, "demo.html")]), 1)
        # validator reports errors -> does-not-validate branch
        with mock.patch.object(deck_scaffold._validate, "validate", return_value=(["boom"], [])):
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(deck_scaffold.main(["--slides", "1", "--label", "L",
                                                     "--out", os.path.join(self.tmp, "inv.html")]), 1)
        # validator module unavailable -> skip-validation branch
        with mock.patch.object(deck_scaffold, "_validate", None):
            self.assertEqual(deck_scaffold.main(["--slides", "1", "--label", "L",
                                                 "--out", os.path.join(self.tmp, "noval.html")]), 0)


    def test_existing_ids_and_inject_targets_real_root(self):
        frag = os.path.join(self.tmp, "hasid.html")
        Path(frag).write_text(
            '<section class="slide" data-slide-id="slide-abcdef01"><p>keep</p></section>',
            encoding="utf-8")
        out = os.path.join(self.tmp, "hasid-out.html")
        self.assertEqual(deck_scaffold.main(["--content", frag, "--label", "L", "--out", out]), 0)
        self.assertIn('data-slide-id="slide-abcdef01"', Path(out).read_text(encoding="utf-8"))
        # _inject_deck_mode tags the root carrying the given key, never a decoy with a different key
        html = ('<main id="commentRoot" data-comment-key="my-doc">decoy</main>'
                '<main id="commentRoot" data-comment-key="real-123">real</main>')
        tagged = deck_scaffold._inject_deck_mode(html, "real-123")
        roots = re.findall(r'<main[^>]*id="commentRoot"[^>]*>', tagged)
        self.assertNotIn("data-cmh-mode", roots[0])
        self.assertIn('data-cmh-mode="deck"', roots[1])
        # no-op when the key is absent
        self.assertEqual(deck_scaffold._inject_deck_mode("<main>x</main>", "missing"), "<main>x</main>")
        # idempotent: a second injection does not add a second attribute
        tagged2 = deck_scaffold._inject_deck_mode(tagged, "real-123")
        self.assertEqual(tagged2.count('data-cmh-mode="deck"'), 1)

    def test_scaffold_declares_slides_kind(self):
        html = self._make("--slides", "2")
        self.assertIn('content="slides"', html)

    def test_scaffold_has_legible_presentation_defaults(self):
        html = self._make("--slides", "2")
        body = html.split("BEGIN: commentable-html - CONTENT", 1)[1].split(
            "END: commentable-html - CONTENT", 1)[0]
        # slide content gets an explicit light colour on the dark stage (legible in any theme)
        self.assertIn("--slide-fg", body)
        self.assertIn('data-cmh-mode="deck"] .slide', body)
        # and presentation-scale typography (a large heading size), so it does not render tiny
        self.assertRegex(body, r"font-size:\s*7[0-9]px")

    def test_scaffold_fails_closed_on_remote_media(self):
        # R1: deck_scaffold runs the deck contract (deck_checks), not just base validate.py, so a
        # slide carrying remote media fails closed and NOTHING is written to disk.
        frag = os.path.join(self.tmp, "remote.html")
        Path(frag).write_text(
            '<section class="slide"><img src="http://evil/x.png"><p>x</p></section>',
            encoding="utf-8")
        proc = _scaffold(self.out, "--content", frag)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("remote media", proc.stderr)
        self.assertFalse(os.path.exists(self.out))

    # CMH-STAMP-04: a scaffolded deck stamps the creating AI session id by default (flag or env),
    # records the agent, and suppresses it with --no-session-id.
    def test_scaffold_stamps_session_from_flag(self):
        from unittest import mock
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(deck_scaffold.main(
                ["--slides", "1", "--label", "L", "--out", self.out,
                 "--session-id", "deck-flag", "--agent", "claude"]), 0)
        html = Path(self.out).read_text(encoding="utf-8")
        self.assertIn('<meta name="commentable-html-session-id" content="deck-flag"', html)
        self.assertIn('<meta name="commentable-html-agent" content="claude"', html)

    def test_scaffold_stamps_session_from_environment_by_default(self):
        from unittest import mock
        with mock.patch.dict(os.environ, {"COPILOT_AGENT_SESSION_ID": "deck-env"}, clear=True):
            self.assertEqual(deck_scaffold.main(
                ["--slides", "1", "--label", "L", "--out", self.out]), 0)
        html = Path(self.out).read_text(encoding="utf-8")
        self.assertIn('<meta name="commentable-html-session-id" content="deck-env"', html)
        self.assertIn('<meta name="commentable-html-agent" content="copilot"', html)

    def test_scaffold_no_session_id_flag_suppresses(self):
        from unittest import mock
        with mock.patch.dict(os.environ, {"COPILOT_AGENT_SESSION_ID": "deck-env"}, clear=True):
            self.assertEqual(deck_scaffold.main(
                ["--slides", "1", "--label", "L", "--out", self.out, "--no-session-id"]), 0)
        html = Path(self.out).read_text(encoding="utf-8")
        # Check the meta TAG is absent, not the bare name string: the shareable deck inlines the
        # runtime JS, which references the meta name "commentable-html-session-id" dynamically.
        self.assertNotIn('<meta name="commentable-html-session-id"', html)


if __name__ == "__main__":
    unittest.main()
