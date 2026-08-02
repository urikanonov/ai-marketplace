#!/usr/bin/env python3
"""Migrate an existing NonShareable commentable-html document to a self-contained Shareable one.

Shareable is the ONLY mode this skill now GENERATES, but NonShareable documents created by earlier
releases must keep working indefinitely - there is no deprecation deadline, and the NonShareable
runtime and its companion files stay shipped for exactly that reason. This tool is the migration
path for an author who WANTS an existing NonShareable document to become self-contained: it inlines
the layer so the file no longer depends on `commentable-html.{css,js,assets.js}` sitting beside it.

It is the counterpart to `upgrade.py`, which deliberately REFUSES a NonShareable document (a
NonShareable file is upgraded by replacing its companions, not by swapping inline regions). Run
this first if you want such a document to become Shareable, then `upgrade.py` keeps it current.

What is preserved: the authored CONTENT region, the embedded comments, and the handled ids - the
whole point of migrating rather than regenerating is that review state travels with the document.

Usage:
  python tools/authoring/to_shareable.py <file.html> [more.html ...]
  python tools/authoring/to_shareable.py --check <file.html>     # report, write nothing
"""
import argparse
import io
import json
import os
import re
import sys
try:
    from urllib.parse import unquote as urlunquote
except ImportError:  # pragma: no cover - Python 2 style fallback, kept for parity with tools/
    from urllib import unquote as urlunquote
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tools/ root
import _toolpath  # noqa: E402
_toolpath.ensure()

import _atomic_io  # noqa: E402
import upgrade  # noqa: E402

# The companion files a NonShareable document references, and the element each is inlined into.
# HANDLED IDS, EMBEDDED COMMENTS and CONTENT are the document's own state and are never touched.
COMPANIONS = (
    ("commentable-html.css", "style"),
    ("commentable-html.js", "script"),
)

# `commentable-html.assets.js` is deliberately NOT inlined. It defines
# `window.__COMMENTABLE_ASSETS__`, a registry holding a SECOND full copy of the CSS and JS as
# strings, and it exists for exactly one purpose: to let the in-page "Export standalone" action
# turn a NonShareable document into a Shareable one without fetch() (which file:// blocks). Once
# this tool has done that conversion the registry is dead weight - a natively generated
# dist/SHAREABLE.html does not carry it either - so migrating drops its reference instead of
# inlining 937 KB of duplicated payload.
DROPPED_COMPANION = "commentable-html.assets.js"

_BOOTSTRAP_BEGIN = "<!-- BEGIN: commentable-html - NONSHAREABLE BOOTSTRAP -->"
_BOOTSTRAP_END = "<!-- END: commentable-html - NONSHAREABLE BOOTSTRAP -->"
# Documents produced before the Portable -> Shareable rename carry the legacy anchor pair and the
# legacy descriptor mode values. Both stay recognized so an existing document still migrates.
_LEGACY_BOOTSTRAP_BEGIN = "<!-- BEGIN: commentable-html - NONPORTABLE BOOTSTRAP -->"
_LEGACY_BOOTSTRAP_END = "<!-- END: commentable-html - NONPORTABLE BOOTSTRAP -->"
_BOOTSTRAP_ANCHORS = ((_BOOTSTRAP_BEGIN, _BOOTSTRAP_END),
                      (_LEGACY_BOOTSTRAP_BEGIN, _LEGACY_BOOTSTRAP_END))
_BOOTSTRAP_BEGINS = (_BOOTSTRAP_BEGIN, _LEGACY_BOOTSTRAP_BEGIN)
_BOOTSTRAP_ENDS = (_BOOTSTRAP_END, _LEGACY_BOOTSTRAP_END)
SHAREABLE_MODES = ("shareable", "portable")
NONSHAREABLE_MODES = ("nonshareable", "nonportable")


