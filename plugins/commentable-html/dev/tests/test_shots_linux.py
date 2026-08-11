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
import shutil
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
        # package.json carries a semver RANGE; the RESOLVED lockfile version is what the suite
        # actually runs, so it is the only value that keeps the image and the renderer in lockstep.
        # The fixture below uses an arbitrary version deliberately unrelated to the real pin, so the
        # assertion cannot pass by accidentally agreeing with it (and needs no edit on a bump).
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
        self.assertEqual(_with_field(upload, "name"), "tutorial-shots-drift",
                         "the guide names this artifact; a silent rename orphans the instructions")
        # A missing scratch dir (the gate failed before rendering) must not add a SECOND, confusing
        # failure on top of the real one.
        self.assertEqual(_with_field(upload, "if-no-files-found"), "warn")
        # "Re-run failed jobs" reuses the run id, and an artifact name is unique per run.
        self.assertEqual(_with_field(upload, "overwrite"), "true")
        self.assertEqual(_with_field(upload, "retention-days"), "14")

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
    """The job block split into its individual `- name:` steps.

    Comment lines aligned with the `- name:` bullet belong to no step: they neither end the step
    being read nor join it. Two assumptions, both true of this job: a step starts with its `name:`
    (a `- uses:`-first step would be invisible here, so a failure below would read as "removed"
    when it was only reordered), and values are single-line scalars (no `>` / `|` blocks).
    """
    lines = block.split("\n")
    steps = []
    current = None
    for line in lines:
        if line.startswith("      - name:"):
            current = [line]
            steps.append(current)
            continue
        if line.strip().startswith("#"):
            continue
        if current is not None:
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
    value = raw.split("  #", 1)[0].strip()
    for _ in range(2):
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1].strip()
        elif value.startswith("${{") and value.endswith("}}"):
            value = value[3:-2].strip()
        else:
            break
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



class DriftEvidenceRetentionTests(unittest.TestCase):
    """CMH-BUILD-18: the check keeps its scratch on ANY unsuccessful run, not only a
    comparison failure. It used to set its keep-flag only on the compare path, so an
    exception thrown mid-capture (a browser crash, a selector timeout) fell through the
    `finally` and DELETED the shots already rendered - leaving the CI drift-evidence
    artifact with nothing to upload for exactly the failure a contributor without Docker
    can least reproduce."""

    def setUp(self):
        path = os.path.join(_paths.DEV, "tools", "capture_tutorial.mjs")
        with open(path, "r", encoding="utf-8") as fh:
            self.src = fh.read()

    def _check_body(self):
        start = self.src.index("async function checkScreenshots(")
        end = self.src.index("\nasync function ", start + 1)
        return self.src[start:end]

    def test_the_scratch_is_removed_only_on_a_clean_pass(self):
        body = self._check_body()
        self.assertIn("if (clean) fs.rmSync(checkRoot", body,
                      "the scratch must be deleted only when the run SUCCEEDED")
        self.assertNotIn("if (!stale) fs.rmSync(checkRoot", body,
                         "the old keep-flag deleted evidence when capture threw")

    def test_the_clean_flag_is_set_only_after_the_comparison_passed(self):
        body = self._check_body()
        success = body.index("clean = true")
        in_sync = body.index("tutorial screenshots are in sync")
        self.assertGreater(success, in_sync,
                           "clean must be set on the success path, after the comparison")

    def test_a_failure_says_where_the_evidence_is(self):
        self.assertIn("check scratch kept for evidence in", self._check_body())


class DiffImageTests(unittest.TestCase):
    """CMH-BUILD-18: a failing check writes a per-shot diff image beside the fresh PNG,
    inside the tree the CI artifact already uploads, so a reviewer sees WHAT moved."""

    def setUp(self):
        with open(os.path.join(_paths.DEV, "tools", "capture_tutorial.mjs"),
                  "r", encoding="utf-8") as fh:
            self.capture = fh.read()
        with open(os.path.join(_paths.DEV, "tools", "shot_compare.mjs"),
                  "r", encoding="utf-8") as fh:
            self.compare = fh.read()

    def test_the_comparator_exports_a_diff_writer(self):
        self.assertIn("export async function writeDiffImage(", self.compare)

    def test_the_check_writes_a_diff_only_for_a_failing_shot(self):
        # Producing one on every shot would cost a render per pass and change nothing.
        start = self.capture.index("const result = await compareImages(")
        window = self.capture[start:start + 900]
        self.assertIn("if (!result.ok)", window)
        self.assertIn("writeDiffImage(", window)

    def test_the_diff_lands_inside_the_uploaded_scratch_tree(self):
        # It must sit in tmp/tutorial-shots-check/<pid>/<scene>/ so the existing
        # tutorial-shots-drift artifact carries it with no workflow change.
        self.assertIn("path.join(checkDir,", self.capture)
        self.assertIn(".diff.png", self.capture)

    def test_a_diff_failure_cannot_change_the_gate_outcome(self):
        # The diff is evidence, not a verdict: it is written after the problem is already
        # recorded, and writeDiffImage swallows its own errors.
        start = self.capture.index("const result = await compareImages(")
        window = self.capture[start:start + 900]
        self.assertLess(window.index("problems.push"), window.index("writeDiffImage("))
        self.assertIn("return false;", self.compare[self.compare.index("export async function writeDiffImage("):])


