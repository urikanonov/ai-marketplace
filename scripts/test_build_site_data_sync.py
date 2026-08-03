from _build_site_data_test_helpers import *


class SkillZipTests(unittest.TestCase):
    """The Claude Desktop install tab downloads a ZIP of the shipped skill (SITE-INSTALL-06)."""

    def _make_skill(self, root):
        skill_rel = "plugins/demo/pkg/skills/demo"
        skill_dir = os.path.join(root, skill_rel.replace("/", os.sep))
        os.makedirs(os.path.join(skill_dir, "tools"), exist_ok=True)
        os.makedirs(os.path.join(skill_dir, "references"), exist_ok=True)
        with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as fh:
            fh.write("---\nname: demo\ndescription: d\n---\n# Demo\n")
        with open(os.path.join(skill_dir, "tools", "x.py"), "w", encoding="utf-8") as fh:
            fh.write("print('x')\n")
        with open(os.path.join(skill_dir, "references", "a.md"), "w", encoding="utf-8") as fh:
            fh.write("ref\n")
        return skill_rel

    def _descriptor(self, skill_rel):
        return [{"skill_dir": skill_rel, "skill": "demo", "zip": "skills/demo.zip"}]

    def _make_skill_bytes(self, root, text_eol=b"\n"):
        """A skill dir written with EXPLICIT byte line endings (bypassing Python's text-mode newline
        translation): SKILL.md and a text file use `text_eol`, plus a binary asset carrying a NUL
        byte and literal CR/LF bytes that must survive verbatim. Not a git repo, so
        build_skill_zip_members exercises the filtered-walk fallback that reads working-tree bytes."""
        skill_rel = "plugins/demo/pkg/skills/demo"
        skill_dir = os.path.join(root, skill_rel.replace("/", os.sep))
        os.makedirs(skill_dir, exist_ok=True)

        def w(rel, data):
            with open(os.path.join(skill_dir, rel.replace("/", os.sep)), "wb") as fh:
                fh.write(data)

        eol = text_eol
        w("SKILL.md", b"---" + eol + b"name: demo" + eol + b"description: d" + eol + b"---" + eol + b"# Demo" + eol)
        w("notes.md", b"line one" + eol + b"line two" + eol)
        w("logo.png", b"\x89PNG\x00\r\ndata\x00\r\n")
        return skill_rel

    def test_text_members_are_line_ending_normalized_for_cross_platform_determinism(self):
        # A CRLF checkout (for example Windows where eol=lf is not honored) must still yield LF text
        # members so the committed ZIP is byte-identical to a Linux CI rebuild (SITE-BUILD-16).
        with tempfile.TemporaryDirectory() as root:
            skill_rel = self._make_skill_bytes(root, text_eol=b"\r\n")
            members = dict(bsd.build_skill_zip_members(root, skill_rel, "demo"))
            self.assertNotIn(b"\r", members["demo/SKILL.md"])
            self.assertNotIn(b"\r", members["demo/notes.md"])
            # The binary asset is left byte-for-byte: its CR/LF/NUL bytes are data, not line endings.
            self.assertEqual(members["demo/logo.png"], b"\x89PNG\x00\r\ndata\x00\r\n")

    def test_zip_bytes_identical_from_crlf_and_lf_checkouts(self):
        # The whole skill ZIP is byte-reproducible regardless of the checkout's line-ending config,
        # so the required `site` --check gate cannot fail merely because a commit was built off-Linux.
        with tempfile.TemporaryDirectory() as lf_root, tempfile.TemporaryDirectory() as crlf_root:
            lf_rel = self._make_skill_bytes(lf_root, text_eol=b"\n")
            crlf_rel = self._make_skill_bytes(crlf_root, text_eol=b"\r\n")
            lf_zip = bsd._skill_zip_bytes(bsd.build_skill_zip_members(lf_root, lf_rel, "demo"))
            crlf_zip = bsd._skill_zip_bytes(bsd.build_skill_zip_members(crlf_root, crlf_rel, "demo"))
            self.assertEqual(lf_zip, crlf_zip)

    def test_members_have_top_level_skill_folder_with_skill_md(self):
        with tempfile.TemporaryDirectory() as root:
            skill_rel = self._make_skill(root)
            members = bsd.build_skill_zip_members(root, skill_rel, "demo")
            arcnames = [m[0] for m in members]
            self.assertIn("demo/SKILL.md", arcnames)
            self.assertIn("demo/tools/x.py", arcnames)
            self.assertIn("demo/references/a.md", arcnames)
            # Every member sits under the single top-level <skill-name>/ folder Claude Desktop expects.
            for arc in arcnames:
                self.assertTrue(arc.startswith("demo/"), arc)

    def test_sync_writes_a_zip_and_check_is_clean(self):
        with tempfile.TemporaryDirectory() as root:
            skill_rel = self._make_skill(root)
            skills = self._descriptor(skill_rel)
            self.assertEqual(bsd.sync_skill_zips(root, False, skills=skills), [])
            zip_path = os.path.join(root, bsd.SITE_OUT, "skills", "demo.zip")
            self.assertTrue(os.path.isfile(zip_path))
            import zipfile as _zip
            with _zip.ZipFile(zip_path) as z:
                self.assertIn("demo/SKILL.md", z.namelist())
            self.assertEqual(bsd.sync_skill_zips(root, True, skills=skills), [])

    def test_check_flags_a_missing_zip(self):
        with tempfile.TemporaryDirectory() as root:
            skill_rel = self._make_skill(root)
            skills = self._descriptor(skill_rel)
            self.assertTrue(bsd.sync_skill_zips(root, True, skills=skills))

    def test_check_flags_content_drift_after_a_skill_edit(self):
        with tempfile.TemporaryDirectory() as root:
            skill_rel = self._make_skill(root)
            skills = self._descriptor(skill_rel)
            bsd.sync_skill_zips(root, False, skills=skills)
            self.assertEqual(bsd.sync_skill_zips(root, True, skills=skills), [])
            # Edit a skill file without rebuilding the zip; check must catch the drift.
            with open(os.path.join(root, skill_rel.replace("/", os.sep), "SKILL.md"),
                      "a", encoding="utf-8") as fh:
                fh.write("\nchanged\n")
            self.assertTrue(bsd.sync_skill_zips(root, True, skills=skills))

    def test_write_is_idempotent_and_avoids_churn(self):
        # Re-running write with unchanged skill contents leaves the committed zip bytes untouched,
        # so build_site_data.py does not produce spurious multi-MB diffs on every run.
        with tempfile.TemporaryDirectory() as root:
            skill_rel = self._make_skill(root)
            skills = self._descriptor(skill_rel)
            bsd.sync_skill_zips(root, False, skills=skills)
            zip_path = os.path.join(root, bsd.SITE_OUT, "skills", "demo.zip")
            with open(zip_path, "rb") as fh:
                first = fh.read()
            bsd.sync_skill_zips(root, False, skills=skills)
            with open(zip_path, "rb") as fh:
                second = fh.read()
            self.assertEqual(first, second)

    def test_git_tracked_build_excludes_untracked_developer_noise(self):
        # The primary path uses git-tracked files, so untracked noise (.DS_Store, __pycache__)
        # dropped into the skill tree can never leak into the ZIP and break a clean-checkout --check.
        import subprocess as sp
        with tempfile.TemporaryDirectory() as root:
            skill_rel = self._make_skill(root)
            # Scrub inherited git location vars (GIT_DIR, ...) so these operate on the temp
            # repo, never the real one when the suite runs from the pre-push hook (#283).
            env = clean_git_env()
            try:
                sp.run(["git", "init", "-q"], cwd=root, env=env, check=True)
                sp.run(["git", "add", "-A"], cwd=root, env=env, check=True)
                sp.run(["git", "commit", "-qm", "init"], cwd=root, env=env, check=True)
            except (FileNotFoundError, sp.CalledProcessError):
                self.skipTest("git not available")
            skill_dir = os.path.join(root, skill_rel.replace("/", os.sep))
            with open(os.path.join(skill_dir, ".DS_Store"), "wb") as fh:
                fh.write(b"\x00")
            os.makedirs(os.path.join(skill_dir, "__pycache__"), exist_ok=True)
            with open(os.path.join(skill_dir, "__pycache__", "x.pyc"), "wb") as fh:
                fh.write(b"\x00")
            arcs = [m[0] for m in bsd.build_skill_zip_members(root, skill_rel, "demo")]
            self.assertIn("demo/SKILL.md", arcs)
            self.assertNotIn("demo/.DS_Store", arcs)
            self.assertFalse(any("__pycache__" in a or a.endswith(".pyc") for a in arcs), arcs)

    def test_fallback_walk_excludes_developer_noise(self):
        # Outside a git checkout the filtered-walk fallback still drops the same noise.
        with tempfile.TemporaryDirectory() as root:
            skill_rel = self._make_skill(root)
            skill_dir = os.path.join(root, skill_rel.replace("/", os.sep))
            with open(os.path.join(skill_dir, ".DS_Store"), "wb") as fh:
                fh.write(b"\x00")
            os.makedirs(os.path.join(skill_dir, "__pycache__"), exist_ok=True)
            with open(os.path.join(skill_dir, "__pycache__", "x.pyc"), "wb") as fh:
                fh.write(b"\x00")
            arcs = [m[0] for m in bsd.build_skill_zip_members(root, skill_rel, "demo")]
            self.assertIn("demo/SKILL.md", arcs)
            self.assertNotIn("demo/.DS_Store", arcs)
            self.assertFalse(any("__pycache__" in a or a.endswith(".pyc") for a in arcs), arcs)

    def test_missing_skill_dir_raises(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(SystemExit):
                bsd.build_skill_zip_members(root, "plugins/nope/pkg/skills/nope", "nope")

    def test_skill_without_skill_md_at_root_raises(self):
        with tempfile.TemporaryDirectory() as root:
            skill_rel = "plugins/demo/pkg/skills/demo"
            skill_dir = os.path.join(root, skill_rel.replace("/", os.sep))
            os.makedirs(skill_dir)
            with open(os.path.join(skill_dir, "notes.md"), "w", encoding="utf-8") as fh:
                fh.write("x\n")
            with self.assertRaises(SystemExit):
                bsd.build_skill_zip_members(root, skill_rel, "demo")

    def test_tracked_skill_files_refuses_an_unmerged_index(self):
        # `git ls-files` prints an UNMERGED path once per index stage, so a rebuild run during a
        # conflicted merge/rebase repeats it. Fail closed rather than package a half-resolved file
        # (its working-tree bytes may still carry conflict markers) (SITE-BUILD-19).
        out = "\0".join(["plugins/demo/pkg/skills/demo/SKILL.md"] * 3
                        + ["plugins/demo/pkg/skills/demo/tools/x.py"]) + "\0"
        completed = mock.Mock(stdout=out.encode("utf-8"))
        with mock.patch("subprocess.run", return_value=completed):
            with self.assertRaises(SystemExit) as caught:
                bsd._tracked_skill_files("/repo", "plugins/demo/pkg/skills/demo")
        self.assertIn("SKILL.md", str(caught.exception))

    def test_a_conflicted_index_aborts_the_build(self):
        # End-to-end reproduction: an unmerged index entry (three stages) with conflict markers left
        # in the working tree must abort the build, so neither a duplicated member nor the markers
        # can reach the committed ZIP (SITE-BUILD-19).
        import shutil as _shutil
        import subprocess as sp
        if _shutil.which("git") is None:
            self.skipTest("git not available")
        with tempfile.TemporaryDirectory() as root:
            skill_rel = self._make_skill(root)
            env = clean_git_env()
            sp.run(["git", "init", "-q"], cwd=root, env=env, check=True)
            sp.run(["git", "add", "-A"], cwd=root, env=env, check=True)
            sp.run(["git", "commit", "-qm", "init"], cwd=root, env=env, check=True)
            path = skill_rel + "/SKILL.md"
            sha = sp.run(["git", "hash-object", "-w", "--stdin"], input=b"conflicted\n",
                         cwd=root, env=env, capture_output=True, check=True).stdout.decode().strip()
            sp.run(["git", "rm", "--cached", "-q", "--", path], cwd=root, env=env, check=True)
            stages = "".join("100644 %s %d\t%s\n" % (sha, stage, path) for stage in (1, 2, 3))
            sp.run(["git", "update-index", "--index-info"], input=stages.encode("utf-8"),
                   cwd=root, env=env, check=True)
            unmerged = sp.run(["git", "ls-files", "-u", "--", path], cwd=root, env=env,
                              capture_output=True, check=True).stdout.decode()
            self.assertEqual(len(unmerged.strip().splitlines()), 3, unmerged)
            with open(os.path.join(root, path.replace("/", os.sep)), "w", encoding="utf-8") as fh:
                fh.write("<<<<<<< HEAD\nours\n=======\ntheirs\n>>>>>>> other\n")
            skills = self._descriptor(skill_rel)
            # Clear inherited git location vars so the builder's own `git` call targets this repo.
            with mock.patch.dict(os.environ, clean_git_env(), clear=True):
                with self.assertRaises(SystemExit):
                    bsd.build_skill_zip_members(root, skill_rel, "demo")
                with self.assertRaises(SystemExit):
                    bsd.sync_skill_zips(root, False, skills=skills)
            self.assertFalse(os.path.exists(os.path.join(root, bsd.SITE_OUT, "skills", "demo.zip")))

    def test_zip_writer_rejects_duplicate_members(self):
        # Fail closed rather than write a path twice, whatever produced the member list.
        members = [("demo/SKILL.md", b"a"), ("demo/SKILL.md", b"b")]
        with self.assertRaises(SystemExit):
            bsd._skill_zip_bytes(members)

    def test_zip_logical_members_is_an_ordered_list_that_keeps_duplicates(self):
        # The reading of a committed ZIP is an ORDERED LIST taken from infolist(), not a name->bytes
        # map: a map collapses a repeated path to one key and reports a bloated archive as in sync,
        # which is what let a duplicated archive survive every --check run (SITE-BUILD-19).
        import zipfile as _zip
        with tempfile.TemporaryDirectory() as root:
            dup = os.path.join(root, "dup.zip")
            import warnings
            with warnings.catch_warnings():  # zipfile warns on the intentional duplicate
                warnings.simplefilter("ignore", UserWarning)
                with _zip.ZipFile(dup, "w") as z:
                    z.writestr("demo/SKILL.md", "a")
                    z.writestr("demo/SKILL.md", "b")
            read = bsd._zip_logical_members(dup)
            self.assertIsInstance(read, list)
            self.assertEqual([entry[0] for entry in read],
                             ["demo/SKILL.md", "demo/SKILL.md"])
            # Distinct payloads: each entry's bytes are read per infolist() entry, so this is the
            # real archive order and not the name table, which resolves both copies to the last.
            self.assertEqual([entry[-1] for entry in read], [b"a", b"b"])

    def test_check_flags_a_reordered_committed_zip_and_write_repairs_it(self):
        # Same names, same bytes, DIFFERENT member order: a name->bytes map compares that equal, so
        # a repacked archive would sail through --check forever. The ordered comparison catches it
        # and a write run restores the canonical sorted archive (SITE-BUILD-19).
        import zipfile as _zip
        with tempfile.TemporaryDirectory() as root:
            skill_rel = self._make_skill(root)
            skills = self._descriptor(skill_rel)
            bsd.sync_skill_zips(root, False, skills=skills)
            zip_path = os.path.join(root, bsd.SITE_OUT, "skills", "demo.zip")
            members = bsd.build_skill_zip_members(root, skill_rel, "demo")
            self.assertGreater(len(members), 1, "need at least two members to reorder")
            with _zip.ZipFile(zip_path, "w") as z:
                for arcname, data in reversed(members):
                    info = _zip.ZipInfo(arcname, date_time=(1980, 1, 1, 0, 0, 0))
                    info.external_attr = 0o644 << 16
                    info.create_system = 3
                    info.compress_type = _zip.ZIP_DEFLATED
                    z.writestr(info, data)
            self.assertTrue(bsd.sync_skill_zips(root, True, skills=skills),
                            "a reordered committed zip must be reported as drift")
            bsd.sync_skill_zips(root, False, skills=skills)
            with _zip.ZipFile(zip_path) as z:
                names = [info.filename for info in z.infolist()]
            self.assertEqual(names, sorted(names), names)
            self.assertEqual(bsd.sync_skill_zips(root, True, skills=skills), [])

    def test_zip_logical_members_treats_a_corrupt_member_payload_as_unreadable(self):
        # A member whose COMPRESSED payload is garbage raises zlib.error out of the decompressor -
        # not BadZipFile - so an unguarded read would crash the required site --check instead of
        # reporting the archive as stale (SITE-BUILD-19).
        import zipfile as _zip
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "corrupt-member.zip")
            with _zip.ZipFile(path, "w", _zip.ZIP_DEFLATED) as z:
                z.writestr("demo/SKILL.md", b"hello world " * 50)
            with _zip.ZipFile(path) as z:
                info = z.infolist()[0]
                start = (info.header_offset + 30 + len(info.filename.encode("utf-8"))
                         + len(info.extra or b""))
                size = info.compress_size
            with open(path, "rb") as fh:
                raw = bytearray(fh.read())
            raw[start:start + size] = b"\xff" * size
            with open(path, "wb") as fh:
                fh.write(bytes(raw))
            self.assertIsNone(bsd._zip_logical_members(path))

    def test_check_flags_a_committed_zip_with_directory_entries_and_write_repairs_it(self):
        # Unzipping and re-zipping by hand adds explicit directory entries this build never emits,
        # so the repacked archive is drift and a write run replaces it (SITE-BUILD-19).
        import zipfile as _zip
        with tempfile.TemporaryDirectory() as root:
            skill_rel = self._make_skill(root)
            skills = self._descriptor(skill_rel)
            bsd.sync_skill_zips(root, False, skills=skills)
            zip_path = os.path.join(root, bsd.SITE_OUT, "skills", "demo.zip")
            members = bsd.build_skill_zip_members(root, skill_rel, "demo")
            with _zip.ZipFile(zip_path, "w") as z:
                z.writestr("demo/", b"")
                for arcname, data in members:
                    z.writestr(bsd._zip_member_info(arcname), data)
            self.assertTrue(bsd.sync_skill_zips(root, True, skills=skills),
                            "a committed zip carrying directory entries must be reported as drift")
            bsd.sync_skill_zips(root, False, skills=skills)
            with _zip.ZipFile(zip_path) as z:
                self.assertEqual([i.filename for i in z.infolist()],
                                 [arcname for arcname, _ in members])
            self.assertEqual(bsd.sync_skill_zips(root, True, skills=skills), [])

    def test_check_flags_each_noncanonical_member_stamp_on_its_own(self):
        # Every stamp the writer applies is compared, so drifting any ONE of them is caught. A test
        # that mutates all four at once would pass even if only one were compared (SITE-BUILD-19).
        import zipfile as _zip
        mutations = {"date_time": (2024, 5, 6, 7, 8, 10),
                     "external_attr": 0o777 << 16,
                     "create_system": 0,
                     "compress_type": _zip.ZIP_STORED}
        for field, value in mutations.items():
            with self.subTest(stamp=field):
                with tempfile.TemporaryDirectory() as root:
                    skill_rel = self._make_skill(root)
                    skills = self._descriptor(skill_rel)
                    bsd.sync_skill_zips(root, False, skills=skills)
                    zip_path = os.path.join(root, bsd.SITE_OUT, "skills", "demo.zip")
                    members = bsd.build_skill_zip_members(root, skill_rel, "demo")
                    with _zip.ZipFile(zip_path, "w") as z:
                        for arcname, data in members:
                            info = bsd._zip_member_info(arcname)
                            setattr(info, field, value)
                            z.writestr(info, data)
                    self.assertTrue(bsd.sync_skill_zips(root, True, skills=skills),
                                    "a drifted %s stamp must be reported as drift" % field)

    def test_check_flags_a_noncanonical_committed_zip_and_write_repairs_it(self):
        # Same names, same bytes, same order, but repacked with host timestamps/modes and stored
        # (uncompressed) members. The archive is not what this build produces, so --check reports
        # drift and a write run replaces it with the canonically stamped one (SITE-BUILD-19).
        import zipfile as _zip
        with tempfile.TemporaryDirectory() as root:
            skill_rel = self._make_skill(root)
            skills = self._descriptor(skill_rel)
            bsd.sync_skill_zips(root, False, skills=skills)
            zip_path = os.path.join(root, bsd.SITE_OUT, "skills", "demo.zip")
            members = bsd.build_skill_zip_members(root, skill_rel, "demo")
            with _zip.ZipFile(zip_path, "w") as z:
                for arcname, data in members:
                    info = _zip.ZipInfo(arcname, date_time=(2024, 5, 6, 7, 8, 10))
                    info.external_attr = 0o777 << 16
                    info.create_system = 0
                    info.compress_type = _zip.ZIP_STORED
                    z.writestr(info, data)
            self.assertTrue(bsd.sync_skill_zips(root, True, skills=skills),
                            "a noncanonically stamped committed zip must be reported as drift")
            bsd.sync_skill_zips(root, False, skills=skills)
            with _zip.ZipFile(zip_path) as z:
                stamps = {(i.date_time, i.external_attr, i.create_system, i.compress_type)
                          for i in z.infolist()}
            self.assertEqual(stamps, {((1980, 1, 1, 0, 0, 0), 0o644 << 16, 3, _zip.ZIP_DEFLATED)})
            self.assertEqual(bsd.sync_skill_zips(root, True, skills=skills), [])

    def test_check_flags_a_duplicated_committed_zip_and_write_repairs_it(self):
        import zipfile as _zip
        with tempfile.TemporaryDirectory() as root:
            skill_rel = self._make_skill(root)
            skills = self._descriptor(skill_rel)
            bsd.sync_skill_zips(root, False, skills=skills)
            zip_path = os.path.join(root, bsd.SITE_OUT, "skills", "demo.zip")
            members = bsd.build_skill_zip_members(root, skill_rel, "demo")
            import warnings
            with warnings.catch_warnings():  # zipfile warns on each intentional duplicate
                warnings.simplefilter("ignore", UserWarning)
                with _zip.ZipFile(zip_path, "w") as z:  # every member written twice
                    for arcname, data in members + members:
                        z.writestr(arcname, data)
            self.assertTrue(bsd.sync_skill_zips(root, True, skills=skills),
                            "a duplicated committed zip must be reported as drift")
            bsd.sync_skill_zips(root, False, skills=skills)
            with _zip.ZipFile(zip_path) as z:
                names = [info.filename for info in z.infolist()]
            self.assertEqual(len(names), len(set(names)), names)
            self.assertEqual(bsd.sync_skill_zips(root, True, skills=skills), [])

    def test_committed_site_zips_carry_each_path_exactly_once(self):
        # The shipped artifacts themselves: member count must equal unique-name count, so a
        # duplicated archive can never sit in main unnoticed (SITE-BUILD-19).
        import zipfile as _zip
        for name in ("commentable-html.zip", "multi-duck.zip"):
            zip_path = os.path.join(bsd.REPO_ROOT, bsd.SITE_OUT, "skills", name)
            if not os.path.isfile(zip_path):
                self.skipTest("committed skill zip not generated yet")
            with _zip.ZipFile(zip_path) as z:
                names = [info.filename for info in z.infolist()]
            self.assertEqual(len(names), len(set(names)),
                             "%s carries duplicate members: %s" % (name, sorted(
                                 n for n in set(names) if names.count(n) > 1)))

    def test_rebuilding_twice_from_unchanged_sources_is_byte_identical(self):
        with tempfile.TemporaryDirectory() as root:
            skill_rel = self._make_skill(root)
            first = bsd._skill_zip_bytes(bsd.build_skill_zip_members(root, skill_rel, "demo"))
            second = bsd._skill_zip_bytes(bsd.build_skill_zip_members(root, skill_rel, "demo"))
            self.assertEqual(first, second)

    def test_zip_logical_members_treats_a_corrupt_archive_as_unreadable(self):
        # A malformed archive must be treated as stale (None), not crash --check.
        with tempfile.TemporaryDirectory() as root:
            bad = os.path.join(root, "bad.zip")
            with open(bad, "wb") as fh:
                fh.write(b"not a zip file at all")
            self.assertIsNone(bsd._zip_logical_members(bad))

    def test_committed_commentable_html_zip_has_top_level_skill_folder(self):
        # The real committed site zip must extract to a single commentable-html/ folder with SKILL.md
        # at its root, matching what Claude Desktop's skill import expects.
        import zipfile as _zip
        zip_path = os.path.join(bsd.REPO_ROOT, bsd.SITE_OUT, "skills", "commentable-html.zip")
        if not os.path.isfile(zip_path):
            self.skipTest("committed skill zip not generated yet")
        with _zip.ZipFile(zip_path) as z:
            names = z.namelist()
        self.assertIn("commentable-html/SKILL.md", names)
        for n in names:
            self.assertTrue(n.startswith("commentable-html/"), n)

    def test_committed_multi_duck_zip_has_top_level_skill_folder(self):
        # multi-duck is also an importable Claude Desktop skill (SITE-INSTALL-05/06), so its committed
        # site zip must extract to a single multi-duck/ folder with SKILL.md at its root.
        import zipfile as _zip
        zip_path = os.path.join(bsd.REPO_ROOT, bsd.SITE_OUT, "skills", "multi-duck.zip")
        if not os.path.isfile(zip_path):
            self.skipTest("committed skill zip not generated yet")
        with _zip.ZipFile(zip_path) as z:
            names = z.namelist()
        self.assertIn("multi-duck/SKILL.md", names)
        for n in names:
            self.assertTrue(n.startswith("multi-duck/"), n)

