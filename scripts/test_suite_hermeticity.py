#!/usr/bin/env python3
"""The scripts unit suite must never touch the repository it runs in.

Git hooks export location variables (`GIT_DIR`, `GIT_INDEX_FILE`, `GIT_WORK_TREE`, ...) that point
at the REAL repository. A test that spawns `git` in its own temporary directory INHERITS them, so
the command silently targets the real repo instead of the temp one: `git add` stages a fixture into
the real index, `git commit` puts a stray commit on the current branch, and the checker under test
reads the real index rather than the fixture. That is not theoretical - it is how the fixtures
`a.md` and `old.md` came to be tracked on `main` (#778, and the duplicate reports #772 and #773),
and it also made the conflict-marker suite FAIL on its own leftovers.

`scripts/_git_test_env.clean_git_env()` exists to scrub exactly those variables (#283). These two
guards keep every test on it: the static one is the general rule (any test that spawns git routes
its environment through the helper), and the behavioral one proves the rule is load-bearing by
running the real-git suite under an inherited hook environment and asserting the ambient repository
comes out byte-identical.

Scrubbing the environment closes only one of the two leak vectors, though. The other one (#791) is
plainer: a test that writes a bare relative filename puts it in whatever directory the suite was
launched from, and both `pre-push` and CI launch it from the repository root. `run_script_tests.py`
closes that by running the suite from a throwaway cwd, so a third guard here keeps every launcher
on it.
"""
import ast
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _git_test_env import clean_git_env  # noqa: E402

SCRIPTS = Path(__file__).resolve().parent
SELF = Path(__file__).name
HOOK = SCRIPTS.parent / ".githooks" / "pre-push"
WORKFLOWS = SCRIPTS.parent / ".github" / "workflows"
#: The launcher that runs the suite from a throwaway cwd and fails on anything left behind.
RUNNER = "run_script_tests.py"
#: Spellings of "discover the scripts suite yourself". Long options, `-s=scripts`, `./scripts`, and
#: the POSITIONAL start directory (`unittest discover scripts`) all count, so a launcher cannot slip
#: past by rewording the same command. Matching is per line, which a YAML folded scalar could in
#: principle split; that is the known limit of a text rule, and the runner is what actually gates.
_DISCOVER_RE = re.compile(r"unittest\s+discover\b")
_SCRIPTS_DIR_RE = re.compile(
    r"(?:(?:-s|--start-directory)[=\s]+|discover\s+(?:-[a-zA-Z]+\s+)*)[\"']?\.?[\\/]?scripts\b")
#: Running one module by path (`python scripts/test_build_site_data.py`) skips the runner just as
#: completely as discovering the whole suite does, so it is the same offence.
_DIRECT_MODULE_RE = re.compile(
    r"\bpython[0-9.]*\b.*?[\s\"'=]\.?[\\/]?scripts[\\/]test_[\w*?.-]+\.py")

# The subprocess entry points a test can use to spawn a command.
_SPAWNERS = {"run", "Popen", "check_output", "check_call", "call"}


def _argv_literal(node):
    """The literal head of an argv expression, unwrapping `["git", ...] + more`."""
    while isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        node = node.left
    return node if isinstance(node, (ast.List, ast.Tuple)) else None


def _git_argv_names(tree):
    """Names bound to an argv literal that starts with "git" (`cmd = ["git", ...]`), so a spawn
    that passes the variable rather than the literal is still recognized."""
    names = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        argv = _argv_literal(node.value)
        if argv is None or not argv.elts:
            continue
        first = argv.elts[0]
        if not (isinstance(first, ast.Constant) and first.value == "git"):
            continue
        for target in node.targets:
            names.add(ast.unparse(target))
    return names


def _scrubbed_env_expressions(tree):
    """Source of every expression that holds a `clean_git_env(...)` result, so `env=self.env` is
    accepted only when `self.env` was actually built by the helper.

    Matching is by expression SOURCE within the module, so a module that binds `env = clean_git_env(...)`
    also whitelists a helper's `env=env` parameter. That is deliberate - the point is to reject
    `env=os.environ.copy()`, not to do full dataflow - and the hook-level scrub is what makes
    hermeticity independent of this rule's precision."""
    scrubbed = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if "clean_git_env" not in ast.unparse(node.value):
            continue
        for target in node.targets:
            scrubbed.add(ast.unparse(target))
    return scrubbed


