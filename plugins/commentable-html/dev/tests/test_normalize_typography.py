#!/usr/bin/env python3
"""Tests for normalize_typography.py - the CMH-ASCII-01 AI-typography prose normalizer."""
import contextlib
import io
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402  shared pkg/dev split path constants
TOOLS = _paths.TOOLS
sys.path.insert(0, TOOLS)
import normalize_typography as nt  # noqa: E402

NORM_PY = os.path.join(TOOLS, "authoring", "normalize_typography.py")

EM = "\u2014"
EN = "\u2013"
ELL = "\u2026"
LDQ = "\u201C"
RDQ = "\u201D"
LSQ = "\u2018"
RSQ = "\u2019"
NBSP = "\u00A0"


class NormalizeProseTests(unittest.TestCase):
    def test_replaces_each_ai_character_in_prose(self):
        src = "<p>alpha%sbeta %s gamma%sdelta %squote%s %sit%ss%s</p>" % (
            EM, EN, ELL, LDQ, RDQ, LSQ, RSQ, NBSP)
        out, count = nt.normalize_typography(src)
        self.assertNotIn(EM, out)
        self.assertNotIn(EN, out)
        self.assertNotIn(ELL, out)
        self.assertNotIn(LDQ, out)
        self.assertNotIn(RDQ, out)
        self.assertNotIn(LSQ, out)
        self.assertNotIn(RSQ, out)
        self.assertNotIn(NBSP, out)
        self.assertIn("alpha - beta", out)
        self.assertIn("gamma...delta", out)
        self.assertIn('"quote"', out)
        self.assertIn("'it's", out)
        self.assertEqual(count, 8)

    def test_no_ai_characters_is_byte_identical(self):
        src = "<h1>Plain ASCII - only ... here</h1>"
        out, count = nt.normalize_typography(src)
        self.assertEqual(out, src)
        self.assertEqual(count, 0)

    def test_idempotent(self):
        src = "<p>a%sb %s c</p>" % (EM, ELL)
        once, _ = nt.normalize_typography(src)
        twice, count = nt.normalize_typography(once)
        self.assertEqual(once, twice)
        self.assertEqual(count, 0)

    def test_removes_zero_width_characters(self):
        # CMH-ASCII-01 claims zero-width removal; pin both U+200B and U+FEFF, not just NBSP.
        src = "<p>a\u200bb\ufeffc</p>"
        out, count = nt.normalize_typography(src)
        self.assertNotIn("\u200b", out)
        self.assertNotIn("\ufeff", out)
        self.assertIn("<p>abc</p>", out)
        self.assertEqual(count, 2)


class VerbatimRegionsTests(unittest.TestCase):
    def test_pre_and_code_are_untouched(self):
        src = "<p>text%shere</p><pre>code%sblock</pre><code>x%sy</code>" % (EM, EM, EM)
        out, count = nt.normalize_typography(src)
        self.assertIn("text - here", out)
        self.assertIn("<pre>code%sblock</pre>" % EM, out)   # em-dash preserved in code
        self.assertIn("<code>x%sy</code>" % EM, out)
        self.assertEqual(count, 1)                          # only the prose em-dash

    def test_script_and_style_are_untouched(self):
        src = ('<script id="embeddedComments" type="application/json">'
               '{"body":"a%sb"}</script>'
               "<style>.x::after{content:'%s'}</style>"
               "<p>real%sprose</p>") % (EM, ELL, EM)
        out, count = nt.normalize_typography(src)
        self.assertIn('{"body":"a%sb"}' % EM, out)           # comment JSON untouched
        self.assertIn("content:'%s'" % ELL, out)             # style untouched
        self.assertIn("real - prose", out)
        self.assertEqual(count, 1)

    def test_html_comment_is_untouched(self):
        src = "<!-- author note: a%sb -->\n<p>c%sd</p>" % (EM, EM)
        out, count = nt.normalize_typography(src)
        self.assertIn("<!-- author note: a%sb -->" % EM, out)
        self.assertIn("c - d", out)
        self.assertEqual(count, 1)

    def test_tag_attributes_are_not_broken(self):
        # A stray "<" in prose must not swallow following text as a fake tag.
        src = "<p>if a < b then a%sb</p>" % EM
        out, count = nt.normalize_typography(src)
        self.assertIn("a - b", out)
        self.assertEqual(count, 1)


