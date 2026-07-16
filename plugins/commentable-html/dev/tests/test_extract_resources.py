#!/usr/bin/env python3
"""Tests for the shipped skill-resources extractor (pkg/hooks/extract_resources.py).

Standard library only. The extractor unpacks the shipped skill-resources.zip into the skill
directory once per version, with a per-file retry/backoff so a transient Windows Defender file
lock (ERROR_ACCESS_DENIED, which the Copilot/Claude plugin installer does not retry on) does not
abort the extraction. These tests pin:

- CMH-PKG-01 first extraction unpacks every member and writes the version marker;
- CMH-PKG-02 a present marker makes a re-run a no-op (the hot path does no work);
- CMH-PKG-03 a transient lock is retried with backoff until it succeeds;
- CMH-PKG-04 an unrecoverable lock leaves NO marker so the next session retries;
- CMH-PKG-05 a stale marker from an older version is cleared and the new one written;
- CMH-PKG-06 --force re-extracts even when the current marker is present.

Run from the skill root:  python -m unittest discover -s tests -p "test_extract_resources.py" -v
"""
import importlib.util
import os
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402  shared pkg/dev split path constants

EXTRACTOR = os.path.join(_paths.HOOKS, "extract_resources.py")


def _load():
    spec = importlib.util.spec_from_file_location("extract_resources", EXTRACTOR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


extract_resources = _load()


def _make_zip(path, files):
    with zipfile.ZipFile(path, "w") as zf:
        for name, text in files.items():
            zf.writestr(name, text)


class ExtractResourcesTests(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.tmp = tempfile.mkdtemp(prefix="cmh-extract-")
        self.addCleanup(self._rmtree, self.tmp)
        self.skill = os.path.join(self.tmp, "skill")
        os.makedirs(self.skill)
        self.zip = os.path.join(self.skill, "skill-resources.zip")
        _make_zip(self.zip, {
            "tools/a.py": "print('a')\n",
            "references/b.md": "# b\n",
            "dist/c.html": "<html></html>\n",
        })

    @staticmethod
    def _rmtree(path):
        import shutil

        shutil.rmtree(path, ignore_errors=True)

    def _marker(self, version):
        return os.path.join(self.skill, ".skill-resources-" + version + ".ok")

    # CMH-PKG-01
    def test_first_extraction_unpacks_all_members_and_writes_marker(self):
        rc = extract_resources.run(self.skill, "1.0.0")
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.isfile(os.path.join(self.skill, "tools", "a.py")))
        self.assertTrue(os.path.isfile(os.path.join(self.skill, "references", "b.md")))
        self.assertTrue(os.path.isfile(os.path.join(self.skill, "dist", "c.html")))
        self.assertTrue(os.path.isfile(self._marker("1.0.0")))

    # CMH-PKG-02
    def test_present_marker_makes_rerun_a_noop(self):
        extract_resources.run(self.skill, "1.0.0")
        # Delete an extracted file; a no-op re-run must NOT recreate it (marker short-circuits).
        os.remove(os.path.join(self.skill, "tools", "a.py"))
        calls = {"n": 0}

        def _never(zf, member, dest):
            calls["n"] += 1

        rc = extract_resources.run(self.skill, "1.0.0", extract=_never)
        self.assertEqual(rc, 0)
        self.assertEqual(calls["n"], 0)
        self.assertFalse(os.path.isfile(os.path.join(self.skill, "tools", "a.py")))

    # CMH-PKG-03
    def test_transient_lock_is_retried_until_success(self):
        real = extract_resources._extract_member
        state = {"fails": 3}
        slept = []

        def _flaky(zf, member, dest):
            if member.filename.endswith("a.py") and state["fails"] > 0:
                state["fails"] -= 1
                raise PermissionError("Access is denied")
            real(zf, member, dest)

        rc = extract_resources.run(
            self.skill, "1.0.0", extract=_flaky, sleep=slept.append, backoff=0.01)
        self.assertEqual(rc, 0)
        self.assertEqual(state["fails"], 0)
        self.assertTrue(os.path.isfile(os.path.join(self.skill, "tools", "a.py")))
        self.assertGreaterEqual(len(slept), 3)  # backed off once per transient failure
        self.assertTrue(os.path.isfile(self._marker("1.0.0")))

    # CMH-PKG-04
    def test_unrecoverable_lock_leaves_no_marker(self):
        def _always_locked(zf, member, dest):
            raise PermissionError("Access is denied")

        with self.assertRaises(PermissionError):
            extract_resources.extract_all(
                self.zip, self.skill, "1.0.0", retries=2, backoff=0.001,
                sleep=lambda *_: None, extract=_always_locked)
        self.assertFalse(os.path.isfile(self._marker("1.0.0")))

    # CMH-PKG-05
    def test_stale_marker_is_cleared_and_new_one_written(self):
        # Simulate an older version already extracted.
        old = self._marker("0.9.0")
        with open(old, "w", encoding="utf-8") as fh:
            fh.write("0.9.0\n")
        rc = extract_resources.run(self.skill, "1.0.0")
        self.assertEqual(rc, 0)
        self.assertFalse(os.path.isfile(old))
        self.assertTrue(os.path.isfile(self._marker("1.0.0")))

    # CMH-PKG-06
    def test_force_reextracts_even_with_marker_present(self):
        extract_resources.run(self.skill, "1.0.0")
        os.remove(os.path.join(self.skill, "tools", "a.py"))
        rc = extract_resources.run(self.skill, "1.0.0", force=True)
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.isfile(os.path.join(self.skill, "tools", "a.py")))

    def test_missing_zip_is_a_soft_noop(self):
        os.remove(self.zip)
        rc = extract_resources.run(self.skill, "1.0.0")
        self.assertEqual(rc, 0)
        self.assertFalse(os.path.isfile(self._marker("1.0.0")))


if __name__ == "__main__":
    unittest.main()
