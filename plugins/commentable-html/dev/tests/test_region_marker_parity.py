#!/usr/bin/env python3
"""CMH-VAL-22: every region-marker locator answers a canonical corpus identically.

The layer's regions are located four times over: once in the runtime
(`_cmhRegionMarkerMatches`, assets/js/67-export-standalone.js) and three times in Python
(`_region_marker_matches` in tools/build_parts/20-nonshareable-regions.py, in
skill/tools/validate/checks/parsing.py and in skill/tools/authoring/upgrade.py). Two views that
disagree about which comment IS the boundary is the defect class #964 fixed - a document one view
counts and the other does not is a document the validator blesses and the exporter mangles (or
vice versa).

This test pins the PYTHON copies to tests/fixtures/region_marker_parity.json;
tests/59-region-marker-parity.spec.js pins the RUNTIME to the SAME fixture, so a divergence in
either language fails one of the two suites.
"""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402

PARITY_FIXTURE = os.path.join(HERE, "fixtures", "region_marker_parity.json")


def _load_module(path, name):
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _implementations():
    """{label: callable(text, kind, name) -> [match]} for every Python copy."""
    sys.path.insert(0, _paths.TOOLS)
    from checks import parsing  # noqa: E402

    import upgrade  # noqa: E402
    import validate  # noqa: E402

    build = _load_module(os.path.join(_paths.DEV_TOOLS, "build.py"), "cmh_build_tool")
    return (
        {
            "validate/checks/parsing.py": parsing._region_marker_matches,
            "authoring/upgrade.py": upgrade._region_marker_matches,
            "build_parts/20-nonshareable-regions.py": build._region_marker_matches,
        },
        {
            "validate/validate.py": (validate._read, parsing._region_marker_matches),
            "authoring/upgrade.py": (upgrade._read, upgrade._region_marker_matches),
        },
    )


class RegionMarkerParityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(PARITY_FIXTURE, "r", encoding="utf-8") as fh:
            cls.cases = json.load(fh)["cases"]
        cls.impls, cls.readers = _implementations()

    def test_fixture_is_non_trivial(self):
        """A corpus that lost its hard cases would pass while pinning nothing."""
        self.assertGreaterEqual(len(self.cases), 24)
        ids = [c["id"] for c in self.cases]
        self.assertEqual(len(ids), len(set(ids)), "case ids must be unique")
        self.assertTrue(any(c["expected"] for c in self.cases), "some case must match")
        self.assertTrue(any(not c["expected"] for c in self.cases), "some case must not match")
        # Every separator Python calls a line break, and the lone CR, must be in the corpus, so the
        # fixture really is the whole contract rather than a sample of it.
        for sep in ("\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029", "\r"):
            self.assertTrue(any(sep in c["text"] for c in self.cases),
                            "no corpus case carries %r" % sep)

    def test_corpus_stays_in_the_basic_multilingual_plane(self):
        """The pinned offsets are shared by two languages that COUNT differently: JavaScript
        indexes UTF-16 code units and Python indexes code points, so a case carrying an astral
        character would make the same document resolve to two different numbers and the runtime
        spec and this test would disagree while both were right. Every character stays in the BMP,
        where the two coordinate systems coincide."""
        for case in self.cases:
            for ch in case["text"]:
                self.assertLess(ord(ch), 0x10000,
                                "case %s carries a non-BMP character %r" % (case["id"], ch))

    def test_a_match_refuses_a_group_it_does_not_have(self):
        """The three copies expose the same start(group)/end(group) signature; group 0 and 1 are
        deliberately the same span, and anything else is refused rather than answered with a
        plausible wrong offset."""
        text = "<!-- BEGIN: commentable-html - CSS -->\n"
        for label, fn in self.impls.items():
            with self.subTest(impl=label):
                m = fn(text, "BEGIN", "CSS")[0]
                self.assertEqual(m.start(0), m.start(1))
                self.assertEqual(m.end(0), m.end(1))
                with self.assertRaises(IndexError):
                    m.start(2)
                with self.assertRaises(IndexError):
                    m.end(2)

    def test_every_python_copy_answers_the_corpus_identically(self):
        for case in self.cases:
            for label, fn in self.impls.items():
                with self.subTest(case=case["id"], impl=label):
                    got = [m.start(1) for m in fn(case["text"], case["kind"], case["region"])]
                    self.assertEqual(got, case["expected"])

    def test_match_ends_cover_exactly_the_marker(self):
        for case in self.cases:
            marker = "%s: commentable-html - %s" % (case["kind"], case["region"])
            for label, fn in self.impls.items():
                with self.subTest(case=case["id"], impl=label):
                    for m in fn(case["text"], case["kind"], case["region"]):
                        self.assertEqual(case["text"][m.start(1):m.end(1)], marker)

    def test_line_breaks_are_the_newlines_the_runtime_sees(self):
        """Python's own idea of a line break is WIDER than a browser's, and the difference is
        the whole bug: `str.splitlines()` breaks on \\x0b, \\x0c, \\x1c, \\x1d, \\x1e, \\x85,
        \\u2028 and \\u2029, and treats a lone \\r as a terminator, while the runtime (and the
        HTML a reader opens) break on \\n only. A marker "line" that exists only after such a
        split would be counted by the validator, the build and the upgrade tool, and ignored by
        the runtime that reads the file back."""
        for sep in ("\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029", "\r"):
            text = "<!--%sBEGIN: commentable-html - CSS%s-->\n" % (sep, sep)
            for label, fn in self.impls.items():
                with self.subTest(sep=repr(sep), impl=label):
                    self.assertEqual(fn(text, "BEGIN", "CSS"), [])

    def test_file_readers_preserve_lone_cr_for_the_marker_decision(self):
        text = "prefix\r<!-- BEGIN: commentable-html - CSS -->\rsuffix"
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "lone-cr.html")
            with open(path, "wb") as fh:
                fh.write(text.encode("utf-8"))
            for label, (reader, matcher) in self.readers.items():
                with self.subTest(reader=label):
                    read_text = reader(path)
                    self.assertEqual(read_text, text)
                    self.assertEqual(matcher(read_text, "BEGIN", "CSS"), [])
            import validate

            errors, _warnings = validate.validate(path, charts=False)
            self.assertTrue(
                any("marker count changes after browser newline normalization" in error
                    for error in errors),
                errors,
            )

    def test_validator_file_reader_normalizes_browser_semantic_newlines(self):
        import validate

        text = (
            '<html><body><div class="cmh-checklist" data-cmh-checklist="c">'
            '<li data-cmh-item="a\nb">A</li>'
            '<li data-cmh-item="a\r\nb">B</li>'
            "</div></body></html>"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "mixed-newlines.html")
            with open(path, "wb") as fh:
                fh.write(text.encode("utf-8"))
            _errors, warnings = validate.validate(path, charts=False)
        self.assertTrue(
            any("duplicate data-cmh-item id" in warning for warning in warnings),
            warnings,
        )


if __name__ == "__main__":
    unittest.main()
