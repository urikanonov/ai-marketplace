#!/usr/bin/env python3
"""Create a ready-to-use commentable-html document from a content fragment.

A finished commentable report is a ~240KB standalone file whose CSS/HTML/JS
regions are byte-for-byte the template's; the only per-document parts are the
content root's data-* attributes and the fragment between the CONTENT markers.
Re-emitting the whole template by hand to place a new document wastes tokens and
risks corrupting a layer region. This helper instead clones dist/PORTABLE.html and
surgically swaps only those two per-document parts:

  - the fragment BETWEEN the CONTENT-BEGIN/CONTENT-END markers, and
  - `data-comment-key` / `data-doc-label` / `data-doc-source` on the
    `<main id="commentRoot">` that IMMEDIATELY precedes CONTENT-BEGIN.

The content root is anchored off the unique CONTENT markers, never off the first
`<main id="commentRoot">` in the file - the template's top-of-file documentation
comment contains a second, decoy `<main id="commentRoot">` (the "my-doc"
example) that must stay untouched.

Usage (run from the skill root):
    python tools/new_document.py --content body.html --key my-report-v1 --label "My Report"
    echo '<section><h2 id="a">Hi</h2></section>' | \
        python tools/new_document.py --content - --key my-report-v1 --label "My Report" --out out.html

The result is self-validated with validate.py before it is written; validation
errors print to stderr and exit 1. Output goes to stdout unless --out is given.
"""
import argparse
import hashlib
import html as _html
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BEGIN_MARKER = "<!-- BEGIN: commentable-html - CONTENT (agent edits ONLY between these markers) -->"
END_MARKER = "<!-- END: commentable-html - CONTENT -->"

# Keys that must never become a live content root: the two demo roots the
# template ships and the "my-doc" example in the top documentation comment.
# validate.py fails a document whose active root keeps a demo key, so refusing
# them up front keeps this tool from ever producing a document validate rejects.
REFUSED_KEYS = frozenset({
    "commentable-html-demo",
    "commentable-html-nonportable-demo",
    "my-doc",
})

# The content root, anchored so only a real `<main>` opening tag matches (id is
# case-sensitive to match getElementById; the value may be quoted or unquoted).
_MAIN_ROOT_RE = re.compile(r'<main\b[^>]*?\bid\s*=\s*["\']?commentRoot["\']?(?=[\s>/])')
# name / optional value (double-quoted, single-quoted, or bare) for tag attrs.
_ATTR_RE = re.compile(r'([^\s=/<>]+)(?:\s*=\s*("[^"]*"|\'[^\']*\'|[^\s>]+))?')
_TITLE_RE = re.compile(r'(<title[^>]*>).*?(</title>)', re.IGNORECASE | re.DOTALL)


def _tag_end(html, start):
    """Return the index of the '>' that closes the tag opening at `start`,
    skipping any '>' that sits inside a quoted attribute value."""
    quote = None
    for i in range(start, len(html)):
        c = html[i]
        if quote is not None:
            if c == quote:
                quote = None
        elif c in "\"'":
            quote = c
        elif c == ">":
            return i
    raise ValueError("unterminated <main id=commentRoot> tag")


def _parse_attrs(interior):
    """Parse a tag's attribute text into an ordered [(name, value_or_None)] list.
    value is None for a boolean attribute; otherwise it is the unquoted string."""
    attrs = []
    for m in _ATTR_RE.finditer(interior):
        name = m.group(1)
        raw = m.group(2)
        if not name:
            continue
        if raw is None:
            attrs.append((name, None))
        elif raw[:1] in "\"'":
            attrs.append((name, raw[1:-1]))
        else:
            attrs.append((name, raw))
    return attrs


def _set_attr(attrs, name, value):
    for i, (k, _v) in enumerate(attrs):
        if k.lower() == name.lower():
            attrs[i] = (k, value)
            return
    attrs.append((name, value))


def _drop_attr(attrs, name):
    attrs[:] = [(k, v) for (k, v) in attrs if k.lower() != name.lower()]


def _build_main_tag(interior, key, label, source, generated=None):
    attrs = _parse_attrs(interior)
    _set_attr(attrs, "data-comment-key", key)
    _set_attr(attrs, "data-doc-label", label)
    if source is not None:
        _set_attr(attrs, "data-doc-source", source)
    else:
        _drop_attr(attrs, "data-doc-source")
    if generated is not None:
        _set_attr(attrs, "data-generated", generated)
    parts = ["<main"]
    for name, value in attrs:
        if value is None:
            parts.append(name)
        else:
            parts.append('%s="%s"' % (name, _html.escape(value, quote=True)))
    return " ".join(parts) + ">"


