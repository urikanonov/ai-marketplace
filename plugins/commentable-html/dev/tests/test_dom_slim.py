#!/usr/bin/env python3
"""CMH-SIZE-02/03: tools/authoring/dom_slim.py stops a finished document storing a checklist
item's identity twice, and every reading of the document agrees on what is left."""
import os
import re
import shutil
import sys
import tempfile
import unittest

import _paths  # noqa: E402
sys.path.insert(0, _paths.TOOLS)
import checklist_apply  # noqa: E402
import dom_slim  # noqa: E402
import finalize  # noqa: E402
import validate  # noqa: E402


def _checklist_instances(html):
    """The validator's own view of the checklists in `html`, for the parity assertions."""
    sys.path.insert(0, os.path.join(_paths.TOOLS, "validate"))
    from checks import checklist as check_mod  # noqa: E402
    p = check_mod._ChecklistParser()
    p.feed(html)
    p.close()
    return p.instances

# The gate the dedupe runs behind: an EXECUTABLE script, OUTSIDE the content root, that mentions
# the pointer - which is what a real embedded runtime looks like.
LAYER = '<script>/* layer */ var alias = "%s";</script>' % dom_slim.ITEM_ALIAS_ATTR


def doc(inner, head="", runtime=True):
    return ('<!DOCTYPE html>\n<html><head>' + head + (LAYER if runtime else "")
            + '</head><body>\n<main id="commentRoot">\n' + inner
            + '\n</main>\n</body></html>\n')


LIST_CHECKLIST = """
<div class="cmh-checklist" data-cmh-checklist="release">
  <ul>
    <li data-rdc-id="backend" data-cmh-item="backend">Backend
      <ul>
        <li data-rdc-id="mig" data-cmh-item="mig" data-cmh-state="check">Migrations applied</li>
        <li data-rdc-id="load" data-cmh-item="load" data-cmh-state="cross">Load test green</li>
      </ul>
    </li>
    <li data-rdc-id="docs" data-cmh-item="docs" data-cmh-state="blank">Docs updated</li>
  </ul>
</div>
"""

TABLE_CHECKLIST = """
<table class="cmh-checklist" data-cmh-checklist="audit">
  <tbody>
    <tr data-rdc-id="net" data-cmh-item="net"><td></td><td>Network</td></tr>
    <tr data-rdc-id="fw" data-rdc-parent="net" data-cmh-item="fw" data-cmh-parent="net" data-cmh-state="check"><td></td><td>Firewall</td></tr>
    <tr data-rdc-id="tls" data-rdc-parent="net" data-cmh-item="tls" data-cmh-parent="net" data-cmh-state="cross"><td></td><td>TLS</td></tr>
  </tbody>
</table>
"""


