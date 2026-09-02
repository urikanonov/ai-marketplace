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
EXTRACTOR = os.path.join(PKG, "skills", "multi-duck", "tools", "extract_open_comments.py")
README = os.path.join(PKG, "README.md")
CHANGELOG = os.path.join(REPO_ROOT, "plugins", "multi-duck", "CHANGELOG.md")
SPEC = os.path.join(REPO_ROOT, "plugins", "multi-duck", "dev", "SPEC.md")
COPILOT_MKT = os.path.join(REPO_ROOT, ".github", "plugin", "marketplace.json")
CLAUDE_MKT = os.path.join(REPO_ROOT, ".claude-plugin", "marketplace.json")
COPILOT_PJ = os.path.join(PKG, "plugin.json")
CLAUDE_PJ = os.path.join(PKG, ".claude-plugin", "plugin.json")
LICENSE = os.path.join(PKG, "LICENSE")
ROOT_LICENSE = os.path.join(REPO_ROOT, "LICENSE")

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


def _md_table_rows(text, header_line):
    """Return the data rows (each a list of stripped cell strings) of the first Markdown
    pipe-table whose header row equals header_line, skipping the `---|---` separator."""
    lines = text.splitlines()
    try:
        start = next(i for i, ln in enumerate(lines) if ln.strip() == header_line)
    except StopIteration:
        return []
    rows = []
    for ln in lines[start + 2:]:  # +1 header, +1 the |---|---| separator
        if not ln.strip().startswith("|"):
            break
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        rows.append(cells)
    return rows


def _base_family(cell):
    """Normalise a roster/prisms family cell (e.g. 'Anthropic Opus', 'Microsoft MAI',
    'OpenAI (5.6 sibling variant)') to its base provider (first word)."""
    return cell.split()[0] if cell else ""