def _spawns_git(tree, argv_names=None):
    """Every subprocess call in `tree` that spawns git.

    A bare `git --version` probe is exempt: it reads no repository, so an inherited GIT_DIR cannot
    make it act on one."""
    argv_names = argv_names if argv_names is not None else _git_argv_names(tree)
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        # `subprocess.run(...)` / `sp.run(...)`, and the bare `run(...)` of
        # `from subprocess import run`. Matching the NAME rather than resolving the import keeps
        # this loud: a false positive is a visible failure a test author fixes by scrubbing, while a
        # false negative would be silent - the failure mode this whole module exists to prevent.
        if isinstance(node.func, ast.Attribute):
            name = node.func.attr
        elif isinstance(node.func, ast.Name):
            name = node.func.id
        else:
            continue
        if name not in _SPAWNERS:
            continue
        # `subprocess.run(["git", ...])` and the keyword form `subprocess.run(args=["git", ...])`.
        argv_node = node.args[0] if node.args else None
        if argv_node is None:
            for kw in node.keywords:
                if kw.arg == "args":
                    argv_node = kw.value
                    break
        if argv_node is None:
            continue
        argv = _argv_literal(argv_node)
        if argv is None:
            head = argv_node
            while isinstance(head, ast.BinOp) and isinstance(head.op, ast.Add):
                head = head.left
            if ast.unparse(head) in argv_names:
                found.append(node)
            continue
        if not argv.elts:
            continue
        first = argv.elts[0]
        if not (isinstance(first, ast.Constant) and first.value == "git"):
            continue
        rest = [e.value for e in argv.elts[1:] if isinstance(e, ast.Constant)]
        if rest == ["--version"]:
            continue
        found.append(node)
    return found


def _test_modules():
    return sorted(p for p in SCRIPTS.glob("test_*.py") if p.name != SELF)


#: The repository's own scratch directories - the gitignored ones a fixture is tempted to use. They
#: are IGNORED, which is exactly what makes a fixture there invisible: an absolute path defeats the
#: sandbox cwd, and `git ls-files --others --exclude-standard` drops ignored files from the
#: untracked digest, so neither leak guard sees it. Under `--jobs` two workers then race on the same
#: fixed directory (issue #832 - `test_check_spec_test_refs.py` deleted a tree another worker was
#: still using). Deliberately just the SCRATCH roots: other ignored directories (`node_modules`,
#: `test-results`) are names a legitimate temp fixture builds too, so listing them would cost more
#: false positives than the hazard is worth.
_REPO_SCRATCH_DIRS = ("tmp", ".plans", ".worktrees", "plugins/tmp")
#: What "this path starts at the repository" looks like in a test module.
_REPO_ROOT_MARKERS = ("__file__", "REPO_ROOT", "REPO", "SCRIPTS", "ROOT", "root", "repo_root")
#: ...and what says a name is a TEMP root despite its spelling. `self.root = mkdtemp()` is a common
#: idiom, and `root / "tmp" / x` under it is perfectly hermetic.
_TEMP_MARKERS = ("tempfile", "mkdtemp", "TemporaryDirectory", "gettempdir", "mkstemp")


def _referenced_names(node):
    """Every identifier the expression mentions: bare names and the tail of an attribute."""
    names = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            names.add(child.id)
        elif isinstance(child, ast.Attribute):
            names.add(child.attr)
            names.add(ast.unparse(child))
    return names


