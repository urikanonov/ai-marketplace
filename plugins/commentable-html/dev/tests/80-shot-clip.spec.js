import { test, expect } from "@playwright/test";
import { spawnSync } from "child_process";
import fs from "fs";
import path from "path";
import { DEV, PLUGIN } from "./helpers.js";
import {
  CLIP_QUANTUM, DEVICE_SCALE, DIMENSION_DELTA_PX, MAX_WIDTH_DELTA,
  quantizeClipHeight, clampedClipHeight, heightDeltaAllowed,
} from "../tools/shot_clip.mjs";
import {
  compareImages, dimensionsMatch, imagesMatch, withinPixelBudget,
  MAX_DIFF_PIXELS, PIXEL_CHANNEL_TOLERANCE,
} from "../tools/shot_compare.mjs";
import { freezeBuildStamps, STAMP_DATE, STAMP_VERSION } from "../tools/shot_stamps.mjs";

// CMH-BUILD-17. Element-clipped tutorial screenshots are sized from the element's LAID-OUT height,
// which depends on font metrics: the report font stack has no entry present on every OS, so the same
// checklist measures 228 CSS px on a Windows host and 230 in the pinned Linux renderer (issue #698).
// These tests pin the geometry contract that makes the resulting PNG dimensions renderer-independent.

const ASSETS = path.join(PLUGIN, "docs", "assets");
// Full-viewport clips are a fixed 1320x900 CSS px box, so their height is a constant rather than a
// content-derived measurement and is deliberately NOT quantized.
const FULL_VIEWPORT_PX = 900 * DEVICE_SCALE;

// PNG dimensions live in the IHDR chunk: width at byte 16, height at byte 20, both big-endian.
function pngSize(file) {
  const buf = fs.readFileSync(file);
  return { width: buf.readUInt32BE(16), height: buf.readUInt32BE(20) };
}

function printPaths() {
  const dry = spawnSync("node", [path.join(DEV, "tools", "capture_tutorial.mjs"), "--print-paths"],
    { encoding: "utf8" });
  expect(dry.error, String(dry.error)).toBeFalsy();
  expect(dry.status, dry.stderr).toBe(0);
  return JSON.parse(dry.stdout);
}

test("quantizeClipHeight collapses any sub-quantum drift onto the grid (CMH-BUILD-17)", () => {
  // The exact pair measured in issue #698 for .cmh-checklist: Windows 228, pinned Linux 230.
  expect(quantizeClipHeight(228)).toBe(quantizeClipHeight(230));
  // The guarantee the --check budget is built on: while the renderer drift stays under one quantum,
  // two measurements land either on the SAME grid value or exactly one quantum apart - never
  // anything in between, and never two quanta. Sweeping drift to the full quantum pins the
  // boundary (an identity function fails at drift 0, which must not move the clip at all).
  for (let base = 1; base <= 400; base += 1) {
    for (let drift = 0; drift <= CLIP_QUANTUM; drift += 1) {
      const moved = quantizeClipHeight(base + drift) - quantizeClipHeight(base);
      expect([0, CLIP_QUANTUM], `drift ${drift} from ${base} moved the clip by ${moved}`)
        .toContain(moved);
    }
  }
});

test("quantizeClipHeight never crops the element and is idempotent (CMH-BUILD-17)", () => {
  for (const raw of [1, 7, 8, 9, 70, 228, 229.64, 230, 477, 900]) {
    const q = quantizeClipHeight(raw);
    expect(q, `${raw} quantized below its own height`).toBeGreaterThanOrEqual(raw);
    expect(q - raw, `${raw} gained more than a whole quantum of padding`).toBeLessThan(CLIP_QUANTUM);
    expect(q % CLIP_QUANTUM, `${raw} did not land on the grid`).toBe(0);
    expect(quantizeClipHeight(q), `${raw} is not idempotent`).toBe(q);
  }
});

