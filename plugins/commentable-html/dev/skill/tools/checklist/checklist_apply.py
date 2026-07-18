#!/usr/bin/env python3
"""Cement layered-checklist states into the source HTML - a deterministic iteration step.

During a review loop the reviewer flips checklist item states in the browser and clicks
"Copy all"; the bundle carries a machine-readable `CHECKLIST_STATE_JSON:` line. This helper
reads that map (or an explicit --state-json) and rewrites the `data-cmh-state` attribute on
each named item inside its `data-cmh-checklist` container, so the state is baked into the
source the agent owns. It is deterministic and idempotent, touches only the matched items'
start tags, and leaves branch items (which derive their state at runtime) untouched.

Item identity matches the runtime: an item's key is its `data-cmh-item` id when present,
else its 1-based position in document order among the items of its checklist container.

Usage (run from the skill root):
    python tools/checklist_apply.py file.html --from-bundle bundle.txt   # or: -  (stdin)
    python tools/checklist_apply.py file.html --state-json '{"audit":{"fw":"cross"}}'

State tokens are blank, check, cross, and question; any other value is ignored with a
warning. Exit code 0 on success (including "nothing to change"), 1 on error.
"""
import argparse
import json
import os
import re
import sys
from html.parser import HTMLParser

STATES = ("blank", "check", "cross", "question")
_BUNDLE_RE = re.compile(r"^\s*CHECKLIST_STATE_JSON:\s*(\{.*\})\s*$", re.MULTILINE)
_TRAILER_OPEN_RE = re.compile(
    r"^=== CMH MACHINE TRAILER \(do not edit\) ===[^\n]*\n", re.MULTILINE)
_TRAILER_CLOSE_RE = re.compile(r"^=== END CMH MACHINE TRAILER ===", re.MULTILINE)
_VOID = frozenset(
    "area base br col embed hr img input link meta param source track wbr".split())


class _ChecklistScanner(HTMLParser):
    """Record each checklist item's start-tag char span and its stable key, scoped to the
    innermost open data-cmh-checklist container (mirrors the runtime's ownership filter)."""

    def __init__(self, text):
        super().__init__(convert_charrefs=False)
        self._offsets = [0]
        for m in re.finditer("\n", text):
            self._offsets.append(m.end())
        self._containers = []   # stack of {"id": str, "counter": int}
        self._elems = []        # stack of (tag, opened_container: bool)
        self.items = []         # {container_id, key, start, length, starttag}

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

    def _record_item(self, d):
        if not self._containers:
            return
        if "data-cmh-state" not in d and "data-cmh-item" not in d:
            return
        ctx = self._containers[-1]
        ctx["counter"] += 1
        key = d.get("data-cmh-item") or str(ctx["counter"])
        starttag = self.get_starttag_text() or ""
        self.items.append({
            "container_id": ctx["id"],
            "key": key,
            "start": self._idx(),
            "length": len(starttag),
            "starttag": starttag,
        })

    def handle_starttag(self, tag, attrs):
        d = self._attrs(attrs)
        self._record_item(d)
        is_container = "data-cmh-checklist" in d
        if is_container:
            self._containers.append({"id": d.get("data-cmh-checklist") or "", "counter": 0})
        if tag.lower() not in _VOID:
            self._elems.append((tag.lower(), is_container))

    def handle_startendtag(self, tag, attrs):
        # A self-closing item opens and closes at once: record it, push no context.
        self._record_item(self._attrs(attrs))

    def handle_endtag(self, tag):
        tag = tag.lower()
        for i in range(len(self._elems) - 1, -1, -1):
            if self._elems[i][0] == tag:
                popped = self._elems[i:]
                del self._elems[i:]
                for (_t, opened_container) in reversed(popped):
                    if opened_container and self._containers:
                        self._containers.pop()
                return


def _scan_items(html):
    p = _ChecklistScanner(html)
    try:
        p.feed(html)
        p.close()
    except Exception:
        pass
    return p.items


