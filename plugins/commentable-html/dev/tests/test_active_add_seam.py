#!/usr/bin/env python3
"""Seam guard for the shared single-affordance sentinel (CMH-ANCHOR-01).

The structural-anchor layers (image/mermaid/diff/link/widget/heading) must reveal their floating
Add Comment button ONLY through `setActiveAdd()`, never by assigning the shared `_activeAdd`
sentinel directly with an object literal. A layer that writes `_activeAdd = {...}` on its own
bypasses the mutual-exclusion + innermost-wins logic and silently reintroduces the two-buttons bug
(the exact defect issue #481 fixed) for just that layer, while every existing test stays green.

This test makes the seam a mechanical gate: no partial may contain a direct `_activeAdd = { ... }`
assignment, and the shared helpers must exist. Bypassing the seam fails the build instead of
relying on a code comment.
"""
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402
JS_DIR = os.path.join(_paths.ASSETS, "js")

_PART_RE = re.compile(r"^\d{2}-[a-z0-9-]+\.js$")
# A direct assignment of an object literal to the shared sentinel - the forbidden anti-pattern.
# Matched against a whitespace-collapsed view of each file so a multi-line assignment
# (`_activeAdd =\n{...}`) or a parens-wrapped one (`_activeAdd = ({...})`) cannot slip past a
# naive per-line check.
_DIRECT_ASSIGN_RE = re.compile(r"_activeAdd\s*=\s*\(*\s*\{")
# ANY assignment to the shared sentinel (object literal OR a named variable), including the logical
# compound-assignment forms (`||=`, `&&=`, `??=`), but excluding the equality operators `==` / `===`.
# Assigning a pre-built entry (`const e = {...}; _activeAdd = e;`) would bypass the object-literal
# check above, so ownership of the sentinel is restricted to the two modules that legitimately own it
# (see _SENTINEL_OWNERS).
_ANY_ASSIGN_RE = re.compile(r"_activeAdd\s*(?:\|\||&&|\?\?)?=(?!=)")
# The ONLY partials allowed to assign the shared `_activeAdd` sentinel directly: its home module
# (20-mermaid.js hosts setActiveAdd/clearActiveAdd) and the scroll repositioner (52-hover-bubble.js
# nulls it when the target scrolls out of view). Every structural-anchor LAYER must go through the
# shared helpers, never touch the sentinel itself.
_SENTINEL_OWNERS = frozenset({"20-mermaid.js", "52-hover-bubble.js"})


def _partials():
    return sorted(n for n in os.listdir(JS_DIR)
                  if os.path.isfile(os.path.join(JS_DIR, n)) and _PART_RE.match(n))


def _read(name):
    with open(os.path.join(JS_DIR, name), "r", encoding="utf-8") as fh:
        return fh.read()