class MidCaptureCrashTests(unittest.TestCase):
    """CMH-BUILD-18: force a REAL mid-capture failure in checkScreenshots and assert the PNGs
    it had already rendered SURVIVE. Source-level assertions alone stay green through a
    control-flow or filesystem regression, which is what issue #717 asked to be covered for
    real; `CMH_SHOTS_FAIL_AFTER_SCENE` is a test-only hook that throws after the first scene
    is on disk."""

    def test_a_crash_after_the_first_scene_keeps_the_rendered_pngs(self):
        import glob
        import shutil
        import subprocess

        if shutil.which("node") is None:
            self.skipTest("node is not on PATH")
        dev = _paths.DEV
        if not os.path.isdir(os.path.join(dev, "node_modules", "@playwright", "test")):
            self.skipTest("playwright is not installed in this checkout")
        # capture_tutorial refuses to run directly (CMH-BUILD-16): the shots render ONLY in the
        # pinned container, so the check has to be driven through the wrapper, which needs docker
        # (or a host that IS the CI platform). Skip cleanly where neither is available; CI has both.
        if not S.renderer_available():
            self.skipTest("no pinned renderer available (docker or the native CI platform)")

        repo = os.path.abspath(os.path.join(dev, os.pardir, os.pardir, os.pardir))
        scratch_root = os.path.join(repo, "tmp", "tutorial-shots-check")
        before = set(glob.glob(os.path.join(scratch_root, "*")))
        env = dict(os.environ, CMH_SHOTS_FAIL_AFTER_SCENE="1")
        proc = subprocess.run(
            [sys.executable, os.path.join(dev, "tools", "shots_linux.py"), "--check"],
            capture_output=True, text=True, env=env, cwd=dev)
        self.assertNotEqual(proc.returncode, 0, "the injected fault must fail the run")
        new_dirs = [d for d in glob.glob(os.path.join(scratch_root, "*")) if d not in before]
        try:
            self.assertTrue(new_dirs, "the check must KEEP its scratch tree on a mid-capture crash")
            pngs = glob.glob(os.path.join(new_dirs[0], "*", "*.png"))
            self.assertTrue(pngs, "the PNGs rendered before the crash must survive in %s" % new_dirs[0])
        finally:
            for d in new_dirs:
                shutil.rmtree(d, ignore_errors=True)

    def test_the_fault_hook_is_unset_in_a_normal_run(self):
        # The hook must be opt-in: a stray default would make every check fail.
        with open(os.path.join(_paths.DEV, "tools", "capture_tutorial.mjs"),
                  "r", encoding="utf-8") as fh:
            body = fh.read()
        self.assertIn("process.env.CMH_SHOTS_FAIL_AFTER_SCENE", body)
        self.assertNotIn("CMH_SHOTS_FAIL_AFTER_SCENE = ", body)

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _png(body=b"\xff\x00\x00"):
    """A structurally complete 1px PNG. `body` varies the pixel so shots differ byte-wise.

    Built rather than hand-rolled from magic bytes because the adopt path validates the whole chunk
    stream (CRCs, IEND, no trailing data), so a signature-only fixture would be refused - which is
    itself asserted below.
    """
    import struct
    import zlib

    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00" + body)
    return PNG_MAGIC + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def _artifact(root, shots, diffs=()):
    """An unzipped tutorial-shots-drift tree: <pid>/<scene>/<scene>-<shot>.png."""
    for name, body in shots.items():
        scene = name.split("-", 1)[0]
        d = os.path.join(root, "1", scene)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, name), "wb") as fh:
            fh.write(body)
    for name in diffs:
        scene = name.split("-", 1)[0]
        d = os.path.join(root, "1", scene)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, name), "wb") as fh:
            fh.write(_png(b"\x00\x00\xff"))
    return root


def _baselines(root, shots):
    os.makedirs(root, exist_ok=True)
    for name, body in shots.items():
        with open(os.path.join(root, name), "wb") as fh:
            fh.write(body)
    return root


def _bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


