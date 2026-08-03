// Image comment layer: structural (reload-stable) comments anchored to an <img>
// by (imageIndex) + src, mirroring the mermaid-node layer.
import { test, expect } from "@playwright/test";
import { openInline, ready, copiedBundle, fileUrl, INLINE, installClipboardCapture, DEV,
  clickSidebarExport, stageContent, denyExternalNetwork, storedComments, EXAMPLES } from "./helpers.js";
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
    html = html.replace('data-doc-source="SHAREABLE.html"', 'data-doc-source="image-order.html"');
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

      // Editing the card is inline in the sidebar; the reordered anchor must survive it, so the
      // ring stays on the FIRST image and the stored anchor metadata is untouched.
      await card.locator('[data-act="edit"]').click();
      const editor = card.locator(".cm-entry-root .cm-reply-compose");
      await editor.locator("textarea").fill("target the first image (edited)");
      await editor.locator(".cm-reply-save").click();
      await expect(page.locator(`.cm-card[data-cid="${cid}"] .note`)).toContainText("target the first image (edited)");
      await expect(page.locator('img[src="first-image.png"].cm-img-hl')).toHaveCount(1);
      await expect(page.locator('img[src="second-image.png"].cm-img-hl')).toHaveCount(0);
      const stillFirst = await page.evaluate((id) => {
        const el = document.querySelector(`img[data-cid="${id}"]`);
        return el ? el.getAttribute("src") : null;
      }, cid);
      expect(stillFirst).toBe("first-image.png");
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

// CMH-IMG-08: an authored inline <svg> figure is commentable media exactly like an <img>, while
// every SVG the runtime (or another layer) owns stays untouched.
const SVG_FIGURE = "#commentRoot svg.cm-img-commentable";
const SVG_LABEL = "Quarterly burndown sketch";

function svgFigureContent() {
  return `<h1>Inline SVG figures</h1>
    <section aria-labelledby="svg-title">
      <h2 id="svg-title">Figures</h2>
      <figure>
        <svg width="220" height="120" viewBox="0 0 220 120" role="img" aria-label="${SVG_LABEL}"
             style="display:block;border:2px solid #456;">
          <rect x="10" y="10" width="200" height="100" fill="#eef"></rect>
          <path d="M10 110 L210 20" stroke="#345" stroke-width="4" fill="none"></path>
          <svg x="150" y="70" width="40" height="40" viewBox="0 0 10 10"><circle cx="5" cy="5" r="4" fill="#b11f4b"></circle></svg>
        </svg>
        <figcaption>${SVG_LABEL}</figcaption>
      </figure>
      <p class="cm-skip"><svg data-case="cm-skip" width="16" height="16" viewBox="0 0 16 16"><rect width="16" height="16" fill="#999"></rect></svg> chrome icon</p>
      <p>Decorative <svg data-case="aria-hidden-self" aria-hidden="true" width="16" height="16" viewBox="0 0 16 16"><rect width="16" height="16" fill="#999"></rect></svg> bullet.</p>
      <p>Wrapped <span aria-hidden="true"><svg data-case="aria-hidden-wrapper" width="16" height="16" viewBox="0 0 16 16"><rect width="16" height="16" fill="#999"></rect></svg></span> icon.</p>
      <p>Presentational <svg data-case="role-presentation" role="presentation" width="16" height="16" viewBox="0 0 16 16"><rect width="16" height="16" fill="#999"></rect></svg> mark.</p>
      <p>None-role <svg data-case="role-none" role="none" width="16" height="16" viewBox="0 0 16 16"><rect width="16" height="16" fill="#999"></rect></svg> mark.</p>
      <svg data-case="sprite-defs" width="0" height="0" aria-label="sprite sheet"><defs><symbol id="ico-star"><path d="M0 0 L8 8"></path></symbol></defs></svg>
      <p>Hidden <svg data-case="display-none" style="display:none" width="16" height="16" viewBox="0 0 16 16"><rect width="16" height="16" fill="#999"></rect></svg> shape.</p>
      <p>Zero <svg data-case="zero-height" width="16" height="0" viewBox="0 0 16 16"><rect width="16" height="16" fill="#999"></rect></svg> shape.</p>
      <figure class="chart"><span class="cm-skip"><svg data-case="chart-chrome" width="40" height="20" viewBox="0 0 40 20" aria-label="chart chrome"><rect width="40" height="20" fill="#999"></rect></svg></span><figcaption>Chart chrome</figcaption></figure>
      <p><a href="#svg-title">Back to top <svg data-case="in-link" width="16" height="16" viewBox="0 0 16 16"><rect width="16" height="16" fill="#999"></rect></svg></a></p>
      <p><button type="button">Act <svg data-case="in-button" width="16" height="16" viewBox="0 0 16 16"><rect width="16" height="16" fill="#999"></rect></svg></button></p>
      <p><label>Pick <svg data-case="in-label" width="16" height="16" viewBox="0 0 16 16"><rect width="16" height="16" fill="#999"></rect></svg></label></p>
      <p><span role="button" tabindex="0">Go <svg data-case="in-role-button" width="16" height="16" viewBox="0 0 16 16"><rect width="16" height="16" fill="#999"></rect></svg></span></p>
      <details><summary>More <svg data-case="in-summary" width="16" height="16" viewBox="0 0 16 16"><rect width="16" height="16" fill="#999"></rect></svg></summary><p>Detail body.</p></details>
      <div data-cm-widget="flow">
        <svg data-case="widget-parts" width="120" height="60" viewBox="0 0 120 60">
          <g data-cm-part="node-a" data-cm-part-label="Node A"><rect x="4" y="4" width="60" height="40" fill="#cde"></rect></g>
        </svg>
      </div>
    </section>`;
}

