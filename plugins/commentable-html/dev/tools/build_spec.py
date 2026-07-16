#!/usr/bin/env python3
"""Assemble dev/SPEC.md from numbered topic partials.

The commentable-html feature spec is generated from dev/spec/NN-topic.md partials in directory
sort order, mirroring the runtime asset split. Use --check to verify the checked SPEC.md is in sync.
"""
import argparse
import os
import re
import sys

DEV = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.abspath(os.path.join(DEV, "..", "..", ".."))
SPEC_DIR = os.path.join(DEV, "spec")
SPEC_OUT = os.path.join(DEV, "SPEC.md")
SCRIPT = os.path.join(DEV, "tools", "build_spec.py")

GENERATED_BANNER_PREFIX = "GENERATED FILE - DO NOT EDIT."
_PART_RE = re.compile(r"^\d{2}-[a-z0-9-]+\.md$")


def _lf(text):
    return text.replace("\r\n", "\n").replace("\r", "\n")


def read(path):
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return _lf(fh.read())


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(_lf(text))


def _display(path):
    return os.path.relpath(os.path.abspath(path), REPO).replace(os.sep, "/")


def ordered_parts(spec_dir=None):
    """Return numbered Markdown partials in directory sort order, rejecting stray .md files."""
    spec_dir = SPEC_DIR if spec_dir is None else os.path.abspath(spec_dir)
    if not os.path.isdir(spec_dir):
        raise SystemExit("commentable-html spec source directory missing: %s" % _display(spec_dir))
    names = [n for n in os.listdir(spec_dir)
             if os.path.isfile(os.path.join(spec_dir, n)) and n.lower().endswith(".md")]
    stray = [n for n in names if not _PART_RE.match(n)]
    if stray:
        raise SystemExit("%s holds Markdown files that are not `NN-topic.md` partials: %s"
                         % (_display(spec_dir), ", ".join(sorted(stray))))
    if not names:
        raise SystemExit("no spec partials found under %s" % _display(spec_dir))
    return [os.path.join(spec_dir, n) for n in sorted(names)]


def banner(spec_dir=None):
    spec_dir = SPEC_DIR if spec_dir is None else os.path.abspath(spec_dir)
    return ("<!-- %s Built from %s/NN-*.md by %s; run: python %s -->\n"
            % (GENERATED_BANNER_PREFIX, _display(spec_dir), _display(SCRIPT), _display(SCRIPT)))


def assemble_spec(spec_dir=None, out_path=None):
    spec_dir = SPEC_DIR if spec_dir is None else os.path.abspath(spec_dir)
    return banner(spec_dir) + "".join(read(path) for path in ordered_parts(spec_dir))


def main(argv=None):
    argv = sys.argv if argv is None else argv
    parser = argparse.ArgumentParser(prog="build_spec.py",
                                     description="Assemble commentable-html dev/SPEC.md.")
    parser.add_argument("--check", action="store_true",
                        help="verify dev/SPEC.md matches the partials instead of writing it")
    parser.add_argument("--spec-dir", default=SPEC_DIR,
                        help="directory holding numbered spec partials")
    parser.add_argument("--out", default=SPEC_OUT,
                        help="generated SPEC.md path")
    ns = parser.parse_args(argv[1:])

    spec_dir = os.path.abspath(ns.spec_dir)
    out_path = os.path.abspath(ns.out)
    expected = assemble_spec(spec_dir, out_path)
    if ns.check:
        if not os.path.exists(out_path):
            sys.stderr.write("build_spec --check FAILED; run `python %s`:\n" % _display(SCRIPT))
            sys.stderr.write("  - %s (missing)\n" % _display(out_path))
            return 1
        if _lf(read(out_path)) != _lf(expected):
            sys.stderr.write("build_spec --check FAILED; run `python %s`:\n" % _display(SCRIPT))
            sys.stderr.write("  - %s (out of date)\n" % _display(out_path))
            return 1
        print("build_spec --check OK (%d partials in sync)" % len(ordered_parts(spec_dir)))
        return 0
    write(out_path, expected)
    print("build_spec OK (%d partials assembled into %s)" % (len(ordered_parts(spec_dir)), _display(out_path)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
