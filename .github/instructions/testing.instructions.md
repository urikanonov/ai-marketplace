---
applyTo: "**/tests/**,**/*.spec.js,**/*.test.js,**/*.spec.mjs,scripts/test_*.py,plugins/**/dev/**,tests/**"
---

# Testing instructions

When you write, modify, debug, or review any test in this repository, read and follow the repository
testing guidelines in [docs/testing-guidelines.md](../../docs/testing-guidelines.md) before you start.

That document is the single source of truth for test conventions and the pitfalls past refactors already
paid for (test-driven and genuinely-red-first, hermetic and network-blocked Playwright specs, rebuilding
the generated `site/` before asserting, choosing a viewport where a layout behavior is observable,
asserting visibility instead of computed style for show/hide changes, regenerating version-stamped
fixtures and highlighter goldens, and feature-id discipline). Do not restate or fork those rules here -
follow the guidelines file and keep it as the one place they are maintained.
