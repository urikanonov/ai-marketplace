#!/usr/bin/env python3
"""validate_markdown.py - repository-wide Markdown hygiene checks.

Scans the repository's Markdown files for issues that break rendering or
violate the project's ASCII-only writing convention. It is a global tool: it
is not tied to any single plugin or skill.

Errors (fail the run, exit code 1):
  - ai-chars     Non-ASCII "smart" characters: em/en dashes, curly quotes,
                 ellipsis, non-breaking / zero-width spaces, byte-order marks.
                 Run with --fix to rewrite them to plain ASCII in place.
  - local-path   Absolute local filesystem paths (C:\\..., /Users/..., etc.)
                 embedded in prose.
  - broken-link  Relative links whose target file does not exist.
  - link-case    Links whose case differs from the on-disk path. Local Windows
                 and macOS filesystems accept the mismatch; the Linux CI runner
                 is case-sensitive and rejects it.

Warnings (informational; fail the run only with --strict):
  - broken-anchor  `#section` or `other.md#section` refs with no matching heading.
  - table          Table rows whose column count differs from the header row.
  - placeholder    TODO / FIXME / TBD / XXX markers left in shipped docs.
  - blank-heading  A heading that is not followed by a blank line.
  - double-bracket Wiki-style `[[link]]` remnants.
  - style          Filler intros, promotional adjectives, and stale "line N"
                   references (only checked when --style is given).

Usage:
  python scripts/validate_markdown.py                 # scan the whole repo
  python scripts/validate_markdown.py path/ file.md   # scan specific paths
  python scripts/validate_markdown.py --fix           # auto-fix ai-chars in place
  python scripts/validate_markdown.py --strict        # treat warnings as failures too
  python scripts/validate_markdown.py --style         # also run prose-style checks
  python scripts/validate_markdown.py --no-links      # skip link and anchor checks
"""

import argparse
import difflib
import os
import re
import sys
from collections import namedtuple
from pathlib import Path

Finding = namedtuple("Finding", ["severity", "line", "code", "message"])

ERROR = "error"
WARNING = "warning"


# Characters that AI tools commonly substitute for plain ASCII equivalents.
# Each entry maps a Unicode char to (human-readable name, ASCII replacement).
# An empty replacement means the character is removed entirely.
AI_CHARACTERS = {
    "\u2014": ("em-dash",             " - "),
    "\u2013": ("en-dash",             "-"),
    "\u2026": ("ellipsis",            "..."),
    "\u201C": ("left double quote",   '"'),
    "\u201D": ("right double quote",  '"'),
    "\u2018": ("left single quote",   "'"),
    "\u2019": ("right single quote",  "'"),
    "\u00A0": ("non-breaking space",  " "),
    "\u200B": ("zero-width space",    ""),
    "\u2003": ("em space",            " "),
    "\u2002": ("en space",            " "),
    "\uFEFF": ("byte-order mark",     ""),
}

LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
HTML_ANCHOR_RE = re.compile(r'<a\s+(?:id|name)=["\']([^"\']+)["\']', re.IGNORECASE)
CODE_FENCE_RE = re.compile(r"^\s*```.*?^\s*```", re.MULTILINE | re.DOTALL)
INLINE_CODE_RE = re.compile(r"``[^`]+``|`[^`]+`")
LINE_NUM_REF_RE = re.compile(r"\blines?\s+\d+(?:\s*[-,]\s*\d+)*\b", re.IGNORECASE)
DOUBLE_BRACKET_RE = re.compile(r"\[\[")
TABLE_ROW_RE = re.compile(r"^\s*\|")
TABLE_SEP_RE = re.compile(r"^\s*\|[\s:_-]+\|")

EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "ftp://", "tel:")

LOCAL_PATH_RES = [
    (re.compile(r"\b[A-Za-z]:[\\/][\w.\-\\/ ]+"), "Windows filesystem path"),
    (re.compile(r"(?<![\w/])/(?:Users|home|tmp|var)/[\w.\-/]+"), "Unix filesystem path"),
]

PLACEHOLDER_RES = [
    (re.compile(r"\bTBD\b"), "TBD"),
    (re.compile(r"\bTODO\b"), "TODO"),
    (re.compile(r"\bFIXME\b"), "FIXME"),
    (re.compile(r"\bXXX\b"), "XXX"),
]

