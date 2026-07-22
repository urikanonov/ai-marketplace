#!/usr/bin/env python3
"""Validate a commentable-html document against the skill's invariants.

This is the single, unified checker. It always validates the commentable LAYER
(region markers, required/forbidden ids, the two JSON blocks, theme variables,
mermaid cm-skip, ...) and, when the document embeds Chart.js charts, it also
checks the chart-embedding invariants that used to live in validate_charts.py.
Not all chart checks are enforced equally: a missing/broken loader, wrong chart
init ordering, and invalid chart-data JSON are hard ERRORS, while a non-pinned or
un-SRI loader, missing canvas accessibility (role/aria-label), and a missing
`typeof Chart` network-failure guard are advisory WARNINGS.

Both halves share ONE tolerant HTML parse (see _DocParser), so script tags are
read via the parser's own attribute handling rather than a fragile regex: a `>`
inside a quoted attribute, a loader or `new Chart(` inside an HTML comment, and
`data-src` / `data-type` masquerading as `src` / `type` are all handled
correctly.

Usage (run from the skill root):
    python tools/validate.py path/to/file.html [more.html ...]
    python tools/validate.py --charts-only file.html      # only the Chart.js checks
    python tools/validate.py --layer-only  file.html      # only the layer checks

Exit code 0 when every file passes (warnings allowed), 1 when any file has
errors, 2 on a usage problem. Pure standard library, no third-party packages.

Note: the layer checks expect human-readable (non-minified) HTML - the region
markers must sit on their own lines, which is how the skill emits them.

Structure: this module is the entry point and orchestrator (read, parse, run the
checks, CLI). The checks themselves live in focused submodules under `checks/`
(parsing, layer, resources, kind, charts, checklist, highlighting) and the
content-syntax checks in the sibling `cmhval/` package; validate.py re-exports
their public names so `validate.<name>` keeps resolving.
"""

import os
import re
import sys
import traceback

# The focused check modules live in the sibling cmhval/ and checks/ packages.
# Guarantee this tools dir is importable so `from cmhval...` / `from checks...`
# resolve under any invocation (mirrors the sys.path guard the other tools use).
_HERE = os.path.dirname(os.path.abspath(__file__))

if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# Put the tools/ root and every topic subdirectory (authoring/, blocks/, ...) on sys.path via the
# shared bootstrap, so the strict-clean stamp writer can `import doc_stamp` (which in turn imports
# section_hash) when validate.py runs as a STANDALONE CLI subprocess - not only in-process under a
# test's path setup. Without this, _stamp_validated_file's import silently ImportError'd and a
# `python tools/validate/validate.py <file>` run never stamped, so a clean validate still left the
# runtime "not validated" banner up (the exact defect in issue #584). The bootstrap below is a HARD
# dependency (see the import), not best-effort.
_TOOLS_ROOT = os.path.dirname(_HERE)
if _TOOLS_ROOT not in sys.path:
    sys.path.insert(0, _TOOLS_ROOT)
# A HARD import (not best-effort): every tool depends on _toolpath, and the failure handlers below
# reference it, so it must be bound. _HERE and _TOOLS_ROOT are on sys.path above, so this resolves
# in any real install; a genuinely missing _toolpath crashes loudly here (like every other tool),
# never silently - which is the whole point.
import _toolpath  # noqa: E402
_toolpath.ensure()

try:
    from cmhval.mermaid import check_mermaid_syntax, check_mermaid_source  # noqa: E402
    from cmhval.jsonblocks import check_json_blocks  # noqa: E402
    _CMHVAL_AVAILABLE = True
