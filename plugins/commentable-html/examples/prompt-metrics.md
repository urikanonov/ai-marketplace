# Example prompt - Commentable Visuals Matrix

A minimal prompt that produces the companion `report-metrics.html`. It is a dense
gallery that packs one of every commentable visual into a single page, so it doubles as
a coverage matrix for the review anchors (diagrams, charts, an SVG widget, a diff, and a
KQL block).

## Prompt

> Make me a commentable HTML gallery that shows one of every visual the skill can anchor
> a comment on, so I can review the whole set in one place. Include a Mermaid gallery
> with a flowchart, a sequence diagram, a gantt, a state diagram, a class diagram, an ER
> diagram, and a pie chart; a Chart gallery with a bar, line, pie, and doughnut chart; an
> SVG widget whose individual parts are commentable; and a section with a code-review
> diff and a KQL block. Add a short inventory table at the top listing every visual kind.

## What you get

From that one line, the skill produces a single self-contained HTML file you can open
in any browser and share:

- Every part is commentable: text, tables, charts, Mermaid nodes, diff lines, the KQL
  block, and each part of the SVG widget, so no anchor kind is left out.
- It renders every diagram and chart kind side by side, which makes the page a quick way
  to confirm the review layer works on all of them at once.
- Copy all hands your comments back to the agent as a tidy list, and Export as Portable
  bakes them into a shareable copy.
