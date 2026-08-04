#!/usr/bin/env python3
"""Verify spec rows point at real tests and exact test names.

Four directions are checked:

- FORWARD (`check_spec`): every test file and exact test name a spec row cites exists.
- REVERSE (`check_test_id_mappings`): every test that CARRIES a feature id is owned by that id's
  spec row. It runs in two halves. OWNERSHIP - the id has a row at all - covers the WHOLE JS test
  corpus of EVERY target. CITATION - that row names this exact title - covers the whole corpus for
  a target listed in `FULLY_REVERSE_MAPPED_SPECS`, and for the rest only what `_is_reverse_mapped`
  accepts: the `*.test.*` suites and the `*regressions*.spec.*` files. So a target waiting to
  graduate is never a hiding place for an unowned id; it is only excused from citations.
  A target graduates once every feature id its tests carry is owned and cited by its spec, which
  is a spec cleanup rather than a code change. EVERY shipped target is there now: the site and
  demo-video targets graduated in #800, and commentable-html followed in #853. That cleanup was 32
  violations: 23 uses of 14 VESTIGIAL labels (a test title carried an id no row owned while an
  existing row already described that behavior AND cited that very test, so the titles were
  normalized onto the owning id rather than minting parallel ids), plus 9 titles whose id DID have
  a row that simply did not cite them, which gained the citation. The set stays as the mechanism,
  not as a standing exemption: a NEW target that must start restricted is registered in
  `INTENTIONALLY_RESTRICTED_SPECS`, a reviewed one-line edit rather than a silent omission.
  A `describe(...)` suite title gets the OWNERSHIP half only; a row cannot CITE a suite title
  (issue #629), so demanding a citation for one would be unsatisfiable.
  Unlike the duplicate direction below, this one does NOT skip an id whose area no row owns: a
  typo'd prefix (`CHM-DECK-05`) is exactly the miss it exists to catch, and it has caught orphan
  regression ids since #800. The cost is that any `AREA-NN`-shaped token in a title is read as a
  feature id (`UTF-8`, `SHA-256`), so a title must not carry one incidentally - rename the test.
- DUPLICATE (`check_duplicate_feature_ids`): a feature id carried by test titles in MORE THAN ONE
  file must have every one of those titles cited by a spec row that owns the id, so a new test
  cannot quietly borrow an id another file already owns. It reads the WHOLE test corpus, not just
  the reverse-mapped part. Three rules bound it:
  - While an id lives in ONE file this direction demands no citation, unconditionally. That
    relaxation used to be load-bearing (the `*.spec.*` corpus was not reverse-mapped, so nothing
    else asked for those citations). For a FULLY mapped target it is not: the reverse direction
    already demands a citation for every test title that carries an id, same-file ones included,
    and dropping the relaxation was measured to find nothing the reverse direction does not
    already report - it is kept so a same-file miss is reported ONCE, by the direction that
    explains it best. For a RESTRICTED target the relaxation does bite: a single-file id in a
    plain `*.spec.*` file gets the ownership half above but no citation demand from either
    direction until the target graduates. That is the deliberate meaning of "restricted", not an
    oversight; making it conditional here was tried and reverted, because the message this
    direction emits ("also used by test ... in another file") is false for a single-file id.
  - An id whose AREA (the segment before the first `-`) no spec row anywhere owns is skipped. An
    `HTTP-404` in a title matches the feature-id shape, and must not red CI on its own. A NEW id
    in a known area - `CMH-DECK-99`, say - is still checked even before it has a row, because
    that is exactly the borrow this gate exists to catch.
  - A `describe(...)` wrapper counts toward "how many files carry this id", since hiding a borrow
    in a suite title is the obvious evasion, but only a `test(...)`/`it(...)` title is REPORTED
    here - a suite title cannot be cited by a row (issue #629), so demanding it be cited would be
    a demand no author could satisfy. The reverse direction still checks a suite title's id for
    OWNERSHIP, which is satisfiable, so a suite-title borrow is not invisible.
- DUPLICATE ROWS (`check_duplicate_spec_rows`): a feature id is the id cell of at most ONE feature
  row per spec. The other three directions all assume "one feature id, one behavior", but nothing
  enforced it (issue #904): `_spec_rows` merges same-id rows, so a test cited by EITHER row
  satisfied the other. `_feature_rows` is the single definition of "a spec row" for both this
  direction and `_spec_rows`, so what is ENFORCED covers what is CONSUMED. A row is excluded only
  when it sits under a `Doc-surface registry` heading (`_NON_FEATURE_SECTIONS`) AND its table
  header carries a `Doc surface` column (`_NON_FEATURE_TABLE_HEADERS`) - that table's rows also
  begin with a feature id. Either gate alone was wrong: keying on the header let a duplicate be
  parked under any table that spelled a column `Doc surface`. Anything else counts, so the rule
  fails CLOSED.

The REVERSE direction reads only literal `test(...)` / `it(...)` / `describe(...)` calls that
BEGIN a line (`_js_test_titles`), so `page.test(...)` is correctly ignored - but so is a
declaration buried mid-line (`if (cond) test("x (AREA-99)", ...)`) or a title assembled by
concatenation. There are none in the corpus today; that is the residual escape hatch, and it is a
grammar limit rather than an exemption.

Two TARGET SHAPES are registered. The usual one owns a `tests/` directory of JS/TS specs. The
other is a FLAT PYTHON SUITE (`FLAT_PYTHON_SUITES`, issue #1002): `test_*.py` files sitting beside
the code they cover, which is what `scripts/SPEC.md` owns and what `run_script_tests.py` runs. For
that shape `_tests_dir` answers with the spec's own directory (only when it really holds such a
suite, so a mistyped registration still fails closed) and `_test_corpus` collects its `test_*.py`
files. A flat target gets the FORWARD and DUPLICATE-ROW directions in full; the two JS-title
directions are bounded to files that carry JS titles (`_carries_js_titles`), because a Python test
is a `Class.method` name that cannot spell a hyphenated feature id, and because such a corpus is
full of feature-id-SHAPED fixture strings written for these checkers' own unit tests. That is why
`scripts/SPEC.md` is registered in `INTENTIONALLY_RESTRICTED_SPECS` rather than waiting to
graduate.
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
    (REPO_ROOT / "scripts" / "SPEC.md", REPO_ROOT),
)
# Targets whose tests are a FLAT `test_*.py` set sitting BESIDE the code they cover, rather than a
# `tests/` directory of JS specs (issue #1002). The repo-guard spec is that shape: its suites are
# `scripts/test_*.py`, so the `<spec dir>/tests` / `<base>/tests` lookup found nothing and the
# target failed closed with "no tests directory found". Membership is declared, not sniffed, so a
# new flat target is a reviewed edit; the directory is the spec's own, and it counts only when it
# really holds a suite, so a mistyped registration still fails closed.
FLAT_PYTHON_SUITES: frozenset[Path] = frozenset({
    (REPO_ROOT / "scripts" / "SPEC.md").resolve(),
})
# Specs whose ENTIRE test corpus is reverse-mapped, not just the `*.test.*` / regressions subset.
# A spec joins this set once every feature id its tests carry is owned and cited by it; see the
# module docstring. Every SPEC_TARGETS entry with a JS corpus is listed - the set remains the
# graduation mechanism for a target added later, not a standing exemption for any shipped one.
FULLY_REVERSE_MAPPED_SPECS = frozenset({
    (REPO_ROOT / "plugins" / "commentable-html" / "dev" / "SPEC.md").resolve(),
    (REPO_ROOT / "site" / "tests" / "SPEC.md").resolve(),
    (REPO_ROOT / ".github" / "skills" / "demo-video" / "SPEC.md").resolve(),
})
# The targets deliberately left OUT of the set above, i.e. still restricted to the `*.test.*` /
# regressions subset. A new target that genuinely needs to start restricted and graduate later is
# registered HERE, which is a reviewed one-line edit rather than a silent omission -
# `test_every_spec_target_is_fully_reverse_mapped` compares the two.
# `scripts/SPEC.md` is here for a reason that will not change with a cleanup: a Python test is a
# `Class.method` name, and an identifier cannot carry a hyphenated feature id, so there is no
# reverse citation to demand. Its corpus is also full of feature-id-SHAPED fixture strings
# (`CMH-FOO-01`, `DEMO-01`, `ORPHAN-99`) written for the checkers' own unit tests, which a reverse
# scan would read as real ids. The FORWARD and DUPLICATE-ROW directions do gate it.
INTENTIONALLY_RESTRICTED_SPECS: frozenset[Path] = frozenset({
    (REPO_ROOT / "scripts" / "SPEC.md").resolve(),
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
# The flat Python suite grammar, matching what `run_script_tests.py` discovers: `test_*.py`.
_PY_TEST_FILE_RE = re.compile(r"test_[^/\\]*\.py$")
_PY_TEST_GLOB = "test_*.py"
_JS_TEST_ONLY_FILE_RE = re.compile(r"\.test\.%s$" % _JS_TEST_SUFFIX, re.IGNORECASE)
_REGRESSION_FILE_RE = re.compile(
    r"regressions[^/\\]*\.spec\.%s$" % _JS_TEST_SUFFIX, re.IGNORECASE)
_JS_SUFFIXES = frozenset({".js", ".cjs", ".mjs", ".ts", ".cts", ".mts"})
_BACKTICK_PATH_RE = re.compile(r"`([^`]+\.(?:py|%s|tsx))`" % _JS_TEST_SUFFIX)
_QUOTED_RE = re.compile(r"`([^`]+)`")
_FEATURE_ID_RE = re.compile(r"\b[A-Z][A-Z0-9]+(?:-[A-Z0-9]+)*-\d+[a-z]?\b")
_PY_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?")
# Duplicate-row parsing (`_feature_rows`): a CommonMark fence, a blockquote prefix, the inline
# decoration a table cell may carry, the heading that opens a non-feature section, and the tables
# whose feature-id rows are NOT feature rows.
_FENCE_RE = re.compile(r" {0,3}(`{3,}|~{3,})(.*)$")
_BLOCKQUOTE_RE = re.compile(r"^(?: {0,3}>[ \t]?)+")
_MD_DECORATION_RE = re.compile(r"^[*_`~]+|[*_`~]+$")
_HTML_TAG_RE = re.compile(r"</?[A-Za-z][^>]*>")
_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\ufeff]")
_HEADING_RE = re.compile(r" {0,3}#{1,6}\s+(.*?)\s*#*\s*$")
_INDENTED_CODE_RE = re.compile(r" {4,}\S")
_NON_FEATURE_SECTIONS = ("doc-surface registry",)
_NON_FEATURE_TABLE_HEADERS = ("doc surface",)
_JS_TITLE_RE = re.compile(
    r'(?:test\.describe(?:\.(?:only|skip|fixme|fail|serial|parallel))*|'
    r'(?:test|it|describe)(?:\.(?:only|skip|fixme|fail|serial|parallel))*)\s*\(\s*'
    r'(?:"((?:\\.|[^"\\])*)"|\'((?:\\.|[^\'\\])*)\'|`((?:\\.|[^`\\])*)`)',
    re.DOTALL,
)
# Test-only titles: `test(...)` / `it(...)` (with modifiers) but NOT `describe(...)` suite names,
# so the strict "cite an exact TEST" gate is not satisfied by a suite/group title.
_JS_TEST_ONLY_RE = re.compile(
    r'(?:test|it)(?:\.(?:only|skip|fixme|fail|serial|parallel))*\s*\(\s*'
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


def _is_flat_python_suite(spec_path: Path) -> bool:
    """Whether this target's tests are a flat `test_*.py` set beside the code (see the registry)."""
    return spec_path.resolve() in FLAT_PYTHON_SUITES


