# tests

Development-only regression suites for the commentable-html layer.

- `test_*.py` files use Python `unittest` for build, validation, and runtime helper coverage.
- `*.spec.js` files use Playwright for browser behavior.
- `fixtures/` contains generated edge-case documents checked by `fixtures/generate.mjs --check`.

Run from `dev/`; see `../README.md` for setup and commands.
