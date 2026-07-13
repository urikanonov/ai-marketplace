#!/usr/bin/env python3
"""Regression tests for validate.py (the commentable-html invariant checker).

Standard library only (unittest) - no third-party packages, matching validate.py.
Run from the skill root:

    python tests/test_validate.py      # or: python -m unittest discover -s tests -v

Most tests build a MINIMAL valid commentable document in-memory and mutate one
thing to assert a specific error/warning. One test validates the real
dist/PORTABLE.html as a positive control (it must pass with zero errors and zero
warnings). Several tests drive the CLI as a subprocess to cover exit codes,
CRLF, non-UTF-8 input, and batch behaviour. Coverage is mutation-checked: for
each validator branch there is a test that fails if the branch is deleted.
"""

import contextlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402  shared pkg/dev split path constants
ROOT = _paths.PKG
TOOLS = _paths.TOOLS
sys.path.insert(0, TOOLS)
import validate  # noqa: E402

TEMPLATE = os.path.join(ROOT, "dist", "PORTABLE.html")
VALIDATE_PY = os.path.join(TOOLS, "validate.py")

# Frozen, test-owned copy of the required-id contract. The fixture is built from
# THIS list (not validate.REQUIRED_IDS), and test_required_ids_contract asserts
# the two match - so shrinking or growing REQUIRED_IDS in the validator is a
# deliberate, test-visible change rather than a silent regression.
EXPECTED_REQUIRED_IDS = frozenset({
    "sidebar", "commentList", "contextMenu", "mermaidAddBtn", "diffAddBtn", "imageAddBtn", "hlBubble", "toast",
    "toolbarCount", "sidebarCount",
    "btnToggleSidebar", "btnCopyAll", "btnCopyAllTop", "btnClearAll",
    "btnCloseSidebar", "menuComment",
    "btnToolbarMenu", "toolbarMenu",
    "btnSaveHtml", "btnSaveHtmlTop", "btnSavePlain", "btnSavePlainTop",
    "btnExportOffline", "btnExportOfflineTop",
    "headingAddBtn", "widgetAddBtn", "menuDocComment",
})
EXPECTED_REGIONS = ["CSS", "HANDLED IDS", "EMBEDDED COMMENTS", "COMMENT UI", "JS"]
CONTENT_BEGIN = "<!-- BEGIN: commentable-html - CONTENT (agent edits ONLY between these markers) -->"
CONTENT_END = "<!-- END: commentable-html - CONTENT -->"


# --------------------------------------------------------------------------- #
# Minimal valid document builder. Region markers sit ALONE on their own line
# (BEGIN) exactly as the skill emits them.
# --------------------------------------------------------------------------- #

CSS_REGION = (
    "/*\n"
    "BEGIN: commentable-html - CSS\n"
    "*/\n"
    ":root { --cp-bg: #ffffff; --cp-text: #000000; }\n"
    ".cm-skip[hidden], .cm-skip [hidden] { display: none !important; }\n"
    "/*\n"
    "END: commentable-html - CSS\n"
    "*/"
)

HANDLED_REGION = (
    "<!--\n"
    "BEGIN: commentable-html - HANDLED IDS\n"
    "-->\n"
    '<script type="application/json" id="handledCommentIds">[]</script>\n'
    "<!-- END: commentable-html - HANDLED IDS -->"
)

EMBEDDED_REGION = (
    "<!--\n"
    "BEGIN: commentable-html - EMBEDDED COMMENTS\n"
    "-->\n"
    '<script type="application/json" id="embeddedComments">[]</script>\n'
    "<!-- END: commentable-html - EMBEDDED COMMENTS -->"
)

JS_REGION = (
    "<!--\n"
    "BEGIN: commentable-html - JS\n"
    "-->\n"
    "<script>\n(function () { var a = 1; return a; })();\n</script>\n"
    "<!-- END: commentable-html - JS -->"
)

MAIN = (
    '<main id="commentRoot" data-cmh-content-root data-comment-key="k" data-doc-label="l" data-doc-source="s">\n'
    + CONTENT_BEGIN + "\n"
    "  <p>content</p>\n"
    + CONTENT_END + "\n"
    "</main>"
)

_MERMAID_LOADER = (
    '<script type="module">const m = (await import('
    '"https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs")).default; '
    'm.initialize({ startOnLoad: false }); m.run().catch(() => {});</script>'
)


def comment_ui(extra=""):
    """COMMENT UI region carrying every EXPECTED_REQUIRED_ID except commentRoot.
    Built from the frozen test list so a shrink of validate.REQUIRED_IDS does not
    also shrink the fixture (that would hide the regression)."""
    ids = sorted(u for u in EXPECTED_REQUIRED_IDS if u != "commentRoot")
    spans = "\n".join('  <span id="%s" class="cm-skip"></span>' % u for u in ids)
    return (
        "<!--\n"
        "BEGIN: commentable-html - COMMENT UI\n"
        "-->\n"
        '<div class="cm-toolbar cm-skip">\n'
        + spans + "\n"
        + extra
        + "</div>\n"
        "<!-- END: commentable-html - COMMENT UI -->"
    )


def build(css=None, body=None):
    css = CSS_REGION if css is None else css
    if body is None:
        body = [HANDLED_REGION, EMBEDDED_REGION, comment_ui(), MAIN, JS_REGION]
    body_html = "\n".join(body)
    if CONTENT_BEGIN not in body_html:
        m = re.search(r'<main\b[^>]*\bid\s*=\s*(["\'])commentRoot\1[^>]*>', body_html, re.IGNORECASE)
        if m:
            close = body_html.find("</main>", m.end())
            if close != -1:
                body_html = body_html[:m.end()] + "\n" + CONTENT_BEGIN + body_html[m.end():close] + "\n" + CONTENT_END + "\n" + body_html[close:]
    return (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n'
        '<script type="application/json" id="commentableHtmlLayer">'
        + '{"version":"1.0.0","mode":"portable","regions":'
        + json.dumps(EXPECTED_REGIONS, separators=(",", ":"))
        + '}</script>\n'
        '<style>\n'
        + css
        + "\n</style>\n</head>\n<body>\n"
        + body_html
        + "\n</body>\n</html>\n"
    )


OFFLINE_CSP = (
    "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; "
    "font-src data:; connect-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; "
    "form-action 'none'; frame-ancestors 'none'"
)


def with_offline_mode(doc, csp=True):
    doc = doc.replace('"mode":"portable"', '"mode":"offline"', 1)
    if csp:
        meta = '<meta http-equiv="Content-Security-Policy" content="%s">\n' % OFFLINE_CSP
        doc = doc.replace("<head>\n", "<head>\n" + meta, 1)
    return doc


def _validate_text(content, crlf=False):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "doc.html")
        data = content.replace("\n", "\r\n") if crlf else content
        with open(p, "w", encoding="utf-8", newline="") as fh:
            fh.write(data)
        return validate.validate(p)


