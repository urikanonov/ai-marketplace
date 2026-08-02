#!/usr/bin/env python3
"""Verify spec rows point at real tests and exact test names.

Three directions are checked:

- FORWARD (`check_spec`): every test file and exact test name a spec row cites exists.
- REVERSE (`check_test_id_mappings`): every test that CARRIES a feature id is owned by that id's
  spec row. For a target listed in `FULLY_REVERSE_MAPPED_SPECS` this covers its WHOLE test
  corpus; for the rest it covers only what `_is_reverse_mapped` accepts - the `*.test.*` suites
  and the `*regressions*.spec.*` files. A target graduates to the full corpus once every feature
  id its tests carry is owned and cited by its spec, which is a spec cleanup rather than a code
  change: the site target is there today, commentable-html is not (a few dozen of its test titles
  have no owning row, or a row that does not cite them, and several would need brand-new feature
  ids, which also demands a doc-surface registry entry). Issue #853 tracks that cleanup and
  carries the measured breakdown. Until it lands, a commentable-html `*.spec.*` file is covered by
  the forward direction and by the cross-file duplicate check below, but not by the reverse
  mapping.
- DUPLICATE (`check_duplicate_feature_ids`): a feature id carried by test titles in MORE THAN ONE
  file must have every one of those titles cited by a spec row that owns the id, so a new test
  cannot quietly borrow an id another file already owns. It reads the WHOLE test corpus, not just
  the reverse-mapped part. Three rules bound it:
  - While an id lives in ONE file, extra titles there need no citation: a single behavior
    asserted from several angles in its own spec file is the repo's existing convention (114
    instances). The moment the id also appears in another file, traceability matters more than
    that convenience, so EVERY carrier of it - including the same-file ones - must be cited.
  - An id whose AREA (the segment before the first `-`) no spec row anywhere owns is skipped. An
    `HTTP-404` in a title matches the feature-id shape, and must not red CI on its own. A NEW id
    in a known area - `CMH-DECK-99`, say - is still checked even before it has a row, because
    that is exactly the borrow this gate exists to catch and most of the `*.spec.*` corpus is not
    reverse-mapped yet.
  - A `describe(...)` wrapper counts toward "how many files carry this id", since hiding a borrow
    in a suite title is the obvious evasion, but only a `test(...)`/`it(...)` title is REPORTED -
    a suite title cannot be cited by a row (issue #629), so demanding it be cited would be a
    demand no author could satisfy.

Only `test(...)` / `it(...)` titles are read by the REVERSE direction. A `describe(...)` suite
title groups tests rather than being one, and the forward direction refuses a suite title as
coverage (issue #629), so a row could not cite one even if asked to.
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import functools
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC_TARGETS = (
    (REPO_ROOT / "plugins" / "commentable-html" / "dev" / "SPEC.md",
     REPO_ROOT / "plugins" / "commentable-html" / "dev"),
    (REPO_ROOT / "site" / "tests" / "SPEC.md", REPO_ROOT),
    (REPO_ROOT / ".github" / "skills" / "demo-video" / "SPEC.md",
     REPO_ROOT / ".github" / "skills" / "demo-video"),
)
# Specs whose ENTIRE test corpus is reverse-mapped, not just the `*.test.*` / regressions subset.
# A spec joins this set once every feature id its tests carry is owned and cited by it; see the
# module docstring and issue #853.
FULLY_REVERSE_MAPPED_SPECS = frozenset({
    (REPO_ROOT / "site" / "tests" / "SPEC.md").resolve(),
    (REPO_ROOT / ".github" / "skills" / "demo-video" / "SPEC.md").resolve(),
})

# One grammar for "a JS/TS test file" everywhere. Playwright's default testMatch is
# `**/*.@(spec|test).?(c|m)[jt]s`, so the corpus the reverse and duplicate directions read must
# recognise every one of those spellings - otherwise a file CI really runs (say `foo.test.js`) is
# invisible to both gates. The CITATION grammar has to agree with it, or a legitimately cited
# `tests/x.spec.ts` row would be unciteable and the gate would red a correct spec.
_JS_TEST_SUFFIX = r"[cm]?[jt]s"
_TEST_PATH_RE = re.compile(
    r"`((?:tests|site/tests/tests)/[^`]+\.(?:py|%s)|scripts/test_[^`]+\.py)`" % _JS_TEST_SUFFIX
)
_JS_TEST_FILE_RE = re.compile(r"\.(?:spec|test)\.%s$" % _JS_TEST_SUFFIX, re.IGNORECASE)
_JS_TEST_ONLY_FILE_RE = re.compile(r"\.test\.%s$" % _JS_TEST_SUFFIX, re.IGNORECASE)
_REGRESSION_FILE_RE = re.compile(
    r"regressions[^/\\]*\.spec\.%s$" % _JS_TEST_SUFFIX, re.IGNORECASE)
_JS_SUFFIXES = frozenset({".js", ".cjs", ".mjs", ".ts", ".cts", ".mts"})
_BACKTICK_PATH_RE = re.compile(r"`([^`]+\.(?:py|%s|tsx))`" % _JS_TEST_SUFFIX)
_QUOTED_RE = re.compile(r"`([^`]+)`")
_FEATURE_ID_RE = re.compile(r"\b[A-Z][A-Z0-9]+(?:-[A-Z0-9]+)*-\d+[a-z]?\b")
_PY_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?")
_JS_TITLE_RE = re.compile(
    r'(?:test\.describe(?:\.(?:only|skip|fixme|serial|parallel))*|'
    r'(?:test|it|describe)(?:\.(?:only|skip|fixme|serial|parallel))*)\s*\(\s*'
    r'(?:"((?:\\.|[^"\\])*)"|\'((?:\\.|[^\'\\])*)\'|`((?:\\.|[^`\\])*)`)',
    re.DOTALL,
)
# Test-only titles: `test(...)` / `it(...)` (with modifiers) but NOT `describe(...)` suite names,
# so the strict "cite an exact TEST" gate is not satisfied by a suite/group title.
_JS_TEST_ONLY_RE = re.compile(
    r'(?:test|it)(?:\.(?:only|skip|fixme|serial|parallel))*\s*\(\s*'
    r'(?:"((?:\\.|[^"\\])*)"|\'((?:\\.|[^\'\\])*)\'|`((?:\\.|[^`\\])*)`)',
    re.DOTALL,
)


@dataclass(frozen=True)
class SpecIssue:
    spec: Path
    line: int
    message: str

    def format(self) -> str:
        return "%s:%d: %s" % (_display(self.spec), self.line, self.message)


def _display(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _scoped(fn):
    """Run fn inside a cache_scope, so a top-level check never re-uses another run's cache."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with cache_scope():
            return fn(*args, **kwargs)
    return wrapper