class PngStructureTests(unittest.TestCase):
    """CMH-BUILD-28: what counts as an installable PNG.

    The gate DECODES these files, so the check has to be structural: the refusal message names a
    truncated download, and a signature-only test would not catch one.
    """

    def test_a_complete_png_is_accepted(self):
        self.assertIsNone(S.png_problem(_png()))

    def test_every_committed_screenshot_passes(self):
        # The real corpus, so the validator can never be stricter than the renderer's own output.
        names = [n for n in sorted(os.listdir(S.SHOTS_DIR)) if n.lower().endswith(".png")]
        self.assertGreater(len(names), 10, names)
        for name in names:
            self.assertIsNone(S.png_problem(_bytes(os.path.join(S.SHOTS_DIR, name))), name)

    def test_a_truncated_png_is_refused_even_though_its_signature_is_intact(self):
        # The exact case the refusal message promises: a download cut short still starts with the
        # 8 magic bytes, so only walking the chunks to IEND catches it.
        self.assertIn("truncated", S.png_problem(_png()[:-6]))
        self.assertIn("truncated", S.png_problem(PNG_MAGIC))

    def test_data_appended_after_iend_is_refused(self):
        self.assertIn("IEND", S.png_problem(_png() + b"payload"))

    def test_a_corrupt_chunk_crc_is_refused(self):
        data = bytearray(_png())
        data[20] ^= 0xFF  # flip a byte inside IHDR's payload; its CRC no longer matches
        self.assertIn("CRC", S.png_problem(bytes(data)))

    def test_a_non_png_is_refused(self):
        self.assertIn("signature", S.png_problem(b"<html>rate limited</html>"))


class AdoptArtifactScanTests(unittest.TestCase):
    """CMH-BUILD-28: read the fresh PNGs out of an unzipped drift artifact."""

    def test_shots_are_found_at_any_depth_and_keyed_by_file_name(self):
        # Deliberately three DIFFERENT depths, so a walk hard-coded to the <pid>/<scene>/ shape
        # would fail rather than pass by matching the fixture's only depth.
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "note-01-note.png"), "wb") as fh:
                fh.write(_png())
            deep = os.path.join(tmp, "1", "garden", "extra")
            os.makedirs(deep)
            with open(os.path.join(deep, "garden-15-format-toolbar.png"), "wb") as fh:
                fh.write(_png())
            _artifact(tmp, {"triage-01-board.png": _png()})
            self.assertEqual(sorted(S.find_artifact_shots(tmp)),
                             ["garden-15-format-toolbar.png", "note-01-note.png",
                              "triage-01-board.png"])

    def test_the_generated_diff_images_are_not_adoptable_shots(self):
        # The check writes <shot>.diff.png beside the fresh PNG. It is a magenta-marked REPORT,
        # not a render, so adopting one would install a picture of the failure as the baseline.
        with tempfile.TemporaryDirectory() as tmp:
            _artifact(tmp, {"garden-15-format-toolbar.png": _png()},
                      diffs=["garden-15-format-toolbar.diff.png"])
            self.assertEqual(list(S.find_artifact_shots(tmp)), ["garden-15-format-toolbar.png"])

    def test_one_name_appearing_twice_is_refused_rather_than_resolved_by_walk_order(self):
        # Two runs unzipped into one directory would otherwise adopt whichever os.walk reached
        # last - a silent coin flip over which render becomes the committed baseline.
        with tempfile.TemporaryDirectory() as tmp:
            for pid in ("1", "2"):
                d = os.path.join(tmp, pid, "garden")
                os.makedirs(d)
                with open(os.path.join(d, "garden-15-format-toolbar.png"), "wb") as fh:
                    fh.write(_png(bytes([int(pid), 0, 0])))
            with self.assertRaises(S.ShotsError) as ctx:
                S.find_artifact_shots(tmp)
            self.assertIn("garden-15-format-toolbar.png", str(ctx.exception))

    def test_two_spellings_of_one_name_collide_even_on_a_case_insensitive_disk(self):
        # On Windows both address ONE baseline, so they must be caught as duplicates here rather
        # than racing each other into the same destination.
        with tempfile.TemporaryDirectory() as tmp:
            for pid, name in (("1", "note-01-note.png"), ("2", "NOTE-01-NOTE.PNG")):
                d = os.path.join(tmp, pid)
                os.makedirs(d)
                with open(os.path.join(d, name), "wb") as fh:
                    fh.write(_png())
            with self.assertRaises(S.ShotsError):
                S.find_artifact_shots(tmp)

    def test_an_upper_case_png_is_seen_rather_than_silently_ignored(self):
        # A lowercase-only suffix test would drop it and adopt the REST of the artifact - a silent
        # partial adoption, the one outcome this tool must never produce. Seen here, it is then
        # either adopted or refused by name, loudly.
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "note-01-note.PNG"), "wb") as fh:
                fh.write(_png())
            self.assertEqual(list(S.find_artifact_shots(tmp)), ["note-01-note.PNG"])

    @unittest.skipUnless(hasattr(os, "symlink"), "no symlink support")
    def test_a_symlinked_entry_is_refused_instead_of_being_dereferenced(self):
        # copyfile would otherwise install bytes from OUTSIDE the artifact as a committed
        # screenshot, which is exactly what "the bytes come from this artifact" must exclude.
        with tempfile.TemporaryDirectory() as tmp:
            outside = os.path.join(tmp, "outside.bin")
            with open(outside, "wb") as fh:
                fh.write(_png())
            art = os.path.join(tmp, "art")
            os.makedirs(art)
            try:
                os.symlink(outside, os.path.join(art, "note-01-note.png"))
            except (OSError, NotImplementedError):
                self.skipTest("this account cannot create symlinks")
            with self.assertRaises(S.ShotsError) as ctx:
                S.find_artifact_shots(art)
            self.assertIn("regular file", str(ctx.exception))