def is_nonshareable(html):
    """True when the document's LIVE layer descriptor declares the nonshareable mode.

    Deliberately not a substring test for the bootstrap marker: a migrated document can contain
    that text perfectly legitimately - authored prose about this skill quotes it, and inlined
    companion bytes may carry it - and reading it as the mode made a second run try to migrate an
    already-Shareable document, breaking the idempotency this tool promises. The descriptor is
    where the runtime and the validator read the mode from. A document with no parsable
    descriptor falls back to the marker, so a hand-made legacy file is still recognized.
    """
    m = _DESCRIPTOR_RE.search(_mask_comments(html))
    if m:
        try:
            mode = json.loads(html[m.start(3):m.end(3)]).get("mode")
        except ValueError:
            mode = None
        if mode in SHAREABLE_MODES or mode in NONSHAREABLE_MODES:
            return mode in NONSHAREABLE_MODES
    return upgrade.has_nonshareable_marker(html)


# The pre-rename name of this predicate, kept so an existing caller keeps working.
is_nonportable = is_nonshareable


def _strip_bootstrap_edit(html, span):
    """The (start, end, "") edit removing the NonShareable bootstrap block, or None.

    Anchored on the exact BEGIN/END comment pair and only OUTSIDE the authored CONTENT region:
    authored content can and does keep a literal, unescaped `NONSHAREABLE BOOTSTRAP` anchor pair
    verbatim (a document about this skill). Every anchor in this module is resolved against the
    document's ORIGINAL bytes, before any companion text is inlined, so untrusted `--dist` bytes
    can never move one.

    Either spelling is accepted on EITHER side, because a hand-edited or partially-migrated
    document can pair a legacy BEGIN with a current END and leaving that block behind would
    strand a dead companion watchdog. The block still has to be WELL FORMED: the END taken is the
    nearest one after the BEGIN, and a second BEGIN appearing before it means the two anchors
    belong to different blocks - that is refused rather than deleting everything between them.
    """
    starts = sorted(m.start() for begin in _BOOTSTRAP_BEGINS
                    for m in re.finditer(re.escape(begin), html))
    outside = [at for at in starts if at < span[0] or at >= span[1]]
    if not outside:
        return None
    start = outside[0]
    ends = [(html.find(end, start), len(end)) for end in _BOOTSTRAP_ENDS]
    ends = [(at, size) for at, size in ends if at != -1 and not (span[0] <= at < span[1])]
    if not ends:
        return None
    end, end_len = min(ends)
    if any(start < other < end for other in starts):
        return None
    return (start, _consume_eol(html, end + end_len), "")


_LOADER_NOTE = "<!-- commentable-html - layer loaded from companion files (nonshareable mode) -->"
_LEGACY_LOADER_NOTE = "<!-- commentable-html - layer loaded from companion files (nonportable mode) -->"
_LOADER_NOTES = (_LOADER_NOTE, _LEGACY_LOADER_NOTE)


def _loader_note_edits(html, span):
    """Edits removing the legacy loader note, outside CONTENT only.

    A whole-document replace deleted the author's own quotation of the note - the same silent
    corruption class as the mode rewrite that used to rewrite authored prose.
    """
    return [(m.start(), _consume_eol(html, m.end()), "")
            for note in _LOADER_NOTES
            for m in re.finditer(re.escape(note), html)
            if not (span[0] <= m.start() < span[1])]


def _consume_eol(html, at):
    """Extend `at` past a trailing line break, so removing an element leaves no blank line."""
    while at < len(html) and html[at] in "\r\n":
        at += 1
    return at


_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_RAW_TEXT_BODY_RE = re.compile(r"(<(script|style)\b[^>]*>)([\s\S]*?)(</\2\s*[^>]*>)", re.IGNORECASE)


def _blank(text):
    """Same-length filler that keeps newlines, so masking never shifts an offset."""
    return re.sub(r"[^\r\n]", " ", text)


def _mask_comments(html):
    """The document with HTML comment bodies blanked, offsets preserved.

    A document about this skill legitimately contains commented-out copies of the very elements
    this tool rewrites. Discovering anchors in the masked view - and applying the edits to the
    real bytes at the same offsets - is what stops a commented-out `<script src=...>` from being
    inlined while the live one is left behind.
    """
    return _COMMENT_RE.sub(lambda m: _blank(m.group(0)), html)


