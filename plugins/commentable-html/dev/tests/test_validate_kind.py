from _validate_helpers import *


class ValidateBodyAndKindTests(ValidateAssertions, unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
