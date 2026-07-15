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
> Audience and arc: the deck is a five-act narrative. Acts 1 to 3 speak to a non-technical viewer
> and land on the primary call to action; act 4 is an engineers-only deep dive; act 5 is a
> room-wide close. Retitle slides to outcome-focused promises, not feature names.
>
> One running example: thread a single community-garden plan (raised beds, crops, watering, and
> budget) through every value slide, so the demo is coherent instead of a pile of unrelated feature
> samples. Reuse that domain for the chart, the table, the diff, the code, and the KQL.
>
> Theme requirement: make it look like a real product pitch deck, not an unstyled example. Use a
> light "Parchment and Amber" theme pinned to `data-theme="light"`: a parchment background
> (`#f7f4ef`), a raspberry accent (`#b11f4b`), indigo ink body text (`#1b1f3b`), and an amber
> comment-highlight motif (`rgba(245, 158, 11, 0.42)`) applied as a focused decorative highlight on
> key title words - a look-alike class, never the runtime's live `mark.cm-hl`. No gradient hero
> wash. Keep readable table headers, visible Mermaid nodes and connectors, clear typography, and
> enough spacing for a 1920x1080 fixed stage. Every slide must be legible in present mode and in
> comment mode with the sidebar open, and every foreground/background pair must clear WCAG 4.5:1.
>
> Install call to action - show it EARLY, not only at the end: place a full install slide near the
> end of the opening hook (act 2) AND a primary call-to-action slide near the end of act 3. Each
> call to action must render BOTH agents' exact install commands as code blocks and the site,
> GitHub, and tutorial links:
> - Copilot: `copilot plugin marketplace add https://github.com/urikanonov/ai-marketplace` then
>   `copilot plugin install commentable-html@urikan-ai-marketplace`.
> - Claude: `claude plugin marketplace add https://github.com/urikanonov/ai-marketplace` then
>   `claude plugin install commentable-html@urikan-ai-marketplace`.
> - Links: site `https://urikanonov.github.io/ai-marketplace/`, GitHub
>   `https://github.com/urikanonov/ai-marketplace`, tutorial
>   `https://urikanonov.github.io/ai-marketplace/commentable-html/tutorial/`.
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
>   navigation, keyboard navigation, slide-aware comment jumps, the split-screen slide-overview navigator,
>   and the comment-mode brand-icon toggle.
> - Deterministic tooling: stdlib-only scaffold and strict validator, deterministic slide ids,
>   create-only behavior, no remote media, reduced-motion CSS, and validation before write.
> - Use the exact phrase "syntax-highlighted code and KQL" in the content so the feature is explicit.
>
> Slide outline to follow (about 17 slides across five acts):
> Act 1 - Hook:
> 1. Title promise - keep the review loop inside the artifact; a strong opening line and a
>    commentable subtitle.
> 2. The pain, shown - reviewing the garden plan, then losing the location by describing it in chat.
> 3. Close the loop - a Mermaid flowchart of agent -> commentable plan -> comment in place ->
>    Copy all -> agent applies -> handled ids embedded.
> Act 2 - Value on one example:
> 4. Comment on anything - the element-type grid plus a soft pointer to the live demo.
> 5. Review data and diagrams - the garden watering chart, the bed table, and an image, all
>    commentable.
> 6. Review code, not just prose - a real `pre.cmh-diff` garden diff plus syntax-highlighted code
>    and KQL block.
> 7. Decide and track - one slide holding both the drag-and-drop triage board (garden decisions) and
>    the layered checklist.
> 8. Why not just chat, a doc, or a PR - a comparison table.
> 9. Start today (EARLY install) - both agents' install commands as code blocks plus the site,
>    GitHub, and tutorial links.
> Act 3 - How it fits and the ask:
> 10. Three review loops - review your own work, peer review, and reviewing a plan before you build.
> 11. Prompts that work - the two prompts that produce and then apply a review.
> 12. Primary call to action - the payoff line plus both installs and the links again.
> Act 4 - Behind the scenes (engineers):
> 13. Anatomy of a file - the region map of layer versus CONTENT.
> 14. How comments stick - text offsets, structural keys, and widget deltas.
> 15. Portability internals - Live, Portable, Offline, and Markdown.
> 16. Safe and deterministic - the scaffold and strict validator checklist.
> Act 5 - Close:
> 17. Tomorrow morning - a room-wide close with one next action and a compact restated call to
>     action.
>
> Quality gates before returning:
> - Run `python tools/deck/deck_validate.py <deck-file>` and fix every error.
> - Verify the deck opens in a browser, starts in present mode, toggles to comment mode, and allows a
>   text comment on the title slide.
> - Verify the Mermaid slide renders, the table header is readable, the triage board card can move
>   between slots, the checklist initializes, and the diff renders with an inline/side-by-side
>   toggle.
> - Verify both install call-to-action slides show the Copilot and Claude commands and the links.
> - Return the final HTML file path and a one-paragraph summary of the slide story.

## What you get

A single prompt that gives the agent both the product story and the authoring contract. It removes
ambiguity about feature coverage, slide order, theme quality, the running example, the early and
primary install call to action, deck-mode requirements, and validation, so the generated deck is a
strong showcase in one pass instead of a generic slide sample.
