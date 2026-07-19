import { test, expect } from "@playwright/test";
import { spawnSync } from "child_process";
import fs from "fs";
import os from "os";
import path from "path";
import { DEV, PLUGIN } from "./helpers.js";

const TOOL = path.join(DEV, "tools", "check_shot_quality.mjs");
const ASSETS = path.join(PLUGIN, "docs", "assets");

function runGate(dir) {
  const args = [TOOL];
  if (dir) args.push(dir);
  return spawnSync("node", args, { encoding: "utf8", timeout: 120000, killSignal: "SIGKILL" });
}

// Render a deliberately degraded copy of a committed shot in the browser and return its PNG bytes.
// pageFn(b64) runs in the page, decodes the source, applies one specific degradation, and returns
// base64 PNG. Each negative test degrades along ONE axis so it fails the matching gate check (and
// only that one), giving every quality check a named, genuinely-red covering fixture.
async function degradedShot(browser, srcName, pageFn) {
  const src = fs.readFileSync(path.join(ASSETS, srcName)).toString("base64");
  const page = await browser.newPage();
  try {
    return await page.evaluate(pageFn, src);
  } finally {
    await page.close();
  }
}

// Write the degraded PNG into a temp assets dir and run the gate over just that dir.
function gateOnDegraded(b64, name) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cmh_shotq_"));
  try {
    fs.writeFileSync(path.join(dir, name), Buffer.from(b64, "base64"));
    return runGate(dir);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
}

// The committed tutorial screenshots (docs/assets) must be crisp and true-color, not blurry or
// faded/color-quantized like the shots the old capture normalization produced. check_shot_quality
// enforces that over the committed PNGs so a low-quality shot can never reach the tutorial again.
test("the committed tutorial screenshots pass the quality gate (CMH-TUT-QUALITY-01)", () => {
  const r = runGate();
  expect(r.error, String(r.error)).toBeFalsy();
  expect(r.status, r.stdout + r.stderr).toBe(0);
  expect(r.stdout).toContain("pass the quality gate");
});

