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
