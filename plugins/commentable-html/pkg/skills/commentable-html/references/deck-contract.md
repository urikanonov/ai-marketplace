# Deck runtime interface contract

This is the frozen interface between the three deck workstreams: the author-time tools
(`deck/deck_scaffold.py`, `deck/deck_validate.py`) and the commentable-html runtime (the deck
profile in the layer JS). Both sides build against these names so they can be developed and
tested independently. Do not change a name here without updating the scaffold, the validator, and
the runtime together.

## Contents

- [Activation signal](#activation-signal)
- [Slide markup](#slide-markup)
  - [Stable slide id](#stable-slide-id)
- [Controller (in the shipped layer JS, not the deck body)](#controller-in-the-shipped-layer-js-not-the-deck-body)
- [Anchoring (comments to slides)](#anchoring-comments-to-slides)
- [Content scripts and validator scope](#content-scripts-and-validator-scope)

## Activation signal

A deck is a commentable-html document whose content root carries `data-cmh-mode="deck"`:

```html
<main id="commentRoot" data-comment-key="..." data-doc-label="..." data-cmh-mode="deck">
```

The runtime reads this once at startup. When present it activates the **deck profile** and does
NOT install the document-mode features that assume a scrolling flow document (heading deep-links,
collapsible-section carets, the scroll-spy table-of-contents side menu, the scroll-progress
bubble, and the runtime footer). When absent the layer behaves exactly as today.

## Slide markup

The content root holds one fixed-stage viewport; each slide is a `<section class="slide">`
nested inside the stage (NOT a direct child of `#commentRoot`):

```html
<main id="commentRoot" ... data-cmh-mode="deck">
  <div class="deck-viewport">
    <div class="deck-stage">
      <section class="slide" data-slide-id="slide-1a2b3c4d"> ... </section>
      ...
    </div>
  </div>
</main>
```

- Visibility is controlled by the `.active` / `.visible` classes (from `viewport-base.css`), never
  `display:none`. Exactly one slide is `.active` at a time. Hidden slides stay in the DOM
  (`visibility`, not `display`), so a comment highlight on a non-active slide is preserved and
  restores when that slide is shown.
- `data-slide-id` is a **stable** id (see below). It is the durable identity the deck-aware jump
  resolves a comment to; the 1-based ordinal is derived and never stored.

### Stable slide id

- Format: `slide-<8 lowercase hex>`, where the hex is the first 8 chars of
  `sha256(normalized-slide-text)`; on collision within one deck, append `-2`, `-3`, ...
- `deck_scaffold.py` mints ids at authoring time. On reiteration the agent edits the deck in place
  and keeps existing ids; a genuinely new slide gets a fresh id. `deck_scaffold.py` is create-only
  and refuses to overwrite an existing deck unless `--force` is passed, so absent `--force` a
  rescaffold can never silently renumber ids or reset comment state.

## Controller (in the shipped layer JS, not the deck body)

The deck body carries no executable script. The controller is exposed by the commentable-html
runtime as a global once the deck profile is active:

```js
window.__cmhDeck = {
  showSlideById(slideId),   // activate the slide with this stable id; returns true if found
  showSlide(index),         // activate by 0-based index; returns true if in range
  activeSlideId(),          // the stable id of the currently active slide
  slideCount(),             // number of slides
};
```

The runtime dispatches `document`-level `cmh:slidechange` (`detail: { slideId, index }`) on every
navigation. Comment-card / jump navigation resolves a comment's `slideId` via `showSlideById`
BEFORE flashing, because the layer's default `scrollIntoView` cannot reveal a hidden slide.

## Anchoring (comments to slides)

Deck comments use the **existing** commentable-html anchor shapes unchanged (text-offset,
structural, image, mermaid - see `comment-data-shape.md`). The deck layer adds NO new persisted
field: a comment does not store a `slideId`, and there is no `anchorType: "slide"`.

Instead, navigation is resolved from the live DOM. When a comment card is activated, the deck
runtime finds the comment's highlight/anchor element and calls
`anchor.closest(".slide")` to learn the owning slide, then `showSlideById(...)` to reveal it
BEFORE the layer's default `scrollIntoView` runs (which alone cannot reveal a hidden slide). A
coarse, whole-slide comment is simply a comment anchored to slide-level markup.

Documented limitation / future work: because anchors are not yet slide-relative, reordering
slides during reiteration can in principle move a text-offset anchor. Persisting a `slideId` and
slide-relative offsets (so a reorder can never move an anchor onto the wrong slide) is a planned
enhancement, not a current guarantee.

## Content scripts and validator scope

`deck_validate.py` does NOT add a separate deck-only script allowlist; the layer's own script
regions are covered by the base `validate.py`. A deck slide may legitimately carry a same-document
inline `<script>` (a chart init block) exactly like any other commentable-html document (mermaid
needs none - it is `<pre class="mermaid">` text). What the deck validator DOES enforce, fail-closed,
is the corporate-safety and XSS surface, using an **HTML parser** (not regex) to inspect tags and
attributes so a solidus separator (`<svg/onload=>`), an entity-encoded scheme (`&#106;avascript:`),
an unquoted attribute (`<img src=//evil>`), or an SVG `<image>`/`<use>` cannot bypass it: no remote
fonts, no remote media/resource fetch (`img`/`video`/`audio`/`source`/`track`/`input`/`image`/`use`/
`iframe`/`embed`/`object`/`link`/`base` to `http(s):` / `//`, or CSS `url()`), no remote CSS
`@import` (including a protocol-relative `@import "//..."`), no inline event-handler attributes, no
`iframe`/`object`/`embed`, no external `<script src>` and no `<script>` nested in `<svg>` (only a
same-document inline `<script>` such as a chart init is allowed), no `<meta http-equiv=refresh>`
redirect, and no `javascript:`/`vbscript:`/`data:text/html` or `../` URLs. An external hyperlink
(`<a href="https://...">`) is allowed because it is not egress. The content region is delimited by
the full HTML-comment markers and the LAST end marker is used, so slide text that contains the bare
marker string cannot truncate validation.

The deck must also carry a `prefers-reduced-motion` rule (supplied by the inlined
`viewport-base.css`); `deck_validate.py` errors if it is absent, so entrance animations always
honour a reduced-motion preference.

The strict "zero network of any kind" guarantee (including the optional mermaid/Chart CDN loaders
and any chart init script) is asserted separately against the **Export Offline** deck.

