"""Shipped-doc checks for the portability-mode diagrams (CMH-MODE-08).

The Output modes reference must carry two mermaid diagrams (one Portable, one NonPortable)
showing what is bundled in the file versus fetched from where, and SKILL.md must point at them.
"""
import os
import re
import unittest
import json

import _paths

EXPORTS_MD = os.path.join(_paths.PKG, "references", "exports.md")
SKILL_MD = os.path.join(_paths.PKG, "SKILL.md")
TUTORIAL_MD = os.path.join(_paths.DOCS, "TUTORIAL.md")
REFERENCES = os.path.join(_paths.PKG, "references")
FILE_INVENTORY_MD = os.path.join(REFERENCES, "file-inventory.md")


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class PortabilityDiagramsTests(unittest.TestCase):
    def test_exports_has_two_mode_mermaid_diagrams(self):
        text = _read(EXPORTS_MD)
        heading = "## What is bundled in the file vs fetched from where"
        self.assertIn(heading, text)
        section = text.split(heading, 1)[1].split("\n## ", 1)[0]
        fences = re.findall(r"```mermaid\b", section)
        self.assertGreaterEqual(len(fences), 2, "expected two mermaid diagrams in the section")
        # Portable inlines the layer CSS/JS; NonPortable loads the companions from dist/.
        self.assertIn("(inlined)", section)
        for companion in ("commentable-html.css", "commentable-html.js", "commentable-html.assets.js"):
            self.assertIn(companion, section)
        # Both modes keep content and comments inline and fetch optional libraries from a CDN.
        self.assertIn("EMBEDDED COMMENTS", section)
        self.assertIn("CDN", section)

    def test_skill_output_modes_references_the_diagrams(self):
        text = _read(SKILL_MD)
        self.assertIn(
            "references/exports.md#what-is-bundled-in-the-file-vs-fetched-from-where",
            text)


PLUGIN_README = os.path.normpath(os.path.join(_paths.PKG_SHIPPED, "..", "..", "README.md"))
BLOG_URL = "https://claude.com/blog/using-claude-code-the-unreasonable-effectiveness-of-html"

DIST_README = os.path.join(_paths.PKG, "dist", "README.md")
MANIFEST_JSON = os.path.join(_paths.PKG, "dist", "manifest.json")


class VisibleVersionDocsTests(unittest.TestCase):
    """CMH-DOC-10: the shipped SKILL.md and dist/README.md display the current version in a
    clear, human-readable place, matching the shipped runtime version in dist/manifest.json."""

    def _shipped_version(self):
        with open(MANIFEST_JSON, encoding="utf-8") as fh:
            return json.load(fh)["version"]

    def test_skill_shows_current_version(self):
        self.assertIn("**Version:** `%s`" % self._shipped_version(), _read(SKILL_MD))

    def test_dist_readme_shows_current_version(self):
        self.assertIn("**Version:** `%s`" % self._shipped_version(), _read(DIST_README))


class DualAgentDocsTests(unittest.TestCase):
    """CMH-DOC-12: the shipped SKILL.md states the plugin installs into both Claude Code and the
    GitHub Copilot CLI and is invokable from each agent's CLI and Desktop app, so the dual-agent
    support is visible in the discovery doc the agent reads."""

    def test_skill_states_dual_agent_install_and_cli_and_desktop(self):
        text = _read(SKILL_MD)
        self.assertIn("Claude Code", text)
        self.assertIn("GitHub Copilot CLI", text)
        self.assertIn("claude plugin install commentable-html@urikan-ai-marketplace", text)
        self.assertIn("copilot plugin install commentable-html@urikan-ai-marketplace", text)
        self.assertIn("CLI and Desktop app", text)

    def test_skill_frontmatter_description_avoids_reserved_words(self):
        # The dual-agent note lives in the BODY; CMH-DOC-06 still forbids the reserved words in the
        # discovery front-matter description, so keep them out of the YAML scalar.
        text = _read(SKILL_MD)
        front = text.split("---", 2)[1]
        self.assertNotIn("claude", front.lower())
        self.assertNotIn("anthropic", front.lower())


