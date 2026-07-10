#!/usr/bin/env python3
"""Regression tests for the Chart.js embedding checks in validate.py.

Standard library only (unittest), matching validate.py. Run from the skill
root:

    python tests/test_validate_charts.py   # or: python -m unittest discover -s tests -v

Each test builds a MINIMAL valid chart document in-memory and mutates one thing
to assert a specific error or warning. The base fixture must pass with zero
errors and zero warnings. The real dist/PORTABLE.html (no <canvas>) and the field
artifact mde-mad-growth.html (if present) are positive controls. A few tests
drive the CLI as a subprocess to cover exit codes and batch behaviour.

Coverage is mutation-checked: for each ERROR and WARNING branch (and each arm of
the OR conditions) there is a test that fails if the branch were narrowed or
removed. Several tests exercise the parsing robustness the multi-model review
required (unclosed <p>, canvas fallback content, unquoted attrs, prose text).
"""

import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402  shared pkg/dev split path constants
ROOT = _paths.PKG
TOOLS = _paths.TOOLS
sys.path.insert(0, TOOLS)
import validate  # noqa: E402

TEMPLATE = os.path.join(ROOT, "dist", "PORTABLE.html")
SCRIPT = os.path.join(TOOLS, "validate.py")
_FIELD_CANDIDATES = [
    os.path.join(os.path.expanduser("~"), "Downloads", "mde-mad-growth.html"),
    os.path.join(os.path.expanduser("~"), "OneDrive - Microsoft", "COGS", "Forecasting", "mde-mad-growth.html"),
]
FIELD_ARTIFACT = next((p for p in _FIELD_CANDIDATES if os.path.exists(p)), _FIELD_CANDIDATES[0])

CDN_VALID = (
    '<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js" '
    'integrity="sha384-e6nUZLBkQ86NJ6TVVKAeSaK8jWa3NhkYWZFomE39AvDbQWeie9PlQqM3pmYW5d1g" '
    'crossorigin="anonymous"></script>'
)
FIGURE_VALID = (
    '<figure class="chart">\n'
    '  <div class="chart-wrap cm-skip"><canvas id="c" role="img" aria-label="MAD chart"></canvas></div>\n'
    "  <figcaption>Hover for exact values.</figcaption>\n"
    "</figure>"
)
INIT_VALID = (
    "<script>(function(){ if (typeof Chart === \"undefined\") return; "
    'new Chart(document.getElementById("c"), {type:"line"}); })();</script>'
)
MARKER = "<!-- END: commentable-html v2 - JS -->"


def build(cdn=CDN_VALID, figure=FIGURE_VALID, json_body='{"labels":[1,2]}',
          init=INIT_VALID, marker=True, layer=True, pre_marker=""):
    js_end = MARKER + "\n" if marker else ""
    root_open = ('<main id="commentRoot" data-comment-key="k" data-doc-label="l">'
                 if layer else "<main>")
    return (
        "<!doctype html><html><head>\n" + cdn + "\n</head><body>\n"
        + root_open + "\n" + figure + "\n</main>\n"
        + pre_marker + js_end
        + '<script id="mad" type="application/json">' + json_body + "</script>\n"
        + init + "\n</body></html>"
    )


def run(html):
    fd, path = tempfile.mkstemp(suffix=".html")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(html)
        return validate.validate_charts(path)
    finally:
        os.remove(path)


