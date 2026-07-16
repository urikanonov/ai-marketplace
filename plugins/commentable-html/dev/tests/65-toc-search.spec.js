import { test, expect } from "@playwright/test";
import { stageContent, fileUrl, ready, addTextComment } from "./helpers.js";

// Three tall, distinctly-worded sections so the side TOC renders (>= 2 items), scroll-spy
// moves between them, and a query matches exactly one section's body text.
const CONTENT = `
<section aria-labelledby="alpha"><h2 id="alpha">Alpha overview</h2>
  <p>Apple content describing the first area.</p>
  <p style="display:block;height:1400px">alpha filler</p></section>
<section aria-labelledby="beta"><h2 id="beta">Beta details</h2>
  <p>Banana content describing the second area.</p>
  <p style="display:block;height:1400px">beta filler</p></section>
<section aria-labelledby="gamma"><h2 id="gamma">Gamma appendix</h2>
  <p id="gp">Cherry content mentioning the unique word zebra.</p>
  <p style="display:block;height:1400px">gamma filler</p></section>
`;

// The sections carry no id (only their headings do), so address each by its heading.
const sec = (page, hid) => page.locator(`#commentRoot section:has(#${hid})`);

async function openDoc(page) {
  const { html } = stageContent(CONTENT, { key: "cmh-toc-search-test", source: "toc-search.html" });
  await page.setViewportSize({ width: 1600, height: 800 });
  await page.goto(fileUrl(html));
  await ready(page);
  const toc = page.locator("#cmSideToc");
  await expect(toc).toBeVisible();
  return toc;
}

test.describe("side-TOC search and aria-current", () => {
  test("the active section link carries aria-current=location and it tracks scroll (CMH-TOC-08)", async ({ page }) => {
    const toc = await openDoc(page);
    const current = toc.locator('.cm-side-toc-list a[aria-current="location"]');
    // Exactly one link is marked current, and at the top it is the first section.
    await expect(current).toHaveCount(1);
    await expect(current).toContainText("Alpha overview");
    // Scrolling a later section to the top moves the marker (and it stays unique).
    await page.evaluate(() => document.getElementById("gamma").scrollIntoView());
    await expect(toc.locator('.cm-side-toc-list a[aria-current="location"]')).toHaveCount(1);
    await expect(toc.locator('.cm-side-toc-list a[aria-current="location"]')).toContainText("Gamma appendix");
  });

  test("the search box filters visible sections by heading and body text, Escape clears (CMH-TOC-09)", async ({ page }) => {
    const toc = await openDoc(page);
    const search = toc.locator(".cm-side-toc-search");
    await expect(search).toBeVisible();

    // A body-only word (in Gamma) hides the other sections and their TOC entries.
    await search.fill("zebra");
    await expect(sec(page, "gamma")).toBeVisible();
    await expect(sec(page, "alpha")).toBeHidden();
    await expect(sec(page, "beta")).toBeHidden();
    await expect(toc.locator('.cm-side-toc-list a[href="#gamma"]')).toBeVisible();
    await expect(toc.locator('.cm-side-toc-list a[href="#alpha"]')).toBeHidden();

    // A heading word matches too.
    await search.fill("Beta");
    await expect(sec(page, "beta")).toBeVisible();
    await expect(sec(page, "alpha")).toBeHidden();

    // Escape clears the filter and restores every section.
    await search.press("Escape");
    await expect(search).toHaveValue("");
    await expect(sec(page, "alpha")).toBeVisible();
    await expect(sec(page, "beta")).toBeVisible();
    await expect(sec(page, "gamma")).toBeVisible();
  });

  test("navigating to a filtered-out section reveals it (CMH-TOC-09)", async ({ page }) => {
    const toc = await openDoc(page);
    await toc.locator(".cm-side-toc-search").fill("zebra");
    await expect(sec(page, "alpha")).toBeHidden();
    // A deep-link to a hidden section must reveal it rather than scroll to nothing.
    await page.evaluate(() => { location.hash = "#alpha"; });
    await expect(sec(page, "alpha")).toBeVisible();
  });

  test("the filter box hides when the side menu is collapsed (CMH-TOC-09)", async ({ page }) => {
    const toc = await openDoc(page);
    await expect(toc.locator(".cm-side-toc-search")).toBeVisible();
    await toc.locator(".cm-side-toc-toggle").click();
    await expect(toc.locator(".cm-side-toc-search")).toBeHidden();
  });

  test("jumping to a comment inside a filtered-out section reveals it (CMH-TOC-09)", async ({ page }) => {
    const toc = await openDoc(page);
    // Comment on text in Gamma, then filter to a query that matches only Alpha (hiding Gamma).
    await addTextComment(page, "#gp", "note on cherry");
    await toc.locator(".cm-side-toc-search").fill("Apple");
    await expect(sec(page, "gamma")).toBeHidden();
    // Activating the comment card must clear the filter so the highlight is laid out and reachable.
    await page.locator(".cm-card").first().click();
    await expect(sec(page, "gamma")).toBeVisible();
    await expect(toc.locator(".cm-side-toc-search")).toHaveValue("");
  });

  test("a filtered-out flat heading entry never receives aria-current (CMH-TOC-09)", async ({ page }) => {
    // Flat headings with no <section> wrapper: filtering hides the menu row (not the body), and the
    // scroll-spy must never mark a hidden row current.
    const FLAT = `<h2 id="fone">Flat one apple</h2><p style="display:block;height:1400px">a</p>
      <h2 id="ftwo">Flat two banana</h2><p style="display:block;height:1400px">b</p>`;
    const { html } = stageContent(FLAT, { key: "cmh-toc-flat", source: "flat.html" });
    await page.setViewportSize({ width: 1600, height: 800 });
    await page.goto(fileUrl(html));
    await ready(page);
    const toc = page.locator("#cmSideToc");
    await expect(toc).toBeVisible();
    await toc.locator(".cm-side-toc-search").fill("apple");
    // The non-matching row is hidden, and no hidden row is ever aria-current.
    await expect(toc.locator('.cm-side-toc-list a[href="#ftwo"]')).toBeHidden();
    await expect(toc.locator('.cm-side-toc-list li.cm-toc-li-hidden a[aria-current="location"]')).toHaveCount(0);
    // A query matching nothing leaves no current link at all.
    await toc.locator(".cm-side-toc-search").fill("nomatchxyz");
    await expect(toc.locator('.cm-side-toc-list a[aria-current="location"]')).toHaveCount(0);
  });
});
