#!/usr/bin/env python3
"""Add the commentable-html layer to an existing HTML document.

The tool injects the same layer regions that new_document.py emits, wires a
single content root, validates the result, and writes only after validation
succeeds. Use upgrade.py for files that already contain commentable-html regions.
"""
import argparse
import html as _html
from html.parser import HTMLParser
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tools/ root
import _toolpath  # noqa: E402
_toolpath.ensure()

import _atomic_io  # noqa: E402
import _brand_profile  # noqa: E402
import _browser_attrs  # noqa: E402
import _favicon  # noqa: E402
import doc_stamp  # noqa: E402
import new_document  # noqa: E402
import recommend_kind  # noqa: E402
import upgrade  # noqa: E402
try:
    import highlight_document as _highlight_document  # noqa: E402
except ImportError:  # pragma: no cover
    _highlight_document = None
    _toolpath.warn_missing_tool("highlight_document", "syntax highlighting")
try:
    import generate_toc as _generate_toc  # noqa: E402
except ImportError:  # pragma: no cover
    _generate_toc = None
    _toolpath.warn_missing_tool("generate_toc", "the table of contents")
try:
    import doc_stats as _doc_stats  # noqa: E402
except ImportError:  # pragma: no cover
    _doc_stats = None
    _toolpath.warn_missing_tool("doc_stats", "the document stats strip")


VOID = frozenset((
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
))
OPTIONAL_END_TAGS = frozenset((
    "caption", "colgroup", "dd", "dt", "li", "optgroup", "option", "p",
    "rp", "rt", "tbody", "td", "tfoot", "th", "thead", "tr",
))

LAYER_IDS = {"commentableHtmlLayer", "handledCommentIds", "embeddedComments"}
_KIND_META_NAME = "commentable-html-kind"
CSS_COLLISION_RE = re.compile(r"--cp-[A-Za-z0-9_-]*|(?:[.#])cm-[A-Za-z0-9_-]+|color-scheme\s*:", re.I)
Z_INDEX_RE = re.compile(r"z-index\s*:\s*(-?\d+)", re.I)
SELECTOR_RE = re.compile(r"^(?:#[A-Za-z_][\w:.-]*|\.[A-Za-z_][\w:.-]*|[A-Za-z][\w:-]*)$")


class RetrofitError(ValueError):
    pass


class Element:
    def __init__(self, tag, attrs, start, start_end, self_closing=False):
        self.tag = tag
        self.attrs = attrs
        self.attr_map = _attrs_map(attrs)
        self.start = start
        self.start_end = start_end
        self.self_closing = self_closing
        self.end_start = None
        self.end_end = None


def _attrs_map(attrs):
    out = {}
    for name, value in attrs:
        # ASCII-only, as a browser folds an attribute name (CMH-VAL-21 clause 7).
        key = _browser_attrs.ascii_lower(name)
        if key not in out:
            out[key] = value if value is not None else ""
    return out


class _StructureParser(_browser_attrs.BrowserTagNames):
    # The SHARED bounded TEXT decode (CMH-VAL-21): an oversized numeric character reference
    # in prose resolves to U+FFFD instead of raising, so this tool reads the same document
    # every validator parse reads (issue #946).
    goahead = _browser_attrs.text_goahead(HTMLParser.goahead)

    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.text = text
        self.line_starts = _line_starts(text)
        self.stack = []
        self.elements = []
        self.heads = []
        self.bodies = []
        self.errors = []

    def _off(self):
        line, col = self.getpos()
        return self.line_starts[line - 1] + col

    def _tag_end(self, start):
        try:
            return new_document._tag_end(self.text, start) + 1
        except ValueError as exc:
            self.errors.append(str(exc))
            return start

    def handle_starttag(self, tag, attrs):
        tag = self._browser_tag(tag)
        start = self._off()
        end = self._tag_end(start)
        elem = Element(tag, attrs, start, end)
        self.elements.append(elem)
        if tag == "head":
            self.heads.append(elem)
        elif tag == "body":
            self.bodies.append(elem)
        if tag not in VOID:
            self.stack.append(elem)

    def handle_startendtag(self, tag, attrs):
        tag = self._browser_tag(tag)
        start = self._off()
        end = self._tag_end(start)
        elem = Element(tag, attrs, start, end, self_closing=True)
        elem.end_start = start
        elem.end_end = end
        self.elements.append(elem)
        if tag in ("head", "body"):
            self.errors.append("<%s/> is not a valid document container" % tag)

    def handle_endtag(self, tag):
        tag = self._browser_tag(tag)
        start = self._off()
        end = self.text.find(">", start)
        end = len(self.text) if end < 0 else end + 1
        if not self.stack:
            self.errors.append("unexpected </%s>" % tag)
            return
        idx = None
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i].tag == tag:
                idx = i
                break
        if idx is None:
            self.errors.append("unexpected </%s>" % tag)
            return
        implicit = self.stack[idx + 1:]
        if any(elem.tag not in OPTIONAL_END_TAGS for elem in implicit):
            self.errors.append("malformed HTML near </%s>" % tag)
            return
        closing = self.stack[idx:]
        self.stack = self.stack[:idx]
        elem = closing[0]
        elem.end_start = start
        elem.end_end = end
        for implicit in closing[1:]:
            implicit.end_start = start
            implicit.end_end = start


