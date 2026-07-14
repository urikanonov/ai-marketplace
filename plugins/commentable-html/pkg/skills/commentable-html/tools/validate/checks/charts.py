"""Chart.js embedding checks: canvas labelling, the CDN-failure guard, and
chart-data JSON validity."""

import re
import json
from .parsing import LAYER_JSON_IDS, _is_executable_js, _is_json_attrs, _js_scan
from .resources import CHARTJS_SRC_RE


def _reject_json_constant(name):
    # Python's json.loads accepts NaN / Infinity / -Infinity by default, but the
    # browser's JSON.parse rejects them, so a chart-data block using one would throw
    # at init. Reject them here too.
    raise ValueError("invalid JSON constant %s (JSON.parse rejects it)" % name)


# A real network-failure guard (typeof Chart ==/===/!=/!== "undefined", optionally
# parenthesised as typeof(Chart)), not the bare substring "typeof Chart".
GUARD_RE = re.compile(r"typeof\s*\(?\s*Chart\s*\)?\s*[!=]={1,2}\s*(['\"])undefined\1", re.IGNORECASE)

# Executable chart init: `new Chart(` or a global-qualified `new window.Chart(` /
# `new globalThis.Chart(` / `new self.Chart(`.
NEW_CHART_RE = re.compile(r"\bnew\s+(?:Chart|(?:window|globalThis|self)\.Chart)\s*\(")

# An inline canvas draw: `<ctx>.getContext(...)` (2D or webgl). Lets a plain drawn
# canvas count as a renderer even without Chart.js.
CANVAS_RENDER_RE = re.compile(r"\.getContext\s*\(")