def _fingerprint(path: Path) -> tuple[int, int] | None:
    """(mtime_ns, size) for path, or None when it cannot be stat'd.

    Part of every cache key, so a file that CHANGES on disk is re-read and re-parsed automatically.
    Keying on the path alone would be faster by one stat() per lookup, but it would hand a caller a
    stale parse of a file it had just rewritten - a silent wrong answer that no caller could see.
    A stat is negligible next to the read+parse it guards.
    """
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def _read(path: Path) -> str:
    return _read_fingerprinted(path, _fingerprint(path))


@functools.lru_cache(maxsize=None)
def _read_fingerprinted(path: Path, fingerprint: tuple[int, int] | None) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")


def _python_ast(path: Path) -> ast.Module | None:
    """Parsed module for path, or None when it does not parse.

    Cached because several checks (name lookup, exact-test classification) each used to re-read and
    re-parse the same file for every spec row that referenced it - the bulk of this checker's cost.
    Callers only ever ast.walk() the result, so sharing one tree is safe.
    """
    return _python_ast_fingerprinted(path, _fingerprint(path))


@functools.lru_cache(maxsize=None)
def _python_ast_fingerprinted(path: Path, fingerprint: tuple[int, int] | None) -> ast.Module | None:
    try:
        return ast.parse(_read(path), filename=str(path))
    except SyntaxError:
        return None