def _tests_dir(spec_path: Path, base_dir: Path) -> Path | None:
    """The tests directory a spec owns.

    A registered FLAT PYTHON target has no `tests/` directory at all - its `test_*.py` files sit
    beside the code they cover - so its own directory is the answer, and only when that directory
    really holds such a suite. A mistyped registration therefore still fails closed, exactly as a
    mistyped base does.

    Otherwise `<spec dir>/tests` is tried FIRST because it is the unambiguous one: it resolves
    `dev/tests`, `.github/skills/demo-video/tests`, and `site/tests/tests` alike. Preferring
    `<base>/tests` would let a future repo-root `tests/` shadow the site target's real corpus and
    silently stop checking it. `<base>/tests` stays as the fallback for a target whose spec does
    not sit beside its tests.
    """
    if _is_flat_python_suite(spec_path):
        parent = spec_path.parent
        return parent if parent.is_dir() and any(parent.glob(_PY_TEST_GLOB)) else None
    for candidate in (spec_path.parent / "tests", base_dir / "tests"):
        if candidate.is_dir():
            return candidate
    return None


def _is_reverse_mapped(name: str) -> bool:
    """Whether a test file name is in the reverse-mapping corpus (see the module docstring)."""
    return bool(_JS_TEST_ONLY_FILE_RE.search(name) or _REGRESSION_FILE_RE.search(name))


