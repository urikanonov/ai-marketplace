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


def current_version_for(root, source, entry):
    """Resolve the plugin's current version from the plugin.json at the manifest source
    (this covers both a pkg/ layout, e.g. plugins/<p>/pkg/plugin.json, and a plugin-dir
    layout, e.g. plugins/<p>/plugin.json). Fall back to the manifest entry version when the
    source has no plugin.json (a single-skill source); validate_marketplace.py enforces that
    a plugin.json version matches the manifest entry."""
    src = _norm_source(source)
    if src:
        plugin_json = root / src / "plugin.json"
        if plugin_json.exists():
            data = load_json(plugin_json)
            return str(data.get("version", "")), rel(plugin_json, root)
    return str(entry.get("version", "")), "marketplace entry %s" % entry.get("name", "<unknown>")


def iter_plugin_changelogs(root, manifest):
    for entry in manifest.get("plugins", []):
        source = entry.get("source", "")
        plugin_root = plugin_root_from_source(source)
        if plugin_root is None:
            continue
        changelog = root / plugin_root / "CHANGELOG.md"
        if not changelog.exists():
            continue
        version, version_source = current_version_for(root, source, entry)
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


def duplicate_released_headings(content):
    """Return semver versions whose released heading appears more than once. A duplicate
    heading lets a PR prepend a second section with rewritten history that the by-version
    comparison would otherwise miss."""
    text = normalize_newlines(content)
    counts = {}
    for match in HEADING_RE.finditer(text):
        version = match.group(1).strip()
        if SEMVER_RE.match(version):
            counts[version] = counts.get(version, 0) + 1
    return sorted(v for v, n in counts.items() if n > 1)


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
    """Return (content, error, skip_note). A path that is simply new at the base ref is a
    safe skip (skip_note set); a base ref that cannot be resolved is a hard error, because
    the tamper guard must not silently stop enforcing history."""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "show", "%s:%s" % (base_ref, repo_relative_path)],
            capture_output=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, None, "git is unavailable (%s); skipping history check for %s." % (exc, repo_relative_path)
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", "replace").lower()
        if "does not exist in" in stderr or "exists on disk, but not in" in stderr:
            return None, None, "%s is new at %s; skipping history check." % (repo_relative_path, base_ref)
        first = (stderr.strip().splitlines() or ["git show failed"])[0]
        return None, (
            "cannot resolve base ref '%s' to verify released history of %s (%s); "
            "fetch the base branch (fetch-depth: 0) or set CHANGELOG_BASE_REF."
            % (base_ref, repo_relative_path, first)
        ), None
    try:
        return result.stdout.decode("utf-8"), None, None
    except UnicodeDecodeError as exc:
        return None, None, "%s at %s is not UTF-8 (%s); skipping history check." % (repo_relative_path, base_ref, exc)


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


def _git_out(root, args):
    try:
        result = subprocess.run(["git", "-C", str(root)] + args, capture_output=True)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.decode("utf-8", "replace").strip() or None


def _rev_parse(root, ref):
    return _git_out(root, ["rev-parse", "--verify", "--quiet", ref + "^{commit}"])


def resolve_base_ref(root, base_ref):
    """Compare released history against the commit the current work diverged from, not the
    live tip of base_ref. Using merge-base(base_ref, HEAD) means a concurrent advance of the
    base branch (a sibling PR merging while this one is open) does not look like removed
    history and spuriously fail the check. When the merge-base is HEAD itself - which is what
    a push to main looks like, where base_ref (origin/main) is the just-pushed commit - fall
    back to HEAD's first parent so the push is still checked against the previous tip. Fall
    back to base_ref when git history is unavailable (git_show_text then reports it)."""
    head = _rev_parse(root, "HEAD")
    merge_base = _git_out(root, ["merge-base", base_ref, "HEAD"])
    if merge_base and merge_base != head:
        return merge_base
    if head and _rev_parse(root, "HEAD^"):
        return "HEAD^"
    return base_ref


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
    base_ref = resolve_base_ref(ROOT, args.base)

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
        for version in duplicate_released_headings(head_content):
            failures.append(
                "%s: %s has a duplicate released heading ## [%s]; each version must appear once "
                "(a duplicate can hide edited history)." % (plugin.name, changelog_rel, version)
            )

        if changelog_rel in checked_history:
            continue
        checked_history.add(changelog_rel)
        base_content, error, note = git_show_text(ROOT, base_ref, changelog_rel)
        if error:
            failures.append("%s: %s" % (plugin.name, error))
            continue
        if note:
            notes.append("check-changelog-sync: NOTE - " + note)
            continue
        for change in compare_released_history(base_content, head_content):
            failures.append(history_failure_message(plugin, change, base_ref))

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
