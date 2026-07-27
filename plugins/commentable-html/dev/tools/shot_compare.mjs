// Shared tutorial-screenshot comparison (dev-only, not shipped).
//
// Both `capture_tutorial.mjs` (its --check freshness gate and its compare-and-skip write path) and
// the heavy `54-tutorial-shots.spec.js` determinism tests need the SAME image diff. They used to
// carry byte-identical copies of it, which is exactly how the budgets silently drift apart - the
// spec even documents that it must never be STRICTER than the gate it mirrors. One module, imported
// by both, removes that class.
//
// The DIMENSION gate runs here in Node (PNG headers are cheap to read), not inside the page, so the
// grid rule lives in one testable place instead of being serialized into browser script. Only the
// pixel diff needs a browser.
import fs from "fs";
import { MAX_WIDTH_DELTA, heightDeltaAllowed } from "./shot_clip.mjs";

// Normalization applied to BOTH images before diffing: downsample then upsample nearest (to erase
// the sub-pixel font antialiasing that differs across platforms) and quantize colors. The committed
// PNGs are written to disk raw and crisp; this degradation exists only for the comparison.
export const PNG_QUANTIZE_STEP = 64;
export const PNG_DOWNSAMPLE = 2;
export const PIXEL_CHANNEL_TOLERANCE = 96;
export const MAX_PIXEL_DIFF_RATIO = 0.2;

// PNG dimensions live in the IHDR chunk: width at byte 16, height at byte 20, both big-endian.
export function pngSize(file) {
  const buf = fs.readFileSync(file);
  if (buf.length < 24 || buf.readUInt32BE(0) !== 0x89504e47) return null;
  return { width: buf.readUInt32BE(16), height: buf.readUInt32BE(20) };
}

export function dimensionsMatch(expectedSize, actualSize) {
  if (!expectedSize || !actualSize) return false;
  if (Math.abs(expectedSize.width - actualSize.width) > MAX_WIDTH_DELTA) return false;
  return heightDeltaAllowed(expectedSize.height, actualSize.height);
}

// Runs in the browser: no closure over module scope, so it survives being serialized to page.evaluate.
function diffRatio({ expectedBase64, actualBase64, tolerance, scale, step }) {
  async function decode(base64) {
    const img = new Image();
    img.src = "data:image/png;base64," + base64;
    await img.decode();
    return img;
  }
  function normalize(img, width, height) {
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    ctx.drawImage(img, 0, 0);
    if (scale > 1) {
      const small = document.createElement("canvas");
      small.width = Math.max(1, Math.ceil(width / scale));
      small.height = Math.max(1, Math.ceil(height / scale));
      const sctx = small.getContext("2d");
      sctx.imageSmoothingEnabled = true;
      sctx.drawImage(canvas, 0, 0, small.width, small.height);
      ctx.clearRect(0, 0, width, height);
      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(small, 0, 0, width, height);
    }
    const image = ctx.getImageData(0, 0, width, height);
    const d = image.data;
    for (let i = 0; i < d.length; i += 4) {
      d[i] = Math.round(d[i] / step) * step;
      d[i + 1] = Math.round(d[i + 1] / step) * step;
      d[i + 2] = Math.round(d[i + 2] / step) * step;
      if (d[i] === d[i + 1] && d[i + 1] === d[i + 2] && d[i] >= 192) {
        d[i] = 255;
        d[i + 1] = 255;
        d[i + 2] = 255;
      }
    }
    return d;
  }
  return (async () => {
    try {
      const expectedImg = await decode(expectedBase64);
      const actualImg = await decode(actualBase64);
      const width = Math.min(expectedImg.naturalWidth, actualImg.naturalWidth);
      const height = Math.min(expectedImg.naturalHeight, actualImg.naturalHeight);
      const expectedData = normalize(expectedImg, width, height);
      const actualData = normalize(actualImg, width, height);
      let different = 0;
      const total = width * height;
      for (let i = 0; i < expectedData.length; i += 4) {
        const maxChannelDelta = Math.max(
          Math.abs(expectedData[i] - actualData[i]),
          Math.abs(expectedData[i + 1] - actualData[i + 1]),
          Math.abs(expectedData[i + 2] - actualData[i + 2]),
          Math.abs(expectedData[i + 3] - actualData[i + 3]),
        );
        if (maxChannelDelta > tolerance) different += 1;
      }
      return different / total;
    } catch {
      return 1;
    }
  })();
}

export async function imagesMatch(comparePage, expected, actual) {
  if (!fs.existsSync(expected) || !fs.existsSync(actual)) return false;
  if (!dimensionsMatch(pngSize(expected), pngSize(actual))) return false;
  const ratio = await comparePage.evaluate(diffRatio, {
    expectedBase64: fs.readFileSync(expected).toString("base64"),
    actualBase64: fs.readFileSync(actual).toString("base64"),
    tolerance: PIXEL_CHANNEL_TOLERANCE,
    scale: PNG_DOWNSAMPLE,
    step: PNG_QUANTIZE_STEP,
  });
  return ratio <= MAX_PIXEL_DIFF_RATIO;
}
