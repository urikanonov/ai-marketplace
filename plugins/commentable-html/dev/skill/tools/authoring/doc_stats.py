#!/usr/bin/env python3
"""Compute and inject a commentable-html document-overview strip.

The strip reports how many sections the document has, its word count, and an approximate
reading time. It is a `cm-skip` block placed directly under the <h1> title inside
#commentRoot, so it is not itself commentable, is excluded from its own word count, and
survives Plain / Standalone exports (it is baked into the content, not runtime-only).

Sections are the <h2> headings inside #commentRoot; words are the visible text of the
content, excluding chrome (`cm-skip`), navigation (`nav.cm-toc`), and `script`/`style`/
`template` bodies; reading time is words / words-per-minute, rounded up with a floor of one
minute. Re-running refreshes the counts in place, so the tool is idempotent.
"""
import argparse
import html as html_lib
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tools/ root
import _browser_boundaries  # noqa: E402

DEFAULT_WPM = 200
STATS_ATTR = "data-cmh-doc-stats"
# Element bodies whose text is never part of the reading content.
SKIP_TAGS = {"script", "style", "template"}


def _has_class(attrs, class_name):
    return class_name in set((attrs.get("class") or "").split())


def _is_word(token):
    return any(ch.isalnum() for ch in token)


class _StatsParser(_browser_boundaries.BrowserBoundaries):
    """Count the sections and words a reader sees.

    Derives from the SHARED element boundaries (CMH-VAL-21), so an `<h2>` a reader only SEES quoted
    inside a raw-text body (`<textarea>`, `<title>`, `<noscript>`, ...), inside a comment or behind
    a bogus `<![CDATA[` marked section is not a section of the document - the same view the
    validator takes, and the same on every interpreter. The element stack runs parallel to the
    shared namespace stack.
    """

    def __init__(self, text):
        super().__init__(text)
        self._text = text
        self.stack = []                 # [(tag, opens_skip_subtree)]
        self.root_depth = None
        self.root_closed = False
        self.root_start_end = None
        self.section_count = 0
        self.text_parts = []
        self._title_index = None
        self.title_container_end = None
        self.stats_start = None
        self.stats_end = None
        self.stats_own_close = False
        self._stats_index = None

    def _truncate_stacks(self, depth):
        # EVERY close runs through here - the element's own end tag, an ANCESTOR's end tag, HTML5's
        # implicit `</p>` / `</li>`, a foreign-content breakout, and end of input - so a span keyed
        # on a stack index can never run past the element a browser closed. That matters here
        # because `doc_stats` REPLACES the bytes between `stats_start` and `stats_end`. Only the
        # element's OWN end tag belongs to it: an ancestor's `</section>` closes it at the START of
        # that tag, so the span must not swallow the ancestor's closer.
        if (self._title_index is not None and self.title_container_end is None
                and depth <= self._title_index):
            self.title_container_end = self._extent_end(depth == self._title_index)
        if (self._stats_index is not None and self.stats_end is None
                and depth <= self._stats_index):
            own = self._end_tag_close and depth == self._stats_index
            self.stats_end = self._extent_end(own)
            # Only a strip the browser closed with its OWN end tag has a span a rewrite may
            # REPLACE: one an ancestor's closer (or end of input) ended runs past every following
            # sibling, so replacing it would take the document's body with it.
            self.stats_own_close = own
        if self.root_depth is not None and depth <= self.root_depth:
            self.root_closed = True
        super()._truncate_stacks(depth)
        del self.stack[depth:]

    def _extent_end(self, own):
        return (_browser_boundaries.end_tag_end(self._text, self._off())
                if (self._end_tag_close and own) else self._off())

    def _inside_root(self):
        return (self.root_depth is not None and not self.root_closed
                and len(self.stack) > self.root_depth)

    def _skip_ancestor(self):
        return any(skip for _tag, skip in self.stack)

    def _visit_start(self, tag, ad, ns, opens):
        # The shared browser attribute decode (CMH-VAL-21), so a class token this tool reads is
        # the token a browser sees - and the one the validator sees.
        attrs_dict = ad
        start = self._off()
        start_text = self.get_starttag_text() or ""
        is_stats = STATS_ATTR in attrs_dict
        own_skip = (
            _has_class(attrs_dict, "cm-skip")
            or tag in SKIP_TAGS
            or is_stats
            or (tag == "nav" and _has_class(attrs_dict, "cm-toc"))
        )

        if attrs_dict.get("id") == "commentRoot" and self.root_start_end is None:
            self.root_depth = len(self.stack)
            self.root_start_end = start + len(start_text)

        inside_root = self._inside_root()
        skip_ancestor = self._skip_ancestor()

        if (tag == "h2" and inside_root and not own_skip and not skip_ancestor):
            self.section_count += 1

        if (tag == "h1" and inside_root and not own_skip and not skip_ancestor
                and self._title_index is None):
            # The title's top-level container is the direct child of #commentRoot at this
            # index, whether that is the <h1> itself or a wrapper (e.g. header.cmh-lede).
            self._title_index = self.root_depth + 1

        # A VOID element has no body, so it can never be the strip this tool replaces.
        if is_stats and opens and self.stats_start is None:
            self.stats_start = start
            self._stats_index = len(self.stack)
        return own_skip

    def _push_element(self, tag, ad, ns, info):
        self.stack.append((tag, info))

    def handle_data(self, data):
        if self._inside_root() and not self._skip_ancestor():
            self.text_parts.append(data)

    def word_count(self):
        tokens = " ".join(self.text_parts).split()
        return sum(1 for token in tokens if _is_word(token))

    def close(self):
        super().close()
        # A browser closes whatever is still open at end of input, so a title container or a
        # doc-stats strip left unclosed ends there rather than never - otherwise a re-run inserted
        # a SECOND strip and left the stale one behind.
        self._truncate_stacks(0)


