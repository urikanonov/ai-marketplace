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

// The shape a generated multi-level report has: an author `nav.cm-toc` whose labels carry NO
// number (generate_toc strips a redundant leading one, CMH-TOC-10) while the headings themselves
// display the document's own hierarchical numbering, and a single wrapper <section> around the
// whole body rather than one <section> per heading.
const NESTED = `
<nav class="cm-toc"><ol>
  <li><a href="#risk">Risk register</a><ol>
    <li><a href="#vendor">Vendor exposure</a><ol>
      <li><a href="#audit">Audit cadence</a></li>
    </ol></li>
    <li><a href="#mitigation">Mitigation plan</a></li>
  </ol></li>
  <li><a href="#rollout">Rollout</a></li>
</ol></nav>
<section id="wrap">
  <h2 id="risk">10. Risk register</h2>
  <p>Register overview prose.</p>
  <h3 id="vendor">10.3 Vendor exposure</h3>
  <p>Third-party surface notes.</p>
  <h4 id="audit">10.3.1 Audit cadence</h4>
  <p>Walkthrough every quarter.</p>
  <h3 id="mitigation">10.4 Mitigation plan</h3>
  <p>Controls and owners.</p>
  <h2 id="rollout">11. Rollout</h2>
  <p>Sequencing notes.</p>
</section>`;

async function openNested(page, content = NESTED, key = "cmh-toc-nested") {
  const { html } = stageContent(content, { key, source: "nested.html" });
  await page.setViewportSize({ width: 1600, height: 800 });
  await page.goto(fileUrl(html));
  await ready(page);
  const toc = page.locator("#cmSideToc");
  await expect(toc).toBeVisible();
  return toc;
}

