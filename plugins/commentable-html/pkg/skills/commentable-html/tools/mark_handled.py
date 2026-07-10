#!/usr/bin/env python3
"""Surgically mark commentable-html comments as handled - a zero-token iteration step.

During a review loop the ONLY change the agent must make to a generated document
is appending the ids from a "Copy all" bundle to the document's
`<script id="handledCommentIds">` block. Doing that with an LLM re-emits
surrounding boilerplate; this helper does it deterministically instead, touching
only the handled-ids array and leaving the rest of the document's structure
untouched. (A file's newline style is preserved when it is uniformly CRLF or
uniformly LF; a file that mixes newline styles is normalized to the dominant one.)
It works for both inline and nonportable documents (the block is inline in both).

Usage (run from the skill root):
    python tools/mark_handled.py <file.html> c<id> [c<id> ...]
    python tools/mark_handled.py <file.html> --json '["cabc123","cdef456"]'
    python tools/mark_handled.py <file.html> --from-bundle bundle.txt   # or: -  (stdin)

The bundle form parses the machine-readable `HANDLED_IDS_JSON: [...]` line that
"Copy all" appends, so you can pipe the pasted bundle straight in. Exit code 0 on
success (including "nothing new to add"), 1 on error.
"""
import json
import os
import re
import sys
from html.parser import HTMLParser

SAFE_ID_RE = re.compile(r"^c[a-z0-9]{6,63}$")
_BUNDLE_RE = re.compile(r"HANDLED_IDS_JSON:\s*(\[[^\]]*\])")
_BUNDLE_LINE_RE = re.compile(r"^\s*HANDLED_IDS_JSON:\s*(\[[^\]]*\])", re.MULTILINE)


class _HandledLocator(HTMLParser):
    """Locate the REAL <script id="handledCommentIds"> content range with the tolerant
    HTML parser, so a decoy inside an HTML comment (parsed as a comment, never a start
    tag) or a quoted '>' in the tag cannot fool the locator the way a raw regex would.
    Records (content_start, endtag_start) char indices for each such script."""

    def __init__(self, text):
        super().__init__(convert_charrefs=False)
        self._offsets = [0]
        for m in re.finditer("\n", text):
            self._offsets.append(m.end())
        self._active = False
        self._content_start = None
        self._template_depth = 0
        self.spans = []

    def _idx(self):
        lineno, col = self.getpos()
        return self._offsets[lineno - 1] + col

    def _is_target(self, tag, attrs):
        if tag.lower() != "script":
            return False
        d = {}
        for k, v in attrs:
            kl = (k or "").lower()
            if kl not in d:
                d[kl] = v if v is not None else ""
        return d.get("id") == "handledCommentIds"

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "template":
            # <template> contents are an inert DocumentFragment: getElementById (and
            # so the runtime) never sees a script inside one, so skip it here too.
            self._template_depth += 1
            return
        if self._template_depth == 0 and self._is_target(tag, attrs):
            # Content starts right after the parsed start tag. Use the parser's own
            # start-tag source so a quoted '>' or odd spacing is handled correctly.
            self._content_start = self._idx() + len(self.get_starttag_text())
            self._active = True

    # A '<script .../>' on a non-void element is still an opening tag to a browser
    # (the content up to the next </script> is the body), so treat it the same way.
    # A self-closing '<template/>' is the exception: it opens and closes at once, so it
    # must NOT leave _template_depth incremented (that would wrongly hide a following
    # handledCommentIds script as if it were inside a live <template>).
    def handle_startendtag(self, tag, attrs):
        if tag.lower() == "template":
            return
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag.lower() == "template":
            if self._template_depth > 0:
                self._template_depth -= 1
            return
        if self._active and tag.lower() == "script":
            self.spans.append((self._content_start, self._idx()))
            self._active = False


def _locate_handled_block(html):
    """Return the (content_start, endtag_start) char ranges of every real
    handledCommentIds <script> body (comments/decoys already excluded)."""
    p = _HandledLocator(html)
    try:
        p.feed(html)
        p.close()
    except Exception:
        pass
    return p.spans


