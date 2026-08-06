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
            m = deck_scaffold.SECTION_RE.search(prepared)
            self.assertIsNotNone(m, attrs)
            # BOTH sides are read the way a browser reads them - an absent value IS the empty
            # string - so this pins the round trip itself and not the spelling that achieves it.
            # An authored EMPTY value collapses into the same bucket, which is the point: the two
            # are one attribute to a browser and must come back as one. The expected class is
            # DERIVED from the input's own tokens, so a case whose class is not exactly `slide`
            # does not fail for a reason unrelated to fusion.
            got = norm(_browser_attrs.raw_attrs_pairs(m.group(1)))
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
                m.group(1),
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