test("a clamped clip lands on the grid and never exceeds its bound (CMH-BUILD-17)", () => {
  // Quantizing UP and then clamping would leave the height equal to the bound, which is off-grid: an
  // element that clamps on one renderer but not the other would then differ by an arbitrary
  // sub-quantum amount - the #698 class moved rather than fixed. So the clamp quantizes DOWNWARD.
  for (let bound = CLIP_QUANTUM; bound <= 920; bound += 1) {
    for (const raw of [bound - 9, bound - 1, bound, bound + 1, bound + 9]) {
      if (raw < 1) continue;
      const h = clampedClipHeight(raw, bound);
      expect(h, `clamped height ${h} exceeds its bound ${bound}`).toBeLessThanOrEqual(bound);
      expect(h % CLIP_QUANTUM, `raw ${raw} bound ${bound} produced off-grid height ${h}`).toBe(0);
    }
  }
  // An unclamped raw height is unaffected by a bound it never reaches.
  expect(clampedClipHeight(228, 900)).toBe(quantizeClipHeight(228));
  // A bound narrower than one quantum cannot be gridded; the bound still wins, never the grid.
  expect(clampedClipHeight(100, 5)).toBe(5);
});

test("the straddle allowance applies only between two on-grid heights (CMH-BUILD-17)", () => {
  const onGrid = 464;
  expect(onGrid % DIMENSION_DELTA_PX).toBe(0);
  // Identical heights always match, quantized or not.
  expect(heightDeltaAllowed(onGrid, onGrid)).toBe(true);
  expect(heightDeltaAllowed(FULL_VIEWPORT_PX, FULL_VIEWPORT_PX)).toBe(true);
  // A grid-line straddle between two quantized clips is the one tolerated difference.
  expect(heightDeltaAllowed(onGrid, onGrid - DIMENSION_DELTA_PX)).toBe(true);
  expect(heightDeltaAllowed(onGrid - DIMENSION_DELTA_PX, onGrid)).toBe(true);
  // A sub-quantum or over-quantum shift is real content, not renderer drift.
  for (const delta of [1, 4, DIMENSION_DELTA_PX - 1, DIMENSION_DELTA_PX + 1, DIMENSION_DELTA_PX * 2]) {
    expect(heightDeltaAllowed(onGrid, onGrid - delta), `delta ${delta} must not be allowed`).toBe(false);
  }
  // A fixed-viewport shot is NOT quantized (1800 is off-grid), so appending or removing exactly one
  // quantum of visible rows there is real content and must still fail.
  expect(FULL_VIEWPORT_PX % DIMENSION_DELTA_PX).not.toBe(0);
  expect(heightDeltaAllowed(FULL_VIEWPORT_PX, FULL_VIEWPORT_PX - DIMENSION_DELTA_PX)).toBe(false);
  expect(heightDeltaAllowed(FULL_VIEWPORT_PX, FULL_VIEWPORT_PX + DIMENSION_DELTA_PX)).toBe(false);
});

test("dimensionsMatch keeps width strict and rejects an unreadable PNG (CMH-BUILD-17)", () => {
  const base = { width: 2444, height: 464 };
  expect(dimensionsMatch(base, { width: 2444, height: 464 })).toBe(true);
  expect(dimensionsMatch(base, { width: 2444 + MAX_WIDTH_DELTA, height: 464 })).toBe(true);
  // Width is not quantized, so it must not inherit the quantum-sized allowance.
  expect(dimensionsMatch(base, { width: 2444 + DIMENSION_DELTA_PX, height: 464 })).toBe(false);
  expect(dimensionsMatch(base, null)).toBe(false);
  expect(dimensionsMatch(null, base)).toBe(false);
});

test("capture_tutorial reports the shared clip geometry and budgets it renders with (CMH-BUILD-17)", () => {
  // The capture tool must consume the shared module rather than carry its own copies, so the
  // quantum, the device scale, and the comparison budgets cannot drift apart across the tool, the
  // heavy freshness gate, and this suite.
  const info = printPaths();
  expect(info.clipQuantum).toBe(CLIP_QUANTUM);
  expect(info.deviceScale).toBe(DEVICE_SCALE);
  expect(info.maxWidthDelta).toBe(MAX_WIDTH_DELTA);
  expect(info.quantumStraddlePx).toBe(DIMENSION_DELTA_PX);
  expect(info.maxWidthDelta).toBeLessThan(DIMENSION_DELTA_PX);
});

