#!/usr/bin/env python3
"""Forward-compatible content/infra contract tests for generated documents."""
import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402
sys.path.insert(0, _paths.TOOLS)
import new_document  # noqa: E402

EXPECTED_REGIONS = ["CSS", "HANDLED IDS", "EMBEDDED COMMENTS", "COMMENT UI", "JS"]
CONTENT_BEGIN = "<!-- BEGIN: commentable-html - CONTENT (agent edits ONLY between these markers) -->"
CONTENT_END = "<!-- END: commentable-html - CONTENT -->"


def _read(path):
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read().replace("\r\n", "\n").replace("\r", "\n")


def _descriptor(html):
    m = re.search(
        r'<script\b[^>]*\bid\s*=\s*(["\'])commentableHtmlLayer\1[^>]*>([\s\S]*?)</script>',
        html,
        re.IGNORECASE,
    )
    if not m:
        return None
    return json.loads(m.group(2))


def _marker_line(kind, region):
    return re.compile(
        r"(?m)^[ \t]*(?:<!--[ \t]*)?(?:/\*[ \t]*)?(?:=+[ \t]*)?"
        + re.escape(kind + ": commentable-html - " + region)
        + r"[ \t]*(?:=+[ \t]*)?(?:-->|\*/)?[ \t]*$"
    )


def _assert_region_order(testcase, html):
    last_begin = -1
    for region in EXPECTED_REGIONS:
        begins = list(_marker_line("BEGIN", region).finditer(html))
        ends = list(_marker_line("END", region).finditer(html))
        testcase.assertEqual(len(begins), 1, "expected one BEGIN marker for %s" % region)
        testcase.assertEqual(len(ends), 1, "expected one END marker for %s" % region)
        testcase.assertLess(begins[0].start(), ends[0].start(), "%s END precedes BEGIN" % region)
        testcase.assertGreater(begins[0].start(), last_begin, "%s is out of order" % region)
        last_begin = begins[0].start()


def _assert_content_root(testcase, html):
    begin = html.index(CONTENT_BEGIN)
    end = html.index(CONTENT_END)
    testcase.assertLess(begin, end)
    root = None
    for match in re.finditer(r"<main\b[^>]*\bid\s*=\s*([\"'])commentRoot\1[^>]*>", html[:begin], re.IGNORECASE):
        root = match
    testcase.assertIsNotNone(root, "no #commentRoot before CONTENT BEGIN")
    tag = root.group(0)
    testcase.assertIn("data-cmh-content-root", tag)
    close = html.find("</main>", end)
    testcase.assertNotEqual(close, -1, "no closing </main> after CONTENT END")
    testcase.assertLess(root.start(), begin)
    testcase.assertLess(end, close)


class ForwardCompatibleLayoutTests(unittest.TestCase):
    def assert_contract(self, html, mode):
        desc = _descriptor(html)
        self.assertIsInstance(desc, dict)
        self.assertRegex(desc.get("version", ""), r"^\d+\.\d+\.\d+$")
        self.assertEqual(desc.get("mode"), mode)
        self.assertEqual(desc.get("regions"), EXPECTED_REGIONS)
        _assert_region_order(self, html)
        _assert_content_root(self, html)

    def test_dist_templates_publish_layer_descriptor_and_content_hook(self):
        for name, mode in (("PORTABLE.html", "portable"), ("NONPORTABLE.html", "nonportable")):
            with self.subTest(name=name):
                self.assert_contract(_read(os.path.join(_paths.DIST, name)), mode)

    def test_new_document_preserves_descriptor_and_content_hook(self):
        template = _read(os.path.join(_paths.DIST, "PORTABLE.html"))
        html = new_document.make_document(
            template,
            '<section><h2 id="summary">Summary</h2><p>Body.</p></section>',
            "forward-compat-doc",
            "Forward Compat Doc",
            "source.md",
        )
        self.assert_contract(html, "portable")

    def test_offline_descriptor_mode_is_valid_contract(self):
        html = _read(os.path.join(_paths.DIST, "PORTABLE.html")).replace('"mode":"portable"', '"mode":"offline"', 1)
        self.assert_contract(html, "offline")


if __name__ == "__main__":
    unittest.main()