def check_charts(html, parser):
    """Return (errors, warnings, n_canvas). No-op (0 canvas) when the document
    embeds no <canvas>. Assumes `parser` already fed `html` successfully."""
    errors, warnings = [], []

    n_canvas = len(parser.canvases)
    if n_canvas == 0:
        return errors, warnings, 0

    marker_pos = parser.js_end_marker_pos
    has_layer = parser.has_comment_root or marker_pos is not None

    # Executable (classic/module JS) scripts: where `new Chart(` may run, and the
    # guard. A script with a `src` has its inline body ignored by the browser, so
    # do not scan it. Comments and string literals are blanked so they cannot
    # false-trigger.
    new_chart_positions = []
    guard_present = False
    inline_canvas_render = False
    for s in parser.scripts:
        if not _is_executable_js(s["attrs"]):
            continue
        if s["attrs"].get("src") is not None:
            continue  # <script src=...> inline content is dead code in the browser
        guard_src, init_src = _js_scan(s["body"])
        if NEW_CHART_RE.search(init_src):
            new_chart_positions.append(s["pos"])
        # An inline getContext draw renders a canvas WITHOUT any library. A bare
        # `new Chart(` does NOT count here: it needs the Chart.js loader (E3 still
        # fires if the loader is missing).
        if CANVAS_RENDER_RE.search(init_src):
            inline_canvas_render = True
        if GUARD_RE.search(guard_src):
            guard_present = True

    # The first executable Chart.js loader tag (by document position). A
    # non-executable script (e.g. type="application/json") with a chart.js src
    # does not load Chart, so it is not a loader.
    loader_attrs, loader_src, loader_pos = None, None, None
    for s in parser.scripts:
        src = s["attrs"].get("src")
        if src and CHARTJS_SRC_RE.search(src) and _is_executable_js(s["attrs"]):
            loader_attrs, loader_src, loader_pos = s["attrs"], src, s["pos"]
            break

    # E1) Every <canvas> must sit inside a cm-skip element (layer docs only).
    unskipped = sum(1 for c in parser.canvases if not c["skip"])
    if has_layer and unskipped:
        errors.append(f"{unskipped} of {n_canvas} <canvas> element(s) are not inside a cm-skip "
                      f"wrapper (the chart pixels become selectable; put cm-skip on the .chart-wrap)")

    # E2) A chart's <figcaption> must stay commentable. Flag only captions inside a
    # chart <figure> that got swept into cm-skip (the author put cm-skip on the
    # <figure> instead of the .chart-wrap). Other cm-skip captions (e.g. the KQL
    # caption chrome) are intentional and not chart captions.
    capped = sum(1 for f in parser.figcaptions
                 if f["skip"] and not f["in_canvas"] and f.get("in_chart_figure"))
    if has_layer and capped:
        errors.append(f"{capped} chart <figcaption>(s) are inside a cm-skip element and cannot be "
                      f"commented on - put cm-skip on the .chart-wrap around the <canvas>, not on the <figure>")

    # E3) A canvas needs a renderer or nothing shows: either the Chart.js loader,
    # or an inline script that draws to a canvas (getContext) / builds a Chart.
    if loader_attrs is None and not inline_canvas_render:
        errors.append("a <canvas> is present but no renderer was found (no Chart.js <script src> "
                      "and no inline canvas draw) - the chart will not render")

    # E4) Chart-data JSON must be valid and free of a "</script"/"<!--" breakout.
    for s in parser.scripts:
        if not _is_json_attrs(s["attrs"]):
            continue
        jid = s["attrs"].get("id") or None
        if jid in LAYER_JSON_IDS:
            continue  # owned by the commentable layer, not chart data
        where = f'id="{jid}"' if jid else "(no id)"
        body = s["body"]
        if "<!--" in body:
            errors.append(f'chart-data <script type="application/json"> {where} contains a "<!--" '
                          f'that can break out of the block - escape "<" as \\u003C when serializing')
            continue
        stripped = body.strip()
        if not stripped:
            errors.append(f'chart-data <script type="application/json"> {where} is empty - '
                          f'JSON.parse() will throw at chart init; emit valid JSON (e.g. [] or {{}})')
            continue
        try:
            json.loads(stripped, parse_constant=_reject_json_constant)
        except (json.JSONDecodeError, ValueError):
            errors.append(f'chart-data <script type="application/json"> {where} is not valid JSON - a raw '
                          f'"</script>" or a NaN/Infinity literal that JSON.parse rejects; serialize with '
                          f'an encoder and escape "<" as \\u003C')

    # E5) Chart init must come AFTER the JS END marker comment (Save-as-plain
    # keeps it) AND after the Chart.js loader (or Chart is undefined when it runs).
    if marker_pos is not None:
        if any(pos < marker_pos for pos in new_chart_positions):
            errors.append("chart init (`new Chart(`) appears before the `END: commentable-html - JS` "
                          "marker - place chart scripts after it so Save-as-plain preserves the chart")
    if loader_pos is not None:
        if any(pos < loader_pos for pos in new_chart_positions):
            errors.append("chart init (`new Chart(`) appears before the Chart.js `<script src>` loader - "
                          "load Chart.js first, or Chart is undefined when the init runs")

    # ---- warnings ----
    if loader_attrs is not None:
        integ = loader_attrs.get("integrity")
        has_cross = "crossorigin" in loader_attrs
        if not (integ and integ.strip()) or not has_cross:
            warnings.append("the Chart.js CDN tag has no (non-empty) Subresource Integrity hash + crossorigin - "
                            'add integrity="sha384-..." crossorigin="anonymous" for a shareable artifact')
        typ = (loader_attrs.get("type") or "").lower()
        if "defer" in loader_attrs or "async" in loader_attrs or typ == "module":
            warnings.append("the Chart.js CDN tag is deferred/async/module - the inline init can run before "
                            "Chart is defined; load it synchronously before the init")
        if not re.search(r"chart\.js@\d+\.\d+\.\d+", loader_src or "", re.IGNORECASE):
            warnings.append("the Chart.js CDN URL is not pinned to a full version (use chart.js@X.Y.Z, not "
                            "@latest or @4) - a floating version can change under you and break the SRI hash")

    n_missing_aria = sum(1 for c in parser.canvases
                         if c["attrs"].get("role", "").lower() != "img"
                         or not c["attrs"].get("aria-label", "").strip())
    if n_missing_aria:
        warnings.append("%d of %d <canvas> element(s) are missing role=\"img\" + a non-empty "
                        "aria-label (a canvas is opaque to screen readers; add an accessible "
                        "label to each)" % (n_missing_aria, n_canvas))

    if new_chart_positions and not guard_present:
        warnings.append("the chart init does not guard with `typeof Chart === \"undefined\"` - a network-unavailable / "
                        "CDN-blocked load will throw instead of degrading to a blank canvas")

    # W6) A loaded canvas with no executable `new Chart(` renders nothing.
    if loader_attrs is not None and not new_chart_positions:
        warnings.append("a <canvas> and the Chart.js loader are present but no executable `new Chart(` init "
                        "was found - the canvas will render blank (build the chart in an executable script)")

    return errors, warnings, n_canvas