def _mask_markup(html):
    """`_mask_comments` plus raw-text bodies, for finding real ELEMENTS only."""
    masked = _mask_comments(html)
    return _RAW_TEXT_BODY_RE.sub(
        lambda m: m.group(1) + _blank(m.group(3)) + m.group(4), masked)


def _apply_edits(html, edits):
    """Apply non-overlapping (start, end, replacement) edits to the original bytes."""
    ordered = sorted((e for e in edits if e is not None), key=lambda e: e[0])
    for earlier, later in zip(ordered, ordered[1:]):
        if later[0] < earlier[1]:
            raise ValueError("internal: overlapping edits at %d and %d" % (earlier[0], later[0]))
    out = []
    at = 0
    for start, end, replacement in ordered:
        out.append(html[at:start])
        out.append(replacement)
        at = end
    out.append(html[at:])
    return "".join(out)


_DESCRIPTOR_RE = re.compile(
    r'(<script\b[^>]*\sid\s*=\s*(["\'])commentableHtmlLayer\2[^>]*>)([\s\S]*?)(</script>)',
    re.IGNORECASE)
_MODE_VALUE_RE = re.compile(r'("mode"\s*:\s*)"(?:nonshareable|nonportable)"')


def _mode_edit(html, masked, target_name):
    """The edit flipping the layer descriptor's mode to shareable, or None when already shareable.

    Two things went wrong with a lexical `str.replace` and are pinned by tests. Applied to the
    whole document it rewrote authored PROSE that quotes the descriptor (invisible, because the
    result still validated). Restricted to the descriptor but still byte-exact, it silently did
    NOTHING when the same JSON was formatted differently, and the migration reported success on
    a document that was still marked nonshareable. So: parse the descriptor, require exactly one
    mode transition, and re-parse to confirm the document really says what it now claims.

    `masked` is the comment-masked view, so a commented-out descriptor (a document about this
    skill quotes one) is never the one that gets switched.
    """
    found = list(_DESCRIPTOR_RE.finditer(masked))
    if not found:
        raise ValueError("%s has no live commentable-html layer descriptor; it may not be a "
                         "commentable-html document" % target_name)
    if len(found) > 1:
        raise ValueError("%s carries %d live layer descriptors; refusing to migrate an "
                         "ambiguous document" % (target_name, len(found)))
    m = found[0]
    body = html[m.start(3):m.end(3)]
    try:
        descriptor = json.loads(body)
    except ValueError:
        raise ValueError("%s has an unparsable layer descriptor; refusing to migrate it"
                         % target_name)
    if descriptor.get("mode") in SHAREABLE_MODES:
        return None
    if descriptor.get("mode") not in NONSHAREABLE_MODES:
        raise ValueError("%s declares an unknown layer mode %r; refusing to migrate it"
                         % (target_name, descriptor.get("mode")))
    swapped, count = _MODE_VALUE_RE.subn(r'\1"shareable"', body)
    if count != 1:
        raise ValueError("%s: expected exactly one descriptor mode to switch, found %d"
                         % (target_name, count))
    if json.loads(swapped).get("mode") != "shareable":
        raise ValueError("%s: the descriptor did not end up shareable; refusing to write"
                         % target_name)
    return (m.start(3), m.end(3), swapped)


# The CONTENT region's BEGIN marker carries a trailing note ("(agent edits ONLY between these
# markers)"), so it cannot use upgrade's strict region-marker matcher; it is still matched as a
# whole-line HTML COMMENT, which is what reviewer text can never forge (notes serialize '<' as
# \u003c). Authored content CAN carry such a comment - that makes the region ambiguous, and an
# ambiguous region is refused rather than guessed.
_CONTENT_BEGIN_LINE_RE = re.compile(
    r"^[ \t]*<!--[ \t]*BEGIN: commentable-html - CONTENT\b[^\n]*?-->[ \t]*\r?$", re.MULTILINE)


