"""CMH-DECK-SHOWCASE-04: the one-shot showcase-deck authoring prompt
(examples/prompt-showcase.md) has an INDEPENDENT dev-side source
(dev/examples/src/prompt-showcase.md) that build.py copies verbatim into the shipped file,
and it is content-complete enough to reproduce the shipped deck in one pass.

Reproducibility proxy (why AC#2 is checked this way): a true LLM regeneration of the deck from
the prompt cannot run inside a hermetic unit test - it would need a live model call, which the
suite forbids. So single-pass reproducibility is verified by a deterministic two-part proxy:
  1. content-completeness - the prompt enumerates the exact five-act slide outline, the
     Parchment-and-Amber theme tokens, the deck constraints, the single running community-garden
     example, and the cwd-safe validate/scaffold commands an agent must follow; and
  2. deck-validity - the deck the prompt describes (the shipped examples/deck-showcase.html)
     passes deck_validate.py --strict right now.
A sound, self-consistent recipe whose target artifact validates strictly is the strongest
reproducibility guarantee obtainable without a model in the loop.

The build-gate tests prove the shipped prompt is a pure artifact of its dev source: build.py
--check reproduces it byte-identically and flags a hand-edit, mirroring the report/deck example
self-source contract in tests/test_examples.py and tests/test_deck_example.py.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402  shared pkg/dev split path constants
SKILL = _paths.PKG
PROMPT = os.path.join(SKILL, "examples", "prompt-showcase.md")
PROMPT_SRC = os.path.join(_paths.DEV, "examples", "src", "prompt-showcase.md")
DECK = os.path.join(SKILL, "examples", "deck-showcase.html")
DECK_VALIDATE = os.path.join(SKILL, "tools", "deck", "deck_validate.py")
BUILD_PY = os.path.join(_paths.DEV_TOOLS, "build.py")


def _read(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return fh.read()


class PromptSourceTests(unittest.TestCase):
    def test_prompt_and_source_exist(self):
        self.assertTrue(os.path.isfile(PROMPT), "shipped prompt is missing: " + PROMPT)
        self.assertTrue(os.path.isfile(PROMPT_SRC), "dev-side prompt source is missing: " + PROMPT_SRC)

    def test_shipped_prompt_is_byte_identical_to_its_source(self):
        # The shipped prompt is a verbatim build artifact of its independent dev source.
        self.assertEqual(_read(PROMPT), _read(PROMPT_SRC),
                         "shipped prompt drifted from dev/examples/src (run build.py)")


class PromptCompletenessTests(unittest.TestCase):
    def setUp(self):
        self.prompt = _read(PROMPT)

    def test_prompt_prescribes_the_five_act_slide_outline(self):
        for token in ["five-act narrative", "Slide outline",
                      "Act 1 -", "Act 2 -", "Act 3 -", "Act 4 -", "Act 5 -"]:
            self.assertIn(token, self.prompt, "prompt is missing outline token: " + token)

    def test_prompt_pins_the_parchment_and_amber_theme_tokens(self):
        # Parchment bg, raspberry accent, and indigo ink, pinned to a light theme; the amber
        # comment-highlight motif is the rgba form of #f59e0b (rgb 245, 158, 11), which is how
        # the prompt expresses it.
        for token in ["#f7f4ef", "#b11f4b", "#1b1f3b", "245, 158, 11", 'data-theme="light"']:
            self.assertIn(token, self.prompt, "prompt is missing theme token: " + token)

    def test_prompt_states_the_deck_constraints(self):
        for token in ["data-cmh-mode", "commentable-html-kind=slides", "no remote media",
                      "no remote fonts", "no external scripts", "reduced-motion",
                      "stable", "data-slide-id"]:
            self.assertIn(token, self.prompt, "prompt is missing deck constraint: " + token)

    def test_prompt_threads_one_running_community_garden_example(self):
        self.assertIn("One running example", self.prompt)
        self.assertIn("community-garden", self.prompt)

    def test_prompt_gives_cwd_safe_validate_and_scaffold_commands(self):
        # The authoring commands are repo-cwd-relative (run from the skill root), never an
        # absolute machine path, so an agent following the prompt from any checkout resolves them.
        self.assertIn("tools/deck/deck_validate.py", self.prompt)
        self.assertIn("tools/deck/deck_scaffold.py", self.prompt)
        self.assertIn("python tools/deck/deck_validate.py", self.prompt)
        self.assertNotIn(":\\", self.prompt)
        self.assertNotRegex(self.prompt, r"(?m)(?<![\w.])/(?:home|Users|root)/")


class DeckValidityTests(unittest.TestCase):
    def test_shipped_deck_passes_strict_deck_validate(self):
        # The verifiable proxy for single-pass reproduction: the artifact the prompt targets
        # validates strictly right now (unique stable slide ids, no remote egress, deck contract).
        r = subprocess.run([sys.executable, DECK_VALIDATE, "--strict", DECK],
                           capture_output=True, text=True, cwd=SKILL)
        self.assertEqual(r.returncode, 0,
                         "deck_validate --strict failed:\nstdout=" + r.stdout + "\nstderr=" + r.stderr)


class PromptBuildGateTests(unittest.TestCase):
    def _staged_tree(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        assets = os.path.join(d, "assets")
        out_dir = os.path.join(d, "skill")
        shutil.copytree(_paths.ASSETS, assets)
        shutil.copytree(_paths.DIST, os.path.join(out_dir, "dist"))
        shutil.copytree(_paths.EXAMPLES, os.path.join(out_dir, "examples"))
        return [sys.executable, BUILD_PY, "--assets-dir", assets, "--out-dir", out_dir], out_dir

    def test_build_check_reproduces_the_prompt_and_flags_a_hand_edit(self):
        # The shipped prompt is a pure artifact of dev/examples/src/prompt-showcase.md; --check
        # must reproduce it byte-identically and catch a hand-edit to the shipped copy.
        base, out_dir = self._staged_tree()
        self.assertEqual(subprocess.run(base + ["--check"], capture_output=True, text=True).returncode, 0,
                         "freshly copied tree should be in sync")
        shipped = os.path.join(out_dir, "examples", "prompt-showcase.md")
        with open(shipped, "a", encoding="utf-8", newline="") as fh:
            fh.write("\nPOISON-PROMPT-DRIFT\n")
        r = subprocess.run(base + ["--check"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("prompt-showcase.md", r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