def make_document(template_html, content, key, label, source=None, generated=None):
    """Return a standalone commentable-html document built from `template_html`.

    Replaces the fragment between the CONTENT markers with `content` and sets the
    preceding content root's data-* attributes. Raises ValueError on a refused
    key or when the CONTENT markers / content root cannot be located.
    """
    k = (key or "").strip()
    if not k:
        raise ValueError("key must be a non-empty string")
    if k in REFUSED_KEYS:
        raise ValueError(
            'refusing the demo/example data-comment-key "%s" - give the document a '
            "unique key (validate.py fails a document that keeps a demo key)" % k)
    if not (label or "").strip():
        raise ValueError("label must be a non-empty string")

    if template_html.count(BEGIN_MARKER) != 1 or template_html.count(END_MARKER) != 1:
        raise ValueError("template is missing a unique CONTENT-BEGIN/CONTENT-END marker pair")
    begin_idx = template_html.index(BEGIN_MARKER)
    end_idx = template_html.index(END_MARKER)
    if end_idx <= begin_idx:
        raise ValueError("CONTENT-END marker precedes CONTENT-BEGIN marker")
    content_after_begin = begin_idx + len(BEGIN_MARKER)

    # The real content root is the LAST `<main id=commentRoot>` opening before the
    # CONTENT-BEGIN marker; earlier matches (e.g. the doc-comment decoy) are ignored.
    main_match = None
    for m in _MAIN_ROOT_RE.finditer(template_html, 0, begin_idx):
        main_match = m
    if main_match is None:
        raise ValueError('no <main id="commentRoot"> found before the CONTENT-BEGIN marker')

    main_start = main_match.start()
    tag_end = _tag_end(template_html, main_start)
    interior = template_html[main_start + len("<main"):tag_end]
    new_tag = _build_main_tag(interior, k, label, source, generated=generated)

    fragment = "\n\n" + content.strip("\n") + "\n\n"
    out = (
        template_html[:main_start]
        + new_tag
        + template_html[tag_end + 1:content_after_begin]
        + fragment
        + template_html[end_idx:]
    )
    # Best-effort: keep the browser tab / fallback label in sync with the doc label.
    out = _TITLE_RE.sub(lambda mo: mo.group(1) + _html.escape(label) + mo.group(2), out, count=1)
    return out


def _self_validate(html_out):
    """Validate `html_out` with validate.py. Returns a list of error strings, or
    None only when the validator module is genuinely unavailable (degrade gracefully)."""
    try:
        import validate as _validate
    except ImportError:
        return None
    fd, tmp = tempfile.mkstemp(suffix=".html", dir=os.getcwd())
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(html_out)
        errors, _warnings = _validate.validate(tmp)
        return errors
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _default_template():
    # tools/ lives directly under the skill root, next to dist/PORTABLE.html.
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dist", "PORTABLE.html")


def _derive_auto_key(seed):
    token = (seed or "").strip()
    if not token:
        raise ValueError("cannot derive an auto key from an empty logical id")
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return "cmh-" + digest[:12]


def resolve_key(key, label, key_from_source=None):
    value = (key or "").strip()
    if value and value.lower() != "auto":
        return value
    source = key_from_source if key_from_source is not None else label
    return _derive_auto_key(source)


def _read_file(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _read_content(source):
    if source == "-":
        # Read raw bytes and decode UTF-8 explicitly: text-mode stdin uses the locale
        # codepage on Windows and would mangle non-ASCII content piped into the tool.
        # Fall back to text mode for stdin substitutes (e.g. StringIO) that have no buffer.
        buffer = getattr(sys.stdin, "buffer", None)
        if buffer is not None:
            return buffer.read().decode("utf-8", errors="replace")
        return sys.stdin.read()
    return _read_file(source)


def main(argv):
    parser = argparse.ArgumentParser(
        prog="new_document.py",
        description="Create a standalone commentable-html document from a content fragment.")
    parser.add_argument("--content", required=True,
                        help="content fragment file, or '-' to read the fragment from stdin")
    parser.add_argument("--key", required=True,
                        help='unique data-comment-key for the content root, or "auto"')
    parser.add_argument("--key-from-source", default=None,
                        help="logical id used to derive --key auto (defaults to --label)")
    parser.add_argument("--label", required=True, help="data-doc-label (also used as the <title>)")
    parser.add_argument("--source", default=None, help="optional data-doc-source")
    parser.add_argument("--generated", default=None,
                        help="optional data-generated ISO-8601 timestamp for deterministic metadata")
    parser.add_argument("--template", default=None,
                        help="template to clone (default: the skill's dist/PORTABLE.html)")
    parser.add_argument("--out", default=None, help="output file (default: stdout)")
    args = parser.parse_args(argv[1:])

    template_path = args.template or _default_template()
    try:
        template_html = _read_file(template_path)
    except OSError as exc:
        sys.stderr.write("new_document: cannot read template: %s\n" % exc)
        return 1
    try:
        content = _read_content(args.content)
    except OSError as exc:
        sys.stderr.write("new_document: cannot read content: %s\n" % exc)
        return 1

    try:
        key = resolve_key(args.key, args.label, key_from_source=args.key_from_source)
        out_html = make_document(template_html, content, key, args.label, args.source, generated=args.generated)
    except ValueError as exc:
        sys.stderr.write("new_document: %s\n" % exc)
        return 2

    errors = _self_validate(out_html)
    if errors:
        sys.stderr.write("new_document: the generated document does not validate:\n")
        for e in errors:
            sys.stderr.write("  - %s\n" % e)
        return 1

    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="") as fh:
            fh.write(out_html)
        sys.stderr.write("new_document: wrote %s\n" % args.out)
    else:
        sys.stdout.write(out_html)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