def _content_span(html, target_name):
    """(begin, end) offsets of the authored CONTENT region.

    Every companion reference this tool rewrites lives OUTSIDE that region - the CSS link in
    <head> BEFORE it, the scripts at the end of <body> AFTER it. Restricting rewrites to outside
    the span is what stops a document whose own content DEMONSTRATES the runtime (a literal
    `<script src="commentable-html.js"></script>` in prose) from having the 746 KB runtime
    spliced into the author's markup while the real reference is left dangling.

    The span therefore decides which occurrence is "the real one", so it is derived from
    line-anchored comment markers and required to be unique. Bare substring search was not
    enough: a reviewer NOTE quoting the marker text placed a fake END before the genuine BEGIN,
    the span collapsed, and the stylesheet was inlined into the author's markup instead.
    """
    starts = [m.start() for m in _CONTENT_BEGIN_LINE_RE.finditer(html)]
    if len(starts) != 1:
        raise ValueError("%s: expected exactly one CONTENT region BEGIN marker, found %d; "
                         "refusing to migrate an ambiguous document"
                         % (target_name, len(starts)))
    ends = upgrade._region_marker_matches(html, "END", "CONTENT")
    ends = [m for m in ends if m.start(1) > starts[0]]
    if len(ends) != 1:
        raise ValueError("%s: expected exactly one CONTENT region END marker after the BEGIN "
                         "marker, found %d; refusing to migrate an ambiguous document"
                         % (target_name, len(ends)))
    close = html.find("-->", ends[0].end(1))
    return (starts[0], (close + 3) if close != -1 else ends[0].end(1))


_COMPANION_ELEMENT_RE = {
    # A stylesheet companion is a <link>; a script companion is a <script src=...></script> pair.
    # The end tag is matched as `</script` plus anything up to `>`, not `</script>`: HTML lets an
    # end tag carry (ignored) attributes and trailing space, so `</script >` and `</script foo>`
    # both really close the element, and a regex that missed them would stop recognizing the
    # element (CodeQL "bad HTML filtering regexp").
    "style": re.compile(r"<link\b[^>]*>", re.IGNORECASE),
    "script": re.compile(r"<script\b[^>]*>[ \t\r\n]*</script\s*[^>]*>", re.IGNORECASE),
}
# `(?<![-\w])` so `data-href="commentable-html.css"` on an element pointing somewhere else is
# not read as the companion reference - `\b` matches inside `data-href`.
_URL_ATTR_RE = {
    "style": re.compile(r"""(?<![-\w])href\s*=\s*("([^"]*)"|'([^']*)'|([^\s>]+))""",
                        re.IGNORECASE),
    "script": re.compile(r"""(?<![-\w])src\s*=\s*("([^"]*)"|'([^']*)'|([^\s>]+))""",
                         re.IGNORECASE),
}


def _url_basename(value):
    """The file name a browser would fetch: query/fragment dropped, percent-decoding applied.

    A NonShareable document does NOT necessarily reference `commentable-html.css` by bare name.
    The CLI's own default was an absolute `file://` URL into the installed skill dist/, and
    `--assets-relative` / `--copy-assets` / `--assets-href PREFIX` each produce another prefix,
    while the runtime tolerates a `?v=` cache-buster. Matching the bare byte sequence refused
    exactly the documents this tool exists to rescue.
    """
    path = value.split("#", 1)[0].split("?", 1)[0]
    try:
        path = urlunquote(path)
    except Exception:
        pass
    return re.split(r"[\\/]", path)[-1]


