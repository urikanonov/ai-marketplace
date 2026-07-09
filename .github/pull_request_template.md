## Summary

<!-- What does this PR change? -->

## Type

- [ ] Improvement or fix to an existing plugin
- [ ] New plugin (maintainer only)
- [ ] Docs or repo tooling

## Checklist

- [ ] Version bumped per CONTRIBUTING when a published plugin changed (both `plugin.json` and manifest for a plugin-dir source; manifest only for a single-skill source)
- [ ] `CHANGELOG.md` updated when a plugin version changed
- [ ] `python scripts/validate_marketplace.py` passes locally

## Maintainer (before approving CI and before merging)

- [ ] Read `dev/package.json` lifecycle scripts and the `package-lock.json` diff before "Approve and run"
- [ ] Reviewed any change under `.github/workflows/**`, `.githooks/**`, `scripts/**`, plugin `hooks/**`, `*.ps1`, `.mcp.json`
- [ ] Not a new plugin from an external contributor (new plugins are maintainer-authored)
- [ ] Required checks green: `validate` and `plugin-tests`

## Notes

<!-- Anything reviewers should know. -->
