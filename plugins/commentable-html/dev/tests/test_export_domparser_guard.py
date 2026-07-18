#!/usr/bin/env python3
"""Static source guard: DOMParser round-trip call sites never take comment-data fields.

CMH-EXP-14: the whole-document DOMParser -> outerHTML round-trip in the export and
apply-state paths is safe only because comment/state data never enters it as markup.
This test locks that invariant at source level: every parseFromString() call site feeds
only the trusted document `html` string, never a comment note, quote, author, or any
other user-supplied field. It also pins the set of partials that contain DOMParser so a
new call site in an unexpected partial triggers a review rather than silently landing.
"""
import os
import re
import sys
import unittest

import _paths

ASSETS_JS = os.path.join(_paths.ASSETS, "js")

# Comment data fields from the comment schema that must never appear in parseFromString args.
_COMMENT_FIELDS = (
    "c.note", "c.quote", "c.author", "c.before", "c.after",
    ".note", ".quote", ".author",
)

# All current call sites feed the trusted document string: either String(html ...) directly, or a
# local `src` that is itself assigned from String(html ...) (e.g. 84-section-review.js).
_ALLOWED_ARG_RE = re.compile(r"^(?:String\(html\b|src$)")

# Captures the first argument of a .parseFromString(...) call.
_PARSE_CALL_RE = re.compile(r"\.parseFromString\(([^,]+),")


def _partials():
    names = sorted(
        n for n in os.listdir(ASSETS_JS)
        if n.endswith(".js") and re.match(r"^\d{2}-", n)
    )
    return [os.path.join(ASSETS_JS, n) for n in names]


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class DomParserRoundTripGuardTests(unittest.TestCase):

    def test_domparser_call_sites_never_take_comment_fields(self):
        """parseFromString arg must not reference a comment data field (CMH-EXP-14)."""
        violations = []
        for path in _partials():
            src = _read(path)
            if "DOMParser" not in src:
                continue
            name = os.path.basename(path)
            for m in _PARSE_CALL_RE.finditer(src):
                arg = m.group(1).strip()
                for field in _COMMENT_FIELDS:
                    if field in arg:
                        line_no = src[: m.start()].count("\n") + 1
                        violations.append(
                            "%s:%d: arg contains comment field %r: %r" % (name, line_no, field, arg)
                        )
        self.assertEqual(
            violations, [],
            "DOMParser round-trip received comment-data field(s):\n" + "\n".join(violations),
        )

    def test_domparser_call_sites_use_the_trusted_html_variable(self):
        """parseFromString must be fed only the trusted `html` doc string (CMH-EXP-14)."""
        bad = []
        for path in _partials():
            src = _read(path)
            if "DOMParser" not in src:
                continue
            name = os.path.basename(path)
            for m in _PARSE_CALL_RE.finditer(src):
                arg = m.group(1).strip()
                if not _ALLOWED_ARG_RE.search(arg):
                    line_no = src[: m.start()].count("\n") + 1
                    bad.append(
                        "%s:%d: unexpected arg (expected String(html...)), got: %r" % (name, line_no, arg)
                    )
        self.assertEqual(
            bad, [],
            "DOMParser round-trip uses unexpected source:\n" + "\n".join(bad),
        )

    def test_domparser_present_only_in_expected_partials(self):
        """DOMParser must only appear in the known export/apply partials (CMH-EXP-14).

        A new call site in an unexpected partial invalidates the containment invariant
        and must be reviewed before merging.
        """
        expected = frozenset({
            "36-checklist.js",
            "37-notes.js",
            "65-export-portable.js",
            "68-export-offline.js",
            "84-section-review.js",
        })
        found = {os.path.basename(p) for p in _partials() if "DOMParser" in _read(p)}
        unexpected = found - expected
        missing = expected - found
        self.assertEqual(
            unexpected,
            set(),
            "DOMParser found in unexpected partial(s) - review for round-trip safety: %s"
            % sorted(unexpected),
        )
        self.assertEqual(
            missing,
            set(),
            "Expected DOMParser partial(s) no longer contain DOMParser - update expected set: %s"
            % sorted(missing),
        )


if __name__ == "__main__":
    unittest.main()