except ImportError:
    _toolpath.warn_missing_tool("cmhval", "content-syntax validation (mermaid diagrams / JSON blocks)")
    # The content-syntax checks live in the sibling cmhval/ package, which ships in
    # this same tools/ directory. If it cannot be imported (a broken/partial
    # install), fail CLOSED for any content it WOULD have inspected: a validator
    # that silently passes because its checks vanished is worse than one that
    # reports it cannot check. A document with no such content still passes, and
    # these stubs run only on the layer path, so --charts-only (which uses
    # check_charts here, not cmhval) is unaffected.
    _CMHVAL_AVAILABLE = False
    _CMHVAL_MISSING = (
        "the cmhval package could not be imported (broken/partial install of "
        "tools/cmhval/); repair the install to validate this content"
    )
    _LAYER_JSON_IDS = {"handledCommentIds", "embeddedComments", "commentableHtmlLayer"}

    def check_mermaid_syntax(parser):  # noqa: E402
        if getattr(parser, "mermaid_blocks", None):
            return ["mermaid syntax validation unavailable: " + _CMHVAL_MISSING], []
        return [], []

    def check_mermaid_source(src):  # noqa: E402
        if (src or "").strip():
            return ["mermaid syntax validation unavailable: " + _CMHVAL_MISSING]
        return []

    def check_json_blocks(parser, chart_checks_run=True):  # noqa: E402
        # Mirror the real check's deferral: when a canvas is present and the chart
        # checks run, the chart path (check_charts, unaffected by cmhval) owns JSON
        # validity, so there is nothing this would have inspected.
        if chart_checks_run and (getattr(parser, "canvases", []) or []):
            return [], []
        for s in getattr(parser, "scripts", []) or []:
            attrs = s.get("attrs", {}) if isinstance(s, dict) else {}
            stype = (attrs.get("type") or "").split(";")[0].strip().lower()
            if stype == "application/json" and (attrs.get("id") or None) not in _LAYER_JSON_IDS:
                return ["embedded-JSON validation unavailable: " + _CMHVAL_MISSING], []
        return [], []

# Re-export the focused check modules so every `validate.<name>` the tests and
# sibling tools reference keeps resolving after the split (see checks/).
from checks.parsing import (  # noqa: F401,E402
    CONTENT_BEGIN,
    CONTENT_END,
    DEMO_COMMENT_KEY,
    DEMO_KEYS,
    DEMO_NONPORTABLE_COMMENT_KEY,
    DEMO_NONPORTABLE_TITLE,
    DEMO_TITLE,
    DOC_EXAMPLE_COMMENT_KEY,
    FORBIDDEN_IDS,
    JS_END_MARKER_TEXT,
    LAYER_DESCRIPTOR_ID,
    LAYER_JSON_IDS,
    P_CLOSERS,
    REGIONS,
    REQUIRED_IDS,
    SAFE_ID_RE,
    VOID,
    _CLASS_ATTR_RE,
    _CODE_TAG_RE,
    _COMMENT_ROOT_ATTR_RE,
    _DATA_KEY_RE,
    _DocParser,
    _HEADING_TAGS,
    _HTML_COMMENT_RE,
    _JS_TYPES,
    _LI_CLOSE_BOUNDARY,
    _MarkerMatch,
    _PRE_TAG_RE,
    _P_CLOSE_BOUNDARY,
    _SCRIPT_STYLE_RE,
    _TITLE_RE,
    _TRANSIENT_BODY_CLASSES,
    _TagAttrParser,
    _advance_comment_state,
    _attrs_have_class,
    _find_tag_attrs,
    _is_executable_js,
    _is_json_attrs,
    _js_scan,
    _line_starts,
    _parser_script,
    _parser_script_body,
    _region_marker_matches,
)
from checks.resources import (  # noqa: F401,E402
    CHARTJS_SRC_RE,
    CSS_NETWORK_URL_RE,
    FETCHING_LINK_RELS,
    META_REFRESH_NETWORK_RE,
    NONPORTABLE_REGIONS,
    OFFLINE_CSP_REQUIRED,
    _ADX_RUN_HOST,
    _check_nonportable,
    _csp_directives,
    _file_url_to_path,
    _is_adx_run_href,
    _is_nonportable,
    _link_loads,
    _nonportable_css_refs,
    _nonportable_js_refs,
    _nonportable_meta_versions,
    _offline_csp_errors,
    _ref_path,
)
from checks.kind import (  # noqa: F401,E402
    _DOC_KINDS,
    _KINDS_REQUIRING_H1,
    _KIND_META_NAME,
    _SECTION_DIR_RE,
    check_document_kind,
    check_favicon,
    check_mermaid_renders,
    check_section_reference_links,
)
from checks.charts import (  # noqa: F401,E402
    CANVAS_RENDER_RE,
    GUARD_RE,
    NEW_CHART_RE,
    _reject_json_constant,
    check_charts,
)
from checks.checklist import (  # noqa: F401,E402
    _CHECK_STATES,
    _CL_VOID,
    _ChecklistParser,
    check_checklists,
)
from checks.notes import (  # noqa: F401,E402
    _NotesParser,
    check_notes,
)
from checks.highlighting import (  # noqa: F401,E402
    _code_block_language,
    _highlight_language_table,
    check_code_highlighting,
)
from checks.theme_contrast import (  # noqa: F401,E402
    ADVISORY_PREFIX,
    check_theme_contrast,
    theme_contrast_findings,
)
from checks.density import (  # noqa: F401,E402
    check_density,
)
from checks.layer import (  # noqa: F401,E402
    _check_layer_descriptor,
    _layer_descriptor_data,
    check_layer,
)


