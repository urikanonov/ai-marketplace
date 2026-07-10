// Kusto query blocks: framed figure, author-time KQL syntax highlighting, a safe
// Run-in-Kusto link, and the query still fully commentable as a code block.
import { test, expect } from "@playwright/test";
import { openInline, ready, fileUrl, INLINE, addTextComment, distinctCids, storedComments, allCids, markTextForCid } from "./helpers.js";

const FIG = "figure.cmh-kql";
const CODE = "figure.cmh-kql pre code.language-kusto";

test.describe("Kusto query blocks", () => {
  test("the demo ships exactly one framed KQL figure", async ({ page }) => {
    await openInline(page);
    await expect(page.locator(FIG)).toHaveCount(1);
    const frame = await page.locator(FIG).evaluate((el) => {
      const cs = getComputedStyle(el);
      return { border: cs.borderTopWidth, radius: cs.borderTopLeftRadius, overflow: cs.overflowX };
    });
    expect(parseFloat(frame.border)).toBeGreaterThan(0);
    expect(parseFloat(frame.radius)).toBeGreaterThan(0);
    // The inner <pre> carries no border of its own (the frame is the figure).
    const preBorder = await page.locator(`${FIG} pre`).evaluate((el) => getComputedStyle(el).borderTopWidth);
    expect(parseFloat(preBorder)).toBe(0);
    // Caption bar has a bottom divider.
    const capDivider = await page.locator(`${FIG} .cmh-kql-cap`).evaluate((el) => getComputedStyle(el).borderBottomWidth);
    expect(parseFloat(capDivider)).toBeGreaterThan(0);
  });

  test("the code is syntax-highlighted but textContent is the raw query", async ({ page }) => {
    await openInline(page);
    // Token spans exist for keywords, functions, strings/numbers, comments.
    expect(await page.locator(`${CODE} .cmh-kql-kw`).count()).toBeGreaterThan(0);
    expect(await page.locator(`${CODE} .cmh-kql-fn`).count()).toBeGreaterThan(0);
    expect(await page.locator(`${CODE} .cmh-kql-com`).count()).toBeGreaterThan(0);
    expect(await page.locator(`${CODE} .cmh-kql-str`).count()).toBeGreaterThan(0);
    expect(await page.locator(`${CODE} .cmh-kql-num`).count()).toBeGreaterThan(0);
    // A keyword span is actually colored (not the default text color).
    const kw = await page.locator(`${CODE} .cmh-kql-kw`).first().evaluate((el) => getComputedStyle(el).color);
    const plain = await page.locator(CODE).evaluate((el) => getComputedStyle(el).color);
    expect(kw).not.toBe(plain);
    // textContent is unchanged by the spans - the raw KQL is intact.
    const text = await page.locator(CODE).evaluate((el) => el.textContent);
    expect(text).toContain("| summarize");
    expect(text).toContain("| where");
    expect(text).not.toContain("<span");
  });

  test("the Run in Azure Data Explorer link is a safe ADX deep link inside cm-skip chrome", async ({ page }) => {
    await openInline(page);
    const a = page.locator("a.cmh-kql-run");
    await expect(a).toHaveCount(1);
    const info = await a.evaluate((el) => ({
      href: el.href, target: el.target, rel: el.rel, inSkip: !!el.closest(".cm-skip"),
    }));
    expect(info.href.startsWith("https://dataexplorer.azure.com/")).toBe(true);
    expect(info.target).toBe("_blank");
    expect(info.rel).toContain("noopener");
    expect(info.inSkip).toBe(true); // the link is not itself commentable
  });

  test("the highlighted query is still commentable as a code block", async ({ page }) => {
    await openInline(page);
    await addTextComment(page, CODE, "does this join scale?");
    expect(await distinctCids(page)).toBeGreaterThanOrEqual(1);
    // A mark landed inside the code, and the comment is classified as code/kusto.
    expect(await page.locator(`${CODE} mark.cm-hl`).count()).toBeGreaterThan(0);
    const stored = await storedComments(page);
    const c = stored[stored.length - 1];
    expect(c.isCode).toBe(true);
    expect(c.codeLanguage).toBe("kusto");
  });

  test("a comment over highlighted code survives reload (author-time spans are inert)", async ({ page }) => {
    // This is the load-bearing coexistence claim: baked-in token spans are static
    // markup, so a <mark> created across them must rehydrate at the same offsets.
    await openInline(page);
    await addTextComment(page, CODE, "reload me");
    const cidBefore = (await allCids(page))[0];
    const textBefore = await markTextForCid(page, cidBefore);
    expect(textBefore.length).toBeGreaterThan(0);
    await page.reload();
    await ready(page);
    const cids = await allCids(page);
    expect(cids.length).toBe(1);
    expect(await page.locator(`${CODE} mark.cm-hl`).count()).toBeGreaterThan(0);
    // The restored highlight covers the exact same text, across the token spans.
    expect(await markTextForCid(page, cids[0])).toBe(textBefore);
    // wrapRangeWithMark wraps each token's text node in its own <mark>, so a
    // selection crossing >=2 highlighted tokens restores as >=2 marks - proving the
    // multi-text-node path works over the baked-in spans after reload.
    expect(await page.locator(`${CODE} mark.cm-hl`).count()).toBeGreaterThan(1);
  });

  test("token colors adapt in dark theme", async ({ page }) => {
    await page.goto(fileUrl(INLINE) + "?clawpilotTheme=dark");
    await ready(page);
    expect(await page.evaluate(() => document.documentElement.getAttribute("data-theme"))).toBe("dark");
    const plain = await page.locator(CODE).evaluate((el) => getComputedStyle(el).color);
    // kw/fn/str/num all carry explicit dark overrides, so each differs from default text.
    for (const cls of ["cmh-kql-kw", "cmh-kql-fn", "cmh-kql-str", "cmh-kql-num"]) {
      const col = await page.locator(`${CODE} .${cls}`).first().evaluate((el) => getComputedStyle(el).color);
      expect(col, cls).not.toBe(plain);
    }
  });
});
