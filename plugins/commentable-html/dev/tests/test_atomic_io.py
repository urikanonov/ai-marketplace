#!/usr/bin/env python3
"""The shared crash-safe write helper keeps the destination's permissions (CMH-PORT-04).

`_atomic_io.atomic_write` stages the new bytes in a `mkstemp` file and swaps that inode into
place, and `mkstemp` creates 0600. Without an explicit mode step the swap silently narrows a
world-readable document to owner-only, which is a data-visibility regression an author only
notices when someone else can no longer open the file they were sent.
"""
import contextlib
import io
import os
import shutil
import stat
import sys
import tempfile
import time
import unittest
from unittest import mock

import _paths  # noqa: E402
import _io_faults  # noqa: E402
sys.path.insert(0, _paths.TOOLS)
import _atomic_io  # noqa: E402


class PreserveModeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cmh-atomic-io-")
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _file(self, name="doc.html", text="<html>original</html>"):
        p = os.path.join(self.tmp, name)
        with open(p, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        return p

    @unittest.skipIf(os.name == "nt", "POSIX permission-bit semantics")
    def test_rewriting_a_file_keeps_its_mode(self):
        p = self._file()
        os.chmod(p, 0o644)
        _atomic_io.atomic_write(p, "<html>new</html>")
        with open(p, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "<html>new</html>")
        self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o644)

    @unittest.skipIf(os.name == "nt", "POSIX permission-bit semantics")
    def test_rewriting_a_restricted_file_keeps_it_restricted(self):
        # Preservation copies the destination's mode in BOTH directions: a deliberately
        # owner-only document must not be widened either.
        p = self._file()
        os.chmod(p, 0o600)
        _atomic_io.atomic_write(p, "<html>new</html>")
        self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o600)

    @unittest.skipIf(os.name == "nt", "POSIX permission-bit semantics")
    def test_a_new_file_lands_with_the_default_creation_mode(self):
        # A destination that does not exist has no mode to copy, so it must land the way a
        # plain create would rather than keeping mkstemp's owner-only 0600.
        umask = os.umask(0o022)
        self.addCleanup(os.umask, umask)
        p = os.path.join(self.tmp, "fresh.html")
        _atomic_io.atomic_write(p, "<html>new</html>")
        self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o644)

    @unittest.skipIf(os.name == "nt", "POSIX permission-bit semantics")
    def test_a_new_file_takes_an_explicit_fallback_file_mode(self):
        # A caller that knows the SOURCE document passes it as the fallback, so writing to a new
        # path preserves the source's visibility. 0640 is neither mkstemp's 0600 nor the umask
        # default, so this cannot pass by accident on either fallback.
        source = self._file("private.html")
        os.chmod(source, 0o640)
        umask = os.umask(0o022)
        self.addCleanup(os.umask, umask)
        staged = self._file("staged.html")
        os.chmod(staged, 0o600)
        _atomic_io.preserve_mode(staged, os.path.join(self.tmp, "absent.html"), fallback=source)
        self.assertEqual(stat.S_IMODE(os.stat(staged).st_mode), 0o640)

    @unittest.skipIf(os.name == "nt", "POSIX permission-bit semantics")
    def test_an_unstattable_fallback_does_not_fall_through_to_the_umask_default(self):
        # A caller NAMED a source, so a source that cannot be read must not be quietly replaced
        # by a process default that could be wider - the staged file keeps its own mode.
        umask = os.umask(0o022)
        self.addCleanup(os.umask, umask)
        staged = self._file("staged.html")
        os.chmod(staged, 0o600)
        _atomic_io.preserve_mode(staged, os.path.join(self.tmp, "absent.html"),
                                 fallback=os.path.join(self.tmp, "gone.html"))
        self.assertEqual(stat.S_IMODE(os.stat(staged).st_mode), 0o600)

    @unittest.skipIf(os.name == "nt", "POSIX permission-bit semantics")
    def test_special_bits_are_not_copied_onto_the_staged_file(self):
        # A setuid/setgid/sticky bit belongs to the file it was set on, never to a freshly
        # staged inode owned by whoever ran the tool.
        dest = self._file("dest.html")
        os.chmod(dest, 0o4755)
        staged = self._file("staged.html")
        _atomic_io.preserve_mode(staged, dest)
        self.assertEqual(stat.S_IMODE(os.stat(staged).st_mode), 0o755)

    @unittest.skipIf(os.name == "nt", "POSIX permission-bit semantics")
    def test_an_unstattable_destination_leaves_the_staged_mode_alone(self):
        # The destination exists but its mode cannot be read. Guessing there could WIDEN a
        # deliberately private file, so the staged file keeps mkstemp's conservative 0600.
        dest = self._file("dest.html")
        staged = self._file("staged.html")
        os.chmod(staged, 0o600)
        real_stat = os.stat

        def denied(path, *args, **kwargs):
            if str(path) == dest:
                raise PermissionError(13, "denied")
            return real_stat(path, *args, **kwargs)

        with mock.patch("os.stat", denied):
            _atomic_io.preserve_mode(staged, dest)
        self.assertEqual(stat.S_IMODE(os.stat(staged).st_mode), 0o600)

    def test_a_failure_to_preserve_the_mode_is_reported_not_silent(self):
        # A silently wrong mode is exactly the class of bug this helper exists to prevent, so a
        # failed chmod says so on stderr even though it never fails the write.
        dest = self._file("dest.html")
        staged = self._file("staged.html")

        def boom(*args, **kwargs):
            raise OSError(13, "denied")

        err = io.StringIO()
        with mock.patch("os.chmod", boom), contextlib.redirect_stderr(err):
            _atomic_io.preserve_mode(staged, dest)
        self.assertIn("could not preserve the file mode", err.getvalue())

    @unittest.skipIf(os.name == "nt", "POSIX umask semantics (the Windows CRT umask tracks only the write bit)")
    def test_default_file_mode_follows_the_umask(self):
        umask = os.umask(0o077)
        self.addCleanup(os.umask, umask)
        self.assertEqual(_atomic_io.default_file_mode(), 0o600)
        os.umask(0o022)
        self.assertEqual(_atomic_io.default_file_mode(), 0o644)

    @unittest.skipIf(os.name == "nt", "POSIX umask semantics (the Windows CRT umask tracks only the write bit)")
    def test_default_file_mode_does_not_leave_the_umask_changed(self):
        # It reads the umask by setting and restoring it; a leaked umask would silently change
        # the permissions of every file the rest of the process creates.
        before = os.umask(0o027)
        self.addCleanup(os.umask, before)
        _atomic_io.default_file_mode()
        after = os.umask(0o027)
        self.assertEqual(after, 0o027)

    def test_default_file_mode_is_always_a_usable_mode(self):
        # Runs everywhere, including Windows, where the CRT umask only tracks the write bit: the
        # helper must still return a sane owner-readable/writable mode rather than raising.
        mode = _atomic_io.default_file_mode()
        self.assertIsInstance(mode, int)
        self.assertEqual(mode & ~0o777, 0)
        self.assertTrue(mode & stat.S_IRUSR)
        self.assertTrue(mode & stat.S_IWUSR)

    def test_default_file_mode_survives_a_failing_umask_restore(self):
        # The restore lives in a finally and is itself best effort: a failure there must not
        # turn a mode lookup into a crash for the caller.
        calls = []

        def flaky(mask):
            calls.append(mask)
            if len(calls) == 1:
                return 0o022  # report the current umask without changing the real one
            raise OSError("umask unavailable")

        with mock.patch("os.umask", flaky):
            self.assertEqual(_atomic_io.default_file_mode(), 0o644)
        self.assertEqual(len(calls), 2, "the restore must be attempted")

    def test_default_file_mode_fails_closed_when_the_umask_cannot_be_read(self):
        # With the umask unknown there is no honest "what a plain create would do" answer, so it
        # must fail CLOSED to owner-only rather than guessing a world-readable default.
        def boom(mask):
            raise OSError("umask unavailable")

        with mock.patch("os.umask", boom):
            self.assertEqual(_atomic_io.default_file_mode(), 0o600)

    def test_mode_handling_is_best_effort_and_never_raises(self):
        # Mode handling must never cost the write itself, so an unreadable destination or an
        # unchmod-able staged file is swallowed rather than propagated.
        missing = os.path.join(self.tmp, "gone.html")
        _atomic_io.preserve_mode(missing, os.path.join(self.tmp, "also-gone.html"))
        p = self._file()
        _atomic_io.preserve_mode(missing, p)  # destination readable, staged file absent

    @unittest.skipIf(os.name == "nt", "POSIX permission-bit semantics")
    def test_atomic_write_passes_the_fallback_through_to_a_new_destination(self):
        # The `--out` CLIs name their SOURCE document as the fallback, so writing a transformed
        # copy to a path that does not exist yet keeps the source's visibility instead of
        # landing at the (possibly wider) process default.
        source = self._file("private.html")
        os.chmod(source, 0o600)
        umask = os.umask(0o022)
        self.addCleanup(os.umask, umask)
        dest = os.path.join(self.tmp, "out.html")
        _atomic_io.atomic_write(dest, "<html>new</html>", fallback=source)
        self.assertEqual(stat.S_IMODE(os.stat(dest).st_mode), 0o600)


