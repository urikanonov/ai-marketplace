#!/usr/bin/env python3
"""Wrap bare top-level <h2> blocks in <section> so report/plan docs render as cards.

A report or plan renders as a stack of boxed section cards, styled from
`#commentRoot > section`. A document whose content sits under bare top-level <h2>
headings with no <section> wrapper passes every structural check yet renders as a flat,
off-brand page (validate.py's check_section_wrapping (CMH-VAL-14) warns on exactly this). This
tool is the deterministic auto-fix: it wraps each top-level <h2>-led block - the <h2> plus the
sibling elements that follow it, up to the next top-level <h2> - in
`<section aria-labelledby="the-h2-id">...</section>`.

"Top level" means a direct child of the content scope: for a bare content fragment that
is a direct child of the fragment root; for a full document it is a direct child of the
#commentRoot element (fix() locates that element's inner HTML). Content that precedes the
first top-level <h2> (the <h1> title, a `cmh-lede`, intro callouts) is left above the
cards, matching the worked examples.

Idempotent and conservative: if the scope already contains a top-level <section>, or has
fewer than one top-level <h2>, nothing is wrapped. Scope to report/plan is the caller's
job (new_document.py gates on --kind; the CLI/finalize path reads the kind meta), so this
module never needs to know the kind.

Usage:
    python tools/wrap_sections.py <file.html>            # wrap in place (full doc)
    python tools/wrap_sections.py <file.html> --check     # report only, exit 1 if any bare
    python tools/wrap_sections.py <file.html> --out FILE  # write the wrapped doc elsewhere
    python tools/wrap_sections.py --fragment frag.html    # treat input as a bare fragment

Exit code 0 on success (including "nothing to wrap"), 1 on error or (with --check) when at
least one top-level <h2> block is unwrapped.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tools/ root
import _browser_boundaries  # noqa: E402


class _TopLevelLocator(_browser_boundaries.BrowserBoundaries):
    """Locate direct-child <h2> start tags (and any direct-child <section>) in a fragment.

    The SHARED element boundaries decide what an element even is (CMH-VAL-21), so an <h2> or
    <section> a reader only SEES quoted inside a raw-text body (`<textarea>`, `<title>`,
    `<noscript>`, ...), inside a comment or behind a bogus `<![CDATA[` marked section is text,
    exactly as it is to a browser and to the validator - and the same on every interpreter. That
    matters more here than in a read-only check: this tool INSERTS bytes at the offsets it reports,
    so an element a browser never builds would move the edit into someone's prose.

    The shared base runs the tag handlers (so the void, foreign self-closing, implicit-close and
    raw-text steps are not repeated here); this class only collects, and pushes its element stack
    parallel to the shared namespace stack through `_push_element()`.
    """

    def __init__(self, html):
        super().__init__(html)
        self.stack = []          # open non-void tag names
        self.h2_starts = []      # [(start_offset, id_or_None)] for direct-child <h2>
        self.has_top_section = False

    def _truncate_stacks(self, depth):
        super()._truncate_stacks(depth)
        del self.stack[depth:]

    def _record(self, tag, ad):
        if not self.stack:  # direct child of the scope root
            if tag == "h2":
                self.h2_starts.append((self._off(), ad.get("id")))
            elif tag == "section":
                self.has_top_section = True

    def _visit_start(self, tag, ad, ns, opens):
        self._record(tag, ad)

    def _push_element(self, tag, ad, ns, info):
        self.stack.append(tag)


def wrap_fragment(html):
    """Wrap each bare top-level <h2> block of a content fragment in a <section>.

    Returns (new_html, count) where count is the number of sections created. Byte-for-byte
    identical to the input when nothing is wrapped; idempotent when re-run (a fragment that
    already has a top-level <section> is returned unchanged).
    """
    locator = _TopLevelLocator(html)
    try:
        locator.parse_document(html)
    except Exception:
        return html, 0
    if locator.has_top_section or not locator.h2_starts:
        return html, 0

    starts = locator.h2_starts
    content_end = len(html)
    first = starts[0][0]
    out = [html[:first]]
    for i, (start, hid) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else content_end
        chunk = html[start:end].rstrip()
        aria = ' aria-labelledby="%s"' % hid if hid else ""
        out.append("<section%s>\n%s\n</section>\n" % (aria, chunk))
    out.append(html[content_end:])
    return "".join(out), len(starts)


class _ContentRootLocator(_browser_boundaries.BrowserBoundaries):
    """Locate the inner-HTML span of the #commentRoot element in a full document.

    Records the offset immediately after the #commentRoot start tag and the offset of the end tag
    that closes it, tracking the element stack so a nested element of the same tag name does not
    close the region early - and so an ANCESTOR's end tag, which a browser closes the root with
    too, does.

    The SHARED element boundaries (CMH-VAL-21) decide which start tags exist at all, so a decoy
    `<main id="commentRoot">` a reader only sees quoted inside a raw-text body, a comment or a
    bogus `<![CDATA[` marked section is not the content root and the wrapping stays scoped to the
    element a browser calls #commentRoot.
    """

    def __init__(self, html):
        super().__init__(html)
        self.stack = []
        self._root_index = None
        self.inner_start = None
        self.inner_end = None

    def _truncate_stacks(self, depth):
        super()._truncate_stacks(depth)
        del self.stack[depth:]

    def _before_truncate(self, depth):
        # The root can also be closed WITHOUT its own end tag: HTML5's implicit `</p>` / `</li>`
        # close, or a breakout start tag popping foreign content. A browser ends the root's content
        # right there, so the region does too - otherwise the wrapping would rewrite the sibling
        # content a browser puts OUTSIDE the root.
        if (self._root_index is not None and self.inner_end is None
                and depth <= self._root_index):
            self.inner_end = self._off()

    def _visit_start(self, tag, ad, ns, opens):
        # A void element has no inner HTML, so it can never be the content root.
        if opens and self.inner_start is None and ad.get("id") == "commentRoot":
            self._root_index = len(self.stack)
            self.inner_start = self._start_tag_end()

    def _push_element(self, tag, ad, ns, info):
        self.stack.append(tag)

    def _visit_end(self, tag, index):
        if (index >= 0 and self._root_index is not None and self.inner_end is None
                and index <= self._root_index):
            self.inner_end = self._off()


def _locate_content_region(html):
    """Return (inner_start, inner_end) of the #commentRoot body, or None if not found."""
    loc = _ContentRootLocator(html)
    try:
        loc.parse_document(html)
    except Exception:
        return None
    if loc.inner_start is None or loc.inner_end is None or loc.inner_end <= loc.inner_start:
        return None
    return loc.inner_start, loc.inner_end