// This pins the committed BASELINES (a fresh-capture assertion lives in the heavy suite, which is the
// only place the capture actually runs). The expected file list comes from the tool's own registry,
// not a directory glob, so a shot renamed or dropped cannot silently fall out of the check.
test("every committed tutorial shot is on the clip grid or full-viewport (CMH-BUILD-17)", () => {
  const scenes = printPaths().scenes;
  const expected = Object.entries(scenes)
    .flatMap(([prefix, shots]) => shots.map((name) => `${prefix}-${name}.png`));
  expect(expected.length, "the capture registry reported no shots to check").toBeGreaterThan(0);
  const missing = expected.filter((name) => !fs.existsSync(path.join(ASSETS, name)));
  expect(missing, "the capture registry names shots that are not committed").toEqual([]);
  const offGrid = expected
    .map((name) => ({ name, ...pngSize(path.join(ASSETS, name)) }))
    .filter((s) => s.height % DIMENSION_DELTA_PX !== 0 && s.height !== FULL_VIEWPORT_PX)
    .map((s) => `${s.name} (${s.width}x${s.height})`);
  expect(offGrid, "these shots are neither on the clip grid nor the fixed full-viewport height, so "
    + "their height can drift with the renderer's font metrics (run 'npm run shots')").toEqual([]);
});

// CMH-BUILD-19. The pixel diff is now channel-EXACT with only a small absolute allowance, because
// both sides of every comparison are the one digest-pinned renderer. These tests are hermetic: they
// alter a COPY of a committed shot in a canvas and diff it with the shared comparator, so they pin
// the budget without running a capture.
const COMPARE_TMP = path.join(PLUGIN, "..", "..", "tmp", "shot-compare-spec", String(process.pid));

test.afterAll(() => {
  fs.rmSync(COMPARE_TMP, { recursive: true, force: true });
});

// Re-encode the source PNG through a canvas, optionally altering a region, and write the result.
// `mode` "fill" paints an opaque block (an obvious regression); "wash" nudges every channel in the
// region by a small delta (a low-contrast regression the old tolerance-96 budget could not see).
async function reencode(page, source, name, alter) {
  fs.mkdirSync(COMPARE_TMP, { recursive: true });
  const out = path.join(COMPARE_TMP, name);
  const base64 = await page.evaluate(async ({ sourceBase64, region }) => {
    const img = new Image();
    img.src = "data:image/png;base64," + sourceBase64;
    await img.decode();
    const canvas = document.createElement("canvas");
    canvas.width = img.naturalWidth;
    canvas.height = img.naturalHeight;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    ctx.drawImage(img, 0, 0);
    if (region && region.mode === "fill") {
      ctx.fillStyle = "#ff0000";
      ctx.fillRect(region.x, region.y, region.w, region.h);
    } else if (region && region.mode === "wash") {
      const patch = ctx.getImageData(region.x, region.y, region.w, region.h);
      const d = patch.data;
      for (let i = 0; i < d.length; i += 4) {
        d[i] = Math.min(255, d[i] + region.delta);
        d[i + 1] = Math.min(255, d[i + 1] + region.delta);
        d[i + 2] = Math.min(255, d[i + 2] + region.delta);
      }
      ctx.putImageData(patch, region.x, region.y);
    }
    return canvas.toDataURL("image/png").split(",")[1];
  }, { sourceBase64: fs.readFileSync(source).toString("base64"), region: alter || null });
  fs.writeFileSync(out, Buffer.from(base64, "base64"));
  return out;
}

