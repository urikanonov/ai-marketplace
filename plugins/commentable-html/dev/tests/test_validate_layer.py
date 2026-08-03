from _validate_helpers import *


class ValidateLayerStructureTests(ValidateAssertions, unittest.TestCase):
    def _with_content(self, content_html, css=None):
        """A valid document whose AUTHORED CONTENT region is `content_html`.

        The CMH-VAL-20 checks must read the layer's own markup, so their fixtures need content
        that is inside the CONTENT markers - where an author's prose legitimately quotes the
        layer's own CSS, theme tokens and retired markers. The replacement is asserted so a
        future change to MAIN's shape cannot silently stop exercising the content region.
        """
        needle = "  <p>content</p>"
        self.assertIn(needle, MAIN, "MAIN no longer carries the expected content placeholder")
        main = MAIN.replace(needle, "  " + content_html)
        return build(css=css,
                     body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION])

    def test_real_template_is_clean(self):
        self.assertTrue(os.path.exists(TEMPLATE), "dist/SHAREABLE.html not found next to the tests")
        errors, warnings = validate.validate(TEMPLATE)
        self.assertEqual(errors, [], "dist/SHAREABLE.html should have no errors, got: %r" % errors)
        self.assertEqual(warnings, [], "dist/SHAREABLE.html should have no warnings, got: %r" % warnings)

    def test_case_insensitive_tags_and_ids_ok(self):
        doc = build()
        doc = (doc.replace("<script", "<SCRIPT").replace("</script", "</SCRIPT")
                  .replace("<main", "<MAIN").replace("</main", "</MAIN")
                  .replace('id="commentRoot"', 'ID="commentRoot"'))
        self.assertOkNoWarn(doc)

    def test_all_single_quoted_ok(self):
        # Every attribute switched to single quotes must still validate cleanly.
        doc = build()
        m = re.search(r'<script\b[^>]*\bid="commentableHtmlLayer"[^>]*>[\s\S]*?</script>', doc)
        self.assertIsNotNone(m)
        token = "\x00DESCRIPTOR\x00"
        single_attr_descriptor = (
            '<script type=\'application/json\' id=\'commentableHtmlLayer\'>'
            + json.dumps({"version": "1.0.0", "mode": "shareable", "regions": EXPECTED_REGIONS},
                         separators=(",", ":"))
            + "</script>"
        )
        doc = doc[:m.start()] + token + doc[m.end():]
        self.assertOkNoWarn(doc.replace('"', "'").replace(token, single_attr_descriptor))

    def test_missing_region(self):
        self.assertError(build(body=[EMBEDDED_REGION, comment_ui(), MAIN, JS_REGION]),
                         "region 'HANDLED IDS': expected 1 BEGIN marker, found 0")

    def test_duplicate_begin_marker(self):
        self.assertError(build(body=[HANDLED_REGION, HANDLED_REGION, EMBEDDED_REGION, comment_ui(), MAIN, JS_REGION]),
                         "expected 1 BEGIN marker, found 2")

    def test_duplicate_end_marker(self):
        doc = build().replace(
            "<!-- END: commentable-html - HANDLED IDS -->",
            "<!-- END: commentable-html - HANDLED IDS -->\n<!-- END: commentable-html - HANDLED IDS -->",
            1)
        self.assertError(doc, "expected 1 END marker, found 2")

    def test_region_marker_text_inside_pre_is_content_not_duplicate(self):
        main = MAIN.replace("<p>content</p>", "<pre>\nBEGIN: commentable-html - CSS\n</pre>")
        self.assertOkNoWarn(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]))

    def test_missing_end_marker(self):
        doc = build().replace("<!-- END: commentable-html - HANDLED IDS -->", "", 1)
        self.assertError(doc, "expected 1 END marker, found 0")

    def test_regions_out_of_order(self):
        self.assertError(build(body=[EMBEDDED_REGION, HANDLED_REGION, comment_ui(), MAIN, JS_REGION]),
                         "out of order")

    def test_css_region_out_of_order(self):
        body = [HANDLED_REGION, EMBEDDED_REGION, comment_ui(), MAIN, JS_REGION, CSS_REGION]
        doc = ('<!DOCTYPE html>\n<html lang="en">\n<head>\n<style>\n</style>\n</head>\n<body>\n'
               + "\n".join(body) + "\n</body>\n</html>\n")
        self.assertError(doc, "out of order")

    def test_end_before_begin(self):
        doc = build()
        doc = (doc.replace("BEGIN: commentable-html - CSS", "\x00TMP\x00")
                  .replace("END: commentable-html - CSS", "BEGIN: commentable-html - CSS")
                  .replace("\x00TMP\x00", "END: commentable-html - CSS"))
        self.assertError(doc, "END marker appears before its BEGIN")

    def test_missing_layer_descriptor(self):
        doc = re.sub(r'<script\b[^>]*\bid="commentableHtmlLayer"[^>]*>[\s\S]*?</script>\n?', "", build(), count=1)
        self.assertError(doc, "layer descriptor")

    def test_layer_descriptor_region_list_must_match_contract(self):
        doc = build().replace('"regions":["CSS","HANDLED IDS","EMBEDDED COMMENTS","COMMENT UI","JS"]',
                              '"regions":["CSS","JS"]')
        self.assertError(doc, "commentableHtmlLayer.regions")

    def test_unknown_region_marker_is_rejected(self):
        # Forward-compat: `validate.py --strict` validates the CURRENT contract only, so a
        # document that introduces a region the current layer does not define (a
        # comment-delimited BEGIN/END marker pair plus the matching descriptor entry) is
        # rejected. An unknown or future region name can never masquerade as valid.
        unknown_region = ("<!-- BEGIN: commentable-html - UNKNOWN -->\n"
                          "<!-- END: commentable-html - UNKNOWN -->")
        body = [HANDLED_REGION, EMBEDDED_REGION, comment_ui(), MAIN, JS_REGION, unknown_region]
        doc = build(body=body).replace(
            '"regions":["CSS","HANDLED IDS","EMBEDDED COMMENTS","COMMENT UI","JS"]',
            '"regions":["CSS","HANDLED IDS","EMBEDDED COMMENTS","COMMENT UI","JS","UNKNOWN"]',
            1)
        self.assertError(doc, "commentableHtmlLayer.regions must list exactly the active region markers")
        # Control: the same document without the unknown region validates cleanly, proving the
        # error above is attributable to the unknown region and not to incidental structure.
        self.assertOkNoWarn(build())

    def test_layer_descriptor_mode_must_match_document_mode(self):
        doc = build().replace('"mode":"shareable"', '"mode":"nonshareable"', 1)
        self.assertError(doc, 'commentableHtmlLayer.mode must be "shareable" or "offline"')

    def test_layer_descriptor_offline_mode_is_clean_for_inline_document(self):
        doc = with_offline_mode(build())
        self.assertOkNoWarn(doc)

    def test_layer_descriptor_offline_artifact_requires_offline_mode(self):
        doc = build().replace(
            "<p>content</p>",
            '<img class="cmh-chart" data-cm-offline-chart="true" '
            'src="data:image/png;base64,AA==" alt="Offline chart">'
        )
        self.assertError(doc, 'commentableHtmlLayer.mode must be "offline" when offline chart snapshots are present')

    def test_layer_descriptor_id_decoy_div_is_flagged(self):
        doc = build().replace(
            '<script type="application/json" id="commentableHtmlLayer">',
            '<div id="commentableHtmlLayer"></div>\n<script type="application/json" id="commentableHtmlLayer">',
            1)
        self.assertError(doc, 'id="commentableHtmlLayer" appears 2 times')

    def test_id_in_attribute_value_is_not_a_real_id(self):
        # id="commentRoot" appearing INSIDE another attribute's value must not
        # satisfy the commentRoot requirement (parser reads real id attributes only).
        doc = build().replace(
            '<main id="commentRoot"',
            '<main data-note=\'id="commentRoot"\' id="realRoot"')
        self.assertError(doc, 'no element with id="commentRoot"')

    def test_required_id_survives_gt_in_quoted_attr(self):
        # A `>` inside a quoted attribute on a required-id element must not hide it.
        doc = build().replace('<span id="btnCopyAll" class="cm-skip">',
                              '<span id="btnCopyAll" data-x="a>b" class="cm-skip">')
        self.assertOkNoWarn(doc)

    def test_unified_validate_runs_layer_and_charts(self):
        # A full, layer-valid document that ALSO embeds an unskipped <canvas> must
        # surface the chart error through the same validate() call.
        doc = build().replace("</main>", '<canvas id="z" role="img" aria-label="x"></canvas></main>')
        self.assertError(doc, "not inside a cm-skip")

    def test_duplicate_attribute_keeps_first(self):
        # `<main id="fake" id="commentRoot">` is id="fake" to a browser, so the
        # commentRoot requirement is NOT satisfied.
        doc = build().replace('<main id="commentRoot"', '<main id="fake" id="commentRoot"')
        self.assertError(doc, 'no element with id="commentRoot"')

    def test_duplicate_required_id_flagged(self):
        # A second element with a required id must be flagged (decoy / wrong bind).
        doc = build().replace("</main>", '<div id="sidebar"></div></main>')
        self.assertError(doc, 'id="sidebar" appears 2 times')

    def test_handled_empty_body_is_ok(self):
        # An empty handledCommentIds body is treated as an empty array, not an error.
        doc = build().replace('id="handledCommentIds">[]</script>', 'id="handledCommentIds"></script>')
        self.assertOkNoWarn(doc)

    def test_embedded_empty_body_is_ok(self):
        doc = build().replace('id="embeddedComments">[]</script>', 'id="embeddedComments"></script>')
        self.assertOkNoWarn(doc)

    def test_handled_block_requires_json_type(self):
        # Without type="application/json" the browser executes the block as JS.
        doc = build().replace('<script type="application/json" id="handledCommentIds">',
                              '<script id="handledCommentIds">')
        self.assertError(doc, 'must be type="application/json"')

    def test_embedded_block_requires_json_type(self):
        doc = build().replace('<script type="application/json" id="embeddedComments">',
                              '<script id="embeddedComments">')
        self.assertError(doc, 'must be type="application/json"')

    def test_duplicate_handled_block_flagged(self):
        # A second id="handledCommentIds" makes getElementById bind a decoy.
        doc = build().replace(
            "</main>", '<script type="application/json" id="handledCommentIds">[]</script></main>')
        self.assertError(doc, '<script id="handledCommentIds"> appears 2 times')

    def test_duplicate_embedded_block_flagged(self):
        doc = build().replace(
            "</main>", '<script type="application/json" id="embeddedComments">[]</script></main>')
        self.assertError(doc, '<script id="embeddedComments"> appears 2 times')

    def test_template_contents_are_inert(self):
        # A <template>'s contents are an inert DocumentFragment, so a duplicate id
        # inside a <template> must NOT trip the unique-required-id check.
        doc = build().replace("</main>", '<template><div id="sidebar"></div></template></main>')
        self.assertOkNoWarn(doc)

    def test_missing_comment_root(self):
        self.assertError(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), JS_REGION]),
                         'no element with id="commentRoot"')

    def test_duplicate_comment_root(self):
        dup = MAIN + '\n<div id="commentRoot"></div>'
        self.assertError(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), dup, JS_REGION]),
                         "appears 2 times")

    def test_missing_data_comment_key(self):
        main = '<main id="commentRoot" data-cmh-content-root data-doc-label="l" data-doc-source="s"><p>x</p></main>'
        self.assertError(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]),
                         "data-comment-key")

    def test_missing_content_root_hook(self):
        main = '<main id="commentRoot" data-comment-key="k" data-doc-label="l" data-doc-source="s"><p>x</p></main>'
        self.assertError(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]),
                         "data-cmh-content-root")

    def test_missing_data_doc_label_warns(self):
        main = '<main id="commentRoot" data-cmh-content-root data-comment-key="k" data-doc-source="s"><p>x</p></main>'
        self.assertWarn(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]),
                        "data-doc-label")

    def test_missing_data_doc_source_warns(self):
        main = '<main id="commentRoot" data-cmh-content-root data-comment-key="k" data-doc-label="l"><p>x</p></main>'
        self.assertWarn(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]),
                        "data-doc-source")

    def test_data_id_does_not_count_as_comment_root(self):
        main = '<main data-id="commentRoot" data-comment-key="k" data-doc-label="l" data-doc-source="s"><p>x</p></main>'
        self.assertError(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]),
                         'no element with id="commentRoot"')

    _DEMO_MAIN = ('<main id="commentRoot" data-cmh-content-root data-comment-key="commentable-html-demo" '
                  'data-doc-label="l" data-doc-source="s"><p>x</p></main>')

    def test_demo_content_root_survived_is_error(self):
        # Active root still uses the demo data-comment-key while <title> was
        # customized -> the template demo content root survived a retrofit.
        doc = build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), self._DEMO_MAIN, JS_REGION])
        doc = doc.replace("<head>\n", "<head>\n<title>My Real Doc</title>\n", 1)
        self.assertError(doc, "demo content root survived")

    def test_demo_key_with_demo_title_is_ok(self):
        # Matches dist/SHAREABLE.html (demo key + demo <title>): the survivor check is
        # title-gated so the pristine template and its derivatives stay green.
        doc = build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), self._DEMO_MAIN, JS_REGION])
        doc = doc.replace("<head>\n", "<head>\n<title>Commentable HTML - Demo</title>\n", 1)
        self.assertOkNoWarn(doc)

    def test_active_my_doc_key_is_error_CMH_VAL_13(self):
        main = MAIN.replace('data-comment-key="k"', 'data-comment-key="my-doc"', 1)
        self.assertError(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]),
                         "documentation example data-comment-key")

    def test_real_content_root_in_comment_is_error(self):
        # A retrofit that buried the real content root inside a comment (a key
        # other than the "my-doc" example) must be caught even though a valid
        # root also exists in the live DOM.
        buried = ('<!--\nleftover from a bad retrofit:\n'
                  '<main id="commentRoot" data-cmh-content-root data-comment-key="my-real-doc-v1" '
                  'data-doc-label="x">\n  <p>real content</p>\n</main>\n-->')
        doc = build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), buried + "\n" + MAIN, JS_REGION])
        self.assertError(doc, "inside an HTML comment")

    def test_content_root_in_comment_without_key_is_error(self):
        buried = '<!--\n<main id="commentRoot"><p>x</p></main>\n-->'
        doc = build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), buried + "\n" + MAIN, JS_REGION])
        self.assertError(doc, "inside an HTML comment")

    def test_commented_root_uppercase_attr_names_is_error(self):
        # HTML attribute NAMES are case-insensitive, so a commented real root with
        # ID= / DATA-COMMENT-KEY= (uppercase names, correct-case commentRoot value)
        # must still be caught by the retrofit guard.
        buried = ('<!--\n<main ID="commentRoot" data-cmh-content-root DATA-COMMENT-KEY="my-real-doc-v1" '
                  'data-doc-label="x"><p>real content</p></main>\n-->')
        doc = build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), buried + "\n" + MAIN, JS_REGION])
        self.assertError(doc, "inside an HTML comment")

    def test_commented_root_uppercase_value_is_not_matched(self):
        # ...but the id VALUE is case-sensitive (getElementById is), so a commented
        # <main id="COMMENTROOT"> is not the real root and must NOT trip the guard.
        buried = '<!--\n<main id="COMMENTROOT" data-comment-key="my-real-doc-v1"><p>x</p></main>\n-->'
        doc = build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), buried + "\n" + MAIN, JS_REGION])
        self.assertOkNoWarn(doc)

    def test_doc_example_commented_root_is_ok(self):
        # The template's own documentation example (data-comment-key="my-doc")
        # lives inside a comment and must NOT be flagged.
        example = ('<!--\n  <main id="commentRoot"\n'
                   '        data-comment-key="my-doc"\n'
                   '        data-doc-label="My Document">\n'
                   '    ... your content ...\n  </main>\n-->')
        doc = build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), example + "\n" + MAIN, JS_REGION])
        self.assertOkNoWarn(doc)

    def test_commented_data_id_comment_root_is_not_a_hidden_root(self):
        buried = '<!--\n<div data-id="commentRoot" data-comment-key="my-real-doc-v1"></div>\n-->'
        doc = build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), buried + "\n" + MAIN, JS_REGION])
        self.assertOkNoWarn(doc)

    def test_unquoted_commented_root_is_error(self):
        # A bad retrofit can leave the real root commented out with UNQUOTED
        # attributes; the guard is case-sensitive on the id but tolerates missing
        # quotes on both id and data-comment-key.
        buried = ('<!--\nleftover:\n<main id=commentRoot data-cmh-content-root data-comment-key=my-real-doc-v1 '
                  'data-doc-label=x>\n<p>real content</p>\n</main>\n-->')
        doc = build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), buried + "\n" + MAIN, JS_REGION])
        self.assertError(doc, "inside an HTML comment")

    def test_comment_like_text_in_script_or_style_is_not_flagged(self):
        # A "<!-- ... -->" that appears only inside <script>/<style> data is script/
        # style text to the browser, not an HTML comment, so it must NOT trip the
        # commented-root guard.
        decoy = ('<style>/* <!-- <main id="commentRoot" data-cmh-content-root data-comment-key="bad"> --> */</style>\n'
                 '<script type="application/json">'
                 '"<!-- <main id=commentRoot data-cmh-content-root data-comment-key=bad> -->"</script>')
        doc = build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), decoy + "\n" + MAIN, JS_REGION])
        self.assertOkNoWarn(doc)

    _JS_OFFSET_NO_NORM = (
        "<!--\nBEGIN: commentable-html - JS\n-->\n"
        "<script>\n(function(){ function offsetWithin(n,o){ return -1; } })();\n</script>\n"
        "<!-- END: commentable-html - JS -->"
    )

    _JS_OFFSET_WITH_NORM = (
        "<!--\nBEGIN: commentable-html - JS\n-->\n"
        "<script>\n(function(){ function normalizeBoundary(n,o){ return [n,o]; }\n"
        "function offsetWithin(n,o){ [n,o]=normalizeBoundary(n,o); return -1; } })();\n</script>\n"
        "<!-- END: commentable-html - JS -->"
    )

    _JS_OFFSETWITHIN_PREFIX_DECOY = (
        "<!--\nBEGIN: commentable-html - JS\n-->\n"
        "<script>\n(function(){ function offsetWithinX(n,o){ return -1; } })();\n</script>\n"
        "<!-- END: commentable-html - JS -->"
    )

    _JS_OFFSET_COMMENTED = (
        "<!--\nBEGIN: commentable-html - JS\n-->\n"
        "<script>\n(function(){\n"
        "/* function normalizeBoundary(n,o){ return [n,o]; } */\n"
        "function offsetWithin(n,o){ /* normalizeBoundary(n,o) */ return -1; } })();\n</script>\n"
        "<!-- END: commentable-html - JS -->"
    )

    _JS_OFFSET_STRINGCALL = (
        "<!--\nBEGIN: commentable-html - JS\n-->\n"
        "<script>\n(function(){\n"
        'function offsetWithin(n,o){ var s = "normalizeBoundary("; return -1; } })();\n</script>\n'
        "<!-- END: commentable-html - JS -->"
    )

    _JS_OFFSET_BRACE_STRING = (
        "<!--\nBEGIN: commentable-html - JS\n-->\n"
        "<script>\n(function(){ function normalizeBoundary(n,o){ return [n,o]; }\n"
        'function offsetWithin(n,o){ var s = "}"; [n,o]=normalizeBoundary(n,o); return -1; } })();\n</script>\n'
        "<!-- END: commentable-html - JS -->"
    )

    _JS_OFFSET_CALL_ELSEWHERE = (
        "<!--\nBEGIN: commentable-html - JS\n-->\n"
        "<script>\n(function(){ function normalizeBoundary(n,o){ return [n,o]; }\n"
        "function offsetWithin(n,o){ return -1; }\n"
        "function other(n,o){ return normalizeBoundary(n,o); } })();\n</script>\n"
        "<!-- END: commentable-html - JS -->"
    )

    def test_offsetwithin_without_normalizeboundary_is_error(self):
        # offsetWithin present but the element-boundary normalizer missing -> a
        # selection starting/ending at a block edge would abort anchoring.
        doc = build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), MAIN, self._JS_OFFSET_NO_NORM])
        self.assertError(doc, "normalizeBoundary")

    def test_offsetwithin_with_normalizeboundary_is_ok(self):
        doc = build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), MAIN, self._JS_OFFSET_WITH_NORM])
        self.assertOkNoWarn(doc)

    def test_offsetwithin_normalizeboundary_only_in_comment_is_error(self):
        # F-C2 false-pass guard: a commented-out helper + commented call must not pass.
        doc = build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), MAIN, self._JS_OFFSET_COMMENTED])
        self.assertError(doc, "normalizeBoundary")

    def test_offsetwithin_normalizeboundary_only_in_string_is_error(self):
        # F-C2 false-pass guard: the call token appearing only in a string literal must not pass.
        doc = build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), MAIN, self._JS_OFFSET_STRINGCALL])
        self.assertError(doc, "normalizeBoundary")

    def test_offsetwithin_with_brace_in_string_is_ok(self):
        # F-C2 false-fail guard: a `}` inside a string in the body must not close it early.
        doc = build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), MAIN, self._JS_OFFSET_BRACE_STRING])
        self.assertOkNoWarn(doc)

    def test_offsetwithin_call_in_unrelated_function_is_error(self):
        # Body-local: a normalizeBoundary call in a later unrelated function does not count.
        doc = build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), MAIN, self._JS_OFFSET_CALL_ELSEWHERE])
        self.assertError(doc, "normalizeBoundary")

    def test_offsetwithin_prefix_name_is_exempt(self):
        # A function named offsetWithinX (prefix only) is not the real offsetWithin(),
        # so the substring gate must not falsely require normalizeBoundary.
        doc = build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), MAIN, self._JS_OFFSETWITHIN_PREFIX_DECOY])
        self.assertOkNoWarn(doc)

    def test_handled_invalid_json(self):
        doc = build().replace('id="handledCommentIds">[]', 'id="handledCommentIds">[not json')
        self.assertError(doc, "handledCommentIds is not valid JSON")

    def test_handled_not_array(self):
        doc = build().replace('id="handledCommentIds">[]', 'id="handledCommentIds">{"a":1}')
        self.assertError(doc, "handledCommentIds is not a JSON array")

    def test_handled_bad_ids_error(self):
        # Aligns with mark_handled.py, which refuses to edit a file whose existing
        # handledCommentIds contains ids outside the safe pattern.
        doc = build().replace('id="handledCommentIds">[]', 'id="handledCommentIds">["cabcdef1","BADID"]')
        self.assertError(doc, "safe pattern")

    def test_embedded_invalid_json(self):
        doc = build().replace('id="embeddedComments">[]', 'id="embeddedComments">[bad json')
        self.assertError(doc, "embeddedComments is not valid JSON")

    def test_embedded_not_array(self):
        doc = build().replace('id="embeddedComments">[]', 'id="embeddedComments">{"a":1}')
        self.assertError(doc, "embeddedComments is not a JSON array")

    def test_missing_handled_block(self):
        doc = build().replace('<script type="application/json" id="handledCommentIds">[]</script>', "")
        self.assertError(doc, "missing <script id=\"handledCommentIds\"> block")

    def test_missing_embedded_block(self):
        doc = build().replace('<script type="application/json" id="embeddedComments">[]</script>', "")
        self.assertError(doc, "missing <script id=\"embeddedComments\"> block")

    def test_duplicate_handled_id_outside_region_flagged(self):
        # A stray id="handledCommentIds" placed BEFORE the region is what
        # getElementById() binds to first (document order), so the runtime would
        # read the decoy. The uniqueness guard must flag it even though the
        # region-scoped JSON check still parses the valid in-region block.
        decoy = '<script type="application/json" id="handledCommentIds">not json here</script>'
        body = [decoy, HANDLED_REGION, EMBEDDED_REGION, comment_ui(), MAIN, JS_REGION]
        self.assertError(build(body=body), '<script id="handledCommentIds"> appears 2 times')

    def test_unescaped_script_close_in_js(self):
        doc = build().replace("(function () { var a = 1; return a; })();",
                              "document.write('</script>'); (function(){})();")
        self.assertError(doc, "</script> tags")

    def test_js_region_missing_script_close(self):
        js = ("<!--\nBEGIN: commentable-html - JS\n-->\n"
              "<script>\nvar a = 1;\n"          # closing </script> deliberately absent
              "<!-- END: commentable-html - JS -->")
        self.assertError(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), MAIN, js]),
                         "no closing </script>")

    def test_escaped_script_close_is_ok(self):
        doc = build().replace("(function () { var a = 1; return a; })();",
                              "var s = '<\\/script>'; (function(){})();")
        self.assertOkNoWarn(doc)

    def test_missing_required_id_button(self):
        doc = build().replace('<span id="btnCopyAll" class="cm-skip"></span>', "")
        self.assertError(doc, 'required element id="btnCopyAll" is missing')

    def test_missing_required_id_sort(self):
        # btnSort is the sole control wired by 80-sort-comments.js; without it sorting no-ops.
        doc = build().replace('<span id="btnSort" class="cm-skip"></span>', "")
        self.assertError(doc, 'required element id="btnSort" is missing')

    def test_missing_required_id_sidebar(self):
        doc = build().replace('<span id="sidebar" class="cm-skip"></span>', "")
        self.assertError(doc, 'required element id="sidebar" is missing')

    def test_missing_required_id_heading_add_btn(self):
        doc = build().replace('<span id="headingAddBtn" class="cm-skip"></span>', "")
        self.assertError(doc, 'required element id="headingAddBtn" is missing')

    def test_missing_required_id_widget_add_btn(self):
        doc = build().replace('<span id="widgetAddBtn" class="cm-skip"></span>', "")
        self.assertError(doc, 'required element id="widgetAddBtn" is missing')

    def test_missing_required_id_link_add_btn(self):
        doc = build().replace('<span id="linkAddBtn" class="cm-skip"></span>', "")
        self.assertError(doc, 'required element id="linkAddBtn" is missing')

    def test_missing_required_id_menu_doc_comment(self):
        doc = build().replace('<span id="menuDocComment" class="cm-skip"></span>', "")
        self.assertError(doc, 'required element id="menuDocComment" is missing')

    def test_missing_required_id_menu_slide_comment(self):
        doc = build().replace('<span id="menuSlideComment" class="cm-skip"></span>', "")
        self.assertError(doc, 'required element id="menuSlideComment" is missing')

    def test_missing_required_id_storage_top(self):
        doc = build().replace('<span id="btnStorageTop" class="cm-skip"></span>', "")
        self.assertError(doc, 'required element id="btnStorageTop" is missing')

    def test_missing_required_id_storage(self):
        doc = build().replace('<span id="btnStorage" class="cm-skip"></span>', "")
        self.assertError(doc, 'required element id="btnStorage" is missing')

    def test_missing_required_id_more_menu_button(self):
        doc = build().replace('<span id="btnMoreMenu" class="cm-skip"></span>', "")
        self.assertError(doc, 'required element id="btnMoreMenu" is missing')

    def test_missing_required_id_sidebar_more_menu(self):
        doc = build().replace('<span id="sidebarMoreMenu" class="cm-skip"></span>', "")
        self.assertError(doc, 'required element id="sidebarMoreMenu" is missing')

    def test_missing_required_id_search_toggle(self):
        doc = build().replace('<span id="btnSearchToggle" class="cm-skip"></span>', "")
        self.assertError(doc, 'required element id="btnSearchToggle" is missing')

    def test_missing_required_id_cm_identity(self):
        doc = build().replace('<span id="cmIdentity" class="cm-skip"></span>', "")
        self.assertError(doc, 'required element id="cmIdentity" is missing')

    def test_missing_required_id_cm_identity_input(self):
        doc = build().replace('<span id="cmIdentityInput" class="cm-skip"></span>', "")
        self.assertError(doc, 'required element id="cmIdentityInput" is missing')

    def test_missing_required_id_btn_edit_identity(self):
        doc = build().replace('<span id="btnEditIdentity" class="cm-skip"></span>', "")
        self.assertError(doc, 'required element id="btnEditIdentity" is missing')

    def test_required_id_only_in_comment_is_ignored(self):
        doc = build().replace('<span id="btnCopyAll" class="cm-skip"></span>', "")
        doc = doc.replace("<body>\n", '<body>\n<!-- <span id="btnCopyAll"></span> -->\n', 1)
        self.assertError(doc, 'required element id="btnCopyAll" is missing')

    def test_data_id_does_not_satisfy_required_id(self):
        doc = build().replace('<span id="btnCopyAll" class="cm-skip"></span>',
                              '<span data-id="btnCopyAll" class="cm-skip"></span>')
        self.assertError(doc, 'required element id="btnCopyAll" is missing')

    def test_reintroduced_export_id_warns(self):
        body = [HANDLED_REGION, EMBEDDED_REGION,
                comment_ui(extra='  <button id="btnExport"></button>\n'), MAIN, JS_REGION]
        self.assertWarn(build(body=body), "Export/Import UI detected")

    def test_export_removal_note_cites_exact_version(self):
        body = [HANDLED_REGION, EMBEDDED_REGION,
                comment_ui(extra='  <button id="btnExport"></button>\n'), MAIN, JS_REGION]
        self.assertWarn(build(body=body), "removed before the 1.0.0 release")

    def test_export_marker_warns(self):
        # The marker must sit in the LAYER's own markup: an occurrence in the authored CONTENT
        # is the author quoting a retired marker, not a reintroduced export UI (CMH-VAL-20,
        # covered by test_export_marker_inside_authored_content_is_not_flagged).
        doc = build().replace(
            '<div class="cm-toolbar cm-skip">',
            '<div class="cm-toolbar cm-skip">\n  <!-- --START-COMMENTS-EXPORT-- -->', 1)
        self.assertWarn(doc, "Export/Import UI detected")

    def test_export_marker_inside_authored_content_is_not_flagged(self):
        # CMH-VAL-20: a document that DOCUMENTS the layer legitimately quotes the old export
        # marker in its prose. Scanning the whole document let that prose forge a diagnostic
        # about the layer's own markup - a false positive the reader cannot fix without
        # rewording their content.
        doc = self._with_content("<p>The retired marker was <code>--START-COMMENTS-EXPORT--</code>.</p>")
        errors, warnings = _validate_text(doc)
        self.assertEqual(errors, [], "expected no errors, got: %r" % errors)
        self.assertFalse(any("Export/Import UI detected" in w for w in warnings),
                         "authored prose must not raise the export warning: %r" % warnings)

    def test_missing_cp_variables(self):
        css = CSS_REGION.replace("--cp-bg: #ffffff;", "")
        self.assertError(build(css=css), "--cp-* theme variables are not defined")

    def test_cp_variable_mentioned_in_authored_content_does_not_satisfy_the_check(self):
        # CMH-VAL-20: prose that MENTIONS "--cp-bg:" is not a declaration. Scanning the whole
        # document let a document with no theme variables at all pass this ERROR by talking
        # about them - a suppressed diagnostic, the dangerous direction.
        css = CSS_REGION.replace("--cp-bg: #ffffff;", "")
        doc = self._with_content("<p>Set <code>--cp-bg: #fff;</code> to theme the layer.</p>",
                                 css=css)
        self.assertError(doc, "--cp-* theme variables are not defined")

    def test_cp_variable_declared_outside_the_content_region_still_satisfies_the_check(self):
        doc = self._with_content("<p>plain prose</p>")
        errors, _warnings = _validate_text(doc)
        self.assertFalse(any("theme variables are not defined" in e for e in errors),
                         "a real declaration must still satisfy the check: %r" % errors)

    def test_scoped_hidden_rule_mentioned_in_authored_content_does_not_satisfy_the_check(self):
        # CMH-VAL-20: the most plausible of the three - a document explaining the layer's CSS
        # naturally contains the scoped rule, which silently suppressed the warning.
        css = (
            "/*\nBEGIN: commentable-html - CSS\n*/\n"
            ":root { --cp-bg: #fff; }\n"
            "/*\nEND: commentable-html - CSS\n*/"
        )
        doc = self._with_content(
            "<p>The layer scopes it as <code>.cm-skip[hidden]</code>.</p>", css=css)
        self.assertWarn(doc, "missing the scoped '.cm-skip[hidden]'")

    def test_scoped_hidden_rule_outside_the_content_region_still_satisfies_the_check(self):
        doc = self._with_content("<p>plain prose</p>")
        errors, warnings = _validate_text(doc)
        self.assertEqual(errors, [], "expected no errors, got: %r" % errors)
        self.assertFalse(any("missing the scoped" in w for w in warnings),
                         "the real CSS rule must still satisfy the check: %r" % warnings)

    def test_reviewer_prose_in_the_embedded_state_blocks_cannot_forge_the_verdict(self):
        # CMH-VAL-20: "Export with embedded comments" bakes REVIEWER prose into the
        # embeddedComments block, which sits OUTSIDE the CONTENT region - so blanking only the
        # content still let a reviewer who quotes the layer's CSS satisfy these checks. A review
        # of a document ABOUT commentable-html is exactly when that text appears.
        forged = ".cm-skip[hidden] and --cp-bg: #fff and --START-COMMENTS-EXPORT--"
        css = (
            "/*\nBEGIN: commentable-html - CSS\n*/\n"
            ":root { color: #000; }\n"
            "/*\nEND: commentable-html - CSS\n*/"
        )
        embedded = EMBEDDED_REGION.replace(
            ">[]<", '>[{"id":"cabc123","text":"%s"}]<' % forged, 1)
        main = MAIN.replace("  <p>content</p>", "  <p>plain prose</p>")
        doc = build(css=css,
                    body=[HANDLED_REGION, embedded, comment_ui(), main, JS_REGION])
        errors, warnings = _validate_text(doc)
        self.assertTrue(any("theme variables are not defined" in e for e in errors),
                        "reviewer prose must not satisfy the theme ERROR: %r" % errors)
        self.assertTrue(any("missing the scoped" in w for w in warnings),
                        "reviewer prose must not satisfy the scoped-rule check: %r" % warnings)
        self.assertFalse(any("Export/Import UI detected" in w for w in warnings),
                         "reviewer prose must not forge the export warning: %r" % warnings)
        # The other document-owned state block must be equally powerless.
        handled = HANDLED_REGION.replace(">[]<", '>["%s"]<' % forged, 1)
        doc2 = build(css=css,
                     body=[handled, EMBEDDED_REGION, comment_ui(), main, JS_REGION])
        errors2, warnings2 = _validate_text(doc2)
        self.assertTrue(any("theme variables are not defined" in e for e in errors2), errors2)
        self.assertFalse(any("Export/Import UI detected" in w for w in warnings2), warnings2)

    def test_a_marker_quoted_in_script_data_cannot_define_the_layer_view(self):
        # CMH-VAL-20 fails CLOSED on an ambiguous marker set. A CONTENT marker quoted inside
        # <script> data is not a real boundary, and treating it as one let a document with no
        # theme variables at all validate clean by supplying them from its own prose.
        css = (
            "/*\nBEGIN: commentable-html - CSS\n*/\n"
            ":root { color: #000; }\n"
            "/*\nEND: commentable-html - CSS\n*/"
        )
        js = JS_REGION.replace(
            "<script>\n",
            '<script>\nvar t = "%s" + "%s";\n' % (CONTENT_BEGIN, CONTENT_END), 1)
        main = MAIN.replace(
            "  <p>content</p>",
            "  <p>set <code>--cp-bg: #fff</code> and <code>.cm-skip[hidden]</code></p>")
        doc = build(css=css,
                    body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, js])
        errors, _warnings = _validate_text(doc)
        self.assertTrue(any("theme variables are not defined" in e for e in errors),
                        "a script-quoted marker must not let prose satisfy the check: %r" % errors)

    def test_the_layer_region_view_is_an_allow_list(self):
        # The marker check reads only what the LAYER's own regions contain. A deny-list cannot be
        # made safe here, because user text reaches <title>, data-doc-label and every other
        # attribute - new_document --label copies the label verbatim into two of them.
        from checks.parsing import layer_regions_text
        doc = build()
        view = layer_regions_text(doc)
        self.assertIn("cm-toolbar", view, "the layer's own regions must be present")
        self.assertNotIn("<title>", view, "document chrome is outside the layer's regions")
        self.assertNotIn("data-doc-label", view, "author-supplied attributes are never inspected")
        self.assertEqual(layer_regions_text("no regions at all"), "",
                         "a document with no layer regions exposes nothing to inspect")

    def test_a_script_named_inside_a_comment_does_not_swallow_the_content_markers(self):
        # The marker scan masks <script>/<style> BODIES, but it must do so in the same ONE-PASS
        # way CMH-VAL-11 uses: masking naively let a "<script" NAMED INSIDE a comment open a mask
        # that ran to the document's next real </script>, blanking a CONTENT marker in between.
        # The view then saw an ambiguous marker set and failed closed, inventing a theme ERROR on
        # a perfectly good document.
        doc = self._with_content(
            "<!-- move the <script> tag later -->\n  <p>plain prose</p>")
        errors, warnings = _validate_text(doc)
        self.assertEqual(errors, [], "a commented <script> must not break the layer view: %r" % errors)
        self.assertFalse(any("missing the scoped" in w for w in warnings), warnings)

    def test_a_marker_quoted_in_script_data_is_not_counted_as_a_duplicate(self):
        # The marker COUNT and the layer view must agree on what a marker is. Counting raw text
        # made a marker quoted inside script data forge a duplicate-marker ERROR, and could also
        # leave the count satisfied while the layer view saw none.
        js = JS_REGION.replace(
            "<script>\n", '<script>\nvar t = "%s";\n' % CONTENT_BEGIN, 1)
        main = MAIN.replace("  <p>content</p>", "  <p>plain prose</p>")
        doc = build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, js])
        errors, _warnings = _validate_text(doc)
        self.assertFalse(any("CONTENT region" in e for e in errors),
                         "a marker quoted in script data is not a real marker: %r" % errors)

    def test_an_unterminated_or_string_quoted_css_comment_is_lexed_correctly(self):
        # The comment stripper is a lexer, not a regex, because both mistakes are reachable:
        # an unterminated comment runs to end of input in a real parser (so its text must not
        # satisfy a check), and `/*` inside a quoted CSS string is an ordinary character (so
        # treating it as a delimiter would blank the LIVE declarations after it).
        from checks.layer import _css_declarations_view as strip

        unterminated = "/* --cp-bg: #fff"
        self.assertNotIn("--cp-bg", strip(unterminated),
                         "an unterminated comment must be blanked to end of input")

        quoted = 'a { content: "/*" }\n:root { --cp-bg: #fff }\nb { content: "*/" }'
        stripped = strip(quoted)
        self.assertIn("--cp-bg", stripped,
                      "a live declaration between quoted comment-like strings must survive")
        for src in (unterminated, quoted):
            out = strip(src)
            self.assertEqual(len(out), len(src), "blanking must preserve offsets")
            self.assertEqual(out.count("\n"), src.count("\n"), "line breaks must survive")

    def test_an_open_comment_cannot_cross_a_style_boundary(self):
        # A browser parses each <style> as its OWN stylesheet, so an unterminated `/*` in one
        # cannot comment out a LATER element's rules. Stripping a JOINED string let a stray
        # comment anywhere in the document hide a live, dangerous unscoped reset from check 9.
        doc = self._with_content(
            "<style>\n/* an author's unterminated comment\n</style>\n"
            "<style>\n[hidden] { display: none !important; }\n</style>")
        self.assertWarn(doc, "unscoped '[hidden]")

    def test_a_style_with_a_non_css_type_is_not_a_stylesheet(self):
        # A browser applies a <style> only when its type is absent, empty, or text/css. Reading
        # every <style> body let `<style type="text/plain">` - which renders nothing - satisfy
        # the CSS checks for a document that declares no theme and no scoped rule.
        css = (
            "/*\nBEGIN: commentable-html - CSS\n*/\n"
            ":root { color: #000; }\n"
            "/*\nEND: commentable-html - CSS\n*/"
        )
        doc = self._with_content(
            '<style type="text/plain">\n'
            ":root { --cp-bg: #fff; }\n"
            ".cm-skip[hidden] { display: none !important; }\n"
            "</style>",
            css=css)
        errors, warnings = _validate_text(doc)
        self.assertTrue(any("theme variables are not defined" in e for e in errors),
                        "a non-CSS <style> must not satisfy the theme ERROR: %r" % errors)
        self.assertTrue(any("missing the scoped" in w for w in warnings), warnings)

    def test_a_quoted_css_string_is_not_a_selector_or_a_declaration(self):
        # A string VALUE can never be a selector or a declaration name, so its text must not
        # decide any of the three CSS verdicts: `content: ".cm-skip[hidden] --cp-bg: x"` is live
        # CSS that declares neither, and an unscoped reset quoted in one is not a live rule.
        css = (
            "/*\nBEGIN: commentable-html - CSS\n*/\n"
            ':root::before { content: ".cm-skip[hidden] --cp-bg: #fff"; }\n'
            "/*\nEND: commentable-html - CSS\n*/"
        )
        errors, warnings = _validate_text(build(css=css))
        self.assertTrue(any("theme variables are not defined" in e for e in errors),
                        "a quoted string must not satisfy the theme ERROR: %r" % errors)
        self.assertTrue(any("missing the scoped" in w for w in warnings), warnings)

        quoted_reset = (
            "/*\nBEGIN: commentable-html - CSS\n*/\n"
            ":root { --cp-bg: #fff; }\n"
            ".cm-skip[hidden], .cm-skip [hidden] { display: none !important; }\n"
            ':root::after { content: "\\A[hidden] { display: none !important; }"; }\n'
            "/*\nEND: commentable-html - CSS\n*/"
        )
        _errors, warnings2 = _validate_text(build(css=quoted_reset))
        self.assertFalse(any("unscoped '[hidden]" in w for w in warnings2),
                         "a quoted reset is not a live rule: %r" % warnings2)

    def test_an_unterminated_css_string_ends_at_the_newline(self):
        # CSS terminates a string at a raw newline (a bad-string token), so an author's stray
        # quote cannot swallow every declaration after it. Letting the string run on blanked the
        # layer's real theme declaration and failed a valid document.
        from checks.layer import _css_declarations_view as view

        src = 'a { content: "oops\n:root { --cp-bg: #fff; }\n'
        out = view(src)
        self.assertIn("--cp-bg", out,
                      "a string must not swallow the next line's declaration")
        self.assertEqual(len(out), len(src), "blanking must preserve offsets")
        self.assertEqual(out.count("\n"), src.count("\n"), "line breaks must survive")

    def test_a_commented_out_css_rule_is_not_a_rule(self):
        # A commented-out declaration is not a declaration, in either direction: a quoted
        # `--cp-bg:` must not SATISFY the theme ERROR, and a rule someone commented out while
        # debugging must not still raise the unscoped-[hidden] warning.
        css = (
            "/*\nBEGIN: commentable-html - CSS\n*/\n"
            ":root { color: #000; }\n"
            "/* --cp-bg: #fff; .cm-skip[hidden] { display: none !important; } */\n"
            "/*\nEND: commentable-html - CSS\n*/"
        )
        errors, warnings = _validate_text(build(css=css))
        self.assertTrue(any("theme variables are not defined" in e for e in errors),
                        "a commented-out declaration must not satisfy the check: %r" % errors)
        self.assertTrue(any("missing the scoped" in w for w in warnings), warnings)

        commented_reset = (
            "/*\nBEGIN: commentable-html - CSS\n*/\n"
            ":root { --cp-bg: #fff; }\n"
            ".cm-skip[hidden], .cm-skip [hidden] { display: none !important; }\n"
            "/*\n[hidden] {\n  display: none !important;\n}\n*/\n"
            "/*\nEND: commentable-html - CSS\n*/"
        )
        _errors, warnings2 = _validate_text(build(css=commented_reset))
        self.assertFalse(any("unscoped '[hidden]" in w for w in warnings2),
                         "a commented-out reset is not a live rule: %r" % warnings2)

    def test_the_export_marker_outside_the_layer_regions_is_not_flagged(self):
        # The marker probe is an ALLOW-list over the layer's own regions, because
        # `new_document --label` copies the label verbatim into <title> AND data-doc-label - so
        # naming a document after the retired marker used to raise a warning the author could
        # only clear by renaming the document.
        label = "About the --START-COMMENTS-EXPORT-- marker"
        doc = build().replace("<title>", "<title>" + label, 1) if "<title>" in build() else build()
        doc = doc.replace('data-doc-label="l"', 'data-doc-label="%s"' % label, 1)
        _errors, warnings = _validate_text(doc)
        self.assertFalse(any("Export/Import UI detected" in w for w in warnings),
                         "author-supplied chrome must not forge the export warning: %r" % warnings)

    def test_an_unclosed_style_at_eof_is_still_scanned(self):
        # A browser runs an unclosed raw-text element to EOF, so its CSS is live. Reading only
        # closed <style> elements would let a dangerous unscoped rule hide behind a missing
        # closing tag.
        from checks.parsing import _DocParser
        html = "<html><head><style>\n[hidden] { display: none !important; }"
        parser = _DocParser(html)
        parser.feed(html)
        parser.close()
        self.assertTrue(parser.styles, "an unclosed <style> must still be captured")
        self.assertIn("[hidden]", parser.styles[0]["body"])

    def test_a_style_the_author_puts_in_their_own_content_still_counts(self):
        # The CSS checks are narrowed by CSS-ness, NOT by region: a <style> inside the authored
        # content is live CSS that really would hide host elements, so it must still be seen.
        # (test_an_unscoped_hidden_rule_shown_in_prose_is_not_a_live_rule pins the other side.)
        doc = self._with_content(
            "<style>\n[hidden] { display: none !important; }\n</style>")
        self.assertWarn(doc, "unscoped '[hidden]")

    def test_a_layer_script_that_merely_mentions_the_css_cannot_satisfy_the_checks(self):
        # Text is not a stylesheet. Reading any "layer text" let a layer <script> that merely
        # MENTIONS the tokens satisfy both CSS checks on a document that declares neither.
        css = (
            "/*\nBEGIN: commentable-html - CSS\n*/\n"
            ":root { color: #000; }\n"
            "/*\nEND: commentable-html - CSS\n*/"
        )
        js = JS_REGION.replace(
            "<script>\n", '<script>\nvar hint = "--cp-bg: #fff .cm-skip[hidden]";\n', 1)
        doc = build(css=css, body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), MAIN, js])
        errors, warnings = _validate_text(doc)
        self.assertTrue(any("theme variables are not defined" in e for e in errors),
                        "a script mention must not satisfy the theme ERROR: %r" % errors)
        self.assertTrue(any("missing the scoped" in w for w in warnings),
                        "a script mention must not satisfy the scoped-rule check: %r" % warnings)

    def test_a_clean_document_survives_a_marker_quoted_in_script_data(self):
        # The marker scan must MASK script bodies rather than count raw text: counting raw text
        # would see two BEGIN markers here, fail closed, and invent findings on a good document.
        js = JS_REGION.replace(
            "<script>\n", '<script>\nvar t = "%s";\n' % CONTENT_BEGIN, 1)
        doc = build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), MAIN, js])
        self.assertOkNoWarn(doc)

    def test_the_marker_scan_keeps_comments_while_blanking_script_bodies(self):
        # The marker scan blanks raw-text BODIES but must NOT blank comments (the CONTENT
        # markers ARE comments), which is the opposite of every view that hides quoted markup.
        # Conflating the two silently breaks marker discovery, so pin the distinction - along
        # with the offset and line preservation callers slice the ORIGINAL document by.
        from checks.parsing import content_marker_scan
        doc = "<script>\nvar s = 1;\n</script>\n" + CONTENT_BEGIN
        scan = content_marker_scan(doc)
        self.assertIn(CONTENT_BEGIN, scan, "the marker scan must keep comments")
        self.assertNotIn("var s = 1", scan, "the marker scan must blank script bodies")
        self.assertEqual(len(scan), len(doc), "blanking must preserve offsets")
        self.assertEqual(scan.count("\n"), doc.count("\n"), "line breaks must survive")

    def test_an_unscoped_hidden_rule_shown_in_prose_is_not_a_live_rule(self):
        # CMH-VAL-20: the unscoped-[hidden] warning reads real <style> BODIES, so a code sample
        # that SHOWS the rule is not treated as one. It is narrowed by CSS-ness rather than by
        # region, because a <style> the author puts in their content really would hide host
        # elements (test_unscoped_hidden_warns pins that direction).
        doc = self._with_content(
            "<pre><code>[hidden] {\n  display: none !important;\n}</code></pre>")
        _errors, warnings = _validate_text(doc)
        self.assertFalse(any("unscoped '[hidden]" in w for w in warnings),
                         "a code sample must not raise the unscoped-rule warning: %r" % warnings)

    def test_cp_variable_must_be_defined_not_just_used(self):
        css = (
            "/*\nBEGIN: commentable-html - CSS\n*/\n"
            "body { background: var(--cp-bg); }\n"
            ".cm-skip[hidden], .cm-skip [hidden] { display: none !important; }\n"
            "/*\nEND: commentable-html - CSS\n*/"
        )
        self.assertError(build(css=css), "--cp-* theme variables are not defined")

    def test_unscoped_hidden_warns(self):
        css = (
            "/*\nBEGIN: commentable-html - CSS\n*/\n"
            ":root { --cp-bg: #fff; }\n"
            "[hidden] {\n  display: none !important;\n}\n"
            ".cm-skip[hidden] { display: none !important; }\n"
            "/*\nEND: commentable-html - CSS\n*/"
        )
        self.assertWarn(build(css=css), "unscoped '[hidden]")

    def test_missing_scoped_hidden_warns(self):
        css = (
            "/*\nBEGIN: commentable-html - CSS\n*/\n"
            ":root { --cp-bg: #fff; }\n"
            "/*\nEND: commentable-html - CSS\n*/"
        )
        self.assertWarn(build(css=css), "missing the scoped '.cm-skip[hidden]'")

    def test_mermaid_pre_without_cmskip_warns(self):
        main = MAIN.replace("<p>content</p>", '<pre class="mermaid">flowchart TD\nA-->B</pre>')
        self.assertWarn(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]),
                        "mermaid block is missing")

    def test_mermaid_div_without_cmskip_warns(self):
        main = MAIN.replace("<p>content</p>", '<div class="mermaid">flowchart TD</div>')
        self.assertWarn(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]),
                        "mermaid block is missing")

    def test_mermaid_with_cmskip_ok(self):
        main = MAIN.replace("<p>content</p>", '<pre class="mermaid cm-skip">flowchart TD\nA-->B</pre>')
        self.assertOkNoWarn(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, _MERMAID_LOADER, JS_REGION]))

    def test_mermaid_single_quoted_class_ok(self):
        main = MAIN.replace("<p>content</p>", "<pre class='mermaid cm-skip'>flowchart TD</pre>")
        self.assertOkNoWarn(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, _MERMAID_LOADER, JS_REGION]))

    def _mermaid_warns(self, loader):
        main = MAIN.replace("<p>content</p>", '<pre class="mermaid cm-skip">flowchart TD\nA-->B</pre>')
        body = [HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main]
        if loader:
            body.append(loader)
        body.append(JS_REGION)
        errors, warnings = _validate_text(build(body=body))
        self.assertEqual(errors, [], errors)
        return any("mermaid" in w and ("render" in w or "loader" in w) for w in warnings)

    def test_mermaid_ungated_loader_ok(self):
        self.assertFalse(self._mermaid_warns(_MERMAID_LOADER))

    def test_mermaid_missing_loader_warns(self):
        self.assertTrue(self._mermaid_warns(None))

    def test_rendered_mermaid_svg_without_loader_is_clean(self):
        main = MAIN.replace(
            "<p>content</p>",
            '<pre class="mermaid cm-skip" data-processed="true"><svg><g class="node"><text>A</text></g></svg></pre>')
        self.assertOkNoWarn(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]))

    def test_mermaid_gated_loader_warns(self):
        gated = ('<script type="module">if (new URLSearchParams(location.search).get("mermaid") === "1") '
                 '{ const m = (await import("https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs")).default; '
                 'm.initialize({ startOnLoad: false }); m.run(); }</script>')
        self.assertTrue(self._mermaid_warns(gated))

    def test_mermaid_loader_without_run_warns(self):
        norun = ('<script type="module">const m = (await import("https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs")).default; '
                 'm.initialize({ startOnLoad: false });</script>')
        self.assertTrue(self._mermaid_warns(norun))

    def test_mermaid_startonload_true_ok(self):
        s = ('<script type="module">const m = (await import("https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs")).default; '
             'm.initialize({ startOnLoad: true });</script>')
        self.assertFalse(self._mermaid_warns(s))

    def test_no_mermaid_blocks_no_render_warning(self):
        # A gated-looking script with NO mermaid blocks present must not warn.
        gated = '<script type="module">if (new URLSearchParams(location.search).get("mermaid") === "1") { }</script>'
        errors, warnings = _validate_text(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), MAIN, gated, JS_REGION]))
        self.assertEqual(errors, [])
        self.assertFalse(any("will not render" in w or "mermaid loader" in w for w in warnings))


