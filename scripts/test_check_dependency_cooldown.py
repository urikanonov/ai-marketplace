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

        changed = cdc.lockfile_diff(head, base).changed

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

        self.assertEqual(cdc.lockfile_diff(head, base).changed, set())

    def test_missing_base_lockfile_treats_all_head_entries_as_added(self):
        head = {
            "packages": {
                "node_modules/nested/node_modules/leaf": {
                    "version": "3.0.0",
                    "resolved": "https://registry.npmjs.org/leaf/-/leaf-3.0.0.tgz",
                }
            }
        }

        self.assertEqual(cdc.lockfile_diff(head, None).changed, {dep("leaf", "3.0.0")})

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

        self.assertEqual(cdc.lockfile_diff(head, base).changed, set())

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

        self.assertEqual(cdc.lockfile_diff(head, None).changed, {dep("real-package", "2.0.0")})

    def test_changed_non_registry_dependency_emits_warning_not_cooldown_pair(self):
        head = {
            "packages": {
                "node_modules/git-only": {
                    "version": "1.0.0",
                    "resolved": "git+https://example.invalid/git-only.git#abcdef",
                }
            }
        }

        result = cdc.lockfile_diff(head, None)
        changed, warnings = result.changed, result.warnings

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

    def test_same_commit_yields_an_empty_diff(self):
        with mock.patch.object(cdc, "ref_exists", return_value=True), \
                mock.patch.object(cdc, "rev_parse", return_value="abc"):
            result = cdc.diff_from_git("base", "head", "pull_request")

        self.assertEqual(result.changed, set())
        self.assertEqual(result.warnings, [])
        self.assertEqual(result.base_versions, {})


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


def advisory(ghsa_id, name, vulnerable_range, first_patched, **extra):
    entry = {
        "ghsa_id": ghsa_id,
        "vulnerabilities": [
            {
                "package": {"ecosystem": "npm", "name": name},
                "vulnerable_version_range": vulnerable_range,
                "first_patched_version": first_patched,
            }
        ],
    }
    entry.update(extra)
    return entry


