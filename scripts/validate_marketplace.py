#!/usr/bin/env python3
"""Validate the marketplace manifest, every plugin.json, and every SKILL.md.

Fails (exit 1) on any structural error so broken plugins cannot be merged. Checks:
- marketplace.json parses and matches the marketplace JSON Schema.
- Each manifest entry: unique name, semver version, repo-relative source without '..',
  the source path exists, and it contains either a plugin.json (whose version must match
  the manifest entry) or a SKILL.md (whose front matter must have name + description).
- Every plugins/**/plugin.json parses, matches the plugin JSON Schema, and has a semver version.
- Every plugins/**/SKILL.md has YAML front matter with a non-empty name and description.
- Development-only folders (dev/, node_modules/, __pycache__/) are ignored. A gitignored one nested in a
  shipped source is pruned (git can never commit or ship it); a tracked one nested in a source is rejected.

Run locally: python scripts/validate_marketplace.py
Dependencies: jsonschema, pyyaml.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path, PureWindowsPath

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SEMVER = re.compile(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?\Z")

# Directory names under plugins/ that hold development-only content that is never distributed.
# The validator ignores them, and a manifest source must never resolve into (or contain) one.
RESERVED_DEV_DIRS = {"dev", "node_modules", "__pycache__"}

errors: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)


def rel(p: Path) -> str:
    return str(p.relative_to(ROOT)).replace("\\", "/")


def is_dev_path(path: Path) -> bool:
    return any(part.lower() in RESERVED_DEV_DIRS for part in path.relative_to(ROOT).parts)


def git_ignores(path: Path) -> bool:
    """True if git ignores path, so it can never be committed and thus never shipped.

    Best-effort: if git is unavailable or ROOT is not a git repo, returns False so a
    physically-present dev-only folder is still flagged (strict fallback).
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(ROOT), "check-ignore", "-q", str(path)],
            capture_output=True,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as ex:  # noqa: BLE001
        err(f"{rel(path)}: invalid JSON: {ex}")
        return None


def read_front_matter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^\ufeff?---\s*\r?\n(.*?)\r?\n(?:---|\.\.\.)\s*(?:\r?\n|\Z)", text, re.S)
    if not m:
        return {}
    try:
        data = yaml.safe_load(m.group(1))
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


