---
name: visual-audit
description: >-
  Run a full visual audit of the commentable-html examples in a real browser. Drives every example
  (reports and the deck) through Playwright in BOTH desktop and mobile viewports, exercises the
  interactive UI (enters comment mode, selects text, adds and saves comments, opens the toolbar
  menu, navigates deck slides and the overview grid), captures a screenshot at each state, records
  console/page errors and mobile horizontal-overflow, and writes a JSON transcript plus a Markdown
  report. Use when asked to visually audit, screenshot, or review how the examples look and behave,
  check mobile rendering, or produce artifacts to feed a multi-duck review. Trigger on: visual audit,
  screenshot the examples, audit the examples, mobile view, how do the examples look, review the
  examples visually, browser walkthrough, capture screenshots.
---

# visual-audit

A reusable, repeatable visual audit of the `commentable-html` example documents. It opens each
example in a real Chromium browser (via Playwright), drives the interactive UI the way a reviewer
would, captures screenshots in desktop and mobile viewports, and emits a transcript plus a Markdown
report so a human - or a `multi-duck` panel - can judge how the examples look and behave.

The point is to catch what a static read of the HTML cannot: real rendering (mermaid diagrams, tables,
callouts), the comment flow (selecting text, the composer, the saved comment and sidebar), the toolbar
menu, deck navigation, and mobile layout problems (horizontal overflow, cramped chrome).

## When to use

Invoke when the user requests a visual audit, a mobile layout check, screenshots to attach or to feed a
review panel, or a browser walkthrough of the examples. It is read-only and never edits the examples; it
only produces screenshots and a report.

## What it does (the flow)

For every `*.html` under the examples dir, in each of two viewports (desktop 1440x900, mobile 390x844):

1. Open the example over a local static HTTP server (not `file://`), wait for the runtime to signal ready, and let mermaid/rich content render (the mermaid CDN import is routed to the vendored, version-matched local copy so diagrams render deterministically; Chart.js and other resources load from their own pinned CDNs, so a chart pass needs network).
2. Detect the profile from `data-cmh-mode="deck"`: a **report** or the **deck**.
3. Report flow: full-page screenshot; open the toolbar overflow menu; select a real paragraph, open the comment composer, type and save a comment; show the sidebar with the saved comment; scroll to the footer.
4. Deck flow: screenshot the opening slide; advance a few slides with the keyboard; open the overview grid ("o"); toggle deck comment mode; select slide text and save a comment.
5. Record every action with its screenshot and a note, plus any console errors, page errors, and a per-state horizontal-overflow check across the whole document (content and chrome), which flags offending elements.

Outputs (all in the gitignored `<out-dir>`, default `tmp/visual-audit/` - nothing is checked in):

- Screenshots under `<out-dir>/<example>/<viewport>/NN-state.png`.
- `<out-dir>/transcript.json` - the full machine-readable transcript.
- `<out-dir>/audit-report.html` - the PRIMARY report, a **commentable-html** document (built with the
  plugin's own `new_document.py`) so the audit itself is reviewable: it inlines the comment layer and
  embeds every screenshot as a figure plus an automated findings-summary table, so you can open it in a
  browser and leave inline comments on any shot, cell, or note. The screenshots are referenced as sibling
  files under the same out-dir (open the report in place), so keep the folder together.
- `<out-dir>/audit-report.md` - a plain-text Markdown sidecar of the same content for text tools.

## How to run

Playwright is reused from the commentable-html dev install (this skill declares no dependency of its
own) and is resolved automatically via `createRequire` - no `NODE_PATH` or other env var is needed.
Install it once if needed, then run the driver with Node:

```bash
# one-time, if plugins/commentable-html/dev/node_modules is missing (run these from that dir):
cd plugins/commentable-html/dev
npm ci --ignore-scripts
npx playwright install chromium
cd ../../..

# run the full audit (from the repo root), opening the commentable-html report when done:
node .github/skills/visual-audit/tools/audit.mjs --open
```

Options (all optional):

- `--examples-dir <dir>` - directory of `*.html` to audit (default: the shipped commentable-html examples).
- `--out-dir <dir>` - where screenshots, `transcript.json`, and the reports go (default: `tmp/visual-audit`).
- `--report <path>` - commentable-html report path (default: `<out-dir>/audit-report.html`).
- `--only <substring>` - audit only examples whose name contains the substring (e.g. `--only deck`).
- `--open` - open the commentable-html report in the OS default browser when done.
- `--from-transcript [path]` - regenerate the reports from an existing `transcript.json`
  (the given path, or `<out-dir>/transcript.json` if none) WITHOUT re-running the browser.

On Windows, put Node on PATH first (`$env:Path = "C:\Program Files\nodejs;$env:Path"`), then run the
same `node .github/skills/visual-audit/tools/audit.mjs` command.

## Feeding a multi-duck review

The transcript, screenshots, and the commentable-html report are designed to be reviewed by the
`multi-duck` skill. Point the panel at `<out-dir>/audit-report.html` (or the `audit-report.md` sidecar)
and the `transcript.json` (a local machine artifact - it holds host-specific absolute paths, so do not
commit or forward it as-is); the ducks open the shots, read the per-step notes and the automated findings
summary, and propose visual/UX improvements. Because the examples are pure build artifacts, any fix a
duck proposes is applied to the CONTENT source under
`plugins/commentable-html/dev/examples/src/<name>.html` (or the shared runtime
under `plugins/commentable-html/dev/assets/`), then rebuilt - never hand-edited in the shipped example.

## Notes

- Per-model image caps when a review panel VIEWS the screenshots: some models fail a turn with "too
  many images" past a per-request limit (Gemini 3.1 Pro allows at most 10). The audit captures roughly
  a dozen shots per example (about 7 states x 2 viewports), so when feeding them to a `multi-duck`
  panel you MUST give capped models a curated subset of <=10 (batch in groups of <=8 to stay safe).
- Deterministic-ish: comment timestamps render at minute resolution, so screenshots captured after a comment is saved can differ across a minute boundary; the pre-comment shots are stable.
- The overflow check reports elements whose right edge exceeds the viewport, which is the primary mobile-layout signal; a clean run shows `overflowX=false` for every example in both viewports.
- Extend coverage by adding examples to the examples dir - discovery is automatic; deck vs report is auto-detected.
