# commentable-html

`commentable-html` is a skill that turns any standalone HTML report into an inline-comment review surface you can hand back to an AI agent. It drastically shortens the AI planning and iteration loop: you review the artifact in place and return structured notes instead of narrating changes in chat.

Try the [Dynamic Controls demo](examples/report-checklist.html) to work with checklists, editable
notes and a numeric/choice follow-up table together. The [tutorial](docs/TUTORIAL.md) walks through
their shared Copy all and export flow; the [dedicated table playground](examples/report-editable-table.html)
focuses on the table controls.

For questions before changes, choose **Ask AI** in a comment. Hand back Copy or exported HTML,
reload the owner's persisted answer, then choose **Ask AI** for a follow-up or **Request edit**
for an explicit change. Check the remembered reply purpose before saving. See the
[tutorial walkthrough](docs/TUTORIAL.md#17-hand-your-comments-back) and
[AI discussion author reference](dev/skill/references/discussions.md).

## Repository layout

This plugin is split into two directories:

- [`pkg/`](pkg/README.md) - the shipped marketplace plugin users install.
  It contains `plugin.json`, the skill, runtime tools, generated dist files, references, docs, and examples.
- [`dev/`](dev/README.md) - the development home.
  It contains the canonical sources, build tooling, tests, fixtures, and spec, and it is never shipped.
