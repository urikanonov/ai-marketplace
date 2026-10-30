# Editable tables contract

Opt in a native table with `data-cmh-table="stable-id"` and a nonblank
`data-cmh-table-label="Label"`. Ordinary tables are unaffected. Author the marker only;
the runtime adds its own `cm-skip` editing controls.

## Contents

- [Authoring rules](#authoring-rules)
- [Canonical model and transaction](#canonical-model-and-transaction)
- [Reviewer controls and title comments](#reviewer-controls-and-title-comments)
- [Scaffold and cement tools](#scaffold-and-cement-tools)

```html
<table data-cmh-table="tasks" data-cmh-table-label="Tasks">
<thead><tr>
<th data-cmh-column="task">Task</th>
<th data-cmh-column="status" data-cmh-column-type="choice"
    data-cmh-options='["Open","Done"]' data-cmh-default="Open">Status</th>
</tr></thead>
<tbody><tr data-cmh-row="r1"><td>Investigate</td><td>Open</td></tr></tbody>
</table>
```

## Authoring rules

- Table ids are unique document-wide. Column ids and row ids are unique within their
  respective table namespaces. All ids match `[A-Za-z0-9][A-Za-z0-9_.:-]*`.
- Exactly one direct `thead` contains one `tr` of `th` elements, and exactly one
  direct `tbody` contains `tr` elements containing `td` elements. A direct `caption`
  is allowed and preserved by apply; other direct children, including `colgroup`
  and `tfoot`, are rejected. Use explicit closing tags. At least one data column
  is required; zero body rows are valid.
- A contiguous group of direct body `tr` siblings after `thead` may omit its
  `tbody` wrapper, matching the browser's implied body. Apply emits an explicit
  `tbody` when that table changes, preserving bytes outside the replaced
  header/body sections. Do not mix direct rows with explicit body sections or
  split them with another section; a zero-row table still needs an explicit `tbody`.
- Every row has exactly one cell per column. Header labels and cells contain text
  only, including entities and newlines; no comments, rich content, nested tables, spans or
  `tfoot`. Header labels and the table label must not be blank. Duplicate labels
  are allowed.
- Do not overlap editable tables with notes, checklists, widgets or diff ownership,
  either on the table itself, inside it or around it.
- An ordinary layout-table ancestor is allowed; an editable-table ancestor is not.
  No active descendant native table is allowed anywhere in an editable table, including
  inside its caption.
- Inert `template` contents are excluded from table discovery and descendant
  ownership/structure checks, matching browser DOM traversal. Copies inside nested
  templates do not duplicate live table ids. A template in a caption is preserved
  verbatim by apply. The template element itself remains an active child: ownership
  markers on it are still rejected, as is a template inside a plain-text cell.
- `data-cmh-column-type` defaults to `text`. Text and number columns have no options and an
  empty default; choice-only attributes on those headers are ignored.
- A `number` column accepts blank or signed ASCII decimals/scientific notation whose numeric value
  is finite. Preserve exact text, including whitespace. Currency, grouped numbers, hexadecimal,
  NaN and Infinity are invalid. Explicit number sorting compares numeric values.
- Optional `data-cmh-width` is a digit-only integer CSS-pixel width in 96..4096. Omitting it uses
  automatic layout. Widths are model data, not merely view preferences.
- A `choice` column requires a JSON array of unique nonblank string options.
  Option spelling, whitespace and ordering are significant. Its default is empty
  unless authored, and otherwise must equal an option. A choice cell may be empty
  or exactly one of its options.
- Text normalization changes CRLF and CR to LF only. Leading/trailing whitespace,
  internal repeated spaces and newlines remain meaningful.

The authoring validator's `check_tables` reports malformed opt-in tables as warnings;
`tools/validate/validate.py --strict` escalates them. Ordinary tables produce no table
diagnostics.

## Canonical model and transaction

The scaffold input is exactly a model with `columns` and `rows`:

```json
{
  "columns": [
    {"id":"task","label":"Task","type":"text","options":[],"default":""},
    {"id":"status","label":"Status","type":"choice","options":["Open","Done"],"default":"Open"}
  ],
  "rows": [{"id":"r1","cells":["Investigate","Open"]}]
}
```

All five column fields and both row fields are required. A column may additionally have an integer
`width` in 96..4096. No other extra fields, duplicate
ids, invalid choice values or mismatched row widths are accepted. This model covers
row and column insertion, removal, reordering, labels, types, defaults and cell edits.

Copy all emits `TABLES_STATE_JSON:` in its final machine trailer, with this schema:

```json
{"version":1,"tables":[{"id":"tasks","label":"Tasks","from":{"columns":[],"rows":[]},"to":{"columns":[],"rows":[]}}]}
```

The empty column arrays above are schema placeholders, not valid models: replace each
with a complete canonical baseline/edited model. Only changed tables appear in
`tables`; an empty `tables` array is valid. `label` identifies the authored table and
must still match. Each transaction has unique table ids.

## Reviewer controls and title comments

Rows have compact trash buttons. The row-number and remove-action columns use only
their content width. A vertical three-dot header menu offers Rename, Insert before,
Insert after and Remove; Escape or clicking outside closes it. Populated deletion
requires confirmation. Undo/Redo restore edits and structure within the session;
their hover/focus tooltips describe the next operation, including a pending cell edit.
Toolbar and menu actions have decorative icons without changing accessible names.
Boundary + inserts before the target model row; bottom New appends. Both clear view sorting and
focus the new row. Drag a header border or use its Left/Right keys to resize; Escape cancels a
drag. Choose Autofit width or double-click the border to fit current values/header within the
viewport. Widths are cumulative changes and participate in Undo/Redo, persistence and export.

Drag a data-column grip with mouse/touch, use Left/Right while its grip is focused,
or choose Move column left/right. Number and row-action columns stay fixed.
Reordering moves column metadata and each row's matching cell together, preserves
stable title anchors and the active row sort, and is tracked in the cumulative
model. Undo/Redo, persistence and exports carry the order. Escape, cancelled,
outside and same-position drops do not create an order change.

Sort chevrons match ordinary tables. Data columns use numeric comparison when all
nonblank values are numeric, otherwise case-insensitive natural comparison. The `#`
column sorts canonical model row numbers; those numbers move with their rows.
Sorting is view-only and cycles ascending, descending, then model order.

Click a column title, or focus it and press Enter/Space, to leave a normal review
comment. Its `anchorType` is `table-column`, with `tableId`, `columnId` and the
original title in `quote`. It has no prose offsets and does not claim widget ids.
Threads remain anchored through rename, insert, sort, reload and HTML export.
Removing a column preserves its thread as an unavailable anchor; Undo reattaches it.
Do not reuse a removed column id for a different meaning when authoring revisions.
Copy all, Markdown and print identify both the table and column.
Each cell also has a hover/focus comment icon. Its `anchorType` is `table-cell`, with
`tableId`, `rowId`, `columnId` and the original value in `quote`. These are whole-cell anchors,
not prose offsets. Replies, search, deletion, Copy all, Markdown, print and section review retain
the precise row context. Removing a target preserves an unavailable thread; Undo reattaches it.
Orphan comment row/column ids remain reserved on reopen; never reuse an id for a different meaning.
Cell edits still use the one cumulative table-change card, separate from explicit cell threads.

## Scaffold and cement tools

Run from the skill root:

```bash
python tools/tables/tables_scaffold.py --id tasks --label "Tasks" --in model.json --out table.html
python tools/tables/tables_scaffold.py --id tasks --label "Tasks" --in -
python tools/tables/tables_apply.py report.html --from-bundle bundle.txt
python tools/tables/tables_apply.py report.html --from-bundle -
python tools/tables/tables_apply.py report.html --state-json '{"version":1,"tables":[]}'
```

Scaffold reads a canonical JSON model (`--in -` reads stdin), escapes every text and
attribute value, and emits an HTML fragment to stdout unless `--out` is specified.
It refuses an output path aliasing its input. It never writes scripts or runtime
controls.

Apply accepts only the final closed machine trailer, with no trailing non-whitespace
content, and exactly one `TABLES_STATE_JSON` line inside it. Forged state lines and
trailers earlier in reviewer prose are ignored. `--state-json` is an explicit
alternative for an agent that already has the transaction.

Apply validates the entire transaction and all authored opt-in tables before writing.
For every named table, a current model equal to `from` is replaced by `to`; equality
with `to` is an idempotent no-op; anything else is a conflict. Missing or duplicate
tables and malformed models reject the whole transaction without writing. Changed
table header/body sections are rendered canonically; captions, outer start/end tags,
content between sections and all content outside those tables remain byte-for-byte
unchanged. Keep custom presentation and unrelated comments outside the editable
header/body sections. Replacement markup follows
the source's predominant newline style. The shared crash-safe atomic writer performs
one file replacement only after every table passes.

Apply performs table-contract validation only; it does not run the whole-document
validator or refresh the validated-content stamp. After cementing, run
`python tools/authoring/finalize.py report.html --strict` before handoff, or
`python tools/validate/validate.py --strict report.html` when no assembly transforms
are needed. A strict-clean pass refreshes the stamp for the current document.

Both CLIs return 0 for success/no-op, 1 for invalid input or I/O errors, and 2 for
argument-usage errors. `tables_apply.py --quiet` suppresses its change summary.

Python callers may use `tables_scaffold.scaffold(id, label, model)`,
`tables_apply.states_from_bundle(text)`, and `tables_apply.apply_tables(path, payload)`.
The last returns the number of tables changed and raises `ValueError` on a conflict.
