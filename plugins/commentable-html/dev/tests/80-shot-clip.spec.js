import { test, expect } from "@playwright/test";
import { spawnSync } from "child_process";
import fs from "fs";
import path from "path";
import { DEV, PLUGIN } from "./helpers.js";
import {
  CLIP_QUANTUM, DEVICE_SCALE, DIMENSION_DELTA_PX, MAX_WIDTH_DELTA, ALLOWED_HEIGHT_DELTAS,
  quantizeClipHeight, clampedClipHeight,
} from "../tools/shot_clip.mjs";

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

test("capture_tutorial reports the shared clip geometry and budgets it renders with (CMH-BUILD-17)", () => {
  // The capture tool must consume the shared module rather than carry its own copies, so the
  // quantum, the device scale, and the comparison budgets cannot drift apart across the tool, the
  // heavy freshness gate, and this suite.
  const info = printPaths();
  expect(info.clipQuantum).toBe(CLIP_QUANTUM);
  expect(info.deviceScale).toBe(DEVICE_SCALE);
  expect(info.maxWidthDelta).toBe(MAX_WIDTH_DELTA);
  // The height allowance is two EXACT values, not a band: a sub-quantum delta is real content added
  // or removed at the bottom edge, which the overlap-cropped pixel diff cannot see, so it must not
  // be admitted. Width is not quantized and must not inherit the quantum-sized allowance.
  expect(info.allowedHeightDeltas).toEqual(ALLOWED_HEIGHT_DELTAS);
  expect(info.allowedHeightDeltas).not.toContain(DIMENSION_DELTA_PX - 1);
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