class ValidateUnitTests(unittest.TestCase):
    # -- assertion helpers -------------------------------------------------- #
    def assertOkNoWarn(self, content):
        errors, warnings = _validate_text(content)
        self.assertEqual(errors, [], "expected no errors, got: %r" % errors)
        self.assertEqual(warnings, [], "expected no warnings, got: %r" % warnings)

    def assertError(self, content, needle):
        errors, _ = _validate_text(content)
        self.assertTrue(any(needle in e for e in errors),
                        "expected an error containing %r, got: %r" % (needle, errors))

    def assertWarn(self, content, needle):
        errors, warnings = _validate_text(content)
        self.assertEqual(errors, [], "expected no errors, got: %r" % errors)
        self.assertTrue(any(needle in w for w in warnings),
                        "expected a warning containing %r, got: %r" % (needle, warnings))

    # -- contract ----------------------------------------------------------- #
    def test_required_ids_contract(self):
        # If this fails, REQUIRED_IDS changed: update EXPECTED_REQUIRED_IDS on
        # purpose (and make sure the template + fixture provide the id).
        self.assertEqual(set(validate.REQUIRED_IDS), set(EXPECTED_REQUIRED_IDS))

    # -- positive controls -------------------------------------------------- #
    def test_minimal_document_is_clean(self):
        self.assertOkNoWarn(build())

    def test_diff_block_is_tolerated(self):
        # A cmh-diff code-review block is authored content; the validator must
        # accept it (no false errors) and it must not disturb region/root checks.
        main_with_diff = (
            '<main id="commentRoot" data-cmh-content-root data-comment-key="k" data-doc-label="l" data-doc-source="s">\n'
            "  <p>content</p>\n"
            '  <pre class="cmh-diff" data-diff-label="a.py">@@ -1,2 +1,2 @@\n'
            " keep\n-old\n+new\n</pre>\n"
            "</main>"
        )
        body = [HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main_with_diff, JS_REGION]
        self.assertOkNoWarn(build(body=body))

    def test_diff_block_raw_html_errors_double_quoted_class(self):
        main = MAIN.replace("<p>content</p>", '<pre class="cmh-diff">@@ -1 +1 @@\n<img src=x>\n</pre>')
        self.assertError(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]),
                         "raw HTML tag")

    def test_diff_block_raw_html_errors_single_quoted_class(self):
        main = MAIN.replace("<p>content</p>", "<pre class='cmh-diff'>@@ -1 +1 @@\n<img src=x>\n</pre>")
        self.assertError(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]),
                         "raw HTML tag")

    def test_diff_block_raw_html_errors_unquoted_class(self):
        main = MAIN.replace("<p>content</p>", "<pre class=cmh-diff>@@ -1 +1 @@\n<img src=x>\n</pre>")
        self.assertError(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]),
                         "raw HTML tag")

    def test_diff_block_escaped_text_does_not_warn(self):
        main = MAIN.replace("<p>content</p>", '<pre class="cmh-diff">@@ -1 +1 @@\n-&lt;old&gt;\n+new\n</pre>')
        self.assertOkNoWarn(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]))

    def test_diff_block_reports_every_bad_block_in_one_pass(self):
        # Two offending diffs must both be surfaced (no early break) so the AI fixes
        # everything in a single validation iteration.
        two = ('<pre class="cmh-diff">@@ -1 +1 @@\n<img src=x>\n</pre>'
               '<pre class="cmh-diff">@@ -2 +2 @@\n<script>bad</script>\n</pre>')
        main = MAIN.replace("<p>content</p>", two)
        errors, _ = _validate_text(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]))
        raw = [e for e in errors if "raw HTML tag" in e]
        self.assertEqual(len(raw), 2, "both bad diff blocks should be reported, got: %r" % raw)
        self.assertIn("diff block #1", raw[0])
        self.assertIn("diff block #2", raw[1])

    def test_minimal_document_crlf_is_clean(self):
        errors, warnings = _validate_text(build(), crlf=True)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_kusto_run_link_valid_is_clean(self):
        link = ('<a class="cmh-kql-run" href="https://dataexplorer.azure.com/clusters/c/databases/d?query=H4sI" '
                'target="_blank" rel="noopener noreferrer">Run in Azure Data Explorer</a>')
        main = MAIN.replace("<p>content</p>", "<p>content</p>" + link)
        self.assertOkNoWarn(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]))

    def test_kusto_run_link_wrong_origin_warns(self):
        link = '<a class="cmh-kql-run" href="https://evil.example.com/x" target="_blank" rel="noopener">Run</a>'
        main = MAIN.replace("<p>content</p>", "<p>content</p>" + link)
        self.assertWarn(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]),
                        "does not point at https://dataexplorer.azure.com/")

    def test_kusto_run_link_blank_without_noopener_warns(self):
        link = ('<a class="cmh-kql-run" href="https://dataexplorer.azure.com/x" target="_blank">Run</a>')
        main = MAIN.replace("<p>content</p>", "<p>content</p>" + link)
        self.assertWarn(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]),
                        'without rel="noopener"')

    def test_plain_kusto_code_block_no_runlink_is_clean(self):
        # A KQL code block WITHOUT a run link must NOT warn (the check is gated on
        # the explicit cmh-kql-run class, so syntax examples are never flagged).
        block = '<pre><code class="language-kusto">T | take 1</code></pre>'
        main = MAIN.replace("<p>content</p>", "<p>content</p>" + block)
        self.assertOkNoWarn(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]))

    def test_kql_figure_without_run_link_warns(self):
        fig = ('<figure class="cmh-kql"><figcaption class="cm-skip">'
               '<button class="cmh-kql-title" type="button">cluster</button></figcaption>'
               '<pre><code class="language-kusto">T | take 1</code></pre></figure>')
        main = MAIN.replace("<p>content</p>", "<p>content</p>" + fig)
        self.assertWarn(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]),
                        'figure.cmh-kql has no "Run in Azure Data Explorer" link')

    def test_kql_figure_with_run_link_is_clean(self):
        fig = ('<figure class="cmh-kql"><figcaption class="cm-skip">'
               '<button class="cmh-kql-title" type="button">cluster</button>'
               '<a class="cmh-kql-run" href="https://dataexplorer.azure.com/x" '
               'target="_blank" rel="noopener noreferrer">Run in Azure Data Explorer</a></figcaption>'
               '<pre><code class="language-kusto">T | take 1</code></pre></figure>')
        main = MAIN.replace("<p>content</p>", "<p>content</p>" + fig)
        self.assertOkNoWarn(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]))

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

    # -- regions ------------------------------------------------------------ #
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

    # -- commentRoot -------------------------------------------------------- #
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

    # -- retrofit / demo leftovers ------------------------------------------ #
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

    # -- text-anchoring robustness ------------------------------------------ #
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
    # A function merely NAMED like offsetWithin* (offsetWithinX) is NOT the real
    # offsetWithin(), so the normalizeBoundary requirement must stay exempt.
    _JS_OFFSETWITHIN_PREFIX_DECOY = (
        "<!--\nBEGIN: commentable-html - JS\n-->\n"
        "<script>\n(function(){ function offsetWithinX(n,o){ return -1; } })();\n</script>\n"
        "<!-- END: commentable-html - JS -->"
    )
    # normalizeBoundary present only inside comments -> must still error: the
    # string/comment-blanked scan strips it, so the guard fires (F-C2 false-pass).
    _JS_OFFSET_COMMENTED = (
        "<!--\nBEGIN: commentable-html - JS\n-->\n"
        "<script>\n(function(){\n"
        "/* function normalizeBoundary(n,o){ return [n,o]; } */\n"
        "function offsetWithin(n,o){ /* normalizeBoundary(n,o) */ return -1; } })();\n</script>\n"
        "<!-- END: commentable-html - JS -->"
    )
    # normalizeBoundary token present only inside a string literal -> must error.
    _JS_OFFSET_STRINGCALL = (
        "<!--\nBEGIN: commentable-html - JS\n-->\n"
        "<script>\n(function(){\n"
        'function offsetWithin(n,o){ var s = "normalizeBoundary("; return -1; } })();\n</script>\n'
        "<!-- END: commentable-html - JS -->"
    )
    # Valid helper + real call, but the body also has a `}` inside a string literal
    # -> must NOT false-fail (F-C2 false-fail: string-blanked brace matching).
    _JS_OFFSET_BRACE_STRING = (
        "<!--\nBEGIN: commentable-html - JS\n-->\n"
        "<script>\n(function(){ function normalizeBoundary(n,o){ return [n,o]; }\n"
        'function offsetWithin(n,o){ var s = "}"; [n,o]=normalizeBoundary(n,o); return -1; } })();\n</script>\n'
        "<!-- END: commentable-html - JS -->"
    )
    # Helper declared and called, but the call is in an UNRELATED later function,
    # not inside offsetWithin's body -> must error (body-local check).
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

    # -- JSON script blocks ------------------------------------------------- #
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

    # -- JS region ---------------------------------------------------------- #
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

    # -- required / forbidden ids ------------------------------------------- #
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

    def test_missing_required_id_menu_doc_comment(self):
        doc = build().replace('<span id="menuDocComment" class="cm-skip"></span>', "")
        self.assertError(doc, 'required element id="menuDocComment" is missing')

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

    # -- theme variables ---------------------------------------------------- #
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

    # -- [hidden] scoping --------------------------------------------------- #
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

    # -- mermaid ------------------------------------------------------------ #
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

    # -- mermaid renders on open (loader present, triggers a render, not gated) ---- #
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