class ReviewedSectionsTests(ValidateAssertions, unittest.TestCase):
    """CMH-REVIEW-07: the optional reviewedSections marker block is schema-validated."""

    @staticmethod
    def _embedded(inner):
        return (
            "<!--\nBEGIN: commentable-html - EMBEDDED COMMENTS\n-->\n"
            '<script type="application/json" id="embeddedComments">[]</script>\n'
            '<script type="application/json" id="reviewedSections">' + inner + "</script>\n"
            "<!-- END: commentable-html - EMBEDDED COMMENTS -->"
        )

    def _build(self, inner):
        return build(body=[HANDLED_REGION, self._embedded(inner), comment_ui(), MAIN, JS_REGION])

    def test_reviewed_sections_block_is_validated(self):
        # A valid object with a safe base36 hash validates clean.
        self.assertOkNoWarn(self._build(
            '{"goals": {"hash": "abc123", "headingText": "Goals", "level": 2, "reviewedAt": "x"}}'))
        # An empty object is fine (the default baked block).
        self.assertOkNoWarn(self._build("{}"))
        # A non-object is rejected.
        self.assertError(self._build("[]"), "reviewedSections is not a JSON object")
        # A marker with an unsafe hash is rejected.
        self.assertError(self._build('{"goals": {"hash": "NOT SAFE!"}}'), "unsafe hash")
        # Invalid JSON is rejected.
        self.assertError(self._build("{bad"), "reviewedSections is not valid JSON")

    def test_duplicate_reviewed_sections_block_flagged(self):
        # CMH-REVIEW-16: review state is user data, so a decoy block that getElementById would
        # bind INSTEAD of the region-owned one must be reported, exactly like the other state
        # blocks. The decoy sits in the authored content, ahead of the real block.
        doc = self._build("{}").replace(
            "<p>content</p>",
            '<p>content</p><script type="application/json" id="reviewedSections">{}</script>')
        self.assertError(doc, '<script id="reviewedSections"> appears 2 times')

    def test_reviewed_sections_block_outside_the_region_flagged(self):
        # CMH-REVIEW-16: a LONE block outside the region satisfies the uniqueness rule, but the
        # runtime reads and writes only the block the region owns - so a document that looks like it
        # carries review state, and does not, must be reported rather than called clean.
        owned = '<script type="application/json" id="reviewedSections">{}</script>\n'
        doc = self._build("{}")
        self.assertIn(owned, doc)
        doc = doc.replace(owned, "").replace(
            "<p>content</p>",
            '<p>content</p><script type="application/json" id="reviewedSections">{}</script>')
        self.assertError(doc, "is not on a <script> the EMBEDDED COMMENTS region owns")


if __name__ == "__main__":
    unittest.main()