def _line_starts(text):
    starts = [0]
    pos = text.find("\n")
    while pos != -1:
        starts.append(pos + 1)
        pos = text.find("\n", pos + 1)
    return starts


def _parse_structure(text):
    parser = _StructureParser(text)
    try:
        parser.feed(text)
        parser.close()
    except Exception as exc:  # noqa: BLE001
        raise RetrofitError("malformed HTML: %s" % exc)
    if parser.errors:
        raise RetrofitError("malformed HTML: %s" % parser.errors[0])
    if len(parser.heads) != 1:
        raise RetrofitError("expected exactly one <head>, found %d" % len(parser.heads))
    if len(parser.bodies) != 1:
        raise RetrofitError("expected exactly one <body>, found %d" % len(parser.bodies))
    head = parser.heads[0]
    body = parser.bodies[0]
    if head.end_start is None or body.end_start is None:
        raise RetrofitError("missing closing </head> or </body>")
    if not (head.start < head.end_start < body.start):
        raise RetrofitError("expected <head> to close before <body>")
    return parser


def _read_utf8(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except UnicodeDecodeError as exc:
        raise RetrofitError("input must be valid UTF-8: %s" % exc)
    except OSError as exc:
        raise RetrofitError("cannot read input: %s" % exc)


def _detect_newline(path):
    """Return the input's dominant newline ('\\r\\n' or '\\n') from its raw bytes, so a
    Windows-authored (CRLF) host file keeps its line endings through the retrofit instead of
    being silently normalized to LF by the universal-newline reader."""
    with open(path, "rb") as fh:
        raw = fh.read()
    crlf = raw.count(b"\r\n")
    lf = raw.count(b"\n") - crlf
    return "\r\n" if crlf > lf else "\n"


def _write_atomic(path, text, copy_assets=False, newline="\n", source=None):
    # Follow a symlink to its target so the replace does not turn the LINK into a regular file
    # and strand the real document (matches _atomic_io.atomic_write). The staging file must sit
    # beside the REAL file (os.replace needs the same filesystem), but companions are resolved by
    # the browser against the URL the document is OPENED by, so they still go beside the path the
    # caller named.
    real_path = os.path.realpath(path)
    real_dir = os.path.dirname(os.path.abspath(real_path)) or "."
    asset_dir = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp_path = tempfile.mkstemp(prefix=".cmh-retrofit-", suffix=".html", dir=real_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline=newline) as fh:
            fh.write(text)
            # Flush all the way to the disk before the swap: the rename is only as durable as
            # the bytes it points at (see _atomic_io.fsync_file).
            _atomic_io.fsync_file(fh)
        if copy_assets:
            new_document._copy_companions(asset_dir)
        # mkstemp creates 0600 and os.replace carries the staged inode's mode to the target, so
        # retrofitting a 0644 host page in place would otherwise make it owner-only. A brand-new
        # --out file takes the source page's mode rather than a process default.
        _atomic_io.commit_staged(tmp_path, real_path, fallback=source)
        tmp_path = None
    finally:
        if tmp_path is not None and os.path.exists(tmp_path):
            _atomic_io.quiet_remove(tmp_path)


def _has_layer(text, parser):
    for region in upgrade.LAYER_REGIONS:
        if upgrade._region_marker_matches(text, "BEGIN", region) or upgrade._region_marker_matches(text, "END", region):
            return True
    if new_document.BEGIN_MARKER in text or new_document.END_MARKER in text:
        return True
    ids = {elem.attr_map.get("id") for elem in parser.elements}
    return bool(ids & LAYER_IDS)


def _region_block(template, name):
    begins = upgrade._region_marker_matches(template, "BEGIN", name)
    ends = upgrade._region_marker_matches(template, "END", name)
    if len(begins) != 1 or len(ends) != 1:
        raise RetrofitError("template region %s is missing or duplicated" % name)
    html_open = template.rfind("<!--", 0, begins[0].start())
    css_open = template.rfind("/*", 0, begins[0].start())
    open_pos = max(html_open, css_open)
    start = template.rfind("\n", 0, open_pos if open_pos >= 0 else begins[0].start()) + 1
    end = template.find("\n", ends[0].end())
    if end < 0:
        end = len(template)
    else:
        end += 1
    return template[start:end]


def _one_line(template, pattern, label):
    m = re.search(pattern, template, re.I)
    if not m:
        raise RetrofitError("template is missing %s" % label)
    return m.group(0).rstrip() + "\n"


def _nonshareable_theme_style(template):
    css_begins = upgrade._region_marker_matches(template, "BEGIN", "CSS")
    if len(css_begins) != 1:
        raise RetrofitError("nonshareable template CSS region is missing or duplicated")
    css_begin = css_begins[0]
    style_start = template.rfind("<style>", 0, css_begin.start())
    if style_start < 0:
        raise RetrofitError("nonshareable template is missing its theme style")
    style_open_end = template.find(">", style_start)
    if style_open_end < 0:
        raise RetrofitError("nonshareable template has an unterminated theme style tag")
    style_open_end += 1
    css_line_start = template.rfind("\n", 0, css_begin.start()) + 1
    raw = template[style_open_end:css_line_start]
    demo = raw.find("/* Demo page chrome.")
    if demo >= 0:
        raw = raw[:demo]
    return '<style data-cmh-theme-vars>\n%s\n</style>\n' % raw.strip()


def _template(shareable):
    path = new_document._default_template(nonshareable=not shareable)
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


# The bootstrap anchor pair, current spelling first. A template produced before the
# Portable -> Shareable rename carries only the legacy pair, so both are tried.
_BOOTSTRAP_ANCHORS = (
    ("<!-- BEGIN: commentable-html - NONSHAREABLE BOOTSTRAP -->",
     "<!-- END: commentable-html - NONSHAREABLE BOOTSTRAP -->"),
    ("<!-- BEGIN: commentable-html - NONPORTABLE BOOTSTRAP -->",
     "<!-- END: commentable-html - NONPORTABLE BOOTSTRAP -->"),
)


def _nonshareable_bootstrap_block(template):
    for begin, end in _BOOTSTRAP_ANCHORS:
        if begin in template and end in template:
            return _block_between(template, begin, end)
    raise RetrofitError("template is missing the NONSHAREABLE BOOTSTRAP block")


def _kind_meta_tag(kind):
    return '<meta name="commentable-html-kind" content="%s" />' % kind


def _find_kind_meta(parser):
    """Return the existing commentable-html-kind <meta> Element, order-independent, or None.

    Detection reads the parsed attribute map (not attribute order or a raw regex), so a host
    that already declares a kind meta - even with content before name - is found and REPLACED
    rather than duplicated by a second appended meta."""
    for elem in parser.elements:
        if elem.tag == "meta" and (elem.attr_map.get("name") or "").strip().lower() == _KIND_META_NAME:
            return elem
    return None


def _layer_parts(shareable, kind, include_kind=True):
    template = _template(shareable)
    head = ""
    head += _one_line(template, r'<meta\s+name="commentable-html-version"[^>]*>', "version meta")
    if include_kind:
        head += _kind_meta_tag(kind) + "\n"
    head += _one_line(template, r'<script\s+type="application/json"\s+id="commentableHtmlLayer"[^>]*>.*?</script>',
                      "layer descriptor")
    if shareable:
        head += _nonshareable_theme_style(_template(False))
        head += "<style>\n%s</style>\n" % _region_block(template, "CSS")
    else:
        head += _nonshareable_theme_style(template)
        head += _region_block(template, "CSS")
    body_top = ""
    if not shareable:
        body_top += _nonshareable_bootstrap_block(template)
    for name in ("HANDLED IDS", "EMBEDDED COMMENTS", "COMMENT UI"):
        body_top += _region_block(template, name)
    body_bottom = _region_block(template, "JS")
    return head, body_top, body_bottom


def _block_between(text, start_marker, end_marker):
    start = text.find(start_marker)
    end = text.find(end_marker)
    if start < 0 or end < 0 or end < start:
        raise RetrofitError("template block is missing: %s" % start_marker)
    end_line = text.find("\n", end)
    return text[start:(len(text) if end_line < 0 else end_line + 1)]


def _source_attr(args):
    return args.source if args.source is not None else args.file


def _resolve_key(args, out_path):
    return new_document.resolve_key(
        args.key,
        args.label,
        key_from_source="%s|%s" % (args.label, os.path.abspath(out_path)),
        source=_source_attr(args),
        out=out_path,
    )


def _root_tag(key, label, source, tag="main"):
    attrs = 'id="commentRoot" data-cmh-content-root data-comment-key="%s" data-doc-label="%s" data-doc-source="%s"' % (
        _html.escape(key, quote=True),
        _html.escape(label, quote=True),
        _html.escape(source, quote=True),
    )
    return "<%s %s>" % (tag, attrs)


def _edits_apply(text, edits):
    edits = [
        (index, start, end, repl)
        for index, (start, end, repl) in enumerate(edits)
    ]
    edits = sorted(edits, key=lambda item: (item[1], item[2], item[0]), reverse=True)
    last_start = len(text) + 1
    out = text
    for _index, start, end, repl in edits:
        if end > last_start:
            raise RetrofitError("internal edit overlap while retrofitting")
        out = out[:start] + repl + out[end:]
        last_start = start
    return out


def _start_tag_source(text, elem):
    return text[elem.start:elem.start_end]


def _split_start_tag(tag_source):
    inner = tag_source[1:-1].strip()
    if inner.endswith("/"):
        inner = inner[:-1].rstrip()
    bits = inner.split(None, 1)
    name = bits[0]
    rest = bits[1] if len(bits) > 1 else ""
    return name, rest


def _build_start_tag(tag_name, attrs):
    parts = ["<" + tag_name]
    for name, value in attrs:
        if value is None:
            parts.append(name)
        else:
            parts.append('%s="%s"' % (name, _html.escape(value, quote=True)))
    return " ".join(parts) + ">"


def _set_attr(attrs, name, value):
    new_document._set_attr(attrs, name, value)


def _drop_attr(attrs, name):
    new_document._drop_attr(attrs, name)


def _class_with_cm_skip(attrs):
    current = ""
    for name, value in attrs:
        if _browser_attrs.ascii_lower(name) == "class":
            current = value or ""
            break
    # The ORDERED shared reading, not `str.split()`: this REWRITES the attribute, so the tokens
    # have to go back in the order the author wrote them - and Python's split would also turn a
    # `class="a\u000bb"` (ONE class to a browser) into two real classes on the way through.
    classes = _browser_attrs.html_ws_tokens(current)
    if "cm-skip" not in classes:
        classes.append("cm-skip")
    _set_attr(attrs, "class", " ".join(classes))


def _replace_start_tag(text, elem, mutator):
    tag_name, attr_text = _split_start_tag(_start_tag_source(text, elem))
    attrs = new_document._parse_attrs(attr_text)
    mutator(attrs)
    return _build_start_tag(tag_name, attrs)


def _stamp_root_tag(text, elem, key, label, source):
    if elem.self_closing and elem.tag not in VOID:
        raise RetrofitError("--root-selector points at a self-closing non-void element; use an explicit closing tag")
    if elem.tag in VOID or elem.end_start is None:
        raise RetrofitError("--root-selector must point at a non-void element with a closing tag")
    if elem.end_start == elem.end_end:
        raise RetrofitError("--root-selector points at an implicitly closed element; use an explicit closing tag")

    def mutate(attrs):
        _set_attr(attrs, "id", "commentRoot")
        _set_attr(attrs, "data-cmh-content-root", None)
        _set_attr(attrs, "data-comment-key", key)
        _set_attr(attrs, "data-doc-label", label)
        _set_attr(attrs, "data-doc-source", source)

    return _replace_start_tag(text, elem, mutate)


def _add_cm_skip_tag(text, elem):
    return _replace_start_tag(text, elem, _class_with_cm_skip)


def _selector_list(raw):
    if not raw:
        return []
    selectors = [part.strip() for part in raw.split(",") if part.strip()]
    for selector in selectors:
        if not SELECTOR_RE.match(selector):
            raise RetrofitError("unsupported selector %r; use #id, .class, or a tag name" % selector)
    return selectors


def _matches_selector(elem, selector):
    if selector.startswith("#"):
        return elem.attr_map.get("id") == selector[1:]
    if selector.startswith("."):
        return selector[1:] in _browser_attrs.class_tokens(elem.attr_map.get("class"))
    # An HTML type selector matches ASCII-case-insensitively, as the element name folds.
    return elem.tag == _browser_attrs.ascii_lower(selector)


def _apply_skip_selectors(text, selectors):
    if not selectors:
        return text, []
    parser = _parse_structure(text)
    matches = {}
    warnings = []
    for selector in selectors:
        found = [elem for elem in parser.elements if _matches_selector(elem, selector)]
        if not found:
            warnings.append("skip selector %s matched no elements" % selector)
        for elem in found:
            if elem.tag in ("html", "head", "body"):
                raise RetrofitError("skip selector %s points at <%s>, which cannot be marked cm-skip" % (selector, elem.tag))
            matches[elem.start] = elem
    edits = []
    for elem in matches.values():
        if "cm-skip" in _browser_attrs.class_tokens(elem.attr_map.get("class")):
            continue
        edits.append((elem.start, elem.start_end, _add_cm_skip_tag(text, elem)))
    return _edits_apply(text, edits), warnings


def _root_selector(raw):
    if raw is None:
        return None
    if not re.match(r"^#[A-Za-z_][\w:.-]*$", raw):
        raise RetrofitError('--root-selector supports only a single #id selector, got "%s"' % raw)
    return raw[1:]


def _find_root(parser, root_id):
    found = [elem for elem in parser.elements if elem.attr_map.get("id") == root_id]
    if len(found) != 1:
        raise RetrofitError("--root-selector #%s matched %d elements" % (root_id, len(found)))
    return found[0]


def _active_comment_roots(parser):
    return [elem for elem in parser.elements if elem.attr_map.get("id") == "commentRoot"]


def _body_contains(body, elem):
    return body.start_end <= elem.start and elem.start_end <= body.end_start


def _body_has_main(parser, body):
    return any(elem.tag == "main" and _body_contains(body, elem) for elem in parser.elements)


def _insert_title_if_missing(text, head, label):
    head_text = text[head.start_end:head.end_start]
    if re.search(r"<title\b", head_text, re.I):
        return ""
    return "<title>%s</title>\n" % _html.escape(label)


def _insert_favicon_if_missing(text, head, template):
    """Return the template's favicon `<link rel="icon">` (with a trailing newline) when the host
    head declares none, else "". A retrofitted host often has no favicon, which would leave the
    browser tab showing the generic globe and trip the validator's favicon check; mirror
    _insert_title_if_missing and add the CMH favicon when it is absent. Detection matches the
    validator's semantics through the ONE shared reading (see tools/authoring/_favicon.py): a `rel`
    token exactly `icon` plus an href that survives the URL parser's end trim, so
    `apple-touch-icon` / `mask-icon` and an icon link whose href trims away do NOT count."""
    head_text = text[head.start_end:head.end_start]
    if _favicon.head_has_favicon(head_text):
        return ""
    tag = _favicon.template_favicon_tag(template)
    if not tag:
        raise RetrofitError("template is missing a favicon <link rel=\"icon\">")
    return tag + "\n"


def _collision_warnings(original):
    warnings = []
    if CSS_COLLISION_RE.search(original):
        warnings.append("host CSS appears to use --cp- variables, cm-* selectors, or color-scheme")
    high = [int(m.group(1)) for m in Z_INDEX_RE.finditer(original) if int(m.group(1)) >= 300]
    if high:
        warnings.append("host CSS has z-index >= 300; confirm the review UI is not covered")
    return warnings


def build_retrofit(html, args, out_path):
    html, skip_warnings = _apply_skip_selectors(html, _selector_list(args.skip_selectors))
    parser = _parse_structure(html)
    if _has_layer(html, parser):
        raise RetrofitError("this file already has commentable-html regions; use tools/upgrade.py instead")
    key = _resolve_key(args, out_path)
    if key in new_document.REFUSED_KEYS:
        raise RetrofitError('refusing the demo/example data-comment-key "%s"' % key)
    source = doc_stamp.source_basename(_source_attr(args))
    head = parser.heads[0]
    body = parser.bodies[0]
    existing_kind_meta = _find_kind_meta(parser)
    head_insert, body_top, body_bottom = _layer_parts(
        args.shareable, args.kind, include_kind=existing_kind_meta is None)
    title_insert = _insert_title_if_missing(html, head, args.label)
    favicon_insert = _insert_favicon_if_missing(html, head, _template(args.shareable))

    edits = [
        (head.end_start, head.end_start, "\n" + title_insert + favicon_insert + head_insert),
        (body.start_end, body.start_end, "\n" + body_top),
        (body.end_start, body.end_start, "\n" + body_bottom),
    ]

    root_id = _root_selector(args.root_selector)
    if root_id is None:
        existing_roots = _active_comment_roots(parser)
        if existing_roots:
            raise RetrofitError('active id="commentRoot" already exists; use --root-selector "#commentRoot" for an unlayered host root, or use upgrade.py for an already-layered file')
        body_inner = html[body.start_end:body.end_start]
        root_tag = "div" if _body_has_main(parser, body) else "main"
        root_open = _root_tag(key, args.label, source, tag=root_tag)
        wrapped = ("\n" + root_open + "\n" + new_document.BEGIN_MARKER + "\n"
                   + body_inner.strip("\n") + "\n" + new_document.END_MARKER + "\n</%s>\n" % root_tag)
        edits = [
            (head.end_start, head.end_start, "\n" + title_insert + favicon_insert + head_insert),
            (body.start_end, body.end_start, "\n" + body_top + wrapped + body_bottom + "\n"),
        ]
    else:
        root = _find_root(parser, root_id)
        if not _body_contains(body, root):
            raise RetrofitError("--root-selector #%s is not inside <body>" % root_id)
        existing_roots = _active_comment_roots(parser)
        if existing_roots and not (len(existing_roots) == 1 and existing_roots[0].start == root.start):
            raise RetrofitError('another active id="commentRoot" already exists; refuse to create duplicate roots')
        edits.extend([
            (root.start, root.start_end, _stamp_root_tag(html, root, key, args.label, source)),
            (root.start_end, root.start_end, "\n" + new_document.BEGIN_MARKER + "\n"),
            (root.end_start, root.end_start, "\n" + new_document.END_MARKER + "\n"),
        ])

    # A host that already declares a kind meta gets that meta REPLACED with the requested kind
    # (the layer head insert omits its own kind meta in this case), so the result never carries
    # two kind metas with a conflicting effective kind.
    if existing_kind_meta is not None:
        edits.append((existing_kind_meta.start, existing_kind_meta.start_end, _kind_meta_tag(args.kind)))

    result = _edits_apply(html, edits)
    if not args.shareable:
        result = new_document._repoint_companions(result, args.assets_prefix)
    return result, skip_warnings + _collision_warnings(html)


def _validate_candidate(text, out_path, base_dir):
    out_dir = os.path.dirname(os.path.abspath(out_path)) or "."
    fd, tmp_path = tempfile.mkstemp(prefix=".cmh-retrofit-", suffix=".html", dir=out_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        import validate  # noqa: E402
        errors, warnings = validate.validate(tmp_path, base_dir=base_dir)
        return errors, warnings
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def _partition_val_warnings(warnings):
    """Split validator warnings into (fatal, advisory) for retrofit's hard-fail path.

    Two prefixes stay OUT of it: the never-blocking advisories every tool tolerates
    (`validate.ADVISORY_PREFIXES`, whose membership is CMH-VAL-18's business and is deliberately
    not restated here),
    plus retrofit's own long-standing carve-out for the theme-contrast near-miss/unresolved
    advisory (CMH-THEME-02), which other tools still treat as fatal. A bad-contrast ERROR is not
    a warning and continues to block the retrofit; every OTHER validator warning stays fatal,
    preserving retrofit's clean-result guarantee. `validate` is already a hard dependency of the
    surrounding flow (`_validate_candidate` imports it), so if it cannot be imported here we fail
    CLOSED rather than keep a second copy of the prefixes that could silently drift."""
    try:
        import validate
        prefixes = validate.ADVISORY_PREFIXES + (validate.ADVISORY_PREFIX,)
    except Exception:
        _toolpath.warn_missing_tool("validate", "advisory-warning classification")
        return list(warnings), []
    fatal, advisory = [], []
    for w in warnings:
        (advisory if isinstance(w, str) and w.startswith(prefixes) else fatal).append(w)
    return fatal, advisory


def main(argv):
    parser = argparse.ArgumentParser(
        prog="retrofit.py",
        description="Inject the commentable-html layer into an existing HTML file.",
    )
    parser.add_argument("file", help="existing HTML file to retrofit")
    parser.add_argument("--label", required=True, help="data-doc-label for the review bundle")
    parser.add_argument("--kind", required=True, choices=new_document.DOC_KINDS,
                        help="document kind (%s); report and plan require an <h1> title"
                             % ", ".join(new_document.DOC_KINDS))
    parser.add_argument("--key", default="auto", help='data-comment-key, or "auto" for a stable generated key')
    parser.add_argument("--source", default=None,
                        help="data-doc-source filename; defaults to the input filename")
    parser.add_argument("--out", default=None, help="output path; defaults to overwriting the input after validation")
    parser.add_argument("--root-selector", default=None, help='existing root to stamp, limited to a single "#id" selector')
    parser.add_argument("--skip-selectors", default="", help='comma-separated #id, .class, or tag selectors to mark class="cm-skip"')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--shareable", "--portable", action="store_true", dest="shareable",
                      help="accepted for compatibility and now the default: inline the layer "
                           "into one self-contained Shareable file (--portable is the accepted "
                           "legacy spelling)")
    mode.add_argument("--nonshareable", "--nonportable", action="store_true", dest="nonshareable",
                      help="produce a legacy NonShareable document that references the companion "
                           "commentable-html.{css,js,assets.js} instead of inlining them. New "
                           "documents are no longer generated this way; existing ones stay "
                           "supported, and tools/authoring/to_shareable.py migrates one "
                           "(--nonportable is the accepted legacy spelling)")
    parser.add_argument("--assets-relative", action="store_true", help="NonShareable only: reference companions by a relative path to skill dist/")
    parser.add_argument("--copy-assets", action="store_true", help="NonShareable only: copy companions next to the output")
    parser.add_argument("--assets-href", default=None, help="NonShareable only: companion path prefix")
    parser.add_argument("--no-highlight", action="store_true",
                        help="do not bake syntax highlighting into raw language-labelled code "
                             "blocks (baking is ON by default so a retrofitted document is never raw)")
    parser.add_argument("--brand", default=None,
                        help="optional brand.json profile that stamps validated --cp-* theme "
                             "tokens and local data-URI font faces")
    parser.add_argument("--no-stats", action="store_true",
                        help="do not bake the section/word/reading-time overview strip for "
                             "report/plan documents (baking is ON by default; ignored for other kinds)")
    args = parser.parse_args(argv[1:])

    out_path = args.out or args.file
    if not args.label.strip():
        sys.stderr.write("retrofit: --label must be non-empty\n")
        return 2
    selected_asset_modes = sum(1 for item in (args.assets_relative, args.copy_assets, args.assets_href is not None) if item)
    if args.shareable and selected_asset_modes:
        sys.stderr.write("retrofit: asset href options are NonShareable only\n")
        return 2
    if selected_asset_modes > 1:
        sys.stderr.write("retrofit: choose only one of --assets-relative, --copy-assets, or --assets-href\n")
        return 2
    # Shareable is the ONLY mode generated. A legacy NonShareable document is an EXPLICIT request:
    # --nonshareable, or one of the companion-href options, which only make sense in that mode.
    # Deriving the mode from what the caller actually asked for means --shareable (now the
    # default) can stay accepted without ever contradicting the file that gets written.
    args.shareable = not (args.nonshareable or selected_asset_modes)

    # Retrofitting rewrites args.file, which is the SAME artifact. The brand profile and the
    # templates it reads are not, so a destination that resolves to any of them would replace it
    # with the layered page (CMH-TOOL-23). SHAREABLE mode reads BOTH templates - the NonShareable
    # one supplies the theme variables (`_layer_parts`) - so both are listed. --copy-assets writes
    # three MORE destinations on fixed names beside the output, so each of those is checked too,
    # against args.file as well, since a companion landing on the page being retrofitted would
    # lose it.
    templates = [new_document._default_template(nonshareable=not args.shareable)]
    if args.shareable:
        templates.append(new_document._default_template(nonshareable=True))
    inputs = [args.brand] + templates
    if _atomic_io.refuse_aliased_output("retrofit", out_path, inputs):
        return 1
    if not args.shareable and args.copy_assets:
        asset_dir = os.path.dirname(os.path.abspath(out_path)) or "."
        for name in new_document.COMPANIONS:
            if _atomic_io.refuse_aliased_output(
                    "retrofit", os.path.join(asset_dir, name), inputs + [args.file],
                    what="the --copy-assets companion"):
                return 1

    try:
        if args.shareable:
            args.assets_prefix = ""
            validate_base = None
        else:
            args.assets_prefix, validate_base = new_document._companion_prefix(
                out_path,
                args.assets_href,
                args.copy_assets,
                assets_relative=args.assets_relative,
            )
        html = _read_utf8(args.file)
        newline = _detect_newline(args.file)
        warning = recommend_kind.warning_for_kind(args.kind, html, filename=args.file)
        if warning:
            sys.stderr.write(warning + "\n")
        result, warnings = build_retrofit(html, args, out_path)
        # Bake syntax highlighting into raw language-labelled code blocks so a retrofitted document
        # is never raw (opt out with --no-highlight).
        if not args.no_highlight and _highlight_document is not None:
            result, _ = _highlight_document.highlight_document(result)
        brand_warnings = []
        result, brand_warnings = _brand_profile.apply_brand(result, args.brand)
        warnings.extend(brand_warnings)
        # De-duplicate an author-numbered ordered-list .cm-toc so it is never double-numbered.
        if _generate_toc is not None:
            result, _ = _generate_toc.strip_toc_numbers(result)
        # Bake the section/word/reading-time overview strip for report/plan documents.
        if not args.no_stats and args.kind in new_document._SECTION_CARD_KINDS and _doc_stats is not None:
            try:
                result = _doc_stats.rewrite_html(result)
            except ValueError:
                pass  # no #commentRoot to anchor to; leave the document as built
        errors, val_warnings = _validate_candidate(result, out_path, validate_base)
    except RetrofitError as exc:
        sys.stderr.write("retrofit: %s\n" % exc)
        return 2
    except _brand_profile.BrandProfileError as exc:
        sys.stderr.write("retrofit: %s\n" % exc)
        return 2
    except ValueError as exc:
        sys.stderr.write("retrofit: %s\n" % exc)
        return 2
    except OSError as exc:
        sys.stderr.write("retrofit: %s\n" % exc)
        return 1

    for warning in warnings:
        sys.stderr.write("retrofit warning: %s\n" % warning)
    fatal_warnings, advisories = _partition_val_warnings(val_warnings)
    for advisory in advisories:
        sys.stderr.write("retrofit advisory (non-fatal): %s\n" % advisory)
    if errors or fatal_warnings:
        sys.stderr.write("retrofit: validation failed; target left unchanged:\n")
        for warning in fatal_warnings:
            sys.stderr.write("  WARNING: %s\n" % warning)
        for error in errors:
            sys.stderr.write("  ERROR: %s\n" % error)
        return 1

    try:
        _write_atomic(out_path, result, copy_assets=(not args.shareable and args.copy_assets), newline=newline,
                      source=args.file)
    except OSError as exc:
        sys.stderr.write("retrofit: cannot write %s: %s\n" % (out_path, exc))
        return 1
    print("retrofit: wrote %s" % out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