class AdoptPlanTests(unittest.TestCase):
    """CMH-BUILD-28: what may be adopted, decided before anything is written."""

    def _dirs(self, tmp):
        return os.path.join(tmp, "artifact"), os.path.join(tmp, "shots")

    def test_only_the_shots_that_actually_differ_are_adopted(self):
        with tempfile.TemporaryDirectory() as tmp:
            art, shots = self._dirs(tmp)
            _artifact(art, {"garden-15-format-toolbar.png": _png(b"\x01\x00\x00"),
                            "note-01-note.png": _png(b"\x02\x00\x00")})
            _baselines(shots, {"garden-15-format-toolbar.png": _png(b"\x09\x00\x00"),
                               "note-01-note.png": _png(b"\x02\x00\x00"),
                               "landing-composer.png": _png(b"\x03\x00\x00")})
            plan = S.plan_adoption(art, shots)
            self.assertEqual([n for n, _ in plan.changed], ["garden-15-format-toolbar.png"])
            self.assertEqual(plan.unchanged, ["note-01-note.png"])

    def test_a_png_with_no_committed_baseline_refuses_the_whole_adoption(self):
        # The safety property: adopt only ever REWRITES an existing baseline. A name that is not
        # one is either the wrong artifact or a shot this repo has never committed, and a NEW
        # baseline has to come from the renderer - so the rest of the artifact is not adopted.
        with tempfile.TemporaryDirectory() as tmp:
            art, shots = self._dirs(tmp)
            _artifact(art, {"garden-15-format-toolbar.png": _png(b"\x01\x00\x00"),
                            "totally-other-thing.png": _png()})
            _baselines(shots, {"garden-15-format-toolbar.png": _png(b"\x09\x00\x00")})
            with self.assertRaises(S.ShotsError) as ctx:
                S.plan_adoption(art, shots)
            self.assertIn("totally-other-thing.png", str(ctx.exception))
            # And nothing was written on the way to deciding that.
            self.assertEqual(_bytes(os.path.join(shots, "garden-15-format-toolbar.png")),
                             _png(b"\x09\x00\x00"))

    def test_a_file_that_is_not_a_usable_png_refuses_the_whole_adoption(self):
        # A truncated download or an HTML error page saved as .png must never be installed as a
        # baseline; the drift gate would then fail on an unreadable image forever.
        with tempfile.TemporaryDirectory() as tmp:
            art, shots = self._dirs(tmp)
            _artifact(art, {"garden-15-format-toolbar.png": b"<html>rate limited</html>"})
            _baselines(shots, {"garden-15-format-toolbar.png": _png(b"\x09\x00\x00")})
            with self.assertRaises(S.ShotsError) as ctx:
                S.plan_adoption(art, shots)
            self.assertIn("garden-15-format-toolbar.png", str(ctx.exception))

    def test_a_truncated_png_is_refused_by_the_plan_not_installed(self):
        with tempfile.TemporaryDirectory() as tmp:
            art, shots = self._dirs(tmp)
            _artifact(art, {"garden-15-format-toolbar.png": _png(b"\x01\x00\x00")[:-6]})
            _baselines(shots, {"garden-15-format-toolbar.png": _png(b"\x09\x00\x00")})
            with self.assertRaises(S.ShotsError) as ctx:
                S.plan_adoption(art, shots)
            self.assertIn("truncated", str(ctx.exception))

    def test_an_artifact_with_no_shots_is_refused_not_reported_as_nothing_to_do(self):
        # "Nothing to adopt" and "you pointed me at the wrong directory" must not look the same:
        # the second would read as a clean success while main stayed red.
        with tempfile.TemporaryDirectory() as tmp:
            art, shots = self._dirs(tmp)
            os.makedirs(art)
            _baselines(shots, {"garden-15-format-toolbar.png": _png(b"\x09\x00\x00")})
            with self.assertRaises(S.ShotsError):
                S.plan_adoption(art, shots)

    def test_a_path_that_is_not_a_directory_says_so(self):
        # A typo'd path used to report "no screenshots found", which reads as "wrong contents"
        # rather than "no such directory".
        with tempfile.TemporaryDirectory() as tmp:
            _, shots = self._dirs(tmp)
            _baselines(shots, {"note-01-note.png": _png()})
            with self.assertRaises(S.ShotsError) as ctx:
                S.plan_adoption(os.path.join(tmp, "nope"), shots)
            self.assertIn("not a directory", str(ctx.exception))

    def test_baseline_membership_is_matched_by_exact_name(self):
        # os.path.isfile answers case-insensitively on Windows, which would let a differently-cased
        # artifact name through and rewrite the tracked file under a new spelling.
        with tempfile.TemporaryDirectory() as tmp:
            art, shots = self._dirs(tmp)
            _artifact(art, {"NOTE-01-NOTE.png": _png(b"\x01\x00\x00")})
            _baselines(shots, {"note-01-note.png": _png(b"\x09\x00\x00")})
            with self.assertRaises(S.ShotsError) as ctx:
                S.plan_adoption(art, shots)
            self.assertIn("NOTE-01-NOTE.png", str(ctx.exception))

    def test_the_plan_carries_the_bytes_so_the_write_cannot_re_read_a_changed_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            art, shots = self._dirs(tmp)
            _artifact(art, {"note-01-note.png": _png(b"\x01\x00\x00")})
            _baselines(shots, {"note-01-note.png": _png(b"\x09\x00\x00")})
            plan = S.plan_adoption(art, shots)
            self.assertEqual(plan.changed[0][1], _png(b"\x01\x00\x00"))


