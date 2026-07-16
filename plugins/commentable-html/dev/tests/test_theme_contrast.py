#!/usr/bin/env python3
"""Tests for the flat-doc theme-contrast advisory (CMH-THEME-02): the validator evaluates
authored --cp-* overrides for WCAG readability in each theme environment separately, with
graduated severity, an unresolved advisory, and a --suggest nudge."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402

sys.path.insert(0, os.path.join(_paths.TOOLS, "validate"))
from cmhval import contrast  # noqa: E402
from checks import theme_contrast  # noqa: E402


def _doc(root_vars="", dark_vars=""):
    """A minimal document whose palette can be overridden per environment. Only the tokens
    under test need to be present; unresolved tokens are simply absent."""
    return (
        "<!doctype html><html><head><style>\n"
        ":root {\n" + root_vars + "\n}\n"
        'html[data-theme="dark"] {\n' + dark_vars + "\n}\n"
        "</style></head><body><main>x</main></body></html>"
    )


# A fully compliant light+dark palette (mirrors the shipped template defaults for the pairs
# under test) used as the clean baseline that every negative test perturbs.
_GOOD_LIGHT = (
    "--cp-bg: #f7f4ef; --cp-bg-elevated: #fcfbf8; --cp-text: #242424; "
    "--cp-link: #0078d4; --cp-accent: #b11f4b; --cp-accent-fg: #ffffff; "
    "--cp-border-strong: #919191;"
)
_GOOD_DARK = (
    "--cp-bg: #3d3b3a; --cp-bg-elevated: #343231; --cp-text: #dedede; "
    "--cp-link: #4da6ff; --cp-accent: #fd8ea1; --cp-accent-fg: #1a1a1a; "
    "--cp-border-strong: #5f5f5f;"
)


class ThemeEnvironmentTests(unittest.TestCase):
    def test_cmh_theme_02_environments_resolve_dark_overrides_separately(self):
        envs = contrast.theme_environments(_doc(_GOOD_LIGHT, _GOOD_DARK))
        self.assertIn("light", envs)
        self.assertIn("dark", envs)
        # The dark environment sees the dark override, the light one the :root value.
        self.assertEqual(envs["light"]["--cp-text"], "#242424")
        self.assertEqual(envs["dark"]["--cp-text"], "#dedede")

    def test_cmh_theme_02_nudge_reaches_target(self):
        # A near-miss link on the light background nudged to the 4.5 text target.
        suggestion = contrast.nudge_to_ratio("#3a86c9", "#f7f4ef", 4.5)
        self.assertIsNotNone(suggestion)
        self.assertGreaterEqual(contrast.contrast_ratio(suggestion, "#f7f4ef"), 4.5)

    def test_cmh_theme_02_nudge_returns_none_when_unreachable(self):
        # A mid-tone background cannot reach a very high target from black or white.
        self.assertIsNone(contrast.nudge_to_ratio("#808080", "#808080", 7.0))

    def test_cmh_theme_02_grouped_selector_applies_to_both_envs(self):
        envs = contrast.theme_environments(
            '<style>:root, html[data-theme="dark"] { --cp-probe: #123456; }</style>')
        self.assertEqual(envs["light"].get("--cp-probe"), "#123456")
        self.assertEqual(envs["dark"].get("--cp-probe"), "#123456")

    def test_cmh_theme_02_print_media_block_is_ignored(self):
        # The shipped @media print block redefines --cp-* via a grouped :root,[data-theme=dark]
        # selector; it must NOT be resolved as the screen palette.
        envs = contrast.theme_environments(
            '<style>:root { --cp-bg: #f7f4ef; } html[data-theme="dark"] { --cp-bg: #3d3b3a; }'
            '@media print { :root, html[data-theme="dark"] { --cp-bg: #ffffff; } }</style>')
        self.assertEqual(envs["light"].get("--cp-bg"), "#f7f4ef")
        self.assertEqual(envs["dark"].get("--cp-bg"), "#3d3b3a")

    def test_cmh_theme_02_screen_conditional_groups_are_traversed(self):
        # Screen @media and @supports groups are traversed so an override inside them is seen.
        envs = contrast.theme_environments(
            '<style>@media screen { :root { --cp-a: #111111; } }'
            '@supports (color: #fff) { html[data-theme="dark"] { --cp-b: #222222; } }</style>')
        self.assertEqual(envs["light"].get("--cp-a"), "#111111")
        self.assertEqual(envs["dark"].get("--cp-b"), "#222222")

    def test_cmh_theme_02_statement_at_rules_do_not_swallow_the_next_rule(self):
        envs = contrast.theme_environments(
            '<style>@charset "utf-8"; @import url(x.css); :root { --cp-a: #111111; }</style>')
        self.assertEqual(envs["light"].get("--cp-a"), "#111111")

    def test_cmh_theme_02_brace_in_declaration_value_does_not_drop_the_rule(self):
        envs = contrast.theme_environments(
            '<style>:root { --cp-a: #111111; --cp-note: "{x}"; }</style>')
        self.assertEqual(envs["light"].get("--cp-a"), "#111111")

    def test_cmh_theme_02_print_style_block_is_ignored(self):
        envs = contrast.theme_environments(
            '<style>:root { --cp-bg: #f7f4ef; }</style>'
            '<style media="print">:root { --cp-bg: #ffffff; }</style>')
        self.assertEqual(envs["light"].get("--cp-bg"), "#f7f4ef")

    def test_cmh_theme_02_brand_stamped_palette_is_deferred(self):
        # A <style data-cmh-brand> palette is validated by the --brand tooling (CMH-TOOL-19); the
        # flat-doc check does not double-flag it, so a bad brand palette is not turned into a hard
        # error here.
        doc = '<style data-cmh-brand="b.json">:root { --cp-bg: #777777; --cp-text: #777777; }</style>'
        self.assertEqual(contrast.theme_environments(doc), {})
        errors, warnings = theme_contrast.check_theme_contrast(doc)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_cmh_theme_02_not_screen_media_is_excluded(self):
        # `@media not screen` applies to print/speech, never screen; it must not overwrite the
        # screen palette (an alternate spelling of the print-masquerade class).
        envs = contrast.theme_environments(
            '<style>:root { --cp-bg: #f7f4ef; }'
            '@media not screen { :root { --cp-bg: #ffff00; } }</style>')
        self.assertEqual(envs["light"].get("--cp-bg"), "#f7f4ef")

    def test_cmh_theme_02_compact_at_rule_syntax_is_traversed(self):
        # Compact/minified at-rules with no space before the parenthesis are still recognized.
        envs = contrast.theme_environments(
            '<style>@media(min-width:600px){:root{--cp-a:#111111}}'
            '@supports(display:grid){:root{--cp-b:#222222}}</style>')
        self.assertEqual(envs["light"].get("--cp-a"), "#111111")
        self.assertEqual(envs["light"].get("--cp-b"), "#222222")

    def test_cmh_theme_02_deeply_nested_groups_do_not_crash(self):
        # Pathological nesting must degrade gracefully (depth cap), not raise RecursionError and
        # abort the whole validation run.
        css = "@media screen{" * 1200 + ":root{--cp-a:#111111}" + "}" * 1200
        self.assertEqual(contrast.theme_environments("<style>" + css + "</style>"), {})


class CheckThemeContrastTests(unittest.TestCase):
    def _run(self, root_vars, dark_vars=""):
        return theme_contrast.check_theme_contrast(_doc(root_vars, dark_vars or root_vars))

    def test_cmh_theme_02_compliant_palette_is_clean(self):
        errors, warnings = self._run(_GOOD_LIGHT, _GOOD_DARK)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_cmh_theme_02_bad_text_contrast_is_an_error(self):
        bad = _GOOD_LIGHT.replace("--cp-text: #242424;", "--cp-text: #b8b8b8;")
        errors, warnings = self._run(bad, _GOOD_DARK)
        self.assertTrue(any("--cp-text" in e and "light" in e for e in errors),
                        msg=f"expected a light-env text error, got {errors}")

    def test_cmh_theme_02_near_miss_is_a_warning_not_an_error(self):
        # #6f8fb0 link on #f7f4ef sits in the 3.0-4.49 band: readable-ish but below AA text.
        near = _GOOD_LIGHT.replace("--cp-link: #0078d4;", "--cp-link: #6f8fb0;")
        errors, warnings = self._run(near, _GOOD_DARK)
        self.assertEqual([e for e in errors if "--cp-link" in e], [])
        self.assertTrue(any("--cp-link" in w for w in warnings),
                        msg=f"expected a near-miss link warning, got {warnings}")
        self.assertTrue(all(w.startswith(theme_contrast.ADVISORY_PREFIX)
                            for w in warnings if "--cp-link" in w))

    def test_cmh_theme_02_dark_only_override_is_caught_in_dark_env_only(self):
        dark_bad = _GOOD_DARK.replace("--cp-text: #dedede;", "--cp-text: #555555;")
        errors, warnings = self._run(_GOOD_LIGHT, dark_bad)
        self.assertTrue(any("--cp-text" in e and "dark" in e for e in errors),
                        msg=f"expected a dark-env text error, got {errors}")
        self.assertEqual([e for e in errors if "light" in e], [])

    def test_cmh_theme_02_unresolved_chain_is_an_advisory(self):
        unresolved = _GOOD_LIGHT.replace("--cp-link: #0078d4;", "--cp-link: var(--missing);")
        errors, warnings = self._run(unresolved, _GOOD_DARK)
        self.assertEqual([e for e in errors if "--cp-link" in e], [])
        self.assertTrue(any("--cp-link" in w and "not evaluated" in w for w in warnings),
                        msg=f"expected an unresolved advisory, got {warnings}")

    def test_cmh_theme_02_print_block_does_not_mask_bad_screen_dark_override(self):
        # A bad SCREEN dark override must still be caught even though a compliant @media print
        # block (grouped :root,[data-theme=dark], dark-on-white) sits after the screen dark block.
        bad_dark = _GOOD_DARK.replace("--cp-text: #dedede;", "--cp-text: #444444;")
        html = (
            "<!doctype html><html><head><style>\n"
            ":root {\n" + _GOOD_LIGHT + "\n}\n"
            'html[data-theme="dark"] {\n' + bad_dark + "\n}\n"
            '@media print { :root, html[data-theme="dark"] {\n'
            "--cp-bg: #ffffff; --cp-text: #111827; --cp-link: #1d4ed8;\n} }\n"
            "</style></head><body><main>x</main></body></html>"
        )
        errors, _ = theme_contrast.check_theme_contrast(html)
        self.assertTrue(any("--cp-text" in e and "dark" in e for e in errors),
                        msg=f"screen dark override must survive the print block, got {errors}")

    def test_cmh_theme_02_partial_override_pairs_against_default(self):
        # A realistic partial override: the full palette is present (as in a real doc's shell) and
        # the author changes ONLY --cp-bg to a bad value; the un-overridden default text it pairs
        # with must still be evaluated against the new background.
        bad_bg = _GOOD_LIGHT.replace("--cp-bg: #f7f4ef;", "--cp-bg: #202020;")
        errors, _ = self._run(bad_bg, _GOOD_DARK)
        self.assertTrue(any("--cp-bg" in e and "light" in e for e in errors),
                        msg=f"a lone bad --cp-bg override must be caught against the text, got {errors}")

    def test_cmh_theme_02_undefined_tokens_are_not_fabricated(self):
        # Overriding ONLY --cp-accent (omitting its paired --cp-accent-fg) must NOT be paired
        # against a fabricated default accent-fg: with no defined accent-fg there is nothing to
        # evaluate, so the pair is skipped rather than judged against an invented color.
        errors, warnings = theme_contrast.check_theme_contrast(
            '<style>:root { --cp-accent: #eeeeee; }</style>')
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_cmh_theme_02_bad_override_in_screen_media_is_evaluated(self):
        doc = ("<style>:root {" + _GOOD_LIGHT + "}"
               'html[data-theme="dark"] {' + _GOOD_DARK + "}"
               "@media screen { :root { --cp-text: #b8b8b8; } }</style>")
        errors, _ = theme_contrast.check_theme_contrast(doc)
        self.assertTrue(any("--cp-text" in e and "light" in e for e in errors),
                        msg=f"a bad @media screen override must be caught, got {errors}")

    def test_cmh_theme_02_unresolved_background_is_an_advisory(self):
        unresolved = _GOOD_LIGHT.replace("--cp-bg: #f7f4ef;", "--cp-bg: var(--missing);")
        errors, warnings = self._run(unresolved, _GOOD_DARK)
        self.assertTrue(any("not evaluated" in w for w in warnings),
                        msg=f"an unresolved background must be an advisory, got {warnings}")

    def test_cmh_theme_02_reformatted_default_is_not_an_override(self):
        # A default respelled as rgb() is canonically the same color, so it is not an override and
        # must not be flagged - even though the shipped default link is a sub-4.5 near-miss.
        recolored = _GOOD_LIGHT.replace("--cp-link: #0078d4;", "--cp-link: rgb(0, 120, 212);")
        errors, warnings = self._run(recolored, _GOOD_DARK)
        self.assertEqual([m for m in errors + warnings if "--cp-link" in m], [])

    def test_cmh_theme_02_non_text_ui_uses_three_to_one(self):
        # A UI edge at ~3.6:1 on bg is a clean non-text pair (it would fail the 4.5 text bar).
        ok_ui = _GOOD_LIGHT.replace("--cp-border-strong: #919191;", "--cp-border-strong: #808080;")
        errors, warnings = self._run(ok_ui, _GOOD_DARK)
        self.assertEqual([m for m in errors + warnings if "--cp-border-strong" in m], [])
        bad_ui = _GOOD_LIGHT.replace("--cp-border-strong: #919191;", "--cp-border-strong: #a8a8a8;")
        errors2, _ = self._run(bad_ui, _GOOD_DARK)
        self.assertTrue(any("--cp-border-strong" in e for e in errors2),
                        msg=f"expected a non-text UI error below 3:1, got {errors2}")


class SuggestFindingTests(unittest.TestCase):
    def test_cmh_theme_02_findings_carry_a_reachable_suggestion(self):
        near = _GOOD_LIGHT.replace("--cp-link: #0078d4;", "--cp-link: #6f8fb0;")
        findings = theme_contrast.theme_contrast_findings(_doc(near, _GOOD_DARK))
        link = [f for f in findings if f.fg_token == "--cp-link" and f.env == "light"]
        self.assertTrue(link, msg=f"expected a light link finding, got {findings}")
        self.assertIsNotNone(link[0].suggestion)
        self.assertGreaterEqual(
            contrast.contrast_ratio(link[0].suggestion, link[0].bg_value), link[0].target)


class RetrofitExemptionTests(unittest.TestCase):
    """AC4: a contrast near-miss/unresolved advisory stays out of retrofit's hard-fail path, but a
    bad-contrast ERROR still blocks it. retrofit treats every non-advisory validator warning as
    fatal, so the partition must key off the stable advisory prefix."""

    def setUp(self):
        sys.path.insert(0, os.path.join(_paths.TOOLS, "authoring"))
        import retrofit  # noqa: E402
        self.retrofit = retrofit

    def test_cmh_theme_02_advisory_is_not_fatal_for_retrofit(self):
        advisory = theme_contrast.ADVISORY_PREFIX + "light theme links near-miss"
        real = "some other validator warning"
        fatal, advisories = self.retrofit._partition_val_warnings([advisory, real])
        self.assertIn(real, fatal)
        self.assertIn(advisory, advisories)
        self.assertNotIn(advisory, fatal)


class DriftGuardTests(unittest.TestCase):
    def test_cmh_theme_02_defaults_match_shipped_template(self):
        # The DEFAULT_LIGHT/DARK constants must stay equal to the shipped template palette, or the
        # "accepted shipped defaults are never flagged" invariant silently breaks.
        tpl_path = os.path.join(HERE, "..", "assets", "template.shell.html")
        with open(tpl_path, encoding="utf-8") as fh:
            envs = contrast.theme_environments(fh.read())
        for token, value in theme_contrast.DEFAULT_LIGHT.items():
            self.assertEqual(contrast.parse_css_color(envs["light"].get(token)),
                             contrast.parse_css_color(value),
                             msg=f"DEFAULT_LIGHT[{token}] drifted from template.shell.html")
        for token, value in theme_contrast.DEFAULT_DARK.items():
            self.assertEqual(contrast.parse_css_color(envs["dark"].get(token)),
                             contrast.parse_css_color(value),
                             msg=f"DEFAULT_DARK[{token}] drifted from template.shell.html")


if __name__ == "__main__":
    unittest.main()
