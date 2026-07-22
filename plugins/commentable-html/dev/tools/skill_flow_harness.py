#!/usr/bin/env python3
"""Local-only regression harness for the commentable-html Copilot skill flows.

It drives the INSTALLED ``copilot`` executable, non-interactively, through the skill's create /
retrofit / deck / export / validation-handoff routes and then RE-VALIDATES each produced artifact
with this repo's own tools - so a skill regression that makes the agent emit an invalid document is
caught even when the agent reports success. It is a manual, local tool: it HARD-refuses to run under
CI, it is wired into no workflow, and every scratch file lives under the repo's gitignored ``tmp/``.

Usage (from anywhere in the repo):

    python plugins/commentable-html/dev/tools/skill_flow_harness.py            # run all flows
    python .../skill_flow_harness.py --flows create,deck                       # a subset
    python .../skill_flow_harness.py --list                                    # list flow names
    python .../skill_flow_harness.py --dry-run                                 # print commands only
    python .../skill_flow_harness.py --model claude-sonnet-4.5 --keep          # pin a model, keep scratch

Each flow makes an isolated workspace ``<repo>/tmp/skill-flow-harness/<run-id>/<flow>/`` with the
shipped skill copied into ``<ws>/.github/skills/commentable-html/`` (which is how ``copilot -C <ws>``
discovers it), invokes copilot with the flow's prompt, and re-checks the artifact. Because it calls a
live model, it consumes AI credits and is non-deterministic - see ``skill_flow_harness.md``.
"""
import argparse
import datetime
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent            # .../dev/tools
DEV = HERE.parent                                 # .../dev
PLUGIN = DEV.parent                               # .../commentable-html
REPO_ROOT = PLUGIN.parent.parent                  # repo root (plugins/<plugin> -> up 2)
PKG_SKILL = PLUGIN / "pkg" / "skills" / "commentable-html"
SKILL_RESOURCES_ZIP = "skill-resources.zip"
SKILL_TOOLS = DEV / "skill" / "tools"
VALIDATE_PY = SKILL_TOOLS / "validate" / "validate.py"
DECK_VALIDATE_PY = SKILL_TOOLS / "deck" / "deck_validate.py"

sys.path.insert(0, str(HERE))
import skill_flow_prompts  # noqa: E402

# The token validate.py / doc_stamp.py write on a clean --strict pass. Used only to confirm the
# validation-handoff flow left the artifact stamped. A test ties it to doc_stamp.VALIDATED_META.
STAMP_TOKEN = "commentable-html-validated"
# The actual validated-stamp <meta> tag with NON-EMPTY content (the bare token also appears in the
# runtime JS, so a substring check would be vacuous - require the real meta tag).
_VALIDATED_META_RE = re.compile(
    r'<meta\s+name=["\']%s["\']\s+content=["\'][^"\']+["\']' % re.escape(STAMP_TOKEN), re.I)
# A commentable document embeds a content root keyed with data-comment-key; used as the positive
# half of the portable check (absence of companion refs alone would pass a bare HTML file).
_LAYER_RE = re.compile(r'data-comment-key\s*=', re.I)
# Resource-loading elements whose src/href, when it points at a LOCAL relative path, means the file is
# NOT self-contained (a portable file must embed or remote-load its assets, never need a companion
# file). <a> is excluded on purpose - a hyperlink is navigation, not a required companion asset.
_RESOURCE_REF_RE = re.compile(
    r'<(?:script|link|img|iframe|source|audio|video)\b[^>]*?\b(?:src|href)\s*=\s*["\']([^"\']+)["\']', re.I)
# A ref that needs no companion FILE: inline data, a remote URL, an in-page fragment, or a protocol.
_SELF_CONTAINED_REF_RE = re.compile(r'^(?:data:|https?:|//|#|mailto:|javascript:|blob:|about:)', re.I)

# CI environment variables that must make the harness refuse to run. This is belt-and-suspenders on
# top of the real guarantee (the harness is wired into no workflow); it covers the common CI systems.
_CI_ENV_VARS = ("CI", "GITHUB_ACTIONS", "CONTINUOUS_INTEGRATION", "TF_BUILD", "GITLAB_CI",
                "JENKINS_URL", "CIRCLECI", "BUILDKITE", "TEAMCITY_VERSION", "APPVEYOR", "TRAVIS")


