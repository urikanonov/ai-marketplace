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

Output mode. Every new document is SHAREABLE: one self-contained file with the layer
CSS/JS inlined, ready to share the moment it is written. There is no mode to choose,
so `--nonshareable` is accepted and ignored and `--shareable` merely names the default.
A legacy NonShareable document (the layer referenced from the companion
commentable-html.{css,js,assets.js} files beside it) is still OPENED, VALIDATED and
FINALIZED forever; only creating a new one has gone away. Build one deliberately -
chiefly for the compatibility suite - with --template <dist>/NONSHAREABLE.html, and
migrate an existing one with tools/authoring/to_shareable.py.

For that explicit NonShareable output the companion references default to absolute
file:// URLs that point at this installed skill's dist/ folder. The generated HTML can
move anywhere on the same machine and still find the shared companions. Use
--assets-relative to opt back into a relative path from --out to the skill's dist/
folder for a movable folder bundle, --assets-href PREFIX to reference companions
elsewhere, or --copy-assets to copy the three files next to --out and reference them
by bare name.

Usage (run from the skill root):
    python tools/new_document.py --content body.html --key auto --label "My Report" --kind report --out r.html
    python tools/new_document.py --content body.html --key auto --label "My Report" --kind report --shareable --out r.html
    echo '<section><h2 id="a">Hi</h2></section>' | \
        python tools/new_document.py --content - --key auto --label "My Report" --kind report --shareable --out out.html

