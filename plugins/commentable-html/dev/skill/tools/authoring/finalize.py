#!/usr/bin/env python3
"""Run deterministic commentable-html finalize steps in a fixed order.

Usage (run from the skill root):
    python tools/finalize.py file.html
    python tools/finalize.py file.html --toc --fix-skip --inline-images
    python tools/finalize.py file.html --inline-images --images-base examples
    python tools/finalize.py file.html --strict

Order is always:
  1) normalize_typography (on by default; skip with --no-normalize)
  2) generate_toc (when --toc)
  3) wrap_sections (report/plan only; on by default, skip with --no-wrap-sections)
  4) fix_skip (when --fix-skip)
  5) inline_images (when --inline-images)
  6) highlight_document (on by default; skip with --no-highlight)
  7) validate
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tools/ root
import _toolpath  # noqa: E402
_toolpath.ensure()

import fix_skip  # noqa: E402
import generate_toc  # noqa: E402
import doc_stats  # noqa: E402
import highlight_document  # noqa: E402
import inline_images  # noqa: E402
import normalize_typography  # noqa: E402
import validate  # noqa: E402
import wrap_sections  # noqa: E402

# Kinds that render as boxed section cards; only these get auto section-wrapping.
_SECTION_CARD_KINDS = frozenset({"report", "plan"})
_KIND_META_RE = re.compile(
    r'<meta\s+name="commentable-html-kind"\s+content="([^"]*)"', re.IGNORECASE)


def _read(path):
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def _write(path, html):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(html)


def _run_normalize(path):
    source = _read(path)
    rewritten, count = normalize_typography.normalize_typography(source)
    changed = rewritten != source
    if changed:
        _write(path, rewritten)
    return changed, count


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


def _run_wrap_sections(path):
    source = _read(path)
    m = _KIND_META_RE.search(source)
    kind = (m.group(1) if m else "").strip().lower()
    if kind not in _SECTION_CARD_KINDS:
        return False, 0
    rewritten, count = wrap_sections.fix(source)
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


def _run_toc_dedup(path):
    source = _read(path)
    rewritten, count = generate_toc.strip_toc_numbers(source)
    changed = rewritten != source
    if changed:
        _write(path, rewritten)
    return changed, count


def _run_stats(path):
    source = _read(path)
    m = _KIND_META_RE.search(source)
    kind = (m.group(1) if m else "").strip().lower()
    if kind not in _SECTION_CARD_KINDS:
        return False, False
    rewritten = doc_stats.rewrite_html(source)
    changed = rewritten != source
    if changed:
        _write(path, rewritten)
    return True, changed


def finalize(path, run_toc=False, run_fix_skip=False, run_inline=False, images_base=None,
             run_highlight=True, run_wrap_sections=True, run_stats=True, run_normalize=True):
    steps = []
    if run_normalize:
        changed, count = _run_normalize(path)
        status = "normalized %d AI char(s)" % count if changed else "unchanged"
        steps.append(("normalize", status))
    if run_toc:
        changed = _run_toc(path)
        steps.append(("toc", "updated" if changed else "unchanged"))
    if run_wrap_sections:
        changed, count = _run_wrap_sections(path)
        status = "wrapped %d section(s)" % count if changed else "unchanged"
        steps.append(("wrap-sections", status))
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
    # Always de-duplicate an author-numbered ordered-list .cm-toc so it is never double-numbered.
    changed, count = _run_toc_dedup(path)
    if changed:
        steps.append(("toc-numbers", "stripped %d entry(ies)" % count))
    # Bake the section/word/reading-time overview strip for report/plan documents.
    if run_stats:
        applicable, changed = _run_stats(path)
        if applicable:
            steps.append(("doc-stats", "updated" if changed else "unchanged"))
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
    parser.add_argument("--no-wrap-sections", action="store_true",
                        help="skip wrapping bare top-level <h2> blocks in <section> for report/plan "
                             "documents (on by default)")
    parser.add_argument("--no-stats", action="store_true",
                        help="skip baking the section/word/reading-time overview strip for "
                             "report/plan documents (on by default)")
    parser.add_argument("--no-normalize", action="store_true",
                        help="skip rewriting AI smart-typography (em/en dashes, ellipsis, curly "
                             "quotes, nbsp) to plain ASCII in prose (on by default)")
    parser.add_argument("--strict", action="store_true",
                        help="treat validator warnings as failures (errors already fail)")
    parser.add_argument("--no-stamp", action="store_true",
                        help="do not write the commentable-html-validated stamp on a strict-clean pass")
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
            run_wrap_sections=not args.no_wrap_sections,
            run_stats=not args.no_stats,
            run_normalize=not args.no_normalize,
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
    # Strict-clean: stamp the document as validated so the runtime fallback banner clears. --no-stamp
    # keeps a read-only run from writing.
    if not args.no_stamp and not errors and not warnings:
        validate._stamp_validated_file(args.file)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