def is_ci_environment(env=None):
    """True when a well-known CI env var is set to a non-empty, non-false value."""
    env = os.environ if env is None else env
    for name in _CI_ENV_VARS:
        val = env.get(name)
        if val is not None and str(val).strip().lower() not in ("", "0", "false", "no"):
            return True
    return False


def scratch_root():
    """Root for all harness scratch - always under the repo's gitignored tmp/ (never elsewhere)."""
    return REPO_ROOT / "tmp" / "skill-flow-harness"


def _safe_subpath(base, rel):
    """Resolve ``rel`` under ``base``, clamping leading separators and refusing to escape ``base``.

    Leading ``/`` or ``\\`` are stripped (an absolute-looking corpus path is treated as workspace
    relative, not as an escape to the filesystem root), and any resulting path outside ``base`` (for
    example via ``..``) raises. This keeps the tmp-only invariant structural, not trust-based, and
    doubles as a zip-slip guard when extracting the skill resources.
    """
    base = Path(base).resolve()
    dest = (base / str(rel).lstrip("/\\")).resolve()
    if dest != base and base not in dest.parents:
        raise ValueError("path %r escapes the workspace %s" % (rel, base))
    return dest


def build_copilot_command(prompt, workspace, model=None, copilot_bin="copilot"):
    """The non-interactive copilot invocation for one flow (pure, so the test can assert it).

    File access is SCOPED to the workspace (``-C`` sets the cwd and ``--add-dir`` allowlists it) rather
    than opened up with ``--allow-all-paths`` - the workspace lives under the gitignored ``tmp/``, so
    the agent's file tools cannot touch a tracked file. ``--allow-all-tools`` is still required for a
    non-interactive run (no permission prompts). Note the agent still has a shell, so containment is
    best-effort; run this only with a trusted model (it is a local-only tool - see the docs).
    """
    cmd = [
        copilot_bin,
        "-C", str(workspace),
        "-p", prompt,
        "--allow-all-tools",          # required for non-interactive mode (no permission prompts)
        "--add-dir", str(workspace),  # scope file access to the workspace (under tmp/), not all paths
        "--no-color",
    ]
    if model:
        cmd += ["--model", model]
    return cmd


def validator_command(kind, artifact, python_exe=None):
    """The subprocess command for a tool-backed validator, or None for a content-only check.

    The harness re-validates READ-ONLY: it passes ``--no-stamp`` so validate.py never writes the
    validated stamp into the artifact. That keeps the harness from mutating the file it is checking
    (so a symlinked artifact cannot be used to write through to a tracked file) and, crucially, keeps
    the validation-handoff ``stamp`` check honest - the stamp must have come from the AGENT, not from
    the harness's own validation pass.
    """
    python_exe = python_exe or sys.executable
    if kind == "validate":
        return [python_exe, str(VALIDATE_PY), "--strict", "--no-stamp", str(artifact)]
    if kind == "deck_validate":
        return [python_exe, str(DECK_VALIDATE_PY), "--strict", str(artifact)]
    if kind in ("portable", "stamp"):
        return None
    raise ValueError("unknown validator kind: %r" % kind)


def _content_check(kind, html):
    if kind == "portable":
        for m in _RESOURCE_REF_RE.finditer(html):
            ref = m.group(1).strip()
            if not _SELF_CONTAINED_REF_RE.match(ref):
                return (False, "references companion file %r (not self-contained)" % ref)
        if _LAYER_RE.search(html) is None:
            return (False, "no embedded review layer (missing data-comment-key)")
        return (True, "self-contained with embedded layer")
    if kind == "stamp":
        ok = _VALIDATED_META_RE.search(html) is not None
        return (ok, "stamped" if ok else "missing <meta name=%r> validated stamp" % STAMP_TOKEN)
    raise ValueError("unknown content check: %r" % kind)


def _run_validator(kind, artifact, timeout=120):
    cmd = validator_command(kind, artifact)
    if cmd is None:
        try:
            html = Path(artifact).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return {"kind": kind, "ok": False, "detail": "could not read artifact: %s" % exc}
        ok, detail = _content_check(kind, html)
        return {"kind": kind, "ok": ok, "detail": detail}
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              encoding="utf-8", errors="replace",
                              env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    except subprocess.TimeoutExpired:
        return {"kind": kind, "ok": False, "detail": "validator timed out after %ss" % timeout}
    ok = proc.returncode == 0
    detail = "ok" if ok else (proc.stdout + proc.stderr).strip()[-800:]
    return {"kind": kind, "ok": ok, "detail": detail}


