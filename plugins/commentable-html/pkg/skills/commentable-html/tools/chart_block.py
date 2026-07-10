#!/usr/bin/env python3
"""Build a deterministic Chart.js block for commentable-html documents.

Usage (run from the skill root):
    python tools/chart_block.py --spec spec.json --canvas-id wateringNeedsChart --caption "Weekly watering"
    python tools/chart_block.py --spec - --canvas-id wateringNeedsChart --caption "Weekly watering" --title "Beds"

The output has two clearly separated fragments:
  1) a <figure class="chart"> block for #commentRoot content
  2) chart scripts for after "END: commentable-html - JS" and before </body>

The tool self-validates the emitted fragments by injecting them into dist/PORTABLE.html
and running tools/validate.py as an import.
"""
import argparse
import html as _html
import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(HERE)
DEFAULT_TEMPLATE = os.path.join(SKILL_ROOT, "dist", "PORTABLE.html")

BEGIN_MARKER = "<!-- BEGIN: commentable-html - CONTENT (agent edits ONLY between these markers) -->"
END_MARKER = "<!-- END: commentable-html - CONTENT -->"

CHART_CDN = (
    '<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js" '
    'integrity="sha384-e6nUZLBkQ86NJ6TVVKAeSaK8jWa3NhkYWZFomE39AvDbQWeie9PlQqM3pmYW5d1g" '
    'crossorigin="anonymous"></script>'
)

_CANVAS_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")


def _read_text(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _read_spec(path):
    if path == "-":
        buffer = getattr(sys.stdin, "buffer", None)
        if buffer is not None:
            return buffer.read().decode("utf-8", errors="replace")
        return sys.stdin.read()
    return _read_text(path)


def _normalize_space(text):
    return re.sub(r"\s+", " ", (text or "").strip())


def derive_aria_label(caption, title=None):
    caption_text = _normalize_space(caption)
    title_text = _normalize_space(title)
    parts = []
    if title_text:
        parts.append(title_text)
    if caption_text and (not title_text or caption_text != title_text):
        parts.append(caption_text)
    if not parts:
        return "Chart"
    return "Chart: " + ". ".join(parts)


def _validate_canvas_id(canvas_id):
    if not _CANVAS_ID_RE.match(canvas_id or ""):
        raise ValueError("canvas id must match ^[A-Za-z][A-Za-z0-9_-]*$")


def _validate_spec(spec):
    if not isinstance(spec, dict):
        raise ValueError("spec must be a JSON object")
    if "type" not in spec:
        raise ValueError('spec is missing required "type"')
    if "data" not in spec:
        raise ValueError('spec is missing required "data"')


def _dump_spec(spec):
    dumped = json.dumps(spec, indent=2, ensure_ascii=False)
    return dumped.replace("<", "\\u003C")


def render_chart_fragments(spec, canvas_id, caption, title=None):
    _validate_canvas_id(canvas_id)
    if not _normalize_space(caption):
        raise ValueError("caption must be a non-empty string")
    _validate_spec(spec)

    caption_id = canvas_id + "-caption"
    data_id = canvas_id + "-data"
    aria_label = derive_aria_label(caption, title)
    caption_html = _html.escape(caption, quote=False)
    aria_html = _html.escape(aria_label, quote=True)
    spec_json = _dump_spec(spec)

    figure = (
        '<figure class="chart" aria-labelledby="%s">\n'
        '  <div class="chart-wrap cm-skip" style="position: relative; height: 360px;">\n'
        '    <canvas id="%s" role="img" aria-label="%s"></canvas>\n'
        "  </div>\n"
        '  <figcaption id="%s">%s</figcaption>\n'
        "</figure>"
    ) % (caption_id, canvas_id, aria_html, caption_id, caption_html)

    scripts = (
        CHART_CDN
        + "\n"
        + '<script id="%s" type="application/json">\n%s\n</script>\n'
        + "<script>\n"
        + "(function () {\n"
        + '  var el = document.getElementById("%s");\n'
        + '  if (!el || typeof Chart === "undefined") return;\n'
        + '  var config = JSON.parse(document.getElementById("%s").textContent);\n'
        + "  new Chart(el, config);\n"
        + "})();\n"
        + "</script>"
    ) % (data_id, spec_json, canvas_id, data_id)
    return {"figure": figure, "scripts": scripts, "spec_json": spec_json}


def render_output(spec, canvas_id, caption, title=None):
    parts = render_chart_fragments(spec, canvas_id, caption, title=title)
    return (
        "<!-- chart_block.py: paste this figure inside #commentRoot content -->\n"
        + parts["figure"]
        + "\n\n"
        + "<!-- chart_block.py: paste these scripts after END: commentable-html - JS and before </body> -->\n"
        + parts["scripts"]
        + "\n"
    )


def _inject_for_validation(template_html, figure, scripts):
    if template_html.count(BEGIN_MARKER) != 1 or template_html.count(END_MARKER) != 1:
        raise ValueError("template is missing a unique CONTENT marker pair")
    begin_idx = template_html.index(BEGIN_MARKER)
    end_idx = template_html.index(END_MARKER, begin_idx + len(BEGIN_MARKER))
    content_start = begin_idx + len(BEGIN_MARKER)
    out = template_html[:content_start] + "\n\n" + figure.strip() + "\n\n" + template_html[end_idx:]

    body_matches = list(re.finditer(r"</body\s*>", out, flags=re.IGNORECASE))
    if not body_matches:
        raise ValueError("template is missing </body>")
    body_pos = body_matches[-1].start()
    return out[:body_pos] + "\n\n" + scripts.strip() + "\n\n" + out[body_pos:]


def _self_validate(figure, scripts, template_path=DEFAULT_TEMPLATE):
    try:
        import validate as _validate
    except ModuleNotFoundError as exc:
        if exc.name != "validate":
            raise
        return None
    template_html = _read_text(template_path)
    candidate = _inject_for_validation(template_html, figure, scripts)
    fd, tmp = tempfile.mkstemp(suffix=".html", dir=os.getcwd())
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(candidate)
        return _validate.validate(tmp)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def main(argv):
    parser = argparse.ArgumentParser(
        prog="chart_block.py",
        description="Generate a validator-clean Chart.js figure and script bundle.")
    parser.add_argument("--spec", required=True, help="Chart.js config JSON file path, or '-' for stdin")
    parser.add_argument("--canvas-id", required=True, help="canvas element id")
    parser.add_argument("--caption", required=True, help="figure caption text")
    parser.add_argument("--title", default=None, help="optional chart title used in aria-label derivation")
    args = parser.parse_args(argv[1:])

    try:
        raw = _read_spec(args.spec)
        spec = json.loads(raw)
        fragments = render_chart_fragments(spec, args.canvas_id, args.caption, title=args.title)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        sys.stderr.write("chart_block: %s\n" % exc)
        return 2

    try:
        result = _self_validate(fragments["figure"], fragments["scripts"])
    except (OSError, ValueError) as exc:
        sys.stderr.write("chart_block: self-validation failed: %s\n" % exc)
        return 1
    if result is not None:
        errors, warnings = result
        if errors or warnings:
            sys.stderr.write("chart_block: generated fragments do not validate cleanly:\n")
            for item in errors:
                sys.stderr.write("  ERROR: %s\n" % item)
            for item in warnings:
                sys.stderr.write("  WARNING: %s\n" % item)
            return 1

    sys.stdout.write(render_output(spec, args.canvas_id, args.caption, title=args.title))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
