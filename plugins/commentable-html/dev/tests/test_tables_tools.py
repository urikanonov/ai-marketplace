"""Editable-table authoring, validation and transactional cementing."""
import copy
import importlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import _paths


MODEL = {
    "columns": [
        {"id": "task", "label": "Task", "type": "text", "options": [], "default": ""},
        {"id": "state", "label": "State", "type": "choice",
         "options": ["Open", "Done"], "default": "Open"},
    ],
    "rows": [{"id": "r1", "cells": ["  A & <B>\nnext  ", "Open"]}],
}


def payload(before, after, tid="tasks"):
    return {"version": 1, "tables": [
        {"id": tid, "label": "Tasks", "from": before, "to": after}]}


class TablesToolsTests(unittest.TestCase):
    def setUp(self):
        self.common = importlib.import_module("tables_common")
        self.scaffold = importlib.import_module("tables_scaffold")
        self.apply = importlib.import_module("tables_apply")
        self.check = importlib.import_module("validate").check_tables
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "report.html"

    def markup(self, model=None, tid="tasks"):
        return self.scaffold.scaffold(tid, "Tasks", model or MODEL)

    def test_scaffold_escapes_and_roundtrips_exact_text(self):
        model = copy.deepcopy(MODEL)
        model["columns"][0]["label"] = 'Task </script> & "label"'
        model["rows"][0]["cells"][0] = "  </script> & <b>\r\nx\ry  "
        html = self.markup(model)
        self.assertNotIn("</script>", html)
        self.assertIn("&lt;/script&gt;", html)
        expected = copy.deepcopy(model)
        expected["rows"][0]["cells"][0] = "  </script> & <b>\nx\ny  "
        tables = self.common.scan_tables(html)
        self.assertEqual(tables[0]["model"], expected)
        self.assertEqual(self.check(html), ([], []))
        empty = copy.deepcopy(MODEL)
        empty["rows"] = []
        self.assertEqual(self.common.scan_tables(self.markup(empty))[0]["model"], empty)

    def test_numeric_columns_and_widths_roundtrip_and_apply(self):
        model = copy.deepcopy(MODEL)
        model["columns"][0].update(type="number", width=236)
        model["rows"][0]["cells"][0] = "-1.25e2"
        self.assertEqual(self.common.scan_tables(self.markup(model))[0]["model"], model)
        self.assertEqual(self.check(self.markup(model)), ([], []))
        after = copy.deepcopy(model)
        after["columns"][0]["width"] = 310
        after["rows"][0]["cells"][0] = ".75"
        self.path.write_text(self.markup(model), encoding="utf-8")
        self.assertEqual(self.apply.apply_tables(self.path, payload(model, after)), 1)
        self.assertEqual(self.common.scan_tables(self.path.read_text())[0]["model"], after)
        self.assertEqual(self.apply.apply_tables(self.path, payload(model, after)), 0)
        for value in ["\ufeff12", "\u00a0-.25e2\u2029", "\ufeff"]:
            with self.subTest(value=value):
                model["rows"][0]["cells"][0] = value
                self.assertEqual(self.common.scan_tables(self.markup(model))[0]["model"], model)

    def test_numeric_and_width_validation_rejects_invalid_values(self):
        for value in ["money", "$12", "1,000", "NaN", "Infinity", "1e999", "0x12", "\x1c12", "\x8512"]:
            model = copy.deepcopy(MODEL)
            model["columns"][0]["type"] = "number"
            model["rows"][0]["cells"][0] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.markup(model)
        for width in [True, "200", 95, 4097, 200.5, None]:
            model = copy.deepcopy(MODEL)
            model["columns"][0]["width"] = width
            with self.subTest(width=width), self.assertRaises(ValueError):
                self.markup(model)

    def test_schema_rejects_malformed_models(self):
        variants = []
        for field, value in [("columns", []), ("rows", {}), ("extra", True)]:
            m = copy.deepcopy(MODEL)
            m[field] = value
            variants.append(m)
        for field, value in [
                ("id", "__proto__"), ("id", " bad"), ("label", " \n "),
                ("type", "number"), ("options", ["Open", "Open"]),
                ("options", [""]), ("options", "Open"), ("default", "Other")]:
            m = copy.deepcopy(MODEL)
            m["columns"][1][field] = value
            variants.append(m)
        for cells in [["short"], ["task", "Other"], ["task", 3]]:
            m = copy.deepcopy(MODEL)
            m["rows"][0]["cells"] = cells
            variants.append(m)
        for key in ["rows", "columns"]:
            m = copy.deepcopy(MODEL)
            m[key].append(copy.deepcopy(m[key][0]))
            variants.append(m)
        for m in variants:
            with self.subTest(model=m), self.assertRaises(ValueError):
                self.markup(m)
        for tid, label in [("", "Tasks"), ("__proto__", "Tasks"), ("tasks", " ")]:
            with self.assertRaises(ValueError):
                self.scaffold.scaffold(tid, label, MODEL)

    def test_apply_row_column_changes_idempotent_and_preserves_surroundings(self):
        after = copy.deepcopy(MODEL)
        after["columns"].reverse()
        after["columns"].append(
            {"id": "new", "label": "New", "type": "text", "options": [], "default": ""})
        after["rows"] = [{"id": "r2", "cells": ["Done", "  changed & <  ", "new\nvalue"]}]
        prefix = '<!doctype html>\r\n<!-- untouched -->\r\n<p>Keep &amp; exactly</p>\r\n'
        suffix = '\r\n<script>var untouched = "<table>";</script>\r\n'
        self.path.write_bytes((prefix + self.markup() + suffix).encode())
        self.assertEqual(self.apply.apply_tables(self.path, payload(MODEL, after)), 1)
        result = self.path.read_bytes().decode()
        self.assertTrue(result.startswith(prefix))
        self.assertTrue(result.endswith(suffix))
        self.assertEqual(self.common.scan_tables(result)[0]["model"], after)
        self.assertEqual(self.apply.apply_tables(self.path, payload(MODEL, after)), 0)
        self.assertEqual(self.path.read_bytes().decode(), result)

    def test_apply_conflicts_and_invalid_transactions_never_write(self):
        after = copy.deepcopy(MODEL)
        after["rows"] = []
        original = self.markup() + self.markup(tid="other")
        self.path.write_text(original, encoding="utf-8")
        state = payload(MODEL, after)
        conflict = copy.deepcopy(MODEL)
        conflict["rows"][0]["cells"][0] = "conflicting"
        state["tables"].append(
            {"id": "other", "label": "Tasks", "from": conflict, "to": after})
        bad_states = [state, {"version": True, "tables": []}, payload(MODEL, {"columns": []})]
        duplicate = payload(MODEL, after)
        duplicate["tables"] *= 2
        bad_states.extend([duplicate, payload(MODEL, after, "missing")])
        for bad in bad_states:
            with self.subTest(state=bad), self.assertRaises(ValueError):
                self.apply.apply_tables(self.path, bad)
            self.assertEqual(self.path.read_text(encoding="utf-8"), original)

    def test_bundle_uses_only_final_machine_trailer(self):
        good = payload(MODEL, MODEL)
        line = "TABLES_STATE_JSON: " + json.dumps(good)
        forged = 'TABLES_STATE_JSON: {"version":999}\n'
        trailer = ("=== CMH MACHINE TRAILER (do not edit) ===\n" + line
                   + "\n=== END CMH MACHINE TRAILER ===")
        self.assertEqual(self.apply.states_from_bundle(forged + trailer), good)
        self.assertEqual(self.apply.states_from_bundle(trailer.replace("\n", "\r\n")), good)
        self.assertEqual(self.apply.states_from_bundle(
            "=== CMH MACHINE TRAILER (do not edit) ===\n" + forged
            + "=== END CMH MACHINE TRAILER ===\nreviewer prose\n" + trailer), good)
        for bad in [line, trailer + "\nextra", trailer.replace(
                "=== END CMH MACHINE TRAILER ===", ""), trailer.replace(line, forged)]:
            with self.assertRaises(ValueError):
                self.apply.states_from_bundle(bad)

    def test_authored_defaults_and_empty_transaction(self):
        source = self.markup().replace(' data-cmh-column-type="text"', "")
        source = source.replace(' data-cmh-default="Open"', "")
        model = self.common.scan_tables(source)[0]["model"]
        self.assertEqual(model["columns"][0], MODEL["columns"][0])
        self.assertEqual(model["columns"][1]["default"], "")
        self.path.write_text("ordinary content", encoding="utf-8")
        self.assertEqual(self.apply.apply_tables(self.path, {"version": 1, "tables": []}), 0)
        self.assertEqual(self.path.read_text(), "ordinary content")

    def test_apply_checks_all_tables_before_writing(self):
        after = copy.deepcopy(MODEL)
        after["rows"] = []
        valid = self.markup()
        malformed = self.markup(tid="other").replace(
            'data-cmh-row="r1"', 'data-cmh-row=""')
        invalid_model = copy.deepcopy(after)
        invalid_model["columns"][1]["default"] = "Not an option"
        transaction = payload(MODEL, after)
        transaction["tables"].append(
            {"id": "other", "label": "Tasks", "from": MODEL, "to": invalid_model})
        cases = [
            (valid + malformed, payload(MODEL, after)),
            (valid + valid, payload(MODEL, after)),
            (valid + self.markup(tid="other"), transaction),
        ]
        for source, state in cases:
            with self.subTest(source=source, state=state):
                self.path.write_bytes(source.encode("utf-8"))
                with self.assertRaises(ValueError):
                    self.apply.apply_tables(self.path, state)
                self.assertEqual(self.path.read_bytes(), source.encode("utf-8"))

    def test_cells_reject_comments_and_markup(self):
        for cell in ["<!-- preserve me -->plain", "<b>rich</b>", "<br>",
                     "<?processing instruction?>", "<!DOCTYPE html>"]:
            html = self.markup().replace("<td>", "<td>" + cell, 1)
            with self.subTest(cell=cell):
                errors, warnings = self.check(html)
                self.assertTrue(errors or warnings)
                with self.assertRaises(ValueError):
                    self.common.scan_tables(html)
                self.path.write_bytes(html.encode("utf-8"))
                after = copy.deepcopy(MODEL)
                after["rows"] = []
                with self.assertRaises(ValueError):
                    self.apply.apply_tables(self.path, payload(MODEL, after))
                self.assertEqual(self.path.read_bytes(), html.encode("utf-8"))

    def test_caption_allowed_and_preserved_while_other_sections_rejected(self):
        source = self.markup().replace(
            "<thead>", '<caption class="custom">Caption &amp; text<!-- intact --></caption>\n<thead>')
        self.assertEqual(self.check(source), ([], []))
        after = copy.deepcopy(MODEL)
        after["rows"] = []
        self.path.write_bytes(source.encode("utf-8"))
        self.assertEqual(self.apply.apply_tables(self.path, payload(MODEL, after)), 1)
        result = self.path.read_text(encoding="utf-8")
        self.assertIn('<caption class="custom">Caption &amp; text<!-- intact --></caption>', result)
        self.assertEqual(self.common.scan_tables(result)[0]["model"], after)
        for section in ["colgroup", "tfoot"]:
            html = self.markup().replace("<thead>", "<%s></%s><thead>" % (section, section))
            self.assertTrue(any(self.check(html)))
            with self.assertRaises(ValueError):
                self.common.scan_tables(html)

    def test_ordinary_layout_table_ancestor_allowed_but_editable_ownership_rejected(self):
        prefix = '<table class="layout"><tbody><tr><td><!-- layout intact -->'
        suffix = '</td></tr></tbody></table><p>After &amp; unchanged</p>'
        source = prefix + self.markup() + suffix
        self.assertEqual(self.check(source), ([], []))
        after = copy.deepcopy(MODEL)
        after["rows"] = []
        self.path.write_bytes(source.encode("utf-8"))
        self.assertEqual(self.apply.apply_tables(self.path, payload(MODEL, after)), 1)
        result = self.path.read_text(encoding="utf-8")
        self.assertTrue(result.startswith(prefix))
        self.assertTrue(result.endswith(suffix))
        self.assertEqual(self.common.scan_tables(result)[0]["model"], after)
        for owner in ['data-cmh-table="outer"', 'data-cmh-note="n"',
                      'data-cmh-checklist="c"', 'data-cm-widget="w"', 'class="cmh-diff"']:
            with self.subTest(owner=owner):
                with self.assertRaises(ValueError):
                    self.common.scan_tables("<div %s>%s</div>" % (owner, self.markup()))

    def test_implied_tbody_rows_apply_canonical_body_and_preserve_other_bytes(self):
        source = self.markup().replace("<tbody>", "").replace("</tbody>", "")
        source = source.replace(
            "<thead>", '<caption>Keep &amp; caption<!-- exact --></caption>\n<thead>')
        prefix, suffix = '<p>Before &amp; intact</p>\r\n', '\r\n<!-- after intact -->'
        original = prefix + source + suffix
        self.assertEqual(self.check(original), ([], []))
        self.assertEqual(self.common.scan_tables(original)[0]["model"], MODEL)
        after = copy.deepcopy(MODEL)
        after["rows"].append({"id": "r2", "cells": ["  New & <value>  ", ""]})
        self.path.write_bytes(original.encode("utf-8"))
        self.assertEqual(self.apply.apply_tables(self.path, payload(MODEL, after)), 1)
        result = self.path.read_bytes().decode("utf-8")
        self.assertTrue(result.startswith(prefix))
        self.assertTrue(result.endswith(suffix))
        self.assertIn('<caption>Keep &amp; caption<!-- exact --></caption>', result)
        self.assertIn("<tbody>", result)
        self.assertEqual(self.common.scan_tables(result)[0]["model"], after)
        self.assertEqual(self.apply.apply_tables(self.path, payload(MODEL, after)), 0)
        row = '<tr data-cmh-row="extra"><td>Extra</td><td>Open</td></tr>'
        two_rows = source.replace("</tr>\n</table>", "</tr>" + row + "\n</table>")
        expected = copy.deepcopy(MODEL)
        expected["rows"].append({"id": "extra", "cells": ["Extra", "Open"]})
        self.assertEqual(self.common.scan_tables(two_rows)[0]["model"], expected)
        malformed = [
            source.replace("</thead>", "</thead><tbody></tbody>"),
            source.replace("</thead>", "</thead>" + row + "<caption>Split</caption>"),
            source.replace("</thead>", "</thead>" + row.replace("<td>Extra</td>", "")),
            source.replace("</tr>\n</table>", "\n</table>"),
            source.replace("</thead>", "</thead><tbody></tbody><tbody></tbody>"),
        ]
        for html in malformed:
            with self.subTest(html=html), self.assertRaises(ValueError):
                self.common.scan_tables(html)

    def test_caption_rejects_all_descendant_native_tables(self):
        nested = "<table><tbody><tr><td>Nested</td></tr></tbody></table>"
        source = self.markup().replace("<thead>", "<caption>%s</caption><thead>" % nested)
        errors, warnings = self.check(source)
        self.assertTrue(errors or warnings)
        with self.assertRaises(ValueError):
            self.common.scan_tables(source)
        self.path.write_bytes(source.encode("utf-8"))
        after = copy.deepcopy(MODEL)
        after["rows"] = []
        with self.assertRaises(ValueError):
            self.apply.apply_tables(self.path, payload(MODEL, after))
        self.assertEqual(self.path.read_bytes(), source.encode("utf-8"))

    def test_inert_template_copies_do_not_duplicate_live_table_ids(self):
        inert = ('<template id="copy"><!-- inert intact -->' + self.markup()
                 + '<template id="nested">' + self.markup() + "</template></template>")
        self.assertEqual(self.common.scan_tables(inert), [])
        source = inert + "\r\n" + self.markup() + "<!-- live suffix -->"
        self.assertEqual(self.check(source), ([], []))
        tables = self.common.scan_tables(source)
        self.assertEqual([(table["id"], table["model"]) for table in tables], [("tasks", MODEL)])
        after = copy.deepcopy(MODEL)
        after["rows"] = []
        self.path.write_bytes(source.encode("utf-8"))
        self.assertEqual(self.apply.apply_tables(self.path, payload(MODEL, after)), 1)
        result = self.path.read_bytes().decode("utf-8")
        self.assertTrue(result.startswith(inert + "\r\n"))
        self.assertTrue(result.endswith("<!-- live suffix -->"))
        self.assertEqual(self.common.scan_tables(result)[0]["model"], after)
        with self.assertRaises(ValueError):
            self.common.scan_tables(source + self.markup())

    def test_caption_template_contents_are_inert_but_template_node_is_active(self):
        inert = ('<template id="caption-copy"><div data-cmh-note="n">'
                 '<template><div data-cmh-checklist="c" data-cm-widget="w" class="cmh-diff">'
                 '<table><tbody><tr><td colspan="2">Inert</td></tr></tbody></table>'
                 + self.markup() + "</div></template></div></template>")
        caption = "<caption>Caption<!-- keep -->" + inert + "</caption>"
        source = self.markup().replace("<thead>", caption + "\n<thead>")
        self.assertEqual(self.check(source), ([], []))
        self.assertEqual(self.common.scan_tables(source)[0]["model"], MODEL)
        after = copy.deepcopy(MODEL)
        after["rows"] = []
        self.path.write_bytes(source.encode("utf-8"))
        self.assertEqual(self.apply.apply_tables(self.path, payload(MODEL, after)), 1)
        self.assertIn(caption.encode("utf-8"), self.path.read_bytes())
        self.assertEqual(self.common.scan_tables(
            self.path.read_bytes().decode("utf-8"))[0]["model"], after)
        for marker in ['data-cmh-note="active"', 'data-cmh-checklist="active"',
                       'data-cm-widget="active"', 'class="cmh-diff"', 'rowspan="2"']:
            active = source.replace('<template id="caption-copy">',
                                    '<template id="caption-copy" %s>' % marker)
            with self.subTest(marker=marker), self.assertRaises(ValueError):
                self.common.scan_tables(active)
        cell_template = self.markup().replace("<td>", "<td><template>Inert text</template>", 1)
        with self.assertRaises(ValueError):
            self.common.scan_tables(cell_template)

    def test_choice_empty_cells_and_stable_label_renames(self):
        before = copy.deepcopy(MODEL)
        before["rows"][0]["cells"][1] = ""
        before["rows"][0]["cells"][0] = "  text\r\nline  "
        self.path.write_bytes(self.markup(before).encode("utf-8"))
        canonical = copy.deepcopy(before)
        canonical["rows"][0]["cells"][0] = "  text\nline  "
        after = copy.deepcopy(canonical)
        after["columns"][1]["label"] = "Renamed status"
        self.assertEqual(self.apply.apply_tables(self.path, payload(before, after)), 1)
        actual = self.common.scan_tables(self.path.read_text(encoding="utf-8"))[0]["model"]
        self.assertEqual(actual, after)
        self.assertEqual(actual["columns"][1]["id"], "state")
        self.assertEqual(actual["columns"][1]["default"], "Open")
        self.assertEqual(actual["rows"][0]["cells"][1], "")

    def test_validator_diagnoses_invalid_structure_and_ownership(self):
        good = self.markup()
        invalid = [
            good + good,
            good.replace('data-cmh-row="r1"', 'data-cmh-row=""'),
            good.replace("<td>", '<td colspan="2">', 1),
            good.replace("Task</th>", "<b>Task</b></th>"),
            good.replace("Task</th>", "Task<!-- comment --></th>"),
            good.replace("</table>", "<tfoot></tfoot></table>"),
            good.replace("</td>", "<table></table></td>", 1),
            '<div data-cmh-note="n">' + good + "</div>",
            '<div data-cmh-checklist="c">' + good + "</div>",
            '<div data-cm-widget="w">' + good + "</div>",
            good.replace("<table ", '<table data-cmh-note="n" ', 1),
            good.replace("<table ", '<table data-cmh-checklist="c" ', 1),
            good.replace("<table ", '<table data-cm-widget="w" ', 1),
            good.replace("<td>", '<td data-cmh-checklist="c">', 1),
            good.replace("<tbody>", "<tbody><tr><td>wrong</td></tr>"),
            good.replace("</tbody>", ""),
        ]
        for html in invalid:
            with self.subTest(html=html):
                errors, warnings = self.check(html)
                self.assertTrue(errors or warnings)
                self.assertIn("table", " ".join(errors + warnings).lower())
        self.assertEqual(self.check("<table><tr><td>ordinary</td></tr></table>"), ([], []))

    def test_scaffold_and_apply_cli(self):
        model_path = Path(self.temp.name) / "model.json"
        model_path.write_text(json.dumps(MODEL), encoding="utf-8")
        tool = Path(_paths.TOOLS) / "tables"
        command = [sys.executable, str(tool / "tables_scaffold.py"), "--id", "tasks",
                   "--label", "Tasks", "--in", str(model_path), "--out", str(self.path)]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.common.scan_tables(self.path.read_text())[0]["model"], MODEL)
        after = copy.deepcopy(MODEL)
        after["rows"] = []
        result = subprocess.run([sys.executable, str(tool / "tables_apply.py"), str(self.path),
                                 "--state-json", json.dumps(payload(MODEL, after))],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.common.scan_tables(self.path.read_text())[0]["model"], after)
        result = subprocess.run(command[:-2] + ["--out", str(model_path)],
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(model_path.read_text()), MODEL)


if __name__ == "__main__":
    unittest.main()