def _bindings(tree):
    """(value, targets) for every binding shape a root is written with: plain assignment, an
    annotated one (`root: Path = ...`), and the walrus."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            yield node.value, node.targets
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            yield node.value, [node.target]
        elif isinstance(node, ast.NamedExpr):
            yield node.value, [node.target]


def _temp_names(tree):
    """Names ever bound to a temporary directory, whatever they are called.

    Both bindings count: `d = tempfile.mkdtemp()` and `with TemporaryDirectory() as d:`.
    """
    names = set()

    def bind(target):
        names.add(ast.unparse(target))
        if isinstance(target, ast.Attribute):
            names.add(target.attr)
        elif isinstance(target, ast.Name):
            names.add(target.id)

    for value, targets in _bindings(tree):
        if _referenced_names(value) & set(_TEMP_MARKERS):
            for target in targets:
                bind(target)
    for node in ast.walk(tree):
        if isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if item.optional_vars is None:
                    continue
                if _referenced_names(item.context_expr) & set(_TEMP_MARKERS):
                    bind(item.optional_vars)
    # A name derived from a temp name is temporary too (`root = Path(d)`).
    changed = True
    while changed:
        changed = False
        for value, targets in _bindings(tree):
            if not (_referenced_names(value) & names):
                continue
            for target in targets:
                before = len(names)
                bind(target)
                changed = changed or len(names) != before
    return names


def _is_repo_expr(node, bound, temps=()):
    """True when this expression starts at the repository (directly or via a bound name).

    Matching is on NAME NODES, never on the unparsed source, so a string literal that happens to
    contain the word ROOT cannot taint an unrelated variable, and a name the module ever binds to a
    temporary directory is never treated as the repository.
    """
    referenced = _referenced_names(node)
    if referenced & set(temps):
        return False
    if "__file__" in referenced:
        return True
    return bool(referenced & (set(_REPO_ROOT_MARKERS) | bound))


def _repo_root_names(tree, temps=()):
    """Names bound to a repository-derived path (`root = Path(__file__).resolve().parent`), so a
    fixture built off the variable rather than the literal expression is still recognized."""
    names = set()
    changed = True
    while changed:
        changed = False
        for value, targets in _bindings(tree):
            if not _is_repo_expr(value, names, temps):
                continue
            for target in targets:
                name = ast.unparse(target)
                if name not in names and name not in temps:
                    names.add(name)
                    changed = True
    return names


def _path_segments(node):
    """The literal segments to the RIGHT of the base, in order.

    Only the FIRST of them decides: `root / "tmp" / "x"` is the repository's scratch directory,
    while `root / "site" / "tmp"` is an ordinary tracked path that happens to be called tmp.
    """
    if isinstance(node, ast.Call):
        args = node.args[1:] if len(node.args) > 1 else []
        if isinstance(node.func, ast.Attribute) and node.func.attr == "joinpath":
            args = node.args
        return [a.value if isinstance(a, ast.Constant) else None for a in args]
    segments = []
    while isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        right = node.right
        segments.append(right.value if isinstance(right, ast.Constant) else None)
        node = node.left
    return list(reversed(segments))


def _path_base(node):
    """The leftmost operand of a `a / b / c` chain, or the receiver/first argument of a call."""
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Attribute) and node.func.attr == "joinpath":
            return node.func.value
        return node.args[0] if node.args else None
    while isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        node = node.left
    return node


def _is_path_expr(node):
    """True for the shapes a fixture path is built with: `a / b`, `os.path.join(a, b)`,
    `Path(a, b)`, and `a.joinpath(b)`."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return True
    if not isinstance(node, ast.Call):
        return False
    if isinstance(node.func, ast.Attribute):
        return node.func.attr in ("join", "joinpath")
    return isinstance(node.func, ast.Name) and node.func.id == "Path" and len(node.args) > 1


def repo_scratch_paths(source, filename="<test>"):
    """Descriptions of every fixed path this module builds under a repo scratch directory.

    Matches the shapes a fixture is written with - `<repo-ish> / "tmp" / "name"`,
    `os.path.join(<repo-ish>, "tmp", ...)`, `Path(<repo-ish>, "tmp", ...)`, and
    `<repo-ish>.joinpath("tmp", ...)`. Reading such a path is as suspect as writing one here,
    because the fixture pattern always writes; a test that genuinely needs the repository reads a
    TRACKED path, which no scratch directory is.
    """
    tree = ast.parse(source, filename=filename)
    temps = _temp_names(tree)
    names = _repo_root_names(tree, temps)
    candidates = [node for node in ast.walk(tree) if _is_path_expr(node)]
    # `a / "tmp" / "x"` CONTAINS `a / "tmp"`, so report only the outermost expression: collect the
    # immediate sub-expression of each candidate (not the chain's base, which is never a candidate).
    inner = set()
    for node in candidates:
        if isinstance(node, ast.BinOp):
            inner.add(id(node.left))
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                inner.add(id(node.func.value))
            elif node.args:
                inner.add(id(node.args[0]))
    found = []
    for node in candidates:
        if id(node) in inner:
            continue
        base = _path_base(node)
        if base is None or not _is_repo_expr(base, names, temps):
            continue
        segments = _path_segments(node)
        prefixes = {segments[0]} if segments else set()
        if len(segments) > 1 and None not in segments[:2]:
            prefixes.add("/".join(segments[:2]))
        if prefixes & set(_REPO_SCRATCH_DIRS):
            found.append("%s:%d %s" % (filename, node.lineno, ast.unparse(node)))
    return found


