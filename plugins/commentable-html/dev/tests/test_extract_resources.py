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
import time
import unittest
import unittest.mock
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

    # CMH-PKG-03: the lock classifier retries the real Windows/Defender lock variants.
    def test_retries_winerror_and_errno_lock_variants(self):
        for exc in (OSError(13, "sharing"), PermissionError("denied")):
            with self.subTest(exc=exc):
                self._reset_skill()
                state = {"fails": 2}
                slept = []
                real = extract_resources._extract_member

                def _flaky(zf, member, dest, _exc=exc):
                    if member.filename.endswith("a.py") and state["fails"] > 0:
                        state["fails"] -= 1
                        raise _exc
                    real(zf, member, dest)

                rc = extract_resources.run(self.skill, "1.0.0", extract=_flaky,
                                           sleep=slept.append, backoff=0.001)
                self.assertEqual(rc, 0)
                self.assertEqual(state["fails"], 0)
                self.assertGreaterEqual(len(slept), 2)

    def test_winerror_lock_is_retried(self):
        err = OSError("locked")
        err.winerror = 32  # ERROR_SHARING_VIOLATION
        state = {"fails": 1}
        real = extract_resources._extract_member

        def _flaky(zf, member, dest):
            if member.filename.endswith("a.py") and state["fails"] > 0:
                state["fails"] -= 1
                raise err
            real(zf, member, dest)

        rc = extract_resources.run(self.skill, "1.0.0", extract=_flaky, sleep=lambda *_: None,
                                   backoff=0.001)
        self.assertEqual(rc, 0)
        self.assertEqual(state["fails"], 0)

    def test_non_lock_error_is_not_retried(self):
        calls = {"n": 0}

        def _boom(zf, member, dest):
            calls["n"] += 1
            raise ValueError("not a lock")

        with self.assertRaises(ValueError):
            extract_resources.extract_all(self.zip, self.skill, "1.0.0", retries=5, backoff=0.001,
                                          sleep=lambda *_: None, extract=_boom)
        self.assertEqual(calls["n"], 1)  # raised on the first attempt, no retry
        self.assertFalse(os.path.isfile(self._marker("1.0.0")))

    # CMH-PKG-08: a tampered zip with a traversing/absolute member is rejected (fail closed).
    def test_rejects_zip_slip_member(self):
        slip = os.path.join(self.skill, "slip.zip")
        _make_zip(slip, {"tools/ok.py": "x\n", "../evil.txt": "pwn\n"})
        with self.assertRaises(ValueError):
            extract_resources.extract_all(slip, self.skill, "1.0.0", sleep=lambda *_: None)
        self.assertFalse(os.path.isfile(os.path.join(os.path.dirname(self.skill), "evil.txt")))
        self.assertFalse(os.path.isfile(self._marker("1.0.0")))

    # CMH-PKG-05: a file removed in a newer version does not linger after re-extraction.
    def test_removes_files_absent_from_new_version(self):
        extract_resources.run(self.skill, "1.0.0")
        gone = os.path.join(self.skill, "tools", "gone.py")
        os.makedirs(os.path.dirname(gone), exist_ok=True)
        with open(gone, "w", encoding="utf-8") as fh:
            fh.write("stale\n")
        # New version's zip does not contain tools/gone.py.
        extract_resources.run(self.skill, "1.1.0")
        self.assertFalse(os.path.isfile(gone), "stale file from the old version must be removed")
        self.assertTrue(os.path.isfile(os.path.join(self.skill, "tools", "a.py")))
        self.assertTrue(os.path.isfile(self._marker("1.1.0")))
        self.assertFalse(os.path.isfile(self._marker("1.0.0")))

    # A fresh lock held by another session makes this session skip (no concurrent extraction).
    def test_concurrent_lock_makes_run_skip(self):
        lock = os.path.join(self.skill, extract_resources.LOCK_NAME)
        open(lock, "w").close()
        calls = {"n": 0}

        def _count(zf, member, dest):
            calls["n"] += 1

        rc = extract_resources.run(self.skill, "1.0.0", extract=_count)
        self.assertEqual(rc, 0)
        self.assertEqual(calls["n"], 0)
        self.assertFalse(os.path.isfile(self._marker("1.0.0")))

    def test_stale_lock_is_stolen(self):
        lock = os.path.join(self.skill, extract_resources.LOCK_NAME)
        open(lock, "w").close()
        old = time.time() - (extract_resources.STALE_LOCK_SECONDS + 60)
        os.utime(lock, (old, old))
        rc = extract_resources.run(self.skill, "1.0.0", sleep=lambda *_: None)
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.isfile(self._marker("1.0.0")))
        self.assertFalse(os.path.isfile(lock), "the stale lock must be released")

    # CMH-PKG-03: the zip OPEN (not just members) is retried on a transient lock.
    def test_zip_open_is_retried(self):
        real_zipfile = extract_resources.zipfile.ZipFile
        state = {"fails": 2}
        slept = []

        def _flaky_open(path, *a, **k):
            if state["fails"] > 0:
                state["fails"] -= 1
                raise PermissionError("zip is locked")
            return real_zipfile(path, *a, **k)

        with unittest.mock.patch.object(extract_resources.zipfile, "ZipFile", _flaky_open):
            extract_resources.extract_all(self.zip, self.skill, "1.0.0", backoff=0.001,
                                          sleep=slept.append)
        self.assertEqual(state["fails"], 0)
        self.assertGreaterEqual(len(slept), 2)
        self.assertTrue(os.path.isfile(self._marker("1.0.0")))

    # CMH-PKG-03/04: an exhausted time budget aborts without a marker (never hangs).
    def test_budget_exhausted_aborts_without_marker(self):
        def _always_locked(zf, member, dest):
            raise PermissionError("still locked")

        with self.assertRaises(PermissionError):
            extract_resources.extract_all(self.zip, self.skill, "1.0.0", retries=1000,
                                          backoff=0.001, sleep=lambda *_: None,
                                          extract=_always_locked, budget=0.0)
        self.assertFalse(os.path.isfile(self._marker("1.0.0")))

    # CMH-PKG-12: a failed extraction releases the lock so a later session can proceed.
    def test_lock_released_on_extraction_failure(self):
        def _boom(zf, member, dest):
            raise ValueError("not a lock")

        with self.assertRaises(ValueError):
            extract_resources.run(self.skill, "1.0.0", extract=_boom, sleep=lambda *_: None)
        self.assertFalse(os.path.isfile(os.path.join(self.skill, extract_resources.LOCK_NAME)),
                         "the lock must be released even when extraction raises")
        # A subsequent normal run proceeds and completes.
        self.assertEqual(extract_resources.run(self.skill, "1.0.0"), 0)
        self.assertTrue(os.path.isfile(self._marker("1.0.0")))

    # CMH-PKG-05: a failed upgrade leaves the previous version's files intact (staging swap).
    def test_failed_upgrade_leaves_previous_version_intact(self):
        extract_resources.run(self.skill, "1.0.0")
        old_tool = os.path.join(self.skill, "tools", "a.py")
        self.assertTrue(os.path.isfile(old_tool))

        def _always_locked(zf, member, dest):
            raise PermissionError("locked")

        with self.assertRaises(PermissionError):
            extract_resources.extract_all(self.zip, self.skill, "1.1.0", retries=1,
                                          backoff=0.001, sleep=lambda *_: None,
                                          extract=_always_locked)
        self.assertTrue(os.path.isfile(old_tool),
                        "a failed upgrade must not destroy the working previous version")
        self.assertFalse(os.path.isfile(self._marker("1.1.0")))
        self.assertFalse(os.path.isdir(os.path.join(self.skill, extract_resources.STAGING_NAME)),
                         "staging must be cleaned up after a failure")

    # CMH-PKG-05: a failure DURING the swap rolls every touched dir back to the previous version.
    def test_swap_rollback_restores_previous_version_on_mid_swap_failure(self):
        _make_zip(self.zip, {"tools/a.py": "x\n", "dist/c.html": "<html></html>\n"})
        extract_resources.run(self.skill, "1.0.0")
        sentinel = os.path.join(self.skill, "tools", "old_only.py")
        with open(sentinel, "w", encoding="utf-8") as fh:
            fh.write("old\n")
        real_replace = extract_resources.os.replace

        def _fail_moving_tools_in(src, dst, *a, **k):
            # Fail only the move of the NEW tools dir into place (entries sort dist, then tools, so
            # dist is already swapped when this fires - exercising multi-entry rollback).
            if os.path.basename(dst) == "tools" and extract_resources.STAGING_NAME in str(src):
                raise PermissionError("locked during swap")
            return real_replace(src, dst, *a, **k)

        with unittest.mock.patch.object(extract_resources.os, "replace", _fail_moving_tools_in):
            with self.assertRaises(PermissionError):
                extract_resources.extract_all(self.zip, self.skill, "1.1.0", retries=1,
                                              backoff=0.001, sleep=lambda *_: None)
        self.assertTrue(os.path.isfile(sentinel),
                        "rollback must restore the previous tools/ (with its old-only file)")
        self.assertTrue(os.path.isfile(os.path.join(self.skill, "dist", "c.html")),
                        "the already-swapped dist/ must be rolled back too")
        self.assertFalse(os.path.isfile(self._marker("1.1.0")))
        self.assertFalse(os.path.isdir(os.path.join(self.skill, extract_resources.STAGING_NAME)))
        leftovers = [n for n in os.listdir(self.skill)
                     if n.endswith(extract_resources.BACKUP_SUFFIX)]
        self.assertEqual(leftovers, [], "no backup dirs may linger after rollback")

    # A zip whose root entry collides with a control file must not overwrite it via the swap.
    def test_swap_does_not_overwrite_control_files(self):
        _make_zip(self.zip, {"tools/a.py": "x\n", "SKILL.md": "HOSTILE\n"})
        with open(os.path.join(self.skill, "SKILL.md"), "w", encoding="utf-8") as fh:
            fh.write("REAL\n")
        extract_resources.run(self.skill, "1.0.0")
        with open(os.path.join(self.skill, "SKILL.md"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "REAL\n", "the shipped SKILL.md must not be overwritten")
        self.assertTrue(os.path.isfile(os.path.join(self.skill, "tools", "a.py")))

    def test_is_swappable_rejects_case_variant_reserved_and_backup_names(self):
        staging = os.path.join(self.skill, extract_resources.STAGING_NAME)
        for name in ("skill.md", "License", "SKILL-RESOURCES.ZIP", "tools.skill-resources-old",
                     ".hidden"):
            os.makedirs(os.path.join(staging, name), exist_ok=True)
            self.assertFalse(extract_resources._is_swappable(self.skill, name),
                             "%r must not be swappable" % name)
        os.makedirs(os.path.join(staging, "tools"), exist_ok=True)
        self.assertTrue(extract_resources._is_swappable(self.skill, "tools"))

    # CMH-PKG-08: only real directories are installed - a plain file at the staging root (which a
    # tampered zip could carry) is never swapped over a control file.
    def test_is_swappable_rejects_a_plain_file(self):
        staging = os.path.join(self.skill, extract_resources.STAGING_NAME)
        os.makedirs(staging, exist_ok=True)
        with open(os.path.join(staging, "loose.txt"), "w", encoding="utf-8") as fh:
            fh.write("x\n")
        self.assertFalse(extract_resources._is_swappable(self.skill, "loose.txt"),
                         "a plain file at the staging root must not be swappable")

    # CMH-PKG-01: a zip that carries no installable directory must NOT be marked successful (else a
    # truncated/empty/wrong zip would permanently cache a broken install and never self-heal).
    def test_zip_without_installable_directories_writes_no_marker(self):
        _make_zip(self.zip, {"SKILL.md": "loose\n", "notes.txt": "x\n"})
        with self.assertRaises(RuntimeError):
            extract_resources.extract_all(self.zip, self.skill, "1.0.0", retries=1, backoff=0.001,
                                          sleep=lambda *_: None)
        self.assertFalse(os.path.isfile(self._marker("1.0.0")),
                         "an empty/incomplete zip must leave no marker so the next session retries")

    # CMH-PKG-04: the marker's own final rename retries a transient Defender lock, so a lock on the
    # just-written temp does not waste a fully-successful extraction.
    def test_write_marker_retries_transient_lock_on_final_rename(self):
        real_replace = os.replace
        state = {"fails": 2}
        slept = []
        dst = self._marker("1.0.0")

        def _flaky(src, target, *a, **k):
            if os.path.abspath(target) == os.path.abspath(dst) and state["fails"] > 0:
                state["fails"] -= 1
                err = OSError("locked")
                err.winerror = 5
                raise err
            return real_replace(src, target, *a, **k)

        with unittest.mock.patch("os.replace", _flaky):
            extract_resources._write_marker(self.skill, "1.0.0", retries=5, backoff=0.001,
                                            sleep=slept.append, deadline=time.monotonic() + 30)
        self.assertEqual(state["fails"], 0)
        self.assertTrue(os.path.isfile(dst))
        self.assertGreaterEqual(len(slept), 2)

    # CMH-PKG-03: the retryable Windows error set includes 33 (lock-pending) and 145 (dir-not-empty),
    # the NTFS delete-pending races that motivated adding them - pin them so trimming the set fails.
    def test_winerror_dir_not_empty_and_lock_pending_are_retried(self):
        for code in (33, 145):
            with self.subTest(winerror=code):
                self._reset_skill()
                err = OSError("locked")
                err.winerror = code
                state = {"fails": 1}
                real = extract_resources._extract_member

                def _flaky(zf, member, dest, _err=err, _st=state):
                    if member.filename.endswith("a.py") and _st["fails"] > 0:
                        _st["fails"] -= 1
                        raise _err
                    real(zf, member, dest)

                rc = extract_resources.run(self.skill, "1.0.0", extract=_flaky,
                                           sleep=lambda *_: None, backoff=0.001)
                self.assertEqual(rc, 0)
                self.assertEqual(state["fails"], 0)

    # CMH-PKG-08: _make_writable restores the directory execute/search bit (not S_IWRITE only), so a
    # tree that came back with cleared bits on POSIX can still be walked and removed by rmtree.
    @unittest.skipIf(os.name == "nt", "POSIX permission-bit semantics")
    def test_make_writable_restores_execute_bit_on_directories(self):
        import stat as _stat

        d = os.path.join(self.tmp, "ro")
        os.makedirs(os.path.join(d, "sub"))
        os.chmod(os.path.join(d, "sub"), 0o000)
        os.chmod(d, 0o000)
        extract_resources._make_writable(d)
        self.assertTrue(os.stat(d).st_mode & _stat.S_IXUSR, "dir search bit must be restored")
        self.assertTrue(os.stat(d).st_mode & _stat.S_IWUSR, "dir write bit must be restored")

    # CMH-PKG-05: the rollback itself retries a transient lock and restores the previous version.
    def test_rollback_survives_transient_lock_during_restore(self):
        _make_zip(self.zip, {"tools/a.py": "x\n", "dist/c.html": "<html></html>\n"})
        extract_resources.run(self.skill, "1.0.0")
        sentinel = os.path.join(self.skill, "tools", "old_only.py")
        with open(sentinel, "w", encoding="utf-8") as fh:
            fh.write("old\n")
        real_replace = extract_resources.os.replace
        state = {"restore_fails": 2}

        def _patched(src, dst, *a, **k):
            base = os.path.basename(dst)
            if base == "tools" and extract_resources.STAGING_NAME in str(src):
                raise PermissionError("move-in locked")  # force a rollback
            if base == "tools" and str(src).endswith(extract_resources.BACKUP_SUFFIX):
                if state["restore_fails"] > 0:
                    state["restore_fails"] -= 1
                    raise PermissionError("restore transiently locked")
            return real_replace(src, dst, *a, **k)

        with unittest.mock.patch.object(extract_resources.os, "replace", _patched):
            with self.assertRaises(PermissionError):
                extract_resources.extract_all(self.zip, self.skill, "1.1.0", retries=6,
                                              backoff=0.001, sleep=lambda *_: None)
        self.assertEqual(state["restore_fails"], 0, "the rollback restore must have been retried")
        self.assertTrue(os.path.isfile(sentinel),
                        "the rollback must restore the previous version despite a transient lock")

    def test_release_does_not_delete_a_foreign_pid_lock(self):
        lock, fd = extract_resources._acquire_lock(self.skill)
        self.assertIsNotNone(lock)
        os.close(fd)
        with open(lock, "wb") as fh:  # simulate a concurrent session that stole and recreated it
            fh.write(b"999999")
        extract_resources._release_lock(lock, None)
        self.assertTrue(os.path.isfile(lock), "must not delete a lock owned by another session")
        os.remove(lock)

    # A crash between rename-aside and move-in leaves a backup but no live dir; the next run restores
    # it instead of deleting the only copy.
    def test_cleanup_restores_backup_when_live_dir_is_missing(self):
        extract_resources.run(self.skill, "1.0.0")
        live = os.path.join(self.skill, "tools")
        bak = live + extract_resources.BACKUP_SUFFIX
        os.replace(live, bak)  # simulate a crash right after the rename-aside
        self.assertFalse(os.path.isdir(live))
        extract_resources._cleanup_leftovers(self.skill, 3, 0.001, lambda *_: None, None)
        self.assertTrue(os.path.isdir(live), "the backup must be restored when the live dir is gone")
        self.assertFalse(os.path.isdir(bak))
        self.assertTrue(os.path.isfile(os.path.join(live, "a.py")))

    def test_cleanup_preserves_backup_when_restore_fails(self):
        extract_resources.run(self.skill, "1.0.0")
        live = os.path.join(self.skill, "tools")
        bak = live + extract_resources.BACKUP_SUFFIX
        os.replace(live, bak)  # crash after rename-aside; live is gone, bak is the only copy
        real_replace = extract_resources.os.replace

        def _fail_restore(src, dst, *a, **k):
            if dst == live:
                raise PermissionError("restore locked")
            return real_replace(src, dst, *a, **k)

        with unittest.mock.patch.object(extract_resources.os, "replace", _fail_restore):
            extract_resources._cleanup_leftovers(self.skill, 1, 0.001, lambda *_: None, None)
        self.assertTrue(os.path.isdir(bak),
                        "a failed restore must NOT delete the backup (the only recoverable copy)")
        self.assertTrue(os.path.isfile(os.path.join(bak, "a.py")))

    def _reset_skill(self):
        import shutil

        for name in os.listdir(self.skill):
            if name == "skill-resources.zip":
                continue
            p = os.path.join(self.skill, name)
            shutil.rmtree(p, ignore_errors=True) if os.path.isdir(p) else os.remove(p)


if __name__ == "__main__":
    unittest.main()