class IdentityDedupeTests(unittest.TestCase):
    """CMH-SIZE-02: the identity is stored once and DERIVED, not written on every row."""

    # A second, perfectly ordinary checklist. Every refusal case runs BESIDE it and asserts this
    # one was still trimmed, so a refusal test can never pass merely because the transform
    # stopped running - which is also what "the attribute survived" looks like.
    CONTROL = ('<div class="cmh-checklist" data-cmh-checklist="control"><ul>'
               '<li data-ctl-id="p" data-cmh-item="p" data-cmh-state="blank">P</li>'
               '<li data-ctl-id="q" data-cmh-item="q" data-cmh-state="check">Q</li>'
               '</ul></div>')

    def _refuse(self, inner):
        """Slim `inner` beside the control; assert the control WAS trimmed and return the output."""
        out, changed, _stats = dom_slim.slim(doc(inner + self.CONTROL))
        self.assertTrue(changed, "the control checklist should still have been trimmed")
        self.assertIn('data-cmh-checklist="control" data-cmh-item-attr="data-ctl-id"', out)
        self.assertNotIn('data-cmh-item="p"', out)
        return out

    def test_the_duplicated_item_id_is_dropped_and_the_container_names_its_source(self):
        out, changed, stats = dom_slim.slim(doc(LIST_CHECKLIST))
        self.assertTrue(changed)
        self.assertEqual(stats["identity"], 4)
        self.assertNotIn("data-cmh-item=", out)
        self.assertIn('data-cmh-item-attr="data-rdc-id"', out)
        for iid in ("backend", "mig", "load", "docs"):
            self.assertIn('data-rdc-id="%s"' % iid, out)

    def test_the_parent_link_is_derived_from_its_own_named_attribute(self):
        out, _changed, _stats = dom_slim.slim(doc(TABLE_CHECKLIST))
        self.assertIn('data-cmh-parent-attr="data-rdc-parent"', out)
        self.assertNotIn("data-cmh-parent=", out)
        self.assertIn('data-rdc-parent="net"', out)

    def test_an_alias_that_disagrees_on_one_row_is_refused(self):
        out = self._refuse(LIST_CHECKLIST.replace('data-rdc-id="load"', 'data-rdc-id="LOAD"'))
        self.assertIn('data-cmh-item="load"', out)
        self.assertNotIn('data-cmh-item-attr="data-rdc-id"', out)

    def test_an_alias_carried_by_a_non_item_inside_the_container_is_refused(self):
        out = self._refuse(
            LIST_CHECKLIST.replace("<ul>", '<ul><li data-rdc-id="stray">stray</li>', 1))
        self.assertNotIn('data-cmh-item-attr="data-rdc-id"', out)
        self.assertIn('data-cmh-item="backend"', out)

    def test_an_EMPTY_alias_on_a_non_item_still_refuses_the_dedupe(self):
        # The runtime selects on `[alias]`, which an EMPTY value satisfies, so the guard tests
        # PRESENCE. A truthiness test let this through and promoted the stray to an item.
        out = self._refuse(LIST_CHECKLIST.replace("<ul>", '<ul><li data-rdc-id="">stray</li>', 1))
        self.assertNotIn('data-cmh-item-attr="data-rdc-id"', out)
        self.assertIn('data-cmh-item="backend"', out)

    def test_a_container_that_already_carries_an_EMPTY_alias_is_left_alone(self):
        # The worst failure this tool could have: reading the pointer by truthiness treated
        # `data-cmh-item-attr=""` as absent, so every row was stripped of its id while the
        # container rewrite was refused (the name was already on it) - a document with no
        # identity at all and nothing to derive it from.
        out = self._refuse(LIST_CHECKLIST.replace(
            'data-cmh-checklist="release"', 'data-cmh-checklist="release" data-cmh-item-attr=""'))
        for iid in ("backend", "mig", "load", "docs"):
            self.assertIn('data-cmh-item="%s"' % iid, out)

    def test_a_container_that_already_carries_a_valid_alias_is_left_alone(self):
        once, _c, _s = dom_slim.slim(doc(LIST_CHECKLIST))
        again, changed, _s2 = dom_slim.slim(once)
        self.assertEqual(again, once)
        self.assertFalse(changed)

    def test_a_parent_alias_present_where_no_parent_is_authored_is_refused(self):
        out, _changed, _stats = dom_slim.slim(doc(TABLE_CHECKLIST.replace(
            '<tr data-rdc-id="net" data-cmh-item="net">',
            '<tr data-rdc-id="net" data-rdc-parent="root" data-cmh-item="net">')))
        self.assertIn('data-cmh-item-attr="data-rdc-id"', out)
        self.assertNotIn('data-cmh-parent-attr="', out)
        self.assertIn('data-cmh-parent="net"', out)

    def test_a_self_closing_container_still_owns_the_rows_after_it(self):
        # A browser IGNORES `/>` on a non-void HTML element, so a `<div data-cmh-checklist/>`
        # stays OPEN and the rows after it belong to THAT checklist. Treating it as closed handed
        # them to the enclosing list, so this reader would strip them under the outer pointer
        # while the runtime keyed them under the inner one.
        inner = ('<div class="cmh-checklist" data-cmh-checklist="outer">'
                 '<div data-cmh-checklist="inner"/><ul>'
                 '<li data-rdc-id="a" data-cmh-item="a" data-cmh-state="blank">A</li>'
                 '<li data-rdc-id="b" data-cmh-item="b" data-cmh-state="blank">B</li>'
                 '</ul></div>')
        scan = dom_slim._scan(doc(inner))
        owners = [dom_slim._checklist_container(n).attrs.get("data-cmh-checklist")
                  for n in scan.nodes if "data-cmh-item" in n.attrs]
        self.assertEqual(owners, ["inner", "inner"])
        # The two Python readers must agree with that, or a cemented state lands on the wrong row.
        items = checklist_apply._scan_items(doc(inner))
        self.assertEqual([i["container_id"] for i in items], ["inner", "inner"])
        instances = {i["id"]: len(i["items"]) for i in _checklist_instances(doc(inner))}
        self.assertEqual(instances.get("inner"), 2)
        self.assertEqual(instances.get("outer"), 0)

    def test_a_cmh_attribute_is_never_treated_as_the_alias(self):
        out = self._refuse(
            '<div class="cmh-checklist" data-cmh-checklist="x"><ul>'
            '<li data-cmh-item="check" data-cmh-state="check">A</li>'
            '<li data-cmh-item="cross" data-cmh-state="cross">B</li></ul></div>')
        self.assertNotIn('data-cmh-item-attr="data-cmh-state"', out)
        self.assertIn('data-cmh-item="check"', out)

    def test_a_nested_checklist_container_is_not_an_item_of_the_outer_one(self):
        # The runtime scopes items with `closest("[data-cmh-checklist]") === container`, which is
        # ancestor-or-SELF, so a nested container belongs to itself. Recording it as an outer
        # item made a ghost row that shifted every positional key after it.
        nested = ('<div class="cmh-checklist" data-cmh-checklist="outer" '
                  'data-cmh-item-attr="data-rdc-id"><ul>'
                  '<li data-rdc-id="a" data-cmh-state="blank">A</li>'
                  '<li data-rdc-id="b" data-cmh-state="blank">B</li>'
                  '<div class="cmh-checklist" data-cmh-checklist="inner" data-rdc-id="ghost">'
                  '<ul><li data-rdc-id="i1" data-cmh-state="blank">I1</li></ul></div>'
                  '<li data-rdc-id="c" data-cmh-state="blank">C</li>'
                  '</ul></div>')
        items = checklist_apply._scan_items(doc(nested))
        self.assertEqual([i["key"] for i in items if i["container_id"] == "outer"],
                         ["a", "b", "c"])

    def test_an_empty_id_nested_checklist_is_still_an_ownership_boundary(self):
        # `data-cmh-checklist=""` is a boundary to the runtime (`closest` tests PRESENCE) but was
        # invisible to a truthiness test here, so the inner rows were treated as the OUTER
        # checklist's and stripped while only the outer container got the pointer.
        out = self._refuse(
            '<div class="cmh-checklist" data-cmh-checklist="outer"><ul>'
            '<li data-rdc-id="a" data-cmh-item="a" data-cmh-state="blank">A</li>'
            '<li data-rdc-id="b" data-cmh-item="b" data-cmh-state="blank">B</li></ul>'
            '<div data-cmh-checklist=""><ul>'
            '<li data-rdc-id="i1" data-cmh-item="i1" data-cmh-state="blank">Inner</li>'
            '</ul></div></div>')
        self.assertIn('data-cmh-item="i1"', out)

    def test_a_checklist_whose_row_cannot_be_rewritten_is_left_whole(self):
        # All-or-nothing: committing the pointer while a row keeps its own id is the same
        # non-atomic shape that produced the identity loss above.
        out = self._refuse(LIST_CHECKLIST.replace(
            '<li data-rdc-id="mig"', '<li\r data-rdc-id="mig"'))
        self.assertNotIn('data-cmh-item-attr="data-rdc-id"', out)
        self.assertIn('data-cmh-item="backend"', out)

    def test_a_container_a_browser_would_have_closed_is_refused(self):
        # This reader nests by TAG; a browser REPAIRS. A `<p>` holding block children is already
        # closed when the browser reaches them, so the browser gives those rows to the OUTER
        # checklist and keys them differently. Acting on that disagreement strips identity from
        # rows the runtime then keys POSITIONALLY, orphaning saved state.
        out = self._refuse(
            '<div data-cmh-checklist="outer"><p data-cmh-checklist="inner">'
            '<div data-cmh-item="x" data-ns-id="x" data-cmh-state="blank">Ex</div>'
            '<div data-cmh-item="y" data-ns-id="y" data-cmh-state="blank">Why</div>'
            '</p></div>')
        self.assertIn('data-cmh-item="x"', out)
        self.assertIn('data-cmh-item="y"', out)