const tocRow = (toc, id) => toc.locator(`.cm-side-toc-list li:has(> a[href="#${id}"])`);
const tocLink = (toc, id) => toc.locator(`.cm-side-toc-list a[href="#${id}"]`);
const tocNum = (toc, id) => tocLink(toc, id).locator(".cm-toc-num");
const linkLeft = async (toc, id) => (await tocLink(toc, id).boundingBox()).x;

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

  test("a serializable closed shadow heading supplies its runtime TOC label (CMH-VAL-23)", async ({ page }) => {
    const { html } = stageContent(
      '<h2 id="shadow-heading"><template shadowrootmode="closed" shadowrootserializable>'
      + "Shadow section</template></h2>"
      + '<h2 id="light-heading">Light section</h2>',
      { key: "cmh-shadow-toc-label" },
    );
    await page.setViewportSize({ width: 1600, height: 800 });
    await page.goto(fileUrl(html));
    await ready(page);
    const links = page.locator("#cmSideToc .cm-side-toc-list a");
    await expect(links).toHaveCount(2);
    await expect(links.nth(0)).toContainText("Shadow section");
    await expect(links.nth(0)).toHaveAttribute("href", "#shadow-heading");
  });

  test("runtime TOC labels ignore invalid and duplicate shadow declarations (CMH-VAL-23)", async ({ page }) => {
    const { html } = stageContent(
      '<h2 id="invalid-shadow"><template shadowrootmode="bogus">Invalid hidden</template></h2>'
      + '<h2 id="valid-shadow"><template shadowrootmode="open" shadowrootserializable>'
      + "Visible shadow</template><template shadowrootmode=\"closed\">Duplicate hidden</template></h2>"
      + '<h2 id="light-heading">Light section</h2>',
      { key: "cmh-shadow-toc-validity" },
    );
    await page.setViewportSize({ width: 1600, height: 800 });
    await page.goto(fileUrl(html));
    await ready(page);
    const invalid = page.locator('#cmSideToc a[href="#invalid-shadow"]');
    const valid = page.locator('#cmSideToc a[href="#valid-shadow"]');
    await expect(invalid).not.toContainText("Invalid hidden");
    await expect(valid).toContainText("Visible shadow");
    await expect(valid).not.toContainText("Duplicate hidden");
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

  test("the side menu keeps the document's own section numbering and nests subsections (CMH-TOC-11)", async ({ page }) => {
    const toc = await openNested(page);
    // Every nav entry carries the number its heading displays - a subsection is 10.3, never a
    // flat sequential 2 - and a deeper heading is never numbered as a top-level peer.
    await expect(tocNum(toc, "risk")).toHaveText("10");
    await expect(tocNum(toc, "vendor")).toHaveText("10.3");
    await expect(tocNum(toc, "audit")).toHaveText("10.3.1");
    await expect(tocNum(toc, "mitigation")).toHaveText("10.4");
    await expect(tocNum(toc, "rollout")).toHaveText("11");
    // Hierarchy is visible: each level is indented further than its parent.
    await expect(tocRow(toc, "vendor")).toHaveClass(/is-sub/);
    await expect(tocRow(toc, "audit")).toHaveClass(/is-level-3/);
    const top = await linkLeft(toc, "risk");
    const sub = await linkLeft(toc, "vendor");
    const subSub = await linkLeft(toc, "audit");
    expect(sub).toBeGreaterThan(top);
    expect(subSub).toBeGreaterThan(sub);
    expect(await linkLeft(toc, "rollout")).toBeCloseTo(top, 0);
  });

  test("an unnumbered nested document is numbered hierarchically, not flat (CMH-TOC-11)", async ({ page }) => {
    // No author numbers anywhere (nav or headings) and no author nav: the h2/h3/h4 fallback
    // computes 1, 1.1, 1.1.1 from the real heading depth instead of 1, 2, 3.
    const PLAIN = `
      <h2 id="one">Findings</h2><p>lead</p>
      <h3 id="one-a">Signals</h3><p>detail</p>
      <h4 id="one-a-i">Sampling</h4><p>detail</p>
      <h2 id="two">Next steps</h2><p>lead</p>`;
    const toc = await openNested(page, PLAIN, "cmh-toc-plain");
    await expect(tocNum(toc, "one")).toHaveText("1");
    await expect(tocNum(toc, "one-a")).toHaveText("1.1");
    await expect(tocNum(toc, "one-a-i")).toHaveText("1.1.1");
    await expect(tocNum(toc, "two")).toHaveText("2");
    expect(await linkLeft(toc, "one-a-i")).toBeGreaterThan(await linkLeft(toc, "one-a"));
  });

  test("the filter narrows the navigation to matching headings and keeps ancestor context (CMH-TOC-09)", async ({ page }) => {
    const toc = await openNested(page);
    const search = toc.locator(".cm-side-toc-search");

    // Case-insensitive, and it narrows: only the matching heading and the ancestors that place
    // it stay listed, even though every heading shares one wrapper <section>.
    await search.fill("CADENCE");
    await expect(tocRow(toc, "audit")).toBeVisible();
    await expect(tocRow(toc, "vendor")).toBeVisible();
    await expect(tocRow(toc, "risk")).toBeVisible();
    await expect(tocRow(toc, "mitigation")).toBeHidden();
    await expect(tocRow(toc, "rollout")).toBeHidden();
    // The wrapper section still holds a visible entry, so it is never hidden out from under it.
    await expect(page.locator("#wrap")).toBeVisible();

    // Body text still matches, and it belongs to the heading that owns it - not to every
    // heading that happens to share the wrapper.
    await search.fill("controls");
    await expect(tocRow(toc, "mitigation")).toBeVisible();
    await expect(tocRow(toc, "risk")).toBeVisible();
    await expect(tocRow(toc, "audit")).toBeHidden();
    await expect(tocRow(toc, "rollout")).toBeHidden();

    // Clearing restores the complete tree.
    await search.press("Escape");
    await expect(search).toHaveValue("");
    for (const id of ["risk", "vendor", "audit", "mitigation", "rollout"]) {
      await expect(tocRow(toc, id)).toBeVisible();
    }
  });
});