class AdoptWriteTests(unittest.TestCase):
    """CMH-BUILD-28: adopting writes the container's bytes and reports exactly what moved."""

    def test_the_committed_baseline_becomes_the_artifacts_bytes(self):
        import io
        import contextlib
        with tempfile.TemporaryDirectory() as tmp:
            art, shots = os.path.join(tmp, "artifact"), os.path.join(tmp, "shots")
            _artifact(art, {"garden-15-format-toolbar.png": _png(b"\x01\x00\x00")})
            _baselines(shots, {"garden-15-format-toolbar.png": _png(b"\x09\x00\x00")})
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = S.adopt_artifact(art, shots)
            self.assertEqual(rc, 0)
            self.assertEqual(_bytes(os.path.join(shots, "garden-15-format-toolbar.png")),
                             _png(b"\x01\x00\x00"))
            self.assertIn("garden-15-format-toolbar.png", out.getvalue())

    def test_an_artifact_that_matches_reports_no_drift_and_writes_nothing(self):
        import io
        import contextlib
        with tempfile.TemporaryDirectory() as tmp:
            art, shots = os.path.join(tmp, "artifact"), os.path.join(tmp, "shots")
            _artifact(art, {"garden-15-format-toolbar.png": _png(b"\x05\x00\x00")})
            _baselines(shots, {"garden-15-format-toolbar.png": _png(b"\x05\x00\x00")})
            before = os.stat(os.path.join(shots, "garden-15-format-toolbar.png")).st_mtime_ns
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = S.adopt_artifact(art, shots)
            self.assertEqual(rc, 0)
            self.assertEqual(
                os.stat(os.path.join(shots, "garden-15-format-toolbar.png")).st_mtime_ns, before)
            self.assertIn("no drift", out.getvalue().lower())

    def test_the_no_drift_report_does_not_claim_every_committed_shot_is_fresh(self):
        # An artifact carrying ONE matching shot must not read as "the whole set is in sync" while
        # other baselines are still stale and main is still red.
        import io
        import contextlib
        with tempfile.TemporaryDirectory() as tmp:
            art, shots = os.path.join(tmp, "artifact"), os.path.join(tmp, "shots")
            _artifact(art, {"note-01-note.png": _png(b"\x05\x00\x00")})
            _baselines(shots, {"note-01-note.png": _png(b"\x05\x00\x00"),
                               "garden-15-format-toolbar.png": _png(b"\x09\x00\x00")})
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                S.adopt_artifact(art, shots)
            self.assertIn("shots:check", out.getvalue())
            self.assertIn("coverage", out.getvalue().lower())

    def test_the_report_points_back_at_the_authoritative_gate(self):
        # Adopting is a re-baseline from CI's render, never a verdict: the pinned container's
        # check stays the only thing that says the screenshots are right.
        import io
        import contextlib
        with tempfile.TemporaryDirectory() as tmp:
            art, shots = os.path.join(tmp, "artifact"), os.path.join(tmp, "shots")
            _artifact(art, {"garden-15-format-toolbar.png": _png(b"\x01\x00\x00")})
            _baselines(shots, {"garden-15-format-toolbar.png": _png(b"\x09\x00\x00")})
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                S.adopt_artifact(art, shots)
            self.assertIn("shots:check", out.getvalue())

    def test_a_failed_write_rolls_back_so_no_baseline_is_left_half_adopted(self):
        # The decision refuses as a whole; so must the WRITE. A disk-full or permission error on
        # the second file must not leave the first one rewritten.
        import io
        import contextlib
        with tempfile.TemporaryDirectory() as tmp:
            art, shots = os.path.join(tmp, "artifact"), os.path.join(tmp, "shots")
            _artifact(art, {"garden-15-format-toolbar.png": _png(b"\x01\x00\x00"),
                            "note-01-note.png": _png(b"\x02\x00\x00")})
            originals = {"garden-15-format-toolbar.png": _png(b"\x09\x00\x00"),
                         "note-01-note.png": _png(b"\x08\x00\x00")}
            _baselines(shots, dict(originals))
            real = S._write_atomically
            calls = []

            def flaky(path, data):
                calls.append(path)
                if len(calls) == 2:
                    raise OSError(28, "No space left on device")
                return real(path, data)

            with mock.patch.object(S, "_write_atomically", side_effect=flaky):
                with contextlib.redirect_stdout(io.StringIO()):
                    with self.assertRaises(S.ShotsError) as ctx:
                        S.adopt_artifact(art, shots)
            self.assertIn("rolled back", str(ctx.exception))
            for name, body in originals.items():
                self.assertEqual(_bytes(os.path.join(shots, name)), body, name)

    def test_a_write_replaces_atomically_rather_than_truncating_in_place(self):
        # A partial write must never leave a truncated PNG behind - that is the undecodable
        # baseline the plan's own PNG check exists to keep out.
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "note-01-note.png")
            with open(target, "wb") as fh:
                fh.write(_png(b"\x09\x00\x00"))
            with mock.patch.object(S.os, "replace", side_effect=OSError(13, "denied")):
                with self.assertRaises(OSError):
                    S._write_atomically(target, _png(b"\x01\x00\x00"))
            self.assertEqual(_bytes(target), _png(b"\x09\x00\x00"))
            self.assertEqual([n for n in os.listdir(tmp) if n != "note-01-note.png"], [])