FILLER_INTRO_RES = [
    (re.compile(
        r"^\s*This (?:guide|document|page|section|article|chapter) "
        r"(?:describes|covers|explains|introduces|provides|outlines|details)",
        re.IGNORECASE),
     "filler intro ('This X describes/covers/...')"),
    (re.compile(r"^\s*In this (?:guide|document|page|section|article|chapter)\b",
                re.IGNORECASE),
     "filler intro ('In this X...')"),
    (re.compile(r"^\s*The purpose of this (?:guide|document|page|section)\b",
                re.IGNORECASE),
     "filler intro ('The purpose of this X...')"),
]

PROMO_WORDS = {
    "powerful": "promotional; say what the thing does instead",
    "robust": "promotional; describe the actual guarantees",
    "seamless": "promotional filler",
    "seamlessly": "promotional filler",
    "comprehensive": "promotional; list the surface or link to it",
    "cutting-edge": "promotional filler",
    "state-of-the-art": "promotional filler",
    "best-in-class": "promotional filler",
    "world-class": "promotional filler",
}
PROMO_RE = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in PROMO_WORDS) + r")\b",
    re.IGNORECASE,
)

EXCLUDE_DIRS = {
    ".git", ".worktrees", ".plans", "tmp", "node_modules", "bin", "obj", "dist", "build",
    "TestResults", "test-results", "playwright-report", "__pycache__",
    ".venv", "venv", ".vscode", "vendor",
}


def find_repo_root(start):
    """Walk up from *start* to find the repository root (nearest .git)."""
    current = Path(start).resolve()
    while current != current.parent:
        if (current / ".git").exists():
            return current
        current = current.parent
    return Path(start).resolve()


def heading_to_slug(heading):
    """Convert a Markdown heading to a GitHub-compatible anchor slug."""
    slug = re.sub(r"<[^>]+>", "", heading)
    slug = re.sub(r"[`*_~\[\]()]", "", slug)
    slug = slug.strip().lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"\s", "-", slug)
    return slug.strip("-")


_ANCHOR_CACHE = {}


