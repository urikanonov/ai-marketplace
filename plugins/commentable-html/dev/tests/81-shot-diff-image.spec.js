import { test, expect } from "@playwright/test";
import fs from "fs";
import os from "os";
import path from "path";
import { DEV } from "./helpers.js";

// CMH-BUILD-18: a failing drift gate must leave EVIDENCE behind - the pixels it saw, plus a diff
// image saying what moved - because the tutorial PNGs render only in the pinned container, so a
// contributor without Docker cannot reproduce the failure locally.
const { writeDiffImage, compareImages, PIXEL_CHANNEL_TOLERANCE } = await import(
  path.join(DEV, "tools", "shot_compare.mjs").replace(/\\/g, "/").replace(/^/, "file:///"));

async function pngOf(page, width, height, paint) {
  const base64 = await page.evaluate(({ w, h, body }) => {
    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d");
    // eslint-disable-next-line no-new-func
    new Function("ctx", "w", "h", body)(ctx, w, h);
    return canvas.toDataURL("image/png").split(",")[1];
  }, { w: width, h: height, body: paint });
  return Buffer.from(base64, "base64");
}

// Count magenta-marked pixels in a rendered diff, and report its bounds.
async function countMarked(page, base64) {
  return page.evaluate(async (b64) => {
    const img = new Image();
    img.src = "data:image/png;base64," + b64;
    await img.decode();
    const canvas = document.createElement("canvas");
    canvas.width = img.naturalWidth;
    canvas.height = img.naturalHeight;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    ctx.drawImage(img, 0, 0);
    const d = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
    let n = 0;
    for (let i = 0; i < d.length; i += 4) {
      if (d[i] === 255 && d[i + 1] === 0 && d[i + 2] === 255) n += 1;
    }
    return { marked: n, width: canvas.width, height: canvas.height };
  }, base64);
}