class SyncOrphanTests(unittest.TestCase):
    def test_orphan_flagged_then_removed(self):
        import os as _os
        import tempfile
        base = tempfile.mkdtemp()
        dst = _os.path.join(base, "dst")
        _os.makedirs(dst)
        open(_os.path.join(dst, "keep.png"), "wb").close()
        open(_os.path.join(dst, "orphan.png"), "wb").close()
        drift = bsd._orphans(dst, ["keep.png"], check=True)
        self.assertTrue(any("orphan.png" in item for item in drift))
        bsd._orphans(dst, ["keep.png"], check=False)
        self.assertFalse(_os.path.exists(_os.path.join(dst, "orphan.png")))
        self.assertTrue(_os.path.exists(_os.path.join(dst, "keep.png")))

    def test_orphans_reported_in_sorted_order(self):
        # Determinism: the orphan sweep must report drift in a stable, sorted order regardless
        # of the order os.listdir happens to return, so `--check` output and CI logs never flip
        # across platforms. Reverting the sorted() around the directory scan turns this red.
        names = ["c.html", "a.html", "b.html"]
        with tempfile.TemporaryDirectory() as d:
            for name in names:
                open(os.path.join(d, name), "wb").close()
            with mock.patch.object(bsd.os, "listdir", return_value=list(names)):
                drift = bsd._orphans(d, [], check=True)
        self.assertEqual(drift, ["a.html (orphaned)", "b.html (orphaned)", "c.html (orphaned)"])

