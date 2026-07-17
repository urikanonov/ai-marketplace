# Vendored upstream: frontend-slides

This directory is a **pristine, curated subset** of the third-party `frontend-slides` skill,
vendored into the commentable-html skill to power its built-in deck capability. Do not hand-edit
these files; they are replaced wholesale on resync (see the sync playbook below).

## Provenance

- Upstream repo: https://github.com/zarazhangrui/frontend-slides
- Author: Zara Zhang (https://github.com/zarazhangrui)
- License: MIT (see `LICENSE` in this directory, kept verbatim)
- Vendored commit: `9906a34d640d2111f724544cbc50f7f130569ae1`
- Security review: SAFE-WITH-CAVEATS at this commit (nothing runs at install/session start; the
  Vercel deploy and PDF-export paths are excluded from this subset - see exclusions).

## What is vendored (curated subset)

- `viewport-base.css`, `html-template.md`, `animation-patterns.md`, `STYLE_PRESETS.md`
- `bold-template-pack/` (all styles, plus `deck-stage.js` as inert reference only - it is NOT
  emitted into generated decks)
- `scripts/extract-pptx.py`

## What is deliberately excluded (never vendored)

- `scripts/deploy.sh` - uploads the deck to a public Vercel URL and copies relative asset refs
  without `../` filtering (data-leakage risk); the deck capability does not deploy.
- `scripts/export-pdf.sh` - runs an unpinned runtime `npm install`; no PDF export in v1.
- `.claude-plugin/` (upstream plugin manifest), `plugins/` (a duplicate payload copy), `README.md`,
  `SKILL.md` (our own SKILL.md drives the flow), and repo dotfiles.

## Integrity

- `MANIFEST.sha256` records the SHA-256 of every vendored file. The required CI check
  `dev/tools/check_vendor.py` fails on any unknown, changed, removed, or denylisted file (for
  example a resync that reintroduces `deploy.sh`).

## Resync

See `dev/frontend-slides-upstream-sync.md`. In short: fetch upstream, re-run the security scan on
the new commit, diff against this commit, re-vendor the curated subset (exclusions preserved),
run `python dev/tools/check_vendor.py --update`, update this file's commit + the site credit +
CHANGELOG, bump the plugin version, and run the validators.

## Native deck theme presets (adapted, not vendored)

The deck engine ships NATIVE theme presets under
`pkg/skills/commentable-html/tools/deck/themes/<name>.theme.json`. These are CMH-authored files, NOT
vendored copies: they re-express a frontend-slides style's palette and character as an allowlisted
set of CMH deck CSS variables with system-font stacks, contrast-checked at build time. The shipped
`terminal` preset is ADAPTED (color and name inspired) from the frontend-slides "Terminal Green"
style. frontend-slides is MIT (see `LICENSE`), which permits this adaptation; each preset records its
`adaptedFrom` and `sourceCommit` provenance in its JSON.

### Updating CMH deck themes from a new frontend-slides release

When you resync the vendored subset (above), also review the deck theme presets:

1. Diff the upstream `STYLE_PRESETS.md` entries a preset was adapted from against the preset's pinned
   `sourceCommit`. A palette or type change upstream is a candidate preset update - but a curated
   adaptation need not track every upstream tweak; record "reviewed, no change" rather than forcing a
   port.
2. For a NEW preset, prefer a STYLE_PRESETS.md style whose identity survives system fonts (monospace,
   Swiss/Helvetica) or self-host an OFL `.woff2` subset as a local `data:` font (the preset `fonts`
   array accepts only local data URIs). Author explicit opaque fg/bg pairs and list them under the
   preset's `contrastPairs` so the load-time self-check and `deck_validate.py` both gate them.
3. Run the gate stack: `python dev/tools/../tests` deck theme tests, `deck_validate.py --strict` on a
   `--theme` scaffold, and the `70-deck-theme.spec.js` rendered checks.

Deferred automation (tracked as follow-up issues, see #334): a deterministic converter
(`fs_theme_convert.py`) that extracts hex colors, scales `vw`/`clamp()` to the 1920x1080 stage, and
substitutes remote fonts for system stacks to emit a STARTER preset a human reviews; and a staleness
CI gate keyed on each preset's `sourceCommit`.

### Licensing note: bold-template-pack

The vendored `bold-template-pack/` originates from `zarazhangrui/beautiful-html-templates` (a DIFFERENT
upstream repo than frontend-slides), as declared by `bold-template-pack/selection-index.json`
(`source_repo`). Its license has been independently verified:

- Upstream repo: https://github.com/zarazhangrui/beautiful-html-templates
- Author: Zara Zhang (https://github.com/zarazhangrui)
- License: MIT - Copyright (c) 2026 Zara Zhang (kept verbatim as `bold-template-pack/LICENSE`)
- Verified commit: `e5e204fb1f3b06290846e7dcd7aceddabeceec8c` (2026-06-09)

Both frontend-slides and beautiful-html-templates are MIT by the same author, so the top-level
frontend-slides `LICENSE` and the `bold-template-pack/LICENSE` grant the same permissions. Adapting a
bold-template-pack design into a native CMH deck preset is therefore permitted; keep the `adaptedFrom`
provenance in each preset JSON and preserve both `LICENSE` files on resync.