class RuntimeGateTests(unittest.TestCase):
    """CMH-SIZE-02: the dedupe only fires when the document's own runtime can derive the id."""

    def test_a_document_whose_runtime_cannot_read_the_pointer_is_never_trimmed(self):
        # A NonShareable document loads its runtime from a sibling file this tool can neither see
        # nor version; a stale companion would read the trimmed rows as unidentified and fall
        # back to POSITIONAL keys, silently orphaning stored checklist state.
        out, changed, stats = dom_slim.slim(doc(LIST_CHECKLIST, runtime=False))
        self.assertEqual(stats["identity"], 0)
        self.assertIn('data-cmh-item="backend"', out)
        self.assertFalse(changed)

    def test_an_inert_script_mentioning_the_pointer_is_not_evidence(self):
        # A `text/plain` island never executes, so a mention inside it says nothing about what
        # will read the document.
        head = '<script type="text/plain">data-cmh-item-attr="data-rdc-id"</script>'
        out, changed, _stats = dom_slim.slim(doc(LIST_CHECKLIST, head=head, runtime=False))
        self.assertIn('data-cmh-item="backend"', out)
        self.assertFalse(changed)

    def test_an_authored_example_inside_the_content_root_is_not_evidence(self):
        # A document DOCUMENTING this feature is content, not a runtime - the exact shape
        # CMH-SIZE-01 records as having been destroyed once by an unscoped scan.
        inner = ('<script>var example = "data-cmh-item-attr";</script>' + LIST_CHECKLIST)
        out, changed, _stats = dom_slim.slim(doc(inner, runtime=False))
        self.assertIn('data-cmh-item="backend"', out)
        self.assertFalse(changed)

    def test_the_shipped_runtime_really_does_satisfy_the_gate(self):
        # The gate only means anything if a REAL built document passes it, so pin it against the
        # shipped template rather than against this file's own stub.
        with open(_paths.TEMPLATE, encoding="utf-8", newline="") as fh:
            scan = dom_slim._scan(fh.read())
        self.assertIsNotNone(scan, "the shipped template no longer parses")
        self.assertTrue(dom_slim._runtime_reads_the_alias(scan),
                        "the shipped runtime no longer mentions %s, so the dedupe would silently "
                        "stop firing on every real document" % dom_slim.ITEM_ALIAS_ATTR)


