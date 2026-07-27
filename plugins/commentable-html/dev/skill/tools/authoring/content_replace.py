#!/usr/bin/env python3
"""Write a CONTENT fragment back into a commentable-html document, atomically.

This is ONE transaction, deliberately. The steps a correct write-back needs - validate
the fragment, swap the region, re-bake (typography, section cards, highlighting, an
existing table of contents), strict-validate, re-stamp the content-bound validated hash -
are not optional follow-ups an agent can be trusted to remember; a half-completed
sequence leaves a document that renders a "not validated" banner and has lost its
highlighting and section cards. So either every step succeeds and the file is replaced,
or the original is left byte-for-byte untouched.

Section hashes are textContent-based, so re-baking a block never moves the hash of a
section the agent did not edit - Mark-reviewed markers survive an edit elsewhere in the
document. Byte-level fidelity is preserved too: before finalizing, every block whose
SOURCE is unchanged has its ORIGINAL stored markup restored, so a document baked by an
older tokenizer is not rewritten wholesale just because one paragraph changed. Blocks the
highlighter would not re-bake are never de-highlighted in the first place.

A code block the highlighter's inverse refuses (hand-written markup inside a
`<pre><code>`) is left exactly as the caller supplied it - never re-highlighted, never
rewritten.

Usage (run from the skill root):
    python tools/authoring/content_replace.py file.html --content fragment.html
    python tools/authoring/content_replace.py file.html --content -        # stdin
    python tools/authoring/content_replace.py file.html --content f.html --handled-from-bundle b.txt
"""
import argparse
import io
import os
import re
import stat
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tools/ root
import _toolpath  # noqa: E402
_toolpath.ensure()
import content_extract  # noqa: E402
import doc_stamp  # noqa: E402
import finalize  # noqa: E402
import generate_toc  # noqa: E402
import mark_handled  # noqa: E402
import section_hash  # noqa: E402
import validate  # noqa: E402


class ReplaceError(Exception):
    """The fragment or the resulting document is unusable; nothing was written."""


_VALIDATED_META_RE = re.compile(
    r'<meta name="commentable-html-validated" content="[^"]*" />\s*', re.IGNORECASE)
# A real layer region marker is an HTML COMMENT, not marker-like prose: a document may
# legitimately quote "BEGIN: commentable-html - JS" while documenting the layer.
_REGION_MARKER_RE = re.compile(
    r"<!--\s*(?:BEGIN|END):\s*commentable-html\s*-\s*[A-Z]", re.IGNORECASE)


def _read(path):
    with io.open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def _write(path, text, newline=""):
    with io.open(path, "w", encoding="utf-8", newline=newline) as fh:
        fh.write(text)


def _check_fragment(fragment):
    """Reject a fragment that must not be spliced in, before touching the file.

    Deliberately narrow: it rejects only layer INFRASTRUCTURE, which must never come
    from content. Structural well-formedness is left to the strict validation of the
    ASSEMBLED document below, which is authoritative and cannot false-reject. (An
    earlier angle-bracket count was tried here and was unsound: `content_extract`
    hands back de-highlighted SOURCE, so a code block containing `if a < b:` carries a
    raw `<` and the count rejected the tool's own output.)
    """
    if fragment is None:
        raise ReplaceError("no fragment supplied")
    for marker in (content_extract.new_document.BEGIN_MARKER,
                   content_extract.new_document.END_MARKER):
        if marker in fragment:
            raise ReplaceError("the fragment contains a CONTENT marker; supply only the "
                               "fragment BETWEEN the markers, not the markers themselves")
    if _REGION_MARKER_RE.search(fragment):
        raise ReplaceError("the fragment contains a commentable-html region marker; "
                           "content must not carry layer infrastructure")


def _code_blocks(fragment):
    """Return [(code_attrs, inner)] for every block code element, in order."""
    return [(m.group(2), m.group(3))
            for m in content_extract._PRE_CODE_RE.finditer(fragment or "")]


def restore_unchanged_blocks(new_fragment, old_fragment):
    """Put back the ORIGINAL stored markup for blocks whose source did not change.

    Without this, a no-op edit re-highlights every block with TODAY's tokenizer, so a
    document baked by an OLDER one is rewritten wholesale - churn in code the agent
    never touched, and a needless diff. Blocks are matched by their de-highlighted
    SOURCE, so an edit elsewhere (which shifts block positions) still leaves untouched
    blocks byte-identical.
    """
    available = {}
    for attrs, inner in _code_blocks(old_fragment):
        source = content_extract._reversible_source(attrs, inner)
        if source is not None:
            key = (content_extract._language(attrs), source)
            available.setdefault(key, []).append(inner)

    def repl(m):
        open_tag, attrs, inner, close_tag = m.group(1), m.group(2), m.group(3), m.group(4)
        stored = available.get((content_extract._language(attrs), inner))
        if not stored:
            return m.group(0)
        return open_tag + stored.pop(0) + close_tag

    return content_extract._PRE_CODE_RE.sub(repl, new_fragment)


def splice(html, fragment):
    """Return `html` with its CONTENT region replaced by `fragment`."""
    start, end = content_extract.content_span(html)
    return html[:start] + "\n\n" + fragment.strip("\n") + "\n\n" + html[end:]


