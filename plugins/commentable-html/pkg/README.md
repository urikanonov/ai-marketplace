# commentable-html plugin

`commentable-html` turns standalone HTML reports into inline-comment review surfaces. A reviewer can select text, code, diff lines, Mermaid nodes, images, or charts, leave comments in the page, copy a compact Markdown bundle back to an agent, and export a portable file with comments embedded.

## Features

- Inline text comments anchored by offsets, including nested inline elements, entities, emoji, and RTL text.
- Code-aware comments that preserve indentation and fenced Markdown in the copy bundle.
- Line and region comments on rendered unified diffs, with inline and side-by-side views.
- Mermaid, image, and Chart.js canvas comments with structural anchors.
- Sidebar and floating toolbar for adding, editing, deleting, jumping to, and copying comments.
- `Copy all` output with pinpoint metadata and a machine-readable `HANDLED_IDS_JSON` line.
- `Export as Portable` for a single shareable file with current comments embedded.
- `Export to Plain HTML` for a clean report without the review layer.
- Standalone and NonPortable output modes, both built from the same runtime.
- Runtime helpers for validation, handled-id updates, document creation, upgrades, diffs, charts, KQL, code highlighting, TOCs, Mermaid skip fixes, and image inlining.

## Using the skill

The authoritative per-generation instructions are in [`skills/commentable-html/SKILL.md`](skills/commentable-html/SKILL.md). In short: start from `skills/commentable-html/dist/PORTABLE.html` for a standalone file, or `skills/commentable-html/dist/NONPORTABLE.html` plus its companions for a local iterative file, then run the validator when Python is available:

```powershell
python skills\commentable-html\tools\validate.py --strict <file.html>
```

The review loop is also documented in `skills/commentable-html/SKILL.md`: the user copies all comments, the agent processes the bundle, and `tools\mark_handled.py` appends handled ids so processed comments disappear on reload.

Contributors should follow the development guide in the project's source repository. Packaged installs do not include the development harness.

## Directory layout

| Path | What ships |
| --- | --- |
| `skills/commentable-html/SKILL.md` | Public skill instructions and review loop. |
| `skills/commentable-html/dist/` | Generated bundle: `PORTABLE.html`, `NONPORTABLE.html`, CSS/JS/assets companions, and `manifest.json`. |
| `skills/commentable-html/tools/` | Runtime Python tools used while generating, validating, upgrading, and processing reports. |
| `skills/commentable-html/references/` | Detailed reference docs for anchors, layout, charts, validation, exports, and helper tools. |
| `skills/commentable-html/docs/` | Tutorial only: `docs/TUTORIAL.md` and `tutorial-images/`. |
| `skills/commentable-html/examples/` | Worked prompts and reports, including `prompt-community-garden.md`, `prompt-taxi.md`, `report-community-garden.html`, and `report-taxi.html`. |