--kind declares the document type (report, plan, slides, board, or generic). report and
plan require a top-level <h1> title (one is auto-added from --label when the fragment has
none); slides and board do not. Syntax highlighting is baked into raw language-labelled code
blocks by default (opt out with --no-highlight) so a created document is never raw. The result
is self-validated with validate.py before it is written; validation errors print to stderr and
exit 1, and validator warnings print to stderr (the document is still not finished - it MUST be
finalized and strict-validated before it is shared). When the document cannot be CHECKED at all
(an unimportable or crashing validator, a `validate` module resolved from outside this skill, or
a validator answering in an unexpected shape - i.e. a broken or partial install) the tool FAILS
CLOSED: nothing is written and it exits non-zero naming the actual cause. Pass
--allow-unvalidated-output to knowingly accept unchecked output; that flag never suppresses a
real validation failure. Output goes to stdout unless --out is given.
"""
import argparse
import hashlib
import html as _html
import importlib.util
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tools/ root
import _toolpath  # noqa: E402
_toolpath.ensure()
_TOOLS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import _brand_profile  # noqa: E402
import _browser_attrs  # noqa: E402
import doc_stamp  # noqa: E402
import recommend_kind  # noqa: E402

BEGIN_MARKER = "<!-- BEGIN: commentable-html - CONTENT (agent edits ONLY between these markers) -->"
END_MARKER = "<!-- END: commentable-html - CONTENT -->"

# Keys that must never become a live content root: the two demo roots the
# template ships and the "my-doc" documentation-example key. validate.py fails a
# document whose active root keeps a demo key, so refusing them up front keeps
# this tool from ever producing a document validate rejects.
REFUSED_KEYS = frozenset({
    "commentable-html-demo",
    "commentable-html-nonshareable-demo",
    "commentable-html-nonportable-demo",
    "my-doc",
})

# A NonShareable document carries this exact bootstrap comment (the same anchor upgrade.py
# uses). The mode is derived from the resolved TEMPLATE rather than a flag, so the two can
# never disagree.
NONSHAREABLE_MARKER = "<!-- BEGIN: commentable-html - NONSHAREABLE BOOTSTRAP -->"
# Documents built before the Portable -> Shareable rename carry the LEGACY spelling, so both
# anchors are recognized.
LEGACY_NONSHAREABLE_MARKER = "<!-- BEGIN: commentable-html - NONPORTABLE BOOTSTRAP -->"
NONSHAREABLE_MARKERS = (NONSHAREABLE_MARKER, LEGACY_NONSHAREABLE_MARKER)
# The pre-rename name of this constant; `test_new_document.py` and user scripts read it across the
# module boundary, so it aliases the LEGACY string and keeps its exact former value.
NONPORTABLE_MARKER = LEGACY_NONSHAREABLE_MARKER


def has_nonshareable_marker(html):
    """True when the document/template carries the companion bootstrap anchor, either spelling."""
    return any(marker in (html or "") for marker in NONSHAREABLE_MARKERS)

# The layer companion files a NonShareable document references. Ordered longest-suffix
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
# Kinds that render as boxed section cards: their top-level <h2> blocks are auto-wrapped
# in <section> so a created document is never a flat, off-brand page (validate.py's
# check_section_wrapping (CMH-VAL-14) warns on the unwrapped case). Only report/plan are
# auto-wrapped; a generic document is left as authored (its author still gets the warning).
_SECTION_CARD_KINDS = frozenset({"report", "plan"})
# HTML void elements never open a nesting level, so they must not shift the top-level depth
# used to decide whether the fragment already carries its own document title.
_VOID_ELEMENTS = frozenset((
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr"))
_LEDE_CLASS_RE = re.compile(r'(^|\s)cmh-lede(\s|$)')


class _TitleDetector(_browser_attrs.BrowserTagNames):
    """Detect a genuine, rendered document title at the TOP level of a content fragment:
    a top-level <h1> or a top-level element carrying the cmh-lede class. Parsing (rather
    than a raw-text scan) means an <h1> inside an HTML comment, <script>, or <style> is not
    seen as a tag, and the depth check means a nested h1/lede deep in the body does not
    count as the document's own title."""

    # The SHARED bounded TEXT decode (CMH-VAL-21): an oversized numeric character reference
    # in prose resolves to U+FFFD instead of raising, so this tool reads the same document
    # every validator parse reads (issue #946).
    goahead = _browser_attrs.text_goahead(_browser_attrs.BrowserTagNames.goahead)

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
        tag = self._browser_tag(tag)
        self._check_top_level(tag, attrs)
        if tag not in _VOID_ELEMENTS:
            self.depth += 1

    def handle_startendtag(self, tag, attrs):
        self._check_top_level(self._browser_tag(tag), attrs)

    def handle_endtag(self, tag):
        if self._browser_tag(tag) not in _VOID_ELEMENTS and self.depth > 0:
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
    # ASCII-only name folding, as a browser folds an attribute name (CMH-VAL-21 clause 7).
    target = _browser_attrs.ascii_lower(name)
    for i, (k, _v) in enumerate(attrs):
        if _browser_attrs.ascii_lower(k) == target:
            attrs[i] = (k, value)
            return
    attrs.append((name, value))


def _drop_attr(attrs, name):
    target = _browser_attrs.ascii_lower(name)
    attrs[:] = [(k, v) for (k, v) in attrs if _browser_attrs.ascii_lower(k) != target]


def _build_main_tag(interior, key, label, source, generated=None):
    attrs = _parse_attrs(interior)
    _set_attr(attrs, "data-comment-key", key)
    _set_attr(attrs, "data-doc-label", label)
    if source is not None:
        _set_attr(attrs, "data-doc-source", doc_stamp.source_basename(source))
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


def _kind_hint_filename(args):
    if args.content != "-":
        return args.content
    return args.source or args.out


def _warn_kind_mismatch(kind, content, filename=None):
    warning = recommend_kind.warning_for_kind(kind, content, filename=filename)
    if warning:
        sys.stderr.write(warning + "\n")


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
    is to distinguish "checked and bad" from "could not check". The origin is checked BEFORE
    the import, so an unrelated `validate` earlier on sys.path is refused without executing
    its module body; an already-imported module is re-checked by its `__file__`.
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
            _toolpath.warn_missing_tool("validate", "self-validation of the new document")
            return None, "the sibling 'validate' tool could not be imported (%s: %s)" % (
                type(exc).__name__, _safe_text(exc))
    origin = _origin_of(module, "__file__")
    if not _contained(origin):
        return None, ("the imported 'validate' module is %s, not this skill's "
                      "tools/validate/validate.py" % (_describe(origin),))
    return module, None


