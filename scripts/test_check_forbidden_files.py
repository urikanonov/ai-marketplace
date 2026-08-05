#!/usr/bin/env python3
"""Tests for scripts/check_forbidden_files.py.

Run from the repo root:
    python -m unittest discover -s scripts -p "test_*.py"
"""

import contextlib
import importlib.util
import io
import os
import re
import subprocess
import sys
import tempfile
import unicodedata
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _git_test_env import clean_git_env  # noqa: E402

_MODULE_PATH = Path(__file__).with_name("check_forbidden_files.py")
_spec = importlib.util.spec_from_file_location("check_forbidden_files", _MODULE_PATH)
cff = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cff)


class IsForbiddenTest(unittest.TestCase):
    def test_flags_secret_bearing_files(self):
        for path in [
            ".env",
            ".env.local",
            "config/prod.pem",
            "deep/nested/server.key",
            "certs/cert.pfx",
            "keystore.p12",
            "home/.ssh/id_rsa",
            "id_ed25519",
            "vendor/keys/id_ecdsa",
            "SERVER.PEM",
            "config/PROD.KEY",
            "ID_RSA",
            "backup.PFX",
            ".envrc",
            "release.env",
            ".netrc",
            ".npmrc",
            "auth/credentials.json",
            "credentials.prod.json",
            "service-account.json",
            "gcp/service-account.ci.json",
            "keys/apns.p8",
            "wallet.kdb",
        ]:
            self.assertTrue(cff.is_forbidden(path), path)

    def test_allows_safe_files(self):
        for path in [
            ".env.example",
            ".env.sample",
            "config/.env.template",
            "config/.ENV.EXAMPLE",
            "README.md",
            "scripts/validate_markdown.py",
            "docs/public.pem.example",
            "notes.txt",
        ]:
            self.assertFalse(cff.is_forbidden(path), path)


class IsScratchArtifactTest(unittest.TestCase):
    """A committed diff dump is how `changes.diff` (180KB, unreferenced) reached main.

    The root-anchored .gitignore block only swallows scratch at the REPO ROOT, so a dump
    written into a subdirectory - which is where an agent's cwd usually is - sails past it
    and gets swept up by `git add -A`.
    """

    def test_flags_scratch_dumps_anywhere_in_the_tree(self):
        for path in [
            "changes.diff",
            ".github/skills/demo-video/changes.diff",
            "plugins/commentable-html/dev/tmp_diff.patch",
            "deep/nested/OUT.DIFF",
        ]:
            with self.subTest(path=path):
                self.assertTrue(cff.is_scratch_artifact(path), f"{path} should be refused")

    def test_leaves_real_files_alone(self):
        for path in [
            "scripts/check_forbidden_files.py",
            "docs/diffing.md",
            "plugins/commentable-html/dev/assets/js/30-diff.js",
            "site/pages/index.html",
        ]:
            with self.subTest(path=path):
                self.assertFalse(cff.is_scratch_artifact(path), f"{path} should be allowed")

    def test_the_repo_tracks_no_scratch_dumps(self):
        files = cff.tracked_files()
        if files is None:
            self.skipTest("git unavailable")
        offenders = [p for p in files if cff.is_scratch_artifact(p)]
        self.assertEqual(offenders, [], f"scratch dumps are tracked: {offenders}")


