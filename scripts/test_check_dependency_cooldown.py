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

from _git_test_env import clean_git_env  # noqa: E402  (scripts/ is on sys.path under discover)


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
            env=clean_git_env(),
            capture_output=True,
            text=True,
            check=True,
        )
        tracked = sorted(
            line for line in result.stdout.splitlines()
            if line.endswith("package-lock.json") and "/node_modules/" not in line
        )

        self.assertEqual(list(cdc.discover_lockfiles(repo)), tracked)

    def test_discover_lockfiles_returns_sorted_output(self):
        # Determinism (round-3 fix): discover_lockfiles wraps the glob scan in sorted() so the
        # cooldown gate reports lockfiles in a stable order regardless of filesystem listing
        # order. Reverting the sorted() lets set/glob ordering leak through and turns this red.
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            names = ["m", "b", "z", "a", "n", "c"]
            for name in names:
                d = os.path.join(root, "plugins", name, "dev")
                os.makedirs(d)
                open(os.path.join(d, "package-lock.json"), "wb").close()
            os.makedirs(os.path.join(root, "site", "tests"))
            open(os.path.join(root, "site", "tests", "package-lock.json"), "wb").close()

            result = cdc.discover_lockfiles(root)
            expected = tuple(sorted(
                ["plugins/%s/dev/package-lock.json" % n for n in names]
                + ["site/tests/package-lock.json"]
            ))
            self.assertEqual(result, expected)
            self.assertEqual(list(result), sorted(result))

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


def advisory(ghsa_id, name, vulnerable_range, first_patched):
    return {
        "ghsa_id": ghsa_id,
        "vulnerabilities": [
            {
                "package": {"ecosystem": "npm", "name": name},
                "vulnerable_version_range": vulnerable_range,
                "first_patched_version": first_patched,
            }
        ],
    }


# The two advisories that fixed dompurify while #1233 was open (GHSA ids and ranges as published).
DOMPURIFY_ADVISORIES = [
    advisory("GHSA-55q2-fjhq-7xh7", "dompurify", "<= 3.4.12", "3.4.13"),
    advisory("GHSA-c2j3-45gr-mqc4", "dompurify", "<= 3.4.11", "3.4.12"),
]


class TestVersionComparison(unittest.TestCase):
    def test_release_parts_compare_numerically_not_lexically(self):
        self.assertEqual(cdc.compare_versions("3.4.9", "3.4.11"), -1)
        self.assertEqual(cdc.compare_versions("11.16.1", "11.16.1"), 0)
        self.assertEqual(cdc.compare_versions("2.0.0", "1.99.99"), 1)

    def test_prerelease_sorts_below_its_release(self):
        self.assertEqual(cdc.compare_versions("1.2.3-beta.1", "1.2.3"), -1)
        self.assertEqual(cdc.compare_versions("1.2.3-beta.2", "1.2.3-beta.10"), -1)

    def test_build_metadata_and_v_prefix_are_ignored(self):
        self.assertEqual(cdc.compare_versions("v1.2.3+build.5", "1.2.3"), 0)

    def test_version_matches_range_handles_compound_constraints(self):
        self.assertTrue(cdc.version_matches_range("<= 3.4.11", "3.4.11"))
        self.assertFalse(cdc.version_matches_range("<= 3.4.11", "3.4.12"))
        self.assertTrue(cdc.version_matches_range(">= 2.0.0, < 2.1.5", "2.1.4"))
        self.assertFalse(cdc.version_matches_range(">= 2.0.0, < 2.1.5", "1.9.0"))
        self.assertTrue(cdc.version_matches_range("= 1.2.3", "1.2.3"))

    def test_unparseable_range_matches_nothing(self):
        self.assertFalse(cdc.version_matches_range("", "1.0.0"))
        self.assertFalse(cdc.version_matches_range("~1.2.3", "1.2.3"))

    def test_first_patched_identifier_accepts_both_api_shapes(self):
        self.assertEqual(cdc.first_patched_identifier("3.4.13"), "3.4.13")
        self.assertEqual(cdc.first_patched_identifier({"identifier": "3.4.13"}), "3.4.13")
        self.assertIsNone(cdc.first_patched_identifier(None))


class TestAdvisoryExemption(unittest.TestCase):
    def test_bump_that_patches_an_open_alert_is_exempt(self):
        exemption = cdc.advisory_exemption("dompurify", "3.4.13", {"3.4.11"}, DOMPURIFY_ADVISORIES)

        self.assertIsNotNone(exemption)
        self.assertEqual(exemption.name, "dompurify")
        self.assertEqual(exemption.version, "3.4.13")
        self.assertEqual(exemption.from_version, "3.4.11")
        self.assertEqual(exemption.ghsa_id, "GHSA-55q2-fjhq-7xh7")

    def test_bump_from_an_unaffected_base_version_is_not_exempt(self):
        self.assertIsNone(
            cdc.advisory_exemption("dompurify", "3.5.0", {"3.4.13"}, DOMPURIFY_ADVISORIES)
        )

    def test_bump_that_lands_on_a_still_vulnerable_version_is_not_exempt(self):
        advisories = [advisory("GHSA-55q2-fjhq-7xh7", "dompurify", "<= 3.4.12", "3.4.13")]

        self.assertIsNone(cdc.advisory_exemption("dompurify", "3.4.12", {"3.4.11"}, advisories))

    def test_newly_added_package_has_no_base_version_and_is_not_exempt(self):
        self.assertIsNone(cdc.advisory_exemption("dompurify", "3.4.13", set(), DOMPURIFY_ADVISORIES))

    def test_advisory_for_another_package_is_ignored(self):
        advisories = [advisory("GHSA-xxxx-xxxx-xxxx", "other-pkg", "<= 3.4.12", "3.4.13")]

        self.assertIsNone(cdc.advisory_exemption("dompurify", "3.4.13", {"3.4.11"}, advisories))

    def test_exemption_is_deterministic_when_several_advisories_match(self):
        first = cdc.advisory_exemption("dompurify", "3.4.13", {"3.4.10"}, DOMPURIFY_ADVISORIES)
        second = cdc.advisory_exemption(
            "dompurify", "3.4.13", {"3.4.10"}, list(reversed(DOMPURIFY_ADVISORIES))
        )

        self.assertEqual(first, second)
        self.assertEqual(first.ghsa_id, "GHSA-55q2-fjhq-7xh7")


