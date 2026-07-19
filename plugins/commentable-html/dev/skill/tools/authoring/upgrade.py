#!/usr/bin/env python3
"""Upgrade an existing commentable-html file to a newer dist/PORTABLE.html.

Swaps the three layer regions - CSS, COMMENT UI, and JS - in a deployed standalone
(inline) commentable-html file with the versions from a template, while leaving the
document's own state and content untouched: HANDLED IDS, EMBEDDED COMMENTS, the
CONTENT block, and the `#commentRoot` wrapper except for basename-only source provenance.

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
import html as _html
import os
import re
import sys
import tempfile
from html.parser import HTMLParser

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tools/ root
import _toolpath  # noqa: E402
_toolpath.ensure()
import doc_stamp  # noqa: E402
SKILL_ROOT = _toolpath.SKILL_ROOT
DEFAULT_TEMPLATE = os.path.join(SKILL_ROOT, "dist", "PORTABLE.html")

# Regions swapped from the template. HANDLED IDS, EMBEDDED COMMENTS, CONTENT, and the
# #commentRoot wrapper are document-owned; only its source provenance is normalized.
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


class _RootSourceFinder(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self._line_offsets = []
        offset = 0
        for line in html.splitlines(True):
            self._line_offsets.append(offset)
            offset += len(line)
        if not self._line_offsets:
            self._line_offsets.append(0)
        self.root_result = None
        self.body_result = None

    def handle_starttag(self, tag, attrs):
        if self.root_result is not None:
            return
        first_id = next((v for k, v in attrs if k == "id"), None)
        has_source = any(k == "data-doc-source" for k, _v in attrs)
        is_root = first_id == "commentRoot"
        is_body_fallback = tag.lower() == "body" and self.body_result is None
        if not is_root and not is_body_fallback:
            return
        line, column = self.getpos()
        start = self._line_offsets[line - 1] + column
        raw = self.get_starttag_text()
        result = (start, start + len(raw), raw)
        if is_root:
            self.root_result = result
        elif has_source:
            self.body_result = result

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)


def _raw_tag_attributes(tag):
    attrs = []
    pos = 1
    while pos < len(tag) and tag[pos] not in " \t\r\n/>":
        pos += 1
    while pos < len(tag):
        while pos < len(tag) and tag[pos].isspace():
            pos += 1
        if pos >= len(tag) or tag[pos] in ">/":
            break
        name_start = pos
        while pos < len(tag) and tag[pos] not in " \t\r\n=/>":
            pos += 1
        if pos == name_start:
            pos += 1
            continue
        name = tag[name_start:pos].lower()
        while pos < len(tag) and tag[pos].isspace():
            pos += 1
        value_start = value_end = None
        quote = ""
        if pos < len(tag) and tag[pos] == "=":
            pos += 1
            while pos < len(tag) and tag[pos].isspace():
                pos += 1
            if pos < len(tag) and tag[pos] in "\"'":
                quote = tag[pos]
                pos += 1
                value_start = pos
                while pos < len(tag) and tag[pos] != quote:
                    pos += 1
                value_end = pos
                if pos < len(tag):
                    pos += 1
            else:
                value_start = pos
                while pos < len(tag) and not tag[pos].isspace() and tag[pos] != ">":
                    pos += 1
                value_end = pos
        attrs.append((name, value_start, value_end, quote))
    return attrs


def _normalize_source_provenance(html):
    finder = _RootSourceFinder(html)
    finder.feed(html)
    result = finder.root_result or finder.body_result
    if result is None:
        return html, False
    start, end, tag = result
    changed = False
    new_tag = tag
    source_attrs = [
        attr for attr in _raw_tag_attributes(tag)
        if attr[0] == "data-doc-source" and attr[1] is not None
    ]
    for _name, value_start, value_end, quote in reversed(source_attrs):
        source = _html.unescape(tag[value_start:value_end])
        basename = doc_stamp.source_basename(source)
        if basename == source:
            continue
        changed = True
        escaped = _html.escape(basename, quote=True)
        replacement = escaped if quote else '"%s"' % escaped
        new_tag = new_tag[:value_start] + replacement + new_tag[value_end:]
    if not changed:
        return html, False
    return html[:start] + new_tag + html[end:], True


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


# The head version meta. Region swaps leave <head> alone, so an upgraded document keeps
# self-reporting its OLD runtime version unless we restamp this to the template's version
# (the same value the build stamps into a fresh document). Matched order-independently so a
# reordered content/name attribute pair still counts. Scoped to <head> so the marker-like
# text inside the JS export regex literal (content="[^"]+") is never matched or rewritten.
_HEAD_RE = re.compile(r"<head\b[^>]*>.*?</head>", re.IGNORECASE | re.DOTALL)
_VERSION_META_TAG_RE = re.compile(
    r'<meta\b[^>]*\bname="commentable-html-version"[^>]*>', re.IGNORECASE)
_CONTENT_ATTR_RE = re.compile(r'(\bcontent=")([^"]*)(")', re.IGNORECASE)


def _meta_version(html):
    """Return the <head> commentable-html-version meta content, or None when absent."""
    head = _HEAD_RE.search(html or "")
    if not head:
        return None
    m = _VERSION_META_TAG_RE.search(head.group(0))
    if not m:
        return None
    cm = _CONTENT_ATTR_RE.search(m.group(0))
    return cm.group(2).strip() if cm else None


def _set_version_meta(html, version):
    """Restamp (or insert) the <head> commentable-html-version meta to `version`.
    Returns (new_html, changed?). Only <head> is touched: content, state, the #commentRoot
    wrapper, and the JS export regex literal are all left alone."""
    head = _HEAD_RE.search(html)
    if not head:
        return html, False
    hs, he = head.start(), head.end()
    head_text = head.group(0)
    m = _VERSION_META_TAG_RE.search(head_text)
    if m:
        tag = m.group(0)
        cm = _CONTENT_ATTR_RE.search(tag)
        if cm:
            if cm.group(2).strip() == version:
                return html, False
            new_tag = tag[:cm.start()] + cm.group(1) + version + cm.group(3) + tag[cm.end():]
        else:
            new_tag = re.sub(r"\s*/?>$", ' content="%s" />' % version, tag)
        new_head = head_text[:m.start()] + new_tag + head_text[m.end():]
        return html[:hs] + new_head + html[he:], True
    tag = '<meta name="commentable-html-version" content="%s" />\n' % version
    hm = re.match(r"<head\b[^>]*>", head_text, re.IGNORECASE)
    new_head = head_text[:hm.end()] + "\n" + tag + head_text[hm.end():]
    return html[:hs] + new_head + html[he:], True


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
    out, source_normalized = _normalize_source_provenance(out)
    if source_normalized:
        changed.append("source provenance")
    # Restamp the head version meta to the template's runtime version so an upgraded
    # document no longer self-reports the old version (region swaps leave <head> alone).
    # Purely a <head> meta rewrite: content, state, and the remaining #commentRoot attrs are untouched.
    tpl_version = _meta_version(template_html)
    if tpl_version:
        out, bumped = _set_version_meta(out, tpl_version)
        if bumped:
            changed.append("version meta")
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


def _detect_newline(path):
    """Return the input's dominant newline ('\\r\\n' or '\\n') from its raw bytes, so a
    Windows-authored (CRLF) document keeps its line endings through the upgrade instead of
    being silently normalized to LF by the universal-newline reader."""
    with open(path, "rb") as fh:
        raw = fh.read()
    crlf = raw.count(b"\r\n")
    lf = raw.count(b"\n") - crlf
    return "\r\n" if crlf > lf else "\n"


def main(argv):
    p = argparse.ArgumentParser(description="Upgrade a commentable-html file's layer regions from a template.")
    p.add_argument("file", help="the deployed commentable-html file to upgrade")
    p.add_argument("--template", default=DEFAULT_TEMPLATE, help="template to upgrade from (default: skill dist/PORTABLE.html)")
    p.add_argument("--out", default=None, help="write result here instead of in place")
    p.add_argument("--check", action="store_true", help="do not write; exit 1 if any region is stale")
    p.add_argument("--strict", action="store_true",
                   help="treat post-upgrade validator warnings as failures: leave the target unchanged "
                        "and exit non-zero (errors already do this). Off by default so a version-only "
                        "upgrade is never blocked by a pre-existing content warning.")
    args = p.parse_args(argv[1:])

    try:
        target = _read(args.file)
        template = _read(args.template)
        newline = _detect_newline(args.file)
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
    warnings = []
    fd, tmp_path = tempfile.mkstemp(prefix=".cmh-upgrade-", suffix=".html", dir=out_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline=newline) as fh:
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
                errors, warnings = validate.validate(tmp_path)
            except Exception as exc:  # noqa: BLE001
                sys.stderr.write("upgrade aborted: validator crashed on the new %s: %s\n" % (out_path, exc))
                return 1
            if errors:
                sys.stderr.write("upgrade aborted: the new %s would FAIL validation (target left unchanged):\n  %s\n"
                                 % (out_path, "\n  ".join(errors)))
                return 1
            if warnings and args.strict:
                sys.stderr.write("upgrade aborted (--strict): the new %s has validator warning(s) "
                                 "(target left unchanged):\n  %s\n" % (out_path, "\n  ".join(warnings)))
                return 1

        os.replace(tmp_path, out_path)
        tmp_path = None
    finally:
        if tmp_path is not None and os.path.exists(tmp_path):
            os.remove(tmp_path)

    print("Upgraded %s (regions: %s)%s" % (out_path, ", ".join(changed),
          "" if out_path == args.file else " from " + args.file))
    # Surface (non-blocking) any validator warnings the upgrade did not abort on, so the
    # agent can resolve them with a finalize/validate pass instead of shipping them unseen.
    if warnings:
        print("%d validator warning(s) remain (run finalize.py --strict to resolve):" % len(warnings))
        for item in warnings:
            print("  WARNING: %s" % item)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
