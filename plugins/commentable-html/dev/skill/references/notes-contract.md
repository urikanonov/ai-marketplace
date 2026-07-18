# Editable notes-field contract

An editable notes field turns a single element into a plain-text `<textarea>` a reviewer can type into.
The field has an authored baseline; an edit is tracked as a minimal `localStorage` delta, surfaces as a
per-note change card, and travels back to the agent through the Copy-all bundle so the text can be
cemented into the source HTML. It mirrors the layered checklist, differing only in that the tracked
value is free text instead of a four-state cycle.

## Author markup

A notes field is any container element carrying `data-cmh-note="<id>"`. Its authored inner text is the
baseline. The element must contain text only (no child elements), must not be a void element, and must
not nest inside another notes field or inside a checklist / diff / widget / deck substrate.

- `data-cmh-note="<id>"` - the note id. It is the storage sub-key, the Copy-all heading, and the
  `notes_apply.py` target, so keep it unique per document.
- `data-cmh-note-label="..."` - an optional friendly title for the change card (defaults to the id).
- `data-cmh-note-multiline="true"` - an optional flag to default the field to multi-line (the reviewer
  can still toggle it either way).
- `data-cmh-note-foldable="true"` - an optional flag that makes the note a disclosure: a `+`/`-` toggle on
  the header line reveals or hides the field on the line below. A foldable note starts collapsed only when
  it is empty; a note with content starts expanded.

```html
<div class="cmh-note" data-cmh-note="risk-summary"
     data-cmh-note-label="Reviewer risk summary">No blocking risks identified yet.</div>
```

Do not hand-write the attributes; generate the markup with
`python tools/notes/notes_scaffold.py --id risk-summary --label "Reviewer risk summary" --text "..."`
(add `--multiline` to default to a multi-line field).

## The canonical text model

One normalizer is shared byte-for-byte by the runtime and `tools/notes/notes_apply.py`: line endings
are normalized to LF and the outer whitespace is trimmed; internal newlines and spaces are preserved.
The baseline is `normalize(authored textContent)`, and an override is stored only when
`normalize(current)` differs from it. An override that equals the baseline (for example after a prior
apply baked the same text) is pruned at load time, so an exported or cemented file always reopens with
no pending change.

## Runtime behavior

- **Editable field.** The element becomes `cm-skip` and `cmh-note-ready` and hosts a `<textarea>` seeded
  with the current text, a label chip, and a single/multi-line toggle button. Because it is `cm-skip`,
  selecting or typing in it never creates a highlight comment, and its text is excluded from the comment
  offset system (it is set up before offset restoration, like the diff layer).
- **Foldable disclosure.** A `data-cmh-note-foldable` note gains a `+`/`-` toggle on the header line that
  reveals or hides the field below. It starts collapsed only when empty; the fold state is session-only,
  evaluated once at load (a manual collapse sticks and is never re-opened by a later render), and a
  collapsed note that still holds content is badged so hidden text stays discoverable. The collapse is
  presentation only: it never enters `localStorage`, `NOTES_STATE_JSON`, or the exported source.
- **Persistence.** Only changed notes are stored, as `{id:text}` under `COMMENT_KEY + "::note"`; editing
  a note back to its baseline prunes its entry.
- **Change card.** Each changed note shows one non-comment card in the sidebar (placed by document
  order) with a from/to preview, a jump button, and a reset button that reverts that note to its
  authored baseline. It is not counted as a comment, and it is searchable by its label and text.
- **Clear.** The global Clear all comments also reverts every changed note to its authored baseline.
- **Badge.** An unsaved note edit flips the document badge to Not portable until the file is re-exported.
- **Copy all.** The bundle gains a `## Note "<id>"` human-readable section with the from/to text; the
  machine-readable `NOTES_STATE_JSON: {...}` line is emitted only inside the single, final
  `=== CMH MACHINE TRAILER (do not edit) ===` block (never inline in the per-note section), so a forged
  `NOTES_STATE_JSON` line inside an untrusted reviewer note cannot be mistaken for the real state.
- **Export.** Every export (Portable / Offline / Plain / Standalone) bakes each note's current text into
  its element via `textContent` (never `innerHTML`), so the exported file opens with no pending change and
  reviewer text can never inject markup.

## Cementing edits into the source (the agent step)

When the reviewer pastes a Copy-all bundle back, cement the text into the source HTML deterministically:

```
python tools/notes/notes_apply.py source.html --from-bundle bundle.txt   # or: - for stdin
python tools/notes/notes_apply.py source.html --state-json '{"risk-summary":"One blocker."}'
```

It rewrites each named note element's inner content with the HTML-escaped text, is idempotent, preserves
the file's newline style, fills an empty element, and skips unknown ids. Run
`python tools/validate/validate.py --strict` afterward.

## Validation

`validate.py` (a no-op for a notes-free document) warns - and, under `--strict`, fails - on a duplicate
`data-cmh-note` id, an empty id, a nested note, a void-element note, a note that contains child elements,
and a note nested inside a checklist / diff / widget / deck substrate.