def _format_array(ids):
    if not ids:
        return "[]"
    return "[\n" + ",\n".join("  " + json.dumps(x) for x in ids) + "\n]"


def mark_handled(path, new_ids):
    """Merge `new_ids` into the file's handledCommentIds block. Returns the list
    of ids actually added (empty if all were already present). Raises ValueError
    on a malformed id, a missing block, or invalid existing JSON."""
    bad = [x for x in new_ids if not (isinstance(x, str) and SAFE_ID_RE.match(x))]
    if bad:
        raise ValueError("refusing to write unsafe comment id(s): %r" % bad[:5])

    with open(path, "r", encoding="utf-8", newline="") as fh:
        raw = fh.read()
    # Preserve the file's DOMINANT newline style: count CRLF vs bare LF so a single
    # stray CRLF in a mostly-LF file does not rewrite the whole file to CRLF.
    crlf = raw.count("\r\n")
    lf = raw.count("\n") - crlf  # a "\n" that is not part of a "\r\n"
    nl = "\r\n" if crlf > lf else "\n"
    html = raw.replace("\r\n", "\n").replace("\r", "\n")

    spans = _locate_handled_block(html)
    if not spans:
        raise ValueError('no <script id="handledCommentIds"> block found in %s' % path)
    if len(spans) > 1:
        # validate.py already errors on a duplicate id; refuse to guess which one
        # is authoritative rather than silently editing the first.
        raise ValueError('multiple <script id="handledCommentIds"> blocks in %s (must be unique)' % path)
    content_start, endtag_start = spans[0]
    try:
        existing = json.loads((html[content_start:endtag_start].strip() or "[]"))
    except json.JSONDecodeError as exc:
        raise ValueError("existing handledCommentIds is not valid JSON: %s" % exc)
    if not isinstance(existing, list):
        raise ValueError("existing handledCommentIds is not a JSON array")
    bad_existing = [x for x in existing if not (isinstance(x, str) and SAFE_ID_RE.match(x))]
    if bad_existing:
        raise ValueError("existing handledCommentIds contains unsafe id(s), refusing to rewrite: %r" % bad_existing[:5])

    seen = set(existing)
    added = []
    merged = list(existing)
    for x in new_ids:
        if x not in seen:
            seen.add(x)
            merged.append(x)
            added.append(x)
    if not added:
        return []

    out = html[:content_start] + "\n" + _format_array(merged) + "\n" + html[endtag_start:]
    if nl != "\n":
        out = out.replace("\n", nl)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(out)
    return added


def _ids_from_bundle(text):
    matches = list(_BUNDLE_LINE_RE.finditer(text))
    if not matches:
        matches = list(_BUNDLE_RE.finditer(text))
    if not matches:
        raise ValueError("no 'HANDLED_IDS_JSON: [...]' line found in the bundle")
    return json.loads(matches[-1].group(1))


def main(argv):
    args = argv[1:]
    if not args:
        sys.stderr.write(__doc__)
        return 1
    path = args[0]
    rest = args[1:]
    if not os.path.exists(path):
        sys.stderr.write("mark_handled: file not found: %s\n" % path)
        return 1

    try:
        if rest[:1] == ["--json"]:
            if len(rest) < 2:
                raise ValueError("--json requires a JSON array argument, e.g. --json '[\"cabc123\"]'")
            ids = json.loads(rest[1])
        elif rest[:1] == ["--from-bundle"]:
            src = rest[1] if len(rest) > 1 else "-"
            if src == "-":
                text = sys.stdin.read()
            else:
                with open(src, encoding="utf-8") as fh:
                    text = fh.read()
            ids = _ids_from_bundle(text)
        else:
            ids = rest
        if not isinstance(ids, list):
            raise ValueError("expected a list of ids")
        added = mark_handled(path, [str(x) for x in ids])
    except (ValueError, IndexError, json.JSONDecodeError, OSError) as exc:
        sys.stderr.write("mark_handled: %s\n" % exc)
        return 1

    if added:
        print("marked %d comment(s) handled in %s: %s" % (len(added), path, ", ".join(added)))
    else:
        print("nothing to do: all ids already handled in %s" % path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
