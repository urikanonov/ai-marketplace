#!/usr/bin/env python3
"""Canonical editable-table schema, markup and source spans shared by table tools."""
import html
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _browser_attrs  # noqa: E402

SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]*\Z")
VOID = frozenset("area base br col embed hr img input link meta param source track wbr".split())
OWNER_ATTRS = ("data-cmh-note", "data-cmh-checklist", "data-cm-widget")


def text(value):
    if not isinstance(value, str):
        raise ValueError("table text values must be strings")
    return value.replace("\r\n", "\n").replace("\r", "\n")


def identifier(value):
    if not isinstance(value, str) or not SAFE_ID.fullmatch(value):
        raise ValueError("table ids must match [A-Za-z0-9][A-Za-z0-9_.:-]*")
    return value


def label(value):
    value = text(value)
    if not value.strip():
        raise ValueError("table labels must be nonblank strings")
    return value


def _object(value, keys, what):
    if not isinstance(value, dict) or set(value) != set(keys.split()):
        raise ValueError("%s must contain exactly %s" % (what, keys))


def validate_model(model):
    """Return a fresh canonical model; normalize line endings only."""
    _object(model, "columns rows", "table model")
    if not isinstance(model["columns"], list) or not model["columns"]:
        raise ValueError("table needs at least one column")
    if not isinstance(model["rows"], list):
        raise ValueError("table rows must be an array")
    columns, rows, ids = [], [], set()
    for column in model["columns"]:
        _object(column, "id label type options default", "table column")
        cid = identifier(column["id"])
        if cid in ids:
            raise ValueError("duplicate table column id: " + cid)
        ids.add(cid)
        kind = column["type"]
        if kind not in ("text", "choice"):
            raise ValueError("table column type must be text or choice")
        options = column["options"]
        default = text(column["default"])
        if not isinstance(options, list):
            raise ValueError("table choice options must be an array")
        options = [text(option) for option in options]
        if kind == "text":
            if options or default:
                raise ValueError("text table columns require options:[] and default:\"\"")
        elif (not options or any(not option.strip() for option in options)
              or len(set(options)) != len(options) or (default and default not in options)):
            raise ValueError("table choice options must be unique nonblank strings; default must be an option")
        columns.append({"id": cid, "label": label(column["label"]), "type": kind,
                        "options": options, "default": default})
    ids = set()
    for row in model["rows"]:
        _object(row, "id cells", "table row")
        rid = identifier(row["id"])
        if rid in ids:
            raise ValueError("duplicate table row id: " + rid)
        ids.add(rid)
        if not isinstance(row["cells"], list) or len(row["cells"]) != len(columns):
            raise ValueError("table row cells must match column width")
        cells = [text(cell) for cell in row["cells"]]
        for column, cell in zip(columns, cells):
            if column["type"] == "choice" and cell and cell not in column["options"]:
                raise ValueError("table choice cell must be empty or an authored option")
        rows.append({"id": rid, "cells": cells})
    return {"columns": columns, "rows": rows}


def validate_payload(payload):
    _object(payload, "version tables", "table payload")
    if type(payload["version"]) is not int or payload["version"] != 1:
        raise ValueError("table payload version must be 1")
    if not isinstance(payload["tables"], list):
        raise ValueError("table payload tables must be an array")
    result, ids = [], set()
    for table in payload["tables"]:
        _object(table, "id label from to", "table change")
        tid = identifier(table["id"])
        if tid in ids:
            raise ValueError("duplicate table change id: " + tid)
        ids.add(tid)
        result.append({"id": tid, "label": label(table["label"]),
                       "from": validate_model(table["from"]), "to": validate_model(table["to"])})
    return {"version": 1, "tables": result}


def _escape(value):
    return html.escape(value, quote=True)


def render_sections(model):
    model = validate_model(model)
    headers = []
    for column in model["columns"]:
        attrs = ' data-cmh-column="%s" data-cmh-column-type="%s"' % (
            column["id"], column["type"])
        if column["type"] == "choice":
            attrs += ' data-cmh-options="%s" data-cmh-default="%s"' % (
                _escape(json.dumps(column["options"], ensure_ascii=True)), _escape(column["default"]))
        headers.append("<th%s>%s</th>" % (attrs, _escape(column["label"])))
    rows = ['<tr data-cmh-row="%s">%s</tr>' % (
        row["id"], "".join("<td>%s</td>" % _escape(cell) for cell in row["cells"]))
        for row in model["rows"]]
    return {"thead": "<thead><tr>%s</tr></thead>" % "".join(headers),
            "tbody": "<tbody>%s</tbody>" % "\n".join(rows)}


def render_inner(model):
    sections = render_sections(model)
    return "\n%s\n%s\n" % (sections["thead"], sections["tbody"])


def _owner(attrs):
    return (any(key in attrs for key in OWNER_ATTRS)
            or "cmh-diff" in (attrs.get("class") or "").split())


