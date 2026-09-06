"""Hermetic real-CLI lifecycle coverage for the marketplace auto-updater."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import tempfile
import threading
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit


MARKETPLACE = "urikan-ai-marketplace"
UPDATER = "urikan-ai-marketplace-auto-updater"
FIXTURE = "updater-lifecycle-fixture"
UPDATER_N = "1.5.0"
UPDATER_N1 = "1.5.1"
FIXTURE_N = "1.0.0"
FIXTURE_N1 = "1.1.0"
TEST_DIR = Path(__file__).resolve().parent
REPO_ROOT = TEST_DIR.parents[3]
UPDATER_PACKAGE = REPO_ROOT / "plugins" / UPDATER / "pkg"
CLI_BIN = TEST_DIR / "real-cli" / "node_modules" / ".bin"


def run(
    *args: str | os.PathLike[str],
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 90,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [str(arg) for arg in args],
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    if result.returncode:
        command = " ".join(str(arg) for arg in args)
        raise AssertionError(
            f"command failed ({result.returncode}): {command}\n{result.stdout}"
        )
    return result


def run_json(
    *args: str | os.PathLike[str],
    env: dict[str, str] | None = None,
    timeout: int = 90,
) -> object:
    result = subprocess.run(
        [str(arg) for arg in args],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    command = " ".join(str(arg) for arg in args)
    if result.returncode:
        raise AssertionError(
            f"command failed ({result.returncode}): {command}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise AssertionError(
            f"command returned invalid JSON: {command}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        ) from error


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def plugin_manifest(name: str, version: str) -> dict[str, object]:
    return {
        "name": name,
        "description": "Hermetic updater lifecycle fixture.",
        "version": version,
        "author": {"name": "Lifecycle Test", "email": "test@example.invalid"},
        "keywords": ["test"],
        "license": "MIT",
        "skills": "./skills/",
    }


def marketplace_manifest(
    updater_version: str, fixture_version: str, *, copilot: bool
) -> dict[str, object]:
    plugins = []
    for name, version in (
        (UPDATER, updater_version),
        (FIXTURE, fixture_version),
    ):
        entry: dict[str, object] = {
            "name": name,
            "description": "Hermetic updater lifecycle fixture.",
            "version": version,
            "source": f"./plugins/{name}/pkg",
            "author": {
                "name": "Lifecycle Test",
                "email": "test@example.invalid",
            },
            "license": "MIT",
            "keywords": ["test"],
        }
        if copilot:
            entry.update({"category": "infrastructure", "strict": False})
        plugins.append(entry)
    return {
        "name": MARKETPLACE,
        "metadata": {
            "description": "Hermetic updater lifecycle marketplace.",
            "version": updater_version,
        },
        "owner": {
            "name": "Lifecycle Test",
            "email": "test@example.invalid",
        },
        "plugins": plugins,
    }


def write_release(source: Path, updater_version: str, fixture_version: str) -> None:
    updater = source / "plugins" / UPDATER / "pkg"
    if updater.exists():
        shutil.rmtree(updater)
    shutil.copytree(UPDATER_PACKAGE, updater)
    for relative in ("plugin.json", ".claude-plugin/plugin.json"):
        path = updater / relative
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["version"] = updater_version
        write_json(path, manifest)
    (updater / "lifecycle-release.txt").write_text(
        f"{updater_version}\n", encoding="utf-8"
    )

    fixture = source / "plugins" / FIXTURE / "pkg"
    write_json(fixture / "plugin.json", plugin_manifest(FIXTURE, fixture_version))
    write_json(
        fixture / ".claude-plugin" / "plugin.json",
        plugin_manifest(FIXTURE, fixture_version),
    )
    skill = fixture / "skills" / "lifecycle-fixture" / "SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text(
        "---\n"
        "name: lifecycle-fixture\n"
        "description: Hermetic marker used only by the updater lifecycle test.\n"
        "---\n\n"
        f"Release {fixture_version}.\n",
        encoding="utf-8",
    )

    write_json(
        source / ".github" / "plugin" / "marketplace.json",
        marketplace_manifest(updater_version, fixture_version, copilot=True),
    )
    write_json(
        source / ".claude-plugin" / "marketplace.json",
        marketplace_manifest(updater_version, fixture_version, copilot=False),
    )


class GitHttpHandler(BaseHTTPRequestHandler):
    server: "GitHttpServer"

    def do_GET(self) -> None:
        self._run_backend()

    def do_POST(self) -> None:
        self._run_backend()

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _run_backend(self) -> None:
        parsed = urlsplit(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b""
        env = os.environ.copy()
        env.update(
            {
                "GIT_PROJECT_ROOT": str(self.server.project_root),
                "GIT_HTTP_EXPORT_ALL": "1",
                "PATH_INFO": unquote(parsed.path),
                "QUERY_STRING": parsed.query,
                "REQUEST_METHOD": self.command,
                "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                "CONTENT_LENGTH": str(length),
                "REMOTE_ADDR": self.client_address[0],
            }
        )
        result = subprocess.run(
            ["git", "http-backend"],
            input=body,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        headers, separator, payload = result.stdout.partition(b"\r\n\r\n")
        if not separator:
            self.send_error(500, result.stderr.decode("utf-8", "replace"))
            return
        status = 200
        forwarded: list[tuple[str, str]] = []
        for line in headers.decode("iso-8859-1").split("\r\n"):
            if ":" not in line:
                self.send_error(500, f"malformed git http-backend header: {line}")
                return
            name, value = line.split(":", 1)
            if name.lower() == "status":
                status = int(value.strip().split(" ", 1)[0])
            else:
                forwarded.append((name.strip(), value.strip()))
        self.send_response(status)
        for name, value in forwarded:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(payload)


class GitHttpServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, project_root: Path):
        self.project_root = project_root
        super().__init__(("127.0.0.1", 0), GitHttpHandler)


@contextmanager
def serve_git(project_root: Path):
    server = GitHttpServer(project_root)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        yield f"http://127.0.0.1:{port}/marketplace.git"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def isolated_env(root: Path, agent: str) -> dict[str, str]:
    env = os.environ.copy()
    home = root / agent
    home.mkdir(parents=True)
    local_data = home / "local-data"
    roaming_data = home / "roaming-data"
    xdg_cache = home / "xdg-cache"
    xdg_config = home / "xdg-config"
    xdg_data = home / "xdg-data"
    xdg_state = home / "xdg-state"
    process_temp = home / "tmp"
    for path in (
        local_data,
        roaming_data,
        xdg_cache,
        xdg_config,
        xdg_data,
        xdg_state,
        process_temp,
    ):
        path.mkdir()
    env.update(
        {
            "HOME": str(home),
            "USERPROFILE": str(home),
            "LOCALAPPDATA": str(local_data),
            "APPDATA": str(roaming_data),
            "XDG_CACHE_HOME": str(xdg_cache),
            "XDG_CONFIG_HOME": str(xdg_config),
            "XDG_DATA_HOME": str(xdg_data),
            "XDG_STATE_HOME": str(xdg_state),
            "TEMP": str(process_temp),
            "TMP": str(process_temp),
            "TMPDIR": str(process_temp),
            "GIT_CONFIG_GLOBAL": str(home / ".gitconfig"),
            "GIT_CONFIG_NOSYSTEM": "1",
            "NO_PROXY": "127.0.0.1,localhost",
            "no_proxy": "127.0.0.1,localhost",
            "URIKAN_AI_MARKETPLACE_THROTTLE_HOURS": "0",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            "DISABLE_TELEMETRY": "1",
        }
    )
    if agent == "copilot":
        env["COPILOT_HOME"] = str(home)
        env["COPILOT_CACHE_HOME"] = str(root / "copilot-cache")
    else:
        env["CLAUDE_CONFIG_DIR"] = str(home)
    return env


def manifest_version(package_root: Path) -> str:
    for relative in ("plugin.json", ".claude-plugin/plugin.json"):
        path = package_root / relative
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))["version"]
    raise AssertionError(f"no plugin manifest under {package_root}")


def copilot_package(home: Path, name: str) -> Path:
    package = home / "installed-plugins" / MARKETPLACE / name
    if not package.is_dir():
        raise AssertionError(f"Copilot package was not installed at {package}")
    return package


def claude_package(home: Path, name: str, version: str) -> Path:
    package = home / "plugins" / "cache" / MARKETPLACE / name / version
    if not package.is_dir():
        raise AssertionError(f"Claude package was not installed at {package}")
    return package


def install_agent(
    executable: str,
    agent: str,
    marketplace_url: str,
    env: dict[str, str],
) -> None:
    if agent == "copilot":
        run(executable, "plugin", "marketplace", "add", marketplace_url, env=env)
        for plugin in (UPDATER, FIXTURE):
            run(
                executable,
                "plugin",
                "install",
                f"{plugin}@{MARKETPLACE}",
                env=env,
            )
    else:
        run(
            executable,
            "plugin",
            "marketplace",
            "add",
            marketplace_url,
            "--scope",
            "user",
            env=env,
        )
        for plugin in (UPDATER, FIXTURE):
            run(
                executable,
                "plugin",
                "install",
                f"{plugin}@{MARKETPLACE}",
                "--scope",
                "user",
                "--yes",
                env=env,
            )


def plugin_records(value: object, name: str) -> list[dict[str, object]]:
    records = []
    if isinstance(value, dict):
        identity = " ".join(
            str(value.get(key, "")) for key in ("id", "name", "plugin")
        )
        if name in identity and "version" in value:
            records.append(value)
        for child in value.values():
            records.extend(plugin_records(child, name))
    elif isinstance(value, list):
        for child in value:
            records.extend(plugin_records(child, name))
    return records


def resolve_cli(name: str) -> str | None:
    if name == "claude":
        system = {
            "Darwin": "darwin",
            "Linux": "linux",
            "Windows": "win32",
        }.get(platform.system())
        machine = platform.machine().lower()
        architecture = "arm64" if machine in {"arm64", "aarch64"} else "x64"
        if system:
            package = (
                TEST_DIR
                / "real-cli"
                / "node_modules"
                / "@anthropic-ai"
                / f"claude-code-{system}-{architecture}"
            )
            binary = package / ("claude.exe" if system == "win32" else "claude")
            if binary.is_file():
                return str(binary)
    installed = CLI_BIN / (f"{name}.cmd" if os.name == "nt" else name)
    if installed.is_file():
        return str(installed)
    return shutil.which(name)


class RealCliLifecycleTests(unittest.TestCase):
    def test_upd_29_real_cli_updater_lifecycle(self) -> None:
        """UPD-29 real CLI updater lifecycle."""
        copilot = resolve_cli("copilot")
        claude = resolve_cli("claude")
        pwsh = shutil.which("pwsh")
        missing = [
            name
            for name, executable in (
                ("copilot", copilot),
                ("claude", claude),
                ("pwsh", pwsh),
            )
            if executable is None
        ]
        if missing:
            raise unittest.SkipTest(
                "real CLI lifecycle dependencies are missing: "
                + ", ".join(missing)
            )

        with tempfile.TemporaryDirectory(prefix="updater-real-cli-") as temp:
            root = Path(temp)
            source = root / "source"
            remote = root / "server" / "marketplace.git"
            source.mkdir()
            remote.parent.mkdir()
            run("git", "init", "--initial-branch=main", source)
            run("git", "config", "user.name", "Lifecycle Test", cwd=source)
            run(
                "git",
                "config",
                "user.email",
                "test@example.invalid",
                cwd=source,
            )
            write_release(source, UPDATER_N, FIXTURE_N)
            run("git", "add", ".", cwd=source)
            run("git", "commit", "-m", "release N", cwd=source)
            run("git", "init", "--bare", remote)
            run("git", "remote", "add", "origin", remote, cwd=source)
            run("git", "push", "--set-upstream", "origin", "main", cwd=source)
            run(
                "git",
                f"--git-dir={remote}",
                "symbolic-ref",
                "HEAD",
                "refs/heads/main",
            )

            copilot_env = isolated_env(root, "copilot")
            claude_env = isolated_env(root, "claude")
            copilot_env["PATH"] = (
                str(Path(copilot).parent)
                + os.pathsep
                + copilot_env.get("PATH", "")
            )
            claude_env["PATH"] = (
                str(Path(claude).parent)
                + os.pathsep
                + claude_env.get("PATH", "")
            )
            with serve_git(remote.parent) as marketplace_url:
                install_agent(copilot, "copilot", marketplace_url, copilot_env)
                install_agent(claude, "claude", marketplace_url, claude_env)

                copilot_home = Path(copilot_env["COPILOT_HOME"])
                claude_home = Path(claude_env["CLAUDE_CONFIG_DIR"])
                copilot_updater_n = copilot_package(copilot_home, UPDATER)
                self.assertEqual(
                    manifest_version(copilot_updater_n), UPDATER_N
                )
                self.assertEqual(
                    (copilot_updater_n / "lifecycle-release.txt").read_text(
                        encoding="utf-8"
                    ),
                    f"{UPDATER_N}\n",
                )
                self.assertEqual(
                    manifest_version(copilot_package(copilot_home, FIXTURE)),
                    FIXTURE_N,
                )
                claude_updater_n = claude_package(
                    claude_home, UPDATER, UPDATER_N
                )
                self.assertEqual(
                    (claude_updater_n / "lifecycle-release.txt").read_text(
                        encoding="utf-8"
                    ),
                    f"{UPDATER_N}\n",
                )
                self.assertEqual(
                    manifest_version(
                        claude_package(claude_home, FIXTURE, FIXTURE_N)
                    ),
                    FIXTURE_N,
                )

                write_release(source, UPDATER_N1, FIXTURE_N1)
                run("git", "add", ".", cwd=source)
                run("git", "commit", "-m", "release N+1", cwd=source)
                run("git", "push", "origin", "main", cwd=source)

                run(
                    pwsh,
                    "-NoProfile",
                    "-File",
                    copilot_updater_n / "hooks" / "marketplace-update.ps1",
                    env=copilot_env,
                )
                run(
                    pwsh,
                    "-NoProfile",
                    "-File",
                    claude_updater_n / "hooks" / "marketplace-update.ps1",
                    "-Agent",
                    "claude",
                    env=claude_env,
                )

                copilot_status = json.loads(
                    (
                        copilot_home
                        / "plugin-data"
                        / f"{UPDATER}.status.json"
                    ).read_text(encoding="utf-8-sig")
                )
                claude_status = json.loads(
                    (
                        claude_home
                        / "plugin-data"
                        / f"{UPDATER}.status.json"
                    ).read_text(encoding="utf-8-sig")
                )
                for agent, status in (
                    ("copilot", copilot_status),
                    ("claude", claude_status),
                ):
                    outcomes = {
                        outcome["name"]: outcome
                        for outcome in status["plugins"]
                    }
                    self.assertEqual(
                        status["result"], "success", f"{agent}: {status}"
                    )
                    self.assertTrue(
                        status["restartRequired"], f"{agent}: {status}"
                    )
                    self.assertEqual(
                        outcomes[FIXTURE]["beforeVersion"], FIXTURE_N
                    )
                    self.assertEqual(
                        outcomes[FIXTURE]["finalVersion"], FIXTURE_N1
                    )
                    self.assertEqual(outcomes[FIXTURE]["result"], "updated")
                    self.assertEqual(
                        outcomes[UPDATER]["beforeVersion"], UPDATER_N
                    )
                    self.assertEqual(
                        outcomes[UPDATER]["finalVersion"], UPDATER_N1
                    )
                    self.assertTrue(outcomes[UPDATER]["restartRequired"])

                self.assertEqual(
                    manifest_version(
                        copilot_package(copilot_home, UPDATER)
                    ),
                    UPDATER_N1,
                )
                self.assertEqual(
                    (
                        copilot_package(copilot_home, UPDATER)
                        / "lifecycle-release.txt"
                    ).read_text(encoding="utf-8"),
                    f"{UPDATER_N1}\n",
                )
                self.assertEqual(
                    manifest_version(
                        copilot_package(copilot_home, FIXTURE)
                    ),
                    FIXTURE_N1,
                )
                claude_updater_n1 = claude_package(
                    claude_home, UPDATER, UPDATER_N1
                )
                self.assertEqual(
                    (
                        claude_updater_n1 / "lifecycle-release.txt"
                    ).read_text(encoding="utf-8"),
                    f"{UPDATER_N1}\n",
                )
                self.assertEqual(
                    manifest_version(
                        claude_package(claude_home, FIXTURE, FIXTURE_N1)
                    ),
                    FIXTURE_N1,
                )

                for agent, package, env in (
                    ("copilot", copilot_package(copilot_home, UPDATER), copilot_env),
                    ("claude", claude_updater_n1, claude_env),
                ):
                    active = run_json(
                        pwsh,
                        "-NoProfile",
                        "-File",
                        package / "hooks" / "marketplace-update.ps1",
                        "-Agent",
                        agent,
                        "-Mode",
                        "health",
                        env=env,
                    )
                    self.assertEqual(
                        active["activeUpdaterVersion"], UPDATER_N1
                    )
                    self.assertFalse(active["restartRequired"])

                copilot_registry = run(
                    copilot, "plugin", "list", env=copilot_env
                ).stdout
                self.assertIn(
                    f"{UPDATER}@{MARKETPLACE} (v{UPDATER_N1})",
                    copilot_registry,
                )
                claude_registry = run_json(
                    claude,
                    "plugin",
                    "list",
                    "--json",
                    env=claude_env,
                )
                updater_records = plugin_records(claude_registry, UPDATER)
                self.assertTrue(
                    updater_records,
                    f"Claude registry omitted {UPDATER}: {claude_registry}",
                )
                self.assertIn(
                    UPDATER_N1,
                    {str(record["version"]) for record in updater_records},
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
