#!/usr/bin/env python3
"""Golden-fixture tests for highlight_code.py.

Each language in `LANGUAGE_CONFIGS` has a realistic source sample (`highlight_samples.SAMPLES`)
rendered into a checked-in, pre-annotated golden under `fixtures/highlight/<lang>.html`. These
tests re-run the shipped highlighter on every `<lang>.sample` and assert the output byte-for-byte
matches the committed golden, so any change in highlighting behaviour surfaces as a reviewable
fixture diff. Regenerate intentional changes with:

    python plugins/commentable-html/dev/tests/build_highlight_fixtures.py
"""
import html
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402
sys.path.insert(0, _paths.TOOLS)
import highlight_code as H  # noqa: E402
from highlight_samples import SAMPLES  # noqa: E402

FIXTURES = os.path.join(HERE, "fixtures", "highlight")


def _read(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _text_content(fragment):
    return html.unescape(re.sub(r"<[^>]+>", "", fragment))


class HighlightGoldenTests(unittest.TestCase):
    def test_every_config_language_has_a_sample(self):
        self.assertEqual(sorted(H.LANGUAGE_CONFIGS), sorted(SAMPLES))

    def test_fixtures_cover_exactly_the_samples(self):
        htmls = {n[:-5] for n in os.listdir(FIXTURES) if n.endswith(".html")}
        samples = {n[:-7] for n in os.listdir(FIXTURES) if n.endswith(".sample")}
        self.assertEqual(htmls, set(SAMPLES))
        self.assertEqual(samples, set(SAMPLES))

    def test_highlight_matches_preannotated_golden(self):
        for language in sorted(SAMPLES):
            with self.subTest(language=language):
                sample = _read(os.path.join(FIXTURES, language + ".sample"))
                golden = _read(os.path.join(FIXTURES, language + ".html"))
                self.assertEqual(H.highlight_code(language, sample), golden)

    def test_golden_text_roundtrips_to_the_sample(self):
        for language in sorted(SAMPLES):
            with self.subTest(language=language):
                sample = _read(os.path.join(FIXTURES, language + ".sample"))
                golden = _read(os.path.join(FIXTURES, language + ".html"))
                self.assertEqual(_text_content(golden), sample)

    def test_samples_have_no_crlf_or_trailing_whitespace(self):
        for language in sorted(SAMPLES):
            with self.subTest(language=language):
                sample = _read(os.path.join(FIXTURES, language + ".sample"))
                self.assertNotIn("\r", sample)
                self.assertFalse(re.search(r"[ \t]+\n", sample), "trailing whitespace")

    def test_every_golden_is_actually_annotated(self):
        # Every sample includes keywords and numbers; every sample except JSON
        # (which has no comment syntax) includes a comment. Guards against a
        # language silently degrading to escaped-only plain text.
        for language in sorted(SAMPLES):
            with self.subTest(language=language):
                golden = _read(os.path.join(FIXTURES, language + ".html"))
                self.assertIn('class="cmh-code-kw"', golden)
                self.assertIn('class="cmh-code-num"', golden)
                if language != "json":
                    self.assertIn('class="cmh-code-com"', golden)

    def test_fixtures_are_up_to_date_with_the_builder(self):
        # Fails if a sample changed without regenerating the goldens.
        for language in sorted(SAMPLES):
            with self.subTest(language=language):
                sample_on_disk = _read(os.path.join(FIXTURES, language + ".sample"))
                normalized = SAMPLES[language].replace("\r\n", "\n").replace("\r", "\n")
                self.assertEqual(sample_on_disk, normalized)


if __name__ == "__main__":
    unittest.main()
