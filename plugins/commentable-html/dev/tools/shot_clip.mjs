// Shared clip geometry for the tutorial screenshot capture (dev-only, not shipped).
//
// Element-clipped shots are sized from the element's LAID-OUT height, and that height depends on
// FONT METRICS. The example reports use the native-UI stack
// ("Segoe UI", Aptos, Calibri, -apple-system, BlinkMacSystemFont, sans-serif), which has no entry
// present on every operating system, so a Windows host resolves Segoe UI while the pinned Linux
// renderer falls through to its generic sans-serif. Issue #698 measured the result on
// `.cmh-checklist`: identical CSS (font-size 15px, line-height 23.25px) and identical chromium, but
// each row renders 0.141 CSS px taller on Linux, so the element measures 228 CSS px on Windows and
// 230 in the container - a 4 device px PNG delta at deviceScaleFactor 2, with no content change.
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
// Height IS quantized on both sides, so the only legitimate cross-renderer difference is a grid-line
// straddle: exactly one whole quantum, in device pixels. This is deliberately an exact-value
// allowance rather than a tolerance band, because a band would also wave through an in-between
// delta - real content added or removed at the bottom edge, which the overlap-cropped pixel diff
// cannot see. Quantizing already absorbs sub-quantum content changes into an IDENTICAL height, where
// the pixel diff does see them.
export const ALLOWED_HEIGHT_DELTAS = [0, DIMENSION_DELTA_PX];

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