def _carries_js_titles(path: Path) -> bool:
    """Whether the JS title grammar can say anything about this file.

    The reverse and duplicate directions read `test(...)` / `it(...)` / `describe(...)` titles, a
    JS/TS construct. Running that scanner over a Python suite is not merely useless, it is unsafe:
    a flat `scripts/test_*.py` corpus is full of feature-id-SHAPED fixture strings written for the
    checkers' own unit tests, and a JS fixture embedded in a Python string would be read as a real
    declaration. So both directions are bounded to the files whose grammar they actually parse.
    """
    return path.suffix in _JS_SUFFIXES


def _test_corpus(spec_path: Path, base_dir: Path) -> tuple[Path, ...]:
    """Every test file under the spec's tests dir, recursively.

    Recursive, not flat: the forward direction accepts a nested citation
    (`tests/sub/x.spec.js`), so a flat scan would let a test one directory down fall out of the
    reverse and duplicate directions while still being a valid citation - and still RUNNING in CI.
    One walk filtered by name, rather than a walk per glob, keeps the added cost negligible.

    A registered FLAT PYTHON target's corpus is its `test_*.py` files instead - the shape
    `run_script_tests.py` discovers - so "the tests this spec owns" means the same thing for both
    shapes.

    The WHOLE corpus is returned; `check_all` decides which half of the reverse direction each
    file gets (`_is_reverse_mapped`), so the split lives in one place instead of here as well.
    """
    tests_dir = _tests_dir(spec_path, base_dir)
    if tests_dir is None:
        return ()
    flat_python = _is_flat_python_suite(spec_path)
    found: list[Path] = []
    for path in tests_dir.rglob("*"):
        name = path.name
        matches = (
            _PY_TEST_FILE_RE.match(name) if flat_python else _JS_TEST_FILE_RE.search(name)
        )
        if not matches or not path.is_file():
            continue
        found.append(path)
    return tuple(sorted(set(found), key=lambda path: path.as_posix()))