class PluginReadmeDualAgentTests(unittest.TestCase):
    """CMH-DOC-13: the shipped plugin README.md states the plugin installs into both Claude Code and
    the GitHub Copilot CLI and shows each agent's install commands, so the shipped README does not lag
    the SKILL.md, the marketplace manifests, and the site in presenting the dual-agent support."""

    def test_plugin_readme_states_dual_agent_install(self):
        text = _read(PLUGIN_README)
        self.assertIn("Claude Code", text)
        self.assertIn("GitHub Copilot CLI", text)
        self.assertIn("claude plugin install commentable-html@urikan-ai-marketplace", text)
        self.assertIn("copilot plugin install commentable-html@urikan-ai-marketplace", text)


class ShippedLicenseTests(unittest.TestCase):
    """CMH-DOC-14: the shipped skill carries the MIT LICENSE at its root, so every copy that ships
    (the Copilot/Claude `plugin install` source subtree and the Claude Desktop skill ZIP) redistributes
    the code with its required license notice."""

    def test_skill_ships_the_mit_license(self):
        license_path = os.path.join(_paths.PKG, "LICENSE")
        self.assertTrue(os.path.isfile(license_path),
                        "the shipped skill must carry a LICENSE at its root: %s" % license_path)
        text = _read(license_path)
        self.assertIn("MIT License", text)
        self.assertIn("Uri Kanonov", text)

    def test_shipped_license_matches_the_repo_license(self):
        repo_license = os.path.normpath(os.path.join(_paths.PKG, "..", "..", "..", "..", "LICENSE"))
        skill_license = os.path.join(_paths.PKG, "LICENSE")
        self.assertTrue(os.path.isfile(repo_license), repo_license)
        self.assertEqual(_read(skill_license).strip(), _read(repo_license).strip(),
                         "the shipped skill LICENSE must match the repository root LICENSE")


class PluginReadmeToolPathDocsTests(unittest.TestCase):
    """CMH-DOC-15: every tool path in the shipped plugin README.md resolves to a real shipped file."""

    TOOL_PATH_RE = re.compile(r"(?:skills[\\/]+commentable-html[\\/]+)?tools[\\/]+[A-Za-z0-9_.\\/-]+\.py")

    def test_plugin_readme_tool_paths_resolve(self):
        text = _read(PLUGIN_README)
        paths = sorted({match.group(0) for match in self.TOOL_PATH_RE.finditer(text)})
        self.assertGreater(len(paths), 0)
        for path in paths:
            normalized = path.replace("\\", "/")
            tools_tail = normalized.split("tools/", 1)[1]
            shipped_path = os.path.join(_paths.TOOLS, *tools_tail.split("/"))
            self.assertTrue(os.path.isfile(shipped_path), "%s does not resolve to %s" % (path, shipped_path))


class MotivationDocsTests(unittest.TestCase):
    """CMH-DOC-01: the shipped README and SKILL.md carry the medium-comparison motivation
    and cite the "unreasonable effectiveness of HTML" blog post."""

    def test_readme_has_comparison_table_and_blog_reference(self):
        text = _read(PLUGIN_README)
        self.assertIn("Why not just plan in chat, Markdown, or plain HTML?", text)
        self.assertIn("| **Commentable HTML** |", text)
        for medium in ("Chat / terminal", "Markdown file", "Plain HTML"):
            self.assertIn(medium, text)
        self.assertIn(BLOG_URL, text)

    def test_skill_cites_the_blog_reference(self):
        self.assertIn(BLOG_URL, _read(SKILL_MD))


class PitchPersistenceAndBatchDocsTests(unittest.TestCase):
    """CMH-DOC-11: the shipped README pitch surfaces two value props of existing behavior - that
    comments persist in localStorage and survive a browser restart or reboot while iterating, and
    that Copy all returns every comment at once so the agent makes one coordinated, coherent edit
    instead of a fragile one-at-a-time pass."""

    def test_readme_states_comments_survive_a_restart(self):
        text = _read(PLUGIN_README)
        self.assertIn("survive a browser restart", text)
        self.assertIn("localStorage", text)

    def test_readme_states_copy_all_returns_every_comment_at_once(self):
        text = _read(PLUGIN_README)
        self.assertIn("every comment at once", text)
        self.assertIn("coordinated", text)