# --------------------------------------------------------------------------- #
# NonPortable-mode fixtures: CSS/JS live in companion files referenced via
# <link>/<script src>; HANDLED IDS, EMBEDDED COMMENTS and COMMENT UI stay inline.
# --------------------------------------------------------------------------- #
NONPORTABLE_VERSION = "1.0.0"


def layer_descriptor(version=NONPORTABLE_VERSION, mode="portable", regions=None):
    data = {
        "version": version,
        "mode": mode,
        "regions": EXPECTED_REGIONS if regions is None else regions,
    }
    return '<script type="application/json" id="commentableHtmlLayer">%s</script>' % json.dumps(data, separators=(",", ":"))


def nonportable_bootstrap(banner=True, watchdog=True):
    inner = ""
    if banner:
        inner += '<div id="cmhAssetBanner" class="cm-skip" role="alert" hidden>missing</div>\n'
    if watchdog:
        inner += ("<script>window.setTimeout(function () { "
                  "if (!window.__commentableHtmlReady) {} }, 3000);</script>\n")
    return ("<!-- BEGIN: commentable-html - NONPORTABLE BOOTSTRAP -->\n"
            + inner
            + "<!-- END: commentable-html - NONPORTABLE BOOTSTRAP -->")


def nonportable_scripts(version=NONPORTABLE_VERSION, runtime=True, assets=True):
    out = ["<!--\nBEGIN: commentable-html - JS\n-->"]
    if assets:
        out.append('<script src="commentable-html.assets.js"></script>')
    if runtime:
        out.append('<script src="commentable-html.js"></script>')
    out.append("<!-- END: commentable-html - JS -->")
    return "\n".join(out)


def build_nonportable(version=NONPORTABLE_VERSION, link=True, runtime=True, assets=True, meta=True,
                  banner=True, watchdog=True, link_version=None):
    """A minimal, valid nonportable document (theme vars inline, layer externalized)."""
    head = [
        '<script type="application/json" id="commentableHtmlLayer">%s</script>'
        % json.dumps({"version": version, "mode": "nonportable", "regions": EXPECTED_REGIONS},
                     separators=(",", ":")),
        "<style>\n:root { --cp-bg: #fff; --cp-text: #000; }\n</style>",
    ]
    if link:
        head.append("<!--\nBEGIN: commentable-html - CSS\n-->\n"
                    '<link rel="stylesheet" href="commentable-html.css">\n'
                    "<!-- END: commentable-html - CSS -->")
    if meta:
        head.append('<meta name="commentable-html-version" content="%s">' % version)
    body = [nonportable_bootstrap(banner, watchdog), HANDLED_REGION, EMBEDDED_REGION,
            comment_ui(), MAIN, nonportable_scripts(version, runtime, assets)]
    return ('<!DOCTYPE html>\n<html lang="en">\n<head>\n'
            + "\n".join(head)
            + "\n</head>\n<body>\n"
            + "\n".join(body)
            + "\n</body>\n</html>\n")


class SectionReferenceLinkTests(unittest.TestCase):
    """Deterministic detection of section cross-references in prose that are NOT links."""

    HEADS = '<h2 id="a">Alpha</h2><h2 id="b">Beta plan</h2>'

    def _main(self, content):
        return ('<main id="commentRoot" data-cmh-content-root data-comment-key="k" data-doc-label="l" data-doc-source="s">\n'
                + content + "\n</main>")

    def _warns(self, content):
        errors, warnings = _validate_text(
            build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), self._main(content), JS_REGION]))
        self.assertEqual(errors, [], errors)
        return any("cross-reference" in w for w in warnings)

    def test_unlinked_directional_reference_warns(self):
        self.assertTrue(self._warns(self.HEADS + "<p>See the section below for details.</p>"))

    def test_previous_section_reference_warns(self):
        self.assertTrue(self._warns(self.HEADS + "<p>As in the previous section, retries apply.</p>"))

    def test_linked_directional_reference_ok(self):
        self.assertFalse(self._warns(self.HEADS + '<p>See <a href="#b">the section below</a> for details.</p>'))

    def test_unlinked_named_reference_warns(self):
        self.assertTrue(self._warns(self.HEADS + "<p>Refer to Beta plan for the rollout.</p>"))

    def test_named_reference_with_section_suffix_warns(self):
        self.assertTrue(self._warns(self.HEADS + "<p>The Beta plan section covers rollout.</p>"))

    def test_linked_named_reference_ok(self):
        self.assertFalse(self._warns(self.HEADS + '<p>Refer to <a href="#b">Beta plan</a> for the rollout.</p>'))

    def test_benign_directional_word_not_flagged(self):
        # "below freezing" has no section word adjacent, so it is not a cross reference.
        self.assertFalse(self._warns(self.HEADS + "<p>Temperatures were below freezing overnight.</p>"))

    def test_reference_inside_cm_skip_ignored(self):
        self.assertFalse(self._warns(self.HEADS + '<nav class="cm-skip"><p>see the section above</p></nav><p>body</p>'))

    def test_reference_after_root_close_ignored(self):
        # A directional cross-reference in a sibling <footer> AFTER </main id=commentRoot>
        # is outside the reviewable content and must not be validated as prose.
        body = [HANDLED_REGION, EMBEDDED_REGION, comment_ui(),
                self._main(self.HEADS + "<p>Body text.</p>"),
                '<footer><h2 id="c">Gamma plan</h2>'
                "<p>See the section below for details.</p></footer>",
                JS_REGION]
        errors, warnings = _validate_text(build(body=body))
        self.assertEqual(errors, [], errors)
        self.assertFalse(any("cross-reference" in w for w in warnings), warnings)

    def test_named_reference_to_nonexistent_heading_not_flagged(self):
        self.assertFalse(self._warns(self.HEADS + "<p>Refer to Gamma plan for details.</p>"))

    def test_single_heading_document_skips_named_check(self):
        self.assertFalse(self._warns('<h2 id="a">Overview</h2><p>The overview covers scope.</p>'))