def _spec_rows(spec_path: Path) -> dict[str, list[str]]:
    """Map each feature id to the coverage cell of every WELL-FORMED feature row it owns.

    Reads the same enumeration the duplicate-row direction enforces over (`_feature_rows`), so the
    invariant that is CHECKED covers everything that is CONSUMED. The relationship is deliberately
    "enforced is a SUPERSET of consumed", not equality: the duplicate direction is permissive on
    purpose (a blockquoted, two-cell, or trailing-pipe-less row still counts, so a malformed
    duplicate is SEEN), but the same permissiveness here would be fail-OPEN - an illustrative row
    quoted in prose would OWN an id and SATISFY a citation. So only a well-formed row supplies a
    coverage cell, while every row counts toward the duplicate gate. A registry row or a row inside
    a fenced sample table is not a row at all for either, which is what stops a citation from being
    satisfied by a line that is not a spec row.
    """
    rows: dict[str, list[str]] = {}
    for _line_no, feature_id, cells, well_formed in _feature_rows(spec_path)[0]:
        coverage = rows.setdefault(feature_id, [])
        if well_formed:
            coverage.append(cells[-1])
    return rows


def _unfenced_lines(text: str) -> tuple[tuple[tuple[int, str], ...], int | None]:
    """Every `(line_no, line)` OUTSIDE a fenced code block, plus an unclosed fence's line.

    One fence state machine for the whole module, following CommonMark: a fence opens on a run of
    3+ backticks or tildes indented at most 3 spaces (4+ spaces is indented CODE, not a fence) and
    closes only on a run of the SAME character that is at least as long and carries no other text.
    A backtick fence's info string may not contain a backtick, so such a line is not an opener. A
    tilde line inside a backtick fence is therefore literal content, and a sample table in a code
    block is never read as a spec row.
    """
    lines: list[tuple[int, str]] = []
    fence: tuple[str, int] | None = None
    fence_line: int | None = None
    for line_no, line in enumerate(text.splitlines(), 1):
        match = _FENCE_RE.match(_BLOCKQUOTE_RE.sub("", line))
        if match:
            marker, rest = match.group(1), match.group(2)
            if fence is None:
                if marker[0] != "`" or "`" not in rest:
                    fence, fence_line = (marker[0], len(marker)), line_no
                    continue
            elif fence[0] == marker[0] and len(marker) >= fence[1] and not rest.strip():
                fence, fence_line = None, None
                continue
        if fence is not None:
            continue
        lines.append((line_no, line))
    return tuple(lines), fence_line