class TestsMustNotBuildFixturesInsideTheRepository(unittest.TestCase):
    """A fixture path built from the repository root is invisible to BOTH leak guards.

    The sandbox cwd only catches a RELATIVE write, and the worktree snapshot only hashes untracked
    files git does not ignore - so a fixture under the repo's own `tmp/` slips past both, and under
    `--jobs` it is also a shared directory two workers fight over. Fixtures belong in
    `tempfile.mkdtemp()`/`TemporaryDirectory()`."""

    def test_no_scripts_test_builds_a_fixture_under_a_repo_scratch_directory(self):
        offenders = []
        for path in _test_modules():
            offenders += repo_scratch_paths(path.read_text(encoding="utf-8"), path.name)
        self.assertEqual(
            offenders, [],
            "these fixture paths live inside the repository's gitignored scratch directories, "
            "where neither leak guard can see them and parallel workers race each other - build "
            "them with tempfile.mkdtemp()/TemporaryDirectory() instead: %r" % (offenders,))

    def test_the_rule_catches_the_pattern_it_exists_for(self):
        # The exact shape that raced under --jobs (scripts/test_check_spec_test_refs.py, pre-fix),
        # plus the other spellings of the same thing.
        for source in (
            'from pathlib import Path\n'
            'root = Path(__file__).resolve().parent.parent\n'
            'sandbox = root / "tmp" / "test_check_spec_test_refs"\n',
            'import os\n'
            'sandbox = os.path.join(REPO_ROOT, "tmp", "fixtures")\n',
            'self.sandbox = self.root / "tmp" / "x"\n',
            'sandbox = Path(REPO_ROOT, "tmp", "fixtures")\n',
            'sandbox = REPO_ROOT.joinpath("tmp", "fixtures")\n',
            'sandbox = SCRIPTS.parent / ".plans" / "scratch"\n',
            # An annotated binding and a walrus bind a root just as well as a plain assignment.
            'from pathlib import Path\n'
            'root: Path = Path(__file__).resolve().parent.parent\n'
            'sandbox = root / "tmp" / "case"\n',
            'from pathlib import Path\n'
            'if (root := Path(__file__).resolve().parent) is not None:\n'
            '    sandbox = root / "tmp" / "case"\n',
            # A nested scratch tree is the same hole one level down.
            'sandbox = REPO_ROOT / "plugins" / "tmp" / "case"\n',
        ):
            self.assertTrue(repo_scratch_paths(source),
                            "the rule missed a repo-scratch fixture path: %r" % source)

    def test_a_nested_path_is_reported_once(self):
        source = ('from pathlib import Path\n'
                  'root = Path(__file__).resolve().parent.parent\n'
                  'sandbox = root / "tmp" / "case" / "deep"\n')
        self.assertEqual(len(repo_scratch_paths(source)), 1)

    def test_the_rule_leaves_legitimate_paths_alone(self):
        for source in (
            'import tempfile\nsandbox = tempfile.mkdtemp(prefix="x-")\n',
            'spec = self.root / "site" / "tests" / "SPEC.md"\n',
            'out = Path(tmp) / "tmp" / "nested"\n',
            # A tracked directory that merely happens to be called tmp is not the repo's scratch.
            'fixture = REPO_ROOT / "site" / "tmp" / "keep.md"\n',
            # `root` naming a TEMP root is a common idiom; the binding wins over the spelling.
            'import tempfile\nfrom pathlib import Path\n'
            'self.root = Path(tempfile.mkdtemp())\nfixture = self.root / "tmp" / "case"\n',
            'import os, tempfile\nd = tempfile.mkdtemp()\n'
            'os.makedirs(os.path.join(d, "tmp", "node_modules"))\n',
        ):
            self.assertEqual(repo_scratch_paths(source), [],
                             "the rule flagged a legitimate path: %r" % source)


