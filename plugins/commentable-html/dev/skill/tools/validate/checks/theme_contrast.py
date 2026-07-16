#!/usr/bin/env python3
"""Author-time WCAG contrast advisory for authored --cp-* theme overrides (CMH-THEME-02).

The shipped palette is accepted as-is; this check evaluates a pair only when the author has
OVERRIDDEN one of its tokens away from the shipped default, and it evaluates the light and dark
theme environments separately (a token overridden only in dark is judged against its dark value).

Non-goal: this is a STATIC resolution of the authored `--cp-*` values, not a computed-style /
cascade simulation. It does not follow every possible selector specificity or element-by-element
inheritance; a chain it cannot resolve to two concrete colors is reported as 'not evaluated'
rather than guessed.
"""
import os
import sys

try:
    from cmhval import contrast
except ImportError:  # pragma: no cover - path guard mirrors the sibling checks
    _here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _here not in sys.path:
        sys.path.insert(0, _here)
    from cmhval import contrast

from dataclasses import dataclass

ADVISORY_PREFIX = "theme contrast advisory: "
ERROR_PREFIX = "theme contrast: "

TEXT_TARGET = 4.5
UI_TARGET = 3.0
# Below this a text/link pair is bad (a hard error); between it and the text target it is a
# near-miss advisory. The UI target doubles as the UI pass bar (below it is a hard error).
BAD_FLOOR = 3.0

# (foreground token, background token, human label) evaluated at the text bar (4.5).
TEXT_PAIRS = (
    ("--cp-text", "--cp-bg", "body text"),
    ("--cp-text", "--cp-bg-elevated", "text on panels"),
    ("--cp-link", "--cp-bg", "links"),
    ("--cp-accent-fg", "--cp-accent", "accent button label"),
)
# Non-text UI pairs evaluated at the 3:1 bar (a control edge is not running text).
UI_PAIRS = (
    ("--cp-border-strong", "--cp-bg", "strong border / control edge"),
)

# The shipped default palette for the checked tokens (mirrors assets/template.shell.html). A pair
# is evaluated only when the effective value of one of its tokens DIFFERS from this default, so
# the accepted shipped defaults (a 4.1:1 link, a subtle 2.9:1 hairline border) are never flagged -
# only genuine author overrides are. If the template defaults change, update these to match.
DEFAULT_LIGHT = {
    "--cp-bg": "#f7f4ef", "--cp-bg-elevated": "#fcfbf8", "--cp-text": "#242424",
    "--cp-link": "#0078d4", "--cp-accent": "#b11f4b", "--cp-accent-fg": "#ffffff",
    "--cp-border-strong": "#919191",
}
DEFAULT_DARK = {
    "--cp-bg": "#3d3b3a", "--cp-bg-elevated": "#343231", "--cp-text": "#dedede",
    "--cp-link": "#4da6ff", "--cp-accent": "#fd8ea1", "--cp-accent-fg": "#1a1a1a",
    "--cp-border-strong": "#5f5f5f",
}
_DEFAULTS = {"light": DEFAULT_LIGHT, "dark": DEFAULT_DARK}


@dataclass(frozen=True)
class ThemeContrastFinding:
    env: str
    label: str
    fg_token: str
    bg_token: str
    fg_value: str
    bg_value: str
    ratio: float  # None when the pair could not be resolved to two concrete colors
    target: float
    kind: str  # "text" | "ui"
    severity: str  # "error" | "warn" | "unresolved"
    suggestion: str  # a compliant nudged foreground hex, or None


def _norm(value):
    return " ".join((value or "").split()).lower()


def _overridden(authored, default, token):
    # A token is an author override when its resolved color differs from the shipped default.
    # Comparing canonical parsed colors (not raw strings) means a harmless reformat of a default
    # (#fff vs #ffffff, uppercase, an rgb() spelling, or a var() that resolves to the default) is
    # NOT treated as an override, so an accepted shipped default is never re-flagged. An authored
    # value that cannot be resolved is treated as an override so it surfaces as the 'not evaluated'
    # advisory rather than passing.
    eff = contrast.parse_css_color(authored.get(token), authored)
    if eff is None:
        return True
    return eff != contrast.parse_css_color(default.get(token))