test.describe("screenshot drift evidence (CMH-BUILD-18)", () => {
  test("a differing pair produces a diff image marking the changed pixels", async ({ browser }) => {
    const page = await browser.newPage();
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cmh-diffimg-"));
    try {
      const expectedFile = path.join(dir, "expected.png");
      const actualFile = path.join(dir, "actual.png");
      const outFile = path.join(dir, "out.diff.png");
      fs.writeFileSync(expectedFile, await pngOf(page, 40, 20,
        "ctx.fillStyle='#ffffff';ctx.fillRect(0,0,w,h);"));
      fs.writeFileSync(actualFile, await pngOf(page, 40, 20,
        "ctx.fillStyle='#ffffff';ctx.fillRect(0,0,w,h);ctx.fillStyle='#000000';ctx.fillRect(0,0,10,10);"));

      expect(await writeDiffImage(page, expectedFile, actualFile, outFile)).toBe(true);
      expect(fs.existsSync(outFile)).toBe(true);
      expect(fs.statSync(outFile).size).toBeGreaterThan(0);

      // The marked pixels are the ones that moved: the 10x10 block, painted magenta.
      const marked = await page.evaluate(async (b64) => {
        const img = new Image();
        img.src = "data:image/png;base64," + b64;
        await img.decode();
        const canvas = document.createElement("canvas");
        canvas.width = img.naturalWidth;
        canvas.height = img.naturalHeight;
        const ctx = canvas.getContext("2d", { willReadFrequently: true });
        ctx.drawImage(img, 0, 0);
        const d = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
        let n = 0;
        for (let i = 0; i < d.length; i += 4) {
          if (d[i] === 255 && d[i + 1] === 0 && d[i + 2] === 255) n += 1;
        }
        return n;
      }, fs.readFileSync(outFile).toString("base64"));
      expect(marked).toBe(100);
    } finally {
      await page.close();
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  test("an identical pair marks nothing", async ({ browser }) => {
    const page = await browser.newPage();
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cmh-diffimg-same-"));
    try {
      const a = path.join(dir, "a.png");
      const b = path.join(dir, "b.png");
      const out = path.join(dir, "same.diff.png");
      const png = await pngOf(page, 20, 10, "ctx.fillStyle='#123456';ctx.fillRect(0,0,w,h);");
      fs.writeFileSync(a, png);
      fs.writeFileSync(b, png);
      expect(await writeDiffImage(page, a, b, out)).toBe(true);
      const marked = await page.evaluate(async (b64) => {
        const img = new Image();
        img.src = "data:image/png;base64," + b64;
        await img.decode();
        const canvas = document.createElement("canvas");
        canvas.width = img.naturalWidth;
        canvas.height = img.naturalHeight;
        const ctx = canvas.getContext("2d", { willReadFrequently: true });
        ctx.drawImage(img, 0, 0);
        const d = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
        let n = 0;
        for (let i = 0; i < d.length; i += 4) {
          if (d[i] === 255 && d[i + 1] === 0 && d[i + 2] === 255) n += 1;
        }
        return n;
      }, fs.readFileSync(out).toString("base64"));
      expect(marked).toBe(0);
    } finally {
      await page.close();
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  test("a missing input is reported rather than throwing", async ({ browser }) => {
    const page = await browser.newPage();
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cmh-diffimg-miss-"));
    try {
      const out = path.join(dir, "x.diff.png");
      expect(await writeDiffImage(page, path.join(dir, "nope.png"),
                                  path.join(dir, "also-nope.png"), out)).toBe(false);
      expect(fs.existsSync(out)).toBe(false);
    } finally {
      await page.close();
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  test("a dimension change is marked, not silently dropped", async ({ browser }) => {
    // Rendering on the OVERLAP would discard the added strip entirely and produce a faded
    // image with zero magenta pixels - for a failure the gate genuinely reports.
    const page = await browser.newPage();
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cmh-diffimg-dim-"));
    try {
      const a = path.join(dir, "small.png");
      const b = path.join(dir, "tall.png");
      const out = path.join(dir, "dim.diff.png");
      fs.writeFileSync(a, await pngOf(page, 10, 10, "ctx.fillStyle='#ffffff';ctx.fillRect(0,0,w,h);"));
      fs.writeFileSync(b, await pngOf(page, 10, 20, "ctx.fillStyle='#ffffff';ctx.fillRect(0,0,w,h);"));
      expect(await writeDiffImage(page, a, b, out)).toBe(true);
      const { marked, height } = await countMarked(page, fs.readFileSync(out).toString("base64"));
      expect(height).toBe(20);
      // The 10x10 strip that exists in only one image is the difference.
      expect(marked).toBe(100);
    } finally {
      await page.close();
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  test("the diff marks exactly what the gate counts, at the tolerance boundary", async ({ browser }) => {
    // A source-text check would still pass if renderDiff used >= where the gate uses >, marking
    // pixels the gate accepts. Drive both at EXACTLY the tolerance and at tolerance + 1.
    const page = await browser.newPage();
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cmh-diffimg-tol-"));
    try {
      const base = path.join(dir, "base.png");
      fs.writeFileSync(base, await pngOf(page, 10, 10, "ctx.fillStyle='rgb(100,100,100)';ctx.fillRect(0,0,w,h);"));
      for (const [delta, expectMarked] of [[PIXEL_CHANNEL_TOLERANCE, 0],
                                           [PIXEL_CHANNEL_TOLERANCE + 1, 100]]) {
        const other = path.join(dir, `d${delta}.png`);
        const out = path.join(dir, `d${delta}.diff.png`);
        fs.writeFileSync(other, await pngOf(page, 10, 10,
          `ctx.fillStyle='rgb(${100 + delta},100,100)';ctx.fillRect(0,0,w,h);`));
        const gate = await compareImages(page, base, other);
        expect(await writeDiffImage(page, base, other, out)).toBe(true);
        const { marked } = await countMarked(page, fs.readFileSync(out).toString("base64"));
        // The image and the gate must agree on the SAME pixels.
        expect(marked).toBe(expectMarked);
        expect(gate.different).toBe(expectMarked);
      }
    } finally {
      await page.close();
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  test("the tolerance the diff marks with is the same one the gate counts with", () => {
    // A diff image drawn at a different threshold than the gate would highlight pixels the gate
    // did not count (or hide ones it did), which is worse than no diff at all.
    const src = fs.readFileSync(path.join(DEV, "tools", "shot_compare.mjs"), "utf8");
    expect(src).toContain("tolerance: PIXEL_CHANNEL_TOLERANCE");
    expect(PIXEL_CHANNEL_TOLERANCE).toBeGreaterThanOrEqual(0);
  });
});
