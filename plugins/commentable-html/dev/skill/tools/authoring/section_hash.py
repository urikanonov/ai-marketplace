#!/usr/bin/env python3
"""Section content hashing for the review-tracking feature (CMH-REVIEW).

The runtime (assets/js/84-section-review.js `cmhSectionHash`) fingerprints a section's text with a
deterministic FNV-1a (32-bit) hash so it can tell whether the section changed since it was marked
reviewed. This module reproduces that hash BYTE FOR BYTE in Python so the `mark_reviewed.py` tool can
bake matching markers, and so a committed golden fixture can pin the two implementations equal
(tests/test_section_hash_golden.py, CMH-REVIEW-08).

Two public entry points:
  - cmh_section_hash(text): the hash over an already-extracted section text string. This is the
    shared contract with the JS runtime; the golden test pins it.
  - extract_section_hashes(html): parse a layered document, and for every heading (h1-h6) inside the
    content root that is NOT inside a cm-skip subtree, return {heading_id: (level, section_hash)}.
    The section text runs from the heading up to the next heading of the same-or-higher level, with
    cm-skip subtrees, <script>, and <style> excluded - mirroring the runtime's DOM walk.
"""
import re
from html.parser import HTMLParser

# Whitespace class collapsed to a single space, matching the runtime REVIEW_WS_RE
# (/[ \t\n\r\f\v\u00a0]+/). \v is \x0b and \f is \x0c.
_WS_RE = re.compile("[ \t\n\r\f\x0b\u00a0]+")
_HEADING_RE = re.compile(r"^h[1-6]$", re.IGNORECASE)
# Element classes whose subtree the runtime rewrites at load; excluded from the hash on both sides.
_SKIP_CLASSES = frozenset(("cm-skip", "cmh-diff", "cmh-kql", "mermaid"))
# HTML void elements have no end tag, so they must never be pushed onto the open-element stack
# (a `<img class="cm-skip">` left on the stack would suppress every following sibling's text).
_VOID_ELEMENTS = frozenset((
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
))
_B36 = "0123456789abcdefghijklmnopqrstuvwxyz"


def _to_base36(n):
    if n == 0:
        return "0"
    out = ""
    while n:
        n, r = divmod(n, 36)
        out = _B36[r] + out
    return out


def cmh_section_hash(text):
    """FNV-1a (32-bit) over the whitespace-collapsed text, as base36. Identical to the runtime
    cmhSectionHash: char codes are UTF-16 code units (JS String.charCodeAt), so we iterate the
    UTF-16-LE encoding two bytes at a time."""
    s = _WS_RE.sub(" ", text or "").strip(" ")
    units = s.encode("utf-16-le")
    h = 0x811C9DC5
    for i in range(0, len(units), 2):
        cu = units[i] | (units[i + 1] << 8)
        h ^= cu
        h = (h * 0x01000193) & 0xFFFFFFFF
    return _to_base36(h)


