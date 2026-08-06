from _validate_helpers import *


class LinkTargetTests(unittest.TestCase):
    """The validator warns when an author <a href> document reference inside
    #commentRoot opens in the SAME tab (an explicit target other than _blank), so a
    reviewer is not navigated away from the report and their comments (CMH-LINK-05)."""

    def _main(self, content):
        return ('<main id="commentRoot" data-cmh-content-root data-comment-key="k" data-doc-label="l" data-doc-source="s">\n'
                + content + "\n</main>")

    def _warns(self, content):
        errors, warnings = _validate_text(
            build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), self._main(content), JS_REGION]))
        self.assertEqual(errors, [], errors)
        return any("same tab" in w for w in warnings)

    def _sample(self, content):
        """The emitted same-tab warning text, which carries the deduped href samples."""
        errors, warnings = _validate_text(
            build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), self._main(content), JS_REGION]))
        self.assertEqual(errors, [], errors)
        return "".join(w for w in warnings if "same tab" in w)

    def test_relative_document_link_with_self_target_warns_cmh_link_05(self):
        self.assertTrue(self._warns('<p><a href="page.html" target="_self">x</a></p>'))

    def test_external_https_link_with_self_target_warns(self):
        self.assertTrue(self._warns('<p><a href="https://example.com/a" target="_self">x</a></p>'))

    def test_document_link_with_top_target_warns(self):
        self.assertTrue(self._warns('<p><a href="/guide" target="_top">x</a></p>'))

    def test_document_link_with_named_frame_target_warns(self):
        self.assertTrue(self._warns('<p><a href="https://example.com/b" target="viewer">x</a></p>'))

    def test_document_link_blank_target_ok(self):
        self.assertFalse(self._warns('<p><a href="page.html" target="_blank">x</a></p>'))

    def test_document_link_blank_target_case_insensitive_ok(self):
        self.assertFalse(self._warns('<p><a href="page.html" target="_BLANK">x</a></p>'))

    def test_document_link_no_target_ok(self):
        self.assertFalse(self._warns('<p><a href="page.html">x</a></p>'))

    def test_empty_target_warns_cmh_link_05(self):
        # An empty (or whitespace) target attribute is still an explicit same-tab target other than
        # _blank; the browser treats it as the current tab, so it is flagged like target="_self".
        self.assertTrue(self._warns('<p><a href="page.html" target="">x</a></p>'))
        self.assertTrue(self._warns('<p><a href="page.html" target="   ">x</a></p>'))

    def test_mailto_with_self_target_ok(self):
        self.assertFalse(self._warns('<p><a href="mailto:x@example.com" target="_self">x</a></p>'))

    def test_tel_with_self_target_ok(self):
        self.assertFalse(self._warns('<p><a href="tel:+15551234" target="_self">x</a></p>'))

    def test_javascript_with_self_target_ok(self):
        self.assertFalse(self._warns('<p><a href="javascript:void(0)" target="_self">x</a></p>'))

    def test_fragment_with_self_target_ok(self):
        self.assertFalse(self._warns('<p><a href="#section-2" target="_self">x</a></p>'))

    def test_cm_skip_link_with_self_target_ok(self):
        self.assertFalse(self._warns('<p class="cm-skip"><a href="page.html" target="_self">x</a></p>'))

    def test_protocol_relative_link_with_self_target_warns(self):
        self.assertTrue(self._warns('<p><a href="//example.com/p" target="_self">x</a></p>'))

    def test_control_char_obfuscated_scheme_is_exempt(self):
        # Browsers strip tab/CR/LF from a URL before parsing its scheme, so java&#9;script:
        # normalizes to javascript: and the runtime excludes it; the validator must match and
        # not misread the obfuscated scheme as a relative document reference (parity).
        self.assertFalse(self._warns('<p><a href="java&#9;script:void(0)" target="_self">x</a></p>'))
        self.assertFalse(self._warns('<p><a href="mai&#10;lto:x@example.com" target="_self">x</a></p>'))

    def test_svg_anchor_with_self_target_ok(self):
        # An SVG-namespaced <a> has tagName "a" (not "A"), so the runtime never stamps it; the
        # validator must not warn on it either (parity).
        self.assertFalse(self._warns('<p><svg><a href="https://example.com/s" target="_self">x</a></svg></p>'))

    def test_svg_foreignobject_html_anchor_warns_cmh_link_05(self):
        # An <a> inside an SVG <foreignObject> is at an HTML integration point (tagName "A"), so the
        # runtime DOES stamp it; the validator must warn on a same-tab target to keep parity.
        self.assertTrue(self._warns(
            '<p><svg><foreignObject><a href="page.html" target="_self">x</a></foreignObject></svg></p>'))

    def test_mathml_anchor_with_self_target_ok(self):
        # A MathML-namespaced <a> has tagName "a" too, so the runtime never stamps it either. The
        # exemption is the NAMESPACE, not the SVG ancestor: keyed on an svg ancestor this warned
        # about a link that has no problem, and check_links is fatal under --strict.
        self.assertFalse(self._warns('<p><math><a href="https://example.com/m" target="_self">x</a></math></p>'))

    def test_mathml_mtext_html_anchor_warns_cmh_link_05(self):
        # <mtext> is a MathML TEXT integration point, so its <a> child is inserted in the HTML
        # namespace (tagName "A") and the runtime DOES stamp it - the validator must warn.
        self.assertTrue(self._warns(
            '<p><math><mtext><a href="page.html" target="_self">x</a></mtext></math></p>'))

    def test_every_html_integration_point_anchor_is_still_checked(self):
        # `desc` and `title` are HTML integration points too (a mermaid <svg> routinely carries
        # them), and so is an `annotation-xml` whose encoding a browser matches EXACTLY - each puts
        # its <a> child in the HTML namespace, where the runtime stamps it. Reading the exemption
        # off an svg ANCESTOR exempted the first two; reading it off the namespace does not.
        for frag in ('<svg><desc><a href="page.html" target="_self">x</a></desc></svg>',
                     '<svg><title><a href="page.html" target="_self">x</a></title></svg>',
                     '<math><annotation-xml encoding="text/html">'
                     '<a href="page.html" target="_self">x</a></annotation-xml></math>'):
            self.assertTrue(self._warns("<p>" + frag + "</p>"), frag)

    def test_an_href_is_classified_the_way_a_browser_classifies_it(self):
        # #1156: the URL parser trims only C0 controls and space (U+0000-U+0020) from a URL's
        # ends. Python's argument-less `str.strip()` reaches past ASCII and also takes NBSP,
        # U+2028, U+3000 and U+0085, which the parser KEEPS - so the scheme regex matched at
        # position 0 for the validator, saw a non-document scheme, and skipped the check. A
        # browser keeps the character, finds no scheme there, and reads a RELATIVE reference:
        # the click navigates the reviewer's own tab away from the report and their comments,
        # which is exactly what this check exists to prevent.
        for pad in ("\u00a0", "\u2028", "\u3000", "\u0085"):
            for href in ("mailto:x@example.com", "tel:+15551234", "javascript:void(0)"):
                frag = '<p><a href="%s%s" target="_self">x</a></p>' % (pad, href)
                self.assertTrue(self._warns(frag), frag)
        # The true controls: a character Python's `str.strip()` removes TOO, so the verdict is
        # unchanged and the fix invents no warning about a link a browser reads as mailto:.
        for pad in ("", " ", "\t", "\u001f"):
            frag = '<p><a href="%smailto:x@example.com" target="_self">x</a></p>' % pad
            self.assertFalse(self._warns(frag), frag)
        # The OTHER direction of the same differential, which also changes: Python's `str.strip()`
        # does NOT remove a non-whitespace C0 control, so `href="&#x1;mailto:x"` used to read as a
        # relative document reference and WARN. The URL parser removes every C0 control from a
        # URL's ends, so a browser reads `mailto:` and the link is exempt - the warning was a false
        # positive, and the same goes for a padded fragment or an href made only of such controls.
        for href in ("\u0001mailto:x@example.com", "\u0008tel:+15551234",
                     "\u0001#section-2", "\u0001", "\t#section-2"):
            frag = '<p><a href="%s" target="_self">x</a></p>' % href
            self.assertFalse(self._warns(frag), frag)

    def test_the_reported_sample_is_deduped_by_the_same_reading(self):
        # The dedupe key that groups the reported samples applies the same cleanup the
        # classification does, so two spellings the cleanup makes identical are ONE entry ...
        one = self._sample('<p><a href="&#9;page.html" target="_self">x</a>'
                           '<a href="page.html&#13;" target="_self">y</a></p>')
        self.assertEqual(one.count("page.html"), 1, one)
        # ... and two that differ by a character the URL parser KEEPS stay separate, because a
        # browser really does resolve them to different documents.
        two = self._sample('<p><a href="&#xa0;page.html" target="_self">x</a>'
                           '<a href="page.html" target="_self">y</a></p>')
        self.assertEqual(two.count("page.html"), 2, two)

    def test_an_nbsp_padded_fragment_is_not_a_same_page_fragment(self):
        # #1156, the other half of the same trim: `href="&#xa0;#frag"` is NOT a same-page fragment.
        # The URL parser keeps the NBSP, so the reference resolves to a DIFFERENT document
        # (`%C2%A0#frag`) and an author-set `target="_self"` navigates the reviewer's own tab away
        # from the report and their comments. Python's `str.strip()` removed the NBSP, so the
        # `raw[0] == "#"` test exempted it as a same-page fragment.
        for pad in ("\u00a0", "\u2028", "\u3000", "\u0085"):
            frag = '<p><a href="%s#section-2" target="_self">x</a></p>' % pad
            self.assertTrue(self._warns(frag), frag)

    def test_a_padded_annotation_xml_encoding_anchor_is_exempt(self):
        # `encoding=" text/html"` is NOT an integration point (a browser matches the value
        # exactly), so the <a> stays MathML, has tagName "a", and is never stamped.
        self.assertFalse(self._warns(
            '<p><math><annotation-xml encoding=" text/html">'
            '<a href="page.html" target="_self">x</a></annotation-xml></math></p>'))
    def test_a_target_html_coerces_to_blank_is_not_reported_as_same_tab(self):
        # CMH-LINK-05 / CMH-LINK-01: the AUTHORED target is read through the shared
        # `effective_link_target`, so a name carrying both an ASCII tab-or-newline and a U+003C is
        # the `_blank` HTML replaces it with - a NEW tab. Reporting it as opening in the same tab
        # was a false positive, and a warning is fatal under --strict.
        for spelling in ("x&#10;&lt;", "&lt;&#9;x", "a&#13;b&lt;c"):
            self.assertFalse(self._warns('<p><a href="page.html" target="%s">x</a></p>' % spelling),
                             spelling)
        # The coercion needs BOTH characters, so these stay ordinary same-tab names and are still
        # reported - the fix removes a false positive, it does not blunt the check.
        for spelling in ("x&lt;", "x&#10;y", "viewer"):
            self.assertTrue(self._warns('<p><a href="page.html" target="%s">x</a></p>' % spelling),
                            spelling)

    def test_a_document_reference_with_no_target_is_exempt_whatever_the_base_says(self):
        # The document's `<base target>` is deliberately NOT fed into this check: its question is
        # whether the AUTHOR asked for the same tab, and the runtime overrides a document reference
        # to `_blank` regardless of the base, so inheriting one here would invent a warning about
        # markup the author never wrote on the link.
        for base in ('<base target="_self">', '<base target="_blank">', '<base target="viewer">'):
            self.assertFalse(self._warns(base + '<p><a href="page.html">x</a></p>'), base)


if __name__ == "__main__":
    unittest.main()
