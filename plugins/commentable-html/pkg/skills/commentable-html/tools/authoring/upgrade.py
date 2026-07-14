#!/usr/bin/env python3
"""Upgrade an existing commentable-html file to a newer dist/PORTABLE.html.

Swaps the three layer regions - CSS, COMMENT UI, and JS - in a deployed standalone
(inline) commentable-html file with the versions from a template, while leaving the
document's own state and content untouched: HANDLED IDS, EMBEDDED COMMENTS, the
CONTENT block, and the `#commentRoot` wrapper are never modified.

This is the "Upgrade an existing instance to a new dist/PORTABLE.html" recipe from SKILL.md,
made deterministic. Doing it by hand is error prone because of two documented footguns:
the JS payload's own plain-HTML-export code contains marker-like text, so the real JS
region END is the LAST `END: commentable-html - JS` occurrence, and a naive first
match truncates the region.

Stdlib-only, local-only, deterministic. Usage:

    python tools/upgrade.py <file.html>                 # upgrade in place from dist/PORTABLE.html
    python tools/upgrade.py <file.html> --template T     # use a specific template
    python tools/upgrade.py <file.html> --out out.html   # write elsewhere
    python tools/upgrade.py <file.html> --check          # exit 1 if regions are stale, no write
"""
import argparse
import os
import re
import sys
import tempfile
from html.parser import HTMLParser

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tools/ root
import _toolpath  # noqa: E402
_toolpath.ensure()
SKILL_ROOT = _toolpath.SKILL_ROOT
DEFAULT_TEMPLATE = os.path.join(SKILL_ROOT, "dist", "PORTABLE.html")

# Regions swapped from the template. HANDLED IDS, EMBEDDED COMMENTS, CONTENT, and the
# #commentRoot wrapper are the document's own state and are deliberately left alone.
SWAP_REGIONS = ["CSS", "COMMENT UI", "JS"]
LAYER_REGIONS = ["CSS", "HANDLED IDS", "EMBEDDED COMMENTS", "COMMENT UI", "JS"]
# State/content markers a valid target must contain (so we never "upgrade" a file that
# is not actually a commentable-html document).
REQUIRED_MARKERS = ["HANDLED IDS", "EMBEDDED COMMENTS", "COMMENT UI", "CONTENT", "CSS", "JS"]
CONTENT_BEGIN_RE = re.compile(r"<!--\s*BEGIN: commentable-html - CONTENT\b", re.IGNORECASE)
# A real nonportable document carries this exact bootstrap comment. The inline JS body only
# mentions the marker text inside a regex literal (with `\s*`, not literal spaces), so
# matching the full comment avoids a false positive on standalone files.
NONPORTABLE_MARKER = "<!-- BEGIN: commentable-html - NONPORTABLE BOOTSTRAP -->"

# Older documents predate the mandatory document-kind meta. On upgrade we add a default
# (generic) kind so the result declares one and passes validation; the author can change
# it to report/plan/slides/board afterwards. Detection is order-independent (a reordered
# <meta content=... name=...> still counts), so an existing kind is never duplicated.
_KIND_META_NAME = "commentable-html-kind"