def _table_cells(line: str) -> tuple[list[str], bool] | None:
    """`(cells, well_formed)` for a markdown table row, or None when *line* is not one.

    Deliberately more permissive than `_row_cells`: a row inside a blockquote, a two-cell row, and
    a row with a missing trailing pipe are all returned, because the duplicate gate must SEE a
    malformed duplicate rather than skip it. `well_formed` says whether the row is the canonical
    shape every other direction consumes - not blockquoted, closed with a trailing pipe, and at
    least three cells - so the two consumers can differ deliberately (see `_spec_rows`).
    """
    unquoted = _BLOCKQUOTE_RE.sub("", line)
    quoted = unquoted != line
    stripped = unquoted.strip()
    if not stripped.startswith("|"):
        return None
    body = stripped[1:]
    closed = body.endswith("|")
    if closed:
        body = body[:-1]
    cells = [cell.strip() for cell in body.split("|")]
    if len(cells) < 2:
        return None
    return cells, (closed and not quoted and len(cells) >= 3)


def _undecorated(cell: str) -> str:
    """*cell* with the markup that WRAPS its text removed, so an id is seen as the reader sees it.

    Strips an HTML tag (`<code>ID</code>`), a markdown link (`[ID](#x)`), a zero-width character,
    and leading/trailing emphasis/code/strikethrough runs (`**ID**`, `` `ID` ``, `~~ID~~`). Only
    WRAPPING decoration goes: an id that merely CONTAINS one of those characters (`DEM*O-01`) is
    left alone rather than being normalised into a different id. Anything the reader sees as a
    feature id must normalise to one, or a duplicate could hide behind ordinary markup.
    """
    text = _ZERO_WIDTH_RE.sub("", cell)
    text = _HTML_TAG_RE.sub("", text)
    text = _MD_LINK_RE.sub(r"\1", text)
    return _MD_DECORATION_RE.sub("", text.strip()).strip()


def _is_non_feature_header(header: list[str]) -> bool:
    """Whether *header* belongs to a table whose feature-id rows are not feature rows.

    Matched as a PREFIX against any cell, so renaming the column (`Doc surfaces`) or inserting one
    before it does not silently turn every registry row into a duplicate.
    """
    return any(
        _undecorated(cell).lower().startswith(_NON_FEATURE_TABLE_HEADERS)
        for cell in header
    )


def _is_delimiter_row(cells: list[str]) -> bool:
    return all(cell and set(cell) <= {"-", ":", " "} for cell in cells)