def _self_validate_result(html_out, base_dir=None):
    """Validate `html_out` with validate.py.

    Returns ((errors, warnings), None), or (None, reason it could not be CHECKED at all).
    A "could not check" is deliberately NOT reported as an empty error list: returning
    (None, None) here used to read as "no errors, no warnings" in main() and write the
    document unvalidated on exactly the broken or partial install this check exists for.
    base_dir is where NonShareable companion refs resolve for the existence check (the
    file's final directory), or None to check structure only and defer companion
    resolution to when the placed file is validated."""
    module, reason = _load_validator()
    if module is None:
        return None, reason
    # The temp file location does not affect validation: base_dir is passed explicitly,
    # so companion refs never resolve against the temp file's directory. Use the system
    # temp dir (not os.getcwd(), which may be read-only, e.g. C:\Windows\System32).
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(suffix=".html")
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(html_out)
        outcome = module.validate(tmp, base_dir=base_dir)
    except Exception as exc:  # noqa: BLE001
        # A validator that crashes, or a temp dir that cannot be written, means the check did
        # not happen - the same "could not be checked" signal, so it takes the same gate.
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
        # Checking the MEMBERS matters as much as the arity: a `(None, None)` would satisfy a
        # bare 2-tuple test and then read as "no errors, no warnings", i.e. fail-open again.
        return None, "the validator returned an unexpected result (%s)" % (_safe_repr(outcome),)
    return outcome, None


def _self_validate(html_out, base_dir=None):
    """(errors, warnings) when the document could be checked, else None."""
    return _self_validate_result(html_out, base_dir)[0]


def _skill_root():
    return _toolpath.SKILL_ROOT


def _default_template(nonshareable=False):
    name = _toolpath.NONSHAREABLE_TEMPLATE if nonshareable else _toolpath.SHAREABLE_TEMPLATE
    return _toolpath.dist_template(name, root=_skill_root())


def _join_ref(prefix, name):
    return name if not prefix else prefix.rstrip("/") + "/" + name


def _repoint_companions(html, prefix):
    """Rewrite the NonShareable template's bare companion references to `prefix`/<name>.
    A falsy prefix leaves the bare names untouched (companions expected alongside)."""
    if not prefix:
        return html
    for name in COMPANIONS:
        html = html.replace('href="%s"' % name, 'href="%s"' % _join_ref(prefix, name), 1)
        html = html.replace('src="%s"' % name, 'src="%s"' % _join_ref(prefix, name), 1)
    return html


def _has_bare_companion_refs(html):
    """True when every companion is referenced by BARE name, the shape _repoint_companions
    rewrites. That is what makes a template one this tool knows how to place, wherever it
    was copied from."""
    return all('href="%s"' % name in html or 'src="%s"' % name in html for name in COMPANIONS)


def _file_url_prefix(path):
    return Path(os.path.abspath(path)).resolve().as_uri()


