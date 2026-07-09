// Same-selection re-open: selecting the exact same text range (or diff region)
// that already has a comment re-opens it for editing instead of duplicating.
import { test, expect } from "@playwright/test";
import { openInline, ready } from "./helpers.js";

// Select an exact phrase within #commentRoot (skipping .cm-skip), the same way
// the runtime computes offsets, so the same phrase yields the same (start,end)
// even after a prior comment has wrapped text in a <mark>.
async function selectPhrase(page, phrase) {
  await page.evaluate((ph) => {
    const root = document.getElementById("commentRoot");
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode(n) {
        return n.parentElement && n.parentElement.closest(".cm-skip")
          ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT;
      },
    });
    let acc = "";
    const nodes = [];
    let n;
    while ((n = walker.nextNode())) { nodes.push([n, acc.length]); acc += n.data; }
    const idx = acc.indexOf(ph);
    if (idx < 0) throw new Error("phrase not found: " + ph);
    const locate = (pos) => {
      for (let i = nodes.length - 1; i >= 0; i--) if (nodes[i][1] <= pos) return [nodes[i][0], pos - nodes[i][1]];
      return [nodes[0][0], 0];
    };
    const [sn, so] = locate(idx);
    const [en, eo] = locate(idx + ph.length);
    const r = document.createRange();
    r.setStart(sn, so); r.setEnd(en, eo);
    const s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
    root.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, clientX: 40, clientY: 40 }));
  }, phrase);
  await expect(page.locator("#menuComment")).toBeVisible();
}

test("selecting the exact same text range re-opens its comment for editing", async ({ page }) => {
  await openInline(page);
  const phrase = "character offsets";
  await selectPhrase(page, phrase);
  await page.locator("#menuComment").click();
  const c1 = page.locator(".cm-composer").last();
  await c1.locator("textarea").fill("original note");
  await c1.locator('[data-act="save"]').click();
  await expect(c1).toBeHidden();
  await expect(page.locator("mark.cm-hl")).toHaveCount(1);

  // Same exact range again -> edit the existing comment (prefilled), not a new one.
  await selectPhrase(page, phrase);
  await page.locator("#menuComment").click();
  const c2 = page.locator(".cm-composer").last();
  await expect(c2.locator("textarea")).toHaveValue("original note");
  await c2.locator("textarea").fill("edited note");
  await c2.locator('[data-act="save"]').click();
  await expect(page.locator("mark.cm-hl")).toHaveCount(1); // still exactly one
  await expect(page.locator(".cm-card").filter({ hasText: "edited note" })).toHaveCount(1);
  // The edit persists (updatedAt won) and exactly one highlight reappears on reload.
  await page.reload();
  await ready(page);
  await expect(page.locator("mark.cm-hl")).toHaveCount(1);
  await expect(page.locator(".cm-card").filter({ hasText: "edited note" })).toHaveCount(1);
});

test("selecting a DIFFERENT text range makes a new comment", async ({ page }) => {
  await openInline(page);
  await selectPhrase(page, "character offsets");
  await page.locator("#menuComment").click();
  let c = page.locator(".cm-composer").last();
  await c.locator("textarea").fill("first");
  await c.locator('[data-act="save"]').click();
  await expect(c).toBeHidden();
  await selectPhrase(page, "localStorage");
  await page.locator("#menuComment").click();
  c = page.locator(".cm-composer").last();
  await c.locator("textarea").fill("second");
  await c.locator('[data-act="save"]').click();
  await expect(c).toBeHidden();
  await expect(page.locator("mark.cm-hl")).toHaveCount(2);
});
