#!/usr/bin/env python3
"""Generate an editable notes-field element from an id, a label, and optional seed text -
so authors never hand-write the data attributes.

A notes field is a single element carrying data-cmh-note="<id>". Its authored inner text is
the baseline; a reviewer edits it in the browser and the change travels back through the
Copy-all bundle to be cemented with tools/notes/notes_apply.py. The field is plain text only
(the runtime renders it as a <textarea>), so the element must contain text, not markup.

Usage (run from the skill root):
    python tools/notes/notes_scaffold.py --id risk-summary --label "Reviewer risk summary" \
        --text "No blocking risks identified yet."
    python tools/notes/notes_scaffold.py --id notes --multiline --text - < seed.txt

The result is a ready-to-paste fragment (stdout, or --out FILE). Wrap it into a document with
tools/authoring/new_document.py or paste it into an existing document.
"""
import argparse
import html as _html
import re
import sys


def _attr(name, value):
    return ' %s="%s"' % (name, _html.escape(value, quote=True))


def scaffold(cid, label, text, multiline=False, foldable=False):
    """Return a data-cmh-note element as a single-line, validator-clean fragment."""
    out = '<div class="cmh-note"' + _attr("data-cmh-note", cid)
    if label:
        out += _attr("data-cmh-note-label", label)
    if multiline:
        out += _attr("data-cmh-note-multiline", "true")
    if foldable:
        out += _attr("data-cmh-note-foldable", "true")
    out += ">" + _html.escape(text) + "</div>\n"
    return out


def main(argv):
    parser = argparse.ArgumentParser(
        prog="notes_scaffold.py",
        description="Generate an editable notes-field (data-cmh-note) element.")
    parser.add_argument("--id", required=True, help="the note id (data-cmh-note); a simple slug")
    parser.add_argument("--label", default="", help="the note label (data-cmh-note-label)")
    parser.add_argument("--text", default="", help="the authored baseline text, or - to read stdin")
    parser.add_argument("--multiline", action="store_true",
                        help="default the field to multi-line (data-cmh-note-multiline)")
    parser.add_argument("--foldable", action="store_true",
                        help="make the note foldable (data-cmh-note-foldable): a +/- toggle that "
                             "reveals the field; starts collapsed when empty")
    parser.add_argument("--out", help="write to FILE instead of stdout")
    args = parser.parse_args(argv[1:])

    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_-]*$", args.id):
        sys.stderr.write("notes_scaffold: --id must be a simple slug (letters, digits, - or _)\n")
        return 1
    text = sys.stdin.read() if args.text == "-" else args.text
    out = scaffold(args.id, args.label, text, multiline=args.multiline, foldable=args.foldable)
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(out)
    else:
        sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