def _companion_edit(html, masked, span, name, tag, replacement, target_name, required=True):
    """The edit rewriting the LIVE element that references companion `name`, or None.

    Matching is by the BASENAME of the URL the element points at, so every reference shape a
    legacy document can carry migrates. Candidates come from `masked` (comments and raw-text
    bodies blanked) because a document about this skill quotes these elements in prose and in
    commented-out examples, and rewriting one of those leaves the real reference behind. More
    than one LIVE reference means the document is ambiguous, and an ambiguous document that
    would be rewritten in place is refused rather than guessed at.
    """
    found = []
    for m in _COMPANION_ELEMENT_RE[tag].finditer(masked):
        if span[0] <= m.start() < span[1]:
            continue
        attr = _URL_ATTR_RE[tag].search(m.group(0))
        if not attr:
            continue
        value = next((g for g in attr.groups()[1:] if g is not None), "")
        if _url_basename(value).lower() == name.lower():
            found.append((m.start(), m.end()))
    if not found:
        if required:
            raise ValueError(
                "%s does not reference %s outside its CONTENT region; it may not be a "
                "NonShareable document built by this skill" % (target_name, name))
        return None
    if len(found) > 1:
        raise ValueError("%s carries %d live references to %s; refusing to migrate an "
                         "ambiguous document" % (target_name, len(found), name))
    start, end = found[0]
    if not replacement:
        end = _consume_eol(html, end)
    return (start, end, replacement)


def _raw_text_close_re(tag):
    """Matches what actually ends a raw-text element: `</tag` followed by a name-ending char."""
    return re.compile(r"</(%s)(?=[\s/>]|$)" % tag, re.IGNORECASE)


def _neutralize_raw_text_close(text, tag):
    """Escape any terminator for `tag` inside text that is about to become that element's body.

    Companion bytes are inserted verbatim, and `--dist` accepts any directory, so the CSS or JS
    being inlined is not necessarily the shipped one. A stylesheet carrying `</StYlE><script>`
    closed the element early and everything after it parsed as live markup - control of a
    STYLESHEET became script execution in a document holding authored content and reviewer
    comments. Escaping the slash is what the runtime's own Export-as-Shareable path does: it
    leaves the text meaning the same inside CSS or JS, and stops it ending the element.
    """
    return _raw_text_close_re(tag).sub(lambda m: "<\\/" + m.group(1), text)


def _inlined_element(name, tag, body, target_name):
    """The `<style>`/`<script>` element that replaces a companion reference.

    Inlining the COMPANION FILES is deliberate; copying the Shareable template's CSS/JS region
    inners instead silently broke the document, because those inners carry their own
    "BEGIN/END: commentable-html - CSS" banner text and the migrated file ended up with three
    copies of a region marker and failed validation.
    """
    body = _neutralize_raw_text_close(body, tag)
    if _raw_text_close_re(tag).search(body):
        raise ValueError("%s: could not neutralize a </%s terminator in %s"
                         % (target_name, tag, name))
    element = "style" if tag == "style" else "script"
    return "<%s>\n%s\n</%s>" % (element, body.strip("\n"), element)


_SURVIVING_COMPANION_RE = re.compile(
    r"<(?:link\b[^>]*(?<![-\w])href|script\b[^>]*(?<![-\w])src)\s*=\s*"
    r"""("([^"]*)"|'([^']*)'|([^\s>]+))""", re.IGNORECASE)


def _assert_self_contained(html, span, target_name):
    """Refuse to write a document that still references a companion outside CONTENT.

    The validator calls a document NonShareable if ANY companion reference survives, so a
    leftover one (an unusual element shape this tool did not rewrite) would produce a file that
    both claims shareable and still needs its companions - broken, and written over the user's
    only copy. Checking the RESULT rather than trusting the edits keeps that impossible.
    """
    masked = _mask_markup(html)
    for m in _SURVIVING_COMPANION_RE.finditer(masked):
        if span[0] <= m.start() < span[1]:
            continue
        value = next((g for g in m.groups()[1:] if g is not None), "")
        base = _url_basename(value).lower()
        if base.startswith("commentable-html") and base.endswith((".css", ".js")):
            raise ValueError(
                "%s would still reference the companion %s after migration; refusing to write a "
                "document that is not self-contained" % (target_name, base))


