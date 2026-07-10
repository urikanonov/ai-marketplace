# commentable-html

`commentable-html` is a skill that turns any standalone HTML report into a single-file inline-comment review surface you can hand back to an AI agent.

## Repository layout

This plugin is split into two directories:

- [`pkg/`](pkg/README.md) - the shipped marketplace plugin users install.
  It contains `plugin.json`, the skill, runtime tools, generated dist files, references, docs, and examples.
- [`dev/`](dev/README.md) - the development home.
  It contains the canonical sources, build tooling, tests, fixtures, and spec, and it is never shipped.
