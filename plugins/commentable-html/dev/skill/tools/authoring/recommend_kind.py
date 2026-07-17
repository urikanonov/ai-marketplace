#!/usr/bin/env python3
"""Recommend a commentable-html --kind from filename and content signals."""
import argparse
from dataclasses import dataclass
import os
import re
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tools/ root
import _toolpath  # noqa: E402
_toolpath.ensure()

RECOMMENDED_KINDS = ("report", "plan", "slides")
ALL_KINDS = ("report", "plan", "slides", "board", "generic")

_FILENAME_HINTS = (
    ("slides", re.compile(r"(^|[-_\s.])(slides?|deck|presentation|pitch|talk)([-_\s.]|$)", re.I)),
    ("plan", re.compile(
        r"(^|[-_\s.])(plan|proposal|strategy|roadmap|migration|design|implementation|architecture|spec)"
        r"([-_\s.]|$)", re.I)),
    ("report", re.compile(
        r"(^|[-_\s.])(report|review|audit|analysis|summary|findings|postmortem|incident|status)"
        r"([-_\s.]|$)", re.I)),
)
_DIFF_FENCE_RE = re.compile(
    r"(?im)(^```diff\b|<pre\b[^>]*(?:cmh-diff|language-diff)[^>]*>|^diff --git\b)")
_HUNK_RE = re.compile(r"(?m)^@@\s+-\d+(?:,\d+)?\s+\+\d+(?:,\d+)?\s+@@")
_HR_RE = re.compile(r"(?i)<hr\b[^>]*>")
_HTML_H1_RE = re.compile(r"(?is)<h1\b[^>]*>.*?</h1>")
_MD_H1_RE = re.compile(r"(?m)^#\s+\S")
_HTML_TABLE_RE = re.compile(r"(?is)<table\b.*?</table>")
_MD_TABLE_RE = re.compile(r"(?m)^\s*\|.*\|\s*$")
_COMPARISON_WORD_RE = re.compile(r"\b(option|pros?|cons?|trade-?offs?|decision|recommendation|comparison)\b", re.I)
_CALLOUT_RE = re.compile(
    r"(?is)(class=[\"'][^\"']*\bcmh-callout\b[^\"']*[\"']|"
    r"<blockquote\b[^>]*>.*?\b(recommendation|decision|risk|note|warning|consideration)\b.*?</blockquote>|"
    r"^\s*>\s*(?:\*\*)?(?:recommendation|decision|risk|note|warning|consideration)\b)",
    re.M,
)


@dataclass(frozen=True)
class Evidence:
    kind: str
    score: int
    message: str


@dataclass(frozen=True)
class KindRecommendation:
    kind: Optional[str]
    scores: dict
    evidence: tuple


def _add(evidence, scores, kind, score, message):
    scores[kind] += score
    evidence.append(Evidence(kind, score, "%s (+%d for %s)" % (message, score, kind)))


def _score_filename(filename, scores, evidence):
    if not filename:
        return
    base = os.path.basename(filename).lower()
    for kind, pattern in _FILENAME_HINTS:
        if pattern.search(base):
            _add(evidence, scores, kind, 2, "filename hint %r" % base)
            return


def _table_looks_comparative(text):
    tables = _HTML_TABLE_RE.findall(text)
    if tables:
        return any(len(set(m.group(1).lower() for m in _COMPARISON_WORD_RE.finditer(table))) >= 3
                   for table in tables)
    rows = [line for line in text.splitlines() if _MD_TABLE_RE.match(line)]
    return any(len(set(m.group(1).lower() for m in _COMPARISON_WORD_RE.finditer(row))) >= 3
               for row in rows[:3])


def _score_content(text, scores, evidence):
    if _DIFF_FENCE_RE.search(text):
        _add(evidence, scores, "report", 4, "content signal: diff fence or diff block")
    if _HUNK_RE.search(text):
        _add(evidence, scores, "report", 3, "content signal: @@ hunk")

    hr_count = len(_HR_RE.findall(text))
    if hr_count >= 3:
        _add(evidence, scores, "slides", 4, "content signal: %d hr divider(s)" % hr_count)
    h1_count = len(_HTML_H1_RE.findall(text)) + len(_MD_H1_RE.findall(text))
    if h1_count >= 3:
        _add(evidence, scores, "slides", 3, "content signal: %d-heading h1 cadence" % h1_count)

    if _table_looks_comparative(text):
        _add(evidence, scores, "plan", 4, "content signal: comparison table")
    if _CALLOUT_RE.search(text):
        _add(evidence, scores, "plan", 2, "content signal: callout")


def recommend_kind(text, filename=None):
    scores = {kind: 0 for kind in RECOMMENDED_KINDS}
    evidence = []
    _score_filename(filename, scores, evidence)
    _score_content(text, scores, evidence)
    top = max(scores.values())
    if top <= 0:
        return KindRecommendation(None, scores, tuple(evidence))
    winners = [kind for kind in RECOMMENDED_KINDS if scores[kind] == top]
    kind = winners[0] if len(winners) == 1 else None
    return KindRecommendation(kind, scores, tuple(evidence))


def mismatch_warning(chosen_kind, recommendation):
    if not chosen_kind or not recommendation.kind:
        return None
    chosen = chosen_kind.strip().lower()
    if chosen == recommendation.kind:
        return None
    return "recommend_kind: warning: --kind %s differs from recommended --kind %s" % (
        chosen, recommendation.kind)


def warning_for_kind(chosen_kind, text, filename=None):
    return mismatch_warning(chosen_kind, recommend_kind(text, filename=filename))


def _read_content(path):
    if path == "-":
        return sys.stdin.read(), None
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read(), path


def _print_recommendation(recommendation):
    if recommendation.kind:
        print("Recommended --kind: %s" % recommendation.kind)
    else:
        print("No confident --kind recommendation.")
    print("Evidence:")
    if recommendation.evidence:
        for item in recommendation.evidence:
            print("- " + item.message)
    else:
        print("- no report, plan, or slides signals found")


def main(argv):
    parser = argparse.ArgumentParser(
        prog="recommend_kind.py",
        description="Recommend a commentable-html --kind from filename and content signals.",
    )
    parser.add_argument("content", help="content fragment or HTML file to inspect, or '-' for stdin")
    parser.add_argument("--filename", default=None,
                        help="optional logical filename hint; defaults to the content path")
    parser.add_argument("--kind", choices=ALL_KINDS, default=None,
                        help="chosen kind to compare with the recommendation; advisory only")
    args = parser.parse_args(argv[1:])

    try:
        text, path_hint = _read_content(args.content)
    except OSError as exc:
        sys.stderr.write("recommend_kind: cannot read content: %s\n" % exc)
        return 1
    filename = args.filename or path_hint
    recommendation = recommend_kind(text, filename=filename)
    _print_recommendation(recommendation)
    warning = mismatch_warning(args.kind, recommendation)
    if warning:
        sys.stderr.write(warning + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