class AdoptRunDownloadTests(unittest.TestCase):
    """CMH-BUILD-28: fetching that artifact from the run that produced it."""

    def test_the_download_asks_gh_for_this_checkouts_drift_artifact_by_run_id(self):
        with mock.patch.object(S.shutil, "which", return_value="/usr/bin/gh"), \
                mock.patch.object(S, "_run", return_value=0) as run:
            S.download_drift_artifact("31463992366", "/tmp/dest")
        cmd = run.call_args[0][0]
        self.assertEqual(cmd[:3], ["gh", "run", "download"])
        self.assertIn("31463992366", cmd)
        self.assertIn(S.DRIFT_ARTIFACT, cmd)
        self.assertIn("/tmp/dest", cmd)

    def test_gh_is_pinned_to_this_checkout_rather_than_the_callers_cwd_or_gh_repo(self):
        # gh resolves the repository from GH_REPO, then `gh repo set-default`, then the CWD's git
        # remotes - NOT from where this script lives. Without both of these a run id would name a
        # run of whatever repository the operator happened to be standing in.
        with mock.patch.object(S.shutil, "which", return_value="/usr/bin/gh"), \
                mock.patch.object(S, "_run", return_value=0) as run:
            with mock.patch.dict(S.os.environ, {"GH_REPO": "someone/else"}, clear=False):
                S.download_drift_artifact("1", "/tmp/dest")
        self.assertEqual(run.call_args[1]["cwd"], S.REPO_ROOT)
        self.assertNotIn("GH_REPO", run.call_args[1]["env"])

    def test_a_run_id_that_is_not_a_number_is_refused_before_gh_is_invoked(self):
        # The id is interpolated into an argv; anything but digits (an option, a path) must not
        # reach gh at all.
        with mock.patch.object(S.shutil, "which", return_value="/usr/bin/gh"), \
                mock.patch.object(S, "_run", return_value=0) as run:
            for bad in ("--repo=evil/repo", "12 34", "", "1a", "1\n2"):
                with self.assertRaises(S.ShotsError, msg=bad):
                    S.download_drift_artifact(bad, "/tmp/dest")
            run.assert_not_called()

    def test_a_pasted_run_id_with_surrounding_whitespace_is_accepted_cleanly(self):
        # `^...$` used to match a trailing newline, so a pasted id reached gh WITH the newline.
        with mock.patch.object(S.shutil, "which", return_value="/usr/bin/gh"), \
                mock.patch.object(S, "_run", return_value=0) as run:
            S.download_drift_artifact(" 31463992366\n", "/tmp/dest")
        self.assertIn("31463992366", run.call_args[0][0])

    def test_a_missing_gh_says_so_instead_of_failing_obscurely(self):
        with mock.patch.object(S.shutil, "which", return_value=None):
            with self.assertRaises(S.ShotsError) as ctx:
                S.download_drift_artifact("1", "/tmp/dest")
            self.assertIn("gh", str(ctx.exception))

    def test_a_failed_download_is_reported_as_a_refusal_not_a_traceback(self):
        with mock.patch.object(S.shutil, "which", return_value="/usr/bin/gh"), \
                mock.patch.object(S, "_run", return_value=1):
            with self.assertRaises(S.ShotsError) as ctx:
                S.download_drift_artifact("1", "/tmp/dest")
            self.assertIn(S.DRIFT_ARTIFACT, str(ctx.exception))


