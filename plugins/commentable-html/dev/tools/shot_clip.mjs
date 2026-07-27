// Shared clip geometry for the tutorial screenshot capture (dev-only, not shipped).
//
// Element-clipped shots are sized from the element's LAID-OUT height, and that height depends on
// FONT METRICS. `freezeMotion` pins the capture to `font-family: Arial, sans-serif !important`, and
// that pin is only as portable as Arial is: Windows resolves real Arial, while the pinned Linux
// container ships no Arial at all and fontconfig substitutes Liberation Sans. Liberation Sans is
// metric-compatible with Arial in ADVANCE WIDTHS but not in vertical metrics, which is exactly why
// width never drifts and height does. Issue #698 measured it on `.cmh-checklist` under identical CSS
// (font-size 15px, line-height 23.25px) and an identical lockfile-pinned chromium: each row renders
// 23.391 CSS px tall on Linux versus 23.250 on Windows, so the element measures 230 CSS px instead of
// 228 - a 4 device px PNG delta at deviceScaleFactor 2, with no content change.
//
// Snapping every content-derived clip height onto a coarse grid collapses that drift onto a single
// value, so the committed PNG dimensions stop depending on which renderer produced them.
//
// PRECONDITION for the "at most one quantum" guarantee: the per-shot renderer drift must stay under
// CLIP_QUANTUM. The drift is proportional to the number of text rows in the clip (about 0.6% of the
// clip height for the measured font pair), so a full-viewport-tall 900 CSS px element drifts about
// 5.4 px - inside the quantum, but only by ~1.5x. A materially taller text clip, or a font pair with
// a wider metric gap, would move TWO quanta and fail --check loudly. That is the signal to raise
// CLIP_QUANTUM, not to widen the comparison budget.
export const CLIP_QUANTUM = 8;
export const DEVICE_SCALE = 2;
export const DIMENSION_DELTA_PX = CLIP_QUANTUM * DEVICE_SCALE;

// Comparison budgets for --check, kept beside the geometry that justifies them.
//
// Width is NOT quantized - the layout width comes from the fixed viewport and was never observed to
// drift - so it keeps a strict budget.
export const MAX_WIDTH_DELTA = 2;
// Height IS quantized on both sides for content-derived clips, so the only legitimate cross-renderer
// difference is a grid-line straddle: exactly one whole quantum, in device pixels, BETWEEN TWO
// HEIGHTS THAT ARE BOTH ON THE GRID. Both halves matter. Restricting it to an exact value rather than
// a tolerance band keeps a sub-quantum delta failing, because that can only be real content added or
// removed at the bottom edge, which the overlap-cropped pixel diff cannot see. Requiring both heights
// to be on the grid keeps the allowance away from clips that are NOT quantized - a fixed 1320x900
// viewport shot is 1800 device px tall, off-grid, so appending or removing 16 visible rows there is
// real content and still fails.
export function heightDeltaAllowed(expectedHeight, actualHeight) {
  const delta = Math.abs(expectedHeight - actualHeight);
  if (delta === 0) return true;
  if (delta !== DIMENSION_DELTA_PX) return false;
  return expectedHeight % DIMENSION_DELTA_PX === 0 && actualHeight % DIMENSION_DELTA_PX === 0;
}

export function quantizeClipHeight(height) {
  const raw = Math.max(1, Math.ceil(height));
  return Math.ceil(raw / CLIP_QUANTUM) * CLIP_QUANTUM;
}

// A clip that must not exceed a bound (the viewport, or a panel's own height) is quantized LAST and
// DOWNWARD, so a clamped clip lands on the grid too. Quantizing up and then clamping would leave the
// height equal to the bound, which is off-grid: an element that clamps on one renderer but not the
// other would then differ by an arbitrary sub-quantum amount and hard-fail --check - the #698 class
// moved rather than fixed. The bound wins over the grid only when it is smaller than one quantum,
// which cannot be gridded at all.
export function clampedClipHeight(height, bound) {
  const capped = Math.min(quantizeClipHeight(height), Math.max(1, Math.floor(bound)));
  const onGrid = Math.floor(capped / CLIP_QUANTUM) * CLIP_QUANTUM;
  return onGrid >= CLIP_QUANTUM ? onGrid : capped;
}
