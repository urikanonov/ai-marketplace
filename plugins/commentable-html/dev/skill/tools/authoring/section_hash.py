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
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tools/ root
import _browser_attrs  # noqa: E402
import _browser_boundaries  # noqa: E402

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


class _SectionParser(_browser_boundaries.BrowserBoundaries):
    """Collect the content-root text with cm-skip / script / style subtrees excluded, and record
    each heading's (id, level, start-offset, end-offset). convert_charrefs=True so entities arrive
    decoded, like DOM textContent."""

    _track_offsets = False

    def __init__(self, single_root=False, html=""):
        super().__init__("")
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

    def _in_html_template(self):
        return bool(self._tpl_stop) and self._tpl_stop[-1] >= 0

    def _visit_start(self, tag_l, d, ns, opens):
        if self._stack:
            self._stack[-1]["strip_lf"] = False
        classes = (d.get("class") or "").split()
        # HTML5's h1-h6 start tag pops an open heading that is the CURRENT node, so a heading whose
        # end tag never arrived stops here instead of running on to collect the rest of the
        # document as its own text. The rule is STRUCTURAL - a browser pops whatever open heading
        # is the current node - so a heading excluded from the hash is popped too; keyed on `hidx`
        # instead, an unterminated cm-skip heading stayed open and the VISIBLE heading after it
        # inherited its skip, dropping a section a browser renders. This runs BEFORE the skip
        # inheritance below so that inheritance is read off the heading's parent, as in the DOM.
        # Mirrors the validator's _DocParser (CMH-VAL-21).
        if (ns == "html" and _HEADING_RE.match(tag_l) and self._stack
                and _HEADING_RE.match(self._stack[-1]["tag"])):
            self._truncate_stacks(len(self._stack) - 1)
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
        is_root = not self._in_html_template() and (
            (d.get("id") == "commentRoot") if self.single_root
            else ((d.get("id") == "commentRoot") or ("data-cmh-content-root" in d))
        )
        entry = {
            "tag": tag_l,
            "skip": skip,
            "hidx": None,
            "strip_lf": ns == "html" and tag_l in ("pre", "textarea", "listing"),
        }
        # Open the root only when not already inside one and, in single_root mode, only the first
        # one (found_root latches True) - a later id=commentRoot never re-opens a subtree.
        if (is_root and self._root_depth is None
                and not (self.single_root and self.found_root)):
            self._root_depth = len(self._stack) + 1
            self.found_root = True
        if self._in_root() and not skip and _HEADING_RE.match(tag_l):
            entry["hidx"] = len(self.headings)
            self.headings.append({"id": d.get("id") or "", "level": int(tag_l[1]),
                                  "start": self.length, "end": None})
        return entry

    def _push_element(self, _tag, _ad, _ns, entry):
        self._stack.append(entry)

    def _visit_void(self, _tag, _ad, _ns, _entry):
        self._truncate_stacks(len(self._stack))

    def _visit_end(self, tag_l, index):
        if self._stack:
            self._stack[-1]["strip_lf"] = False
        # In the HTML namespace, these end tags only switch insertion mode without popping. A
        # same-named foreign element is ordinary content and still closes normally.
        return not (index >= 0 and tag_l in ("body", "html")
                    and self._ns[index][1] == "html")

    def _truncate_stacks(self, index):
        """Pop the open-element stack back to `index`, applying every boundary that depth ends.

        A heading the popped subtree holds ends there, and so does the content root when an
        ANCESTOR of it closes: only the root's OWN end tag used to end it, so an unterminated root
        an ancestor closed over (`<section><main id="commentRoot">...</section>`) kept collecting
        the text and the headings a browser puts outside it into the last section. The validator's
        `_DocParser` and the table-of-contents parser read those two boundaries the same way
        (CMH-VAL-21).
        """
        for entry in self._stack[index:]:
            hidx = entry.get("hidx")
            if hidx is not None and self.headings[hidx]["end"] is None:
                self.headings[hidx]["end"] = self.length
        if self._root_depth is not None and (index + 1) <= self._root_depth:
            self._root_depth = None
        super()._truncate_stacks(index)
        del self._stack[index:]

    def close(self):
        """End a heading still open at end of input, so the PARSER owns that boundary rather than
        leaving each caller to guess it. A browser renders a heading whose end tag never arrives,
        so its text runs to the end of the document. The host's own close() runs FIRST so trailing
        text it is still holding is counted before the ends are stamped."""
        super().close()
        for heading in self.headings:
            if heading["end"] is None:
                heading["end"] = self.length

    def handle_data(self, data):
        if self._stack and self._stack[-1]["strip_lf"]:
            self._stack[-1]["strip_lf"] = False
            if data.startswith("\n"):
                data = data[1:]
        if (self._stack and self._ns and self._stack[-1]["tag"] in ("title", "textarea")
                and self._ns[-1][1] == "html"):
            # Shared boundaries deliberately expose every raw-text/RCDATA body as stable raw
            # source. The runtime hashes DOM textContent, so RCDATA references decode here while
            # script/style/xmp/etc. remain literal.
            data = _browser_attrs.unescape_text(data)
        if self._in_root() and not self._skipping() and data:
            self.parts.append(data)
            self.length += len(data)

    def handle_comment(self, _data):
        if self._stack:
            self._stack[-1]["strip_lf"] = False


def extract_sections(html):
    """Return a list of {id, level, headingText, hash} for every id'd heading in the content root,
    in document order. `hash` is the section content hash (heading through the next same-or-higher
    heading); `headingText` is the heading's own whitespace-collapsed text."""
    text = html or ""
    p = _SectionParser(html=text)
    p.parse_document(text)
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
    text = html or ""
    p = _SectionParser(single_root=True, html=text)
    p.parse_document(text)
    if not p.found_root:
        return None
    return cmh_section_hash("".join(p.parts))