def main() -> int:
    schema_dir = ROOT / ".github" / "schemas"
    mp_schema = load_json(schema_dir / "marketplace.schema.json")
    pl_schema = load_json(schema_dir / "plugin.schema.json")

    manifest_path = ROOT / ".github" / "plugin" / "marketplace.json"
    manifest = load_json(manifest_path)

    if manifest is not None and mp_schema is not None:
        for e in Draft202012Validator(mp_schema).iter_errors(manifest):
            err(f"marketplace.json schema: {'/'.join(map(str, e.path))}: {e.message}")

    seen: set[str] = set()
    for entry in (manifest or {}).get("plugins", []):
        name = entry.get("name", "<no-name>")
        if name in seen:
            err(f"duplicate plugin name in manifest: {name}")
        seen.add(name)

        version = str(entry.get("version", ""))
        if not SEMVER.match(version):
            err(f"{name}: manifest version is not semver: {version!r}")

        src = entry.get("source", "")
        if not src.startswith("./") or ".." in src:
            err(f"{name}: source must be repo-relative and must not contain '..': {src!r}")
            continue
        if any(part.lower() in RESERVED_DEV_DIRS for part in src.strip("./").split("/")):
            err(
                f"{name}: source must not live under a dev-only folder "
                f"({', '.join(sorted(RESERVED_DEV_DIRS))}): {src!r}"
            )
            continue

        raw_src = ROOT / src
        if raw_src.is_symlink():
            err(f"{name}: source must not be a symlink: {src!r}")
            continue
        src_path = raw_src.resolve()
        if ROOT != src_path and ROOT not in src_path.parents:
            err(f"{name}: source escapes the repository: {src!r}")
            continue
        if not src_path.exists():
            err(f"{name}: source path does not exist: {src!r}")
            continue
        if src_path.name.lower() in RESERVED_DEV_DIRS:
            err(f"{name}: source is itself a dev-only folder: {src!r}")
            continue

        # Walk without following symlinks (Python 3.12 rglob would descend into symlinked dirs).
        for dirpath, dirnames, filenames in os.walk(src_path, followlinks=False):
            base = Path(dirpath)
            # Prune gitignored dev-only folders: git never commits them, so an install (a clean
            # checkout) can never ship them. Don't descend into or flag them.
            for d in list(dirnames):
                if d.lower() in RESERVED_DEV_DIRS and git_ignores(base / d):
                    dirnames.remove(d)
            for entry in list(dirnames) + filenames:
                if (base / entry).is_symlink():
                    err(f"{name}: shipped source must not contain a symlink: {rel(base / entry)}")
            for d in dirnames:
                if d.lower() in RESERVED_DEV_DIRS:
                    err(f"{name}: shipped source would distribute a dev-only folder: {rel(base / d)}")

        plugin_json = src_path / "plugin.json"
        skill_md = src_path / "SKILL.md"
        if plugin_json.exists():
            pj = load_json(plugin_json)
            if pj is not None:
                if str(pj.get("version", "")) != version:
                    err(
                        f"{name}: manifest version {version} != {rel(plugin_json)} "
                        f"version {pj.get('version')!r}"
                    )
                if pj.get("name") != name:
                    err(
                        f"{name}: {rel(plugin_json)} name {pj.get('name')!r} does not match "
                        f"manifest entry name {name!r}"
                    )
                for key in ("hooks", "skills"):
                    ref = pj.get(key)
                    if not ref:
                        continue
                    parts = str(ref).replace("\\", "/").split("/")
                    target = (src_path / ref).resolve()
                    src_resolved = src_path.resolve()
                    within = target == src_resolved or src_resolved in target.parents
                    if (
                        PureWindowsPath(str(ref)).is_absolute()
                        or str(ref).startswith("/")
                        or ".." in parts
                        or any(p.lower() in RESERVED_DEV_DIRS for p in parts)
                        or not within
                    ):
                        err(f"{name}: {rel(plugin_json)} '{key}' path escapes the shipped source: {ref!r}")
                        continue
                    if key == "hooks":
                        if not target.is_file():
                            err(f"{name}: {rel(plugin_json)} 'hooks' target does not exist: {ref!r}")
                        else:
                            load_json(target)
                    elif not target.is_dir():
                        err(f"{name}: {rel(plugin_json)} 'skills' target is not a directory: {ref!r}")
        elif skill_md.exists():
            fm = read_front_matter(skill_md)
            if not fm.get("name"):
                err(f"{name}: {rel(skill_md)} front matter is missing 'name'")
            if not fm.get("description"):
                err(f"{name}: {rel(skill_md)} front matter is missing 'description'")
        else:
            err(f"{name}: source has neither plugin.json nor SKILL.md: {src!r}")

    for pj_path in sorted(ROOT.glob("plugins/**/plugin.json")):
        if is_dev_path(pj_path):
            continue
        pj = load_json(pj_path)
        if pj is None:
            continue
        if pl_schema is not None:
            for e in Draft202012Validator(pl_schema).iter_errors(pj):
                err(f"{rel(pj_path)} schema: {'/'.join(map(str, e.path))}: {e.message}")
        if not SEMVER.match(str(pj.get("version", ""))):
            err(f"{rel(pj_path)}: version is not semver: {pj.get('version')!r}")

    for skill_md in sorted(ROOT.glob("plugins/**/SKILL.md")):
        if is_dev_path(skill_md):
            continue
        fm = read_front_matter(skill_md)
        if not fm.get("name"):
            err(f"{rel(skill_md)}: front matter is missing 'name'")
        if not fm.get("description"):
            err(f"{rel(skill_md)}: front matter is missing 'description'")

    if errors:
        print(f"Validation FAILED with {len(errors)} error(s):")
        for e in errors:
            print(f"  - {e}")
        return 1

    print("Validation passed: manifest, plugins, and skills are consistent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