def registry_entry(name, version, resolved=None):
    if resolved is None:
        basename = name.rsplit("/", 1)[-1]
        resolved = "https://registry.npmjs.org/%s/-/%s-%s.tgz" % (name, basename, version)
    return {"version": version, "resolved": resolved}


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
        self.assertIsNone(cdc.range_covers("~1.2.3", "1.2.3"))
        self.assertIsNone(cdc.range_covers("", "1.0.0"))

    def test_a_trailing_comma_does_not_void_the_range(self):
        self.assertTrue(cdc.version_matches_range(">= 1.0.0, ", "1.2.0"))

    def test_a_prerelease_is_outside_a_release_only_range(self):
        self.assertFalse(cdc.version_matches_range("< 1.0.0", "1.0.0-rc.1"))
        self.assertTrue(cdc.version_matches_range(">= 1.0.0-alpha, < 1.0.0", "1.0.0-rc.1"))

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

    def test_withdrawn_advisory_never_grants_an_exemption(self):
        advisories = [
            advisory(
                "GHSA-55q2-fjhq-7xh7",
                "dompurify",
                "<= 3.4.12",
                "3.4.13",
                withdrawn_at="2026-01-01T00:00:00Z",
            )
        ]

        self.assertIsNone(cdc.advisory_exemption("dompurify", "3.4.13", {"3.4.11"}, advisories))

    def test_version_still_vulnerable_under_a_sibling_entry_is_not_exempt(self):
        multi_line = {
            "ghsa_id": "GHSA-multi-line-0001",
            "vulnerabilities": [
                {
                    "package": {"ecosystem": "npm", "name": "pkg"},
                    "vulnerable_version_range": "< 2.5.4",
                    "first_patched_version": "2.5.4",
                },
                {
                    "package": {"ecosystem": "npm", "name": "pkg"},
                    "vulnerable_version_range": ">= 3.0.0, < 3.1.3",
                    "first_patched_version": "3.1.3",
                },
            ],
        }

        self.assertIsNone(cdc.advisory_exemption("pkg", "3.0.0", {"2.0.0"}, [multi_line]))

    def test_leap_past_the_patched_release_line_is_not_exempt(self):
        advisories = [advisory("GHSA-line-0001", "pkg", "< 1.0.1", "1.0.1")]

        self.assertIsNotNone(cdc.advisory_exemption("pkg", "1.4.0", {"1.0.0"}, advisories))
        self.assertIsNone(cdc.advisory_exemption("pkg", "99.0.0", {"1.0.0"}, advisories))

    def test_advisory_without_a_patched_version_grants_nothing(self):
        advisories = [advisory("GHSA-nofix-0001", "pkg", "< 2.0.0", None)]

        self.assertIsNone(cdc.advisory_exemption("pkg", "2.0.0", {"1.0.0"}, advisories))

    def test_malformed_advisory_entries_are_skipped_without_crashing(self):
        advisories = [
            "not-a-dict",
            {"ghsa_id": "GHSA-bad-0001", "vulnerabilities": "not-a-list"},
            {"ghsa_id": "GHSA-bad-0002", "vulnerabilities": [{"package": "not-a-dict"}]},
            {"ghsa_id": "GHSA-bad-0003", "vulnerabilities": [None]},
        ] + DOMPURIFY_ADVISORIES

        exemption = cdc.advisory_exemption("dompurify", "3.4.13", {"3.4.11"}, advisories)

        self.assertEqual(exemption.ghsa_id, "GHSA-55q2-fjhq-7xh7")

    def test_every_range_shape_the_advisory_api_publishes_is_understood(self):
        # The four shapes observed across a 200-entry sample of reviewed npm advisories.
        self.assertTrue(cdc.version_matches_range("< 4.0.0", "3.9.9"))
        self.assertTrue(cdc.version_matches_range("<= 2.70.1", "2.70.1"))
        self.assertTrue(cdc.version_matches_range(">= 3.8.0, < 4.12.34", "4.0.0"))
        self.assertTrue(cdc.version_matches_range(">= 4.4.0, <= 4.5.0", "4.5.0"))

    def test_advisory_without_a_ghsa_id_grants_nothing(self):
        advisories = [{"vulnerabilities": DOMPURIFY_ADVISORIES[0]["vulnerabilities"]}]

        self.assertIsNone(cdc.advisory_exemption("dompurify", "3.4.13", {"3.4.11"}, advisories))

    def test_an_unparseable_sibling_range_reads_as_still_vulnerable(self):
        advisories = [
            {
                "ghsa_id": "GHSA-unparseable-0001",
                "vulnerabilities": [
                    {
                        "package": {"ecosystem": "npm", "name": "pkg"},
                        "vulnerable_version_range": ">= 1.0.0, < 1.5.0",
                        "first_patched_version": "1.5.0",
                    },
                    {
                        "package": {"ecosystem": "npm", "name": "pkg"},
                        "vulnerable_version_range": "^1.5.0",
                        "first_patched_version": "1.9.0",
                    },
                ],
            }
        ]

        self.assertIsNone(cdc.advisory_exemption("pkg", "1.5.1", {"1.2.0"}, advisories))

    def test_a_zero_major_minor_is_its_own_release_line(self):
        advisories = [advisory("GHSA-zero-0001", "pkg", "< 0.1.1", "0.1.1")]

        self.assertIsNotNone(cdc.advisory_exemption("pkg", "0.1.2", {"0.1.0"}, advisories))
        self.assertIsNone(cdc.advisory_exemption("pkg", "0.9.0", {"0.1.0"}, advisories))

    def test_an_unparseable_first_patched_version_grants_nothing(self):
        advisories = [advisory("GHSA-unknown-0001", "pkg", "< 1.0.0", "unknown")]

        self.assertIsNone(cdc.advisory_exemption("pkg", "0.9.9", {"0.5.0"}, advisories))

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
        base = {dep("dompurify", "3.4.13"): {"3.4.11"}, dep("dompurify", "3.4.12"): {"3.4.11"}}
        calls = []

        def fake_fetch(name, deadline_at=None):
            calls.append(name)
            return DOMPURIFY_ADVISORIES, []

        with mock.patch.object(cdc, "fetch_advisories", side_effect=fake_fetch):
            exempt, warnings = cdc.security_exemptions(changed, base, changed)

        self.assertEqual(calls, ["dompurify"])
        self.assertEqual(warnings, [])
        self.assertEqual(sorted(d.version for d in exempt), ["3.4.12", "3.4.13"])

    def test_packages_with_no_base_version_are_never_queried(self):
        changed = {dep("brand-new", "1.0.0")}

        with mock.patch.object(cdc, "fetch_advisories", side_effect=AssertionError("queried")):
            exempt, warnings = cdc.security_exemptions(changed, {}, changed)

        self.assertEqual(exempt, {})
        self.assertEqual(warnings, [])

    def test_entry_whose_resolved_url_disagrees_is_never_queried(self):
        changed = {dep("dompurify", "3.4.13")}
        base = {dep("dompurify", "3.4.13"): {"3.4.11"}}

        with mock.patch.object(cdc, "fetch_advisories", side_effect=AssertionError("queried")):
            exempt, warnings = cdc.security_exemptions(changed, base, set())

        self.assertEqual(exempt, {})
        self.assertEqual(warnings, [])