test("the pixel diff is exact and rejects a deliberately altered shot (CMH-BUILD-19)", async ({ browser }) => {
  const page = await browser.newPage();
  try {
    // The smallest committed shot that carries the review-layer chrome.
    const source = path.join(ASSETS, "garden-13-comment-search.png");
    // Control: a byte copy, and a canvas round-trip with no alteration, both still match. Without
    // this the failures below could come from the re-encode rather than from the alteration.
    const copy = path.join(COMPARE_TMP, "unaltered-copy.png");
    fs.mkdirSync(COMPARE_TMP, { recursive: true });
    fs.copyFileSync(source, copy);
    expect(await imagesMatch(page, source, copy),
      "an identical copy of a committed shot must pass the budget").toBe(true);
    const roundTrip = await reencode(page, source, "round-trip.png", null);
    expect(await imagesMatch(page, source, roundTrip),
      "a lossless canvas round-trip must pass the budget").toBe(true);
    // A single 4x4 opaque block - far smaller than any UI element, and utterly invisible to the
    // retired budget (20 percent of pixels at a channel delta of 96 after a 2x downsample).
    const block = await reencode(page, source, "altered-block.png",
      { mode: "fill", x: 40, y: 200, w: 4, h: 4 });
    const blockResult = await compareImages(page, source, block);
    expect(blockResult.ok, "a 16 px repaint must fail the exact budget").toBe(false);
    // A red gate must say HOW far off it is, not just that it is off, or a CI failure is unreadable.
    expect(blockResult.different, "the failure must report the differing-pixel count")
      .toBeGreaterThan(MAX_DIFF_PIXELS);
    expect(blockResult.reason).toContain("differing px");
    expect(blockResult.reason).toContain(String(PIXEL_CHANNEL_TOLERANCE));
    // A low-contrast wash: every channel in a large region shifted by 3 - one step past the
    // tolerance - which the retired tolerance (96) and 64-step quantize erased entirely.
    const wash = await reencode(page, source, "altered-wash.png",
      { mode: "wash", x: 40, y: 500, w: 300, h: 300, delta: PIXEL_CHANNEL_TOLERANCE + 1 });
    expect(await imagesMatch(page, source, wash),
      "a wash one step past the channel tolerance must fail").toBe(false);
    // ...while a wash INSIDE the tolerance passes: that is the deliberate insurance for a
    // least-significant-bit raster difference on another host CPU, and nothing wider.
    const lsb = await reencode(page, source, "altered-lsb.png",
      { mode: "wash", x: 40, y: 500, w: 300, h: 300, delta: PIXEL_CHANNEL_TOLERANCE });
    expect(await imagesMatch(page, source, lsb),
      "a wash within the channel tolerance is absorbed on purpose").toBe(true);
    // A dimension change is reported as such rather than as a pixel count.
    const shorter = path.join(COMPARE_TMP, "shorter.png");
    fs.writeFileSync(shorter, Buffer.from("not a png"));
    const unreadable = await compareImages(page, source, shorter);
    expect(unreadable.ok).toBe(false);
    expect(unreadable.reason).toContain("dimensions");
  } finally {
    await page.close();
  }
});

test("no differing pixel is allowed, whatever the shot size (CMH-BUILD-19)", () => {
  // The budget is absolute and zero: it does not scale with the image, so a large shot cannot buy a
  // proportionally larger allowance the way a ratio budget would.
  for (const total of [372 * 432, 800 * 960, 2640 * 1800]) {
    expect(withinPixelBudget(0, total)).toBe(true);
    expect(withinPixelBudget(1, total)).toBe(false);
  }
  // A nonsense count or an empty image never passes.
  expect(withinPixelBudget(1, 0)).toBe(false);
  expect(withinPixelBudget(NaN, 100)).toBe(false);
  expect(withinPixelBudget(0, NaN)).toBe(false);
});

test("the budget is exact, its tolerance is invisible, and the tool reports both (CMH-BUILD-19)", () => {
  // Two independent runs of the pinned renderer produce BYTE-IDENTICAL PNGs (measured for all 19
  // committed shots, in the container and on a host browser alike, including under concurrency), so
  // no differing pixel is allowed at all - the volatile build stamps are frozen at capture time
  // (shot_stamps.mjs) rather than bought off with an allowance that would also hide a regression.
  expect(MAX_DIFF_PIXELS).toBe(0);
  // The channel tolerance is insurance for the one input the container digest does not pin - the
  // host CPU's raster rounding - so it must stay at least an order of magnitude below the retired
  // budget (96) and small enough to be invisible.
  expect(PIXEL_CHANNEL_TOLERANCE).toBeGreaterThan(0);
  expect(PIXEL_CHANNEL_TOLERANCE).toBeLessThanOrEqual(4);
  // The tool renders and verifies with the SAME budget and placeholders this suite asserts, so the
  // gate, the capture and the specs that mirror them cannot drift apart.
  const info = printPaths();
  expect(info.pixelChannelTolerance).toBe(PIXEL_CHANNEL_TOLERANCE);
  expect(info.maxDiffPixels).toBe(MAX_DIFF_PIXELS);
  expect(info.stampVersion).toBe(STAMP_VERSION);
  expect(info.stampDate).toBe(STAMP_DATE);
});