class StaticGitEnvRule(unittest.TestCase):
    """Any scripts test that spawns git must scrub the inherited git environment."""

    def test_every_git_spawning_call_passes_a_scrubbed_env(self):
        offenders = []
        for path in _test_modules():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            scrubbed = _scrubbed_env_expressions(tree)
            for call in _spawns_git(tree):
                env = next((kw.value for kw in call.keywords if kw.arg == "env"), None)
                if env is None:
                    offenders.append("%s:%d (no env=)" % (path.name, call.lineno))
                    continue
                source = ast.unparse(env)
                # `env=os.environ.copy()` satisfies "an env was passed" while still carrying the
                # inherited GIT_DIR, so require the value to come from the helper.
                if "clean_git_env" not in source and source not in scrubbed:
                    offenders.append("%s:%d (env=%s)" % (path.name, call.lineno, source))
        self.assertEqual(
            offenders, [],
            "these git spawns do not scrub the ambient git environment (GIT_DIR and friends), so "
            "under a git hook they target the REAL repo instead of their temp one - pass "
            "env=clean_git_env(): %r" % (offenders,))


class HookScrubsTheGitEnvironment(unittest.TestCase):
    """The suite-level net: the pre-push hook runs the test suites with the variables removed.

    A per-test rule cannot see a test that shells out to a wrapper which spawns git in turn, so the
    hook is what makes hermeticity independent of any individual test."""

    #: What a line has to mention to count as "this launches a test suite".
    SUITE_TOKENS = ("unittest discover", "-m unittest", "pytest", "run_plugin_python_tests.py",
                    RUNNER)

    def _hook_source(self):
        if not HOOK.exists():
            self.skipTest("pre-push hook not present")
        # Collapse shell line continuations first: the plugin-suite invocation is split across two
        # lines, so a line-oriented scan would see `run "plugin Python tests ..." \` (no suite token)
        # and `"$PY" scripts/run_plugin_python_tests.py ...` (does not start with `run `), and match
        # neither - a silent false pass for that branch.
        return re.sub(r"\\\r?\n\s*", " ", HOOK.read_text(encoding="utf-8"))

    def test_no_test_suite_is_launched_without_scrubbing(self):
        source = self._hook_source()
        self.assertIn("run_hermetic", source, "the pre-push hook defines no scrubbing wrapper")
        # A denylist, not an allowlist: a suite added later is caught even though this test has
        # never heard of it.
        offenders = [line.strip() for line in source.splitlines()
                     if line.strip().startswith("run ")
                     and any(token in line for token in self.SUITE_TOKENS)]
        self.assertEqual(
            offenders, [],
            "these pre-push lines launch a test suite without scrubbing the inherited git "
            "environment - use run_hermetic: %r" % (offenders,))

    def test_both_known_suites_are_still_launched_hermetically(self):
        # The denylist above cannot tell "protected" from "absent", so pin that the two suites this
        # hook is supposed to run are actually there, and hermetic.
        source = self._hook_source()
        for suite in (RUNNER, "run_plugin_python_tests.py"):
            launched = [line.strip() for line in source.splitlines()
                        if suite in line and line.strip().startswith("run_hermetic ")]
            self.assertTrue(launched,
                            "the pre-push hook no longer launches %r through run_hermetic" % (suite,))

    def test_the_hook_unsets_every_variable_the_helper_scrubs(self):
        source = self._hook_source()
        import _git_test_env
        # Read the tokens off the `unset` command itself: a variable named only in a comment must
        # not satisfy this.
        unset_tokens = set()
        for match in re.finditer(r"^\s*unset\s+(.+)$", source, re.MULTILINE):
            unset_tokens.update(match.group(1).split())
        missing = [v for v in _git_test_env._GIT_LOCATION_VARS if v not in unset_tokens]
        self.assertEqual(
            missing, [],
            "the pre-push hook's unset list has drifted from _git_test_env._GIT_LOCATION_VARS: %r"
            % (missing,))


