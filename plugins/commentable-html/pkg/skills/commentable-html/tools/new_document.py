#!/usr/bin/env python3
"""Create a ready-to-use commentable-html document from a content fragment.

A commentable document's CSS/HTML/JS regions are byte-for-byte the template's; the
only per-document parts are the content root's data-* attributes and the fragment
between the CONTENT markers. Re-emitting the whole template by hand to place a new
document wastes tokens and risks corrupting a layer region. This helper instead clones
the dist template and surgically swaps only those two per-document parts:

  - the fragment BETWEEN the CONTENT-BEGIN/CONTENT-END markers, and
  - `data-comment-key` / `data-doc-label` / `data-doc-source` on the
    `<main id="commentRoot">` that IMMEDIATELY precedes CONTENT-BEGIN.

The content root is anchored off the unique CONTENT markers, never off the first
`<main id="commentRoot">` in the file - the template's top-of-file documentation
comment contains a second, decoy `<main id="commentRoot">` (the "my-doc"
example) that must stay untouched.

Output mode. New documents are NonPortable by DEFAULT: the ~89KB of layer CSS/JS is
referenced from the companion commentable-html.{css,js,assets.js} files instead of
inlined, so the document (and every regeneration of it) is small and cheap to iterate
on. A NonPortable file needs its companions reachable at the referenced path, so it is
for local iteration; run tools/export_portable.py (or the in-page Export as Portable)
to get a single self-contained file to share. Pass --portable to emit an inlined
single file directly instead.

For NonPortable output the companion references default to a relative path from --out to
the skill's dist/ folder; use --assets-href PREFIX to reference them elsewhere, or
--copy-assets to copy the three files next to --out and reference them by bare name (a
movable self-contained folder). Writing NonPortable to stdout (no --out) falls back to
bare companion names, which assume the companions sit next to the eventual file.

Usage (run from the skill root):
    python tools/new_document.py --content body.html --key auto --label "My Report" --out r.html
    python tools/new_document.py --content body.html --key auto --label "My Report" --portable --out r.html
    echo '<section><h2 id="a">Hi</h2></section>' | \
        python tools/new_document.py --content - --key auto --label "My Report" --portable --out out.html

The result is self-validated with validate.py before it is written; validation
errors print to stderr and exit 1. Output goes to stdout unless --out is given.
"""
import argparse
import hashlib
import html as _html
import os
import re
import shutil
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

# The layer companion files a NonPortable document references. Ordered longest-suffix
# first so a literal ref rewrite never clips commentable-html.js out of the .assets.js
# name. Filenames are version-agnostic (each document stamps its own version meta).
COMPANIONS = ("commentable-html.css", "commentable-html.assets.js", "commentable-html.js")

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


def _find_active_root(template_html):
    """Return (begin_idx, end_idx, main_start, tag_end) for a template: the CONTENT
    marker offsets and the active content root (the LAST `<main id=commentRoot>` opening
    before CONTENT-BEGIN; earlier matches such as the doc-comment decoy are ignored).
    Raises ValueError when the markers or the content root cannot be located."""
    if template_html.count(BEGIN_MARKER) != 1 or template_html.count(END_MARKER) != 1:
        raise ValueError("template is missing a unique CONTENT-BEGIN/CONTENT-END marker pair")
    begin_idx = template_html.index(BEGIN_MARKER)
    end_idx = template_html.index(END_MARKER)
    if end_idx <= begin_idx:
        raise ValueError("CONTENT-END marker precedes CONTENT-BEGIN marker")
    main_match = None
    for m in _MAIN_ROOT_RE.finditer(template_html, 0, begin_idx):
        main_match = m
    if main_match is None:
        raise ValueError('no <main id="commentRoot"> found before the CONTENT-BEGIN marker')
    main_start = main_match.start()
    tag_end = _tag_end(template_html, main_start)
    return begin_idx, end_idx, main_start, tag_end


def active_root_attrs(html):
    """Return the active content root's attributes as an ordered [(name, value)] list.
    value is None for a boolean attribute; otherwise the unquoted string."""
    _begin, _end, main_start, tag_end = _find_active_root(html)
    return _parse_attrs(html[main_start + len("<main"):tag_end])


def make_document(template_html, content, key, label, source=None, generated=None,
                  allow_reserved_key=False):
    """Return a standalone commentable-html document built from `template_html`.

    Replaces the fragment between the CONTENT markers with `content` and sets the
    preceding content root's data-* attributes. Raises ValueError on a refused
    key or when the CONTENT markers / content root cannot be located. Pass
    `allow_reserved_key=True` only when re-stamping a document that legitimately
    already carries a reserved key (e.g. export_portable.py preserving the source
    document's key), never for a brand-new document.
    """
    k = (key or "").strip()
    if not k:
        raise ValueError("key must be a non-empty string")
    if k in REFUSED_KEYS and not allow_reserved_key:
        raise ValueError(
            'refusing the demo/example data-comment-key "%s" - give the document a '
            "unique key (validate.py fails a document that keeps a demo key)" % k)
    if not (label or "").strip():
        raise ValueError("label must be a non-empty string")

    begin_idx, end_idx, main_start, tag_end = _find_active_root(template_html)
    content_after_begin = begin_idx + len(BEGIN_MARKER)

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