def _read(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _parse(html):
    """Feed `html` to a fresh _DocParser. Returns (parser, ok); ok is False if
    HTMLParser raised on markup too malformed to tokenize."""
    parser = _DocParser(html)
    try:
        parser.feed(html)
        parser.close()
        return parser, True
    except Exception:
        return parser, False


_PARSE_FAIL = ("the document could not be parsed as HTML (malformed markup) - "
               "fix the markup and re-run")

_BASE_DIR_UNSET = object()


def validate(path, layer=True, charts=True, base_dir=_BASE_DIR_UNSET):
    """Unified check. Returns (errors, warnings). Runs the layer checks and,
    when the document has a <canvas>, the chart checks too.

    base_dir controls how NonPortable companion references are resolved for the
    existence/remote/absolute checks: by default it is the document's own directory.
    Pass an explicit directory to resolve refs against the file's FINAL location (used
    when validating before the file is written there), or None to skip the companion
    path checks entirely (structure is still validated) - appropriate when the
    companions are supplied separately or placement is deferred."""
    try:
        html = _read(path)
    except (OSError, UnicodeDecodeError) as exc:
        return [f"cannot read file: {exc}"], []
    parser, ok = _parse(html)
    if not ok:
        return [_PARSE_FAIL], []
    errors, warnings = [], []
    if layer:
        bd = os.path.dirname(os.path.abspath(path)) if base_dir is _BASE_DIR_UNSET else base_dir
        e, w = check_layer(html, parser, base_dir=bd)
        errors += e
        warnings += w
        # Content-syntax checks (mermaid diagrams, embedded JSON, and later
        # diff/kql) are document-content invariants, so they run with the layer
        # checks, not the chart-only path.
        e, w = check_mermaid_syntax(parser)
        errors += e
        warnings += w
        e, w = check_json_blocks(parser, chart_checks_run=charts)
        errors += e
        warnings += w
    if charts:
        e, w, _n = check_charts(html, parser)
        errors += e
        warnings += w
    if layer:
        e, w = check_checklists(html)
        errors += e
        warnings += w
        e, w = check_notes(html)
        errors += e
        warnings += w
        e, w = check_code_highlighting(html)
        errors += e
        warnings += w
        e, w = check_theme_contrast(html)
        errors += e
        warnings += w
        e, w = check_density(html)
        errors += e
        warnings += w
    return errors, warnings


def validate_charts(path):
    """Chart-only check. Returns (errors, warnings, n_canvas)."""
    try:
        html = _read(path)
    except (OSError, UnicodeDecodeError) as exc:
        return [f"cannot read file: {exc}"], [], 0
    parser, ok = _parse(html)
    if not ok:
        n = len(re.findall(r"<canvas(?![-\w])", html, re.IGNORECASE))
        return ([_PARSE_FAIL] if n else []), [], n
    return check_charts(html, parser)


_USAGE = "usage: python tools/validate.py [--charts-only|--layer-only] [--strict] [--suggest] [--no-stamp] <file.html> [more.html ...]"


def _print_theme_suggestions(path):
    """Print a compliant nudged value for each authored --cp-* override that misses its contrast
    target. Best-effort: a read/parse failure here never affects the validation exit code."""
    try:
        html = _read(path)
    except (OSError, UnicodeDecodeError):
        return
    for f in theme_contrast_findings(html):
        if f.severity == "unresolved":
            print(f"  SUGGEST: {f.env} theme {f.fg_token} on {f.bg_token} not evaluated "
                  f"({f.fg_value!r} or {f.bg_value!r} did not resolve to a concrete color)")
        elif f.suggestion:
            print(f"  SUGGEST: {f.env} theme {f.fg_token} -> {f.suggestion} to reach "
                  f"{f.target:.1f}:1 on {f.bg_token} ({f.fg_value} is {f.ratio:.2f}:1)")
        else:
            print(f"  SUGGEST: {f.env} theme {f.fg_token} on {f.bg_token} at {f.ratio:.2f}:1 has "
                  f"no reachable fix by nudging the foreground; adjust {f.bg_token} instead")


def _stamp_validated_file(path):
    """Write the commentable-html-validated provenance stamp (timestamp + content hash) into a
    strict-clean file. Best-effort so a stamp failure never BLOCKS validation, but NOT silent: the
    import path is fixed (see the _toolpath bootstrap above) so this should always succeed, and if
    it ever fails we print a visible NOTE rather than silently reporting a clean validation that
    wrote no stamp - the confusing UX that #584 fixed. Stamping now runs an HTML parse
    (doc_stamp -> section_hash), a wider failure surface than the old timestamp-only write, so catch
    broadly. The subprocess-stamp tests guard against a silent regression of the import path."""
    try:
        import doc_stamp
    except ImportError:
        _toolpath.warn_missing_tool("doc_stamp", "the validated stamp")
        return
    try:
        with open(path, "r", encoding="utf-8", newline="") as fh:
            html = fh.read()
        stamped = doc_stamp.stamp_validated_html(html)
        if stamped != html:
            with open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(stamped)
    except Exception as exc:
        sys.stderr.write(
            "  NOTE: could not write the validated stamp (%s); the document PASSED validation but "
            "is not stamped, so the runtime may still show the 'not validated' banner - re-run to "
            "stamp.\n" % exc)


def _wants_help(tokens):
    # Honor -h/--help only before an end-of-options "--"; a -h AFTER "--" is a filename.
    for t in tokens:
        if t == "--":
            return False
        if t in ("-h", "--help"):
            return True
    return False


def main(argv):
    raw = argv[1:]
    if _wants_help(raw):
        print(_USAGE)
        print("\nValidate one or more commentable-html documents.")
        print("  --charts-only  run only the Chart.js checks")
        print("  --layer-only   run only the commentable-html layer checks")
        print("  --strict       exit non-zero if any warning remains")
        print("  --suggest      print a compliant nudged value for each low-contrast --cp-* override")
        print("  --no-stamp     do not write the commentable-html-validated stamp on a clean pass")
        print("                 (a --charts-only/--layer-only partial run never stamps either)")
        return 0
    # A bare "--" ends options: everything after it is a positional path, even if it
    # begins with a dash. Flags are only recognized before the separator.
    if "--" in raw:
        sep = raw.index("--")
        before, after = raw[:sep], raw[sep + 1:]
    else:
        before, after = raw, []
    args = [a for a in before if not a.startswith("--")] + after
    flags = {a for a in before if a.startswith("--")}
    known_flags = {"--charts-only", "--layer-only", "--strict", "--suggest", "--no-stamp"}
    unknown = sorted(flags - known_flags)
    if unknown:
        sys.stderr.write("unknown flag(s): %s\n" % ", ".join(unknown))
        sys.stderr.write(_USAGE + "\n")
        return 2
    layer = "--charts-only" not in flags
    charts = "--layer-only" not in flags
    strict = "--strict" in flags
    suggest = "--suggest" in flags
    # Only a FULL validation (both the layer and chart halves) may stamp: a partial run
    # (--charts-only / --layer-only) has not confirmed the whole document, so stamping it would let
    # a doc with broken layer regions (or chart errors) suppress the runtime banner. --no-stamp also
    # keeps any run read-only.
    stamp = ("--no-stamp" not in flags) and layer and charts
    if not args or (not layer and not charts):
        sys.stderr.write(_USAGE + "\n")
        return 2
    any_errors = False
    any_warnings = False
    for path in args:
        try:
            errors, warnings = validate(path, layer=layer, charts=charts)
        except Exception:
            # A bug in one file's checks must never abort the whole batch.
            errors, warnings = [f"internal validator error:\n{traceback.format_exc().strip()}"], []
        print(f"commentable-html validate: {path}")
        for w in warnings:
            print(f"  WARNING: {w}")
        for e in errors:
            print(f"  ERROR:   {e}")
        if suggest:
            _print_theme_suggestions(path)
        if warnings:
            any_warnings = True
        if errors:
            any_errors = True
            print(f"  FAILED ({len(errors)} error(s), {len(warnings)} warning(s))")
        elif strict and warnings:
            print(f"  FAILED (strict): {len(warnings)} warning(s) - resolve every warning before handoff")
        else:
            print(f"  OK ({len(warnings)} warning(s))")
            # Stamp commentable-html-validated ONLY on a strict-clean pass (no errors AND no
            # warnings) of a FULL validation (see `stamp` above: never for a --charts-only /
            # --layer-only partial run), so the runtime banner clears only for a document that
            # genuinely passed the whole validator. --no-stamp keeps a pure --check/CI run read-only.
            if stamp and not errors and not warnings:
                _stamp_validated_file(path)
    if any_errors:
        return 1
    if strict and any_warnings:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
