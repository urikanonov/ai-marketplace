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
            env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e",
                       GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@e")
            try:
                sp.run(["git", "init", "-q"], cwd=root, check=True)
                sp.run(["git", "add", "-A"], cwd=root, check=True)
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


if __name__ == "__main__":
    unittest.main()