class NonPortableTests(unittest.TestCase):
    """Dual-mode validation: the nonportable branch and its guardrails."""

    def _validate(self, content, companions=("css", "js", "assets"), version=NONPORTABLE_VERSION):
        exts = {"css": ".css", "js": ".js", "assets": ".assets.js"}
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "doc.html")
            with open(p, "w", encoding="utf-8", newline="") as fh:
                fh.write(content)
            for c in companions:
                with open(os.path.join(d, "commentable-html%s" % exts[c]), "w",
                          encoding="utf-8") as fh:
                    fh.write("/* stub */")
            return validate.validate(p)

    def assertNonPortableError(self, content, needle, **kw):
        errors, _ = self._validate(content, **kw)
        self.assertTrue(any(needle in e for e in errors),
                        "expected an error containing %r, got: %r" % (needle, errors))

    def assertNonPortableWarn(self, content, needle, **kw):
        errors, warnings = self._validate(content, **kw)
        self.assertEqual(errors, [], "expected no errors, got: %r" % errors)
        self.assertTrue(any(needle in w for w in warnings),
                        "expected a warning containing %r, got: %r" % (needle, warnings))

    # -- positive controls -------------------------------------------------- #
    def test_minimal_nonportable_is_clean(self):
        errors, warnings = self._validate(build_nonportable())
        self.assertEqual(errors, [], "nonportable errors: %r" % errors)
        self.assertEqual(warnings, [], "nonportable warnings: %r" % warnings)

    def test_nonportable_document_rejects_offline_mode(self):
        html = build_nonportable().replace('"mode":"nonportable"', '"mode":"offline"', 1)
        self.assertNonPortableError(html, 'commentableHtmlLayer.mode must be "nonportable"')

    def test_real_nonportable_template_is_clean(self):
        eco = os.path.join(ROOT, "dist", "NONPORTABLE.html")
        self.assertTrue(os.path.exists(eco), "dist/NONPORTABLE.html not found - run python tools/build.py")
        errors, warnings = validate.validate(eco)
        self.assertEqual(errors, [], "dist/NONPORTABLE.html errors: %r" % errors)
        self.assertEqual(warnings, [], "dist/NONPORTABLE.html warnings: %r" % warnings)

    def test_is_nonportable_detection(self):
        self.assertTrue(validate._is_nonportable(build_nonportable()))
        self.assertFalse(validate._is_nonportable(build()))

    def test_nonportable_detection_ignores_attribute_substrings(self):
        # A decoy tag whose attribute NAME merely contains "href"/"src" as a
        # substring (data-href / data-src) must NOT be treated as a real
        # companion reference - the browser would never load it.
        decoy = (
            '<!DOCTYPE html>\n<html><head>\n'
            '<link rel="preload" data-href="commentable-html.css">\n'
            '<script type="application/json" data-src="commentable-html.js">{}</script>\n'
            '</head><body>\n'
            + "\n".join([HANDLED_REGION, EMBEDDED_REGION, comment_ui(), MAIN])
            + '\n</body></html>\n')
        self.assertFalse(validate._is_nonportable(decoy))

    def test_nonportable_detection_accepts_unquoted_and_reordered_attrs(self):
        # Unquoted href/src and a reordered <meta content=.. name=..> are valid
        # HTML that the browser loads, so nonportable detection must recognize them.
        v = NONPORTABLE_VERSION
        unquoted = (
            "<!DOCTYPE html>\n<html><head>\n"
            "<link rel=stylesheet href=commentable-html.css>\n"
            "<script src=commentable-html.js></script>\n"
            "</head><body>\n"
            + "\n".join([HANDLED_REGION, EMBEDDED_REGION, comment_ui(), MAIN])
            + "\n</body></html>\n")
        self.assertTrue(validate._is_nonportable(unquoted))
        self.assertEqual(validate._nonportable_css_refs(unquoted), ["commentable-html.css"])
        # Reordered meta (content before name) is still read for the version.
        reordered = '<meta content="%s" name="commentable-html-version">' % v
        self.assertEqual(validate._nonportable_meta_versions(reordered), [v])

    def test_nonportable_detection_is_case_insensitive(self):
        # The "commentable-html" substring and the extension are matched
        # case-insensitively, so a mixed-case companion reference is still detected.
        v = NONPORTABLE_VERSION
        mixed = (
            "<!DOCTYPE html>\n<html><head>\n"
            '<link rel="stylesheet" href="Commentable-HTML.CSS">\n'
            '<script src="Commentable-HTML.JS"></script>\n'
            "</head><body>\n"
            + "\n".join([HANDLED_REGION, EMBEDDED_REGION, comment_ui(), MAIN])
            + "\n</body></html>\n")
        self.assertTrue(validate._is_nonportable(mixed))
        self.assertEqual(validate._nonportable_css_refs(mixed), ["Commentable-HTML.CSS"])
        self.assertEqual(validate._nonportable_js_refs(mixed), ["Commentable-HTML.JS"])

    def test_nonportable_detection_ignores_gt_in_value_and_decoys(self):
        # The HTMLParser-based scan must (a) not be fooled by a '>' inside a quoted
        # attribute value, and (b) ignore link/script tags that only appear inside an
        # HTML comment or a <script>/<style> body (CDATA), which a naive regex matched.
        v = NONPORTABLE_VERSION
        gt_in_value = '<link rel="stylesheet" title="a>b" href="commentable-html.css">'
        self.assertEqual(validate._nonportable_css_refs(gt_in_value), ["commentable-html.css"])
        commented = '<!-- <link rel="stylesheet" href="commentable-html.css"> -->'
        self.assertEqual(validate._nonportable_css_refs(commented), [])
        in_script = '<script>var s = "<link href=\'commentable-html.css\'>";</script>'
        self.assertEqual(validate._nonportable_css_refs(in_script), [])

    def test_nonportable_detection_accepts_cache_busted_refs(self):
        # A ?query / #fragment cache-buster is stripped by the browser before it
        # fetches the file, so detection and the on-disk check must ignore it too.
        busted = (
            '<link rel="stylesheet" href="commentable-html.css?v=1.7.0">'
            '<script src="commentable-html.js#build9"></script>'
            '<script src="commentable-html.assets.js?v=1.7.0"></script>')
        self.assertEqual(validate._nonportable_css_refs(busted), ["commentable-html.css"])
        self.assertEqual(validate._nonportable_js_refs(busted),
                         ["commentable-html.js", "commentable-html.assets.js"])

    def test_cache_busted_companion_refs_validate_clean(self):
        doc = (build_nonportable()
               .replace('href="commentable-html.css"', 'href="commentable-html.css?v=1.7.0"')
               .replace('src="commentable-html.assets.js"', 'src="commentable-html.assets.js?v=1.7.0"')
               .replace('src="commentable-html.js"', 'src="commentable-html.js?v=1.7.0"'))
        errors, warnings = self._validate(doc)
        self.assertEqual(errors, [], "cache-busted refs should validate clean: %r" % errors)
        self.assertEqual(warnings, [], "cache-busted refs should not warn: %r" % warnings)


    def test_missing_stylesheet_link_errors(self):
        self.assertNonPortableError(build_nonportable(link=False), "no commentable-html stylesheet")

    def test_missing_runtime_script_errors(self):
        self.assertNonPortableError(build_nonportable(runtime=False), "no commentable-html runtime")

    def test_missing_assets_js_warns(self):
        self.assertNonPortableWarn(build_nonportable(assets=False), "Export with embedded comments", companions=("css", "js"))

    def test_missing_version_meta_warns(self):
        self.assertNonPortableWarn(build_nonportable(meta=False), 'missing <meta name="commentable-html-version"')

    def test_version_meta_does_not_compare_to_versionless_filenames(self):
        html = build_nonportable(version="9.9.9")
        errors, warnings = self._validate(html)
        self.assertEqual(errors, [])
        self.assertFalse(any("must match" in w for w in warnings), warnings)

    def test_missing_banner_errors(self):
        self.assertNonPortableError(build_nonportable(banner=False), "#cmhAssetBanner")

    def test_missing_watchdog_warns(self):
        self.assertNonPortableWarn(build_nonportable(watchdog=False), "bootstrap watchdog")

    def test_missing_companion_file_errors(self):
        # HTML references the runtime but the .js file is absent on disk.
        self.assertNonPortableError(build_nonportable(), "companion file not found", companions=("css", "assets"))

    def test_nonportable_state_regions_still_validated(self):
        # Dropping the inline HANDLED IDS region must still fail in nonportable mode.
        html = build_nonportable().replace(HANDLED_REGION, "")
        self.assertNonPortableError(html, "handledCommentIds")

    def test_nonportable_uses_marker_wrapped_companion_regions(self):
        html = build_nonportable()
        self.assertIn("BEGIN: commentable-html - CSS", html)
        self.assertIn("BEGIN: commentable-html - JS", html)

    def test_absolute_companion_path_warns(self):
        # An absolute path is usable but leaks a local directory - warn, do not error.
        with tempfile.TemporaryDirectory() as d:
            css = os.path.join(d, "commentable-html.css")
            for c, ext in (("css", ".css"), ("js", ".js"), ("assets", ".assets.js")):
                with open(os.path.join(d, "commentable-html%s" % ext), "w") as fh:
                    fh.write("/* stub */")
            html = build_nonportable().replace(
                'href="commentable-html.css"',
                'href="%s"' % css.replace("\\", "/"))
            p = os.path.join(d, "doc.html")
            with open(p, "w", encoding="utf-8", newline="") as fh:
                fh.write(html)
            errors, warnings = validate.validate(p)
        self.assertEqual(errors, [], errors)
        self.assertTrue(any("absolute path" in w for w in warnings), warnings)

    def test_file_url_companion_refs_validate_clean(self):
        with tempfile.TemporaryDirectory() as d:
            urls = {}
            for ext in (".css", ".js", ".assets.js"):
                p = os.path.join(d, "commentable-html%s" % ext)
                with open(p, "w", encoding="utf-8") as fh:
                    fh.write("/* stub */")
                urls[ext] = Path(p).resolve().as_uri()
            html = (build_nonportable()
                    .replace('href="commentable-html.css"', 'href="%s"' % urls[".css"])
                    .replace('src="commentable-html.js"', 'src="%s"' % urls[".js"])
                    .replace('src="commentable-html.assets.js"', 'src="%s"' % urls[".assets.js"]))
            p = os.path.join(d, "doc.html")
            with open(p, "w", encoding="utf-8", newline="") as fh:
                fh.write(html)
            errors, warnings = validate.validate(p)
        self.assertEqual(errors, [], errors)
        self.assertFalse(any("remote/CDN URL" in w or "absolute path" in w for w in warnings), warnings)

    def test_companion_parent_relative_ref_ok(self):
        # NonPortable may point at the skill dist/ folder via a ../ path; if the target
        # resolves to an existing file it is valid (no "escapes the folder" error).
        with tempfile.TemporaryDirectory() as d:
            sub = os.path.join(d, "reports")
            os.makedirs(sub)
            for ext in (".css", ".js", ".assets.js"):
                with open(os.path.join(d, "commentable-html%s" % ext), "w") as fh:
                    fh.write("/* stub */")
            html = (build_nonportable()
                    .replace('href="commentable-html.css"',
                             'href="../commentable-html.css"')
                    .replace('src="commentable-html.js"',
                             'src="../commentable-html.js"')
                    .replace('src="commentable-html.assets.js"',
                             'src="../commentable-html.assets.js"'))
            p = os.path.join(sub, "doc.html")
            with open(p, "w", encoding="utf-8", newline="") as fh:
                fh.write(html)
            errors, warnings = validate.validate(p)
        self.assertEqual(errors, [], errors)

    def test_companion_in_subfolder_ok(self):
        # A subdirectory reference (e.g. the skill's dist/) is the intended nonportable
        # workflow, so it is valid as long as the file exists at the resolved path.
        with tempfile.TemporaryDirectory() as d:
            dist = os.path.join(d, "dist")
            os.makedirs(dist)
            for ext in (".css", ".js", ".assets.js"):
                with open(os.path.join(dist, "commentable-html%s" % ext), "w") as fh:
                    fh.write("/* stub */")
            html = (build_nonportable()
                    .replace('href="commentable-html.css"',
                             'href="dist/commentable-html.css"')
                    .replace('src="commentable-html.js"',
                             'src="dist/commentable-html.js"')
                    .replace('src="commentable-html.assets.js"',
                             'src="dist/commentable-html.assets.js"'))
            p = os.path.join(d, "doc.html")
            with open(p, "w", encoding="utf-8", newline="") as fh:
                fh.write(html)
            errors, warnings = validate.validate(p)
        self.assertEqual(errors, [], errors)

    def test_remote_companion_url_errors(self):
        html = build_nonportable().replace(
            'href="commentable-html.css"',
            'href="https://cdn.example.com/commentable-html.css"')
        self.assertNonPortableError(html, "remote/CDN URL")

    def test_protocol_relative_companion_url_errors(self):
        html = build_nonportable().replace(
            'href="commentable-html.css"',
            'href="//cdn.example.com/commentable-html.css"')
        self.assertNonPortableError(html, "remote/CDN URL")

    def test_non_file_scheme_companion_ref_errors(self):
        html = build_nonportable().replace(
            'src="commentable-html.js"',
            'src="vscode://extension/commentable-html.js"')
        self.assertNonPortableError(html, "non-file URL scheme")

    def test_nonportable_demo_key_survivor_is_flagged(self):
        # The real nonportable template (nonportable demo key + nonportable demo title) is clean,
        # but changing only the title while keeping the demo key is a survived retrofit.
        eco = os.path.join(ROOT, "dist", "NONPORTABLE.html")
        with open(eco, encoding="utf-8") as fh:
            html = fh.read()
        mutated = html.replace("<title>Commentable HTML - NonPortable Demo</title>",
                               "<title>My Real NonPortable Doc</title>")
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "NONPORTABLE.html")
            with open(p, "w", encoding="utf-8", newline="") as fh:
                fh.write(mutated)
            for c in ("css", "js", "assets"):
                ext = {"css": ".css", "js": ".js", "assets": ".assets.js"}[c]
                with open(os.path.join(d, "commentable-html%s" % ext), "w", encoding="utf-8") as fh:
                    fh.write("/* stub */")
            errors, _ = validate.validate(p)
        self.assertTrue(any("demo content root survived" in e for e in errors), errors)


