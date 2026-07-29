#!/usr/bin/env python3
"""Tests for scripts/check_conflict_markers.py."""

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_MODULE_PATH = Path(__file__).with_name("check_conflict_markers.py")
_spec = importlib.util.spec_from_file_location("check_conflict_markers", _MODULE_PATH)
ccm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ccm)

CONFLICTED = (
    "# Title\n"
    "<<<<<<< HEAD\n"
    "ours\n"
    "=======\n"
    "theirs\n"
    ">>>>>>> abc1234 (a commit subject)\n"
)


class ScanTest(unittest.TestCase):
    def test_reports_every_marker_line_with_its_line_number(self):
        self.assertEqual(
            ccm.scan_text(CONFLICTED),
            [(2, "<<<<<<< HEAD"), (4, "======="), (6, ">>>>>>> abc1234 (a commit subject)")],
        )

    def test_a_setext_heading_underline_is_not_a_marker(self):
        # A Markdown H1 underline of equals signs is legitimate text; a separator counts
        # only in a file that also opens or closes a conflict.
        self.assertEqual(ccm.scan_text("Summary\n=======\n\nBody text.\n"), [])

    def test_a_horizontal_rule_of_equals_is_not_a_marker(self):
        self.assertEqual(ccm.scan_text("intro\n" + "=" * 60 + "\nmore\n"), [])

    def test_a_markdown_table_row_of_pipes_is_only_flagged_as_a_base_marker(self):
        # Seven pipes IS how git writes a diff3 base line, so it is reported; a real
        # Markdown table row has content between the pipes and is not a run.
        self.assertEqual(ccm.scan_text("| a | b |\n|---|---|\n"), [])

    def test_reports_the_diff3_base_marker_inside_a_conflict(self):
        text = "<<<<<<< HEAD\nours\n||||||| base\nbase\n=======\ntheirs\n>>>>>>> other\n"
        self.assertEqual([line for line, _ in ccm.scan_text(text)], [1, 3, 5, 7])

    def test_an_indented_marker_is_not_flagged(self):
        # Only a marker at column 0 is one git wrote; an indented copy is quoted prose.
        self.assertEqual(ccm.scan_text("    <<<<<<< HEAD\n    =======\n    >>>>>>> x\n"), [])

    def test_a_custom_conflict_marker_size_is_still_detected(self):
        # `conflict-marker-size` widens the run git writes; anchoring on exactly seven
        # would let that one attribute silently switch the guard off.
        text = "<<<<<<<<<< HEAD\nours\n==========\ntheirs\n>>>>>>>>>> other\n"
        self.assertEqual([line for line, _ in ccm.scan_text(text)], [1, 3, 5])

    def test_a_shorter_run_is_not_a_marker(self):
        self.assertEqual(ccm.scan_text("<<<<<< six\n>>>>>> six\n"), [])

    def test_crlf_and_a_bare_marker_with_no_label_are_recognized(self):
        self.assertEqual(
            [line for line, _ in ccm.scan_text("<<<<<<<\r\nours\r\n=======\r\ntheirs\r\n>>>>>>>\r\n")],
            [1, 3, 5],
        )

    def test_a_byte_order_mark_does_not_hide_a_first_line_marker(self):
        text = "\ufeff<<<<<<< HEAD\nours\n=======\ntheirs\n>>>>>>> x\n"
        self.assertEqual([line for line, _ in ccm.scan_text(text)], [1, 3, 5])

    def test_a_separator_left_behind_by_a_half_resolution_is_reported(self):
        # The start line was hand-deleted; the separator and the end marker survived.
        self.assertEqual([line for line, _ in ccm.scan_text("ours\n=======\ntheirs\n>>>>>>> x\n")],
                         [2, 4])

    def test_a_unicode_line_separator_does_not_start_a_new_line(self):
        # str.splitlines() treats U+2028 as a break; git does not, so column 0 must not move.
        self.assertEqual(ccm.scan_text("<<<<<<< HEAD\nfoo\u2028=======\n>>>>>>> x\n"),
                         [(1, "<<<<<<< HEAD"), (3, ">>>>>>> x")])

    def test_non_utf8_bytes_do_not_hide_a_marker(self):
        data = b"<<<<<<< HEAD\ncaf\xe9\n=======\ntheirs\n>>>>>>> x\n"
        self.assertEqual([line for line, _ in ccm.scan_bytes(data)], [1, 3, 5])

    def test_a_file_that_opts_out_is_not_scanned(self):
        opted_out = "<!-- check-conflict-markers: allow" + "-file -->\n" + CONFLICTED
        self.assertEqual(ccm.scan_text(opted_out), [])

    def test_merely_documenting_the_pragma_does_not_opt_a_file_out(self):
        # The pragma must be the whole line. A substring test would exempt every file that
        # explains the escape hatch - including this guard's own source and AGENTS.md.
        prose = ("A file opts out with a `check-conflict-markers: allow" + "-file` line.\n"
                 + CONFLICTED)
        self.assertEqual([line for line, _ in ccm.scan_text(prose)], [3, 5, 7])

    def test_the_guard_and_its_tests_do_not_opt_themselves_out(self):
        # Both files necessarily contain the pragma token; neither may exempt itself.
        conflict = b"\n<<<<<<< HEAD\n=======\n>>>>>>> x\n"
        for path in (_MODULE_PATH, Path(__file__)):
            self.assertTrue(ccm.scan_bytes(path.read_bytes() + conflict),
                            f"{path.name} exempts itself from the guard")

    def test_a_lone_diff3_base_marker_is_reported(self):
        # A hand resolution that deleted both bracket lines can leave this behind.
        self.assertEqual([line for line, _ in ccm.scan_text("ours\n||||||| base\ntheirs\n")], [2])

    def test_utf16_text_is_scanned_rather_than_skipped_as_binary(self):
        data = b"\xff\xfe" + CONFLICTED.encode("utf-16-le")
        self.assertEqual([line for line, _ in ccm.scan_bytes(data)], [2, 4, 6])


