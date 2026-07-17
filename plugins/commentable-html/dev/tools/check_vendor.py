#!/usr/bin/env python3
"""Verify the vendored frontend-slides trees stay pristine, curated subsets.

The shipped copy under ``pkg/skills/commentable-html/vendor/frontend-slides/`` and the agent-only
``bold-template-pack`` under ``dev/vendor/frontend-slides/`` must remain pristine subsets of their
recorded upstreams. This gate fails on any unknown, changed, or removed file versus each tree's
``MANIFEST.sha256``, and on any denylisted file (``deploy.sh``, ``export-pdf.sh``, an upstream plugin
manifest) being reintroduced by a resync. It is the enforceable stand-in for "re-review on every
resync": run ``--update`` only after an intentional, security-reviewed resync.

Usage (run from anywhere):
    python dev/tools/check_vendor.py            # verify (CI / pre-push); exits non-zero on drift
    python dev/tools/check_vendor.py --update   # regenerate MANIFEST.sha256 from the current tree
"""
import argparse
import hashlib
from pathlib import Path
import sys

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
VENDOR_DIR = PLUGIN_ROOT / "pkg" / "skills" / "commentable-html" / "vendor" / "frontend-slides"
DEV_VENDOR_DIR = PLUGIN_ROOT / "dev" / "vendor" / "frontend-slides" / "bold-template-pack"

# Files that are ours (provenance), not upstream-derived, excluded from the hashed set.
SELF_FILES = {"MANIFEST.sha256", "UPSTREAM.md"}
# Names/dirs that must NEVER appear in the vendored subtree (network/deploy/exec or upstream manifest).
DENY_NAMES = {"deploy.sh", "export-pdf.sh"}
DENY_DIRS = {".claude-plugin", ".git"}


def _rel(vendor_dir: Path, p: Path) -> str:
    return p.relative_to(vendor_dir).as_posix()


def _iter_files(vendor_dir: Path):
    for p in sorted(vendor_dir.rglob("*")):
        if p.is_file() and _rel(vendor_dir, p) not in SELF_FILES:
            yield p, _rel(vendor_dir, p)


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _compute(vendor_dir: Path):
    return {rel: _sha256(p) for p, rel in _iter_files(vendor_dir)}


def _denylisted(vendor_dir: Path):
    hits = set()
    for p in vendor_dir.rglob("*"):
        rel_parts = set(p.relative_to(vendor_dir).parts)
        if p.is_file() and p.name in DENY_NAMES:
            hits.add(_rel(vendor_dir, p))
        if rel_parts & DENY_DIRS:
            hits.add(p.relative_to(vendor_dir).as_posix())
    return sorted(hits)


def _read_manifest(vendor_dir: Path):
    entries = {}
    manifest = vendor_dir / "MANIFEST.sha256"
    if not manifest.exists():
        return entries
    for line in manifest.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        digest, path = line.split("  ", 1)
        entries[path] = digest
    return entries


def _write_manifest(vendor_dir: Path, entries):
    lines = [
        "# SHA-256 manifest of the pristine vendored frontend-slides subset.",
        "# Regenerate only after a reviewed resync: python dev/tools/check_vendor.py --update",
        "",
    ]
    lines += [f"{entries[path]}  {path}" for path in sorted(entries)]
    (vendor_dir / "MANIFEST.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(vendor_dir: Path, update: bool = False) -> int:
    if not vendor_dir.exists():
        print(f"check_vendor: vendor dir missing: {vendor_dir}", file=sys.stderr)
        return 1

    deny = _denylisted(vendor_dir)
    if deny:
        print("check_vendor: FORBIDDEN files in the vendored subtree:", file=sys.stderr)
        for d in deny:
            print(f"  {d}", file=sys.stderr)
        return 1

    current = _compute(vendor_dir)

    if update:
        _write_manifest(vendor_dir, current)
        print(f"check_vendor: wrote MANIFEST.sha256 ({len(current)} files)")
        return 0

    recorded = _read_manifest(vendor_dir)
    if not recorded:
        print("check_vendor: no MANIFEST.sha256; run --update after a reviewed resync", file=sys.stderr)
        return 1

    missing = sorted(set(recorded) - set(current))
    unknown = sorted(set(current) - set(recorded))
    changed = sorted(p for p in set(current) & set(recorded) if current[p] != recorded[p])
    if missing or unknown or changed:
        print("check_vendor: vendored subtree does not match MANIFEST.sha256", file=sys.stderr)
        for p in missing:
            print(f"  MISSING {p}", file=sys.stderr)
        for p in unknown:
            print(f"  UNKNOWN {p}", file=sys.stderr)
        for p in changed:
            print(f"  CHANGED {p}", file=sys.stderr)
        print("  If this is an intentional resync, review the diff then run --update.", file=sys.stderr)
        return 1

    print(f"check_vendor: OK ({len(current)} files match manifest)")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Verify the pristine vendored frontend-slides trees.")
    ap.add_argument("--update", action="store_true", help="regenerate each MANIFEST.sha256")
    ap.add_argument("--vendor-dir", help="verify one vendored subtree instead of both (testing)")
    args = ap.parse_args(argv)
    vendor_dirs = (Path(args.vendor_dir),) if args.vendor_dir else (VENDOR_DIR, DEV_VENDOR_DIR)
    return max(run(vendor_dir, update=args.update) for vendor_dir in vendor_dirs)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
