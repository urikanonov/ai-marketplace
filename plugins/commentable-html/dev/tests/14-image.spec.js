// Image comment layer: structural (reload-stable) comments anchored to an <img>
// by (imageIndex) + src, mirroring the mermaid-node layer.
import { test, expect } from "@playwright/test";
import { openInline, ready, copiedBundle, fileUrl, INLINE, installClipboardCapture, DEV,
  clickSidebarExport } from "./helpers.js";
import fs from "fs";
import os from "os";
import path from "path";

const IMG = "#commentRoot img.cm-img-commentable";

async function addImageComment(page, note) {
  return addMediaComment(page, IMG, note);
}

async function addMediaComment(page, selector, note) {
  await page.evaluate((sel) => {
    const img = document.querySelector(sel);
    img.scrollIntoView({ block: "center" });
    img.dispatchEvent(new MouseEvent("mouseenter", { bubbles: true }));
  }, selector);
  await expect(page.locator("#imageAddBtn")).toBeVisible();
  await page.locator("#imageAddBtn").click();
  const composer = page.locator(".cm-composer").last();
  await composer.locator("textarea").fill(note);
  await composer.locator('[data-act="save"]').click();
  await expect(composer).toBeHidden();
}

const REPO_TMP = path.resolve(DEV, "..", "..", "..", "tmp");
const IMAGE_ORDER_KEY = "cmh-image-order-regression";
const IMAGE_ITEMS = {
  first: { src: "first-image.png", alt: "First target image" },
  second: { src: "second-image.png", alt: "Second decoy image" },
  dupTarget: { src: "shared-image.png", alt: "Shared source target" },
  dupDecoy: { src: "shared-image.png", alt: "Shared source decoy" },
  dupOther: { src: "shared-image.png", alt: "Shared source other" },
  chartTarget: { alt: "Target chart canvas", kind: "chart" },
  chartDecoy: { alt: "Decoy chart canvas", kind: "chart" },
  chartBlank: { alt: "", kind: "chart" },
};

function mediaMarkup(name) {
  const item = IMAGE_ITEMS[name];
  if (item.kind === "chart") {
    const aria = item.alt ? ` aria-label="${item.alt}"` : "";
    return `
      <figure class="chart" style="margin: 40px 0 900px;">
        <canvas class="cmh-chart"${aria} width="220" height="120" style="display:block;border:2px solid #456;"></canvas>
        <figcaption>${item.alt}</figcaption>
      </figure>`;
  }
  return `
      <figure style="margin: 40px 0 900px;">
        <img src="${item.src}" alt="${item.alt}" width="220" height="120" style="display:block;border:2px solid #456;">
        <figcaption>${item.alt}</figcaption>
      </figure>`;
}

function imageOrderContent(order) {
  const figures = order.map(mediaMarkup).join("\n");
  return `<h1>Image order regression</h1>
    <section aria-labelledby="images-title">
      <h2 id="images-title">Images</h2>
      ${figures}
    </section>`;
}

