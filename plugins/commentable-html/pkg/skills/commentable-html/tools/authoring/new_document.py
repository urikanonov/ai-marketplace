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
`<main id="commentRoot">` in the file, so an earlier decoy root left in an HTML
comment (an authoring example) is ignored and only the real, last root is edited.

Output mode. New documents are NonPortable by DEFAULT: the ~89KB of layer CSS/JS is
referenced from the companion commentable-html.{css,js,assets.js} files instead of
inlined, so the document (and every regeneration of it) is small and cheap to iterate
on. A NonPortable file needs its companions reachable at the referenced path, so it is
for local iteration. To get a single self-contained file to share, regenerate with
--portable (safe when the document has no in-browser comments yet) or use the in-page
Export as Portable button; there is no CLI export because a tool cannot read the
browser localStorage where in-browser comments live. Pass --portable to emit an
inlined single file directly instead.

For NonPortable output the companion references default to absolute file:// URLs that
point at this installed skill's dist/ folder. The generated HTML can move anywhere on
the same machine and still find the shared companions. Use --assets-relative to opt
back into a relative path from --out to the skill's dist/ folder for a movable folder
bundle, --assets-href PREFIX to reference companions elsewhere, or --copy-assets to
copy the three files next to --out and reference them by bare name.

Usage (run from the skill root):
    python tools/new_document.py --content body.html --key auto --label "My Report" --kind report --out r.html
    python tools/new_document.py --content body.html --key auto --label "My Report" --kind report --portable --out r.html
    echo '<section><h2 id="a">Hi</h2></section>' | \
        python tools/new_document.py --content - --key auto --label "My Report" --kind report --portable --out out.html

--kind declares the document type (report, plan, slides, board, or generic). report and
plan require a top-level <h1> title (one is auto-added from --label when the fragment has
none); slides and board do not. The result is self-validated with validate.py before it is
written; validation errors print to stderr and exit 1. Output goes to stdout unless --out is given.
"""
import argparse
import hashlib
import html as _html
import html.parser as _html_parser
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tools/ root
import _toolpath  # noqa: E402
_toolpath.ensure()

BEGIN_MARKER = "<!-- BEGIN: commentable-html - CONTENT (agent edits ONLY between these markers) -->"
END_MARKER = "<!-- END: commentable-html - CONTENT -->"

# Keys that must never become a live content root: the two demo roots the
# template ships and the "my-doc" documentation-example key. validate.py fails a
# document whose active root keeps a demo key, so refusing them up front keeps
# this tool from ever producing a document validate rejects.
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
_KIND_META_RE = re.compile(
    r'(<meta\s+name="commentable-html-kind"\s+content=")[^"]*(")', re.IGNORECASE)

# Document kinds this tool can stamp. validate._DOC_KINDS is the source of truth;
# test_new_document asserts these stay in sync so they cannot silently diverge.
DOC_KINDS = ("report", "plan", "slides", "board", "generic")
# Kinds for which no document <h1> is auto-added: a slide deck or a board has no title.
_NO_AUTO_TITLE_KINDS = frozenset({"slides", "board"})
# HTML void elements never open a nesting level, so they must not shift the top-level depth
# used to decide whether the fragment already carries its own document title.
_VOID_ELEMENTS = frozenset((
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr"))
_LEDE_CLASS_RE = re.compile(r'(^|\s)cmh-lede(\s|$)')


class _TitleDetector(_html_parser.HTMLParser):
    """Detect a genuine, rendered document title at the TOP level of a content fragment:
    a top-level <h1> or a top-level element carrying the cmh-lede class. Parsing (rather
    than a raw-text scan) means an <h1> inside an HTML comment, <script>, or <style> is not
    seen as a tag, and the depth check means a nested h1/lede deep in the body does not
    count as the document's own title."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.found = False

    def _check_top_level(self, tag, attrs):
        if self.depth != 0 or self.found:
            return
        if tag == "h1":
            self.found = True
            return
        cls = dict(attrs).get("class") or ""
        if _LEDE_CLASS_RE.search(cls):
            self.found = True

    def handle_starttag(self, tag, attrs):
        self._check_top_level(tag, attrs)
        if tag not in _VOID_ELEMENTS:
            self.depth += 1

    def handle_startendtag(self, tag, attrs):
        self._check_top_level(tag, attrs)

    def handle_endtag(self, tag):
        if tag not in _VOID_ELEMENTS and self.depth > 0:
            self.depth -= 1


def _has_active_title(content):
    """True if `content` already carries a rendered top-level <h1> or cmh-lede header."""
    if not content:
        return False
    det = _TitleDetector()
    try:
        det.feed(content)
        det.close()
    except Exception:
        # A malformed fragment cannot be trusted to already carry a title; prepend one.
        return False
    return det.found