class UnderscoreScratchTest(unittest.TestCase):
    """An `_`-prefixed dump is scratch WHEREVER it lands, and the rule is an ALLOWLIST.

    `_t1.txt`, `_t2.txt` and `_review_diff1.txt` reached main this way (#917), and a review agent
    left `_diff_record.txt`, `_diff_script.txt` and `_wip_diff.txt` behind while #927 was in
    flight - caught by eye, not by a gate. The root allowlist covers the root, but an agent's cwd
    is usually a SUBDIRECTORY, where nothing refused these shapes: the tree-wide rule only knew
    `*.diff` / `*.patch`. Listing dump extensions instead would repeat the mistake the root rule
    already learned - a denylist cannot keep up with what the next probe is named - so an
    `_`-prefixed file is scratch unless it wears a SOURCE extension.
    """

    def test_flags_an_underscore_dump_in_a_subdirectory(self):
        for path in [
            "plugins/commentable-html/dev/_wip_diff.txt",
            "plugins/commentable-html/dev/tests/_diff_record.txt",
            "scripts/_t1.json",
            "site/pages/_DIFF_SCRIPT.TXT",
            ".github/skills/demo-video/_review_diff1.txt",
            "docs/_notes.md",
            "scripts/_out.csv",
            "site/src/_probe.html",
            "scripts/_wip",
        ]:
            with self.subTest(path=path):
                self.assertTrue(cff.is_scratch_artifact(path), f"{path} should be refused")

    def test_leaves_underscore_prefixed_private_modules_alone(self):
        for path in [
            "scripts/_git_test_env.py",
            "scripts/_build_site_data_test_helpers.py",
            "plugins/commentable-html/dev/tests/_paths.py",
            "plugins/commentable-html/dev/tests/_shard.mjs",
            "plugins/commentable-html/dev/skill/tools/_toolpath.py",
            "plugins/commentable-html/dev/skill/tools/validate/checks/__init__.py",
        ]:
            with self.subTest(path=path):
                self.assertFalse(cff.is_scratch_artifact(path), f"{path} should be allowed")

    def test_a_backslash_does_not_hide_an_underscore_dump(self):
        """A git index path separates on `/` only, so a backslash stays part of the NAME."""
        self.assertTrue(cff.is_scratch_artifact("scripts/_dump\\out.txt"))
        self.assertTrue(cff.is_scratch_artifact("scripts/_wip\\notes.txt"))

    def test_a_source_suffix_cannot_be_worn_on_top_of_a_dump(self):
        """`_t1.txt.py` is a dump wearing a module's clothes; `__init__.py` is a real module."""
        for path in ["scripts/_t1.txt.py", "scripts/_wip.diff.py", "docs/_notes.md.js"]:
            with self.subTest(path=path):
                self.assertTrue(cff.is_scratch_artifact(path), f"{path} should be refused")
        for path in ["scripts/_paths.py", "scripts/__init__.py", "scripts/_types.d.ts"]:
            with self.subTest(path=path):
                self.assertFalse(cff.is_scratch_artifact(path), f"{path} should be allowed")

    def test_an_underscore_directory_cannot_shelter_a_dump(self):
        """The basename is not the whole story: `_scratch/` one level down is the same dump."""
        for path in ["scripts/_scratch/wip.txt", "plugins/commentable-html/dev/_probe/out.json"]:
            with self.subTest(path=path):
                self.assertTrue(cff.is_scratch_artifact(path), f"{path} should be refused")

    def test_an_underscore_directory_may_hold_a_private_package(self):
        """A private PACKAGE is the same convention as a private module, so source stays source."""
        for path in ["scripts/_helpers/__init__.py", "scripts/_helpers/util.py"]:
            with self.subTest(path=path):
                self.assertFalse(cff.is_scratch_artifact(path), f"{path} should be allowed")

    def test_the_source_suffixes_are_well_formed(self):
        """An empty entry would make `endswith` true for every name and fail the rule OPEN."""
        for suffix in cff.UNDERSCORE_SOURCE_SUFFIXES:
            with self.subTest(suffix=suffix):
                self.assertTrue(suffix.startswith("."), suffix)
                self.assertGreater(len(suffix), 1, suffix)
                self.assertEqual(suffix, suffix.lower(), suffix)

    def test_every_tracked_underscore_file_is_allowed(self):
        """The allowlist is checked against the real tree, so a new source kind cannot be missed."""
        files = cff.tracked_files()
        if files is None:
            self.skipTest("git unavailable")
        underscored = [p for p in files if any(seg.startswith("_") for seg in p.split("/"))]
        self.assertTrue(underscored, "expected the repo to track `_`-prefixed private modules")
        offenders = sorted(p for p in underscored if cff.is_scratch_artifact(p))
        self.assertEqual(offenders, [], f"legitimate `_`-prefixed sources are refused: {offenders}")