class ReplaceRetryTests(unittest.TestCase):
    """CMH-PORT-04: a Windows sharing violation on the swap is retried, briefly and boundedly.

    `os.replace` is the one step of the atomic write that a truncating write did not have. On
    Windows it fails with a sharing violation while another process holds the destination open
    (a virus scanner, an editor, a sync client) - a case where the old truncating write would
    have succeeded - so widening the shared writer to every tool must not turn a transient lock
    into a failed run. It must not paper over a REAL one either: the loop is bounded, so a
    genuinely locked file still fails loudly, and POSIX (which has no sharing violation) never
    waits at all.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cmh-atomic-replace-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.path = os.path.join(self.tmp, "doc.html")
        with open(self.path, "w", encoding="utf-8", newline="") as fh:
            fh.write("<html>original</html>")
        self.slept = []

    def _run(self, replace, system="nt"):
        with mock.patch.object(os, "name", system), \
                mock.patch.object(os, "replace", replace), \
                mock.patch.object(time, "sleep", self.slept.append):
            _atomic_io.atomic_write(self.path, "<html>new</html>")

    def _read(self):
        with open(self.path, encoding="utf-8") as fh:
            return fh.read()

    @staticmethod
    def _sharing_violation():
        # The attribute is set explicitly rather than passed to the constructor: `winerror` is a
        # Windows-only member, so a constructor form that carries it would not reproduce the
        # Windows failure when this test runs on the Linux CI matrix.
        exc = PermissionError(13, "the process cannot access the file")
        exc.winerror = 32
        return exc

    def _staged(self):
        return sorted(n for n in os.listdir(self.tmp) if n.startswith(".cmh-"))

    def test_a_transient_sharing_violation_is_retried_until_the_swap_lands(self):
        real = os.replace
        calls = []

        def flaky(src, dst):
            calls.append(1)
            if len(calls) < 3:
                raise self._sharing_violation()
            return real(src, dst)

        self._run(flaky)
        self.assertEqual(len(calls), 3)
        self.assertEqual(self._read(), "<html>new</html>")
        self.assertEqual(self._staged(), [])
        self.assertEqual(self.slept, [0.05, 0.1], "the wait must back off, not spin")

    def test_a_persistently_locked_destination_fails_loudly_and_leaks_nothing(self):
        calls = []

        def locked(src, dst):
            calls.append(1)
            raise self._sharing_violation()

        with self.assertRaises(PermissionError):
            self._run(locked)
        self.assertEqual(len(calls), _atomic_io._REPLACE_ATTEMPTS,
                         "the retry must be bounded, not an unbounded wait")
        # Pin the total wait too: a bounded ATTEMPT count with unbounded delays would still hang.
        self.assertEqual(self.slept, [0.05, 0.1, 0.2, 0.4])
        self.assertEqual(self._read(), "<html>original</html>")
        self.assertEqual(self._staged(), [], "a failed swap must clean up its staged file")

    def test_a_posix_permission_error_is_raised_at_once(self):
        # No sharing violation exists on POSIX: there a PermissionError is a real permission
        # problem, and retrying it would only add three quarters of a second to every failure.
        calls = []

        def denied(src, dst):
            calls.append(1)
            raise PermissionError(13, "denied")

        with self.assertRaises(PermissionError):
            self._run(denied, system="posix")
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.slept, [], "POSIX must not wait before failing")
        self.assertEqual(self._staged(), [])

    def test_a_windows_access_denied_is_not_retried(self):
        # Only a sharing/lock violation (winerror 32/33) is transient. An access-denied - a
        # read-only destination, or one that is a directory - is deterministic, so waiting only
        # delays the report the caller needs.
        calls = []

        def denied(src, dst):
            calls.append(1)
            exc = PermissionError(13, "access is denied")
            exc.winerror = 5
            raise exc

        with self.assertRaises(PermissionError):
            self._run(denied)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.slept, [])
        self.assertEqual(self._staged(), [])


class AtomicCopyTests(unittest.TestCase):
    """CMH-TOOL-22: the companion COPY is crash-safe too.

    A NonShareable document loads its runtime and stylesheet from companion files beside it.
    `shutil.copyfile` truncates the destination first, so a failed refresh left the document
    loading a half-written runtime - the same class as a truncating document write, on a file the
    user cannot re-author by hand.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cmh-atomic-copy-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.src = os.path.join(self.tmp, "src.js")
        with open(self.src, "wb") as fh:
            fh.write(b"var fresh = 1;\n")
        self.dst = os.path.join(self.tmp, "dst.js")
        with open(self.dst, "wb") as fh:
            fh.write(b"var previous = 1;\n")

    def _read(self, path):
        with open(path, "rb") as fh:
            return fh.read()

    def test_a_clean_copy_replaces_the_destination(self):
        _atomic_io.atomic_copy(self.src, self.dst)
        self.assertEqual(self._read(self.dst), b"var fresh = 1;\n")
        self.assertEqual(sorted(os.listdir(self.tmp)), ["dst.js", "src.js"])

    def test_a_failed_copy_leaves_the_destination_untouched(self):
        patcher = mock.patch.object(shutil, "copyfileobj", side_effect=IOError("simulated disk-full"))
        patcher.start()
        self.addCleanup(patcher.stop)
        with self.assertRaises(IOError):
            _atomic_io.atomic_copy(self.src, self.dst)
        self.assertEqual(self._read(self.dst), b"var previous = 1;\n")
        self.assertEqual(sorted(os.listdir(self.tmp)), ["dst.js", "src.js"],
                         "a failed copy must clean up its staged file")

    def test_a_half_written_copy_leaves_the_destination_untouched(self):
        # The same fault the document harness injects, so the copy path is proven against a
        # partial WRITE and not only against a helper that refuses to start.
        with contextlib.ExitStack() as stack:
            for target, real in (("io.open", io.open), ("builtins.open", open)):
                stack.enter_context(mock.patch(target, _io_faults.half_writing_opener(real)))
            with self.assertRaises(IOError):
                _atomic_io.atomic_copy(self.src, self.dst)
        self.assertEqual(self._read(self.dst), b"var previous = 1;\n")
        self.assertEqual(sorted(os.listdir(self.tmp)), ["dst.js", "src.js"])

    def test_a_new_destination_is_not_given_the_sources_mode_by_default(self):
        # A copy's source is usually the skill's own installed dist/, whose mode says how the
        # plugin was extracted - not what the user wants beside their document. A read-only one
        # would land a companion that can never be refreshed again.
        fresh = os.path.join(self.tmp, "fresh.js")
        _atomic_io.atomic_copy(self.src, fresh)
        self.assertEqual(self._read(fresh), b"var fresh = 1;\n")

    def test_staging_a_copy_does_not_touch_the_destination(self):
        # The companion set is staged in full before ANY of it is swapped in, so a failure part
        # way through cannot leave a document pairing a new runtime with an old stylesheet.
        staged = _atomic_io.stage_copy(self.src, self.tmp, self.dst)
        self.addCleanup(_atomic_io.quiet_remove, staged)
        self.assertEqual(self._read(self.dst), b"var previous = 1;\n")
        self.assertEqual(self._read(staged), b"var fresh = 1;\n")
        _atomic_io.commit_staged(staged, self.dst)
        self.assertEqual(self._read(self.dst), b"var fresh = 1;\n")
        self.assertEqual(sorted(os.listdir(self.tmp)), ["dst.js", "src.js"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