def _feature_rows(
    spec_path: Path,
) -> tuple[tuple[tuple[int, str, tuple[str, ...], bool], ...], int | None]:
    """Every FEATURE row as `(line_no, feature_id, cells, well_formed)`, plus an open fence line.

    The single definition of "a spec row" for this module. The "Doc-surface registry" table
    (`Feature id | Doc surface | Deck`) also starts every row with a feature id, so a row is
    excluded when it is BOTH under a recognised non-feature SECTION heading
    (`_NON_FEATURE_SECTIONS`) AND under a table header carrying a recognised non-feature column
    (`_NON_FEATURE_TABLE_HEADERS`, matched against ANY header cell so a renamed or reordered column
    does not silently turn every registry row into a duplicate). Otherwise every registered id
    would look like a second row for itself - while a table that merely spells a column
    `Doc surface` somewhere else in the spec cannot be used to park a hidden duplicate.

    The rule is deliberately inverted so it FAILS CLOSED: anything else counts. Excluding
    everything that is not spelled exactly `Behavior` was the opposite, and hid a real duplicate
    behind a header this parser merely failed to recognise (`**Behavior**`, `Behaviour`, or a cell
    split apart by a pipe inside a code span). Wrapping decoration is stripped from the header and
    id cells for the same reason.

    The header is taken from the line ABOVE each DELIMITER row, as GFM defines it, so header state
    cannot latch past the end of its table: a second table butted directly against the registry
    with no blank line gets its own header (or none) rather than inheriting the registry's.

    A line indented 4+ spaces is indented CODE, so - like the fence rule - it is never a row.
    The second return value is the line where a fence was opened and never closed: an unterminated
    fence would otherwise silently blank every row after it, and because `dev/SPEC.md` is a
    concatenation of `dev/spec/NN-*.md` partials, one imbalance in an early partial would un-check
    every later section.
    """
    rows: list[tuple[int, str, tuple[str, ...], bool]] = []
    header: list[str] | None = None
    previous: list[str] | None = None
    in_non_feature_section = False
    lines, fence_line = _unfenced_lines(_read(spec_path))
    for line_no, line in lines:
        heading = _HEADING_RE.match(line)
        if heading:
            in_non_feature_section = heading.group(1).strip().lower() in _NON_FEATURE_SECTIONS
            header, previous = None, None
            continue
        if _INDENTED_CODE_RE.match(_BLOCKQUOTE_RE.sub("", line)):
            header, previous = None, None
            continue
        parsed = _table_cells(line)
        if parsed is None:
            header, previous = None, None
            continue
        cells, well_formed = parsed
        if _is_delimiter_row(cells):
            header, previous = previous, None
            continue
        previous = cells
        feature_id = _undecorated(cells[0])
        if not _FEATURE_ID_RE.fullmatch(feature_id):
            continue
        if in_non_feature_section and header is not None and _is_non_feature_header(header):
            continue
        rows.append((line_no, feature_id, tuple(cells), well_formed))
    return tuple(rows), fence_line


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
    # Scans every table row, not only feature rows, so a citation anywhere in the spec is checked -
    # but through the shared fence state machine, so a sample table inside a code block is never
    # validated as if it were a real citation.
    for line_no, line in _unfenced_lines(text)[0]:
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
    ownership_only: bool = False,
) -> list[SpecIssue]:
    """Report tests whose feature id has no owning spec row, or whose row does not cite them.

    With *ownership_only* the citation half is skipped: only "this id has no spec row" is
    reported. That is the half a RESTRICTED target still gets over its plain `*.spec.*` files, so
    an id no row owns can never hide there even before the target graduates.
    """
    rows = _spec_rows(spec_path)

    issues: list[SpecIssue] = []
    for test_path in test_paths:
        if not _carries_js_titles(test_path):
            continue
        text = _read(test_path)
        rel = _coverage_rel(base_dir, test_path)
        test_titles = _js_test_titles(text, _JS_TEST_ONLY_RE)
        for title in sorted(test_titles):
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
                if ownership_only:
                    continue
                if not _row_cites(matching_rows, rel, title):
                    issues.append(SpecIssue(
                        test_path,
                        line_no,
                        "test title `%s` is not cited by its `%s` spec row (add the title to "
                        "that row's covering-tests cell in `%s`, after its `%s` reference and "
                        "before the next one or the next `;`)"
                        % (title, feature_id, _display(spec_path), rel),
                    ))
        # A `describe(...)` suite title is checked for OWNERSHIP only. A row cannot cite a suite
        # title (issue #629), so demanding one would be unsatisfiable - but an id no row owns,
        # parked in a suite title, IS satisfiable (drop the id, or add the row) and was otherwise
        # the last carrier both directions missed: REVERSE read only `test`/`it`, and DUPLICATE
        # skips a single-file id.
        for title in sorted(_js_test_titles(text, _JS_TITLE_RE) - test_titles):
            line_no = _title_line(text, title)
            for feature_id in sorted(set(_FEATURE_ID_RE.findall(title))):
                if feature_id not in rows:
                    issues.append(SpecIssue(
                        test_path,
                        line_no,
                        "feature id `%s` has no spec row (carried by the suite title `%s`; a "
                        "suite title cannot be cited, so drop the id or add its row)"
                        % (feature_id, title),
                    ))
    return issues