def finalize_document(path, strict=True):
    """Re-bake, strict-validate and re-stamp a document in place.

    Raises ReplaceError unless the result is clean, so a caller can never end up with a
    half-baked document. Stamping lives in validate.py's CLI (not in `validate()`), so
    the stamp is written here only on a genuinely clean pass - the same rule the CLI uses.
    """
    try:
        result = finalize.finalize(path, run_toc=_has_toc(_read(path)))
    except Exception as exc:
        raise ReplaceError("finalize failed: %s" % exc)
    errors, warnings = result["errors"], result["warnings"]
    if errors:
        raise ReplaceError("the document has %d validation error(s) after the swap: %s"
                           % (len(errors), errors[0]))
    if strict and warnings:
        raise ReplaceError("the document has %d validation warning(s) after the swap: %s"
                           % (len(warnings), warnings[0]))
    if warnings:
        # A stamp asserts a STRICT-clean pass, so a warning-bearing document is written
        # without one and the runtime keeps its "not validated" banner up. Say so rather
        # than failing, since --no-strict deliberately allows this.
        sys.stderr.write("content_replace: %d warning(s) remain, so no validated stamp "
                         "was written; resolve them and re-run for a clean stamp\n"
                         % len(warnings))
        return
    _stamp(path)


def _has_toc(html):
    """True when the author's CONTENT already carries a generated table of contents.

    Uses generate_toc's own tolerant parser rather than a string probe: a probe both
    misses valid `nav.cm-toc` markup (single quotes, another class first) and fires on
    any unrelated `id="toc"`, so it would leave a stale TOC or invent an unwanted one.
    """
    try:
        return bool(generate_toc._parse(html).toc_spans)
    except Exception:
        return False


def _without_validated_timestamp(html):
    """Strip the validated timestamp so two documents can be compared for real change.
    The timestamp moves on every validation; the content-bound HASH beside it does not."""
    return _VALIDATED_META_RE.sub("", html)


def replace(path, fragment, handled_ids=None, strict=True):
    """Swap the CONTENT region of `path` for `fragment`, re-bake, validate and stamp.

    Atomic: on any failure the original file is left byte-for-byte unchanged and no
    temporary file survives. A replacement that produces no real change does not touch
    the file at all, so re-writing a document with its own content is a true no-op
    rather than a fresh validation timestamp and a needless diff.
    """
    _check_fragment(fragment)
    original = _read(path)
    start, end = content_extract.content_span(original)
    fragment = restore_unchanged_blocks(fragment, original[start:end])
    spliced = splice(original, fragment)

    work_fd, work = tempfile.mkstemp(prefix=".cmh-replace-", suffix=".html",
                                     dir=os.path.dirname(os.path.abspath(path)) or ".")
    os.close(work_fd)
    try:
        _write(work, spliced)
        finalize_document(work, strict=strict)
        if handled_ids:
            mark_handled.mark_handled(work, handled_ids)
            # Marking handled ids edits state AFTER the stamp, so re-stamp the document.
            # Only meaningful when the document is strict-clean; a warning-bearing one
            # carries no stamp to refresh.
            if strict:
                _stamp(work)
        final = _read(work)
    except Exception:
        _quiet_remove(work)
        raise
    else:
        _quiet_remove(work)

    if _without_validated_timestamp(final) == _without_validated_timestamp(original):
        return original
    _atomic_write(path, final)
    return final


def _atomic_write(path, text):
    """Replace `path` with `text` via a fully-written temp file plus os.replace.

    A plain write truncates the target first, so a crash or a full disk mid-write would
    leave the user's document destroyed - the opposite of this tool's guarantee.
    os.replace is atomic on POSIX and on Windows (MoveFileEx with REPLACE_EXISTING).
    """
    directory = os.path.dirname(os.path.abspath(path)) or "."
    fd, staged = tempfile.mkstemp(prefix=".cmh-write-", suffix=".html", dir=directory)
    os.close(fd)
    try:
        with io.open(staged, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        # mkstemp creates 0600 and os.replace carries that inode's mode to the target,
        # so a 0644 report would silently become owner-only. Keep the target's mode.
        try:
            os.chmod(staged, stat.S_IMODE(os.stat(path).st_mode))
        except OSError:
            pass
        os.replace(staged, path)
    except Exception:
        _quiet_remove(staged)
        raise


def _stamp(path):
    """Write the content-bound validated stamp for the document's CURRENT bytes.

    `validate._stamp_validated_file` is deliberately best-effort (it swallows every
    failure) and rewrites the file in place, so a partial write there could leave the
    staged candidate truncated and we would commit those bytes. Verify the stamp landed
    and that the file still validates, so any failure aborts before the target is
    replaced.
    """
    errors, warnings = validate.validate(path)
    if errors or warnings:
        raise ReplaceError("the document did not validate cleanly before stamping")
    validate._stamp_validated_file(path)
    stamped = _read(path)
    if doc_stamp.get_meta(stamped, doc_stamp.VALIDATED_HASH_META) != \
            section_hash.document_content_hash(stamped):
        raise ReplaceError("the validated stamp was not written correctly")


def _quiet_remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def _read_fragment(source):
    if source == "-":
        return sys.stdin.read()
    return _read(source)


def main(argv):
    ap = argparse.ArgumentParser(
        description="replace the CONTENT region of a commentable-html document, atomically")
    ap.add_argument("file", help="the commentable-html document to rewrite")
    ap.add_argument("--content", required=True,
                    help="path to the replacement fragment, or - for stdin")
    ap.add_argument("--handled-from-bundle",
                    help="also mark the ids in this Copy-all bundle handled")
    ap.add_argument("--no-strict", action="store_true",
                    help="allow validator warnings (errors still abort the write)")
    args = ap.parse_args(argv)

    handled = None
    try:
        if args.handled_from_bundle:
            handled = mark_handled._ids_from_bundle(_read(args.handled_from_bundle))
        replace(args.file, _read_fragment(args.content), handled_ids=handled,
                strict=not args.no_strict)
    except (ReplaceError, content_extract.ExtractError, ValueError, OSError) as exc:
        sys.stderr.write("content_replace: %s (the document was NOT modified)\n" % exc)
        return 1

    sys.stderr.write("content_replace: rewrote the CONTENT region of %s\n" % args.file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