class TestAdvisoryFetchFailOpen(unittest.TestCase):
    def test_unreachable_advisory_api_leaves_the_bump_unexempted(self):
        changed = {dep("dompurify", "3.4.13")}
        base = {dep("dompurify", "3.4.13"): {"3.4.11"}}

        with mock.patch.object(
            cdc.urllib.request, "urlopen", side_effect=cdc.urllib.error.URLError("offline")
        ), mock.patch.object(cdc, "REQUEST_RETRIES", 1):
            exempt, warnings = cdc.security_exemptions(changed, base, changed)

        self.assertEqual(exempt, {})
        self.assertEqual(len(warnings), 1)
        self.assertIn("dompurify", warnings[0])
        self.assertIn("security advisories", warnings[0])

    def test_unauthorized_advisory_api_leaves_the_bump_unexempted(self):
        error = cdc.urllib.error.HTTPError(
            cdc.ADVISORY_API_URL, 403, "Forbidden", {}, None
        )

        with mock.patch.object(cdc.urllib.request, "urlopen", side_effect=error) as urlopen, \
                mock.patch.object(cdc, "REQUEST_RETRIES", 3):
            advisories, warnings = cdc.fetch_advisories("dompurify")

        self.assertEqual(advisories, [])
        self.assertEqual(len(warnings), 1)
        self.assertIn("403", warnings[0])
        self.assertEqual(urlopen.call_count, 1)

    def test_rate_limited_advisory_api_is_retried_then_fails_open(self):
        error = cdc.urllib.error.HTTPError(cdc.ADVISORY_API_URL, 429, "Too Many", {}, None)

        with mock.patch.object(cdc.urllib.request, "urlopen", side_effect=error) as urlopen, \
                mock.patch.object(cdc, "REQUEST_RETRIES", 2), \
                mock.patch.object(cdc.time, "sleep", lambda _s: None):
            advisories, warnings = cdc.fetch_advisories("dompurify")

        self.assertEqual(advisories, [])
        self.assertEqual(len(warnings), 1)
        self.assertEqual(urlopen.call_count, 2)

    def test_truncated_response_body_fails_open_instead_of_crashing(self):
        import http.client

        class Response:
            headers = {}

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                raise http.client.IncompleteRead(b"partial")

        with mock.patch.object(cdc.urllib.request, "urlopen", return_value=Response()), \
                mock.patch.object(cdc, "REQUEST_RETRIES", 1):
            advisories, warnings = cdc.fetch_advisories("dompurify")

        self.assertEqual(advisories, [])
        self.assertEqual(len(warnings), 1)

    def test_malformed_advisory_payload_fails_open(self):
        class Response:
            headers = {}

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"message": "not a list"}'

        with mock.patch.object(cdc.urllib.request, "urlopen", return_value=Response()), \
                mock.patch.object(cdc, "REQUEST_RETRIES", 1):
            advisories, warnings = cdc.fetch_advisories("dompurify")

        self.assertEqual(advisories, [])
        self.assertEqual(len(warnings), 1)

    def test_no_authorization_header_is_ever_sent(self):
        captured = {}

        class Response:
            headers = {}

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b"[]"

        def fake_urlopen(request, timeout=None):
            captured["headers"] = dict(request.headers)
            captured["url"] = request.full_url
            return Response()

        with mock.patch.dict(cdc.os.environ, {"GITHUB_TOKEN": "should-not-be-used"}), \
                mock.patch.object(cdc.urllib.request, "urlopen", side_effect=fake_urlopen):
            cdc.fetch_advisories("dompurify")

        self.assertNotIn("Authorization", captured["headers"])
        self.assertTrue(captured["url"].startswith(cdc.ADVISORY_API_URL))
        self.assertIn("is_withdrawn=false", captured["url"])

    def test_advisories_beyond_the_first_page_are_followed(self):
        pages = {}

        class Response:
            def __init__(self, body, link):
                self._body = body
                self.headers = {"Link": link} if link else {}

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return self._body

        second = cdc.ADVISORY_API_URL + "?page=2"

        def fake_urlopen(request, timeout=None):
            pages.setdefault("urls", []).append(request.full_url)
            if request.full_url == second:
                return Response(b'[{"ghsa_id": "GHSA-page-two"}]', None)
            return Response(b"[]", '<%s>; rel="next"' % second)

        with mock.patch.object(cdc.urllib.request, "urlopen", side_effect=fake_urlopen):
            advisories, warnings = cdc.fetch_advisories("dompurify")

        self.assertEqual(warnings, [])
        self.assertEqual([a["ghsa_id"] for a in advisories], ["GHSA-page-two"])
        self.assertEqual(len(pages["urls"]), 2)

    def test_a_next_link_to_another_host_is_not_followed(self):
        class Response:
            def __init__(self, body, link):
                self._body = body
                self.headers = {"Link": link} if link else {}

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return self._body

        for link in (
            "https://evil.example/advisories",
            "https://api.github.com.evil.example/advisories",
            "https://api.github.com/advisories/../other",
            "https://user@api.github.com/advisories",
        ):
            calls = []

            def fake_urlopen(request, timeout=None, _link=link):
                calls.append(request.full_url)
                return Response(b"[]", '<%s>; rel="next"' % _link)

            with mock.patch.object(cdc.urllib.request, "urlopen", side_effect=fake_urlopen):
                advisories, warnings = cdc.fetch_advisories("dompurify")

            self.assertEqual(advisories, [], link)
            self.assertEqual(warnings, [], link)
            self.assertEqual(len(calls), 1, link)

    def test_a_failure_after_the_first_page_discards_the_partial_list(self):
        second = cdc.ADVISORY_API_URL + "?page=2"

        class Response:
            def __init__(self, body, link):
                self._body = body
                self.headers = {"Link": link} if link else {}

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return self._body

        def fake_urlopen(request, timeout=None):
            if request.full_url == second:
                raise cdc.urllib.error.HTTPError(second, 404, "Not Found", {}, None)
            return Response(b'[{"ghsa_id": "GHSA-page-one"}]', '<%s>; rel="next"' % second)

        with mock.patch.object(cdc.urllib.request, "urlopen", side_effect=fake_urlopen):
            advisories, warnings = cdc.fetch_advisories("dompurify")

        self.assertEqual(advisories, [])
        self.assertEqual(len(warnings), 1)

    def test_hitting_the_page_cap_warns_that_the_list_is_truncated(self):
        class Response:
            headers = {"Link": '<%s?page=n>; rel="next"' % cdc.ADVISORY_API_URL}

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b"[]"

        with mock.patch.object(cdc.urllib.request, "urlopen", return_value=Response()) as urlopen:
            advisories, warnings = cdc.fetch_advisories("dompurify")

        self.assertEqual(advisories, [])
        self.assertEqual(urlopen.call_count, cdc.ADVISORY_MAX_PAGES)
        self.assertEqual(len(warnings), 1)
        self.assertIn("truncated", warnings[0])

    def test_the_lookup_phase_stops_once_its_time_budget_is_spent(self):
        changed = {dep("aaa", "1.0.1"), dep("bbb", "1.0.1")}
        base = {d: {"1.0.0"} for d in changed}
        calls = []
        clock = iter([0, 0, cdc.GLOBAL_DEADLINE_SECONDS + 1])

        def fake_fetch(name, deadline_at=None):
            calls.append(name)
            return [], []

        with mock.patch.object(cdc, "fetch_advisories", side_effect=fake_fetch), \
                mock.patch.object(cdc.time, "monotonic", side_effect=lambda: next(clock)):
            exempt, warnings = cdc.security_exemptions(changed, base, changed)

        self.assertEqual(exempt, {})
        self.assertEqual(calls, ["aaa"])
        self.assertEqual(len(warnings), 1)
        self.assertIn("time budget", warnings[0])