class _KindMetaFinder(HTMLParser):
    """Detect a <meta name="commentable-html-kind"> regardless of attribute order."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.found = False

    def _check(self, tag, attrs):
        if tag.lower() != "meta":
            return
        for k, v in attrs:
            if (k or "").lower() == "name" and (v or "").strip().lower() == _KIND_META_NAME:
                self.found = True

    def handle_starttag(self, tag, attrs):
        self._check(tag, attrs)

    def handle_startendtag(self, tag, attrs):
        self._check(tag, attrs)


def _has_kind_meta(html):
    p = _KindMetaFinder()
    try:
        p.feed(html)
        p.close()
    except Exception:
        pass
    return p.found


def _insert_kind_meta(html, kind):
    """Insert a <meta name="commentable-html-kind"> into <head>, preferring the spot right
    after the version meta. Returns (new_html, inserted?)."""
    tag = '<meta name="commentable-html-kind" content="%s" />\n' % kind
    m = re.search(r'<meta\s+name="commentable-html-version"[^>]*>[ \t]*\n?', html, re.IGNORECASE)
    if m:
        return html[:m.end()] + tag + html[m.end():], True
    m = re.search(r"<head[^>]*>", html, re.IGNORECASE)
    if m:
        return html[:m.end()] + "\n" + tag + html[m.end():], True
    return html, False


class _MarkerMatch:
    def __init__(self, marker_start, marker_end):
        self._marker_start = marker_start
        self._marker_end = marker_end

    def start(self, group=0):
        return self._marker_start

    def end(self, group=0):
        return self._marker_end


def _advance_comment_state(line, state):
    i = 0
    while i < len(line):
        if state == "html":
            close = line.find("-->", i)
            if close < 0:
                return "html"
            state = ""
            i = close + 3
            continue
        if state == "css":
            close = line.find("*/", i)
            if close < 0:
                return "css"
            state = ""
            i = close + 2
            continue
        html_open = line.find("<!--", i)
        css_open = line.find("/*", i)
        if html_open >= 0 and (css_open < 0 or html_open < css_open):
            state = "html"
            i = html_open + 4
            continue
        if css_open >= 0:
            state = "css"
            i = css_open + 2
            continue
        return ""
    return state


def _region_marker_matches(text, kind, name):
    marker = "%s: commentable-html - %s" % (kind, name)
    marker_re = re.escape(marker)
    bare = re.compile(r"^[ \t]*(?:=+[ \t]*)?(%s)[ \t]*(?:=+[ \t]*)?$" % marker_re)
    inline = re.compile(r"^[ \t]*(?:<!--[ \t]*|/\*[ \t]*)(?:=+[ \t]*)?(%s)[ \t]*(?:=+[ \t]*)?(?:-->|\*/)[ \t]*$" % marker_re)
    matches = []
    state = ""
    offset = 0
    for line in (text or "").splitlines(True):
        body = line[:-1] if line.endswith("\n") else line
        if body.endswith("\r"):
            body = body[:-1]
        m = inline.match(body)
        if m is None and state in ("html", "css"):
            m = bare.match(body)
        if m is not None:
            matches.append(_MarkerMatch(offset + m.start(1), offset + m.end(1)))
        state = _advance_comment_state(body, state)
        offset += len(line)
    return matches


def _region_inner(text, name, where):
    """Return (start, end) byte offsets of a region's inner content (between the BEGIN
    and END marker texts). The line-anchored match ignores marker-like strings."""
    begins = _region_marker_matches(text, "BEGIN", name)
    if not begins:
        raise ValueError("%s: '%s' region BEGIN marker not found" % (where, name))
    if len(begins) > 1:
        raise ValueError("%s: duplicate region: %s" % (where, name))
    bm = begins[0]
    b = bm.end(1)
    ends = [m for m in _region_marker_matches(text, "END", name) if m.start(1) >= b]
    if not ends:
        raise ValueError("%s: '%s' region END marker not found after BEGIN" % (where, name))
    if len(ends) > 1:
        raise ValueError("%s: duplicate region: %s" % (where, name))
    em = ends[0]
    return b, em.start(1)


def upgrade(target_html, template_html, target_name="<target>", template_name="<template>"):
    """Return (new_html, changed_region_names). Raises ValueError on an unusable input."""
    if NONPORTABLE_MARKER in target_html:
        raise ValueError(
            "%s looks like a nonportable document (companion assets). Upgrade nonportable files by "
            "replacing the dist/ companions from the new release; the version meta is stamped by the build." % target_name)
    for marker in REQUIRED_MARKERS:
        found = bool(CONTENT_BEGIN_RE.search(target_html)) if marker == "CONTENT" \
            else bool(_region_marker_matches(target_html, "BEGIN", marker))
        if not found:
            raise ValueError("%s is not a commentable-html document (missing '%s' region)" % (target_name, marker))
    for name in LAYER_REGIONS:
        _region_inner(template_html, name, template_name)
        _region_inner(target_html, name, target_name)
    out = target_html
    changed = []
    for name in SWAP_REGIONS:
        tb, te = _region_inner(template_html, name, template_name)
        db, de = _region_inner(out, name, target_name)
        new_inner = template_html[tb:te]
        if out[db:de] != new_inner:
            out = out[:db] + new_inner + out[de:]
            changed.append(name)
    # Migrate a pre-kind document: add the mandatory document-kind meta if it is missing.
    # Detection is order-independent so a reordered existing meta is never duplicated.
    if not _has_kind_meta(out):
        out, added = _insert_kind_meta(out, "generic")
        if added:
            changed.append("kind meta")
    return out, changed


def _read(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def main(argv):
    p = argparse.ArgumentParser(description="Upgrade a commentable-html file's layer regions from a template.")
    p.add_argument("file", help="the deployed commentable-html file to upgrade")
    p.add_argument("--template", default=DEFAULT_TEMPLATE, help="template to upgrade from (default: skill dist/PORTABLE.html)")
    p.add_argument("--out", default=None, help="write result here instead of in place")
    p.add_argument("--check", action="store_true", help="do not write; exit 1 if any region is stale")
    args = p.parse_args(argv[1:])

    try:
        target = _read(args.file)
        template = _read(args.template)
    except OSError as exc:
        sys.stderr.write("cannot read file: %s\n" % exc)
        return 2
    try:
        new_html, changed = upgrade(target, template, args.file, args.template)
    except ValueError as exc:
        sys.stderr.write("upgrade failed: %s\n" % exc)
        return 2

    if args.check:
        if changed:
            print("%s is STALE: regions differ from template: %s" % (args.file, ", ".join(changed)))
            return 1
        print("%s regions are up to date." % args.file)
        return 0

    if not changed:
        print("%s already up to date; nothing to do." % args.file)
        return 0

    out_path = args.out or args.file

    # Validate BEFORE committing: write to a temp file in the destination directory,
    # validate that, and only atomically replace the target on success. This guarantees
    # a failed validation never clobbers the source/target with a broken document.
    out_dir = os.path.dirname(os.path.abspath(out_path)) or "."
    fd, tmp_path = tempfile.mkstemp(prefix=".cmh-upgrade-", suffix=".html", dir=out_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(new_html)

        # Self-check the result with the validator when it is importable, so the
        # automated path never silently emits a broken file. An ImportError just means
        # the validator is unavailable (skip); any OTHER exception is a real validator
        # failure and must surface instead of being swallowed.
        try:
            _toolpath.ensure()
            import validate  # noqa: E402
        except ImportError:
            validate = None
        if validate is not None:
            try:
                errors, _warnings = validate.validate(tmp_path)
            except Exception as exc:  # noqa: BLE001
                sys.stderr.write("upgrade aborted: validator crashed on the new %s: %s\n" % (out_path, exc))
                return 1
            if errors:
                sys.stderr.write("upgrade aborted: the new %s would FAIL validation (target left unchanged):\n  %s\n"
                                 % (out_path, "\n  ".join(errors)))
                return 1

        os.replace(tmp_path, out_path)
        tmp_path = None
    finally:
        if tmp_path is not None and os.path.exists(tmp_path):
            os.remove(tmp_path)

    print("Upgraded %s (regions: %s)%s" % (out_path, ", ".join(changed),
          "" if out_path == args.file else " from " + args.file))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