def clear_caches() -> None:
    """Drop every memoized read/parse."""
    _read_fingerprinted.cache_clear()
    _python_ast_fingerprinted.cache_clear()
    _python_symbols_fingerprinted.cache_clear()
    _js_test_titles.cache_clear()


_cache_depth = 0


@contextlib.contextmanager
def cache_scope():
    """Confine the memo caches to ONE top-level check, then drop them.

    This, not the fingerprint, is what makes the caching sound. A (mtime_ns, size) key is a
    heuristic: a same-SIZE rewrite that lands in the same mtime tick (or has its mtime restored)
    is indistinguishable from no change, and for this checker a stale hit means a spec row whose
    test was renamed still PASSES - a false green on a required gate.

    Within a single check the tree is static: the pass is synchronous and reads files it never
    writes, so nothing can change under it and caching is exact. Scoping to that window keeps the
    whole speedup (the win is re-use WITHIN one pass, where a file is referenced by many rows) and
    leaves nothing cached afterwards to go stale. Nested scopes share one window, so check_all
    still re-uses reads across its specs.

    SINGLE-THREADED BY CONTRACT: `_cache_depth` is a plain counter, so two threads entering these
    entry points concurrently could strand it above zero, which would pin the caches warm for the
    rest of the process and reinstate exactly the stale-hit false pass described above. Every
    caller today is sequential (the CLI, the pre-push hook, the validate job, and the unittest
    suite); add a lock here before that changes.
    """
    global _cache_depth
    if _cache_depth == 0:
        clear_caches()
    _cache_depth += 1
    try:
        yield
    finally:
        _cache_depth -= 1
        if _cache_depth == 0:
            clear_caches()


def _row_cells(line: str) -> list[str] | None:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return None
    cells = [cell.strip() for cell in stripped.strip("|").split("|")]
    if len(cells) < 3:
        return None
    if cells[0].lower() in {"feature id", "feature"}:
        return None
    if all(set(cell) <= {"-", ":", " "} for cell in cells):
        return None
    return cells


def _python_symbols(path: Path):
    """(classes, functions, all_methods, test_classes) for a module, walked ONCE per file.

    The AST is already cached, but every name lookup used to re-walk that whole tree: 1511 lookups
    produced ~6M ast.walk steps and dominated the run once the parse itself was cached. The walk is
    a pure function of the module, so it is hoisted here and shared by both name checks.
    """
    return _python_symbols_fingerprinted(path, _fingerprint(path))


