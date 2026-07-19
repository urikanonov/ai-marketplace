import { test, expect } from "@playwright/test";
import { fileUrl, ready, stageContent, openComposerFor, addTextComment } from "./helpers.js";

// CMH-SEL-02: the amber comment highlight must not fill the whole line box. It paints a centered
// band a little shorter than the line box (with box-decoration-break: clone), so a highlight that
// wraps across two lines shows clear vertical space between the lines instead of two touching
// bands. This holds for BOTH the composing preview (mark.cm-preview) and the saved highlight
// (mark.cm-hl), so the two look identical (only the preview's dashed outline differs).
function readBand(mark) {
  return mark.evaluate((el) => {
    const cs = getComputedStyle(el);
    // background-size resolves to "100% <bandpx>"; the second token is the painted band height.
    const first = cs.backgroundSize.split(",")[0].trim().split(/\s+/);
    return {
      bandPx: parseFloat(first[first.length - 1]),
      lineHeight: parseFloat(cs.lineHeight),
      bgImage: cs.backgroundImage,
      decoBreak: cs.webkitBoxDecorationBreak || cs.boxDecorationBreak,
    };
  });
}

test.describe("comment highlight vertical spacing (CMH-SEL-02)", () => {
  test("CMH-SEL-02: the saved highlight and the composing preview both paint a band shorter than the line box so wrapped lines get vertical spacing", async ({ page }) => {
    const { html } = stageContent(
      '<p id="para" style="font-size:24px;line-height:2;">This is a fairly long sentence of body prose that a reviewer highlights end to end so the mark spans real laid-out text and we can measure the painted band height against the line box height.</p>',
      { key: "cmh-hl-band" });
    await page.goto(fileUrl(html));
    await ready(page);

    // While the composer is open, the live PREVIEW highlight already paints the short band.
    const composer = await openComposerFor(page, "#para");
    const preview = page.locator("mark.cm-preview").first();
    await expect(preview).toHaveCount(1);
    const pv = await readBand(preview);
    expect(pv.bgImage).toContain("gradient");
    expect(pv.bandPx).toBeGreaterThan(0);
    expect(pv.bandPx).toBeLessThan(pv.lineHeight - 4);
    expect(pv.decoBreak).toBe("clone");

    // Saving converts the preview into the persisted highlight, which paints the same short band.
    await composer.locator("textarea").fill("band check note");
    await composer.locator('[data-act="save"]').click();
    await expect(composer).toHaveCount(0);
    const mark = page.locator("mark.cm-hl").first();
    await expect(mark).toHaveCount(1);
    const geom = await readBand(mark);
    expect(geom.bgImage).toContain("gradient");
    expect(geom.bandPx).toBeGreaterThan(0);
    expect(geom.bandPx).toBeLessThan(geom.lineHeight - 4);
    expect(geom.decoBreak).toBe("clone");
  });

  test("CMH-SEL-02: a highlight inside a code block keeps a solid full-height fill (no short band)", async ({ page }) => {
    const { html } = stageContent(
      '<pre><code id="code">const answer = computeTheAnswerFromAFairlyLongExpression(1, 2, 3, 4, 5);</code></pre>',
      { key: "cmh-hl-code" });
    await page.goto(fileUrl(html));
    await ready(page);
    await addTextComment(page, "#code", "code note");
    const mark = page.locator("pre mark.cm-hl, code mark.cm-hl").first();
    await expect(mark).toHaveCount(1);
    const cs = await mark.evaluate((el) => {
      const s = getComputedStyle(el);
      return { bgImage: s.backgroundImage, bgColor: s.backgroundColor };
    });
    // Code highlights carve out the band: no gradient image, a real (non-transparent) fill colour.
    expect(cs.bgImage).toBe("none");
    expect(cs.bgColor).not.toBe("rgba(0, 0, 0, 0)");
    expect(cs.bgColor).not.toBe("transparent");
  });
});