const SVG_SKIP_CASES = ["cm-skip", "aria-hidden-self", "aria-hidden-wrapper", "role-presentation",
  "role-none", "sprite-defs", "display-none", "zero-height", "chart-chrome", "in-link", "in-button",
  "in-label", "in-role-button", "in-summary", "widget-parts"];

async function addSvgComment(page, note) {
  return addMediaComment(page, SVG_FIGURE, note);
}

// Unlabeled figures: no author label and (being inline svg) no src, so the stored index and the
// structural signature are the only things telling one from another.
const UNLABELED_SHAPES = {
  circle: '<circle cx="100" cy="45" r="40" fill="#dde"></circle>',
  rect: '<rect width="200" height="90" fill="#eef"></rect>',
  polygon: '<polygon points="10,80 100,10 190,80" fill="#edd"></polygon>',
};

function unlabeledFiguresContent(shapes) {
  return "<h1>Unlabeled figures</h1>" + shapes.map((name) => `
    <figure style="margin: 20px 0;">
      <svg width="200" height="90" viewBox="0 0 200 90" style="display:block;border:2px solid #456;">${UNLABELED_SHAPES[name]}</svg>
    </figure>`).join("\n");
}

async function addNthMediaComment(page, selector, nth, note) {
  await page.evaluate(([sel, i]) => {
    const el = document.querySelectorAll(sel)[i];
    el.scrollIntoView({ block: "center" });
    el.dispatchEvent(new MouseEvent("mouseenter", { bubbles: true }));
  }, [selector, nth]);
  await expect(page.locator("#imageAddBtn")).toBeVisible();
  await page.locator("#imageAddBtn").click();
  const composer = page.locator(".cm-composer").last();
  await composer.locator("textarea").fill(note);
  await composer.locator('[data-act="save"]').click();
  await expect(composer).toBeHidden();
}

async function seedComments(page, key, comments) {
  await page.addInitScript(([k, list]) => {
    localStorage.setItem(k, JSON.stringify(list));
  }, [key, comments]);
}

// Comment on one unlabeled figure and hand back the stored record (the anchor metadata a later
// document revision has to resolve) plus the Copy all bundle.
async function stageUnlabeledFigures(page, shapes, { key, note, target }) {
  const staged = stageContent(unlabeledFiguresContent(shapes), { key });
  await installClipboardCapture(page);
  await page.goto(fileUrl(staged.html));
  await ready(page);
  await addNthMediaComment(page, SVG_FIGURE, target, note);
  const stored = (await storedComments(page))[0];
  await page.click("#btnCopyAll");
  const bundle = await copiedBundle(page);
  return { dir: staged.dir, stored, bundle };
}