class TestLockfileDiffBaseVersions(unittest.TestCase):
    def test_diff_reports_the_base_version_each_bump_replaces(self):
        base = {"packages": {"": {}, "node_modules/dompurify": registry_entry("dompurify", "3.4.11")}}
        head = {"packages": {"": {}, "node_modules/dompurify": registry_entry("dompurify", "3.4.13")}}

        result = cdc.lockfile_diff(head, base)

        self.assertEqual(result.changed, {dep("dompurify", "3.4.13")})
        self.assertEqual(result.base_versions, {dep("dompurify", "3.4.13"): {"3.4.11"}})
        self.assertEqual(result.attested, {dep("dompurify", "3.4.13")})
        self.assertEqual(result.warnings, [])

    def test_a_base_version_head_still_pins_is_not_reported_as_replaced(self):
        base = {
            "packages": {
                "": {},
                "node_modules/d3-shape": registry_entry("d3-shape", "1.3.7"),
                "node_modules/x/node_modules/d3-shape": registry_entry("d3-shape", "3.2.0"),
            }
        }
        head = {
            "packages": {
                "": {},
                "node_modules/d3-shape": registry_entry("d3-shape", "1.3.7"),
                "node_modules/x/node_modules/d3-shape": registry_entry("d3-shape", "3.3.0"),
            }
        }

        result = cdc.lockfile_diff(head, base)

        self.assertEqual(result.changed, {dep("d3-shape", "3.3.0")})
        self.assertEqual(result.base_versions, {dep("d3-shape", "3.3.0"): {"3.2.0"}})

    def test_base_versions_do_not_leak_across_lockfiles(self):
        vulnerable = {"packages": {"": {}, "node_modules/pkg": registry_entry("pkg", "1.0.0")}}
        other = {"packages": {"": {}, "node_modules/pkg": registry_entry("pkg", "9.9.9")}}

        merged = cdc.LockfileDiff()
        merged.merge(cdc.lockfile_diff(vulnerable, vulnerable))
        merged.merge(cdc.lockfile_diff(other, {"packages": {"": {}}}))

        self.assertEqual(merged.changed, {dep("pkg", "9.9.9")})
        self.assertEqual(merged.base_versions, {})

    def test_an_entry_whose_resolved_url_names_another_package_is_not_attested(self):
        base = {"packages": {"": {}, "node_modules/mermaid": registry_entry("mermaid", "11.16.0")}}
        head = {
            "packages": {
                "": {},
                "node_modules/mermaid": {
                    "name": "mermaid",
                    "version": "11.16.1",
                    "resolved": "https://registry.npmjs.org/evil-pkg/-/evil-pkg-1.0.0.tgz",
                },
            }
        }

        result = cdc.lockfile_diff(head, base)

        self.assertEqual(result.changed, {dep("mermaid", "11.16.1")})
        self.assertEqual(result.attested, set())

    def test_a_scope_swap_that_keeps_the_basename_is_not_attested(self):
        head = {
            "packages": {
                "": {},
                "node_modules/mermaid": {
                    "name": "mermaid",
                    "version": "11.16.1",
                    "resolved": "https://registry.npmjs.org/@evil/mermaid/-/mermaid-11.16.1.tgz",
                },
            }
        }

        result = cdc.lockfile_diff(head, {"packages": {"": {}}})

        self.assertEqual(result.changed, {dep("mermaid", "11.16.1")})
        self.assertEqual(result.attested, set())

    def test_a_resolved_url_with_a_query_or_extra_segments_is_not_attested(self):
        for resolved in (
            "https://registry.npmjs.org/pkg/-/pkg-1.0.0.tgz?token=abc",
            "https://registry.npmjs.org/evil/pkg/-/pkg-1.0.0.tgz",
            "http://registry.npmjs.org/pkg/-/pkg-1.0.0.tgz",
            "https://user@registry.npmjs.org/pkg/-/pkg-1.0.0.tgz",
        ):
            head = {
                "packages": {
                    "": {},
                    "node_modules/pkg": {"version": "1.0.0", "resolved": resolved},
                }
            }

            self.assertEqual(cdc.lockfile_diff(head, {"packages": {"": {}}}).attested, set(), resolved)

    def test_simultaneous_bumps_do_not_borrow_each_others_base_versions(self):
        base = {
            "packages": {
                "": {},
                "node_modules/pkg": registry_entry("pkg", "1.0.0"),
                "node_modules/x/node_modules/pkg": registry_entry("pkg", "1.5.0"),
            }
        }
        head = {
            "packages": {
                "": {},
                "node_modules/pkg": registry_entry("pkg", "1.0.1"),
                "node_modules/x/node_modules/pkg": registry_entry("pkg", "1.6.0"),
            }
        }

        result = cdc.lockfile_diff(head, base)

        self.assertEqual(
            result.base_versions,
            {dep("pkg", "1.0.1"): {"1.0.0"}, dep("pkg", "1.6.0"): {"1.5.0"}},
        )

    def test_lineage_follows_the_lockfile_slot_not_the_version_order(self):
        # The slot that held the vulnerable 1.0.0 becomes 1.7.0; the ordinary bump is 1.5.0 -> 1.6.0.
        base = {
            "packages": {
                "": {},
                "node_modules/pkg": registry_entry("pkg", "1.0.0"),
                "node_modules/x/node_modules/pkg": registry_entry("pkg", "1.5.0"),
            }
        }
        head = {
            "packages": {
                "": {},
                "node_modules/pkg": registry_entry("pkg", "1.7.0"),
                "node_modules/x/node_modules/pkg": registry_entry("pkg", "1.6.0"),
            }
        }

        result = cdc.lockfile_diff(head, base)

        self.assertEqual(
            result.base_versions,
            {dep("pkg", "1.7.0"): {"1.0.0"}, dep("pkg", "1.6.0"): {"1.5.0"}},
        )

    def test_a_rehoisted_entry_has_no_lineage_and_earns_no_exemption(self):
        base = {"packages": {"": {}, "node_modules/x/node_modules/pkg": registry_entry("pkg", "1.0.0")}}
        head = {"packages": {"": {}, "node_modules/pkg": registry_entry("pkg", "1.0.1")}}

        result = cdc.lockfile_diff(head, base)

        self.assertEqual(result.changed, {dep("pkg", "1.0.1")})
        self.assertEqual(result.base_versions, {})

    def test_one_unattested_occurrence_rejects_the_whole_identity(self):
        head = {
            "packages": {
                "": {},
                "node_modules/pkg": registry_entry("pkg", "1.0.1"),
                "node_modules/x/node_modules/pkg": {
                    "name": "pkg",
                    "version": "1.0.1",
                    "resolved": "https://registry.npmjs.org/@evil/pkg/-/pkg-1.0.1.tgz",
                },
            }
        }

        result = cdc.lockfile_diff(head, {"packages": {"": {}}})

        self.assertEqual(result.attested_versions(), set())

    def test_a_rejection_in_one_lockfile_survives_the_merge(self):
        good = cdc.LockfileDiff(attested={dep("pkg", "1.0.1")})
        bad = cdc.LockfileDiff(rejected={dep("pkg", "1.0.1")})

        self.assertEqual(cdc.LockfileDiff().merge(good).merge(bad).attested_versions(), set())
        self.assertEqual(cdc.LockfileDiff().merge(bad).merge(good).attested_versions(), set())

    def test_a_scoped_package_is_attested(self):
        head = {
            "packages": {
                "": {},
                "node_modules/@scope/pkg": registry_entry("@scope/pkg", "1.2.3"),
            }
        }

        result = cdc.lockfile_diff(head, {"packages": {"": {}}})

        self.assertEqual(result.attested, {dep("@scope/pkg", "1.2.3")})


