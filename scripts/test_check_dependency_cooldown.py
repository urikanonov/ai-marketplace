#!/usr/bin/env python3
"""Tests for scripts/check_dependency_cooldown.py."""

import importlib.util
import os
import subprocess
import unittest
from unittest import mock
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

    def test_rehoist_same_name_and_version_is_not_reported(self):
        base = {
            "packages": {
                "node_modules/parent/node_modules/leaf": {
                    "version": "3.0.0",
                    "resolved": "https://registry.npmjs.org/leaf/-/leaf-3.0.0.tgz",
                }
            }
        }
        head = {
            "packages": {
                "node_modules/leaf": {
                    "version": "3.0.0",
                    "resolved": "https://registry.npmjs.org/leaf/-/leaf-3.0.0.tgz",
                }
            }
        }

        self.assertEqual(cdc.changed_dependency_versions(head, base), set())

    def test_alias_uses_lockfile_entry_name_instead_of_path_segment(self):
        head = {
            "packages": {
                "node_modules/local-alias": {
                    "name": "real-package",
                    "version": "2.0.0",
                    "resolved": "https://registry.npmjs.org/real-package/-/real-package-2.0.0.tgz",
                }
            }
        }

        self.assertEqual(cdc.changed_dependency_versions(head, None), {dep("real-package", "2.0.0")})

    def test_changed_non_registry_dependency_emits_warning_not_cooldown_pair(self):
        head = {
            "packages": {
                "node_modules/git-only": {
                    "version": "1.0.0",
                    "resolved": "git+https://example.invalid/git-only.git#abcdef",
                }
            }
        }

        changed, warnings = cdc.changed_dependency_versions(head, None, include_warnings=True)

        self.assertEqual(changed, set())
        self.assertEqual(len(warnings), 1)
        self.assertIn("git-only@1.0.0", warnings[0])
        self.assertIn("not cooldown-checked", warnings[0])

    def test_discovered_lockfiles_cover_tracked_package_locks(self):
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        )
        tracked = sorted(
            line for line in result.stdout.splitlines()
            if line.endswith("package-lock.json") and "/node_modules/" not in line
        )

        self.assertEqual(list(cdc.discover_lockfiles(repo)), tracked)

    def test_same_commit_returns_empty_tuple_when_warnings_requested(self):
        with mock.patch.object(cdc, "ref_exists", return_value=True), \
                mock.patch.object(cdc, "rev_parse", return_value="abc"):
            self.assertEqual(
                cdc.changed_pairs_from_git("base", "head", "pull_request", include_warnings=True),
                (set(), []),
            )


class TestRegistryFetchFailOpen(unittest.TestCase):
    def test_null_time_map_fails_open_without_crashing(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"time": null}'

        changed = {dep("null-time", "1.0.0")}
        with mock.patch.object(cdc.urllib.request, "urlopen", return_value=Response()), \
                mock.patch.object(cdc, "REQUEST_RETRIES", 1):
            publish_times, warnings = cdc.fetch_publish_times(changed)

        self.assertEqual(publish_times, {})
        self.assertEqual(len(warnings), 1)
        self.assertIn("could not verify null-time@1.0.0", warnings[0])

    def test_registry_warnings_are_sorted_for_deterministic_output(self):
        changed = {dep("beta", "1.0.0"), dep("alpha", "1.0.0")}

        def fail(name, versions, deadline_at):
            return {}, [
                "check-dependency-cooldown: WARNING - could not verify %s@%s from npm registry after 1 attempts; skipping this package (%s)."
                % (name, version, name)
                for version in versions
            ]

        with mock.patch.object(cdc, "fetch_publish_times_for_name", side_effect=fail), \
                mock.patch.object(cdc, "REQUEST_RETRIES", 1):
            publish_times, warnings = cdc.fetch_publish_times(changed)

        self.assertEqual(publish_times, {})
        self.assertEqual(warnings, sorted(warnings))
        self.assertIn("alpha@1.0.0", warnings[0])
        self.assertIn("beta@1.0.0", warnings[1])

    def test_packuments_are_fetched_once_per_package_name(self):
        changed = {dep("shared", "1.0.0"), dep("shared", "2.0.0")}
        calls = []

        def fake_fetch(name, versions, deadline_at):
            calls.append((name, tuple(versions)))
            return {
                dep(name, "1.0.0"): datetime(2026, 1, 1, tzinfo=timezone.utc),
                dep(name, "2.0.0"): datetime(2026, 1, 2, tzinfo=timezone.utc),
            }, []

        with mock.patch.object(cdc, "fetch_publish_times_for_name", side_effect=fake_fetch):
            publish_times, warnings = cdc.fetch_publish_times(changed)

        self.assertEqual(warnings, [])
        self.assertEqual(calls, [("shared", ("1.0.0", "2.0.0"))])
        self.assertEqual(set(publish_times), changed)


if __name__ == "__main__":
    unittest.main()