test.describe("inline svg figure comments (CMH-IMG-08)", () => {
  test("an inline <svg> figure is commentable media and reveals the + button on hover (CMH-IMG-08)", async ({ page }) => {
    const staged = stageContent(svgFigureContent(), { key: "cmh-svg-figure-hover" });
    try {
      await page.goto(fileUrl(staged.html));
      await ready(page);
      // Only the authored figure is commentable: chrome, decorative (own and wrapper
      // aria-hidden), presentational, sprite-sheet, link-icon, widget-owned and nested inner
      // SVG nodes are all skipped.
      await expect(page.locator(SVG_FIGURE)).toHaveCount(1);
      await expect(page.locator(SVG_FIGURE)).toHaveAttribute("aria-label", SVG_LABEL);
      await expect(page.locator(SVG_FIGURE)).toHaveAttribute("tabindex", "0");
      // A REAL pointer, not a synthetic event: an inline svg root hit-tests by SVG rules, so this
      // is what proves "hovering the figure offers the affordance".
      await page.locator(SVG_FIGURE).scrollIntoViewIfNeeded();
      await page.locator(SVG_FIGURE).hover();
      await expect(page.locator("#imageAddBtn")).toBeVisible();
      // The widget layer still owns the labeled <g> part inside the diagram SVG.
      await expect(page.locator("#commentRoot [data-cm-part].cm-part-commentable")).toHaveCount(1);
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("decorative, chrome, sprite-sheet and widget-owned svg stay uncommentable (CMH-IMG-08)", async ({ page }) => {
    const staged = stageContent(svgFigureContent(), { key: "cmh-svg-figure-skips" });
    try {
      await page.goto(fileUrl(staged.html));
      await ready(page);
      // Every skip rule is pinned INDIVIDUALLY, so a regression names the rule that broke.
      const state = await page.evaluate((cases) => {
        const out = {};
        cases.forEach((name) => {
          const el = document.querySelector(`#commentRoot svg[data-case="${name}"]`);
          out[name] = !el ? "missing" : {
            commentable: el.classList.contains("cm-img-commentable"),
            tabindex: el.getAttribute("tabindex"),
            index: el.getAttribute("data-cm-image-index"),
          };
        });
        return out;
      }, SVG_SKIP_CASES);
      for (const name of SVG_SKIP_CASES) {
        expect(state[name], `${name}: fixture element missing`).not.toBe("missing");
        expect(state[name].commentable, `${name}: should not be commentable`).toBe(false);
        expect(state[name].tabindex, `${name}: should not be focusable`).toBeNull();
        expect(state[name].index, `${name}: should not take an image index`).toBeNull();
      }
      // The nested inner <svg> of the authored figure is not a separate target either.
      await expect(page.locator(SVG_FIGURE)).toHaveCount(1);
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("an svg named by aria-labelledby anchors by that name (CMH-IMG-08)", async ({ page }) => {    const content = `<h1>Labelledby svg</h1>
      <figure>
        <svg width="220" height="120" viewBox="0 0 220 120" aria-labelledby="cap-a"><rect width="220" height="120" fill="#eef"></rect></svg>
        <figcaption id="cap-a">Error budget burn</figcaption>
      </figure>`;
    const staged = stageContent(content, { key: "cmh-svg-labelledby" });
    try {
      await page.goto(fileUrl(staged.html));
      await ready(page);
      // A name the author supplied indirectly is still the author's name: no synthesized label.
      await expect(page.locator(SVG_FIGURE)).not.toHaveAttribute("data-cm-img-auto-label", "1");
      await addSvgComment(page, "labelledby note");
      const stored = await storedComments(page);
      expect(stored[0].imageAlt).toBe("Error budget burn");
      expect(stored[0].quote).toBe("Error budget burn");
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("an unlabeled svg inside figure.chart is chart media (CMH-IMG-08)", async ({ page }) => {
    const content = `<h1>Chart svg</h1>
      <figure class="chart">
        <svg width="220" height="120" viewBox="0 0 220 120"><rect width="220" height="120" fill="#eef"></rect></svg>
        <figcaption>Hand-drawn chart</figcaption>
      </figure>`;
    const staged = stageContent(content, { key: "cmh-svg-chart-kind" });
    try {
      await page.goto(fileUrl(staged.html));
      await ready(page);
      await addSvgComment(page, "chart svg note");
      const stored = await storedComments(page);
      expect(stored[0].imageKind).toBe("chart");
      expect(stored[0].quote).toBe("chart 1");
      await expect(page.locator(".cm-card").filter({ hasText: "chart svg note" })).toContainText(/chart 1/);
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("a link that wraps only the figure keeps it commentable (CMH-IMG-08)", async ({ page }) => {
    const content = `<h1>Linked figure</h1>
      <figure>
        <a href="full-size.html"><svg width="220" height="120" viewBox="0 0 220 120" aria-label="Linked schematic"><rect width="220" height="120" fill="#eef"></rect></svg></a>
        <figcaption>Open the schematic full size.</figcaption>
      </figure>`;
    const staged = stageContent(content, { key: "cmh-svg-linked-figure" });
    try {
      await page.goto(fileUrl(staged.html));
      await ready(page);
      // A linked <img> stays commentable, so a linked figure svg must too - only an icon sitting
      // beside link TEXT is chrome.
      await expect(page.locator(SVG_FIGURE)).toHaveCount(1);
      await addSvgComment(page, "linked figure note");
      const stored = await storedComments(page);
      expect(stored[0].imageAlt).toBe("Linked schematic");
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("a forged auto-label marker cannot hide the author's own name (CMH-IMG-08)", async ({ page }) => {
    const content = `<h1>Forged marker</h1>
      <figure>
        <svg data-cm-img-auto-label="1" aria-label="Innocent chart" width="220" height="120" viewBox="0 0 220 120">
          <title>Something else entirely</title>
          <rect width="220" height="120" fill="#eef"></rect>
        </svg>
      </figure>`;
    const staged = stageContent(content, { key: "cmh-svg-forged-marker" });
    try {
      await page.goto(fileUrl(staged.html));
      await ready(page);
      await addSvgComment(page, "forged marker note");
      // The stored metadata matches what a reader/AT sees, not the shadowed <title>.
      const stored = await storedComments(page);
      expect(stored[0].imageAlt).toBe("Innocent chart");
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("an svg labelled only by a direct-child title anchors by that title (CMH-IMG-08)", async ({ page }) => {
    const content = `<h1>Title-labelled svg</h1>
      <figure>
        <svg width="220" height="120" viewBox="0 0 220 120">
          <title>Latency budget sketch</title>
          <g><title>inner tooltip</title><rect x="10" y="10" width="200" height="100" fill="#eef"></rect></g>
        </svg>
      </figure>`;
    const staged = stageContent(content, { key: "cmh-svg-figure-title" });
    try {
      await installClipboardCapture(page);
      await page.goto(fileUrl(staged.html));
      await ready(page);
      await addSvgComment(page, "title-labelled note");
      const card = page.locator(".cm-card").filter({ hasText: "title-labelled note" });
      await expect(card).toContainText("Latency budget sketch");
      await expect(card).not.toContainText("inner tooltip");
      await page.click("#btnCopyAll");
      expect(await copiedBundle(page)).toContain("Alt: Latency budget sketch");
      // The author's own name is never overwritten by an affordance label.
      await expect(page.locator(SVG_FIGURE)).not.toHaveAttribute("aria-label", /press Enter/);
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("an unlabeled svg is named for AT, quotes image N, and survives reload (CMH-IMG-08)", async ({ page }) => {
    const content = `<h1>Unlabeled svg</h1>
      <figure>
        <svg width="220" height="120" viewBox="0 0 220 120"><rect x="10" y="10" width="200" height="100" fill="#eef"></rect></svg>
      </figure>`;
    const staged = stageContent(content, { key: "cmh-svg-figure-unlabeled" });
    try {
      await page.goto(fileUrl(staged.html));
      await ready(page);
      const figure = page.locator(SVG_FIGURE);
      // A focusable graphic must never be nameless, but the synthesized name is marked so it
      // cannot leak into the anchor metadata.
      await expect(figure).toHaveAttribute("role", "img");
      await expect(figure).toHaveAttribute("aria-label", "Image - press Enter to comment");
      await expect(figure).toHaveAttribute("data-cm-img-auto-label", "1");
      await addSvgComment(page, "unlabeled svg note");
      const stored = await storedComments(page);
      expect(stored).toHaveLength(1);
      expect(stored[0].imageAlt).toBe("");
      expect(stored[0].quote).toBe("image 1");
      const cid = await page.locator("svg.cm-img-hl").getAttribute("data-cid");
      await page.reload();
      await ready(page);
      await expect(page.locator(`svg.cm-img-hl[data-cid="${cid}"]`)).toHaveCount(1);
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("an svg anchor is not re-attached to an <img> that has a src (CMH-IMG-09)", async ({ page }) => {
    const content = `<h1>Media mix</h1>
      <p><img src="only-image.png" alt="Capacity headroom" width="60" height="40"></p>
      <figure><svg width="220" height="120" viewBox="0 0 220 120" aria-label="Capacity headroom"><rect x="10" y="10" width="200" height="100" fill="#eef"></rect></svg></figure>`;
    const staged = stageContent(content, { key: "cmh-svg-vs-img" });
    try {
      // The image and the svg carry the SAME alt and the same kind, so ONLY the stored-but-empty
      // imageSrc can tell them apart: the stored svg anchor must not ring the image.
      await page.addInitScript(() => {
        localStorage.setItem("cmh-svg-vs-img", JSON.stringify([
          { id: "csvgimg01", anchorType: "image", imageIndex: 0, imageSrc: "",
            imageAlt: "Capacity headroom", imageKind: "image", quote: "Capacity headroom",
            note: "svg only", createdAt: new Date().toISOString() },
        ]));
      });
      await page.goto(fileUrl(staged.html));
      await ready(page);
      await expect(page.locator("img.cm-img-hl")).toHaveCount(0);
      await expect(page.locator("svg.cm-img-hl")).toHaveCount(1);
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("two unlabeled svg figures leave a reordered anchor unresolved instead of misattributing it (CMH-IMG-09)", async ({ page }) => {
    const content = `<h1>Two unlabeled figures</h1>
      <p><img src="pushed-in.png" alt="Pushed in" width="60" height="40"></p>
      <figure><svg width="200" height="90" viewBox="0 0 200 90"><rect width="200" height="90" fill="#eef"></rect></svg></figure>
      <figure><svg width="200" height="90" viewBox="0 0 200 90"><circle cx="100" cy="45" r="40" fill="#dde"></circle></svg></figure>`;
    const staged = stageContent(content, { key: "cmh-svg-ambiguous" });
    try {
      // The comment was saved on an svg that used to be index 0; an image now occupies that slot
      // and both surviving svgs are indistinguishable, so the anchor must fail safe.
      await page.addInitScript(() => {
        localStorage.setItem("cmh-svg-ambiguous", JSON.stringify([
          { id: "csvgamb01", anchorType: "image", imageIndex: 0, imageSrc: "", imageAlt: "",
            imageKind: "image", quote: "image 1", note: "ambiguous svg", createdAt: new Date().toISOString() },
        ]));
      });
      await page.goto(fileUrl(staged.html));
      await ready(page);
      await expect(page.locator("svg.cm-img-hl")).toHaveCount(0);
      await expect(page.locator("img.cm-img-hl")).toHaveCount(0);
      // The comment itself is not lost - it is still listed, just not anchored.
      await expect(page.locator(".cm-card").filter({ hasText: "ambiguous svg" })).toHaveCount(1);
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("an unlabeled figure re-anchors by its structural signature after the media order shifts (CMH-IMG-11)", async ({ page }) => {
    // Unlabeled media has no src and no label, so before the signature the stored index was its
    // ONLY identity: inserting a figure ahead of it silently moved the comment to a different one.
    const first = await stageUnlabeledFigures(page, ["circle", "rect"], {
      key: "cmh-svg-sig-write", note: "signature note", target: 1,
    });
    try {
      expect(typeof first.stored.imageSig).toBe("string");
      expect(first.stored.imageSig.length).toBeGreaterThan(0);
      // The discriminator is anchor plumbing, never reader-facing text.
      expect(first.bundle).not.toContain(first.stored.imageSig);
      expect(first.bundle).toMatch(/Anchor: image #2/);
    } finally {
      fs.rmSync(first.dir, { recursive: true, force: true });
    }
    // A figure is inserted ahead of the commented one, so the stored index now points at a
    // DIFFERENT unlabeled figure that is identical in every other respect.
    const staged = stageContent(unlabeledFiguresContent(["circle", "polygon", "rect"]),
      { key: "cmh-svg-sig-shift" });
    try {
      await seedComments(page, "cmh-svg-sig-shift", [{ ...first.stored, id: "csvgsig01" }]);
      await page.goto(fileUrl(staged.html));
      await ready(page);
      await expect(page.locator("svg.cm-img-hl")).toHaveCount(1);
      await expect(page.locator("svg.cm-img-hl")).toHaveAttribute("data-cm-image-index", "2");
      await expect(page.locator("svg.cm-img-hl > rect")).toHaveCount(1);
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("a stored comment that predates the structural signature resolves unchanged (CMH-IMG-11)", async ({ page }) => {
    const staged = stageContent(unlabeledFiguresContent(["circle", "rect"]),
      { key: "cmh-svg-sig-legacy" });
    try {
      // No imageSig field at all: the resolver must take neither the mismatch nor the
      // tie-breaker path and anchor by the stored index exactly as it did before.
      await seedComments(page, "cmh-svg-sig-legacy", [
        { id: "csvgleg01", anchorType: "image", imageIndex: 1, imageSrc: "", imageAlt: "",
          imageKind: "image", quote: "image 2", note: "legacy svg note",
          createdAt: new Date().toISOString() },
      ]);
      await page.goto(fileUrl(staged.html));
      await ready(page);
      await expect(page.locator("svg.cm-img-hl")).toHaveCount(1);
      await expect(page.locator("svg.cm-img-hl")).toHaveAttribute("data-cm-image-index", "1");
      await expect(page.locator("svg.cm-img-hl > rect")).toHaveCount(1);
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("a labelled figure whose drawing changed keeps its anchor (CMH-IMG-11)", async ({ page }) => {
    const content = `<h1>Redrawn figure</h1>
      <figure><svg width="200" height="90" viewBox="0 0 200 90" aria-label="Capacity headroom"><rect width="200" height="90" fill="#eef"></rect><circle cx="40" cy="40" r="10" fill="#345"></circle></svg></figure>`;
    const staged = stageContent(content, { key: "cmh-svg-sig-redrawn" });
    try {
      // The signature is the discriminator of LAST resort: a labelled graphic still resolves by
      // its label, so redrawing it (a different shape signature) must not orphan the comment.
      await seedComments(page, "cmh-svg-sig-redrawn", [
        { id: "csvgred01", anchorType: "image", imageIndex: 0, imageSrc: "",
          imageAlt: "Capacity headroom", imageKind: "image", imageSig: "stalesig",
          quote: "Capacity headroom", note: "redrawn svg note",
          createdAt: new Date().toISOString() },
      ]);
      await page.goto(fileUrl(staged.html));
      await ready(page);
      await expect(page.locator("svg.cm-img-hl")).toHaveCount(1);
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("unlabeled figures that differ only in what they draw are told apart (CMH-IMG-11)", async ({ page }) => {
    // A tag/child-shape digest alone would collide here: both figures are one <rect> in the same
    // viewBox, so only the drawing attributes separate them.
    const wide = '<rect x="0" y="0" width="200" height="90" fill="#eef"></rect>';
    const narrow = '<rect x="20" y="20" width="60" height="50" fill="#dde"></rect>';
    const shapes = (list) => "<h1>Same shape, different drawing</h1>" + list.map((inner) => `
      <figure style="margin: 20px 0;">
        <svg width="200" height="90" viewBox="0 0 200 90" style="display:block;border:2px solid #456;">${inner}</svg>
      </figure>`).join("\n");
    const first = stageContent(shapes([wide, narrow]), { key: "cmh-svg-sig-attrs-write" });
    let stored;
    try {
      await page.goto(fileUrl(first.html));
      await ready(page);
      await addNthMediaComment(page, SVG_FIGURE, 1, "narrow rect note");
      stored = (await storedComments(page))[0];
    } finally {
      fs.rmSync(first.dir, { recursive: true, force: true });
    }
    const staged = stageContent(shapes([wide, wide, narrow]), { key: "cmh-svg-sig-attrs" });
    try {
      await seedComments(page, "cmh-svg-sig-attrs", [{ ...stored, id: "csvgatt01" }]);
      await page.goto(fileUrl(staged.html));
      await ready(page);
      await expect(page.locator("svg.cm-img-hl")).toHaveCount(1);
      await expect(page.locator("svg.cm-img-hl")).toHaveAttribute("data-cm-image-index", "2");
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("unlabeled chart canvases are told apart by their authored caption (CMH-IMG-11)", async ({ page }) => {
    // A bare <canvas class="cmh-chart"> carries nothing of its own - no label, no src, no chart data
    // attributes - so the figure's caption is the only authored thing that identifies it.
    const charts = (captions) => "<h1>Bare charts</h1>" + captions.map((caption) => `
      <figure class="chart" style="margin: 20px 0;">
        <canvas class="cmh-chart" width="220" height="120" style="display:block;border:2px solid #456;"></canvas>
        <figcaption>${caption}</figcaption>
      </figure>`).join("\n");
    const first = stageContent(charts(["Latency by region", "Throughput by tier"]),
      { key: "cmh-canvas-sig-write" });
    let stored;
    try {
      await page.goto(fileUrl(first.html));
      await ready(page);
      await addNthMediaComment(page, "#commentRoot canvas.cm-img-commentable", 1, "throughput note");
      stored = (await storedComments(page))[0];
      expect(stored.imageAlt).toBe("");
      expect(stored.imageKind).toBe("chart");
    } finally {
      fs.rmSync(first.dir, { recursive: true, force: true });
    }
    const staged = stageContent(charts(["Latency by region", "Queue depth", "Throughput by tier"]),
      { key: "cmh-canvas-sig" });
    try {
      await seedComments(page, "cmh-canvas-sig", [{ ...stored, id: "ccanvsig01" }]);
      await page.goto(fileUrl(staged.html));
      await ready(page);
      await expect(page.locator("canvas.cm-img-hl")).toHaveCount(1);
      await expect(page.locator("canvas.cm-img-hl")).toHaveAttribute("data-cm-image-index", "2");
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("a poisoned or oversized stored signature is treated as absent (CMH-IMG-11)", async ({ page }) => {
    const staged = stageContent(unlabeledFiguresContent(["circle", "rect"]),
      { key: "cmh-svg-sig-poison" });
    try {
      await installClipboardCapture(page);
      // A shared report's stored payload is attacker-influenced: a value that is not a digest this
      // runtime could have written must not steer resolution, it must simply not count.
      await seedComments(page, "cmh-svg-sig-poison", [
        { id: "csvgpsn01", anchorType: "image", imageIndex: 1, imageSrc: "", imageAlt: "",
          imageKind: "image", imageSig: "<img src=x onerror=\"window.__xss=1\">".repeat(200),
          quote: "image 2", note: "poisoned sig note", createdAt: new Date().toISOString() },
      ]);
      await page.goto(fileUrl(staged.html));
      await ready(page);
      await expect(page.locator("svg.cm-img-hl")).toHaveCount(1);
      await expect(page.locator("svg.cm-img-hl")).toHaveAttribute("data-cm-image-index", "1");
      expect(await page.evaluate(() => window.__xss)).toBeUndefined();
      await page.click("#btnCopyAll");
      expect(await copiedBundle(page)).not.toContain("onerror");
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("a well-formed but unreachable stored signature is treated as absent (CMH-IMG-11)", async ({ page }) => {
    // Every one of these is well-FORMED base 36 but unreachable for a 32-bit digest rendered with
    // toString(36): too long, out of uint32 range, and a non-canonical leading zero. None may steer
    // resolution - each comment must anchor by its index exactly like a pre-signature one.
    const cases = [
      { id: "csvglong01", imageSig: "1z141z30", index: 0 },
      { id: "csvgover01", imageSig: "zzzzzzz", index: 1 },
      { id: "csvgzero01", imageSig: "01z141z", index: 2 },
    ];
    const staged = stageContent(unlabeledFiguresContent(["circle", "rect", "polygon"]),
      { key: "cmh-svg-sig-unreachable" });
    try {
      await seedComments(page, "cmh-svg-sig-unreachable", cases.map((c) => ({
        id: c.id, anchorType: "image", imageIndex: c.index, imageSrc: "", imageAlt: "",
        imageKind: "image", imageSig: c.imageSig, quote: "image " + (c.index + 1),
        note: "unreachable sig " + c.id, createdAt: new Date().toISOString(),
      })));
      await page.goto(fileUrl(staged.html));
      await ready(page);
      await expect(page.locator("svg.cm-img-hl")).toHaveCount(3);
      for (const c of cases) {
        await expect(page.locator(`svg.cm-img-hl[data-cids~="${c.id}"]`))
          .toHaveAttribute("data-cm-image-index", String(c.index));
      }
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("an unlabeled figure whose own drawing changed fails safe instead of guessing (CMH-IMG-11)", async ({ page }) => {
    const first = await stageUnlabeledFigures(page, ["circle", "rect"], {
      key: "cmh-svg-sig-redraw-write", note: "redrawn unlabeled note", target: 1,
    });
    fs.rmSync(first.dir, { recursive: true, force: true });
    // The commented figure is redrawn in place. There is nothing left that identifies it - a
    // redrawn figure and a deleted one whose index another figure inherited look identical - so the
    // anchor must go unresolved rather than ring the wrong graphic.
    const staged = stageContent(unlabeledFiguresContent(["circle", "polygon"]),
      { key: "cmh-svg-sig-redraw" });
    try {
      await seedComments(page, "cmh-svg-sig-redraw", [{ ...first.stored, id: "csvgrdw01" }]);
      await page.goto(fileUrl(staged.html));
      await ready(page);
      await expect(page.locator("svg.cm-img-hl")).toHaveCount(0);
      // The comment is not lost, only unanchored.
      await expect(page.locator(".cm-card").filter({ hasText: "redrawn unlabeled note" })).toHaveCount(1);
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("figures that draw the same shapes with different text are told apart (CMH-IMG-11)", async ({ page }) => {
    // Same tags, same geometry, same caption-less figure: only the <text> label differs, which a
    // shape-and-attributes-only digest would miss.
    const labelled = (word) => `<rect width="200" height="90" fill="#eef"></rect><text x="20" y="50">${word}</text>`;
    const shapes = (words) => "<h1>Same shapes, different text</h1>" + words.map((word) => `
      <figure style="margin: 20px 0;">
        <svg width="200" height="90" viewBox="0 0 200 90" style="display:block;border:2px solid #456;">${labelled(word)}</svg>
      </figure>`).join("\n");
    const first = stageContent(shapes(["Alpha", "Beta"]), { key: "cmh-svg-sig-text-write" });
    let stored;
    try {
      await page.goto(fileUrl(first.html));
      await ready(page);
      await addNthMediaComment(page, SVG_FIGURE, 1, "beta note");
      stored = (await storedComments(page))[0];
      expect(stored.imageAlt).toBe("");
    } finally {
      fs.rmSync(first.dir, { recursive: true, force: true });
    }
    const staged = stageContent(shapes(["Alpha", "Gamma", "Beta"]), { key: "cmh-svg-sig-text" });
    try {
      await seedComments(page, "cmh-svg-sig-text", [{ ...stored, id: "csvgtxt01" }]);
      await page.goto(fileUrl(staged.html));
      await ready(page);
      await expect(page.locator("svg.cm-img-hl")).toHaveCount(1);
      await expect(page.locator("svg.cm-img-hl")).toHaveAttribute("data-cm-image-index", "2");
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("the signature narrows duplicate LABELLED figures that metadata cannot separate (CMH-IMG-11)", async ({ page }) => {
    // Two figures share one label, so the metadata fallback matches both and used to give up. The
    // signature separates them - and because they carry a label, it is only ever a tie-breaker.
    const shapes = (list) => "<h1>Duplicate labels</h1>" + list.map((inner) => `
      <figure style="margin: 20px 0;">
        <svg width="200" height="90" viewBox="0 0 200 90" aria-label="Capacity headroom" style="display:block;border:2px solid #456;">${inner}</svg>
      </figure>`).join("\n");
    const circle = '<circle cx="100" cy="45" r="40" fill="#dde"></circle>';
    const rect = '<rect width="200" height="90" fill="#eef"></rect>';
    const first = stageContent(shapes([circle, rect]), { key: "cmh-svg-sig-dup-write" });
    let stored;
    try {
      await page.goto(fileUrl(first.html));
      await ready(page);
      await addNthMediaComment(page, SVG_FIGURE, 1, "duplicate label note");
      stored = (await storedComments(page))[0];
      expect(stored.imageAlt).toBe("Capacity headroom");
    } finally {
      fs.rmSync(first.dir, { recursive: true, force: true });
    }
    const staged = stageContent(shapes([circle, circle, rect]), { key: "cmh-svg-sig-dup" });
    try {
      await seedComments(page, "cmh-svg-sig-dup", [{ ...stored, id: "csvgdup01", imageIndex: 5 }]);
      await page.goto(fileUrl(staged.html));
      await ready(page);
      await expect(page.locator("svg.cm-img-hl")).toHaveCount(1);
      await expect(page.locator("svg.cm-img-hl")).toHaveAttribute("data-cm-image-index", "2");
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("an unlabeled figure's signature survives Export as Shareable and re-anchors on reopen (CMH-IMG-11)", async ({ page, browser }) => {
    const staged = stageContent(unlabeledFiguresContent(["circle", "rect"]),
      { key: "cmh-svg-sig-export" });
    try {
      await page.goto(fileUrl(staged.html));
      await ready(page);
      await addNthMediaComment(page, SVG_FIGURE, 1, "exported unlabeled note");
      const cid = await page.locator("svg.cm-img-hl").getAttribute("data-cid");
      const sig = (await storedComments(page))[0].imageSig;
      const [dl] = await Promise.all([
        page.waitForEvent("download"),
        clickSidebarExport(page, "#btnSaveHtml"),
      ]);
      const html = fs.readFileSync(await dl.path(), "utf8");
      const arr = JSON.parse(html.match(/id="embeddedComments">([\s\S]*?)<\/script>/)[1].trim());
      // The signature must ride along in the embedded record - it is the reopened copy's only way
      // to tell this unlabeled figure from the other one.
      expect(arr.find((c) => c.id === cid).imageSig).toBe(sig);
      const saved = path.join(staged.dir, "svg-sig-shareable.html");
      fs.writeFileSync(saved, html);
      const ctx2 = await browser.newContext();
      const page2 = await ctx2.newPage();
      try {
        await page2.goto(fileUrl(saved));
        await ready(page2);
        // The reopened copy recomputes the same digest from its own DOM, so the ring lands back on
        // the same figure rather than the other unlabeled one.
        await expect(page2.locator(`svg.cm-img-hl[data-cid="${cid}"]`)).toHaveCount(1);
        await expect(page2.locator("svg.cm-img-hl")).toHaveAttribute("data-cm-image-index", "1");
      } finally {
        await ctx2.close();
      }
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("an inline <svg> figure is keyboard-commentable and rings like an image (CMH-IMG-08)", async ({ page }) => {
    const staged = stageContent(svgFigureContent(), { key: "cmh-svg-figure-keyboard" });
    try {
      await page.goto(fileUrl(staged.html));
      await ready(page);
      await page.locator(SVG_FIGURE).focus();
      await expect(page.locator("#imageAddBtn")).toBeVisible();
      await page.locator(SVG_FIGURE).press("Enter");
      const composer = page.locator(".cm-composer").last();
      await expect(composer).toBeVisible();
      await composer.locator("textarea").fill("label the trend line");
      await composer.locator('[data-act="save"]').click();
      await expect(page.locator("svg.cm-img-hl")).toHaveCount(1);
      const card = page.locator(".cm-card").filter({ hasText: "label the trend line" });
      await expect(card).toHaveCount(1);
      await expect(card).toContainText(/image 1/);
      await expect(card).toContainText(SVG_LABEL);
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("an inline <svg> comment survives reload and Copy all (CMH-IMG-08)", async ({ page }) => {
    const staged = stageContent(svgFigureContent(), { key: "cmh-svg-figure-reload" });
    try {
      await installClipboardCapture(page);
      await page.goto(fileUrl(staged.html));
      await ready(page);
      await addSvgComment(page, "svg reload note");
      const cid = await page.locator("svg.cm-img-hl").getAttribute("data-cid");
      await page.reload();
      await ready(page);
      await expect(page.locator(`svg.cm-img-hl[data-cid="${cid}"]`)).toHaveCount(1);
      await expect(page.locator(".cm-card").filter({ hasText: "svg reload note" })).toHaveCount(1);
      await page.click("#btnCopyAll");
      const bundle = await copiedBundle(page);
      expect(bundle).toContain("## Comment 1 (image)");
      expect(bundle).toMatch(/Anchor: image #1/);
      expect(bundle).toContain("Alt: " + SVG_LABEL);
      expect(bundle).toContain("svg reload note");
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("an inline <svg> comment survives Export as Shareable + reopen (CMH-IMG-08)", async ({ page, browser }) => {
    const staged = stageContent(svgFigureContent(), { key: "cmh-svg-figure-export" });
    let saved = null;
    try {
      await page.goto(fileUrl(staged.html));
      await ready(page);
      await addSvgComment(page, "embedded svg note");
      const cid = await page.locator("svg.cm-img-hl").getAttribute("data-cid");
      const [dl] = await Promise.all([
        page.waitForEvent("download"),
        clickSidebarExport(page, "#btnSaveHtml"),
      ]);
      const html = fs.readFileSync(await dl.path(), "utf8");
      const arr = JSON.parse(html.match(/id="embeddedComments">([\s\S]*?)<\/script>/)[1].trim());
      expect(arr.find((c) => c.id === cid && c.anchorType === "image")).toBeTruthy();
      saved = path.join(staged.dir, "svg-shareable.html");
      fs.writeFileSync(saved, html);
      const ctx2 = await browser.newContext();
      const page2 = await ctx2.newPage();
      try {
        await page2.goto(fileUrl(saved));
        await ready(page2);
        await expect(page2.locator(`svg.cm-img-hl[data-cid="${cid}"]`)).toHaveCount(1);
        await expect(page2.locator(".cm-card").filter({ hasText: "embedded svg note" })).toHaveCount(1);
      } finally {
        await ctx2.close();
      }
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("deleting an inline <svg> comment clears its ring (CMH-IMG-08)", async ({ page }) => {
    const staged = stageContent(svgFigureContent(), { key: "cmh-svg-figure-delete" });
    try {
      await page.goto(fileUrl(staged.html));
      await ready(page);
      page.on("dialog", (d) => d.accept());
      await addSvgComment(page, "remove the svg note");
      await expect(page.locator("svg.cm-img-hl")).toHaveCount(1);
      await page.locator(".cm-card").filter({ hasText: "remove the svg note" }).locator('[data-act="del"]').click();
      await expect(page.locator("svg.cm-img-hl")).toHaveCount(0);
      await expect(page.locator(".cm-card")).toHaveCount(0);
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  // The behavior ships in a live demo: the visuals-matrix report carries a plain inline <svg>
  // figure beside the labeled-parts diagram, so a reader can actually try it.
  test("media metadata is normalized at the write side, not just on the way out (CMH-IMG-10)", async ({ page }) => {
    // The label carries a NEL, a Unicode line separator, a paragraph separator, an RLO and an
    // ALM - every class the stored metadata must never keep.
    const label = "Cap\u0085acity\u2028head\u2029room \u202Erev\u061Cersed";
    const content = `<h1>Hostile label</h1>
      <figure><svg width="220" height="120" viewBox="0 0 220 120" aria-label="${label}"><rect width="220" height="120" fill="#eef"></rect></svg></figure>`;
    const staged = stageContent(content, { key: "cmh-svg-write-side" });
    try {
      await installClipboardCapture(page);
      await page.goto(fileUrl(staged.html));
      await ready(page);
      await addSvgComment(page, "hostile label note");
      const stored = await storedComments(page);
      expect(stored).toHaveLength(1);
      // Persisted already inert: one line, no bidi controls - not merely sanitized on emission.
      expect(stored[0].imageAlt).toBe("Cap acity head room reversed");
      expect(stored[0].imageAlt).not.toMatch(/[\u0085\u2028\u2029\u061C\u200E\u200F\u202A-\u202E\u2066-\u2069]/);
      expect(stored[0].quote).toBe(stored[0].imageAlt);
      await page.click("#btnCopyAll");
      const bundle = await copiedBundle(page);
      expect((bundle.match(/^HANDLED_IDS_JSON:/gm) || []).length).toBe(1);
      expect(bundle).toContain("Alt: " + stored[0].imageAlt);
    } finally {
      fs.rmSync(staged.dir, { recursive: true, force: true });
    }
  });

  test("the visuals-matrix demo ships a commentable inline <svg> figure (CMH-IMG-08, CMH-DEMO-08)", async ({ page }) => {
    await denyExternalNetwork(page);
    await page.goto(fileUrl(path.join(EXAMPLES, "report-metrics.html")));
    await ready(page);
    const figure = page.locator("#commentRoot svg.cm-img-commentable");
    await expect(figure).toHaveCount(1);
    await expect(figure).toHaveAttribute("aria-label", "Capacity headroom by region");
    // The labeled-parts diagram stays with the widget layer, not the image layer.
    await expect(page.locator('#commentRoot svg[data-cm-widget="metric-signal-svg"].cm-img-commentable')).toHaveCount(0);
    await expect(page.locator('#commentRoot [data-cm-part-label="Ingest node"].cm-part-commentable')).toHaveCount(1);
    await figure.focus();
    await expect(page.locator("#imageAddBtn")).toBeVisible();
  });
});