class SyncDemosDriftTests(unittest.TestCase):
    def _make_root(self):
        import os as _os
        import tempfile
        root = tempfile.mkdtemp()
        src = _os.path.join(root, bsd.EXAMPLES_REL)
        dst = _os.path.join(root, bsd.DEMO_REL)
        _os.makedirs(src)
        _os.makedirs(dst)
        for name in bsd.DEMO_FILES:
            with open(_os.path.join(src, name), "wb") as fh:
                fh.write(b"<html>source " + name.encode() + b"</html>\n")
        return root, src, dst

    def test_content_difference_flagged_then_synced(self):
        import os as _os
        root, _src, dst = self._make_root()
        with open(_os.path.join(dst, bsd.DEMO_FILES[0]), "wb") as fh:
            fh.write(b"<html>STALE</html>\n")
        drift = bsd.sync_demos(root, check=True)
        self.assertIn(bsd.DEMO_FILES[0], drift)
        self.assertFalse(bsd.sync_demos(root, check=False))
        self.assertFalse(bsd.sync_demos(root, check=True))

    def test_missing_destination_flagged(self):
        root, _src, _dst = self._make_root()
        drift = bsd.sync_demos(root, check=True)
        self.assertEqual(sorted(drift), sorted(bsd.DEMO_FILES))

