#!/usr/bin/env python3
"""Covering tests for the multi-duck plugin (MDUCK-*).

Run by the validate CI job via `python -m unittest discover -s scripts -p "test_*.py"` (and by the
cross-platform matrix), so the multi-duck plugin's registration, dual-host manifests, and the
SKILL.md invariants this PR promises are gated by a required status check. Standard library only.
"""
import json
import os
import re
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = "multi-duck"
PKG = os.path.join(REPO_ROOT, "plugins", "multi-duck", "pkg")
SKILL = os.path.join(PKG, "skills", "multi-duck", "SKILL.md")
README = os.path.join(PKG, "README.md")
CHANGELOG = os.path.join(REPO_ROOT, "plugins", "multi-duck", "CHANGELOG.md")
SPEC = os.path.join(REPO_ROOT, "plugins", "multi-duck", "dev", "SPEC.md")
COPILOT_MKT = os.path.join(REPO_ROOT, ".github", "plugin", "marketplace.json")
CLAUDE_MKT = os.path.join(REPO_ROOT, ".claude-plugin", "marketplace.json")
COPILOT_PJ = os.path.join(PKG, "plugin.json")
CLAUDE_PJ = os.path.join(PKG, ".claude-plugin", "plugin.json")

# Punctuation the repo house style forbids (em dash, en dash, ellipsis).
_FORBIDDEN = "\u2014\u2013\u2026"


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _entry(marketplace_path, name):
    for p in _json(marketplace_path).get("plugins", []):
        if p.get("name") == name:
            return p
    return None


def _front_matter(text):
    """Return the raw YAML front-matter block (between the first two --- fences)."""
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    return m.group(1) if m else ""


class MultiDuckRegistrationTests(unittest.TestCase):
    def test_registered_in_both_marketplaces_with_matching_identity(self):
        # MDUCK-REG-01: multi-duck is registered in the Copilot and Claude marketplace manifests, and
        # the shared identity fields (version, source, description, keywords) match across both plus
        # the two plugin.json files, at 1.0.0.
        cop = _entry(COPILOT_MKT, PLUGIN)
        cla = _entry(CLAUDE_MKT, PLUGIN)
        self.assertIsNotNone(cop, "multi-duck missing from Copilot marketplace")
        self.assertIsNotNone(cla, "multi-duck missing from Claude marketplace")
        self.assertEqual(cop["source"], "./plugins/multi-duck/pkg")
        self.assertEqual(cla["source"], "./plugins/multi-duck/pkg")
        cop_pj = _json(COPILOT_PJ)
        cla_pj = _json(CLAUDE_PJ)
        versions = {cop["version"], cla["version"], cop_pj["version"], cla_pj["version"]}
        self.assertEqual(versions, {"1.0.0"})
        descs = {cop["description"], cla["description"],
                 cop_pj["description"], cla_pj["description"]}
        self.assertEqual(len(descs), 1, "description must be byte-identical across all four manifests")
        self.assertEqual(cop["keywords"], cla["keywords"])
        self.assertEqual(cop_pj["keywords"], cla_pj["keywords"])

    def test_plugin_json_identity_mirrors_across_hosts(self):
        # MDUCK-MANIFEST-02: the Claude plugin.json mirrors the Copilot plugin.json identity fields
        # (the same fields validate_claude_compat enforces), authored by the maintainer under MIT.
        cop_pj = _json(COPILOT_PJ)
        cla_pj = _json(CLAUDE_PJ)
        for field in ("name", "version", "description", "author", "license", "keywords"):
            self.assertEqual(cop_pj.get(field), cla_pj.get(field), "mismatch on %s" % field)
        self.assertEqual(cop_pj["name"], PLUGIN)
        self.assertEqual(cop_pj["license"], "MIT")
        self.assertEqual(cop_pj["author"], {"name": "Uri Kanonov", "email": "urikanonov@gmail.com"})


class MultiDuckSkillTests(unittest.TestCase):
    def test_front_matter_has_name_and_bounded_description(self):
        # MDUCK-SKILL-03: SKILL.md front matter names the skill and carries a non-empty description
        # under the 800-char marketplace limit.
        fm = _front_matter(_read(SKILL))
        self.assertIn("name: multi-duck", fm)
        m = re.search(r"description:\s*>-\n(.*)", fm, re.S)
        self.assertTrue(m, "SKILL.md front matter has no folded description")
        desc = " ".join(line.strip() for line in m.group(1).splitlines() if line.strip())
        self.assertTrue(desc)
        self.assertLess(len(desc), 800)

    def test_documents_both_hosts_with_a_mapping(self):
        # MDUCK-DUAL-05: the skill is genuinely dual-host - it names both agents and gives a host
        # mapping table (a Reviewer subagent row) rather than assuming one host.
        t = _read(SKILL)
        self.assertIn("Claude Code", t)
        self.assertIn("GitHub Copilot CLI", t)
        self.assertIn("## Hosts: how the panel maps to your agent", t)
        self.assertIn("Reviewer subagent", t)

    def test_model_roster_is_an_illustrative_example_not_a_fixed_catalog(self):
        # MDUCK-ROSTER-06: the model roster is framed as a selection STRATEGY with a current example
        # roster (diversity-first), not an authoritative fixed catalog, so it reads as illustration.
        t = _read(SKILL)
        self.assertIn("selection rule is model diversity first", t)
        self.assertIn("current example roster for the GitHub Copilot CLI", t)
        self.assertIn("substitute the equivalents your host exposes", t)

    def test_core_safety_invariants_present(self):
        # MDUCK-SAFE-07: the skill encodes its safety guarantees - review-only ducks, untrusted
        # bundle content (no embedded-instruction obedience), and a publication boundary that forbids
        # autonomous commit/push, plus the risky-change exclusions.
        t = _read(SKILL)
        self.assertIn("review-only", t)
        self.assertIn("untrusted DATA", t)
        self.assertIn("Confine autonomous action to LOCAL", t)
        self.assertIn("Do NOT commit, push", t)
        self.assertIn("no infrastructure or deployment/config change", t)


class MultiDuckHouseStyleTests(unittest.TestCase):
    def test_docs_are_lf_ascii_and_free_of_forbidden_punctuation(self):
        # MDUCK-STYLE-04: every multi-duck doc uses LF line endings, plain ASCII, and none of the
        # forbidden em/en dash or ellipsis characters (the repo house style).
        for path in (SKILL, README, CHANGELOG, SPEC):
            raw = _read(path)
            self.assertNotIn("\r", raw, "%s has CR/CRLF line endings" % os.path.basename(path))
            for ch in _FORBIDDEN:
                self.assertNotIn(ch, raw,
                                 "%s contains a forbidden punctuation char U+%04X"
                                 % (os.path.basename(path), ord(ch)))
            try:
                raw.encode("ascii")
            except UnicodeEncodeError as exc:
                self.fail("%s is not plain ASCII: %s" % (os.path.basename(path), exc))


if __name__ == "__main__":
    unittest.main()
