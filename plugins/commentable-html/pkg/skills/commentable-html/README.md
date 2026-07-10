# commentable-html

A Copilot skill that turns any standalone HTML document into an **inline-comment
code-review surface**. Drop a small, namespaced CSS/JS layer into a page and a
reviewer can select text (or a mermaid node), leave comments, and hand them back
to the agent as a compact markdown bundle. The agent marks each comment handled in
the file and it is pruned on the next reload.

This README is an orientation recap. The authoritative per-generation instructions
are in **`SKILL.md`**; the maintainer build/test guide is in **`docs/DEVELOPMENT.md`**.

## Features

- **Inline comments on text.** Select any text, add a comment; the selection is
  highlighted and anchored by character offsets so it survives reload. Anchoring is
  robust across nested inline elements, HTML entities, Unicode/emoji, and RTL runs.
- **Mermaid node comments.** Hover a diagram node and comment it; the node is ringed
  and the comment is anchored by (diagram index, node key).
- **Code-aware comments.** Comments on `<pre>/<code>` are tagged as code and copied
  back as fenced blocks so indentation and newlines survive paste-back.
- **Code-review diffs.** A `<pre class="cmh-diff">` unified diff renders into a colored
  review view with a **side-by-side / inline** toggle (persisted). Diff lines are
  commentable via a per-line "Add Comment" button; the comment is anchored structurally
  so it survives the layout toggle, reload, copy, and Save.
- **Sidebar + floating toolbar.** A comments panel lists every comment with edit /
  delete / jump actions; a minimal floating toolbar (Copy all, count, Show/Hide, and
  a `...` overflow menu) stays out of the document. The toolbar hides while the panel
  is open.
- **Copy all.** Produces a markdown bundle (document label, per-comment pinpoint /
  offsets / quoted text / context, agent instructions, and a machine-readable
  `HANDLED_IDS_JSON` line), with an `execCommand` clipboard fallback.
- **Save / share.** *Export as Portable* embeds the comments into a downloadable copy that
  travels without localStorage. *Export to Plain HTML* strips the layer back to clean HTML while keeping the styling.
- **Two output modes.** *Standalone* (one self-contained file) and *economy* (the
  layer lives in companion `commentable-html.v<V>.{css,js,assets.js}` files referenced
  from the skill's `dist/` folder, so refreshes stay cheap). *Export as Portable*
  rebuilds a self-contained file from an economy doc. A version handshake shows a
  banner if the companions are missing or stale.
- **Handled-id pruning.** `tools/mark_handled.py` appends processed ids surgically; on
  reload those comments and highlights disappear.
- **Optional Chart.js charts.** Documented in `docs/CHARTS.md` and structurally
  checked by the validator.

## Directory layout

| Path | What it is |
| --- | --- |
| `SKILL.md` | Per-generation instructions (the skill's public surface). |
| `TEMPLATE.html` | The generated standalone/inline template + demo. Copy its five regions into a target page. |
| `assets/` | **Canonical hand-edited sources**: `commentable-html.css`, `commentable-html.js` (holds `CMH_VERSION`), `template.shell.html`. See `assets/README.md`. |
| `dist/` | **Generated economy bundle**: `ECONOMY.html`, the `commentable-html.v<V>.*` companions, `manifest.json`. See `dist/README.md`. |
| `tools/` | Python scripts: `build.py` (regenerates `TEMPLATE.html` + `dist/`), `validate.py` (per-generation invariant checker), `mark_handled.py`. |
| `docs/` | `DEVELOPMENT.md` (build + test guide) and `CHARTS.md` (Chart.js recipe). |
| `tests/` | The Playwright browser specs (`*.spec.js`), the Python `test_*.py` suites, shared `helpers.js`, and generated `fixtures/`. Present in the source-of-record repo; not vendored into the published plugin copy. |
| `package.json`, `playwright.config.js` | Test tooling config (source repo only; not vendored into the published plugin copy). |

`TEMPLATE.html` and everything in `dist/` are **generated** by `python tools/build.py`
from `assets/`; never hand-edit them (`python tools/build.py --check` guards drift).

## Using the skill

Per generated document, the only thing to run is the optional validator:

```
python tools/validate.py <file.html>
```

Everything else (how to retrofit a page, the five regions, the review loop) is in
`SKILL.md`.

## Developing and testing

The `tests/` suite and the Node/Playwright tooling (`package.json`, `playwright.config.js`)
live in the source-of-record repository and are not vendored into the published plugin
copy; run the commands below from a clone of that repo. The full guide is in
`docs/DEVELOPMENT.md`. The skill has two test layers, both green:

- **Python** (standard-library `unittest`, no install): 320 tests for `build.py`,
  `validate.py`, `mark_handled.py`, the KQL highlighter, the Kusto deep-link builder, the code highlighter, the image inliner, and the worked example.

  ```
  python -m unittest discover -s tests -p "test_*.py"
  ```

- **Browser E2E** (`@playwright/test`): 196 tests covering the full runtime feature
  surface, run **offline** (mermaid is served from a locally vendored copy via route
  interception).

  ```
  npm install                       # or: npm install --registry https://registry.npmjs.org
  npx playwright install chromium
  npx playwright test
  ```

After changing the layer, run `python tools/build.py` then
`node tests/fixtures/generate.mjs` to refresh the generated template and fixtures. See
`docs/DEVELOPMENT.md` for the full guide.
