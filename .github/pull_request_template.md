## Summary

<!-- What does this PR change? -->

## Type

- [ ] Improvement or fix to an existing plugin
- [ ] New plugin (maintainer only)
- [ ] Docs or repo tooling

## Checklist

- [ ] New or changed feature/behavior has a matching feature-id row in the owning spec (`plugins/<plugin>/dev/SPEC.md` for a skill, `site/tests/SPEC.md` for the site) and a covering automated test named in that row
- [ ] Version bumped per CONTRIBUTING when a published plugin changed (both `plugin.json` and manifest for a plugin-dir source; manifest only for a single-skill source)
- [ ] The changed plugin's `CHANGELOG.md` updated when its version changed
- [ ] `python scripts/validate_marketplace.py` passes locally
- [ ] `python scripts/validate_markdown.py` passes locally

## Maintainer (before approving CI and before merging)

- [ ] Read `dev/package.json` lifecycle scripts and the `package-lock.json` diff before "Approve and run"
- [ ] Reviewed any change under `.github/workflows/**`, `.githooks/**`, `scripts/**`, plugin `hooks/**`, `*.ps1`, `.mcp.json`
- [ ] For a whole-file reorg of a hand-edited source (`site/pages/**` and `site/css/**`, `dev/assets/**` partials, `site/src/` statics), ran it alone/last and will run the post-merge `git log -S` survival check (AGENTS.md finding 4.8)
- [ ] Not a new plugin from an external contributor (new plugins are maintainer-authored)
- [ ] Required checks green: `validate`, `version-bump`, `dist-in-sync`, `actionlint`, `site`, `plugin-tests`, `require-owner-approval` (external PRs), and `All conversations resolved`

## Notes

<!-- Anything reviewers should know. -->
