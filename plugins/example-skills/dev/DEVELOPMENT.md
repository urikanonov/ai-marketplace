# Development notes (not distributed)

This `dev/` folder is NOT shipped when someone installs a plugin from this marketplace. Only a plugin's
registered `source` (for this plugin, `../skills/hello-world`) is copied to the user's machine.

Put anything that supports development but should not reach end users here:

- `tests/` - unit and end-to-end tests, fixtures, and test config.
- Build tooling and canonical sources, when the shipped assets are generated (commit the built outputs into
  the shipped folder; keep the inputs and the builder here).
- Design notes, specs, and maintainer docs.

The marketplace validator ignores `dev/` (and `node_modules/`, `__pycache__/`), and it rejects any manifest
`source` that would ship one of these folders. Run a plugin's tests from a CI job scoped to
`plugins/<plugin>/**`.
