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
import unittest
from unittest import mock

import _paths  # noqa: E402
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
