// Tutorial screenshot quality gate (dev-only, not shipped). Reads every committed tutorial image
// under docs/assets and fails if any is too blurry, too faded/quantized, or too small - the exact
// classes of low-quality screenshot that used to reach the published tutorial. It reads the static
// committed PNG bytes (never a fresh capture), so the metrics are deterministic across platforms.
//
// Usage:
//   node tools/check_shot_quality.mjs            # gate: exit non-zero if any image fails
//   node tools/check_shot_quality.mjs --report   # print per-image metrics (crisp vs a degraded
//                                                 # copy) for calibration; never fails
import { chromium } from "@playwright/test";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const reportMode = process.argv.includes("--report");
// Optional positional arg overrides the assets dir (used by the negative test to point the gate at
// a temp dir holding a deliberately degraded image); defaults to the committed docs/assets.
const dirArg = process.argv.slice(2).find((a) => !a.startsWith("--"));
const ASSETS = dirArg ? path.resolve(dirArg) : path.resolve(HERE, "..", "..", "docs", "assets");

// Thresholds calibrated so every current crisp shot clears them with margin while a shot degraded
// by the old downsample+quantize normalization fails. Richness is the primary gate: a color-
// quantized (faded/banded) shot has ZERO off-grid pixels, while every real crisp shot has at least
// ~4% of them. Sharpness is a secondary floor against a smooth-blur regression. A resolution
// regression (e.g. capturing at 1x) is already caught by capture_tutorial.mjs --check, which pins
// each shot's dimensions, so no dimension floor is needed here. See report mode for the calibration.
const MIN_SHARPNESS = 60;      // variance of the Laplacian on luma; a smooth-blurred shot scores low.
const MIN_RICHNESS = 0.02;     // fraction of off-grid pixels; a color-quantized/faded shot scores 0.

// Compute the quality metrics of a decoded image, and (for calibration) of a copy degraded exactly
// the way the old normalization degraded shots, so a threshold can sit cleanly between the two.
async function metricsFor(page, base64) {
  return page.evaluate(async ({ b64 }) => {
    const img = new Image();
    img.src = "data:image/png;base64," + b64;
    await img.decode();
    const width = img.naturalWidth;
    const height = img.naturalHeight;

    function measure(data) {
      const n = width * height;
      const luma = new Float64Array(n);
      for (let i = 0, p = 0; i < data.length; i += 4, p += 1) {
        luma[p] = 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];
      }
      let sum = 0;
      let sumSq = 0;
      let count = 0;
      for (let y = 1; y < height - 1; y += 1) {
        for (let x = 1; x < width - 1; x += 1) {
          const idx = y * width + x;
          const lap = luma[idx - 1] + luma[idx + 1] + luma[idx - width] + luma[idx + width] - 4 * luma[idx];
          sum += lap;
          sumSq += lap * lap;
          count += 1;
        }
      }
      const mean = count ? sum / count : 0;
      const sharpness = count ? sumSq / count - mean * mean : 0;
      // A channel value is "on the degradation grid" if it is a multiple of the quantize step or the
      // pure white the old normalization snapped near-white pixels to. Anti-aliased (crisp) shots
      // have many off-grid gradient pixels; a color-quantized shot has almost none.
      const step = 64;
      let offGrid = 0;
      for (let i = 0; i < data.length; i += 4) {
        const onGrid = (v) => v % step === 0 || v === 255;
        if (!onGrid(data[i]) || !onGrid(data[i + 1]) || !onGrid(data[i + 2])) offGrid += 1;
      }
      return { sharpness, richness: offGrid / n };
    }

    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    ctx.drawImage(img, 0, 0);
    const crisp = measure(ctx.getImageData(0, 0, width, height).data);

    // Degraded copy: downsample by 2 (smoothing) then upsample nearest, and quantize colors - the
    // exact old normalization - so report mode shows the gap the thresholds must sit inside.
    const scale = 2;
    const small = document.createElement("canvas");
    small.width = Math.max(1, Math.ceil(width / scale));
    small.height = Math.max(1, Math.ceil(height / scale));
    const sctx = small.getContext("2d");
    sctx.imageSmoothingEnabled = true;
    sctx.drawImage(canvas, 0, 0, small.width, small.height);
    ctx.clearRect(0, 0, width, height);
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(small, 0, 0, width, height);
    const dImage = ctx.getImageData(0, 0, width, height);
    const d = dImage.data;
    for (let i = 0; i < d.length; i += 4) {
      d[i] = Math.round(d[i] / 64) * 64;
      d[i + 1] = Math.round(d[i + 1] / 64) * 64;
      d[i + 2] = Math.round(d[i + 2] / 64) * 64;
      if (d[i] === d[i + 1] && d[i + 1] === d[i + 2] && d[i] >= 192) {
        d[i] = 255;
        d[i + 1] = 255;
        d[i + 2] = 255;
      }
    }
    const degraded = measure(d);
    return { width, height, crisp, degraded };
  }, { b64: base64 });
}

async function run() {
  if (!fs.existsSync(ASSETS)) {
    console.error("check_shot_quality: assets dir not found:", ASSETS);
    return 2;
  }
  const files = fs.readdirSync(ASSETS).filter((f) => f.endsWith(".png")).sort();
  if (!files.length) {
    console.error("check_shot_quality: no PNG shots found in", ASSETS);
    return 2;
  }
  const browser = await chromium.launch();
  const page = await browser.newPage();
  const problems = [];
  try {
    for (const file of files) {
      const base64 = fs.readFileSync(path.join(ASSETS, file)).toString("base64");
      const m = await metricsFor(page, base64);
      if (reportMode) {
        console.log(
          `${file.padEnd(30)} ${m.width}x${m.height}  sharp=${m.crisp.sharpness.toFixed(1)}`
          + ` (deg ${m.degraded.sharpness.toFixed(1)})  rich=${m.crisp.richness.toFixed(3)}`
          + ` (deg ${m.degraded.richness.toFixed(3)})`);
        continue;
      }
      const failed = [];
      if (m.crisp.sharpness < MIN_SHARPNESS) failed.push(`blurry (sharpness ${m.crisp.sharpness.toFixed(1)} < ${MIN_SHARPNESS})`);
      if (m.crisp.richness < MIN_RICHNESS) failed.push(`faded/quantized (richness ${m.crisp.richness.toFixed(3)} < ${MIN_RICHNESS})`);
      if (failed.length) problems.push(`${file}: ${failed.join("; ")}`);
    }
  } finally {
    await page.close().catch(() => {});
    await browser.close();
  }
  if (reportMode) return 0;
  if (problems.length) {
    for (const p of problems) console.error(p);
    console.error("check_shot_quality: one or more tutorial screenshots are low quality. Regenerate"
      + " them with `npm run shots` after fixing the capture, and confirm they are crisp.");
    return 1;
  }
  console.log(`check_shot_quality: all ${files.length} tutorial screenshots pass the quality gate`);
  return 0;
}

run().then((code) => process.exit(code)).catch((e) => { console.error(e); process.exit(1); });