class TestSecurityExemptCooldown(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 9, 9, 0, tzinfo=timezone.utc)

    def test_fresh_security_patch_is_not_a_violation(self):
        changed = {dep("dompurify", "3.4.13")}
        times = {dep("dompurify", "3.4.13"): self.now - timedelta(days=5)}
        exempt = {
            dep("dompurify", "3.4.13"): cdc.SecurityExemption(
                "dompurify", "3.4.13", "3.4.11", "GHSA-55q2-fjhq-7xh7"
            )
        }

        self.assertEqual(cdc.cooldown_violations(changed, times, self.now, 14, exempt), [])

    def test_fresh_non_security_bump_is_still_a_violation(self):
        changed = {dep("dompurify", "3.4.13"), dep("left-pad", "9.9.9")}
        times = {
            dep("dompurify", "3.4.13"): self.now - timedelta(days=5),
            dep("left-pad", "9.9.9"): self.now - timedelta(days=5),
        }
        exempt = {
            dep("dompurify", "3.4.13"): cdc.SecurityExemption(
                "dompurify", "3.4.13", "3.4.11", "GHSA-55q2-fjhq-7xh7"
            )
        }

        violations = cdc.cooldown_violations(changed, times, self.now, 14, exempt)

        self.assertEqual([v.name for v in violations], ["left-pad"])

    def test_security_exemptions_query_each_package_name_once(self):
        changed = {dep("dompurify", "3.4.13"), dep("dompurify", "3.4.12")}
        calls = []

        def fake_fetch(name, deadline_at):
            calls.append(name)
            return DOMPURIFY_ADVISORIES, []

        with mock.patch.object(cdc, "fetch_advisories", side_effect=fake_fetch):
            exempt, warnings = cdc.security_exemptions(changed, {"dompurify": {"3.4.11"}})

        self.assertEqual(calls, ["dompurify"])
        self.assertEqual(warnings, [])
        self.assertEqual(sorted(d.version for d in exempt), ["3.4.12", "3.4.13"])

    def test_packages_with_no_base_version_are_never_queried(self):
        changed = {dep("brand-new", "1.0.0")}

        with mock.patch.object(cdc, "fetch_advisories", side_effect=AssertionError("queried")):
            exempt, warnings = cdc.security_exemptions(changed, {})

        self.assertEqual(exempt, {})
        self.assertEqual(warnings, [])


class TestAdvisoryFetchFailOpen(unittest.TestCase):
    def test_unreachable_advisory_api_leaves_the_bump_unexempted(self):
        changed = {dep("dompurify", "3.4.13")}

        with mock.patch.object(
            cdc.urllib.request, "urlopen", side_effect=cdc.urllib.error.URLError("offline")
        ), mock.patch.object(cdc, "REQUEST_RETRIES", 1):
            exempt, warnings = cdc.security_exemptions(changed, {"dompurify": {"3.4.11"}})

        self.assertEqual(exempt, {})
        self.assertEqual(len(warnings), 1)
        self.assertIn("dompurify", warnings[0])
        self.assertIn("security advisories", warnings[0])

    def test_unauthorized_advisory_api_leaves_the_bump_unexempted(self):
        error = cdc.urllib.error.HTTPError(
            cdc.ADVISORY_API_URL, 403, "Forbidden", {}, None
        )

        with mock.patch.object(cdc.urllib.request, "urlopen", side_effect=error), \
                mock.patch.object(cdc, "REQUEST_RETRIES", 1):
            advisories, warnings = cdc.fetch_advisories("dompurify", cdc.time.monotonic() + 5)

        self.assertEqual(advisories, [])
        self.assertEqual(len(warnings), 1)
        self.assertIn("403", warnings[0])

    def test_malformed_advisory_payload_fails_open(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"message": "not a list"}'

        with mock.patch.object(cdc.urllib.request, "urlopen", return_value=Response()), \
                mock.patch.object(cdc, "REQUEST_RETRIES", 1):
            advisories, warnings = cdc.fetch_advisories("dompurify", cdc.time.monotonic() + 5)

        self.assertEqual(advisories, [])
        self.assertEqual(len(warnings), 1)


class TestLockfileDiffBaseVersions(unittest.TestCase):
    def test_diff_reports_the_base_version_each_bump_replaces(self):
        base = {
            "packages": {
                "": {},
                "node_modules/dompurify": {
                    "version": "3.4.11",
                    "resolved": "https://registry.npmjs.org/dompurify/-/dompurify-3.4.11.tgz",
                },
            }
        }
        head = {
            "packages": {
                "": {},
                "node_modules/dompurify": {
                    "version": "3.4.13",
                    "resolved": "https://registry.npmjs.org/dompurify/-/dompurify-3.4.13.tgz",
                },
            }
        }

        result = cdc.lockfile_diff(head, base)

        self.assertEqual(result.changed, {dep("dompurify", "3.4.13")})
        self.assertEqual(result.base_versions, {"dompurify": {"3.4.11"}})
        self.assertEqual(result.warnings, [])


if __name__ == "__main__":
    unittest.main()