class SyncTutorialImagesTests(unittest.TestCase):
    def _make_root(self, with_src=True):
        import os as _os
        import tempfile
        root = tempfile.mkdtemp()
        if with_src:
            src = _os.path.join(root, bsd.TUTORIAL_IMAGES_SRC)
            _os.makedirs(src)
            with open(_os.path.join(src, "a.png"), "wb") as fh:
                fh.write(b"IMG-A")
        _os.makedirs(_os.path.join(root, bsd.TUTORIAL_IMAGES_DST))
        return root

    def test_content_difference_flagged_then_synced(self):
        import os as _os
        root = self._make_root()
        dst = _os.path.join(root, bsd.TUTORIAL_IMAGES_DST)
        with open(_os.path.join(dst, "a.png"), "wb") as fh:
            fh.write(b"STALE")
        self.assertIn("a.png", bsd.sync_tutorial_images(root, check=True))
        self.assertFalse(bsd.sync_tutorial_images(root, check=False))
        self.assertFalse(bsd.sync_tutorial_images(root, check=True))

    def test_orphan_removed_when_source_file_gone(self):
        import os as _os
        root = self._make_root()
        dst = _os.path.join(root, bsd.TUTORIAL_IMAGES_DST)
        bsd.sync_tutorial_images(root, check=False)
        with open(_os.path.join(dst, "gone.png"), "wb") as fh:
            fh.write(b"ORPHAN")
        self.assertTrue(any("gone.png" in d for d in bsd.sync_tutorial_images(root, check=True)))
        bsd.sync_tutorial_images(root, check=False)
        self.assertFalse(_os.path.exists(_os.path.join(dst, "gone.png")))
        self.assertTrue(_os.path.exists(_os.path.join(dst, "a.png")))

    def test_missing_source_dir_orphans_committed_images(self):
        import os as _os
        root = self._make_root(with_src=False)
        dst = _os.path.join(root, bsd.TUTORIAL_IMAGES_DST)
        with open(_os.path.join(dst, "stale.png"), "wb") as fh:
            fh.write(b"X")
        self.assertTrue(any("stale.png" in d for d in bsd.sync_tutorial_images(root, check=True)))
        bsd.sync_tutorial_images(root, check=False)
        self.assertFalse(_os.path.exists(_os.path.join(dst, "stale.png")))

