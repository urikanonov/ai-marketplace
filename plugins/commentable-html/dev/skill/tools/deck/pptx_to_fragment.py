#!/usr/bin/env python3
"""Turn extracted PowerPoint content into an escaped commentable-html deck fragment.

This is the ONLY path by which PowerPoint-derived text enters a deck. It escapes every
extracted string as HTML text (the deck never inserts extracted text via innerHTML) and
emits one ``<section class="slide" data-slide-id=...>`` per slide, matching the deck
contract (references/deck-contract.md). Speaker notes are NOT supported and are ignored.

Input is the extracted-content JSON produced either by the Anthropic ``pptx`` skill (when
the agent has it) or by the vendored local extractor. The JSON is a list of slide objects:
``{"title": str, "content": [{"type": "text", "content": str}, ...], "images": [{"path": str}, ...]}``.
Each image ``path`` must be LOCAL and RELATIVE (no URL scheme, no ``//host``, no leading ``/``,
no ``..``) or a self-contained ``data:image/...;base64,...`` URI; a remote or traversing path
fails closed. Every slide must have at least a title, one text block, or one image.

Usage (run from the skill root):
    python deck/pptx_to_fragment.py --input extracted-slides.json --out fragment.html
    some-extractor | python deck/pptx_to_fragment.py --input - > fragment.html
    python deck/pptx_to_fragment.py --pptx deck.pptx --out fragment.html   # local fallback

The ``--pptx`` fallback shells out to the vendored ``extract-pptx.py`` and FAILS CLOSED if
``python-pptx`` is not installed (it never auto-installs anything). Its extracted images are
inlined as ``data:`` URIs so the fragment stays self-contained (the extractor's temp dir is
deleted right after extraction).
"""
import argparse
import base64
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tools/ root
import _toolpath  # noqa: E402
_toolpath.ensure()
from deck_common import esc, slide_id  # noqa: E402

HERE = Path(__file__).resolve().parent
VENDOR_EXTRACTOR = Path(_toolpath.SKILL_ROOT) / "vendor" / "frontend-slides" / "scripts" / "extract-pptx.py"

_IMG_MIME = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
    ".svg": "image/svg+xml", ".webp": "image/webp", ".bmp": "image/bmp",
}

_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.\-]*:", re.I)
# A self-contained inline image (base64). The deck validator allows data:image (it is local,
# non-egress) but rejects data:text/html and every other scheme.
_DATA_IMAGE_RE = re.compile(r"^data:image/[a-z0-9.+-]+;base64,", re.I)

MAX_PPTX_TOTAL_BYTES = 1024 * 1024 * 1024
MAX_PPTX_ENTRY_BYTES = 250 * 1024 * 1024
MAX_PPTX_ENTRIES = 100_000
MAX_PPTX_COMPRESSION_RATIO = 250


def _preflight_pptx_archive(pptx_path):
    with zipfile.ZipFile(pptx_path) as archive:
        entries = archive.infolist()
    if len(entries) > MAX_PPTX_ENTRIES:
        raise ValueError(
            f"archive has {len(entries)} entries; limit is {MAX_PPTX_ENTRIES}"
        )

    total_size = 0
    total_compressed = 0
    for entry in entries:
        if entry.file_size > MAX_PPTX_ENTRY_BYTES:
            raise ValueError(
                f"entry {entry.filename!r} expands to {entry.file_size} bytes; "
                f"per-entry limit is {MAX_PPTX_ENTRY_BYTES}"
            )
        total_size += entry.file_size
        total_compressed += entry.compress_size

    if total_size > MAX_PPTX_TOTAL_BYTES:
        raise ValueError(
            f"archive expands to {total_size} bytes; total limit is {MAX_PPTX_TOTAL_BYTES}"
        )
    if total_size and (
        total_compressed == 0
        or total_size / total_compressed > MAX_PPTX_COMPRESSION_RATIO
    ):
        raise ValueError(
            f"archive compression ratio exceeds {MAX_PPTX_COMPRESSION_RATIO}:1"
        )


def _safe_image_path(path, index):
    """Return a vetted image reference, or raise ValueError.

    A local, relative, traversal-free path is allowed, as is a self-contained
    ``data:image/...;base64,...`` URI (the local `--pptx` extractor inlines its images this way so
    the fragment is self-contained). Any other scheme (http:, data:text/html, ...), a
    protocol-relative (//host), an absolute, or a parent-directory (..) reference is rejected, so a
    PPTX-derived deck stays free of egress and path traversal at the source.
    """
    p = (path or "").strip()
    if not p:
        return None
    if _DATA_IMAGE_RE.match(p):
        return p
    norm = p.replace("\\", "/")
    if _SCHEME_RE.match(p) or norm.startswith("//"):
        raise ValueError(f"slide {index}: remote/scheme image path not allowed: {path!r}")
    if norm.startswith("/"):
        raise ValueError(f"slide {index}: absolute image path not allowed: {path!r}")
    if ".." in norm.split("/"):
        raise ValueError(f"slide {index}: parent-directory (..) image path not allowed: {path!r}")
    return norm


