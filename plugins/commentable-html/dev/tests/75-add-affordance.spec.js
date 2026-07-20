// Unified structural-anchor add-comment affordance (CMH-ANCHOR-01): the image, mermaid,
// diff, link, widget, and heading layers share one active affordance, so only one floating
// "Add Comment" button is shown at a time and a nested <a><img></a> resolves to exactly one
// owner (the inner image).
import { test, expect } from "@playwright/test";
import { ready, fileUrl, stageContent, installClipboardCapture } from "./helpers.js";

// A tiny inline 1x1 GIF; the width/height attributes give it a real 60x60 layout box so the
// image layer's hover affordance measures and positions (no network, fully hermetic).
const IMG_SRC = "data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==";
const CONTENT = `
<h2 id="lead">Affordance</h2>
<p id="p1">A clickable thumbnail:
  <a id="thumb" href="https://example.com/home"><img id="thumbimg" src="${IMG_SRC}" alt="logo" width="60" height="60"></a>
</p>
<p id="p2">Then, further down, a standalone
  <a id="plainlink" href="https://example.com/docs">reference link</a> and a standalone
  <img id="plainimg" src="${IMG_SRC}" alt="figure" width="60" height="60"> image.</p>
<h2 id="sec">Section with a <a id="seclink" href="https://example.com/ref">reference</a> inside it</h2>`;

async function stage(page) {
  const { html } = stageContent(CONTENT, { key: "cmh-affordance-test" });
  await installClipboardCapture(page);
  await page.goto(fileUrl(html));
  await ready(page);
}

// Fire a real-hover-style mouseenter on each element id, in the given order, so a test can
// prove the affordance owner is deterministic regardless of which layer's handler runs first.
async function hover(page, ids) {
  await page.evaluate((list) => {
    list.forEach((id) => {
      const el = document.getElementById(id);
      el.scrollIntoView({ block: "center" });
      el.dispatchEvent(new MouseEvent("mouseenter", { bubbles: false }));
    });
  }, ids);
}

test.describe("unified add-comment affordance", () => {
  test("a nested <a><img></a> shows exactly one affordance - the image, when the image fires first (CMH-ANCHOR-01)", async ({ page }) => {
    await stage(page);
    await hover(page, ["thumbimg", "thumb"]);
    await expect(page.locator("#imageAddBtn")).toBeVisible();
    await expect(page.locator("#linkAddBtn")).toBeHidden();
  });

  test("a nested <a><img></a> shows exactly one affordance - the image, when the link fires first (CMH-ANCHOR-01)", async ({ page }) => {
    await stage(page);
    // Opposite hover-event order: the inner image still owns the affordance (deterministic).
    await hover(page, ["thumb", "thumbimg"]);
    await expect(page.locator("#imageAddBtn")).toBeVisible();
    await expect(page.locator("#linkAddBtn")).toBeHidden();
  });

  test("showing one layer's add button hides another layer's (single active affordance) (CMH-ANCHOR-01)", async ({ page }) => {
    await stage(page);
    await hover(page, ["plainimg"]);
    await expect(page.locator("#imageAddBtn")).toBeVisible();
    // Moving onto a different structural anchor (a link) reveals its button and clears the
    // previously-shown image button, so the two never coexist.
    await hover(page, ["plainlink"]);
    await expect(page.locator("#linkAddBtn")).toBeVisible();
    await expect(page.locator("#imageAddBtn")).toBeHidden();
  });

  test("the image affordance on a nested <a><img></a> still saves an image comment, not a link comment (CMH-ANCHOR-01)", async ({ page }) => {
    await stage(page);
    await hover(page, ["thumb", "thumbimg"]);
    await expect(page.locator("#imageAddBtn")).toBeVisible();
    await page.locator("#imageAddBtn").click();
    const composer = page.locator(".cm-composer").last();
    await expect(composer).toBeVisible();
    await composer.locator("textarea").fill("comment on the thumbnail image");
    await composer.locator('[data-act="save"]').click();
    await expect(composer).toBeHidden();
    await expect(page.locator("#commentList .cm-card")).toHaveCount(1);
    // The comment rings the inner image (anchorType image), not the wrapping link.
    await expect(page.locator("#thumbimg.cm-img-hl")).toHaveCount(1);
    await expect(page.locator("#thumb.cm-link-hl")).toHaveCount(0);
  });

  test("a cross-layer overlap (a link inside a heading) also resolves to one affordance - the inner link (CMH-ANCHOR-01)", async ({ page }) => {
    await stage(page);
    // Heading (82-toc.js, #headingAddBtn) is the outer layer; the inline link (31-links.js,
    // #linkAddBtn) is inner. Hovering the link fires both layers' mouseenter; the inner link
    // wins, proving the shared setActiveAdd() mechanism across a non-image/link pair.
    await hover(page, ["sec", "seclink"]);
    await expect(page.locator("#linkAddBtn")).toBeVisible();
    await expect(page.locator("#headingAddBtn")).toBeHidden();
  });

  test("the outer affordance recovers after the inner one is dismissed - no stale-ghost suppression (CMH-ANCHOR-01)", async ({ page }) => {
    await stage(page);
    // Hover the inner link inside the heading: the link wins, the heading button is hidden.
    await hover(page, ["sec", "seclink"]);
    await expect(page.locator("#linkAddBtn")).toBeVisible();
    // Leave the link; its 220ms hide timer hides the link button and clears the shared sentinel.
    await page.evaluate(() => {
      document.getElementById("seclink").dispatchEvent(new MouseEvent("mouseleave", { bubbles: false }));
    });
    await expect(page.locator("#linkAddBtn")).toBeHidden();
    // Now hover the enclosing heading afresh: its Add button must appear. Before the stale-ghost
    // fix, setActiveAdd() still saw the (hidden) inner link as active and, because the heading
    // contains it, suppressed the heading button forever.
    await hover(page, ["sec"]);
    await expect(page.locator("#headingAddBtn")).toBeVisible();
  });
});