class StampAssetsTests(unittest.TestCase):
    def test_stamps_css_and_js_with_content_hash_at_every_prefix(self):
        css = bsd._asset_hash(bsd.REPO_ROOT, "styles.css")
        js = bsd._asset_hash(bsd.REPO_ROOT, "site.js")
        html = ('<link rel="stylesheet" href="assets/styles.css" />\n'
                '<link rel="stylesheet" href="../assets/styles.css" />\n'
                '<script src="../../assets/site.js"></script>')
        out = bsd.stamp_assets(html, bsd.REPO_ROOT)
        self.assertIn('href="assets/styles.css?v=%s"' % css, out)
        self.assertIn('href="../assets/styles.css?v=%s"' % css, out)
        self.assertIn('src="../../assets/site.js?v=%s"' % js, out)

    def test_replaces_an_existing_stale_stamp(self):
        css = bsd._asset_hash(bsd.REPO_ROOT, "styles.css")
        out = bsd.stamp_assets('<link href="assets/styles.css?v=deadbeef" />', bsd.REPO_ROOT)
        self.assertIn('href="assets/styles.css?v=%s"' % css, out)
        self.assertNotIn("deadbeef", out)

    def test_is_idempotent(self):
        html = '<link href="../../assets/styles.css" /><script src="../../assets/site.js"></script>'
        once = bsd.stamp_assets(html, bsd.REPO_ROOT)
        self.assertEqual(once, bsd.stamp_assets(once, bsd.REPO_ROOT))

    def test_leaves_other_assets_untouched(self):
        html = '<link rel="icon" href="../assets/commentable-html.svg" />'
        self.assertEqual(bsd.stamp_assets(html, bsd.REPO_ROOT), html)

    def test_replaces_any_existing_query_or_fragment(self):
        css = bsd._asset_hash(bsd.REPO_ROOT, "styles.css")
        for ref in ["assets/styles.css?v=ABC123&t=1", "../assets/styles.css?foo=bar",
                    "assets/styles.css#frag"]:
            out = bsd.stamp_assets('<link href="%s" />' % ref, bsd.REPO_ROOT)
            self.assertRegex(out, r'href="(?:\.\./)*assets/styles\.css\?v=%s"' % css)
            for stale in ("ABC123", "foo=bar", "#frag"):
                self.assertNotIn(stale, out)

    def test_matches_dot_slash_prefix(self):
        css = bsd._asset_hash(bsd.REPO_ROOT, "styles.css")
        out = bsd.stamp_assets('<link href="./assets/styles.css" />', bsd.REPO_ROOT)
        self.assertIn('href="./assets/styles.css?v=%s"' % css, out)

