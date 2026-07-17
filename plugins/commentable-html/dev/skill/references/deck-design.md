# Deck design playbook (CHM-specific)

How to author a commentable-html deck that is presentation-ready, not just valid. For visual styling,
apply a **native CMH deck theme preset** (`tools/deck/themes/`, via `deck_scaffold.py --theme` or
`deck_theme.py apply`) and compose the native recipe classes (see the
[deck runtime contract](deck-contract.md)) - that is the default, corporate-safe path and needs no
per-deck CSS. The vendored `vendor/frontend-slides/` design system (`STYLE_PRESETS.md`,
`html-template.md`, `animation-patterns.md`) is design
provenance and a source of ideas for a bespoke, non-preset look a user explicitly asks for. This file
is the CHM-specific narrative and layout delta on top of either path: a CHM deck is a **local-first
commentable review surface**, it renders on a **fixed 1920x1080 stage gated by a strict validator** (no
vertical clip, AA contrast), and it must stay **corporate-safe** (no remote fonts/media/scripts). Every
rule below was paid for while building the shipped showcase deck (`examples/deck-showcase.html`).

## Contents

- [Ask first (conditional questions before you plan)](#ask-first-conditional-questions-before-you-plan)
- [Fill the fixed stage](#fill-the-fixed-stage)
- [Motion must be capture-safe](#motion-must-be-capture-safe)
- [Light-theme depth and palette](#light-theme-depth-and-palette)
- [Wayfinding and chrome](#wayfinding-and-chrome)
- [Narrative and persuasion](#narrative-and-persuasion)
- [Review-surface patterns (CHM-specific)](#review-surface-patterns-chm-specific)
- [Card systems and variety](#card-systems-and-variety)
- [Contrast, clipping, and validation discipline](#contrast-clipping-and-validation-discipline)
- [CSS gotchas specific to CHM decks](#css-gotchas-specific-to-chm-decks)
- [Verify like a reviewer](#verify-like-a-reviewer)

## Ask first (conditional questions before you plan)

A deck's density, depth, chrome, and export story all depend on facts only the user has. Before you
outline slides, ask the ones you cannot infer (offer the default in parentheses so the user can just
confirm):

1. **Duration and format.** Lightning (about 5 min), a talk (30-60 min), or self-guided/leave-behind?
   Drives slide count and density. A talk deck should still let a newcomer grasp the "why" in the first
   5-10 minutes, even if the whole thing runs long.
2. **Audience.** Newcomer, mixed, or technical? Drives how much motivation ("why") comes before
   mechanism ("how"). Put everything a non-technical newcomer needs up front; keep the deep
   "how it works" material in later, skippable slides for the technical audience.
3. **Presented live vs handed off.** Live with internet (a live Chart/Mermaid via CDN is fine), live
   air-gapped, or emailed/handed off? Air-gapped or handoff means author for **Export Offline**
   (snapshotted diagrams/charts, zero network) and expect a static fallback to show.
4. **Async peer review?** Will reviewers comment on it and send it back? If yes, emphasize the
   **Export Portable** round-trip and stable-id story; the deck is itself the review surface.
5. **Theme / brand.** Which native deck theme preset (`tools/deck/themes/`, for example `terminal`),
   or a specific palette/brand? Commit to ONE content-informed theme; prefer a native preset, and use
   the vendored frontend-slides `STYLE_PRESETS.md` only for a bespoke look; avoid generic AI-slop defaults.
6. **Running example.** Is there one concrete scenario to thread through every slide (the showcase deck
   uses a single community-garden plan)? A through-line beats abstract feature lists.
7. **Install / call-to-action.** Which agents (Copilot, Claude, both), and should the install CTA
   appear EARLY (not just on the closing slide)? See "Narrative" below.

Default when the user does not answer: a 30-60 min live talk for a mixed audience, one running example,
install CTA early and at the close, a native deck theme preset (for example `terminal`), both agents.

## Fill the fixed stage

The stage is exactly 1920x1080 and scaled to fit; `deck_validate.py --strict` FAILS on any content
taller than the stage. Two failure modes, opposite directions:

- **Top-weighted clusters.** Content bunched at the top with a large empty lower band reads unfinished.
  Use `justify-content: safe center` and a fluid `clamp()` type scale so content occupies the stage.
  Some breathing room at the bottom is fine; a 40%-empty slide is not - fill it with a concrete proof
  (a real sample, a caption, a specimen), not filler.
- **Overflow.** Never solve emptiness by piling on content that clips. Validate strict after every
  change; also run `tools/audit.mjs` and read `issues` (it flags horizontal overflow and vertical
  clip). A single glyph or badge whose fixed width is smaller than its text will overflow by a few px:
  size such chips with `min-width` + padding, not a hard `width`.

## Motion must be capture-safe

frontend-slides entrance animations fade opacity from 0. Do NOT do that in a CHM deck: static captures
(the audit harness, print, an Export Offline snapshot, a screenshot) can catch content mid-fade and
render it blank or faint. Use a **transform-only** entrance reveal (for example `translateY`) so content
is ALWAYS painted at full opacity; the slide-level cross-fade handles opacity. Gate all entrance motion
behind `@media (prefers-reduced-motion: reduce)` (the inlined `viewport-base.css` supplies the required
rule; the validator errors without it).

## Light-theme depth and palette

A flat single-fill light slide looks cheap. Add depth with layers that cost no vertical room: a subtle
radial background wash, bento card surfaces with a soft gradient plus a layered shadow, and tabular
figures. Pin the design theme when it has no dark variant: set `data-theme` in the head and do not let a
host theme parameter flip it (the showcase deck hard-pins light because its parchment palette has no
dark variant). Keep the palette content-informed and consistent; one accent should dominate.

## Wayfinding and chrome

- Give each act a cue: a per-act accent rail (a thin edge gradient that progresses across acts is a free
  progress signal) and a large low-opacity editorial act numeral. Add a short uppercase kicker per slide.
- Put the commentable-html brand mark in one corner (top-right on the showcase deck) and move the
  comment-mode toggle to the opposite corner so the two do not collide.
- Keep the nav pill quiet. If a centered composer's Save button can land over the fixed nav, give the
  nav `pointer-events: none` and re-enable it on its buttons (`button:not(:disabled)`), so a click passes
  through to the composer.

## Narrative and persuasion

- **Pain before mechanism.** Open by naming the frustration the audience feels, in their words, BEFORE
  you show the loop/diagram/mechanism. A mechanism slide that arrives before the "why" lands falls flat.
- **Make the pain concrete.** A muted row of real "lost" phrasings (the exact vague things people type
  into chat) is more visceral than an abstract claim. Make every such callback pay off later in the
  deck; a callback that never recurs is a dud.
- **Benefit, not demo description.** The strongest real estate (slide 1 pills, section openers) should
  state what the user gets, not describe what the deck is about.
- **One running example.** Thread a single concrete scenario through every slide.
- **Install CTA early AND at the close.** Do not hide the install behind the whole talk. Put the exact
  commands on an early slide (with the live-demo/repo/tutorial links) and again on the closing slide.
- **Show the actual output.** The deck claims a "structured Copy all bundle" repeatedly; show a real
  4-6 line sample of that bundle (quote / path / stable id / note) somewhere in the technical half. The
  single most convincing thing a review-tool deck can do is show its own artifact.

## Review-surface patterns (CHM-specific)

- The deck IS a commentable document: it should demonstrate commenting on a chart, a table cell, a
  Mermaid node, a diff line, a board card, and a checklist item, so "comment on anything" is shown, not
  told. Keep the count you claim ("N targets") in sync with what the deck actually demonstrates.
- **Copyable commands.** Split each install command into its own block. A whole-row click-to-copy is a
  nice convenience on top of the per-block Copy button, but implement it correctly: `navigator.clipboard
  .writeText` is async - only fall back to `execCommand` when the promise REJECTS, never synchronously,
  or the fallback silently never runs on a denied/insecure clipboard. Keep the delegated handler guarded
  off in comment mode.
- **Always-paint CDN-dependent content.** Anything that renders from a CDN (Mermaid, Chart) can be slow
  or blocked. Author a static fallback that is always painted and hide it via `:has(pre.mermaid svg)`
  once the live render exists, so a blocked CDN never leaves a blank box on stage.

## Card systems and variety

- Break the "four identical cards" look with a small on-brand glyph badge per card heading. It reads as
  an iconographic system and costs no height.
- When card headings wrap unevenly (one line vs two), reserve heading height (`min-height`) so every
  card's body starts on the same baseline.
- Vary layout across a run of similar slides (asymmetric bento column ratios, a table, a specimen) so
  four consecutive card grids do not blur together.

## Contrast, clipping, and validation discipline

- `deck_validate.py --strict` is the authoritative gate for BOTH vertical clip and AA contrast on the
  content region. Run it after every change. See [deck-contract.md](deck-contract.md) for exactly which
  color pairs it checks.
- Do not lean on `aria-hidden`/`cm-skip` to dodge the contrast check for text a viewer must actually
  read; darken muted/echo text enough to read from the back of a room.
- **Scope emphasis styles.** A "winning row" or "highlight" rule written as `table tbody tr:last-child`
  leaks onto every other table in the deck (this shipped as a bug: a data table's last row looked like a
  comparison "winner"). Scope such rules with a class on the specific element.

## CSS gotchas specific to CHM decks

- **Never use `data-slide-id` in a CSS selector.** The export test counts `data-slide-id` occurrences to
  assert uniqueness; a selector that repeats an id fails it. Use a class instead.
- Negate a CSS function with `calc(-1 * ...)`; a leading `-clamp(...)`/`-min(...)` is silently dropped by
  the browser (from frontend-slides `STYLE_PRESETS.md`).
- The runtime adds its own Copy button to `pre > code`. For a display-only sample you do not want a Copy
  button on, use a `<pre>` without a nested `<code>`.

## Verify like a reviewer

Author-time validation passing is necessary, not sufficient. Render the deck with
`tools/audit.mjs --target <deck> --out <dir> --max-slides <n>` and actually LOOK at the slide PNGs at
1920x1080, one by one, as an audience member would. The highest-leverage polish this deck got came from
rendering every slide and running several different high-capability models over the screenshots in
parallel, each on a distinct aspect (layout, narrative, code/CSS), then applying only the changes they
agreed on. Treat the first render as a bug hunt, not a confirmation.