class TestDiffFromGit(unittest.TestCase):
    def _run(self, lockfiles):
        def fake_lockfile_at(ref, path):
            return lockfiles[path]["head" if ref == "head" else "base"]

        with mock.patch.object(cdc, "ref_exists", return_value=True), \
                mock.patch.object(cdc, "rev_parse", side_effect=lambda ref: ref), \
                mock.patch.object(cdc, "merge_base", return_value="base"), \
                mock.patch.object(cdc, "discover_lockfiles", return_value=tuple(lockfiles)), \
                mock.patch.object(cdc, "lockfile_at", side_effect=fake_lockfile_at):
            return cdc.diff_from_git("base", "head", "pull_request")

    def test_a_version_another_lockfile_still_pins_closes_no_alert(self):
        bumped = {
            "base": {"packages": {"": {}, "node_modules/pkg": registry_entry("pkg", "1.0.0")}},
            "head": {"packages": {"": {}, "node_modules/pkg": registry_entry("pkg", "1.5.0")}},
        }
        untouched = {
            "base": {"packages": {"": {}, "node_modules/pkg": registry_entry("pkg", "1.0.0")}},
            "head": {"packages": {"": {}, "node_modules/pkg": registry_entry("pkg", "1.0.0")}},
        }

        result = self._run({"a/package-lock.json": bumped, "b/package-lock.json": untouched})

        self.assertEqual(result.changed, {dep("pkg", "1.5.0")})
        self.assertEqual(result.base_versions, {})

    def test_a_bump_no_other_lockfile_holds_back_keeps_its_base_version(self):
        bumped = {
            "base": {"packages": {"": {}, "node_modules/pkg": registry_entry("pkg", "1.0.0")}},
            "head": {"packages": {"": {}, "node_modules/pkg": registry_entry("pkg", "1.5.0")}},
        }

        result = self._run({"a/package-lock.json": bumped})

        self.assertEqual(result.base_versions, {dep("pkg", "1.5.0"): {"1.0.0"}})