def _extract_skill_resources(skills_dir):
    """Materialize the shipped skill's tools/ and references/ from skill-resources.zip.

    The shipped skill packages its whole tool tree inside skill-resources.zip - the copied skill dir
    otherwise contains only SKILL.md and the zip, so every flow that references ``tools/...`` would
    fail. Extract it into the copied skill dir so each workspace holds the complete shipped skill
    exactly as an installed one, and so the flows exercise THIS repo's shipped resources rather than
    whatever skill happens to be installed on the machine.
    """
    zip_path = skills_dir / SKILL_RESOURCES_ZIP
    if not zip_path.is_file():
        return
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.namelist():
            _safe_subpath(skills_dir, member)   # zip-slip guard: refuse entries that escape skills_dir
        zf.extractall(skills_dir)


def _prepare_workspace(flow, ws):
    (ws / "output").mkdir(parents=True, exist_ok=True)
    skills_dir = ws / ".github" / "skills" / "commentable-html"
    skills_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(PKG_SKILL, skills_dir)
    _extract_skill_resources(skills_dir)
    for rel, content in (flow.get("seed_files") or {}).items():
        dest = _safe_subpath(ws, rel)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")


def run_flow(flow, run_dir, model=None, copilot_bin="copilot", timeout=1800):
    # Defense in depth: never spawn a live model under CI even if called directly (main() also guards).
    if is_ci_environment():
        raise RuntimeError("run_flow must never run under CI - this harness calls a live model")
    # Refuse a run_dir that is not under the gitignored scratch root, so a caller cannot make the
    # harness write into a tracked tree (main() always passes scratch_root()/<run-id>).
    run_dir = Path(run_dir)
    root = scratch_root().resolve()
    if run_dir.resolve() != root and root not in run_dir.resolve().parents:
        raise ValueError("run_dir %s must be under the scratch root %s" % (run_dir, root))
    ws = run_dir / flow["name"]
    _prepare_workspace(flow, ws)
    cmd = build_copilot_command(flow["prompt"], ws, model=model, copilot_bin=copilot_bin)
    log_path = ws / "copilot.log"
    # Do not let subprocesses (copilot's Python tools, our validators) drop __pycache__ outside tmp/,
    # and drop COPILOT_ALLOW_ALL (== --allow-all, which would re-enable --allow-all-paths).
    child_env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    child_env.pop("COPILOT_ALLOW_ALL", None)
    started = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              encoding="utf-8", errors="replace", env=child_env)
        rc = proc.returncode
        log_path.write_text((proc.stdout or "") + "\n----- STDERR -----\n" + (proc.stderr or ""),
                            encoding="utf-8")
    except subprocess.TimeoutExpired as exc:
        out, err = exc.output or exc.stdout or "", exc.stderr or ""
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        if isinstance(err, bytes):
            err = err.decode("utf-8", "replace")
        log_path.write_text("copilot timed out after %ss\n----- STDOUT -----\n%s\n----- STDERR -----\n%s"
                            % (timeout, out, err), encoding="utf-8")
        rc = None
    elapsed = round(time.time() - started, 1)

    artifact = ws / str(flow["output"]).lstrip("/\\")
    result = {"name": flow["name"], "workspace": str(ws), "copilot_rc": rc, "seconds": elapsed,
              "artifact": str(artifact), "log": str(log_path), "validators": []}
    # A timeout (rc is None) means the run never completed - a hung/looping agent is a regression even
    # if a valid artifact was written earlier, so fail it outright rather than trusting the leftover.
    if rc is None:
        result["ok"] = False
        result["error"] = "copilot timed out after %ss - the artifact is not trusted" % timeout
        return result
    # Reject a missing artifact, or one whose REAL path (following symlinks) escapes the workspace -
    # the agent runs with workspace-scoped file access, and this fails the flow (never raises) so a
    # rogue symlink cannot abort the whole batch.
    if not artifact.is_file() or ws.resolve() not in artifact.resolve().parents:
        result["ok"] = False
        result["error"] = "the agent did not produce the expected artifact %s inside the workspace" % flow["output"]
        return result
    for kind in flow["validators"]:
        result["validators"].append(_run_validator(kind, artifact))
    result["ok"] = all(v["ok"] for v in result["validators"])
    return result


