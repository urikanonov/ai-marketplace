#!/usr/bin/env python3
"""Upgrade anti-regression corpus (CMH-TOOL-20).

Every frozen per-version snapshot under dev/upgrade-corpus/ must still upgrade cleanly with the
CURRENT upgrade.py: the upgraded document validates strict-clean (no errors and no warnings) and the
upgrade is idempotent (upgrading the upgraded document again changes nothing). This catches a layer
or tool change that would break upgrading a document produced by an older version.
"""
import glob
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402  shared pkg/dev split path constants
TOOLS = _paths.TOOLS
sys.path.insert(0, TOOLS)
import upgrade  # noqa: E402
import validate  # noqa: E402

CORPUS_DIR = os.path.join(_paths.DEV, "upgrade-corpus")
TEMPLATE = _paths.TEMPLATE  # the current dist/PORTABLE.html


def _snapshots():
    return sorted(glob.glob(os.path.join(CORPUS_DIR, "v*.html")))


def _read(path):
    with open(path, "r", encoding="utf-8", newline="") as handle:
        return handle.read()


class UpgradeCorpusTests(unittest.TestCase):
    def test_corpus_is_non_empty(self):
        self.assertTrue(_snapshots(), "no dev/upgrade-corpus/v*.html snapshots found")

    def test_every_snapshot_upgrades_clean_and_is_idempotent(self):
        template = _read(TEMPLATE)
        for snapshot in _snapshots():
            with self.subTest(snapshot=os.path.basename(snapshot)):
                target = _read(snapshot)
                upgraded, _changed = upgrade.upgrade(target, template, snapshot, TEMPLATE)
                with tempfile.TemporaryDirectory() as directory:
                    out_path = os.path.join(directory, "upgraded.html")
                    with open(out_path, "w", encoding="utf-8", newline="") as handle:
                        handle.write(upgraded)
                    errors, warnings = validate.validate(out_path)
                self.assertEqual(errors, [], "%s: upgrade validation errors: %r" % (snapshot, errors))
                self.assertEqual(warnings, [], "%s: upgrade validation warnings: %r" % (snapshot, warnings))
                # Idempotent: upgrading the upgraded document changes nothing.
                _again, changed_again = upgrade.upgrade(upgraded, template, snapshot, TEMPLATE)
                self.assertEqual(
                    changed_again, [], "%s: upgrade is not idempotent (still stale: %r)" % (snapshot, changed_again))


if __name__ == "__main__":
    unittest.main()
