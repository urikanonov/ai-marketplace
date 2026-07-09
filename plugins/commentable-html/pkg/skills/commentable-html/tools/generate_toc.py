#!/usr/bin/env python3
"""Generate a commentable-html table of contents from document headings."""
import argparse
import html as html_lib
import os
import re
import sys
from html.parser import HTMLParser

HEADING_TAGS = {"h2", "h3"}
VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}
SLUG_RE = re.compile(r"[^a-z0-9]+")


def _line_starts(text):
    starts = [0]
    for match in re.finditer("\n", text):
        starts.append(match.end())
    return starts


def _attrs_dict(attrs):
    result = {}
    for key, value in attrs:
        name = (key or "").lower()
        if name not in result:
            result[name] = value if value is not None else ""
    return result


def _has_class(attrs, class_name):
    return class_name in set((attrs.get("class") or "").split())


def _end_tag_end(text, start):
    end = text.find(">", start)
    if end == -1:
        return start
    return end + 1


class _TocParser(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self._text = text
        self._starts = _line_starts(text)
        self.stack = []
        self.root_depth = None
        self.root_start_end = None
        self.all_ids = []
        self.headings = []
        self.toc_spans = []
        self._heading = None
        self._toc_depth = 0
        self._toc_start = None

    def _idx(self):
        line, col = self.getpos()
        return self._starts[line - 1] + col

    def _in_template(self):
        return any(tag == "template" for tag, _skip in self.stack)

    def _skip_ancestor(self):
        return any(skip for _tag, skip in self.stack)

    def _inside_root(self):
        return self.root_depth is not None and len(self.stack) > self.root_depth

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attrs_dict = _attrs_dict(attrs)
        own_skip = _has_class(attrs_dict, "cm-skip")
        start = self._idx()
        start_text = self.get_starttag_text() or ""
        if tag == "nav" and self._toc_depth:
            self._toc_depth += 1
        elif (tag == "nav" and self._inside_root() and not self._in_template()
              and _has_class(attrs_dict, "cm-toc")):
            self._toc_start = start
            self._toc_depth = 1

        if not self._in_template():
            element_id = attrs_dict.get("id")
            if element_id:
                self.all_ids.append(element_id)
                if element_id == "commentRoot" and self.root_start_end is None:
                    self.root_depth = len(self.stack)
                    self.root_start_end = start + len(start_text)

        if (tag in HEADING_TAGS and self._heading is None and self._inside_root()
                and not own_skip and not self._skip_ancestor() and not self._in_template()):
            self._heading = {
                "tag": tag,
                "id": attrs_dict.get("id"),
                "text_parts": [],
                "start": start,
                "start_text": start_text,
            }

        if tag not in VOID_TAGS:
            self.stack.append((tag, own_skip))

    def handle_startendtag(self, tag, attrs):
        if tag.lower() not in VOID_TAGS:
            self.handle_starttag(tag, attrs)
            return
        tag = tag.lower()
        attrs_dict = _attrs_dict(attrs)
        if not self._in_template():
            element_id = attrs_dict.get("id")
            if element_id:
                self.all_ids.append(element_id)

    def handle_data(self, data):
        if self._heading is not None:
            self._heading["text_parts"].append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if self._heading is not None and tag == self._heading["tag"]:
            text = re.sub(r"\s+", " ", "".join(self._heading["text_parts"])).strip()
            if text:
                self.headings.append({
                    "tag": self._heading["tag"],
                    "id": self._heading["id"],
                    "text": text,
                    "start": self._heading["start"],
                    "start_text": self._heading["start_text"],
                })
            self._heading = None

        if tag == "nav" and self._toc_depth:
            self._toc_depth -= 1
            if self._toc_depth == 0:
                self.toc_spans.append((self._toc_start, _end_tag_end(self._text, self._idx())))
                self._toc_start = None

        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                return


def _parse(html):
    parser = _TocParser(html)
    parser.feed(html)
    parser.close()
    return parser


def _slug(text):
    value = SLUG_RE.sub("-", text.lower()).strip("-")
    return value or "section"


def _unique_slug(text, used):
    base = _slug(text)
    candidate = base
    suffix = 2
    while candidate in used:
        candidate = "%s-%d" % (base, suffix)
        suffix += 1
    used.add(candidate)
    return candidate


def _heading_items(parser):
    used = set(parser.all_ids)
    items = []
    for heading in parser.headings:
        heading_id = heading["id"]
        generated = False
        if not heading_id:
            heading_id = _unique_slug(heading["text"], used)
            generated = True
        items.append({
            "tag": heading["tag"],
            "id": heading_id,
            "text": heading["text"],
            "start": heading["start"],
            "start_text": heading["start_text"],
            "generated": generated,
        })
    return items


def _render_nav(items):
    lines = [
        '<nav class="cm-toc" aria-label="Table of contents">',
        '  <div class="cm-toc-title">Contents</div>',
        "  <ol>",
    ]
    for item in items:
        class_attr = ' class="is-sub"' if item["tag"] == "h3" else ""
        href = html_lib.escape("#" + item["id"], quote=True)
        text = html_lib.escape(item["text"], quote=False)
        lines.append('    <li%s><a href="%s">%s</a></li>' % (class_attr, href, text))
    lines.extend(["  </ol>", "</nav>"])
    return "\n".join(lines)


def build_toc(html):
    """Return a nav.cm-toc snippet for h2 and h3 headings inside #commentRoot."""
    return _render_nav(_heading_items(_parse(html)))


def _id_insert_pos(start, start_text):
    gt = start_text.rfind(">")
    if gt == -1:
        return start + len(start_text)
    before_gt = start_text[:gt].rstrip()
    if before_gt.endswith("/"):
        return start + len(before_gt) - 1
    return start + gt


def _leading_ws_end(html, start):
    end = start
    while end < len(html) and html[end] in " \t\r\n":
        end += 1
    return end


def _toc_removal_span(html, start, end):
    return start, _leading_ws_end(html, end)


def _dominant_newline(html):
    crlf = html.count("\r\n")
    lf = html.count("\n") - crlf
    return "\r\n" if crlf > lf else "\n"


def rewrite_html(html):
    """Return HTML with generated ids injected and nav.cm-toc placed under #commentRoot."""
    parser = _parse(html)
    if parser.root_start_end is None:
        raise ValueError('no element with id="commentRoot" found')
    items = _heading_items(parser)
    newline = _dominant_newline(html)
    nav = _render_nav(items).replace("\n", newline)
    edits = []
    for item in items:
        if item["generated"]:
            pos = _id_insert_pos(item["start"], item["start_text"])
            edits.append((pos, pos, ' id="%s"' % item["id"]))
    for start, end in parser.toc_spans:
        edits.append((*_toc_removal_span(html, start, end), ""))
    edits.append((parser.root_start_end, _leading_ws_end(html, parser.root_start_end), newline + nav + newline))

    out = html
    for start, end, replacement in sorted(edits, key=lambda edit: (edit[0], edit[1]), reverse=True):
        out = out[:start] + replacement + out[end:]
    return out


def main(argv):
    parser = argparse.ArgumentParser(description="Generate a commentable-html table of contents.")
    parser.add_argument("file", help="HTML file to read")
    parser.add_argument("--in-place", action="store_true", help="rewrite the file with the generated table of contents")
    args = parser.parse_args(argv[1:])

    if not os.path.exists(args.file):
        sys.stderr.write("generate_toc: file not found: %s\n" % args.file)
        return 1
    try:
        with open(args.file, "r", encoding="utf-8", newline="") as handle:
            source = handle.read()
        if args.in_place:
            rewritten = rewrite_html(source)
            with open(args.file, "w", encoding="utf-8", newline="") as handle:
                handle.write(rewritten)
            print("updated %s" % args.file)
        else:
            print(build_toc(source))
    except (OSError, ValueError) as exc:
        sys.stderr.write("generate_toc: %s\n" % exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