def _parse(html):
    parser = _StatsParser(html)
    parser.parse_document(html)
    return parser


def count_sections(html):
    """Return the number of <h2> sections inside #commentRoot (chrome/cm-skip excluded)."""
    return _parse(html).section_count


def count_words(html):
    """Return the reading word count of #commentRoot content.

    Excludes cm-skip chrome, nav.cm-toc navigation, and script/style/template bodies, and
    counts only whitespace-separated tokens that contain at least one alphanumeric character.
    """
    return _parse(html).word_count()


def reading_minutes(words, wpm=DEFAULT_WPM):
    """Approximate reading time in whole minutes, rounded up with a floor of one minute."""
    if wpm <= 0:
        wpm = DEFAULT_WPM
    return max(1, math.ceil(words / wpm))


def _plural(count, singular):
    return singular if count == 1 else singular + "s"


def build_stats_block(sections, words, minutes):
    """Return the cm-skip document-overview block for the given counts."""
    label = "Document overview: %s, %s, about %d min read" % (
        "%d %s" % (sections, _plural(sections, "section")),
        "%s %s" % (format(words, ","), _plural(words, "word")),
        minutes,
    )
    lines = [
        '<div class="cmh-doc-stats cm-skip" %s="1" role="note" aria-label="%s">'
        % (STATS_ATTR, html_lib.escape(label, quote=True)),
        '<span class="cmh-doc-stat"><strong>%d</strong> %s</span>'
        % (sections, _plural(sections, "section")),
        '<span class="cmh-doc-stat"><strong>%s</strong> %s</span>'
        % (format(words, ","), _plural(words, "word")),
        '<span class="cmh-doc-stat">~<strong>%d</strong> min read</span>' % minutes,
        "</div>",
    ]
    return "\n".join(lines)


def compute(html, wpm=DEFAULT_WPM):
    """Return (sections, words, minutes) for the document."""
    parser = _parse(html)
    words = parser.word_count()
    return parser.section_count, words, reading_minutes(words, wpm)


def _dominant_newline(html):
    crlf = html.count("\r\n")
    lf = html.count("\n") - crlf
    return "\r\n" if crlf > lf else "\n"


def rewrite_html(html, wpm=DEFAULT_WPM):
    """Return HTML with the document-overview block inserted or refreshed in place.

    Raises ValueError when there is no element with id="commentRoot".
    """
    parser = _parse(html)
    if parser.root_start_end is None:
        raise ValueError('no element with id="commentRoot" found')
    words = parser.word_count()
    block = build_stats_block(parser.section_count, words, reading_minutes(words, wpm))
    newline = _dominant_newline(html)
    block = block.replace("\n", newline)

    # An UNCLOSED strip is not replaced: its extent runs past every following sibling, so the
    # replace would delete the document's body. The non-destructive anchor insert is used instead.
    if (parser.stats_start is not None and parser.stats_end is not None
            and parser.stats_own_close):
        return html[:parser.stats_start] + block + html[parser.stats_end:]

    anchor = parser.title_container_end
    if anchor is None:
        anchor = parser.root_start_end
    return html[:anchor] + newline + block + html[anchor:]


def main(argv):
    parser = argparse.ArgumentParser(
        prog="doc_stats.py",
        description="Compute or inject the section / word / reading-time overview strip.")
    parser.add_argument("file", help="HTML file to read")
    parser.add_argument("--in-place", action="store_true",
                        help="rewrite the file with the overview strip inserted or refreshed")
    parser.add_argument("--wpm", type=int, default=DEFAULT_WPM,
                        help="words per minute for the reading-time estimate (default %d)" % DEFAULT_WPM)
    args = parser.parse_args(argv[1:])

    if not os.path.exists(args.file):
        sys.stderr.write("doc_stats: file not found: %s\n" % args.file)
        return 1
    try:
        with open(args.file, "r", encoding="utf-8", newline="") as handle:
            source = handle.read()
        if args.in_place:
            rewritten = rewrite_html(source, wpm=args.wpm)
            with open(args.file, "w", encoding="utf-8", newline="") as handle:
                handle.write(rewritten)
            print("updated %s" % args.file)
        else:
            sections, words, minutes = compute(source, wpm=args.wpm)
            print("%d %s, %s %s, ~%d min read" % (
                sections, _plural(sections, "section"),
                format(words, ","), _plural(words, "word"), minutes))
    except (OSError, ValueError) as exc:
        sys.stderr.write("doc_stats: %s\n" % exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
