#!/usr/bin/env python3
"""Tests for dev/tools/check_vendor.py (CMH-DECK-07).

The vendor gate must pass on the real pristine subtree and fail closed on drift: a changed file,
an unknown extra file, a removed file, and a reintroduced denylisted file (deploy.sh) or a
.claude-plugin/ dir. Written as unittest so CI's `unittest discover` gates it.
"""
import contextlib
import io
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402  shared pkg/dev split path constants

sys.path.insert(0, _paths.DEV_TOOLS)
import check_vendor  # noqa: E402

REAL_VENDOR = check_vendor.VENDOR_DIR


def _run(vendor_dir, update=False):
    err = io.StringIO()
    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
        code = check_vendor.run(Path(vendor_dir), update=update)
    return code, err.getvalue()


class CheckVendorTests(unittest.TestCase):
    def test_real_vendor_matches_manifest(self):
        code, _ = _run(REAL_VENDOR)
        self.assertEqual(code, 0)

    def _copy(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        dst = Path(tmp) / "frontend-slides"
        shutil.copytree(REAL_VENDOR, dst)
        self.assertEqual(_run(dst)[0], 0)  # sanity: the copy is clean
        return dst

    def test_changed_file_fails(self):
        d = self._copy()
        t = d / "viewport-base.css"
        t.write_text(t.read_text(encoding="utf-8") + "\n/* tamper */\n", encoding="utf-8")
        code, err = _run(d)
        self.assertEqual(code, 1)
        self.assertIn("CHANGED viewport-base.css", err)

    def test_unknown_file_fails(self):
        d = self._copy()
        (d / "bold-template-pack" / "sneaky.js").write_text("evil()", encoding="utf-8")
        code, err = _run(d)
        self.assertEqual(code, 1)
        self.assertIn("UNKNOWN bold-template-pack/sneaky.js", err)

    def test_removed_file_fails(self):
        d = self._copy()
        os.remove(d / "STYLE_PRESETS.md")
        code, err = _run(d)
        self.assertEqual(code, 1)
        self.assertIn("MISSING STYLE_PRESETS.md", err)

    def test_reintroduced_deploy_sh_is_forbidden(self):
        d = self._copy()
        (d / "scripts" / "deploy.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
        code, err = _run(d)
        self.assertEqual(code, 1)
        self.assertIn("FORBIDDEN", err)
        self.assertIn("scripts/deploy.sh", err)

    def test_claude_plugin_dir_is_forbidden(self):
        d = self._copy()
        cp = d / ".claude-plugin"
        cp.mkdir()
        (cp / "plugin.json").write_text("{}", encoding="utf-8")
        code, err = _run(d)
        self.assertEqual(code, 1)
        self.assertIn("FORBIDDEN", err)

    def test_update_regenerates_manifest(self):
        d = self._copy()
        (d / "bold-template-pack" / "new-style.css").write_text("body{}", encoding="utf-8")
        self.assertEqual(_run(d)[0], 1)              # unknown before update
        self.assertEqual(_run(d, update=True)[0], 0)  # regenerate
        self.assertEqual(_run(d)[0], 0)              # accepted after update


    def test_no_manifest_fails(self):
        d = self._copy()
        os.remove(d / "MANIFEST.sha256")
        code, err = _run(d)
        self.assertEqual(code, 1)
        self.assertIn("no MANIFEST.sha256", err)

    def test_missing_vendor_dir_fails(self):
        code, err = _run(Path(self.__class__.__name__ + "-does-not-exist"))
        self.assertEqual(code, 1)
        self.assertIn("vendor dir missing", err)

    def test_main_cli_in_process(self):
        import contextlib
        import io
        d = self._copy()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(check_vendor.main(["--vendor-dir", str(d)]), 0)
        (d / "bold-template-pack" / "x.css").write_text("body{}", encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(check_vendor.main(["--vendor-dir", str(d)]), 1)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(check_vendor.main(["--vendor-dir", str(d), "--update"]), 0)


if __name__ == "__main__":
    unittest.main()
