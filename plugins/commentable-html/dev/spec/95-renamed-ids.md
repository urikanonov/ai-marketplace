## Renamed feature ids (the ledger)

One feature id owns exactly ONE row (`CMH-BUILD-21` enforces it). When issue #904 found ids that
owned two rows each, the row touching the least reader-facing surface was given a free id. A reader
who follows an older `CHANGELOG.md` entry citing the OLD id lands on the row that KEPT it, which
now describes a different behavior, and released changelog history is never edited - so the mapping
lives here instead. This is a bullet list, not a table, deliberately: a table row starting with a
feature id would itself read as a second spec row for that id.

- `CMH-BUILD-13` -> `CMH-BUILD-21` for the `scripts/check_spec_test_refs.py` spec-to-test gate.
  `CMH-BUILD-13` kept the duration-based Playwright shard-balancing behavior, which AGENTS.md,
  `docs/testing-guidelines.md`, and the `tests/00-projects.spec.js` titles all mean by that id.
- `CMH-CONTENT-01` -> `CMH-CONTENT-IO-01`, `CMH-CONTENT-02` -> `CMH-CONTENT-IO-02`,
  `CMH-CONTENT-03` -> `CMH-CONTENT-IO-03`, and `CMH-CONTENT-04` -> `CMH-CONTENT-IO-04` for the
  `tools/authoring/` content round-trip tools (content extract/replace, edit locality, and the
  embedded-comment export). `CMH-CONTENT-01..04` kept the visual content-styling behaviors (section
  cards, tables, badges, the authored TOC), which own that number space up to `CMH-CONTENT-19`. A
  changelog entry citing `CMH-CONTENT-01..04` for the agent review loop means the `-IO-` ids.
- `CMH-DECK-21` -> `CMH-DECK-43` for the deck table-cell hover highlight. `CMH-DECK-21` kept the
  deck chrome project link and Overview/count pill styling, which claimed the id first. A changelog
  entry citing `CMH-DECK-21` for hover smoothness means `CMH-DECK-43`.