function stageImageOrderDoc(order) {
  fs.mkdirSync(REPO_TMP, { recursive: true });
  const dir = fs.mkdtempSync(path.join(REPO_TMP, "cmh_img_order_"));
  const p = path.join(dir, "image-order.html");
  const writeOrder = (nextOrder) => {
    let html = fs.readFileSync(INLINE, "utf8");
    const contentRe = /(<!-- BEGIN: commentable-html - CONTENT[^>]*-->)[\s\S]*?(<!-- END: commentable-html - CONTENT -->)/;
    html = html.replace(contentRe, (_m, a, b) => a + "\n" + imageOrderContent(nextOrder) + "\n" + b);
    html = html.replace('data-comment-key="commentable-html-demo"', 'data-comment-key="' + IMAGE_ORDER_KEY + '"');
    html = html.replace('data-doc-source="PORTABLE.html"', 'data-doc-source="image-order.html"');
    fs.writeFileSync(p, html);
  };
  writeOrder(order);
  return { dir, html: p, writeOrder };
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
      clickSidebarExport(page, "#btnSaveHtml"),
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

  test("image comments resolve reordered anchors by stored src for jump and edit (CMH-IMG-07)", async ({ page }) => {
    const staged = stageImageOrderDoc(["first", "second"]);
    try {
      await page.goto(fileUrl(staged.html));
      await ready(page);
      await addImageComment(page, "target the first image");
      const cid = await page.locator('img[src="first-image.png"]').getAttribute("data-cid");
      expect(cid).toBeTruthy();

      staged.writeOrder(["second", "first"]);
      await page.reload();
      await ready(page);
      await expect(page.locator('img[src="first-image.png"].cm-img-hl')).toHaveCount(1);
      await expect(page.locator('img[src="second-image.png"].cm-img-hl')).toHaveCount(0);

      const card = page.locator(".cm-card").filter({ hasText: "target the first image" });
      await card.locator('[data-act="jump"]').click();
      await expect.poll(async () => page.evaluate(() => window.scrollY)).toBeGreaterThan(600);

      await card.locator('[data-act="edit"]').click();
      const distances = await page.evaluate(() => {
        const composer = document.querySelector(".cm-composer");
        const first = document.querySelector('img[src="first-image.png"]');
        const second = document.querySelector('img[src="second-image.png"]');
        const mid = (el) => {
          const r = el.getBoundingClientRect();
          return r.top + r.height / 2;
        };
        return {
          first: Math.abs(mid(composer) - mid(first)),
          second: Math.abs(mid(composer) - mid(second)),
        };
      });
      expect(distances.first).toBeLessThan(distances.second);
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("image comments resolve reordered duplicate-src images and chart canvases by metadata (CMH-IMG-07)", async ({ page }) => {
    const staged = stageImageOrderDoc(["dupTarget", "dupDecoy", "chartTarget", "chartDecoy"]);
    try {
      await page.goto(fileUrl(staged.html));
      await ready(page);
      await addImageComment(page, "shared src target");
      await addMediaComment(page, 'canvas[aria-label="Target chart canvas"]', "chart target");

      staged.writeOrder(["dupDecoy", "dupTarget", "chartDecoy", "chartTarget"]);
      await page.reload();
      await ready(page);

      await expect(page.locator('img[alt="Shared source target"].cm-img-hl')).toHaveCount(1);
      await expect(page.locator('img[alt="Shared source decoy"].cm-img-hl')).toHaveCount(0);
      await expect(page.locator('canvas[aria-label="Target chart canvas"].cm-img-hl')).toHaveCount(1);
      await expect(page.locator('canvas[aria-label="Decoy chart canvas"].cm-img-hl')).toHaveCount(0);
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("image comments do not choose an ambiguous source-only fallback (CMH-IMG-07)", async ({ page }) => {
    const staged = stageImageOrderDoc(["dupTarget", "second"]);
    try {
      await page.goto(fileUrl(staged.html));
      await ready(page);
      await addImageComment(page, "removed duplicate source target");

      staged.writeOrder(["dupDecoy", "dupOther"]);
      await page.reload();
      await ready(page);

      await expect(page.locator('img[alt="Shared source decoy"].cm-img-hl')).toHaveCount(0);
      await expect(page.locator('img[alt="Shared source other"].cm-img-hl')).toHaveCount(0);
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("image comments treat a missing stale chart label as a metadata mismatch (CMH-IMG-07)", async ({ page }) => {
    const staged = stageImageOrderDoc(["chartTarget", "chartBlank"]);
    try {
      await page.goto(fileUrl(staged.html));
      await ready(page);
      await addMediaComment(page, 'canvas[aria-label="Target chart canvas"]', "labelled chart target");

      staged.writeOrder(["chartBlank", "chartTarget"]);
      await page.reload();
      await ready(page);

      await expect(page.locator('canvas[aria-label="Target chart canvas"].cm-img-hl')).toHaveCount(1);
      await expect(page.locator('canvas:not([aria-label]).cm-img-hl')).toHaveCount(0);
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("image comments treat a missing stored chart label as metadata (CMH-IMG-07)", async ({ page }) => {
    const staged = stageImageOrderDoc(["chartBlank", "chartTarget"]);
    try {
      await page.goto(fileUrl(staged.html));
      await ready(page);
      await addMediaComment(page, "canvas:not([aria-label])", "unlabelled chart target");

      staged.writeOrder(["chartTarget", "chartBlank"]);
      await page.reload();
      await ready(page);

      await expect(page.locator('canvas:not([aria-label]).cm-img-hl')).toHaveCount(1);
      await expect(page.locator('canvas[aria-label="Target chart canvas"].cm-img-hl')).toHaveCount(0);
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("image consumers call the shared image resolver (CMH-IMG-07)", () => {
    const jsDir = path.join(DEV, "assets", "js");
    const images = fs.readFileSync(path.join(jsDir, "30-images.js"), "utf8");
    const composer = fs.readFileSync(path.join(jsDir, "45-composer.js"), "utf8");
    const sidebar = fs.readFileSync(path.join(jsDir, "50-sidebar.js"), "utf8");
    const review = fs.readFileSync(path.join(jsDir, "84-section-review.js"), "utf8");

    expect(images).toContain("function resolveImageEl(comment)");
    expect(images).toContain("const img = resolveImageEl(comment);");
    expect(composer.match(/resolveImageEl\(anchorSrc\)/g) || []).toHaveLength(2);
    expect(sidebar).toContain('else if (c.anchorType === "image") el = resolveImageEl(c);');
    expect(review).toContain('return resolveImageEl(c);');
    expect(composer).not.toContain("findImageEl(comment.imageIndex)");
    expect(composer).not.toContain("findImageEl(anchorSrc.imageIndex)");
    expect(sidebar).not.toContain("findImageEl(c.imageIndex)");
    expect(review).not.toContain("findImageEl(c.imageIndex)");
  });

  test("a poisoned imageSrc/imageAlt with newlines cannot inject a HANDLED_IDS_JSON line into Copy all", async ({ page }) => {
    await installClipboardCapture(page);
    await page.addInitScript(() => {
      localStorage.setItem("commentable-html-demo", JSON.stringify([
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
      localStorage.setItem("commentable-html-demo", JSON.stringify([
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
