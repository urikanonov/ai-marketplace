# One-shot prompt - Commentable HTML showcase deck

Use this prompt when you want an AI agent to generate a flagship, in-depth, commentable pitch deck
for the `commentable-html` plugin in a single pass. The output should be a deck-mode
commentable-html document, not a flat report.

## Prompt

> Build a polished, self-contained Commentable HTML showcase deck that pitches the plugin and
> demonstrates it in depth. Use the deck contract exactly: `#commentRoot` has
> `data-cmh-mode="deck"`; slides live inside `.deck-viewport > .deck-stage`; every slide is a
> `<section class="slide">` with a stable `data-slide-id`; the first slide is active; the document
> carries `commentable-html-kind=slides`; the deck body has no external scripts, no remote fonts,
> no remote media, and no unsafe active content. Use the shipped `tools/deck/deck_scaffold.py` to
> create the deck and `tools/deck/deck_validate.py` to validate it. Keep it fully local-first and
> pass the strict validator before returning the file.
>
> Theme requirement: make it look like a real product pitch deck, not an unstyled example. Use a
> high-contrast dark theme with readable table headers, visible Mermaid nodes and connectors, clear
> typography, and enough spacing for a 1920x1080 fixed stage. Do not use remote fonts or assets.
> Every slide must be legible in present mode and in comment mode with the sidebar open.
>
> Feature coverage to demonstrate and explicitly name:
> - Comment on anything: prose, table cells, code blocks, KQL, charts, images, Mermaid nodes, and
>   whole slides.
> - Rich content: Chart.js charts or a canvas chart in the Chart.js pattern, Mermaid diagrams,
>   drag-and-drop triage board, rendered code diffs inline and side-by-side, syntax-highlighted code
>   and KQL, and the layered checklist.
> - Round-trip to the agent: Copy all creates a Markdown bundle plus a machine-readable id list;
>   the agent applies changes, marks handled ids, and handled-comment pruning removes resolved
>   comments on reload.
> - Exports: Export as Portable, Export Offline, Plain HTML, and Markdown.
> - Privacy and offline story: comments stay local in browser storage or embedded in the exported
>   HTML file; there is no server, account, telemetry, or upload; Offline export snapshots diagrams
>   and charts and strips loaders for zero-network review.
> - Deck mode itself: fixed 16:9 slides, present mode vs comment mode, slide-bar and arrow
>   navigation, keyboard navigation, slide-aware comment jumps, the split-screen slide-overview
>   navigator, and the comment-mode brand-icon toggle.
> - Deterministic tooling: stdlib-only scaffold and strict validator, deterministic slide ids,
>   create-only behavior, no remote media, reduced-motion CSS, and validation before write.
> - Use the exact phrase "syntax-highlighted code and KQL" in the content so the feature is explicit.
>
> Slide outline to follow exactly:
> 1. Title promise - a strong opening that says Commentable HTML turns AI-made HTML into a review
>    room.
> 2. Problem - show the broken out-of-band review loop and the improved in-document loop.
> 3. Anchor coverage - table of every comment target: prose, table cells, code/KQL, Mermaid,
>    charts, images, widgets, and slides.
> 4. Rich content matrix - cards for Chart.js charts, Mermaid diagrams, diffs/code/KQL, drag board,
>    and checklist.
> 5. Live chart and image slide - include a chart surface and an image surface that are both
>    commentable, with accessible labels.
> 6. Mermaid architecture - render a flowchart of agent -> commentable HTML -> reviewer -> Copy all
>    -> agent -> handled ids -> export.
> 7. Diff, code, and KQL slide - include a real `pre.cmh-diff` diff plus syntax-highlighted code and
>    KQL block.
> 8. Drag-and-drop triage board - include a real `[data-cm-widget][data-cm-draggable]` board with
>    three slots and movable cards.
> 9. Layered checklist - include a real `data-cmh-checklist` nested checklist and explain that
>    changed states are copied back to the agent.
> 10. Copy all workflow - show the Markdown bundle and handled id list the agent receives.
> 11. Handled-comment pruning - explain the reload loop and why resolved comments stay gone.
> 12. Export modes - compare Portable, Offline, Plain HTML, and Markdown.
> 13. Privacy/offline - explain local-only storage, no server, no telemetry, and Offline for
>     air-gapped review.
> 14. Deck mode - show fixed 16:9, present vs comment mode, slide-bar/arrow/keyboard navigation,
>     split-screen slide-overview navigator, slide-aware jumps, and comment-mode brand-icon toggle.
> 15. Tooling and validator - show the scaffold and validate commands, and list what the strict
>     validator rejects.
> 16. Close - crisp call to action: install the plugin, generate the artifact, review in place,
>     Copy all back.
>
> Quality gates before returning:
> - Run `python tools/deck/deck_validate.py <deck-file>` and fix every error.
> - Verify the deck opens in a browser, starts in present mode, toggles to comment mode, and allows a
>   text comment on the title slide.
> - Verify the Mermaid slide renders, the table header is readable, the triage board card can move
>   between slots, the checklist initializes, and the diff renders with an inline/side-by-side
>   toggle.
> - Return the final HTML file path and a one-paragraph summary of the slide story.

## What you get

A single prompt that gives the agent both the product story and the authoring contract. It removes
ambiguity about feature coverage, slide order, theme quality, deck-mode requirements, and validation,
so the generated deck is a strong showcase in one pass instead of a generic slide sample.
