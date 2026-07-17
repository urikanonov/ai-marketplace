#!/usr/bin/env python3
"""Tests for dev/tools/check_theme_sources.py (CMH-DECK-THEME-04).

The staleness gate must PASS on the real shipped presets (every preset acknowledges the currently
vendored frontend-slides commit) and FAIL closed on each unacknowledged state: a missing adaptedFrom,
a missing sourceCommit, and a sourceCommit that lags the vendored commit. Acknowledging an upstream
refresh (setting sourceCommit to the new vendored commit) must clear the failure. Written as unittest
so CI's `unittest discover` gates it.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402  shared pkg/dev split path constants

sys.path.insert(0, _paths.DEV_TOOLS)
import check_theme_sources as cts  # noqa: E402

REAL_COMMIT = cts.vendored_commit()


def _write_upstream(dirpath, commit):
    p = Path(dirpath) / "UPSTREAM.md"
    p.write_text("- Vendored commit: `%s`\n" % commit, encoding="utf-8")
    return p


def _write_preset(dirpath, name, **overrides):
    data = {
        "label": name,
        "adaptedFrom": "frontend-slides STYLE_PRESETS.md 'X' (Zara Zhang, MIT).",
        "sourceCommit": "0123456789abcdef0123456789abcdef01234567",
        "tokens": {"--slide-bg": "#101014"},
    }
    data.update(overrides)
    p = Path(dirpath) / (name + ".theme.json")
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return p


class CheckThemeSourcesTests(unittest.TestCase):
    def test_real_presets_pass(self):
        # Guard against the gate silently passing because the vendored commit could not be parsed.
        self.assertTrue(bool(REAL_COMMIT), "must be able to parse the vendored commit from UPSTREAM.md")
        self.assertEqual(cts.check(), [])

    def _bench(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(_rmtree, tmp)
        themes = Path(tmp) / "themes"
        themes.mkdir()
        commit = "abcabcabcabcabcabcabcabcabcabcabcabcabca"
        up = _write_upstream(tmp, commit)
        return themes, commit, up

    def test_matching_source_commit_passes(self):
        themes, commit, up = self._bench()
        _write_preset(themes, "ok", sourceCommit=commit)
        self.assertEqual(cts.check(themes, up), [])

    def test_missing_adapted_from_fails(self):
        themes, commit, up = self._bench()
        _write_preset(themes, "noattr", sourceCommit=commit, adaptedFrom="")
        errors = cts.check(themes, up)
        self.assertTrue(any("adaptedFrom" in e for e in errors))

    def test_missing_source_commit_fails(self):
        themes, commit, up = self._bench()
        _write_preset(themes, "nocommit", sourceCommit="")
        errors = cts.check(themes, up)
        self.assertTrue(any("sourceCommit" in e and "missing" in e for e in errors))

    def test_stale_source_commit_is_an_unacknowledged_change_and_fails(self):
        themes, commit, up = self._bench()
        _write_preset(themes, "stale", sourceCommit="0000000000000000000000000000000000000000")
        errors = cts.check(themes, up)
        self.assertTrue(any("does not match" in e for e in errors))

    def test_acknowledging_the_refresh_clears_the_failure(self):
        themes, commit, up = self._bench()
        preset = _write_preset(themes, "ack", sourceCommit="1111111111111111111111111111111111111111")
        self.assertTrue(cts.check(themes, up))  # stale -> fails
        data = json.loads(preset.read_text(encoding="utf-8"))
        data["sourceCommit"] = commit  # maintainer records "reviewed against the new commit"
        preset.write_text(json.dumps(data, indent=2), encoding="utf-8")
        self.assertEqual(cts.check(themes, up), [])

    def test_invalid_json_fails(self):
        themes, commit, up = self._bench()
        (themes / "broken.theme.json").write_text("{not json", encoding="utf-8")
        errors = cts.check(themes, up)
        self.assertTrue(any("invalid JSON" in e for e in errors))

    def test_unparseable_upstream_commit_fails_closed(self):
        # If the reference commit cannot be read, the gate must FAIL (not silently pass a stale preset).
        themes, commit, up = self._bench()
        _write_preset(themes, "stale", sourceCommit="0000000000000000000000000000000000000000")
        up.write_text("no vendored commit line here\n", encoding="utf-8")
        self.assertIsNone(cts.vendored_commit(up))
        errors = cts.check(themes, up)
        self.assertTrue(errors)
        self.assertTrue(any("could not determine the vendored" in e for e in errors))

    def test_cli_returns_zero_on_real_presets(self):
        self.assertEqual(cts.main([]), 0)


def _rmtree(path):
    import shutil
    shutil.rmtree(path, ignore_errors=True)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
