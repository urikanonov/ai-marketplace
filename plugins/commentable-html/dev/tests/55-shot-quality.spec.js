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