class NewFeatureDocsTests(unittest.TestCase):
    """CMH-DOC-02: the shipped guidance covers widget drag opt-in, Offline state, and Export Offline."""

    def test_skill_documents_widget_drag_and_offline_modes(self):
        text = _read(SKILL_MD)
        for snippet in (
            "NonPortable is for fast iteration",
            "Portable is for peer review",
            "Offline is for zero-network handoff",
            "data-cm-draggable",
            "Only direct `data-cm-part` children of a slot are movable",
            "Export Offline",
            "after mermaid diagrams and charts have rendered",
        ):
            self.assertIn(snippet, text)
        self.assertEqual(text.count("data-cm-draggable"), 1)

    def test_tutorial_documents_offline_export(self):
        text = _read(TUTORIAL_MD)
        for snippet in (
            "Offline",
            "Export Offline",
            "zero-network handoff",
            "after Mermaid diagrams and charts have rendered",
        ):
            self.assertIn(snippet, text)
        # The doc-type badge documents its three exact states with their color cues; assert the
        # precise wording so a regression that drops a state or renames it turns this test red.
        for badge_phrase in (
            "reads **Portable** (green)",
            "reads **Offline** when",
            "reads **Not portable** (orange)",
            "reopens with the **Offline** badge",
        ):
            self.assertIn(badge_phrase, text)


class SkillTrimDocsTests(unittest.TestCase):
    """CMH-DOC-03: SKILL.md stays lean while routing moved detail to real references."""

    def test_skill_is_lean_and_keeps_generation_critical_contracts(self):
        text = _read(SKILL_MD)
        # Leanness guard. Topic-bucketed tool paths (tools/<topic>/<tool>.py) add a per-invocation
        # path segment across the ~44 tool references, so the cap allows for that qualification while
        # still holding SKILL.md well under the skill-loader budget.
        self.assertLess(os.path.getsize(SKILL_MD), 38 * 1024)
        for snippet in (
            "TOOL ROUTING contract",
            "tools/authoring/new_document.py",
            "tools/authoring/retrofit.py",
            "tools/authoring/upgrade.py",
            "tools/authoring/finalize.py <file> [--toc --fix-skip --inline-images --images-base DIR] --strict",
            "python tools/validate/validate.py --strict <file.html>",
            "python tools/authoring/mark_handled.py <file.html> --from-bundle -",
            "Trust boundary (MUST)",
            "Portable != offline",
            "private class prefix",
            "reserved `cmh-*`",
        ):
            self.assertIn(snippet, text)

    def test_moved_detail_lives_in_references_that_skill_links(self):
        skill = _read(SKILL_MD)
        checks = {
            "document-layout.md": (
                "runtime toolbar",
                "Clear Comments",
                "Per-document configuration example",
                "oldest-first and newest-first",
                "Clicking the active arrow again",
                "records a tombstone",
                "remains **Not portable** until **Export as Portable**",
            ),
            "interaction-model.md": (
                "staggers by 28px",
                "composer popover",
                "Handled comments stay handled",
            ),
            "exports.md": (
                "Producing a NonPortable document",
                "Guardrails that make NonPortable safe",
                "Network requirements and CDN caveats",
            ),
            "retrofitting.md": (
                "tools/authoring/retrofit.py",
                "Manual paste fallback",
                "--root-selector",
            ),
            "code-blocks.md": (
                "tools/blocks/highlight_document.py",
                "runtime tokenizes it on load",
            ),
        }
        for name, snippets in checks.items():
            with self.subTest(reference=name):
                self.assertIn("references/" + name, skill)
                text = _read(os.path.join(REFERENCES, name))
                for snippet in snippets:
                    self.assertIn(snippet, text)


class ReferenceReachabilityDocsTests(unittest.TestCase):
    """CMH-DOC-04: every reference file is reachable from the skill or inventory."""

    def test_every_reference_is_linked_from_skill_or_inventory(self):
        skill = _read(SKILL_MD)
        inventory = _read(FILE_INVENTORY_MD)
        missing = []
        for name in sorted(os.listdir(REFERENCES)):
            if not name.endswith(".md"):
                continue
            reference = "references/" + name
            if reference not in skill and reference not in inventory:
                missing.append(reference)
        self.assertEqual([], missing)


