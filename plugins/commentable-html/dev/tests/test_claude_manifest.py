"""CMH-CLAUDE-01: the shipped plugin carries a Claude Code manifest that mirrors the Copilot one.

commentable-html is a portable HTML review surface that works with any agent; this proves the
plugin is installable in Claude Code by shipping `.claude-plugin/plugin.json` whose identity
fields match the Copilot `plugin.json`, plus a resolvable skills directory. The live
`claude plugin validate --strict` check lives in scripts/validate_claude_compat.py.
"""
import json
import os
import unittest

import _paths

# _paths.PKG is the skill root (pkg/skills/commentable-html); the plugin dir is two levels up.
PLUGIN_DIR = os.path.dirname(os.path.dirname(_paths.PKG))
COPILOT_PJ = os.path.join(PLUGIN_DIR, "plugin.json")
CLAUDE_PJ = os.path.join(PLUGIN_DIR, ".claude-plugin", "plugin.json")

_MIRROR_FIELDS = ("name", "version", "description", "author", "license", "keywords")


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


class ClaudeManifestTests(unittest.TestCase):
    def test_claude_plugin_manifest_ships(self):
        self.assertTrue(os.path.isfile(CLAUDE_PJ), f"missing {CLAUDE_PJ}")

    def test_identity_fields_mirror_the_copilot_manifest(self):
        claude = _read(CLAUDE_PJ)
        copilot = _read(COPILOT_PJ)
        for field in _MIRROR_FIELDS:
            self.assertEqual(
                claude.get(field), copilot.get(field), f"{field} must match the Copilot plugin.json"
            )

    def test_skills_path_resolves_and_skill_ships(self):
        claude = _read(CLAUDE_PJ)
        self.assertEqual(claude.get("skills"), "./skills/")
        skills_dir = os.path.join(PLUGIN_DIR, "skills")
        self.assertTrue(os.path.isdir(skills_dir))
        self.assertTrue(os.path.isfile(os.path.join(_paths.PKG, "SKILL.md")))


if __name__ == "__main__":
    unittest.main()