class ValidateCliTests(unittest.TestCase):
    def _run(self, *args):
        return subprocess.run([sys.executable, VALIDATE_PY, *args], capture_output=True, text=True)

    def _write(self, d, name, content, raw=None):
        p = os.path.join(d, name)
        if raw is not None:
            with open(p, "wb") as fh:
                fh.write(raw)
        else:
            with open(p, "w", encoding="utf-8", newline="") as fh:
                fh.write(content)
        return p

    def test_no_args_exit_2(self):
        self.assertEqual(self._run().returncode, 2)

    def test_both_flags_exit_2(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d, "ok.html", build())
            self.assertEqual(self._run("--charts-only", "--layer-only", p).returncode, 2)

    def test_unknown_flag_exit_2(self):
        # An unrecognized --flag must fail loudly rather than being silently ignored.
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d, "ok.html", build())
            r = self._run("--layer-onyl", p)
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            self.assertIn("unknown flag", r.stderr)
            self.assertIn("--layer-onyl", r.stderr)

    def test_layer_only_suppresses_chart_errors(self):
        # Layer-valid doc with an unskipped <canvas> (a chart E1). --layer-only must
        # skip the chart half, so exit 0 and no chart error text.
        doc = build().replace("</main>", '<canvas id="z" role="img" aria-label="x"></canvas></main>')
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d, "layeronly.html", doc)
            r = self._run("--layer-only", p)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertNotIn("not inside a cm-skip", r.stdout)

    def test_charts_only_suppresses_layer_errors(self):
        # Layer-broken doc (a mangled region marker) but no <canvas>. --charts-only
        # skips the layer half, so exit 0 with no region error.
        doc = build().replace("BEGIN: commentable-html - CSS", "BEGIN: commentable-html - BROKEN")
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d, "chartsonly.html", doc)
            r = self._run("--charts-only", p)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertNotIn("region", r.stdout)

    def test_valid_file_exit_0(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d, "ok.html", build())
            r = self._run(p)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("OK (0 warning(s))", r.stdout)

    def test_warning_only_file_exit_0(self):
        main = '<main id="commentRoot" data-cmh-content-root data-comment-key="k" data-doc-label="l"><p>x</p></main>'
        doc = build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION])
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d, "warn.html", doc)
            r = self._run(p)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("WARNING", r.stdout)

    def test_broken_file_exit_1(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d, "bad.html", "not a commentable document")
            self.assertEqual(self._run(p).returncode, 1)

    def test_non_utf8_does_not_crash(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d, "bin.html", None, raw=b"\xff\xfe\x00\x01 not utf-8")
            r = self._run(p)
            out = r.stdout + r.stderr
            self.assertNotIn("Traceback (most recent call last)", out)
            self.assertIn("cannot read file", out)
            self.assertEqual(r.returncode, 1)

    def test_batch_continues_after_bad_file(self):
        with tempfile.TemporaryDirectory() as d:
            bad = self._write(d, "bin.html", None, raw=b"\xff\xfe garbage")
            good = self._write(d, "good.html", build())
            r = self._run(bad, good)
            out = r.stdout + r.stderr
            self.assertNotIn("Traceback (most recent call last)", out)
            self.assertIn("cannot read file", out)
            self.assertIn("OK (0 warning(s))", out)
            self.assertEqual(r.returncode, 1)

    def test_directory_argument_is_reported_not_crashed(self):
        with tempfile.TemporaryDirectory() as d:
            r = self._run(d)
            out = r.stdout + r.stderr
            self.assertNotIn("Traceback (most recent call last)", out)
            self.assertIn("cannot read file", out)
            self.assertEqual(r.returncode, 1)


