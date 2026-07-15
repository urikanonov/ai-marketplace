#!/usr/bin/env python3
"""CMH-TOOL-LAYOUT-01: the shipped tools are grouped into per-topic buckets under tools/<topic>/,
every expected tool lives at its bucket path, the tools/ root holds no stray flat tool (only the
_toolpath.py bootstrap), and every tool imports by bare name via the bootstrap - so a bucket move
that stranded a sibling import (for example finalize -> validate, or a deck tool -> deck_common) is
caught here instead of at runtime.
"""
import importlib
import os
import unittest

import _paths  # noqa: E402  adds the tool buckets to sys.path via the shipped tools/_toolpath.py

# The intended bucket layout. Every shipped tool module is listed exactly once under its topic.
EXPECTED = {
    "deck": ["deck_common", "deck_scaffold", "deck_validate", "pptx_to_fragment"],
    "kusto": ["kql_highlight", "kusto_link"],
    "checklist": ["checklist_apply", "checklist_scaffold"],
    "notes": ["notes_apply", "notes_scaffold"],
    "blocks": ["chart_block", "diff_block", "highlight_code", "highlight_document"],
    "authoring": ["new_document", "generate_toc", "inline_images", "finalize",
                  "fix_skip", "mark_handled", "upgrade", "retrofit", "doc_stamp"],
    "validate": ["validate"],
}


class ToolsLayoutTests(unittest.TestCase):
    def test_every_expected_tool_exists_at_its_bucket_path(self):
        for topic, names in EXPECTED.items():
            for name in names:
                path = os.path.join(_paths.TOOLS, topic, name + ".py")
                with self.subTest(tool="%s/%s" % (topic, name)):
                    self.assertTrue(os.path.isfile(path), "missing shipped tool: %s" % path)

    def test_tools_root_holds_only_the_bootstrap_and_buckets(self):
        stray = sorted(
            n for n in os.listdir(_paths.TOOLS)
            if n.endswith(".py") and n != "_toolpath.py")
        self.assertEqual(stray, [], "unbucketed tool(s) left at tools/ root: %s" % stray)

    def test_no_shipped_tool_is_unlisted(self):
        # Every top-level tool module directly under a topic bucket (tools/<topic>/<name>.py) must be
        # accounted for in EXPECTED, so a new tool added to a bucket without updating this map (and the
        # SKILL references) is flagged. Nested helper packages (for example validate/cmhval/) are not
        # standalone tools and are not scanned.
        found = set()
        for topic in os.listdir(_paths.TOOLS):
            tdir = os.path.join(_paths.TOOLS, topic)
            if not os.path.isdir(tdir) or topic.startswith(("_", ".")):
                continue
            for n in os.listdir(tdir):
                if (n.endswith(".py") and not n.startswith("_")
                        and os.path.isfile(os.path.join(tdir, n))):
                    found.add(n[:-3])
        listed = {name for names in EXPECTED.values() for name in names}
        self.assertEqual(found, listed,
                         "tools on disk vs listed differ: on disk only=%s, listed only=%s"
                         % (sorted(found - listed), sorted(listed - found)))

    def test_every_tool_imports_by_bare_name(self):
        # Importing each module runs its module-level cross-imports through the _toolpath bootstrap,
        # so a stranded sibling import surfaces as a failure here.
        for topic, names in EXPECTED.items():
            for name in names:
                with self.subTest(tool=name):
                    try:
                        importlib.import_module(name)
                    except Exception as exc:  # noqa: BLE001 - any import failure is the bug we guard
                        self.fail("import %s failed: %r" % (name, exc))


if __name__ == "__main__":
    unittest.main()