test("the capture freezes the volatile build stamps, and only in the review layer (CMH-BUILD-19)", async ({ browser }) => {
  const page = await browser.newPage();
  try {
    // A synthetic stand-in for the review layer: the sidebar version badge, the "Generated on" line,
    // the footer, and a Help heading that wraps the version in a longer string - plus an authored
    // document that legitimately mentions the same version and date, and layer copy (a rendered
    // comment) that merely looks like a stamp and must NOT be rewritten.
    await page.setContent(`<!doctype html><html><body>
      <div id="commentRoot"><p>Upgraded to 1.255.0 on Generated on: Jul 26, 2026</p></div>
      <div class="cm-sidebar">
        <span id="cmVersion">v1.255.0</span>
        <div id="cmGenerated">Generated on: Jul 26, 2026</div>
        <div id="cmLastComment">Last comment: Jan 1, 2024, 12:00</div>
        <div class="cm-card">Generated on: Jul 26, 2026 - and v1.255.0 looks wrong here</div>
      </div>
      <div class="cm-help-head"><h2><svg></svg> Commentable HTML v1.255.0 - Help</h2></div>
      <footer class="cm-footer"><span class="cm-footer-ver">v1.255.0</span>
        <span class="cm-footer-gen">Generated Jul 26, 2026</span></footer>
      <script>window.__commentableHtmlVersion = "1.255.0";</script>
    </body></html>`);
    const frozen = await freezeBuildStamps(page);
    expect(frozen, "the stamps in the review layer must have been rewritten").toBeGreaterThan(0);
    const text = (sel) => page.locator(sel).innerText();
    expect(await text("#cmVersion")).toBe(`v${STAMP_VERSION}`);
    expect(await text(".cm-footer-ver")).toBe(`v${STAMP_VERSION}`);
    // The label survives - only the date is replaced - so rewording it stays a visible change.
    expect(await text("#cmGenerated")).toBe(`Generated on: ${STAMP_DATE}`);
    expect(await text(".cm-footer-gen")).toBe(`Generated ${STAMP_DATE}`);
    // A version embedded in a longer heading is replaced in place, leaving the heading intact.
    expect(await text(".cm-help-head h2")).toContain(`Commentable HTML v${STAMP_VERSION} - Help`);
    // Deterministic layer text is untouched...
    expect(await text("#cmLastComment")).toBe("Last comment: Jan 1, 2024, 12:00");
    // ...and so is any other layer copy that merely looks like a stamp: the freeze targets the
    // stamped elements only, so a rendered comment cannot be silently rewritten.
    expect(await text(".cm-card")).toBe("Generated on: Jul 26, 2026 - and v1.255.0 looks wrong here");
    // ...and the authored document is never rewritten, even when it names the same version or date.
    expect(await text("#commentRoot p")).toBe("Upgraded to 1.255.0 on Generated on: Jul 26, 2026");
    // Freezing twice must not keep changing the page, or a shot would depend on how often it ran.
    expect(await freezeBuildStamps(page), "the freeze must be idempotent").toBe(0);
    // A stamp that is not a real date (no data-generated, so the runtime renders "unknown") is left
    // alone: it is a broken build stamp, and the shot must move so the gate reports it.
    await page.locator("#cmGenerated").evaluate((el) => { el.textContent = "Generated on: unknown"; });
    expect(await freezeBuildStamps(page), "a non-date stamp must not be frozen").toBe(0);
    expect(await text("#cmGenerated")).toBe("Generated on: unknown");
    // An empty value must not be mis-split into a new label either (it is not a date, so it stays).
    await page.locator("#cmGenerated").evaluate((el) => { el.textContent = "Generated on: "; });
    expect(await freezeBuildStamps(page), "an empty stamp must not be frozen").toBe(0);
    expect(await page.locator("#cmGenerated").textContent()).toBe("Generated on: ");
    // Date.parse alone would accept these: "0" is a year shorthand and "Feb 31" silently rolls over
    // into March. Only a value the runtime could have RENDERED is frozen, so both stay visible.
    for (const broken of ["0", "Feb 31, 2026", "2026-07-26", "Jul 26, 2026, 12:00"]) {
      await page.locator("#cmGenerated").evaluate((el, value) => {
        el.textContent = `Generated on: ${value}`;
      }, broken);
      expect(await freezeBuildStamps(page), `a malformed stamp (${broken}) must not be frozen`).toBe(0);
      expect(await text("#cmGenerated")).toBe(`Generated on: ${broken}`);
    }
  } finally {
    await page.close();
  }
});