LONG_REFERENCE_LINE_THRESHOLD = 100
PLUGIN_JSON = os.path.normpath(os.path.join(_paths.PKG_SHIPPED, "..", "..", "plugin.json"))
MARKETPLACE_JSON = os.path.normpath(
    os.path.join(_paths.DEV, "..", "..", "..", ".github", "plugin", "marketplace.json"))


def _lines_outside_fences(text):
    """Yield lines that are NOT inside a fenced code block (``` or ~~~)."""
    fenced = False
    for line in text.splitlines():
        if re.match(r"^\s*(```|~~~)", line):
            fenced = not fenced
            continue
        if not fenced:
            yield line


def _heading_to_slug(heading):
    """Mirror scripts/validate_markdown.py:heading_to_slug so TOC anchors match the validator.

    Kept as a local copy on purpose: the plugin-tests Python job installs no extra deps and
    does not put scripts/ on the path. A change to the validator's slug rule that broke a TOC
    anchor would still be caught by the markdown validator's own broken-anchor check.
    """
    slug = re.sub(r"<[^>]+>", "", heading)
    slug = re.sub(r"[`*_~\[\]()]", "", slug)
    slug = slug.strip().lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"\s", "-", slug)
    return slug.strip("-")


def _section_headings(text):
    """Level 2-3 headings outside fenced code blocks, as (level, title) pairs."""
    out = []
    for line in _lines_outside_fences(text):
        m = re.match(r"^(#{2,3})\s+(.+?)\s*$", line)
        if m:
            out.append((len(m.group(1)), m.group(2)))
    return out


def _contents_block(text):
    """The lines under a '## Contents' heading up to the next level-2 heading (fence-aware)."""
    block = []
    inside = False
    for line in _lines_outside_fences(text):
        if re.match(r"^##\s+Contents\s*$", line):
            inside = True
            continue
        if inside and re.match(r"^##(?!#)\s+", line):
            break
        if inside:
            block.append(line)
    return "\n".join(block)


def _frontmatter_description_raw(text):
    """Return the raw description value from the SKILL.md YAML front matter (single-line scalar)."""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    front = m.group(1) if m else ""
    dm = re.search(r"^description:[ \t]*(.*)$", front, re.M)
    return dm.group(1).strip() if dm else ""


def _unquote(value):
    """Strip a single pair of matching surrounding quotes so the length matches the real string."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


class ReferenceTocDocsTests(unittest.TestCase):
    """CMH-DOC-05: every reference longer than 100 lines opens with a '## Contents' table of
    contents whose anchor links cover all of that file's own section headings and each link
    resolves to a real heading, so a partial read still sees the file's full scope."""

    def test_long_references_have_a_validated_contents_toc(self):
        found_long = False
        for name in sorted(os.listdir(REFERENCES)):
            if not name.endswith(".md"):
                continue
            text = _read(os.path.join(REFERENCES, name))
            if len(text.splitlines()) <= LONG_REFERENCE_LINE_THRESHOLD:
                continue
            found_long = True
            with self.subTest(reference=name):
                headings = _section_headings(text)
                self.assertTrue(headings, f"{name}: no level 2-3 headings found")
                # The TOC must be the FIRST level-2 section, so a partial read sees it.
                first_l2 = next((title for lvl, title in headings if lvl == 2), None)
                self.assertEqual(
                    "Contents", first_l2,
                    f"{name}: '## Contents' must be the first level-2 section (found {first_l2!r})")
                # Exactly one Contents heading, so a second one cannot slip past the filter below.
                contents_headings = [t for _, t in headings if _heading_to_slug(t) == "contents"]
                self.assertEqual(
                    1, len(contents_headings),
                    f"{name}: expected exactly one Contents heading, found {len(contents_headings)}")
                heading_slugs = [
                    _heading_to_slug(title) for _, title in headings
                    if _heading_to_slug(title) != "contents"
                ]
                # GitHub disambiguates duplicate slugs with -1/-2 suffixes; the TOC test does
                # not model that, so fail fast if a file ever introduces a duplicate slug.
                self.assertEqual(
                    len(heading_slugs), len(set(heading_slugs)),
                    f"{name}: duplicate heading slugs would need -N anchor suffixes: "
                    f"{sorted(s for s in heading_slugs if heading_slugs.count(s) > 1)}")
                toc_targets = re.findall(r"\]\(#([\w-]+)\)", _contents_block(text))
                self.assertTrue(
                    toc_targets, f"{name}: the '## Contents' section has no anchor links")
                for slug in heading_slugs:
                    self.assertIn(
                        slug, toc_targets,
                        f"{name}: section '#{slug}' is missing from the Contents TOC")
                for target in toc_targets:
                    self.assertIn(
                        target, heading_slugs,
                        f"{name}: Contents TOC link '#{target}' resolves to no heading")
        self.assertTrue(found_long, "expected at least one reference over 100 lines")


