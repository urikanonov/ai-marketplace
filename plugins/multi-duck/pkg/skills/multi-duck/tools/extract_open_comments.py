#!/usr/bin/env python3
"""Extract the plan text and open inline comments from a commentable-HTML plan.

Given the path to a commentable-HTML file, print the doc label/source, the count and body of the
OPEN inline comments (every embedded comment whose id is NOT in handledCommentIds), and the rendered
plan text (the #commentRoot element, falling back to <body>). Read the HTML file as the source of
truth; never touch the browser localStorage.

Usage: python extract_open_comments.py <path-to-file.html>

Ships with the multi-duck skill so the panel does not rehydrate this parser from the SKILL.md on
every run. Standard library only, so it stays portable across hosts and operating systems.
"""
import json, re, sys
from html.parser import HTMLParser
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
html = open(sys.argv[1], encoding="utf-8", errors="replace").read()

def script_json(idv):
    # Require a whitespace-delimited id so data-id / aria-id decoys cannot match.
    m = re.search(r'<script\b[^>]*\sid\s*=\s*["\']%s["\'][^>]*>(.*?)</script>' % re.escape(idv),
                  html, re.I | re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(1).strip() or "[]")
    except Exception:
        return []
    return data if isinstance(data, list) else []

def cid(c):
    i = c.get("id")
    return i if isinstance(i, (str, int)) else None

embedded = [c for c in script_json("embeddedComments") if isinstance(c, dict)]
handled = {i for i in script_json("handledCommentIds") if isinstance(i, (str, int))}
open_c = [c for c in embedded if cid(c) not in handled]

def where(c):
    if c.get("section"):
        return c["section"]
    path = c.get("headingPath")
    if isinstance(path, list):
        crumb = " > ".join(h.get("text", "") for h in path if isinstance(h, dict))
        if crumb:
            return crumb
    return c.get("where") or c.get("anchor") or ""

class _Doc(HTMLParser):
    # HTMLParser ignores <!-- comments -->, so a commented-out demo #commentRoot is skipped for free.
    VOID = {"area","base","br","col","embed","hr","img","input","link","meta","param","source","track","wbr"}
    def __init__(self, root_id=None, root_tag=None):
        super().__init__(); self.parts = []; self._stack = []; self._skip = 0
        self.root_id = root_id; self.root_tag = root_tag; self._cap = None
        self.label = ""; self.source = ""
    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"): self._skip += 1
        if tag not in self.VOID:
            self._stack.append(tag)
            a = dict(attrs)
            if self._cap is None and (a.get("id") == self.root_id or tag == self.root_tag):
                self._cap = len(self._stack)
                self.label = a.get("data-doc-label") or self.label
                self.source = a.get("data-doc-source") or self.source
    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip: self._skip -= 1
        if tag not in self.VOID and self._stack:
            if self._cap is not None and self._cap == len(self._stack): self._cap = None
            self._stack.pop()
    def handle_data(self, data):
        if not self._skip and self._cap is not None and data.strip():
            self.parts.append(data.strip())

root = _Doc(root_id="commentRoot"); root.feed(html)
text = " ".join(root.parts)
if not text:
    body = _Doc(root_tag="body"); body.feed(html); text = " ".join(body.parts)

print("LABEL:", root.label); print("SOURCE:", root.source)
print("OPEN_COMMENTS:", len(open_c), "of", len(embedded), "embedded")
for c in open_c:
    quote = (c.get("quote") or c.get("nodeLabel") or "")[:200]
    note = c.get("note") or c.get("text") or ""
    print(f'- [{cid(c)}] {where(c)} | quoted: {quote!r} | note: {note}')
print("PLAN_TEXT:", text[:200000])