class ScanNamesTest(unittest.TestCase):
    def test_binary_and_unreadable_entries_are_counted_separately(self):
        reads = {"a.md": CONFLICTED.encode("utf-8"), "b.bin": b"\x00\x01\x02", "gone.md": None}
        offenders, scanned, skipped = ccm.scan_names(list(reads), reads.get)
        self.assertEqual([(name, number) for name, number, _ in offenders],
                         [("a.md", 2), ("a.md", 4), ("a.md", 6)])
        self.assertEqual((scanned, skipped[ccm.BINARY], skipped[ccm.UNREAD]), (1, 1, 1))


class MainTest(unittest.TestCase):
    def _main(self, names, reads):
        with mock.patch.object(ccm, "tracked_files", return_value=names), \
             mock.patch.object(ccm, "read_worktree", side_effect=reads.get):
            return ccm.main([])

    def test_main_passes_on_a_clean_tree(self):
        self.assertEqual(self._main(["AGENTS.md"], {"AGENTS.md": b"Summary\n=======\n\nBody.\n"}), 0)

    def test_main_fails_when_a_tracked_file_carries_markers(self):
        self.assertEqual(self._main(["spec.md"], {"spec.md": CONFLICTED.encode("utf-8")}), 1)

    def test_main_fails_rather_than_reporting_a_scan_that_read_nothing(self):
        # The subdirectory / broken-checkout shape: files were listed but none could be
        # read. A green "OK" there would be a guard that never looked.
        self.assertEqual(self._main(["a.md", "b.md"], {}), 1)

    def test_a_commit_of_only_binary_files_still_passes(self):
        # Binary is a legitimate skip, not "we could not look" - blocking a screenshot-only
        # commit is exactly what trains people to reach for --no-verify.
        self.assertEqual(self._main(["a.png"], {"a.png": b"\x89PNG\r\n\x1a\n\x00\x00"}), 0)

    def test_main_passes_when_git_is_unavailable(self):
        with mock.patch.object(ccm, "tracked_files", return_value=None):
            self.assertEqual(ccm.main([]), 0)

    def test_staged_mode_reads_the_index_not_the_working_tree(self):
        with mock.patch.object(ccm, "staged_files", return_value=["spec.md"]) as staged, \
             mock.patch.object(ccm, "read_staged_batch",
                               return_value={"spec.md": CONFLICTED.encode("utf-8")}) as batch, \
             mock.patch.object(ccm, "read_worktree", side_effect=AssertionError("read the worktree")):
            self.assertEqual(ccm.main(["--staged"]), 1)
        staged.assert_called_once_with()
        batch.assert_called_once_with(["spec.md"])


