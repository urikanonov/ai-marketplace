# Example prompt - Incident Triage Board

A minimal prompt that produces the companion `report-triage.html`. It is a compact
on-call review surface built around a kanban board widget, so it exercises the
commentable widget parts (columns and cards) alongside a table and a chart.

## Prompt

> Make me a commentable HTML incident triage board so my on-call team can review queue
> order and ownership in place. Add a Snapshot section with a small table (Queue, Owner,
> Oldest, Exit check), then a commentable kanban board with New, Investigating, and Fixed
> columns and a card per incident (for example API saturation, Checkout timeouts, Auth
> retries, Cache patch), and finish with a Queue counts chart of how many incidents sit
> in each column.

## What you get

From that one line, the skill produces a single self-contained HTML file you can open
in any browser and share:

- Every part is commentable: select text, a table cell, a chart, or a single kanban
  card, and leave a note; the side panel collects them.
- The kanban board is a widget whose columns and cards are individually commentable, so
  a reviewer can pin a comment to the exact incident instead of the whole board.
- It writes the sections with a table of contents, adds the snapshot table and the queue
  chart, and Copy all hands your comments back to the agent as a tidy list.