class ActiveAddSeamTests(unittest.TestCase):
    def test_no_direct_active_add_object_assignment(self):
        offenders = []
        for name in _partials():
            collapsed = re.sub(r"\s+", " ", _read(name))
            if _DIRECT_ASSIGN_RE.search(collapsed):
                offenders.append(name)
        self.assertEqual(
            offenders, [],
            "A structural-anchor layer assigns the shared `_activeAdd` sentinel with an object "
            "literal directly instead of calling setActiveAdd(); this bypasses the single-affordance "
            "mutual exclusion (CMH-ANCHOR-01) and reintroduces the two-buttons bug. Route it through "
            "setActiveAdd({el, btn, position, clear}). Offending file(s): " + ", ".join(offenders))

    def test_shared_helpers_exist(self):
        blob = "\n".join(_read(n) for n in _partials())
        self.assertIn("function setActiveAdd(", blob,
                      "the shared setActiveAdd() helper must exist (CMH-ANCHOR-01)")
        self.assertIn("function clearActiveAdd(", blob,
                      "the shared clearActiveAdd() helper must exist so a layer's hide path clears "
                      "the shared sentinel (CMH-ANCHOR-01)")

    def test_only_owner_modules_assign_the_sentinel(self):
        # Defense against a named-variable bypass: `const e = {...}; _activeAdd = e;` evades the
        # object-literal check but still skips setActiveAdd()'s mutual exclusion. Only the sentinel's
        # owner modules may assign it at all; every layer must route through the shared helpers.
        offenders = []
        for name in _partials():
            if name in _SENTINEL_OWNERS:
                continue
            collapsed = re.sub(r"\s+", " ", _read(name))
            if _ANY_ASSIGN_RE.search(collapsed):
                offenders.append(name)
        self.assertEqual(
            offenders, [],
            "A structural-anchor layer assigns the shared `_activeAdd` sentinel directly (even via a "
            "named variable) instead of calling setActiveAdd()/clearActiveAdd(); this bypasses the "
            "single-affordance mutual exclusion (CMH-ANCHOR-01). Only " + ", ".join(sorted(_SENTINEL_OWNERS)) +
            " may own the sentinel. Offending file(s): " + ", ".join(offenders))

    def test_every_revealing_layer_clears_on_hide(self):
        # Each layer that reveals its button through setActiveAdd() must also clear the shared sentinel
        # via clearActiveAdd() on its hide path, so a dismissed inner affordance never keeps
        # suppressing an enclosing layer (the stale-ghost fix). Pins the clearActiveAdd() calls so a
        # future edit that drops one fails the build rather than silently regressing.
        missing = []
        for name in _partials():
            body = _read(name)
            # Ignore BOTH helper DEFINITIONS (their `function setActiveAdd(` / `function
            # clearActiveAdd(` headers) so the owner module 20-mermaid.js is judged on its real CALL
            # sites too - dropping mermaid's own hide-path clearActiveAdd() call must fail the build,
            # not be masked by the definition header it also hosts.
            calls = re.sub(r"function\s+(?:setActiveAdd|clearActiveAdd)\s*\(", "", body)
            if "setActiveAdd(" in calls and "clearActiveAdd(" not in calls:
                missing.append(name)
        self.assertEqual(
            missing, [],
            "A layer reveals its Add Comment button via setActiveAdd() but never calls "
            "clearActiveAdd() on its hide path, so its dismissed affordance can leave a stale "
            "sentinel that suppresses an enclosing layer (CMH-ANCHOR-01). Add clearActiveAdd(btn) to "
            "its hide timer. Offending file(s): " + ", ".join(missing))

    def test_guard_catches_evasion_patterns(self):
        # The guard must catch reformatted bypasses, not just the canonical one-liner, so it is a
        # real mechanical gate. Each sample is collapsed the same way the file check collapses.
        def hit(s):
            return bool(_DIRECT_ASSIGN_RE.search(re.sub(r"\s+", " ", s)))
        for bad in ["_activeAdd = { el: x }", "_activeAdd={el:x}",
                    "_activeAdd = ({ el: x })", "_activeAdd =\n  { el: x }",
                    "_activeAdd  =  (  { el: x } )"]:
            self.assertTrue(hit(bad), "guard should flag a direct assignment: %r" % bad)
        for ok in ["_activeAdd = entry;", "_activeAdd = null;",
                   "setActiveAdd({ el: x });", "clearActiveAdd(btn);"]:
            self.assertFalse(hit(ok), "guard should allow the sanctioned form: %r" % ok)

    def test_any_assign_regex_distinguishes_assignment_from_equality(self):
        # The ownership guard's regex must catch every assignment form but never trip on the equality
        # operators the helpers themselves use (`_activeAdd.btn === btn`, `_activeAdd === x`).
        def hit(s):
            return bool(_ANY_ASSIGN_RE.search(re.sub(r"\s+", " ", s)))
        for bad in ["_activeAdd = e", "_activeAdd = { el: x }", "_activeAdd=null",
                    "_activeAdd = makeEntry()", "_activeAdd ||= e", "_activeAdd &&= e",
                    "_activeAdd ??= e"]:
            self.assertTrue(hit(bad), "ownership guard should flag an assignment: %r" % bad)
        for ok in ["_activeAdd === entry", "_activeAdd.btn === btn",
                   "if (_activeAdd && _activeAdd.btn === btn)", "prev === _activeAdd"]:
            self.assertFalse(hit(ok), "ownership guard must not flag equality: %r" % ok)


if __name__ == "__main__":
    unittest.main()
