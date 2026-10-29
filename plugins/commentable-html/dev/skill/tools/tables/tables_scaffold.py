#!/usr/bin/env python3
"""Emit native editable-table markup from a canonical JSON model."""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _atomic_io  # noqa: E402
from tables_common import _escape, identifier, label, render_inner  # noqa: E402


def scaffold(table_id, table_label, model):
    return '<table data-cmh-table="%s" data-cmh-table-label="%s">%s</table>\n' % (
        identifier(table_id), _escape(label(table_label)), render_inner(model))


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id", required=True, help="stable table id")
    parser.add_argument("--label", required=True, help="nonblank table label")
    parser.add_argument("--in", dest="input", required=True, metavar="FILE",
                        help="canonical model JSON file, or - for stdin")
    parser.add_argument("--out", metavar="FILE", help="output HTML fragment (default: stdout)")
    args = parser.parse_args(argv[1:])
    if _atomic_io.refuse_aliased_output(
            "tables_scaffold", args.out, [_atomic_io.not_stdin(args.input)]):
        return 1
    try:
        if args.input == "-":
            model = json.load(sys.stdin)
        else:
            with open(args.input, encoding="utf-8") as fh:
                model = json.load(fh)
        output = scaffold(args.id, args.label, model)
        if args.out:
            _atomic_io.atomic_write(args.out, output)
        else:
            sys.stdout.write(output)
    except (OSError, ValueError) as exc:
        sys.stderr.write("tables_scaffold: %s\n" % exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