def extract_anchors(file_path):
    """Return the set of anchor slugs defined in a Markdown file (cached)."""
    key = str(file_path)
    if key in _ANCHOR_CACHE:
        return _ANCHOR_CACHE[key]
    try:
        content = Path(file_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        _ANCHOR_CACHE[key] = set()
        return _ANCHOR_CACHE[key]
    anchors = set()
    for m in HEADING_RE.finditer(content):
        slug = heading_to_slug(m.group(2))
        if slug:
            anchors.add(slug)
    for m in HTML_ANCHOR_RE.finditer(content):
        anchors.add(m.group(1).lower())
    _ANCHOR_CACHE[key] = anchors
    return anchors


def lines_outside_code_blocks(content):
    """Yield (line_number, text) for lines NOT inside fenced code blocks."""
    blocked = set()
    for m in CODE_FENCE_RE.finditer(content):
        first = content[:m.start()].count("\n")
        last = content[:m.end()].count("\n")
        blocked.update(range(first, last + 1))
    for idx, text in enumerate(content.split("\n")):
        if idx not in blocked:
            yield idx + 1, text


def find_ai_characters(content):
    """Return findings for each AI/non-ASCII character present."""
    findings = []
    for line_num, line in enumerate(content.split("\n"), start=1):
        for char, (name, _) in AI_CHARACTERS.items():
            if char in line:
                count = line.count(char)
                findings.append(Finding(
                    ERROR, line_num, "ai-chars",
                    f"{count}x {name} (U+{ord(char):04X}); use ASCII instead "
                    f"(run with --fix to rewrite automatically)"))
    return findings


def fix_ai_characters(content):
    """Replace AI-favored characters in place. Returns (new_content, count)."""
    count = 0
    new_content = content
    for char, (_, replacement) in AI_CHARACTERS.items():
        if char in new_content:
            count += new_content.count(char)
            new_content = new_content.replace(char, replacement)
    return new_content, count


def write_text_lf(path, content):
    Path(path).write_text(content, encoding="utf-8", newline="\n")


def check_local_paths(content):
    """Flag absolute local filesystem paths embedded in prose."""
    findings = []
    for line_num, line in lines_outside_code_blocks(content):
        stripped = INLINE_CODE_RE.sub("", line)
        for pattern, label in LOCAL_PATH_RES:
            for m in pattern.finditer(stripped):
                findings.append(Finding(
                    ERROR, line_num, "local-path",
                    f"{label} '{m.group(0)[:60]}'; use a repo-relative path or a web link"))
    return findings


def _check_path_case(link_path, repo_root):
    """Return the on-disk path (correct case) if it differs from *link_path*.

    *link_path* must be normalized but NOT resolved, because resolving folds
    the case to the on-disk spelling on case-insensitive filesystems and hides
    the mismatch. Returns None when the case already matches or cannot judge.
    """
    try:
        rel = link_path.relative_to(repo_root)
    except ValueError:
        try:
            rel = Path(os.path.relpath(link_path, repo_root))
        except (ValueError, OSError):
            return None
    parts = rel.parts
    if not parts or parts[0] == "..":
        return None
    current = repo_root
    corrected = []
    for part in parts:
        if not current.is_dir():
            return None
        try:
            entries = {e.name for e in current.iterdir()}
        except OSError:
            return None
        if part in entries:
            corrected.append(part)
            current = current / part
            continue
        match = next((e for e in entries if e.lower() == part.lower()), None)
        if match is None:
            return None
        corrected.append(match)
        current = current / match
    if tuple(corrected) == parts:
        return None
    return "/".join(corrected)


def _suggest_anchor(missing, available):
    """Return ' (did you mean: #x, #y)?' or '' when no close match exists."""
    if not available:
        return ""
    matches = difflib.get_close_matches(missing, sorted(available), n=3, cutoff=0.6)
    if not matches:
        return ""
    return " (did you mean: " + ", ".join(f"#{m}" for m in matches) + "?)"


def check_links(file_path, content, repo_root):
    """Flag broken relative links, case mismatches, and broken anchors."""
    findings = []
    file_path = Path(file_path)
    file_dir = file_path.parent
    self_anchors = None

    for line_num, line in lines_outside_code_blocks(content):
        for m in LINK_RE.finditer(line):
            link_text = m.group(1)
            url = m.group(2).strip()
            if url.startswith("<") and url.endswith(">"):
                url = url[1:-1]

            if url.startswith("#"):
                anchor = url[1:].lower()
                if anchor:
                    if self_anchors is None:
                        self_anchors = extract_anchors(file_path)
                    if anchor not in self_anchors:
                        hint = _suggest_anchor(anchor, self_anchors)
                        findings.append(Finding(
                            WARNING, line_num, "broken-anchor",
                            f"broken anchor '{url}'; no matching heading in this file{hint}"))
                continue

            if any(url.lower().startswith(p) for p in EXTERNAL_PREFIXES):
                continue

            if "#" in url:
                path_part, anchor = url.rsplit("#", 1)
                anchor = anchor.lower()
            else:
                path_part, anchor = url, None
            path_part = path_part.split("?", 1)[0]
            if not path_part:
                continue

            if path_part.startswith("/"):
                raw_target = repo_root / path_part.lstrip("/")
            else:
                raw_target = file_dir / path_part
            raw_target = Path(os.path.normpath(raw_target))
            target = raw_target

            if not target.exists():
                try:
                    rel_target = target.relative_to(repo_root)
                except ValueError:
                    rel_target = target
                findings.append(Finding(
                    ERROR, line_num, "broken-link",
                    f"broken link [{link_text}]({url}); target not found: {rel_target}"))
                continue

            case_fix = _check_path_case(raw_target, repo_root)
            if case_fix is not None:
                findings.append(Finding(
                    ERROR, line_num, "link-case",
                    f"case-sensitive path mismatch [{link_text}]({url}); on-disk path is "
                    f"'{case_fix}'. The Linux CI runner is case-sensitive; match it exactly"))

            if anchor and target.is_file() and target.suffix.lower() == ".md":
                target_anchors = extract_anchors(target)
                if anchor not in target_anchors:
                    hint = _suggest_anchor(anchor, target_anchors)
                    findings.append(Finding(
                        WARNING, line_num, "broken-anchor",
                        f"broken anchor [{link_text}]({url}); no heading "
                        f"'{anchor}' in {target.name}{hint}"))
    return findings


def _count_table_columns(line):
    """Count table columns, ignoring escaped pipes and pipes inside backticks."""
    clean = re.sub(r"\\\|", "XX", line)
    clean = INLINE_CODE_RE.sub("", clean)
    return clean.count("|")


def check_unbalanced_tables(content):
    """Flag tables whose rows have inconsistent column counts."""
    findings = []
    table_lines = []
    for line_num, line in lines_outside_code_blocks(content):
        if TABLE_ROW_RE.match(line):
            table_lines.append((line_num, _count_table_columns(line), line.strip()))
        else:
            if len(table_lines) >= 2:
                _emit_table_findings(table_lines, findings)
            table_lines = []
    if len(table_lines) >= 2:
        _emit_table_findings(table_lines, findings)
    return findings


def _emit_table_findings(table_lines, findings):
    expected = table_lines[0][1]
    for line_num, pipes, text in table_lines[1:]:
        if TABLE_SEP_RE.match(text):
            continue
        if pipes != expected:
            findings.append(Finding(
                WARNING, line_num, "table",
                f"table row has {pipes - 1} columns, expected {expected - 1} "
                f"(based on the header row)"))


def check_placeholders(content):
    """Flag TBD/TODO/FIXME/XXX markers in shipped docs."""
    findings = []
    for line_num, line in lines_outside_code_blocks(content):
        stripped = INLINE_CODE_RE.sub("", line)
        for pattern, label in PLACEHOLDER_RES:
            if pattern.search(stripped):
                findings.append(Finding(
                    WARNING, line_num, "placeholder",
                    f"placeholder marker '{label}'; finish the section or remove it"))
    return findings


def check_blank_after_heading(content):
    """Every heading should be followed by a blank line."""
    findings = []
    lines = content.split("\n")
    in_fence = False
    for idx, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if HEADING_RE.match(line):
            nxt = lines[idx + 1] if idx + 1 < len(lines) else ""
            # An HTML comment right after a heading is a structural marker, not prose (Backlog.md
            # generates "## Section\n<!-- SECTION:...:BEGIN -->"), so it does not need a blank line.
            if nxt.strip() != "" and not nxt.lstrip().startswith("<!--"):
                findings.append(Finding(
                    WARNING, idx + 1, "blank-heading",
                    "heading is not followed by a blank line"))
    return findings


def check_double_brackets(content):
    """Flag wiki-style [[link]] remnants."""
    findings = []
    for line_num, line in lines_outside_code_blocks(content):
        stripped = INLINE_CODE_RE.sub("", line)
        for m in DOUBLE_BRACKET_RE.finditer(stripped):
            findings.append(Finding(
                WARNING, line_num, "double-bracket",
                f"double bracket '[[' at col {m.start() + 1}; "
                f"use standard Markdown link syntax [text](url)"))
    return findings


def check_filler_intros(content):
    """Flag filler-intro sentences."""
    findings = []
    for line_num, line in lines_outside_code_blocks(content):
        for pattern, label in FILLER_INTRO_RES:
            if pattern.match(line):
                findings.append(Finding(
                    WARNING, line_num, "style",
                    f"{label}; lead with the answer, drop the preamble"))
                break
    return findings


def check_promotional_words(content):
    """Flag promotional adjectives."""
    findings = []
    for line_num, line in lines_outside_code_blocks(content):
        stripped = INLINE_CODE_RE.sub("", line)
        for m in PROMO_RE.finditer(stripped):
            reason = PROMO_WORDS[m.group(1).lower()]
            findings.append(Finding(
                WARNING, line_num, "style",
                f"promotional word '{m.group(1)}' at col {m.start() + 1}; {reason}"))
    return findings


def check_line_number_references(content):
    """Flag 'line(s) N' references that go stale on code changes."""
    findings = []
    for line_num, line in lines_outside_code_blocks(content):
        stripped = INLINE_CODE_RE.sub("", line)
        for m in LINE_NUM_REF_RE.finditer(stripped):
            findings.append(Finding(
                WARNING, line_num, "style",
                f"line-number reference '{m.group()}'; these go stale, "
                f"link to the file or symbol name instead"))
    return findings


def validate_content(file_path, content, repo_root, no_links=False, style=False):
    """Run every check on one file's content. Returns a list of Findings."""
    findings = []
    findings.extend(find_ai_characters(content))
    findings.extend(check_local_paths(content))
    if not no_links:
        findings.extend(check_links(file_path, content, repo_root))
    findings.extend(check_unbalanced_tables(content))
    findings.extend(check_placeholders(content))
    findings.extend(check_blank_after_heading(content))
    findings.extend(check_double_brackets(content))
    if style:
        findings.extend(check_filler_intros(content))
        findings.extend(check_promotional_words(content))
        findings.extend(check_line_number_references(content))
    findings.sort(key=lambda f: (f.line, f.code))
    return findings


def find_markdown_files(root):
    """Collect all .md files under *root*, excluding build and VCS directories that appear
    BELOW root. The exclusion is matched on the path relative to root, so running from inside
    a directory whose name is in EXCLUDE_DIRS (for example a `.worktrees/<name>` checkout)
    still scans that tree's own files, while a nested excluded directory under root is skipped."""
    root = Path(root)
    files = []
    for path in root.rglob("*.md"):
        if any(part in EXCLUDE_DIRS for part in path.relative_to(root).parts):
            continue
        files.append(path)
    return sorted(files)


def collect_targets(paths, repo_root):
    """Expand CLI paths (files or directories) into a sorted list of .md files."""
    md_files = []
    for raw in paths:
        p = Path(raw).resolve()
        if p.is_dir():
            md_files.extend(find_markdown_files(p))
        elif p.suffix.lower() == ".md":
            md_files.append(p)
        else:
            print(f"Skipping non-markdown path: {raw}", file=sys.stderr)
    return sorted(set(md_files))


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Validate Markdown files across the repository.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("paths", nargs="*",
                        help="Files or directories to scan (default: the whole repo).")
    parser.add_argument("--fix", action="store_true",
                        help="Auto-fix AI/non-ASCII characters in place.")
    parser.add_argument("--strict", action="store_true",
                        help="Treat warnings as failures (exit 1) too.")
    parser.add_argument("--style", action="store_true",
                        help="Also run prose-style checks (filler, promo, line refs).")
    parser.add_argument("--no-links", action="store_true",
                        help="Skip link, case, and anchor checks.")
    args = parser.parse_args(argv)

    repo_root = find_repo_root(Path(__file__).parent)
    _ANCHOR_CACHE.clear()

    if args.paths:
        md_files = collect_targets(args.paths, repo_root)
    else:
        md_files = find_markdown_files(repo_root)

    total_errors = 0
    total_warnings = 0
    total_fixed = 0
    files_with_issues = 0

    for md_file in md_files:
        try:
            content = md_file.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            print(f"\n{md_file}\n  ERROR: could not read: {exc}")
            total_errors += 1
            files_with_issues += 1
            continue

        fixed_here = 0
        if args.fix:
            new_content, count = fix_ai_characters(content)
            if count:
                write_text_lf(md_file, new_content)
                content = new_content
                fixed_here = count
                total_fixed += count

        findings = validate_content(
            md_file, content, repo_root, no_links=args.no_links, style=args.style)

        try:
            rel = md_file.relative_to(repo_root)
        except ValueError:
            rel = md_file

        if findings or fixed_here:
            print(f"\n{rel}")
            if fixed_here:
                print(f"  FIXED: {fixed_here}x AI/non-ASCII character(s)")
            for f in findings:
                tag = "ERROR" if f.severity == ERROR else "WARNING"
                print(f"  {tag} line {f.line} [{f.code}]: {f.message}")
            files_with_issues += 1
            total_errors += sum(1 for f in findings if f.severity == ERROR)
            total_warnings += sum(1 for f in findings if f.severity == WARNING)

    print("\n" + "=" * 60)
    parts = [f"Scanned {len(md_files)} file(s)"]
    if total_fixed:
        parts.append(f"{total_fixed} AI char(s) auto-fixed")
    parts.append(f"{total_errors} error(s)")
    parts.append(f"{total_warnings} warning(s)")
    parts.append(f"{files_with_issues} file(s) with issues")
    print(", ".join(parts))

    failed = total_errors > 0 or (args.strict and total_warnings > 0)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
