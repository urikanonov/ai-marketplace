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
VALIDATE_PY = os.path.join(TOOLS, "validate", "validate.py")

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

# Same as MAIN but the content opens with a top-level <h1>, so it satisfies the
# title requirement of the report/plan document kinds.
MAIN_H1 = (
    '<main id="commentRoot" data-cmh-content-root data-comment-key="k" data-doc-label="l" data-doc-source="s">\n'
    + CONTENT_BEGIN + "\n"
    "  <h1>Title</h1>\n"
    "  <p>content</p>\n"
    + CONTENT_END + "\n"
    "</main>"
)

# A report/plan whose only <h1> is buried inside a <section> - a NESTED heading, not the
# document's own top-level title. new_document (and #81) require a top-level title, so this
# must fail the report/plan h1 rule.
MAIN_NESTED_H1 = (
    '<main id="commentRoot" data-cmh-content-root data-comment-key="k" data-doc-label="l" data-doc-source="s">\n'
    + CONTENT_BEGIN + "\n"
    "  <section><h1>Buried Title</h1></section>\n"
    "  <p>content</p>\n"
    + CONTENT_END + "\n"
    "</main>"
)

# new_document's auto-title wraps the <h1> in a top-level <header class="cmh-lede">. That
# lede header is a direct child of #commentRoot and is the document's title, so it must
# satisfy the report/plan h1 rule (this pins compatibility with new_document.ensure_doc_title).
MAIN_LEDE_H1 = (
    '<main id="commentRoot" data-cmh-content-root data-comment-key="k" data-doc-label="l" data-doc-source="s">\n'
    + CONTENT_BEGIN + "\n"
    '  <header class="cmh-lede">\n    <h1>Lede Title</h1>\n  </header>\n'
    "  <p>content</p>\n"
    + CONTENT_END + "\n"
    "</main>"
)

# An EMPTY lede header (no h1) must NOT satisfy the title rule (F5: the class alone used to pass).
MAIN_EMPTY_LEDE = (
    '<main id="commentRoot" data-cmh-content-root data-comment-key="k" data-doc-label="l" data-doc-source="s">\n'
    + CONTENT_BEGIN + "\n"
    '  <header class="cmh-lede"></header>\n'
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


def build(css=None, body=None, kind="generic"):
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
    kind_meta = ('<meta name="commentable-html-kind" content="%s" />\n' % kind) if kind is not None else ""
    return (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n'
        + kind_meta
        + '<script type="application/json" id="commentableHtmlLayer">'
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
    head.append('<meta name="commentable-html-kind" content="generic">')
    body = [nonportable_bootstrap(banner, watchdog), HANDLED_REGION, EMBEDDED_REGION,
            comment_ui(), MAIN, nonportable_scripts(version, runtime, assets)]
    return ('<!DOCTYPE html>\n<html lang="en">\n<head>\n'
            + "\n".join(head)
            + "\n</head>\n<body>\n"
            + "\n".join(body)
            + "\n</body>\n</html>\n")