def _validate_slides(slides):
    if not isinstance(slides, list):
        raise ValueError("expected a JSON list of slides")
    if not slides:
        raise ValueError("no slides in the extracted content")
    for i, slide in enumerate(slides):
        if not isinstance(slide, dict):
            raise ValueError(f"slide {i} is not a JSON object")
        content = slide.get("content")
        if content is not None and not isinstance(content, list):
            raise ValueError(f"slide {i}: 'content' must be a list")
        images = slide.get("images")
        if images is not None and not isinstance(images, list):
            raise ValueError(f"slide {i}: 'images' must be a list")


def slides_to_fragment(slides) -> str:
    _validate_slides(slides)
    taken = set()
    out = []
    for i, slide in enumerate(slides):
        title = (slide.get("title") or "").strip()
        texts = []
        for block in slide.get("content") or []:
            if not isinstance(block, dict):
                raise ValueError(f"slide {i}: content block is not a JSON object")
            if block.get("type", "text") != "text":
                continue
            text = (block.get("content") or "").strip()
            if text:
                texts.append(text)
        images = []
        for img in slide.get("images") or []:
            if not isinstance(img, dict):
                raise ValueError(f"slide {i}: image entry is not a JSON object")
            vetted = _safe_image_path(img.get("path"), i)
            if vetted:
                images.append(vetted)
        if not (title or texts or images):
            raise ValueError(f"slide {i} has no title, text, or image content")
        sid = slide_id(title + "\n" + "\n".join(texts), taken)
        parts = [f'<section class="slide" data-slide-id="{sid}">']
        if title:
            parts.append(f'  <h2 class="cmh-slide-title">{esc(title)}</h2>')
        for text in texts:
            parts.append(f"  <p>{esc(text)}</p>")
        for path in images:
            parts.append(f'  <img src="{esc(path)}" alt="">')
        parts.append("</section>")
        out.append("\n".join(parts))
    return "\n".join(out) + "\n"


def _inline_local_images(slides, base_dir):
    """Rewrite each slide image whose ``path`` is a local file under ``base_dir`` to a
    self-contained ``data:image/...;base64,...`` URI. The local ``--pptx`` extractor writes images
    into a temp dir that is deleted right after extraction; inlining here (before teardown) keeps
    the extracted images in the fragment instead of leaving dangling ``assets/...`` references.
    """
    if not isinstance(slides, list):
        return slides
    base = Path(base_dir)
    for slide in slides:
        if not isinstance(slide, dict):
            continue
        for img in slide.get("images") or []:
            if not isinstance(img, dict):
                continue
            path = (img.get("path") or "").strip()
            norm = path.replace("\\", "/")
            if not path or _SCHEME_RE.match(path) or norm.startswith(("//", "/")) or ".." in norm.split("/"):
                continue  # leave odd/absolute/traversing paths for _safe_image_path to handle
            f = base / norm
            if not f.is_file():
                continue
            mime = _IMG_MIME.get(f.suffix.lower(), "application/octet-stream")
            img["path"] = "data:%s;base64,%s" % (mime, base64.b64encode(f.read_bytes()).decode("ascii"))
    return slides


def _extract_via_local(pptx_path: str):
    if not VENDOR_EXTRACTOR.exists():
        print(f"pptx_to_fragment: vendored extractor missing: {VENDOR_EXTRACTOR}", file=sys.stderr)
        raise SystemExit(1)
    try:
        _preflight_pptx_archive(pptx_path)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"pptx_to_fragment: PPTX archive rejected: {exc}", file=sys.stderr)
        raise SystemExit(1)
    with tempfile.TemporaryDirectory() as tmp:
        proc = subprocess.run(
            [sys.executable, str(VENDOR_EXTRACTOR), pptx_path, tmp],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            msg = (proc.stderr or proc.stdout or "").strip()
            hint = ""
            if "pptx" in msg.lower() or "No module named" in msg:
                hint = " (install python-pptx to use the local fallback)"
            print(f"pptx_to_fragment: local extraction failed{hint}:\n{msg}", file=sys.stderr)
            raise SystemExit(1)
        data = Path(tmp, "extracted-slides.json")
        if not data.exists():
            print("pptx_to_fragment: local extractor produced no extracted-slides.json", file=sys.stderr)
            raise SystemExit(1)
        # Inline the extracted images WHILE the temp dir still exists, so they survive its teardown.
        return _inline_local_images(json.loads(data.read_text(encoding="utf-8")), tmp)


def _load_input(arg: str):
    raw = sys.stdin.read() if arg == "-" else Path(arg).read_text(encoding="utf-8")
    return json.loads(raw)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Escaped commentable-html deck fragment from extracted PPTX content.")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--input", help="extracted-content JSON file, or - for stdin")
    src.add_argument("--pptx", help="a .pptx file (uses the vendored local extractor; fails closed)")
    ap.add_argument("--out", help="write the fragment here (default: stdout)")
    args = ap.parse_args(argv)

    if args.pptx:
        slides = _extract_via_local(args.pptx)
    else:
        slides = _load_input(args.input)

    try:
        fragment = slides_to_fragment(slides)
    except ValueError as exc:
        print(f"pptx_to_fragment: {exc}", file=sys.stderr)
        return 1
    if args.out:
        Path(args.out).write_text(fragment, encoding="utf-8")
    else:
        sys.stdout.buffer.write(fragment.encode("utf-8"))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
