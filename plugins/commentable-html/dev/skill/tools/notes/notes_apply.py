#!/usr/bin/env python3
"""Cement editable notes-field text into the source HTML - a deterministic iteration step.

During a review loop the reviewer edits a notes field in the browser and clicks "Copy all";
the bundle carries a machine-readable `NOTES_STATE_JSON:` line mapping each note id to its
current text. This helper reads that map (or an explicit --state-json) and replaces the inner
content of each `data-cmh-note` element with the HTML-escaped text, so the edit is baked into
the source the agent owns. It is deterministic and idempotent, touches only the matched notes'
inner content, and preserves the file's newline style (including inside the replacement text).

Item identity matches the runtime: a note's key is its `data-cmh-note` id.

Usage (run from the skill root):
    python tools/notes/notes_apply.py file.html --from-bundle bundle.txt   # or: -  (stdin)
    python tools/notes/notes_apply.py file.html --state-json '{"risk-summary":"One blocker."}'

Exit code 0 on success (including "nothing to change"), 1 on error.
"""
import argparse
import html as _html
import json
import os
import re
import sys
from html.parser import HTMLParser

_BUNDLE_RE = re.compile(r"^\s*NOTES_STATE_JSON:\s*(\{.*\})\s*$", re.MULTILINE)
_TRAILER_OPEN_RE = re.compile(
    r"^=== CMH MACHINE TRAILER \(do not edit\) ===[^\n]*\n", re.MULTILINE)
_TRAILER_CLOSE_RE = re.compile(r"^=== END CMH MACHINE TRAILER ===", re.MULTILINE)
_VOID = frozenset(
    "area base br col embed hr img input link meta param source track wbr".split())


class _NoteScanner(HTMLParser):
    """Record each data-cmh-note element's inner-content char span (end of its start tag to the
    start of its MATCHING end tag), tracking nesting so a same-named child does not close it."""

    def __init__(self, text):
        super().__init__(convert_charrefs=False)
        self._offsets = [0]
        for m in re.finditer("\n", text):
            self._offsets.append(m.end())
        self._stack = []   # list of {"tag": str, "note": dict|None}
        self.notes = []    # {"id": str, "start": int, "end": int|None}

    def _idx(self):
        lineno, col = self.getpos()
        return self._offsets[lineno - 1] + col

    def _attrs(self, attrs):
        d = {}
        for k, v in attrs:
            kl = (k or "").lower()
            if kl not in d:
                d[kl] = v if v is not None else ""
        return d

    def handle_starttag(self, tag, attrs):
        d = self._attrs(attrs)
        note = None
        if "data-cmh-note" in d and tag.lower() not in _VOID:
            starttag = self.get_starttag_text() or ""
            note = {"id": d.get("data-cmh-note") or "", "start": self._idx() + len(starttag), "end": None}
            self.notes.append(note)
        if tag.lower() not in _VOID:
            self._stack.append({"tag": tag.lower(), "note": note})

    def handle_startendtag(self, tag, attrs):
        # A self-closing note has no inner content; ignore it (the validator forbids this shape).
        pass

    def handle_endtag(self, tag):
        tag = tag.lower()
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i]["tag"] == tag:
                popped = self._stack[i:]
                del self._stack[i:]
                end = self._idx()
                for frame in reversed(popped):
                    if frame["note"] is not None and frame["note"]["end"] is None:
                        frame["note"]["end"] = end
                return


def _scan_notes(html):
    p = _NoteScanner(html)
    try:
        p.feed(html)
        p.close()
    except Exception:
        pass
    return [n for n in p.notes if n["end"] is not None]


def apply_notes(path, state_map, warn=None):
    """Rewrite the inner content of every note named in `state_map` ({noteId: text}).
    Returns the number of notes changed."""
    if warn is None:
        warn = lambda msg: sys.stderr.write("notes_apply: " + msg + "\n")
    if not isinstance(state_map, dict):
        raise ValueError("state map must be a JSON object of {noteId: text}")

    with open(path, "r", encoding="utf-8", newline="") as fh:
        raw = fh.read()
    crlf = raw.count("\r\n")
    lf = raw.count("\n") - crlf
    nl = "\r\n" if crlf > lf else "\n"
    html = raw.replace("\r\n", "\n").replace("\r", "\n")

    notes = _scan_notes(html)
    index = {}
    for n in notes:
        index.setdefault(n["id"], n)  # first note wins on a duplicate id

    edits = []  # (start, end, escaped_text)
    changed = 0
    for key, value in state_map.items():
        if not isinstance(value, str):
            warn('note "%s": expected a string value, skipping' % key)
            continue
        n = index.get(str(key))
        if not n:
            warn('note "%s": no data-cmh-note element found, skipping' % key)
            continue
        escaped = _html.escape(value, quote=False)
        if html[n["start"]:n["end"]] != escaped:
            edits.append((n["start"], n["end"], escaped))
            changed += 1

    if not edits:
        return 0
    # Splice from the last edit back to the first so earlier offsets stay valid.
    edits.sort(key=lambda e: e[0], reverse=True)
    out = html
    for start, end, escaped in edits:
        out = out[:start] + escaped + out[end:]
    if nl != "\n":
        out = out.replace("\n", nl)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(out)
    return changed


def _machine_trailer_body(text):
    """Return the body of the FINAL '=== CMH MACHINE TRAILER ===' block. Copy all emits
    that trailer unconditionally as the last block of the bundle, so a forged trailer or
    STATE line inside an untrusted reviewer note (always earlier in the text) is ignored:
    the parser reads state ONLY from the genuine trailer, never via a last-match over the
    whole bundle."""
    opens = list(_TRAILER_OPEN_RE.finditer(text))
    if not opens:
        raise ValueError("no CMH machine trailer found in the bundle")
    body = text[opens[-1].end():]
    close = _TRAILER_CLOSE_RE.search(body)
    if close is None:
        raise ValueError("CMH machine trailer is not closed (missing END marker)")
    if body[close.end():].strip():
        raise ValueError("CMH machine trailer has trailing content after the END marker")
    return body[:close.start()]


def states_from_bundle(text):
    body = _machine_trailer_body(text)
    matches = list(_BUNDLE_RE.finditer(body))
    if not matches:
        raise ValueError("no 'NOTES_STATE_JSON: {...}' line found in the machine trailer")
    return json.loads(matches[-1].group(1))


def _read(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def main(argv):
    parser = argparse.ArgumentParser(
        prog="notes_apply.py",
        description="Cement editable notes-field text into the source HTML.")
    parser.add_argument("file", help="the source HTML file to edit in place")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--from-bundle", metavar="FILE",
                     help="read the NOTES_STATE_JSON line from a Copy-all bundle file, or - for stdin")
    src.add_argument("--state-json", metavar="JSON",
                     help='an explicit state map, e.g. \'{"risk-summary":"One blocker."}\'')
    parser.add_argument("--quiet", action="store_true", help="do not print the change summary")
    args = parser.parse_args(argv[1:])

    if not os.path.exists(args.file):
        sys.stderr.write("notes_apply: file not found: %s\n" % args.file)
        return 1
    try:
        if args.state_json is not None:
            state_map = json.loads(args.state_json)
        else:
            text = sys.stdin.read() if args.from_bundle == "-" else _read(args.from_bundle)
            state_map = states_from_bundle(text)
        changed = apply_notes(args.file, state_map)
    except (ValueError, json.JSONDecodeError) as exc:
        sys.stderr.write("notes_apply: %s\n" % exc)
        return 1
    if not args.quiet:
        sys.stdout.write("notes_apply: updated %d note(s) in %s\n" % (changed, args.file))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