class FrontmatterDescriptionDocsTests(unittest.TestCase):
    """CMH-DOC-06: the SKILL.md front-matter description is the discovery string the agent
    reads, so it states both WHAT the skill does and WHEN to use it, is a plain single-line
    scalar within the marketplace validator's 800-char cap, uses no XML tags, and avoids the
    reserved skill-name words."""

    def test_frontmatter_description_states_what_and_when(self):
        skill = _read(SKILL_MD)
        fm = re.match(r"^---\s*\n(.*?)\n---\s*\n", skill, re.S)
        front = fm.group(1) if fm else ""
        # The description must be a single physical line: reject a YAML continuation (an
        # indented follow-on line after `description:`) so the checks below measure it all.
        self.assertIsNone(
            re.search(r"(?m)^description:[^\n]*\n[ \t]+\S", front),
            "front-matter description must be a single line (no YAML continuation)")
        raw = _frontmatter_description_raw(skill)
        self.assertTrue(raw, "SKILL.md front matter has no description")
        # Reject YAML flow collections and block scalars so the assertions below measure the
        # real string, not a "{...}" mapping or a ">"/"|" placeholder.
        self.assertNotIn(
            raw[:1], ("{", "[", ">", "|"),
            "front-matter description must be a plain single-line scalar")
        desc = _unquote(raw)
        low = desc.lower()
        # Match the marketplace validator's contract exactly: it fails only when len > 800.
        self.assertLessEqual(
            len(desc), 800,
            "front-matter description must be 800 chars or fewer (marketplace validator cap)")
        self.assertIsNone(
            re.search(r"<[A-Za-z/][^>]*>", desc),
            "front-matter description must not contain XML tags")
        self.assertNotIn("anthropic", low, "description must not use the reserved word 'anthropic'")
        self.assertNotIn("claude", low, "description must not use the reserved word 'claude'")
        self.assertIn("use when", low, "description must state WHEN to use the skill ('Use when ...')")
        self.assertIn("html", low, "description must name the HTML artifact it operates on")
        self.assertTrue(
            "comment" in low or "review" in low,
            "description must name the comment/review capability")

    def test_description_carries_the_cmh_shorthand_trigger(self):
        # CMH-DOC-06: the discovery description ends with an explicit 'cmh' shorthand clause so
        # the skill auto-triggers when the user types the shorthand.
        desc = _unquote(_frontmatter_description_raw(_read(SKILL_MD))).lower()
        self.assertRegex(
            desc, r"\bcmh\b",
            "front-matter discovery description must carry the 'cmh' shorthand trigger")


class DirectReferenceLinkDocsTests(unittest.TestCase):
    """CMH-DOC-07: every shipped reference is linked DIRECTLY from SKILL.md as a real Markdown
    link (one level deep), so progressive disclosure never hides a reference behind another
    reference file or behind a bare prose/code mention."""

    def test_every_reference_is_linked_directly_from_skill(self):
        body = "\n".join(_lines_outside_fences(_read(SKILL_MD)))
        # Ignore inline-code spans and HTML comments so a `references/x.md` literal or a
        # commented-out link is not mistaken for a real, rendered link.
        body = re.sub(r"`[^`]*`", "", body)
        body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
        missing = []
        for name in sorted(os.listdir(REFERENCES)):
            if not name.endswith(".md"):
                continue
            # A real, non-image Markdown link: [text](references/name[#anchor]). The negative
            # lookbehind on '!' rejects an image link; a bare mention has no [text](...) form.
            link = (r"(?<!!)\[[^\]]*\]\(\s*references/" + re.escape(name)
                    + r"(?:#[^)]*)?\s*\)")
            if not re.search(link, body):
                missing.append("references/" + name)
        self.assertEqual(
            [], missing,
            f"references not linked directly from SKILL.md as a Markdown link (one level "
            f"deep): {missing}")