class ValidateMainTests(unittest.TestCase):
    def test_main_guards_each_file_against_internal_errors(self):
        # A crash inside validate() for one file must be reported as an internal
        # error but must not abort the batch: the second file still validates.
        buf = io.StringIO()
        with mock.patch.object(validate, "validate", side_effect=[RuntimeError("boom"), ([], [])]):
            with contextlib.redirect_stdout(buf):
                rc = validate.main(["validate.py", "a.html", "b.html"])
        out = buf.getvalue()
        self.assertEqual(rc, 1)
        self.assertIn("internal validator error", out)
        self.assertIn("a.html", out)
        self.assertIn("b.html", out)
        self.assertIn("OK", out)  # b.html still validated

    def test_main_returns_0_when_all_clean(self):
        buf = io.StringIO()
        with mock.patch.object(validate, "validate", return_value=([], [])):
            with contextlib.redirect_stdout(buf):
                rc = validate.main(["validate.py", "x.html"])
        self.assertEqual(rc, 0)


class ErrorPathTests(unittest.TestCase):
    """The validator's failure and resilience paths: unreadable input, unparseable
    markup, unknown CLI flags, and a check that throws mid-batch."""

    def _tmp(self, text):
        fd, p = tempfile.mkstemp(suffix=".html")
        os.close(fd)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)
        self.addCleanup(lambda: os.path.exists(p) and os.remove(p))
        return p

    def test_validate_unreadable_file_returns_error(self):
        missing = os.path.join(tempfile.gettempdir(), "cmh-does-not-exist-xyz.html")
        errors, warnings = validate.validate(missing)
        self.assertTrue(errors and errors[0].startswith("cannot read file:"))
        self.assertEqual(warnings, [])

    def test_validate_charts_unreadable_file_returns_error(self):
        missing = os.path.join(tempfile.gettempdir(), "cmh-does-not-exist-xyz.html")
        errors, warnings, n = validate.validate_charts(missing)
        self.assertTrue(errors and errors[0].startswith("cannot read file:"))
        self.assertEqual((warnings, n), ([], 0))

    def test_validate_unparseable_markup_reports_parse_failure(self):
        p = self._tmp("<html>ignored</html>")
        with mock.patch.object(validate, "_parse", return_value=(None, False)):
            errors, warnings = validate.validate(p)
        self.assertEqual(errors, [validate._PARSE_FAIL])
        self.assertEqual(warnings, [])

    def test_validate_charts_unparseable_with_canvas_reports_parse_failure(self):
        p = self._tmp("<html><canvas></canvas></html>")
        with mock.patch.object(validate, "_parse", return_value=(None, False)):
            errors, warnings, n = validate.validate_charts(p)
        self.assertEqual(errors, [validate._PARSE_FAIL])
        self.assertEqual(n, 1)

    def test_main_rejects_unknown_flag(self):
        p = self._tmp("<html></html>")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = validate.main(["validate.py", "--bogus", p])
        self.assertEqual(rc, 2)
        self.assertIn("unknown flag(s): --bogus", err.getvalue())

    def test_main_no_files_prints_usage(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = validate.main(["validate.py"])
        self.assertEqual(rc, 2)
        self.assertIn("usage:", err.getvalue())

    def test_main_internal_check_error_does_not_abort_batch(self):
        p = self._tmp("<html></html>")
        out = io.StringIO()
        with mock.patch.object(validate, "validate", side_effect=RuntimeError("boom")):
            with contextlib.redirect_stdout(out):
                rc = validate.main(["validate.py", p])
        self.assertEqual(rc, 1)
        self.assertIn("internal validator error", out.getvalue())


class NewCheckTests(unittest.TestCase):
    """Coverage for the self-contained-guarantee, embedded-comment schema, duplicate-heading,
    canvas-report-all, and --strict additions."""

    def _body(self, main, *extra):
        return [HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main] + list(extra) + [JS_REGION]

    def _errs_warns(self, content):
        return _validate_text(content)

    # -- self-contained guarantee -------------------------------------------------- #
    def test_external_img_src_errors(self):
        main = MAIN.replace("<p>content</p>", '<p>content</p>\n  <img src="https://example.com/x.png" alt="x">')
        errors, _ = self._errs_warns(build(body=self._body(main)))
        self.assertTrue(any("loads over the network" in e for e in errors), errors)

    def test_local_path_img_warns_not_errors(self):
        main = MAIN.replace("<p>content</p>", '<p>content</p>\n  <img src="images/x.png" alt="x">')
        errors, warnings = self._errs_warns(build(body=self._body(main)))
        self.assertEqual(errors, [], errors)
        self.assertTrue(any("local path" in w for w in warnings), warnings)

    def test_data_uri_img_is_clean(self):
        main = MAIN.replace("<p>content</p>", '<p>content</p>\n  <img src="data:image/png;base64,AAAA" alt="x">')
        errors, warnings = self._errs_warns(build(body=self._body(main)))
        self.assertEqual(errors, [], errors)
        self.assertEqual(warnings, [], warnings)

    def test_external_script_src_errors(self):
        errors, _ = self._errs_warns(build(body=self._body(MAIN, '<script src="https://evil.cdn/x.js"></script>')))
        self.assertTrue(any("self-contained guarantee" in e for e in errors), errors)

    def test_chartjs_cdn_script_is_exempt_from_self_contained_error(self):
        script = '<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>'
        errors, _ = self._errs_warns(build(body=self._body(MAIN, script)))
        self.assertFalse(any("self-contained guarantee" in e for e in errors), errors)

    def test_offline_mode_rejects_chartjs_cdn_script(self):
        script = '<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>'
        doc = with_offline_mode(build(body=self._body(MAIN, script)))
        errors, _ = self._errs_warns(doc)
        self.assertTrue(any("offline mode" in e and "Chart.js" in e for e in errors), errors)

    def test_offline_mode_rejects_network_resources_and_css_imports(self):
        css = CSS_REGION.replace(
            ":root { --cp-bg: #ffffff; --cp-text: #000000; }",
            '@import "https://cdn.example.com/theme.css";\n'
            ":root { --cp-bg: #ffffff; --cp-text: #000000; }")
        main = MAIN.replace(
            "<p>content</p>",
            '<img src="https://example.com/x.png" alt="x">\n'
            '<iframe src="https://example.com/f.html"></iframe>\n'
            '<video poster="https://example.com/poster.png"><track src="https://example.com/c.vtt"></video>')
        extras = [
            '<link rel="stylesheet" href="https://example.com/app.css">',
            '<script src="https://example.com/app.js"></script>',
        ]
        doc = with_offline_mode(build(css=css, body=self._body(main, *extras)))
        errors, _ = self._errs_warns(doc)
        for needle in ("<img", "<iframe", "<video", "<track", "<link", "<script", "@import"):
            self.assertTrue(any("offline mode" in e and needle in e for e in errors),
                            "expected offline error for %s, got %r" % (needle, errors))

    def test_offline_mode_accepts_inlined_data_resources(self):
        main = MAIN.replace(
            "<p>content</p>",
            '<img src="data:image/png;base64,AAAA" alt="x">\n'
            '<video poster="data:image/png;base64,AAAA"></video>')
        doc = with_offline_mode(build(body=self._body(main)))
        errors, warnings = self._errs_warns(doc)
        self.assertEqual(errors, [], errors)
        self.assertEqual(warnings, [], warnings)

    def test_offline_mode_requires_restrictive_csp(self):
        errors, _ = self._errs_warns(with_offline_mode(build(), csp=False))
        self.assertTrue(any("Content-Security-Policy" in e for e in errors), errors)
        weak = with_offline_mode(build()).replace("form-action 'none'; ", "", 1)
        errors, _ = self._errs_warns(weak)
        self.assertTrue(any("form-action 'none'" in e for e in errors), errors)

    def test_offline_mode_rejects_network_form_actions(self):
        main = MAIN.replace(
            "<p>content</p>",
            '<form action="https://example.com/post"><button formaction="//example.com/button">Send</button>'
            '<input formaction="https://example.com/input" value="Send"></form>')
        errors, _ = self._errs_warns(with_offline_mode(build(body=self._body(main))))
        for needle in ("<form action", "<button formaction", "<input formaction"):
            self.assertTrue(any("offline mode" in e and needle in e for e in errors),
                            "expected offline form error for %s, got %r" % (needle, errors))

    def test_offline_mode_rejects_network_meta_refresh(self):
        doc = with_offline_mode(build(body=self._body(MAIN, '<meta http-equiv="refresh" content="0; url=https://example.com/out">')))
        errors, _ = self._errs_warns(doc)
        self.assertTrue(any("offline mode" in e and "meta refresh" in e for e in errors), errors)

    def test_offline_mode_rejects_network_css_urls(self):
        css = CSS_REGION.replace(
            ":root { --cp-bg: #ffffff; --cp-text: #000000; }",
            ":root { --cp-bg: #ffffff; --cp-text: #000000; background-image: url(https://example.com/bg.png); }")
        main = MAIN.replace("<p>content</p>", '<p style="background: url(//example.com/inline.png)">content</p>')
        errors, _ = self._errs_warns(with_offline_mode(build(css=css, body=self._body(main))))
        for needle in ("style block", "inline style"):
            self.assertTrue(any("offline mode" in e and "url(" in e and needle in e for e in errors),
                            "expected offline CSS url error for %s, got %r" % (needle, errors))

    def test_offline_mode_allows_non_fetching_network_links(self):
        links = (
            '<link rel="canonical" href="https://example.com/report">\n'
            '<link rel="alternate" href="https://example.com/report.atom" type="application/atom+xml">\n'
            '<link rel="author" href="https://example.com/about">'
        )
        errors, warnings = self._errs_warns(with_offline_mode(build(body=self._body(MAIN, links))))
        self.assertEqual(errors, [], errors)
        self.assertEqual(warnings, [], warnings)

    def test_external_stylesheet_link_warns(self):
        link = '<link rel="stylesheet" href="https://fonts.googleapis.com/css?family=X">'
        errors, warnings = self._errs_warns(build(body=self._body(MAIN, link)))
        self.assertEqual(errors, [], errors)
        self.assertTrue(any("self-contained guarantee" in w for w in warnings), warnings)

    # -- duplicate heading ids --------------------------------------------- #
    def test_duplicate_heading_ids_warn(self):
        main = ('<main id="commentRoot" data-cmh-content-root data-comment-key="k" data-doc-label="l" data-doc-source="s">\n'
                '  <h2 id="dup">A</h2>\n  <p>x</p>\n  <h2 id="dup">B</h2>\n</main>')
        errors, warnings = self._errs_warns(build(body=self._body(main)))
        self.assertEqual(errors, [], errors)
        self.assertTrue(any("duplicate heading id" in w for w in warnings), warnings)

    # -- embeddedComments per-item schema ---------------------------------- #
    def _embedded(self, payload):
        return ("<!--\nBEGIN: commentable-html - EMBEDDED COMMENTS\n-->\n"
                '<script type="application/json" id="embeddedComments">' + payload + "</script>\n"
                "<!-- END: commentable-html - EMBEDDED COMMENTS -->")

    def test_embedded_comment_item_bad_id_errors(self):
        body = [HANDLED_REGION, self._embedded('[{"id": null, "note": "x"}]'), comment_ui(), MAIN, JS_REGION]
        errors, _ = self._errs_warns(build(body=body))
        self.assertTrue(any("missing or unsafe id" in e for e in errors), errors)

    def test_embedded_comment_item_valid_id_is_clean(self):
        body = [HANDLED_REGION, self._embedded('[{"id": "cabc123", "note": "hi"}]'), comment_ui(), MAIN, JS_REGION]
        errors, warnings = self._errs_warns(build(body=body))
        self.assertEqual(errors, [], errors)
        self.assertEqual(warnings, [], warnings)

    # -- canvas aria: report ALL offenders in one pass --------------------- #
    def test_multiple_canvases_missing_aria_reported_together(self):
        main = ('<main id="commentRoot" data-cmh-content-root data-comment-key="k" data-doc-label="l" data-doc-source="s">\n'
                '  <div class="cm-skip"><canvas id="c1"></canvas></div>\n'
                '  <div class="cm-skip"><canvas id="c2"></canvas></div>\n</main>')
        render = '<script>var x = document.getElementById("c1").getContext("2d");</script>'
        errors, warnings = self._errs_warns(build(body=self._body(main, render)))
        self.assertEqual(errors, [], errors)
        self.assertTrue(any("2 of 2 <canvas>" in w for w in warnings), warnings)

    # -- --strict CLI ------------------------------------------------------- #
    def test_strict_flag_fails_on_warnings_only(self):
        main = MAIN.replace("<p>content</p>", '<p>content</p>\n  <img src="images/x.png" alt="x">')
        content = build(body=self._body(main))
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "doc.html")
            with open(p, "w", encoding="utf-8", newline="") as fh:
                fh.write(content)
            r_plain = subprocess.run([sys.executable, VALIDATE_PY, p], capture_output=True, text=True)
            self.assertEqual(r_plain.returncode, 0, r_plain.stdout + r_plain.stderr)
            self.assertIn("WARNING", r_plain.stdout)
            r_strict = subprocess.run([sys.executable, VALIDATE_PY, "--strict", p], capture_output=True, text=True)
            self.assertEqual(r_strict.returncode, 1, r_strict.stdout + r_strict.stderr)
            self.assertIn("strict", r_strict.stdout.lower())