class GitignoreRootBlockTest(unittest.TestCase):
    """The root-anchored .gitignore block is the FIRST line of defence, and it was unpinned.

    The guard refuses a dump that is already TRACKED; the ignore block is what stops `git add -A`
    staging one in the first place. Nothing asserted that `/_*` is in that block, so narrowing or
    dropping it would leave the `_t1.txt` shape stageable again with every test still green.

    Two `git check-ignore` details decide whether these assertions mean anything. It consults the
    INDEX by default and calls any TRACKED path "not ignored" whatever the patterns say, so a
    negative assertion without `--no-index` is vacuous - it would stay green even if the block
    were widened to a bare `_*` that swallowed every private module. And it reports only the LAST
    matching pattern, so asserting the exit status alone would not notice `/_*` being deleted
    while a broader neighbour still matched; the pattern itself has to be asserted.
    """

    @classmethod
    def setUpClass(cls):
        # Resolved ONCE, and through clean_git_env: cff.repo_root() inherits os.environ, so under
        # a git hook (which exports GIT_DIR) it would resolve `scripts/` rather than the repo.
        result = subprocess.run(
            ["git", "-C", str(Path(cff.__file__).resolve().parent), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            env=clean_git_env(),
        )
        cls._root = result.stdout.strip() if result.returncode == 0 else ""

    def _repo_root(self):
        if not self._root:
            self.skipTest("git unavailable")
        expected = Path(cff.__file__).resolve().parent.parent
        self.assertEqual(
            Path(self._root).resolve(), expected, f"resolved the wrong repo root: {self._root}"
        )
        return self._root

    def _check_ignore(self, paths):
        """Return {path: match-or-None} for every path, in ONE git call."""
        root = self._repo_root()
        result = subprocess.run(
            # `-c core.excludesFile=` keeps a developer's GLOBAL ignore file out of the answer.
            # `-n` prints a `::` line for a non-matching path, so one call answers every path.
            ["git", "-C", root, "-c", "core.excludesFile=", "check-ignore", "-v", "-n",
             "--no-index", "--", *paths],
            capture_output=True,
            text=True,
            env=clean_git_env(),
        )
        if result.returncode not in (0, 1):
            self.fail(f"git check-ignore failed: {result.stderr.strip()}")
        matches = {}
        for line in result.stdout.splitlines():
            head, _, target = line.partition("\t")
            # `<source>:<line>:<pattern>`. The source can hold a colon (a Windows drive letter)
            # and so can the pattern, so anchor on the `:<digits>:` in between.
            parsed = re.match(r"^(?P<source>.*?):(?P<line>\d+):(?P<pattern>.*)$", head)
            # `-v` exits 0 for a NEGATED match too (`.gitignore:21:!tmp/.gitkeep`), which means
            # the path is explicitly NOT ignored - reading that as "ignored" would invert this.
            if parsed is None or parsed.group("pattern").startswith("!"):
                matches[target] = None
            elif not parsed.group("source").endswith(".gitignore"):
                # A clone-local `.git/info/exclude` entry is not a repository rule, and these
                # assertions are about the committed `.gitignore` only.
                matches[target] = None
            else:
                matches[target] = parsed.groupdict()
        self.assertEqual(sorted(matches), sorted(paths), f"unexpected output: {result.stdout!r}")
        return matches

    def test_the_root_block_swallows_underscore_scratch(self):
        """`/_*` itself must be the matching pattern, or its deletion would go unnoticed.

        Uppercase shapes are included because `/_*` holds no case-sensitive literal, so it
        matches `_DUMP.TXT` on a case-sensitive filesystem just as it does here.
        """
        paths = [
            "_t1.txt",
            "_t2.patch",
            "_review_diff1.diff",
            "_out.json",
            "_x",
            "_probe",
            "_DUMP.TXT",
            "_X",
        ]
        for path, match in self._check_ignore(paths).items():
            with self.subTest(path=path):
                self.assertIsNotNone(match, f"{path} is not ignored at the root")
                self.assertEqual(match["pattern"], "/_*", f"{path} matched {match}")
                # endswith, not equality: git prints the source path as it resolved it.
                self.assertTrue(match["source"].endswith(".gitignore"), f"{path} matched {match}")

    def test_the_root_block_leaves_real_files_alone(self):
        """`--no-index` is what makes this meaningful: every path below is TRACKED."""
        root = self._repo_root()
        paths = [
            "README.md",
            "AGENTS.md",
            "scripts/task.py",
            "scripts/_git_test_env.py",
            "plugins/commentable-html/dev/tests/_shard.mjs",
            "site/pages/index.html",
        ]
        for path, match in self._check_ignore(paths).items():
            with self.subTest(path=path):
                self.assertTrue((Path(root) / path).exists(), f"{path} no longer exists; fix me")
                self.assertIsNone(match, f"{path} must not be ignored: {match}")

    def test_a_negated_pattern_is_not_read_as_ignored(self):
        """`-v` exits 0 for a negation too, so the helper reads the `!` rather than the status."""
        self.assertIsNone(self._check_ignore(["tmp/.gitkeep"])["tmp/.gitkeep"])

    def test_no_tracked_file_is_ignored(self):
        """The invariant the ignore rules lean on: nothing legitimate is hidden by them.

        `--exclude-per-directory` rather than `--exclude-standard`, so a clone-local
        `.git/info/exclude` cannot red this: the claim is about the committed `.gitignore` files.
        """
        root = self._repo_root()
        result = subprocess.run(
            ["git", "-C", root, "-c", "core.excludesFile=", "ls-files", "-i", "-c",
             "--exclude-per-directory=.gitignore"],
            capture_output=True,
            text=True,
            env=clean_git_env(),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        hidden = sorted(line for line in result.stdout.splitlines() if line)
        self.assertEqual(hidden, [], f"tracked files are hidden by an ignore rule: {hidden}")


class RootScratchTest(unittest.TestCase):
    """A file tracked at the repo ROOT that is not a documented top-level file is scratch.

    An agent's one-off probe lands beside AGENTS.md as `test_svg_exec.html`, `temp.txt`, or a
    bare `x`; the *.diff / *.patch rule never saw those shapes, so a `git add -A` could commit
    one and every gate would stay green. The root is a closed set, so the rule is an allowlist
    (a denylist of shapes cannot keep up with what a probe is named) and it is ANCHORED there -
    a real report under examples/ or a page under site/ is untouched.
    """

    def test_flags_probes_at_the_repo_root(self):
        for path in [
            "test_svg_exec.html",
            "test_importmap.html",
            "TEST_CSP.HTML",
            "test-fp12.js",
            "temp.txt",
            "temp.html",
            "test_out.txt",
            "x",
            "out.json",
            "err.txt",
            "tmp_probe.py",
            "probe_svg.mjs",
            "scratch.ts",
            "diff.txt",
            "js-diff.txt",
            "local.js",
            "old_parsing.py",
            "screenshot.png",
            "result.svg",
            "debug.yaml",
            "notes.md",
            "foo",
            "./temp.txt",
        ]:
            with self.subTest(path=path):
                self.assertTrue(cff.is_scratch_artifact(path), f"{path} should be refused")

    def test_leaves_legitimate_files_alone(self):
        for path in [
            "plugins/commentable-html/examples/report-basic.html",
            "site/dist/index.html",
            "site/pages/index.html",
            "plugins/commentable-html/dev/tests/fixtures/report.html",
            "plugins/commentable-html/dev/tests/test_build.py",
            "scripts/test_check_forbidden_files.py",
            "site/src/site.js",
            "docs/notes.txt",
            "plugins/commentable-html/dev/skill/dist/x",
            "./scripts/check_forbidden_files.py",
        ]:
            with self.subTest(path=path):
                self.assertFalse(cff.is_scratch_artifact(path), f"{path} should be allowed")

    def test_keeps_the_real_top_level_files(self):
        for path in [
            "README.md",
            "AGENTS.md",
            "CLAUDE.md",
            "LICENSE",
            "SECURITY.md",
            "CONTRIBUTING.md",
            "MAINTAINING.md",
            "CODE_OF_CONDUCT.md",
            ".gitignore",
            ".gitattributes",
            ".editorconfig",
            ".ignore",
            "ai-marketplace.code-workspace",
        ]:
            with self.subTest(path=path):
                self.assertFalse(cff.is_scratch_artifact(path), f"{path} should be allowed")

    def test_the_allowlist_is_the_escape_hatch(self):
        """A real top-level file is allowed by naming it exactly as git records it."""
        original = cff.ROOT_ALLOWED
        cff.ROOT_ALLOWED = frozenset(("CITATION.cff", "renovate.json"))
        try:
            self.assertFalse(cff.is_scratch_artifact("CITATION.cff"))
            self.assertFalse(cff.is_scratch_artifact("renovate.json"))
            self.assertTrue(cff.is_scratch_artifact("README.md"))
        finally:
            cff.ROOT_ALLOWED = original

    def test_the_allowlist_is_case_exact(self):
        """A lowercase `readme.md` is a DIFFERENT file on Linux, so folding case would let it in."""
        for path in ["readme.md", "License", "AGENTS.MD", "Security.md"]:
            with self.subTest(path=path):
                self.assertTrue(cff.is_scratch_artifact(path), f"{path} should be refused")

    def test_a_backslash_in_a_root_name_does_not_pose_as_a_subdirectory(self):
        """`foo\\bar` at the root is one file whose NAME holds a backslash, not a nested path."""
        self.assertTrue(cff.is_scratch_artifact("foo\\bar"))

    def test_every_tracked_root_file_is_allowed(self):
        files = cff.tracked_files()
        if files is None:
            self.skipTest("git unavailable")
        root = [p for p in files if "/" not in p]
        offenders = [p for p in root if cff.is_scratch_artifact(p)]
        self.assertEqual(offenders, [], f"scratch is tracked at the repo root: {offenders}")


class TrackedFilesTest(unittest.TestCase):
    """`git ls-files` reports paths relative to the CWD, which would break the root rule.

    Run from a subdirectory, every listed path loses its directory component and looks
    root-level, so the guard would refuse legitimate files; run from outside the repository
    (the script test suite's sandbox), it would silently scan nothing at all. Both are fixed by
    anchoring git on the repository this script lives in.
    """

    def test_paths_are_repo_root_relative_from_any_cwd(self):
        files = cff.tracked_files()
        if files is None:
            self.skipTest("git unavailable")
        self.assertIn("scripts/check_forbidden_files.py", files)
        self.assertIn("README.md", files)

    def test_survives_being_run_from_an_unrelated_directory(self):
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as sandbox:
            os.chdir(sandbox)
            try:
                files = cff.tracked_files()
            finally:
                os.chdir(original)
        if files is None:
            self.skipTest("git unavailable")
        self.assertIn("scripts/check_forbidden_files.py", files)
        offenders = [p for p in files if cff.is_scratch_artifact(p)]
        self.assertEqual(offenders, [], f"scratch is tracked: {offenders}")


class RootDirectoryTest(unittest.TestCase):
    """The top-level DIRECTORIES are a closed set too, or the file rule has an obvious dodge.

    A root rule that only inspects files waves `captures/out.txt` and `_scratch/probe.html`
    straight through on a plain `git add -A`, because they have a slash. They are dumps all the
    same, so the first path component has to be approved either way.
    """

    def test_flags_a_dump_parked_in_a_new_top_level_directory(self):
        for path in [
            "captures/out.txt",
            "_scratch/probe.html",
            "backlog/tasks/x.md",
            "node_modules/left/behind.js",
            "./captures/out.txt",
        ]:
            with self.subTest(path=path):
                self.assertTrue(cff.is_scratch_artifact(path), f"{path} should be refused")

    def test_allows_anything_under_an_approved_directory(self):
        for path in [
            ".github/workflows/validate.yml",
            ".githooks/pre-commit",
            ".claude-plugin/marketplace.json",
            ".vscode/settings.json",
            "docs/testing-guidelines.md",
            "plugins/commentable-html/dev/SPEC.md",
            "scripts/task.py",
            "site/css/00-base.css",
        ]:
            with self.subTest(path=path):
                self.assertFalse(cff.is_scratch_artifact(path), f"{path} should be allowed")

    def test_tmp_admits_only_its_marker_file(self):
        """tmp/ is where this guard TELLS you to write scratch, so it cannot be a free pass."""
        self.assertFalse(cff.is_scratch_artifact("tmp/.gitkeep"))
        for path in ["tmp/dump.txt", "tmp/probe.html", "tmp/nested/out.json"]:
            with self.subTest(path=path):
                self.assertTrue(cff.is_scratch_artifact(path), f"{path} should be refused")

    def test_every_tracked_directory_is_allowed(self):
        files = cff.tracked_files()
        if files is None:
            self.skipTest("git unavailable")
        offenders = sorted({p for p in files if "/" in p and cff.is_scratch_artifact(p)})
        self.assertEqual(offenders, [], f"tracked under an unapproved top-level dir: {offenders}")

    def test_the_directory_allowlists_do_not_rot(self):
        """A name left behind after its entry is gone would quietly widen the closed set."""
        files = cff.tracked_files()
        if files is None:
            self.skipTest("git unavailable")
        stale = sorted(cff.ROOT_ALLOWED - {p for p in files if "/" not in p})
        self.assertEqual(stale, [], f"ROOT_ALLOWED names files that are not tracked: {stale}")
        tracked_dirs = {p.split("/", 1)[0] for p in files if "/" in p}
        stale_dirs = sorted(cff.ROOT_DIR_ALLOWED - tracked_dirs)
        self.assertEqual(stale_dirs, [], f"ROOT_DIR_ALLOWED names absent dirs: {stale_dirs}")


class DisplayPathTest(unittest.TestCase):
    """An offender must be PRINTABLE, or the guard's clearest moment becomes a traceback.

    A name that is not valid UTF-8 arrives as surrogates from the scan; printing one to a
    cp1252 console raises UnicodeEncodeError, losing the refusal message entirely.
    """

    def test_a_surrogate_bearing_name_survives_a_narrow_console(self):
        rendered = cff.display_path("bad\udcff.txt")
        for encoding in ("ascii", "cp1252", "utf-8"):
            with self.subTest(encoding=encoding):
                rendered.encode(encoding)

    def test_an_ordinary_name_is_unchanged(self):
        self.assertEqual(cff.display_path("scripts/task.py"), "scripts/task.py")


class TrackedFilesEncodingTest(unittest.TestCase):
    """A non-ASCII path must survive git and Python intact, or the allowlist misses silently.

    `-z` changes only the DELIMITER, so `core.quotePath` still C-quotes the NAME, and
    `text=True` without an explicit codec decodes git's path bytes with the locale encoding
    (cp1252 on Windows). Either corruption turns an allowed name into an unrecognised one, and
    the guard then refuses a legitimate file with a mangled message.
    """

    def test_a_non_ascii_name_is_reported_literally(self):
        try:
            subprocess.run(["git", "--version"], capture_output=True, check=True)
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("git unavailable")
        name = "caf\u00e9.md"
        env = clean_git_env()
        child = (
            "import runpy, sys; m = runpy.run_path(sys.argv[1]); "
            "print('\\n'.join(m['tracked_files']() or []))"
        )
        with tempfile.TemporaryDirectory() as repo:
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True, env=env)
            subprocess.run(
                ["git", "config", "core.quotePath", "true"], cwd=repo, check=True, env=env
            )
            (Path(repo) / name).write_text("x\n", encoding="utf-8")
            subprocess.run(["git", "add", "-A"], cwd=repo, check=True, env=env)
            proc = subprocess.run(
                [sys.executable, "-c", child, str(_MODULE_PATH)],
                cwd=repo,
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=clean_git_env(
                    GIT_DIR=str(Path(repo) / ".git"),
                    GIT_WORK_TREE=repo,
                    # The child prints the name down a PIPE, where Python otherwise encodes it
                    # with the locale codec and the utf-8 decode here would mojibake it.
                    PYTHONIOENCODING="utf-8",
                ),
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            listed = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
        # Some filesystems store NFD, so compare canonically: the point is that the name is
        # LITERAL (not `"caf\303\251.md"` and not `cafÃ©.md`), not which form it round-trips in.
        normalized = [unicodedata.normalize("NFC", entry) for entry in listed]
        self.assertIn(name, normalized, f"expected a literal name, got {listed}")


class GuardExitStatusTest(unittest.TestCase):
    """The guard must FAIL on a stray, not merely classify it.

    The unit tests above exercise the classifier; this pins the behavior the required CI job
    and the pre-commit hook actually depend on - a non-zero exit that names the offender.
    """

    def _run_main(self, files):
        original = cff.tracked_files
        cff.tracked_files = lambda: files
        buffer = io.StringIO()
        try:
            with contextlib.redirect_stdout(buffer):
                status = cff.main()
        finally:
            cff.tracked_files = original
        return status, buffer.getvalue()

    def test_a_root_scratch_dump_fails_the_guard(self):
        status, out = self._run_main(["README.md", "_t1.txt", "scripts/task.py"])
        self.assertEqual(status, 1, out)
        self.assertIn("_t1.txt", out)
        self.assertIn("ROOT_ALLOWED", out)

    def test_a_dump_in_an_unapproved_directory_fails_the_guard(self):
        status, out = self._run_main(["README.md", "captures/out.txt"])
        self.assertEqual(status, 1, out)
        self.assertIn("captures/out.txt", out)
        self.assertNotIn("README.md", out)

    def test_an_offender_is_named_once(self):
        """During a conflict `git ls-files` reports an unmerged path once per stage."""
        status, out = self._run_main(["_t1.txt", "_t1.txt", "_t1.txt"])
        self.assertEqual(status, 1, out)
        self.assertEqual(out.count("  - _t1.txt"), 1, out)

    def test_a_subdirectory_underscore_dump_fails_the_guard(self):
        """REPO-GUARD-07 is about the EXIT, so the new offender class needs its own boundary pin."""
        status, out = self._run_main(
            ["README.md", "plugins/commentable-html/dev/_wip_diff.txt", "scripts/_git_test_env.py"]
        )
        self.assertEqual(status, 1, out)
        self.assertIn("plugins/commentable-html/dev/_wip_diff.txt", out)
        self.assertNotIn("scripts/_git_test_env.py", out)
        self.assertIn("UNDERSCORE_SOURCE_SUFFIXES", out)

    def test_a_clean_tree_passes(self):
        status, out = self._run_main(["README.md", "scripts/task.py", "docs/README.md"])
        self.assertEqual(status, 0, out)
        self.assertIn("OK", out)


if __name__ == "__main__":
    unittest.main()
