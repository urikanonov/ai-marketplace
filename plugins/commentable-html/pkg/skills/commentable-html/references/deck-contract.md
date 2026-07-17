# Deck runtime interface contract

This is the frozen interface between the three deck workstreams: the author-time tools
(`tools/deck/deck_scaffold.py`, `tools/deck/deck_validate.py`) and the commentable-html runtime (the deck
profile in the layer JS). Both sides build against these names so they can be developed and
tested independently. Do not change a name here without updating the scaffold, the validator, and
the runtime together.

## Contents

- [Activation signal](#activation-signal)
- [Authoring commands and PPTX conversion](#authoring-commands-and-pptx-conversion)
- [Slide design and fonts](#slide-design-and-fonts)
- [Slide markup](#slide-markup)
  - [Stable slide id](#stable-slide-id)
- [Controller (in the shipped layer JS, not the deck body)](#controller-in-the-shipped-layer-js-not-the-deck-body)
- [Anchoring (comments to slides)](#anchoring-comments-to-slides)
- [Content scripts and validator scope](#content-scripts-and-validator-scope)
  - [Contrast validation scope](#contrast-validation-scope)

## Activation signal

A deck is a commentable-html document whose content root carries `data-cmh-mode="deck"`:

```html
<main id="commentRoot" data-comment-key="..." data-doc-label="..." data-cmh-mode="deck">
```

The runtime reads this once at startup. When present it activates the **deck profile** and does
NOT install the document-mode features that assume a scrolling flow document (heading deep-links,
collapsible-section carets, the scroll-spy table-of-contents side menu, the scroll-progress
bubble, and the runtime footer). When absent the layer behaves exactly as today.

## Authoring commands and PPTX conversion

Use `tools/deck/deck_scaffold.py` to create a commentable-native fixed-stage deck. It accepts either a
slide-sections HTML fragment or placeholder count:

```bash
python tools/deck/deck_scaffold.py --content slides.html --label "Roadmap" --source roadmap.html --out roadmap.html
python tools/deck/deck_scaffold.py --slides 5 --label "Draft" --out draft-deck.html
```

`--content -` reads the slide fragment from stdin. `--slides N` emits N placeholder slides and must be at
least 1. `--out` is create-only unless `--force` is supplied, so a normal scaffold cannot overwrite a deck
that already has stable slide ids and review state. `--key auto` derives a comment key from `--label`;
`--source` sets `data-doc-source`; `--generated` stamps a deterministic generated timestamp.

For PowerPoint input, convert extracted content through `tools/deck/pptx_to_fragment.py` before scaffolding:

```bash
python tools/deck/pptx_to_fragment.py --input extracted-slides.json --out slides.html
some-extractor | python tools/deck/pptx_to_fragment.py --input - > slides.html
python tools/deck/pptx_to_fragment.py --pptx deck.pptx --out slides.html
```

`--input` reads the JSON shape produced by a PPTX extractor, or `-` for stdin. `--pptx` uses the vendored
local extractor and fails closed if extraction fails. In both paths, `pptx_to_fragment.py` HTML-escapes
extracted strings before they enter slide markup. Speaker notes are not supported and are ignored.

## Slide design and fonts

After scaffolding, fill the existing `.slide` sections in place. Prefer a NATIVE deck theme preset over
per-deck styling: pass `deck_scaffold.py --theme <name>` (or re-theme in place later with
`deck_theme.py apply --theme <name> <deck.html>`; `deck_theme.py list` prints the presets) to stamp a `<style id="cmh-deck-theme" class="cm-skip">` block of
allowlisted, system-font, contrast-safe deck tokens (`--slide-bg/-fg/-accent/-link/-border`, the
`--cmh-deck-*` component colours, and `--font-body/--font-display`). Presets live under
`tools/deck/themes/`; the block is `cm-skip`, so re-theming never shifts a stored comment offset.

Compose slide bodies from the reusable native recipe classes so a themed deck needs no per-deck CSS:

- `.cmh-slide-section` - a section-divider slide; put an uppercase `<p class="cmh-slide-kicker">` and an
  `<h2>` inside. Budget: a kicker + a heading + at most one line.
- `.cmh-slide-lede` - a large muted intro paragraph (about 26ch). Budget: one short paragraph.
- `.cmh-cols-2` - a two-column grid wrapper; put two child blocks inside. Budget: two columns.
- `.cmh-metric-grid` + `.cmh-metric` (with `.cmh-metric-value` + `.cmh-metric-label`) - stat cards.
  Budget: 2-4 metrics per row.
- `.cmh-pill` - an accent-filled inline label (uses `--slide-accent` with `--slide-accent-fg` text).
  Budget: one or two words.

These recipes consume the theme accent/muted/border tokens, so they recolour automatically under any
preset and stay coherent (with generic-dark defaults) on an unthemed deck.

For a bespoke, non-preset style a user explicitly asks for, you MAY read the vendored frontend-slides
references before authoring slide layouts:

- `vendor/frontend-slides/html-template.md`
- `vendor/frontend-slides/viewport-base.css`
- `vendor/frontend-slides/animation-patterns.md`
- `vendor/frontend-slides/STYLE_PRESETS.md`

Keep the style's palette, layout, spacing rhythm, and component grammar, but do not keep remote font
loads from the vendored examples. The upstream templates and style packs can include
`<link href="https://fonts.googleapis.com/...">`, `https://api.fontshare.com/...`, `@import`, or
`@font-face url(https://...)` examples. Run the deterministic fixer before validation:

```bash
python tools/deck/deck_fix_fonts.py deck.html
```

The fixer strips remote font links, remote CSS imports, and remote `@font-face` blocks, then maps copied
font stacks to system stacks:

- Serif or editorial faces: `"Iowan Old Style","Palatino Linotype","Georgia",serif`.
- Slab, display, or script faces: `"Impact","Rockwell","Arial Black",sans-serif` with heavier
  `letter-spacing`.
- Geometric or body sans faces: `system-ui,-apple-system,"Segoe UI",Roboto,sans-serif`.
- Monospace faces: `"Cascadia Code","Consolas","Fira Code",ui-monospace,monospace`.
- CJK faces: drop the explicit remote family and let the system CJK face resolve.

If a deck truly needs a specific face, obtain the `.woff2` locally and embed it as a `@font-face` whose
`src` is a `data:font/woff2;base64,...` URI, then rerun `deck_validate.py`.

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

### Contrast validation scope

`deck_validate.py` also runs the shipped `tools/validate/cmhval/contrast.py` WCAG contrast helper
over the deck CONTENT region. It errors when an explicit foreground/background pair has a contrast
ratio below the configurable default threshold of 4.5:1. The static scope is intentionally
deterministic: inline `style` attributes, CSS rules whose same declaration block contains `color`
plus the last effective `background` or `background-color`, and the deck theme variable pairs
`--slide-fg` with `--slide-bg` / `--stage-bg`, with simple custom-property (`var(...)`) resolution.
The validator names the offending element, selector, or variable pair and both colors. It does not
attempt a full CSS cascade, inherited color lookup, media-query evaluation, or alpha compositing
against unknown ancestor backgrounds; semi-transparent backgrounds are skipped for that reason. Use
explicit text/background pairs for any deck theme override that must be author-time checked. The
variable pairs are resolved from the custom properties declared in the document; the native flow
declares the theme tokens only in the `cmh-deck-theme` block (there is no per-deck CSS), so that block
is authoritative. A deck that additionally redefines a theme token (for example `--slide-bg`) in an
unrelated rule can skew a variable-pair check - do not redefine the theme tokens outside the theme block.

The strict "zero network of any kind" guarantee (including the optional mermaid/Chart CDN loaders
and any chart init script) is asserted separately against the **Export Offline** deck.