@_scoped
def check_duplicate_feature_ids(
    targets: tuple[tuple[Path, Path], ...] = SPEC_TARGETS,
) -> list[SpecIssue]:
    """Fail when one feature id is carried by test titles in more than one FILE and no spec row
    that owns the id cites every one of them (see the module docstring for the three bounding
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
            if not _carries_js_titles(test_path):
                continue
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
        # A single-file id is left to the REVERSE direction (see the module docstring), which now
        # reads every target's whole corpus for OWNERSHIP and, for a fully mapped target,
        # citations too.
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
def check_duplicate_spec_rows(
    targets: tuple[tuple[Path, Path], ...] = SPEC_TARGETS,
) -> list[SpecIssue]:
    """Fail when one feature id is the id cell of more than one FEATURE row in the same spec.

    "One feature id, one behavior" was unenforced (issue #904): `_spec_rows` merges same-id rows
    by appending their coverage cells, so a test cited by EITHER row satisfied the other and a
    citation for such an id was ambiguous - a future test carrying the id could be "cited" by the
    unrelated row. Seven ids owned two rows each before this direction existed: `CMH-BUILD-13`,
    `CMH-CONTENT-01` through `CMH-CONTENT-04`, and `CMH-DECK-21` in the commentable-html spec, plus
    `SITE-NAV-02` in the site spec. Each spec's "Renamed feature ids" section records where a
    renamed behavior went, since released `CHANGELOG.md` history still cites the old id.

    Scope note: this is enforced over `SPEC_TARGETS` (commentable-html, the site, demo-video, and
    the repo-guard scripts), not over every `SPEC.md` in the repository; a new target joins by
    being registered there.
    """
    issues: list[SpecIssue] = []
    for spec_path, _base_dir in targets:
        rows, open_fence_line = _feature_rows(spec_path)
        if open_fence_line is not None:
            # A fence that never closes swallows every row after it, so the direction would go
            # quietly green over an unchecked spec. `dev/SPEC.md` is a concatenation of partials,
            # so one imbalance early on would un-check every later section.
            issues.append(SpecIssue(
                spec_path,
                open_fence_line,
                "code fence opened here is never closed, so the spec rows after it cannot be "
                "read; close the fence",
            ))
        lines: dict[str, list[int]] = {}
        for line_no, feature_id, _cells, _well_formed in rows:
            lines.setdefault(feature_id, []).append(line_no)
        for feature_id, line_numbers in sorted(lines.items()):
            if len(line_numbers) < 2:
                continue
            issues.append(SpecIssue(
                spec_path,
                line_numbers[0],
                "feature id `%s` is the id cell of %d spec rows (lines %s); one feature id, one "
                "behavior - give one row a free id and update its citations"
                % (feature_id, len(line_numbers),
                   ", ".join(str(number) for number in line_numbers)),
            ))
    return issues


@_scoped
def check_all(
    targets: tuple[tuple[Path, Path], ...] = SPEC_TARGETS,
    fully_reverse_mapped: frozenset[Path] = FULLY_REVERSE_MAPPED_SPECS,
) -> list[SpecIssue]:
    issues: list[SpecIssue] = []
    readable = []
    for spec_path, base_dir in targets:
        if _feature_rows(spec_path)[1] is not None:
            # An unclosed fence blanks every row after it, so the citation directions would report
            # "has no spec row" for hundreds of tests and bury the one actionable cause.
            # `check_duplicate_spec_rows` below reports the fence itself.
            continue
        readable.append((spec_path, base_dir))
    for spec_path, base_dir in readable:
        issues.extend(check_spec(spec_path, base_dir))
        if _tests_dir(spec_path, base_dir) is None:
            # Fail CLOSED: with no tests directory the reverse and duplicate directions are silent
            # no-ops, so a mistyped base would look like a clean target forever.
            looked_in = (
                "`%s` (no `test_*.py` beside the spec)" % _display(spec_path.parent)
                if _is_flat_python_suite(spec_path)
                else "`%s` and `%s`"
                % (_display(spec_path.parent / "tests"), _display(base_dir / "tests"))
            )
            issues.append(SpecIssue(
                spec_path,
                1,
                "no tests directory found for this target (looked in %s), so the "
                "reverse and duplicate directions would check nothing" % looked_in,
            ))
            continue
        fully_mapped = spec_path.resolve() in fully_reverse_mapped
        corpus = _test_corpus(spec_path, base_dir)
        if fully_mapped:
            if corpus:
                issues.extend(check_test_id_mappings(spec_path, base_dir, corpus))
        else:
            mapped = tuple(path for path in corpus if _is_reverse_mapped(path.name))
            if mapped:
                issues.extend(check_test_id_mappings(spec_path, base_dir, mapped))
            # The rest of a restricted target's corpus still gets the OWNERSHIP half, so an id no
            # row owns cannot hide in a plain `*.spec.*` file while the target waits to graduate.
            rest = tuple(path for path in corpus if not _is_reverse_mapped(path.name))
            if rest:
                issues.extend(check_test_id_mappings(
                    spec_path, base_dir, rest, ownership_only=True))
    issues.extend(check_duplicate_feature_ids(readable))
    issues.extend(check_duplicate_spec_rows(targets))
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