class ChartValidatorTests(unittest.TestCase):

    # -- positive controls --------------------------------------------------- #

    def test_valid_fixture_passes(self):
        e, w, n = run(build())
        self.assertEqual(e, [], f"unexpected errors: {e}")
        self.assertEqual(w, [], f"unexpected warnings: {w}")
        self.assertEqual(n, 1)

    def test_template_has_valid_demo_chart(self):
        # The template ships a commentable demo chart: one <canvas> rendered by an
        # inline 2D-context draw (no Chart.js library), which must validate clean.
        e, w, n = validate.validate_charts(TEMPLATE)
        self.assertEqual(n, 1, "template should ship exactly one demo canvas")
        self.assertEqual(e, [], f"template demo chart should validate clean: {e}")

    def test_no_canvas_document(self):
        e, w, n = run("<html><body><p>no charts here</p></body></html>")
        self.assertEqual(n, 0)
        self.assertEqual(e, [])

    @unittest.skipUnless(os.path.exists(FIELD_ARTIFACT), "field artifact not present")
    def test_field_artifact_clean(self):
        e, w, n = validate.validate_charts(FIELD_ARTIFACT)
        self.assertEqual(e, [], f"field artifact should validate clean: {e}")
        self.assertGreaterEqual(n, 1)

    # -- E1 / E2 cm-skip ----------------------------------------------------- #

    def test_canvas_not_in_cm_skip(self):
        figure = FIGURE_VALID.replace('class="chart-wrap cm-skip"', 'class="chart-wrap"')
        e, _w, _n = run(build(figure=figure))
        self.assertEqual(sum(1 for x in e if "not inside a cm-skip" in x), 1, e)

    def test_figcaption_inside_cm_skip(self):
        figure = (
            '<figure class="chart cm-skip">\n'
            '  <div class="chart-wrap"><canvas id="c" role="img" aria-label="x"></canvas></div>\n'
            "  <figcaption>cap</figcaption>\n</figure>"
        )
        e, _w, _n = run(build(figure=figure))
        self.assertEqual(sum(1 for x in e if "figcaption" in x and "cm-skip" in x), 1, e)

    def test_e2_gated_by_layer(self):
        # A plain (non-layer) page with a cm-skip figcaption must NOT trip E2.
        figure = ('<figure class="cm-skip"><div><canvas id="c" role="img" aria-label="x"></canvas></div>'
                  "<figcaption>cap</figcaption></figure>")
        e, _w, _n = run(build(figure=figure, marker=False, layer=False))
        self.assertEqual([x for x in e if "figcaption" in x], [], e)

    def test_e1_from_marker_only_layer(self):
        # No commentRoot, but a real marker comment => has_layer, so E1 still fires.
        figure = '<figure class="chart"><div class="chart-wrap"><canvas id="c" role="img" aria-label="x"></canvas></div></figure>'
        e, _w, _n = run(build(figure=figure, layer=False))  # marker True, layer False
        self.assertTrue(any("not inside a cm-skip" in x for x in e), e)

    def test_canvas_fallback_figcaption_exempt(self):
        figure = ('<figure class="chart"><div class="chart-wrap cm-skip">'
                  '<canvas id="c" role="img" aria-label="x"><figcaption>fallback</figcaption></canvas>'
                  "</div></figure>")
        e, _w, _n = run(build(figure=figure))
        self.assertEqual([x for x in e if "figcaption" in x], [], e)

    def test_unclosed_p_does_not_poison_stack(self):
        # An unclosed cm-skip <p> must not leak cm-skip onto a later figcaption.
        figure = ('<p class="cm-skip">note'
                  '<div class="chart-wrap cm-skip"><canvas id="c" role="img" aria-label="x"></canvas></div>'
                  "<figcaption>cap</figcaption>")
        e, _w, _n = run(build(figure=figure))
        self.assertEqual([x for x in e if "figcaption" in x], [], e)

    def test_self_closing_non_void_tag_does_not_desync(self):
        # A trailing slash on a NON-void tag (<div/>) is ignored by browsers (treated as
        # an open tag). The parser must delegate so the element stack stays in sync; a
        # desync would mis-scope the later chart figcaption (regression for duck finding).
        figure = ('<div/><figure class="chart"><div class="chart-wrap cm-skip">'
                  '<canvas id="c" role="img" aria-label="x"></canvas></div>'
                  '<figcaption>ok caption</figcaption></figure>')
        draw = '<script>document.getElementById("c").getContext("2d");</script>'
        e, _w, _n = run(build(cdn="", figure=figure, json_body="[]", init=draw))
        self.assertEqual([x for x in e if "figcaption" in x], [], e)

    def test_nested_chart_figures_balance(self):
        # Nested chart figures must push/pop the figure-chart stack cleanly so the outer
        # (non-cm-skip) figcaption is not falsely flagged.
        figure = ('<figure class="chart"><figure class="chart"><div class="chart-wrap cm-skip">'
                  '<canvas id="c" role="img" aria-label="x"></canvas></div></figure>'
                  '<figcaption>outer caption</figcaption></figure>')
        draw = '<script>document.getElementById("c").getContext("2d");</script>'
        e, _w, _n = run(build(cdn="", figure=figure, json_body="[]", init=draw))
        self.assertEqual([x for x in e if "figcaption" in x], [], e)

    # -- E3 loader ----------------------------------------------------------- #

    def test_missing_chartjs_loader(self):
        e, _w, _n = run(build(cdn=""))
        self.assertTrue(any("no Chart.js" in x for x in e), e)

    def test_flowchart_is_not_a_loader(self):
        e, _w, _n = run(build(cdn='<script src="https://cdn/flowchart.min.js"></script>'))
        self.assertTrue(any("no Chart.js" in x for x in e), e)

    def test_unquoted_src_is_accepted(self):
        cdn = ("<script src=https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js "
               "integrity=sha384-x crossorigin=anonymous></script>")
        e, _w, _n = run(build(cdn=cdn))
        self.assertEqual([x for x in e if "no Chart.js" in x], [], e)

    def test_inline_getcontext_render_is_a_valid_renderer(self):
        # A canvas drawn by an inline 2D-context script (no Chart.js) renders and
        # must not trip E3.
        figure = ('<figure class="chart"><div class="chart-wrap cm-skip">'
                  '<canvas id="c" role="img" aria-label="x"></canvas></div></figure>')
        draw = '<script>var cx=document.getElementById("c").getContext("2d");cx.fillRect(0,0,9,9);</script>'
        e, _w, _n = run(build(cdn="", figure=figure, json_body="[]", init=draw))
        self.assertEqual([x for x in e if "will not render" in x], [], e)

    def test_canvas_with_no_renderer_errors(self):
        # A canvas with neither a Chart.js loader nor an inline draw cannot render.
        figure = ('<figure class="chart"><div class="chart-wrap cm-skip">'
                  '<canvas id="c" role="img" aria-label="x"></canvas></div></figure>')
        e, _w, _n = run(build(cdn="", figure=figure, json_body="[]", init=""))
        self.assertTrue(any("will not render" in x for x in e), e)

    def test_new_chart_without_loader_still_errors(self):
        # A bare `new Chart(` does not count as a renderer: Chart is undefined
        # without the loader, so E3 must still fire.
        figure = ('<figure class="chart"><div class="chart-wrap cm-skip">'
                  '<canvas id="c" role="img" aria-label="x"></canvas></div></figure>')
        init = '<script>new Chart(document.getElementById("c"),{});</script>'
        e, _w, _n = run(build(cdn="", figure=figure, json_body="[]", init=init))
        self.assertTrue(any("will not render" in x for x in e), e)

    def test_e2_ignores_non_chart_cm_skip_caption(self):
        # A cm-skip <figcaption> that is NOT inside a chart figure (e.g. the KQL
        # caption chrome) must not be flagged even when the doc also has a canvas.
        figure = (
            '<figure class="chart"><div class="chart-wrap cm-skip">'
            '<canvas id="c" role="img" aria-label="x"></canvas></div>'
            "<figcaption>ok caption</figcaption></figure>\n"
            '<figure class="cmh-kql"><figcaption class="cm-skip">cluster / db</figcaption></figure>'
        )
        draw = '<script>document.getElementById("c").getContext("2d");</script>'
        e, _w, _n = run(build(cdn="", figure=figure, json_body="[]", init=draw))
        self.assertEqual([x for x in e if "figcaption" in x], [], e)

    # -- E4 chart JSON ------------------------------------------------------- #

    def test_e4_script_breakout_caught(self):
        e, _w, _n = run(build(json_body='{"t":"</script>"}'))
        self.assertTrue(any('id="mad"' in x for x in e), e)

    def test_e4_benign_lt_is_allowed(self):
        e, _w, _n = run(build(json_body='{"math":"x < y"}'))
        self.assertEqual(e, [], e)

    def test_e4_escaped_slash_is_allowed(self):
        e, _w, _n = run(build(json_body='{"t":"a<\\/b"}'))
        self.assertEqual(e, [], e)

    def test_e4_html_comment_caught(self):
        e, _w, _n = run(build(json_body='{"t":"<!-- x -->"}'))
        self.assertTrue(any('id="mad"' in x for x in e), e)

    def test_e4_layer_json_ids_exempt(self):
        for lid in ("embeddedComments", "handledCommentIds"):
            html = build().replace(
                '<script id="mad" type="application/json">{"labels":[1,2]}</script>',
                '<script id="mad" type="application/json">{"labels":[1,2]}</script>\n'
                f'<script id="{lid}" type="application/json">[{{"q":"<!-- x -->"}}]</script>',
            )
            e, _w, _n = run(html)
            # The `<!--` payload WOULD trip E4 if the block were not exempt, so this
            # pins the LAYER_JSON_IDS `continue` (not just a trivially-valid payload).
            self.assertEqual([x for x in e if lid in x], [], f"{lid}: {e}")

    # -- E5 init placement --------------------------------------------------- #

    def test_init_before_js_end_marker(self):
        e, _w, _n = run(build(pre_marker="<script>new Chart(x,{});</script>\n"))
        self.assertTrue(any("before the" in x and "JS`" in x for x in e), e)

    def test_e5_skipped_without_marker(self):
        e, _w, _n = run(build(marker=False, pre_marker="<script>new Chart(x,{});</script>\n"))
        self.assertEqual([x for x in e if "before the" in x], [], e)

    def test_e5_new_chart_in_prose_not_flagged(self):
        # `new Chart(` in a <pre> before the marker is not executable init.
        e, _w, _n = run(build(pre_marker="<pre>new Chart(ctx, config)</pre>\n"))
        self.assertEqual([x for x in e if "before the" in x], [], e)

    def test_e5_marker_text_in_prose_not_a_marker(self):
        # A bare "END: ... JS" in prose must NOT be treated as the marker. An
        # executable init is placed AFTER the prose text but BEFORE the real marker
        # comment, so E5 must FIRE (the real comment is the marker). If a regressed
        # regex mistook the prose text for the marker, the init would count as
        # "after" it and E5 would wrongly stay silent - this asserts it does not.
        html = build(pre_marker="<p>END: commentable-html v2 - JS</p>\n"
                                "<script>new Chart(x,{});</script>\n")
        e, _w, _n = run(html)
        self.assertTrue(any("before the" in x for x in e), e)

    # -- warnings ------------------------------------------------------------ #

    def test_w1_missing_integrity_only(self):
        cdn = ('<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js" '
               'crossorigin="anonymous"></script>')
        _e, w, _n = run(build(cdn=cdn))
        self.assertTrue(any("Integrity" in x for x in w), w)

    def test_w1_empty_integrity(self):
        cdn = ('<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js" '
               'integrity="" crossorigin="anonymous"></script>')
        _e, w, _n = run(build(cdn=cdn))
        self.assertTrue(any("Integrity" in x for x in w), w)

    def test_w1_missing_crossorigin_only(self):
        cdn = ('<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js" '
               'integrity="sha384-x"></script>')
        _e, w, _n = run(build(cdn=cdn))
        self.assertTrue(any("Integrity" in x for x in w), w)

    def test_w2_defer_async_module(self):
        for attr in ('defer', 'async', 'type = "module"'):
            cdn = ('<script ' + attr + ' src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js" '
                   'integrity="sha384-x" crossorigin="anonymous"></script>')
            _e, w, _n = run(build(cdn=cdn))
            self.assertTrue(any("deferred/async/module" in x for x in w), f"{attr}: {w}")

    def test_w3_unpinned_and_partial(self):
        for ver in ("latest", "4", "4.4"):
            cdn = (f'<script src="https://cdn.jsdelivr.net/npm/chart.js@{ver}/dist/chart.umd.min.js" '
                   'integrity="sha384-x" crossorigin="anonymous"></script>')
            _e, w, _n = run(build(cdn=cdn))
            self.assertTrue(any("full version" in x for x in w), f"@{ver}: {w}")

    def test_w4_missing_role_only(self):
        figure = FIGURE_VALID.replace(' role="img"', "")
        _e, w, _n = run(build(figure=figure))
        self.assertTrue(any("aria-label" in x for x in w), w)

    def test_w4_empty_aria_only(self):
        figure = FIGURE_VALID.replace('aria-label="MAD chart"', 'aria-label="  "')
        _e, w, _n = run(build(figure=figure))
        self.assertTrue(any("aria-label" in x for x in w), w)

    def test_w5_missing_guard(self):
        init = '<script>new Chart(document.getElementById("c"), {type:"line"});</script>'
        _e, w, _n = run(build(init=init))
        self.assertTrue(any("typeof Chart" in x for x in w), w)

    def test_w5_fake_guard_string(self):
        init = '<script>var s="typeof Chart"; new Chart(document.getElementById("c"),{});</script>'
        _e, w, _n = run(build(init=init))
        self.assertTrue(any("typeof Chart" in x for x in w), w)

    # -- misc / CLI ---------------------------------------------------------- #

    def test_cannot_read_missing_file(self):
        e, w, n = validate.validate_charts(os.path.join(HERE, "no-such-file.html"))
        self.assertTrue(any("cannot read file" in x for x in e), e)

    def _cli(self, *args):
        return subprocess.run([sys.executable, SCRIPT, "--charts-only", *args], capture_output=True, text=True)

    def _write(self, html):
        fd, path = tempfile.mkstemp(suffix=".html")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(html)
        return path

    def test_cli_ok_exit_zero(self):
        path = self._write(build())
        try:
            r = self._cli(path)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("OK", r.stdout)
        finally:
            os.remove(path)

    def test_cli_warnings_only_exit_zero(self):
        cdn = '<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>'
        path = self._write(build(cdn=cdn))  # missing SRI -> warning, no error
        try:
            r = self._cli(path)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("WARNING", r.stdout)
        finally:
            os.remove(path)

    def test_cli_error_exit_one(self):
        path = self._write(build(cdn=""))  # missing loader -> error
        try:
            r = self._cli(path)
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertIn("ERROR", r.stdout)
        finally:
            os.remove(path)

    def test_cli_batch_mixed_exits_one(self):
        ok = self._write(build())
        bad = self._write(build(cdn=""))
        try:
            r = self._cli(ok, bad)
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertIn("OK", r.stdout)
            self.assertIn("ERROR", r.stdout)
        finally:
            os.remove(ok)
            os.remove(bad)

    def test_cli_usage_exit_two(self):
        r = self._cli()
        self.assertEqual(r.returncode, 2)

    # -- multi-model review follow-ups --------------------------------------- #

    def test_e4_invalid_json_caught(self):
        # Malformed-but-safe JSON (no </script>/<!-- breakout) must still be flagged
        # by the json.loads branch of E4.
        e, _w, _n = run(build(json_body='{"a": }'))
        self.assertTrue(any('id="mad"' in x and "not valid JSON" in x for x in e), e)

    def test_li_implicit_close_does_not_poison_stack(self):
        # An unclosed cm-skip <li> must not leak cm-skip onto a canvas in a later <li>.
        figure = ('<ul><li class="cm-skip">note'
                  '<li><div class="chart-wrap"><canvas id="c" role="img" aria-label="x"></canvas></div></ul>')
        e, _w, _n = run(build(figure=figure))
        self.assertTrue(any("not inside a cm-skip" in x for x in e), e)

    def test_has_layer_commentroot_only(self):
        # commentRoot present but no marker comment => has_layer via commentRoot alone,
        # so an unskipped canvas still trips E1 (pins the commentRoot arm of the OR).
        figure = '<figure class="chart"><div class="chart-wrap"><canvas id="c" role="img" aria-label="x"></canvas></div></figure>'
        e, _w, _n = run(build(figure=figure, marker=False, layer=True))
        self.assertTrue(any("not inside a cm-skip" in x for x in e), e)

    def test_data_prefixed_attr_not_read_as_real_attr(self):
        # data-integrity must NOT satisfy the real integrity check (attribute-boundary
        # match); with no real integrity the SRI warning must still fire.
        cdn = ('<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js" '
               'data-integrity="x" crossorigin="anonymous"></script>')
        _e, w, _n = run(build(cdn=cdn))
        self.assertTrue(any("Integrity" in x for x in w), w)

    def test_loader_bare_pinned_semver_accepted(self):
        # jsdelivr auto-resolve form (.../npm/chart.js@X.Y.Z, no /dist/... file) is a loader.
        cdn = ('<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0" '
               'integrity="sha384-x" crossorigin="anonymous"></script>')
        e, _w, _n = run(build(cdn=cdn))
        self.assertEqual([x for x in e if "no Chart.js" in x], [], e)

    def test_guard_negated_form_accepted(self):
        # `if (typeof Chart !== "undefined")` is a real guard; W5 must NOT fire.
        init = ('<script>if (typeof Chart !== "undefined") '
                'new Chart(document.getElementById("c"), {type:"line"});</script>')
        _e, w, _n = run(build(init=init))
        self.assertEqual([x for x in w if "typeof Chart" in x], [], w)

    def test_json_type_with_charset_still_checked(self):
        # type="application/json; charset=utf-8" is still a chart-data block, so its
        # breakout is caught (unquoted / parameterised type detection).
        html = build().replace(
            '<script id="mad" type="application/json">{"labels":[1,2]}</script>',
            '<script id="mad" type="application/json; charset=utf-8">{"t":"</script>"}</script>',
        )
        e, _w, _n = run(html)
        self.assertTrue(any('id="mad"' in x for x in e), e)

    def test_commented_out_loader_not_counted(self):
        # A Chart.js loader that is commented out must not satisfy E3.
        cdn = '<!-- <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script> -->'
        e, _w, _n = run(build(cdn=cdn))
        self.assertTrue(any("no Chart.js" in x for x in e), e)

    def test_init_before_loader_flagged(self):
        # If the Chart.js loader is placed AFTER the init, Chart is undefined when
        # init runs -> E5 loader-ordering must fire.
        html = build(cdn="", init="").replace(
            "</body></html>",
            '<script>new Chart(document.getElementById("c"),{});</script>\n' + CDN_VALID + "\n</body></html>")
        e, _w, _n = run(html)
        self.assertTrue(any("before the Chart.js" in x for x in e), e)

    def test_json_typed_src_is_not_a_loader(self):
        # A chart.js src on a non-executable (application/json) script does not load
        # Chart, so E3 must still fire.
        cdn = ('<script type="application/json" src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js">'
               '</script>')
        e, _w, _n = run(build(cdn=cdn))
        self.assertTrue(any("no Chart.js" in x for x in e), e)

    def test_empty_chart_json_is_invalid(self):
        # An empty chart-data JSON block throws in JSON.parse at init.
        e, _w, _n = run(build(json_body="   "))
        self.assertTrue(any('id="mad"' in x and "empty" in x for x in e), e)

    def test_new_chart_in_comment_not_flagged(self):
        # `new Chart(` inside a JS comment before the marker is not executable init.
        e, _w, _n = run(build(pre_marker="<script>// call new Chart(x) after load\n</script>\n"))
        self.assertEqual([x for x in e if "before the" in x], [], e)

    def test_new_chart_in_string_not_flagged(self):
        # `new Chart(` inside a JS string literal before the marker is not init.
        e, _w, _n = run(build(pre_marker="<script>var doc=\"call new Chart(x)\";\n</script>\n"))
        self.assertEqual([x for x in e if "before the" in x], [], e)

    def test_gt_in_quoted_attr_json_block_ok(self):
        # A `>` inside a quoted attribute must not mis-slice the JSON <script> tag.
        html = build().replace(
            '<script id="mad" type="application/json">{"labels":[1,2]}</script>',
            '<script id="mad" type="application/json" data-note="a>b">{"labels":[1,2]}</script>')
        e, _w, _n = run(html)
        self.assertEqual(e, [], e)

    def test_e1_gate_without_layer(self):
        # A non-layer page (no commentRoot, no marker) with an unskipped canvas must
        # NOT trip E1 (pins the has_layer gate on E1, not just E2).
        figure = '<figure><div class="chart-wrap"><canvas id="c" role="img" aria-label="x"></canvas></div></figure>'
        e, _w, _n = run(build(figure=figure, marker=False, layer=False))
        self.assertEqual([x for x in e if "not inside a cm-skip" in x], [], e)

    def test_malformed_markup_reported(self):
        # If HTMLParser raises, validate_charts reports a parse error (with canvas count).
        import validate as _v
        orig = _v._DocParser.feed
        try:
            _v._DocParser.feed = lambda self, data: (_ for _ in ()).throw(RuntimeError("boom"))
            e, _w, n = run(build())
            self.assertTrue(any("could not be parsed" in x for x in e), e)
            self.assertGreaterEqual(n, 1)
        finally:
            _v._DocParser.feed = orig

    def test_crlf_offsets_e5_still_fires(self):
        # _DocParser offset math must survive CRLF: an init before the marker still
        # trips E5 when the document uses \r\n line endings.
        html = build(pre_marker="<script>new Chart(x,{});</script>\n").replace("\n", "\r\n")
        fd, path = tempfile.mkstemp(suffix=".html")
        try:
            with open(fd, "w", encoding="utf-8", newline="") as fh:
                fh.write(html)
            e, _w, _n = validate.validate_charts(path)
            self.assertTrue(any("before the" in x for x in e), e)
        finally:
            os.remove(path)

    def test_cli_layer_only_skips_charts(self):
        # `--layer-only` on a chart-broken (missing loader) but layer-less doc: the
        # chart check is suppressed, so no "no Chart.js" error appears.
        path = self._write(build(cdn=""))
        try:
            r = subprocess.run([sys.executable, SCRIPT, "--layer-only", path], capture_output=True, text=True)
            self.assertNotIn("no Chart.js", r.stdout, r.stdout)
        finally:
            os.remove(path)

    def test_line_comment_marker_in_string_does_not_hide_init(self):
        # A `//` inside a JS STRING before the marker must not blank a real
        # `new Chart(` on the same line (single-pass lexer, not a naive regex).
        e, _w, _n = run(build(pre_marker='<script>var u="https://x"; new Chart(z,{});</script>\n'))
        self.assertTrue(any("before the" in x for x in e), e)

    def test_block_comment_marker_in_string_does_not_erase_code(self):
        # A `/*` inside a JS STRING before the marker must not erase the rest of the
        # script (which would drop a real `new Chart(`).
        e, _w, _n = run(build(pre_marker='<script>var u="/*"; new Chart(z,{});</script>\n'))
        self.assertTrue(any("before the" in x for x in e), e)

    def test_babel_typed_src_is_not_a_loader(self):
        # text/babel needs a transpiler runtime the browser does not run natively.
        cdn = ('<script type="text/babel" src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js">'
               '</script>')
        e, _w, _n = run(build(cdn=cdn))
        self.assertTrue(any("no Chart.js" in x for x in e), e)

    def test_new_chart_in_json_script_not_init(self):
        # `new Chart(` text inside a chart-data JSON block is not executable init;
        # it must not trip E5 (pins the _is_executable_js gate on the init scan).
        html = build(pre_marker='<script id="j" type="application/json">{"d":"new Chart(x)"}</script>\n')
        e, _w, _n = run(html)
        self.assertEqual([x for x in e if "before the" in x], [], e)

    def test_canvas_with_loader_but_no_init_warns(self):
        # A loaded canvas with no executable init renders blank -> W6.
        html = build(init="")
        _e, w, _n = run(html)
        self.assertTrue(any("render blank" in x for x in w), w)

    def test_marker_text_in_prose_comment_ignored(self):
        # A comment that merely MENTIONS the marker text (not an exact marker) must
        # not be treated as the JS END marker; the real marker still gates E5.
        html = build(pre_marker="<!-- note: END: commentable-html v2 - JS is the marker name -->\n"
                                "<script>new Chart(z,{});</script>\n")
        e, _w, _n = run(html)
        self.assertTrue(any("before the" in x for x in e), e)

    def test_e4_no_id_chart_json_message(self):
        # An id-less chart-data JSON block that is invalid reports "(no id)".
        html = build().replace(
            '<script id="mad" type="application/json">{"labels":[1,2]}</script>',
            '<script type="application/json">{bad</script>')
        e, _w, _n = run(html)
        self.assertTrue(any("(no id)" in x for x in e), e)

    def test_global_qualified_init_counts(self):
        # `new window.Chart(` is executable init, so no W6 and E5 ordering applies.
        e, _w, _n = run(build(pre_marker="<script>new window.Chart(z,{});</script>\n"))
        self.assertTrue(any("before the" in x for x in e), e)

    def test_typeof_parenthesised_guard_accepted(self):
        # `typeof(Chart) === "undefined"` is a real guard; W5 must NOT fire.
        init = ('<script>if (typeof(Chart) === "undefined") return; '
                'new Chart(document.getElementById("c"), {});</script>')
        _e, w, _n = run(build(init=init))
        self.assertEqual([x for x in w if "typeof Chart" in x], [], w)

    def test_script_src_body_is_dead_code(self):
        # A <script src=...> ignores its inline body in the browser; a `new Chart(`
        # placed there is not real init, so W6 (no init) fires.
        cdn = ('<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js" '
               'integrity="sha384-x" crossorigin="anonymous">new Chart(document.getElementById("c"),{})</script>')
        html = build(cdn=cdn, init="")
        _e, w, _n = run(html)
        self.assertTrue(any("render blank" in x for x in w), w)

    def test_real_block_comment_hides_init(self):
        # `new Chart(` inside a genuine /* ... */ block comment before the marker is
        # not executable init (pins the _js_scan block-comment branch).
        e, _w, _n = run(build(pre_marker="<script>/* TODO new Chart(z) once data is ready */</script>\n"))
        self.assertEqual([x for x in e if "before the" in x], [], e)

    def test_escaped_quote_string_not_init(self):
        # A string containing an escaped quote and `new Chart(`-looking text is pure
        # data (pins the _js_scan string-escape branch).
        e, _w, _n = run(build(pre_marker='<script>var m="call \\"new Chart(z)\\" later";</script>\n'))
        self.assertEqual([x for x in e if "before the" in x], [], e)

    def test_globalthis_and_self_init_count(self):
        # `new globalThis.Chart(` and `new self.Chart(` are executable init too
        # (pins those arms of NEW_CHART_RE); E5 fires when placed before the marker.
        for form in ("globalThis", "self"):
            e, _w, _n = run(build(pre_marker=f"<script>new {form}.Chart(z,{{}});</script>\n"))
            self.assertTrue(any("before the" in x for x in e), f"{form}: {e}")

    def test_p_closed_through_inline_exposes_canvas(self):
        # A canvas whose only cm-skip ancestor is a <p> with an intervening inline
        # element: a browser closes the <p> at the <div>, exposing the canvas, so E1
        # must fire (pins the scope-aware _implicit_close).
        figure = ('<figure><p class="cm-skip"><span><div class="chart-wrap">'
                  '<canvas id="c" role="img" aria-label="x"></canvas></div></span></p></figure>')
        e, _w, _n = run(build(figure=figure))
        self.assertTrue(any("not inside a cm-skip" in x for x in e), e)

    def test_template_marker_is_ignored(self):
        # A JS END marker comment inside an inert <template> must not become the E5
        # boundary; the real marker after it still gates an earlier init.
        html = build(pre_marker="<template><!-- END: commentable-html v2 - JS --></template>\n"
                                "<script>new Chart(z,{});</script>\n")
        e, _w, _n = run(html)
        self.assertTrue(any("before the" in x for x in e), e)

    def test_template_script_is_inert(self):
        # A Chart.js loader / init inside a <template> is inert; with no real loader
        # elsewhere, E3 must still fire (pins the script-capture _in_template guard).
        html = build(cdn="").replace(
            "</body></html>",
            "<template>" + CDN_VALID + "<script>new Chart(z,{});</script></template></body></html>")
        e, _w, _n = run(html)
        self.assertTrue(any("no Chart.js" in x for x in e), e)


if __name__ == "__main__":
    unittest.main(verbosity=2)
