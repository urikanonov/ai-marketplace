#!/usr/bin/env python3
"""Atomically cement TABLES_STATE_JSON table edits into authored HTML."""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _atomic_io  # noqa: E402
from tables_common import render_sections, scan_tables, validate_payload  # noqa: E402

_OPEN = re.compile(r"^=== CMH MACHINE TRAILER \(do not edit\) ===[^\n]*\n", re.MULTILINE)
_CLOSE = re.compile(r"^=== END CMH MACHINE TRAILER ===", re.MULTILINE)
_STATE = re.compile(r"^TABLES_STATE_JSON:[ \t]*(\{[^\n]*\})[ \t\r]*$", re.MULTILINE)


def states_from_bundle(bundle):
    opens = list(_OPEN.finditer(bundle))
    if not opens:
        raise ValueError("no CMH machine trailer found")
    body = bundle[opens[-1].end():]
    close = _CLOSE.search(body)
    if close is None or body[close.end():].strip():
        raise ValueError("CMH machine trailer is unclosed or has trailing content")
    matches = list(_STATE.finditer(body[:close.start()]))
    if len(matches) != 1:
        raise ValueError("machine trailer needs exactly one TABLES_STATE_JSON line")
    return validate_payload(json.loads(matches[0].group(1)))


def apply_tables(path, payload):
    payload = validate_payload(payload)
    with open(path, encoding="utf-8", newline="") as fh:
        source = fh.read()
    if not payload["tables"]:
        return 0
    tables = {table["id"]: table for table in scan_tables(source)}
    edits, changed = [], 0
    for change in payload["tables"]:
        table = tables.get(change["id"])
        if table is None:
            raise ValueError("table not found: " + change["id"])
        if table["label"] != change["label"]:
            raise ValueError("table label conflict: " + change["id"])
        if table["model"] == change["to"]:
            continue
        if table["model"] != change["from"]:
            raise ValueError("table baseline conflict: " + change["id"])
        replacements = render_sections(change["to"])
        crlf = source.count("\r\n")
        for tag, replacement in replacements.items():
            if crlf > source.count("\n") - crlf:
                replacement = replacement.replace("\n", "\r\n")
            start, end = table["sections"][tag]
            edits.append((start, end, replacement))
        changed += 1
    output = source
    for start, end, replacement in sorted(edits, reverse=True):
        output = output[:start] + replacement + output[end:]
    if edits:
        _atomic_io.atomic_write(path, output)
    return changed


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", help="source HTML file to edit in place")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--from-bundle", metavar="FILE", help="Copy-all bundle, or - for stdin")
    group.add_argument("--state-json", metavar="JSON", help="explicit version-1 table transaction")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv[1:])
    try:
        if args.state_json is not None:
            state = json.loads(args.state_json)
        elif args.from_bundle == "-":
            state = states_from_bundle(sys.stdin.read())
        else:
            with open(args.from_bundle, encoding="utf-8") as fh:
                state = states_from_bundle(fh.read())
        changed = apply_tables(args.file, state)
    except (ValueError, OSError) as exc:
        sys.stderr.write("tables_apply: %s\n" % exc)
        return 1
    if not args.quiet:
        sys.stdout.write("tables_apply: updated %d table(s) in %s\n" % (changed, args.file))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
