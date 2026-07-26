#!/usr/bin/env python3
"""CMH-BUILD-16: tests for tools/shots_linux.py (CI-identical tutorial screenshot regeneration).

The committed tutorial PNGs are LINUX-rendered. Regenerating them on another OS silently produces a
different rasterization that passes every local check (both `npm run shots:check` and
`rebuild_all.py --check` compare against the HOST renderer) and then fails the required
`playwright-heavy` job. This tool is the deterministic, one-command way to regenerate them anywhere.
"""
import json
import os
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
    def test_tag_is_derived_from_the_version_and_pins_the_ci_ubuntu_release(self):
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

    def test_a_linux_host_runs_the_container_as_the_invoking_user(self):
        # Otherwise every PNG the container rewrites, and the scratch dir it creates, is left
        # root-owned in the worktree and a later native run cannot clean up after it.
        cmd = S.docker_command("/repo", "dev", "img:tag", [], (1000, 1000))
        self.assertIn("--user", cmd)
        self.assertEqual(cmd[cmd.index("--user") + 1], "1000:1000")
        # Docker Desktop already maps ownership, so no --user is passed where uid/gid do not exist.
        self.assertNotIn("--user", S.docker_command("/repo", "dev", "img:tag", [], None))

    def test_extra_capture_arguments_reach_the_capture_script(self):
        # capture_tutorial.mjs accepts [example] [outDir] [prefix] and --print-paths. Without
        # passthrough a single-scene recapture would still need the raw, unguarded command.
        with mock.patch.object(S, "host_matches_ci_renderer", return_value=True), \
                mock.patch.object(S, "_in_ci", return_value=False), \
                mock.patch.object(S.shutil, "which", return_value="/usr/bin/node"), \
                mock.patch.object(S, "_deps_installed", return_value=True), \
                mock.patch.object(S, "_run", return_value=0) as run:
            rc = S.main(["shots_linux.py", "--print-paths", "examples/report-checklist.html"])
        self.assertEqual(rc, 0)
        joined = " ".join(run.call_args[0][0])
        self.assertIn("--print-paths", joined)
        self.assertIn("examples/report-checklist.html", joined)