class DerivedIdentityParityTests(unittest.TestCase):
    """CMH-SIZE-03: every reading of a slimmed document resolves the SAME identity."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="cmh-dom-slim-")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _write(self, name, text):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        return path

    def test_checklist_apply_cements_a_state_by_the_derived_key(self):
        path = self._write("slim.html", dom_slim.slim(doc(TABLE_CHECKLIST))[0])
        self.assertEqual(
            checklist_apply.apply_states(path, {"audit": {"tls": "question"}},
                                         warn=lambda _m: None), 1)
        with open(path, encoding="utf-8") as fh:
            after = fh.read()
        self.assertIn('data-rdc-id="tls"', after)
        self.assertIn('data-cmh-state="question"', after)

    def test_checklist_apply_resolves_the_same_keys_before_and_after_the_trim(self):
        # The positive control for the parity claim: the SAME state map must reach the SAME items
        # in the authored document and in the trimmed one.
        authored = self._write("authored.html", doc(TABLE_CHECKLIST))
        slimmed = self._write("slim.html", dom_slim.slim(doc(TABLE_CHECKLIST))[0])
        for path in (authored, slimmed):
            self.assertEqual(
                checklist_apply.apply_states(path, {"audit": {"fw": "question"}},
                                             warn=lambda _m: None), 1, path)
            with open(path, encoding="utf-8") as fh:
                self.assertIn('data-cmh-state="question"', fh.read())

    def test_the_validator_resolves_the_derived_parent_link(self):
        errors, warnings = validate.check_checklists(dom_slim.slim(doc(TABLE_CHECKLIST))[0])
        self.assertEqual(errors, [])
        self.assertEqual([w for w in warnings if "checklist" in w.lower()], [])

    def test_the_validator_still_sees_a_duplicate_id_through_the_alias(self):
        inner = ('<div class="cmh-checklist" data-cmh-checklist="a" data-cmh-item-attr="data-rdc-id">'
                 '<ul><li data-rdc-id="x">A</li><li data-rdc-id="x">B</li></ul></div>')
        _errors, warnings = validate.check_checklists(doc(inner))
        self.assertTrue(any('duplicate data-cmh-item id "x"' in w for w in warnings), warnings)

    def test_a_malformed_alias_name_never_reaches_a_selector(self):
        inner = ('<div class="cmh-checklist" data-cmh-checklist="a" data-cmh-item-attr="x&quot;]">'
                 '<ul><li data-cmh-item="q">A</li></ul></div>')
        _errors, warnings = validate.check_checklists(doc(inner))
        self.assertEqual([w for w in warnings if "checklist" in w.lower()], [])


class SafetyTests(unittest.TestCase):
    """The transform fails safe: no content root, no parse, no change."""

    def test_a_document_with_nothing_to_trim_is_returned_byte_identical(self):
        html = doc("<p>Just prose.</p>")
        out, changed, _stats = dom_slim.slim(html)
        self.assertEqual(out, html)
        self.assertFalse(changed)

    def test_a_document_without_a_content_root_is_left_alone(self):
        html = "<!DOCTYPE html><html><head>" + LAYER + "</head><body>" + LIST_CHECKLIST + "</body></html>"
        out, changed, _stats = dom_slim.slim(html)
        self.assertEqual(out, html)
        self.assertFalse(changed)

    def test_a_checklist_outside_the_content_root_is_never_trimmed(self):
        html = doc(LIST_CHECKLIST.replace('="release"', '="inside"')).replace(
            "</body>", LIST_CHECKLIST.replace('="release"', '="outside"') + "</body>")
        out, changed, stats = dom_slim.slim(html)
        self.assertTrue(changed)
        self.assertEqual(stats["identity"], 4)  # the in-root one only
        self.assertIn('data-cmh-checklist="outside"', out)
        self.assertEqual(out.count('data-cmh-item-attr="data-rdc-id"'), 1)

    def test_nothing_inside_foreign_content_is_ever_rewritten(self):
        # The shared tokenizer folds attribute names to lower case, so re-serializing a tag
        # inside <svg> would turn `viewBox` into `viewbox` and break the rendering.
        html = doc('<div><svg viewBox="0 0 10 10">'
                   '<text data-cmh-item="a" pathLength="9">Hi</text></svg></div>')
        out, changed, _stats = dom_slim.slim(html)
        self.assertEqual(out, html)
        self.assertFalse(changed)
        self.assertIn("viewBox", out)
        self.assertIn("pathLength", out)

    def test_slim_is_idempotent(self):
        once, _c1, _s1 = dom_slim.slim(doc(LIST_CHECKLIST + TABLE_CHECKLIST))
        twice, changed, _s2 = dom_slim.slim(once)
        self.assertEqual(twice, once)
        self.assertFalse(changed)

    def test_every_shipped_example_settles_in_one_pass(self):
        seen = 0
        for name in sorted(os.listdir(_paths.EXAMPLES)):
            if not name.endswith(".html"):
                continue
            with open(os.path.join(_paths.EXAMPLES, name), encoding="utf-8", newline="") as fh:
                html = fh.read()
            once, _c, _s = dom_slim.slim(html)
            twice, changed, _s2 = dom_slim.slim(once)
            seen += 1
            with self.subTest(example=name):
                self.assertEqual(twice, once)
                self.assertFalse(changed)
        self.assertTrue(seen, "no shipped example was scanned")


class MeasuredWinTests(unittest.TestCase):
    """CMH-SIZE-02: the trim removes real bytes from a document shaped like the surveyed corpus.

    The shipped examples are small and hand-authored, so they carry none of the duplication this
    targets and trim to zero - a suite built only on them would pass with the transform broken.
    This builds the shape #1250 actually measured and asserts a real reduction.
    """

    ROWS = 200

    def _corpus_document(self):
        rows = ['    <tr data-rdc-id="row-%d" data-rdc-parent="net" data-cmh-item="row-%d" '
                'data-cmh-parent="net" data-cmh-state="blank"><td></td><td>Control %d</td></tr>'
                % (i, i, i) for i in range(self.ROWS)]
        return doc('<table class="cmh-checklist" data-cmh-checklist="audit">\n  <tbody>\n'
                   '    <tr data-rdc-id="net" data-cmh-item="net"><td></td><td>Network</td></tr>\n'
                   + "\n".join(rows) + '\n  </tbody>\n</table>')

    def test_a_corpus_shaped_document_gets_measurably_smaller(self):
        html = self._corpus_document()
        out, changed, stats = dom_slim.slim(html)
        self.assertTrue(changed)
        self.assertEqual(stats["identity"], self.ROWS + 1)
        saved = len(html) - len(out)
        # Each row sheds `data-cmh-item="row-N"` and `data-cmh-parent="net"`; the container gains
        # two pointers. The floor is deliberately far below the measured saving, so the test pins
        # a REAL reduction without pinning an exact byte count.
        self.assertGreater(saved, 30 * self.ROWS,
                           "expected a real reduction, saved only %d bytes" % saved)

    def test_the_corpus_document_keeps_every_item_and_parent_link(self):
        out, _changed, _stats = dom_slim.slim(self._corpus_document())
        self.assertIn('data-cmh-item-attr="data-rdc-id"', out)
        self.assertIn('data-cmh-parent-attr="data-rdc-parent"', out)
        for i in range(self.ROWS):
            self.assertIn('data-rdc-id="row-%d"' % i, out)
        self.assertEqual(out.count('data-rdc-parent="net"'), self.ROWS)
        _errors, warnings = validate.check_checklists(out)
        self.assertEqual([w for w in warnings if "checklist" in w.lower()], [])


class FinalizePhaseTests(unittest.TestCase):
    """CMH-SIZE-02: the trim is a finalize phase, and --no-slim opts out of it."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="cmh-dom-slim-fin-")
        self.path = os.path.join(self.dir, "doc.html")
        with open(self.path, "w", encoding="utf-8", newline="") as fh:
            fh.write(doc(LIST_CHECKLIST))

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _read(self):
        with open(self.path, encoding="utf-8", newline="") as fh:
            return fh.read()

    def test_finalize_runs_the_trim_by_default(self):
        result = finalize.finalize(self.path, run_highlight=False, run_wrap_sections=False,
                                   run_stats=False, run_normalize=False)
        self.assertIn("dom-slim", [name for name, _status in result["steps"]])
        self.assertIn('data-cmh-item-attr="data-rdc-id"', self._read())

    def test_no_slim_leaves_the_document_alone(self):
        result = finalize.finalize(self.path, run_highlight=False, run_wrap_sections=False,
                                   run_stats=False, run_normalize=False, run_slim=False)
        self.assertNotIn("dom-slim", [name for name, _status in result["steps"]])
        self.assertIn('data-cmh-item="backend"', self._read())


