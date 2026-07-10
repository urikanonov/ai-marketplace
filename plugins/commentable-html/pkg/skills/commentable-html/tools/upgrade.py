#!/usr/bin/env python3
"""Upgrade an existing commentable-html file to a newer dist/PORTABLE.html.

Swaps the three layer regions - CSS, COMMENT UI, and JS - in a deployed standalone
(inline) commentable-html file with the versions from a template, while leaving the
document's own state and content untouched: HANDLED IDS, EMBEDDED COMMENTS, the
CONTENT block, and the `#commentRoot` wrapper are never modified.

This is the "Upgrade an existing instance to a new dist/PORTABLE.html" recipe from SKILL.md,
made deterministic. Doing it by hand is error prone because of two documented footguns:
the JS payload's own plain-HTML-export code contains marker-like text, so the real JS
region END is the LAST `END: commentable-html v2 - JS` occurrence, and a naive first
match truncates the region.

Stdlib-only, local-only, deterministic. Usage:

    python tools/upgrade.py <file.html>                 # upgrade in place from dist/PORTABLE.html
    python tools/upgrade.py <file.html> --template T     # use a specific template
    python tools/upgrade.py <file.html> --out out.html   # write elsewhere
    python tools/upgrade.py <file.html> --check          # exit 1 if regions are stale, no write
"""
import argparse
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(HERE)
DEFAULT_TEMPLATE = os.path.join(SKILL_ROOT, "dist", "PORTABLE.html")

# Regions swapped from the template. HANDLED IDS, EMBEDDED COMMENTS, CONTENT, and the
# #commentRoot wrapper are the document's own state and are deliberately left alone.
SWAP_REGIONS = ["CSS", "COMMENT UI", "JS"]
# State/content markers a valid target must contain (so we never "upgrade" a file that
# is not actually a commentable-html document).
REQUIRED_MARKERS = ["HANDLED IDS", "EMBEDDED COMMENTS", "COMMENT UI", "CONTENT", "CSS", "JS"]
# A real nonportable document carries this exact bootstrap comment. The inline JS body only
# mentions the marker text inside a regex literal (with `\s*`, not literal spaces), so
# matching the full comment avoids a false positive on standalone files.
NONPORTABLE_MARKER = "<!-- BEGIN: commentable-html v2 - NONPORTABLE BOOTSTRAP -->"


def _region_inner(text, name, where):
    """Return (start, end) byte offsets of a region's inner content (between the BEGIN
    and END marker texts). For JS the END is the LAST occurrence, because the JS body
    contains marker-like strings that would fool a first match."""
    begin = "BEGIN: commentable-html v2 - " + name
    end = "END: commentable-html v2 - " + name
    bi = text.find(begin)
    if bi < 0:
        raise ValueError("%s: '%s' region BEGIN marker not found" % (where, name))
    b = bi + len(begin)
    ei = text.rfind(end) if name == "JS" else text.find(end, b)
    if ei < 0 or ei < b:
        raise ValueError("%s: '%s' region END marker not found after BEGIN" % (where, name))
    return b, ei


def upgrade(target_html, template_html, target_name="<target>", template_name="<template>"):
    """Return (new_html, changed_region_names). Raises ValueError on an unusable input."""
    if NONPORTABLE_MARKER in target_html:
        raise ValueError(
            "%s looks like an nonportable document (companion assets). Upgrade nonportable files by "
            "replacing the dist/ companions and bumping the assets version meta instead." % target_name)
    for marker in REQUIRED_MARKERS:
        if ("BEGIN: commentable-html v2 - " + marker) not in target_html:
            raise ValueError("%s is not a commentable-html document (missing '%s' region)" % (target_name, marker))
    out = target_html
    changed = []
    for name in SWAP_REGIONS:
        tb, te = _region_inner(template_html, name, template_name)
        db, de = _region_inner(out, name, target_name)
        new_inner = template_html[tb:te]
        if out[db:de] != new_inner:
            out = out[:db] + new_inner + out[de:]
            changed.append(name)
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
            sys.path.insert(0, HERE)
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