class MultiDuckRegistrationTests(unittest.TestCase):
    def test_registered_in_both_marketplaces_with_matching_identity(self):
        # MDUCK-REG-01: multi-duck is registered in the Copilot and Claude marketplace manifests, and
        # the shared identity fields (version, source, description, keywords) match across both plus
        # the two plugin.json files, at the version the CHANGELOG's newest release heading names.
        # The expected version is DERIVED rather than hardcoded: a literal went stale the moment a
        # release bumped the four manifests and reddened this required test for no real defect. The
        # drift-detection value is unchanged - all four manifests must still agree with each other
        # AND with the changelog, which is the actual invariant.
        cop = _entry(COPILOT_MKT, PLUGIN)
        cla = _entry(CLAUDE_MKT, PLUGIN)
        self.assertIsNotNone(cop, "multi-duck missing from Copilot marketplace")
        self.assertIsNotNone(cla, "multi-duck missing from Claude marketplace")
        self.assertEqual(cop["source"], "./plugins/multi-duck/pkg")
        self.assertEqual(cla["source"], "./plugins/multi-duck/pkg")
        cop_pj = _json(COPILOT_PJ)
        cla_pj = _json(CLAUDE_PJ)
        released = re.search(r"^## \[(\d+\.\d+\.\d+)\]", _read(CHANGELOG), re.MULTILINE)
        self.assertIsNotNone(released, "CHANGELOG.md has no versioned release heading")
        versions = {cop["version"], cla["version"], cop_pj["version"], cla_pj["version"]}
        self.assertEqual(
            versions, {released.group(1)},
            "all four manifests must carry the version of the newest CHANGELOG release heading",
        )
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

    def test_shipped_package_includes_canonical_mit_license(self):
        # MDUCK-LICENSE-08: installs include the full canonical MIT text, not only a manifest label.
        with open(ROOT_LICENSE, "rb") as fh:
            expected = fh.read()
        with open(LICENSE, "rb") as fh:
            actual = fh.read()
        self.assertEqual(actual, expected)


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

    def test_roster_leads_with_opus5_and_documents_run_rotation(self):
        # MDUCK-ROTATE-11: the example roster leads with claude-opus-5 (roster row 1 and duck 1 in
        # the prisms table), and the skill documents rotating/refreshing the roster across repeated
        # runs while keeping the top flagships and widening the panel when weaker models take part.
        t = _read(SKILL)
        # claude-opus-5 leads both the roster table (row 1) and the prisms assignment (duck 1).
        self.assertIn("| 1 | `claude-opus-5` | Anthropic Opus |", t)
        self.assertIn("| 1 | `claude-opus-5` | Anthropic | correctness & logic bugs |", t)
        # The lead is a fresh flagship, so the prior generation is now a tail row, not the lead.
        self.assertNotIn("| 1 | `claude-opus-4.8` | Anthropic Opus |", t)
        # A dedicated repeated-runs section covers rotation, keeping the anchors, and widening.
        self.assertIn("### Repeated runs: rotate the roster and widen for weaker models", t)
        self.assertIn("Keep the top flagships every run", t)
        self.assertIn("Rotate the tail between runs", t)
        self.assertIn("Widen the panel when weaker models take part", t)
        self.assertIn("increase `count`", t)
        # Pin the SUBSTANTIVE rotation rules, not just their headings, so removing them fails the test:
        # rotate to models earlier runs did not use, and (prisms) rotate model-to-aspect assignments.
        self.assertIn("no earlier run has used", t)
        self.assertIn("rotate which model reviews which aspect", t)
        self.assertIn("raise `count` by roughly one duck per weaker model added", t)

        # The two invariants MDUCK-ROTATE-11 promises are asserted against the actual tables, so a
        # future roster refresh that breaks them (e.g. a second same-family model in the front-load
        # positions, or a same-family aspect pair) fails this test rather than passing silently.
        roster = _md_table_rows(t, "| # | example model | family |")
        self.assertGreaterEqual(len(roster), 4, "roster table not found or too short")
        # Front-load one model per family: with D distinct families in the roster, the FIRST D rows
        # must all be distinct families (no family taken twice before every family appears once).
        families = [_base_family(r[2]) for r in roster]
        distinct = len(set(families))
        self.assertGreaterEqual(distinct, 4,
                                "roster must span at least 4 provider families, got %r" % sorted(set(families)))
        front = families[:distinct]
        self.assertEqual(len(set(front)), distinct,
                         "the first %d rows must front-load one model per family before any repeat, "
                         "got %r" % (distinct, front))
        self.assertEqual(families[0], "Anthropic")  # opus-5 leads

        # Every prisms aspect is covered by two ducks on DIFFERENT families. Asserted from the table
        # itself rather than against a hardcoded panel size, so changing the DEFAULT count (which is
        # what the worked example illustrates) cannot redden this row: the invariant is 2 ducks per
        # aspect on different families, not any particular number of ducks.
        prisms = _md_table_rows(t, "| duck | model | family | aspect |")
        self.assertGreaterEqual(len(prisms), 4, "prisms example table not found or too short")
        self.assertEqual(len(prisms) % 2, 0, "the prisms example must pair every aspect")
        by_aspect = {}
        for _duck, _model, family, aspect in ((r[0], r[1], r[2], r[3]) for r in prisms):
            by_aspect.setdefault(aspect, []).append(_base_family(family))
        self.assertEqual(len(by_aspect), len(prisms) // 2, "expected 2 ducks per aspect")
        for aspect, fams in by_aspect.items():
            self.assertEqual(len(fams), 2, "aspect %r must have exactly 2 ducks" % aspect)
            self.assertNotEqual(fams[0], fams[1],
                                "aspect %r must pair two different families, got %r" % (aspect, fams))

    def test_extractor_is_shipped_and_referenced_not_inlined(self):
        # MDUCK-EXTRACT-09: the open-comments extractor ships as a real file under tools/, SKILL.md
        # references it via the plugin root, and the inline parser listing is gone (not rehydrated
        # from the doc on every run).
        self.assertTrue(os.path.isfile(EXTRACTOR),
                        "multi-duck must ship tools/extract_open_comments.py")
        t = _read(SKILL)
        self.assertIn("tools/extract_open_comments.py", t)
        self.assertIn("${CLAUDE_PLUGIN_ROOT}/skills/multi-duck/tools/extract_open_comments.py", t)
        # The old inline HTMLParser listing must not reappear in the doc.
        self.assertNotIn("from html.parser import HTMLParser", t)
        self.assertNotIn("class _Doc(HTMLParser)", t)

    def test_targetless_discovery_asks_instead_of_auto_picking_downloads(self):
        # MDUCK-DISCOVER-10: a targetless run does not auto-select the newest Downloads HTML by
        # mtime; it stops and asks the user when no target is clearly identified. An explicit or
        # session-identified target takes priority over scratch/cwd discovery (a scratch/cwd file
        # must never override an explicit target), and scratch/cwd is searched only for a targetless
        # run and only for a candidate unambiguously tied to this session.
        t = _read(SKILL)
        self.assertIn("Do NOT auto-select an arbitrary document from the user's Downloads folder", t)
        self.assertIn("STOP and ASK the user which document or target to review", t)
        self.assertNotIn("Rank by most-recently-modified", t)
        # Priority invariant: explicit/session-identified targets are honored before scratch/cwd,
        # and the old stop-at-first-hit ordering (scratch/cwd first) is gone.
        self.assertNotIn("stop at the first non-empty hit", t)
        self.assertIn("honor the clearly-intended target FIRST", t)
        self.assertIn("never let a scratch or working-tree file override it", t)
        self.assertIn("Targetless run only", t)
        self.assertIn("unambiguously tied to this session", t)
        # The explicit-target item must precede the targetless scratch/cwd discovery item in the doc.
        explicit_pos = t.find("**Explicit target**")
        targetless_pos = t.find("**Targetless run only**")
        self.assertGreater(explicit_pos, -1, "discovery must list an explicit-target rule")
        self.assertGreater(targetless_pos, explicit_pos,
                           "explicit-target discovery must precede targetless scratch/cwd discovery")

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


class MultiDuckScopeGateTests(unittest.TestCase):
    def test_the_panel_respects_a_declared_threat_model_and_dismisses_out_of_scope_findings(self):
        # MDUCK-SCOPE-12: the panel collects the project's declared threat model / non-goals into the
        # shared bundle, instructs every duck to respect it, and consolidates an out-of-scope finding
        # as a recorded DISMISSAL instead of a follow-up issue. Without this a review panel
        # manufactures work faster than it can be done (branching factor 1.83 over issues #623-#1073).
        t = _read(SKILL)
        # It is gathered into the bundle...
        self.assertIn("Declared threat model and non-goals", t)
        self.assertIn("the declared threat model / non-goals", t)
        # ...the ducks are told to honor it...
        self.assertIn("RESPECT THE DECLARED THREAT MODEL AND NON-GOALS", t)
        self.assertIn("declares TRUSTED", t)
        self.assertIn("already accepted by design", t)
        # ...a POLICY disagreement is raised as a question, not laundered into a finding...
        self.assertIn("never laundered into `FINDINGS:` as if it were a bug", t)
        self.assertIn("The split is by KIND OF CLAIM", t)
        # ...and consolidation records the dismissal without spawning an issue.
        self.assertIn("Dismissed-as-out-of-scope", t)
        self.assertIn("Do NOT open a follow-up issue for a dismissed finding", t)

    def test_the_scope_gate_still_admits_the_findings_that_always_matter(self):
        # MDUCK-SCOPE-12: the gate is not a blanket silencer - a weakened enforcement layer, a false
        # positive that breaks benign input, and validator drift stay in scope. The always-in-scope
        # list must reach BOTH audiences: whoever assembles the bundle (Step 1) and the ducks
        # themselves (the shared hard rules). Asserted per SECTION rather than as a global count, so
        # an extra harmless mention elsewhere cannot redden this.
        t = _read(SKILL)
        bundle, _, rest = t.partition("**Shared hard rules**")
        self.assertTrue(rest, "SKILL.md no longer has a 'Shared hard rules' section")
        for section, label in ((bundle, "bundle assembly"), (rest, "shared hard rules")):
            self.assertIn(
                "WEAKENS a declared enforcement layer", section,
                "the always-in-scope list must appear in the " + label + " section",
            )
        self.assertIn("FALSE POSITIVE where a guard breaks or rejects benign input", t)
        self.assertIn("its own validator rejects", t)

    def test_an_inaccurate_enforcement_claim_can_never_be_dismissed_as_out_of_scope(self):
        # MDUCK-SCOPE-12: the escape hatch that stops the gate becoming a suppression tool. A duck
        # that can SHOW a channel the project asserts is blocked is not blocked has disproved the
        # non-goal, so it must be reported as a finding rather than demoted to a question - the
        # panel found exactly this (a WebRTC channel no CSP directive covers) while reviewing the
        # change that introduced this gate.
        t = _read(SKILL)
        self.assertIn("EVIDENCE THAT A DECLARED ENFORCEMENT CLAIM IS FACTUALLY INACCURATE", t)
        self.assertIn("never demote it to a question", t)

    def test_findings_are_verified_before_filing_and_questions_are_carried_through(self):
        # MDUCK-SCOPE-12: filtering out-of-scope findings does not filter WRONG ones, so a finding is
        # confirmed against the code before it becomes an issue; and an unresolved question against a
        # declared non-goal reaches a human instead of dying in the panel.
        t = _read(SKILL)
        self.assertIn("Verify BEFORE you file, not just before you fix", t)
        self.assertIn("never filed as a defect", t)
        self.assertIn("Carry unresolved `QUESTIONS:` through", t)
        self.assertIn("must reach a human, not die in the panel", t)

    def test_the_scope_policy_is_read_from_the_base_revision_not_the_reviewed_diff(self):
        # MDUCK-SCOPE-12: without this a PR could ADD a non-goal declaring its own vulnerability class
        # accepted by design and have the panel suppress findings about itself - and the diff is
        # untrusted data, so a policy taken from it is attacker-controlled.
        t = _read(SKILL)
        self.assertIn("Read them from the BASE/target revision, never from the PR's own checkout", t)
        self.assertIn("do NOT apply it as scope policy to its own diff", t)

    def test_a_dismissed_candidate_actually_reaches_the_consolidator(self):
        # MDUCK-SCOPE-12: the ducks are told to keep out-of-scope candidates OUT of FINDINGS, so
        # without a dedicated channel the consolidator could never record the auditable dismissal it
        # promises. The output shape carries a SCOPED-OUT section and consolidation consumes it.
        t = _read(SKILL)
        self.assertIn("`SCOPED-OUT:`", t)
        self.assertIn("Consume each duck's `SCOPED-OUT:` section", t)
        self.assertIn("never in `FINDINGS:`", t)


    def test_an_incidental_pre_existing_finding_is_not_filed_as_an_issue(self):
        # MDUCK-SCOPE-12: the highest-volume generator. A panel reviewing a change kept spinning off
        # PRE-EXISTING defects it noticed in passing - 47% of the issues filed in one two-day window -
        # which is what held the branching factor at 1.52, above 1.0. Scope is the CHANGE under
        # review; a problem equally present on the base revision is routed to SCOPED-OUT instead.
        t = _read(SKILL)
        self.assertIn("Nor is a PRE-EXISTING defect you noticed incidentally", t)
        self.assertIn("equally present on the base revision", t)
        # The narrow exception must survive, so the rule cannot silence genuine breakage.
        self.assertIn(
            "unless it is user-observable breakage, data loss, or a security issue reachable under"
            " the declared threat model", t,
        )


class MultiDuckPanelBudgetTests(unittest.TestCase):
    def test_the_default_panel_is_four_ducks(self):
        # MDUCK-COUNT-13: a duck is a whole model context over the same bundle, so the default panel
        # is the smallest one that covers BOTH top aspects with two cross-family opinions each: 4,
        # not 8. Every place the doc states the default has to agree, or an agent reading one section
        # launches a panel twice the size the next section describes.
        t = _read(SKILL)
        self.assertIn("`count` (optional, default **4**)", t)
        self.assertIn("If a number is not given, use 4", t)
        self.assertIn("Clamp to 1..12", t)  # the range itself is unchanged
        self.assertIn("At the default `count=4`, `A=2`", t)
        self.assertIn("Default count is 4", t)
        self.assertIn("4 ducks on medium-tier models by default", _front_matter(t))
        # No OTHER default may be stated in any of the three canonical phrasings: the NUMBER is
        # matched by shape, so "default **6**" fails without a denylist entry of its own.
        for phrase, number in re.findall(r"(If a number is not given, use (\d+))", t):
            self.assertEqual(number, "4", "conflicting default stated: %r" % phrase)
        for phrase, number in re.findall(r"(Default count is (\d+))", t):
            self.assertEqual(number, "4", "conflicting default stated: %r" % phrase)
        for phrase, number in re.findall(r"(`count` \(optional, default \*\*(\d+)\*\*\))", t):
            self.assertEqual(number, "4", "conflicting default stated: %r" % phrase)
        self.assertNotIn("defaults to 8 ducks", t)

        # The worked prisms example IS the default panel: 4 ducks over the FIRST TWO aspects of the
        # priority-ordered aspect list, two ducks each. Grouped BY THE ASPECT CELL rather than by row
        # position, so re-presenting the same panel in deal order (1,2,1,2 instead of 1,1,2,2) is not
        # a required-check failure - the invariant is the coverage, not the row order.
        prisms = _md_table_rows(t, "| duck | model | family | aspect |")
        self.assertEqual(len(prisms), 4, "the worked prisms example must show the default panel")
        aspect_section = t.split("### Aspect list (prisms mode only)", 1)
        self.assertEqual(len(aspect_section), 2, "the priority-ordered aspect list is missing")
        # Bounded to THAT section: unbounded, the numbered lists in Steps 5 and 7 pad the match to 20
        # items and the length guard below stops guarding anything (deleting aspects 5-6 stayed green).
        aspect_body = aspect_section[1].split("\n### ", 1)[0]
        aspects = re.findall(r"^\d+\. (.+)$", aspect_body, re.M)
        self.assertEqual(len(aspects), 6, "expected the 6 priority-ordered aspects, got %d"
                         % len(aspects))
        covered = {}
        for row in prisms:
            covered.setdefault(row[3], []).append(row[0])
        self.assertEqual(len(covered), 2, "the default panel must cover exactly 2 aspects, got %r"
                         % sorted(covered))
        for i, (reviewed, ducks) in enumerate(sorted(
                covered.items(), key=lambda kv: min(kv[1]))):
            self.assertEqual(len(ducks), 2, "aspect %r must have exactly 2 ducks" % reviewed)
            self.assertTrue(
                aspects[i].startswith(reviewed),
                "the panel reviews %r, which is not aspect %d (%r) of the priority list"
                % (reviewed, i + 1, aspects[i]))

        # The narrower coverage is stated as a trade, with both ways to widen it - drop either and an
        # agent silently loses the aspects the old default covered. Pinned by shape, not as exact
        # sentences, so an editorial rewording is not a required-check failure.
        self.assertRegex(t, r"`guidance`[^.\n]*aspect 1")
        self.assertRegex(t, r"or (raise|increase) (the )?`count`")
        # An explicit user count is authoritative - the widening advice must never license quietly
        # spending more ducks than the user asked for.
        self.assertRegex(t, r"explicit user count is authoritative")

    def test_effort_selects_one_of_exactly_two_model_tiers(self):
        # MDUCK-EFFORT-14: `effort` picks WHICH TIER of models the roster is drawn from (and the
        # per-call reasoning-effort floor), so the routine case is cheap by default and the strongest
        # panel is one word away. Exactly two levels, defaulting to MEDIUM (the token-light one), and
        # neither tier may buy its cheapness by collapsing the cross-family independence the panel
        # exists for.
        t = _read(SKILL)
        self.assertIn("`effort` (optional, default **medium**)", t)
        # The declared default is read from the `effort` bullet BLOCK, with flexible trailing
        # punctuation, and no OTHER value may be declared for it there - a file-wide ordered tuple
        # reddened on an unrelated input being reworded or reordered, which is a false positive on a
        # required gate.
        effort_block = t.split("- `effort` (optional", 1)
        self.assertEqual(len(effort_block), 2, "the effort input is missing")
        effort_block = re.split(r"^- `", effort_block[1], maxsplit=1, flags=re.M)[0]
        declared = re.findall(r"If not stated, use ([a-z]+)\b", effort_block)
        self.assertEqual(declared, ["medium"],
                         "the effort input must declare exactly one default, got %r" % declared)
        # EXACTLY two levels, read from the same block: scanned file-wide this was coupled to the
        # unrelated `mode` bullets' punctuation, and it missed a third level written without a colon.
        levels = re.findall(r"^  - \*\*`([a-z]+)`\*\*", effort_block, re.M)
        self.assertEqual(sorted(levels), ["high", "medium"],
                         "the effort input must offer exactly two levels, got %r" % levels)
        self.assertEqual(levels[0], "medium", "the default level is listed first, got %r" % levels)
        # ...and exactly two roster tables, so an added tier cannot ship without its own spec row.
        # The header pattern is deliberately loose about the middle column: a third table headed
        # "| # | low-tier model | family |" must be COUNTED, not slip past on wording.
        headers = re.findall(r"^\| # \|[^|]*\| family \|$", t, re.M)
        self.assertEqual(len(headers), 2, "expected exactly two roster tables, got %d" % len(headers))
        # The tier sets a per-call reasoning-effort floor on hosts that expose one...
        self.assertIn("reasoning-effort floor", t)
        self.assertIn("`high` tier -> `high` or better", t)
        self.assertIn("`medium` tier -> `medium`", t)
        # ...the run's tier and the effort actually applied survive a restart in the tracking store,
        # and Step 7 discloses both, so a reader always knows how deep a read produced the verdict.
        self.assertIn("effort_tier", t)
        self.assertIn("effort_applied", t)
        self.assertIn("host-default", t)
        self.assertRegex(t, r"Read the tier and the applied effort from the tracking store")
        # A run does not mix tiers, and cheapness is never bought from the family count. Pinned by
        # shape so a reworded but equivalent rule is not a required-check failure.
        self.assertRegex(t, r"[Dd]raw every duck in a run from the SAME tier")
        self.assertRegex(t, r"never pair two ducks of the same family on one aspect")
        self.assertRegex(t, r"[Nn]ever reach into the other tier")
        self.assertRegex(t, r"beyond the tier's roster")   # the widen carve-out
        self.assertRegex(t, r"IN THE SAME TIER")           # the rotation limit
        # The invocation-to-tier parsing contract: representative triggers for BOTH tiers must be
        # documented and land on the right side, or an agent has no way to honour "keep it cheap".
        parse = re.search(r"Parse from the invocation: (.+?) If not stated", effort_block, re.S)
        self.assertTrue(parse, "the effort input documents no invocation parsing")
        high_side, _, medium_side = parse.group(1).partition("-> high;")
        self.assertIn("-> medium", medium_side)
        for trigger in ("high effort", "flagship", "thorough"):
            self.assertIn(trigger, high_side, "%r must map to the high tier" % trigger)
        for trigger in ("medium effort", "cheap", "save tokens"):
            self.assertIn(trigger, medium_side, "%r must map to the medium tier" % trigger)

        # Both tiers are real, distinct rosters that obey the same diversity-first rule.
        tiers = {
            "high": _md_table_rows(t, "| # | example model | family |"),
            "medium": _md_table_rows(t, "| # | example medium-tier model | family |"),
        }
        for tier, rows in tiers.items():
            self.assertGreaterEqual(len(rows), 4, "%s-tier roster not found or too short" % tier)
            families = [_base_family(r[2]) for r in rows]
            distinct = len(set(families))
            self.assertGreaterEqual(
                distinct, 4,
                "the %s-tier roster must span at least 4 provider families, got %r"
                % (tier, sorted(set(families))))
            self.assertEqual(
                len(set(families[:distinct])), distinct,
                "the %s-tier roster must front-load one model per family, got %r"
                % (tier, families[:distinct]))
        # `effort: medium` must actually be cheaper: the medium roster may share a high tier's TAIL
        # (a strong mid model is legitimately both), but it may never replay the flagships the high
        # tier front-loads - a "medium" panel made of flagships is the default panel with a new name.
        # Model ids are unwrapped from their backticks so a reformatted cell cannot dodge the check.
        def model_ids(rows):
            return {r[1].strip().strip("`").strip() for r in rows}

        high = tiers["high"]
        high_families = [_base_family(r[2]) for r in high]
        flagships = model_ids(high[:len(set(high_families))])
        replayed = flagships & model_ids(tiers["medium"])
        self.assertFalse(replayed, "the medium tier replays high-tier flagships: %r"
                         % sorted(replayed))

    def test_pairing_is_deterministic_and_degradation_is_never_silent(self):
        # MDUCK-PAIR-15: two behaviors an agent must not have to invent. (a) Prisms assignment is a
        # DETERMINISTIC round-robin deal of the tier's first 2A rows across the A aspects, with a
        # repair swap for any same-family pair, so every count has one executable answer instead of a
        # worked example to extrapolate from - and so the tier's strongest reviewers are not stacked
        # on aspect 1, leaving aspect 2 to its weakest. (b) There is ONE rule for what happens when
        # reviewers cannot be independent: mark the run `diversity_degraded` BEFORE launch and say so
        # in the report. Three sections used to state their own fallback, so a same-family pair could
        # be presented as an ordinary one.
        t = _read(SKILL)
        # (a) the deal, its formula, and the repair step.
        self.assertRegex(t, r"round-robin")
        self.assertRegex(t, r"row `j` goes to aspect `\(\(j - 1\) mod A\) \+ 1`")
        self.assertRegex(t, r"first `2A` rows")
        self.assertRegex(t, r"[Tt]hen REPAIR")
        self.assertRegex(t, r"swap one of them with a duck from another aspect")
        # (b) the single degraded rule: declared once as THE rule, applied before launch, reported,
        # and deferred to (not restated with different terms) by the effort input and the assignment
        # step. `assertRegex` on short phrases so a rewording of the surrounding prose is not a
        # required-check failure.
        self.assertRegex(t, r"this is the SINGLE rule")
        self.assertRegex(t, r"mark the panel `diversity_degraded` BEFORE launching")
        # Each place that could state its own fallback must instead reference the degraded state, so
        # the rule is one policy rather than three. Checked per REGION, not as a global count, so
        # rewording a sentence does not red a required check.
        for region, marker in (("Model diversity across hosts", "**Model diversity across hosts.**"),
                               ("the effort input", "- `effort` (optional"),
                               ("prisms assignment", "- **prisms mode**:"),
                               ("Step 7", "## Step 7. Present the summary")):
            body = t.split(marker, 1)
            self.assertEqual(len(body), 2, "%s section is missing" % region)
            self.assertIn("diversity_degraded", body[1].split("\n## ", 1)[0],
                          "%s does not defer to the degraded-run rule" % region)
        self.assertRegex(t, r"never present a same-family pair as an ordinary one")
        # It reaches the reader: the Step 7 panel line reports it.
        summary = t.split("## Step 7. Present the summary", 1)
        self.assertEqual(len(summary), 2, "Step 7 is missing")
        self.assertRegex(summary[1], r"`diversity_degraded`")


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