class AdoptProvenanceTests(unittest.TestCase):
    """CMH-BUILD-28: which commit the adopted pixels were rendered from."""

    def _report(self, run_json, head):
        import io
        import contextlib

        def capture(cmd, **kwargs):
            return head if cmd[:2] == ["git", "-C"] else run_json

        out = io.StringIO()
        with mock.patch.object(S, "_capture", side_effect=capture):
            with contextlib.redirect_stdout(out):
                S.report_run_provenance("1")
        return out.getvalue()

    def test_a_run_of_a_different_commit_is_called_out(self):
        text = self._report('{"headSha": "%s", "headBranch": "main"}' % ("a" * 40), "b" * 40 + "\n")
        self.assertIn("WARNING", text)
        self.assertIn("aaaaaaaaaaaa", text)
        self.assertIn("bbbbbbbbbbbb", text)

    def test_a_run_of_this_commit_is_reported_without_a_warning(self):
        text = self._report('{"headSha": "%s", "headBranch": "main"}' % ("a" * 40), "a" * 40 + "\n")
        self.assertNotIn("WARNING", text)
        self.assertIn("aaaaaaaaaaaa", text)

    def test_an_unreadable_lookup_never_costs_the_operator_the_fix(self):
        # Provenance is reporting, not a gate: a gh/network failure must not block the adoption.
        for raw in (None, "not json", "{}"):
            text = self._report(raw, "a" * 40)
            self.assertIn("provenance", text.lower())