class ChartReferenceSplitDocsTests(unittest.TestCase):
    """CMH-DOC-16: the Chart.js guidance stays split into focused references, with a
    thin compatibility router and direct SKILL.md links to each focused file."""

    def test_cmh_doc_16_chart_references_are_split_and_routed(self):
        skill = _read(SKILL_MD)
        for name in ("charts.md", "charts-embedding.md", "charts-recipes.md"):
            with self.subTest(reference=name):
                self.assertIn("references/" + name, skill)
                self.assertTrue(os.path.isfile(os.path.join(REFERENCES, name)))

        index = _read(os.path.join(REFERENCES, "charts.md"))
        self.assertLessEqual(
            len(index.splitlines()), 40,
            "charts.md should stay a thin router so agents do not load both chart guides")
        self.assertIn("charts-embedding.md", index)
        self.assertIn("charts-recipes.md", index)

    def test_cmh_doc_16_embedding_and_recipe_guides_have_distinct_scopes(self):
        embedding = _read(os.path.join(REFERENCES, "charts-embedding.md"))
        recipes = _read(os.path.join(REFERENCES, "charts-recipes.md"))

        for heading in (
            "## Dependency and portability",
            "## Four rules for coexisting with the commenting layer",
            "## Minimal copy-paste recipe (light theme)",
            "## The tooltip options that matter",
        ):
            self.assertIn(heading, embedding)
        self.assertNotIn("## Chart-type recipes", embedding)
        self.assertNotIn("## Data hygiene", embedding)

        for heading in (
            "## Chart-type recipes (from the sample report)",
            "## Data hygiene",
            "## Dark theme",
        ):
            self.assertIn(heading, recipes)
        self.assertNotIn("## Four rules for coexisting with the commenting layer", recipes)


class DescriptionConsistencyDocsTests(unittest.TestCase):
    """CMH-DOC-08: the SKILL.md discovery description and the plugin.json marketplace
    description are intentionally different surfaces (agent trigger vs human blurb), but they
    must share a small core vocabulary (whole words) so they cannot silently drift into
    telling different stories."""

    def test_skill_and_plugin_descriptions_share_core_vocabulary(self):
        import json

        skill_desc = _unquote(_frontmatter_description_raw(_read(SKILL_MD))).lower()
        with open(PLUGIN_JSON, encoding="utf-8") as fh:
            plugin_desc = json.load(fh).get("description", "").lower()
        shared = {
            "html": r"\bhtml\b",
            "comment": r"\bcomments?\b|\bcommentable\b",
            "review": r"\breview(?:s|er|ers|able|ing)?\b",
            "portable": r"\bportable\b",
        }
        for label, desc in (("SKILL.md", skill_desc), ("plugin.json", plugin_desc)):
            with self.subTest(surface=label):
                self.assertTrue(desc, f"{label} has no description")
                for word, pattern in shared.items():
                    self.assertRegex(
                        desc, pattern,
                        f"{label} description must mention '{word}' (shared vocabulary)")


class CmhKeywordDocsTests(unittest.TestCase):
    """CMH-DOC-09: the `cmh` shorthand is a declared keyword in BOTH plugin.json and the
    commentable-html marketplace entry, so marketplace search and the site keyword chips match
    the shorthand."""

    def test_cmh_is_a_keyword_in_plugin_and_marketplace(self):
        import json

        with open(PLUGIN_JSON, encoding="utf-8") as fh:
            plugin_keywords = json.load(fh).get("keywords", [])
        self.assertIn(
            "cmh", plugin_keywords, "plugin.json keywords must include the 'cmh' shorthand")
        with open(MARKETPLACE_JSON, encoding="utf-8") as fh:
            manifest = json.load(fh)
        entry = next(p for p in manifest["plugins"] if p["name"] == "commentable-html")
        self.assertIn(
            "cmh", entry.get("keywords", []),
            "the commentable-html marketplace entry keywords must include the 'cmh' shorthand")