def to_shareable(target_html, layer, target_name="<target>"):
    """Return (new_html, changed). Raises ValueError on an unusable input.

    `layer` maps each companion file name to its text (see `read_layer`). An ALREADY-Shareable
    document is returned byte-identical with changed=False, so running this twice - or across a
    mixed directory - is safe and idempotent.

    Every anchor is resolved against the document's ORIGINAL bytes and the edits are applied in
    one pass, so no step can be aimed by what an earlier step inserted - the companion bytes are
    untrusted (`--dist` accepts any directory) and used to be inlined before later anchors were
    computed.
    """
    for marker in upgrade.REQUIRED_MARKERS:
        found = bool(upgrade.CONTENT_BEGIN_RE.search(target_html)) if marker == "CONTENT" \
            else bool(upgrade._region_marker_matches(target_html, "BEGIN", marker))
        if not found:
            raise ValueError(
                "%s is not a commentable-html document (missing '%s' region)"
                % (target_name, marker))
    if not is_nonshareable(target_html):
        return target_html, False

    span = _content_span(target_html, target_name)
    masked = _mask_comments(target_html)
    markup = _mask_markup(target_html)
    edits = [_strip_bootstrap_edit(target_html, span)]
    edits += _loader_note_edits(target_html, span)
    edits.append(_companion_edit(
        target_html, markup, span, "commentable-html.css", "style",
        _inlined_element("commentable-html.css", "style", layer["commentable-html.css"],
                         target_name), target_name))
    edits.append(_companion_edit(
        target_html, markup, span, "commentable-html.js", "script",
        _inlined_element("commentable-html.js", "script", layer["commentable-html.js"],
                         target_name), target_name))
    # The asset registry is OPTIONAL: the validator only warns when a NonShareable document has
    # none, so a document that never carried one must still migrate.
    edits.append(_companion_edit(target_html, markup, span, DROPPED_COMPANION, "script", "",
                                 target_name, required=False))
    edits.append(_mode_edit(target_html, masked, target_name))

    out = _apply_edits(target_html, edits)
    _assert_self_contained(out, _content_span(out, target_name), target_name)
    return out, out != target_html


def read_layer(dist_dir):
    """Read the three companion files from a dist directory into a {name: text} map."""
    layer = {}
    for name, _tag in COMPANIONS:
        with io.open(os.path.join(dist_dir, name), "r", encoding="utf-8", newline="") as fh:
            layer[name] = fh.read()
    return layer


def _read(path):
    with io.open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def _write(path, text):
    """Stage the new bytes and swap them in, so a failed write never destroys the document."""
    _atomic_io.atomic_write(path, text)


def main(argv):
    parser = argparse.ArgumentParser(
        prog="to_shareable.py",
        description="Migrate a NonShareable commentable-html document to a self-contained "
                    "Shareable one, preserving its content, embedded comments, and handled ids. "
                    "An already-Shareable document is left untouched.")
    parser.add_argument("files", nargs="+", help="document(s) to migrate in place")
    parser.add_argument("--check", action="store_true",
                        help="report what would change and write nothing")
    parser.add_argument("--dist", default=None,
                        help="dist directory holding the companion files to inline "
                             "(default: the skill's own dist/)")
    args = parser.parse_args(argv[1:])

    dist_dir = args.dist or os.path.dirname(_toolpath.dist_template(_toolpath.SHAREABLE_TEMPLATE))
    try:
        layer = read_layer(dist_dir)
    except (OSError, UnicodeDecodeError) as exc:
        sys.stderr.write("to_shareable: cannot read the layer from %s: %s\n" % (dist_dir, exc))
        return 1

    failed = False
    for path in args.files:
        try:
            html = _read(path)
        except (OSError, UnicodeDecodeError) as exc:
            sys.stderr.write("to_shareable: %s: %s\n" % (path, exc))
            failed = True
            continue
        try:
            out, changed = to_shareable(html, layer, path)
        except ValueError as exc:
            sys.stderr.write("to_shareable: %s\n" % exc)
            failed = True
            continue
        if not changed:
            print("to_shareable: %s is already Shareable; nothing to do" % path)
            continue
        if args.check:
            print("to_shareable: %s WOULD be migrated to Shareable" % path)
            continue
        try:
            _write(path, out)
        except (OSError, IOError) as exc:
            sys.stderr.write("to_shareable: %s: could not write the migrated document: %s\n"
                             % (path, exc))
            failed = True
            continue
        print("to_shareable: migrated %s to Shareable (%d -> %d bytes)"
              % (path, len(html), len(out)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