class AdoptCliTests(unittest.TestCase):
    """CMH-BUILD-28: the CLI wiring, and the modes it may not be combined with."""

    def _main(self, argv):
        import io
        import contextlib
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = S.main(argv)
        return rc, out.getvalue(), err.getvalue()

    def _adoptable(self, tmp):
        art, shots = os.path.join(tmp, "artifact"), os.path.join(tmp, "shots")
        _artifact(art, {"garden-15-format-toolbar.png": _png(b"\x01\x00\x00")})
        _baselines(shots, {"garden-15-format-toolbar.png": _png(b"\x09\x00\x00")})
        return art, shots

    def test_adopt_reads_the_named_directory_and_needs_no_docker(self):
        # The whole point: this is the path for a maintainer who cannot run the renderer at all.
        with tempfile.TemporaryDirectory() as tmp:
            art, shots = self._adoptable(tmp)
            with mock.patch.object(S, "SHOTS_DIR", shots), \
                    mock.patch.object(S.shutil, "which", return_value=None), \
                    mock.patch.object(S, "_docker_daemon_ok", return_value=False):
                rc, _, _ = self._main(["shots_linux.py", "--adopt", art])
            self.assertEqual(rc, 0)
            self.assertEqual(_bytes(os.path.join(shots, "garden-15-format-toolbar.png")),
                             _png(b"\x01\x00\x00"))

    def test_adopt_run_downloads_then_adopts_and_removes_the_scratch_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            shots = _baselines(os.path.join(tmp, "shots"),
                               {"garden-15-format-toolbar.png": _png(b"\x09\x00\x00")})
            seen = []

            def fake_download(run_id, dest):
                seen.append(dest)
                _artifact(dest, {"garden-15-format-toolbar.png": _png(b"\x01\x00\x00")})

            with mock.patch.object(S, "SHOTS_DIR", shots), \
                    mock.patch.object(S, "report_run_provenance"), \
                    mock.patch.object(S, "download_drift_artifact", side_effect=fake_download):
                rc, _, _ = self._main(["shots_linux.py", "--adopt-run", "31463992366"])
            self.assertEqual(rc, 0)
            self.assertEqual(_bytes(os.path.join(shots, "garden-15-format-toolbar.png")),
                             _png(b"\x01\x00\x00"))
            self.assertFalse(os.path.exists(seen[0]), seen[0])

    def test_a_refused_adopt_run_KEEPS_the_download_and_names_where(self):
        # The error tells the operator to inspect the artifact, so deleting the only unzipped copy
        # would force a re-download - and the drift gate itself keeps its evidence on failure.
        with tempfile.TemporaryDirectory() as tmp:
            shots = _baselines(os.path.join(tmp, "shots"), {"note-01-note.png": _png()})
            seen = []

            def fake_download(run_id, dest):
                seen.append(dest)
                _artifact(dest, {"stranger.png": _png()})

            with mock.patch.object(S, "SHOTS_DIR", shots), \
                    mock.patch.object(S, "report_run_provenance"), \
                    mock.patch.object(S, "download_drift_artifact", side_effect=fake_download):
                rc, _, err = self._main(["shots_linux.py", "--adopt-run", "1"])
            self.assertNotEqual(rc, 0)
            self.assertTrue(os.path.exists(seen[0]), seen[0])
            self.assertIn(seen[0], err)
            shutil.rmtree(seen[0], ignore_errors=True)

    def test_adopt_never_renders_so_it_cannot_be_combined_with_check_or_native(self):
        # Adopting INSTALLS someone else's render. Pairing it with a mode that renders here
        # would make it ambiguous which pixels won. The artifact is deliberately ADOPTABLE, so
        # removing the guard would exit 0 and this test would genuinely go red.
        with tempfile.TemporaryDirectory() as tmp:
            art, shots = self._adoptable(tmp)
            for other in (["--check"], ["--native"], ["--record-digest"], ["--print-image"]):
                with mock.patch.object(S, "SHOTS_DIR", shots):
                    rc, _, err = self._main(["shots_linux.py", "--adopt", art] + other)
                self.assertNotEqual(rc, 0, other)
                self.assertIn("cannot be combined with", err, other)
            self.assertEqual(_bytes(os.path.join(shots, "garden-15-format-toolbar.png")),
                             _png(b"\x09\x00\x00"))

    def test_adopt_and_adopt_run_are_mutually_exclusive(self):
        with tempfile.TemporaryDirectory() as tmp:
            art, shots = self._adoptable(tmp)
            with mock.patch.object(S, "SHOTS_DIR", shots):
                rc, _, err = self._main(["shots_linux.py", "--adopt", art, "--adopt-run", "1"])
            self.assertNotEqual(rc, 0)
            self.assertIn("mutually exclusive", err)
            self.assertEqual(_bytes(os.path.join(shots, "garden-15-format-toolbar.png")),
                             _png(b"\x09\x00\x00"))

    def test_an_empty_adopt_value_never_falls_through_to_the_render_path(self):
        # `--adopt "$dir"` with an unset variable used to be falsy, skip the adopt branch, and
        # drop into the container REGENERATE path - the write direction, on a machine the operator
        # explicitly asked not to render on.
        for argv in (["shots_linux.py", "--adopt", ""], ["shots_linux.py", "--adopt-run", "  "]):
            with mock.patch.object(S, "_run", return_value=0) as run:
                rc, _, err = self._main(argv)
            self.assertNotEqual(rc, 0, argv)
            self.assertIn("empty value", err)
            run.assert_not_called()

    def test_adopt_rejects_stray_arguments_instead_of_silently_dropping_them(self):
        # Unknown args are forwarded to the capture script on the render paths; adopting runs no
        # capture, so a typo'd flag would vanish and the run would read as a clean adoption.
        with tempfile.TemporaryDirectory() as tmp:
            art, shots = self._adoptable(tmp)
            with mock.patch.object(S, "SHOTS_DIR", shots):
                rc, _, err = self._main(["shots_linux.py", "--adopt", art, "--chek"])
            self.assertNotEqual(rc, 0)
            self.assertIn("--chek", err)
            self.assertEqual(_bytes(os.path.join(shots, "garden-15-format-toolbar.png")),
                             _png(b"\x09\x00\x00"))

    def test_a_refused_adoption_exits_non_zero_with_the_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            art, shots = os.path.join(tmp, "artifact"), os.path.join(tmp, "shots")
            _artifact(art, {"stranger.png": _png()})
            _baselines(shots, {"garden-15-format-toolbar.png": _png(b"\x09\x00\x00")})
            with mock.patch.object(S, "SHOTS_DIR", shots):
                rc, _, err = self._main(["shots_linux.py", "--adopt", art])
            self.assertNotEqual(rc, 0)
            self.assertIn("stranger.png", err)


class AdoptShotsDirTests(unittest.TestCase):
    """CMH-BUILD-28: the tool writes the real committed baselines, not some other directory."""

    def test_the_shots_dir_is_the_committed_tutorial_assets(self):
        self.assertTrue(os.path.isdir(S.SHOTS_DIR), S.SHOTS_DIR)
        self.assertEqual(os.path.basename(S.SHOTS_DIR), "assets")
        self.assertTrue(os.path.exists(
            os.path.join(S.SHOTS_DIR, "garden-15-format-toolbar.png")))


if __name__ == "__main__":
    unittest.main()