class _SectionParser(HTMLParser):
    """Collect the content-root text with cm-skip / script / style subtrees excluded, and record
    each heading's (id, level, start-offset, end-offset). convert_charrefs=True so entities arrive
    decoded, like DOM textContent."""

    def __init__(self, single_root=False):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.length = 0
        self.headings = []          # list of dicts: {id, level, start, end}
        self._stack = []            # {tag, skip, hidx}
        self._root_depth = None
        self.found_root = False     # True once a content root was seen
        # When True, mirror the runtime document hasher exactly: the root is ONLY an id=commentRoot
        # element (not a bare data-cmh-content-root), and only the FIRST one - once it closes, no
        # later element re-opens a root. This matches getElementById("commentRoot") (first match,
        # single subtree) so document_content_hash never hashes text the runtime would not.
        self.single_root = single_root

    def _in_root(self):
        return self._root_depth is not None

    def _skipping(self):
        return bool(self._stack) and self._stack[-1]["skip"]

    def handle_starttag(self, tag, attrs):
        tag_l = tag.lower()
        # A void element opens no subtree (it has no end tag); it also contributes no text, so it is
        # simply ignored - pushing it would corrupt the stack for every following sibling.
        if tag_l in _VOID_ELEMENTS:
            return
        d = dict(attrs)
        classes = (d.get("class") or "").split()
        parent_skip = self._skipping()
        # Skip cm-skip chrome, inert script/style/template/noscript, and runtime-transformed blocks
        # (rendered diffs, KQL, mermaid, chart canvases, editable notes) - the same set the JS
        # runtime walk excludes - so the hash covers the section's stable prose and the two
        # extractors agree. noscript is excluded because with scripting ON the browser exposes its
        # markup as literal text, which would diverge from this tag-parsing extractor.
        skip = (parent_skip
                or bool(_SKIP_CLASSES.intersection(classes))
                or tag_l in ("script", "style", "template", "canvas", "noscript")
                or "data-cmh-note" in d)
        is_root = (d.get("id") == "commentRoot") if self.single_root \
            else ((d.get("id") == "commentRoot") or ("data-cmh-content-root" in d))
        entry = {"tag": tag_l, "skip": skip, "hidx": None}
        self._stack.append(entry)
        # Open the root only when not already inside one and, in single_root mode, only the first
        # one (found_root latches True) - a later id=commentRoot never re-opens a subtree.
        if (is_root and self._root_depth is None
                and not (self.single_root and self.found_root)):
            self._root_depth = len(self._stack)
            self.found_root = True
        if self._in_root() and not skip and _HEADING_RE.match(tag_l):
            entry["hidx"] = len(self.headings)
            self.headings.append({"id": d.get("id") or "", "level": int(tag_l[1]),
                                  "start": self.length, "end": None})

    def handle_startendtag(self, tag, attrs):
        pass  # void / self-closing element: opens no subtree

    def handle_endtag(self, tag):
        tag_l = tag.lower()
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i]["tag"] == tag_l:
                for entry in self._stack[i:]:
                    hidx = entry.get("hidx")
                    if hidx is not None and self.headings[hidx]["end"] is None:
                        self.headings[hidx]["end"] = self.length
                if self._root_depth is not None and (i + 1) == self._root_depth:
                    self._root_depth = None
                del self._stack[i:]
                break

    def handle_data(self, data):
        if self._in_root() and not self._skipping() and data:
            self.parts.append(data)
            self.length += len(data)


def extract_sections(html):
    """Return a list of {id, level, headingText, hash} for every id'd heading in the content root,
    in document order. `hash` is the section content hash (heading through the next same-or-higher
    heading); `headingText` is the heading's own whitespace-collapsed text."""
    p = _SectionParser()
    p.feed(html or "")
    p.close()
    full = "".join(p.parts)
    heads = p.headings
    out = []
    for i, h in enumerate(heads):
        if not h["id"]:
            continue
        sec_end = len(full)
        for j in range(i + 1, len(heads)):
            if heads[j]["level"] <= h["level"]:
                sec_end = heads[j]["start"]
                break
        h_end = h["end"] if h["end"] is not None else len(full)
        out.append({
            "id": h["id"],
            "level": h["level"],
            "headingText": _WS_RE.sub(" ", full[h["start"]:h_end]).strip(" "),
            "hash": cmh_section_hash(full[h["start"]:sec_end]),
        })
    return out


def extract_section_hashes(html):
    """Convenience map {heading_id: (level, section_hash)}."""
    return {s["id"]: (s["level"], s["hash"]) for s in extract_sections(html)}


def document_content_hash(html):
    """The WHOLE content-root text hashed once with cmh_section_hash, using the same extraction
    contract as the section hashes (cm-skip / script / style / template / canvas / .cmh-diff /
    .cmh-kql / .mermaid / [data-cmh-note] subtrees excluded). This reproduces the runtime
    cmhDocContentHash (assets/js/84-section-review.js) byte for byte, so a document that was
    strict-validated and then manually edited hashes differently and the runtime banner returns.

    Returns None when the document has no content root: without one the runtime cannot reproduce a
    matching hash, so the stamp is left un-content-bound (timestamp only) rather than risk a false
    banner on a valid document."""
    p = _SectionParser(single_root=True)
    p.feed(html or "")
    p.close()
    if not p.found_root:
        return None
    return cmh_section_hash("".join(p.parts))

