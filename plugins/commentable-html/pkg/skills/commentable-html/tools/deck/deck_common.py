#!/usr/bin/env python3
"""Shared helpers for the commentable-html deck tools.

Deterministic slide-id minting and HTML-text escaping used by deck_scaffold.py,
pptx_to_fragment.py, and deck_validate.py so all three agree on the same contract
(see references/deck-contract.md).
"""
import hashlib
import html
import re

SLIDE_ID_RE = re.compile(r"^slide-[0-9a-f]{8}(-[0-9]+)?$")


def normalize_text(text: str) -> str:
    """Collapse whitespace and lowercase, for stable content hashing."""
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def slide_id(text: str, taken) -> str:
    """A stable slide id: slide-<8 hex of sha256(normalized text)>, with a numeric
    suffix on collision within the same deck. ``taken`` is a set of ids already used
    (mutated: the returned id is added to it)."""
    digest = hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()[:8]
    base = f"slide-{digest}"
    candidate = base
    n = 2
    while candidate in taken:
        candidate = f"{base}-{n}"
        n += 1
    taken.add(candidate)
    return candidate


def esc(text: str) -> str:
    """Escape text for safe insertion as HTML text content (quotes included)."""
    return html.escape(text or "", quote=True)