@functools.lru_cache(maxsize=None)
def _python_symbols_fingerprinted(path: Path, fingerprint: tuple[int, int] | None):
    tree = _python_ast(path)
    if tree is None:
        return None
    classes: dict[str, frozenset[str]] = {}
    functions: set[str] = set()
    all_methods: set[str] = set()
    test_classes: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            class_methods = frozenset(
                child.name
                for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            )
            classes[node.name] = class_methods
            all_methods.update(class_methods)
            if _TEST_CLASS_NAME_RE.search(node.name) or _has_testcase_base(node):
                test_classes.add(node.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.add(node.name)
    return classes, frozenset(functions), frozenset(all_methods), frozenset(test_classes)


def _python_has_name(path: Path, name: str) -> bool:
    symbols = _python_symbols(path)
    if symbols is None:
        return False
    classes, functions, all_methods, _test_classes = symbols

    if "." in name:
        class_name, method_name = name.split(".", 1)
        return method_name in classes.get(class_name, frozenset())
    return name in classes or name in functions or name in all_methods


def _file_has_name(path: Path, name: str) -> bool:
    text = _read(path)
    if _FEATURE_ID_RE.fullmatch(name.strip()):
        haystack = ("\n".join(_js_test_titles(text, _JS_TITLE_RE))
                    if path.suffix in _JS_SUFFIXES else text)
        return name in set(_FEATURE_ID_RE.findall(haystack))
    if path.suffix == ".py":
        return _python_has_name(path, name)
    if path.suffix in _JS_SUFFIXES:
        return name in _js_test_titles(text, _JS_TITLE_RE)
    return False


def _python_is_exact_test(path: Path, name: str) -> bool:
    """True when name is a test method (`test_*`, bare or `Class.method`) or a test-case CLASS in
    path. A non-test helper/function (e.g. `main`, `setUp`) or a non-test helper class does NOT
    qualify; a class counts only when it subclasses `TestCase` or is named `*Tests`/`*Case`."""
    symbols = _python_symbols(path)
    if symbols is None:
        return False
    classes, _functions, _all_methods, test_classes = symbols
    if "." in name:
        class_name, method_name = name.split(".", 1)
        return method_name.startswith("test") and method_name in classes.get(
            class_name, frozenset())
    if name in test_classes:
        return True  # a TestCase class names a group of tests
    return name.startswith("test") and any(name in methods for methods in classes.values())


_TEST_CLASS_NAME_RE = re.compile(r"(?:Tests?|Case)$")


def _has_testcase_base(node: ast.ClassDef) -> bool:
    for base in node.bases:
        label = getattr(base, "attr", None) or getattr(base, "id", None)
        if label and "TestCase" in label:
            return True
    return False


def _is_exact_test_name(path: Path, name: str) -> bool:
    """True when name is a verbatim JS TEST title (`test(...)`/`it(...)`, not a `describe(...)`
    suite) or a Python test method/test-case class in path. A bare feature id, a suite/group title,
    or a non-test helper does NOT count - the strict gate wants an exact TEST, per issue #629."""
    if _FEATURE_ID_RE.fullmatch(name.strip()):
        return False
    if path.suffix in _JS_SUFFIXES:
        return name in _js_test_titles(_read(path), _JS_TEST_ONLY_RE)
    if path.suffix == ".py":
        return _python_is_exact_test(path, name)
    return False


def _clause_cites_exact_test_name(segment: str, test_path: Path) -> bool:
    """Whether any backticked token in an automated coverage clause is an exact test title/method.
    Catches a single-token JS title (no whitespace) that the _looks_like_test_reference heuristic
    used by _referenced_names would otherwise miss."""
    for match in _QUOTED_RE.finditer(segment):
        token = match.group(1)
        if _TEST_PATH_RE.fullmatch("`%s`" % token):
            continue
        if _is_exact_test_name(test_path, token):
            return True
    return False


@functools.lru_cache(maxsize=None)
def _js_test_titles(text: str, pattern: re.Pattern) -> frozenset[str]:
    """Test titles declared in a JS/MJS source.

    Cached on the source text (which `_read` returns as one shared, hash-cached string per file),
    because this hand-rolled scanner walks the file character by character and used to run once per
    spec row that referenced the file. Returns a frozenset so a cached result cannot be mutated by
    a caller; `in`, `sorted()`, and `join()` all behave as before.

    `pattern` is REQUIRED rather than defaulted: lru_cache keys on the arguments as PASSED, so a
    defaulted call and an explicit one that resolve to the same pattern would occupy two entries
    and scan the same file twice.
    """
    titles: set[str] = set()
    i = 0
    quote = ""
    line_start = True
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if quote:
            if ch == "\\" and i + 1 < len(text):
                i += 2
                continue
            if ch == quote:
                quote = ""
            if ch in "\r\n":
                line_start = True
            i += 1
            continue
        if ch in "\r\n":
            line_start = True
            i += 1
            continue
        if ch in " \t" and line_start:
            i += 1
            continue
        if ch in "'\"`":
            quote = ch
            line_start = False
            i += 1
            continue
        if ch == "/" and nxt == "/":
            while i < len(text) and text[i] not in "\r\n":
                i += 1
            continue
        if ch == "/" and nxt == "*":
            i += 2
            while i < len(text) - 1 and not (text[i] == "*" and text[i + 1] == "/"):
                if text[i] in "\r\n":
                    line_start = True
                i += 1
            i = i + 2 if i < len(text) - 1 else i
            continue
        if ch == "/" and _starts_regex_literal(list(text[:i])):
            i = _skip_regex_literal(text, i)
            line_start = False
            continue
        if line_start:
            match = pattern.match(text, i)
            if match:
                raw = next(group for group in match.groups() if group is not None)
                titles.add(_decode_js_string(raw))
                i = match.end()
                line_start = False
                continue
        line_start = False
        i += 1
    return frozenset(titles)


def _skip_regex_literal(text: str, pos: int) -> int:
    i = pos + 1
    in_class = False
    while i < len(text):
        current = text[i]
        if current == "\\" and i + 1 < len(text):
            i += 2
            continue
        if current == "[":
            in_class = True
        elif current == "]":
            in_class = False
        elif current == "/" and not in_class:
            i += 1
            while i < len(text) and text[i].isalpha():
                i += 1
            return i
        i += 1
    return i


def _starts_regex_literal(out: list[str]) -> bool:
    pos = len(out) - 1
    while pos >= 0 and out[pos].isspace():
        pos -= 1
    if pos < 0:
        return True
    last = pos
    word_end = pos + 1
    while pos >= 0 and (out[pos].isalnum() or out[pos] in "_$"):
        pos -= 1
    if out[pos + 1:word_end] and "".join(out[pos + 1:word_end]) in {
        "case",
        "delete",
        "in",
        "new",
        "of",
        "return",
        "throw",
        "typeof",
        "void",
        "yield",
    }:
        return True
    return out[last] in "([{:;,=!?&|+-*~^<>%"


def _decode_js_string(raw: str) -> str:
    return (
        raw
        .replace(r"\\", "\\")
        .replace(r"\'", "'")
        .replace(r'\"', '"')
        .replace(r"\`", "`")
        .replace(r"\n", "\n")
        .replace(r"\r", "\r")
        .replace(r"\t", "\t")
    )


def _resolve_test_path(base_dir: Path, rel: str) -> Path:
    if rel.startswith(("scripts/", "site/")):
        return (REPO_ROOT / rel).resolve()
    return (base_dir / rel).resolve()


def _referenced_names(segment: str, test_path: Path) -> list[str]:
    return [
        match.group(1)
        for match in _QUOTED_RE.finditer(segment)
        if (
            not _TEST_PATH_RE.fullmatch("`%s`" % match.group(1))
            and _looks_like_test_reference(match.group(1), test_path)
        )
    ]


def _looks_like_test_reference(name: str, test_path: Path) -> bool:
    if _FEATURE_ID_RE.search(name):
        return True
    if test_path.suffix in _JS_SUFFIXES:
        return bool(re.search(r"\s", name))
    if _PY_NAME_RE.fullmatch(name):
        return (
            name.startswith("test_")
            or "." in name
            or re.search(r"[a-z][A-Z]", name) is not None
            or re.search(r"(Tests?|Case)$", name) is not None
        )
    return False


def _tests_dir(spec_path: Path, base_dir: Path) -> Path | None:
    """The tests directory a spec owns.

    `<spec dir>/tests` is tried FIRST because it is the unambiguous one: it resolves `dev/tests`,
    `.github/skills/demo-video/tests`, and `site/tests/tests` alike. Preferring `<base>/tests`
    would let a future repo-root `tests/` shadow the site target's real corpus and silently stop
    checking it. `<base>/tests` stays as the fallback for a target whose spec does not sit beside
    its tests.
    """
    for candidate in (spec_path.parent / "tests", base_dir / "tests"):
        if candidate.is_dir():
            return candidate
    return None


def _is_reverse_mapped(name: str) -> bool:
    """Whether a test file name is in the reverse-mapping corpus (see the module docstring)."""
    return bool(_JS_TEST_ONLY_FILE_RE.search(name) or _REGRESSION_FILE_RE.search(name))


def _test_corpus(spec_path: Path, base_dir: Path, reverse_only: bool = False) -> tuple[Path, ...]:
    """Every JS test file under the spec's tests dir, recursively.

    Recursive, not flat: the forward direction accepts a nested citation
    (`tests/sub/x.spec.js`), so a flat scan would let a test one directory down fall out of the
    reverse and duplicate directions while still being a valid citation - and still RUNNING in CI.
    One walk filtered by name, rather than a walk per glob, keeps the added cost negligible.
    """
    tests_dir = _tests_dir(spec_path, base_dir)
    if tests_dir is None:
        return ()
    found: list[Path] = []
    for path in tests_dir.rglob("*"):
        name = path.name
        if not _JS_TEST_FILE_RE.search(name) or not path.is_file():
            continue
        if reverse_only and not _is_reverse_mapped(name):
            continue
        found.append(path)
    return tuple(sorted(set(found), key=lambda path: path.as_posix()))


def _spec_rows(spec_path: Path) -> dict[str, list[str]]:
    rows: dict[str, list[str]] = {}
    for line in _read(spec_path).splitlines():
        cells = _row_cells(line)
        if cells and _FEATURE_ID_RE.fullmatch(cells[0]):
            rows.setdefault(cells[0], []).append(cells[-1])
    return rows


def _coverage_rel(base_dir: Path, test_path: Path) -> str:
    """The path spelling a coverage cell uses for *test_path*."""
    resolved = test_path.resolve()
    if resolved.is_relative_to(base_dir.resolve()):
        return resolved.relative_to(base_dir.resolve()).as_posix()
    if resolved.is_relative_to(REPO_ROOT):
        return resolved.relative_to(REPO_ROOT).as_posix()
    return resolved.as_posix()


def _row_cites(coverage_cells: list[str], rel: str, title: str) -> bool:
    """Whether a coverage cell names *title* in the clause belonging to *rel*.

    A cell routinely lists several files, each with its own titles
    (`` `tests/a.spec.js` - `A`; `tests/b.spec.js` - `B` ``). Asking only whether both strings
    appear SOMEWHERE in the cell would let `tests/a.spec.js` claim `B` - so a borrowed id could be
    excused by a citation that never named the borrowing test. The clause ends at the next test
    path OR at the first `;` outside a code span (`_clause_end`, the same bound the forward
    direction uses), so a trailing `source:` note cannot supply a citation either.
    """
    quoted_title = "`%s`" % title
    for coverage in coverage_cells:
        matches = list(_TEST_PATH_RE.finditer(coverage))
        for index, match in enumerate(matches):
            if match.group(1) != rel:
                continue
            next_ref = matches[index + 1].start() if index + 1 < len(matches) else len(coverage)
            end = _clause_end(coverage, match.end(), next_ref)
            if quoted_title in coverage[match.end():end]:
                return True
    return False


def _title_line(text: str, title: str) -> int:
    index = text.find(title)
    if index < 0:
        return 1
    return text[:index].count("\n") + 1


def _clause_end(text: str, start: int, default_end: int) -> int:
    in_code = False
    for pos in range(start, default_end):
        char = text[pos]
        if char == "`":
            in_code = not in_code
        elif char == ";" and not in_code:
            return pos
    return default_end


@_scoped
def check_spec(spec_path: Path, base_dir: Path) -> list[SpecIssue]:
    issues: list[SpecIssue] = []
    text = _read(spec_path)
    for line_no, line in enumerate(text.splitlines(), 1):
        cells = _row_cells(line)
        if cells is None:
            continue
        coverage = cells[-1]
        supported_spans = []
        matches = list(_TEST_PATH_RE.finditer(coverage))
        for match in matches:
            supported_spans.append(match.span())
        for testish in _BACKTICK_PATH_RE.finditer(coverage):
            rel = testish.group(1)
            after_ref = coverage[testish.end():]
            if (
                "test" in rel.lower()
                and re.match(r"\s+-\s+", after_ref)
                and not any(
                    start <= testish.start() and testish.end() <= end
                    for start, end in supported_spans
                )
            ):
                issues.append(SpecIssue(
                    spec_path,
                    line_no,
                    "unsupported test file reference `%s`" % rel,
                ))
        for idx, match in enumerate(matches):
            rel = match.group(1)
            test_path = _resolve_test_path(base_dir, rel)
            if not test_path.is_file():
                issues.append(SpecIssue(spec_path, line_no, "missing test file `%s`" % rel))
                continue
            after_ref = coverage[match.end():]
            if not re.match(r"\s+-\s+", after_ref):
                continue
            next_ref = matches[idx + 1].start() if idx + 1 < len(matches) else len(coverage)
            end = _clause_end(coverage, match.end(), next_ref)
            names = _referenced_names(coverage[match.end():end], test_path)
            segment = coverage[match.end():end]
            missing = [name for name in names if not _file_has_name(test_path, name)]
            # Strict rule (issue #629): an automated test-file clause must cite at least one EXACT
            # test - a JS test/it title or a Python test method/test-case class. A bare feature id,
            # a describe suite title, a non-test helper, or pure prose does not satisfy it. Only flag
            # this when every cited name resolves, so a mistyped name still surfaces as "not found"
            # (its own, more specific error) rather than a redundant "no exact test name cited".
            if not missing and not _clause_cites_exact_test_name(segment, test_path):
                issues.append(SpecIssue(
                    spec_path,
                    line_no,
                    "no exact test name cited for `%s` (name at least one exact test title or "
                    "Python test method)" % rel,
                ))
            for name in missing:
                issues.append(SpecIssue(
                    spec_path,
                    line_no,
                    "`%s` not found in `%s`" % (name, rel),
                ))
    return issues


@_scoped
def check_test_id_mappings(
    spec_path: Path,
    base_dir: Path,
    test_paths: tuple[Path, ...],
) -> list[SpecIssue]:
    rows = _spec_rows(spec_path)

    issues: list[SpecIssue] = []
    for test_path in test_paths:
        text = _read(test_path)
        rel = _coverage_rel(base_dir, test_path)
        for title in sorted(_js_test_titles(text, _JS_TEST_ONLY_RE)):
            line_no = _title_line(text, title)
            for feature_id in sorted(set(_FEATURE_ID_RE.findall(title))):
                matching_rows = rows.get(feature_id)
                if not matching_rows:
                    issues.append(SpecIssue(
                        test_path,
                        line_no,
                        "feature id `%s` has no spec row" % feature_id,
                    ))
                    continue
                if not _row_cites(matching_rows, rel, title):
                    issues.append(SpecIssue(
                        test_path,
                        line_no,
                        "test title `%s` is not cited by its `%s` spec row"
                        % (title, feature_id),
                    ))
    return issues


@_scoped
def check_duplicate_feature_ids(
    targets: tuple[tuple[Path, Path], ...] = SPEC_TARGETS,
) -> list[SpecIssue]:
    """Fail when one feature id is carried by test titles in more than one FILE and no spec row
    that owns the id cites every one of them (see the module docstring for the two bounding
    rules)."""
    rows_by_spec: dict[Path, dict[str, list[str]]] = {}
    for spec_path, _base_dir in targets:
        rows_by_spec[spec_path] = _spec_rows(spec_path)
    known_areas = {
        feature_id.split("-", 1)[0]
        for rows in rows_by_spec.values()
        for feature_id in rows
    }

    uses: dict[str, list[tuple[Path, str, int, bool]]] = {}
    for spec_path, base_dir in targets:
        for test_path in _test_corpus(spec_path, base_dir):
            text = _read(test_path)
            test_only = _js_test_titles(text, _JS_TEST_ONLY_RE)
            for title in sorted(_js_test_titles(text, _JS_TITLE_RE)):
                line_no = _title_line(text, title)
                for feature_id in sorted(set(_FEATURE_ID_RE.findall(title))):
                    uses.setdefault(feature_id, []).append(
                        (test_path, title, line_no, title in test_only))

    issues: list[SpecIssue] = []
    for feature_id, entries in sorted(uses.items()):
        # Identity is the RESOLVED path: two targets can each hold a `tests/x.spec.js`, and
        # collapsing them by their spec-relative spelling would hide a genuine cross-file reuse.
        if len({test_path.resolve() for test_path, *_rest in entries}) < 2:
            continue
        if feature_id.split("-", 1)[0] not in known_areas:
            # Not a feature id at all: an `HTTP-404` in a title matches the same shape, and no
            # spec anywhere owns that area, so it must not red CI on its own.
            continue
        owners = [
            (spec_path, base_dir)
            for spec_path, base_dir in targets
            if feature_id in rows_by_spec[spec_path]
        ]
        for test_path, title, line_no, is_test_title in entries:
            # A `describe(...)` wrapper still makes an id span files (that is how a borrow hides),
            # but only a real test can be CITED, so only a real test is reported.
            if not is_test_title:
                continue
            if any(
                _row_cites(
                    rows_by_spec[spec_path].get(feature_id, []),
                    _coverage_rel(base_dir, test_path),
                    title,
                )
                for spec_path, base_dir in owners
            ):
                continue
            issues.append(SpecIssue(
                test_path,
                line_no,
                "feature id `%s` is also used by test `%s` in another file, and its `%s` spec "
                "row does not cite this test (one feature id, one behavior)"
                % (feature_id, title, feature_id),
            ))
    return issues


@_scoped
def check_all(
    targets: tuple[tuple[Path, Path], ...] = SPEC_TARGETS,
    fully_reverse_mapped: frozenset[Path] = FULLY_REVERSE_MAPPED_SPECS,
) -> list[SpecIssue]:
    issues: list[SpecIssue] = []
    for spec_path, base_dir in targets:
        issues.extend(check_spec(spec_path, base_dir))
        reverse_only = spec_path.resolve() not in fully_reverse_mapped
        reverse_mapped = _test_corpus(spec_path, base_dir, reverse_only=reverse_only)
        if reverse_mapped:
            issues.extend(check_test_id_mappings(spec_path, base_dir, reverse_mapped))
    issues.extend(check_duplicate_feature_ids(targets))
    return issues


def _parse_target(raw: str) -> tuple[Path, Path]:
    if "=" not in raw:
        raise argparse.ArgumentTypeError("target must be SPEC=BASE")
    spec, base = raw.split("=", 1)
    return (Path(spec).resolve(), Path(base).resolve())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        action="append",
        type=_parse_target,
        help="Spec/base pair to check, formatted SPEC=BASE. May be repeated.",
    )
    args = parser.parse_args(argv)

    targets = tuple(args.target) if args.target else SPEC_TARGETS
    issues = check_all(targets)
    if issues:
        print("Spec test reference check FAILED:", file=sys.stderr)
        for issue in issues:
            print("  - " + issue.format(), file=sys.stderr)
        return 1
    print("Spec test reference check OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