def _companion_prefix(out_path, assets_href, copy_assets, assets_relative=False):
    """Resolve (prefix, validate_base) for a NonShareable document's companion
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


def resolve_output_path(out, force=False):
    if not out or force:
        return out
    path = Path(out)
    if not path.exists():
        return out
    parent = path.parent
    stem = path.stem
    suffix = path.suffix
    index = 2
    while True:
        candidate = parent / ("%s-%d%s" % (stem, index, suffix))
        if not candidate.exists():
            return os.fspath(candidate)
        index += 1


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
        description="Create a self-contained Shareable commentable-html document from a content "
                    "fragment (Shareable is the only mode generated).",
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
    parser.add_argument("--source", default=None,
                        help="optional data-doc-source (directory components are stripped)")
    parser.add_argument("--generated", default=None,
                        help="optional data-generated ISO-8601 timestamp for deterministic metadata")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--nonshareable", "--nonportable", action="store_true", dest="nonshareable",
                      help="DEPRECATED and ignored: this skill no longer generates NonShareable "
                           "documents. Existing ones keep working forever - migrate one with "
                           "tools/authoring/to_shareable.py, or pass --template <dist>/"
                           "NONSHAREABLE.html to build a legacy document deliberately "
                           "(--nonportable is the accepted legacy spelling)")
    mode.add_argument("--shareable", "--portable", action="store_true", dest="shareable",
                      help="accepted for compatibility and now the default: a single "
                           "self-contained Shareable file (inlines the layer). --portable is "
                           "the accepted legacy spelling")
    parser.add_argument("--assets-href", default=None,
                        help="NonShareable only: path prefix used to reference the companions "
                             "(default: an absolute file:// URL to the skill's dist/)")
    parser.add_argument("--assets-relative", action="store_true",
                        help="NonShareable only: reference companions by a relative path from "
                             "--out to the skill's dist/ (old movable-folder behavior)")
    parser.add_argument("--copy-assets", action="store_true",
                        help="NonShareable only: copy the three companions next to --out and "
                             "reference them by bare name (a movable self-contained folder)")
    parser.add_argument("--template", default=None,
                        help="template to clone (default: the skill's dist/SHAREABLE.html; pass "
                             "dist/NONSHAREABLE.html to build a legacy document deliberately)")
    parser.add_argument("--out", default=None, help="output file (default: stdout)")
    parser.add_argument("--force", action="store_true",
                        help="overwrite --out if it exists instead of writing a suffixed sibling")
    parser.add_argument("--no-title", action="store_true",
                        help="do not prepend a document title header (by default a visible "
                             "<h1> from --label is added when the fragment has none)")
    parser.add_argument("--no-highlight", action="store_true",
                        help="do not bake syntax highlighting into raw language-labelled code "
                             "blocks (baking is ON by default so a created document is never raw)")
    parser.add_argument("--no-wrap-sections", action="store_true",
                        help="do not wrap bare top-level <h2> blocks in <section> for report/plan "
                             "documents (wrapping is ON by default so cards render; ignored for "
                             "other kinds)")
    parser.add_argument("--brand", default=None,
                        help="optional brand.json profile that stamps validated --cp-* theme "
                             "tokens and local data-URI font faces")
    parser.add_argument("--session-id", default=None,
                        help="AI session id of the agent creating this document, stamped as "
                             "provenance and copyable from the footer (default: auto-detected "
                             "from the environment, e.g. COPILOT_AGENT_SESSION_ID)")
    parser.add_argument("--agent", default=None,
                        help="producing agent slug (e.g. copilot, claude) shown in the footer "
                             "copy tooltip; default: inferred from which session env var matched")
    parser.add_argument("--no-session-id", action="store_true",
                        help="do not stamp the creating AI session id (stamping is ON by default "
                             "when a session id is available from --session-id or the environment)")
    parser.add_argument("--no-stats", action="store_true",
                        help="do not bake the section/word/reading-time overview strip for "
                             "report/plan documents (baking is ON by default; ignored for other kinds)")
    parser.add_argument("--allow-unvalidated-output", action="store_true",
                        help="write the document even when it could not be CHECKED at all - an "
                             "unimportable or crashing validator, a 'validate' module resolved "
                             "from outside this skill, or a validator that answers in an "
                             "unexpected shape. Off by default: this tool's guarantee is that "
                             "what it writes validates, and silently dropping that guarantee on "
                             "a broken install is the wrong direction. It never suppresses a "
                             "real validation failure.")
    args = parser.parse_args(argv[1:])
    out_path = resolve_output_path(args.out, force=args.force)

    # Shareable is the ONLY mode this skill generates. The mode now follows the RESOLVED TEMPLATE
    # rather than a flag: the default is dist/SHAREABLE.html, and a caller that genuinely needs a
    # legacy NonShareable document (the compatibility test suite, mostly) asks for it explicitly
    # with --template dist/NONSHAREABLE.html. Deriving the mode from the template it is actually
    # built from means the two can never disagree.
    #
    # NonShareable documents are still OPENED, VALIDATED and FINALIZED forever, and the
    # NonShareable runtime and its companions stay shipped for exactly that reason - only
    # CREATING one by default goes away. `to_shareable.py` migrates an existing one.
    if args.template:
        template_path = _toolpath.resolve_template_path(args.template)
    else:
        template_path = _default_template(nonshareable=False)
    try:
        template_html = _read_file(template_path)
    except OSError as exc:
        sys.stderr.write("new_document: cannot read template: %s\n" % exc)
        return 1
    nonshareable = has_nonshareable_marker(template_html)
    # --template is now the ONLY way to ask for a NonShareable document, so "a template was
    # passed" no longer implies "a CUSTOM template the caller owns". Recognize the template by
    # what it CONTAINS: one carrying the bare companion references this tool knows how to
    # repoint is ours to handle (repointing plus the existence check), wherever it lives - a
    # staged or vendored copy of NONSHAREABLE.html is still NONSHAREABLE.html. Only a template
    # whose references we do not recognize stays the caller's responsibility. Deciding this from
    # the PATH silently shipped bare refs with no companions beside the output, and exited 0.
    custom_template = bool(args.template) and not _has_bare_companion_refs(template_html)
    try:
        content = _read_content(args.content)
    except OSError as exc:
        sys.stderr.write("new_document: cannot read content: %s\n" % exc)
        return 1
    _warn_kind_mismatch(args.kind, content, filename=_kind_hint_filename(args))
    if not args.no_title and args.kind not in _NO_AUTO_TITLE_KINDS:
        content = ensure_doc_title(content, args.label)
    # Wrap bare top-level <h2> blocks in <section> for the card-rendering kinds, so a
    # created report/plan is never a flat page. Wrapping runs after the title is prepended
    # (the title stays above the cards) and before injection. Opt out with --no-wrap-sections.
    if args.kind in _SECTION_CARD_KINDS and not args.no_wrap_sections:
        try:
            import wrap_sections
            content, _wrapped = wrap_sections.wrap_fragment(content)
        except ImportError:
            _toolpath.warn_missing_tool("wrap_sections", "section wrapping")

    prefix = ""
    copy_here = False
    validate_base = None
    if nonshareable:
        selected_asset_modes = sum(1 for x in (args.assets_href is not None, args.copy_assets, args.assets_relative) if x)
        if selected_asset_modes > 1:
            sys.stderr.write("new_document: choose only one of --assets-href, --copy-assets, or --assets-relative\n")
            return 2
        try:
            prefix, validate_base = _companion_prefix(out_path, args.assets_href, args.copy_assets,
                                                      assets_relative=args.assets_relative)
        except ValueError as exc:
            sys.stderr.write("new_document: %s\n" % exc)
            return 2
        copy_here = args.copy_assets
        if custom_template:
            # A custom template's companion references are the caller's responsibility:
            # we do not rewrite them and cannot assume they resolve to the skill dist/,
            # so defer the companion existence check to when the placed file is validated.
            validate_base = None
    elif args.copy_assets or args.assets_href is not None or args.assets_relative:
        sys.stderr.write("new_document: --copy-assets / --assets-href / --assets-relative are ignored with --shareable "
                         "(a Shareable file inlines the layer and references no companions)\n")

    if nonshareable and not custom_template:
        # Repoint the TEMPLATE, before the caller's content is injected. Repointing the assembled
        # document rewrote the first `src="commentable-html.js"` it found, and the real runtime
        # reference sits AFTER the content region - so a document whose own content demonstrates
        # that tag had its authored markup rewritten while the real reference stayed bare.
        template_html = _repoint_companions(template_html, prefix)

    try:
        key = resolve_key(args.key, args.label, key_from_source=args.key_from_source,
                          source=args.source, out=out_path)
        out_html = make_document(template_html, content, key, args.label, args.source,
                                 generated=args.generated, kind=args.kind)
    except ValueError as exc:
        sys.stderr.write("new_document: %s\n" % exc)
        return 2

    # Bake syntax highlighting into raw language-labelled code blocks so a created document is never
    # raw. Baking used to live only in the separate, manual finalize step, so a document that skipped
    # finalize shipped with monochrome code (the notes-feature-plan.html defect). Opt out with
    # --no-highlight for parity with finalize.py.
    if not args.no_highlight:
        try:
            import highlight_document
            out_html, _highlighted = highlight_document.highlight_document(out_html)
        except ImportError:
            _toolpath.warn_missing_tool("highlight_document", "syntax highlighting")

    # Bake the section/word/reading-time overview strip for report/plan documents so a created
    # plan/report always opens with its size at a glance. Opt out with --no-stats.
    if args.kind in _SECTION_CARD_KINDS and not args.no_stats:
        try:
            import doc_stats
            out_html = doc_stats.rewrite_html(out_html)
        except ImportError:
            _toolpath.warn_missing_tool("doc_stats", "the document stats strip")

    # Stamp the creation time so the runtime can tell a produced-but-never-validated document apart
    # from one that was strict-validated (validate.py stamps commentable-html-validated on a clean
    # pass). Use --generated when supplied so metadata stays deterministic.
    try:
        import doc_stamp
        out_html = doc_stamp.stamp_created(out_html, when=args.generated)
        if not args.no_session_id:
            sid, agent = args.session_id, args.agent
            if not sid:
                sid, detected_agent = doc_stamp.detect_session()
                if agent is None:
                    agent = detected_agent
            out_html = doc_stamp.stamp_session(out_html, sid, agent=agent)
    except ImportError:
        _toolpath.warn_missing_tool("doc_stamp", "the creation and session-id stamps")

    brand_warnings = []
    try:
        out_html, brand_warnings = _brand_profile.apply_brand(out_html, args.brand)
    except _brand_profile.BrandProfileError as exc:
        sys.stderr.write("new_document: %s\n" % exc)
        return 2

    result, reason = _self_validate_result(out_html, base_dir=validate_base)
    if result is None:
        # The document could not be CHECKED (a broken or partial install), which is not the
        # same as being invalid. Writing it anyway would drop this tool's one guarantee
        # precisely where something is already wrong, so fail closed unless the caller opted
        # in knowingly.
        if not args.allow_unvalidated_output:
            sys.stderr.write(
                "new_document: the generated document could not be self-validated - %s - so "
                "nothing was written. Reinstall or re-extract the skill, or pass "
                "--allow-unvalidated-output to write it unchecked.\n" % reason)
            return 1
        sys.stderr.write("new_document: WARNING - writing a document that was not "
                         "self-validated (%s).\n" % reason)
        warnings = []
    else:
        errors, warnings = result
        if errors:
            sys.stderr.write("new_document: the generated document does not validate:\n")
            for e in errors:
                sys.stderr.write("  - %s\n" % e)
            return 1
    # Surface validator warnings (they used to be discarded). A warning here means the document is
    # valid but not finished - it MUST still be finalized and strict-validated before it is shared.
    for w in list(warnings or []) + brand_warnings:
        sys.stderr.write("new_document: warning: %s\n" % w)

    if out_path:
        # Copy companions BEFORE writing the HTML, so a copy failure never leaves a
        # written document that references companions missing from its folder.
        if copy_here:
            try:
                _copy_companions(os.path.dirname(os.path.abspath(out_path)))
            except OSError as exc:
                sys.stderr.write("new_document: could not copy companions next to %s: %s\n"
                                 % (out_path, exc))
                return 1
        try:
            mode = "w" if args.force else "x"
            with open(out_path, mode, encoding="utf-8", newline="") as fh:
                fh.write(out_html)
        except OSError as exc:
            sys.stderr.write("new_document: cannot write %s: %s\n" % (out_path, exc))
            return 1
        sys.stderr.write("new_document: wrote %s\n" % out_path)
    else:
        sys.stdout.write(out_html)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