class _Parser(_browser_attrs.BrowserTagNames):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.source = source
        self.offsets = [0] + [m.end() for m in re.finditer("\n", source)]
        self.root = {"children": [], "attrs": {}, "tag": "", "text": []}
        self.stack = [self.root]
        self.tables = []

    def _index(self):
        line, col = self.getpos()
        return self.offsets[line - 1] + col

    def handle_starttag(self, tag, attrs):
        tag = self._browser_tag(tag)
        attrs = _browser_attrs.attrs_dict(self, tag, attrs)
        node = {"tag": tag, "attrs": attrs, "children": [], "text": [],
                "start": self._index(), "inner": self._index() + len(self.get_starttag_text()),
                "end": None, "close": None, "malformed": False,
                "in_owner": any(_owner(n["attrs"]) for n in self.stack),
                "in_editable_table": any("data-cmh-table" in n["attrs"] for n in self.stack)}
        self.stack[-1]["children"].append(node)
        if "data-cmh-table" in attrs and not any(n["tag"] == "template" for n in self.stack):
            self.tables.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if self.stack[-1]["tag"] == self._browser_tag(tag):
            self.stack[-1]["malformed"] = True
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        tag = self._browser_tag(tag)
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i]["tag"] == tag:
                for node in self.stack[i + 1:]:
                    node["malformed"] = True
                node = self.stack[i]
                node["close"] = self._index()
                node["end"] = self.source.find(">", self._index()) + 1
                del self.stack[i:]
                return
        if any("data-cmh-table" in n["attrs"] for n in self.stack):
            self.stack[-1]["malformed"] = True

    def handle_data(self, data):
        self.stack[-1]["text"].append(data)

    def handle_comment(self, data):
        if self.stack[-1]["tag"] in ("th", "td"):
            self.stack[-1]["malformed"] = True

    handle_pi = handle_comment
    handle_decl = handle_comment
    unknown_decl = handle_comment


def _children(node, tag):
    children = node["children"]
    if (node["malformed"] or node["end"] is None
            or any(child["tag"] != tag for child in children)
            or "".join(node["text"]).strip()):
        raise ValueError("table requires explicit, direct %s children and closing tags" % tag)
    return children


def _plain(node):
    if node["children"] or node["malformed"] or node["end"] is None:
        raise ValueError("table header labels and cells must contain plain text only, without comments")
    return text("".join(node["text"]))


def _imply_tbody(node):
    children = node["children"]
    positions = [i for i, child in enumerate(children) if child["tag"] == "tr"]
    if not positions:
        return node
    first, last = positions[0], positions[-1]
    if (positions != list(range(first, last + 1))
            or any(child["tag"] == "tbody" for child in children)
            or not any(child["tag"] == "thead" for child in children[:first])):
        raise ValueError("table implied tbody must be one contiguous body after thead")
    rows = children[first:last + 1]
    body = {"tag": "tbody", "attrs": {}, "children": rows, "text": [],
            "malformed": False, "start": rows[0]["start"], "end": rows[-1]["end"]}
    return dict(node, children=children[:first] + [body] + children[last + 1:])


def _model(node):
    attrs = node["attrs"]
    identifier(attrs.get("data-cmh-table"))
    label(attrs.get("data-cmh-table-label"))
    if node["tag"] != "table" or node["in_editable_table"] or node["in_owner"] or _owner(attrs):
        raise ValueError("editable table must be a standalone native table, without overlapping ownership")
    pending = list(node["children"])
    while pending:
        child = pending.pop()
        if (child["tag"] == "table" or _owner(child["attrs"]) or "data-cmh-table" in child["attrs"]
                or "rowspan" in child["attrs"] or "colspan" in child["attrs"]):
            raise ValueError("table cannot contain spans, nested tables or note/checklist/widget ownership")
        if child["tag"] != "template":
            pending.extend(child["children"])
    heads = [child for child in node["children"] if child["tag"] == "thead"]
    bodies = [child for child in node["children"] if child["tag"] == "tbody"]
    if (node["malformed"] or node["end"] is None or len(heads) != 1 or len(bodies) != 1
            or any(child["tag"] not in ("caption", "thead", "tbody")
                   for child in node["children"])
            or "".join(node["text"]).strip()):
        raise ValueError("table requires one direct thead and tbody; only caption is also allowed")
    head, body = heads[0], bodies[0]
    header_rows = _children(head, "tr")
    if len(header_rows) != 1:
        raise ValueError("table requires exactly one header row")
    columns = []
    for th in _children(header_rows[0], "th"):
        attrs = th["attrs"]
        kind = attrs.get("data-cmh-column-type", "text")
        options = []
        default = ""
        if kind == "choice":
            try:
                options = json.loads(attrs.get("data-cmh-options", ""))
            except (TypeError, ValueError) as exc:
                raise ValueError("table choice options must be a JSON array") from exc
            default = attrs.get("data-cmh-default", "")
        columns.append({"id": attrs.get("data-cmh-column"), "label": _plain(th),
                        "type": kind, "options": options, "default": default})
    rows = [{"id": tr["attrs"].get("data-cmh-row"),
             "cells": [_plain(td) for td in _children(tr, "td")]}
            for tr in _children(body, "tr")]
    return validate_model({"columns": columns, "rows": rows})


def scan_tables(source):
    """Read authored models and exact table inner spans; reject ambiguous markup."""
    parser = _Parser(source)
    parser.feed(source)
    parser.close()
    result, ids = [], set()
    for node in parser.tables:
        node = _imply_tbody(node)
        tid = node["attrs"].get("data-cmh-table")
        model = _model(node)
        if tid in ids:
            raise ValueError("duplicate table id: " + tid)
        ids.add(tid)
        result.append({"id": tid, "label": label(node["attrs"].get("data-cmh-table-label")),
                       "model": model, "start": node["inner"], "end": node["close"],
                       "sections": {child["tag"]: (child["start"], child["end"])
                                    for child in node["children"]
                                    if child["tag"] in ("thead", "tbody")}})
    return result
