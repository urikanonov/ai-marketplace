import { test, expect } from "@playwright/test";
import { execFileSync } from "child_process";
import fs from "fs";
import path from "path";
import {
  openKitchenSink, openKitchenSinkNonPortable, addTextComment, openToolbarMenu, lastCopied,
  readDownload, fileUrl, ready, stageInline, KITCHEN_SINK, KITCHEN_SINK_NONPORTABLE, SKILL, DEV,
} from "./helpers.js";

test.describe("theme, copy payload, nonportable plain, drift", () => {
  test("renders and works in dark theme (clawpilotTheme=dark)", async ({ page }) => {
    await page.goto(fileUrl(KITCHEN_SINK) + "?clawpilotTheme=dark");
    await ready(page);
    expect(await page.evaluate(() => document.documentElement.getAttribute("data-theme"))).toBe("dark");
    // The dark theme variables actually apply (dark background, light text).
    const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
    const rgb = bg.match(/\d+/g).map(Number);
    expect(rgb[0] + rgb[1] + rgb[2], "dark background").toBeLessThan(360);
    await addTextComment(page, "#commentRoot section p", "dark mode note");
    await expect(page.locator("#commentList")).toContainText("dark mode note");
  });

  test("Copy all emits a fenced code block for a code comment", async ({ page }) => {
    await openKitchenSink(page);
    await addTextComment(page, "#commentRoot pre code", "review this code");
    await page.locator("#btnCopyAll").click(); // panel is open -> use the panel button
    const bundle = await lastCopied(page);
    // The code comment's quoted text is a fenced block tagged with the language.
    expect(bundle).toMatch(/```python[\s\S]*```/);
    expect(bundle).toContain("review this code");
  });

  test("Export plain in nonportable mode strips the JS companion but keeps the CSS companion and content", async ({ page }) => {
    await openKitchenSinkNonPortable(page);
    await openToolbarMenu(page);
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.click("#btnSavePlainTop"),
    ]);
    const html = await readDownload(download);
    // The CSS companion stays so the content keeps its styling; only the JS companion
    // (the commenting ability), the comment DOM, and the markers are removed.
    expect(html).toMatch(/<link\b[^>]*\bhref\s*=\s*["'][^"']*commentable-html[^"']*\.css/i);
    expect(html).not.toMatch(/<script\b[^>]*\bsrc\s*=\s*["'][^"']*commentable-html/i);
    expect(html).not.toContain('id="handledCommentIds"');
    expect(html).not.toContain('class="cm-toolbar');
    expect(html).toContain("Kitchen-sink sample"); // host content survives
  });

  test("Export plain does not leak comments when a note forges the region END marker", async ({ page }) => {
    const { html } = stageInline({ source: KITCHEN_SINK });
    // 1) Create a real comment so we embed a valid comment shape.
    await page.goto(fileUrl(html));
    await ready(page);
    await addTextComment(page, "#commentRoot section p", "seed");
    const comment = await page.evaluate(() => {
      const k = document.getElementById("commentRoot").dataset.commentKey;
      return JSON.parse(localStorage.getItem(k))[0];
    });
    // 2) Two embedded comments: the first forges an EMBEDDED COMMENTS END marker in its
    //    text (no "<", which the save path escapes to \u003c), the second holds secrets.
    const marker = "x END: commentable-html - EMBEDDED COMMENTS --> y";
    const forged = { ...comment, id: "cforge01", note: marker, text: marker, quote: marker };
    const secret = { ...comment, id: "csecret02", note: "SECRET_SECOND_NOTE", text: "SECRET_SECOND_NOTE", quote: "SECRET_SECOND_QUOTE" };
    const embedded = JSON.stringify([forged, secret]);
    const embRe = /(<script[^>]*id="embeddedComments"[^>]*>)([\s\S]*?)(<\/script>)/;
    fs.writeFileSync(html, fs.readFileSync(html, "utf8").replace(embRe, (_m, a, _b, c) => a + "\n" + embedded + "\n" + c));
    // 3) Reload with the crafted embedded block and export to plain.
    await page.goto(fileUrl(html));
    await ready(page);
    const [dl] = await Promise.all([
      page.waitForEvent("download"),
      (async () => {
        if (await page.locator("#btnSavePlain").isVisible()) return page.click("#btnSavePlain");
        await openToolbarMenu(page);
        return page.click("#btnSavePlainTop");
      })(),
    ]);
    const out = await readDownload(dl);
    // The whole EMBEDDED COMMENTS region (both comments) must be gone - no leak past the forged marker.
    expect(out).not.toContain("SECRET_SECOND_NOTE");
    expect(out).not.toContain("SECRET_SECOND_QUOTE");
    expect(out).not.toContain('id="embeddedComments"');
  });



  test("Export plain ignores a data-id commentableHtmlLayer decoy script", async ({ page }) => {
    const decoy = '<script type="application/json" data-id="commentableHtmlLayer">{"host":"keep"}</script>';
    const { html, dir } = stageInline({
      source: KITCHEN_SINK,
      mutate: (raw) => raw.replace('<script type="application/json" id="commentableHtmlLayer">', decoy + '\n<script type="application/json" id="commentableHtmlLayer">'),
    });
    try {
      await page.goto(fileUrl(html));
      await ready(page);
      await openToolbarMenu(page);
      const [download] = await Promise.all([
        page.waitForEvent("download"),
        page.click("#btnSavePlainTop"),
      ]);
      const out = await readDownload(download);
      expect(out).toMatch(/<script\b(?=[^>]*\sdata-id\s*=\s*["']commentableHtmlLayer["'])(?=[^>]*\stype\s*=\s*["']application\/json["'])[^>]*>\s*\{"host":"keep"\}\s*<\/script>/i);
      expect(out).not.toMatch(/<script\b[^>]*\sid\s*=\s*["']commentableHtmlLayer["']/i);
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  test("committed sample fixtures are not stale (generate.mjs --check)", () => {
    execFileSync("node", ["tests/fixtures/generate.mjs", "--check"], { cwd: DEV });
  });

  test("embedded comments merge by latest updatedAt (both directions)", async ({ page, browser }) => {
    const { html, dir } = stageInline({ source: KITCHEN_SINK });
    try {
      // 1) Create a real comment so we have valid offsets, then read it back.
      await page.goto(fileUrl(html));
      await ready(page);
      await addTextComment(page, "#commentRoot section p", "base");
      const { key, comment } = await page.evaluate(() => {
        const k = document.getElementById("commentRoot").dataset.commentKey;
        return { key: k, comment: JSON.parse(localStorage.getItem(k))[0] };
      });

      const variant = (note, iso) => JSON.stringify([{ ...comment, note, updatedAt: iso }]);
      const embRe = /(<script[^>]*id="embeddedComments"[^>]*>)([\s\S]*?)(<\/script>)/;

      async function loadMerged(embeddedNote, embeddedIso, localNote, localIso) {
        const merged = fs.readFileSync(html, "utf8").replace(embRe,
          (_m, a, _b, c) => a + "\n" + variant(embeddedNote, embeddedIso) + "\n" + c);
        const p = path.join(dir, "merged.html");
        fs.writeFileSync(p, merged);
        const ctx = await browser.newContext();
        try {
          const pg = await ctx.newPage();
          await pg.addInitScript(([k, v]) => localStorage.setItem(k, v), [key, variant(localNote, localIso)]);
          await pg.goto(fileUrl(p));
          await pg.waitForFunction(() => window.__commentableHtmlReady === true);
          return await pg.locator("#commentList").innerText();
        } finally {
          await ctx.close();
        }
      }

      // Embedded is newer -> embedded wins.
      let text = await loadMerged("EMBEDDED_WINS", "2099-01-01T00:00:00.000Z", "local_old", "2000-01-01T00:00:00.000Z");
      expect(text).toContain("EMBEDDED_WINS");
      expect(text).not.toContain("local_old");

      // localStorage is newer -> local wins.
      text = await loadMerged("embedded_old", "2000-01-01T00:00:00.000Z", "LOCAL_WINS", "2099-01-01T00:00:00.000Z");
      expect(text).toContain("LOCAL_WINS");
      expect(text).not.toContain("embedded_old");

      // Disjoint ids -> the two comment sets are UNIONED (neither overwrites the other).
      const variantId = (id, note) => JSON.stringify([{ ...comment, id, note, updatedAt: "2050-01-01T00:00:00.000Z" }]);
      const disjoint = fs.readFileSync(html, "utf8").replace(embRe,
        (_m, a, _b, c) => a + "\n" + variantId("cembedonly", "EMBED_ONLY") + "\n" + c);
      const dp = path.join(dir, "disjoint.html");
      fs.writeFileSync(dp, disjoint);
      const ctx = await browser.newContext();
      try {
        const pg = await ctx.newPage();
        await pg.addInitScript(([k, v]) => localStorage.setItem(k, v), [key, variantId("clocalonly", "LOCAL_ONLY")]);
        await pg.goto(fileUrl(dp));
        await pg.waitForFunction(() => window.__commentableHtmlReady === true);
        const t = await pg.locator("#commentList").innerText();
        expect(t).toContain("EMBED_ONLY");
        expect(t).toContain("LOCAL_ONLY");
        expect(await pg.locator(".cm-card").count()).toBe(2);
      } finally {
        await ctx.close();
      }
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });
});
