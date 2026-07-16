from validate_test_support import *  # noqa: F401,F403
import validate_test_support as _support
globals().update({k: v for k, v in vars(_support).items() if k.startswith("_") and not k.startswith("__")})

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

    # -- code-block highlighting guard (CMH-VAL-11) ------------------------- #
    def _doc_with_code(self, code_html):
        main = (
            '<main id="commentRoot" data-cmh-content-root data-comment-key="k" '
            'data-doc-label="l" data-doc-source="s">\n'
            + CONTENT_BEGIN + "\n" + code_html + "\n" + CONTENT_END + "\n</main>"
        )
        return build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION])

    def test_unhighlighted_language_code_block_warns(self):
        # CMH-VAL-11: a <pre><code class="language-XXX"> block for a highlightable language that
        # carries no cmh-code-* spans was never run through highlight_code.py, so it renders as
        # monochrome text - warn so the author highlights it.
        doc = self._doc_with_code(
            '<pre><code class="language-csharp">public sealed class X { int Y { get; } }</code></pre>')
        self.assertWarn(doc, "is not syntax-highlighted")

    def test_unhighlighted_alias_language_code_block_warns(self):
        # The language token is normalized through the highlighter aliases (cs -> csharp).
        doc = self._doc_with_code('<pre><code class="language-cs">var x = 1;</code></pre>')
        self.assertWarn(doc, "is not syntax-highlighted")

    def test_unhighlighted_markup_language_code_block_warns(self):
        # CMH-VAL-11: markup (html/xml) is a highlightable language, so a raw language-html/xml
        # block with no cmh-code-* spans must be flagged - this is exactly the notes-feature-plan.html
        # defect (a language-html block shipped without baked highlighting).
        for lang in ("html", "xml"):
            doc = self._doc_with_code(
                '<pre><code class="language-%s">&lt;div class="x"&gt;hi&lt;/div&gt;</code></pre>' % lang)
            self.assertWarn(doc, "is not syntax-highlighted")

    def test_highlighted_code_block_is_clean(self):
        doc = self._doc_with_code(
            '<pre><code class="language-python">'
            '<span class="cmh-code-kw">def</span> f(): <span class="cmh-code-kw">return</span> 1'
            '</code></pre>')
        self.assertOkNoWarn(doc)

    def test_non_highlightable_language_code_block_is_clean(self):
        # language-text / an unknown label (e.g. console) is not a highlightable language, so a
        # monochrome block is expected, not a defect. (KQL - language-kusto - has its own runnable
        # rule, CMH-KQL-08, so it is not used here as a plain non-highlightable example.)
        for cls in ("language-text", "language-console"):
            doc = self._doc_with_code('<pre><code class="%s">plain content 123</code></pre>' % cls)
            errors, warnings = _validate_text(doc)
            self.assertEqual(errors, [], "expected no errors for %s, got: %r" % (cls, errors))
            self.assertFalse(any("syntax-highlighted" in w for w in warnings),
                             "%s should not be flagged, got: %r" % (cls, warnings))

    def test_code_block_without_language_is_not_flagged(self):
        doc = self._doc_with_code('<pre><code>just some plain code {}</code></pre>')
        self.assertOkNoWarn(doc)

    def test_normal_pre_cmskip_warns_CMH_VAL_12(self):
        doc = self._doc_with_code('<pre class="cm-skip"><code>just some plain code {}</code></pre>')
        self.assertWarn(doc, "will not be commentable")

    def test_normal_pre_code_cmskip_warns_CMH_VAL_12(self):
        doc = self._doc_with_code('<pre><code class="cm-skip">just some plain code {}</code></pre>')
        self.assertWarn(doc, "will not be commentable")

    def test_host_chrome_pre_cmskip_is_not_flagged_CMH_VAL_12(self):
        doc = build(body=[
            HANDLED_REGION,
            EMBEDDED_REGION,
            comment_ui('<pre class="cm-skip">host chrome</pre>\n'),
            MAIN,
            JS_REGION,
        ])
        errors, warnings = _validate_text(doc)
        self.assertEqual(errors, [], "expected no errors, got: %r" % errors)
        self.assertFalse(any("will not be commentable" in w for w in warnings),
                         "host chrome cm-skip should not be flagged: %r" % warnings)

    def test_inline_language_code_is_not_flagged(self):
        # Only block code (<pre><code>) is author-highlighted; an inline <code class="language-...">
        # in prose is never highlighted, so it must not be flagged.
        doc = self._doc_with_code('<p>see <code class="language-csharp">Foo.Bar()</code> inline</p>')
        self.assertOkNoWarn(doc)

    # -- transient body-state class guard (CMH-VAL-10) ---------------------- #
    def test_sidebar_open_body_class_errors(self):
        # CMH-VAL-10: sidebar-open is a transient runtime UI-state class the layer toggles on
        # document.body; a shipped <body> must never bake it in (it renders the doc full width
        # with an empty sidebar gutter via the body.sidebar-open .app rule before the runtime
        # re-derives the state on load). A clean <body> passes; a baked one is a hard error.
        self.assertOkNoWarn(build())
        doc = build().replace("<body>\n", '<body class="sidebar-open">\n', 1)
        self.assertNotEqual(doc, build(), "fixture setup: could not bake sidebar-open into <body>")
        self.assertError(doc, "sidebar-open")

    def test_sidebar_open_only_in_css_or_js_is_clean(self):
        # The guard must inspect only the <body> open tag, not the whole document: the runtime
        # CSS/JS legitimately reference sidebar-open (the .app layout rule, openSidebar()), so a
        # document whose <body> is clean but whose script mentions sidebar-open must still pass.
        doc = build().replace(
            "<body>\n",
            '<body>\n<script>function openSidebar(){document.body.classList.add("sidebar-open");}</script>\n',
            1)
        self.assertNotEqual(doc, build(), "fixture setup: could not add a sidebar-open script reference")
        errors, _ = _validate_text(doc)
        self.assertFalse(any("sidebar-open" in e for e in errors),
                         "the guard false-positived on a non-<body> sidebar-open reference: %r" % errors)

    def test_sidebar_open_decoy_before_real_body_is_clean(self):
        # CMH-VAL-10: the guard must inspect the REAL parsed <body>, not the first raw
        # "<body ...>" token in the file. A fake "<body class=sidebar-open>" literal inside a
        # head <script> BEFORE the clean real <body> must NOT be flagged (no dirty real body).
        decoy = "<script>var t = '<body class=\"sidebar-open\">';</script>\n"
        doc = build().replace("</head>", decoy + "</head>", 1)
        self.assertNotEqual(doc, build(), "fixture setup: could not inject a head-script <body> decoy")
        errors, _ = _validate_text(doc)
        self.assertFalse(any("sidebar-open" in e for e in errors),
                         "the guard false-positived on a decoy <body> before the real body: %r" % errors)

    def test_sidebar_open_real_body_after_decoy_errors(self):
        # CMH-VAL-10: a benign "<body ...>" decoy that appears first must not let a genuinely
        # dirty real <body> slip through. The real body carries sidebar-open, so it must error
        # even though an earlier decoy token has no transient class.
        decoy = "<script>var t = '<body class=\"host-shell\">';</script>\n"
        doc = build().replace("</head>", decoy + "</head>", 1)
        doc = doc.replace("<body>\n", '<body class="sidebar-open">\n', 1)
        self.assertIn('<body class="sidebar-open">', doc, "fixture setup: real body not made dirty")
        self.assertError(doc, "sidebar-open")

    # -- document kind (CMH-KIND) ------------------------------------------- #
    def _report_body(self):
        return [HANDLED_REGION, EMBEDDED_REGION, comment_ui(), MAIN_H1, JS_REGION]

    def test_missing_kind_meta_errors(self):
        # A document with no commentable-html-kind meta must be rejected: the kind is
        # mandatory so per-type rules can apply and the doc is self-describing.
        self.assertError(build(kind=None), "declare the document kind")

    def test_unknown_kind_errors(self):
        self.assertError(build(kind="newsletter"), "unknown document kind")

    def test_report_without_h1_errors(self):
        # report/plan are title-bearing kinds: the exact gap that shipped a title-less deck.
        self.assertError(build(kind="report"), "requires a top-level <h1>")

    def test_plan_without_h1_errors(self):
        self.assertError(build(kind="plan"), "requires a top-level <h1>")

    def test_report_with_h1_is_clean(self):
        self.assertOkNoWarn(build(kind="report", body=self._report_body()))

    def test_report_with_nested_only_h1_errors(self):
        # CMH-KIND-01: a report/plan h1 must be the document's top-level title. An <h1> buried
        # inside a <section> is not a top-level title and must NOT satisfy the rule (new_document
        # requires a top-level title; the old rule accepted any nested h1 anywhere in #commentRoot).
        body = [HANDLED_REGION, EMBEDDED_REGION, comment_ui(), MAIN_NESTED_H1, JS_REGION]
        self.assertError(build(kind="report", body=body), "requires a top-level <h1>")

    def test_report_with_lede_wrapped_h1_is_clean(self):
        # CMH-KIND-01: new_document.ensure_doc_title wraps the h1 in a top-level
        # <header class="cmh-lede">. That lede header is the document's title, so a report
        # whose top-level title is a lede-wrapped h1 must validate clean (matches new_document).
        body = [HANDLED_REGION, EMBEDDED_REGION, comment_ui(), MAIN_LEDE_H1, JS_REGION]
        self.assertOkNoWarn(build(kind="report", body=body))

    def test_report_with_empty_lede_errors(self):
        # CMH-KIND-01 (F5): an EMPTY <header class="cmh-lede"></header> must NOT satisfy the
        # report/plan title rule - the class alone used to pass, letting a title-less report ship.
        body = [HANDLED_REGION, EMBEDDED_REGION, comment_ui(), MAIN_EMPTY_LEDE, JS_REGION]
        self.assertError(build(kind="report", body=body), "requires a top-level <h1>")

    def test_plan_with_h1_is_clean(self):
        self.assertOkNoWarn(build(kind="plan", body=self._report_body()))

    def test_slides_without_h1_is_clean(self):
        # A slide deck legitimately has no document <h1> or table of contents.
        self.assertOkNoWarn(build(kind="slides"))

    def test_board_without_h1_is_clean(self):
        self.assertOkNoWarn(build(kind="board"))

    def test_generic_without_h1_is_clean(self):
        self.assertOkNoWarn(build(kind="generic"))

    def test_kind_is_case_insensitive(self):
        self.assertOkNoWarn(build(kind="Report", body=self._report_body()))


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

    def test_bare_kusto_without_no_cluster_marker_errors(self):
        # CMH-KQL-08: a bare KQL code block that is neither framed in a figure.cmh-kql (with a Run in
        # Azure Data Explorer link) nor explicitly marked data-cmh-kql-no-cluster is a hard error -
        # a KQL block must either run on a cluster or be a deliberate no-cluster snippet. Prefer
        # providing a cluster; the marker is the rare escape hatch.
        block = '<pre><code class="language-kusto">T | take 1</code></pre>'
        main = MAIN.replace("<p>content</p>", "<p>content</p>" + block)
        self.assertError(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]),
                         "not runnable")

    def test_bare_kusto_with_no_cluster_marker_is_clean(self):
        # CMH-KQL-08: the explicit data-cmh-kql-no-cluster override marks a deliberate highlight-only
        # snippet (no known cluster to run it on), so it is validator-clean.
        block = '<pre data-cmh-kql-no-cluster><code class="language-kusto">T | take 1</code></pre>'
        main = MAIN.replace("<p>content</p>", "<p>content</p>" + block)
        self.assertOkNoWarn(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]))

    def test_bare_kusto_inside_kql_figure_is_not_double_flagged(self):
        # CMH-KQL-08: the <pre><code class="language-kusto"> that lives inside a figure.cmh-kql is
        # covered by the figure run-link rule (11d), so it must NOT also be flagged as a bare block.
        fig = ('<figure class="cmh-kql"><figcaption class="cm-skip">'
               '<button class="cmh-kql-title" type="button">cluster</button>'
               '<a class="cmh-kql-run" href="https://dataexplorer.azure.com/x" '
               'target="_blank" rel="noopener noreferrer">Run in Azure Data Explorer</a></figcaption>'
               '<pre><code class="language-kusto">T | take 1</code></pre></figure>')
        main = MAIN.replace("<p>content</p>", "<p>content</p>" + fig)
        self.assertOkNoWarn(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]))

    def test_bare_kusto_mention_in_style_is_not_a_false_positive(self):
        # CMH-KQL-08 must not scan <style>/<script>/comment bodies: a `<pre>` mentioned in a CSS
        # comment must not start a spurious match that swallows a later real KQL block (which broke
        # the report-taxi example the naive scan flagged).
        style = '<style>/* the mark lives inside <pre>/<code> language-kusto */ .x{color:red}</style>'
        fig = ('<figure class="cmh-kql"><figcaption class="cm-skip">'
               '<button class="cmh-kql-title" type="button">cluster</button>'
               '<a class="cmh-kql-run" href="https://dataexplorer.azure.com/x" '
               'target="_blank" rel="noopener noreferrer">Run in Azure Data Explorer</a></figcaption>'
               '<pre><code class="language-kusto">T | take 1</code></pre></figure>')
        main = MAIN.replace("<p>content</p>", "<p>content</p>" + style + fig)
        self.assertOkNoWarn(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]))

    def test_kql_figure_without_run_link_errors(self):
        # A framed KQL figure MUST carry a Run in Azure Data Explorer link; a missing one
        # is a hard validation ERROR (not a warning) so the reader can always open the query.
        fig = ('<figure class="cmh-kql"><figcaption class="cm-skip">'
               '<button class="cmh-kql-title" type="button">cluster</button></figcaption>'
               '<pre><code class="language-kusto">T | take 1</code></pre></figure>')
        main = MAIN.replace("<p>content</p>", "<p>content</p>" + fig)
        self.assertError(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]),
                         'figure.cmh-kql has no "Run in Azure Data Explorer" link')

    def test_kql_figure_with_run_link_is_clean(self):
        fig = ('<figure class="cmh-kql"><figcaption class="cm-skip">'
               '<button class="cmh-kql-title" type="button">cluster</button>'
               '<a class="cmh-kql-run" href="https://dataexplorer.azure.com/x" '
               'target="_blank" rel="noopener noreferrer">Run in Azure Data Explorer</a></figcaption>'
               '<pre><code class="language-kusto">T | take 1</code></pre></figure>')
        main = MAIN.replace("<p>content</p>", "<p>content</p>" + fig)
        self.assertOkNoWarn(build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION]))

    def _kql_figure(self, run_link_html):
        return ('<figure class="cmh-kql"><figcaption class="cm-skip">'
                '<button class="cmh-kql-title" type="button">cluster</button>'
                + run_link_html +
                '</figcaption><pre><code class="language-kusto">T | take 1</code></pre></figure>')

    def _kql_doc(self, fig):
        main = MAIN.replace("<p>content</p>", "<p>content</p>" + fig)
        return build(body=[HANDLED_REGION, EMBEDDED_REGION, comment_ui(), main, JS_REGION])

    def test_kql_figure_javascript_run_link_errors(self):
        # CMH-KQL-07 hardening: a PRESENT cmh-kql-run link with a non-https / non-ADX href on a
        # framed figure is a hard ERROR, not a warning - a javascript: URL must never pass.
        fig = self._kql_figure('<a class="cmh-kql-run" href="javascript:alert(1)">Run</a>')
        self.assertError(self._kql_doc(fig), "https://dataexplorer.azure.com/")

    def test_kql_figure_data_run_link_errors(self):
        fig = self._kql_figure('<a class="cmh-kql-run" href="data:text/html,x">Run</a>')
        self.assertError(self._kql_doc(fig), "https://dataexplorer.azure.com/")

    def test_kql_figure_http_non_adx_run_link_errors(self):
        fig = self._kql_figure('<a class="cmh-kql-run" href="http://dataexplorer.azure.com/x">Run</a>')
        self.assertError(self._kql_doc(fig), "https://dataexplorer.azure.com/")

    def test_kql_figure_lookalike_host_run_link_errors(self):
        # A look-alike host must not pass a substring test: parse the URL and require the host be
        # exactly dataexplorer.azure.com.
        fig = self._kql_figure('<a class="cmh-kql-run" href="https://dataexplorer.azure.com.evil.example/x">Run</a>')
        self.assertError(self._kql_doc(fig), "https://dataexplorer.azure.com/")

    def test_kql_figure_entity_encoded_javascript_run_link_errors(self):
        # The href is HTML-entity-decoded before parsing, so an encoded javascript: scheme is caught.
        fig = self._kql_figure('<a class="cmh-kql-run" href="&#106;avascript:alert(1)">Run</a>')
        self.assertError(self._kql_doc(fig), "https://dataexplorer.azure.com/")

    def test_kql_figure_run_link_only_in_query_text_errors_missing(self):
        # CMH-KQL-07: the run link must be a real <a class="cmh-kql-run"> element, not a raw
        # substring. A figure whose QUERY TEXT merely mentions "cmh-kql-run" (with no real link)
        # must be reported as MISSING the run link.
        fig = ('<figure class="cmh-kql"><figcaption class="cm-skip">'
               '<button class="cmh-kql-title" type="button">cluster</button></figcaption>'
               '<pre><code class="language-kusto">T | where note == "cmh-kql-run"</code></pre></figure>')
        self.assertError(self._kql_doc(fig), 'figure.cmh-kql has no "Run in Azure Data Explorer" link')

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
