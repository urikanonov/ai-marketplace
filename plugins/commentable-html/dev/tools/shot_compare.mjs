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

// The comparison is EXACT: no differing pixels are allowed (CMH-BUILD-19). It used to downsample 2x,
// quantize colors onto a 64-step ladder and tolerate a channel delta of 96 across up to 20% of the
// pixels, because two DIFFERENT renderers (a local host browser and a bare CI runner) had to agree
// on the same PNGs. Since the renderer became a single digest-pinned container (issue #701) there is
// no cross-renderer antialiasing jitter left to absorb, and it was measured: two independent renders
// of all 19 committed shots are BYTE-IDENTICAL, in the container and on a host browser alike - also
// under four concurrent captures and a 6-worker stress run. So no normalization is applied at all.
//
// The volatile build stamps (the version badge, the "Generated on" date) that would otherwise force
// a re-render on every release are neutralized at CAPTURE time instead of being bought off with a
// pixel allowance here (see shot_stamps.mjs), because an allowance applies to the WHOLE image: a
// budget wide enough for a repainted version badge is also wide enough to hide a small real
// regression - exactly the class of miss this change removes - and the same comparison drives the
// write path, so `npm run shots` would refuse to update a shot whose intended change fell inside it.
export const MAX_DIFF_PIXELS = 0;
// The one deliberate slack. A pixel counts as different when any channel differs by MORE than this.
// Within one machine the measured difference is zero, so this is not sized from observed drift: it
// is insurance for the single input the digest pin does NOT fix, the host CPU. Chromium rasterizes
// in software and Skia dispatches on CPU features, so a runner with a different SIMD level could in
// principle round a blended edge pixel by a least significant bit or two. Two 8-bit steps are
// invisible (0.8% of the channel range) and far below any real change: the smallest regression this
// still catches is a delta-3 wash, where the retired budget waved through a delta-96 one. If a
// cross-host difference ever exceeds it, the gate fails loudly with a measured count (compareImages
// reports it) - re-size this from THAT measurement rather than widening it pre-emptively.
export const PIXEL_CHANNEL_TOLERANCE = 2;

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

// The budget, applied to one counted diff. Kept out of the browser (and out of imagesMatch) so the
// rule itself is directly testable without decoding a PNG.
export function withinPixelBudget(different, total) {
  if (!Number.isFinite(different) || !Number.isFinite(total) || total <= 0) return false;
  return different <= MAX_DIFF_PIXELS;
}

function describeSize(size) {
  return size ? `${size.width}x${size.height}` : "unreadable";
}

// Runs in the browser: no closure over module scope, so it survives being serialized to page.evaluate.
function countDifferences({ expectedBase64, actualBase64, tolerance }) {
  async function decode(base64) {
    const img = new Image();
    img.src = "data:image/png;base64," + base64;
    await img.decode();
    return img;
  }
  function pixels(img, width, height) {
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    ctx.drawImage(img, 0, 0);
    return ctx.getImageData(0, 0, width, height).data;
  }
  return (async () => {
    try {
      const expectedImg = await decode(expectedBase64);
      const actualImg = await decode(actualBase64);
      const width = Math.min(expectedImg.naturalWidth, actualImg.naturalWidth);
      const height = Math.min(expectedImg.naturalHeight, actualImg.naturalHeight);
      const expectedData = pixels(expectedImg, width, height);
      const actualData = pixels(actualImg, width, height);
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
      return { different, total };
    } catch {
      return null;
    }
  })();
}

export async function compareImages(comparePage, expected, actual) {
  if (!fs.existsSync(expected)) return { ok: false, reason: "expected file missing" };
  if (!fs.existsSync(actual)) return { ok: false, reason: "actual file missing" };
  const expectedSize = pngSize(expected);
  const actualSize = pngSize(actual);
  if (!dimensionsMatch(expectedSize, actualSize)) {
    return {
      ok: false,
      reason: `dimensions ${describeSize(expectedSize)} vs ${describeSize(actualSize)}`,
      expectedSize,
      actualSize,
    };
  }
  const counted = await comparePage.evaluate(countDifferences, {
    expectedBase64: fs.readFileSync(expected).toString("base64"),
    actualBase64: fs.readFileSync(actual).toString("base64"),
    tolerance: PIXEL_CHANNEL_TOLERANCE,
  });
  if (!counted) return { ok: false, reason: "one of the images could not be decoded" };
  const { different, total } = counted;
  const ok = withinPixelBudget(different, total);
  return {
    ok,
    reason: ok ? "" : `${different} differing px of ${total} (ratio ${(different / total).toExponential(2)}), `
      + `budget ${MAX_DIFF_PIXELS} px at channel tolerance ${PIXEL_CHANNEL_TOLERANCE}`,
    expectedSize,
    actualSize,
    different,
    total,
  };
}

export async function imagesMatch(comparePage, expected, actual) {
  return (await compareImages(comparePage, expected, actual)).ok;
}

