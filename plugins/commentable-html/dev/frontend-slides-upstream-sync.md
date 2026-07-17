# Resyncing the vendored frontend-slides subset (maintainer)

The deck capability vendors a pristine, curated subset of the third-party `frontend-slides`
skill under `plugins/commentable-html/pkg/skills/commentable-html/vendor/frontend-slides/`. This
is development-only guidance; it is never shipped.

The vendored subtree is enforced pristine by `dev/tools/check_vendor.py`, which runs in the
required `validate` CI job. Never hand-edit vendored files - a resync replaces them wholesale.

## When to resync

Only to pull an intentional upstream improvement. A resync is a security event: the whole point
of pinning to a commit is that new upstream code is re-reviewed before it can ship.

## Steps

1. **Fetch upstream and pick the target commit.**
   ```bash
   git -C /path/to/frontend-slides fetch origin
   git -C /path/to/frontend-slides log --oneline origin/main -20
   ```
2. **Re-run the security scan** on the target commit. Do not resync a commit that fails review.
   Note especially any newly added script, network call, hook, or plugin manifest.
3. **Diff the target commit against the recorded one** (`UPSTREAM.md` holds the current commit):
   review every changed file, especially the templates and `bold-template-pack/`.
4. **Re-vendor the curated subset** (a clean copy). Two of the exclusions are HARD-DENIED by
   `check_vendor.py` and can never be reintroduced even by a `--update` re-baseline:
   `scripts/deploy.sh`, `scripts/export-pdf.sh`, and any `.claude-plugin/` or `.git/` directory.
   The remaining exclusions - the top-level `plugins/`, the repo-root `README.md`, and `SKILL.md` -
   are enforced only by the curated file list and the SHA-256 manifest (NOT a hard deny), so review
   the diff before running `--update` so you do not baseline a file that should not ship. Keep the
   upstream `LICENSE`. Note that legitimately vendored sub-READMEs (for example
   `bold-template-pack/README.md`) ARE kept - only the repo-root `README.md` is excluded.
5. **Regenerate the integrity manifest** and confirm it verifies:
   ```bash
   python plugins/commentable-html/dev/tools/check_vendor.py --update
   python plugins/commentable-html/dev/tools/check_vendor.py
   ```
6. **Re-run the deck layer tests** (`deck/` tools and the deck Playwright suite). Adjust the glue
   only if a template contract changed; the runtime and tools consume the vendored templates, so a
   template-structure change may need a matching fix.
7. **Update provenance and ship metadata**: set the new commit in `vendor/frontend-slides/UPSTREAM.md`,
   refresh the site credit line, add a `CHANGELOG.md` entry, and bump the plugin version.
8. **Validate**: `python scripts/validate_marketplace.py`, `python scripts/validate_markdown.py`,
   and the plugin test suites must pass, plus `check_vendor.py`.
9. **Re-review the native deck theme presets** against the new commit (see the next section). The
   required `validate` job runs `dev/tools/check_theme_sources.py`, which FAILS once `UPSTREAM.md`
   names a new commit until every `tools/deck/themes/*.theme.json` acknowledges it, so a resync is not
   done until each preset is re-reviewed and its `sourceCommit` updated.

## Refreshing the native deck theme presets (merge-time port)

The frontend-slides design system is incorporated as NATIVE CMH deck theme presets
(`tools/deck/themes/*.theme.json`), not translated per deck at runtime. The lossy upstream->CMH
mapping (remote fonts to system stacks, arbitrary palettes to contrast-safe deck tokens) is done ONCE
here, at merge time, so every deck gets a reviewed, golden-tested theme instead of a per-deck guess.
Two dev tools support this flow:

- `dev/tools/fs_theme_convert.py` - a deterministic BOOTSTRAP. Given a STYLE_PRESETS.md style it emits
  a STARTER `<name>.theme.json`: it harvests the palette, maps the darkest colour to the slide/stage
  background, the lightest to the foreground, the most-saturated mid to the accent, picks the
  higher-contrast black/white accent text, and substitutes the remote display/body fonts for the
  approved system stacks (reusing `deck_fix_fonts`). The output is flagged `_starter` and is NOT
  guaranteed to pass the validator - it is a first draft a human finishes.
- `dev/tools/check_theme_sources.py` - the staleness gate. Each preset records the `sourceCommit` it
  was reviewed against; the gate fails when a preset lacks provenance or lags the vendored commit.

### Recipe: port a new preset

```bash
# 1. Bootstrap a starter from an upstream style (writes to tmp/, never into themes/):
python plugins/commentable-html/dev/tools/fs_theme_convert.py --preset "Bold Signal" \
  --out tmp/bold-signal.theme.json
```
2. Review and finish the starter by hand: add the component tokens (`--cmh-deck-*` syntax, table,
   diff, mermaid), add a `contrastPairs` list covering every fg/bg surface, and adjust colours until
   they pass AA. Copy the finished file to `tools/deck/themes/<name>.theme.json`.
3. Validate the port fails closed and stays contrast-clean:
   ```bash
   python plugins/commentable-html/pkg/skills/commentable-html/tools/deck/deck_theme.py --list
   python plugins/commentable-html/pkg/skills/commentable-html/tools/deck/deck_scaffold.py \
     --theme <name> ...   # then deck_validate.py the output
   ```
   Add a golden/contrast test row under CMH-DECK-THEME-* and bump the plugin version.

### Recipe: acknowledge an upstream refresh ("reviewed, no change")

After a resync bumps the vendored commit, `check_theme_sources.py` fails for every preset whose
`sourceCommit` still points at the old commit. For each preset, review the upstream style's diff:

- If the palette or typography changed, re-port it (rerun `fs_theme_convert.py`, re-finish, re-test).
- If nothing meaningful changed, no colour edit is needed.

Either way, set the preset's `sourceCommit` to the new vendored commit. That edit is the
acknowledgement the gate requires; a "reviewed, no change" acknowledgement is just the commit bump
with no token change.

### Areas to focus on when porting

- **Contrast is the hard part.** The upstream palettes are tuned for their own layout, not for CMH's
  translucent table headers and diff-row fills. `_deck_theme._check_effective_contrast` composites
  those real backdrops, so a colour that looks fine in isolation can still fail - trust the validator.
- **Fonts must be local.** Never carry an upstream `@font-face`/Google Fonts family into a preset; the
  converter already maps them, and `deck_validate.py` rejects remote fonts.
- **Keep provenance and credit.** Every preset's `adaptedFrom` credits Zara Zhang / frontend-slides
  (MIT) and names the source style; `sourceCommit` records the reviewed commit.

