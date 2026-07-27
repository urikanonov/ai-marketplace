#!/usr/bin/env python3
"""CMH-BUILD-16: tests for tools/shots_linux.py (one container renderer, locally and in CI).

The committed tutorial PNGs are rendered by a browser, and font rasterization is decided by the OS
image that browser runs on. So there is exactly ONE renderer on both sides - the digest-pinned
Playwright container - and these tests pin that: no host fast path, no second CI renderer, an
immutable digest rather than a mutable tag, and a required gate that cannot skip itself.
"""
import json
import os
import re
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402
sys.path.insert(0, _paths.DEV_TOOLS)
import shots_linux as S  # noqa: E402


def _dev_tree(tmp, version="1.61.1", with_deps=True):
    """A minimal dev/ tree: a package-lock pinning @playwright/test and optional node_modules."""
    lock = {"packages": {"": {"name": "commentable-html-dev"},
                         "node_modules/@playwright/test": {"version": version}}}
    with open(os.path.join(tmp, "package-lock.json"), "w", encoding="utf-8") as fh:
        json.dump(lock, fh)
    if with_deps:
        os.makedirs(os.path.join(tmp, "node_modules", "@playwright", "test"), exist_ok=True)
    return tmp


class PinnedVersionTests(unittest.TestCase):
    def test_version_comes_from_the_lockfile_not_a_semver_range(self):
        # package.json carries "^1.61.1"; the RESOLVED lockfile version is what the suite actually
        # runs, so it is the only value that keeps the image and the renderer in lockstep.
        with tempfile.TemporaryDirectory() as tmp:
            _dev_tree(tmp, version="1.61.1")
            self.assertEqual(S.pinned_playwright_version(tmp), "1.61.1")

    def test_a_missing_or_malformed_lockfile_is_reported_not_guessed(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(S.ShotsError):
                S.pinned_playwright_version(tmp)
            with open(os.path.join(tmp, "package-lock.json"), "w", encoding="utf-8") as fh:
                json.dump({"packages": {}}, fh)
            with self.assertRaises(S.ShotsError):
                S.pinned_playwright_version(tmp)

    def test_the_real_repo_lockfile_resolves(self):
        self.assertRegex(S.pinned_playwright_version(_paths.DEV), r"^\d+\.\d+\.\d+")


class ImageRefTests(unittest.TestCase):
    def test_tag_is_derived_from_the_version_and_the_pinned_ubuntu_variant(self):
        self.assertEqual(S.image_ref("1.61.1"), "mcr.microsoft.com/playwright:v1.61.1-noble")

    def test_a_different_pinned_version_yields_a_different_image(self):
        # The determinism guarantee: bump the dependency and the renderer follows automatically.
        self.assertNotEqual(S.image_ref("1.61.1"), S.image_ref("1.62.0"))


class DockerCommandTests(unittest.TestCase):
    def test_command_mounts_the_repo_and_runs_the_capture_in_the_dev_dir(self):
        cmd = S.docker_command("/repo", "plugins/commentable-html/dev", "img:tag", [])
        self.assertEqual(cmd[:3], ["docker", "run", "--rm"])
        self.assertIn("/repo:/repo", cmd)
        self.assertIn("img:tag", cmd)
        joined = " ".join(cmd)
        self.assertIn("capture_tutorial.mjs", joined)
        # The container works inside the mounted repo, so it writes the PNGs back to the worktree.
        self.assertIn("-w", cmd)
        self.assertIn("/repo/plugins/commentable-html/dev", cmd)

    def test_extra_args_are_forwarded_to_the_capture_script(self):
        cmd = S.docker_command("/repo", "plugins/commentable-html/dev", "img:tag", ["--check"])
        self.assertIn("--check", " ".join(cmd))

    def test_a_host_path_with_spaces_cannot_break_the_inner_shell(self):
        # The host path lands ONLY in the -v argv element, which docker receives verbatim (no shell
        # involved). The `bash -lc` string uses the fixed in-container path, so a Windows checkout
        # under "C:\Users\My Name\..." cannot split the command.
        cmd = S.docker_command("/repo/My Repo", "plugins/commentable-html/dev", "img:tag", [])
        self.assertIn("/repo/My Repo:/repo", cmd)
        shell_script = cmd[-1]
        self.assertNotIn("My Repo", shell_script)
        self.assertIn("/repo/plugins/commentable-html/dev", shell_script)

    def test_forwarded_args_are_shell_quoted(self):
        cmd = S.docker_command("/repo", "plugins/commentable-html/dev", "img:tag", ["--check; rm -rf /"])
        self.assertIn("'--check; rm -rf /'", cmd[-1])

    def test_a_ci_run_forwards_the_ci_marker_into_the_container(self):
        # capture_tutorial.mjs doubles its settle deadlines when CI is set. Docker does not inherit
        # the host environment, so without this the CI render would silently get the SHORTER
        # deadlines - the tighter, flakier setting - on the required gate.
        cmd = S.docker_command("/repo", "dev", "img:tag", [], None, ci=True)
        self.assertIn("-e", cmd)
        self.assertIn("CI=true", cmd)
        self.assertNotIn("CI=true", S.docker_command("/repo", "dev", "img:tag", [], None))

    def test_a_linux_host_runs_the_container_as_the_invoking_user(self):
        # Otherwise every PNG the container rewrites, and the scratch dir it creates, is left
        # root-owned in the worktree and a later native run cannot clean up after it.
        cmd = S.docker_command("/repo", "dev", "img:tag", [], (1000, 1000))
        self.assertIn("--user", cmd)
        self.assertEqual(cmd[cmd.index("--user") + 1], "1000:1000")
        # Docker Desktop already maps ownership, so no --user is passed where uid/gid do not exist.
        self.assertNotIn("--user", S.docker_command("/repo", "dev", "img:tag", [], None))

    def test_only_a_linux_host_maps_the_invoking_user(self):
        # os.getuid EXISTS on macOS, so keying on it alone would hand Docker Desktop a uid (501)
        # that has no passwd entry in the image. Ownership of the bind mount only needs fixing on a
        # native Linux daemon; everywhere else the desktop VM already maps it.
        with mock.patch.object(S.sys, "platform", "darwin"), \
                mock.patch.object(S.os, "getuid", create=True, return_value=501), \
                mock.patch.object(S.os, "getgid", create=True, return_value=20):
            self.assertIsNone(S._host_uid_gid())
        with mock.patch.object(S.sys, "platform", "linux"), \
                mock.patch.object(S.os, "getuid", create=True, return_value=1001), \
                mock.patch.object(S.os, "getgid", create=True, return_value=1001):
            self.assertEqual(S._host_uid_gid(), (1001, 1001))

    def test_every_run_pins_a_writable_home_and_shares_the_hosts_ipc(self):
        # HOME: with --user the invoking uid may have no passwd entry, and docker then points HOME
        # at an unwritable "/" - pinning it keeps every run (CI included) identical and writable,
        # instead of depending on the runner uid happening to match a user in the image.
        # --ipc=host: the image's documented invocation. The default 64MB /dev/shm can crash
        # chromium mid-capture, which would red the required gate with an unreproducible stack.
        cmd = S.docker_command("/repo", "dev", "img:tag", [])
        self.assertIn("HOME=/tmp", cmd)
        self.assertIn("--ipc=host", cmd)

    def test_wrapper_flags_are_not_matched_by_abbreviation(self):
        # Unknown args are forwarded to capture_tutorial.mjs. With argparse's default abbreviation
        # matching, a future capture flag that merely PREFIXES a wrapper flag ('--nat', '--rec')
        # would be swallowed by the wrapper instead of reaching the capture script.
        with mock.patch.object(S, "_in_ci", return_value=False), \
                mock.patch.object(S.shutil, "which", return_value="/usr/bin/docker"), \
                mock.patch.object(S, "_docker_daemon_ok", return_value=True), \
                mock.patch.object(S, "_deps_installed", return_value=True), \
                mock.patch.object(S, "_run", return_value=0) as run:
            rc = S.main(["shots_linux.py", "--nat"])
        self.assertEqual(rc, 0)
        cmd = run.call_args[0][0]
        self.assertEqual(cmd[0], "docker", "--nat must not be read as --native")
        self.assertIn("--nat", cmd[-1])

    def test_extra_capture_arguments_reach_the_capture_script(self):
        # capture_tutorial.mjs accepts [example] [outDir] [prefix] and --print-paths. Without
        # passthrough a single-scene recapture would still need the raw, unguarded command.
        with mock.patch.object(S, "_in_ci", return_value=False), \
                mock.patch.object(S.shutil, "which", return_value="/usr/bin/docker"), \
                mock.patch.object(S, "_docker_daemon_ok", return_value=True), \
                mock.patch.object(S, "_deps_installed", return_value=True), \
                mock.patch.object(S, "_run", return_value=0) as run:
            rc = S.main(["shots_linux.py", "--print-paths", "examples/report-checklist.html"])
        self.assertEqual(rc, 0)
        joined = " ".join(run.call_args[0][0])
        self.assertIn("--print-paths", joined)
        self.assertIn("examples/report-checklist.html", joined)


class RendererDispatchTests(unittest.TestCase):
    """ONE renderer by construction: the pinned container renders on every host, CI included."""

    def _dispatch(self, argv, ci=False, docker=True):
        def which(name):
            if name == "docker" and not docker:
                return None
            return "/usr/bin/" + name
        with mock.patch.object(S, "_in_ci", return_value=ci), \
                mock.patch.object(S.shutil, "which", side_effect=which), \
                mock.patch.object(S, "_docker_daemon_ok", return_value=True), \
                mock.patch.object(S, "_deps_installed", return_value=True), \
                mock.patch.object(S, "_run", return_value=0) as run:
            rc = S.main(argv)
        return rc, run

    def test_every_host_renders_in_the_pinned_container(self):
        # There is no host fast path any more: Windows, macOS and Linux all render in the same
        # image, so no host's font/fontconfig packages can decide the pixels. Only the ownership
        # mapping differs, and only on Linux.
        for host, uid_gid in (("win32", None), ("darwin", None), ("linux", (1001, 1001))):
            with mock.patch.object(S.sys, "platform", host), \
                    mock.patch.object(S, "_host_uid_gid", return_value=uid_gid):
                rc, run = self._dispatch(["shots_linux.py"])
            self.assertEqual(rc, 0, host)
            cmd = run.call_args[0][0]
            self.assertEqual(cmd[0], "docker", host)
            self.assertEqual("--user" in cmd, uid_gid is not None, host)

    def test_the_capture_script_is_told_which_renderer_invoked_it(self):
        # capture_tutorial.mjs refuses to touch the COMMITTED screenshots unless a renderer marker
        # says the guarded wrapper drove it, so a raw `node capture_tutorial.mjs` cannot rewrite or
        # "verify" them with this machine's fonts. Both wrapper paths therefore set the marker.
        cmd = S.docker_command("/repo", "dev", "img:tag", [])
        self.assertIn("%s=container" % S.RENDERER_ENV, cmd)
        with mock.patch.object(S, "_in_ci", return_value=False), \
                mock.patch.object(S.shutil, "which", return_value="/usr/bin/node"), \
                mock.patch.object(S, "_deps_installed", return_value=True), \
                mock.patch.object(S, "_run", return_value=0) as run:
            import io
            import contextlib
            with contextlib.redirect_stderr(io.StringIO()):
                rc = S.main(["shots_linux.py", "--native"])
        self.assertEqual(rc, 0)
        self.assertEqual(run.call_args[1]["env"][S.RENDERER_ENV], "native")

    def test_ci_renders_in_the_same_container_a_developer_uses(self):
        # The heart of this design: CI is no longer a SECOND renderer that must agree with the
        # container by convention (a pinned runner LABEL is not an immutable image, and GitHub
        # updates that image's fonts over time). It IS the container, so drift is impossible.
        rc_ci, ci_run = self._dispatch(["shots_linux.py", "--check"], ci=True)
        rc_dev, dev_run = self._dispatch(["shots_linux.py", "--check"], ci=False)
        self.assertEqual((rc_ci, rc_dev), (0, 0))
        ci_cmd, dev_cmd = ci_run.call_args[0][0], dev_run.call_args[0][0]
        self.assertEqual(ci_cmd[0], "docker")
        self.assertIn("mcr.microsoft.com/playwright", " ".join(ci_cmd))
        # Identical apart from the CI marker that only scales the capture's settle deadlines: same
        # image, same platform, same mount, same command line.
        stripped = list(ci_cmd)
        i = stripped.index("CI=true")
        del stripped[i - 1:i + 1]
        self.assertEqual(stripped, dev_cmd)

    def test_the_host_platform_probe_is_gone(self):
        # `host_matches_ci_renderer()` accepted ANY x86_64 Ubuntu 24.04 host as "the CI renderer",
        # but /etc/os-release says nothing about the installed font/fontconfig/rasterizer packages.
        # Structural guard: the probe must not come back as a silent fast path.
        self.assertFalse(hasattr(S, "host_matches_ci_renderer"))
        self.assertFalse(hasattr(S, "UBUNTU_RELEASES"))

    def test_native_rendering_is_an_explicit_opt_in_that_declares_itself_unofficial(self):
        import io
        import contextlib
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc, run = self._dispatch(["shots_linux.py", "--native"])
        self.assertEqual(rc, 0)
        cmd = run.call_args[0][0]
        self.assertNotIn("docker", cmd[0])
        self.assertIn("capture_tutorial.mjs", " ".join(cmd))
        warning = err.getvalue().lower()
        self.assertIn("--native", warning)
        self.assertIn("not the authoritative renderer", warning)

    def test_a_truthy_ci_env_is_what_forbids_skipping(self):
        # _in_ci() no longer picks a renderer - it only means "this is a gate that must not skip".
        for truthy in ("true", "1", "yes"):
            with mock.patch.dict(os.environ, {"CI": truthy}, clear=False):
                self.assertTrue(S._in_ci(), "CI=%r is a CI runner" % truthy)
        for falsy in ("", "0", "false", "no"):
            with mock.patch.dict(os.environ, {"CI": falsy}, clear=False):
                self.assertFalse(S._in_ci(), "CI=%r must not count as a CI runner" % falsy)


class IndicativeErrorTests(unittest.TestCase):
    """Each failure mode must name what is missing AND what to do about it."""

    def setUp(self):
        # Hermetic: `_in_ci()` is true when this suite runs on a CI runner, and CI is forbidden to
        # skip - these cases assert the DEVELOPER-facing failure text, not the CI gate.
        patcher = mock.patch.object(S, "_in_ci", return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _stderr_of(self, **patches):
        import io
        import contextlib
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            with contextlib.ExitStack() as stack:
                for target, kwargs in patches.items():
                    stack.enter_context(mock.patch.object(S, target, **kwargs))
                rc = S.main(["shots_linux.py"])
        return rc, err.getvalue()

    def test_missing_docker_explains_why_it_is_needed_and_how_to_proceed(self):
        rc, msg = self._stderr_of(shutil=dict(which=mock.Mock(return_value=None)),
                                  _deps_installed=dict(return_value=True))
        self.assertNotEqual(rc, 0)
        self.assertIn("Docker", msg)
        self.assertIn("not installed", msg.lower())
        # It must say WHY docker is involved at all, name the exact image, and offer the way out.
        self.assertIn("pinned", msg.lower())
        self.assertIn("mcr.microsoft.com/playwright", msg)
        self.assertIn("npm run shots", msg)
        self.assertIn("docs/testing-guidelines.md", msg)

    def test_a_stopped_docker_daemon_is_distinguished_from_a_missing_docker(self):
        rc, msg = self._stderr_of(shutil=dict(which=mock.Mock(return_value="/usr/bin/docker")),
                                  _docker_daemon_ok=dict(return_value=False),
                                  _deps_installed=dict(return_value=True))
        self.assertNotEqual(rc, 0)
        self.assertIn("daemon", msg.lower())
        self.assertNotIn("not installed", msg.lower())

    def test_a_wedged_daemon_probe_gives_up_instead_of_hanging(self):
        # `docker version` against a wedged or remote daemon can block forever; in CI that would
        # burn the whole job timeout instead of failing fast with the actionable message.
        with mock.patch.object(S.subprocess, "run",
                               side_effect=S.subprocess.TimeoutExpired("docker", 20)):
            self.assertFalse(S._docker_daemon_ok())

    def test_missing_node_modules_points_at_setup_dev(self):
        rc, msg = self._stderr_of(shutil=dict(which=mock.Mock(return_value="/usr/bin/docker")),
                                  _docker_daemon_ok=dict(return_value=True),
                                  _deps_installed=dict(return_value=False))
        self.assertNotEqual(rc, 0)
        self.assertIn("setup_dev.py", msg)

    def test_the_deps_message_does_not_mention_the_container_on_the_native_path(self):
        # A fresh-clone Linux contributor never touches Docker; telling them the container reuses
        # their node_modules is confusing and wrong.
        self.assertNotIn("container", S._deps_missing_message(native=True))
        self.assertIn("container", S._deps_missing_message(native=False))


class NpmScriptWiringTests(unittest.TestCase):
    def test_package_json_exposes_one_shots_command_and_the_digest_recorder(self):
        with open(os.path.join(_paths.DEV, "package.json"), encoding="utf-8") as fh:
            scripts = json.load(fh)["scripts"]
        for name in ("shots", "shots:check", "shots:digest"):
            self.assertIn(name, scripts)
            self.assertIn("shots_linux.py", scripts[name])
        self.assertIn("--check", scripts["shots:check"])
        self.assertIn("--record-digest", scripts["shots:digest"])

    def test_the_habitual_shots_scripts_route_through_the_guard(self):
        # The motivating trap was that the SHORT, habitual command silently produced host-rendered
        # PNGs. Leaving `shots` pointed straight at the raw capture would re-open it, so both
        # legacy scripts go through shots_linux.py.
        with open(os.path.join(_paths.DEV, "package.json"), encoding="utf-8") as fh:
            scripts = json.load(fh)["scripts"]
        self.assertIn("shots_linux.py", scripts["shots"])
        self.assertIn("shots_linux.py", scripts["shots:check"])
        # `npm test` runs shots:check; it must not hard-fail on a dev laptop with no Docker.
        self.assertIn("--skip-without-renderer", scripts["shots:check"])
        self.assertIn("shots:check", scripts["test"])
        # No script may opt out of the one renderer behind the maintainer's back.
        for name, body in scripts.items():
            self.assertNotIn("--native", body, "%s must not bake in the unofficial renderer" % name)

    def test_no_script_or_doc_hardcodes_the_container_image_tag(self):
        # A hardcoded tag is the drift this tool exists to prevent: it would keep pointing at an old
        # renderer after a Playwright bump.
        with open(os.path.join(_paths.DEV, "package.json"), encoding="utf-8") as fh:
            raw = fh.read()
        self.assertNotIn("mcr.microsoft.com/playwright", raw)
        self.assertNotIn("mcr.microsoft.com/playwright", _workflow_text(),
                         "CI must resolve the image through the tool, not pin a second tag")


class SkipWithoutRendererTests(unittest.TestCase):
    def _check(self, argv, ci=False, docker=True, daemon=True):
        import io
        import contextlib
        out, err = io.StringIO(), io.StringIO()

        def which(name):
            if name == "docker" and not docker:
                return None
            return "/usr/bin/" + name
        with mock.patch.object(S, "_in_ci", return_value=ci), \
                mock.patch.object(S.shutil, "which", side_effect=which), \
                mock.patch.object(S, "_docker_daemon_ok", return_value=daemon), \
                mock.patch.object(S, "_deps_installed", return_value=True), \
                mock.patch.object(S, "_run", return_value=0) as run:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = S.main(argv)
        return rc, run, out.getvalue(), err.getvalue()

    def test_check_skips_cleanly_when_the_pinned_renderer_cannot_run(self):
        # `npm test` runs this. Docker stays an OPTIONAL developer dependency: without it the
        # check skips with a note instead of hard-failing a suite that has nothing to do with it.
        rc, run, out, _ = self._check(
            ["shots_linux.py", "--check", "--skip-without-renderer"], docker=False)
        self.assertEqual(rc, 0)
        run.assert_not_called()
        self.assertIn("skipped", out.lower())
        self.assertIn("docker", out.lower())
        self.assertIn("npm run shots:check", out)

    def test_a_stopped_daemon_also_skips_rather_than_false_failing(self):
        rc, run, out, _ = self._check(
            ["shots_linux.py", "--check", "--skip-without-renderer"], daemon=False)
        self.assertEqual(rc, 0)
        run.assert_not_called()
        self.assertIn("skipped", out.lower())

    def test_ci_never_skips_the_required_gate(self):
        # Fail CLOSED where it matters: in CI a renderer that cannot start must RED the job, never
        # quietly pass, or the drift gate silently disappears.
        rc, run, out, err = self._check(
            ["shots_linux.py", "--check", "--skip-without-renderer"], ci=True, docker=False)
        self.assertNotEqual(rc, 0)
        run.assert_not_called()
        self.assertNotIn("skipped", out.lower())
        self.assertIn("Docker", err)

    def test_the_renderer_still_runs_when_docker_is_present(self):
        rc, run, _, _ = self._check(["shots_linux.py", "--check", "--skip-without-renderer"])
        self.assertEqual(rc, 0)
        run.assert_called_once()

    def test_the_write_path_never_silently_skips(self):
        # Regenerating is the dangerous direction: it must produce a correct PNG or refuse loudly.
        rc, run, _, _ = self._check(["shots_linux.py", "--skip-without-renderer"], docker=False)
        self.assertNotEqual(rc, 0)
        run.assert_not_called()


class ContainerPinningTests(unittest.TestCase):
    TAG = "mcr.microsoft.com/playwright:v1.61.1-noble"
    DIGEST = "sha256:" + "a" * 64

    def test_the_container_run_pins_the_amd64_platform(self):
        # The playwright image is multi-arch. On Apple Silicon docker would otherwise select arm64
        # and render with a different rasterizer than the x86_64 image CI runs.
        cmd = S.docker_command("/repo", "plugins/commentable-html/dev", "img:tag", [])
        self.assertIn("--platform", cmd)
        self.assertEqual(cmd[cmd.index("--platform") + 1], "linux/amd64")

    def test_a_matching_lock_pins_the_renderer_by_digest(self):
        # A tag is mutable - the registry can rebuild v<ver>-noble on a newer base OS with different
        # font packages. The digest makes the renderer immutable on BOTH sides.
        ref, warning = S.resolved_image(self.TAG, {"image": self.TAG, "digest": self.DIGEST})
        self.assertEqual(ref, "mcr.microsoft.com/playwright@" + self.DIGEST)
        self.assertIsNone(warning)

    def test_a_stale_lock_falls_back_to_the_tag_and_says_how_to_repin(self):
        # A @playwright/test bump must not HARD-BREAK rendering; it degrades to the tag and says so.
        ref, warning = S.resolved_image(
            self.TAG, {"image": "mcr.microsoft.com/playwright:v1.60.0-noble", "digest": self.DIGEST})
        self.assertEqual(ref, self.TAG)
        self.assertIn("shots:digest", warning)

    def test_ci_refuses_to_render_with_an_unpinned_tag(self):
        # Degrading to a mutable tag is a developer convenience, never a CI behaviour: in CI the
        # renderer must be the exact recorded image or the job fails loudly, so a run can never
        # validate the screenshots against whatever the registry is serving that day.
        import io
        import contextlib
        err = io.StringIO()
        with mock.patch.object(S, "_in_ci", return_value=True), \
                mock.patch.object(S, "read_image_lock", return_value={}), \
                mock.patch.object(S.shutil, "which", return_value="/usr/bin/docker"), \
                mock.patch.object(S, "_docker_daemon_ok", return_value=True), \
                mock.patch.object(S, "_deps_installed", return_value=True), \
                mock.patch.object(S, "_run", return_value=0) as run:
            with contextlib.redirect_stderr(err):
                rc = S.main(["shots_linux.py", "--check", "--skip-without-renderer"])
        self.assertNotEqual(rc, 0)
        run.assert_not_called()
        self.assertIn("shots:digest", err.getvalue())
        # --print-image fails the same way, so the CI pull step reds before the render is attempted.
        err = io.StringIO()
        with mock.patch.object(S, "_in_ci", return_value=True), \
                mock.patch.object(S, "read_image_lock", return_value={}):
            with contextlib.redirect_stderr(err):
                rc = S.main(["shots_linux.py", "--print-image"])
        self.assertNotEqual(rc, 0)

    def test_a_developer_can_still_render_after_a_bump_before_re_recording(self):
        # Outside CI the same situation is a WARNING plus a render on the tag, so a Playwright bump
        # never leaves a contributor unable to regenerate.
        import io
        import contextlib
        err = io.StringIO()
        with mock.patch.object(S, "_in_ci", return_value=False), \
                mock.patch.object(S, "read_image_lock", return_value={}), \
                mock.patch.object(S.shutil, "which", return_value="/usr/bin/docker"), \
                mock.patch.object(S, "_docker_daemon_ok", return_value=True), \
                mock.patch.object(S, "_deps_installed", return_value=True), \
                mock.patch.object(S, "_run", return_value=0) as run:
            with contextlib.redirect_stderr(err):
                rc = S.main(["shots_linux.py"])
        self.assertEqual(rc, 0)
        run.assert_called_once()
        self.assertIn("shots:digest", err.getvalue())

    def test_a_malformed_digest_is_never_used(self):
        for bad in ("", "latest", "sha256:nothex", "sha256:" + "a" * 63, "sha512:" + "a" * 64):
            ref, warning = S.resolved_image(self.TAG, {"image": self.TAG, "digest": bad})
            self.assertEqual(ref, self.TAG, bad)
            self.assertTrue(warning, bad)

    def test_a_non_string_lock_value_degrades_instead_of_crashing(self):
        # A syntactically valid but wrongly typed lock (hand-edited, or written by another tool)
        # must take the documented mutable-tag path, not hand a developer or CI a traceback.
        for bad in (123, None, [], {}, True):
            ref, warning = S.resolved_image(self.TAG, {"image": self.TAG, "digest": bad})
            self.assertEqual(ref, self.TAG, repr(bad))
            self.assertTrue(warning, repr(bad))
            ref, warning = S.resolved_image(self.TAG, {"image": bad, "digest": self.DIGEST})
            self.assertEqual(ref, self.TAG, repr(bad))
            self.assertTrue(warning, repr(bad))

    def test_the_committed_lock_pins_the_version_the_package_lock_resolves(self):
        lock = S.read_image_lock()
        self.assertEqual(lock.get("image"), S.image_ref(S.pinned_playwright_version(_paths.DEV)),
                         "after a @playwright/test bump, re-record the renderer digest with "
                         "'npm run shots:digest' so both sides keep using ONE immutable image")
        ref, warning = S.resolved_image(lock["image"], lock)
        self.assertIsNone(warning)
        self.assertIn("@sha256:", ref)

    def test_a_repo_digest_is_parsed_only_for_the_pinned_repository(self):
        self.assertEqual(S.parse_repo_digest(["mcr.microsoft.com/playwright@" + self.DIGEST]),
                         self.DIGEST)
        self.assertIsNone(S.parse_repo_digest(["evil.example.com/playwright@" + self.DIGEST]))
        self.assertIsNone(S.parse_repo_digest([]))
        self.assertIsNone(S.parse_repo_digest(["mcr.microsoft.com/playwright:v1.61.1-noble"]))

    def test_the_lock_round_trips_through_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "shots-image.lock")
            self.assertEqual(S.read_image_lock(path), {},
                             "a missing lock is 'no digest recorded', never an error")
            S.write_image_lock(path, self.TAG, self.DIGEST)
            self.assertEqual(S.read_image_lock(path),
                             {"image": self.TAG, "digest": self.DIGEST})

    def test_the_container_run_uses_the_resolved_digest_reference(self):
        with mock.patch.object(S, "_in_ci", return_value=False), \
                mock.patch.object(S, "read_image_lock",
                                  return_value={"image": S.image_ref(
                                      S.pinned_playwright_version(_paths.DEV)),
                                      "digest": self.DIGEST}), \
                mock.patch.object(S.shutil, "which", return_value="/usr/bin/docker"), \
                mock.patch.object(S, "_docker_daemon_ok", return_value=True), \
                mock.patch.object(S, "_deps_installed", return_value=True), \
                mock.patch.object(S, "_run", return_value=0) as run:
            rc = S.main(["shots_linux.py", "--check"])
        self.assertEqual(rc, 0)
        self.assertIn("mcr.microsoft.com/playwright@" + self.DIGEST, run.call_args[0][0])

    def test_print_image_reports_the_resolved_reference_without_rendering(self):
        # CI pulls exactly what the tool will run (and times it), so the pull can never warm a
        # DIFFERENT image than the render uses.
        import io
        import contextlib
        buf = io.StringIO()
        with mock.patch.object(S, "_deps_installed", return_value=True), \
                mock.patch.object(S, "_run") as run:
            with contextlib.redirect_stdout(buf):
                rc = S.main(["shots_linux.py", "--print-image"])
        self.assertEqual(rc, 0)
        run.assert_not_called()
        printed = buf.getvalue().strip()
        self.assertTrue(printed.startswith("mcr.microsoft.com/playwright@sha256:"), printed)

    def test_the_ci_screenshot_gate_runs_in_the_pinned_container(self):
        # The acceptance criterion of issue #701: the required job VALIDATES the screenshots in the
        # same image the local tooling renders with, so the authority is one fixed environment.
        block = _shots_job_block(_workflow_text())
        self.assertIn("shots_linux.py --check", block)
        self.assertNotIn("--native", block)
        self.assertNotIn("capture_tutorial.mjs", block)
        self.assertIn("--print-image", block)

    def test_the_ci_gate_cannot_skip_itself_by_construction(self):
        # `npm run shots:check` carries --skip-without-renderer, whose only brake is reading the CI
        # environment variable. GitHub always sets it, but a self-hosted or container runner with a
        # scrubbed environment would silently turn the required drift gate into exit 0. The CI step
        # therefore calls the tool WITHOUT the skip flag: it cannot skip, whatever the environment.
        # Comments are stripped - only what the job RUNS counts.
        block = "\n".join(ln for ln in _shots_job_block(_workflow_text()).split("\n")
                          if not ln.strip().startswith("#"))
        self.assertNotIn("--skip-without-renderer", block)
        self.assertNotIn("npm run shots:check", block)

    def test_the_screenshot_gate_is_reachable_on_a_shard_that_exists(self):
        # A string match alone would not notice an unreachable step: a typo'd `if:` (a shard the
        # matrix never produces, or a property that does not exist) would silently DROP the drift
        # gate while the job still went green. Pin the shots steps to the SAME condition as the
        # sibling fixtures check, and check that value against the MATRIX LIST only - matching it
        # against the whole block would find it in the `if:` line itself and prove nothing.
        block = _shots_job_block(_workflow_text())
        conditions = [ln.strip() for ln in block.split("\n") if ln.strip().startswith("if: matrix.")]
        self.assertTrue(conditions, "the once-only steps must carry a shard condition")
        self.assertEqual(len(set(conditions)), 1,
                         "the fixtures, pull and shots:check steps must share one shard condition")
        # There are three of them (fixtures, pull, shots check) - none silently lost its guard.
        self.assertEqual(len(conditions), 3)
        prop, _, value = conditions[0][len("if: "):].partition("==")
        self.assertEqual(prop.strip(), "matrix.shard",
                         "a condition on any other property is never true and skips the gate")
        matrix_line = next(ln for ln in block.split("\n") if ln.strip().startswith("shard:"))
        self.assertIn('"%s"' % value.strip().strip("'\""), matrix_line.replace("'", '"'),
                      "the once-only steps run on a shard the matrix never produces")

    def test_the_ci_job_no_longer_pins_a_runner_release_as_the_renderer(self):
        # With the container as the renderer, the runner's own Ubuntu release (and its font
        # packages, which GitHub updates over time) no longer decides a single pixel.
        block = _shots_job_block(_workflow_text())
        runs_on = [ln.split(":", 1)[1].strip() for ln in block.split("\n")
                   if ln.strip().startswith("runs-on:")]
        self.assertEqual(runs_on, ["ubuntu-latest"])

    def test_the_job_block_helper_really_isolates_that_job(self):
        # The guard above is only meaningful if the block it inspects is the playwright-heavy job
        # and nothing else - a helper that returned one line, or the whole file, would make the
        # assertion vacuous.
        block = _shots_job_block(_workflow_text())
        self.assertTrue(block.startswith("  playwright-heavy:"))
        self.assertIn("runs-on:", block)
        self.assertNotIn("\n  playwright:", block)
        self.assertNotIn("\n  python:", block)


class DriftEvidenceArtifactTests(unittest.TestCase):
    """CMH-BUILD-18: a failed drift gate must leave the fresh PNGs behind as a CI artifact.

    The screenshots are rendered ONLY in the pinned container, so a contributor without Docker
    cannot reproduce a drift failure at all - the CI run is their only evidence, and the fresh PNGs
    the tool keeps in tmp/tutorial-shots-check/<pid> die with the runner unless CI uploads them.
    """

    def test_a_drift_failure_uploads_the_fresh_screenshots(self):
        steps = _shots_job_steps(_shots_job_block(_workflow_text()))
        check = _step_with(steps, "shots_linux.py --check")
        step_id = _field(check, "id")
        self.assertTrue(step_id, "the drift gate step needs an id so a later step can read its outcome")
        upload = _step_with(steps, "uses: actions/upload-artifact@")
        self.assertIsNotNone(upload, "a failed drift gate must upload the freshly rendered PNGs")
        # The whole guard, not a substring: `... outcome != 'failure'` (or any other near-miss that
        # merely CONTAINS these tokens) would silently upload nothing on real drift.
        self.assertEqual(" ".join(_field(upload, "if").split()),
                         "failure() && steps.%s.outcome == 'failure'" % step_id,
                         "the upload must be tied to the drift gate's own outcome, not the job's")
        self.assertGreater(steps.index(upload), steps.index(check),
                           "the upload has to come AFTER the step whose outcome it reads")
        self.assertEqual(_with_field(upload, "path"), "tmp/tutorial-shots-check/",
                         "the check keeps the fresh PNGs there; nothing else is evidence")
        # A missing scratch dir (the gate failed before rendering) must not add a SECOND, confusing
        # failure on top of the real one.
        self.assertIn(_with_field(upload, "if-no-files-found"), ("warn", "ignore"))

    def test_the_evidence_upload_never_runs_on_a_green_job(self):
        # Uploading unconditionally would cost every green run the artifact packing time, and would
        # bury the one upload that matters in noise.
        upload = _step_with(_shots_job_steps(_shots_job_block(_workflow_text())),
                            "uses: actions/upload-artifact@")
        condition = _field(upload, "if")
        self.assertTrue(condition.startswith("failure() &&"),
                        "without failure() the step runs on every green run too")
        self.assertNotIn("always()", condition)
        self.assertNotIn("success()", condition)

    def test_the_artifact_action_is_pinned_by_commit_sha(self):
        # House rule: third-party actions are pinned by full commit SHA, never by a movable tag.
        block = _shots_job_block(_workflow_text())
        pins = re.findall(r"uses: actions/upload-artifact@(\S+)", block)
        self.assertTrue(pins)
        for pin in pins:
            self.assertRegex(pin, r"^[0-9a-f]{40}$")

    def test_the_guide_tells_a_contributor_where_the_artifact_is(self):
        # The artifact is only useful if the drift instructions name it; a rename here without a
        # doc update would send a contributor looking for something that does not exist.
        upload = _step_with(_shots_job_steps(_shots_job_block(_workflow_text())),
                            "uses: actions/upload-artifact@")
        name = _with_field(upload, "name")
        self.assertTrue(name)
        guide = os.path.normpath(os.path.join(_paths.PLUGIN_ROOT, "..", "..", "docs",
                                              "testing-guidelines.md"))
        with open(guide, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn(name, text)


def _workflow_text():
    path = os.path.normpath(os.path.join(_paths.PLUGIN_ROOT, "..", "..", ".github", "workflows",
                                         "plugin-tests.yml"))
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _shots_job_steps(block):
    """The job block split into its individual `- name:` steps (text, comments included)."""
    lines = block.split("\n")
    steps = []
    current = None
    for line in lines:
        if line.startswith("      - name:"):
            current = [line]
            steps.append(current)
        elif current is not None:
            if line.strip() and not line.startswith("       "):
                current = None
                continue
            current.append(line)
    return ["\n".join(step) for step in steps]


def _step_with(steps, needle):
    """The first step whose text contains `needle`, or None."""
    return next((step for step in steps if needle in step), None)


def _field(step, key):
    """The value of a step-level `key:` (`if`, `id`, `uses`), with comments and quotes handled."""
    for line in (step or "").split("\n")[1:]:
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if stripped.startswith(key + ":"):
            return _scalar(stripped.split(":", 1)[1])
    return ""


def _with_field(step, key):
    """The value of `key:` inside the step's `with:` mapping (and nothing outside it)."""
    indent = None
    for line in (step or "").split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if indent is None:
            if stripped == "with:":
                indent = len(line) - len(line.lstrip())
            continue
        if len(line) - len(line.lstrip()) <= indent:
            break  # a sibling key ended the with: mapping
        if stripped.startswith(key + ":"):
            return _scalar(stripped.split(":", 1)[1])
    return ""


def _scalar(raw):
    value = raw.strip()
    if value.startswith("${{") and value.endswith("}}"):
        value = value[3:-2].strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        value = value[1:-1]
    return value


def _shots_job_block(text):
    """The full `playwright-heavy:` top-level job block (the job that validates the screenshots).

    Top-level jobs are indented two spaces; every line INSIDE a job is indented further. So the
    block ends at the next line that starts with exactly two spaces followed by a non-space.
    """
    lines = text.split("\n")
    start = next(i for i, ln in enumerate(lines) if ln.startswith("  playwright-heavy:"))
    end = len(lines)
    for i in range(start + 1, len(lines)):
        ln = lines[i]
        if ln.startswith("  ") and not ln.startswith("   ") and ln.strip():
            end = i
            break
    return "\n".join(lines[start:end])


if __name__ == "__main__":
    unittest.main()