class StampWiringTests(unittest.TestCase):
    PAGES = ["site/dist/index.html", "site/dist/commentable-html/index.html",
             "site/dist/commentable-html/tutorial/index.html"]

    def test_committed_pages_carry_current_asset_stamps(self):
        import os as _os
        css = bsd._asset_hash(bsd.REPO_ROOT, "styles.css")
        js = bsd._asset_hash(bsd.REPO_ROOT, "site.js")
        for rel in self.PAGES:
            text = bsd.read_text(_os.path.join(bsd.REPO_ROOT, *rel.split("/")))
            self.assertIn("styles.css?v=%s" % css, text)
            self.assertIn("site.js?v=%s" % js, text)

    def test_no_site_html_has_a_stale_or_unstamped_asset_ref(self):
        import os as _os
        import glob
        want = {name: "?v=" + bsd._asset_hash(bsd.REPO_ROOT, name) for name in bsd.CACHE_BUSTED_ASSETS}
        alternation = "|".join(re.escape(name) for name in bsd.CACHE_BUSTED_ASSETS)
        pat = re.compile(r'(?:href|src)="[^"]*?assets/(%s)([^"]*)"' % alternation)
        bad = []
        for path in sorted(glob.glob(_os.path.join(bsd.REPO_ROOT, "site", "dist", "**", "*.html"), recursive=True)):
            for m in pat.finditer(bsd.read_text(path)):
                if m.group(2) != want[m.group(1)]:
                    bad.append(_os.path.relpath(path, bsd.REPO_ROOT) + ": " + m.group(0))
        self.assertEqual(bad, [])

class StylesConcatTests(unittest.TestCase):
    def test_concat_matches_committed_stylesheet(self):
        import os as _os
        root = bsd.REPO_ROOT
        built = bsd.build_styles(root)
        committed = bsd.read_text(_os.path.join(root, "site", "dist", "assets", "styles.css"))
        self.assertEqual(
            built, committed,
            "site/dist/assets/styles.css is stale vs site/css/ partials; run build_site_data.py")

    def test_parts_exist_and_base_loads_first(self):
        import os as _os
        root = bsd.REPO_ROOT
        parts = bsd.ordered_css_parts(root)
        self.assertTrue(parts, "no CSS partials discovered under site/css/")
        for name in parts:
            self.assertTrue(
                _os.path.exists(_os.path.join(root, "site", "css", name)),
                "missing CSS partial: " + name)
        # Order is load-bearing (directory-sorted): the tokens/base partial must come first.
        self.assertEqual(parts[0], "10-base.css")
        self.assertEqual(parts, sorted(parts), "partials must be returned in sorted (cascade) order")

    def test_a_stray_non_numbered_css_file_is_rejected(self):
        import os as _os
        import tempfile
        root = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, root, ignore_errors=True)
        css_dir = _os.path.join(root, "site", "css")
        _os.makedirs(css_dir)
        with open(_os.path.join(css_dir, "10-base.css"), "w", encoding="utf-8") as fh:
            fh.write("a{}")
        with open(_os.path.join(css_dir, "helpers.css"), "w", encoding="utf-8") as fh:
            fh.write("b{}")
        with self.assertRaises(SystemExit):
            bsd.ordered_css_parts(root)




