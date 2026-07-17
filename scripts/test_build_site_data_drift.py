from _build_site_data_test_helpers import *


class WriteOrCheckTests(unittest.TestCase):
    def test_writes_then_reports_drift_only_on_change(self):
        import shutil
        import tempfile
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        path = os.path.join(d, "sitemap.xml")
        self.assertEqual(bsd.write_or_check(path, "a\nb\n", False), [])
        self.assertEqual(bsd.write_or_check(path, "a\nb\n", True), [])
        self.assertEqual(bsd.write_or_check(path, "a\nc\n", True), ["sitemap.xml"])
        self.assertEqual(bsd.write_or_check(os.path.join(d, "gone.txt"), "x", True), ["gone.txt"])

class CheckDriftTests(unittest.TestCase):
    # Building the clone is the dominant cost of this suite (~17 tests each copied every tracked
    # file, including the large vendored dev/ subtree that build_site_data.py never reads). Build a
    # filtered template ONCE per class (one git call, dev/ and dist/ excluded) and copytree from that
    # warm local template per test - same inputs build_site_data needs, a fraction of the bytes.
    _template = None
    _template_ok = False

    @classmethod
    def setUpClass(cls):
        import os as _os
        import shutil
        import subprocess
        import tempfile
        try:
            tracked = subprocess.run(["git", "-C", bsd.REPO_ROOT, "ls-files", "-z"],
                                     env=clean_git_env(),
                                     capture_output=True, check=True).stdout.decode("utf-8").split("\0")
        except (FileNotFoundError, subprocess.CalledProcessError):
            cls._template_ok = False
            return
        cls._template = tempfile.mkdtemp(prefix="cmh-site-template-")
        for rel in tracked:
            if not rel:
                continue
            # build_site_data.py reads site/ (sources AND the committed site/dist output) plus the
            # plugins' pkg changelogs/docs/examples and the marketplace manifest, and the STAGE skill
            # tree (plugins/*/dev/skill/**) which it zips for the Claude Desktop download - never the
            # rest of plugins/*/dev/** or the generated plugin dist/ bundles. Keep site/dist/ (the
            # tests operate on the built site) and dev/skill/, but drop everything else under dev/.
            is_stage_skill = "/dev/skill/" in rel or rel.endswith("/dev/skill")
            if not is_stage_skill and (
                    "/dev/" in rel or rel.endswith("/dev")
                    or ("/dist/" in rel and not rel.startswith("site/dist/"))):
                continue
            src = _os.path.join(bsd.REPO_ROOT, rel.replace("/", _os.sep))
            if not _os.path.isfile(src):
                continue
            dst = _os.path.join(cls._template, rel.replace("/", _os.sep))
            _os.makedirs(_os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
        cls._template_ok = True

    @classmethod
    def tearDownClass(cls):
        import shutil
        if cls._template:
            shutil.rmtree(cls._template, ignore_errors=True)

    def _clone_repo(self):
        import shutil
        import tempfile
        if not self._template_ok:
            self.skipTest("git not available on PATH; cannot clone the repo for this test")
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        shutil.copytree(self._template, root, dirs_exist_ok=True)
        return root

    def test_check_flags_a_stale_asset_stamp(self):
        import os as _os
        root = self._clone_repo()
        self.assertEqual(bsd.main(["build_site_data.py", "--root", root]), 0)
        self.assertEqual(bsd.main(["build_site_data.py", "--check", "--root", root]), 0)
        with open(_os.path.join(root, "site", "dist", "assets", "styles.css"), "a", encoding="utf-8") as fh:
            fh.write("\n/* mutate without regenerating */\n")
        self.assertEqual(bsd.main(["build_site_data.py", "--check", "--root", root]), 1)

    def test_cli_wrapper_propagates_nonzero_exit_on_drift(self):
        # Regression guard for the CLI entrypoint itself: bsd.main() returns 1 on drift, but the
        # `python scripts/build_site_data.py` wrapper must PROPAGATE that as the process exit code -
        # the `site` CI gate (pages.yml runs `build_site_data.py --check`) relies on the exit code,
        # so a wrapper that swallowed it (bare `main(sys.argv)`) would make the gate toothless.
        import os as _os
        import subprocess
        import sys
        wrapper = _os.path.join(bsd.REPO_ROOT, "scripts", "build_site_data.py")
        if not _os.path.isfile(wrapper):
            self.skipTest("build_site_data.py wrapper not found")
        root = self._clone_repo()
        self.assertEqual(bsd.main(["build_site_data.py", "--root", root]), 0)
        clean = subprocess.run([sys.executable, wrapper, "--check", "--root", root],
                               capture_output=True)
        self.assertEqual(clean.returncode, 0, "a fresh tree must exit 0")
        with open(_os.path.join(root, "site", "dist", "assets", "styles.css"), "a",
                  encoding="utf-8") as fh:
            fh.write("\n/* mutate without regenerating */\n")
        drifted = subprocess.run([sys.executable, wrapper, "--check", "--root", root],
                                 capture_output=True)
        self.assertNotEqual(drifted.returncode, 0,
                            "the CLI wrapper must exit non-zero on drift so the site gate can fail")

    def test_check_flags_a_hand_edited_built_page(self):
        # The clobber guard, end to end through the real CLI: a hand-edit to a built page's STATIC
        # content (not a marker region) must fail --check, because the page is rebuilt from its
        # independent site/pages source. This is the CI gate SITE-BUILD-14 promises.
        import os as _os
        root = self._clone_repo()
        self.assertEqual(bsd.main(["build_site_data.py", "--root", root]), 0)
        self.assertEqual(bsd.main(["build_site_data.py", "--check", "--root", root]), 0)
        page = _os.path.join(root, "site", "dist", "commentable-html", "index.html")
        html = bsd.read_text(page)
        self.assertIn("Why Commentable HTML", html)
        with open(page, "w", encoding="utf-8", newline="") as fh:
            fh.write(html.replace("Why Commentable HTML", "HAND EDITED", 1))
        self.assertEqual(bsd.main(["build_site_data.py", "--check", "--root", root]), 1)

    def test_check_flags_an_orphaned_page_whose_source_was_removed(self):
        # If a page's site source is removed but its built artifact lingers, --check must flag it
        # so the "pure artifact" invariant never silently ignores a stranded page. Capture stderr so
        # the assertion isolates the orphan guard (a --check would also fail from sitemap/llms drift).
        import contextlib
        import io
        import os as _os
        root = self._clone_repo()
        self.assertEqual(bsd.main(["build_site_data.py", "--root", root]), 0)
        self.assertEqual(bsd.main(["build_site_data.py", "--check", "--root", root]), 0)
        _os.remove(_os.path.join(root, bsd.TUTORIAL_PAGE_SRC))
        self.assertTrue(_os.path.exists(_os.path.join(root, bsd.TUTORIAL_PAGE)))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = bsd.main(["build_site_data.py", "--check", "--root", root])
        self.assertEqual(rc, 1)
        self.assertIn("orphaned", err.getvalue())

    def test_check_flags_a_missing_built_page_when_its_source_exists(self):
        # First-build / forgot-to-commit case: the source exists but the built artifact does not.
        import os as _os
        root = self._clone_repo()
        self.assertEqual(bsd.main(["build_site_data.py", "--root", root]), 0)
        self.assertEqual(bsd.main(["build_site_data.py", "--check", "--root", root]), 0)
        _os.remove(_os.path.join(root, bsd.TUTORIAL_PAGE))
        self.assertEqual(bsd.main(["build_site_data.py", "--check", "--root", root]), 1)

    def test_write_removes_an_orphaned_page_whose_source_was_removed(self):
        import os as _os
        root = self._clone_repo()
        self.assertEqual(bsd.main(["build_site_data.py", "--root", root]), 0)
        _os.remove(_os.path.join(root, bsd.TUTORIAL_PAGE_SRC))
        self.assertEqual(bsd.main(["build_site_data.py", "--root", root]), 0)
        self.assertFalse(_os.path.exists(_os.path.join(root, bsd.TUTORIAL_PAGE)))

    def test_removing_tutorial_source_drops_its_llms_link(self):
        # The llms.txt tutorial link is gated on the tutorial source, so removing the source and
        # rebuilding leaves no llms.txt link pointing at the deleted tutorial page.
        import os as _os
        root = self._clone_repo()
        self.assertEqual(bsd.main(["build_site_data.py", "--root", root]), 0)
        llms = _os.path.join(root, "site", "dist", "llms.txt")
        self.assertIn("commentable-html/tutorial/", bsd.read_text(llms))
        _os.remove(_os.path.join(root, bsd.TUTORIAL_PAGE_SRC))
        self.assertEqual(bsd.main(["build_site_data.py", "--root", root]), 0)
        self.assertNotIn("commentable-html/tutorial/", bsd.read_text(llms))

    def test_missing_required_page_source_errors_clearly(self):
        # A hub/plugin page is required: removing its source must raise a clear SystemExit rather
        # than a bare FileNotFoundError traceback (they are not optional like the tutorial).
        import os as _os
        root = self._clone_repo()
        _os.remove(_os.path.join(root, bsd.HUB_SRC))
        with self.assertRaises(SystemExit):
            bsd.main(["build_site_data.py", "--check", "--root", root])

    def test_check_flags_a_missing_built_hub_page(self):
        # The required hub artifact missing (source intact) must be drift, exercising the hub/plugin
        # comparison branch directly (the tutorial-missing test covers only the optional page).
        import os as _os
        root = self._clone_repo()
        self.assertEqual(bsd.main(["build_site_data.py", "--root", root]), 0)
        self.assertEqual(bsd.main(["build_site_data.py", "--check", "--root", root]), 0)
        _os.remove(_os.path.join(root, bsd.HUB_OUT))
        self.assertEqual(bsd.main(["build_site_data.py", "--check", "--root", root]), 1)

    def test_check_flags_a_missing_built_stylesheet_without_crashing(self):
        # A missing site/assets/styles.css must be reported as drift, not crash the build: the page
        # ?v= stamp is derived from the source partials, so build_page never reads the absent file.
        import os as _os
        root = self._clone_repo()
        self.assertEqual(bsd.main(["build_site_data.py", "--root", root]), 0)
        self.assertEqual(bsd.main(["build_site_data.py", "--check", "--root", root]), 0)
        _os.remove(_os.path.join(root, "site", "dist", "assets", "styles.css"))
        self.assertEqual(bsd.main(["build_site_data.py", "--check", "--root", root]), 1)

    def test_styles_asset_hash_ignores_a_stale_on_disk_stylesheet(self):
        # The styles.css cache-bust stamp must come from the SOURCE partials, not the on-disk
        # artifact. With a STALE styles.css on disk, _asset_hash must still return the source-derived
        # hash. This discriminates: a regression back to disk-reading would return the stale hash and
        # fail here (a tautology hashing build_styles on both sides could not catch that).
        import hashlib as _hashlib
        import os as _os
        root = self._clone_repo()
        stale = _os.path.join(root, "site", "dist", "assets", "styles.css")
        with open(stale, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("/* STALE - not the real bundle */\n")
        source_derived = _hashlib.sha256(bsd.build_styles(root).encode("utf-8")).hexdigest()[:12]
        with open(stale, "rb") as fh:
            stale_disk = _hashlib.sha256(fh.read()).hexdigest()[:12]
        self.assertNotEqual(source_derived, stale_disk)  # the two differ, so the test can discriminate
        self.assertEqual(bsd._asset_hash(root, "styles.css"), source_derived)

    def test_build_writes_nested_artifacts_on_a_fresh_checkout_without_site_tree(self):
        # write_text creates parent dirs, so a build with the nested generated page dir removed
        # recreates the plugin and tutorial pages (and their directories) instead of crashing with
        # FileNotFoundError. site/assets (committed, non-generated, e.g. site.js) is left intact.
        import os as _os
        import shutil
        root = self._clone_repo()
        shutil.rmtree(_os.path.join(root, "site", "dist", "commentable-html"))
        self.assertEqual(bsd.main(["build_site_data.py", "--root", root]), 0)
        self.assertTrue(_os.path.isfile(_os.path.join(root, bsd.PLUGIN_OUT)))
        self.assertTrue(_os.path.isfile(_os.path.join(root, bsd.TUTORIAL_PAGE)))

    def test_check_flags_a_hand_edited_built_hub_page(self):
        # The hub page goes through the same build_page/_read_artifact path as the plugin page; prove
        # the whole-page guard at the CLI level for the hub too (SITE-BUILD-14 covers "any built page").
        import os as _os
        root = self._clone_repo()
        self.assertEqual(bsd.main(["build_site_data.py", "--root", root]), 0)
        self.assertEqual(bsd.main(["build_site_data.py", "--check", "--root", root]), 0)
        page = _os.path.join(root, bsd.HUB_OUT)
        html = bsd.read_text(page)
        with open(page, "w", encoding="utf-8", newline="") as fh:
            fh.write(html.replace("</body>", "<p>HAND EDITED</p></body>", 1))
        self.assertEqual(bsd.main(["build_site_data.py", "--check", "--root", root]), 1)

    def test_missing_required_plugin_page_source_errors_clearly(self):
        # Parallel to the hub-source test: removing the plugin page source must also raise SystemExit,
        # so a future refactor cannot break the required-source loop for one page only.
        import os as _os
        root = self._clone_repo()
        _os.remove(_os.path.join(root, bsd.PLUGIN_SRC))
        with self.assertRaises(SystemExit):
            bsd.main(["build_site_data.py", "--check", "--root", root])

    def test_missing_required_auto_updater_page_source_errors_clearly(self):
        # The auto-updater page is a REQUIRED page like the hub/plugin: removing its source must
        # raise a clear SystemExit, not a bare traceback (SITE-UPDATER-01).
        import os as _os
        root = self._clone_repo()
        _os.remove(_os.path.join(root, bsd.UPDATER_SRC))
        with self.assertRaises(SystemExit):
            bsd.main(["build_site_data.py", "--check", "--root", root])

    def test_check_flags_a_hand_edited_built_auto_updater_page(self):
        # The auto-updater page is a pure artifact built from its independent site/pages source, so a
        # hand-edit to its static content must fail --check (SITE-UPDATER-01, same guard as the hub).
        import os as _os
        root = self._clone_repo()
        self.assertEqual(bsd.main(["build_site_data.py", "--root", root]), 0)
        self.assertEqual(bsd.main(["build_site_data.py", "--check", "--root", root]), 0)
        page = _os.path.join(root, bsd.UPDATER_OUT)
        html = bsd.read_text(page)
        with open(page, "w", encoding="utf-8", newline="") as fh:
            fh.write(html.replace("</body>", "<p>HAND EDITED</p></body>", 1))
        self.assertEqual(bsd.main(["build_site_data.py", "--check", "--root", root]), 1)

    def test_auto_updater_page_version_badge_matches_manifest(self):
        # The hero version badge is filled from the manifest at build time (SITE-UPDATER-02), so it
        # never drifts from the shipped plugin version.
        import json as _json
        import os as _os
        root = self._clone_repo()
        self.assertEqual(bsd.main(["build_site_data.py", "--root", root]), 0)
        with open(_os.path.join(root, ".github", "plugin", "marketplace.json"), encoding="utf-8") as fh:
            manifest = _json.load(fh)
        version = bsd.plugin_version(manifest, "urikan-ai-marketplace-auto-updater")
        self.assertTrue(version)
        html = bsd.read_text(_os.path.join(root, bsd.UPDATER_OUT))
        self.assertIn("v" + version, html)

    def test_missing_required_multi_duck_page_source_errors_clearly(self):
        # The multi-duck page is a REQUIRED page like the hub/plugin/updater: removing its source
        # must raise a clear SystemExit, not a bare traceback (SITE-MDUCK-01).
        import os as _os
        root = self._clone_repo()
        _os.remove(_os.path.join(root, bsd.MULTI_DUCK_SRC))
        with self.assertRaises(SystemExit):
            bsd.main(["build_site_data.py", "--check", "--root", root])

    def test_check_flags_a_hand_edited_built_multi_duck_page(self):
        # The multi-duck page is a pure artifact built from its independent site/pages source, so a
        # hand-edit to its static content must fail --check (SITE-MDUCK-01, same guard as the hub).
        import os as _os
        root = self._clone_repo()
        self.assertEqual(bsd.main(["build_site_data.py", "--root", root]), 0)
        self.assertEqual(bsd.main(["build_site_data.py", "--check", "--root", root]), 0)
        page = _os.path.join(root, bsd.MULTI_DUCK_OUT)
        html = bsd.read_text(page)
        with open(page, "w", encoding="utf-8", newline="") as fh:
            fh.write(html.replace("</body>", "<p>HAND EDITED</p></body>", 1))
        self.assertEqual(bsd.main(["build_site_data.py", "--check", "--root", root]), 1)

    def test_multi_duck_page_version_badge_matches_manifest(self):
        # The hero version badge is filled from the manifest at build time (SITE-MDUCK-02), so it
        # never drifts from the shipped plugin version.
        import json as _json
        import os as _os
        root = self._clone_repo()
        self.assertEqual(bsd.main(["build_site_data.py", "--root", root]), 0)
        with open(_os.path.join(root, ".github", "plugin", "marketplace.json"), encoding="utf-8") as fh:
            manifest = _json.load(fh)
        version = bsd.plugin_version(manifest, "multi-duck")
        self.assertTrue(version)
        html = bsd.read_text(_os.path.join(root, bsd.MULTI_DUCK_OUT))
        self.assertIn("v" + version, html)

    def test_missing_manifest_errors_clearly(self):
        # A missing marketplace manifest must raise a clear SystemExit, not a raw FileNotFoundError.
        import os as _os
        root = self._clone_repo()
        _os.remove(_os.path.join(root, ".github", "plugin", "marketplace.json"))
        with self.assertRaises(SystemExit):
            bsd.main(["build_site_data.py", "--check", "--root", root])

    def test_malformed_manifest_errors_clearly(self):
        # A hand-broken manifest (invalid JSON) must raise a clear SystemExit naming the file, not a
        # raw json.JSONDecodeError traceback.
        import os as _os
        root = self._clone_repo()
        mpath = _os.path.join(root, ".github", "plugin", "marketplace.json")
        with open(mpath, "w", encoding="utf-8") as fh:
            fh.write("{ not valid json, }")
        with self.assertRaises(SystemExit):
            bsd.main(["build_site_data.py", "--check", "--root", root])

    def test_missing_required_site_js_asset_errors_clearly(self):
        # site.js is a committed (non-generated) cache-busted asset: if it is deleted, the build must
        # fail loudly with a clear SystemExit rather than silently stamping or a raw traceback.
        import os as _os
        root = self._clone_repo()
        _os.remove(_os.path.join(root, "site", "dist", "assets", "site.js"))
        with self.assertRaises(SystemExit):
            bsd.main(["build_site_data.py", "--check", "--root", root])

    def test_removing_tutorial_source_drops_its_sitemap_entry(self):
        # Parallel to the llms.txt gating: removing the tutorial source and rebuilding must drop the
        # tutorial <loc> from sitemap.xml (the SITE-BUILD-14 sitemap-gating claim).
        import os as _os
        root = self._clone_repo()
        self.assertEqual(bsd.main(["build_site_data.py", "--root", root]), 0)
        sitemap = _os.path.join(root, "site", "dist", "sitemap.xml")
        self.assertIn("commentable-html/tutorial/", bsd.read_text(sitemap))
        _os.remove(_os.path.join(root, bsd.TUTORIAL_PAGE_SRC))
        self.assertEqual(bsd.main(["build_site_data.py", "--root", root]), 0)
        self.assertNotIn("commentable-html/tutorial/", bsd.read_text(sitemap))

class PageBannerAndGuardTests(unittest.TestCase):
    """Site pages are pure artifacts built from site/pages/ sources and carry a DO NOT EDIT
    banner; a hand-edit to a built page is caught by comparing it to a fresh build (SITE-BUILD-14)."""

    def _mktemp(self):
        import shutil
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        return d

    def test_page_banner_names_source_and_says_do_not_edit(self):
        b = bsd.page_banner(os.path.join("site", "pages", "index.html"))
        self.assertIn("DO NOT EDIT", b)
        self.assertIn("site/pages/index.html", b)  # forward slashes even on Windows
        self.assertIn("build_site_data.py", b)

    def test_css_banner_says_do_not_edit(self):
        b = bsd.css_banner()
        self.assertIn("DO NOT EDIT", b)
        self.assertTrue(b.lstrip().startswith("/*"))

    def test_apply_page_banner_inserts_after_doctype_and_is_idempotent(self):
        html = "<!DOCTYPE html>\n<html><head></head><body></body></html>\n"
        once = bsd.apply_page_banner(html, "site/pages/index.html")
        self.assertRegex(once, r"^<!DOCTYPE html>\n<!-- GENERATED FILE - DO NOT EDIT\.")
        # Re-applying replaces the prior banner instead of stacking a second one.
        twice = bsd.apply_page_banner(once, "site/pages/index.html")
        self.assertEqual(once, twice)
        self.assertEqual(twice.count(bsd.GENERATED_BANNER_PREFIX), 1)

    def test_apply_page_banner_leaves_a_body_comment_with_the_banner_prefix(self):
        # Only the banner in the slot right after the doctype is replaced; a comment elsewhere in
        # the page body that happens to start with the banner prefix must NOT be stripped.
        body_comment = "<!-- %s real body content -->" % bsd.GENERATED_BANNER_PREFIX
        html = "<!DOCTYPE html>\n<html><body>\n%s\n</body></html>\n" % body_comment
        out = bsd.apply_page_banner(html, "site/pages/index.html")
        self.assertIn(body_comment, out)
        self.assertEqual(out.count(bsd.GENERATED_BANNER_PREFIX), 2)  # slot banner + body comment
        self.assertEqual(out, bsd.apply_page_banner(out, "site/pages/index.html"))  # idempotent

    def test_apply_page_banner_tolerates_a_doctype_with_attributes(self):
        html = '<!DOCTYPE html SYSTEM "about:legacy-compat">\n<html></html>\n'
        out = bsd.apply_page_banner(html, "site/pages/index.html")
        # The banner goes AFTER the doctype (never before it, which would trip quirks mode).
        self.assertRegex(
            out, r'^<!DOCTYPE html SYSTEM "about:legacy-compat">\n<!-- GENERATED FILE - DO NOT EDIT\.')

    def _write_source(self, root):
        src_rel = os.path.join("site", "pages", "x.html")
        os.makedirs(os.path.join(root, "site", "pages"))
        with open(os.path.join(root, src_rel), "w", encoding="utf-8", newline="") as fh:
            fh.write("<!DOCTYPE html>\n<html><body>\n<h1>Real title</h1>\n"
                     "<!-- BEGIN:plugins -->OLD<!-- END:plugins -->\n</body></html>\n")
        return src_rel

    def test_build_page_fills_region_and_banners(self):
        root = self._mktemp()
        src_rel = self._write_source(root)
        art = bsd.build_page(root, src_rel, [("block", "plugins", "GRID")])
        self.assertIn("DO NOT EDIT", art)
        self.assertIn("<h1>Real title</h1>", art)
        self.assertIn("GRID", art)
        self.assertNotIn("OLD", art)

    def test_check_catches_a_hand_edit_to_the_built_page(self):
        # A hand-edit to the built page's STATIC content (not a marker region) differs from a fresh
        # build of its independent source. This is the guard that closes the site clobber gap: the
        # static content used to be self-sourced and invisible to --check.
        root = self._mktemp()
        src_rel = self._write_source(root)
        out_path = os.path.join(root, "site", "x.html")
        os.makedirs(os.path.join(root, "site"), exist_ok=True)
        fillers = [("block", "plugins", "GRID")]
        art = bsd.build_page(root, src_rel, fillers)
        with open(out_path, "w", encoding="utf-8", newline="") as fh:
            fh.write(art)
        # In sync: a fresh build equals the committed artifact.
        self.assertEqual(bsd.build_page(root, src_rel, fillers), bsd._read_artifact(out_path))
        # Hand-edit the built page -> it no longer equals a fresh build (drift is detected).
        with open(out_path, "w", encoding="utf-8", newline="") as fh:
            fh.write(art.replace("Real title", "HACKED"))
        self.assertNotEqual(bsd.build_page(root, src_rel, fillers), bsd._read_artifact(out_path))

    def test_missing_artifact_counts_as_drift(self):
        self.assertIsNone(bsd._read_artifact(os.path.join(self._mktemp(), "nope.html")))

    def test_write_text_creates_missing_parent_dirs(self):
        # Isolated proof of the makedirs behavior: writing into a not-yet-existing nested path works.
        root = self._mktemp()
        target = os.path.join(root, "deep", "nested", "page.html")
        bsd.write_text(target, "hello\n")
        self.assertEqual(bsd.read_text(target), "hello\n")

    def test_write_text_errors_clearly_when_a_parent_is_a_file(self):
        # A malformed tree where a parent path is a regular file must raise a clear SystemExit
        # (path conflict) instead of a raw NotADirectoryError/FileExistsError traceback.
        root = self._mktemp()
        blocker = os.path.join(root, "blocker")
        with open(blocker, "w", encoding="utf-8") as fh:
            fh.write("i am a file, not a directory")
        target = os.path.join(blocker, "child", "page.html")
        with self.assertRaises(SystemExit):
            bsd.write_text(target, "hello\n")

    def test_build_page_rejects_an_unknown_region_kind(self):
        # build_page only knows "block" (and historically "attr") region kinds; an unknown kind must
        # fail loudly rather than silently leave the marker unfilled in the shipped artifact.
        root = self._mktemp()
        src_rel = self._write_source(root)
        with self.assertRaises(SystemExit):
            bsd.build_page(root, src_rel, [("bogus", "plugins", "GRID")])

    def test_build_page_rejects_a_source_without_a_doctype(self):
        # Every shipped page must start with a doctype so the banner has a slot; a source missing it
        # must raise rather than emit a page the banner cannot be applied to.
        root = self._mktemp()
        os.makedirs(os.path.join(root, "site", "pages"))
        src_rel = os.path.join("site", "pages", "y.html")
        with open(os.path.join(root, src_rel), "w", encoding="utf-8", newline="") as fh:
            fh.write("<html><body><h1>No doctype</h1></body></html>\n")
        with self.assertRaises(SystemExit):
            bsd.build_page(root, src_rel, [])

    def test_build_page_rejects_a_source_with_two_doctypes(self):
        # A duplicated <!doctype> is the classic malformed-merge artifact: it would build and match
        # its committed copy (passing --check) while shipping invalid HTML, so reject it at build.
        root = self._mktemp()
        os.makedirs(os.path.join(root, "site", "pages"))
        src_rel = os.path.join("site", "pages", "dup.html")
        with open(os.path.join(root, src_rel), "w", encoding="utf-8", newline="") as fh:
            fh.write("<!DOCTYPE html>\n<html><body>\n<!DOCTYPE html>\n</body></html>\n")
        with self.assertRaises(SystemExit):
            bsd.build_page(root, src_rel, [])

    def test_build_page_allows_a_literal_doctype_inside_content(self):
        # The duplicate-doctype guard counts only LINE-LEADING declarations, so a literal "<!doctype"
        # embedded in a script string or in prose (a real HTML-tooling page could carry one) does not
        # false-trip the guard.
        root = self._mktemp()
        os.makedirs(os.path.join(root, "site", "pages"))
        src_rel = os.path.join("site", "pages", "lit.html")
        with open(os.path.join(root, src_rel), "w", encoding="utf-8", newline="") as fh:
            fh.write('<!DOCTYPE html>\n<html><body>\n'
                     '<script>var s = "<!doctype html>";</script>\n'
                     '<p>Type <!doctype html> to start a page.</p>\n'
                     '</body></html>\n')
        art = bsd.build_page(root, src_rel, [])
        self.assertIn('var s = "<!doctype html>";', art)  # the literal survived; no SystemExit

    def test_build_styles_errors_on_a_missing_css_directory(self):
        # A missing site/css/ directory must raise a clear SystemExit, not a raw OSError.
        root = self._mktemp()
        with self.assertRaises(SystemExit):
            bsd.build_styles(root)

    def test_build_styles_errors_on_an_empty_css_directory(self):
        # A directory that EXISTS but holds no `.css` partials must fail loudly rather than emit a
        # banner-only stylesheet (mirrors build.ordered_parts on the commentable-html side).
        root = self._mktemp()
        os.makedirs(os.path.join(root, "site", "css"))
        with self.assertRaises(SystemExit):
            bsd.build_styles(root)

    def test_build_styles_strips_a_bom_from_a_css_partial(self):
        # A BOM saved into any CSS partial must not land inside the concatenated bundle (it would sit
        # mid-file and can break CSS parsing); build_styles strips it like build_page does for pages.
        root = self._mktemp()
        css_dir = os.path.join(root, "site", "css")
        os.makedirs(css_dir)
        names = ["10-base.css", "20-mid.css", "30-tail.css"]
        for i, name in enumerate(names):
            enc = "utf-8-sig" if i == 1 else "utf-8"  # a BOM on a non-first partial is the worst case.
            with open(os.path.join(css_dir, name), "w", encoding=enc, newline="") as fh:
                fh.write("/* %s */\n" % name)
        built = bsd.build_styles(root)
        self.assertNotIn("\ufeff", built)
        # A source saved with a UTF-8 BOM still builds (the BOM is stripped before the doctype check),
        # and the built artifact never carries the BOM into the shipped page.
        root = self._mktemp()
        os.makedirs(os.path.join(root, "site", "pages"))
        src_rel = os.path.join("site", "pages", "bom.html")
        with open(os.path.join(root, src_rel), "w", encoding="utf-8-sig", newline="") as fh:
            fh.write("<!DOCTYPE html>\n<html><body><h1>BOM</h1></body></html>\n")
        art = bsd.build_page(root, src_rel, [])
        self.assertFalse(art.startswith("\ufeff"))
        self.assertRegex(art, r"^<!DOCTYPE html>\n<!-- %s" % bsd.GENERATED_BANNER_PREFIX)

    def test_committed_page_sources_are_banner_free(self):
        # The editable sources under site/pages must NOT carry the generated banner; the banner
        # is injected only into the built artifact. If a source picked one up, a rebuild would be a
        # no-op on the banner line and hand-edits could hide there.
        for rel in (bsd.HUB_SRC, bsd.PLUGIN_SRC, bsd.TUTORIAL_PAGE_SRC):
            src = os.path.join(bsd.REPO_ROOT, rel)
            if not os.path.exists(src):
                continue
            self.assertNotIn(bsd.GENERATED_BANNER_PREFIX, bsd.read_text(src),
                             "%s must not contain the generated banner" % rel)

    def test_committed_stylesheet_carries_the_banner(self):
        css = os.path.join(bsd.REPO_ROOT, "site", "dist", "assets", "styles.css")
        self.assertIn("DO NOT EDIT", bsd.read_text(css))


if __name__ == "__main__":
    unittest.main()