class EverySuiteLaunchGoesThroughTheLeakGuard(unittest.TestCase):
    """Nothing may launch the scripts suite except `run_script_tests.py`.

    Scrubbing the git environment closes one leak vector; it does nothing about the other one
    (#791): a test that writes a bare relative filename lands it in whatever directory the suite
    was launched from, which for `pre-push` and CI is the repository root. `run_script_tests.py`
    runs the suite from a throwaway cwd and fails on anything left behind, so it only protects the
    launches that actually use it - hence this rule. It matches the command by SHAPE (long options,
    a `./scripts` start directory, and a `--pattern` glob all count), so a launcher added later
    cannot slip past by rewording."""

    def _launchers(self, source):
        """Lines of `source` that run tests under `scripts/` outside the runner.

        Both spellings count: discovering the suite, and running ONE module by path. A targeted run
        leaks exactly the same way the whole suite does, and the runner takes `--pattern` for that
        case, so reverting a step to a direct run is caught however narrow it is."""
        found = []
        # Drop shell comments so the RATIONALE for this rule cannot trip the rule.
        source = re.sub(r"(?m)^\s*#.*$", "", source)
        for line in re.sub(r"\\\r?\n\s*", " ", source).splitlines():
            stripped = line.strip()
            discovers = _DISCOVER_RE.search(stripped) and _SCRIPTS_DIR_RE.search(stripped)
            if discovers or _DIRECT_MODULE_RE.search(stripped):
                found.append(stripped)
        return found

    def _workflows(self):
        return sorted(p for pat in ("*.yml", "*.yaml") for p in WORKFLOWS.glob(pat))

    def test_the_pre_push_hook_launches_the_suite_through_the_runner(self):
        if not HOOK.exists():
            self.skipTest("pre-push hook not present")
        source = HOOK.read_text(encoding="utf-8")
        self.assertIn(RUNNER, source,
                      "the pre-push hook no longer runs the scripts suite through %s, so a test "
                      "that writes a scratch file into the cwd would dirty the repo root again"
                      % RUNNER)
        self.assertEqual(
            self._launchers(source), [],
            "these pre-push lines discover the scripts suite directly instead of running it "
            "through %s: %r" % (RUNNER, self._launchers(source)))

    def test_no_workflow_launches_the_suite_directly(self):
        if not WORKFLOWS.is_dir():
            self.skipTest("no workflows directory")
        offenders = []
        for path in self._workflows():
            offenders += ["%s: %s" % (path.name, line)
                          for line in self._launchers(path.read_text(encoding="utf-8"))]
        self.assertEqual(
            offenders, [],
            "these CI steps discover the scripts suite directly, so a test that leaks a file into "
            "the cwd goes unnoticed - run it through scripts/%s: %r" % (RUNNER, offenders))

    def test_no_workflow_disables_the_repository_check(self):
        # `--no-worktree-check` exists for a local run on a tree the author is still editing.
        # In CI nothing else touches the tree, so passing it there would only blind the one check
        # that catches a test writing an ABSOLUTE path into the repository. `--sandbox` is the
        # same class of hole: it points a shard at a directory the caller owns, and only the
        # runner's own fan-out ever inspects one.
        if not WORKFLOWS.is_dir():
            self.skipTest("no workflows directory")
        offenders = []
        for path in self._workflows():
            offenders += ["%s: %s" % (path.name, line.strip())
                          for line in path.read_text(encoding="utf-8").splitlines()
                          if RUNNER in line
                          and ("--no-worktree-check" in line or "--sandbox" in line)]
        self.assertEqual(offenders, [],
                         "these CI steps disable the runner's leak checks: %r" % (offenders,))

    def test_every_job_that_runs_the_suite_still_runs_it(self):
        # The denylist cannot tell "guarded" from "deleted", so pin that both `validate.yml` jobs
        # (`validate` and `cross-platform`) still run the suite - through the runner.
        validate = WORKFLOWS / "validate.yml"
        if not validate.exists():
            self.skipTest("validate workflow not present")
        source = validate.read_text(encoding="utf-8")
        self.assertGreaterEqual(
            source.count(RUNNER), 2,
            "validate.yml should run the scripts suite through scripts/%s in both the `validate` "
            "and `cross-platform` jobs" % RUNNER)

    def test_the_rule_catches_a_reworded_launcher(self):
        # The rule is only worth having if it survives an equivalent spelling, so pin the ones a
        # future edit is most likely to reach for - including the narrow, single-module revert that
        # `pages.yml` used to do.
        for line in ('run: python -m unittest discover -s scripts -p "test_*.py"',
                     "run: python -m unittest discover --start-directory scripts",
                     'run: python -m unittest discover -t . -s ./scripts -p "test_check_*.py"',
                     "run: python -m unittest discover -s=scripts",
                     "run: python -m unittest discover scripts",
                     "run: python -m unittest discover -v scripts",
                     'run: python -m unittest discover -s scripts -p "test_build_site_data.py"',
                     "run: python scripts/test_build_site_data.py",
                     "run: python -X dev ./scripts/test_task.py"):
            self.assertEqual(len(self._launchers(line)), 1, "not caught: %s" % line)
        for line in ("run: python scripts/run_script_tests.py",
                     "run: python scripts/run_script_tests.py --pattern test_build_site_data.py",
                     "run: python -m unittest discover -s plugins/x/dev/tests",
                     "run: python plugins/x/dev/tests/test_thing.py",
                     "        # a comment about unittest discover -s scripts is not a launcher"):
            self.assertEqual(self._launchers(line), [], "false positive: %s" % line)


