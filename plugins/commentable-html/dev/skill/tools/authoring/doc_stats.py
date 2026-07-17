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
import re
import sys
from html.parser import HTMLParser

DEFAULT_WPM = 200
STATS_ATTR = "data-cmh-doc-stats"
VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}
# Element bodies whose text is never part of the reading content.
SKIP_TAGS = {"script", "style", "template"}


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


def _is_word(token):
    return any(ch.isalnum() for ch in token)


class _StatsParser(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self._text = text
        self._starts = _line_starts(text)
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
        self._stats_index = None

    def _idx(self):
        line, col = self.getpos()
        return self._starts[line - 1] + col

    def _inside_root(self):
        return (self.root_depth is not None and not self.root_closed
                and len(self.stack) > self.root_depth)

    def _skip_ancestor(self):
        return any(skip for _tag, skip in self.stack)

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attrs_dict = _attrs_dict(attrs)
        start = self._idx()
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
        is_direct_child = inside_root and len(self.stack) == self.root_depth + 1

        if (tag == "h2" and inside_root and not own_skip and not skip_ancestor):
            self.section_count += 1

        if (tag == "h1" and inside_root and not own_skip and not skip_ancestor
                and self._title_index is None):
            # The title's top-level container is the direct child of #commentRoot at this
            # index, whether that is the <h1> itself or a wrapper (e.g. header.cmh-lede).
            self._title_index = self.root_depth + 1

        if is_stats and self.stats_start is None:
            self.stats_start = start
            self._stats_index = len(self.stack)

        if tag not in VOID_TAGS:
            self.stack.append((tag, own_skip))
        # A direct child kept for symmetry; is_direct_child is consumed above via _title_index.
        _ = is_direct_child

    def handle_startendtag(self, tag, attrs):
        if tag.lower() not in VOID_TAGS:
            self.handle_starttag(tag, attrs)

    def handle_data(self, data):
        if self._inside_root() and not self._skip_ancestor():
            self.text_parts.append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                if self._title_index is not None and index == self._title_index and self.title_container_end is None:
                    self.title_container_end = _end_tag_end(self._text, self._idx())
                if self._stats_index is not None and index == self._stats_index and self.stats_end is None:
                    self.stats_end = _end_tag_end(self._text, self._idx())
                if self.root_depth is not None and index <= self.root_depth:
                    self.root_closed = True
                del self.stack[index:]
                return

    def word_count(self):
        tokens = " ".join(self.text_parts).split()
        return sum(1 for token in tokens if _is_word(token))


def _parse(html):
    parser = _StatsParser(html)
    parser.feed(html)
    parser.close()
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

    if parser.stats_start is not None and parser.stats_end is not None:
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
