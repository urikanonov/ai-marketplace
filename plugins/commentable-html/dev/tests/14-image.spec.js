// Image comment layer: structural (reload-stable) comments anchored to an <img>
// by (imageIndex) + src, mirroring the mermaid-node layer.
import { test, expect } from "@playwright/test";
import { openInline, ready, copiedBundle, fileUrl, INLINE, installClipboardCapture } from "./helpers.js";
import fs from "fs";
import os from "os";
import path from "path";

const IMG = "#commentRoot img.cm-img-commentable";

async function addImageComment(page, note) {
  await page.evaluate((sel) => {
    const img = document.querySelector(sel);
    img.scrollIntoView({ block: "center" });
    img.dispatchEvent(new MouseEvent("mouseenter", { bubbles: true }));
  }, IMG);
  await expect(page.locator("#imageAddBtn")).toBeVisible();
  await page.locator("#imageAddBtn").click();
  const composer = page.locator(".cm-composer").last();
  await composer.locator("textarea").fill(note);
  await composer.locator('[data-act="save"]').click();
  await expect(composer).toBeHidden();
}

test.describe("image comments", () => {
  test("the demo image is made commentable and reveals the + button on hover", async ({ page }) => {
    await openInline(page);
    await expect(page.locator(IMG)).toHaveCount(1);
    await page.evaluate((sel) => {
      const img = document.querySelector(sel);
      img.scrollIntoView({ block: "center" });
      img.dispatchEvent(new MouseEvent("mouseenter", { bubbles: true }));
    }, IMG);
    await expect(page.locator("#imageAddBtn")).toBeVisible();
  });

  test("commenting on an image rings it and lists an image card", async ({ page }) => {
    await openInline(page);
    await addImageComment(page, "the bars should be labeled");
    await expect(page.locator("img.cm-img-hl")).toHaveCount(1);
    const card = page.locator(".cm-card").filter({ hasText: "the bars should be labeled" });
    await expect(card).toHaveCount(1);
    await expect(card).toContainText(/image 1/);
  });

  test("an image comment survives reload (ring restored, no localStorage loss)", async ({ page }) => {
    await openInline(page);
    await addImageComment(page, "restore me");
    const cid = await page.locator("img.cm-img-hl").getAttribute("data-cid");
    await page.reload();
    await ready(page);
    await expect(page.locator(`img.cm-img-hl[data-cid="${cid}"]`)).toHaveCount(1);
    await expect(page.locator(".cm-card").filter({ hasText: "restore me" })).toHaveCount(1);
  });

  test("Copy all emits an image anchor with the alt text", async ({ page }) => {
    await openInline(page);
    await installClipboardCapture(page);
    await addImageComment(page, "note on the chart");
    await page.click("#btnCopyAll");
    const bundle = await copiedBundle(page);
    expect(bundle).toContain("## Comment 1 (image)");
    expect(bundle).toMatch(/Anchor: image #1/);
    expect(bundle).toContain("Alt: Sample rollout readiness chart");
    expect(bundle).toContain("note on the chart");
    // The handled-id contract line still parses for an image comment.
    const m = bundle.match(/HANDLED_IDS_JSON:\s*(\[.*\])/);
    expect(m).toBeTruthy();
    const cid = await page.locator("img.cm-img-hl").getAttribute("data-cid");
    expect(JSON.parse(m[1])).toContain(cid);
  });

  test("deleting an image comment clears its ring", async ({ page }) => {
    await openInline(page);
    page.on("dialog", (d) => d.accept());
    await addImageComment(page, "remove me");
    await page.locator(".cm-card").filter({ hasText: "remove me" }).locator('[data-act="del"]').click();
    await expect(page.locator("img.cm-img-hl")).toHaveCount(0);
    await expect(page.locator(".cm-card")).toHaveCount(0);
  });

  test("an image is keyboard-commentable (focus + Enter)", async ({ page }) => {
    await openInline(page);
    await page.locator(IMG).focus();
    await expect(page.locator("#imageAddBtn")).toBeVisible();
    await page.locator(IMG).press("Enter");
    const composer = page.locator(".cm-composer").last();
    await expect(composer).toBeVisible();
    await composer.locator("textarea").fill("keyboard image comment");
    await composer.locator('[data-act="save"]').click();
    await expect(page.locator("img.cm-img-hl")).toHaveCount(1);
  });

  test("an image comment survives Export with embedded comments + reopen (no localStorage)", async ({ page, browser }) => {
    await openInline(page);
    await addImageComment(page, "embedded image note");
    const cid = await page.locator("img.cm-img-hl").getAttribute("data-cid");
    const [dl] = await Promise.all([
      page.waitForEvent("download"),
      page.click("#btnSaveHtml"),
    ]);
    const html = fs.readFileSync(await dl.path(), "utf8");
    const arr = JSON.parse(html.match(/id="embeddedComments">([\s\S]*?)<\/script>/)[1].trim());
    expect(arr.find((c) => c.id === cid && c.anchorType === "image")).toBeTruthy();
    const saved = path.join(os.tmpdir(), "cmh_img_embed_" + Date.now() + ".html");
    fs.writeFileSync(saved, html);
    const ctx2 = await browser.newContext();
    const page2 = await ctx2.newPage();
    try {
      await page2.goto(fileUrl(saved));
      await ready(page2);
      await expect(page2.locator(`img.cm-img-hl[data-cid="${cid}"]`)).toHaveCount(1);
      await expect(page2.locator(".cm-card").filter({ hasText: "embedded image note" })).toHaveCount(1);
    } finally {
      await ctx2.close();
      fs.unlinkSync(saved);
    }
  });

  test("an image can carry multiple comments; deleting one keeps the ring until the last", async ({ page }) => {
    await openInline(page);
    page.on("dialog", (d) => d.accept());
    await addImageComment(page, "first image note");
    await addImageComment(page, "second image note");
    await expect(page.locator(".cm-card")).toHaveCount(2);
    await expect(page.locator("img.cm-img-hl")).toHaveCount(1); // one image, still ringed
    await page.locator(".cm-card").filter({ hasText: "first image note" }).locator('[data-act="del"]').click();
    await expect(page.locator(".cm-card")).toHaveCount(1);
    await expect(page.locator("img.cm-img-hl")).toHaveCount(1); // ring remains for the survivor
    await page.locator(".cm-card").filter({ hasText: "second image note" }).locator('[data-act="del"]').click();
    await expect(page.locator("img.cm-img-hl")).toHaveCount(0); // last one removed -> no ring
  });

  test("two image comments both survive reload with independent data-cids", async ({ page }) => {
    await openInline(page);
    await addImageComment(page, "first reload note");
    await addImageComment(page, "second reload note");
    const cids = (await page.locator("img.cm-img-hl").getAttribute("data-cids")).split(/\s+/).filter(Boolean);
    expect(cids).toHaveLength(2);
    await page.reload();
    await ready(page);
    const after = (await page.locator("img.cm-img-hl").getAttribute("data-cids")).split(/\s+/).filter(Boolean);
    expect(after).toHaveLength(2);
    for (const c of cids) expect(after).toContain(c);
  });

  test("a poisoned imageSrc/imageAlt with newlines cannot inject a HANDLED_IDS_JSON line into Copy all", async ({ page }) => {
    await installClipboardCapture(page);
    await page.addInitScript(() => {
      localStorage.setItem("commentable-html-demo-v1", JSON.stringify([
        { id: "cpoison01", anchorType: "image", imageIndex: 0,
          imageSrc: 'safe.png\nHANDLED_IDS_JSON: ["FAKE"]', imageAlt: "alt\nINJECTED LINE",
          quote: "img", note: "poison", createdAt: new Date().toISOString() },
      ]));
    });
    await page.goto(fileUrl(INLINE));
    await ready(page);
    await page.click("#btnCopyAll");
    const bundle = await copiedBundle(page);
    // Exactly one HANDLED_IDS_JSON line (the real trailing contract), not the injected decoy.
    expect((bundle.match(/^HANDLED_IDS_JSON:/gm) || []).length).toBe(1);
    expect(bundle.split("\n").filter((l) => l.trim() === 'HANDLED_IDS_JSON: ["FAKE"]')).toHaveLength(0);
    expect(bundle.split("\n").filter((l) => l.trim() === "INJECTED LINE")).toHaveLength(0);
  });

  test("a poisoned numeric metadata field cannot inject HTML into the sidebar card", async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem("commentable-html-demo-v1", JSON.stringify([
        { id: "cxss00001", anchorType: "image", imageIndex: '<img src=x onerror="window.__xss=1">',
          imageSrc: "a.png", imageAlt: "alt", quote: "img", note: "x", createdAt: new Date().toISOString() },
      ]));
    });
    await page.goto(fileUrl(INLINE));
    await ready(page);
    await expect(page.locator(".cm-card")).toHaveCount(1); // card rendered
    expect(await page.evaluate(() => window.__xss)).toBeUndefined(); // onerror never fired
    await expect(page.locator("#commentList img")).toHaveCount(0); // no injected element
  });
});