class StampsMediaAssetsTest(unittest.TestCase):
    """A re-recorded clip keeps its filename, so without a stamp a returning visitor keeps the
    cached one - and the whole point of the recorder is that these get re-recorded."""

    def test_stamps_the_demo_clips_and_posters(self):
        clip = bsd._asset_hash(bsd.REPO_ROOT, "demo-multi-duck.webm")
        poster = bsd._asset_hash(bsd.REPO_ROOT, "poster-multi-duck.jpg")
        html = ('<button data-video="../assets/demo-multi-duck.webm">'
                '<img src="../assets/poster-multi-duck.jpg" /></button>')
        out = bsd.stamp_assets(html, bsd.REPO_ROOT)
        # The clip URL lives in data-video, not href/src, so the attribute set has to cover it.
        self.assertIn('data-video="../assets/demo-multi-duck.webm?v=%s"' % clip, out)
        self.assertIn('src="../assets/poster-multi-duck.jpg?v=%s"' % poster, out)

    def test_stamps_the_tutorial_images(self):
        # Driven by the tutorial's own assets DIRECTORY, not a hand-maintained name list: the
        # tutorial ships ~21 images that come from the plugin docs, so listing them by name would
        # rot the moment one is added or renamed.
        name = "garden-01-top-light.png"
        digest = bsd._tutorial_asset_hash(bsd.REPO_ROOT, name)
        tutorial_src = os.path.join(bsd.SITE_PAGES, "commentable-html", "tutorial", "index.html")
        html = '<p><img src="assets/%s" alt="x" loading="lazy" /></p>' % name
        out = bsd.stamp_tutorial_assets(html, bsd.REPO_ROOT, tutorial_src)
        self.assertIn('src="assets/%s?v=%s"' % (name, digest), out)

        # The SAME image is referenced from the plugin page one directory up, so narrowing the
        # stamper to the tutorial page's own spelling would silently leave that copy stale.
        plugin_src = os.path.join(bsd.SITE_PAGES, "commentable-html", "index.html")
        plugin_html = '<img src="tutorial/assets/%s" />' % name
        plugin_out = bsd.stamp_tutorial_assets(plugin_html, bsd.REPO_ROOT, plugin_src)
        self.assertIn('src="tutorial/assets/%s?v=%s"' % (name, digest), plugin_out)

        # Idempotent: an already-stamped reference is not stamped twice.
        self.assertEqual(bsd.stamp_tutorial_assets(out, bsd.REPO_ROOT, tutorial_src), out)

        # A `./`-prefixed reference resolves to the same place, so it is stamped too - the
        # normalisation that makes that true is otherwise unexercised.
        dotted = bsd.stamp_tutorial_assets(
            '<img src="./assets/%s" />' % name, bsd.REPO_ROOT, tutorial_src)
        self.assertIn('src="./assets/%s?v=%s"' % (name, digest), dotted)

        # Vector and modern raster formats are stamped as well: review-loop.svg already sits in the
        # tutorial assets directory, so the day a page references it by URL it must not ship
        # unstamped just because the extension list was raster-only.
        svg = bsd.stamp_tutorial_assets(
            '<img src="assets/review-loop.svg" />', bsd.REPO_ROOT, tutorial_src)
        self.assertIn('src="assets/review-loop.svg?v=%s"'
                      % bsd._tutorial_asset_hash(bsd.REPO_ROOT, "review-loop.svg"), svg)

    def test_a_same_named_shared_asset_does_not_take_the_tutorial_digest(self):
        # `assets/x.png` means the SHARED assets dir on the hub page and the TUTORIAL one on the
        # tutorial page. Matching on filename alone would stamp an unrelated shared file with a
        # tutorial image's digest - a silently wrong cache key that never expires.
        name = "garden-01-top-light.png"
        hub_src = os.path.join(bsd.SITE_PAGES, "index.html")
        html = '<img src="assets/%s" />' % name
        self.assertEqual(bsd.stamp_tutorial_assets(html, bsd.REPO_ROOT, hub_src), html)

    def test_the_tutorial_stamp_tracks_the_bytes(self):
        # Built in a temp root: mutating the real committed image and restoring it in a `finally`
        # leaves a corrupted binary behind if the process is killed between the two writes.
        name = "garden-01-top-light.png"
        with tempfile.TemporaryDirectory() as root:
            src_dir = os.path.join(root, bsd.TUTORIAL_IMAGES_SRC)
            os.makedirs(src_dir)
            path = os.path.join(src_dir, name)
            with open(path, "wb") as fh:
                fh.write(b"first bytes")
            first = bsd._tutorial_asset_hash(root, name)
            self.assertEqual(first, bsd._tutorial_asset_hash(root, name))
            with open(path, "wb") as fh:
                fh.write(b"second bytes")
            self.assertNotEqual(first, bsd._tutorial_asset_hash(root, name))

    def test_a_missing_tutorial_image_fails_loudly(self):
        # The name guard normally makes this unreachable, but a file deleted between the listing
        # and the read must not surface as a bare traceback.
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, bsd.TUTORIAL_IMAGES_SRC))
            with self.assertRaises(SystemExit) as caught:
                bsd._tutorial_asset_hash(root, "gone.png")
            self.assertIn("gone.png", str(caught.exception))

    def test_a_page_source_outside_site_pages_fails_loudly(self):
        # Resolving against anything else makes every reference land outside the tutorial directory,
        # so the page would ship with zero stamps and no error at all.
        with self.assertRaises(SystemExit):
            bsd.stamp_tutorial_assets('<img src="assets/x.png" />', bsd.REPO_ROOT,
                                      os.path.join("plugins", "x", "index.html"))

    def test_a_reference_to_a_missing_tutorial_image_is_left_alone(self):
        # Only files that actually sit in the tutorial assets directory are stamped, so a link to
        # something else that happens to start with assets/ is not rewritten into a broken URL.
        tutorial_src = os.path.join(bsd.SITE_PAGES, "commentable-html", "tutorial", "index.html")
        html = '<img src="assets/not-a-tutorial-image.png" />'
        self.assertEqual(bsd.stamp_tutorial_assets(html, bsd.REPO_ROOT, tutorial_src), html)

    def test_the_stamp_hashes_the_source_not_the_copy_in_dist(self):
        # sync_tutorial_images copies source -> dist AFTER the pages are built, so hashing the dist
        # copy stamped each page with the PREVIOUS build's bytes and then overwrote them: the stamp
        # lagged a build behind and named content the visitor no longer received. Pin the direction.
        with tempfile.TemporaryDirectory() as root:
            src_dir = os.path.join(root, bsd.TUTORIAL_IMAGES_SRC)
            dst_dir = os.path.join(root, bsd.TUTORIAL_IMAGES_DST)
            os.makedirs(src_dir)
            os.makedirs(dst_dir)
            with open(os.path.join(src_dir, "shot.png"), "wb") as fh:
                fh.write(b"the new bytes")
            with open(os.path.join(dst_dir, "shot.png"), "wb") as fh:
                fh.write(b"the stale bytes from the previous build")
            expected = bsd.hashlib.sha256(b"the new bytes").hexdigest()[:12]
            self.assertEqual(bsd._tutorial_asset_hash(root, "shot.png"), expected)

    def test_the_tutorial_stamp_matches_the_bytes_that_ship(self):
        # The stamp is computed while building the pages, but the images are copied into site/dist
        # AFTERWARDS. Hashing the destination therefore stamped a page with the PREVIOUS build's
        # bytes, so a regenerated screenshot shipped under its old cache key - exactly the staleness
        # the stamp exists to prevent. Pin the stamp against the bytes actually served.
        page = os.path.join(bsd.REPO_ROOT, bsd.TUTORIAL_PAGE)
        with open(page, encoding="utf-8") as fh:
            built = fh.read()
        refs = re.findall(r'src="assets/([\w.\-]+\.(?:png|jpg|jpeg))\?v=([0-9a-f]{12})"', built)
        self.assertTrue(refs, "the tutorial page has no stamped images")
        for name, stamp in refs:
            served = os.path.join(bsd.REPO_ROOT, bsd.TUTORIAL_IMAGES_DST, name)
            with open(served, "rb") as fh:
                digest = bsd.hashlib.sha256(fh.read()).hexdigest()[:12]
            self.assertEqual(stamp, digest,
                             "%s is stamped %s but the shipped bytes hash to %s" % (name, stamp, digest))

    def test_every_served_clip_and_poster_is_stamped_on_the_built_pages(self):
        # Globbed, not a list of the pages that happen to have clips today: an unstamped clip
        # added to any other page would otherwise ship green.
        out_root = os.path.join(bsd.REPO_ROOT, bsd.SITE_OUT)
        tutorial_dir = os.path.normpath(os.path.join(bsd.REPO_ROOT, bsd.TUTORIAL_IMAGES_DST))
        pages = [os.path.join(base, name)
                 for base, _dirs, names in os.walk(out_root)
                 for name in names if name.endswith(".html")]
        self.assertTrue(pages, "no built pages found")
        checked_dirs = set()
        for path in pages:
            page = os.path.relpath(path, out_root)
            with open(path, encoding="utf-8") as fh:
                built = fh.read()
            for match in re.finditer(
                    r'(?:data-video|src|href)="([^"?]+\.(?:webm|mp4|jpg|jpeg|png|gif|webp|svg))([^"]*)"', built):
                ref, query = match.group(1), match.group(2)
                # An off-site asset is not ours to stamp, and os.path.join would mangle its URL
                # into a path that happens to end in `assets`.
                if ref.startswith(("http://", "https://", "//", "data:")):
                    continue
                # Resolve the reference against the page that holds it. EVERY assets/ directory
                # counts - the site's shared one and the tutorial's own - because a regenerated
                # screenshot keeps its filename exactly as a re-recorded clip does.
                resolved = os.path.normpath(os.path.join(os.path.dirname(path), ref))
                holder = os.path.dirname(resolved)
                if os.path.basename(holder) != "assets":
                    continue
                # The site's own icons are deliberately exempt (CACHE_BUSTED_ASSETS): they change
                # rarely and a cached favicon does not misrender a page. Tutorial images are the
                # opposite - regenerated in place under the same filename - so nothing there is
                # exempt whatever its extension.
                if holder != tutorial_dir and ref.lower().endswith((".svg", ".ico")):
                    continue
                checked_dirs.add(holder)
                self.assertTrue(
                    query.startswith("?v="),
                    "%s on the %s page is served without a cache-busting stamp" % (ref, page))
        # Naming the directories keeps this from passing vacuously on the shared assets alone:
        # narrowing the filter back to site/dist/assets must fail here.
        self.assertIn(os.path.normpath(os.path.join(out_root, "assets")), checked_dirs)
        self.assertIn(tutorial_dir, checked_dirs)

class SiteDistHasNoStrayFilesTest(unittest.TestCase):
    """site/dist IS the published Pages artifact - pages.yml uploads the whole directory.

    --check compares the files the generator knows about; it has no sweep for arbitrary extra
    files, so a scratch file dropped in here ships live with CI green. Two range-test fixtures
    (test.txt, empty.txt) reached this branch exactly that way.
    """

    ALLOWED_TOP_LEVEL = {
        "assets", "commentable-html", "multi-duck", "skills",
        "urikan-ai-marketplace-auto-updater", "index.html", "llms.txt", "sitemap.xml",
    }

    def test_no_unexpected_entries_at_the_top_level(self):
        out = os.path.join(bsd.REPO_ROOT, bsd.SITE_OUT)
        found = set(os.listdir(out))
        stray = sorted(found - self.ALLOWED_TOP_LEVEL)
        self.assertEqual(
            stray, [],
            "unexpected entries in the published site/dist: %s - scratch belongs in tmp/" % stray)


if __name__ == "__main__":
    unittest.main()