class NonPortableBaseDirTests(unittest.TestCase):
    """CMH-VAL-05: the optional base_dir controls how companion refs are resolved."""

    def _write(self, d, content):
        p = os.path.join(d, "doc.html")
        with open(p, "w", encoding="utf-8", newline="") as fh:
            fh.write(content)
        return p

    def test_base_dir_none_skips_existence_check(self):
        # Companions are MISSING on disk. The default base_dir (the file's dir) flags
        # them; base_dir=None defers the existence check (placement not yet done).
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d, build_nonportable())
            errors_default, _ = validate.validate(p)
            errors_none, _ = validate.validate(p, base_dir=None)
        self.assertTrue(any("not found" in e for e in errors_default),
                        "default base_dir should flag missing companions: %r" % errors_default)
        self.assertFalse(any("not found" in e for e in errors_none),
                         "base_dir=None should skip the existence check: %r" % errors_none)

    def test_base_dir_none_still_runs_structural_checks(self):
        # A remote companion URL is a structural error that must fire even when the
        # existence check is deferred with base_dir=None.
        content = build_nonportable().replace('href="commentable-html.css"',
                                               'href="https://cdn.example.com/commentable-html.css"')
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d, content)
            errors, _ = validate.validate(p, base_dir=None)
        self.assertTrue(any("remote/CDN URL" in e for e in errors),
                        "remote-URL check must run with base_dir=None: %r" % errors)

    def test_explicit_base_dir_resolves_against_that_dir(self):
        # The document lives in dir A (no companions); companions live in dir B.
        # base_dir=B resolves the refs there and validates clean.
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            p = self._write(a, build_nonportable())
            for name in ("commentable-html.css", "commentable-html.js", "commentable-html.assets.js"):
                with open(os.path.join(b, name), "w", encoding="utf-8") as fh:
                    fh.write("/* stub */")
            errors_a, _ = validate.validate(p)
            errors_b, _ = validate.validate(p, base_dir=b)
        self.assertTrue(any("not found" in e for e in errors_a),
                        "refs should be missing when resolved against the file's own dir")
        self.assertFalse(any("not found" in e for e in errors_b),
                         "refs should resolve against the explicit base_dir: %r" % errors_b)


if __name__ == "__main__":
    unittest.main(verbosity=2)