def _self_validate(html_out, base_dir=None):
    """Validate `html_out` with validate.py. Returns a list of error strings, or
    None only when the validator module is genuinely unavailable (degrade gracefully).
    base_dir is where NonPortable companion refs resolve for the existence check (the
    file's final directory), or None to check structure only and defer companion
    resolution to when the placed file is validated."""
    try:
        import validate as _validate
    except ImportError:
        return None
    fd, tmp = tempfile.mkstemp(suffix=".html", dir=os.getcwd())
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(html_out)
        errors, _warnings = _validate.validate(tmp, base_dir=base_dir)
        return errors
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _skill_root():
    # tools/ lives directly under the skill root, next to dist/.
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _default_template(nonportable=False):
    name = "NONPORTABLE.html" if nonportable else "PORTABLE.html"
    return os.path.join(_skill_root(), "dist", name)


def _join_ref(prefix, name):
    return name if not prefix else prefix.rstrip("/") + "/" + name


def _repoint_companions(html, prefix):
    """Rewrite the NonPortable template's bare companion references to `prefix`/<name>.
    A falsy prefix leaves the bare names untouched (companions expected alongside)."""
    if not prefix:
        return html
    for name in COMPANIONS:
        html = html.replace('href="%s"' % name, 'href="%s"' % _join_ref(prefix, name), 1)
        html = html.replace('src="%s"' % name, 'src="%s"' % _join_ref(prefix, name), 1)
    return html


def _companion_prefix(out_path, assets_href, copy_assets):
    """Resolve (prefix, note, validate_base) for a NonPortable document's companion
    references.

    - --copy-assets  -> bare names ("") and the caller copies the files next to --out;
                        validate_base None (existence is guaranteed by the copy);
    - --assets-href  -> the given prefix verbatim; validate_base None (a caller-managed
                        path we cannot resolve at generation time);
    - --out (default)-> a relative path from --out's directory to the skill's dist/,
                        and validate_base = --out's directory so the existence check
                        genuinely confirms the refs resolve to the skill dist/;
    - stdout default -> bare names with a note; validate_base None (no final directory).
    """
    if copy_assets:
        if not out_path:
            raise ValueError("--copy-assets needs --out FILE (cannot copy companions next to a stream)")
        return "", None, None
    if assets_href is not None:
        return assets_href.rstrip("/"), None, None
    if not out_path:
        return "", ("nonportable output to stdout references the companions by bare name; keep "
                    "commentable-html.{css,js,assets.js} next to the saved file, or pass --assets-href"), None
    out_dir = os.path.dirname(os.path.abspath(out_path))
    dist = os.path.join(_skill_root(), "dist")
    rel = os.path.relpath(dist, out_dir)
    return rel.replace(os.sep, "/"), None, out_dir


def _copy_companions(dest_dir):
    dist = os.path.join(_skill_root(), "dist")
    for name in COMPANIONS:
        shutil.copyfile(os.path.join(dist, name), os.path.join(dest_dir, name))


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
        description="Create a commentable-html document from a content fragment "
                    "(NonPortable by default; pass --portable for a single self-contained file).")
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
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--nonportable", action="store_true",
                      help="produce a NonPortable document (the default): references the companion "
                           "commentable-html.{css,js,assets.js} instead of inlining them; cheap to "
                           "iterate on, export to Portable to share")
    mode.add_argument("--portable", action="store_true",
                      help="produce a single self-contained Portable file (inlines the layer)")
    parser.add_argument("--assets-href", default=None,
                        help="NonPortable only: path prefix used to reference the companions "
                             "(default: a relative path from --out to the skill's dist/)")
    parser.add_argument("--copy-assets", action="store_true",
                        help="NonPortable only: copy the three companions next to --out and "
                             "reference them by bare name (a movable self-contained folder)")
    parser.add_argument("--template", default=None,
                        help="template to clone (default: the skill's dist/NONPORTABLE.html, "
                             "or dist/PORTABLE.html with --portable)")
    parser.add_argument("--out", default=None, help="output file (default: stdout)")
    args = parser.parse_args(argv[1:])

    nonportable = not args.portable
    if args.template:
        template_path = args.template
    else:
        template_path = _default_template(nonportable=nonportable)
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

    prefix = ""
    copy_here = False
    validate_base = None
    if nonportable:
        try:
            prefix, note, validate_base = _companion_prefix(args.out, args.assets_href, args.copy_assets)
        except ValueError as exc:
            sys.stderr.write("new_document: %s\n" % exc)
            return 2
        copy_here = args.copy_assets
        if note:
            sys.stderr.write("new_document: %s\n" % note)

    try:
        key = resolve_key(args.key, args.label, key_from_source=args.key_from_source)
        out_html = make_document(template_html, content, key, args.label, args.source, generated=args.generated)
    except ValueError as exc:
        sys.stderr.write("new_document: %s\n" % exc)
        return 2

    if nonportable and not args.template:
        out_html = _repoint_companions(out_html, prefix)

    errors = _self_validate(out_html, base_dir=validate_base)
    if errors:
        sys.stderr.write("new_document: the generated document does not validate:\n")
        for e in errors:
            sys.stderr.write("  - %s\n" % e)
        return 1

    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="") as fh:
            fh.write(out_html)
        if copy_here:
            try:
                _copy_companions(os.path.dirname(os.path.abspath(args.out)))
            except OSError as exc:
                sys.stderr.write("new_document: wrote %s but could not copy companions: %s\n"
                                 % (args.out, exc))
                return 1
        sys.stderr.write("new_document: wrote %s\n" % args.out)
    else:
        sys.stdout.write(out_html)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
