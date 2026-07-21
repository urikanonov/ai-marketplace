from _validate_helpers import *


class ValidateLayerStructureTests(ValidateAssertions, unittest.TestCase):
    def test_real_template_is_clean(self):
        self.assertTrue(os.path.exists(TEMPLATE), "dist/PORTABLE.html not found next to the tests")
        errors, warnings = validate.validate(TEMPLATE)
        self.assertEqual(errors, [], "dist/PORTABLE.html should have no errors, got: %r" % errors)
        self.assertEqual(warnings, [], "dist/PORTABLE.html should have no warnings, got: %r" % warnings)

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
            + json.dumps({"version": "1.0.0", "mode": "portable", "regions": EXPECTED_REGIONS},
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
        doc = build().replace('"mode":"portable"', '"mode":"nonportable"', 1)
        self.assertError(doc, 'commentableHtmlLayer.mode must be "portable" or "offline"')

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
        # Matches dist/PORTABLE.html (demo key + demo <title>): the survivor check is
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
        doc = build().replace("<p>content</p>", "<p>--START-COMMENTS-EXPORT--</p>")
        self.assertWarn(doc, "Export/Import UI detected")

    def test_missing_cp_variables(self):
        css = CSS_REGION.replace("--cp-bg: #ffffff;", "")
        self.assertError(build(css=css), "--cp-* theme variables are not defined")

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


if __name__ == "__main__":
    unittest.main()
