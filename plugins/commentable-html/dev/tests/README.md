# tests

Development-only regression suites for the commentable-html layer.

- `test_*.py` files use Python `unittest` for build, validation, and runtime helper coverage.
- `*.spec.js` files use Playwright for browser behavior.
- `fixtures/` contains generated edge-case documents checked by `fixtures/generate.mjs --check`.
- `fixtures/highlight/` holds the syntax-highlighter golden fixtures: one realistic `<lang>.sample`
  per supported language plus its pre-annotated `<lang>.html` output. `test_highlight_golden.py`
  re-runs the highlighter and diffs against these; regenerate after intentional changes with
  `python build_highlight_fixtures.py` (samples live in `highlight_samples.py`).

Run from `dev/`; see `../README.md` for setup and commands.
