#!/usr/bin/env python3
"""Build a deterministic Chart.js block for commentable-html documents.

Usage (run from the skill root):
    python tools/chart_block.py --spec spec.json --canvas-id wateringNeedsChart --caption "Weekly watering"
    python tools/chart_block.py --spec - --canvas-id wateringNeedsChart --caption "Weekly watering" --title "Beds"

The output has two clearly separated fragments:
  1) a <figure class="chart"> block for #commentRoot content
  2) chart scripts for after "END: commentable-html - JS" and before </body>

The tool self-validates the emitted fragments by injecting them into dist/SHAREABLE.html
and running tools/validate.py as an import.
"""
import argparse
import importlib.util
import json
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tools/ root
import _toolpath  # noqa: E402
_toolpath.ensure()
import _browser_attrs  # noqa: E402
SKILL_ROOT = _toolpath.SKILL_ROOT
_TOOLS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_TEMPLATE = _toolpath.dist_template(_toolpath.SHAREABLE_TEMPLATE)

BEGIN_MARKER = "<!-- BEGIN: commentable-html - CONTENT (agent edits ONLY between these markers) -->"
END_MARKER = "<!-- END: commentable-html - CONTENT -->"

CHART_CDN = (
    '<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.js" '
    'integrity="sha384-FcQlsUOd0TJjROrBxhJdUhXTUgNJQxTMcxZe6nHbaEfFL1zjQ+bq/uRoBQxb0KMo" '
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
    caption_html = _browser_attrs.escape_text(caption)
    aria_html = _browser_attrs.escape_attr_value(aria_label)
    spec_json = _dump_spec(spec)

    figure = (
        '<figure class="chart" aria-labelledby="%s">\n'
        '  <div class="chart-wrap cm-skip" style="position: relative; height: 360px; max-height: min(60vh, 480px); overflow: hidden;">\n'
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
        + "  config.options = config.options || {};\n"
        + "  config.options.responsive = true;\n"
        + "  config.options.maintainAspectRatio = false;\n"
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


def _canonical(path):
    """Resolve for COMPARISON: symlinks and junctions followed, Windows casing folded.

    A plain abspath+startswith rejects the real validator when the skill is reached through
    a junction or a differently-cased path, which would turn this guard into a false alarm.
    """
    if not path:
        return ""
    return os.path.normcase(os.path.realpath(path))


def _contained(path):
    """True when `path` lives inside this skill's own tools/validate directory.

    Both sides are compared in two forms - fully resolved, and merely absolute - so a
    junction, a differently-cased path, OR a per-file symlink of validate.py to a shared
    location all still count as the real validator rather than tripping the guard.

    Anything that is not a usable path string is REFUSED rather than allowed to raise:
    `os.PathLike` is only a promise of `__fspath__`, and the caller runs outside its own
    try block, so a value that cannot be normalized has to come back as "not ours".
    """
    try:
        path = os.fspath(path)
    except Exception:  # noqa: BLE001  a non-path value, or a hostile/broken __fspath__
        return False
    if type(path) is not str or not path:
        return False
    expected = os.path.join(_TOOLS_DIR, "validate")
    try:
        candidates = {_canonical(path), os.path.normcase(os.path.abspath(path))}
        bases = {_canonical(expected), os.path.normcase(os.path.abspath(expected))}
        return any(c.startswith(b + os.sep) for c in candidates if c for b in bases if b)
    except (OSError, ValueError):
        # A NUL byte or an over-long path cannot name the real validator either.
        return False


def _describe(value):
    """Render a module origin for a message without letting an odd value raise."""
    try:
        if not value:
            return "an unknown location"
        return str(value) or "an unknown location"
    except Exception:  # noqa: BLE001  a hostile __bool__ or __str__
        return "an unrepresentable location"


def _safe_repr(value):
    """repr() that cannot itself raise, for values a misbehaving validator produced."""
    try:
        return repr(value)
    except Exception:  # noqa: BLE001  a hostile __repr__
        return "an unrepresentable value"


def _safe_text(value):
    """str() that cannot itself raise, for an exception rendered into a reason."""
    try:
        return str(value)
    except Exception:  # noqa: BLE001  a hostile __str__
        return "an unrepresentable value"


def _origin_of(obj, name):
    """Read a module/spec origin attribute without letting the ACCESS raise.

    `sys.modules` can hold a lazy loader or a proxy whose attribute access executes
    arbitrary code, and this runs outside the caller's try block.
    """
    try:
        return getattr(obj, name, "")
    except Exception:  # noqa: BLE001
        return ""


def _load_validator():
    """Return (module, None), or (None, reason) when it cannot be used.

    Every failure becomes a REASON rather than an exception, because the caller's whole job
    is to distinguish "checked and bad" from "could not check". Re-raising gave a traceback
    instead of the fail-closed message and made the opt-out unreachable - and the shapes that
    reach here are exactly the broken installs this guard exists for: a missing `validate`,
    a `validate.py` whose own `checks.*` imports are missing, and a truncated `validate.py`
    that raises SyntaxError.

    The origin is checked BEFORE the import, so an unrelated `validate` earlier on sys.path
    is refused without executing its module body; an already-imported module is re-checked by
    its `__file__` for the same reason.
    """
    module = sys.modules.get("validate")
    if module is None:
        try:
            spec = importlib.util.find_spec("validate")
        except Exception as exc:  # noqa: BLE001  a broken parent package, a bad sys.path entry
            return None, "the sibling 'validate' tool could not be located (%s: %s)" % (
                type(exc).__name__, _safe_text(exc))
        if spec is None:
            return None, "the sibling 'validate' tool is not importable (no module named 'validate')"
        origin = _origin_of(spec, "origin")
        if not _contained(origin):
            return None, ("the 'validate' module on sys.path is %s, not this skill's "
                          "tools/validate/validate.py" % (_describe(origin),))
        try:
            import validate as module  # noqa: F401
        except Exception as exc:  # noqa: BLE001
            # Announce it here too (the repo forbids a silent guarded sibling import), then let
            # the caller decide what to do with the reason.
            _toolpath.warn_missing_tool("validate", "chart self-validation")
            return None, "the sibling 'validate' tool could not be imported (%s: %s)" % (
                type(exc).__name__, _safe_text(exc))
    origin = _origin_of(module, "__file__")
    if not _contained(origin):
        return None, ("the imported 'validate' module is %s, not this skill's "
                      "tools/validate/validate.py" % (_describe(origin),))
    return module, None


def _self_validate_result(figure, scripts, template_path=None):
    """Return ((errors, warnings), None), or (None, reason it could not be checked)."""
    template_path = template_path or DEFAULT_TEMPLATE
    module, reason = _load_validator()
    if module is None:
        return None, reason
    try:
        template_html = _read_text(template_path)
        candidate = _inject_for_validation(template_html, figure, scripts)
    except (OSError, ValueError) as exc:
        # A missing or corrupt dist/SHAREABLE.html is the same class of problem as a missing
        # validator - the environment, not the fragments - so it takes the same gate.
        return None, "the validation template could not be prepared (%s)" % exc
    # The temp file location does not affect chart validation (it inspects the fragment,
    # not companion files), so use the system temp dir rather than os.getcwd(), which may
    # be read-only (e.g. C:\Windows\System32).
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(suffix=".html")
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(candidate)
        outcome = module.validate(tmp)
    except Exception as exc:  # noqa: BLE001
        # A validator that crashes, or a temp dir that cannot be written, means the check did
        # not happen - the same "could not be checked" signal, so it takes the same gate and
        # the opt-out applies, instead of escaping as a traceback.
        return None, "the validator could not run (%s: %s)" % (
            type(exc).__name__, _safe_text(exc))
    finally:
        if tmp is not None:
            try:
                os.remove(tmp)
            except OSError:
                pass
    if not (isinstance(outcome, tuple) and len(outcome) == 2
            and all(isinstance(part, list) for part in outcome)):
        # A validator that answers in an unexpected shape has not given a verdict. Checking the
        # MEMBERS matters as much as the arity: a `(None, None)` would satisfy a bare 2-tuple
        # test and then read as "no errors, no warnings", i.e. the fail-open path again.
        return None, "the validator returned an unexpected result (%s)" % (_safe_repr(outcome),)
    return outcome, None


def _self_validate(figure, scripts, template_path=None):
    return _self_validate_result(figure, scripts, template_path)[0]


def main(argv):
    parser = argparse.ArgumentParser(
        prog="chart_block.py",
        description="Generate a validator-clean Chart.js figure and script bundle.")
    parser.add_argument("--spec", required=True, help="Chart.js config JSON file path, or '-' for stdin")
    parser.add_argument("--canvas-id", required=True, help="canvas element id")
    parser.add_argument("--caption", required=True, help="figure caption text")
    parser.add_argument("--title", default=None, help="optional chart title used in aria-label derivation")
    parser.add_argument("--allow-unvalidated-output", action="store_true",
                        help="print the fragments even when they could not be CHECKED at all - an "
                             "unimportable or crashing validator, a validator that answers in an "
                             "unexpected shape, or a missing/corrupt validation template. Off by "
                             "default: this tool's guarantee is that what it prints validates, and "
                             "silently dropping that guarantee on a broken install is the wrong "
                             "direction. It never suppresses a real validation failure.")
    args = parser.parse_args(argv[1:])

    try:
        raw = _read_spec(args.spec)
        spec = json.loads(raw)
        fragments = render_chart_fragments(spec, args.canvas_id, args.caption, title=args.title)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        sys.stderr.write("chart_block: %s\n" % exc)
        return 2

    result, reason = _self_validate_result(fragments["figure"], fragments["scripts"])
    if result is None:
        # The fragments could not be CHECKED (a broken or partial install), which is not the
        # same as being invalid. Emitting them anyway would drop this tool's one guarantee
        # precisely where something is already wrong, so fail closed unless the caller opted
        # in knowingly.
        if not args.allow_unvalidated_output:
            sys.stderr.write(
                "chart_block: the fragments could not be self-validated - %s - so nothing was "
                "written. Reinstall or re-extract the skill, or pass --allow-unvalidated-output "
                "to emit them unchecked.\n" % reason)
            return 1
        sys.stderr.write("chart_block: WARNING - emitting fragments that were not self-validated "
                         "(%s).\n" % reason)
    else:
        errors, warnings = result
        # An advisory names something the author cannot clear (CMH-VAL-18), so it is reported
        # but never blocks; every other warning still fails this self-validation closed. A
        # non-None result means validate imported cleanly inside _self_validate.
        import validate as _validate  # noqa: E402
        fatal, advisory = _validate.partition_warnings(warnings)
        for item in advisory:
            sys.stderr.write("chart_block: ADVISORY: %s\n" % item)
        if errors or fatal:
            sys.stderr.write("chart_block: generated fragments do not validate cleanly:\n")
            for item in errors:
                sys.stderr.write("  ERROR: %s\n" % item)
            for item in fatal:
                sys.stderr.write("  WARNING: %s\n" % item)
            return 1

    sys.stdout.write(render_output(spec, args.canvas_id, args.caption, title=args.title))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
