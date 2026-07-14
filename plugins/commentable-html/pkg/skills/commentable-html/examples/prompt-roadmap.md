# Example prompt - Autumn Roadmap Review deck

A minimal prompt that produces the companion `deck-roadmap.html` slide deck. The deck is a
`kind=slides` commentable HTML document: a fixed 1920x1080 stage with several slides, each
individually reviewable through the same commentable layer used by the report examples.

## Prompt

> Make me a commentable HTML slide deck for an Autumn (Q3) roadmap review with the review-tool
> team. Cover: a title slide, current-state numbers, planned themes, an architecture change,
> risks (as a three-column Now/Next/Watch board with cards), and a two-item ask. Keep it fully
> self-contained (no remote fonts or assets), use one mermaid diagram, and make every slide
> element commentable so reviewers can leave feedback in place.

## What you get

From that one line, the skill produces a single self-contained HTML file you can open in any
browser and share:

- A fixed 16:9 stage with six slides (title, numbers, themes table, mermaid diagram, risk board,
  the ask), each with a stable slide id so a comment survives an edit-and-rebuild round-trip.
- Every part is commentable: slide text, table cells, mermaid nodes, risk cards, and the ask
  bullets, keyed to their owning slide by the deck-aware jump.
- Present mode for a full-screen review; toggle Comment mode to reveal the sidebar and leave
  feedback on any slide. Copy all hands the review bundle back to the agent.