def fix(html):
    """Wrap top-level <h2> blocks inside a full document's #commentRoot content region.

    Scopes to the inner HTML of the #commentRoot element so the surrounding layer shell is
    never touched. Returns (new_html, count). Unchanged when the region cannot be located or
    nothing needs wrapping. Kind gating is the caller's responsibility.
    """
    region = _locate_content_region(html)
    if region is None:
        return html, 0
    inner_start, inner_end = region
    inner = html[inner_start:inner_end]
    wrapped, count = wrap_fragment(inner)
    if not count:
        return html, 0
    return html[:inner_start] + wrapped + html[inner_end:], count


def main(argv):
    parser = argparse.ArgumentParser(
        prog="wrap_sections.py",
        description="Wrap bare top-level <h2> blocks in <section> so report/plan documents "
                    "render as boxed section cards.",
    )
    parser.add_argument("file", help="the .html file to wrap")
    parser.add_argument("--fragment", action="store_true",
                        help="treat the input as a bare content fragment (no layer shell / "
                             "CONTENT markers) instead of a full document")
    parser.add_argument("--check", action="store_true",
                        help="report the count of unwrapped top-level <h2> blocks and exit 1 "
                             "if any, without writing")
    parser.add_argument("--out", metavar="FILE",
                        help="write the wrapped document to FILE instead of in place")
    args = parser.parse_args(argv[1:])

    if not os.path.exists(args.file):
        sys.stderr.write("wrap_sections: file not found: %s\n" % args.file)
        return 1
    try:
        with open(args.file, "r", encoding="utf-8", newline="") as fh:
            html = fh.read()
    except OSError as exc:
        sys.stderr.write("wrap_sections: %s\n" % exc)
        return 1

    new_html, count = (wrap_fragment(html) if args.fragment else fix(html))

    if args.check:
        if count:
            print("%d top-level <h2> block(s) not wrapped in <section> in %s" % (count, args.file))
            return 1
        print("no unwrapped top-level <h2> blocks in %s" % args.file)
        return 0

    out_path = args.out if args.out else args.file
    if count:
        with open(out_path, "w", encoding="utf-8", newline="") as fh:
            fh.write(new_html)
        print("wrapped %d top-level <h2> block(s) in %s" % (count, out_path))
    elif args.out:
        with open(out_path, "w", encoding="utf-8", newline="") as fh:
            fh.write(new_html)
        print("no top-level <h2> blocks to wrap in %s" % args.file)
    else:
        print("no top-level <h2> blocks to wrap in %s" % args.file)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