class HtmlAwarenessTests(unittest.TestCase):
    def test_quoted_gt_in_attribute_does_not_leak_into_prose(self):
        # A ">" inside a quoted attribute must not end the tag early and rewrite machine data.
        src = '<div data-json=\'{"expr":"a > b","text":"x%sy"}\'>prose%shere</div>' % (EM, EM)
        out, count = nt.normalize_typography(src)
        self.assertIn('data-json=\'{"expr":"a > b","text":"x%sy"}\'' % EM, out)  # attribute untouched
        self.assertIn("prose - here", out)
        self.assertEqual(count, 1)

    def test_smart_quote_in_attribute_is_untouched(self):
        src = '<img alt="say %shi%s" title="A > B%sC">next%sline' % (LDQ, RDQ, EM, EM)
        out, count = nt.normalize_typography(src)
        self.assertIn('alt="say %shi%s"' % (LDQ, RDQ), out)      # attribute markup untouched
        self.assertIn('title="A > B%sC"' % EM, out)
        self.assertIn("next - line", out)                        # only the prose after the tag
        self.assertEqual(count, 1)

    def test_nested_code_tail_is_protected(self):
        src = "<code>outer%s<code>inner%s</code>tail%s</code>" % (EM, EM, EM)
        out, count = nt.normalize_typography(src)
        self.assertEqual(out, src)   # every dash sits inside a code element (incl. the tail)
        self.assertEqual(count, 0)

    def test_unclosed_verbatim_fails_closed(self):
        for opener in ("<pre>", "<code>", "<script>", "<style>", "<textarea>"):
            src = "<p>ok%sok</p>%scode%stail" % (EM, opener, EM)
            out, count = nt.normalize_typography(src)
            self.assertIn("ok - ok", out)                          # prose before the opener normalized
            self.assertIn("%scode%stail" % (opener, EM), out)      # unterminated body left verbatim
            self.assertEqual(count, 1, opener)

    def test_title_text_normalized_but_textarea_inert(self):
        src = "<title>Report%sQ3</title><textarea>draft%shere</textarea>" % (EM, EM)
        out, count = nt.normalize_typography(src)
        self.assertIn("Report - Q3", out)                          # title text is prose
        self.assertIn("<textarea>draft%shere</textarea>" % EM, out)  # textarea is inert/verbatim
        self.assertEqual(count, 1)

    def test_mixed_reconstruction_counts_only_prose(self):
        src = ('A%s<!--C%s--><script>S%s</script><pre>P%s</pre>'
               '<code>K%s</code><p title="T%s">Q%s</p>Z%s') % ((EM,) * 8)
        out, count = nt.normalize_typography(src)
        self.assertEqual(count, 3)                                 # only A..., Q..., Z... prose runs
        self.assertIn("<!--C%s-->" % EM, out)
        self.assertIn("<script>S%s</script>" % EM, out)
        self.assertIn("<pre>P%s</pre>" % EM, out)
        self.assertIn("<code>K%s</code>" % EM, out)
        self.assertIn('title="T%s"' % EM, out)
        self.assertTrue(out.startswith("A - "))
        self.assertTrue(out.endswith("Z - "))

    def test_many_unclosed_tags_are_linear(self):
        # The old regex was O(n^2)/ReDoS on many unterminated verbatim tags; the parser is linear.
        import time
        src = ("<script>" + ("a" * 20)) * 5000
        t0 = time.time()
        out, count = nt.normalize_typography(src)
        self.assertLess(time.time() - t0, 5.0)
        self.assertEqual(count, 0)

    def test_self_closing_verbatim_protects_tail(self):
        # HTML ignores the "/" on a non-void element, so <pre/> opens a pre; its tail is verbatim.
        for opener in ("<pre/>", "<code/>", "<script/>"):
            src = "%scode%stail" % (opener, EM)
            out, count = nt.normalize_typography(src)
            self.assertEqual(out, src, opener)
            self.assertEqual(count, 0, opener)

    def test_doctype_and_pi_with_quoted_gt_are_untouched(self):
        for src in (
            '<!DOCTYPE x " > %s "><p>%s</p>' % (EM, EM),
            '<?pi x=" > %s "?><p>%s</p>' % (EM, EM),
        ):
            out, count = nt.normalize_typography(src)
            self.assertIn(EM, out)              # the em-dash inside the declaration / PI is preserved
            self.assertIn("<p> - </p>", out)    # prose after it is still normalized
            self.assertEqual(count, 1, src)

    def test_misnested_verbatim_stays_protected(self):
        # </code> while <textarea> is the innermost open verbatim must not expose textarea content.
        src = "<code><textarea>x%s</code>tail%sz</textarea>after%sq" % (EM, EM, EM)
        out, count = nt.normalize_typography(src)
        self.assertEqual(out, src)   # everything sits inside a verbatim element; nothing normalized
        self.assertEqual(count, 0)

    def test_many_unmatched_end_tags_are_linear(self):
        # Non-verbatim tags never touch the verbatim stack, so unmatched closes stay O(1) each.
        import time
        src = ("<div>" * 20000) + ("</x>" * 20000) + "<p>a%sb</p>" % EM
        t0 = time.time()
        out, count = nt.normalize_typography(src)
        self.assertLess(time.time() - t0, 5.0)
        self.assertIn("a - b", out)
        self.assertEqual(count, 1)


class PlainTextTests(unittest.TestCase):
    def test_normalize_text_treats_input_as_literal(self):
        # A tag-like label is literal text, not markup: every AI char is normalized, tags and all.
        out, count = nt.normalize_text("AI %s <script>%s</script> %s done" % (EM, EM, ELL))
        self.assertNotIn(EM, out)
        self.assertNotIn(ELL, out)
        self.assertIn("<script>", out)   # the literal angle-bracket text survives
        self.assertEqual(count, 3)

    def test_normalize_text_plain(self):
        out, count = nt.normalize_text("Company %s Q3" % EM)
        self.assertNotIn(EM, out)
        self.assertEqual(count, 1)


class CliTests(unittest.TestCase):
    def _run(self, argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = nt.main(["normalize_typography.py"] + argv)
        return rc, buf.getvalue()

    def test_check_reports_and_leaves_file(self):
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False,
                                         encoding="utf-8", newline="") as fh:
            fh.write("<p>a%sb</p>" % EM)
            path = fh.name
        try:
            rc, out = self._run([path, "--check"])
            self.assertEqual(rc, 1)
            self.assertIn("AI character", out)
            with open(path, encoding="utf-8") as fh:
                self.assertIn(EM, fh.read())  # --check never writes
        finally:
            os.unlink(path)

    def test_in_place_rewrites(self):
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False,
                                         encoding="utf-8", newline="") as fh:
            fh.write("<p>a%sb</p>" % EM)
            path = fh.name
        try:
            rc, _ = self._run([path])
            self.assertEqual(rc, 0)
            with open(path, encoding="utf-8") as fh:
                data = fh.read()
            self.assertNotIn(EM, data)
            self.assertIn("a - b", data)
            rc2, _ = self._run([path, "--check"])
            self.assertEqual(rc2, 0)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