class AmbientRepoIsUntouched(unittest.TestCase):
    """Run the real-git suite under an inherited hook environment; the repo must not change."""

    #: The class that drives real git plumbing against a throwaway repository. It owns the exact
    #: fixtures (a.md, b.md, new.md, old.md) that leaked into `main`, and it runs in seconds, so it
    #: is the representative case; the hook-level scrub and the static rule cover every other
    #: module. Fully qualified so a rename cannot silently turn this into a no-op.
    MODULE = "test_check_conflict_markers.StagedEndToEndTest"
    #: The number of real-git tests that class must run, so a nested suite that collected nothing
    #: (or skipped everything) cannot pass by exiting 0 without spawning git at all.
    MIN_TESTS = 3

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        self.env = clean_git_env()
        if not self._git("init", "-q", "-b", "main"):
            self.skipTest("git init failed (git missing, or too old for -b)")
        (self.repo / "keep.md").write_text("keep\n", encoding="utf-8")
        self._git("add", "keep.md")
        self._git("commit", "-qm", "base")

    def _git(self, *args):
        proc = subprocess.run(["git", "-C", str(self.repo)] + list(args),
                              capture_output=True, text=True, env=self.env)
        return proc.returncode == 0

    def _capture(self, *args):
        return subprocess.run(["git", "-C", str(self.repo)] + list(args),
                              capture_output=True, text=True, env=self.env).stdout

    def _snapshot(self):
        # Status/HEAD alone would miss a stray branch, tag, stash, reflog entry, or a `git config`
        # write - all of which a regressed test could leave behind on the ambient repository.
        return {
            "status": self._capture("status", "--porcelain"),
            "head": self._capture("rev-parse", "HEAD").strip(),
            "log": self._capture("log", "--oneline"),
            "refs": self._capture("for-each-ref", "--format=%(refname) %(objectname)"),
            "reflog": self._capture("reflog", "--format=%H %gs"),
            "stash": self._capture("stash", "list"),
            "config": self._capture("config", "--local", "--list"),
            "files": sorted(p.name for p in self.repo.iterdir() if p.name != ".git"),
        }

    def test_the_real_git_suite_does_not_touch_an_inherited_repository(self):
        before = self._snapshot()
        # Exactly what a git hook hands its child process: the location variables of the repository
        # the hook is running for, with the work tree as the working directory.
        hooked = dict(self.env)
        hooked["GIT_DIR"] = str(self.repo / ".git")
        hooked["GIT_INDEX_FILE"] = str(self.repo / ".git" / "index")
        hooked["GIT_WORK_TREE"] = str(self.repo)
        proc = subprocess.run([sys.executable, "-m", "unittest", self.MODULE],
                              cwd=str(SCRIPTS), env=hooked, capture_output=True, text=True)
        after = self._snapshot()
        self.assertEqual(after, before,
                         "%s changed the inherited repository: %r -> %r" % (self.MODULE, before, after))
        self.assertEqual(proc.returncode, 0,
                         "%s must pass with git location variables inherited (it reads the ambient "
                         "repo instead of its own fixtures when it does not scrub them):\n%s"
                         % (self.MODULE, proc.stderr[-3000:]))
        ran = re.search(r"^Ran (\d+) tests?", proc.stderr, re.MULTILINE)
        self.assertIsNotNone(ran, "could not read the nested test count from:\n%s" % proc.stderr[-2000:])
        self.assertGreaterEqual(
            int(ran.group(1)), self.MIN_TESTS,
            "%s ran %s tests; a nested suite that collects nothing would pass this guard without "
            "ever spawning git" % (self.MODULE, ran.group(1)))
        skipped = re.search(r"\bskipped=([1-9]\d*)", proc.stderr)
        self.assertIsNone(skipped,
                          "the nested real-git tests were skipped, so nothing was actually "
                          "exercised:\n%s" % proc.stderr[-2000:])


if __name__ == "__main__":
    unittest.main()