def _set_state_attr(starttag, token):
    m = re.search(r"\sdata-cmh-state\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", starttag, re.IGNORECASE)
    if m:
        return starttag[:m.start()] + ' data-cmh-state="' + token + '"' + starttag[m.end():]
    m2 = re.search(r"/?>\s*$", starttag)
    insert_at = m2.start() if m2 else len(starttag) - 1
    return starttag[:insert_at] + ' data-cmh-state="' + token + '"' + starttag[insert_at:]


def apply_states(path, state_map, warn=None):
    """Rewrite data-cmh-state on every item named in `state_map`
    ({checklistId: {itemKey: token}}). Returns the number of items changed."""
    if warn is None:
        warn = lambda msg: sys.stderr.write("checklist_apply: " + msg + "\n")
    if not isinstance(state_map, dict):
        raise ValueError("state map must be a JSON object of {checklistId: {itemKey: state}}")

    with open(path, "r", encoding="utf-8", newline="") as fh:
        raw = fh.read()
    crlf = raw.count("\r\n")
    lf = raw.count("\n") - crlf
    nl = "\r\n" if crlf > lf else "\n"
    html = raw.replace("\r\n", "\n").replace("\r", "\n")

    items = _scan_items(html)
    index = {}
    for it in items:
        index.setdefault((it["container_id"], it["key"]), it)  # first item wins on a duplicate key

    edits = []  # (start, length, new_starttag)
    changed = 0
    for cid, leaves in state_map.items():
        if not isinstance(leaves, dict):
            warn('checklist "%s": expected an object of {itemKey: state}, skipping' % cid)
            continue
        for key, token in leaves.items():
            token = str(token).strip().lower()
            if token not in STATES:
                warn('checklist "%s" item "%s": invalid state "%s", skipping' % (cid, key, token))
                continue
            it = index.get((cid, str(key)))
            if not it:
                warn('checklist "%s": no item "%s" found, skipping' % (cid, key))
                continue
            new_tag = _set_state_attr(it["starttag"], token)
            if new_tag != it["starttag"]:
                edits.append((it["start"], it["length"], new_tag))
                changed += 1

    if not edits:
        return 0
    # Splice from the last edit back to the first so earlier offsets stay valid.
    edits.sort(key=lambda e: e[0], reverse=True)
    out = html
    for start, length, new_tag in edits:
        out = out[:start] + new_tag + out[start + length:]
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
        raise ValueError("no 'CHECKLIST_STATE_JSON: {...}' line found in the machine trailer")
    return json.loads(matches[-1].group(1))


def main(argv):
    parser = argparse.ArgumentParser(
        prog="checklist_apply.py",
        description="Cement layered-checklist states into the source HTML.")
    parser.add_argument("file", help="the source HTML file to edit in place")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--from-bundle", metavar="FILE",
                     help="read the CHECKLIST_STATE_JSON line from a Copy-all bundle file, or - for stdin")
    src.add_argument("--state-json", metavar="JSON",
                     help='an explicit state map, e.g. \'{"audit":{"fw":"cross"}}\'')
    parser.add_argument("--quiet", action="store_true", help="do not print the change summary")
    args = parser.parse_args(argv[1:])

    if not os.path.exists(args.file):
        sys.stderr.write("checklist_apply: file not found: %s\n" % args.file)
        return 1
    try:
        if args.state_json is not None:
            state_map = json.loads(args.state_json)
        else:
            text = sys.stdin.read() if args.from_bundle == "-" else _read(args.from_bundle)
            state_map = states_from_bundle(text)
        changed = apply_states(args.file, state_map)
    except (ValueError, json.JSONDecodeError) as exc:
        sys.stderr.write("checklist_apply: %s\n" % exc)
        return 1
    if not args.quiet:
        sys.stdout.write("checklist_apply: updated %d item(s) in %s\n" % (changed, args.file))
    return 0


def _read(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