class CapabilitiesOverviewDocsTests(unittest.TestCase):
    """CMH-DOC-17: SKILL.md opens with a single upfront capabilities list that names the tested
    tool/contract for every capability (so no capability - notes fields especially - is missed and
    the agent does not invent a novel mechanism), plus an upfront MUST-validate-before-handoff
    directive. Both sit ABOVE the detailed Steps so a quick read cannot miss them."""

    def _skill(self):
        return _read(SKILL_MD)

    def test_capabilities_section_is_upfront(self):
        text = self._skill()
        self.assertIn("## Capabilities", text, "SKILL.md must have an upfront Capabilities section")
        self.assertIn("## Steps", text)
        self.assertLess(
            text.index("## Capabilities"), text.index("## Steps"),
            "the Capabilities section must appear ABOVE the detailed Steps")

    def test_capabilities_directive_says_use_the_tested_tool(self):
        text = self._skill()
        cap = text.split("## Capabilities", 1)[1].split("\n## ", 1)[0]
        # The whole point: use the tested tool, never invent a bespoke mechanism.
        self.assertIn("USE THE NAMED TOOL", cap)
        self.assertIn("novel mechanism", cap)

    def test_capabilities_list_names_every_tested_tool(self):
        cap = self._skill().split("## Capabilities", 1)[1].split("\n## ", 1)[0]
        # The gap that triggered this: editable notes fields, plus the other interactive/content
        # and create/retrofit capabilities, must each name their tested tool/contract in the
        # upfront list so no capability is missed and no ad-hoc mechanism is invented.
        for tool in (
            "tools/authoring/new_document.py",
            "tools/authoring/retrofit.py",
            "tools/authoring/upgrade.py",
            "tools/authoring/mark_reviewed.py",
            "tools/authoring/generate_toc.py",
            "tools/authoring/wrap_sections.py",
            "tools/authoring/doc_stats.py",
            "tools/authoring/fix_skip.py",
            "tools/authoring/inline_images.py",
            "tools/notes/notes_scaffold.py",
            "tools/notes/notes_apply.py",
            "tools/checklist/checklist_scaffold.py",
            "tools/checklist/checklist_apply.py",
            "tools/blocks/highlight_code.py",
            "tools/kusto/kql_highlight.py",
            "tools/blocks/diff_block.py",
            "tools/blocks/chart_block.py",
            "tools/deck/deck_scaffold.py",
            "tools/deck/deck_theme.py",
        ):
            self.assertIn(tool, cap, f"upfront Capabilities list must name {tool}")
        # The `slides` flat kind must be named alongside the real-deck tool so they are not confused.
        self.assertIn("slides", cap)
        # And each capability's owning reference is linked from the same list.
        for ref in (
            "references/interaction-model.md",
            "references/code-blocks.md",
            "references/kusto-query-blocks.md",
            "references/code-review-diffs.md",
            "references/mermaid-diagrams.md",
            "references/charts-embedding.md",
            "references/charts-recipes.md",
            "references/images-commentable.md",
            "references/document-layout.md",
            "references/content-conventions.md",
            "references/checklist-contract.md",
            "references/notes-contract.md",
            "references/commentable-widgets.md",
            "references/exports.md",
        ):
            self.assertIn(ref, cap, f"upfront Capabilities list must link {ref}")

    def test_validate_before_handoff_is_stated_upfront(self):
        text = self._skill()
        self.assertIn("## Always validate before handoff (MUST)", text)
        self.assertLess(
            text.index("## Always validate before handoff (MUST)"), text.index("## Steps"),
            "the validate-before-handoff directive must appear ABOVE the detailed Steps")
        directive = text.split("## Always validate before handoff (MUST)", 1)[1].split("\n## ", 1)[0]
        self.assertIn("tools/authoring/finalize.py <file> --strict", directive)
        self.assertIn("tools/validate/validate.py --strict <file.html>", directive)
        # Decks need the deck-specific validator too, named in the same upfront directive.
        self.assertIn("tools/deck/deck_validate.py --strict", directive)


if __name__ == "__main__":
    unittest.main()