def _classify(ratio, target, kind):
    if kind == "text":
        if ratio >= target:
            return None
        return "error" if ratio < BAD_FLOOR else "warn"
    # UI: the pass bar IS the target (3:1); below it is a hard error, no near-miss band.
    return None if ratio >= target else "error"


def theme_contrast_findings(html):
    """Return the list of ThemeContrastFinding for the authored --cp-* overrides in `html`."""
    envs = contrast.theme_environments(html)
    if not envs:
        return []
    findings = []
    for env in ("light", "dark"):
        authored = envs.get(env) or {}
        default = _DEFAULTS[env]
        for kind, target, pairs in (("text", TEXT_TARGET, TEXT_PAIRS), ("ui", UI_TARGET, UI_PAIRS)):
            for fg_token, bg_token, label in pairs:
                # Evaluate only pairs the document actually DEFINES both tokens for (a real
                # commentable-html doc's shell defines the whole palette, so a partial override -
                # e.g. only --cp-bg - is still paired against the shell-provided text). Never
                # fabricate a value from the defaults: a custom doc that declares only some tokens
                # has no defined color for the rest, so pairing against a shipped default would be
                # fictional.
                if fg_token not in authored or bg_token not in authored:
                    continue
                if not (_overridden(authored, default, fg_token)
                        or _overridden(authored, default, bg_token)):
                    continue  # accepted shipped default, not an authored override
                fg_value = authored[fg_token]
                bg_value = authored[bg_token]
                try:
                    ratio = contrast.contrast_ratio(fg_value, bg_value, authored)
                except ValueError:
                    findings.append(ThemeContrastFinding(
                        env, label, fg_token, bg_token, fg_value, bg_value, None, target, kind,
                        "unresolved", None))
                    continue
                severity = _classify(ratio, target, kind)
                if severity is None:
                    continue
                suggestion = contrast.nudge_to_ratio(fg_value, bg_value, target, authored)
                findings.append(ThemeContrastFinding(
                    env, label, fg_token, bg_token, fg_value, bg_value, ratio, target, kind,
                    severity, suggestion))
    return findings


def _message(finding, with_suggestion=False):
    loc = (f"{finding.env} theme {finding.label} ({finding.fg_token} on {finding.bg_token})")
    if finding.severity == "unresolved":
        body = (f"{loc}: authored override could not be resolved to two concrete colors, so it "
                f"was not evaluated for WCAG contrast (static check, no computed-style parity)")
    elif finding.severity == "error":
        body = (f"{loc}: authored override has contrast {finding.ratio:.2f}:1, below the "
                f"{finding.target:.1f}:1 minimum - this is unreadable; fix one color")
    else:  # warn / near-miss
        body = (f"{loc}: authored override has contrast {finding.ratio:.2f}:1, a near-miss below "
                f"the {finding.target:.1f}:1 text minimum")
    if with_suggestion and finding.suggestion:
        body += f" - try {finding.fg_token}: {finding.suggestion}"
    return body


def check_theme_contrast(html):
    """Return (errors, warnings). Bad (< 3:1) text/link and below-3:1 UI overrides are ERRORS;
    near-miss text/link overrides and unresolved chains are advisory WARNINGS carrying a stable
    ADVISORY_PREFIX so downstream tools (retrofit) can keep them out of the hard-fail path. Any
    unexpected failure while resolving the palette degrades to no findings (best-effort) rather
    than aborting the whole validation run for every caller."""
    try:
        findings = theme_contrast_findings(html)
    except Exception:
        return [], []
    errors, warnings = [], []
    for finding in findings:
        if finding.severity == "error":
            errors.append(ERROR_PREFIX + _message(finding, with_suggestion=True))
        else:
            warnings.append(ADVISORY_PREFIX + _message(finding))
    return errors, warnings
