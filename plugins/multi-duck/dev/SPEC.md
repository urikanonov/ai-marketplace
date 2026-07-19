# multi-duck feature specification

The `multi-duck` skill convenes a panel of independent rubber-duck reviewer subagents (each on a
different model) over the work in flight, consolidates their findings, and autonomously applies the
safe fixes. It ships as a single documentation skill (`pkg/skills/multi-duck/SKILL.md`) with no
runtime code, and it targets both Claude Code and the GitHub Copilot CLI.

Because the shipped surface is an instruction document, its "features" are the promises the SKILL.md
makes and the plugin's registration and dual-host packaging. Each is pinned by a covering test that
runs in the required `validate` and `cross-platform` CI jobs (they run
`python -m unittest discover -s scripts -p "test_*.py"`). The plugin has no browser runtime, so its
tests are Python, not Playwright; the site page for the plugin is covered separately by the
`SITE-MDUCK-*` rows in `site/tests/SPEC.md`.

Coverage notation: each row names the covering test method in `scripts/test_multi_duck.py`.

| Feature id | Behavior | Covering test |
| --- | --- | --- |
| MDUCK-REG-01 | multi-duck is registered in BOTH the Copilot (`.github/plugin/marketplace.json`) and Claude (`.claude-plugin/marketplace.json`) marketplace manifests, with `source: ./plugins/multi-duck/pkg`, and a byte-identical description and matching keywords across both entries and both `plugin.json` files, all at version 1.0.1. | `scripts/test_multi_duck.py` - `MultiDuckRegistrationTests.test_registered_in_both_marketplaces_with_matching_identity` |
| MDUCK-MANIFEST-02 | The Claude `pkg/.claude-plugin/plugin.json` mirrors the Copilot `pkg/plugin.json` identity fields (name, version, description, author, license, keywords) that `validate_claude_compat.py` enforces; the plugin is authored as `Uri Kanonov <urikanonov@gmail.com>` under MIT. | `scripts/test_multi_duck.py` - `MultiDuckRegistrationTests.test_plugin_json_identity_mirrors_across_hosts` |
| MDUCK-SKILL-03 | SKILL.md front matter names the skill `multi-duck` and carries a non-empty trigger description under the 800-character marketplace limit. | `scripts/test_multi_duck.py` - `MultiDuckSkillTests.test_front_matter_has_name_and_bounded_description` |
| MDUCK-STYLE-04 | Every shipped/dev multi-duck doc (SKILL.md, README.md, CHANGELOG.md, dev/SPEC.md) uses LF line endings and plain ASCII, with no em dash, en dash, or ellipsis characters (the repo house style). | `scripts/test_multi_duck.py` - `MultiDuckHouseStyleTests.test_docs_are_lf_ascii_and_free_of_forbidden_punctuation` |
| MDUCK-DUAL-05 | The skill is genuinely dual-host: it names both Claude Code and the GitHub Copilot CLI and provides a "Hosts" mapping (reviewer subagent, per-duck model, parallel launch, result collection, tracking store, scratch dir) rather than assuming a single host. | `scripts/test_multi_duck.py` - `MultiDuckSkillTests.test_documents_both_hosts_with_a_mapping` |
| MDUCK-ROSTER-06 | The model roster is framed as a diversity-first selection STRATEGY with a clearly-labelled current example roster (substitute the equivalents your host exposes), not an authoritative fixed catalog. | `scripts/test_multi_duck.py` - `MultiDuckSkillTests.test_model_roster_is_an_illustrative_example_not_a_fixed_catalog` |
| MDUCK-SAFE-07 | The skill encodes its safety guarantees: the ducks are review-only, the reviewed bundle is treated as untrusted data (embedded directives are never obeyed), autonomous action is confined to local edits and validation (no commit, push, or PR mutation), and risky changes (API, dependency, migration, security, infrastructure, history rewrite, deletions) are excluded from autonomous fixes. | `scripts/test_multi_duck.py` - `MultiDuckSkillTests.test_core_safety_invariants_present` |
| MDUCK-LICENSE-08 | The shipped package includes a `LICENSE` file that is byte-identical to the repository's canonical MIT license text, including `Copyright (c) 2026 Uri Kanonov`. | `scripts/test_multi_duck.py` - `MultiDuckRegistrationTests.test_shipped_package_includes_canonical_mit_license` |

## Coverage gaps

None. Every row above names an automated test that runs in the required CI jobs.
