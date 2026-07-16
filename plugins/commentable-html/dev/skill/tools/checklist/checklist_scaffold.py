#!/usr/bin/env python3
"""Generate layered-checklist markup from a plain indented outline - so authors never
hand-write the nesting, ids, or parent links.

Each non-empty input line is one item; leading indentation (spaces or tabs) sets its depth.
An optional leading state marker sets the authored baseline: [v] check, [x] cross, [?]
question, [ ] or none blank. The tool assigns a stable slug id per item (data-cmh-item),
links children to parents (by DOM nesting for --shape list, by data-cmh-parent for
--shape table, which cannot nest rows and may be sorted), and defaults leaves to blank.

Usage (run from the skill root):
    python tools/checklist_scaffold.py --in outline.txt --shape list  --id release --label "Release readiness"
    python tools/checklist_scaffold.py --in outline.txt --shape table --id audit   --label "Security audit"
    printf 'Backend\\n\\tMigrations\\n\\tLoad test\\nDocs' | \\
        python tools/checklist_scaffold.py --in - --id release

The result is a ready-to-paste fragment (stdout, or --out FILE). Wrap it into a document
with tools/new_document.py or paste it into an existing checklist-bearing document.
"""
import argparse
import html as _html
import os
import re
import sys

_STATE_BY_MARK = {" ": "blank", "": "blank", "v": "check", "x": "cross", "?": "question"}


def _indent_width(raw):
    n = 0
    for ch in raw:
        if ch == "\t":
            n += 4
        elif ch == " ":
            n += 1
        else:
            break
    return n


def _slug(label, used):
    base = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")[:40] or "item"
    cand = base
    i = 2
    while cand in used:
        cand = base + "-" + str(i)
        i += 1
    used.add(cand)
    return cand


def parse_outline(text):
    """Return a flat list of items with resolved ids, parent ids, and depth."""
    rows = []
    for raw in text.splitlines():
        if not raw.strip():
            continue
        label = raw.strip()
        state = "blank"
        m = re.match(r"^\[([ vVxX?])\]\s*(.*)$", label)
        if m:
            state = _STATE_BY_MARK[m.group(1).lower()]
            label = m.group(2).strip()
        rows.append({"indent": _indent_width(raw), "label": label, "state": state})
    used = set()
    stack = []  # list of {indent, id}
    items = []
    for r in rows:
        while stack and stack[-1]["indent"] >= r["indent"]:
            stack.pop()
        parent = stack[-1]["id"] if stack else None
        iid = _slug(r["label"], used)
        items.append({
            "id": iid, "label": r["label"], "state": r["state"],
            "parent": parent, "depth": len(stack),
        })
        stack.append({"indent": r["indent"], "id": iid})
    # A branch (has children) derives its state, so it carries no data-cmh-state baseline.
    parents = set(i["parent"] for i in items if i["parent"])
    for it in items:
        it["is_branch"] = it["id"] in parents
    return items


def _attr(name, value):
    return ' %s="%s"' % (name, _html.escape(value, quote=True))


def render_list(items, cid, label):
    by_parent = {}
    for it in items:
        by_parent.setdefault(it["parent"], []).append(it)

    def block(parent, depth):
        kids = by_parent.get(parent, [])
        if not kids:
            return ""
        pad = "  " * (depth + 2)
        out = "\n" + pad + "<ul>"
        for it in kids:
            state = "" if it["is_branch"] else _attr("data-cmh-state", it["state"])
            out += ("\n" + pad + "  <li" + _attr("data-cmh-item", it["id"]) + state + ">"
                    + _html.escape(it["label"]))
            out += block(it["id"], depth + 1)
            out += "</li>"
        out += "\n" + pad + "</ul>"
        return out

    head = '<div class="cmh-checklist"' + _attr("data-cmh-checklist", cid)
    if label:
        head += _attr("data-cmh-checklist-label", label)
    head += ">"
    return head + block(None, 0) + "\n</div>\n"


def render_table(items, cid, label):
    head = '<table class="cmh-checklist"' + _attr("data-cmh-checklist", cid)
    if label:
        head += _attr("data-cmh-checklist-label", label)
    head += ">\n  <thead><tr><th></th><th>Item</th></tr></thead>\n  <tbody>"
    rows = ""
    for it in items:
        parent = _attr("data-cmh-parent", it["parent"]) if it["parent"] else ""
        state = "" if it["is_branch"] else _attr("data-cmh-state", it["state"])
        pad = (' style="padding-left:%.2grem"' % (it["depth"] * 1.2)) if it["depth"] else ""
        rows += ("\n    <tr" + _attr("data-cmh-item", it["id"]) + parent + state + ">"
                 + "<td></td><td" + pad + ">" + _html.escape(it["label"]) + "</td></tr>")
    return head + rows + "\n  </tbody>\n</table>\n"


def scaffold(text, cid, label, shape):
    items = parse_outline(text)
    if not items:
        raise ValueError("the outline has no items")
    return render_table(items, cid, label) if shape == "table" else render_list(items, cid, label)


def main(argv):
    parser = argparse.ArgumentParser(
        prog="checklist_scaffold.py",
        description="Generate layered-checklist markup from an indented outline.")
    parser.add_argument("--in", dest="infile", required=True,
                        help="the outline file, or - to read from stdin")
    parser.add_argument("--id", required=True, help="the checklist id (data-cmh-checklist)")
    parser.add_argument("--label", default="", help="the checklist label (data-cmh-checklist-label)")
    parser.add_argument("--shape", choices=("list", "table"), default="list",
                        help="list (nested <ul>/<li>) or table (rows with data-cmh-parent)")
    parser.add_argument("--out", help="write to FILE instead of stdout")
    args = parser.parse_args(argv[1:])

    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_-]*$", args.id):
        sys.stderr.write("checklist_scaffold: --id must be a simple slug (letters, digits, - or _)\n")
        return 1
    try:
        text = sys.stdin.read() if args.infile == "-" else _read(args.infile)
        out = scaffold(text, args.id, args.label, args.shape)
    except (ValueError, OSError) as exc:
        sys.stderr.write("checklist_scaffold: %s\n" % exc)
        return 1
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(out)
    else:
        sys.stdout.write(out)
    return 0


def _read(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
