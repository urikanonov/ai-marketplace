#!/usr/bin/env python3
"""Tests for scripts/check_dependency_cooldown.py."""

import importlib.util
import os
import unittest
from datetime import datetime, timedelta, timezone

_MODULE_PATH = os.path.join(os.path.dirname(__file__), "check_dependency_cooldown.py")
_spec = importlib.util.spec_from_file_location("check_dependency_cooldown", _MODULE_PATH)
cdc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cdc)


def dep(name, version):
    return cdc.DependencyVersion(name, version)


class TestCooldownViolations(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 7, 12, 9, 0, tzinfo=timezone.utc)

    def test_twenty_day_old_version_passes(self):
        changed = {dep("old", "1.0.0")}
        times = {dep("old", "1.0.0"): self.now - timedelta(days=20)}

        self.assertEqual(cdc.cooldown_violations(changed, times, self.now, 14), [])

    def test_five_day_old_version_violates(self):
        changed = {dep("fresh", "1.0.0")}
        times = {dep("fresh", "1.0.0"): self.now - timedelta(days=5)}

        violations = cdc.cooldown_violations(changed, times, self.now, 14)

        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].name, "fresh")
        self.assertEqual(violations[0].version, "1.0.0")

    def test_exactly_fourteen_days_old_passes(self):
        changed = {dep("boundary", "1.0.0")}
        times = {dep("boundary", "1.0.0"): self.now - timedelta(days=14)}

        self.assertEqual(cdc.cooldown_violations(changed, times, self.now, 14), [])

    def test_empty_changed_set_passes(self):
        self.assertEqual(cdc.cooldown_violations(set(), {}, self.now, 14), [])

    def test_missing_publish_time_is_skipped(self):
        changed = {dep("missing", "1.0.0")}

        self.assertEqual(cdc.cooldown_violations(changed, {}, self.now, 14), [])


class TestLockfileDiff(unittest.TestCase):
    def test_added_and_bumped_registry_versions_are_reported_once(self):
        base = {
            "packages": {
                "": {"version": "1.0.0"},
                "node_modules/old": {
                    "version": "1.0.0",
                    "resolved": "https://registry.npmjs.org/old/-/old-1.0.0.tgz",
                },
                "node_modules/same": {
                    "version": "1.0.0",
                    "resolved": "https://registry.npmjs.org/same/-/same-1.0.0.tgz",
                },
            }
        }
        head = {
            "packages": {
                "": {"version": "2.0.0"},
                "node_modules/old": {
                    "version": "2.0.0",
                    "resolved": "https://registry.npmjs.org/old/-/old-2.0.0.tgz",
                },
                "node_modules/same": {
                    "version": "1.0.0",
                    "resolved": "https://registry.npmjs.org/same/-/same-1.0.0.tgz",
                },
                "node_modules/@scope/new": {
                    "version": "1.0.0",
                    "resolved": "https://registry.npmjs.org/@scope/new/-/new-1.0.0.tgz",
                },
                "node_modules/no-version": {
                    "resolved": "https://registry.npmjs.org/no-version/-/no-version-1.0.0.tgz",
                },
                "node_modules/off-registry": {
                    "version": "1.0.0",
                    "resolved": "https://example.invalid/off-registry-1.0.0.tgz",
                },
            }
        }

        changed = cdc.changed_dependency_versions(head, base)

        self.assertEqual(changed, {dep("old", "2.0.0"), dep("@scope/new", "1.0.0")})

    def test_resolved_url_only_change_is_not_reported(self):
        base = {
            "packages": {
                "node_modules/@scope/pkg": {
                    "version": "1.0.0",
                    "resolved": "https://example.invalid/@scope/pkg-1.0.0.tgz",
                }
            }
        }
        head = {
            "packages": {
                "node_modules/@scope/pkg": {
                    "version": "1.0.0",
                    "resolved": "https://registry.npmjs.org/@scope/pkg/-/pkg-1.0.0.tgz",
                }
            }
        }

        self.assertEqual(cdc.changed_dependency_versions(head, base), set())

    def test_missing_base_lockfile_treats_all_head_entries_as_added(self):
        head = {
            "packages": {
                "node_modules/nested/node_modules/leaf": {
                    "version": "3.0.0",
                    "resolved": "https://registry.npmjs.org/leaf/-/leaf-3.0.0.tgz",
                }
            }
        }

        self.assertEqual(cdc.changed_dependency_versions(head, None), {dep("leaf", "3.0.0")})


if __name__ == "__main__":
    unittest.main()
