#!/usr/bin/env python3
"""Validate plugin changelog entries and protect released changelog history.

For each marketplace plugin with plugins/<plugin>/CHANGELOG.md, the plugin's
current version must have a released changelog heading. Released changelog
sections that already exist on the base branch must remain unchanged. Editing
## [Unreleased] and adding new released sections is allowed.

The plugin.json versus marketplace version match is already enforced by
scripts/validate_marketplace.py, so this script does not duplicate it.

Usage:
  python scripts/check_changelog_sync.py [--base origin/main]
"""

import argparse
import json
import os
import posixpath
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ".github/plugin/marketplace.json"

HEADING_RE = re.compile(r"^## \[([^\]]+)\].*$", re.MULTILINE)
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?\Z")


@dataclass(frozen=True)
class PluginChangelog:
    name: str
    root: Path
    changelog: Path
    version: str
    version_source: str


@dataclass(frozen=True)
class HistoryChange:
    version: str
    kind: str


def normalize_newlines(content):
    return content.replace("\r\n", "\n").replace("\r", "\n")


def rel(path, root=ROOT):
    return str(path.relative_to(root)).replace("\\", "/")


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _norm_source(source):
    src = str(source).replace("\\", "/")
    if src.startswith("./"):
        src = src[2:]
    src = posixpath.normpath(src)
    return "" if src == "." else src.strip("/")


def plugin_root_from_source(source):
    parts = [p for p in _norm_source(source).split("/") if p]
    if len(parts) < 2 or parts[0] != "plugins":
        return None
    return Path("plugins") / parts[1]


def current_version_for(root, plugin_root, entry):
    pkg_plugin_json = root / plugin_root / "pkg" / "plugin.json"
    if pkg_plugin_json.exists():
        data = load_json(pkg_plugin_json)
        return str(data.get("version", "")), rel(pkg_plugin_json, root)
    return str(entry.get("version", "")), "marketplace entry %s" % entry.get("name", "<unknown>")


def iter_plugin_changelogs(root, manifest):
    for entry in manifest.get("plugins", []):
        plugin_root = plugin_root_from_source(entry.get("source", ""))
        if plugin_root is None:
            continue
        changelog = root / plugin_root / "CHANGELOG.md"
        if not changelog.exists():
            continue
        version, version_source = current_version_for(root, plugin_root, entry)
        yield PluginChangelog(str(entry.get("name", "<unknown>")), plugin_root, changelog, version, version_source)


def parse_released_sections(content):
    text = normalize_newlines(content)
    matches = list(HEADING_RE.finditer(text))
    sections = {}
    for index, match in enumerate(matches):
        version = match.group(1).strip()
        if not SEMVER_RE.match(version):
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections[version] = text[match.start():end]
    return sections


def has_released_version(content, version):
    return str(version) in parse_released_sections(content)


def check_current_version(plugin_name, changelog_rel, content, version, version_source):
    if has_released_version(content, version):
        return []
    return [
        "%s: %s is missing released heading ## [%s] for the current version from %s. "
        "Add a Keep a Changelog release entry for this version."
        % (plugin_name, changelog_rel, version, version_source)
    ]


def compare_released_history(base_content, head_content):
    base_sections = parse_released_sections(base_content)
    head_sections = parse_released_sections(head_content)
    changes = []
    for version, base_section in base_sections.items():
        head_section = head_sections.get(version)
        if head_section is None:
            changes.append(HistoryChange(version, "removed"))
        elif head_section != base_section:
            changes.append(HistoryChange(version, "modified"))
    return changes


def git_show_text(root, base_ref, repo_relative_path):
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "show", "%s:%s" % (base_ref, repo_relative_path)],
            capture_output=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, "git is unavailable (%s); skipping history check for %s." % (exc, repo_relative_path)
    if result.returncode != 0:
        return None, "%s is unavailable at %s; skipping history check." % (repo_relative_path, base_ref)
    try:
        return result.stdout.decode("utf-8"), None
    except UnicodeDecodeError as exc:
        return None, "%s at %s is not UTF-8 (%s); skipping history check." % (repo_relative_path, base_ref, exc)


def history_failure_message(plugin, change, base_ref):
    if change.kind == "removed":
        return (
            "%s: released changelog section %s from %s was removed from %s. Restore it unchanged."
            % (plugin.name, change.version, base_ref, rel(plugin.changelog))
        )
    return (
        "%s: released changelog section %s from %s was modified in %s. "
        "Do not edit released history; add a new version section or edit ## [Unreleased]."
        % (plugin.name, change.version, base_ref, rel(plugin.changelog))
    )


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Validate that plugin versions have changelog entries and released history is unchanged."
    )
    parser.add_argument(
        "--base",
        default=os.environ.get("CHANGELOG_BASE_REF", "origin/main"),
        help="Git ref used for released-history comparison (default: origin/main).",
    )
    args = parser.parse_args(argv)

    try:
        manifest = load_json(ROOT / MANIFEST)
    except (OSError, json.JSONDecodeError) as exc:
        sys.stderr.write("check-changelog-sync FAILED:\n")
        sys.stderr.write("  - could not read %s: %s\n" % (MANIFEST, exc))
        return 1

    failures = []
    notes = []
    checked_history = set()
    for plugin in iter_plugin_changelogs(ROOT, manifest):
        changelog_rel = rel(plugin.changelog)
        try:
            head_content = plugin.changelog.read_text(encoding="utf-8")
        except OSError as exc:
            failures.append("%s: could not read %s: %s" % (plugin.name, changelog_rel, exc))
            continue

        failures.extend(
            check_current_version(plugin.name, changelog_rel, head_content, plugin.version, plugin.version_source)
        )

        if changelog_rel in checked_history:
            continue
        checked_history.add(changelog_rel)
        base_content, note = git_show_text(ROOT, args.base, changelog_rel)
        if note:
            notes.append("check-changelog-sync: NOTE - " + note)
            continue
        for change in compare_released_history(base_content, head_content):
            failures.append(history_failure_message(plugin, change, args.base))

    for note in notes:
        print(note)

    if failures:
        sys.stderr.write("check-changelog-sync FAILED:\n")
        for failure in failures:
            sys.stderr.write("  - " + failure + "\n")
        return 1

    print("check-changelog-sync OK (current versions have changelog entries and released history is unchanged).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
