#!/usr/bin/env python3
"""Build escaped cmh-diff blocks from unified diffs."""
import argparse
import difflib
import html
import os
import re
import sys

_WARN_LINE_THRESHOLD = 2000

_NO_NEWLINE_MARKER = "\\ No newline at end of file"
_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@")


def _normalize_newlines(text):
    return text.replace("\r\n", "\n").replace("\r", "\n")


def render_diff_block(diff_text, label, lang=None):
    """Return a cmh-diff pre block with escaped diff text."""
    normalized = _normalize_newlines(diff_text)
    attrs = ['class="cmh-diff"', 'data-diff-label="%s"' % html.escape(label, quote=True)]
    if lang:
        attrs.append('data-diff-lang="%s"' % html.escape(lang, quote=True))
    return "<pre %s>%s</pre>" % (" ".join(attrs), html.escape(normalized, quote=False))


def unified_diff(old_text, new_text, label):
    """Return a deterministic unified diff with LF line endings.

    Lines are compared with their terminators kept, so a difference that is ONLY a
    missing final newline is not erased (splitlines() would drop it). A file whose last
    line lacks a trailing newline is annotated with the standard git marker
    `\\ No newline at end of file`, matching what real diff tooling emits.
    """
    normalized_old = _normalize_newlines(old_text)
    normalized_new = _normalize_newlines(new_text)
    raw = difflib.unified_diff(
        normalized_old.splitlines(keepends=True),
        normalized_new.splitlines(keepends=True),
        fromfile="a/%s" % label,
        tofile="b/%s" % label,
        lineterm="",
    )
    out = []
    seen_hunk = False
    for line in raw:
        if not seen_hunk and (line.startswith("--- ") or line.startswith("+++ ")):
            out.append(line)
            continue
        if _HUNK_RE.match(line):
            seen_hunk = True
            out.append(line)
            continue
        if line.endswith("\n"):
            out.append(line[:-1])
        else:
            out.append(line)
            out.append(_NO_NEWLINE_MARKER)
    return "\n".join(out)


def _build_parser():
    parser = argparse.ArgumentParser(description="Render commentable-html diff blocks.")
    parser.add_argument("--label", help="label for a provided unified diff")
    parser.add_argument("--lang", help="optional language for syntax highlighting")
    parser.add_argument("--from-files", nargs=2, metavar=("OLD", "NEW"), help="generate unified diff from two files")
    parser.add_argument("--diff-label", help="label used by --from-files output and generated diff headers")
    parser.add_argument("diff_file", nargs="?", default="-", help="unified diff file path, or - for stdin")
    return parser


def _read_text(path):
    with open(path, "rb") as handle:
        return handle.read().decode("utf-8", errors="replace")


def _warn_if_large(diff_text):
    if not diff_text:
        return
    logical_lines = diff_text.count("\n") + 1
    if logical_lines > _WARN_LINE_THRESHOLD:
        sys.stderr.write(
            "diff_block: warning - diff has %d lines; rendering may fall back to inert text for very large diffs.\n"
            % logical_lines
        )


def main(argv=None):
    parser = _build_parser()
    if argv is None:
        argv = sys.argv[1:]
    try:
        args = parser.parse_args(argv)
        if args.from_files:
            if args.diff_file != "-":
                parser.error("diff_file positional argument is not allowed with --from-files")
            label = args.diff_label if args.diff_label is not None else os.path.basename(args.from_files[1])
            old_text = _read_text(args.from_files[0])
            new_text = _read_text(args.from_files[1])
            diff_text = unified_diff(old_text, new_text, label)
        else:
            if args.diff_label is not None:
                parser.error("--diff-label requires --from-files")
            if not args.label:
                parser.error("--label is required unless --from-files is used")
            if args.diff_file == "-":
                diff_text = sys.stdin.buffer.read().decode("utf-8", errors="replace")
            else:
                diff_text = _read_text(args.diff_file)
            label = args.label
    except SystemExit as exc:
        return int(exc.code)
    except OSError as exc:
        sys.stderr.write("diff_block: %s\n" % exc)
        return 2

    normalized = _normalize_newlines(diff_text)
    _warn_if_large(normalized)
    sys.stdout.write(render_diff_block(normalized, label, args.lang))
    return 0


if __name__ == "__main__":
    sys.exit(main())