class TestMainWiring(unittest.TestCase):
    def _diff(self, changed, base_versions):
        return cdc.LockfileDiff(
            changed=set(changed), base_versions=dict(base_versions), attested=set(changed)
        )

    def test_a_clean_run_never_looks_up_an_advisory(self):
        changed = {dep("pkg", "2.0.0")}
        old = datetime.now(timezone.utc) - timedelta(days=90)

        with mock.patch.object(cdc, "diff_from_git", return_value=self._diff(changed, {})), \
                mock.patch.object(cdc, "fetch_publish_times", return_value=({dep("pkg", "2.0.0"): old}, [])), \
                mock.patch.object(cdc, "fetch_advisories", side_effect=AssertionError("queried")):
            self.assertEqual(cdc.main(["--base", "a", "--head", "b"]), 0)

    def test_a_fresh_security_patch_passes_and_a_fresh_ordinary_bump_fails(self):
        fresh = datetime.now(timezone.utc) - timedelta(days=1)
        patched = dep("dompurify", "3.4.13")
        ordinary = dep("left-pad", "9.9.9")
        diff = self._diff({patched, ordinary}, {patched: {"3.4.11"}})
        times = {patched: fresh, ordinary: fresh}

        def fake_fetch(name, deadline_at=None):
            return DOMPURIFY_ADVISORIES if name == "dompurify" else [], []

        with mock.patch.object(cdc, "diff_from_git", return_value=diff), \
                mock.patch.object(cdc, "fetch_publish_times", return_value=(times, [])), \
                mock.patch.object(cdc, "fetch_advisories", side_effect=fake_fetch):
            self.assertEqual(cdc.main(["--base", "a", "--head", "b"]), 1)

        diff = self._diff({patched}, {patched: {"3.4.11"}})
        with mock.patch.object(cdc, "diff_from_git", return_value=diff), \
                mock.patch.object(cdc, "fetch_publish_times", return_value=({patched: fresh}, [])), \
                mock.patch.object(cdc, "fetch_advisories", side_effect=fake_fetch):
            self.assertEqual(cdc.main(["--base", "a", "--head", "b"]), 0)


if __name__ == "__main__":
    unittest.main()
