"""Embedded application/json script-block validity (a shipped, zero-false-positive
check). A `<script type="application/json">` block whose text is not valid JSON
makes the `JSON.parse(...)` that reads it throw at runtime (chart init, a data
table, etc.), so an invalid block is always a real defect.

This complements, and does not duplicate, the Chart.js checks in charts.py: those
validate chart-data JSON only when the document has a <canvas> AND the chart
checks actually run (the default and --charts-only). This module covers the
remaining cases - a document that embeds JSON but has no canvas, or a --layer-only
run where the chart checks do not run - so a broken data block is still caught.
Deeper Chart.js CONFIG validity (unknown chart type, malformed structure) is
intentionally left to the repo-side real-Chart.js oracle
(dev/tools/validate_render.mjs); reproducing it in Python risks false positives (a
plugin-registered controller, a non-chart JSON blob that merely has a "type"
field), so it is not attempted here.
"""

import json

# application/json blocks owned by the commentable layer, not user data.
_LAYER_JSON_IDS = {"handledCommentIds", "embeddedComments", "commentableHtmlLayer"}


def _is_json_attrs(ad):
    return (ad.get("type", "") or "").split(";")[0].strip().lower() == "application/json"


def _reject_constant(name):
    # Python's json.loads accepts NaN / Infinity / -Infinity by default, but the
    # browser's JSON.parse rejects them, so they must fail here too.
    raise ValueError("invalid JSON constant %s (JSON.parse rejects it)" % name)


def check_json_blocks(parser, chart_checks_run=True):
    """Return (errors, warnings). Flags non-layer application/json blocks that are
    empty, not valid JSON, or carry a `<!--` breakout. When a <canvas> is present
    AND the chart checks will run (chart_checks_run), the chart path owns JSON
    validity, so this defers to avoid double-reporting; in --layer-only mode
    (chart_checks_run False) the chart checks do not run, so this must still
    validate."""
    errors, warnings = [], []
    if chart_checks_run and len(getattr(parser, "canvases", []) or []):
        return errors, warnings
    for s in getattr(parser, "scripts", []) or []:
        ad = s.get("attrs", {})
        if not _is_json_attrs(ad):
            continue
        jid = ad.get("id") or None
        if jid in _LAYER_JSON_IDS:
            continue
        where = 'id="%s"' % jid if jid else "(no id)"
        body = s.get("body") or ""
        stripped = body.strip()
        if not stripped:
            errors.append('embedded <script type="application/json"> %s is empty - '
                          "JSON.parse() will throw when it is read; emit valid JSON "
                          "(e.g. [] or {})" % where)
            continue
        try:
            json.loads(stripped, parse_constant=_reject_constant)
        except (json.JSONDecodeError, ValueError):
            errors.append('embedded <script type="application/json"> %s is not valid JSON - '
                          "the JSON.parse() that reads it will throw at runtime; fix the JSON "
                          '(a raw "</script>", a trailing comma, or a NaN/Infinity literal is the '
                          "usual cause)" % where)
    return errors, warnings
