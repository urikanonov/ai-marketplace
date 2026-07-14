#!/usr/bin/env python3
"""Run deterministic commentable-html finalize steps in a fixed order.

Usage (run from the skill root):
    python tools/finalize.py file.html
    python tools/finalize.py file.html --toc --fix-skip --inline-images
    python tools/finalize.py file.html --inline-images --images-base examples
    python tools/finalize.py file.html --strict

Order is always:
  1) generate_toc (when --toc)
  2) fix_skip (when --fix-skip)
  3) inline_images (when --inline-images)
  4) highlight_document (on by default; skip with --no-highlight)
  5) validate
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import fix_skip  # noqa: E402
import generate_toc  # noqa: E402
import highlight_document  # noqa: E402
import inline_images  # noqa: E402
import validate  # noqa: E402


def _read(path):
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def _write(path, html):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(html)


def _run_toc(path):
    source = _read(path)
    rewritten = generate_toc.rewrite_html(source)
    changed = rewritten != source
    if changed:
        _write(path, rewritten)
    return changed


def _run_fix_skip(path):
    source = _read(path)
    rewritten, count = fix_skip.fix(source)
    changed = rewritten != source
    if changed:
        _write(path, rewritten)
    return changed, count


def _run_inline_images(path, base_dir):
    source = _read(path)
    rewritten, inlined, missing = inline_images.inline_images(source, base_dir)
    changed = rewritten != source
    if changed:
        _write(path, rewritten)
    return changed, inlined, missing


def _run_highlight(path):
    source = _read(path)
    rewritten, count = highlight_document.highlight_document(source)
    changed = rewritten != source
    if changed:
        _write(path, rewritten)
    return changed, count


def finalize(path, run_toc=False, run_fix_skip=False, run_inline=False, images_base=None,
             run_highlight=True):
    steps = []
    if run_toc:
        changed = _run_toc(path)
        steps.append(("toc", "updated" if changed else "unchanged"))
    if run_fix_skip:
        changed, count = _run_fix_skip(path)
        status = "fixed %d block(s)" % count if changed else "unchanged"
        steps.append(("fix-skip", status))
    if run_inline:
        base = images_base or os.path.dirname(os.path.abspath(path))
        changed, inlined, missing = _run_inline_images(path, base)
        status = "inlined %d image(s), %d missing" % (inlined, len(missing))
        if not changed and not inlined and not missing:
            status = "unchanged"
        steps.append(("inline-images", status))
    if run_highlight:
        changed, count = _run_highlight(path)
        status = "highlighted %d block(s)" % count if changed else "unchanged"
        steps.append(("highlight", status))
    errors, warnings = validate.validate(path)
    return {"steps": steps, "errors": errors, "warnings": warnings}


def main(argv):
    parser = argparse.ArgumentParser(
        prog="finalize.py",
        description="Run optional assembly steps in a fixed order, then validate.")
    parser.add_argument("file", help="HTML file to finalize")
    parser.add_argument("--toc", action="store_true", help="run generate_toc in place first")
    parser.add_argument("--fix-skip", action="store_true",
                        help='run fix_skip in place to add cm-skip to bare <pre class="mermaid"> blocks')
    parser.add_argument("--inline-images", action="store_true", help="run inline_images in place")
    parser.add_argument("--images-base", default=None, help="base directory used by --inline-images")
    parser.add_argument("--no-highlight", action="store_true",
                        help="skip baking syntax highlighting into raw language-labelled code blocks "
                             "(on by default)")
    parser.add_argument("--strict", action="store_true",
                        help="treat validator warnings as failures (errors already fail)")
    args = parser.parse_args(argv[1:])

    if not os.path.exists(args.file):
        sys.stderr.write("finalize: file not found: %s\n" % args.file)
        return 1

    try:
        result = finalize(
            args.file,
            run_toc=args.toc,
            run_fix_skip=args.fix_skip,
            run_inline=args.inline_images,
            images_base=args.images_base,
            run_highlight=not args.no_highlight,
        )
    except (OSError, ValueError) as exc:
        sys.stderr.write("finalize: %s\n" % exc)
        return 1

    ran = [name for name, _status in result["steps"]]
    print("finalize: ran %s" % (", ".join(ran) if ran else "validation only"))
    for name, status in result["steps"]:
        print("  %s: %s" % (name, status))

    errors = result["errors"]
    warnings = result["warnings"]
    print("finalize: validate -> %d error(s), %d warning(s)" % (len(errors), len(warnings)))
    for item in warnings:
        print("  WARNING: %s" % item)
    for item in errors:
        print("  ERROR:   %s" % item)

    if errors:
        return 1
    if args.strict and warnings:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