// The gate must actually reject a degraded shot, not just pass everything. Degrade a real committed
// shot exactly the way the old normalization did (downsample by 2, upsample nearest, quantize
// colors), write it to a temp assets dir, and confirm the gate flags it as faded/quantized. This
// pins that the gate catches the specific low-quality class this change removed.
test("the quality gate rejects a degraded (downsampled + color-quantized) screenshot (CMH-TUT-QUALITY-01)", async ({ browser }) => {
  const src = fs.readFileSync(path.join(ASSETS, "garden-01-top-light.png")).toString("base64");
  const page = await browser.newPage();
  let degradedB64;
  try {
    degradedB64 = await page.evaluate(async ({ b64 }) => {
      const img = new Image();
      img.src = "data:image/png;base64," + b64;
      await img.decode();
      const w = img.naturalWidth;
      const h = img.naturalHeight;
      const canvas = document.createElement("canvas");
      canvas.width = w;
      canvas.height = h;
      const ctx = canvas.getContext("2d", { willReadFrequently: true });
      ctx.drawImage(img, 0, 0);
      const small = document.createElement("canvas");
      small.width = Math.ceil(w / 2);
      small.height = Math.ceil(h / 2);
      const sctx = small.getContext("2d");
      sctx.imageSmoothingEnabled = true;
      sctx.drawImage(canvas, 0, 0, small.width, small.height);
      ctx.clearRect(0, 0, w, h);
      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(small, 0, 0, w, h);
      const image = ctx.getImageData(0, 0, w, h);
      const d = image.data;
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
      ctx.putImageData(image, 0, 0);
      return canvas.toDataURL("image/png").split(",", 2)[1];
    }, { b64: src });
  } finally {
    await page.close();
  }
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cmh_shotq_"));
  try {
    fs.writeFileSync(path.join(dir, "garden-01-top-light.png"), Buffer.from(degradedB64, "base64"));
    const r = runGate(dir);
    expect(r.error, String(r.error)).toBeFalsy();
    expect(r.status, r.stdout + r.stderr).toBe(1);
    expect(r.stderr).toContain("faded/quantized");
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

// A smooth blur (downsample then upsample with smoothing, NO color quantize) drops the sharpness
// below the floor while keeping true-color, off-grid gradients - so it must fail SPECIFICALLY as
// blurry, not as faded/quantized. This pins the smooth-blur behavior of the gate with its own
// covering fixture (the combined blur+quantize fixture above would still pass if the sharpness
// check were deleted).
test("the quality gate rejects a smooth-blurred (non-quantized) screenshot (CMH-TUT-QUALITY-01)", async ({ browser }) => {
  const b64 = await degradedShot(browser, "garden-01-top-light.png", async (src) => {
    const img = new Image();
    img.src = "data:image/png;base64," + src;
    await img.decode();
    const w = img.naturalWidth;
    const h = img.naturalHeight;
    const full = document.createElement("canvas");
    full.width = w;
    full.height = h;
    full.getContext("2d").drawImage(img, 0, 0);
    const scale = 6;
    const small = document.createElement("canvas");
    small.width = Math.max(1, Math.round(w / scale));
    small.height = Math.max(1, Math.round(h / scale));
    const sctx = small.getContext("2d");
    sctx.imageSmoothingEnabled = true;
    sctx.drawImage(full, 0, 0, small.width, small.height);
    const out = document.createElement("canvas");
    out.width = w;
    out.height = h;
    const octx = out.getContext("2d");
    octx.imageSmoothingEnabled = true;
    octx.drawImage(small, 0, 0, w, h);
    return out.toDataURL("image/png").split(",", 2)[1];
  });
  const r = gateOnDegraded(b64, "garden-01-top-light.png");
  expect(r.error, String(r.error)).toBeFalsy();
  expect(r.status, r.stdout + r.stderr).toBe(1);
  expect(r.stderr).toContain("blurry");
  expect(r.stderr).not.toContain("faded/quantized");
});

// An under-resolved shot (scaled far below the captured size) fails the minimum-dimension floor,
// matching the issue's concern that small element shots carry too few pixels and blur on HiDPI.
test("the quality gate rejects an under-resolved screenshot (CMH-TUT-QUALITY-01)", async ({ browser }) => {
  const b64 = await degradedShot(browser, "garden-12-export-menu.png", async (src) => {
    const img = new Image();
    img.src = "data:image/png;base64," + src;
    await img.decode();
    const tw = 50;
    const th = Math.max(1, Math.round(img.naturalHeight * tw / img.naturalWidth));
    const out = document.createElement("canvas");
    out.width = tw;
    out.height = th;
    out.getContext("2d").drawImage(img, 0, 0, tw, th);
    return out.toDataURL("image/png").split(",", 2)[1];
  });
  const r = gateOnDegraded(b64, "garden-12-export-menu.png");
  expect(r.error, String(r.error)).toBeFalsy();
  expect(r.status, r.stdout + r.stderr).toBe(1);
  expect(r.stderr).toContain("under-resolved");
});

// An oversized clip leaves a large blank band below the content. Pad a real shot with a tall blank
// bottom margin (filled with its own background) and the vertical-whitespace check must reject it.
test("the quality gate rejects a shot with excess blank vertical margin (CMH-TUT-QUALITY-01)", async ({ browser }) => {
  const b64 = await degradedShot(browser, "garden-01-top-light.png", async (src) => {
    const img = new Image();
    img.src = "data:image/png;base64," + src;
    await img.decode();
    const w = img.naturalWidth;
    const h = img.naturalHeight;
    const probe = document.createElement("canvas");
    probe.width = w;
    probe.height = h;
    const pctx = probe.getContext("2d", { willReadFrequently: true });
    pctx.drawImage(img, 0, 0);
    const bg = pctx.getImageData(0, 0, 1, 1).data;
    const pad = Math.round(h * 0.9);
    const out = document.createElement("canvas");
    out.width = w;
    out.height = h + pad;
    const octx = out.getContext("2d");
    octx.fillStyle = `rgb(${bg[0]},${bg[1]},${bg[2]})`;
    octx.fillRect(0, 0, w, h + pad);
    octx.drawImage(img, 0, 0);
    return out.toDataURL("image/png").split(",", 2)[1];
  });
  const r = gateOnDegraded(b64, "garden-01-top-light.png");
  expect(r.error, String(r.error)).toBeFalsy();
  expect(r.status, r.stdout + r.stderr).toBe(1);
  expect(r.stderr).toContain("whitespace");
});

// The captured load-flash frame washes a large area with a semi-transparent yellow. Blend a real
// shot heavily toward yellow (true-color, still sharp) and the color-cast check must reject it,
// matching the issue's "faded / yellow animation cast" offender.
test("the quality gate rejects a yellow-cast (load-flash) screenshot (CMH-TUT-QUALITY-01)", async ({ browser }) => {
  const b64 = await degradedShot(browser, "garden-01-top-light.png", async (src) => {
    const img = new Image();
    img.src = "data:image/png;base64," + src;
    await img.decode();
    const w = img.naturalWidth;
    const h = img.naturalHeight;
    const out = document.createElement("canvas");
    out.width = w;
    out.height = h;
    const ctx = out.getContext("2d", { willReadFrequently: true });
    ctx.drawImage(img, 0, 0);
    const im = ctx.getImageData(0, 0, w, h);
    const d = im.data;
    for (let i = 0; i < d.length; i += 4) {
      d[i] = Math.round(d[i] * 0.35 + 255 * 0.65);
      d[i + 1] = Math.round(d[i + 1] * 0.35 + 210 * 0.65);
      d[i + 2] = Math.round(d[i + 2] * 0.35 + 40 * 0.65);
    }
    ctx.putImageData(im, 0, 0);
    return out.toDataURL("image/png").split(",", 2)[1];
  });
  const r = gateOnDegraded(b64, "garden-01-top-light.png");
  expect(r.error, String(r.error)).toBeFalsy();
  expect(r.status, r.stdout + r.stderr).toBe(1);
  expect(r.stderr).toContain("color-cast");
});