class RuntimeParityTests(unittest.TestCase):
    """The runtime derives identity from the same names, validated the same way."""

    def _runtime(self):
        with open(os.path.join(_paths.ASSETS, "js", "36-checklist.js"), encoding="utf-8") as fh:
            return fh.read()

    def test_the_runtime_reads_the_container_attributes_this_tool_writes(self):
        src = self._runtime()
        self.assertIn('"' + dom_slim.ITEM_ALIAS_ATTR + '"', src)
        self.assertIn('"' + dom_slim.PARENT_ALIAS_ATTR + '"', src)

    def test_every_implementation_spells_the_alias_pattern_identically(self):
        # Three readers and one writer; the claim that they shared a pattern was untrue (the
        # writer was stricter), and nothing would have caught a future divergence.
        m = re.search(r"CMH_CL_ALIAS_RE\s*=\s*/([^/]+)/", self._runtime())
        self.assertIsNotNone(m, "the runtime no longer declares CMH_CL_ALIAS_RE")
        spellings = {"runtime": m.group(1), "dom_slim": dom_slim._ALIAS_NAME_RE.pattern}
        for label, path in (
                ("checklist_apply", os.path.join(_paths.TOOLS, "checklist", "checklist_apply.py")),
                ("validator", os.path.join(_paths.TOOLS, "validate", "checks", "checklist.py"))):
            with open(path, encoding="utf-8") as fh:
                found = re.search(r'_ALIAS_NAME_RE = re\.compile\(r"([^"]+)"\)', fh.read())
            self.assertIsNotNone(found, "%s no longer declares _ALIAS_NAME_RE" % label)
            spellings[label] = found.group(1)
        self.assertEqual(len(set(spellings.values())), 1,
                         "alias pattern spellings differ: %r" % spellings)

    def test_the_tool_only_ever_writes_a_name_that_pattern_accepts(self):
        for name in ("data-rdc-id", "data-x", "data-a-b-c"):
            self.assertTrue(dom_slim._ALIAS_NAME_RE.match(name), name)
        for name in ("data-", "dataX", "data-A", 'data-x"]', "data-x_y"):
            with self.subTest(name=name):
                self.assertFalse(dom_slim._ALIAS_NAME_RE.match(name), name)


