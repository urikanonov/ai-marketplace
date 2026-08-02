#!/usr/bin/env python3
"""Per-module coverage gate for the split commentable-html sources.

The runtime/CSS ship as `NN-topic.{js,css}` partials under dev/assets/js and dev/assets/css. Each
partial is documented in the sibling MODULES.md with the SPEC feature-id areas it implements. This
test makes that map an enforced gate, not just a listing (GH: modularization multi-duck, ducks 7/8):

  - Every partial on disk has exactly one MODULES.md row, and every MODULES.md row names a real
    partial (no stray/undocumented module, no stale row). "Exactly one" is checked on the RAW rows,
    not the parsed map: the map is a dict, so a duplicated path silently collapses to the last row
    (GH #782 - 41-selection.js was listed twice with conflicting SPEC areas and nothing failed).
  - Every SPEC area a module claims is a REAL, TEST-BACKED area: at least one `| <AREA>-NN |` row
    exists in dev/SPEC.md AND that row references a covering test (`tests/` or `manual`), so the map
    cannot point at an empty or untested area.
"""
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402
DEV = _paths.DEV
ASSETS = _paths.ASSETS
SPEC = os.path.join(DEV, "SPEC.md")

_PART_RE = {"js": re.compile(r"^\d{2}-[a-z0-9-]+\.js$"), "css": re.compile(r"^\d{2}-[a-z0-9-]+\.css$")}
_ROW_RE = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*([^|]+?)\s*\|")


def _read(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _dir_partials(ext):
    d = os.path.join(ASSETS, ext)
    return sorted(n for n in os.listdir(d)
                  if os.path.isfile(os.path.join(d, n)) and _PART_RE[ext].match(n))


def _modules_rows(ext):
    """Parse dev/assets/<ext>/MODULES.md -> [(partial, [SPEC area, ...]), ...] in file order."""
    text = _read(os.path.join(ASSETS, ext, "MODULES.md"))
    rows = []
    for line in text.splitlines():
        m = _ROW_RE.match(line)
        if not m:
            continue
        name, areas = m.group(1), m.group(2)
        if not _PART_RE[ext].match(name):
            continue  # skip a code-span in prose that is not a partial filename
        rows.append((name, [a.strip() for a in areas.split(",") if a.strip()]))
    return rows


def _modules_map(ext):
    """Parse dev/assets/<ext>/MODULES.md -> {partial: [SPEC area, ...]}."""
    return dict(_modules_rows(ext))


class ModuleCoverageTests(unittest.TestCase):
    def _check_ext(self, ext):
        spec = _read(SPEC)
        on_disk = set(_dir_partials(ext))
        documented = _modules_map(ext)
        self.assertEqual(
            on_disk, set(documented),
            "%s MODULES.md is out of sync with the partials on disk. "
            "On disk but undocumented: %s. Documented but missing: %s."
            % (ext, sorted(on_disk - set(documented)), sorted(set(documented) - on_disk)))
        for partial, areas in documented.items():
            self.assertTrue(areas, "%s: %s lists no SPEC area" % (ext, partial))
            for area in areas:
                rows = [ln for ln in spec.splitlines() if ln.startswith("| " + area + "-")]
                self.assertTrue(
                    rows, "%s: %s maps to SPEC area %s which has no `| %s-NN |` row in SPEC.md"
                    % (ext, partial, area, area))
                self.assertTrue(
                    any(("tests/" in ln) or ("manual" in ln.lower()) for ln in rows),
                    "%s: %s maps to SPEC area %s but no %s-NN row names a covering test"
                    % (ext, partial, area, area))

    def _check_no_duplicate_rows(self, ext):
        seen = {}
        for name, areas in _modules_rows(ext):
            seen.setdefault(name, []).append(areas)
        dupes = sorted(n for n, v in seen.items() if len(v) > 1)
        self.assertEqual(
            [], dupes,
            "%s MODULES.md lists the same partial more than once: %s. The map is a dict, so a "
            "duplicate row silently wins and its SPEC areas can conflict - keep exactly one row "
            "per partial." % (ext, ", ".join("%s (%d rows)" % (n, len(seen[n])) for n in dupes)))

    def test_js_modules_map_to_real_tested_spec_areas(self):
        self._check_ext("js")

    def test_css_modules_map_to_real_tested_spec_areas(self):
        self._check_ext("css")

    def test_js_modules_map_has_no_duplicate_rows(self):
        self._check_no_duplicate_rows("js")

    def test_css_modules_map_has_no_duplicate_rows(self):
        self._check_no_duplicate_rows("css")


if __name__ == "__main__":
    unittest.main()
