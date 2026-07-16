# Resyncing the vendored frontend-slides subset (maintainer)

The deck capability vendors a pristine, curated subset of the third-party `frontend-slides`
skill under `plugins/commentable-html/dev/skill/vendor/frontend-slides/` (the STAGE source of
truth; it ships inside `skill-resources.zip` and extracts to `skills/commentable-html/vendor/`).
This is development-only guidance; it is never shipped.

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