def ensure_doc_title(content, label):
    """Return `content` with a visible document title prepended when it has none.

    A generated document should show a heading. If the fragment already opens with a
    rendered top-level <h1> or lede header, it is left untouched; otherwise a themed lede
    header carrying the label as an <h1> is prepended so the document is never title-less."""
    if _has_active_title(content or ""):
        return content
    header = ('<header class="cmh-lede">\n  <h1>%s</h1>\n</header>'
              % _html.escape((label or "").strip()))
    body = (content or "").strip("\n")
    return header + ("\n\n" + body if body else "")


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
                  allow_reserved_key=False, kind=None):
    """Return a standalone commentable-html document built from `template_html`.

    Replaces the fragment between the CONTENT markers with `content` and sets the
    preceding content root's data-* attributes. When `kind` is given it also stamps the
    <meta name="commentable-html-kind"> so the document declares its kind. Raises ValueError
    on a refused key or when the CONTENT markers / content root cannot be located. Pass
    `allow_reserved_key=True` only when re-stamping a document that legitimately
    already carries a reserved key (a caller re-stamping an existing document),
    never for a brand-new document.
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
    if kind is not None:
        out = _set_kind_meta(out, kind)
    return out


def _set_kind_meta(html, kind):
    """Set the <meta name="commentable-html-kind"> content to `kind`. If the template has
    no such meta (a custom template), insert one into <head> so every generated document
    declares its kind."""
    new_html, n = _KIND_META_RE.subn(lambda m: m.group(1) + kind + m.group(2), html, count=1)
    if n:
        return new_html
    tag = '<meta name="commentable-html-kind" content="%s" />' % kind
    m = re.search(r"<head[^>]*>", html, re.IGNORECASE)
    if m:
        return html[:m.end()] + "\n" + tag + html[m.end():]
    return html


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
    # The temp file location does not affect validation: base_dir is passed explicitly,
    # so companion refs never resolve against the temp file's directory. Use the system
    # temp dir (not os.getcwd(), which may be read-only, e.g. C:\Windows\System32).
    fd, tmp = tempfile.mkstemp(suffix=".html")
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
    return _toolpath.SKILL_ROOT


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


def _file_url_prefix(path):
    return Path(os.path.abspath(path)).resolve().as_uri()


def _companion_prefix(out_path, assets_href, copy_assets, assets_relative=False):
    """Resolve (prefix, validate_base) for a NonPortable document's companion
    references.

    - --copy-assets  -> bare names ("") and the caller copies the files next to --out;
                        validate_base None (existence is guaranteed by the copy);
    - --assets-href  -> the given prefix verbatim; validate_base None (a caller-managed
                        path we cannot resolve at generation time);
    - default        -> an absolute file:// URL to the skill's dist/ folder;
                        validate_base None (the URL itself is absolute);
    - --assets-relative
                     -> a relative path from --out's directory to the skill's dist/,
                        and validate_base = --out's directory so the existence check
                        genuinely confirms the refs resolve to the skill dist/;
                        requires --out because a stream has no stable folder.
    """
    if copy_assets:
        if not out_path:
            raise ValueError("--copy-assets needs --out FILE (cannot copy companions next to a stream)")
        return "", None
    if assets_href is not None:
        # Return the prefix verbatim - _join_ref trims a trailing "/" without losing a
        # bare root "/" (rstrip here would turn "/" into "" and drop the prefix).
        return assets_href, None
    dist = os.path.join(_skill_root(), "dist")
    if not assets_relative:
        return _file_url_prefix(dist), None
    if not out_path:
        raise ValueError("--assets-relative needs --out FILE (cannot compute a relative companion path for a stream)")
    out_dir = os.path.dirname(os.path.abspath(out_path))
    try:
        rel = os.path.relpath(dist, out_dir)
    except ValueError:
        # Windows raises when --out is on a different drive/mount than the skill dist/.
        raise ValueError("cannot compute a relative companion path (--out is on a different "
                         "drive than the skill); use --assets-href PREFIX or --copy-assets")
    return rel.replace(os.sep, "/"), out_dir


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


def resolve_key(key, label, key_from_source=None, source=None, out=None):
    """Resolve the final data-comment-key.

    An explicit key is used as-is. `--key auto` derives a stable, collision-resistant
    key from the document's IDENTITY, not its label (two distinct documents can share a
    label, and a label-derived key would leak comments across them). The seed precedence
    is: an explicit --key-from-source logical id, then --source (the doc's declared
    source), then the --out path. With none of these - a stdout document with no
    source - auto cannot be made collision-free, so an explicit --key (or --source) is
    required rather than silently reusing a label-derived key.
    """
    value = (key or "").strip()
    if value and value.lower() != "auto":
        return value
    seed = None
    if key_from_source is not None and key_from_source.strip():
        seed = key_from_source.strip()
    elif source is not None and source.strip():
        seed = source.strip()
    elif out is not None and str(out).strip():
        seed = os.path.abspath(str(out).strip())
    if not seed:
        raise ValueError(
            '--key auto needs a stable document identity: pass --out, --source, or '
            '--key-from-source. A bare --label is not unique across documents, so it '
            "cannot be a collision-free key; give the document an explicit --key instead.")
    return _derive_auto_key(seed)


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
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Create a commentable-html document from a content fragment "
                    "(NonPortable by default; pass --portable for a single self-contained file).",
        epilog=(
            "Trust boundary: the --content fragment is treated as TRUSTED HTML and is copied into\n"
            "the document verbatim - new_document.py does NOT sanitize it. The runtime protects only\n"
            "reviewer-supplied data (it escapes/textContents comment text and metadata, validates\n"
            "comment ids against SAFE_ID_RE, and escapes '<' in the embeddedComments JSON); it does\n"
            "not neutralize scripts or event handlers in the authored content. If any part of the\n"
            "fragment comes from an untrusted source, sanitize it yourself before passing it in."))
    parser.add_argument("--content", required=True,
                        help="content fragment file, or '-' to read the fragment from stdin")
    parser.add_argument("--key", required=True,
                        help='unique data-comment-key for the content root, or "auto" to derive a '
                             'stable key from --out/--source/--key-from-source (not from --label)')
    parser.add_argument("--key-from-source", default=None,
                        help="explicit logical id used to derive --key auto; requires a stable "
                             "identity and does not fall back to --label")
    parser.add_argument("--label", required=True, help="data-doc-label (also used as the <title>)")
    parser.add_argument("--kind", required=True, choices=DOC_KINDS,
                        help="document kind (%s); report and plan require an <h1> title, "
                             "slides and board do not" % ", ".join(DOC_KINDS))
    parser.add_argument("--source", default=None, help="optional data-doc-source")
    parser.add_argument("--generated", default=None,
                        help="optional data-generated ISO-8601 timestamp for deterministic metadata")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--nonportable", action="store_true",
                      help="produce a NonPortable document (the default): references the companion "
                           "commentable-html.{css,js,assets.js} instead of inlining them; cheap to "
                           "iterate on, movable on this machine, export to Portable to share")
    mode.add_argument("--portable", action="store_true",
                      help="produce a single self-contained Portable file (inlines the layer)")
    parser.add_argument("--assets-href", default=None,
                        help="NonPortable only: path prefix used to reference the companions "
                             "(default: an absolute file:// URL to the skill's dist/)")
    parser.add_argument("--assets-relative", action="store_true",
                        help="NonPortable only: reference companions by a relative path from "
                             "--out to the skill's dist/ (old movable-folder behavior)")
    parser.add_argument("--copy-assets", action="store_true",
                        help="NonPortable only: copy the three companions next to --out and "
                             "reference them by bare name (a movable self-contained folder)")
    parser.add_argument("--template", default=None,
                        help="template to clone (default: the skill's dist/NONPORTABLE.html, "
                             "or dist/PORTABLE.html with --portable)")
    parser.add_argument("--out", default=None, help="output file (default: stdout)")
    parser.add_argument("--no-title", action="store_true",
                        help="do not prepend a document title header (by default a visible "
                             "<h1> from --label is added when the fragment has none)")
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
    if not args.no_title and args.kind not in _NO_AUTO_TITLE_KINDS:
        content = ensure_doc_title(content, args.label)

    prefix = ""
    copy_here = False
    validate_base = None
    if nonportable:
        selected_asset_modes = sum(1 for x in (args.assets_href is not None, args.copy_assets, args.assets_relative) if x)
        if selected_asset_modes > 1:
            sys.stderr.write("new_document: choose only one of --assets-href, --copy-assets, or --assets-relative\n")
            return 2
        try:
            prefix, validate_base = _companion_prefix(args.out, args.assets_href, args.copy_assets,
                                                      assets_relative=args.assets_relative)
        except ValueError as exc:
            sys.stderr.write("new_document: %s\n" % exc)
            return 2
        copy_here = args.copy_assets
        if args.template:
            # A custom template's companion references are the caller's responsibility:
            # we do not rewrite them and cannot assume they resolve to the skill dist/,
            # so defer the companion existence check to when the placed file is validated.
            validate_base = None
    elif args.copy_assets or args.assets_href is not None or args.assets_relative:
        sys.stderr.write("new_document: --copy-assets / --assets-href / --assets-relative are ignored with --portable "
                         "(a Portable file inlines the layer and references no companions)\n")

    try:
        key = resolve_key(args.key, args.label, key_from_source=args.key_from_source,
                          source=args.source, out=args.out)
        out_html = make_document(template_html, content, key, args.label, args.source,
                                 generated=args.generated, kind=args.kind)
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
        # Copy companions BEFORE writing the HTML, so a copy failure never leaves a
        # written document that references companions missing from its folder.
        if copy_here:
            try:
                _copy_companions(os.path.dirname(os.path.abspath(args.out)))
            except OSError as exc:
                sys.stderr.write("new_document: could not copy companions next to %s: %s\n"
                                 % (args.out, exc))
                return 1
        try:
            with open(args.out, "w", encoding="utf-8", newline="") as fh:
                fh.write(out_html)
        except OSError as exc:
            sys.stderr.write("new_document: cannot write %s: %s\n" % (args.out, exc))
            return 1
        sys.stderr.write("new_document: wrote %s\n" % args.out)
    else:
        sys.stdout.write(out_html)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
