#!/usr/bin/env python3
"""Verify spec rows point at real tests and exact test names."""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC_TARGETS = (
    (REPO_ROOT / "plugins" / "commentable-html" / "dev" / "SPEC.md",
     REPO_ROOT / "plugins" / "commentable-html" / "dev"),
    (REPO_ROOT / "site" / "tests" / "SPEC.md", REPO_ROOT),
)

_TEST_PATH_RE = re.compile(
    r"`((?:tests|site/tests/tests)/[^`]+\.(?:py|js|mjs)|scripts/test_[^`]+\.py)`"
)
_BACKTICK_PATH_RE = re.compile(r"`([^`]+\.(?:py|js|mjs|ts|tsx))`")
_QUOTED_RE = re.compile(r"`([^`]+)`")
_FEATURE_ID_RE = re.compile(r"\b[A-Z][A-Z0-9]+(?:-[A-Z0-9]+)*-\d+[a-z]?\b")
_PY_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?")
_JS_TITLE_RE = re.compile(
    r'(?:test\.describe(?:\.(?:only|skip|fixme|serial|parallel))*|'
    r'(?:test|it|describe)(?:\.(?:only|skip|fixme|serial|parallel))*)\s*\(\s*'
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


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")


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


def _python_has_name(path: Path, name: str) -> bool:
    text = _read(path)
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return False

    classes: dict[str, set[str]] = {}
    functions: set[str] = set()
    all_methods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            class_methods = {
                child.name
                for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            classes[node.name] = class_methods
            all_methods.update(class_methods)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.add(node.name)

    if "." in name:
        class_name, method_name = name.split(".", 1)
        return method_name in classes.get(class_name, set())
    return name in classes or name in functions or name in all_methods


def _file_has_name(path: Path, name: str) -> bool:
    text = _read(path)
    if _FEATURE_ID_RE.fullmatch(name.strip()):
        haystack = "\n".join(_js_test_titles(text)) if path.suffix in {".js", ".mjs"} else text
        return name in set(_FEATURE_ID_RE.findall(haystack))
    if path.suffix == ".py":
        return _python_has_name(path, name)
    if path.suffix in {".js", ".mjs"}:
        return name in _js_test_titles(text)
    return False


def _js_test_titles(text: str) -> set[str]:
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
            match = _JS_TITLE_RE.match(text, i)
            if match:
                raw = next(group for group in match.groups() if group is not None)
                titles.add(_decode_js_string(raw))
                i = match.end()
                line_start = False
                continue
        line_start = False
        i += 1
    return titles


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
    if test_path.suffix in {".js", ".mjs"}:
        return bool(re.search(r"\s", name))
    if _PY_NAME_RE.fullmatch(name):
        return (
            name.startswith("test_")
            or "." in name
            or re.search(r"[a-z][A-Z]", name) is not None
            or re.search(r"(Tests?|Case)$", name) is not None
        )
    return False


def _clause_end(text: str, start: int, default_end: int) -> int:
    in_code = False
    for pos in range(start, default_end):
        char = text[pos]
        if char == "`":
            in_code = not in_code
        elif char == ";" and not in_code:
            return pos
    return default_end


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
            for name in _referenced_names(coverage[match.end():end], test_path):
                if not _file_has_name(test_path, name):
                    issues.append(SpecIssue(
                        spec_path,
                        line_no,
                        "`%s` not found in `%s`" % (name, rel),
                    ))
    return issues


def check_test_id_mappings(
    spec_path: Path,
    base_dir: Path,
    test_paths: tuple[Path, ...],
) -> list[SpecIssue]:
    rows: dict[str, list[str]] = {}
    for line in _read(spec_path).splitlines():
        cells = _row_cells(line)
        if cells and _FEATURE_ID_RE.fullmatch(cells[0]):
            rows.setdefault(cells[0], []).append(cells[-1])

    issues: list[SpecIssue] = []
    for test_path in test_paths:
        text = _read(test_path)
        rel = (
            test_path.resolve().relative_to(base_dir.resolve()).as_posix()
            if test_path.resolve().is_relative_to(base_dir.resolve())
            else test_path.resolve().relative_to(REPO_ROOT).as_posix()
        )
        for title in sorted(_js_test_titles(text)):
            line_no = text[:text.find(title)].count("\n") + 1
            for feature_id in _FEATURE_ID_RE.findall(title):
                matching_rows = rows.get(feature_id)
                if not matching_rows:
                    issues.append(SpecIssue(
                        test_path,
                        line_no,
                        "feature id `%s` has no spec row" % feature_id,
                    ))
                    continue
                if not any(
                    "`%s`" % rel in coverage and "`%s`" % title in coverage
                    for coverage in matching_rows
                ):
                    issues.append(SpecIssue(
                        test_path,
                        line_no,
                        "test title `%s` is not cited by its `%s` spec row"
                        % (title, feature_id),
                    ))
    return issues


def check_all(targets: tuple[tuple[Path, Path], ...] = SPEC_TARGETS) -> list[SpecIssue]:
    issues: list[SpecIssue] = []
    for spec_path, base_dir in targets:
        issues.extend(check_spec(spec_path, base_dir))
        regression_dir = base_dir / "tests"
        if regression_dir.is_dir():
            regression_tests = tuple(sorted(regression_dir.glob("*regressions*.spec.js")))
            issues.extend(check_test_id_mappings(spec_path, base_dir, regression_tests))
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