def _select_flows(names_arg):
    by_name = skill_flow_prompts.flows_by_name()
    if not names_arg:
        return list(skill_flow_prompts.FLOWS)
    selected = []
    for name in [n.strip() for n in names_arg.split(",") if n.strip()]:
        if name not in by_name:
            raise SystemExit("unknown flow %r (known: %s)" % (name, ", ".join(by_name)))
        selected.append(by_name[name])
    return selected


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--flows", help="comma-separated flow names (default: all). See --list.")
    parser.add_argument("--model", help="pin the copilot model (default: copilot's choice)")
    parser.add_argument("--copilot", default="copilot", help="path to the copilot executable")
    parser.add_argument("--timeout", type=int, default=1800, help="per-flow copilot timeout (seconds)")
    parser.add_argument("--keep", action="store_true", help="keep scratch even on success")
    parser.add_argument("--list", action="store_true", help="list flow names and exit")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the copilot command per flow without running it (no model call)")
    args = parser.parse_args(argv)

    if args.list:
        print("\n".join(skill_flow_prompts.flow_names()))
        return 0

    flows = _select_flows(args.flows)

    # --dry-run and --list are inert (no model call), so they work anywhere, including CI. Only a
    # real run is refused under CI below.
    if args.dry_run:
        for flow in flows:
            ws = scratch_root() / "DRYRUN" / flow["name"]
            cmd = build_copilot_command(flow["prompt"], ws, model=args.model, copilot_bin=args.copilot)
            printable = " ".join(('"%s"' % c if (" " in c or "\n" in c) else c) for c in cmd)
            print("# flow: %s -> %s" % (flow["name"], flow["output"]))
            print(printable)
            print()
        return 0

    # Never actually RUN in CI. This is a manual, credit-consuming, non-deterministic local tool.
    if is_ci_environment():
        print("skill_flow_harness: refusing to run under CI - this harness calls a live model and is "
              "local-only by design (see skill_flow_harness.md).", file=sys.stderr)
        return 3

    if shutil.which(args.copilot) is None and not Path(args.copilot).exists():
        print("skill_flow_harness: could not find the copilot executable %r on PATH. Install the "
              "GitHub Copilot CLI or pass --copilot <path>." % args.copilot, file=sys.stderr)
        return 2

    run_id = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    run_dir = scratch_root() / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    print("skill_flow_harness: %d flow(s) into %s\n" % (len(flows), run_dir))

    results = []
    for flow in flows:
        print("-> %-9s ..." % flow["name"], end="", flush=True)
        try:
            result = run_flow(flow, run_dir, model=args.model, copilot_bin=args.copilot,
                              timeout=args.timeout)
        except Exception as exc:  # noqa: BLE001 - one flow's failure must not abort the batch
            result = {"name": flow["name"], "ok": False, "copilot_rc": None, "validators": [],
                      "error": "harness error: %s" % exc}
        results.append(result)
        status = "PASS" if result["ok"] else "FAIL"
        print(" %s (rc=%s, %ss)" % (status, result.get("copilot_rc"), result.get("seconds", "?")))
        if result["ok"] and result.get("copilot_rc") not in (0,):
            # The artifact re-validated clean, but copilot itself did not exit 0 (crash or timeout);
            # surface it so a passing-but-crashed run is never silent.
            print("     note: copilot exited rc=%s but the artifact re-validated clean"
                  % result.get("copilot_rc"))
        if not result["ok"]:
            if result.get("error"):
                print("     %s" % result["error"])
            for v in result.get("validators", []):
                if not v["ok"]:
                    print("     validator %s: %s" % (v["kind"], v["detail"]))
            print("     see %s" % result.get("log"))

    passed = sum(1 for r in results if r["ok"])
    print("\nskill_flow_harness: %d/%d passed" % (passed, len(results)))
    all_ok = passed == len(results)
    if all_ok and not args.keep:
        shutil.rmtree(run_dir, ignore_errors=True)
    else:
        print("scratch kept at %s" % run_dir)
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
