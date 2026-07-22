#!/usr/bin/env python3
"""CMH-STORE-09 / CMH-STORE-03: storage-manager source invariants.

The storage manager reclaims a document's space from a single centralized list of per-document
subkey suffixes (CMH_SUBKEY_SUFFIXES in assets/js/01-config.js). If a runtime writer adds a new
`COMMENT_KEY + "::<suffix>"` subkey without registering it there, the manager would leave orphan
bytes behind on delete. This test greps the runtime sources for every such suffix and asserts each
is listed, so the "delete a document frees all its space" guarantee cannot silently regress.

Standard library only.
"""
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402  shared pkg/dev split path constants

JS_DIR = os.path.join(_paths.ASSETS, "js")
CONFIG_JS = os.path.join(JS_DIR, "01-config.js")

# Suffixes derived from COMMENT_KEY that are NOT per-document data the manager should reclaim:
# none currently. (The modern comment slot "::z" IS per-document and IS listed.)
_ALLOWED_UNLISTED = set()


def _read(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


class SuffixListTests(unittest.TestCase):
    def _declared_suffixes(self):
        text = _read(CONFIG_JS)
        m = re.search(r"const CMH_SUBKEY_SUFFIXES\s*=\s*\[(.*?)\]", text, re.DOTALL)
        self.assertIsNotNone(m, "CMH_SUBKEY_SUFFIXES not found in 01-config.js")
        return set(re.findall(r'"(::[^"]+)"', m.group(1)))

    def test_every_comment_key_subkey_suffix_is_registered(self):
        declared = self._declared_suffixes()
        # Every `COMMENT_KEY + "::..."` used anywhere in the runtime JS.
        found = set()
        pat = re.compile(r'COMMENT_KEY\s*\+\s*"(::[^"]+)"')
        for name in os.listdir(JS_DIR):
            if not name.endswith(".js"):
                continue
            for suf in pat.findall(_read(os.path.join(JS_DIR, name))):
                found.add(suf)
        missing = (found - declared) - _ALLOWED_UNLISTED
        self.assertEqual(
            missing, set(),
            "these COMMENT_KEY subkey suffixes are written by the runtime but not listed in "
            "CMH_SUBKEY_SUFFIXES (the storage manager would orphan them on delete): %s"
            % sorted(missing))

    def test_declared_suffixes_include_the_modern_slot(self):
        declared = self._declared_suffixes()
        self.assertIn("::z", declared)
        self.assertIn("::reviews::deleted", declared)


if __name__ == "__main__":
    unittest.main()