class AbandonedTransformTests(unittest.TestCase):
    """CMH-SIZE-03: the two transforms that were tried and removed stay removed.

    A class hoist and an `aria-label` trim were both implemented, measured at zero effect on
    every shipped document, and found to change something a reader can observe. Each is easy to
    re-add by reflex, so the absence is pinned rather than left to memory.
    """

    def _body(self):
        with open(os.path.join(_paths.TOOLS, "authoring", "dom_slim.py"), encoding="utf-8") as fh:
            # Everything after the module docstring, which is where the history is recorded.
            return fh.read().split('"""', 2)[2]

    def test_no_class_is_hoisted_and_no_selector_is_rewritten(self):
        cells = "".join('<td class="rdc-n">%d</td>' % i for i in range(8))
        html = doc("<table><tbody><tr>" + cells + "</tr></tbody></table>",
                   head="<style>.rdc-n { color: red; }</style>")
        out, changed, _stats = dom_slim.slim(html)
        self.assertEqual(out, html)
        self.assertFalse(changed)

    def test_an_aria_label_is_never_trimmed(self):
        # Removing one empties the accessible name on every element whose implicit role does not
        # take its name from content - measured in Chromium on li, p, ul, dd, label and more.
        for tag in ("li", "p", "div", "span", "nav", "section", "button", "a"):
            with self.subTest(tag=tag):
                html = doc('<%s aria-label="Alpha">Alpha</%s>' % (tag, tag))
                out, changed, _stats = dom_slim.slim(html)
                self.assertEqual(out, html)
                self.assertFalse(changed)

    def test_a_title_is_never_trimmed(self):
        html = doc('<p title="Hello there">Hello there</p>')
        out, changed, _stats = dom_slim.slim(html)
        self.assertEqual(out, html)
        self.assertFalse(changed)

    def test_the_source_carries_no_leftover_machinery(self):
        body = self._body()
        for token in ("data-cmh-cls", "aria-label", "_plan_labels", "> *"):
            with self.subTest(token=token):
                self.assertNotIn(token, body)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="cmh-dom-slim-cli-")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_check_reports_without_writing(self):
        path = os.path.join(self.dir, "doc.html")
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(doc(LIST_CHECKLIST))
        self.assertEqual(dom_slim.main(["dom_slim.py", path, "--check"]), 0)
        with open(path, encoding="utf-8", newline="") as fh:
            self.assertIn('data-cmh-item="backend"', fh.read())

    def test_a_missing_file_is_an_error_not_a_crash(self):
        self.assertEqual(
            dom_slim.main(["dom_slim.py", os.path.join(self.dir, "nope.html")]), 1)


if __name__ == "__main__":
    unittest.main()