class GitInvocationTest(unittest.TestCase):
    """The listing must be root-relative and cwd-independent, or a run from a subdirectory
    lists paths that are then not found on disk and the guard passes having read nothing."""

    def _args_for(self, fn):
        with mock.patch.object(ccm.subprocess, "run") as run:
            run.return_value = mock.Mock(stdout=b"a.md\0")
            fn()
        return run.call_args[0][0]

    def test_tracked_files_runs_git_at_the_repo_root_with_full_names(self):
        args = self._args_for(ccm.tracked_files)
        self.assertEqual(args[:3], ["git", "-C", str(ccm.repo_root())])
        self.assertIn("--full-name", args)

    def test_staged_files_runs_git_at_the_repo_root_and_keeps_renames(self):
        args = self._args_for(ccm.staged_files)
        self.assertEqual(args[:3], ["git", "-C", str(ccm.repo_root())])
        # `d` excludes only deletions; an `ACM` list would silently drop a staged rename.
        self.assertIn("--diff-filter=d", args)

    def test_paths_are_decoded_without_the_platform_locale_and_deduplicated(self):
        # An unmerged path is listed once per stage; a non-ASCII path must survive.
        self.assertEqual(ccm._split_paths("a.md\0a.md\0caf\u00e9.md\0".encode("utf-8")),
                         ["a.md", "caf\u00e9.md"])


class StagedEndToEndTest(unittest.TestCase):
    """Exercise the real git plumbing against a throwaway repository.

    The rest of the suite mocks git, which cannot catch a wrong `--diff-filter` or a
    mis-parsed `cat-file --batch` frame - the two places round 2 found real defects.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        if not self._git("init", "-q", "-b", "main"):
            self.skipTest("git is not available")
        self._git("config", "user.email", "t@example.com")
        self._git("config", "user.name", "t")
        self._patch = mock.patch.object(ccm, "repo_root", return_value=self.root)
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def _git(self, *args):
        try:
            subprocess.run(["git", "-C", str(self.root)] + list(args),
                           check=True, capture_output=True)
        except (FileNotFoundError, subprocess.CalledProcessError):
            return False
        return True

    def _write(self, name, data):
        (self.root / name).write_bytes(data)

    def test_a_staged_rename_with_markers_is_caught(self):
        self._write("old.md", b"clean\n")
        self._git("add", "old.md")
        self._git("commit", "-qm", "seed")
        self._git("mv", "old.md", "new.md")
        self._write("new.md", CONFLICTED.encode("utf-8"))
        self._git("add", "new.md")
        self.assertEqual(ccm.main(["--staged"]), 1)

    def test_the_batch_reader_returns_each_staged_blob(self):
        self._write("a.md", b"alpha\n")
        self._write("b.md", CONFLICTED.encode("utf-8"))
        self._git("add", "a.md", "b.md")
        blobs = ccm.read_staged_batch(["a.md", "b.md", "absent.md"])
        self.assertEqual(blobs["a.md"], b"alpha\n")
        self.assertEqual(blobs["b.md"], CONFLICTED.encode("utf-8"))
        self.assertIsNone(blobs["absent.md"])

    def test_a_clean_staged_tree_passes(self):
        self._write("a.md", b"Summary\n=======\n\nBody.\n")
        self._git("add", "a.md")
        self.assertEqual(ccm.main(["--staged"]), 0)


if __name__ == "__main__":
    unittest.main()