class HostDispatchTests(unittest.TestCase):
    UBUNTU_2404 = {"ID": "ubuntu", "VERSION_ID": "24.04"}

    def test_only_the_exact_ci_platform_renders_natively(self):
        # `sys.platform.startswith("linux")` is NOT enough: Fedora, an older Ubuntu, or an ARM Linux
        # host has different fonts or a different rasterizer, so rendering natively there
        # reintroduces the very bug this tool exists to prevent.
        self.assertTrue(S.host_matches_ci_renderer("linux", "x86_64", self.UBUNTU_2404))
        self.assertTrue(S.host_matches_ci_renderer("linux", "AMD64", self.UBUNTU_2404))
        self.assertFalse(S.host_matches_ci_renderer("win32", "x86_64", self.UBUNTU_2404))
        self.assertFalse(S.host_matches_ci_renderer("darwin", "arm64", {}))
        self.assertFalse(S.host_matches_ci_renderer("linux", "aarch64", self.UBUNTU_2404),
                         "an ARM Linux host does not match the x86_64 CI runner")
        self.assertFalse(S.host_matches_ci_renderer("linux", "x86_64",
                                                    {"ID": "ubuntu", "VERSION_ID": "22.04"}),
                         "a different Ubuntu release has a different font set")
        self.assertFalse(S.host_matches_ci_renderer("linux", "x86_64",
                                                    {"ID": "fedora", "VERSION_ID": "40"}))
        self.assertFalse(S.host_matches_ci_renderer("linux", "x86_64", {}),
                         "an unreadable /etc/os-release must fail closed, not assume a match")

    def test_the_pinned_release_is_derived_from_the_same_constant_as_the_image(self):
        self.assertTrue(S.UBUNTU_RELEASES[S.IMAGE_VARIANT].endswith(S.CI_UBUNTU_VERSION))

    def test_a_ci_matching_host_captures_natively_and_never_needs_docker(self):
        # Docker must NOT become a blanket requirement: where the host renderer already matches CI,
        # the tool runs node directly.
        with mock.patch.object(S, "host_matches_ci_renderer", return_value=True), \
                mock.patch.object(S, "_in_ci", return_value=False), \
                mock.patch.object(S.shutil, "which", side_effect=lambda n: None if n == "docker" else "/usr/bin/" + n), \
                mock.patch.object(S, "_deps_installed", return_value=True), \
                mock.patch.object(S, "_run", return_value=0) as run:
            rc = S.main(["shots_linux.py"])
        self.assertEqual(rc, 0)
        cmd = run.call_args[0][0]
        self.assertNotIn("docker", cmd[0])
        self.assertIn("capture_tutorial.mjs", " ".join(cmd))

    def test_a_non_matching_linux_host_falls_back_to_the_container_automatically(self):
        # The user must not have to remember --container on Fedora/ARM/22.04; getting it wrong is
        # silent, so the tool decides.
        with mock.patch.object(S, "host_matches_ci_renderer", return_value=False), \
                mock.patch.object(S, "_in_ci", return_value=False), \
                mock.patch.object(S.shutil, "which", return_value="/usr/bin/docker"), \
                mock.patch.object(S, "_docker_daemon_ok", return_value=True), \
                mock.patch.object(S, "_deps_installed", return_value=True), \
                mock.patch.object(S, "_run", return_value=0) as run:
            rc = S.main(["shots_linux.py"])
        self.assertEqual(rc, 0)
        self.assertEqual(run.call_args[0][0][0], "docker")

    def test_ci_always_renders_natively_even_if_the_probe_cannot_confirm_the_platform(self):
        # Fail-closed on a dev box, fail-OPEN in CI: if /etc/os-release ever changes shape, the
        # required CI check must still RUN rather than silently skip and lose the gate.
        with mock.patch.object(S, "host_matches_ci_renderer", return_value=False), \
                mock.patch.object(S, "_in_ci", return_value=True), \
                mock.patch.object(S.shutil, "which", return_value="/usr/bin/node"), \
                mock.patch.object(S, "_deps_installed", return_value=True), \
                mock.patch.object(S, "_run", return_value=0) as run:
            rc = S.main(["shots_linux.py", "--check", "--skip-unless-ci-renderer"])
        self.assertEqual(rc, 0)
        run.assert_called_once()
        self.assertIn("capture_tutorial.mjs", " ".join(run.call_args[0][0]))

    def test_the_ci_escape_hatch_is_scoped_to_a_linux_runner(self):
        # A bare truthy CI is not enough: a Windows/macOS CI job (or a local shell exporting CI=1)
        # would otherwise bypass the platform guard and rewrite the PNGs with the wrong renderer.
        with mock.patch.dict(os.environ, {"CI": "true"}, clear=False), \
                mock.patch.object(S.sys, "platform", "win32"):
            self.assertFalse(S._in_ci())
        with mock.patch.dict(os.environ, {"CI": "true"}, clear=False), \
                mock.patch.object(S.sys, "platform", "linux"):
            self.assertTrue(S._in_ci())
        for falsy in ("", "0", "false", "no"):
            with mock.patch.dict(os.environ, {"CI": falsy}, clear=False), \
                    mock.patch.object(S.sys, "platform", "linux"):
                self.assertFalse(S._in_ci(), "CI=%r must not count as a CI runner" % falsy)

    def test_a_non_linux_host_uses_the_pinned_container(self):
        with mock.patch.object(S, "host_matches_ci_renderer", return_value=False), \
                mock.patch.object(S, "_in_ci", return_value=False), \
                mock.patch.object(S.shutil, "which", return_value="/usr/bin/docker"), \
                mock.patch.object(S, "_docker_daemon_ok", return_value=True), \
                mock.patch.object(S, "_deps_installed", return_value=True), \
                mock.patch.object(S, "_run", return_value=0) as run:
            rc = S.main(["shots_linux.py", "--check"])
        self.assertEqual(rc, 0)
        cmd = run.call_args[0][0]
        self.assertEqual(cmd[0], "docker")
        self.assertIn("mcr.microsoft.com/playwright:v", " ".join(cmd))
        self.assertIn("--check", " ".join(cmd))


