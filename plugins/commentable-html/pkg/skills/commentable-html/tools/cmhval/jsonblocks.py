"""Embedded application/json script-block validity (a shipped, zero-false-positive
check). A `<script type="application/json">` block whose text is not valid JSON
makes the `JSON.parse(...)` that reads it throw at runtime (chart init, a data
table, etc.), so an invalid block is always a real defect.

This complements, and does not duplicate, the Chart.js checks in charts.py: those
validate chart-data JSON only when the document has a <canvas> (the chart path).
This module covers the remaining case - a document that embeds JSON but has no
canvas - so a broken data block is still caught. Deeper Chart.js CONFIG validity
(unknown chart type, malformed structure) is intentionally left to the repo-side
real-Chart.js oracle (dev/tools/validate_render.mjs); reproducing it in Python
risks false positives (a plugin-registered controller, a non-chart JSON blob that
merely has a "type" field), so it is not attempted here.
"""

import json

# application/json blocks owned by the commentable layer, not user data.
_LAYER_JSON_IDS = {"handledCommentIds", "embeddedComments", "commentableHtmlLayer"}


def _is_json_attrs(ad):
    return (ad.get("type", "") or "").split(";")[0].strip().lower() == "application/json"


def check_json_blocks(parser):
    """Return (errors, warnings). Flags non-layer application/json blocks that are
    not valid JSON, but only when the document has no <canvas> - the chart checks
    already validate chart-data JSON on the canvas path, so this never
    double-reports."""
    errors, warnings = [], []
    if len(getattr(parser, "canvases", []) or []):
        # The chart path (charts.check_charts) owns JSON validity when a canvas is
        # present; skip here so a broken block is reported exactly once.
        return errors, warnings
    for s in getattr(parser, "scripts", []) or []:
        ad = s.get("attrs", {})
        if not _is_json_attrs(ad):
            continue
        jid = ad.get("id") or None
        if jid in _LAYER_JSON_IDS:
            continue
        where = 'id="%s"' % jid if jid else "(no id)"
        stripped = (s.get("body") or "").strip()
        if not stripped:
            errors.append('embedded <script type="application/json"> %s is empty - '
                          "JSON.parse() will throw when it is read; emit valid JSON "
                          "(e.g. [] or {})" % where)
            continue
        try:
            json.loads(stripped)
        except (json.JSONDecodeError, ValueError):
            errors.append('embedded <script type="application/json"> %s is not valid JSON - '
                          "the JSON.parse() that reads it will throw at runtime; fix the JSON "
                          '(a raw "</script>" or a trailing comma is the usual cause)' % where)
    return errors, warnings
