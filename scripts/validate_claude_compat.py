#!/usr/bin/env python3
"""Validate that this repo's plugins are installable in Claude Code.

Two layers:

1. Structural (always, no network, no CLI): every plugin listed in the Claude marketplace
   manifest (`.claude-plugin/marketplace.json`) must mirror the GitHub Copilot marketplace
   (`.github/plugin/marketplace.json`) and carry a `.claude-plugin/plugin.json` whose
   identity fields (name, version, description, author, license, keywords) match the Copilot
   `plugin.json`. Claude support may be a subset of the Copilot marketplace (plugins gain
   Claude manifests incrementally), so the check runs Claude -> Copilot, not the reverse.

2. Live (only when the `claude` CLI is on PATH, or `--require-cli` is passed): runs
   `claude plugin validate --strict` on the marketplace manifest and each Claude plugin dir,
   which is the authoritative check that Claude Code accepts the manifests.

Exit code 0 when compatible, 1 on any error. Standard library only.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

# Identity fields a Claude plugin.json must share with the Copilot plugin.json.
_MIRROR_FIELDS = ("name", "version", "description", "author", "license", "keywords")

# Marketplace-entry fields that are intentionally Copilot-marketplace-specific: Claude's marketplace
# schema does not define them, so they are excluded from the Claude<->Copilot entry mirror. Every
# OTHER shared field (description, author, homepage, repository, license, keywords, ...) must match so
# the two manifests cannot drift silently.
_COPILOT_ONLY_MARKETPLACE_FIELDS = ("category", "strict")


def _load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _entries_by_name(marketplace):
    return {p.get("name"): p for p in marketplace.get("plugins", []) if p.get("name")}


def structural_errors(repo_root):
    """Return a list of Claude-compat structural errors for the repo (empty when compatible)."""
    errors = []
    claude_mkt_path = os.path.join(repo_root, ".claude-plugin", "marketplace.json")
    copilot_mkt_path = os.path.join(repo_root, ".github", "plugin", "marketplace.json")

    if not os.path.isfile(claude_mkt_path):
        return [f"missing Claude marketplace manifest: {claude_mkt_path}"]
    if not os.path.isfile(copilot_mkt_path):
        return [f"missing Copilot marketplace manifest: {copilot_mkt_path}"]

    try:
        claude_mkt = _load_json(claude_mkt_path)
    except (OSError, ValueError) as exc:
        return [f".claude-plugin/marketplace.json is not valid JSON: {exc}"]
    try:
        copilot_mkt = _load_json(copilot_mkt_path)
    except (OSError, ValueError) as exc:
        return [f".github/plugin/marketplace.json is not valid JSON: {exc}"]

    copilot_by_name = _entries_by_name(copilot_mkt)

    claude_plugins = claude_mkt.get("plugins", [])
    if not claude_plugins:
        errors.append(".claude-plugin/marketplace.json lists no plugins")

    for entry in claude_plugins:
        name = entry.get("name")
        if not name:
            errors.append("a Claude marketplace entry has no name")
            continue
        copilot_entry = copilot_by_name.get(name)
        if copilot_entry is None:
            errors.append(f"{name}: in the Claude marketplace but not the Copilot marketplace")
            continue
        for field in sorted(set(entry) | set(copilot_entry)):
            if field in _COPILOT_ONLY_MARKETPLACE_FIELDS:
                continue
            if entry.get(field) != copilot_entry.get(field):
                errors.append(
                    f"{name}: Claude marketplace {field} {entry.get(field)!r} != "
                    f"Copilot {field} {copilot_entry.get(field)!r}"
                )

        source = entry.get("source", "")
        if not source.startswith("./") or ".." in source:
            errors.append(f"{name}: source must be a repo-relative './' path: {source!r}")
            continue
        plugin_dir = os.path.normpath(os.path.join(repo_root, source))
        claude_pj_path = os.path.join(plugin_dir, ".claude-plugin", "plugin.json")
        copilot_pj_path = os.path.join(plugin_dir, "plugin.json")
        if not os.path.isfile(claude_pj_path):
            errors.append(f"{name}: missing Claude plugin manifest: {claude_pj_path}")
            continue
        try:
            claude_pj = _load_json(claude_pj_path)
        except (OSError, ValueError) as exc:
            errors.append(f"{name}: .claude-plugin/plugin.json is not valid JSON: {exc}")
            continue

        # Mirror the Copilot plugin.json identity fields when it exists (commentable-html shape).
        if os.path.isfile(copilot_pj_path):
            try:
                copilot_pj = _load_json(copilot_pj_path)
            except (OSError, ValueError) as exc:
                errors.append(f"{name}: plugin.json is not valid JSON: {exc}")
                copilot_pj = None
            if copilot_pj is not None:
                for field in _MIRROR_FIELDS:
                    if claude_pj.get(field) != copilot_pj.get(field):
                        errors.append(
                            f"{name}: Claude plugin.json {field} != Copilot plugin.json {field}"
                        )

        # A skills path, when declared, must resolve to a real skills directory.
        skills = claude_pj.get("skills")
        if isinstance(skills, str):
            skills_dir = os.path.normpath(os.path.join(plugin_dir, skills))
            if not os.path.isdir(skills_dir):
                errors.append(f"{name}: skills path does not resolve to a directory: {skills!r}")

    return errors


def _run_claude_validate(target):
    proc = subprocess.run(
        ["claude", "plugin", "validate", target, "--strict"],
        capture_output=True,
        text=True,
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def live_errors(repo_root):
    """Run `claude plugin validate --strict` on the marketplace and each Claude plugin dir."""
    errors = []
    targets = [os.path.join(repo_root, ".claude-plugin", "marketplace.json")]
    claude_mkt_path = targets[0]
    if os.path.isfile(claude_mkt_path):
        try:
            claude_mkt = _load_json(claude_mkt_path)
        except (OSError, ValueError):
            claude_mkt = {"plugins": []}
        for entry in claude_mkt.get("plugins", []):
            source = entry.get("source", "")
            if source.startswith("./") and ".." not in source:
                targets.append(os.path.normpath(os.path.join(repo_root, source)))
    for target in targets:
        code, out = _run_claude_validate(target)
        if code != 0:
            errors.append(f"claude plugin validate failed for {target}:\n{out.strip()}")
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate Claude Code plugin compatibility.")
    parser.add_argument("--repo-root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    parser.add_argument(
        "--require-cli",
        action="store_true",
        help="fail if the `claude` CLI is not installed (default: skip the live check)",
    )
    args = parser.parse_args(argv)
    repo_root = args.repo_root

    errors = structural_errors(repo_root)

    have_cli = shutil.which("claude") is not None
    if have_cli:
        errors.extend(live_errors(repo_root))
    elif args.require_cli:
        errors.append("the `claude` CLI is not on PATH but --require-cli was passed")

    if errors:
        sys.stderr.write("Claude compatibility: FAILED\n")
        for e in errors:
            sys.stderr.write(f"  - {e}\n")
        return 1

    if have_cli:
        print("Claude compatibility: OK (structural + `claude plugin validate --strict`)")
    else:
        print("Claude compatibility: OK (structural only; `claude` CLI not found, live check skipped)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