class IndicativeErrorTests(unittest.TestCase):
    """Each failure mode must name what is missing AND what to do about it."""

    def setUp(self):
        # Hermetic: these cases exercise the CONTAINER branch, which `_in_ci()` would short-circuit
        # to the native path when the suite itself runs on a CI runner.
        patcher = mock.patch.object(S, "_in_ci", return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _stderr_of(self, **patches):
        import io
        import contextlib
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            with mock.patch.object(S, "host_matches_ci_renderer", return_value=False):
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
        # It must say WHY docker is involved at all, name the exact image, and offer the escape hatch.
        self.assertIn("Linux", msg)
        self.assertIn("mcr.microsoft.com/playwright:v", msg)
        self.assertIn("docs/testing-guidelines.md", msg)

    def test_a_stopped_docker_daemon_is_distinguished_from_a_missing_docker(self):
        rc, msg = self._stderr_of(shutil=dict(which=mock.Mock(return_value="/usr/bin/docker")),
                                  _docker_daemon_ok=dict(return_value=False),
                                  _deps_installed=dict(return_value=True))
        self.assertNotEqual(rc, 0)
        self.assertIn("daemon", msg.lower())
        self.assertNotIn("not installed", msg.lower())

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
    def test_package_json_exposes_shots_linux_and_its_check_variant(self):
        with open(os.path.join(_paths.DEV, "package.json"), encoding="utf-8") as fh:
            scripts = json.load(fh)["scripts"]
        self.assertIn("shots:linux", scripts)
        self.assertIn("shots:linux:check", scripts)
        for name in ("shots:linux", "shots:linux:check"):
            self.assertIn("shots_linux.py", scripts[name])
        self.assertIn("--check", scripts["shots:linux:check"])

    def test_the_habitual_shots_scripts_route_through_the_guard(self):
        # The motivating trap was that the SHORT, habitual command silently produced host-rendered
        # PNGs. Leaving `shots` pointed straight at the raw capture would re-open it, so both
        # legacy scripts go through shots_linux.py.
        with open(os.path.join(_paths.DEV, "package.json"), encoding="utf-8") as fh:
            scripts = json.load(fh)["scripts"]
        self.assertIn("shots_linux.py", scripts["shots"])
        self.assertIn("shots_linux.py", scripts["shots:check"])
        # `npm test` runs shots:check; it must not hard-fail (or demand Docker) on a dev laptop.
        self.assertIn("--skip-unless-ci-renderer", scripts["shots:check"])
        self.assertIn("shots:check", scripts["test"])

    def test_no_script_or_doc_hardcodes_the_container_image_tag(self):
        # A hardcoded tag is the drift this tool exists to prevent: it would keep pointing at an old
        # renderer after a Playwright bump.
        with open(os.path.join(_paths.DEV, "package.json"), encoding="utf-8") as fh:
            raw = fh.read()
        self.assertNotIn("mcr.microsoft.com/playwright", raw)


class SkipOffLinuxTests(unittest.TestCase):
    def setUp(self):
        # Hermetic: `_in_ci()` is true when this suite runs on a CI runner, which would flip the
        # dispatch to the native path and invalidate every case below.
        patcher = mock.patch.object(S, "_in_ci", return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_check_skips_cleanly_when_the_host_cannot_match_ci(self):
        # `npm test` runs this. On Windows the committed (Linux-rendered) PNGs never match the host
        # renderer, so a real check would FALSE-FAIL and its remediation text would point at the
        # unsafe capture. Skip with a note and exit 0 instead; CI (Linux) still runs it for real.
        import io
        import contextlib
        buf = io.StringIO()
        with mock.patch.object(S, "host_matches_ci_renderer", return_value=False), \
                mock.patch.object(S, "_deps_installed", return_value=True), \
                mock.patch.object(S, "_run") as run:
            with contextlib.redirect_stdout(buf):
                rc = S.main(["shots_linux.py", "--check", "--skip-unless-ci-renderer"])
        self.assertEqual(rc, 0)
        run.assert_not_called()
        out = buf.getvalue()
        self.assertIn("skipped", out.lower())
        self.assertIn("shots:linux", out)

    def test_skip_flag_still_runs_natively_on_the_ci_platform(self):
        with mock.patch.object(S, "host_matches_ci_renderer", return_value=True), \
                mock.patch.object(S, "_deps_installed", return_value=True), \
                mock.patch.object(S.shutil, "which", return_value="/usr/bin/node"), \
                mock.patch.object(S, "_run", return_value=0) as run:
            rc = S.main(["shots_linux.py", "--check", "--skip-unless-ci-renderer"])
        self.assertEqual(rc, 0)
        run.assert_called_once()

    def test_the_write_path_never_silently_skips(self):
        # Regenerating is the dangerous direction: it must produce a correct PNG or refuse loudly.
        with mock.patch.object(S, "host_matches_ci_renderer", return_value=False), \
                mock.patch.object(S, "_deps_installed", return_value=True), \
                mock.patch.object(S.shutil, "which", return_value=None):
            rc = S.main(["shots_linux.py", "--skip-unless-ci-renderer"])
        self.assertNotEqual(rc, 0)


class ContainerPinningTests(unittest.TestCase):
    def test_the_container_run_pins_the_amd64_platform(self):
        # The playwright image is multi-arch. On Apple Silicon docker would otherwise select arm64
        # and render with a different rasterizer than the x86_64 CI runner.
        cmd = S.docker_command("/repo", "plugins/commentable-html/dev", "img:tag", [])
        self.assertIn("--platform", cmd)
        self.assertEqual(cmd[cmd.index("--platform") + 1], "linux/amd64")

    def test_container_flag_forces_the_container_even_on_linux(self):
        # A Linux host that is NOT the CI Ubuntu release (Fedora, an older WSL distro) has its own
        # fonts, so it needs the same escape hatch a Windows host uses.
        with mock.patch.object(S, "host_matches_ci_renderer", return_value=True), \
                mock.patch.object(S, "_deps_installed", return_value=True), \
                mock.patch.object(S.shutil, "which", return_value="/usr/bin/docker"), \
                mock.patch.object(S, "_docker_daemon_ok", return_value=True), \
                mock.patch.object(S, "_run", return_value=0) as run:
            rc = S.main(["shots_linux.py", "--container"])
        self.assertEqual(rc, 0)
        self.assertEqual(run.call_args[0][0][0], "docker")

    def test_the_image_variant_matches_the_ubuntu_release_the_shots_ci_job_pins(self):
        # The container is only equivalent to CI while the two name the SAME Ubuntu release. CI does
        # NOT run inside this image (it installs chromium on a bare runner), so the correspondence is
        # by agreement, not by construction - this guard makes a future runner bump a conscious,
        # two-sided edit instead of a silent divergence.
        block = _shots_job_block(_workflow_text())
        runs_on = [ln.split(":", 1)[1].strip() for ln in block.split("\n")
                   if ln.strip().startswith("runs-on:")]
        self.assertEqual(runs_on, [S.UBUNTU_RELEASES[S.IMAGE_VARIANT]],
                         "the screenshot-validating job must pin exactly the Ubuntu release the "
                         "container image variant names")

    def test_the_job_block_helper_really_isolates_that_job(self):
        # The guard above is only meaningful if the block it inspects is the playwright-heavy job
        # and nothing else - a helper that returned one line, or the whole file, would make the
        # assertion vacuous.
        block = _shots_job_block(_workflow_text())
        self.assertTrue(block.startswith("  playwright-heavy:"))
        self.assertIn("runs-on:", block)
        self.assertNotIn("\n  playwright:", block)
        self.assertNotIn("\n  python:", block)


def _workflow_text():
    path = os.path.normpath(os.path.join(_paths.PLUGIN_ROOT, "..", "..", ".github", "workflows",
                                         "plugin-tests.yml"))
    with open(path, encoding="utf-8") as fh:
        return fh.read()


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
